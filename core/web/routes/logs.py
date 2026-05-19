"""Log preview and guarded cleanup routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from core.web.services.log_service import (
    build_log_tree,
    clear_log_file,
    delete_log_files,
    list_log_roots,
    read_log_file,
)
from core.web.services.runtime_scene_service import (
    delete_runtime_scenes,
    get_runtime_scene_detail,
    list_runtime_scenes,
    read_runtime_scene_file,
)


router = APIRouter(tags=["logs"])


class LogClearPayload(BaseModel):
    root: str = Field(..., min_length=1)
    path: str = Field(..., min_length=1)


class LogDeletePayload(BaseModel):
    root: str = Field(..., min_length=1)
    paths: list[str] = Field(default_factory=list)


class RuntimeSceneDeletePayload(BaseModel):
    sceneIds: list[str] = Field(default_factory=list)


@router.get("/logs/roots")
def log_roots() -> list[dict]:
    return list_log_roots()


@router.get("/logs/tree")
def log_tree(root: str = Query(..., min_length=1)) -> dict:
    try:
        return build_log_tree(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/logs/content")
def log_content(
    root: str = Query(..., min_length=1),
    path: str = Query(..., min_length=1),
) -> dict:
    try:
        return read_log_file(root, path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/logs/runtime-scenes")
def runtime_scene_list() -> list[dict]:
    return list_runtime_scenes()


@router.get("/logs/runtime-scenes/{scene_id}")
def runtime_scene_detail(scene_id: str) -> dict:
    try:
        return get_runtime_scene_detail(scene_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/logs/runtime-scenes/{scene_id}/content")
def runtime_scene_content(
    scene_id: str,
    path: str = Query(..., min_length=1),
) -> dict:
    try:
        return read_runtime_scene_file(scene_id, path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/logs/clear")
def clear_log(payload: LogClearPayload) -> dict:
    try:
        return clear_log_file(payload.root, payload.path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/logs/delete")
def delete_logs(payload: LogDeletePayload) -> dict:
    try:
        return delete_log_files(payload.root, payload.paths)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/logs/runtime-scenes/delete")
def delete_runtime_scene_bundles(payload: RuntimeSceneDeletePayload) -> dict:
    try:
        return delete_runtime_scenes(payload.sceneIds)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
