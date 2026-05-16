# -*- coding: utf-8 -*-
"""系统提示词类型定义 — SystemPrompt / SystemPromptSection / BuildContext"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, NewType, Any

# 品牌化的不可变字符串元组，等效于 TypeScript 的 readonly string[] & { __brand }
SystemPrompt = NewType("SystemPrompt", tuple)

# 静/动态边界标记，用于 API 缓存前缀分割
SYSTEM_PROMPT_DYNAMIC_BOUNDARY = "<<<SYSTEM_PROMPT_SPLIT>>>"


def as_system_prompt(values):
    """将字符串序列转换为 SystemPrompt。"""
    return SystemPrompt(tuple(values))


@dataclass(frozen=True)
class SystemPromptSection:
    """系统提示词的一个章节。

    Attributes:
        name: 唯一标识，同时也是缓存 key。
        compute: 同步计算函数，返回章节内容或 None。
        cache_break: True = 每轮重新计算（动态章节），False = 全会话计算一次（静态章节）。
        priority: 排序优先级，数字越小越靠前。
        description: 章节描述（供 LLM 的 <active_components> 标签参考）。
        required: True 时无法被 exclude 移除。
        is_empty: 章节内容是否为空（无实际正文）。
    """

    name: str
    compute: Callable[[], Optional[str]]
    cache_break: bool = False
    priority: int = 50
    description: str = ""
    required: bool = False
    is_empty: bool = False


@dataclass(frozen=True)
class SectionRenderResult:
    """单个章节的一次实际渲染结果。"""

    name: str
    priority: int
    required: bool
    cache_break: bool
    description: str
    content: Optional[str]
    is_empty: bool
    source: Optional[str] = None


@dataclass(frozen=True)
class PromptBuildResult:
    """一次系统提示词构建的完整结果。"""

    prompt: SystemPrompt
    section_results: tuple[SectionRenderResult, ...]
    available_sections_text: str = ""


@dataclass
class BuildContext:
    """构建上下文，携带每轮可变的参数。"""

    core_context: Optional[str] = None
    current_goal: Optional[str] = None
    state_memory: str = ""
    prompt_mode: str = "orient"
