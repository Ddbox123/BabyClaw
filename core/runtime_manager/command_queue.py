"""File-backed command queue for the runtime manager."""

from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .constants import (
    DEFAULT_COMMAND_WAIT_SECONDS,
    INBOX_DIR,
    PROCESSING_DIR,
    RESULTS_DIR,
    ensure_runtime_manager_dirs,
)


def _command_timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def build_command(command_type: str, *, args: dict[str, Any] | None = None, requested_by: str = "unknown") -> dict[str, Any]:
    return {
        "commandId": f"cmd_{_command_timestamp()}_{uuid4().hex[:8]}",
        "type": str(command_type or "").strip(),
        "requestedBy": str(requested_by or "unknown").strip() or "unknown",
        "requestedAt": datetime.now(UTC).isoformat(),
        "args": args or {},
    }


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    ensure_runtime_manager_dirs()
    fd, temp_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def submit_command(
    command_type: str,
    *,
    args: dict[str, Any] | None = None,
    requested_by: str = "unknown",
) -> dict[str, Any]:
    command = build_command(command_type, args=args, requested_by=requested_by)
    _atomic_write_json(INBOX_DIR / f"{command['commandId']}.json", command)
    return command


def wait_for_result(command_id: str, *, timeout_seconds: float = DEFAULT_COMMAND_WAIT_SECONDS) -> dict[str, Any]:
    deadline = time.monotonic() + max(0.5, float(timeout_seconds))
    result_path = RESULTS_DIR / f"{command_id}.json"
    while time.monotonic() < deadline:
        if result_path.exists():
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
            break
        time.sleep(0.2)
    raise TimeoutError(f"Timed out waiting for runtime-manager command {command_id}.")


def recover_processing_queue() -> None:
    ensure_runtime_manager_dirs()
    for path in sorted(PROCESSING_DIR.glob("*.json")):
        target = INBOX_DIR / path.name
        try:
            os.replace(path, target)
        except OSError:
            continue


def claim_next_command() -> tuple[Path, dict[str, Any]] | None:
    ensure_runtime_manager_dirs()
    for path in sorted(INBOX_DIR.glob("*.json")):
        target = PROCESSING_DIR / path.name
        try:
            os.replace(path, target)
        except OSError:
            continue
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        if isinstance(payload, dict):
            return target, payload
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
    return None


def complete_command(path: Path, result: dict[str, Any]) -> None:
    command_id = str(result.get("commandId") or path.stem).strip() or path.stem
    _atomic_write_json(RESULTS_DIR / f"{command_id}.json", result)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
