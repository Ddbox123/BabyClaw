"""Runtime summary routes."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field
from fastapi.responses import StreamingResponse

from core.web.services.runtime_service import get_runtime_summary, request_runtime_shutdown
from core.web.services.runtime_scene_service import record_browser_telemetry


router = APIRouter(tags=["runtime"])


class BrowserTelemetryPayload(BaseModel):
    phase: str = Field(default="page", min_length=1)
    eventCode: str = Field(..., min_length=1)
    message: str = ""
    level: str = Field(default="info", min_length=1)
    fields: dict[str, Any] = Field(default_factory=dict)


@router.get("/runtime/summary")
def runtime_summary() -> dict:
    return get_runtime_summary()


@router.post("/runtime/shutdown", status_code=202)
def runtime_shutdown() -> dict:
    return request_runtime_shutdown()


@router.post("/runtime/browser-telemetry", status_code=202)
def runtime_browser_telemetry(payload: BrowserTelemetryPayload) -> dict:
    return record_browser_telemetry(payload.model_dump())


@router.get("/runtime/events")
async def runtime_events() -> StreamingResponse:
    async def event_stream():
        while True:
            payload = {
                "type": "heartbeat",
                "at": datetime.now(UTC).isoformat(),
            }
            yield f"event: heartbeat\ndata: {json.dumps(payload)}\n\n"
            await asyncio.sleep(15)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
