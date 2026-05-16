# -*- coding: utf-8 -*-
"""Runnable Gym session entry points."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from core.infrastructure.workspace_manager import get_workspace

from .collections import GymCollectionRegistry, build_builtin_collection_registry
from .engine import AgentHarnessAdapter, EvolutionEngine
from .episodes import trace_index_path_for_decision
from .models import ImprovementEpisode, utcnow_iso
from .promotion import (
    activate_gym_promotion_proposal,
    apply_gym_promotion_proposal,
    rollback_gym_promotion_proposal,
)
from .vibelution_adapter import VibelutionAgentHarnessAdapter


DEFAULT_COLLECTION_ID = "foundation_local_stability"
PROMOTION_GATE_COLLECTION_ID = "mixed_readiness_gate"


@dataclass
class GymRunResult:
    collection_id: str
    episode_id: str
    decision: str
    reason: str
    decision_path: str
    trace_index_path: str
    promotion_proposal_path: Optional[str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def run_gym_collection_episode(
    *,
    collection_id: str = DEFAULT_COLLECTION_ID,
    project_root: Optional[Path] = None,
    adapter: Optional[AgentHarnessAdapter] = None,
    registry: Optional[GymCollectionRegistry] = None,
    episode_id: Optional[str] = None,
    keep_worktree: bool = False,
    post_restart_observe_seconds: int = 20,
) -> GymRunResult:
    root = (project_root or get_workspace().project_root).resolve()
    active_registry = registry or build_builtin_collection_registry()
    collection = active_registry.get_collection(collection_id)
    exercise = active_registry.materialize_exercise(collection_id)
    cases = active_registry.materialize_cases(collection_id)
    if not cases:
        raise ValueError(f"Gym collection {collection_id!r} has no materialized cases")
    if exercise.training_tier != collection.training_tier:
        raise ValueError(
            f"Exercise {exercise.exercise_id} tier {exercise.training_tier!r} does not match collection {collection_id!r}"
        )

    active_adapter = adapter or VibelutionAgentHarnessAdapter(
        project_root=root,
        keep_worktree=keep_worktree,
        post_restart_observe_seconds=post_restart_observe_seconds,
    )
    engine = EvolutionEngine(active_adapter)
    episode = engine.run_proposal_only_episode(
        episode_id=episode_id or _episode_id(collection_id),
        exercise=exercise,
        cases=cases,
    )
    decision_path = engine.record_episode(episode, project_root=root)
    return _to_run_result(collection_id=collection_id, episode=episode, decision_path=decision_path)


def run_promotion_gate_episode(
    *,
    project_root: Optional[Path] = None,
    adapter: Optional[AgentHarnessAdapter] = None,
    registry: Optional[GymCollectionRegistry] = None,
    episode_id: Optional[str] = None,
    keep_worktree: bool = False,
    post_restart_observe_seconds: int = 20,
) -> GymRunResult:
    """Run the embeddable mixed-tier promotion gate for any Agent adapter."""

    return run_gym_collection_episode(
        collection_id=PROMOTION_GATE_COLLECTION_ID,
        project_root=project_root,
        adapter=adapter,
        registry=registry,
        episode_id=episode_id,
        keep_worktree=keep_worktree,
        post_restart_observe_seconds=post_restart_observe_seconds,
    )


def format_gym_run_result(result: GymRunResult) -> str:
    return "\n".join(
        [
            f"collection: {result.collection_id}",
            f"episode: {result.episode_id}",
            f"decision: {result.decision}",
            f"reason: {result.reason}",
            f"record: {result.decision_path}",
            f"traces: {result.trace_index_path}",
            f"proposal: {result.promotion_proposal_path or '-'}",
        ]
    )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run Gym proposal-only episodes")
    parser.add_argument("--collection", default=DEFAULT_COLLECTION_ID)
    parser.add_argument("--project-root", default=None)
    parser.add_argument("--keep-worktree", action="store_true")
    parser.add_argument("--post-restart-observe-seconds", type=int, default=20)
    parser.add_argument("--episode-id", default=None)
    parser.add_argument("--list", action="store_true", help="List built-in Gym collections")
    parser.add_argument("--apply-proposal", default=None, help="Explicitly apply a Gym promotion proposal")
    parser.add_argument("--approved-by", default="manual", help="Operator label recorded for --apply-proposal")
    parser.add_argument("--apply-mode", default="record_only", help="Application mode recorded for --apply-proposal")
    parser.add_argument("--rollback-proposal", default=None, help="Explicitly roll back an applied Gym promotion proposal")
    parser.add_argument("--rolled-back-by", default="manual", help="Operator label recorded for --rollback-proposal")
    parser.add_argument("--rollback-reason", default="", help="Reason recorded for --rollback-proposal")
    parser.add_argument("--activate-proposal", default=None, help="Explicitly activate an applied Gym promotion proposal")
    parser.add_argument("--activated-by", default="manual", help="Operator label recorded for --activate-proposal")
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    args = parser.parse_args(argv)
    project_root = Path(args.project_root).resolve() if args.project_root else None

    if args.list:
        payload = [item.to_dict() for item in build_builtin_collection_registry().list_collections()]
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            for item in payload:
                print(f"{item['collection_id']}\t{item['training_tier']}\t{item['name']}")
        return 0

    if args.apply_proposal:
        application = apply_gym_promotion_proposal(
            args.apply_proposal,
            project_root=project_root,
            approved_by=args.approved_by,
            apply_mode=args.apply_mode,
        )
        if args.json:
            print(json.dumps(application.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(format_gym_promotion_application(application))
        return 0

    if args.rollback_proposal:
        rollback = rollback_gym_promotion_proposal(
            args.rollback_proposal,
            project_root=project_root,
            rolled_back_by=args.rolled_back_by,
            reason=args.rollback_reason,
        )
        if args.json:
            print(json.dumps(rollback.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(format_gym_promotion_rollback(rollback))
        return 0

    if args.activate_proposal:
        activation = activate_gym_promotion_proposal(
            args.activate_proposal,
            project_root=project_root,
            activated_by=args.activated_by,
        )
        if args.json:
            print(json.dumps(activation.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(format_gym_promotion_activation(activation))
        return 0

    result = run_gym_collection_episode(
        collection_id=args.collection,
        project_root=project_root,
        episode_id=args.episode_id,
        keep_worktree=args.keep_worktree,
        post_restart_observe_seconds=args.post_restart_observe_seconds,
    )
    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(format_gym_run_result(result))
    return 0


def format_gym_promotion_application(application) -> str:
    return "\n".join(
        [
            f"proposal: {application.proposal_id}",
            f"episode: {application.episode_id}",
            f"status: {application.status}",
            f"mode: {application.apply_mode}",
            f"approved_by: {application.approved_by}",
            f"decision: {application.decision_path}",
            f"traces: {application.trace_index_path}",
            f"ledger: {application.ledger_path}",
        ]
    )


def format_gym_promotion_rollback(rollback) -> str:
    return "\n".join(
        [
            f"proposal: {rollback.proposal_id}",
            f"episode: {rollback.episode_id}",
            f"status: {rollback.status}",
            f"rolled_back_by: {rollback.rolled_back_by}",
            f"reason: {rollback.reason}",
            f"decision: {rollback.decision_path}",
            f"traces: {rollback.trace_index_path}",
            f"ledger: {rollback.ledger_path}",
        ]
    )


def format_gym_promotion_activation(activation) -> str:
    return "\n".join(
        [
            f"proposal: {activation.proposal_id}",
            f"episode: {activation.episode_id}",
            f"status: {activation.status}",
            f"target: {activation.target_key}",
            f"activated_by: {activation.activated_by}",
            f"runtime_effect: {activation.runtime_effect}",
            f"agent_consumption: {activation.agent_consumption}",
            f"previous_active: {activation.previous_active_proposal_id or '-'}",
            f"decision: {activation.decision_path}",
            f"traces: {activation.trace_index_path}",
            f"registry: {activation.registry_path}",
            f"history: {activation.history_path}",
        ]
    )


def _to_run_result(*, collection_id: str, episode: ImprovementEpisode, decision_path: Path) -> GymRunResult:
    proposal_path = None
    if episode.promotion_proposal:
        proposal_path = episode.promotion_proposal.proposal_path
    return GymRunResult(
        collection_id=collection_id,
        episode_id=episode.episode_id,
        decision=episode.decision,
        reason=episode.reason,
        decision_path=str(decision_path),
        trace_index_path=str(trace_index_path_for_decision(decision_path)),
        promotion_proposal_path=proposal_path,
    )


def _episode_id(collection_id: str) -> str:
    stamp = utcnow_iso().replace(":", "").replace("-", "").replace(".", "").replace("+", "_")
    return f"gym_{collection_id}_{stamp}"
