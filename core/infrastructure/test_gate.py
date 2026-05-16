# -*- coding: utf-8 -*-
"""Evolution test gate — runs pytest before self-restart to prevent broken code propagation."""

import subprocess
import sys
from pathlib import Path
from typing import Tuple

from core.infrastructure.agent_session import get_session_state
from core.infrastructure.event_bus import EventNames, get_event_bus


def _resolve_project_root() -> Path:
    p = Path(__file__).parent.parent.parent.resolve()
    if (p / "agent.py").exists():
        return p
    for sp in sys.path:
        if Path(sp, "agent.py").exists():
            return Path(sp).resolve()
    return p


def check_evolution_ready(timeout: int = 120) -> Tuple[bool, str]:
    """Run pytest suite. Returns (passed, message). Called before self-restart.

    Args:
        timeout: max seconds for test run (default 120)

    Returns:
        (passed, message) — passed=True means all tests green
    """
    project_root = _resolve_project_root()
    bus = get_event_bus()
    session = get_session_state()
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "-x", "--tb=short", "-q"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            message = "All tests passed"
            session.record_validation_result(message, True)
            bus.publish(EventNames.VALIDATION_COMPLETED, {"kind": "tests", "passed": True, "message": message}, source="test_gate")
            return True, message
        # Extract failed test summary
        output = result.stdout + result.stderr
        message = f"Tests failed (exit {result.returncode})\n{output[-1200:]}"
        session.record_validation_result(message, False)
        bus.publish(EventNames.VALIDATION_COMPLETED, {"kind": "tests", "passed": False, "message": message}, source="test_gate")
        return False, message
    except subprocess.TimeoutExpired:
        message = f"Test gate timed out after {timeout}s"
        session.record_validation_result(message, False)
        bus.publish(EventNames.VALIDATION_COMPLETED, {"kind": "tests", "passed": False, "message": message}, source="test_gate")
        return False, message
    except Exception as e:
        message = f"Test gate error: {e}"
        session.record_validation_result(message, False)
        bus.publish(EventNames.VALIDATION_COMPLETED, {"kind": "tests", "passed": False, "message": message}, source="test_gate")
        return False, message


def check_environment_ready(timeout: int = 90) -> Tuple[bool, str]:
    """Run the stable environment smoke gate before restart/self-evolution."""
    project_root = _resolve_project_root()
    runner_path = project_root / "tests" / "test_runner.py"
    bus = get_event_bus()
    session = get_session_state()
    try:
        result = subprocess.run(
            [sys.executable, str(runner_path), "--environment-smoke"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            message = "Environment smoke passed"
            session.record_validation_result(message, True)
            bus.publish(EventNames.VALIDATION_COMPLETED, {"kind": "environment", "passed": True, "message": message}, source="test_gate")
            return True, message
        output = result.stdout + result.stderr
        message = f"Environment smoke failed (exit {result.returncode})\n{output[-1200:]}"
        session.record_validation_result(message, False)
        bus.publish(EventNames.VALIDATION_COMPLETED, {"kind": "environment", "passed": False, "message": message}, source="test_gate")
        return False, message
    except subprocess.TimeoutExpired:
        message = f"Environment smoke timed out after {timeout}s"
        session.record_validation_result(message, False)
        bus.publish(EventNames.VALIDATION_COMPLETED, {"kind": "environment", "passed": False, "message": message}, source="test_gate")
        return False, message
    except Exception as e:
        message = f"Environment smoke error: {e}"
        session.record_validation_result(message, False)
        bus.publish(EventNames.VALIDATION_COMPLETED, {"kind": "environment", "passed": False, "message": message}, source="test_gate")
        return False, message
