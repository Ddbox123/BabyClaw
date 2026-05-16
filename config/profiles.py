"""
稳定运行时配置档案

将“稳定运行基线”收敛为几个明确的 profile，
避免每次启动都依赖手工拼装参数。
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from .models import AppConfig, ProviderConfig, LLMProfile


VALID_RUNTIME_PROFILES = {"", "safe_local", "safe_remote", "debug", "ci"}


def _is_local_base_url(base_url: str) -> bool:
    parsed = urlparse(str(base_url or "").strip())
    return parsed.hostname in {"localhost", "127.0.0.1", "::1"}


def _find_local_profile_id(config: "AppConfig") -> str | None:
    for profile_id, profile in config.llm.profiles.items():
        try:
            provider = config.llm.get_provider(profile.provider_id)
        except ValueError:
            continue
        if provider.kind == "local" or _is_local_base_url(provider.base_url):
            return profile_id
    return None


def _overlay_profile(target: "LLMProfile", source: "LLMProfile") -> None:
    for key, value in source.model_dump().items():
        if key == "profile_id":
            continue
        setattr(target, key, copy.deepcopy(value))


def apply_runtime_profile(config: "AppConfig") -> "AppConfig":
    """根据 runtime.profile 对配置做受控覆写。"""
    profile = (getattr(config.runtime, "profile", "") or "").strip().lower()
    if not profile:
        return config

    if profile not in VALID_RUNTIME_PROFILES:
        raise ValueError(
            f"未知 runtime profile: {profile}。"
            f"可用值: {', '.join(sorted(p for p in VALID_RUNTIME_PROFILES if p))}"
        )

    if profile == "safe_local":
        primary = config.llm.get_profile(role="primary")
        local_template_id = _find_local_profile_id(config)
        if local_template_id and local_template_id != primary.profile_id:
            _overlay_profile(primary, config.llm.get_profile(local_template_id))
        provider = config.llm.get_provider(primary.provider_id)
        provider.kind = "local"
        if not _is_local_base_url(provider.base_url):
            provider.base_url = "http://localhost:11434/v1"
        provider.requires_api_key = False
        provider.api_key = ""
        provider.api_key_env = ""
        primary.temperature = 0.1
        primary.timeout = 45
        primary.connect_timeout = 5
        primary.discovery_enabled = False
        config.llm.discovery.enabled = False
        config.agent.max_iterations = min(config.agent.max_iterations, 40)
        config.agent.awake_interval = min(config.agent.awake_interval, 30)
        config.context_compression.enabled = True
        config.context_compression.max_token_limit = min(
            config.context_compression.max_token_limit, 24576
        )
        config.runtime.preflight_doctor = True
        config.runtime.require_venv = True
        return config

    if profile == "safe_remote":
        primary = config.llm.get_profile(role="primary")
        primary.temperature = max(primary.temperature, 0.1)
        primary.timeout = max(primary.timeout, 120)
        primary.connect_timeout = min(primary.connect_timeout, 20)
        config.llm.discovery.enabled = True
        config.agent.max_iterations = min(config.agent.max_iterations, 60)
        config.agent.awake_interval = min(config.agent.awake_interval, 60)
        config.context_compression.enabled = True
        config.runtime.preflight_doctor = True
        config.runtime.require_venv = True
        return config

    if profile == "debug":
        config.debug.enabled = True
        config.debug.verbose = True
        config.debug.trace_llm = True
        config.debug.trace_tools = True
        config.log.level = "DEBUG"
        config.agent.max_iterations = min(config.agent.max_iterations, 20)
        config.agent.awake_interval = min(config.agent.awake_interval, 15)
        config.runtime.preflight_doctor = True
        return config

    if profile == "ci":
        config.debug.enabled = False
        config.debug.verbose = False
        config.debug.trace_llm = False
        config.debug.trace_tools = False
        config.log.level = "WARNING"
        primary = config.llm.get_profile(role="primary")
        primary.temperature = max(primary.temperature, 0.1)
        config.llm.discovery.enabled = False
        config.agent.max_iterations = min(config.agent.max_iterations, 5)
        config.agent.awake_interval = min(config.agent.awake_interval, 5)
        config.agent.auto_backup = False
        config.context_compression.enabled = False
        config.runtime.preflight_doctor = True
        config.runtime.require_venv = True
        return config

    return config
