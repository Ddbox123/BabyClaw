import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.routes import evolution as evolution_routes
from core.web.services import self_evolution_control_service as service


client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


@pytest.fixture(autouse=True)
def reset_self_evolution_run_state(monkeypatch: pytest.MonkeyPatch):
    manager_store: dict[str, dict[str, dict]] = {"self": {}, "supervised": {}}
    manager_index: dict[str, dict[str, str]] = {
        "self": {"activeRunId": "", "latestRunId": ""},
        "supervised": {"activeRunId": "", "latestRunId": ""},
    }

    def fake_persist_manager_run_snapshot(kind: str, snapshot: dict, *, active_run_id: str = "") -> dict:
        run_id = str(snapshot.get("runId") or "").strip()
        payload = copy.deepcopy(snapshot)
        manager_store.setdefault(kind, {})[run_id] = payload
        manager_index.setdefault(kind, {"activeRunId": "", "latestRunId": ""})
        manager_index[kind]["activeRunId"] = str(active_run_id or "").strip()
        manager_index[kind]["latestRunId"] = run_id
        return copy.deepcopy(payload)

    def fake_load_manager_run_snapshot(kind: str, run_id: str) -> dict | None:
        payload = manager_store.get(kind, {}).get(str(run_id or "").strip())
        return copy.deepcopy(payload) if payload is not None else None

    def fake_load_manager_active_run_snapshot(kind: str) -> dict | None:
        active_run_id = manager_index.get(kind, {}).get("activeRunId", "")
        return fake_load_manager_run_snapshot(kind, active_run_id)

    def fake_load_manager_latest_run_snapshot(kind: str) -> dict | None:
        latest_run_id = manager_index.get(kind, {}).get("latestRunId", "")
        return fake_load_manager_run_snapshot(kind, latest_run_id)

    monkeypatch.setattr(service, "_runtime_manager_live_control_enabled", lambda: False)
    monkeypatch.setattr(service, "persist_manager_run_snapshot", fake_persist_manager_run_snapshot)
    monkeypatch.setattr(service, "load_manager_run_snapshot", fake_load_manager_run_snapshot)
    monkeypatch.setattr(service, "load_manager_active_run_snapshot", fake_load_manager_active_run_snapshot)
    monkeypatch.setattr(service, "load_manager_latest_run_snapshot", fake_load_manager_latest_run_snapshot)
    with service._RUN_STATE_LOCK:
        service._RUN_STATES.clear()
        service._RUN_INTERNALS.clear()
        service._ACTIVE_RUN_ID = None
    with service._RUN_SUBSCRIBERS_LOCK:
        service._RUN_SUBSCRIBERS.clear()
    yield
    with service._RUN_STATE_LOCK:
        service._RUN_STATES.clear()
        service._RUN_INTERNALS.clear()
        service._ACTIVE_RUN_ID = None
    with service._RUN_SUBSCRIBERS_LOCK:
        service._RUN_SUBSCRIBERS.clear()


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_latest_self_evolution_run_decorates_runtime_attention(monkeypatch):
    run_id = "web-self-live"
    with service._RUN_STATE_LOCK:
        service._RUN_STATES[run_id] = {
            "runId": run_id,
            "goal": "autonomous patch",
            "status": "running",
            "phase": "running",
            "startedAt": "2026-05-18T12:00:00Z",
            "updatedAt": "2026-05-18T12:00:01Z",
            "finishedAt": "",
            "latestMessage": "latest message",
            "currentGoal": "",
            "currentTask": "",
            "lastToolName": "",
            "runtimeStatus": "",
            "toolCallCount": 0,
            "summary": "",
            "error": "",
            "cancelRequested": False,
            "cancelRequestedAt": "",
            "stopReason": "",
            "readingTask": "",
            "readingHint": "",
            "readingSufficiency": "",
            "convergenceState": "",
            "nextToolIntent": "",
            "rollback": {
                "status": "idle",
                "reason": "",
                "baseRev": "",
                "rolledBackAt": "",
                "entryCount": 0,
                "touchedFiles": [],
                "conflictFiles": [],
                "blockedHint": "",
            },
        }
        service._ACTIVE_RUN_ID = run_id
    monkeypatch.setattr(
        service,
        "_load_runtime_state",
        lambda: {
            "current_goal": "inspect guidance",
            "last_tool_name": "rg",
            "runtime_status": "thinking",
            "updated_at": "2026-05-18T12:00:02Z",
        },
    )
    monkeypatch.setattr(
        service,
        "get_session_state",
        lambda: SimpleNamespace(
            get_attention_snapshot=lambda: {
                "reading_task": "Read supervised control flow",
                "reading_recommendation": "Check the latest pause event first",
                "reading_sufficiency": "insufficient",
                "convergence_state": "exploring",
                "next_tool_intent": "Open the control service module",
                "stop_reason": "",
            }
        ),
    )

    payload = service.get_latest_self_evolution_run()

    assert payload is not None
    assert payload["phase"] == "reading"
    assert payload["currentGoal"] == "inspect guidance"
    assert payload["currentTask"] == "Read supervised control flow"
    assert payload["readingHint"] == "Check the latest pause event first"
    assert payload["nextToolIntent"] == "Open the control service module"


def _seed_terminal_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, current_text: str = "after\n") -> dict:
    monkeypatch.setattr(service, "PROJECT_ROOT", tmp_path)
    run_id = "web-self-test"
    target_path = tmp_path / "web" / "src" / "demo.txt"
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(current_text, encoding="utf-8", newline="\n")

    backup_path = tmp_path / "workspace" / "self_evolution" / "rollback" / run_id / "files" / "web" / "src" / "demo.txt"
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    backup_path.write_text("before\n", encoding="utf-8", newline="\n")
    before_hash = hashlib.sha256(backup_path.read_bytes()).hexdigest()
    after_hash = hashlib.sha256(target_path.read_bytes()).hexdigest()

    touched_file = {
        "path": "web/src/demo.txt",
        "changeType": "modified",
        "trackedBefore": True,
        "existedBefore": True,
        "statusAfter": "M",
        "preHash": before_hash,
        "postHash": after_hash,
        "postExists": True,
        "conflict": False,
        "conflictReason": "",
    }
    rollback_state = {
        "status": "available",
        "reason": "ready",
        "baseRev": "abcdef123456",
        "rolledBackAt": "",
        "entryCount": 1,
        "touchedFiles": [touched_file],
        "conflictFiles": [],
        "blockedHint": "",
    }
    manifest_path = tmp_path / "workspace" / "self_evolution" / "rollback" / run_id / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "version": 1,
                "runId": run_id,
                "baseRev": "abcdef123456",
                "display": rollback_state,
                "entries": [
                    {
                        **touched_file,
                        "restoreSource": "backup",
                        "backupPath": str(backup_path),
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    state = {
        "runId": run_id,
        "goal": "网页回滚测试",
        "status": "done",
        "phase": "done",
        "startedAt": "2026-05-18T11:55:00Z",
        "updatedAt": "2026-05-18T12:00:00Z",
        "finishedAt": "2026-05-18T12:00:00Z",
        "latestMessage": "done",
        "currentGoal": "网页回滚测试",
        "lastToolName": "apply_patch",
        "runtimeStatus": "success",
        "toolCallCount": 1,
        "summary": "done",
        "error": "",
        "cancelRequested": False,
        "cancelRequestedAt": "",
        "stopReason": "",
        "rollback": rollback_state,
        "artifacts": {
            "rollbackDir": str(manifest_path.parent),
            "manifestPath": str(manifest_path),
        },
    }

    with service._RUN_STATE_LOCK:
        service._RUN_STATES[run_id] = copy.deepcopy(state)
        service._ACTIVE_RUN_ID = None

    return {
        "run_id": run_id,
        "target_path": target_path,
    }


def test_rollback_self_evolution_run_restores_files_from_manifest(tmp_path, monkeypatch):
    seeded = _seed_terminal_run(tmp_path, monkeypatch)

    snapshot = service.rollback_self_evolution_run(seeded["run_id"])

    assert seeded["target_path"].read_text(encoding="utf-8") == "before\n"
    assert snapshot["rollback"]["status"] == "rolled_back"
    assert snapshot["rollback"]["rolledBackAt"]


def test_rollback_self_evolution_run_blocks_when_file_changed_after_run(tmp_path, monkeypatch):
    seeded = _seed_terminal_run(tmp_path, monkeypatch)
    seeded["target_path"].write_text("externally changed\n", encoding="utf-8", newline="\n")

    snapshot = service.rollback_self_evolution_run(seeded["run_id"])

    assert seeded["target_path"].read_text(encoding="utf-8") == "externally changed\n"
    assert snapshot["rollback"]["status"] == "blocked"
    assert snapshot["rollback"]["conflictFiles"][0]["path"] == "web/src/demo.txt"


def test_self_evolution_latest_run_route(monkeypatch):
    monkeypatch.setattr(
        evolution_routes,
        "get_latest_self_evolution_run",
        lambda: {"runId": "web-self-latest", "status": "done"},
    )

    response = client.get("/api/evolution/self/latest-run")

    assert response.status_code == 200
    assert response.json()["runId"] == "web-self-latest"


def test_self_evolution_run_events_route(monkeypatch):
    monkeypatch.setattr(
        evolution_routes,
        "get_self_evolution_run_snapshot",
        lambda run_id: {"runId": run_id, "status": "running"},
    )
    monkeypatch.setattr(
        evolution_routes,
        "stream_self_evolution_run_events",
        lambda run_id, initial_snapshot=None: iter(
            [f'event: self_evolution_run\ndata: {{"runId": "{run_id}", "status": "running"}}\n\n']
        ),
    )

    response = client.get("/api/evolution/self/runs/web-self-stream/events")

    assert response.status_code == 200
    assert "self_evolution_run" in response.text
    assert "web-self-stream" in response.text


def test_runtime_manager_latest_self_evolution_run_reads_store(monkeypatch):
    snapshot = {"runId": "web-self-managed", "status": "running"}

    monkeypatch.setattr(service, "_runtime_manager_live_control_enabled", lambda: True)
    monkeypatch.setattr(service, "load_manager_latest_run_snapshot", lambda kind: snapshot if kind == "self" else None)
    monkeypatch.setattr(service, "load_manager_active_run_snapshot", lambda kind: snapshot if kind == "self" else None)

    result = service.get_latest_self_evolution_run()

    assert result is not None
    assert result["runId"] == snapshot["runId"]
    assert result["status"] == snapshot["status"]
    assert result["runSemantics"]["runStatus"] == "running"
    assert result["actionStates"]["pause"]["enabled"] is True


def test_runtime_manager_latest_self_evolution_run_closes_orphaned_locked_snapshot(monkeypatch):
    snapshot = {
        "runId": "web-self-orphan",
        "goal": "orphan",
        "status": "queued",
        "phase": "queued",
        "startedAt": "2026-05-18T12:00:00Z",
        "updatedAt": "2026-05-18T12:00:00Z",
        "finishedAt": "",
        "latestMessage": "queued",
        "currentGoal": "orphan",
        "lastToolName": "",
        "runtimeStatus": "working",
        "toolCallCount": 0,
        "summary": "",
        "error": "",
        "cancelRequested": False,
        "cancelRequestedAt": "",
        "stopReason": "",
        "controlAction": "",
        "controlRequestedAt": "",
        "messages": [],
        "turnCount": 0,
        "resumeCount": 0,
        "rollback": {
            "status": "unavailable",
            "reason": "",
            "baseRev": "",
            "rolledBackAt": "",
            "entryCount": 0,
            "touchedFiles": [],
            "conflictFiles": [],
            "blockedHint": "",
        },
    }
    persisted: dict[str, object] = {}

    monkeypatch.setattr(service, "_runtime_manager_live_control_enabled", lambda: True)
    monkeypatch.setattr(service, "load_manager_latest_run_snapshot", lambda kind: copy.deepcopy(snapshot) if kind == "self" else None)
    monkeypatch.setattr(service, "load_manager_active_run_snapshot", lambda kind: None)

    def fake_persist(kind: str, payload: dict, *, active_run_id: str = "") -> dict:
        persisted["kind"] = kind
        persisted["payload"] = copy.deepcopy(payload)
        persisted["active_run_id"] = active_run_id
        return copy.deepcopy(payload)

    monkeypatch.setattr(service, "persist_manager_run_snapshot", fake_persist)

    result = service.get_latest_self_evolution_run()

    assert result is not None
    assert result["status"] == "cancelled"
    assert result["phase"] == "cancelled"
    assert result["runtimeStatus"] == "idle"
    assert result["cancelRequested"] is True
    assert result["finishedAt"]
    assert result["messages"][-1]["role"] == "assistant"
    assert persisted["kind"] == "self"
    assert persisted["active_run_id"] == ""
    assert persisted["payload"]["status"] == "cancelled"


def test_runtime_manager_start_self_evolution_still_blocks_running_sessions(monkeypatch):
    monkeypatch.setattr(service, "_runtime_manager_live_control_enabled", lambda: True)
    monkeypatch.setattr(
        service,
        "get_workbench_contract",
        lambda: {"modeAvailability": {"self_evolution": True}},
    )
    monkeypatch.setattr(service, "has_running_sessions", lambda: True)
    monkeypatch.setattr(service, "get_active_supervised_run", lambda: None)

    with pytest.raises(service.SelfEvolutionRunBusyError):
        service.start_self_evolution_run({"goal": "managed"})


def test_runtime_manager_live_control_requires_matching_project_root(monkeypatch, tmp_path):
    monkeypatch.setattr(service, "PROJECT_ROOT", tmp_path)

    from core.runtime_manager import daemon as runtime_daemon

    monkeypatch.setattr(
        runtime_daemon,
        "load_runtime_snapshot",
        lambda: {"daemonRunning": True, "projectRoot": str(Path.cwd())},
    )

    assert service._runtime_manager_live_control_enabled() is False


def test_self_evolution_terminate_route(monkeypatch):
    monkeypatch.setattr(
        evolution_routes,
        "request_stop_self_evolution_run",
        lambda run_id: {"runId": run_id, "status": "stopping"},
    )

    response = client.post("/api/evolution/self/runs/web-self-stop/terminate")

    assert response.status_code == 200
    assert response.json()["status"] == "stopping"


def test_request_pause_self_evolution_run_marks_queued_run_paused():
    run_id = "web-self-pause"
    with service._RUN_STATE_LOCK:
        service._RUN_STATES[run_id] = {
            "runId": run_id,
            "goal": "pause me",
            "status": "queued",
            "phase": "queued",
            "startedAt": "2026-05-18T12:00:00Z",
            "updatedAt": "2026-05-18T12:00:00Z",
            "finishedAt": "",
            "latestMessage": "queued",
            "currentGoal": "pause me",
            "lastToolName": "",
            "runtimeStatus": "idle",
            "toolCallCount": 0,
            "summary": "",
            "error": "",
            "cancelRequested": False,
            "cancelRequestedAt": "",
            "stopReason": "",
            "controlAction": "",
            "controlRequestedAt": "",
            "messages": [],
            "turnCount": 0,
            "resumeCount": 0,
            "rollback": {
                "status": "idle",
                "reason": "",
                "baseRev": "",
                "rolledBackAt": "",
                "entryCount": 0,
                "touchedFiles": [],
                "conflictFiles": [],
                "blockedHint": "",
            },
        }
        service._ACTIVE_RUN_ID = run_id

    snapshot = service.request_pause_self_evolution_run(run_id)

    assert snapshot["status"] == "paused"
    assert snapshot["phase"] == "paused"
    assert snapshot["messages"][-1]["role"] == "assistant"
    assert snapshot["messages"][-1]["content"] == snapshot["latestMessage"]


def test_request_stop_self_evolution_run_closes_file_only_queued_run(monkeypatch):
    run_id = "web-self-file-only"
    persisted: dict[str, object] = {}
    stored = {
        "runId": run_id,
        "goal": "file only",
        "status": "queued",
        "phase": "queued",
        "startedAt": "2026-05-18T12:00:00Z",
        "updatedAt": "2026-05-18T12:00:00Z",
        "finishedAt": "",
        "latestMessage": "queued",
        "currentGoal": "file only",
        "lastToolName": "",
        "runtimeStatus": "working",
        "toolCallCount": 0,
        "summary": "",
        "error": "",
        "cancelRequested": False,
        "cancelRequestedAt": "",
        "stopReason": "",
        "controlAction": "",
        "controlRequestedAt": "",
        "messages": [],
        "turnCount": 0,
        "resumeCount": 0,
        "rollback": {
            "status": "unavailable",
            "reason": "",
            "baseRev": "",
            "rolledBackAt": "",
            "entryCount": 0,
            "touchedFiles": [],
            "conflictFiles": [],
            "blockedHint": "",
        },
    }

    monkeypatch.setattr(service, "load_manager_run_snapshot", lambda kind, loaded_run_id: copy.deepcopy(stored) if kind == "self" and loaded_run_id == run_id else None)

    def fake_persist(kind: str, payload: dict, *, active_run_id: str = "") -> dict:
        persisted["kind"] = kind
        persisted["payload"] = copy.deepcopy(payload)
        persisted["active_run_id"] = active_run_id
        return copy.deepcopy(payload)

    monkeypatch.setattr(service, "persist_manager_run_snapshot", fake_persist)

    snapshot = service.request_stop_self_evolution_run(run_id)

    assert snapshot["status"] == "cancelled"
    assert snapshot["phase"] == "cancelled"
    assert snapshot["runtimeStatus"] == "idle"
    assert snapshot["cancelRequested"] is True
    assert snapshot["finishedAt"]
    assert snapshot["messages"][-1]["role"] == "assistant"
    assert persisted["kind"] == "self"
    assert persisted["active_run_id"] == ""
    assert persisted["payload"]["status"] == "cancelled"


def test_resume_self_evolution_run_requeues_paused_run(monkeypatch):
    run_id = "web-self-resume"
    submitted: list[dict[str, str]] = []
    with service._RUN_STATE_LOCK:
        service._RUN_STATES[run_id] = {
            "runId": run_id,
            "goal": "resume me",
            "status": "paused",
            "phase": "paused",
            "startedAt": "2026-05-18T12:00:00Z",
            "updatedAt": "2026-05-18T12:01:00Z",
            "finishedAt": "",
            "latestMessage": "paused",
            "currentGoal": "resume me",
            "lastToolName": "",
            "runtimeStatus": "idle",
            "toolCallCount": 0,
            "summary": "",
            "error": "",
            "cancelRequested": False,
            "cancelRequestedAt": "",
            "stopReason": "paused",
            "controlAction": "",
            "controlRequestedAt": "",
            "messages": [],
            "turnCount": 0,
            "resumeCount": 0,
            "rollback": {
                "status": "idle",
                "reason": "",
                "baseRev": "",
                "rolledBackAt": "",
                "entryCount": 0,
                "touchedFiles": [],
                "conflictFiles": [],
                "blockedHint": "",
            },
        }
        service._RUN_INTERNALS[run_id] = {
            "preflight": {},
            "carryover": {},
        }
        service._ACTIVE_RUN_ID = run_id
    monkeypatch.setattr(service, "has_running_sessions", lambda: False)
    monkeypatch.setattr(service, "get_active_supervised_run", lambda: None)
    monkeypatch.setattr(
        service._RUN_EXECUTOR,
        "submit",
        lambda fn, context: submitted.append({"fn": fn.__name__, "runId": context["runId"], "goal": context["goal"]}),
    )

    snapshot = service.resume_self_evolution_run(run_id)

    assert snapshot["status"] == "queued"
    assert snapshot["resumeCount"] == 1
    assert snapshot["messages"][-1]["role"] == "user"
    assert "resume me" in snapshot["messages"][-1]["content"]
    assert submitted == [{"fn": "_run_self_evolution_turn", "runId": run_id, "goal": "resume me"}]


def test_self_evolution_pause_route(monkeypatch):
    monkeypatch.setattr(
        evolution_routes,
        "request_pause_self_evolution_run",
        lambda run_id: {"runId": run_id, "status": "paused"},
    )

    response = client.post("/api/evolution/self/runs/web-self-pause/pause")

    assert response.status_code == 200
    assert response.json()["status"] == "paused"


def test_self_evolution_resume_route(monkeypatch):
    monkeypatch.setattr(
        evolution_routes,
        "resume_self_evolution_run",
        lambda run_id: {"runId": run_id, "status": "queued", "resumeCount": 1},
    )

    response = client.post("/api/evolution/self/runs/web-self-resume/resume")

    assert response.status_code == 200
    assert response.json()["resumeCount"] == 1


def test_self_evolution_handoff_route(monkeypatch):
    monkeypatch.setattr(
        evolution_routes,
        "handoff_self_evolution_run_to_session",
        lambda run_id: {
            "status": "ready",
            "message": "ready",
            "sessionId": "session-live",
            "content": f"handoff {run_id}",
            "run": {"runId": run_id, "status": "blocked"},
        },
    )

    response = client.post("/api/evolution/self/runs/web-self-handoff/handoff")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["sessionId"] == "session-live"
