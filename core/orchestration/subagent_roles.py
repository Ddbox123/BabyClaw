# -*- coding: utf-8 -*-
"""子 agent 角色模型。

从全局职责上定义子 agent 的系统角色，而不是只在局部启发式里判断 task_type。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Tuple


@dataclass(frozen=True)
class SubagentRoleSpec:
    task_type: str
    role_name: str
    system_purpose: str
    owned_work: Tuple[str, ...]
    forbidden_work: Tuple[str, ...]
    return_shape: str


@dataclass(frozen=True)
class SubagentRoleNeed:
    task_type: str
    trigger_reason: str
    why_now: str


_ROLE_SPECS: Dict[str, SubagentRoleSpec] = {
    "diagnose": SubagentRoleSpec(
        task_type="diagnose",
        role_name="局部故障归因器",
        system_purpose="隔离高噪音的失败归因工作，为主 agent 产出可裁决的异常证据。",
        owned_work=(
            "定位重复调用、漂移、超时、验证失败、traceback 等局部异常线索",
            "把失败现象压缩成最短证据链与下一步建议",
        ),
        forbidden_work=(
            "不负责跨模块方案选择",
            "不负责直接修改代码或替主 agent 做最终裁决",
        ),
        return_shape="返回异常摘要、命中证据、局部发现与建议的下一步。",
    ),
    "inspect": SubagentRoleSpec(
        task_type="inspect",
        role_name="局部状态探针",
        system_purpose="隔离局部查阅和一致性核查，减少主 agent 在静态阅读上的工作记忆负担。",
        owned_work=(
            "对单段链路、配置、prompt、局部修改范围做静态核查",
            "把分散片段压缩成是否一致、哪里不一致、还缺什么证据",
        ),
        forbidden_work=(
            "不负责故障根因裁决",
            "不负责把局部观察直接扩大成全局方案",
        ),
        return_shape="返回局部状态摘要、一致性判断、缺口说明与建议的下一步。",
    ),
    "summarize": SubagentRoleSpec(
        task_type="summarize",
        role_name="证据压缩器",
        system_purpose="把已存在的局部证据压缩成低熵结论，帮助主 agent 收束上下文。",
        owned_work=(
            "整理已有 findings、validation、blockers、modified_paths",
            "在不新增探查链路的前提下压缩成结论草案与证据包",
        ),
        forbidden_work=(
            "不负责继续探路或扩展读取范围",
            "不负责把摘要结果当成最终决策落地",
        ),
        return_shape="返回压缩后的结论、关键证据、剩余缺口与建议的下一步。",
    ),
}

ALLOWED_SUBAGENT_TASK_TYPES = frozenset(_ROLE_SPECS.keys())


def get_subagent_role_spec(task_type: str) -> SubagentRoleSpec:
    normalized = (task_type or "").strip().lower() or "inspect"
    return _ROLE_SPECS.get(normalized, _ROLE_SPECS["inspect"])


def extract_subagent_primary_goal(prompt: str | None) -> str:
    """从子 agent 的瘦提示词中提取唯一目标，避免整段模板污染 current_goal。"""
    text = (prompt or "").strip()
    if not text:
        return ""

    match = re.search(r"^\-\s*当前唯一目标:\s*(.+?)\s*$", text, flags=re.MULTILINE)
    if match:
        goal = match.group(1).strip()
        if goal:
            return goal

    legacy_match = re.search(
        r"请围绕以下唯一任务开展分析.*?\n\n(.+?)\n\nJSON 至少包含:",
        text,
        flags=re.DOTALL,
    )
    if legacy_match:
        goal = legacy_match.group(1).strip()
        if goal:
            return goal

    return text
