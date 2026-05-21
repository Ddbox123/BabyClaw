"""Shared persistent snapshot storage for manager-owned work runs."""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from .constants import RUNTIME_MANAGER_DIR


WORK_RUNS_DIR = RUNTIME_MANAGER_DIR / "work_runs"
WRITE_RETRY_TIMEOUT_SECONDS = 5.0
READ_RETRY_ATTEMPTS = 5
READ_RETRY_DELAY_SECONDS = 0.05
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def normalize_run_kind(kind: str) -> str:
    normalized = str(kind or "").strip().lower()
    if not normalized or not _SAFE_NAME_RE.fullmatch(normalized):
        raise ValueError("Invalid work run kind.")
    if "/" in normalized or "\\" in normalized or normalized in {".", ".."}:
        raise ValueError("Invalid work run kind.")
    return normalized


def normalize_run_id(run_id: str) -> str:
    normalized = str(run_id or "").strip()
    if not normalized or "/" in normalized or "\\" in normalized or normalized in {".", ".."}:
        raise ValueError("Invalid work run id.")
    return normalized


def _default_index() -> dict[str, Any]:
    now = _now_iso()
    return {
        "version": 1,
        "updatedAt": now,
        "activeRunId": "",
        "latestRunId": "",
    }


def _read_text_with_retry(path: Path) -> str:
    for attempt in range(READ_RETRY_ATTEMPTS):
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            if attempt + 1 >= READ_RETRY_ATTEMPTS:
                raise
            time.sleep(READ_RETRY_DELAY_SECONDS)
    raise OSError(f"Unable to read {path}")


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    for attempt in range(READ_RETRY_ATTEMPTS):
        try:
            payload = json.loads(_read_text_with_retry(path))
        except (OSError, json.JSONDecodeError):
            if attempt + 1 >= READ_RETRY_ATTEMPTS:
                return {}
            time.sleep(READ_RETRY_DELAY_SECONDS)
            continue
        return payload if isinstance(payload, dict) else {}
    return {}


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        deadline = time.monotonic() + WRITE_RETRY_TIMEOUT_SECONDS
        attempt = 0
        while True:
            try:
                os.replace(temp_path, path)
                break
            except PermissionError:
                attempt += 1
                if time.monotonic() >= deadline:
                    raise
                time.sleep(min(0.05 * attempt, 0.25))
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def _run_sort_key(payload: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(payload.get("updatedAt") or ""),
        str(payload.get("startedAt") or ""),
        str(payload.get("runId") or ""),
    )


@dataclass(frozen=True)
class WorkRunStore:
    root: Path = WORK_RUNS_DIR

    def kind_dir(self, run_kind: str) -> Path:
        return self.root / normalize_run_kind(run_kind)

    def runs_dir(self, run_kind: str) -> Path:
        return self.kind_dir(run_kind) / "runs"

    def index_path(self, run_kind: str) -> Path:
        return self.kind_dir(run_kind) / "index.json"

    def ensure_kind_dirs(self, run_kind: str) -> None:
        self.runs_dir(run_kind).mkdir(parents=True, exist_ok=True)

    def load_run_index(self, run_kind: str) -> dict[str, Any]:
        payload = _load_json(self.index_path(run_kind))
        if not payload:
            return _default_index()
        default = _default_index()
        default.update(payload)
        return default

    def save_run_index(self, run_kind: str, *, active_run_id: str = "", latest_run_id: str = "") -> dict[str, Any]:
        payload = self.load_run_index(run_kind)
        payload.update(
            {
                "updatedAt": _now_iso(),
                "activeRunId": str(active_run_id or "").strip(),
                "latestRunId": str(latest_run_id or "").strip(),
            }
        )
        self.ensure_kind_dirs(run_kind)
        _atomic_write_json(self.index_path(run_kind), payload)
        return payload

    def persist_snapshot(self, run_kind: str, snapshot: dict[str, Any], *, active_run_id: str = "") -> dict[str, Any]:
        try:
            run_id = normalize_run_id(str(snapshot.get("runId") or ""))
        except ValueError as exc:
            raise ValueError("Work run snapshot is missing runId.") from exc
        payload = json.loads(json.dumps(snapshot, ensure_ascii=False))
        self.ensure_kind_dirs(run_kind)
        _atomic_write_json(self.runs_dir(run_kind) / f"{run_id}.json", payload)
        self.save_run_index(run_kind, active_run_id=active_run_id, latest_run_id=run_id)
        return payload

    def load_snapshot(self, run_kind: str, run_id: str) -> dict[str, Any] | None:
        try:
            normalized = normalize_run_id(run_id)
        except ValueError:
            return None
        payload = _load_json(self.runs_dir(run_kind) / f"{normalized}.json")
        return payload or None

    def load_active_snapshot(self, run_kind: str) -> dict[str, Any] | None:
        active_run_id = str(self.load_run_index(run_kind).get("activeRunId") or "").strip()
        if not active_run_id:
            return None
        return self.load_snapshot(run_kind, active_run_id)

    def load_latest_snapshot(self, run_kind: str) -> dict[str, Any] | None:
        latest_run_id = str(self.load_run_index(run_kind).get("latestRunId") or "").strip()
        if latest_run_id:
            payload = self.load_snapshot(run_kind, latest_run_id)
            if payload is not None:
                return payload

        candidates: list[dict[str, Any]] = []
        for path in sorted(self.runs_dir(run_kind).glob("*.json")):
            payload = _load_json(path)
            if payload:
                candidates.append(payload)
        if not candidates:
            return None
        return max(candidates, key=_run_sort_key)

    def delete_snapshot(self, run_kind: str, run_id: str) -> dict[str, Any]:
        normalized = normalize_run_id(run_id)
        runs_dir = self.runs_dir(run_kind)
        target = runs_dir / f"{normalized}.json"
        index = self.load_run_index(run_kind)
        active_run_id = str(index.get("activeRunId") or "").strip()
        latest_run_id = str(index.get("latestRunId") or "").strip()
        existed = target.exists()

        try:
            target.unlink(missing_ok=True)
        except OSError:
            if target.exists():
                raise

        cleared_active = active_run_id == normalized
        cleared_latest = latest_run_id == normalized
        next_active_id = "" if cleared_active else active_run_id
        next_latest_id = latest_run_id

        if cleared_latest:
            candidates: list[dict[str, Any]] = []
            for path in sorted(runs_dir.glob("*.json")):
                if path.name == target.name:
                    continue
                payload = _load_json(path)
                if payload:
                    candidates.append(payload)
            next_latest_id = str(max(candidates, key=_run_sort_key).get("runId") or "") if candidates else ""

        if existed or cleared_active or cleared_latest:
            self.save_run_index(run_kind, active_run_id=next_active_id, latest_run_id=next_latest_id)

        return {
            "deleted": existed,
            "runId": normalized,
            "clearedActive": cleared_active,
            "clearedLatest": cleared_latest,
            "activeRunId": next_active_id,
            "latestRunId": next_latest_id,
        }

    def clear(self, run_kinds: Iterable[str] | None = None) -> None:
        if run_kinds is None:
            if not self.root.exists():
                return
            run_kinds = [path.name for path in self.root.iterdir() if path.is_dir()]
        for run_kind in run_kinds:
            index_path = self.index_path(run_kind)
            paths = [index_path, *self.runs_dir(run_kind).glob("*.json")]
            for path in paths:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    continue


def build_work_run_summary(store: WorkRunStore | None = None, kinds: Iterable[str] | None = None) -> dict[str, Any]:
    current_store = store or WorkRunStore()
    selected_kinds = list(kinds or [])
    if not selected_kinds and current_store.root.exists():
        selected_kinds = [path.name for path in sorted(current_store.root.iterdir()) if path.is_dir()]
    return {
        normalize_run_kind(kind): {
            "active": current_store.load_active_snapshot(kind),
            "latest": current_store.load_latest_snapshot(kind),
        }
        for kind in selected_kinds
    }
