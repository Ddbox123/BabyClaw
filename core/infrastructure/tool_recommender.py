# -*- coding: utf-8 -*-
"""
工具推荐/决策器。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Dict, Any


@dataclass(frozen=True)
class ToolDecision:
    next_intent: str
    recommended_tools: List[str]
    avoid_tools: List[str]
    reason: str
    fallback_if_failed: List[str]


def decide_next_tools(snapshot: Dict[str, Any]) -> ToolDecision:
    task = snapshot.get("reading_task") or "locate"
    sufficiency = snapshot.get("reading_sufficiency") or ""
    read_ranges = snapshot.get("read_ranges") or {}
    read_entities = snapshot.get("read_entities") or {}
    read_searches = snapshot.get("read_searches") or []
    blockers = snapshot.get("recent_blockers") or []
    validations = snapshot.get("recent_validation_results") or []
    pending_continuations = snapshot.get("pending_continuations") or []

    if pending_continuations:
        latest = pending_continuations[-1]
        path = latest.get("path") or ""
        reason = f"上一段结果未读完，先沿续读线索补读 {path}。" if path else "上一段结果未读完，先沿续读线索补读。"
        return ToolDecision(
            next_intent="inspect_range",
            recommended_tools=["read_file_tool"],
            avoid_tools=["grep_search_tool", "cli_tool"],
            reason=reason,
            fallback_if_failed=["get_code_entity_tool", "list_file_entities_tool"],
        )

    if task == "verify":
        return ToolDecision(
            next_intent="inspect_range" if validations else "locate_text",
            recommended_tools=["run_test_for_tool", "read_file_tool"],
            avoid_tools=["cli_tool"] if validations else [],
            reason="验证任务优先读取失败输出与相关片段，再决定复测。",
            fallback_if_failed=["grep_search_tool", "python_lint_tool"],
        )

    if task == "modify":
        enough = "已足够" in sufficiency or "可开始动手" in sufficiency
        return ToolDecision(
            next_intent="inspect_entity" if not enough else "edit_target",
            recommended_tools=["get_code_entity_tool", "read_file_tool"] if not enough else ["apply_diff_edit_tool"],
            avoid_tools=["grep_search_tool"] if enough else ["cli_tool"],
            reason="修改任务先拿到目标实体和上下文；证据足够后直接进入编辑。",
            fallback_if_failed=["list_file_entities_tool", "grep_search_tool"],
        )

    if task == "understand":
        return ToolDecision(
            next_intent="inspect_structure" if not read_entities else "inspect_entity",
            recommended_tools=["list_file_entities_tool", "get_code_entity_tool"],
            avoid_tools=["cli_tool"],
            reason="理解任务先看结构，再看实体。",
            fallback_if_failed=["read_file_tool"],
        )

    if task == "analyze":
        return ToolDecision(
            next_intent="locate_text" if not read_searches else "inspect_range",
            recommended_tools=["grep_search_tool", "read_file_tool"],
            avoid_tools=["cli_tool"],
            reason="归因任务先定位症状，再补局部证据。",
            fallback_if_failed=["python_symbol_tool"],
        )

    has_location = bool(read_searches)
    has_detail = any(read_ranges.values()) or any(read_entities.values())
    avoid = []
    if any(item.get("kind") == "duplicate_search" for item in blockers):
        avoid.append("grep_search_tool")
    return ToolDecision(
        next_intent="locate_text" if not has_location else ("inspect_entity" if not has_detail else "inspect_range"),
        recommended_tools=["grep_search_tool", "python_symbol_tool"] if not has_location else (["get_code_entity_tool", "list_file_entities_tool"] if not has_detail else ["read_file_tool"]),
        avoid_tools=avoid + ["cli_tool"],
        reason="定位任务先命中，再转实体或局部上下文。",
        fallback_if_failed=["python_symbol_tool", "read_file_tool"],
    )


def format_decision_summary(decision: ToolDecision) -> str:
    parts = [
        f"下一步意图：{decision.next_intent}",
        f"推荐工具：{' -> '.join(decision.recommended_tools)}",
    ]
    if decision.avoid_tools:
        parts.append(f"避免工具：{' / '.join(decision.avoid_tools)}")
    parts.append(f"原因：{decision.reason}")
    if decision.fallback_if_failed:
        parts.append(f"失败回退：{' -> '.join(decision.fallback_if_failed)}")
    return " | ".join(parts)


__all__ = ["ToolDecision", "decide_next_tools", "format_decision_summary"]
