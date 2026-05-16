#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from core.infrastructure.agent_session import (
    get_session_state,
    reset_session_state,
    is_probable_language_drift,
)


def test_runtime_constraints_render_and_reset():
    session = reset_session_state()
    session.record_blocked_tool_pattern("cli_tool:pipe", "安全策略已拦截该模式", "read_file_tool")
    session.record_validation_result("pytest 通过", True, kind="tests")
    session.note_feedback_loop(loop_type="tests", target="pytest tests/test_demo.py", result="pytest 通过")
    session.freeze_scope("tests/test_demo.py", "已锁定当前失败锚点")
    session.set_diagnostic_phase("observe")
    session.set_reading_strategy("verify", "grep_search_tool -> read_file_tool")

    summary = session.render_runtime_constraints()
    assert "当前轮强约束" in summary
    assert "cli_tool:pipe" in summary
    assert "pytest 通过" in summary
    assert "当前阶段：观测" in summary
    assert "反馈环：tests | pytest tests/test_demo.py" in summary
    assert "范围已冻结" in summary
    assert "当前任务：验证" in summary
    assert "搜索命中 -> 读局部片段" in summary

    session.reset_runtime_constraints()
    assert session.render_runtime_constraints() == ""


def test_language_drift_heuristic():
    chinese = "我先读取当前文件，再根据结果继续判断。"
    english = (
        "I will inspect the current file, compare the validation output, "
        "trace the runtime state, and then continue the diagnosis with more observations."
    )
    assert is_probable_language_drift(chinese) is False
    assert is_probable_language_drift(english) is False

    long_english = (
        "I see the issue and I will inspect the current validation flow, compare the runtime state, "
        "review the blocked tool pattern, and continue the diagnosis with more observations before making changes. "
        "This is still natural language rather than code or a shell command."
    )
    assert is_probable_language_drift(long_english) is True

    mixed_drift = "我需要 inspect 当前 context，然后 verify 这个 result 是否已经 stable。"
    assert is_probable_language_drift(mixed_drift) is True

    technical_mix = "运行 `python -m pytest tests/test_agent_session_runtime.py` 后检查结果。"
    assert is_probable_language_drift(technical_mix) is False

    tagged_text = "<state>focused</state> 我先读取日志，再继续判断。"
    assert is_probable_language_drift(tagged_text) is False


def test_reading_sufficiency_changes_with_evidence():
    session = reset_session_state()
    session.set_reading_strategy("modify", "get_code_entity_tool -> read_file_tool")

    assert "证据还不够" in session.evaluate_reading_sufficiency()

    session.record_read_entity("core/demo.py", "Demo.run")
    session.record_read_range("core/demo.py", 10, 30, source="read_file_tool")

    assert "已足够" in session.evaluate_reading_sufficiency()


def test_clear_reading_guidance_clears_sufficiency_and_decision():
    session = reset_session_state()
    session.set_reading_strategy("verify", "grep_search_tool -> read_file_tool")
    session.set_reading_sufficiency("验证证据已具备，可继续修复或复测。")
    session.set_tool_decision("inspect_entity", ["get_code_entity_tool"], ["cli_tool"])

    session.clear_reading_guidance(clear_decision=True)
    snapshot = session.get_attention_snapshot()

    assert snapshot["reading_sufficiency"] == ""
    assert snapshot["reading_recommendation"] == ""
    assert snapshot["next_tool_intent"] == ""
    assert snapshot["recommended_tools"] == []


def test_duplicate_read_and_search_detection():
    session = reset_session_state()
    session.record_read_range("core/demo.py", 10, 20, source="read_file_tool")
    session.record_read_entity("core/demo.py", "Demo.run")
    session.record_search_query("Demo", "core")

    assert session.has_read_range_overlap("core/demo.py", 12, 18) is True
    assert session.has_read_entity("core/demo.py", "Demo.run") is True
    assert session.has_search_query("Demo", "core") is True


def test_pending_continuation_is_rendered_and_exposed():
    session = reset_session_state()
    session.record_pending_continuation(
        "read_file_tool",
        'read_file_tool(file_path="core/demo.py", offset=80, max_lines=80)',
        "core/demo.py",
    )

    summary = session.render_runtime_constraints()
    snapshot = session.get_attention_snapshot()

    assert "续读提示" in summary
    assert "core/demo.py" in summary
    assert "先补读" in summary
    assert snapshot["pending_continuations"][-1]["path"] == "core/demo.py"


def test_pending_continuation_can_be_cleared_by_path():
    session = reset_session_state()
    session.record_pending_continuation(
        "read_file_tool",
        'read_file_tool(file_path="core/demo.py", offset=80, max_lines=80)',
        "core/demo.py",
    )
    session.record_pending_continuation(
        "read_file_tool",
        'read_file_tool(file_path="core/other.py", offset=40, max_lines=80)',
        "core/other.py",
    )

    session.clear_pending_continuation(path="core/demo.py")
    snapshot = session.get_attention_snapshot()

    assert len(snapshot["pending_continuations"]) == 1
    assert snapshot["pending_continuations"][0]["path"] == "core/other.py"


def test_get_overlapping_ranges_and_latest_continuation():
    session = reset_session_state()
    session.record_read_range("core/demo.py", 10, 30)
    session.record_read_range("core/demo.py", 40, 55)
    session.record_pending_continuation(
        "read_file_tool",
        'read_file_tool(file_path="core/demo.py", offset=55, max_lines=40)',
        "core/demo.py",
    )

    overlaps = session.get_overlapping_read_ranges("core/demo.py", 25, 45)
    latest = session.get_latest_pending_continuation("core/demo.py")

    assert len(overlaps) == 2
    assert latest is not None
    assert latest["path"] == "core/demo.py"


def test_tool_decision_and_deviation_render():
    session = reset_session_state()
    session.set_tool_decision("inspect_entity", ["get_code_entity_tool", "read_file_tool"], ["cli_tool"])
    session.record_tool_deviation("cli_tool", "当前存在更合适的主通道工具。")

    summary = session.render_runtime_constraints()

    assert "下一步意图：精读实体" in summary
    assert "读目标实体 -> 读局部片段" in summary
    assert "命令兜底" in summary


def test_delegation_state_is_rendered_and_deduplicated():
    session = reset_session_state()
    session.record_delegation_start("diagnose", "分析为什么重复调用工具", {"log": "log_info/demo.jsonl"})
    rules = session.render_delegation_rules()
    assert "委派规则" in rules
    assert "当前委派中" in rules

    session.record_delegation_result(
        "diagnose",
        "分析为什么重复调用工具",
        {"log": "log_info/demo.jsonl"},
        "定位到重复调用源于相同 blocker 被重复绕过。",
        findings=["同轮重复搜索", "无新增证据仍继续推理"],
        confidence="high",
        recommended_next_action="主 agent 直接收束为停机结论",
    )
    assert session.has_recent_delegation("diagnose", "分析为什么重复调用工具", {"log": "log_info/demo.jsonl"}) is True

    summary = session.render_runtime_constraints()
    snapshot = session.get_attention_snapshot()
    assert "委派状态" in summary
    assert "最近证据" in summary
    assert snapshot["delegation_evidence_digest"]


def test_feedback_loop_and_scope_freeze_exposed_in_snapshot():
    session = reset_session_state()
    session.note_feedback_loop(loop_type="lint", target="agent.py", result="ruff lint 通过")
    session.freeze_scope("agent.py", "已形成单一文件修复锚点")
    session.note_scope_completion("当前轮已完成修复与验证")

    snapshot = session.get_attention_snapshot()

    assert snapshot["feedback_loop_ready"] is True
    assert snapshot["feedback_loop_type"] == "lint"
    assert snapshot["scope_frozen"] is True
    assert snapshot["convergence_state"] == "ready_to_stop"
    assert "修复与验证" in snapshot["stop_reason"]
