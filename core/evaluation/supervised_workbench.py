# -*- coding: utf-8 -*-
"""Supervised Evolution workbench helpers.

This module keeps Decision Record, Lineage, Bundle preview, and persisted
Workbench state knowledge in the evolution domain instead of the UI shell.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .lineage import summarize_lineage


@dataclass(frozen=True)
class DecisionHistoryRecord:
    path: str
    session_id: str
    bundle_name: str
    decision: str
    reason: str
    ended_at: str
    lineage_index_path: str | None = None

    @property
    def decision_path(self) -> str:
        return self.path


@dataclass(frozen=True)
class DatasetRunPreparation:
    dataset_name: str
    dataset_limit: int | None
    bundle_name: str
    runnable: bool
    adapter_status: str
    summary: str
    blocked_message: str = ""


@dataclass(frozen=True)
class SupervisedWorkbenchRunResult:
    decision: Any
    decision_summary: str
    result_border_style: str
    lineage_index_path: str | None = None
    lineage_summary: str | None = None


@dataclass(frozen=True)
class SupervisedGymProposalLifecycle:
    supervised_decision_path: str
    proposal_path: str | None
    proposal_id: str | None
    episode_id: str | None
    gym_decision_path: str | None
    trace_index_path: str | None
    status: str
    target_key: str | None = None
    runtime_effect: str = "not_applied"
    agent_consumption: str = "advisory"
    registry_path: str | None = None
    history_path: str | None = None
    apply_ledger_path: str | None = None
    rollback_ledger_path: str | None = None
    previous_active_proposal_id: str | None = None
    active_registry_match: bool = False
    available_actions: tuple[str, ...] = ()
    note: str = ""
    error: str = ""


@dataclass(frozen=True)
class SupervisedGymProposalActionResult:
    action: str
    proposal_id: str | None
    lifecycle: SupervisedGymProposalLifecycle
    summary: str


def default_bundle_name() -> str:
    from .supervised_evolution import DEFAULT_BUNDLE_NAME

    return DEFAULT_BUNDLE_NAME


def format_run_banner(bundle_name: str, keep_worktree: bool) -> str:
    return f"bundle={bundle_name}\nkeep_worktree={keep_worktree}"


def run_workbench_session(
    bundle_name: str,
    keep_worktree: bool,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    project_root: Path | None = None,
) -> SupervisedWorkbenchRunResult:
    from .supervised_evolution import format_decision_record_summary, run_supervised_evolution_session

    kwargs: dict[str, Any] = {
        "bundle_name": bundle_name,
        "keep_worktree": keep_worktree,
    }
    if progress_callback is not None:
        kwargs["progress_callback"] = progress_callback
    if project_root is not None:
        kwargs["project_root"] = project_root
    decision = run_supervised_evolution_session(**kwargs)
    lineage_index_path = (decision.policy_action or {}).get("lineage_index_path")
    return SupervisedWorkbenchRunResult(
        decision=decision,
        decision_summary=format_decision_record_summary(decision),
        result_border_style="green" if decision.decision in {"PROMOTE", "HOLD"} else "red",
        lineage_index_path=lineage_index_path,
        lineage_summary=(
            format_lineage_summary(lineage_index_path, decision.bundle_name) if lineage_index_path else None
        ),
    )


def list_dataset_choices(project_root: Path) -> list[dict]:
    from .dataset_registry import list_dataset_status

    return list_dataset_status(project_root)


def prepare_dataset_run(project_root: Path, dataset_name: str, dataset_limit: int | None) -> DatasetRunPreparation:
    from .dataset_registry import materialize_dataset_bundle

    materialized = materialize_dataset_bundle(dataset_name, project_root=project_root, limit=dataset_limit)
    adapter_status = getattr(materialized, "adapter_status", "-")
    runnable = bool(getattr(materialized, "runnable", False))
    return DatasetRunPreparation(
        dataset_name=getattr(materialized, "dataset_name", dataset_name),
        dataset_limit=dataset_limit,
        bundle_name=getattr(materialized, "bundle_name", "-"),
        runnable=runnable,
        adapter_status=adapter_status,
        summary=format_materialization_summary(materialized, dataset_name),
        blocked_message=(
            ""
            if runnable
            else f"{dataset_name} 已登记，但 adapter_status={adapter_status}，当前不能直接运行。"
        ),
    )


def format_lineage_summary(lineage_index_path: str, bundle_name: str, limit: int = 3) -> str:
    summary = summarize_lineage(bundle_name=bundle_name, limit=limit, lineage_index_path=lineage_index_path)
    if not summary.path or not Path(summary.path).exists():
        return "lineage index 不可用"
    if not summary.items:
        return "暂无 lineage 记录"
    lines = [
        f"bundle cases: {summary.bundle_case_count}",
        f"index cases: {summary.index_case_count}",
    ]
    for item in summary.items:
        lines.append(
            f"- {item.case_id or '?'}: baseline={item.current_baseline_id or '-'} latest={item.latest_candidate_id or '-'}"
        )
        lines.append(f"  chain: {item.chain_preview}")
    return "\n".join(lines)


def extract_gym_promotion_proposal_path(decision_source: Any) -> str | None:
    for gate in _decision_gates(decision_source):
        metrics = gate.get("metrics") if isinstance(gate.get("metrics"), dict) else {}
        proposal_path = str(metrics.get("promotion_proposal_path") or "").strip()
        if proposal_path:
            return proposal_path
    return None


def load_gym_promotion_lifecycle(
    decision_source: Any,
    *,
    project_root: Path | None = None,
) -> SupervisedGymProposalLifecycle:
    root = _resolve_project_root(project_root)
    supervised_decision_path = _decision_path_from_source(decision_source)
    proposal_path_text = extract_gym_promotion_proposal_path(decision_source)

    if not proposal_path_text:
        return SupervisedGymProposalLifecycle(
            supervised_decision_path=supervised_decision_path or "-",
            proposal_path=None,
            proposal_id=None,
            episode_id=None,
            gym_decision_path=None,
            trace_index_path=None,
            status="missing",
            available_actions=(),
            note="该监督结果没有可操作的 Gym promotion proposal。",
        )

    proposal_path = Path(proposal_path_text).resolve()
    if not proposal_path.exists():
        return SupervisedGymProposalLifecycle(
            supervised_decision_path=supervised_decision_path or "-",
            proposal_path=str(proposal_path),
            proposal_id=None,
            episode_id=None,
            gym_decision_path=None,
            trace_index_path=None,
            status="missing",
            available_actions=(),
            note="Gym promotion proposal 文件不存在。",
        )

    try:
        proposal = _load_json_object(proposal_path, label="Gym promotion proposal")
    except ValueError as exc:
        return SupervisedGymProposalLifecycle(
            supervised_decision_path=supervised_decision_path or "-",
            proposal_path=str(proposal_path),
            proposal_id=None,
            episode_id=None,
            gym_decision_path=None,
            trace_index_path=None,
            status="invalid",
            available_actions=(),
            error=str(exc),
        )

    proposal_id = _optional_text(proposal, "proposal_id")
    episode_id = _optional_text(proposal, "episode_id")
    status = _optional_text(proposal, "status") or "unknown"
    gym_decision_path = _resolve_known_path(
        proposal.get("decision_path"),
        root / "workspace" / "gym" / "decisions" / f"{episode_id}.json" if episode_id else None,
    )
    trace_index_path = _resolve_known_path(
        proposal.get("trace_index_path"),
        root / "workspace" / "gym" / "traces" / episode_id / "index.json" if episode_id else None,
    )
    registry_path = _resolve_known_path(
        proposal.get("activation_registry_path"),
        root / "workspace" / "gym" / "active_promotions.json",
    )
    history_path = _resolve_known_path(
        proposal.get("activation_history_path"),
        root / "workspace" / "gym" / "activation_history.jsonl",
    )
    apply_ledger_path = _resolve_known_path(
        proposal.get("ledger_path"),
        root / "workspace" / "gym" / "applied_promotions.jsonl",
    )
    rollback_ledger_path = _resolve_known_path(
        proposal.get("rollback_ledger_path"),
        root / "workspace" / "gym" / "rolled_back_promotions.jsonl",
    )
    target_key = _optional_text(proposal, "target_key")
    runtime_effect = _optional_text(proposal, "runtime_effect") or "not_applied"
    agent_consumption = _optional_text(proposal, "agent_consumption") or "advisory"
    previous_active_proposal_id = _optional_text(proposal, "previous_active_proposal_id")
    active_registry_match = _matches_active_registry(
        registry_path=registry_path,
        target_key=target_key,
        proposal_id=proposal_id,
    )

    note = ""
    if status == "active" and not active_registry_match:
        note = "proposal 标记为 active，但当前 active registry 中没有匹配项。"
    elif status == "superseded":
        note = "该 proposal 已被更新的 active proposal 替代。"
    elif status == "rolled_back":
        note = "该 proposal 已回滚，仅保留审计证据。"

    return SupervisedGymProposalLifecycle(
        supervised_decision_path=supervised_decision_path or "-",
        proposal_path=str(proposal_path),
        proposal_id=proposal_id,
        episode_id=episode_id,
        gym_decision_path=gym_decision_path,
        trace_index_path=trace_index_path,
        status=status,
        target_key=target_key,
        runtime_effect=runtime_effect,
        agent_consumption=agent_consumption,
        registry_path=registry_path,
        history_path=history_path,
        apply_ledger_path=apply_ledger_path,
        rollback_ledger_path=rollback_ledger_path,
        previous_active_proposal_id=previous_active_proposal_id,
        active_registry_match=active_registry_match,
        available_actions=_available_actions_for_status(status),
        note=note,
    )


def execute_gym_promotion_action(
    decision_source: Any,
    action: str,
    *,
    project_root: Path | None = None,
) -> SupervisedGymProposalActionResult:
    root = _resolve_project_root(project_root)
    lifecycle = load_gym_promotion_lifecycle(decision_source, project_root=root)
    if action not in lifecycle.available_actions:
        raise ValueError(f"Gym promotion proposal 当前状态={lifecycle.status}，不能执行 {action}")
    if not lifecycle.proposal_path:
        raise ValueError("当前监督结果没有可操作的 Gym promotion proposal")

    from core.gym import (
        activate_gym_promotion_proposal,
        apply_gym_promotion_proposal,
        rollback_gym_promotion_proposal,
    )

    if action == "apply":
        result = apply_gym_promotion_proposal(lifecycle.proposal_path, project_root=root, approved_by="workbench")
        summary_lines = [
            f"action: apply",
            f"proposal: {result.proposal_id}",
            f"status: {result.status}",
            f"decision: {result.decision_path}",
            f"trace_index: {result.trace_index_path}",
        ]
    elif action == "activate":
        result = activate_gym_promotion_proposal(lifecycle.proposal_path, project_root=root, activated_by="workbench")
        summary_lines = [
            f"action: activate",
            f"proposal: {result.proposal_id}",
            f"status: {result.status}",
            f"target: {result.target_key}",
            f"runtime_effect: {result.runtime_effect}",
            f"agent_consumption: {result.agent_consumption}",
            f"previous_active: {result.previous_active_proposal_id or '-'}",
        ]
    elif action == "rollback":
        result = rollback_gym_promotion_proposal(
            lifecycle.proposal_path,
            project_root=root,
            rolled_back_by="workbench",
            reason="manual supervised workbench rollback",
        )
        summary_lines = [
            f"action: rollback",
            f"proposal: {result.proposal_id}",
            f"status: {result.status}",
            f"reason: {result.reason or '-'}",
            f"decision: {result.decision_path}",
            f"trace_index: {result.trace_index_path}",
        ]
    else:
        raise ValueError(f"未知 Gym proposal 动作: {action}")

    refreshed = load_gym_promotion_lifecycle(decision_source, project_root=root)
    return SupervisedGymProposalActionResult(
        action=action,
        proposal_id=lifecycle.proposal_id,
        lifecycle=refreshed,
        summary="\n".join(summary_lines),
    )


def format_gym_promotion_lifecycle(lifecycle: SupervisedGymProposalLifecycle) -> str:
    lines = [
        f"proposal: {lifecycle.proposal_id or '-'}",
        f"status: {lifecycle.status}",
        f"target: {lifecycle.target_key or '-'}",
        f"runtime_effect: {lifecycle.runtime_effect}",
        f"agent_consumption: {lifecycle.agent_consumption}",
        f"active_registry_match: {'yes' if lifecycle.active_registry_match else 'no'}",
        f"available_actions: {', '.join(lifecycle.available_actions) if lifecycle.available_actions else '-'}",
        f"proposal_path: {lifecycle.proposal_path or '-'}",
        f"supervised_decision: {lifecycle.supervised_decision_path or '-'}",
        f"gym_decision: {lifecycle.gym_decision_path or '-'}",
        f"trace_index: {lifecycle.trace_index_path or '-'}",
        f"registry: {lifecycle.registry_path or '-'}",
        f"activation_history: {lifecycle.history_path or '-'}",
        f"apply_ledger: {lifecycle.apply_ledger_path or '-'}",
        f"rollback_ledger: {lifecycle.rollback_ledger_path or '-'}",
        f"previous_active: {lifecycle.previous_active_proposal_id or '-'}",
    ]
    if lifecycle.note:
        lines.append(f"note: {lifecycle.note}")
    if lifecycle.error:
        lines.append(f"error: {lifecycle.error}")
    return "\n".join(lines)


def dataset_status_line(item: dict, index: int | None = None) -> str:
    prefix = f"{index}. " if index is not None else "- "
    ready = "ready" if item["available"] else "missing-source"
    runnable = "runnable" if item["runnable"] else item["adapter_status"]
    return f"{prefix}{item['name']} [{ready}, {runnable}] -> {item['bundle_name']}"


def select_dataset_by_input(datasets: list[dict], raw: str) -> dict | None:
    value = raw.strip()
    if not value and datasets:
        return datasets[0]
    if value.isdigit():
        index = int(value)
        if 1 <= index <= len(datasets):
            return datasets[index - 1]
    for item in datasets:
        if item["name"] == value:
            return item
    return None


def format_bundle_preview(bundle_path: str) -> str:
    path = Path(bundle_path)
    if not path.exists():
        return f"bundle 文件不存在：{bundle_path}"
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get("cases") or []
    lines = [
        f"bundle: {payload.get('bundle_name', path.stem)}",
        f"benchmark: {payload.get('benchmark', '-')}",
        f"cases: {len(cases)}",
    ]
    for case in cases[:5]:
        prompt = str(case.get("candidate_prompt") or case.get("baseline_prompt") or "").replace("\n", " ")
        if len(prompt) > 96:
            prompt = prompt[:93] + "..."
        lines.append(f"- {case.get('case_id', '?')} [{case.get('scenario', '-')}/{case.get('mode', '-')}] {prompt}")
    if len(cases) > 5:
        lines.append(f"... 还有 {len(cases) - 5} 个 case")
    return "\n".join(lines)


def resolve_workbench_bundle_path(project_root: Path, bundle_name: str) -> Path:
    return project_root / "workspace" / "evaluation" / "bundles" / f"{bundle_name}.json"


def format_materialization_summary(materialized: object, fallback_dataset_name: str) -> str:
    return "\n".join(
        [
            f"dataset: {getattr(materialized, 'dataset_name', fallback_dataset_name)}",
            f"bundle: {getattr(materialized, 'bundle_name', '-')}",
            f"cases: {getattr(materialized, 'case_count', '-')}",
            f"adapter: {getattr(materialized, 'adapter_status', '-')}",
            f"runnable: {getattr(materialized, 'runnable', False)}",
            f"path: {getattr(materialized, 'bundle_path', '-')}",
        ]
    )


def build_workbench_state(
    *,
    source_kind: str,
    bundle_name: str,
    keep_worktree: bool,
    dataset_name: str | None = None,
    dataset_limit: int | None = None,
) -> dict:
    if str(source_kind or "").strip().lower() in {"1", "dataset"}:
        return {
            "source": "dataset",
            "dataset_name": dataset_name,
            "dataset_limit": dataset_limit,
            "bundle_name": bundle_name,
            "keep_worktree": keep_worktree,
        }
    return {
        "source": "bundle",
        "bundle_name": bundle_name,
        "keep_worktree": keep_worktree,
    }


def format_file_excerpt(file_path: str, limit: int = 4000) -> str:
    path = Path(file_path)
    if not path.exists():
        return f"文件不存在：{file_path}"
    content = path.read_text(encoding="utf-8", errors="replace")
    if len(content) <= limit:
        return content
    return content[:limit] + f"\n... 已截断，还剩 {len(content) - limit} 字符"


def list_recent_decision_records(project_root: Path, limit: int = 8) -> list[DecisionHistoryRecord]:
    decisions_dir = project_root / "workspace" / "supervised_evolution" / "decisions"
    if not decisions_dir.exists():
        return []
    records = []
    for path in sorted(decisions_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)[:limit]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        policy_action = payload.get("policy_action") if isinstance(payload.get("policy_action"), dict) else {}
        records.append(
            DecisionHistoryRecord(
                path=str(path),
                session_id=payload.get("session_id") or path.stem,
                bundle_name=payload.get("bundle_name") or "-",
                decision=payload.get("decision") or "-",
                reason=payload.get("reason") or "-",
                ended_at=payload.get("ended_at") or "-",
                lineage_index_path=policy_action.get("lineage_index_path"),
            )
        )
    return records


def format_decision_history(records: list[DecisionHistoryRecord]) -> str:
    if not records:
        return "暂无 decision 记录"
    lines = []
    for idx, item in enumerate(records, start=1):
        reason = str(item.reason).replace("\n", " ")
        if len(reason) > 80:
            reason = reason[:77] + "..."
        lines.append(
            f"{idx}. {item.ended_at} {item.decision} {item.bundle_name} "
            f"({item.session_id}) - {reason}"
        )
    return "\n".join(lines)


def select_decision_record(records: list[DecisionHistoryRecord], raw: str) -> DecisionHistoryRecord | None:
    value = raw.strip()
    if not value and records:
        return records[0]
    if value.isdigit():
        index = int(value)
        if 1 <= index <= len(records):
            return records[index - 1]
    for item in records:
        if item.session_id == value:
            return item
    return None


def workbench_state_path(project_root: Path) -> Path:
    return project_root / "workspace" / "supervised_evolution" / "workbench_state.json"


def save_workbench_state(project_root: Path, state: dict) -> None:
    path = workbench_state_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def load_workbench_state(project_root: Path) -> dict:
    path = workbench_state_path(project_root)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _decision_path_from_source(decision_source: Any) -> str | None:
    if isinstance(decision_source, DecisionHistoryRecord):
        return decision_source.decision_path
    if isinstance(decision_source, Path):
        return str(decision_source.resolve())
    if isinstance(decision_source, str):
        return str(Path(decision_source).resolve())
    if isinstance(decision_source, dict):
        value = decision_source.get("decision_path")
    else:
        value = getattr(decision_source, "decision_path", None)
    value_text = str(value or "").strip()
    return str(Path(value_text).resolve()) if value_text else None


def _decision_gates(decision_source: Any) -> list[dict[str, Any]]:
    if isinstance(decision_source, DecisionHistoryRecord):
        payload = _load_decision_payload(Path(decision_source.decision_path))
        return _coerce_gates(payload.get("gates"))
    if isinstance(decision_source, Path):
        payload = _load_decision_payload(decision_source)
        return _coerce_gates(payload.get("gates"))
    if isinstance(decision_source, str):
        payload = _load_decision_payload(Path(decision_source))
        return _coerce_gates(payload.get("gates"))
    if isinstance(decision_source, dict):
        return _coerce_gates(decision_source.get("gates"))
    return _coerce_gates(getattr(decision_source, "gates", None))


def _coerce_gates(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _load_decision_payload(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    if not path.exists():
        raise ValueError(f"Missing {label}: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid {label}: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid {label}: expected object at {path}")
    return payload


def _resolve_project_root(project_root: Path | None) -> Path:
    if project_root is not None:
        return project_root.resolve()
    from core.infrastructure.workspace_manager import get_workspace

    return get_workspace().project_root.resolve()


def _optional_text(payload: dict[str, Any], key: str) -> str | None:
    value = str(payload.get(key) or "").strip()
    return value or None


def _resolve_known_path(primary: Any, fallback: Path | None) -> str | None:
    primary_text = str(primary or "").strip()
    if primary_text:
        return str(Path(primary_text).resolve())
    if fallback is None:
        return None
    return str(fallback.resolve())


def _available_actions_for_status(status: str) -> tuple[str, ...]:
    if status == "proposed":
        return ("apply",)
    if status == "applied":
        return ("activate", "rollback")
    if status == "active":
        return ("rollback",)
    return ()


def _matches_active_registry(*, registry_path: str | None, target_key: str | None, proposal_id: str | None) -> bool:
    if not registry_path or not target_key or not proposal_id:
        return False
    path = Path(registry_path)
    if not path.exists():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    active = payload.get("active") if isinstance(payload, dict) else None
    if not isinstance(active, dict):
        return False
    entry = active.get(target_key)
    return isinstance(entry, dict) and str(entry.get("proposal_id") or "") == proposal_id
