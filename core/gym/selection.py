# -*- coding: utf-8 -*-
"""Tier-aware selection policy for Gym v1."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Dict, Sequence

from .models import ALLOWED_TRAINING_TIERS, Attempt


@dataclass
class TierScoreSummary:
    tier: str
    baseline_attempts: int
    candidate_attempts: int
    baseline_success_rate: float
    candidate_success_rate: float
    delta: float

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


@dataclass
class TierSelectionDecision:
    decision: str
    reason: str
    tier_summaries: list[TierScoreSummary] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        payload = asdict(self)
        payload["tier_summaries"] = [item.to_dict() for item in self.tier_summaries]
        return payload


def select_by_training_tier(
    *,
    baseline_attempts: Sequence[Attempt],
    candidate_attempts: Sequence[Attempt],
) -> TierSelectionDecision:
    summaries = _tier_summaries(baseline_attempts, candidate_attempts)
    by_tier = {item.tier: item for item in summaries}
    blockers: list[str] = []

    foundation = by_tier.get("foundation")
    if foundation is None or foundation.baseline_attempts == 0 or foundation.candidate_attempts == 0:
        blockers.append("missing foundation evidence")
    elif foundation.delta < 0:
        blockers.append("foundation regression")

    regressed_tiers = [
        item.tier
        for item in summaries
        if item.tier != "foundation" and item.baseline_attempts and item.candidate_attempts and item.delta < 0
    ]
    if regressed_tiers:
        blockers.append(f"higher-tier regression: {', '.join(regressed_tiers)}")

    overall_baseline = _success_rate(baseline_attempts)
    overall_candidate = _success_rate(candidate_attempts)
    overall_delta = overall_candidate - overall_baseline

    if "foundation regression" in blockers:
        return TierSelectionDecision(
            decision="REJECT",
            reason="Candidate regressed on foundation stability, which blocks promotion.",
            tier_summaries=summaries,
            blockers=blockers,
        )
    if "missing foundation evidence" in blockers and overall_delta > 0:
        return TierSelectionDecision(
            decision="HOLD",
            reason="Candidate improved, but promotion needs foundation evidence.",
            tier_summaries=summaries,
            blockers=blockers,
        )
    if regressed_tiers:
        return TierSelectionDecision(
            decision="HOLD",
            reason="Candidate improved or held overall, but one or more higher tiers regressed.",
            tier_summaries=summaries,
            blockers=blockers,
        )
    if overall_delta > 0:
        return TierSelectionDecision(
            decision="PROMOTE",
            reason="Candidate improved without foundation or tier regressions; v1 records a promotion proposal only.",
            tier_summaries=summaries,
            blockers=blockers,
        )
    if overall_delta == 0:
        return TierSelectionDecision(
            decision="OBSERVE",
            reason="Candidate did not regress, but evidence is not strong enough to promote.",
            tier_summaries=summaries,
            blockers=blockers,
        )
    return TierSelectionDecision(
        decision="REJECT",
        reason="Candidate regressed against baseline Attempts.",
        tier_summaries=summaries,
        blockers=blockers,
    )


def _tier_summaries(
    baseline_attempts: Sequence[Attempt],
    candidate_attempts: Sequence[Attempt],
) -> list[TierScoreSummary]:
    tiers = sorted(
        ALLOWED_TRAINING_TIERS,
        key=lambda tier: {"foundation": 0, "coordination": 1, "intelligence": 2}[tier],
    )
    summaries: list[TierScoreSummary] = []
    for tier in tiers:
        baseline = [item for item in baseline_attempts if item.training_tier == tier]
        candidate = [item for item in candidate_attempts if item.training_tier == tier]
        if not baseline and not candidate:
            continue
        baseline_rate = _success_rate(baseline)
        candidate_rate = _success_rate(candidate)
        summaries.append(
            TierScoreSummary(
                tier=tier,
                baseline_attempts=len(baseline),
                candidate_attempts=len(candidate),
                baseline_success_rate=baseline_rate,
                candidate_success_rate=candidate_rate,
                delta=round(candidate_rate - baseline_rate, 6),
            )
        )
    return summaries


def _success_rate(attempts: Sequence[Attempt]) -> float:
    if not attempts:
        return 0.0
    return sum(1 for item in attempts if item.score.success) / len(attempts)
