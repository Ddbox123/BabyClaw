# -*- coding: utf-8 -*-
"""Agent 自进化 workbench helpers."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config import get_config
from tools.git_tools import (
    explain_current_worktree_tool,
    get_evolution_fitness_tool,
    get_git_status_summary_tool,
    get_recent_changes_tool,
)


DEFAULT_SELF_EVOLUTION_GOAL = "开始自主进化"


@dataclass(frozen=True)
class SelfEvolutionTransactionRecord:
    txn_id: str
    opened_at: str
    closed_at: str | None
    base_rev: str | None
    status: str
    summary: str


def build_self_evolution_preview(
    goal: str = DEFAULT_SELF_EVOLUTION_GOAL,
    *,
    status_limit: int = 5,
    change_limit: int = 3,
    recent_limit: int = 3,
) -> str:
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
    return format_self_evolution_preview(
        goal=goal,
        status_summary=status_summary,
        recent_changes_json=recent_changes_json,
        fitness_json=fitness_json,
    )


def format_self_evolution_preview(
    *,
    goal: str,
    status_summary: str,
    recent_changes_json: str,
    fitness_json: str,
) -> str:
    lines = [
        f"goal: {goal or DEFAULT_SELF_EVOLUTION_GOAL}",
        "git status:",
        *_indent_lines(_trim_lines(status_summary, fallback="git 状态暂不可用")),
        "recent changes:",
        *_indent_lines(_format_recent_changes(recent_changes_json)),
        "fitness:",
        *_indent_lines(_format_fitness(fitness_json)),
    ]
    return "\n".join(lines)


def build_self_evolution_worktree_snapshot() -> str:
    snapshot_json = _safe_tool_call(
        explain_current_worktree_tool,
        fallback="{}",
    )
    return format_self_evolution_worktree_snapshot(snapshot_json)


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
    if not audit_path.exists():
        return "暂无自进化审计日志"

    records: list[dict[str, Any]] = []
    for line in audit_path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        payload = _load_json_value(text, fallback=None)
        if isinstance(payload, dict):
            records.append(payload)
    if not records:
        return "自进化审计日志为空"

    tail = records[-max(1, int(limit or 10)) :]
    lines = [f"audit log: {audit_path}"]
    for item in tail:
        lines.append(f"- {_summarize_audit_record(item)}")
    return "\n".join(lines)


def _safe_tool_call(fn, *, fallback: str) -> str:
    try:
        result = fn()
    except Exception as exc:
        return f"{fallback} ({type(exc).__name__}: {exc})"
    text = str(result or "").strip()
    return text or fallback


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
    payload = _load_json_value(text, fallback=[])
    if not isinstance(payload, list) or not payload:
        return ["暂无最近变更"]

    lines: list[str] = []
    for item in payload[:3]:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "-")
        change_type = str(item.get("change_type") or "-")
        summary = str(item.get("summary") or item.get("subject") or "").replace("\n", " ").strip()
        if not summary:
            summary = "无摘要"
        if len(summary) > 72:
            summary = summary[:69] + "..."
        lines.append(f"- {change_type} {path} | {summary}")
    return lines or ["最近变更格式不可用"]


def _format_fitness(text: str) -> list[str]:
    payload = _load_json_value(text, fallback={})
    if not isinstance(payload, dict) or not payload:
        return ["暂无 fitness 数据"]

    transactions = payload.get("transactions") if isinstance(payload.get("transactions"), dict) else {}
    validation = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
    mutations = payload.get("mutations") if isinstance(payload.get("mutations"), dict) else {}

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
    "build_self_evolution_worktree_snapshot",
    "format_self_evolution_audit_excerpt",
    "format_self_evolution_preview",
    "format_self_evolution_transaction_history",
    "format_self_evolution_worktree_snapshot",
    "list_recent_self_evolution_transactions",
]
