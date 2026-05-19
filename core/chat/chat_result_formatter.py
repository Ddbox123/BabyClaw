# -*- coding: utf-8 -*-
"""format user-visible chat replies for coding tasks."""

from __future__ import annotations

from typing import Any, Dict, List

from .chat_result_contract import build_chat_coding_result_contract
from .chat_task_types import CHAT_TASK_KIND_CODING, dedupe_strings, status_label, trim_lines


def _summary_from_result(result: Dict[str, Any]) -> str:
    return trim_lines(result.get("summary") or result.get("raw_output") or "", max_lines=6)


def _build_file_line(label: str, items: List[str], *, limit: int = 4) -> str:
    cleaned = dedupe_strings(items, limit=limit)
    if not cleaned:
        return ""
    return f"{label}：{', '.join(cleaned)}"


def format_chat_reply(result: Dict[str, Any] | Any, active_task: Dict[str, Any] | None = None) -> str:
    if not isinstance(result, dict):
        return "本轮没有产生可见回复。"

    summary = _summary_from_result(result)
    if not active_task or str(active_task.get("kind") or "").strip().lower() != CHAT_TASK_KIND_CODING:
        contract = build_chat_coding_result_contract(result)
        lines: List[str] = []
        if summary:
            lines.append(summary)

        changed_line = _build_file_line("修改文件", list(contract.get("changed_files") or []))
        read_line = _build_file_line("已查看", list(contract.get("read_files") or []))
        if changed_line:
            lines.append(changed_line)
        elif read_line:
            lines.append(read_line)

        verification_status = str(contract.get("verification_status") or "").strip().lower()
        verification_summary = trim_lines(contract.get("verification_summary") or "", max_lines=2)
        if verification_status or verification_summary:
            verification_text = verification_summary or status_label(verification_status)
            if verification_status == "passed":
                lines.append(f"验证：通过。{verification_text}")
            elif verification_status == "failed":
                lines.append(f"验证：失败。{verification_text}")
            else:
                lines.append(f"验证：{verification_text}")

        next_action = trim_lines(
            contract.get("required_user_input") or contract.get("blocked_reason") or contract.get("next_action") or "",
            max_lines=2,
        )
        if next_action:
            lines.append(f"下一步：{next_action}")

        text = "\n".join(line for line in lines if str(line).strip()).strip()
        return text or "本轮没有产生可见回复。"

    lines: List[str] = []
    if summary:
        lines.append(summary)

    changed_line = _build_file_line("修改文件", list(active_task.get("changed_files") or []))
    read_line = _build_file_line("已查看", list(active_task.get("read_files") or []))
    verification_status = str(active_task.get("verification_status") or "").strip().lower()
    verification_summary = trim_lines(active_task.get("verification_summary") or "", max_lines=2)
    next_action = trim_lines(active_task.get("next_action") or "", max_lines=2)

    if changed_line:
        lines.append(changed_line)
    elif read_line:
        lines.append(read_line)

    if verification_status or verification_summary:
        verification_text = verification_summary or status_label(active_task.get("status") or "")
        if verification_status == "passed":
            lines.append(f"验证：通过。{verification_text}")
        elif verification_status == "failed":
            lines.append(f"验证：失败。{verification_text}")
        else:
            lines.append(f"验证：{verification_text}")

    if next_action and str(active_task.get("status") or "").strip().lower() not in {"done"}:
        lines.append(f"下一步：{next_action}")

    text = "\n".join(line for line in lines if str(line).strip()).strip()
    return text or "本轮没有产生可见回复。"
