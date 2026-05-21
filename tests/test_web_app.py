import copy
import json
import shutil
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.evaluation.chat_dataset_capture import ChatDatasetCaptureService, resolve_chat_dataset_paths
from core.evaluation.chat_segmenter import ChatTurnRecord
from config.public_config import UNCONFIGURED_MODEL_REF, load_public_config, public_config_hash
from core.gym import run_gym_collection_episode
from core.gym.promotion import (
    activate_gym_promotion_proposal,
    apply_gym_promotion_proposal,
    rollback_gym_promotion_proposal,
)
from core.web import app as web_app
from core.ui.chat_state import load_chat_state, save_chat_state
from core.runtime_manager import constants as runtime_manager_constants
from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import (
    chat_review_service,
    config_service,
    evolution_service,
    git_status_service,
    log_service,
    runtime_service,
    runtime_scene_service,
    session_service,
    self_evolution_control_service,
    self_evolution_service,
    supervised_control_service,
    workbench_contract_service,
)
from tests.test_gym_runner import RunnerFakeAdapter


client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


@pytest.fixture(autouse=True)
def disable_runtime_manager_live_control(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(supervised_control_service, "_runtime_manager_live_control_enabled", lambda: False)
    monkeypatch.setattr(self_evolution_control_service, "_runtime_manager_live_control_enabled", lambda: False)


def _read_first_sse_event(response):
    event_name = ""
    data_lines = []
    for line in response.iter_lines():
        if line.startswith("event: "):
            event_name = line[len("event: ") :]
            continue
        if line.startswith("data: "):
            data_lines.append(line[len("data: ") :])
            continue
        if line == "":
            if event_name or data_lines:
                return {
                    "event": event_name,
                    "data": "\n".join(data_lines),
                }
    raise AssertionError("Expected at least one SSE event")


def _real_runtime_manager_evolution_paths(kind: str, run_id: str) -> tuple[Path, Path]:
    root = runtime_manager_constants.PROJECT_ROOT / ".runtime" / "runtime-manager" / "evolution" / kind
    return root / "runs" / f"{run_id}.json", root / "index.json"


def _read_optional_text(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.exists() else None


def _restore_real_runtime_index_if_touched(kind: str, run_id: str, original_index_text: str | None) -> None:
    run_path, index_path = _real_runtime_manager_evolution_paths(kind, run_id)
    if run_path.exists():
        run_path.unlink()
    if index_path.exists() and run_id in index_path.read_text(encoding="utf-8"):
        if original_index_text is None:
            index_path.unlink()
        else:
            index_path.write_text(original_index_text, encoding="utf-8")


def test_web_control_token_endpoint_is_local_and_required_for_mutations():
    guarded_client = TestClient(create_app())

    token_response = guarded_client.get("/api/control-token")
    assert token_response.status_code == 200
    token_payload = token_response.json()
    assert token_payload["header"] == CONTROL_TOKEN_HEADER
    assert token_payload["controlToken"]

    read_response = guarded_client.get("/api/health")
    assert read_response.status_code == 200

    rejected_response = guarded_client.post("/api/runtime/shutdown")
    assert rejected_response.status_code == 403
    assert "control token" in rejected_response.json()["detail"]

    accepted_client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: token_payload["controlToken"]})
    accepted_response = accepted_client.post(
        "/api/runtime/browser-telemetry",
        json={"phase": "page", "eventCode": "probe", "message": "accepted"},
    )
    assert accepted_response.status_code == 202


def test_web_control_guard_rejects_untrusted_origin_even_with_token():
    guarded_client = TestClient(create_app())

    response = guarded_client.post(
        "/api/runtime/browser-telemetry",
        headers={
            CONTROL_TOKEN_HEADER: get_control_token(),
            "Origin": "https://example.invalid",
        },
        json={"phase": "page", "eventCode": "probe", "message": "blocked"},
    )

    assert response.status_code == 403
    assert "origin" in response.json()["detail"].lower()


def test_web_control_token_endpoint_rejects_untrusted_origin():
    guarded_client = TestClient(create_app())

    response = guarded_client.get(
        "/api/control-token",
        headers={"Origin": "https://example.invalid"},
    )

    assert response.status_code == 403
    assert "origin" in response.json()["detail"].lower()


def test_static_assets_allow_same_origin_referer_on_custom_port(tmp_path, monkeypatch):
    dist_dir = tmp_path / "web-dist"
    assets_dir = dist_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    (dist_dir / "index.html").write_text("<!doctype html><html><body>app</body></html>", encoding="utf-8")
    (assets_dir / "app.js").write_text("console.log('ok');", encoding="utf-8")

    monkeypatch.setattr("core.web.app.WEB_DIST", dist_dir)
    temp_client = TestClient(create_app(), base_url="http://127.0.0.1:8012")

    response = temp_client.get("/assets/app.js", headers={"Referer": "http://127.0.0.1:8012/"})

    assert response.status_code == 200, response.text
    assert "console.log" in response.text


def test_static_assets_reject_cross_origin_referer(tmp_path, monkeypatch):
    dist_dir = tmp_path / "web-dist"
    assets_dir = dist_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    (dist_dir / "index.html").write_text("<!doctype html><html><body>app</body></html>", encoding="utf-8")
    (assets_dir / "app.js").write_text("console.log('ok');", encoding="utf-8")

    monkeypatch.setattr("core.web.app.WEB_DIST", dist_dir)
    temp_client = TestClient(create_app(), base_url="http://127.0.0.1:8012")

    response = temp_client.get("/assets/app.js", headers={"Referer": "https://example.invalid/"})

    assert response.status_code == 403
    assert "referer" in response.json()["detail"].lower()


def _seed_runtime_scene_bundle(project_root: Path, scene_id: str = "scene-1", status: str = "stopped") -> Path:
    scene_dir = project_root / "logs" / "runtime_scenes" / f"20260518T120000Z__{scene_id}"
    events_dir = scene_dir / "events"
    raw_dir = scene_dir / "raw"
    events_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)
    (scene_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "runtime_scene_id": scene_id,
                "title": f"Managed workbench run {scene_id}",
                "package": {
                    "schema_version": 2,
                    "timeline_path": "timeline.jsonl",
                    "lifecycle_path": "lifecycle.jsonl",
                    "raw_dir": "raw",
                    "conversations_dir": "conversations",
                    "agent_dir": "agent",
                    "artifacts_dir": "artifacts",
                },
                "started_at": "2026-05-18T12:00:00Z",
                "ended_at": "" if status == "running" else "2026-05-18T12:03:00Z",
                "status": status,
                "result": "" if status == "running" else "explicit_stop",
                "stop_reason": "" if status == "running" else "explicit stop",
                "trigger": "start",
                "session_mode": "managed",
                "host": "127.0.0.1",
                "port": 8000,
                "url": "http://127.0.0.1:8000",
                "frontend": {
                    "build_status": "success",
                    "build_reason": "frontend sources changed",
                    "log_path": "raw/frontend.build.log",
                },
                "backend": {
                    "pid": 12345,
                    "health_status": "stopped",
                    "stdout_path": "raw/backend.stdout.log",
                    "stderr_path": "raw/backend.stderr.log",
                },
                "browser": {
                    "managed": True,
                    "status": "stopped",
                    "log_path": "raw/browser.log",
                    "launch_pid": 222,
                    "window_pid": 333,
                },
                "supervisor": {
                    "pid": 444,
                    "status": "stopped",
                    "log_path": "raw/supervisor.log",
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (events_dir / "frontend.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "runtime_scene_id": scene_id,
                        "ts": "2026-05-18T12:00:01Z",
                        "seq": 1,
                        "component": "frontend",
                        "phase": "build",
                        "event_code": "frontend.build.started",
                        "level": "info",
                        "outcome": "started",
                        "message": "Starting frontend build.",
                        "fields": {"reason": "frontend sources changed"},
                        "raw_refs": [{"path": "raw/frontend.build.log", "tail_lines": 40}],
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "runtime_scene_id": scene_id,
                        "ts": "2026-05-18T12:00:03Z",
                        "seq": 2,
                        "component": "frontend",
                        "phase": "build",
                        "event_code": "frontend.build.succeeded",
                        "level": "info",
                        "outcome": "succeeded",
                        "message": "Frontend build completed successfully.",
                        "fields": {"output": "web/dist/index.html"},
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (events_dir / "backend.jsonl").write_text(
        json.dumps(
            {
                "runtime_scene_id": scene_id,
                "ts": "2026-05-18T12:00:05Z",
                "seq": 1,
                "component": "backend",
                "phase": "health",
                "event_code": "backend.health.succeeded",
                "level": "info",
                "outcome": "succeeded",
                "message": "Backend passed health checks.",
                "fields": {"pid": 12345, "url": "http://127.0.0.1:8000"},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (raw_dir / "frontend.build.log").write_text("vite build ok\n", encoding="utf-8")
    (raw_dir / "backend.stdout.log").write_text("uvicorn started\n", encoding="utf-8")
    (raw_dir / "backend.stderr.log").write_text("", encoding="utf-8")
    (raw_dir / "supervisor.log").write_text("supervisor ok\n", encoding="utf-8")
    (raw_dir / "browser.log").write_text("browser open\n", encoding="utf-8")
    timeline_payloads = [
        line
        for path in sorted(events_dir.glob("*.jsonl"))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    (scene_dir / "timeline.jsonl").write_text("\n".join(timeline_payloads) + "\n", encoding="utf-8")
    (scene_dir / "lifecycle.jsonl").write_text("\n".join(timeline_payloads) + "\n", encoding="utf-8")
    return scene_dir


def _runtime_scene_local_index_parts(iso_value: str) -> tuple[str, str, str]:
    parsed = datetime.fromisoformat(iso_value.replace("Z", "+00:00")).astimezone()
    return parsed.strftime("%Y-%m-%d"), parsed.strftime("%H:%M:%S"), parsed.strftime("%H-%M-%S")


def test_runtime_summary_shape():
    response = client.get("/api/runtime/summary")
    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["agentName"] == "Vibelution"
    assert "mode" in payload
    assert "profile" in payload
    assert "sessionState" in payload
    assert "sessionStateLine" in payload
    assert "sessionNeedsResponse" in payload
    assert "sessionUpdatedAt" in payload
    assert "mentalState" in payload
    assert "runtimeManager" in payload
    assert "workbench" in payload


def test_ignores_windows_proactor_disconnect_noise(monkeypatch):
    monkeypatch.setattr(web_app.os, "name", "nt", raising=False)

    context = {
        "message": "Exception in callback _ProactorBasePipeTransport._call_connection_lost(None)",
        "exception": ConnectionResetError(10054, "connection reset"),
        "handle": "<Handle _ProactorBasePipeTransport._call_connection_lost(None)>",
    }

    assert web_app._is_windows_proactor_disconnect_noise(context) is True


def test_keeps_non_proactor_or_non_windows_disconnects_visible(monkeypatch):
    monkeypatch.setattr(web_app.os, "name", "nt", raising=False)

    assert web_app._is_windows_proactor_disconnect_noise(
        {
            "message": "Exception in callback some_other_handle",
            "exception": ConnectionResetError(10054, "connection reset"),
            "handle": "<Handle some_other_handle>",
        }
    ) is False

    monkeypatch.setattr(web_app.os, "name", "posix", raising=False)
    assert web_app._is_windows_proactor_disconnect_noise(
        {
            "message": "Exception in callback _ProactorBasePipeTransport._call_connection_lost(None)",
            "exception": ConnectionResetError(10054, "connection reset"),
            "handle": "<Handle _ProactorBasePipeTransport._call_connection_lost(None)>",
        }
    ) is False


def test_runtime_shutdown_queues_runtime_manager_when_state_exists(tmp_path, monkeypatch):
    script_path = tmp_path / "vibelution_launcher.ps1"
    script_path.write_text("Write-Host managed\n", encoding="utf-8")
    state_path = tmp_path / "state.json"
    state_path.write_text("{}", encoding="utf-8")
    calls: list[object] = []

    monkeypatch.setattr(runtime_service, "LAUNCHER_SCRIPT_PATH", script_path)
    monkeypatch.setattr(runtime_service, "LAUNCHER_STATE_PATH", state_path)
    monkeypatch.setattr(runtime_service.os, "name", "nt", raising=False)
    monkeypatch.setattr(runtime_service, "list_active_session_work_runs", lambda: [])
    monkeypatch.setattr(runtime_service, "ensure_daemon_running", lambda: calls.append("ensure"))
    monkeypatch.setattr(
        runtime_service,
        "submit_command",
        lambda command_type, args=None, requested_by="unknown": calls.append((command_type, args, requested_by)),
    )

    response = client.post("/api/runtime/shutdown")

    assert response.status_code == 202
    assert response.json()["accepted"] is True
    assert response.json()["mode"] == "runtime_manager"
    assert response.json()["chatTurns"] == []
    assert calls[0] == "ensure"
    assert calls[1] == ("close_workbench", {"reason": "web_close_button", "source": "web_ui"}, "web_ui")


def test_runtime_shutdown_stops_active_chat_turn_before_manager_close(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)
    script_path = tmp_path / "vibelution_launcher.ps1"
    script_path.write_text("Write-Host managed\n", encoding="utf-8")
    state_path = tmp_path / "state.json"
    state_path.write_text("{}", encoding="utf-8")
    calls: list[object] = []

    monkeypatch.setattr(runtime_service, "LAUNCHER_SCRIPT_PATH", script_path)
    monkeypatch.setattr(runtime_service, "LAUNCHER_STATE_PATH", state_path)
    monkeypatch.setattr(runtime_service.os, "name", "nt", raising=False)
    monkeypatch.setattr(runtime_service, "ensure_daemon_running", lambda: calls.append("ensure"))
    monkeypatch.setattr(
        runtime_service,
        "submit_command",
        lambda command_type, args=None, requested_by="unknown": calls.append((command_type, args, requested_by)),
    )

    try:
        submit_response = client.post(
            "/api/sessions/session-live/messages",
            json={"content": "关闭前保存当前对话现场"},
        )
        assert submit_response.status_code == 202
        turn_control = session_service._get_session_turn_control("session-live")
        assert turn_control is not None
        session_service._set_session_live_output(
            "session-live",
            turn_id=turn_control.turn_id,
            thought="关闭前已经捕获到思考片段。",
            content="当前回答已经输出了一半。",
            tool_calls=[{"name": "read_file_tool", "status": "done", "summary": "runtime_service.py"}],
        )

        response = client.post("/api/runtime/shutdown")

        assert response.status_code == 202
        payload = response.json()
        assert payload["accepted"] is True
        assert payload["mode"] == "runtime_manager"
        assert payload["chatTurns"] == [
            {"sessionId": "session-live", "runId": turn_control.turn_id, "status": "stopped"}
        ]
        assert calls == [
            "ensure",
            ("close_workbench", {"reason": "web_close_button", "source": "web_ui"}, "web_ui"),
        ]

        detail_response = client.get("/api/sessions/session-live")
        assert detail_response.status_code == 200
        detail = detail_response.json()
        assert detail["currentPhase"] == "ready"
        assert detail["messages"][-1]["role"] == "assistant"
        assert "当前回答已经输出了一半" in detail["messages"][-1]["content"]
        assert "本轮已按请求停止" in detail["messages"][-1]["content"]
        assert detail["messages"][-1]["thought"] == "关闭前已经捕获到思考片段。"
        assert detail["messages"][-1]["toolCalls"][0]["name"] == "read_file_tool"
        assert session_service.load_chat_turn_work_run_summary()["active"] is None
    finally:
        session_service._set_session_running("session-live", False)
        session_service._clear_session_turn_control("session-live")
        session_service._clear_session_live_output("session-live")


def test_runtime_shutdown_continues_when_chat_stop_fails(tmp_path, monkeypatch):
    script_path = tmp_path / "vibelution_launcher.ps1"
    script_path.write_text("Write-Host managed\n", encoding="utf-8")
    state_path = tmp_path / "state.json"
    state_path.write_text("{}", encoding="utf-8")
    calls: list[object] = []

    def fail_stop(session_id):
        raise RuntimeError(f"stop failed for {session_id}")

    monkeypatch.setattr(runtime_service, "LAUNCHER_SCRIPT_PATH", script_path)
    monkeypatch.setattr(runtime_service, "LAUNCHER_STATE_PATH", state_path)
    monkeypatch.setattr(runtime_service.os, "name", "nt", raising=False)
    monkeypatch.setattr(
        runtime_service,
        "list_active_session_work_runs",
        lambda: [{"sessionId": "session-live", "runId": "chat-turn-live", "status": "running"}],
    )
    monkeypatch.setattr(runtime_service, "request_stop_session_turn", fail_stop)
    monkeypatch.setattr(runtime_service, "ensure_daemon_running", lambda: calls.append("ensure"))
    monkeypatch.setattr(
        runtime_service,
        "submit_command",
        lambda command_type, args=None, requested_by="unknown": calls.append((command_type, args, requested_by)),
    )

    response = client.post("/api/runtime/shutdown")

    assert response.status_code == 202
    payload = response.json()
    assert payload["accepted"] is True
    assert payload["mode"] == "runtime_manager"
    assert payload["chatTurns"][0]["sessionId"] == "session-live"
    assert payload["chatTurns"][0]["runId"] == "chat-turn-live"
    assert payload["chatTurns"][0]["status"] == "failed"
    assert "RuntimeError" in payload["chatTurns"][0]["error"]
    assert calls == [
        "ensure",
        ("close_workbench", {"reason": "web_close_button", "source": "web_ui"}, "web_ui"),
    ]


def test_runtime_shutdown_falls_back_to_launcher_stop_when_manager_queue_fails(tmp_path, monkeypatch):
    script_path = tmp_path / "vibelution_launcher.ps1"
    script_path.write_text("Write-Host managed\n", encoding="utf-8")
    state_path = tmp_path / "state.json"
    state_path.write_text("{}", encoding="utf-8")
    calls: list[str] = []

    monkeypatch.setattr(runtime_service, "LAUNCHER_SCRIPT_PATH", script_path)
    monkeypatch.setattr(runtime_service, "LAUNCHER_STATE_PATH", state_path)
    monkeypatch.setattr(runtime_service.os, "name", "nt", raising=False)
    monkeypatch.setattr(runtime_service, "list_active_session_work_runs", lambda: [])
    monkeypatch.setattr(runtime_service, "ensure_daemon_running", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(runtime_service, "_spawn_managed_launcher_shutdown", lambda: calls.append("fallback"))

    response = client.post("/api/runtime/shutdown")

    assert response.status_code == 202
    assert response.json()["accepted"] is True
    assert response.json()["mode"] == "managed_fallback"
    assert response.json()["chatTurns"] == []
    assert calls == ["fallback"]


def test_runtime_shutdown_falls_back_to_local_exit_when_not_managed(monkeypatch):
    calls: list[str] = []

    monkeypatch.setattr(runtime_service, "LAUNCHER_SCRIPT_PATH", Path("missing-launcher.ps1"))
    monkeypatch.setattr(runtime_service, "LAUNCHER_STATE_PATH", Path("missing-state.json"))
    monkeypatch.setattr(runtime_service.os, "name", "nt", raising=False)
    monkeypatch.setattr(runtime_service, "list_active_session_work_runs", lambda: [])
    monkeypatch.setattr(runtime_service, "_schedule_local_backend_exit", lambda delay_seconds=0.35: calls.append("local"))

    response = client.post("/api/runtime/shutdown")

    assert response.status_code == 202
    assert response.json()["accepted"] is True
    assert response.json()["mode"] == "local"
    assert response.json()["chatTurns"] == []
    assert calls == ["local"]


def test_files_tree_lists_repo_entries():
    response = client.get("/api/files/tree")
    assert response.status_code == 200, response.json()
    payload = response.json()
    assert any(item["name"] == "core" for item in payload)
    assert any(item["name"] == "docs" for item in payload)


def test_file_content_rejects_path_escape():
    response = client.get("/api/files/content", params={"path": "../outside.txt"})
    assert response.status_code == 400
    assert "project root" in response.json()["detail"]


def test_git_status_endpoint_exposes_read_only_worktree_snapshot(monkeypatch):
    class FakeGitStatusService:
        def scan_working_tree(self, store=False):
            assert store is False
            return SimpleNamespace(
                available=True,
                error=None,
                snapshot_id="wt-test",
                created_at="2026-05-21T10:00:00",
                base_rev="abcdef1234567890",
                files=[
                    SimpleNamespace(
                        path="web/src/app/AppShell.tsx",
                        status=" M",
                        staged=False,
                        unstaged=True,
                        untracked=False,
                        deleted=False,
                        old_path=None,
                    ),
                    SimpleNamespace(
                        path="core/web/routes/git.py",
                        status="??",
                        staged=False,
                        unstaged=False,
                        untracked=True,
                        deleted=False,
                        old_path=None,
                    ),
                ],
            )

        def _git_head_rev(self):
            return "abcdef1234567890"

        def _run_git(self, args):
            if args == ["branch", "--show-current"]:
                return SimpleNamespace(returncode=0, stdout="codex/git-navbar\n")
            if args == ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"]:
                return SimpleNamespace(returncode=0, stdout="origin/codex/git-navbar\n")
            if args == ["rev-list", "--left-right", "--count", "origin/codex/git-navbar...HEAD"]:
                return SimpleNamespace(returncode=0, stdout="1\t2\n")
            raise AssertionError(args)

    monkeypatch.setattr(git_status_service, "get_git_memory_service", lambda: FakeGitStatusService())

    response = client.get("/api/git/status", params={"limit": 1})

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["available"] is True
    assert payload["branch"] == "codex/git-navbar"
    assert payload["headRevShort"] == "abcdef123456"
    assert payload["upstream"]["name"] == "origin/codex/git-navbar"
    assert payload["upstream"]["ahead"] == 2
    assert payload["upstream"]["behind"] == 1
    assert payload["dirty"] is True
    assert payload["counts"] == {
        "total": 2,
        "staged": 0,
        "unstaged": 1,
        "untracked": 1,
        "deleted": 0,
    }
    assert payload["files"][0]["path"] == "web/src/app/AppShell.tsx"
    assert payload["files"][0]["statusLabel"] == "modified"
    assert payload["totalFiles"] == 2
    assert payload["truncated"] is True


def test_git_status_endpoint_reports_unavailable(monkeypatch):
    class FakeUnavailableGitStatusService:
        def scan_working_tree(self, store=False):
            return SimpleNamespace(
                available=False,
                error="not a git repository",
                snapshot_id="unavailable",
                created_at="2026-05-21T10:00:00",
                base_rev=None,
                files=[],
            )

    monkeypatch.setattr(git_status_service, "get_git_memory_service", lambda: FakeUnavailableGitStatusService())

    response = client.get("/api/git/status")

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["available"] is False
    assert payload["dirty"] is False
    assert payload["summary"] == "Git unavailable: not a git repository"
    assert payload["error"] == "not a git repository"
    assert payload["files"] == []


def test_git_commits_endpoint_exposes_recent_commits(monkeypatch):
    class FakeGitStatusService:
        def is_git_available(self):
            return True, None

        def _run_git(self, args):
            assert args == [
                "log",
                "--max-count=2",
                "--date=iso-strict",
                "--pretty=format:%H%x1f%h%x1f%aN%x1f%aI%x1f%s",
            ]
            return SimpleNamespace(
                returncode=0,
                stdout=(
                    "abcdef1234567890\x1fabcdef1\x1fAgent\x1f2026-05-21T10:00:00+08:00\x1ffeat: git page\n"
                    "1111111111111111\x1f1111111\x1fAgent\x1f2026-05-20T10:00:00+08:00\x1ffix: prior"
                ),
                stderr="",
            )

    monkeypatch.setattr(git_status_service, "get_git_memory_service", lambda: FakeGitStatusService())

    response = client.get("/api/git/commits", params={"limit": 2})

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["available"] is True
    assert [item["shortSha"] for item in payload["commits"]] == ["abcdef1", "1111111"]
    assert payload["commits"][0]["subject"] == "feat: git page"


def test_git_diff_endpoint_exposes_file_diff(monkeypatch):
    class FakeGitStatusService:
        def is_git_available(self):
            return True, None

        def scan_working_tree(self, store=False):
            return SimpleNamespace(
                available=True,
                error=None,
                snapshot_id="wt-test",
                created_at="2026-05-21T10:00:00",
                base_rev="abcdef1234567890",
                files=[
                    SimpleNamespace(
                        path="web/src/routes/GitRoute.tsx",
                        status=" M",
                        staged=False,
                        unstaged=True,
                        untracked=False,
                        deleted=False,
                        old_path=None,
                    )
                ],
            )

        def _run_git(self, args):
            if args == ["diff", "--cached", "--no-ext-diff", "--no-color", "--", "web/src/routes/GitRoute.tsx"]:
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            if args == ["diff", "--no-ext-diff", "--no-color", "--", "web/src/routes/GitRoute.tsx"]:
                return SimpleNamespace(returncode=0, stdout="diff --git a/web/src/routes/GitRoute.tsx b/web/src/routes/GitRoute.tsx\n+page\n", stderr="")
            raise AssertionError(args)

    monkeypatch.setattr(git_status_service, "get_git_memory_service", lambda: FakeGitStatusService())

    response = client.get("/api/git/diff", params={"path": "web/src/routes/GitRoute.tsx"})

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["available"] is True
    assert payload["path"] == "web/src/routes/GitRoute.tsx"
    assert payload["language"] == "diff"
    assert "# unstaged" in payload["diff"]
    assert payload["statusLabel"] == "modified"


def test_git_diff_endpoint_rejects_path_escape():
    response = client.get("/api/git/diff", params={"path": "../secret.txt"})

    assert response.status_code == 400
    assert "project root" in response.json()["detail"]


def test_logs_roots_and_tree_are_read_only(tmp_path, monkeypatch):
    runtime_log = tmp_path / "logs" / "agent_realtime.log"
    runtime_log.parent.mkdir(parents=True, exist_ok=True)
    runtime_log.write_text("runtime line\n", encoding="utf-8")
    _seed_runtime_scene_bundle(tmp_path, scene_id="scene-tree")

    workspace_log = tmp_path / "workspace" / "logs" / "turns" / "latest.md"
    workspace_log.parent.mkdir(parents=True, exist_ok=True)
    workspace_log.write_text("# latest transcript\n", encoding="utf-8")

    conversation_log = tmp_path / "log_info" / "chat.jsonl"
    conversation_log.parent.mkdir(parents=True, exist_ok=True)
    conversation_log.write_text('{"message":"ok"}\n', encoding="utf-8")

    monkeypatch.setattr(log_service, "PROJECT_ROOT", tmp_path)

    roots_response = client.get("/api/logs/roots")
    tree_response = client.get("/api/logs/tree", params={"root": "workspace_logs"})
    content_response = client.get(
        "/api/logs/content",
        params={"root": "workspace_logs", "path": "turns/latest.md"},
    )

    assert roots_response.status_code == 200
    roots_payload = roots_response.json()
    assert [
        {"id": item["id"], "path": item["path"], "exists": item["exists"]}
        for item in roots_payload
    ] == [
        {"id": "runtime_scenes", "path": "logs/runtime_scenes", "exists": True},
        {"id": "runtime_logs", "path": "logs", "exists": True},
        {"id": "workspace_logs", "path": "workspace/logs", "exists": True},
        {"id": "conversation_logs", "path": "log_info", "exists": True},
    ]
    runtime_root = next(item for item in roots_payload if item["id"] == "runtime_logs")
    assert runtime_root["summary"]["fileCount"] == 1
    assert runtime_root["summary"]["latestPath"] == "agent_realtime.log"
    assert "后端" in runtime_root["summary"]["userGuide"]
    conversation_root = next(item for item in roots_payload if item["id"] == "conversation_logs")
    assert conversation_root["summary"]["fileCount"] == 1
    assert "conversation_" in conversation_root["summary"]["agentGuide"] or "debug_" in conversation_root["summary"]["agentGuide"]

    assert tree_response.status_code == 200
    tree_payload = tree_response.json()
    assert tree_payload["root"]["id"] == "workspace_logs"
    assert tree_payload["root"]["path"] == "workspace/logs"
    assert tree_payload["nodes"][0]["name"] == "turns"
    assert tree_payload["nodes"][0]["children"][0]["path"] == "turns/latest.md"

    assert content_response.status_code == 200
    content_payload = content_response.json()
    assert content_payload["path"] == "workspace/logs/turns/latest.md"
    assert content_payload["relativePath"] == "turns/latest.md"
    assert "# latest transcript" in content_payload["content"]
    assert content_payload["diagnostics"]["severity"] == "info"
    assert content_payload["diagnostics"]["lineCount"] == 1
    assert "正常路径" in content_payload["diagnostics"]["userSummary"]

    runtime_tree_response = client.get("/api/logs/tree", params={"root": "runtime_logs"})
    assert runtime_tree_response.status_code == 200
    runtime_tree_payload = runtime_tree_response.json()
    assert all(node["name"] != "runtime_scenes" for node in runtime_tree_payload["nodes"])


def test_log_content_returns_user_and_agent_diagnostics(tmp_path, monkeypatch):
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

    response = client.get(
        "/api/logs/content",
        params={"root": "conversation_logs", "path": "conversation_debug.jsonl"},
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
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


def test_log_content_rejects_path_escape(tmp_path, monkeypatch):
    (tmp_path / "logs").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(log_service, "PROJECT_ROOT", tmp_path)

    response = client.get(
        "/api/logs/content",
        params={"root": "runtime_logs", "path": "../log_info/chat.jsonl"},
    )

    assert response.status_code == 400
    assert "selected log root" in response.json()["detail"]


def test_clear_log_file_empties_content_but_keeps_file(tmp_path, monkeypatch):
    runtime_log = tmp_path / "logs" / "agent_realtime.log"
    runtime_log.parent.mkdir(parents=True, exist_ok=True)
    runtime_log.write_text("runtime line\nsecond line\n", encoding="utf-8")
    monkeypatch.setattr(log_service, "PROJECT_ROOT", tmp_path)

    response = client.post(
        "/api/logs/clear",
        json={"root": "runtime_logs", "path": "agent_realtime.log"},
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["relativePath"] == "agent_realtime.log"
    assert payload["content"] == ""
    assert payload["truncated"] is False
    assert runtime_log.exists()
    assert runtime_log.read_text(encoding="utf-8") == ""


def test_delete_logs_removes_selected_files_only(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "logs"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    keep_log = runtime_dir / "keep.log"
    delete_a = runtime_dir / "delete_a.log"
    delete_b = runtime_dir / "delete_b.log"
    keep_log.write_text("keep\n", encoding="utf-8")
    delete_a.write_text("a\n", encoding="utf-8")
    delete_b.write_text("b\n", encoding="utf-8")
    monkeypatch.setattr(log_service, "PROJECT_ROOT", tmp_path)

    response = client.post(
        "/api/logs/delete",
        json={
            "root": "runtime_logs",
            "paths": ["delete_a.log", "delete_b.log", "delete_a.log"],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["deletedCount"] == 2
    assert payload["deletedPaths"] == ["delete_a.log", "delete_b.log"]
    assert payload["missingPaths"] == []
    assert keep_log.exists()
    assert not delete_a.exists()
    assert not delete_b.exists()


def test_delete_logs_rejects_directory_targets(tmp_path, monkeypatch):
    turns_dir = tmp_path / "workspace" / "logs" / "turns"
    turns_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(log_service, "PROJECT_ROOT", tmp_path)

    response = client.post(
        "/api/logs/delete",
        json={"root": "workspace_logs", "paths": ["turns"]},
    )

    assert response.status_code == 400
    assert "Only log files can be deleted" in response.json()["detail"]


def test_runtime_scene_endpoints_list_detail_content_and_delete(tmp_path, monkeypatch):
    _seed_runtime_scene_bundle(tmp_path, scene_id="scene-a")
    _seed_runtime_scene_bundle(tmp_path, scene_id="scene-b")
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(log_service, "PROJECT_ROOT", tmp_path)

    list_response = client.get("/api/logs/runtime-scenes")
    assert list_response.status_code == 200
    scenes = list_response.json()
    assert {item["runtimeSceneId"] for item in scenes} == {"scene-a", "scene-b"}
    scene_a = next(item for item in scenes if item["runtimeSceneId"] == "scene-a")
    local_date, local_time, local_time_key = _runtime_scene_local_index_parts("2026-05-18T12:00:00Z")
    assert scene_a["displayName"] != "scene-a"
    assert scene_a["packageIndex"]["packageId"] == "scene-a"
    assert scene_a["packageIndex"]["displayName"] == scene_a["displayName"]
    assert scene_a["packageIndex"]["startedDate"] == local_date
    assert scene_a["packageIndex"]["startedTime"] == local_time
    assert scene_a["packageIndex"]["durationSeconds"] == 180
    assert scene_a["packageIndex"]["indexKey"] == f"{local_date}_{local_time_key}_workbench-start_manual-stop"
    assert "scene-a" in scene_a["packageIndex"]["searchText"]
    assert local_date in scene_a["packageIndex"]["searchText"]
    assert "workbench-lifecycle" in scene_a["packageIndex"]["tags"]
    assert "工作台启动" in scene_a["displayName"]
    assert "手动停止" in scene_a["displayName"]
    assert scenes[0]["eventCount"] >= 3
    assert scenes[0]["rawLogCount"] >= 5

    detail_response = client.get("/api/logs/runtime-scenes/scene-a")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["runtimeSceneId"] == "scene-a"
    assert detail["displayName"] == scene_a["displayName"]
    assert detail["packageIndex"] == scene_a["packageIndex"]
    assert detail["status"] == "stopped"
    assert detail["frontend"]["build_status"] == "success"
    assert detail["timeline"][0]["eventCode"] == "frontend.build.started"
    assert detail["timeline"][-1]["eventCode"] == "backend.health.succeeded"
    assert any(item["path"] == "raw/backend.stdout.log" for item in detail["rawFiles"])
    assert detail["packageSummary"]["schemaVersion"] == 2
    assert detail["packageSummary"]["lifecycleEventCount"] >= 3
    assert detail["lifecycle"][0]["eventCode"] == "backend.health.succeeded" or detail["lifecycle"][0]["eventCode"].startswith("frontend.")

    content_response = client.get(
        "/api/logs/runtime-scenes/scene-a/content",
        params={"path": "raw/backend.stdout.log"},
    )
    assert content_response.status_code == 200
    content_payload = content_response.json()
    assert content_payload["rootId"] == "runtime_scenes"
    assert content_payload["relativePath"] == "raw/backend.stdout.log"
    assert "uvicorn started" in content_payload["content"]
    assert content_payload["diagnostics"]["severity"] == "info"
    assert content_payload["diagnostics"]["agentHint"] == "runtime_scenes/scene-a/raw/backend.stdout.log; severity=info"

    delete_response = client.post(
        "/api/logs/runtime-scenes/delete",
        json={"sceneIds": ["scene-a"]},
    )
    assert delete_response.status_code == 200
    delete_payload = delete_response.json()
    assert delete_payload["deletedCount"] == 1
    assert delete_payload["deletedSceneIds"] == ["scene-a"]
    assert not (tmp_path / "logs" / "runtime_scenes" / "20260518T120000Z__scene-a").exists()
    assert (tmp_path / "logs" / "runtime_scenes" / "20260518T120000Z__scene-b").exists()


def test_runtime_scene_endpoints_read_timeline_package_without_legacy_events(tmp_path, monkeypatch):
    scene_dir = _seed_runtime_scene_bundle(tmp_path, scene_id="scene-package-only")
    shutil.rmtree(scene_dir / "events")
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)

    list_response = client.get("/api/logs/runtime-scenes")
    assert list_response.status_code == 200
    [summary] = list_response.json()
    local_date, _, local_time_key = _runtime_scene_local_index_parts("2026-05-18T12:00:00Z")
    assert summary["runtimeSceneId"] == "scene-package-only"
    assert summary["eventCount"] >= 3
    assert summary["packageIndex"]["startedDate"] == local_date
    assert summary["packageIndex"]["indexKey"] == f"{local_date}_{local_time_key}_workbench-start_manual-stop"

    detail_response = client.get("/api/logs/runtime-scenes/scene-package-only")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["timeline"][0]["eventCode"] == "frontend.build.started"
    assert detail["timeline"][-1]["eventCode"] == "backend.health.succeeded"
    assert detail["packageSummary"]["eventCount"] >= 3
    assert detail["packageSummary"]["lifecycleEventCount"] >= 3
    assert "scene-package-only" in detail["packageIndex"]["searchText"]


def test_runtime_scene_package_records_conversation_as_child_log(tmp_path, monkeypatch):
    scene_dir = _seed_runtime_scene_bundle(tmp_path, scene_id="scene-chat", status="running")
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text(
        json.dumps(
            {
                "runtimeSceneId": "scene-chat",
                "runtimeSceneDir": str(scene_dir),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "LAUNCHER_STATE_PATH", launcher_state_path)

    payload = runtime_scene_service.record_runtime_scene_conversation_event(
        "session-demo",
        "user",
        "帮我分析这个周期日志",
        event="user_message",
        status="running",
        tool_calls=[{"name": "inspect_logs", "status": "done", "summary": "read package"}],
    )

    assert payload["accepted"] is True
    conversation_log = scene_dir / "conversations" / "session-demo.jsonl"
    assert conversation_log.exists()
    assert "帮我分析这个周期日志" in conversation_log.read_text(encoding="utf-8")
    assert (scene_dir / "agent" / "turns.jsonl").exists()
    assert (scene_dir / "agent" / "tool_calls.jsonl").exists()
    timeline_text = (scene_dir / "timeline.jsonl").read_text(encoding="utf-8")
    assert "conversation.user_message" in timeline_text

    detail_response = client.get("/api/logs/runtime-scenes/scene-chat")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    local_date, _, local_time_key = _runtime_scene_local_index_parts("2026-05-18T12:00:00Z")
    assert detail["packageIndex"]["indexKey"] == f"{local_date}_{local_time_key}_workbench-start_running"
    assert detail["packageIndex"]["durationSeconds"] is None
    assert detail["packageSummary"]["conversationLogCount"] == 1
    assert detail["packageSummary"]["agentLogCount"] == 2
    assert detail["timeline"][-1]["eventCode"] == "conversation.user_message"
    assert detail["timeline"][-1]["rawRefs"] == [{"path": "conversations/session-demo.jsonl", "tail_lines": 80}]
    assert detail["conversationLogs"][0]["path"] == "conversations/session-demo.jsonl"


def test_runtime_browser_telemetry_records_into_active_scene(tmp_path, monkeypatch):
    scene_dir = _seed_runtime_scene_bundle(tmp_path, scene_id="scene-live", status="running")
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text(
        json.dumps(
            {
                "runtimeSceneId": "scene-live",
                "runtimeSceneDir": str(scene_dir),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "LAUNCHER_STATE_PATH", launcher_state_path)

    response = client.post(
        "/api/runtime/browser-telemetry",
        json={
            "phase": "navigation",
            "eventCode": "browser.route.changed",
            "message": "React route changed to /chat",
            "level": "info",
            "fields": {
                "pathname": "/chat",
                "href": "http://127.0.0.1:8000/chat",
                "title": "Chat",
                "activeNavHref": "/self-evolution",
                "heading": "Self evolution",
            },
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["accepted"] is True
    assert payload["runtimeSceneId"] == "scene-live"

    telemetry_raw = (scene_dir / "raw" / "browser.telemetry.log").read_text(encoding="utf-8")
    assert "browser.route.changed" in telemetry_raw
    assert "/chat" in telemetry_raw

    telemetry_events = (scene_dir / "events" / "browser_page.jsonl").read_text(encoding="utf-8")
    assert "browser.route.changed" in telemetry_events
    assert "\"activeNavHref\":\"/self-evolution\"" in telemetry_events

    manifest = json.loads((scene_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["browser"]["telemetry_path"] == "raw/browser.telemetry.log"
    assert manifest["browser"]["current_pathname"] == "/chat"
    assert manifest["browser"]["active_nav_href"] == "/self-evolution"
    assert manifest["browser"]["current_heading"] == "Self evolution"


def test_backend_api_runtime_event_records_mutating_request(tmp_path, monkeypatch):
    scene_dir = _seed_runtime_scene_bundle(tmp_path, scene_id="scene-api", status="running")
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text(
        json.dumps(
            {
                "runtimeSceneId": "scene-api",
                "runtimeSceneDir": str(scene_dir),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "LAUNCHER_STATE_PATH", launcher_state_path)
    monkeypatch.setattr(runtime_service, "_schedule_local_backend_exit", lambda delay_seconds=0.35: None)
    monkeypatch.setattr(runtime_service, "LAUNCHER_SCRIPT_PATH", tmp_path / "missing-launcher.ps1")
    monkeypatch.setattr(runtime_service, "LAUNCHER_STATE_PATH", tmp_path / "missing-state.json")

    response = client.post("/api/runtime/shutdown")

    assert response.status_code == 202
    backend_raw = (scene_dir / "raw" / "backend.api.log").read_text(encoding="utf-8")
    assert "backend.api.request" in backend_raw
    assert "/api/runtime/shutdown" in backend_raw

    backend_events = [
        json.loads(line)
        for line in (scene_dir / "events" / "backend.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    api_event = backend_events[-1]
    assert api_event["phase"] == "api"
    assert api_event["event_code"] == "backend.api.request"
    assert api_event["fields"]["method"] == "POST"
    assert api_event["fields"]["pathTemplate"] == "/api/runtime/shutdown"
    assert api_event["fields"]["statusCode"] == 202
    assert api_event["raw_refs"] == [{"path": "raw/backend.api.log", "tail_lines": 80}]

    manifest = json.loads((scene_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["backend"]["api_log_path"] == "raw/backend.api.log"
    assert manifest["backend"]["last_api_path"] == "/api/runtime/shutdown"


def test_backend_api_runtime_event_skips_health_noise(tmp_path, monkeypatch):
    scene_dir = _seed_runtime_scene_bundle(tmp_path, scene_id="scene-health", status="running")
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text(
        json.dumps(
            {
                "runtimeSceneId": "scene-health",
                "runtimeSceneDir": str(scene_dir),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "LAUNCHER_STATE_PATH", launcher_state_path)

    response = client.get("/api/health")

    assert response.status_code == 200
    assert not (scene_dir / "raw" / "backend.api.log").exists()


def test_runtime_logs_reject_runtime_scene_path_operations(tmp_path, monkeypatch):
    _seed_runtime_scene_bundle(tmp_path, scene_id="scene-guard")
    monkeypatch.setattr(log_service, "PROJECT_ROOT", tmp_path)

    response = client.post(
        "/api/logs/delete",
        json={"root": "runtime_logs", "paths": ["runtime_scenes/20260518T120000Z__scene-guard/manifest.json"]},
    )

    assert response.status_code == 400
    assert "runtime scenes surface" in response.json()["detail"].lower()


def test_runtime_scene_delete_rejects_running_bundle(tmp_path, monkeypatch):
    _seed_runtime_scene_bundle(tmp_path, scene_id="scene-live", status="running")
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)

    response = client.post(
        "/api/logs/runtime-scenes/delete",
        json={"sceneIds": ["scene-live"]},
    )

    assert response.status_code == 400
    assert "still running" in response.json()["detail"]


def test_missing_static_asset_returns_404_instead_of_index(tmp_path, monkeypatch):
    dist_dir = tmp_path / "web-dist"
    assets_dir = dist_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    (dist_dir / "index.html").write_text("<!doctype html><html><body>app</body></html>", encoding="utf-8")

    monkeypatch.setattr("core.web.app.WEB_DIST", dist_dir)
    temp_client = TestClient(create_app())

    response = temp_client.get("/assets/FilePreview-missing.js")

    assert response.status_code == 404
    assert response.json()["detail"] == "Not Found"


def test_spa_route_still_falls_back_to_index_html(tmp_path, monkeypatch):
    dist_dir = tmp_path / "web-dist"
    dist_dir.mkdir(parents=True, exist_ok=True)
    index_html = "<!doctype html><html><body>app shell</body></html>"
    (dist_dir / "index.html").write_text(index_html, encoding="utf-8")

    monkeypatch.setattr("core.web.app.WEB_DIST", dist_dir)
    temp_client = TestClient(create_app())

    response = temp_client.get("/logs")

    assert response.status_code == 200
    assert "app shell" in response.text


def _seed_chat_state(project_root, *, task_status="reading", active_task=None):
    save_chat_state(
        project_root,
        {
            "version": 1,
            "active_conversation_id": "session-live",
            "updated_at": "2026-05-18T12:00:00",
            "conversations": [
                {
                    "conversation_id": "session-live",
                    "title": "真实会话",
                    "updated_at": "2026-05-18T12:00:00",
                    "last_turn_status": "failed" if task_status == "failed" else "ready",
                    "active_task": active_task,
                    "messages": [
                        {
                            "role": "user",
                            "content": "继续前端开发",
                            "timestamp": "2026-05-18T11:55:00",
                        },
                        {
                            "role": "assistant",
                            "content": "<think>internal</think>\n\n已经接到真实状态了。",
                            "timestamp": "2026-05-18T11:56:00",
                            "tool_calls": [
                                {"name": "read_file_tool"},
                                {"function": {"name": "search_code_tool"}},
                            ],
                        },
                    ],
                }
            ],
        },
    )


def test_session_detail_exists(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    sessions_response = client.get("/api/sessions")
    assert sessions_response.status_code == 200
    sessions = sessions_response.json()
    assert sessions
    assert sessions[0]["id"] == "session-live"

    response = client.get("/api/sessions/session-live")
    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "session-live"
    assert payload["messages"]
    assert payload["messages"][1]["content"] == "已经接到真实状态了。"
    assert payload["messages"][1]["thought"] == "internal"
    assert payload["messages"][1]["toolCalls"] == [
        {"name": "read_file_tool", "status": "done"},
        {"name": "search_code_tool", "status": "done"},
    ]
    assert payload["taskSummary"] == "已经接到真实状态了。"
    assert payload["previewTabs"] == []
    assert payload["currentPhase"] == "ready"


def test_create_session_persists_new_active_empty_conversation(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.post("/api/sessions")

    assert response.status_code == 201
    payload = response.json()
    assert payload["id"].startswith("session-")
    assert payload["title"] == "新会话"
    assert payload["messages"] == []
    assert payload["currentPhase"] == "ready"

    state = load_chat_state(tmp_path)
    assert state["active_conversation_id"] == payload["id"]
    assert [item["conversation_id"] for item in state["conversations"]] == [
        "session-live",
        payload["id"],
    ]


def test_update_session_title_persists_to_list_and_detail(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.patch(
        "/api/sessions/session-live",
        json={"title": "重命名后的会话"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "session-live"
    assert payload["title"] == "重命名后的会话"

    sessions_response = client.get("/api/sessions")
    assert sessions_response.status_code == 200
    assert sessions_response.json()[0]["title"] == "重命名后的会话"

    state = load_chat_state(tmp_path)
    assert state["conversations"][0]["title"] == "重命名后的会话"


def test_update_session_title_rejects_empty_title(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.patch(
        "/api/sessions/session-live",
        json={"title": "   "},
    )

    assert response.status_code == 422
    assert "名称" in response.json()["detail"]
    state = load_chat_state(tmp_path)
    assert state["conversations"][0]["title"] == "真实会话"


def test_delete_session_switches_to_latest_remaining_session(tmp_path, monkeypatch):
    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "active_conversation_id": "session-live",
            "updated_at": "2026-05-18T12:00:00",
            "conversations": [
                {
                    "conversation_id": "session-live",
                    "title": "当前会话",
                    "updated_at": "2026-05-18T12:00:00",
                    "last_turn_status": "ready",
                    "messages": [{"role": "user", "content": "删除我", "timestamp": "2026-05-18T12:00:00"}],
                },
                {
                    "conversation_id": "session-older",
                    "title": "旧会话",
                    "updated_at": "2026-05-18T10:00:00",
                    "last_turn_status": "ready",
                    "messages": [{"role": "user", "content": "旧", "timestamp": "2026-05-18T10:00:00"}],
                },
                {
                    "conversation_id": "session-newer",
                    "title": "新会话",
                    "updated_at": "2026-05-18T11:00:00",
                    "last_turn_status": "ready",
                    "messages": [{"role": "user", "content": "新", "timestamp": "2026-05-18T11:00:00"}],
                },
            ],
        },
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.delete("/api/sessions/session-live")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "session-newer"

    state = load_chat_state(tmp_path)
    assert state["active_conversation_id"] == "session-newer"
    assert [item["conversation_id"] for item in state["conversations"]] == [
        "session-older",
        "session-newer",
    ]


def test_delete_last_session_creates_replacement(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.delete("/api/sessions/session-live")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"].startswith("session-")
    assert payload["id"] != "session-live"
    assert payload["messages"] == []

    state = load_chat_state(tmp_path)
    assert state["active_conversation_id"] == payload["id"]
    assert [item["conversation_id"] for item in state["conversations"]] == [payload["id"]]


def test_delete_session_rejects_running_turn(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    session_service._set_session_running("session-live", True)
    try:
        response = client.delete("/api/sessions/session-live")
    finally:
        session_service._set_session_running("session-live", False)

    assert response.status_code == 409
    assert "运行" in response.json()["detail"]
    state = load_chat_state(tmp_path)
    assert [item["conversation_id"] for item in state["conversations"]] == ["session-live"]


def test_session_detail_uses_live_phase_while_turn_is_running(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    session_service._set_session_running("session-live", True)
    try:
        response = client.get("/api/sessions/session-live")
    finally:
        session_service._set_session_running("session-live", False)

    assert response.status_code == 200
    payload = response.json()
    assert payload["currentPhase"] == "running"


def test_session_detail_hydrates_file_context_from_saved_active_task(tmp_path, monkeypatch):
    (tmp_path / "web" / "src" / "routes").mkdir(parents=True, exist_ok=True)
    (tmp_path / "core" / "web" / "services").mkdir(parents=True, exist_ok=True)
    (tmp_path / "web" / "src" / "routes" / "ChatCodingRoute.tsx").write_text("export {};\n", encoding="utf-8")
    (tmp_path / "core" / "web" / "services" / "session_service.py").write_text("pass\n", encoding="utf-8")
    _seed_chat_state(
        tmp_path,
        active_task={
            "task_id": "session-live-coding-task",
            "kind": "coding",
            "status": "done",
            "title": "修复会话页面文件上下文",
            "read_files": ["web/src/routes/ChatCodingRoute.tsx"],
            "changed_files": ["core/web/services/session_service.py"],
            "verification_status": "passed",
            "verification_summary": "2 passed in 0.31s",
            "default_file_context": "core/web/services/session_service.py",
        },
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.get("/api/sessions/session-live")

    assert response.status_code == 200
    payload = response.json()
    assert payload["readFiles"] == ["web/src/routes/ChatCodingRoute.tsx"]
    assert payload["changedFiles"] == ["core/web/services/session_service.py"]
    assert payload["defaultFileContext"] == "core/web/services/session_service.py"
    assert payload["previewTabs"] == [
        "core/web/services/session_service.py",
        "web/src/routes/ChatCodingRoute.tsx",
    ]
    assert payload["activePreviewPath"] == "core/web/services/session_service.py"


def test_session_events_stream_initial_detail(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    detail = session_service.get_session_detail("session-live")
    assert detail is not None

    stream = session_service.stream_session_events("session-live", initial_detail=detail)
    raw_event = next(stream)
    stream.close()

    class _SingleEventResponse:
        def iter_lines(self):
            for line in str(raw_event).splitlines():
                yield line
            yield ""

    event = _read_first_sse_event(_SingleEventResponse())

    assert event["event"] == "session_detail"
    payload = json.loads(event["data"])
    assert payload["type"] == "session_detail"
    assert payload["sessionId"] == "session-live"
    assert payload["detail"]["id"] == "session-live"
    assert payload["detail"]["messages"][1]["content"] == "已经接到真实状态了。"


def test_session_events_stream_rejects_missing_session():
    response = client.get("/api/sessions/missing-session/events")
    assert response.status_code == 404
    assert response.json()["detail"] == "Session not found"


def test_submit_session_message_runs_turn_and_persists_reply(tmp_path, monkeypatch):
    (tmp_path / "web" / "src" / "routes").mkdir(parents=True, exist_ok=True)
    (tmp_path / "core" / "web" / "services").mkdir(parents=True, exist_ok=True)
    (tmp_path / "web" / "src" / "routes" / "ChatCodingRoute.tsx").write_text("export {};\n", encoding="utf-8")
    (tmp_path / "core" / "web" / "services" / "session_service.py").write_text("pass\n", encoding="utf-8")
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    class DummyAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            assert "ChatCodingRoute.tsx" in initial_prompt
            return {
                "status": "completed",
                "summary": "已完成网页对话提交接线。",
                "raw_output": "已完成网页对话提交接线。",
                "reasoning_content": "先确认消息模型，再把思考与心智快照一起落盘。",
                "mental_snapshot": {
                    "mood": "专注",
                    "feeling": "主链路已经清楚了。",
                    "whisper": "把思考和回答放在同一张卡片里。",
                    "summary": "主链路已经清楚了。",
                    "cognitiveState": "productive",
                    "confidence": 0.86,
                    "sampleSize": 4,
                    "interventionCount": 1,
                    "updatedAt": "2026-05-18T12:01:00",
                    "source": "state",
                },
                "outcome": "done",
                "read_files": ["web/src/routes/ChatCodingRoute.tsx"],
                "changed_files": ["core/web/services/session_service.py"],
                "verification_status": "passed",
                "verification_summary": "2 passed in 0.31s",
                "tool_call_count": 2,
                "tool_trace": [
                    {"name": "read_file_tool"},
                    {"function": {"name": "apply_patch_tool"}},
                ],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: DummyAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "请继续修复 web/src/routes/ChatCodingRoute.tsx 并验证"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["messages"][-2]["role"] == "user"
    assert payload["messages"][-2]["content"] == "请继续修复 web/src/routes/ChatCodingRoute.tsx 并验证"
    assert payload["messages"][-1]["role"] == "assistant"
    assert payload["messages"][-1]["content"] == "已完成网页对话提交接线。"
    assert payload["messages"][-1]["thought"] == "先确认消息模型，再把思考与心智快照一起落盘。"
    assert payload["messages"][-1]["mentalSnapshot"]["mood"] == "专注"
    assert payload["messages"][-1]["mentalSnapshot"]["cognitiveState"] == "productive"
    assert payload["messages"][-1]["toolCalls"] == [
        {"name": "read_file_tool", "status": "done"},
        {"name": "apply_patch_tool", "status": "done"},
    ]
    assert payload["taskSummary"] == "已完成网页对话提交接线。"
    assert payload["currentPhase"] == "ready"
    assert payload["readFiles"] == ["web/src/routes/ChatCodingRoute.tsx"]
    assert payload["changedFiles"] == ["core/web/services/session_service.py"]
    assert payload["defaultFileContext"] == "core/web/services/session_service.py"
    assert payload["previewTabs"] == [
        "core/web/services/session_service.py",
        "web/src/routes/ChatCodingRoute.tsx",
    ]
    assert payload["activePreviewPath"] == "core/web/services/session_service.py"
    assert "activeTask" not in payload


def test_chat_turn_registers_as_work_run_until_finished(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "解释当前状态"},
    )

    assert response.status_code == 202
    running_summary = runtime_service.get_runtime_summary()
    active_chat = running_summary["workRuns"]["active"]["chat_turn"]
    assert active_chat["runKind"] == "chat_turn"
    assert active_chat["status"] == "running"
    assert active_chat["sessionId"] == "session-live"
    assert active_chat["leases"] == ["readonly_chat"]

    turn_id = active_chat["runId"]
    session_service._persist_session_turn_result(
        "session-live",
        {
            "status": "completed",
            "summary": "已解释当前状态。",
            "raw_output": "已解释当前状态。",
            "outcome": "done",
            "tool_call_count": 0,
            "tool_trace": [],
        },
        turn_id=turn_id,
    )
    session_service._set_session_running("session-live", False, turn_id=turn_id)

    finished_summary = runtime_service.get_runtime_summary()
    assert finished_summary["workRuns"]["active"]["chat_turn"] is None
    latest_chat = finished_summary["workRuns"]["latest"]["chat_turn"]
    assert latest_chat["runId"] == turn_id
    assert latest_chat["status"] == "completed"


def test_runtime_summary_exposes_three_work_run_kinds(monkeypatch):
    monkeypatch.setattr(runtime_service, "get_active_session_detail", lambda: {})
    monkeypatch.setattr(runtime_service, "_load_runtime_state", lambda: {})
    self_evolution_control_service.persist_manager_run_snapshot(
        "self",
        {
            "runId": "self-work-run",
            "status": "running",
            "startedAt": "2026-05-21T00:00:00",
            "updatedAt": "2026-05-21T00:00:00",
        },
        active_run_id="self-work-run",
    )
    supervised_control_service.persist_manager_run_snapshot(
        "supervised",
        {
            "runId": "supervised-work-run",
            "status": "done",
            "startedAt": "2026-05-21T00:00:00",
            "updatedAt": "2026-05-21T00:01:00",
        },
        active_run_id="",
    )

    payload = runtime_service.get_runtime_summary()

    assert set(payload["workRuns"]["active"]) == {
        "chat_turn",
        "self_evolution_run",
        "supervised_evolution_run",
    }
    assert payload["workRuns"]["active"]["self_evolution_run"]["runKind"] == "self_evolution_run"
    assert payload["workRuns"]["active"]["self_evolution_run"]["leases"] == [
        "evolution_transaction",
        "worktree_write",
        "memory_write",
    ]
    assert payload["workRuns"]["latest"]["supervised_evolution_run"]["runKind"] == "supervised_evolution_run"
    assert payload["workRuns"]["latest"]["supervised_evolution_run"]["leases"] == ["evaluation"]


def test_submit_session_message_captures_chat_review_candidate(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_review_service, "PROJECT_ROOT", tmp_path)

    class DummyAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "completed",
                "summary": "结论：已经定位到网页聊天提交流程。下一步我会把采样和审核接上。",
                "raw_output": "结论：已经定位到网页聊天提交流程。下一步我会把采样和审核接上。",
                "tool_call_count": 2,
                "tool_trace": [
                    {"name": "read_file_tool"},
                    {"function": {"name": "apply_patch_tool"}},
                ],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: DummyAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续把网页聊天里的 case 抽出来给监督进化用"},
    )

    assert response.status_code == 202
    queue_response = client.get("/api/evolution/chat-review")
    assert queue_response.status_code == 200
    payload = queue_response.json()
    assert payload["pendingCount"] == 1
    assert payload["items"][0]["sessionId"] == "session-live"
    assert payload["items"][0]["qualitySignals"]


def test_submit_session_message_rejects_busy_session(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    session_service._set_session_running("session-live", True)
    try:
        response = client.post(
            "/api/sessions/session-live/messages",
            json={"content": "继续修复 web/src/routes/ChatCodingRoute.tsx"},
        )
    finally:
        session_service._set_session_running("session-live", False)

    assert response.status_code == 409
    assert "运行" in response.json()["detail"] or "running" in response.json()["detail"].lower()


def test_submit_session_message_write_intent_rejects_self_evolution_lease(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)
    self_snapshot = {
        "runId": "web-self-active-for-chat",
        "runKind": "self_evolution_run",
        "status": "running",
        "leases": ["evolution_transaction", "worktree_write", "memory_write"],
        "startedAt": "2026-05-21T00:00:00",
        "updatedAt": "2026-05-21T00:00:00",
    }
    self_evolution_control_service.persist_manager_run_snapshot("self", self_snapshot, active_run_id=self_snapshot["runId"])

    readonly = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "解释当前状态"},
    )

    assert readonly.status_code == 202
    session_service._set_session_running("session-live", False)
    session_service._clear_session_turn_control("session-live")

    write_response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续修复这个 bug", "writeIntent": True},
    )

    assert write_response.status_code == 409
    assert "resource" in write_response.json()["detail"].lower() or "资源" in write_response.json()["detail"]


def test_request_stop_session_turn_persists_stop_snapshot_and_releases_session(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)

    try:
        submit_response = client.post(
            "/api/sessions/session-live/messages",
            json={"content": "先继续分析当前对话提交流程"},
        )

        assert submit_response.status_code == 202
        running_payload = submit_response.json()
        assert running_payload["currentPhase"] == "running"
        assert running_payload["stopRequested"] is False

        stop_response = client.post("/api/sessions/session-live/stop")

        assert stop_response.status_code == 202
        payload = stop_response.json()
        assert payload["currentPhase"] == "ready"
        assert payload["stopRequested"] is False
        assert payload["messages"][-1]["role"] == "assistant"
        assert "本轮已按请求停止" in payload["messages"][-1]["content"]

        continue_response = client.post(
            "/api/sessions/session-live/messages",
            json={"content": "继续"},
        )
        assert continue_response.status_code == 202
        assert continue_response.json()["currentPhase"] == "running"
    finally:
        session_service._set_session_running("session-live", False)
        session_service._clear_session_turn_control("session-live")


def test_stop_requested_turn_persists_visible_stop_message(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    started = threading.Event()
    finished = threading.Event()
    worker_threads = []

    class StoppableAgent:
        def __init__(self):
            self.stop_checker = None

        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def set_turn_interrupt_checker(self, checker):
            self.stop_checker = checker

        def run_single_turn(self, initial_prompt=None):
            started.set()
            for _ in range(200):
                reason = self.stop_checker() if callable(self.stop_checker) else ""
                if reason:
                    return {
                        "status": "stopped",
                        "summary": "",
                        "raw_output": "",
                        "stop_requested": True,
                        "stop_reason": reason,
                        "tool_call_count": 0,
                        "tool_trace": [],
                    }
                time.sleep(0.01)
            return {
                "status": "completed",
                "summary": "不该走到这里。",
                "raw_output": "不该走到这里。",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: StoppableAgent())

    def run_async(context):
        def _worker():
            try:
                session_service._run_session_turn(context)
            finally:
                finished.set()

        thread = threading.Thread(target=_worker, daemon=True)
        worker_threads.append(thread)
        thread.start()

    monkeypatch.setattr(session_service, "_schedule_session_turn", run_async)

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续推进当前网页会话的终止能力"},
    )

    assert response.status_code == 202
    assert started.wait(1.0), "expected the background turn to start"

    stop_response = client.post("/api/sessions/session-live/stop")

    assert stop_response.status_code == 202
    assert stop_response.json()["currentPhase"] == "ready"
    assert finished.wait(2.0), "expected the stopped turn to finish"

    for thread in worker_threads:
        thread.join(timeout=0.2)

    detail_response = client.get("/api/sessions/session-live")
    assert detail_response.status_code == 200
    payload = detail_response.json()
    assert payload["currentPhase"] == "ready"
    assert payload["stopRequested"] is False
    assert payload["messages"][-1]["role"] == "assistant"
    assert "本轮已按请求停止" in payload["messages"][-1]["content"]


def test_stop_session_turn_persists_partial_snapshot_and_allows_immediate_continue(tmp_path, monkeypatch):
    _seed_chat_state(
        tmp_path,
        task_status="reading",
        active_task={
            "task_id": "chat-stop-resume",
            "kind": "coding",
            "status": "reading",
            "title": "修复 Web Chat 停止恢复",
            "goal": "修复 Web Chat 停止恢复",
            "read_files": ["tests/prompt_debugger.py"],
            "latest_summary": "已定位停止按钮问题。",
            "updated_at": "2026-05-20T16:24:53",
        },
    )
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "prompt_debugger.py").write_text("pass\n", encoding="utf-8")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)

    submit_response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续修复停止恢复"},
    )
    assert submit_response.status_code == 202
    old_control = session_service._get_session_turn_control("session-live")
    assert old_control is not None

    session_service._set_session_live_output(
        "session-live",
        thought="我已经定位到 stop checker。",
        content="已完成一部分：停止请求进入后会设置 stop flag。",
        tool_calls=[{"name": "read_file_tool", "status": "done", "summary": "session_service.py"}],
    )

    stop_response = client.post("/api/sessions/session-live/stop")
    assert stop_response.status_code == 202
    stopped_payload = stop_response.json()
    assert stopped_payload["currentPhase"] == "ready"
    assert stopped_payload["stopRequested"] is False
    assert "已完成一部分" in stopped_payload["messages"][-1]["content"]
    assert "本轮已按请求停止" in stopped_payload["messages"][-1]["content"]
    assert stopped_payload["messages"][-1]["thought"] == "我已经定位到 stop checker。"
    assert stopped_payload["messages"][-1]["toolCalls"][0]["name"] == "read_file_tool"

    continue_response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续"},
    )
    assert continue_response.status_code == 202
    new_control = session_service._get_session_turn_control("session-live")
    assert new_control is not None
    assert new_control.turn_id != old_control.turn_id

    session_service._clear_session_turn_control("session-live", turn_id=old_control.turn_id)
    assert session_service._get_session_turn_control("session-live").turn_id == new_control.turn_id

    session_service._set_session_running("session-live", False, turn_id=old_control.turn_id)
    assert session_service._is_session_running("session-live") is True

    session_service._set_session_running("session-live", False, turn_id=new_control.turn_id)
    session_service._clear_session_turn_control("session-live", turn_id=new_control.turn_id)


def test_stale_stopped_turn_does_not_run_after_immediate_continue(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    scheduled_contexts = []
    stale_agent_called = False

    class StaleAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def set_turn_interrupt_checker(self, checker):
            self.stop_checker = checker

        def run_single_turn(self, initial_prompt=None):
            nonlocal stale_agent_called
            stale_agent_called = True
            return {
                "status": "completed",
                "summary": "旧轮结果不应该写入当前会话。",
                "raw_output": "旧轮结果不应该写入当前会话。",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: scheduled_contexts.append(dict(context)))
    monkeypatch.setattr(session_service, "create_chat_agent", lambda: StaleAgent())

    try:
        first_response = client.post(
            "/api/sessions/session-live/messages",
            json={"content": "第一轮需要停止"},
        )
        assert first_response.status_code == 202
        assert len(scheduled_contexts) == 1

        stop_response = client.post("/api/sessions/session-live/stop")
        assert stop_response.status_code == 202

        continue_response = client.post(
            "/api/sessions/session-live/messages",
            json={"content": "第二轮已经开始"},
        )
        assert continue_response.status_code == 202
        assert continue_response.json()["currentPhase"] == "running"
        assert len(scheduled_contexts) == 2

        session_service._run_session_turn(scheduled_contexts[0])

        detail_response = client.get("/api/sessions/session-live")
        assert detail_response.status_code == 200
        payload = detail_response.json()
        assert stale_agent_called is False
        assert payload["currentPhase"] == "running"
        assert payload["messages"][-1]["role"] == "user"
        assert payload["messages"][-1]["content"] == "第二轮已经开始"
    finally:
        session_service._set_session_running("session-live", False)
        session_service._clear_session_turn_control("session-live")
        session_service._clear_session_live_output("session-live")


def test_stale_turn_live_output_does_not_overwrite_new_turn(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)

    try:
        first_response = client.post(
            "/api/sessions/session-live/messages",
            json={"content": "第一轮需要停止"},
        )
        assert first_response.status_code == 202
        old_control = session_service._get_session_turn_control("session-live")
        assert old_control is not None

        stop_response = client.post("/api/sessions/session-live/stop")
        assert stop_response.status_code == 202

        continue_response = client.post(
            "/api/sessions/session-live/messages",
            json={"content": "第二轮已经开始"},
        )
        assert continue_response.status_code == 202
        new_control = session_service._get_session_turn_control("session-live")
        assert new_control is not None

        session_service._set_session_live_output(
            "session-live",
            turn_id=new_control.turn_id,
            content="新轮正在输出。",
        )
        session_service._set_session_live_output(
            "session-live",
            turn_id=old_control.turn_id,
            content="旧轮迟到输出，不应该可见。",
        )

        detail_response = client.get("/api/sessions/session-live")
        assert detail_response.status_code == 200
        payload = detail_response.json()
        assert payload["messages"][-1]["streaming"] is True
        assert payload["messages"][-1]["content"] == "新轮正在输出。"
    finally:
        session_service._set_session_running("session-live", False)
        session_service._clear_session_turn_control("session-live")
        session_service._clear_session_live_output("session-live")


def test_session_detail_includes_live_thought_draft(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    session_service._set_session_running("session-live", True)
    session_service._set_session_live_output(
        "session-live",
        thought="先把这轮的思考过程挂进消息卡片。",
        mental_snapshot={
            "mood": "专注",
            "feeling": "链路已经接近打通。",
            "whisper": "再把默认折叠状态接上。",
            "cognitiveState": "productive",
        },
    )
    try:
        response = client.get("/api/sessions/session-live")
    finally:
        session_service._clear_session_live_output("session-live")
        session_service._set_session_running("session-live", False)

    assert response.status_code == 200
    payload = response.json()
    assert payload["messages"][-1]["streaming"] is True
    assert payload["messages"][-1]["thought"] == "先把这轮的思考过程挂进消息卡片。"
    assert payload["messages"][-1]["mentalSnapshot"]["mood"] == "专注"


def test_session_detail_hides_partial_state_live_answer(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    session_service._set_session_running("session-live", True)
    session_service._set_session_live_output(
        "session-live",
        content="<state",
        tool_calls=[{"name": "read_file_tool", "status": "running"}],
    )
    try:
        response = client.get("/api/sessions/session-live")
    finally:
        session_service._clear_session_live_output("session-live")
        session_service._set_session_running("session-live", False)

    assert response.status_code == 200
    payload = response.json()
    assert payload["messages"][-1]["streaming"] is True
    assert payload["messages"][-1]["content"] == ""
    assert payload["messages"][-1]["toolCalls"] == [
        {"name": "read_file_tool", "status": "running"}
    ]


def test_session_detail_hides_dsml_and_lone_angle_live_answer(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    session_service._set_session_running("session-live", True)
    session_service._set_session_live_output(
        "session-live",
        content="<state>\n{}\n</｜｜DSML｜｜parameter>\n</invoke>\n</｜｜DSML｜｜tool_calls>\n<",
        thought="</invoke>\n<",
        tool_calls=[{"name": "spawn_agent_tool", "status": "running"}],
    )
    try:
        response = client.get("/api/sessions/session-live")
    finally:
        session_service._clear_session_live_output("session-live")
        session_service._set_session_running("session-live", False)

    assert response.status_code == 200
    payload = response.json()
    assert payload["messages"][-1]["streaming"] is True
    assert payload["messages"][-1]["content"] == ""
    assert "thought" not in payload["messages"][-1]
    assert payload["messages"][-1]["toolCalls"] == [
        {"name": "spawn_agent_tool", "status": "running"}
    ]


def test_session_detail_hides_parameter_live_answer(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    session_service._set_session_running("session-live", True)
    session_service._set_session_live_output(
        "session-live",
        content="连续被拦截。让我尝试拆分写入。\n</parameter>",
        thought="</parameter>\n<parameter",
        tool_calls=[{"name": "cli_tool", "status": "running"}],
    )
    try:
        response = client.get("/api/sessions/session-live")
    finally:
        session_service._clear_session_live_output("session-live")
        session_service._set_session_running("session-live", False)

    assert response.status_code == 200
    payload = response.json()
    assert payload["messages"][-1]["streaming"] is True
    assert payload["messages"][-1]["content"] == "连续被拦截。让我尝试拆分写入。"
    assert "thought" not in payload["messages"][-1]
    assert payload["messages"][-1]["toolCalls"] == [
        {"name": "cli_tool", "status": "running"}
    ]


def test_session_detail_sanitizes_persisted_protocol_messages_and_active_task(tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "prompt_debugger.py").write_text("pass\n", encoding="utf-8")
    _seed_chat_state(
        tmp_path,
        task_status="reading",
        active_task={
            "task_id": "polluted-protocol",
            "kind": "coding",
            "status": "reading",
            "title": "<invoke name=\"read_file_tool\"><parameter name=\"file_path\">secret.py</parameter></invoke>",
            "goal": "<state",
            "read_files": ["tests/prompt_debugger.py"],
            "latest_summary": "继续检查。\n</parameter>",
            "next_action": "<parameter name=\"file_path\">secret.py</parameter>",
            "updated_at": "2026-05-20T17:54:06",
        },
    )
    state = load_chat_state(tmp_path)
    state["conversations"][0]["messages"].append(
        {
            "role": "assistant",
            "content": (
                "继续检查。\n"
                '<invoke name="read_file_tool">'
                '<parameter name="file_path">tests/prompt_debugger.py</parameter>'
                "</invoke>\n"
                "<state"
            ),
            "thought": "</parameter>\n<parameter",
            "timestamp": "2026-05-20T17:55:00",
            "tool_calls": [{"name": "read_file_tool"}],
        }
    )
    save_chat_state(tmp_path, state)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.get("/api/sessions/session-live")

    assert response.status_code == 200, response.json()
    payload = response.json()
    normalized_task = session_service._normalize_session_active_task(
        load_chat_state(tmp_path)["conversations"][0]["active_task"]
    )
    assistant = payload["messages"][-1]
    assert assistant["content"] == "继续检查。"
    assert "thought" not in assistant
    assert payload["taskSummary"] == "继续检查。"
    assert normalized_task["latest_summary"] == "继续检查。"
    assert normalized_task["title"] == ""
    assert normalized_task["goal"] == ""
    assert normalized_task["next_action"] == ""
    assert "<invoke" not in json.dumps(payload, ensure_ascii=False)
    assert "<parameter" not in json.dumps(payload, ensure_ascii=False)
    assert "<state" not in json.dumps(payload, ensure_ascii=False)


def test_session_detail_recovers_stale_running_state(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    state = load_chat_state(tmp_path)
    state["conversations"][0]["last_turn_status"] = "running"
    save_chat_state(tmp_path, state)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    session_service._set_session_running("session-live", False)

    response = client.get("/api/sessions/session-live")

    assert response.status_code == 200
    payload = response.json()
    assert payload["currentPhase"] == "ready"
    assert payload["messages"][-1]["role"] == "assistant"
    assert "已被中断" in payload["messages"][-1]["content"]
    persisted = load_chat_state(tmp_path)
    assert persisted["conversations"][0]["last_turn_status"] == "ready"


def test_submit_session_message_allows_follow_up_when_previous_turn_finished(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=1),
    )

    class DummyAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "completed",
                "summary": "继续推进并给出下一步建议。",
                "raw_output": "继续推进并给出下一步建议。",
                "outcome": "done",
                "read_files": ["web/src/routes/ChatCodingRoute.tsx"],
                "tool_call_count": 1,
                "tool_trace": [
                    {"name": "read_file_tool"},
                ],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: DummyAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续修复 web/src/routes/ChatCodingRoute.tsx"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["messages"][-1]["role"] == "assistant"
    assert payload["messages"][-1]["content"] == "继续推进并给出下一步建议。"
    assert payload["currentPhase"] == "ready"
    assert "activeTask" not in payload


def test_submit_session_message_continues_progress_until_done(tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "prompt_debugger.py").write_text("pass\n", encoding="utf-8")
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=2),
    )
    calls = []

    class ContinuingAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            calls.append(initial_prompt)
            if len(calls) == 1:
                return {
                    "status": "completed",
                    "summary": "<state>",
                    "raw_output": "<state>",
                    "outcome": "progress",
                    "next_action": "继续读取测试工具结构并形成规划。",
                    "read_files": ["tests/prompt_debugger.py"],
                    "tool_call_count": 1,
                    "tool_trace": [
                        {"name": "read_file_tool", "args": {"file_path": "tests/prompt_debugger.py"}},
                    ],
                }
            return {
                "status": "completed",
                "summary": "规划完成：先复用 prompt_debugger，再包装 BDD 调试入口。",
                "raw_output": "规划完成：先复用 prompt_debugger，再包装 BDD 调试入口。",
                "outcome": "done",
                "read_files": ["tests/prompt_debugger.py"],
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: ContinuingAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "做一个测试工具吧,能够更快速的进行BDD调试,先规划一下,然后向我汇报"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert len(calls) == 2
    assert "继续完成同一个用户目标" in calls[1]
    assert payload["messages"][-1]["content"] == "规划完成：先复用 prompt_debugger，再包装 BDD 调试入口。"
    assert payload["currentPhase"] == "ready"


def test_submit_session_message_does_not_persist_xml_protocol_as_reply_or_task(tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "prompt_debugger.py").write_text("pass\n", encoding="utf-8")
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=1),
    )

    class ProtocolOnlyAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "completed",
                "summary": (
                    "继续检查文件。\n"
                    '<invoke name="read_file_tool">'
                    '<parameter name="file_path">tests/prompt_debugger.py</parameter>'
                    "</invoke>\n"
                    "</parameter>"
                ),
                "raw_output": (
                    "继续检查文件。\n"
                    '<invoke name="read_file_tool">'
                    '<parameter name="file_path">tests/prompt_debugger.py</parameter>'
                    "</invoke>\n"
                    "<state"
                ),
                "outcome": "done",
                "read_files": ["tests/prompt_debugger.py"],
                "tool_call_count": 1,
                "tool_trace": [
                    {"name": "read_file_tool", "args": {"file_path": "tests/prompt_debugger.py"}},
                ],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: ProtocolOnlyAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "请继续检查 BDD 调试工具规划"},
    )

    assert response.status_code == 202, response.json()
    payload = response.json()
    assistant = payload["messages"][-1]
    assert assistant["content"] == "继续检查文件。"
    state = load_chat_state(tmp_path)
    persisted_json = json.dumps(state, ensure_ascii=False)
    assert "<invoke" not in persisted_json
    assert "<parameter" not in persisted_json
    assert "</parameter>" not in persisted_json
    assert "<state" not in persisted_json
    active_task = state["conversations"][0]["active_task"]
    assert active_task["latest_summary"] == "继续检查文件。"
    assert active_task["title"] == "请继续检查 BDD 调试工具规划"
    assert active_task["goal"] == "请继续检查 BDD 调试工具规划"


def test_submit_session_message_surfaces_continuation_limit(tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "prompt_debugger.py").write_text("pass\n", encoding="utf-8")
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=1),
    )

    class ProgressOnlyAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "completed",
                "summary": "",
                "raw_output": "",
                "outcome": "progress",
                "next_action": "继续读取测试工具结构并形成规划。",
                "read_files": ["tests/prompt_debugger.py"],
                "tool_call_count": 1,
                "tool_trace": [
                    {"name": "read_file_tool", "args": {"file_path": "tests/prompt_debugger.py"}},
                ],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: ProgressOnlyAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "做一个测试工具吧,能够更快速的进行BDD调试,先规划一下,然后向我汇报"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert "任务级持续上限" in payload["messages"][-1]["content"]
    assert "发送“继续”" in payload["messages"][-1]["content"]
    assert payload["currentPhase"] == "ready"


def test_submit_session_continue_preserves_unfinished_task_goal(tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "prompt_debugger.py").write_text("pass\n", encoding="utf-8")
    _seed_chat_state(
        tmp_path,
        task_status="reading",
        active_task={
            "task_id": "bdd-tool-plan",
            "kind": "coding",
            "status": "reading",
            "title": "做一个 BDD 调试测试工具规划并汇报",
            "goal": "做一个 BDD 调试测试工具规划并汇报",
            "read_files": ["tests/prompt_debugger.py"],
            "latest_summary": "已读取测试工具结构。",
            "updated_at": "2026-05-20T16:24:53",
        },
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=1),
    )
    prompts = []

    class ResumeAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            prompts.append(initial_prompt)
            return {
                "status": "completed",
                "summary": "继续完成规划：建议包装 prompt_debugger 的 BDD 场景过滤能力。",
                "raw_output": "继续完成规划：建议包装 prompt_debugger 的 BDD 场景过滤能力。",
                "outcome": "progress",
                "read_files": ["tests/prompt_debugger.py"],
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: ResumeAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert prompts[0] == "继续完成上一任务：做一个 BDD 调试测试工具规划并汇报"
    state = load_chat_state(tmp_path)
    active_task = state["conversations"][0]["active_task"]
    assert active_task["goal"] == "做一个 BDD 调试测试工具规划并汇报"
    assert active_task["title"] == "做一个 BDD 调试测试工具规划并汇报"
    assert active_task["last_user_message"] == "继续"


def test_submit_session_continue_recovers_goal_when_active_task_is_continue(tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "prompt_debugger.py").write_text("pass\n", encoding="utf-8")
    _seed_chat_state(
        tmp_path,
        task_status="reading",
        active_task={
            "task_id": "polluted-continue",
            "kind": "coding",
            "status": "reading",
            "title": "继续",
            "goal": "继续",
            "read_files": ["tests/prompt_debugger.py"],
            "latest_summary": "<state",
            "updated_at": "2026-05-20T17:54:06",
        },
    )
    state = load_chat_state(tmp_path)
    state["conversations"][0]["messages"] = [
        {
            "role": "user",
            "content": "做一个测试工具吧,能够更快速的进行BDD调试,先规划一下,然后向我汇报",
            "timestamp": "2026-05-20T17:50:00",
        },
        {
            "role": "assistant",
            "content": "已达到 Web Chat 任务级持续上限（1 轮），本次先暂停，避免后台无限运行。",
            "timestamp": "2026-05-20T17:51:00",
        },
        {
            "role": "user",
            "content": "继续",
            "timestamp": "2026-05-20T17:53:05",
        },
    ]
    save_chat_state(tmp_path, state)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=1),
    )
    prompts = []

    class ResumeAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            prompts.append(initial_prompt)
            return {
                "status": "completed",
                "summary": "<state",
                "raw_output": "<state",
                "outcome": "progress",
                "next_action": "继续读取测试工具结构并形成规划。",
                "read_files": ["tests/prompt_debugger.py"],
                "tool_call_count": 1,
                "tool_trace": [
                    {"name": "read_file_tool", "args": {"file_path": "tests/prompt_debugger.py"}},
                ],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: ResumeAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续"},
    )

    assert response.status_code == 202
    assert prompts[0] == (
        "继续完成上一任务：做一个测试工具吧,能够更快速的进行BDD调试,先规划一下,然后向我汇报"
    )
    payload = response.json()
    assert "任务级持续上限" in payload["messages"][-1]["content"]
    assert "<state" not in payload["messages"][-1]["content"]
    state = load_chat_state(tmp_path)
    active_task = state["conversations"][0]["active_task"]
    assert active_task["goal"] == "做一个测试工具吧,能够更快速的进行BDD调试,先规划一下,然后向我汇报"
    assert active_task["title"] == "做一个测试工具吧,能够更快速的进行BDD调试,先规划一下,然后向我汇报"
    assert active_task["latest_summary"] != "<state"


def test_persist_turn_result_cleans_parameter_and_requires_real_stop(tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "prompt_debugger.py").write_text("pass\n", encoding="utf-8")
    _seed_chat_state(
        tmp_path,
        task_status="reading",
        active_task={
            "task_id": "bdd-tool-plan",
            "kind": "coding",
            "status": "reading",
            "title": "做一个 BDD 调试测试工具规划并汇报",
            "goal": "做一个 BDD 调试测试工具规划并汇报",
            "read_files": ["tests/prompt_debugger.py"],
            "latest_summary": "已读取测试工具结构。",
            "updated_at": "2026-05-20T16:24:53",
        },
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    session_service._clear_session_turn_control("session-live")

    session_service._persist_session_turn_result(
        "session-live",
        {
            "status": "stopped",
            "summary": "连续被拦截。让我尝试拆分写入。\n</parameter>",
            "raw_output": "连续被拦截。让我尝试拆分写入。\n</parameter>",
            "stop_requested": True,
            "outcome": "progress",
            "read_files": ["tests/prompt_debugger.py"],
            "tool_call_count": 0,
            "tool_trace": [],
        },
    )

    state = load_chat_state(tmp_path)
    message = state["conversations"][0]["messages"][-1]
    assert message["role"] == "assistant"
    assert message["content"] == "连续被拦截。让我尝试拆分写入。"
    assert message["content"] != "本轮已按请求停止。"
    active_task = state["conversations"][0]["active_task"]
    assert active_task["latest_summary"] == "连续被拦截。让我尝试拆分写入。"
    assert "</parameter>" not in json.dumps(active_task, ensure_ascii=False)


def test_session_detail_uses_ready_phase_for_resting_sessions(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.get("/api/sessions/session-live")

    assert response.status_code == 200
    payload = response.json()
    assert payload["currentPhase"] == "ready"


def test_submit_session_message_persists_visible_failure(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    class FailingAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            raise RuntimeError("LLM unavailable")

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: FailingAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "请修复 web/src/routes/ChatCodingRoute.tsx 的提交流程"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["messages"][-1]["role"] == "assistant"
    assert "失败" in payload["messages"][-1]["content"] or "failed" in payload["messages"][-1]["content"].lower()
    assert "LLM unavailable" in payload["messages"][-1]["content"]
    assert payload["currentPhase"] == "failed"


def test_submit_session_message_surfaces_failed_result_error(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    class FailingResultAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "failed",
                "summary": "",
                "raw_output": "",
                "error": "configuration_error: LiteLLM 未安装，无法执行模型调用；请安装 litellm",
                "outcome": "blocked",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: FailingResultAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "你现在是这个项目的agent，请告诉我目前的感受"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["messages"][-1]["role"] == "assistant"
    assert "LiteLLM 未安装" in payload["messages"][-1]["content"]
    assert payload["currentPhase"] == "failed"


def test_submit_session_message_omits_mental_snapshot_when_disabled(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "is_mental_model_enabled", lambda: False)

    class DummyAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "completed",
                "summary": "继续推进并给出下一步建议。",
                "raw_output": "继续推进并给出下一步建议。",
                "reasoning_content": "先保留思考，再让心智快照按开关退场。",
                "mental_snapshot": {
                    "mood": "专注",
                    "feeling": "这部分应该被开关挡住。",
                    "whisper": "不要落盘。",
                    "cognitiveState": "productive",
                },
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: DummyAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续修复 web/src/routes/ChatCodingRoute.tsx"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["messages"][-1]["thought"] == "先保留思考，再让心智快照按开关退场。"
    assert "mentalSnapshot" not in payload["messages"][-1]


def test_submit_session_message_uses_per_turn_mental_model_override(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "is_mental_model_enabled", lambda: True)

    created_agents = []

    class DummyAgent:
        def __init__(self):
            self.override = None
            self.seeded_history = None
            created_agents.append(self)

        def set_mental_model_enabled_override(self, enabled):
            self.override = enabled

        def seed_chat_history(self, messages):
            self.seeded_history = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "completed",
                "summary": "已按本轮开关处理。",
                "raw_output": "已按本轮开关处理。",
                "mental_snapshot": {
                    "mood": "专注",
                    "feeling": "如果开关关闭，这里不应该落盘。",
                    "whisper": "per-turn",
                    "cognitiveState": "productive",
                },
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", DummyAgent)
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    disabled_response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "这一轮不要打开心智模型", "mentalModelEnabled": False},
    )

    assert disabled_response.status_code == 202, disabled_response.json()
    disabled_payload = disabled_response.json()
    assert created_agents[-1].override is False
    assert "mentalSnapshot" not in disabled_payload["messages"][-1]

    enabled_response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "这一轮打开心智模型", "mentalModelEnabled": True},
    )

    assert enabled_response.status_code == 202, enabled_response.json()
    enabled_payload = enabled_response.json()
    assert created_agents[-1].override is True
    assert enabled_payload["messages"][-1]["mentalSnapshot"]["mood"] == "专注"


def test_submit_session_message_includes_stream_friendly_tool_and_mental_payloads(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    class DummyAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "completed",
                "summary": "已完成三段式输出。",
                "raw_output": "最终回答内容。",
                "thought": "这是一段可见思考。",
                "reasoning_content": "这是一段可见思考。",
                "state_info": {
                    "mood": "专注",
                    "feeling": "心智模型已展开。",
                    "whisper": "工具调用继续保持单块。",
                },
                "mental_snapshot": {
                    "mood": "专注",
                    "feeling": "心智模型已展开。",
                    "whisper": "工具调用继续保持单块。",
                    "cognitiveState": "productive",
                    "confidence": 0.91,
                    "sampleSize": 3,
                    "interventionCount": 1,
                    "updatedAt": "2026-05-18T12:01:00",
                    "source": "diagnosis",
                    "intervention": "继续保持当前路径。",
                    "metrics": {"sample_size": 3, "intervention_count": 1},
                    "historyTail": [
                        {"cognitiveState": "productive", "confidence": 0.91, "timestamp": "2026-05-18T12:01:00"},
                    ],
                },
                "tool_trace": [
                    {"name": "read_file_tool", "result_preview": "read ok", "status": "success"},
                    {"name": "run_test_for_tool", "result_preview": "tests passed", "status": "success"},
                ],
                "tool_call_count": 2,
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: DummyAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续把对话展示改成四段式"},
    )

    assert response.status_code == 202
    payload = response.json()
    assistant = payload["messages"][-1]
    assert assistant["content"] == "最终回答内容。"
    assert assistant["thought"] == "这是一段可见思考。"
    assert assistant["mentalSnapshot"]["cognitiveState"] == "productive"
    assert assistant["mentalSnapshot"]["intervention"] == "继续保持当前路径。"
    assert assistant["mentalSnapshot"]["metrics"]["sample_size"] == 3
    assert assistant["toolCalls"] == [
        {"name": "read_file_tool", "status": "done", "summary": "read ok"},
        {"name": "run_test_for_tool", "status": "done", "summary": "tests passed"},
    ]
    assert payload["currentPhase"] == "ready"


def test_submit_session_message_restores_prior_mental_snapshot_for_agent(tmp_path, monkeypatch):
    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "active_conversation_id": "session-live",
            "updated_at": "2026-05-20T14:00:00",
            "conversations": [
                {
                    "conversation_id": "session-live",
                    "title": "真实会话",
                    "updated_at": "2026-05-20T14:00:00",
                    "last_turn_status": "ready",
                    "messages": [
                        {
                            "role": "user",
                            "content": "你能感知到你的心智模型吗",
                            "timestamp": "2026-05-20T13:58:00",
                        },
                        {
                            "role": "assistant",
                            "content": "我对自己的心智模型能感知多少？",
                            "timestamp": "2026-05-20T13:59:00",
                            "mental_snapshot": {
                                "mood": "沉思",
                                "feeling": "正在延续心智模型话题。",
                                "whisper": "接住上一段回答。",
                                "sampleSize": 4,
                            },
                        },
                    ],
                }
            ],
        },
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    captured = {}

    class DummyAgent:
        def seed_chat_history(self, messages):
            captured["history"] = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "completed",
                "summary": "继续补完心智模型回答。",
                "raw_output": "继续补完心智模型回答。",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: DummyAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "你话还没说完"},
    )

    assert response.status_code == 202
    assert captured["history"][1]["mental_snapshot"]["mood"] == "沉思"
    assert captured["history"][0]["content"] == "你能感知到你的心智模型吗"


def test_runtime_summary_prefers_current_phase_over_stale_task_progress(monkeypatch):
    monkeypatch.setattr(
        runtime_service,
        "get_active_session_detail",
        lambda: {
            "title": "真实会话",
            "taskSummary": "继续前端开发",
            "currentPhase": "ready",
            "changedFiles": ["web/src/routes/ChatCodingRoute.tsx"],
        },
    )
    monkeypatch.setattr(runtime_service, "_load_runtime_state", lambda: {})

    payload = runtime_service.get_runtime_summary()

    assert payload["status"] == "success"
    assert payload["currentPhase"] == "ready"


def test_runtime_summary_exposes_runtime_manager_workbench_state(monkeypatch):
    monkeypatch.setattr(runtime_service, "get_active_session_detail", lambda: {})
    monkeypatch.setattr(runtime_service, "_load_runtime_state", lambda: {})
    monkeypatch.setattr(
        runtime_service,
        "_load_runtime_manager_snapshot",
        lambda: {
            "daemonRunning": True,
            "runtimeState": "running",
            "managerPid": 9912,
            "stateVersion": 17,
            "workbench": {
                "desiredState": "closed",
                "observedState": "open",
                "phase": "closing",
                "backendPid": 3001,
                "browserWindowPid": 4002,
                "browserManaged": True,
                "url": "http://127.0.0.1:8000",
                "lastReason": "web_close_button",
                "failureMessage": "",
            },
        },
    )

    payload = runtime_service.get_runtime_summary()

    assert payload["runtimeManager"]["running"] is True
    assert payload["runtimeManager"]["managerPid"] == 9912
    assert payload["workbench"]["desiredState"] == "closed"
    assert payload["workbench"]["observedState"] == "open"
    assert payload["workbench"]["phase"] == "closing"
    assert payload["workbench"]["backendPid"] == 3001


def test_runtime_summary_exposes_tool_call_session_state(monkeypatch):
    monkeypatch.setattr(
        runtime_service,
        "get_active_session_detail",
        lambda: {
            "title": "真实会话",
            "taskSummary": "继续前端开发",
            "currentPhase": "running",
        },
    )
    monkeypatch.setattr(
        runtime_service,
        "_load_runtime_state",
        lambda: {
            "status": "THINKING",
            "runtime_status": "ACTING",
            "last_tool_name": "read_file_tool",
        },
    )

    payload = runtime_service.get_runtime_summary()

    assert payload["sessionState"] == "tooling"
    assert payload["sessionNeedsResponse"] is False
    assert payload["sessionToolName"] == "read_file_tool"
    assert "tool" in payload["sessionStateLine"].lower() or "工具" in payload["sessionStateLine"]


def test_runtime_summary_exposes_thinking_session_state(monkeypatch):
    monkeypatch.setattr(
        runtime_service,
        "get_active_session_detail",
        lambda: {
            "title": "真实会话",
            "taskSummary": "继续前端开发",
            "currentPhase": "running",
        },
    )
    monkeypatch.setattr(
        runtime_service,
        "_load_runtime_state",
        lambda: {
            "status": "THINKING",
            "runtime_status": "WORKING",
            "last_tool_name": "grep_search_tool",
        },
    )

    payload = runtime_service.get_runtime_summary()

    assert payload["sessionState"] == "thinking"
    assert payload["sessionNeedsResponse"] is False
    assert payload["sessionToolName"] == "grep_search_tool"


def test_runtime_summary_exposes_answering_session_state(monkeypatch):
    monkeypatch.setattr(
        runtime_service,
        "get_active_session_detail",
        lambda: {
            "title": "真实会话",
            "taskSummary": "继续前端开发",
            "currentPhase": "running",
        },
    )
    monkeypatch.setattr(
        runtime_service,
        "_load_runtime_state",
        lambda: {
            "status": "WORKING",
            "runtime_status": "WORKING",
            "turn_output_tokens": 64,
            "last_tool_name": "",
        },
    )

    payload = runtime_service.get_runtime_summary()

    assert payload["sessionState"] == "answering"
    assert payload["sessionNeedsResponse"] is False


def test_runtime_summary_treats_stopping_session_as_active(monkeypatch):
    monkeypatch.setattr(
        runtime_service,
        "get_active_session_detail",
        lambda: {
            "title": "真实会话",
            "taskSummary": "正在收束当前轮。",
            "currentPhase": "stopping",
        },
    )
    monkeypatch.setattr(runtime_service, "_load_runtime_state", lambda: {})

    payload = runtime_service.get_runtime_summary()

    assert payload["status"] == "running"
    assert payload["sessionState"] == "running"
    assert payload["sessionNeedsResponse"] is False


def test_runtime_summary_marks_ready_session_as_needing_response(monkeypatch):
    monkeypatch.setattr(
        runtime_service,
        "get_active_session_detail",
        lambda: {
            "title": "真实会话",
            "taskSummary": "继续前端开发",
            "currentPhase": "ready",
        },
    )
    monkeypatch.setattr(runtime_service, "_load_runtime_state", lambda: {})

    payload = runtime_service.get_runtime_summary()

    assert payload["sessionState"] == "ready"
    assert payload["sessionNeedsResponse"] is True
    assert "继续" in payload["sessionStateLine"] or "ready" in payload["sessionStateLine"].lower()


def test_runtime_summary_marks_failed_session_as_needing_response(monkeypatch):
    monkeypatch.setattr(
        runtime_service,
        "get_active_session_detail",
        lambda: {
            "title": "真实会话",
            "taskSummary": "测试失败，需要你决定先修测试还是先回退。",
            "currentPhase": "failed",
            "updatedAt": "2026-05-18T20:00:00",
        },
    )
    monkeypatch.setattr(
        runtime_service,
        "_load_runtime_state",
        lambda: {
            "status": "ERROR",
            "runtime_status": "ERROR",
            "updated_at": "2026-05-18T20:00:01",
        },
    )

    payload = runtime_service.get_runtime_summary()

    assert payload["sessionState"] == "failed"
    assert payload["sessionNeedsResponse"] is True
    assert payload["sessionUpdatedAt"] == "2026-05-18T20:00:00"


def test_runtime_summary_ready_session_ignores_stale_runtime_error(monkeypatch):
    monkeypatch.setattr(
        runtime_service,
        "get_active_session_detail",
        lambda: {
            "title": "真实会话",
            "taskSummary": "继续前端开发",
            "currentPhase": "ready",
            "updatedAt": "2026-05-18T20:30:00",
        },
    )
    monkeypatch.setattr(
        runtime_service,
        "_load_runtime_state",
        lambda: {
            "status": "ERROR",
            "runtime_status": "IDLE",
            "updated_at": "2026-05-18T20:29:59",
        },
    )

    payload = runtime_service.get_runtime_summary()

    assert payload["status"] == "success"
    assert payload["sessionState"] == "ready"
    assert payload["sessionNeedsResponse"] is True


def test_runtime_summary_exposes_latest_mental_state(monkeypatch):
    monkeypatch.setattr(runtime_service, "get_active_session_detail", lambda: {})
    monkeypatch.setattr(runtime_service, "_load_runtime_state", lambda: {})

    class DummyMentalModel:
        def get_last_state(self):
            return {
                "mood": "专注",
                "feeling": "规则感知: normal",
                "whisper": "继续推进",
                "timestamp": "2026-05-18T20:00:02",
            }

        def diagnose(self):
            return SimpleNamespace(
                state="normal",
                confidence=0.82,
                metrics={"sample_size": 6, "intervention_count": 1},
                timestamp="2026-05-18T20:00:02",
            )

    monkeypatch.setattr(runtime_service, "get_mental_model", lambda *args, **kwargs: DummyMentalModel())

    payload = runtime_service.get_runtime_summary()

    assert payload["mentalState"]["mood"] == "专注"
    assert payload["mentalState"]["feeling"] == "规则感知: normal"
    assert payload["mentalState"]["whisper"] == "继续推进"
    assert payload["mentalState"]["cognitiveState"] == "normal"
    assert payload["mentalState"]["source"] == "state"
    assert payload["mentalState"]["confidence"] == pytest.approx(0.82)
    assert payload["mentalState"]["sampleSize"] == 6
    assert payload["mentalState"]["updatedAt"] == "2026-05-18T20:00:02"


def test_runtime_summary_reports_disabled_mental_model(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    public_config["mental_model"] = {"enabled": False}

    monkeypatch.setattr(runtime_service, "load_public_config", lambda: copy.deepcopy(public_config))
    monkeypatch.setattr(runtime_service, "get_active_session_detail", lambda: {})
    monkeypatch.setattr(runtime_service, "_load_runtime_state", lambda: {})
    monkeypatch.setattr(runtime_service, "_load_runtime_manager_snapshot", lambda: {})

    payload = runtime_service.get_runtime_summary()

    assert payload["mentalState"]["source"] == "disabled"
    assert "关闭" in payload["mentalState"]["summary"] or "disabled" in payload["mentalState"]["summary"].lower()


def test_runtime_summary_falls_back_to_mental_diagnosis_when_state_is_empty(monkeypatch):
    monkeypatch.setattr(runtime_service, "get_active_session_detail", lambda: {})
    monkeypatch.setattr(runtime_service, "_load_runtime_state", lambda: {})

    class DummyMentalModel:
        def get_last_state(self):
            return {}

        def diagnose(self):
            return SimpleNamespace(
                state="thrashing",
                confidence=0.71,
                metrics={"sample_size": 8, "intervention_count": 3},
                timestamp="2026-05-18T20:00:03",
            )

    monkeypatch.setattr(runtime_service, "get_mental_model", lambda *args, **kwargs: DummyMentalModel())

    payload = runtime_service.get_runtime_summary()

    assert payload["mentalState"]["mood"] == ""
    assert payload["mentalState"]["cognitiveState"] == "thrashing"
    assert payload["mentalState"]["source"] == "diagnosis"
    assert payload["mentalState"]["confidence"] == pytest.approx(0.71)
    assert payload["mentalState"]["sampleSize"] == 8
    assert payload["mentalState"]["updatedAt"] == "2026-05-18T20:00:03"


def test_config_summary_exposes_language():
    response = client.get("/api/config/public")
    assert response.status_code == 200
    payload = response.json()
    assert payload["language"] in {"zh", "en"}


def test_config_workspace_exposes_unified_config_payload(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    public_config.setdefault("ui", {})["language"] = "en"

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.get("/api/config/workspace")

    assert response.status_code == 200
    payload = response.json()
    assert payload["language"] == "en"
    assert payload["publicConfig"]["ui"]["language"] == "en"
    assert "rawToml" in payload
    assert "diagnosis" in payload
    preset_options = {item["preset_id"]: item for item in payload["modelPresetOptions"]}
    relay_preset = preset_options["relay_openai_gpt_5_5"]
    assert relay_preset["category"] == "relay"
    assert relay_preset["provider"]["kind"] == "relay"
    assert relay_preset["provider"]["base_url"] == "https://pixel.try-chatapi.com/v1"
    assert relay_preset["model"]["transport"] == "chat_completions"
    assert relay_preset["model"]["contract"] == "tool_chat"
    assert "modelOptions" in payload
    assert "profileCards" in payload


def test_config_workspace_exposes_full_editor_schema(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.get("/api/config/workspace")

    assert response.status_code == 200
    payload = response.json()
    editor_sections = {section["id"]: section for section in payload["editorSections"]}
    editor_meta = payload["editorMeta"]

    assert "runtime" in editor_sections
    assert "tools" in editor_sections
    assert "prompt" in editor_sections
    assert "llm-profiles" in editor_sections
    assert editor_sections["runtime"]["path"] == "runtime"
    assert editor_meta["runtime.profile"]["kind"] == "select"
    assert editor_meta["runtime.profile"]["badge"] == "选项"
    assert editor_meta["tools.file.editable_extensions"]["kind"] == "string_list"
    assert editor_meta["prompt.sections"]["kind"] == "object_list"
    assert editor_meta["prompt.sections"]["badge"] == "列表"
    assert editor_meta["llm.profiles.primary.provider.kind"]["label"] == "服务商类型"
    assert editor_meta["llm.profiles.primary.provider.base_url"]["label"] == "服务商基础地址"
    assert any(section["id"] == "overview" for section in payload["sections"])
    assert any(section["id"] == "shell" for section in payload["sections"])


def test_config_workspace_surfaces_llm_security_diagnostics_without_blocking_read(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    public_config["llm"]["profiles"]["primary"]["provider"] = {
        "kind": "openai",
        "api_key_env": "OPENAI_API_KEY",
        "base_url": "file:///C:/Windows/win.ini",
        "compat_mode": "openai",
        "requires_api_key": True,
        "context_window": 100000,
    }

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.get("/api/config/workspace")

    assert response.status_code == 200
    payload = response.json()
    assert payload["blockingCount"] >= 1
    assert any("LLM security guard" in item for item in payload["diagnosis"]["blocking_issues"])


def test_config_workspace_draft_delete_model_marks_profiles_unconfigured(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    public_config["llm"]["profiles"]["primary"] = {
        "model_ref": "openai_gpt_5_5",
        "overrides": {},
    }

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.post(
        "/api/config/draft/delete-model",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "modelId": "openai_gpt_5_5",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["publicConfig"]["llm"]["profiles"]["primary"]["model_ref"] == UNCONFIGURED_MODEL_REF
    assert next(item for item in payload["profileCards"] if item["profileId"] == "primary")["requiredModelMissing"] is True


def test_config_workspace_test_llm_uses_pending_draft_key(monkeypatch):
    public_config = copy.deepcopy(load_public_config())

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    def fake_http_probe(provider, profile, api_key=None):
        assert api_key == "draft-secret"
        return {"ok": True, "message": "ok"}

    monkeypatch.setattr("config.public_config._probe_llm_http", fake_http_probe)

    draft_response = client.post(
        "/api/config/draft/update-model",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "modelId": "deepseek_v4_pro",
            "provider": public_config["llm"]["model_library"]["deepseek_v4_pro"]["provider"],
            "model": "deepseek-v4-pro",
            "label": "DeepSeek V4 Pro",
            "details": public_config["llm"]["model_library"]["deepseek_v4_pro"],
            "apiKeyEnv": "VIBELUTION_LLM_DEEPSEEK_V4_PRO_API_KEY",
            "apiKey": "draft-secret",
        },
    )

    assert draft_response.status_code == 200
    draft_payload = draft_response.json()
    pending_token = draft_payload["draftMeta"]["pending_api_keys"]["VIBELUTION_LLM_DEEPSEEK_V4_PRO_API_KEY"]
    assert pending_token != "draft-secret"
    assert pending_token.startswith("pending-secret:")

    response = client.post(
        "/api/config/test-llm",
        json={
            "publicConfig": draft_payload["publicConfig"],
            "draftMeta": draft_payload["draftMeta"],
            "profileId": "subagent_explorer",
        },
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["ok"] is True
    assert payload["api_key_source"] == "pending-env:VIBELUTION_LLM_DEEPSEEK_V4_PRO_API_KEY"
    assert payload["config_scope"] == "draft"
    assert payload["requires_api_key"] is True


def test_config_workspace_test_llm_ignores_forged_pending_draft_key(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    monkeypatch.delenv("VIBELUTION_LLM_DEEPSEEK_V4_PRO_API_KEY", raising=False)

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    def fake_http_probe(provider, profile, api_key=None):
        assert api_key is None
        return {"ok": False, "message": "missing"}

    monkeypatch.setattr("config.public_config._probe_llm_http", fake_http_probe)

    response = client.post(
        "/api/config/test-llm",
        json={
            "publicConfig": public_config,
            "draftMeta": {
                "pending_api_keys": {"VIBELUTION_LLM_DEEPSEEK_V4_PRO_API_KEY": "forged-secret"},
                "pending_cleared_api_keys": [],
            },
            "profileId": "subagent_explorer",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["api_key_source"] == "missing"


def test_config_workspace_test_llm_reports_local_draft_route_clearly(monkeypatch):
    saved_config = copy.deepcopy(load_public_config())
    draft_config = copy.deepcopy(saved_config)
    draft_config.setdefault("runtime", {})["profile"] = "safe_local"
    monkeypatch.delenv("VIBELUTION_LLM_DEEPSEEK_V4_PRO_API_KEY", raising=False)

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(saved_config))

    def fake_http_probe(provider, profile, api_key=None):
        assert provider.kind == "local"
        assert provider.base_url == "http://localhost:11434/v1"
        return {"ok": False, "message": "<urlopen error [WinError 10061] connection refused>"}

    monkeypatch.setattr("config.public_config._probe_llm_http", fake_http_probe)

    response = client.post(
        "/api/config/test-llm",
        json={
            "publicConfig": draft_config,
            "draftMeta": {},
            "profileId": "primary",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["provider_kind"] == "local"
    assert payload["base_url"] == "http://localhost:11434/v1"
    assert payload["config_scope"] == "draft"
    assert payload["requires_api_key"] is False
    assert payload["api_key_source"] == "not-required"


def test_config_workspace_test_llm_rejects_metadata_service_base_url(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    target = public_config["llm"]["profiles"]["primary"]
    target["provider"] = {
        "kind": "openai",
        "api_key_env": "OPENAI_API_KEY",
        "base_url": "http://169.254.169.254/v1",
        "compat_mode": "openai",
        "requires_api_key": True,
        "context_window": 100000,
    }
    target["model"] = "gpt-5.5"

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(load_public_config()))

    response = client.post(
        "/api/config/test-llm",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "profileId": "primary",
        },
    )

    assert response.status_code == 422
    assert "base_url" in response.json()["detail"]


def test_config_workspace_test_llm_rejects_file_base_url(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    target = public_config["llm"]["profiles"]["primary"]
    target["provider"] = {
        "kind": "openai",
        "api_key_env": "OPENAI_API_KEY",
        "base_url": "file:///C:/Windows/win.ini",
        "compat_mode": "openai",
        "requires_api_key": True,
        "context_window": 100000,
    }
    target["model"] = "gpt-5.5"

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(load_public_config()))

    response = client.post(
        "/api/config/test-llm",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "profileId": "primary",
        },
    )

    assert response.status_code == 422
    assert "http(s)" in response.json()["detail"]


def test_config_workspace_test_llm_allows_localhost_for_local_provider(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    target = public_config["llm"]["profiles"]["primary"]
    target["provider"] = {
        "kind": "local",
        "api_key_env": "",
        "base_url": "http://127.0.0.1:11434/v1",
        "compat_mode": "openai",
        "requires_api_key": False,
        "context_window": 65536,
    }
    target["model"] = "llama3.2"

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(load_public_config()))

    def fake_http_probe(provider, profile, api_key=None):
        assert provider.kind == "local"
        assert provider.base_url == "http://127.0.0.1:11434/v1"
        assert api_key is None
        return {"ok": True, "message": "local-ok"}

    monkeypatch.setattr("config.public_config._probe_llm_http", fake_http_probe)

    response = client.post(
        "/api/config/test-llm",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "profileId": "primary",
        },
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["ok"] is True
    assert payload["provider_kind"] == "local"


def test_config_workspace_draft_model_rejects_path_api_key_env(monkeypatch):
    public_config = copy.deepcopy(load_public_config())

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.post(
        "/api/config/draft/update-model",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "modelId": "deepseek_v4_pro",
            "provider": public_config["llm"]["model_library"]["deepseek_v4_pro"]["provider"],
            "model": "deepseek-v4-pro",
            "label": "DeepSeek V4 Pro",
            "details": public_config["llm"]["model_library"]["deepseek_v4_pro"],
            "apiKeyEnv": "PATH",
            "apiKey": "draft-secret",
        },
    )

    assert response.status_code == 422
    assert "PATH" in response.json()["detail"]


def test_config_workspace_apply_rejects_stale_base_hash(monkeypatch):
    original = copy.deepcopy(load_public_config())
    stale_hash = public_config_hash(original)
    external = copy.deepcopy(original)
    external.setdefault("ui", {})["language"] = "en"
    public_config = external

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.put(
        "/api/config/apply",
        json={
            "publicConfig": original,
            "draftMeta": {},
            "baseHash": stale_hash,
        },
    )

    assert response.status_code == 409
    assert "重新加载" in response.json()["detail"]


def test_config_workspace_apply_persists_changes_and_pending_env(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    writes = []
    deletes = []

    def fake_load_public_config():
        return copy.deepcopy(public_config)

    def fake_save_public_config(updated_public_config):
        public_config.clear()
        public_config.update(copy.deepcopy(updated_public_config))

    monkeypatch.setattr(config_service, "load_public_config", fake_load_public_config)
    monkeypatch.setattr(config_service, "save_public_config", fake_save_public_config)
    monkeypatch.setattr(config_service, "_set_user_env_var", lambda name, value: writes.append((name, value)))
    monkeypatch.setattr(config_service, "_delete_user_env_var", lambda name: deletes.append(name))

    payload = copy.deepcopy(public_config)
    payload.setdefault("ui", {})["language"] = "en"

    draft_response = client.post(
        "/api/config/draft/update-model",
        json={
            "publicConfig": payload,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "modelId": "deepseek_v4_pro",
            "provider": payload["llm"]["model_library"]["deepseek_v4_pro"]["provider"],
            "model": "deepseek-v4-pro",
            "label": "DeepSeek V4 Pro",
            "details": payload["llm"]["model_library"]["deepseek_v4_pro"],
            "apiKeyEnv": "VIBELUTION_LLM_DEEPSEEK_V4_PRO_API_KEY",
            "apiKey": "draft-secret",
        },
    )

    assert draft_response.status_code == 200
    draft_payload = draft_response.json()

    response = client.put(
        "/api/config/apply",
        json={
            "publicConfig": draft_payload["publicConfig"],
            "draftMeta": draft_payload["draftMeta"],
            "baseHash": public_config_hash(public_config),
        },
    )

    assert response.status_code == 200
    persisted = response.json()
    assert public_config["ui"]["language"] == "en"
    assert writes == [("VIBELUTION_LLM_DEEPSEEK_V4_PRO_API_KEY", "draft-secret")]
    assert deletes == []
    assert persisted["baseHash"] == persisted["hash"]


def test_config_workspace_apply_ignores_forged_pending_env(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    writes = []

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))
    monkeypatch.setattr(config_service, "save_public_config", lambda updated: None)
    monkeypatch.setattr(config_service, "_set_user_env_var", lambda name, value: writes.append((name, value)))

    response = client.put(
        "/api/config/apply",
        json={
            "publicConfig": public_config,
            "draftMeta": {
                "pending_api_keys": {"VIBELUTION_LLM_DEEPSEEK_V4_PRO_API_KEY": "forged-secret"},
                "pending_cleared_api_keys": [],
            },
            "baseHash": public_config_hash(public_config),
        },
    )

    assert response.status_code == 200
    assert writes == []


def test_config_and_evolution_share_intake_mode(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    public_config.setdefault("evolution", {})["intake_mode"] = "auto"

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))
    monkeypatch.setattr(workbench_contract_service, "load_public_config", lambda: copy.deepcopy(public_config))

    config_response = client.get("/api/config/public")
    overview_response = client.get("/api/evolution/overview")

    assert config_response.status_code == 200
    assert overview_response.status_code == 200
    assert config_response.json()["intakeMode"] == "auto"
    assert overview_response.json()["intakeMode"] == "auto"


def test_chat_disable_redirects_home_contract_to_evolution(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    agent_cfg = public_config.setdefault("agent", {})
    modes_cfg = agent_cfg.setdefault("modes", {})
    modes_cfg["chat_enabled"] = False
    modes_cfg["self_evolution_enabled"] = True
    modes_cfg["supervised_evolution_enabled"] = True
    modes_cfg["default_shell_mode"] = "chat"
    public_config.setdefault("evolution", {})["enabled"] = True

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))
    monkeypatch.setattr(runtime_service, "load_public_config", lambda: copy.deepcopy(public_config))

    config_response = client.get("/api/config/public")
    runtime_response = client.get("/api/runtime/summary")

    assert config_response.status_code == 200
    assert runtime_response.status_code == 200

    config_payload = config_response.json()
    runtime_payload = runtime_response.json()

    assert config_payload["defaultRoute"] == "/self-evolution"
    assert runtime_payload["defaultRoute"] == "/self-evolution"
    assert config_payload["defaultMode"] == "self_evolution"
    assert runtime_payload["mode"] == "self_evolution"
    assert config_payload["domainAvailability"]["chat"] is False
    assert config_payload["domainAvailability"]["evolution"] is True
    assert runtime_payload["domainAvailability"]["chat"] is False
    assert runtime_payload["domainAvailability"]["evolution"] is True


def test_updating_intake_mode_refreshes_config_and_evolution(monkeypatch):
    public_config = copy.deepcopy(load_public_config())

    def fake_load_public_config():
        return copy.deepcopy(public_config)

    def fake_save_public_config(updated_public_config):
        public_config.clear()
        public_config.update(copy.deepcopy(updated_public_config))

    monkeypatch.setattr(config_service, "load_public_config", fake_load_public_config)
    monkeypatch.setattr(config_service, "save_public_config", fake_save_public_config)
    monkeypatch.setattr(workbench_contract_service, "load_public_config", fake_load_public_config)

    update_response = client.put("/api/config/intake-mode", json={"intakeMode": "auto"})
    config_response = client.get("/api/config/public")
    overview_response = client.get("/api/evolution/overview")

    assert update_response.status_code == 200
    assert config_response.status_code == 200
    assert overview_response.status_code == 200
    assert update_response.json()["intakeMode"] == "auto"
    assert config_response.json()["intakeMode"] == "auto"
    assert overview_response.json()["intakeMode"] == "auto"


def test_updating_language_refreshes_config_summary(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    public_config.setdefault("ui", {})["language"] = "zh"

    def fake_load_public_config():
        return copy.deepcopy(public_config)

    def fake_save_public_config(updated_public_config):
        public_config.clear()
        public_config.update(copy.deepcopy(updated_public_config))

    monkeypatch.setattr(config_service, "load_public_config", fake_load_public_config)
    monkeypatch.setattr(config_service, "save_public_config", fake_save_public_config)
    monkeypatch.setattr("core.web.services.i18n.load_public_config", fake_load_public_config)

    update_response = client.put("/api/config/language", json={"language": "en"})
    config_response = client.get("/api/config/public")

    assert update_response.status_code == 200
    assert config_response.status_code == 200
    assert update_response.json()["language"] == "en"
    assert config_response.json()["language"] == "en"


def test_evolution_routes_use_real_supervised_records(tmp_path, monkeypatch):
    pending_result = run_gym_collection_episode(
        collection_id="foundation_local_stability",
        project_root=tmp_path,
        adapter=RunnerFakeAdapter(),
        episode_id="web_pending_episode",
    )
    _write_supervised_decision_record(
        tmp_path,
        "web_pending_run",
        {
            "decision": "PROMOTE",
            "reason": "候选方案值得继续进入治理流程。",
            "gates": [
                {
                    "name": "gym_promotion",
                    "status": "pass",
                    "reason": "proposal created",
                    "metrics": {
                        "promotion_proposal_path": pending_result.promotion_proposal_path,
                        "decision_path": pending_result.decision_path,
                    },
                }
            ],
        },
    )

    active_result = run_gym_collection_episode(
        collection_id="foundation_local_stability",
        project_root=tmp_path,
        adapter=RunnerFakeAdapter(),
        episode_id="web_active_episode",
    )
    apply_gym_promotion_proposal(active_result.promotion_proposal_path, project_root=tmp_path)
    activation = activate_gym_promotion_proposal(active_result.promotion_proposal_path, project_root=tmp_path)
    _write_supervised_decision_record(
        tmp_path,
        "web_active_run",
        {
            "decision": "PROMOTE",
            "reason": "候选方案已成为当前建议基线。",
            "gates": [
                {
                    "name": "gym_promotion",
                    "status": "pass",
                    "reason": "proposal activated",
                    "metrics": {
                        "promotion_proposal_path": active_result.promotion_proposal_path,
                        "decision_path": active_result.decision_path,
                    },
                }
            ],
            "advisory_context": {
                "active_count": 1,
                "entries": [
                    {
                        "target_key": activation.target_key,
                        "target_label": "local_transaction_closing_v1",
                        "proposal_id": activation.proposal_id,
                        "runtime_effect": "not_applied",
                        "agent_consumption": "advisory",
                    }
                ],
            },
        },
    )
    _write_workbench_state(
        tmp_path,
        {
            "source": "dataset",
            "dataset_name": "custom_prompt_jsonl",
            "dataset_limit": 2,
            "bundle_name": "custom_prompt_jsonl_v1",
            "keep_worktree": True,
        },
    )

    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        evolution_service,
        "get_workbench_contract",
        lambda: {
            "defaultMode": "supervised_evolution",
            "defaultRoute": "/evolution",
            "intakeMode": "manual_review",
            "modeAvailability": {
                "chat": True,
                "self_evolution": True,
                "supervised_evolution": True,
            },
            "domainAvailability": {
                "chat": True,
                "evolution": True,
                "config": True,
            },
        },
    )

    overview_response = client.get("/api/evolution/overview")
    runs_response = client.get("/api/evolution/runs")
    library_response = client.get("/api/evolution/library")

    assert overview_response.status_code == 200
    assert runs_response.status_code == 200
    assert library_response.status_code == 200

    overview_payload = overview_response.json()
    runs_payload = runs_response.json()
    library_payload = library_response.json()

    assert overview_payload["currentStatus"]["decision"] == "PROMOTE"
    assert overview_payload["currentStatus"]["proposalStatus"] == "active"
    assert overview_payload["currentStatus"]["runtimeEffect"] == "not_applied"
    assert overview_payload["currentStatus"]["runSemantics"]["runStatus"] == "success"
    assert overview_payload["currentStatus"]["outcomeSemantics"]["proposalStatusLabel"]
    assert overview_payload["currentStatus"]["actionStates"]["delete"]["enabled"] is False
    assert overview_payload["workbench"]["source"] == "dataset"
    assert overview_payload["workbench"]["datasetName"] == "custom_prompt_jsonl"
    assert overview_payload["recentRuns"][0]["id"] == "web_active_run"
    assert runs_payload[0]["proposalStatus"] == "active"
    assert runs_payload[0]["decision"] == "PROMOTE"
    assert runs_payload[0]["runtimeEffect"] == "not_applied"
    assert runs_payload[0]["outcomeSemantics"]["runtimeEffect"] == "not_applied"
    assert runs_payload[0]["actionStates"]["delete"]["enabled"] is False
    assert any(item["sourceRun"] == "web_active_run" for item in library_payload["items"])
    assert any(item["sourceRun"] == "web_pending_run" for item in library_payload["pending"])
    assert library_payload["items"][0]["proposalStatus"] == "active"
    assert library_payload["pending"][0]["proposalStatus"] == "proposed"
    assert library_payload["items"][0]["outcomeSemantics"]["proposalStatus"] == "active"


def test_evolution_routes_handle_empty_supervised_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        evolution_service,
        "get_workbench_contract",
        lambda: {
            "defaultMode": "supervised_evolution",
            "defaultRoute": "/evolution",
            "intakeMode": "manual_review",
            "modeAvailability": {
                "chat": True,
                "self_evolution": True,
                "supervised_evolution": True,
            },
            "domainAvailability": {
                "chat": True,
                "evolution": True,
                "config": True,
            },
        },
    )

    overview_response = client.get("/api/evolution/overview")
    runs_response = client.get("/api/evolution/runs")
    library_response = client.get("/api/evolution/library")

    assert overview_response.status_code == 200
    assert runs_response.status_code == 200
    assert library_response.status_code == 200
    assert overview_response.json()["currentStatus"]["state"] == "idle"
    assert overview_response.json()["workbench"]["source"] == "unknown"
    assert runs_response.json() == []
    assert library_response.json() == {"items": [], "pending": []}


def test_evolution_workbench_route_exposes_dataset_choices_and_saved_state(tmp_path, monkeypatch):
    _write_workbench_state(
        tmp_path,
        {
            "source": "bundle",
            "bundle_name": "saved_bundle_v1",
            "keep_worktree": False,
        },
    )
    _reset_supervised_live_state()
    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(supervised_control_service, "PROJECT_ROOT", tmp_path)

    response = client.get("/api/evolution/workbench")

    assert response.status_code == 200
    payload = response.json()
    assert payload["defaultBundleName"]
    assert payload["savedState"]["source"] == "bundle"
    assert payload["savedState"]["bundleName"] == "saved_bundle_v1"
    assert any(item["name"] == "supervised_dry_run" for item in payload["datasets"])
    assert payload["activeRun"] is None


def test_chat_review_routes_list_and_approve_candidate(tmp_path, monkeypatch):
    monkeypatch.setattr(chat_review_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(supervised_control_service, "PROJECT_ROOT", tmp_path)

    capture_service = ChatDatasetCaptureService(project_root=tmp_path)
    candidate = capture_service.capture_candidate(
        mode="chat",
        session_id="session-live",
        source_log_path=str(tmp_path / "log_info" / "conversation_session-live.jsonl"),
        turns=[
            ChatTurnRecord(
                turn_number=1,
                user_message="继续排查网页聊天提交链路",
                assistant_message="我先检查 session_service 里的真实提交路径。",
                tool_calls=["read_file_tool"],
                tool_call_count=1,
            ),
            ChatTurnRecord(
                turn_number=2,
                user_message="把根因和下一步说清楚",
                assistant_message="结论：网页聊天每轮都会重建 agent。下一步：把持久化消息重建成 turn 记录并接入审核。",
                tool_calls=["apply_patch_tool"],
                tool_call_count=1,
                had_explicit_conclusion=True,
                had_next_action=True,
            ),
        ],
    )

    assert candidate is not None

    queue_response = client.get("/api/evolution/chat-review")
    assert queue_response.status_code == 200
    queue_payload = queue_response.json()
    assert queue_payload["pendingCount"] == 1
    assert queue_payload["positiveCount"] == 0
    assert queue_payload["negativeCount"] == 0
    assert queue_payload["discardCount"] == 0
    assert queue_payload["countsByStatus"] == {
        "pending": 1,
        "positive": 0,
        "negative": 0,
        "discard": 0,
    }
    assert queue_payload["lifecycle"]["rawChatDirectTrainingAllowed"] is False
    assert queue_payload["lifecycle"]["candidateStage"] == "pending_review"
    assert queue_payload["lifecycle"]["reviewedCaseStage"] == "reviewed_chat_case"
    assert queue_payload["lifecycle"]["datasetTarget"] == "chat_reviewed_multiturn"
    assert queue_payload["lifecycle"]["negativeTarget"] == "chat_negative_multiturn"
    assert "supervised_evaluation" in queue_payload["lifecycle"]["allowedDownstreamUses"]
    candidate_id = queue_payload["items"][0]["candidateId"]

    decision_response = client.post(
        f"/api/evolution/chat-review/{candidate_id}/decision",
        json={
            "decision": "negative",
            "reviewerNote": "keep as an anti-pattern",
            "reasonCode": "missing_evidence",
            "errorType": "ungrounded_inference",
            "correctPrinciple": "inspect logs before concluding",
        },
    )

    assert decision_response.status_code == 200
    decision_payload = decision_response.json()
    assert decision_payload["status"] == "negative"

    paths = resolve_chat_dataset_paths(project_root=tmp_path)
    assert paths.negative_jsonl_path.exists()

    workbench_response = client.get("/api/evolution/workbench")
    assert workbench_response.status_code == 200
    dataset_entry = next(
        item for item in workbench_response.json()["datasets"] if item["name"] == "chat_reviewed_multiturn"
    )
    assert dataset_entry["available"] is True
    assert dataset_entry["reviewRequired"] is True
    assert dataset_entry["sourceTrack"] == "dialogue"
    assert dataset_entry["holdoutAllowed"] is False
    assert dataset_entry["rawChatDirectTrainingAllowed"] is False
    assert "gym_candidate_case" in dataset_entry["allowedDownstreamUses"]


def test_workbench_dataset_list_backfills_new_builtin_datasets(tmp_path, monkeypatch):
    registry_path = tmp_path / "workspace" / "evaluation" / "datasets" / "registry.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        json.dumps(
            {
                "version": 1,
                "datasets": [
                    {
                        "name": "custom_prompt_jsonl",
                        "kind": "prompt_jsonl",
                        "bundle_name": "custom_prompt_jsonl_v1",
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)

    response = client.get("/api/evolution/workbench")

    assert response.status_code == 200
    rows = response.json()["datasets"]
    assert any(item["name"] == "generated_cases" for item in rows)
    chat_row = next(item for item in rows if item["name"] == "chat_reviewed_multiturn")
    assert chat_row["reviewRequired"] is True
    assert chat_row["sourceTrack"] == "dialogue"
    assert chat_row["holdoutAllowed"] is False


def test_start_supervised_run_from_dataset_exposes_active_snapshot_and_sse(tmp_path, monkeypatch):
    dataset_path = tmp_path / "workspace" / "evaluation" / "datasets" / "custom_prompt_tasks.jsonl"
    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    dataset_path.write_text(
        json.dumps({"case_id": "case_1", "prompt": "fix bug"}) + "\n",
        encoding="utf-8",
    )
    _reset_supervised_live_state()
    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(supervised_control_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        supervised_control_service._RUN_EXECUTOR,
        "submit",
        lambda fn, *args, **kwargs: object(),
    )

    response = client.post(
        "/api/evolution/runs",
        json={
            "sourceKind": "dataset",
            "datasetName": "custom_prompt_jsonl",
            "datasetLimit": 2,
            "keepWorktree": True,
        },
    )
    active_response = client.get("/api/evolution/active-run")
    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["sourceKind"] == "dataset"
    assert payload["datasetName"] == "custom_prompt_jsonl"
    assert payload["bundleName"] == "custom_prompt_jsonl_v1"
    assert payload["keepWorktree"] is True

    assert active_response.status_code == 200
    assert active_response.json()["runId"] == payload["runId"]

    stream = supervised_control_service.stream_active_supervised_run_events(
        initial_snapshot=active_response.json()
    )
    raw_event = next(stream)
    stream.close()

    class _SingleEventResponse:
        def iter_lines(self):
            for line in str(raw_event).splitlines():
                yield line
            yield ""

    event = _read_first_sse_event(_SingleEventResponse())
    event_payload = json.loads(event["data"])
    assert event["event"] == "supervised_run"
    assert event_payload["snapshot"]["runId"] == payload["runId"]
    assert event_payload["snapshot"]["status"] == "queued"

    state_path = tmp_path / "workspace" / "supervised_evolution" / "workbench_state.json"
    bundle_path = tmp_path / "workspace" / "evaluation" / "bundles" / "custom_prompt_jsonl_v1.json"
    assert state_path.exists()
    assert bundle_path.exists()

    _reset_supervised_live_state()


def test_start_supervised_run_from_web_does_not_write_real_runtime_manager_store(tmp_path, monkeypatch):
    bundle_path = tmp_path / "workspace" / "evaluation" / "bundles" / "manual_bundle.json"
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text(
        json.dumps({"bundle_name": "manual_bundle", "cases": [{"case_id": "case_1"}]}),
        encoding="utf-8",
    )
    _reset_supervised_live_state()
    monkeypatch.setattr(supervised_control_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        supervised_control_service._RUN_EXECUTOR,
        "submit",
        lambda fn, *args, **kwargs: object(),
    )

    response = client.post(
        "/api/evolution/runs",
        json={
            "sourceKind": "bundle",
            "bundleName": "manual_bundle",
            "keepWorktree": False,
        },
    )
    assert response.status_code == 202
    run_id = response.json()["runId"]
    run_path, index_path = _real_runtime_manager_evolution_paths("supervised", run_id)
    original_index_text = _read_optional_text(index_path)

    try:
        active_response = client.get("/api/evolution/active-run")

        assert active_response.status_code == 200
        assert active_response.json()["runId"] == run_id
        assert not run_path.exists()
        current_index_text = _read_optional_text(index_path)
        assert current_index_text is None or run_id not in current_index_text
    finally:
        _restore_real_runtime_index_if_touched("supervised", run_id, original_index_text)
        _reset_supervised_live_state()


def test_start_supervised_run_rejects_second_active_run(tmp_path, monkeypatch):
    bundle_path = tmp_path / "workspace" / "evaluation" / "bundles" / "manual_bundle.json"
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text(json.dumps({"bundle_name": "manual_bundle", "cases": [{"case_id": "case_1"}]}), encoding="utf-8")
    _reset_supervised_live_state()
    monkeypatch.setattr(supervised_control_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        supervised_control_service._RUN_EXECUTOR,
        "submit",
        lambda fn, *args, **kwargs: object(),
    )

    first = client.post(
        "/api/evolution/runs",
        json={
            "sourceKind": "bundle",
            "bundleName": "manual_bundle",
            "keepWorktree": False,
        },
    )
    second = client.post(
        "/api/evolution/runs",
        json={
            "sourceKind": "bundle",
            "bundleName": "manual_bundle",
            "keepWorktree": False,
        },
    )

    assert first.status_code == 202
    assert second.status_code == 409

    _reset_supervised_live_state()


def test_start_supervised_run_rejects_when_self_evolution_lease_active(tmp_path, monkeypatch):
    bundle_path = tmp_path / "workspace" / "evaluation" / "bundles" / "manual_bundle.json"
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text(json.dumps({"bundle_name": "manual_bundle", "cases": [{"case_id": "case_1"}]}), encoding="utf-8")
    _reset_supervised_live_state()
    _reset_self_evolution_live_state()
    monkeypatch.setattr(supervised_control_service, "PROJECT_ROOT", tmp_path)
    self_snapshot = {
        "runId": "web-self-active-lease",
        "runKind": "self_evolution_run",
        "status": "running",
        "leases": ["evolution_transaction", "worktree_write", "memory_write"],
        "startedAt": "2026-05-21T00:00:00",
        "updatedAt": "2026-05-21T00:00:00",
    }
    self_evolution_control_service.persist_manager_run_snapshot("self", self_snapshot, active_run_id=self_snapshot["runId"])

    response = client.post(
        "/api/evolution/runs",
        json={
            "sourceKind": "bundle",
            "bundleName": "manual_bundle",
            "keepWorktree": False,
        },
    )

    assert response.status_code == 409
    assert "resource" in response.json()["detail"].lower() or "资源" in response.json()["detail"]

    _reset_supervised_live_state()
    _reset_self_evolution_live_state()


def test_supervised_run_control_routes_pause_resume_and_terminate(tmp_path, monkeypatch):
    bundle_path = tmp_path / "workspace" / "evaluation" / "bundles" / "manual_bundle.json"
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text(json.dumps({"bundle_name": "manual_bundle", "cases": [{"case_id": "case_1"}]}), encoding="utf-8")
    _reset_supervised_live_state()
    monkeypatch.setattr(supervised_control_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        supervised_control_service._RUN_EXECUTOR,
        "submit",
        lambda fn, *args, **kwargs: object(),
    )

    start_response = client.post(
        "/api/evolution/runs",
        json={
            "sourceKind": "bundle",
            "bundleName": "manual_bundle",
            "keepWorktree": False,
        },
    )
    run_id = start_response.json()["runId"]

    pause_response = client.post(f"/api/evolution/runs/{run_id}/pause")
    active_after_pause = client.get("/api/evolution/active-run")
    blocked_start = client.post(
        "/api/evolution/runs",
        json={
            "sourceKind": "bundle",
            "bundleName": "manual_bundle",
            "keepWorktree": False,
        },
    )
    resume_response = client.post(f"/api/evolution/runs/{run_id}/resume")
    terminate_response = client.post(f"/api/evolution/runs/{run_id}/terminate")
    active_after_terminate = client.get("/api/evolution/active-run")

    assert start_response.status_code == 202
    assert pause_response.status_code == 200
    assert pause_response.json()["status"] == "paused"
    assert pause_response.json()["pauseRequested"] is True
    assert active_after_pause.status_code == 200
    assert active_after_pause.json()["status"] == "paused"
    assert blocked_start.status_code == 409
    assert resume_response.status_code == 200
    assert resume_response.json()["status"] == "queued"
    assert resume_response.json()["pauseRequested"] is False
    assert terminate_response.status_code == 200
    assert terminate_response.json()["status"] == "cancelled"
    assert terminate_response.json()["stopRequested"] is True
    assert active_after_terminate.status_code == 200
    assert active_after_terminate.json() is None

    _reset_supervised_live_state()


def test_supervised_run_delete_route_clears_queued_run_and_unlocks_start(tmp_path, monkeypatch):
    bundle_path = tmp_path / "workspace" / "evaluation" / "bundles" / "manual_bundle.json"
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text(json.dumps({"bundle_name": "manual_bundle", "cases": [{"case_id": "case_1"}]}), encoding="utf-8")
    _reset_supervised_live_state()
    monkeypatch.setattr(supervised_control_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        supervised_control_service._RUN_EXECUTOR,
        "submit",
        lambda fn, *args, **kwargs: object(),
    )

    start_response = client.post(
        "/api/evolution/runs",
        json={
            "sourceKind": "bundle",
            "bundleName": "manual_bundle",
            "keepWorktree": False,
        },
    )
    run_id = start_response.json()["runId"]

    delete_response = client.delete(f"/api/evolution/runs/{run_id}")
    active_after_delete = client.get("/api/evolution/active-run")
    restart_response = client.post(
        "/api/evolution/runs",
        json={
            "sourceKind": "bundle",
            "bundleName": "manual_bundle",
            "keepWorktree": False,
        },
    )

    assert start_response.status_code == 202
    assert delete_response.status_code == 200, delete_response.json()
    assert delete_response.json()["deleted"] is True
    assert delete_response.json()["clearedActive"] is True
    assert active_after_delete.status_code == 200
    assert active_after_delete.json() is None
    assert restart_response.status_code == 202
    assert restart_response.json()["runId"] != run_id

    _reset_supervised_live_state()


def test_supervised_run_delete_route_rejects_running_run():
    _reset_supervised_live_state()
    context = {
        "runId": "web-supervised-running-delete",
        "lang": "en",
        "sourceKind": "bundle",
        "datasetName": "",
        "datasetLimit": None,
        "bundleName": "manual_bundle",
        "keepWorktree": False,
        "startedAt": "2026-05-18T12:00:00Z",
    }
    state = supervised_control_service._initial_run_state(context)
    state["status"] = "running"
    state["currentPhase"] = "running"
    state["runtimeStatus"] = "running"
    with supervised_control_service._RUN_STATE_LOCK:
        supervised_control_service._RUN_STATES[context["runId"]] = state
        supervised_control_service._RUN_CONTROLLERS[context["runId"]] = supervised_control_service._SupervisedRunController()
        supervised_control_service._ACTIVE_RUN_ID = context["runId"]
    supervised_control_service.persist_manager_run_snapshot("supervised", state, active_run_id=context["runId"])

    response = client.delete(f"/api/evolution/runs/{context['runId']}")

    assert response.status_code == 409
    assert "Terminate" in response.json()["detail"] or "终止" in response.json()["detail"]

    _reset_supervised_live_state()


def test_supervised_run_action_route_executes_and_respects_active_lock(tmp_path, monkeypatch):
    pending_result = run_gym_collection_episode(
        collection_id="foundation_local_stability",
        project_root=tmp_path,
        adapter=RunnerFakeAdapter(),
        episode_id="web_action_episode",
    )
    _write_supervised_decision_record(
        tmp_path,
        "web_action_run",
        {
            "decision": "PROMOTE",
            "reason": "候选方案进入 proposal 流程。",
            "gates": [
                {
                    "name": "gym_promotion",
                    "status": "pass",
                    "reason": "proposal created",
                    "metrics": {
                        "promotion_proposal_path": pending_result.promotion_proposal_path,
                        "decision_path": pending_result.decision_path,
                    },
                }
            ],
        },
    )

    _reset_supervised_live_state()
    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(supervised_control_service, "PROJECT_ROOT", tmp_path)

    apply_response = client.post(
        "/api/evolution/runs/web_action_run/actions",
        json={"action": "apply"},
    )

    assert apply_response.status_code == 200
    payload = apply_response.json()
    assert payload["action"] == "apply"
    assert payload["run"]["proposalStatus"] == "applied"
    assert payload["lifecycle"]["status"] == "applied"

    bundle_path = tmp_path / "workspace" / "evaluation" / "bundles" / "manual_bundle.json"
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text(json.dumps({"bundle_name": "manual_bundle", "cases": [{"case_id": "case_1"}]}), encoding="utf-8")
    monkeypatch.setattr(
        supervised_control_service._RUN_EXECUTOR,
        "submit",
        lambda fn, *args, **kwargs: object(),
    )
    start_response = client.post(
        "/api/evolution/runs",
        json={
            "sourceKind": "bundle",
            "bundleName": "manual_bundle",
            "keepWorktree": False,
        },
    )
    blocked_response = client.post(
        "/api/evolution/runs/web_action_run/actions",
        json={"action": "activate"},
    )

    assert start_response.status_code == 202
    assert blocked_response.status_code == 409

    _reset_supervised_live_state()


def test_evolution_proposal_detail_route_exposes_review_first_payload(tmp_path, monkeypatch):
    seeded = _seed_supervised_proposal_record(tmp_path, "proposal_detail_run", status="proposed")
    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)

    response = client.get("/api/evolution/proposals/proposal_detail_run")

    assert response.status_code == 200
    payload = response.json()
    assert payload["sessionId"] == "proposal_detail_run"
    assert payload["proposalStatus"] == "proposed"
    assert payload["canDelete"] is True
    assert payload["review"]["headline"]
    assert payload["review"]["changeSummary"]
    assert payload["review"]["whatChanged"]
    assert payload["review"]["whyCreated"]
    assert payload["proposal"]["proposalId"]
    assert payload["proposal"]["improvementType"]
    assert payload["proposal"]["expectedEffect"]
    assert payload["paths"]["gymProposalPath"] == str(seeded["proposal_path"])
    assert payload["rawProposal"]["status"] == "proposed"
    assert payload["rawGymDecision"]["candidate_improvement"]["improvement_id"]


def test_evolution_runs_route_exposes_run_delete_state(tmp_path, monkeypatch):
    _seed_supervised_proposal_record(tmp_path, "run_delete_missing", status="missing")
    _seed_supervised_proposal_record(tmp_path, "run_delete_active", status="active")
    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)

    response = client.get("/api/evolution/runs")

    assert response.status_code == 200
    payload = {item["id"]: item for item in response.json()}
    assert payload["run_delete_missing"]["canDelete"] is True
    assert payload["run_delete_missing"]["deleteBlockReason"] == ""
    assert payload["run_delete_active"]["canDelete"] is False
    assert payload["run_delete_active"]["deleteBlockReason"]


@pytest.mark.parametrize("status", ["proposed", "rolled_back", "missing", "superseded"])
def test_evolution_delete_proposal_allows_removable_states(tmp_path, monkeypatch, status):
    session_id = f"delete_{status}"
    seeded = _seed_supervised_proposal_record(tmp_path, session_id, status=status)
    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)

    response = client.delete(f"/api/evolution/proposals/{session_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["deleted"] is True
    assert not seeded["decision_path"].exists()
    assert not seeded["proposal_path"].exists()

    runs_payload = client.get("/api/evolution/runs").json()
    library_payload = client.get("/api/evolution/library").json()
    visible_source_runs = {item["sourceRun"] for item in library_payload["items"] + library_payload["pending"]}

    assert all(run["id"] != session_id for run in runs_payload)
    assert session_id not in visible_source_runs


@pytest.mark.parametrize("status", ["applied", "active"])
def test_evolution_delete_proposal_blocks_live_states(tmp_path, monkeypatch, status):
    session_id = f"blocked_{status}"
    seeded = _seed_supervised_proposal_record(tmp_path, session_id, status=status)
    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)

    response = client.delete(f"/api/evolution/proposals/{session_id}")
    detail_response = client.get(f"/api/evolution/proposals/{session_id}")

    assert response.status_code == 409
    assert detail_response.status_code == 200
    assert detail_response.json()["canDelete"] is False
    assert seeded["decision_path"].exists()
    assert seeded["proposal_path"].exists()


def test_evolution_bulk_delete_proposals_reports_mixed_results(tmp_path, monkeypatch):
    proposed = _seed_supervised_proposal_record(tmp_path, "bulk_delete_proposed", status="proposed")
    missing = _seed_supervised_proposal_record(tmp_path, "bulk_delete_missing", status="missing")
    active = _seed_supervised_proposal_record(tmp_path, "bulk_delete_active", status="active")
    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)

    response = client.post(
        "/api/evolution/proposals/delete",
        json={
            "sessionIds": [
                "bulk_delete_proposed",
                "bulk_delete_missing",
                "bulk_delete_active",
            ]
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["deletedCount"] == 2
    assert payload["skippedCount"] == 1
    assert payload["errorCount"] == 0
    result_status = {item["sessionId"]: item["status"] for item in payload["results"]}
    assert result_status["bulk_delete_proposed"] == "deleted"
    assert result_status["bulk_delete_missing"] == "deleted"
    assert result_status["bulk_delete_active"] == "skipped"
    assert not proposed["decision_path"].exists()
    assert not missing["decision_path"].exists()
    assert active["decision_path"].exists()
    assert active["proposal_path"].exists()

    runs_payload = client.get("/api/evolution/runs").json()
    run_ids = {item["id"] for item in runs_payload}
    assert "bulk_delete_proposed" not in run_ids
    assert "bulk_delete_missing" not in run_ids
    assert "bulk_delete_active" in run_ids


def test_self_evolution_routes_expose_read_only_evidence(monkeypatch):
    monkeypatch.setattr(self_evolution_service, "get_web_language", lambda: "zh")
    monkeypatch.setattr(
        self_evolution_service,
        "get_workbench_contract",
        lambda: {
            "defaultMode": "self_evolution",
            "defaultRoute": "/evolution",
            "intakeMode": "manual_review",
            "modeAvailability": {
                "chat": True,
                "self_evolution": True,
                "supervised_evolution": True,
            },
            "domainAvailability": {
                "chat": True,
                "evolution": True,
                "config": True,
            },
        },
    )
    monkeypatch.setattr(
        self_evolution_service,
        "build_self_evolution_snapshot",
        lambda project_root=None, transaction_limit=6, recent_limit=4: {
            "goal": "开始自主进化",
            "advisory": {
                "active_count": 1,
                "entries": [
                    {
                        "target_key": "target:a",
                        "target_label": "local_transaction_closing_v1",
                        "proposal_id": "proposal-1",
                        "episode_id": "episode-1",
                        "candidate_improvement_id": "cand-1",
                        "activated_at": "2026-05-18T12:00:00Z",
                        "runtime_effect": "not_applied",
                        "agent_consumption": "advisory",
                        "proposal_path": "workspace/gym/proposal-1.json",
                        "decision_path": "workspace/gym/decision-1.json",
                        "trace_index_path": "workspace/gym/trace-1.json",
                    }
                ],
            },
            "git_status": {
                "summary": json.dumps(
                    {
                        "dirty_summary": "有 unstaged 改动，共 1 个变化文件",
                        "modified_paths": ["core/evaluation/self_evolution_workbench.py"],
                        "modified_entities": [],
                        "last_validation_summary": "ruff lint 通过",
                        "recent_changes": [
                            {
                                "path": "core/evaluation/self_evolution_workbench.py",
                                "change_type": "modified",
                                "subject": "refine self evidence",
                            }
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                "lines": [
                    "{",
                    '  "dirty_summary": "有 unstaged 改动，共 1 个变化文件",',
                    '  "modified_paths": ["core/evaluation/self_evolution_workbench.py"],',
                ],
            },
            "recent_changes": [
                {
                    "path": "core/evaluation/self_evolution_workbench.py",
                    "change_type": "M",
                    "summary": "refine self evidence",
                }
            ],
            "fitness": {
                "transactions": {
                    "opened": 2,
                    "closed": 2,
                    "successful": 1,
                    "failed": 1,
                    "success_rate": 0.5,
                    "recent": [
                        {
                            "txn_id": "txn-1",
                            "status": "failed",
                            "validation_passed": 1,
                            "validation_failed": 1,
                            "mutations_recorded": 2,
                        }
                    ],
                },
                "validation": {"passed": 2, "failed": 1, "pass_rate": 0.66},
                "mutations": {"recorded": 3, "successful": 1, "failed": 1, "blocked": 1},
            },
            "worktree": {
                "available": True,
                "error": "",
                "snapshot_id": "snap-1",
                "created_at": "2026-05-18T12:00:00Z",
                "base_rev": "abcdef1234567890",
                "has_staged": False,
                "has_unstaged": True,
                "has_untracked": False,
                "is_dirty": True,
                "dirty_file_count": 1,
                "files": [
                    {
                        "path": "core/evaluation/self_evolution_workbench.py",
                        "status": "M",
                        "staged": False,
                        "unstaged": True,
                        "untracked": False,
                        "deleted": False,
                    }
                ],
            },
            "recent_transactions": [
                {
                    "txn_id": "txn-1",
                    "opened_at": "2026-05-18T11:55:00Z",
                    "closed_at": "2026-05-18T12:00:00Z",
                    "base_rev": "abcdef1234567890",
                    "base_rev_short": "abcdef123456",
                    "status": "failed",
                    "summary": "touch self loop",
                    "is_open": False,
                }
            ],
        },
    )
    monkeypatch.setattr(
        self_evolution_service,
        "list_recent_self_evolution_transaction_payloads",
        lambda project_root, limit=24: [
            {
                "txn_id": "txn-1",
                "opened_at": "2026-05-18T11:55:00Z",
                "closed_at": "2026-05-18T12:00:00Z",
                "base_rev": "abcdef1234567890",
                "base_rev_short": "abcdef123456",
                "status": "failed",
                "summary": "touch self loop",
                "is_open": False,
            }
        ],
    )
    monkeypatch.setattr(
        self_evolution_service,
        "load_self_evolution_audit_records",
        lambda project_root, limit=6: [
            {
                "timestamp": "2026-05-18T12:00:00Z",
                "event": "validation_completed",
                "txn_id": "txn-1",
                "status": "",
                "kind": "pytest",
                "message": "1 failed",
                "tool_name": "",
                "target_paths": ["tests/test_self_evolution_workbench.py"],
                "passed": False,
                "base_rev": "abcdef1234567890",
                "summary": "2026-05-18T12:00:00Z validation_completed txn-1 kind=pytest passed=False message=1 failed",
            }
        ],
    )

    overview_response = client.get("/api/evolution/self/overview")
    transactions_response = client.get("/api/evolution/self/transactions")
    audit_response = client.get("/api/evolution/self/audit")

    assert overview_response.status_code == 200
    assert transactions_response.status_code == 200
    assert audit_response.status_code == 200

    overview_payload = overview_response.json()
    assert overview_payload["enabled"] is True
    assert overview_payload["readiness"]["state"] == "caution"
    assert overview_payload["advisory"]["activeCount"] == 1
    assert overview_payload["metrics"]["dirtyFiles"] == 1
    assert overview_payload["gitStatus"]["summary"] == "有 unstaged 改动，共 1 个变化文件"
    assert overview_payload["gitStatus"]["lines"][1] == "最近验证: ruff lint 通过"
    assert overview_payload["worktree"]["snapshotId"] == "snap-1"
    assert overview_payload["sceneSemantics"]["sceneState"] == "caution"
    assert overview_payload["runSemantics"]["runStatus"] == "failed"
    assert overview_payload["actionStates"]["start"]["enabled"] is True
    assert overview_payload["recentTransactions"][0]["txnId"] == "txn-1"
    assert overview_payload["auditTail"][0]["event"] == "validation_completed"
    assert transactions_response.json()[0]["baseRevShort"] == "abcdef123456"
    assert audit_response.json()[0]["summary"].startswith("2026-05-18T12:00:00Z")


def test_start_self_evolution_run_from_web_exposes_active_snapshot(monkeypatch):
    _reset_self_evolution_live_state()
    monkeypatch.setattr(
        self_evolution_control_service,
        "get_workbench_contract",
        lambda: {
            "defaultMode": "self_evolution",
            "defaultRoute": "/evolution",
            "intakeMode": "manual_review",
            "modeAvailability": {
                "chat": True,
                "self_evolution": True,
                "supervised_evolution": True,
            },
            "domainAvailability": {
                "chat": True,
                "evolution": True,
                "config": True,
            },
        },
    )
    monkeypatch.setattr(self_evolution_control_service, "has_running_sessions", lambda: False)
    monkeypatch.setattr(self_evolution_control_service, "get_active_supervised_run", lambda: None)
    monkeypatch.setattr(
        self_evolution_control_service._RUN_EXECUTOR,
        "submit",
        lambda fn, *args, **kwargs: object(),
    )

    response = client.post("/api/evolution/self/runs", json={"goal": "网页触发一轮自进化"})
    active_response = client.get("/api/evolution/self/active-run")

    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["goal"] == "网页触发一轮自进化"
    assert payload["runId"].startswith("web-self-")
    assert payload["runSemantics"]["runStatus"] == "queued"
    assert payload["actionStates"]["pause"]["enabled"] is True

    assert active_response.status_code == 200
    active_payload = active_response.json()
    assert active_payload["runId"] == payload["runId"]
    assert active_payload["status"] == "queued"
    assert active_payload["actionStates"]["resume"]["enabled"] is False

    _reset_self_evolution_live_state()


def test_start_self_evolution_run_from_web_does_not_write_real_runtime_manager_store(monkeypatch):
    _reset_self_evolution_live_state()
    monkeypatch.setattr(
        self_evolution_control_service,
        "get_workbench_contract",
        lambda: {
            "defaultMode": "self_evolution",
            "defaultRoute": "/evolution",
            "intakeMode": "manual_review",
            "modeAvailability": {
                "chat": True,
                "self_evolution": True,
                "supervised_evolution": True,
            },
            "domainAvailability": {
                "chat": True,
                "evolution": True,
                "config": True,
            },
        },
    )
    monkeypatch.setattr(self_evolution_control_service, "has_running_sessions", lambda: False)
    monkeypatch.setattr(self_evolution_control_service, "get_active_supervised_run", lambda: None)
    monkeypatch.setattr(
        self_evolution_control_service._RUN_EXECUTOR,
        "submit",
        lambda fn, *args, **kwargs: object(),
    )

    response = client.post("/api/evolution/self/runs", json={"goal": "隔离真实 runtime store"})
    assert response.status_code == 202
    run_id = response.json()["runId"]
    run_path, index_path = _real_runtime_manager_evolution_paths("self", run_id)
    original_index_text = _read_optional_text(index_path)

    try:
        active_response = client.get("/api/evolution/self/active-run")

        assert active_response.status_code == 200
        assert active_response.json()["runId"] == run_id
        assert not run_path.exists()
        current_index_text = _read_optional_text(index_path)
        assert current_index_text is None or run_id not in current_index_text
    finally:
        _restore_real_runtime_index_if_touched("self", run_id, original_index_text)
        _reset_self_evolution_live_state()


def test_start_self_evolution_run_allows_readonly_chat_but_blocks_write_chat(monkeypatch):
    _reset_self_evolution_live_state()
    monkeypatch.setattr(
        self_evolution_control_service,
        "get_workbench_contract",
        lambda: {
            "defaultMode": "self_evolution",
            "defaultRoute": "/evolution",
            "intakeMode": "manual_review",
            "modeAvailability": {
                "chat": True,
                "self_evolution": True,
                "supervised_evolution": True,
            },
            "domainAvailability": {
                "chat": True,
                "evolution": True,
                "config": True,
            },
        },
    )
    monkeypatch.setattr(self_evolution_control_service, "get_active_supervised_run", lambda: None)
    monkeypatch.setattr(
        self_evolution_control_service._RUN_EXECUTOR,
        "submit",
        lambda fn, *args, **kwargs: object(),
    )

    session_service._set_session_running("session-readonly", True, turn_id="chat-turn-readonly", leases=["readonly_chat"])
    try:
        response = client.post("/api/evolution/self/runs", json={"goal": "允许只读 chat 并行"})
    finally:
        session_service._set_session_running("session-readonly", False, turn_id="chat-turn-readonly")

    assert response.status_code == 202
    _reset_self_evolution_live_state()

    session_service._set_session_running("session-write", True, turn_id="chat-turn-write", leases=["worktree_write"])
    try:
        blocked = client.post("/api/evolution/self/runs", json={"goal": "阻止写入型 chat 并行"})
    finally:
        session_service._set_session_running("session-write", False, turn_id="chat-turn-write")

    assert blocked.status_code == 409
    assert "写入" in blocked.json()["detail"] or "write" in blocked.json()["detail"].lower()

    _reset_self_evolution_live_state()


def test_start_self_evolution_run_rejects_when_supervised_run_active(monkeypatch):
    _reset_self_evolution_live_state()
    monkeypatch.setattr(
        self_evolution_control_service,
        "get_workbench_contract",
        lambda: {
            "defaultMode": "self_evolution",
            "defaultRoute": "/evolution",
            "intakeMode": "manual_review",
            "modeAvailability": {
                "chat": True,
                "self_evolution": True,
                "supervised_evolution": True,
            },
            "domainAvailability": {
                "chat": True,
                "evolution": True,
                "config": True,
            },
        },
    )
    monkeypatch.setattr(self_evolution_control_service, "has_running_sessions", lambda: False)
    monkeypatch.setattr(
        self_evolution_control_service,
        "get_active_supervised_run",
        lambda: {"runId": "supervised-1", "status": "running"},
    )

    response = client.post("/api/evolution/self/runs", json={"goal": "blocked"})

    assert response.status_code == 409
    assert "监督任务" in response.json()["detail"]

    _reset_self_evolution_live_state()


def test_self_evolution_routes_hide_data_when_mode_disabled(monkeypatch):
    monkeypatch.setattr(
        self_evolution_service,
        "get_workbench_contract",
        lambda: {
            "defaultMode": "supervised_evolution",
            "defaultRoute": "/evolution",
            "intakeMode": "manual_review",
            "modeAvailability": {
                "chat": True,
                "self_evolution": False,
                "supervised_evolution": True,
            },
            "domainAvailability": {
                "chat": True,
                "evolution": True,
                "config": True,
            },
        },
    )

    overview_response = client.get("/api/evolution/self/overview")
    transactions_response = client.get("/api/evolution/self/transactions")
    audit_response = client.get("/api/evolution/self/audit")

    assert overview_response.status_code == 200
    assert transactions_response.status_code == 200
    assert audit_response.status_code == 200
    assert overview_response.json()["enabled"] is False
    assert overview_response.json()["readiness"]["state"] == "disabled"
    assert transactions_response.json() == []
    assert audit_response.json() == []


def _seed_self_evolution_history(project_root: Path) -> Path:
    workspace_dir = project_root / "workspace"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    db_path = workspace_dir / "agent_brain.db"
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            """
            CREATE TABLE EvolutionTransaction (
                txn_id TEXT PRIMARY KEY,
                opened_at TEXT,
                closed_at TEXT,
                base_rev TEXT,
                status TEXT,
                summary TEXT
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO EvolutionTransaction (txn_id, opened_at, closed_at, base_rev, status, summary)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                ("txn-delete-a", "2026-05-18T11:00:00Z", "2026-05-18T11:10:00Z", "aaaabbbbcccc", "done", "delete me"),
                ("txn-keep-b", "2026-05-18T12:00:00Z", "2026-05-18T12:10:00Z", "ddddeeeeffff", "failed", "keep me"),
                ("txn-open-c", "2026-05-18T13:00:00Z", None, "gggghhhhiiii", "running", "still open"),
            ],
        )
        conn.commit()

    audit_dir = workspace_dir / "evolution"
    audit_dir.mkdir(parents=True, exist_ok=True)
    audit_path = audit_dir / "audit.jsonl"
    audit_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-05-18T11:05:00Z",
                        "event": "validation_completed",
                        "txn_id": "txn-delete-a",
                        "summary": "delete audit",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "timestamp": "2026-05-18T12:05:00Z",
                        "event": "validation_completed",
                        "txn_id": "txn-keep-b",
                        "summary": "keep audit",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "timestamp": "2026-05-18T12:06:00Z",
                        "event": "system_note",
                        "txn_id": "",
                        "summary": "ungrouped audit",
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return audit_path


def test_self_evolution_history_delete_removes_transaction_groups_and_linked_audit(tmp_path, monkeypatch):
    audit_path = _seed_self_evolution_history(tmp_path)
    monkeypatch.setattr(self_evolution_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        self_evolution_service,
        "get_workbench_contract",
        lambda: {
            "modeAvailability": {
                "chat": True,
                "self_evolution": True,
                "supervised_evolution": True,
            }
        },
    )
    monkeypatch.setattr(self_evolution_service, "get_web_language", lambda: "zh")

    response = client.post(
        "/api/evolution/self/history/delete",
        json={"txnIds": ["txn-delete-a"]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["deletedGroupCount"] == 1
    assert payload["deletedAuditCount"] == 1
    assert payload["deletedTxnIds"] == ["txn-delete-a"]

    transactions_response = client.get("/api/evolution/self/transactions")
    remaining_txn_ids = {item["txnId"] for item in transactions_response.json()}
    assert "txn-delete-a" not in remaining_txn_ids
    assert "txn-keep-b" in remaining_txn_ids

    audit_response = client.get("/api/evolution/self/audit")
    audit_txn_ids = [item["txnId"] for item in audit_response.json()]
    assert "txn-delete-a" not in audit_txn_ids
    assert "txn-keep-b" in audit_txn_ids
    assert "" in audit_txn_ids
    assert "txn-delete-a" not in audit_path.read_text(encoding="utf-8")


def test_self_evolution_history_delete_blocks_open_transaction_groups(tmp_path, monkeypatch):
    _seed_self_evolution_history(tmp_path)
    monkeypatch.setattr(self_evolution_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        self_evolution_service,
        "get_workbench_contract",
        lambda: {
            "modeAvailability": {
                "chat": True,
                "self_evolution": True,
                "supervised_evolution": True,
            }
        },
    )
    monkeypatch.setattr(self_evolution_service, "get_web_language", lambda: "zh")

    response = client.post(
        "/api/evolution/self/history/delete",
        json={"txnIds": ["txn-open-c"]},
    )

    assert response.status_code == 422
    assert "当前现场" in response.json()["detail"]


def test_pet_summary_shape():
    response = client.get("/api/pet/summary")
    assert response.status_code == 200
    payload = response.json()
    assert payload["name"]
    assert "statusLine" in payload


def test_reset_summary_shape():
    response = client.get("/api/reset/summary")
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "custom"
    assert payload["presets"] == []
    assert payload["items"]
    assert payload["categories"]
    item_ids = {item["id"] for item in payload["items"]}
    assert "chat_history" in item_ids
    assert "web_dist" in item_ids
    protected_paths = {path for group in payload["protected"] for path in group["paths"]}
    assert "workspace/memory/" in protected_paths
    assert "workspace/prompts/" in protected_paths


def _seed_supervised_proposal_record(project_root: Path, session_id: str, *, status: str) -> dict[str, Path]:
    result = run_gym_collection_episode(
        collection_id="foundation_local_stability",
        project_root=project_root,
        adapter=RunnerFakeAdapter(),
        episode_id=f"{session_id}_episode",
    )
    proposal_path = Path(result.promotion_proposal_path)

    activation = None
    if status in {"applied", "active", "rolled_back"}:
        apply_gym_promotion_proposal(result.promotion_proposal_path, project_root=project_root)
    if status == "active":
        activation = activate_gym_promotion_proposal(result.promotion_proposal_path, project_root=project_root)
    elif status == "rolled_back":
        rollback_gym_promotion_proposal(
            result.promotion_proposal_path,
            project_root=project_root,
            reason="manual cleanup for test",
        )
    elif status == "superseded":
        apply_gym_promotion_proposal(result.promotion_proposal_path, project_root=project_root)
        activate_gym_promotion_proposal(result.promotion_proposal_path, project_root=project_root)
        replacement = run_gym_collection_episode(
            collection_id="foundation_local_stability",
            project_root=project_root,
            adapter=RunnerFakeAdapter(),
            episode_id=f"{session_id}_replacement",
        )
        apply_gym_promotion_proposal(replacement.promotion_proposal_path, project_root=project_root)
        activate_gym_promotion_proposal(replacement.promotion_proposal_path, project_root=project_root)
    elif status == "missing":
        proposal_path.unlink()

    advisory_context = None
    if activation is not None:
        advisory_context = {
            "active_count": 1,
            "entries": [
                {
                    "target_key": activation.target_key,
                    "target_label": "local_transaction_closing_v1",
                    "proposal_id": activation.proposal_id,
                    "runtime_effect": activation.runtime_effect,
                    "agent_consumption": activation.agent_consumption,
                }
            ],
        }

    decision_path = _write_supervised_decision_record(
        project_root,
        session_id,
        {
            "decision": "PROMOTE",
            "reason": f"{status} proposal for cleanup review.",
            "gates": [
                {
                    "name": "gym_promotion",
                    "status": "pass",
                    "reason": f"proposal {status}",
                    "metrics": {
                        "promotion_proposal_path": str(proposal_path),
                        "decision_path": result.decision_path,
                    },
                }
            ],
            "advisory_context": advisory_context,
        },
    )
    return {
        "decision_path": decision_path,
        "proposal_path": proposal_path,
    }


def _write_workbench_state(project_root: Path, payload: dict) -> None:
    state_path = project_root / "workspace" / "supervised_evolution" / "workbench_state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_supervised_decision_record(project_root: Path, session_id: str, overrides: dict) -> Path:
    decisions_dir = project_root / "workspace" / "supervised_evolution" / "decisions"
    decisions_dir.mkdir(parents=True, exist_ok=True)
    path = decisions_dir / f"{session_id}.json"
    payload = {
        "session_id": session_id,
        "bundle_name": "demo_bundle",
        "decision": "HOLD",
        "reason": "baseline 与 candidate 持平",
        "ended_at": "2026-05-18T12:00:00Z",
        "baseline_success_rate": 1.0,
        "candidate_success_rate": 1.0,
        "score_delta": 0.0,
        "baseline_summary": {"validation_failed": 0, "total_guarded_tools": 2, "avg_wall_clock_seconds": 1.0},
        "candidate_summary": {"validation_failed": 0, "total_guarded_tools": 2, "avg_wall_clock_seconds": 2.0},
        "case_summaries": [
            {
                "case_id": "case_1",
                "baseline_status": "success",
                "candidate_status": "success",
                "decision_signal": "stable_success",
            }
        ],
        "gates": [],
        "decision_path": str(path),
        "policy_action": {"lineage_index_path": str(project_root / "workspace" / "lineage.json")},
    }
    payload.update(overrides)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _reset_supervised_live_state() -> None:
    with supervised_control_service._RUN_STATE_LOCK:
        supervised_control_service._RUN_STATES.clear()
        supervised_control_service._RUN_CONTROLLERS.clear()
        supervised_control_service._ACTIVE_RUN_ID = None
    with supervised_control_service._RUN_SUBSCRIBERS_LOCK:
        supervised_control_service._RUN_SUBSCRIBERS.clear()


def _reset_self_evolution_live_state() -> None:
    with self_evolution_control_service._RUN_STATE_LOCK:
        self_evolution_control_service._RUN_STATES.clear()
        self_evolution_control_service._ACTIVE_RUN_ID = None
