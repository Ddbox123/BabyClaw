# -*- coding: utf-8 -*-
"""Streaming protocol normalization for LLM providers.

Provider streams are delta-oriented: tool call names, ids, and JSON arguments
can arrive across multiple chunks. The agent loop should never see those
partials as executable tools. This module translates raw provider chunks into
stable internal stream events.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, Iterator, List

from .types import StreamChunk, ToolCall


def extract_text_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or ""))
            else:
                parts.append(str(item))
        return "".join(parts)
    return str(content or "")


def parse_tool_arguments(raw_args: Any) -> Dict[str, Any]:
    if isinstance(raw_args, str):
        try:
            return json.loads(raw_args) if raw_args.strip() else {}
        except json.JSONDecodeError:
            return {}
    if isinstance(raw_args, dict):
        return raw_args
    return {}


def extract_message_tool_calls(message: Dict[str, Any]) -> List[ToolCall]:
    items: List[ToolCall] = []
    for index, raw_tool in enumerate(message.get("tool_calls") or []):
        tool = _as_dict(raw_tool)
        if not isinstance(tool, dict):
            continue
        function = _as_dict(tool.get("function") or {})
        raw_args = function.get("arguments") or {}
        items.append(
            ToolCall(
                id=str(tool.get("id") or f"tool_{index}"),
                name=str(function.get("name") or ""),
                arguments=parse_tool_arguments(raw_args),
                raw_arguments=raw_args,
                provider_payload=tool,
            )
        )
    return items


class ToolCallAccumulator:
    """Accumulates provider tool-call deltas into executable calls."""

    def __init__(self) -> None:
        self._by_index: Dict[int, Dict[str, Any]] = {}

    def add_deltas(self, deltas: Iterable[Any]) -> None:
        for fallback_index, raw_tool in enumerate(deltas or []):
            tool = _as_dict(raw_tool)
            if not isinstance(tool, dict):
                continue
            index = _safe_int(tool.get("index"), fallback_index)
            state = self._by_index.setdefault(index, {"id": "", "name": "", "arguments": ""})
            if tool.get("id"):
                state["id"] = str(tool.get("id"))
            function = _as_dict(tool.get("function") or {})
            if not isinstance(function, dict):
                continue
            if function.get("name"):
                state["name"] = str(function.get("name"))
            if "arguments" in function:
                self._append_arguments(state, function.get("arguments"))

    def final_calls(self) -> List[ToolCall]:
        calls = [
            self._to_tool_call(index, self._by_index[index])
            for index in sorted(self._by_index)
        ]
        return [call for call in calls if call.name]

    @staticmethod
    def _append_arguments(state: Dict[str, Any], part: Any) -> None:
        if isinstance(part, str):
            state["arguments"] = str(state.get("arguments") or "") + part
        elif isinstance(part, dict):
            state["arguments"] = part
        elif part is not None:
            state["arguments"] = str(state.get("arguments") or "") + str(part)

    @staticmethod
    def _to_tool_call(index: int, state: Dict[str, Any]) -> ToolCall:
        raw_args = state.get("arguments") or ""
        provider_payload = {
            "id": state.get("id") or f"tool_{index}",
            "type": "function",
            "function": {
                "name": state.get("name") or "",
                "arguments": raw_args,
            },
        }
        return ToolCall(
            id=str(state.get("id") or f"tool_{index}"),
            name=str(state.get("name") or ""),
            arguments=parse_tool_arguments(raw_args),
            raw_arguments=raw_args,
            provider_payload=provider_payload,
        )


class LiteLLMStreamNormalizer:
    """Normalizes LiteLLM/OpenAI-compatible chunks into internal events."""

    def __init__(self) -> None:
        self._tool_calls = ToolCallAccumulator()

    def events(self, raw_chunks: Iterable[Any]) -> Iterator[StreamChunk]:
        for raw_chunk in raw_chunks:
            delta = self._extract_delta(raw_chunk)
            if not delta:
                continue
            reasoning = extract_text_content(delta.get("reasoning_content") or "")
            if reasoning:
                yield StreamChunk(type="reasoning_delta", text=reasoning, provider_payload=delta)
            content = extract_text_content(delta.get("content") or "")
            if content:
                yield StreamChunk(type="text_delta", text=content, provider_payload=delta)
            tool_deltas = delta.get("tool_calls") or []
            if tool_deltas:
                self._tool_calls.add_deltas(tool_deltas)
        final_calls = self._tool_calls.final_calls()
        if final_calls:
            yield StreamChunk(type="tool_call_final", tool_calls=final_calls)
        yield StreamChunk(type="done")

    @staticmethod
    def _extract_delta(raw_chunk: Any) -> Dict[str, Any]:
        chunk = _as_dict(raw_chunk)
        choices = chunk.get("choices") if isinstance(chunk, dict) else getattr(raw_chunk, "choices", None)
        choices = choices or []
        if not choices:
            return {}
        choice = _as_dict(choices[0])
        delta = choice.get("delta") if isinstance(choice, dict) else getattr(choices[0], "delta", None)
        delta = _as_dict(delta)
        return delta if isinstance(delta, dict) else {}


def _as_dict(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return value


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


__all__ = [
    "LiteLLMStreamNormalizer",
    "ToolCallAccumulator",
    "extract_message_tool_calls",
    "extract_text_content",
    "parse_tool_arguments",
]
