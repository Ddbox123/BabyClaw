#!/usr/bin/env python3
"""chat 数据采样与审核回归测试。"""

import json
from pathlib import Path

from config import AppConfig
from core.evaluation.chat_dataset_capture import (
    ChatDatasetCaptureService,
    approve_chat_candidate,
    discard_chat_candidate,
    load_candidate_payload,
    record_negative_chat_candidate,
    reject_chat_candidate,
    resolve_chat_dataset_paths,
)
from core.evaluation.chat_review_queue import get_review_item, list_review_items
from core.evaluation.chat_segmenter import ChatTurnRecord
from core.evaluation.dataset_registry import ensure_dataset_registry, materialize_dataset_bundle


def test_chat_candidate_capture_writes_raw_and_queue(tmp_path: Path):
    config = AppConfig()
    service = ChatDatasetCaptureService(project_root=tmp_path, config=config)

    candidate = service.capture_candidate(
        mode="chat",
        session_id="chat_session_demo",
        source_log_path=str(tmp_path / "log_info" / "conversation_demo.jsonl"),
        turns=[
            ChatTurnRecord(
                turn_number=1,
                user_message="帮我排查一下为什么 lint 一直失败",
                assistant_message="先看失败输出和相关文件，再归因。",
                tool_calls=["read_file_tool"],
                tool_call_count=1,
            ),
            ChatTurnRecord(
                turn_number=2,
                user_message="继续",
                assistant_message="结论：是路径大小写不一致。下一步建议修正导入并复测。",
                tool_calls=["grep_search_tool", "python_lint_tool"],
                tool_call_count=2,
                had_explicit_conclusion=True,
                had_next_action=True,
            ),
        ],
    )

    assert candidate is not None
    paths = resolve_chat_dataset_paths(project_root=tmp_path, config=config)
    assert Path(candidate.raw_excerpt_path).exists()
    queue_items = list_review_items(paths.review_queue_path)
    assert queue_items[0]["candidate_id"] == candidate.candidate_id
    assert queue_items[0]["status"] == "pending"
    payload = load_candidate_payload(candidate.raw_excerpt_path)
    assert payload["structured_sample_preview"]["mode"] == "multiturn_chat"


def test_chat_candidate_decisions_update_queue_and_datasets(tmp_path: Path):
    config = AppConfig()
    service = ChatDatasetCaptureService(project_root=tmp_path, config=config)
    candidate = service.capture_candidate(
        mode="chat",
        session_id="chat_session_demo",
        source_log_path=str(tmp_path / "log_info" / "conversation_demo.jsonl"),
        turns=[
            ChatTurnRecord(
                turn_number=1,
                user_message="请帮我分析这段多轮上下文",
                assistant_message="我先梳理上下文，再给结论。",
                tool_calls=["read_file_tool"],
                tool_call_count=1,
            ),
            ChatTurnRecord(
                turn_number=2,
                user_message="好",
                assistant_message="结论：需要保留上下文并给出下一步建议。",
                tool_calls=[],
                tool_call_count=0,
                had_explicit_conclusion=True,
                had_next_action=True,
            ),
        ],
    )
    assert candidate is not None

    payload = load_candidate_payload(candidate.raw_excerpt_path)
    approved = approve_chat_candidate(
        candidate_payload=payload,
        project_root=tmp_path,
        reviewer_note="保留这个多轮承接样本",
        config=config,
    )
    paths = resolve_chat_dataset_paths(project_root=tmp_path, config=config)

    assert Path(paths.approved_jsonl_path).exists()
    approved_rows = [json.loads(line) for line in paths.approved_jsonl_path.read_text(encoding="utf-8").splitlines()]
    assert approved_rows[0]["case_id"] == candidate.candidate_id
    assert approved["approval"]["status"] == "positive"
    review_item = get_review_item(candidate.candidate_id, paths.review_queue_path)
    assert review_item is not None
    assert review_item["status"] == "positive"

    ensure_dataset_registry(tmp_path)
    bundle = materialize_dataset_bundle("chat_reviewed_multiturn", project_root=tmp_path)
    bundle_payload = json.loads(Path(bundle.bundle_path).read_text(encoding="utf-8"))
    assert bundle.case_count == 1
    assert bundle_payload["cases"][0]["scenario"] == "conversation_collaboration"
    assert "多轮上下文" in bundle_payload["cases"][0]["baseline_prompt"]

    negative = record_negative_chat_candidate(
        candidate_payload=payload,
        project_root=tmp_path,
        reviewer_note="保留成反例，强调不要跳过分析链路",
        reason_code="missing_analysis",
        error_type="ungrounded_inference",
        correct_principle="先给证据，再形成结论",
        ideal_behavior="先检查工具输出和日志，再总结",
        config=config,
    )
    assert negative["approval"]["status"] == "negative"
    assert paths.negative_jsonl_path.exists()

    discarded = discard_chat_candidate(
        candidate_payload=payload,
        project_root=tmp_path,
        reviewer_note="信息太薄，直接丢弃",
        reason_code="thin_signal",
        config=config,
    )
    assert discarded["candidate_id"] == candidate.candidate_id
    assert Path(paths.rejected_log_path).exists()

    legacy_discard = reject_chat_candidate(
        candidate_payload=payload,
        project_root=tmp_path,
        reviewer_note="兼容旧 reject API",
        config=config,
    )
    assert legacy_discard["status"] == "discard"
