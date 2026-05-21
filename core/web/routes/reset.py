"""Reset overview routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.web.services.reset_service import execute_reset, get_reset_summary, preview_reset


router = APIRouter(tags=["reset"])


class ResetSelectionPayload(BaseModel):
    itemIds: list[str] = Field(default_factory=list)


class ResetExecutePayload(ResetSelectionPayload):
    confirmed: bool = False


@router.get("/reset/summary")
def reset_summary() -> dict:
    return get_reset_summary()


@router.post("/reset/preview")
def reset_preview(payload: ResetSelectionPayload) -> dict:
    try:
        return preview_reset(payload.itemIds)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/reset/execute")
def reset_execute(payload: ResetExecutePayload) -> dict:
    try:
        return execute_reset(payload.itemIds, confirmed=payload.confirmed)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
