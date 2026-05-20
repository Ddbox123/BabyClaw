"""Real chat session payloads for the web workbench."""

from __future__ import annotations

import json
import queue
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from config.settings import get_web_chat_config
from core.chat.chat_result_contract import build_chat_coding_result_contract
from core.chat.chat_result_formatter import format_chat_reply
from core.chat.chat_task_types import trim_lines
from core.infrastructure.event_bus import EventNames, get_event_bus
from core.mental_model_flags import is_mental_model_enabled
from core.evaluation.chat_dataset_capture import ChatDatasetCaptureService
from core.evaluation.chat_segmenter import ChatTurnRecord, has_conclusion_signal, has_next_action_signal
from core.logging.logger import debug as _debug_logger
from core.logging.unified_logger import logger as unified_logger
from core.ui.chat_state import (
    DEFAULT_CHAT_CONVERSATION_ID,
    DEFAULT_CHAT_CONVERSATION_TITLE,
    load_chat_state,
    normalize_chat_messages,
    normalize_chat_tool_calls,
    save_chat_state,
)

from .i18n import get_web_language, text_for


PROJECT_ROOT = Path(__file__).resolve().parents[3]
_CHAT_STATE_LOCK = threading.Lock()
_RUNNING_SESSIONS_LOCK = threading.Lock()
_RUNNING_SESSION_IDS: set[str] = set()
_SESSION_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="web-chat-turn")
_SESSION_STREAM_SUBSCRIBERS_LOCK = threading.Lock()
_SESSION_STREAM_SUBSCRIBERS: dict[str, set[queue.Queue[dict[str, Any]]]] = {}
_SESSION_STREAM_HEARTBEAT_SECONDS = 15.0
_SESSION_STREAM_QUEUE_SIZE = 8
_SESSION_TURN_CONTROLS_LOCK = threading.Lock()
_SESSION_TURN_CONTROLS: dict[str, "SessionTurnControl"] = {}
_SESSION_LIVE_OUTPUTS_LOCK = threading.Lock()
_SESSION_LIVE_OUTPUTS: dict[str, "SessionLiveOutputState"] = {}
_SESSION_UI_CAPTURE_LOCK = threading.Lock()
_UNSET = object()


class SessionNotFoundError(ValueError):
    """Raised when a requested session id does not exist."""


class SessionBusyError(RuntimeError):
    """Raised when a session already has an active running turn."""


class SessionValidationError(ValueError):
    """Raised when an incoming session turn payload is invalid."""


@dataclass
class SessionTurnControl:
    """Ephemeral runtime control surface for one active web chat turn."""

    session_id: str
    stop_requested: bool = False
    stop_requested_at: str = ""
    stop_reason: str = ""
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def request_stop(self, reason: str) -> None:
        with self._lock:
            if self.stop_requested:
                if reason and not self.stop_reason:
                    self.stop_reason = str(reason).strip()
                return
            self.stop_requested = True
            self.stop_requested_at = _now_timestamp()
            self.stop_reason = str(reason or "").strip()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "stopRequested": self.stop_requested,
                "stopRequestedAt": self.stop_requested_at,
                "stopReason": self.stop_reason,
            }


@dataclass
class SessionLiveOutputState:
    """Ephemeral live assistant output for one active web chat turn."""

    session_id: str
    thought: str = ""
    content: str = ""
    mental_snapshot: dict[str, Any] | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    updated_at: str = ""


@dataclass
class SessionTurnCapture:
    """Collect live UI breadcrumbs so the web session can replay them."""

    session_id: str
    thought: str = ""
    content: str = ""
    mental_state: dict[str, str] = field(default_factory=dict)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)

    def note_thought(self, text: str) -> None:
        cleaned = _sanitize_thought_text(text)
        if cleaned:
            self.thought = cleaned

    def clear_thought(self) -> None:
        self.thought = ""

    def note_content(self, text: str) -> None:
        cleaned = _sanitize_message_content("assistant", text)
        if cleaned:
            self.content = cleaned

    def clear_content(self) -> None:
        self.content = ""

    def note_mental_state(self, *, mood: str = "", feeling: str = "", whisper: str = "") -> None:
        self.mental_state = {
            "mood": str(mood or "").strip(),
            "feeling": str(feeling or "").strip(),
            "whisper": str(whisper or "").strip(),
        }

    def note_tool_event(self, name: str, status: str, summary: str = "") -> None:
        tool_name = str(name or "").strip()
        if not tool_name:
            return
        entry = {
            "name": tool_name,
            "status": _normalize_tool_call_status(status, default="running"),
        }
        cleaned_summary = trim_lines(summary or "", max_lines=2)
        if cleaned_summary:
            entry["summary"] = cleaned_summary
        for index in range(len(self.tool_calls) - 1, -1, -1):
            existing = self.tool_calls[index]
            if existing.get("name") == tool_name and existing.get("status") == "running":
                self.tool_calls[index] = entry
                return
        self.tool_calls.append(entry)
        if len(self.tool_calls) > 30:
            self.tool_calls = self.tool_calls[-30:]


def list_sessions() -> list[dict]:
    """Return summarized sessions sourced from persisted chat state."""

    active_id, conversations = _load_conversations()
    sessions = [_build_session_summary(item) for item in conversations]
    sessions.sort(
        key=lambda item: (
            0 if item["id"] == active_id else 1,
            -_timestamp_sort_key(item.get("updatedAt") or item.get("lastActive") or ""),
        )
    )
    return sessions


def get_session_detail(session_id: str) -> dict | None:
    """Return a session detail payload by persisted conversation id."""

    _, conversations = _load_conversations()
    for item in conversations:
        if item["id"] == session_id:
            return _build_session_detail(item)
    return None


def get_active_session_detail() -> dict | None:
    """Return the current active conversation detail when available."""

    active_id, conversations = _load_conversations()
    if not conversations:
        return None
    target_id = active_id or conversations[0]["id"]
    for item in conversations:
        if item["id"] == target_id:
            return _build_session_detail(item)
    return _build_session_detail(conversations[0])


def request_stop_session_turn(session_id: str) -> dict:
    """Request a graceful stop for one active web chat turn."""

    lang = get_web_language()
    conversation_id = str(session_id or "").strip()
    if not conversation_id:
        raise SessionNotFoundError(text_for(lang, zh="未找到当前会话。", en="Session not found."))

    detail = get_session_detail(conversation_id)
    if detail is None:
        raise SessionNotFoundError(text_for(lang, zh="未找到当前会话。", en="Session not found."))

    if not _is_session_running(conversation_id):
        return detail

    controller = _get_session_turn_control(conversation_id)
    if controller is None:
        controller = _create_session_turn_control(conversation_id)

    controller.request_stop(
        text_for(
            lang,
            zh="操作者请求停止当前轮。",
            en="The operator requested this turn to stop.",
        )
    )
    _publish_session_detail_snapshot(conversation_id)
    return get_session_detail(conversation_id) or detail


def stream_session_events(session_id: str, initial_detail: dict[str, Any] | None = None):
    """Yield SSE events for one persisted chat session."""

    conversation_id = str(session_id or "").strip()
    if not conversation_id:
        raise SessionNotFoundError(
            text_for(get_web_language(), zh="未找到当前会话。", en="Session not found.")
        )
    detail = initial_detail or get_session_detail(conversation_id)
    if detail is None:
        raise SessionNotFoundError(
            text_for(get_web_language(), zh="未找到当前会话。", en="Session not found.")
        )

    subscriber: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=_SESSION_STREAM_QUEUE_SIZE)
    _register_session_stream_subscriber(conversation_id, subscriber)
    try:
        yield _encode_sse_event(
            "session_detail",
            {
                "type": "session_detail",
                "sessionId": conversation_id,
                "detail": detail,
            },
        )
        while True:
            try:
                event = subscriber.get(timeout=_SESSION_STREAM_HEARTBEAT_SECONDS)
            except queue.Empty:
                yield ": keep-alive\n\n"
                continue
            yield _encode_sse_event(str(event.get("type") or "message"), event)
    finally:
        _unregister_session_stream_subscriber(conversation_id, subscriber)


def submit_session_message(session_id: str, content: str) -> dict:
    """Persist a user message and start a single web chat turn."""

    lang = get_web_language()
    conversation_id = str(session_id or "").strip()
    message = str(content or "").strip()
    if not conversation_id:
        raise SessionNotFoundError(text_for(lang, zh="未找到当前会话。", en="Session not found."))
    if not message:
        raise SessionValidationError(
            text_for(lang, zh="请输入本轮消息后再发送。", en="Enter a message before sending.")
        )

    with _CHAT_STATE_LOCK:
        payload = load_chat_state(PROJECT_ROOT)
        conversation = _find_conversation_entry(payload, conversation_id)
        if conversation is None:
            raise SessionNotFoundError(text_for(lang, zh="未找到当前会话。", en="Session not found."))

        if _is_session_running(conversation_id):
            raise SessionBusyError(
                text_for(
                    lang,
                    zh="当前会话仍在运行，请等这一轮结束后再继续发送。",
                    en="This session is still running. Wait for the current turn to finish before sending again.",
                )
            )

        previous_messages = normalize_chat_messages(conversation.get("messages") or [])
        user_entry = _make_chat_message("user", message)
        conversation["messages"] = previous_messages + [user_entry]
        conversation["last_turn_status"] = "running"
        conversation["updated_at"] = user_entry["timestamp"]
        payload["active_conversation_id"] = conversation_id
        payload["updated_at"] = user_entry["timestamp"]
        save_chat_state(PROJECT_ROOT, payload)
        _set_session_running(conversation_id, True)
        _create_session_turn_control(conversation_id)
    _publish_session_detail_snapshot(conversation_id)

    context = {
        "session_id": conversation_id,
        "user_message": message,
        "history_messages": previous_messages,
    }
    try:
        _schedule_session_turn(context)
    except Exception as exc:
        _set_session_running(conversation_id, False)
        _clear_session_turn_control(conversation_id)
        _persist_session_turn_failure(conversation_id, context, exc)
        _publish_session_detail_snapshot(conversation_id)
        raise
    return get_session_detail(conversation_id) or {}


def _load_conversations() -> tuple[str, list[dict[str, Any]]]:
    payload = load_chat_state(PROJECT_ROOT)
    active_id = str(payload.get("active_conversation_id") or DEFAULT_CHAT_CONVERSATION_ID).strip()
    conversations: list[dict[str, Any]] = []
    for raw in list(payload.get("conversations") or []):
        conversation = _normalize_conversation(raw)
        if conversation is not None:
            conversations.append(conversation)
    return active_id or DEFAULT_CHAT_CONVERSATION_ID, conversations


def _normalize_conversation(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    conversation_id = str(raw.get("conversation_id") or DEFAULT_CHAT_CONVERSATION_ID).strip()
    if not conversation_id:
        return None
    title = str(raw.get("title") or DEFAULT_CHAT_CONVERSATION_TITLE).strip() or DEFAULT_CHAT_CONVERSATION_TITLE
    messages = _normalize_messages(conversation_id, raw.get("messages") or [])
    last_turn_status = str(raw.get("last_turn_status") or "").strip().lower()
    updated_at = (
        str(raw.get("updated_at") or "").strip()
        or _latest_message_timestamp(messages)
    )
    active_task = raw.get("active_task")
    if not isinstance(active_task, dict):
        active_task = raw.get("activeTask")
    if not isinstance(active_task, dict):
        active_task = None
    return {
        "id": conversation_id,
        "title": title,
        "messages": messages,
        "lastTurnStatus": last_turn_status,
        "updatedAt": updated_at,
        "activeTask": dict(active_task or {}) if isinstance(active_task, dict) else None,
    }


def _normalize_messages(conversation_id: str, items: Any) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for index, raw in enumerate(list(items or []), start=1):
        if not isinstance(raw, dict):
            continue
        role = str(raw.get("role") or "").strip().lower()
        if role not in {"user", "assistant"}:
            continue
        content = _sanitize_message_content(role, raw.get("content") or "")
        thought = _normalize_message_thought(raw, role=role)
        mental_snapshot = _normalize_mental_snapshot(raw.get("mental_snapshot") or raw.get("mentalSnapshot"))
        if not content and not thought and mental_snapshot is None:
            continue
        entry: dict[str, Any] = {
            "id": f"{conversation_id}-message-{index}",
            "role": role,
            "content": content,
            "timestamp": str(raw.get("timestamp") or "").strip(),
        }
        if thought:
            entry["thought"] = thought
        if mental_snapshot is not None:
            entry["mentalSnapshot"] = mental_snapshot
        tool_calls = _normalize_message_tool_calls(raw.get("tool_calls") or raw.get("toolCalls") or raw.get("tools") or [])
        if tool_calls:
            entry["toolCalls"] = tool_calls
        messages.append(entry)
    return messages


def _sanitize_message_content(role: str, content: Any) -> str:
    text = str(content or "").strip()
    if str(role or "").strip().lower() != "assistant":
        return text
    text = re.sub(
        r"<(?:think|thinking)[^>]*>.*?</(?:think|thinking)>",
        "",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    text = re.sub(
        r"<(?:think|thinking)[^>]*>.*$",
        "",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    text = re.sub(r"<state[^>]*>.*?</state>", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<state[^>]*>.*$", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"</?(?:think|thinking)[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"</?[\w:-]*tool_call[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _build_session_summary(conversation: dict[str, Any]) -> dict[str, Any]:
    status = _conversation_phase(conversation["id"], conversation)
    summary = _latest_message_summary(conversation.get("messages") or [])
    updated_at = str(conversation.get("updatedAt") or "").strip()
    return {
        "id": conversation["id"],
        "title": conversation["title"],
        "status": status,
        "taskSummary": summary,
        "lastActive": updated_at,
        "updatedAt": updated_at,
        "currentPhase": status,
    }


def _build_session_detail(conversation: dict[str, Any]) -> dict[str, Any]:
    summary = _build_session_summary(conversation)
    turn_control = _get_session_turn_control(conversation["id"])
    turn_snapshot = turn_control.snapshot() if turn_control is not None else {
        "stopRequested": False,
        "stopRequestedAt": "",
        "stopReason": "",
    }
    active_task = _normalize_session_active_task(
        conversation.get("active_task") or conversation.get("activeTask")
    )
    changed_files = list(active_task.get("changed_files") or []) if active_task else []
    read_files = list(active_task.get("read_files") or []) if active_task else []
    preview_tabs = list(active_task.get("preview_tabs") or []) if active_task else []
    default_file_context = str(active_task.get("default_file_context") or "").strip() if active_task else ""
    active_preview_path = (
        str(active_task.get("active_preview_path") or "").strip() if active_task else ""
    ) or "agent"
    detail_messages = _messages_with_live_output(conversation["id"], conversation.get("messages") or [])
    detail = {
        **summary,
        "defaultFileContext": default_file_context,
        "previewTabs": preview_tabs,
        "activePreviewPath": active_preview_path,
        "changedFiles": changed_files,
        "readFiles": read_files,
        "messages": detail_messages,
        "stopRequested": bool(turn_snapshot["stopRequested"]),
        "stopRequestedAt": str(turn_snapshot["stopRequestedAt"] or "").strip(),
        "stopReason": str(turn_snapshot["stopReason"] or "").strip(),
    }
    return detail


def _normalize_project_paths(items: Any, *, existing_only: bool) -> list[str]:
    project_root = PROJECT_ROOT.resolve()
    paths: list[str] = []
    for raw in list(items or []):
        value = str(raw or "").strip()
        if not value or value in {".", "./"}:
            continue
        candidate = (project_root / value).resolve()
        try:
            candidate.relative_to(project_root)
        except ValueError:
            continue
        if existing_only:
            if not candidate.exists() or not candidate.is_file():
                continue
        elif candidate.exists() and candidate.is_dir():
            continue
        normalized = candidate.relative_to(project_root).as_posix()
        if normalized not in paths:
            paths.append(normalized)
    return paths


def _normalize_project_path(value: Any, *, existing_only: bool) -> str:
    paths = _normalize_project_paths([value], existing_only=existing_only)
    return paths[0] if paths else ""


def _merge_project_paths(*groups: list[str], limit: int = 8) -> list[str]:
    merged: list[str] = []
    for group in groups:
        for raw in list(group or []):
            value = str(raw or "").strip()
            if not value or value in merged:
                continue
            merged.append(value)
    if limit > 0:
        return merged[-limit:]
    return merged


def _normalize_session_active_task(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None

    read_files = _normalize_project_paths(
        value.get("read_files") or value.get("readFiles") or [],
        existing_only=True,
    )
    changed_files = _normalize_project_paths(
        value.get("changed_files") or value.get("changedFiles") or [],
        existing_only=False,
    )
    preview_tabs = _merge_project_paths(
        _normalize_project_paths(
            value.get("preview_tabs") or value.get("previewTabs") or [],
            existing_only=True,
        ),
        _normalize_project_paths(changed_files, existing_only=True),
        read_files,
    )
    default_file_context = (
        _normalize_project_path(
            value.get("default_file_context") or value.get("defaultFileContext"),
            existing_only=False,
        )
        or (changed_files[-1] if changed_files else "")
        or (read_files[-1] if read_files else "")
    )
    active_preview_path = (
        _normalize_project_path(
            value.get("active_preview_path") or value.get("activePreviewPath"),
            existing_only=True,
        )
        or _normalize_project_path(default_file_context, existing_only=True)
        or (preview_tabs[0] if preview_tabs else "")
    )
    if active_preview_path and active_preview_path not in preview_tabs:
        preview_tabs = [active_preview_path, *preview_tabs]
    if not active_preview_path:
        active_preview_path = "agent"

    normalized = {
        "task_id": str(value.get("task_id") or value.get("taskId") or "").strip(),
        "kind": str(value.get("kind") or "coding").strip().lower() or "coding",
        "status": str(value.get("status") or "idle").strip().lower() or "idle",
        "title": trim_lines(value.get("title") or "", max_lines=2),
        "goal": trim_lines(value.get("goal") or "", max_lines=2),
        "read_files": read_files,
        "changed_files": changed_files,
        "verification_status": str(value.get("verification_status") or value.get("verificationStatus") or "").strip().lower(),
        "verification_summary": trim_lines(
            value.get("verification_summary") or value.get("verificationSummary") or "",
            max_lines=4,
        ),
        "latest_summary": trim_lines(
            value.get("latest_summary") or value.get("latestSummary") or "",
            max_lines=6,
        ),
        "next_action": trim_lines(
            value.get("next_action") or value.get("nextAction") or "",
            max_lines=3,
        ),
        "last_user_message": trim_lines(
            value.get("last_user_message") or value.get("lastUserMessage") or "",
            max_lines=3,
        ),
        "turn_count": _coerce_nonnegative_int(value.get("turn_count") or value.get("turnCount") or 0),
        "resume_count": _coerce_nonnegative_int(value.get("resume_count") or value.get("resumeCount") or 0),
        "created_at": str(value.get("created_at") or value.get("createdAt") or "").strip(),
        "updated_at": str(value.get("updated_at") or value.get("updatedAt") or "").strip(),
        "default_file_context": default_file_context,
        "preview_tabs": preview_tabs,
        "active_preview_path": active_preview_path,
        "metadata": dict(value.get("metadata") or {}) if isinstance(value.get("metadata"), dict) else {},
    }
    if not any(
        (
            normalized["read_files"],
            normalized["changed_files"],
            normalized["verification_status"],
            normalized["verification_summary"],
            normalized["next_action"],
            normalized["latest_summary"],
        )
    ):
        return None
    return normalized


def _latest_assistant_summary(messages: list[dict[str, Any]]) -> str:
    for item in reversed(messages):
        if str(item.get("role") or "").strip().lower() != "assistant":
            continue
        return _compact_preview_text(item.get("content") or "")
    return ""


def _latest_user_summary(messages: list[dict[str, Any]]) -> str:
    for item in reversed(messages):
        if str(item.get("role") or "").strip().lower() != "user":
            continue
        return _compact_preview_text(item.get("content") or "")
    return ""


def _latest_user_message(messages: list[dict[str, Any]]) -> str:
    for item in reversed(messages):
        if str(item.get("role") or "").strip().lower() != "user":
            continue
        return trim_lines(item.get("content") or "", max_lines=4)
    return ""


def _latest_message_summary(messages: list[dict[str, Any]]) -> str:
    for item in reversed(messages):
        preview = _compact_preview_text(item.get("content") or "")
        if preview:
            return preview
    return ""


def _compact_preview_text(text: Any, *, max_lines: int = 3, max_chars: int = 180) -> str:
    lines = [re.sub(r"\s+", " ", str(line or "")).strip() for line in str(text or "").splitlines()]
    visible_lines = [line for line in lines if line]
    if not visible_lines:
        return ""
    preview = " ".join(visible_lines[:max_lines]).strip()
    if len(preview) <= max_chars:
        return preview
    return f"{preview[: max_chars - 1].rstrip()}..."


def _latest_message_timestamp(messages: list[dict[str, Any]]) -> str:
    for item in reversed(messages):
        timestamp = str(item.get("timestamp") or "").strip()
        if timestamp:
            return timestamp
    return ""


def _timestamp_sort_key(value: str) -> float:
    text = str(value or "").strip()
    if not text:
        return 0.0
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _find_conversation_entry(payload: dict[str, Any], session_id: str) -> dict[str, Any] | None:
    conversations = payload.get("conversations")
    if not isinstance(conversations, list):
        return None
    for item in conversations:
        if not isinstance(item, dict):
            continue
        if str(item.get("conversation_id") or "").strip() == session_id:
            return item
    return None


def _conversation_phase(conversation_id: str, conversation: dict[str, Any]) -> str:
    if _is_session_stop_requested(conversation_id):
        return "stopping"
    if _is_session_running(conversation_id):
        return "running"
    normalized = str(conversation.get("lastTurnStatus") or "").strip().lower()
    if normalized in {"failed", "ready"}:
        return normalized
    if conversation.get("messages"):
        return "ready"
    return "idle"


def _is_session_running(session_id: str) -> bool:
    with _RUNNING_SESSIONS_LOCK:
        return session_id in _RUNNING_SESSION_IDS


def has_running_sessions() -> bool:
    """Return whether any web chat session turn is currently active."""

    with _RUNNING_SESSIONS_LOCK:
        return bool(_RUNNING_SESSION_IDS)


def _set_session_running(session_id: str, is_running: bool) -> None:
    with _RUNNING_SESSIONS_LOCK:
        if is_running:
            _RUNNING_SESSION_IDS.add(session_id)
        else:
            _RUNNING_SESSION_IDS.discard(session_id)


def _schedule_session_turn(context: dict[str, Any]) -> None:
    _SESSION_EXECUTOR.submit(_run_session_turn, context)


def _run_session_turn(context: dict[str, Any]) -> None:
    session_id = str(context.get("session_id") or "").strip()
    turn_capture = SessionTurnCapture(session_id=session_id)
    try:
        initial_stop_reason = _get_session_stop_reason(session_id)
        if initial_stop_reason:
            _persist_session_turn_result(session_id, _build_stopped_turn_result(initial_stop_reason))
            return

        with _capture_session_ui_stream(session_id, turn_capture):
            agent = create_chat_agent()
            restore = getattr(agent, "seed_chat_history", None)
            stop_configurer = getattr(agent, "set_turn_interrupt_checker", None)
            if callable(stop_configurer):
                stop_configurer(lambda: _get_session_stop_reason(session_id))
            history_messages = list(context.get("history_messages") or [])
            if callable(restore) and history_messages:
                restore(history_messages)

            preflight_stop_reason = _get_session_stop_reason(session_id)
            if preflight_stop_reason:
                _persist_session_turn_result(session_id, _build_stopped_turn_result(preflight_stop_reason))
                return

            user_message = str(context.get("user_message") or "").strip()
            result = _run_session_continuation_loop(
                agent,
                session_id=session_id,
                initial_prompt=user_message,
                history_messages=history_messages,
            )
        result = _attach_turn_capture_to_result(result, turn_capture)
        _persist_session_turn_result(session_id, result)
    except Exception as exc:
        _persist_session_turn_failure(session_id, context, exc)
    finally:
        _set_session_running(session_id, False)
        _clear_session_turn_control(session_id)
        _publish_session_detail_snapshot(session_id)


def create_chat_agent() -> Any:
    from agent import SelfEvolvingAgent

    return SelfEvolvingAgent(mode="chat")


def _run_session_continuation_loop(
    agent: Any,
    *,
    session_id: str,
    initial_prompt: str,
    history_messages: list[dict[str, Any]],
) -> Any:
    max_turns = _web_chat_max_continuation_turns()
    prompt = str(initial_prompt or "").strip()
    if _is_continue_request(prompt):
        resume_goal = _latest_unfinished_task_goal(session_id)
        if resume_goal:
            prompt = f"继续完成上一任务：{resume_goal}"

    result: Any = None
    for turn_index in range(1, max_turns + 1):
        stop_reason = _get_session_stop_reason(session_id)
        if stop_reason:
            return _build_stopped_turn_result(stop_reason)

        result = agent.run_single_turn(initial_prompt=prompt)
        if _is_session_turn_terminal(result):
            return _annotate_continuation_result(result, turn_index, max_turns, reached_limit=False)

        if turn_index >= max_turns:
            return _build_continuation_limit_result(result, turn_index, max_turns)

        prompt = _build_followup_prompt(
            original_prompt=initial_prompt,
            effective_prompt=prompt,
            latest_result=result,
            history_messages=history_messages,
            turn_index=turn_index,
        )

    return _build_continuation_limit_result(result, max_turns, max_turns)


def _persist_session_turn_result(session_id: str, result: Any) -> None:
    lang = get_web_language()
    capture_messages: list[dict[str, Any]] | None = None
    with _CHAT_STATE_LOCK:
        payload = load_chat_state(PROJECT_ROOT)
        conversation = _find_conversation_entry(payload, session_id)
        if conversation is None:
            return
        messages = normalize_chat_messages(conversation.get("messages") or [])
        result_status = str(result.get("status") or "").strip().lower() if isinstance(result, dict) else ""
        stop_requested = bool(result.get("stop_requested")) if isinstance(result, dict) else False
        assistant_text = (
            text_for(
                lang,
                zh="本轮已按请求停止。",
                en="This turn was stopped as requested.",
            )
            if stop_requested
            else _format_visible_reply(result)
        )
        assistant_entry = _make_chat_message(
            "assistant",
            assistant_text,
            _extract_chat_tool_calls(result),
            thought=_extract_chat_thought(result, assistant_text),
            mental_snapshot=_build_turn_mental_snapshot(result, lang),
        )
        if isinstance(result, dict):
            assistant_entry["toolCalls"] = _normalize_message_tool_calls(_extract_chat_tool_calls(result))
        conversation["messages"] = messages + [assistant_entry]
        existing_active_task = _normalize_session_active_task(
            conversation.get("active_task") or conversation.get("activeTask")
        )
        next_active_task = _build_session_active_task(
            session_id,
            result,
            conversation["messages"],
            existing_task=existing_active_task,
        )
        if next_active_task is not None:
            conversation["active_task"] = next_active_task
        conversation["last_turn_status"] = "failed" if result_status == "failed" else "ready"
        conversation["updated_at"] = assistant_entry["timestamp"]
        payload["updated_at"] = assistant_entry["timestamp"]
        save_chat_state(PROJECT_ROOT, payload)
        _clear_session_live_output(session_id)
        if result_status == "completed" and not stop_requested:
            capture_messages = list(conversation["messages"])
    if capture_messages:
        _capture_session_chat_candidate(session_id, capture_messages)


def _persist_session_turn_failure(session_id: str, context: dict[str, Any], exc: Exception) -> None:
    lang = get_web_language()
    reason = trim_lines(str(exc or "").strip(), max_lines=2)
    summary = text_for(
        lang,
        zh="网页工作台这一轮执行失败，请检查配置或稍后重试。",
        en="This web workbench turn failed. Check configuration and try again.",
    )
    if reason:
        summary = f"{summary}\n{reason}"

    with _CHAT_STATE_LOCK:
        payload = load_chat_state(PROJECT_ROOT)
        conversation = _find_conversation_entry(payload, session_id)
        if conversation is None:
            return
        messages = normalize_chat_messages(conversation.get("messages") or [])
        assistant_entry = _make_chat_message("assistant", summary)
        conversation["messages"] = messages + [assistant_entry]
        conversation["last_turn_status"] = "failed"
        conversation["updated_at"] = assistant_entry["timestamp"]
        payload["updated_at"] = assistant_entry["timestamp"]
        save_chat_state(PROJECT_ROOT, payload)
        _clear_session_live_output(session_id)


def _make_chat_message(
    role: str,
    content: str,
    tool_calls: list[Any] | None = None,
    *,
    thought: str = "",
    mental_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    message: dict[str, Any] = {
        "role": str(role or "").strip().lower(),
        "content": str(content or "").strip(),
        "timestamp": _now_timestamp(),
    }
    cleaned_thought = _sanitize_thought_text(thought)
    if cleaned_thought:
        message["thought"] = cleaned_thought
    normalized_snapshot = _normalize_mental_snapshot(mental_snapshot)
    if normalized_snapshot is not None:
        message["mental_snapshot"] = normalized_snapshot
    normalized_tool_calls = _normalize_persisted_tool_calls(tool_calls or [])
    if normalized_tool_calls:
        message["tool_calls"] = normalized_tool_calls
    return message


def _now_timestamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _normalize_tool_call_status(value: Any, *, default: str = "done") -> str:
    status = str(value or "").strip().lower()
    if status in {"running", "pending", "done", "success", "failed", "error", "blocked"}:
        if status == "success":
            return "done"
        if status == "error":
            return "failed"
        return status
    return default


def _tool_call_name(raw: Any) -> str:
    if isinstance(raw, dict):
        function_block = raw.get("function") or {}
        if not isinstance(function_block, dict):
            function_block = {}
        return str(
            raw.get("name")
            or raw.get("tool_name")
            or function_block.get("name")
            or ""
        ).strip()
    return str(raw or "").strip()


def _normalize_persisted_tool_calls(value: Any) -> list[dict[str, Any]]:
    tool_calls: list[dict[str, Any]] = []
    for item in list(value or []):
        name = _tool_call_name(item)
        if not name:
            continue
        status = _normalize_tool_call_status(
            item.get("status") if isinstance(item, dict) else "",
            default="done",
        )
        entry: dict[str, Any] = {
            "name": name,
            "status": status,
        }
        if isinstance(item, dict):
            summary = trim_lines(
                item.get("summary")
                or item.get("result_preview")
                or item.get("resultPreview")
                or item.get("error")
                or "",
                max_lines=2,
            )
            if summary:
                entry["summary"] = summary
        tool_calls.append(entry)
    return tool_calls


def _normalize_message_tool_calls(value: Any) -> list[dict[str, Any]]:
    tool_calls: list[dict[str, Any]] = []
    for item in _normalize_persisted_tool_calls(value):
        entry = {
            "name": str(item.get("name") or "").strip(),
            "status": _normalize_tool_call_status(item.get("status"), default="done"),
        }
        summary = trim_lines(item.get("summary") or "", max_lines=2)
        if summary:
            entry["summary"] = summary
        if entry["name"]:
            tool_calls.append(entry)
    return tool_calls


def _extract_chat_tool_calls(result: Any) -> list[dict[str, Any]]:
    if not isinstance(result, dict):
        return []
    tool_calls = _normalize_persisted_tool_calls(result.get("tool_trace") or [])
    if tool_calls:
        return tool_calls
    return _normalize_persisted_tool_calls(result.get("tool_calls") or result.get("tools") or [])


def _extract_chat_thought(result: Any, assistant_text: str) -> str:
    if not isinstance(result, dict) or bool(result.get("stop_requested")):
        return ""

    candidates = [
        result.get("thought"),
        result.get("reasoning_content"),
        _extract_embedded_thought(result.get("raw_output") or ""),
        _extract_embedded_thought(result.get("summary") or ""),
        _extract_embedded_thought(result.get("message") or ""),
    ]
    for candidate in candidates:
        cleaned = _sanitize_thought_text(candidate)
        if not cleaned:
            continue
        if _thought_duplicates_reply(cleaned, assistant_text):
            continue
        return cleaned
    return ""


def _format_visible_reply(result: Any) -> str:
    if not isinstance(result, dict):
        return text_for(
            get_web_language(),
            zh="本轮没有产生可见回复。",
            en="This turn did not produce a visible reply.",
        )

    visible = _sanitize_message_content(
        "assistant",
        result.get("raw_output") or result.get("summary") or result.get("error") or result.get("message") or "",
    )
    if visible and not _looks_like_structured_payload(visible):
        return visible

    summary = _sanitize_message_content("assistant", format_chat_reply(result))
    if summary:
        return summary
    return text_for(
        get_web_language(),
        zh="本轮没有产生可见回复。",
        en="This turn did not produce a visible reply.",
    )


def _looks_like_structured_payload(text: str) -> bool:
    candidate = str(text or "").strip()
    if not candidate:
        return False
    if not (
        (candidate.startswith("{") and candidate.endswith("}"))
        or (candidate.startswith("[") and candidate.endswith("]"))
    ):
        return False
    try:
        parsed = json.loads(candidate)
    except Exception:
        return False
    return isinstance(parsed, (dict, list))


def _normalize_message_thought(raw: dict[str, Any], *, role: str) -> str:
    if role != "assistant":
        return ""
    explicit = _sanitize_thought_text(raw.get("thought") or "")
    if explicit:
        return explicit
    return _extract_embedded_thought(raw.get("content") or "")


def _extract_embedded_thought(content: Any) -> str:
    text = str(content or "")
    parts = [
        _sanitize_thought_text(match)
        for match in re.findall(
            r"<(?:think|thinking)[^>]*>(.*?)</(?:think|thinking)>",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
    ]
    parts = [item for item in parts if item]
    if not parts:
        open_match = re.search(r"<(?:think|thinking)[^>]*>(.*)$", text, flags=re.IGNORECASE | re.DOTALL)
        if open_match:
            candidate = _sanitize_thought_text(open_match.group(1))
            if candidate:
                parts.append(candidate)
    if not parts:
        return ""
    return "\n\n".join(parts).strip()


def _sanitize_thought_text(text: Any) -> str:
    cleaned = str(text or "")
    cleaned = re.sub(r"</?(?:think|thinking)[^>]*>", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<(?:think|thinking)?/?[^>\n]*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<state>.*?</state>", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"<state>\s*.*$", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"</?[\w:-]*tool_call[^>]*>", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _thought_duplicates_reply(thought: str, reply: str) -> bool:
    thought_compact = re.sub(r"\s+", " ", str(thought or "")).strip()
    reply_compact = re.sub(r"\s+", " ", str(reply or "")).strip()
    if not thought_compact or not reply_compact:
        return False
    if thought_compact == reply_compact:
        return True
    if thought_compact in reply_compact or reply_compact in thought_compact:
        shorter = min(len(thought_compact), len(reply_compact))
        longer = max(len(thought_compact), len(reply_compact))
        return shorter >= max(24, int(longer * 0.75))
    return False


def _normalize_mental_snapshot(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    raw_metrics = value.get("metrics")
    metrics = dict(raw_metrics) if isinstance(raw_metrics, dict) else {}
    history_tail: list[dict[str, Any]] = []
    if isinstance(value.get("historyTail"), list):
        history_source = value.get("historyTail")
    elif isinstance(value.get("history_tail"), list):
        history_source = value.get("history_tail")
    else:
        history_source = []
    for item in list(history_source or [])[-5:]:
        if isinstance(item, dict):
            history_tail.append({
                "cognitiveState": str(item.get("cognitiveState") or item.get("state") or item.get("cognitive_state") or "").strip(),
                "confidence": _coerce_confidence(item.get("confidence")),
                "timestamp": str(item.get("timestamp") or item.get("updatedAt") or item.get("updated_at") or "").strip(),
            })
    snapshot = {
        "mood": str(value.get("mood") or "").strip(),
        "feeling": str(value.get("feeling") or "").strip(),
        "whisper": str(value.get("whisper") or "").strip(),
        "summary": str(value.get("summary") or "").strip(),
        "cognitiveState": str(value.get("cognitiveState") or value.get("cognitive_state") or "").strip(),
        "confidence": _coerce_confidence(value.get("confidence")),
        "sampleSize": _coerce_nonnegative_int(value.get("sampleSize") or value.get("sample_size") or 0),
        "interventionCount": _coerce_nonnegative_int(
            value.get("interventionCount") or value.get("intervention_count") or 0
        ),
        "updatedAt": str(value.get("updatedAt") or value.get("updated_at") or "").strip(),
        "source": str(value.get("source") or "").strip(),
        "intervention": trim_lines(value.get("intervention") or "", max_lines=8),
        "metrics": metrics,
        "historyTail": history_tail,
    }
    if not snapshot["summary"]:
        snapshot["summary"] = snapshot["feeling"] or snapshot["whisper"]
    return snapshot


def _coerce_confidence(value: Any) -> float:
    try:
        return max(0.0, min(float(value or 0.0), 1.0))
    except (TypeError, ValueError):
        return 0.0


def _coerce_nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _has_meaningful_mental_snapshot(snapshot: dict[str, Any] | None) -> bool:
    if not isinstance(snapshot, dict):
        return False
    return any(
        str(snapshot.get(key) or "").strip()
        for key in ("mood", "feeling", "whisper", "cognitiveState")
    )


def _live_mental_snapshot(state_info: dict[str, Any], lang: str) -> dict[str, Any] | None:
    mood = str((state_info or {}).get("mood") or "").strip()
    feeling = str((state_info or {}).get("feeling") or "").strip()
    whisper = str((state_info or {}).get("whisper") or "").strip()
    if not any((mood, feeling, whisper)):
        return None
    return {
        "mood": mood,
        "feeling": feeling,
        "whisper": whisper,
        "summary": feeling or whisper or text_for(
            lang,
            zh="当前心智层已给出最近一次状态。",
            en="The mental layer has produced a recent state.",
        ),
        "cognitiveState": "",
        "confidence": 0.0,
        "sampleSize": 0,
        "interventionCount": 0,
        "updatedAt": _now_timestamp(),
        "source": "state",
    }


def _build_turn_mental_snapshot(result: Any, lang: str) -> dict[str, Any] | None:
    if not is_mental_model_enabled():
        return None
    state_snapshot = None
    if isinstance(result, dict):
        explicit = _normalize_mental_snapshot(result.get("mental_snapshot") or result.get("mentalSnapshot"))
        if _has_meaningful_mental_snapshot(explicit):
            return explicit
        state_snapshot = _live_mental_snapshot(result.get("state_info") or result.get("stateInfo") or {}, lang)
    else:
        state_snapshot = None

    runtime_snapshot = None
    try:
        from .runtime_service import _mental_state_summary

        runtime_snapshot = _normalize_mental_snapshot(_mental_state_summary(lang))
    except Exception:
        runtime_snapshot = None

    diagnosis_snapshot = _diagnosis_mental_snapshot(lang)

    if _has_meaningful_mental_snapshot(runtime_snapshot):
        merged = dict(runtime_snapshot)
        if diagnosis_snapshot:
            for key in ("intervention", "metrics", "historyTail"):
                if diagnosis_snapshot.get(key):
                    merged[key] = diagnosis_snapshot[key]
            if not merged.get("cognitiveState"):
                merged["cognitiveState"] = diagnosis_snapshot.get("cognitiveState", "")
            if not merged.get("confidence"):
                merged["confidence"] = diagnosis_snapshot.get("confidence", 0.0)
            if not merged.get("sampleSize"):
                merged["sampleSize"] = diagnosis_snapshot.get("sampleSize", 0)
            if not merged.get("interventionCount"):
                merged["interventionCount"] = diagnosis_snapshot.get("interventionCount", 0)
        return _normalize_mental_snapshot(merged)
    if _has_meaningful_mental_snapshot(state_snapshot):
        return state_snapshot
    if _has_meaningful_mental_snapshot(diagnosis_snapshot):
        return diagnosis_snapshot
    return None


def _diagnosis_mental_snapshot(lang: str) -> dict[str, Any] | None:
    try:
        from core.infrastructure.mental_model import get_mental_model

        mental_model = get_mental_model(workspace_root=str(PROJECT_ROOT / "workspace"))
        diagnosis = mental_model.diagnose()
        history = []
        try:
            history = mental_model.get_diagnosis_history(limit=5)
        except Exception:
            history = []
    except Exception:
        return None

    metrics = getattr(diagnosis, "metrics", {}) or {}
    cognitive_state = str(getattr(diagnosis, "state", "") or "").strip()
    intervention = trim_lines(getattr(diagnosis, "intervention", "") or "", max_lines=8)
    history_tail = [
        {
            "cognitiveState": str(getattr(item, "state", "") or "").strip(),
            "confidence": _coerce_confidence(getattr(item, "confidence", 0.0)),
            "timestamp": str(getattr(item, "timestamp", "") or "").strip(),
        }
        for item in list(history or [])[-5:]
    ]
    return _normalize_mental_snapshot({
        "mood": "",
        "feeling": "",
        "whisper": "",
        "summary": _mental_diagnosis_summary(lang, cognitive_state) if cognitive_state else "",
        "cognitiveState": cognitive_state,
        "confidence": _coerce_confidence(getattr(diagnosis, "confidence", 0.0)),
        "sampleSize": metrics.get("sample_size") or 0,
        "interventionCount": metrics.get("intervention_count") or 0,
        "updatedAt": str(getattr(diagnosis, "timestamp", "") or "").strip(),
        "source": "diagnosis",
        "intervention": intervention,
        "metrics": metrics,
        "historyTail": history_tail,
    })


def _mental_diagnosis_summary(lang: str, cognitive_state: str) -> str:
    labels = {
        "normal": text_for(lang, zh="心智诊断稳定。", en="Mental diagnosis is stable."),
        "productive": text_for(lang, zh="心智诊断显示当前推进顺畅。", en="Mental diagnosis shows productive progress."),
        "looping": text_for(lang, zh="心智诊断检测到重复循环。", en="Mental diagnosis detected looping."),
        "thrashing": text_for(lang, zh="心智诊断检测到工具或方案失稳。", en="Mental diagnosis detected thrashing."),
        "tunnel_vision": text_for(lang, zh="心智诊断检测到隧道视野。", en="Mental diagnosis detected tunnel vision."),
        "disoriented": text_for(lang, zh="心智诊断检测到方向分散。", en="Mental diagnosis detected disorientation."),
    }
    return labels.get(str(cognitive_state or "").strip().lower(), str(cognitive_state or "").strip())


def _messages_with_live_output(session_id: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    detail_messages = list(messages or [])
    live_message = _build_live_output_message(session_id)
    if live_message is None:
        return detail_messages
    return detail_messages + [live_message]


def _build_live_output_message(session_id: str) -> dict[str, Any] | None:
    with _SESSION_LIVE_OUTPUTS_LOCK:
        state = _SESSION_LIVE_OUTPUTS.get(session_id)
        if state is None:
            return None
        thought = str(state.thought or "").strip()
        content = str(state.content or "").strip()
        mental_snapshot = _normalize_mental_snapshot(state.mental_snapshot)
        tool_calls = _normalize_message_tool_calls(state.tool_calls)
        timestamp = str(state.updated_at or "").strip() or _now_timestamp()
    if not thought and not content and mental_snapshot is None and not tool_calls:
        return None
    message: dict[str, Any] = {
        "id": f"{session_id}-message-live",
        "role": "assistant",
        "content": content,
        "timestamp": timestamp,
        "streaming": True,
    }
    if thought:
        message["thought"] = thought
    if mental_snapshot is not None:
        message["mentalSnapshot"] = mental_snapshot
    if tool_calls:
        message["toolCalls"] = tool_calls
    return message


def _set_session_live_output(
    session_id: str,
    *,
    thought: Any = _UNSET,
    content: Any = _UNSET,
    mental_snapshot: Any = _UNSET,
    tool_calls: Any = _UNSET,
) -> None:
    with _SESSION_LIVE_OUTPUTS_LOCK:
        state = _SESSION_LIVE_OUTPUTS.get(session_id)
        if state is None:
            state = SessionLiveOutputState(session_id=session_id)
            _SESSION_LIVE_OUTPUTS[session_id] = state
        if thought is not _UNSET:
            state.thought = _sanitize_thought_text(thought)
        if content is not _UNSET:
            state.content = str(content or "").strip()
        if mental_snapshot is not _UNSET:
            state.mental_snapshot = _normalize_mental_snapshot(mental_snapshot)
        if tool_calls is not _UNSET:
            state.tool_calls = _normalize_message_tool_calls(tool_calls)
        state.updated_at = _now_timestamp()
        if not state.thought and not state.content and state.mental_snapshot is None and not state.tool_calls:
            _SESSION_LIVE_OUTPUTS.pop(session_id, None)
    _publish_session_detail_snapshot(session_id)


def _clear_session_live_output(session_id: str) -> None:
    with _SESSION_LIVE_OUTPUTS_LOCK:
        _SESSION_LIVE_OUTPUTS.pop(session_id, None)


def _attach_turn_capture_to_result(result: Any, capture: SessionTurnCapture) -> Any:
    if not isinstance(result, dict):
        return result
    if capture.thought and not result.get("thought") and not result.get("reasoning_content"):
        result["thought"] = capture.thought
    if capture.content and not result.get("raw_output") and not result.get("summary"):
        result["raw_output"] = capture.content
    if capture.mental_state and not result.get("state_info") and not result.get("stateInfo"):
        result["state_info"] = dict(capture.mental_state)
    if capture.tool_calls and not result.get("tool_trace") and not result.get("tool_calls"):
        result["tool_trace"] = list(capture.tool_calls)
    return result


@contextmanager
def _capture_session_ui_stream(session_id: str, capture: SessionTurnCapture):
    from core.ui import get_ui

    with _SESSION_UI_CAPTURE_LOCK:
        ui = get_ui()
        original_stream_thought = getattr(ui, "stream_thought", None)
        original_clear_thought_stream = getattr(ui, "clear_thought_stream", None)
        original_stream_response = getattr(ui, "stream_response", None)
        original_clear_response_stream = getattr(ui, "clear_response_stream", None)
        original_set_pet_mental_state = getattr(ui, "set_pet_mental_state", None)
        event_bus = get_event_bus()
        callback_ids: list[str] = []

        def stream_thought_proxy(text: str, done: bool = False):
            if callable(original_stream_thought):
                original_stream_thought(text, done=done)
            cleaned = _sanitize_thought_text(text)
            if cleaned and not done:
                capture.note_thought(cleaned)
                _set_session_live_output(session_id, thought=cleaned)

        def clear_thought_stream_proxy():
            if callable(original_clear_thought_stream):
                original_clear_thought_stream()
            capture.clear_thought()
            _set_session_live_output(session_id, thought="")

        def stream_response_proxy(text: str, done: bool = False):
            if callable(original_stream_response):
                original_stream_response(text, done=done)
            cleaned = _sanitize_message_content("assistant", text)
            if cleaned:
                capture.note_content(cleaned)
                _set_session_live_output(session_id, content=cleaned)

        def clear_response_stream_proxy():
            if callable(original_clear_response_stream):
                original_clear_response_stream()
            capture.clear_content()
            _set_session_live_output(session_id, content="")

        def set_pet_mental_state_proxy(mood: str = "", feeling: str = "", whisper: str = ""):
            if callable(original_set_pet_mental_state):
                original_set_pet_mental_state(mood=mood, feeling=feeling, whisper=whisper)
            capture.note_mental_state(mood=mood, feeling=feeling, whisper=whisper)
            if not is_mental_model_enabled():
                return
            snapshot = _live_mental_snapshot(capture.mental_state, get_web_language())
            if snapshot is not None:
                _set_session_live_output(session_id, mental_snapshot=snapshot)

        def tool_event_proxy(event):
            data = event.data or {}
            name = str(data.get("name") or "").strip()
            if not name:
                return
            status = {
                EventNames.TOOL_START: "running",
                EventNames.TOOL_SUCCESS: "done",
                EventNames.TOOL_ERROR: "failed",
            }.get(event.name, "running")
            summary = str(data.get("result") or data.get("error") or "").strip()
            capture.note_tool_event(name, status, summary)
            _set_session_live_output(session_id, tool_calls=capture.tool_calls)

        setattr(ui, "stream_thought", stream_thought_proxy)
        setattr(ui, "clear_thought_stream", clear_thought_stream_proxy)
        setattr(ui, "stream_response", stream_response_proxy)
        setattr(ui, "clear_response_stream", clear_response_stream_proxy)
        setattr(ui, "set_pet_mental_state", set_pet_mental_state_proxy)
        for event_name in (EventNames.TOOL_START, EventNames.TOOL_SUCCESS, EventNames.TOOL_ERROR):
            callback_ids.append(
                event_bus.subscribe(
                    event_name,
                    tool_event_proxy,
                    callback_id=f"web_chat_{session_id}_{event_name}_{id(capture)}",
                )
            )
        try:
            yield
        finally:
            for callback_id in callback_ids:
                event_bus.unsubscribe_by_id(callback_id)
            setattr(ui, "stream_thought", original_stream_thought)
            setattr(ui, "clear_thought_stream", original_clear_thought_stream)
            setattr(ui, "stream_response", original_stream_response)
            setattr(ui, "clear_response_stream", original_clear_response_stream)
            setattr(ui, "set_pet_mental_state", original_set_pet_mental_state)


def _capture_session_chat_candidate(session_id: str, messages: list[dict[str, Any]]) -> None:
    service = ChatDatasetCaptureService(project_root=PROJECT_ROOT)
    if not service.should_capture_mode("chat"):
        return
    turns = _build_chat_turn_records_from_messages(messages)
    if len(turns) < 2:
        return
    try:
        service.capture_candidate(
            mode="chat",
            session_id=session_id or "chat_session",
            source_log_path=_resolve_chat_source_log_path(),
            turns=turns,
        )
    except Exception as exc:
        _debug_logger.warning(f"web chat candidate capture skipped: {type(exc).__name__}: {exc}", tag="CHAT")


def _build_chat_turn_records_from_messages(messages: list[dict[str, Any]]) -> list[ChatTurnRecord]:
    turns: list[ChatTurnRecord] = []
    pending_user_message = ""
    for item in list(messages or []):
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        content = _sanitize_message_content(role, item.get("content") or "")
        if not content:
            continue
        if role == "user":
            pending_user_message = content
            continue
        if role != "assistant" or not pending_user_message:
            continue
        tool_calls = normalize_chat_tool_calls(item.get("tool_calls") or item.get("toolCalls") or item.get("tools") or [])
        turns.append(
            ChatTurnRecord(
                turn_number=len(turns) + 1,
                user_message=pending_user_message,
                assistant_message=content,
                tool_calls=tool_calls,
                tool_call_count=len(tool_calls),
                had_delegation=False,
                had_explicit_conclusion=has_conclusion_signal(content),
                had_next_action=has_next_action_signal(content),
                metadata={"mode": "chat", "source": "web_session"},
            )
        )
        pending_user_message = ""
    return turns


def _resolve_chat_source_log_path() -> str:
    conversation_logger = getattr(unified_logger, "conversation", None)
    current_session_file = str(getattr(conversation_logger, "_current_session_file", "") or "").strip()
    if current_session_file:
        path = Path(current_session_file)
        if path.exists():
            return str(path.resolve())
    log_dir = (PROJECT_ROOT / "log_info").resolve()
    if not log_dir.exists():
        return ""
    candidates = sorted(
        (path for path in log_dir.glob("conversation_*.jsonl") if path.is_file()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        return ""
    return str(candidates[0].resolve())


def _build_stopped_turn_result(reason: str) -> dict[str, Any]:
    return {
        "status": "stopped",
        "summary": "",
        "raw_output": "",
        "stop_requested": True,
        "stop_reason": str(reason or "").strip(),
        "tool_call_count": 0,
        "tool_trace": [],
    }


def _web_chat_max_continuation_turns() -> int:
    try:
        value = int(getattr(get_web_chat_config(), "max_continuation_turns", 4) or 4)
    except Exception:
        value = 4
    return max(1, value)


def _is_continue_request(text: Any) -> bool:
    normalized = re.sub(r"\s+", "", str(text or "").strip().lower())
    return normalized in {
        "继续",
        "接着",
        "继续做",
        "继续执行",
        "继续推进",
        "接着做",
        "继续上一轮",
        "继续上一个任务",
        "continue",
        "goon",
    }


def _latest_unfinished_task_goal(session_id: str) -> str:
    with _CHAT_STATE_LOCK:
        payload = load_chat_state(PROJECT_ROOT)
        conversation = _find_conversation_entry(payload, session_id)
        if conversation is None:
            return ""
        active_task = _normalize_session_active_task(
            conversation.get("active_task") or conversation.get("activeTask")
        )
    if not isinstance(active_task, dict):
        return ""
    status = str(active_task.get("status") or "").strip().lower()
    if status in {"done", "idle"}:
        return ""
    goal = trim_lines(active_task.get("goal") or active_task.get("title") or "", max_lines=2)
    if _is_continue_request(goal):
        return ""
    return goal


def _is_session_turn_terminal(result: Any) -> bool:
    if not isinstance(result, dict):
        return True
    if bool(result.get("stop_requested")):
        return True

    status = str(result.get("status") or "").strip().lower()
    contract = build_chat_coding_result_contract(result)
    outcome = str(contract.get("outcome") or "").strip().lower()
    visible = _visible_reply_candidate(result)
    tool_count = int(result.get("tool_call_count") or 0)
    tool_trace = list(result.get("tool_trace") or [])

    if status in {"failed", "timeout", "stopped"}:
        return True
    explicit_outcome = str(result.get("outcome") or result.get("task_outcome") or "").strip().lower()

    if outcome in {"done", "blocked", "needs_input"}:
        return True
    if explicit_outcome == "progress":
        return False
    if not visible and (tool_count > 0 or tool_trace):
        return False
    if not visible:
        return False
    return True


def _visible_reply_candidate(result: dict[str, Any]) -> str:
    return _sanitize_message_content(
        "assistant",
        result.get("raw_output") or result.get("summary") or result.get("error") or result.get("message") or "",
    )


def _annotate_continuation_result(
    result: Any,
    turn_count: int,
    max_turns: int,
    *,
    reached_limit: bool,
) -> Any:
    if not isinstance(result, dict):
        return result
    metadata = dict(result.get("metadata") or {}) if isinstance(result.get("metadata"), dict) else {}
    metadata.update(
        {
            "continuation_turn_count": turn_count,
            "max_continuation_turns": max_turns,
            "continuation_limit_reached": reached_limit,
        }
    )
    result["metadata"] = metadata
    return result


def _build_continuation_limit_result(result: Any, turn_count: int, max_turns: int) -> dict[str, Any]:
    base = dict(result or {}) if isinstance(result, dict) else {}
    contract = build_chat_coding_result_contract(base)
    visible = _visible_reply_candidate(base) if base else ""
    latest = trim_lines(visible, max_lines=4)
    raw_next_action = contract.get("next_action") or base.get("recommended_next_action") or ""
    next_action = trim_lines(raw_next_action or "发送“继续”以继续同一任务。", max_lines=2)
    summary_lines = [
        f"已达到 Web Chat 任务级持续上限（{max_turns} 轮），本次先暂停，避免后台无限运行。",
    ]
    if latest and "本轮没有产生可见回复" not in latest:
        summary_lines.append(f"当前进展：{latest}")
    if next_action and raw_next_action:
        summary_lines.append(f"下一步：{next_action}；也可以发送“继续”以继续同一任务。")
    else:
        summary_lines.append("下一步：发送“继续”以继续同一任务。")

    base.update(
        {
            "status": "completed",
            "summary": "\n".join(summary_lines),
            "raw_output": "\n".join(summary_lines),
            "outcome": "progress",
            "recommended_next_action": next_action or "发送“继续”以继续同一任务。",
        }
    )
    return _annotate_continuation_result(base, turn_count, max_turns, reached_limit=True)


def _build_followup_prompt(
    *,
    original_prompt: str,
    effective_prompt: str,
    latest_result: Any,
    history_messages: list[dict[str, Any]],
    turn_index: int,
) -> str:
    next_action = ""
    if isinstance(latest_result, dict):
        contract = build_chat_coding_result_contract(latest_result)
        next_action = trim_lines(
            contract.get("next_action") or latest_result.get("recommended_next_action") or "",
            max_lines=2,
        )
    goal = str(effective_prompt or original_prompt or "").strip()
    if _is_continue_request(goal):
        goal = _latest_user_message(history_messages) or str(original_prompt or "").strip()
    lines = [
        f"继续完成同一个用户目标：{goal}",
        f"上一内部回合仍未完成用户目标（第 {turn_index} 轮）。",
        "不要只输出 <state>；如果目标已完成，请给出可见汇报并标记 outcome=done。",
    ]
    if next_action:
        lines.append(f"优先执行上一轮下一步：{next_action}")
    return "\n".join(lines)


def _build_session_active_task(
    session_id: str,
    result: Any,
    messages: list[dict[str, Any]],
    *,
    existing_task: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not isinstance(result, dict):
        return existing_task

    contract = build_chat_coding_result_contract(result)
    read_files = _normalize_project_paths(contract.get("read_files") or [], existing_only=True)
    changed_files = _normalize_project_paths(contract.get("changed_files") or [], existing_only=False)
    if isinstance(existing_task, dict):
        if not read_files:
            read_files = _normalize_project_paths(existing_task.get("read_files") or [], existing_only=True)
        if not changed_files:
            changed_files = _normalize_project_paths(existing_task.get("changed_files") or [], existing_only=False)
    verification_status = str(contract.get("verification_status") or "").strip().lower()
    verification_summary = trim_lines(contract.get("verification_summary") or "", max_lines=4)
    blocked_reason = trim_lines(contract.get("blocked_reason") or "", max_lines=3)
    required_user_input = trim_lines(contract.get("required_user_input") or "", max_lines=3)
    next_action = trim_lines(contract.get("next_action") or "", max_lines=3)

    if not any(
        (
            read_files,
            changed_files,
            verification_status,
            verification_summary,
            blocked_reason,
            required_user_input,
            next_action,
        )
    ):
        return existing_task

    preview_tabs = _merge_project_paths(
        _normalize_project_paths(changed_files, existing_only=True),
        read_files,
    )
    default_file_context = (
        changed_files[-1] if changed_files else ""
    ) or (read_files[-1] if read_files else "")
    active_preview_path = (
        _normalize_project_path(default_file_context, existing_only=True)
        or (preview_tabs[0] if preview_tabs else "")
        or "agent"
    )
    if active_preview_path != "agent" and active_preview_path not in preview_tabs:
        preview_tabs = [active_preview_path, *preview_tabs]

    outcome = str(contract.get("outcome") or "").strip().lower()
    task_status = _task_status_from_result_contract(
        outcome,
        read_files=read_files,
        changed_files=changed_files,
        verification_status=verification_status,
    )
    latest_summary = trim_lines(
        _sanitize_message_content(
            "assistant",
            result.get("summary") or result.get("raw_output") or result.get("error") or result.get("message") or "",
        )
        or _format_visible_reply(result),
        max_lines=6,
    )
    last_user_message = _latest_user_message(messages)
    existing_metadata = dict(existing_task.get("metadata") or {}) if isinstance(existing_task, dict) else {}
    existing_created_at = str(existing_task.get("created_at") or "").strip() if isinstance(existing_task, dict) else ""
    existing_turn_count = (
        _coerce_nonnegative_int(existing_task.get("turn_count") or 0) if isinstance(existing_task, dict) else 0
    )
    existing_goal = (
        trim_lines(existing_task.get("goal") or existing_task.get("title") or "", max_lines=2)
        if isinstance(existing_task, dict)
        else ""
    )
    effective_goal = existing_goal if _is_continue_request(last_user_message) and existing_goal else last_user_message
    effective_title = (
        existing_goal
        if _is_continue_request(last_user_message) and existing_goal
        else (last_user_message or latest_summary)
    )
    metadata = dict(existing_metadata)
    metadata.update(
        {
            "source": "web_session",
            "outcome": outcome,
            "default_file_context": default_file_context,
            "active_preview_path": active_preview_path,
        }
    )
    if blocked_reason:
        metadata["blocked_reason"] = blocked_reason
    if required_user_input:
        metadata["required_user_input"] = required_user_input

    return {
        "task_id": str(existing_task.get("task_id") or f"{session_id}-coding-task").strip()
        if isinstance(existing_task, dict)
        else f"{session_id}-coding-task",
        "kind": "coding",
        "status": task_status,
        "title": trim_lines(effective_title, max_lines=2),
        "goal": trim_lines(effective_goal, max_lines=2),
        "read_files": read_files,
        "changed_files": changed_files,
        "verification_status": verification_status,
        "verification_summary": verification_summary,
        "latest_summary": latest_summary,
        "next_action": next_action or required_user_input or blocked_reason,
        "last_user_message": last_user_message,
        "turn_count": max(0, existing_turn_count) + 1,
        "resume_count": (
            _coerce_nonnegative_int(existing_task.get("resume_count") or 0)
            if isinstance(existing_task, dict)
            else 0
        ),
        "created_at": existing_created_at or _now_timestamp(),
        "updated_at": _now_timestamp(),
        "default_file_context": default_file_context,
        "preview_tabs": preview_tabs,
        "active_preview_path": active_preview_path,
        "metadata": metadata,
    }


def _task_status_from_result_contract(
    outcome: str,
    *,
    read_files: list[str],
    changed_files: list[str],
    verification_status: str,
) -> str:
    normalized_outcome = str(outcome or "").strip().lower()
    if normalized_outcome == "needs_input":
        return "needs_input"
    if normalized_outcome == "blocked":
        return "blocked"
    if normalized_outcome == "done":
        return "done"
    if verification_status == "passed" and changed_files:
        return "done"
    if changed_files:
        return "editing"
    if read_files:
        return "reading"
    return "idle"


def _create_session_turn_control(session_id: str) -> SessionTurnControl:
    with _SESSION_TURN_CONTROLS_LOCK:
        control = SessionTurnControl(session_id=session_id)
        _SESSION_TURN_CONTROLS[session_id] = control
        return control


def _get_session_turn_control(session_id: str) -> SessionTurnControl | None:
    with _SESSION_TURN_CONTROLS_LOCK:
        return _SESSION_TURN_CONTROLS.get(session_id)


def _clear_session_turn_control(session_id: str) -> None:
    with _SESSION_TURN_CONTROLS_LOCK:
        _SESSION_TURN_CONTROLS.pop(session_id, None)


def _is_session_stop_requested(session_id: str) -> bool:
    controller = _get_session_turn_control(session_id)
    if controller is None:
        return False
    return bool(controller.snapshot().get("stopRequested"))


def _get_session_stop_reason(session_id: str) -> str:
    controller = _get_session_turn_control(session_id)
    if controller is None:
        return ""
    snapshot = controller.snapshot()
    if not snapshot.get("stopRequested"):
        return ""
    return str(snapshot.get("stopReason") or "").strip()


def _register_session_stream_subscriber(session_id: str, subscriber: queue.Queue[dict[str, Any]]) -> None:
    with _SESSION_STREAM_SUBSCRIBERS_LOCK:
        bucket = _SESSION_STREAM_SUBSCRIBERS.setdefault(session_id, set())
        bucket.add(subscriber)


def _unregister_session_stream_subscriber(session_id: str, subscriber: queue.Queue[dict[str, Any]]) -> None:
    with _SESSION_STREAM_SUBSCRIBERS_LOCK:
        bucket = _SESSION_STREAM_SUBSCRIBERS.get(session_id)
        if not bucket:
            return
        bucket.discard(subscriber)
        if not bucket:
            _SESSION_STREAM_SUBSCRIBERS.pop(session_id, None)


def _publish_session_detail_snapshot(session_id: str) -> None:
    detail = get_session_detail(session_id)
    if detail is None:
        return
    event = {
        "type": "session_detail",
        "sessionId": session_id,
        "detail": detail,
    }
    with _SESSION_STREAM_SUBSCRIBERS_LOCK:
        subscribers = list(_SESSION_STREAM_SUBSCRIBERS.get(session_id) or [])
    for subscriber in subscribers:
        try:
            subscriber.put_nowait(event)
        except queue.Full:
            try:
                subscriber.get_nowait()
            except queue.Empty:
                pass
            try:
                subscriber.put_nowait(event)
            except queue.Full:
                continue


def _encode_sse_event(event_name: str, payload: dict[str, Any]) -> str:
    body = json.dumps(payload, ensure_ascii=False)
    return f"event: {event_name}\ndata: {body}\n\n"
