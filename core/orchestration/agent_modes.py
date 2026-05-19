# -*- coding: utf-8 -*-
"""Agent 模式策略与模式扩展入口。

把运行模式定义、模式策略和模式级输入协议收口在 core/orchestration，
避免把未来的 chat / plan / query 等扩展继续堆在 agent.py。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Callable

from core.infrastructure.runtime_input import (
    build_chat_user_message,
    build_external_request_message,
    build_supervised_evolution_request_message,
)

if TYPE_CHECKING:
    from config import AppConfig


class AgentMode(str, Enum):
    CHAT = "chat"
    SELF_EVOLUTION = "self_evolution"
    SUPERVISED_EVOLUTION = "supervised_evolution"


@dataclass(frozen=True)
class ModePolicy:
    mode: AgentMode
    orchestrator_kind: str
    keep_multi_turn_context: bool
    allow_auto_loop: bool
    capture_chat_dataset_candidates: bool
    route_explicit_evolution_requests: bool
    reset_context_before_turn: bool
    reset_context_between_cases: bool
    allow_direct_supervised_payload: bool
    finish_after_direct_response: bool
    runtime_input_builder: Callable[[str], object]


def normalize_agent_mode(value: str | AgentMode | None, *, default: str = AgentMode.SELF_EVOLUTION.value) -> AgentMode:
    if isinstance(value, AgentMode):
        return value
    text = str(value or default).strip().lower() or AgentMode.SELF_EVOLUTION.value
    try:
        return AgentMode(text)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in AgentMode)
        raise ValueError(f"未知 Agent mode: {value!r}；可选: {allowed}") from exc


def is_mode_enabled(mode: AgentMode, config: "AppConfig") -> bool:
    modes_cfg = getattr(getattr(config, "agent", None), "modes", None)
    if mode == AgentMode.CHAT:
        return bool(getattr(modes_cfg, "chat_enabled", True))
    if mode == AgentMode.SUPERVISED_EVOLUTION:
        return bool(getattr(modes_cfg, "supervised_evolution_enabled", True))
    return bool(getattr(modes_cfg, "self_evolution_enabled", True))


def resolve_mode_policy(mode: str | AgentMode | None, config: "AppConfig") -> ModePolicy:
    normalized = normalize_agent_mode(mode, default=getattr(config.agent, "default_mode", AgentMode.SELF_EVOLUTION.value))
    if not is_mode_enabled(normalized, config):
        raise ValueError(f"Agent mode `{normalized.value}` 当前已在配置中禁用")

    explicit_behavior = str(
        getattr(getattr(config.agent, "modes", None), "explicit_evolution_request_behavior", "route_to_workbench")
        or "route_to_workbench"
    ).strip().lower()
    route_explicit = explicit_behavior == "route_to_workbench"

    if normalized == AgentMode.CHAT:
        return ModePolicy(
            mode=normalized,
            orchestrator_kind="chat",
            keep_multi_turn_context=True,
            allow_auto_loop=False,
            capture_chat_dataset_candidates=True,
            route_explicit_evolution_requests=route_explicit,
            reset_context_before_turn=False,
            reset_context_between_cases=False,
            allow_direct_supervised_payload=False,
            finish_after_direct_response=False,
            runtime_input_builder=build_chat_user_message,
        )
    if normalized == AgentMode.SUPERVISED_EVOLUTION:
        return ModePolicy(
            mode=normalized,
            orchestrator_kind="evolution",
            keep_multi_turn_context=True,
            allow_auto_loop=False,
            capture_chat_dataset_candidates=False,
            route_explicit_evolution_requests=False,
            reset_context_before_turn=True,
            reset_context_between_cases=True,
            allow_direct_supervised_payload=True,
            finish_after_direct_response=False,
            runtime_input_builder=build_supervised_evolution_request_message,
        )
    return ModePolicy(
        mode=normalized,
        orchestrator_kind="evolution",
        keep_multi_turn_context=True,
        allow_auto_loop=True,
        capture_chat_dataset_candidates=False,
        route_explicit_evolution_requests=False,
        reset_context_before_turn=False,
        reset_context_between_cases=False,
        allow_direct_supervised_payload=False,
        finish_after_direct_response=False,
        runtime_input_builder=build_external_request_message,
    )


def looks_like_explicit_evolution_request(text: str) -> bool:
    normalized = (text or "").strip().lower()
    if not normalized:
        return False
    markers = (
        "开始自主进化",
        "自主进化",
        "自进化",
        "监督进化",
        "进化一下",
        "触发进化",
        "trigger_self_restart_tool",
        "open_evolution_transaction_tool",
        "close_evolution_transaction_tool",
        "start self evolution",
        "self evolve",
        "self-evolution",
        "supervised evolution",
    )
    return any(marker in normalized for marker in markers)


__all__ = [
    "AgentMode",
    "ModePolicy",
    "is_mode_enabled",
    "looks_like_explicit_evolution_request",
    "normalize_agent_mode",
    "resolve_mode_policy",
]
