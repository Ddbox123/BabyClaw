#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Token 管理器完整测试套件

测试 tools/token_manager.py 中的所有功能：
- Token 精确估算（中英文差异）
- 消息列表 Token 计算
- 消息优先级推断
- Token 压缩器（EnhancedTokenCompressor）
- 智能截断（工具结果、AI 响应）
- 压缩统计（TokenCompressionStats）
"""

import os
import sys
import pytest
import time
import json
from pathlib import Path
from datetime import datetime
from typing import List, Any

from tools.token_manager import (
    # 工具函数
    estimate_tokens_precise,
    estimate_messages_tokens,
    get_message_priority,
    truncate_tool_result,
    truncate_ai_response,
    smart_compress_message,
    create_compressor,
    truncate_by_priority,
    format_compression_report,
    # 类和枚举
    EnhancedTokenCompressor,
    TokenCompressionStats,
    CompressionRecord,
    MessageMeta,
    MessagePriority,
    TokenBudget,
)
from core.infrastructure.runtime_input import build_external_request_message


# ============================================================================
# 测试辅助函数和数据
# ============================================================================

SAMPLE_ENGLISH_TEXT = """
The quick brown fox jumps over the lazy dog. This is a classic English 
pangram that contains all 26 letters of the alphabet. It's often used for
testing keyboard layouts and fonts.
""".strip()

SAMPLE_CHINESE_TEXT = """
中文文本测试。这个句子包含了常用的汉字。词语成语都很丰富。
阅读理解需要良好的语言能力。现代汉语有数千个常用字。
""".strip()

SAMPLE_MIXED_TEXT = """
Mixed content: 中文 English 混合 日本語も混在。Numbers 123, symbols !@#.
This is a test with multiple languages and character sets.
""".strip()

SAMPLE_CODE = '''
def hello_world():
    """Hello world function."""
    print("Hello, World!")
    return True

class MyClass:
    def __init__(self):
        self.value = 42
    
    def get_value(self):
        return self.value
'''.strip()

LARGE_TEXT = "x" * 10000  # 10k 字符


class FakeMessage:
    """模拟 LangChain 消息对象"""
    def __init__(self, content: str, msg_type: str = "ai"):
        self.content = content
        self.type = msg_type


class FakeToolCallMessage(FakeMessage):
    """带工具调用的 AI 消息。"""

    def __init__(self, tool_name: str, args: dict | None = None, content: str = ""):
        super().__init__(content=content, msg_type="ai")
        self.tool_calls = [{"name": tool_name, "args": args or {}}]


# ============================================================================
# estimate_tokens_precise 测试
# ============================================================================

class TestEstimateTokensPrecise:
    """精确 Token 估算测试"""

    def test_estimate_english_text(self):
        """测试英文文本估算"""
        tokens = estimate_tokens_precise(SAMPLE_ENGLISH_TEXT)
        # 英文约 4 字符/Token，加上 overhead
        expected_min = len(SAMPLE_ENGLISH_TEXT) // 4
        assert tokens >= expected_min
        assert tokens > 0

    def test_estimate_chinese_text(self):
        """测试中文文本估算"""
        tokens = estimate_tokens_precise(SAMPLE_CHINESE_TEXT)
        # 中文约 1.5 字符/Token
        expected_min = len(SAMPLE_CHINESE_TEXT) // 2  # 保守估计
        assert tokens >= expected_min
        assert tokens > 0

    def test_estimate_mixed_text(self):
        """测试混合文本估算"""
        tokens = estimate_tokens_precise(SAMPLE_MIXED_TEXT)
        assert tokens > 0
        # 混合文本 Token 数应介于纯中文和纯英文之间
        english_tokens = estimate_tokens_precise("a" * len(SAMPLE_MIXED_TEXT))
        assert tokens <= english_tokens * 1.5  # 不会太离谱

    def test_estimate_empty_string(self):
        """测试空字符串"""
        assert estimate_tokens_precise("") == 0

    def test_estimate_code(self):
        """测试代码估算"""
        tokens = estimate_tokens_precise(SAMPLE_CODE)
        assert tokens > 0
        # 代码 Token 数应与字符数成正比
        assert tokens < len(SAMPLE_CODE)

    def test_estimate_very_long_text(self):
        """测试超长文本"""
        tokens = estimate_tokens_precise(LARGE_TEXT)
        expected = len(LARGE_TEXT) // 4  # 英文字符估算
        # 允许一定误差
        assert tokens >= expected * 0.8
        assert tokens <= expected * 1.5

    def test_estimate_with_emoji(self):
        """测试 Emoji 字符"""
        emoji_text = "Hello 😀 World 🎉 !"
        tokens = estimate_tokens_precise(emoji_text)
        assert tokens > 0

    def test_estimate_safety_margin(self):
        """测试安全系数（1.2x）"""
        # 估算应偏保守（向上取整 + 50  overhead）
        short = "test"
        tokens = estimate_tokens_precise(short)
        # 短文本至少有一些 overhead
        assert tokens >= 1

    def test_repeated_calls_consistency(self):
        """测试重复调用一致性"""
        text = "Consistent test content " * 100
        tokens1 = estimate_tokens_precise(text)
        tokens2 = estimate_tokens_precise(text)
        assert tokens1 == tokens2


# ============================================================================
# estimate_messages_tokens 测试
# ============================================================================

class TestEstimateMessagesTokens:
    """消息列表 Token 估算测试"""

    def test_estimate_single_message(self):
        """测试单条消息"""
        msg = FakeMessage("Hello World")
        tokens = estimate_messages_tokens([msg])
        assert tokens > 0

    def test_estimate_multiple_messages(self):
        """测试多条消息"""
        messages = [
            FakeMessage("First message"),
            FakeMessage("Second message with more content"),
            FakeMessage("Third" * 50),
        ]
        tokens = estimate_messages_tokens(messages)
        assert tokens > 0
        # 总和应合理
        expected_min = sum(len(m.content) // 4 for m in messages)
        assert tokens >= expected_min

    def test_estimate_empty_messages(self):
        """测试空消息列表"""
        assert estimate_messages_tokens([]) == 0

    def test_estimate_messages_with_none_content(self):
        """测试内容为 None 的消息"""
        msg = FakeMessage(None)
        tokens = estimate_messages_tokens([msg])
        assert tokens >= 0  # 能处理 None

    def test_estimate_real_langchain_messages(self):
        """测试真实的 LangChain 消息类型"""
        from langchain_core.messages import AIMessage, SystemMessage
        
        messages = [
            SystemMessage(content="You are a helpful assistant"),
            build_external_request_message("Hello"),
            AIMessage(content="Hi there!"),
        ]
        tokens = estimate_messages_tokens(messages)
        assert tokens > 0


# ============================================================================
# get_message_priority 测试
# ============================================================================

class TestGetMessagePriority:
    """消息优先级推断测试"""

    def test_system_message_priority(self):
        """测试系统消息优先级"""
        msg = FakeMessage("System prompt", msg_type="system")
        assert get_message_priority(msg) == MessagePriority.CRITICAL

    def test_tool_message_with_success(self):
        """测试成功工具结果"""
        msg = FakeMessage("文件读取成功", msg_type="tool")
        priority = get_message_priority(msg)
        assert priority == MessagePriority.HIGH or priority == MessagePriority.CRITICAL

    def test_tool_message_with_error(self):
        """测试错误工具结果"""
        msg = FakeMessage("Error: file not found", msg_type="tool")
        priority = get_message_priority(msg)
        assert priority == MessagePriority.HIGH

    def test_tool_message_with_edit(self):
        """测试编辑操作"""
        msg = FakeMessage("[edit_local_file] agent.py modified", msg_type="tool")
        priority = get_message_priority(msg)
        assert priority == MessagePriority.HIGH

    def test_tool_message_with_restart(self):
        """测试重启操作"""
        msg = FakeMessage("trigger_self_restart_tool called", msg_type="tool")
        priority = get_message_priority(msg)
        assert priority == MessagePriority.HIGH

    def test_regular_ai_message(self):
        """测试普通 AI 回复"""
        msg = FakeMessage("This is a normal AI response", msg_type="ai")
        priority = get_message_priority(msg)
        # 可能是 MEDIUM 或更高
        assert priority in [MessagePriority.MEDIUM, MessagePriority.HIGH, MessagePriority.CRITICAL]

    def test_external_request_message_priority(self):
        """协议标记的外部任务输入保留中等优先级。"""
        msg = build_external_request_message("External input")
        priority = get_message_priority(msg)
        assert priority == MessagePriority.MEDIUM

    def test_unknown_type_default(self):
        """测试未知类型默认值"""
        msg = FakeMessage("Unknown", msg_type="unknown")
        priority = get_message_priority(msg)
        assert priority == MessagePriority.MEDIUM


# ============================================================================
# truncate_tool_result 测试
# ============================================================================

class TestTruncateToolResult:
    """工具结果截断测试"""

    def test_truncate_short_result(self):
        """测试短结果（不截断）"""
        short = "Short result"
        truncated = truncate_tool_result(short)
        assert truncated == short

    def test_truncate_long_result(self):
        """测试长结果截断"""
        long_result = "x" * 5000
        truncated = truncate_tool_result(long_result)
        assert len(truncated) < len(long_result)
        assert len(truncated) <= 400  # MAX_TOOL_RESULT_TOKENS 约 400 字符

    def test_truncate_preserves_head_and_tail(self):
        """测试保留头尾"""
        content = "A" * 100 + "B" * 100 + "C" * 100
        truncated = truncate_tool_result(content, max_chars=150)
        assert "A" * 50 in truncated  # 头部保留
        assert "C" * 50 in truncated  # 尾部保留

    def test_truncate_with_error_keyword(self):
        """测试包含错误关键词的内容"""
        error_content = "Error: something failed\n" + "x" * 1000
        truncated = truncate_tool_result(error_content, max_chars=200)
        # 错误信息应优先保留
        assert "Error" in truncated

    def test_truncate_with_none(self):
        """测试 None 值"""
        result = truncate_tool_result(None)
        assert result == "" or result is None

    def test_truncate_with_custom_max(self):
        """测试自定义最大长度"""
        content = "a" * 1000
        truncated = truncate_tool_result(content, max_chars=100)
        assert len(truncated) <= 100

    def test_truncate_empty_string(self):
        """测试空字符串"""
        assert truncate_tool_result("") == ""


# ============================================================================
# truncate_ai_response 测试
# ============================================================================

class TestTruncateAIResponse:
    """AI 响应截断测试"""

    def test_truncate_short_ai_response(self):
        """测试短 AI 响应"""
        short = "Here is the answer."
        truncated = truncate_ai_response(short)
        assert truncated == short

    def test_truncate_long_ai_response(self):
        """测试长 AI 响应"""
        long_response = "Answer: " + "detail " * 500
        truncated = truncate_ai_response(long_response)
        assert len(truncated) < len(long_response)
        assert len(truncated) <= 300  # MAX_AI_RESPONSE_CHARS

    def test_truncate_ai_response_keeps_conclusion(self):
        """测试保留结论（截断中间）"""
        # 构造一个长响应，开头是结论，中间是详细分析
        response = "CONCLUSION: The answer is 42.\n" + "analysis " * 500 + "\nMore analysis."
        truncated = truncate_ai_response(response, max_chars=200)
        # 开头应保留
        assert "CONCLUSION" in truncated or "answer is 42" in truncated

    def test_truncate_ai_response_with_none(self):
        """测试 None"""
        result = truncate_ai_response(None)
        assert result == "" or result is None


# ============================================================================
# smart_compress_message 测试
# ============================================================================

class TestSmartCompressMessage:
    """智能压缩消息测试"""

    def test_compress_system_message(self):
        """测试系统消息压缩"""
        msg = FakeMessage("System prompt content", msg_type="system")
        compressed = smart_compress_message(msg)
        assert isinstance(compressed, str)
        # 系统消息应保留

    def test_compress_tool_result(self):
        """测试工具结果压缩"""
        msg = FakeMessage("Tool result: some data", msg_type="tool")
        compressed = smart_compress_message(msg)
        assert isinstance(compressed, str)

    def test_compress_ai_thinking(self):
        """测试 AI 思考压缩"""
        thinking = "Let me think step by step. " * 100
        msg = FakeMessage(thinking, msg_type="ai")
        compressed = smart_compress_message(msg)
        assert len(compressed) < len(thinking)

    def test_compress_preserves_priority_info(self):
        """测试保留优先级信息"""
        long_text = "Important: " + "x" * 1000 + " Conclusion: done."
        msg = FakeMessage(long_text, msg_type="tool")
        compressed = smart_compress_message(msg)
        # 关键信息应保留
        assert "Important" in compressed or "Conclusion" in compressed

    def test_compress_empty_message(self):
        """测试空��息"""
        msg = FakeMessage("", msg_type="ai")
        result = smart_compress_message(msg)
        assert result == ""

    def test_compress_already_short(self):
        """测试已压缩的短消息"""
        short = "Short"
        msg = FakeMessage(short, msg_type="ai")
        compressed = smart_compress_message(msg)
        assert compressed == short


# ============================================================================
# EnhancedTokenCompressor 测试
# ============================================================================

class TestEnhancedTokenCompressor:
    """增强型 Token 压缩器测试"""

    def test_compressor_initialization(self):
        """测试压缩器初始化"""
        compressor = EnhancedTokenCompressor(
            token_budget=8000,
            max_history_pairs=3,
            compression_llm=None  # 不使用 LLM
        )
        assert compressor is not None
        assert compressor.token_budget == 8000
        assert compressor.max_history_pairs == 3

    def test_compressor_with_default_config(self):
        """测试默认配置"""
        compressor = EnhancedTokenCompressor()
        assert compressor.token_budget > 0
        assert compressor.max_history_pairs > 0

    def test_compress_empty_messages(self):
        """测试压缩空消息列表"""
        compressor = EnhancedTokenCompressor()
        compressed, stats = compressor.compress([])
        assert compressed == []
        assert stats is not None

    def test_compress_single_message(self):
        """测试压缩单条消息"""
        msg = FakeMessage("Test message")
        compressor = EnhancedTokenCompressor()
        compressed, stats = compressor.compress([msg])
        assert len(compressed) >= 1  # 可能保留
        assert stats is not None

    def test_compress_short_conversation(self):
        """测试短对话压缩（不压缩）"""
        messages = [
            FakeMessage("Hello", msg_type="human"),
            FakeMessage("Hi!", msg_type="ai"),
        ]
        compressor = EnhancedTokenCompressor(token_budget=10000)  # 高预算
        compressed, stats = compressor.compress(messages)
        assert len(compressed) == len(messages)  # 不压缩
        assert stats.tokens_after == stats.tokens_before

    def test_compress_long_conversation(self):
        """测试长对话压缩"""
        # 构造长对话
        messages = []
        for i in range(20):
            messages.append(FakeMessage(f"Human message {i}", msg_type="human"))
            messages.append(FakeMessage(f"AI response {i} with lots of content " * 10, msg_type="ai"))
        
        compressor = EnhancedTokenCompressor(token_budget=2000, max_history_pairs=2)
        compressed, stats = stats = compressor.compress(messages)
        
        assert len(compressed) < len(messages)
        assert stats.tokens_after < stats.tokens_before

    def test_compress_preserves_recent_messages(self):
        """测试保留最近外部任务输入和 AI 上下文"""
        from langchain_core.messages import AIMessage

        messages = [build_external_request_message("目标 H9")]
        for i in range(10):
            messages.append(AIMessage(content=f"A{i}"))
        
        compressor = EnhancedTokenCompressor(token_budget=1000, max_history_pairs=2)
        compressed, _ = compressor.compress(messages)
        
        contents = [m.content for m in compressed]
        assert any("目标 H9" in c for c in contents)
        assert any("A9" in c for c in contents[-4:])

    def test_compression_does_not_create_human_message_for_external_request(self):
        """压缩真实运行时消息时不生成 HumanMessage。"""
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

        messages = [
            SystemMessage(content="system"),
            build_external_request_message("开始自主进化"),
        ]
        for i in range(8):
            messages.append(AIMessage(content=f"step {i} " + ("x" * 500)))

        compressor = EnhancedTokenCompressor(token_budget=1000, max_history_pairs=1)
        compressed, _ = compressor.compress(messages, keep_count=1, use_llm_summary=False)

        assert all(not isinstance(msg, HumanMessage) for msg in compressed)
        assert any("外部任务输入" in getattr(msg, "content", "") for msg in compressed)

    def test_rule_based_summary_prefers_external_request_protocol(self):
        """规则摘要应直接识别外部任务输入协议。"""
        messages = [
            build_external_request_message("修复压缩摘要"),
            FakeToolCallMessage("grep_search_tool", {"query": "external_request"}),
            FakeMessage("已定位问题", msg_type="ai"),
        ]

        compressor = EnhancedTokenCompressor(token_budget=1000, max_history_pairs=1)
        summary = compressor._rule_based_summary(messages, max_chars=300)

        assert "外部任务" in summary
        assert "修复压缩摘要" in summary

    def test_compression_stats_recording(self):
        """测试压缩统计记录"""
        compressor = EnhancedTokenCompressor()
        messages = [FakeMessage("test" * 1000, msg_type="ai") for _ in range(10)]
        
        compressed, stats = compressor.compress(messages)
        
        assert stats.tokens_before > 0
        assert stats.tokens_after > 0
        assert stats.tokens_saved > 0
        assert stats.compression_ratio > 0
        assert stats.compression_ratio <= 1.0

    def test_preemptive_compression(self):
        """测试预压缩机制"""
        compressor = EnhancedTokenCompressor(
            token_budget=1000,
            preemptive_threshold=0.6,
            forced_threshold=0.8
        )
        # 创建接近预算的消息
        messages = [FakeMessage("x" * 100, msg_type="ai") for _ in range(15)]
        
        compressed, stats = compressor.compress(messages)
        # 应该触发预压缩
        assert stats is not None


# ============================================================================
# truncate_by_priority 测试
# ============================================================================

class TestTruncateByPriority:
    """按优先级截断测试"""

    def test_truncate_prioritizes_critical(self):
        """测试 CRITICAL 优先级消息保留"""
        messages = [
            (MessagePriority.CRITICAL, "Critical content"),
            (MessagePriority.LOW, "Low priority " * 100),
        ]
        truncated = truncate_by_priority(messages, max_chars=100)
        # Critical 应保留
        assert "Critical" in truncated
        assert "Low priority" not in truncated or len(truncated) < 100

    def test_truncate_removes_trivial_first(self):
        """测试优先移除 TRIVIAL 消息"""
        messages = [
            (MessagePriority.MEDIUM, "Medium"),
            (MessagePriority.TRIVIAL, "Trivial " * 100),
            (MessagePriority.HIGH, "High"),
        ]
        truncated = truncate_by_priority(messages, max_chars=50)
        # TRIVIAL 应最先被移除
        assert "High" in truncated or "Medium" in truncated

    def test_truncate_empty_list(self):
        """测试空列表"""
        result = truncate_by_priority([], max_chars=100)
        assert result == ""

    def test_truncate_already_fits(self):
        """测试已符合预算"""
        messages = [
            (MessagePriority.HIGH, "Short"),
            (MessagePriority.MEDIUM, "Medium"),
        ]
        truncated = truncate_by_priority(messages, max_chars=1000)
        assert "Short" in truncated
        assert "Medium" in truncated


# ============================================================================
# format_compression_report 测试
# ============================================================================

class TestFormatCompressionReport:
    """压缩报告格式化测试"""

    def test_format_report_with_stats(self):
        """测试带统计的报告"""
        stats = TokenCompressionStats()
        stats.record(5000, 3000, 10, "Test summary", "test")
        
        report = format_compression_report(stats)
        assert isinstance(report, str)
        assert "5000" in report or "5000" in report
        assert "3000" in report or "3000" in report

    def test_format_report_empty_stats(self):
        """测试空统计"""
        stats = TokenCompressionStats()
        report = format_compression_report(stats)
        assert "无" in report or "0" in report or "no" in report.lower()

    def test_format_report_multiple_compressions(self):
        """测试多次压缩报告"""
        stats = TokenCompressionStats()
        stats.record(5000, 4000, 5, "First", "preemptive")
        stats.record(4000, 3000, 5, "Second", "incremental")
        stats.record(3000, 2500, 3, "Third", "forced")
        
        report = format_compression_report(stats)
        assert "3" in report  # 总次数
        assert "preemptive" in report or "incremental" in report


# ============================================================================
# TokenBudget 测试
# ============================================================================

class TestTokenBudget:
    """Token 预算测试"""

    def test_token_budget_default(self):
        """测试默认预算"""
        budget = TokenBudget()
        assert budget.total_budget == 8000
        assert budget.system_prompt_tokens == 0
        assert budget.reserved_tokens == 0

    def test_token_budget_custom(self):
        """测试自定义预算"""
        budget = TokenBudget(total_budget=10000, reserved_tokens=1000)
        assert budget.total_budget == 10000
        assert budget.reserved_tokens == 1000
        assert budget.effective_budget == 9000

    def test_token_budget_available(self):
        """测试可用 Token 计算"""
        budget = TokenBudget(total_budget=8000, system_prompt_tokens=2000)
        assert budget.available_tokens == 6000

    def test_token_budget_with_reservation(self):
        """测试预留空间"""
        budget = TokenBudget(total_budget=8000, system_prompt_tokens=3000, reserved_tokens=1000)
        assert budget.effective_budget == 7000
        assert budget.available_tokens == 4000


# ============================================================================
# CompressionRecord 测试
# ============================================================================

class TestCompressionRecord:
    """压缩记录测试"""

    def test_create_compression_record(self):
        """测试创建压缩记录"""
        record = CompressionRecord(
            timestamp=time.time(),
            before_tokens=5000,
            after_tokens=3000,
            compression_ratio=0.4,
            pairs_compressed=10,
            summary_preview="Test summary",
            compression_type="test"
        )
        assert record.before_tokens == 5000
        assert record.after_tokens == 3000
        assert record.compression_ratio == 0.4

    def test_compression_ratio_calculation(self):
        """测试压缩率计算"""
        record = CompressionRecord(
            timestamp=time.time(),
            before_tokens=1000,
            after_tokens=700,
            compression_ratio=0.0,  # 实际会计算
            pairs_compressed=5,
            summary_preview="",
            compression_type="incremental"
        )
        # ratio 应自动计算
        expected_ratio = (1000 - 700) / 1000
        assert abs(record.compression_ratio - expected_ratio) < 0.001


# ============================================================================
# MessageMeta 测试
# ============================================================================

class TestMessageMeta:
    """消息元数据测试"""

    def test_create_message_meta_default(self):
        """测试默认消息元数据"""
        meta = MessageMeta()
        assert meta.priority == MessagePriority.MEDIUM
        assert meta.is_essential is False
        assert meta.can_truncate is True
        assert meta.token_cost == 0

    def test_create_message_meta_custom(self):
        """测试自定义消息元数据"""
        meta = MessageMeta(
            priority=MessagePriority.CRITICAL,
            is_essential=True,
            can_truncate=False,
            token_cost=100
        )
        assert meta.priority == MessagePriority.CRITICAL
        assert meta.is_essential is True
        assert meta.can_truncate is False
        assert meta.token_cost == 100


# ============================================================================
# create_compressor 便捷函数测试
# ============================================================================

class TestCreateCompressor:
    """压缩器创建函数测试"""

    def test_create_default_compressor(self):
        """测试创建默认压缩器"""
        compressor = create_compressor()
        assert isinstance(compressor, EnhancedTokenCompressor)

    def test_create_with_custom_budget(self):
        """测试自定义预算"""
        compressor = create_compressor(token_budget=10000, max_history_pairs=5)
        assert compressor.token_budget == 10000
        assert compressor.max_history_pairs == 5


# ============================================================================
# 集成测试
# ============================================================================

class TestTokenManagerIntegration:
    """Token 管理器集成测试"""

    def test_full_compression_workflow(self):
        """测试完整压缩工作流"""
        # 1. 创建压缩器
        compressor = EnhancedTokenCompressor(
            token_budget=3000,
            max_history_pairs=2
        )
        
        # 2. 构造消息
        messages = [
            FakeMessage("System prompt", msg_type="system"),
            FakeMessage("User: " + "x" * 1000, msg_type="human"),
            FakeMessage("AI: " + "y" * 1000, msg_type="ai"),
            FakeMessage("User: " + "z" * 1000, msg_type="human"),
            FakeMessage("AI: " + "w" * 1000, msg_type="ai"),
        ]
        
        # 3. 压缩
        compressed, stats = compressor.compress(messages)
        
        # 4. 验证
        assert len(compressed) <= len(messages)
        assert stats.tokens_after <= stats.tokens_before

    def test_estimate_and_compress_cycle(self):
        """测试估算-压缩循环"""
        messages = [FakeMessage("Content " * 100, msg_type="ai") for _ in range(20)]
        
        # 估算 Token
        total_tokens = estimate_messages_tokens(messages)
        assert total_tokens > 0
        
        # 如果超出预算，进行压缩
        if total_tokens > 3000:
            compressor = EnhancedTokenCompressor(token_budget=3000)
            compressed, stats = compressor.compress(messages)
            final_tokens = estimate_messages_tokens(compressed)
            assert final_tokens <= 3500  # 允许一定余量

    def test_truncate_after_compression(self):
        """测试压缩后截断"""
        messages = [FakeMessage("x" * 500, msg_type="ai") for _ in range(50)]
        
        compressor = EnhancedTokenCompressor(token_budget=2000)
        compressed, _ = compressor.compress(messages)
        
        # 进一步截断
        truncated = truncate_by_priority(
            [(get_message_priority(m), m.content) for m in compressed],
            max_chars=1000
        )
        assert len(truncated) <= 1000


# ============================================================================
# 错误处理和边界测试
# ============================================================================

class TestErrorHandling:
    """错误处理测试"""

    def test_estimate_tokens_with_none(self):
        """测试 None 输入"""
        assert estimate_tokens_precise(None) == 0

    def test_estimate_tokens_with_non_string(self):
        """测试非字符串输入"""
        assert estimate_tokens_precise(123) == 0
        assert estimate_tokens_precise([]) == 0

    def test_compressor_with_invalid_budget(self):
        """测试无效预算"""
        compressor = EnhancedTokenCompressor(token_budget=0)
        # 零预算应能处理
        messages = [FakeMessage("test")]
        compressed, _ = compressor.compress(messages)
        # 至少能返回原消息或空
        assert compressed is not None

    def test_truncate_with_negative_max(self):
        """测试负的最大长度"""
        result = truncate_tool_result("test", max_chars=-1)
        # 应处理为不截断或最小长度
        assert isinstance(result, str)

    def test_message_without_content_attribute(self):
        """测试无 content 属性的消息"""
        class FakeMsg:
            pass
        msg = FakeMsg()
        # 不应崩溃
        assert get_message_priority(msg) == MessagePriority.MEDIUM


# ============================================================================
# 性能测试
# ============================================================================

class TestPerformance:
    """性能基准测试"""

    def test_estimate_tokens_performance(self):
        """测试 Token 估算性能"""
        import time
        text = "test " * 10000
        
        start = time.time()
        for _ in range(100):
            estimate_tokens_precise(text)
        elapsed = time.time() - start
        
        assert elapsed < 1.0  # 100 次应在 1 秒内

    def test_compression_performance(self):
        """测试压缩性能"""
        import time
        
        messages = [FakeMessage("x" * 200, msg_type="ai") for _ in range(100)]
        compressor = EnhancedTokenCompressor()
        
        start = time.time()
        compressed, _ = compressor.compress(messages)
        elapsed = time.time() - start
        
        assert elapsed < 2.0  # 应在 2 秒内完成

    def test_truncate_performance(self):
        """测试截断性能"""
        import time
        
        long_content = "x" * 10000
        messages = [(MessagePriority.MEDIUM, long_content) for _ in range(100)]
        
        start = time.time()
        for _ in range(10):
            truncate_by_priority(messages, max_chars=500)
        elapsed = time.time() - start
        
        assert elapsed < 1.0


# ============================================================================
# 特殊场景测试
# ============================================================================

class TestSpecialScenarios:
    """特殊场景测试"""

    def test_unicode_in_token_estimation(self):
        """测试 Unicode 字符 Token 估算"""
        unicode_text = "中文 🎉 日本語 한국어 العربية"
        tokens = estimate_tokens_precise(unicode_text)
        assert tokens > 0

    def test_very_long_single_message(self):
        """测试超长单条消息"""
        long_msg = "a" * 100000
        tokens = estimate_tokens_precise(long_msg)
        assert tokens > 10000

    def test_compressor_with_llm_callback(self):
        """测试带 LLM 回调的压缩器"""
        def mock_llm_compress(messages, max_chars):
            return "Mock compressed summary", messages[:1]
        
        compressor = EnhancedTokenCompressor(
            token_budget=1000,
            compression_llm=mock_llm_compress
        )
        messages = [FakeMessage("x" * 1000, msg_type="ai") for _ in range(5)]
        compressed, stats = compressor.compress(messages)
        # 应使用 mock LLM
        assert compressed is not None

    def test_token_estimation_edge_cases(self):
        """测试边界情况"""
        # 全是空格
        assert estimate_tokens_precise("     ") >= 0
        
        # 特殊字符
        special = "!@#$%^&*()_+-=[]{}|;:,.<>?"
        tokens = estimate_tokens_precise(special)
        assert tokens > 0

    def test_mixed_priority_truncation(self):
        """测试混合优先级截断"""
        messages = [
            (MessagePriority.CRITICAL, "System prompt kept"),
            (MessagePriority.HIGH, "Tool result kept"),
            (MessagePriority.MEDIUM, "Medium" * 100),
            (MessagePriority.LOW, "Low" * 100),
            (MessagePriority.TRIVIAL, "Trivial" * 100),
        ]
        result = truncate_by_priority(messages, max_chars=100)
        # CRITICAL 和 HIGH 应优先保留
        assert "System" in result or "Tool" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
