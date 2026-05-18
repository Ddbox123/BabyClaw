# -*- coding: utf-8 -*-
"""Agent 自进化 workbench helpers."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config import get_config
from core.gym import build_active_advisory_snapshot, summarize_active_advisory_baselines
from tools.git_tools import (
    explain_current_worktree_tool,
    get_evolution_fitness_tool,
    get_git_status_summary_tool,
    get_recent_changes_tool,
)


DEFAULT_SELF_EVOLUTION_GOAL = "开始自主进化"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class SelfEvolutionTransactionRecord:
    txn_id: str
    opened_at: str
    closed_at: str | None
    base_rev: str | None
    status: str
    summary: str


def build_self_evolution_snapshot(
    goal: str = DEFAULT_SELF_EVOLUTION_GOAL,
    *,
    status_limit: int = 5,
    change_limit: int = 3,
    recent_limit: int = 3,
    transaction_limit: int = 3,
    project_root: Path | None = None,
) -> dict[str, Any]:
    """Collect a structured self-evolution snapshot for web or other read-only surfaces."""

    root = _resolve_project_root(project_root)
    status_summary = _safe_tool_call(
        lambda: get_git_status_summary_tool(limit=status_limit),
        fallback="git 状态暂不可用",
    )
    recent_changes_json = _safe_tool_call(
        lambda: get_recent_changes_tool(limit=change_limit),
        fallback="[]",
    )
    fitness_json = _safe_tool_call(
        lambda: get_evolution_fitness_tool(recent_limit=recent_limit),
        fallback="{}",
    )
    worktree_snapshot_json = _safe_tool_call(
        explain_current_worktree_tool,
        fallback="{}",
    )
    return {
        "goal": goal or DEFAULT_SELF_EVOLUTION_GOAL,
        "advisory": build_active_advisory_snapshot(project_root=root, limit=recent_limit),
        "git_status": {
            "summary": status_summary,
            "lines": _trim_lines(status_summary, fallback="git 状态暂不可用"),
        },
        "recent_changes": _normalize_recent_changes_payload(recent_changes_json),
        "fitness": _normalize_fitness_payload(fitness_json),
        "worktree": _normalize_worktree_snapshot(worktree_snapshot_json),
        "recent_transactions": list_recent_self_evolution_transaction_payloads(
            root,
            limit=transaction_limit,
        ),
    }


def build_self_evolution_preview(
    goal: str = DEFAULT_SELF_EVOLUTION_GOAL,
    *,
    status_limit: int = 5,
    change_limit: int = 3,
    recent_limit: int = 3,
    transaction_limit: int = 3,
    project_root: Path | None = None,
) -> str:
    root = _resolve_project_root(project_root)
    advisory_lines = summarize_active_advisory_baselines(limit=recent_limit)
    status_summary = _safe_tool_call(
        lambda: get_git_status_summary_tool(limit=status_limit),
        fallback="git 状态暂不可用",
    )
    recent_changes_json = _safe_tool_call(
        lambda: get_recent_changes_tool(limit=change_limit),
        fallback="[]",
    )
    fitness_json = _safe_tool_call(
        lambda: get_evolution_fitness_tool(recent_limit=recent_limit),
        fallback="{}",
    )
    worktree_snapshot_json = _safe_tool_call(
        explain_current_worktree_tool,
        fallback="{}",
    )
    transaction_records = list_recent_self_evolution_transactions(root, limit=transaction_limit)
    return format_self_evolution_preview(
        goal=goal,
        advisory_lines=advisory_lines,
        status_summary=status_summary,
        recent_changes_json=recent_changes_json,
        fitness_json=fitness_json,
        worktree_snapshot_json=worktree_snapshot_json,
        recent_transactions=transaction_records,
    )


def build_self_evolution_run_prompt(
    goal: str = DEFAULT_SELF_EVOLUTION_GOAL,
    *,
    recent_limit: int = 3,
    transaction_limit: int = 2,
    project_root: Path | None = None,
) -> str:
    root = _resolve_project_root(project_root)
    advisory_lines = summarize_active_advisory_baselines(limit=recent_limit)
    fitness_json = _safe_tool_call(
        lambda: get_evolution_fitness_tool(recent_limit=recent_limit),
        fallback="{}",
    )
    worktree_snapshot_json = _safe_tool_call(
        explain_current_worktree_tool,
        fallback="{}",
    )
    transaction_records = list_recent_self_evolution_transactions(root, limit=transaction_limit)
    return format_self_evolution_run_prompt(
        goal=goal,
        advisory_lines=advisory_lines,
        fitness_json=fitness_json,
        worktree_snapshot_json=worktree_snapshot_json,
        recent_transactions=transaction_records,
    )


def format_self_evolution_preview(
    *,
    goal: str,
    status_summary: str,
    recent_changes_json: str,
    fitness_json: str,
    advisory_lines: list[str] | None = None,
    worktree_snapshot_json: str = "{}",
    recent_transactions: list[SelfEvolutionTransactionRecord] | None = None,
) -> str:
    lines = [
        f"goal: {goal or DEFAULT_SELF_EVOLUTION_GOAL}",
        "agent view:",
        *_indent_lines(advisory_lines or ["当前未记住 active advisory baseline"]),
        "git status:",
        *_indent_lines(_trim_lines(status_summary, fallback="git 状态暂不可用")),
        "recent changes:",
        *_indent_lines(_format_recent_changes(recent_changes_json)),
        "current worktree:",
        *_indent_lines(_format_preview_worktree(worktree_snapshot_json)),
        "recent transactions:",
        *_indent_lines(_format_preview_transactions(recent_transactions)),
        "fitness:",
        *_indent_lines(_format_fitness(fitness_json)),
    ]
    return "\n".join(lines)


def format_self_evolution_run_prompt(
    *,
    goal: str,
    advisory_lines: list[str] | None = None,
    fitness_json: str,
    worktree_snapshot_json: str = "{}",
    recent_transactions: list[SelfEvolutionTransactionRecord] | None = None,
) -> str:
    lines = [
        goal or DEFAULT_SELF_EVOLUTION_GOAL,
        "",
        "把当前 active advisory baseline 视为观察参照，不代表自动授权，也不要把它当成 runtime rewrite 指令。",
        "优先围绕 runtime stability、evolution efficiency、UI/agent coherence 选择下一步。",
        "如果 advisory baseline 与当前变更没有直接映射，就把它当作一般能力信号，而不是硬性目标。",
        "如果当前工作区已有未提交改动，先把它们视为共享现场，解释风险，再决定是否继续修改。",
        "",
        "当前 advisory baseline:",
        *_indent_lines(advisory_lines or ["当前未记住 active advisory baseline"]),
        "当前工作区快照:",
        *_indent_lines(_format_run_prompt_worktree(worktree_snapshot_json)),
        "最近自进化事务:",
        *_indent_lines(_format_preview_transactions(recent_transactions)),
        "最近 fitness:",
        *_indent_lines(_format_fitness(fitness_json)),
    ]
    return "\n".join(lines)


def build_self_evolution_worktree_snapshot() -> str:
    snapshot_json = _safe_tool_call(
        explain_current_worktree_tool,
        fallback="{}",
    )
    return format_self_evolution_worktree_snapshot(snapshot_json)


def list_recent_self_evolution_transaction_payloads(
    project_root: Path,
    *,
    limit: int = 8,
) -> list[dict[str, Any]]:
    return [
        {
            "txn_id": item.txn_id,
            "opened_at": item.opened_at,
            "closed_at": item.closed_at,
            "base_rev": item.base_rev,
            "base_rev_short": _short_rev(item.base_rev),
            "status": item.status,
            "summary": item.summary,
            "is_open": item.closed_at is None,
        }
        for item in list_recent_self_evolution_transactions(project_root, limit=limit)
    ]


def load_self_evolution_audit_records(project_root: Path, *, limit: int = 10) -> list[dict[str, Any]]:
    audit_path = _audit_log_path(project_root)
    if not audit_path.exists():
        return []

    records: list[dict[str, Any]] = []
    for line in audit_path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        payload = _load_json_value(text, fallback=None)
        if isinstance(payload, dict):
            records.append(payload)
    if not records:
        return []

    tail = records[-max(1, int(limit or 10)) :]
    normalized: list[dict[str, Any]] = []
    for item in tail:
        targets = item.get("target_paths") if isinstance(item.get("target_paths"), list) else []
        normalized.append(
            {
                "timestamp": str(item.get("timestamp") or ""),
                "event": str(item.get("event") or ""),
                "txn_id": str(item.get("txn_id") or ""),
                "status": str(item.get("status") or ""),
                "kind": str(item.get("kind") or ""),
                "message": str(item.get("message") or ""),
                "tool_name": str(item.get("tool_name") or ""),
                "target_paths": [str(path) for path in targets if str(path).strip()],
                "passed": item.get("passed"),
                "base_rev": str(item.get("base_rev") or ""),
                "summary": _summarize_audit_record(item),
            }
        )
    return normalized


def format_self_evolution_worktree_snapshot(snapshot_json: str) -> str:
    payload = _load_json_value(snapshot_json, fallback={})
    if not isinstance(payload, dict) or not payload:
        return "工作区快照暂不可用"
    if not payload.get("available", True):
        return f"Git worktree 不可用: {payload.get('error') or 'unknown'}"

    lines = [
        f"snapshot: {payload.get('snapshot_id') or '-'}",
        f"created_at: {payload.get('created_at') or '-'}",
        f"base_rev: {payload.get('base_rev') or '-'}",
        (
            "dirty flags: "
            f"staged={bool(payload.get('has_staged'))} "
            f"unstaged={bool(payload.get('has_unstaged'))} "
            f"untracked={bool(payload.get('has_untracked'))}"
        ),
    ]
    files = payload.get("files")
    if not isinstance(files, list) or not files:
        lines.append("files:")
        lines.append("  工作区干净")
        return "\n".join(lines)

    lines.append("files:")
    for item in files[:8]:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "-")
        path = str(item.get("path") or "-")
        flags = []
        if item.get("staged"):
            flags.append("staged")
        if item.get("unstaged"):
            flags.append("unstaged")
        if item.get("untracked"):
            flags.append("untracked")
        if item.get("deleted"):
            flags.append("deleted")
        suffix = f" ({', '.join(flags)})" if flags else ""
        lines.append(f"  - {status} {path}{suffix}")
    hidden = len(files) - min(len(files), 8)
    if hidden > 0:
        lines.append(f"  ... 还有 {hidden} 个文件")
    return "\n".join(lines)


def list_recent_self_evolution_transactions(
    project_root: Path,
    *,
    limit: int = 8,
) -> list[SelfEvolutionTransactionRecord]:
    db_path = _workspace_root(project_root) / "agent_brain.db"
    if not db_path.exists():
        return []

    try:
        with sqlite3.connect(str(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT txn_id, opened_at, closed_at, base_rev, status, summary
                FROM EvolutionTransaction
                ORDER BY COALESCE(closed_at, opened_at) DESC, opened_at DESC
                LIMIT ?
                """,
                (max(1, int(limit or 8)),),
            ).fetchall()
    except sqlite3.Error:
        return []

    return [
        SelfEvolutionTransactionRecord(
            txn_id=str(row["txn_id"] or ""),
            opened_at=str(row["opened_at"] or ""),
            closed_at=str(row["closed_at"] or "") or None,
            base_rev=str(row["base_rev"] or "") or None,
            status=str(row["status"] or "unknown"),
            summary=str(row["summary"] or ""),
        )
        for row in rows
    ]


def format_self_evolution_transaction_history(records: list[SelfEvolutionTransactionRecord]) -> str:
    if not records:
        return "暂无自进化事务记录"

    lines = [f"recent transactions: {len(records)}"]
    for item in records:
        summary = item.summary.strip() or "无摘要"
        if len(summary) > 64:
            summary = summary[:61] + "..."
        lines.extend(
            [
                f"- {item.txn_id} status={item.status}",
                f"  opened={item.opened_at}",
                f"  closed={item.closed_at or '-'}",
                f"  base_rev={_short_rev(item.base_rev)} summary={summary}",
            ]
        )
    return "\n".join(lines)


def format_self_evolution_audit_excerpt(project_root: Path, *, limit: int = 10) -> str:
    audit_path = _audit_log_path(project_root)
    records = load_self_evolution_audit_records(project_root, limit=limit)
    if not audit_path.exists():
        return "暂无自进化审计日志"
    if not records:
        return "自进化审计日志为空"

    lines = [f"audit log: {audit_path}"]
    for item in records:
        lines.append(f"- {item.get('summary') or '-'}")
    return "\n".join(lines)


def _safe_tool_call(fn, *, fallback: str) -> str:
    try:
        result = fn()
    except Exception as exc:
        return f"{fallback} ({type(exc).__name__}: {exc})"
    text = str(result or "").strip()
    return text or fallback


def _resolve_project_root(project_root: Path | None) -> Path:
    if project_root is None:
        return PROJECT_ROOT.resolve()
    return Path(project_root).resolve()


def _trim_lines(text: str, *, limit: int = 6, fallback: str) -> list[str]:
    raw_lines = [line.rstrip() for line in str(text or "").splitlines() if line.strip()]
    if not raw_lines:
        return [fallback]
    if len(raw_lines) <= limit:
        return raw_lines
    hidden = len(raw_lines) - limit
    return [*raw_lines[:limit], f"... 还有 {hidden} 行"]


def _indent_lines(lines: list[str]) -> list[str]:
    return [f"  {line}" for line in lines]


def _load_json_value(text: str, *, fallback: Any) -> Any:
    try:
        return json.loads(text)
    except Exception:
        return fallback


def _format_recent_changes(text: str) -> list[str]:
    payload = _normalize_recent_changes_payload(text)
    if not payload:
        return ["暂无最近变更"]

    lines: list[str] = []
    for item in payload[:3]:
        lines.append(f"- {item['change_type']} {item['path']} | {item['summary']}")
    return lines or ["最近变更格式不可用"]


def _format_fitness(text: str) -> list[str]:
    payload = _normalize_fitness_payload(text)
    if not payload:
        return ["暂无 fitness 数据"]

    transactions = payload.get("transactions", {})
    validation = payload.get("validation", {})
    mutations = payload.get("mutations", {})

    lines = [
        (
            "transactions: "
            f"opened={transactions.get('opened', 0)} "
            f"closed={transactions.get('closed', 0)} "
            f"success={transactions.get('successful', 0)} "
            f"failed={transactions.get('failed', 0)} "
            f"success_rate={transactions.get('success_rate', '-')}"
        ),
        (
            "validation: "
            f"passed={validation.get('passed', 0)} "
            f"failed={validation.get('failed', 0)} "
            f"pass_rate={validation.get('pass_rate', '-')}"
        ),
        (
            "mutations: "
            f"recorded={mutations.get('recorded', 0)} "
            f"successful={mutations.get('successful', 0)} "
            f"failed={mutations.get('failed', 0)} "
            f"blocked={mutations.get('blocked', 0)}"
        ),
    ]

    recent = transactions.get("recent")
    if isinstance(recent, list) and recent:
        for item in recent[:2]:
            if not isinstance(item, dict):
                continue
            lines.append(
                "- recent "
                f"{item.get('txn_id', '-')} "
                f"status={item.get('status', '-')} "
                f"validation={item.get('validation_passed', 0)}/{item.get('validation_failed', 0)} "
                f"mutations={item.get('mutations_recorded', 0)}"
            )
    return lines


def _normalize_recent_changes_payload(text: str) -> list[dict[str, str]]:
    payload = _load_json_value(text, fallback=[])
    if not isinstance(payload, list):
        return []

    lines: list[dict[str, str]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "-")
        change_type = str(item.get("change_type") or "-")
        summary = str(item.get("summary") or item.get("subject") or "").replace("\n", " ").strip()
        if not summary:
            summary = "无摘要"
        if len(summary) > 72:
            summary = summary[:69] + "..."
        lines.append(
            {
                "path": path,
                "change_type": change_type,
                "summary": summary,
            }
        )
    return lines


def _normalize_fitness_payload(text: str) -> dict[str, Any]:
    payload = _load_json_value(text, fallback={})
    if not isinstance(payload, dict) or not payload:
        return {}

    transactions = payload.get("transactions") if isinstance(payload.get("transactions"), dict) else {}
    validation = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
    mutations = payload.get("mutations") if isinstance(payload.get("mutations"), dict) else {}
    recent_payload = transactions.get("recent") if isinstance(transactions.get("recent"), list) else []

    recent: list[dict[str, Any]] = []
    for item in recent_payload[:3]:
        if not isinstance(item, dict):
            continue
        recent.append(
            {
                "txn_id": str(item.get("txn_id") or ""),
                "status": str(item.get("status") or ""),
                "validation_passed": item.get("validation_passed", 0),
                "validation_failed": item.get("validation_failed", 0),
                "mutations_recorded": item.get("mutations_recorded", 0),
            }
        )

    return {
        "transactions": {
            "opened": transactions.get("opened", 0),
            "closed": transactions.get("closed", 0),
            "successful": transactions.get("successful", 0),
            "failed": transactions.get("failed", 0),
            "success_rate": transactions.get("success_rate"),
            "recent": recent,
        },
        "validation": {
            "passed": validation.get("passed", 0),
            "failed": validation.get("failed", 0),
            "pass_rate": validation.get("pass_rate"),
        },
        "mutations": {
            "recorded": mutations.get("recorded", 0),
            "successful": mutations.get("successful", 0),
            "failed": mutations.get("failed", 0),
            "blocked": mutations.get("blocked", 0),
        },
    }


def _normalize_worktree_snapshot(text: str) -> dict[str, Any]:
    payload = _load_json_value(text, fallback={})
    if not isinstance(payload, dict) or not payload:
        return {
            "available": False,
            "error": "worktree_snapshot_unavailable",
            "snapshot_id": "",
            "created_at": "",
            "base_rev": "",
            "has_staged": False,
            "has_unstaged": False,
            "has_untracked": False,
            "is_dirty": False,
            "dirty_file_count": 0,
            "files": [],
        }

    files_payload = payload.get("files") if isinstance(payload.get("files"), list) else []
    files: list[dict[str, Any]] = []
    for item in files_payload:
        if not isinstance(item, dict):
            continue
        files.append(
            {
                "path": str(item.get("path") or "-"),
                "status": str(item.get("status") or "-"),
                "staged": bool(item.get("staged")),
                "unstaged": bool(item.get("unstaged")),
                "untracked": bool(item.get("untracked")),
                "deleted": bool(item.get("deleted")),
            }
        )

    has_staged = bool(payload.get("has_staged"))
    has_unstaged = bool(payload.get("has_unstaged"))
    has_untracked = bool(payload.get("has_untracked"))
    return {
        "available": bool(payload.get("available", True)),
        "error": str(payload.get("error") or ""),
        "snapshot_id": str(payload.get("snapshot_id") or ""),
        "created_at": str(payload.get("created_at") or ""),
        "base_rev": str(payload.get("base_rev") or ""),
        "has_staged": has_staged,
        "has_unstaged": has_unstaged,
        "has_untracked": has_untracked,
        "is_dirty": has_staged or has_unstaged or has_untracked or bool(files),
        "dirty_file_count": len(files),
        "files": files,
    }


def _format_preview_worktree(snapshot_json: str) -> list[str]:
    formatted = format_self_evolution_worktree_snapshot(snapshot_json)
    return _trim_lines(formatted, limit=8, fallback="工作区快照暂不可用")


def _format_run_prompt_worktree(snapshot_json: str) -> list[str]:
    lines = _format_preview_worktree(snapshot_json)
    if lines and lines[0].startswith("snapshot:"):
        return lines[:1] + [line for line in lines[1:] if not line.startswith("created_at:")]
    return lines


def _format_preview_transactions(records: list[SelfEvolutionTransactionRecord] | None) -> list[str]:
    formatted = format_self_evolution_transaction_history(records or [])
    return _trim_lines(formatted, limit=6, fallback="暂无自进化事务记录")


def _workspace_root(project_root: Path) -> Path:
    workspace_name = getattr(get_config().agent, "workspace", "workspace")
    return (Path(project_root).resolve() / workspace_name).resolve()


def _audit_log_path(project_root: Path) -> Path:
    raw = Path(str(get_config().evolution.audit_log_path or "workspace/evolution/audit.jsonl"))
    if raw.is_absolute():
        return raw.resolve()
    return (Path(project_root).resolve() / raw).resolve()


def _short_rev(value: str | None) -> str:
    text = str(value or "").strip()
    return text[:12] if text else "-"


def _summarize_audit_record(record: dict[str, Any]) -> str:
    timestamp = str(record.get("timestamp") or "-")
    event = str(record.get("event") or "-")
    txn_id = str(record.get("txn_id") or "").strip()
    prefix = f"{timestamp} {event}"
    if txn_id:
        prefix += f" {txn_id}"

    if event == "txn_opened":
        return f"{prefix} base_rev={_short_rev(record.get('base_rev'))}"
    if event == "txn_closed":
        return f"{prefix} status={record.get('status') or '-'}"
    if event == "validation_completed":
        return (
            f"{prefix} kind={record.get('kind') or '-'} "
            f"passed={bool(record.get('passed'))} "
            f"message={str(record.get('message') or '').strip() or '-'}"
        )
    if event == "mutation_recorded":
        targets = record.get("target_paths")
        target = targets[0] if isinstance(targets, list) and targets else "-"
        return (
            f"{prefix} tool={record.get('tool_name') or '-'} "
            f"status={record.get('status') or '-'} "
            f"target={target}"
        )
    if event == "mutation_blocked":
        targets = record.get("target_paths")
        target = targets[0] if isinstance(targets, list) and targets else "-"
        return f"{prefix} tool={record.get('tool_name') or '-'} target={target}"
    return f"{prefix} {json.dumps(record, ensure_ascii=False)}"


__all__ = [
    "DEFAULT_SELF_EVOLUTION_GOAL",
    "SelfEvolutionTransactionRecord",
    "build_self_evolution_preview",
    "build_self_evolution_run_prompt",
    "build_self_evolution_snapshot",
    "build_self_evolution_worktree_snapshot",
    "format_self_evolution_audit_excerpt",
    "format_self_evolution_preview",
    "format_self_evolution_run_prompt",
    "format_self_evolution_transaction_history",
    "format_self_evolution_worktree_snapshot",
    "list_recent_self_evolution_transaction_payloads",
    "list_recent_self_evolution_transactions",
    "load_self_evolution_audit_records",
]
