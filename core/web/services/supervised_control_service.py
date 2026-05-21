"""Live supervised run control for the web workbench."""

from __future__ import annotations

import json
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from core.evaluation import (
    build_workbench_state,
    default_bundle_name,
    execute_gym_promotion_action,
    list_dataset_choices,
    load_gym_promotion_lifecycle,
    prepare_dataset_run,
    resolve_workbench_bundle_path,
    run_workbench_session,
    save_workbench_state,
)
from core.runtime_manager.command_queue import submit_command, wait_for_result
from core.runtime_manager.evolution_store import (
    load_active_run_snapshot as load_manager_active_run_snapshot,
    load_run_snapshot as load_manager_run_snapshot,
    persist_run_snapshot as persist_manager_run_snapshot,
)

from .evolution_service import get_run, get_workbench_state_payload
from .i18n import get_web_language, text_for


PROJECT_ROOT = Path(__file__).resolve().parents[3]
_RUN_STATE_LOCK = threading.Lock()
_RUN_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="web-supervised-run")
_RUN_SUBSCRIBERS_LOCK = threading.Lock()
_RUN_SUBSCRIBERS: dict[str, set[queue.Queue[dict[str, Any]]]] = {}
_RUN_STATES: dict[str, dict[str, Any]] = {}
_RUN_CONTROLLERS: dict[str, "_SupervisedRunController"] = {}
_ACTIVE_RUN_ID: str | None = None
_RUN_STREAM_HEARTBEAT_SECONDS = 15.0
_RUN_STREAM_QUEUE_SIZE = 16
_EVENT_TAIL_LIMIT = 12
_ACTIVE_RUN_STATUSES = {"queued", "running", "paused", "stopping"}


class SupervisedRunBusyError(RuntimeError):
    """Raised when a supervised run is already active."""


class SupervisedRunValidationError(ValueError):
    """Raised when a start request is invalid."""


class SupervisedRunNotFoundError(ValueError):
    """Raised when a requested supervised run cannot be found."""


class SupervisedRunActionError(RuntimeError):
    """Raised when a supervised proposal action cannot be executed."""


class SupervisedRunStateError(RuntimeError):
    """Raised when a run control request is invalid for the current state."""


class _SupervisedRunInterrupted(RuntimeError):
    """Raised when the live run thread should exit without being marked failed."""


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
    if normalized == "SupervisedRunBusyError":
        return SupervisedRunBusyError(message)
    if normalized == "SupervisedRunNotFoundError":
        return SupervisedRunNotFoundError(message)
    if normalized == "SupervisedRunStateError":
        return SupervisedRunStateError(message)
    if normalized == "SupervisedRunActionError":
        return SupervisedRunActionError(message)
    return SupervisedRunValidationError(message)


class _SupervisedRunController:
    def __init__(self) -> None:
        self.condition = threading.Condition()
        self.pause_requested = False
        self.stop_requested = False

    def request_pause(self) -> None:
        with self.condition:
            self.pause_requested = True
            self.condition.notify_all()

    def request_resume(self) -> None:
        with self.condition:
            self.pause_requested = False
            self.condition.notify_all()

    def request_stop(self) -> None:
        with self.condition:
            self.stop_requested = True
            self.condition.notify_all()


def get_supervised_workbench() -> dict[str, Any]:
    """Return workbench defaults, datasets, and current live run when present."""

    return {
        "defaultBundleName": default_bundle_name(),
        "savedState": get_workbench_state_payload(project_root=PROJECT_ROOT),
        "datasets": [_dataset_payload(item) for item in list_dataset_choices(PROJECT_ROOT)],
        "activeRun": get_active_supervised_run(),
    }


def start_supervised_run(payload: dict[str, Any]) -> dict[str, Any]:
    """Start a live supervised run and return the initial snapshot."""

    lang = get_web_language()
    source_kind = str(payload.get("sourceKind") or "").strip().lower()
    keep_worktree = bool(payload.get("keepWorktree"))
    dataset_name = str(payload.get("datasetName") or "").strip()
    dataset_limit = _coerce_dataset_limit(payload.get("datasetLimit"))
    bundle_name = str(payload.get("bundleName") or "").strip()

    if source_kind not in {"dataset", "bundle"}:
        raise SupervisedRunValidationError(
            text_for(lang, zh="请选择监督运行来源。", en="Choose a supervised run source.")
        )

    if source_kind == "dataset":
        if not dataset_name:
            raise SupervisedRunValidationError(
                text_for(lang, zh="请选择一个数据集。", en="Choose a dataset.")
            )
        prepared = prepare_dataset_run(PROJECT_ROOT, dataset_name, dataset_limit)
        if not prepared.runnable:
            raise SupervisedRunValidationError(
                prepared.blocked_message
                or text_for(lang, zh="当前数据集暂不可运行。", en="This dataset is not runnable right now.")
            )
        bundle_name = prepared.bundle_name
    else:
        if not bundle_name:
            raise SupervisedRunValidationError(
                text_for(lang, zh="请输入监督 bundle 名称。", en="Enter a supervised bundle name.")
            )
        bundle_path = resolve_workbench_bundle_path(PROJECT_ROOT, bundle_name)
        if not bundle_path.exists():
            raise SupervisedRunValidationError(
                text_for(
                    lang,
                    zh=f"监督 bundle 不存在：{bundle_name}",
                    en=f"Supervised bundle does not exist: {bundle_name}",
                )
            )
        dataset_name = ""
        dataset_limit = None

    context = {
        "runId": f"web-supervised-{uuid4().hex[:12]}",
        "lang": lang,
        "sourceKind": source_kind,
        "datasetName": dataset_name,
        "datasetLimit": dataset_limit,
        "bundleName": bundle_name,
        "keepWorktree": keep_worktree,
        "startedAt": _now_timestamp(),
    }
    state = _initial_run_state(context)

    with _RUN_STATE_LOCK:
        active = _current_active_run_locked()
        if active is not None and str(active.get("status") or "").strip().lower() in _ACTIVE_RUN_STATUSES:
            raise SupervisedRunBusyError(
                text_for(
                    lang,
                    zh="当前已有监督任务在运行，请等这一轮结束后再启动新的任务。",
                    en="A supervised run is already active. Wait for it to finish before starting another one.",
                )
            )
        _RUN_STATES[context["runId"]] = state
        _RUN_CONTROLLERS[context["runId"]] = _SupervisedRunController()
        global _ACTIVE_RUN_ID
        _ACTIVE_RUN_ID = context["runId"]

    save_workbench_state(
        PROJECT_ROOT,
        build_workbench_state(
            source_kind=source_kind,
            dataset_name=dataset_name or None,
            dataset_limit=dataset_limit,
            bundle_name=bundle_name,
            keep_worktree=keep_worktree,
        ),
    )
    _publish_run_snapshot(context["runId"])

    try:
        _RUN_EXECUTOR.submit(_run_supervised_session, context)
    except Exception as exc:
        _mark_run_failed(
            context["runId"],
            text_for(
                lang,
                zh=f"无法启动监督任务：{type(exc).__name__}: {exc}",
                en=f"Failed to start supervised run: {type(exc).__name__}: {exc}",
            ),
        )
        raise
    return get_supervised_run_snapshot(context["runId"])


def get_active_supervised_run() -> dict[str, Any] | None:
    """Return the current active supervised run snapshot."""

    with _RUN_STATE_LOCK:
        active = _current_active_run_locked()
        if active is None:
            return None
        return _decorate_supervised_snapshot(_clone_locked(active))


def get_supervised_run_snapshot(run_id: str) -> dict[str, Any]:
    """Return a supervised run snapshot by its live run id."""

    with _RUN_STATE_LOCK:
        payload = _RUN_STATES.get(str(run_id or "").strip())
        if payload is None:
            raise SupervisedRunNotFoundError("Supervised run not found.")
        return _decorate_supervised_snapshot(_clone_locked(payload))


def request_pause_supervised_run(run_id: str) -> dict[str, Any]:
    """Pause one active supervised run at the next safe checkpoint."""

    lang = get_web_language()
    normalized = str(run_id or "").strip()
    if not normalized:
        raise SupervisedRunValidationError(text_for(lang, zh="缺少监督 run id。", en="Missing supervised run id."))

    publish_terminal = False
    with _RUN_STATE_LOCK:
        state = _require_run_locked(normalized, lang=lang)
        controller = _require_controller_locked(normalized, lang=lang)
        status = str(state.get("status") or "").strip().lower()
        now = _now_timestamp()

        if status in {"done", "failed", "cancelled"}:
            raise SupervisedRunStateError(
                text_for(lang, zh="这条监督记录已经结束，不能再暂停。", en="This supervised run is already finished.")
            )
        if status == "stopping":
            raise SupervisedRunStateError(
                text_for(lang, zh="这条监督记录正在终止，不能再暂停。", en="This supervised run is stopping already.")
            )
        if status == "paused" or bool(state.get("pauseRequested")):
            return _clone_locked(state)

        state["pauseRequested"] = True
        state["pauseRequestedAt"] = now
        _append_control_event_locked(
            state,
            event="pause_requested",
            title="已请求暂停",
            summary=text_for(
                lang,
                zh="这一轮会在当前安全点暂停。",
                en="This run will pause at the next safe checkpoint.",
            ),
            status="waiting",
        )
        if status == "queued":
            _set_paused_locked(
                state,
                lang=lang,
                now=now,
                summary=text_for(
                    lang,
                    zh="监督任务已在启动前暂停，等待恢复。",
                    en="The supervised run is paused before start and waiting to resume.",
                ),
            )
        else:
            state["currentPhase"] = "pause_requested"
            state["runtimeStatus"] = "waiting"
            state["currentTask"] = text_for(
                lang,
                zh="将在当前 case 结束后的安全点暂停监督运行。",
                en="The supervised run will pause at the next safe checkpoint after the current case.",
            )
            state["latestMessage"] = text_for(
                lang,
                zh="已请求暂停，当前 case 结束后会停下。",
                en="Pause requested. The run will stop after the current case reaches a safe checkpoint.",
            )
        publish_terminal = str(state.get("status") or "").strip().lower() == "cancelled"

    controller.request_pause()
    _publish_run_snapshot(normalized, terminal=publish_terminal)
    return get_supervised_run_snapshot(normalized)


def request_resume_supervised_run(run_id: str) -> dict[str, Any]:
    """Resume one paused supervised run or cancel a pending pause request."""

    lang = get_web_language()
    normalized = str(run_id or "").strip()
    if not normalized:
        raise SupervisedRunValidationError(text_for(lang, zh="缺少监督 run id。", en="Missing supervised run id."))

    with _RUN_STATE_LOCK:
        state = _require_run_locked(normalized, lang=lang)
        controller = _require_controller_locked(normalized, lang=lang)
        status = str(state.get("status") or "").strip().lower()
        pause_requested = bool(state.get("pauseRequested"))
        if status in {"done", "failed", "cancelled"}:
            raise SupervisedRunStateError(
                text_for(lang, zh="这条监督记录已经结束，不能再恢复。", en="This supervised run is already finished.")
            )
        if status == "stopping":
            raise SupervisedRunStateError(
                text_for(lang, zh="这条监督记录正在终止，不能再恢复。", en="This supervised run is already stopping.")
            )
        if status != "paused" and not pause_requested:
            return _clone_locked(state)

        state["pauseRequested"] = False
        if status == "paused":
            if _has_session_started(state):
                state["status"] = "running"
                state["currentPhase"] = "running"
                state["runtimeStatus"] = "running"
            else:
                state["status"] = "queued"
                state["currentPhase"] = "queued"
                state["runtimeStatus"] = "preparing"
            state["currentTask"] = text_for(
                lang,
                zh="监督任务已恢复，准备继续执行。",
                en="The supervised run has resumed and is preparing to continue.",
            )
        else:
            state["currentPhase"] = "running"
            state["runtimeStatus"] = "running"
            state["currentTask"] = text_for(
                lang,
                zh="已取消暂停请求，继续执行这一轮监督任务。",
                en="The pause request was cleared and the supervised run will keep going.",
            )
        state["latestMessage"] = text_for(
            lang,
            zh="监督任务已恢复。",
            en="The supervised run has resumed.",
        )
        _append_control_event_locked(
            state,
            event="run_resumed",
            title="监督任务已恢复",
            summary=state["latestMessage"],
            status="running" if _has_session_started(state) else "queued",
        )

    controller.request_resume()
    _publish_run_snapshot(normalized)
    return get_supervised_run_snapshot(normalized)


def request_stop_supervised_run(run_id: str) -> dict[str, Any]:
    """Request a graceful stop for one active supervised run."""

    lang = get_web_language()
    normalized = str(run_id or "").strip()
    if not normalized:
        raise SupervisedRunValidationError(text_for(lang, zh="缺少监督 run id。", en="Missing supervised run id."))

    publish_terminal = False
    with _RUN_STATE_LOCK:
        state = _RUN_STATES.get(normalized)
        if state is None:
            return _cancel_file_only_supervised_run(normalized, lang=lang)
        controller = _require_controller_locked(normalized, lang=lang)
        status = str(state.get("status") or "").strip().lower()
        now = _now_timestamp()

        if status in {"done", "failed", "cancelled"}:
            return _clone_locked(state)
        if status == "stopping" or bool(state.get("stopRequested")):
            return _clone_locked(state)

        state["stopRequested"] = True
        state["stopRequestedAt"] = now
        state["pauseRequested"] = False
        _append_control_event_locked(
            state,
            event="stop_requested",
            title="已请求终止",
            summary=text_for(
                lang,
                zh="这一轮会在当前安全点终止。",
                en="This run will stop at the next safe checkpoint.",
            ),
            status="stopping",
        )
        if status in {"queued", "paused"}:
            _cancel_run_locked(
                normalized,
                state,
                lang=lang,
                now=now,
                summary=text_for(
                    lang,
                    zh="监督任务已按请求终止。",
                    en="The supervised run was cancelled as requested.",
                ),
                reason=text_for(
                    lang,
                    zh="操作者请求终止这一轮监督任务。",
                    en="The operator requested this supervised run to stop.",
                ),
            )
            publish_terminal = True
        else:
            state["status"] = "stopping"
            state["currentPhase"] = "stopping"
            state["runtimeStatus"] = "stopping"
            state["currentTask"] = text_for(
                lang,
                zh="将在当前 case 结束后的安全点终止监督运行。",
                en="The supervised run will stop at the next safe checkpoint after the current case.",
            )
            state["latestMessage"] = text_for(
                lang,
                zh="已请求终止，等待当前安全点收口。",
                en="Stop requested. Waiting for the current safe checkpoint to close.",
            )

    controller.request_stop()
    _publish_run_snapshot(normalized, terminal=publish_terminal)
    return get_supervised_run_snapshot(normalized)


def _cancel_file_only_supervised_run(run_id: str, *, lang: str) -> dict[str, Any]:
    stored = load_manager_run_snapshot("supervised", run_id)
    if stored is None:
        raise SupervisedRunNotFoundError(text_for(lang, zh="未找到监督记录。", en="Supervised run not found."))

    status = str(stored.get("status") or "").strip().lower()
    if status not in _ACTIVE_RUN_STATUSES:
        return _decorate_supervised_snapshot(_clone_locked(stored))

    now = _now_timestamp()
    summary = text_for(
        lang,
        zh="运行管理器中断后已清理孤儿监督运行。",
        en="The orphaned supervised run was cleaned up after the runtime manager lost its live control context.",
    )
    reason = text_for(
        lang,
        zh="监督运行只有持久化快照，没有可继续控制的内存运行上下文。",
        en="The supervised run only had a persisted snapshot and no live in-memory control context.",
    )
    payload = _clone_locked(stored)
    payload["status"] = "cancelled"
    payload["currentPhase"] = "cancelled"
    payload["runtimeStatus"] = "idle"
    payload["updatedAt"] = now
    payload["finishedAt"] = now
    payload["stopRequested"] = True
    payload["stopRequestedAt"] = str(payload.get("stopRequestedAt") or now)
    payload["pauseRequested"] = False
    payload["reason"] = reason
    payload["latestMessage"] = summary
    payload["currentTask"] = text_for(
        lang,
        zh="监督任务已结束，不再继续执行。",
        en="The supervised run has stopped and will not continue.",
    )
    _append_control_event_locked(
        payload,
        event="run_cancelled",
        title="监督任务已终止",
        summary=summary,
        status="cancelled",
    )
    persisted = persist_manager_run_snapshot("supervised", payload, active_run_id="")
    return _decorate_supervised_snapshot(_clone_locked(persisted))


def stream_active_supervised_run_events(initial_snapshot: dict[str, Any] | None = None):
    """Yield SSE snapshots for the current active supervised run."""

    snapshot = initial_snapshot or get_active_supervised_run()
    if snapshot is None:
        raise SupervisedRunNotFoundError("No active supervised run.")

    run_id = str(snapshot.get("runId") or "").strip()
    if not run_id:
        raise SupervisedRunNotFoundError("No active supervised run.")

    subscriber: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=_RUN_STREAM_QUEUE_SIZE)
    _register_run_subscriber(run_id, subscriber)
    try:
        yield _encode_sse_event(
            "supervised_run",
            {
                "type": "supervised_run",
                "runId": run_id,
                "snapshot": snapshot,
            },
        )
        while True:
            try:
                event = subscriber.get(timeout=_RUN_STREAM_HEARTBEAT_SECONDS)
            except queue.Empty:
                yield ": keep-alive\n\n"
                continue
            yield _encode_sse_event(str(event.get("type") or "supervised_run"), event)
            if bool(event.get("terminal")):
                break
    finally:
        _unregister_run_subscriber(run_id, subscriber)


def execute_supervised_action(session_id: str, action: str) -> dict[str, Any]:
    """Execute a proposal lifecycle action for a finished supervised run."""

    lang = get_web_language()
    active = get_active_supervised_run()
    if active is not None and str(active.get("status") or "").strip().lower() in _ACTIVE_RUN_STATUSES:
        raise SupervisedRunBusyError(
            text_for(
                lang,
                zh="监督任务运行中，暂时不能改 proposal 状态。",
                en="A supervised run is active. Proposal actions are blocked until it finishes.",
            )
        )

    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        raise SupervisedRunNotFoundError(text_for(lang, zh="未找到监督运行。", en="Supervised run not found."))

    decision_path = PROJECT_ROOT / "workspace" / "supervised_evolution" / "decisions" / f"{normalized_session_id}.json"
    if not decision_path.exists():
        raise SupervisedRunNotFoundError(text_for(lang, zh="未找到监督运行。", en="Supervised run not found."))

    normalized_action = str(action or "").strip().lower()
    if normalized_action not in {"apply", "activate", "rollback"}:
        raise SupervisedRunActionError(
            text_for(lang, zh="未知 proposal 动作。", en="Unknown proposal action.")
        )

    try:
        result = execute_gym_promotion_action(
            str(decision_path),
            normalized_action,
            project_root=PROJECT_ROOT,
        )
    except ValueError as exc:
        raise SupervisedRunActionError(str(exc)) from exc

    run_payload = get_run(normalized_session_id, project_root=PROJECT_ROOT)
    lifecycle = load_gym_promotion_lifecycle(str(decision_path), project_root=PROJECT_ROOT)
    return {
        "action": normalized_action,
        "summary": result.summary,
        "run": run_payload,
        "lifecycle": _lifecycle_payload(lifecycle),
    }


def _run_supervised_session(context: dict[str, Any]) -> None:
    run_id = context["runId"]
    try:
        _checkpoint_supervised_run(
            run_id,
            {
                "phase": "preflight",
                "bundle_name": context["bundleName"],
            },
        )
        result = run_workbench_session(
            bundle_name=context["bundleName"],
            keep_worktree=bool(context["keepWorktree"]),
            progress_callback=lambda event: _handle_progress_event(run_id, event),
            checkpoint_callback=lambda checkpoint: _checkpoint_supervised_run(run_id, checkpoint),
            project_root=PROJECT_ROOT,
        )
    except _SupervisedRunInterrupted:
        return
    except Exception as exc:
        _mark_run_failed(run_id, f"{type(exc).__name__}: {exc}")
        return

    with _RUN_STATE_LOCK:
        state = _RUN_STATES.get(run_id)
        if state is None:
            return
        decision = result.decision
        state["status"] = "done"
        state["currentPhase"] = "done"
        state["runtimeStatus"] = "idle"
        state["currentTask"] = text_for(
            get_web_language(),
            zh="监督运行已完成，可查看结论并决定后续动作。",
            en="The supervised run is complete. Review the decision and choose the next action.",
        )
        state["sessionId"] = str(getattr(decision, "session_id", "") or state.get("sessionId") or "")
        state["decision"] = str(getattr(decision, "decision", "") or "")
        state["reason"] = str(getattr(decision, "reason", "") or "")
        state["decisionPath"] = str(getattr(decision, "decision_path", "") or "")
        policy_action = getattr(decision, "policy_action", {}) or {}
        state["policyAction"] = str(policy_action.get("action") or "")
        state["latestMessage"] = result.decision_summary
        state["updatedAt"] = _now_timestamp()
        state["finishedAt"] = state["updatedAt"]
        state["lineageIndexPath"] = str(result.lineage_index_path or "")
        state["lineageSummary"] = str(result.lineage_summary or "")
        _append_event_locked(
            state,
            {
                "timestamp": state["updatedAt"],
                "event": "run_completed",
                "title": "监督运行完成",
                "summary": result.decision_summary,
                "status": "done",
                "decision": state["decision"],
                "reason": state["reason"],
                "sessionId": state["sessionId"],
            },
        )
        _clear_active_run_locked(run_id)
        _RUN_CONTROLLERS.pop(run_id, None)
    _publish_run_snapshot(run_id, terminal=True)


def _handle_progress_event(run_id: str, event: dict[str, Any]) -> None:
    lang = get_web_language()
    with _RUN_STATE_LOCK:
        state = _RUN_STATES.get(run_id)
        if state is None:
            return
        event_type = str(event.get("event") or "").strip()
        status = str(state.get("status") or "").strip().lower()
        pause_requested = bool(state.get("pauseRequested"))
        stop_requested = bool(state.get("stopRequested"))
        state["updatedAt"] = _now_timestamp()
        if event_type == "session_start":
            if status not in {"paused", "stopping", "cancelled"}:
                state["status"] = "running"
            state["currentPhase"] = "stopping" if stop_requested else "pause_requested" if pause_requested else "running"
            state["sessionId"] = str(event.get("session_id") or state.get("sessionId") or "")
            state["bundleName"] = str(event.get("bundle_name") or state.get("bundleName") or "")
            state["caseTotal"] = max(0, int(event.get("case_total") or 0))
            state["activeAdvisoryCount"] = max(0, int(event.get("active_advisory_count") or 0))
            state["latestMessage"] = _event_summary(event)
            state["runtimeStatus"] = "stopping" if stop_requested else "waiting" if pause_requested else "running"
            if stop_requested:
                state["currentTask"] = text_for(
                    lang,
                    zh="已请求终止，等待当前安全点收口。",
                    en="Stop requested. Waiting for the current safe checkpoint to close.",
                )
            elif pause_requested:
                state["currentTask"] = text_for(
                    lang,
                    zh="已请求暂停，等待当前安全点停下。",
                    en="Pause requested. Waiting for the next safe checkpoint.",
                )
            else:
                state["currentTask"] = text_for(
                    lang,
                    zh="监督会话已启动，准备进入 case 对比。",
                    en="The supervised session started and is preparing the case comparison run.",
                )
        elif event_type == "role_start":
            if status not in {"paused", "stopping", "cancelled"}:
                state["status"] = "running"
            state["currentPhase"] = "stopping" if stop_requested else "pause_requested" if pause_requested else "running"
            state["currentCaseIndex"] = max(0, int(event.get("case_index") or 0))
            state["caseTotal"] = max(0, int(event.get("case_total") or state.get("caseTotal") or 0))
            state["currentCaseId"] = str(event.get("case_id") or "")
            state["currentRole"] = str(event.get("role") or "")
            state["currentCaseScenario"] = str(event.get("scenario") or "")
            state["currentCaseMode"] = str(event.get("mode") or "")
            state["currentCasePrompt"] = str(event.get("prompt") or "")
            state["currentCaseIo"] = None
            state["latestMessage"] = _event_summary(event)
            state["runtimeStatus"] = "stopping" if stop_requested else "waiting" if pause_requested else "running"
            if stop_requested:
                state["currentTask"] = text_for(
                    lang,
                    zh="已请求终止，当前 case 结束后会收口。",
                    en="Stop requested. The run will stop after the current case finishes.",
                )
            elif pause_requested:
                state["currentTask"] = text_for(
                    lang,
                    zh="已请求暂停，当前 case 结束后会停下。",
                    en="Pause requested. The run will pause after the current case finishes.",
                )
            else:
                state["currentTask"] = text_for(
                    lang,
                    zh=f"正在执行 case {state['currentCaseIndex']}/{state['caseTotal']} 的 {state['currentRole']} 对比。",
                    en=(
                        f"Running case {state['currentCaseIndex']}/{state['caseTotal']} "
                        f"for the {state['currentRole']} role."
                    ),
                )
        elif event_type == "role_live":
            if status not in {"paused", "stopping", "cancelled"}:
                state["status"] = "running"
            state["currentPhase"] = "stopping" if stop_requested else "pause_requested" if pause_requested else "running"
            state["currentCaseIndex"] = max(0, int(event.get("case_index") or state.get("currentCaseIndex") or 0))
            state["caseTotal"] = max(0, int(event.get("case_total") or state.get("caseTotal") or 0))
            state["currentCaseId"] = str(event.get("case_id") or state.get("currentCaseId") or "")
            state["currentRole"] = str(event.get("role") or state.get("currentRole") or "")
            state["currentCaseScenario"] = str(event.get("scenario") or state.get("currentCaseScenario") or "")
            state["currentCaseMode"] = str(event.get("mode") or state.get("currentCaseMode") or "")
            state["currentCasePrompt"] = str(event.get("prompt") or state.get("currentCasePrompt") or "")
            state["currentCaseIo"] = _case_io_payload(event)
            latest_output = str(((state.get("currentCaseIo") or {}).get("latestOutput")) or "").strip()
            latest_label = str(((state.get("currentCaseIo") or {}).get("latestOutputLabel")) or "").strip()
            if latest_output:
                state["latestMessage"] = latest_output
            state["runtimeStatus"] = "stopping" if stop_requested else "waiting" if pause_requested else "running"
            if stop_requested:
                state["currentTask"] = text_for(
                    lang,
                    zh="已请求终止，当前 case 结束后会收口。",
                    en="Stop requested. The run will stop after the current case finishes.",
                )
            elif pause_requested:
                state["currentTask"] = text_for(
                    lang,
                    zh="已请求暂停，当前 case 结束后会停下。",
                    en="Pause requested. The run will pause after the current case finishes.",
                )
            elif latest_label:
                state["currentTask"] = text_for(
                    lang,
                    zh=(
                        f"正在执行 case {state['currentCaseIndex']}/{state['caseTotal']} 的 "
                        f"{state['currentRole']}，最新输出来自 {latest_label}。"
                    ),
                    en=(
                        f"Running case {state['currentCaseIndex']}/{state['caseTotal']} "
                        f"for {state['currentRole']}. Latest output came from {latest_label}."
                    ),
                )
            else:
                state["currentTask"] = text_for(
                    lang,
                    zh=f"正在执行 case {state['currentCaseIndex']}/{state['caseTotal']} 的 {state['currentRole']} 对比。",
                    en=(
                        f"Running case {state['currentCaseIndex']}/{state['caseTotal']} "
                        f"for the {state['currentRole']} role."
                    ),
                )
        elif event_type == "role_finish":
            if status not in {"paused", "stopping", "cancelled"}:
                state["status"] = "running"
            state["currentPhase"] = "stopping" if stop_requested else "pause_requested" if pause_requested else "running"
            state["currentCaseIndex"] = max(0, int(event.get("case_index") or state.get("currentCaseIndex") or 0))
            state["caseTotal"] = max(0, int(event.get("case_total") or state.get("caseTotal") or 0))
            state["currentCaseId"] = str(event.get("case_id") or "")
            state["currentRole"] = str(event.get("role") or "")
            state["latestMessage"] = _event_summary(event)
            state["runtimeStatus"] = "stopping" if stop_requested else "waiting" if pause_requested else "running"
            if stop_requested:
                state["currentTask"] = text_for(
                    lang,
                    zh="已请求终止，等待当前安全点结束这一轮。",
                    en="Stop requested. Waiting for the current safe checkpoint to end this run.",
                )
            elif pause_requested:
                state["currentTask"] = text_for(
                    lang,
                    zh="已请求暂停，等待当前安全点停下。",
                    en="Pause requested. Waiting for the current safe checkpoint.",
                )
            else:
                state["currentTask"] = text_for(
                    lang,
                    zh=f"已完成 case {state['currentCaseId'] or state['currentCaseIndex']} 的 {state['currentRole']}，准备继续。",
                    en=(
                        f"Finished {state['currentRole']} for case "
                        f"{state['currentCaseId'] or state['currentCaseIndex']} and preparing the next step."
                    ),
                )
        elif event_type == "session_finish":
            if status not in {"paused", "stopping", "cancelled"}:
                state["status"] = "running"
            state["currentPhase"] = "evaluating"
            state["sessionId"] = str(event.get("session_id") or state.get("sessionId") or "")
            state["decision"] = str(event.get("decision") or "")
            state["reason"] = str(event.get("reason") or "")
            state["decisionPath"] = str(event.get("decision_path") or "")
            state["policyAction"] = str(event.get("policy_action") or "")
            state["activeAdvisoryCount"] = max(0, int(event.get("active_advisory_count") or state.get("activeAdvisoryCount") or 0))
            state["latestMessage"] = _event_summary(event)
            state["runtimeStatus"] = "running"
            state["currentTask"] = text_for(
                lang,
                zh="case 对比已结束，正在整理监督结论。",
                en="The case comparison run finished and the supervised decision is being assembled.",
            )
        elif event_type == "session_error":
            if status not in {"paused", "stopping", "cancelled"}:
                state["status"] = "running"
            state["latestMessage"] = _event_summary(event)
            state["runtimeStatus"] = "failed"
            state["currentTask"] = text_for(
                lang,
                zh="监督运行遇到异常，请查看错误与日志。",
                en="The supervised run hit an error. Inspect the error and logs.",
            )
        if event_type != "role_live":
            _append_event_locked(state, _event_tail_entry(event, timestamp=state["updatedAt"]))
    _publish_run_snapshot(run_id)


def _mark_run_failed(run_id: str, message: str) -> None:
    with _RUN_STATE_LOCK:
        state = _RUN_STATES.get(run_id)
        if state is None:
            return
        state["status"] = "failed"
        state["currentPhase"] = "failed"
        state["runtimeStatus"] = "failed"
        state["reason"] = str(message or "").strip()
        state["latestMessage"] = str(message or "").strip()
        state["updatedAt"] = _now_timestamp()
        state["finishedAt"] = state["updatedAt"]
        state["currentTask"] = text_for(
            get_web_language(),
            zh="监督运行失败，请检查错误与日志。",
            en="The supervised run failed. Inspect the error and logs.",
        )
        _append_event_locked(
            state,
            {
                "timestamp": state["updatedAt"],
                "event": "run_failed",
                "title": "监督运行失败",
                "summary": state["latestMessage"],
                "status": "failed",
                "reason": state["reason"],
            },
        )
        _clear_active_run_locked(run_id)
        _RUN_CONTROLLERS.pop(run_id, None)
    _publish_run_snapshot(run_id, terminal=True)


def _initial_run_state(context: dict[str, Any]) -> dict[str, Any]:
    dataset_name = str(context.get("datasetName") or "").strip()
    lang = str(context.get("lang") or "zh")
    return {
        "runId": context["runId"],
        "status": "queued",
        "currentPhase": "queued",
        "runtimeStatus": "queued",
        "sourceKind": context["sourceKind"],
        "sessionId": "",
        "bundleName": context["bundleName"],
        "datasetName": dataset_name,
        "datasetLimit": context["datasetLimit"],
        "keepWorktree": bool(context["keepWorktree"]),
        "startedAt": context["startedAt"],
        "updatedAt": context["startedAt"],
        "finishedAt": "",
        "caseTotal": 0,
        "currentCaseIndex": 0,
        "currentCaseId": "",
        "currentRole": "",
        "currentCaseScenario": "",
        "currentCaseMode": "",
        "currentCasePrompt": "",
        "currentCaseIo": None,
        "currentTask": text_for(
            lang,
            zh="监督任务已排队，等待开始。",
            en="The supervised run is queued and waiting to start.",
        ),
        "decision": "",
        "reason": "",
        "decisionPath": "",
        "policyAction": "",
        "lineageIndexPath": "",
        "lineageSummary": "",
        "activeAdvisoryCount": 0,
        "pauseRequested": False,
        "pauseRequestedAt": "",
        "pausedAt": "",
        "stopRequested": False,
        "stopRequestedAt": "",
        "latestMessage": text_for(
            lang,
            zh="监督任务已排队。",
            en="Queued supervised run.",
        ),
        "eventTail": [
            {
                "timestamp": context["startedAt"],
                "event": "queued",
                "title": "监督任务已排队",
                "summary": _queued_summary(context),
                "status": "queued",
                "sourceKind": context["sourceKind"],
                "datasetName": dataset_name,
                "datasetLimit": context["datasetLimit"],
                "bundleName": context["bundleName"],
                "keepWorktree": bool(context["keepWorktree"]),
            }
        ],
    }


def _clone_locked(payload: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(payload, ensure_ascii=False))


def _decorate_supervised_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    payload["actionStates"] = _supervised_action_states(payload, lang=get_web_language())
    return payload


def _supervised_action_states(payload: dict[str, Any], *, lang: str) -> dict[str, dict[str, Any]]:
    status = str(payload.get("status") or "").strip().lower()
    pause_requested = bool(payload.get("pauseRequested"))
    stop_requested = bool(payload.get("stopRequested"))

    def enabled_state() -> dict[str, Any]:
        return {"enabled": True, "reason": ""}

    def disabled_state(reason: str) -> dict[str, Any]:
        return {"enabled": False, "reason": reason}

    if status in {"queued", "running"} and not pause_requested and not stop_requested:
        pause_state = enabled_state()
    elif status == "paused":
        pause_state = disabled_state(
            text_for(lang, zh="这一轮已经暂停，可以直接恢复。", en="This run is already paused and can be resumed directly.")
        )
    elif status in {"done", "failed", "cancelled"}:
        pause_state = disabled_state(
            text_for(lang, zh="这条监督记录已经结束，不能再暂停。", en="This supervised run is already finished and cannot be paused.")
        )
    elif stop_requested or status == "stopping":
        pause_state = disabled_state(
            text_for(lang, zh="这一轮正在终止，不能再请求暂停。", en="This run is already stopping and cannot accept another pause request.")
        )
    else:
        pause_state = disabled_state(
            text_for(lang, zh="暂停请求已经发出，等待当前安全点收口。", en="Pause has already been requested. Wait for the current safe checkpoint.")
        )

    if status == "paused" or (status in {"queued", "running"} and pause_requested):
        resume_state = enabled_state()
    elif status in {"done", "failed", "cancelled"}:
        resume_state = disabled_state(
            text_for(lang, zh="这条监督记录已经结束，不能再恢复。", en="This supervised run is already finished and cannot be resumed.")
        )
    else:
        resume_state = disabled_state(
            text_for(lang, zh="只有已暂停或等待暂停的这一轮才能恢复。", en="Only a paused run, or one waiting to pause, can be resumed.")
        )

    if status in {"queued", "running", "paused"} and not stop_requested:
        terminate_state = enabled_state()
    elif status in {"done", "failed", "cancelled"}:
        terminate_state = disabled_state(
            text_for(lang, zh="这条监督记录已经结束，无需再次终止。", en="This supervised run is already finished and does not need another stop request.")
        )
    else:
        terminate_state = disabled_state(
            text_for(lang, zh="终止请求已经发出，等待这一轮收口。", en="A stop request has already been sent. Wait for this run to close.")
        )

    return {
        "pause": pause_state,
        "resume": resume_state,
        "terminate": terminate_state,
    }


def _require_run_locked(run_id: str, *, lang: str) -> dict[str, Any]:
    state = _RUN_STATES.get(run_id)
    if state is None:
        raise SupervisedRunNotFoundError(text_for(lang, zh="未找到监督记录。", en="Supervised run not found."))
    return state


def _require_controller_locked(run_id: str, *, lang: str) -> _SupervisedRunController:
    controller = _RUN_CONTROLLERS.get(run_id)
    if controller is None:
        raise SupervisedRunStateError(
            text_for(
                lang,
                zh="这条监督记录当前没有可继续控制的运行上下文。",
                en="This supervised run no longer has a live control context.",
            )
        )
    return controller


def _clear_active_run_locked(run_id: str) -> None:
    global _ACTIVE_RUN_ID
    if _ACTIVE_RUN_ID == run_id:
        _ACTIVE_RUN_ID = None


def _has_session_started(state: dict[str, Any]) -> bool:
    return bool(str(state.get("sessionId") or "").strip()) or int(state.get("caseTotal") or 0) > 0


def _append_control_event_locked(
    state: dict[str, Any],
    *,
    event: str,
    title: str,
    summary: str,
    status: str,
) -> None:
    _append_event_locked(
        state,
        {
            "timestamp": state["updatedAt"],
            "event": event,
            "title": title,
            "summary": summary,
            "status": status,
            "caseId": str(state.get("currentCaseId") or ""),
            "caseIndex": _optional_int(state.get("currentCaseIndex")),
            "caseTotal": _optional_int(state.get("caseTotal")),
            "role": str(state.get("currentRole") or ""),
            "scenario": "",
            "mode": "",
            "bundleName": str(state.get("bundleName") or ""),
            "sessionId": str(state.get("sessionId") or ""),
            "decision": str(state.get("decision") or ""),
            "reason": str(state.get("reason") or ""),
            "errorType": "",
            "elapsedSeconds": None,
            "resultStatus": status,
        },
    )


def _set_paused_locked(state: dict[str, Any], *, lang: str, now: str, summary: str) -> None:
    state["status"] = "paused"
    state["currentPhase"] = "paused"
    state["runtimeStatus"] = "paused"
    state["updatedAt"] = now
    state["pausedAt"] = now
    state["currentTask"] = text_for(
        lang,
        zh="监督任务已暂停，等待人工恢复。",
        en="The supervised run is paused and waiting to resume.",
    )
    state["latestMessage"] = summary
    _append_control_event_locked(
        state,
        event="run_paused",
        title="监督任务已暂停",
        summary=summary,
        status="paused",
    )


def _cancel_run_locked(
    run_id: str,
    state: dict[str, Any],
    *,
    lang: str,
    now: str,
    summary: str,
    reason: str,
) -> None:
    state["status"] = "cancelled"
    state["currentPhase"] = "cancelled"
    state["runtimeStatus"] = "idle"
    state["updatedAt"] = now
    state["finishedAt"] = now
    state["reason"] = reason
    state["latestMessage"] = summary
    state["currentTask"] = text_for(
        lang,
        zh="监督任务已结束，不再继续执行。",
        en="The supervised run has stopped and will not continue.",
    )
    _append_control_event_locked(
        state,
        event="run_cancelled",
        title="监督任务已终止",
        summary=summary,
        status="cancelled",
    )
    _clear_active_run_locked(run_id)
    _RUN_CONTROLLERS.pop(run_id, None)


def _checkpoint_supervised_run(run_id: str, checkpoint: dict[str, Any]) -> None:
    controller = _RUN_CONTROLLERS.get(run_id)
    if controller is None:
        return

    lang = get_web_language()
    with _RUN_STATE_LOCK:
        state = _RUN_STATES.get(run_id)
        if state is None:
            return
        status = str(state.get("status") or "").strip().lower()
        if status in {"done", "failed", "cancelled"}:
            return
        stop_requested = bool(state.get("stopRequested"))
        pause_requested = bool(state.get("pauseRequested"))
        if stop_requested:
            now = _now_timestamp()
            _cancel_run_locked(
                run_id,
                state,
                lang=lang,
                now=now,
                summary=text_for(
                    lang,
                    zh="监督任务已在安全点终止。",
                    en="The supervised run stopped at a safe checkpoint.",
                ),
                reason=text_for(
                    lang,
                    zh="操作者请求在安全点终止这一轮监督任务。",
                    en="The operator requested this supervised run to stop at a safe checkpoint.",
                ),
            )
            terminal = True
        elif pause_requested:
            now = _now_timestamp()
            if status != "paused":
                _set_paused_locked(
                    state,
                    lang=lang,
                    now=now,
                    summary=text_for(
                        lang,
                        zh="监督任务已在安全点暂停，等待恢复。",
                        en="The supervised run paused at a safe checkpoint and is waiting to resume.",
                    ),
                )
            terminal = False
        else:
            terminal = False
            status = ""
    if terminal:
        _publish_run_snapshot(run_id, terminal=True)
        raise _SupervisedRunInterrupted()

    with controller.condition:
        while controller.pause_requested and not controller.stop_requested:
            controller.condition.wait()
        stop_requested = controller.stop_requested

    with _RUN_STATE_LOCK:
        state = _RUN_STATES.get(run_id)
        if state is None:
            return
        status = str(state.get("status") or "").strip().lower()
        if status in {"done", "failed", "cancelled"}:
            return
        if stop_requested or bool(state.get("stopRequested")):
            now = _now_timestamp()
            _cancel_run_locked(
                run_id,
                state,
                lang=lang,
                now=now,
                summary=text_for(
                    lang,
                    zh="监督任务已在安全点终止。",
                    en="The supervised run stopped at a safe checkpoint.",
                ),
                reason=text_for(
                    lang,
                    zh="操作者请求在安全点终止这一轮监督任务。",
                    en="The operator requested this supervised run to stop at a safe checkpoint.",
                ),
            )
            terminal = True
        elif status == "paused":
            now = _now_timestamp()
            if _has_session_started(state):
                state["status"] = "running"
                state["currentPhase"] = "running"
                state["runtimeStatus"] = "running"
            else:
                state["status"] = "queued"
                state["currentPhase"] = "queued"
                state["runtimeStatus"] = "preparing"
            state["updatedAt"] = now
            state["currentTask"] = text_for(
                lang,
                zh="监督任务已恢复，继续推进下一步。",
                en="The supervised run resumed and is continuing with the next step.",
            )
            state["latestMessage"] = text_for(
                lang,
                zh="监督任务已恢复。",
                en="The supervised run has resumed.",
            )
            terminal = False
        else:
            terminal = False
    _publish_run_snapshot(run_id, terminal=terminal)
    if terminal:
        raise _SupervisedRunInterrupted()


def _dataset_payload(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": str(item.get("name") or "").strip(),
        "bundleName": str(item.get("bundle_name") or "").strip(),
        "available": bool(item.get("available")),
        "runnable": bool(item.get("runnable")),
        "adapterStatus": str(item.get("adapter_status") or "").strip(),
        "description": str(item.get("description") or "").strip(),
        "sourcePath": str(item.get("source_path") or "").strip(),
        "sourceExists": bool(item.get("source_exists")),
        "tags": [str(tag) for tag in list(item.get("tags") or []) if str(tag).strip()],
    }


def _lifecycle_payload(lifecycle) -> dict[str, Any]:
    return {
        "status": lifecycle.status,
        "proposalId": lifecycle.proposal_id,
        "targetKey": lifecycle.target_key,
        "runtimeEffect": lifecycle.runtime_effect,
        "agentConsumption": lifecycle.agent_consumption,
        "availableActions": list(lifecycle.available_actions),
        "note": lifecycle.note,
        "error": lifecycle.error,
    }


def _coerce_dataset_limit(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise SupervisedRunValidationError("datasetLimit must be an integer or null.")
    try:
        numeric = int(value)
    except (TypeError, ValueError) as exc:
        raise SupervisedRunValidationError("datasetLimit must be an integer or null.") from exc
    if numeric <= 0:
        raise SupervisedRunValidationError("datasetLimit must be greater than zero.")
    return numeric


def _queued_summary(context: dict[str, Any]) -> str:
    source_kind = str(context.get("sourceKind") or "")
    if source_kind == "dataset":
        limit_text = context["datasetLimit"] if context["datasetLimit"] is not None else "all"
        return (
            f"source=dataset {context['datasetName']} "
            f"limit={limit_text} keep_worktree={context['keepWorktree']}"
        )
    return f"source=bundle {context['bundleName']} keep_worktree={context['keepWorktree']}"


def _event_tail_entry(event: dict[str, Any], *, timestamp: str) -> dict[str, Any]:
    return {
        "timestamp": timestamp,
        "event": str(event.get("event") or "").strip(),
        "title": _event_title(event),
        "summary": _event_summary(event),
        "status": _event_status(event),
        "caseId": str(event.get("case_id") or ""),
        "caseIndex": _optional_int(event.get("case_index")),
        "caseTotal": _optional_int(event.get("case_total")),
        "role": str(event.get("role") or ""),
        "scenario": str(event.get("scenario") or ""),
        "mode": str(event.get("mode") or ""),
        "bundleName": str(event.get("bundle_name") or ""),
        "sessionId": str(event.get("session_id") or ""),
        "decision": str(event.get("decision") or ""),
        "reason": str(event.get("reason") or event.get("error") or ""),
        "errorType": str(event.get("error_type") or ""),
        "elapsedSeconds": _optional_float(event.get("elapsed_seconds")),
        "resultStatus": str(event.get("status") or ""),
    }


def _event_title(event: dict[str, Any]) -> str:
    event_type = str(event.get("event") or "").strip()
    return {
        "session_start": "监督任务开始",
        "role_start": "Case 开始",
        "role_finish": "Case 完成",
        "session_error": "监督任务异常",
        "session_finish": "监督任务结束",
    }.get(event_type, event_type or "监督任务更新")


def _event_status(event: dict[str, Any]) -> str:
    event_type = str(event.get("event") or "").strip()
    if event_type == "session_error":
        return "failed"
    if event_type == "session_finish":
        return "done"
    if event_type == "role_finish":
        raw_status = str(event.get("status") or "").strip().lower()
        return raw_status or "running"
    return "running"


def _event_summary(event: dict[str, Any]) -> str:
    event_type = str(event.get("event") or "").strip()
    if event_type == "session_start":
        return (
            f"session={event.get('session_id')} bundle={event.get('bundle_name')} "
            f"cases={event.get('case_total')}"
        )
    if event_type == "role_start":
        return (
            f"case {event.get('case_index')}/{event.get('case_total')} "
            f"{event.get('case_id')} {event.get('role')} "
            f"scenario={event.get('scenario')} mode={event.get('mode')}"
        )
    if event_type == "role_finish":
        return (
            f"{event.get('case_id')} {event.get('role')} status={event.get('status')} "
            f"reason={event.get('reason')}"
        )
    if event_type == "session_error":
        return (
            f"case {event.get('case_index')}/{event.get('case_total')} "
            f"{event.get('case_id')} {event.get('role')} "
            f"{event.get('error_type')}: {event.get('error')}"
        )
    if event_type == "session_finish":
        return f"decision={event.get('decision')} reason={event.get('reason')}"
    return json.dumps(event, ensure_ascii=False)


def _case_io_payload(event: dict[str, Any]) -> dict[str, Any] | None:
    transcript_items = []
    for raw in list(event.get("transcript") or []):
        if not isinstance(raw, dict):
            continue
        transcript_items.append(
            {
                "timestamp": str(raw.get("timestamp") or "").strip(),
                "kind": str(raw.get("kind") or "").strip(),
                "label": str(raw.get("label") or "").strip(),
                "content": str(raw.get("content") or "").strip(),
                "status": str(raw.get("status") or "").strip(),
            }
        )

    payload = {
        "conversationPath": str(event.get("conversation_path") or "").strip(),
        "latestInput": str(event.get("latest_input") or "").strip(),
        "latestOutput": str(event.get("latest_output") or "").strip(),
        "latestOutputKind": str(event.get("latest_output_kind") or "").strip(),
        "latestOutputLabel": str(event.get("latest_output_label") or "").strip(),
        "updatedAt": str(event.get("updated_at") or "").strip(),
        "transcript": transcript_items,
    }

    if any(
        [
            payload["conversationPath"],
            payload["latestInput"],
            payload["latestOutput"],
            payload["latestOutputKind"],
            payload["latestOutputLabel"],
            payload["updatedAt"],
            transcript_items,
        ]
    ):
        return payload
    return None


def _append_event_locked(state: dict[str, Any], item: dict[str, Any]) -> None:
    tail = list(state.get("eventTail") or [])
    tail.append(item)
    state["eventTail"] = tail[-_EVENT_TAIL_LIMIT:]


def _optional_int(value: Any) -> int | None:
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return None
    return numeric


def _optional_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric


def _publish_run_snapshot(run_id: str, *, terminal: bool = False) -> None:
    with _RUN_STATE_LOCK:
        current = _RUN_STATES.get(run_id)
        if current is None:
            return
        snapshot = _clone_locked(current)
        active_run_id = _ACTIVE_RUN_ID if _ACTIVE_RUN_ID else ""
    persist_manager_run_snapshot("supervised", snapshot, active_run_id=active_run_id)
    event = {
        "type": "supervised_run",
        "runId": run_id,
        "snapshot": snapshot,
        "terminal": terminal,
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


def _current_active_run_locked() -> dict[str, Any] | None:
    if not _ACTIVE_RUN_ID:
        return None
    return _RUN_STATES.get(_ACTIVE_RUN_ID)


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


def _encode_sse_event(event_name: str, payload: dict[str, Any]) -> str:
    body = json.dumps(payload, ensure_ascii=False)
    return f"event: {event_name}\ndata: {body}\n\n"


def _now_timestamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


_LOCAL_GET_SUPERVISED_WORKBENCH = get_supervised_workbench
_LOCAL_START_SUPERVISED_RUN = start_supervised_run
_LOCAL_GET_ACTIVE_SUPERVISED_RUN = get_active_supervised_run
_LOCAL_GET_SUPERVISED_RUN_SNAPSHOT = get_supervised_run_snapshot
_LOCAL_REQUEST_PAUSE_SUPERVISED_RUN = request_pause_supervised_run
_LOCAL_REQUEST_RESUME_SUPERVISED_RUN = request_resume_supervised_run
_LOCAL_REQUEST_STOP_SUPERVISED_RUN = request_stop_supervised_run
_LOCAL_STREAM_ACTIVE_SUPERVISED_RUN_EVENTS = stream_active_supervised_run_events


def _stream_manager_supervised_events(initial_snapshot: dict[str, Any] | None = None):
    snapshot = initial_snapshot or load_manager_active_run_snapshot("supervised")
    if snapshot is None:
        raise SupervisedRunNotFoundError("No active supervised run.")

    run_id = str(snapshot.get("runId") or "").strip()
    if not run_id:
        raise SupervisedRunNotFoundError("No active supervised run.")

    last_signature = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
    last_keepalive = time.monotonic()
    yield _encode_sse_event(
        "supervised_run",
        {
            "type": "supervised_run",
            "runId": run_id,
            "snapshot": snapshot,
            "terminal": False,
        },
    )

    while True:
        latest = load_manager_run_snapshot("supervised", run_id)
        if latest is not None:
            signature = json.dumps(latest, ensure_ascii=False, sort_keys=True)
            if signature != last_signature:
                last_signature = signature
                terminal = str(latest.get("status") or "").strip().lower() in {"done", "failed", "cancelled"}
                yield _encode_sse_event(
                    "supervised_run",
                    {
                        "type": "supervised_run",
                        "runId": run_id,
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
        time.sleep(1.5)


def _submit_supervised_runtime_manager_command(command_type: str, *, run_id: str = "", payload: dict[str, Any] | None = None) -> dict[str, Any]:
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
    loaded = load_manager_run_snapshot("supervised", target_run_id) if target_run_id else None
    if loaded is not None:
        return loaded
    return {}


def get_supervised_workbench() -> dict[str, Any]:
    if _runtime_manager_live_control_enabled():
        return {
            "defaultBundleName": default_bundle_name(),
            "savedState": get_workbench_state_payload(project_root=PROJECT_ROOT),
            "datasets": [_dataset_payload(item) for item in list_dataset_choices(PROJECT_ROOT)],
            "activeRun": get_active_supervised_run(),
        }
    return _LOCAL_GET_SUPERVISED_WORKBENCH()


def start_supervised_run(payload: dict[str, Any]) -> dict[str, Any]:
    if _runtime_manager_live_control_enabled():
        return _submit_supervised_runtime_manager_command("start_supervised_run", payload=payload)
    return _LOCAL_START_SUPERVISED_RUN(payload)


def get_active_supervised_run() -> dict[str, Any] | None:
    if _runtime_manager_live_control_enabled():
        snapshot = load_manager_active_run_snapshot("supervised")
        if snapshot is None:
            return None
        return _decorate_supervised_snapshot(_clone_locked(snapshot))
    return _LOCAL_GET_ACTIVE_SUPERVISED_RUN()


def get_supervised_run_snapshot(run_id: str) -> dict[str, Any]:
    if _runtime_manager_live_control_enabled():
        payload = load_manager_run_snapshot("supervised", run_id)
        if payload is None:
            raise SupervisedRunNotFoundError("Supervised run not found.")
        return _decorate_supervised_snapshot(_clone_locked(payload))
    return _LOCAL_GET_SUPERVISED_RUN_SNAPSHOT(run_id)


def request_pause_supervised_run(run_id: str) -> dict[str, Any]:
    if _runtime_manager_live_control_enabled():
        return _submit_supervised_runtime_manager_command("pause_supervised_run", run_id=run_id)
    return _LOCAL_REQUEST_PAUSE_SUPERVISED_RUN(run_id)


def request_resume_supervised_run(run_id: str) -> dict[str, Any]:
    if _runtime_manager_live_control_enabled():
        return _submit_supervised_runtime_manager_command("resume_supervised_run", run_id=run_id)
    return _LOCAL_REQUEST_RESUME_SUPERVISED_RUN(run_id)


def request_stop_supervised_run(run_id: str) -> dict[str, Any]:
    if _runtime_manager_live_control_enabled():
        return _submit_supervised_runtime_manager_command("stop_supervised_run", run_id=run_id)
    return _LOCAL_REQUEST_STOP_SUPERVISED_RUN(run_id)


def stream_active_supervised_run_events(initial_snapshot: dict[str, Any] | None = None):
    if _runtime_manager_live_control_enabled():
        return _stream_manager_supervised_events(initial_snapshot=initial_snapshot)
    return _LOCAL_STREAM_ACTIVE_SUPERVISED_RUN_EVENTS(initial_snapshot=initial_snapshot)
