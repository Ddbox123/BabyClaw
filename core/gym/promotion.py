# -*- coding: utf-8 -*-
"""Explicit application step for Gym promotion proposals."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from core.infrastructure.workspace_manager import get_workspace

from .episodes import trace_index_path_for_decision
from .models import utcnow_iso


@dataclass
class GymPromotionApplication:
    proposal_id: str
    episode_id: str
    candidate_improvement_id: str
    status: str
    apply_mode: str
    approved_by: str
    applied_at: str
    proposal_path: str
    decision_path: str
    trace_index_path: str
    ledger_path: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class GymPromotionRollback:
    proposal_id: str
    episode_id: str
    candidate_improvement_id: str
    status: str
    rolled_back_by: str
    rolled_back_at: str
    reason: str
    proposal_path: str
    decision_path: str
    trace_index_path: str
    ledger_path: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class GymPromotionActivation:
    proposal_id: str
    episode_id: str
    candidate_improvement_id: str
    target_key: str
    status: str
    activated_by: str
    activated_at: str
    runtime_effect: str
    agent_consumption: str
    previous_active_proposal_id: Optional[str]
    proposal_path: str
    decision_path: str
    trace_index_path: str
    registry_path: str
    history_path: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def apply_gym_promotion_proposal(
    proposal_path: str | Path,
    *,
    project_root: Optional[Path] = None,
    approved_by: str = "manual",
    apply_mode: str = "record_only",
) -> GymPromotionApplication:
    """Mark a Gym promotion proposal as explicitly applied.

    This is the first post-proposal step in the larger loop. It verifies that
    the proposal, decision record, and trace index are present before changing
    proposal state. It intentionally records application only; baseline rewrite
    remains a separate, later behavior.
    """

    root = (project_root or get_workspace().project_root).resolve()
    active_proposal_path = Path(proposal_path).resolve()
    proposal = _load_json_object(active_proposal_path, label="promotion proposal")

    status = str(proposal.get("status") or "").strip()
    if status == "applied":
        return _application_from_applied_proposal(active_proposal_path, proposal, root)
    if status != "proposed":
        raise ValueError(f"Gym promotion proposal must be proposed before apply; got {status or 'missing'}")

    episode_id = _required_text(proposal, "episode_id")
    candidate_improvement_id = _required_text(proposal, "candidate_improvement_id")
    proposal_id = _required_text(proposal, "proposal_id")

    decision_path = root / "workspace" / "gym" / "decisions" / f"{episode_id}.json"
    decision = _load_json_object(decision_path, label="Gym decision")
    if str(decision.get("decision") or "").upper() != "PROMOTE":
        raise ValueError("Gym promotion proposal can only be applied for PROMOTE decisions")
    recorded = decision.get("candidate_improvement") or {}
    if str(recorded.get("improvement_id") or "") != candidate_improvement_id:
        raise ValueError("Gym promotion proposal does not match decision candidate improvement")

    trace_index_path = trace_index_path_for_decision(decision_path)
    _validate_trace_index(trace_index_path)

    applied_at = utcnow_iso()
    ledger_path = root / "workspace" / "gym" / "applied_promotions.jsonl"
    application = GymPromotionApplication(
        proposal_id=proposal_id,
        episode_id=episode_id,
        candidate_improvement_id=candidate_improvement_id,
        status="applied",
        apply_mode=apply_mode,
        approved_by=approved_by,
        applied_at=applied_at,
        proposal_path=str(active_proposal_path),
        decision_path=str(decision_path),
        trace_index_path=str(trace_index_path),
        ledger_path=str(ledger_path),
    )

    proposal.update(
        {
            "status": "applied",
            "apply_mode": apply_mode,
            "applied_by": approved_by,
            "applied_at": applied_at,
            "decision_path": str(decision_path),
            "trace_index_path": str(trace_index_path),
            "ledger_path": str(ledger_path),
        }
    )
    active_proposal_path.write_text(json.dumps(proposal, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _append_ledger_once(ledger_path, application)
    return application


def rollback_gym_promotion_proposal(
    proposal_path: str | Path,
    *,
    project_root: Optional[Path] = None,
    rolled_back_by: str = "manual",
    reason: str = "",
) -> GymPromotionRollback:
    """Mark an applied Gym promotion proposal as rolled back.

    Rollback is record-only for now. It proves that every applied proposal has
    an explicit reversal path before later work starts mutating baseline
    behavior.
    """

    root = (project_root or get_workspace().project_root).resolve()
    active_proposal_path = Path(proposal_path).resolve()
    proposal = _load_json_object(active_proposal_path, label="promotion proposal")

    status = str(proposal.get("status") or "").strip()
    if status == "rolled_back":
        return _rollback_from_rolled_back_proposal(active_proposal_path, proposal, root)
    if status != "applied":
        raise ValueError(f"Gym promotion proposal must be applied before rollback; got {status or 'missing'}")

    episode_id = _required_text(proposal, "episode_id")
    decision_path = Path(
        str(proposal.get("decision_path") or root / "workspace" / "gym" / "decisions" / f"{episode_id}.json")
    ).resolve()
    trace_index_path = Path(str(proposal.get("trace_index_path") or trace_index_path_for_decision(decision_path))).resolve()
    _load_json_object(decision_path, label="Gym decision")
    _validate_trace_index(trace_index_path)

    rolled_back_at = utcnow_iso()
    ledger_path = root / "workspace" / "gym" / "rolled_back_promotions.jsonl"
    rollback = GymPromotionRollback(
        proposal_id=_required_text(proposal, "proposal_id"),
        episode_id=episode_id,
        candidate_improvement_id=_required_text(proposal, "candidate_improvement_id"),
        status="rolled_back",
        rolled_back_by=rolled_back_by,
        rolled_back_at=rolled_back_at,
        reason=reason,
        proposal_path=str(active_proposal_path),
        decision_path=str(decision_path),
        trace_index_path=str(trace_index_path),
        ledger_path=str(ledger_path),
    )

    proposal.update(
        {
            "status": "rolled_back",
            "rolled_back_by": rolled_back_by,
            "rolled_back_at": rolled_back_at,
            "rollback_reason": reason,
            "rollback_ledger_path": str(ledger_path),
        }
    )
    active_proposal_path.write_text(json.dumps(proposal, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _append_ledger_once(ledger_path, rollback)
    return rollback


def activate_gym_promotion_proposal(
    proposal_path: str | Path,
    *,
    project_root: Optional[Path] = None,
    activated_by: str = "manual",
) -> GymPromotionActivation:
    """Mark an applied Gym promotion proposal as the active advisory baseline candidate."""

    root = (project_root or get_workspace().project_root).resolve()
    active_proposal_path = Path(proposal_path).resolve()
    proposal = _load_json_object(active_proposal_path, label="promotion proposal")

    status = str(proposal.get("status") or "").strip()
    if status == "active":
        return _activation_from_active_proposal(active_proposal_path, proposal, root)
    if status != "applied":
        raise ValueError(f"Gym promotion proposal must be applied before activation; got {status or 'missing'}")

    episode_id = _required_text(proposal, "episode_id")
    candidate_improvement_id = _required_text(proposal, "candidate_improvement_id")
    proposal_id = _required_text(proposal, "proposal_id")
    decision_path = Path(
        str(proposal.get("decision_path") or root / "workspace" / "gym" / "decisions" / f"{episode_id}.json")
    ).resolve()
    decision = _load_json_object(decision_path, label="Gym decision")
    if str(decision.get("decision") or "").upper() != "PROMOTE":
        raise ValueError("Gym promotion proposal can only be activated for PROMOTE decisions")
    recorded = decision.get("candidate_improvement") or {}
    if str(recorded.get("improvement_id") or "") != candidate_improvement_id:
        raise ValueError("Gym promotion proposal does not match decision candidate improvement")

    trace_index_path = Path(str(proposal.get("trace_index_path") or trace_index_path_for_decision(decision_path))).resolve()
    _validate_trace_index(trace_index_path)

    target_key = _target_key(decision, proposal)
    registry_path = root / "workspace" / "gym" / "active_promotions.json"
    history_path = root / "workspace" / "gym" / "activation_history.jsonl"
    registry = _load_registry(registry_path)
    active_entries = registry.setdefault("active", {})
    previous_entry = active_entries.get(target_key) if isinstance(active_entries, dict) else None
    previous_active_proposal_id = None
    if isinstance(previous_entry, dict):
        previous_active_proposal_id = str(previous_entry.get("proposal_id") or "") or None

    activated_at = utcnow_iso()
    activation = GymPromotionActivation(
        proposal_id=proposal_id,
        episode_id=episode_id,
        candidate_improvement_id=candidate_improvement_id,
        target_key=target_key,
        status="active",
        activated_by=activated_by,
        activated_at=activated_at,
        runtime_effect="not_applied",
        agent_consumption="advisory",
        previous_active_proposal_id=previous_active_proposal_id,
        proposal_path=str(active_proposal_path),
        decision_path=str(decision_path),
        trace_index_path=str(trace_index_path),
        registry_path=str(registry_path),
        history_path=str(history_path),
    )

    if previous_active_proposal_id and previous_active_proposal_id != proposal_id:
        _mark_previous_active_superseded(
            previous_entry=previous_entry,
            superseded_by=proposal_id,
            superseded_at=activated_at,
        )

    active_entries[target_key] = {
        "proposal_id": proposal_id,
        "episode_id": episode_id,
        "candidate_improvement_id": candidate_improvement_id,
        "target_key": target_key,
        "status": "active",
        "activated_by": activated_by,
        "activated_at": activated_at,
        "runtime_effect": "not_applied",
        "agent_consumption": "advisory",
        "proposal_path": str(active_proposal_path),
        "decision_path": str(decision_path),
        "trace_index_path": str(trace_index_path),
        "previous_active_proposal_id": previous_active_proposal_id,
    }
    registry["updated_at"] = activated_at
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    proposal.update(
        {
            "status": "active",
            "activated_by": activated_by,
            "activated_at": activated_at,
            "target_key": target_key,
            "runtime_effect": "not_applied",
            "agent_consumption": "advisory",
            "activation_registry_path": str(registry_path),
            "activation_history_path": str(history_path),
            "previous_active_proposal_id": previous_active_proposal_id,
        }
    )
    active_proposal_path.write_text(json.dumps(proposal, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _append_ledger_once(history_path, activation)
    return activation


def _application_from_applied_proposal(
    proposal_path: Path,
    proposal: dict,
    project_root: Path,
) -> GymPromotionApplication:
    episode_id = _required_text(proposal, "episode_id")
    decision_path = Path(str(proposal.get("decision_path") or project_root / "workspace" / "gym" / "decisions" / f"{episode_id}.json")).resolve()
    trace_index_path = Path(str(proposal.get("trace_index_path") or trace_index_path_for_decision(decision_path))).resolve()
    ledger_path = Path(str(proposal.get("ledger_path") or project_root / "workspace" / "gym" / "applied_promotions.jsonl")).resolve()
    return GymPromotionApplication(
        proposal_id=_required_text(proposal, "proposal_id"),
        episode_id=episode_id,
        candidate_improvement_id=_required_text(proposal, "candidate_improvement_id"),
        status="applied",
        apply_mode=str(proposal.get("apply_mode") or "record_only"),
        approved_by=str(proposal.get("applied_by") or "manual"),
        applied_at=str(proposal.get("applied_at") or ""),
        proposal_path=str(proposal_path),
        decision_path=str(decision_path),
        trace_index_path=str(trace_index_path),
        ledger_path=str(ledger_path),
    )


def _activation_from_active_proposal(
    proposal_path: Path,
    proposal: dict,
    project_root: Path,
) -> GymPromotionActivation:
    episode_id = _required_text(proposal, "episode_id")
    decision_path = Path(
        str(proposal.get("decision_path") or project_root / "workspace" / "gym" / "decisions" / f"{episode_id}.json")
    ).resolve()
    trace_index_path = Path(str(proposal.get("trace_index_path") or trace_index_path_for_decision(decision_path))).resolve()
    registry_path = Path(str(proposal.get("activation_registry_path") or project_root / "workspace" / "gym" / "active_promotions.json")).resolve()
    history_path = Path(str(proposal.get("activation_history_path") or project_root / "workspace" / "gym" / "activation_history.jsonl")).resolve()
    return GymPromotionActivation(
        proposal_id=_required_text(proposal, "proposal_id"),
        episode_id=episode_id,
        candidate_improvement_id=_required_text(proposal, "candidate_improvement_id"),
        target_key=str(proposal.get("target_key") or _fallback_target_key(proposal)),
        status="active",
        activated_by=str(proposal.get("activated_by") or "manual"),
        activated_at=str(proposal.get("activated_at") or ""),
        runtime_effect=str(proposal.get("runtime_effect") or "not_applied"),
        agent_consumption=str(proposal.get("agent_consumption") or "advisory"),
        previous_active_proposal_id=proposal.get("previous_active_proposal_id"),
        proposal_path=str(proposal_path),
        decision_path=str(decision_path),
        trace_index_path=str(trace_index_path),
        registry_path=str(registry_path),
        history_path=str(history_path),
    )


def _rollback_from_rolled_back_proposal(
    proposal_path: Path,
    proposal: dict,
    project_root: Path,
) -> GymPromotionRollback:
    episode_id = _required_text(proposal, "episode_id")
    decision_path = Path(
        str(proposal.get("decision_path") or project_root / "workspace" / "gym" / "decisions" / f"{episode_id}.json")
    ).resolve()
    trace_index_path = Path(str(proposal.get("trace_index_path") or trace_index_path_for_decision(decision_path))).resolve()
    ledger_path = Path(str(proposal.get("rollback_ledger_path") or project_root / "workspace" / "gym" / "rolled_back_promotions.jsonl")).resolve()
    return GymPromotionRollback(
        proposal_id=_required_text(proposal, "proposal_id"),
        episode_id=episode_id,
        candidate_improvement_id=_required_text(proposal, "candidate_improvement_id"),
        status="rolled_back",
        rolled_back_by=str(proposal.get("rolled_back_by") or "manual"),
        rolled_back_at=str(proposal.get("rolled_back_at") or ""),
        reason=str(proposal.get("rollback_reason") or ""),
        proposal_path=str(proposal_path),
        decision_path=str(decision_path),
        trace_index_path=str(trace_index_path),
        ledger_path=str(ledger_path),
    )


def _append_ledger_once(path: Path, record: GymPromotionApplication | GymPromotionRollback | GymPromotionActivation) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("proposal_id") == record.proposal_id:
                return
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")


def _validate_trace_index(path: Path) -> None:
    payload = _load_json_object(path, label="Gym trace index")
    traces = payload.get("traces")
    if not isinstance(traces, list) or not traces:
        raise ValueError("Gym trace index must contain traces before apply")
    for item in traces:
        trace_path = Path(str((item or {}).get("path") or "")).resolve()
        if not trace_path.exists():
            raise ValueError(f"Gym trace index references missing trace file: {trace_path}")


def _load_json_object(path: Path, *, label: str) -> dict:
    if not path.exists():
        raise ValueError(f"Missing {label}: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid {label}: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid {label}: expected object at {path}")
    return payload


def _required_text(payload: dict, key: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise ValueError(f"Gym promotion proposal missing {key}")
    return value


def _load_registry(path: Path) -> dict:
    if not path.exists():
        return {"active": {}}
    payload = _load_json_object(path, label="Gym active promotion registry")
    active = payload.get("active")
    if not isinstance(active, dict):
        payload["active"] = {}
    return payload


def _target_key(decision: dict, proposal: dict) -> str:
    candidate = decision.get("candidate_improvement") or {}
    target = candidate.get("target") or {}
    if isinstance(target, dict) and target:
        return "target:" + json.dumps(target, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _fallback_target_key(proposal)


def _fallback_target_key(proposal: dict) -> str:
    return f"episode:{proposal.get('episode_id') or ''}:{proposal.get('candidate_improvement_id') or ''}"


def _mark_previous_active_superseded(
    *,
    previous_entry: object,
    superseded_by: str,
    superseded_at: str,
) -> None:
    if not isinstance(previous_entry, dict):
        return
    previous_path_text = str(previous_entry.get("proposal_path") or "")
    if not previous_path_text:
        return
    previous_path = Path(previous_path_text).resolve()
    if not previous_path.exists():
        return
    previous = _load_json_object(previous_path, label="previous active Gym promotion proposal")
    if str(previous.get("status") or "") != "active":
        return
    previous.update(
        {
            "status": "superseded",
            "superseded_by": superseded_by,
            "superseded_at": superseded_at,
        }
    )
    previous_path.write_text(json.dumps(previous, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


__all__ = [
    "GymPromotionApplication",
    "GymPromotionActivation",
    "GymPromotionRollback",
    "activate_gym_promotion_proposal",
    "apply_gym_promotion_proposal",
    "rollback_gym_promotion_proposal",
]
