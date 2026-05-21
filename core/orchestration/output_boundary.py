# -*- coding: utf-8 -*-
"""Shared boundary for LLM protocol text before UI or persistence."""

from __future__ import annotations

import re
from typing import Any


_NAMED_PROTOCOL_TAGS = (
    "state",
    "active_components",
    "invoke",
    "parameter",
)

_TRAILING_PARTIAL_PREFIXES = (
    "sta",
    "state",
    "/state",
    "active",
    "active_components",
    "/active_components",
    "inv",
    "invoke",
    "/invoke",
    "par",
    "param",
    "parameter",
    "/parameter",
    "tool",
    "tool_call",
    "/tool_call",
)


def _coerce_text(value: Any) -> str:
    return str(value or "")


def _strip_think_blocks(text: str) -> str:
    cleaned = re.sub(
        r"<(?:think|thinking)\b[^>]*>[\s\S]*?</(?:think|thinking)\s*>",
        "",
        text or "",
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"<(?:think|thinking)\b[^>]*(?:>[\s\S]*)?$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"</?(?:think|thinking)[^>]*>", "", cleaned, flags=re.IGNORECASE)
    return _strip_trailing_partial_protocol_tag(cleaned, extra_prefixes=("thi", "think", "thinking"))


def _strip_think_tags_keep_body(text: str) -> str:
    cleaned = re.sub(r"</?(?:think|thinking)[^>]*>", "", text or "", flags=re.IGNORECASE)
    return _strip_trailing_partial_protocol_tag(cleaned, extra_prefixes=("thi", "think", "thinking"))


def strip_llm_protocol_artifacts(value: Any) -> str:
    """Remove internal protocol/control markup while preserving normal text."""

    text = _coerce_text(value)
    if not text:
        return ""

    for tag in _NAMED_PROTOCOL_TAGS:
        text = re.sub(
            rf"<{tag}\b[^>]*>[\s\S]*?</{tag}\s*>",
            "",
            text,
            flags=re.IGNORECASE,
        )

    text = re.sub(
        r"<[\w:.-]*tool_call\b[^>]*>[\s\S]*?</[\w:.-]*tool_call\s*>",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"<[^>\n]*DSML[^>]*>[\s\S]*?</[^>\n]*DSML[^>]*>",
        "",
        text,
        flags=re.IGNORECASE,
    )

    for tag in _NAMED_PROTOCOL_TAGS:
        text = re.sub(
            rf"<{tag}\b[^>]*(?:>[\s\S]*)?$",
            "",
            text,
            flags=re.IGNORECASE,
        )

    text = re.sub(
        r"<[\w:.-]*tool_call\b[^>]*(?:>[\s\S]*)?$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"<[^>\n]*DSML[^>\n]*(?:>[\s\S]*)?$",
        "",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(
        r"</?(?:state|active_components|invoke|parameter)[^>]*>",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"</?[\w:.-]*tool_call[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"</?[^>\n]*DSML[^>]*>", "", text, flags=re.IGNORECASE)

    text = _strip_trailing_partial_protocol_tag(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def sanitize_assistant_visible_text(value: Any) -> str:
    """Return assistant text safe for UI display and chat-state persistence."""

    text = _strip_think_blocks(_coerce_text(value))
    return strip_llm_protocol_artifacts(text)


def sanitize_assistant_thought_text(value: Any) -> str:
    """Return thought text with protocol blocks removed but thought body kept."""

    text = _strip_think_tags_keep_body(_coerce_text(value))
    return strip_llm_protocol_artifacts(text)


def _strip_trailing_partial_protocol_tag(text: str, *, extra_prefixes: tuple[str, ...] = ()) -> str:
    cleaned = text or ""
    while True:
        match = re.search(r"<[^<>\n]*$", cleaned)
        if not match:
            return cleaned
        fragment = match.group(0)
        normalized = fragment[1:].strip().lower()
        if not normalized:
            cleaned = cleaned[: match.start()]
            continue
        prefixes = _TRAILING_PARTIAL_PREFIXES + tuple(extra_prefixes or ())
        if "dsml" in normalized or any(normalized.startswith(prefix) for prefix in prefixes):
            cleaned = cleaned[: match.start()]
            continue
        return cleaned


__all__ = [
    "sanitize_assistant_thought_text",
    "sanitize_assistant_visible_text",
    "strip_llm_protocol_artifacts",
]
