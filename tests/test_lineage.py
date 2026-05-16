#!/usr/bin/env python3
"""监督进化 lineage 查询测试"""

import json
from pathlib import Path

from core.evaluation.lineage import load_lineage_index, query_lineage_cases, summarize_lineage


def test_load_lineage_index_and_query_cases(tmp_path: Path):
    index_path = tmp_path / "lineage_index.json"
    index_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-15T00:00:00Z",
                "proposal_count": 2,
                "case_count": 2,
                "cases": [
                    {
                        "bundle_name": "bundle_a",
                        "case_id": "probe",
                        "current_baseline_id": "baseline_a",
                        "latest_candidate_id": "candidate_b",
                        "proposal_count": 2,
                        "observation_cycles": 3,
                        "target": {"kind": "bundle_prompt_case"},
                        "chain": [
                            {
                                "proposal_id": "candidate_a",
                                "status": "observing",
                                "decision": "HOLD",
                                "observation_count": 2,
                                "parent_baseline_id": None,
                            },
                            {
                                "proposal_id": "candidate_b",
                                "status": "promoted",
                                "decision": "PROMOTE",
                                "observation_count": 1,
                                "parent_baseline_id": "candidate_a",
                            },
                        ],
                    },
                    {
                        "bundle_name": "bundle_b",
                        "case_id": "other",
                        "current_baseline_id": None,
                        "latest_candidate_id": "candidate_x",
                        "proposal_count": 1,
                        "observation_cycles": 1,
                        "chain": [],
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    index = load_lineage_index(str(index_path))

    assert index.case_count == 2
    assert index.cases[0].bundle_name == "bundle_a"
    assert index.cases[0].chain[1].proposal_id == "candidate_b"

    cases = query_lineage_cases(bundle_name="bundle_a", lineage_index_path=str(index_path))
    assert len(cases) == 1
    assert cases[0].case_id == "probe"
    assert cases[0].observation_cycles == 3

    limited = query_lineage_cases(lineage_index_path=str(index_path), limit=1)
    assert len(limited) == 1

    summary = summarize_lineage(bundle_name="bundle_a", lineage_index_path=str(index_path), limit=1)
    assert summary.bundle_case_count == 1
    assert summary.index_case_count == 2
    assert len(summary.items) == 1
    assert summary.items[0].case_id == "probe"
    assert summary.items[0].chain_preview == "observing[2] -> promoted[1]"
