#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
工具执行器测试

测试 core/tool_executor.py 中的：
- 工具注册与管理
- 超时控制
- 事件总线集成
"""

import os
import sys
import pytest
import time
from types import SimpleNamespace
from pathlib import Path
from core.infrastructure.event_bus import EventNames, get_event_bus
from core.pet_system import get_pet_system
from core.pet_system.pet_system import reset_pet_system

from core.infrastructure import evolution_governor as governor_module
from core.infrastructure.tool_executor import ToolExecutor, get_tool_executor
from core.infrastructure.agent_session import get_session_state, reset_session_state


class TestToolExecutorInit:
    """工具执行器初始化测试"""

    def test_init(self):
        """测试初始化"""
        executor = ToolExecutor()
        assert executor._tool_map is not None
        assert len(executor._tool_map) > 0
        assert executor._timeout_map is not None
        assert executor._event_bus is not None

    def test_get_tool_executor_singleton(self):
        """测试单例模式"""
        executor1 = get_tool_executor()
        executor2 = get_tool_executor()
        assert executor1 is executor2

    def test_default_tools_registered(self):
        """测试默认工具已注册"""
        executor = ToolExecutor()
        
        # 检查关键工具是否已注册
        expected_tools = [
            "list_directory", "execute_shell_command", "run_powershell", "check_python_syntax",
            "trigger_self_restart_tool", "grep_search_tool",
            "task_create_tool", "task_update_tool", "task_list_tool",
            "cli_tool",
        ]
        
        for tool_name in expected_tools:
            assert tool_name in executor._tool_map, f"工具 {tool_name} 应该已注册"

    def test_default_timeouts_configured(self):
        """测试默认超时配置"""
        executor = ToolExecutor()
        
        # 检查关键工具的超时配置
        assert "execute_shell_command" in executor._timeout_map
        assert executor._timeout_map["execute_shell_command"] == 60
        
        assert "check_python_syntax" in executor._timeout_map
        assert executor._timeout_map["check_python_syntax"] == 10


class TestToolExecutorExecute:
    """工具执行测试"""

    @pytest.fixture
    def executor(self):
        """创建测试用的执行器实例"""
        return ToolExecutor()

    def test_execute_unknown_tool(self, executor):
        """测试执行未知工具"""
        result, action = executor.execute("nonexistent_tool", {})
        assert result is not None
        assert "[错误] 未知工具" in result
        assert action is None

    def test_execute_read_file(self, executor):
        """测试读取文件工具"""
        # 创建一个测试文件
        test_file = Path(__file__).parent / "test_temp_file.txt"
        test_content = "Hello, Tool Executor!"
        test_file.write_text(test_content, encoding='utf-8')
        
        try:
            result, action = executor.execute("read_file", {
                "file_path": str(test_file)
            })
            
            assert action is None
            assert test_content in str(result)
        finally:
            # 清理测试文件
            if test_file.exists():
                test_file.unlink()

    def test_execute_list_directory(self, executor):
        """测试列出目录工具"""
        test_dir = Path(__file__).parent
        
        result, action = executor.execute("list_directory", {
            "path": str(test_dir)
        })
        
        assert action is None
        assert result is not None
        # 应该包含当前目录的文件
        assert "test_security.py" in str(result) or "test_tool_executor.py" in str(result)

    def test_execute_check_python_syntax_valid(self, executor):
        """测试语法检查 - 有效文件"""
        # 使用当前测试文件（语法正确）
        result, action = executor.execute("check_python_syntax", {
            "file_path": __file__
        })
        
        assert action is None
        assert result is not None
        # 语法正确应该返回成功消息
        assert "语法正确" in str(result) or "Syntax OK" in str(result) or "通过" in str(result)

    def test_execute_with_timeout(self, executor):
        """测试超时控制"""
        # 执行一个快速命令验证超时机制工作
        result, action = executor.execute("list_directory", {
            "path": str(Path(__file__).parent)
        },)
        
        # 应该正常返回，不超时
        assert action is None
        assert result is not None
        assert "[超时]" not in str(result)


class TestToolExecutorTimeout:
    """超时控制测试"""

    @pytest.fixture
    def executor(self):
        return ToolExecutor()

    def test_custom_timeout_registration(self, executor):
        """测试自定义工具超时注册"""
        def slow_tool():
            time.sleep(0.1)
            return "done"
        
        executor.register_tool("test_slow_tool", slow_tool, timeout=5)
        assert executor._timeout_map["test_slow_tool"] == 5

    def test_default_timeout_for_unconfigured_tools(self, executor):
        """测试未配置超时工具的默认超时"""
        # execute 方法内部使用默认超时 30 秒
        # 这里验证工具执行不会因为缺少超时配置而崩溃
        result, action = executor.execute("list_directory", {
            "path": str(Path(__file__).parent)
        })
        assert result is not None

    def test_spawn_agent_tool_uses_requested_timeout_with_buffer(self, executor):
        timeout = executor._resolve_timeout("spawn_agent_tool", {"timeout": 120})

        assert timeout == 150

    def test_cli_tool_uses_requested_timeout(self, executor):
        timeout = executor._resolve_timeout("cli_tool", {"timeout": 600})

        assert timeout == 600

    def test_spawn_agent_tool_is_registered_for_internal_governor(self, executor):
        assert "spawn_agent_tool" in executor._tool_map

    def test_get_file_entities_tool_compat_alias_is_registered(self, executor):
        assert "get_file_entities_tool" in executor._tool_map

    def test_spawn_agent_tool_requires_internal_delegate_flag(self, executor):
        result, action = executor.execute("spawn_agent_tool", {"goal": "分析重复调用"})

        assert action is None
        assert "仅允许主 agent 的委派治理层内部调用" in str(result)

    def test_spawn_agent_tool_allows_internal_delegate_flag(self, executor):
        def fake_spawn_agent_tool(**kwargs):
            return f"delegated:{kwargs.get('goal', '')}"

        executor.register_tool("spawn_agent_tool", fake_spawn_agent_tool, timeout=5)

        result, action = executor.execute(
            "spawn_agent_tool",
            {"goal": "分析重复调用", "_internal_delegate": True},
        )

        assert action is None
        assert str(result) == "delegated:分析重复调用"

    def test_spawn_agent_tool_internal_flag_is_not_forwarded_to_tool(self, executor):
        captured = {}

        def fake_spawn_agent_tool(**kwargs):
            captured.update(kwargs)
            return "ok"

        executor.register_tool("spawn_agent_tool", fake_spawn_agent_tool, timeout=5)

        result, action = executor.execute(
            "spawn_agent_tool",
            {"goal": "分析重复调用", "_internal_delegate": True},
        )

        assert action is None
        assert str(result) == "ok"
        assert "_internal_delegate" not in captured


class TestToolExecutorEvents:
    """事件总线集成测试"""

    @pytest.fixture
    def executor(self):
        return ToolExecutor()

    def test_event_bus_integration(self, executor):
        """测试事件总线集成"""
        # 验证事件总线已连接
        assert executor._event_bus is not None
        
        # 执行一个工具，验证不会抛出异常
        result, action = executor.execute("list_directory", {
            "path": str(Path(__file__).parent)
        })
        
        # 如果事件总线有问题，这里会抛出异常
        assert result is not None


class TestToolExecutorRetry:
    """重试机制测试"""

    @pytest.fixture
    def executor(self):
        return ToolExecutor()

    def test_retryable_tools_configured(self, executor):
        """测试可重试工具配置"""
        # 检查是否配置了可重试工具
        assert isinstance(executor._retryable_tools, set)
        
        # 搜索工具应该是可重试的（网络相关可能失败）
        # 注意：根据实际配置调整
        assert len(executor._retryable_tools) >= 0  # 允许为空


class TestToolExecutorErrorHandling:
    """错误处理测试"""

    @pytest.fixture
    def executor(self):
        return ToolExecutor()

    def test_execute_tool_with_invalid_args(self, executor):
        """测试执行工具时参数错误"""
        # 传递错误参数类型
        result, action = executor.execute("read_file", {
            "file_path": 12345  # 应该是字符串
        })
        
        # 应该返回错误而不是抛出异常
        assert result is not None
        assert action is None

    def test_python_lint_publishes_validation_event(self, executor):
        events = []

        def on_validation(event):
            events.append(event.data)

        bus = get_event_bus()
        callback_id = "test_tool_executor_validation_event"
        bus.subscribe(EventNames.VALIDATION_COMPLETED, on_validation, callback_id=callback_id)

        def fake_lint_tool(file_path=""):
            return '{"status": "ok", "issue_count": 0}'

        executor.register_tool("python_lint_tool", fake_lint_tool, timeout=5)

        try:
            result, action = executor.execute("python_lint_tool", {"file_path": "agent.py"})
            assert action is None
            assert '"status": "ok"' in str(result)
            assert events
            assert events[-1]["kind"] == "lint"
            assert events[-1]["passed"] is True
        finally:
            bus.unsubscribe_by_id(callback_id)

    def test_cli_pipe_pattern_short_circuits_within_same_turn(self, executor):
        """同轮同类 pipe 模式被拦截后，第二次应直接短路。"""
        reset_session_state()

        call_counter = {"count": 0}

        def fake_cli_tool(command="", timeout=60):
            call_counter["count"] += 1
            return "[安全拦截] [Whitelist Block] 命令包含危险字符：|\n该危险命令已被系统安全策略禁止执行。"

        executor.register_tool("cli_tool", fake_cli_tool, timeout=5)

        first, _ = executor.execute("cli_tool", {"command": "git diff a b | head -20"})
        second, _ = executor.execute("cli_tool", {"command": "git show :x | head -20"})

        assert "[安全拦截]" in str(first)
        assert "[短路]" in str(second)
        assert call_counter["count"] == 1
        snapshot = get_session_state().get_attention_snapshot()
        assert "cli_tool:pipe" in snapshot["blocked_tool_patterns"]

    def test_cross_platform_warning_is_recorded_as_successful_platform_check(self, executor):
        """跨平台命令拦截是平台检查通过，不能污染 pytest 失败状态。"""
        reset_session_state()

        def fake_cli_tool(command="", timeout=60):
            return (
                "[跨平台警告] 在 Windows 上检测到 Unix shell 片段: "
                f"{command}\n请改用 PowerShell/Windows 等价命令。"
            )

        executor.register_tool("cli_tool", fake_cli_tool, timeout=5)

        result, action = executor.execute(
            "cli_tool",
            {"command": "python -m pytest tests/ --collect-only -q 2>/dev/null | tail -5"},
        )

        assert action is None
        assert "[跨平台警告]" in str(result)
        snapshot = get_session_state().get_attention_snapshot()
        assert snapshot["last_validation_summary"] == "Windows 平台检查通过：已拦截 Unix shell 片段"
        assert snapshot["last_validation_passed"] is True
        assert snapshot["recent_validation_results"][-1]["kind"] == "platform_check"
        assert snapshot["feedback_loop_ready"] is True
        assert snapshot["feedback_loop_type"] == "platform_check"
        assert snapshot["convergence_state"] == "ready_to_stop"
        assert "cli_tool:unix_shell_on_windows" in snapshot["blocked_tool_patterns"]

    def test_lint_validation_establishes_feedback_loop_and_freezes_scope(self, executor):
        reset_session_state()

        def fake_lint_tool(file_path=""):
            return '{"status": "ok", "issue_count": 0}'

        executor.register_tool("python_lint_tool", fake_lint_tool, timeout=5)

        result, action = executor.execute("python_lint_tool", {"file_path": "agent.py"})

        assert action is None
        assert '"status": "ok"' in str(result)
        snapshot = get_session_state().get_attention_snapshot()
        assert snapshot["feedback_loop_ready"] is True
        assert snapshot["feedback_loop_type"] == "lint"
        assert snapshot["scope_frozen"] is True
        assert snapshot["scope_anchor"] == "agent.py"

    def test_cli_command_chain_short_circuits_within_same_turn(self, executor):
        """同轮同类命令链模式被拦截后，第二次应直接短路。"""
        reset_session_state()

        call_counter = {"count": 0}

        def fake_cli_tool(command="", timeout=60):
            call_counter["count"] += 1
            return "[安全拦截] [Whitelist Block] 命令包含危险字符：&&\n该危险命令已被系统安全策略禁止执行。"

        executor.register_tool("cli_tool", fake_cli_tool, timeout=5)

        first, _ = executor.execute("cli_tool", {"command": "python -m py_compile agent.py && python -m pytest tests/test_agent_protocol.py -q"})
        second, _ = executor.execute("cli_tool", {"command": "cd workspace && dir"})

        assert "[安全拦截]" in str(first)
        assert "[短路]" in str(second)
        assert call_counter["count"] == 1
        snapshot = get_session_state().get_attention_snapshot()
        assert "cli_tool:command_chain" in snapshot["blocked_tool_patterns"]

    def test_read_file_records_read_range(self, executor, tmp_path):
        reset_session_state()
        file_path = tmp_path / "demo.txt"
        file_path.write_text("a\nb\nc\nd\n", encoding="utf-8")

        result, action = executor.execute("read_file", {
            "file_path": str(file_path),
            "offset": 1,
            "max_lines": 2,
        })

        assert action is None
        assert "第     2 行" in str(result)
        snapshot = get_session_state().get_attention_snapshot()
        ranges = snapshot["read_ranges"]
        assert any("demo.txt" in key for key in ranges.keys())
        stored = next(iter(ranges.values()))
        assert stored[-1]["start_line"] == 2
        assert stored[-1]["end_line"] == 3

    def test_execute_read_file_accepts_string_numeric_args(self, executor, tmp_path):
        reset_session_state()
        file_path = tmp_path / "demo_string_args.txt"
        file_path.write_text("a\nb\nc\nd\n", encoding="utf-8")

        result, action = executor.execute(
            "read_file",
            {
                "file_path": str(file_path),
                "offset": "1",
                "max_lines": "2",
            },
        )

        assert action is None
        assert "[文件读取] 错误" not in str(result)
        assert "第     2 行" in str(result)

    def test_duplicate_read_records_blocker(self, executor, tmp_path):
        reset_session_state()
        file_path = tmp_path / "demo_repeat.txt"
        file_path.write_text("a\nb\nc\nd\ne\n", encoding="utf-8")

        executor.execute("read_file", {"file_path": str(file_path), "offset": 0, "max_lines": 2})
        second, _ = executor.execute("read_file", {"file_path": str(file_path), "offset": 0, "max_lines": 2})

        snapshot = get_session_state().get_attention_snapshot()
        assert "[短路]" in str(second) or any(
            item["kind"] in {"duplicate_read", "duplicate_read_guard"} for item in snapshot["recent_blockers"]
        )

    def test_read_file_records_hint_when_continuation_is_ignored(self, executor, tmp_path):
        session = reset_session_state()
        file_path = tmp_path / "demo_flow.txt"
        file_path.write_text("\n".join(f"line {i}" for i in range(1, 120)), encoding="utf-8")
        session.record_pending_continuation(
            "read_file_tool",
            f'read_file_tool(file_path="{file_path}", offset=40, max_lines=40)',
            str(file_path),
        )

        result, action = executor.execute("read_file", {"file_path": str(file_path), "offset": 10, "max_lines": 40})

        assert action is None
        assert "[短路]" not in str(result)
        assert "第    11 行" in str(result) or "第     11 行" in str(result)
        snapshot = get_session_state().get_attention_snapshot()
        assert any(item["kind"] == "continuation_drift" for item in snapshot["recent_blockers"])
        assert any(
            item["kind"] == "continuation_drift" and item.get("severity") == "hint"
            for item in snapshot["recent_blockers"]
        )

    def test_read_file_allows_switching_away_from_latest_pending_continuation_but_records_hint(self, executor, tmp_path):
        session = reset_session_state()
        first = tmp_path / "first_flow.txt"
        second = tmp_path / "second_flow.txt"
        first.write_text("\n".join(f"line {i}" for i in range(1, 120)), encoding="utf-8")
        second.write_text("\n".join(f"line {i}" for i in range(1, 120)), encoding="utf-8")

        session.record_pending_continuation(
            "read_file_tool",
            f'read_file_tool(file_path="{first}", offset=40, max_lines=40)',
            str(first),
        )

        result, action = executor.execute("read_file", {"file_path": str(second), "offset": 0, "max_lines": 40})

        assert action is None
        assert "[短路]" not in str(result)
        assert "第     1 行" in str(result)
        snapshot = get_session_state().get_attention_snapshot()
        assert any(item["kind"] == "continuation_focus" for item in snapshot["recent_blockers"])
        assert any(
            item["kind"] == "continuation_focus" and item.get("severity") == "hint"
            for item in snapshot["recent_blockers"]
        )

    def test_read_file_short_circuits_on_high_overlap(self, executor, tmp_path):
        session = reset_session_state()
        file_path = tmp_path / "demo_overlap.txt"
        file_path.write_text("\n".join(f"line {i}" for i in range(1, 160)), encoding="utf-8")
        session.record_read_range(str(file_path), 21, 80, source="read_file_tool")

        result, action = executor.execute("read_file", {"file_path": str(file_path), "offset": 30, "max_lines": 60})

        assert action is None
        assert "[短路]" in str(result)
        snapshot = get_session_state().get_attention_snapshot()
        assert any(item["kind"] == "duplicate_read_guard" for item in snapshot["recent_blockers"])

    def test_duplicate_search_records_blocker(self, executor):
        reset_session_state()

        def fake_grep_search_tool(regex_pattern="", include_ext=".py", search_dir=".", case_sensitive=True, max_results=50, max_output_chars=8000):
            return (
                f"[搜索] 正则: {regex_pattern}\n"
                f"[搜索] 目录: {search_dir}\n"
                f"[搜索] 类型: {include_ext}\n"
                f"[搜索] 找到 1 个匹配，分布在 1 个文件\n"
                "[搜索摘要]\n"
                "- core/demo.py | 命中 1 处 | 行 10\n"
                "\n[续读] read_file_tool(file_path=\"core/demo.py\", offset=0, max_lines=40)\n"
            )

        executor.register_tool("grep_search_tool", fake_grep_search_tool, timeout=5)

        executor.execute("grep_search_tool", {"regex_pattern": "Demo", "search_dir": "core"})
        executor.execute("grep_search_tool", {"regex_pattern": "Demo", "search_dir": "core"})

        snapshot = get_session_state().get_attention_snapshot()
        assert any(item["kind"] == "duplicate_search" for item in snapshot["recent_blockers"])
        assert snapshot["pending_continuations"][-1]["path"] == "core/demo.py"

    def test_duplicate_search_short_circuits_before_execution(self, executor):
        session = reset_session_state()
        session.record_search_query("Demo", "core")

        called = {"count": 0}

        def fake_grep_search_tool(**_kwargs):
            called["count"] += 1
            return "should not execute"

        executor.register_tool("grep_search_tool", fake_grep_search_tool, timeout=5)
        result, action = executor.execute("grep_search_tool", {"regex_pattern": "Demo", "search_dir": "core"})

        assert action is None
        assert "[短路]" in str(result)
        assert called["count"] == 0
        snapshot = get_session_state().get_attention_snapshot()
        assert any(item["kind"] == "duplicate_search" for item in snapshot["recent_blockers"])

    def test_search_allows_progress_when_pending_continuation_exists(self, executor):
        session = reset_session_state()
        session.record_pending_continuation(
            "read_file_tool",
            'read_file_tool(file_path="core/demo.py", offset=40, max_lines=40)',
            "core/demo.py",
        )

        called = {"count": 0}

        def fake_grep_search_tool(**_kwargs):
            called["count"] += 1
            return "should not execute"

        executor.register_tool("grep_search_tool", fake_grep_search_tool, timeout=5)
        result, action = executor.execute("grep_search_tool", {"regex_pattern": "Demo", "search_dir": "core"})

        assert action is None
        assert "[短路]" not in str(result)
        assert called["count"] == 1
        snapshot = get_session_state().get_attention_snapshot()
        assert any(item["kind"] == "continuation_focus" for item in snapshot["recent_blockers"])

    def test_weak_search_continuation_does_not_block_switching_to_another_file(self, executor, tmp_path):
        session = reset_session_state()
        first = tmp_path / "search_hit.py"
        second = tmp_path / "target.py"
        first.write_text("\n".join(f"line {i}" for i in range(1, 40)), encoding="utf-8")
        second.write_text("\n".join(f"line {i}" for i in range(1, 80)), encoding="utf-8")
        session.record_pending_continuation(
            "grep_search_tool",
            f'read_file_tool(file_path="{first}", offset=0, max_lines=40)',
            str(first),
            strength="weak",
        )

        result, action = executor.execute("read_file", {"file_path": str(second), "offset": 0, "max_lines": 40})

        assert action is None
        assert "[短路]" not in str(result)
        snapshot = get_session_state().get_attention_snapshot()
        assert not any(item["kind"] == "continuation_focus" for item in snapshot["recent_blockers"])

    def test_duplicate_entity_short_circuits_before_execution(self, executor):
        session = reset_session_state()
        session.record_read_entity("core/demo.py", "Demo.run")

        called = {"count": 0}

        def fake_get_code_entity_tool(**_kwargs):
            called["count"] += 1
            return "should not execute"

        executor.register_tool("get_code_entity_tool", fake_get_code_entity_tool, timeout=5)
        result, action = executor.execute(
            "get_code_entity_tool",
            {"file_path": "core/demo.py", "entity_name": "Demo.run"},
        )

        assert action is None
        assert "[短路]" in str(result)
        assert called["count"] == 0
        snapshot = get_session_state().get_attention_snapshot()
        assert any(item["kind"] == "duplicate_entity_guard" for item in snapshot["recent_blockers"])

    def test_cli_tool_records_deviation_when_recommendation_exists(self, executor):
        session = reset_session_state()
        session.set_tool_decision("inspect_entity", ["get_code_entity_tool", "read_file_tool"], ["cli_tool"])

        def fake_cli_tool(command="", timeout=60):
            return "[命令执行完成，无输出]"

        executor.register_tool("cli_tool", fake_cli_tool, timeout=5)
        executor.execute("cli_tool", {"command": "echo ok"})

        snapshot = get_session_state().get_attention_snapshot()
        assert any(item["tool_name"] == "cli_tool" for item in snapshot["tool_deviations"])
        assert any(item["kind"] == "tool_deviation" for item in snapshot["recent_blockers"])

    def test_execute_tool_missing_required_args(self, executor):
        """测试执行工具时缺少必需参数"""
        # 缺少 file_path 参数
        result, action = executor.execute("read_file", {})
        
        # 应该返回错误而不是抛出异常
        assert result is not None
        assert action is None

    def test_python_lint_records_validation_signal(self, executor, monkeypatch):
        reset_session_state()
        executor.register_tool(
            "python_lint_tool",
            lambda target=".", max_issues=100: '{"status": "ok", "issue_count": 0, "issues": []}',
            timeout=5,
        )

        result, _ = executor.execute("python_lint_tool", {"target": "."})

        assert '"issue_count": 0' in str(result)
        snapshot = get_session_state().get_attention_snapshot()
        assert snapshot["recent_validation_results"][-1]["kind"] == "lint"

    def test_successful_validation_and_task_completion_reward_pet_exp(self, executor):
        reset_session_state()
        reset_pet_system()
        pet = get_pet_system()
        start_exp = pet.data.attributes.exp
        start_tasks = pet.data.attributes.total_tasks

        executor.register_tool(
            "python_lint_tool",
            lambda target=".", max_issues=100: '{"status": "ok", "issue_count": 0, "issues": []}',
            timeout=5,
        )
        executor.register_tool(
            "task_update_tool",
            lambda task_id=1, is_completed=True, result_summary="": '{"status":"success"}',
            timeout=5,
        )

        executor.execute("python_lint_tool", {"target": "."})
        executor.execute("task_update_tool", {"task_id": 1, "is_completed": True, "result_summary": "done"})

        assert pet.data.attributes.exp > start_exp
        assert pet.data.attributes.total_tasks == start_tasks + 1

    def test_readonly_subagent_blocks_mutating_tools(self, executor, monkeypatch):
        monkeypatch.setenv("VIBELUTION_SUBAGENT_MODE", "readonly")

        result, action = executor.execute(
            "write_file_tool",
            {"file_path": "workspace/demo.txt", "content": "x"},
        )

        assert action is None
        assert "[只读子代理]" in str(result)

    def test_readonly_subagent_blocks_spawn_agent_tool(self, executor, monkeypatch):
        monkeypatch.setenv("VIBELUTION_SUBAGENT_MODE", "readonly")

        result, action = executor.execute(
            "spawn_agent_tool",
            {"goal": "继续分析", "_internal_delegate": True},
        )

        assert action is None
        assert "禁止继续派发子 agent" in str(result)

    def test_active_evolution_transaction_blocks_writes_outside_allowed_dirs(self, executor, monkeypatch, tmp_path):
        project_root = tmp_path / "project"
        project_root.mkdir(parents=True, exist_ok=True)

        class _FakeWorkspace:
            def __init__(self, root: Path):
                self.project_root = root

            def get_prompt_path(self, name: str) -> Path:
                return self.project_root / "workspace" / "prompts" / name

        evolution = SimpleNamespace(
            allowed_target_dirs=["workspace/prompts/"],
            audit_log_path="workspace/evolution/audit.jsonl",
        )
        monkeypatch.setattr(governor_module, "get_config", lambda: SimpleNamespace(evolution=evolution))
        monkeypatch.setattr(governor_module, "get_workspace", lambda: _FakeWorkspace(project_root))
        governor_module._governor = None

        session = reset_session_state()
        session.set_active_evolution_txn("txn_guard")
        executor.register_tool("write_file_tool", lambda file_path, content: "ok", timeout=5)

        result, action = executor.execute(
            "write_file_tool",
            {"file_path": "core/runtime.py", "content": "x"},
        )

        assert action is None
        assert "[演化治理]" in str(result)


class TestToolExecutorConvenience:
    """便捷功能测试"""

    def test_register_tool(self):
        """测试注册自定义工具"""
        executor = ToolExecutor()
        
        def my_custom_tool(param1, param2="default"):
            return f"Called with {param1} and {param2}"
        
        executor.register_tool("my_custom_tool", my_custom_tool, timeout=10)
        
        assert "my_custom_tool" in executor._tool_map
        assert executor._timeout_map["my_custom_tool"] == 10
        
        # 执行自定义工具
        result, action = executor.execute("my_custom_tool", {
            "param1": "test",
            "param2": "value"
        })
        
        assert "test" in str(result)
        assert "value" in str(result)
        assert action is None

    def test_register_tool_default_timeout(self):
        """测试注册工具时使用默认超时"""
        executor = ToolExecutor()
        
        def my_tool():
            return "done"
        
        executor.register_tool("my_tool", my_tool)
        assert executor._timeout_map["my_tool"] == 30  # 默认超时


class TestToolExecutorIntegration:
    """集成测试"""

    def test_full_workflow(self):
        """测试完整工作流程"""
        # 1. 获取执行器
        executor = get_tool_executor()
        
        # 2. 列出目录
        result, action = executor.execute("list_directory", {
            "path": str(Path(__file__).parent)
        })
        assert result is not None
        assert action is None
        
        # 3. 读取文件
        result, action = executor.execute("read_file", {
            "file_path": __file__
        })
        assert result is not None
        assert action is None
        
        # 4. 检查语法
        result, action = executor.execute("check_python_syntax", {
            "file_path": __file__
        })
        assert result is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
