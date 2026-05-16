# -*- coding: utf-8 -*-
"""Profile routing helpers for LLM recovery."""

from __future__ import annotations

from dataclasses import replace
from typing import Optional

from config import AppConfig

from .recovery import LLMRecoveryDecision


def attach_recovery_fallback(
    decision: LLMRecoveryDecision,
    *,
    config: Optional[AppConfig],
    role: str = "primary",
    current_profile_id: Optional[str] = None,
) -> LLMRecoveryDecision:
    if config is None:
        return decision
    fallback = select_recovery_profile(
        config,
        role=role,
        current_profile_id=current_profile_id,
        action=decision.action,
    )
    if not fallback:
        return decision
    return replace(decision, fallback_profile_id=fallback)


def select_recovery_profile(
    config: AppConfig,
    *,
    role: str = "primary",
    current_profile_id: Optional[str] = None,
    action: str,
) -> Optional[str]:
    llm_config = config.llm
    current_id = current_profile_id or llm_config.get_role_profile_id(role)
    current_profile = llm_config.get_profile(current_id)
    current_provider = llm_config.get_provider(current_profile.provider_id)

    candidates = []
    for profile_id, profile in llm_config.profiles.items():
        if profile_id == current_id:
            continue
        try:
            provider = llm_config.get_provider(profile.provider_id)
        except Exception:
            continue
        if provider.requires_api_key and not config.get_api_key_for_profile(profile_id=profile_id):
            continue
        score = _score_candidate(
            action=action,
            profile=profile,
            provider=provider,
            current_profile=current_profile,
            current_provider=current_provider,
        )
        if score <= 0:
            continue
        candidates.append((score, profile_id))

    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return candidates[0][1]


def _score_candidate(
    *,
    action: str,
    profile,
    provider,
    current_profile,
    current_provider,
) -> int:
    score = 1
    if provider.provider_id != current_provider.provider_id:
        score += 2
    if profile.profile_id.startswith("fallback"):
        score += 1

    if action in {"disable_tools", "disable_tools_and_retry_without_streaming"}:
        if profile.tool_calling_mode == "disabled":
            score += 5
        if not profile.streaming:
            score += 3
        return score

    if action == "retry_without_streaming":
        if not profile.streaming:
            score += 5
        return score

    if action == "compress_context":
        context_window = int(provider.context_window or 0)
        if context_window <= int(current_provider.context_window or 0):
            return 0
        score += 5 + min(context_window // 1000, 1000)
        return score

    if action in {"retry_with_backoff", "retry_after_backoff"}:
        if provider.provider_id == current_provider.provider_id:
            return 0
        return score

    return 0


__all__ = ["attach_recovery_fallback", "select_recovery_profile"]
