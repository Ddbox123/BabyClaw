#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
工作区管理器测试 (test_workspace_manager.py)

测试 core/infrastructure/workspace_manager.py 中的：
- Singleton 模式
- 目录结构创建
- SQLite 数据库初始化
- Identity CRUD
- LongTermMemory 操作
- TaskLog CRUD
- ErrorArchive 操作
- CodebaseKnowledge 操作
- Memory Index JSON 读写
- Prompt 文件读写
- Workspace 状态报告
"""

import sys
import sqlite3
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


# ============================================================================
# Fixture: 用 tmp_path 替换项目根目录
# ============================================================================

@pytest.fixture
def isolated_workspace(tmp_path, monkeypatch):
    """
    创建隔离的 WorkspaceManager 实例，所有操作在 tmp_path 中进行。
    绕过单例模式，直接构造新实例。
    """
    # 在 tmp_path 中创建 agent.py 以通过 _resolve_project_root 检查
    (tmp_path / "agent.py").write_text("# test", encoding="utf-8")

    # 重写 _resolve_project_root
    monkeypatch.setattr(
        "core.infrastructure.workspace_manager._resolve_project_root",
        lambda: tmp_path.resolve(),
    )

    from core.infrastructure.workspace_manager import WorkspaceManager

    # 创建新实例（绕过单例）
    old_instance = WorkspaceManager._instance
    WorkspaceManager._instance = None
    wm = WorkspaceManager()
    yield wm
    WorkspaceManager._instance = old_instance


# ============================================================================
# Singleton 测试
# ============================================================================

class TestWorkspaceManagerSingleton:
    """Singleton 模式测试"""

    def test_get_workspace_returns_instance(self):
        """get_workspace 返回实例"""
        from core.infrastructure.workspace_manager import get_workspace
        wm = get_workspace()
        assert wm is not None

    def test_get_workspace_same_instance(self):
        """多次调用返回同一实例"""
        from core.infrastructure.workspace_manager import get_workspace
        wm1 = get_workspace()
        wm2 = get_workspace()
        assert wm1 is wm2


# ============================================================================
# 目录结构测试
# ============================================================================

class TestDirectoryStructure:
    """目录结构测试"""

    def test_workspace_root_exists(self, isolated_workspace):
        """workspace 根目录创建"""
        assert isolated_workspace.root.exists()

    def test_memory_dir_exists(self, isolated_workspace):
        """memory 目录创建"""
        assert isolated_workspace.memory_dir.exists()

    def test_archives_dir_exists(self, isolated_workspace):
        """archives 目录创建"""
        assert isolated_workspace.archives_dir.exists()

    def test_prompts_dir_exists(self, isolated_workspace):
        """prompts 目录创建"""
        assert isolated_workspace.prompts_dir.exists()

    def test_logs_dir_exists(self, isolated_workspace):
        """logs 目录创建"""
        assert isolated_workspace.logs_dir.exists()

    def test_database_file_created(self, isolated_workspace):
        """数据库文件创建"""
        assert isolated_workspace.db_path.exists()


# ============================================================================
# 路径属性测试
# ============================================================================

class TestPathProperties:
    """路径属性测试"""

    def test_root_is_path(self, isolated_workspace):
        """root 返回 Path 对象"""
        assert isinstance(isolated_workspace.root, Path)

    def test_db_path_in_workspace(self, isolated_workspace):
        """db_path 在 workspace 下"""
        assert "agent_brain.db" in str(isolated_workspace.db_path)
        assert str(isolated_workspace.root) in str(isolated_workspace.db_path)

    def test_memory_index_path(self, isolated_workspace):
        """memory_index 返回 JSON 文件路径"""
        assert isolated_workspace.memory_index.suffix == ".json"

    def test_get_prompt_path(self, isolated_workspace):
        """get_prompt_path 返回正确路径"""
        path = isolated_workspace.get_prompt_path("SOUL")
        assert "SOUL" in str(path)
        assert path.parent == isolated_workspace.prompts_dir

    def test_get_archive_path(self, isolated_workspace):
        """get_archive_path 返回正确路径"""
        path = isolated_workspace.get_archive_path(5)
        assert "5" in str(path)
        assert path.parent == isolated_workspace.archives_dir

    def test_workspace_root_does_not_follow_cwd(self, tmp_path, monkeypatch):
        """workspace 根目录应由项目根决定，而不是当前 cwd"""
        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / "agent.py").write_text("# test", encoding="utf-8")
        nested_cwd = tmp_path / "elsewhere"
        nested_cwd.mkdir()

        monkeypatch.chdir(nested_cwd)
        monkeypatch.setattr(
            "core.infrastructure.workspace_manager._resolve_project_root",
            lambda: project_root.resolve(),
        )

        from core.infrastructure.workspace_manager import WorkspaceManager

        old_instance = WorkspaceManager._instance
        WorkspaceManager._instance = None
        try:
            wm = WorkspaceManager()
            assert wm.root == project_root / "workspace"
        finally:
            WorkspaceManager._instance = old_instance


# ============================================================================
# SQLite 数据库测试
# ============================================================================

class TestSQLiteDatabase:
    """SQLite 数据库测试"""

    def test_database_has_identity_table(self, isolated_workspace):
        """数据库包含 Identity 表"""
        with isolated_workspace.get_db_connection() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='Identity'"
            )
            assert cursor.fetchone() is not None

    def test_database_has_long_term_memory_table(self, isolated_workspace):
        """数据库包含 LongTermMemory 表"""
        with isolated_workspace.get_db_connection() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='LongTermMemory'"
            )
            assert cursor.fetchone() is not None

    def test_database_has_task_log_table(self, isolated_workspace):
        """数据库包含 TaskLog 表"""
        with isolated_workspace.get_db_connection() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='TaskLog'"
            )
            assert cursor.fetchone() is not None

    def test_database_has_error_archive_table(self, isolated_workspace):
        """数据库包含 ErrorArchive 表"""
        with isolated_workspace.get_db_connection() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='ErrorArchive'"
            )
            assert cursor.fetchone() is not None

    def test_database_has_codebase_knowledge_table(self, isolated_workspace):
        """数据库包含 CodebaseKnowledge 表"""
        with isolated_workspace.get_db_connection() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='CodebaseKnowledge'"
            )
            assert cursor.fetchone() is not None

    def test_db_connection_context_manager(self, isolated_workspace):
        """数据库连接作为上下文管理器工作"""
        with isolated_workspace.get_db_connection() as conn:
            cursor = conn.execute("SELECT 1")
            assert cursor.fetchone()[0] == 1


# ============================================================================
# Identity CRUD 测试
# ============================================================================

class TestIdentityCRUD:
    """Identity CRUD 测试"""

    def test_get_identity_nonexistent_returns_none(self, isolated_workspace):
        """不存在的 key 返回 None"""
        assert isolated_workspace.get_identity("nonexistent_key") is None

    def test_set_and_get_identity(self, isolated_workspace):
        """设置后可以获取"""
        isolated_workspace.set_identity("agent_name", "TestAgent", "Agent name")
        assert isolated_workspace.get_identity("agent_name") == "TestAgent"

    def test_set_identity_updates_existing(self, isolated_workspace):
        """更新已存在的 key"""
        isolated_workspace.set_identity("key1", "value1")
        isolated_workspace.set_identity("key1", "value2")
        assert isolated_workspace.get_identity("key1") == "value2"

    def test_set_identity_special_characters(self, isolated_workspace):
        """特殊字符值"""
        isolated_workspace.set_identity("special", "unicode: 你好世界")
        assert isolated_workspace.get_identity("special") == "unicode: 你好世界"

    def test_set_identity_empty_value(self, isolated_workspace):
        """空值"""
        isolated_workspace.set_identity("empty_key", "")
        assert isolated_workspace.get_identity("empty_key") == ""

    def test_set_identity_without_description(self, isolated_workspace):
        """无 description 参数"""
        isolated_workspace.set_identity("key2", "value")
        assert isolated_workspace.get_identity("key2") == "value"


# ============================================================================
# LongTermMemory 测试
# ============================================================================

class TestLongTermMemory:
    """LongTermMemory 测试"""

    def test_add_and_get_by_generation(self, isolated_workspace):
        """添加后按世代查询"""
        isolated_workspace.add_long_term_memory(1, "insight", "测试记忆", importance=5)
        results = isolated_workspace.get_memories_by_generation(1)
        assert len(results) == 1
        assert results[0]["content"] == "测试记忆"
        assert results[0]["category"] == "insight"
        assert results[0]["importance"] == 5

    def test_get_empty_generation(self, isolated_workspace):
        """查询无记忆的世代返回空列表"""
        results = isolated_workspace.get_memories_by_generation(999)
        assert results == []

    def test_multiple_memories_same_generation(self, isolated_workspace):
        """同一世代多条记忆"""
        isolated_workspace.add_long_term_memory(2, "insight", "Memory 1")
        isolated_workspace.add_long_term_memory(2, "lesson", "Memory 2")
        results = isolated_workspace.get_memories_by_generation(2)
        assert len(results) == 2

    def test_memory_without_title(self, isolated_workspace):
        """无标题记忆"""
        isolated_workspace.add_long_term_memory(3, "note", "No title memory")
        results = isolated_workspace.get_memories_by_generation(3)
        assert results[0]["title"] is None


# ============================================================================
# TaskLog 测试
# ============================================================================

class TestTaskLog:
    """TaskLog 测试"""

    def test_add_task(self, isolated_workspace):
        """添加任务"""
        task_id = isolated_workspace.add_task("task_1", 1, "Test task")
        assert task_id >= 1

    def test_update_task_status(self, isolated_workspace):
        """更新任务状态"""
        isolated_workspace.add_task("task_2", 1, "Complete me")
        isolated_workspace.update_task("task_2", "completed", "Done")
        # 通过数据库验证
        with isolated_workspace.get_db_connection() as conn:
            row = conn.execute(
                "SELECT status, result FROM TaskLog WHERE task_id='task_2'"
            ).fetchone()
            assert row["status"] == "completed"
            assert row["result"] == "Done"

    def test_add_duplicate_task_id(self, isolated_workspace):
        """重复 task_id 会触发 UNIQUE 约束"""
        isolated_workspace.add_task("unique_task", 1, "First")
        with pytest.raises((sqlite3.IntegrityError, Exception)):
            isolated_workspace.add_task("unique_task", 1, "Second")


# ============================================================================
# ErrorArchive 测试
# ============================================================================

class TestErrorArchive:
    """ErrorArchive 测试"""

    def test_record_and_get_errors(self, isolated_workspace):
        """记录后可以获取"""
        isolated_workspace.record_error("ValueError", "Invalid value")
        errors = isolated_workspace.get_recent_errors(10)
        assert len(errors) >= 1

    def test_record_error_with_solution(self, isolated_workspace):
        """带解决方案的错误"""
        isolated_workspace.record_error("TypeError", "Bad type", solution="Cast it")
        errors = isolated_workspace.get_recent_errors(10)
        found = [e for e in errors if e["error_type"] == "TypeError"]
        assert len(found) >= 1
        assert found[0].get("solution") == "Cast it"

    def test_get_recent_errors_limit(self, isolated_workspace):
        """limit 参数有效"""
        for i in range(5):
            isolated_workspace.record_error(f"Error_{i}", f"Message {i}")
        errors = isolated_workspace.get_recent_errors(3)
        assert len(errors) == 3

    def test_record_error_upsert_deduplication(self, isolated_workspace):
        """相同 error_type + error_msg 去重（UPSERT）"""
        isolated_workspace.record_error("DupError", "Same message")
        isolated_workspace.record_error("DupError", "Same message", solution="Fixed")
        errors = isolated_workspace.get_recent_errors(10)
        dup_errors = [e for e in errors if e["error_type"] == "DupError"]
        assert len(dup_errors) == 1
        assert dup_errors[0].get("solution") == "Fixed"


# ============================================================================
# CodebaseKnowledge 测试
# ============================================================================

class TestCodebaseKnowledge:
    """CodebaseKnowledge 测试"""

    def test_record_and_get_insights(self, isolated_workspace):
        """记录后可以获取"""
        isolated_workspace.record_codebase_insight("agent.py", "Main entry", 1)
        results = isolated_workspace.get_all_codebase_knowledge()
        assert len(results) >= 1

    def test_record_insight_update_existing(self, isolated_workspace):
        """更新已存在的模块洞察"""
        isolated_workspace.record_codebase_insight("agent.py", "Insight v1", 1)
        isolated_workspace.record_codebase_insight("agent.py", "Insight v2", 2)
        results = isolated_workspace.get_all_codebase_knowledge()
        agent_insights = [r for r in results if r["module_path"] == "agent.py"]
        assert len(agent_insights) == 1

    def test_generate_codebase_map(self, isolated_workspace):
        """生成代码库地图"""
        isolated_workspace.record_codebase_insight("agent.py", "Main entry", 1)
        map_str = isolated_workspace.generate_codebase_map()
        assert isinstance(map_str, str)
        assert "agent.py" in map_str

    def test_get_all_knowledge_empty(self, isolated_workspace):
        """空知识库返回空列表"""
        results = isolated_workspace.get_all_codebase_knowledge()
        assert isinstance(results, list)


# ============================================================================
# Memory Index 测试
# ============================================================================

class TestMemoryIndex:
    """Memory Index JSON 读写测试"""

    def test_read_memory_index_returns_dict(self, isolated_workspace):
        """读取返回字典"""
        data = isolated_workspace.read_memory_index()
        assert isinstance(data, dict)

    def test_read_memory_index_has_default_keys(self, isolated_workspace):
        """默认包含必要字段"""
        data = isolated_workspace.read_memory_index()
        assert "current_generation" in data

    def test_write_and_read_roundtrip(self, isolated_workspace):
        """写入后读取往返一致"""
        test_data = {
            "current_generation": 7,
            "core_wisdom": "Test wisdom",
            "custom_key": "custom_value",
        }
        isolated_workspace.write_memory_index(test_data)
        result = isolated_workspace.read_memory_index()
        assert result["current_generation"] == 7
        assert result["core_wisdom"] == "Test wisdom"
        assert result["custom_key"] == "custom_value"

    def test_write_memory_index_returns_true(self, isolated_workspace):
        """写入成功返回 True"""
        result = isolated_workspace.write_memory_index({"gen": 1})
        assert result is True


# ============================================================================
# Prompt 文件读写测试
# ============================================================================

class TestPromptIO:
    """Prompt 文件读写测试"""

    def test_write_and_read_prompt(self, isolated_workspace):
        """写入后可以读取"""
        isolated_workspace.write_prompt("TEST.md", "# Test Prompt")
        content = isolated_workspace.read_prompt("TEST.md")
        assert content == "# Test Prompt"

    def test_read_nonexistent_prompt_returns_empty(self, isolated_workspace):
        """读取不存在的文件返回空字符串"""
        content = isolated_workspace.read_prompt("NONEXISTENT.md")
        assert content == ""

    def test_write_prompt_returns_true(self, isolated_workspace):
        """写入成功返回 True"""
        result = isolated_workspace.write_prompt("TEST2.md", "content")
        assert result is True

    def test_write_prompt_creates_file(self, isolated_workspace):
        """写入创建文件"""
        isolated_workspace.write_prompt("TEST3.md", "hello")
        path = isolated_workspace.prompts_dir / "TEST3.md"
        assert path.exists()


# ============================================================================
# Workspace Status 测试
# ============================================================================

class TestWorkspaceStatus:
    """Workspace Status 测试"""

    def test_get_workspace_status_returns_dict(self, isolated_workspace):
        """返回字典"""
        status = isolated_workspace.get_workspace_status()
        assert isinstance(status, dict)

    def test_workspace_status_has_directories(self, isolated_workspace):
        """包含目录信息"""
        status = isolated_workspace.get_workspace_status()
        assert "workspace_root" in status
        assert "directories" in status


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
