#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from core.infrastructure.tool_recommender import decide_next_tools


def test_locate_defaults_to_search_then_symbol():
    decision = decide_next_tools({
        "reading_task": "locate",
        "reading_sufficiency": "",
        "read_ranges": {},
        "read_entities": {},
        "read_searches": [],
        "recent_blockers": [],
        "recent_validation_results": [],
    })

    assert decision.next_intent == "locate_text"
    assert "grep_search_tool" in decision.recommended_tools
    assert "cli_tool" in decision.avoid_tools


def test_pending_continuation_takes_priority():
    decision = decide_next_tools({
        "reading_task": "analyze",
        "reading_sufficiency": "",
        "read_ranges": {},
        "read_entities": {},
        "read_searches": [{"query": "Demo", "scope": "core"}],
        "recent_blockers": [{"kind": "partial_read", "summary": "需要补读"}],
        "recent_validation_results": [],
        "pending_continuations": [
            {
                "tool_name": "grep_search_tool",
                "hint": 'read_file_tool(file_path="core/demo.py", offset=0, max_lines=80)',
                "path": "core/demo.py",
            }
        ],
    })

    assert decision.next_intent == "inspect_range"
    assert decision.recommended_tools == ["read_file_tool"]
    assert "grep_search_tool" in decision.avoid_tools
    assert "cli_tool" in decision.avoid_tools
    assert "core/demo.py" in decision.reason


def test_modify_switches_to_edit_when_sufficient():
    decision = decide_next_tools({
        "reading_task": "modify",
        "reading_sufficiency": "修改上下文已足够，可开始动手并保留验证闭环。",
        "read_ranges": {"a.py": [{"start_line": 1, "end_line": 20}]},
        "read_entities": {"a.py": ["Foo.run"]},
        "read_searches": [],
        "recent_blockers": [],
        "recent_validation_results": [],
        "pending_continuations": [],
    })

    assert decision.next_intent == "edit_target"
    assert "apply_diff_edit_tool" in decision.recommended_tools
