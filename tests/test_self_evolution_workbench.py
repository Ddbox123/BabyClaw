#!/usr/bin/env python3
"""Agent 自进化 workbench helper tests."""

import json
import sqlite3
from pathlib import Path

from core.evaluation.self_evolution_workbench import (
    build_self_evolution_preview,
    build_self_evolution_worktree_snapshot,
    format_self_evolution_audit_excerpt,
    format_self_evolution_preview,
    format_self_evolution_transaction_history,
    format_self_evolution_worktree_snapshot,
    list_recent_self_evolution_transactions,
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
    )

    assert "goal: 开始自主进化" in rendered
    assert "git status:" in rendered
    assert "dirty: core/ui/workbench.py" in rendered
    assert "- M core/ui/workbench.py | refine evolution menu" in rendered
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

    rendered = build_self_evolution_preview(goal="自定义进化目标")

    assert "goal: 自定义进化目标" in rendered
    assert "status-limit=5" in rendered
    assert "- M agent.py | touch agent loop" in rendered
    assert "success_rate=1.0" in rendered


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

    assert "audit log:" in rendered
    assert "txn_opened txn-1 base_rev=abcdef123456" in rendered
    assert "validation_completed txn-1 kind=lint passed=True" in rendered
