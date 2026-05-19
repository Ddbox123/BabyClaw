"""Shared paths and defaults for the runtime manager."""

from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_MANAGER_DIR = PROJECT_ROOT / ".runtime" / "runtime-manager"
INBOX_DIR = RUNTIME_MANAGER_DIR / "inbox"
PROCESSING_DIR = RUNTIME_MANAGER_DIR / "processing"
RESULTS_DIR = RUNTIME_MANAGER_DIR / "results"
STATE_PATH = RUNTIME_MANAGER_DIR / "state.json"
PID_PATH = RUNTIME_MANAGER_DIR / "daemon.pid"
EVENTS_PATH = RUNTIME_MANAGER_DIR / "events.jsonl"
DAEMON_STDOUT_PATH = RUNTIME_MANAGER_DIR / "daemon.out.log"
DAEMON_STDERR_PATH = RUNTIME_MANAGER_DIR / "daemon.err.log"

LAUNCHER_SCRIPT_PATH = PROJECT_ROOT / "scripts" / "vibelution_launcher.ps1"
LAUNCHER_STATE_PATH = PROJECT_ROOT / ".runtime" / "launcher" / "state.json"

DEFAULT_HOST = "127.0.0.1"


def _read_default_port() -> int:
    raw_value = str(os.environ.get("VIBELUTION_PORT") or "").strip()
    try:
        port = int(raw_value)
    except ValueError:
        return 8000
    return port if 0 < port < 65536 else 8000


DEFAULT_PORT = _read_default_port()
DEFAULT_URL = f"http://{DEFAULT_HOST}:{DEFAULT_PORT}"
DEFAULT_HEALTH_URL = f"{DEFAULT_URL}/api/health"

DAEMON_LOOP_INTERVAL_SECONDS = 0.45
DEFAULT_COMMAND_WAIT_SECONDS = 45.0


def ensure_runtime_manager_dirs() -> None:
    """Create the runtime-manager directory tree if it is missing."""

    for path in (RUNTIME_MANAGER_DIR, INBOX_DIR, PROCESSING_DIR, RESULTS_DIR):
        path.mkdir(parents=True, exist_ok=True)
