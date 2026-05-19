# -*- coding: utf-8 -*-
"""Chat 候选审核队列。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List


LEGACY_STATUS_MAP = {
    "approved": "positive",
    "rejected": "discard",
    "discarded": "discard",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def normalize_review_status(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return "pending"
    return LEGACY_STATUS_MAP.get(normalized, normalized)


def append_queue_event(queue_path: Path, payload: Dict[str, Any]) -> None:
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    with queue_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def append_review_queue_candidate(candidate_payload: Dict[str, Any], queue_path: Path) -> None:
    append_queue_event(
        queue_path,
        {
            "event": "candidate",
            "timestamp": _now_iso(),
            **candidate_payload,
        },
    )


def append_review_decision(
    candidate_id: str,
    *,
    status: str,
    reviewer_note: str,
    queue_path: Path,
    extra: Dict[str, Any] | None = None,
) -> None:
    append_queue_event(
        queue_path,
        {
            "event": "decision",
            "timestamp": _now_iso(),
            "candidate_id": candidate_id,
            "status": status,
            "reviewer_note": reviewer_note or "",
            **(extra or {}),
        },
    )


def iter_queue_events(queue_path: Path) -> Iterable[Dict[str, Any]]:
    if not queue_path.exists():
        return []
    events: List[Dict[str, Any]] = []
    for line in queue_path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events


def load_review_items(queue_path: Path) -> List[Dict[str, Any]]:
    state: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for event in iter_queue_events(queue_path):
        candidate_id = str(event.get("candidate_id") or "").strip()
        if not candidate_id:
            continue
        if event.get("event") == "candidate":
            candidate = dict(event)
            candidate["status"] = normalize_review_status(candidate.get("status"))
            candidate.setdefault("reviewer_note", "")
            if candidate_id not in state:
                order.append(candidate_id)
            state[candidate_id] = candidate
            continue

        current = state.setdefault(candidate_id, {"candidate_id": candidate_id})
        current["status"] = normalize_review_status(event.get("status") or current.get("status") or "pending")
        current["reviewer_note"] = str(event.get("reviewer_note") or "")
        current["reviewed_at"] = str(event.get("timestamp") or "")
        for key, value in event.items():
            if key not in {"event", "timestamp", "candidate_id", "status", "reviewer_note"}:
                current[key] = value
        if candidate_id not in order:
            order.append(candidate_id)

    items = [state[item_id] for item_id in order if item_id in state]
    items.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)
    return items


def list_review_items(queue_path: Path, *, status: str | None = None) -> List[Dict[str, Any]]:
    items = load_review_items(queue_path)
    if status is None:
        return items
    normalized = normalize_review_status(status)
    return [item for item in items if str(item.get("status") or "").strip().lower() == normalized]


def get_review_item(candidate_id: str, queue_path: Path) -> Dict[str, Any] | None:
    normalized = str(candidate_id or "").strip()
    if not normalized:
        return None
    for item in load_review_items(queue_path):
        if item.get("candidate_id") == normalized:
            return item
    return None


__all__ = [
    "append_queue_event",
    "append_review_decision",
    "append_review_queue_candidate",
    "get_review_item",
    "iter_queue_events",
    "list_review_items",
    "load_review_items",
    "normalize_review_status",
]
