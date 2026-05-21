"""Read-only Git status payloads for the web workbench."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from core.infrastructure.git_memory import WorkingTreeSnapshot, get_git_memory_service
from core.web.services.file_service import LANGUAGE_BY_SUFFIX


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_STATUS_LIMIT = 80
MAX_STATUS_LIMIT = 500
DEFAULT_COMMIT_LIMIT = 20
MAX_COMMIT_LIMIT = 60
MAX_DIFF_CHARS = 180_000


def get_git_status(limit: int | None = DEFAULT_STATUS_LIMIT) -> dict[str, Any]:
    """Return a compact, read-only view of the current repository state."""

    service = get_git_memory_service()
    snapshot = service.scan_working_tree(store=False)
    head_rev = service._git_head_rev() if snapshot.available else None
    branch = _current_branch(service) if snapshot.available else ""
    files = [_file_payload(_object_payload(item)) for item in snapshot.files]
    counts = _status_counts(files)
    dirty = bool(files)
    visible_files = _limit_files(files, limit)

    return {
        "available": bool(snapshot.available),
        "error": snapshot.error or "",
        "branch": branch,
        "headRev": head_rev or snapshot.base_rev or "",
        "headRevShort": _short_rev(head_rev or snapshot.base_rev),
        "upstream": _upstream_payload(service, branch) if snapshot.available else _empty_upstream(),
        "snapshotId": snapshot.snapshot_id,
        "createdAt": snapshot.created_at,
        "dirty": dirty,
        "summary": _summary(snapshot, counts),
        "counts": counts,
        "files": visible_files,
        "totalFiles": len(files),
        "truncated": len(visible_files) < len(files),
    }


def get_git_commits(limit: int = DEFAULT_COMMIT_LIMIT) -> dict[str, Any]:
    service = get_git_memory_service()
    available, error = service.is_git_available()
    if not available:
        return {"available": False, "error": error or "git unavailable", "commits": []}

    safe_limit = max(1, min(int(limit or DEFAULT_COMMIT_LIMIT), MAX_COMMIT_LIMIT))
    result = _safe_run_git(
        service,
        [
            "log",
            f"--max-count={safe_limit}",
            "--date=iso-strict",
            "--pretty=format:%H%x1f%h%x1f%aN%x1f%aI%x1f%s",
        ],
    )
    if result is None or result.returncode != 0:
        return {
            "available": False,
            "error": _git_error(result) or "git log failed",
            "commits": [],
        }

    commits: list[dict[str, Any]] = []
    for raw in result.stdout.splitlines():
        parts = raw.split("\x1f", 4)
        if len(parts) < 5:
            continue
        commits.append(
            {
                "sha": parts[0],
                "shortSha": parts[1],
                "author": parts[2],
                "authoredAt": parts[3],
                "subject": parts[4],
            }
        )
    return {"available": True, "error": "", "commits": commits}


def get_git_file_diff(path: str) -> dict[str, Any]:
    service = get_git_memory_service()
    normalized_path = _normalize_git_path(path)
    available, error = service.is_git_available()
    if not available:
        return {
            "available": False,
            "error": error or "git unavailable",
            "path": normalized_path,
            "status": "",
            "statusLabel": "",
            "summary": "Git unavailable",
            "diff": "",
            "content": "",
            "language": _language_for_path(normalized_path),
            "truncated": False,
            "binary": False,
        }

    status_file = _find_status_file(service, normalized_path)
    staged = _git_stdout(service, ["diff", "--cached", "--no-ext-diff", "--no-color", "--", normalized_path])
    unstaged = _git_stdout(service, ["diff", "--no-ext-diff", "--no-color", "--", normalized_path])
    chunks = []
    if staged:
        chunks.append(f"# staged\n{staged}".rstrip())
    if unstaged:
        chunks.append(f"# unstaged\n{unstaged}".rstrip())
    diff = "\n\n".join(chunks).strip()

    content = ""
    binary = False
    if not diff and status_file and status_file.get("untracked"):
        content, binary = _read_untracked_content(normalized_path)

    display = diff or content
    truncated = len(display) > MAX_DIFF_CHARS
    if truncated:
        display = display[:MAX_DIFF_CHARS] + "\n\n... git preview truncated ..."
    if diff:
        diff = display
    else:
        content = display

    status = str(status_file.get("status") if status_file else "").strip()
    return {
        "available": True,
        "error": "",
        "path": normalized_path,
        "status": status,
        "statusLabel": str(status_file.get("statusLabel") if status_file else ""),
        "summary": _diff_summary(status_file, bool(diff), bool(content), binary),
        "diff": diff,
        "content": content,
        "language": "diff" if diff else _language_for_path(normalized_path),
        "truncated": truncated,
        "binary": binary,
    }


def _current_branch(service: Any) -> str:
    result = _safe_run_git(service, ["branch", "--show-current"])
    if result is not None and result.returncode == 0:
        branch = result.stdout.strip()
        if branch:
            return branch
    result = _safe_run_git(service, ["rev-parse", "--short", "HEAD"])
    if result is not None and result.returncode == 0:
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


def _limit_files(files: list[dict[str, Any]], limit: int | None) -> list[dict[str, Any]]:
    if limit is None:
        return files[:MAX_STATUS_LIMIT]
    safe_limit = max(0, min(int(limit), MAX_STATUS_LIMIT))
    return files[:safe_limit]


def _empty_upstream() -> dict[str, Any]:
    return {
        "name": "",
        "remote": "",
        "ahead": 0,
        "behind": 0,
        "hasUpstream": False,
    }


def _upstream_payload(service: Any, branch: str) -> dict[str, Any]:
    payload = _empty_upstream()
    upstream_result = _safe_run_git(service, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"])
    if upstream_result is None or upstream_result.returncode != 0:
        remote_result = _safe_run_git(service, ["remote"])
        if remote_result is not None and remote_result.returncode == 0:
            remotes = [line.strip() for line in remote_result.stdout.splitlines() if line.strip()]
            payload["remote"] = remotes[0] if remotes else ""
        return payload

    upstream = upstream_result.stdout.strip()
    payload["name"] = upstream
    payload["hasUpstream"] = bool(upstream)
    if "/" in upstream:
        payload["remote"] = upstream.split("/", 1)[0]
    elif branch:
        remote_result = _safe_run_git(service, ["config", "--get", f"branch.{branch}.remote"])
        if remote_result is not None and remote_result.returncode == 0:
            payload["remote"] = remote_result.stdout.strip()

    counts_result = _safe_run_git(service, ["rev-list", "--left-right", "--count", f"{upstream}...HEAD"])
    if counts_result is not None and counts_result.returncode == 0:
        parts = counts_result.stdout.strip().split()
        if len(parts) >= 2:
            payload["behind"] = _safe_int(parts[0])
            payload["ahead"] = _safe_int(parts[1])
    return payload


def _safe_int(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _safe_run_git(service: Any, args: list[str]) -> Any | None:
    try:
        return service._run_git(args)
    except Exception:
        return None


def _git_error(result: Any | None) -> str:
    if result is None:
        return ""
    return str(getattr(result, "stderr", "") or getattr(result, "stdout", "") or "").strip()


def _git_stdout(service: Any, args: list[str]) -> str:
    result = _safe_run_git(service, args)
    if result is None or result.returncode != 0:
        return ""
    return result.stdout.strip()


def _find_status_file(service: Any, path: str) -> dict[str, Any] | None:
    snapshot = service.scan_working_tree(store=False)
    for item in snapshot.files:
        payload = _file_payload(_object_payload(item))
        if payload["path"] == path or payload["oldPath"] == path:
            return payload
    return None


def _normalize_git_path(path: str) -> str:
    raw = str(path or "").replace("\\", "/").strip()
    while raw.startswith("./"):
        raw = raw[2:]
    candidate = PurePosixPath(raw)
    if not raw or candidate.is_absolute() or any(part == ".." for part in candidate.parts):
        raise ValueError("Path must stay inside the project root")
    resolved = (PROJECT_ROOT / raw).resolve()
    try:
        resolved.relative_to(PROJECT_ROOT.resolve())
    except ValueError as exc:
        raise ValueError("Path must stay inside the project root") from exc
    return candidate.as_posix()


def _language_for_path(path: str) -> str:
    return LANGUAGE_BY_SUFFIX.get(Path(path).suffix.lower(), "text")


def _read_untracked_content(path: str) -> tuple[str, bool]:
    file_path = (PROJECT_ROOT / path).resolve()
    if not file_path.exists() or not file_path.is_file():
        return "", False
    raw = file_path.read_bytes()
    if b"\x00" in raw[:8192]:
        return "", True
    return raw.decode("utf-8", errors="replace"), False


def _diff_summary(status_file: dict[str, Any] | None, has_diff: bool, has_content: bool, binary: bool) -> str:
    if binary:
        return "Binary file; textual preview is unavailable."
    if has_diff:
        return "Showing read-only Git diff."
    if has_content:
        return "Untracked file; showing current content."
    if status_file:
        return "Git reported this file as changed, but no textual diff is available."
    return "This file is not currently listed as changed."


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
