"""File tree and preview routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from core.web.services.file_service import build_file_tree, read_text_file


router = APIRouter(tags=["files"])


@router.get("/files/tree")
def files_tree() -> list[dict]:
    return build_file_tree()


@router.get("/files/content")
def file_content(path: str = Query(..., min_length=1)) -> dict:
    try:
        return read_text_file(path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
