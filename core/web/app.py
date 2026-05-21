"""FastAPI entrypoint for the Vibelution web workbench."""

from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from .control import WebControlGuardMiddleware, control_token_payload, ensure_control_source, trusted_control_origins
from .routes.config import router as config_router
from .routes.evolution import router as evolution_router
from .routes.files import router as files_router
from .routes.git import router as git_router
from .routes.logs import router as logs_router
from .routes.pet import router as pet_router
from .routes.reset import router as reset_router
from .routes.runtime import router as runtime_router
from .routes.sessions import router as sessions_router
from .services.runtime_scene_service import record_backend_api_event


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_DIST = PROJECT_ROOT / "web" / "dist"
INDEX_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}


def _looks_like_static_asset_request(full_path: str) -> bool:
    normalized = str(full_path or "").strip().lstrip("/")
    if not normalized:
        return False
    path = Path(normalized)
    return normalized.startswith("assets/") or bool(path.suffix)


def _default_workbench_port() -> int:
    raw_value = str(os.environ.get("VIBELUTION_PORT") or "").strip()
    try:
        port = int(raw_value)
    except ValueError:
        return 8000
    return port if 0 < port < 65536 else 8000


def _is_windows_proactor_disconnect_noise(context: dict[str, Any]) -> bool:
    if os.name != "nt":
        return False
    exception = context.get("exception")
    if not isinstance(exception, ConnectionResetError):
        return False
    fragments = [
        str(context.get("message") or ""),
        repr(context.get("handle")),
        repr(context.get("transport")),
        repr(context.get("protocol")),
    ]
    haystack = " ".join(fragment for fragment in fragments if fragment).lower()
    return "proactorbasepipetransport._call_connection_lost" in haystack


class RuntimeSceneApiEventMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.perf_counter()
        should_record = _should_record_api_runtime_event(request)
        try:
            response = await call_next(request)
        except Exception as exc:
            if should_record:
                _record_api_runtime_event(
                    request,
                    status_code=500,
                    duration_ms=(time.perf_counter() - start) * 1000,
                    exception=exc,
                )
            raise

        if should_record and _is_signal_api_response(request, response.status_code):
            _record_api_runtime_event(
                request,
                status_code=response.status_code,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
        return response


def _should_record_api_runtime_event(request: Request) -> bool:
    path = str(request.url.path or "")
    if not path.startswith("/api/"):
        return False
    if path in {"/api/health", "/api/control-token", "/api/runtime/browser-telemetry", "/api/runtime/events"}:
        return False
    return True


def _is_signal_api_response(request: Request, status_code: int) -> bool:
    method = request.method.upper()
    if method in {"POST", "PUT", "PATCH", "DELETE"}:
        return True
    return int(status_code or 0) >= 400


def _record_api_runtime_event(
    request: Request,
    *,
    status_code: int,
    duration_ms: float,
    exception: Exception | None = None,
) -> None:
    try:
        route = request.scope.get("route")
        path_template = str(getattr(route, "path", "") or request.url.path)
        client = request.client.host if request.client else ""
        record_backend_api_event(
            {
                "method": request.method.upper(),
                "path": str(request.url.path or ""),
                "path_template": path_template,
                "query": str(request.url.query or ""),
                "status_code": int(status_code or 0),
                "duration_ms": duration_ms,
                "client": client,
                "exception_type": type(exception).__name__ if exception else "",
                "exception_message": str(exception or ""),
            }
        )
    except Exception:
        pass


@asynccontextmanager
async def _lifespan(_: FastAPI):
    loop = asyncio.get_running_loop()
    previous_handler = loop.get_exception_handler()

    def handle_loop_exception(current_loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
        if _is_windows_proactor_disconnect_noise(context):
            return
        if previous_handler is not None:
            previous_handler(current_loop, context)
            return
        current_loop.default_exception_handler(context)

    loop.set_exception_handler(handle_loop_exception)
    try:
        yield
    finally:
        loop.set_exception_handler(previous_handler)


def create_app() -> FastAPI:
    """Create the local web workbench app."""

    app = FastAPI(
        title="Vibelution Web Workbench",
        version="0.1.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=_lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(trusted_control_origins()),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*", "X-Vibelution-Control-Token"],
    )
    app.add_middleware(WebControlGuardMiddleware)
    app.add_middleware(RuntimeSceneApiEventMiddleware)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/control-token")
    def control_token(request: Request) -> dict[str, str]:
        ensure_control_source(request)
        return control_token_payload()

    app.include_router(runtime_router, prefix="/api")
    app.include_router(sessions_router, prefix="/api")
    app.include_router(files_router, prefix="/api")
    app.include_router(git_router, prefix="/api")
    app.include_router(logs_router, prefix="/api")
    app.include_router(evolution_router, prefix="/api")
    app.include_router(config_router, prefix="/api")
    app.include_router(reset_router, prefix="/api")
    app.include_router(pet_router, prefix="/api")

    @app.get("/", include_in_schema=False)
    def index(request: Request):
        ensure_control_source(request)
        if WEB_DIST.exists():
            return FileResponse(WEB_DIST / "index.html", headers=INDEX_CACHE_HEADERS)
        return JSONResponse(
            {
                "message": "Web frontend has not been built yet.",
                "next": "Run `npm install` and `npm run build` in `web/`, then restart the server.",
            },
            status_code=503,
        )

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str, request: Request):
        ensure_control_source(request)
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        if WEB_DIST.exists():
            candidate = (WEB_DIST / full_path).resolve()
            dist_root = WEB_DIST.resolve()
            try:
                candidate.relative_to(dist_root)
            except ValueError:
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            if candidate.exists() and candidate.is_file():
                return FileResponse(candidate)
            if _looks_like_static_asset_request(full_path):
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            return FileResponse(WEB_DIST / "index.html", headers=INDEX_CACHE_HEADERS)
        return JSONResponse(
            {
                "message": "Web frontend has not been built yet.",
                "next": "Run `npm install` and `npm run build` in `web/`, then restart the server.",
            },
            status_code=503,
        )

    return app


app = create_app()
