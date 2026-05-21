#!/usr/bin/env python3
"""
配置面板测试
"""

import json
import os
import threading
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from config.toml_writer import dumps_public_config
from scripts.config_panel import (
    ConfigPanelHandler,
    HEADER_LINES,
    _assert_base_hash_matches,
    _render_llm_profile_card,
    _submitted_base_hash,
    _validate_required_llm_profiles,
    _delete_user_env_var,
    _set_user_env_var,
    add_llm_model,
    add_llm_profile,
    apply_llm_model_preset,
    build_effective_config,
    clear_llm_model_api_key,
    delete_llm_model,
    get_config_language,
    inspect_public_config,
    list_llm_model_options,
    list_llm_model_preset_options,
    load_public_config,
    localize_label,
    localize_section_label,
    preserve_secret_blanks,
    render_panel_html,
    save_public_config,
    set_llm_model_api_key,
    test_llm_connection as run_llm_connection_test,
    update_llm_model,
)
from config.public_config import UNCONFIGURED_MODEL_REF, public_config_hash


PROJECT_ROOT = Path(__file__).parent.parent


def _start_test_config_panel(monkeypatch: pytest.MonkeyPatch, config_path: Path):
    from config.public_config import load_public_config as load_public_config_from_path
    from config.public_config import save_public_config as save_public_config_to_path

    def fake_load_public_config():
        return load_public_config_from_path(config_path)

    def fake_save_public_config(public_config):
        return save_public_config_to_path(public_config, config_path)

    monkeypatch.setattr("scripts.config_panel.load_public_config", fake_load_public_config)
    monkeypatch.setattr("scripts.config_panel.save_public_config", fake_save_public_config)
    server = ThreadingHTTPServer(("127.0.0.1", 0), ConfigPanelHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    return server, thread, base_url


def _post_form(base_url: str, path: str, fields: dict[str, str]):
    data = urllib.parse.urlencode(fields).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    return urllib.request.urlopen(request, timeout=10)


def _provider(
    kind: str,
    base_url: str,
    api_key_env: str,
    *,
    compat_mode: str = "openai",
    requires_api_key: bool = True,
    context_window: int = 400000,
) -> dict:
    return {
        "kind": kind,
        "api_key_env": api_key_env,
        "base_url": base_url,
        "compat_mode": compat_mode,
        "requires_api_key": requires_api_key,
        "context_window": context_window,
    }


def test_public_llm_shape_is_inline_provider_only():
    public_config = load_public_config()
    llm = public_config["llm"]

    assert "providers" not in llm
    assert all("provider" in profile for profile in llm["profiles"].values())
    assert all("provider_id" not in profile for profile in llm["profiles"].values())
    assert all("provider" in item for item in llm["model_library"].values())
    assert all("provider_id" not in item for item in llm["model_library"].values())


def test_render_panel_html_uses_inline_provider_controls():
    html = render_panel_html(load_public_config(), lang="zh")

    assert "Vibelution 配置面板" in html
    assert "通用模型库" in html
    assert "模型服务" not in html
    assert "remote_main" not in html
    assert 'data-add-model-field="provider_kind"' in html
    assert 'data-add-model-field="provider_base_url"' in html
    assert 'data-edit-field="provider_kind"' in html
    assert 'data-edit-field="provider_id"' not in html
    assert 'data-path="llm.providers.remote_main.kind"' not in html
    assert 'data-path="llm.profiles.primary.provider.kind"' in html
    assert 'data-provider="' in html


def test_render_panel_html_uses_inline_profile_clone_controls():
    html = render_panel_html(load_public_config(), lang="zh")

    assert 'id="add-llm-profile-card"' in html
    assert 'data-add-profile-field="source_profile_id"' in html
    assert 'id="add-llm-profile-model"' in html
    assert 'data-add-profile-field="provider_id"' not in html
    assert 'saveInlineLlmProfile()' in html
    assert "profile_id and model_id are required" in html


def test_render_panel_html_embeds_inline_provider_js_helpers():
    html = render_panel_html(load_public_config(), lang="zh")

    assert "collectProviderFields" in html
    assert "applySelectedModelToProfile" in html
    assert "provider_extra_headers must be valid JSON" in html
    assert "provider.kind and model are required" in html


def test_render_panel_html_uses_confirm_apply_flow_and_draft_routes():
    html = render_panel_html(load_public_config(), lang="zh")

    assert "应用配置" in html
    assert "修改已确认，等待应用" in html
    assert 'postHtmlNavigation("/preview"' in html
    assert 'fetch("/preview-config-card"' in html
    assert 'fetch("/preview-llm-profile-card"' in html
    assert "postPreviewState(" in html
    assert '"/draft-add-llm-model"' in html
    assert '"/draft-update-llm-model"' in html
    assert '"/draft-delete-llm-model"' in html
    assert '"/draft-add-llm-profile"' in html


def test_render_panel_html_embeds_base_hash_for_apply_flow():
    public_config = load_public_config()
    expected_hash = public_config_hash(public_config)

    html = render_panel_html(public_config, lang="zh")

    assert 'name="base_hash"' in html
    assert 'id="base-hash"' in html
    assert "const INITIAL_BASE_HASH" in html
    assert expected_hash in html
    assert "collectBaseHash()" in html


def test_render_panel_html_marks_missing_profile_models_as_required():
    public_config = load_public_config()
    public_config["llm"]["profiles"]["primary"] = {
        "model_ref": UNCONFIGURED_MODEL_REF,
        "overrides": {},
    }

    html = render_panel_html(public_config, lang="zh")

    assert '* 必填' in html
    assert 'data-profile-required="primary"' in html
    assert '请选择模型' in html


def test_render_llm_profile_card_includes_stable_card_id():
    html = _render_llm_profile_card(load_public_config(), "primary", "zh")

    assert 'id="config-card-llm-profiles-primary"' in html
    assert 'data-card-path="llm.profiles.primary"' in html


def test_render_llm_profile_card_accepts_model_ref_profiles():
    public_config = load_public_config()
    public_config["llm"]["profiles"]["primary"] = {
        "model_ref": "openai_gpt_5_5",
        "overrides": {"temperature": 0.25},
    }

    html = _render_llm_profile_card(public_config, "primary", "zh")

    assert 'data-profile-required="primary"' not in html
    assert 'gpt-5.5' in html


def test_submitted_base_hash_reads_form_value():
    assert _submitted_base_hash({"base_hash": ["abc123"]}) == "abc123"
    assert _submitted_base_hash({}) == ""


def test_assert_base_hash_matches_rejects_stale_snapshot():
    public_config = load_public_config()
    stale_hash = public_config_hash(public_config)
    updated = load_public_config()
    updated["ui"]["language"] = "en"

    with pytest.raises(ValueError, match="重新加载"):
        _assert_base_hash_matches(stale_hash, updated, "zh")


def test_confirm_preview_does_not_persist_config_file(tmp_path, monkeypatch):
    public_config = load_public_config()
    config_path = tmp_path / "config.toml"
    config_path.write_text(dumps_public_config(public_config, HEADER_LINES), encoding="utf-8")
    original_text = config_path.read_text(encoding="utf-8")
    payload = load_public_config(config_path)
    payload["ui"]["language"] = "en"
    base_hash = public_config_hash(public_config)
    server, thread, base_url = _start_test_config_panel(monkeypatch, config_path)

    try:
        response = _post_form(
            base_url,
            "/preview",
            {
                "payload": json.dumps(payload, ensure_ascii=False),
                "draft_meta": json.dumps({}, ensure_ascii=False),
                "base_hash": base_hash,
                "lang": "en",
                "message": "preview-only",
            },
        )
        html = response.read().decode("utf-8")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert response.status == 200
    assert 'id="base-hash"' in html
    assert base_hash in html
    assert "preview-only" in html
    assert config_path.read_text(encoding="utf-8") == original_text


def test_preview_config_card_returns_html_without_persisting_config_file(tmp_path, monkeypatch):
    public_config = load_public_config()
    config_path = tmp_path / "config.toml"
    config_path.write_text(dumps_public_config(public_config, HEADER_LINES), encoding="utf-8")
    original_text = config_path.read_text(encoding="utf-8")
    payload = load_public_config(config_path)
    payload["tools"]["shell"]["default_timeout"] = 321
    base_hash = public_config_hash(public_config)
    server, thread, base_url = _start_test_config_panel(monkeypatch, config_path)

    try:
        response = _post_form(
            base_url,
            "/preview-config-card",
            {
                "payload": json.dumps(payload, ensure_ascii=False),
                "draft_meta": json.dumps({}, ensure_ascii=False),
                "base_hash": base_hash,
                "card_path": "tools.shell",
                "lang": "zh",
            },
        )
        result = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert response.status == 200
    assert result["ok"] is True
    assert 'data-card-path="tools.shell"' in result["html"]
    assert 'value="321"' in result["html"]
    assert result["message"] == "修改已确认，等待应用"
    assert config_path.read_text(encoding="utf-8") == original_text


def test_draft_add_llm_model_returns_preview_fragments_without_persisting_config_file(tmp_path, monkeypatch):
    public_config = load_public_config()
    config_path = tmp_path / "config.toml"
    config_path.write_text(dumps_public_config(public_config, HEADER_LINES), encoding="utf-8")
    original_text = config_path.read_text(encoding="utf-8")
    payload = load_public_config(config_path)
    base_hash = public_config_hash(public_config)
    server, thread, base_url = _start_test_config_panel(monkeypatch, config_path)

    try:
        response = _post_form(
            base_url,
            "/draft-add-llm-model",
            {
                "payload": json.dumps(payload, ensure_ascii=False),
                "draft_meta": json.dumps({}, ensure_ascii=False),
                "base_hash": base_hash,
                "response_mode": "fragments",
                "model_id": "preview_custom_model",
                "provider": json.dumps(
                    _provider("openai", "https://api.openai.com/v1", "OPENAI_API_KEY"),
                    ensure_ascii=False,
                ),
                "model": "gpt-5.5",
                "label": "Preview Custom Model",
                "details": json.dumps({}, ensure_ascii=False),
                "api_key_env": "",
                "lang": "zh",
            },
        )
        result = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert response.status == 200
    assert result["ok"] is True
    assert result["public_config"]["llm"]["model_library"]["preview_custom_model"]["model"] == "gpt-5.5"
    assert "Preview Custom Model" in result["main_html"]
    assert "配置诊断" in result["aside_html"]
    assert result["message"] == "修改已确认，等待应用"
    assert config_path.read_text(encoding="utf-8") == original_text


def test_draft_add_llm_profile_returns_preview_fragments_without_persisting_config_file(tmp_path, monkeypatch):
    public_config = load_public_config()
    config_path = tmp_path / "config.toml"
    config_path.write_text(dumps_public_config(public_config, HEADER_LINES), encoding="utf-8")
    original_text = config_path.read_text(encoding="utf-8")
    payload = load_public_config(config_path)
    base_hash = public_config_hash(public_config)
    server, thread, base_url = _start_test_config_panel(monkeypatch, config_path)

    try:
        response = _post_form(
            base_url,
            "/draft-add-llm-profile",
            {
                "payload": json.dumps(payload, ensure_ascii=False),
                "draft_meta": json.dumps({}, ensure_ascii=False),
                "base_hash": base_hash,
                "response_mode": "fragments",
                "profile_id": "preview_profile_copy",
                "source_profile_id": "primary",
                "model_id": "openai_gpt_5_5",
                "lang": "zh",
            },
        )
        result = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert response.status == 200
    assert result["ok"] is True
    assert result["public_config"]["llm"]["profiles"]["preview_profile_copy"]["model"] == "gpt-5.5"
    assert 'data-profile-id="preview_profile_copy"' in result["main_html"]
    assert result["message"] == "修改已确认，等待应用"
    assert config_path.read_text(encoding="utf-8") == original_text


def test_draft_delete_llm_model_fragments_mark_referencing_profiles_unconfigured(tmp_path, monkeypatch):
    public_config = load_public_config()
    public_config["llm"]["profiles"]["primary"] = {
        "model_ref": "openai_gpt_5_5",
        "overrides": {},
    }
    config_path = tmp_path / "config.toml"
    config_path.write_text(dumps_public_config(public_config, HEADER_LINES), encoding="utf-8")
    original_text = config_path.read_text(encoding="utf-8")
    payload = json.loads(json.dumps(public_config, ensure_ascii=False))
    base_hash = public_config_hash(load_public_config(config_path))
    server, thread, base_url = _start_test_config_panel(monkeypatch, config_path)

    try:
        response = _post_form(
            base_url,
            "/draft-delete-llm-model",
            {
                "payload": json.dumps(payload, ensure_ascii=False),
                "draft_meta": json.dumps({}, ensure_ascii=False),
                "base_hash": base_hash,
                "response_mode": "fragments",
                "model_id": "openai_gpt_5_5",
                "lang": "zh",
            },
        )
        result = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert response.status == 200
    assert result["ok"] is True
    assert result["public_config"]["llm"]["profiles"]["primary"]["model_ref"] == UNCONFIGURED_MODEL_REF
    assert 'data-profile-required="primary"' in result["main_html"]
    assert "请选择模型" in result["main_html"]
    assert result["message"] == "修改已确认，等待应用"
    assert config_path.read_text(encoding="utf-8") == original_text


def test_apply_requires_matching_base_hash(tmp_path, monkeypatch):
    public_config = load_public_config()
    config_path = tmp_path / "config.toml"
    config_path.write_text(dumps_public_config(public_config, HEADER_LINES), encoding="utf-8")
    stale_hash = public_config_hash(public_config)
    external = load_public_config(config_path)
    external["ui"]["language"] = "en"
    save_public_config(external, config_path)
    payload = load_public_config(config_path)
    payload["ui"]["language"] = "zh"
    server, thread, base_url = _start_test_config_panel(monkeypatch, config_path)

    try:
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            _post_form(
                base_url,
                "/save",
                {
                    "payload": json.dumps(payload, ensure_ascii=False),
                    "draft_meta": json.dumps({}, ensure_ascii=False),
                    "base_hash": stale_hash,
                    "lang": "zh",
                },
            )
        body = exc_info.value.read().decode("utf-8")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    result = json.loads(body)
    assert exc_info.value.code == 409
    assert result["ok"] is False
    assert "重新加载" in result["message"]
    assert load_public_config(config_path)["ui"]["language"] == "en"


def test_apply_with_matching_base_hash_persists_config_file(tmp_path, monkeypatch):
    public_config = load_public_config()
    config_path = tmp_path / "config.toml"
    config_path.write_text(dumps_public_config(public_config, HEADER_LINES), encoding="utf-8")
    payload = load_public_config(config_path)
    payload["ui"]["language"] = "en"
    base_hash = public_config_hash(load_public_config(config_path))
    server, thread, base_url = _start_test_config_panel(monkeypatch, config_path)

    try:
        response = _post_form(
            base_url,
            "/save",
            {
                "payload": json.dumps(payload, ensure_ascii=False),
                "draft_meta": json.dumps({}, ensure_ascii=False),
                "base_hash": base_hash,
                "lang": "en",
            },
        )
        result = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert response.status == 200
    assert result["ok"] is True
    assert load_public_config(config_path)["ui"]["language"] == "en"


def test_render_panel_html_supports_english():
    html = render_panel_html(load_public_config(), lang="en")

    assert "Vibelution Config Panel" in html
    assert "Model Library" in html
    assert "Providers" not in html
    assert 'option value="en" selected' in html


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


def test_model_preset_options_include_codex_preset():
    presets = {item["preset_id"]: item for item in list_llm_model_preset_options()}

    assert "openai_gpt_5_3_codex" in presets
    assert presets["openai_gpt_5_3_codex"]["model"]["model"] == "gpt-5.3-codex"
    assert presets["openai_gpt_5_3_codex"]["provider"]["kind"] == "openai"
    assert "openai_gpt_5_5" in presets
    assert presets["openai_gpt_5_5"]["model"]["model"] == "gpt-5.5"
    assert presets["openai_gpt_5_5"]["provider"]["context_window"] == 1050000
    assert "relay_openai_gpt_5_5" in presets
    assert presets["relay_openai_gpt_5_5"]["category"] == "relay"
    assert presets["relay_openai_gpt_5_5"]["model"]["model"] == "gpt-5.5"
    assert presets["relay_openai_gpt_5_5"]["model"]["transport"] == "chat_completions"
    assert presets["relay_openai_gpt_5_5"]["model"]["contract"] == "tool_chat"
    assert presets["relay_openai_gpt_5_5"]["provider"]["kind"] == "relay"
    assert presets["relay_openai_gpt_5_5"]["provider"]["base_url"] == "https://pixel.try-chatapi.com/v1"
    assert "deepseek_v4_flash" in presets
    assert presets["deepseek_v4_flash"]["model"]["model"] == "deepseek-v4-flash"
    assert presets["deepseek_v4_flash"]["model"]["contract"] == "reasoning_chat"
    assert presets["deepseek_v4_pro"]["model"]["reasoning_state_field"] == "reasoning_content"


def test_list_llm_model_options_exposes_inline_provider_and_source():
    options = list_llm_model_options(load_public_config())

    assert options
    assert all("provider" in item for item in options)
    assert all("provider_id" not in item for item in options)
    assert all(item["source"] in {"model_library", "profile"} for item in options)


def test_apply_codex_model_preset_materializes_inline_provider():
    updated = apply_llm_model_preset(load_public_config(), "openai_gpt_5_3_codex")
    model = updated["llm"]["model_library"]["openai_gpt_5_3_codex"]

    assert model["provider"]["kind"] == "openai"
    assert model["provider"]["api_key_env"] == "OPENAI_API_KEY"
    assert model["provider"]["requires_api_key"] is True
    assert model["provider"]["context_window"] == 400000
    assert model["model"] == "gpt-5.3-codex"
    assert model["contract"] == "tool_chat"
    assert model["api_key_env"] == "VIBELUTION_LLM_OPENAI_GPT_5_3_CODEX_API_KEY"
    build_effective_config(updated)


def test_apply_relay_model_preset_materializes_openai_compatible_provider():
    updated = apply_llm_model_preset(load_public_config(), "relay_openai_gpt_5_5")
    model = updated["llm"]["model_library"]["relay_openai_gpt_5_5"]

    assert model["provider"]["kind"] == "relay"
    assert model["provider"]["api_key_env"] == "OPENAI_API_KEY"
    assert model["provider"]["base_url"] == "https://pixel.try-chatapi.com/v1"
    assert model["provider"]["compat_mode"] == "openai"
    assert model["provider"]["requires_api_key"] is True
    assert model["provider"]["context_window"] == 1000000
    assert model["model"] == "gpt-5.5"
    assert model["transport"] == "chat_completions"
    assert model["contract"] == "tool_chat"
    assert model["api_key_env"] == "VIBELUTION_LLM_RELAY_OPENAI_GPT_5_5_API_KEY"
    build_effective_config(updated)


def test_default_public_config_includes_new_official_model_templates():
    public_config = load_public_config()
    openai_model = public_config["llm"]["model_library"]["openai_gpt_5_5"]

    assert openai_model["provider"]["kind"] == "openai"
    assert openai_model["provider"]["context_window"] == 1050000
    assert openai_model["model"] == "gpt-5.5"
    assert openai_model["max_output_tokens"] == 128000
    assert openai_model["api_key_env"] == "VIBELUTION_LLM_OPENAI_GPT_5_5_API_KEY"

    deepseek_model = public_config["llm"]["model_library"]["deepseek_v4_flash"]

    assert deepseek_model["provider"]["kind"] == "deepseek"
    assert deepseek_model["provider"]["context_window"] == 1000000
    assert deepseek_model["model"] == "deepseek-v4-flash"
    assert deepseek_model["contract"] == "reasoning_chat"
    assert deepseek_model["reasoning_state_field"] == "reasoning_content"
    assert deepseek_model["max_output_tokens"] == 384000
    build_effective_config(public_config)


def test_add_update_and_delete_llm_model_with_inline_provider():
    public_config = load_public_config()
    openai = _provider("openai", "https://api.openai.com/v1", "OPENAI_API_KEY")
    local = _provider(
        "local",
        "http://127.0.0.1:11434/v1",
        "",
        requires_api_key=False,
        context_window=65536,
    )

    updated = add_llm_model(public_config, "custom_codex", openai, "gpt-5.3-codex", "Custom Codex")
    assert updated["llm"]["model_library"]["custom_codex"] == {
        "provider": openai,
        "model": "gpt-5.3-codex",
        "label": "Custom Codex",
        "api_key_env": "VIBELUTION_LLM_CUSTOM_CODEX_API_KEY",
    }
    assert "custom_codex" not in public_config.get("llm", {}).get("model_library", {})
    build_effective_config(updated)

    edited = update_llm_model(
        updated,
        "custom_codex",
        local,
        "qwen-72b-awq",
        "Qwen Local",
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
    assert edited["llm"]["model_library"]["custom_codex"]["provider"] == local
    assert edited["llm"]["model_library"]["custom_codex"]["model"] == "qwen-72b-awq"
    assert edited["llm"]["model_library"]["custom_codex"]["label"] == "Qwen Local"
    assert edited["llm"]["model_library"]["custom_codex"]["api_key_env"] == "VIBELUTION_LLM_CUSTOM_CODEX_API_KEY"
    assert edited["llm"]["model_library"]["custom_codex"]["reasoning_state_field"] == "reasoning_content"
    build_effective_config(edited)

    deleted = delete_llm_model(edited, "custom_codex")
    assert "custom_codex" not in deleted["llm"]["model_library"]
    build_effective_config(deleted)


def test_delete_generated_profile_model_clears_matching_profiles():
    public_config = load_public_config()
    provider = _provider("openai", "https://api.openai.com/v1", "OPENAI_API_KEY")
    public_config["llm"]["profiles"]["primary"]["provider"] = provider.copy()
    public_config["llm"]["profiles"]["primary"]["model"] = "gpt-5.4"
    public_config["llm"]["profiles"]["mental_model"]["provider"] = provider.copy()
    public_config["llm"]["profiles"]["mental_model"]["model"] = "gpt-5.4"

    generated = next(item for item in list_llm_model_options(public_config) if item["source"] == "profile")
    deleted = delete_llm_model(public_config, generated["model_id"])

    assert deleted["llm"]["profiles"]["primary"]["model"] == ""
    assert deleted["llm"]["profiles"]["mental_model"]["model"] == ""
    assert deleted["llm"]["profiles"]["subagent_explorer"]["model"] == "deepseek-v4-pro"
    assert not any(item["model_id"] == generated["model_id"] for item in list_llm_model_options(deleted))
    build_effective_config(deleted)


def test_add_llm_profile_from_model_library_copies_provider_independently():
    public_config = load_public_config()
    updated = add_llm_profile(public_config, "codex_clone", source_profile_id="primary", model_id="share_ai")

    clone = updated["llm"]["profiles"]["codex_clone"]
    assert clone["model"] == "gpt-5.3-codex"
    assert clone["provider"] == updated["llm"]["model_library"]["share_ai"]["provider"]
    assert clone["api_key_env"] == "VIBELUTION_LLM_SHARE_AI_API_KEY"

    edited = update_llm_model(
        updated,
        "share_ai",
        _provider("deepseek", "https://api.deepseek.com", "DEEPSEEK_API_KEY", context_window=131072),
        "deepseek-v4-pro",
        "DeepSeek Changed",
    )
    assert edited["llm"]["profiles"]["codex_clone"]["model"] == "gpt-5.3-codex"
    assert edited["llm"]["profiles"]["codex_clone"]["provider"]["kind"] == "minimax"

    deleted = delete_llm_model(updated, "share_ai")
    assert deleted["llm"]["profiles"]["codex_clone"]["model"] == "gpt-5.3-codex"
    assert deleted["llm"]["profiles"]["codex_clone"]["provider"]["kind"] == "minimax"


def test_build_effective_config_rejects_reasoning_chat_without_supported_state_field():
    public_config = load_public_config()
    profile = public_config["llm"]["profiles"]["primary"]
    profile["provider"] = _provider("openai", "https://api.openai.com/v1", "OPENAI_API_KEY")
    profile["model"] = "gpt-5.4"
    profile["transport"] = "chat_completions"
    profile["contract"] = "reasoning_chat"
    profile["tool_calling_mode"] = "auto"
    profile["reasoning_state_field"] = ""
    profile["strict_compatibility"] = True

    with pytest.raises(ValueError, match="reasoning_state_field"):
        build_effective_config(public_config)


def test_build_effective_config_accepts_reasoning_chat_with_reasoning_content():
    public_config = load_public_config()
    profile = public_config["llm"]["profiles"]["primary"]
    profile["provider"] = _provider("openai", "https://api.openai.com/v1", "OPENAI_API_KEY")
    profile["model"] = "gpt-5.4"
    profile["transport"] = "chat_completions"
    profile["contract"] = "reasoning_chat"
    profile["tool_calling_mode"] = "auto"
    profile["reasoning_state_field"] = "reasoning_content"
    profile["strict_compatibility"] = True

    config = build_effective_config(public_config)

    assert config.llm.get_profile("primary").contract == "reasoning_chat"
    assert config.llm.get_profile("primary").reasoning_state_field == "reasoning_content"


def test_llm_connection_uses_selected_profile_inline_provider(monkeypatch):
    public_config = load_public_config()
    calls = []

    def fake_http_probe(provider, profile):
        calls.append((provider.kind, profile.profile_id, profile.model))
        return {"ok": True, "message": "ok"}

    monkeypatch.setattr("scripts.config_panel._probe_llm_http", fake_http_probe)

    result = run_llm_connection_test(public_config, "subagent_explorer")

    assert result["ok"] is True
    assert result["profile_id"] == "subagent_explorer"
    assert result["provider_kind"] == "deepseek"
    assert calls == [("deepseek", "subagent_explorer", "deepseek-v4-pro")]


def test_llm_connection_returns_route_diagnostics(monkeypatch):
    public_config = load_public_config()
    monkeypatch.setenv("VIBELUTION_LLM_DEEPSEEK_V4_PRO_API_KEY", "model-secret")

    def fake_http_probe(provider, profile, api_key=None):
        assert api_key == "model-secret"
        return {"ok": False, "message": "HTTP 401: Unauthorized"}

    monkeypatch.setattr("scripts.config_panel._probe_llm_http", fake_http_probe)

    result = run_llm_connection_test(public_config, "subagent_explorer")

    assert result["ok"] is False
    assert result["provider_kind"] == "deepseek"
    assert result["base_url"] == "https://api.deepseek.com"
    assert result["api_key_source"] == "profile-env:VIBELUTION_LLM_DEEPSEEK_V4_PRO_API_KEY"


def test_llm_connection_prefers_pending_draft_api_key(monkeypatch):
    public_config = load_public_config()

    def fake_http_probe(provider, profile, api_key=None):
        assert api_key == "draft-secret"
        return {"ok": True, "message": "ok"}

    monkeypatch.setattr("scripts.config_panel._probe_llm_http", fake_http_probe)

    result = run_llm_connection_test(
        public_config,
        "subagent_explorer",
        {
            "pending_api_keys": {"VIBELUTION_LLM_DEEPSEEK_V4_PRO_API_KEY": "draft-secret"},
            "pending_cleared_api_keys": [],
        },
    )

    assert result["ok"] is True
    assert result["api_key_source"] == "pending-env:VIBELUTION_LLM_DEEPSEEK_V4_PRO_API_KEY"


def test_llm_connection_rejects_metadata_service_base_url():
    public_config = load_public_config()
    public_config["llm"]["profiles"]["primary"]["provider"] = _provider(
        "openai",
        "http://169.254.169.254/v1",
        "OPENAI_API_KEY",
    )
    public_config["llm"]["profiles"]["primary"]["model"] = "gpt-5.5"

    with pytest.raises(ValueError, match="base_url"):
        run_llm_connection_test(public_config, "primary")


def test_llm_connection_allows_localhost_without_api_key(monkeypatch):
    public_config = load_public_config()
    public_config["llm"]["profiles"]["primary"]["provider"] = _provider(
        "local",
        "http://127.0.0.1:11434/v1",
        "",
        requires_api_key=False,
        context_window=65536,
    )
    public_config["llm"]["profiles"]["primary"]["model"] = "llama3.2"
    monkeypatch.setenv("VIBELUTION_LLM_DEEPSEEK_V4_PRO_API_KEY", "should-not-be-sent")

    def fake_http_probe(provider, profile, api_key=None):
        assert provider.kind == "local"
        assert api_key is None
        return {"ok": True, "message": "ok"}

    monkeypatch.setattr("scripts.config_panel._probe_llm_http", fake_http_probe)

    result = run_llm_connection_test(public_config, "primary")

    assert result["ok"] is True
    assert result["api_key_source"] == "not-required"


def test_validate_required_llm_profiles_blocks_missing_models():
    public_config = load_public_config()
    public_config["llm"]["profiles"]["primary"] = {
        "model_ref": UNCONFIGURED_MODEL_REF,
        "overrides": {},
    }

    with pytest.raises(ValueError, match="主智能体"):
        _validate_required_llm_profiles(public_config, "zh")


def test_model_library_api_key_writes_user_env_without_persisting_secret(monkeypatch):
    public_config = add_llm_model(
        load_public_config(),
        "custom_codex",
        _provider("openai", "https://api.openai.com/v1", "OPENAI_API_KEY"),
        "gpt-5.3-codex",
        "Custom Codex",
    )
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

    env_name = set_llm_model_api_key(public_config, "custom_codex", "model-secret")

    assert env_name == "VIBELUTION_LLM_CUSTOM_CODEX_API_KEY"
    assert writes == [("VIBELUTION_LLM_CUSTOM_CODEX_API_KEY", "model-secret")]
    assert "model-secret" not in dumps_public_config(public_config, HEADER_LINES)
    assert "model-secret" not in render_panel_html(public_config, lang="zh")

    clear_llm_model_api_key(public_config, "custom_codex")

    assert deletes == ["VIBELUTION_LLM_CUSTOM_CODEX_API_KEY"]


def test_set_user_env_var_uses_windows_registry_helper(monkeypatch):
    writes = []

    monkeypatch.setattr("scripts.config_panel.os.name", "nt", raising=False)
    monkeypatch.setattr("scripts.config_panel._write_windows_user_env_var", lambda name, value: writes.append((name, value)))
    monkeypatch.delenv("VIBELUTION_LLM_TEST_ENV_KEY", raising=False)

    _set_user_env_var("VIBELUTION_LLM_TEST_ENV_KEY", "secret")

    assert writes == [("VIBELUTION_LLM_TEST_ENV_KEY", "secret")]
    assert os.environ["VIBELUTION_LLM_TEST_ENV_KEY"] == "secret"


def test_set_user_env_var_rejects_system_names():
    with pytest.raises(ValueError, match="PATH"):
        _set_user_env_var("PATH", "secret")


def test_delete_user_env_var_uses_windows_registry_helper(monkeypatch):
    deletes = []

    monkeypatch.setattr("scripts.config_panel.os.name", "nt", raising=False)
    monkeypatch.setattr("scripts.config_panel._write_windows_user_env_var", lambda name, value: deletes.append((name, value)))
    monkeypatch.setenv("VIBELUTION_LLM_TEST_ENV_KEY", "secret")

    _delete_user_env_var("VIBELUTION_LLM_TEST_ENV_KEY")

    assert deletes == [("VIBELUTION_LLM_TEST_ENV_KEY", None)]
    assert "VIBELUTION_LLM_TEST_ENV_KEY" not in os.environ


def test_list_llm_model_options_detects_windows_user_scoped_model_key(monkeypatch):
    public_config = add_llm_model(
        load_public_config(),
        "custom_codex",
        _provider("openai", "https://api.openai.com/v1", "OPENAI_API_KEY"),
        "gpt-5.3-codex",
        "Custom Codex",
    )

    monkeypatch.setattr("config.public_config.os.name", "nt", raising=False)
    monkeypatch.setenv("VIBELUTION_ENABLE_USER_ENV_FALLBACK", "1")
    monkeypatch.delenv("VIBELUTION_LLM_CUSTOM_CODEX_API_KEY", raising=False)
    monkeypatch.setattr(
        "config.public_config._read_windows_user_env_var",
        lambda name: "model-secret" if name == "VIBELUTION_LLM_CUSTOM_CODEX_API_KEY" else "",
    )

    option = next(item for item in list_llm_model_options(public_config) if item["model_id"] == "custom_codex")

    assert option["api_key_env"] == "VIBELUTION_LLM_CUSTOM_CODEX_API_KEY"
    assert option["api_key_configured"] is True


def test_build_effective_config_prefers_model_user_env_key_on_windows(monkeypatch):
    public_config = add_llm_model(
        load_public_config(),
        "custom_codex",
        _provider("openai", "https://api.openai.com/v1", "OPENAI_API_KEY"),
        "gpt-5.3-codex",
        "Custom Codex",
    )
    primary = public_config["llm"]["profiles"]["primary"]
    primary["provider"] = public_config["llm"]["model_library"]["custom_codex"]["provider"].copy()
    primary["model"] = "gpt-5.3-codex"
    primary.pop("api_key_env", None)

    monkeypatch.setattr("config.models.os.name", "nt", raising=False)
    monkeypatch.setenv("VIBELUTION_ENABLE_USER_ENV_FALLBACK", "1")
    monkeypatch.delenv("VIBELUTION_LLM_CUSTOM_CODEX_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "provider-secret")
    monkeypatch.setattr(
        "config.models._read_windows_user_env_var",
        lambda name: "model-secret" if name == "VIBELUTION_LLM_CUSTOM_CODEX_API_KEY" else None,
    )

    effective = build_effective_config(public_config)

    assert effective.get_api_key_for_profile(profile_id="primary") == "model-secret"
    assert effective.llm.get_api_key_source_label_for_profile(profile_id="primary") == (
        "model-env:VIBELUTION_LLM_CUSTOM_CODEX_API_KEY"
    )


def test_preserve_secret_blanks_keeps_existing_api_key():
    old_public = {
        "llm": {
            "profiles": {
                "primary": {
                    "provider": {"kind": "openai", "api_key": "secret-key"},
                    "model": "gpt-5.4",
                }
            }
        }
    }
    new_public = {
        "llm": {
            "profiles": {
                "primary": {
                    "provider": {"kind": "openai", "api_key": ""},
                    "model": "gpt-5.4",
                }
            }
        }
    }

    merged = preserve_secret_blanks(new_public, old_public)

    assert merged["llm"]["profiles"]["primary"]["provider"]["api_key"] == "secret-key"


def test_toml_writer_round_trip_for_public_config_uses_inline_provider_blocks():
    public_config = load_public_config()
    dumped = dumps_public_config(public_config, HEADER_LINES)
    loaded = tomllib.loads(dumped)

    assert "[llm.providers]" not in dumped
    assert "[llm.profiles.primary.provider]" in dumped
    assert "[llm.model_library.share_ai.provider]" in dumped
    assert loaded["llm"]["profiles"]["primary"]["provider"]["kind"] == public_config["llm"]["profiles"]["primary"]["provider"]["kind"]
    assert loaded["prompt"]["sections"][0]["name"] == public_config["prompt"]["sections"][0]["name"]
    assert loaded["pet"]["heart"]["enabled"] is True


def test_toml_writer_quotes_dotted_model_library_ids(tmp_path):
    public_config = add_llm_model(
        load_public_config(),
        "custom.gpt-5.3-codex",
        _provider("openai", "https://api.openai.com/v1", "OPENAI_API_KEY"),
        "gpt-5.3-codex",
        "Custom Codex",
    )

    dumped = dumps_public_config(public_config, HEADER_LINES)
    config_path = tmp_path / "config.toml"
    config_path.write_text(dumped, encoding="utf-8")

    loaded = load_public_config(config_path)

    assert '[llm.model_library."custom.gpt-5.3-codex"]' in dumped
    assert loaded["llm"]["model_library"]["custom.gpt-5.3-codex"]["model"] == "gpt-5.3-codex"
    assert loaded["llm"]["model_library"]["custom.gpt-5.3-codex"]["provider"]["kind"] == "openai"


def test_save_public_config_preserves_dotted_model_library_ids(tmp_path):
    public_config = add_llm_model(
        load_public_config(),
        "custom.gpt-5.3-codex",
        _provider("openai", "https://api.openai.com/v1", "OPENAI_API_KEY"),
        "gpt-5.3-codex",
        "Custom Codex",
    )
    config_path = tmp_path / "config.toml"
    config_path.write_text(dumps_public_config(load_public_config(), HEADER_LINES), encoding="utf-8")

    save_public_config(public_config, config_path)
    dumped = config_path.read_text(encoding="utf-8")

    assert '[llm.model_library."custom.gpt-5.3-codex"]' in dumped
    assert "[llm.providers]" not in dumped


def test_load_public_config_recovers_from_legacy_dotted_model_library_shape(tmp_path):
    legacy_text = """
[llm]

[llm.model_library.custom.gpt-5.3-codex]
model = "gpt-5.3-codex"
label = "Custom Codex"
api_key_env = "VIBELUTION_LLM_CUSTOM_GPT_5_3_CODEX_API_KEY"

[llm.model_library.custom.gpt-5.3-codex.provider]
kind = "openai"
api_key_env = "OPENAI_API_KEY"
base_url = "https://api.openai.com/v1"
compat_mode = "openai"
requires_api_key = true
context_window = 400000
""".strip()
    config_path = tmp_path / "config.toml"
    config_path.write_text(legacy_text, encoding="utf-8")

    loaded = load_public_config(config_path)

    assert loaded["llm"]["model_library"]["custom.gpt-5.3-codex"]["label"] == "Custom Codex"
    assert loaded["llm"]["model_library"]["custom.gpt-5.3-codex"]["provider"]["kind"] == "openai"


def test_build_effective_config_from_public_structure_uses_inline_provider():
    public_config = load_public_config()
    config = build_effective_config(public_config)
    profile = config.llm.get_profile("subagent_explorer")
    provider = config.llm.get_provider(profile.provider_id)
    explorer_public = public_config["llm"]["profiles"]["subagent_explorer"]

    assert config.runtime.profile == "safe_remote"
    assert profile.model == explorer_public["model"]
    assert profile.contract == explorer_public.get("contract", profile.contract)
    assert profile.reasoning_state_field == explorer_public.get("reasoning_state_field", "")
    assert provider.kind == explorer_public["provider"]["kind"]
    assert config.ui.language == public_config["ui"]["language"]


def test_inspect_public_config_summarizes_effective_state():
    public_config = load_public_config()

    snapshot = inspect_public_config(public_config)
    summary = snapshot["summary"]
    diagnosis = snapshot["diagnosis"]
    effective = snapshot["effective"]

    assert summary["provider_count"] == len(effective.llm.providers)
    assert summary["profile_count"] == len(public_config["llm"]["profiles"])
    assert summary["model_library_count"] == len(public_config["llm"]["model_library"])
    assert summary["selectable_model_count"] == len(list_llm_model_options(public_config))
    assert summary["blocking_count"] == len(diagnosis["blocking_issues"])
    assert summary["warning_count"] == len(diagnosis["warnings"])
    assert summary["action_count"] == len(diagnosis["suggested_actions"])
    assert summary["active_profile_id"] == effective.llm.get_profile(role="primary").profile_id
