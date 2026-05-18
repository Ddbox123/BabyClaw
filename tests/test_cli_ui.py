#!/usr/bin/env python3
"""
CLI UI 渲染行为测试
"""

import json
from pathlib import Path

from rich.console import Console

from core.infrastructure.event_bus import Event, EventNames
from core.ui.ascii_art import get_avatar_manager
from core.ui.cli_ui import UIManager
from core.ui.token_display import format_token_count, format_token_report
from core.infrastructure.agent_session import get_session_state, reset_session_state


def test_stream_thought_hides_think_tags():
    ui = UIManager()
    ui._thought_history.clear()
    ui._current_thought_stream = ""

    ui.stream_thought("<think>alpha\nbeta</think>", done=True)

    assert ui._current_thought_stream == "alpha\nbeta"
    assert ui._thought_history[-1] == "alpha\nbeta"


def test_build_thought_text_shows_latest_lines():
    ui = UIManager()
    ui._current_thought_stream = "\n".join(f"line {i}" for i in range(1, 40))

    rendered = ui._build_thought_text(width=40, max_lines=6)

    assert "line 1" not in rendered
    assert "line 39" in rendered


def test_format_tool_result_lines_summarizes_json_object():
    ui = UIManager()

    lines = ui._format_tool_result_lines(
        '{"status":"success","message":"saved","count":3,"path":"workspace/demo.py","results":[1,2,3]}'
    )

    assert any("status: success" in line for line in lines)
    assert any("count: 3" in line for line in lines)
    assert not any("{" in line and "results" in line for line in lines)


def test_format_tool_args_compacts_nested_values():
    ui = UIManager()

    text = ui._format_tool_args({
        "path": "workspace/demo.py",
        "payload": {"a": 1, "b": 2},
        "items": [1, 2, 3],
    })

    assert "path=workspace/demo.py" in text
    assert "payload={2 keys}" in text
    assert "items=[3 items]" in text


def test_summarize_tool_result_prefers_single_line_summary():
    ui = UIManager()

    summary = ui._summarize_tool_result('{"status":"success","message":"saved","count":3}')

    assert "status: success" in summary
    assert "\n" not in summary


def test_render_pet_stage_contains_ground():
    ui = UIManager()

    stage = ui._render_pet_stage()

    assert "." * 10 in stage


def test_render_pet_stage_keeps_ground_on_last_line():
    ui = UIManager()
    ui.set_pet_mental_state(mood="专注", feeling="规则感知 normal", whisper="继续推进")

    stage = ui._render_pet_stage()
    last_line = stage.splitlines()[-1]

    assert "." * 10 in last_line


def test_pet_animation_step_updates_offset():
    ui = UIManager()
    ui._pet_walk_offset = 0
    ui._pet_walk_direction = 1

    ui._step_pet_animation()

    assert ui._pet_walk_offset == 1


def test_pet_stage_status_prefers_thinking_stream():
    ui = UIManager()
    ui._status = "IDLE"
    ui._current_thought_stream = "pondering"

    assert ui._get_pet_stage_status() == "thinking"


def test_pet_animation_sleeping_glides_to_rest():
    ui = UIManager()
    ui._status = "SLEEPING"
    ui._current_thought_stream = ""
    ui._pet_walk_offset = 0

    ui._step_pet_animation()

    assert ui._pet_walk_offset == 1


def test_render_pet_stage_marks_thinking_focus():
    ui = UIManager()
    ui.set_pet_mental_state(mood="专注", feeling="规则感知: normal", whisper="继续")
    ui._step_pet_animation()

    stage = ui._render_pet_stage()

    assert "? ?" in stage


def test_render_pet_stage_bubble_anchor_moves_with_pet_head():
    ui = UIManager()
    ui.set_avatar_preset("moose")
    ui._pet_walk_offset = 0
    ui._current_thought_stream = "好奇\n先看看"
    left_stage = ui._render_pet_stage()

    ui._pet_walk_offset = 10
    right_stage = ui._render_pet_stage()

    left_tail = [line for line in left_stage.splitlines() if "╰" in line][0]
    right_tail = [line for line in right_stage.splitlines() if "╰" in line][0]

    assert left_tail != right_tail


def test_render_pet_stage_shows_mental_bubble_content():
    ui = UIManager()
    ui.set_avatar_preset("moose")
    ui._current_thought_stream = ""
    ui.set_pet_mental_state(mood="专注", feeling="规则感知 normal", whisper="继续推进")

    stage = ui._render_pet_stage()

    assert "继续推进" in stage
    assert "专注" in stage


def test_build_mental_bubble_falls_back_to_thought_preview():
    ui = UIManager()
    ui.set_pet_mental_state("", "", "")
    ui._current_thought_stream = "先扫描当前工作区，再落刀。"

    lines = ui._build_mental_bubble_lines(width=12)

    assert lines
    assert lines[0].startswith("先扫描当前")


def test_build_mental_bubble_scrolls_to_latest_lines():
    ui = UIManager()
    ui.set_pet_mental_state("", "", "")
    ui._current_thought_stream = "\n".join(
        [f"第{i}行消息内容" for i in range(1, 8)]
    )

    lines = ui._build_mental_bubble_lines(width=10, max_lines=3)

    assert len(lines) == 3
    assert any("第7行" in line for line in lines)
    assert not any("第1行" in line for line in lines)


def test_render_pet_stage_shows_wider_bubble_content():
    ui = UIManager()
    ui.set_avatar_preset("moose")
    ui._current_thought_stream = "好奇\n先看看\n这个计划怎么推进"

    stage = ui._render_pet_stage()

    assert "好奇" in stage
    assert "先看看" in stage


def test_avatar_pose_art_differs_by_direction():
    avatar = get_avatar_manager("lobster")

    left = avatar.get_pose_art("walk", "left", 0)
    right = avatar.get_pose_art("walk", "right", 0)

    assert left != right


def test_secondary_avatar_pose_art_differs_by_direction():
    avatar = get_avatar_manager("cat")

    left = avatar.get_pose_art("walk", "left", 0)
    right = avatar.get_pose_art("walk", "right", 0)

    assert left != right


def test_moose_avatar_has_distinct_directions_and_walk_frames():
    avatar = get_avatar_manager("moose")

    left = avatar.get_pose_art("walk", "left", 0)
    right = avatar.get_pose_art("walk", "right", 0)
    alt = avatar.get_pose_art("walk", "right", 1)

    assert left != right
    assert right != alt


def test_ui_can_sync_avatar_preset_from_config():
    ui = UIManager()
    ui.set_avatar_preset("chick")
    assert ui.avatar.preset_name == "chick"

    ui.set_avatar_preset("lobster")
    assert ui.avatar.preset_name == "lobster"


def test_set_pet_mental_state_updates_expression_state():
    ui = UIManager()

    ui.set_pet_mental_state(mood="疲惫", feeling="上下文拥挤", whisper="调用 compress_context_tool 后再继续")

    assert ui._pet_state.mental_mood == "疲惫"
    assert ui._get_pet_stage_status() == "tired"


def test_humanize_work_state_uses_chinese_labels():
    ui = UIManager()
    ui._status = "THINKING"

    assert ui._humanize_work_state() == "思考中"


def test_runtime_metrics_follow_agent_state_signals():
    reset_session_state()
    ui = UIManager()
    ui.reset_workspace()
    ui.set_pet_mental_state(mood="自信", feeling="顺畅推进", whisper="继续")
    ui.update_status("SUCCESS")
    ui._runtime.validation_passes = 2
    ui._runtime.successful_rounds = 1

    metrics = ui._derive_runtime_metrics(ui._get_pet_snapshot())

    assert metrics["spirit"] >= 80
    assert metrics["energy"] >= 70
    assert metrics["bond"] >= 50
    assert any("自信" in item[0] for item in metrics["spirit_explain"])


def test_pet_status_panel_keeps_context_near_top_when_runtime_rows_grow():
    reset_session_state()
    ui = UIManager()
    session = get_session_state()
    ui.note_turn_start(7)
    ui.note_token_usage(1234, 567, observed=True)
    ui.note_context_window(8192, 204800)
    ui.set_pet_mental_state(mood="专注", feeling="顺畅推进", whisper="继续")
    ui.update_status("THINKING")
    session.set_reading_strategy("inspect_file", "先读局部，再决定是否扩散")
    session.set_tool_decision("read_file", ["read_file_tool", "grep_search_tool"], ["cli_tool"])
    session.set_reading_sufficiency("enough")
    session.feedback_loop_ready = True
    session.feedback_loop_type = "active"
    session.feedback_loop_target = "状态面板"
    session.convergence_state = "narrowing"
    session.scope_anchor = "core/ui/cli_ui.py"
    session.stop_reason = "待验证"
    session.record_delegation_start("inspect", "审查 UI 状态区", ["core/ui/cli_ui.py"])

    panel = ui._build_pet_panel()
    console = Console(record=True, width=120)
    console.print(panel)
    text = console.export_text()

    assert "本轮消耗" in text
    assert "累计 Token" in text
    assert "请求上下文" in text
    assert "委派  子 agent 干活中" in text


def test_runtime_metrics_include_turn_cycle_and_age():
    reset_session_state()
    ui = UIManager()
    ui.reset_workspace()
    ui.note_turn_start(3)
    ui.update_status("THINKING", iterations=7)
    ui._runtime.completed_rounds = 2

    pet = ui._get_pet_snapshot()
    pet["age"] = 6
    metrics = ui._derive_runtime_metrics(pet)

    assert metrics["current_turn"] == 3
    assert metrics["react_step"] == 7
    assert metrics["completed_rounds"] == 2
    assert metrics["pet_age"] == 6


def test_pet_snapshot_age_uses_completed_evolutions_not_pet_level():
    ui = UIManager()
    ui.reset_workspace()
    ui._completed_evolutions = 2

    pet = ui._get_pet_snapshot()

    assert pet["age"] == 2


def test_successful_evolution_close_increments_age_once(tmp_path):
    ui = UIManager()
    ui.reset_workspace()
    ui._runtime_state_path = tmp_path / "ui_runtime_state.json"
    ui._completed_evolutions = 0
    ui._seen_closed_evolution_txns = set()

    event = Event(
        EventNames.EVOLUTION_TXN_CLOSED,
        {"txn_id": "txn-demo", "status": "success"},
    )
    ui._on_evolution_txn_closed(event)
    ui._on_evolution_txn_closed(event)

    assert ui._completed_evolutions == 1

    data = json.loads(ui._runtime_state_path.read_text(encoding="utf-8"))
    assert data["completed_evolutions"] == 1
    assert data["seen_closed_evolution_txns"] == ["txn-demo"]


def test_failed_evolution_close_does_not_increment_age(tmp_path):
    ui = UIManager()
    ui.reset_workspace()
    ui._runtime_state_path = tmp_path / "ui_runtime_state.json"
    ui._completed_evolutions = 0

    ui._on_evolution_txn_closed(
        Event(EventNames.EVOLUTION_TXN_CLOSED, {"txn_id": "txn-failed", "status": "failed"})
    )

    assert ui._completed_evolutions == 0


def test_runtime_metrics_drop_after_failures_and_drift():
    reset_session_state()
    ui = UIManager()
    ui.reset_workspace()
    ui.set_pet_mental_state(mood="疲惫", feeling="重复 thrashing", whisper="暂停，重新审视")
    ui.update_status("ERROR")
    ui._runtime.tool_errors = 2
    ui._runtime.failed_rounds = 1
    ui._runtime.validation_failures = 1

    metrics = ui._derive_runtime_metrics(ui._get_pet_snapshot())

    assert metrics["spirit"] < 70
    assert metrics["energy"] < 75
    assert metrics["stability"] < 70
    assert any("疲惫" in item[0] for item in metrics["spirit_explain"]) or any("验证失败" in item[0] for item in metrics["spirit_explain"])
    assert any("失败回合" in item[0] for item in metrics["bond_explain"]) or any("验证失败" in item[0] for item in metrics["bond_explain"])


def test_format_metric_explain_colors_positive_and_negative_factors():
    ui = UIManager()

    text = ui._format_metric_explain("心气", [("自信", 14), ("工具错误x1", -5)])

    assert "[green]自信+14[/green]" in text
    assert "[red]工具错误x1-5[/red]" in text


def test_runtime_metrics_include_reading_sufficiency():
    reset_session_state()
    from core.infrastructure.agent_session import get_session_state

    session = get_session_state()
    session.set_reading_strategy("modify", "get_code_entity_tool -> read_file_tool")
    session.set_reading_sufficiency("修改上下文已足够，可开始动手并保留验证闭环。")

    ui = UIManager()
    ui.reset_workspace()
    metrics = ui._derive_runtime_metrics(ui._get_pet_snapshot())

    assert metrics["reading_task"] == "modify"
    assert "可开始动手" in metrics["reading_sufficiency"]


def test_pet_panel_renders_reading_sufficiency():
    reset_session_state()
    from core.infrastructure.agent_session import get_session_state

    session = get_session_state()
    session.set_reading_strategy("verify", "grep_search_tool -> read_file_tool")
    session.set_reading_sufficiency("验证证据已具备，可继续修复或复测。")

    ui = UIManager()
    ui.reset_workspace()
    panel = ui._build_pet_panel()
    console = Console(record=True, width=120)
    console.print(panel)
    rendered = console.export_text()

    assert "验证证据已具备" in rendered


def test_runtime_metrics_include_tool_decision():
    reset_session_state()
    from core.infrastructure.agent_session import get_session_state

    session = get_session_state()
    session.set_tool_decision("inspect_entity", ["get_code_entity_tool", "read_file_tool"], ["cli_tool"])

    ui = UIManager()
    ui.reset_workspace()
    metrics = ui._derive_runtime_metrics(ui._get_pet_snapshot())

    assert metrics["next_tool_intent"] == "inspect_entity"
    assert metrics["next_tool_intent_label"] == "精读实体"
    assert metrics["recommended_tools"][0] == "get_code_entity_tool"
    assert metrics["recommended_tools_label"].startswith("读目标实体")
    assert "cli_tool" in metrics["avoid_tools"]
    assert "命令兜底" in metrics["avoid_tools_label"]


def test_runtime_metrics_ignore_hint_only_continuation_from_blocker_penalty():
    reset_session_state()
    from core.infrastructure.agent_session import get_session_state

    session = get_session_state()
    session.record_blocker(
        "continuation_focus",
        "当前已存在 core/demo.py 的未完成续读。",
        "先顺着续读继续。",
        severity="hint",
    )

    ui = UIManager()
    ui.reset_workspace()
    metrics = ui._derive_runtime_metrics(ui._get_pet_snapshot())

    assert not any(label == "阻塞点" for label, _ in metrics["spirit_explain"])
    assert not any(label == "阻塞堆积" for label, _ in metrics["energy_explain"])


def test_pet_panel_renders_tool_decision():
    reset_session_state()
    from core.infrastructure.agent_session import get_session_state

    session = get_session_state()
    session.set_tool_decision("inspect_entity", ["get_code_entity_tool", "read_file_tool"], ["cli_tool"])
    session.set_reading_sufficiency("理解上下文已基本够用，可开始归纳实现或准备修改。")

    ui = UIManager()
    ui.reset_workspace()
    panel = ui._build_pet_panel()
    console = Console(record=True, width=120)
    console.print(panel)
    rendered = console.export_text()

    assert "精读实体" in rendered
    assert "读目标实体 -> 读局部片段" in rendered
    assert "命令兜底" in rendered


def test_pet_panel_renders_turn_cycle_and_age():
    ui = UIManager()
    ui.reset_workspace()
    ui.note_turn_start(5)
    ui.update_status("THINKING", iterations=3)
    ui._runtime.completed_rounds = 4

    panel = ui._build_pet_panel()
    console = Console(record=True, width=120)
    console.print(panel)
    rendered = console.export_text()

    assert "第 5 轮" in rendered
    assert "ReAct步" in rendered
    assert "完成轮" in rendered
    assert "岁数" in rendered
    assert "3" in rendered
    assert "4" in rendered


def test_pet_panel_renders_turn_and_total_tokens():
    ui = UIManager()
    ui.reset_workspace()
    ui.note_turn_start(3)
    ui.note_token_usage(120, 45, observed=True)
    ui.note_token_usage(30, 15, observed=True)
    ui.update_status("THINKING", input_tokens=150, output_tokens=60)

    panel = ui._build_pet_panel()
    console = Console(record=True, width=120)
    console.print(panel)
    rendered = console.export_text()

    assert "本轮消耗" in rendered
    assert "累计 Token" in rendered
    assert "In 150" in rendered
    assert "Out 60" in rendered
    assert "Σ 210" in rendered


def test_format_token_count_uses_compact_units():
    assert format_token_count(999) == "999"
    assert format_token_count(1000) == "1K"
    assert format_token_count(1500) == "1.5K"
    assert format_token_count(7_000_000) == "7M"
    assert format_token_report(1200, 6_800_000) == "Token: 1.2K + 6.8M = 6.8M"


def test_pet_panel_compacts_large_token_counts():
    ui = UIManager()
    ui.reset_workspace()
    ui.note_turn_start(3)
    ui._turn_input_tokens = 2400
    ui._turn_output_tokens = 75
    ui._total_input_tokens = 7_000_000
    ui._total_output_tokens = 512_000
    ui.note_context_window(1234, 204800)

    panel = ui._build_pet_panel()
    console = Console(record=True, width=120)
    console.print(panel)
    rendered = console.export_text()

    assert "In 2.4K" in rendered
    assert "Out 75" in rendered
    assert "Σ 2.5K" in rendered
    assert "In 7M" in rendered
    assert "Out 512K" in rendered
    assert "Σ 7.5M" in rendered
    assert "/ 204.8K" in rendered


def test_note_token_usage_updates_turn_and_total_counts():
    ui = UIManager()
    ui.reset_workspace()
    ui.note_turn_start(2)
    start_input = ui._total_input_tokens
    start_output = ui._total_output_tokens

    ui.note_token_usage(120, 45, observed=True)
    ui.note_token_usage(30, 15, observed=True)

    assert ui._turn_input_tokens == 150
    assert ui._turn_output_tokens == 60
    assert ui._total_input_tokens == start_input + 150
    assert ui._total_output_tokens == start_output + 60


def test_token_totals_persist_across_workspace_reset(tmp_path):
    ui = UIManager()
    ui.reset_workspace()
    ui._runtime_state_path = tmp_path / "ui_runtime_state.json"
    ui._total_input_tokens = 0
    ui._total_output_tokens = 0

    ui.note_token_usage(120, 45, observed=True)
    ui.reset_workspace()

    assert ui._total_input_tokens == 120
    assert ui._total_output_tokens == 45

    data = json.loads(ui._runtime_state_path.read_text(encoding="utf-8"))
    assert data["total_input_tokens"] == 120
    assert data["total_output_tokens"] == 45


def test_token_totals_load_from_runtime_state_file(tmp_path):
    state_path = tmp_path / "ui_runtime_state.json"
    state_path.write_text(
        json.dumps({"total_input_tokens": 321, "total_output_tokens": 54}),
        encoding="utf-8",
    )

    ui = UIManager()
    ui.reset_workspace()
    ui._runtime_state_path = state_path
    ui._load_runtime_totals()

    assert ui._total_input_tokens == 321
    assert ui._total_output_tokens == 54


def test_completed_evolutions_backfills_from_db_when_runtime_state_is_legacy(tmp_path, monkeypatch):
    import sqlite3

    db_path = tmp_path / "agent_brain.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE EvolutionTransaction (
                txn_id TEXT PRIMARY KEY,
                opened_at TEXT NOT NULL,
                closed_at TEXT,
                base_rev TEXT,
                status TEXT NOT NULL,
                summary TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO EvolutionTransaction VALUES (?, ?, ?, ?, ?, ?)",
            ("txn-ok-1", "t0", "t1", "rev", "success", ""),
        )
        conn.execute(
            "INSERT INTO EvolutionTransaction VALUES (?, ?, ?, ?, ?, ?)",
            ("txn-open", "t0", None, "rev", "success", ""),
        )
        conn.execute(
            "INSERT INTO EvolutionTransaction VALUES (?, ?, ?, ?, ?, ?)",
            ("txn-failed", "t0", "t2", "rev", "failed", ""),
        )

    class FakeWorkspace:
        def get_db_connection(self):
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            return conn

    monkeypatch.setattr(
        "core.infrastructure.workspace_manager.get_workspace",
        lambda: FakeWorkspace(),
    )

    state_path = tmp_path / "ui_runtime_state.json"
    state_path.write_text(
        json.dumps({"total_input_tokens": 321, "total_output_tokens": 54}),
        encoding="utf-8",
    )

    ui = UIManager()
    ui.reset_workspace()
    ui._runtime_state_path = state_path
    ui._completed_evolutions = 0
    ui._seen_closed_evolution_txns = set()
    ui._load_runtime_totals()

    assert ui._completed_evolutions == 1
    assert ui._seen_closed_evolution_txns == {"txn-ok-1"}


def test_pet_panel_renders_context_window_usage():
    ui = UIManager()
    ui.reset_workspace()
    ui.note_context_window(1234, 32768)

    panel = ui._build_pet_panel()
    console = Console(record=True, width=120)
    console.print(panel)
    rendered = console.export_text()

    assert "请求上下文" in rendered
    assert "上下文当前" in rendered
    assert "1.2K" in rendered
    assert "32.8K" in rendered
    assert "3%" in rendered


def test_context_window_persists_runtime_state(tmp_path):
    ui = UIManager()
    ui.reset_workspace()
    ui._runtime_state_path = tmp_path / "ui_runtime_state.json"

    ui.note_context_window(2048, 8192)

    data = json.loads(ui._runtime_state_path.read_text(encoding="utf-8"))
    assert data["current_context_tokens"] == 2048
    assert data["context_token_limit"] == 8192
    assert data["status"] == "IDLE"


def test_pet_panel_distinguishes_request_context_from_turn_usage():
    ui = UIManager()
    ui.reset_workspace()
    ui.note_turn_start(4)
    ui.note_context_window(1000, 10000)
    ui.note_token_usage(1000, 50, observed=True)
    ui.note_context_window(1400, 10000)
    ui.note_token_usage(1400, 25, observed=True)

    panel = ui._build_pet_panel()
    console = Console(record=True, width=120)
    console.print(panel)
    rendered = console.export_text()

    assert "请求上下文" in rendered
    assert "本轮消耗" in rendered
    assert "In 1.4K" in rendered
    assert "In 2.4K" in rendered
    assert "Out 75" in rendered
    assert "Σ 2.5K" in rendered

def test_compact_sentence_truncates_cleanly():
    ui = UIManager()

    text = ui._compact_sentence("规则感知: productive and very stable", limit=12)

    assert text.endswith("…")


def test_conversation_panel_renders_delegation_evidence():
    ui = UIManager()
    ui.reset_workspace()
    ui.set_shell_mode("self_evolution")
    ui.add_content("主任务流内容")
    ui.add_delegation_evidence("已定位重复调用源头", next_action="主 agent 收束", confidence="high")

    panel = ui._build_conversation_panel()
    console = Console(record=True, width=120)
    console.print(panel)
    rendered = console.export_text()

    assert "[子]" in rendered
    assert "已定位重复调用源头" in rendered


def test_conversation_panel_renders_subagent_process_and_thought():
    ui = UIManager()
    ui.reset_workspace()
    ui.set_shell_mode("self_evolution")
    ui.start_subagent_activity("diagnose", "分析为什么重复调用工具", {"log": "log_info/demo.jsonl"})
    ui.finish_subagent_activity(
        status="completed",
        summary="已定位重复读取链路",
        findings=["重复调用 read_file_tool", "没有消费已读证据"],
        evidence=["recent_blockers", "delegation_history"],
        next_action="主 agent 收束",
        process="● read_file_tool agent.py\nok read_file_tool 已读取 80 行",
        thought="发现:\n- 重复调用 read_file_tool\n过程:\n先看 attention snapshot，再看最近工具轨迹。",
    )

    panel = ui._build_conversation_panel()
    console = Console(record=True, width=120)
    console.print(panel)
    rendered = console.export_text()

    assert "任务流" in rendered
    assert "[子]" in rendered
    assert "已定位重复读取链路" in rendered
    assert "重复调用 read_file_tool" in rendered
    assert "已读取 80 行" in rendered
    assert "先看 attention snapshot" in rendered


def test_conversation_panel_merges_all_subagent_blocks_and_uses_taller_panel():
    ui = UIManager()
    ui.reset_workspace()
    ui.set_shell_mode("self_evolution")
    for idx in range(1, 6):
        ui.add_subagent_process(f"过程块 {idx}\n第 {idx} 段")
    for idx in range(1, 4):
        ui.set_subagent_thought(f"思考片段 {idx}\n继续分析 {idx}")

    panel = ui._build_conversation_panel()
    console = Console(record=True, width=120, height=40)
    console.print(panel)
    rendered = console.export_text()

    assert "任务流" in rendered
    assert "[子]" in rendered
    assert "过程块 1" in rendered
    assert "过程块 5" in rendered
    assert "思考片段 1" in rendered
    assert "思考片段 3" in rendered


def test_conversation_panel_renders_live_subagent_thought_stream():
    ui = UIManager()
    ui.reset_workspace()
    ui.set_shell_mode("self_evolution")
    ui.start_subagent_activity("diagnose", "分析为什么重复调用工具", {"log": "log_info/demo.jsonl"})
    ui.add_subagent_process("START read_file_tool agent.py")
    ui.stream_subagent_thought("先看 attention snapshot\n再看工具轨迹", done=False)

    panel = ui._build_conversation_panel()
    console = Console(record=True, width=120)
    console.print(panel)
    rendered = console.export_text()

    assert "思路(进行中)" in rendered
    assert "[子]" in rendered
    assert "attention snapshot" in rendered


def test_conversation_panel_renders_live_main_thought_stream_first():
    ui = UIManager()
    ui.reset_workspace()
    ui.set_shell_mode("self_evolution")
    ui.add_content("主任务流内容")
    ui.stream_thought("先看当前目标\n再检查最近改动", done=False)

    panel = ui._build_conversation_panel()
    console = Console(record=True, width=120)
    console.print(panel)
    rendered = console.export_text()

    assert "思考(进行中)" in rendered
    assert "工作区" in rendered
    assert "[主]" in rendered
    assert "先看当前目标" in rendered
    assert "主任务流内容" in rendered


def test_tool_events_are_labeled_as_main_agent_in_conversation():
    ui = UIManager()
    ui.reset_workspace()
    ui.set_shell_mode("self_evolution")

    ui.print_tool_start("read_file_tool", {"path": "agent.py", "start_line": 1})
    ui.print_tool_result("read_file_tool", '{"status":"success","lines":80}', success=True)

    panel = ui._build_conversation_panel()
    console = Console(record=True, width=120)
    console.print(panel)
    rendered = console.export_text()

    assert "[主]" in rendered
    assert "工作区" in rendered
    assert "read_file_tool" in rendered


def test_conversation_panel_uses_fixed_thought_and_workspace_regions():
    ui = UIManager()
    ui.reset_workspace()
    ui.set_shell_mode("self_evolution")

    ui.stream_thought("先看目标\n再看日志", done=False)
    ui.add_content("模型输出内容")
    ui.print_tool_start("grep_search_tool", {"regex_pattern": "Layout"})

    panel = ui._build_conversation_panel()
    console = Console(record=True, width=120, height=36)
    console.print(panel)
    rendered = console.export_text()

    assert "任务流" in rendered
    assert "思考" in rendered
    assert "工作区" in rendered
    assert "先看目标" in rendered
    assert "模型输出内容" in rendered
    assert "grep_search_tool" in rendered


def test_agent_badge_only_appears_once_per_block():
    ui = UIManager()
    ui.reset_workspace()

    lines = ui._prefixed_agent_lines("main", "第一行\n第二行\n第三行")

    assert lines[0].startswith("[bold steel_blue1][主][/bold steel_blue1]")
    assert lines[1].startswith("    [dim]|[/dim] ")
    assert lines[2].startswith("    [dim]|[/dim] ")


def test_conversation_panel_no_longer_uses_separate_subagent_panel():
    ui = UIManager()
    ui.reset_workspace()
    ui.set_shell_mode("self_evolution")
    ui.start_subagent_activity("inspect", "检查统一任务流", {"path": "core/ui/cli_ui.py"})

    panel = ui._build_conversation_panel()
    console = Console(record=True, width=120)
    console.print(panel)
    rendered = console.export_text()

    assert "子 Agent 过程与思路" not in rendered
    assert "委派证据" not in rendered
    assert "[子]" in rendered


def test_chat_panel_renders_split_dialog_history():
    ui = UIManager()
    ui.reset_workspace()
    ui.set_shell_mode("chat")
    ui.load_chat_messages(
        [
            {"role": "user", "content": "你好", "timestamp": "2026-05-01T12:00:00"},
            {"role": "assistant", "content": "你好，我在。", "timestamp": "2026-05-01T12:00:01"},
        ]
    )

    panel = ui._build_conversation_panel()
    console = Console(record=True, width=120, height=36)
    console.print(panel)
    rendered = console.export_text()

    assert "Vibelution Chat" in rendered
    assert "会话概览" in rendered
    assert "最近对话" in rendered
    assert "2 条消息" in rendered
    assert "使用提示" not in rendered
    assert "当前状态" in rendered
    assert "概览" in rendered
    assert "角色" in rendered
    assert "你" in rendered
    assert "Agent" in rendered
    assert "12:00" in rendered
    assert "12:00:00" not in rendered
    assert "你好，我在。" in rendered
    assert "对话记录" not in rendered
    assert "系统日志" not in rendered


def test_chat_recent_dialog_hides_assistant_thought_content():
    ui = UIManager()
    ui.reset_workspace()
    ui.set_shell_mode("chat")
    ui.load_chat_messages(
        [
            {"role": "user", "content": "你好", "timestamp": "2026-05-01T12:00:00"},
            {
                "role": "assistant",
                "content": "<think>内部推理，不该展示</think>真正回复",
                "timestamp": "2026-05-01T12:00:01",
            },
        ]
    )

    panel = ui._build_conversation_panel()
    console = Console(record=True, width=120, height=36)
    console.print(panel)
    rendered = console.export_text()

    assert "真正回复" in rendered
    assert "内部推理，不该展示" not in rendered


def test_chat_recent_dialog_keeps_continuation_text_bright():
    ui = UIManager()
    ui.reset_workspace()
    ui.set_shell_mode("chat")
    ui.load_chat_messages(
        [
            {
                "role": "assistant",
                "content": "这是一条比较长的回复，需要换行显示，看看续行是不是还保持统一亮度。",
                "timestamp": "2026-05-01T12:00:01",
            },
        ]
    )

    lines = ui._build_chat_recent_lines(width=16)

    assert len(lines) >= 2
    assert "[white]" in lines[0]
    assert lines[1].startswith("[dim]   ·[/dim] [white]")
    assert "[/white]" in lines[1]


def test_chat_dialog_block_renders_message_cards_with_recent_hint():
    ui = UIManager()
    ui.reset_workspace()
    ui.set_shell_mode("chat")
    ui.load_chat_messages(
        [
            {"role": "user", "content": "先看这个页面", "timestamp": "2026-05-01T12:00:00"},
            {"role": "assistant", "content": "好，我先看右侧布局。", "timestamp": "2026-05-01T12:00:02"},
        ]
    )

    block = ui._build_chat_dialog_block(width=64)
    console = Console(record=True, width=90, height=30)
    console.print(block)
    rendered = console.export_text()

    assert "不截断单条消息" in rendered
    assert "先看这个页面" in rendered
    assert "好，我先看右侧布局。" in rendered
    assert "12:00" in rendered


def test_chat_dialog_block_keeps_full_multiline_assistant_reply():
    ui = UIManager()
    ui.reset_workspace()
    ui.set_shell_mode("chat")
    ui.load_chat_messages(
        [
            {
                "role": "assistant",
                "content": "\n".join(
                    [
                        "第1段：先说明现象。",
                        "第2段：再说明定位过程。",
                        "第3段：接着说明修改点。",
                        "第4段：然后说明验证方法。",
                        "第5段：最后补充后续建议。",
                    ]
                ),
                "timestamp": "2026-05-01T12:00:01",
            },
        ]
    )

    block = ui._build_chat_dialog_block(width=64)
    console = Console(record=True, width=90, height=30)
    console.print(block)
    rendered = console.export_text()

    assert "第1段：先说明现象。" in rendered
    assert "第4段：然后说明验证方法。" in rendered
    assert "第5段：最后补充后续建议。" in rendered
    assert "…" not in rendered


def test_chat_dialog_block_renders_full_history_without_message_cap():
    ui = UIManager()
    ui.reset_workspace()
    ui.set_shell_mode("chat")
    ui.load_chat_messages(
        [
            {"role": "user", "content": f"第{i}条消息", "timestamp": f"2026-05-01T12:00:0{i}"}
            for i in range(6)
        ]
    )

    block = ui._build_chat_dialog_block(width=64)
    console = Console(record=True, width=90, height=48)
    console.print(block)
    rendered = console.export_text()

    assert "第0条消息" in rendered
    assert "第5条消息" in rendered


def test_chat_panel_prefers_latest_messages_when_height_is_limited():
    ui = UIManager()
    ui.console = Console(record=True, width=120, height=36)
    ui.reset_workspace()
    ui.set_shell_mode("chat")
    ui.set_chat_task_snapshot({"title": "现在看看整个项目，然后向我汇报", "status": "reading"})
    ui.load_chat_messages(
        [
            {"role": "user", "content": "这轮请求请你自己判断是否需要切控制台", "timestamp": "2026-05-16T19:35:00"},
            {"role": "user", "content": "你好", "timestamp": "2026-05-16T19:35:10"},
            {"role": "assistant", "content": "收到：你好", "timestamp": "2026-05-16T19:35:20"},
            {"role": "user", "content": "你好啊", "timestamp": "2026-05-16T19:38:00"},
            {"role": "assistant", "content": "收到：你好啊", "timestamp": "2026-05-16T19:38:05"},
            {
                "role": "user",
                "content": "再试一条更长的消息，看看底部到底还能不能露出来，以及左右两栏会不会继续乱。",
                "timestamp": "2026-05-16T19:39:00",
            },
            {"role": "assistant", "content": "可以，我继续检查布局，把底部消息也露出来。", "timestamp": "2026-05-16T19:39:08"},
            {"role": "user", "content": "最后一条用户消息", "timestamp": "2026-05-16T19:40:00"},
            {"role": "assistant", "content": "最后一条 assistant 回复", "timestamp": "2026-05-16T19:40:10"},
        ]
    )

    panel = ui._build_conversation_panel()
    console = ui.console
    console.print(panel)
    rendered = console.export_text()

    assert "最后一条用户消息" in rendered
    assert "最后一条 assistant 回复" in rendered
    assert "这轮请求请你自己判断是否需要切控制台" not in rendered


def test_chat_identity_block_uses_compact_workspace_summary():
    ui = UIManager()
    ui.reset_workspace()
    ui.set_shell_mode("chat")

    panel = ui._build_conversation_panel()
    console = Console(record=True, width=120, height=36)
    console.print(panel)
    rendered = console.export_text()

    assert "Chat Session" in rendered
    assert "角色" in rendered
    assert "当前状态" in rendered
    assert str(Path.cwd()) not in rendered


def test_chat_identity_block_keeps_avatar_separate_from_summary_lines():
    ui = UIManager()
    ui.console = Console(record=True, width=120, height=36)
    ui.reset_workspace()
    ui.set_shell_mode("chat")
    ui.set_avatar_preset("moose")
    ui.set_chat_task_snapshot({"title": "修复输入框定位问题", "status": "reading"})

    panel = ui._build_conversation_panel()
    console = ui.console
    console.print(panel)
    rendered = console.export_text()

    mode_line = next(line for line in rendered.splitlines() if "模式" in line)
    assert "(oo)" not in mode_line
    assert "^__^" in rendered
    assert "Chat Coding" in rendered
    ui.set_avatar_preset("lobster")


def test_chat_identity_block_shows_active_task_status():
    ui = UIManager()
    ui.reset_workspace()
    ui.set_shell_mode("chat")
    ui.set_chat_task_snapshot(
        {
            "title": "修复输入框定位问题",
            "status": "verifying",
            "verification_status": "passed",
            "verification_summary": "3 passed",
            "metadata": {"resumed": True},
        }
    )

    panel = ui._build_conversation_panel()
    console = Console(record=True, width=120, height=36)
    console.print(panel)
    rendered = console.export_text()

    assert "修复输入框定位问题" in rendered
    assert "验证中" in rendered
    assert "已通过" in rendered
    assert "流程" in rendered
    assert "Chat Coding" in rendered


def test_chat_identity_block_stacks_avatar_above_summary_to_avoid_overlap():
    ui = UIManager()
    ui.console = Console(record=True, width=88, height=36)
    ui.reset_workspace()
    ui.set_shell_mode("chat")
    ui.set_chat_task_snapshot({"title": "修复输入框定位问题", "status": "reading"})

    panel = ui._build_conversation_panel()
    console = ui.console
    console.print(panel)
    rendered = console.export_text()

    mode_line = next(line for line in rendered.splitlines() if "模式" in line)
    assert "(oo)" not in mode_line
    assert "概览" in rendered
    assert "Chat Coding" in rendered
    assert "当前状态" in rendered


def test_chat_home_layout_gives_more_width_to_dialog_on_wide_terminal():
    ui = UIManager()
    ui.console = Console(record=True, width=120, height=36)

    left_ratio, right_ratio, right_text_width = ui._chat_home_layout_metrics()

    assert right_ratio > left_ratio
    assert right_text_width > 62


def test_chat_mode_requests_larger_terminal_target():
    ui = UIManager()

    assert ui._terminal_resize_target("chat") == (150, 44)
    assert ui._terminal_resize_target("shell") == (140, 40)


def test_chat_mode_resize_is_skipped_for_non_tty_console(monkeypatch):
    ui = UIManager()
    ui.console = Console(record=True, width=120, height=36)
    called = {}

    monkeypatch.setattr(ui, "_request_terminal_resize", lambda cols, rows: called.setdefault("size", (cols, rows)))

    resized = ui._ensure_terminal_footprint("chat")

    assert resized is False
    assert called == {}


def test_chat_dialog_block_keeps_full_markdown_reply_and_tool_calls():
    ui = UIManager()
    ui.reset_workspace()
    ui.set_shell_mode("chat")
    ui.load_chat_messages(
        [
            {
                "role": "assistant",
                "content": "\n".join(
                    [
                        "好的，我已经完成了对项目的全面浏览。以下是我的汇报：",
                        "---",
                        "## Vibelution 项目全景汇报",
                        "### 一、项目规模",
                        "| 指标 | 数值 |",
                        "|------|------|",
                        "```python",
                        "print(123)",
                        "```",
                    ]
                ),
                "timestamp": "2026-05-01T12:00:01",
                "tool_calls": ["read_file_tool", "run_test_for_tool"],
            }
        ]
    )

    block = ui._build_chat_dialog_block(width=64)
    console = Console(record=True, width=90, height=30)
    console.print(block)
    rendered = console.export_text()

    assert "## Vibelution 项目全景汇报" in rendered
    assert "### 一、项目规模" in rendered
    assert "| 指标 | 数值 |" in rendered
    assert "|------|------|" in rendered
    assert "```python" in rendered
    assert "```" in rendered
    assert "工具" in rendered
    assert "read_file_tool -> run_test_for_tool" in rendered


def test_chat_dialog_block_expands_latest_message_when_height_allows():
    ui = UIManager()
    ui.reset_workspace()
    ui.set_shell_mode("chat")
    ui.load_chat_messages(
        [
            {"role": "user", "content": "现在看看整个项目，然后向我汇报", "timestamp": "2026-05-01T12:00:00"},
            {
                "role": "assistant",
                "content": "\n".join(
                    [
                        "好的，我已经完成了对项目的全面浏览。以下是我的汇报：",
                        "---",
                        "## Vibelution 项目全景汇报",
                        "### 一、项目规模",
                        "| 指标 | 数值 |",
                        "|------|------|",
                        "已查看：agent.py, main.py, core/ui/cli_ui.py",
                    ]
                ),
                "timestamp": "2026-05-01T12:00:01",
            },
        ]
    )

    block = ui._build_chat_dialog_block(width=74, height_budget=18)
    console = Console(record=True, width=96, height=30)
    console.print(block)
    rendered = console.export_text()

    assert "Vibelution 项目全景汇报" in rendered
    assert "一、项目规模" in rendered
    assert "指标 | 数值" in rendered
    assert "已查看：agent.py, main.py, core/ui/cli_ui.py" in rendered


def test_chat_dialog_block_message_card_reaches_right_edge():
    ui = UIManager()
    ui.reset_workspace()
    ui.set_shell_mode("chat")
    ui.load_chat_messages(
        [
            {
                "role": "assistant",
                "content": "这是一条需要尽量铺满右栏的消息。",
                "timestamp": "2026-05-01T12:00:01",
            }
        ]
    )

    block = ui._build_chat_dialog_block(width=74, height_budget=18)
    console = Console(record=True, width=96, height=20)
    console.print(block)
    rendered = console.export_text()

    border_line = next(line for line in rendered.splitlines() if "┐" in line)
    assert len(border_line.rstrip()) >= 70


def test_chat_shell_snapshot_uses_dedicated_input_layout():
    ui = UIManager()
    ui.console = Console(record=True, width=120, height=36)
    ui.reset_workspace()
    ui.set_shell_mode("chat")

    console = ui.console
    console.print(ui.render_shell_snapshot())
    rendered = console.export_text()

    assert "消息输入" in rendered
    assert "输入消息..." in rendered
    assert "Chat Session" in rendered
    assert "Enter 发送  /back 返回" in rendered
    assert "查看 chat 提示" not in rendered
    assert "等待首轮请求" in rendered


def test_chat_shell_snapshot_renders_live_context_usage_in_status_panel():
    ui = UIManager()
    ui.console = Console(record=True, width=120, height=36)
    ui.reset_workspace()
    ui.set_shell_mode("chat")
    ui.note_context_window(8192, 204800)

    console = ui.console
    console.print(ui.render_shell_snapshot())
    rendered = console.export_text()

    assert "上下文" in rendered
    assert "8.2K / 204.8K" in rendered
    assert "4%" in rendered
    assert "消息输入" in rendered


def test_chat_input_panel_switches_mode_label_for_coding_task():
    ui = UIManager()
    ui.console = Console(record=True, width=120, height=36)
    ui.reset_workspace()
    ui.set_shell_mode("chat")
    ui.set_chat_task_snapshot({"title": "修复 bug", "status": "editing"})

    panel = ui._build_chat_input_panel()
    console = Console(record=True, width=120, height=12)
    console.print(panel)
    rendered = console.export_text()

    assert "消息输入" in rendered
    assert "Chat Coding" in rendered
    assert "输入消息..." in rendered
    assert "上下文" not in rendered


def test_chat_identity_block_shows_context_status():
    ui = UIManager()
    ui.console = Console(record=True, width=120, height=36)
    ui.reset_workspace()
    ui.set_shell_mode("chat")
    ui.note_context_window(845, 1_000_000)

    panel = ui._build_conversation_panel()
    console = ui.console
    console.print(panel)
    rendered = console.export_text()

    assert "上下文" in rendered
    assert "845 / 1M" in rendered
    assert "0%" in rendered


def test_chat_prompt_cursor_anchor_stays_inside_input_panel():
    ui = UIManager()
    ui.console = Console(record=True, width=120, height=40)
    ui.reset_workspace()
    ui.set_shell_mode("chat")
    ui.load_chat_messages(
        [
            {"role": "user", "content": "你好", "timestamp": "2026-05-01T12:00:00"},
            {"role": "assistant", "content": "你好，我在。", "timestamp": "2026-05-01T12:00:01"},
        ]
    )

    cursor = ui._locate_chat_prompt_cursor()

    assert cursor is not None
    column, row = cursor
    assert column > 0
    assert row > 0


def test_chat_input_bounds_are_detected_from_input_panel():
    ui = UIManager()
    ui.console = Console(record=True, width=120, height=40)
    ui.reset_workspace()
    ui.set_shell_mode("chat")

    bounds = ui._locate_chat_input_bounds()

    assert bounds is not None
    column, row, width = bounds
    assert column > 0
    assert row > 0
    assert width >= 8


def test_pet_panel_shows_subagent_running_status():
    reset_session_state()
    from core.infrastructure.agent_session import get_session_state

    session = get_session_state()
    session.record_delegation_start("diagnose", "分析为什么重复调用工具", {"log": "log_info/demo.jsonl"})

    ui = UIManager()
    ui.reset_workspace()
    panel = ui._build_pet_panel()
    console = Console(record=True, width=120)
    console.print(panel)
    rendered = console.export_text()

    assert "子 agent 干活中" in rendered


def test_render_pet_stage_shows_subagent_companion_when_delegating():
    reset_session_state()
    from core.infrastructure.agent_session import get_session_state

    session = get_session_state()
    session.record_delegation_start("inspect", "检查配置一致性", {"path": "config.toml"})

    ui = UIManager()
    ui.set_avatar_preset("moose")
    stage = ui._render_pet_stage()

    assert "( oo)" in stage or "(oo )" in stage


def test_render_pet_stage_keeps_main_pet_shape_when_subagent_appears_near_edge():
    reset_session_state()
    from core.infrastructure.agent_session import get_session_state

    session = get_session_state()
    session.record_delegation_start("inspect", "检查配置一致性", {"path": "config.toml"})

    ui = UIManager()
    ui.set_avatar_preset("moose")
    ui._pet_state.direction = "right"
    ui._pet_walk_offset = 0

    stage = ui._render_pet_stage()

    assert "_______/(oo)" in stage
    assert "/\\/(       (__)" in stage
    assert "( oo)" in stage or "(oo )" in stage


def test_append_conversation_buffers_when_not_live(monkeypatch):
    ui = UIManager()
    ui._live = False
    old_mode = UIManager._test_mode
    UIManager._test_mode = False

    try:
        ui._append_conversation("[cyan]●[/cyan] [bold]tool[/bold] [dim]path=demo.py[/dim]")
        assert ui._conversation_events
        assert "tool" in ui._conversation_events[-1]
    finally:
        UIManager._test_mode = old_mode


def test_safe_console_render_falls_back_when_console_print_breaks(monkeypatch):
    ui = UIManager()
    captured = []

    def boom(_renderable):
        raise OSError(22, "Invalid argument")

    monkeypatch.setattr(ui.console, "print", boom)
    monkeypatch.setattr(ui, "_write_plain_console_fallback", lambda text: captured.append(text))
    ui.print_markdown("hello fallback")

    assert captured
    assert "hello fallback" in captured[-1]


def test_start_subagent_activity_marks_fast_log_scan_path():
    ui = UIManager()
    ui.start_subagent_activity(
        "diagnose",
        "分析超时",
        {"goal": "分析 log_info/conversation_20260511_162502.jsonl 中子 agent 为什么会超时"},
    )

    assert ui._subagent_process_events
    assert "快速日志诊断" in ui._subagent_process_events[-1]
