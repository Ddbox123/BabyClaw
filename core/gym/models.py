# -*- coding: utf-8 -*-
"""Domain models for Gym v1.

These models are intentionally small and serializable. They describe the Gym
closed loop without depending on Workbench, agent.py, or a specific dataset
format.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


ALLOWED_DATASET_SPLITS = {"train", "dev", "observe", "regression", "holdout", "smoke"}
GENERATED_CASE_DEFAULT_SPLITS = ("train", "observe")
ALLOWED_TRAINING_TIERS = {"foundation", "coordination", "intelligence"}


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def normalize_dataset_splits(splits: Optional[List[str] | tuple[str, ...]]) -> List[str]:
    if not splits:
        return ["train"]
    normalized: List[str] = []
    for raw in splits:
        split = str(raw).strip().lower()
        if not split:
            continue
        if split not in ALLOWED_DATASET_SPLITS:
            raise ValueError(f"Unknown dataset split: {raw}")
        if split not in normalized:
            normalized.append(split)
    return normalized or ["train"]


def normalize_training_tier(tier: str | None) -> str:
    normalized = str(tier or "foundation").strip().lower()
    if normalized not in ALLOWED_TRAINING_TIERS:
        raise ValueError(f"Unknown training tier: {tier}")
    return normalized


@dataclass
class GeneratedCaseProvenance:
    source_trace_id: str
    source_episode_id: str
    source_harness_gap: str
    generation_reason: str
    creator_version: str
    created_at: str = field(default_factory=utcnow_iso)
    allowed_splits: List[str] = field(default_factory=lambda: list(GENERATED_CASE_DEFAULT_SPLITS))

    def __post_init__(self) -> None:
        required = {
            "source_trace_id": self.source_trace_id,
            "source_episode_id": self.source_episode_id,
            "source_harness_gap": self.source_harness_gap,
            "generation_reason": self.generation_reason,
            "creator_version": self.creator_version,
            "created_at": self.created_at,
        }
        missing = [name for name, value in required.items() if not str(value or "").strip()]
        if missing:
            raise ValueError(f"Generated case provenance missing fields: {', '.join(missing)}")
        self.allowed_splits = normalize_dataset_splits(self.allowed_splits)
        if "holdout" in self.allowed_splits:
            raise ValueError("Generated cases cannot automatically enter holdout")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class GymExercise:
    exercise_id: str
    name: str
    objective: str
    capability_tags: List[str]
    training_tier: str = "foundation"
    dataset_names: List[str] = field(default_factory=list)
    default_splits: List[str] = field(default_factory=lambda: ["train", "dev", "regression"])

    def __post_init__(self) -> None:
        self.default_splits = normalize_dataset_splits(self.default_splits)
        self.training_tier = normalize_training_tier(self.training_tier)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class GymTrainingCollection:
    collection_id: str
    name: str
    training_tier: str
    objective: str
    exercise_ids: List[str] = field(default_factory=list)
    capability_tags: List[str] = field(default_factory=list)
    promotion_gate: bool = False
    allow_mixed_tiers: bool = False

    def __post_init__(self) -> None:
        self.training_tier = normalize_training_tier(self.training_tier)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class GymCase:
    case_id: str
    objective: str
    prompt: str
    validation: Dict[str, Any]
    scoring_basis: Dict[str, Any]
    dataset_splits: List[str]
    training_tier: str = "foundation"
    capability_tags: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    allowed_tools: List[str] = field(default_factory=list)
    dataset_ref: Dict[str, Any] = field(default_factory=dict)
    provenance: Optional[GeneratedCaseProvenance] = None

    def __post_init__(self) -> None:
        self.dataset_splits = normalize_dataset_splits(self.dataset_splits)
        self.training_tier = normalize_training_tier(self.training_tier)
        if self.provenance:
            for split in self.dataset_splits:
                if split not in self.provenance.allowed_splits:
                    raise ValueError(f"Generated case split {split!r} is not allowed by provenance")

    def to_bundle_case(self) -> Dict[str, Any]:
        payload = {
            "case_id": self.case_id,
            "scenario": self.validation.get("scenario", "transaction"),
            "mode": self.validation.get("mode", "single_turn"),
            "expect_restart": bool(self.validation.get("expect_restart", False)),
            "timeout_seconds": int(self.validation.get("timeout_seconds", 600)),
            "baseline_prompt": self.prompt,
            "candidate_prompt": self.prompt,
            "objective": self.objective,
            "dataset_splits": self.dataset_splits,
            "training_tier": self.training_tier,
            "capability_tags": self.capability_tags,
            "constraints": self.constraints,
            "allowed_tools": self.allowed_tools,
            "validation": self.validation,
            "scoring_basis": self.scoring_basis,
            "dataset_ref": self.dataset_ref,
        }
        if self.provenance:
            payload["provenance"] = self.provenance.to_dict()
            payload["generated"] = True
        return payload

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        if self.provenance:
            payload["provenance"] = self.provenance.to_dict()
        return payload


@dataclass
class Score:
    success: bool
    quality: float = 0.0
    cost: float = 0.0
    latency: float = 0.0
    validation: Dict[str, Any] = field(default_factory=dict)
    tool_errors: int = 0
    regression_risk: float = 0.0
    safety_risk: float = 0.0
    training_tier: str = "foundation"

    def __post_init__(self) -> None:
        self.training_tier = normalize_training_tier(self.training_tier)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Trace:
    trace_id: str
    case_id: str
    events: List[Dict[str, Any]] = field(default_factory=list)
    artifacts: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Attempt:
    attempt_id: str
    case_id: str
    agent_version: str
    trace_id: str
    score: Score
    role: str = "baseline"
    harness_variant_id: Optional[str] = None
    dataset_splits: List[str] = field(default_factory=lambda: ["train"])
    training_tier: str = "foundation"

    def __post_init__(self) -> None:
        self.dataset_splits = normalize_dataset_splits(self.dataset_splits)
        self.training_tier = normalize_training_tier(self.training_tier)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EvaluationRun:
    evaluation_run_id: str
    bundle_name: str
    split: str
    attempts: List[Attempt]
    training_tier: str = "foundation"

    def __post_init__(self) -> None:
        self.split = normalize_dataset_splits([self.split])[0]
        self.training_tier = normalize_training_tier(self.training_tier)

    @property
    def success_rate(self) -> float:
        if not self.attempts:
            return 0.0
        return sum(1 for item in self.attempts if item.score.success) / len(self.attempts)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["success_rate"] = self.success_rate
        return payload


@dataclass
class CandidateImprovement:
    improvement_id: str
    improvement_type: str
    target: Dict[str, Any]
    expected_effect: str
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class HarnessVariant:
    variant_id: str
    candidate_improvement_id: str
    application_mode: str = "isolated"
    applied_at: str = field(default_factory=utcnow_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PromotionProposal:
    proposal_id: str
    episode_id: str
    candidate_improvement_id: str
    status: str
    action: str
    created_at: str = field(default_factory=utcnow_iso)
    proposal_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ImprovementEpisode:
    episode_id: str
    exercise: GymExercise
    baseline_attempts: List[Attempt]
    baseline_traces: List[Trace]
    candidate_improvement: CandidateImprovement
    harness_variant: HarnessVariant
    candidate_attempts: List[Attempt]
    candidate_traces: List[Trace]
    evaluation_runs: List[EvaluationRun]
    decision: str
    reason: str
    harness_gap: str
    started_at: str = field(default_factory=utcnow_iso)
    ended_at: str = field(default_factory=utcnow_iso)
    promotion_proposal: Optional[PromotionProposal] = None

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["exercise"] = self.exercise.to_dict()
        payload["baseline_attempts"] = [item.to_dict() for item in self.baseline_attempts]
        payload["baseline_traces"] = [item.to_dict() for item in self.baseline_traces]
        payload["candidate_improvement"] = self.candidate_improvement.to_dict()
        payload["harness_variant"] = self.harness_variant.to_dict()
        payload["candidate_attempts"] = [item.to_dict() for item in self.candidate_attempts]
        payload["candidate_traces"] = [item.to_dict() for item in self.candidate_traces]
        payload["evaluation_runs"] = [item.to_dict() for item in self.evaluation_runs]
        if self.promotion_proposal:
            payload["promotion_proposal"] = self.promotion_proposal.to_dict()
        return payload
