#!/usr/bin/env python3
"""
稳定运行档案测试
"""

from config import Settings
from config.profiles import apply_runtime_profile


def make_config(**kwargs):
    return Settings(None, **kwargs).config


def test_safe_local_profile_applies_local_guardrails():
    baseline = make_config()
    config = make_config(runtime__profile="safe_local")
    primary = config.llm.get_profile(role="primary")
    provider = config.llm.get_provider(primary.provider_id)
    local_template = next(
        (
            profile
            for profile in baseline.llm.profiles.values()
            if baseline.llm.get_provider(profile.provider_id).kind == "local"
        ),
        None,
    )
    expected_model = local_template.model if local_template else baseline.llm.get_profile(role="primary").model

    assert config.runtime.profile == "safe_local"
    assert config.llm.get_role_profile_id("primary") == "primary"
    assert provider.kind == "local"
    assert provider.base_url.startswith("http://localhost")
    assert provider.requires_api_key is False
    assert primary.model == expected_model
    assert primary.temperature == 0.1
    assert primary.timeout == 45
    assert primary.connect_timeout == 5
    assert config.llm.discovery.enabled is False
    assert config.agent.max_iterations == 40
    assert config.agent.awake_interval == 30
    assert config.runtime.preflight_doctor is True


def test_safe_local_replaces_remote_base_url_when_no_local_profile():
    config = make_config(
        **{
            "llm.profiles.compression.provider_id": "remote_main",
            "llm.providers.local_main.kind": "minimax",
            "llm.providers.remote_main.kind": "minimax",
            "llm.providers.remote_main.base_url": "https://api.minimaxi.com/v1",
            "runtime.profile": "safe_local",
        }
    )
    primary = config.llm.get_profile(role="primary")
    provider = config.llm.get_provider(primary.provider_id)

    assert provider.kind == "local"
    assert provider.base_url == "http://localhost:11434/v1"
    assert provider.requires_api_key is False
    assert provider.api_key == ""
    assert provider.api_key_env == ""


def test_safe_remote_profile_applies_remote_guardrails():
    config = make_config(
        **{
            "llm.profiles.primary.provider_id": "remote_main",
            "llm.providers.remote_main.kind": "minimax",
            "llm.providers.remote_main.base_url": "https://api.minimaxi.com/v1",
            "llm.profiles.primary.model": "MiniMax-M2.7",
            "runtime.profile": "safe_remote",
        },
    )
    apply_runtime_profile(config)
    primary = config.llm.get_profile(role="primary")
    provider = config.llm.get_provider(primary.provider_id)

    assert config.runtime.profile == "safe_remote"
    assert provider.kind == "minimax"
    assert primary.timeout == 120
    assert primary.connect_timeout == 20
    assert config.llm.discovery.enabled is True
    assert config.agent.max_iterations == 60


def test_debug_profile_enables_debug_tracing():
    config = make_config(runtime__profile="debug")

    assert config.debug.enabled is True
    assert config.debug.verbose is True
    assert config.debug.trace_llm is True
    assert config.debug.trace_tools is True
    assert config.log.level == "DEBUG"
    assert config.runtime.preflight_doctor is True


def test_explicit_provider_override_can_escape_default_safe_remote_profile():
    config = make_config(
        **{
            "llm.profiles.primary.provider_id": "remote_main",
            "llm.providers.remote_main.kind": "local",
            "llm.providers.remote_main.api_key": "",
            "runtime.profile": "",
        },
    )
    provider = config.llm.get_provider(role="primary")

    assert config.runtime.profile == ""
    assert provider.kind == "local"


def test_ci_profile_disables_heavy_runtime_features():
    config = make_config(runtime__profile="ci")

    assert config.runtime.profile == "ci"
    assert config.llm.discovery.enabled is False
    assert config.context_compression.enabled is False
    assert config.agent.auto_backup is False
    assert config.agent.max_iterations == 5
    assert config.log.level == "WARNING"


def test_explicit_runtime_overrides_survive_profile_application():
    config = make_config(
        runtime__profile="safe_local",
        runtime__preflight_doctor=False,
        runtime__require_venv=False,
    )

    assert config.runtime.profile == "safe_local"
    assert config.runtime.preflight_doctor is False
    assert config.runtime.require_venv is False


def test_unknown_profile_raises_clear_error():
    config = make_config(runtime__profile="")
    config.runtime.profile = "mystery_mode"

    try:
        apply_runtime_profile(config)
    except ValueError as exc:
        assert "未知 runtime profile" in str(exc)
    else:
        raise AssertionError("expected ValueError")
