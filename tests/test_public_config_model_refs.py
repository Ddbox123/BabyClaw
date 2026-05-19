#!/usr/bin/env python3
"""
LLM 模型模板引用结构测试
"""

from pathlib import Path

from config import ConfigLoader
from config.public_config import UNCONFIGURED_MODEL_REF, build_effective_config, delete_llm_model, load_public_config


PROJECT_ROOT = Path(__file__).parent.parent


def test_build_effective_config_resolves_model_ref_and_overrides():
    public_config = load_public_config()
    public_config["llm"]["profiles"]["primary"] = {
        "model_ref": "openai_gpt_5_5",
        "overrides": {
            "temperature": 0.25,
            "max_output_tokens": 64000,
        },
    }

    effective = build_effective_config(public_config)
    profile = effective.llm.get_profile("primary")
    provider = effective.llm.get_provider(profile.provider_id)

    assert provider.kind == "openai"
    assert provider.base_url == "https://api.openai.com/v1"
    assert profile.model == "gpt-5.5"
    assert profile.temperature == 0.25
    assert profile.max_output_tokens == 64000
    assert profile.timeout == 120


def test_config_loader_accepts_model_ref_toml(tmp_path):
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        """
[llm.model_library.openai_gpt_5_5]
model = "gpt-5.5"
label = "OpenAI GPT-5.5"
api_key_env = "VIBELUTION_LLM_OPENAI_GPT_5_5_API_KEY"
transport = "chat_completions"
contract = "tool_chat"
temperature = 0.7
max_output_tokens = 128000
timeout = 120
connect_timeout = 20
streaming = true
tool_calling_mode = "auto"
discovery_enabled = true

[llm.model_library.openai_gpt_5_5.provider]
kind = "openai"
api_key_env = "OPENAI_API_KEY"
base_url = "https://api.openai.com/v1"
compat_mode = "openai"
requires_api_key = true
context_window = 1050000

[llm.profiles.primary]
model_ref = "openai_gpt_5_5"

[llm.profiles.primary.overrides]
temperature = 0.2
max_output_tokens = 32000
""".strip(),
        encoding="utf-8",
    )

    config = ConfigLoader(str(config_file)).load()
    profile = config.llm.get_profile("primary")
    provider = config.llm.get_provider(profile.provider_id)

    assert provider.kind == "openai"
    assert profile.model == "gpt-5.5"
    assert profile.temperature == 0.2
    assert profile.max_output_tokens == 32000


def test_delete_llm_model_marks_model_ref_profiles_unconfigured():
    public_config = load_public_config()
    public_config["llm"]["profiles"]["primary"] = {
        "model_ref": "openai_gpt_5_5",
        "overrides": {"temperature": 0.3},
    }
    public_config["llm"]["profiles"]["mental_model"] = {
        "model_ref": "openai_gpt_5_5",
        "overrides": {"temperature": 0.4},
    }

    deleted = delete_llm_model(public_config, "openai_gpt_5_5")

    assert deleted["llm"]["profiles"]["primary"]["model_ref"] == UNCONFIGURED_MODEL_REF
    assert deleted["llm"]["profiles"]["primary"]["overrides"] == {}
    assert deleted["llm"]["profiles"]["mental_model"]["model_ref"] == UNCONFIGURED_MODEL_REF
    assert deleted["llm"]["profiles"]["mental_model"]["overrides"] == {}
