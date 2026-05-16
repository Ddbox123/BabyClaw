# -*- coding: utf-8 -*-
"""LLM 子系统核心类型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class LLMCapabilities:
    supports_streaming: bool = True
    supports_tool_calling: bool = True
    supports_parallel_tool_calls: bool = False
    supports_system_messages: bool = True
    supports_json_mode: bool = False
    supports_model_discovery: bool = True


@dataclass
class UsageStats:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    provider_raw_usage: Dict[str, Any] = field(default_factory=dict)
    estimated_cost: float = 0.0
    latency_ms: int = 0


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    raw_arguments: Any = None
    provider_payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ResolvedModelSpec:
    provider: str
    profile_id: str
    model: str
    transport: str
    contract: str
    context_window: int
    capabilities: LLMCapabilities
    discovery_status: str = "configured"
    max_output_tokens: int = 0
    reasoning_state_field: str = ""
    strict_compatibility: bool = True
    provider_details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DiagnosticReport:
    ok: bool
    provider: str
    profile_id: str
    model: str
    messages: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    resolved_spec: Optional[ResolvedModelSpec] = None


@dataclass
class StreamChunk:
    type: str
    text: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    usage: Optional[UsageStats] = None
    provider_payload: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


class LLMError(RuntimeError):
    """统一的 LLM 错误类型。"""

    def __init__(
        self,
        category: str,
        message: str,
        *,
        retryable: bool = False,
        provider: str = "",
        model: str = "",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.retryable = retryable
        self.provider = provider
        self.model = model
        self.details = details or {}
