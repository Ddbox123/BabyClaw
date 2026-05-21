"""Persistent run snapshot storage for manager-owned evolution work."""

from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .constants import RUNTIME_MANAGER_DIR
from .work_run_store import WorkRunStore, normalize_run_id


EVOLUTION_DIR = RUNTIME_MANAGER_DIR / "evolution"
SELF_RUNS_DIR = EVOLUTION_DIR / "self" / "runs"
SUPERVISED_RUNS_DIR = EVOLUTION_DIR / "supervised" / "runs"
SELF_INDEX_PATH = EVOLUTION_DIR / "self" / "index.json"
SUPERVISED_INDEX_PATH = EVOLUTION_DIR / "supervised" / "index.json"
WRITE_RETRY_TIMEOUT_SECONDS = 5.0
READ_RETRY_ATTEMPTS = 5
READ_RETRY_DELAY_SECONDS = 0.05


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def ensure_evolution_store_dirs() -> None:
    for path in (
        EVOLUTION_DIR,
        SELF_RUNS_DIR.parent,
        SELF_RUNS_DIR,
        SUPERVISED_RUNS_DIR.parent,
        SUPERVISED_RUNS_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    ensure_evolution_store_dirs()
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


def _kind_paths(kind: str) -> tuple[Path, Path]:
    normalized = str(kind or "").strip().lower()
    if normalized == "self":
        return SELF_RUNS_DIR, SELF_INDEX_PATH
    if normalized == "supervised":
        return SUPERVISED_RUNS_DIR, SUPERVISED_INDEX_PATH
    raise ValueError(f"Unsupported evolution store kind: {kind}")


class _LegacyEvolutionWorkRunStore(WorkRunStore):
    def runs_dir(self, run_kind: str) -> Path:
        runs_dir, _ = _kind_paths(_legacy_kind(run_kind))
        return runs_dir

    def index_path(self, run_kind: str) -> Path:
        _, index_path = _kind_paths(_legacy_kind(run_kind))
        return index_path

    def ensure_kind_dirs(self, run_kind: str) -> None:
        ensure_evolution_store_dirs()


def _legacy_kind(kind: str) -> str:
    normalized = str(kind or "").strip().lower()
    if normalized == "self_evolution_run":
        return "self"
    if normalized == "supervised_evolution_run":
        return "supervised"
    if normalized in {"self", "supervised"}:
        return normalized
    raise ValueError(f"Unsupported evolution store kind: {kind}")


def _legacy_store() -> WorkRunStore:
    return _LegacyEvolutionWorkRunStore(root=EVOLUTION_DIR)


def _normalize_run_id(run_id: str) -> str:
    try:
        return normalize_run_id(run_id)
    except ValueError as exc:
        raise ValueError("Invalid evolution run id.") from exc


def _default_index() -> dict[str, Any]:
    now = _now_iso()
    return {
        "version": 1,
        "updatedAt": now,
        "activeRunId": "",
        "latestRunId": "",
    }


def load_run_index(kind: str) -> dict[str, Any]:
    return _legacy_store().load_run_index(kind)


def save_run_index(kind: str, *, active_run_id: str = "", latest_run_id: str = "") -> dict[str, Any]:
    return _legacy_store().save_run_index(kind, active_run_id=active_run_id, latest_run_id=latest_run_id)


def persist_run_snapshot(kind: str, snapshot: dict[str, Any], *, active_run_id: str = "") -> dict[str, Any]:
    try:
        run_id = _normalize_run_id(str(snapshot.get("runId") or ""))
    except ValueError as exc:
        raise ValueError("Run snapshot is missing runId.") from exc
    return _legacy_store().persist_snapshot(kind, snapshot, active_run_id=active_run_id)


def load_run_snapshot(kind: str, run_id: str) -> dict[str, Any] | None:
    try:
        _normalize_run_id(run_id)
    except ValueError:
        return None
    return _legacy_store().load_snapshot(kind, run_id)


def _run_sort_key(payload: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(payload.get("updatedAt") or ""),
        str(payload.get("startedAt") or ""),
        str(payload.get("runId") or ""),
    )


def delete_run_snapshot(kind: str, run_id: str) -> dict[str, Any]:
    return _legacy_store().delete_snapshot(kind, run_id)


def load_active_run_snapshot(kind: str) -> dict[str, Any] | None:
    return _legacy_store().load_active_snapshot(kind)


def load_latest_run_snapshot(kind: str) -> dict[str, Any] | None:
    return _legacy_store().load_latest_snapshot(kind)


def build_evolution_summary() -> dict[str, Any]:
    self_active = load_active_run_snapshot("self")
    self_latest = load_latest_run_snapshot("self")
    supervised_active = load_active_run_snapshot("supervised")
    supervised_latest = load_latest_run_snapshot("supervised")
    return {
        "self": {
            "activeRunId": str((self_active or {}).get("runId") or ""),
            "activeStatus": str((self_active or {}).get("status") or ""),
            "latestRunId": str((self_latest or {}).get("runId") or ""),
            "latestStatus": str((self_latest or {}).get("status") or ""),
        },
        "supervised": {
            "activeRunId": str((supervised_active or {}).get("runId") or ""),
            "activeStatus": str((supervised_active or {}).get("status") or ""),
            "latestRunId": str((supervised_latest or {}).get("runId") or ""),
            "latestStatus": str((supervised_latest or {}).get("status") or ""),
        },
    }


def clear_evolution_store() -> None:
    for path in (
        SELF_INDEX_PATH,
        SUPERVISED_INDEX_PATH,
        *SELF_RUNS_DIR.glob("*.json"),
        *SUPERVISED_RUNS_DIR.glob("*.json"),
    ):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            continue
