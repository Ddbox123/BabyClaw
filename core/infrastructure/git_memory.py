from __future__ import annotations

import json
import subprocess
import threading
import uuid
import ast
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.infrastructure.agent_session import get_session_state
from core.infrastructure.event_bus import EventNames, get_event_bus
from core.infrastructure.workspace_manager import get_workspace
from core.logging import debug_logger


_RISKY_EVOLUTION_PATH_PREFIXES = ("core/", "tools/", "config/", "workspace/prompts/")
_RISKY_EVOLUTION_PATHS = {"agent.py"}


def _is_risky_evolution_path(filepath: str) -> bool:
    normalized = filepath.replace("\\", "/").lstrip("./")
    return normalized in _RISKY_EVOLUTION_PATHS or normalized.startswith(_RISKY_EVOLUTION_PATH_PREFIXES)


def _utcnow_iso() -> str:
    return datetime.now().isoformat()


def _short_subject(subject: Optional[str]) -> Optional[str]:
    if not subject:
        return subject
    normalized = subject.replace("\\n", "\n")
    first_line = normalized.splitlines()[0].strip()
    return first_line or subject.strip()


@dataclass
class WorkingTreeFile:
    path: str
    status: str
    staged: bool = False
    unstaged: bool = False
    untracked: bool = False
    deleted: bool = False
    old_path: Optional[str] = None


@dataclass
class WorkingTreeSnapshot:
    snapshot_id: str
    created_at: str
    base_rev: Optional[str]
    has_staged: bool
    has_unstaged: bool
    has_untracked: bool
    files: List[WorkingTreeFile]
    available: bool = True
    error: Optional[str] = None


@dataclass
class ChangeRecord:
    kind: str
    path: str
    summary: str
    commit_sha: Optional[str] = None
    entity_refs: Optional[List[str]] = None
    change_type: Optional[str] = None
    old_path: Optional[str] = None
    subject: Optional[str] = None


@dataclass
class AttentionContext:
    modified_paths: List[str]
    modified_entities: List[str]
    dirty_summary: str
    last_validation_summary: Optional[str]
    recent_changes: List[ChangeRecord]


@dataclass
class GitMemoryState:
    available: bool
    head_rev: Optional[str]
    indexed_head_rev: Optional[str]
    dirty: bool
    snapshot_id: Optional[str]
    refreshed_at: str
    error: Optional[str] = None


class GitMemoryService:
    def __init__(self) -> None:
        self._workspace = get_workspace()
        self._project_root = self._workspace.project_root
        self._bus = get_event_bus()
        self._lock = threading.Lock()
        self._last_snapshot: Optional[WorkingTreeSnapshot] = None
        self._last_state = GitMemoryState(
            available=False,
            head_rev=None,
            indexed_head_rev=None,
            dirty=False,
            snapshot_id=None,
            refreshed_at=_utcnow_iso(),
            error="not_initialized",
        )
        self._ensure_tables()
        self._subscribe_events()

    def _subscribe_events(self) -> None:
        """订阅关键运行时事件，保持 Git attention 缓存新鲜。"""
        try:
            self._bus.subscribe(EventNames.VALIDATION_COMPLETED, self._on_validation_completed)
        except Exception:
            pass

    def _on_validation_completed(self, event: Any) -> None:
        """验证完成后同步 attention cache，写入最近验证摘要。"""
        try:
            self._sync_attention_cache()
        except Exception:
            pass

    def _ensure_tables(self) -> None:
        with self._workspace.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS GitCommit (
                    commit_sha TEXT PRIMARY KEY,
                    parent_sha TEXT,
                    author_time TEXT,
                    subject TEXT,
                    indexed_at TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS GitFileChange (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    commit_sha TEXT NOT NULL,
                    path TEXT NOT NULL,
                    change_type TEXT NOT NULL,
                    old_path TEXT,
                    is_worktree INTEGER NOT NULL DEFAULT 0,
                    summary TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(commit_sha, path, change_type, old_path, is_worktree)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS GitEntityChange (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    commit_sha TEXT NOT NULL,
                    path TEXT NOT NULL,
                    entity_ref TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    change_type TEXT NOT NULL,
                    is_worktree INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    UNIQUE(commit_sha, path, entity_ref, change_type, is_worktree)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS GitWorkingTreeSnapshot (
                    snapshot_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    base_rev TEXT,
                    has_staged INTEGER NOT NULL DEFAULT 0,
                    has_unstaged INTEGER NOT NULL DEFAULT 0,
                    has_untracked INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS GitAttentionCache (
                    session_id TEXT PRIMARY KEY,
                    updated_at TEXT NOT NULL,
                    modified_paths_json TEXT NOT NULL,
                    modified_entities_json TEXT NOT NULL,
                    dirty_summary TEXT,
                    last_validation_summary TEXT
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS EvolutionTransaction (
                    txn_id TEXT PRIMARY KEY,
                    opened_at TEXT NOT NULL,
                    closed_at TEXT,
                    base_rev TEXT,
                    status TEXT NOT NULL,
                    summary TEXT
                )
                """
            )
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_git_file_change_commit ON GitFileChange(commit_sha)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_git_entity_change_commit ON GitEntityChange(commit_sha)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_git_entity_change_ref ON GitEntityChange(entity_ref)")

    def _run_git(self, args: List[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=str(self._project_root),
            capture_output=True,
            text=True,
            timeout=20,
        )

    def is_git_available(self) -> tuple[bool, Optional[str]]:
        try:
            result = self._run_git(["rev-parse", "--git-dir"])
        except Exception as exc:
            return False, str(exc)
        if result.returncode != 0:
            return False, (result.stderr or result.stdout or "git unavailable").strip()
        return True, None

    def _git_head_rev(self) -> Optional[str]:
        result = self._run_git(["rev-parse", "HEAD"])
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None

    def _get_last_indexed_commit(self) -> Optional[str]:
        with self._workspace.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT commit_sha FROM GitCommit ORDER BY author_time DESC, indexed_at DESC LIMIT 1"
            )
            row = cursor.fetchone()
            return row["commit_sha"] if row else None

    def _list_commits_to_index(self, base_rev: Optional[str]) -> List[str]:
        if base_rev:
            result = self._run_git(["rev-list", "--reverse", f"{base_rev}..HEAD"])
        else:
            result = self._run_git(["rev-list", "--reverse", "--max-count", "20", "HEAD"])
        if result.returncode != 0:
            return []
        commits = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if base_rev and base_rev in commits:
            commits = [c for c in commits if c != base_rev]
        return commits

    def _commit_meta(self, commit_sha: str) -> Dict[str, Optional[str]]:
        result = self._run_git(["show", "-s", "--format=%H%x1f%P%x1f%cI%x1f%s", commit_sha])
        if result.returncode != 0:
            return {"commit_sha": commit_sha, "parent_sha": None, "author_time": None, "subject": None}
        parts = result.stdout.strip().split("\x1f")
        parent_sha = parts[1].split()[0] if len(parts) > 1 and parts[1].strip() else None
        return {
            "commit_sha": parts[0] if parts else commit_sha,
            "parent_sha": parent_sha,
            "author_time": parts[2] if len(parts) > 2 else None,
            "subject": parts[3] if len(parts) > 3 else None,
        }

    def _parse_name_status(self, output: str) -> List[Dict[str, Optional[str]]]:
        changes: List[Dict[str, Optional[str]]] = []
        for raw in output.splitlines():
            line = raw.strip()
            if not line:
                continue
            parts = line.split("\t")
            if not parts:
                continue
            status = parts[0]
            change_type = status[0]
            if change_type == "R" and len(parts) >= 3:
                changes.append(
                    {
                        "change_type": "renamed",
                        "old_path": parts[1],
                        "path": parts[2],
                    }
                )
            else:
                changes.append(
                    {
                        "change_type": {
                            "A": "added",
                            "D": "deleted",
                            "M": "modified",
                            "T": "type_changed",
                        }.get(change_type, "modified"),
                        "old_path": None,
                        "path": parts[-1],
                    }
                )
        return changes

    def _entity_refs_for_path(self, rel_path: str) -> List[Dict[str, str]]:
        if not rel_path.endswith(".py"):
            return []
        path = self._project_root / rel_path
        if not path.exists():
            return []
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except Exception:
            return []
        entities: Dict[str, List[Dict[str, Any]]] = {"class": [], "function": [], "async_function": []}
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                methods = []
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        methods.append({"name": item.name})
                entities["class"].append({"name": node.name, "methods": methods})
            elif isinstance(node, ast.FunctionDef):
                entities["function"].append({"name": node.name})
            elif isinstance(node, ast.AsyncFunctionDef):
                entities["async_function"].append({"name": node.name})
        refs: List[Dict[str, str]] = []
        for cls in entities.get("class", []):
            refs.append({"entity_ref": cls["name"], "entity_type": "class"})
            for method in cls.get("methods", []):
                refs.append(
                    {
                        "entity_ref": f"{cls['name']}.{method['name']}",
                        "entity_type": "method",
                    }
                )
        for fn in entities.get("function", []):
            refs.append({"entity_ref": fn["name"], "entity_type": "function"})
        for fn in entities.get("async_function", []):
            refs.append({"entity_ref": fn["name"], "entity_type": "async_function"})
        return refs

    def _store_commit_changes(self, commit_sha: str, changes: List[Dict[str, Optional[str]]], subject: Optional[str]) -> None:
        now = _utcnow_iso()
        with self._workspace.get_db_connection() as conn:
            cursor = conn.cursor()
            meta = self._commit_meta(commit_sha)
            cursor.execute(
                """
                INSERT OR IGNORE INTO GitCommit(commit_sha, parent_sha, author_time, subject, indexed_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (meta["commit_sha"], meta["parent_sha"], meta["author_time"], meta["subject"], now),
            )
            for change in changes:
                path = change["path"]
                change_type = change["change_type"]
                old_path = change.get("old_path")
                summary = f"{change_type}: {path}"
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO GitFileChange(commit_sha, path, change_type, old_path, is_worktree, summary, created_at)
                    VALUES (?, ?, ?, ?, 0, ?, ?)
                    """,
                    (commit_sha, path, change_type, old_path, summary, now),
                )
                for entity in self._entity_refs_for_path(path):
                    cursor.execute(
                        """
                        INSERT OR IGNORE INTO GitEntityChange(commit_sha, path, entity_ref, entity_type, change_type, is_worktree, created_at)
                        VALUES (?, ?, ?, ?, ?, 0, ?)
                        """,
                        (
                            commit_sha,
                            path,
                            entity["entity_ref"],
                            entity["entity_type"],
                            change_type,
                            now,
                        ),
                    )

    def index_recent_changes(self, base_rev: Optional[str] = None) -> Dict[str, Any]:
        available, error = self.is_git_available()
        if not available:
            return {"available": False, "indexed_commits": [], "error": error}

        last_indexed = base_rev or self._get_last_indexed_commit()
        commits = self._list_commits_to_index(last_indexed)
        indexed: List[str] = []
        for commit_sha in commits:
            diff_result = self._run_git(["show", "--format=", "--name-status", commit_sha])
            if diff_result.returncode != 0:
                continue
            changes = self._parse_name_status(diff_result.stdout)
            meta = self._commit_meta(commit_sha)
            self._store_commit_changes(commit_sha, changes, meta.get("subject"))
            indexed.append(commit_sha)
        return {"available": True, "indexed_commits": indexed, "error": None}

    def scan_working_tree(self, store: bool = True) -> WorkingTreeSnapshot:
        available, error = self.is_git_available()
        if not available:
            return WorkingTreeSnapshot(
                snapshot_id="unavailable",
                created_at=_utcnow_iso(),
                base_rev=None,
                has_staged=False,
                has_unstaged=False,
                has_untracked=False,
                files=[],
                available=False,
                error=error,
            )

        result = self._run_git(["status", "--porcelain=1"])
        if result.returncode != 0:
            return WorkingTreeSnapshot(
                snapshot_id="error",
                created_at=_utcnow_iso(),
                base_rev=self._git_head_rev(),
                has_staged=False,
                has_unstaged=False,
                has_untracked=False,
                files=[],
                available=False,
                error=(result.stderr or result.stdout).strip(),
            )

        files: List[WorkingTreeFile] = []
        has_staged = False
        has_unstaged = False
        has_untracked = False
        for raw in result.stdout.splitlines():
            if len(raw) < 3:
                continue
            x = raw[0]
            y = raw[1]
            payload = raw[3:]
            old_path = None
            path = payload
            if " -> " in payload:
                old_path, path = payload.split(" -> ", 1)
            staged = x not in (" ", "?")
            unstaged = y not in (" ", "?")
            untracked = x == "?" and y == "?"
            deleted = x == "D" or y == "D"
            has_staged = has_staged or staged
            has_unstaged = has_unstaged or unstaged
            has_untracked = has_untracked or untracked
            files.append(
                WorkingTreeFile(
                    path=path,
                    status=f"{x}{y}",
                    staged=staged,
                    unstaged=unstaged,
                    untracked=untracked,
                    deleted=deleted,
                    old_path=old_path,
                )
            )
        snapshot = WorkingTreeSnapshot(
            snapshot_id=f"wt-{uuid.uuid4().hex[:12]}",
            created_at=_utcnow_iso(),
            base_rev=self._git_head_rev(),
            has_staged=has_staged,
            has_unstaged=has_unstaged,
            has_untracked=has_untracked,
            files=files,
            available=True,
            error=None,
        )
        if store:
            self._store_worktree_snapshot(snapshot)
            self._last_snapshot = snapshot
        return snapshot

    def _store_worktree_snapshot(self, snapshot: WorkingTreeSnapshot) -> None:
        now = _utcnow_iso()
        with self._workspace.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO GitWorkingTreeSnapshot(
                    snapshot_id, created_at, base_rev, has_staged, has_unstaged, has_untracked
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.snapshot_id,
                    snapshot.created_at,
                    snapshot.base_rev,
                    int(snapshot.has_staged),
                    int(snapshot.has_unstaged),
                    int(snapshot.has_untracked),
                ),
            )
            for wf in snapshot.files:
                change_type = "deleted" if wf.deleted else ("untracked" if wf.untracked else "modified")
                summary = f"{change_type}: {wf.path}"
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO GitFileChange(commit_sha, path, change_type, old_path, is_worktree, summary, created_at)
                    VALUES (?, ?, ?, ?, 1, ?, ?)
                    """,
                    (snapshot.snapshot_id, wf.path, change_type, wf.old_path, summary, now),
                )
                for entity in self._entity_refs_for_path(wf.path):
                    cursor.execute(
                        """
                        INSERT OR IGNORE INTO GitEntityChange(commit_sha, path, entity_ref, entity_type, change_type, is_worktree, created_at)
                        VALUES (?, ?, ?, ?, ?, 1, ?)
                        """,
                        (
                            snapshot.snapshot_id,
                            wf.path,
                            entity["entity_ref"],
                            entity["entity_type"],
                            change_type,
                            now,
                        ),
                    )

    def _dirty_summary(self, snapshot: WorkingTreeSnapshot) -> str:
        if not snapshot.available:
            return f"Git unavailable: {snapshot.error or 'unknown'}"
        if not snapshot.files:
            return "工作区干净"
        parts: List[str] = []
        if snapshot.has_staged:
            parts.append("有 staged 改动")
        if snapshot.has_unstaged:
            parts.append("有 unstaged 改动")
        if snapshot.has_untracked:
            parts.append("有 untracked 文件")
        parts.append(f"共 {len(snapshot.files)} 个变化文件")
        return "，".join(parts)

    def refresh_git_memory(self, force: bool = False) -> GitMemoryState:
        with self._lock:
            available, error = self.is_git_available()
            now = _utcnow_iso()
            if not available:
                self._last_state = GitMemoryState(
                    available=False,
                    head_rev=None,
                    indexed_head_rev=None,
                    dirty=False,
                    snapshot_id=None,
                    refreshed_at=now,
                    error=error,
                )
                return self._last_state

            index_result = self.index_recent_changes()
            snapshot = self.scan_working_tree(store=True)
            head_rev = self._git_head_rev()
            self._last_state = GitMemoryState(
                available=True,
                head_rev=head_rev,
                indexed_head_rev=head_rev if head_rev else self._get_last_indexed_commit(),
                dirty=bool(snapshot.files),
                snapshot_id=snapshot.snapshot_id,
                refreshed_at=now,
                error=index_result.get("error"),
            )
            session = get_session_state()
            if not snapshot.files:
                session.clear_attention_tracking(keep_validation=True)
            session.active_git_base = head_rev
            session.last_git_scan_at = now
            self._sync_attention_cache(snapshot)
            self._bus.publish(
                EventNames.GIT_SCAN_COMPLETED,
                {"head_rev": head_rev, "dirty": bool(snapshot.files), "snapshot_id": snapshot.snapshot_id},
                source="GitMemoryService",
            )
            self._bus.publish(
                EventNames.GIT_INDEX_UPDATED,
                {
                    "indexed_commits": index_result.get("indexed_commits", []),
                    "snapshot_id": snapshot.snapshot_id,
                    "dirty": bool(snapshot.files),
                },
                source="GitMemoryService",
            )
            return self._last_state

    def note_file_modified(self, filepath: str) -> None:
        session = get_session_state()
        session.record_modified_path(filepath)
        entities = [entity["entity_ref"] for entity in self._entity_refs_for_path(filepath)]
        if entities:
            session.record_modified_entities(filepath, entities)
        self._sync_attention_cache()

    def _sync_attention_cache(self, snapshot: Optional[WorkingTreeSnapshot] = None) -> None:
        session = get_session_state()
        attention = session.get_attention_snapshot()
        dirty_summary = self._dirty_summary(snapshot) if snapshot else attention.get("dirty_summary", "")
        with self._workspace.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO GitAttentionCache(
                    session_id, updated_at, modified_paths_json, modified_entities_json, dirty_summary, last_validation_summary
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "default",
                    _utcnow_iso(),
                    json.dumps(attention["modified_paths"], ensure_ascii=False),
                    json.dumps(attention["modified_entities"], ensure_ascii=False),
                    dirty_summary,
                    attention.get("last_validation_summary"),
                ),
            )

    def get_recent_project_changes(self, limit: int = 10) -> List[ChangeRecord]:
        with self._workspace.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT fc.commit_sha, fc.path, fc.change_type, fc.old_path, fc.summary, gc.subject
                FROM GitFileChange fc
                LEFT JOIN GitCommit gc ON gc.commit_sha = fc.commit_sha
                WHERE fc.is_worktree = 0
                ORDER BY gc.author_time DESC, fc.id DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cursor.fetchall()
        return [
            ChangeRecord(
                kind="commit",
                path=row["path"],
                summary=row["summary"] or f"{row['change_type']}: {row['path']}",
                commit_sha=row["commit_sha"],
                change_type=row["change_type"],
                old_path=row["old_path"],
                subject=row["subject"],
            )
            for row in rows
        ]

    def get_entity_history(self, entity_ref: str, limit: int = 10) -> List[Dict[str, Any]]:
        with self._workspace.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT ec.commit_sha, ec.path, ec.entity_ref, ec.entity_type, ec.change_type, ec.is_worktree, gc.subject
                FROM GitEntityChange ec
                LEFT JOIN GitCommit gc ON gc.commit_sha = ec.commit_sha
                WHERE ec.entity_ref = ?
                ORDER BY ec.id DESC
                LIMIT ?
                """,
                (entity_ref, limit),
            )
            rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def get_current_attention_context(self) -> AttentionContext:
        session = get_session_state()
        snapshot = self._last_snapshot or self.scan_working_tree(store=False)
        attention = session.get_attention_snapshot()
        recent_changes = self.get_recent_project_changes(limit=5)
        return AttentionContext(
            modified_paths=attention["modified_paths"],
            modified_entities=attention["modified_entities"],
            dirty_summary=self._dirty_summary(snapshot),
            last_validation_summary=attention.get("last_validation_summary"),
            recent_changes=recent_changes,
        )

    def format_prompt_context(self) -> str:
        state = self._last_state
        attention = self.get_current_attention_context()
        session_snapshot = get_session_state().get_attention_snapshot()
        lines = ["## Git Memory"]
        if not state.available:
            lines.append(f"- Git 状态: 不可用 ({state.error or 'unknown'})")
            return "\n".join(lines)

        if attention.recent_changes:
            lines.append("- 最近提交变化:")
            for change in attention.recent_changes[:4]:
                suffix = f" ({change.subject})" if change.subject else ""
                lines.append(f"  - `{change.path}`: {change.change_type}{suffix}")

        lines.append(f"- 当前工作区: {attention.dirty_summary}")
        if attention.modified_entities:
            display = ", ".join(f"`{name}`" for name in attention.modified_entities[:6])
            lines.append(f"- 最近关注实体: {display}")
        recent_runtime_validations = session_snapshot.get("recent_validation_results") or []
        if attention.last_validation_summary and not recent_runtime_validations:
            lines.append(f"- 最近验证: {attention.last_validation_summary}")
        return "\n".join(lines)

    def get_git_status_summary(self, limit: int = 5) -> str:
        attention = self.get_current_attention_context()
        recent_changes = self.get_recent_project_changes(limit=max(1, min(int(limit or 5), 10)))
        payload = {
            "dirty_summary": attention.dirty_summary,
            "modified_paths": attention.modified_paths,
            "modified_entities": attention.modified_entities,
            "last_validation_summary": attention.last_validation_summary,
            "recent_changes": [
                {
                    "path": change.path,
                    "change_type": change.change_type,
                    "subject": _short_subject(change.subject),
                }
                for change in recent_changes
            ],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def explain_current_worktree(self) -> str:
        snapshot = self._last_snapshot or self.scan_working_tree(store=False)
        return json.dumps(asdict(snapshot), ensure_ascii=False, indent=2)

    def open_evolution_transaction(self, summary: str = "") -> str:
        head_rev = self._git_head_rev()
        txn_id = f"txn-{uuid.uuid4().hex[:12]}"
        with self._workspace.get_db_connection() as conn:
            conn.cursor().execute(
                """
                INSERT INTO EvolutionTransaction(txn_id, opened_at, closed_at, base_rev, status, summary)
                VALUES (?, ?, NULL, ?, 'open', ?)
                """,
                (txn_id, _utcnow_iso(), head_rev, summary),
            )
        self._bus.publish(EventNames.EVOLUTION_TXN_OPENED, {"txn_id": txn_id, "base_rev": head_rev}, source="GitMemoryService")
        return txn_id

    def close_evolution_transaction(self, txn_id: str, status: str, summary: str = "") -> None:
        with self._workspace.get_db_connection() as conn:
            conn.cursor().execute(
                """
                UPDATE EvolutionTransaction
                SET closed_at = ?, status = ?, summary = ?
                WHERE txn_id = ?
                """,
                (_utcnow_iso(), status, summary, txn_id),
            )
        self._bus.publish(EventNames.EVOLUTION_TXN_CLOSED, {"txn_id": txn_id, "status": status}, source="GitMemoryService")


_git_memory_service: Optional[GitMemoryService] = None


def get_git_memory_service() -> GitMemoryService:
    global _git_memory_service
    if _git_memory_service is None:
        _git_memory_service = GitMemoryService()
    return _git_memory_service


def refresh_git_memory(force: bool = False) -> GitMemoryState:
    return get_git_memory_service().refresh_git_memory(force=force)


def get_recent_project_changes(limit: int = 10) -> List[ChangeRecord]:
    return get_git_memory_service().get_recent_project_changes(limit=limit)


def get_current_attention_context() -> AttentionContext:
    return get_git_memory_service().get_current_attention_context()
