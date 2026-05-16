#!/usr/bin/env python3
"""监督进化 CLI 选择数据集测试。"""

from pathlib import Path
from types import SimpleNamespace

from core.evaluation.supervised_cli import choose_dataset_interactively, run_supervised_cli_from_args, should_handle_supervised_cli


def test_choose_dataset_interactively_accepts_number(monkeypatch, tmp_path: Path):
    rows = [
        {
            "name": "supervised_dry_run",
            "available": True,
            "runnable": True,
            "adapter_status": "ready",
            "bundle_name": "supervised_evolution_dry_run_v1",
            "description": "dry",
        },
        {
            "name": "custom_prompt_jsonl",
            "available": True,
            "runnable": True,
            "adapter_status": "ready",
            "bundle_name": "custom_prompt_jsonl_v1",
            "description": "custom",
        },
    ]
    monkeypatch.setattr("core.evaluation.supervised_cli.list_dataset_status", lambda project_root: rows)
    answers = iter(["2", "5"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))

    dataset_name, limit = choose_dataset_interactively(project_root=tmp_path)

    assert dataset_name == "custom_prompt_jsonl"
    assert limit == 5


def test_choose_dataset_interactively_accepts_name_and_empty_limit(monkeypatch, tmp_path: Path):
    rows = [
        {
            "name": "supervised_dry_run",
            "available": True,
            "runnable": True,
            "adapter_status": "ready",
            "bundle_name": "supervised_evolution_dry_run_v1",
            "description": "dry",
        }
    ]
    monkeypatch.setattr("core.evaluation.supervised_cli.list_dataset_status", lambda project_root: rows)
    answers = iter(["supervised_dry_run", ""])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))

    dataset_name, limit = choose_dataset_interactively(project_root=tmp_path)

    assert dataset_name == "supervised_dry_run"
    assert limit is None


def test_supervised_cli_generates_dashboard(monkeypatch, tmp_path: Path, capsys):
    calls = []

    class Result:
        html_path = str(tmp_path / "workspace" / "supervised_evolution" / "dashboard" / "index.html")
        session_count = 2
        skipped_count = 1
        latest_decision = "HOLD"
        risk_level = "medium"
        agent_consumption = "advisory"
        runtime_authorization = "none"

    monkeypatch.setattr(
        "core.evaluation.supervised_cli.generate_supervised_dashboard",
        lambda **kwargs: calls.append(kwargs) or Result(),
    )

    args = SimpleNamespace(supervised_dashboard=True, open_dashboard=False)

    assert should_handle_supervised_cli(args) is True
    assert run_supervised_cli_from_args(args=args, project_root=tmp_path) == 0

    output = capsys.readouterr().out
    assert "index.html" in output
    assert "advisory" in output
    assert calls == [{"project_root": tmp_path}]
