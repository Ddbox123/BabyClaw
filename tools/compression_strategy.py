#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Token 压缩策略管理器

提供多级压缩策略支持，根据当前 Token 使用情况动态选择压缩级别。

压缩级别：
- LIGHT: 轻度压缩，保留 80% 内容
- STANDARD: 标准压缩，保留 50% 内容
- DEEP: 深度压缩，保留 30% 内容 + 关键信息
- EMERGENCY: 紧急压缩，只保留最新消息
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, List, Optional


class CompressionLevel(Enum):
    """压缩级别枚举"""
    LIGHT = "light"           # 轻度压缩：保留 80% 内容
    STANDARD = "standard"     # 标准压缩：保留 50% 内容
    DEEP = "deep"            # 深度压缩：保留 30% 内容 + 关键信息
    EMERGENCY = "emergency"  # 紧急压缩：只保留最新消息

    @property
    def severity(self) -> int:
        _order = {
            CompressionLevel.LIGHT: 1,
            CompressionLevel.STANDARD: 2,
            CompressionLevel.DEEP: 3,
            CompressionLevel.EMERGENCY: 4,
        }
        return _order[self]

    @classmethod
    def max_severity(cls, a: 'CompressionLevel', b: 'CompressionLevel') -> 'CompressionLevel':
        return a if a.severity >= b.severity else b


@dataclass
class CompressionConfig:
    """压缩配置"""
    level: CompressionLevel
    summary_max_chars: int
    keep_ai_messages: int
    keep_tool_results: bool = True
    extract_key_decisions: bool = True
    preserve_errors: bool = True
    preserve_system_prompt: bool = True


@dataclass
class CompressionThresholds:
    """压缩阈值配置"""
    light_threshold: float = 0.6    # 60% 开始轻度压缩
    standard_threshold: float = 0.8  # 80% 标准压缩
    deep_threshold: float = 0.9     # 90% 深度压缩
    emergency_threshold: float = 0.95  # 95% 紧急压缩


class CompressionStrategy:
    """
    压缩策略管理器

    根据当前 Token 使用情况和压缩次数，智能选择压缩策略。
    """

    def __init__(self, thresholds: Optional[CompressionThresholds] = None):
        """
        初始化压缩策略管理器

        Args:
            thresholds: 压缩阈值配置，默认使用标准配置
        """
        self.thresholds = thresholds or CompressionThresholds()

        # 从配置加载默认摘要字数
        try:
            from config import get_config
            cfg = get_config()
            cc = cfg.context_compression
            self._summary_chars = {
                CompressionLevel.LIGHT: cc.summary_chars.light,
                CompressionLevel.STANDARD: cc.summary_chars.standard,
                CompressionLevel.DEEP: cc.summary_chars.deep,
                CompressionLevel.EMERGENCY: cc.summary_chars.emergency,
            }
            self._keep_ai_messages = {
                CompressionLevel.LIGHT: cc.preservation.keep_ai_messages,
                CompressionLevel.STANDARD: max(cc.preservation.keep_ai_messages - 2, 1),
                CompressionLevel.DEEP: max(cc.preservation.keep_ai_messages - 3, 1),
                CompressionLevel.EMERGENCY: 1,
            }
        except Exception:
            # 兜底默认值
            self._summary_chars = {
                CompressionLevel.LIGHT: 500,
                CompressionLevel.STANDARD: 1000,
                CompressionLevel.DEEP: 2000,
                CompressionLevel.EMERGENCY: 3000,
            }
            self._keep_ai_messages = {
                CompressionLevel.LIGHT: 5,
                CompressionLevel.STANDARD: 3,
                CompressionLevel.DEEP: 2,
                CompressionLevel.EMERGENCY: 1,
            }

    def get_config(
        self,
        level: CompressionLevel,
        current_tokens: int = 0,
        max_tokens: int = 16000,
    ) -> CompressionConfig:
        """
        根据压缩级别获取压缩配置

        Args:
            level: 压缩级别
            current_tokens: 当前 Token 数
            max_tokens: 最大 Token 数

        Returns:
            压缩配置
        """
        return CompressionConfig(
            level=level,
            summary_max_chars=self._summary_chars.get(level, 1000),
            keep_ai_messages=self._keep_ai_messages.get(level, 3),
            keep_tool_results=True,
            extract_key_decisions=level in (CompressionLevel.STANDARD, CompressionLevel.DEEP),
            preserve_errors=True,
            preserve_system_prompt=True,
        )

    def calculate_compression_ratio(self, level: CompressionLevel) -> float:
        """
        计算目标压缩比

        Args:
            level: 压缩级别

        Returns:
            目标压缩比（0.0 - 1.0），保留的比例
        """
        ratios = {
            CompressionLevel.LIGHT: 0.8,
            CompressionLevel.STANDARD: 0.5,
            CompressionLevel.DEEP: 0.3,
            CompressionLevel.EMERGENCY: 0.15,
        }
        return ratios.get(level, 0.5)

    def should_preserve_message(self, msg: Any, level: CompressionLevel) -> bool:
        """
        判断是否应保留某条消息

        Args:
            msg: 消息对象
            level: 压缩级别

        Returns:
            是否应保留
        """
        msg_type = getattr(msg, 'type', 'unknown')
        content = getattr(msg, 'content', '')
        has_tool_calls = bool(getattr(msg, 'tool_calls', None))

        # 系统消息总是保留
        if msg_type == 'system':
            return True

        # 紧急压缩只保留最新的 AI 消息
        if level == CompressionLevel.EMERGENCY:
            return msg_type == 'ai' and has_tool_calls

        # 深度压缩保留工具调用
        if level == CompressionLevel.DEEP and has_tool_calls:
            return True

        # 标准及以上保留工具结果中的错误信息
        if level in (CompressionLevel.STANDARD, CompressionLevel.DEEP):
            if msg_type == 'tool' and content:
                # 检查是否包含错误关键词
                error_keywords = ['error', 'exception', 'failed', 'traceback', '错误', '异常', '失败']
                if any(kw in content.lower() for kw in error_keywords):
                    return True

        # 默认保留
        return True

    def determine_level(
        self,
        current_tokens: int,
        max_tokens: int,
        compression_count: int = 0,
    ) -> CompressionLevel:
        """
        根据 Token 使用情况确定压缩级别

        Args:
            current_tokens: 当前 Token 数
            max_tokens: 最大 Token 数
            compression_count: 已压缩次数

        Returns:
            压缩级别
        """
        if max_tokens <= 0:
            return CompressionLevel.STANDARD

        ratio = current_tokens / max_tokens

        # 紧急阈值
        if ratio >= self.thresholds.emergency_threshold:
            return CompressionLevel.EMERGENCY

        # 深度阈值
        if ratio >= self.thresholds.deep_threshold:
            if compression_count >= 2:
                # 多次压缩后使用保守策略
                return CompressionLevel.STANDARD
            return CompressionLevel.DEEP

        # 标准阈值
        if ratio >= self.thresholds.standard_threshold:
            return CompressionLevel.STANDARD

        # 轻度阈值
        if ratio >= self.thresholds.light_threshold:
            return CompressionLevel.LIGHT

        return CompressionLevel.LIGHT  # 默认轻度

    def determine_level_with_iteration(
        self,
        current_tokens: int,
        max_tokens: int,
        iteration: int,
        compression_count: int = 0,
    ) -> CompressionLevel:
        """结合 token 比和迭代数确定压缩级别（防止认知漂移）。

        Args:
            current_tokens: 当前 Token 数
            max_tokens: 最大 Token 数
            iteration: 当前迭代数
            compression_count: 已压缩次数

        Returns:
            压缩级别
        """
        base = self.determine_level(current_tokens, max_tokens, compression_count)
        if iteration >= 25:
            return CompressionLevel.EMERGENCY
        elif iteration >= 18:
            return CompressionLevel.max_severity(base, CompressionLevel.DEEP)
        elif iteration >= 12:
            return CompressionLevel.max_severity(base, CompressionLevel.STANDARD)
        return base

    def set_summary_chars(
        self,
        level: CompressionLevel,
        chars: int,
    ) -> None:
        """
        设置指定压缩级别的摘要字数

        Args:
            level: 压缩级别
            chars: 摘要最大字符数
        """
        self._summary_chars[level] = chars

    def get_summary_chars(self, level: CompressionLevel) -> int:
        """
        获取指定压缩级别的摘要字数

        Args:
            level: 压缩级别

        Returns:
            摘要最大字符数
        """
        return self._summary_chars.get(level, 1000)

    def set_keep_ai_messages(
        self,
        level: CompressionLevel,
        count: int,
    ) -> None:
        """
        设置指定压缩级别保留的 AI 消息数

        Args:
            level: 压缩级别
            count: 保留的消息数
        """
        self._keep_ai_messages[level] = count

    def get_keep_ai_messages(self, level: CompressionLevel) -> int:
        """
        获取指定压缩级别保留的 AI 消息数

        Args:
            level: 压缩级别

        Returns:
            保留的消息数
        """
        return self._keep_ai_messages.get(level, 3)


# 全局单例
_strategy_instance: Optional[CompressionStrategy] = None


def get_compression_strategy(
    thresholds: Optional[CompressionThresholds] = None,
) -> CompressionStrategy:
    """
    获取压缩策略管理器单例

    Args:
        thresholds: 压缩阈值配置

    Returns:
        压缩策略管理器实例
    """
    global _strategy_instance
    if _strategy_instance is None or thresholds is not None:
        _strategy_instance = CompressionStrategy(thresholds)
    return _strategy_instance


def reset_compression_strategy() -> None:
    """重置压缩策略管理器单例"""
    global _strategy_instance
    _strategy_instance = None
