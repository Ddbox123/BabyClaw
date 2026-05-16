# -*- coding: utf-8 -*-
"""监督进化 proposal lineage 查询接口。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import get_config
from core.infrastructure.workspace_manager import get_workspace


@dataclass
class LineageChainNode:
    proposal_id: str
    status: str
    decision: str
    observation_count: int = 0
    parent_baseline_id: Optional[str] = None
    first_seen_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class LineageCaseRecord:
    bundle_name: str
    case_id: str
    target: Dict[str, Any] = field(default_factory=dict)
    current_baseline_id: Optional[str] = None
    latest_candidate_id: Optional[str] = None
    proposal_count: int = 0
    observation_cycles: int = 0
    chain: List[LineageChainNode] = field(default_factory=list)


@dataclass
class LineageIndex:
    generated_at: Optional[str] = None
    proposal_count: int = 0
    case_count: int = 0
    cases: List[LineageCaseRecord] = field(default_factory=list)
    path: Optional[str] = None


@dataclass
class LineageSummaryItem:
    case_id: str
    current_baseline_id: Optional[str] = None
    latest_candidate_id: Optional[str] = None
    chain_preview: str = "none"


@dataclass
class LineageSummary:
    bundle_name: Optional[str] = None
    bundle_case_count: int = 0
    index_case_count: int = 0
    items: List[LineageSummaryItem] = field(default_factory=list)
    path: Optional[str] = None


def resolve_lineage_index_path(*, project_root: Optional[Path] = None) -> Path:
    root = (project_root or get_workspace().project_root).resolve()
    proposals_dir = Path(get_config().evolution.proposals_dir)
    if not proposals_dir.is_absolute():
        proposals_dir = (root / proposals_dir).resolve()
    return proposals_dir / "lineage_index.json"


def load_lineage_index(
    lineage_index_path: Optional[str] = None,
    *,
    project_root: Optional[Path] = None,
) -> LineageIndex:
    path = Path(lineage_index_path).resolve() if lineage_index_path else resolve_lineage_index_path(project_root=project_root)
    if not path.exists():
        return LineageIndex(path=str(path))
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return LineageIndex(path=str(path))
    case_records: List[LineageCaseRecord] = []
    for item in payload.get("cases") or []:
        chain = [
            LineageChainNode(
                proposal_id=str(node.get("proposal_id") or ""),
                status=str(node.get("status") or ""),
                decision=str(node.get("decision") or ""),
                observation_count=int(node.get("observation_count") or 0),
                parent_baseline_id=node.get("parent_baseline_id"),
                first_seen_at=node.get("first_seen_at"),
                updated_at=node.get("updated_at"),
            )
            for node in (item.get("chain") or [])
        ]
        case_records.append(
            LineageCaseRecord(
                bundle_name=str(item.get("bundle_name") or ""),
                case_id=str(item.get("case_id") or ""),
                target=item.get("target") or {},
                current_baseline_id=item.get("current_baseline_id"),
                latest_candidate_id=item.get("latest_candidate_id"),
                proposal_count=int(item.get("proposal_count") or 0),
                observation_cycles=int(item.get("observation_cycles") or 0),
                chain=chain,
            )
        )
    return LineageIndex(
        generated_at=payload.get("generated_at"),
        proposal_count=int(payload.get("proposal_count") or 0),
        case_count=int(payload.get("case_count") or 0),
        cases=case_records,
        path=str(path),
    )


def query_lineage_cases(
    *,
    bundle_name: Optional[str] = None,
    case_id: Optional[str] = None,
    limit: Optional[int] = None,
    lineage_index_path: Optional[str] = None,
    project_root: Optional[Path] = None,
) -> List[LineageCaseRecord]:
    index = load_lineage_index(lineage_index_path, project_root=project_root)
    cases = index.cases
    if bundle_name:
        cases = [item for item in cases if item.bundle_name == bundle_name]
    if case_id:
        cases = [item for item in cases if item.case_id == case_id]
    if limit is not None:
        cases = cases[: max(0, int(limit))]
    return cases


def summarize_lineage(
    *,
    bundle_name: Optional[str] = None,
    limit: int = 3,
    chain_tail: int = 3,
    lineage_index_path: Optional[str] = None,
    project_root: Optional[Path] = None,
) -> LineageSummary:
    index = load_lineage_index(lineage_index_path, project_root=project_root)
    filtered = query_lineage_cases(
        bundle_name=bundle_name,
        lineage_index_path=lineage_index_path,
        project_root=project_root,
    )
    selected = filtered[: max(0, int(limit))]
    if not selected and not bundle_name:
        selected = index.cases[: max(0, int(limit))]
    items: List[LineageSummaryItem] = []
    for case in selected:
        tail = (case.chain or [])[-max(0, int(chain_tail)) :]
        chain_preview = " -> ".join(
            f"{node.status or '?'}[{node.observation_count}]"
            for node in tail
        ) or "none"
        items.append(
            LineageSummaryItem(
                case_id=case.case_id,
                current_baseline_id=case.current_baseline_id,
                latest_candidate_id=case.latest_candidate_id,
                chain_preview=chain_preview,
            )
        )
    return LineageSummary(
        bundle_name=bundle_name,
        bundle_case_count=len(filtered) if bundle_name else index.case_count,
        index_case_count=index.case_count,
        items=items,
        path=index.path,
    )


__all__ = [
    "LineageCaseRecord",
    "LineageChainNode",
    "LineageIndex",
    "LineageSummary",
    "LineageSummaryItem",
    "load_lineage_index",
    "query_lineage_cases",
    "resolve_lineage_index_path",
    "summarize_lineage",
]
