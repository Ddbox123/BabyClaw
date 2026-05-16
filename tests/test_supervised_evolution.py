#!/usr/bin/env python3
"""监督进化模式最小闭环测试"""

import json
from pathlib import Path
from types import SimpleNamespace

from core.evaluation.supervised_evolution import (
    DEFAULT_BUNDLE_NAME,
    format_decision_record_summary,
    load_supervised_bundle,
    run_supervised_evolution_session,
)
from scripts.evolution_harness import HarnessResult


def _fake_result(status: str, reason: str, worktree_name: str) -> HarnessResult:
    return HarnessResult(
        harness_id=f"h_{worktree_name}",
        status=status,
        reason=reason,
        started_at="2026-05-14T00:00:00Z",
        ended_at="2026-05-14T00:00:10Z",
        repo_root="C:/repo",
        worktree_path=f"C:/repo/.tmp/{worktree_name}",
        base_head="abc123",
        checkpoint_commit="abc123",
        checkpoint_ref=None,
        tracked_dirty=False,
        untracked_files=[],
        command=["python", "agent.py"],
        timeout_seconds=60,
        restarts_observed=0,
        normalized_restarts_observed=0,
        restart_expected=False,
        restart_reentered=False,
        process_history=[],
        process_summary={},
        new_conversation_files=[],
        new_debug_files=[],
        stdout_tail=[],
        stderr_tail=[],
        agent_realtime_tail=[],
        last_observation={},
        post_restart_observation={},
        evolution_summary={
            "validation": {
                "passed": 1 if status == "success" else 0,
                "failed": 0 if status == "success" else 1,
                "last": None,
            },
            "transaction": {
                "opened": True,
                "closed": True,
                "status": "success",
                "txn_id": "txn_demo",
            },
            "git": {
                "commit_detected": False,
                "commit_refs": [],
            },
            "restart": {
                "expected": False,
                "triggered": False,
                "reentered": False,
            },
            "guarded_tools": {
                "total": 2,
                "restart_guarded": 0,
            },
        },
    )


def _fake_promotion_gate(decision: str = "PROMOTE"):
    return SimpleNamespace(
        collection_id="mixed_readiness_gate",
        episode_id=f"gym_{decision.lower()}",
        decision=decision,
        reason=f"gym {decision.lower()}",
        decision_path=f"workspace/gym/decisions/gym_{decision.lower()}.json",
        promotion_proposal_path=None,
    )


def test_load_supervised_bundle_reads_default_fixture(project_root: Path):
    bundle = load_supervised_bundle(DEFAULT_BUNDLE_NAME, project_root=project_root)

    assert bundle["bundle_name"] == DEFAULT_BUNDLE_NAME
    assert bundle["benchmark"] == "vibelution_supervised_evolution_dry_run"
    assert len(bundle["cases"]) >= 1
    safe_modify = next(item for item in bundle["cases"] if item["case_id"] == "safe_modify_probe")
    assert "def probe_marker() -> str" in safe_modify["baseline_prompt"]
    assert "import " not in safe_modify["baseline_prompt"]


def test_run_supervised_evolution_session_persists_decision_record(tmp_path: Path):
    bundle_dir = tmp_path / "workspace" / "evaluation" / "bundles"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = bundle_dir / f"{DEFAULT_BUNDLE_NAME}.json"
    bundle_path.write_text(
        """
{
  "benchmark": "dry",
  "bundle_name": "supervised_evolution_dry_run_v1",
  "cases": [
    {
      "case_id": "probe",
      "scenario": "transaction",
      "mode": "single_turn",
      "baseline_prompt": "baseline",
      "candidate_prompt": "candidate"
    }
  ]
}
        """.strip(),
        encoding="utf-8",
    )

    seen = []

    def fake_runner(**kwargs):
        seen.append((kwargs["prompt"], kwargs["scenario"], kwargs["mode"]))
        if kwargs["prompt"] == "baseline":
            return _fake_result("success", "baseline ok", "baseline")
        return _fake_result("success", "candidate ok", "candidate")

    decision = run_supervised_evolution_session(
        bundle_name=DEFAULT_BUNDLE_NAME,
        project_root=tmp_path,
        harness_runner=fake_runner,
    )

    assert seen == [
        ("baseline", "transaction", "single_turn"),
        ("candidate", "transaction", "single_turn"),
    ]
    assert decision.decision == "HOLD"
    assert decision.baseline_success_rate == 1.0
    assert decision.candidate_success_rate == 1.0
    assert decision.baseline_summary.validation_passed == 1
    assert decision.candidate_summary.total_guarded_tools == 2
    assert decision.gates[-1].name == "cost"
    assert decision.gates[-1].status == "hold"
    assert decision.case_summaries[0].decision_signal == "stable_success"
    assert decision.decision_path
    assert Path(decision.decision_path).exists()
    assert decision.policy_action["action"] == "HOLD"
    history_path = tmp_path / "workspace" / "supervised_evolution" / "history.jsonl"
    assert history_path.exists()
    observation_pool = tmp_path / "workspace" / "supervised_evolution" / "policy" / "candidate_observation_pool.jsonl"
    assert observation_pool.exists()
    proposal_path = Path(decision.policy_action["proposal_paths"][0])
    assert proposal_path.exists()
    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    assert proposal["status"] == "observing"
    assert proposal["observation_count"] == 1
    assert proposal["target"]["kind"] == "bundle_prompt_case"
    assert proposal["lineage"]["parent_baseline_id"] is None
    lineage_index_path = Path(decision.policy_action["lineage_index_path"])
    assert lineage_index_path.exists()
    lineage_index = json.loads(lineage_index_path.read_text(encoding="utf-8"))
    assert lineage_index["case_count"] == 1
    assert lineage_index["cases"][0]["proposal_count"] == 1
    audit_path = tmp_path / "workspace" / "evolution" / "audit.jsonl"
    assert audit_path.exists()
    rendered = format_decision_record_summary(decision)
    assert "gates:" in rendered
    assert "cases:" in rendered
    assert "runtime(avg):" in rendered
    assert "guarded tools:" in rendered
    assert "policy:" in rendered


def test_run_supervised_evolution_session_emits_progress_events(tmp_path: Path):
    bundle_dir = tmp_path / "workspace" / "evaluation" / "bundles"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = bundle_dir / f"{DEFAULT_BUNDLE_NAME}.json"
    bundle_path.write_text(
        """
{
  "benchmark": "dry",
  "bundle_name": "supervised_evolution_dry_run_v1",
  "default_timeout_seconds": 123,
  "cases": [
    {
      "case_id": "probe",
      "scenario": "transaction",
      "mode": "single_turn",
      "baseline_prompt": "baseline",
      "candidate_prompt": "candidate"
    }
  ]
}
        """.strip(),
        encoding="utf-8",
    )
    events = []

    def fake_runner(**kwargs):
        if kwargs["prompt"] == "baseline":
            return _fake_result("success", "baseline ok", "baseline")
        return _fake_result("failed", "candidate delegated to subagent", "candidate")

    run_supervised_evolution_session(
        bundle_name=DEFAULT_BUNDLE_NAME,
        project_root=tmp_path,
        harness_runner=fake_runner,
        progress_callback=events.append,
    )

    event_types = [event["event"] for event in events]
    assert event_types == [
        "session_start",
        "role_start",
        "role_finish",
        "role_start",
        "role_finish",
        "session_finish",
    ]
    first_start = events[1]
    assert first_start["case_index"] == 1
    assert first_start["case_total"] == 1
    assert first_start["case_id"] == "probe"
    assert first_start["role"] == "baseline"
    assert first_start["scenario"] == "transaction"
    assert first_start["mode"] == "single_turn"
    assert first_start["timeout_seconds"] == 123
    assert first_start["observational"] is True
    candidate_finish = events[4]
    assert candidate_finish["role"] == "candidate"
    assert candidate_finish["status"] == "failed"
    assert candidate_finish["drift_warning"] is True
    assert "subagent" in candidate_finish["reason"]
    assert candidate_finish["report_path"].endswith("probe_candidate.json")
    assert candidate_finish["worktree_path"].endswith("candidate")
    assert candidate_finish["observational"] is True


def test_run_supervised_evolution_session_emits_session_error(tmp_path: Path):
    bundle_dir = tmp_path / "workspace" / "evaluation" / "bundles"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = bundle_dir / f"{DEFAULT_BUNDLE_NAME}.json"
    bundle_path.write_text(
        """
{
  "benchmark": "dry",
  "bundle_name": "supervised_evolution_dry_run_v1",
  "cases": [
    {
      "case_id": "probe",
      "scenario": "transaction",
      "mode": "single_turn",
      "baseline_prompt": "baseline",
      "candidate_prompt": "candidate"
    }
  ]
}
        """.strip(),
        encoding="utf-8",
    )
    events = []

    def broken_runner(**kwargs):
        raise RuntimeError("harness exploded")

    try:
        run_supervised_evolution_session(
            bundle_name=DEFAULT_BUNDLE_NAME,
            project_root=tmp_path,
            harness_runner=broken_runner,
            progress_callback=events.append,
        )
    except RuntimeError:
        pass

    assert events[-1]["event"] == "session_error"
    assert events[-1]["case_id"] == "probe"
    assert events[-1]["role"] == "baseline"
    assert events[-1]["error_type"] == "RuntimeError"
    assert events[-1]["observational"] is True


def test_run_supervised_evolution_session_rolls_back_when_candidate_regresses(tmp_path: Path):
    bundle_dir = tmp_path / "workspace" / "evaluation" / "bundles"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = bundle_dir / f"{DEFAULT_BUNDLE_NAME}.json"
    bundle_path.write_text(
        """
{
  "benchmark": "dry",
  "bundle_name": "supervised_evolution_dry_run_v1",
  "cases": [
    {
      "case_id": "probe",
      "scenario": "transaction",
      "mode": "single_turn",
      "baseline_prompt": "baseline",
      "candidate_prompt": "candidate"
    }
  ]
}
        """.strip(),
        encoding="utf-8",
    )

    def fake_runner(**kwargs):
        if kwargs["prompt"] == "baseline":
            return _fake_result("success", "baseline ok", "baseline")
        return _fake_result("failed", "candidate bad", "candidate")

    decision = run_supervised_evolution_session(
        bundle_name=DEFAULT_BUNDLE_NAME,
        project_root=tmp_path,
        harness_runner=fake_runner,
    )

    assert decision.decision == "ROLLBACK"
    assert decision.score_delta == -1.0
    assert decision.gates[1].name == "safety"
    assert decision.gates[1].status == "fail"
    assert decision.policy_action["action"] == "ROLLBACK"
    rollback_pool = tmp_path / "workspace" / "supervised_evolution" / "policy" / "candidate_rollbacks.jsonl"
    assert rollback_pool.exists()
    proposal_path = Path(decision.policy_action["proposal_paths"][0])
    assert proposal_path.exists()
    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    assert proposal["status"] == "rolled_back"


def test_run_supervised_evolution_session_holds_improvement_when_cost_is_too_high(tmp_path: Path):
    bundle_dir = tmp_path / "workspace" / "evaluation" / "bundles"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = bundle_dir / f"{DEFAULT_BUNDLE_NAME}.json"
    bundle_path.write_text(
        """
{
  "benchmark": "dry",
  "bundle_name": "supervised_evolution_dry_run_v1",
  "cases": [
    {
      "case_id": "probe",
      "scenario": "transaction",
      "mode": "single_turn",
      "baseline_prompt": "baseline",
      "candidate_prompt": "candidate"
    }
  ]
}
        """.strip(),
        encoding="utf-8",
    )

    def fake_runner(**kwargs):
        if kwargs["prompt"] == "baseline":
            result = _fake_result("failed", "baseline bad", "baseline")
            result.ended_at = "2026-05-14T00:00:02Z"
            result.evolution_summary["guarded_tools"]["total"] = 1
            return result
        result = _fake_result("success", "candidate ok", "candidate")
        result.ended_at = "2026-05-14T00:00:12Z"
        result.evolution_summary["guarded_tools"]["total"] = 8
        result.new_conversation_files = ["a.jsonl", "b.jsonl"]
        return result

    decision = run_supervised_evolution_session(
        bundle_name=DEFAULT_BUNDLE_NAME,
        project_root=tmp_path,
        harness_runner=fake_runner,
    )

    assert decision.decision == "HOLD"
    assert decision.gates[-1].name == "cost"
    assert decision.gates[-1].status == "hold"
    assert "代价偏高" in decision.gates[-1].reason


def test_run_supervised_evolution_session_promotes_candidate_into_bundle(tmp_path: Path):
    bundle_dir = tmp_path / "workspace" / "evaluation" / "bundles"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = bundle_dir / f"{DEFAULT_BUNDLE_NAME}.json"
    bundle_path.write_text(
        """
{
  "benchmark": "dry",
  "bundle_name": "supervised_evolution_dry_run_v1",
  "cases": [
    {
      "case_id": "probe",
      "scenario": "transaction",
      "mode": "single_turn",
      "baseline_prompt": "baseline",
      "candidate_prompt": "candidate improved"
    }
  ]
}
        """.strip(),
        encoding="utf-8",
    )

    def fake_runner(**kwargs):
        if kwargs["prompt"] == "baseline":
            result = _fake_result("failed", "baseline bad", "baseline")
            result.ended_at = "2026-05-14T00:00:02Z"
            result.evolution_summary["guarded_tools"]["total"] = 1
            return result
        result = _fake_result("success", "candidate ok", "candidate")
        result.ended_at = "2026-05-14T00:00:03Z"
        result.evolution_summary["guarded_tools"]["total"] = 2
        return result

    decision = run_supervised_evolution_session(
        bundle_name=DEFAULT_BUNDLE_NAME,
        project_root=tmp_path,
        harness_runner=fake_runner,
        promotion_gate_runner=lambda **kwargs: _fake_promotion_gate("PROMOTE"),
    )

    assert decision.decision == "PROMOTE"
    assert decision.gates[-1].name == "gym_promotion"
    assert decision.gates[-1].status == "pass"
    assert decision.policy_action["action"] == "PROMOTE"
    updated_bundle = bundle_path.read_text(encoding="utf-8")
    assert '"baseline_prompt": "candidate improved"' in updated_bundle
    promotion_history = tmp_path / "workspace" / "supervised_evolution" / "policy" / "promotion_history.jsonl"
    baseline_registry = tmp_path / "workspace" / "supervised_evolution" / "policy" / "accepted_baselines.json"
    assert promotion_history.exists()
    assert baseline_registry.exists()
    proposal_path = Path(decision.policy_action["proposal_paths"][0])
    assert proposal_path.exists()
    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    assert proposal["status"] == "promoted"
    assert proposal["lineage"]["parent_baseline_id"] is None


def test_run_supervised_evolution_session_reuses_proposal_and_increments_observation_count(tmp_path: Path):
    bundle_dir = tmp_path / "workspace" / "evaluation" / "bundles"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = bundle_dir / f"{DEFAULT_BUNDLE_NAME}.json"
    bundle_path.write_text(
        """
{
  "benchmark": "dry",
  "bundle_name": "supervised_evolution_dry_run_v1",
  "cases": [
    {
      "case_id": "probe",
      "scenario": "transaction",
      "mode": "single_turn",
      "baseline_prompt": "baseline",
      "candidate_prompt": "candidate"
    }
  ]
}
        """.strip(),
        encoding="utf-8",
    )

    def fake_runner(**kwargs):
        if kwargs["prompt"] == "baseline":
            return _fake_result("success", "baseline ok", "baseline")
        return _fake_result("success", "candidate ok", "candidate")

    first = run_supervised_evolution_session(
        bundle_name=DEFAULT_BUNDLE_NAME,
        project_root=tmp_path,
        harness_runner=fake_runner,
    )
    second = run_supervised_evolution_session(
        bundle_name=DEFAULT_BUNDLE_NAME,
        project_root=tmp_path,
        harness_runner=fake_runner,
    )

    assert first.policy_action["proposal_paths"] == second.policy_action["proposal_paths"]
    proposal_path = Path(second.policy_action["proposal_paths"][0])
    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    assert proposal["status"] == "observing"
    assert proposal["observation_count"] == 2
    lineage_index = json.loads(Path(second.policy_action["lineage_index_path"]).read_text(encoding="utf-8"))
    assert lineage_index["cases"][0]["proposal_count"] == 1
    assert lineage_index["cases"][0]["observation_cycles"] == 2
    assert len(lineage_index["cases"][0]["chain"]) == 1


def test_run_supervised_evolution_session_records_parent_lineage_after_prior_promotion(tmp_path: Path):
    bundle_dir = tmp_path / "workspace" / "evaluation" / "bundles"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = bundle_dir / f"{DEFAULT_BUNDLE_NAME}.json"
    bundle_path.write_text(
        """
{
  "benchmark": "dry",
  "bundle_name": "supervised_evolution_dry_run_v1",
  "cases": [
    {
      "case_id": "probe",
      "scenario": "transaction",
      "mode": "single_turn",
      "baseline_prompt": "baseline",
      "candidate_prompt": "candidate improved"
    }
  ]
}
        """.strip(),
        encoding="utf-8",
    )

    call_index = {"value": 0}

    def promote_runner(**kwargs):
        call_index["value"] += 1
        if call_index["value"] % 2 == 1:
            result = _fake_result("failed", "baseline bad", "baseline")
            result.ended_at = "2026-05-14T00:00:02Z"
            result.evolution_summary["guarded_tools"]["total"] = 1
            return result
        result = _fake_result("success", "candidate ok", "candidate")
        result.ended_at = "2026-05-14T00:00:03Z"
        result.evolution_summary["guarded_tools"]["total"] = 2
        return result

    first = run_supervised_evolution_session(
        bundle_name=DEFAULT_BUNDLE_NAME,
        project_root=tmp_path,
        harness_runner=promote_runner,
        promotion_gate_runner=lambda **kwargs: _fake_promotion_gate("PROMOTE"),
    )

    bundle_path.write_text(
        """
{
  "benchmark": "dry",
  "bundle_name": "supervised_evolution_dry_run_v1",
  "cases": [
    {
      "case_id": "probe",
      "scenario": "transaction",
      "mode": "single_turn",
      "baseline_prompt": "candidate improved",
      "candidate_prompt": "candidate v2"
    }
  ]
}
        """.strip(),
        encoding="utf-8",
    )

    second = run_supervised_evolution_session(
        bundle_name=DEFAULT_BUNDLE_NAME,
        project_root=tmp_path,
        harness_runner=promote_runner,
        promotion_gate_runner=lambda **kwargs: _fake_promotion_gate("PROMOTE"),
    )

    assert second.decision == "PROMOTE"
    proposal_path = Path(second.policy_action["proposal_paths"][0])
    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    assert proposal["status"] == "promoted"
    assert proposal["lineage"]["parent_baseline_id"]
    assert proposal["lineage"]["parent_baseline_id"] != proposal["proposal_id"]
    assert proposal["lineage"]["parent_session_id"] == first.session_id
    lineage_index = json.loads(Path(second.policy_action["lineage_index_path"]).read_text(encoding="utf-8"))
    assert lineage_index["case_count"] == 1
    case_entry = lineage_index["cases"][0]
    assert case_entry["proposal_count"] == 2
    assert case_entry["current_baseline_id"] == proposal["proposal_id"]
    assert len(case_entry["chain"]) == 2
    chain_entry = next(item for item in case_entry["chain"] if item["proposal_id"] == proposal["proposal_id"])
    assert chain_entry["parent_baseline_id"] == proposal["lineage"]["parent_baseline_id"]


def test_run_supervised_evolution_session_rejects_promotion_when_gym_gate_rejects(tmp_path: Path):
    bundle_dir = tmp_path / "workspace" / "evaluation" / "bundles"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = bundle_dir / f"{DEFAULT_BUNDLE_NAME}.json"
    bundle_path.write_text(
        """
{
  "benchmark": "dry",
  "bundle_name": "supervised_evolution_dry_run_v1",
  "cases": [
    {
      "case_id": "probe",
      "scenario": "transaction",
      "mode": "single_turn",
      "baseline_prompt": "baseline",
      "candidate_prompt": "candidate improved"
    }
  ]
}
        """.strip(),
        encoding="utf-8",
    )

    def fake_runner(**kwargs):
        if kwargs["prompt"] == "baseline":
            result = _fake_result("failed", "baseline bad", "baseline")
            result.ended_at = "2026-05-14T00:00:02Z"
            result.evolution_summary["guarded_tools"]["total"] = 1
            return result
        result = _fake_result("success", "candidate ok", "candidate")
        result.ended_at = "2026-05-14T00:00:03Z"
        result.evolution_summary["guarded_tools"]["total"] = 2
        return result

    decision = run_supervised_evolution_session(
        bundle_name=DEFAULT_BUNDLE_NAME,
        project_root=tmp_path,
        harness_runner=fake_runner,
        promotion_gate_runner=lambda **kwargs: _fake_promotion_gate("REJECT"),
    )

    assert decision.decision == "REJECT"
    assert decision.gates[-1].name == "gym_promotion"
    assert decision.gates[-1].status == "fail"
    assert decision.policy_action["action"] == "REJECT"
    assert '"baseline_prompt": "baseline"' in bundle_path.read_text(encoding="utf-8")


def test_run_supervised_evolution_session_holds_promotion_when_gym_gate_observes(tmp_path: Path):
    bundle_dir = tmp_path / "workspace" / "evaluation" / "bundles"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = bundle_dir / f"{DEFAULT_BUNDLE_NAME}.json"
    bundle_path.write_text(
        """
{
  "benchmark": "dry",
  "bundle_name": "supervised_evolution_dry_run_v1",
  "cases": [
    {
      "case_id": "probe",
      "scenario": "transaction",
      "mode": "single_turn",
      "baseline_prompt": "baseline",
      "candidate_prompt": "candidate improved"
    }
  ]
}
        """.strip(),
        encoding="utf-8",
    )

    def fake_runner(**kwargs):
        if kwargs["prompt"] == "baseline":
            result = _fake_result("failed", "baseline bad", "baseline")
            result.ended_at = "2026-05-14T00:00:02Z"
            result.evolution_summary["guarded_tools"]["total"] = 1
            return result
        result = _fake_result("success", "candidate ok", "candidate")
        result.ended_at = "2026-05-14T00:00:03Z"
        result.evolution_summary["guarded_tools"]["total"] = 2
        return result

    decision = run_supervised_evolution_session(
        bundle_name=DEFAULT_BUNDLE_NAME,
        project_root=tmp_path,
        harness_runner=fake_runner,
        promotion_gate_runner=lambda **kwargs: _fake_promotion_gate("OBSERVE"),
    )

    assert decision.decision == "HOLD"
    assert decision.gates[-1].name == "gym_promotion"
    assert decision.gates[-1].status == "hold"
    assert decision.policy_action["action"] == "HOLD"
    assert '"baseline_prompt": "baseline"' in bundle_path.read_text(encoding="utf-8")
