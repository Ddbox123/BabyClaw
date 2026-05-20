"""Session routes for the chat/coding shell."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from starlette.responses import StreamingResponse

from core.web.services.session_service import (
    SessionBusyError,
    SessionNotFoundError,
    SessionValidationError,
    create_chat_session,
    delete_chat_session,
    get_session_detail,
    list_sessions,
    request_stop_session_turn,
    stream_session_events,
    submit_session_message,
    update_chat_session_title,
)


router = APIRouter(tags=["sessions"])


class SessionMessagePayload(BaseModel):
    content: str = ""


class SessionUpdatePayload(BaseModel):
    title: str = ""


@router.get("/sessions")
def sessions() -> list[dict]:
    return list_sessions()


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
def session_create() -> dict:
    return create_chat_session()


@router.get("/sessions/{session_id}")
def session_detail(session_id: str) -> dict:
    detail = get_session_detail(session_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return detail


@router.patch("/sessions/{session_id}")
def session_update(session_id: str, payload: SessionUpdatePayload) -> dict:
    try:
        return update_chat_session_title(session_id, payload.title)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/sessions/{session_id}")
def session_delete(session_id: str) -> dict:
    try:
        return delete_chat_session(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/sessions/{session_id}/events")
def session_events(session_id: str) -> StreamingResponse:
    detail = get_session_detail(session_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return StreamingResponse(
        stream_session_events(session_id, initial_detail=detail),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.post("/sessions/{session_id}/messages", status_code=status.HTTP_202_ACCEPTED)
def session_submit_message(session_id: str, payload: SessionMessagePayload) -> dict:
    try:
        return submit_session_message(session_id, payload.content)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SessionValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/sessions/{session_id}/stop", status_code=status.HTTP_202_ACCEPTED)
def session_stop_turn(session_id: str) -> dict:
    try:
        return request_stop_session_turn(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
