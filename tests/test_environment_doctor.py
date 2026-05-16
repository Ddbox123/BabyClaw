#!/usr/bin/env python3
"""
环境自检脚本回归测试
"""

import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).parent.parent
DOCTOR_SCRIPT = PROJECT_ROOT / "scripts" / "doctor.ps1"
EXPECTED_VENV_PYTHON = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"


def run_doctor():
    result = subprocess.run(
        [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(DOCTOR_SCRIPT),
            "-Json",
        ],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        timeout=30,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return json.loads(result.stdout)


def test_doctor_script_exists():
    assert DOCTOR_SCRIPT.exists()


def test_doctor_reports_expected_python_and_venv():
    report = run_doctor()

    assert report["ok"] is True
    assert Path(report["python"]["expected"]).resolve() == EXPECTED_VENV_PYTHON.resolve()
    assert Path(report["python"]["selected"]).resolve() == EXPECTED_VENV_PYTHON.resolve()
    assert report["checks"]["venv"]["ok"] is True


def test_doctor_reports_critical_imports_and_pytest():
    report = run_doctor()

    imports = {item["name"]: item["ok"] for item in report["checks"]["imports"]}
    assert imports["rich"] is True
    assert imports["pydantic"] is True
    assert imports["langchain_openai"] is True
    assert imports["pytest_asyncio"] is True

    pytest_check = report["checks"]["pytest_module"]
    assert pytest_check["ok"] is True
    assert "pytest" in pytest_check["version"].lower()
