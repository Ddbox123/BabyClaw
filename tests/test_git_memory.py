#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from core.infrastructure.agent_session import get_session_state
from core.infrastructure.event_bus import EventNames
from core.infrastructure.git_memory import GitMemoryService
from tools.git_tools import (
    get_git_status_summary_tool,
    open_evolution_transaction_tool,
    close_evolution_transaction_tool,
)


class FakeWorkspace:
    def __init__(self, project_root: Path, db_path: Path):
        self.project_root = project_root
        self._db_path = db_path

    @contextmanager
    def get_db_connection(self):
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def _run(cmd: str, cwd: Path) -> None:
    import subprocess

    subprocess.run(cmd, cwd=str(cwd), shell=True, check=True, capture_output=True, text=True)


def _init_git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run("git init", repo)
    _run('git config user.email "tests@example.com"', repo)
    _run('git config user.name "Tests"', repo)
    (repo / "sample.py").write_text(
        "def alpha():\n    return 1\n\n\nclass Beta:\n    def gamma(self):\n        return 2\n",
        encoding="utf-8",
    )
    _run("git add sample.py", repo)
    _run('git commit -m "initial commit"', repo)
    return repo


class TestGitMemoryService:
    def test_refresh_indexes_commits_and_worktree(self, tmp_path, monkeypatch):
        repo = _init_git_repo(tmp_path)
        db_path = tmp_path / "brain.db"
        fake_workspace = FakeWorkspace(repo, db_path)

        published = []

        class FakeBus:
            def publish(self, name, data=None, source=None):
                published.append((name, data, source))

        monkeypatch.setattr("core.infrastructure.git_memory.get_workspace", lambda: fake_workspace)
        monkeypatch.setattr("core.infrastructure.git_memory.get_event_bus", lambda: FakeBus())

        service = GitMemoryService()
        state = service.refresh_git_memory(force=True)

        assert state.available is True
        changes = service.get_recent_project_changes(limit=5)
        assert changes
        assert any(change.path == "sample.py" for change in changes)
        assert any(event[0] == EventNames.GIT_INDEX_UPDATED for event in published)

    def test_note_file_modified_tracks_entities(self, tmp_path, monkeypatch):
        repo = _init_git_repo(tmp_path)
        db_path = tmp_path / "brain.db"
        fake_workspace = FakeWorkspace(repo, db_path)

        class FakeBus:
            def publish(self, name, data=None, source=None):
                return None

        monkeypatch.setattr("core.infrastructure.git_memory.get_workspace", lambda: fake_workspace)
        monkeypatch.setattr("core.infrastructure.git_memory.get_event_bus", lambda: FakeBus())

        service = GitMemoryService()
        service.note_file_modified("sample.py")
        attention = get_session_state().get_attention_snapshot()

        assert "sample.py" in attention["modified_paths"]
        assert "alpha" in attention["modified_entities"]
        assert "Beta.gamma" in attention["modified_entities"]

    def test_open_and_close_evolution_transaction_tools(self, tmp_path, monkeypatch):
        repo = _init_git_repo(tmp_path)
        db_path = tmp_path / "brain.db"
        fake_workspace = FakeWorkspace(repo, db_path)

        class FakeBus:
            def publish(self, name, data=None, source=None):
                return None

        monkeypatch.setattr("core.infrastructure.git_memory.get_workspace", lambda: fake_workspace)
        monkeypatch.setattr("core.infrastructure.git_memory.get_event_bus", lambda: FakeBus())

        service = GitMemoryService()
        monkeypatch.setattr("tools.git_tools.get_git_memory_service", lambda: service)

        opened = open_evolution_transaction_tool("touch core loop")
        assert "txn_id" in opened
        import json
        txn_id = json.loads(opened)["txn_id"]

        closed = close_evolution_transaction_tool(txn_id=txn_id, status="failed", summary="test failed")
        payload = json.loads(closed)
        assert payload["transaction_status"] == "failed"

    def test_validation_event_syncs_attention_cache(self, tmp_path, monkeypatch):
        repo = _init_git_repo(tmp_path)
        db_path = tmp_path / "brain.db"
        fake_workspace = FakeWorkspace(repo, db_path)

        class FakeBus:
            def __init__(self):
                self.handlers = {}

            def publish(self, name, data=None, source=None):
                for handler in self.handlers.get(name, []):
                    handler(type("Evt", (), {"data": data or {}, "source": source})())

            def subscribe(self, name, handler, priority=0):
                self.handlers.setdefault(name, []).append(handler)
                return True

        fake_bus = FakeBus()
        monkeypatch.setattr("core.infrastructure.git_memory.get_workspace", lambda: fake_workspace)
        monkeypatch.setattr("core.infrastructure.git_memory.get_event_bus", lambda: fake_bus)

        service = GitMemoryService()
        session = get_session_state()
        session.record_validation_result("Environment smoke passed", True)

        fake_bus.publish(
            EventNames.VALIDATION_COMPLETED,
            {"kind": "environment", "passed": True, "message": "Environment smoke passed"},
            source="test",
        )

        with fake_workspace.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT last_validation_summary FROM GitAttentionCache WHERE session_id = ?", ("default",))
            row = cursor.fetchone()

        assert row is not None
        assert row["last_validation_summary"] == "Environment smoke passed"

    def test_get_git_status_summary_tool_accepts_string_limit(self, tmp_path, monkeypatch):
        repo = _init_git_repo(tmp_path)
        db_path = tmp_path / "brain.db"
        fake_workspace = FakeWorkspace(repo, db_path)

        class FakeBus:
            def publish(self, name, data=None, source=None):
                return None

            def subscribe(self, name, handler, priority=0):
                return True

        monkeypatch.setattr("core.infrastructure.git_memory.get_workspace", lambda: fake_workspace)
        monkeypatch.setattr("core.infrastructure.git_memory.get_event_bus", lambda: FakeBus())

        service = GitMemoryService()
        service.refresh_git_memory(force=True)
        monkeypatch.setattr("tools.git_tools.get_git_memory_service", lambda: service)

        import json

        payload = json.loads(get_git_status_summary_tool(limit="5"))
        assert payload["dirty_summary"] == "工作区干净"
        assert isinstance(payload["recent_changes"], list)
        assert len(payload["recent_changes"]) <= 5
        assert payload["recent_changes"][0]["path"] == "sample.py"

    def test_clean_refresh_clears_stale_attention_but_keeps_validation(self, tmp_path, monkeypatch):
        repo = _init_git_repo(tmp_path)
        db_path = tmp_path / "brain.db"
        fake_workspace = FakeWorkspace(repo, db_path)

        class FakeBus:
            def publish(self, name, data=None, source=None):
                return None

            def subscribe(self, name, handler, priority=0):
                return True

        monkeypatch.setattr("core.infrastructure.git_memory.get_workspace", lambda: fake_workspace)
        monkeypatch.setattr("core.infrastructure.git_memory.get_event_bus", lambda: FakeBus())

        service = GitMemoryService()
        session = get_session_state()
        session.record_modified_path("sample.py")
        session.record_modified_entities("sample.py", ["alpha"])
        session.record_validation_result("All tests passed", True)

        state = service.refresh_git_memory(force=True)
        attention = session.get_attention_snapshot()

        assert state.dirty is False
        assert attention["modified_paths"] == []
        assert attention["modified_entities"] == []
        assert attention["last_validation_summary"] == "All tests passed"

    def test_note_file_modified_tracks_risky_path_without_opening_txn(self, tmp_path, monkeypatch):
        repo = _init_git_repo(tmp_path)
        db_path = tmp_path / "brain.db"
        fake_workspace = FakeWorkspace(repo, db_path)

        class FakeBus:
            def __init__(self):
                self.handlers = {}

            def publish(self, name, data=None, source=None):
                for handler in self.handlers.get(name, []):
                    handler(type("Evt", (), {"data": data or {}, "source": source})())

            def subscribe(self, name, handler, priority=0):
                self.handlers.setdefault(name, []).append(handler)
                return True

        fake_bus = FakeBus()
        monkeypatch.setattr("core.infrastructure.git_memory.get_workspace", lambda: fake_workspace)
        monkeypatch.setattr("core.infrastructure.git_memory.get_event_bus", lambda: fake_bus)

        service = GitMemoryService()
        session = get_session_state()

        service.note_file_modified("core/example.py")

        assert session.get_active_evolution_txn() is None

        fake_bus.publish(
            EventNames.VALIDATION_COMPLETED,
            {"kind": "tests", "passed": True, "message": "All tests passed"},
            source="test",
        )

        assert session.get_active_evolution_txn() is None

        with fake_workspace.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) AS count FROM EvolutionTransaction")
            row = cursor.fetchone()

        assert row is not None
        assert row["count"] == 0
