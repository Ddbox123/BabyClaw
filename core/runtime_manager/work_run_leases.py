"""Resource lease policy for manager-owned work runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .work_run_store import normalize_run_kind


READONLY_CHAT_LEASE = "readonly_chat"
WORKTREE_WRITE_LEASE = "worktree_write"
MEMORY_WRITE_LEASE = "memory_write"
POLICY_WRITE_LEASE = "policy_write"
EVALUATION_LEASE = "evaluation"
EVOLUTION_TRANSACTION_LEASE = "evolution_transaction"

LOCKING_STATUSES = {"queued", "running", "stopping", "paused"}
WRITE_LEASES = {
    WORKTREE_WRITE_LEASE,
    MEMORY_WRITE_LEASE,
    POLICY_WRITE_LEASE,
    EVOLUTION_TRANSACTION_LEASE,
}
EXCLUSIVE_LEASES = WRITE_LEASES | {EVALUATION_LEASE}
LEASE_CONFLICTS = {
    READONLY_CHAT_LEASE: set(),
    WORKTREE_WRITE_LEASE: {WORKTREE_WRITE_LEASE, POLICY_WRITE_LEASE, EVALUATION_LEASE, EVOLUTION_TRANSACTION_LEASE},
    MEMORY_WRITE_LEASE: {MEMORY_WRITE_LEASE, EVOLUTION_TRANSACTION_LEASE},
    POLICY_WRITE_LEASE: {WORKTREE_WRITE_LEASE, POLICY_WRITE_LEASE, EVALUATION_LEASE, EVOLUTION_TRANSACTION_LEASE},
    EVALUATION_LEASE: {WORKTREE_WRITE_LEASE, POLICY_WRITE_LEASE, EVALUATION_LEASE, EVOLUTION_TRANSACTION_LEASE},
    EVOLUTION_TRANSACTION_LEASE: set(EXCLUSIVE_LEASES),
}


@dataclass(frozen=True)
class WorkRunLeaseRequest:
    run_kind: str
    leases: list[str] = field(default_factory=list)
    run_id: str = ""

    def normalized_kind(self) -> str:
        return normalize_run_kind(self.run_kind)

    def normalized_leases(self) -> list[str]:
        return normalize_leases(self.leases)


@dataclass(frozen=True)
class WorkRunLeaseDecision:
    allowed: bool
    reason: str = ""
    conflicts: list[dict[str, Any]] = field(default_factory=list)


def normalize_lease(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def normalize_leases(values: Iterable[Any] | None) -> list[str]:
    seen: set[str] = set()
    leases: list[str] = []
    for value in list(values or []):
        lease = normalize_lease(value)
        if not lease or lease in seen:
            continue
        seen.add(lease)
        leases.append(lease)
    return leases


def normalize_status(value: Any) -> str:
    return str(value or "").strip().lower()


def active_run_is_locking(run: dict[str, Any]) -> bool:
    return normalize_status(run.get("status")) in LOCKING_STATUSES


def leases_conflict(requested: Iterable[Any], active: Iterable[Any]) -> list[str]:
    requested_leases = normalize_leases(requested)
    active_leases = set(normalize_leases(active))
    conflicts: set[str] = set()
    for requested_lease in requested_leases:
        blocked_by = LEASE_CONFLICTS.get(requested_lease)
        if not blocked_by:
            continue
        if active_leases.intersection(blocked_by):
            conflicts.add(requested_lease)
    return sorted(conflicts)


def check_lease_conflicts(
    request: WorkRunLeaseRequest,
    active_runs: Iterable[dict[str, Any]] | None,
) -> WorkRunLeaseDecision:
    requested_leases = request.normalized_leases()
    conflicts: list[dict[str, Any]] = []
    for run in list(active_runs or []):
        if not isinstance(run, dict) or not active_run_is_locking(run):
            continue
        conflict_leases = leases_conflict(requested_leases, leases_for_snapshot(run))
        if not conflict_leases:
            continue
        conflicts.append(
            {
                "runId": str(run.get("runId") or ""),
                "runKind": str(run.get("runKind") or ""),
                "status": normalize_status(run.get("status")),
                "leases": conflict_leases,
            }
        )

    if not conflicts:
        return WorkRunLeaseDecision(allowed=True)

    first = conflicts[0]
    leases = ", ".join(first["leases"])
    run_id = first.get("runId") or "active run"
    return WorkRunLeaseDecision(
        allowed=False,
        reason=f"Resource lease conflict on {leases} with {run_id}.",
        conflicts=conflicts,
    )


def default_leases_for_run_kind(run_kind: str) -> list[str]:
    kind = normalize_run_kind(run_kind)
    if kind == "chat_turn":
        return [READONLY_CHAT_LEASE]
    if kind == "supervised_evolution_run":
        return [EVALUATION_LEASE]
    if kind == "self_evolution_run":
        return [EVOLUTION_TRANSACTION_LEASE, WORKTREE_WRITE_LEASE, MEMORY_WRITE_LEASE]
    if kind == "proposal_action":
        return [POLICY_WRITE_LEASE]
    return []


def run_kind_from_snapshot(snapshot: dict[str, Any]) -> str:
    for key in ("runKind", "kind"):
        value = str(snapshot.get(key) or "").strip()
        if value:
            if value == "self":
                return "self_evolution_run"
            if value == "supervised":
                return "supervised_evolution_run"
            try:
                return normalize_run_kind(value)
            except ValueError:
                pass

    control = snapshot.get("runtimeManagerControl")
    if isinstance(control, dict):
        value = str(control.get("kind") or "").strip()
        if value == "self":
            return "self_evolution_run"
        if value == "supervised":
            return "supervised_evolution_run"

    run_id = str(snapshot.get("runId") or "").strip()
    if run_id.startswith("web-self-"):
        return "self_evolution_run"
    if run_id.startswith("web-supervised-"):
        return "supervised_evolution_run"
    if run_id.startswith("chat-turn-"):
        return "chat_turn"
    return ""


def leases_for_snapshot(snapshot: dict[str, Any]) -> list[str]:
    leases = normalize_leases(snapshot.get("leases") or snapshot.get("resourceLeases") or [])
    if leases:
        return leases
    run_kind = run_kind_from_snapshot(snapshot)
    if not run_kind:
        return []
    return default_leases_for_run_kind(run_kind)


def infer_chat_turn_leases(payload: dict[str, Any] | None) -> list[str]:
    data = payload if isinstance(payload, dict) else {}
    if bool(data.get("writeIntent")):
        return [WORKTREE_WRITE_LEASE, MEMORY_WRITE_LEASE]

    mode = str(data.get("mode") or data.get("turnMode") or data.get("intent") or "").strip().lower()
    if mode in {"coding", "code", "edit", "write", "worktree_write"}:
        return [WORKTREE_WRITE_LEASE, MEMORY_WRITE_LEASE]

    tool_mode = str(data.get("toolMode") or data.get("tool_calling_mode") or "").strip().lower()
    if tool_mode in {"write", "edit", "agent"}:
        return [WORKTREE_WRITE_LEASE, MEMORY_WRITE_LEASE]

    active_task = data.get("activeTask") if isinstance(data.get("activeTask"), dict) else {}
    active_task_status = str(active_task.get("status") or "").strip().lower()
    changed_files = active_task.get("changed_files") or active_task.get("changedFiles") or []
    if active_task_status in {"editing", "verifying", "blocked", "stopped"} or list(changed_files or []):
        return [WORKTREE_WRITE_LEASE, MEMORY_WRITE_LEASE]

    content = str(data.get("content") or "").strip().lower()
    compact_content = "".join(content.split())
    write_markers = (
        "修改",
        "修复",
        "实现",
        "新增",
        "删除",
        "重构",
        "提交",
        "继续修",
        "继续做",
        "动手",
        "apply",
        "edit",
        "modify",
        "fix",
        "implement",
        "refactor",
        "commit",
    )
    if any(marker in compact_content for marker in write_markers):
        return [WORKTREE_WRITE_LEASE, MEMORY_WRITE_LEASE]

    return [READONLY_CHAT_LEASE]
