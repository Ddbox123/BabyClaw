#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
记忆与任务管理工具完整测试套件

测试 tools/memory_tools.py 中的所有功能：
- 记忆管理：索引、动态提示词
- 任务管理：计划制定、进度追踪、重启阻塞检查
"""

import os
import sys
import pytest
import tempfile
import shutil
import json
from datetime import datetime
from pathlib import Path

from tools.memory_tools import (
    read_memory_tool, get_memory_summary_tool,
    get_current_goal_tool, get_core_context_tool,
    commit_compressed_memory_tool, force_save_current_state,
    read_dynamic_prompt_tool,
    add_insight_to_dynamic_tool,
    check_restart_block,
    task_create_tool, task_update_tool,
    _load_memory, _save_memory, _get_memory_index_path,
)


@pytest.fixture(autouse=True)
def _isolate_memory(tmp_path):
    """隔离记忆文件和动态提示词：每个测试前备份，测试后恢复，防止测试污染 agent 状态。"""
    import tools.memory_tools as _mm_mod

    # --- 记忆文件隔离 ---
    monkey_path = str(tmp_path / "memory.json")
    old_env = os.environ.get("VIBELUTION_MEMORY_INDEX_PATH")
    os.environ["VIBELUTION_MEMORY_INDEX_PATH"] = monkey_path

    real_mem_path = _mm_mod._get_memory_index_path()
    backup_mem = None
    if os.path.exists(real_mem_path):
        with open(real_mem_path, 'r', encoding='utf-8') as f:
            backup_mem = f.read()

    with open(monkey_path, 'w', encoding='utf-8') as f:
        json.dump({"core_wisdom": "", "current_goal": ""}, f)

    # --- 动态提示词隔离 ---
    real_dyn_path = _mm_mod._get_dynamic_prompt_path()
    backup_dyn = None
    if os.path.exists(real_dyn_path):
        with open(real_dyn_path, 'r', encoding='utf-8') as f:
            backup_dyn = f.read()

    fake_dyn_path = str(tmp_path / "DYNAMIC.md")

    orig_dyn_func = _mm_mod._get_dynamic_prompt_path
    _mm_mod._get_dynamic_prompt_path = lambda: fake_dyn_path

    yield

    # --- 恢复 ---
    if backup_mem is not None:
        with open(real_mem_path, 'w', encoding='utf-8') as f:
            f.write(backup_mem)
    if old_env is None:
        os.environ.pop("VIBELUTION_MEMORY_INDEX_PATH", None)
    else:
        os.environ["VIBELUTION_MEMORY_INDEX_PATH"] = old_env

    _mm_mod._get_dynamic_prompt_path = orig_dyn_func
    if backup_dyn is not None:
        with open(real_dyn_path, 'w', encoding='utf-8') as f:
            f.write(backup_dyn)


# ============================================================================
# 记忆基础功能测试
# ============================================================================

class TestMemoryBasics:
    """记忆基础功能测试"""

    def test_memory_index_path_respects_env_override(self, tmp_path, monkeypatch):
        custom_path = tmp_path / "custom-memory.json"
        monkeypatch.setenv("VIBELUTION_MEMORY_INDEX_PATH", str(custom_path))

        assert _get_memory_index_path() == str(custom_path)
        assert custom_path.parent.exists()

    def test_read_memory_tool_returns_valid_json(self):
        """测试 read_memory_tool 返回有效 JSON 字符串"""
        import json
        result = read_memory_tool()
        assert isinstance(result, str)
        memory = json.loads(result)
        assert "core_wisdom" in memory

    def test_get_core_context_tool(self):
        """测试获取核心上下文"""
        context = get_core_context_tool()
        assert isinstance(context, str)

    def test_get_current_goal_tool(self):
        """测试获取当前目标"""
        goal = get_current_goal_tool()
        assert isinstance(goal, str)


# ============================================================================
# 记忆索引管理测试
# ============================================================================

class TestMemoryIndex:
    """记忆索引管理测试"""

    def test_default_memory_structure(self):
        """测试默认记忆结构"""
        memory = _load_memory()
        required_fields = ["core_wisdom", "current_goal"]
        for field in required_fields:
            assert field in memory, f"缺少字段: {field}"

    def test_memory_persistence(self):
        """测试记忆持久化"""
        # 读取应创建文件（如果不存在）
        memory = _load_memory()
        memory_path = _load_memory.__module__  # 仅验证不抛异常

        # 再次读取应相同
        memory2 = _load_memory()
        assert memory == memory2

    def test_save_memory_custom_values(self):
        """测试保存自定义记忆值"""
        memory = _load_memory()
        memory["test_key"] = "test_value"
        result = _save_memory(memory)
        assert result is True

        # 验证保存成功
        memory2 = _load_memory()
        assert memory2.get("test_key") == "test_value"

        # 清理
        del memory2["test_key"]
        _save_memory(memory2)


# ============================================================================
# 动态提示词测试
# ============================================================================

class TestDynamicPrompt:
    """动态提示词管理测试"""

    def test_read_dynamic_prompt_returns_content(self):
        """测试读取动态提示词"""
        content = read_dynamic_prompt_tool()
        assert isinstance(content, str)

    def test_add_insight_to_dynamic(self):
        """测试添加洞察"""
        insight = "测试洞察：代码应该保持简洁"
        result = add_insight_to_dynamic_tool(insight=insight)
        assert isinstance(result, str)

        # 验证
        content = read_dynamic_prompt_tool()
        assert insight in content

    def test_dynamic_prompt_persistence(self):
        """测试动态提示词持久化"""
        add_insight_to_dynamic_tool(insight="持久化测试洞察")

        # 重新读取
        content1 = read_dynamic_prompt_tool()
        assert "持久化测试洞察" in content1

        # 再次读取（应保持一致）
        content2 = read_dynamic_prompt_tool()
        assert content1 == content2


# ============================================================================
# 代码库洞察测试
# ============================================================================

class TestDynamicInsight:
    """动态洞察管理测试"""

    def test_insight_accumulation(self):
        """测试洞察累积"""
        insights = [
            "洞察1：模块化很重要",
            "洞察2：测试应该全面",
            "洞察3：代码需要文档",
        ]

        for insight in insights:
            add_insight_to_dynamic_tool(insight=insight)

        content = read_dynamic_prompt_tool()
        for insight in insights:
            assert insight in content


# ============================================================================
# commit_compressed_memory 测试
# ============================================================================

class TestCommitCompressedMemory:
    """commit_compressed_memory 测试"""

    def test_commit_memory_updates_index(self):
        """测试提交记忆更新索引"""
        result = commit_compressed_memory_tool(
            new_core_context="Test context",
            next_goal="Test goal"
        )
        assert isinstance(result, str)

        # 验证索引更新
        memory2 = _load_memory()
        assert "last_archive_time" in memory2

    def test_force_save_current_state(self):
        """测试强制保存当前状态"""
        result = force_save_current_state()
        assert isinstance(result, str)


# ============================================================================
# 记忆摘要测试
# ============================================================================

class TestMemorySummary:
    """记忆摘要测试"""

    def test_get_memory_summary_returns_readable(self):
        """测试获取可读的记忆摘要"""
        summary = get_memory_summary_tool()
        assert isinstance(summary, str)
        assert len(summary) > 0

    def test_memory_summary_format(self):
        """测试摘要格式"""
        summary = get_memory_summary_tool()
        lines = summary.split('\n')
        assert len(lines) >= 1


# ============================================================================
# 重启阻塞检查测试
# ============================================================================

class TestRestartBlock:
    """重启阻塞检查测试"""

    def test_restart_block_clear_initially(self):
        """初始状态允许重启（没有任务时）"""
        is_blocked, msg = check_restart_block()
        assert not is_blocked

    def test_restart_block_with_incomplete_tasks(self):
        """测试有未完成任务时阻止重启"""
        from core.orchestration.task_planner import get_task_manager
        tm = get_task_manager()
        tm.task_create(tasks=[{"description": "待办1"}], goal="测试")
        is_blocked, msg = check_restart_block()
        assert is_blocked
        assert "未完成" in msg


# ============================================================================
# 集成测试
# ============================================================================

class TestMemoryToolsIntegration:
    """记忆工具集成测试"""

    def test_full_memory_lifecycle(self):
        """测试完整记忆生命周期"""
        goal = get_current_goal_tool()
        assert isinstance(goal, str)

        add_insight_to_dynamic_tool(insight="集成测试洞察")

        dynamic = read_dynamic_prompt_tool()
        assert "集成测试洞察" in dynamic

        commit_result = commit_compressed_memory_tool(
            new_core_context="Integration test context",
            next_goal="Integration test goal"
        )
        assert isinstance(commit_result, str)

    def test_task_create_tool_accepts_json_string_payload(self):
        result = task_create_tool(
            task_list='[{"description":"验证当前工作区状态"},{"description":"执行 Agent 重启触发"}]',
            goal="测试重启闭环",
        )

        assert "已创建 2 个任务" in result

    def test_task_update_tool_coerces_string_task_id_and_bool(self):
        task_create_tool(
            task_list=[{"description": "验证当前工作区状态"}],
            goal="测试任务更新",
        )

        result = task_update_tool(
            task_id="1",
            is_completed="true",
            result_summary="状态已确认",
        )

        assert "任务 1 已更新: 完成" in result


# ============================================================================
# 异常处理测试
# ============================================================================

class TestErrorHandling:
    """异常处理测试"""

    def test_commit_without_prior_setup(self):
        """在没有前置操作时提交记忆"""
        result = commit_compressed_memory_tool(
            new_core_context="Error test context",
            next_goal="Error test goal"
        )
        assert isinstance(result, str)


# ============================================================================
# 性能测试
# ============================================================================

class TestPerformance:
    """性能基准测试"""

    def test_read_memory_performance(self):
        """测试读取记忆性能"""
        import time

        start = time.time()
        result = read_memory_tool()
        elapsed = time.time() - start

        assert elapsed < 2.0  # 应在 2 秒内完成


# ============================================================================

class TestDataConsistency:
    """数据一致性测试"""

    def test_memory_file_integrity(self):
        """测试记忆文件完整性"""
        memory = _load_memory()

        # 验证所有必需字段存在且类型正确
        assert isinstance(memory["core_wisdom"], str)
        assert isinstance(memory["current_goal"], str)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
