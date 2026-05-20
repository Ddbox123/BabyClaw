"""FastAPI entrypoint for the Vibelution web workbench."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from .routes.config import router as config_router
from .routes.evolution import router as evolution_router
from .routes.files import router as files_router
from .routes.logs import router as logs_router
from .routes.pet import router as pet_router
from .routes.reset import router as reset_router
from .routes.runtime import router as runtime_router
from .routes.sessions import router as sessions_router


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
        allow_origins=[
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "http://127.0.0.1:8000",
            "http://localhost:8000",
            f"http://127.0.0.1:{_default_workbench_port()}",
            f"http://localhost:{_default_workbench_port()}",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(runtime_router, prefix="/api")
    app.include_router(sessions_router, prefix="/api")
    app.include_router(files_router, prefix="/api")
    app.include_router(logs_router, prefix="/api")
    app.include_router(evolution_router, prefix="/api")
    app.include_router(config_router, prefix="/api")
    app.include_router(reset_router, prefix="/api")
    app.include_router(pet_router, prefix="/api")

    @app.get("/", include_in_schema=False)
    def index():
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
    def spa_fallback(full_path: str):
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
