"""Git status routes for the local web workbench."""

from __future__ import annotations

from fastapi import APIRouter

from core.web.services.git_status_service import get_git_status


router = APIRouter(tags=["git"])


@router.get("/git/status")
def git_status() -> dict:
    return get_git_status()
