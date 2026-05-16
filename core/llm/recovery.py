# -*- coding: utf-8 -*-
"""Recovery policy for normalized LLM failures."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .errors import classify_exception
from .types import LLMError


@dataclass(frozen=True)
class LLMRecoveryDecision:
    category: str
    retryable: bool
    action: str
    user_message: str
    wait_seconds: int = 0
    stop_current_turn: bool = False
    disable_streaming: bool = False
    disable_tools: bool = False
    request_context_compression: bool = False
    fallback_profile_id: Optional[str] = None


def plan_recovery(
    exc: Exception,
    *,
    attempt: int = 1,
    max_attempts: int = 5,
) -> LLMRecoveryDecision:
    error = classify_exception(exc)
    action = _action_for_category(error.category)
    wait_seconds = _retry_wait_seconds(error, attempt, max_attempts)
    return LLMRecoveryDecision(
        category=error.category,
        retryable=error.retryable,
        action=action,
        user_message=str(error),
        wait_seconds=wait_seconds,
        stop_current_turn=_should_stop_current_turn(error, attempt, max_attempts),
        disable_streaming=error.category in {"empty_content_error", "tool_protocol_error"},
        disable_tools=error.category in {"tool_protocol_error", "capability_error"},
        request_context_compression=error.category == "context_length_error",
    )


def _action_for_category(category: str) -> str:
    return {
        "network_error": "retry_with_backoff",
        "timeout": "retry_with_backoff",
        "server_error": "retry_with_backoff",
        "rate_limit": "retry_after_backoff",
        "context_length_error": "compress_context",
        "tool_protocol_error": "disable_tools_and_retry_without_streaming",
        "empty_content_error": "retry_without_streaming",
        "capability_error": "disable_tools",
        "quota_error": "fail_fast",
        "auth_error": "fail_fast",
        "configuration_error": "fail_fast",
        "provider_protocol_error": "fail_fast",
        "user_interrupt": "stop",
    }.get(category, "fail_fast")


def _retry_wait_seconds(error: LLMError, attempt: int, max_attempts: int) -> int:
    if not error.retryable or attempt >= max_attempts:
        return 0
    if error.category == "rate_limit":
        return min(10 * max(attempt, 1), 60)
    return min(2 ** max(attempt, 1), 30)


def _should_stop_current_turn(error: LLMError, attempt: int, max_attempts: int) -> bool:
    if error.category in {"user_interrupt", "auth_error", "quota_error", "configuration_error"}:
        return True
    if error.category in {"context_length_error", "tool_protocol_error", "empty_content_error", "capability_error"}:
        return False
    if not error.retryable:
        return True
    return attempt >= max_attempts


__all__ = ["LLMRecoveryDecision", "plan_recovery"]
