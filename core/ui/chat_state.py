# -*- coding: utf-8 -*-
"""chat 模式的轻量状态落盘与恢复。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


CHAT_STATE_VERSION = 1
DEFAULT_CHAT_CONVERSATION_ID = "default"
DEFAULT_CHAT_CONVERSATION_TITLE = "默认对话"


def chat_state_path(project_root: Path) -> Path:
    return project_root / "workspace" / "chat" / "chat_state.json"


def normalize_chat_tool_calls(value: Any) -> list[str]:
    tool_calls: list[str] = []
    for item in list(value or []):
        name = ""
        if isinstance(item, dict):
            function_block = item.get("function") or {}
            if not isinstance(function_block, dict):
                function_block = {}
            name = str(
                item.get("name")
                or item.get("tool_name")
                or function_block.get("name")
                or ""
            ).strip()
        else:
            name = str(item or "").strip()
        if name:
            tool_calls.append(name)
    return tool_calls


def normalize_chat_message(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    role = str(item.get("role") or "").strip().lower()
    if role not in {"user", "assistant"}:
        return None
    content = str(item.get("content") or "").strip()
    thought = str(item.get("thought") or "").strip()
    mental_snapshot = item.get("mental_snapshot")
    if mental_snapshot is None:
        mental_snapshot = item.get("mentalSnapshot")
    if role == "user" and not content:
        return None
    if role == "assistant" and not content and not thought and not isinstance(mental_snapshot, dict):
        return None
    timestamp = str(item.get("timestamp") or "").strip() or datetime.now().isoformat(timespec="seconds")
    normalized: dict[str, Any] = {
        "role": role,
        "content": content,
        "timestamp": timestamp,
    }
    if thought:
        normalized["thought"] = thought
    if isinstance(mental_snapshot, dict) and mental_snapshot:
        normalized["mental_snapshot"] = dict(mental_snapshot)
    tool_calls = normalize_chat_tool_calls(item.get("tool_calls") or item.get("tools") or [])
    if tool_calls:
        normalized["tool_calls"] = tool_calls
    return normalized


def normalize_chat_messages(items: Any) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for item in list(items or []):
        normalized = normalize_chat_message(item)
        if normalized is not None:
            messages.append(normalized)
    return messages


def load_chat_state(project_root: Path) -> dict[str, Any]:
    path = chat_state_path(project_root)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def save_chat_state(project_root: Path, state: dict[str, Any]) -> None:
    path = chat_state_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def get_active_chat_conversation(state: dict[str, Any]) -> dict[str, Any]:
    conversation_id = str(state.get("active_conversation_id") or DEFAULT_CHAT_CONVERSATION_ID).strip()
    conversations = state.get("conversations")
    if not isinstance(conversations, list):
        return {
            "conversation_id": conversation_id or DEFAULT_CHAT_CONVERSATION_ID,
            "title": DEFAULT_CHAT_CONVERSATION_TITLE,
            "messages": [],
            "active_task": None,
            "updated_at": "",
        }
    for item in conversations:
        if not isinstance(item, dict):
            continue
        if str(item.get("conversation_id") or "").strip() == conversation_id:
            return {
                "conversation_id": conversation_id,
                "title": str(item.get("title") or DEFAULT_CHAT_CONVERSATION_TITLE),
                "messages": normalize_chat_messages(item.get("messages") or []),
                "active_task": item.get("active_task") if isinstance(item.get("active_task"), dict) else None,
                "updated_at": str(item.get("updated_at") or ""),
            }
    return {
        "conversation_id": conversation_id or DEFAULT_CHAT_CONVERSATION_ID,
        "title": DEFAULT_CHAT_CONVERSATION_TITLE,
        "messages": [],
        "active_task": None,
        "updated_at": "",
    }


def build_chat_state(
    messages: list[dict[str, Any]],
    *,
    conversation_id: str = DEFAULT_CHAT_CONVERSATION_ID,
    title: str = DEFAULT_CHAT_CONVERSATION_TITLE,
    active_task: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_messages = normalize_chat_messages(messages)
    updated_at = datetime.now().isoformat(timespec="seconds")
    return {
        "version": CHAT_STATE_VERSION,
        "active_conversation_id": conversation_id,
        "updated_at": updated_at,
        "conversations": [
            {
                "conversation_id": conversation_id,
                "title": title,
                "updated_at": updated_at,
                "messages": normalized_messages,
                "active_task": dict(active_task or {}) if isinstance(active_task, dict) and active_task else None,
            }
        ],
    }
