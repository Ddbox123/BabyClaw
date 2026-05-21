"""Read-only Git status payloads for the web workbench."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from core.infrastructure.git_memory import WorkingTreeSnapshot, get_git_memory_service


def get_git_status() -> dict[str, Any]:
    """Return a compact, read-only view of the current repository state."""

    service = get_git_memory_service()
    snapshot = service.scan_working_tree(store=False)
    head_rev = service._git_head_rev() if snapshot.available else None
    branch = _current_branch(service) if snapshot.available else ""
    files = [_file_payload(_object_payload(item)) for item in snapshot.files]
    counts = _status_counts(files)
    dirty = bool(files)

    return {
        "available": bool(snapshot.available),
        "error": snapshot.error or "",
        "branch": branch,
        "headRev": head_rev or snapshot.base_rev or "",
        "headRevShort": _short_rev(head_rev or snapshot.base_rev),
        "snapshotId": snapshot.snapshot_id,
        "createdAt": snapshot.created_at,
        "dirty": dirty,
        "summary": _summary(snapshot, counts),
        "counts": counts,
        "files": files[:80],
        "truncated": len(files) > 80,
    }


def _current_branch(service: Any) -> str:
    result = service._run_git(["branch", "--show-current"])
    if result.returncode == 0:
        branch = result.stdout.strip()
        if branch:
            return branch
    result = service._run_git(["rev-parse", "--short", "HEAD"])
    if result.returncode == 0:
        head = result.stdout.strip()
        if head:
            return f"detached@{head}"
    return ""


def _short_rev(value: str | None) -> str:
    text = str(value or "").strip()
    return text[:12] if text else ""


def _object_payload(value: Any) -> dict[str, Any]:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return value
    return dict(vars(value))


def _file_payload(item: dict[str, Any]) -> dict[str, Any]:
    status = str(item.get("status") or "").strip() or "??"
    return {
        "path": str(item.get("path") or ""),
        "status": status,
        "statusLabel": _status_label(status),
        "staged": bool(item.get("staged")),
        "unstaged": bool(item.get("unstaged")),
        "untracked": bool(item.get("untracked")),
        "deleted": bool(item.get("deleted")),
        "oldPath": str(item.get("old_path") or ""),
    }


def _status_label(status: str) -> str:
    if status == "??":
        return "untracked"
    labels: list[str] = []
    x = status[0] if len(status) >= 1 else " "
    y = status[1] if len(status) >= 2 else " "
    if x != " ":
        labels.append(_code_label(x))
    if y != " ":
        unstaged = _code_label(y)
        if unstaged not in labels:
            labels.append(unstaged)
    return ", ".join(labels) or "clean"


def _code_label(value: str) -> str:
    return {
        "A": "added",
        "M": "modified",
        "D": "deleted",
        "R": "renamed",
        "C": "copied",
        "T": "type changed",
        "U": "unmerged",
    }.get(value, value)


def _status_counts(files: list[dict[str, Any]]) -> dict[str, int]:
    counts = {
        "total": len(files),
        "staged": 0,
        "unstaged": 0,
        "untracked": 0,
        "deleted": 0,
    }
    for item in files:
        if item["staged"]:
            counts["staged"] += 1
        if item["unstaged"]:
            counts["unstaged"] += 1
        if item["untracked"]:
            counts["untracked"] += 1
        if item["deleted"]:
            counts["deleted"] += 1
    return counts


def _summary(snapshot: WorkingTreeSnapshot, counts: dict[str, int]) -> str:
    if not snapshot.available:
        return f"Git unavailable: {snapshot.error or 'unknown'}"
    if counts["total"] == 0:
        return "工作区干净"
    parts: list[str] = []
    if counts["staged"]:
        parts.append(f"staged {counts['staged']}")
    if counts["unstaged"]:
        parts.append(f"unstaged {counts['unstaged']}")
    if counts["untracked"]:
        parts.append(f"untracked {counts['untracked']}")
    if counts["deleted"]:
        parts.append(f"deleted {counts['deleted']}")
    detail = " / ".join(parts) if parts else "changed"
    return f"{counts['total']} 个变化文件，{detail}"
