#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from core.infrastructure.reading_strategy import infer_reading_task, build_reading_strategy


def test_infer_reading_task_prefers_verify_for_test_failures():
    assert infer_reading_task("请分析 pytest 失败原因并验证修复") == "verify"


def test_infer_reading_task_prefers_modify_for_edit_intent():
    assert infer_reading_task("修改这个函数并重构读取逻辑") == "modify"


def test_build_reading_strategy_returns_tool_sequence():
    strategy = build_reading_strategy("理解这个 Python 文件的结构")

    assert strategy.task_type == "understand"
    assert "get_code_entity_tool" in strategy.recommended_tools
    assert strategy.rationale
