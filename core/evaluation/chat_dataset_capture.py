# -*- coding: utf-8 -*-
"""Chat 对话候选采样与结构化数据构建。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Sequence

from config import AppConfig, get_config

from .chat_review_queue import append_review_decision, append_review_queue_candidate
from .chat_segmenter import (
    ChatSegment,
    ChatTurnRecord,
    build_latest_task_segment,
    has_analysis_signal,
    has_conclusion_signal,
    has_next_action_signal,
    is_pure_chitchat_segment,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class ChatDatasetPaths:
    candidate_dir: Path
    review_queue_path: Path
    approved_raw_dir: Path
    approved_jsonl_path: Path
    negative_raw_dir: Path
    negative_jsonl_path: Path
    rejected_log_path: Path


@dataclass(frozen=True)
class ChatDatasetCandidate:
    candidate_id: str
    session_id: str
    mode: str
    start_turn: int
    end_turn: int
    turn_count: int
    topic_summary: str
    quality_signals: List[str]
    source_log_path: str
    raw_excerpt_path: str
    segment: Dict[str, Any]
    structured_sample_preview: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def resolve_chat_dataset_paths(
    *,
    project_root: Path,
    config: AppConfig | None = None,
) -> ChatDatasetPaths:
    cfg = config or get_config()
    capture = cfg.evolution.chat_dataset

    def _resolve(raw: str) -> Path:
        path = Path(str(raw or "").strip())
        if path.is_absolute():
            return path.resolve()
        return (project_root / path).resolve()

    return ChatDatasetPaths(
        candidate_dir=_resolve(capture.candidate_dir),
        review_queue_path=_resolve(capture.review_queue_path),
        approved_raw_dir=(approved_raw_dir := _resolve(capture.approved_raw_dir)),
        approved_jsonl_path=(approved_jsonl_path := _resolve(capture.approved_jsonl_path)),
        negative_raw_dir=approved_raw_dir.parent.parent / "chat_negative" / "raw",
        negative_jsonl_path=approved_jsonl_path.parent / "chat_negative_multiturn.jsonl",
        rejected_log_path=_resolve(capture.rejected_log_path),
    )


class ChatDatasetCaptureService:
    """根据 chat 对话轮次静默采样候选片段。"""

    def __init__(self, *, project_root: Path, config: AppConfig | None = None) -> None:
        self.config = config or get_config()
        self.paths = resolve_chat_dataset_paths(project_root=project_root, config=self.config)

    def should_capture_mode(self, mode: str) -> bool:
        capture = self.config.evolution.chat_dataset
        normalized = str(mode or "").strip().lower()
        return bool(capture.enabled and capture.auto_capture and normalized in set(capture.source_modes or []))

    def capture_candidate(
        self,
        *,
        mode: str,
        session_id: str,
        source_log_path: str,
        turns: Sequence[ChatTurnRecord],
    ) -> ChatDatasetCandidate | None:
        capture = self.config.evolution.chat_dataset
        if not self.should_capture_mode(mode):
            return None

        segment = build_latest_task_segment(
            turns,
            session_id=session_id,
            mode=mode,
            min_turns=capture.min_turns,
            max_turns=capture.max_turns,
        )
        if segment is None:
            return None

        quality_signals = collect_quality_signals(segment)
        exclusion_reasons = collect_exclusion_reasons(
            segment,
            exclude_pure_chitchat=bool(capture.exclude_pure_chitchat),
            require_tool_call_or_analysis_or_conclusion=bool(capture.require_tool_call_or_analysis_or_conclusion),
        )
        if exclusion_reasons:
            return None

        raw_path = self.paths.candidate_dir / f"{segment.segment_id}.json"
        if raw_path.exists():
            return None

        structured_preview = build_structured_chat_sample(
            segment=segment,
            source_log_path=source_log_path,
            raw_excerpt_path=str(raw_path),
            approval={
                "status": "pending",
                "approved_at": "",
                "reviewer_note": "",
            },
        )
        candidate = ChatDatasetCandidate(
            candidate_id=segment.segment_id,
            session_id=session_id,
            mode=str(mode or "chat"),
            start_turn=segment.start_turn,
            end_turn=segment.end_turn,
            turn_count=segment.turn_count,
            topic_summary=segment.topic_summary,
            quality_signals=quality_signals,
            source_log_path=source_log_path,
            raw_excerpt_path=str(raw_path),
            segment=segment.to_dict(),
            structured_sample_preview=structured_preview,
        )
        self.paths.candidate_dir.mkdir(parents=True, exist_ok=True)
        raw_path.write_text(json.dumps(candidate.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        append_review_queue_candidate(candidate.to_dict(), self.paths.review_queue_path)
        return candidate


def collect_quality_signals(segment: ChatSegment) -> List[str]:
    signals: List[str] = []
    if segment.tool_calls:
        signals.append("tool_call")
    if segment.has_delegation:
        signals.append("delegation")
    if any(has_analysis_signal(text) for text in segment.assistant_messages):
        signals.append("analysis")
    if segment.has_explicit_conclusion or any(has_conclusion_signal(text) for text in segment.assistant_messages):
        signals.append("conclusion")
    if segment.has_next_action or any(has_next_action_signal(text) for text in segment.assistant_messages):
        signals.append("next_action")
    if segment.turn_count >= 3:
        signals.append("multi_turn")
    deduped: List[str] = []
    for item in signals:
        if item not in deduped:
            deduped.append(item)
    return deduped


def collect_exclusion_reasons(
    segment: ChatSegment,
    *,
    exclude_pure_chitchat: bool,
    require_tool_call_or_analysis_or_conclusion: bool,
) -> List[str]:
    reasons: List[str] = []
    if exclude_pure_chitchat and is_pure_chitchat_segment(segment):
        reasons.append("pure_chitchat")
    if require_tool_call_or_analysis_or_conclusion:
        has_required = bool(
            segment.tool_calls
            or segment.has_explicit_conclusion
            or any(has_analysis_signal(text) for text in segment.assistant_messages)
            or any(has_conclusion_signal(text) for text in segment.assistant_messages)
        )
        if not has_required:
            reasons.append("missing_required_signal")
    return reasons


def render_multiturn_prompt(segment: ChatSegment) -> str:
    lines = [
        "你正在处理一个来自真实对话协作的多轮上下文 case。",
        "请继承既有风格、上下文和任务连续性，不要把下面的多轮内容当成一次性单轮问答。",
        "",
        f"session_id: {segment.session_id}",
        f"turn_range: {segment.start_turn}-{segment.end_turn}",
        f"topic: {segment.topic_summary}",
        "",
        "对话上下文：",
    ]
    for item in segment.conversation_turns:
        turn_no = int(item.get("turn_number") or 0)
        user_message = str(item.get("user_message") or "").strip()
        assistant_message = str(item.get("assistant_message") or "").strip()
        lines.append(f"[Turn {turn_no}] 用户: {user_message}")
        if item.get("tool_calls"):
            lines.append(f"[Turn {turn_no}] 工具: {', '.join(item.get('tool_calls') or [])}")
        lines.append(f"[Turn {turn_no}] 助手: {assistant_message}")
        lines.append("")
    lines.extend(
        [
            "任务要求：",
            "- 继续保持该对话中的风格与工作方式。",
            "- 在已有上下文上延续分析、工具使用和结论收束能力。",
            "- 回答时优先体现上下文承接、任务推进和下一步建议。",
        ]
    )
    return "\n".join(lines).strip()


def build_structured_chat_sample(
    *,
    segment: ChatSegment,
    source_log_path: str,
    raw_excerpt_path: str,
    approval: Dict[str, Any],
    review: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    quality_signals = collect_quality_signals(segment)
    sample = {
        "case_id": segment.segment_id,
        "mode": "multiturn_chat",
        "scenario": "conversation_collaboration",
        "prompt_seed": segment.user_messages[0] if segment.user_messages else "",
        "prompt": render_multiturn_prompt(segment),
        "conversation_turns": list(segment.conversation_turns),
        "expected_effect": "在多轮上下文中延续风格、任务推进、分析和收束能力。",
        "quality_signals": quality_signals,
        "training_tier": "coordination",
        "dataset_ref": {
            "session_id": segment.session_id,
            "mode": segment.mode,
            "source_log_path": source_log_path,
            "raw_excerpt_path": raw_excerpt_path,
            "turn_range": [segment.start_turn, segment.end_turn],
        },
        "approval": approval,
    }
    if review:
        sample["review"] = review
    return sample


def load_candidate_payload(raw_excerpt_path: str | Path) -> Dict[str, Any]:
    path = Path(raw_excerpt_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"候选文件格式错误: {path}")
    return payload


def _review_payload(
    *,
    decision: str,
    reviewed_at: str,
    reviewer_note: str,
    reason_code: str = "",
    error_type: str = "",
    correct_principle: str = "",
    ideal_behavior: str = "",
) -> Dict[str, Any]:
    return {
        "decision": str(decision or "").strip().lower(),
        "reviewed_at": reviewed_at,
        "reviewer_note": reviewer_note or "",
        "reason_code": reason_code or "",
        "error_type": error_type or "",
        "correct_principle": correct_principle or "",
        "ideal_behavior": ideal_behavior or "",
    }


def approve_chat_candidate(
    *,
    candidate_payload: Dict[str, Any],
    project_root: Path,
    reviewer_note: str = "",
    config: AppConfig | None = None,
) -> Dict[str, Any]:
    cfg = config or get_config()
    paths = resolve_chat_dataset_paths(project_root=project_root, config=cfg)
    candidate_id = str(candidate_payload.get("candidate_id") or "").strip()
    if not candidate_id:
        raise ValueError("candidate_payload 缺少 candidate_id")

    segment_payload = candidate_payload.get("segment")
    if not isinstance(segment_payload, dict):
        raise ValueError("candidate_payload 缺少 segment")
    segment = ChatSegment(**segment_payload)
    reviewed_at = _now_iso()
    approved_raw_path = paths.approved_raw_dir / f"{candidate_id}.json"
    approved_raw_path.parent.mkdir(parents=True, exist_ok=True)
    approved_raw_path.write_text(
        json.dumps(
            {
                **candidate_payload,
                "review": _review_payload(
                    decision="positive",
                    reviewed_at=reviewed_at,
                    reviewer_note=reviewer_note,
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    sample = build_structured_chat_sample(
        segment=segment,
        source_log_path=str(candidate_payload.get("source_log_path") or ""),
        raw_excerpt_path=str(approved_raw_path),
        approval={
            "status": "positive",
            "reviewed_at": reviewed_at,
            "reviewer_note": reviewer_note or "",
        },
        review=_review_payload(
            decision="positive",
            reviewed_at=reviewed_at,
            reviewer_note=reviewer_note,
        ),
    )
    paths.approved_jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    with paths.approved_jsonl_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(sample, ensure_ascii=False) + "\n")
    append_review_decision(
        candidate_id,
        status="positive",
        reviewer_note=reviewer_note,
        queue_path=paths.review_queue_path,
        extra={
            "approved_raw_path": str(approved_raw_path),
            "approved_jsonl_path": str(paths.approved_jsonl_path),
        },
    )
    return sample


def record_negative_chat_candidate(
    *,
    candidate_payload: Dict[str, Any],
    project_root: Path,
    reviewer_note: str = "",
    reason_code: str = "",
    error_type: str = "",
    correct_principle: str = "",
    ideal_behavior: str = "",
    config: AppConfig | None = None,
) -> Dict[str, Any]:
    cfg = config or get_config()
    paths = resolve_chat_dataset_paths(project_root=project_root, config=cfg)
    candidate_id = str(candidate_payload.get("candidate_id") or "").strip()
    if not candidate_id:
        raise ValueError("candidate_payload 缺少 candidate_id")

    segment_payload = candidate_payload.get("segment")
    if not isinstance(segment_payload, dict):
        raise ValueError("candidate_payload 缺少 segment")
    segment = ChatSegment(**segment_payload)
    reviewed_at = _now_iso()
    negative_raw_path = paths.negative_raw_dir / f"{candidate_id}.json"
    negative_raw_path.parent.mkdir(parents=True, exist_ok=True)
    negative_raw_path.write_text(
        json.dumps(
            {
                **candidate_payload,
                "review": _review_payload(
                    decision="negative",
                    reviewed_at=reviewed_at,
                    reviewer_note=reviewer_note,
                    reason_code=reason_code,
                    error_type=error_type,
                    correct_principle=correct_principle,
                    ideal_behavior=ideal_behavior,
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    sample = build_structured_chat_sample(
        segment=segment,
        source_log_path=str(candidate_payload.get("source_log_path") or ""),
        raw_excerpt_path=str(negative_raw_path),
        approval={
            "status": "negative",
            "reviewed_at": reviewed_at,
            "reviewer_note": reviewer_note or "",
        },
        review=_review_payload(
            decision="negative",
            reviewed_at=reviewed_at,
            reviewer_note=reviewer_note,
            reason_code=reason_code,
            error_type=error_type,
            correct_principle=correct_principle,
            ideal_behavior=ideal_behavior,
        ),
    )
    paths.negative_jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    with paths.negative_jsonl_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(sample, ensure_ascii=False) + "\n")
    append_review_decision(
        candidate_id,
        status="negative",
        reviewer_note=reviewer_note,
        queue_path=paths.review_queue_path,
        extra={
            "negative_raw_path": str(negative_raw_path),
            "negative_jsonl_path": str(paths.negative_jsonl_path),
            "reason_code": reason_code or "",
            "error_type": error_type or "",
            "correct_principle": correct_principle or "",
            "ideal_behavior": ideal_behavior or "",
        },
    )
    return sample


def discard_chat_candidate(
    *,
    candidate_payload: Dict[str, Any],
    project_root: Path,
    reviewer_note: str = "",
    reason_code: str = "",
    config: AppConfig | None = None,
) -> Dict[str, Any]:
    cfg = config or get_config()
    paths = resolve_chat_dataset_paths(project_root=project_root, config=cfg)
    candidate_id = str(candidate_payload.get("candidate_id") or "").strip()
    if not candidate_id:
        raise ValueError("candidate_payload 缺少 candidate_id")
    discarded_at = _now_iso()
    payload = {
        "candidate_id": candidate_id,
        "timestamp": discarded_at,
        "status": "discard",
        "reason_code": reason_code or "",
        "reviewer_note": reviewer_note or "",
        "topic_summary": candidate_payload.get("topic_summary") or "",
        "raw_excerpt_path": candidate_payload.get("raw_excerpt_path") or "",
    }
    paths.rejected_log_path.parent.mkdir(parents=True, exist_ok=True)
    with paths.rejected_log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
    append_review_decision(
        candidate_id,
        status="discard",
        reviewer_note=reviewer_note,
        queue_path=paths.review_queue_path,
        extra={
            "rejected_log_path": str(paths.rejected_log_path),
            "reason_code": reason_code or "",
        },
    )
    return payload


def reject_chat_candidate(
    *,
    candidate_payload: Dict[str, Any],
    project_root: Path,
    reviewer_note: str = "",
    config: AppConfig | None = None,
) -> Dict[str, Any]:
    return discard_chat_candidate(
        candidate_payload=candidate_payload,
        project_root=project_root,
        reviewer_note=reviewer_note,
        config=config,
    )


def format_candidate_preview(candidate_payload: Dict[str, Any], *, max_turns: int = 6) -> str:
    lines = [
        f"candidate: {candidate_payload.get('candidate_id')}",
        f"topic: {candidate_payload.get('topic_summary') or '-'}",
        f"turns: {candidate_payload.get('start_turn')} - {candidate_payload.get('end_turn')}",
        f"signals: {', '.join(candidate_payload.get('quality_signals') or []) or '-'}",
        f"source_log: {candidate_payload.get('source_log_path') or '-'}",
        "",
        "对话摘录：",
    ]
    segment = candidate_payload.get("segment") if isinstance(candidate_payload.get("segment"), dict) else {}
    turns = list(segment.get("conversation_turns") or [])[:max_turns]
    for item in turns:
        lines.append(f"[Turn {item.get('turn_number')}] 用户: {str(item.get('user_message') or '').strip()}")
        if item.get("tool_calls"):
            lines.append(f"[Turn {item.get('turn_number')}] 工具: {', '.join(item.get('tool_calls') or [])}")
        lines.append(f"[Turn {item.get('turn_number')}] 助手: {str(item.get('assistant_message') or '').strip()}")
        lines.append("")
    remaining = max(0, len(segment.get("conversation_turns") or []) - len(turns))
    if remaining:
        lines.append(f"... 还有 {remaining} 轮")
    return "\n".join(lines).strip()


def format_structured_sample_preview(sample: Dict[str, Any]) -> str:
    lines = [
        f"case_id: {sample.get('case_id')}",
        f"mode: {sample.get('mode')}",
        f"scenario: {sample.get('scenario')}",
        f"training_tier: {sample.get('training_tier')}",
        f"quality_signals: {', '.join(sample.get('quality_signals') or []) or '-'}",
        f"prompt_seed: {sample.get('prompt_seed') or '-'}",
        f"dataset_ref: {json.dumps(sample.get('dataset_ref') or {}, ensure_ascii=False)}",
        "",
        "prompt preview:",
        str(sample.get("prompt") or "")[:1200],
    ]
    return "\n".join(lines).strip()


__all__ = [
    "ChatDatasetCandidate",
    "ChatDatasetCaptureService",
    "ChatDatasetPaths",
    "approve_chat_candidate",
    "build_structured_chat_sample",
    "collect_exclusion_reasons",
    "collect_quality_signals",
    "discard_chat_candidate",
    "format_candidate_preview",
    "format_structured_sample_preview",
    "load_candidate_payload",
    "record_negative_chat_candidate",
    "reject_chat_candidate",
    "render_multiturn_prompt",
    "resolve_chat_dataset_paths",
]
