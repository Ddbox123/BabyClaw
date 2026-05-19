"""Persistent state helpers for the runtime manager."""

from __future__ import annotations

import copy
import json
import os
import tempfile
import time
from datetime import UTC, datetime
from typing import Any

from .constants import DEFAULT_URL, PID_PATH, STATE_PATH, ensure_runtime_manager_dirs


WRITE_RETRY_TIMEOUT_SECONDS = 5.0
READ_RETRY_ATTEMPTS = 5
READ_RETRY_DELAY_SECONDS = 0.05


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def default_state() -> dict[str, Any]:
    now = now_iso()
    return {
        "version": 1,
        "stateVersion": 0,
        "runtimeState": "idle",
        "managerPid": 0,
        "startedAt": now,
        "updatedAt": now,
        "workbench": {
            "desiredState": "closed",
            "observedState": "closed",
            "phase": "steady",
            "sessionId": "",
            "backendPid": 0,
            "browserLaunchPid": 0,
            "browserWindowPid": 0,
            "browserManaged": True,
            "url": DEFAULT_URL,
            "lastReason": "",
            "lastTransitionAt": now,
            "statusLine": "Workbench is closed.",
            "failureMessage": "",
        },
        "command": {
            "activeCommandId": "",
            "activeType": "",
            "requestedBy": "",
            "startedAt": "",
        },
        "lastError": {
            "scope": "",
            "message": "",
            "at": "",
        },
    }


def _atomic_write_text(path, text: str) -> None:
    ensure_runtime_manager_dirs()
    fd, temp_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        deadline = time.monotonic() + WRITE_RETRY_TIMEOUT_SECONDS
        attempt = 0
        last_replace_error: PermissionError | None = None
        while True:
            try:
                os.replace(temp_path, path)
                break
            except PermissionError as exc:
                last_replace_error = exc
                attempt += 1
                if time.monotonic() >= deadline:
                    try:
                        with path.open("w", encoding="utf-8", newline="") as handle:
                            handle.write(text)
                        break
                    except OSError:
                        raise last_replace_error
                time.sleep(min(0.05 * attempt, 0.25))
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def _read_text_with_retry(path, *, encoding: str) -> str:
    for attempt in range(READ_RETRY_ATTEMPTS):
        try:
            return path.read_text(encoding=encoding)
        except OSError:
            if attempt + 1 >= READ_RETRY_ATTEMPTS:
                raise
            time.sleep(READ_RETRY_DELAY_SECONDS)
    raise OSError(f"Unable to read {path}")


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return default_state()
    for attempt in range(READ_RETRY_ATTEMPTS):
        try:
            payload = json.loads(_read_text_with_retry(STATE_PATH, encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            if attempt + 1 >= READ_RETRY_ATTEMPTS:
                return default_state()
            time.sleep(READ_RETRY_DELAY_SECONDS)
            continue
        if isinstance(payload, dict):
            return payload
        return default_state()
    return default_state()


def save_state(state: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(state)
    payload["stateVersion"] = int(payload.get("stateVersion") or 0) + 1
    payload["updatedAt"] = now_iso()
    _atomic_write_text(STATE_PATH, json.dumps(payload, ensure_ascii=False, indent=2))
    return payload


def save_pid(pid: int) -> None:
    ensure_runtime_manager_dirs()
    _atomic_write_text(PID_PATH, str(int(pid)))


def load_pid() -> int:
    if not PID_PATH.exists():
        return 0
    try:
        return int(_read_text_with_retry(PID_PATH, encoding="utf-8").strip() or "0")
    except (OSError, ValueError):
        return 0


def clear_pid(expected_pid: int | None = None) -> None:
    if expected_pid is not None and load_pid() != int(expected_pid):
        return
    try:
        PID_PATH.unlink(missing_ok=True)
    except OSError:
        pass
