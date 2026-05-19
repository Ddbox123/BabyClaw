# -*- coding: utf-8 -*-
"""chat session load/save helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from core.ui.chat_state import (
    DEFAULT_CHAT_CONVERSATION_ID,
    DEFAULT_CHAT_CONVERSATION_TITLE,
    build_chat_state,
    get_active_chat_conversation,
    load_chat_state,
    save_chat_state,
)


@dataclass
class ChatSessionState:
    conversation_id: str = DEFAULT_CHAT_CONVERSATION_ID
    title: str = DEFAULT_CHAT_CONVERSATION_TITLE
    messages: List[Dict[str, Any]] = field(default_factory=list)
    updated_at: str = ""


def load_chat_session(project_root: Path) -> ChatSessionState:
    payload = load_chat_state(project_root)
    conversation = get_active_chat_conversation(payload)
    return ChatSessionState(
        conversation_id=str(conversation.get("conversation_id") or DEFAULT_CHAT_CONVERSATION_ID).strip(),
        title=str(conversation.get("title") or DEFAULT_CHAT_CONVERSATION_TITLE).strip(),
        messages=list(conversation.get("messages") or []),
        updated_at=str(conversation.get("updated_at") or "").strip(),
    )


def save_chat_session(project_root: Path, session: ChatSessionState) -> None:
    save_chat_state(
        project_root,
        build_chat_state(
            session.messages,
            conversation_id=session.conversation_id or DEFAULT_CHAT_CONVERSATION_ID,
            title=session.title or DEFAULT_CHAT_CONVERSATION_TITLE,
        ),
    )
