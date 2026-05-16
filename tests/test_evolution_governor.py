from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from core.infrastructure import evolution_governor as governor_module
from core.infrastructure.event_bus import EventNames, get_event_bus
from tools.git_tools import get_evolution_fitness_tool


class _FakeWorkspace:
    def __init__(self, project_root: Path):
        self.project_root = project_root

    def get_prompt_path(self, name: str) -> Path:
        return self.project_root / "workspace" / "prompts" / name


def _patch_runtime(monkeypatch, tmp_path: Path) -> Path:
    project_root = tmp_path / "project"
    project_root.mkdir(parents=True, exist_ok=True)
    evolution = SimpleNamespace(
        allowed_target_dirs=["workspace/prompts/"],
        audit_log_path="workspace/evolution/audit.jsonl",
    )
    monkeypatch.setattr(governor_module, "get_config", lambda: SimpleNamespace(evolution=evolution))
    monkeypatch.setattr(governor_module, "get_workspace", lambda: _FakeWorkspace(project_root))
    governor_module._governor = None
    return project_root


def test_governor_blocks_mutation_outside_allowed_dirs(monkeypatch, tmp_path):
    project_root = _patch_runtime(monkeypatch, tmp_path)
    governor = governor_module.EvolutionGovernor()

    message = governor.check_mutation_allowed(
        "write_file_tool",
        {"file_path": "core/runtime.py", "content": "x"},
        "txn_demo",
    )

    assert message is not None
    assert "当前演化事务" in message
    audit_path = project_root / "workspace" / "evolution" / "audit.jsonl"
    records = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    assert records[-1]["event"] == "mutation_blocked"
    assert records[-1]["target_paths"] == ["core/runtime.py"]


def test_governor_records_complexity_for_dynamic_prompt_mutation(monkeypatch, tmp_path):
    project_root = _patch_runtime(monkeypatch, tmp_path)
    governor = governor_module.EvolutionGovernor()

    governor.record_mutation_result(
        "write_dynamic_prompt_tool",
        {"content": "hello"},
        '{"status":"success"}',
        "txn_demo",
    )

    audit_path = project_root / "workspace" / "evolution" / "audit.jsonl"
    records = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    assert records[-1]["event"] == "mutation_recorded"
    assert records[-1]["status"] == "success"
    assert records[-1]["target_paths"] == ["workspace/prompts/DYNAMIC.md"]
    assert records[-1]["complexity"]["complexity_units"] == 1


def test_governor_builds_fitness_summary_from_audit_events(monkeypatch, tmp_path):
    _patch_runtime(monkeypatch, tmp_path)
    governor = governor_module.EvolutionGovernor()
    bus = get_event_bus()

    bus.publish(EventNames.EVOLUTION_TXN_OPENED, {"txn_id": "txn_1", "base_rev": "abc"})
    governor.record_mutation_result(
        "write_dynamic_prompt_tool",
        {"content": "hello"},
        '{"status":"success"}',
        "txn_1",
    )
    bus.publish(EventNames.VALIDATION_COMPLETED, {"kind": "lint", "passed": True, "message": "ruff lint 通过"})
    bus.publish(EventNames.EVOLUTION_TXN_CLOSED, {"txn_id": "txn_1", "status": "success"})

    summary = governor.build_fitness_summary(recent_limit=3)

    assert summary["transactions"]["opened"] == 1
    assert summary["transactions"]["successful"] == 1
    assert summary["transactions"]["success_rate"] == 1.0
    assert summary["validation"]["passed"] == 1
    assert summary["validation"]["by_kind"]["lint"]["passed"] == 1
    assert summary["mutations"]["successful"] == 1


def test_get_evolution_fitness_tool_returns_summary_json(monkeypatch, tmp_path):
    _patch_runtime(monkeypatch, tmp_path)
    governor = governor_module.EvolutionGovernor()
    bus = get_event_bus()

    bus.publish(EventNames.EVOLUTION_TXN_OPENED, {"txn_id": "txn_2", "base_rev": "def"})
    governor.check_mutation_allowed(
        "write_file_tool",
        {"file_path": "core/runtime.py", "content": "x"},
        "txn_2",
    )
    bus.publish(EventNames.VALIDATION_COMPLETED, {"kind": "tests", "passed": False, "message": "1 failed"})
    bus.publish(EventNames.EVOLUTION_TXN_CLOSED, {"txn_id": "txn_2", "status": "failed"})

    payload = json.loads(get_evolution_fitness_tool(recent_limit=2))

    assert payload["transactions"]["failed"] == 1
    assert payload["mutations"]["blocked"] == 1
    assert payload["validation"]["failed"] == 1
