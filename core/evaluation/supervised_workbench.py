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


def default_bundle_name() -> str:
    from .supervised_evolution import DEFAULT_BUNDLE_NAME

    return DEFAULT_BUNDLE_NAME


def format_run_banner(bundle_name: str, keep_worktree: bool) -> str:
    return f"bundle={bundle_name}\nkeep_worktree={keep_worktree}"


def run_workbench_session(
    bundle_name: str,
    keep_worktree: bool,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> SupervisedWorkbenchRunResult:
    from .supervised_evolution import format_decision_record_summary, run_supervised_evolution_session

    kwargs: dict[str, Any] = {
        "bundle_name": bundle_name,
        "keep_worktree": keep_worktree,
    }
    if progress_callback is not None:
        kwargs["progress_callback"] = progress_callback
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
    if source_kind == "1":
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
