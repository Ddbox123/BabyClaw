"""Pet space routes."""

from __future__ import annotations

from fastapi import APIRouter

from core.web.services.pet_service import get_pet_summary


router = APIRouter(tags=["pet"])


@router.get("/pet/summary")
def pet_summary() -> dict:
    return get_pet_summary()
