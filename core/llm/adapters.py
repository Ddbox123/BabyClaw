# -*- coding: utf-8 -*-
"""Provider-specific LLM payload adaptation.

The rest of the agent keeps an internal OpenAI-like message/tool shape. This
module owns the narrower contract of translating that shape into the model
router/provider shape accepted by LiteLLM and provider APIs.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict, List
from urllib.parse import urlparse

from config import LLMProfile, ProviderConfig

from .schema import sanitize_tool_schema
from .streaming import LiteLLMStreamNormalizer
from .types import LLMCapabilities


_LITELLM_PROVIDER_PREFIXES = {
    "ai21",
    "aleph_alpha",
    "anthropic",
    "azure",
    "bedrock",
    "cohere",
    "deepseek",
    "fireworks_ai",
    "gemini",
    "groq",
    "huggingface",
    "mistral",
    "minimax",
    "ollama",
    "openai",
    "openrouter",
    "perplexity",
    "replicate",
    "together_ai",
    "vertex_ai",
    "voyage",
}

_NATIVE_LITELLM_PREFIX_BY_PROVIDER = {
    "anthropic": "anthropic",
    "deepseek": "deepseek",
    "groq": "groq",
    "minimax": "minimax",
    "ollama": "ollama",
    "openai": "openai",
}

_OPENAI_COMPAT_PROVIDER_KINDS = {
    "aliyun",
    "local",
    "openai_compatible",
    "siliconflow",
    "zhipu",
}


def _is_litellm_provider_qualified(model: str) -> bool:
    prefix, separator, _ = str(model or "").partition("/")
    return bool(separator and prefix.strip().lower() in _LITELLM_PROVIDER_PREFIXES)


class ProviderAdapter:
    """Base adapter for provider/model specific payload quirks."""

    preserves_structured_content = False
    preserves_reasoning_content = False

    def __init__(self, provider: ProviderConfig, profile: LLMProfile) -> None:
        self.provider = provider
        self.profile = profile
        self.kind = str(provider.kind or "").strip().lower()
        self.compat_mode = str(provider.compat_mode or "").strip().lower()

    def litellm_model_name(self) -> str:
        raw_model = str(self.profile.model or "").strip()
        if not raw_model or _is_litellm_provider_qualified(raw_model):
            return raw_model

        prefix = self._litellm_provider_prefix()
        if prefix:
            return f"{prefix}/{raw_model}"
        return raw_model

    def _litellm_provider_prefix(self) -> str:
        if self.kind in _OPENAI_COMPAT_PROVIDER_KINDS:
            return "openai"
        if self.kind in _NATIVE_LITELLM_PREFIX_BY_PROVIDER:
            return _NATIVE_LITELLM_PREFIX_BY_PROVIDER[self.kind]
        if self.compat_mode == "openai" and self.kind not in {"azure"}:
            return "openai"
        return ""

    def messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return messages

    def capabilities(self, base: LLMCapabilities) -> LLMCapabilities:
        return base

    def sanitize_tool_schema(self, tool_schema: Dict[str, Any]) -> Dict[str, Any]:
        return sanitize_tool_schema(tool_schema)

    def stream_normalizer(self) -> LiteLLMStreamNormalizer:
        return LiteLLMStreamNormalizer()

    def should_preserve_reasoning_content(self) -> bool:
        if self.preserves_reasoning_content:
            return True
        host = urlparse(str(self.provider.base_url or "").strip()).hostname or ""
        return "deepseek.com" in host.lower()


class OpenAICompatibleAdapter(ProviderAdapter):
    """Adapter for OpenAI-compatible HTTP endpoints."""

    def _litellm_provider_prefix(self) -> str:
        if self.kind == "minimax":
            return "minimax"
        return "openai"


class MiniMaxAdapter(ProviderAdapter):
    """MiniMax's chat endpoint expects only the first system message as system."""

    def _litellm_provider_prefix(self) -> str:
        return "minimax"

    def messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        seen_system = False
        for item in messages:
            message = dict(item)
            if message.get("role") == "system":
                if seen_system:
                    message["role"] = "user"
                else:
                    seen_system = True
            normalized.append(message)
        return normalized

    def capabilities(self, base: LLMCapabilities) -> LLMCapabilities:
        return replace(
            base,
            supports_json_mode=False,
            supports_parallel_tool_calls=False,
        )


class AnthropicAdapter(ProviderAdapter):
    """Native Anthropic routing can preserve structured content blocks."""

    preserves_structured_content = True

    def _litellm_provider_prefix(self) -> str:
        return "anthropic"

    def capabilities(self, base: LLMCapabilities) -> LLMCapabilities:
        return replace(base, supports_json_mode=True)


class DeepSeekAdapter(ProviderAdapter):
    """DeepSeek thinking mode requires round-tripping reasoning_content."""

    preserves_reasoning_content = True

    def _litellm_provider_prefix(self) -> str:
        return "deepseek"


def get_provider_adapter(provider: ProviderConfig, profile: LLMProfile) -> ProviderAdapter:
    kind = str(provider.kind or "").strip().lower()
    compat_mode = str(provider.compat_mode or "").strip().lower()
    if kind == "minimax":
        return MiniMaxAdapter(provider, profile)
    if kind == "anthropic":
        return AnthropicAdapter(provider, profile)
    if kind == "deepseek":
        return DeepSeekAdapter(provider, profile)
    if kind in _NATIVE_LITELLM_PREFIX_BY_PROVIDER:
        return ProviderAdapter(provider, profile)
    if kind in _OPENAI_COMPAT_PROVIDER_KINDS or compat_mode in {"openai", "openai_compatible"}:
        return OpenAICompatibleAdapter(provider, profile)
    return ProviderAdapter(provider, profile)


def capabilities_for_adapter(
    provider: ProviderConfig,
    profile: LLMProfile,
    base: LLMCapabilities,
) -> LLMCapabilities:
    adapter = get_provider_adapter(provider, profile)
    capabilities = adapter.capabilities(base)
    if not profile.streaming:
        capabilities = replace(capabilities, supports_streaming=False)
    if profile.tool_calling_mode == "disabled":
        capabilities = replace(
            capabilities,
            supports_tool_calling=False,
            supports_parallel_tool_calls=False,
        )
    elif profile.tool_calling_mode != "parallel":
        capabilities = replace(capabilities, supports_parallel_tool_calls=False)
    return capabilities
