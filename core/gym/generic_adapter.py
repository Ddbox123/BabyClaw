# -*- coding: utf-8 -*-
"""Generic callable adapter for embedding Gym in non-Vibelution agents."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .engine import AgentHarnessAdapter, AttemptEvidence, CriticDiagnosis
from .models import (
    Attempt,
    CandidateImprovement,
    GymCase,
    GymExercise,
    HarnessVariant,
    Score,
    Trace,
)


CaseRunner = Callable[[GymCase, str, Optional[HarnessVariant]], "GenericCaseResult"]


@dataclass
class GenericCaseResult:
    """Host-neutral result returned by a callable agent runner."""

    success: bool
    quality: float = 1.0
    cost: float = 0.0
    latency: float = 0.0
    validation: dict[str, Any] = field(default_factory=dict)
    tool_errors: int = 0
    regression_risk: float = 0.0
    safety_risk: float = 0.0
    events: list[dict[str, Any]] = field(default_factory=list)
    artifacts: dict[str, Any] = field(default_factory=dict)
    reason: str = ""


class CallableAgentHarnessAdapter(AgentHarnessAdapter):
    """Adapter for any Agent that can run a GymCase via a Python callable."""

    def __init__(
        self,
        *,
        agent_version_label: str,
        run_case_fn: CaseRunner,
        improvement_type: str = "policy_patch",
        application_mode: str = "proposal_only",
    ) -> None:
        self.agent_version_label = agent_version_label
        self.run_case_fn = run_case_fn
        self.improvement_type = improvement_type
        self.application_mode = application_mode

    def agent_version(self) -> str:
        return self.agent_version_label

    def run_case(self, case: GymCase, *, role: str, variant: HarnessVariant | None = None) -> AttemptEvidence:
        result = self.run_case_fn(case, role, variant)
        trace_id = f"generic:{self.agent_version()}:{role}:{case.case_id}"
        attempt = Attempt(
            attempt_id=f"{trace_id}:attempt",
            case_id=case.case_id,
            agent_version=self.agent_version(),
            trace_id=trace_id,
            score=Score(
                success=result.success,
                quality=result.quality,
                cost=result.cost,
                latency=result.latency,
                validation=result.validation,
                tool_errors=result.tool_errors,
                regression_risk=result.regression_risk,
                safety_risk=result.safety_risk,
                training_tier=case.training_tier,
            ),
            role=role,
            harness_variant_id=variant.variant_id if variant else None,
            dataset_splits=case.dataset_splits,
            training_tier=case.training_tier,
        )
        trace = Trace(
            trace_id=trace_id,
            case_id=case.case_id,
            events=[
                {
                    "type": "generic_case_result",
                    "role": role,
                    "success": result.success,
                    "reason": result.reason,
                    "variant_id": variant.variant_id if variant else None,
                },
                *result.events,
            ],
            artifacts=result.artifacts,
        )
        return AttemptEvidence(attempt=attempt, trace=trace)

    def propose_improvement(self, exercise: GymExercise, diagnosis: CriticDiagnosis) -> CandidateImprovement:
        return CandidateImprovement(
            improvement_id=f"{self.agent_version()}:{exercise.exercise_id}:{diagnosis.harness_gap}:proposal",
            improvement_type=self.improvement_type,
            target={
                "kind": "generic_agent_harness",
                "exercise_id": exercise.exercise_id,
                "harness_gap": diagnosis.harness_gap,
            },
            expected_effect=diagnosis.reason,
            payload={"evidence": diagnosis.evidence},
        )

    def apply_variant(self, improvement: CandidateImprovement) -> HarnessVariant:
        return HarnessVariant(
            variant_id=f"{self.agent_version()}:variant:{improvement.improvement_id}",
            candidate_improvement_id=improvement.improvement_id,
            application_mode=self.application_mode,
        )


__all__ = ["CallableAgentHarnessAdapter", "GenericCaseResult"]
