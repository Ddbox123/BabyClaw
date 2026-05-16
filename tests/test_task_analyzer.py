#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
from pathlib import Path

from core.prompt_manager.task_analyzer import TaskAnalyzer


def _write_jsonl(path: Path, records):
    with open(path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def test_analyze_evolution_session_extracts_goal_validations_and_blocker(tmp_path):
    project_root = tmp_path
    log_dir = project_root / "log_info"
    log_dir.mkdir()
    session_file = log_dir / "conversation_20260509_105646.jsonl"

    records = [
        {
            "type": "session_start",
            "timestamp": "2026-05-09T10:56:46.583",
            "session_id": "20260509_105646",
            "metadata": {"model": "MiniMax-M2.7"},
        },
        {"type": "human", "content": "开始自主进化"},
        {
            "type": "tool_call",
            "turn": 1,
            "timestamp": "2026-05-09T10:58:11.921",
            "tool_name": "cli_tool",
            "tool_args": {"command": "python -m py_compile config/models.py core/prompt_manager/sections.py"},
            "tool_result": "[命令执行完成，无输出]",
            "status": "success",
        },
        {
            "type": "tool_call",
            "turn": 1,
            "timestamp": "2026-05-09T10:58:22.180",
            "tool_name": "run_test_for_tool",
            "tool_args": {"source_path": "config/models.py", "timeout": 120},
            "tool_result": "[运行测试] 未找到对应测试文件",
            "status": "success",
        },
        {
            "type": "tool_call",
            "turn": 1,
            "timestamp": "2026-05-09T10:58:37.222",
            "tool_name": "cli_tool",
            "tool_args": {"command": "python -m pytest tests/test_config_sync.py tests/test_prompt_manager.py -v --tb=short 2>&1"},
            "tool_result": "============================= test session starts =============================\n58 passed in 1.96s",
            "status": "success",
        },
        {
            "type": "debug",
            "turn": 1,
            "timestamp": "2026-05-09T10:59:02.835",
            "level": "INFO",
            "tag": "STATE",
            "message": "[感知] 轻松 | 思维空间充裕，可以从容思考问题 | 保持当前节奏，不要急于求成",
        },
        {
            "type": "tool_call",
            "turn": 1,
            "timestamp": "2026-05-09T10:59:02.862",
            "tool_name": "cli_tool",
            "tool_args": {"command": "git commit -m \"feat(prompt): add language awareness\""},
            "tool_result": "[安全拦截] [Whitelist Block] 命令包含危险字符：(",
            "status": "success",
        },
        {
            "type": "session_end",
            "timestamp": "2026-05-09T10:59:19.182",
            "session_id": "20260509_105646",
            "total_turns": 1,
            "summary": {"uptime_seconds": 152.640951, "total_turns": 1},
        },
    ]
    _write_jsonl(session_file, records)

    analyzer = TaskAnalyzer(str(project_root))
    report = analyzer.analyze_evolution_session(session_file=session_file)

    assert report.session_id == "20260509_105646"
    assert report.goal == "开始自主进化"
    assert report.total_validation_checks == 3
    assert report.outcome == "受阻"
    assert "核心验证已通过" in report.outcome_reason
    assert any(item["kind"] == "安全策略拦截" for item in report.blockers)
    assert any(item["kind"] == "测试验证" and item["passed"] for item in report.validations)
    assert report.repeated_failure_patterns == []
    assert report.tool_misuse_patterns == []
    assert report.language_drift_detected is False
    assert any("当前验证组合" in item for item in report.recommendations)
    assert report.notable_states[-1].startswith("[感知] 轻松")


def test_generate_and_save_evolution_retrospective(tmp_path):
    project_root = tmp_path
    log_dir = project_root / "log_info"
    log_dir.mkdir()
    session_file = log_dir / "conversation_demo.jsonl"
    _write_jsonl(
        session_file,
        [
            {
                "type": "session_start",
                "timestamp": "2026-05-09T00:00:00.000",
                "session_id": "demo",
                "metadata": {},
            },
            {"type": "human", "content": "验证一下"},
            {
                "type": "tool_call",
                "turn": 1,
                "timestamp": "2026-05-09T00:00:02.000",
                "tool_name": "cli_tool",
                "tool_args": {"command": "python -m pytest tests/test_prompt_manager.py"},
                "tool_result": "1 passed in 0.12s",
                "status": "success",
            },
            {
                "type": "session_end",
                "timestamp": "2026-05-09T00:00:03.000",
                "session_id": "demo",
                "total_turns": 1,
                "summary": {"uptime_seconds": 3, "total_turns": 1},
            },
        ],
    )

    analyzer = TaskAnalyzer(str(project_root))
    markdown = analyzer.generate_evolution_retrospective(session_file=session_file)
    report = analyzer.analyze_evolution_session(session_file=session_file)
    saved_path = analyzer.save_evolution_analysis(report)

    assert "# 进化结果分析" in markdown
    assert "**目标**: 验证一下" in markdown
    assert Path(saved_path).exists()
    data = json.loads(Path(saved_path).read_text(encoding="utf-8"))
    assert data["outcome"] == "完成"
    assert data["goal"] == "验证一下"


def test_analyze_evolution_session_extracts_external_request_goal(tmp_path):
    project_root = tmp_path
    log_dir = project_root / "log_info"
    log_dir.mkdir()
    session_file = log_dir / "conversation_external_request.jsonl"
    _write_jsonl(
        session_file,
        [
            {
                "type": "session_start",
                "timestamp": "2026-05-13T00:00:00.000",
                "session_id": "external_request",
                "metadata": {},
            },
            {"type": "external_request", "content": "执行去人格化输入验证"},
            {
                "type": "session_end",
                "timestamp": "2026-05-13T00:00:01.000",
                "session_id": "external_request",
                "total_turns": 1,
                "summary": {"uptime_seconds": 1, "total_turns": 1},
            },
        ],
    )

    analyzer = TaskAnalyzer(str(project_root))
    report = analyzer.analyze_evolution_session(session_file=session_file)

    assert report.goal == "执行去人格化输入验证"


def test_analyze_evolution_session_detects_repeated_pipe_misuse_and_language_drift(tmp_path):
    project_root = tmp_path
    log_dir = project_root / "log_info"
    log_dir.mkdir()
    session_file = log_dir / "conversation_pipe.jsonl"
    _write_jsonl(
        session_file,
        [
            {"type": "session_start", "timestamp": "2026-05-09T11:14:09.000", "session_id": "pipe", "metadata": {}},
            {"type": "human", "content": "分析最新测试"},
            {
                "type": "llm_response",
                "turn": 1,
                "timestamp": "2026-05-09T11:15:41.275",
                "content": "<think>I see the issue and I will inspect the current validation output, compare the runtime state, review the blocked tool pattern, and continue the diagnosis with more observations before making changes.</think>",
            },
            {
                "type": "tool_call",
                "turn": 1,
                "timestamp": "2026-05-09T11:15:16.273",
                "tool_name": "cli_tool",
                "tool_args": {"command": "git diff config.toml config.example.toml 2>&1 | head -30"},
                "tool_result": "[安全拦截] [Whitelist Block] 命令包含危险字符：|",
                "status": "success",
            },
            {
                "type": "tool_call",
                "turn": 1,
                "timestamp": "2026-05-09T11:15:27.373",
                "tool_name": "cli_tool",
                "tool_args": {"command": "git diff core/core_prompt/SPEC.md 2>&1 | head -60"},
                "tool_result": "[安全拦截] [Whitelist Block] 命令包含危险字符：|",
                "status": "success",
            },
            {
                "type": "tool_call",
                "turn": 1,
                "timestamp": "2026-05-09T11:15:53.770",
                "tool_name": "read_file_tool",
                "tool_args": {"file_path": "core/core_prompt/SPEC.md", "max_lines": 80},
                "tool_result": "content",
                "status": "success",
            },
            {
                "type": "tool_call",
                "turn": 1,
                "timestamp": "2026-05-09T11:16:52.130",
                "tool_name": "run_test_for_tool",
                "tool_args": {"source_path": "core/infrastructure/security.py", "timeout": 120},
                "tool_result": "FAILED test_validate_file_path",
                "status": "success",
            },
            {
                "type": "tool_call",
                "turn": 1,
                "timestamp": "2026-05-09T11:17:22.886",
                "tool_name": "get_code_entity_tool",
                "tool_args": {"file_path": "core/infrastructure/security.py", "entity_name": "validate_path"},
                "tool_result": "entity",
                "status": "success",
            },
            {
                "type": "tool_call",
                "turn": 1,
                "timestamp": "2026-05-09T11:17:50.436",
                "tool_name": "get_code_entity_tool",
                "tool_args": {"file_path": "core/infrastructure/security.py", "entity_name": "is_within_project"},
                "tool_result": "entity",
                "status": "success",
            },
            {"type": "session_end", "timestamp": "2026-05-09T11:20:30.064", "session_id": "pipe", "total_turns": 1, "summary": {"uptime_seconds": 10, "total_turns": 1}},
        ],
    )

    analyzer = TaskAnalyzer(str(project_root))
    report = analyzer.analyze_evolution_session(session_file=session_file)
    memory = analyzer.build_next_round_state_memory(report)

    assert report.repeated_failure_patterns
    assert report.tool_misuse_patterns
    assert report.language_drift_detected is True
    assert report.diagnostic_drift_detected is True
    assert report.next_round_constraints
    assert "## 延续约束" in memory
