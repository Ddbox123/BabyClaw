"""Runtime manager helpers for the local workbench lifecycle."""

from __future__ import annotations


def ensure_daemon_running(*, python_executable: str | None = None) -> bool:
    from .daemon import ensure_daemon_running as _ensure_daemon_running

    return _ensure_daemon_running(python_executable=python_executable)


def is_daemon_running() -> bool:
    from .daemon import is_daemon_running as _is_daemon_running

    return _is_daemon_running()


def load_runtime_snapshot() -> dict:
    from .daemon import load_runtime_snapshot as _load_runtime_snapshot

    return _load_runtime_snapshot()


def submit_command(command_type: str, *, args: dict | None = None, requested_by: str = "unknown") -> dict:
    from .command_queue import submit_command as _submit_command

    return _submit_command(command_type, args=args, requested_by=requested_by)


def wait_for_result(command_id: str, *, timeout_seconds: float = 45.0) -> dict:
    from .command_queue import wait_for_result as _wait_for_result

    return _wait_for_result(command_id, timeout_seconds=timeout_seconds)


__all__ = [
    "ensure_daemon_running",
    "is_daemon_running",
    "load_runtime_snapshot",
    "submit_command",
    "wait_for_result",
]
