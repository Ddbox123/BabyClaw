#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
关键信息提取器测试
"""

import pytest
from tools.key_info_extractor import (
    KeyInfoExtractor,
    get_key_info_extractor,
    reset_key_info_extractor,
)


class MockMessage:
    """模拟消息对象"""

    def __init__(self, msg_type: str, content: str = "", tool_calls: list = None):
        self.type = msg_type
        self.content = content
        self.tool_calls = tool_calls or []


class TestKeyInfoExtractor:
    """测试关键信息提取器"""

    def setup_method(self):
        """每个测试前重置单例"""
        reset_key_info_extractor()

    def test_init(self):
        """测试初始化"""
        extractor = KeyInfoExtractor()
        assert extractor.ERROR_KEYWORDS is not None
        assert extractor.DECISION_KEYWORDS is not None
        assert extractor.IMPORTANT_TOOLS is not None

    def test_extract_errors_from_tool_results(self):
        """测试从工具结果中提取错误"""
        extractor = KeyInfoExtractor()
        messages = [
            MockMessage('ai', '', tool_calls=[{'name': 'execute_shell'}]),
            MockMessage('tool', 'Error: Command failed with exit code 1'),
        ]
        errors = extractor.extract_errors(messages)
        assert len(errors) == 1
        assert errors[0]['tool'] == 'execute_shell'

    def test_extract_errors_from_ai_analysis(self):
        """测试从AI分析中提取错误"""
        extractor = KeyInfoExtractor()
        messages = [
            MockMessage('ai', '分析发现了一个错误：语法不正确'),
        ]
        errors = extractor.extract_errors(messages)
        assert len(errors) >= 1

    def test_extract_errors_empty_messages(self):
        """测试空消息列表"""
        extractor = KeyInfoExtractor()
        errors = extractor.extract_errors([])
        assert errors == []

    def test_extract_key_decisions(self):
        """测试提取关键决策"""
        extractor = KeyInfoExtractor()
        messages = [
            MockMessage('human', '请帮我分析代码'),
            MockMessage('ai', '经过分析，我决定采用AST方法来解析代码'),
        ]
        decisions = extractor.extract_key_decisions(messages)
        assert len(decisions) >= 1

    def test_extract_key_decisions_uses_external_request_context(self):
        """测试关键决策优先关联外部任务输入上下文"""
        extractor = KeyInfoExtractor()
        messages = [
            MockMessage('system', '## 外部任务输入\n检查 token 压缩协议'),
            MockMessage('ai', '我决定先统一外部输入识别函数'),
        ]
        decisions = extractor.extract_key_decisions(messages)

        assert len(decisions) >= 1
        assert '检查 token 压缩协议' in decisions[0]['context']

    def test_extract_tool_results(self):
        """测试提取工具结果"""
        extractor = KeyInfoExtractor()
        messages = [
            MockMessage('ai', '', tool_calls=[{'name': 'grep_search'}]),
            MockMessage('tool', 'Found 10 matches in 5 files'),
        ]
        results = extractor.extract_tool_results(messages)
        assert len(results) == 1
        assert results[0]['tool'] == 'grep_search'

    def test_extract_tool_results_important_only(self):
        """测试只提取重要工具结果"""
        extractor = KeyInfoExtractor()
        messages = [
            MockMessage('ai', '', tool_calls=[{'name': 'grep_search'}]),
            MockMessage('tool', 'Found matches'),
            MockMessage('ai', '', tool_calls=[{'name': 'trigger_self_restart'}]),
            MockMessage('tool', 'Restarting...'),
        ]
        results = extractor.extract_tool_results(messages, important_only=True)
        assert len(results) == 1
        assert results[0]['tool'] == 'trigger_self_restart'

    def test_extract_learning_insights(self):
        """测试提取学习洞察"""
        extractor = KeyInfoExtractor()
        messages = [
            MockMessage('ai', '我学到了一个新的优化技巧'),
            MockMessage('ai', '发现了一个更好的实现方式'),
        ]
        insights = extractor.extract_learning_insights(messages)
        assert len(insights) >= 1

    def test_extract_learning_insights_empty(self):
        """测试无洞察时返回空"""
        extractor = KeyInfoExtractor()
        messages = [
            MockMessage('ai', '这是一个普通的回复'),
        ]
        insights = extractor.extract_learning_insights(messages)
        assert insights == []

    def test_extract_key_info_summary(self):
        """测试提取关键信息摘要"""
        extractor = KeyInfoExtractor()
        messages = [
            MockMessage('ai', '', tool_calls=[{'name': 'execute_shell'}]),
            MockMessage('tool', 'Error: Command failed'),
            MockMessage('ai', '经过分析，我决定采用新的方案'),
        ]
        summary = extractor.extract_key_info_summary(messages)
        assert summary != ""
        assert "错误" in summary or "Error" in summary

    def test_extract_key_info_summary_empty(self):
        """测试空消息的关键信息摘要"""
        extractor = KeyInfoExtractor()
        summary = extractor.extract_key_info_summary([])
        assert summary == ""


class TestKeyInfoExtractorSingleton:
    """测试关键信息提取器单例"""

    def setup_method(self):
        """每个测试前重置单例"""
        reset_key_info_extractor()

    def test_get_singleton(self):
        """测试获取单例"""
        e1 = get_key_info_extractor()
        e2 = get_key_info_extractor()
        assert e1 is e2

    def test_reset_singleton(self):
        """测试重置单例"""
        e1 = get_key_info_extractor()
        reset_key_info_extractor()
        e2 = get_key_info_extractor()
        assert e1 is not e2
