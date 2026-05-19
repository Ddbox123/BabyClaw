# -*- coding: utf-8 -*-
"""监督进化模式的最小执行闭环。"""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core.infrastructure.workspace_manager import get_workspace
from core.evaluation.selection_policy import execute_supervised_policy
from core.gym import build_active_advisory_snapshot, summarize_active_advisory_baselines
from scripts.evolution_harness import HarnessResult, run_harness


DEFAULT_BUNDLE_NAME = "supervised_evolution_dry_run_v1"
DEFAULT_BUNDLE_PATH = Path("workspace/evaluation/bundles") / f"{DEFAULT_BUNDLE_NAME}.json"
DEFAULT_BUNDLE_TEMPLATE_DIR = Path(__file__).resolve().parent / "bundles"
ProgressCallback = Callable[[Dict[str, Any]], None]
CheckpointCallback = Callable[[Dict[str, Any]], None]


def _workspace_bundle_path(root: Path, bundle_name: str) -> Path:
    return root / "workspace" / "evaluation" / "bundles" / f"{bundle_name}.json"


def _ensure_default_bundle_available(root: Path, bundle_name: str) -> Path:
    bundle_path = _workspace_bundle_path(root, bundle_name)
    if bundle_path.exists() or bundle_name != DEFAULT_BUNDLE_NAME:
        return bundle_path

    template_path = DEFAULT_BUNDLE_TEMPLATE_DIR / f"{bundle_name}.json"
    if template_path.exists():
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(template_path, bundle_path)
    return bundle_path


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass
class SupervisedEvolutionRun:
    role: str
    case_id: str
    status: str
    reason: str
    started_at: str
    ended_at: str
    scenario: str
    mode: str
    prompt: str
    worktree_path: str
    checkpoint_commit: str
    report_path: Optional[str] = None
    restarts_observed: int = 0
    new_conversation_files: List[str] = field(default_factory=list)
    new_debug_files: List[str] = field(default_factory=list)
    evolution_summary: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DecisionGate:
    name: str
    status: str
    reason: str
    metrics: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RunAggregate:
    total: int
    successes: int
    failed: int
    timeouts: int
    success_rate: float
    avg_wall_clock_seconds: float
    validation_passed: int
    validation_failed: int
    total_guarded_tools: int
    total_restart_observed: int
    total_new_logs: int


@dataclass
class CaseDecisionSummary:
    case_id: str
    baseline_status: str
    candidate_status: str
    baseline_reason: str
    candidate_reason: str
    decision_signal: str


@dataclass
class SupervisedEvolutionDecision:
    session_id: str
    bundle_name: str
    started_at: str
    ended_at: str
    benchmark: str
    baseline_runs: List[SupervisedEvolutionRun]
    candidate_runs: List[SupervisedEvolutionRun]
    baseline_summary: RunAggregate
    candidate_summary: RunAggregate
    case_summaries: List[CaseDecisionSummary]
    gates: List[DecisionGate]
    decision: str
    reason: str
    baseline_success_rate: float
    candidate_success_rate: float
    score_delta: float
    advisory_context: Dict[str, Any] = field(default_factory=dict)
    summary: Dict[str, Any] = field(default_factory=dict)
    decision_path: Optional[str] = None
    policy_action: Dict[str, Any] = field(default_factory=dict)


def load_supervised_bundle(bundle_name: str = DEFAULT_BUNDLE_NAME, *, project_root: Optional[Path] = None) -> Dict[str, Any]:
    root = (project_root or get_workspace().project_root).resolve()
    bundle_path = _ensure_default_bundle_available(root, bundle_name)
    if not bundle_path.exists():
        raise FileNotFoundError(f"监督进化 bundle 不存在: {bundle_path}")
    payload = json.loads(bundle_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("监督进化 bundle 格式错误：根节点必须是对象")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("监督进化 bundle 至少需要一个 case")
    return payload


def resolve_supervised_bundle_path(bundle_name: str = DEFAULT_BUNDLE_NAME, *, project_root: Optional[Path] = None) -> Path:
    root = (project_root or get_workspace().project_root).resolve()
    return _ensure_default_bundle_available(root, bundle_name)


def _ensure_supervised_dirs(project_root: Path) -> Dict[str, Path]:
    base = project_root / "workspace" / "supervised_evolution"
    dirs = {
        "base": base,
        "sessions": base / "sessions",
        "decisions": base / "decisions",
    }
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    return dirs


def _to_supervised_run(
    *,
    role: str,
    case_id: str,
    prompt: str,
    scenario: str,
    mode: str,
    result: HarnessResult,
    report_path: Optional[Path],
) -> SupervisedEvolutionRun:
    return SupervisedEvolutionRun(
        role=role,
        case_id=case_id,
        status=result.status,
        reason=result.reason,
        started_at=result.started_at,
        ended_at=result.ended_at,
        scenario=scenario,
        mode=mode,
        prompt=prompt,
        worktree_path=result.worktree_path,
        checkpoint_commit=result.checkpoint_commit,
        report_path=str(report_path) if report_path else None,
        restarts_observed=result.restarts_observed,
        new_conversation_files=result.new_conversation_files,
        new_debug_files=result.new_debug_files,
        evolution_summary=result.evolution_summary,
    )


def _success_rate(items: List[SupervisedEvolutionRun]) -> float:
    if not items:
        return 0.0
    success = sum(1 for item in items if item.status == "success")
    return round(success / len(items), 3)


def _parse_iso_timestamp(value: str) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _extract_run_metrics(item: SupervisedEvolutionRun) -> Dict[str, Any]:
    summary = item.evolution_summary or {}
    validation = summary.get("validation") or {}
    guarded = summary.get("guarded_tools") or {}
    restart = summary.get("restart") or {}
    transaction = summary.get("transaction") or {}
    git = summary.get("git") or {}
    started_at = _parse_iso_timestamp(item.started_at)
    ended_at = _parse_iso_timestamp(item.ended_at)
    wall_clock_seconds = 0.0
    if started_at and ended_at:
        wall_clock_seconds = max(0.0, round((ended_at - started_at).total_seconds(), 3))
    return {
        "wall_clock_seconds": wall_clock_seconds,
        "validation_passed": int(validation.get("passed") or 0),
        "validation_failed": int(validation.get("failed") or 0),
        "guarded_tools": int(guarded.get("total") or 0),
        "restart_guarded_tools": int(guarded.get("restart_guarded") or 0),
        "transaction_opened": bool(transaction.get("opened")),
        "transaction_closed": bool(transaction.get("closed")),
        "transaction_status": str(transaction.get("status") or ""),
        "commit_detected": bool(git.get("commit_detected")),
        "restart_expected": bool(restart.get("expected")),
        "restart_triggered": bool(restart.get("triggered")),
        "restart_reentered": bool(restart.get("reentered")),
        "new_logs": len(item.new_conversation_files) + len(item.new_debug_files),
    }


def _build_run_aggregate(items: List[SupervisedEvolutionRun]) -> RunAggregate:
    total = len(items)
    successes = sum(1 for item in items if item.status == "success")
    failed = sum(1 for item in items if item.status == "failed")
    timeouts = sum(1 for item in items if item.status == "timeout")
    metrics = [_extract_run_metrics(item) for item in items]
    return RunAggregate(
        total=total,
        successes=successes,
        failed=failed,
        timeouts=timeouts,
        success_rate=_success_rate(items),
        avg_wall_clock_seconds=round(sum(m["wall_clock_seconds"] for m in metrics) / total, 3) if total else 0.0,
        validation_passed=sum(m["validation_passed"] for m in metrics),
        validation_failed=sum(m["validation_failed"] for m in metrics),
        total_guarded_tools=sum(m["guarded_tools"] for m in metrics),
        total_restart_observed=sum(item.restarts_observed for item in items),
        total_new_logs=sum(m["new_logs"] for m in metrics),
    )


def _build_case_summaries(
    baseline_runs: List[SupervisedEvolutionRun],
    candidate_runs: List[SupervisedEvolutionRun],
) -> List[CaseDecisionSummary]:
    baseline_by_case = {item.case_id: item for item in baseline_runs}
    candidate_by_case = {item.case_id: item for item in candidate_runs}
    case_ids = sorted(set(baseline_by_case) | set(candidate_by_case))
    summaries: List[CaseDecisionSummary] = []
    for case_id in case_ids:
        baseline = baseline_by_case.get(case_id)
        candidate = candidate_by_case.get(case_id)
        baseline_status = baseline.status if baseline else "missing"
        candidate_status = candidate.status if candidate else "missing"
        signal = "tie"
        if baseline_status == "success" and candidate_status != "success":
            signal = "candidate_regressed"
        elif baseline_status != "success" and candidate_status == "success":
            signal = "candidate_improved"
        elif baseline_status == candidate_status == "success":
            signal = "stable_success"
        summaries.append(
            CaseDecisionSummary(
                case_id=case_id,
                baseline_status=baseline_status,
                candidate_status=candidate_status,
                baseline_reason=baseline.reason if baseline else "missing baseline run",
                candidate_reason=candidate.reason if candidate else "missing candidate run",
                decision_signal=signal,
            )
        )
    return summaries


def _evaluate_gates(
    baseline_runs: List[SupervisedEvolutionRun],
    candidate_runs: List[SupervisedEvolutionRun],
) -> tuple[List[DecisionGate], str, str, float]:
    baseline_success = _success_rate(baseline_runs)
    candidate_success = _success_rate(candidate_runs)
    score_delta = round(candidate_success - baseline_success, 3)
    gates: List[DecisionGate] = []
    baseline_metrics = [_extract_run_metrics(item) for item in baseline_runs]
    candidate_metrics = [_extract_run_metrics(item) for item in candidate_runs]

    baseline_commit_detected = sum(1 for item in baseline_metrics if item["commit_detected"])
    candidate_commit_detected = sum(1 for item in candidate_metrics if item["commit_detected"])
    candidate_transaction_issues = sum(
        1
        for item in candidate_metrics
        if not item["transaction_opened"]
        or not item["transaction_closed"]
        or item["transaction_status"] not in {"", "success"}
    )
    legality_status = "pass"
    legality_reason = "candidate 运行保持在受控事务约束内"
    if candidate_commit_detected:
        legality_status = "fail"
        legality_reason = "candidate 在 dry-run 中出现提交痕迹，越过了监督边界"
    elif candidate_transaction_issues:
        legality_status = "fail"
        legality_reason = "candidate 存在未完整关账或事务状态异常"

    legality_gate = DecisionGate(
        name="legality",
        status=legality_status,
        reason=legality_reason,
        metrics={
            "candidate_runs": len(candidate_runs),
            "baseline_runs": len(baseline_runs),
            "candidate_commit_detected": candidate_commit_detected,
            "baseline_commit_detected": baseline_commit_detected,
            "candidate_transaction_issues": candidate_transaction_issues,
        },
    )
    gates.append(legality_gate)
    if legality_status == "fail":
        gates.append(
            DecisionGate(
                name="safety",
                status="skipped",
                reason="合法性未通过，跳过后续门控",
                metrics={"score_delta": score_delta},
            )
        )
        gates.append(
            DecisionGate(
                name="survival",
                status="skipped",
                reason="合法性未通过，跳过后续晋升判断",
                metrics={"score_delta": score_delta},
            )
        )
        gates.append(
            DecisionGate(
                name="cost",
                status="skipped",
                reason="合法性未通过，跳过成本门",
                metrics={},
            )
        )
        return gates, "ROLLBACK", legality_reason, score_delta

    candidate_failed = sum(1 for item in candidate_runs if item.status == "failed")
    candidate_timeouts = sum(1 for item in candidate_runs if item.status == "timeout")
    baseline_validation_failed = sum(item["validation_failed"] for item in baseline_metrics)
    candidate_validation_failed = sum(item["validation_failed"] for item in candidate_metrics)
    baseline_restart_misses = sum(
        1 for item in baseline_metrics if item["restart_expected"] and not item["restart_reentered"]
    )
    candidate_restart_misses = sum(
        1 for item in candidate_metrics if item["restart_expected"] and not item["restart_reentered"]
    )
    safety_status = "pass"
    safety_reason = "candidate 未出现显式安全退化"
    if candidate_failed and all(item.status == "success" for item in baseline_runs):
        safety_status = "fail"
        safety_reason = "candidate 在 baseline 全通过时出现失败，触发回滚保护"
    elif candidate_restart_misses > baseline_restart_misses:
        safety_status = "fail"
        safety_reason = "candidate 在需要重启的 case 中出现更多重启接力失败"
    gates.append(
        DecisionGate(
            name="safety",
            status=safety_status,
            reason=safety_reason,
            metrics={
                "candidate_failed_runs": candidate_failed,
                "candidate_timeouts": candidate_timeouts,
                "baseline_validation_failed": baseline_validation_failed,
                "candidate_validation_failed": candidate_validation_failed,
                "baseline_restart_misses": baseline_restart_misses,
                "candidate_restart_misses": candidate_restart_misses,
            },
        )
    )
    if safety_status == "fail":
        gates.append(
            DecisionGate(
                name="survival",
                status="skipped",
                reason="安全门未通过，跳过后续晋升判断",
                metrics={"score_delta": score_delta},
            )
        )
        gates.append(
            DecisionGate(
                name="cost",
                status="skipped",
                reason="安全门未通过，跳过成本门",
                metrics={},
            )
        )
        return gates, "ROLLBACK", "candidate 在监督进化 dry-run 中退化", score_delta

    survival_status = "pass"
    survival_reason = "candidate 与 baseline 持平"
    if candidate_success > baseline_success:
        survival_reason = "candidate 成功率优于 baseline"
    elif candidate_success < baseline_success:
        survival_status = "fail"
        survival_reason = "candidate 成功率低于 baseline"
    gates.append(
        DecisionGate(
            name="survival",
            status=survival_status,
            reason=survival_reason,
            metrics={
                "baseline_success_rate": baseline_success,
                "candidate_success_rate": candidate_success,
                "score_delta": score_delta,
            },
        )
    )
    if survival_status == "fail":
        gates.append(
            DecisionGate(
                name="cost",
                status="skipped",
                reason="生存门未通过，跳过成本门",
                metrics={},
            )
        )
        return gates, "REJECT", "candidate 成功率低于 baseline", score_delta

    cost_status = "pass"
    baseline_guarded_tools = sum(item["guarded_tools"] for item in baseline_metrics)
    candidate_guarded_tools = sum(item["guarded_tools"] for item in candidate_metrics)
    baseline_runtime = round(sum(item["wall_clock_seconds"] for item in baseline_metrics), 3)
    candidate_runtime = round(sum(item["wall_clock_seconds"] for item in candidate_metrics), 3)
    baseline_new_logs = sum(item["new_logs"] for item in baseline_metrics)
    candidate_new_logs = sum(item["new_logs"] for item in candidate_metrics)
    guarded_delta = candidate_guarded_tools - baseline_guarded_tools
    runtime_delta = round(candidate_runtime - baseline_runtime, 3)
    new_logs_delta = candidate_new_logs - baseline_new_logs
    cost_reason = "candidate 在收益提升下未显著增加运行代价"
    if candidate_success == baseline_success:
        cost_status = "hold"
        cost_reason = "表现持平，保留观察，不直接晋升"
    if candidate_success > baseline_success and (
        guarded_delta > max(2, len(candidate_runs))
        or runtime_delta > max(5.0, baseline_runtime * 0.25 if baseline_runtime else 5.0)
        or new_logs_delta > len(candidate_runs)
    ):
        cost_status = "hold"
        cost_reason = "candidate 虽有提升，但 guarded tools / runtime / log 噪声代价偏高，先保留观察"
    gates.append(
        DecisionGate(
            name="cost",
            status=cost_status,
            reason=cost_reason,
            metrics={
                "score_delta": score_delta,
                "baseline_guarded_tools": baseline_guarded_tools,
                "candidate_guarded_tools": candidate_guarded_tools,
                "guarded_tools_delta": guarded_delta,
                "baseline_runtime_seconds": baseline_runtime,
                "candidate_runtime_seconds": candidate_runtime,
                "runtime_delta_seconds": runtime_delta,
                "baseline_new_logs": baseline_new_logs,
                "candidate_new_logs": candidate_new_logs,
                "new_logs_delta": new_logs_delta,
            },
        )
    )

    if candidate_success > baseline_success and cost_status == "pass":
        return gates, "PROMOTE", "candidate 在监督进化 dry-run 中优于 baseline", score_delta
    if candidate_success > baseline_success and cost_status == "hold":
        return gates, "HOLD", "candidate 有提升，但当前代价信号偏高，继续观察", score_delta
    return gates, "HOLD", "baseline 与 candidate 表现持平，保留观察", score_delta


def _apply_promotion_gate(
    *,
    decision: str,
    reason: str,
    gates: List[DecisionGate],
    project_root: Path,
    keep_worktree: bool,
    promotion_gate_runner: Optional[Callable[..., Any]],
) -> tuple[str, str, List[DecisionGate]]:
    if decision != "PROMOTE":
        return decision, reason, gates

    runner = promotion_gate_runner
    if runner is None:
        from core.gym.runner import run_promotion_gate_episode

        runner = run_promotion_gate_episode

    try:
        gate_result = runner(
            project_root=project_root,
            keep_worktree=keep_worktree,
        )
    except Exception as exc:
        gates.append(
            DecisionGate(
                name="gym_promotion",
                status="hold",
                reason=f"Gym promotion gate 运行失败：{type(exc).__name__}: {exc}",
                metrics={"collection_id": "mixed_readiness_gate"},
            )
        )
        return "HOLD", "candidate 已通过监督进化，但 Gym promotion gate 未能完成，先保留观察", gates

    gate_decision = str(getattr(gate_result, "decision", "") or "").upper()
    gate_reason = str(getattr(gate_result, "reason", "") or "")
    gate_metrics = {
        "collection_id": getattr(gate_result, "collection_id", "mixed_readiness_gate"),
        "episode_id": getattr(gate_result, "episode_id", ""),
        "decision": gate_decision,
        "reason": gate_reason,
        "decision_path": getattr(gate_result, "decision_path", ""),
        "promotion_proposal_path": getattr(gate_result, "promotion_proposal_path", None),
    }
    if gate_decision == "PROMOTE":
        gates.append(
            DecisionGate(
                name="gym_promotion",
                status="pass",
                reason="Gym mixed_readiness_gate 通过，允许监督进化晋升",
                metrics=gate_metrics,
            )
        )
        return decision, reason, gates
    if gate_decision == "REJECT":
        gates.append(
            DecisionGate(
                name="gym_promotion",
                status="fail",
                reason=f"Gym mixed_readiness_gate 拒绝晋升：{gate_reason}",
                metrics=gate_metrics,
            )
        )
        return "REJECT", "candidate 已通过监督进化，但 Gym promotion gate 检测到回归", gates

    gates.append(
        DecisionGate(
            name="gym_promotion",
            status="hold",
            reason=f"Gym mixed_readiness_gate 尚未给出晋升许可：{gate_decision or 'UNKNOWN'} {gate_reason}",
            metrics=gate_metrics,
        )
    )
    return "HOLD", "candidate 已通过监督进化，但 Gym promotion gate 要求继续观察", gates


def _append_session_index(path: Path, payload: Dict[str, Any]) -> None:
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _emit_progress(progress_callback: Optional[ProgressCallback], payload: Dict[str, Any]) -> None:
    if progress_callback is None:
        return
    event = dict(payload)
    event["observational"] = True
    progress_callback(event)


def _run_checkpoint(checkpoint_callback: Optional[CheckpointCallback], payload: Dict[str, Any]) -> None:
    if checkpoint_callback is None:
        return
    checkpoint_callback(dict(payload))


def _has_drift_warning(*, status: str, reason: str) -> bool:
    text = f"{status} {reason}".lower()
    markers = (
        "delegation",
        "subagent",
        "spawn_agent",
        "委派",
        "子 agent",
        "子agent",
    )
    return any(marker in text for marker in markers)


def _elapsed_seconds(started_at: str, ended_at: str) -> float:
    started = _parse_iso_timestamp(started_at)
    ended = _parse_iso_timestamp(ended_at)
    if not started or not ended:
        return 0.0
    return max(0.0, round((ended - started).total_seconds(), 3))


def format_decision_record_summary(decision: SupervisedEvolutionDecision) -> str:
    advisory_context = getattr(decision, "advisory_context", {}) or {}
    advisory_lines = _format_advisory_context_lines(advisory_context)
    gate_lines = [
        f"- {gate.name}: {gate.status} | {gate.reason}"
        for gate in decision.gates
    ]
    case_lines = [
        f"- {case.case_id}: {case.baseline_status} -> {case.candidate_status} ({case.decision_signal})"
        for case in decision.case_summaries[:5]
    ]
    lines = [
        f"session: {decision.session_id}",
        f"bundle: {decision.bundle_name}",
        f"decision: {decision.decision}",
        f"reason: {decision.reason}",
        f"baseline: {decision.baseline_summary.successes}/{decision.baseline_summary.total} success ({decision.baseline_success_rate})",
        f"candidate: {decision.candidate_summary.successes}/{decision.candidate_summary.total} success ({decision.candidate_success_rate})",
        f"runtime(avg): {decision.baseline_summary.avg_wall_clock_seconds}s -> {decision.candidate_summary.avg_wall_clock_seconds}s",
        f"validation: {decision.baseline_summary.validation_passed}/{decision.baseline_summary.validation_failed} -> {decision.candidate_summary.validation_passed}/{decision.candidate_summary.validation_failed}",
        f"guarded tools: {decision.baseline_summary.total_guarded_tools} -> {decision.candidate_summary.total_guarded_tools}",
        f"delta: {decision.score_delta}",
        "advisory context:",
        *(advisory_lines or ["- 当前未记住 active advisory baseline"]),
        "gates:",
        *(gate_lines or ["- none"]),
        "cases:",
        *(case_lines or ["- none"]),
        f"record: {decision.decision_path or '-'}",
        f"policy: {(decision.policy_action or {}).get('summary', '-')}",
    ]
    return "\n".join(lines)


def run_supervised_evolution_session(
    *,
    bundle_name: str = DEFAULT_BUNDLE_NAME,
    project_root: Optional[Path] = None,
    keep_worktree: bool = False,
    harness_runner: Optional[Callable[..., HarnessResult]] = None,
    promotion_gate_runner: Optional[Callable[..., Any]] = None,
    progress_callback: Optional[ProgressCallback] = None,
    checkpoint_callback: Optional[CheckpointCallback] = None,
) -> SupervisedEvolutionDecision:
    root = (project_root or get_workspace().project_root).resolve()
    bundle_path = resolve_supervised_bundle_path(bundle_name, project_root=root)
    bundle = load_supervised_bundle(bundle_name, project_root=root)
    dirs = _ensure_supervised_dirs(root)
    session_id = f"supervised_{_now_stamp()}"
    started_at = _now_iso()
    runner = harness_runner or run_harness
    advisory_context = build_active_advisory_snapshot(project_root=root)
    advisory_lines = summarize_active_advisory_baselines(project_root=root, limit=3)

    baseline_runs: List[SupervisedEvolutionRun] = []
    candidate_runs: List[SupervisedEvolutionRun] = []
    cases = bundle["cases"]

    _emit_progress(
        progress_callback,
        {
            "event": "session_start",
            "session_id": session_id,
            "bundle_name": str(bundle.get("bundle_name") or bundle_name),
            "benchmark": str(bundle.get("benchmark") or "dry_run"),
            "case_total": len(cases),
            "keep_worktree": keep_worktree,
            "active_advisory_count": advisory_context.get("active_count", 0),
            "active_advisory_lines": advisory_lines,
        },
    )
    _run_checkpoint(
        checkpoint_callback,
        {
            "phase": "session_start",
            "session_id": session_id,
            "bundle_name": str(bundle.get("bundle_name") or bundle_name),
            "case_total": len(cases),
        },
    )

    for case_index, case in enumerate(cases, start=1):
        case_id = str(case.get("case_id") or "").strip() or "case"
        scenario = str(case.get("scenario") or "transaction").strip() or "transaction"
        mode = str(case.get("mode") or "single_turn").strip() or "single_turn"
        timeout_seconds = int(case.get("timeout_seconds") or bundle.get("default_timeout_seconds") or 600)
        post_restart_observe_seconds = int(case.get("post_restart_observe_seconds") or 20)
        expect_restart = bool(case.get("expect_restart", False))
        baseline_prompt = str(case.get("baseline_prompt") or case.get("prompt") or "").strip()
        candidate_prompt = str(case.get("candidate_prompt") or baseline_prompt).strip()

        for role, prompt, sink in (
            ("baseline", baseline_prompt, baseline_runs),
            ("candidate", candidate_prompt, candidate_runs),
        ):
            _emit_progress(
                progress_callback,
                {
                    "event": "role_start",
                    "session_id": session_id,
                    "case_index": case_index,
                    "case_total": len(cases),
                    "case_id": case_id,
                    "role": role,
                    "scenario": scenario,
                    "mode": mode,
                    "prompt": prompt,
                    "timeout_seconds": timeout_seconds,
                    "keep_worktree": keep_worktree,
                },
            )
            try:
                def emit_live_case_progress(payload: Dict[str, Any]) -> None:
                    _emit_progress(
                        progress_callback,
                        {
                            "event": "role_live",
                            "session_id": session_id,
                            "case_index": case_index,
                            "case_total": len(cases),
                            "case_id": case_id,
                            "role": role,
                            "scenario": scenario,
                            "mode": mode,
                            "prompt": prompt,
                            **payload,
                        },
                    )

                result = runner(
                    repo_root=root,
                    mode=mode,
                    prompt=prompt,
                    scenario=scenario,
                    timeout_seconds=timeout_seconds,
                    expect_restart=expect_restart,
                    post_restart_observe_seconds=post_restart_observe_seconds,
                    keep_worktree=keep_worktree,
                    progress_callback=emit_live_case_progress,
                )
            except Exception as exc:
                _emit_progress(
                    progress_callback,
                    {
                        "event": "session_error",
                        "session_id": session_id,
                        "case_index": case_index,
                        "case_total": len(cases),
                        "case_id": case_id,
                        "role": role,
                        "scenario": scenario,
                        "mode": mode,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                )
                raise
            report_path = None
            session_dir = dirs["sessions"] / session_id
            session_dir.mkdir(parents=True, exist_ok=True)
            report_name = f"{case_id}_{role}.json"
            report_path = session_dir / report_name
            report_path.write_text(json.dumps(asdict(result), ensure_ascii=False, indent=2), encoding="utf-8")
            _emit_progress(
                progress_callback,
                {
                    "event": "role_finish",
                    "session_id": session_id,
                    "case_index": case_index,
                    "case_total": len(cases),
                    "case_id": case_id,
                    "role": role,
                    "status": result.status,
                    "reason": result.reason,
                    "elapsed_seconds": _elapsed_seconds(result.started_at, result.ended_at),
                    "worktree_path": result.worktree_path,
                    "report_path": str(report_path),
                    "drift_warning": _has_drift_warning(status=result.status, reason=result.reason),
                },
            )
            sink.append(
                _to_supervised_run(
                    role=role,
                    case_id=case_id,
                    prompt=prompt,
                    scenario=scenario,
                    mode=mode,
                    result=result,
                    report_path=report_path,
                )
            )
            _run_checkpoint(
                checkpoint_callback,
                {
                    "phase": "role_boundary",
                    "session_id": session_id,
                    "bundle_name": str(bundle.get("bundle_name") or bundle_name),
                    "case_index": case_index,
                    "case_total": len(cases),
                    "case_id": case_id,
                    "role": role,
                },
            )
        _run_checkpoint(
            checkpoint_callback,
            {
                "phase": "case_boundary",
                "session_id": session_id,
                "bundle_name": str(bundle.get("bundle_name") or bundle_name),
                "case_index": case_index,
                "case_total": len(cases),
                "case_id": case_id,
            },
        )

    baseline_summary = _build_run_aggregate(baseline_runs)
    candidate_summary = _build_run_aggregate(candidate_runs)
    case_summaries = _build_case_summaries(baseline_runs, candidate_runs)
    gates, decision, reason, score_delta = _evaluate_gates(baseline_runs, candidate_runs)
    decision, reason, gates = _apply_promotion_gate(
        decision=decision,
        reason=reason,
        gates=gates,
        project_root=root,
        keep_worktree=keep_worktree,
        promotion_gate_runner=promotion_gate_runner,
    )
    ended_at = _now_iso()
    payload = SupervisedEvolutionDecision(
        session_id=session_id,
        bundle_name=str(bundle.get("bundle_name") or bundle_name),
        started_at=started_at,
        ended_at=ended_at,
        benchmark=str(bundle.get("benchmark") or "dry_run"),
        baseline_runs=baseline_runs,
        candidate_runs=candidate_runs,
        baseline_summary=baseline_summary,
        candidate_summary=candidate_summary,
        case_summaries=case_summaries,
        gates=gates,
        decision=decision,
        reason=reason,
        baseline_success_rate=_success_rate(baseline_runs),
        candidate_success_rate=_success_rate(candidate_runs),
        score_delta=score_delta,
        advisory_context=advisory_context,
        summary={
            "case_count": len(cases),
            "baseline_successes": sum(1 for item in baseline_runs if item.status == "success"),
            "candidate_successes": sum(1 for item in candidate_runs if item.status == "success"),
        },
    )
    decision_path = dirs["decisions"] / f"{session_id}.json"
    decision_path.write_text(json.dumps(asdict(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    payload.decision_path = str(decision_path)
    decision_path.write_text(json.dumps(asdict(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    policy_record = execute_supervised_policy(
        decision=payload,
        bundle=bundle,
        bundle_path=bundle_path,
        project_root=root,
    )
    payload.policy_action = asdict(policy_record)
    decision_path.write_text(json.dumps(asdict(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    _append_session_index(
        dirs["base"] / "history.jsonl",
        {
            "session_id": payload.session_id,
            "bundle_name": payload.bundle_name,
            "decision": payload.decision,
            "baseline_success_rate": payload.baseline_success_rate,
            "candidate_success_rate": payload.candidate_success_rate,
            "score_delta": payload.score_delta,
            "decision_path": payload.decision_path,
            "policy_action": payload.policy_action.get("action"),
            "ended_at": payload.ended_at,
        },
    )
    _emit_progress(
        progress_callback,
        {
            "event": "session_finish",
            "session_id": payload.session_id,
            "bundle_name": payload.bundle_name,
            "decision": payload.decision,
            "reason": payload.reason,
            "decision_path": payload.decision_path,
            "policy_action": payload.policy_action.get("action"),
            "active_advisory_count": advisory_context.get("active_count", 0),
        },
    )
    return payload


def _format_advisory_context_lines(advisory_context: Dict[str, Any]) -> list[str]:
    if not isinstance(advisory_context, dict):
        return []
    count = int(advisory_context.get("active_count") or 0)
    entries = advisory_context.get("entries") if isinstance(advisory_context.get("entries"), list) else []
    if count <= 0:
        return ["- 当前未记住 active advisory baseline"]
    lines = [f"- active_count={count}"]
    for item in entries[:3]:
        if not isinstance(item, dict):
            continue
        lines.append(
            "- "
            f"{item.get('target_label') or item.get('target_key') or '-'} "
            f"proposal={item.get('proposal_id') or '-'} "
            f"runtime_effect={item.get('runtime_effect') or 'not_applied'} "
            f"agent_consumption={item.get('agent_consumption') or 'advisory'}"
        )
    hidden = count - min(len(entries), 3)
    if hidden > 0:
        lines.append(f"- ... 还有 {hidden} 个 active advisory baseline")
    return lines


__all__ = [
    "DEFAULT_BUNDLE_NAME",
    "DecisionGate",
    "RunAggregate",
    "CaseDecisionSummary",
    "SupervisedEvolutionDecision",
    "SupervisedEvolutionRun",
    "format_decision_record_summary",
    "load_supervised_bundle",
    "resolve_supervised_bundle_path",
    "run_supervised_evolution_session",
]
