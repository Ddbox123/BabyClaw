#!/usr/bin/env python3
import json
from pathlib import Path

from core.logging.logger import ConversationLogger
from core.logging.transcript_logger import TranscriptLogger


def _fresh_logger(tmp_path: Path) -> ConversationLogger:
    ConversationLogger._instance = None
    logger = ConversationLogger()
    logger._log_dir = str(tmp_path)
    logger._current_session_file = None
    logger._session_id = "test_session"
    logger._turn_count = 0
    logger._session_active = False
    logger._ensure_log_dir()
    logger.start_session()
    return logger


def test_system_prompt_uses_preview_and_sidecar_for_long_payload(tmp_path):
    logger = _fresh_logger(tmp_path)
    long_text = "A" * 1200 + "\n" + "B" * 1200

    logger.log_system_prompt(long_text)

    session_file = tmp_path / "conversation_test_session.jsonl"
    lines = [json.loads(line) for line in session_file.read_text(encoding="utf-8").splitlines()]
    record = lines[-1]

    assert record["type"] == "system_prompt"
    assert record["content_inlined"] is False
    assert "content_preview" in record
    assert "content_ref" in record
    assert "content" not in record
    assert (tmp_path / record["content_ref"]).exists()


def test_tool_result_keeps_main_log_compact_and_spills_raw_payload(tmp_path):
    logger = _fresh_logger(tmp_path)
    logger._turn_count = 1
    long_result = "result-head\n" + ("X" * 1500) + "\nresult-tail"

    logger.log_tool_call("read_file_tool", {"file_path": "demo.py"}, tool_result=long_result)

    session_file = tmp_path / "conversation_test_session.jsonl"
    lines = [json.loads(line) for line in session_file.read_text(encoding="utf-8").splitlines()]
    record = lines[-1]

    assert record["type"] == "tool_call"
    assert record["tool_result_inlined"] is False
    assert "tool_result_preview" in record
    assert "result-head" in record["tool_result_preview"]
    assert "result-tail" in record["tool_result_preview"]
    assert (tmp_path / record["tool_result_ref"]).exists()


def test_llm_response_raw_length_falls_back_to_content_when_raw_missing(tmp_path):
    logger = _fresh_logger(tmp_path)
    logger._turn_count = 1

    logger.log_llm_response("OK", input_tokens=1, output_tokens=1, tool_call_count=0)

    session_file = tmp_path / "conversation_test_session.jsonl"
    lines = [json.loads(line) for line in session_file.read_text(encoding="utf-8").splitlines()]
    record = lines[-1]

    assert record["type"] == "llm_response"
    assert record["raw_length"] == 2
    assert record["content"] == "OK"


def test_inherited_subagent_session_appends_to_parent_log_with_actor_metadata(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_LOG_SESSION_ID", "parent_session")
    monkeypatch.setenv("VIBELUTION_LOG_ACTOR", "subagent")
    monkeypatch.setenv("VIBELUTION_LOG_PARENT_TURN", "7")
    monkeypatch.setenv("VIBELUTION_LOG_ACTOR_LABEL", "diagnose")
    monkeypatch.setenv("VIBELUTION_SUBAGENT_DEPTH", "1")

    ConversationLogger._instance = None
    logger = ConversationLogger()
    logger._log_dir = str(tmp_path)
    logger._current_session_file = None
    logger._ensure_log_dir()
    logger.new_session()
    logger.start_session({"mode": "single_turn"})
    logger.log_external_request("分析为什么超时")
    logger.log_subagent_stream("stdout", "<think>先看日志</think>", task_type="diagnose", goal="分析超时")
    logger.end_session({"ok": True})

    session_file = tmp_path / "conversation_parent_session.jsonl"
    lines = [json.loads(line) for line in session_file.read_text(encoding="utf-8").splitlines()]

    assert lines[0]["type"] == "session_attach"
    assert lines[0]["actor"] == "subagent"
    assert lines[0]["parent_turn"] == 7
    assert lines[1]["type"] == "external_request"
    assert lines[1]["actor"] == "subagent"
    assert lines[1]["actor_label"] == "diagnose"
    assert lines[2]["type"] == "subagent_stream"
    assert lines[2]["actor"] == "subagent"
    assert lines[2]["content"] == "<think>先看日志</think>"
    assert lines[-1]["type"] == "session_detach"


def test_external_request_api_writes_external_request(tmp_path):
    logger = _fresh_logger(tmp_path)

    logger.log_external_request("外部任务")

    session_file = tmp_path / "conversation_test_session.jsonl"
    lines = [json.loads(line) for line in session_file.read_text(encoding="utf-8").splitlines()]

    assert lines[-1]["type"] == "external_request"
    assert lines[-1]["content"] == "外部任务"


def test_session_file_name_includes_readable_label(tmp_path):
    logger = _fresh_logger(tmp_path)
    logger._session_id = "20260520_120001"
    logger._current_session_file = None
    logger.start_session({
        "mode": "single_turn",
        "agent_mode": "chat",
        "conversation_topic": "继续修复对话日志吞消息问题",
    })

    session_file = Path(logger._get_session_file())
    assert session_file.name == "conversation_20260520_120001__chat__继续修复对话日志吞消息问题.jsonl"
    record = json.loads(session_file.read_text(encoding="utf-8").splitlines()[-1])
    assert record["session_label"] == "chat__继续修复对话日志吞消息问题"


def test_turn_end_writes_round_summary_before_terminal_marker(tmp_path):
    logger = _fresh_logger(tmp_path)

    logger.log_turn_end(1, {"iterations": 3, "tool_calls": 2})

    session_file = tmp_path / "conversation_test_session.jsonl"
    lines = [json.loads(line) for line in session_file.read_text(encoding="utf-8").splitlines()]

    assert lines[-2]["type"] == "round_summary"
    assert lines[-2]["turn"] == 1
    assert lines[-2]["summary"]["session_id"] == "test_session"
    assert lines[-2]["summary"]["stats"] == {"iterations": 3, "tool_calls": 2}
    assert lines[-1]["type"] == "turn_end"
    assert lines[-1]["stats"] == {"iterations": 3, "tool_calls": 2}


def test_transcript_writer_marks_queue_items_done(tmp_path):
    TranscriptLogger._instance = None
    logger = TranscriptLogger()
    logger._logs_dir = tmp_path
    logger.start_session()
    logger.write_external_request("flush me")

    logger._flush_pending_writes()

    assert logger._write_queue.unfinished_tasks == 0
    assert "flush me" in logger._get_transcript_file().read_text(encoding="utf-8")


def test_transcript_writer_marks_failed_items_done(tmp_path):
    TranscriptLogger._instance = None
    logger = TranscriptLogger()
    logger._logs_dir = tmp_path
    logger._write_queue.put((tmp_path, "cannot append to directory"))

    logger._flush_pending_writes()

    assert logger._write_queue.unfinished_tasks == 0
