#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
工具执行器模块

负责：
- 管理工具函数映射
- 通过事件总线解耦工具执行
- 提供工具超时和重试机制
"""

from __future__ import annotations

import os
import re
import threading
import time
from typing import Dict, Callable, Any, Optional
from concurrent.futures import ThreadPoolExecutor, TimeoutError

# 核心模块导入
from core.infrastructure.event_bus import get_event_bus, EventNames
from core.infrastructure.agent_session import get_session_state
from core.infrastructure.evolution_governor import get_evolution_governor
from core.infrastructure.llm_utils import parse_tool_args
from core.infrastructure.tool_recommender import decide_next_tools


class ToolExecutor:
    """
    工具执行器

    负责管理所有工具的注册、执行、超时和重试。
    """

    def __init__(self):
        self._tool_map: Dict[str, Callable] = {}
        self._timeout_map: Dict[str, int] = {}
        self._retryable_tools: set = set()
        self._event_bus = get_event_bus()
        self._cancel_checker: Optional[Callable[[], str]] = None
        self._cancel_checker_owner: Any = None
        self._cancel_checker_lock = threading.Lock()
        self._register_default_tools()

    _READ_ONLY_BLOCKED_TOOLS = {
        "spawn_agent_tool",
        "apply_diff_edit_tool",
        "write_file_tool",
        "create_file",
        "create_file_tool",
        "write_dynamic_prompt_tool",
        "add_insight_to_dynamic_tool",
        "commit_compressed_memory_tool",
        "record_learning_tool",
        "trigger_self_restart_tool",
        "enter_hibernation_tool",
        "open_evolution_transaction_tool",
        "close_evolution_transaction_tool",
        "execute_shell_command",
        "execute_shell_command_tool",
        "run_powershell",
        "run_powershell_tool",
        "run_batch",
        "run_batch_tool",
        "cli_tool",
        "task_create_tool",
        "task_update_tool",
        "task_start_tool",
        "task_stop_tool",
        "compress_context_tool",
    }

    def _register_default_tools(self):
        """注册默认工具映射 — Key_Tools 工具自动推导，程序化工具手动注册"""
        from tools import (
            list_directory_tool,
            check_python_syntax_tool, extract_symbols_tool, backup_project_tool,
            cleanup_test_files_tool, execute_shell_command_tool, run_powershell_tool,
            run_batch_tool, self_test_tool, get_agent_status_tool,
            read_file_tool, create_file_tool, glob_files_tool,
            read_memory_tool,
            get_current_goal_tool, get_core_context_tool,
            read_dynamic_prompt_tool,
            add_insight_to_dynamic_tool,
            get_memory_summary_tool, write_dynamic_prompt_tool,
            find_function_calls_tool, find_definitions_tool,
            search_imports_tool, search_and_read_tool,
            preview_diff_tool, get_file_entities_tool,
            spawn_agent_tool,
            python_symbol_tool, python_lint_tool,
        )
        from core.infrastructure.mental_model import (
            get_mental_state_tool, update_diagnosis_rules_tool,
            update_self_model_tool, get_self_model_tool, record_evolution_tool,
        )

        # ── 从 Key_Tools 自动推导工具映射 ──────────────────────────────
        from tools.Key_Tools import create_key_tools
        for tool in create_key_tools():
            self._tool_map[tool.name] = tool.func

        # ── 程序化工具手动注册 (不对 LLM 暴露) ─────────────────────────
        self._tool_map.update({
            "list_directory": list_directory_tool,
            "check_python_syntax": check_python_syntax_tool,
            "extract_symbols": extract_symbols_tool,
            "backup_project": backup_project_tool,
            "cleanup_test_files": cleanup_test_files_tool,
            "execute_shell_command": execute_shell_command_tool,
            "run_powershell": run_powershell_tool,
            "run_batch": run_batch_tool,
            "self_test": self_test_tool,
            "get_agent_status": get_agent_status_tool,
            "read_file": read_file_tool,
            "create_file": create_file_tool,
            "glob_files": glob_files_tool,
            "read_memory": read_memory_tool,
            "get_current_goal": get_current_goal_tool,
            "get_core_context": get_core_context_tool,
            "read_dynamic_prompt": read_dynamic_prompt_tool,
            "add_insight_to_dynamic": add_insight_to_dynamic_tool,
            "get_memory_summary": get_memory_summary_tool,
            "write_dynamic_prompt": write_dynamic_prompt_tool,
            "find_function_calls": find_function_calls_tool,
            "find_definitions": find_definitions_tool,
            "search_imports": search_imports_tool,
            "search_and_read": search_and_read_tool,
            "preview_diff": preview_diff_tool,
            "get_file_entities": get_file_entities_tool,
            "get_file_entities_tool": get_file_entities_tool,
            # 只供主 agent 调度层内部使用，不向 LLM 工具目录暴露。
            "spawn_agent_tool": spawn_agent_tool,
            "python_symbol": python_symbol_tool,
            "python_lint": python_lint_tool,
            # 心智模型工具
            "get_mental_state": get_mental_state_tool,
            "update_diagnosis_rules": update_diagnosis_rules_tool,
            "update_self_model": update_self_model_tool,
            "get_self_model": get_self_model_tool,
            "record_evolution": record_evolution_tool,
        })

        self._timeout_map = {
            "execute_shell_command": 60,
            "run_powershell": 60,
            "run_batch": 60,
            "self_test": 30,
            "check_python_syntax": 10,
            "grep_search_tool": 30,
            "find_function_calls": 30,
            "find_definitions": 30,
            "search_and_read": 30,
            "backup_project": 60,
            "web_search_tool": 30,
            "python_symbol_tool": 30,
            "python_lint_tool": 60,
            "spawn_agent_tool": 150,
        }
        self._retryable_tools = {"grep_search_tool", "search_and_read"}

    def register_tool(self, name: str, func: Callable, timeout: int = 30):
        """注册自定义工具"""
        self._tool_map[name] = func
        self._timeout_map[name] = timeout

    def set_cancel_checker(
        self,
        checker: Optional[Callable[[], str]] = None,
        *,
        owner: Any = None,
    ) -> None:
        """Attach the current turn cancellation checker to tool execution."""

        with self._cancel_checker_lock:
            if checker is None:
                if owner is None or self._cancel_checker_owner is owner:
                    self._cancel_checker = None
                    self._cancel_checker_owner = None
                return
            self._cancel_checker = checker
            self._cancel_checker_owner = owner if owner is not None else checker

    def _snapshot_cancel_checker(self) -> Optional[Callable[[], str]]:
        with self._cancel_checker_lock:
            return self._cancel_checker

    def _current_cancel_reason(self, checker: Optional[Callable[[], str]] = None) -> str:
        if checker is None:
            checker = self._snapshot_cancel_checker()
        if not callable(checker):
            return ""
        try:
            return str(checker() or "").strip()
        except Exception:
            return ""

    def execute(self, tool_name: str, tool_args: dict) -> tuple:
        """
        执行工具

        Args:
            tool_name: 工具名称
            tool_args: 工具参数字典

        Returns:
            (result, action): 元组
                result: 工具执行结果
                action: 特殊动作 (如 "restart", "hibernated", None)
        """
        tool_args = parse_tool_args(tool_args or {})

        readonly_block = self._check_readonly_subagent_block(tool_name)
        if readonly_block:
            self._event_bus.publish(EventNames.TOOL_ERROR, {
                "name": tool_name,
                "error": readonly_block,
            })
            return (readonly_block, None)

        blocked_message = self._check_runtime_block(tool_name, tool_args)
        if blocked_message:
            self._event_bus.publish(EventNames.TOOL_ERROR, {
                "name": tool_name,
                "error": blocked_message,
            })
            return (blocked_message, None)

        self._track_tool_decision_alignment(tool_name)

        # 发布工具开始事件
        self._event_bus.publish(EventNames.TOOL_START, {
            "name": tool_name,
            "args": tool_args,
        })

        if tool_name not in self._tool_map:
            error_msg = f"[错误] 未知工具 {tool_name}"
            self._event_bus.publish(EventNames.TOOL_ERROR, {
                "name": tool_name,
                "error": error_msg,
            })
            return (error_msg, None)

        func = self._tool_map[tool_name]
        timeout = self._resolve_timeout(tool_name, tool_args)
        call_args = dict(tool_args or {})
        # 内部治理哨兵只用于执行权限判断，不能透传给真实工具函数。
        call_args.pop("_internal_delegate", None)
        cancel_checker = self._snapshot_cancel_checker()
        if tool_name == "spawn_agent_tool" and "_cancel_checker" not in call_args:
            call_args["_cancel_checker"] = lambda: self._current_cancel_reason(cancel_checker)

        executor = ThreadPoolExecutor(max_workers=1)
        future = None

        try:
            cancel_reason = self._current_cancel_reason(cancel_checker)
            if cancel_reason:
                error_msg = f"[取消] {tool_name} 已因停止请求跳过执行：{cancel_reason}"
                self._event_bus.publish(EventNames.TOOL_ERROR, {
                    "name": tool_name,
                    "error": error_msg,
                })
                return (error_msg, None)
            future = executor.submit(func, **call_args)
            deadline = time.monotonic() + max(float(timeout), 0.1)
            while True:
                cancel_reason = self._current_cancel_reason(cancel_checker)
                if cancel_reason:
                    future.cancel()
                    executor.shutdown(wait=False, cancel_futures=True)
                    error_msg = f"[取消] {tool_name} 已因停止请求中断：{cancel_reason}"
                    self._event_bus.publish(EventNames.TOOL_ERROR, {
                        "name": tool_name,
                        "error": error_msg,
                    })
                    self._record_runtime_signals(tool_name, tool_args, error_msg)
                    return (error_msg, None)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError()
                try:
                    result = future.result(timeout=min(0.2, remaining))
                    cancel_reason = self._current_cancel_reason(cancel_checker)
                    if cancel_reason:
                        error_msg = f"[取消] {tool_name} 已因停止请求中断：{cancel_reason}"
                        self._event_bus.publish(EventNames.TOOL_ERROR, {
                            "name": tool_name,
                            "error": error_msg,
                        })
                        self._record_runtime_signals(tool_name, tool_args, error_msg)
                        return (error_msg, None)
                    break
                except TimeoutError:
                    continue

            # 发布工具成功事件
            self._event_bus.publish(EventNames.TOOL_SUCCESS, {
                "name": tool_name,
                "result": str(result)[:200],
            })

            self._record_runtime_signals(tool_name, tool_args, result)

            # ── 自动更新代码库地图（检测文件修改工具）──
            self._try_auto_update_map(tool_name, tool_args)

            executor.shutdown(wait=False, cancel_futures=False)
            return (result, None)

        except TimeoutError:
            if future is not None:
                future.cancel()
            executor.shutdown(wait=False, cancel_futures=True)
            error_msg = f"[超时] {tool_name} 执行超时 ({timeout}秒)"
            self._event_bus.publish(EventNames.TOOL_ERROR, {
                "name": tool_name,
                "error": error_msg,
            })
            self._record_runtime_signals(tool_name, tool_args, error_msg)
            return (error_msg, None)

        except Exception as e:
            executor.shutdown(wait=False, cancel_futures=True)
            error_msg = f"[错误] {type(e).__name__}: {e}"
            self._event_bus.publish(EventNames.TOOL_ERROR, {
                "name": tool_name,
                "error": error_msg,
            })
            self._record_runtime_signals(tool_name, tool_args, error_msg)
            return (error_msg, None)

    def _resolve_timeout(self, tool_name: str, tool_args: dict) -> int:
        timeout = self._timeout_map.get(tool_name, 30)
        requested = (tool_args or {}).get("timeout")
        try:
            requested_int = int(requested)
        except (TypeError, ValueError):
            requested_int = 0

        # 除 spawn_agent_tool 外，其它工具允许按调用方显式拉长超时。
        if tool_name != "spawn_agent_tool":
            if requested_int > 0:
                return max(timeout, requested_int)
            return timeout

        if requested_int <= 0:
            return timeout

        # 给外层线程执行器留一点缓冲，避免子进程还在收尾时外层先误杀。
        return max(timeout, requested_int + 15)

    @classmethod
    def _check_readonly_subagent_block(cls, tool_name: str) -> Optional[str]:
        if os.environ.get("VIBELUTION_SUBAGENT_MODE", "").strip().lower() != "readonly":
            return None
        if tool_name not in cls._READ_ONLY_BLOCKED_TOOLS:
            return None
        if tool_name == "spawn_agent_tool":
            return "[只读子代理] 当前子 agent 运行在只读模式，禁止继续派发子 agent。"
        return f"[只读子代理] 当前子 agent 运行在只读模式，禁止调用 `{tool_name}`。"

    def _check_runtime_block(self, tool_name: str, tool_args: dict) -> Optional[str]:
        """检查当前轮次是否已记录同类失败模式。"""
        session = get_session_state()
        spawn_block = self._check_spawn_agent_permission(tool_name, tool_args)
        if spawn_block:
            return spawn_block
        duplicate_block = self._check_duplicate_intent_block(session, tool_name, tool_args)
        if duplicate_block:
            return duplicate_block
        focus_block = self._check_attention_focus_block(session, tool_name, tool_args)
        if focus_block:
            return focus_block
        read_block = self._check_read_path_guard(session, tool_name, tool_args)
        if read_block:
            return read_block
        evolution_block = self._check_evolution_mutation_guard(session, tool_name, tool_args)
        if evolution_block:
            return evolution_block
        pattern = self._detect_tool_pattern(tool_name, tool_args)
        if not pattern:
            return None
        blocked = session.get_blocked_tool_pattern(pattern)
        if not blocked:
            return None
        hint = blocked.get("hint", "")
        suffix = f" 建议改用：{hint}" if hint else ""
        return f"[短路] {pattern} 本轮已被阻塞：{blocked.get('reason', '')}.{suffix}"

    @staticmethod
    def _check_evolution_mutation_guard(session, tool_name: str, tool_args: dict) -> Optional[str]:
        governor = get_evolution_governor()
        return governor.check_mutation_allowed(
            tool_name=tool_name,
            tool_args=tool_args or {},
            active_txn_id=session.get_active_evolution_txn(),
        )

    @staticmethod
    def _check_spawn_agent_permission(tool_name: str, tool_args: dict) -> Optional[str]:
        """禁止 LLM 直接调用子 agent；只允许主脑调度层显式放行。"""
        if tool_name != "spawn_agent_tool":
            return None
        if os.environ.get("VIBELUTION_SUBAGENT_MODE", "").strip().lower() == "readonly":
            return "[只读子代理] 当前子 agent 运行在只读模式，禁止继续派发子 agent。"
        if (tool_args or {}).get("_internal_delegate") is True:
            return None
        return "[短路] spawn_agent_tool 仅允许主 agent 的委派治理层内部调用，不能直接作为普通工具发起。"

    @staticmethod
    def _parse_pending_read_hint(hint: str) -> tuple[str, int, int] | None:
        if not hint:
            return None
        match = re.search(r'file_path="([^"]+)".*offset=(\d+).*max_lines=(\d+)', hint)
        if not match:
            return None
        return match.group(1), int(match.group(2)), int(match.group(3))

    @classmethod
    def _check_attention_focus_block(cls, session, tool_name: str, tool_args: dict) -> Optional[str]:
        """存在未完成续读时，记录偏离提示，但不再强制短路。"""
        latest_pending = session.get_latest_pending_continuation()
        if not latest_pending:
            return None

        if str(latest_pending.get("strength") or "strong") != "strong":
            return None

        pending_hint = str(latest_pending.get("hint") or "").strip()
        pending_path = str(latest_pending.get("path") or "").replace("\\", "/")
        parsed = cls._parse_pending_read_hint(pending_hint)
        if not pending_hint or not pending_path or not parsed:
            return None

        _, expected_offset, expected_max_lines = parsed
        if tool_name in {"grep_search_tool", "list_file_entities_tool", "get_file_entities"}:
            session.record_blocker(
                "continuation_focus",
                f"当前已存在 {pending_path} 的未完成续读，不应回退到 {tool_name}。",
                f"先执行 read_file_tool(file_path=\"{pending_path}\", offset={expected_offset}, max_lines={expected_max_lines})",
                severity="hint",
            )
            return None

        if tool_name == "get_code_entity_tool":
            file_path = str((tool_args or {}).get("file_path") or "").replace("\\", "/")
            if not file_path or file_path != pending_path:
                session.record_blocker(
                    "continuation_focus",
                    f"当前优先续读目标是 {pending_path}，不应切换到新的实体读取。",
                    f"先执行 read_file_tool(file_path=\"{pending_path}\", offset={expected_offset}, max_lines={expected_max_lines})",
                    severity="hint",
                )
                return None
        return None

    @staticmethod
    def _check_duplicate_intent_block(session, tool_name: str, tool_args: dict) -> Optional[str]:
        """对同轮完全重复的搜索/实体读取做前置短路。"""
        if tool_name == "grep_search_tool":
            query = str((tool_args or {}).get("regex_pattern") or "")
            scope = str((tool_args or {}).get("search_dir") or "")
            if query and session.has_search_query(query, scope):
                session.record_blocker(
                    "duplicate_search",
                    f"{query} 在 {scope or '.'} 中本轮已搜索过，无需重复搜索。",
                    "改读已命中文件、缩小范围，或直接开始修改/验证",
                )
                return (
                    f"[短路] {query} 在 {scope or '.'} 中本轮已搜索过。"
                    " 建议改用：read_file_tool 读取已命中文件，或更换关键词/缩小范围。"
                )

        if tool_name == "get_code_entity_tool":
            file_path = str((tool_args or {}).get("file_path") or "")
            entity = str((tool_args or {}).get("entity_name") or "")
            normalized = file_path.replace("\\", "/")
            if file_path and entity and session.has_read_entity(file_path, entity):
                session.record_blocker(
                    "duplicate_entity_guard",
                    f"{entity} 在 {normalized} 中本轮已读过，无需重复读取。",
                    "改读调用点、相邻上下文，或直接进入修改/验证",
                )
                return (
                    f"[短路] {entity} 在当前轮次已读取过。"
                    " 建议改用：读取相邻上下文、调用点，或直接开始修改/验证。"
                )
        return None

    @classmethod
    def _check_read_path_guard(cls, session, tool_name: str, tool_args: dict) -> Optional[str]:
        if tool_name not in {"read_file_tool", "read_file"}:
            return None
        file_path = str((tool_args or {}).get("file_path") or "")
        if not file_path:
            return None
        normalized_file_path = file_path.replace("\\", "/")
        offset = int((tool_args or {}).get("offset") or 0)
        max_lines = int((tool_args or {}).get("max_lines") or 0)
        start_line = offset + 1
        end_line = offset + max_lines if max_lines > 0 else offset

        latest_pending = session.get_latest_pending_continuation()
        if latest_pending:
            if str(latest_pending.get("strength") or "strong") != "strong":
                latest_pending = None
        if latest_pending:
            parsed_latest = cls._parse_pending_read_hint(str(latest_pending.get("hint") or ""))
            latest_path = str(latest_pending.get("path") or "")
            if parsed_latest and latest_path:
                _, latest_offset, latest_max_lines = parsed_latest
                if normalized_file_path != latest_path:
                    session.record_blocker(
                        "continuation_focus",
                        f"当前优先续读目标是 {latest_path} offset={latest_offset}，不应切换到 {file_path} offset={offset}。",
                        f"先执行 read_file_tool(file_path=\"{latest_path}\", offset={latest_offset}, max_lines={latest_max_lines})",
                        severity="hint",
                    )
                    return None

        pending = session.get_latest_pending_continuation(normalized_file_path)
        if pending:
            parsed = cls._parse_pending_read_hint(str(pending.get("hint") or ""))
            if parsed:
                _, expected_offset, expected_max_lines = parsed
                if offset != expected_offset:
                    session.record_blocker(
                        "continuation_drift",
                        f"{file_path} 存在未完成续读，应从 offset={expected_offset} 开始，而不是 {offset}。",
                        f"先执行 read_file_tool(file_path=\"{file_path}\", offset={expected_offset}, max_lines={expected_max_lines})",
                        severity="hint",
                    )
                    return None

        if max_lines >= 40:
            overlaps = session.get_overlapping_read_ranges(normalized_file_path, start_line, end_line)
            for item in overlaps:
                existing_start = int(item.get("start_line", 0))
                existing_end = int(item.get("end_line", 0))
                overlap_start = max(existing_start, start_line)
                overlap_end = min(existing_end, end_line)
                overlap_size = max(0, overlap_end - overlap_start + 1)
                request_size = max(1, end_line - start_line + 1)
                if overlap_size / request_size >= 0.6:
                    session.record_blocker(
                        "duplicate_read_guard",
                        f"{file_path} 第 {start_line}-{end_line} 行与已读区间 {existing_start}-{existing_end} 高度重叠。",
                        "优先顺着续读继续，或缩小到尚未读取的相邻区间"
                    )
                    return (
                        f"[短路] 当前读取区间与已读内容高度重叠（{existing_start}-{existing_end}）。"
                        " 建议改用：顺着上一条续读继续，或缩小到未读相邻区间。"
                    )
        return None

    def _record_runtime_signals(self, tool_name: str, tool_args: dict, result: Any) -> None:
        """把工具执行结果转成会话级短期约束。"""
        session = get_session_state()
        result_text = str(result or "")
        pattern = self._detect_tool_pattern(tool_name, tool_args)
        pet = None
        try:
            from core.pet_system import get_pet_system
            pet = get_pet_system()
        except Exception:
            pet = None

        if "[安全拦截]" in result_text and pattern:
            hint = self._pattern_hint(pattern)
            session.record_blocked_tool_pattern(pattern, "安全策略已拦截该模式", hint)
            session.record_blocker("security_block", f"{tool_name} 触发 `{pattern}` 安全拦截", hint)

        command = str((tool_args or {}).get("command") or "")
        if tool_name in {"run_test_for_tool", "cli_tool"} and ("pytest" in command or tool_name == "run_test_for_tool"):
            is_cross_platform_warning = "[跨平台警告]" in result_text
            passed = (
                not is_cross_platform_warning
                and "[运行测试] 未找到对应测试文件" not in result_text
                and ("passed" in result_text.lower() or "PASSED" in result_text)
            )
            summary = "pytest 通过" if passed else result_text[:200]
            if tool_name == "run_test_for_tool" and "未找到对应测试文件" in result_text:
                summary = "未找到映射测试文件，已退回手动 pytest"
            if is_cross_platform_warning:
                platform_summary = "Windows 平台检查通过：已拦截 Unix shell 片段"
                session.record_blocked_tool_pattern(
                    "cli_tool:unix_shell_on_windows",
                    "跨平台检查已拦截 Unix shell 片段",
                    "改用 PowerShell 等价命令或结构化工具",
                )
                session.record_blocker(
                    "cross_platform_command",
                    summary,
                    "改用 PowerShell 等价命令或结构化工具",
                    severity="hint",
                )
                session.record_validation_result(platform_summary, True, kind="platform_check")
                session.note_feedback_loop(
                    loop_type="platform_check",
                    target=command or "Windows shell compatibility",
                    result=platform_summary,
                    phase="observe",
                )
                session.note_scope_completion("平台兼容性已完成最小验证，直接给出结论。")
                self._event_bus.publish(EventNames.VALIDATION_COMPLETED, {
                    "kind": "platform_check",
                    "passed": True,
                    "message": platform_summary,
                })
                if pet:
                    pet.reward_validation("platform_check", True)
            else:
                session.record_validation_result(summary, passed, kind="tests")
                session.note_feedback_loop(
                    loop_type="tests",
                    target=command or "pytest",
                    result=summary,
                    phase="reproduce",
                )
                session.set_diagnostic_phase("reproduce")
                self._event_bus.publish(EventNames.VALIDATION_COMPLETED, {
                    "kind": "tests",
                    "passed": passed,
                    "message": summary,
                })
                if pet and passed:
                    pet.reward_validation("tests", True)
        elif tool_name == "cli_tool" and "py_compile" in command:
            passed = "[命令执行完成，无输出]" in result_text
            session.record_validation_result("python -m py_compile 通过" if passed else result_text[:200], passed, kind="compile")
            session.note_feedback_loop(
                loop_type="compile",
                target=command or "python -m py_compile",
                result="python -m py_compile 通过" if passed else result_text[:200],
                phase="reproduce",
            )
            session.set_diagnostic_phase("reproduce")
            self._event_bus.publish(EventNames.VALIDATION_COMPLETED, {
                "kind": "compile",
                "passed": passed,
                "message": "python -m py_compile 通过" if passed else result_text[:200],
            })
            if pet and passed:
                pet.reward_validation("compile", True)
        elif tool_name == "python_lint_tool":
            passed = '"status": "ok"' in result_text and '"issue_count": 0' in result_text
            summary = "ruff lint 通过" if passed else result_text[:200]
            session.record_validation_result(summary, passed, kind="lint")
            session.note_feedback_loop(
                loop_type="lint",
                target=str((tool_args or {}).get("file_path") or "python_lint_tool"),
                result=summary,
                phase="reproduce",
            )
            self._event_bus.publish(EventNames.VALIDATION_COMPLETED, {
                "kind": "lint",
                "passed": passed,
                "message": summary,
            })
            if pet and passed:
                pet.reward_validation("lint", True)

        if pet and tool_name == "task_update_tool":
            is_completed = bool((tool_args or {}).get("is_completed"))
            if is_completed:
                pet.reward_task_completion(str((tool_args or {}).get("task_id") or "task"))

        get_evolution_governor().record_mutation_result(
            tool_name=tool_name,
            tool_args=tool_args or {},
            result=result,
            active_txn_id=session.get_active_evolution_txn(),
        )

        reading_signal_tools = {
            "read_file_tool", "read_file", "get_code_entity_tool", "list_file_entities_tool",
            "grep_search_tool", "get_file_entities", "python_symbol_tool", "python_lint_tool",
            "run_test_for_tool", "cli_tool",
        }
        action_phase_tools = {
            "open_evolution_transaction_tool",
            "close_evolution_transaction_tool",
            "trigger_self_restart_tool",
            "write_file_tool",
            "replace_in_file_tool",
            "task_create_tool",
            "task_update_tool",
        }

        if tool_name in {"read_file_tool", "read_file", "get_code_entity_tool", "list_file_entities_tool", "grep_search_tool", "get_file_entities"}:
            session.note_diagnostic_inspection()
            session.note_diagnostic_observation()
        elif tool_name == "python_symbol_tool":
            session.note_diagnostic_inspection()
            session.note_diagnostic_observation("python symbol lookup")

        if session.get_attention_snapshot().get("feedback_loop_ready"):
            if tool_name in {"read_file_tool", "read_file", "get_code_entity_tool", "grep_search_tool", "python_symbol_tool", "python_lint_tool", "run_test_for_tool"}:
                anchor = ""
                if tool_name in {"read_file_tool", "read_file", "python_lint_tool"}:
                    anchor = str((tool_args or {}).get("file_path") or "")
                elif tool_name == "get_code_entity_tool":
                    anchor = str((tool_args or {}).get("entity_name") or "")
                elif tool_name == "grep_search_tool":
                    anchor = str((tool_args or {}).get("regex_pattern") or "")
                elif tool_name == "python_symbol_tool":
                    anchor = str((tool_args or {}).get("symbol") or "")
                session.freeze_scope(anchor or session.get_attention_snapshot().get("feedback_loop_target") or "当前诊断锚点")

        if tool_name in {"read_file_tool", "read_file"}:
            self._record_file_read(session, tool_args, result_text, tool_name)
        elif tool_name == "get_code_entity_tool":
            path = str((tool_args or {}).get("file_path") or "")
            entity = str((tool_args or {}).get("entity_name") or "")
            if path:
                session.clear_pending_continuation(path=path)
            if session.has_read_entity(path, entity):
                session.record_blocker(
                    "duplicate_read",
                    f"{entity} 本轮已读过，除非需要补相邻上下文，否则避免重复读取。",
                    "改读调用点、相邻区间或直接开始修改"
                )
            session.record_read_entity(
                path,
                entity,
            )
        elif tool_name == "grep_search_tool":
            query = str((tool_args or {}).get("regex_pattern") or "")
            scope = str((tool_args or {}).get("search_dir") or "")
            if session.has_search_query(query, scope):
                session.record_blocker(
                    "duplicate_search",
                    f"`{query}` 在 `{scope or '.'}` 中本轮已搜索过。",
                    "缩小范围、换关键词，或直接阅读已命中文件"
                )
            session.record_search_query(
                query,
                scope,
            )
            self._record_search_continuation(session, result_text, tool_name)

        if tool_name in reading_signal_tools:
            sufficiency = session.evaluate_reading_sufficiency()
            if sufficiency:
                session.set_reading_sufficiency(sufficiency)
                if session.get_attention_snapshot().get("scope_frozen") and any(
                    keyword in sufficiency for keyword in ["已足够", "已具备", "可继续修复", "可形成分析结论"]
                ):
                    session.set_convergence_state("ready_to_fix")
            decision = decide_next_tools(session.get_attention_snapshot())
            session.set_tool_decision(decision.next_intent, decision.recommended_tools, decision.avoid_tools)
        elif tool_name in action_phase_tools:
            session.clear_reading_guidance(clear_decision=True)

    def _detect_tool_pattern(self, tool_name: str, tool_args: dict) -> Optional[str]:
        """识别高价值重复失败模式。"""
        if tool_name != "cli_tool":
            return None
        command = str((tool_args or {}).get("command") or "")
        if "&&" in command or "||" in command or ";" in command or "`" in command:
            return "cli_tool:command_chain"
        if "|" in command:
            return "cli_tool:pipe"
        if "$(" in command:
            return "cli_tool:subexpression"
        return None

    @staticmethod
    def _pattern_hint(pattern: str) -> str:
        if pattern == "cli_tool:command_chain":
            return "拆成多个独立工具调用 / 分开执行 python 与 pytest / 使用专用读写工具"
        if pattern == "cli_tool:pipe":
            return "read_file_tool / grep_search_tool / 无 pipe 的 git 子命令"
        if pattern == "cli_tool:subexpression":
            return "read_file_tool / 专用 Python 工具 / 显式参数传递"
        return ""

    @staticmethod
    def _record_file_read(session, tool_args: dict, result_text: str, tool_name: str):
        file_path = str((tool_args or {}).get("file_path") or "")
        if not file_path:
            return
        session.clear_pending_continuation(path=file_path)
        match = re.search(r"\[区间\]\s*第\s*(\d+)-(\d+)\s*行", result_text)
        if match:
            start_line = int(match.group(1))
            end_line = int(match.group(2))
            if session.has_read_range_overlap(file_path, start_line, end_line):
                session.record_blocker(
                    "duplicate_read",
                    f"{file_path} 第 {start_line}-{end_line} 行本轮已读过。",
                    "改读相邻区间、目标实体，或直接开始修改/验证"
                )
            session.record_read_range(file_path, start_line, end_line, source=tool_name)
        else:
            offset = int((tool_args or {}).get("offset") or 0)
            max_lines = int((tool_args or {}).get("max_lines") or 0)
            if max_lines > 0:
                start_line = offset + 1
                end_line = offset + max_lines
                if session.has_read_range_overlap(file_path, start_line, end_line):
                    session.record_blocker(
                        "duplicate_read",
                        f"{file_path} 第 {start_line}-{end_line} 行本轮已读过。",
                        "改读相邻区间、目标实体，或直接开始修改/验证"
                    )
                session.record_read_range(file_path, start_line, end_line, source=tool_name)

        continuation_match = re.search(r"\[续读\]\s*(.+)", result_text)
        if continuation_match:
            session.record_pending_continuation(
                tool_name,
                continuation_match.group(1).strip(),
                file_path,
                strength="strong",
            )

    @staticmethod
    def _track_tool_decision_alignment(tool_name: str):
        session = get_session_state()
        snapshot = session.get_attention_snapshot()
        recommended = snapshot.get("recommended_tools") or []
        avoid = snapshot.get("avoid_tools") or []
        if tool_name in avoid:
            session.record_tool_deviation(tool_name, "当前工具在避免列表中，说明本轮选择偏离了推荐路径。")
            session.record_blocker(
                "tool_deviation",
                f"{tool_name} 当前处于避免列表中。",
                f"优先改用：{' -> '.join(recommended)}" if recommended else "请回到主通道工具"
            )
            if snapshot.get("scope_frozen"):
                session.mark_scope_expansion_denied(f"{tool_name} 偏离了已冻结的当前工具路径。")
        elif recommended and tool_name not in recommended and tool_name == "cli_tool":
            session.record_tool_deviation(tool_name, "当前存在更合适的主通道工具，不应默认回退到 cli_tool。")
            session.record_blocker(
                "tool_deviation",
                "当前已存在推荐工具链，cli_tool 仅应作为兜底。",
                f"优先改用：{' -> '.join(recommended)}"
            )
            if snapshot.get("scope_frozen"):
                session.mark_scope_expansion_denied("已冻结当前范围，但仍尝试回退到 cli_tool。")

    @staticmethod
    def _record_search_continuation(session, result_text: str, tool_name: str):
        continuation_match = re.search(r"\[续读\]\s*(.+)", result_text)
        if not continuation_match:
            return
        hint = continuation_match.group(1).strip()
        path_match = re.search(r'file_path="([^"]+)"', hint)
        path = path_match.group(1) if path_match else ""
        session.record_pending_continuation(tool_name, hint, path, strength="weak")

    def _try_auto_update_map(self, tool_name: str, tool_args: dict):
        """文件修改工具执行成功后，自动触发代码库地图和 Git 注意力刷新。"""
        try:
            from core.prompt_manager.codebase_map_builder import (
                is_file_modifying_tool,
                extract_file_path,
                on_file_modified,
            )
            from core.infrastructure.git_memory import get_git_memory_service
            from core.infrastructure.event_bus import EventNames
            if is_file_modifying_tool(tool_name):
                filepath = extract_file_path(tool_name, tool_args)
                if filepath:
                    self._event_bus.publish(EventNames.WORKSPACE_FILE_MODIFIED, {
                        "path": filepath,
                        "tool_name": tool_name,
                    })
                    on_file_modified(filepath)
                    get_git_memory_service().note_file_modified(filepath)
        except Exception:
            pass


# 全局工具执行器单例
_tool_executor: Optional[ToolExecutor] = None


def get_tool_executor() -> ToolExecutor:
    """获取工具执行器单例"""
    global _tool_executor
    if _tool_executor is None:
        _tool_executor = ToolExecutor()
    return _tool_executor
