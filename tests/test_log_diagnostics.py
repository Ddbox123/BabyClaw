import json
from pathlib import Path

from core.web.services import log_service, runtime_scene_service


def test_log_roots_include_user_and_agent_summaries(tmp_path, monkeypatch):
    runtime_log = tmp_path / "logs" / "agent_realtime.log"
    runtime_log.parent.mkdir(parents=True, exist_ok=True)
    runtime_log.write_text("runtime line\n", encoding="utf-8")
    runtime_scene_log = tmp_path / "logs" / "runtime_scenes" / "scene-a" / "raw" / "backend.log"
    runtime_scene_log.parent.mkdir(parents=True, exist_ok=True)
    runtime_scene_log.write_text("ignored from runtime root summary\n", encoding="utf-8")

    conversation_log = tmp_path / "log_info" / "conversation_debug.jsonl"
    conversation_log.parent.mkdir(parents=True, exist_ok=True)
    conversation_log.write_text('{"type":"external_request"}\n', encoding="utf-8")

    monkeypatch.setattr(log_service, "PROJECT_ROOT", tmp_path)

    roots = log_service.list_log_roots()

    runtime_root = next(item for item in roots if item["id"] == "runtime_logs")
    assert runtime_root["summary"]["fileCount"] == 1
    assert runtime_root["summary"]["latestPath"] == "agent_realtime.log"
    assert "后端" in runtime_root["summary"]["userGuide"]
    assert "runtime_scenes" in runtime_root["summary"]["agentGuide"]

    conversation_root = next(item for item in roots if item["id"] == "conversation_logs")
    assert conversation_root["summary"]["fileCount"] == 1
    assert "conversation_" in conversation_root["summary"]["agentGuide"]


def test_log_file_content_returns_user_summary_and_agent_anchor(tmp_path, monkeypatch):
    conversation_log = tmp_path / "log_info" / "conversation_debug.jsonl"
    conversation_log.parent.mkdir(parents=True, exist_ok=True)
    conversation_log.write_text(
        "\n".join(
            [
                json.dumps({"type": "external_request", "content": "复现问题"}, ensure_ascii=False),
                json.dumps({"type": "tool_call", "tool": "read_file_tool", "status": "success"}, ensure_ascii=False),
                "Traceback (most recent call last): RuntimeError: failed to stop subagent",
                "WARNING retrying stop request",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(log_service, "PROJECT_ROOT", tmp_path)

    payload = log_service.read_log_file("conversation_logs", "conversation_debug.jsonl")

    diagnostics = payload["diagnostics"]
    assert diagnostics["severity"] == "error"
    assert diagnostics["lineCount"] == 4
    assert diagnostics["errorCount"] == 1
    assert diagnostics["warningCount"] == 1
    assert diagnostics["firstSignalLine"] == 3
    assert "failed to stop subagent" in diagnostics["firstSignalPreview"]
    assert diagnostics["topEventTypes"][0] == {"type": "external_request", "count": 1}
    assert "conversation_logs/conversation_debug.jsonl:3" in diagnostics["agentHint"]
    assert "错误筛选" in diagnostics["suggestedNextStep"]


def test_runtime_scene_raw_content_returns_same_diagnostics_shape(tmp_path, monkeypatch):
    scene_dir = tmp_path / "logs" / "runtime_scenes" / "20260518T120000Z__scene-a"
    raw_dir = scene_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (scene_dir / "manifest.json").write_text(
        json.dumps({"runtime_scene_id": "scene-a"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (raw_dir / "backend.stdout.log").write_text("uvicorn started\n", encoding="utf-8")

    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)

    payload = runtime_scene_service.read_runtime_scene_file("scene-a", "raw/backend.stdout.log")

    diagnostics = payload["diagnostics"]
    assert diagnostics["severity"] == "info"
    assert diagnostics["userSummary"] == "这份原始日志未发现明显错误或警告，可作为运行现场的补充证据。"
    assert diagnostics["agentHint"] == "runtime_scenes/scene-a/raw/backend.stdout.log; severity=info"
