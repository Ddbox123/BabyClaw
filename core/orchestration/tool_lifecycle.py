# -*- coding: utf-8 -*-
"""工具生命周期桥接器。

将工具执行、结果回写、生命周期动作派生从 agent.py 主循环中抽离，
让主循环只保留高层调度职责。
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional, Tuple

from langchain_core.messages import AIMessage, ToolMessage

from core.infrastructure.llm_utils import parse_tool_args
from core.infrastructure.tool_result import truncate_result
from core.logging.logger import debug as _debug_logger
from core.logging.unified_logger import logger
from core.ui.cli_ui import get_ui
from tools.rebirth_tools import handle_restart_request


ToolExecuteFn = Callable[[str, dict], Tuple[Any, Optional[str]]]
ToolGuardFn = Callable[[str, dict], Optional[str]]
ToolResultObserverFn = Callable[[Dict[str, Any], Any, Optional[str]], None]


class ToolLifecycleBridge:
    """负责工具调用的执行、结果回写与生命周期动作派生。"""

    def __init__(
        self,
        *,
        tool_executor_execute: ToolExecuteFn,
        tool_guard: Optional[ToolGuardFn] = None,
        tool_result_observer: Optional[ToolResultObserverFn] = None,
        post_close_action_pending: Optional[Callable[[], bool]] = None,
        self_modified: bool = False,
    ) -> None:
        self._tool_executor_execute = tool_executor_execute
        self._tool_guard = tool_guard
        self._tool_result_observer = tool_result_observer
        self._post_close_action_pending = post_close_action_pending
        self._self_modified = self_modified

    def execute_tool(self, tool_call: Dict[str, Any], messages: list) -> tuple:
        """执行单个工具调用。"""
        ui = get_ui()
        tool_name = tool_call.get("name", "unknown")
        tool_args = parse_tool_args(
            tool_call.get("args") or tool_call.get("arguments") or {}
        )
        tool_call_id = tool_call.get("id", None)

        _debug_logger.tool_start(tool_name, tool_args)

        if self._tool_guard:
            blocked_reason = self._tool_guard(tool_name, tool_args)
            if blocked_reason:
                ui.update_status("ERROR")
                logger.log_tool_call(
                    tool_name,
                    tool_args,
                    blocked_reason,
                    status="error",
                    tool_call_id=tool_call_id,
                )
                _debug_logger.warning(f"[工具护栏] {tool_name} 被短路: {blocked_reason}", tag="TOOL")
                self._observe_tool_result(tool_call, blocked_reason, None)
                return (blocked_reason, None)

        if tool_name == "trigger_self_restart_tool":
            ui.update_status("ACTING")
            result, action = handle_restart_request(
                tool_args=tool_args,
                messages=messages,
                self_modified=self._self_modified,
            )
            logger.log_tool_call(
                tool_name,
                tool_args,
                str(result) if result else "",
                status="success",
                tool_call_id=tool_call_id,
            )
            self._observe_tool_result(tool_call, result, action)
            return (result, action)

        ui.update_status("ACTING")
        result, tool_action = self._tool_executor_execute(tool_name, tool_args)
        action = tool_action or self.derive_lifecycle_action(
            tool_name,
            result,
            post_close_action_pending=self._has_post_close_action_pending(),
        )
        is_err = isinstance(result, str) and (
            result.startswith("[错误]")
            or result.startswith("[超时]")
            or result.startswith("[短路]")
        )
        ui.update_status("ERROR" if is_err else "WORKING")

        if result is not None:
            status = "error" if is_err else "success"
            logger.log_tool_call(
                tool_name,
                tool_args,
                str(result),
                status=status,
                tool_call_id=tool_call_id,
            )
            _debug_logger.tool_result(tool_name, str(result), success=not is_err)
        else:
            logger.log_tool_call(
                tool_name,
                tool_args,
                "",
                status="error",
                tool_call_id=tool_call_id,
            )
            _debug_logger.warning(f"[警告] {tool_name} 返回 None", tag="TOOL")

        self._observe_tool_result(tool_call, result, action)
        return (result, action)

    def _observe_tool_result(self, tool_call: Dict[str, Any], result: Any, action: Optional[str]) -> None:
        if self._tool_result_observer is None:
            return
        try:
            self._tool_result_observer(tool_call, result, action)
        except Exception:
            pass

    def _has_post_close_action_pending(self) -> bool:
        if self._post_close_action_pending is None:
            return False
        try:
            return bool(self._post_close_action_pending())
        except Exception:
            return False

    @staticmethod
    def derive_lifecycle_action(
        tool_name: str,
        result: Any,
        *,
        post_close_action_pending: bool = False,
    ) -> Optional[str]:
        """根据工具结果推导生命周期动作。"""
        if tool_name != "close_evolution_transaction_tool":
            return None
        try:
            payload = json.loads(str(result or ""))
        except Exception:
            return None
        if str(payload.get("status") or "").strip().lower() != "success":
            return None
        if str(payload.get("transaction_status") or "").strip().lower() != "success":
            return None
        if post_close_action_pending:
            _debug_logger.info(
                "[生命周期] 事务已成功关账，但当前目标仍有后续动作，继续主循环。",
                tag="TOOL",
            )
            return None
        return "turn_complete"

    @staticmethod
    def handle_tool_result(tool_call: Dict[str, Any], result: Any, action: Optional[str], messages: list) -> None:
        """将工具结果回写到消息历史。"""
        result_str, truncated = truncate_result(result)
        if action in ("restart", "skip", "hibernated"):
            logger.log_action(action, {"tool": tool_call["name"]})
        tool_call_id = tool_call.get("id")
        if tool_call_id:
            messages.append(ToolMessage(content=result_str, tool_call_id=tool_call_id))
        else:
            messages.append(AIMessage(content=result_str))
        if truncated:
            _debug_logger.warning(f"[工具] {tool_call['name']} 结果过长，已截断", tag="TOOL")

    def execute_tools(self, tool_calls: List[Dict[str, Any]], messages: list) -> Optional[str]:
        """串行执行工具，并返回生命周期动作。"""
        if not tool_calls:
            return None

        lifecycle_action: Optional[str] = None
        for tool_call in tool_calls:
            result, action = self.execute_tool(tool_call, messages)
            self.handle_tool_result(tool_call, result, action, messages)
            if action in ("restart", "hibernated", "turn_complete"):
                lifecycle_action = action
                break
        return lifecycle_action
