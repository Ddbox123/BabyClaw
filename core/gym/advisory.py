# -*- coding: utf-8 -*-
"""Read-only advisory baseline helpers for Gym active promotions."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

from core.infrastructure.workspace_manager import get_workspace


@dataclass(frozen=True)
class ActiveAdvisoryBaseline:
    target_key: str
    target_label: str
    proposal_id: str
    episode_id: str
    candidate_improvement_id: str
    activated_at: str
    runtime_effect: str
    agent_consumption: str
    proposal_path: str
    decision_path: str
    trace_index_path: str
    previous_active_proposal_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_active_advisory_baselines(*, project_root: Optional[Path] = None) -> list[ActiveAdvisoryBaseline]:
    root = (project_root or get_workspace().project_root).resolve()
    registry_path = root / "workspace" / "gym" / "active_promotions.json"
    if not registry_path.exists():
        return []
    try:
        payload = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    active = payload.get("active") if isinstance(payload, dict) else None
    if not isinstance(active, dict):
        return []

    baselines: list[ActiveAdvisoryBaseline] = []
    for target_key, raw in active.items():
        if not isinstance(raw, dict):
            continue
        baselines.append(
            ActiveAdvisoryBaseline(
                target_key=str(target_key),
                target_label=_target_label(str(target_key)),
                proposal_id=str(raw.get("proposal_id") or ""),
                episode_id=str(raw.get("episode_id") or ""),
                candidate_improvement_id=str(raw.get("candidate_improvement_id") or ""),
                activated_at=str(raw.get("activated_at") or ""),
                runtime_effect=str(raw.get("runtime_effect") or "not_applied"),
                agent_consumption=str(raw.get("agent_consumption") or "advisory"),
                proposal_path=str(raw.get("proposal_path") or ""),
                decision_path=str(raw.get("decision_path") or ""),
                trace_index_path=str(raw.get("trace_index_path") or ""),
                previous_active_proposal_id=str(raw.get("previous_active_proposal_id") or "") or None,
            )
        )
    baselines.sort(key=lambda item: (item.activated_at, item.target_key), reverse=True)
    return baselines


def build_active_advisory_snapshot(
    *,
    project_root: Optional[Path] = None,
    limit: int | None = None,
) -> dict[str, Any]:
    baselines = load_active_advisory_baselines(project_root=project_root)
    rendered = baselines if limit is None else baselines[: max(0, int(limit))]
    return {
        "active_count": len(baselines),
        "entries": [item.to_dict() for item in rendered],
    }


def summarize_active_advisory_baselines(
    *,
    project_root: Optional[Path] = None,
    limit: int = 3,
) -> list[str]:
    snapshot = build_active_advisory_snapshot(project_root=project_root, limit=limit)
    count = int(snapshot.get("active_count") or 0)
    entries = snapshot.get("entries") if isinstance(snapshot.get("entries"), list) else []
    if count <= 0:
        return ["当前未记住 active advisory baseline"]

    lines = [f"当前记住 {count} 个 active advisory baseline"]
    for item in entries:
        if not isinstance(item, dict):
            continue
        lines.append(
            "- "
            f"{item.get('target_label') or item.get('target_key') or '-'} "
            f"proposal={item.get('proposal_id') or '-'} "
            f"runtime_effect={item.get('runtime_effect') or 'not_applied'} "
            f"agent_consumption={item.get('agent_consumption') or 'advisory'}"
        )
    hidden = count - len(entries)
    if hidden > 0:
        lines.append(f"... 还有 {hidden} 个 active advisory baseline")
    return lines


def _target_label(target_key: str) -> str:
    text = str(target_key or "").strip()
    if not text:
        return "-"
    if text.startswith("target:"):
        raw = text[len("target:") :]
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return text
        if isinstance(payload, dict):
            if payload.get("exercise_id"):
                return str(payload["exercise_id"])
            if payload.get("bundle_name") and payload.get("case_id"):
                return f"{payload['bundle_name']}:{payload['case_id']}"
            if payload.get("kind"):
                return str(payload["kind"])
        return text
    if text.startswith("episode:"):
        parts = text.split(":")
        if len(parts) >= 3:
            return f"{parts[1]}:{parts[2]}"
    return text


__all__ = [
    "ActiveAdvisoryBaseline",
    "build_active_advisory_snapshot",
    "load_active_advisory_baselines",
    "summarize_active_advisory_baselines",
]
