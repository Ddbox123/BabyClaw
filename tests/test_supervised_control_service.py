import threading
import time
from pathlib import Path

import pytest

from core.web.services import supervised_control_service as service


@pytest.fixture(autouse=True)
def reset_supervised_run_state(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(service, "_runtime_manager_live_control_enabled", lambda: False)
    with service._RUN_STATE_LOCK:
        service._RUN_STATES.clear()
        service._RUN_CONTROLLERS.clear()
        service._ACTIVE_RUN_ID = None
    with service._RUN_SUBSCRIBERS_LOCK:
        service._RUN_SUBSCRIBERS.clear()
    yield
    with service._RUN_STATE_LOCK:
        service._RUN_STATES.clear()
        service._RUN_CONTROLLERS.clear()
        service._ACTIVE_RUN_ID = None
    with service._RUN_SUBSCRIBERS_LOCK:
        service._RUN_SUBSCRIBERS.clear()


def _seed_running_run() -> str:
    context = {
        "runId": "web-supervised-test",
        "lang": "en",
        "sourceKind": "bundle",
        "datasetName": "",
        "datasetLimit": None,
        "bundleName": "manual_bundle",
        "keepWorktree": False,
        "startedAt": "2026-05-18T12:00:00Z",
    }
    state = service._initial_run_state(context)
    state["status"] = "running"
    state["currentPhase"] = "running"
    state["runtimeStatus"] = "running"
    state["sessionId"] = "supervised_session"
    state["caseTotal"] = 2
    state["currentCaseIndex"] = 1
    state["currentCaseId"] = "case_1"
    state["currentRole"] = "candidate"
    with service._RUN_STATE_LOCK:
        service._RUN_STATES[context["runId"]] = state
        service._RUN_CONTROLLERS[context["runId"]] = service._SupervisedRunController()
        service._ACTIVE_RUN_ID = context["runId"]
    return context["runId"]


def _wait_until(predicate, *, timeout: float = 1.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("Timed out waiting for condition")


def test_supervised_checkpoint_pauses_then_resumes():
    run_id = _seed_running_run()
    result = {"error": None}

    pause_snapshot = service.request_pause_supervised_run(run_id)
    assert pause_snapshot["pauseRequested"] is True
    assert pause_snapshot["status"] == "running"
    assert pause_snapshot["currentPhase"] == "pause_requested"

    thread = threading.Thread(
        target=lambda: _checkpoint_in_thread(run_id, result),
        daemon=True,
    )
    thread.start()

    _wait_until(lambda: service.get_supervised_run_snapshot(run_id)["status"] == "paused")
    paused_snapshot = service.get_supervised_run_snapshot(run_id)
    assert paused_snapshot["currentPhase"] == "paused"
    assert paused_snapshot["runtimeStatus"] == "paused"

    resume_snapshot = service.request_resume_supervised_run(run_id)
    assert resume_snapshot["pauseRequested"] is False

    thread.join(timeout=1.0)
    assert not thread.is_alive()
    assert result["error"] is None
    running_snapshot = service.get_supervised_run_snapshot(run_id)
    assert running_snapshot["status"] == "running"


def test_supervised_checkpoint_stops_at_safe_boundary():
    run_id = _seed_running_run()

    stop_snapshot = service.request_stop_supervised_run(run_id)
    assert stop_snapshot["status"] == "stopping"
    assert stop_snapshot["stopRequested"] is True

    with pytest.raises(service._SupervisedRunInterrupted):
        service._checkpoint_supervised_run(run_id, {"phase": "case_boundary", "case_id": "case_1"})

    final_snapshot = service.get_supervised_run_snapshot(run_id)
    assert final_snapshot["status"] == "cancelled"
    assert service.get_active_supervised_run() is None


def test_supervised_checkpoint_stops_at_role_boundary_before_next_role():
    run_id = _seed_running_run()

    stop_snapshot = service.request_stop_supervised_run(run_id)
    assert stop_snapshot["status"] == "stopping"
    assert stop_snapshot["stopRequested"] is True

    with pytest.raises(service._SupervisedRunInterrupted):
        service._checkpoint_supervised_run(
            run_id,
            {"phase": "role_boundary", "case_id": "case_1", "role": "baseline"},
        )

    final_snapshot = service.get_supervised_run_snapshot(run_id)
    assert final_snapshot["status"] == "cancelled"
    assert final_snapshot["currentRole"] == "candidate"
    assert service.get_active_supervised_run() is None


def test_handle_progress_event_updates_current_case_io_snapshot():
    run_id = _seed_running_run()

    service._handle_progress_event(
        run_id,
        {
            "event": "role_start",
            "case_index": 1,
            "case_total": 2,
            "case_id": "case_1",
            "role": "candidate",
            "scenario": "transaction",
            "mode": "single_turn",
            "prompt": "compare the candidate behavior",
        },
    )
    service._handle_progress_event(
        run_id,
        {
            "event": "role_live",
            "case_index": 1,
            "case_total": 2,
            "case_id": "case_1",
            "role": "candidate",
            "scenario": "transaction",
            "mode": "single_turn",
            "prompt": "compare the candidate behavior",
            "conversation_path": "log_info/conversation_case_1.jsonl",
            "latest_input": "compare the candidate behavior",
            "latest_output": "assistant produced a live update",
            "latest_output_kind": "assistant",
            "latest_output_label": "assistant",
            "updated_at": "2026-05-19T12:00:03Z",
            "transcript": [
                {
                    "timestamp": "2026-05-19T12:00:01Z",
                    "kind": "input",
                    "label": "prompt",
                    "content": "compare the candidate behavior",
                },
                {
                    "timestamp": "2026-05-19T12:00:03Z",
                    "kind": "assistant",
                    "label": "assistant",
                    "content": "assistant produced a live update",
                },
            ],
        },
    )

    snapshot = service.get_supervised_run_snapshot(run_id)

    assert snapshot["currentCasePrompt"] == "compare the candidate behavior"
    assert snapshot["currentCaseScenario"] == "transaction"
    assert snapshot["currentCaseMode"] == "single_turn"
    assert snapshot["currentCaseIo"]["latestOutput"] == "assistant produced a live update"
    assert snapshot["currentCaseIo"]["latestOutputKind"] == "assistant"
    assert snapshot["currentCaseIo"]["transcript"][0]["kind"] == "input"
    assert snapshot["latestMessage"] == "assistant produced a live update"
    assert snapshot["eventTail"][-1]["event"] == "role_start"


def _checkpoint_in_thread(run_id: str, result: dict[str, object]) -> None:
    try:
        service._checkpoint_supervised_run(run_id, {"phase": "case_boundary", "case_id": "case_1"})
    except Exception as exc:  # pragma: no cover - surfaced through assertion
        result["error"] = exc


def test_runtime_manager_start_supervised_run_submits_command(monkeypatch):
    calls: list[object] = []
    snapshot = {"runId": "web-supervised-managed", "status": "queued"}

    monkeypatch.setattr(service, "_runtime_manager_live_control_enabled", lambda: True)
    monkeypatch.setattr(service, "_ensure_runtime_manager_daemon", lambda: calls.append("ensure"))
    monkeypatch.setattr(
        service,
        "submit_command",
        lambda command_type, args=None, requested_by="unknown": calls.append((command_type, args, requested_by)) or {"commandId": "cmd-1"},
    )
    monkeypatch.setattr(service, "wait_for_result", lambda command_id: {"ok": True, "snapshot": snapshot})

    result = service.start_supervised_run({"sourceKind": "bundle", "bundleName": "manual_bundle"})

    assert result == snapshot
    assert calls[0] == "ensure"
    assert calls[1] == (
        "start_supervised_run",
        {"payload": {"sourceKind": "bundle", "bundleName": "manual_bundle"}},
        "web_ui",
    )


def test_runtime_manager_get_active_supervised_run_reads_store(monkeypatch):
    snapshot = {"runId": "web-supervised-managed", "status": "running"}

    monkeypatch.setattr(service, "_runtime_manager_live_control_enabled", lambda: True)
    monkeypatch.setattr(service, "load_manager_active_run_snapshot", lambda kind: snapshot if kind == "supervised" else None)

    result = service.get_active_supervised_run()

    assert result is not None
    assert result["runId"] == snapshot["runId"]
    assert result["status"] == snapshot["status"]
    assert result["actionStates"]["pause"]["enabled"] is True


def test_runtime_manager_live_control_requires_matching_project_root(monkeypatch, tmp_path):
    monkeypatch.setattr(service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        service,
        "load_runtime_snapshot",
        lambda: {"daemonRunning": True, "projectRoot": str(Path.cwd())},
        raising=False,
    )

    from core.runtime_manager import daemon as runtime_daemon

    monkeypatch.setattr(
        runtime_daemon,
        "load_runtime_snapshot",
        lambda: {"daemonRunning": True, "projectRoot": str(Path.cwd())},
    )

    assert service._runtime_manager_live_control_enabled() is False
