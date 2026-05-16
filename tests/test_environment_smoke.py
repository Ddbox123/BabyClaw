#!/usr/bin/env python3
"""
稳定环境 smoke 验证
"""

import sys
from pathlib import Path

import pytest

from config import Settings
from core.infrastructure.workspace_manager import get_workspace
from tools.shell_tools import execute_shell_command


PROJECT_ROOT = Path(__file__).parent.parent

pytestmark = pytest.mark.environment_smoke


def test_config_smoke_loads():
    config = Settings().config

    assert config.runtime.profile == "safe_remote"
    assert config.runtime.preflight_doctor is True
    assert config.runtime.require_venv is True


def test_boot_prerequisites_exist():
    assert (PROJECT_ROOT / "agent.py").exists()
    assert (PROJECT_ROOT / "scripts" / "doctor.ps1").exists()
    assert (PROJECT_ROOT / ".venv" / "Scripts" / "python.exe").exists()


def test_workspace_can_initialize():
    workspace = get_workspace()
    status = workspace.get_workspace_status()

    assert workspace.root.exists()
    assert workspace.db_path.exists()
    assert Path(status["workspace_root"]).exists()


def test_shell_safety_is_active():
    result = execute_shell_command("rm -rf /", timeout=1, check_safety=True)

    assert "[安全拦截]" in result
    assert "禁止执行" in result


def test_running_inside_project_venv():
    """验证运行在项目虚拟环境中（如果配置了 require_venv）。"""
    expected = (PROJECT_ROOT / ".venv" / "Scripts" / "python.exe").resolve()
    if not expected.exists():
        pytest.skip(".venv not initialized, skip venv check")
    if Path(sys.executable).resolve() != expected:
        pytest.skip(f"running with {sys.executable!s}, not in .venv")
