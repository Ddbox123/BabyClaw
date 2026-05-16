# -*- coding: utf-8 -*-
"""LLM profile discovery and diagnostics."""

from __future__ import annotations

from config import AppConfig

from .adapters import capabilities_for_adapter
from .types import DiagnosticReport, LLMCapabilities, ResolvedModelSpec


KNOWN_CONTEXT_WINDOWS = {
    "minimax-m2.7": 204800,
    "gpt-4o": 128000,
    "gpt-4-turbo": 128000,
    "claude-3-5-sonnet": 200000,
    "deepseek-chat": 65536,
    "qwen-plus": 131072,
    "qwen-max": 131072,
    "qwen-32b-awq": 65536,
}

JSON_MODE_MODEL_HINTS = (
    "gpt-4",
    "gpt-4o",
    "gpt-5",
    "deepseek",
    "qwen",
    "claude",
)
SUPPORTED_REASONING_STATE_FIELDS = {"reasoning_content"}


def _lookup_context_window(model_name: str, fallback: int) -> int:
    normalized = (model_name or "").strip().lower()
    for key, value in KNOWN_CONTEXT_WINDOWS.items():
        if key in normalized:
            return value
    return int(fallback or 32768)


def _base_capabilities_for_model(profile, provider) -> LLMCapabilities:
    model_name = str(profile.model or "").lower()
    provider_kind = str(provider.kind or "").lower()
    supports_json_mode = any(hint in model_name for hint in JSON_MODE_MODEL_HINTS)
    if provider_kind in {"local", "openai_compatible"} and profile.tool_calling_mode == "auto":
        supports_json_mode = False
    return LLMCapabilities(
        supports_streaming=bool(profile.streaming),
        supports_tool_calling=profile.tool_calling_mode != "disabled",
        supports_parallel_tool_calls=profile.tool_calling_mode == "parallel",
        supports_system_messages=True,
        supports_json_mode=supports_json_mode,
        supports_model_discovery=bool(profile.discovery_enabled),
    )


def discover_model(config: AppConfig, profile_id: str) -> ResolvedModelSpec:
    profile = config.llm.get_profile(profile_id)
    provider = config.llm.get_provider(profile.provider_id)
    base_capabilities = _base_capabilities_for_model(profile, provider)
    capabilities = capabilities_for_adapter(provider, profile, base_capabilities)
    context_window = _lookup_context_window(profile.model, provider.context_window)
    return ResolvedModelSpec(
        provider=provider.kind,
        profile_id=profile.profile_id,
        model=profile.model,
        transport=profile.transport,
        contract=profile.contract,
        context_window=context_window,
        capabilities=capabilities,
        discovery_status="configured",
        max_output_tokens=int(profile.max_output_tokens or 0),
        reasoning_state_field=profile.reasoning_state_field,
        strict_compatibility=bool(profile.strict_compatibility),
        provider_details={"provider_id": provider.provider_id, "base_url": provider.base_url},
    )


def _compatibility_issues(profile, provider) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    transport = str(profile.transport or "chat_completions").strip().lower()
    contract = str(profile.contract or "tool_chat").strip().lower()
    tool_mode = str(profile.tool_calling_mode or "auto").strip().lower()
    reasoning_state_field = str(profile.reasoning_state_field or "").strip()
    provider_kind = str(provider.kind or "").strip().lower()
    compat_mode = str(provider.compat_mode or "").strip().lower()

    if transport == "responses":
        errors.append("当前版本尚未启用 responses transport；请改用 chat_completions")

    if contract == "responses_agent":
        errors.append("当前版本尚未启用 responses_agent 合同；请改用 tool_chat 或 reasoning_chat")

    if contract == "basic_chat":
        if tool_mode != "disabled":
            errors.append("basic_chat 要求 tool_calling_mode=disabled")
        if reasoning_state_field:
            warnings.append("basic_chat 不需要 reasoning_state_field，建议留空")

    if contract == "tool_chat":
        if transport != "chat_completions":
            errors.append("tool_chat 目前只支持 chat_completions transport")
        if tool_mode == "disabled":
            errors.append("tool_chat 要求启用 tool calling，tool_calling_mode 不能为 disabled")

    if contract == "reasoning_chat":
        if transport != "chat_completions":
            errors.append("reasoning_chat 目前只支持 chat_completions transport")
        if tool_mode == "disabled":
            errors.append("reasoning_chat 要求启用 tool calling，tool_calling_mode 不能为 disabled")
        if reasoning_state_field not in SUPPORTED_REASONING_STATE_FIELDS:
            errors.append(
                "reasoning_chat 需要受支持的 reasoning_state_field；当前仅支持 reasoning_content"
            )
        if provider_kind == "anthropic":
            errors.append("anthropic provider 当前未接入 reasoning_chat 回放合同")

    if not compat_mode and provider_kind != "anthropic":
        warnings.append("provider 未声明 compat_mode，建议显式设置以减少切换歧义")

    if provider_kind == "local" and contract in {"tool_chat", "reasoning_chat"}:
        warnings.append("local provider 的高级协议兼容性依赖具体服务实现，保存后建议先做连接测试")

    return errors, warnings


def doctor_llm_profile(config: AppConfig, profile_id: str) -> DiagnosticReport:
    profile = config.llm.get_profile(profile_id)
    provider = config.llm.get_provider(profile.provider_id)
    errors = []
    warnings = []
    if provider.requires_api_key and not config.get_api_key_for_profile(profile_id=profile_id):
        errors.append(f"provider `{provider.provider_id}` 缺少 API Key")
    if not provider.base_url:
        warnings.append(f"provider `{provider.provider_id}` 未设置 base_url")
    spec = discover_model(config, profile_id)
    compat_errors, compat_warnings = _compatibility_issues(profile, provider)
    errors.extend(compat_errors)
    warnings.extend(compat_warnings)
    return DiagnosticReport(
        ok=not errors,
        provider=provider.kind,
        profile_id=profile.profile_id,
        model=profile.model,
        messages=[
            (
                f"{profile.profile_id} -> {provider.provider_id}:{profile.model} "
                f"[{profile.transport}/{profile.contract}]"
            )
        ],
        warnings=warnings,
        errors=errors,
        resolved_spec=spec,
    )


def assert_llm_compatibility(config: AppConfig) -> AppConfig:
    issues: list[str] = []
    for profile_id, profile in config.llm.profiles.items():
        provider = config.llm.get_provider(profile.provider_id)
        errors, _warnings = _compatibility_issues(profile, provider)
        if errors and bool(getattr(profile, "strict_compatibility", True)):
            issues.extend(f"[{profile_id}] {item}" for item in errors)
    if issues:
        raise ValueError("LLM 兼容性校验失败:\n- " + "\n- ".join(issues))
    return config
