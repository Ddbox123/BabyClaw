#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
工具结果处理测试 (test_tool_result.py)

测试 core/infrastructure/tool_result.py 中的：
- truncate_result: 超长结果截断
- format_tool_message: 工具消息格式化
- DEFAULT_MAX_CHARS 常量
"""

import sys
from pathlib import Path

import pytest
from core.infrastructure.tool_result import (
    truncate_result,
    package_tool_result,
    format_tool_message,
    DEFAULT_MAX_CHARS,
)


class TestTruncateResult:
    """truncate_result 测试"""

    def test_short_result_not_truncated(self):
        """短结果不截断"""
        result, truncated = truncate_result("hello", max_chars=100)
        assert result == "hello"
        assert truncated is False

    def test_result_at_limit_not_truncated(self):
        """等于限制长度不截断"""
        s = "A" * 10
        result, truncated = truncate_result(s, max_chars=10)
        assert result == s
        assert truncated is False

    def test_result_over_limit_truncated(self):
        """超过限制被截断"""
        s = "A" * 100
        result, truncated = truncate_result(s, max_chars=50)
        assert len(result) < len(s)
        assert truncated is True
        assert "[...结果已截断" in result

    def test_truncation_preserves_prefix(self):
        """截断保留前缀"""
        result, _ = truncate_result("ABCDEFGHIJ", max_chars=5)
        assert result.startswith("ABCDE")

    def test_default_max_chars(self):
        """使用默认限制值"""
        assert DEFAULT_MAX_CHARS == 4000

    def test_non_string_result_converted(self):
        """非字符串结果被转为字符串"""
        result, _ = truncate_result(12345)
        assert isinstance(result, str)
        assert "12345" in result

    def test_empty_string(self):
        """空字符串"""
        result, truncated = truncate_result("")
        assert result == ""
        assert truncated is False

    def test_max_chars_zero(self):
        """max_chars=0 时截断所有内容"""
        result, truncated = truncate_result("hello", max_chars=0)
        assert truncated is True
        assert "[...结果已截断" in result

    def test_list_result_converted(self):
        """列表结果被转为字符串"""
        result, _ = truncate_result([1, 2, 3], max_chars=100)
        assert isinstance(result, str)
        assert "1" in result

    def test_package_tool_result_keeps_continuation_hint_for_file_reads(self):
        raw = (
            "[文件] demo.py\n"
            "[编码] utf-8 | [行数] 400 (已截断) | [大小] 10.0 KB\n"
            "[区间] 第 1-120 行 | 已显示 120 行 | 剩余 280 行\n"
            '[续读] read_file_tool(file_path="demo.py", offset=120, max_lines=120)\n\n'
            "--- Content ---\n"
            + ("A" * 5000)
        )

        packaged = package_tool_result(raw, tool_name="read_file_tool", max_chars=240)

        assert packaged.truncated is True
        assert packaged.result_kind == "file_read"
        assert "offset=120" in packaged.continuation_hint
        assert "[截断信息]" in packaged.content or "[...结果已截断" in packaged.content

    def test_package_tool_result_compacts_file_read_with_preview(self):
        raw = (
            "[文件] demo.py\n"
            "[编码] utf-8 | [行数] 400 (已截断) | [大小] 10.0 KB\n"
            "[区间] 第 1-120 行 | 已显示 120 行 | 剩余 280 行\n"
            '[续读] read_file_tool(file_path="demo.py", offset=120, max_lines=80)\n\n'
            "--- Content ---\n"
            + "\n".join(f"第 {i} 行" for i in range(1, 160))
        )

        packaged = package_tool_result(raw, tool_name="read_file_tool", max_chars=360)

        assert packaged.truncated is True
        assert packaged.strategy in {"structured_compact", "annotated_truncate", "legacy_prefix_truncate"}
        assert "Content Preview" in packaged.content or "[截断信息]" in packaged.content

    def test_package_tool_result_compacts_search_result(self):
        raw = (
            "[搜索] 正则: Demo\n"
            "[搜索] 目录: core\n"
            "[搜索] 类型: .py\n"
            "[搜索] 找到 9 个匹配，分布在 4 个文件\n"
            "[搜索摘要]\n"
            "- core/a.py | 命中 3 处 | 行 1, 4, 8\n\n"
            + "\n".join(
                [f"📁 core/{name}.py\n" + "\n".join([f"  → 第 {i} 行 | demo" for i in range(1, 7)]) for name in ("a", "b", "c", "d")]
            )
        )

        packaged = package_tool_result(raw, tool_name="grep_search_tool", max_chars=320)

        assert packaged.truncated is True
        assert packaged.result_kind == "search"
        assert packaged.strategy in {"structured_compact", "annotated_truncate", "legacy_prefix_truncate"}


class TestFormatToolMessage:
    """format_tool_message 测试"""

    def test_returns_string_and_call_id(self):
        """返回 (result_str, tool_call_id) 元组"""
        result_str, call_id = format_tool_message(
            {"id": "call_123"}, "result text", None
        )
        assert isinstance(result_str, str)
        assert isinstance(call_id, str)
        assert "result text" in result_str

    def test_none_id_handled(self):
        """None ID 被安全处理"""
        result_str, call_id = format_tool_message(
            {"id": None}, "result"
        )
        assert call_id == ""

    def test_missing_id_handled(self):
        """缺少 id 被安全处理"""
        result_str, call_id = format_tool_message({}, "result")
        assert call_id == ""

    def test_long_result_truncated_in_format(self):
        """长结果在格式化时被截断"""
        long_result = "X" * 5000
        result_str, _ = format_tool_message(
            {"id": "call_1"}, long_result
        )
        assert len(result_str) <= DEFAULT_MAX_CHARS + 100  # 截断标记约 +50

    def test_action_param_accepted(self):
        """action 参数被接受（当前未使用）"""
        result_str, call_id = format_tool_message(
            {"id": "call_1"}, "result", action="restart"
        )
        assert result_str is not None
        assert call_id is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
