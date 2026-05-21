import json
import subprocess

import pytest

from core.runtime_manager import cli as runtime_cli
from core.runtime_manager import daemon
from core.runtime_manager import evolution_store
from core.runtime_manager import state_store
from core.runtime_manager import workbench_controller


def test_print_status_reports_stale_runtime_manager_source(capsys):
    runtime_cli._print_status(
        {
            "daemonRunning": True,
            "managerPid": 100,
            "projectRoot": "C:/project",
            "statePath": "C:/project/.runtime/runtime-manager/state.json",
            "workbench": {
                "desiredState": "open",
                "observedState": "open",
                "phase": "steady",
                "backendPid": 200,
                "browserWindowPid": 300,
                "url": "http://127.0.0.1:8766",
            },
            "runtimeManager": {"sourceMatches": False},
        }
    )

    output = capsys.readouterr().out
    assert "source changed" in output

def test_load_runtime_snapshot_aligns_legacy_open_session(monkeypatch):
    monkeypatch.setattr(
        daemon,
        "load_state",
        lambda: {
            "stateVersion": 3,
            "workbench": {
                "desiredState": "closed",
                "observedState": "closed",
                "phase": "steady",
            },
            "command": {"activeCommandId": ""},
        },
    )
    monkeypatch.setattr(
        daemon,
        "observe_workbench",
        lambda: {
            "observedState": "open",
            "backendPid": 3200,
            "browserLaunchPid": 0,
            "browserWindowPid": 4500,
            "browserManaged": True,
            "sessionId": "legacy-session",
            "url": "http://127.0.0.1:8000",
        },
    )
    monkeypatch.setattr(daemon, "is_daemon_running", lambda: False)
    monkeypatch.setattr(daemon, "load_pid", lambda: 0)

    snapshot = daemon.load_runtime_snapshot()

    assert snapshot["runtimeState"] == "idle"
    assert snapshot["workbench"]["desiredState"] == "open"
    assert snapshot["workbench"]["observedState"] == "open"
    assert snapshot["workbench"]["phase"] == "steady"


def test_load_runtime_snapshot_preserves_failed_close_state(monkeypatch):
    monkeypatch.setattr(
        daemon,
        "load_state",
        lambda: {
            "stateVersion": 8,
            "workbench": {
                "desiredState": "closed",
                "observedState": "open",
                "phase": "failed",
                "failureMessage": "stop failed",
            },
            "command": {"activeCommandId": ""},
        },
    )
    monkeypatch.setattr(
        daemon,
        "observe_workbench",
        lambda: {
            "observedState": "open",
            "backendPid": 3200,
            "browserLaunchPid": 0,
            "browserWindowPid": 4500,
            "browserManaged": True,
            "sessionId": "legacy-session",
            "url": "http://127.0.0.1:8000",
        },
    )
    monkeypatch.setattr(daemon, "is_daemon_running", lambda: True)
    monkeypatch.setattr(daemon, "load_pid", lambda: 9912)

    snapshot = daemon.load_runtime_snapshot()

    assert snapshot["runtimeState"] == "running"
    assert snapshot["workbench"]["desiredState"] == "closed"
    assert snapshot["workbench"]["phase"] == "failed"
    assert snapshot["workbench"]["failureMessage"] == "stop failed"


def test_load_runtime_snapshot_recovers_failed_non_lifecycle_error_when_observation_matches(monkeypatch):
    monkeypatch.setattr(
        daemon,
        "load_state",
        lambda: {
            "stateVersion": 9,
            "workbench": {
                "desiredState": "open",
                "observedState": "open",
                "phase": "failed",
                "failureMessage": "missing supervised run",
            },
            "command": {"activeCommandId": ""},
            "lastError": {
                "scope": "stop_supervised_run",
                "message": "missing supervised run",
                "at": "2026-05-19T08:00:00+00:00",
            },
        },
    )
    monkeypatch.setattr(
        daemon,
        "observe_workbench",
        lambda: {
            "observedState": "open",
            "backendPid": 3200,
            "browserLaunchPid": 0,
            "browserWindowPid": 4500,
            "browserManaged": True,
            "sessionId": "managed-session",
            "url": "http://127.0.0.1:8000",
        },
    )
    monkeypatch.setattr(daemon, "is_daemon_running", lambda: True)
    monkeypatch.setattr(daemon, "load_pid", lambda: 9912)
    monkeypatch.setattr(daemon, "_process_source_signature", lambda: "sig-current")

    snapshot = daemon.load_runtime_snapshot()

    assert snapshot["workbench"]["phase"] == "steady"
    assert snapshot["workbench"]["failureMessage"] == ""
    assert "Workbench is open" in snapshot["workbench"]["statusLine"]


def test_handle_start_supervised_run_returns_snapshot(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    monkeypatch.setattr(daemon, "load_state", lambda: {"command": {}, "workbench": {}})
    monkeypatch.setattr(daemon, "save_state", lambda state: state)
    monkeypatch.setattr(daemon, "now_iso", lambda: "2026-05-19T08:00:00+00:00")
    monkeypatch.setattr(daemon, "observe_workbench", lambda: {"observedState": "closed"})
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(
        daemon.supervised_control_service,
        "_LOCAL_START_SUPERVISED_RUN",
        lambda payload: {"runId": "web-supervised-managed", "status": "queued", "payload": payload},
    )

    result = runtime_daemon._handle_start_supervised_run(
        command_id="cmd-1",
        args={"payload": {"sourceKind": "bundle", "bundleName": "managed_bundle"}},
    )

    assert result["ok"] is True
    assert result["runId"] == "web-supervised-managed"
    assert result["snapshot"]["status"] == "queued"


def test_run_forever_refreshes_manager_started_at(monkeypatch):
    class StopLoop(Exception):
        pass

    runtime_daemon = daemon.RuntimeManagerDaemon()
    saved_states: list[dict] = []
    timestamps = iter(["2026-05-19T08:00:00+00:00", "2026-05-19T08:00:01+00:00"])

    monkeypatch.setattr(daemon, "ensure_runtime_manager_dirs", lambda: None)
    monkeypatch.setattr(daemon, "recover_processing_queue", lambda: None)
    monkeypatch.setattr(daemon, "save_pid", lambda pid: None)
    monkeypatch.setattr(
        daemon,
        "load_state",
        lambda: {
            "startedAt": "2026-05-18T01:00:00+00:00",
            "command": {},
            "workbench": {},
        },
    )
    monkeypatch.setattr(daemon, "now_iso", lambda: next(timestamps))
    monkeypatch.setattr(daemon, "observe_workbench", lambda: {"observedState": "closed"})
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(daemon, "_process_source_signature", lambda: "sig-current")
    monkeypatch.setattr(daemon, "save_state", lambda state: saved_states.append(json.loads(json.dumps(state))) or state)

    def stop_after_startup():
        raise StopLoop()

    monkeypatch.setattr(daemon, "claim_next_command", stop_after_startup)

    with pytest.raises(StopLoop):
        runtime_daemon.run_forever()

    assert saved_states[0]["startedAt"] == "2026-05-19T08:00:00+00:00"
    assert saved_states[0]["runtimeManager"]["sourceSignature"] == "sig-current"


def test_handle_command_reports_exception_type(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    monkeypatch.setattr(daemon, "load_state", lambda: {"command": {}, "workbench": {}})
    monkeypatch.setattr(daemon, "save_state", lambda state: state)
    monkeypatch.setattr(daemon, "observe_workbench", lambda: {"observedState": "closed"})
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})

    def boom(*, command_id: str, args: dict):
        raise ValueError("bad payload")

    monkeypatch.setattr(runtime_daemon, "_handle_start_supervised_run", boom)

    result = runtime_daemon._handle_command(
        {
            "commandId": "cmd-err",
            "type": "start_supervised_run",
            "requestedBy": "test",
            "args": {},
        }
    )

    assert result["ok"] is False
    assert result["errorType"] == "ValueError"


def test_non_lifecycle_command_failure_does_not_mark_workbench_failed(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    saved_states: list[dict] = []
    state = {
        "command": {"activeCommandId": "cmd-err", "activeType": "stop_supervised_run"},
        "workbench": {
            "desiredState": "open",
            "observedState": "open",
            "phase": "steady",
            "failureMessage": "",
        },
    }
    monkeypatch.setattr(daemon, "load_state", lambda: json.loads(json.dumps(state)))
    monkeypatch.setattr(daemon, "save_state", lambda payload: saved_states.append(payload) or payload)
    monkeypatch.setattr(
        daemon,
        "observe_workbench",
        lambda: {
            "observedState": "open",
            "backendPid": 3200,
            "browserLaunchPid": 0,
            "browserWindowPid": 4500,
            "browserManaged": True,
        },
    )
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})

    def boom(*, command_id: str, args: dict):
        raise daemon.supervised_control_service.SupervisedRunNotFoundError("missing supervised run")

    monkeypatch.setattr(runtime_daemon, "_handle_stop_supervised_run", boom)

    result = runtime_daemon._handle_command(
        {
            "commandId": "cmd-err",
            "type": "stop_supervised_run",
            "requestedBy": "test",
            "args": {"runId": "missing"},
        }
    )

    assert result["ok"] is False
    assert result["errorType"] == "SupervisedRunNotFoundError"
    assert saved_states[-1]["lastError"]["scope"] == "stop_supervised_run"
    assert saved_states[-1]["workbench"]["phase"] == "steady"
    assert saved_states[-1]["workbench"]["failureMessage"] == ""


def test_is_process_alive_windows_with_real_process():
    import os
    import sys
    import time

    if os.name != "nt":
        return

    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(2)"])
    try:
        deadline = time.time() + 2.0
        while time.time() < deadline and not daemon._is_process_alive(proc.pid):
            time.sleep(0.05)
        assert daemon._is_process_alive(proc.pid) is True
    finally:
        proc.terminate()
        proc.wait(timeout=5)

    assert daemon._is_process_alive(proc.pid) is False


def test_ensure_daemon_running_restarts_stale_source_signature(monkeypatch, tmp_path):
    events: list[tuple[str, dict]] = []
    terminated: list[int] = []
    popen_calls: list[list[str]] = []
    running_checks = iter([False, True])

    monkeypatch.setattr(daemon, "load_pid", lambda: 12345)
    monkeypatch.setattr(daemon, "_is_process_alive", lambda pid: pid == 12345)
    monkeypatch.setattr(
        daemon,
        "load_state",
        lambda: {
            "runtimeManager": {"sourceSignature": "old-signature"},
            "command": {"activeCommandId": "", "startedAt": ""},
        },
    )
    monkeypatch.setattr(daemon, "_process_source_signature", lambda: "new-signature")
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))
    monkeypatch.setattr(daemon, "_terminate_daemon_process", lambda pid: terminated.append(pid))
    monkeypatch.setattr(daemon, "ensure_runtime_manager_dirs", lambda: None)
    monkeypatch.setattr(daemon, "is_daemon_running", lambda: next(running_checks))
    monkeypatch.setattr(daemon, "DAEMON_STDOUT_PATH", tmp_path / "daemon.out.log")
    monkeypatch.setattr(daemon, "DAEMON_STDERR_PATH", tmp_path / "daemon.err.log")
    monkeypatch.setattr(
        daemon.subprocess,
        "Popen",
        lambda args, **kwargs: popen_calls.append(args),
    )

    assert daemon.ensure_daemon_running(python_executable="python-test") is True
    assert terminated == [12345]
    assert events == [("daemon.restart_requested", {"pid": 12345, "reason": "runtime_manager_source_changed"})]
    assert popen_calls == [["python-test", "-m", "core.runtime_manager.cli", "daemon"]]


def test_ensure_daemon_running_keeps_current_source_signature(monkeypatch):
    monkeypatch.setattr(daemon, "load_pid", lambda: 12345)
    monkeypatch.setattr(daemon, "_is_process_alive", lambda pid: True)
    monkeypatch.setattr(
        daemon,
        "load_state",
        lambda: {
            "runtimeManager": {"sourceSignature": "same-signature"},
            "command": {"activeCommandId": "", "startedAt": ""},
        },
    )
    monkeypatch.setattr(daemon, "_process_source_signature", lambda: "same-signature")

    assert daemon.ensure_daemon_running() is False


def test_load_launcher_state_supports_utf8_bom(tmp_path, monkeypatch):
    launcher_state_path = tmp_path / "state.json"
    launcher_state_path.write_text(
        json.dumps({"backendPid": 28888, "browserManaged": False}),
        encoding="utf-8-sig",
    )
    monkeypatch.setattr(workbench_controller, "LAUNCHER_STATE_PATH", launcher_state_path)

    state = workbench_controller._load_launcher_state()

    assert state["backendPid"] == 28888
    assert state["browserManaged"] is False


def test_handle_open_workbench_restarts_headless_session(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    state = {"command": {}, "workbench": {"observedState": "open", "phase": "steady"}}

    monkeypatch.setattr(daemon, "load_state", lambda: state)
    monkeypatch.setattr(daemon, "save_state", lambda next_state: next_state)
    monkeypatch.setattr(daemon, "now_iso", lambda: "2026-05-19T09:00:00+00:00")
    monkeypatch.setattr(
        daemon,
        "observe_workbench",
        lambda: {
            "observedState": "open",
            "launcherStatePresent": True,
            "browserManaged": False,
            "browserWindowAlive": False,
            "backendPid": 28888,
            "browserLaunchPid": 0,
            "browserWindowPid": 0,
            "sessionId": "headless-session",
            "url": "http://127.0.0.1:8000",
        },
    )
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})

    opened = {}

    def fake_open_workbench(*, no_browser: bool):
        opened["no_browser"] = no_browser
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(daemon, "open_workbench", fake_open_workbench)

    result = runtime_daemon._handle_open_workbench(command_id="cmd-open", args={})

    assert result["ok"] is True
    assert result["message"] == "Workbench opened."
    assert opened == {"no_browser": False}


def test_run_launcher_action_uses_devnull_stdio(monkeypatch):
    captured = {}

    def fake_run(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        kwargs["stdout"].write(b"launcher stdout\n")
        kwargs["stdout"].flush()
        kwargs["stderr"].write(b"launcher stderr\n")
        kwargs["stderr"].flush()
        return subprocess.CompletedProcess(args=args[0], returncode=0)

    monkeypatch.setattr(workbench_controller.subprocess, "run", fake_run)

    result = workbench_controller.run_launcher_action("internal-start", no_browser=True)

    assert result.returncode == 0
    assert result.stdout == "launcher stdout\n"
    assert result.stderr == "launcher stderr\n"
    assert captured["args"][0][-2:] == ["internal-start", "-NoBrowser"]
    assert captured["kwargs"]["stdin"] is subprocess.DEVNULL
    assert "capture_output" not in captured["kwargs"]
    assert "text" not in captured["kwargs"]
    assert captured["kwargs"]["stdout"] is not None
    assert captured["kwargs"]["stderr"] is not None


def test_handle_restart_workbench_surfaces_launcher_error(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    state = {"command": {}, "workbench": {"observedState": "open", "phase": "steady"}}

    monkeypatch.setattr(daemon, "load_state", lambda: state)
    monkeypatch.setattr(daemon, "save_state", lambda next_state: next_state)
    monkeypatch.setattr(daemon, "now_iso", lambda: "2026-05-19T09:00:00+00:00")
    monkeypatch.setattr(
        daemon,
        "observe_workbench",
        lambda: {
            "observedState": "open",
            "launcherStatePresent": True,
            "browserManaged": True,
            "browserWindowAlive": True,
            "backendPid": 28888,
            "browserLaunchPid": 29999,
            "browserWindowPid": 29999,
            "sessionId": "managed-session",
            "url": "http://127.0.0.1:8000",
        },
    )
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(
        daemon,
        "restart_workbench",
        lambda **kwargs: subprocess.CompletedProcess(args=[], returncode=1, stdout=None, stderr="launcher failed"),
    )

    with pytest.raises(RuntimeError, match="launcher failed"):
        runtime_daemon._handle_restart_workbench(command_id="cmd-restart", args={})


def test_atomic_write_text_retries_permission_error(tmp_path, monkeypatch):
    target_path = tmp_path / "state.json"
    replace_calls = {"count": 0}
    sleep_calls = []
    real_replace = state_store.os.replace

    monkeypatch.setattr(state_store, "ensure_runtime_manager_dirs", lambda: None)

    def flaky_replace(src: str, dst: str):
        replace_calls["count"] += 1
        if replace_calls["count"] == 1:
            raise PermissionError("locked")
        return real_replace(src, dst)

    monkeypatch.setattr(state_store.os, "replace", flaky_replace)
    monkeypatch.setattr(state_store.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    state_store._atomic_write_text(target_path, "hello")

    assert target_path.read_text(encoding="utf-8") == "hello"
    assert replace_calls["count"] == 2
    assert sleep_calls == [0.05]


def test_atomic_write_text_waits_out_longer_permission_error(tmp_path, monkeypatch):
    target_path = tmp_path / "state.json"
    replace_calls = {"count": 0}
    sleep_calls = []
    real_replace = state_store.os.replace

    monkeypatch.setattr(state_store, "ensure_runtime_manager_dirs", lambda: None)

    def flaky_replace(src: str, dst: str):
        replace_calls["count"] += 1
        if replace_calls["count"] <= 8:
            raise PermissionError("locked")
        return real_replace(src, dst)

    monkeypatch.setattr(state_store.os, "replace", flaky_replace)
    monkeypatch.setattr(state_store.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    state_store._atomic_write_text(target_path, "hello")

    assert target_path.read_text(encoding="utf-8") == "hello"
    assert replace_calls["count"] == 9
    assert sleep_calls[:3] == [0.05, 0.1, 0.15000000000000002]
    assert sleep_calls[-1] == 0.25


def test_atomic_write_text_falls_back_to_in_place_write_after_replace_timeout(tmp_path, monkeypatch):
    target_path = tmp_path / "state.json"
    replace_calls = {"count": 0}
    monotonic_values = iter([0.0, state_store.WRITE_RETRY_TIMEOUT_SECONDS + 0.1])

    monkeypatch.setattr(state_store, "ensure_runtime_manager_dirs", lambda: None)
    monkeypatch.setattr(state_store.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(state_store.time, "monotonic", lambda: next(monotonic_values))

    def always_locked_replace(src: str, dst: str):
        replace_calls["count"] += 1
        raise PermissionError("locked")

    monkeypatch.setattr(state_store.os, "replace", always_locked_replace)

    state_store._atomic_write_text(target_path, "hello")

    assert target_path.read_text(encoding="utf-8") == "hello"
    assert replace_calls["count"] == 1


def test_load_state_retries_transient_json_decode_error(tmp_path, monkeypatch):
    state_path = tmp_path / "state.json"
    state_path.write_text('{"runtimeState": "running"}', encoding="utf-8")
    real_json_loads = state_store.json.loads
    load_calls = {"count": 0}
    sleep_calls = []

    monkeypatch.setattr(state_store, "STATE_PATH", state_path)
    monkeypatch.setattr(state_store.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    def flaky_json_loads(raw: str):
        load_calls["count"] += 1
        if load_calls["count"] == 1:
            raise json.JSONDecodeError("transient", raw, 0)
        return real_json_loads(raw)

    monkeypatch.setattr(state_store.json, "loads", flaky_json_loads)

    payload = state_store.load_state()

    assert payload["runtimeState"] == "running"
    assert load_calls["count"] == 2
    assert sleep_calls == [0.05]


def test_evolution_store_atomic_write_retries_permission_error(tmp_path, monkeypatch):
    target_path = tmp_path / "snapshot.json"
    replace_calls = {"count": 0}
    sleep_calls = []
    real_replace = evolution_store.os.replace

    monkeypatch.setattr(evolution_store, "ensure_evolution_store_dirs", lambda: None)

    def flaky_replace(src: str, dst: str):
        replace_calls["count"] += 1
        if replace_calls["count"] <= 3:
            raise PermissionError("locked")
        return real_replace(src, dst)

    monkeypatch.setattr(evolution_store.os, "replace", flaky_replace)
    monkeypatch.setattr(evolution_store.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    evolution_store._atomic_write_json(target_path, {"ok": True})

    assert json.loads(target_path.read_text(encoding="utf-8")) == {"ok": True}
    assert replace_calls["count"] == 4
    assert sleep_calls == [0.05, 0.1, 0.15000000000000002]


def test_evolution_store_delete_snapshot_clears_active_and_repoints_latest(tmp_path, monkeypatch):
    runs_dir = tmp_path / "supervised" / "runs"
    index_path = tmp_path / "supervised" / "index.json"

    def fake_kind_paths(kind: str):
        assert kind == "supervised"
        return runs_dir, index_path

    monkeypatch.setattr(evolution_store, "_kind_paths", fake_kind_paths)
    runs_dir.mkdir(parents=True, exist_ok=True)

    old = {
        "runId": "old-run",
        "status": "cancelled",
        "startedAt": "2026-05-18T11:00:00Z",
        "updatedAt": "2026-05-18T11:00:00Z",
    }
    active = {
        "runId": "active-run",
        "status": "queued",
        "startedAt": "2026-05-18T12:00:00Z",
        "updatedAt": "2026-05-18T12:00:00Z",
    }
    evolution_store.persist_run_snapshot("supervised", old, active_run_id="")
    evolution_store.persist_run_snapshot("supervised", active, active_run_id="active-run")

    result = evolution_store.delete_run_snapshot("supervised", "active-run")

    assert result["deleted"] is True
    assert result["clearedActive"] is True
    assert result["clearedLatest"] is True
    assert result["activeRunId"] == ""
    assert result["latestRunId"] == "old-run"
    assert evolution_store.load_run_snapshot("supervised", "active-run") is None
    assert evolution_store.load_latest_run_snapshot("supervised")["runId"] == "old-run"


def test_evolution_store_delete_corrupt_index_only_run_clears_index(tmp_path, monkeypatch):
    runs_dir = tmp_path / "supervised" / "runs"
    index_path = tmp_path / "supervised" / "index.json"

    def fake_kind_paths(kind: str):
        assert kind == "supervised"
        return runs_dir, index_path

    monkeypatch.setattr(evolution_store, "_kind_paths", fake_kind_paths)
    runs_dir.mkdir(parents=True, exist_ok=True)

    evolution_store.save_run_index("supervised", active_run_id="missing-run", latest_run_id="missing-run")

    result = evolution_store.delete_run_snapshot("supervised", "missing-run")

    assert result["deleted"] is False
    assert result["clearedActive"] is True
    assert result["clearedLatest"] is True
    assert result["activeRunId"] == ""
    assert result["latestRunId"] == ""


def test_clear_pid_keeps_newer_owner(tmp_path, monkeypatch):
    pid_path = tmp_path / "daemon.pid"
    monkeypatch.setattr(state_store, "PID_PATH", pid_path)

    state_store.save_pid(200)
    state_store.clear_pid(100)
    assert pid_path.read_text(encoding="utf-8") == "200"

    state_store.clear_pid(200)
    assert not pid_path.exists()
