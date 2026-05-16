#!/usr/bin/env python3
"""Generic Gym adapter tests."""

from pathlib import Path

from core.gym import (
    AdapterContractCheck,
    CallableAgentHarnessAdapter,
    EvolutionEngine,
    GenericCaseResult,
    HarnessVariant,
    validate_agent_harness_adapter,
    build_local_transaction_exercise,
    materialize_local_transaction_cases,
    run_promotion_gate_episode,
)
from core.gym.models import Attempt, CandidateImprovement, GymCase, Score, Trace
from core.gym.engine import AttemptEvidence, CriticDiagnosis


def test_callable_agent_adapter_runs_engine_without_vibelution_runtime(tmp_path: Path):
    calls = []

    def run_case(case: GymCase, role: str, variant: HarnessVariant | None) -> GenericCaseResult:
        calls.append((case.case_id, role, variant.variant_id if variant else None))
        return GenericCaseResult(
            success=role == "candidate",
            quality=1.0 if role == "candidate" else 0.0,
            validation={"passed": 1 if role == "candidate" else 0},
            events=[{"type": "host_call", "case_id": case.case_id}],
            artifacts={"host": "example-agent"},
            reason=f"{role} result",
        )

    adapter = CallableAgentHarnessAdapter(
        agent_version_label="example-agent-v1",
        run_case_fn=run_case,
    )
    engine = EvolutionEngine(adapter)
    episode = engine.run_proposal_only_episode(
        episode_id="generic_adapter_episode",
        exercise=build_local_transaction_exercise(),
        cases=materialize_local_transaction_cases(),
    )
    decision_path = engine.record_episode(episode, project_root=tmp_path)

    assert episode.decision == "PROMOTE"
    assert episode.baseline_attempts[0].agent_version == "example-agent-v1"
    assert episode.candidate_attempts[0].harness_variant_id is not None
    assert episode.candidate_improvement.target["kind"] == "generic_agent_harness"
    assert calls[0][1] == "baseline"
    assert calls[1][1] == "candidate"
    assert decision_path.exists()


def test_promotion_gate_accepts_callable_adapter_for_any_agent(tmp_path: Path):
    tiers = []

    def run_case(case: GymCase, role: str, variant: HarnessVariant | None) -> GenericCaseResult:
        tiers.append((role, case.training_tier))
        return GenericCaseResult(
            success=role == "candidate",
            quality=1.0 if role == "candidate" else 0.0,
            validation={"tier": case.training_tier},
        )

    adapter = CallableAgentHarnessAdapter(
        agent_version_label="portable-agent-v1",
        run_case_fn=run_case,
    )

    result = run_promotion_gate_episode(
        project_root=tmp_path,
        adapter=adapter,
        episode_id="portable_agent_gate",
    )

    assert result.collection_id == "mixed_readiness_gate"
    assert result.decision == "PROMOTE"
    assert {tier for role, tier in tiers if role == "baseline"} == {
        "foundation",
        "coordination",
        "intelligence",
    }


def test_adapter_contract_validator_accepts_callable_adapter():
    def run_case(case: GymCase, role: str, variant: HarnessVariant | None) -> GenericCaseResult:
        return GenericCaseResult(success=True, validation={"role": role})

    adapter = CallableAgentHarnessAdapter(
        agent_version_label="contract-agent-v1",
        run_case_fn=run_case,
    )

    result = validate_agent_harness_adapter(adapter)

    assert isinstance(result, AdapterContractCheck)
    assert result.ok is True
    assert result.agent_version == "contract-agent-v1"
    assert result.errors == []


def test_adapter_contract_validator_reports_schema_errors():
    class BrokenAdapter:
        def agent_version(self) -> str:
            return ""

        def run_case(self, case: GymCase, *, role: str, variant: HarnessVariant | None = None) -> AttemptEvidence:
            trace = Trace(trace_id=f"trace:{role}", case_id="wrong-case")
            attempt = Attempt(
                attempt_id=f"attempt:{role}",
                case_id="wrong-case",
                agent_version="wrong-version",
                trace_id="different-trace",
                score=Score(success=True, training_tier="coordination"),
                role="wrong-role",
                harness_variant_id=None,
                dataset_splits=["observe"],
                training_tier="coordination",
            )
            return AttemptEvidence(attempt=attempt, trace=trace)

        def propose_improvement(self, exercise, diagnosis: CriticDiagnosis) -> CandidateImprovement:
            return CandidateImprovement(
                improvement_id="broken-improvement",
                improvement_type="policy_patch",
                target={},
                expected_effect="probe",
            )

        def apply_variant(self, improvement: CandidateImprovement) -> HarnessVariant:
            return HarnessVariant(
                variant_id="broken-variant",
                candidate_improvement_id="wrong-improvement-id",
            )

    result = validate_agent_harness_adapter(BrokenAdapter())

    assert result.ok is False
    assert "agent_version must return a non-empty string" in result.errors
    assert "baseline Attempt.case_id must match GymCase.case_id" in result.errors
    assert "baseline Attempt.trace_id must match Trace.trace_id" in result.errors
    assert "HarnessVariant.candidate_improvement_id must match CandidateImprovement.improvement_id" in result.errors
    assert "candidate Attempt.harness_variant_id must match the provided variant" in result.errors
