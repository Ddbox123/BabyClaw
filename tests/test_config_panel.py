#!/usr/bin/env python3
"""
配置面板测试
"""

import json
import os
import tomllib
from pathlib import Path

import pytest

from config.toml_writer import dumps_public_config
from scripts.config_panel import (
    HEADER_LINES,
    add_llm_model,
    apply_llm_model_preset,
    build_effective_config,
    delete_llm_model,
    get_config_language,
    load_public_config,
    list_llm_model_preset_options,
    list_llm_model_options,
    localize_label,
    localize_section_label,
    add_llm_profile,
    preserve_secret_blanks,
    render_panel_html,
    save_public_config,
    _delete_user_env_var,
    _set_user_env_var,
    test_llm_connection as run_llm_connection_test,
    update_llm_model,
    set_llm_model_api_key,
    clear_llm_model_api_key,
)


PROJECT_ROOT = Path(__file__).parent.parent


def _iter_panel_editable_paths(node, prefix=""):
    if isinstance(node, dict):
        for key, value in node.items():
            path = f"{prefix}.{key}" if prefix else key
            yield from _iter_panel_editable_paths(value, path)
        return

    if isinstance(node, list):
        if all(isinstance(item, str) for item in node):
            yield prefix
            return
        for index, item in enumerate(node):
            yield from _iter_panel_editable_paths(item, f"{prefix}.{index}")
        return

    yield prefix


def _get_path(node, path):
    current = node
    for part in path.split("."):
        if isinstance(current, list):
            current = current[int(part)]
        else:
            current = current[part]
    return current


def _set_path(node, path, value):
    current = node
    parts = path.split(".")
    for part in parts[:-1]:
        if isinstance(current, list):
            current = current[int(part)]
        else:
            current = current[part]
    last = parts[-1]
    if isinstance(current, list):
        current[int(last)] = value
    else:
        current[last] = value


def _configured_test_value(path, value, root_config):
    if isinstance(value, bool):
        return not value
    if isinstance(value, int) and not isinstance(value, bool):
        if path.endswith("summary_max_chars"):
            return value - 1 if value >= 1000 else value + 1
        return value + 1
    if isinstance(value, float):
        return value / 2 if value >= 1 else value + 0.01
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return [*value, "CONFIG_TEST_VALUE"]
    if isinstance(value, str):
        if path == "ui.language":
            return "en" if value != "en" else "zh"
        if path in {"avatar.preset", "ui.theme"}:
            return "cat" if value != "cat" else "moose"
        if path == "runtime.profile":
            return "debug" if value != "debug" else "ci"
        if path == "log.level":
            return "DEBUG" if value != "DEBUG" else "INFO"
        if path.endswith(".provider_id"):
            providers = root_config.get("llm", {}).get("providers", {})
            return "local_main" if "local_main" in providers else next(iter(providers), value)
        if path.endswith(".kind"):
            return "local" if value != "local" else "minimax"
        if path.endswith(".compat_mode"):
            return "native" if value != "native" else "openai"
        if path.endswith(".api_key"):
            return "CONFIG_TEST_SECRET"
        if path.endswith(".api_key_env"):
            return "CONFIG_TEST_API_KEY"
        if path.endswith(".base_url") or path.endswith(".url"):
            return "http://127.0.0.1:9999/v1"
        return f"{value}_CONFIG_TEST" if value else "CONFIG_TEST_VALUE"
    return value


def test_render_panel_html_contains_diagnostics():
    public_config = load_public_config()
    html = render_panel_html(public_config, lang="zh")

    assert "Vibelution 配置面板" in html
    assert "配置诊断" in html
    assert "保存到 config.toml" in html
    assert "运行时" in html
    assert "界面语言" in html
    assert "模型服务" in html
    assert "模型档案" in html
    assert "角色绑定" not in html
    assert "服务提供方:" in html
    assert "模型:" in html
    assert "密钥来源" in html
    assert 'id="toast-stack"' in html
    assert 'value="secret-key"' not in html


def test_render_panel_html_uses_consistent_chinese_llm_terms():
    public_config = load_public_config()
    html = render_panel_html(public_config, lang="zh")

    assert "Providers" not in html
    assert "Profiles" not in html
    assert "Role Bindings" not in html
    assert "Provider 类型" not in html
    assert "Provider 绑定" not in html
    assert "最大输出 Tokens" not in html
    assert "主 Agent Profile" not in html
    assert "服务类型" in html
    assert "模型服务绑定" in html
    assert "最大输出令牌数" in html
    assert "模型档案" in html
    assert "主智能体" in html


def test_render_panel_html_supports_english():
    public_config = load_public_config()
    html = render_panel_html(public_config, lang="en")

    assert "Vibelution Config Panel" in html
    assert "Configuration Diagnostics" in html
    assert "Save to config.toml" in html
    assert "Runtime" in html
    assert "Interface Language" in html
    assert "Providers" in html
    assert 'option value="en" selected' in html


def test_render_panel_html_renders_language_as_select():
    public_config = load_public_config()
    html = render_panel_html(public_config, lang="zh")

    assert 'data-path="ui.language"' in html
    assert "syncLanguageControls(this.value, 'body')" in html
    assert 'option value="zh" selected' in html
    assert 'option value="en"' in html


def test_render_panel_html_renders_controlled_selects():
    public_config = load_public_config()
    html = render_panel_html(public_config, lang="zh")

    assert 'data-path="runtime.profile"' in html
    assert 'option value="safe_remote" selected' in html
    assert 'data-path="llm.providers.remote_main.kind"' in html
    assert 'value="minimax"' in html
    assert 'data-path="avatar.preset"' in html
    assert 'option value="moose" selected' in html
    assert 'onclick="editConfigCard(this)"' in html
    assert 'onclick="saveConfigCard(this)"' in html
    assert 'onclick="editConfigField(this)"' not in html
    assert 'onclick="saveConfigField(this)"' not in html
    assert 'class="field-editor" hidden' in html
    assert 'data-original-value=' in html


def test_render_panel_html_uses_one_edit_button_per_collapsible_card():
    public_config = load_public_config()
    html = render_panel_html(public_config, lang="zh")

    assert html.count('onclick="editConfigCard(this)"') == html.count('data-collapsible-card="true"')
    remote_start = html.index('id="card-content-llm-providers-remote-main"')
    remote_end = html.index('id="card-content-llm-providers-local-main"', remote_start)
    remote_html = html[remote_start:remote_end]
    assert 'onclick="editConfigField(this)"' not in remote_html


def test_render_panel_html_keeps_api_key_env_editable():
    public_config = load_public_config()
    html = render_panel_html(public_config, lang="zh")

    assert 'data-path="llm.providers.remote_main.api_key_env"' in html
    assert 'value="MINIMAX_API_KEY"' in html
    assert '<input type="password" data-path="llm.providers.remote_main.api_key_env"' not in html


def test_render_panel_html_uses_left_nav_as_single_page_switcher():
    public_config = load_public_config()
    html = render_panel_html(public_config, lang="zh")

    assert html.count('data-config-page=') == len(public_config) + 2
    assert html.count('data-config-nav=') == len(public_config) + 2
    assert html.count('class="panel-section config-page') == len(public_config) + 2
    assert html.count('class="panel-section config-page is-active"') == 1
    assert html.count('class="section-content"') == len(public_config) + 1
    assert 'data-config-page="overview"' in html
    assert "selectConfigPage(fromHash || \"overview\")" in html
    assert 'onclick="selectConfigPage(\'llm\'' in html
    assert "selectConfigPage" in html


def test_render_panel_html_refreshes_config_without_losing_current_page():
    public_config = load_public_config()
    html = render_panel_html(public_config, lang="zh")

    assert 'function activeConfigPageId(fallbackPageId = "overview")' in html
    assert 'nextUrl.hash = "section-" + resolvedPageId;' in html
    assert 'reloadConfigPage(lang, result.message, 500, pageId);' in html
    assert 'reloadConfigPage(lang, result.message, 700);' in html
    assert 'reloadConfigPage(lang);' in html


def test_render_panel_home_shows_effective_runtime_config():
    public_config = load_public_config()
    public_config["runtime"]["profile"] = "safe_local"

    html = render_panel_html(public_config, lang="zh")

    assert "实际生效配置" in html
    assert "主智能体" in html
    assert "local_main" in html
    assert "qwen-32b-awq" in html
    assert "http://localhost:8000/v1" in html
    assert "onclick=\"testSelectedLlm()\"" not in html
    assert "onclick=\"selectConfigPage('runtime')\"" in html


def test_render_panel_html_collapses_nested_cards_by_default():
    public_config = load_public_config()
    html = render_panel_html(public_config, lang="zh")

    assert 'data-collapsible-card="true"' in html
    assert 'class="card-content" id="card-content-llm-providers"' in html
    assert 'class="card-content" id="card-content-llm-providers-remote-main"' in html
    assert 'class="card-content" id="card-content-prompt-sections-0"' in html
    assert html.count('data-collapsible-card="true"') == html.count('class="card-content"')
    assert html.count('aria-controls="card-content-') == html.count('data-collapsible-card="true"')


def test_render_panel_html_exposes_every_public_config_parameter():
    public_config = load_public_config()
    html = render_panel_html(public_config, lang="zh")
    missing_paths = [
        path
        for path in _iter_panel_editable_paths(public_config)
        if not path.startswith("llm.model_library.")
        if f'data-path="{path}"' not in html
    ]

    assert missing_paths == []


def test_render_panel_html_toolbar_focuses_on_save_reload_and_language():
    public_config = load_public_config()
    html = render_panel_html(public_config, lang="zh")
    toolbar_start = html.index('<div class="toolbar">')
    toolbar_end = html.index("</div>", toolbar_start)
    toolbar_html = html[toolbar_start:toolbar_end]

    assert "语言" in toolbar_html
    assert "保存到 config.toml" in toolbar_html
    assert "重新加载" in toolbar_html
    assert 'id="llm-profile-switch"' not in html
    assert 'onclick="switchPrimaryLlm()"' not in html
    assert "复制方案" not in toolbar_html
    assert "测试连接" not in toolbar_html
    assert 'id="add-llm-profile-card"' in html
    assert 'class="inline-add-card" hidden' in html
    assert 'onclick="saveInlineLlmProfile()"' in html
    assert html.index('id="add-llm-profile-card"') > html.index('id="card-content-llm-profiles"')
    assert "/switch-llm" not in html
    assert "/add-llm-profile" in html


def test_render_panel_html_localizes_provider_and_profile_card_titles_in_zh():
    public_config = load_public_config()
    html = render_panel_html(public_config, lang="zh")

    assert '<span class="card-title">远程主服务</span>' in html
    assert '<span class="card-title">本地主服务</span>' in html
    assert '<span class="card-title">DeepSeek 主服务</span>' in html
    assert '<span class="card-title">主智能体</span>' in html
    assert '<span class="card-title">心智模型</span>' in html
    assert '<span class="card-title">执行子智能体</span>' in html
    assert '<span class="card-title">探索子智能体</span>' in html
    assert '<span class="card-title">监督基线</span>' in html
    assert '<span class="card-title">监督候选</span>' in html
    assert '<span class="card-title">压缩模型</span>' in html
    assert "无监督进化" in html
    assert "监督进化" in html
    assert ">remotemain<" not in html
    assert ">mental模型<" not in html
    assert ">subagentworker<" not in html


def test_render_panel_html_localizes_model_options_in_zh():
    public_config = load_public_config()
    html = render_panel_html(public_config, lang="zh")

    assert "MiniMax-M2.7 / MiniMax</option>" in html
    assert "DeepSeek V4 Pro / DeepSeek</option>" in html


def test_render_panel_html_adds_model_library_without_duplicate_role_prefixes():
    public_config = load_public_config()
    html = render_panel_html(public_config, lang="zh")
    models = list_llm_model_options(public_config)

    assert 'id="section-llm-model-library"' in html
    assert "通用模型库" in html
    assert "MiniMax-M2.7" in html
    assert "DeepSeek V4 Pro" in html
    assert 'onclick="editLlmModel(this)"' in html
    assert 'onclick="saveLlmModelEdit(this)"' in html
    assert 'id="add-llm-model-card"' in html
    assert 'onclick="saveInlineLlmModel()"' in html
    assert 'class="model-library-edit" hidden' in html
    assert 'data-edit-field="provider_id"' in html
    assert 'data-edit-field="temperature"' in html
    assert 'data-edit-field="api_key_env"' in html
    assert 'data-edit-api-key' in html
    assert 'data-clear-api-key' in html
    assert "VIBELUTION_LLM_REMOTE_MAIN_MINIMAX_M2_7_API_KEY" in html
    assert 'data-edit-field="max_output_tokens"' in html
    assert 'data-details="' in html
    assert "/update-llm-model" in html
    assert len(models) >= 2
    assert {"MiniMax-M2.7", "deepseek-v4-pro"}.issubset({item["model"] for item in models})
    assert not any(item["label"].startswith("primary /") for item in models)


def test_render_panel_html_includes_model_preset_templates():
    public_config = load_public_config()
    html = render_panel_html(public_config, lang="zh")
    presets = list_llm_model_preset_options()

    assert "预设模板" in html
    assert "data-add-model-preset" in html
    assert "applyLlmModelPreset(this.value)" in html
    assert "const LLM_MODEL_PRESETS" in html
    assert "openai_gpt_5_4" in html
    assert "local_openai_compatible" in html
    assert len(presets) >= 8


def test_apply_remote_model_preset_materializes_provider_and_model_library():
    public_config = load_public_config()
    public_config["llm"]["providers"].pop("openai_main", None)
    updated = apply_llm_model_preset(public_config, "openai_gpt_5_4")

    provider = updated["llm"]["providers"]["openai_main"]
    model = updated["llm"]["model_library"]["openai_gpt_5_4"]

    assert provider["kind"] == "openai"
    assert provider["api_key_env"] == "OPENAI_API_KEY"
    assert provider["requires_api_key"] is True
    assert model["provider_id"] == "openai_main"
    assert model["model"] == "gpt-5.4"
    assert model["transport"] == "chat_completions"
    assert model["contract"] == "tool_chat"
    assert model["max_output_tokens"] == 128000
    assert model["api_key_env"] == "VIBELUTION_LLM_OPENAI_GPT_5_4_API_KEY"
    assert "api_key" not in model
    build_effective_config(updated)


def test_model_preset_defaults_match_documented_provider_shapes():
    presets = {item["preset_id"]: item for item in list_llm_model_preset_options()}

    expected = {
        "openai_gpt_5_4": {
            "base_url": "https://api.openai.com/v1",
            "compat_mode": "openai",
            "model": "gpt-5.4",
            "context_window": 1047576,
        },
        "anthropic_claude_sonnet": {
            "base_url": "https://api.anthropic.com",
            "compat_mode": "native",
            "model": "claude-sonnet-4-6",
            "context_window": 200000,
        },
        "deepseek_v4_pro": {
            "base_url": "https://api.deepseek.com",
            "compat_mode": "openai",
            "model": "deepseek-v4-pro",
            "context_window": 131072,
        },
        "google_gemini_flash": {
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
            "compat_mode": "openai",
            "model": "gemini-3-flash-preview",
            "context_window": 1048576,
        },
        "minimax_m2_7": {
            "base_url": "https://api.minimax.io/v1",
            "compat_mode": "openai",
            "model": "MiniMax-M2.7",
            "context_window": 204800,
        },
        "dashscope_qwen3_6_plus": {
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "compat_mode": "openai",
            "model": "qwen3.6-plus",
            "context_window": 131072,
        },
        "siliconflow_glm_4_7": {
            "base_url": "https://api.siliconflow.cn/v1",
            "compat_mode": "openai",
            "model": "Pro/zai-org/GLM-4.7",
            "context_window": 131072,
        },
        "local_openai_compatible": {
            "base_url": "http://localhost:11434/v1/",
            "compat_mode": "openai",
            "model": "llama3.2",
            "context_window": 65536,
        },
    }

    assert set(expected).issubset(presets)
    for preset_id, values in expected.items():
        preset = presets[preset_id]
        provider = preset["provider"]
        model = preset["model"]
        assert provider["base_url"] == values["base_url"], preset_id
        assert provider["compat_mode"] == values["compat_mode"], preset_id
        assert provider["context_window"] == values["context_window"], preset_id
        assert model["model"] == values["model"], preset_id
        assert "api_key" not in provider
        assert "api_key" not in model


def test_apply_local_model_preset_does_not_require_api_key():
    public_config = load_public_config()
    updated = apply_llm_model_preset(public_config, "local_openai_compatible")

    provider = updated["llm"]["providers"]["local_main"]
    model = updated["llm"]["model_library"]["local_openai_compatible"]
    config = build_effective_config(updated)
    local_provider = config.llm.get_provider("local_main")

    assert provider["kind"] == "local"
    assert provider["base_url"] == "http://localhost:11434/v1/"
    assert provider["requires_api_key"] is False
    assert provider["api_key_env"] == ""
    assert model["provider_id"] == "local_main"
    assert model["model"] == "llama3.2"
    assert model["contract"] == "basic_chat"
    assert model["tool_calling_mode"] == "disabled"
    assert local_provider.kind == "local"
    assert local_provider.requires_api_key is False


def test_render_panel_html_avoids_browser_prompt_and_confirm_dialogs():
    public_config = load_public_config()
    html = render_panel_html(public_config, lang="zh")

    assert "window.prompt" not in html
    assert "window.confirm" not in html
    assert "async function testSelectedLlm()" not in html


def test_render_panel_html_keeps_provider_cards_focused_on_provider_config():
    public_config = load_public_config()
    html = render_panel_html(public_config, lang="zh")

    assert 'data-provider-actions=' not in html
    assert 'llm-provider-model-switch-' not in html


def test_render_panel_html_adds_profile_card_actions():
    public_config = load_public_config()
    html = render_panel_html(public_config, lang="zh")

    assert 'data-profile-actions="primary"' in html
    assert 'id="llm-model-switch-llm-profiles-primary"' in html
    assert 'data-profile-id="primary"' in html
    assert 'onclick="cloneLlmProfile(\'primary\', \'llm-model-switch-llm-profiles-primary\')"' in html
    assert 'onclick="applySelectedProfileModel(\'llm-model-switch-llm-profiles-primary\')"' in html
    assert 'onclick="testSelectedProfileModel(\'llm-model-switch-llm-profiles-primary\')"' in html
    assert "MiniMax-M2.7" in html
    assert "qwen-32b-awq" in html
    select_start = html.index('id="llm-model-switch-llm-profiles-primary"')
    select_end = html.index("</select>", select_start)
    assert 'option value="primary"' not in html[select_start:select_end]


def test_add_update_and_delete_llm_model_library_entry():
    public_config = load_public_config()
    updated = add_llm_model(public_config, "backup_remote", "remote_main", "MiniMax-M2.8", "MiniMax 备用")

    assert updated["llm"]["model_library"]["backup_remote"] == {
        "provider_id": "remote_main",
        "model": "MiniMax-M2.8",
        "label": "MiniMax 备用",
        "api_key_env": "VIBELUTION_LLM_BACKUP_REMOTE_API_KEY",
    }
    assert "backup_remote" not in public_config.get("llm", {}).get("model_library", {})
    build_effective_config(updated)

    edited = update_llm_model(updated, "backup_remote", "local_main", "qwen-72b-awq", "Qwen 备用")
    assert edited["llm"]["model_library"]["backup_remote"] == {
        "provider_id": "local_main",
        "model": "qwen-72b-awq",
        "label": "Qwen 备用",
        "api_key_env": "VIBELUTION_LLM_BACKUP_REMOTE_API_KEY",
    }
    assert updated["llm"]["model_library"]["backup_remote"]["model"] == "MiniMax-M2.8"
    build_effective_config(edited)

    detailed = update_llm_model(
        edited,
        "backup_remote",
        "local_main",
        "qwen-72b-awq",
        "Qwen 详细",
        {
            "contract": "reasoning_chat",
            "reasoning_state_field": "reasoning_content",
            "strict_compatibility": True,
            "transport": "chat_completions",
            "temperature": "0.2",
            "max_output_tokens": "4096",
            "timeout": "90",
            "connect_timeout": "10",
            "streaming": False,
            "tool_calling_mode": "disabled",
            "discovery_enabled": True,
        },
    )
    assert detailed["llm"]["model_library"]["backup_remote"] == {
        "provider_id": "local_main",
        "model": "qwen-72b-awq",
        "label": "Qwen 详细",
        "api_key_env": "VIBELUTION_LLM_BACKUP_REMOTE_API_KEY",
        "transport": "chat_completions",
        "contract": "reasoning_chat",
        "reasoning_state_field": "reasoning_content",
        "strict_compatibility": True,
        "temperature": 0.2,
        "max_output_tokens": 4096,
        "timeout": 90,
        "connect_timeout": 10,
        "streaming": False,
        "tool_calling_mode": "disabled",
        "discovery_enabled": True,
    }
    backup_option = next(item for item in list_llm_model_options(detailed) if item["model_id"] == "backup_remote")
    assert backup_option["details"]["temperature"] == 0.2
    build_effective_config(detailed)

    materialized = update_llm_model(public_config, "remote_main_minimax_m2_7", "remote_main", "MiniMax-M2.7", "MiniMax 编辑")
    assert materialized["llm"]["model_library"]["remote_main_minimax_m2_7"] == {
        "provider_id": "remote_main",
        "model": "MiniMax-M2.7",
        "label": "MiniMax 编辑",
        "api_key_env": "VIBELUTION_LLM_REMOTE_MAIN_MINIMAX_M2_7_API_KEY",
    }
    build_effective_config(materialized)

    deleted = delete_llm_model(edited, "backup_remote")
    assert "backup_remote" not in deleted["llm"].get("model_library", {})
    assert "model_library" in deleted["llm"]
    build_effective_config(deleted)


def test_build_effective_config_rejects_reasoning_chat_without_supported_state_field():
    public_config = load_public_config()
    profile = public_config["llm"]["profiles"]["primary"]
    profile["transport"] = "chat_completions"
    profile["contract"] = "reasoning_chat"
    profile["tool_calling_mode"] = "auto"
    profile["reasoning_state_field"] = ""

    with pytest.raises(ValueError, match="reasoning_state_field"):
        build_effective_config(public_config)


def test_build_effective_config_accepts_reasoning_chat_with_reasoning_content():
    public_config = load_public_config()
    profile = public_config["llm"]["profiles"]["primary"]
    profile["transport"] = "chat_completions"
    profile["contract"] = "reasoning_chat"
    profile["tool_calling_mode"] = "auto"
    profile["reasoning_state_field"] = "reasoning_content"

    config = build_effective_config(public_config)

    assert config.llm.get_profile("primary").contract == "reasoning_chat"
    assert config.llm.get_profile("primary").reasoning_state_field == "reasoning_content"


def test_model_library_api_key_writes_user_env_without_persisting_secret(monkeypatch):
    public_config = add_llm_model(load_public_config(), "backup_remote", "remote_main", "MiniMax-M2.8", "MiniMax 备用")
    writes = []
    deletes = []

    def fake_set(name, value):
        writes.append((name, value))
        monkeypatch.setenv(name, value)

    def fake_delete(name):
        deletes.append(name)
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setattr("scripts.config_panel._set_user_env_var", fake_set)
    monkeypatch.setattr("scripts.config_panel._delete_user_env_var", fake_delete)

    env_name = set_llm_model_api_key(public_config, "backup_remote", "model-secret")

    assert env_name == "VIBELUTION_LLM_BACKUP_REMOTE_API_KEY"
    assert writes == [("VIBELUTION_LLM_BACKUP_REMOTE_API_KEY", "model-secret")]
    assert "model-secret" not in dumps_public_config(public_config, HEADER_LINES)
    assert "model-secret" not in render_panel_html(public_config, lang="zh")

    clear_llm_model_api_key(public_config, "backup_remote")

    assert deletes == ["VIBELUTION_LLM_BACKUP_REMOTE_API_KEY"]


def test_set_user_env_var_uses_windows_registry_helper(monkeypatch):
    writes = []

    monkeypatch.setattr("scripts.config_panel.os.name", "nt", raising=False)
    monkeypatch.setattr("scripts.config_panel._write_windows_user_env_var", lambda name, value: writes.append((name, value)))
    monkeypatch.delenv("VIBELUTION_TEST_ENV_KEY", raising=False)

    _set_user_env_var("VIBELUTION_TEST_ENV_KEY", "secret")

    assert writes == [("VIBELUTION_TEST_ENV_KEY", "secret")]
    assert os.environ["VIBELUTION_TEST_ENV_KEY"] == "secret"


def test_delete_user_env_var_uses_windows_registry_helper(monkeypatch):
    deletes = []

    monkeypatch.setattr("scripts.config_panel.os.name", "nt", raising=False)
    monkeypatch.setattr("scripts.config_panel._write_windows_user_env_var", lambda name, value: deletes.append((name, value)))
    monkeypatch.setenv("VIBELUTION_TEST_ENV_KEY", "secret")

    _delete_user_env_var("VIBELUTION_TEST_ENV_KEY")

    assert deletes == [("VIBELUTION_TEST_ENV_KEY", None)]
    assert "VIBELUTION_TEST_ENV_KEY" not in os.environ


def test_add_llm_profile_persists_another_selectable_agent_config():
    public_config = load_public_config()
    updated = add_llm_profile(public_config, "remote_backup", "remote_main", "MiniMax-M2.7")

    assert "remote_backup" in updated["llm"]["profiles"]
    assert updated["llm"]["profiles"]["remote_backup"]["provider_id"] == "remote_main"
    assert updated["llm"]["profiles"]["remote_backup"]["model"] == "MiniMax-M2.7"
    assert "remote_backup" not in public_config["llm"]["profiles"]
    build_effective_config(updated)

def test_llm_connection_uses_selected_profile_and_provider(monkeypatch):
    public_config = load_public_config()
    expected_profile = public_config["llm"]["profiles"]["compression"]
    expected_provider = public_config["llm"]["providers"][expected_profile["provider_id"]]
    calls = []

    def fake_http_probe(provider, profile):
        calls.append((provider.provider_id, provider.kind, profile.profile_id, profile.model))
        return {"ok": True, "message": "ok"}

    monkeypatch.setattr("scripts.config_panel._probe_llm_http", fake_http_probe)

    result = run_llm_connection_test(public_config, "compression")

    assert result["ok"] is True
    assert result["profile_id"] == "compression"
    assert result["provider_id"] == expected_profile["provider_id"]
    assert calls == [(
        expected_profile["provider_id"],
        expected_provider["kind"],
        "compression",
        expected_profile["model"],
    )]


def test_every_public_config_parameter_can_be_saved_and_loaded(tmp_path):
    public_config = load_public_config()
    edited_config = json.loads(json.dumps(public_config, ensure_ascii=False))
    expected_values = {}

    for path in _iter_panel_editable_paths(public_config):
        original_value = _get_path(public_config, path)
        edited_value = _configured_test_value(path, original_value, public_config)
        _set_path(edited_config, path, edited_value)
        expected_values[path] = edited_value

    config_path = tmp_path / "config.toml"
    config_path.write_text(dumps_public_config(public_config, HEADER_LINES), encoding="utf-8")

    save_public_config(edited_config, config_path)
    loaded_config = load_public_config(config_path)
    build_effective_config(loaded_config)

    mismatches = {
        path: (_get_path(loaded_config, path), expected)
        for path, expected in expected_values.items()
        if _get_path(loaded_config, path) != expected
    }
    assert mismatches == {}


def test_render_panel_html_uses_configured_language_by_default():
    public_config = load_public_config()
    public_config.setdefault("ui", {})
    public_config["ui"]["language"] = "en"

    html = render_panel_html(public_config)

    assert "Vibelution Config Panel" in html
    assert 'option value="en" selected' in html


def test_get_config_language_falls_back_safely():
    assert get_config_language({"ui": {"language": "en"}}) == "en"
    assert get_config_language({"ui": {"language": "nope"}}) == "zh"
    assert get_config_language({}) == "zh"


def test_label_localization_prefers_exact_and_fallback_rules():
    assert localize_label("llm.providers.remote_main.api_key", "api_key", "zh") == "API 密钥"
    assert localize_label("tools.shell.default_timeout", "default_timeout", "en") == "Default Timeout"
    assert localize_section_label("llm.discovery", "discovery", "zh") == "模型发现"
    assert localize_section_label("network", "network", "en") == "Network"


def test_preserve_secret_blanks_keeps_existing_api_key():
    old_public = {
        "llm": {"providers": {"remote_main": {"api_key": "secret-key", "kind": "minimax"}}},
        "runtime": {"profile": "safe_remote"},
    }
    new_public = {
        "llm": {"providers": {"remote_main": {"api_key": "", "kind": "minimax"}}},
        "runtime": {"profile": "safe_remote"},
    }

    merged = preserve_secret_blanks(new_public, old_public)

    assert merged["llm"]["providers"]["remote_main"]["api_key"] == "secret-key"


def test_toml_writer_round_trip_for_public_config():
    public_config = load_public_config()
    dumped = dumps_public_config(public_config, HEADER_LINES)
    loaded = tomllib.loads(dumped)

    assert loaded["llm"]["providers"]["remote_main"]["kind"] == public_config["llm"]["providers"]["remote_main"]["kind"]
    assert loaded["prompt"]["sections"][0]["name"] == public_config["prompt"]["sections"][0]["name"]
    assert loaded["pet"]["heart"]["enabled"] is True


def test_build_effective_config_from_public_structure():
    public_config = load_public_config()
    config = build_effective_config(public_config)
    primary = config.llm.get_profile(role="primary")
    provider = config.llm.get_provider(primary.provider_id)
    expected_provider_kind = public_config["llm"]["providers"][
        public_config["llm"]["profiles"]["primary"]["provider_id"]
    ]["kind"]

    assert config.runtime.profile == "safe_remote"
    assert provider.kind == expected_provider_kind
    assert len(config.prompt.sections) == 2
    assert config.ui.language == public_config["ui"]["language"]


def test_config_diagnostics_block_local_provider_with_remote_base_url():
    public_config = load_public_config()
    public_config["llm"]["profiles"]["primary"]["provider_id"] = "local_main"
    public_config["llm"]["providers"]["local_main"]["kind"] = "local"
    public_config["llm"]["providers"]["local_main"]["base_url"] = "https://api.minimaxi.com/v1"
    config = build_effective_config(public_config)

    diagnosis = config.diagnose_config()

    assert "local provider 指向了非本地 API base" in diagnosis["blocking_issues"]


def test_render_panel_html_switch_lang_and_save_behaviors():
    public_config = load_public_config()
    public_config["ui"]["language"] = "en"

    html = render_panel_html(public_config)

    assert "switchLang(lang)" in html
    assert 'nextUrl.searchParams.set("lang", lang);' in html
    assert 'syncLanguageControls(this.value, \'body\')' in html
    assert "payload.ui.language = lang;" in html
    assert 'showToast("success"' in html
    assert 'showToast("error"' in html
    assert "setToolbarMessage(result.message, false);" in html
    assert 'new URL(window.location.origin + "/")' in html
    assert 'const root = {"runtime"' in html
    assert "_json_for_attr(display_config)" not in html
