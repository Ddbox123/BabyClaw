"""Local control-plane guard for the web workbench."""

from __future__ import annotations

import ipaddress
import os
import secrets
from dataclasses import dataclass
from urllib.parse import urlparse

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

CONTROL_TOKEN_HEADER = "X-Vibelution-Control-Token"
CONTROL_TOKEN_ENV = "VIBELUTION_WEB_CONTROL_TOKEN"

_MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_CONTROL_TOKEN = str(os.environ.get(CONTROL_TOKEN_ENV) or "").strip() or secrets.token_urlsafe(32)


@dataclass(frozen=True)
class ControlGuardError:
    status_code: int
    detail: str


def get_control_token() -> str:
    return _CONTROL_TOKEN


def control_token_payload() -> dict[str, str]:
    return {
        "header": CONTROL_TOKEN_HEADER,
        "controlToken": get_control_token(),
    }


def trusted_control_origins() -> set[str]:
    backend_port = _default_workbench_port()
    origins = {
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        f"http://127.0.0.1:{backend_port}",
        f"http://localhost:{backend_port}",
    }
    return {origin.rstrip("/") for origin in origins}


def ensure_control_source(request: Request) -> None:
    error = validate_control_source(request)
    if error is not None:
        raise HTTPException(status_code=error.status_code, detail=error.detail)


def validate_control_source(request: Request) -> ControlGuardError | None:
    host = request.headers.get("host", "")
    if host and not _is_trusted_host(host):
        return ControlGuardError(403, "Untrusted web control host")

    origin = request.headers.get("origin", "")
    if origin and not (_is_trusted_origin(origin) or _matches_request_origin(origin, request)):
        return ControlGuardError(403, "Untrusted web control origin")

    referer = request.headers.get("referer", "")
    if not origin and referer and not (_is_trusted_referer(referer) or _matches_request_origin(referer, request)):
        return ControlGuardError(403, "Untrusted web control referer")

    return None


def validate_control_request(request: Request) -> ControlGuardError | None:
    source_error = validate_control_source(request)
    if source_error is not None:
        return source_error

    submitted = str(request.headers.get(CONTROL_TOKEN_HEADER) or "").strip()
    if not submitted or not secrets.compare_digest(submitted, get_control_token()):
        return ControlGuardError(403, "Missing or invalid web control token")
    return None


class WebControlGuardMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if not _is_guarded_path(request.url.path) or request.method.upper() == "OPTIONS":
            return await call_next(request)

        if request.method.upper() in _MUTATING_METHODS:
            error = validate_control_request(request)
            if error is not None:
                return JSONResponse({"detail": error.detail}, status_code=error.status_code)

        return await call_next(request)


def _is_guarded_path(path: str) -> bool:
    return str(path or "").startswith("/api/")


def _default_workbench_port() -> int:
    raw_value = str(os.environ.get("VIBELUTION_PORT") or "").strip()
    try:
        port = int(raw_value)
    except ValueError:
        return 8000
    return port if 0 < port < 65536 else 8000


def _is_trusted_host(value: str) -> bool:
    host = _parse_hostname(value)
    if not host:
        return False
    if host == "testserver":
        return True
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _is_trusted_origin(value: str) -> bool:
    normalized = _normalize_origin(value)
    return bool(normalized and normalized in trusted_control_origins())


def _is_trusted_referer(value: str) -> bool:
    normalized = _normalize_origin(value)
    return bool(normalized and normalized in trusted_control_origins())


def _matches_request_origin(value: str, request: Request) -> bool:
    normalized = _normalize_origin(value)
    if not normalized:
        return False
    host = request.headers.get("host", "")
    if not host or not _is_trusted_host(host):
        return False
    request_origin = _normalize_origin(f"{request.url.scheme}://{host}")
    return bool(request_origin and normalized == request_origin)


def _normalize_origin(value: str) -> str:
    parsed = urlparse(str(value or "").strip())
    if parsed.scheme not in {"http", "https"}:
        return ""
    if not parsed.hostname:
        return ""
    if not _is_trusted_host(parsed.hostname):
        return ""
    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    return f"{parsed.scheme}://{parsed.hostname}:{port}".rstrip("/")


def _parse_hostname(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else f"//{raw}")
    return str(parsed.hostname or "").strip().lower()
