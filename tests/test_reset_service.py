import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.ui.chat_state import load_chat_state, save_chat_state
from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import reset_service


@pytest.fixture
def reset_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(reset_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(reset_service, "get_web_language", lambda: "zh")
    return tmp_path


def _write(path: Path, content: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _seed_scene(project_root: Path, directory_name: str, scene_id: str, status: str) -> Path:
    scene_dir = project_root / "logs" / "runtime_scenes" / directory_name
    scene_dir.mkdir(parents=True, exist_ok=True)
    _write(
        scene_dir / "manifest.json",
        json.dumps({"runtime_scene_id": scene_id, "status": status}, ensure_ascii=False),
    )
    _write(scene_dir / "raw" / "backend.log", "scene")
    return scene_dir


def test_reset_summary_uses_allow_list_and_protects_memory(reset_project: Path):
    _write(reset_project / "workspace" / "memory" / "long-term.md", "keep")
    _write(reset_project / "workspace" / "prompts" / "dynamic.md", "keep")
    _write(reset_project / "workspace" / "chat" / "chat_state.json", "{}")
    _write(reset_project / "web" / "dist" / "index.html", "<html></html>")

    summary = reset_service.get_reset_summary()

    item_ids = {item["id"] for item in summary["items"]}
    assert "chat_history" in item_ids
    assert "web_dist" in item_ids
    assert "workspace" not in item_ids
    assert summary["presets"] == []
    protected_paths = {path for group in summary["protected"] for path in group["paths"]}
    assert "workspace/memory/" in protected_paths
    assert "workspace/prompts/" in protected_paths


def test_preview_is_non_destructive_and_reports_candidates(reset_project: Path):
    log_file = _write(reset_project / "log_info" / "conversation_001.jsonl", "{}\n")
    debug_file = _write(reset_project / "log_info" / "debug_001.log", "debug")

    preview = reset_service.preview_reset(["conversation_logs"])

    assert log_file.exists()
    assert debug_file.exists()
    assert preview["totals"]["deleteCount"] == 2
    paths = {item["path"] for item in preview["items"][0]["deleteCandidates"]}
    assert paths == {"log_info/conversation_001.jsonl", "log_info/debug_001.log"}


def test_execute_selected_items_deletes_only_allow_list_targets(reset_project: Path):
    _write(reset_project / "log_info" / "conversation_001.jsonl", "{}\n")
    _write(reset_project / "logs" / "agent_realtime.log", "runtime")
    _write(reset_project / "logs" / "runtime_scenes" / "keep" / "raw.log", "scene")
    _write(reset_project / "workspace" / "memory" / "long-term.md", "keep")
    _write(reset_project / "workspace" / "prompts" / "dynamic.md", "keep")
    _write(reset_project / "workspace" / "supervised_evolution" / "decision.json", "{}")

    result = reset_service.execute_reset(["conversation_logs", "runtime_logs"], confirmed=True)

    assert result["totals"]["deletedCount"] == 2
    assert not (reset_project / "log_info" / "conversation_001.jsonl").exists()
    assert not (reset_project / "logs" / "agent_realtime.log").exists()
    assert (reset_project / "logs" / "runtime_scenes" / "keep" / "raw.log").exists()
    assert (reset_project / "workspace" / "memory" / "long-term.md").exists()
    assert (reset_project / "workspace" / "prompts" / "dynamic.md").exists()
    assert (reset_project / "workspace" / "supervised_evolution" / "decision.json").exists()


def test_execute_chat_history_recreates_empty_default_session(reset_project: Path):
    save_chat_state(reset_project, {"version": 1, "conversations": [{"messages": [{"role": "user", "content": "old"}]}]})

    result = reset_service.execute_reset(["chat_history"], confirmed=True)
    state = load_chat_state(reset_project)

    assert result["items"][0]["deleted"][0]["action"] == "reset"
    assert state["conversations"][0]["messages"] == []
    assert state["active_conversation_id"] == "default"


def test_chat_history_is_available_even_before_state_file_exists(reset_project: Path):
    preview = reset_service.preview_reset(["chat_history"])

    assert preview["totals"]["deleteCount"] == 1
    assert preview["items"][0]["deleteCandidates"][0]["action"] == "reset"

    result = reset_service.execute_reset(["chat_history"], confirmed=True)

    assert result["totals"]["deletedCount"] == 1
    assert (reset_project / "workspace" / "chat" / "chat_state.json").exists()


def test_runtime_scene_cleanup_skips_running_and_current_scene(reset_project: Path):
    stopped = _seed_scene(reset_project, "20260501T000000Z__stopped", "stopped", "stopped")
    running = _seed_scene(reset_project, "20260501T010000Z__running", "running", "running")
    current = _seed_scene(reset_project, "20260501T020000Z__current", "current", "stopped")
    _write(
        reset_project / ".runtime" / "launcher" / "state.json",
        json.dumps({"runtimeSceneDir": str(current)}, ensure_ascii=False),
    )

    preview = reset_service.preview_reset(["stopped_runtime_scenes"])
    protected_paths = {item["path"] for item in preview["items"][0]["protected"]}
    delete_paths = {item["path"] for item in preview["items"][0]["deleteCandidates"]}

    assert "logs/runtime_scenes/20260501T000000Z__stopped" in delete_paths
    assert "logs/runtime_scenes/20260501T010000Z__running" in protected_paths
    assert "logs/runtime_scenes/20260501T020000Z__current" in protected_paths

    result = reset_service.execute_reset(["stopped_runtime_scenes"], confirmed=True)

    assert result["totals"]["deletedCount"] == 1
    assert not stopped.exists()
    assert running.exists()
    assert current.exists()


def test_browser_profile_cleanup_protects_current_profile(reset_project: Path):
    current = reset_project / ".runtime" / "launcher" / "edge-app-profile"
    old = reset_project / ".runtime" / "old-test-profile"
    _write(current / "Default" / "LOCK", "locked")
    _write(old / "Default" / "Preferences", "{}")
    _write(
        reset_project / ".runtime" / "launcher" / "state.json",
        json.dumps({"browserProfileDir": str(current)}, ensure_ascii=False),
    )

    result = reset_service.execute_reset(["browser_profiles"], confirmed=True)

    assert result["totals"]["deletedCount"] == 1
    assert current.exists()
    assert not old.exists()


def test_unknown_reset_item_is_rejected(reset_project: Path):
    with pytest.raises(ValueError, match="Unknown reset item id"):
        reset_service.preview_reset(["../workspace"])


def test_reset_routes_expose_preview_and_execute(reset_project: Path):
    _write(reset_project / "web" / "dist" / "index.html", "<html></html>")
    client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})

    summary_response = client.get("/api/reset/summary")
    preview_response = client.post("/api/reset/preview", json={"itemIds": ["web_dist"]})
    rejected_response = client.post("/api/reset/preview", json={"itemIds": ["bad"]})
    execute_response = client.post("/api/reset/execute", json={"itemIds": ["web_dist"], "confirmed": True})

    assert summary_response.status_code == 200
    assert summary_response.json()["mode"] == "custom"
    assert preview_response.status_code == 200
    assert preview_response.json()["totals"]["deleteCount"] == 1
    assert rejected_response.status_code == 400
    assert execute_response.status_code == 200
    assert not (reset_project / "web" / "dist").exists()
