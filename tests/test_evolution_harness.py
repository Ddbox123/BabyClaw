#!/usr/bin/env python3
"""evolution_harness 协议与归因逻辑测试"""

import os
import sys
from pathlib import Path

from scripts.evolution_harness import (
    build_post_restart_observation,
    build_live_case_io_payload,
    build_agent_command,
    build_synthetic_venv,
    classify_tool_event_phase,
    create_harness_config,
    DEFAULT_FULL_EVOLUTION_PROMPT,
    DEFAULT_SAFE_MODIFY_PROMPT,
    DEFAULT_TRANSACTION_PROMPT,
    extend_deadline_for_restart_trigger,
    infer_phase_from_agent_state,
    infer_phase_from_debug_lines,
    infer_phase_from_events,
    infer_first_meaningful_event,
    infer_evolution_summary,
    infer_post_restart_phase,
    infer_result_status,
    is_restart_trigger_line,
    mirror_venv_into_worktree,
    read_conversation_events,
    materialize_scenario_prompt,
    resolve_python_executable,
    resolve_run_options,
    select_observation_files,
    should_finish_post_restart_observation,
    SAFE_MODIFY_MARKER,
    SAFE_MODIFY_PROBE_CONTENT,
    SAFE_MODIFY_PROBE_PATH,
    SAFE_MODIFY_TOOL_PATH_PLACEHOLDER,
    should_stop_after_primary_exit,
    _safe_modify_probe_summary,
    _validation_passed_for_tool,
    ProcessRecord,
    summarize_process_history,
    summarize_agent_state_file,
    summarize_latest_matching_file,
    summarize_conversation_file,
)


def test_build_agent_command_for_test_mode():
    cmd = build_agent_command("test", None)
    assert "--no-shell" in cmd
    assert "--skip-doctor" in cmd
    assert "--test" in cmd
    assert "agent.py" in cmd


def test_build_agent_command_for_single_turn_prompt():
    cmd = build_agent_command("single_turn", "hello", config_path="config.harness.toml")
    assert "--single-turn" in cmd
    assert "--prompt" in cmd
    assert "--config" in cmd
    assert "hello" in cmd


def test_resolve_run_options_preserves_restart_defaults():
    options = resolve_run_options(
        scenario="restart",
        mode="test",
        prompt=None,
        expect_restart=False,
    )

    assert options.mode == "test"
    assert options.expect_restart is True
    assert "trigger_self_restart_tool" in options.prompt


def test_resolve_run_options_for_transaction_probe_forces_single_turn():
    options = resolve_run_options(
        scenario="transaction",
        mode="test",
        prompt=None,
        expect_restart=False,
    )

    assert options.mode == "single_turn"
    assert options.expect_restart is False
    assert options.prompt == DEFAULT_TRANSACTION_PROMPT
    assert "open_evolution_transaction_tool" in options.prompt
    assert "python_lint_tool" in options.prompt
    assert "close_evolution_transaction_tool" in options.prompt
    assert "不要触发重启" in options.prompt


def test_resolve_run_options_allows_custom_transaction_prompt():
    options = resolve_run_options(
        scenario="transaction",
        mode="auto",
        prompt="custom transaction probe",
        expect_restart=False,
    )

    assert options.mode == "single_turn"
    assert options.prompt == "custom transaction probe"


def test_resolve_run_options_for_modify_rollback_probe_forces_single_turn():
    options = resolve_run_options(
        scenario="modify_rollback",
        mode="test",
        prompt=None,
        expect_restart=False,
    )

    assert options.mode == "single_turn"
    assert options.expect_restart is False
    assert options.scenario == "modify_rollback"
    assert options.prompt == DEFAULT_SAFE_MODIFY_PROMPT
    assert "write_file_tool" in options.prompt
    assert "spawn_agent_tool" in options.prompt
    assert "不要委派子 agent" in options.prompt
    assert SAFE_MODIFY_TOOL_PATH_PLACEHOLDER in options.prompt
    assert SAFE_MODIFY_PROBE_PATH in options.prompt
    assert SAFE_MODIFY_MARKER in options.prompt
    assert repr(SAFE_MODIFY_PROBE_CONTENT) in options.prompt
    assert "import " not in SAFE_MODIFY_PROBE_CONTENT
    assert "不要触发重启" in options.prompt


def test_resolve_run_options_for_full_evolution_probe_forces_restartable_single_turn():
    options = resolve_run_options(
        scenario="full_evolution",
        mode="test",
        prompt=None,
        expect_restart=False,
    )

    assert options.mode == "single_turn"
    assert options.expect_restart is True
    assert options.scenario == "full_evolution"
    assert options.prompt == DEFAULT_FULL_EVOLUTION_PROMPT
    assert "write_file_tool" in options.prompt
    assert "close_evolution_transaction_tool" in options.prompt
    assert "trigger_self_restart_tool" in options.prompt
    assert "不要委派子 agent" in options.prompt


def test_resolve_run_options_for_strategy_probe_forces_readonly_single_turn():
    options = resolve_run_options(
        scenario="strategy",
        mode="test",
        prompt="read files and answer",
        expect_restart=True,
    )

    assert options.mode == "single_turn"
    assert options.prompt == "read files and answer"
    assert options.expect_restart is False
    assert options.scenario == "strategy"


def test_materialize_scenario_prompt_injects_worktree_absolute_probe_path(tmp_path: Path):
    prompt = f"写入 {SAFE_MODIFY_TOOL_PATH_PLACEHOLDER} 然后检查 {SAFE_MODIFY_PROBE_PATH}"

    materialized = materialize_scenario_prompt("modify_rollback", prompt, tmp_path)

    assert SAFE_MODIFY_TOOL_PATH_PLACEHOLDER not in materialized
    assert str(tmp_path / SAFE_MODIFY_PROBE_PATH) in materialized
    assert SAFE_MODIFY_PROBE_PATH in materialized


def test_materialize_full_evolution_prompt_injects_worktree_absolute_probe_path(tmp_path: Path):
    prompt = f"写入 {SAFE_MODIFY_TOOL_PATH_PLACEHOLDER} 然后重启"

    materialized = materialize_scenario_prompt("full_evolution", prompt, tmp_path)

    assert SAFE_MODIFY_TOOL_PATH_PLACEHOLDER not in materialized
    assert str(tmp_path / SAFE_MODIFY_PROBE_PATH) in materialized


def test_select_observation_files_uses_all_restart_logs_but_primary_non_restart_log():
    files = [
        "conversation_parent.jsonl",
        "conversation_subagent.jsonl",
        "conversation_late_subagent.jsonl",
    ]

    assert select_observation_files(files, expect_restart=True) == files
    assert select_observation_files(files, expect_restart=False) == ["conversation_parent.jsonl"]


def test_should_stop_after_primary_exit_for_non_restart_scenarios():
    assert should_stop_after_primary_exit(expect_restart=False, primary_returncode=0) is True
    assert should_stop_after_primary_exit(expect_restart=False, primary_returncode=1) is True
    assert should_stop_after_primary_exit(expect_restart=False, primary_returncode=None) is False
    assert should_stop_after_primary_exit(expect_restart=True, primary_returncode=0) is False


def test_should_finish_post_restart_observation_waits_for_meaningful_child_event():
    assert should_finish_post_restart_observation(
        observation_phase="prompt_refresh",
        first_child_event_phase="first_prompt_refresh",
        elapsed_seconds=15,
        min_observe_seconds=15,
    ) is False

    assert should_finish_post_restart_observation(
        observation_phase="first_tool:task_create_tool:success",
        first_child_event_phase="first_tool:task_create_tool:success",
        elapsed_seconds=15,
        min_observe_seconds=15,
    ) is True

    assert should_finish_post_restart_observation(
        observation_phase="prompt_refresh",
        first_child_event_phase="first_prompt_refresh",
        elapsed_seconds=45,
        min_observe_seconds=15,
    ) is True


def test_infer_result_status_requires_safe_modify_and_restart_for_full_evolution():
    status, reason = infer_result_status(
        timed_out=False,
        restart_expected=True,
        restart_reentered=True,
        primary_returncode=0,
        last_observation={"phase": "first_tool:task_create_tool:success"},
        evolution_summary={
            "validation": {"passed": 1, "failed": 0},
            "transaction": {"closed": True, "status": "success"},
            "safe_modify": {
                "exists": True,
                "marker_present": True,
                "out_of_scope_paths": [],
            },
        },
    )

    assert status == "success"
    assert "重启接力" in reason


def test_infer_result_status_rejects_restart_when_safe_modify_missing_even_if_reentered():
    status, reason = infer_result_status(
        timed_out=False,
        restart_expected=True,
        restart_reentered=True,
        primary_returncode=0,
        last_observation={"phase": "first_tool:task_create_tool:success"},
        evolution_summary={
            "validation": {"passed": 1, "failed": 0},
            "transaction": {"closed": True, "status": "success"},
            "safe_modify": {
                "exists": False,
                "marker_present": False,
                "out_of_scope_paths": [],
            },
        },
    )

    assert status == "failed"
    assert "未创建目标文件" in reason


def test_resolve_python_executable_prefers_repo_venv(tmp_path: Path):
    python_path = tmp_path / ".venv" / "Scripts" / "python.exe"
    python_path.parent.mkdir(parents=True)
    python_path.write_text("", encoding="utf-8")

    resolved = resolve_python_executable(tmp_path)

    assert resolved == str(python_path)


def test_build_synthetic_venv_invokes_current_python(monkeypatch, tmp_path: Path):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        python_path = tmp_path / ".venv" / "Scripts" / "python.exe"
        python_path.parent.mkdir(parents=True, exist_ok=True)
        python_path.write_text("python", encoding="utf-8")

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr("scripts.evolution_harness.subprocess.run", fake_run)

    build_synthetic_venv(tmp_path)

    assert calls
    assert calls[0][0][:4] == [sys.executable, "-m", "venv", "--system-site-packages"]
    assert calls[0][0][-1] == str(tmp_path / ".venv")


def test_create_harness_config_overrides_runtime_section(tmp_path: Path):
    config = tmp_path / "config.toml"
    config.write_text(
        "\n".join(
            [
                "[runtime]",
                'profile = "safe_local"',
                "preflight_doctor = true",
                "require_venv = true",
                "",
                "[llm.providers.default]",
                'kind = "minimax"',
                "",
                "[llm.profiles.primary]",
                'provider_id = "default"',
                'model = "MiniMax-M2.7"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    target = create_harness_config(tmp_path)
    content = target.read_text(encoding="utf-8")

    assert 'profile = ""' in content
    assert "preflight_doctor = false" in content
    assert "require_venv = false" in content
    assert content.count("[runtime]") == 1


def test_mirror_venv_into_worktree_copies_venv_without_junction(monkeypatch, tmp_path: Path):
    repo_root = tmp_path / "repo"
    worktree = tmp_path / "worktree"
    source_python = repo_root / ".venv" / "Scripts" / "python.exe"
    source_python.parent.mkdir(parents=True)
    source_python.write_text("python", encoding="utf-8")
    source_package = repo_root / ".venv" / "Lib" / "site-packages" / "annotated_types"
    source_package.mkdir(parents=True)
    worktree.mkdir()

    mirror_venv_into_worktree(repo_root, worktree)

    assert (worktree / ".venv" / "Scripts" / "python.exe").exists()
    assert (worktree / ".venv" / "Lib" / "site-packages" / "annotated_types").exists()


def test_mirror_venv_into_worktree_copies_python_fallback(monkeypatch, tmp_path: Path):
    repo_root = tmp_path / "repo"
    worktree = tmp_path / "worktree"
    source_python = repo_root / ".venv" / "Scripts" / "python.exe"
    source_python.parent.mkdir(parents=True)
    source_python.write_text("python", encoding="utf-8")
    worktree.mkdir()

    monkeypatch.setattr("scripts.evolution_harness.shutil.copytree", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("copy failed")))

    mirror_venv_into_worktree(repo_root, worktree)

    assert (worktree / ".venv" / "Scripts" / "python.exe").exists()


def test_mirror_venv_into_worktree_builds_synthetic_venv_when_source_missing(monkeypatch, tmp_path: Path):
    repo_root = tmp_path / "repo"
    worktree = tmp_path / "worktree"
    repo_root.mkdir()
    worktree.mkdir()
    created = []

    def fake_build(target: Path):
        created.append(target)
        python_path = target / ".venv" / "Scripts" / "python.exe"
        python_path.parent.mkdir(parents=True, exist_ok=True)
        python_path.write_text("python", encoding="utf-8")

    monkeypatch.setattr("scripts.evolution_harness.build_synthetic_venv", fake_build)

    mirror_venv_into_worktree(repo_root, worktree)

    assert created == [worktree]
    assert (worktree / ".venv" / "Scripts" / "python.exe").exists()


def test_mirror_venv_into_worktree_builds_synthetic_venv_when_source_python_missing(monkeypatch, tmp_path: Path):
    repo_root = tmp_path / "repo"
    worktree = tmp_path / "worktree"
    (repo_root / ".venv").mkdir(parents=True)
    worktree.mkdir()
    created = []

    def fake_build(target: Path):
        created.append(target)
        python_path = target / ".venv" / "Scripts" / "python.exe"
        python_path.parent.mkdir(parents=True, exist_ok=True)
        python_path.write_text("python", encoding="utf-8")

    monkeypatch.setattr("scripts.evolution_harness.build_synthetic_venv", fake_build)

    mirror_venv_into_worktree(repo_root, worktree)

    assert created == [worktree]
    assert (worktree / ".venv" / "Scripts" / "python.exe").exists()


def test_infer_phase_from_events_prefers_latest_tool_status():
    events = [
        {"type": "llm_response", "content": "thinking"},
        {"type": "tool_call", "tool_name": "read_file_tool", "status": "success"},
    ]
    assert infer_phase_from_events(events) == "tool:read_file_tool:success"


def test_infer_phase_from_events_labels_restart_guarded_tool():
    events = [
        {
            "type": "tool_call",
            "tool_name": "get_git_status_summary_tool",
            "status": "error",
            "tool_result": "[短路] 当前处于重启测试模式，只允许任务管理与重启闭环工具。",
        },
    ]

    assert infer_phase_from_events(events) == "restart_guarded_tool:get_git_status_summary_tool:error"
    assert classify_tool_event_phase(events[0]) == "restart_guarded_tool:get_git_status_summary_tool:error"


def test_infer_phase_from_events_labels_generic_guarded_tool():
    events = [
        {
            "type": "tool_call",
            "tool_name": "read_file_tool",
            "status": "error",
            "tool_result": "[短路] 当前存在未完成续读，请先继续读取。",
        },
    ]

    assert infer_phase_from_events(events) == "guarded_tool:read_file_tool:error"


def test_infer_phase_from_debug_lines_detects_restarter():
    lines = [
        "[20:00:00.000] [INFO] start",
        "[20:00:01.000] [INFO] Restarter 守护进程启动",
    ]
    assert infer_phase_from_debug_lines(lines) == "restarter_boot"


def test_infer_phase_from_debug_lines_labels_restart_guard():
    lines = [
        "[20:00:00.000] [WARN] [工具护栏] get_git_status_summary_tool 被短路: [短路] 当前处于重启测试模式",
    ]

    assert infer_phase_from_debug_lines(lines) == "restart_guarded_tool"


def test_summarize_conversation_file_extracts_turn_stats_and_phase(tmp_path: Path):
    path = tmp_path / "conversation_demo.jsonl"
    path.write_text(
        "\n".join(
            [
                '{"type":"llm_response","content":"思考"}',
                '{"type":"tool_call","tool_name":"grep_search_tool","status":"error","tool_result":"blocked"}',
                '{"type":"turn_end","stats":{"iterations":3,"tool_calls":2}}',
            ]
        ),
        encoding="utf-8",
    )

    summary = summarize_conversation_file(path)

    assert summary["last_type"] == "turn_end"
    assert summary["turn_stats"]["tool_calls"] == 2
    assert summary["phase"] == "turn_end"
    assert summary["first_meaningful_event"]["phase"] == "first_tool:grep_search_tool:error"


def test_read_conversation_events_ignores_broken_jsonl_rows(tmp_path: Path):
    path = tmp_path / "conversation_demo.jsonl"
    path.write_text(
        '{"type":"debug","message":"ok"}\n'
        "not json\n"
        '{"type":"tool_call","tool_name":"task_create_tool"}\n',
        encoding="utf-8",
    )

    events = read_conversation_events(path)

    assert [item["type"] for item in events] == ["debug", "tool_call"]


def test_build_live_case_io_payload_reads_inline_and_referenced_content(tmp_path: Path):
    payload_dir = tmp_path / "payloads"
    payload_dir.mkdir()
    (payload_dir / "tool_result.txt").write_text("tool result body", encoding="utf-8")
    conversation_path = tmp_path / "conversation_demo.jsonl"
    conversation_path.write_text(
        "\n".join(
            [
                '{"type":"external_request","timestamp":"2026-05-19T12:00:01Z","content":"prompt body"}',
                '{"type":"tool_call","timestamp":"2026-05-19T12:00:02Z","tool_name":"read_file_tool","status":"success","tool_result_ref":"payloads/tool_result.txt"}',
                '{"type":"llm_response","timestamp":"2026-05-19T12:00:03Z","content":"assistant reply"}',
            ]
        ),
        encoding="utf-8",
    )

    payload = build_live_case_io_payload(tmp_path)

    assert payload["conversation_path"].endswith("conversation_demo.jsonl")
    assert payload["latest_input"] == "prompt body"
    assert payload["latest_output"] == "assistant reply"
    assert payload["latest_output_kind"] == "assistant"
    assert payload["latest_output_label"] == "assistant"
    assert payload["updated_at"] == "2026-05-19T12:00:03Z"
    assert [item["kind"] for item in payload["transcript"]] == ["input", "tool", "assistant"]
    assert payload["transcript"][1]["label"] == "read_file_tool"
    assert payload["transcript"][1]["content"] == "tool result body"


def test_safe_modify_probe_summary_reports_marker_and_dirty_state(tmp_path: Path):
    probe = tmp_path / SAFE_MODIFY_PROBE_PATH
    probe.parent.mkdir(parents=True)
    probe.write_text(
        f'MARKER = "{SAFE_MODIFY_MARKER}"\n',
        encoding="utf-8",
    )

    summary = _safe_modify_probe_summary(tmp_path)

    assert summary["path"] == SAFE_MODIFY_PROBE_PATH
    assert summary["exists"] is True
    assert summary["marker_present"] is True
    assert summary["size"] > 0
    assert summary["cleanup"] == "pending"


def test_safe_modify_probe_summary_reports_out_of_scope_dirty_paths(monkeypatch, tmp_path: Path):
    probe = tmp_path / SAFE_MODIFY_PROBE_PATH
    probe.parent.mkdir(parents=True)
    probe.write_text(
        f'MARKER = "{SAFE_MODIFY_MARKER}"\n',
        encoding="utf-8",
    )

    def fake_run_git(_repo_root, *args):
        if args == ("status", "--porcelain", "--", SAFE_MODIFY_PROBE_PATH):
            return f"?? {SAFE_MODIFY_PROBE_PATH}"
        if args == ("status", "--porcelain"):
            return f"?? config.harness.toml\n?? {SAFE_MODIFY_PROBE_PATH}\n M agent.py"
        return ""

    monkeypatch.setattr("scripts.evolution_harness.run_git", fake_run_git)

    summary = _safe_modify_probe_summary(tmp_path)

    assert summary["git_dirty"] is True
    assert summary["dirty_paths"] == ["config.harness.toml", SAFE_MODIFY_PROBE_PATH, "agent.py"]
    assert summary["out_of_scope_paths"] == ["agent.py"]


def test_infer_evolution_summary_extracts_transaction_validation_and_restart():
    events = [
        {
            "type": "tool_call",
            "tool_name": "open_evolution_transaction_tool",
            "status": "success",
            "tool_result": '{"status":"success","txn_id":"txn_1"}',
        },
        {
            "type": "tool_call",
            "tool_name": "task_create_tool",
            "status": "success",
            "tool_args": {"task_list": [{"description": "验证"}]},
            "tool_result": "ok",
        },
        {
            "type": "tool_call",
            "tool_name": "task_update_tool",
            "status": "success",
            "tool_args": {"task_id": 1, "is_completed": True},
            "tool_result": "done",
        },
        {
            "type": "tool_call",
            "tool_name": "cli_tool",
            "status": "success",
            "tool_args": {"command": "python -m pytest tests/test_demo.py -q"},
            "tool_result": "1 passed in 0.10s",
        },
        {
            "type": "tool_call",
            "tool_name": "close_evolution_transaction_tool",
            "status": "success",
            "tool_args": {"txn_id": "txn_1", "status": "success"},
            "tool_result": '{"status":"success","txn_id":"txn_1","transaction_status":"success"}',
        },
    ]

    summary = infer_evolution_summary(
        events,
        ["[INFO] 当前演化事务已成功关账，本轮停止并等待下一轮。"],
        ["11:11:20 -- 重启触发成功"],
        restart_expected=True,
        restart_reentered=True,
        child_first_event_phase="first_tool:task_list_tool:success",
    )

    assert summary["tasks"] == {"created": 1, "updated": 1, "completed": 1}
    assert summary["validation"]["passed"] == 1
    assert summary["validation"]["failed"] == 0
    assert summary["transaction"]["opened"] is True
    assert summary["transaction"]["closed"] is True
    assert summary["transaction"]["status"] == "success"
    assert summary["restart"]["triggered"] is True
    assert summary["restart"]["reentered"] is True
    assert summary["child"]["first_event_phase"] == "first_tool:task_list_tool:success"
    assert summary["guarded_tools"]["total"] == 0


def test_infer_evolution_summary_counts_guarded_tool_phases():
    events = [
        {
            "type": "tool_call",
            "tool_name": "get_git_status_summary_tool",
            "status": "error",
            "tool_result": "[短路] 当前处于重启测试模式，只允许任务管理与重启闭环工具。",
        },
        {
            "type": "tool_call",
            "tool_name": "task_list_tool",
            "status": "success",
            "tool_result": "ok",
        },
    ]

    summary = infer_evolution_summary(
        events,
        [],
        [],
        restart_expected=True,
        restart_reentered=True,
    )

    assert summary["guarded_tools"]["total"] == 1
    assert summary["guarded_tools"]["restart_guarded"] == 1
    assert summary["tool_phase_sequence_tail"] == [
        "restart_guarded_tool:get_git_status_summary_tool:error",
        "tool:task_list_tool:success",
    ]


def test_infer_evolution_summary_includes_safe_modify_probe_state():
    safe_modify = {
        "path": SAFE_MODIFY_PROBE_PATH,
        "exists": True,
        "marker_present": True,
        "git_dirty": True,
        "cleanup": "pending",
    }

    summary = infer_evolution_summary(
        [],
        [],
        [],
        restart_expected=False,
        restart_reentered=False,
        safe_modify_summary=safe_modify,
    )

    assert summary["safe_modify"] == safe_modify


def test_validation_passed_for_python_lint_requires_zero_issues():
    assert _validation_passed_for_tool(
        tool_name="python_lint_tool",
        result_text='{"status":"ok","issue_count":0}',
        result_payload={"status": "ok", "issue_count": 0},
    ) is True

    assert _validation_passed_for_tool(
        tool_name="python_lint_tool",
        result_text='{"status":"ok","issue_count":2}',
        result_payload={"status": "ok", "issue_count": 2},
    ) is False


def test_infer_evolution_summary_counts_python_lint_issues_as_failed_validation():
    events = [
        {
            "type": "tool_call",
            "tool_name": "python_lint_tool",
            "status": "success",
            "tool_result": '{"status":"ok","tool":"ruff","issue_count":2,"issues":[{"code":"invalid-syntax"}]}',
        },
    ]

    summary = infer_evolution_summary(
        events,
        [],
        [],
        restart_expected=False,
        restart_reentered=False,
    )

    assert summary["validation"]["passed"] == 0
    assert summary["validation"]["failed"] == 1
    assert summary["validation"]["last"]["passed"] is False


def test_infer_evolution_summary_detects_failed_validation_and_commit_ref():
    events = [
        {
            "type": "tool_call",
            "tool_name": "run_powershell_tool",
            "status": "success",
            "tool_args": {"command": "python -m pytest tests/test_demo.py -q"},
            "tool_result": "FAILED tests/test_demo.py::test_x",
        },
        {
            "type": "tool_call",
            "tool_name": "run_powershell_tool",
            "status": "success",
            "tool_args": {"command": "git commit -m \"fix: demo\""},
            "tool_result": "[main abc1234] fix: demo",
        },
    ]

    summary = infer_evolution_summary(
        events,
        [],
        [],
        restart_expected=False,
        restart_reentered=False,
    )

    assert summary["validation"]["passed"] == 0
    assert summary["validation"]["failed"] == 1
    assert summary["git"]["commit_detected"] is True
    assert summary["restart"]["triggered"] is False


def test_infer_result_status_handles_restart_success():
    status, reason = infer_result_status(
        timed_out=False,
        restart_expected=True,
        restart_reentered=True,
        primary_returncode=0,
        last_observation={"phase": "restarter_boot"},
    )

    assert status == "success"
    assert "重启接力" in reason


def test_infer_result_status_rejects_unclosed_transaction_probe():
    status, reason = infer_result_status(
        timed_out=False,
        restart_expected=False,
        restart_reentered=False,
        primary_returncode=0,
        last_observation={"phase": "session_end"},
        evolution_summary={
            "validation": {"passed": 1, "failed": 0},
            "transaction": {
                "opened": True,
                "closed": False,
                "status": None,
            },
        },
    )

    assert status == "failed"
    assert "未关账" in reason


def test_infer_result_status_handles_timeout_with_phase():
    status, reason = infer_result_status(
        timed_out=True,
        restart_expected=False,
        restart_reentered=False,
        primary_returncode=None,
        last_observation={"phase": "tool:read_file_tool:success"},
    )

    assert status == "timeout"
    assert "read_file_tool" in reason


def test_infer_result_status_requires_complete_safe_modify_probe():
    status, reason = infer_result_status(
        timed_out=False,
        restart_expected=False,
        restart_reentered=False,
        primary_returncode=0,
        last_observation={"phase": "session_end"},
        evolution_summary={
            "safe_modify": {
                "exists": True,
                "marker_present": True,
                "out_of_scope_paths": [],
            },
            "validation": {
                "passed": 0,
            },
            "transaction": {
                "closed": False,
                "status": None,
            },
        },
    )

    assert status == "failed"
    assert "事务未关账" in reason


def test_infer_result_status_reports_failed_safe_modify_validation_close():
    status, reason = infer_result_status(
        timed_out=False,
        restart_expected=False,
        restart_reentered=False,
        primary_returncode=0,
        last_observation={"phase": "session_end"},
        evolution_summary={
            "safe_modify": {
                "exists": True,
                "marker_present": True,
                "out_of_scope_paths": [],
            },
            "validation": {
                "passed": 0,
                "failed": 1,
            },
            "transaction": {
                "closed": True,
                "status": "failed",
            },
        },
    )

    assert status == "failed"
    assert "验证失败" in reason
    assert "失败状态关账" in reason


def test_infer_result_status_rejects_out_of_scope_safe_modify_paths():
    status, reason = infer_result_status(
        timed_out=False,
        restart_expected=False,
        restart_reentered=False,
        primary_returncode=0,
        last_observation={"phase": "session_end"},
        evolution_summary={
            "safe_modify": {
                "exists": True,
                "marker_present": True,
                "out_of_scope_paths": ["agent.py"],
            },
            "validation": {
                "passed": 1,
            },
            "transaction": {
                "closed": True,
                "status": "success",
            },
        },
    )

    assert status == "failed"
    assert "越界文件修改" in reason


def test_infer_result_status_accepts_complete_safe_modify_probe():
    status, reason = infer_result_status(
        timed_out=False,
        restart_expected=False,
        restart_reentered=False,
        primary_returncode=0,
        last_observation={"phase": "session_end"},
        evolution_summary={
            "safe_modify": {
                "exists": True,
                "marker_present": True,
                "out_of_scope_paths": [],
            },
            "validation": {
                "passed": 1,
            },
            "transaction": {
                "closed": True,
                "status": "success",
            },
        },
    )

    assert status == "success"
    assert "主进程正常结束" in reason


def test_extend_deadline_for_restart_trigger_grants_observation_window():
    deadline = extend_deadline_for_restart_trigger(
        current_deadline=100.0,
        now=99.5,
        post_restart_observe_seconds=20,
    )

    assert deadline == 119.5


def test_extend_deadline_for_restart_trigger_never_shortens_deadline():
    deadline = extend_deadline_for_restart_trigger(
        current_deadline=200.0,
        now=99.5,
        post_restart_observe_seconds=20,
    )

    assert deadline == 200.0


def test_summarize_latest_matching_file_uses_most_recent(tmp_path: Path):
    older = tmp_path / "conversation_older.jsonl"
    newer = tmp_path / "conversation_newer.jsonl"
    older.write_text('{"type":"llm_response","content":"old"}\n', encoding="utf-8")
    newer.write_text('{"type":"tool_call","tool_name":"task_create_tool","status":"success"}\n', encoding="utf-8")
    os.utime(older, (1, 1))
    os.utime(newer, (2, 2))

    summary = summarize_latest_matching_file(tmp_path, "conversation_*.jsonl", summarize_conversation_file)

    assert summary["path"].endswith("conversation_newer.jsonl")
    assert summary["phase"] == "tool:task_create_tool:success"


def test_is_restart_trigger_line_detects_windows_handoff_markers():
    assert is_restart_trigger_line("22:02:19 -- Windows: 已启动脱离进程, PID: 37044")
    assert is_restart_trigger_line("22:02:19 -- 重启触发成功")
    assert not is_restart_trigger_line("22:01:40 >> task_update_tool OK")


def test_infer_result_status_restart_success_still_allows_process_only_post_observation():
    status, reason = infer_result_status(
        timed_out=False,
        restart_expected=True,
        restart_reentered=True,
        primary_returncode=0,
        last_observation={"phase": "session_end"},
    )

    assert status == "success"
    assert "重启接力" in reason


def test_summarize_agent_state_file_extracts_semantic_phase(tmp_path: Path):
    state_path = tmp_path / "agent_state.json"
    state_path.write_text(
        '{"status":"THINKING","current_action":"正在分析重启后的环境","current_goal":"验证重启闭环","iteration_count":2,"tools_executed":1,"last_update":"2026-05-10T22:10:50"}',
        encoding="utf-8",
    )

    summary = summarize_agent_state_file(state_path)

    assert summary["status"] == "THINKING"
    assert summary["phase"].startswith("state:THINKING:")
    assert "正在分析重启后的环境" in summary["current_action"]


def test_infer_phase_from_agent_state_handles_missing_action():
    phase = infer_phase_from_agent_state({"status": "RESTARTING"})
    assert phase == "state:RESTARTING"


def test_find_agent_processes_contract_without_psutil(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("scripts.evolution_harness.psutil", None)
    from scripts.evolution_harness import find_agent_processes

    assert find_agent_processes(tmp_path) == []


def test_find_agent_processes_prefers_restarter_role_when_cmd_mentions_both(monkeypatch, tmp_path: Path):
    class FakeProc:
        def __init__(self):
            self.pid = 123
            self.info = {
                "pid": 123,
                "name": "python",
                "cmdline": [
                    "python",
                    "-m",
                    "core.restarter_manager.restarter",
                    "--script",
                    str(tmp_path / "agent.py"),
                ],
                "cwd": str(tmp_path),
            }

    class FakePsutil:
        NoSuchProcess = RuntimeError
        AccessDenied = RuntimeError

        @staticmethod
        def process_iter(_fields):
            return [FakeProc()]

    monkeypatch.setattr("scripts.evolution_harness.psutil", FakePsutil)
    from scripts.evolution_harness import find_agent_processes

    result = find_agent_processes(tmp_path)

    assert result[0]["role"] == "restarter"


def test_summarize_process_history_groups_windows_python_wrappers():
    records = [
        ProcessRecord(
            pid=10,
            role="agent",
            first_seen="2026-05-11T10:00:00",
            last_seen="2026-05-11T10:00:01",
            cmdline_preview=r"C:\repo\.venv\Scripts\python.exe agent.py --no-shell --test",
        ),
        ProcessRecord(
            pid=11,
            role="agent",
            first_seen="2026-05-11T10:00:02",
            last_seen="2026-05-11T10:00:03",
            cmdline_preview=r"C:\runtime\python.exe C:\repo\agent.py --no-shell --test",
        ),
        ProcessRecord(
            pid=12,
            role="restarter",
            first_seen="2026-05-11T10:00:02",
            last_seen="2026-05-11T10:00:03",
            cmdline_preview=r"python -m core.restarter_manager.restarter --script C:\repo\agent.py",
        ),
    ]

    summary = summarize_process_history(records, reentered_agent_pids=[11])

    assert summary["raw_count"] == 3
    assert summary["role_counts"]["agent"] == 2
    assert summary["unique_agent_families"] == 1
    assert summary["unique_restarter_families"] == 1
    assert summary["normalized_reentered_agent_count"] == 1
    assert summary["duplicate_families"][0]["count"] == 2


def test_infer_first_meaningful_event_prefers_first_tool_call():
    events = [
        {"type": "session_start"},
        {"type": "debug", "message": "noise"},
        {"type": "tool_call", "tool_name": "task_create_tool", "status": "success", "summary": "created"},
        {"type": "llm_response", "content": "later"},
    ]

    summary = infer_first_meaningful_event(events)

    assert summary["phase"] == "first_tool:task_create_tool:success"
    assert summary["tool_name"] == "task_create_tool"


def test_infer_first_meaningful_event_prefers_later_tool_over_prompt_refresh():
    events = [
        {"type": "debug", "message": "[PromptManager] 构建完成"},
        {"type": "llm_response", "content": "准备行动"},
        {"type": "tool_call", "tool_name": "get_git_status_summary_tool", "status": "error", "summary": "guarded"},
    ]

    summary = infer_first_meaningful_event(events)

    assert summary["phase"] == "first_tool:get_git_status_summary_tool:error"
    assert summary["tool_name"] == "get_git_status_summary_tool"


def test_infer_post_restart_phase_prefers_first_child_tool_over_prompt_refresh():
    phase = infer_post_restart_phase(
        {"phase": "no_state"},
        {
            "phase": "prompt_refresh",
            "first_meaningful_event": {
                "phase": "first_tool:task_update_tool:success",
                "tool_name": "task_update_tool",
            },
        },
        {"phase": "prompt_refresh"},
    )

    assert phase == "first_tool:task_update_tool:success"


def test_build_post_restart_observation_surfaces_first_child_fields():
    observation = build_post_restart_observation(
        live_agent_pids=[101],
        reentered_agent_pids=[101],
        reentered_processes=[{"pid": 101, "role": "agent"}],
        state_summary={"phase": "no_state"},
        conversation_summary={
            "phase": "prompt_refresh",
            "prompt_build": {"tag": "prompt_build", "message": "mode=execute len=2048"},
            "first_meaningful_event": {
                "phase": "first_tool:trigger_self_restart_tool:success",
                "tool_name": "trigger_self_restart_tool",
                "message": "restart",
            },
        },
        debug_summary={"phase": "prompt_refresh"},
    )

    assert observation["phase"] == "first_tool:trigger_self_restart_tool:success"
    assert observation["first_child_event_phase"] == "first_tool:trigger_self_restart_tool:success"
    assert observation["first_child_tool_name"] == "trigger_self_restart_tool"
    assert observation["prompt_build"]["message"] == "mode=execute len=2048"


def test_summarize_conversation_file_extracts_prompt_build(tmp_path):
    path = tmp_path / "conversation.jsonl"
    path.write_text(
        "\n".join(
            [
                '{"type":"debug","tag":"prompt_build","message":"mode=diagnose len=2048 rendered=SOUL,SPEC_DIGEST"}',
                '{"type":"debug","message":"[PromptManager] 构建完成"}',
            ]
        ),
        encoding="utf-8",
    )

    summary = summarize_conversation_file(path)

    assert summary["prompt_build"]["tag"] == "prompt_build"
    assert "mode=diagnose" in summary["prompt_build"]["message"]
