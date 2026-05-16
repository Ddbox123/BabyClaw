#!/usr/bin/env python3
"""Embeddable Gym engine tests."""

from pathlib import Path

import pytest

from core.gym import (
    Attempt,
    AttemptEvidence,
    CandidateImprovement,
    CriticDiagnosis,
    EvolutionEngine,
    GymCase,
    GymExercise,
    HarnessVariant,
    Score,
    Trace,
    build_local_transaction_exercise,
    materialize_local_transaction_cases,
    select_by_training_tier,
)


class FakeAgentHarness:
    def __init__(self) -> None:
        self.calls = []

    def agent_version(self) -> str:
        return "fake-agent-v1"

    def run_case(self, case: GymCase, *, role: str, variant: HarnessVariant | None = None) -> AttemptEvidence:
        self.calls.append((case.case_id, role, variant.variant_id if variant else None))
        success = role == "candidate"
        attempt = Attempt(
            attempt_id=f"{role}:{case.case_id}",
            case_id=case.case_id,
            agent_version=self.agent_version(),
            trace_id=f"trace:{role}:{case.case_id}",
            score=Score(success=success, quality=1.0 if success else 0.0, training_tier=case.training_tier),
            role=role,
            harness_variant_id=variant.variant_id if variant else None,
            dataset_splits=case.dataset_splits,
            training_tier=case.training_tier,
        )
        trace = Trace(
            trace_id=attempt.trace_id,
            case_id=case.case_id,
            events=[{"role": role, "success": success}],
        )
        return AttemptEvidence(attempt=attempt, trace=trace)

    def propose_improvement(self, exercise: GymExercise, diagnosis: CriticDiagnosis) -> CandidateImprovement:
        return CandidateImprovement(
            improvement_id=f"{exercise.exercise_id}:verifier_patch",
            improvement_type="verifier_patch",
            target={"kind": "adapter_test"},
            expected_effect=f"Improve {diagnosis.harness_gap}",
        )

    def apply_variant(self, improvement: CandidateImprovement) -> HarnessVariant:
        return HarnessVariant(
            variant_id="fake-variant-v1",
            candidate_improvement_id=improvement.improvement_id,
        )


def test_evolution_engine_runs_with_fake_agent_adapter_and_writes_proposal(tmp_path: Path):
    exercise = build_local_transaction_exercise()
    cases = materialize_local_transaction_cases()
    engine = EvolutionEngine(FakeAgentHarness())

    episode = engine.run_proposal_only_episode(
        episode_id="episode_fake_001",
        exercise=exercise,
        cases=cases,
    )
    decision_path = engine.record_episode(episode, project_root=tmp_path)

    assert episode.decision == "PROMOTE"
    assert episode.promotion_proposal is not None
    assert episode.promotion_proposal.action == "write_promotion_proposal"
    assert decision_path.exists()
    assert (tmp_path / "workspace" / "gym" / "promotion_proposals").exists()
    assert episode.baseline_attempts[0].case_id == cases[0].case_id
    assert episode.candidate_attempts[0].harness_variant_id == "fake-variant-v1"
    assert {run.split for run in episode.evaluation_runs} == {"dev"}
    assert episode.exercise.training_tier == "foundation"
    assert episode.baseline_attempts[0].training_tier == "foundation"
    assert episode.baseline_attempts[0].score.training_tier == "foundation"
    assert {run.training_tier for run in episode.evaluation_runs} == {"foundation"}


def test_generated_case_rejects_holdout_split():
    from core.gym import build_generated_case

    with pytest.raises(ValueError, match="holdout"):
        build_generated_case(
            case_id="generated_bad",
            objective="catch validation shortcut",
            prompt="Run validation before closing.",
            source_trace_id="trace_1",
            source_episode_id="episode_1",
            source_harness_gap="validation",
            generation_reason="baseline skipped validation",
            creator_version="test",
            dataset_splits=["holdout"],
        )


def test_training_tier_validation_and_bundle_case_metadata():
    exercise = build_local_transaction_exercise()
    case = materialize_local_transaction_cases()[0]
    bundle_case = case.to_bundle_case()

    assert exercise.training_tier == "foundation"
    assert case.training_tier == "foundation"
    assert bundle_case["training_tier"] == "foundation"

    with pytest.raises(ValueError, match="Unknown training tier"):
        GymExercise(
            exercise_id="bad",
            name="bad",
            objective="bad",
            capability_tags=[],
            training_tier="expert",
        )


def _tier_case(case_id: str, tier: str) -> GymCase:
    return GymCase(
        case_id=case_id,
        objective=f"{tier} objective",
        prompt=f"Run {tier} case.",
        validation={"scenario": "transaction", "mode": "single_turn"},
        scoring_basis={"success": "synthetic"},
        dataset_splits=["dev"],
        training_tier=tier,
    )


class ScriptedTierHarness(FakeAgentHarness):
    def __init__(self, outcomes: dict[tuple[str, str], bool]) -> None:
        super().__init__()
        self.outcomes = outcomes

    def run_case(self, case: GymCase, *, role: str, variant: HarnessVariant | None = None) -> AttemptEvidence:
        self.calls.append((case.case_id, role, variant.variant_id if variant else None))
        success = self.outcomes[(role, case.case_id)]
        attempt = Attempt(
            attempt_id=f"{role}:{case.case_id}",
            case_id=case.case_id,
            agent_version=self.agent_version(),
            trace_id=f"trace:{role}:{case.case_id}",
            score=Score(success=success, quality=1.0 if success else 0.0, training_tier=case.training_tier),
            role=role,
            harness_variant_id=variant.variant_id if variant else None,
            dataset_splits=case.dataset_splits,
            training_tier=case.training_tier,
        )
        return AttemptEvidence(
            attempt=attempt,
            trace=Trace(trace_id=attempt.trace_id, case_id=case.case_id, events=[]),
        )


def test_foundation_regression_blocks_promotion_even_when_intelligence_improves():
    cases = [_tier_case("foundation_case", "foundation"), _tier_case("intelligence_case", "intelligence")]
    engine = EvolutionEngine(
        ScriptedTierHarness(
            {
                ("baseline", "foundation_case"): True,
                ("candidate", "foundation_case"): False,
                ("baseline", "intelligence_case"): False,
                ("candidate", "intelligence_case"): True,
            }
        )
    )

    episode = engine.run_proposal_only_episode(
        episode_id="tier_regression",
        exercise=GymExercise(
            exercise_id="mixed_tier",
            name="mixed",
            objective="mixed",
            capability_tags=[],
            training_tier="foundation",
        ),
        cases=cases,
    )

    assert episode.decision == "REJECT"
    assert "foundation" in episode.reason
    assert {run.training_tier for run in episode.evaluation_runs} == {"foundation", "intelligence"}


def test_higher_tier_regression_holds_even_when_foundation_improves():
    cases = [
        _tier_case("foundation_case", "foundation"),
        _tier_case("coordination_case", "coordination"),
        _tier_case("intelligence_case", "intelligence"),
    ]
    engine = EvolutionEngine(
        ScriptedTierHarness(
            {
                ("baseline", "foundation_case"): False,
                ("candidate", "foundation_case"): True,
                ("baseline", "coordination_case"): True,
                ("candidate", "coordination_case"): False,
                ("baseline", "intelligence_case"): True,
                ("candidate", "intelligence_case"): True,
            }
        )
    )

    episode = engine.run_proposal_only_episode(
        episode_id="tier_higher_regression",
        exercise=GymExercise(
            exercise_id="mixed_tier",
            name="mixed",
            objective="mixed",
            capability_tags=[],
            training_tier="foundation",
        ),
        cases=cases,
    )

    assert episode.decision == "HOLD"
    assert "higher tiers regressed" in episode.reason
    selection = select_by_training_tier(
        baseline_attempts=episode.baseline_attempts,
        candidate_attempts=episode.candidate_attempts,
    )
    assert "higher-tier regression: coordination" in selection.blockers
    assert {run.training_tier for run in episode.evaluation_runs} == {"foundation", "coordination", "intelligence"}


def test_mixed_tier_improvement_promotes_when_no_tier_regresses():
    cases = [
        _tier_case("foundation_case", "foundation"),
        _tier_case("coordination_case", "coordination"),
        _tier_case("intelligence_case", "intelligence"),
    ]
    engine = EvolutionEngine(
        ScriptedTierHarness(
            {
                ("baseline", "foundation_case"): True,
                ("candidate", "foundation_case"): True,
                ("baseline", "coordination_case"): False,
                ("candidate", "coordination_case"): True,
                ("baseline", "intelligence_case"): True,
                ("candidate", "intelligence_case"): True,
            }
        )
    )

    episode = engine.run_proposal_only_episode(
        episode_id="tier_clean_improvement",
        exercise=GymExercise(
            exercise_id="mixed_tier",
            name="mixed",
            objective="mixed",
            capability_tags=[],
            training_tier="foundation",
        ),
        cases=cases,
    )

    assert episode.decision == "PROMOTE"
    selection = select_by_training_tier(
        baseline_attempts=episode.baseline_attempts,
        candidate_attempts=episode.candidate_attempts,
    )
    assert selection.blockers == []
    assert {item.tier for item in selection.tier_summaries} == {
        "foundation",
        "coordination",
        "intelligence",
    }


def test_intelligence_improvement_without_foundation_evidence_holds():
    cases = [_tier_case("intelligence_case", "intelligence")]
    engine = EvolutionEngine(
        ScriptedTierHarness(
            {
                ("baseline", "intelligence_case"): False,
                ("candidate", "intelligence_case"): True,
            }
        )
    )

    episode = engine.run_proposal_only_episode(
        episode_id="tier_missing_foundation",
        exercise=GymExercise(
            exercise_id="intelligence_only",
            name="intelligence only",
            objective="intelligence",
            capability_tags=[],
            training_tier="intelligence",
        ),
        cases=cases,
    )

    assert episode.decision == "HOLD"
    assert "foundation evidence" in episode.reason
