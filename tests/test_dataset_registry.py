#!/usr/bin/env python3
"""数据集注册与 bundle 物化测试。"""

import json
from pathlib import Path

import pytest

from core.evaluation.dataset_registry import (
    ensure_dataset_registry,
    list_dataset_status,
    materialize_dataset_bundle,
)


def test_default_dataset_registry_lists_builtin_and_swe(tmp_path: Path):
    path = ensure_dataset_registry(tmp_path)

    assert path.exists()
    rows = list_dataset_status(tmp_path)
    by_name = {item["name"]: item for item in rows}

    assert by_name["supervised_dry_run"]["runnable"] is True
    assert by_name["chat_reviewed_multiturn"]["runnable"] is True
    assert by_name["chat_reviewed_multiturn"]["review_required"] is True
    assert by_name["chat_reviewed_multiturn"]["source_track"] == "dialogue"
    assert by_name["chat_reviewed_multiturn"]["holdout_allowed"] is False
    assert by_name["chat_reviewed_multiturn"]["raw_chat_direct_training_allowed"] is False
    assert "supervised_evaluation" in by_name["chat_reviewed_multiturn"]["allowed_downstream_uses"]
    assert by_name["swe_bench_lite"]["runnable"] is False
    assert by_name["swe_bench_lite"]["adapter_status"] == "requires_swe_harness"


def test_ensure_dataset_registry_backfills_missing_builtin_datasets(tmp_path: Path):
    legacy_path = tmp_path / "workspace" / "evaluation" / "datasets" / "registry.json"
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_text(
        json.dumps(
            {
                "version": 1,
                "datasets": [
                    {
                        "name": "custom_prompt_jsonl",
                        "kind": "prompt_jsonl",
                        "bundle_name": "custom_prompt_jsonl_v1",
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    ensure_dataset_registry(tmp_path)
    payload = json.loads(legacy_path.read_text(encoding="utf-8"))
    names = {item["name"] for item in payload["datasets"]}

    assert "generated_cases" in names
    assert "chat_reviewed_multiturn" in names
    assert "custom_prompt_jsonl" in names


def test_dataset_registry_backfills_chat_review_boundary_metadata(tmp_path: Path):
    registry_path = tmp_path / "workspace" / "evaluation" / "datasets" / "registry.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        json.dumps(
            {
                "version": 1,
                "datasets": [
                    {
                        "name": "chat_reviewed_multiturn",
                        "kind": "prompt_jsonl",
                        "description": "legacy chat cases",
                        "source_path": "workspace/evaluation/datasets/chat_reviewed_multiturn.jsonl",
                        "bundle_name": "chat_reviewed_multiturn_v1",
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    ensure_dataset_registry(tmp_path)
    rows = list_dataset_status(tmp_path)
    row = next(item for item in rows if item["name"] == "chat_reviewed_multiturn")

    assert row["review_required"] is True
    assert row["source_track"] == "dialogue"
    assert row["holdout_allowed"] is False
    assert row["raw_chat_direct_training_allowed"] is False
    assert row["allowed_downstream_uses"] == [
        "supervised_evaluation",
        "gym_candidate_case",
        "future_training_export",
    ]


def test_ensure_dataset_registry_bootstraps_generated_and_chat_sources(tmp_path: Path):
    ensure_dataset_registry(tmp_path)

    assert (tmp_path / "workspace" / "evaluation" / "datasets" / "generated_cases.jsonl").exists()
    assert (tmp_path / "workspace" / "evaluation" / "datasets" / "chat_reviewed_multiturn.jsonl").exists()


def test_materialize_builtin_supervised_bundle(tmp_path: Path):
    result = materialize_dataset_bundle("supervised_dry_run", project_root=tmp_path)

    assert result.bundle_name == "supervised_evolution_dry_run_v1"
    assert result.runnable is True
    assert result.case_count >= 1
    assert Path(result.bundle_path).exists()


def test_materialize_builtin_supervised_bundle_respects_limit(tmp_path: Path):
    full = materialize_dataset_bundle("supervised_dry_run", project_root=tmp_path)
    result = materialize_dataset_bundle("supervised_dry_run", project_root=tmp_path, limit=1)
    bundle = json.loads(Path(result.bundle_path).read_text(encoding="utf-8"))
    full_bundle = json.loads(Path(full.bundle_path).read_text(encoding="utf-8"))

    assert result.case_count == 1
    assert len(bundle["cases"]) == 1
    assert result.bundle_path != full.bundle_path
    assert len(full_bundle["cases"]) > 1


def test_materialize_custom_prompt_jsonl(tmp_path: Path):
    registry_path = ensure_dataset_registry(tmp_path)
    dataset_path = tmp_path / "workspace" / "evaluation" / "datasets" / "custom_prompt_tasks.jsonl"
    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    dataset_path.write_text(
        json.dumps(
            {
                "case_id": "hello_case",
                "prompt": "调用 python_lint_tool 检查 scripts/evolution_harness.py，然后成功关账。",
                "training_tier": "coordination",
                "expected": {"kind": "lint_pass"},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    result = materialize_dataset_bundle("custom_prompt_jsonl", project_root=tmp_path)
    bundle = json.loads(Path(result.bundle_path).read_text(encoding="utf-8"))

    assert registry_path.exists()
    assert result.case_count == 1
    assert bundle["dataset"]["name"] == "custom_prompt_jsonl"
    assert bundle["cases"][0]["case_id"] == "hello_case"
    assert bundle["cases"][0]["training_tier"] == "coordination"
    assert bundle["cases"][0]["expected"] == {"kind": "lint_pass"}


def test_materialize_swe_jsonl_marks_external_harness_requirement(tmp_path: Path):
    ensure_dataset_registry(tmp_path)
    dataset_path = tmp_path / "workspace" / "evaluation" / "datasets" / "swe_bench_lite.jsonl"
    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    dataset_path.write_text(
        json.dumps(
            {
                "instance_id": "django__django-1",
                "repo": "django/django",
                "base_commit": "abc123",
                "problem_statement": "Fix a failing queryset edge case.",
                "patch": "gold patch is hidden from prompts",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    result = materialize_dataset_bundle("swe_bench_lite", project_root=tmp_path)
    bundle = json.loads(Path(result.bundle_path).read_text(encoding="utf-8"))

    assert result.runnable is False
    assert result.adapter_status == "requires_swe_harness"
    assert bundle["cases"][0]["scenario"] == "swe_patch"
    assert bundle["cases"][0]["requires_external_harness"] == "swe_bench"
    assert "gold patch" not in bundle["cases"][0]["baseline_prompt"]


def test_materialize_missing_dataset_source_fails_clearly(tmp_path: Path):
    ensure_dataset_registry(tmp_path)

    with pytest.raises(FileNotFoundError):
        materialize_dataset_bundle("custom_prompt_jsonl", project_root=tmp_path)


def test_materialize_generated_cases_requires_provenance_and_blocks_holdout(tmp_path: Path):
    ensure_dataset_registry(tmp_path)
    dataset_path = tmp_path / "workspace" / "evaluation" / "datasets" / "generated_cases.jsonl"
    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    dataset_path.write_text(
        json.dumps(
            {
                "case_id": "generated_validation_case",
                "prompt": "Run validation before closing the transaction.",
                "training_tier": "intelligence",
                "dataset_splits": ["train", "observe"],
                "provenance": {
                    "source_trace_id": "trace_001",
                    "source_episode_id": "episode_001",
                    "source_harness_gap": "validation",
                    "generation_reason": "candidate closed without validation",
                    "creator_version": "gym-v1-test",
                    "created_at": "2026-05-15T00:00:00Z",
                    "allowed_splits": ["train", "observe"],
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    result = materialize_dataset_bundle("generated_cases", project_root=tmp_path)
    bundle = json.loads(Path(result.bundle_path).read_text(encoding="utf-8"))

    assert result.bundle_name == "generated_cases_v1"
    assert bundle["cases"][0]["generated"] is True
    assert bundle["cases"][0]["training_tier"] == "intelligence"
    assert bundle["cases"][0]["dataset_splits"] == ["train", "observe"]
    assert bundle["cases"][0]["provenance"]["source_trace_id"] == "trace_001"

    dataset_path.write_text(
        json.dumps(
            {
                "case_id": "bad_holdout",
                "prompt": "This should not enter holdout automatically.",
                "dataset_splits": ["holdout"],
                "provenance": {
                    "source_trace_id": "trace_002",
                    "source_episode_id": "episode_002",
                    "source_harness_gap": "validation",
                    "generation_reason": "bad generated split",
                    "creator_version": "gym-v1-test",
                    "created_at": "2026-05-15T00:00:00Z",
                    "allowed_splits": ["holdout"],
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="holdout"):
        materialize_dataset_bundle("generated_cases", project_root=tmp_path)


def test_materialize_dataset_rejects_unknown_training_tier(tmp_path: Path):
    ensure_dataset_registry(tmp_path)
    dataset_path = tmp_path / "workspace" / "evaluation" / "datasets" / "custom_prompt_tasks.jsonl"
    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    dataset_path.write_text(
        json.dumps(
            {
                "case_id": "bad_tier",
                "prompt": "Do something.",
                "training_tier": "expert",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="training tier"):
        materialize_dataset_bundle("custom_prompt_jsonl", project_root=tmp_path)
