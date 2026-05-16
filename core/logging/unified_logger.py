# -*- coding: utf-8 -*-
"""
统一日志管理器 - 合并 ConversationLogger 和 TranscriptLogger

提供统一的日志接口，同时输出到两个日志系统：
- JSON 统计日志 (ConversationLogger)
- Markdown 对话实录 (TranscriptLogger)

使用方式：
    from core.unified_logger import logger

    # 记录 LLM 请求（同时写入两个日志系统）
    logger.log_llm_request(messages, model="gpt-4")

    # 记录 LLM 响应
    logger.log_llm_response(response)

    # 记录工具调用
    logger.log_tool_call("read_file", {"path": "test.py"}, result="content")
"""

import threading
from datetime import datetime
from typing import Optional, List, Dict, Any

# 导入 ConversationLogger (在 logger.py 中)
from .logger import ConversationLogger
from .transcript_logger import TranscriptLogger


class UnifiedLogger:
    """
    统一日志管理器
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
        if getattr(self, '_initialized', False):
            return
        self._initialized = True

        # 初始化两个日志器
        self._conversation = ConversationLogger()
        self._transcript = TranscriptLogger()

        # 同步状态
        self._current_turn = 0
        self._system_prompt_written = False

    @property
    def conversation(self) -> ConversationLogger:
        """获取 ConversationLogger 实例（用于需要 JSON 日志的场景）"""
        return self._conversation

    @property
    def transcript(self) -> TranscriptLogger:
        """获取 TranscriptLogger 实例（用于需要 Markdown 日志的场景）"""
        return self._transcript

    def _sync_turn(self, turn: int):
        """同步轮次状态"""
        self._current_turn = turn
        self._conversation._turn_count = turn

    # ==================== 会话管理 ====================

    def start_session(self, system_prompt: str = None, metadata: dict = None):
        """开始新的会话（同时初始化两个日志系统）"""
        self._current_turn = 0
        self._system_prompt_written = False

        # TranscriptLogger: 创建新文件
        self._transcript.start_session(system_prompt if isinstance(system_prompt, str) else None)

        # ConversationLogger: 开始新会话
        self._conversation.new_session()
        if metadata:
            self._conversation.start_session(metadata)

        # 如果有 System Prompt，写入
        if isinstance(system_prompt, str) and system_prompt:
            self.write_system_prompt(system_prompt)

    def write_system_prompt(self, system_prompt: str):
        """写入 System Prompt"""
        if self._system_prompt_written:
            return
        self._system_prompt_written = True

        # TranscriptLogger: 写入 Markdown
        self._transcript.write_system_prompt(system_prompt)

        # ConversationLogger: 记录完整系统提示词
        self._conversation.log_system_prompt(system_prompt)

    # ==================== 对话轮次 ====================

    def start_turn(self, turn: int, timestamp: str = None):
        """开始新的对话轮次"""
        self._sync_turn(turn)

        # TranscriptLogger: 写入轮次标题
        self._transcript.start_turn(turn, timestamp)

    def log_external_request(self, content: str):
        """记录外部任务输入"""
        # ConversationLogger: JSON 日志
        self._conversation.log_external_request(content)

        # TranscriptLogger: Markdown 格式
        self._transcript.write_external_request(content)

    # ==================== LLM 交互 ====================

    def log_llm_request(self, messages: list, model: str = None, iteration: int = 0):
        """记录发送给 LLM 的请求"""
        # ConversationLogger: JSON 日志
        self._conversation.log_llm_request(messages, model=model, iteration=iteration)

    def log_llm_response(self, content: str, raw_response: str = None,
                         input_tokens: int = 0, output_tokens: int = 0, tool_call_count: int = 0):
        """记录 LLM 的响应"""
        # ConversationLogger: JSON 日志
        self._conversation.log_llm_response(content, raw_response,
                                            input_tokens=input_tokens,
                                            output_tokens=output_tokens,
                                            tool_call_count=tool_call_count)

        # TranscriptLogger: Markdown 格式
        self._transcript.write_llm_response(content)

    def log_llm_thinking(self, thinking: str):
        """记录 LLM 的思考过程"""
        # TranscriptLogger: Markdown 格式（带折叠）
        self._transcript.write_llm_response("", thinking)

    def log_llm_intent(self, intent: str, content_preview: str = None):
        """记录 LLM 的意图/思考"""
        # ConversationLogger: JSON 日志
        self._conversation.log_llm_intent(intent, content_preview)

    # ==================== 工具调用 ====================

    def log_tool_call(
        self,
        tool_name: str,
        args: dict,
        result: str = None,
        status: str = "success",
        tool_call_id: str = None,
    ):
        """记录工具调用"""
        # ConversationLogger: JSON 日志
        self._conversation.log_tool_call(tool_name, args, result, status, tool_call_id=tool_call_id)

        # TranscriptLogger: Markdown 格式
        self._transcript.write_tool_call(tool_name, args, result, status)

    # ==================== 特殊事件 ====================

    def log_compression(self, before_tokens: int, after_tokens: int, saved_tokens: int):
        """记录上下文压缩"""
        # ConversationLogger: JSON 日志
        self._conversation.log_compression(before_tokens, after_tokens, saved_tokens)
        # TranscriptLogger: Markdown 格式
        self._transcript.write_compression(before_tokens, after_tokens, saved_tokens)

    def log_action(self, action: str, details: dict = None):
        """记录特殊动作（restart/hibernated/skip 等）"""
        # ConversationLogger: JSON 日志
        self._conversation.log_action(action, details)

        # TranscriptLogger: Markdown 格式
        self._transcript.write_action(action, details)

    def log_error(self, error_type: str, error_msg: str, traceback: str = None, details: dict = None):
        """记录错误"""
        # ConversationLogger: JSON 日志
        self._conversation.log_error(error_type, error_msg, traceback, details=details)
        # TranscriptLogger: Markdown 格式
        self._transcript.write_error(error_type, error_msg)

    # ==================== 会话管理 ====================

    def end_session(self, summary: dict = None):
        """结束会话"""
        # ConversationLogger: JSON 日志
        self._conversation.end_session(summary)

    # ==================== 新增事件转发 ====================

    def log_system_prompt(self, prompt_text: str):
        """记录完整系统提示词"""
        self._conversation.log_system_prompt(prompt_text)

    def log_token_usage(self, input_tokens: int, output_tokens: int, turn: int = 0):
        """记录 token 用量"""
        self._conversation.log_token_usage(input_tokens, output_tokens, turn)

    def log_turn_end(self, turn: int, stats: dict = None):
        """记录轮次汇总"""
        self._conversation.log_turn_end(turn, stats)

    # ==================== 便捷属性（向后兼容） ====================

    @property
    def _turn_count(self) -> int:
        """获取当前轮次（向后兼容）"""
        return self._conversation._turn_count

    @_turn_count.setter
    def _turn_count(self, value: int):
        """设置当前轮次（向后兼容）"""
        self._conversation._turn_count = value


# 全局统一日志管理器实例
logger = UnifiedLogger()


def get_logger() -> UnifiedLogger:
    """获取全局 UnifiedLogger 实例"""
    return logger
