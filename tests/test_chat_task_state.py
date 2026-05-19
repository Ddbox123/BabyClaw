#!/usr/bin/env python3
"""chat result helper tests."""

from core.chat.chat_result_contract import build_chat_coding_result_contract
from core.chat.chat_result_formatter import format_chat_reply


def test_build_chat_coding_result_contract_extracts_structured_fields_from_tool_trace():
    contract = build_chat_coding_result_contract(
        {
            "status": "completed",
            "summary": "已完成修复并验证。",
            "tool_call_count": 3,
            "tool_trace": [
                {
                    "name": "read_file_tool",
                    "args": {"file_path": "core/ui/cli_ui.py"},
                    "result_preview": "read ok",
                },
                {
                    "name": "apply_diff_edit_tool",
                    "args": {"file_path": "core/ui/cli_ui.py"},
                    "result_preview": "patched",
                },
                {
                    "name": "run_test_for_tool",
                    "args": {"source_path": "core/ui/cli_ui.py"},
                    "result_preview": "3 passed in 0.40s",
                },
            ],
        }
    )

    assert contract["read_files"] == ["core/ui/cli_ui.py"]
    assert contract["changed_files"] == ["core/ui/cli_ui.py"]
    assert contract["verification_status"] == "passed"
    assert contract["outcome"] == "done"
    assert contract["no_change"] is False


def test_format_chat_reply_adds_structured_coding_summary():
    reply = format_chat_reply(
        {
            "status": "completed",
            "summary": "已修复问题。",
        },
        {
            "kind": "coding",
            "status": "done",
            "changed_files": ["core/ui/cli_ui.py"],
            "verification_status": "passed",
            "verification_summary": "2 passed",
        },
    )

    assert "已修复问题。" in reply
    assert "修改文件：core/ui/cli_ui.py" in reply
    assert "验证：通过。2 passed" in reply


def test_format_chat_reply_can_summarize_structured_result_without_task_snapshot():
    reply = format_chat_reply(
        {
            "status": "completed",
            "summary": "",
            "raw_output": "",
            "outcome": "done",
            "changed_files": ["core/ui/cli_ui.py"],
            "verification_status": "passed",
            "verification_summary": "3 passed in 0.40s",
        }
    )

    assert "修改文件：core/ui/cli_ui.py" in reply
    assert "验证：通过。3 passed in 0.40s" in reply
