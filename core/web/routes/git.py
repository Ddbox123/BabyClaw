"""Git status routes for the local web workbench."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from core.web.services.git_status_service import get_git_commits, get_git_file_diff, get_git_status


router = APIRouter(tags=["git"])


@router.get("/git/status")
def git_status(limit: int | None = Query(default=80, ge=0, le=500)) -> dict:
    return get_git_status(limit=limit)


@router.get("/git/commits")
def git_commits(limit: int = Query(default=20, ge=1, le=60)) -> dict:
    return get_git_commits(limit=limit)


@router.get("/git/diff")
def git_diff(path: str = Query(min_length=1)) -> dict:
    try:
        return get_git_file_diff(path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
