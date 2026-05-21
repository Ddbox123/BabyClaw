"""Structured runtime scene bundles for frontend inspection and agent diagnosis."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any

from core.web.services.log_diagnostics import analyze_log_content


PROJECT_ROOT = Path(__file__).resolve().parents[3]
LAUNCHER_STATE_PATH = PROJECT_ROOT / ".runtime" / "launcher" / "state.json"
MAX_TEXT_CHARS = 200_000
BROWSER_TELEMETRY_RAW_PATH = "raw/browser.telemetry.log"
BROWSER_TELEMETRY_COMPONENT = "browser_page"
BACKEND_API_RAW_PATH = "raw/backend.api.log"
BACKEND_COMPONENT = "backend"
MAX_TELEMETRY_TEXT_CHARS = 4_000
MAX_TELEMETRY_FIELD_TEXT_CHARS = 1_200
MAX_TELEMETRY_FIELD_ITEMS = 24
BROWSER_TELEMETRY_WRITE_LOCK = Lock()
BACKEND_API_WRITE_LOCK = Lock()
RAW_LABELS = {
    "raw/frontend.build.log": "Frontend build log",
    "raw/backend.stdout.log": "Backend stdout",
    "raw/backend.stderr.log": "Backend stderr",
    BACKEND_API_RAW_PATH: "Backend API events",
    "raw/supervisor.log": "Supervisor log",
    "raw/browser.log": "Browser log",
    BROWSER_TELEMETRY_RAW_PATH: "Browser telemetry",
}
LANGUAGE_BY_SUFFIX = {
    ".css": "css",
    ".html": "html",
    ".js": "javascript",
    ".json": "json",
    ".jsonl": "json",
    ".log": "text",
    ".md": "markdown",
    ".ps1": "powershell",
    ".py": "python",
    ".text": "text",
    ".toml": "toml",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".txt": "text",
    ".yaml": "yaml",
    ".yml": "yaml",
}
DISPLAY_NAME_TRIGGER_LABELS = {
    "start": "工作台启动",
    "internal-start": "工作台启动",
    "internal-restart": "工作台重启",
    "restart": "工作台重启",
    "open": "打开工作台",
    "stop": "关闭工作台",
    "shutdown": "关闭工作台",
}
DISPLAY_NAME_STATUS_LABELS = {
    "running": "运行中",
    "starting": "启动中",
    "queued": "等待中",
    "stopping": "停止中",
    "stopped": "已停止",
    "failed": "失败",
    "success": "成功",
    "succeeded": "成功",
}
DISPLAY_NAME_RESULT_LABELS = {
    "explicit_stop": "手动停止",
    "explicit stop": "手动停止",
    "browser_window_closed": "窗口关闭",
    "app window closed": "窗口关闭",
    "startup_failed": "启动失败",
    "backend_exited": "后端退出",
    "success": "成功",
    "succeeded": "成功",
    "failed": "失败",
}


def list_runtime_scenes(limit: int = 80) -> list[dict]:
    """Return runtime scene summaries sorted by most recent first."""

    scenes: list[dict] = []
    for scene_dir in _scene_dirs():
        manifest = _load_scene_manifest(scene_dir)
        scene_id = _scene_id(scene_dir, manifest)
        if not scene_id:
            continue
        timeline = _read_scene_timeline(scene_dir)
        raw_files = _list_raw_files(scene_dir)
        scenes.append(
            {
                "runtimeSceneId": scene_id,
                "directoryName": scene_dir.name,
                "title": str(manifest.get("title") or scene_dir.name),
                "displayName": _runtime_scene_display_name(scene_dir, manifest, scene_id),
                "startedAt": str(manifest.get("started_at") or ""),
                "endedAt": str(manifest.get("ended_at") or ""),
                "status": str(manifest.get("status") or "unknown"),
                "result": str(manifest.get("result") or ""),
                "stopReason": str(manifest.get("stop_reason") or ""),
                "trigger": str(manifest.get("trigger") or ""),
                "sessionMode": str(manifest.get("session_mode") or ""),
                "backendStatus": str(((manifest.get("backend") or {}) if isinstance(manifest.get("backend"), dict) else {}).get("health_status") or ""),
                "frontendStatus": str(((manifest.get("frontend") or {}) if isinstance(manifest.get("frontend"), dict) else {}).get("build_status") or ""),
                "browserStatus": str(((manifest.get("browser") or {}) if isinstance(manifest.get("browser"), dict) else {}).get("status") or ""),
                "eventCount": len(timeline),
                "rawLogCount": len(raw_files),
            }
        )
    scenes.sort(key=lambda item: (item["startedAt"], item["directoryName"]), reverse=True)
    return scenes[: max(1, int(limit or 80))]


def get_runtime_scene_detail(scene_id: str) -> dict:
    """Return one runtime scene bundle with manifest, merged timeline, and raw file metadata."""

    scene_dir = _resolve_scene_dir(scene_id)
    manifest = _load_scene_manifest(scene_dir)
    detail_scene_id = _scene_id(scene_dir, manifest)
    timeline = _read_scene_timeline(scene_dir)
    raw_files = _list_raw_files(scene_dir)
    return {
        "runtimeSceneId": detail_scene_id,
        "directoryName": scene_dir.name,
        "displayName": _runtime_scene_display_name(scene_dir, manifest, detail_scene_id),
        "manifestPath": str((scene_dir / "manifest.json").relative_to(PROJECT_ROOT).as_posix()),
        "manifest": manifest,
        "startedAt": str(manifest.get("started_at") or ""),
        "endedAt": str(manifest.get("ended_at") or ""),
        "status": str(manifest.get("status") or "unknown"),
        "result": str(manifest.get("result") or ""),
        "stopReason": str(manifest.get("stop_reason") or ""),
        "trigger": str(manifest.get("trigger") or ""),
        "sessionMode": str(manifest.get("session_mode") or ""),
        "host": str(manifest.get("host") or ""),
        "port": int(manifest.get("port") or 0) if str(manifest.get("port") or "").strip() else 0,
        "url": str(manifest.get("url") or ""),
        "frontend": manifest.get("frontend") if isinstance(manifest.get("frontend"), dict) else {},
        "backend": manifest.get("backend") if isinstance(manifest.get("backend"), dict) else {},
        "browser": manifest.get("browser") if isinstance(manifest.get("browser"), dict) else {},
        "supervisor": manifest.get("supervisor") if isinstance(manifest.get("supervisor"), dict) else {},
        "timeline": timeline,
        "rawFiles": raw_files,
    }


def read_runtime_scene_file(scene_id: str, relative_path: str) -> dict:
    """Read a raw or structured file from one runtime scene bundle."""

    scene_dir = _resolve_scene_dir(scene_id)
    relative = _normalize_relative_path(relative_path)
    file_path = _resolve_scene_child(scene_dir, relative)
    if not file_path.exists() or not file_path.is_file():
        raise FileNotFoundError(f"Runtime scene file not found: {relative}")
    raw = file_path.read_bytes()
    if b"\x00" in raw[:8192]:
        raise ValueError("Binary runtime scene files are not supported in the preview yet")
    content = raw.decode("utf-8-sig", errors="replace")
    truncated = len(content) > MAX_TEXT_CHARS
    if truncated:
        content = content[:MAX_TEXT_CHARS] + "\n\n... preview truncated ..."
    scene_root_path = scene_dir.relative_to(PROJECT_ROOT).as_posix()
    return {
        "rootId": "runtime_scenes",
        "rootPath": scene_root_path,
        "relativePath": relative,
        "path": f"{scene_root_path}/{relative}".replace("//", "/"),
        "language": LANGUAGE_BY_SUFFIX.get(file_path.suffix.lower(), "text"),
        "content": content,
        "truncated": truncated,
        "diagnostics": _analyze_runtime_scene_content(scene_id, relative, content),
    }


def record_browser_telemetry(payload: dict[str, Any]) -> dict[str, Any]:
    """Append one browser-side telemetry event into the active runtime scene bundle."""

    scene_dir = _resolve_current_runtime_scene_dir()
    if scene_dir is None:
        return {
            "accepted": False,
            "reason": "no_runtime_scene",
        }

    timestamp = datetime.now(UTC).isoformat()
    phase = _sanitize_token(payload.get("phase"), default="page")
    event_code = _sanitize_token(payload.get("eventCode"), default="browser.telemetry")
    level = _sanitize_token(payload.get("level"), default="info")
    message = _truncate_text(str(payload.get("message") or event_code), 320)
    fields = _normalize_telemetry_fields(payload.get("fields"))

    raw_line = f"[{timestamp}] {event_code} [{level}] {message}"
    if fields:
        raw_line = f"{raw_line} :: {json.dumps(fields, ensure_ascii=False, separators=(',', ':'))}"
    with BROWSER_TELEMETRY_WRITE_LOCK:
        manifest = _load_scene_manifest(scene_dir)
        scene_id = _scene_id(scene_dir, manifest)
        _append_scene_log_line(scene_dir, BROWSER_TELEMETRY_RAW_PATH, _truncate_text(raw_line, MAX_TELEMETRY_TEXT_CHARS))

        raw_refs = [
            {
                "path": BROWSER_TELEMETRY_RAW_PATH,
                "tail_lines": 80,
            },
        ]
        event_payload = {
            "schema_version": 1,
            "runtime_scene_id": scene_id,
            "ts": timestamp,
            "seq": _next_scene_event_seq(scene_dir, BROWSER_TELEMETRY_COMPONENT),
            "component": BROWSER_TELEMETRY_COMPONENT,
            "phase": phase,
            "event_code": event_code,
            "level": level,
            "outcome": "observed",
            "message": message,
            "fields": fields,
            "raw_refs": raw_refs,
        }
        _append_scene_event(scene_dir, BROWSER_TELEMETRY_COMPONENT, event_payload)
        _update_browser_manifest(scene_dir, manifest, timestamp, event_code, level, message, fields)

    return {
        "accepted": True,
        "runtimeSceneId": scene_id,
        "recordedAt": timestamp,
    }


def record_backend_api_event(payload: dict[str, Any]) -> dict[str, Any]:
    """Append one backend API request event into the active runtime scene bundle."""

    scene_dir = _resolve_current_runtime_scene_dir()
    if scene_dir is None:
        return {
            "accepted": False,
            "reason": "no_runtime_scene",
        }

    timestamp = datetime.now(UTC).isoformat()
    method = _truncate_text(str(payload.get("method") or "").upper(), 16)
    path = _truncate_text(str(payload.get("path") or ""), 240)
    status_code = _coerce_int(payload.get("status_code"), default=0)
    duration_ms = _coerce_float(payload.get("duration_ms"), default=0.0)
    path_template = _truncate_text(str(payload.get("path_template") or path), 240)
    level = "error" if status_code >= 500 else "warning" if status_code >= 400 else "info"
    outcome = "failed" if status_code >= 500 else "client_error" if status_code >= 400 else "succeeded"
    event_code = _sanitize_token(payload.get("event_code"), default="backend.api.request")
    message = _truncate_text(
        str(payload.get("message") or f"{method or 'API'} {path_template or path} -> {status_code or '?'}"),
        320,
    )
    fields = _normalize_telemetry_fields(
        {
            "method": method,
            "path": path,
            "pathTemplate": path_template,
            "statusCode": status_code,
            "durationMs": round(duration_ms, 2),
            "query": _truncate_text(str(payload.get("query") or ""), 240),
            "client": _truncate_text(str(payload.get("client") or ""), 160),
            "exceptionType": _truncate_text(str(payload.get("exception_type") or ""), 120),
            "exceptionMessage": _truncate_text(str(payload.get("exception_message") or ""), 320),
        }
    )

    raw_line = f"[{timestamp}] {event_code} [{level}] {message}"
    if fields:
        raw_line = f"{raw_line} :: {json.dumps(fields, ensure_ascii=False, separators=(',', ':'))}"

    with BACKEND_API_WRITE_LOCK:
        manifest = _load_scene_manifest(scene_dir)
        scene_id = _scene_id(scene_dir, manifest)
        _append_scene_log_line(scene_dir, BACKEND_API_RAW_PATH, _truncate_text(raw_line, MAX_TELEMETRY_TEXT_CHARS))
        event_payload = {
            "schema_version": 1,
            "runtime_scene_id": scene_id,
            "ts": timestamp,
            "seq": _next_scene_event_seq(scene_dir, BACKEND_COMPONENT),
            "component": BACKEND_COMPONENT,
            "phase": "api",
            "event_code": event_code,
            "level": level,
            "outcome": outcome,
            "message": message,
            "fields": fields,
            "raw_refs": [
                {
                    "path": BACKEND_API_RAW_PATH,
                    "tail_lines": 80,
                },
            ],
        }
        _append_scene_event(scene_dir, BACKEND_COMPONENT, event_payload)
        _update_backend_api_manifest(scene_dir, manifest, timestamp, level, fields)

    return {
        "accepted": True,
        "runtimeSceneId": scene_id,
        "recordedAt": timestamp,
    }


def delete_runtime_scenes(scene_ids: list[str] | tuple[str, ...]) -> dict:
    """Delete one or more runtime scene bundles as a unit."""

    normalized_ids = _normalize_scene_ids(scene_ids)
    if not normalized_ids:
        raise ValueError("Select at least one runtime scene to delete")

    deleted_ids: list[str] = []
    missing_ids: list[str] = []
    for scene_id in normalized_ids:
        try:
            scene_dir = _resolve_scene_dir(scene_id)
        except FileNotFoundError:
            missing_ids.append(scene_id)
            continue
        manifest = _load_scene_manifest(scene_dir)
        if str(manifest.get("status", "") or "").strip().lower() == "running":
            raise ValueError(f"Runtime scene is still running: {scene_id}")
        shutil.rmtree(scene_dir)
        deleted_ids.append(scene_id)

    return {
        "requestedCount": len(normalized_ids),
        "deletedCount": len(deleted_ids),
        "missingCount": len(missing_ids),
        "deletedSceneIds": deleted_ids,
        "missingSceneIds": missing_ids,
        "summary": (
            f"Deleted {len(deleted_ids)} runtime scene bundle"
            f"{'' if len(deleted_ids) == 1 else 's'}."
        ),
    }


def _scene_dirs() -> list[Path]:
    runtime_scene_root = _runtime_scene_root()
    if not runtime_scene_root.exists() or not runtime_scene_root.is_dir():
        return []
    return sorted([path for path in runtime_scene_root.iterdir() if path.is_dir()], reverse=True)


def _analyze_runtime_scene_content(scene_id: str, relative_path: str, content: str) -> dict[str, Any]:
    return analyze_log_content(
        anchor=f"runtime_scenes/{scene_id}/{relative_path}",
        content=content,
        normal_summary="这份原始日志未发现明显错误或警告，可作为运行现场的补充证据。",
        empty_summary="这份原始日志为空，暂时不能作为诊断证据。",
        error_summary_prefix="这份原始日志发现 ",
        warning_summary_prefix="这份原始日志发现 ",
        error_next_step="打开错误筛选，围绕第 {line} 行对照左侧统一时间线和 rawRefs。",
        warning_next_step="打开警告筛选，把第 {line} 行附近的重试/超时与 timeline 事件对齐。",
        structured_next_step="按结构化事件类型回到统一时间线，确认这份原始日志对应的组件阶段。",
        fallback_next_step="如当前问题仍未解释，继续查看同一运行现场的其它 raw 日志。",
    )


def _load_scene_manifest(scene_dir: Path) -> dict:
    manifest_path = scene_dir / "manifest.json"
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    return payload if isinstance(payload, dict) else {}


def _save_scene_manifest(scene_dir: Path, manifest: dict[str, Any]) -> None:
    manifest_path = scene_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _scene_id(scene_dir: Path, manifest: dict) -> str:
    value = str(manifest.get("runtime_scene_id") or "").strip()
    if value:
        return value
    marker = "__"
    if marker in scene_dir.name:
        return scene_dir.name.split(marker, 1)[1].strip()
    return scene_dir.name


def _runtime_scene_display_name(scene_dir: Path, manifest: dict, scene_id: str) -> str:
    label = _display_name_time_label(str(manifest.get("started_at") or ""), scene_dir)
    trigger_label = _display_name_trigger_label(str(manifest.get("trigger") or ""))
    status_label = _display_name_status_label(manifest)
    parts = [item for item in [label, trigger_label, status_label] if item]
    if parts:
        return " · ".join(parts)
    return str(manifest.get("title") or scene_dir.name or scene_id).strip()


def _display_name_time_label(started_at: str, scene_dir: Path) -> str:
    parsed = _parse_datetime(started_at)
    if parsed is None:
        marker = "__"
        token = scene_dir.name.split(marker, 1)[0] if marker in scene_dir.name else scene_dir.name
        parsed = _parse_directory_timestamp_token(token)
    if parsed is None:
        return ""
    local_value = parsed.astimezone()
    return local_value.strftime("%m/%d %H:%M")


def _display_name_trigger_label(trigger: str) -> str:
    normalized = str(trigger or "").strip().lower()
    if not normalized:
        return "工作台运行"
    return DISPLAY_NAME_TRIGGER_LABELS.get(normalized, _humanize_runtime_token(normalized))


def _display_name_status_label(manifest: dict) -> str:
    status = str(manifest.get("status") or "").strip().lower()
    result = str(manifest.get("result") or "").strip().lower()
    stop_reason = str(manifest.get("stop_reason") or "").strip().lower()
    if status == "stopped" and (result or stop_reason):
        return DISPLAY_NAME_RESULT_LABELS.get(result) or _humanize_runtime_token(stop_reason or result)
    return DISPLAY_NAME_STATUS_LABELS.get(status, _humanize_runtime_token(status))


def _parse_datetime(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _parse_directory_timestamp_token(value: str) -> datetime | None:
    text = str(value or "").strip()
    for pattern in ("%Y%m%dT%H%M%SZ", "%Y%m%dT%H%M%S"):
        try:
            parsed = datetime.strptime(text, pattern)
        except ValueError:
            continue
        return parsed.replace(tzinfo=UTC)
    return None


def _humanize_runtime_token(value: str) -> str:
    token = str(value or "").strip(" ._-")
    if not token:
        return ""
    return token.replace("_", " ").replace("-", " ")


def _read_scene_timeline(scene_dir: Path) -> list[dict]:
    events_dir = scene_dir / "events"
    timeline: list[dict] = []
    if not events_dir.exists() or not events_dir.is_dir():
        return timeline

    for file_path in sorted(events_dir.glob("*.jsonl")):
        component = file_path.stem
        for entry in _read_jsonl_file(file_path):
            timeline.append(
                {
                    "runtimeSceneId": str(entry.get("runtime_scene_id") or _scene_id(scene_dir, {})),
                    "component": str(entry.get("component") or component),
                    "phase": str(entry.get("phase") or ""),
                    "eventCode": str(entry.get("event_code") or ""),
                    "level": str(entry.get("level") or "info"),
                    "message": str(entry.get("message") or ""),
                    "timestamp": str(entry.get("ts") or ""),
                    "seq": int(entry.get("seq") or 0),
                    "outcome": str(entry.get("outcome") or ""),
                    "fields": entry.get("fields") if isinstance(entry.get("fields"), dict) else {},
                    "rawRefs": entry.get("raw_refs") if isinstance(entry.get("raw_refs"), list) else [],
                }
            )

    timeline.sort(key=lambda item: (item["timestamp"], item["component"], item["seq"]))
    return timeline


def _read_jsonl_file(path: Path) -> list[dict]:
    rows: list[dict] = []
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return rows
    for line in lines:
        text = str(line or "").strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _load_launcher_state() -> dict[str, Any]:
    try:
        payload = json.loads(LAUNCHER_STATE_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _list_raw_files(scene_dir: Path) -> list[dict]:
    raw_dir = scene_dir / "raw"
    items: list[dict] = []
    if not raw_dir.exists() or not raw_dir.is_dir():
        return items
    for file_path in sorted(raw_dir.rglob("*")):
        if not file_path.is_file():
            continue
        relative = file_path.relative_to(scene_dir).as_posix()
        items.append(
            {
                "path": relative,
                "label": RAW_LABELS.get(relative, file_path.name),
                "size": file_path.stat().st_size,
                "language": LANGUAGE_BY_SUFFIX.get(file_path.suffix.lower(), "text"),
            }
        )
    return items


def _resolve_current_runtime_scene_dir() -> Path | None:
    launcher_state = _load_launcher_state()
    raw_dir = str(launcher_state.get("runtimeSceneDir") or "").strip()
    if not raw_dir:
        return None

    scene_dir = Path(raw_dir).resolve()
    try:
        scene_dir.relative_to(_runtime_scene_root())
    except ValueError:
        return None

    if not scene_dir.exists() or not scene_dir.is_dir():
        return None
    return scene_dir


def _resolve_scene_dir(scene_id: str) -> Path:
    target = str(scene_id or "").strip()
    if not target:
        raise FileNotFoundError("Runtime scene id is required")
    for scene_dir in _scene_dirs():
        manifest = _load_scene_manifest(scene_dir)
        if _scene_id(scene_dir, manifest) == target:
            return scene_dir
    raise FileNotFoundError(f"Runtime scene not found: {target}")


def _normalize_relative_path(value: str) -> str:
    relative = str(value or "").strip().replace("\\", "/")
    if not relative:
        raise ValueError("Runtime scene path is required")
    return relative


def _resolve_scene_child(scene_dir: Path, relative_path: str) -> Path:
    candidate = (scene_dir / relative_path).resolve()
    try:
        candidate.relative_to(scene_dir.resolve())
    except ValueError as exc:
        raise ValueError("Runtime scene path must stay inside the selected scene") from exc
    return candidate


def _append_scene_log_line(scene_dir: Path, relative_path: str, message: str) -> None:
    target = _resolve_scene_child(scene_dir, relative_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(f"{message}\n")


def _append_scene_event(scene_dir: Path, component: str, payload: dict[str, Any]) -> None:
    events_dir = scene_dir / "events"
    events_dir.mkdir(parents=True, exist_ok=True)
    event_path = events_dir / f"{component}.jsonl"
    with event_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        handle.write("\n")


def _next_scene_event_seq(scene_dir: Path, component: str) -> int:
    event_path = scene_dir / "events" / f"{component}.jsonl"
    last_seq = 0
    for row in _read_jsonl_file(event_path):
        try:
            last_seq = max(last_seq, int(row.get("seq") or 0))
        except (TypeError, ValueError):
            continue
    return last_seq + 1


def _update_browser_manifest(
    scene_dir: Path,
    manifest: dict[str, Any],
    timestamp: str,
    event_code: str,
    level: str,
    message: str,
    fields: dict[str, Any],
) -> None:
    browser = manifest.get("browser")
    if not isinstance(browser, dict):
        browser = {}

    browser["telemetry_path"] = BROWSER_TELEMETRY_RAW_PATH
    browser["last_event_at"] = timestamp

    field_to_manifest_key = {
        "href": "current_href",
        "pathname": "current_pathname",
        "title": "current_title",
        "activeNavHref": "active_nav_href",
        "activeNavText": "active_nav_text",
        "heading": "current_heading",
        "visibilityState": "visibility_state",
    }
    for field_name, manifest_key in field_to_manifest_key.items():
        value = fields.get(field_name)
        if isinstance(value, str) and value.strip():
            browser[manifest_key] = _truncate_text(value.strip(), MAX_TELEMETRY_FIELD_TEXT_CHARS)

    if "online" in fields:
        browser["online"] = bool(fields.get("online"))

    if event_code.startswith("browser.console."):
        browser["last_console_at"] = timestamp
        browser["last_console_level"] = level
        browser["last_console_message"] = message

    if event_code in {"browser.page.error", "browser.promise.rejected", "browser.resource.error"}:
        browser["last_page_error_at"] = timestamp
        browser["last_page_error_message"] = message

    manifest["browser"] = browser
    _save_scene_manifest(scene_dir, manifest)


def _update_backend_api_manifest(
    scene_dir: Path,
    manifest: dict[str, Any],
    timestamp: str,
    level: str,
    fields: dict[str, Any],
) -> None:
    backend = manifest.get("backend")
    if not isinstance(backend, dict):
        backend = {}

    backend["api_log_path"] = BACKEND_API_RAW_PATH
    backend["last_api_event_at"] = timestamp
    backend["last_api_event_level"] = level

    status_code = fields.get("statusCode")
    if isinstance(status_code, int):
        backend["last_api_status_code"] = status_code
    path_template = fields.get("pathTemplate")
    if isinstance(path_template, str) and path_template.strip():
        backend["last_api_path"] = _truncate_text(path_template.strip(), MAX_TELEMETRY_FIELD_TEXT_CHARS)
    method = fields.get("method")
    if isinstance(method, str) and method.strip():
        backend["last_api_method"] = method.strip()

    manifest["backend"] = backend
    _save_scene_manifest(scene_dir, manifest)


def _sanitize_token(value: object, *, default: str) -> str:
    token = str(value or "").strip()
    if not token:
        return default
    return _truncate_text(token, 120)


def _truncate_text(value: str, limit: int) -> str:
    text = str(value or "")
    return text if len(text) <= limit else f"{text[: max(0, limit - 3)]}..."


def _coerce_int(value: object, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_float(value: object, *, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_telemetry_fields(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= MAX_TELEMETRY_FIELD_ITEMS:
                break
            normalized[str(key)] = _normalize_telemetry_value(item, depth=0)
        return normalized
    if value is None:
        return {}
    return {"value": _normalize_telemetry_value(value, depth=0)}


def _normalize_telemetry_value(value: object, *, depth: int) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _truncate_text(value, MAX_TELEMETRY_FIELD_TEXT_CHARS)
    if depth >= 2:
        return _truncate_text(str(value), MAX_TELEMETRY_FIELD_TEXT_CHARS)
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= MAX_TELEMETRY_FIELD_ITEMS:
                break
            normalized[str(key)] = _normalize_telemetry_value(item, depth=depth + 1)
        return normalized
    if isinstance(value, (list, tuple)):
        return [
            _normalize_telemetry_value(item, depth=depth + 1)
            for item in list(value)[:MAX_TELEMETRY_FIELD_ITEMS]
        ]
    return _truncate_text(str(value), MAX_TELEMETRY_FIELD_TEXT_CHARS)


def _normalize_scene_ids(scene_ids: list[str] | tuple[str, ...]) -> list[str]:
    normalized: list[str] = []
    for item in scene_ids:
        value = str(item or "").strip()
        if not value or value in normalized:
            continue
        normalized.append(value)
    return normalized


def _runtime_scene_root() -> Path:
    return (PROJECT_ROOT / "logs" / "runtime_scenes").resolve()
