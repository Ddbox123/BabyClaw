# -*- coding: utf-8 -*-
"""CLI helpers for supervised evolution from the unified agent entrypoint."""

from __future__ import annotations

import dataclasses
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .dataset_registry import list_dataset_status, materialize_dataset_bundle
from .supervised_dashboard import generate_supervised_dashboard
from .supervised_evolution import DEFAULT_BUNDLE_NAME, run_supervised_evolution_session


def print_dataset_menu(rows: List[Dict[str, Any]]) -> None:
    print("可选择的数据集：")
    for idx, item in enumerate(rows, start=1):
        availability = "可用" if item["available"] else "缺少源文件"
        runnable = "可运行" if item["runnable"] else f"暂不可运行:{item['adapter_status']}"
        print(f"{idx}. {item['name']} [{availability}, {runnable}] -> {item['bundle_name']}")
        print(f"   {item['description']}")


def choose_dataset_interactively(*, project_root: Path) -> Tuple[str, Optional[int]]:
    rows = list_dataset_status(project_root)
    if not rows:
        raise RuntimeError("数据集注册表为空")

    print_dataset_menu(rows)
    selected = None
    while selected is None:
        raw = input("请输入数据集编号或名称（直接回车选择 1）：").strip()
        if not raw:
            selected = rows[0]
            break
        if raw.isdigit():
            index = int(raw)
            if 1 <= index <= len(rows):
                selected = rows[index - 1]
                break
        for item in rows:
            if item["name"] == raw:
                selected = item
                break
        if selected is None:
            print("选择无效，请重新输入。")

    limit_raw = input("导入 case 上限（直接回车表示全部）：").strip()
    limit = int(limit_raw) if limit_raw else None
    return str(selected["name"]), limit


def should_handle_supervised_cli(args: Any) -> bool:
    return bool(
        getattr(args, "supervised_evolution", False)
        or getattr(args, "list_datasets", False)
        or getattr(args, "choose_dataset", False)
        or getattr(args, "supervised_dashboard", False)
        or getattr(args, "dataset", None)
        or getattr(args, "bundle", None)
    )


def run_supervised_cli_from_args(*, args: Any, project_root: Path) -> int:
    if getattr(args, "list_datasets", False):
        print(json.dumps(list_dataset_status(project_root), ensure_ascii=False, indent=2))
        return 0

    if getattr(args, "supervised_dashboard", False):
        dashboard = generate_supervised_dashboard(project_root=project_root)
        print(json.dumps(_to_jsonable(dashboard), ensure_ascii=False, indent=2))
        return 0

    bundle_name = getattr(args, "bundle", None) or DEFAULT_BUNDLE_NAME
    dataset_name = getattr(args, "dataset", None)
    dataset_limit = getattr(args, "dataset_limit", None)

    if getattr(args, "choose_dataset", False):
        dataset_name, chosen_limit = choose_dataset_interactively(project_root=project_root)
        if dataset_limit is None:
            dataset_limit = chosen_limit

    if dataset_name:
        materialized = materialize_dataset_bundle(
            dataset_name,
            project_root=project_root,
            limit=dataset_limit,
        )
        print(json.dumps(asdict(materialized), ensure_ascii=False, indent=2))
        if not materialized.runnable:
            print(
                f"数据集 {dataset_name} 已登记/物化，但 adapter_status={materialized.adapter_status}，"
                "当前不能直接用 supervised harness 运行。",
                file=sys.stderr,
            )
            return 2
        bundle_name = materialized.bundle_name

    decision = run_supervised_evolution_session(
        bundle_name=bundle_name,
        keep_worktree=bool(getattr(args, "keep_worktree", False)),
    )
    print(json.dumps(asdict(decision), ensure_ascii=False, indent=2))
    if bool(getattr(args, "fail_on_regression", False)) and decision.decision in {"ROLLBACK", "REJECT"}:
        return 1
    return 0


def _to_jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return asdict(value)
    dashboard_keys = (
        "html_path",
        "session_count",
        "skipped_count",
        "latest_decision",
        "risk_level",
        "agent_consumption",
        "runtime_authorization",
    )
    if all(hasattr(value, key) for key in dashboard_keys):
        return {key: getattr(value, key) for key in dashboard_keys}
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return value


__all__ = [
    "choose_dataset_interactively",
    "print_dataset_menu",
    "run_supervised_cli_from_args",
    "should_handle_supervised_cli",
]
