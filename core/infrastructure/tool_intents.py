# -*- coding: utf-8 -*-
"""
工具意图层定义。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class ToolIntent:
    name: str
    recommended_tools: List[str]
    description: str


TOOL_INTENTS = {
    "locate_text": ToolIntent(
        name="locate_text",
        recommended_tools=["grep_search_tool"],
        description="先定位文本或关键词命中，再决定下一步精读对象。",
    ),
    "locate_symbol": ToolIntent(
        name="locate_symbol",
        recommended_tools=["python_symbol_tool", "find_definitions_tool"],
        description="优先确认定义、引用或真实落点。",
    ),
    "locate_calls": ToolIntent(
        name="locate_calls",
        recommended_tools=["find_function_calls_tool"],
        description="定位函数/方法调用点。",
    ),
    "inspect_structure": ToolIntent(
        name="inspect_structure",
        recommended_tools=["list_file_entities_tool"],
        description="先看结构骨架，避免直接吞整文件。",
    ),
    "inspect_entity": ToolIntent(
        name="inspect_entity",
        recommended_tools=["get_code_entity_tool", "list_file_entities_tool"],
        description="精读类、函数、方法实体。",
    ),
    "inspect_range": ToolIntent(
        name="inspect_range",
        recommended_tools=["read_file_tool"],
        description="分页阅读局部上下文。",
    ),
    "verify_change": ToolIntent(
        name="verify_change",
        recommended_tools=["python_lint_tool", "run_test_for_tool", "cli_tool"],
        description="按 lint / test / compile 闭环验证修改。",
    ),
    "inspect_history": ToolIntent(
        name="inspect_history",
        recommended_tools=[
            "get_git_status_summary_tool",
            "get_recent_changes_tool",
            "get_entity_history_tool",
        ],
        description="查看 Git 变化、实体历史和 worktree 状态。",
    ),
}


def get_tool_intent(name: str) -> ToolIntent | None:
    return TOOL_INTENTS.get(name)


def humanize_reading_task(task: str) -> str:
    mapping = {
        "locate": "定位",
        "understand": "理解",
        "modify": "修改",
        "verify": "验证",
        "analyze": "分析",
    }
    return mapping.get((task or "").lower(), task or "")


def humanize_tool_intent(intent: str) -> str:
    mapping = {
        "locate_text": "定位文本",
        "locate_symbol": "定位符号",
        "locate_calls": "定位调用",
        "inspect_structure": "查看结构",
        "inspect_entity": "精读实体",
        "inspect_range": "查看片段",
        "verify_change": "验证改动",
        "inspect_history": "查看历史",
        "edit_target": "开始修改",
    }
    return mapping.get((intent or "").lower(), intent or "")


def humanize_tool_name(tool_name: str) -> str:
    mapping = {
        "grep_search_tool": "搜索命中",
        "python_symbol_tool": "符号定位",
        "find_definitions_tool": "查定义",
        "find_function_calls_tool": "查调用",
        "list_file_entities_tool": "看结构骨架",
        "get_code_entity_tool": "读目标实体",
        "read_file_tool": "读局部片段",
        "python_lint_tool": "Lint 检查",
        "run_test_for_tool": "运行测试",
        "cli_tool": "命令兜底",
        "apply_diff_edit_tool": "应用修改",
        "get_git_status_summary_tool": "工作区状态",
        "get_recent_changes_tool": "最近变化",
        "get_entity_history_tool": "实体历史",
    }
    return mapping.get(tool_name, tool_name)


def humanize_tool_chain(tool_names: List[str], limit: int | None = None) -> str:
    names = tool_names[:limit] if limit is not None else tool_names
    return " -> ".join(humanize_tool_name(name) for name in names)


__all__ = [
    "ToolIntent",
    "TOOL_INTENTS",
    "get_tool_intent",
    "humanize_reading_task",
    "humanize_tool_intent",
    "humanize_tool_name",
    "humanize_tool_chain",
]
