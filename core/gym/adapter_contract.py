# -*- coding: utf-8 -*-
"""Runtime contract checks for Gym host adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .engine import AgentHarnessAdapter, AttemptEvidence, CriticDiagnosis
from .local import build_local_transaction_exercise, materialize_local_transaction_cases
from .models import CandidateImprovement, GymCase, GymExercise, HarnessVariant


@dataclass
class AdapterContractCheck:
    ok: bool
    agent_version: str = ""
    errors: list[str] = field(default_factory=list)

    def raise_for_errors(self) -> None:
        if self.ok:
            return
        raise ValueError("Invalid Gym AgentHarnessAdapter: " + "; ".join(self.errors))


def validate_agent_harness_adapter(
    adapter: AgentHarnessAdapter,
    *,
    exercise: Optional[GymExercise] = None,
    case: Optional[GymCase] = None,
) -> AdapterContractCheck:
    """Run a small adapter self-check without invoking the full engine."""

    errors: list[str] = []
    active_exercise = exercise or build_local_transaction_exercise()
    active_case = case or materialize_local_transaction_cases()[0]

    try:
        agent_version = adapter.agent_version()
    except Exception as exc:
        return AdapterContractCheck(ok=False, errors=[f"agent_version failed: {type(exc).__name__}: {exc}"])

    agent_version_text = str(agent_version or "").strip()
    if not agent_version_text:
        errors.append("agent_version must return a non-empty string")

    baseline = _call_run_case(adapter, active_case, role="baseline", variant=None, errors=errors)
    if baseline:
        _validate_evidence(
            baseline,
            case=active_case,
            role="baseline",
            expected_agent_version=agent_version_text,
            expected_variant_id=None,
            errors=errors,
        )

    diagnosis = CriticDiagnosis(
        harness_gap="validation",
        evidence=[baseline.trace.trace_id] if baseline else [],
        reason="Adapter contract probe",
    )
    improvement = _call_propose_improvement(adapter, active_exercise, diagnosis, errors=errors)
    variant = _call_apply_variant(adapter, improvement, errors=errors) if improvement else None

    if variant:
        candidate = _call_run_case(adapter, active_case, role="candidate", variant=variant, errors=errors)
        if candidate:
            _validate_evidence(
                candidate,
                case=active_case,
                role="candidate",
                expected_agent_version=agent_version_text,
                expected_variant_id=variant.variant_id,
                errors=errors,
            )

    return AdapterContractCheck(ok=not errors, agent_version=agent_version_text, errors=errors)


def _call_run_case(
    adapter: AgentHarnessAdapter,
    case: GymCase,
    *,
    role: str,
    variant: HarnessVariant | None,
    errors: list[str],
) -> AttemptEvidence | None:
    try:
        return adapter.run_case(case, role=role, variant=variant)
    except Exception as exc:
        errors.append(f"run_case({role}) failed: {type(exc).__name__}: {exc}")
        return None


def _call_propose_improvement(
    adapter: AgentHarnessAdapter,
    exercise: GymExercise,
    diagnosis: CriticDiagnosis,
    *,
    errors: list[str],
) -> CandidateImprovement | None:
    try:
        improvement = adapter.propose_improvement(exercise, diagnosis)
    except Exception as exc:
        errors.append(f"propose_improvement failed: {type(exc).__name__}: {exc}")
        return None
    if not isinstance(improvement, CandidateImprovement):
        errors.append("propose_improvement must return CandidateImprovement")
        return None
    if not str(improvement.improvement_id or "").strip():
        errors.append("CandidateImprovement.improvement_id must be non-empty")
    if not str(improvement.improvement_type or "").strip():
        errors.append("CandidateImprovement.improvement_type must be non-empty")
    if not str(improvement.expected_effect or "").strip():
        errors.append("CandidateImprovement.expected_effect must be non-empty")
    return improvement


def _call_apply_variant(
    adapter: AgentHarnessAdapter,
    improvement: CandidateImprovement,
    *,
    errors: list[str],
) -> HarnessVariant | None:
    try:
        variant = adapter.apply_variant(improvement)
    except Exception as exc:
        errors.append(f"apply_variant failed: {type(exc).__name__}: {exc}")
        return None
    if not isinstance(variant, HarnessVariant):
        errors.append("apply_variant must return HarnessVariant")
        return None
    if not str(variant.variant_id or "").strip():
        errors.append("HarnessVariant.variant_id must be non-empty")
    if variant.candidate_improvement_id != improvement.improvement_id:
        errors.append("HarnessVariant.candidate_improvement_id must match CandidateImprovement.improvement_id")
    return variant


def _validate_evidence(
    evidence: AttemptEvidence,
    *,
    case: GymCase,
    role: str,
    expected_agent_version: str,
    expected_variant_id: str | None,
    errors: list[str],
) -> None:
    if not isinstance(evidence, AttemptEvidence):
        errors.append(f"run_case({role}) must return AttemptEvidence")
        return
    attempt = evidence.attempt
    trace = evidence.trace
    if attempt.case_id != case.case_id:
        errors.append(f"{role} Attempt.case_id must match GymCase.case_id")
    if attempt.role != role:
        errors.append(f"{role} Attempt.role must be {role!r}")
    if attempt.agent_version != expected_agent_version:
        errors.append(f"{role} Attempt.agent_version must match adapter.agent_version")
    if attempt.trace_id != trace.trace_id:
        errors.append(f"{role} Attempt.trace_id must match Trace.trace_id")
    if trace.case_id != case.case_id:
        errors.append(f"{role} Trace.case_id must match GymCase.case_id")
    if attempt.training_tier != case.training_tier:
        errors.append(f"{role} Attempt.training_tier must match GymCase.training_tier")
    if attempt.score.training_tier != case.training_tier:
        errors.append(f"{role} Score.training_tier must match GymCase.training_tier")
    if attempt.dataset_splits != case.dataset_splits:
        errors.append(f"{role} Attempt.dataset_splits must match GymCase.dataset_splits")
    if attempt.harness_variant_id != expected_variant_id:
        errors.append(f"{role} Attempt.harness_variant_id must match the provided variant")


__all__ = ["AdapterContractCheck", "validate_agent_harness_adapter"]
