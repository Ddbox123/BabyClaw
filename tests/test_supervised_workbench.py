#!/usr/bin/env python3
"""Supervised Evolution workbench helper tests."""

import json
from pathlib import Path
from types import SimpleNamespace

from core.evaluation.supervised_workbench import (
    format_bundle_preview,
    format_decision_history,
    format_file_excerpt,
    format_lineage_summary,
    list_recent_decision_records,
    prepare_dataset_run,
    run_workbench_session,
    select_dataset_by_input,
    select_decision_record,
)


def test_format_lineage_summary_reads_index(tmp_path: Path):
    index_path = tmp_path / "lineage_index.json"
    index_path.write_text(
        json.dumps(
            {
                "case_count": 1,
                "cases": [
                    {
                        "bundle_name": "demo_bundle",
                        "case_id": "probe",
                        "current_baseline_id": "baseline_a",
                        "latest_candidate_id": "candidate_b",
                        "chain": [
                            {"status": "observing", "observation_count": 2},
                            {"status": "promoted", "observation_count": 1},
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    rendered = format_lineage_summary(str(index_path), "demo_bundle")

    assert "bundle cases: 1" in rendered
    assert "- probe: baseline=baseline_a latest=candidate_b" in rendered
    assert "observing[2] -> promoted[1]" in rendered


def test_format_lineage_summary_handles_missing_index():
    rendered = format_lineage_summary("C:/missing/lineage_index.json", "demo_bundle")

    assert rendered == "lineage index 不可用"


def test_select_dataset_by_input_accepts_index_name_and_default():
    datasets = [
        {"name": "first"},
        {"name": "second"},
    ]

    assert select_dataset_by_input(datasets, "")["name"] == "first"
    assert select_dataset_by_input(datasets, "2")["name"] == "second"
    assert select_dataset_by_input(datasets, "second")["name"] == "second"
    assert select_dataset_by_input(datasets, "missing") is None


def test_prepare_dataset_run_returns_runnable_bundle(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        "core.evaluation.dataset_registry.materialize_dataset_bundle",
        lambda *args, **kwargs: SimpleNamespace(
            dataset_name="custom_prompt_jsonl",
            runnable=True,
            adapter_status="ready",
            bundle_name="custom_prompt_jsonl_v1",
            case_count=2,
            bundle_path=str(tmp_path / "workspace" / "evaluation" / "bundles" / "custom_prompt_jsonl_v1.json"),
        ),
    )

    prepared = prepare_dataset_run(tmp_path, "custom_prompt_jsonl", 2)

    assert prepared.bundle_name == "custom_prompt_jsonl_v1"
    assert prepared.runnable is True
    assert prepared.blocked_message == ""
    assert "dataset: custom_prompt_jsonl" in prepared.summary


def test_prepare_dataset_run_returns_blocked_reason(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        "core.evaluation.dataset_registry.materialize_dataset_bundle",
        lambda *args, **kwargs: SimpleNamespace(
            dataset_name="swe_bench_lite",
            runnable=False,
            adapter_status="requires_swe_harness",
            bundle_name="swe_bench_lite_v1",
            case_count=0,
            bundle_path="",
        ),
    )

    prepared = prepare_dataset_run(tmp_path, "swe_bench_lite", None)

    assert prepared.runnable is False
    assert prepared.adapter_status == "requires_swe_harness"
    assert "requires_swe_harness" in prepared.blocked_message


def test_run_workbench_session_wraps_decision_summary(monkeypatch):
    decision = SimpleNamespace(
        decision="HOLD",
        bundle_name="demo_bundle",
        policy_action={},
    )
    calls = []
    monkeypatch.setattr(
        "core.evaluation.supervised_evolution.run_supervised_evolution_session",
        lambda **kwargs: calls.append(kwargs) or decision,
    )
    monkeypatch.setattr(
        "core.evaluation.supervised_evolution.format_decision_record_summary",
        lambda item: f"summary:{item.decision}",
    )

    result = run_workbench_session("demo_bundle", keep_worktree=True)

    assert result.decision is decision
    assert result.decision_summary == "summary:HOLD"
    assert result.result_border_style == "green"
    assert result.lineage_index_path is None
    assert calls == [{"bundle_name": "demo_bundle", "keep_worktree": True}]


def test_run_workbench_session_forwards_progress_callback(monkeypatch):
    decision = SimpleNamespace(
        decision="HOLD",
        bundle_name="demo_bundle",
        policy_action={},
    )
    calls = []
    events = []

    def fake_run(**kwargs):
        calls.append(kwargs)
        kwargs["progress_callback"]({"event": "role_start"})
        return decision

    monkeypatch.setattr("core.evaluation.supervised_evolution.run_supervised_evolution_session", fake_run)
    monkeypatch.setattr(
        "core.evaluation.supervised_evolution.format_decision_record_summary",
        lambda item: f"summary:{item.decision}",
    )

    callback = events.append

    result = run_workbench_session("demo_bundle", keep_worktree=True, progress_callback=callback)

    assert result.decision is decision
    assert events == [{"event": "role_start"}]
    assert calls[0]["progress_callback"] is callback


def test_decision_history_helpers_sort_and_select(tmp_path: Path):
    decisions_dir = tmp_path / "workspace" / "supervised_evolution" / "decisions"
    decisions_dir.mkdir(parents=True)
    older = decisions_dir / "older.json"
    newer = decisions_dir / "newer.json"
    older.write_text(json.dumps({"session_id": "older", "decision": "HOLD"}), encoding="utf-8")
    newer.write_text(json.dumps({"session_id": "newer", "decision": "PROMOTE"}), encoding="utf-8")

    records = list_recent_decision_records(tmp_path)
    rendered = format_decision_history(records)

    assert records[0].session_id == "newer"
    assert select_decision_record(records, "1").session_id == "newer"
    assert select_decision_record(records, "older").session_id == "older"
    assert select_decision_record(records, "missing") is None
    assert "PROMOTE" in rendered


def test_format_bundle_preview_renders_case_summary(tmp_path: Path):
    bundle_path = tmp_path / "demo_bundle.json"
    bundle_path.write_text(
        json.dumps(
            {
                "benchmark": "demo",
                "bundle_name": "demo_bundle",
                "cases": [
                    {
                        "case_id": "case_1",
                        "scenario": "transaction",
                        "mode": "single_turn",
                        "candidate_prompt": "run lint",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    rendered = format_bundle_preview(str(bundle_path))

    assert "bundle: demo_bundle" in rendered
    assert "cases: 1" in rendered
    assert "- case_1 [transaction/single_turn] run lint" in rendered


def test_format_file_excerpt_truncates_long_file(tmp_path: Path):
    path = tmp_path / "decision.json"
    path.write_text("abcdef", encoding="utf-8")

    rendered = format_file_excerpt(str(path), limit=3)

    assert rendered.startswith("abc")
    assert "已截断" in rendered
