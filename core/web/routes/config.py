"""Config workspace routes."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.web.services.config_service import (
    ConfigConflictError,
    apply_config_workspace,
    draft_add_model,
    draft_add_profile,
    draft_delete_model,
    draft_update_model,
    get_config_summary,
    get_config_workspace,
    preview_config_workspace,
    run_draft_llm_test,
    update_intake_mode,
    update_language,
)


router = APIRouter(tags=["config"])


class IntakeModeUpdateRequest(BaseModel):
    intakeMode: Literal["manual_review", "auto"]


class LanguageUpdateRequest(BaseModel):
    language: Literal["zh", "en"]


class ConfigDraftPayload(BaseModel):
    publicConfig: dict[str, Any] = Field(default_factory=dict)
    draftMeta: dict[str, Any] = Field(default_factory=dict)
    baseHash: str = ""


class ConfigDraftAddModelPayload(ConfigDraftPayload):
    presetId: str = ""
    modelId: str = ""
    provider: dict[str, Any] = Field(default_factory=dict)
    model: str = ""
    label: str = ""
    details: dict[str, Any] = Field(default_factory=dict)
    apiKeyEnv: str = ""
    apiKey: str = ""


class ConfigDraftUpdateModelPayload(ConfigDraftPayload):
    modelId: str = ""
    provider: dict[str, Any] = Field(default_factory=dict)
    model: str = ""
    label: str = ""
    details: dict[str, Any] = Field(default_factory=dict)
    apiKeyEnv: str = ""
    apiKey: str = ""
    clearApiKey: bool = False


class ConfigDraftDeleteModelPayload(ConfigDraftPayload):
    modelId: str = ""


class ConfigDraftAddProfilePayload(ConfigDraftPayload):
    profileId: str = ""
    sourceProfileId: str = "primary"
    modelId: str = ""


class ConfigDraftTestPayload(ConfigDraftPayload):
    profileId: str | None = None


def _raise_config_http_error(exc: Exception) -> None:
    if isinstance(exc, ConfigConflictError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/config/public")
def public_config_summary() -> dict:
    return get_config_summary()


@router.get("/config/workspace")
def config_workspace() -> dict:
    return get_config_workspace()


@router.post("/config/draft/preview")
def config_draft_preview(payload: ConfigDraftPayload) -> dict:
    try:
        return preview_config_workspace(payload.publicConfig, payload.draftMeta, payload.baseHash)
    except Exception as exc:  # pragma: no cover - routed below
        _raise_config_http_error(exc)


@router.post("/config/draft/add-model")
def config_draft_add_model(payload: ConfigDraftAddModelPayload) -> dict:
    try:
        return draft_add_model(
            payload.publicConfig,
            draft_meta=payload.draftMeta,
            base_hash=payload.baseHash,
            preset_id=payload.presetId,
            model_id=payload.modelId,
            provider=payload.provider,
            model=payload.model,
            label=payload.label,
            details=payload.details,
            api_key_env=payload.apiKeyEnv,
            api_key=payload.apiKey,
        )
    except Exception as exc:  # pragma: no cover - routed below
        _raise_config_http_error(exc)


@router.post("/config/draft/update-model")
def config_draft_update_model(payload: ConfigDraftUpdateModelPayload) -> dict:
    try:
        return draft_update_model(
            payload.publicConfig,
            draft_meta=payload.draftMeta,
            base_hash=payload.baseHash,
            model_id=payload.modelId,
            provider=payload.provider,
            model=payload.model,
            label=payload.label,
            details=payload.details,
            api_key_env=payload.apiKeyEnv,
            api_key=payload.apiKey,
            clear_api_key=payload.clearApiKey,
        )
    except Exception as exc:  # pragma: no cover - routed below
        _raise_config_http_error(exc)


@router.post("/config/draft/delete-model")
def config_draft_delete_model(payload: ConfigDraftDeleteModelPayload) -> dict:
    try:
        return draft_delete_model(
            payload.publicConfig,
            draft_meta=payload.draftMeta,
            base_hash=payload.baseHash,
            model_id=payload.modelId,
        )
    except Exception as exc:  # pragma: no cover - routed below
        _raise_config_http_error(exc)


@router.post("/config/draft/add-profile")
def config_draft_add_profile(payload: ConfigDraftAddProfilePayload) -> dict:
    try:
        return draft_add_profile(
            payload.publicConfig,
            draft_meta=payload.draftMeta,
            base_hash=payload.baseHash,
            profile_id=payload.profileId,
            source_profile_id=payload.sourceProfileId,
            model_id=payload.modelId,
        )
    except Exception as exc:  # pragma: no cover - routed below
        _raise_config_http_error(exc)


@router.post("/config/test-llm")
def config_test_llm(payload: ConfigDraftTestPayload) -> dict:
    try:
        return run_draft_llm_test(
            payload.publicConfig,
            draft_meta=payload.draftMeta,
            profile_id=payload.profileId,
        )
    except Exception as exc:  # pragma: no cover - routed below
        _raise_config_http_error(exc)


@router.put("/config/apply")
def config_apply(payload: ConfigDraftPayload) -> dict:
    try:
        return apply_config_workspace(
            payload.publicConfig,
            draft_meta=payload.draftMeta,
            base_hash=payload.baseHash,
        )
    except Exception as exc:  # pragma: no cover - routed below
        _raise_config_http_error(exc)


@router.put("/config/intake-mode")
def set_intake_mode(payload: IntakeModeUpdateRequest) -> dict:
    return update_intake_mode(payload.intakeMode)


@router.put("/config/language")
def set_language(payload: LanguageUpdateRequest) -> dict:
    return update_language(payload.language)
