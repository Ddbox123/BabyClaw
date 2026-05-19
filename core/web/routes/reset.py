"""Reset overview routes."""

from __future__ import annotations

from fastapi import APIRouter

from core.web.services.reset_service import get_reset_summary


router = APIRouter(tags=["reset"])


@router.get("/reset/summary")
def reset_summary() -> dict:
    return get_reset_summary()
