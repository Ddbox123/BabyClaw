# -*- coding: utf-8 -*-
"""统一 LLM 子系统。"""

from .client import LLMClient, get_llm_client, list_profiles
from .discovery import assert_llm_compatibility, discover_model, doctor_llm_profile
from .errors import classify_exception
from .recovery import LLMRecoveryDecision, plan_recovery
from .routing import attach_recovery_fallback, select_recovery_profile
from .types import (
    DiagnosticReport,
    LLMCapabilities,
    LLMError,
    ResolvedModelSpec,
    StreamChunk,
    ToolCall,
    UsageStats,
)

__all__ = [
    "DiagnosticReport",
    "LLMCapabilities",
    "LLMClient",
    "LLMError",
    "LLMRecoveryDecision",
    "ResolvedModelSpec",
    "StreamChunk",
    "ToolCall",
    "UsageStats",
    "classify_exception",
    "assert_llm_compatibility",
    "discover_model",
    "doctor_llm_profile",
    "get_llm_client",
    "list_profiles",
    "plan_recovery",
    "attach_recovery_fallback",
    "select_recovery_profile",
]
