"""Runtime summary helpers for the web shell."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import threading
import time

from config.public_config import load_public_config
from core.infrastructure.mental_model import get_mental_model
from core.mental_model_flags import is_mental_model_enabled
from core.runtime_manager import ensure_daemon_running, load_runtime_snapshot, submit_command

from .i18n import get_web_language, text_for
from .session_service import get_active_session_detail
from .workbench_contract_service import get_workbench_contract


PROJECT_ROOT = Path(__file__).resolve().parents[3]
RUNTIME_STATE_PATH = PROJECT_ROOT / "workspace" / "ui_runtime_state.json"
LAUNCHER_SCRIPT_PATH = PROJECT_ROOT / "scripts" / "vibelution_launcher.ps1"
LAUNCHER_STATE_PATH = PROJECT_ROOT / ".runtime" / "launcher" / "state.json"
LAUNCHER_SHUTDOWN_LOG_PATH = PROJECT_ROOT / ".runtime" / "launcher" / "shutdown-request.log"
RUNNING_SESSION_PHASES = {"running", "stopping"}


def get_runtime_summary() -> dict:
    """Return a light runtime summary for the global shell."""

    runtime_profile = "safe_local"
    model_ref = "unconfigured"
    lang = get_web_language()
    public_config: dict | None = None
    contract = {
        "defaultMode": "chat",
        "defaultRoute": "/chat",
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
    }
    try:
        public_config = load_public_config()
        contract = get_workbench_contract(public_config)
        runtime_profile = public_config.get("runtime", {}).get("profile", runtime_profile)
        llm_profiles = public_config.get("llm", {}).get("profiles", {})
        primary_profile = llm_profiles.get("primary", {})
        model_ref = primary_profile.get("model_ref") or primary_profile.get("model", model_ref)
    except Exception:
        pass

    active_session = get_active_session_detail() or {}
    runtime_state = _load_runtime_state()
    current_phase = str(active_session.get("currentPhase") or "").strip().lower()
    status = _derive_web_status(current_phase, runtime_state)
    session_state = _derive_session_state(lang, active_session, runtime_state)
    active_tools = _active_tools(active_session, runtime_state)
    context_usage = _context_usage(runtime_state)
    runtime_manager = _load_runtime_manager_snapshot()
    workbench = _workbench_payload(lang, runtime_manager)
    task_summary = (
        active_session.get("taskSummary")
        or text_for(
            lang,
            zh="等待新的任务进入工作台",
            en="Waiting for the next task to enter the workbench",
        )
    )
    session_updated_at = str(
        active_session.get("updatedAt")
        or active_session.get("lastActive")
        or runtime_state.get("updated_at")
        or ""
    ).strip()

    return {
        "status": status,
        "mode": contract["defaultMode"],
        "model": model_ref,
        "profile": runtime_profile,
        "defaultRoute": contract["defaultRoute"],
        "intakeMode": contract["intakeMode"],
        "modeAvailability": contract["modeAvailability"],
        "domainAvailability": contract["domainAvailability"],
        "agentName": "Vibelution",
        "agentStatusLine": _agent_status_line(lang, status, current_phase),
        "sessionTitle": active_session.get("title")
        or text_for(lang, zh="网页工作台 Shell", en="Web workbench shell"),
        "taskSummary": task_summary,
        "currentPhase": current_phase or "idle",
        "sessionState": session_state["state"],
        "sessionStateLine": session_state["line"],
        "sessionNeedsResponse": session_state["needs_response"],
        "sessionToolName": session_state["tool_name"],
        "sessionUpdatedAt": session_updated_at,
        "mentalState": _mental_state_summary(lang, public_config=public_config),
        "contextUsage": context_usage,
        "activeTools": active_tools,
        "changedFilesCount": len(active_session.get("changedFiles") or []),
        "recentAction": _recent_action(lang, active_session, runtime_state),
        "runtimeManager": {
            "running": bool(runtime_manager.get("daemonRunning")),
            "runtimeState": str(runtime_manager.get("runtimeState") or "idle"),
            "managerPid": int(runtime_manager.get("managerPid") or 0),
            "stateVersion": int(runtime_manager.get("stateVersion") or 0),
        },
        "workbench": workbench,
    }


def request_runtime_shutdown() -> dict[str, object]:
    """Request the local workbench backend to stop."""

    lang = get_web_language()
    if _can_use_managed_launcher_shutdown():
        try:
            ensure_daemon_running()
            submit_command(
                "close_workbench",
                args={"reason": "web_close_button"},
                requested_by="web_ui",
            )
            return {
                "accepted": True,
                "mode": "runtime_manager",
                "message": text_for(
                    lang,
                    zh="正在关闭工作台，窗口会在后端停稳后自动关闭。",
                    en="Closing the workbench. The app window will close after the backend stops.",
                ),
            }
        except Exception:
            _spawn_managed_launcher_shutdown()
            return {
                "accepted": True,
                "mode": "managed_fallback",
                "message": text_for(
                    lang,
                    zh="正在关闭工作台，窗口会在后端停稳后自动关闭。",
                    en="Closing the workbench. The app window will close after the backend stops.",
                ),
            }

    _schedule_local_backend_exit()
    return {
        "accepted": True,
        "mode": "local",
        "message": text_for(
            lang,
            zh="正在关闭本地后端服务。",
            en="Shutting down the local backend.",
        ),
    }


def _can_use_managed_launcher_shutdown() -> bool:
    return os.name == "nt" and LAUNCHER_SCRIPT_PATH.exists() and LAUNCHER_STATE_PATH.exists()


def _spawn_managed_launcher_shutdown() -> None:
    LAUNCHER_SHUTDOWN_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    with LAUNCHER_SHUTDOWN_LOG_PATH.open("a", encoding="utf-8") as log_file:
        log_file.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] requesting managed shutdown\n")
        log_file.flush()
        subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(LAUNCHER_SCRIPT_PATH),
                "-Action",
                "stop",
            ],
            cwd=str(PROJECT_ROOT),
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=log_file,
            creationflags=creationflags,
        )


def _schedule_local_backend_exit(delay_seconds: float = 0.35) -> None:
    def _exit_later() -> None:
        time.sleep(max(0.0, float(delay_seconds)))
        os._exit(0)

    thread = threading.Thread(target=_exit_later, name="web-runtime-shutdown", daemon=True)
    thread.start()


def _load_runtime_state() -> dict:
    try:
        payload = json.loads(RUNTIME_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_runtime_manager_snapshot() -> dict:
    try:
        payload = load_runtime_snapshot()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _workbench_payload(lang: str, runtime_manager: dict) -> dict[str, object]:
    workbench = runtime_manager.get("workbench") if isinstance(runtime_manager, dict) else {}
    if not isinstance(workbench, dict):
        workbench = {}

    desired_state = str(workbench.get("desiredState") or "closed").strip() or "closed"
    observed_state = str(workbench.get("observedState") or "closed").strip() or "closed"
    phase = str(workbench.get("phase") or "steady").strip() or "steady"
    failure_message = str(workbench.get("failureMessage") or "").strip()

    if phase == "failed":
        status_line = failure_message or text_for(
            lang,
            zh="工作台生命周期遇到了错误。",
            en="The workbench lifecycle hit an error.",
        )
    elif desired_state == "closed" and observed_state != "closed":
        status_line = text_for(
            lang,
            zh="正在关闭工作台。",
            en="The runtime manager is closing the workbench.",
        )
    elif desired_state == "open" and observed_state != "open":
        status_line = text_for(
            lang,
            zh="正在打开工作台。",
            en="The runtime manager is opening the workbench.",
        )
    elif observed_state == "open":
        status_line = text_for(
            lang,
            zh="工作台正在运行。",
            en="The workbench is running.",
        )
    else:
        status_line = text_for(
            lang,
            zh="工作台已关闭。",
            en="The workbench is closed.",
        )

    return {
        "desiredState": desired_state,
        "observedState": observed_state,
        "phase": phase,
        "backendPid": int(workbench.get("backendPid") or 0),
        "browserWindowPid": int(workbench.get("browserWindowPid") or 0),
        "browserManaged": bool(workbench.get("browserManaged", True)),
        "url": str(workbench.get("url") or "").strip(),
        "lastReason": str(workbench.get("lastReason") or "").strip(),
        "statusLine": status_line,
        "failureMessage": failure_message,
    }


def _derive_web_status(task_status: object, runtime_state: dict) -> str:
    task = str(task_status or "").strip().lower()
    current_status = str(runtime_state.get("status") or "").strip().upper()
    runtime_status = str(runtime_state.get("runtime_status") or "").strip().upper()

    if task == "blocked":
        return "failed"
    if task in {"needs_input", "waiting"}:
        return "waiting"
    if task in {"done", "ready"}:
        return "success"
    if task in {"running", "stopping"}:
        return "running"
    if task in {"planning", "reading", "editing", "verifying"}:
        return "running"
    if current_status == "ERROR" or runtime_status == "ERROR":
        return "failed"
    if current_status == "SUCCESS":
        return "success"
    if current_status in {"THINKING", "PLANNING", "ACTING", "WORKING"}:
        return "running"
    return "idle"


def _agent_status_line(lang: str, status: str, task_status: object) -> str:
    if status == "failed":
        return text_for(lang, zh="当前轮遇到阻塞", en="current pass is blocked")
    if status == "success":
        return text_for(lang, zh="上一轮已经完成", en="latest pass completed")
    if status == "running":
        return text_for(lang, zh="正在推进当前任务", en="working through the current task")
    return text_for(lang, zh="稳定待命", en="steady and ready")


def _derive_session_state(lang: str, active_session: dict, runtime_state: dict) -> dict[str, str]:
    session_phase = str(active_session.get("currentPhase") or "").strip().lower()
    current_status = str(runtime_state.get("status") or "").strip().upper()
    runtime_status = str(runtime_state.get("runtime_status") or "").strip().upper()
    last_tool_name = str(runtime_state.get("last_tool_name") or "").strip()
    turn_output_tokens = max(0, int(runtime_state.get("turn_output_tokens") or 0))

    state = "idle"
    needs_response = session_phase in {"ready", "failed"}
    line = text_for(lang, zh="当前没有活跃会话动作", en="there is no active session activity right now")

    if session_phase == "failed":
        state = "failed"
        needs_response = True
        line = str(active_session.get("taskSummary") or "").strip() or text_for(
            lang,
            zh="当前轮遇到阻塞，需要先处理异常",
            en="the current pass is blocked and needs attention first",
        )
    elif session_phase == "ready":
        state = "ready"
        needs_response = True
        line = text_for(lang, zh="这一轮已经回答完成，可以继续推进", en="the latest reply is complete and ready to continue")
    elif current_status in {"ERROR", "FAILED"} or runtime_status == "ERROR":
        state = "failed"
        needs_response = True
        line = str(active_session.get("taskSummary") or "").strip() or text_for(
            lang,
            zh="当前轮遇到阻塞，需要先处理异常",
            en="the current pass is blocked and needs attention first",
        )
    elif current_status in {"SUCCESS", "DONE"} and session_phase not in RUNNING_SESSION_PHASES:
        state = "ready"
        needs_response = True
        line = text_for(lang, zh="这一轮已经回答完成，可以继续推进", en="the latest reply is complete and ready to continue")
    elif runtime_status == "ACTING":
        state = "tooling"
        line = text_for(
            lang,
            zh=f"正在调用工具 {last_tool_name}" if last_tool_name else "正在调用当前工具",
            en=f"calling tool {last_tool_name}" if last_tool_name else "calling the current tool",
        )
    elif current_status in {"THINKING", "PLANNING"}:
        state = "thinking"
        line = text_for(lang, zh="正在思考这一轮怎么推进", en="thinking through how to advance this pass")
    elif current_status == "WORKING" and runtime_status == "WORKING" and turn_output_tokens > 0 and not last_tool_name:
        state = "answering"
        line = text_for(lang, zh="正在整理并输出回答", en="drafting and sending the current reply")
    elif session_phase in RUNNING_SESSION_PHASES or current_status in {"RUNNING", "WORKING", "ACTING"} or runtime_status == "WORKING":
        state = "running"
        line = _agent_status_line(lang, "running", session_phase)

    return {
        "state": state,
        "line": line,
        "needs_response": needs_response,
        "tool_name": last_tool_name,
    }


def _mental_state_summary(lang: str, public_config: dict | None = None) -> dict[str, object]:
    if not is_mental_model_enabled(public_config):
        return _disabled_mental_state(lang)

    try:
        mental_model = get_mental_model(workspace_root=str(PROJECT_ROOT / "workspace"))
    except TypeError:
        mental_model = get_mental_model()
    except Exception:
        return _empty_mental_state(lang)

    try:
        last_state = mental_model.get_last_state() or {}
    except Exception:
        last_state = {}

    try:
        diagnosis = mental_model.diagnose()
    except Exception:
        diagnosis = None

    mood = str(last_state.get("mood") or "").strip()
    feeling = str(last_state.get("feeling") or "").strip()
    whisper = str(last_state.get("whisper") or "").strip()
    cognitive_state = str(getattr(diagnosis, "state", "") or "").strip().lower()
    confidence = float(getattr(diagnosis, "confidence", 0.0) or 0.0)
    metrics = getattr(diagnosis, "metrics", {}) or {}
    updated_at = str(
        last_state.get("timestamp")
        or getattr(diagnosis, "timestamp", "")
        or ""
    ).strip()

    source = "unavailable"
    if mood or feeling or whisper:
        source = "state"
    elif cognitive_state:
        source = "diagnosis"

    if mood:
        summary = feeling or whisper or text_for(
            lang,
            zh="当前心智层已给出最近一次状态。",
            en="The mental layer has produced a recent state.",
        )
    elif cognitive_state:
        summary = _mental_diagnosis_summary(lang, cognitive_state)
    else:
        summary = text_for(
            lang,
            zh="当前还没有新的心智感知。",
            en="No fresh mental state is available yet.",
        )

    return {
        "mood": mood,
        "feeling": feeling,
        "whisper": whisper,
        "summary": summary,
        "cognitiveState": cognitive_state,
        "confidence": max(0.0, min(confidence, 1.0)),
        "sampleSize": max(0, int(metrics.get("sample_size") or 0)),
        "interventionCount": max(0, int(metrics.get("intervention_count") or 0)),
        "updatedAt": updated_at,
        "source": source,
    }


def _empty_mental_state(lang: str) -> dict[str, object]:
    return {
        "mood": "",
        "feeling": "",
        "whisper": "",
        "summary": text_for(
            lang,
            zh="当前还没有新的心智感知。",
            en="No fresh mental state is available yet.",
        ),
        "cognitiveState": "",
        "confidence": 0.0,
        "sampleSize": 0,
        "interventionCount": 0,
        "updatedAt": "",
        "source": "unavailable",
    }


def _disabled_mental_state(lang: str) -> dict[str, object]:
    return {
        "mood": "",
        "feeling": "",
        "whisper": "",
        "summary": text_for(
            lang,
            zh="心智模型已关闭。",
            en="Mental model is disabled.",
        ),
        "cognitiveState": "",
        "confidence": 0.0,
        "sampleSize": 0,
        "interventionCount": 0,
        "updatedAt": "",
        "source": "disabled",
    }


def _mental_diagnosis_summary(lang: str, cognitive_state: str) -> str:
    label = {
        "normal": text_for(lang, zh="稳定", en="stable"),
        "productive": text_for(lang, zh="顺畅", en="productive"),
        "looping": text_for(lang, zh="循环", en="looping"),
        "thrashing": text_for(lang, zh="失稳", en="thrashing"),
        "tunnel_vision": text_for(lang, zh="聚焦过窄", en="tunnel vision"),
        "disoriented": text_for(lang, zh="方向发散", en="disoriented"),
    }.get(cognitive_state, text_for(lang, zh="未判定", en="unclassified"))
    return text_for(
        lang,
        zh=f"当前以规则诊断为主，认知态：{label}。",
        en=f"Showing rule-based diagnosis right now. Cognitive state: {label}.",
    )


def _context_usage(runtime_state: dict) -> dict[str, int]:
    used = max(0, int(runtime_state.get("current_context_tokens") or 0))
    limit = max(0, int(runtime_state.get("context_token_limit") or 0)) or 128000
    return {"used": min(used, limit), "limit": limit}


def _active_tools(active_session: dict, runtime_state: dict) -> list[str]:
    tools: list[str] = []
    for message in reversed(list(active_session.get("messages") or [])):
        tool_calls = list(message.get("toolCalls") or [])
        if tool_calls:
            for item in tool_calls:
                name = str((item or {}).get("name") or "").strip()
                if name and name not in tools:
                    tools.append(name)
            break
    last_tool_name = str(runtime_state.get("last_tool_name") or "").strip()
    if last_tool_name and last_tool_name not in tools:
        tools.append(last_tool_name)
    return tools[:8]


def _recent_action(lang: str, active_session: dict, runtime_state: dict) -> str:
    for value in (active_session.get("taskSummary"),):
        text = str(value or "").strip()
        if text:
            return text
    last_tool_name = str(runtime_state.get("last_tool_name") or "").strip()
    if last_tool_name:
        return text_for(
            lang,
            zh=f"最近使用工具：{last_tool_name}",
            en=f"Last tool used: {last_tool_name}",
        )
    return text_for(lang, zh="等待新的运行痕迹", en="Waiting for new runtime activity")
