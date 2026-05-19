# -*- coding: utf-8 -*-
"""Chat 对话分段与结构化摘要。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Sequence


@dataclass(frozen=True)
class ChatTurnRecord:
    turn_number: int
    user_message: str
    assistant_message: str
    tool_calls: List[str] = field(default_factory=list)
    tool_call_count: int = 0
    had_delegation: bool = False
    had_explicit_conclusion: bool = False
    had_next_action: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ChatSegment:
    session_id: str
    segment_id: str
    mode: str
    start_turn: int
    end_turn: int
    turn_count: int
    user_messages: List[str]
    assistant_messages: List[str]
    tool_calls: List[str]
    has_delegation: bool
    has_explicit_conclusion: bool
    has_next_action: bool
    topic_summary: str
    conversation_turns: List[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


CONCLUSION_MARKERS = (
    "结论",
    "总结",
    "因此",
    "所以",
    "根因",
    "最终",
    "可以确定",
    "I conclude",
    "in summary",
)

NEXT_ACTION_MARKERS = (
    "下一步",
    "接下来",
    "建议",
    "可以先",
    "我会继续",
    "recommended_next_action",
    "next action",
)

ANALYSIS_MARKERS = (
    "分析",
    "原因",
    "问题",
    "方案",
    "检查",
    "验证",
    "修复",
    "排查",
    "because",
    "reason",
    "diagnos",
)

CHITCHAT_MARKERS = (
    "你好",
    "您好",
    "hi",
    "hello",
    "哈哈",
    "谢谢",
    "晚安",
    "早上好",
    "辛苦了",
    "抱抱",
)


def build_latest_task_segment(
    turns: Sequence[ChatTurnRecord],
    *,
    session_id: str,
    mode: str,
    min_turns: int,
    max_turns: int,
) -> ChatSegment | None:
    if len(turns) < max(1, int(min_turns or 1)):
        return None

    window = list(turns[-max(1, int(max_turns or len(turns))):])
    if not window:
        return None

    start_turn = int(window[0].turn_number)
    end_turn = int(window[-1].turn_number)
    tool_calls: List[str] = []
    for item in window:
        for tool_name in item.tool_calls:
            if tool_name and tool_name not in tool_calls:
                tool_calls.append(tool_name)

    return ChatSegment(
        session_id=session_id,
        segment_id=f"{session_id}_t{start_turn:04d}_{end_turn:04d}",
        mode=str(mode or "chat"),
        start_turn=start_turn,
        end_turn=end_turn,
        turn_count=len(window),
        user_messages=[item.user_message for item in window],
        assistant_messages=[item.assistant_message for item in window],
        tool_calls=tool_calls,
        has_delegation=any(item.had_delegation for item in window),
        has_explicit_conclusion=any(item.had_explicit_conclusion for item in window),
        has_next_action=any(item.had_next_action for item in window),
        topic_summary=summarize_topic(window),
        conversation_turns=[item.to_dict() for item in window],
    )


def summarize_topic(turns: Sequence[ChatTurnRecord], *, max_chars: int = 80) -> str:
    if not turns:
        return ""
    seed = (turns[0].user_message or "").strip().replace("\n", " ")
    if len(seed) <= max_chars:
        return seed
    return seed[: max_chars - 3].rstrip() + "..."


def has_analysis_signal(text: str) -> bool:
    normalized = (text or "").strip().lower()
    if not normalized:
        return False
    if len(normalized) >= 120:
        return True
    return any(marker.lower() in normalized for marker in ANALYSIS_MARKERS)


def has_conclusion_signal(text: str) -> bool:
    normalized = (text or "").strip().lower()
    if not normalized:
        return False
    return any(marker.lower() in normalized for marker in CONCLUSION_MARKERS)


def has_next_action_signal(text: str) -> bool:
    normalized = (text or "").strip().lower()
    if not normalized:
        return False
    return any(marker.lower() in normalized for marker in NEXT_ACTION_MARKERS)


def is_pure_chitchat_segment(segment: ChatSegment) -> bool:
    if segment.tool_calls or segment.has_delegation:
        return False
    combined_user = " ".join(segment.user_messages).strip().lower()
    combined_assistant = " ".join(segment.assistant_messages).strip().lower()
    combined = f"{combined_user} {combined_assistant}".strip()
    if not combined:
        return True
    if len(combined) > 120:
        return False
    if any(marker in combined for marker in CHITCHAT_MARKERS):
        return not has_analysis_signal(combined) and not has_conclusion_signal(combined)
    return False


__all__ = [
    "ChatSegment",
    "ChatTurnRecord",
    "build_latest_task_segment",
    "has_analysis_signal",
    "has_conclusion_signal",
    "has_next_action_signal",
    "is_pure_chitchat_segment",
    "summarize_topic",
]
