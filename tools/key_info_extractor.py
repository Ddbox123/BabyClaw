#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
关键信息提取器

从消息历史中提取关键信息：
- 关键决策点
- 错误信息
- 重要的工具调用结果
- 学习洞察
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from core.infrastructure.runtime_input import is_external_request_message


class KeyInfoExtractor:
    """
    从消息历史中提取关键信息
    """

    # 错误关键词
    ERROR_KEYWORDS = [
        'error', 'exception', 'failed', 'traceback',
        '错误', '异常', '失败', 'warning', '警告',
        'timeout', '超时', 'refused', '拒绝',
    ]

    # 关键决策关键词
    DECISION_KEYWORDS = [
        '决定', '选择', '决策', 'decision',
        '选择使用', '采用', '计划', '开始执行',
        '分析完成', '结论是', '判断',
    ]

    # 重要工具
    IMPORTANT_TOOLS = [
        'trigger_self_restart', 'apply_diff_edit', 'execute_shell',
        'commit_compressed_memory',
    ]

    def __init__(self):
        """初始化关键信息提取器"""
        self._error_pattern = re.compile(
            '|'.join(re.escape(kw) for kw in self.ERROR_KEYWORDS),
            re.IGNORECASE
        )
        self._decision_pattern = re.compile(
            '|'.join(re.escape(kw) for kw in self.DECISION_KEYWORDS),
            re.IGNORECASE
        )

    def extract_errors(self, messages: List[Any]) -> List[Dict[str, str]]:
        """
        从消息历史中提取错误信息

        Args:
            messages: 消息列表

        Returns:
            错误信息列表，每项包含 tool_name, error_message, context
        """
        errors = []
        current_tool = None

        for msg in messages:
            msg_type = getattr(msg, 'type', 'unknown')
            content = getattr(msg, 'content', '')
            tool_calls = getattr(msg, 'tool_calls', None)

            # 记录当前工具
            if tool_calls:
                for tc in tool_calls:
                    current_tool = tc.get('name', 'unknown')

            # 检查错误
            if content and self._error_pattern.search(content):
                # 判断错误来源
                if msg_type == 'tool':
                    error_entry = {
                        'tool': current_tool or 'unknown',
                        'error': content[:500],  # 截断过长内容
                        'context': self._get_context(messages, msg),
                    }
                    errors.append(error_entry)

                # AI 回复中的错误提及
                elif msg_type == 'ai' and not tool_calls:
                    # 检查是否是分析错误
                    if any(kw in content.lower() for kw in ['错误', 'error', 'exception', '失败']):
                        errors.append({
                            'tool': 'analysis',
                            'error': content[:500],
                            'context': 'AI_analysis',
                        })

        return errors

    def extract_key_decisions(self, messages: List[Any]) -> List[Dict[str, str]]:
        """
        从消息历史中提取关键决策点

        Args:
            messages: 消息列表

        Returns:
            决策列表，每项包含 decision, reason, context
        """
        decisions = []
        last_external_request = None

        for msg in messages:
            msg_type = getattr(msg, 'type', 'unknown')
            content = getattr(msg, 'content', '')

            # 记录最后一条外部任务输入作为上下文
            if is_external_request_message(msg):
                last_external_request = content[:200]

            # 检查决策关键词
            if content and self._decision_pattern.search(content):
                decisions.append({
                    'decision': content[:300],
                    'reason': self._extract_reason(content),
                    'context': last_external_request or 'unknown',
                })

        return decisions

    def extract_tool_results(
        self,
        messages: List[Any],
        important_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        提取重要的工具调用结果

        Args:
            messages: 消息列表
            important_only: 是否只提取重要工具的结果

        Returns:
            工具结果列表
        """
        results = []
        current_tool = None

        for msg in messages:
            msg_type = getattr(msg, 'type', 'unknown')
            content = getattr(msg, 'content', '')
            tool_calls = getattr(msg, 'tool_calls', None)

            # 记录当前工具
            if tool_calls:
                for tc in tool_calls:
                    tool_name = tc.get('name', 'unknown')
                    if not important_only or tool_name in self.IMPORTANT_TOOLS:
                        current_tool = tool_name

            # 提取工具结果
            if msg_type == 'tool' and current_tool:
                results.append({
                    'tool': current_tool,
                    'result': content[:500] if content else '',
                    'length': len(content) if content else 0,
                })
                current_tool = None

        return results

    def extract_learning_insights(self, messages: List[Any]) -> List[str]:
        """
        提取学习洞察

        Args:
            messages: 消息列表

        Returns:
            洞察列表
        """
        insights = []
        insight_keywords = [
            '学到', '发现', '学到', '意识到', '理解',
            'learned', 'discovered', 'realized', 'insight',
            'pattern', '规律', '优化', '改进',
        ]

        pattern = re.compile('|'.join(re.escape(kw) for kw in insight_keywords), re.IGNORECASE)

        for msg in messages:
            msg_type = getattr(msg, 'type', 'unknown')
            content = getattr(msg, 'content', '')

            # 只从 AI 回复中提取
            if msg_type == 'ai' and not getattr(msg, 'tool_calls', None):
                if content and pattern.search(content):
                    # 提取包含洞察的句子
                    sentences = re.split(r'[。.!?\n]', content)
                    for sent in sentences:
                        if pattern.search(sent) and len(sent) > 10:
                            insights.append(sent.strip()[:200])

        return list(dict.fromkeys(insights))[:10]  # 去重，最多10条

    def extract_key_info_summary(self, messages: List[Any]) -> str:
        """
        提取关键信息摘要

        Args:
            messages: 消息列表

        Returns:
            格式化的关键信息摘要
        """
        parts = []

        # 提取错误
        errors = self.extract_errors(messages)
        if errors:
            error_summary = [f"[错误] {e['tool']}: {e['error'][:100]}" for e in errors[:3]]
            parts.append("## 错误\n" + "\n".join(error_summary))

        # 提取决策
        decisions = self.extract_key_decisions(messages)
        if decisions:
            decision_summary = [f"[决策] {d['decision'][:100]}" for d in decisions[:3]]
            parts.append("## 决策\n" + "\n".join(decision_summary))

        # 提取洞察
        insights = self.extract_learning_insights(messages)
        if insights:
            insight_summary = [f"[洞察] {i[:100]}" for i in insights[:3]]
            parts.append("## 洞察\n" + "\n".join(insight_summary))

        return "\n\n".join(parts) if parts else ""

    def _get_context(self, messages: List[Any], target_msg: Any) -> str:
        """
        获取错误消息的上下文

        Args:
            messages: 消息列表
            target_msg: 目标消息

        Returns:
            上下文描述
        """
        for i, msg in enumerate(messages):
            if msg is target_msg and i > 0:
                prev_msg = messages[i - 1]
                prev_type = getattr(prev_msg, 'type', 'unknown')
                if prev_type == 'ai':
                    tool_calls = getattr(prev_msg, 'tool_calls', None)
                    if tool_calls:
                        return f"After calling: {tool_calls[0].get('name', 'unknown')}"
                return f"After: {prev_type}"
        return "Start of conversation"

    def _extract_reason(self, content: str) -> str:
        """
        从决策内容中提取原因

        Args:
            content: 决策内容

        Returns:
            提取的原因
        """
        # 尝试提取"因为"、"所以"等因果关系
        reason_patterns = [
            r'因为(.+?)[，,]',
            r'由于(.+?)[，,]',
            r'所以(.+?)[。]',
            r'因此(.+?)[。]',
        ]

        for pattern in reason_patterns:
            match = re.search(pattern, content)
            if match:
                return match.group(1).strip()[:100]

        return content[:100]  # 默认返回前100字符


# 全局单例
_extractor_instance: Optional[KeyInfoExtractor] = None


def get_key_info_extractor() -> KeyInfoExtractor:
    """
    获取关键信息提取器单例

    Returns:
        关键信息提取器实例
    """
    global _extractor_instance
    if _extractor_instance is None:
        _extractor_instance = KeyInfoExtractor()
    return _extractor_instance


def reset_key_info_extractor() -> None:
    """重置关键信息提取器单例"""
    global _extractor_instance
    _extractor_instance = None
