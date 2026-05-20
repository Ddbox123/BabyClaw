"""Shared log diagnostics for user-facing summaries and agent investigation anchors."""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any


MAX_SIGNAL_PREVIEW_CHARS = 220
ERROR_SIGNAL_PATTERN = re.compile(
    r"(?i)(traceback|exception|fatal|severe|(?<![a-z])error(?![a-z])|(?<![a-z])failed(?![a-z])|(?<![a-z])failure(?![a-z]))"
)
WARNING_SIGNAL_PATTERN = re.compile(
    r"(?i)((?<![a-z])warn(?:ing)?(?![a-z])|retrying|deprecated|blocked|timeout|timed out)"
)


def analyze_log_content(
    *,
    anchor: str,
    content: str,
    normal_summary: str,
    empty_summary: str,
    error_summary_prefix: str,
    warning_summary_prefix: str,
    error_next_step: str,
    warning_next_step: str,
    structured_next_step: str,
    fallback_next_step: str,
) -> dict[str, Any]:
    lines = content.splitlines()
    error_count = 0
    warning_count = 0
    first_signal_line: int | None = None
    first_signal_preview = ""
    last_signal_line: int | None = None
    last_signal_preview = ""
    type_counts: Counter[str] = Counter()
    structured_event_count = 0

    for index, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue
        is_error = bool(ERROR_SIGNAL_PATTERN.search(stripped))
        is_warning = bool(WARNING_SIGNAL_PATTERN.search(stripped))
        if is_error:
            error_count += 1
        elif is_warning:
            warning_count += 1
        if is_error or is_warning:
            preview = _preview_line(stripped)
            if first_signal_line is None:
                first_signal_line = index
                first_signal_preview = preview
            last_signal_line = index
            last_signal_preview = preview

        event_type = _extract_structured_event_type(stripped)
        if event_type:
            structured_event_count += 1
            type_counts[event_type] += 1

    severity = "error" if error_count else "warning" if warning_count else "info"
    non_empty_line_count = sum(1 for line in lines if line.strip())
    return {
        "severity": severity,
        "lineCount": len(lines),
        "nonEmptyLineCount": non_empty_line_count,
        "errorCount": error_count,
        "warningCount": warning_count,
        "firstSignalLine": first_signal_line,
        "firstSignalPreview": first_signal_preview,
        "lastSignalLine": last_signal_line,
        "lastSignalPreview": last_signal_preview,
        "structuredEventCount": structured_event_count,
        "topEventTypes": [
            {"type": event_type, "count": count}
            for event_type, count in type_counts.most_common(6)
        ],
        "userSummary": _build_user_summary(
            severity=severity,
            error_count=error_count,
            warning_count=warning_count,
            first_signal_line=first_signal_line,
            non_empty_line_count=non_empty_line_count,
            normal_summary=normal_summary,
            empty_summary=empty_summary,
            error_summary_prefix=error_summary_prefix,
            warning_summary_prefix=warning_summary_prefix,
        ),
        "agentHint": _build_agent_hint(anchor, severity, first_signal_line, type_counts),
        "suggestedNextStep": _build_suggested_next_step(
            severity=severity,
            first_signal_line=first_signal_line,
            structured_event_count=structured_event_count,
            error_next_step=error_next_step,
            warning_next_step=warning_next_step,
            structured_next_step=structured_next_step,
            fallback_next_step=fallback_next_step,
        ),
    }


def _extract_structured_event_type(line: str) -> str:
    if not line.startswith("{"):
        return ""
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return ""
    if not isinstance(payload, dict):
        return ""
    for key in ("type", "event_code", "eventCode", "level"):
        value = str(payload.get(key) or "").strip()
        if value:
            return value[:80]
    return "json_object"


def _build_user_summary(
    *,
    severity: str,
    error_count: int,
    warning_count: int,
    first_signal_line: int | None,
    non_empty_line_count: int,
    normal_summary: str,
    empty_summary: str,
    error_summary_prefix: str,
    warning_summary_prefix: str,
) -> str:
    if severity == "error":
        return f"{error_summary_prefix}{error_count} 条错误信号，建议先看第 {first_signal_line} 行附近。"
    if severity == "warning":
        return f"{warning_summary_prefix}{warning_count} 条警告/风险信号，建议从第 {first_signal_line} 行开始确认。"
    if non_empty_line_count == 0:
        return empty_summary
    return normal_summary


def _build_agent_hint(
    anchor: str,
    severity: str,
    first_signal_line: int | None,
    type_counts: Counter[str],
) -> str:
    line_hint = f":{first_signal_line}" if first_signal_line else ""
    event_hint = ""
    if type_counts:
        event_hint = f"; top_event={type_counts.most_common(1)[0][0]}"
    return f"{anchor}{line_hint}; severity={severity}{event_hint}"


def _build_suggested_next_step(
    *,
    severity: str,
    first_signal_line: int | None,
    structured_event_count: int,
    error_next_step: str,
    warning_next_step: str,
    structured_next_step: str,
    fallback_next_step: str,
) -> str:
    if severity == "error":
        return error_next_step.format(line=first_signal_line)
    if severity == "warning":
        return warning_next_step.format(line=first_signal_line)
    if structured_event_count:
        return structured_next_step
    return fallback_next_step


def _preview_line(line: str) -> str:
    normalized = " ".join(str(line or "").split())
    if len(normalized) <= MAX_SIGNAL_PREVIEW_CHARS:
        return normalized
    return normalized[:MAX_SIGNAL_PREVIEW_CHARS].rstrip() + "..."
