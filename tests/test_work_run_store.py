import json

import pytest

from core.runtime_manager import evolution_store
from core.runtime_manager.work_run_store import WorkRunStore, normalize_run_kind


def test_work_run_store_tracks_active_and_latest_per_kind(tmp_path):
    store = WorkRunStore(root=tmp_path / ".runtime" / "work_runs")
    chat = {"runId": "chat_1", "runKind": "chat_turn", "status": "running"}
    self_run = {"runId": "self_1", "runKind": "self_evolution_run", "status": "running"}

    store.persist_snapshot("chat_turn", chat, active_run_id="chat_1")
    store.persist_snapshot("self_evolution_run", self_run, active_run_id="self_1")

    assert store.load_active_snapshot("chat_turn")["runId"] == "chat_1"
    assert store.load_active_snapshot("self_evolution_run")["runId"] == "self_1"
    assert store.load_latest_snapshot("chat_turn")["status"] == "running"


def test_work_run_store_rejects_unsafe_kind_and_run_id(tmp_path):
    store = WorkRunStore(root=tmp_path / ".runtime" / "work_runs")

    with pytest.raises(ValueError, match="Invalid work run kind"):
        normalize_run_kind("../bad")

    with pytest.raises(ValueError, match="missing runId"):
        store.persist_snapshot("chat_turn", {"status": "running"})

    assert store.load_snapshot("chat_turn", "../bad") is None


def test_evolution_store_delegates_through_legacy_paths(tmp_path, monkeypatch):
    runs_dir = tmp_path / "supervised" / "runs"
    index_path = tmp_path / "supervised" / "index.json"

    def fake_kind_paths(kind: str):
        assert kind == "supervised"
        return runs_dir, index_path

    monkeypatch.setattr(evolution_store, "_kind_paths", fake_kind_paths)

    payload = evolution_store.persist_run_snapshot(
        "supervised",
        {
            "runId": "supervised_1",
            "status": "queued",
            "startedAt": "2026-05-21T00:00:00Z",
            "updatedAt": "2026-05-21T00:00:00Z",
        },
        active_run_id="supervised_1",
    )

    assert payload["runId"] == "supervised_1"
    assert json.loads((runs_dir / "supervised_1.json").read_text(encoding="utf-8"))["status"] == "queued"
    assert evolution_store.load_active_run_snapshot("supervised")["runId"] == "supervised_1"
    assert evolution_store.load_latest_run_snapshot("supervised")["runId"] == "supervised_1"
