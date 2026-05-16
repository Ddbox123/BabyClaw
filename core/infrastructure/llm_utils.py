# -*- coding: utf-8 -*-
"""
core/infrastructure/llm_utils.py — LLM 辅助工具

职责：
- LLM 错误分类与重试策略
- 系统提示词消息构建
- LLM 响应内容解析（XML 工具调用、<state> 块）

从 agent.py 下沉，遵循 Core First 原则。
"""

from __future__ import annotations

import json
import re
from typing import Any, Tuple
from langchain_core.messages import SystemMessage

from core.llm.errors import classify_for_legacy
from core.llm.recovery import LLMRecoveryDecision, plan_recovery
from core.llm.routing import attach_recovery_fallback
from core.prompt_manager import to_string, split_sys_prompt_prefix

MAX_CONSECUTIVE_FAILURES = 5


def classify_llm_error(e: Exception) -> Tuple[str, bool, str]:
    """分类 LLM 异常，返回 (category, is_retryable, user_message)。

    Args:
        e: LLM 调用异常

    Returns:
        (错误类别, 是否可重试, 用户友好消息)
    """
    return classify_for_legacy(e)


def plan_llm_recovery(
    e: Exception,
    *,
    attempt: int = 1,
    max_attempts: int = MAX_CONSECUTIVE_FAILURES,
    config: Any = None,
    role: str = "primary",
    current_profile_id: str | None = None,
) -> LLMRecoveryDecision:
    """Return the normalized recovery decision for an LLM exception."""
    decision = plan_recovery(e, attempt=attempt, max_attempts=max_attempts)
    return attach_recovery_fallback(
        decision,
        config=config,
        role=role,
        current_profile_id=current_profile_id,
    )


_INT_LIKE_PATTERN = re.compile(r"^-?(0|[1-9]\d*)$")
_FLOAT_LIKE_PATTERN = re.compile(r"^-?(0|[1-9]\d*)\.\d+$")


def _coerce_tool_arg_value(value: Any) -> Any:
    """对 LLM/XML 工具参数做轻量标量归一化。"""
    if isinstance(value, dict):
        return {k: _coerce_tool_arg_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_coerce_tool_arg_value(item) for item in value]
    if not isinstance(value, str):
        return value

    stripped = value.strip()
    lowered = stripped.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in {"null", "none"}:
        return None
    if _INT_LIKE_PATTERN.fullmatch(stripped):
        try:
            return int(stripped)
        except ValueError:
            return value
    if _FLOAT_LIKE_PATTERN.fullmatch(stripped):
        try:
            return float(stripped)
        except ValueError:
            return value
    return value


def parse_tool_args(tool_args: Any) -> dict:
    """将工具参数解析为 dict。

    支持传入 str（JSON）、dict 或其他类型。

    Args:
        tool_args: 原始工具参数

    Returns:
        解析后的 dict，失败返回空 dict
    """
    if isinstance(tool_args, dict):
        return _coerce_tool_arg_value(tool_args)
    if isinstance(tool_args, str):
        try:
            parsed = json.loads(tool_args)
            return _coerce_tool_arg_value(parsed) if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}
    try:
        parsed = json.loads(str(tool_args))
        return _coerce_tool_arg_value(parsed) if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def build_system_message(sp) -> Any:
    """将 SystemPrompt 元组转为 API 消息格式，静态前缀标记 cache_control。

    利用 split_sys_prompt_prefix 分离静态/动态部分：
    - 静态前缀附加 cache_control: {"type": "ephemeral"}，供 API 缓存复用
    - 动态后缀不标记缓存，每轮重新计算
    - 无静态前缀时回退为普通 SystemMessage

    Args:
        sp: SystemPrompt 元组

    Returns:
        SystemMessage 或 dict 格式的消息
    """
    static_parts, dynamic_parts = split_sys_prompt_prefix(sp)
    if not static_parts:
        return SystemMessage(content=to_string(sp))
    content_blocks = [{
        "type": "text",
        "text": "\n\n".join(static_parts),
        "cache_control": {"type": "ephemeral"},
    }]
    if dynamic_parts:
        content_blocks.append({
            "type": "text",
            "text": "\n\n".join(dynamic_parts),
        })
    return {"role": "system", "content": content_blocks}


def parse_xml_tool_calls(content: str) -> list:
    """解析 LLM 响应中的 XML 格式工具调用。

    模型有时输出 <invoke> XML 标签而非标准 tool_calls，
    本函数将其解析为统一格式。

    Args:
        content: LLM 响应原始文本

    Returns:
        [{"name": "tool_name", "args": {"arg1": "value1"}, "id": "xml_0"}, ...]
    """
    if '<invoke' not in content:
        return []

    tool_calls = []
    invoke_pattern = re.compile(
        r'<invoke\s+name=["\']([^"\']+)["\']\s*>(.*?)</invoke>',
        re.DOTALL,
    )
    param_pattern = re.compile(
        r'<parameter\s+name=["\']([^"\']+)["\']\s*>(.*?)</parameter>',
        re.DOTALL,
    )

    for i, m in enumerate(invoke_pattern.finditer(content)):
        tool_name = (m.group(1) or "").strip()
        body = m.group(2)
        if not tool_name:
            continue
        args = {}
        for pm in param_pattern.finditer(body):
            param_name = (pm.group(1) or "").strip()
            if not param_name:
                continue
            args[param_name] = (pm.group(2) or "").strip()
        tool_calls.append({"name": tool_name, "args": args, "id": f"xml_{i}"})

    return tool_calls


def parse_state_block(content: str) -> dict:
    """从 LLM 响应中解析 <state> JSON 块（内心感知状态）。

    MENTAL_SOUL.md 要求感知层输出 <state> JSON 块，
    本函数提取其中的情绪和直觉信息用于日志记录。

    Args:
        content: LLM 响应原始文本

    Returns:
        {"mood": "...", "feeling": "...", "whisper": "..."}
        解析失败返回空 dict
    """
    match = re.search(r'<state>\s*(\{.*?\})\s*</state>', content, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except (json.JSONDecodeError, ValueError):
            pass
    return {}
