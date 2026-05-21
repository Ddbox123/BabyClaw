"""Public config workflows shared by the config panel and tests."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import tomllib
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from core.llm import assert_llm_compatibility

from .llm_security import (
    coerce_llm_probe_timeout,
    redact_llm_probe_error,
    validate_llm_api_key_env,
    validate_llm_provider_target,
    validate_llm_public_config,
)
from .models import AppConfig
from .profiles import apply_runtime_profile
from .settings import (
    PROFILE_REFERENCE_OVERRIDE_FIELDS,
    PUBLIC_INLINE_PROVIDER_FIELDS,
    UNCONFIGURED_MODEL_REF,
    denormalize_config_dict,
    normalize_public_config_dict,
)
from .toml_writer import dumps_public_config


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.toml"
HEADER_LINES = [
    "# ============================================================",
    "# Self-Evolving Agent 主配置",
    "# ============================================================",
    "# 本文件是项目的完整主配置面。想知道项目当前如何运行，先看这里。",
    "# 模型默认值仅作为最低优先级兜底。",
    "# 配置优先级：命令行参数(kwargs) > 环境变量 > config.toml > 默认值",
    "# ============================================================",
]
MODEL_LIBRARY_DETAIL_FIELDS = (
    "api_key_env",
    "transport",
    "contract",
    "reasoning_state_field",
    "strict_compatibility",
    "temperature",
    "max_output_tokens",
    "timeout",
    "connect_timeout",
    "streaming",
    "tool_calling_mode",
    "discovery_enabled",
)
PUBLIC_PROVIDER_FIELDS = PUBLIC_INLINE_PROVIDER_FIELDS
PROFILE_OVERRIDE_FIELDS = PROFILE_REFERENCE_OVERRIDE_FIELDS
LLM_MODEL_PRESETS = {
    "openai_gpt_5_5": {
        "label": "OpenAI GPT-5.5",
        "provider_id": "openai_main",
        "model_id": "openai_gpt_5_5",
        "provider": {
            "kind": "openai",
            "api_key_env": "OPENAI_API_KEY",
            "base_url": "https://api.openai.com/v1",
            "compat_mode": "openai",
            "requires_api_key": True,
            "context_window": 1050000,
        },
        "model": {
            "model": "gpt-5.5",
            "label": "OpenAI GPT-5.5",
            "transport": "chat_completions",
            "contract": "tool_chat",
            "temperature": 0.7,
            "max_output_tokens": 128000,
            "timeout": 120,
            "connect_timeout": 20,
            "streaming": True,
            "tool_calling_mode": "auto",
            "discovery_enabled": True,
        },
    },
    "openai_gpt_5_4": {
        "label": "OpenAI GPT-5.4",
        "provider_id": "openai_main",
        "model_id": "openai_gpt_5_4",
        "provider": {
            "kind": "openai",
            "api_key_env": "OPENAI_API_KEY",
            "base_url": "https://api.openai.com/v1",
            "compat_mode": "openai",
            "requires_api_key": True,
            "context_window": 1047576,
        },
        "model": {
            "model": "gpt-5.4",
            "label": "OpenAI GPT-5.4",
            "transport": "chat_completions",
            "contract": "tool_chat",
            "temperature": 0.7,
            "max_output_tokens": 128000,
            "timeout": 120,
            "connect_timeout": 20,
            "streaming": True,
            "tool_calling_mode": "auto",
            "discovery_enabled": True,
        },
    },
    "openai_gpt_5_3_codex": {
        "label": "OpenAI GPT-5.3 Codex",
        "provider_id": "openai_main",
        "model_id": "openai_gpt_5_3_codex",
        "provider": {
            "kind": "openai",
            "api_key_env": "OPENAI_API_KEY",
            "base_url": "https://api.openai.com/v1",
            "compat_mode": "openai",
            "requires_api_key": True,
            "context_window": 400000,
        },
        "model": {
            "model": "gpt-5.3-codex",
            "label": "OpenAI GPT-5.3 Codex",
            "transport": "chat_completions",
            "contract": "tool_chat",
            "temperature": 0.7,
            "max_output_tokens": 128000,
            "timeout": 120,
            "connect_timeout": 20,
            "streaming": True,
            "tool_calling_mode": "auto",
            "discovery_enabled": True,
        },
    },
    "anthropic_claude_sonnet": {
        "label": "Anthropic Claude Sonnet",
        "provider_id": "anthropic_main",
        "model_id": "anthropic_claude_sonnet",
        "provider": {
            "kind": "anthropic",
            "api_key_env": "ANTHROPIC_API_KEY",
            "base_url": "https://api.anthropic.com",
            "compat_mode": "native",
            "requires_api_key": True,
            "context_window": 200000,
        },
        "model": {
            "model": "claude-sonnet-4-6",
            "label": "Anthropic Claude Sonnet",
            "transport": "chat_completions",
            "contract": "tool_chat",
            "temperature": 0.7,
            "max_output_tokens": 8192,
            "timeout": 120,
            "connect_timeout": 20,
            "streaming": True,
            "tool_calling_mode": "auto",
            "discovery_enabled": True,
        },
    },
    "deepseek_v4_flash": {
        "label": "DeepSeek V4 Flash",
        "provider_id": "deepseek_main",
        "model_id": "deepseek_v4_flash",
        "provider": {
            "kind": "deepseek",
            "api_key_env": "DEEPSEEK_API_KEY",
            "base_url": "https://api.deepseek.com",
            "compat_mode": "openai",
            "requires_api_key": True,
            "context_window": 1000000,
        },
        "model": {
            "model": "deepseek-v4-flash",
            "label": "DeepSeek V4 Flash",
            "transport": "chat_completions",
            "contract": "reasoning_chat",
            "reasoning_state_field": "reasoning_content",
            "temperature": 0.7,
            "max_output_tokens": 384000,
            "timeout": 120,
            "connect_timeout": 20,
            "streaming": True,
            "tool_calling_mode": "auto",
            "discovery_enabled": True,
        },
    },
    "deepseek_v4_pro": {
        "label": "DeepSeek V4 Pro",
        "provider_id": "deepseek_main",
        "model_id": "deepseek_v4_pro",
        "provider": {
            "kind": "deepseek",
            "api_key_env": "DEEPSEEK_API_KEY",
            "base_url": "https://api.deepseek.com",
            "compat_mode": "openai",
            "requires_api_key": True,
            "context_window": 1000000,
        },
        "model": {
            "model": "deepseek-v4-pro",
            "label": "DeepSeek V4 Pro",
            "transport": "chat_completions",
            "contract": "reasoning_chat",
            "reasoning_state_field": "reasoning_content",
            "temperature": 0.7,
            "max_output_tokens": 384000,
            "timeout": 120,
            "connect_timeout": 20,
            "streaming": True,
            "tool_calling_mode": "auto",
            "discovery_enabled": True,
        },
    },
    "google_gemini_flash": {
        "label": "Google Gemini Flash",
        "provider_id": "google_main",
        "model_id": "google_gemini_flash",
        "provider": {
            "kind": "google",
            "api_key_env": "GOOGLE_API_KEY",
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
            "compat_mode": "openai",
            "requires_api_key": True,
            "context_window": 1048576,
        },
        "model": {
            "model": "gemini-3-flash-preview",
            "label": "Google Gemini Flash",
            "transport": "chat_completions",
            "contract": "tool_chat",
            "temperature": 0.7,
            "max_output_tokens": 8192,
            "timeout": 120,
            "connect_timeout": 20,
            "streaming": True,
            "tool_calling_mode": "auto",
            "discovery_enabled": True,
        },
    },
    "minimax_m2_7": {
        "label": "MiniMax M2.7",
        "provider_id": "minimax_main",
        "model_id": "minimax_m2_7",
        "provider": {
            "kind": "minimax",
            "api_key_env": "MINIMAX_API_KEY",
            "base_url": "https://api.minimax.io/v1",
            "compat_mode": "openai",
            "requires_api_key": True,
            "context_window": 204800,
        },
        "model": {
            "model": "MiniMax-M2.7",
            "label": "MiniMax M2.7",
            "transport": "chat_completions",
            "contract": "tool_chat",
            "temperature": 1.0,
            "max_output_tokens": 8192,
            "timeout": 120,
            "connect_timeout": 20,
            "streaming": True,
            "tool_calling_mode": "auto",
            "discovery_enabled": True,
        },
    },
    "dashscope_qwen3_6_plus": {
        "label": "阿里云 DashScope Qwen3.6 Plus",
        "provider_id": "dashscope_main",
        "model_id": "dashscope_qwen3_6_plus",
        "provider": {
            "kind": "aliyun",
            "api_key_env": "DASHSCOPE_API_KEY",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "compat_mode": "openai",
            "requires_api_key": True,
            "context_window": 131072,
        },
        "model": {
            "model": "qwen3.6-plus",
            "label": "阿里云 DashScope Qwen3.6 Plus",
            "transport": "chat_completions",
            "contract": "tool_chat",
            "temperature": 0.7,
            "max_output_tokens": 8192,
            "timeout": 120,
            "connect_timeout": 20,
            "streaming": True,
            "tool_calling_mode": "auto",
            "discovery_enabled": True,
        },
    },
    "siliconflow_glm_4_7": {
        "label": "硅基流动 GLM-4.7",
        "provider_id": "siliconflow_main",
        "model_id": "siliconflow_glm_4_7",
        "provider": {
            "kind": "siliconflow",
            "api_key_env": "SILICONFLOW_API_KEY",
            "base_url": "https://api.siliconflow.cn/v1",
            "compat_mode": "openai",
            "requires_api_key": True,
            "context_window": 131072,
        },
        "model": {
            "model": "Pro/zai-org/GLM-4.7",
            "label": "硅基流动 GLM-4.7",
            "transport": "chat_completions",
            "contract": "tool_chat",
            "temperature": 0.7,
            "max_output_tokens": 8192,
            "timeout": 120,
            "connect_timeout": 20,
            "streaming": True,
            "tool_calling_mode": "auto",
            "discovery_enabled": True,
        },
    },
    "local_openai_compatible": {
        "label": "本地 OpenAI-compatible",
        "provider_id": "local_main",
        "model_id": "local_openai_compatible",
        "provider": {
            "kind": "local",
            "api_key_env": "",
            "base_url": "http://localhost:11434/v1/",
            "compat_mode": "openai",
            "requires_api_key": False,
            "context_window": 65536,
        },
        "model": {
            "model": "llama3.2",
            "label": "本地 OpenAI-compatible",
            "transport": "chat_completions",
            "contract": "basic_chat",
            "temperature": 0.3,
            "max_output_tokens": 2048,
            "timeout": 45,
            "connect_timeout": 5,
            "streaming": False,
            "tool_calling_mode": "disabled",
            "discovery_enabled": False,
        },
    },
}


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401, ANN001
        return None


def _load_raw_public_config(config_path: Path) -> dict:
    raw_text = config_path.read_text(encoding="utf-8")
    try:
        return tomllib.loads(raw_text)
    except tomllib.TOMLDecodeError:
        backup_path = config_path.with_suffix(config_path.suffix + ".bak")
        if not backup_path.exists():
            raise
        return tomllib.loads(backup_path.read_text(encoding="utf-8"))


def _public_provider_entry(provider: Any) -> dict[str, Any]:
    if not isinstance(provider, dict):
        return {}
    entry: dict[str, Any] = {}
    for key in PUBLIC_PROVIDER_FIELDS:
        if key in provider:
            entry[key] = copy.deepcopy(provider[key])
    return entry


def _owner_provider(owner: Any) -> dict[str, Any]:
    if not isinstance(owner, dict):
        return {}
    return _public_provider_entry(owner.get("provider"))


def _profile_model_ref(profile: Any) -> str:
    if not isinstance(profile, dict):
        return ""
    return str(profile.get("model_ref", "") or "").strip()


def _provider_fingerprint(provider: dict[str, Any]) -> str:
    payload = json.dumps(_public_provider_entry(provider), ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _generated_model_id(provider: dict[str, Any], model: str) -> str:
    fingerprint = _provider_fingerprint(provider)
    raw = f"generated-{fingerprint}-{str(model or '').strip().lower()}"
    return "".join(char if char.isalnum() else "_" for char in raw).strip("_") or "generated_model"


def _flatten_model_library_entries(node: Any, prefix: str = "") -> dict[str, dict]:
    flattened: dict[str, dict] = {}
    if not isinstance(node, dict):
        return flattened
    for key, value in node.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if not isinstance(value, dict):
            continue
        model = str(value.get("model", "")).strip()
        provider = _owner_provider(value)
        provider_id = str(value.get("provider_id", "")).strip()
        if model and (provider or provider_id):
            flattened[path] = copy.deepcopy(value)
            continue
        flattened.update(_flatten_model_library_entries(value, path))
    return flattened


def _repair_legacy_model_library_shape(public_config: dict) -> dict:
    repaired = copy.deepcopy(public_config)
    llm = repaired.get("llm", {})
    if not isinstance(llm, dict):
        return repaired
    model_library = llm.get("model_library", {})
    if not isinstance(model_library, dict):
        return repaired
    flattened = _flatten_model_library_entries(model_library)
    if not flattened:
        return repaired
    if flattened == model_library:
        return repaired
    llm["model_library"] = flattened
    return repaired


def _canonicalize_public_config(public_config: dict) -> dict:
    normalized = normalize_public_config_dict(public_config)
    denormalized = denormalize_config_dict(normalized)
    return _repair_legacy_model_library_shape(denormalized)


def public_config_hash(public_config: dict) -> str:
    canonical = _canonicalize_public_config(public_config)
    payload = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_public_config(config_path: Path = CONFIG_PATH) -> dict:
    raw = _load_raw_public_config(config_path)
    return _canonicalize_public_config(raw)


def build_effective_config(public_config: dict) -> AppConfig:
    normalized = normalize_public_config_dict(_canonicalize_public_config(public_config))
    config = AppConfig.model_validate(normalized)
    effective = apply_runtime_profile(config)
    assert_llm_compatibility(effective)
    return effective


def _model_library_id(provider_id: str, model: str) -> str:
    raw = f"{provider_id}-{model}".strip("-").lower()
    return "".join(char if char.isalnum() else "_" for char in raw).strip("_") or "model"


def _default_model_api_key_env(model_id: str) -> str:
    token = "".join(char if char.isalnum() else "_" for char in str(model_id or "").upper()).strip("_")
    return f"VIBELUTION_LLM_{token}_API_KEY" if token else "VIBELUTION_LLM_MODEL_API_KEY"


def _resolve_model_reference(public_config: dict, model_id: str) -> dict[str, Any]:
    llm = public_config.get("llm", {})
    if not isinstance(llm, dict):
        return {}

    model_library = llm.get("model_library", {})
    if isinstance(model_library, dict):
        item = model_library.get(model_id, {})
        if isinstance(item, dict):
            provider = _owner_provider(item)
            model = str(item.get("model", "")).strip()
            if provider and model:
                return {"source": "model_library", "provider": provider, "model": model, "model_id": model_id}

    profiles = llm.get("profiles", {})
    if not isinstance(profiles, dict):
        return {}
    for profile_id, profile in profiles.items():
        if not isinstance(profile, dict):
            continue
        provider = _owner_provider(profile)
        model = str(profile.get("model", "")).strip()
        if provider and model and _generated_model_id(provider, model) == model_id:
            return {
                "source": "profile",
                "provider": provider,
                "model": model,
                "profile_id": str(profile_id),
            }
    return {}


def _read_windows_user_env_var(name: str) -> str:
    if os.name != "nt":
        return ""
    try:
        import subprocess

        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", f"[Environment]::GetEnvironmentVariable('{name}', 'User')"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def _read_env_var(name: str) -> str:
    value = os.environ.get(name, "")
    if value:
        return value
    fallback_enabled = str(os.environ.get("VIBELUTION_ENABLE_USER_ENV_FALLBACK", "") or "").strip().lower()
    if fallback_enabled not in {"1", "true", "yes", "on"}:
        return ""
    return _read_windows_user_env_var(name)


def _broadcast_windows_environment_change(timeout_ms: int = 5000) -> None:
    try:
        import ctypes
    except ImportError:
        return
    hwnd_broadcast = 0xFFFF
    wm_settingchange = 0x001A
    smto_abortifhung = 0x0002
    result = ctypes.c_size_t()
    try:
        ctypes.windll.user32.SendMessageTimeoutW(
            hwnd_broadcast,
            wm_settingchange,
            0,
            "Environment",
            smto_abortifhung,
            timeout_ms,
            ctypes.byref(result),
        )
    except Exception:
        return


def _write_windows_user_env_var(name: str, value: str | None) -> None:
    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
        if value is None:
            try:
                winreg.DeleteValue(key, name)
            except FileNotFoundError:
                pass
        else:
            reg_type = winreg.REG_EXPAND_SZ if "%" in value else winreg.REG_SZ
            winreg.SetValueEx(key, name, 0, reg_type, value)
    _broadcast_windows_environment_change()


def _set_user_env_var(name: str, value: str) -> None:
    name = validate_llm_api_key_env(name, required=True)
    os.environ[name] = value
    if os.name != "nt":
        return
    _write_windows_user_env_var(name, value)


def _delete_user_env_var(name: str) -> None:
    name = validate_llm_api_key_env(name, required=False)
    if not name:
        return
    os.environ.pop(name, None)
    if os.name != "nt":
        return
    _write_windows_user_env_var(name, None)


def _coerce_model_library_detail(key: str, value):
    if value in ("", None):
        return None
    if key == "api_key_env":
        return str(value).strip()
    if key in {"transport", "contract", "reasoning_state_field"}:
        return str(value).strip()
    if key == "temperature":
        return float(value)
    if key in {"max_output_tokens", "timeout", "connect_timeout"}:
        return int(value)
    if key in {"streaming", "discovery_enabled", "strict_compatibility"}:
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}
    return str(value).strip()


def _model_library_details(item: dict) -> dict:
    details = {}
    for key in MODEL_LIBRARY_DETAIL_FIELDS:
        if key not in item:
            continue
        value = _coerce_model_library_detail(key, item.get(key))
        if value is not None:
            details[key] = value
    return details


def _provider_kind(provider: dict[str, Any]) -> str:
    return str(provider.get("kind", "")).strip() or "provider"


def _resolve_public_provider_input(public_config: dict, provider_input: Any, fallback: Any = None) -> dict[str, Any]:
    if isinstance(provider_input, dict):
        provider = _public_provider_entry(provider_input)
        if provider:
            return provider

    token = str(provider_input or "").strip()
    if token:
        llm = public_config.get("llm", {})
        providers = llm.get("providers", {}) if isinstance(llm, dict) else {}
        if isinstance(providers, dict) and token in providers:
            provider = _public_provider_entry(providers.get(token))
            if provider:
                return provider
        raise ValueError(f"unknown LLM provider: {token}")

    provider = _public_provider_entry(fallback)
    if provider:
        return provider
    raise ValueError("provider is required")


def _model_library_entry(provider: dict[str, Any], model: str, label: str, details: dict | None = None) -> dict:
    entry = {
        "provider": _public_provider_entry(provider),
        "model": model,
        "label": label or model,
    }
    if details:
        entry.update(_model_library_details(details))
    return entry


def list_llm_model_preset_options() -> list[dict[str, object]]:
    return [
        {
            "preset_id": preset_id,
            "label": str(preset["label"]),
            "provider_id": str(preset["provider_id"]),
            "model_id": str(preset["model_id"]),
            "provider": copy.deepcopy(preset["provider"]),
            "model": copy.deepcopy(preset["model"]),
        }
        for preset_id, preset in LLM_MODEL_PRESETS.items()
    ]


def apply_llm_model_preset(
    public_config: dict,
    preset_id: str,
    model_id: str = "",
    provider_id: Any = "",
    model: str = "",
    label: str = "",
    details: dict | None = None,
    api_key_env: str = "",
) -> dict:
    preset_id = (preset_id or "").strip()
    if preset_id not in LLM_MODEL_PRESETS:
        raise ValueError(f"unknown LLM model preset: {preset_id}")

    preset = LLM_MODEL_PRESETS[preset_id]
    resolved_model_id = (model_id or str(preset["model_id"])).strip()
    resolved_provider = _resolve_public_provider_input(public_config, provider_id, fallback=preset["provider"])
    validate_llm_provider_target(resolved_provider, context="llm.model_library")
    if api_key_env:
        api_key_env = validate_llm_api_key_env(api_key_env, context="llm.model_library.api_key_env")
    model_defaults = copy.deepcopy(preset["model"])
    model_defaults.update(_model_library_details(details or {}))
    resolved_model = (model or str(model_defaults.get("model", ""))).strip()
    resolved_label = (label or str(model_defaults.get("label", "")) or resolved_model).strip()
    if not resolved_model_id:
        raise ValueError("model_id is required")
    if not resolved_model:
        raise ValueError("model is required")

    updated = copy.deepcopy(public_config)
    llm = updated.setdefault("llm", {})
    model_library = llm.setdefault("model_library", {})
    if not isinstance(model_library, dict):
        raise ValueError("llm.model_library must be an object")
    if resolved_model_id in model_library:
        raise ValueError(f"LLM model already exists: {resolved_model_id}")

    model_defaults["model"] = resolved_model
    model_defaults["label"] = resolved_label
    entry = _model_library_entry(resolved_provider, resolved_model, resolved_label, model_defaults)
    entry["api_key_env"] = (api_key_env or _default_model_api_key_env(resolved_model_id)).strip()
    model_library[resolved_model_id] = entry
    build_effective_config(updated)
    return updated


def list_llm_model_options(public_config: dict) -> list[dict[str, object]]:
    llm = public_config.get("llm", {})
    profiles = llm.get("profiles", {}) if isinstance(llm, dict) else {}
    model_library = llm.get("model_library", {}) if isinstance(llm, dict) else {}
    options: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()

    if isinstance(model_library, dict):
        for model_id, item in model_library.items():
            if not isinstance(item, dict):
                continue
            provider = _owner_provider(item)
            model = str(item.get("model", "")).strip()
            if not provider or not model:
                continue
            key = (_provider_fingerprint(provider), model)
            label = str(item.get("label", "")).strip() or model
            options.append(
                {
                    "model_id": str(model_id),
                    "source": "model_library",
                    "provider": provider,
                    "provider_kind": _provider_kind(provider),
                    "model": model,
                    "label": label,
                    "details": _model_library_details(item),
                    "api_key_env": str(item.get("api_key_env", "")).strip(),
                    "api_key_configured": bool(_read_env_var(str(item.get("api_key_env", "")).strip())),
                }
            )
            seen.add(key)

    if isinstance(profiles, dict):
        for profile in profiles.values():
            if not isinstance(profile, dict):
                continue
            provider = _owner_provider(profile)
            model = str(profile.get("model", "")).strip()
            if not provider or not model:
                continue
            key = (_provider_fingerprint(provider), model)
            if key in seen:
                continue
            provider_kind = _provider_kind(provider)
            generated_model_id = _generated_model_id(provider, model)
            generated_api_key_env = str(profile.get("api_key_env", "")).strip() or _default_model_api_key_env(generated_model_id)
            options.append(
                {
                    "model_id": generated_model_id,
                    "source": "profile",
                    "provider": provider,
                    "provider_kind": provider_kind,
                    "model": model,
                    "label": model,
                    "details": _model_library_details(profile),
                    "api_key_env": generated_api_key_env,
                    "api_key_configured": bool(_read_env_var(generated_api_key_env)),
                }
            )
            seen.add(key)
    return options


def add_llm_model(
    public_config: dict,
    model_id: str,
    provider_id: Any,
    model: str,
    label: str = "",
    details: dict | None = None,
    api_key_env: str = "",
) -> dict:
    model_id = (model_id or "").strip()
    model = (model or "").strip()
    label = (label or "").strip()
    if not model_id:
        raise ValueError("model_id is required")
    if not model:
        raise ValueError("model is required")

    provider = _resolve_public_provider_input(public_config, provider_id)
    validate_llm_provider_target(provider, context="llm.model_library")
    if api_key_env:
        api_key_env = validate_llm_api_key_env(api_key_env, context="llm.model_library.api_key_env")
    updated = copy.deepcopy(public_config)
    llm = updated.setdefault("llm", {})
    model_library = llm.setdefault("model_library", {})
    if not isinstance(model_library, dict):
        raise ValueError("llm.model_library must be an object")
    if model_id in model_library:
        raise ValueError(f"LLM model already exists: {model_id}")
    entry = _model_library_entry(provider, model, label or model, details)
    entry["api_key_env"] = (
        api_key_env or entry.get("api_key_env") or _default_model_api_key_env(model_id)
    ).strip()
    model_library[model_id] = entry
    build_effective_config(updated)
    return updated


def update_llm_model(
    public_config: dict,
    model_id: str,
    provider_id: Any,
    model: str,
    label: str = "",
    details: dict | None = None,
    api_key_env: str = "",
) -> dict:
    model_id = (model_id or "").strip()
    model = (model or "").strip()
    label = (label or "").strip()
    if not model_id:
        raise ValueError("model_id is required")
    if not model:
        raise ValueError("model is required")

    updated = copy.deepcopy(public_config)
    llm = updated.setdefault("llm", {})
    model_library = llm.setdefault("model_library", {})
    if not isinstance(model_library, dict):
        raise ValueError("llm.model_library must be an object")
    existing = model_library.get(model_id, {}) if isinstance(model_library.get(model_id, {}), dict) else {}
    provider = _resolve_public_provider_input(updated, provider_id, fallback=existing.get("provider"))
    validate_llm_provider_target(provider, context="llm.model_library")
    if api_key_env:
        api_key_env = validate_llm_api_key_env(api_key_env, context="llm.model_library.api_key_env")
    entry = _model_library_entry(provider, model, label or model, details)
    entry["api_key_env"] = (
        api_key_env
        or entry.get("api_key_env")
        or existing.get("api_key_env")
        or _default_model_api_key_env(model_id)
    ).strip()
    model_library[model_id] = entry
    build_effective_config(updated)
    return updated


def delete_llm_model(public_config: dict, model_id: str) -> dict:
    updated = copy.deepcopy(public_config)
    llm = updated.setdefault("llm", {})
    reference = _resolve_model_reference(updated, model_id)
    model_library = llm.get("model_library", {})
    if isinstance(model_library, dict) and reference.get("source") == "model_library":
        model_library.pop(model_id, None)
    elif not isinstance(model_library, dict):
        llm["model_library"] = {}
    profiles = llm.get("profiles", {})
    if isinstance(profiles, dict):
        for profile in profiles.values():
            if not isinstance(profile, dict):
                continue
            if _profile_model_ref(profile) != model_id:
                continue
            profile["model_ref"] = UNCONFIGURED_MODEL_REF
            profile["overrides"] = {}
            profile.pop("provider", None)
            profile.pop("model", None)
            for key in PROFILE_OVERRIDE_FIELDS:
                profile.pop(key, None)

    provider = reference.get("provider", {}) if isinstance(reference, dict) else {}
    model = str(reference.get("model", "")).strip() if isinstance(reference, dict) else ""
    provider_fingerprint = _provider_fingerprint(provider) if provider else ""
    if reference.get("source") == "profile" and provider_fingerprint and model and isinstance(profiles, dict):
        for profile in profiles.values():
            if not isinstance(profile, dict):
                continue
            if str(profile.get("model", "")).strip() != model:
                continue
            if _provider_fingerprint(_owner_provider(profile)) != provider_fingerprint:
                continue
            profile["model"] = ""
    build_effective_config(updated)
    return updated


def set_llm_model_api_key(public_config: dict, model_id: str, api_key: str) -> str:
    llm = public_config.get("llm", {})
    model_library = llm.get("model_library", {}) if isinstance(llm, dict) else {}
    item = model_library.get(model_id, {}) if isinstance(model_library, dict) else {}
    if not isinstance(item, dict):
        raise ValueError(f"unknown LLM model: {model_id}")
    api_key_env = validate_llm_api_key_env(
        str(item.get("api_key_env") or _default_model_api_key_env(model_id)).strip(),
        required=True,
    )
    item["api_key_env"] = api_key_env
    _set_user_env_var(api_key_env, api_key)
    return api_key_env


def clear_llm_model_api_key(public_config: dict, model_id: str) -> str:
    llm = public_config.get("llm", {})
    model_library = llm.get("model_library", {}) if isinstance(llm, dict) else {}
    item = model_library.get(model_id, {}) if isinstance(model_library, dict) else {}
    if not isinstance(item, dict):
        raise ValueError(f"unknown LLM model: {model_id}")
    api_key_env = validate_llm_api_key_env(
        str(item.get("api_key_env") or _default_model_api_key_env(model_id)).strip(),
        required=True,
    )
    item["api_key_env"] = api_key_env
    _delete_user_env_var(api_key_env)
    return api_key_env


def _find_profile_id_for_provider(public_config: dict, provider_id: str) -> str:
    effective = build_effective_config(public_config)
    for profile_id, profile in effective.llm.profiles.items():
        if effective.llm.get_provider(profile.provider_id).provider_id == provider_id:
            return str(profile_id)
    raise ValueError(f"no LLM profile uses provider: {provider_id}")


def add_llm_profile(
    public_config: dict,
    profile_id: str,
    provider_id: Any = "",
    model: str = "",
    *,
    source_profile_id: str = "primary",
    model_id: str = "",
) -> dict:
    profile_id = (profile_id or "").strip()
    model = (model or "").strip()
    if not profile_id:
        raise ValueError("profile_id is required")

    updated = copy.deepcopy(public_config)
    llm = updated.setdefault("llm", {})
    profiles = llm.setdefault("profiles", {})
    if not isinstance(profiles, dict):
        raise ValueError("llm.profiles must be an object")
    if profile_id in profiles:
        raise ValueError(f"LLM profile already exists: {profile_id}")

    source_id = (source_profile_id or "").strip() or ("primary" if "primary" in profiles else next(iter(profiles), ""))
    source_profile = profiles.get(source_id, {}) if isinstance(profiles.get(source_id, {}), dict) else {}
    new_profile = copy.deepcopy(source_profile)
    if model_id:
        selected_option = next(
            (item for item in list_llm_model_options(updated) if str(item.get("model_id")) == model_id),
            None,
        )
        if not selected_option:
            raise ValueError(f"unknown LLM model: {model_id}")
        for key in MODEL_LIBRARY_DETAIL_FIELDS:
            new_profile.pop(key, None)
        new_profile["provider"] = copy.deepcopy(selected_option.get("provider", {}))
        new_profile["model"] = str(selected_option.get("model", "")).strip()
        new_profile.update(_model_library_details(selected_option.get("details", {})))
        new_profile["api_key_env"] = validate_llm_api_key_env(
            str(selected_option.get("api_key_env", "")).strip(),
            context="llm.profiles.api_key_env",
        )
    else:
        if not model:
            raise ValueError("model is required")
        new_profile["provider"] = _resolve_public_provider_input(updated, provider_id, fallback=source_profile.get("provider"))
        validate_llm_provider_target(new_profile["provider"], context="llm.profiles.provider")
        new_profile["model"] = model
    profiles[profile_id] = new_profile
    build_effective_config(updated)
    return updated


def _probe_llm_http(provider, profile, api_key: str | None = None) -> dict:
    if provider.requires_api_key and not api_key:
        return {"ok": False, "message": f"missing API key for provider `{provider.provider_id}`"}
    if not provider.requires_api_key:
        api_key = None
    if not provider.base_url:
        return {"ok": False, "message": f"missing base_url for provider `{provider.provider_id}`"}
    try:
        validate_llm_provider_target(provider, context="probe", resolve_dns=True)
    except ValueError as exc:
        return {"ok": False, "message": str(exc)}

    base_url = provider.base_url.rstrip("/")
    url = f"{base_url}/chat/completions"
    payload = {
        "model": profile.model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
        "temperature": 0,
        "stream": False,
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        timeout = coerce_llm_probe_timeout(profile.connect_timeout, profile.timeout)
        opener = urllib.request.build_opener(_NoRedirectHandler)
        with opener.open(request, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            if 200 <= status < 300:
                return {"ok": True, "message": f"connected to {profile.model}"}
            return {"ok": False, "message": f"HTTP {status}"}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "message": f"HTTP {exc.code}: {exc.reason}"}
    except Exception as exc:
        return {"ok": False, "message": redact_llm_probe_error(str(exc), api_key=api_key)}


def test_llm_connection(public_config: dict, profile_id: str | None = None) -> dict:
    validate_llm_public_config(public_config)
    effective = build_effective_config(public_config)
    profile = effective.llm.get_profile(profile_id=profile_id) if profile_id else effective.llm.get_profile(role="primary")
    provider = effective.llm.get_provider(profile.provider_id)
    api_key = effective.get_api_key_for_profile(profile_id=profile.profile_id)
    api_key_source = effective.llm.get_api_key_source_label_for_profile(profile_id=profile.profile_id)
    if not provider.requires_api_key:
        api_key = None
        api_key_source = "not-required"
    try:
        result = _probe_llm_http(provider, profile, api_key)
    except TypeError:
        result = _probe_llm_http(provider, profile)
    return {
        **result,
        "profile_id": profile.profile_id,
        "provider_id": provider.provider_id,
        "provider_kind": provider.kind,
        "base_url": provider.base_url,
        "model": profile.model,
        "api_key_source": api_key_source,
    }


def test_llm_connection_by_provider(public_config: dict, provider_id: str) -> dict:
    profile_id = _find_profile_id_for_provider(public_config, provider_id)
    return test_llm_connection(public_config, profile_id)


def preserve_secret_blanks(new_public: dict, old_public: dict) -> dict:
    result = copy.deepcopy(new_public)

    def walk(new_node, old_node):
        if isinstance(new_node, dict) and isinstance(old_node, dict):
            for key, value in new_node.items():
                if key not in old_node:
                    continue
                if key == "api_key" and value == "" and isinstance(old_node[key], str) and old_node[key]:
                    new_node[key] = old_node[key]
                else:
                    walk(value, old_node[key])
        elif isinstance(new_node, list) and isinstance(old_node, list):
            for idx, item in enumerate(new_node):
                if idx < len(old_node):
                    walk(item, old_node[idx])

    walk(result, old_public)
    return result


def save_public_config(public_config: dict, config_path: Path = CONFIG_PATH) -> None:
    cleaned_public_config = _canonicalize_public_config(public_config)
    config_path.with_suffix(config_path.suffix + ".bak").write_text(
        config_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    config_path.write_text(dumps_public_config(cleaned_public_config, HEADER_LINES), encoding="utf-8")


def _profile_api_key_status(effective: AppConfig) -> tuple[int, int]:
    configured = 0
    missing = 0
    for profile_id in effective.llm.profiles:
        profile = effective.llm.get_profile(profile_id=profile_id)
        provider = effective.llm.get_provider(profile.provider_id)
        if not provider.requires_api_key:
            continue
        if effective.get_api_key_for_profile(profile_id=profile.profile_id):
            configured += 1
        else:
            missing += 1
    return configured, missing


def inspect_public_config(public_config: dict) -> dict[str, Any]:
    effective = build_effective_config(public_config)
    diagnosis = effective.diagnose_config()
    try:
        validate_llm_public_config(public_config)
    except ValueError as exc:
        diagnosis = copy.deepcopy(diagnosis)
        diagnosis.setdefault("blocking_issues", []).append(f"LLM security guard: {exc}")
        diagnosis.setdefault("suggested_actions", []).append(
            "Review LLM provider base_url and api_key_env before testing or applying this config."
        )
    llm = public_config.get("llm", {})
    profiles = llm.get("profiles", {}) if isinstance(llm, dict) else {}
    model_library = llm.get("model_library", {}) if isinstance(llm, dict) else {}
    configured_profiles, missing_api_keys = _profile_api_key_status(effective)
    active_profile = effective.llm.get_profile(role="primary")

    summary = {
        "provider_count": len(effective.llm.providers),
        "profile_count": len(profiles) if isinstance(profiles, dict) else 0,
        "model_library_count": len(model_library) if isinstance(model_library, dict) else 0,
        "selectable_model_count": len(list_llm_model_options(public_config)),
        "configured_profile_count": configured_profiles,
        "missing_api_key_count": missing_api_keys,
        "blocking_count": len(diagnosis["blocking_issues"]),
        "warning_count": len(diagnosis["warnings"]),
        "action_count": len(diagnosis["suggested_actions"]),
        "active_profile_id": active_profile.profile_id,
    }
    return {
        "effective": effective,
        "diagnosis": diagnosis,
        "summary": summary,
    }


__all__ = [
    "CONFIG_PATH",
    "HEADER_LINES",
    "MODEL_LIBRARY_DETAIL_FIELDS",
    "PROFILE_OVERRIDE_FIELDS",
    "LLM_MODEL_PRESETS",
    "UNCONFIGURED_MODEL_REF",
    "public_config_hash",
    "load_public_config",
    "build_effective_config",
    "list_llm_model_preset_options",
    "apply_llm_model_preset",
    "list_llm_model_options",
    "add_llm_model",
    "update_llm_model",
    "delete_llm_model",
    "set_llm_model_api_key",
    "clear_llm_model_api_key",
    "add_llm_profile",
    "test_llm_connection",
    "test_llm_connection_by_provider",
    "preserve_secret_blanks",
    "save_public_config",
    "inspect_public_config",
    "_delete_user_env_var",
    "_set_user_env_var",
    "validate_llm_api_key_env",
    "validate_llm_provider_target",
    "validate_llm_public_config",
]
