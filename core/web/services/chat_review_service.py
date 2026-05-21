# -*- coding: utf-8 -*-
"""Web payloads for reviewed chat-dataset candidates."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.evaluation.chat_case_lifecycle import (
    NEGATIVE_DATASET_BUNDLE_NAME,
    NEGATIVE_DATASET_NAME,
    POSITIVE_DATASET_BUNDLE_NAME,
    POSITIVE_DATASET_NAME,
    chat_case_lifecycle_payload,
)
from core.evaluation.chat_dataset_capture import (
    approve_chat_candidate,
    discard_chat_candidate,
    load_candidate_payload,
    record_negative_chat_candidate,
    resolve_chat_dataset_paths,
)
from core.evaluation.chat_review_queue import get_review_item, list_review_items, normalize_review_status

from .i18n import get_web_language, text_for


PROJECT_ROOT = Path(__file__).resolve().parents[3]
PROMPT_PREVIEW_LIMIT = 1200
VALID_DECISIONS = {"positive", "negative", "discard"}


class ChatReviewCandidateNotFoundError(ValueError):
    """Raised when a queued chat review candidate cannot be found."""


class ChatReviewCandidateStateError(RuntimeError):
    """Raised when a queued chat review candidate is not actionable."""


class ChatReviewDecisionValidationError(ValueError):
    """Raised when the submitted review decision payload is invalid."""


def get_chat_review_queue(*, project_root: Path | None = None) -> dict[str, Any]:
    root = (project_root or PROJECT_ROOT).resolve()
    paths = resolve_chat_dataset_paths(project_root=root)
    items = list_review_items(paths.review_queue_path)
    pending_count = sum(1 for item in items if _status(item) == "pending")
    positive_count = sum(1 for item in items if _status(item) == "positive")
    negative_count = sum(1 for item in items if _status(item) == "negative")
    discard_count = sum(1 for item in items if _status(item) == "discard")
    counts_by_status = {
        "pending": pending_count,
        "positive": positive_count,
        "negative": negative_count,
        "discard": discard_count,
    }
    return {
        "datasetName": POSITIVE_DATASET_NAME,
        "bundleName": POSITIVE_DATASET_BUNDLE_NAME,
        "positiveDatasetName": POSITIVE_DATASET_NAME,
        "positiveBundleName": POSITIVE_DATASET_BUNDLE_NAME,
        "positiveDatasetPath": str(paths.approved_jsonl_path),
        "positiveDatasetExists": paths.approved_jsonl_path.exists(),
        "negativeDatasetName": NEGATIVE_DATASET_NAME,
        "negativeBundleName": NEGATIVE_DATASET_BUNDLE_NAME,
        "negativeDatasetPath": str(paths.negative_jsonl_path),
        "negativeDatasetExists": paths.negative_jsonl_path.exists(),
        "discardAuditPath": str(paths.rejected_log_path),
        "approvedDatasetPath": str(paths.approved_jsonl_path),
        "approvedDatasetExists": paths.approved_jsonl_path.exists(),
        "pendingCount": pending_count,
        "positiveCount": positive_count,
        "negativeCount": negative_count,
        "discardCount": discard_count,
        "countsByStatus": counts_by_status,
        "approvedCount": positive_count,
        "rejectedCount": discard_count,
        "lifecycle": chat_case_lifecycle_payload(),
        "items": [_review_item_payload(item) for item in items],
    }


def submit_chat_review_decision(
    candidate_id: str,
    *,
    decision: str,
    reviewer_note: str = "",
    reason_code: str = "",
    error_type: str = "",
    correct_principle: str = "",
    ideal_behavior: str = "",
    project_root: Path | None = None,
) -> dict[str, Any]:
    root = (project_root or PROJECT_ROOT).resolve()
    normalized_decision = str(decision or "").strip().lower()
    if normalized_decision not in VALID_DECISIONS:
        raise ChatReviewDecisionValidationError(
            text_for(
                get_web_language(),
                zh="未知评审结论，只能是正例、负例或丢弃。",
                en="Unknown review decision. Use positive, negative, or discard.",
            )
        )
    if normalized_decision == "negative" and not (reason_code or error_type or correct_principle or ideal_behavior):
        raise ChatReviewDecisionValidationError(
            text_for(
                get_web_language(),
                zh="纳入负例时，至少补充错误类型、原因分类、正确原则或理想做法中的一项。",
                en="Negative examples need at least one learning hint: error type, reason code, correct principle, or ideal behavior.",
            )
        )

    item = _get_pending_candidate(candidate_id, project_root=root)
    payload = load_candidate_payload(str(item.get("raw_excerpt_path") or ""))
    paths = resolve_chat_dataset_paths(project_root=root)

    if normalized_decision == "positive":
        sample = approve_chat_candidate(
            candidate_payload=payload,
            project_root=root,
            reviewer_note=reviewer_note,
        )
        return {
            "candidateId": str(item.get("candidate_id") or "").strip(),
            "status": "positive",
            "datasetName": POSITIVE_DATASET_NAME,
            "bundleName": POSITIVE_DATASET_BUNDLE_NAME,
            "datasetPath": str(paths.approved_jsonl_path),
            "caseId": str(sample.get("case_id") or "").strip(),
            "summary": text_for(
                get_web_language(),
                zh="已纳入正例数据集，后续监督运行可以复用这条多轮协作样本。",
                en="Added to the positive dataset. Future supervised runs can reuse this multi-turn collaboration sample.",
            ),
        }

    if normalized_decision == "negative":
        sample = record_negative_chat_candidate(
            candidate_payload=payload,
            project_root=root,
            reviewer_note=reviewer_note,
            reason_code=reason_code,
            error_type=error_type,
            correct_principle=correct_principle,
            ideal_behavior=ideal_behavior,
        )
        return {
            "candidateId": str(item.get("candidate_id") or "").strip(),
            "status": "negative",
            "datasetName": NEGATIVE_DATASET_NAME,
            "bundleName": NEGATIVE_DATASET_BUNDLE_NAME,
            "datasetPath": str(paths.negative_jsonl_path),
            "caseId": str(sample.get("case_id") or "").strip(),
            "summary": text_for(
                get_web_language(),
                zh="已纳入负例数据集，并记录该样本对应的错误类型与纠正原则。",
                en="Added to the negative dataset with its error type and corrective principle.",
            ),
        }

    discard_chat_candidate(
        candidate_payload=payload,
        project_root=root,
        reviewer_note=reviewer_note,
        reason_code=reason_code,
    )
    return {
        "candidateId": str(item.get("candidate_id") or "").strip(),
        "status": "discard",
        "datasetName": "",
        "bundleName": "",
        "datasetPath": str(paths.rejected_log_path),
        "caseId": "",
        "summary": text_for(
            get_web_language(),
            zh="已丢弃该样本，只保留审计记录，不进入正负例数据集。",
            en="Discarded this sample. It stays only in the audit log and does not enter the positive or negative datasets.",
        ),
    }


def approve_chat_review_candidate(
    candidate_id: str,
    *,
    reviewer_note: str = "",
    project_root: Path | None = None,
) -> dict[str, Any]:
    return submit_chat_review_decision(
        candidate_id,
        decision="positive",
        reviewer_note=reviewer_note,
        project_root=project_root,
    )


def reject_chat_review_candidate(
    candidate_id: str,
    *,
    reviewer_note: str = "",
    project_root: Path | None = None,
) -> dict[str, Any]:
    return submit_chat_review_decision(
        candidate_id,
        decision="discard",
        reviewer_note=reviewer_note,
        project_root=project_root,
    )


def _get_pending_candidate(candidate_id: str, *, project_root: Path) -> dict[str, Any]:
    paths = resolve_chat_dataset_paths(project_root=project_root)
    item = get_review_item(str(candidate_id or "").strip(), paths.review_queue_path)
    if item is None:
        raise ChatReviewCandidateNotFoundError(
            text_for(get_web_language(), zh="未找到该对话候选。", en="Chat review candidate not found.")
        )
    status = _status(item)
    if status != "pending":
        raise ChatReviewCandidateStateError(
            text_for(
                get_web_language(),
                zh="该对话候选已经处理过，刷新后再试。",
                en="This chat review candidate was already handled. Refresh and try again.",
            )
        )
    return item


def _status(item: dict[str, Any]) -> str:
    return normalize_review_status(item.get("status"))


def _review_item_payload(item: dict[str, Any]) -> dict[str, Any]:
    segment = item.get("segment") if isinstance(item.get("segment"), dict) else {}
    sample = item.get("structured_sample_preview") if isinstance(item.get("structured_sample_preview"), dict) else {}
    conversation_turns = []
    for raw_turn in list(segment.get("conversation_turns") or []):
        if not isinstance(raw_turn, dict):
            continue
        conversation_turns.append(
            {
                "turnNumber": int(raw_turn.get("turn_number") or 0),
                "userMessage": str(raw_turn.get("user_message") or "").strip(),
                "assistantMessage": str(raw_turn.get("assistant_message") or "").strip(),
                "toolCalls": [str(name).strip() for name in list(raw_turn.get("tool_calls") or []) if str(name).strip()],
            }
        )
    quality_signals = [str(name).strip() for name in list(item.get("quality_signals") or []) if str(name).strip()]
    prompt_preview = str(sample.get("prompt") or "").strip()
    if len(prompt_preview) > PROMPT_PREVIEW_LIMIT:
        prompt_preview = prompt_preview[: PROMPT_PREVIEW_LIMIT - 3].rstrip() + "..."
    return {
        "candidateId": str(item.get("candidate_id") or "").strip(),
        "status": _status(item),
        "sessionId": str(item.get("session_id") or "").strip(),
        "topicSummary": str(item.get("topic_summary") or "").strip(),
        "startTurn": int(item.get("start_turn") or 0),
        "endTurn": int(item.get("end_turn") or 0),
        "turnCount": int(item.get("turn_count") or len(conversation_turns)),
        "qualitySignals": quality_signals,
        "sourceLogPath": str(item.get("source_log_path") or "").strip(),
        "rawExcerptPath": str(item.get("raw_excerpt_path") or "").strip(),
        "reviewerNote": str(item.get("reviewer_note") or "").strip(),
        "reviewedAt": str(item.get("reviewed_at") or "").strip(),
        "conversationTurns": conversation_turns,
        "structuredSample": {
            "caseId": str(sample.get("case_id") or "").strip(),
            "mode": str(sample.get("mode") or "").strip(),
            "scenario": str(sample.get("scenario") or "").strip(),
            "trainingTier": str(sample.get("training_tier") or "").strip(),
            "promptSeed": str(sample.get("prompt_seed") or "").strip(),
            "promptPreview": prompt_preview,
        },
        "reviewProfile": _build_review_profile(
            item=item,
            conversation_turns=conversation_turns,
            quality_signals=quality_signals,
        ),
        "reviewDecision": {
            "reasonCode": str(item.get("reason_code") or "").strip(),
            "errorType": str(item.get("error_type") or "").strip(),
            "correctPrinciple": str(item.get("correct_principle") or "").strip(),
            "idealBehavior": str(item.get("ideal_behavior") or "").strip(),
        },
    }


def _build_review_profile(
    *,
    item: dict[str, Any],
    conversation_turns: list[dict[str, Any]],
    quality_signals: list[str],
) -> dict[str, Any]:
    signal_set = {signal.strip().lower() for signal in quality_signals if signal.strip()}
    turn_count = int(item.get("turn_count") or len(conversation_turns))
    has_tool = "tool_call" in signal_set
    has_analysis = "analysis" in signal_set
    has_conclusion = "conclusion" in signal_set
    has_next_action = "next_action" in signal_set
    has_delegation = "delegation" in signal_set

    positive_signals: list[str] = []
    negative_signals: list[str] = []

    if has_tool:
        positive_signals.append(
            text_for(get_web_language(), zh="有真实工具链参与，可学习何时读取、搜索或验证。", en="Uses real tools, so it can teach when to read, search, or verify.")
        )
    if has_analysis:
        positive_signals.append(
            text_for(get_web_language(), zh="显式展示分析过程，不只是给结论。", en="Shows explicit analysis instead of only dropping a conclusion.")
        )
    if has_conclusion:
        positive_signals.append(
            text_for(get_web_language(), zh="能明确收束结论，适合作为完成态示例。", en="Closes with a concrete conclusion, which is useful as a completion example.")
        )
    if has_next_action:
        positive_signals.append(
            text_for(get_web_language(), zh="给出了下一步建议，具备可执行性。", en="Includes a next action, which makes it operational.")
        )
    if has_delegation:
        positive_signals.append(
            text_for(get_web_language(), zh="包含 delegation 语境，可沉淀协作经验。", en="Contains delegation context and can preserve collaboration habits.")
        )
    if turn_count >= 3:
        positive_signals.append(
            text_for(get_web_language(), zh="至少包含三轮上下文，能体现多轮承接。", en="Includes at least three turns and captures multi-turn continuity.")
        )

    if not has_tool:
        negative_signals.append(
            text_for(get_web_language(), zh="没有真实工具证据，容易把猜测包装成结论。", en="There is no tool evidence, so it may teach guessing instead of grounded work.")
        )
    if not has_analysis:
        negative_signals.append(
            text_for(get_web_language(), zh="缺少清晰分析链路，容易让 agent 学到跳步回答。", en="The analysis chain is thin, so it may teach the agent to skip reasoning.")
        )
    if not has_conclusion and not has_next_action:
        negative_signals.append(
            text_for(get_web_language(), zh="没有收口或下一步，学习价值偏弱。", en="There is no closure or next action, so the learning value is weak.")
        )
    if turn_count <= 2:
        negative_signals.append(
            text_for(get_web_language(), zh="轮次偏短，更像片段而不是稳定工作流。", en="The excerpt is very short, so it behaves more like a fragment than a stable workflow.")
        )

    suggestion = "discard"
    suggestion_reason = text_for(
        get_web_language(),
        zh="这条样本更适合先丢弃，因为有效工作信号偏弱。",
        en="This sample is better discarded first because the working signals are too weak.",
    )
    learning_focus = text_for(
        get_web_language(),
        zh="重点看它为什么不足以成为可复用经验。",
        en="Focus on why it is not strong enough to become reusable experience.",
    )

    if len(positive_signals) >= 4 and len(negative_signals) <= 2:
        suggestion = "positive"
        suggestion_reason = text_for(
            get_web_language(),
            zh="这条样本具备较完整的任务推进、分析与收束信号，适合作为正例。",
            en="This sample carries a complete task progression, analysis, and closure signal, so it fits the positive dataset.",
        )
        learning_focus = text_for(
            get_web_language(),
            zh="重点学习它如何在多轮上下文里推进任务并留下可执行下一步。",
            en="Learn how it advances a task through multi-turn context and leaves an actionable next step.",
        )
    elif turn_count >= 3 and len(negative_signals) >= 2:
        suggestion = "negative"
        suggestion_reason = text_for(
            get_web_language(),
            zh="这条样本有明确上下文，但同时暴露出可命名的坏模式，适合作为负例。",
            en="This sample has enough context but also exposes named bad patterns, so it fits the negative dataset.",
        )
        learning_focus = text_for(
            get_web_language(),
            zh="重点把坏模式翻译成“别这样做”的经验，而不是简单丢弃。",
            en="Turn the bad pattern into a concrete 'do not do this' lesson instead of merely discarding it.",
        )

    evidence_turn_numbers = [turn.get("turnNumber") for turn in conversation_turns if int(turn.get("turnNumber") or 0) > 0][:4]
    if len(evidence_turn_numbers) < 2 and conversation_turns:
        evidence_turn_numbers = [conversation_turns[0].get("turnNumber", 0)]

    return {
        "suggestedDecision": suggestion,
        "suggestedReason": suggestion_reason,
        "learningFocus": learning_focus,
        "taskClarity": {
            "level": "high" if turn_count >= 3 else "medium" if turn_count == 2 else "low",
            "note": text_for(
                get_web_language(),
                zh="轮次越完整，越能看出任务目标是否稳定。",
                en="More turns make it easier to judge whether the task stays stable.",
            ),
        },
        "goalStability": {
            "level": "high" if has_conclusion or has_next_action else "medium" if has_analysis else "low",
            "note": text_for(
                get_web_language(),
                zh="看用户目标是否一路延续到结论或下一步。",
                en="Check whether the user goal survives through to the conclusion or next step.",
            ),
        },
        "assistantLearningValue": {
            "level": "high" if len(positive_signals) >= 4 else "medium" if len(positive_signals) >= 2 else "low",
            "note": text_for(
                get_web_language(),
                zh="这项衡量 assistant 响应本身是否值得重复学习。",
                en="This measures whether the assistant response is worth repeating in training.",
            ),
        },
        "antiPatternRisk": {
            "level": "high" if len(negative_signals) >= 3 else "medium" if len(negative_signals) >= 1 else "low",
            "note": text_for(
                get_web_language(),
                zh="这项衡量样本是否会把坏习惯带进训练集。",
                en="This measures how likely the sample is to inject bad habits into the dataset.",
            ),
        },
        "positiveSignals": positive_signals,
        "negativeSignals": negative_signals,
        "evidenceTurnNumbers": evidence_turn_numbers,
    }


__all__ = [
    "ChatReviewCandidateNotFoundError",
    "ChatReviewCandidateStateError",
    "ChatReviewDecisionValidationError",
    "approve_chat_review_candidate",
    "get_chat_review_queue",
    "reject_chat_review_candidate",
    "submit_chat_review_decision",
]
