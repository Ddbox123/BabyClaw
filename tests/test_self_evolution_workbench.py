#!/usr/bin/env python3
"""Agent 自进化 workbench helper tests."""

import json
import sqlite3
from pathlib import Path

from core.evaluation.self_evolution_workbench import (
    SelfEvolutionTransactionRecord,
    build_self_evolution_preview,
    build_self_evolution_run_prompt,
    build_self_evolution_snapshot,
    build_self_evolution_worktree_snapshot,
    format_self_evolution_audit_excerpt,
    format_self_evolution_preview,
    format_self_evolution_run_prompt,
    format_self_evolution_transaction_history,
    format_self_evolution_worktree_snapshot,
    list_recent_self_evolution_transaction_payloads,
    list_recent_self_evolution_transactions,
    load_self_evolution_audit_records,
)


def test_format_self_evolution_preview_renders_goal_changes_and_fitness():
    rendered = format_self_evolution_preview(
        goal="开始自主进化",
        status_summary="dirty: core/ui/workbench.py",
        recent_changes_json=(
            '[{"path":"core/ui/workbench.py","change_type":"M","summary":"refine evolution menu"}]'
        ),
        fitness_json=(
            '{"transactions":{"opened":2,"closed":2,"successful":1,"failed":1,"success_rate":0.5,'
            '"recent":[{"txn_id":"txn_1","status":"success","validation_passed":2,"validation_failed":0,'
            '"mutations_recorded":1}]},'
            '"validation":{"passed":3,"failed":1,"pass_rate":0.75},'
            '"mutations":{"recorded":2,"successful":1,"failed":1,"blocked":0}}'
        ),
        advisory_lines=["当前记住 1 个 active advisory baseline", "- local_transaction_closing_v1 proposal=p1"],
        worktree_snapshot_json=json.dumps(
            {
                "snapshot_id": "snap-1",
                "created_at": "2026-05-01T00:00:00",
                "base_rev": "abcdef1234567890",
                "has_staged": True,
                "has_unstaged": True,
                "has_untracked": False,
                "available": True,
                "files": [
                    {
                        "path": "core/ui/workbench.py",
                        "status": "M",
                        "staged": True,
                        "unstaged": False,
                        "untracked": False,
                        "deleted": False,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        recent_transactions=[
            SelfEvolutionTransactionRecord(
                txn_id="txn-1",
                opened_at="2026-05-01T00:00:00",
                closed_at="2026-05-01T00:00:10",
                base_rev="abcdef123456",
                status="success",
                summary="touch core loop",
            )
        ],
    )

    assert "goal: 开始自主进化" in rendered
    assert "agent view:" in rendered
    assert "当前记住 1 个 active advisory baseline" in rendered
    assert "git status:" in rendered
    assert "dirty: core/ui/workbench.py" in rendered
    assert "- M core/ui/workbench.py | refine evolution menu" in rendered
    assert "current worktree:" in rendered
    assert "snapshot: snap-1" in rendered
    assert "- M core/ui/workbench.py (staged)" in rendered
    assert "recent transactions:" in rendered
    assert "txn-1 status=success" in rendered
    assert "transactions: opened=2 closed=2 success=1 failed=1 success_rate=0.5" in rendered
    assert "- recent txn_1 status=success validation=2/0 mutations=1" in rendered


def test_build_self_evolution_preview_uses_tool_outputs(monkeypatch):
    monkeypatch.setattr(
        "core.evaluation.self_evolution_workbench.get_git_status_summary_tool",
        lambda limit=5: f"status-limit={limit}",
    )
    monkeypatch.setattr(
        "core.evaluation.self_evolution_workbench.get_recent_changes_tool",
        lambda limit=3: '[{"path":"agent.py","change_type":"M","summary":"touch agent loop"}]',
    )
    monkeypatch.setattr(
        "core.evaluation.self_evolution_workbench.get_evolution_fitness_tool",
        lambda recent_limit=3: (
            '{"transactions":{"opened":1,"closed":1,"successful":1,"failed":0,"success_rate":1.0,"recent":[]},'
            '"validation":{"passed":1,"failed":0,"pass_rate":1.0},'
            '"mutations":{"recorded":1,"successful":1,"failed":0,"blocked":0}}'
        ),
    )
    monkeypatch.setattr(
        "core.evaluation.self_evolution_workbench.explain_current_worktree_tool",
        lambda: json.dumps(
            {
                "snapshot_id": "snap-2",
                "created_at": "2026-05-01T00:00:00",
                "base_rev": "abc",
                "has_staged": False,
                "has_unstaged": True,
                "has_untracked": False,
                "available": True,
                "files": [
                    {
                        "path": "agent.py",
                        "status": "M",
                        "staged": False,
                        "unstaged": True,
                        "untracked": False,
                        "deleted": False,
                    }
                ],
            },
            ensure_ascii=False,
        ),
    )
    monkeypatch.setattr(
        "core.evaluation.self_evolution_workbench.summarize_active_advisory_baselines",
        lambda limit=3: ["当前记住 1 个 active advisory baseline", "- local_transaction_closing_v1 proposal=p1"],
    )
    monkeypatch.setattr(
        "core.evaluation.self_evolution_workbench.list_recent_self_evolution_transactions",
        lambda project_root, limit=3: [
            SelfEvolutionTransactionRecord(
                txn_id="txn-2",
                opened_at="2026-05-01T00:00:00",
                closed_at="2026-05-01T00:00:20",
                base_rev="abc",
                status="success",
                summary="touch agent loop",
            )
        ],
    )

    rendered = build_self_evolution_preview(goal="自定义进化目标")

    assert "goal: 自定义进化目标" in rendered
    assert "agent view:" in rendered
    assert "local_transaction_closing_v1" in rendered
    assert "status-limit=5" in rendered
    assert "- M agent.py | touch agent loop" in rendered
    assert "current worktree:" in rendered
    assert "snapshot: snap-2" in rendered
    assert "recent transactions:" in rendered
    assert "txn-2 status=success" in rendered
    assert "success_rate=1.0" in rendered


def test_format_self_evolution_run_prompt_renders_advisory_guardrails_and_fitness():
    rendered = format_self_evolution_run_prompt(
        goal="开始自主进化",
        advisory_lines=["当前记住 1 个 active advisory baseline", "- local_transaction_closing_v1 proposal=p1"],
        fitness_json=(
            '{"transactions":{"opened":2,"closed":2,"successful":1,"failed":1,"success_rate":0.5,"recent":[]},'
            '"validation":{"passed":3,"failed":1,"pass_rate":0.75},'
            '"mutations":{"recorded":2,"successful":1,"failed":1,"blocked":0}}'
        ),
        worktree_snapshot_json=json.dumps(
            {
                "snapshot_id": "snap-3",
                "created_at": "2026-05-01T00:00:00",
                "base_rev": "def",
                "has_staged": False,
                "has_unstaged": True,
                "has_untracked": True,
                "available": True,
                "files": [
                    {
                        "path": "core/evaluation/self_evolution_workbench.py",
                        "status": "M",
                        "staged": False,
                        "unstaged": True,
                        "untracked": False,
                        "deleted": False,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        recent_transactions=[
            SelfEvolutionTransactionRecord(
                txn_id="txn-3",
                opened_at="2026-05-01T00:00:00",
                closed_at=None,
                base_rev="def",
                status="running",
                summary="inspect worktree before mutation",
            )
        ],
    )

    assert rendered.startswith("开始自主进化")
    assert "观察参照" in rendered
    assert "runtime rewrite" in rendered
    assert "共享现场" in rendered
    assert "local_transaction_closing_v1" in rendered
    assert "当前工作区快照:" in rendered
    assert "snapshot: snap-3" in rendered
    assert "最近自进化事务:" in rendered
    assert "txn-3 status=running" in rendered
    assert "transactions: opened=2 closed=2 success=1 failed=1 success_rate=0.5" in rendered


def test_build_self_evolution_run_prompt_uses_advisory_and_fitness(monkeypatch):
    monkeypatch.setattr(
        "core.evaluation.self_evolution_workbench.summarize_active_advisory_baselines",
        lambda limit=3: ["当前记住 1 个 active advisory baseline", "- local_transaction_closing_v1 proposal=p1"],
    )
    monkeypatch.setattr(
        "core.evaluation.self_evolution_workbench.get_evolution_fitness_tool",
        lambda recent_limit=3: (
            '{"transactions":{"opened":1,"closed":1,"successful":1,"failed":0,"success_rate":1.0,"recent":[]},'
            '"validation":{"passed":1,"failed":0,"pass_rate":1.0},'
            '"mutations":{"recorded":1,"successful":1,"failed":0,"blocked":0}}'
        ),
    )
    monkeypatch.setattr(
        "core.evaluation.self_evolution_workbench.explain_current_worktree_tool",
        lambda: json.dumps(
            {
                "snapshot_id": "snap-4",
                "created_at": "2026-05-01T00:00:00",
                "base_rev": "ghi",
                "has_staged": False,
                "has_unstaged": False,
                "has_untracked": False,
                "available": True,
                "files": [],
            },
            ensure_ascii=False,
        ),
    )
    monkeypatch.setattr(
        "core.evaluation.self_evolution_workbench.list_recent_self_evolution_transactions",
        lambda project_root, limit=2: [
            SelfEvolutionTransactionRecord(
                txn_id="txn-4",
                opened_at="2026-05-01T00:00:00",
                closed_at="2026-05-01T00:00:05",
                base_rev="ghi",
                status="success",
                summary="clean start",
            )
        ],
    )

    rendered = build_self_evolution_run_prompt(goal="自定义进化目标")

    assert rendered.startswith("自定义进化目标")
    assert "local_transaction_closing_v1" in rendered
    assert "当前工作区快照:" in rendered
    assert "snapshot: snap-4" in rendered
    assert "txn-4 status=success" in rendered
    assert "success_rate=1.0" in rendered


def test_build_self_evolution_snapshot_returns_structured_payload(monkeypatch):
    monkeypatch.setattr(
        "core.evaluation.self_evolution_workbench.get_git_status_summary_tool",
        lambda limit=5: f"status-limit={limit}",
    )
    monkeypatch.setattr(
        "core.evaluation.self_evolution_workbench.get_recent_changes_tool",
        lambda limit=3: '[{"path":"agent.py","change_type":"M","summary":"touch agent loop"}]',
    )
    monkeypatch.setattr(
        "core.evaluation.self_evolution_workbench.get_evolution_fitness_tool",
        lambda recent_limit=3: (
            '{"transactions":{"opened":1,"closed":1,"successful":1,"failed":0,"success_rate":1.0,"recent":[]},'
            '"validation":{"passed":1,"failed":0,"pass_rate":1.0},'
            '"mutations":{"recorded":1,"successful":1,"failed":0,"blocked":0}}'
        ),
    )
    monkeypatch.setattr(
        "core.evaluation.self_evolution_workbench.explain_current_worktree_tool",
        lambda: json.dumps(
            {
                "snapshot_id": "snap-7",
                "created_at": "2026-05-01T00:00:00",
                "base_rev": "abc",
                "has_staged": False,
                "has_unstaged": True,
                "has_untracked": False,
                "available": True,
                "files": [
                    {
                        "path": "agent.py",
                        "status": "M",
                        "staged": False,
                        "unstaged": True,
                        "untracked": False,
                        "deleted": False,
                    }
                ],
            },
            ensure_ascii=False,
        ),
    )
    monkeypatch.setattr(
        "core.evaluation.self_evolution_workbench.build_active_advisory_snapshot",
        lambda project_root=None, limit=3: {
            "active_count": 1,
            "entries": [{"target_key": "target:a", "target_label": "local_transaction_closing_v1"}],
        },
    )
    monkeypatch.setattr(
        "core.evaluation.self_evolution_workbench.list_recent_self_evolution_transaction_payloads",
        lambda project_root, limit=3: [
            {
                "txn_id": "txn-7",
                "opened_at": "2026-05-01T00:00:00",
                "closed_at": "2026-05-01T00:00:10",
                "base_rev": "abcdef123456",
                "base_rev_short": "abcdef123456",
                "status": "success",
                "summary": "touch agent loop",
                "is_open": False,
            }
        ],
    )

    snapshot = build_self_evolution_snapshot(goal="自定义进化目标")

    assert snapshot["goal"] == "自定义进化目标"
    assert snapshot["advisory"]["active_count"] == 1
    assert snapshot["git_status"]["lines"][0] == "status-limit=5"
    assert snapshot["recent_changes"][0]["path"] == "agent.py"
    assert snapshot["fitness"]["transactions"]["success_rate"] == 1.0
    assert snapshot["worktree"]["snapshot_id"] == "snap-7"
    assert snapshot["worktree"]["is_dirty"] is True
    assert snapshot["recent_transactions"][0]["txn_id"] == "txn-7"


def test_format_self_evolution_worktree_snapshot_renders_files():
    rendered = format_self_evolution_worktree_snapshot(
        json.dumps(
            {
                "snapshot_id": "snap-1",
                "created_at": "2026-05-01T00:00:00",
                "base_rev": "abcdef1234567890",
                "has_staged": True,
                "has_unstaged": True,
                "has_untracked": False,
                "available": True,
                "files": [
                    {
                        "path": "core/ui/workbench.py",
                        "status": "M",
                        "staged": True,
                        "unstaged": False,
                        "untracked": False,
                        "deleted": False,
                    }
                ],
            },
            ensure_ascii=False,
        )
    )

    assert "snapshot: snap-1" in rendered
    assert "dirty flags: staged=True unstaged=True untracked=False" in rendered
    assert "- M core/ui/workbench.py (staged)" in rendered


def test_build_self_evolution_worktree_snapshot_uses_tool(monkeypatch):
    monkeypatch.setattr(
        "core.evaluation.self_evolution_workbench.explain_current_worktree_tool",
        lambda: json.dumps(
            {
                "snapshot_id": "snap-2",
                "created_at": "2026-05-01T00:00:00",
                "base_rev": "abc",
                "has_staged": False,
                "has_unstaged": False,
                "has_untracked": False,
                "available": True,
                "files": [],
            },
            ensure_ascii=False,
        ),
    )

    rendered = build_self_evolution_worktree_snapshot()

    assert "snapshot: snap-2" in rendered
    assert "工作区干净" in rendered


def test_transaction_history_helpers_read_workspace_db(monkeypatch, tmp_path: Path):
    project_root = tmp_path / "project"
    workspace = project_root / "workspace"
    workspace.mkdir(parents=True)
    db_path = workspace / "agent_brain.db"
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            """
            CREATE TABLE EvolutionTransaction (
                txn_id TEXT PRIMARY KEY,
                opened_at TEXT NOT NULL,
                closed_at TEXT,
                base_rev TEXT,
                status TEXT NOT NULL,
                summary TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO EvolutionTransaction(txn_id, opened_at, closed_at, base_rev, status, summary)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("txn-1", "2026-05-01T00:00:00", "2026-05-01T00:00:10", "abcdef123456", "success", "touch core loop"),
        )

    records = list_recent_self_evolution_transactions(project_root)
    rendered = format_self_evolution_transaction_history(records)

    assert len(records) == 1
    assert "txn-1 status=success" in rendered
    assert "summary=touch core loop" in rendered

    payloads = list_recent_self_evolution_transaction_payloads(project_root)
    assert payloads[0]["txn_id"] == "txn-1"
    assert payloads[0]["base_rev_short"] == "abcdef123456"
    assert payloads[0]["is_open"] is False


def test_format_self_evolution_audit_excerpt_reads_tail(monkeypatch, tmp_path: Path):
    project_root = tmp_path / "project"
    audit_path = project_root / "workspace" / "evolution" / "audit.jsonl"
    audit_path.parent.mkdir(parents=True)
    audit_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-05-01T00:00:00Z",
                        "event": "txn_opened",
                        "txn_id": "txn-1",
                        "base_rev": "abcdef1234567890",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "timestamp": "2026-05-01T00:00:01Z",
                        "event": "validation_completed",
                        "txn_id": "txn-1",
                        "kind": "lint",
                        "passed": True,
                        "message": "ruff lint 通过",
                    },
                    ensure_ascii=False,
                ),
            ]
        ),
        encoding="utf-8",
    )

    rendered = format_self_evolution_audit_excerpt(project_root)
    records = load_self_evolution_audit_records(project_root)

    assert "audit log:" in rendered
    assert "txn_opened txn-1 base_rev=abcdef123456" in rendered
    assert "validation_completed txn-1 kind=lint passed=True" in rendered
    assert records[0]["txn_id"] == "txn-1"
    assert records[1]["kind"] == "lint"
