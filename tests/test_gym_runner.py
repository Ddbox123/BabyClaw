#!/usr/bin/env python3
"""Gym runner tests."""

import json
from pathlib import Path

import pytest

from core.gym import (
    AgentHarnessAdapter,
    Attempt,
    AttemptEvidence,
    CandidateImprovement,
    GymCase,
    GymCollectionRegistry,
    GymExercise,
    GymTrainingCollection,
    HarnessVariant,
    Score,
    Trace,
    run_gym_collection_episode,
    run_promotion_gate_episode,
)
from core.gym.runner import main


class RunnerFakeAdapter(AgentHarnessAdapter):
    def agent_version(self) -> str:
        return "runner-fake"

    def run_case(self, case: GymCase, *, role: str, variant: HarnessVariant | None = None) -> AttemptEvidence:
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
        return AttemptEvidence(
            attempt=attempt,
            trace=Trace(trace_id=attempt.trace_id, case_id=case.case_id, events=[]),
        )

    def propose_improvement(self, exercise, diagnosis: object) -> CandidateImprovement:
        return CandidateImprovement(
            improvement_id="runner-fake-improvement",
            improvement_type="policy_patch",
            target={"exercise_id": exercise.exercise_id},
            expected_effect="candidate succeeds",
        )

    def apply_variant(self, improvement: CandidateImprovement) -> HarnessVariant:
        return HarnessVariant(
            variant_id="runner-fake-variant",
            candidate_improvement_id=improvement.improvement_id,
            application_mode="proposal_only",
        )


def test_run_gym_collection_episode_records_decision_and_proposal(tmp_path: Path):
    result = run_gym_collection_episode(
        collection_id="foundation_local_stability",
        project_root=tmp_path,
        adapter=RunnerFakeAdapter(),
        episode_id="runner_episode",
    )

    assert result.collection_id == "foundation_local_stability"
    assert result.episode_id == "runner_episode"
    assert result.decision == "PROMOTE"
    assert result.promotion_proposal_path is not None

    decision_path = Path(result.decision_path)
    proposal_path = Path(result.promotion_proposal_path)
    assert decision_path.exists()
    assert proposal_path.exists()
    payload = json.loads(decision_path.read_text(encoding="utf-8"))
    assert payload["decision"] == "PROMOTE"
    assert payload["promotion_proposal"]["status"] == "proposed"


def test_run_gym_collection_episode_records_trace_index(tmp_path: Path):
    result = run_gym_collection_episode(
        collection_id="foundation_local_stability",
        project_root=tmp_path,
        adapter=RunnerFakeAdapter(),
        episode_id="trace_index_episode",
    )

    assert result.trace_index_path is not None
    trace_index_path = Path(result.trace_index_path)
    assert trace_index_path.exists()
    trace_index = json.loads(trace_index_path.read_text(encoding="utf-8"))
    decision = json.loads(Path(result.decision_path).read_text(encoding="utf-8"))

    assert trace_index["episode_id"] == "trace_index_episode"
    expected = {
        (item["role"], item["case_id"], item["trace_id"])
        for item in [*decision["baseline_attempts"], *decision["candidate_attempts"]]
    }
    assert {(item["role"], item["case_id"], item["trace_id"]) for item in trace_index["traces"]} == expected
    for item in trace_index["traces"]:
        trace_path = Path(item["path"])
        assert trace_path.exists()
        trace_payload = json.loads(trace_path.read_text(encoding="utf-8"))
        assert trace_payload["trace_id"] == item["trace_id"]
        assert trace_payload["case_id"] == item["case_id"]


def test_run_gym_collection_episode_records_mixed_gate_tiers(tmp_path: Path):
    result = run_gym_collection_episode(
        collection_id="mixed_readiness_gate",
        project_root=tmp_path,
        adapter=RunnerFakeAdapter(),
        episode_id="mixed_runner_episode",
    )

    assert result.collection_id == "mixed_readiness_gate"
    assert result.decision == "PROMOTE"

    payload = json.loads(Path(result.decision_path).read_text(encoding="utf-8"))
    assert [item["training_tier"] for item in payload["baseline_attempts"]] == [
        "foundation",
        "coordination",
        "intelligence",
    ]
    assert {run["training_tier"] for run in payload["evaluation_runs"]} == {
        "foundation",
        "coordination",
        "intelligence",
    }


def test_promotion_gate_episode_accepts_any_agent_adapter(tmp_path: Path):
    result = run_promotion_gate_episode(
        project_root=tmp_path,
        adapter=RunnerFakeAdapter(),
        episode_id="portable_gate_episode",
    )

    assert result.collection_id == "mixed_readiness_gate"
    assert result.decision == "PROMOTE"


def test_run_gym_collection_episode_rejects_empty_collection(tmp_path: Path):
    registry = GymCollectionRegistry()
    registry.register(
        GymTrainingCollection(
            collection_id="empty_collection",
            name="Empty",
            training_tier="intelligence",
            objective="empty",
        ),
        exercise_factory=lambda: GymExercise(
            exercise_id="empty_exercise",
            name="empty",
            objective="empty",
            capability_tags=[],
            training_tier="intelligence",
        ),
        case_factory=list,
    )

    with pytest.raises(ValueError, match="no materialized cases"):
        run_gym_collection_episode(
            collection_id="empty_collection",
            project_root=tmp_path,
            adapter=RunnerFakeAdapter(),
            registry=registry,
            episode_id="empty_episode",
        )


def test_gym_cli_lists_collections(capsys):
    assert main(["--list"]) == 0
    output = capsys.readouterr().out

    assert "foundation_local_stability" in output
    assert "mixed_readiness_gate" in output
    assert "coordination_workflow_readiness" in output
    assert "intelligence_strategy_readiness" in output
