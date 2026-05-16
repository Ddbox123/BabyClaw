# -*- coding: utf-8 -*-
"""Embeddable Evolution Engine.

The engine knows the Gym domain, but it does not know Vibelution's Workbench,
agent.py, or process model. Hosts integrate by providing an AgentHarnessAdapter.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from .episodes import record_improvement_episode
from .models import (
    Attempt,
    CandidateImprovement,
    EvaluationRun,
    GymCase,
    GymExercise,
    HarnessVariant,
    ImprovementEpisode,
    Trace,
    utcnow_iso,
)
from .selection import select_by_training_tier


@dataclass
class AttemptEvidence:
    attempt: Attempt
    trace: Trace


@dataclass
class CriticDiagnosis:
    harness_gap: str
    evidence: list[str]
    reason: str


class AgentHarnessAdapter(Protocol):
    """Host boundary for running any Agent inside the Evolution Engine."""

    def agent_version(self) -> str:
        """Return a stable label for the current baseline Agent implementation."""

    def run_case(self, case: GymCase, *, role: str, variant: HarnessVariant | None = None) -> AttemptEvidence:
        """Run one Case and return generic Attempt/Trace evidence."""

    def propose_improvement(self, exercise: GymExercise, diagnosis: CriticDiagnosis) -> CandidateImprovement:
        """Create one bounded Candidate Improvement from a diagnosis."""

    def apply_variant(self, improvement: CandidateImprovement) -> HarnessVariant:
        """Return an isolated Harness Variant with the Candidate Improvement applied."""


class EvolutionEngine:
    def __init__(self, adapter: AgentHarnessAdapter) -> None:
        self.adapter = adapter

    def run_proposal_only_episode(
        self,
        *,
        episode_id: str,
        exercise: GymExercise,
        cases: Sequence[GymCase],
    ) -> ImprovementEpisode:
        if not cases:
            raise ValueError("Evolution episode requires at least one case")

        baseline_evidence = [self.adapter.run_case(case, role="baseline") for case in cases]
        diagnosis = self._diagnose(baseline_evidence)
        improvement = self.adapter.propose_improvement(exercise, diagnosis)
        variant = self.adapter.apply_variant(improvement)
        candidate_evidence = [self.adapter.run_case(case, role="candidate", variant=variant) for case in cases]

        baseline_attempts = [item.attempt for item in baseline_evidence]
        candidate_attempts = [item.attempt for item in candidate_evidence]
        evaluation_runs = self._evaluation_runs(exercise.exercise_id, baseline_attempts, candidate_attempts)
        selection = select_by_training_tier(
            baseline_attempts=baseline_attempts,
            candidate_attempts=candidate_attempts,
        )

        episode = ImprovementEpisode(
            episode_id=episode_id,
            exercise=exercise,
            baseline_attempts=baseline_attempts,
            baseline_traces=[item.trace for item in baseline_evidence],
            candidate_improvement=improvement,
            harness_variant=variant,
            candidate_attempts=candidate_attempts,
            candidate_traces=[item.trace for item in candidate_evidence],
            evaluation_runs=evaluation_runs,
            decision=selection.decision,
            reason=selection.reason,
            harness_gap=diagnosis.harness_gap,
            started_at=utcnow_iso(),
            ended_at=utcnow_iso(),
        )
        return episode

    def record_episode(self, episode: ImprovementEpisode, *, project_root=None):
        return record_improvement_episode(episode, project_root=project_root)

    def _diagnose(self, evidence: Sequence[AttemptEvidence]) -> CriticDiagnosis:
        failed = [item for item in evidence if not item.attempt.score.success]
        if failed:
            return CriticDiagnosis(
                harness_gap="validation",
                evidence=[item.trace.trace_id for item in failed],
                reason="One or more baseline Attempts failed validation or success scoring.",
            )
        return CriticDiagnosis(
            harness_gap="efficiency",
            evidence=[item.trace.trace_id for item in evidence],
            reason="Baseline passed; candidate improvement should focus on bounded efficiency or evidence quality.",
        )

    def _evaluation_runs(
        self,
        exercise_id: str,
        baseline_attempts: Sequence[Attempt],
        candidate_attempts: Sequence[Attempt],
    ) -> list[EvaluationRun]:
        runs: list[EvaluationRun] = []
        for role, attempts in (("baseline", baseline_attempts), ("candidate", candidate_attempts)):
            grouped: dict[str, list[Attempt]] = {}
            for attempt in attempts:
                grouped.setdefault(attempt.training_tier, []).append(attempt)
            for tier in sorted(grouped, key=lambda item: {"foundation": 0, "coordination": 1, "intelligence": 2}[item]):
                runs.append(
                    EvaluationRun(
                        evaluation_run_id=f"{exercise_id}:{role}:dev:{tier}",
                        bundle_name=exercise_id,
                        split="dev",
                        attempts=grouped[tier],
                        training_tier=tier,
                    )
                )
        return runs
