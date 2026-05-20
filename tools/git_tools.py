# -*- coding: utf-8 -*-
"""
Git Memory 工具封装。

为 Agent 提供稳定的只读 Git 感知接口，内部委托给 GitMemoryService。
"""

from __future__ import annotations

import json

from core.infrastructure.agent_session import get_session_state
from core.infrastructure.evolution_governor import get_evolution_governor
from core.infrastructure.git_memory import get_git_memory_service


def _short_subject(subject: str | None) -> str | None:
    if not subject:
        return subject
    normalized = subject.replace("\\n", "\n")
    first_line = normalized.splitlines()[0].strip()
    return first_line or subject.strip()


def get_git_status_summary_tool(limit: int = 5) -> str:
    """获取当前 Git 工作区与会话注意力摘要。"""
    try:
        normalized_limit = int(limit)
    except (TypeError, ValueError):
        normalized_limit = 5
    normalized_limit = max(1, min(normalized_limit, 10))
    return get_git_memory_service().get_git_status_summary(limit=normalized_limit)


def get_recent_changes_tool(limit: int = 10) -> str:
    """获取最近提交变化摘要。"""
    changes = get_git_memory_service().get_recent_project_changes(limit=limit)
    payload = []
    for change in changes:
        payload.append(
            {
                "commit_sha": change.commit_sha,
                "path": change.path,
                "change_type": change.change_type,
                "summary": change.summary,
                "subject": _short_subject(change.subject),
                "old_path": change.old_path,
            }
        )
    return json.dumps(payload, ensure_ascii=False, indent=2)


def get_entity_history_tool(entity_ref: str, limit: int = 10) -> str:
    """获取某个实体的最近变化历史。"""
    return json.dumps(
        get_git_memory_service().get_entity_history(entity_ref=entity_ref, limit=limit),
        ensure_ascii=False,
        indent=2,
    )


def explain_current_worktree_tool() -> str:
    """详细解释当前 working tree 变化。"""
    return get_git_memory_service().explain_current_worktree()


def open_evolution_transaction_tool(summary: str = "") -> str:
    """打开一条演化事务记录。"""
    txn_id = get_git_memory_service().open_evolution_transaction(summary=summary)
    get_session_state().set_active_evolution_txn(txn_id)
    return json.dumps(
        {
            "status": "success",
            "txn_id": txn_id,
            "summary": summary,
        },
        ensure_ascii=False,
        indent=2,
    )


def close_evolution_transaction_tool(txn_id: str, status: str = "success", summary: str = "") -> str:
    """关闭一条演化事务记录。"""
    normalized = status.strip().lower() or "success"
    if normalized not in {"success", "failed", "cancelled"}:
        normalized = "success"
    get_git_memory_service().close_evolution_transaction(txn_id=txn_id, status=normalized, summary=summary)
    session = get_session_state()
    if session.get_active_evolution_txn() == txn_id:
        session.set_active_evolution_txn(None)
    return json.dumps(
        {
            "status": "success",
            "txn_id": txn_id,
            "transaction_status": normalized,
            "summary": summary,
        },
        ensure_ascii=False,
        indent=2,
    )


def get_evolution_fitness_tool(recent_limit: int = 5) -> str:
    """读取当前演化审计并生成轻量 fitness 摘要。"""
    try:
        normalized_limit = int(recent_limit)
    except (TypeError, ValueError):
        normalized_limit = 5
    normalized_limit = max(1, min(normalized_limit, 20))
    payload = get_evolution_governor().build_fitness_summary(recent_limit=normalized_limit)
    return json.dumps(payload, ensure_ascii=False, indent=2)


__all__ = [
    "get_git_status_summary_tool",
    "get_recent_changes_tool",
    "get_entity_history_tool",
    "explain_current_worktree_tool",
    "open_evolution_transaction_tool",
    "close_evolution_transaction_tool",
    "get_evolution_fitness_tool",
]
