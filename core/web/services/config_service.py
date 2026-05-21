"""Config workspace helpers for the web workbench."""

from __future__ import annotations

import copy
import secrets
from typing import Any

import config.public_config as public_config_module
from config.public_config import (
    CONFIG_PATH,
    UNCONFIGURED_MODEL_REF,
    _delete_user_env_var,
    _set_user_env_var,
    add_llm_model,
    add_llm_profile,
    apply_llm_model_preset,
    build_effective_config,
    delete_llm_model,
    inspect_public_config,
    list_llm_model_options,
    list_llm_model_preset_options,
    load_public_config,
    preserve_secret_blanks,
    public_config_hash,
    save_public_config,
    update_llm_model,
    validate_llm_api_key_env,
    validate_llm_public_config,
)

from .config_editor_schema import build_editor_meta, build_editor_sections
from .i18n import resolve_language, text_for
from .workbench_contract_service import get_workbench_contract


class ConfigConflictError(ValueError):
    """Raised when a saved config changed since the draft was loaded."""


PROFILE_LABELS = {
    "primary": {"zh": "主智能体", "en": "Primary"},
    "mental_model": {"zh": "心智模型", "en": "Mental Model"},
    "subagent_worker": {"zh": "子代理 Worker", "en": "Subagent Worker"},
    "subagent_explorer": {"zh": "子代理 Explorer", "en": "Subagent Explorer"},
    "supervised_baseline": {"zh": "监督基线", "en": "Supervised Baseline"},
    "supervised_candidate": {"zh": "监督候选", "en": "Supervised Candidate"},
    "compression": {"zh": "压缩配置", "en": "Compression"},
}
_PENDING_SECRET_PREFIX = "pending-secret:"
_PENDING_API_KEY_SECRETS: dict[str, tuple[str, str]] = {}
_PENDING_CLEAR_ENVS: set[str] = set()


def _resolve_workspace_language(public_config: dict[str, Any]) -> str:
    return resolve_language(public_config.get("ui", {}).get("language", "zh"))


def _config_sections(lang: str, editor_sections: list[dict[str, Any]] | None = None) -> list[dict[str, str]]:
    sections = [
        {
            "id": "overview",
            "title": text_for(lang, zh="配置源", en="Config Source"),
            "summary": text_for(
                lang,
                zh="当前生效网页入口与 config.toml 原始内容都在这里，避免再维护第二套页面。",
                en="The active web entry and raw config.toml source live here so there is only one surface.",
            ),
        },
        {
            "id": "shell",
            "title": text_for(lang, zh="工作台默认项", en="Workbench Defaults"),
            "summary": text_for(
                lang,
                zh="语言、intake mode 和当前工作台默认项可以先在这里快速修改。",
                en="Language, intake mode, and current workbench defaults can be changed here.",
            ),
        },
        {
            "id": "profiles",
            "title": text_for(lang, zh="配置档", en="Profiles"),
            "summary": text_for(
                lang,
                zh="查看各个 profile 当前绑定的模型、密钥状态，并直接做连接测试。",
                en="Inspect bound models, key state, and run direct connection checks per profile.",
            ),
        },
        {
            "id": "models",
            "title": text_for(lang, zh="模型库", en="Models"),
            "summary": text_for(
                lang,
                zh="新增、编辑、删除模型库项时继续复用 public config 的共享变更内核。",
                en="Add, edit, and delete model library entries through the shared public config kernel.",
            ),
        },
    ]
    for section in editor_sections or []:
        sections.append(
            {
                "id": str(section.get("id", "")),
                "title": str(section.get("title", "")),
                "summary": str(section.get("summary", "")),
            }
        )
    sections.extend(
        [
            {
                "id": "draft",
                "title": text_for(lang, zh="高级 JSON 编辑", en="Advanced JSON"),
                "summary": text_for(
                    lang,
                    zh="结构化操作之外，还可以直接检查整份 JSON；保存时仍只写 config.toml。",
                    en="Beyond structured controls, check the full JSON here while saving still writes only config.toml.",
                ),
            },
            {
                "id": "diagnostics",
                "title": text_for(lang, zh="诊断", en="Diagnostics"),
                "summary": text_for(
                    lang,
                    zh="阻塞问题、警告与保存冲突保护会在保存前保持可见。",
                    en="Blocking issues, warnings, and save-conflict protection remain visible before saving.",
                ),
            },
        ]
    )
    return sections


def _empty_draft_meta() -> dict[str, object]:
    return {
        "pending_api_keys": {},
        "pending_cleared_api_keys": [],
    }


def _register_pending_api_key(api_key_env: str, api_key: str) -> str:
    env_name = validate_llm_api_key_env(api_key_env, required=True, context="api_key_env")
    token = f"{_PENDING_SECRET_PREFIX}{secrets.token_urlsafe(24)}"
    _PENDING_API_KEY_SECRETS[token] = (env_name, str(api_key))
    return token


def _resolve_pending_api_key(env_name: str, token: object) -> str | None:
    env_name = validate_llm_api_key_env(env_name, required=True, context="api_key_env")
    value = str(token or "").strip()
    if not value.startswith(_PENDING_SECRET_PREFIX):
        return None
    stored = _PENDING_API_KEY_SECRETS.get(value)
    if not stored:
        return None
    stored_env, secret = stored
    if stored_env != env_name:
        return None
    return secret


def _drop_pending_api_key_token(token: object) -> None:
    value = str(token or "").strip()
    if value.startswith(_PENDING_SECRET_PREFIX):
        _PENDING_API_KEY_SECRETS.pop(value, None)


def _move_pending_api_key_token(token: object, old_env: str, new_env: str) -> None:
    value = str(token or "").strip()
    if not value.startswith(_PENDING_SECRET_PREFIX):
        return
    stored = _PENDING_API_KEY_SECRETS.get(value)
    if not stored:
        return
    stored_env, secret = stored
    if stored_env == old_env:
        _PENDING_API_KEY_SECRETS[value] = (new_env, secret)


def _normalize_draft_meta(meta: dict | None) -> dict[str, object]:
    payload = _empty_draft_meta()
    if not isinstance(meta, dict):
        return payload
    pending = meta.get("pending_api_keys", {})
    if isinstance(pending, dict):
        normalized_pending: dict[str, str] = {}
        for key, value in pending.items():
            env_name = str(key or "").strip()
            if not env_name or str(value) == "":
                continue
            try:
                validate_llm_api_key_env(env_name, required=True, context="api_key_env")
            except ValueError:
                continue
            if _resolve_pending_api_key(env_name, value) is None:
                continue
            normalized_pending[env_name] = str(value)
        payload["pending_api_keys"] = normalized_pending
    cleared = meta.get("pending_cleared_api_keys", [])
    if isinstance(cleared, list):
        normalized_cleared: list[str] = []
        for item in cleared:
            env_name = str(item or "").strip()
            if not env_name:
                continue
            try:
                env_name = validate_llm_api_key_env(env_name, required=True, context="api_key_env")
            except ValueError:
                continue
            if env_name in _PENDING_CLEAR_ENVS and env_name not in normalized_cleared:
                normalized_cleared.append(env_name)
        payload["pending_cleared_api_keys"] = normalized_cleared
    return payload


def _draft_meta_has_pending_changes(draft_meta: dict | None) -> bool:
    meta = _normalize_draft_meta(draft_meta)
    return bool(meta["pending_api_keys"] or meta["pending_cleared_api_keys"])


def _llm_test_config_scope(public_config: dict[str, Any], draft_meta: dict | None) -> str:
    try:
        persisted_hash = public_config_hash(load_public_config())
    except Exception:
        persisted_hash = ""
    draft_hash = public_config_hash(public_config)
    if persisted_hash and draft_hash == persisted_hash and not _draft_meta_has_pending_changes(draft_meta):
        return "saved"
    return "draft"


def _with_pending_api_key(meta: dict[str, object], api_key_env: str, api_key: str) -> dict[str, object]:
    payload = _normalize_draft_meta(meta)
    env_name = validate_llm_api_key_env(api_key_env, required=False, context="api_key_env")
    if not env_name:
        return payload
    pending = payload["pending_api_keys"]
    cleared = payload["pending_cleared_api_keys"]
    if isinstance(pending, dict):
        _drop_pending_api_key_token(pending.get(env_name))
        pending[env_name] = _register_pending_api_key(env_name, api_key)
    if isinstance(cleared, list):
        payload["pending_cleared_api_keys"] = [item for item in cleared if item != env_name]
        _PENDING_CLEAR_ENVS.discard(env_name)
    return payload


def _with_cleared_api_key(meta: dict[str, object], api_key_env: str) -> dict[str, object]:
    payload = _normalize_draft_meta(meta)
    env_name = validate_llm_api_key_env(api_key_env, required=False, context="api_key_env")
    if not env_name:
        return payload
    pending = payload["pending_api_keys"]
    cleared = payload["pending_cleared_api_keys"]
    if isinstance(pending, dict):
        _drop_pending_api_key_token(pending.pop(env_name, None))
    if isinstance(cleared, list) and env_name not in cleared:
        cleared.append(env_name)
        _PENDING_CLEAR_ENVS.add(env_name)
    return payload


def _drop_api_key_state(meta: dict[str, object], api_key_env: str) -> dict[str, object]:
    payload = _normalize_draft_meta(meta)
    env_name = validate_llm_api_key_env(api_key_env, required=False, context="api_key_env")
    if not env_name:
        return payload
    pending = payload["pending_api_keys"]
    cleared = payload["pending_cleared_api_keys"]
    if isinstance(pending, dict):
        _drop_pending_api_key_token(pending.pop(env_name, None))
    if isinstance(cleared, list):
        payload["pending_cleared_api_keys"] = [item for item in cleared if item != env_name]
        _PENDING_CLEAR_ENVS.discard(env_name)
    return payload


def _move_pending_api_key_env(meta: dict[str, object], old_env: str, new_env: str) -> dict[str, object]:
    payload = _normalize_draft_meta(meta)
    old_env = validate_llm_api_key_env(old_env, required=False, context="api_key_env")
    new_env = validate_llm_api_key_env(new_env, required=False, context="api_key_env")
    if not old_env or old_env == new_env:
        return payload
    pending = payload["pending_api_keys"]
    cleared = payload["pending_cleared_api_keys"]
    if isinstance(pending, dict) and old_env in pending and new_env:
        token = pending.pop(old_env)
        _drop_pending_api_key_token(pending.get(new_env))
        _move_pending_api_key_token(token, old_env, new_env)
        pending[new_env] = token
    elif isinstance(pending, dict):
        _drop_pending_api_key_token(pending.pop(old_env, None))
    if isinstance(cleared, list):
        payload["pending_cleared_api_keys"] = [
            new_env if item == old_env and new_env else item
            for item in cleared
            if item != old_env or new_env
        ]
        if old_env in _PENDING_CLEAR_ENVS:
            _PENDING_CLEAR_ENVS.discard(old_env)
            if new_env:
                _PENDING_CLEAR_ENVS.add(new_env)
    return payload


def _api_key_display_state(api_key_env: str, configured: bool, draft_meta: dict | None) -> tuple[bool, str]:
    env_name = str(api_key_env or "").strip()
    meta = _normalize_draft_meta(draft_meta)
    pending = meta["pending_api_keys"]
    cleared = meta["pending_cleared_api_keys"]
    if env_name and isinstance(pending, dict) and env_name in pending:
        return True, "pending"
    if env_name and isinstance(cleared, list) and env_name in cleared:
        return False, "clear_pending"
    return configured, "configured" if configured else "missing"


def _profile_label(profile_id: str, lang: str) -> str:
    mapping = PROFILE_LABELS.get(str(profile_id).strip())
    if mapping:
        return text_for(lang, zh=mapping["zh"], en=mapping["en"])
    token = str(profile_id or "").strip().replace("_", " ")
    return token.title() if lang == "en" else token


def _provider_signature(provider: Any) -> str:
    if not isinstance(provider, dict):
        return ""
    kind = str(provider.get("kind", "")).strip()
    base_url = str(provider.get("base_url", "")).strip().rstrip("/")
    api_key_env = str(provider.get("api_key_env", "")).strip()
    compat_mode = str(provider.get("compat_mode", "")).strip()
    return "|".join((kind, base_url, api_key_env, compat_mode))


def _selected_model_option(public_config: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any] | None:
    model_ref = str(profile.get("model_ref", "")).strip()
    options = list_llm_model_options(public_config)
    if model_ref:
        if model_ref == UNCONFIGURED_MODEL_REF:
            return None
        for option in options:
            if str(option.get("model_id", "")).strip() == model_ref:
                return option
        return None

    provider_signature = _provider_signature(profile.get("provider"))
    model = str(profile.get("model", "")).strip()
    if not provider_signature or not model:
        return None
    for option in options:
        if _provider_signature(option.get("provider")) == provider_signature and str(option.get("model", "")).strip() == model:
            return option
    return None


def _missing_required_llm_profiles(public_config: dict[str, Any]) -> list[str]:
    llm = public_config.get("llm", {})
    profiles = llm.get("profiles", {}) if isinstance(llm, dict) else {}
    if not isinstance(profiles, dict):
        return []
    missing: list[str] = []
    for profile_id, profile in profiles.items():
        if not isinstance(profile, dict):
            missing.append(str(profile_id))
            continue
        if _selected_model_option(public_config, profile) is None:
            missing.append(str(profile_id))
    return missing


def _validate_required_llm_profiles(public_config: dict[str, Any], lang: str) -> None:
    missing = _missing_required_llm_profiles(public_config)
    if not missing:
        return
    display_names = " / ".join(_profile_label(profile_id, lang) for profile_id in missing)
    raise ValueError(
        text_for(
            lang,
            zh=f"以下必需配置档还没有绑定可用模型：{display_names}",
            en=f"These required profiles do not have a usable model bound yet: {display_names}",
        )
    )


def _decorate_model_options(public_config: dict[str, Any], draft_meta: dict | None) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    for option in list_llm_model_options(public_config):
        api_key_env = str(option.get("api_key_env", "")).strip()
        configured = bool(option.get("api_key_configured", False))
        resolved_configured, state = _api_key_display_state(api_key_env, configured, draft_meta)
        decorated = copy.deepcopy(option)
        decorated["api_key_configured"] = resolved_configured
        decorated["api_key_state"] = state
        options.append(decorated)
    return options


def _list_profile_cards(public_config: dict[str, Any], draft_meta: dict | None, lang: str) -> list[dict[str, Any]]:
    effective = build_effective_config(public_config)
    llm = public_config.get("llm", {})
    profiles = llm.get("profiles", {}) if isinstance(llm, dict) else {}
    cards: list[dict[str, Any]] = []
    for profile_id in effective.llm.profiles:
        public_profile = profiles.get(profile_id, {}) if isinstance(profiles, dict) else {}
        public_profile = public_profile if isinstance(public_profile, dict) else {}
        selected = _selected_model_option(public_config, public_profile)
        provider = effective.llm.get_provider(effective.llm.get_profile(profile_id=profile_id).provider_id)
        profile = effective.llm.get_profile(profile_id=profile_id)
        api_key_env = (
            str(public_profile.get("api_key_env", "")).strip()
            or str((selected or {}).get("api_key_env", "")).strip()
            or str(getattr(provider, "api_key_env", "") or "").strip()
        )
        configured = bool(effective.get_api_key_for_profile(profile_id=profile_id))
        resolved_configured, api_key_state = _api_key_display_state(api_key_env, configured, draft_meta)
        api_key_source = effective.llm.get_api_key_source_label_for_profile(profile_id=profile_id)
        if api_key_state == "pending":
            api_key_source = f"pending-env:{api_key_env}"
        elif api_key_state == "clear_pending":
            api_key_source = f"pending-clear:{api_key_env}"
        cards.append(
            {
                "profileId": str(profile_id),
                "label": _profile_label(str(profile_id), lang),
                "modelRef": str(public_profile.get("model_ref", "")).strip(),
                "selectedModelId": str((selected or {}).get("model_id", "")).strip(),
                "selectedModelLabel": str((selected or {}).get("label", "")).strip() or profile.model,
                "model": profile.model,
                "providerKind": provider.kind,
                "baseUrl": provider.base_url,
                "apiKeyEnv": api_key_env,
                "apiKeyConfigured": resolved_configured,
                "apiKeyState": api_key_state,
                "apiKeySource": api_key_source,
                "requiredModelMissing": selected is None,
            }
        )
    return cards


def _run_draft_test_llm_connection(
    public_config: dict[str, Any],
    profile_id: str | None = None,
    draft_meta: dict | None = None,
) -> dict[str, Any]:
    validate_llm_public_config(public_config)
    effective = build_effective_config(public_config)
    profile = effective.llm.get_profile(profile_id=profile_id) if profile_id else effective.llm.get_profile(role="primary")
    provider = effective.llm.get_provider(profile.provider_id)
    api_key = effective.get_api_key_for_profile(profile_id=profile.profile_id)
    api_key_source = effective.llm.get_api_key_source_label_for_profile(profile_id=profile.profile_id)
    if not provider.requires_api_key:
        api_key = None
        api_key_source = "not-required"
    meta = _normalize_draft_meta(draft_meta)
    pending = meta["pending_api_keys"]
    cleared = meta["pending_cleared_api_keys"]
    profile_public = (
        public_config.get("llm", {}).get("profiles", {}).get(profile.profile_id, {})
        if isinstance(public_config.get("llm", {}), dict)
        else {}
    )
    profile_public = profile_public if isinstance(profile_public, dict) else {}
    selected_option = _selected_model_option(public_config, profile_public) or {}
    env_candidates = [
        str(profile_public.get("api_key_env", "")).strip(),
        str(selected_option.get("api_key_env", "")).strip(),
        str(getattr(provider, "api_key_env", "") or "").strip(),
    ]
    if provider.requires_api_key:
        for env_name in env_candidates:
            if not env_name:
                continue
            if isinstance(cleared, list) and env_name in cleared:
                api_key = None
                api_key_source = f"pending-clear:{env_name}"
                break
            if isinstance(pending, dict) and env_name in pending:
                pending_secret = _resolve_pending_api_key(env_name, pending[env_name])
                if pending_secret is not None:
                    api_key = pending_secret
                    api_key_source = f"pending-env:{env_name}"
                    break
    try:
        result = public_config_module._probe_llm_http(provider, profile, api_key)
    except TypeError:
        result = public_config_module._probe_llm_http(provider, profile)
    return {
        **result,
        "profile_id": profile.profile_id,
        "provider_id": provider.provider_id,
        "provider_kind": provider.kind,
        "base_url": provider.base_url,
        "model": profile.model,
        "api_key_source": api_key_source,
        "config_scope": _llm_test_config_scope(public_config, draft_meta),
        "requires_api_key": bool(provider.requires_api_key),
    }


def _read_raw_public_config() -> str:
    try:
        return CONFIG_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def _build_workspace(
    public_config: dict[str, Any],
    *,
    draft_meta: dict | None = None,
    base_hash: str = "",
    message: str = "",
    raw_toml: str | None = None,
) -> dict[str, Any]:
    diagnostics = inspect_public_config(public_config)
    diagnosis = diagnostics.get("diagnosis", {})
    summary = diagnostics.get("summary", {})
    lang = _resolve_workspace_language(public_config)
    contract = get_workbench_contract(public_config)
    llm_cfg = public_config.get("llm", {})
    model_library = llm_cfg.get("model_library", {}) if isinstance(llm_cfg, dict) else {}
    profiles = llm_cfg.get("profiles", {}) if isinstance(llm_cfg, dict) else {}
    draft_hash = public_config_hash(public_config)
    blocking = diagnosis.get("blocking_issues") or []
    warnings = diagnosis.get("warnings") or []
    normalized_meta = _normalize_draft_meta(draft_meta)
    editor_sections = build_editor_sections(public_config, lang)
    editor_meta = build_editor_meta(public_config, lang)

    return {
        "message": message,
        "hash": draft_hash,
        "baseHash": str(base_hash or draft_hash).strip() or draft_hash,
        "language": lang,
        "configPath": str(CONFIG_PATH),
        "runtimeProfile": public_config.get("runtime", {}).get("profile", "safe_local"),
        "defaultMode": contract["defaultMode"],
        "defaultRoute": contract["defaultRoute"],
        "intakeMode": contract["intakeMode"],
        "modeAvailability": contract["modeAvailability"],
        "domainAvailability": contract["domainAvailability"],
        "modelLibraryCount": len(model_library) if isinstance(model_library, dict) else 0,
        "profileCount": len(profiles) if isinstance(profiles, dict) else 0,
        "blockingCount": len(blocking),
        "warningCount": len(warnings),
        "sections": _config_sections(lang, editor_sections),
        "publicConfig": public_config,
        "rawToml": _read_raw_public_config() if raw_toml is None else raw_toml,
        "draftMeta": normalized_meta,
        "diagnosis": diagnosis,
        "summary": summary,
        "editorSections": editor_sections,
        "editorMeta": editor_meta,
        "modelPresetOptions": list_llm_model_preset_options(),
        "modelOptions": _decorate_model_options(public_config, normalized_meta),
        "profileCards": _list_profile_cards(public_config, normalized_meta, lang),
    }


def _prepare_submitted_public_config(public_config: dict[str, Any] | None, old_public: dict[str, Any]) -> dict[str, Any]:
    submitted = copy.deepcopy(public_config) if isinstance(public_config, dict) else copy.deepcopy(old_public)
    return preserve_secret_blanks(submitted, old_public)


def _assert_base_hash_matches(base_hash: str, old_public: dict[str, Any], lang: str) -> str:
    current_hash = public_config_hash(old_public)
    expected_hash = str(base_hash or "").strip()
    if expected_hash and expected_hash != current_hash:
        raise ConfigConflictError(
            text_for(
                lang,
                zh="当前配置已被其他页面或进程改动，请重新加载后再保存这次修改",
                en="The saved config changed in another page or process. Reload before saving these changes.",
            )
        )
    return current_hash


def get_config_summary() -> dict[str, Any]:
    """Return a condensed config summary for shell-wide consumers."""

    public_config = load_public_config()
    diagnostics = inspect_public_config(public_config)
    diagnosis = diagnostics.get("diagnosis", {})
    contract = get_workbench_contract(public_config)
    llm_cfg = public_config.get("llm", {})
    model_library = llm_cfg.get("model_library", {})
    profiles = llm_cfg.get("profiles", {})
    lang = _resolve_workspace_language(public_config)

    blocking = diagnosis.get("blocking_issues") or []
    warnings = diagnosis.get("warnings") or []

    return {
        "hash": public_config_hash(public_config),
        "language": lang,
        "runtimeProfile": public_config.get("runtime", {}).get("profile", "safe_local"),
        "defaultMode": contract["defaultMode"],
        "defaultRoute": contract["defaultRoute"],
        "intakeMode": contract["intakeMode"],
        "modeAvailability": contract["modeAvailability"],
        "domainAvailability": contract["domainAvailability"],
        "modelLibraryCount": len(model_library) if isinstance(model_library, dict) else 0,
        "profileCount": len(profiles) if isinstance(profiles, dict) else 0,
        "blockingCount": len(blocking),
        "warningCount": len(warnings),
        "sections": _config_sections(lang, build_editor_sections(public_config, lang)),
    }


def get_config_workspace() -> dict[str, Any]:
    """Return the full config workspace payload for the Config route."""

    public_config = load_public_config()
    return _build_workspace(public_config)


def preview_config_workspace(public_config: dict[str, Any] | None, draft_meta: dict | None = None, base_hash: str = "") -> dict[str, Any]:
    """Validate and normalize a draft config without persisting it."""

    old_public = load_public_config()
    submitted = _prepare_submitted_public_config(public_config, old_public)
    return _build_workspace(
        submitted,
        draft_meta=draft_meta,
        base_hash=str(base_hash or public_config_hash(old_public)).strip(),
        message=text_for(
            _resolve_workspace_language(submitted),
            zh="当前修改已刷新，尚未保存到 config.toml。",
            en="Current changes refreshed and not yet saved to config.toml.",
        ),
    )


def update_intake_mode(intake_mode: str) -> dict[str, Any]:
    """Persist the evolution intake mode and return the refreshed config summary."""

    public_config = load_public_config()
    evolution_cfg = public_config.setdefault("evolution", {})
    evolution_cfg["intake_mode"] = intake_mode
    save_public_config(public_config)
    return get_config_summary()


def update_language(language: str) -> dict[str, Any]:
    """Persist the UI language and return the refreshed config summary."""

    public_config = load_public_config()
    ui_cfg = public_config.setdefault("ui", {})
    ui_cfg["language"] = "en" if str(language or "").strip().lower() == "en" else "zh"
    save_public_config(public_config)
    return get_config_summary()


def draft_add_model(
    public_config: dict[str, Any] | None,
    *,
    draft_meta: dict | None = None,
    base_hash: str = "",
    preset_id: str = "",
    model_id: str = "",
    provider: Any = None,
    model: str = "",
    label: str = "",
    details: dict | None = None,
    api_key_env: str = "",
    api_key: str = "",
) -> dict[str, Any]:
    old_public = load_public_config()
    current = _prepare_submitted_public_config(public_config, old_public)
    current_meta = _normalize_draft_meta(draft_meta)
    validate_llm_public_config(current)
    before_keys = set(current.get("llm", {}).get("model_library", {}).keys()) if isinstance(current.get("llm", {}), dict) else set()
    if str(preset_id or "").strip():
        updated = apply_llm_model_preset(
            current,
            preset_id,
            model_id=model_id,
            provider_id=provider or "",
            model=model,
            label=label,
            details=details,
            api_key_env=api_key_env,
        )
    else:
        updated = add_llm_model(
            current,
            model_id,
            provider or "",
            model,
            label,
            details,
            api_key_env=api_key_env,
        )
    after_library = updated.get("llm", {}).get("model_library", {}) if isinstance(updated.get("llm", {}), dict) else {}
    resolved_model_id = str(model_id or "").strip()
    if not resolved_model_id and isinstance(after_library, dict):
        created = [key for key in after_library.keys() if key not in before_keys]
        if created:
            resolved_model_id = str(created[0])
    if isinstance(after_library, dict):
        resolved_item = after_library.get(resolved_model_id, {})
        if isinstance(resolved_item, dict):
            resolved_env = str(resolved_item.get("api_key_env", "")).strip()
            if api_key and resolved_env:
                current_meta = _with_pending_api_key(current_meta, resolved_env, api_key)
    return _build_workspace(
        updated,
        draft_meta=current_meta,
        base_hash=str(base_hash or public_config_hash(old_public)).strip(),
        message=text_for(
            _resolve_workspace_language(updated),
            zh="模型修改已更新，尚未保存到 config.toml。",
            en="Model changes updated and not yet saved to config.toml.",
        ),
    )


def draft_update_model(
    public_config: dict[str, Any] | None,
    *,
    draft_meta: dict | None = None,
    base_hash: str = "",
    model_id: str,
    provider: Any = None,
    model: str = "",
    label: str = "",
    details: dict | None = None,
    api_key_env: str = "",
    api_key: str = "",
    clear_api_key: bool = False,
) -> dict[str, Any]:
    old_public = load_public_config()
    current = _prepare_submitted_public_config(public_config, old_public)
    current_meta = _normalize_draft_meta(draft_meta)
    validate_llm_public_config(current)
    current_library = current.get("llm", {}).get("model_library", {}) if isinstance(current.get("llm", {}), dict) else {}
    old_item = current_library.get(model_id, {}) if isinstance(current_library, dict) else {}
    old_env = str(old_item.get("api_key_env", "")).strip() if isinstance(old_item, dict) else ""
    updated = update_llm_model(
        current,
        model_id,
        provider or "",
        model,
        label,
        details,
        api_key_env,
    )
    updated_library = updated.get("llm", {}).get("model_library", {}) if isinstance(updated.get("llm", {}), dict) else {}
    new_item = updated_library.get(model_id, {}) if isinstance(updated_library, dict) else {}
    new_env = str(new_item.get("api_key_env", "")).strip() if isinstance(new_item, dict) else ""
    current_meta = _move_pending_api_key_env(current_meta, old_env, new_env)
    if clear_api_key:
        current_meta = _with_cleared_api_key(current_meta, new_env)
    elif api_key:
        current_meta = _with_pending_api_key(current_meta, new_env, api_key)
    return _build_workspace(
        updated,
        draft_meta=current_meta,
        base_hash=str(base_hash or public_config_hash(old_public)).strip(),
        message=text_for(
            _resolve_workspace_language(updated),
            zh="模型修改已更新，尚未保存到 config.toml。",
            en="Model changes updated and not yet saved to config.toml.",
        ),
    )


def draft_delete_model(
    public_config: dict[str, Any] | None,
    *,
    draft_meta: dict | None = None,
    base_hash: str = "",
    model_id: str,
) -> dict[str, Any]:
    old_public = load_public_config()
    current = _prepare_submitted_public_config(public_config, old_public)
    current_meta = _normalize_draft_meta(draft_meta)
    current_library = current.get("llm", {}).get("model_library", {}) if isinstance(current.get("llm", {}), dict) else {}
    old_item = current_library.get(model_id, {}) if isinstance(current_library, dict) else {}
    old_env = str(old_item.get("api_key_env", "")).strip() if isinstance(old_item, dict) else ""
    updated = delete_llm_model(current, model_id)
    current_meta = _drop_api_key_state(current_meta, old_env)
    return _build_workspace(
        updated,
        draft_meta=current_meta,
        base_hash=str(base_hash or public_config_hash(old_public)).strip(),
        message=text_for(
            _resolve_workspace_language(updated),
            zh="模型修改已更新，尚未保存到 config.toml。",
            en="Model changes updated and not yet saved to config.toml.",
        ),
    )


def draft_add_profile(
    public_config: dict[str, Any] | None,
    *,
    draft_meta: dict | None = None,
    base_hash: str = "",
    profile_id: str,
    source_profile_id: str = "primary",
    model_id: str = "",
) -> dict[str, Any]:
    old_public = load_public_config()
    current = _prepare_submitted_public_config(public_config, old_public)
    validate_llm_public_config(current)
    updated = add_llm_profile(
        current,
        profile_id,
        source_profile_id=source_profile_id,
        model_id=model_id,
    )
    return _build_workspace(
        updated,
        draft_meta=draft_meta,
        base_hash=str(base_hash or public_config_hash(old_public)).strip(),
        message=text_for(
            _resolve_workspace_language(updated),
            zh="配置档修改已更新，尚未保存到 config.toml。",
            en="Profile changes updated and not yet saved to config.toml.",
        ),
    )


def run_draft_llm_test(
    public_config: dict[str, Any] | None,
    *,
    draft_meta: dict | None = None,
    profile_id: str | None = None,
) -> dict[str, Any]:
    old_public = load_public_config()
    submitted = _prepare_submitted_public_config(public_config, old_public)
    validate_llm_public_config(submitted)
    return _run_draft_test_llm_connection(submitted, profile_id, _normalize_draft_meta(draft_meta))


def apply_config_workspace(
    public_config: dict[str, Any] | None,
    *,
    draft_meta: dict | None = None,
    base_hash: str = "",
) -> dict[str, Any]:
    old_public = load_public_config()
    submitted = _prepare_submitted_public_config(public_config, old_public)
    lang = _resolve_workspace_language(submitted)
    _assert_base_hash_matches(base_hash, old_public, lang)
    validate_llm_public_config(submitted)
    _validate_required_llm_profiles(submitted, lang)
    build_effective_config(submitted)
    save_public_config(submitted)

    normalized_meta = _normalize_draft_meta(draft_meta)
    for env_name in normalized_meta.get("pending_cleared_api_keys", []):
        _delete_user_env_var(str(env_name))
        _PENDING_CLEAR_ENVS.discard(str(env_name))
    for env_name, api_key in normalized_meta.get("pending_api_keys", {}).items():
        secret = _resolve_pending_api_key(str(env_name), api_key)
        if secret is None:
            continue
        _set_user_env_var(str(env_name), secret)
        _drop_pending_api_key_token(api_key)

    persisted = load_public_config()
    return _build_workspace(
        persisted,
        message=text_for(
            _resolve_workspace_language(persisted),
            zh="配置已保存到 config.toml。",
            en="Config saved to config.toml.",
        ),
    )


__all__ = [
    "ConfigConflictError",
    "apply_config_workspace",
    "draft_add_model",
    "draft_add_profile",
    "draft_delete_model",
    "draft_update_model",
    "get_config_summary",
    "get_config_workspace",
    "preview_config_workspace",
    "run_draft_llm_test",
    "update_intake_mode",
    "update_language",
]
