# -*- coding: utf-8 -*-
"""chat task type helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List


CHAT_TASK_KIND_CODING = "coding"
CHAT_TASK_KIND_CONVERSATION = "conversation"

CHAT_TASK_STATUS_IDLE = "idle"
CHAT_TASK_STATUS_PLANNING = "planning"
CHAT_TASK_STATUS_READING = "reading"
CHAT_TASK_STATUS_EDITING = "editing"
CHAT_TASK_STATUS_VERIFYING = "verifying"
CHAT_TASK_STATUS_DONE = "done"
CHAT_TASK_STATUS_BLOCKED = "blocked"
CHAT_TASK_STATUS_NEEDS_INPUT = "needs_input"

VALID_CHAT_TASK_KINDS = {
    CHAT_TASK_KIND_CODING,
    CHAT_TASK_KIND_CONVERSATION,
}

VALID_CHAT_TASK_STATUSES = {
    CHAT_TASK_STATUS_IDLE,
    CHAT_TASK_STATUS_PLANNING,
    CHAT_TASK_STATUS_READING,
    CHAT_TASK_STATUS_EDITING,
    CHAT_TASK_STATUS_VERIFYING,
    CHAT_TASK_STATUS_DONE,
    CHAT_TASK_STATUS_BLOCKED,
    CHAT_TASK_STATUS_NEEDS_INPUT,
}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def normalize_chat_task_kind(value: Any) -> str:
    kind = str(value or CHAT_TASK_KIND_CODING).strip().lower()
    if kind not in VALID_CHAT_TASK_KINDS:
        return CHAT_TASK_KIND_CODING
    return kind


def normalize_chat_task_status(value: Any) -> str:
    status = str(value or CHAT_TASK_STATUS_IDLE).strip().lower()
    if status not in VALID_CHAT_TASK_STATUSES:
        return CHAT_TASK_STATUS_IDLE
    return status


def dedupe_strings(items: Any, *, limit: int = 12) -> List[str]:
    cleaned: List[str] = []
    for item in list(items or []):
        value = str(item or "").strip()
        if not value or value in cleaned:
            continue
        cleaned.append(value)
    if limit > 0:
        return cleaned[-limit:]
    return cleaned


def trim_lines(text: Any, *, max_lines: int = 4) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if not lines:
        return ""
    return "\n".join(lines[:max_lines]).strip()


def status_label(status: str) -> str:
    mapping = {
        CHAT_TASK_STATUS_IDLE: "待命",
        CHAT_TASK_STATUS_PLANNING: "规划中",
        CHAT_TASK_STATUS_READING: "阅读中",
        CHAT_TASK_STATUS_EDITING: "修改中",
        CHAT_TASK_STATUS_VERIFYING: "验证中",
        CHAT_TASK_STATUS_DONE: "已完成",
        CHAT_TASK_STATUS_BLOCKED: "受阻",
        CHAT_TASK_STATUS_NEEDS_INPUT: "待你决定",
    }
    return mapping.get(normalize_chat_task_status(status), "待命")


@dataclass
class ChatTaskSnapshot:
    task_id: str = ""
    kind: str = CHAT_TASK_KIND_CODING
    status: str = CHAT_TASK_STATUS_IDLE
    title: str = ""
    goal: str = ""
    plan: List[str] = field(default_factory=list)
    read_files: List[str] = field(default_factory=list)
    changed_files: List[str] = field(default_factory=list)
    verification_status: str = ""
    verification_summary: str = ""
    latest_summary: str = ""
    next_action: str = ""
    last_user_message: str = ""
    turn_count: int = 0
    resume_count: int = 0
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": str(self.task_id or "").strip(),
            "kind": normalize_chat_task_kind(self.kind),
            "status": normalize_chat_task_status(self.status),
            "title": str(self.title or "").strip(),
            "goal": str(self.goal or "").strip(),
            "plan": dedupe_strings(self.plan, limit=12),
            "read_files": dedupe_strings(self.read_files, limit=12),
            "changed_files": dedupe_strings(self.changed_files, limit=12),
            "verification_status": str(self.verification_status or "").strip().lower(),
            "verification_summary": trim_lines(self.verification_summary, max_lines=4),
            "latest_summary": trim_lines(self.latest_summary, max_lines=6),
            "next_action": trim_lines(self.next_action, max_lines=3),
            "last_user_message": str(self.last_user_message or "").strip(),
            "turn_count": max(0, int(self.turn_count or 0)),
            "resume_count": max(0, int(self.resume_count or 0)),
            "created_at": str(self.created_at or now_iso()).strip(),
            "updated_at": str(self.updated_at or now_iso()).strip(),
            "metadata": dict(self.metadata or {}),
        }
