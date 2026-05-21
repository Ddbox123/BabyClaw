"""Background runtime-manager daemon."""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.runtime_manager.evolution_store import build_evolution_summary
from core.web.services import self_evolution_control_service, supervised_control_service

from .command_queue import claim_next_command, complete_command, recover_processing_queue
from .constants import (
    DAEMON_LOOP_INTERVAL_SECONDS,
    DAEMON_STDERR_PATH,
    DAEMON_STDOUT_PATH,
    EVENTS_PATH,
    PROJECT_ROOT,
    STATE_PATH,
    ensure_runtime_manager_dirs,
)
from .state_store import clear_pid, default_state, load_pid, load_state, now_iso, save_pid, save_state
from .workbench_controller import close_workbench, observe_workbench, open_workbench, restart_workbench


_WORKBENCH_LIFECYCLE_COMMANDS = {"open_workbench", "close_workbench", "restart_workbench", "toggle_workbench"}
_SOURCE_SIGNATURE_PATHS = (
    Path("core/runtime_manager/cli.py"),
    Path("core/runtime_manager/command_queue.py"),
    Path("core/runtime_manager/constants.py"),
    Path("core/runtime_manager/daemon.py"),
    Path("core/runtime_manager/evolution_store.py"),
    Path("core/runtime_manager/state_store.py"),
    Path("core/runtime_manager/workbench_controller.py"),
    Path("core/web/services/self_evolution_control_service.py"),
    Path("core/web/services/supervised_control_service.py"),
)
_ACTIVE_COMMAND_RESTART_GRACE_SECONDS = 300.0


def _command_affects_workbench_lifecycle(command_type: str) -> bool:
    return str(command_type or "").strip() in _WORKBENCH_LIFECYCLE_COMMANDS


def _runtime_manager_source_signature() -> str:
    digest = hashlib.sha256()
    for relative_path in _SOURCE_SIGNATURE_PATHS:
        path = PROJECT_ROOT / relative_path
        digest.update(str(relative_path).replace("\\", "/").encode("utf-8"))
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(b"<missing>")
    return digest.hexdigest()


_PROCESS_SOURCE_SIGNATURE = _runtime_manager_source_signature()


def _process_source_signature() -> str:
    return _PROCESS_SOURCE_SIGNATURE


def _state_source_signature(state: dict[str, Any]) -> str:
    payload = state.get("runtimeManager") if isinstance(state.get("runtimeManager"), dict) else {}
    return str(payload.get("sourceSignature") or "").strip()


def _active_command_is_recent(state: dict[str, Any]) -> bool:
    command = state.get("command") if isinstance(state.get("command"), dict) else {}
    if not str(command.get("activeCommandId") or "").strip():
        return False
    started_at = str(command.get("startedAt") or "").strip()
    if not started_at:
        return False
    try:
        parsed = datetime.fromisoformat(started_at)
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    age_seconds = (datetime.now(UTC) - parsed.astimezone(UTC)).total_seconds()
    return age_seconds < _ACTIVE_COMMAND_RESTART_GRACE_SECONDS


def _terminate_daemon_process(pid: int) -> None:
    if pid <= 0 or pid == os.getpid():
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if not _is_process_alive(pid):
            clear_pid(pid)
            return
        time.sleep(0.1)
    if hasattr(signal, "SIGKILL"):
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    clear_pid(pid)


def _workbench_failure_should_stick(state: dict[str, Any], *, desired_state: str, observed_state: str) -> bool:
    if observed_state == desired_state:
        return False
    last_error = state.get("lastError") if isinstance(state.get("lastError"), dict) else {}
    scope = str(last_error.get("scope") or "").strip()
    return not scope or _command_affects_workbench_lifecycle(scope)


def _open_request_already_satisfied(observation: dict[str, Any], *, no_browser: bool) -> bool:
    if str(observation.get("observedState") or "closed") != "open":
        return False
    if no_browser:
        return True
    if not bool(observation.get("launcherStatePresent")):
        return False
    if not bool(observation.get("browserManaged")):
        return False
    return bool(observation.get("browserWindowAlive"))


def _is_process_alive_windows(pid: int) -> bool:
    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_INFORMATION = 0x0400
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = None
    for access in (PROCESS_QUERY_LIMITED_INFORMATION, PROCESS_QUERY_INFORMATION):
        handle = kernel32.OpenProcess(access, False, int(pid))
        if handle:
            break
    if not handle:
        return False

    try:
        exit_code = wintypes.DWORD()
        if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)) == 0:
            return False
        return int(exit_code.value) == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _is_process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            return _is_process_alive_windows(int(pid))
        except OSError:
            return False
    try:
        os.kill(int(pid), 0)
    except OSError:
        return False
    return True


def is_daemon_running() -> bool:
    return _is_process_alive(load_pid())


def _append_event(event_type: str, payload: dict[str, Any]) -> None:
    ensure_runtime_manager_dirs()
    event = {
        "type": event_type,
        "at": datetime.now(UTC).isoformat(),
        "payload": payload,
    }
    with EVENTS_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def _creation_flags() -> int:
    flags = 0
    for name in ("DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP", "CREATE_NO_WINDOW"):
        flags |= int(getattr(subprocess, name, 0))
    return flags


def ensure_daemon_running(*, python_executable: str | None = None) -> bool:
    current_pid = load_pid()
    if _is_process_alive(current_pid):
        state = load_state()
        current_signature = _process_source_signature()
        if _state_source_signature(state) == current_signature or _active_command_is_recent(state):
            return False
        _append_event(
            "daemon.restart_requested",
            {"pid": current_pid, "reason": "runtime_manager_source_changed"},
        )
        _terminate_daemon_process(current_pid)

    ensure_runtime_manager_dirs()
    python_cmd = python_executable or sys.executable
    with DAEMON_STDOUT_PATH.open("a", encoding="utf-8") as stdout_handle, DAEMON_STDERR_PATH.open(
        "a", encoding="utf-8"
    ) as stderr_handle:
        subprocess.Popen(
            [python_cmd, "-m", "core.runtime_manager.cli", "daemon"],
            cwd=str(PROJECT_ROOT),
            stdin=subprocess.DEVNULL,
            stdout=stdout_handle,
            stderr=stderr_handle,
            creationflags=_creation_flags(),
            close_fds=True,
        )

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if is_daemon_running():
            return True
        time.sleep(0.2)
    raise RuntimeError("Runtime manager daemon failed to start.")


def load_runtime_snapshot() -> dict[str, Any]:
    state = load_state()
    observation = observe_workbench()
    manager_running = is_daemon_running()

    if not state:
        state = default_state()

    workbench = state.setdefault("workbench", {})
    active_command = str((state.get("command") or {}).get("activeCommandId") or "").strip()
    desired_state = str(workbench.get("desiredState") or "closed").strip() or "closed"
    observed_state = str(observation.get("observedState") or "closed").strip() or "closed"
    phase = str(workbench.get("phase") or "steady").strip() or "steady"

    if phase == "failed" and not _workbench_failure_should_stick(state, desired_state=desired_state, observed_state=observed_state):
        phase = "steady"
        workbench["failureMessage"] = ""

    if (not manager_running or not active_command) and phase != "failed":
        if observed_state == "open" and desired_state != "open":
            desired_state = "open"
            phase = "steady"
        elif observed_state == "closed" and desired_state != "closed":
            desired_state = "closed"
            phase = "steady"

    if observed_state == desired_state and phase != "failed":
        phase = "steady"
    elif desired_state == "closed" and observed_state != "closed" and phase != "failed":
        phase = "closing"
    elif desired_state == "open" and observed_state != "open" and phase != "failed":
        phase = "opening"

    workbench.update(
        {
            "desiredState": desired_state,
            "observedState": observed_state,
            "backendPid": int(observation.get("backendPid") or 0),
            "browserLaunchPid": int(observation.get("browserLaunchPid") or 0),
            "browserWindowPid": int(observation.get("browserWindowPid") or 0),
            "browserManaged": bool(observation.get("browserManaged", True)),
            "sessionId": str(observation.get("sessionId") or "").strip(),
            "url": str(observation.get("url") or workbench.get("url") or "").strip(),
            "phase": phase,
            "statusLine": _build_workbench_status_line(
                desired_state=desired_state,
                observed_state=observed_state,
                phase=phase,
                backend_pid=int(observation.get("backendPid") or 0),
                browser_pid=int(observation.get("browserWindowPid") or 0),
            ),
        }
    )
    state["runtimeState"] = "running" if manager_running else "idle"
    state["managerPid"] = load_pid() if manager_running else 0
    state["daemonRunning"] = manager_running
    state["projectRoot"] = str(PROJECT_ROOT)
    state["statePath"] = str(STATE_PATH)
    state["evolution"] = build_evolution_summary()
    runtime_manager = state.get("runtimeManager") if isinstance(state.get("runtimeManager"), dict) else {}
    state["runtimeManager"] = {
        "sourceSignature": str(runtime_manager.get("sourceSignature") or "").strip(),
        "currentSourceSignature": _process_source_signature(),
        "sourceMatches": _state_source_signature(state) == _process_source_signature(),
    }
    return state


def _build_workbench_status_line(
    *,
    desired_state: str,
    observed_state: str,
    phase: str,
    backend_pid: int,
    browser_pid: int,
) -> str:
    if phase == "failed":
        return "Workbench hit a lifecycle error."
    if desired_state == "closed" and observed_state != "closed":
        return "Runtime manager is closing the workbench."
    if desired_state == "open" and observed_state != "open":
        return "Runtime manager is opening the workbench."
    if observed_state == "open":
        return f"Workbench is open (backend PID={backend_pid or '-'}, window PID={browser_pid or '-'})"
    return "Workbench is closed."


def _launcher_error_detail(result: Any, fallback: str) -> str:
    if not result:
        return fallback
    parts = [str(part or "").strip() for part in (getattr(result, "stdout", ""), getattr(result, "stderr", ""))]
    detail = "\n".join(part for part in parts if part)
    return detail or fallback


class RuntimeManagerDaemon:
    def __init__(self) -> None:
        self._pid = os.getpid()

    def run_forever(self) -> None:
        ensure_runtime_manager_dirs()
        recover_processing_queue()
        save_pid(self._pid)

        state = load_state()
        if not isinstance(state, dict):
            state = default_state()
        state["runtimeState"] = "running"
        state["managerPid"] = self._pid
        state["runtimeManager"] = {"sourceSignature": _process_source_signature()}
        state["startedAt"] = now_iso()
        state = self._reconcile_observation(state)
        save_state(state)

        try:
            while True:
                command = claim_next_command()
                if command is not None:
                    path, payload = command
                    result = self._handle_command(payload)
                    complete_command(path, result)
                    continue

                state = self._reconcile_observation(load_state())
                save_state(state)
                time.sleep(DAEMON_LOOP_INTERVAL_SECONDS)
        finally:
            clear_pid(self._pid)

    def _handle_command(self, payload: dict[str, Any]) -> dict[str, Any]:
        command_id = str(payload.get("commandId") or "").strip()
        command_type = str(payload.get("type") or "").strip()
        requested_by = str(payload.get("requestedBy") or "unknown").strip() or "unknown"
        args = payload.get("args") if isinstance(payload.get("args"), dict) else {}

        state = load_state()
        command_state = state.setdefault("command", {})
        command_state.update(
            {
                "activeCommandId": command_id,
                "activeType": command_type,
                "requestedBy": requested_by,
                "startedAt": now_iso(),
            }
        )
        state = self._reconcile_observation(state)
        state = save_state(state)

        handler = getattr(self, f"_handle_{command_type}", None)
        if handler is None:
            result = self._finish_command(
                command_id,
                ok=False,
                message=f"Unsupported runtime-manager command: {command_type}",
                error_scope="command",
                failure_message=f"Unsupported command: {command_type}",
            )
            _append_event("command.failed", {"commandId": command_id, "type": command_type, "message": result["message"]})
            return result

        try:
            result = handler(command_id=command_id, args=args)
            _append_event("command.completed", {"commandId": command_id, "type": command_type, "ok": result["ok"]})
            return result
        except Exception as exc:
            result = self._finish_command(
                command_id,
                ok=False,
                message=str(exc),
                error_scope=command_type or "command",
                failure_message=str(exc),
                error_type=type(exc).__name__,
            )
            _append_event("command.failed", {"commandId": command_id, "type": command_type, "message": str(exc)})
            return result

    def _finish_command(
        self,
        command_id: str,
        *,
        ok: bool,
        message: str,
        error_scope: str = "",
        failure_message: str = "",
        error_type: str = "",
        result_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        state = load_state()
        state.setdefault("command", {}).update(
            {
                "activeCommandId": "",
                "activeType": "",
                "requestedBy": "",
                "startedAt": "",
            }
        )
        if ok:
            state["lastError"] = {"scope": "", "message": "", "at": ""}
        else:
            state["lastError"] = {"scope": error_scope, "message": message, "at": now_iso()}
            if _command_affects_workbench_lifecycle(error_scope):
                state.setdefault("workbench", {})["phase"] = "failed"
                state["workbench"]["failureMessage"] = failure_message or message
        state = self._reconcile_observation(state)
        state = save_state(state)
        result = {
            "commandId": command_id,
            "accepted": True,
            "completed": True,
            "ok": ok,
            "message": message,
            "stateVersion": int(state.get("stateVersion") or 0),
        }
        if error_type:
            result["errorType"] = error_type
        if isinstance(result_data, dict):
            result.update(result_data)
        return result

    def _reconcile_observation(self, state: dict[str, Any]) -> dict[str, Any]:
        observation = observe_workbench()
        workbench = state.setdefault("workbench", {})
        desired_state = str(workbench.get("desiredState") or "closed").strip() or "closed"
        observed_state = str(observation.get("observedState") or "closed").strip() or "closed"
        phase = str(workbench.get("phase") or "steady").strip() or "steady"
        active_command = str(state.setdefault("command", {}).get("activeCommandId") or "").strip()

        if phase == "failed" and not _workbench_failure_should_stick(
            state,
            desired_state=desired_state,
            observed_state=observed_state,
        ):
            phase = "steady"
            workbench["failureMessage"] = ""

        if not active_command and phase != "failed":
            if observed_state == "open" and desired_state != "open":
                desired_state = "open"
                phase = "steady"
                workbench["lastReason"] = "external_open"
            elif observed_state == "closed" and desired_state != "closed":
                desired_state = "closed"
                if phase != "failed":
                    phase = "steady"
                if not workbench.get("lastReason"):
                    workbench["lastReason"] = "external_close"
            elif observed_state == desired_state and phase != "failed":
                phase = "steady"

        if desired_state == "closed" and observed_state != "closed" and phase != "failed":
            phase = "closing"
        elif desired_state == "open" and observed_state != "open" and phase != "failed":
            phase = "opening"

        workbench.update(
            {
                "desiredState": desired_state,
                "observedState": observed_state,
                "phase": phase,
                "sessionId": str(observation.get("sessionId") or "").strip(),
                "backendPid": int(observation.get("backendPid") or 0),
                "browserLaunchPid": int(observation.get("browserLaunchPid") or 0),
                "browserWindowPid": int(observation.get("browserWindowPid") or 0),
                "browserManaged": bool(observation.get("browserManaged", True)),
                "url": str(observation.get("url") or workbench.get("url") or "").strip(),
                "statusLine": _build_workbench_status_line(
                    desired_state=desired_state,
                    observed_state=observed_state,
                    phase=phase,
                    backend_pid=int(observation.get("backendPid") or 0),
                    browser_pid=int(observation.get("browserWindowPid") or 0),
                ),
            }
        )
        state["runtimeState"] = "running"
        state["managerPid"] = self._pid
        state["runtimeManager"] = {"sourceSignature": _process_source_signature()}
        state["evolution"] = build_evolution_summary()
        return state

    def _handle_open_workbench(self, *, command_id: str, args: dict[str, Any]) -> dict[str, Any]:
        state = load_state()
        workbench = state.setdefault("workbench", {})
        no_browser = bool(args.get("noBrowser"))
        observation = observe_workbench()
        if _open_request_already_satisfied(observation, no_browser=no_browser) and str(workbench.get("phase") or "") != "failed":
            workbench["desiredState"] = "open"
            workbench["phase"] = "steady"
            workbench["failureMessage"] = ""
            save_state(self._reconcile_observation(state))
            return self._finish_command(command_id, ok=True, message="Workbench is already open.")

        workbench.update(
            {
                "desiredState": "open",
                "phase": "opening",
                "lastReason": str(args.get("reason") or "explicit_open"),
                "lastTransitionAt": now_iso(),
                "failureMessage": "",
            }
        )
        save_state(self._reconcile_observation(state))
        result = open_workbench(no_browser=no_browser)
        if result.returncode != 0:
            raise RuntimeError(_launcher_error_detail(result, "Opening the workbench failed."))
        return self._finish_command(command_id, ok=True, message="Workbench opened.")

    def _handle_close_workbench(self, *, command_id: str, args: dict[str, Any]) -> dict[str, Any]:
        state = load_state()
        workbench = state.setdefault("workbench", {})
        observation = observe_workbench()
        if str(observation.get("observedState") or "closed") == "closed" and str(workbench.get("phase") or "") != "failed":
            workbench["desiredState"] = "closed"
            workbench["phase"] = "steady"
            workbench["failureMessage"] = ""
            save_state(self._reconcile_observation(state))
            return self._finish_command(command_id, ok=True, message="Workbench is already closed.")

        workbench.update(
            {
                "desiredState": "closed",
                "phase": "closing",
                "lastReason": str(args.get("reason") or "explicit_close"),
                "lastTransitionAt": now_iso(),
                "failureMessage": "",
            }
        )
        save_state(self._reconcile_observation(state))
        result = close_workbench()
        if result.returncode != 0:
            raise RuntimeError(_launcher_error_detail(result, "Closing the workbench failed."))
        return self._finish_command(command_id, ok=True, message="Workbench closed.")

    def _handle_restart_workbench(self, *, command_id: str, args: dict[str, Any]) -> dict[str, Any]:
        state = load_state()
        workbench = state.setdefault("workbench", {})
        workbench.update(
            {
                "desiredState": "open",
                "phase": "opening",
                "lastReason": str(args.get("reason") or "explicit_restart"),
                "lastTransitionAt": now_iso(),
                "failureMessage": "",
            }
        )
        save_state(self._reconcile_observation(state))
        result = restart_workbench(no_browser=bool(args.get("noBrowser")))
        if result.returncode != 0:
            raise RuntimeError(_launcher_error_detail(result, "Restarting the workbench failed."))
        return self._finish_command(command_id, ok=True, message="Workbench restarted.")

    def _handle_toggle_workbench(self, *, command_id: str, args: dict[str, Any]) -> dict[str, Any]:
        state = load_state()
        observed_state = str(state.setdefault("workbench", {}).get("observedState") or "closed").strip() or "closed"
        if observed_state == "open":
            return self._handle_close_workbench(command_id=command_id, args=args)
        return self._handle_open_workbench(command_id=command_id, args=args)

    def _handle_start_self_evolution_run(self, *, command_id: str, args: dict[str, Any]) -> dict[str, Any]:
        payload = args.get("payload") if isinstance(args.get("payload"), dict) else {}
        snapshot = self_evolution_control_service._LOCAL_START_SELF_EVOLUTION_RUN(payload)
        return self._finish_command(
            command_id,
            ok=True,
            message="Self-evolution run started.",
            result_data={"runId": str(snapshot.get("runId") or ""), "snapshot": snapshot},
        )

    def _handle_pause_self_evolution_run(self, *, command_id: str, args: dict[str, Any]) -> dict[str, Any]:
        run_id = str(args.get("runId") or "").strip()
        snapshot = self_evolution_control_service._LOCAL_REQUEST_PAUSE_SELF_EVOLUTION_RUN(run_id)
        return self._finish_command(
            command_id,
            ok=True,
            message="Self-evolution pause requested.",
            result_data={"runId": run_id, "snapshot": snapshot},
        )

    def _handle_resume_self_evolution_run(self, *, command_id: str, args: dict[str, Any]) -> dict[str, Any]:
        run_id = str(args.get("runId") or "").strip()
        snapshot = self_evolution_control_service._LOCAL_RESUME_SELF_EVOLUTION_RUN(run_id)
        return self._finish_command(
            command_id,
            ok=True,
            message="Self-evolution run resumed.",
            result_data={"runId": run_id, "snapshot": snapshot},
        )

    def _handle_stop_self_evolution_run(self, *, command_id: str, args: dict[str, Any]) -> dict[str, Any]:
        run_id = str(args.get("runId") or "").strip()
        snapshot = self_evolution_control_service._LOCAL_REQUEST_STOP_SELF_EVOLUTION_RUN(run_id)
        return self._finish_command(
            command_id,
            ok=True,
            message="Self-evolution stop requested.",
            result_data={"runId": run_id, "snapshot": snapshot},
        )

    def _handle_start_supervised_run(self, *, command_id: str, args: dict[str, Any]) -> dict[str, Any]:
        payload = args.get("payload") if isinstance(args.get("payload"), dict) else {}
        snapshot = supervised_control_service._LOCAL_START_SUPERVISED_RUN(payload)
        return self._finish_command(
            command_id,
            ok=True,
            message="Supervised run started.",
            result_data={"runId": str(snapshot.get("runId") or ""), "snapshot": snapshot},
        )

    def _handle_pause_supervised_run(self, *, command_id: str, args: dict[str, Any]) -> dict[str, Any]:
        run_id = str(args.get("runId") or "").strip()
        snapshot = supervised_control_service._LOCAL_REQUEST_PAUSE_SUPERVISED_RUN(run_id)
        return self._finish_command(
            command_id,
            ok=True,
            message="Supervised run pause requested.",
            result_data={"runId": run_id, "snapshot": snapshot},
        )

    def _handle_resume_supervised_run(self, *, command_id: str, args: dict[str, Any]) -> dict[str, Any]:
        run_id = str(args.get("runId") or "").strip()
        snapshot = supervised_control_service._LOCAL_REQUEST_RESUME_SUPERVISED_RUN(run_id)
        return self._finish_command(
            command_id,
            ok=True,
            message="Supervised run resumed.",
            result_data={"runId": run_id, "snapshot": snapshot},
        )

    def _handle_stop_supervised_run(self, *, command_id: str, args: dict[str, Any]) -> dict[str, Any]:
        run_id = str(args.get("runId") or "").strip()
        snapshot = supervised_control_service._LOCAL_REQUEST_STOP_SUPERVISED_RUN(run_id)
        return self._finish_command(
            command_id,
            ok=True,
            message="Supervised run stop requested.",
            result_data={"runId": run_id, "snapshot": snapshot},
        )

    def _handle_delete_supervised_run(self, *, command_id: str, args: dict[str, Any]) -> dict[str, Any]:
        run_id = str(args.get("runId") or "").strip()
        result = supervised_control_service._LOCAL_DELETE_SUPERVISED_RUN_SNAPSHOT(run_id)
        return self._finish_command(
            command_id,
            ok=True,
            message="Supervised run record deleted.",
            result_data={"runId": run_id, "deleteResult": result},
        )


def run_daemon() -> None:
    RuntimeManagerDaemon().run_forever()
