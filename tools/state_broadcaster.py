# -*- coding: utf-8 -*-
"""
Agent 状态广播模块 - 实时状态管理

为终端 UI 提供实时状态更新，写入 JSON 文件供 TUI 渲染使用。

状态类型：
- IDLE: 空闲/等待
- AWAKENING: 苏醒中
- THINKING: 思考中
- SEARCHING: 搜索知识
- PLANNING: 制定计划
- CODING: 编写代码
- TESTING: 沙盒测试
- COMPRESSING: 上下文压缩
- RESTARTING: 重启中
- HIBERNATING: 休眠中
- ERROR: 错误状态
"""

import os
import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
from enum import Enum


class AgentStatus(Enum):
    """Agent 状态枚举"""
    IDLE = "IDLE"
    AWAKENING = "AWAKENING"
    THINKING = "THINKING"
    SEARCHING = "SEARCHING"
    PLANNING = "PLANNING"
    CODING = "CODING"
    TESTING = "TESTING"
    COMPRESSING = "COMPRESSING"
    RESTARTING = "RESTARTING"
    HIBERNATING = "HIBERNATING"
    ERROR = "ERROR"


class StateBroadcaster:
    """
    Agent 状态广播器

    将 Agent 当前状态写入 JSON 文件，供 TUI 实时读取渲染。
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        # 获取项目根目录
        self.project_root = Path(__file__).parent.parent.resolve()
        self.state_file = self.project_root / "agent_state.json"
        self.log_file = self.project_root / "logs" / "agent_realtime.log"

        # 确保日志目录存在
        self.log_file.parent.mkdir(exist_ok=True)

        # 状态信息
        self._current_status = AgentStatus.IDLE
        self._current_action = "系统初始化中..."
        self._token_budget = 0
        self._last_update = datetime.now().isoformat()

        # 线程安全
        self._state_lock = threading.Lock()

        # 日志文件句柄
        self._log_handle = None

        # 初始化状态文件
        self._write_state()

    def _get_default_state(self) -> Dict[str, Any]:
        """获取默认状态"""
        return {
            "status": self._current_status.value,
            "current_action": self._current_action,
            "token_budget": self._token_budget,
            "current_goal": "",
            "core_context_preview": "",
            "uptime_seconds": 0,
            "last_update": self._last_update,
            "iteration_count": 0,
            "tools_executed": 0,
        }

    def _write_state(self):
        """线程安全地写入状态文件"""
        with self._state_lock:
            state = self._get_default_state()
            try:
                with open(self.state_file, 'w', encoding='utf-8') as f:
                    json.dump(state, f, ensure_ascii=False, indent=2)
            except Exception as e:
                from core.logging import debug_logger
                debug_logger.error(f"[StateBroadcaster] 写入状态文件失败: {e}")

    def _open_log_file(self):
        """打开日志文件（延迟打开）"""
        if self._log_handle is None:
            try:
                self._log_handle = open(self.log_file, 'a', encoding='utf-8', buffering=1)
            except Exception as e:
                from core.logging import debug_logger
                debug_logger.error(f"[StateBroadcaster] 打开日志文件失败: {e}")

    def update_status(
        self,
        status: AgentStatus,
        action: str = None,
        generation: int = None,
        token_budget: int = None,
        current_goal: str = None,
        core_context_preview: str = None,
        uptime_seconds: int = None,
        iteration_count: int = None,
        tools_executed: int = None,
    ):
        """
        更新 Agent 状态

        Args:
            status: 新状态
            action: 当前动作描述
            generation: 当前世代
            token_budget: Token 预算
            current_goal: 当前目标
            core_context_preview: 核心上下文预览
            uptime_seconds: 运行时间
            iteration_count: 迭代次数
            tools_executed: 已执行工具数
        """
        with self._state_lock:
            if status:
                self._current_status = status
            if action is not None:
                self._current_action = action
            if token_budget is not None:
                self._token_budget = token_budget
            if current_goal is not None:
                self._current_goal = current_goal
            if core_context_preview is not None:
                self._core_context_preview = core_context_preview
            if uptime_seconds is not None:
                self._uptime_seconds = uptime_seconds
            if iteration_count is not None:
                self._iteration_count = iteration_count
            if tools_executed is not None:
                self._tools_executed = tools_executed

            self._last_update = datetime.now().isoformat()

        self._write_state()

    def get_state(self) -> Dict[str, Any]:
        """获取当前状态"""
        with self._state_lock:
            return self._get_default_state()

    def _rotate_log_if_needed(self):
        """日志超过 10MB 时轮转: .log -> .log.1"""
        try:
            if self.log_file.exists() and self.log_file.stat().st_size > 10 * 1024 * 1024:
                if self._log_handle:
                    self._log_handle.close()
                    self._log_handle = None
                rotated = self.log_file.with_suffix('.log.1')
                if rotated.exists():
                    rotated.unlink()
                self.log_file.rename(rotated)
        except OSError:
            pass

    def log(self, message: str, tag: str = "INFO"):
        """
        写入实时日志

        Args:
            message: 日志消息
            tag: 日志标签
        """
        self._rotate_log_if_needed()
        self._open_log_file()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        log_line = f"[{timestamp}] [{tag}] {message}\n"

        if self._log_handle:
            try:
                self._log_handle.write(log_line)
                self._log_handle.flush()
            except Exception as e:
                from core.logging import debug_logger
                debug_logger.error(f"[StateBroadcaster] 写入日志失败: {e}")

    def log_tool_call(self, tool_name: str, status: str = "called"):
        """记录工具调用"""
        self.log(f"Tool: {tool_name} {status}", "TOOL")

    def log_llm_call(self, tokens: int = None):
        """记录 LLM 调用"""
        if tokens:
            self.log(f"LLM 调用 | Tokens: {tokens}", "LLM")
        else:
            self.log("LLM 调用", "LLM")

    def log_error(self, error_msg: str):
        """记录错误"""
        self.log(f"ERROR: {error_msg}", "ERROR")
        self.update_status(AgentStatus.ERROR, action=f"错误: {error_msg[:50]}")

    def log_restart(self, reason: str = ""):
        """记录重启"""
        self.log(f"RESTART 触发 | 原因: {reason}", "RESTART")
        self.update_status(AgentStatus.RESTARTING, action="正在重启...")

    def log_hibernation(self, duration: int = 0):
        """记录休眠"""
        self.log(f"HIBERNATION | 时长: {duration}秒", "SLEEP")
        self.update_status(AgentStatus.HIBERNATING, action=f"休眠 {duration}秒")

    def close(self):
        """关闭日志文件"""
        if self._log_handle:
            try:
                self._log_handle.close()
            except:
                pass
            self._log_handle = None


# 全局单例
broadcaster = StateBroadcaster()


def get_broadcaster() -> StateBroadcaster:
    """获取全局广播器实例"""
    return broadcaster


# 便捷函数
def update_agent_status(status: AgentStatus, action: str = None, **kwargs):
    """便捷函数：更新 Agent 状态"""
    broadcaster.update_status(status, action, **kwargs)


def log_agent_event(message: str, tag: str = "INFO"):
    """便捷函数：记录日志事件"""
    broadcaster.log(message, tag)


def get_agent_state() -> Dict[str, Any]:
    """便捷函数：获取 Agent 状态"""
    return broadcaster.get_state()
