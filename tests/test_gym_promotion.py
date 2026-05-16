#!/usr/bin/env python3
"""Gym promotion application tests."""

import json
from pathlib import Path

import pytest

from core.gym.promotion import (
    activate_gym_promotion_proposal,
    apply_gym_promotion_proposal,
    rollback_gym_promotion_proposal,
)
from tests.test_gym_runner import RunnerFakeAdapter
from core.gym import run_gym_collection_episode
from core.gym.runner import main


def test_apply_gym_promotion_proposal_marks_proposal_applied_and_writes_ledger(tmp_path: Path):
    result = run_gym_collection_episode(
        collection_id="foundation_local_stability",
        project_root=tmp_path,
        adapter=RunnerFakeAdapter(),
        episode_id="apply_episode",
    )

    applied = apply_gym_promotion_proposal(
        result.promotion_proposal_path,
        project_root=tmp_path,
        approved_by="operator",
    )

    assert applied.status == "applied"
    assert applied.approved_by == "operator"
    assert Path(applied.decision_path).exists()
    assert Path(applied.trace_index_path).exists()

    proposal = json.loads(Path(result.promotion_proposal_path).read_text(encoding="utf-8"))
    assert proposal["status"] == "applied"
    assert proposal["applied_by"] == "operator"
    assert proposal["trace_index_path"] == applied.trace_index_path

    ledger_path = tmp_path / "workspace" / "gym" / "applied_promotions.jsonl"
    ledger_rows = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines()]
    assert ledger_rows[-1]["proposal_id"] == applied.proposal_id
    assert ledger_rows[-1]["apply_mode"] == "record_only"


def test_apply_gym_promotion_proposal_rejects_missing_trace_index(tmp_path: Path):
    result = run_gym_collection_episode(
        collection_id="foundation_local_stability",
        project_root=tmp_path,
        adapter=RunnerFakeAdapter(),
        episode_id="missing_trace_episode",
    )
    Path(result.trace_index_path).unlink()

    with pytest.raises(ValueError, match="trace index"):
        apply_gym_promotion_proposal(result.promotion_proposal_path, project_root=tmp_path)

    proposal = json.loads(Path(result.promotion_proposal_path).read_text(encoding="utf-8"))
    assert proposal["status"] == "proposed"


def test_apply_gym_promotion_proposal_is_idempotent(tmp_path: Path):
    result = run_gym_collection_episode(
        collection_id="foundation_local_stability",
        project_root=tmp_path,
        adapter=RunnerFakeAdapter(),
        episode_id="idempotent_apply_episode",
    )

    first = apply_gym_promotion_proposal(result.promotion_proposal_path, project_root=tmp_path)
    second = apply_gym_promotion_proposal(result.promotion_proposal_path, project_root=tmp_path)

    assert first.proposal_id == second.proposal_id
    assert second.status == "applied"
    ledger_path = tmp_path / "workspace" / "gym" / "applied_promotions.jsonl"
    assert len(ledger_path.read_text(encoding="utf-8").splitlines()) == 1


def test_gym_cli_applies_promotion_proposal(tmp_path: Path, capsys):
    result = run_gym_collection_episode(
        collection_id="foundation_local_stability",
        project_root=tmp_path,
        adapter=RunnerFakeAdapter(),
        episode_id="cli_apply_episode",
    )

    assert main(
        [
            "--apply-proposal",
            result.promotion_proposal_path,
            "--project-root",
            str(tmp_path),
            "--approved-by",
            "cli",
            "--json",
        ]
    ) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "applied"
    assert output["approved_by"] == "cli"


def test_rollback_gym_promotion_proposal_marks_proposal_rolled_back_and_writes_ledger(tmp_path: Path):
    result = run_gym_collection_episode(
        collection_id="foundation_local_stability",
        project_root=tmp_path,
        adapter=RunnerFakeAdapter(),
        episode_id="rollback_episode",
    )
    applied = apply_gym_promotion_proposal(
        result.promotion_proposal_path,
        project_root=tmp_path,
        approved_by="operator",
    )

    rolled_back = rollback_gym_promotion_proposal(
        result.promotion_proposal_path,
        project_root=tmp_path,
        rolled_back_by="reviewer",
        reason="post-apply verification failed",
    )

    assert rolled_back.status == "rolled_back"
    assert rolled_back.proposal_id == applied.proposal_id
    assert rolled_back.rolled_back_by == "reviewer"
    assert rolled_back.reason == "post-apply verification failed"
    assert Path(rolled_back.decision_path).exists()
    assert Path(rolled_back.trace_index_path).exists()

    proposal = json.loads(Path(result.promotion_proposal_path).read_text(encoding="utf-8"))
    assert proposal["status"] == "rolled_back"
    assert proposal["rolled_back_by"] == "reviewer"
    assert proposal["rollback_reason"] == "post-apply verification failed"
    assert proposal["applied_by"] == "operator"

    ledger_path = tmp_path / "workspace" / "gym" / "rolled_back_promotions.jsonl"
    ledger_rows = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines()]
    assert ledger_rows[-1]["proposal_id"] == rolled_back.proposal_id
    assert ledger_rows[-1]["reason"] == "post-apply verification failed"


def test_rollback_gym_promotion_proposal_rejects_unapplied_proposal(tmp_path: Path):
    result = run_gym_collection_episode(
        collection_id="foundation_local_stability",
        project_root=tmp_path,
        adapter=RunnerFakeAdapter(),
        episode_id="unapplied_rollback_episode",
    )

    with pytest.raises(ValueError, match="applied"):
        rollback_gym_promotion_proposal(result.promotion_proposal_path, project_root=tmp_path)

    proposal = json.loads(Path(result.promotion_proposal_path).read_text(encoding="utf-8"))
    assert proposal["status"] == "proposed"


def test_rollback_gym_promotion_proposal_is_idempotent(tmp_path: Path):
    result = run_gym_collection_episode(
        collection_id="foundation_local_stability",
        project_root=tmp_path,
        adapter=RunnerFakeAdapter(),
        episode_id="idempotent_rollback_episode",
    )
    apply_gym_promotion_proposal(result.promotion_proposal_path, project_root=tmp_path)

    first = rollback_gym_promotion_proposal(result.promotion_proposal_path, project_root=tmp_path)
    second = rollback_gym_promotion_proposal(result.promotion_proposal_path, project_root=tmp_path)

    assert first.proposal_id == second.proposal_id
    assert second.status == "rolled_back"
    ledger_path = tmp_path / "workspace" / "gym" / "rolled_back_promotions.jsonl"
    assert len(ledger_path.read_text(encoding="utf-8").splitlines()) == 1


def test_gym_cli_rolls_back_promotion_proposal(tmp_path: Path, capsys):
    result = run_gym_collection_episode(
        collection_id="foundation_local_stability",
        project_root=tmp_path,
        adapter=RunnerFakeAdapter(),
        episode_id="cli_rollback_episode",
    )
    apply_gym_promotion_proposal(result.promotion_proposal_path, project_root=tmp_path)

    assert main(
        [
            "--rollback-proposal",
            result.promotion_proposal_path,
            "--project-root",
            str(tmp_path),
            "--rolled-back-by",
            "cli",
            "--rollback-reason",
            "manual review",
            "--json",
        ]
    ) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "rolled_back"
    assert output["rolled_back_by"] == "cli"
    assert output["reason"] == "manual review"


def test_activate_gym_promotion_proposal_records_active_advisory_baseline(tmp_path: Path):
    result = run_gym_collection_episode(
        collection_id="foundation_local_stability",
        project_root=tmp_path,
        adapter=RunnerFakeAdapter(),
        episode_id="activate_episode",
    )
    apply_gym_promotion_proposal(result.promotion_proposal_path, project_root=tmp_path)

    activation = activate_gym_promotion_proposal(
        result.promotion_proposal_path,
        project_root=tmp_path,
        activated_by="operator",
    )

    assert activation.status == "active"
    assert activation.runtime_effect == "not_applied"
    assert activation.agent_consumption == "advisory"
    assert Path(activation.decision_path).exists()
    assert Path(activation.trace_index_path).exists()

    proposal = json.loads(Path(result.promotion_proposal_path).read_text(encoding="utf-8"))
    assert proposal["status"] == "active"
    assert proposal["activated_by"] == "operator"
    assert proposal["runtime_effect"] == "not_applied"
    assert proposal["agent_consumption"] == "advisory"

    registry_path = tmp_path / "workspace" / "gym" / "active_promotions.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    entry = registry["active"][activation.target_key]
    assert entry["proposal_id"] == activation.proposal_id
    assert entry["runtime_effect"] == "not_applied"
    assert entry["agent_consumption"] == "advisory"

    history_path = tmp_path / "workspace" / "gym" / "activation_history.jsonl"
    history_rows = [json.loads(line) for line in history_path.read_text(encoding="utf-8").splitlines()]
    assert history_rows[-1]["proposal_id"] == activation.proposal_id
    assert history_rows[-1]["previous_active_proposal_id"] is None


def test_activate_gym_promotion_proposal_rejects_rolled_back_proposal(tmp_path: Path):
    result = run_gym_collection_episode(
        collection_id="foundation_local_stability",
        project_root=tmp_path,
        adapter=RunnerFakeAdapter(),
        episode_id="rolled_back_activate_episode",
    )
    apply_gym_promotion_proposal(result.promotion_proposal_path, project_root=tmp_path)
    rollback_gym_promotion_proposal(result.promotion_proposal_path, project_root=tmp_path)

    with pytest.raises(ValueError, match="applied"):
        activate_gym_promotion_proposal(result.promotion_proposal_path, project_root=tmp_path)

    proposal = json.loads(Path(result.promotion_proposal_path).read_text(encoding="utf-8"))
    assert proposal["status"] == "rolled_back"
    assert not (tmp_path / "workspace" / "gym" / "active_promotions.json").exists()


def test_activate_gym_promotion_proposal_supersedes_previous_active_for_target(tmp_path: Path):
    first = run_gym_collection_episode(
        collection_id="foundation_local_stability",
        project_root=tmp_path,
        adapter=RunnerFakeAdapter(),
        episode_id="first_active_episode",
    )
    second = run_gym_collection_episode(
        collection_id="foundation_local_stability",
        project_root=tmp_path,
        adapter=RunnerFakeAdapter(),
        episode_id="second_active_episode",
    )
    apply_gym_promotion_proposal(first.promotion_proposal_path, project_root=tmp_path)
    apply_gym_promotion_proposal(second.promotion_proposal_path, project_root=tmp_path)

    first_activation = activate_gym_promotion_proposal(first.promotion_proposal_path, project_root=tmp_path)
    second_activation = activate_gym_promotion_proposal(second.promotion_proposal_path, project_root=tmp_path)

    assert first_activation.target_key == second_activation.target_key
    first_proposal = json.loads(Path(first.promotion_proposal_path).read_text(encoding="utf-8"))
    second_proposal = json.loads(Path(second.promotion_proposal_path).read_text(encoding="utf-8"))
    assert first_proposal["status"] == "superseded"
    assert first_proposal["superseded_by"] == second_activation.proposal_id
    assert second_proposal["status"] == "active"

    registry = json.loads((tmp_path / "workspace" / "gym" / "active_promotions.json").read_text(encoding="utf-8"))
    assert registry["active"][second_activation.target_key]["proposal_id"] == second_activation.proposal_id
    history_rows = [
        json.loads(line)
        for line in (tmp_path / "workspace" / "gym" / "activation_history.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert history_rows[-1]["previous_active_proposal_id"] == first_activation.proposal_id


def test_gym_cli_activates_promotion_proposal(tmp_path: Path, capsys):
    result = run_gym_collection_episode(
        collection_id="foundation_local_stability",
        project_root=tmp_path,
        adapter=RunnerFakeAdapter(),
        episode_id="cli_activate_episode",
    )
    apply_gym_promotion_proposal(result.promotion_proposal_path, project_root=tmp_path)

    assert main(
        [
            "--activate-proposal",
            result.promotion_proposal_path,
            "--project-root",
            str(tmp_path),
            "--activated-by",
            "cli",
            "--json",
        ]
    ) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "active"
    assert output["activated_by"] == "cli"
    assert output["runtime_effect"] == "not_applied"
    assert output["agent_consumption"] == "advisory"
