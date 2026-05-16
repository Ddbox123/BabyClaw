# -*- coding: utf-8 -*-
"""Vibelution host adapter for the embeddable Evolution Engine."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from core.infrastructure.workspace_manager import get_workspace
from scripts.evolution_harness import HarnessResult, run_harness

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


HarnessRunner = Callable[..., HarnessResult]


class VibelutionAgentHarnessAdapter(AgentHarnessAdapter):
    """Adapter that lets the generic Evolution Engine run Vibelution's Agent."""

    def __init__(
        self,
        *,
        project_root: Optional[Path] = None,
        harness_runner: HarnessRunner = run_harness,
        keep_worktree: bool = False,
        post_restart_observe_seconds: int = 20,
        version_label: str = "vibelution-agent",
    ) -> None:
        self.project_root = (project_root or get_workspace().project_root).resolve()
        self.harness_runner = harness_runner
        self.keep_worktree = keep_worktree
        self.post_restart_observe_seconds = post_restart_observe_seconds
        self.version_label = version_label

    def agent_version(self) -> str:
        return self.version_label

    def run_case(self, case: GymCase, *, role: str, variant: HarnessVariant | None = None) -> AttemptEvidence:
        validation = case.validation or {}
        prompt = self._prompt_for_case(case, role=role, variant=variant)
        result = self.harness_runner(
            repo_root=self.project_root,
            mode=str(validation.get("mode") or "single_turn"),
            prompt=prompt,
            timeout_seconds=int(validation.get("timeout_seconds") or 600),
            expect_restart=bool(validation.get("expect_restart", False)),
            post_restart_observe_seconds=self.post_restart_observe_seconds,
            keep_worktree=self.keep_worktree,
            scenario=str(validation.get("scenario") or "transaction"),
        )
        trace = self._trace_from_result(case, result, role=role, variant=variant)
        attempt = Attempt(
            attempt_id=f"{result.harness_id}:{role}:{case.case_id}",
            case_id=case.case_id,
            agent_version=self.agent_version(),
            trace_id=trace.trace_id,
            score=self._score_from_result(result, case=case),
            role=role,
            harness_variant_id=variant.variant_id if variant else None,
            dataset_splits=case.dataset_splits,
            training_tier=case.training_tier,
        )
        return AttemptEvidence(attempt=attempt, trace=trace)

    def propose_improvement(self, exercise: GymExercise, diagnosis: CriticDiagnosis) -> CandidateImprovement:
        return CandidateImprovement(
            improvement_id=f"{exercise.exercise_id}:{diagnosis.harness_gap}:proposal",
            improvement_type="verifier_patch" if diagnosis.harness_gap == "validation" else "policy_patch",
            target={
                "kind": "vibelution_harness_policy",
                "exercise_id": exercise.exercise_id,
                "harness_gap": diagnosis.harness_gap,
            },
            expected_effect=diagnosis.reason,
            payload={"evidence": diagnosis.evidence},
        )

    def apply_variant(self, improvement: CandidateImprovement) -> HarnessVariant:
        return HarnessVariant(
            variant_id=f"vibelution_variant:{improvement.improvement_id}",
            candidate_improvement_id=improvement.improvement_id,
            application_mode="proposal_only",
        )

    def _prompt_for_case(self, case: GymCase, *, role: str, variant: HarnessVariant | None) -> str:
        prompt = case.prompt
        if role != "candidate" or variant is None:
            return prompt
        return (
            f"{prompt}\n\n"
            "Candidate harness variant context:\n"
            f"- variant_id: {variant.variant_id}\n"
            "- Apply the proposed improvement as an execution policy for this attempt only.\n"
            "- Do not persist baseline changes unless the task explicitly asks for normal file edits."
        )

    def _trace_from_result(
        self,
        case: GymCase,
        result: HarnessResult,
        *,
        role: str,
        variant: HarnessVariant | None,
    ) -> Trace:
        return Trace(
            trace_id=f"harness:{result.harness_id}",
            case_id=case.case_id,
            events=[
                {
                    "type": "harness_result",
                    "role": role,
                    "status": result.status,
                    "reason": result.reason,
                    "started_at": result.started_at,
                    "ended_at": result.ended_at,
                    "variant_id": variant.variant_id if variant else None,
                    "new_conversation_files": result.new_conversation_files,
                    "new_debug_files": result.new_debug_files,
                    "stdout_tail": result.stdout_tail,
                    "stderr_tail": result.stderr_tail,
                    "evolution_summary": result.evolution_summary,
                }
            ],
            artifacts={
                "worktree_path": result.worktree_path,
                "checkpoint_commit": result.checkpoint_commit,
                "command": result.command,
                "process_summary": result.process_summary,
                "last_observation": result.last_observation,
                "post_restart_observation": result.post_restart_observation,
            },
        )

    def _score_from_result(self, result: HarnessResult, *, case: GymCase) -> Score:
        summary = result.evolution_summary or {}
        validation = summary.get("validation") or {}
        tasks = summary.get("tasks") or {}
        guarded_tools = summary.get("guarded_tools") or {}
        requirements_met = _case_requirements_met(case, result=result, summary=summary)
        success = result.status == "success" and requirements_met
        regression_risk = 0.0
        if result.restart_expected and not result.restart_reentered:
            regression_risk += 1.0
        if not success:
            regression_risk += 1.0
        safety_risk = 1.0 if result.tracked_dirty else 0.0
        return Score(
            success=success,
            quality=1.0 if success else 0.0,
            cost=float(int(guarded_tools.get("total") or 0)),
            latency=_elapsed_seconds(result.started_at, result.ended_at),
            validation={
                "passed": int(validation.get("passed") or 0),
                "failed": int(validation.get("failed") or 0),
                "last": validation.get("last"),
                "requirements_met": requirements_met,
                "tasks": {
                    "created": int(tasks.get("created") or 0),
                    "updated": int(tasks.get("updated") or 0),
                    "completed": int(tasks.get("completed") or 0),
                },
            },
            tool_errors=int(validation.get("failed") or 0) + (0 if requirements_met else 1),
            regression_risk=regression_risk,
            safety_risk=safety_risk,
            training_tier=case.training_tier,
        )


def _elapsed_seconds(started_at: str, ended_at: str) -> float:
    try:
        start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        end = datetime.fromisoformat(ended_at.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    return max(0.0, round((end - start).total_seconds(), 3))


def _case_requirements_met(case: GymCase, *, result: HarnessResult, summary: dict) -> bool:
    validation_spec = case.validation or {}
    validation = summary.get("validation") or {}
    tasks = summary.get("tasks") or {}
    checks = [
        int(validation.get("passed") or 0) >= int(validation_spec.get("min_validation_passed") or 0),
        int(tasks.get("created") or 0) >= int(validation_spec.get("min_tasks_created") or 0),
        int(tasks.get("updated") or 0) >= int(validation_spec.get("min_tasks_updated") or 0),
        int(tasks.get("completed") or 0) >= int(validation_spec.get("min_tasks_completed") or 0),
    ]
    if validation_spec.get("expect_restart") is not None:
        if bool(validation_spec.get("expect_restart", False)):
            checks.append(bool(result.restart_reentered))
    forbidden_tools = {str(item) for item in validation_spec.get("forbidden_tools") or []}
    required_tools = {str(item) for item in validation_spec.get("required_tools") or []}
    if forbidden_tools or required_tools:
        observed_tools = _observed_tool_names(summary)
    if forbidden_tools:
        checks.append(not forbidden_tools.intersection(observed_tools))
    if required_tools:
        checks.append(required_tools.issubset(observed_tools))
    return all(checks)


def _observed_tool_names(summary: dict) -> set[str]:
    names: set[str] = set()
    for key in ("tool_sequence_tail", "tool_phase_sequence_tail"):
        for item in summary.get(key) or []:
            text = str(item)
            parts = text.split(":")
            if key == "tool_sequence_tail" and parts:
                names.add(parts[0])
            elif key == "tool_phase_sequence_tail" and len(parts) >= 2:
                names.add(parts[1])
    return names
