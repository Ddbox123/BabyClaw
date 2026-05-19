# -*- coding: utf-8 -*-
"""Dataset registry and bundle materialization for supervised evaluation."""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from core.infrastructure.workspace_manager import get_workspace

from .supervised_evolution import DEFAULT_BUNDLE_NAME, resolve_supervised_bundle_path


DATASET_REGISTRY_PATH = Path("workspace/evaluation/datasets/registry.json")


@dataclass
class DatasetSpec:
    name: str
    kind: str
    description: str
    bundle_name: str
    source_path: Optional[str] = None
    scenario: str = "transaction"
    mode: str = "single_turn"
    timeout_seconds: int = 600
    runnable: bool = True
    adapter_status: str = "ready"
    tags: List[str] = None

    def __post_init__(self) -> None:
        if self.tags is None:
            self.tags = []


@dataclass
class DatasetMaterialization:
    dataset_name: str
    bundle_name: str
    bundle_path: str
    case_count: int
    runnable: bool
    adapter_status: str
    source_path: Optional[str] = None


def _registry_path(project_root: Optional[Path] = None) -> Path:
    root = (project_root or get_workspace().project_root).resolve()
    return root / DATASET_REGISTRY_PATH


def _default_registry_payload() -> Dict[str, Any]:
    return {
        "version": 1,
        "datasets": [
            {
                "name": "supervised_dry_run",
                "kind": "supervised_bundle",
                "description": "内置监督进化 dry-run 探针集，用于验证事务、lint 和安全修改闭环。",
                "bundle_name": DEFAULT_BUNDLE_NAME,
                "runnable": True,
                "adapter_status": "ready",
                "tags": ["builtin", "smoke"],
            },
            {
                "name": "custom_prompt_jsonl",
                "kind": "prompt_jsonl",
                "description": "通用 JSONL 任务集。每行可包含 case_id、prompt/problem_statement、expected、scenario 等字段。",
                "source_path": "workspace/evaluation/datasets/custom_prompt_tasks.jsonl",
                "bundle_name": "custom_prompt_jsonl_v1",
                "scenario": "transaction",
                "mode": "single_turn",
                "timeout_seconds": 600,
                "runnable": True,
                "adapter_status": "ready",
                "tags": ["local", "jsonl"],
            },
            {
                "name": "generated_cases",
                "kind": "generated_case_jsonl",
                "description": "Gym 依据 Trace、Harness Gap 或 Improvement Episode 生成的训练压力，不可自动进入 holdout。",
                "source_path": "workspace/evaluation/datasets/generated_cases.jsonl",
                "bundle_name": "generated_cases_v1",
                "scenario": "transaction",
                "mode": "single_turn",
                "timeout_seconds": 600,
                "runnable": True,
                "adapter_status": "ready",
                "tags": ["generated", "gym"],
            },
            {
                "name": "chat_reviewed_multiturn",
                "kind": "prompt_jsonl",
                "description": "经人工审核通过的多轮 chat 协作片段，物化为单 case prompt，用于监督进化和回归评测。",
                "source_path": "workspace/evaluation/datasets/chat_reviewed_multiturn.jsonl",
                "bundle_name": "chat_reviewed_multiturn_v1",
                "scenario": "conversation_collaboration",
                "mode": "single_turn",
                "timeout_seconds": 600,
                "runnable": True,
                "adapter_status": "ready",
                "tags": ["chat", "multiturn", "reviewed"],
            },
            {
                "name": "swe_bench_lite",
                "kind": "swe_bench_jsonl",
                "description": "SWE-bench Lite 本地 JSONL。字段通常包含 instance_id、repo、base_commit、problem_statement、patch、test_patch。",
                "source_path": "workspace/evaluation/datasets/swe_bench_lite.jsonl",
                "bundle_name": "swe_bench_lite_v1",
                "scenario": "swe_patch",
                "mode": "single_turn",
                "timeout_seconds": 1800,
                "runnable": False,
                "adapter_status": "requires_swe_harness",
                "tags": ["swe", "external-repo"],
            },
            {
                "name": "swe_bench_verified",
                "kind": "swe_bench_jsonl",
                "description": "SWE-bench Verified 本地 JSONL。需要后续接入官方 SWE-bench harness 才能真实判分。",
                "source_path": "workspace/evaluation/datasets/swe_bench_verified.jsonl",
                "bundle_name": "swe_bench_verified_v1",
                "scenario": "swe_patch",
                "mode": "single_turn",
                "timeout_seconds": 1800,
                "runnable": False,
                "adapter_status": "requires_swe_harness",
                "tags": ["swe", "verified", "external-repo"],
            },
            {
                "name": "humaneval_jsonl",
                "kind": "prompt_jsonl",
                "description": "HumanEval 风格 JSONL。每行可包含 task_id、prompt、canonical_solution/tests 等字段。",
                "source_path": "workspace/evaluation/datasets/humaneval.jsonl",
                "bundle_name": "humaneval_local_v1",
                "scenario": "transaction",
                "mode": "single_turn",
                "timeout_seconds": 600,
                "runnable": True,
                "adapter_status": "ready",
                "tags": ["codegen", "jsonl"],
            },
            {
                "name": "mbpp_jsonl",
                "kind": "prompt_jsonl",
                "description": "MBPP 风格 JSONL。每行可包含 task_id、text/prompt、test_list/code 等字段。",
                "source_path": "workspace/evaluation/datasets/mbpp.jsonl",
                "bundle_name": "mbpp_local_v1",
                "scenario": "transaction",
                "mode": "single_turn",
                "timeout_seconds": 600,
                "runnable": True,
                "adapter_status": "ready",
                "tags": ["codegen", "jsonl"],
            },
        ],
    }


def ensure_dataset_registry(project_root: Optional[Path] = None) -> Path:
    path = _registry_path(project_root)
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_default_registry_payload(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def load_dataset_specs(project_root: Optional[Path] = None) -> List[DatasetSpec]:
    path = ensure_dataset_registry(project_root)
    payload = json.loads(path.read_text(encoding="utf-8"))
    specs = []
    for item in payload.get("datasets") or []:
        specs.append(
            DatasetSpec(
                name=str(item.get("name") or "").strip(),
                kind=str(item.get("kind") or "").strip(),
                description=str(item.get("description") or "").strip(),
                bundle_name=str(item.get("bundle_name") or "").strip(),
                source_path=item.get("source_path"),
                scenario=str(item.get("scenario") or "transaction"),
                mode=str(item.get("mode") or "single_turn"),
                timeout_seconds=int(item.get("timeout_seconds") or 600),
                runnable=bool(item.get("runnable", True)),
                adapter_status=str(item.get("adapter_status") or "ready"),
                tags=list(item.get("tags") or []),
            )
        )
    return [item for item in specs if item.name and item.kind and item.bundle_name]


def get_dataset_spec(dataset_name: str, *, project_root: Optional[Path] = None) -> DatasetSpec:
    for spec in load_dataset_specs(project_root):
        if spec.name == dataset_name:
            return spec
    available = ", ".join(item.name for item in load_dataset_specs(project_root)) or "none"
    raise ValueError(f"未知数据集: {dataset_name}；可选: {available}")


def resolve_source_path(spec: DatasetSpec, project_root: Path) -> Optional[Path]:
    if not spec.source_path:
        return None
    path = Path(spec.source_path)
    if not path.is_absolute():
        path = project_root / path
    return path.resolve()


def list_dataset_status(project_root: Optional[Path] = None) -> List[Dict[str, Any]]:
    root = (project_root or get_workspace().project_root).resolve()
    rows = []
    for spec in load_dataset_specs(root):
        source = resolve_source_path(spec, root)
        bundle_path = root / "workspace" / "evaluation" / "bundles" / f"{spec.bundle_name}.json"
        available = spec.kind == "supervised_bundle" or bool(source and source.exists())
        rows.append(
            {
                "name": spec.name,
                "kind": spec.kind,
                "bundle_name": spec.bundle_name,
                "runnable": spec.runnable,
                "available": available,
                "adapter_status": spec.adapter_status,
                "source_path": str(source) if source else None,
                "source_exists": bool(source and source.exists()),
                "bundle_path": str(bundle_path),
                "bundle_exists": bundle_path.exists(),
                "description": spec.description,
                "tags": spec.tags,
            }
        )
    return rows


def _iter_jsonl(path: Path, *, limit: Optional[int] = None) -> Iterable[Dict[str, Any]]:
    count = 0
    with path.open("r", encoding="utf-8") as fh:
        for line_number, line in enumerate(fh, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                row = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number} 不是合法 JSONL: {exc}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_number} 必须是 JSON object")
            yield row
            count += 1
            if limit is not None and count >= limit:
                break


def _slug(value: str, fallback: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9_.-]+", "_", value.strip()).strip("_")
    return text[:120] or fallback


def _prompt_from_row(row: Dict[str, Any]) -> str:
    for key in ("prompt", "problem_statement", "text", "instruction", "task", "prompt_seed"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise ValueError("JSONL row 缺少 prompt/problem_statement/text/instruction/task/prompt_seed 字段")


def _case_id_from_row(row: Dict[str, Any], index: int) -> str:
    for key in ("case_id", "instance_id", "task_id", "id"):
        value = row.get(key)
        if value is not None and str(value).strip():
            return _slug(str(value), f"case_{index:04d}")
    return f"case_{index:04d}"


def _build_prompt_case(spec: DatasetSpec, row: Dict[str, Any], index: int) -> Dict[str, Any]:
    prompt = _prompt_from_row(row)
    case = {
        "case_id": _case_id_from_row(row, index),
        "scenario": str(row.get("scenario") or spec.scenario),
        "mode": str(row.get("mode") or spec.mode),
        "timeout_seconds": int(row.get("timeout_seconds") or spec.timeout_seconds),
        "expect_restart": bool(row.get("expect_restart", False)),
        "baseline_prompt": str(row.get("baseline_prompt") or prompt).strip(),
        "candidate_prompt": str(row.get("candidate_prompt") or prompt).strip(),
        "training_tier": _normalize_training_tier(row.get("training_tier")),
        "dataset_ref": {key: row.get(key) for key in ("id", "task_id", "instance_id", "repo", "base_commit") if key in row},
    }
    if "expected" in row:
        case["expected"] = row["expected"]
    if "rubric" in row:
        case["rubric"] = row["rubric"]
    if "dataset_splits" in row:
        case["dataset_splits"] = _normalize_dataset_splits(row["dataset_splits"])
    return case


def _normalize_dataset_splits(value: Any) -> List[str]:
    allowed = {"train", "dev", "observe", "regression", "holdout", "smoke"}
    if value is None:
        return ["train"]
    raw_items = value if isinstance(value, list) else [value]
    splits: List[str] = []
    for raw in raw_items:
        split = str(raw).strip().lower()
        if not split:
            continue
        if split not in allowed:
            raise ValueError(f"未知 dataset split: {raw}")
        if split not in splits:
            splits.append(split)
    return splits or ["train"]


def _normalize_training_tier(value: Any) -> str:
    tier = str(value or "foundation").strip().lower()
    allowed = {"foundation", "coordination", "intelligence"}
    if tier not in allowed:
        raise ValueError(f"未知 training tier: {value}")
    return tier


def _validate_generated_case_provenance(row: Dict[str, Any]) -> Dict[str, Any]:
    provenance = row.get("provenance")
    if not isinstance(provenance, dict):
        raise ValueError("Generated Case 缺少 provenance")
    required = [
        "source_trace_id",
        "source_episode_id",
        "source_harness_gap",
        "generation_reason",
        "creator_version",
        "created_at",
        "allowed_splits",
    ]
    missing = [key for key in required if not provenance.get(key)]
    if missing:
        raise ValueError(f"Generated Case provenance 缺少字段: {', '.join(missing)}")
    allowed_splits = _normalize_dataset_splits(provenance.get("allowed_splits"))
    if "holdout" in allowed_splits:
        raise ValueError("Generated Case provenance 不允许自动进入 holdout")
    provenance["allowed_splits"] = allowed_splits
    return provenance


def _build_generated_case(spec: DatasetSpec, row: Dict[str, Any], index: int) -> Dict[str, Any]:
    provenance = _validate_generated_case_provenance(row)
    splits = _normalize_dataset_splits(row.get("dataset_splits") or provenance.get("allowed_splits"))
    if "holdout" in splits:
        raise ValueError("Generated Case 不能自动进入 holdout")
    disallowed = [split for split in splits if split not in provenance["allowed_splits"]]
    if disallowed:
        raise ValueError(f"Generated Case split 超出 provenance allowed_splits: {', '.join(disallowed)}")
    case = _build_prompt_case(spec, row, index)
    case["dataset_splits"] = splits
    case["provenance"] = provenance
    case["generated"] = True
    return case


def _build_swe_case(spec: DatasetSpec, row: Dict[str, Any], index: int) -> Dict[str, Any]:
    instance_id = _case_id_from_row(row, index)
    problem = str(row.get("problem_statement") or row.get("prompt") or "").strip()
    if not problem:
        raise ValueError("SWE row 缺少 problem_statement")
    repo = str(row.get("repo") or "").strip()
    base_commit = str(row.get("base_commit") or "").strip()
    prompt = (
        "处理 SWE 数据集 case。\n"
        f"instance_id: {instance_id}\n"
        f"repo: {repo or '-'}\n"
        f"base_commit: {base_commit or '-'}\n\n"
        "问题描述:\n"
        f"{problem}\n\n"
        "要求：生成能解决该 issue 的代码修改，并通过对应测试。"
    )
    return {
        "case_id": instance_id,
        "scenario": spec.scenario,
        "mode": spec.mode,
        "timeout_seconds": spec.timeout_seconds,
        "expect_restart": False,
        "baseline_prompt": prompt,
        "candidate_prompt": prompt,
        "training_tier": _normalize_training_tier(row.get("training_tier")),
        "dataset_ref": {
            "dataset": spec.name,
            "instance_id": instance_id,
            "repo": repo,
            "base_commit": base_commit,
        },
        "requires_external_harness": "swe_bench",
    }


def materialize_dataset_bundle(
    dataset_name: str,
    *,
    project_root: Optional[Path] = None,
    limit: Optional[int] = None,
) -> DatasetMaterialization:
    root = (project_root or get_workspace().project_root).resolve()
    spec = get_dataset_spec(dataset_name, project_root=root)
    bundle_path = root / "workspace" / "evaluation" / "bundles" / f"{spec.bundle_name}.json"

    if spec.kind == "supervised_bundle":
        source_bundle = resolve_supervised_bundle_path(spec.bundle_name, project_root=root)
        payload = json.loads(source_bundle.read_text(encoding="utf-8"))
        cases = list(payload.get("cases") or [])
        if limit is not None:
            payload["cases"] = cases[:limit]
        if source_bundle != bundle_path or limit is not None:
            bundle_path.parent.mkdir(parents=True, exist_ok=True)
            bundle_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        elif not bundle_path.exists():
            bundle_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_bundle, bundle_path)
        return DatasetMaterialization(
            dataset_name=spec.name,
            bundle_name=spec.bundle_name,
            bundle_path=str(bundle_path),
            case_count=len(payload.get("cases") or []),
            runnable=spec.runnable,
            adapter_status=spec.adapter_status,
        )

    source = resolve_source_path(spec, root)
    if source is None or not source.exists():
        raise FileNotFoundError(f"数据集源文件不存在: {source or spec.source_path}")

    cases: List[Dict[str, Any]] = []
    for index, row in enumerate(_iter_jsonl(source, limit=limit), start=1):
        if spec.kind == "swe_bench_jsonl":
            cases.append(_build_swe_case(spec, row, index))
        elif spec.kind == "generated_case_jsonl":
            cases.append(_build_generated_case(spec, row, index))
        elif spec.kind == "prompt_jsonl":
            cases.append(_build_prompt_case(spec, row, index))
        else:
            raise ValueError(f"暂不支持的数据集 kind: {spec.kind}")

    bundle = {
        "benchmark": f"dataset::{spec.name}",
        "bundle_name": spec.bundle_name,
        "dataset": {
            "name": spec.name,
            "kind": spec.kind,
            "source_path": str(source),
            "adapter_status": spec.adapter_status,
            "runnable": spec.runnable,
        },
        "default_timeout_seconds": spec.timeout_seconds,
        "cases": cases,
    }
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return DatasetMaterialization(
        dataset_name=spec.name,
        bundle_name=spec.bundle_name,
        bundle_path=str(bundle_path),
        case_count=len(cases),
        runnable=spec.runnable,
        adapter_status=spec.adapter_status,
        source_path=str(source),
    )


__all__ = [
    "DATASET_REGISTRY_PATH",
    "DatasetMaterialization",
    "DatasetSpec",
    "ensure_dataset_registry",
    "get_dataset_spec",
    "list_dataset_status",
    "load_dataset_specs",
    "materialize_dataset_bundle",
    "resolve_source_path",
]
