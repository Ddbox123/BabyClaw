#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
工具结果处理工具

从 agent.py 中提取的工具结果处理函数：
- truncate_result: 截断超长工具结果
- format_tool_message: 格式化工具消息

使用方式：
    from core.infrastructure.tool_result import truncate_result, format_tool_message
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Any, Optional, List


# 默认截断阈值
DEFAULT_MAX_CHARS = 4000


@dataclass
class ToolResultEnvelope:
    """工具结果的统一封装。"""

    content: str
    truncated: bool
    original_length: int
    result_kind: str = "text"
    strategy: str = "passthrough"
    range_info: str = ""
    continuation_hint: str = ""


def _infer_result_kind(tool_name: str = "", result_str: str = "") -> str:
    name = (tool_name or "").lower()
    text = result_str or ""
    if name in {"read_file_tool", "read_file"} or text.startswith("[文件]"):
        return "file_read"
    if name in {"get_code_entity_tool", "list_file_entities_tool", "python_symbol_tool"} or text.startswith("[AST]"):
        return "python_structure"
    if name in {"grep_search_tool", "search_and_read", "find_definitions", "find_function_calls"} or text.startswith("[搜索]"):
        return "search"
    if text.startswith("{") or text.startswith("["):
        return "structured_text"
    return "text"


def _extract_range_info(result_kind: str, result_str: str) -> str:
    if result_kind != "file_read":
        return ""
    for line in result_str.splitlines():
        if line.startswith("[区间] "):
            return line[len("[区间] ") :].strip()
    return ""


def _extract_continuation_hint(result_kind: str, result_str: str) -> str:
    if result_kind == "file_read":
        for line in result_str.splitlines():
            if line.startswith("[续读] "):
                return line[len("[续读] ") :].strip()
    if result_kind == "python_structure":
        return "优先继续使用 get_code_entity_tool / list_file_entities_tool 做实体级补读。"
    if result_kind == "search":
        return "优先缩小搜索范围，或按命中文件继续读取局部上下文。"
    return ""


def _split_header_and_body(result_str: str) -> tuple[list[str], str]:
    marker = "--- Content ---"
    if marker not in result_str:
        return result_str.splitlines(), ""
    head, body = result_str.split(marker, 1)
    header_lines = [line for line in head.splitlines() if line.strip()]
    return header_lines, body.strip("\n")


def _compact_file_read(result_str: str, max_chars: int, continuation_hint: str) -> Optional[str]:
    header_lines, body = _split_header_and_body(result_str)
    if not header_lines:
        return None

    content_lines = [line for line in body.splitlines() if line.strip()]
    head_excerpt = content_lines[:12]
    tail_excerpt = content_lines[-6:] if len(content_lines) > 18 else []

    compact_lines = list(header_lines)
    compact_lines.extend(["", "--- Content Preview ---"])
    compact_lines.extend(head_excerpt)
    if tail_excerpt:
        compact_lines.append("... [中间内容省略，优先按续读提示补局部上下文] ...")
        compact_lines.extend(tail_excerpt)
    compact_lines.append("--- End Preview ---")
    compact_lines.append(f"[...结果已截断，原长度 {len(result_str)} 字符...]")
    if continuation_hint:
        compact_lines.append(f"[截断信息] 建议续读={continuation_hint}")

    compact = "\n".join(compact_lines)
    if len(compact) <= max_chars + 180:
        return compact
    return None


def _compact_search_result(result_str: str, max_chars: int, continuation_hint: str) -> Optional[str]:
    lines = result_str.splitlines()
    if not lines:
        return None

    summary_lines: list[str] = []
    preview_lines: list[str] = []
    in_preview = False
    file_preview_count = 0

    for line in lines:
        stripped = line.strip()
        if stripped == "[搜索预览]":
            in_preview = True
            summary_lines.append(line)
            continue
        if not in_preview:
            summary_lines.append(line)
            continue
        if line.startswith("📁 "):
            file_preview_count += 1
            if file_preview_count > 2:
                continue
        if file_preview_count <= 2:
            preview_lines.append(line)

    compact_lines = summary_lines + preview_lines
    compact_lines.append(f"[...结果已截断，原长度 {len(result_str)} 字符...]")
    if continuation_hint:
        compact_lines.append(f"[截断信息] 建议续读={continuation_hint}")
    compact = "\n".join(line for line in compact_lines if line is not None)
    if len(compact) <= max_chars + 200:
        return compact
    return None


def package_tool_result(
    result: Any,
    *,
    tool_name: str = "",
    max_chars: int = DEFAULT_MAX_CHARS,
) -> ToolResultEnvelope:
    """将工具结果封装为带元信息的统一结构。"""
    result_str = str(result)
    result_kind = _infer_result_kind(tool_name, result_str)
    range_info = _extract_range_info(result_kind, result_str)
    continuation_hint = _extract_continuation_hint(result_kind, result_str)

    if len(result_str) <= max_chars:
        return ToolResultEnvelope(
            content=result_str,
            truncated=False,
            original_length=len(result_str),
            result_kind=result_kind,
            strategy="passthrough",
            range_info=range_info,
            continuation_hint=continuation_hint,
        )

    compact_content: Optional[str] = None
    if result_kind == "file_read":
        compact_content = _compact_file_read(result_str, max_chars, continuation_hint)
    elif result_kind == "search":
        compact_content = _compact_search_result(result_str, max_chars, continuation_hint)
    if compact_content:
        return ToolResultEnvelope(
            content=compact_content,
            truncated=True,
            original_length=len(result_str),
            result_kind=result_kind,
            strategy="structured_compact",
            range_info=range_info,
            continuation_hint=continuation_hint,
        )

    suffix_lines = [
        f"[...结果已截断，原长度 {len(result_str)} 字符...]",
        f"[截断信息] 类型={result_kind} | 原长度={len(result_str)} 字符",
    ]
    if range_info:
        suffix_lines.append(f"[截断信息] 当前范围={range_info}")
    if continuation_hint:
        suffix_lines.append(f"[截断信息] 建议续读={continuation_hint}")
    suffix = "\n" + "\n".join(suffix_lines)
    budget = max(0, max_chars - len(suffix) - 1)
    if budget < max(8, max_chars // 3):
        legacy_content = result_str[:max_chars] + f"\n[...结果已截断，原长度 {len(result_str)} 字符...]"
        return ToolResultEnvelope(
            content=legacy_content,
            truncated=True,
            original_length=len(result_str),
            result_kind=result_kind,
            strategy="legacy_prefix_truncate",
            range_info=range_info,
            continuation_hint=continuation_hint,
        )
    content = result_str[:budget] + suffix if budget > 0 else suffix.lstrip()

    return ToolResultEnvelope(
        content=content,
        truncated=True,
        original_length=len(result_str),
        result_kind=result_kind,
        strategy="annotated_truncate",
        range_info=range_info,
        continuation_hint=continuation_hint,
    )


def truncate_result(result: Any, max_chars: int = DEFAULT_MAX_CHARS) -> tuple:
    """
    截断超长工具结果

    Args:
        result: 工具结果
        max_chars: 最大字符数

    Returns:
        (截断后的结果字符串, 是否被截断)
    """
    packaged = package_tool_result(result, max_chars=max_chars)
    return packaged.content, packaged.truncated


def infer_result_from_tool_outputs(tool_outputs: List[str]) -> Dict[str, Any]:
    """从最近工具输出中提炼结构化诊断结果。"""
    haystack = "\n".join(str(item or "") for item in tool_outputs if str(item or "").strip())
    if not haystack:
        return {}

    error_patterns = [
        r"(OSError:\s*\[Errno\s*\d+\][^\n]*)",
        r"(ValueError:[^\n]*)",
        r"(RuntimeError:[^\n]*)",
        r"(TimeoutError:[^\n]*)",
        r"(主循环异常:[^\n]*)",
        r"(\[超时\][^\n]*)",
    ]
    evidence: List[str] = []
    findings: List[str] = []
    for pattern in error_patterns:
        match = re.search(pattern, haystack, flags=re.IGNORECASE)
        if match:
            line = match.group(1).strip()
            evidence.append(line)
            findings.append(f"最近工具输出已包含异常线索: {line}")
            break

    if "Traceback" in haystack:
        findings.append("最近工具输出包含 traceback，可直接作为诊断证据。")

    if not evidence and not findings:
        return {}

    return {
        "status": "partial",
        "summary": evidence[0] if evidence else "最近工具输出已包含可用异常线索。",
        "findings": findings[:3],
        "evidence": evidence[:3],
        "recommended_next_action": "根据现有异常证据直接收束，不再继续扩散读取。",
        "confidence": "medium",
    }


def compact_tool_output_for_diagnosis(text: str, max_chars: int = 6000) -> str:
    """压缩超长工具输出，保留头尾证据。"""
    raw = str(text or "")
    evidence_lines: List[str] = []
    for pattern in (
        r"OSError:\s*\[Errno\s*\d+\][^\n]*",
        r"ValueError:[^\n]*",
        r"RuntimeError:[^\n]*",
        r"TimeoutError:[^\n]*",
        r"主循环异常:[^\n]*",
        r"\[超时\][^\n]*",
    ):
        match = re.search(pattern, raw, flags=re.IGNORECASE)
        if match:
            evidence_lines.append(match.group(0).strip())

    if len(raw) <= max_chars:
        compacted = raw
    else:
        head = max_chars // 2
        tail = max_chars - head
        compacted = raw[:head] + "\n...\n" + raw[-tail:]

    if evidence_lines:
        suffix = "\n".join(dict.fromkeys(evidence_lines))
        if suffix not in compacted:
            compacted = f"{compacted}\n\n[提取证据]\n{suffix}"
    return compacted


def format_tool_message(
    tool_call: Dict,
    result: Any,
    action: Optional[str] = None,
) -> tuple:
    """
    格式化工具消息

    Args:
        tool_call: 工具调用信息
        result: 工具执行结果
        action: 特殊动作

    Returns:
        (ToolMessage 内容字符串, tool_call_id)
    """
    from langchain_core.messages import ToolMessage

    result_str, _ = truncate_result(result)

    # 安全获取 tool_call_id
    tool_call_id = str(tool_call.get('id', '')) if tool_call.get('id') is not None else ''

    return result_str, tool_call_id


__all__ = [
    "truncate_result",
    "package_tool_result",
    "ToolResultEnvelope",
    "format_tool_message",
    "compact_tool_output_for_diagnosis",
    "infer_result_from_tool_outputs",
    "DEFAULT_MAX_CHARS",
]
