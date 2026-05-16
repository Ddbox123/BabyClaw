# -*- coding: utf-8 -*-
"""Generated Case storage through the dataset boundary."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from core.infrastructure.workspace_manager import get_workspace

from .models import GeneratedCaseProvenance, GymCase


GENERATED_CASES_DATASET_NAME = "generated_cases"
GENERATED_CASES_JSONL = Path("workspace/evaluation/datasets/generated_cases.jsonl")


def append_generated_case(case: GymCase, *, project_root: Optional[Path] = None) -> Path:
    if case.provenance is None:
        raise ValueError("Generated cases must include provenance")
    if "holdout" in case.dataset_splits:
        raise ValueError("Generated cases cannot automatically enter holdout")

    root = (project_root or get_workspace().project_root).resolve()
    path = root / GENERATED_CASES_JSONL
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = case.to_bundle_case()
    payload["dataset_name"] = GENERATED_CASES_DATASET_NAME
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return path


def build_generated_case(
    *,
    case_id: str,
    objective: str,
    prompt: str,
    source_trace_id: str,
    source_episode_id: str,
    source_harness_gap: str,
    generation_reason: str,
    creator_version: str,
    dataset_splits: Optional[list[str]] = None,
) -> GymCase:
    provenance = GeneratedCaseProvenance(
        source_trace_id=source_trace_id,
        source_episode_id=source_episode_id,
        source_harness_gap=source_harness_gap,
        generation_reason=generation_reason,
        creator_version=creator_version,
        allowed_splits=dataset_splits or ["train", "observe"],
    )
    return GymCase(
        case_id=case_id,
        objective=objective,
        prompt=prompt,
        validation={"scenario": "transaction", "mode": "single_turn", "expect_restart": False},
        scoring_basis={"success": "case objective is satisfied"},
        dataset_splits=dataset_splits or ["train", "observe"],
        provenance=provenance,
    )
