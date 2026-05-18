#!/usr/bin/env python3
"""
配置去敏与环境变量优先级测试
"""

from pathlib import Path

from config import ConfigLoader, Settings


PROJECT_ROOT = Path(__file__).parent.parent


def _clear_provider_env(monkeypatch):
    for name in [
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "DEEPSEEK_API_KEY",
        "DASHSCOPE_API_KEY",
        "ZHIPU_API_KEY",
        "GOOGLE_API_KEY",
        "SILICONFLOW_API_KEY",
        "GROQ_API_KEY",
        "MINIMAX_API_KEY",
        "MINIMAX2_7_API_KEY",
        "minimax2.7",
        "AGENT_LLM_PROVIDER",
        "AGENT_LLM__PROVIDERS__DEFAULT__KIND",
        "VIBELUTION_ENABLE_USER_ENV_FALLBACK",
        "VIBELUTION_LLM_REMOTE_MAIN_MINIMAX_M2_7_API_KEY",
        "VIBELUTION_LLM_DEEPSEEK_V4_PRO_API_KEY",
    ]:
        monkeypatch.delenv(name, raising=False)


def _minimal_remote_llm_toml(provider_kind: str, base_url: str, model: str, api_key_env: str) -> str:
    return f"""
[llm.providers.default]
kind = "{provider_kind}"
api_key = ""
api_key_env = "{api_key_env}"
base_url = "{base_url}"

[llm.profiles.primary]
provider_id = "default"
model = "{model}"
""".strip()


def test_tracked_config_has_no_real_api_key():
    content = (PROJECT_ROOT / "config.toml").read_text(encoding="utf-8")
    assert 'api_key = "' not in content
    assert "sk-cp-" not in content


def test_example_config_uses_placeholders_only():
    content = (PROJECT_ROOT / "config.example.toml").read_text(encoding="utf-8")
    assert 'api_key = "' not in content
    assert "your-api-key" not in content
    assert "sk-cp-" not in content


def test_env_overrides_toml_for_api_key(tmp_path, monkeypatch):
    _clear_provider_env(monkeypatch)
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        _minimal_remote_llm_toml(
            provider_kind="minimax",
            base_url="https://api.minimaxi.com/v1",
            model="MiniMax-M2.7",
            api_key_env="MINIMAX_API_KEY",
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("MINIMAX_API_KEY", "env-test-key")

    config = ConfigLoader(str(config_file)).load()

    assert config.llm.get_provider(role="primary").api_key == "env-test-key"


def test_env_overrides_toml_for_non_secret_fields(tmp_path, monkeypatch):
    _clear_provider_env(monkeypatch)
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        _minimal_remote_llm_toml(
            provider_kind="aliyun",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model="qwen-plus",
            api_key_env="DASHSCOPE_API_KEY",
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("AGENT_LLM__PROVIDERS__DEFAULT__KIND", "local")

    config = ConfigLoader(str(config_file)).load()
    provider = config.llm.get_provider(role="primary")

    assert provider.kind == "local"


def test_provider_specific_env_key_does_not_leak_across_providers(tmp_path, monkeypatch):
    _clear_provider_env(monkeypatch)
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        _minimal_remote_llm_toml(
            provider_kind="minimax",
            base_url="https://api.minimaxi.com/v1",
            model="MiniMax-M2.7",
            api_key_env="MINIMAX_API_KEY",
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("DASHSCOPE_API_KEY", "dashscope-test-key")

    config = ConfigLoader(str(config_file)).load()

    assert config.llm.get_provider(role="primary").api_key == ""
    assert config.get_api_key() is None


def test_config_interfaces_resolve_minimax_key_consistently(tmp_path, monkeypatch):
    _clear_provider_env(monkeypatch)
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        _minimal_remote_llm_toml(
            provider_kind="minimax",
            base_url="https://api.minimaxi.com/v1",
            model="MiniMax-M2.7",
            api_key_env="MINIMAX_API_KEY",
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MINIMAX_API_KEY", "minimax-test-key")

    config = ConfigLoader(str(config_file)).load()
    settings = Settings(config_path=str(config_file))

    assert config.get_api_key() == "minimax-test-key"
    assert settings.get_api_key() == "minimax-test-key"


def test_model_library_api_key_env_takes_priority(tmp_path, monkeypatch):
    _clear_provider_env(monkeypatch)
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        """
[llm.providers.default]
kind = "minimax"
api_key = ""
api_key_env = "MINIMAX_API_KEY"
base_url = "https://api.minimaxi.com/v1"

[llm.profiles.primary]
provider_id = "default"
model = "MiniMax-M2.7"

[llm.model_library.primary_minimax]
provider_id = "default"
model = "MiniMax-M2.7"
label = "MiniMax"
api_key_env = "VIBELUTION_LLM_PRIMARY_MINIMAX_API_KEY"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("MINIMAX_API_KEY", "provider-key")
    monkeypatch.setenv("VIBELUTION_LLM_PRIMARY_MINIMAX_API_KEY", "model-key")

    config = ConfigLoader(str(config_file)).load()

    assert config.get_api_key() == "model-key"
    assert config.get_api_key_source_label() == "model-env:VIBELUTION_LLM_PRIMARY_MINIMAX_API_KEY"


def test_config_preserves_prompt_and_pet_sections(tmp_path, monkeypatch):
    _clear_provider_env(monkeypatch)
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        (
            _minimal_remote_llm_toml(
                provider_kind="minimax",
                base_url="https://api.minimaxi.com/v1",
                model="MiniMax-M2.7",
                api_key_env="MINIMAX_API_KEY",
            )
            + """

[pet.gene]
inherit_from_model = false

[prompt]
default_components = ["SOUL", "SPEC"]

[[prompt.sections]]
name = "SOUL"
path = "core/core_prompt/SOUL.md"
priority = 10
required = true
description = "identity"
"""
        ).strip(),
        encoding="utf-8",
    )

    loader_config = ConfigLoader(str(config_file)).load()
    settings_config = Settings(config_path=str(config_file)).config

    assert loader_config.pet_gene.inherit_from_model is False
    assert settings_config.pet_gene.inherit_from_model is False
    assert len(loader_config.prompt.sections) == 1
    assert len(settings_config.prompt.sections) == 1
    assert settings_config.prompt.default_components == ["SOUL", "SPEC"]


def test_legacy_llm_env_var_is_rejected(tmp_path, monkeypatch):
    _clear_provider_env(monkeypatch)
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        _minimal_remote_llm_toml(
            provider_kind="aliyun",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model="qwen-plus",
            api_key_env="DASHSCOPE_API_KEY",
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("AGENT_LLM_PROVIDER", "local")

    try:
        ConfigLoader(str(config_file)).load()
    except ValueError as exc:
        assert "Legacy LLM environment variables" in str(exc)
    else:
        raise AssertionError("expected ValueError")
