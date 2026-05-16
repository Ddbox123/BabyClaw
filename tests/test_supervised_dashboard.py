#!/usr/bin/env python3
"""Supervised evolution dashboard tests."""

import json
from pathlib import Path

from core.evaluation.supervised_dashboard import build_supervised_dashboard, generate_supervised_dashboard


def test_generate_supervised_dashboard_renders_empty_state(tmp_path: Path):
    dashboard = generate_supervised_dashboard(project_root=tmp_path)

    html = Path(dashboard.html_path).read_text(encoding="utf-8")
    assert dashboard.session_count == 0
    assert "暂无监督进化记录" in html
    assert "agent_consumption: advisory" in html
    assert "runtime_authorization: none" in html


def test_generate_supervised_dashboard_renders_normal_decision_summary(tmp_path: Path):
    decision_path = _write_decision(
        tmp_path,
        "supervised_hold",
        {
            "decision": "HOLD",
            "reason": "baseline 与 candidate 持平",
            "baseline_success_rate": 1.0,
            "candidate_success_rate": 1.0,
            "score_delta": 0.0,
            "gates": [{"name": "survival", "status": "pass", "reason": "持平"}],
        },
    )

    dashboard = generate_supervised_dashboard(project_root=tmp_path)

    html = Path(dashboard.html_path).read_text(encoding="utf-8")
    assert dashboard.session_count == 1
    assert "supervised_hold" in html
    assert "HOLD" in html
    assert "baseline 与 candidate 持平" in html
    assert "survival" in html
    assert str(decision_path) in html


def test_generate_supervised_dashboard_highlights_drift_risk(tmp_path: Path):
    _write_decision(
        tmp_path,
        "supervised_rollback",
        {
            "decision": "ROLLBACK",
            "reason": "candidate 在监督进化 dry-run 中退化",
            "baseline_success_rate": 1.0,
            "candidate_success_rate": 0.0,
            "score_delta": -1.0,
            "gates": [
                {
                    "name": "safety",
                    "status": "fail",
                    "reason": "candidate 出现失败，触发回滚保护",
                }
            ],
        },
    )

    html = Path(generate_supervised_dashboard(project_root=tmp_path).html_path).read_text(encoding="utf-8")

    assert "高风险" in html
    assert "candidate 出现失败，触发回滚保护" in html
    assert "safety" in html


def test_generate_supervised_dashboard_skips_broken_json(tmp_path: Path):
    _write_decision(tmp_path, "supervised_good", {"decision": "PROMOTE", "reason": "通过"})
    decisions_dir = tmp_path / "workspace" / "supervised_evolution" / "decisions"
    (decisions_dir / "broken.json").write_text("{broken", encoding="utf-8")

    dashboard = generate_supervised_dashboard(project_root=tmp_path)
    html = Path(dashboard.html_path).read_text(encoding="utf-8")

    assert dashboard.session_count == 1
    assert dashboard.skipped_count == 1
    assert "supervised_good" in html
    assert "跳过损坏记录：1" in html


def test_build_supervised_dashboard_marks_agent_contract():
    html = build_supervised_dashboard(records=[], skipped_count=0)

    assert "仅供监督观察，不代表自动授权" in html
    assert "agent_consumption: advisory" in html
    assert "runtime_authorization: none" in html


def _write_decision(tmp_path: Path, session_id: str, overrides: dict) -> Path:
    decisions_dir = tmp_path / "workspace" / "supervised_evolution" / "decisions"
    decisions_dir.mkdir(parents=True, exist_ok=True)
    path = decisions_dir / f"{session_id}.json"
    payload = {
        "session_id": session_id,
        "bundle_name": "demo_bundle",
        "decision": "HOLD",
        "reason": "tie",
        "ended_at": "2026-05-16T00:00:00Z",
        "baseline_success_rate": 1.0,
        "candidate_success_rate": 1.0,
        "score_delta": 0.0,
        "baseline_summary": {"validation_failed": 0, "total_guarded_tools": 2, "avg_wall_clock_seconds": 1.0},
        "candidate_summary": {"validation_failed": 0, "total_guarded_tools": 2, "avg_wall_clock_seconds": 1.0},
        "case_summaries": [
            {
                "case_id": "case_1",
                "baseline_status": "success",
                "candidate_status": "success",
                "decision_signal": "stable_success",
            }
        ],
        "gates": [],
        "decision_path": str(path),
        "policy_action": {"lineage_index_path": str(tmp_path / "workspace" / "lineage.json")},
    }
    payload.update(overrides)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
