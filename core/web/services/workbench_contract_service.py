"""Shared workbench contract helpers for frontend-facing defaults and availability."""

from __future__ import annotations

from typing import Any

from config.public_config import build_effective_config, load_public_config
from core.orchestration.agent_modes import AgentMode, is_mode_enabled, normalize_agent_mode


def _mode_availability(config) -> dict[str, bool]:
    return {
        AgentMode.CHAT.value: is_mode_enabled(AgentMode.CHAT, config),
        AgentMode.SELF_EVOLUTION.value: is_mode_enabled(AgentMode.SELF_EVOLUTION, config),
        AgentMode.SUPERVISED_EVOLUTION.value: is_mode_enabled(AgentMode.SUPERVISED_EVOLUTION, config),
    }


def _domain_availability(config, mode_availability: dict[str, bool]) -> dict[str, bool]:
    evolution_enabled = bool(getattr(getattr(config, "evolution", None), "enabled", True))
    has_evolution_mode = (
        mode_availability[AgentMode.SELF_EVOLUTION.value]
        or mode_availability[AgentMode.SUPERVISED_EVOLUTION.value]
    )
    return {
        "chat": mode_availability[AgentMode.CHAT.value],
        "evolution": evolution_enabled and has_evolution_mode,
        "config": True,
    }


def _default_mode_candidates(config) -> list[AgentMode]:
    raw_candidates = [
        getattr(getattr(config, "agent", None), "modes", None).default_shell_mode
        if getattr(getattr(config, "agent", None), "modes", None)
        else None,
        getattr(getattr(config, "agent", None), "default_mode", None),
        AgentMode.CHAT.value,
        AgentMode.SELF_EVOLUTION.value,
        AgentMode.SUPERVISED_EVOLUTION.value,
    ]
    candidates: list[AgentMode] = []
    for value in raw_candidates:
        normalized = normalize_agent_mode(value)
        if normalized not in candidates:
            candidates.append(normalized)
    return candidates


def _resolve_default_mode(config, mode_availability: dict[str, bool], domain_availability: dict[str, bool]) -> str:
    for candidate in _default_mode_candidates(config):
        if candidate == AgentMode.CHAT:
            if domain_availability["chat"] and mode_availability[candidate.value]:
                return candidate.value
            continue
        if domain_availability["evolution"] and mode_availability[candidate.value]:
            return candidate.value
    return "config"


def _default_route(
    default_mode: str,
    mode_availability: dict[str, bool],
    domain_availability: dict[str, bool],
) -> str:
    if default_mode == AgentMode.CHAT.value:
        if domain_availability["chat"] and mode_availability[AgentMode.CHAT.value]:
            return "/chat"
    elif default_mode == AgentMode.SELF_EVOLUTION.value:
        if domain_availability["evolution"] and mode_availability[AgentMode.SELF_EVOLUTION.value]:
            return "/self-evolution"
    elif default_mode == AgentMode.SUPERVISED_EVOLUTION.value:
        if domain_availability["evolution"] and mode_availability[AgentMode.SUPERVISED_EVOLUTION.value]:
            return "/supervised-evolution"

    if domain_availability["chat"] and mode_availability[AgentMode.CHAT.value]:
        return "/chat"
    if domain_availability["evolution"] and mode_availability[AgentMode.SUPERVISED_EVOLUTION.value]:
        return "/supervised-evolution"
    if domain_availability["evolution"] and mode_availability[AgentMode.SELF_EVOLUTION.value]:
        return "/self-evolution"
    return "/config"


def get_workbench_contract(public_config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the frontend-facing workbench defaults and availability contract."""

    if public_config is None:
        public_config = load_public_config()
    effective = build_effective_config(public_config)
    mode_availability = _mode_availability(effective)
    domain_availability = _domain_availability(effective, mode_availability)
    default_mode = _resolve_default_mode(effective, mode_availability, domain_availability)
    intake_mode = str(getattr(getattr(effective, "evolution", None), "intake_mode", "manual_review") or "manual_review")

    return {
        "defaultMode": default_mode,
        "defaultRoute": _default_route(default_mode, mode_availability, domain_availability),
        "intakeMode": intake_mode,
        "modeAvailability": mode_availability,
        "domainAvailability": domain_availability,
    }
