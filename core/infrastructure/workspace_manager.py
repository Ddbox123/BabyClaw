# -*- coding: utf-8 -*-
"""
Workspace Manager - 统一工作区管理

所有身份、记忆、任务与运行时派生物都存储在 workspace/ 目录下。
提供 SQLite 数据库 (agent_brain.db) 作为统一存储引擎。

目录结构:
  workspace/
  ├── agent_brain.db      # SQLite 主数据库
  ├── memory/
  │   ├── memory.json     # 轻量级索引
  │   └── archives/        # 世代详细档案
  ├── prompts/            # 运行时派生提示词与状态文件
  │   ├── CODEBASE_MAP.md
  │   ├── DYNAMIC.md
  │   ├── INDEX.md
  │   └── STATE_MEMORY.md
  └── logs/               # 运行日志
"""

import os
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List
from contextlib import contextmanager

# 日志


# =============================================================================
# 项目根目录定位辅助函数
# =============================================================================

def _resolve_project_root() -> Path:
    """
    动态获取项目根目录。

    __file__ = core/infrastructure/workspace_manager.py
    parent  = core/infrastructure/
    parent.parent = core/
    parent.parent.parent = 项目根 (self-evo-baby/)

    如果 core/ 下没有 agent.py，说明算错了，回退到 sys.path 搜索。
    """
    p = Path(__file__).parent.parent.parent.resolve()
    if (p / "agent.py").exists():
        return p
    # 回退：在 sys.path 中找 agent.py
    for sp in sys_path_iter():
        candidate = os.path.join(sp, "agent.py")
        if os.path.exists(candidate):
            return Path(sp).resolve()
    return p


def _resolve_workspace_root(project_root: Optional[Path] = None) -> Path:
    """稳定解析 workspace 根目录。"""
    root = (project_root or _resolve_project_root()).resolve()
    return root / "workspace"


def sys_path_iter():
    """遍历 sys.path，跳过不存在的路径"""
    import sys
    for p in sys.path:
        if p and os.path.isdir(p):
            yield p


# =============================================================================
# WorkspaceManager 类
# =============================================================================

class WorkspaceManager:
    """
    工作区管理器 - 统一管理所有 Agent 数据

    提供：
    - workspace/ 路径管理
    - SQLite 数据库连接
    - 路径解析
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
            cls._instance._initializing = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        # 动态获取项目根目录
        self._project_root = _resolve_project_root()
        self._workspace = _resolve_workspace_root(self._project_root)

        # 数据库路径要在可能触发重入的目录/日志初始化之前可用。
        self._db_path = self._workspace / "agent_brain.db"
        if self._initializing:
            return
        self._initializing = True

        try:
            # 确保目录结构存在
            self._ensure_workspace_structure()

            # 初始化数据库
            self._init_database()

            self._initialized = True
        finally:
            self._initializing = False

    def _ensure_workspace_structure(self):
        """确保工作区目录结构完整"""
        dirs = [
            self._workspace,
            self._workspace / "memory",
            self._workspace / "memory" / "archives",
            self._workspace / "prompts",
            self._workspace / "logs",
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)
            from core.logging import debug_logger

            debug_logger.info(f"[Workspace] 确保目录: {d}")

        # 将合法目录注册到 PathSandbox，防止文件创建时被误拦
        try:
            from core.infrastructure.security import get_security_validator
            sv = get_security_validator()
            for d in dirs:
                sv.path_sandbox.add_allowed_directory(str(d))
        except Exception:
            pass

    def _init_database(self):
        """初始化 SQLite 数据库"""
        conn = sqlite3.connect(str(self._db_path))
        cursor = conn.cursor()

        # Identity 表 - 当前活跃的人设和规则快照
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS Identity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE NOT NULL,
                value TEXT,
                description TEXT,
                updated_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        # LongTermMemory 表 - 跨代总结、核心架构认知
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS LongTermMemory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                generation INTEGER NOT NULL,
                category TEXT NOT NULL,
                title TEXT,
                content TEXT NOT NULL,
                importance INTEGER DEFAULT 1,
                created_at TEXT NOT NULL
            )
        """)

        # TaskLog 表 - 所有子任务及其完成摘要
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS TaskLog (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT UNIQUE NOT NULL,
                generation INTEGER NOT NULL,
                description TEXT NOT NULL,
                status TEXT NOT NULL,
                result TEXT,
                created_at TEXT NOT NULL,
                completed_at TEXT
            )
        """)

        # ErrorArchive 表 - 历史上遇到的致命报错及解决方案
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ErrorArchive (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                error_type TEXT NOT NULL,
                error_msg TEXT NOT NULL,
                solution TEXT,
                occurrence_count INTEGER DEFAULT 1,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                UNIQUE(error_type, error_msg)
            )
        """)

        # CodebaseKnowledge 表 - 代码库认知地图（跨代传承）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS CodebaseKnowledge (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                module_path TEXT UNIQUE NOT NULL,
                insight_summary TEXT NOT NULL,
                last_updated_gen INTEGER NOT NULL,
                updated_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        # Git 记忆索引表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS GitCommit (
                commit_sha TEXT PRIMARY KEY,
                parent_sha TEXT,
                author_time TEXT,
                subject TEXT,
                indexed_at TEXT NOT NULL
            )
        """)
        cursor.execute("""
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
        """)
        cursor.execute("""
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
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS GitWorkingTreeSnapshot (
                snapshot_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                base_rev TEXT,
                has_staged INTEGER NOT NULL DEFAULT 0,
                has_unstaged INTEGER NOT NULL DEFAULT 0,
                has_untracked INTEGER NOT NULL DEFAULT 0
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS GitAttentionCache (
                session_id TEXT PRIMARY KEY,
                updated_at TEXT NOT NULL,
                modified_paths_json TEXT NOT NULL,
                modified_entities_json TEXT NOT NULL,
                dirty_summary TEXT,
                last_validation_summary TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS EvolutionTransaction (
                txn_id TEXT PRIMARY KEY,
                opened_at TEXT NOT NULL,
                closed_at TEXT,
                base_rev TEXT,
                status TEXT NOT NULL,
                summary TEXT
            )
        """)

        # 索引
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ltm_gen ON LongTermMemory(generation)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_task_gen ON TaskLog(generation)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_task_status ON TaskLog(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_codebase_module ON CodebaseKnowledge(module_path)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_git_file_change_commit ON GitFileChange(commit_sha)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_git_entity_change_commit ON GitEntityChange(commit_sha)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_git_entity_change_ref ON GitEntityChange(entity_ref)")

        conn.commit()
        conn.close()

        from core.logging import debug_logger

        debug_logger.info(f"[Workspace] 数据库初始化: {self._db_path}")

    @contextmanager
    def get_db_connection(self):
        """获取数据库连接的上下文管理器"""
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()  # 确保提交事务
        finally:
            conn.close()

    # ==================== 路径属性 ====================

    @property
    def root(self) -> Path:
        """工作区根目录"""
        return self._workspace

    @property
    def project_root(self) -> Path:
        """项目根目录"""
        return self._project_root

    @property
    def db_path(self) -> Path:
        """数据库路径"""
        return self._db_path

    @property
    def memory_dir(self) -> Path:
        """记忆目录"""
        return self._workspace / "memory"

    @property
    def memory_index(self) -> Path:
        """轻量级索引文件"""
        return self._workspace / "memory" / "memory.json"

    @property
    def archives_dir(self) -> Path:
        """世代档案目录"""
        return self._workspace / "memory" / "archives"

    @property
    def prompts_dir(self) -> Path:
        """提示词目录"""
        return self._workspace / "prompts"

    @property
    def logs_dir(self) -> Path:
        """日志目录"""
        return self._workspace / "logs"

    # ==================== 便捷路径方法 ====================

    def get_prompt_path(self, name: str) -> Path:
        """获取提示词文件路径"""
        return self._workspace / "prompts" / name

    def get_archive_path(self, generation: int) -> Path:
        """获取指定世代的档案路径。"""
        return self.archives_dir / f"generation_{generation}.json"

    # ==================== 数据库操作 ====================

    def get_identity(self, key: str) -> Optional[str]:
        """获取身份/规则值"""
        with self.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM Identity WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row['value'] if row else None

    def set_identity(self, key: str, value: str, description: str = None):
        """设置身份/规则值"""
        now = datetime.now().isoformat()
        with self.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO Identity (key, value, description, updated_at, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    description = COALESCE(excluded.description, description),
                    updated_at = excluded.updated_at
            """, (key, value, description, now, now))

    def add_task(self, task_id: str, generation: int, description: Optional[str] = None) -> int:
        """添加任务，兼容旧签名 add_task(task_id, description)。"""
        if description is None:
            description = str(generation)
            generation = 1
        now = datetime.now().isoformat()
        with self.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO TaskLog (task_id, generation, description, status, created_at)
                VALUES (?, ?, ?, 'pending', ?)
            """, (task_id, generation, description, now))
            return cursor.lastrowid

    def update_task(self, task_id: str, status: str, result: str = None):
        """更新任务状态"""
        now = datetime.now().isoformat()
        with self.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE TaskLog SET status = ?, result = ?, completed_at = ?
                WHERE task_id = ?
            """, (status, result, now if status == 'completed' else None, task_id))

    def record_error(self, error_type: str, error_msg: str, solution: str = None):
        """记录错误"""
        now = datetime.now().isoformat()
        with self.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO ErrorArchive (error_type, error_msg, solution, last_seen, first_seen)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(error_type, error_msg) DO UPDATE SET
                    solution = COALESCE(excluded.solution, solution),
                    occurrence_count = occurrence_count + 1,
                    last_seen = excluded.last_seen
            """, (error_type, error_msg, solution, now, now))

    def get_recent_errors(self, limit: int = 10) -> List[Dict]:
        """获取最近的错误记录"""
        with self.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM ErrorArchive ORDER BY last_seen DESC LIMIT ?
            """, (limit,))
            return [dict(row) for row in cursor.fetchall()]

    # ==================== 代码库认知地图操作 ====================

    def record_codebase_insight(self, module_path: str, insight: str, generation: int = 1) -> bool:
        """刻印代码库认知（UPSERT 逻辑）"""
        now = datetime.now().isoformat()
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO CodebaseKnowledge (module_path, insight_summary, last_updated_gen, updated_at, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(module_path) DO UPDATE SET
                        insight_summary = excluded.insight_summary,
                        last_updated_gen = excluded.last_updated_gen,
                        updated_at = excluded.updated_at
                """, (module_path, insight, generation, now, now))
            return True
        except Exception as e:
            from core.logging import debug_logger

            debug_logger.error(f"[Workspace] 刻印代码库认知失败: {e}")
            return False

    def get_all_codebase_knowledge(self) -> List[Dict]:
        """获取所有代码库认知"""
        with self.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM CodebaseKnowledge ORDER BY module_path
            """)
            return [dict(row) for row in cursor.fetchall()]

    def generate_codebase_map(self) -> str:
        """生成代码库认知地图（用于注入 System Prompt）"""
        knowledge = self.get_all_codebase_knowledge()
        if not knowledge:
            return ""
        lines = []
        lines.append("## 🗺️ 你的天生代码库常识 (前代遗传记忆)")
        lines.append("")
        lines.append("> ⚠️ 如果上述地图已包含某个模块的信息，**禁止盲目重复探索**！")
        lines.append("")
        for item in knowledge:
            module = item['module_path']
            insight = item['insight_summary']
            gen = item['last_updated_gen']
            lines.append(f"- `{module}`: {insight} (G{gen})")
        return '\n'.join(lines)

    # ==================== LongTermMemory 操作 ====================

    def add_long_term_memory(self, generation: int, category: str, content: str, title: str = None, importance: int = 1) -> bool:
        """写入跨代长期记忆"""
        now = datetime.now().isoformat()
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO LongTermMemory (generation, category, title, content, importance, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (generation, category, title, content, importance, now))
            return True
        except Exception as e:
            from core.logging import debug_logger

            debug_logger.error(f"[Workspace] 写入长期记忆失败: {e}")
            return False

    def get_memories_by_generation(self, generation: int) -> list:
        """按世代查询长期记忆"""
        with self.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM LongTermMemory WHERE generation = ? ORDER BY id DESC
            """, (generation,))
            return [dict(row) for row in cursor.fetchall()]

    def search_long_term_memory(self, query: str, category: str = None, limit: int = 20) -> list:
        """搜索长期记忆"""
        with self.get_db_connection() as conn:
            cursor = conn.cursor()
            if category:
                cursor.execute("""
                    SELECT * FROM LongTermMemory
                    WHERE (title LIKE ? OR content LIKE ?) AND category = ?
                    ORDER BY importance DESC, id DESC LIMIT ?
                """, (f'%{query}%', f'%{query}%', category, limit))
            else:
                cursor.execute("""
                    SELECT * FROM LongTermMemory
                    WHERE title LIKE ? OR content LIKE ?
                    ORDER BY importance DESC, id DESC LIMIT ?
                """, (f'%{query}%', f'%{query}%', limit))
            return [dict(row) for row in cursor.fetchall()]

    def search_codebase_knowledge(self, query: str, limit: int = 20) -> list:
        """搜索代码库认知"""
        with self.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM CodebaseKnowledge
                WHERE module_path LIKE ? OR insight_summary LIKE ?
                ORDER BY module_path LIMIT ?
            """, (f'%{query}%', f'%{query}%', limit))
            return [dict(row) for row in cursor.fetchall()]

    def search_error_archive(self, error_type: str = None, limit: int = 20) -> list:
        """搜索错误归档"""
        with self.get_db_connection() as conn:
            cursor = conn.cursor()
            if error_type:
                cursor.execute("""
                    SELECT * FROM ErrorArchive WHERE error_type LIKE ?
                    ORDER BY last_seen DESC LIMIT ?
                """, (f'%{error_type}%', limit))
            else:
                cursor.execute("""
                    SELECT * FROM ErrorArchive ORDER BY last_seen DESC LIMIT ?
                """, (limit,))
            return [dict(row) for row in cursor.fetchall()]

    # ==================== 记忆索引文件操作 ====================

    def read_memory_index(self) -> Dict[str, Any]:
        """读取轻量级索引"""
        if self.memory_index.exists():
            with open(self.memory_index, 'r', encoding='utf-8') as f:
                return json.load(f)
        return self._default_memory_index()

    def _default_memory_index(self) -> Dict[str, Any]:
        """默认记忆索引"""
        return {
            "current_generation": 1,
            "core_wisdom": "初始状态",
            "current_goal": "熟悉环境",
            "last_archive_time": None,
        }

    def write_memory_index(self, data: Dict[str, Any]) -> bool:
        """写入轻量级索引"""
        try:
            with open(self.memory_index, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            from core.logging import debug_logger

            debug_logger.error(f"[Workspace] 写入记忆索引失败: {e}")
            return False

    # ==================== 提示词文件操作 ====================

    def read_prompt(self, filename: str) -> str:
        """读取提示词文件"""
        path = self.get_prompt_path(filename)
        if path.exists():
            with open(path, 'r', encoding='utf-8') as f:
                return f.read()
        return ""

    def write_prompt(self, filename: str, content: str) -> bool:
        """写入提示词文件"""
        try:
            path = self.get_prompt_path(filename)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            return True
        except Exception as e:
            from core.logging import debug_logger

            debug_logger.error(f"[Workspace] 写入提示词失败: {e}")
            return False

    # ==================== 状态报告 ====================

    def get_workspace_status(self) -> Dict[str, Any]:
        """获取工作区状态"""
        return {
            "project_root": str(self._project_root),
            "workspace_root": str(self._workspace),
            "db_path": str(self._db_path),
            "db_size_bytes": self._db_path.stat().st_size if self._db_path.exists() else 0,
            "memory_index": str(self.memory_index),
            "prompts_count": len(list(self.prompts_dir.glob("*.md"))),
            "archives_count": len(list(self.archives_dir.glob("*.json"))),
            "directories": {
                "memory": str(self.memory_dir),
                "prompts": str(self.prompts_dir),
                "archives": str(self.archives_dir),
                "logs": str(self.logs_dir),
            }
        }


# =============================================================================
# 全局单例
# =============================================================================

_workspace: Optional[WorkspaceManager] = None


def get_workspace() -> WorkspaceManager:
    """获取全局工作区管理器"""
    global _workspace
    if _workspace is None:
        _workspace = WorkspaceManager()
    return _workspace
