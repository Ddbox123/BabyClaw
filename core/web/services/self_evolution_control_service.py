"""Bounded self-evolution run control for the web workbench."""

from __future__ import annotations

import hashlib
import json
import queue
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from core.evaluation import DEFAULT_SELF_EVOLUTION_GOAL, build_self_evolution_run_prompt
from core.infrastructure.agent_session import get_session_state
from core.runtime_manager.command_queue import submit_command, wait_for_result
from core.runtime_manager.evolution_store import (
    load_active_run_snapshot as load_manager_active_run_snapshot,
    load_latest_run_snapshot as load_manager_latest_run_snapshot,
    load_run_snapshot as load_manager_run_snapshot,
    persist_run_snapshot as persist_manager_run_snapshot,
)

from .i18n import get_web_language, text_for
from .session_service import (
    SessionBusyError,
    SessionNotFoundError,
    get_active_session_detail,
    has_running_sessions,
    submit_session_message,
)
from .supervised_control_service import get_active_supervised_run
from .workbench_contract_service import get_workbench_contract


PROJECT_ROOT = Path(__file__).resolve().parents[3]
RUNTIME_STATE_PATH = PROJECT_ROOT / "workspace" / "ui_runtime_state.json"
ROLLBACK_ROOT = PROJECT_ROOT / "workspace" / "web_self_evolution"
_RUN_STATE_LOCK = threading.Lock()
_RUN_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="web-self-evolution")
_RUN_STATES: dict[str, dict[str, Any]] = {}
_RUN_INTERNALS: dict[str, dict[str, Any]] = {}
_ACTIVE_RUN_ID: str | None = None
_RUN_STREAM_HEARTBEAT_SECONDS = 15.0
_RUN_STREAM_POLL_SECONDS = 2.0
_RUN_STREAM_QUEUE_SIZE = 8
_RUN_SUBSCRIBERS_LOCK = threading.Lock()
_RUN_SUBSCRIBERS: dict[str, set[queue.Queue[dict[str, Any]]]] = {}
_RUN_EXECUTING_STATUSES = {"queued", "running", "stopping"}
_RUN_LOCKED_STATUSES = {"queued", "running", "stopping", "paused"}
_RUN_FINAL_STATUSES = {"done", "failed", "cancelled"}


class SelfEvolutionRunBusyError(RuntimeError):
    """Raised when a self-evolution run is already active."""


class SelfEvolutionRunValidationError(ValueError):
    """Raised when an incoming self-evolution action is invalid."""


class SelfEvolutionRunNotFoundError(LookupError):
    """Raised when a requested self-evolution run cannot be found."""


def _runtime_manager_live_control_enabled() -> bool:
    try:
        from core.runtime_manager.daemon import load_runtime_snapshot

        snapshot = load_runtime_snapshot()
    except Exception:
        return False
    if not bool((snapshot or {}).get("daemonRunning")):
        return False
    snapshot_root = str((snapshot or {}).get("projectRoot") or "").strip()
    if not snapshot_root:
        return False
    try:
        return Path(snapshot_root).resolve() == PROJECT_ROOT.resolve()
    except OSError:
        return False


def _ensure_runtime_manager_daemon() -> None:
    from core.runtime_manager.daemon import ensure_daemon_running

    ensure_daemon_running()


def _map_runtime_manager_error(message: str, error_type: str) -> Exception:
    normalized = str(error_type or "").strip()
    if normalized == "SelfEvolutionRunBusyError":
        return SelfEvolutionRunBusyError(message)
    if normalized == "SelfEvolutionRunNotFoundError":
        return SelfEvolutionRunNotFoundError(message)
    return SelfEvolutionRunValidationError(message)


def get_active_self_evolution_run() -> dict[str, Any] | None:
    """Return the current bounded self-evolution snapshot when it is still active or paused."""

    with _RUN_STATE_LOCK:
        payload = _current_active_run_locked()
        if payload is None:
            return None
        if str(payload.get("status") or "").strip().lower() not in _RUN_LOCKED_STATUSES:
            return None
        return _decorate_runtime_snapshot(_clone_payload(payload))


def get_latest_self_evolution_run() -> dict[str, Any] | None:
    """Return the latest known bounded self-evolution run snapshot."""

    with _RUN_STATE_LOCK:
        payload = _latest_run_locked()
        if payload is None:
            return None
        return _decorate_runtime_snapshot(_clone_payload(payload))


def get_self_evolution_run_snapshot(run_id: str) -> dict[str, Any] | None:
    """Return any known self-evolution run snapshot by id."""

    normalized = str(run_id or "").strip()
    if not normalized:
        return None
    with _RUN_STATE_LOCK:
        payload = _RUN_STATES.get(normalized)
        if payload is None:
            return None
        return _decorate_runtime_snapshot(_clone_payload(payload))


def stream_self_evolution_run_events(run_id: str, initial_snapshot: dict[str, Any] | None = None):
    """Yield SSE snapshots for one self-evolution run."""

    lang = get_web_language()
    normalized = str(run_id or "").strip()
    if not normalized:
        raise SelfEvolutionRunNotFoundError(
            text_for(lang, zh="未找到这条自进化记录。", en="Self-evolution run not found.")
        )

    snapshot = initial_snapshot or get_self_evolution_run_snapshot(normalized)
    if snapshot is None:
        raise SelfEvolutionRunNotFoundError(
            text_for(lang, zh="未找到这条自进化记录。", en="Self-evolution run not found.")
        )

    subscriber: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=_RUN_STREAM_QUEUE_SIZE)
    _register_run_subscriber(normalized, subscriber)
    last_signature = _snapshot_signature(snapshot)
    last_keepalive = time.monotonic()
    try:
        terminal = _is_terminal_run_snapshot(snapshot)
        yield _encode_sse_event(
            "self_evolution_run",
            {
                "type": "self_evolution_run",
                "runId": normalized,
                "snapshot": snapshot,
                "terminal": terminal,
            },
        )
        if terminal:
            return

        while True:
            try:
                event = subscriber.get(timeout=_RUN_STREAM_POLL_SECONDS)
            except queue.Empty:
                latest = get_self_evolution_run_snapshot(normalized)
                if latest is not None:
                    signature = _snapshot_signature(latest)
                    if signature != last_signature:
                        last_signature = signature
                        terminal = _is_terminal_run_snapshot(latest)
                        yield _encode_sse_event(
                            "self_evolution_run",
                            {
                                "type": "self_evolution_run",
                                "runId": normalized,
                                "snapshot": latest,
                                "terminal": terminal,
                            },
                        )
                        last_keepalive = time.monotonic()
                        if terminal:
                            break
                        continue
                if time.monotonic() - last_keepalive >= _RUN_STREAM_HEARTBEAT_SECONDS:
                    yield ": keep-alive\n\n"
                    last_keepalive = time.monotonic()
                continue

            snapshot_payload = event.get("snapshot") if isinstance(event.get("snapshot"), dict) else None
            if snapshot_payload is not None:
                last_signature = _snapshot_signature(snapshot_payload)
            yield _encode_sse_event(str(event.get("type") or "self_evolution_run"), event)
            last_keepalive = time.monotonic()
            if bool(event.get("terminal")):
                break
    finally:
        _unregister_run_subscriber(normalized, subscriber)


def has_active_self_evolution_run() -> bool:
    """Report whether a bounded web self-evolution run is active or paused."""

    with _RUN_STATE_LOCK:
        payload = _current_active_run_locked()
        if payload is None:
            return False
        return str(payload.get("status") or "").strip().lower() in _RUN_LOCKED_STATUSES


def start_self_evolution_run(payload: dict[str, Any]) -> dict[str, Any]:
    """Start one bounded self-evolution pass from the web workbench."""

    global _ACTIVE_RUN_ID
    lang = get_web_language()
    contract = get_workbench_contract()
    if not bool(contract.get("modeAvailability", {}).get("self_evolution")):
        raise SelfEvolutionRunValidationError(
            text_for(
                lang,
                zh="配置里没有启用 self_evolution，当前不能从网页启动这一轮。",
                en="The current config does not enable self_evolution, so the web surface cannot launch this pass.",
            )
        )

    goal = str(payload.get("goal") or DEFAULT_SELF_EVOLUTION_GOAL).strip() or DEFAULT_SELF_EVOLUTION_GOAL
    if has_running_sessions():
        raise SelfEvolutionRunBusyError(
            text_for(
                lang,
                zh="当前有网页会话还在运行，请等这一轮结束后再启动自进化。",
                en="A web chat turn is still running. Wait for it to finish before launching self evolution.",
            )
        )

    active_supervised = get_active_supervised_run()
    if active_supervised is not None and str(active_supervised.get("status") or "").strip().lower() in {"queued", "running"}:
        raise SelfEvolutionRunBusyError(
            text_for(
                lang,
                zh="当前已有监督任务在运行，请等监督任务结束后再启动自进化。",
                en="A supervised run is already active. Wait for it to finish before launching self evolution.",
            )
        )

    with _RUN_STATE_LOCK:
        active_id = _ACTIVE_RUN_ID
        if active_id and _RUN_STATES.get(active_id):
            raise SelfEvolutionRunBusyError(
                text_for(
                    lang,
                    zh="当前已经有一轮网页自进化在运行或暂停中，请先继续或终止这一轮。",
                    en="A web self-evolution pass is already active or paused. Resume or terminate it before starting another one.",
                )
            )

    run_id = f"web-self-{uuid4().hex[:12]}"
    started_at = _now_timestamp()
    preflight = _capture_preflight_state(run_id)
    state = {
        "runId": run_id,
        "goal": goal,
        "status": "queued",
        "phase": "queued",
        "startedAt": started_at,
        "updatedAt": started_at,
        "finishedAt": "",
        "latestMessage": text_for(
            lang,
            zh="已加入网页自进化队列，准备开始这一轮。",
            en="The self-evolution pass is queued and preparing to start.",
        ),
        "currentGoal": goal,
        "lastToolName": "",
        "runtimeStatus": "idle",
        "toolCallCount": 0,
        "summary": "",
        "error": "",
        "cancelRequested": False,
        "cancelRequestedAt": "",
        "stopReason": "",
        "controlAction": "",
        "controlRequestedAt": "",
        "messages": [
            _build_run_message(
                run_id=run_id,
                role="user",
                content=goal,
                timestamp=started_at,
            )
        ],
        "turnCount": 0,
        "resumeCount": 0,
        "rollback": _initial_rollback_state(lang, base_rev=str(preflight.get("baseRev") or "")),
        "artifacts": {
            "runDir": str(preflight.get("runDir") or ""),
            "backupDir": str(preflight.get("backupDir") or ""),
            "manifestPath": str(preflight.get("manifestPath") or ""),
            "baseRev": str(preflight.get("baseRev") or ""),
        },
    }
    context = {
        "runId": run_id,
        "goal": goal,
        "startedAt": started_at,
        "preflight": preflight,
    }

    with _RUN_STATE_LOCK:
        active = _current_active_run_locked()
        if active is not None and str(active.get("status") or "").strip().lower() in _RUN_LOCKED_STATUSES:
            raise SelfEvolutionRunBusyError(
                text_for(
                    lang,
                    zh="当前已有自进化任务在运行或暂停中，请先继续或终止这一轮。",
                    en="A self-evolution pass is already active or paused. Resume or terminate it before starting another one.",
                )
            )
        _RUN_STATES[run_id] = state
        _RUN_INTERNALS[run_id] = {
            "preflight": preflight,
            "carryover": {},
        }
        _ACTIVE_RUN_ID = run_id
    _publish_run_snapshot(run_id)

    try:
        _RUN_EXECUTOR.submit(_run_self_evolution_turn, context)
    except Exception as exc:
        _mark_run_failed(
            run_id,
            text_for(
                lang,
                zh=f"无法启动自进化：{type(exc).__name__}: {exc}",
                en=f"Failed to start self evolution: {type(exc).__name__}: {exc}",
            ),
        )
        raise
    return get_self_evolution_run_snapshot(run_id) or state


def request_pause_self_evolution_run(run_id: str) -> dict[str, Any]:
    """Request a graceful pause for one active self-evolution run."""

    lang = get_web_language()
    normalized = str(run_id or "").strip()
    if not normalized:
        raise SelfEvolutionRunValidationError(
            text_for(lang, zh="缺少自进化 run id。", en="Missing self-evolution run id.")
        )

    now = _now_timestamp()
    immediate_snapshot: dict[str, Any] | None = None
    with _RUN_STATE_LOCK:
        current = _RUN_STATES.get(normalized)
        if current is None:
            raise SelfEvolutionRunNotFoundError(
                text_for(lang, zh="未找到这条自进化记录。", en="Self-evolution run not found.")
            )
        status = str(current.get("status") or "").strip().lower()
        if status in _RUN_FINAL_STATUSES or status == "paused":
            return _decorate_runtime_snapshot(_clone_payload(current))
        if status == "stopping":
            return _decorate_runtime_snapshot(_clone_payload(current))
        if status == "queued":
            current.update(
                {
                    "status": "paused",
                    "phase": "paused",
                    "updatedAt": now,
                    "runtimeStatus": "idle",
                    "latestMessage": text_for(
                        lang,
                        zh="这轮网页自进化已在启动前暂停，可随时继续。",
                        en="This web self-evolution pass was paused before it started and can be resumed any time.",
                    ),
                    "summary": text_for(
                        lang,
                        zh="用户在启动前请求暂停这一轮网页自进化。",
                        en="The operator requested this bounded self-evolution pass to pause before start.",
                    ),
                    "stopReason": text_for(
                        lang,
                        zh="用户请求暂停这一轮。",
                        en="The operator requested this pass to pause.",
                    ),
                    "controlAction": "",
                    "controlRequestedAt": "",
                }
            )
            _append_run_message_locked(
                current,
                role="assistant",
                content=current["latestMessage"],
                timestamp=now,
            )
            immediate_snapshot = _decorate_runtime_snapshot(_clone_payload(current))
        else:
            current.update(
                {
                    "status": "stopping",
                    "phase": "stopping",
                    "updatedAt": now,
                    "runtimeStatus": "pausing",
                    "latestMessage": text_for(
                        lang,
                        zh="已请求暂停这一轮，等待当前安全点收口。",
                        en="A pause was requested. Waiting for the current safe point to pause this pass.",
                    ),
                    "stopReason": text_for(
                        lang,
                        zh="用户请求暂停这一轮网页自进化。",
                        en="The operator requested this bounded self-evolution pass to pause.",
                    ),
                    "controlAction": "pause",
                    "controlRequestedAt": now,
                }
            )
    if immediate_snapshot is not None:
        _publish_run_snapshot(normalized, terminal=True)
        return immediate_snapshot

    _publish_run_snapshot(normalized)
    get_session_state().note_scope_completion(
        text_for(
            lang,
            zh="网页控制台请求暂停当前自进化，请在当前安全点收口并保留可继续上下文。",
            en="The web control requested a pause. Close the current safe point and preserve resumable context for this self-evolution pass.",
        )
    )
    return get_self_evolution_run_snapshot(normalized) or {}


def resume_self_evolution_run(run_id: str) -> dict[str, Any]:
    """Resume one paused self-evolution run."""

    lang = get_web_language()
    normalized = str(run_id or "").strip()
    if not normalized:
        raise SelfEvolutionRunValidationError(
            text_for(lang, zh="缺少自进化 run id。", en="Missing self-evolution run id.")
        )
    if has_running_sessions():
        raise SelfEvolutionRunBusyError(
            text_for(
                lang,
                zh="当前有网页会话还在运行，请等这一轮结束后再继续自进化。",
                en="A web chat turn is still running. Wait for it to finish before resuming self evolution.",
            )
        )
    active_supervised = get_active_supervised_run()
    if active_supervised is not None and str(active_supervised.get("status") or "").strip().lower() in {"queued", "running"}:
        raise SelfEvolutionRunBusyError(
            text_for(
                lang,
                zh="当前已有监督任务在运行，请等监督任务结束后再继续自进化。",
                en="A supervised run is already active. Wait for it to finish before resuming self evolution.",
            )
        )

    now = _now_timestamp()
    state_snapshot: dict[str, Any] | None = None
    with _RUN_STATE_LOCK:
        current = _RUN_STATES.get(normalized)
        if current is None:
            raise SelfEvolutionRunNotFoundError(
                text_for(lang, zh="未找到这条自进化记录。", en="Self-evolution run not found.")
            )
        status = str(current.get("status") or "").strip().lower()
        if status in _RUN_EXECUTING_STATUSES:
            return _decorate_runtime_snapshot(_clone_payload(current))
        if status != "paused":
            raise SelfEvolutionRunValidationError(
                text_for(
                    lang,
                    zh="只有已暂停的自进化任务才能继续。",
                    en="Only a paused self-evolution pass can be resumed.",
                )
            )
        current.update(
            {
                "status": "queued",
                "phase": "queued",
                "updatedAt": now,
                "runtimeStatus": "idle",
                "latestMessage": text_for(
                    lang,
                    zh="这一轮网页自进化已恢复排队，准备继续。",
                    en="This web self-evolution pass is queued to resume.",
                ),
                "summary": "",
                "error": "",
                "cancelRequested": False,
                "cancelRequestedAt": "",
                "stopReason": "",
                "controlAction": "",
                "controlRequestedAt": "",
                "resumeCount": max(0, int(current.get("resumeCount") or 0)) + 1,
            }
        )
        _append_run_message_locked(
            current,
            role="user",
            content=_build_resume_user_message(str(current.get("goal") or "")),
            timestamp=now,
        )
        state_snapshot = _clone_payload(current)

    assert state_snapshot is not None
    _publish_run_snapshot(normalized)
    try:
        _RUN_EXECUTOR.submit(
            _run_self_evolution_turn,
            {
                "runId": normalized,
                "goal": str(state_snapshot.get("goal") or DEFAULT_SELF_EVOLUTION_GOAL),
            },
        )
    except Exception as exc:
        _mark_run_failed(
            normalized,
            text_for(
                lang,
                zh=f"无法继续自进化：{type(exc).__name__}: {exc}",
                en=f"Failed to resume self evolution: {type(exc).__name__}: {exc}",
            ),
        )
        raise
    return get_self_evolution_run_snapshot(normalized) or state_snapshot


def request_stop_self_evolution_run(run_id: str) -> dict[str, Any]:
    """Request termination for one active or paused self-evolution run."""

    global _ACTIVE_RUN_ID
    lang = get_web_language()
    normalized = str(run_id or "").strip()
    if not normalized:
        raise SelfEvolutionRunValidationError(
            text_for(lang, zh="缺少自进化 run id。", en="Missing self-evolution run id.")
        )

    now = _now_timestamp()
    finalize_snapshot: dict[str, Any] | None = None
    publish_terminal = False
    with _RUN_STATE_LOCK:
        current = _RUN_STATES.get(normalized)
        if current is None:
            raise SelfEvolutionRunNotFoundError(
                text_for(lang, zh="未找到这条自进化记录。", en="Self-evolution run not found.")
            )
        status = str(current.get("status") or "").strip().lower()
        if status in _RUN_FINAL_STATUSES:
            return _decorate_runtime_snapshot(_clone_payload(current))
        if status in {"queued", "paused"}:
            current.update(
                {
                    "status": "cancelled",
                    "phase": "cancelled",
                    "updatedAt": now,
                    "finishedAt": now,
                    "runtimeStatus": "idle",
                    "latestMessage": text_for(
                        lang,
                        zh="这轮网页自进化已终止，可以重新开始新的一轮。",
                        en="This web self-evolution pass has been terminated, and a new pass can be started now.",
                    ),
                    "summary": text_for(
                        lang,
                        zh="用户请求终止这一轮网页自进化。",
                        en="The operator requested this bounded self-evolution pass to terminate.",
                    ),
                    "cancelRequested": True,
                    "cancelRequestedAt": now,
                    "stopReason": text_for(
                        lang,
                        zh="用户请求终止这一轮。",
                        en="The operator requested this pass to terminate.",
                    ),
                    "controlAction": "",
                    "controlRequestedAt": "",
                }
            )
            _append_run_message_locked(
                current,
                role="assistant",
                content=current["latestMessage"],
                timestamp=now,
            )
            if _ACTIVE_RUN_ID == normalized:
                _ACTIVE_RUN_ID = None
            finalize_snapshot = _clone_payload(current)
            publish_terminal = True
        else:
            current.update(
                {
                    "status": "stopping",
                    "phase": "stopping",
                    "updatedAt": now,
                    "runtimeStatus": "stopping",
                    "latestMessage": text_for(
                        lang,
                        zh="已请求这一轮尽快收口，等待当前安全点结束。",
                        en="A termination was requested. Waiting for the current safe point to close this pass.",
                    ),
                    "cancelRequested": True,
                    "cancelRequestedAt": now,
                    "stopReason": text_for(
                        lang,
                        zh="用户请求终止这一轮网页自进化。",
                        en="The operator requested this bounded self-evolution pass to terminate.",
                    ),
                    "controlAction": "terminate",
                    "controlRequestedAt": now,
                }
            )
    if finalize_snapshot is not None:
        manifest = _finalize_terminal_run_snapshot(normalized)
        if manifest is not None:
            _merge_run_state(normalized, {"rollback": manifest})
        if publish_terminal:
            _publish_run_snapshot(normalized, terminal=True)
        return get_self_evolution_run_snapshot(normalized) or finalize_snapshot

    _publish_run_snapshot(normalized)
    get_session_state().note_scope_completion(
        text_for(
            lang,
            zh="网页控制台请求终止当前自进化，请在当前安全点收口并停止继续扩散。",
            en="The web control requested termination. Close the current safe point and stop expanding this self-evolution pass.",
        )
    )
    return get_self_evolution_run_snapshot(normalized) or {}


def rollback_self_evolution_run(run_id: str) -> dict[str, Any]:
    """Safely roll one finished self-evolution run back to its pre-run file state."""

    lang = get_web_language()
    state = _require_terminal_run(run_id)
    manifest = _load_rollback_manifest(state)
    rollback = manifest.get("display") if isinstance(manifest.get("display"), dict) else {}
    touched_files = rollback.get("touchedFiles") if isinstance(rollback.get("touchedFiles"), list) else []
    if not touched_files:
        raise SelfEvolutionRunValidationError(
            text_for(
                lang,
                zh="这一轮没有可安全回滚的文件差异。",
                en="This run does not have any safe file diff to roll back.",
            )
        )
    rollback_entries = manifest.get("entries") if isinstance(manifest.get("entries"), list) else []
    if not rollback_entries:
        rollback_entries = touched_files
    if any(
        str(item.get("path") or "").strip() and not str(item.get("restoreSource") or "").strip()
        for item in rollback_entries
    ):
        raise SelfEvolutionRunValidationError(
            text_for(
                lang,
                zh="这轮记录缺少完整的回滚清单，当前不能自动一键回滚，请交给会话 agent 继续处理。",
                en="This run is missing a complete rollback manifest, so automatic rollback is unavailable. Hand it off to the session agent instead.",
            )
        )

    conflicts = _detect_rollback_conflicts(state, entries=rollback_entries)
    if conflicts:
        _merge_run_state(
            state["runId"],
            {
                "rollback": _build_rollback_state(
                    lang=lang,
                    status="blocked",
                    reason=text_for(
                        lang,
                        zh="这些文件在进化后又被改过了，不能自动一键回滚。",
                        en="These files changed again after the self-evolution pass, so automatic rollback is blocked.",
                    ),
                    base_rev=str(rollback.get("baseRev") or ""),
                    touched_files=touched_files,
                    conflict_files=conflicts,
                    rolled_back_at=str(rollback.get("rolledBackAt") or ""),
                )
            }
        )
        return get_self_evolution_run_snapshot(state["runId"]) or {}

    _apply_rollback_entries(state, rollback_entries)
    updated = _build_rollback_state(
        lang=lang,
        status="rolled_back",
        reason=text_for(
            lang,
            zh="已把这轮网页自进化恢复到进化前的文件状态。",
            en="This bounded self-evolution pass has been restored to its pre-run file state.",
        ),
        base_rev=str(rollback.get("baseRev") or ""),
        touched_files=touched_files,
        conflict_files=[],
        rolled_back_at=_now_timestamp(),
    )
    _merge_run_state(
        state["runId"],
        {
            "updatedAt": _now_timestamp(),
            "latestMessage": updated["reason"],
            "rollback": updated,
        }
    )
    return get_self_evolution_run_snapshot(state["runId"]) or {}


def handoff_self_evolution_run_to_session(run_id: str) -> dict[str, Any]:
    """Send or prepare a rollback handoff for the active coding session."""

    lang = get_web_language()
    state = _require_run_snapshot(run_id)
    rollback = state.get("rollback") if isinstance(state.get("rollback"), dict) else {}
    content = _build_session_handoff_message(state)
    active_session = get_active_session_detail()
    session_id = str((active_session or {}).get("id") or "").strip()
    if not session_id:
        return {
            "status": "ready",
            "message": text_for(
                lang,
                zh="当前没有可直接提交的会话，已为会话 agent 准备好 handoff 内容。",
                en="No active session is ready to receive this automatically. The handoff content is prepared for the session agent.",
            ),
            "sessionId": "",
            "content": content,
            "run": get_self_evolution_run_snapshot(state["runId"]),
        }

    try:
        submit_session_message(session_id, content)
    except (SessionBusyError, SessionNotFoundError):
        return {
            "status": "ready",
            "message": text_for(
                lang,
                zh="当前会话正忙，已准备好 handoff 内容，切到会话页后可继续交给 agent。",
                en="The current session is busy. The handoff content is ready to continue with the session agent on the chat page.",
            ),
            "sessionId": session_id,
            "content": content,
            "run": get_self_evolution_run_snapshot(state["runId"]),
        }

    summary = text_for(
        lang,
        zh="已把这次回滚处理请求直接交给当前会话 agent。",
        en="This rollback handoff was sent directly to the current session agent.",
    )
    _merge_run_state(state["runId"], {"updatedAt": _now_timestamp(), "latestMessage": summary})
    return {
        "status": "submitted",
        "message": summary,
        "sessionId": session_id,
        "content": content,
        "run": get_self_evolution_run_snapshot(state["runId"]),
    }


def _run_self_evolution_turn(context: dict[str, Any]) -> None:
    lang = get_web_language()
    run_id = str(context.get("runId") or "").strip()
    goal = str(context.get("goal") or DEFAULT_SELF_EVOLUTION_GOAL).strip() or DEFAULT_SELF_EVOLUTION_GOAL
    initial = get_self_evolution_run_snapshot(run_id) or {}
    initial_status = str(initial.get("status") or "").strip().lower()
    if initial_status in {"cancelled", "paused"}:
        return
    internal = _get_run_internal(run_id)
    preflight = internal.get("preflight") if isinstance(internal.get("preflight"), dict) else {}
    carryover = internal.get("carryover") if isinstance(internal.get("carryover"), dict) else {}

    _merge_run_state(
        run_id,
        {
            "status": "running",
            "phase": "running",
            "updatedAt": _now_timestamp(),
            "runtimeStatus": "running",
            "controlAction": "",
            "controlRequestedAt": "",
            "latestMessage": text_for(
                lang,
                zh="正在执行这一轮网页自进化，现场证据和事务列表会继续刷新。",
                en="The bounded self-evolution pass is running. Evidence and transaction panels will keep refreshing.",
            ),
            "turnCount": max(0, int(initial.get("turnCount") or 0)) + 1,
        },
    )
    live_refresh_stop = threading.Event()
    live_refresh_thread = threading.Thread(
        target=_self_live_refresh_loop,
        args=(run_id, live_refresh_stop),
        daemon=True,
        name=f"self-evolution-live-{run_id[:8]}",
    )
    live_refresh_thread.start()
    result: dict[str, Any] = {}
    result_status = ""
    summary = ""
    tool_call_count = 0
    total_tool_call_count = max(0, int(initial.get("toolCallCount") or 0))
    try:
        from agent import SelfEvolvingAgent

        agent = SelfEvolvingAgent(mode="self_evolution")
        seed_turn_carryover = getattr(agent, "seed_turn_carryover", None)
        if callable(seed_turn_carryover) and carryover:
            seed_turn_carryover(carryover)
        stop_configurer = getattr(agent, "set_turn_interrupt_checker", None)
        if callable(stop_configurer):
            stop_configurer(lambda: _current_run_control_reason(run_id))
        prompt = goal if carryover else _build_web_run_prompt(goal)
        result = agent.run_single_turn(initial_prompt=prompt)
        result_status = str(result.get("status") or "").strip().lower()
        summary = str(result.get("summary") or "").strip()
        tool_call_count = max(0, int(result.get("tool_call_count") or 0))
        total_tool_call_count += tool_call_count
        carryover_payload: dict[str, Any] = {}
        export_turn_carryover = getattr(agent, "export_turn_carryover", None)
        if callable(export_turn_carryover):
            exported = export_turn_carryover()
            if isinstance(exported, dict):
                carryover_payload = exported
        run_snapshot = get_self_evolution_run_snapshot(run_id) or {}
        control_action = str(run_snapshot.get("controlAction") or "").strip().lower()
        cancel_requested = bool(run_snapshot.get("cancelRequested"))
        assistant_message = _build_result_message(
            result=result,
            fallback=summary
            or text_for(
                lang,
                zh="这一轮网页自进化已结束。",
                en="This bounded self-evolution pass is complete.",
            ),
        )
        transcript_tool_calls = _tool_calls_from_result(result)
        last_tool_name = _last_tool_name_from_result(result)
        if result_status == "failed":
            error = str(result.get("error") or summary or "").strip()
            if control_action == "pause":
                _mark_run_paused(
                    run_id,
                    summary=assistant_message or error,
                    tool_call_count=total_tool_call_count,
                    reason=text_for(
                        lang,
                        zh="这一轮已按网页请求暂停，可从当前上下文继续。",
                        en="This pass paused at the web request and can resume from the current context.",
                    ),
                    carryover=carryover_payload,
                    tool_calls=transcript_tool_calls,
                    last_tool_name=last_tool_name,
                )
                return
            if cancel_requested or control_action == "terminate":
                _mark_run_cancelled(
                    run_id,
                    summary=assistant_message or error,
                    tool_call_count=total_tool_call_count,
                    reason=text_for(
                        lang,
                        zh="已请求终止这一轮，运行在失败前收口。",
                        en="A stop was requested and this pass closed before finishing cleanly.",
                    ),
                    tool_calls=transcript_tool_calls,
                    last_tool_name=last_tool_name,
                )
                return
            _mark_run_failed(
                run_id,
                error
                or text_for(
                    lang,
                        zh="这一轮网页自进化执行失败，请检查日志。",
                        en="This web self-evolution pass failed. Check the logs for details.",
                    ),
                tool_call_count=total_tool_call_count,
                summary=assistant_message or summary,
                tool_calls=transcript_tool_calls,
                last_tool_name=last_tool_name,
            )
            return

        if control_action == "pause":
            _mark_run_paused(
                run_id,
                summary=assistant_message
                or text_for(
                    lang,
                    zh="这一轮网页自进化已暂停，可继续当前上下文。",
                    en="This bounded self-evolution pass is paused and can resume from the current context.",
                ),
                tool_call_count=total_tool_call_count,
                reason=text_for(
                    lang,
                    zh="这一轮已按网页请求暂停。",
                    en="This pass was paused by the web request.",
                ),
                carryover=carryover_payload,
                tool_calls=transcript_tool_calls,
                last_tool_name=last_tool_name,
            )
            return

        if cancel_requested or control_action == "terminate" or result_status == "stopped":
            _mark_run_cancelled(
                run_id,
                summary=assistant_message
                or text_for(
                    lang,
                    zh="这一轮网页自进化已按请求终止。",
                    en="This bounded self-evolution pass stopped as requested.",
                ),
                tool_call_count=total_tool_call_count,
                reason=text_for(
                    lang,
                    zh="这一轮已按网页请求收口。",
                    en="This pass was closed by the web stop request.",
                ),
                tool_calls=transcript_tool_calls,
                last_tool_name=last_tool_name,
            )
            return

        finished_at = _now_timestamp()
        _merge_run_state(
            run_id,
            {
                "status": "done",
                "phase": result_status or "completed",
                "updatedAt": finished_at,
                "finishedAt": finished_at,
                "runtimeStatus": "idle",
                "latestMessage": assistant_message
                or text_for(
                    lang,
                    zh="这一轮网页自进化已结束。",
                    en="This bounded self-evolution pass is complete.",
                ),
                "summary": assistant_message or summary,
                "toolCallCount": total_tool_call_count,
                "lastToolName": last_tool_name,
                "error": "",
                "controlAction": "",
                "controlRequestedAt": "",
                "messages": _append_run_message(
                    list(initial.get("messages") or []),
                    _build_run_message(
                        run_id=run_id,
                        role="assistant",
                        content=assistant_message
                        or text_for(
                            lang,
                            zh="这一轮网页自进化已结束。",
                            en="This bounded self-evolution pass is complete.",
                        ),
                        timestamp=finished_at,
                        tool_calls=transcript_tool_calls,
                    ),
                ),
            },
            clear_active=True,
        )
    except SystemExit as exc:
        _mark_run_cancelled(
            run_id,
            summary=text_for(
                lang,
                zh="这一轮网页自进化请求了进程级动作，当前按已结束记录。",
                en="This bounded self-evolution pass requested a process-level action and has been recorded as finished.",
            ),
            tool_call_count=total_tool_call_count,
            reason=str(exc) if str(exc).strip() else "",
        )
    except Exception as exc:
        _mark_run_failed(
            run_id,
            f"{type(exc).__name__}: {exc}",
            tool_call_count=total_tool_call_count,
            summary=summary,
        )
    finally:
        live_refresh_stop.set()
        live_refresh_thread.join(timeout=1.0)
        _persist_self_snapshot(run_id)
        state = get_self_evolution_run_snapshot(run_id) or {}
        if str(state.get("status") or "").strip().lower() in _RUN_FINAL_STATUSES:
            manifest = _finalize_rollback_manifest(run_id, preflight)
            if manifest is not None:
                _merge_run_state(run_id, {"rollback": manifest})
            _clear_run_internal(run_id)


def _self_live_refresh_loop(run_id: str, stop_event: threading.Event) -> None:
    while not stop_event.wait(0.75):
        snapshot = _persist_self_snapshot(run_id)
        if snapshot is None:
            return
        status = str(snapshot.get("status") or "").strip().lower()
        if status in _RUN_FINAL_STATUSES | {"paused"}:
            return


def _build_web_run_prompt(goal: str) -> str:
    base = build_self_evolution_run_prompt(goal=goal, project_root=PROJECT_ROOT)
    return (
        f"{base}\n\n"
        "网页工作台约束:\n"
        "1. 这是一轮有界自进化，只完成当前这一轮，不要继续进入无限自主循环。\n"
        "2. 如果共享现场风险很高，可以先总结风险并停止，不必为了修改而强行修改。\n"
        "3. 不要等待额外人工交互；直接完成这一轮并给出可见结论。"
    )


def _mark_run_paused(
    run_id: str,
    *,
    summary: str,
    tool_call_count: int = 0,
    reason: str = "",
    carryover: dict[str, Any] | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
    last_tool_name: str = "",
) -> None:
    paused_at = _now_timestamp()
    snapshot = get_self_evolution_run_snapshot(run_id) or {}
    if carryover:
        _set_run_internal_value(run_id, "carryover", carryover)
    _merge_run_state(
        run_id,
        {
            "status": "paused",
            "phase": "paused",
            "updatedAt": paused_at,
            "runtimeStatus": "idle",
            "latestMessage": str(summary or "").strip(),
            "summary": str(summary or "").strip(),
            "toolCallCount": max(0, int(tool_call_count or 0)),
            "stopReason": str(reason or "").strip(),
            "lastToolName": str(last_tool_name or "").strip(),
            "controlAction": "",
            "controlRequestedAt": "",
            "messages": _append_run_message(
                list(snapshot.get("messages") or []),
                _build_run_message(
                    run_id=run_id,
                    role="assistant",
                    content=str(summary or "").strip(),
                    timestamp=paused_at,
                    tool_calls=tool_calls,
                ),
            ),
            "error": "",
        },
    )


def _mark_run_failed(
    run_id: str,
    message: str,
    *,
    tool_call_count: int | None = None,
    summary: str = "",
    tool_calls: list[dict[str, Any]] | None = None,
    last_tool_name: str = "",
) -> None:
    finished_at = _now_timestamp()
    snapshot = get_self_evolution_run_snapshot(run_id) or {}
    visible_summary = str(summary or message or "").strip()
    payload: dict[str, Any] = {
        "status": "failed",
        "phase": "failed",
        "updatedAt": finished_at,
        "finishedAt": finished_at,
        "runtimeStatus": "failed",
        "latestMessage": str(message or "").strip(),
        "summary": visible_summary,
        "error": str(message or "").strip(),
        "lastToolName": str(last_tool_name or "").strip(),
        "controlAction": "",
        "controlRequestedAt": "",
    }
    if tool_call_count is not None:
        payload["toolCallCount"] = max(0, int(tool_call_count))
    if visible_summary:
        payload["messages"] = _append_run_message(
            list(snapshot.get("messages") or []),
            _build_run_message(
                run_id=run_id,
                role="assistant",
                content=visible_summary,
                timestamp=finished_at,
                tool_calls=tool_calls,
            ),
        )
    _merge_run_state(run_id, payload, clear_active=True)


def _mark_run_cancelled(
    run_id: str,
    *,
    summary: str,
    tool_call_count: int = 0,
    reason: str = "",
    tool_calls: list[dict[str, Any]] | None = None,
    last_tool_name: str = "",
) -> None:
    finished_at = _now_timestamp()
    snapshot = get_self_evolution_run_snapshot(run_id) or {}
    _merge_run_state(
        run_id,
        {
            "status": "cancelled",
            "phase": "cancelled",
            "updatedAt": finished_at,
            "finishedAt": finished_at,
            "runtimeStatus": "idle",
            "latestMessage": summary,
            "summary": summary,
            "toolCallCount": max(0, int(tool_call_count or 0)),
            "cancelRequested": True,
            "cancelRequestedAt": finished_at,
            "stopReason": str(reason or "").strip(),
            "error": "",
            "lastToolName": str(last_tool_name or "").strip(),
            "controlAction": "",
            "controlRequestedAt": "",
            "messages": _append_run_message(
                list(snapshot.get("messages") or []),
                _build_run_message(
                    run_id=run_id,
                    role="assistant",
                    content=str(summary or "").strip(),
                    timestamp=finished_at,
                    tool_calls=tool_calls,
                ),
            ),
        },
        clear_active=True,
    )


def _merge_run_state(run_id: str, payload: dict[str, Any], *, clear_active: bool = False) -> None:
    global _ACTIVE_RUN_ID
    normalized = str(run_id or "").strip()
    if not normalized:
        return
    terminal = False
    file_only_snapshot: dict[str, Any] | None = None
    active_run_id = ""
    with _RUN_STATE_LOCK:
        current = _RUN_STATES.get(normalized)
        if current is None:
            stored = load_manager_run_snapshot("self", normalized)
            if stored is not None:
                stored.update(payload)
                if clear_active:
                    active_run_id = ""
                else:
                    index_active = load_manager_active_run_snapshot("self")
                    if str((index_active or {}).get("runId") or "").strip() == normalized:
                        active_run_id = normalized
                file_only_snapshot = stored
                terminal = _is_terminal_run_snapshot(stored)
        else:
            current.update(payload)
            terminal = _is_terminal_run_snapshot(current)
            if clear_active and _ACTIVE_RUN_ID == normalized:
                _ACTIVE_RUN_ID = None
            active_run_id = _ACTIVE_RUN_ID if _ACTIVE_RUN_ID else ""
    if file_only_snapshot is not None:
        persist_manager_run_snapshot("self", file_only_snapshot, active_run_id=active_run_id)
        return
    _publish_run_snapshot(normalized, terminal=terminal)


def _get_run_internal(run_id: str) -> dict[str, Any]:
    normalized = str(run_id or "").strip()
    if not normalized:
        return {}
    with _RUN_STATE_LOCK:
        payload = _RUN_INTERNALS.get(normalized) or {}
        return payload if isinstance(payload, dict) else {}


def _set_run_internal_value(run_id: str, key: str, value: Any) -> None:
    normalized = str(run_id or "").strip()
    if not normalized or not key:
        return
    with _RUN_STATE_LOCK:
        bucket = _RUN_INTERNALS.setdefault(normalized, {})
        if isinstance(bucket, dict):
            bucket[key] = value


def _clear_run_internal(run_id: str) -> None:
    normalized = str(run_id or "").strip()
    if not normalized:
        return
    with _RUN_STATE_LOCK:
        _RUN_INTERNALS.pop(normalized, None)


def _finalize_terminal_run_snapshot(run_id: str) -> dict[str, Any] | None:
    internal = _get_run_internal(run_id)
    preflight = internal.get("preflight") if isinstance(internal.get("preflight"), dict) else {}
    manifest = _finalize_rollback_manifest(run_id, preflight)
    _clear_run_internal(run_id)
    return manifest


def _current_run_control_reason(run_id: str) -> str:
    snapshot = get_self_evolution_run_snapshot(run_id) or {}
    if str(snapshot.get("status") or "").strip().lower() != "stopping":
        return ""
    action = str(snapshot.get("controlAction") or "").strip().lower()
    if action not in {"pause", "terminate"}:
        return ""
    return str(snapshot.get("stopReason") or "").strip()


def _build_resume_user_message(goal: str) -> str:
    normalized_goal = str(goal or "").strip() or DEFAULT_SELF_EVOLUTION_GOAL
    return text_for(
        get_web_language(),
        zh=f"继续这一轮自进化\n目标：{normalized_goal}",
        en=f"Resume this self-evolution pass\nGoal: {normalized_goal}",
    )


def _build_run_message(
    *,
    run_id: str,
    role: str,
    content: str,
    timestamp: str,
    tool_calls: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    stamp = str(timestamp or _now_timestamp()).strip()
    payload: dict[str, Any] = {
        "id": f"{run_id}-message-{stamp}-{role}-{uuid4().hex[:8]}",
        "role": str(role or "").strip().lower(),
        "content": str(content or "").strip(),
        "timestamp": stamp,
    }
    normalized_tool_calls = [dict(item) for item in list(tool_calls or []) if isinstance(item, dict)]
    if normalized_tool_calls:
        payload["toolCalls"] = normalized_tool_calls
    return payload


def _append_run_message(messages: list[dict[str, Any]], message: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(message, dict) or not str(message.get("content") or "").strip():
        return list(messages or [])
    return [*list(messages or []), message]


def _append_run_message_locked(
    current: dict[str, Any],
    *,
    role: str,
    content: str,
    timestamp: str,
    tool_calls: list[dict[str, Any]] | None = None,
) -> None:
    current["messages"] = _append_run_message(
        list(current.get("messages") or []),
        _build_run_message(
            run_id=str(current.get("runId") or "web-self"),
            role=role,
            content=content,
            timestamp=timestamp,
            tool_calls=tool_calls,
        ),
    )


def _tool_calls_from_result(result: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(result, dict):
        return []
    seen: set[str] = set()
    calls: list[dict[str, Any]] = []
    for raw in list(result.get("tool_trace") or []):
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        calls.append({"name": name, "status": "done"})
    return calls[:6]


def _last_tool_name_from_result(result: dict[str, Any]) -> str:
    if not isinstance(result, dict):
        return ""
    for raw in reversed(list(result.get("tool_trace") or [])):
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        if name:
            return name
    return ""


def _build_result_message(result: dict[str, Any], fallback: str = "") -> str:
    if not isinstance(result, dict):
        return str(fallback or "").strip()
    for key in ("raw_output", "summary", "error", "message"):
        value = str(result.get(key) or "").strip()
        if value:
            return value
    return str(fallback or "").strip()


def _current_active_run_locked() -> dict[str, Any] | None:
    if not _ACTIVE_RUN_ID:
        return None
    return _RUN_STATES.get(_ACTIVE_RUN_ID)


def _latest_run_locked() -> dict[str, Any] | None:
    if _ACTIVE_RUN_ID and _RUN_STATES.get(_ACTIVE_RUN_ID):
        return _RUN_STATES[_ACTIVE_RUN_ID]
    if not _RUN_STATES:
        return None
    return max(
        _RUN_STATES.values(),
        key=lambda item: (
            str(item.get("updatedAt") or ""),
            str(item.get("startedAt") or ""),
            str(item.get("runId") or ""),
        ),
    )


def _snapshot_from_memory_locked(run_id: str, *, decorate: bool = True) -> dict[str, Any] | None:
    current = _RUN_STATES.get(run_id)
    if current is None:
        return None
    snapshot = _clone_payload(current)
    if decorate:
        return _decorate_runtime_snapshot(snapshot)
    return snapshot


def _persist_self_snapshot(run_id: str, *, decorate: bool = True) -> dict[str, Any] | None:
    with _RUN_STATE_LOCK:
        snapshot = _snapshot_from_memory_locked(run_id, decorate=decorate)
        active_run_id = _ACTIVE_RUN_ID if _ACTIVE_RUN_ID else ""
    if snapshot is None:
        return None
    return persist_manager_run_snapshot("self", snapshot, active_run_id=active_run_id)


def _publish_run_snapshot(run_id: str, *, terminal: bool = False) -> None:
    snapshot = _persist_self_snapshot(run_id)
    if snapshot is None:
        return
    event = {
        "type": "self_evolution_run",
        "runId": run_id,
        "snapshot": snapshot,
        "terminal": terminal or _is_terminal_run_snapshot(snapshot),
    }
    with _RUN_SUBSCRIBERS_LOCK:
        subscribers = list(_RUN_SUBSCRIBERS.get(run_id) or [])
    for subscriber in subscribers:
        try:
            subscriber.put_nowait(event)
        except queue.Full:
            try:
                subscriber.get_nowait()
            except queue.Empty:
                pass
            try:
                subscriber.put_nowait(event)
            except queue.Full:
                continue


def _register_run_subscriber(run_id: str, subscriber: queue.Queue[dict[str, Any]]) -> None:
    with _RUN_SUBSCRIBERS_LOCK:
        bucket = _RUN_SUBSCRIBERS.setdefault(run_id, set())
        bucket.add(subscriber)


def _unregister_run_subscriber(run_id: str, subscriber: queue.Queue[dict[str, Any]]) -> None:
    with _RUN_SUBSCRIBERS_LOCK:
        bucket = _RUN_SUBSCRIBERS.get(run_id)
        if not bucket:
            return
        bucket.discard(subscriber)
        if not bucket:
            _RUN_SUBSCRIBERS.pop(run_id, None)


def _is_terminal_run_snapshot(payload: dict[str, Any]) -> bool:
    status = str(payload.get("status") or "").strip().lower()
    return status in _RUN_FINAL_STATUSES | {"paused"}


def _snapshot_signature(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _decorate_self_snapshot_fields(payload: dict[str, Any]) -> dict[str, Any]:
    lang = get_web_language()
    rollback = payload.get("rollback") if isinstance(payload.get("rollback"), dict) else {}
    rollback_status = str(rollback.get("status") or "unavailable").strip().lower() or "unavailable"
    phase = str(payload.get("phase") or payload.get("status") or "idle").strip().lower() or "idle"
    status = str(payload.get("status") or "idle").strip().lower() or "idle"
    payload["runSemantics"] = {
        "runStatus": status,
        "runStatusLabel": _self_status_label(status, lang=lang),
        "phase": phase,
        "phaseLabel": _self_status_label(phase, lang=lang),
        "rollbackState": rollback_status,
        "rollbackStateLabel": _rollback_state_label(rollback_status, lang=lang),
        "rollbackSummary": str(rollback.get("reason") or "").strip(),
    }
    payload["actionStates"] = _self_action_states(payload, lang=lang)
    return payload


def _self_action_states(payload: dict[str, Any], *, lang: str) -> dict[str, dict[str, Any]]:
    status = str(payload.get("status") or "").strip().lower()
    runtime_status = str(payload.get("runtimeStatus") or "").strip().lower()
    control_action = str(payload.get("controlAction") or "").strip().lower()
    rollback = payload.get("rollback") if isinstance(payload.get("rollback"), dict) else {}
    rollback_status = str(rollback.get("status") or "").strip().lower()
    is_final = status in _RUN_FINAL_STATUSES

    def enabled_state() -> dict[str, Any]:
        return {"enabled": True, "reason": ""}

    def disabled_state(reason: str) -> dict[str, Any]:
        return {"enabled": False, "reason": reason}

    if status in {"queued", "running"} and control_action != "pause" and status != "stopping":
        pause_state = enabled_state()
    elif status == "paused":
        pause_state = disabled_state(
            text_for(lang, zh="这一轮已经暂停，可以直接继续。", en="This pass is already paused and can be resumed directly.")
        )
    elif is_final:
        pause_state = disabled_state(
            text_for(lang, zh="这一轮已经结束，不能再暂停。", en="This pass is already finished and cannot be paused.")
        )
    elif status == "stopping" or control_action == "pause" or runtime_status == "pausing":
        pause_state = disabled_state(
            text_for(lang, zh="暂停请求已经发出，等待当前安全点收口。", en="Pause has already been requested. Wait for the current safe point to close.")
        )
    else:
        pause_state = disabled_state(
            text_for(lang, zh="当前状态不能再发起暂停。", en="The current state cannot accept another pause request.")
        )

    if status == "paused":
        resume_state = enabled_state()
    elif is_final:
        resume_state = disabled_state(
            text_for(lang, zh="这一轮已经结束，不能再继续。", en="This pass is already finished and cannot be resumed.")
        )
    else:
        resume_state = disabled_state(
            text_for(lang, zh="只有已暂停的这一轮才能继续。", en="Only a paused pass can be resumed.")
        )

    if status in {"queued", "running", "paused"}:
        terminate_state = enabled_state()
    elif is_final:
        terminate_state = disabled_state(
            text_for(lang, zh="这一轮已经结束，无需再次终止。", en="This pass is already finished and does not need to be terminated again.")
        )
    else:
        terminate_state = disabled_state(
            text_for(lang, zh="当前正在收束这一轮，请等它结束。", en="This pass is already closing down. Wait for it to finish.")
        )

    if status in _RUN_LOCKED_STATUSES:
        rollback_state = disabled_state(
            text_for(lang, zh="要等这一轮先收口，才会生成可执行回滚。", en="Wait for this pass to close before automatic rollback becomes available.")
        )
    elif rollback_status == "available":
        rollback_state = enabled_state()
    elif rollback_status == "blocked":
        rollback_state = disabled_state(
            str(rollback.get("reason") or "")
            or text_for(lang, zh="这轮回滚已被后续改动污染，需要转交处理。", en="Later edits contaminated this rollback and it now needs handoff handling.")
        )
    elif rollback_status == "rolled_back":
        rollback_state = disabled_state(
            text_for(lang, zh="这轮改动已经回滚完成。", en="This pass has already been rolled back.")
        )
    else:
        rollback_state = disabled_state(
            str(rollback.get("reason") or "")
            or text_for(lang, zh="当前还没有可执行的回滚清单。", en="There is no runnable rollback manifest yet.")
        )

    if rollback_status == "blocked":
        handoff_state = enabled_state()
    else:
        handoff_state = disabled_state(
            text_for(
                lang,
                zh="只有出现回滚冲突时，才需要把这轮交接给会话 agent。",
                en="Rollback handoff is only needed when this pass is blocked by a rollback conflict.",
            )
        )

    return {
        "pause": pause_state,
        "resume": resume_state,
        "terminate": terminate_state,
        "rollback": rollback_state,
        "handoff": handoff_state,
    }


def _self_status_label(status: str, *, lang: str) -> str:
    normalized = str(status or "").strip().lower() or "idle"
    mapping = {
        "idle": text_for(lang, zh="空闲", en="Idle"),
        "queued": text_for(lang, zh="已排队", en="Queued"),
        "running": text_for(lang, zh="进行中", en="Running"),
        "reading": text_for(lang, zh="读现场", en="Reading"),
        "thinking": text_for(lang, zh="想下一步", en="Thinking"),
        "tooling": text_for(lang, zh="调用工具", en="Using tools"),
        "editing": text_for(lang, zh="改实现", en="Editing"),
        "verifying": text_for(lang, zh="做验证", en="Verifying"),
        "answering": text_for(lang, zh="收结论", en="Wrapping up"),
        "paused": text_for(lang, zh="已暂停", en="Paused"),
        "stopping": text_for(lang, zh="等待收口", en="Stopping"),
        "done": text_for(lang, zh="已完成", en="Done"),
        "failed": text_for(lang, zh="已失败", en="Failed"),
        "cancelled": text_for(lang, zh="已终止", en="Cancelled"),
        "blocked": text_for(lang, zh="受阻", en="Blocked"),
        "available": text_for(lang, zh="可执行", en="Available"),
        "unavailable": text_for(lang, zh="暂不可用", en="Unavailable"),
    }
    return mapping.get(normalized, normalized)


def _rollback_state_label(status: str, *, lang: str) -> str:
    normalized = str(status or "").strip().lower() or "unavailable"
    mapping = {
        "available": text_for(lang, zh="可安全回滚", en="Safe rollback ready"),
        "blocked": text_for(lang, zh="回滚冲突待处理", en="Rollback blocked by conflict"),
        "rolled_back": text_for(lang, zh="已完成回滚", en="Rolled back"),
        "unavailable": text_for(lang, zh="暂不可回滚", en="Rollback unavailable"),
    }
    return mapping.get(normalized, normalized)


def _decorate_runtime_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    runtime = _load_runtime_state()
    status = str(payload.get("status") or "").strip().lower()
    if status in _RUN_FINAL_STATUSES | {"paused"}:
        return _decorate_self_snapshot_fields(payload)
    attention = get_session_state().get_attention_snapshot()

    current_goal = str((runtime or {}).get("current_goal") or "").strip()
    last_tool_name = str((runtime or {}).get("last_tool_name") or "").strip()
    runtime_status = str((runtime or {}).get("runtime_status") or (runtime or {}).get("status") or "").strip().lower()
    updated_at = str((runtime or {}).get("updated_at") or "").strip()
    reading_task = str(attention.get("reading_task") or "").strip()
    reading_hint = str(attention.get("reading_recommendation") or "").strip()
    reading_sufficiency = str(attention.get("reading_sufficiency") or "").strip()
    convergence_state = str(attention.get("convergence_state") or "").strip().lower()
    next_tool_intent = str(attention.get("next_tool_intent") or "").strip()
    stop_reason = str(attention.get("stop_reason") or "").strip()

    if current_goal:
        payload["currentGoal"] = current_goal
    if last_tool_name:
        payload["lastToolName"] = last_tool_name
    if runtime_status:
        payload["runtimeStatus"] = runtime_status
    if updated_at:
        payload["updatedAt"] = updated_at

    derived_phase = _derive_self_live_phase(
        status=status,
        runtime_status=runtime_status,
        reading_task=reading_task,
        last_tool_name=last_tool_name,
        convergence_state=convergence_state,
    )
    if derived_phase:
        payload["phase"] = derived_phase

    current_task = _derive_self_current_task(
        phase=derived_phase or str(payload.get("phase") or "").strip().lower(),
        latest_message=str(payload.get("latestMessage") or "").strip(),
        reading_task=reading_task,
        reading_hint=reading_hint,
        next_tool_intent=next_tool_intent,
        last_tool_name=last_tool_name,
        stop_reason=stop_reason,
    )
    if current_task:
        payload["currentTask"] = current_task
    if reading_task:
        payload["readingTask"] = reading_task
    if reading_hint:
        payload["readingHint"] = reading_hint
    if reading_sufficiency:
        payload["readingSufficiency"] = reading_sufficiency
    if convergence_state:
        payload["convergenceState"] = convergence_state
    if next_tool_intent:
        payload["nextToolIntent"] = next_tool_intent
    if stop_reason and not str(payload.get("stopReason") or "").strip():
        payload["stopReason"] = stop_reason
    return _decorate_self_snapshot_fields(payload)


def _derive_self_live_phase(
    *,
    status: str,
    runtime_status: str,
    reading_task: str,
    last_tool_name: str,
    convergence_state: str,
) -> str:
    if status in {"queued", "stopping", "paused"}:
        return status
    if reading_task:
        return "reading"
    if runtime_status in {"thinking", "planning"}:
        return "thinking"
    if runtime_status in {"reading"}:
        return "reading"
    if runtime_status in {"editing", "patching", "writing"}:
        return "editing"
    if runtime_status in {"verifying", "testing", "validating"}:
        return "verifying"
    if runtime_status in {"answering", "responding"}:
        return "answering"
    if last_tool_name or runtime_status in {"tooling", "calling_tools", "calling-tools"}:
        return "tooling"
    if convergence_state in {"converged", "ready_to_answer"}:
        return "answering"
    return "running"


def _derive_self_current_task(
    *,
    phase: str,
    latest_message: str,
    reading_task: str,
    reading_hint: str,
    next_tool_intent: str,
    last_tool_name: str,
    stop_reason: str,
) -> str:
    if phase == "stopping":
        return stop_reason or latest_message or "Stopping current self-evolution pass."
    if phase == "reading":
        return reading_task or reading_hint or latest_message
    if phase == "tooling":
        return next_tool_intent or (f"tool:{last_tool_name}" if last_tool_name else latest_message)
    if phase == "verifying":
        return next_tool_intent or latest_message or "Verifying the latest changes."
    if phase == "editing":
        return next_tool_intent or latest_message or "Editing the current implementation."
    if phase == "thinking":
        return next_tool_intent or reading_hint or latest_message or "Thinking through the next step."
    if phase == "answering":
        return next_tool_intent or latest_message or "Preparing the current conclusion."
    return next_tool_intent or latest_message or reading_hint or reading_task


def _capture_preflight_state(run_id: str) -> dict[str, Any]:
    run_dir = ROLLBACK_ROOT / run_id
    backup_dir = run_dir / "backups"
    manifest_path = run_dir / "rollback_manifest.json"
    backup_dir.mkdir(parents=True, exist_ok=True)
    base_rev = _git_head_rev()
    dirty_entries: dict[str, dict[str, Any]] = {}
    for path, status in _git_status_entries().items():
        abs_path = (PROJECT_ROOT / path).resolve()
        exists_before = abs_path.exists() and abs_path.is_file()
        backup_path = ""
        pre_hash = ""
        backup_error = ""
        if exists_before:
            try:
                pre_hash = _hash_file(abs_path)
                backup_path = _backup_file(abs_path, backup_dir)
            except OSError as exc:
                backup_error = str(exc)
        dirty_entries[path] = {
            "path": path,
            "status": status,
            "trackedBefore": status != "??",
            "existsBefore": exists_before,
            "preHash": pre_hash,
            "backupPath": backup_path,
            "backupError": backup_error,
        }
    return {
        "runDir": str(run_dir),
        "backupDir": str(backup_dir),
        "manifestPath": str(manifest_path),
        "baseRev": base_rev,
        "dirtyEntries": dirty_entries,
    }


def _finalize_rollback_manifest(run_id: str, preflight: dict[str, Any]) -> dict[str, Any] | None:
    lang = get_web_language()
    if not isinstance(preflight, dict):
        return None
    dirty_entries = preflight.get("dirtyEntries") if isinstance(preflight.get("dirtyEntries"), dict) else {}
    post_status = _git_status_entries()
    base_rev = str(preflight.get("baseRev") or "")
    touched_files: list[dict[str, Any]] = []
    candidate_paths = set(dirty_entries.keys()) | set(post_status.keys())
    for path in sorted(candidate_paths):
        pre_entry = dirty_entries.get(path) if isinstance(dirty_entries.get(path), dict) else None
        post_state = post_status.get(path, "")
        abs_path = (PROJECT_ROOT / path).resolve()
        current_exists = abs_path.exists() and abs_path.is_file()
        current_hash = _hash_file(abs_path) if current_exists else ""
        if pre_entry is None:
            if not post_state:
                continue
            existed_before = _path_exists_in_git_revision(path, base_rev)
            tracked_before = existed_before
            restore_source = "git" if existed_before else "delete"
            touched_files.append(
                {
                    "path": path,
                    "changeType": (
                        "created"
                        if not existed_before and current_exists
                        else "deleted"
                        if existed_before and not current_exists
                        else "modified"
                    ),
                    "trackedBefore": tracked_before,
                    "existedBefore": existed_before,
                    "preHash": "",
                    "postHash": current_hash,
                    "postExists": current_exists,
                    "backupPath": "",
                    "restoreSource": restore_source,
                    "statusAfter": post_state,
                    "conflict": False,
                    "conflictReason": "",
                }
            )
            continue

        existed_before = bool(pre_entry.get("existsBefore"))
        pre_hash = str(pre_entry.get("preHash") or "")
        changed = existed_before != current_exists
        if not changed and existed_before:
            changed = pre_hash != current_hash
        if not changed:
            continue
        if not existed_before:
            change_type = "created" if current_exists else "unchanged"
            restore_source = "delete"
        elif not current_exists:
            change_type = "deleted"
            restore_source = "backup" if str(pre_entry.get("backupPath") or "") else "delete"
        else:
            change_type = "modified"
            restore_source = "backup" if str(pre_entry.get("backupPath") or "") else "delete"
        touched_files.append(
            {
                "path": path,
                "changeType": change_type,
                "trackedBefore": bool(pre_entry.get("trackedBefore")),
                "existedBefore": existed_before,
                "preHash": pre_hash,
                "postHash": current_hash,
                "postExists": current_exists,
                "backupPath": str(pre_entry.get("backupPath") or ""),
                "restoreSource": restore_source,
                "statusAfter": post_state,
                "conflict": False,
                "conflictReason": "",
            }
        )

    rollback_state = _build_rollback_state(
        lang=lang,
        status="available" if touched_files else "unavailable",
        reason=(
            text_for(
                lang,
                zh="可以把这轮网页自进化回滚到启动前的文件状态。",
                en="This web self-evolution pass can be rolled back to its pre-run file state.",
            )
            if touched_files
            else text_for(
                lang,
                zh="这一轮没有留下需要回滚的文件差异。",
                en="This run did not leave any file diff that needs rollback.",
            )
        ),
        base_rev=base_rev,
        touched_files=touched_files,
        conflict_files=[],
        rolled_back_at="",
    )
    manifest_payload = {
        "version": 1,
        "runId": run_id,
        "generatedAt": _now_timestamp(),
        "baseRev": base_rev,
        "display": rollback_state,
        "entries": touched_files,
    }
    manifest_path = Path(str(preflight.get("manifestPath") or "")).resolve()
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return rollback_state


def _build_rollback_state(
    *,
    lang: str,
    status: str,
    reason: str,
    base_rev: str,
    touched_files: list[dict[str, Any]],
    conflict_files: list[dict[str, Any]],
    rolled_back_at: str,
) -> dict[str, Any]:
    enriched_touched = []
    conflict_map = {str(item.get("path") or ""): item for item in conflict_files}
    for item in touched_files:
        conflict = conflict_map.get(str(item.get("path") or ""))
        enriched_touched.append(
            {
                "path": str(item.get("path") or ""),
                "changeType": str(item.get("changeType") or "modified"),
                "trackedBefore": bool(item.get("trackedBefore")),
                "existedBefore": bool(item.get("existedBefore")),
                "statusAfter": str(item.get("statusAfter") or ""),
                "preHash": str(item.get("preHash") or ""),
                "postHash": str(item.get("postHash") or ""),
                "postExists": bool(item.get("postExists")),
                "conflict": bool(conflict),
                "conflictReason": str((conflict or {}).get("reason") or ""),
            }
        )
    return {
        "status": status,
        "reason": reason,
        "baseRev": base_rev,
        "rolledBackAt": rolled_back_at,
        "entryCount": len(enriched_touched),
        "touchedFiles": enriched_touched,
        "conflictFiles": [
            {
                "path": str(item.get("path") or ""),
                "reason": str(item.get("reason") or ""),
                "currentHash": str(item.get("currentHash") or ""),
                "expectedHash": str(item.get("expectedHash") or ""),
            }
            for item in conflict_files
        ],
        "blockedHint": (
            text_for(
                lang,
                zh="如果这些文件已经被后续改动污染，请把这次回滚交给会话 agent 继续处理。",
                en="If later edits contaminated these files, hand this rollback off to the session agent instead.",
            )
            if status == "blocked"
            else ""
        ),
    }


def _initial_rollback_state(lang: str, *, base_rev: str) -> dict[str, Any]:
    return _build_rollback_state(
        lang=lang,
        status="unavailable",
        reason=text_for(
            lang,
            zh="这一轮还没结束，暂时不能生成安全回滚清单。",
            en="This pass has not finished yet, so a safe rollback manifest is not available.",
        ),
        base_rev=base_rev,
        touched_files=[],
        conflict_files=[],
        rolled_back_at="",
    )


def _detect_rollback_conflicts(
    state: dict[str, Any],
    *,
    entries: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    rollback_entries = entries
    if rollback_entries is None:
        manifest = _load_rollback_manifest(state)
        rollback_entries = manifest.get("entries") if isinstance(manifest.get("entries"), list) else []
    if not rollback_entries:
        rollback = state.get("rollback") if isinstance(state.get("rollback"), dict) else {}
        rollback_entries = rollback.get("touchedFiles") if isinstance(rollback.get("touchedFiles"), list) else []
    conflicts: list[dict[str, Any]] = []
    for item in rollback_entries:
        path = str(item.get("path") or "").strip()
        if not path:
            continue
        abs_path = (PROJECT_ROOT / path).resolve()
        current_exists = abs_path.exists() and abs_path.is_file()
        current_hash = _hash_file(abs_path) if current_exists else ""
        expected_exists = bool(item.get("postExists"))
        expected_hash = str(item.get("postHash") or "")
        if current_exists != expected_exists or current_hash != expected_hash:
            conflicts.append(
                {
                    "path": path,
                    "reason": text_for(
                        get_web_language(),
                        zh="这个文件在进化后又被修改过了。",
                        en="This file changed again after the self-evolution pass.",
                    ),
                    "currentHash": current_hash,
                    "expectedHash": expected_hash,
                }
            )
    return conflicts


def _apply_rollback_entries(state: dict[str, Any], touched_files: list[dict[str, Any]]) -> None:
    base_rev = str(((state.get("rollback") or {}) if isinstance(state.get("rollback"), dict) else {}).get("baseRev") or "")
    for item in touched_files:
        path = str(item.get("path") or "").strip()
        if not path:
            continue
        abs_path = (PROJECT_ROOT / path).resolve()
        restore_source = str(item.get("restoreSource") or "").strip().lower()
        existed_before = bool(item.get("existedBefore"))
        backup_path = str(item.get("backupPath") or "").strip()
        if restore_source == "git" and existed_before and base_rev:
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            _run_git(["restore", "--source", base_rev, "--worktree", "--", path])
            continue
        if restore_source == "backup" and backup_path:
            backup_file = Path(backup_path).resolve()
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(backup_file, abs_path)
            continue
        if abs_path.exists():
            abs_path.unlink()


def _build_session_handoff_message(state: dict[str, Any]) -> str:
    rollback = state.get("rollback") if isinstance(state.get("rollback"), dict) else {}
    conflicts = rollback.get("conflictFiles") if isinstance(rollback.get("conflictFiles"), list) else []
    touched = rollback.get("touchedFiles") if isinstance(rollback.get("touchedFiles"), list) else []
    lines = [
        "请接手一条网页自进化回滚请求。",
        "",
        f"- run_id: {state.get('runId') or '--'}",
        f"- goal: {state.get('goal') or '--'}",
        f"- status: {state.get('status') or '--'}",
        f"- rollback_status: {rollback.get('status') or '--'}",
        f"- rollback_reason: {rollback.get('reason') or '--'}",
        f"- started_at: {state.get('startedAt') or '--'}",
        f"- finished_at: {state.get('finishedAt') or '--'}",
        "",
        "请先判断这些文件是否还能安全恢复到进化前状态；如果不能安全恢复，就给出最小人工处理建议。",
        "不要覆盖不确定来源的后续改动。",
        "",
        "touched_files:",
    ]
    if touched:
        lines.extend(
            f"- {item.get('path') or '--'} | change={item.get('changeType') or '--'} | conflict={bool(item.get('conflict'))}"
            for item in touched
        )
    else:
        lines.append("- --")
    lines.append("")
    lines.append("conflicts:")
    if conflicts:
        lines.extend(f"- {item.get('path') or '--'} | {item.get('reason') or '--'}" for item in conflicts)
    else:
        lines.append("- --")
    return "\n".join(lines).strip()


def _load_rollback_manifest(state: dict[str, Any]) -> dict[str, Any]:
    rollback = state.get("rollback") if isinstance(state.get("rollback"), dict) else {}
    artifacts = state.get("artifacts") if isinstance(state.get("artifacts"), dict) else {}
    manifest_path = Path(str(artifacts.get("manifestPath") or "")).resolve() if artifacts.get("manifestPath") else None
    payload: dict[str, Any] = {}
    if manifest_path is not None:
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {}
        if isinstance(raw, dict):
            payload = raw
    display = payload.get("display") if isinstance(payload.get("display"), dict) else (
        payload if "status" in payload else rollback
    )
    if not isinstance(display, dict):
        display = rollback
    entries = payload.get("entries") if isinstance(payload.get("entries"), list) else []
    return {
        "display": display if isinstance(display, dict) else {},
        "entries": entries,
        "baseRev": str(payload.get("baseRev") or display.get("baseRev") or rollback.get("baseRev") or ""),
    }


def _require_run_snapshot(run_id: str) -> dict[str, Any]:
    lang = get_web_language()
    snapshot = get_self_evolution_run_snapshot(run_id)
    if snapshot is None:
        raise SelfEvolutionRunNotFoundError(
            text_for(lang, zh="未找到这条自进化记录。", en="Self-evolution run not found.")
        )
    return snapshot


def _require_terminal_run(run_id: str) -> dict[str, Any]:
    lang = get_web_language()
    state = _require_run_snapshot(run_id)
    if str(state.get("status") or "").strip().lower() in _RUN_LOCKED_STATUSES:
        raise SelfEvolutionRunBusyError(
            text_for(
                lang,
                zh="当前这轮还在运行，先等它收口后再回滚。",
                en="This pass is still running. Wait for it to close before rollback.",
            )
        )
    return state


def _git_status_entries() -> dict[str, str]:
    output = _run_git(["-c", "status.renames=false", "status", "--porcelain=v1", "--untracked-files=all"], capture_text=True)
    entries: dict[str, str] = {}
    for raw_line in output.splitlines():
        line = raw_line.rstrip()
        if len(line) < 4:
            continue
        status = line[:2]
        path = line[3:].strip().replace("\\", "/")
        if path:
            entries[path] = status
    return entries


def _git_head_rev() -> str:
    return _run_git(["rev-parse", "HEAD"], capture_text=True).strip()


def _path_exists_in_git_revision(path: str, revision: str) -> bool:
    normalized_path = str(path or "").strip().replace("\\", "/")
    normalized_revision = str(revision or "").strip()
    if not normalized_path or not normalized_revision:
        return False
    completed = subprocess.run(
        ["git", "-C", str(PROJECT_ROOT), "cat-file", "-e", f"{normalized_revision}:{normalized_path}"],
        check=False,
        capture_output=True,
    )
    return completed.returncode == 0


def _run_git(args: list[str], *, capture_text: bool = False) -> str:
    completed = subprocess.run(
        ["git", "-C", str(PROJECT_ROOT), *args],
        check=True,
        capture_output=True,
        text=capture_text,
    )
    if capture_text:
        return completed.stdout
    return ""


def _backup_file(abs_path: Path, backup_dir: Path) -> str:
    relative = abs_path.resolve().relative_to(PROJECT_ROOT)
    target = backup_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(abs_path, target)
    return str(target)


def _hash_file(abs_path: Path) -> str:
    digest = hashlib.sha256()
    with abs_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _clone_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(payload, ensure_ascii=False))


def _load_runtime_state() -> dict[str, Any]:
    try:
        payload = json.loads(RUNTIME_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _encode_sse_event(event_name: str, payload: dict[str, Any]) -> str:
    body = json.dumps(payload, ensure_ascii=False)
    return f"event: {event_name}\ndata: {body}\n\n"


def _now_timestamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


_LOCAL_GET_ACTIVE_SELF_EVOLUTION_RUN = get_active_self_evolution_run
_LOCAL_GET_LATEST_SELF_EVOLUTION_RUN = get_latest_self_evolution_run
_LOCAL_GET_SELF_EVOLUTION_RUN_SNAPSHOT = get_self_evolution_run_snapshot
_LOCAL_STREAM_SELF_EVOLUTION_RUN_EVENTS = stream_self_evolution_run_events
_LOCAL_HAS_ACTIVE_SELF_EVOLUTION_RUN = has_active_self_evolution_run
_LOCAL_START_SELF_EVOLUTION_RUN = start_self_evolution_run
_LOCAL_REQUEST_PAUSE_SELF_EVOLUTION_RUN = request_pause_self_evolution_run
_LOCAL_RESUME_SELF_EVOLUTION_RUN = resume_self_evolution_run
_LOCAL_REQUEST_STOP_SELF_EVOLUTION_RUN = request_stop_self_evolution_run


def _stream_manager_self_events(run_id: str, initial_snapshot: dict[str, Any] | None = None):
    lang = get_web_language()
    normalized = str(run_id or "").strip()
    if not normalized:
        raise SelfEvolutionRunNotFoundError(
            text_for(lang, zh="未找到这条自进化记录。", en="Self-evolution run not found.")
        )

    snapshot = initial_snapshot or load_manager_run_snapshot("self", normalized)
    if snapshot is None:
        raise SelfEvolutionRunNotFoundError(
            text_for(lang, zh="未找到这条自进化记录。", en="Self-evolution run not found.")
        )

    last_signature = _snapshot_signature(snapshot)
    last_keepalive = time.monotonic()
    terminal = _is_terminal_run_snapshot(snapshot)
    yield _encode_sse_event(
        "self_evolution_run",
        {
            "type": "self_evolution_run",
            "runId": normalized,
            "snapshot": snapshot,
            "terminal": terminal,
        },
    )
    if terminal:
        return

    while True:
        latest = load_manager_run_snapshot("self", normalized)
        if latest is not None:
            signature = _snapshot_signature(latest)
            if signature != last_signature:
                last_signature = signature
                terminal = _is_terminal_run_snapshot(latest)
                yield _encode_sse_event(
                    "self_evolution_run",
                    {
                        "type": "self_evolution_run",
                        "runId": normalized,
                        "snapshot": latest,
                        "terminal": terminal,
                    },
                )
                last_keepalive = time.monotonic()
                if terminal:
                    break
        if time.monotonic() - last_keepalive >= _RUN_STREAM_HEARTBEAT_SECONDS:
            yield ": keep-alive\n\n"
            last_keepalive = time.monotonic()
        time.sleep(_RUN_STREAM_POLL_SECONDS)


def _submit_self_runtime_manager_command(command_type: str, *, run_id: str = "", payload: dict[str, Any] | None = None) -> dict[str, Any]:
    _ensure_runtime_manager_daemon()
    args: dict[str, Any] = {}
    if run_id:
        args["runId"] = run_id
    if payload is not None:
        args["payload"] = payload
    command = submit_command(command_type, args=args, requested_by="web_ui")
    result = wait_for_result(command["commandId"])
    if not bool(result.get("ok")):
        raise _map_runtime_manager_error(
            str(result.get("message") or "Runtime manager command failed."),
            str(result.get("errorType") or ""),
        )
    snapshot = result.get("snapshot") if isinstance(result.get("snapshot"), dict) else None
    if snapshot is not None:
        return snapshot
    target_run_id = str(result.get("runId") or run_id or "").strip()
    loaded = load_manager_run_snapshot("self", target_run_id) if target_run_id else None
    if loaded is not None:
        return loaded
    return {}


def get_active_self_evolution_run() -> dict[str, Any] | None:
    if _runtime_manager_live_control_enabled():
        snapshot = load_manager_active_run_snapshot("self")
        if snapshot is None:
            return None
        if str(snapshot.get("status") or "").strip().lower() not in _RUN_LOCKED_STATUSES:
            return None
        return _decorate_self_snapshot_fields(_clone_payload(snapshot))
    return _LOCAL_GET_ACTIVE_SELF_EVOLUTION_RUN()


def get_latest_self_evolution_run() -> dict[str, Any] | None:
    if _runtime_manager_live_control_enabled():
        snapshot = load_manager_latest_run_snapshot("self")
        if snapshot is None:
            return None
        return _decorate_self_snapshot_fields(_clone_payload(snapshot))
    return _LOCAL_GET_LATEST_SELF_EVOLUTION_RUN()


def get_self_evolution_run_snapshot(run_id: str) -> dict[str, Any] | None:
    if _runtime_manager_live_control_enabled():
        snapshot = load_manager_run_snapshot("self", run_id)
        if snapshot is None:
            return None
        return _decorate_self_snapshot_fields(_clone_payload(snapshot))
    return _LOCAL_GET_SELF_EVOLUTION_RUN_SNAPSHOT(run_id)


def stream_self_evolution_run_events(run_id: str, initial_snapshot: dict[str, Any] | None = None):
    if _runtime_manager_live_control_enabled():
        return _stream_manager_self_events(run_id, initial_snapshot=initial_snapshot)
    return _LOCAL_STREAM_SELF_EVOLUTION_RUN_EVENTS(run_id, initial_snapshot=initial_snapshot)


def has_active_self_evolution_run() -> bool:
    if _runtime_manager_live_control_enabled():
        snapshot = load_manager_active_run_snapshot("self")
        if snapshot is None:
            return False
        return str(snapshot.get("status") or "").strip().lower() in _RUN_LOCKED_STATUSES
    return _LOCAL_HAS_ACTIVE_SELF_EVOLUTION_RUN()


def start_self_evolution_run(payload: dict[str, Any]) -> dict[str, Any]:
    if _runtime_manager_live_control_enabled():
        lang = get_web_language()
        contract = get_workbench_contract()
        if not bool(contract.get("modeAvailability", {}).get("self_evolution")):
            raise SelfEvolutionRunValidationError(
                text_for(
                    lang,
                    zh="配置里没有启用 self_evolution，当前不能从网页启动这一轮。",
                    en="The current config does not enable self_evolution, so the web surface cannot launch this pass.",
                )
            )
        if has_running_sessions():
            raise SelfEvolutionRunBusyError(
                text_for(
                    lang,
                    zh="当前有网页会话还在运行，请等这一轮结束后再启动自进化。",
                    en="A web chat turn is still running. Wait for it to finish before launching self evolution.",
                )
            )
        active_supervised = get_active_supervised_run()
        if active_supervised is not None and str(active_supervised.get("status") or "").strip().lower() in {"queued", "running", "paused", "stopping"}:
            raise SelfEvolutionRunBusyError(
                text_for(
                    lang,
                    zh="当前已有监督任务在运行，请等监督任务结束后再启动自进化。",
                    en="A supervised run is already active. Wait for it to finish before launching self evolution.",
                )
            )
        return _submit_self_runtime_manager_command("start_self_evolution_run", payload=payload)
    return _LOCAL_START_SELF_EVOLUTION_RUN(payload)


def request_pause_self_evolution_run(run_id: str) -> dict[str, Any]:
    if _runtime_manager_live_control_enabled():
        return _submit_self_runtime_manager_command("pause_self_evolution_run", run_id=run_id)
    return _LOCAL_REQUEST_PAUSE_SELF_EVOLUTION_RUN(run_id)


def resume_self_evolution_run(run_id: str) -> dict[str, Any]:
    if _runtime_manager_live_control_enabled():
        if has_running_sessions():
            raise SelfEvolutionRunBusyError(
                text_for(
                    get_web_language(),
                    zh="当前有网页会话还在运行，请等这一轮结束后再继续自进化。",
                    en="A web chat turn is still running. Wait for it to finish before resuming self evolution.",
                )
            )
        return _submit_self_runtime_manager_command("resume_self_evolution_run", run_id=run_id)
    return _LOCAL_RESUME_SELF_EVOLUTION_RUN(run_id)


def request_stop_self_evolution_run(run_id: str) -> dict[str, Any]:
    if _runtime_manager_live_control_enabled():
        return _submit_self_runtime_manager_command("stop_self_evolution_run", run_id=run_id)
    return _LOCAL_REQUEST_STOP_SELF_EVOLUTION_RUN(run_id)
