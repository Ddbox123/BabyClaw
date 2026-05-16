#!/usr/bin/env python3
"""Vibelution adapter tests for the embeddable Gym engine."""

from pathlib import Path

from core.gym import (
    EvolutionEngine,
    VibelutionAgentHarnessAdapter,
    materialize_coordination_workflow_cases,
    materialize_intelligence_strategy_cases,
    build_local_transaction_exercise,
    materialize_local_transaction_cases,
)
from scripts.evolution_harness import HarnessResult


def _fake_harness_result(*, status: str, harness_id: str) -> HarnessResult:
    return HarnessResult(
        harness_id=harness_id,
        status=status,
        reason=f"{status} reason",
        started_at="2026-05-15T00:00:00Z",
        ended_at="2026-05-15T00:00:03Z",
        repo_root="C:/repo",
        worktree_path="C:/repo/.tmp/worktree",
        base_head="abc123",
        checkpoint_commit="abc123",
        checkpoint_ref=None,
        tracked_dirty=False,
        untracked_files=[],
        command=["python", "agent.py"],
        timeout_seconds=600,
        restarts_observed=0,
        normalized_restarts_observed=0,
        restart_expected=False,
        restart_reentered=False,
        process_history=[],
        process_summary={"agent_count": 1},
        new_conversation_files=["conversation.jsonl"],
        new_debug_files=["debug.log"],
        stdout_tail=["ok"],
        stderr_tail=[],
        agent_realtime_tail=[],
        last_observation={"phase": "done"},
        post_restart_observation={},
        evolution_summary={
            "validation": {"passed": 1 if status == "success" else 0, "failed": 0 if status == "success" else 1},
            "tasks": {"created": 0, "updated": 0, "completed": 0},
            "guarded_tools": {"total": 2},
        },
    )


def test_vibelution_adapter_maps_gym_case_to_harness_attempt_and_trace(tmp_path: Path):
    calls = []

    def fake_runner(**kwargs):
        calls.append(kwargs)
        return _fake_harness_result(status="success", harness_id=f"h{len(calls)}")

    adapter = VibelutionAgentHarnessAdapter(
        project_root=tmp_path,
        harness_runner=fake_runner,
        version_label="vibelution-test",
    )
    case = materialize_local_transaction_cases()[0]

    evidence = adapter.run_case(case, role="baseline")

    assert calls[0]["repo_root"] == tmp_path
    assert calls[0]["mode"] == "single_turn"
    assert calls[0]["scenario"] == "modify_rollback"
    assert calls[0]["expect_restart"] is False
    assert evidence.attempt.agent_version == "vibelution-test"
    assert evidence.attempt.score.success is True
    assert evidence.attempt.score.latency == 3.0
    assert evidence.attempt.score.validation["passed"] == 1
    assert evidence.trace.events[0]["status"] == "success"
    assert evidence.trace.artifacts["worktree_path"] == "C:/repo/.tmp/worktree"


def test_vibelution_adapter_can_host_engine_without_engine_importing_process_details(tmp_path: Path):
    calls = []

    def fake_runner(**kwargs):
        calls.append(kwargs)
        status = "failed" if len(calls) == 1 else "success"
        return _fake_harness_result(status=status, harness_id=f"h{len(calls)}")

    adapter = VibelutionAgentHarnessAdapter(project_root=tmp_path, harness_runner=fake_runner)
    engine = EvolutionEngine(adapter)
    case = materialize_local_transaction_cases()[0]

    episode = engine.run_proposal_only_episode(
        episode_id="vibelution_adapter_episode",
        exercise=build_local_transaction_exercise(),
        cases=[case],
    )

    assert episode.decision == "PROMOTE"
    assert len(calls) == 2
    assert "Candidate harness variant context" in calls[1]["prompt"]
    assert episode.baseline_attempts[0].score.success is False
    assert episode.candidate_attempts[0].score.success is True


def test_vibelution_adapter_scores_coordination_requirements(tmp_path: Path):
    def fake_runner(**kwargs):
        result = _fake_harness_result(status="success", harness_id="coordination")
        result.evolution_summary["tasks"] = {"created": 1, "updated": 1, "completed": 1}
        return result

    adapter = VibelutionAgentHarnessAdapter(project_root=tmp_path, harness_runner=fake_runner)
    case = materialize_coordination_workflow_cases()[0]

    evidence = adapter.run_case(case, role="baseline")

    assert evidence.attempt.score.success is False
    assert evidence.attempt.score.validation["requirements_met"] is False
    assert evidence.attempt.score.validation["tasks"] == {"created": 1, "updated": 1, "completed": 1}


def test_vibelution_adapter_rejects_forbidden_coordination_tools(tmp_path: Path):
    def fake_runner(**kwargs):
        result = _fake_harness_result(status="success", harness_id="coordination_forbidden")
        result.evolution_summary["validation"] = {"passed": 1, "failed": 0}
        result.evolution_summary["tasks"] = {"created": 1, "updated": 2, "completed": 2}
        result.evolution_summary["tool_sequence_tail"] = [
            "open_evolution_transaction_tool:success",
            "spawn_agent_tool:success",
            "close_evolution_transaction_tool:success",
        ]
        return result

    adapter = VibelutionAgentHarnessAdapter(project_root=tmp_path, harness_runner=fake_runner)
    case = materialize_coordination_workflow_cases()[0]

    evidence = adapter.run_case(case, role="baseline")

    assert evidence.attempt.score.success is False
    assert evidence.attempt.score.validation["requirements_met"] is False


def test_vibelution_adapter_requires_strategy_evidence_tool(tmp_path: Path):
    def fake_runner(**kwargs):
        result = _fake_harness_result(status="success", harness_id="strategy")
        result.evolution_summary["tool_sequence_tail"] = ["read_file_tool:success"]
        return result

    adapter = VibelutionAgentHarnessAdapter(project_root=tmp_path, harness_runner=fake_runner)
    case = materialize_intelligence_strategy_cases()[0]

    evidence = adapter.run_case(case, role="baseline")

    assert evidence.attempt.score.success is True
    assert evidence.attempt.score.training_tier == "intelligence"
    assert evidence.attempt.score.validation["requirements_met"] is True


def test_vibelution_adapter_rejects_strategy_without_required_tool(tmp_path: Path):
    def fake_runner(**kwargs):
        return _fake_harness_result(status="success", harness_id="strategy_missing")

    adapter = VibelutionAgentHarnessAdapter(project_root=tmp_path, harness_runner=fake_runner)
    case = materialize_intelligence_strategy_cases()[0]

    evidence = adapter.run_case(case, role="baseline")

    assert evidence.attempt.score.success is False
    assert evidence.attempt.score.validation["requirements_met"] is False
