# -*- coding: utf-8 -*-
"""
Vibelution CLI UI — 统一终端工作台渲染引擎

布局：
- chat：独立会话页（顶部概览 + 底部输入区）
- 其他模式：宠物区 + 任务流 + 系统日志
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from rich.box import ASCII2, ROUNDED
from rich.cells import cell_len
from rich.align import Align
from rich.console import Console, Group
from rich.control import Control
from rich.layout import Layout
from rich.live import Live
from rich.markup import escape as rich_escape
from rich.markdown import Markdown
from rich.measure import Measurement
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from core.pet_system import get_pet_system as get_pet
from core.infrastructure.tool_intents import (
    humanize_reading_task,
    humanize_tool_intent,
    humanize_tool_name,
    humanize_tool_chain,
)
from core.ui.ascii_art import get_avatar_manager
from core.ui.token_display import format_token_count
from core.ui.theme import get_style, get_theme

_console = Console(stderr=False, force_terminal=True)
_stderr_console = Console(stderr=True, force_terminal=True)


@dataclass
class PetExpressionState:
    mental_mood: str = ""
    mental_feeling: str = ""
    mental_whisper: str = ""
    work_state: str = "idle"
    pose: str = "idle"
    direction: str = "right"
    frame_index: int = 0
    target_zone: str = "center_zone"
    turn_progress: int = 0
    pending_direction: str = "right"


@dataclass
class RuntimeTelemetry:
    current_turn: int = 0
    tool_starts: int = 0
    tool_successes: int = 0
    tool_errors: int = 0
    validation_passes: int = 0
    validation_failures: int = 0
    completed_rounds: int = 0
    successful_rounds: int = 0
    failed_rounds: int = 0
    last_tool_name: str = ""
    last_tool_success: Optional[bool] = None
    last_validation_kind: str = ""
    last_validation_passed: Optional[bool] = None
    last_status: str = "IDLE"
    last_error: str = ""
    missing_usage_rounds: int = 0


class VerticalDivider:
    def __init__(self, char: str = "│", style: str = "#d7875f"):
        self.char = char
        self.style = style

    def __rich_measure__(self, console, options):
        return Measurement(1, 1)

    def __rich_console__(self, console, options):
        height = max(1, int(getattr(options, "height", 0) or 1))
        yield Text("\n".join([self.char] * height), style=self.style)


class UIManager:
    """统一终端工作台 UI 管理器。"""

    _instance = None
    _lock = threading.Lock()
    _test_mode = False

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self.console = _console
        self._stderr_console = _stderr_console
        self._live: Optional[Live] = None

        self.theme = get_theme()
        self.style = get_style()
        self.avatar = get_avatar_manager()
        self.pet = get_pet()

        self._status = "IDLE"
        self._current_goal = ""
        self._tool_count = 0
        self._iterations = 0
        self._turn_input_tokens = 0
        self._turn_output_tokens = 0
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._current_context_tokens = 0
        self._context_token_limit = 0
        self._last_request_input_tokens = 0
        self._completed_evolutions = 0
        self._seen_closed_evolution_txns: set[str] = set()
        self._runtime_state_path = Path("workspace") / "ui_runtime_state.json"
        self._load_runtime_totals()
        self._shell_mode = "chat"

        self._chat_messages: List[Dict[str, Any]] = []
        self._chat_task_snapshot: Dict[str, Any] = {}
        self._conversation_events: List[str] = []
        self._tool_activity_events: List[str] = []
        self._system_logs: List[str] = []
        self._thought_history: List[str] = []
        self._delegation_events: List[str] = []
        self._subagent_process_events: List[str] = []
        self._subagent_thought_events: List[str] = []
        self._current_thought_stream = ""
        self._current_subagent_thought_stream = ""

        self._conversation_max = 400
        self._chat_messages_max = 400
        self._tool_activity_max = 120
        self._logs_max = 200
        self._thought_history_max = 6
        self._subagent_process_max = 24
        self._subagent_thought_max = 12
        self._last_terminal_resize_request: tuple[str, int, int] | None = None
        self._pet_walk_offset = 0
        self._pet_walk_direction = 1
        self._pet_anim_running = False
        self._pet_anim_thread: Optional[threading.Thread] = None
        self._pet_pose_tick = 0
        self._pet_state = PetExpressionState()
        self._runtime = RuntimeTelemetry()
        self._runtime_lock = threading.Lock()
        self._subscribe_runtime_events()

    # ======================== 内部状态 ========================

    def reset_workspace(self):
        self._chat_messages.clear()
        self._chat_task_snapshot = {}
        self._conversation_events.clear()
        self._tool_activity_events.clear()
        self._system_logs.clear()
        self._thought_history.clear()
        self._delegation_events.clear()
        self._subagent_process_events.clear()
        self._subagent_thought_events.clear()
        self._current_thought_stream = ""
        self._current_subagent_thought_stream = ""
        self._tool_count = 0
        self._iterations = 0
        self._turn_input_tokens = 0
        self._turn_output_tokens = 0
        self._current_context_tokens = 0
        self._context_token_limit = 0
        self._last_request_input_tokens = 0
        self._current_goal = ""
        self._status = "IDLE"
        self._shell_mode = "chat"
        self._pet_walk_offset = 0
        self._pet_walk_direction = 1
        self._pet_pose_tick = 0
        self._pet_state = PetExpressionState()
        self._runtime = RuntimeTelemetry()
        self._update_status_line()

    def _load_runtime_totals(self):
        try:
            if not self._runtime_state_path.exists():
                self._load_completed_evolutions_from_db()
                return
            data = json.loads(self._runtime_state_path.read_text(encoding="utf-8"))
            self._total_input_tokens = max(0, int(data.get("total_input_tokens") or 0))
            self._total_output_tokens = max(0, int(data.get("total_output_tokens") or 0))
            if "completed_evolutions" in data:
                self._completed_evolutions = max(0, int(data.get("completed_evolutions") or 0))
            else:
                self._load_completed_evolutions_from_db()
            seen = data.get("seen_closed_evolution_txns")
            if isinstance(seen, list):
                self._seen_closed_evolution_txns = {str(item) for item in seen if item}
        except Exception:
            self._total_input_tokens = 0
            self._total_output_tokens = 0
            self._completed_evolutions = 0
            self._seen_closed_evolution_txns = set()

    def _load_completed_evolutions_from_db(self):
        try:
            from core.infrastructure.workspace_manager import get_workspace

            with get_workspace().get_db_connection() as conn:
                rows = conn.cursor().execute(
                    """
                    SELECT txn_id
                    FROM EvolutionTransaction
                    WHERE status = 'success' AND closed_at IS NOT NULL
                    ORDER BY closed_at
                    """
                ).fetchall()
            txn_ids = [str(row["txn_id"]) for row in rows if row["txn_id"]]
            self._completed_evolutions = len(txn_ids)
            self._seen_closed_evolution_txns = set(txn_ids)
        except Exception:
            self._completed_evolutions = 0

    def _save_runtime_state(self):
        try:
            self._runtime_state_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "total_input_tokens": max(0, int(self._total_input_tokens or 0)),
                "total_output_tokens": max(0, int(self._total_output_tokens or 0)),
                "completed_evolutions": max(0, int(self._completed_evolutions or 0)),
                "seen_closed_evolution_txns": sorted(self._seen_closed_evolution_txns)[-200:],
                "current_context_tokens": max(0, int(self._current_context_tokens or 0)),
                "context_token_limit": max(0, int(self._context_token_limit or 0)),
                "turn_input_tokens": max(0, int(self._turn_input_tokens or 0)),
                "turn_output_tokens": max(0, int(self._turn_output_tokens or 0)),
                "status": str(self._status or "").upper(),
                "runtime_status": str(self._runtime.last_status or "").upper(),
                "current_goal": str(self._current_goal or "").strip(),
                "last_tool_name": str(self._runtime.last_tool_name or "").strip(),
                "last_tool_success": self._runtime.last_tool_success,
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            }
            self._runtime_state_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _save_runtime_totals(self):
        self._save_runtime_state()

    def _subscribe_runtime_events(self):
        try:
            from core.infrastructure.event_bus import EventNames, get_event_bus
        except Exception:
            return

        bus = get_event_bus()
        bus.subscribe(EventNames.TOOL_START, self._on_tool_start, callback_id="ui_tool_start")
        bus.subscribe(EventNames.TOOL_SUCCESS, self._on_tool_success, callback_id="ui_tool_success")
        bus.subscribe(EventNames.TOOL_ERROR, self._on_tool_error, callback_id="ui_tool_error")
        bus.subscribe(
            EventNames.VALIDATION_COMPLETED,
            self._on_validation_completed,
            callback_id="ui_validation_completed",
        )
        bus.subscribe(
            EventNames.EVOLUTION_TXN_CLOSED,
            self._on_evolution_txn_closed,
            callback_id="ui_evolution_txn_closed",
        )

    def set_shell_mode(self, mode: str):
        self._shell_mode = (mode or "chat").lower()
        self._ensure_terminal_footprint(self._shell_mode)
        self._update_status_line()

    @staticmethod
    def _terminal_resize_target(mode: str) -> tuple[int, int] | None:
        normalized = str(mode or "").strip().lower()
        if normalized == "chat":
            return (150, 44)
        if normalized in {"shell", "self_evolution"}:
            return (140, 40)
        return None

    def _current_terminal_dimensions(self) -> tuple[int, int]:
        try:
            size = shutil.get_terminal_size(fallback=(0, 0))
            return (int(size.columns or 0), int(size.lines or 0))
        except Exception:
            return (0, 0)

    def _request_terminal_resize(self, cols: int, rows: int) -> bool:
        if cols <= 0 or rows <= 0:
            return False
        resized = False
        try:
            stream = getattr(self.console, "file", None) or sys.__stdout__
            if stream and hasattr(stream, "write") and hasattr(stream, "flush"):
                stream.write(f"\x1b[8;{rows};{cols}t")
                stream.flush()
                resized = True
        except Exception:
            pass
        if os.name == "nt":
            try:
                exit_code = os.system(f"mode con: cols={cols} lines={rows} > nul")
                resized = resized or exit_code == 0
            except Exception:
                pass
        return resized

    def _ensure_terminal_footprint(self, mode: str | None = None) -> bool:
        if UIManager._test_mode:
            return False
        stream = getattr(self.console, "file", None)
        if stream is None or not getattr(stream, "isatty", lambda: False)():
            return False
        normalized_mode = str(mode or self._shell_mode or "chat").strip().lower()
        target = self._terminal_resize_target(normalized_mode)
        if target is None:
            return False
        cols, rows = target
        current_cols, current_rows = self._current_terminal_dimensions()
        if current_cols >= cols and current_rows >= rows:
            return False
        request_key = (normalized_mode, cols, rows)
        if self._last_terminal_resize_request == request_key:
            return False
        resized = self._request_terminal_resize(cols, rows)
        if resized:
            self._last_terminal_resize_request = request_key
        return resized

    def set_avatar_preset(self, preset: str):
        if not preset:
            return
        try:
            self.avatar = get_avatar_manager(preset)
        except Exception:
            self.avatar = get_avatar_manager()
        self._update_status_line()

    @staticmethod
    def _normalize_chat_message_tool_calls(value: Any) -> List[str]:
        tool_calls: List[str] = []
        for item in list(value or []):
            name = ""
            if isinstance(item, dict):
                function_block = item.get("function") or {}
                if not isinstance(function_block, dict):
                    function_block = {}
                name = str(
                    item.get("name")
                    or item.get("tool_name")
                    or function_block.get("name")
                    or ""
                ).strip()
            else:
                name = str(item or "").strip()
            if name:
                tool_calls.append(name)
        return tool_calls

    def load_chat_messages(self, messages: List[Dict[str, Any]]):
        self._chat_messages = []
        for item in list(messages or []):
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip().lower()
            if role not in {"user", "assistant"}:
                continue
            content = self.sanitize_chat_message_content(role, item.get("content") or "")
            if not content:
                continue
            timestamp = str(item.get("timestamp") or "").strip()
            tool_calls = self._normalize_chat_message_tool_calls(item.get("tool_calls") or [])
            entry: Dict[str, Any] = {
                "role": role,
                "content": content,
                "timestamp": timestamp,
            }
            if tool_calls:
                entry["tool_calls"] = tool_calls
            self._chat_messages.append(entry)
        if len(self._chat_messages) > self._chat_messages_max:
            self._chat_messages = self._chat_messages[-self._chat_messages_max :]
        self._update_status_line()

    def set_chat_task_snapshot(self, snapshot: Dict[str, Any] | None):
        self._chat_task_snapshot = dict(snapshot or {}) if isinstance(snapshot, dict) else {}
        self._update_status_line()

    def get_chat_task_snapshot(self) -> Dict[str, Any]:
        return dict(self._chat_task_snapshot)

    def add_chat_message(
        self,
        role: str,
        content: str,
        timestamp: str = "",
        tool_calls: List[str] | None = None,
    ):
        normalized_role = str(role or "").strip().lower()
        text = self.sanitize_chat_message_content(normalized_role, content or "")
        if normalized_role not in {"user", "assistant"} or not text:
            return
        entry: Dict[str, Any] = {
            "role": normalized_role,
            "content": text,
            "timestamp": str(timestamp or "").strip(),
        }
        normalized_tool_calls = self._normalize_chat_message_tool_calls(tool_calls or [])
        if normalized_tool_calls:
            entry["tool_calls"] = normalized_tool_calls
        self._chat_messages.append(entry)
        if len(self._chat_messages) > self._chat_messages_max:
            self._chat_messages = self._chat_messages[-self._chat_messages_max :]
        self._update_status_line()

    def get_chat_messages(self) -> List[Dict[str, Any]]:
        return [dict(item) for item in self._chat_messages]

    def _append_conversation(self, text: str):
        if UIManager._test_mode:
            plain = re.sub(r"\[/?[^\]]+\]", "", text)
            sys.__stdout__.write(plain + "\n")
            sys.__stdout__.flush()
            return
        if not self._live:
            self._conversation_events.append(text)
            if len(self._conversation_events) > self._conversation_max:
                self._conversation_events = self._conversation_events[-self._conversation_max :]
            return
        self._conversation_events.append(text)
        if len(self._conversation_events) > self._conversation_max:
            self._conversation_events = self._conversation_events[-self._conversation_max :]
        self._update_status_line()

    def _append_tool_activity(self, text: str):
        cleaned = (text or "").strip()
        if not cleaned:
            return
        self._tool_activity_events.append(cleaned)
        if len(self._tool_activity_events) > self._tool_activity_max:
            self._tool_activity_events = self._tool_activity_events[-self._tool_activity_max :]
        self._update_status_line()

    def _write_plain_console_fallback(self, text: str):
        plain = re.sub(r"\[/?[^\]]+\]", "", str(text or ""))
        plain = plain.strip("\n")
        if not plain:
            return
        try:
            sys.__stdout__.write(plain + "\n")
            sys.__stdout__.flush()
        except Exception:
            pass

    def _safe_console_render(self, renderable: Any, *, fallback_text: str = ""):
        try:
            self.console.print(renderable)
        except Exception:
            self._write_plain_console_fallback(fallback_text)

    def _append_log(self, text: str):
        if UIManager._test_mode:
            plain = re.sub(r"\[/?[^\]]+\]", "", text)
            sys.__stdout__.write(plain + "\n")
            sys.__stdout__.flush()
            return
        self._system_logs.append(text)
        if len(self._system_logs) > self._logs_max:
            self._system_logs = self._system_logs[-self._logs_max :]
        self._update_status_line()

    def _agent_badge(self, source: str) -> str:
        normalized = (source or "main").strip().lower()
        if normalized in {"sub", "subagent", "child"}:
            return "[bold cyan][子][/bold cyan]"
        return "[bold steel_blue1][主][/bold steel_blue1]"

    def _prefixed_agent_lines(self, source: str, text: str) -> List[str]:
        cleaned = (text or "").strip()
        if not cleaned:
            return []
        badge = self._agent_badge(source)
        continuation_prefix = "    [dim]|[/dim] "
        lines: List[str] = []
        for idx, raw in enumerate(cleaned.splitlines()):
            line = raw.rstrip()
            if not line:
                continue
            prefix = f"{badge} [dim]|[/dim] " if idx == 0 else continuation_prefix
            lines.append(f"{prefix}{line}")
        return lines

    def _append_agent_block(self, source: str, text: str):
        for line in self._prefixed_agent_lines(source, text):
            self._append_conversation(line)

    def add_delegation_evidence(self, summary: str, next_action: str = "", confidence: str = ""):
        text = (summary or "").strip()
        if not text:
            return
        parts = [f"[bold cyan]证据[/bold cyan] {text}"]
        meta: List[str] = []
        if confidence:
            meta.append(f"置信度 {confidence}")
        if next_action:
            meta.append(f"下一步 {next_action}")
        if meta:
            parts.append("[dim]" + " | ".join(meta) + "[/dim]")
        block = "\n".join(parts)
        self._delegation_events.append(block)
        if len(self._delegation_events) > 8:
            self._delegation_events = self._delegation_events[-8:]
        self._append_agent_block("sub", block)
        self._update_status_line()

    def start_subagent_activity(self, task_type: str, goal: str, scope: Any = None):
        self._current_subagent_thought_stream = ""
        task = (task_type or "inspect").strip()
        goal_text = self._compact_sentence(goal or "分析当前问题", limit=44)
        lines = [f"[bold cyan]启动[/bold cyan] {task} | {goal_text}"]
        if scope not in (None, "", {}, []):
            lines.append(f"[dim]范围 {self._compact_value(scope, 52)}[/dim]")
        lines.append("[dim]状态 已派发，等待子 agent 回传[/dim]")
        if isinstance(scope, dict):
            scope_text = json.dumps(scope, ensure_ascii=False)
            if "log_info" in scope_text and "conversation_" in scope_text:
                lines.append("[dim]路径 先尝试快速日志诊断，必要时再拉起真实子 agent[/dim]")
        block = "\n".join(lines)
        self._subagent_process_events.append(block)
        if len(self._subagent_process_events) > self._subagent_process_max:
            self._subagent_process_events = self._subagent_process_events[-self._subagent_process_max:]
        self._append_agent_block("sub", block)
        self._update_status_line()

    def add_subagent_process(self, text: str):
        cleaned = (text or "").strip()
        if not cleaned:
            return
        self._subagent_process_events.append(cleaned)
        if len(self._subagent_process_events) > self._subagent_process_max:
            self._subagent_process_events = self._subagent_process_events[-self._subagent_process_max:]
        self._append_agent_block("sub", cleaned)
        self._update_status_line()

    def set_subagent_thought(self, text: str):
        cleaned = self._sanitize_thought_text(text)
        if not cleaned:
            return
        lines = []
        for raw in cleaned.splitlines():
            line = raw.strip()
            if not line:
                continue
            wrapped = self._wrap_text_cells(line, 68)
            lines.extend(wrapped if wrapped else [line])
        compact = "\n".join(lines).strip()
        if not compact:
            return
        self._subagent_thought_events.append(compact)
        if len(self._subagent_thought_events) > self._subagent_thought_max:
            self._subagent_thought_events = self._subagent_thought_events[-self._subagent_thought_max:]
        self._append_agent_block("sub", "[yellow]思路[/yellow]\n" + compact)
        self._update_status_line()

    def stream_subagent_thought(self, text: str, done: bool = False):
        cleaned = self._sanitize_thought_text(text)
        self._current_subagent_thought_stream = cleaned
        if done and cleaned:
            self.set_subagent_thought(cleaned)
            self._current_subagent_thought_stream = ""
        self._update_status_line()

    def _format_subagent_thought_block(self, text: str, *, width: int = 68, max_lines: int = 8) -> str:
        cleaned = self._sanitize_thought_text(text)
        if not cleaned:
            return ""
        lines = ["[yellow]思路[/yellow]"]
        used = 0
        for raw in cleaned.splitlines():
            line = raw.strip()
            if not line:
                continue
            wrapped = self._wrap_text_cells(line, width)
            wrapped = wrapped if wrapped else [line]
            for chunk in wrapped:
                lines.append(chunk)
                used += 1
                if used >= max_lines:
                    return "\n".join(lines).strip()
        return "\n".join(lines).strip()

    def _format_subagent_process_block(self, text: str, *, width: int = 68, max_lines: int = 10) -> str:
        cleaned = (text or "").strip()
        if not cleaned:
            return ""
        lines = ["[cyan]回传过程[/cyan]"]
        used = 0
        for raw in cleaned.splitlines():
            line = raw.strip()
            if not line:
                continue
            wrapped = self._wrap_text_cells(line, width)
            wrapped = wrapped if wrapped else [line]
            for chunk in wrapped:
                lines.append(chunk)
                used += 1
                if used >= max_lines:
                    return "\n".join(lines).strip()
        return "\n".join(lines).strip()

    def finish_subagent_activity(
        self,
        *,
        status: str,
        summary: str = "",
        findings: Optional[List[Any]] = None,
        evidence: Optional[List[Any]] = None,
        next_action: str = "",
        process: str = "",
        thought: str = "",
        mode_hint: str = "",
    ):
        verdict = (status or "completed").strip().lower()
        label = {
            "completed": "完成",
            "success": "完成",
            "ok": "完成",
            "timeout": "超时",
            "error": "异常",
            "failed": "失败",
        }.get(verdict, verdict or "完成")
        lines = [f"[bold cyan]{label}[/bold cyan] {self._compact_sentence(summary or '子 agent 已返回', limit=52)}"]
        findings = findings or []
        evidence = evidence or []
        if findings:
            first = self._compact_sentence(str(findings[0]), limit=44)
            lines.append(f"[dim]发现 {first}[/dim]")
        elif evidence:
            first = self._compact_sentence(str(evidence[0]), limit=44)
            lines.append(f"[dim]证据 {first}[/dim]")
        if next_action:
            lines.append(f"[dim]建议 {self._compact_sentence(next_action, limit=44)}[/dim]")
        if mode_hint:
            lines.append(f"[dim]路径 {self._compact_sentence(mode_hint, limit=48)}[/dim]")
        self.add_subagent_process("\n".join(lines))
        if process:
            process_block = self._format_subagent_process_block(process)
            if process_block:
                self.add_subagent_process(process_block)
        if thought:
            thought_block = self._format_subagent_thought_block(thought)
            if thought_block:
                self.add_subagent_process(thought_block)
            self.stream_subagent_thought(thought, done=True)
        else:
            self._current_subagent_thought_stream = ""
            self._update_status_line()

    def _sanitize_thought_text(self, text: str) -> str:
        cleaned = text or ""
        cleaned = re.sub(r"</?(?:think|thinking)[^>]*>", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"<(?:think|thinking)?/?[^>\n]*$", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"<state>.*?</state>", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
        cleaned = re.sub(r"<state>\s*.*$", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
        cleaned = re.sub(r"</?[\w:-]*tool_call[^>]*>", "", cleaned, flags=re.IGNORECASE)
        return cleaned.strip()

    def stream_thought(self, text: str, done: bool = False):
        cleaned = self._sanitize_thought_text(text)
        self._current_thought_stream = cleaned
        if done and cleaned:
            self._thought_history.append(cleaned)
            if len(self._thought_history) > self._thought_history_max:
                self._thought_history = self._thought_history[-self._thought_history_max :]
        self._update_status_line()

    def clear_thought_stream(self):
        self._current_thought_stream = ""
        self._update_status_line()

    def set_pet_mental_state(self, mood: str = "", feeling: str = "", whisper: str = ""):
        self._pet_state.mental_mood = mood or ""
        self._pet_state.mental_feeling = feeling or ""
        self._pet_state.mental_whisper = whisper or ""
        self._update_status_line()

    def note_token_usage(self, input_tokens: int = 0, output_tokens: int = 0, observed: bool = True):
        if observed:
            input_count = max(0, int(input_tokens or 0))
            output_count = max(0, int(output_tokens or 0))
            self._turn_input_tokens += input_count
            self._turn_output_tokens += output_count
            self._total_input_tokens += input_count
            self._total_output_tokens += output_count
            self._save_runtime_totals()
        else:
            with self._runtime_lock:
                self._runtime.missing_usage_rounds += 1
        self._update_status_line()

    def note_turn_result(self, success: bool, had_progress: bool = True):
        with self._runtime_lock:
            self._runtime.completed_rounds += 1
            if success:
                self._runtime.successful_rounds += 1
            else:
                self._runtime.failed_rounds += 1
        if had_progress:
            self._status = "SUCCESS" if success else "ERROR"
        self._save_runtime_state()
        self._update_status_line()

    def note_turn_start(self, turn: int):
        with self._runtime_lock:
            self._runtime.current_turn = max(0, int(turn or 0))
        self._turn_input_tokens = 0
        self._turn_output_tokens = 0
        self._last_request_input_tokens = 0
        self._save_runtime_state()
        self._update_status_line()

    def _on_evolution_txn_closed(self, event):
        data = event.data or {}
        if str(data.get("status") or "").strip().lower() != "success":
            return
        txn_id = str(data.get("txn_id") or "").strip()
        if txn_id and txn_id in self._seen_closed_evolution_txns:
            return
        if txn_id:
            self._seen_closed_evolution_txns.add(txn_id)
        self._completed_evolutions += 1
        self._save_runtime_state()
        self._update_status_line()

    def note_context_window(self, current_tokens: int = 0, total_tokens: int = 0):
        self._current_context_tokens = max(0, int(current_tokens or 0))
        self._last_request_input_tokens = self._current_context_tokens
        self._context_token_limit = max(0, int(total_tokens or 0))
        self._save_runtime_state()
        self._update_status_line()

    def _on_tool_start(self, event):
        data = event.data or {}
        with self._runtime_lock:
            self._runtime.tool_starts += 1
            self._runtime.last_tool_name = str(data.get("name") or "")
            self._runtime.last_status = "ACTING"
        if self._status not in {"THINKING", "PLANNING"}:
            self._status = "ACTING"
        self._save_runtime_state()
        self._update_status_line()

    def _on_tool_success(self, event):
        data = event.data or {}
        with self._runtime_lock:
            self._runtime.tool_successes += 1
            self._runtime.last_tool_name = str(data.get("name") or "")
            self._runtime.last_tool_success = True
            self._runtime.last_status = "WORKING"
            self._runtime.last_error = ""
        if self._status not in {"THINKING", "PLANNING"}:
            self._status = "WORKING"
        self._save_runtime_state()
        self._update_status_line()

    def _on_tool_error(self, event):
        data = event.data or {}
        with self._runtime_lock:
            self._runtime.tool_errors += 1
            self._runtime.last_tool_name = str(data.get("name") or "")
            self._runtime.last_tool_success = False
            self._runtime.last_status = "ERROR"
            self._runtime.last_error = str(data.get("error") or "")[:120]
        if self._status not in {"THINKING", "PLANNING"}:
            self._status = "ERROR"
        self._save_runtime_state()
        self._update_status_line()

    def _on_validation_completed(self, event):
        data = event.data or {}
        passed = bool(data.get("passed"))
        with self._runtime_lock:
            if passed:
                self._runtime.validation_passes += 1
            else:
                self._runtime.validation_failures += 1
            self._runtime.last_validation_kind = str(data.get("kind") or "")
            self._runtime.last_validation_passed = passed
        self._update_status_line()

    @staticmethod
    def _contains_any(text: str, words: List[str]) -> bool:
        lowered = (text or "").lower()
        return any(word.lower() in lowered for word in words)

    def _get_pet_stage_status(self) -> str:
        mood = self._pet_state.mental_mood
        feeling = self._pet_state.mental_feeling
        whisper = self._pet_state.mental_whisper

        if self._contains_any(whisper, ["compress", "拥挤", "暂停"]):
            return "tired"
        if mood == "疲惫":
            return "tired"
        if mood == "焦虑":
            return "confused"
        if mood == "迷茫":
            return "confused"
        if mood == "自信":
            return "success"
        if mood == "专注":
            return "thinking"
        if self._contains_any(feeling, ["thrashing", "looping", "焦虑", "重复"]):
            return "confused"
        if self._contains_any(feeling, ["productive", "confident", "顺畅"]):
            return "success"
        if self._current_thought_stream or self._status in {"THINKING", "PLANNING"}:
            return "thinking"
        if self._status in {"ERROR", "FAILED"}:
            return "sad"
        if self._status in {"SUCCESS", "DONE"}:
            return "success"
        if self._status in {"SLEEPING", "PAUSED"}:
            return "sleeping"
        if self._status in {"WORKING", "ACTING", "RUNNING"}:
            return "working"
        return "idle"

    def _derive_pet_behavior(self) -> Dict[str, Any]:
        status = self._get_pet_stage_status()
        feeling = self._pet_state.mental_feeling
        whisper = self._pet_state.mental_whisper
        stage_width = 18

        profile = {
            "pose": "idle",
            "target_zone": "center_zone",
            "interval": 0.45,
            "step": 1,
            "wander": 1,
        }

        if status == "thinking":
            profile.update({"pose": "think", "target_zone": "bubble_zone", "interval": 0.55, "step": 1, "wander": 0})
        elif status == "success":
            profile.update({"pose": "walk", "target_zone": "center_zone", "interval": 0.30, "step": 2, "wander": 3})
        elif status == "working":
            profile.update({"pose": "walk", "target_zone": "center_zone", "interval": 0.28, "step": 2, "wander": 2})
        elif status == "sleeping":
            profile.update({"pose": "sleep", "target_zone": "rest_zone", "interval": 0.85, "step": 1, "wander": 0})
        elif status == "tired":
            profile.update({"pose": "tired", "target_zone": "rest_zone", "interval": 0.72, "step": 1, "wander": 0})
        elif status == "confused":
            profile.update({"pose": "confused", "target_zone": "bubble_zone", "interval": 0.40, "step": 1, "wander": 2})
        elif status == "sad":
            profile.update({"pose": "sad", "target_zone": "rest_zone", "interval": 0.65, "step": 1, "wander": 0})

        if self._contains_any(feeling, ["disoriented", "tunnel", "迷茫"]):
            profile["wander"] = max(profile["wander"], 2)
            profile["interval"] = max(profile["interval"], 0.52)
        if self._contains_any(feeling, ["productive", "confident", "顺畅"]):
            profile["step"] = max(profile["step"], 2)
            profile["interval"] = min(profile["interval"], 0.30)
        if self._contains_any(whisper, ["暂停", "重新审视"]):
            profile["pose"] = "confused"
            profile["step"] = 0
        if self._contains_any(whisper, ["compress", "拥挤"]):
            profile["pose"] = "tired"
            profile["target_zone"] = "rest_zone"

        base_targets = {
            "rest_zone": 2,
            "center_zone": stage_width // 2,
            "bubble_zone": stage_width - 2,
        }
        target = base_targets[profile["target_zone"]]
        if profile["wander"] > 0:
            wobble = ((self._pet_pose_tick // 2) % (profile["wander"] * 2 + 1)) - profile["wander"]
            target = max(0, min(stage_width, target + wobble))

        return {
            "status": status,
            "pose": profile["pose"],
            "target_zone": profile["target_zone"],
            "target_offset": target,
            "interval": profile["interval"],
            "step": profile["step"],
            "stage_width": stage_width,
        }

    def _step_pet_animation(self):
        behavior = self._derive_pet_behavior()
        self._pet_pose_tick = (self._pet_pose_tick + 1) % 1000
        self._pet_state.work_state = self._status.lower()
        self._pet_state.target_zone = behavior["target_zone"]

        target = behavior["target_offset"]
        current = self._pet_walk_offset
        desired_direction = self._pet_state.direction
        if target > current:
            desired_direction = "right"
        elif target < current:
            desired_direction = "left"

        if self._pet_state.turn_progress > 0:
            self._pet_state.pose = "turn"
            self._pet_state.frame_index = (self._pet_state.frame_index + 1) % 2
            self._pet_state.turn_progress -= 1
            if self._pet_state.turn_progress == 0:
                self._pet_state.direction = self._pet_state.pending_direction
                self._pet_walk_direction = 1 if self._pet_state.direction == "right" else -1
            return

        if desired_direction != self._pet_state.direction and abs(target - current) > 0:
            self._pet_state.pending_direction = desired_direction
            self._pet_state.turn_progress = 2
            self._pet_state.pose = "turn"
            self._pet_state.frame_index = 0
            return

        step = behavior["step"]
        moved = False
        if step > 0 and abs(target - current) > 0:
            delta = min(step, abs(target - current))
            self._pet_walk_offset += delta if target > current else -delta
            moved = True

        self._pet_state.direction = desired_direction
        self._pet_walk_direction = 1 if self._pet_state.direction == "right" else -1

        if behavior["pose"] == "sleep":
            self._pet_state.pose = "sleep"
            self._pet_state.frame_index = 0 if (self._pet_pose_tick % 6 < 3) else 1
        elif moved:
            self._pet_state.pose = "walk" if behavior["pose"] not in {"think", "confused", "tired", "sad"} else behavior["pose"]
            self._pet_state.frame_index = (self._pet_state.frame_index + 1) % 2
        else:
            self._pet_state.pose = behavior["pose"]
            self._pet_state.frame_index = (self._pet_pose_tick // 2) % 2 if behavior["pose"] in {"success", "confused"} else 0

    def _animation_loop(self):
        while self._pet_anim_running:
            self._step_pet_animation()
            self._update_status_line()
            interval = self._derive_pet_behavior()["interval"]
            time.sleep(interval)

    def _start_pet_animation(self):
        if UIManager._test_mode or self._pet_anim_running:
            return
        self._pet_anim_running = True
        self._pet_anim_thread = threading.Thread(target=self._animation_loop, name="pet-ui-anim", daemon=True)
        self._pet_anim_thread.start()

    def _stop_pet_animation(self):
        self._pet_anim_running = False
        if self._pet_anim_thread and self._pet_anim_thread.is_alive():
            self._pet_anim_thread.join(timeout=1.0)
        self._pet_anim_thread = None

    @staticmethod
    def _compact_value(value: Any, limit: int = 36) -> str:
        if isinstance(value, bool):
            text = "true" if value else "false"
        elif value is None:
            text = "null"
        elif isinstance(value, (int, float)):
            text = str(value)
        elif isinstance(value, (list, tuple)):
            text = f"[{len(value)} items]"
        elif isinstance(value, dict):
            text = f"{{{len(value)} keys}}"
        else:
            text = str(value).replace("\n", " ").strip()
        if cell_len(text) <= limit:
            return text
        fitted = UIManager._fit_text_cells(text, max(1, limit - 1))
        return fitted if fitted else text

    def _format_tool_args(self, args: Dict[str, Any] | None) -> str:
        if not args:
            return ""
        parts = []
        for key, value in list(args.items())[:3]:
            parts.append(f"{key}={self._compact_value(value, 28)}")
        extra = len(args) - len(parts)
        if extra > 0:
            parts.append(f"+{extra} more")
        return " | ".join(parts)

    def _format_tool_result_lines(self, result: Any) -> List[str]:
        if result is None:
            return ["No result"]

        raw = result if isinstance(result, str) else str(result)
        text = raw.strip()
        if not text:
            return ["Empty result"]

        try:
            parsed = json.loads(text)
        except Exception:
            parsed = None

        if isinstance(parsed, dict):
            lines: List[str] = []
            headline_parts = []
            for key in ("status", "message", "summary", "subject"):
                value = parsed.get(key)
                if value not in (None, "", [], {}):
                    headline_parts.append(f"{key}: {self._compact_value(value, 72)}")
            if headline_parts:
                lines.append(" | ".join(headline_parts[:2]))

            for key in ("count", "path", "change_type", "txn_id", "transaction_status", "dirty_summary"):
                if key in parsed and parsed[key] not in (None, "", [], {}):
                    lines.append(f"{key}: {self._compact_value(parsed[key], 72)}")

            remaining_keys = [
                key for key in parsed.keys()
                if key not in {"status", "message", "summary", "subject", "count", "path", "change_type", "txn_id", "transaction_status", "dirty_summary"}
            ]
            if remaining_keys and len(lines) < 5:
                lines.append("fields: " + ", ".join(remaining_keys[:6]))
            return lines[:5] or ["Object result"]

        if isinstance(parsed, list):
            lines = [f"{len(parsed)} items"]
            if parsed:
                first = parsed[0]
                if isinstance(first, dict):
                    preview_keys = [key for key in ("path", "summary", "subject", "name", "status") if key in first]
                    if preview_keys:
                        lines.append("first: " + " | ".join(
                            f"{key}={self._compact_value(first[key], 48)}" for key in preview_keys[:3]
                        ))
                    else:
                        lines.append(f"first item: {{{len(first)} keys}}")
                else:
                    lines.append("first: " + self._compact_value(first, 72))
            return lines[:4]

        cleaned_lines = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped:
                cleaned_lines.append(stripped)
        if not cleaned_lines:
            return ["Text result"]
        return [self._compact_value(line, 96) for line in cleaned_lines[:4]]

    def _summarize_tool_result(self, result: Any) -> str:
        lines = self._format_tool_result_lines(result)
        if not lines:
            return "done"
        first = lines[0]
        if len(lines) > 1 and not first.startswith("status:") and not first.startswith("message:"):
            return f"{first} | {lines[1]}"
        return first

    def _humanize_work_state(self) -> str:
        mapping = {
            "IDLE": "待机",
            "THINKING": "思考中",
            "PLANNING": "规划中",
            "WORKING": "执行中",
            "ACTING": "行动中",
            "RUNNING": "运行中",
            "SUCCESS": "顺利",
            "DONE": "完成",
            "ERROR": "异常",
            "FAILED": "失败",
            "SLEEPING": "休眠",
            "PAUSED": "暂停",
        }
        return mapping.get(self._status, self._status.title())

    def _compact_sentence(self, text: str, limit: int = 18) -> str:
        cleaned = (text or "").replace("\n", " ").strip()
        if not cleaned:
            return ""
        return self._fit_text_cells(cleaned, limit)

    @staticmethod
    def _fit_text_cells(text: str, width: int) -> str:
        if width <= 0:
            return ""
        text = (text or "").strip()
        if not text:
            return ""

        current = ""
        for ch in text:
            if cell_len(current + ch) > width:
                break
            current += ch

        if current == text or width < 2:
            return current

        ellipsis = "…"
        while current and cell_len(current + ellipsis) > width:
            current = current[:-1]
        return current + ellipsis if current else ellipsis

    def _wrap_text_cells(self, text: str, width: int) -> List[str]:
        if width <= 0:
            return []
        text = (text or "").strip()
        if not text:
            return []

        lines: List[str] = []
        current = ""
        for ch in text:
            if ch == "\n":
                if current.strip():
                    lines.append(current.rstrip())
                current = ""
                continue
            if cell_len(current + ch) > width:
                if current.strip():
                    lines.append(current.rstrip())
                current = ch
            else:
                current += ch
        if current.strip():
            lines.append(current.rstrip())
        return lines

    def _build_mental_bubble_lines(self, width: int = 14, max_lines: int = 4) -> List[str]:
        snippets: List[str] = []
        if self._pet_state.mental_mood:
            snippets.append(self._pet_state.mental_mood)
        if self._pet_state.mental_whisper:
            snippets.append(self._pet_state.mental_whisper)
        if self._pet_state.mental_feeling:
            snippets.append(self._pet_state.mental_feeling)

        cleaned: List[str] = []
        for snippet in snippets:
            wrapped = self._wrap_text_cells(snippet, width)
            cleaned.extend(wrapped[:max_lines])
            if len(cleaned) >= max_lines:
                return cleaned[:max_lines]

        stream = self._sanitize_thought_text(self._current_thought_stream)
        if stream:
            wrapped = []
            for raw_line in stream.splitlines():
                wrapped.extend(self._wrap_text_cells(raw_line, width))
            wrapped = [line for line in wrapped if line.strip()]
            if wrapped:
                return wrapped[-max_lines:]

        return cleaned[:max_lines]

    @staticmethod
    def _get_subagent_companion_art(direction: str = "right") -> List[str]:
        if direction == "left":
            return [
                r" /\_",
                r"(oo )",
                r" / \ ",
            ]
        return [
            r"_/\ ",
            r"( oo)",
            r" / \ ",
        ]

    @staticmethod
    def _merge_stage_line(existing: str, companion_markup: str, companion_offset: int) -> str:
        if not existing:
            return " " * max(0, companion_offset) + companion_markup
        plain_existing = re.sub(r"\[[^\]]+\]", "", existing)
        existing_indent = len(plain_existing) - len(plain_existing.lstrip(" "))
        if companion_offset <= existing_indent:
            companion_width = len(re.sub(r"\[[^\]]+\]", "", companion_markup))
            gap = max(1, existing_indent - companion_offset - companion_width)
            return " " * max(0, companion_offset) + companion_markup + " " * gap + existing.lstrip(" ")
        return existing + " " * max(1, companion_offset - len(plain_existing)) + companion_markup

    def _render_pet_stage(self) -> str:
        canvas_width = 46
        stage_height = 13
        art = self.avatar.get_pose_art(
            pose=self._pet_state.pose,
            direction=self._pet_state.direction,
            frame_index=self._pet_state.frame_index,
            variant=self._pet_state.mental_mood or None,
        ).strip("\n").splitlines()
        sprite_width = max(len(line) for line in art) if art else 0
        stage_width = max(6, canvas_width - sprite_width - 2)
        offset = min(self._pet_walk_offset, stage_width)
        bubble_lines = self._build_mental_bubble_lines(width=14, max_lines=4)
        bubble_width = min(max((cell_len(line) for line in bubble_lines), default=0), 14)
        art_head_row = 0
        art_head_col = 0
        for idx, line in enumerate(art):
            marker_positions = [pos for pos in (line.find("(oo)"), line.find("(??)"), line.find("(^^)"), line.find("(OO)"), line.find("(--)"), line.find("(;;)"), line.find("(<<)")) if pos >= 0]
            if marker_positions:
                art_head_row = idx
                art_head_col = marker_positions[0] + 2
                break

        head_x = min(canvas_width - 1, max(0, offset + art_head_col))
        if self._pet_state.direction == "left":
            bubble_anchor = min(
                max(head_x - 4, 0),
                max(canvas_width - bubble_width - 4, 0),
            )
        else:
            bubble_anchor = min(
                max(head_x - bubble_width + 2, 0),
                max(canvas_width - bubble_width - 4, 0),
            )
        bubble_head_pad = bubble_anchor

        bubble_rendered: List[str] = []
        if bubble_lines:
            top_border = f"[yellow]╭{'─' * (bubble_width + 2)}╮[/yellow]"
            bubble_rendered.append(" " * bubble_head_pad + top_border)
            for line in bubble_lines:
                padded = line + " " * max(bubble_width - cell_len(line), 0)
                bubble_rendered.append(" " * bubble_head_pad + f"[yellow]│[/yellow] {padded} [yellow]│[/yellow]")
            tail_chars = [" "] * (bubble_width + 4)
            tail_chars[0] = "╰"
            for idx in range(1, bubble_width + 3):
                tail_chars[idx] = "─"
            tail_chars[bubble_width + 3] = "╯"
            tail_offset = max(1, min(bubble_width + 2, head_x - bubble_anchor))
            tail_chars[tail_offset] = "o"
            tail_text = "".join(tail_chars)
            bubble_rendered.append(" " * bubble_head_pad + f"[yellow]{tail_text}[/yellow]")

        art_rendered = []
        for idx, line in enumerate(art):
            wobble = 1 if (self._pet_pose_tick % 2 and idx in (1, 4) and self._pet_state.pose in {"walk", "success"}) else 0
            art_rendered.append(" " * max(offset - wobble, 0) + line)

        rendered = [""] * stage_height
        max_content_row = stage_height - 2

        for idx, line in enumerate(bubble_rendered[:max_content_row]):
            rendered[idx] = line

        bubble_reserved_rows = len(bubble_rendered) + (1 if bubble_rendered else 0)
        art_start = max(bubble_reserved_rows, max_content_row - len(art_rendered))
        art_start = max(0, min(art_start, max_content_row - len(art_rendered)))
        for idx, line in enumerate(art_rendered):
            row = art_start + idx
            if 0 <= row < max_content_row:
                rendered[row] = line

        try:
            from core.infrastructure.agent_session import get_session_state

            attention = get_session_state().get_attention_snapshot()
            active_delegation = attention.get("active_delegation")
        except Exception:
            active_delegation = None

        if active_delegation:
            companion_art = self._get_subagent_companion_art(self._pet_state.direction)
            companion_width = max(len(line) for line in companion_art)
            left_slot = offset - companion_width - 2
            right_slot = offset + sprite_width + 2
            max_offset = max(0, canvas_width - companion_width - 1)
            if self._pet_state.direction == "right":
                preferred_offset = left_slot
                fallback_offset = right_slot
            else:
                preferred_offset = right_slot
                fallback_offset = left_slot
            if 0 <= preferred_offset <= max_offset:
                companion_offset = preferred_offset
            elif 0 <= fallback_offset <= max_offset:
                companion_offset = fallback_offset
            else:
                companion_offset = max(0, min(preferred_offset, max_offset))
            companion_start = min(max_content_row - len(companion_art), max(art_start + 1, 0))
            for idx, line in enumerate(companion_art):
                row = companion_start + idx
                if 0 <= row < max_content_row:
                    existing = rendered[row] or ""
                    companion_line = f"[bright_black]{line}[/bright_black]"
                    rendered[row] = self._merge_stage_line(existing, companion_line, companion_offset)

        rendered[-1] = "." * canvas_width
        return "\n".join(rendered)

    # ======================== 渲染 ========================

    @staticmethod
    def _make_bar(value: int, max_val: int = 100, width: int = 10) -> str:
        pct = max(0, min(value, max_val)) / max(max_val, 1)
        filled = int(pct * width)
        return "█" * filled + "░" * (width - filled)

    def _get_pet_snapshot(self) -> Dict[str, Any]:
        snapshot = {
            "name": "Baby Claw",
            "level": 1,
            "age": 0,
            "mood": 100,
            "hunger": 100,
            "energy": 100,
            "health": 100,
            "love": 100,
            "exp": 0,
            "exp_max": 100,
            "daily_tokens": 0,
            "total_tokens": 0,
        }
        try:
            pet = get_pet()
            attrs = pet.data.attributes
            snapshot.update(
                {
                    "name": attrs.name or snapshot["name"],
                    "level": attrs.level,
                    "age": self._completed_evolutions,
                    "mood": attrs.mood,
                    "hunger": attrs.hunger,
                    "energy": int(attrs.energy),
                    "health": attrs.health,
                    "love": attrs.love,
                    "exp": attrs.exp,
                    "exp_max": attrs.exp_to_next,
                    "daily_tokens": pet.data.hunger.daily_tokens,
                    "total_tokens": pet.data.hunger.total_tokens,
                }
            )
        except Exception:
            pass
        return snapshot

    @staticmethod
    def _clamp_metric(value: int) -> int:
        return max(0, min(int(value), 100))

    def _derive_runtime_metrics(self, pet: Dict[str, Any]) -> Dict[str, Any]:
        try:
            from core.infrastructure.agent_session import get_session_state

            attention = get_session_state().get_attention_snapshot()
        except Exception:
            attention = {
                "recent_validation_results": [],
                "recent_blockers": [],
                "language_drift_count": 0,
                "diagnostic_phase": "idle",
                "diagnostic_drift": False,
                "feedback_loop_ready": False,
                "scope_frozen": False,
                "convergence_state": "open",
            }

        with self._runtime_lock:
            runtime = RuntimeTelemetry(**self._runtime.__dict__)

        current_turn = max(0, int(runtime.current_turn or 0))
        react_step = max(0, int(self._iterations or 0))
        completed_rounds = max(0, int(runtime.completed_rounds or 0))
        pet_age = max(0, int(pet.get("age") or 0))

        spirit_factors: List[tuple[str, int]] = []
        energy_factors: List[tuple[str, int]] = []
        stability_factors: List[tuple[str, int]] = []
        bond_factors: List[tuple[str, int]] = []

        mood_bonus = {
            "自信": 14,
            "专注": 8,
            "焦虑": -12,
            "迷茫": -10,
            "疲惫": -14,
        }.get(self._pet_state.mental_mood, 0)
        if mood_bonus:
            spirit_factors.append((self._pet_state.mental_mood or "情绪", mood_bonus))
        status_bonus = {
            "SUCCESS": 10,
            "DONE": 8,
            "WORKING": 4,
            "ACTING": 3,
            "THINKING": 2,
            "ERROR": -12,
            "FAILED": -16,
            "COMPRESSING": -8,
        }.get(self._status, 0)
        if status_bonus:
            spirit_factors.append((self._humanize_work_state(), status_bonus))

        validation_delta = runtime.validation_passes * 4 - runtime.validation_failures * 9
        tool_delta = runtime.tool_successes * 2 - runtime.tool_errors * 5
        blocking_items = [
            item for item in (attention.get("recent_blockers") or [])
            if str(item.get("severity") or "block").lower() != "hint"
        ]
        blocker_penalty = min(len(blocking_items) * 3, 15)
        drift_penalty = 8 if attention.get("diagnostic_drift") else 0
        freeze_bonus = 4 if attention.get("scope_frozen") else 0
        if runtime.validation_passes:
            spirit_factors.append((f"验证通过x{runtime.validation_passes}", runtime.validation_passes * 4))
        if runtime.validation_failures:
            spirit_factors.append((f"验证失败x{runtime.validation_failures}", -(runtime.validation_failures * 9)))
        if runtime.tool_successes:
            spirit_factors.append((f"工具成功x{runtime.tool_successes}", runtime.tool_successes * 2))
        if runtime.tool_errors:
            spirit_factors.append((f"工具错误x{runtime.tool_errors}", -(runtime.tool_errors * 5)))
        if blocker_penalty:
            spirit_factors.append(("阻塞点", -blocker_penalty))
        spirit = self._clamp_metric(68 + mood_bonus + status_bonus + validation_delta + tool_delta - blocker_penalty + freeze_bonus)
        if freeze_bonus:
            spirit_factors.append(("范围冻结", freeze_bonus))

        token_pressure = 0
        total_tokens = max(0, int(pet.get("daily_tokens") or 0))
        if total_tokens > 0:
            token_pressure = min(18, total_tokens // 4000)
        whisper_pressure = 10 if self._contains_any(self._pet_state.mental_whisper, ["compress", "拥挤", "暂停"]) else 0
        energy_penalty = blocker_penalty + drift_penalty + whisper_pressure + token_pressure
        if blocker_penalty:
            energy_factors.append(("阻塞堆积", -blocker_penalty))
        if drift_penalty:
            energy_factors.append(("诊断漂移", -drift_penalty))
        if whisper_pressure:
            energy_factors.append(("压缩警报", -whisper_pressure))
        if token_pressure:
            energy_factors.append(("上下文压力", -token_pressure))
        if self._status in {"THINKING", "PLANNING"}:
            energy_penalty += 4
            energy_factors.append((self._humanize_work_state(), -4))
        if attention.get("scope_frozen"):
            energy_penalty = max(0, energy_penalty - 2)
            energy_factors.append(("范围收束", 2))
        if self._status in {"ERROR", "FAILED"}:
            energy_penalty += 8
            energy_factors.append((self._humanize_work_state(), -8))
        if self._status in {"SUCCESS", "DONE"}:
            energy_penalty -= 4
            energy_factors.append((self._humanize_work_state(), 4))
        if runtime.successful_rounds:
            energy_factors.append((f"顺利回合x{runtime.successful_rounds}", runtime.successful_rounds * 2))
        if runtime.failed_rounds:
            energy_factors.append((f"失败回合x{runtime.failed_rounds}", -(runtime.failed_rounds * 4)))
        energy = self._clamp_metric(82 - energy_penalty + runtime.successful_rounds * 2 - runtime.failed_rounds * 4)

        recent_validations = attention.get("recent_validation_results") or []
        passed_recent = sum(1 for item in recent_validations if item.get("passed"))
        failed_recent = sum(1 for item in recent_validations if not item.get("passed"))
        if passed_recent:
            stability_factors.append((f"近期验证通过x{passed_recent}", passed_recent * 6))
        if failed_recent:
            stability_factors.append((f"近期验证失败x{failed_recent}", -(failed_recent * 12)))
        if runtime.tool_errors:
            stability_factors.append((f"工具错误x{runtime.tool_errors}", -(runtime.tool_errors * 4)))
        if runtime.tool_successes:
            stability_factors.append((f"工具成功x{runtime.tool_successes}", runtime.tool_successes))
        if drift_penalty:
            stability_factors.append(("诊断漂移", -drift_penalty))
        stability = self._clamp_metric(
            76
            + passed_recent * 6
            - failed_recent * 12
            - runtime.tool_errors * 4
            + runtime.tool_successes
            - drift_penalty
        )

        token_bond = min((pet.get("total_tokens") or 0) // 3000, 10)
        if runtime.successful_rounds:
            bond_factors.append((f"顺利回合x{runtime.successful_rounds}", runtime.successful_rounds * 5))
        if runtime.validation_passes:
            bond_factors.append((f"验证通过x{runtime.validation_passes}", runtime.validation_passes * 3))
        if token_bond:
            bond_factors.append(("长期摄食", token_bond))
        if runtime.failed_rounds:
            bond_factors.append((f"失败回合x{runtime.failed_rounds}", -(runtime.failed_rounds * 4)))
        if runtime.validation_failures:
            bond_factors.append((f"验证失败x{runtime.validation_failures}", -(runtime.validation_failures * 3)))
        bond = self._clamp_metric(
            45
            + runtime.successful_rounds * 5
            + runtime.validation_passes * 3
            + token_bond
            - runtime.failed_rounds * 4
            - runtime.validation_failures * 3
        )

        status_note = self._humanize_work_state()
        if runtime.last_validation_kind:
            verdict = "通过" if runtime.last_validation_passed else "失败"
            status_note = f"{status_note} / {runtime.last_validation_kind}:{verdict}"
        elif runtime.last_tool_name:
            verb = "完成" if runtime.last_tool_success else "受阻"
            status_note = f"{status_note} / {runtime.last_tool_name}:{verb}"

        reading_task = str(attention.get("reading_task") or "")
        reading_recommendation = str(attention.get("reading_recommendation") or "")
        reading_sufficiency = str(attention.get("reading_sufficiency") or "")
        next_tool_intent = str(attention.get("next_tool_intent") or "")
        recommended_tools = list(attention.get("recommended_tools") or [])
        avoid_tools = list(attention.get("avoid_tools") or [])
        active_delegation = attention.get("active_delegation") or {}
        feedback_loop_ready = bool(attention.get("feedback_loop_ready"))
        feedback_loop_type = str(attention.get("feedback_loop_type") or "")
        feedback_loop_target = str(attention.get("feedback_loop_target") or "")
        scope_frozen = bool(attention.get("scope_frozen"))
        scope_anchor = str(attention.get("scope_anchor") or "")
        convergence_state = str(attention.get("convergence_state") or "open")
        stop_reason = str(attention.get("stop_reason") or "")
        delegation_running = bool(active_delegation)
        delegation_label = ""
        if delegation_running:
            delegation_goal = str(active_delegation.get("goal") or "").strip()
            delegation_type = str(active_delegation.get("task_type") or "inspect").strip()
            delegation_label = f"{delegation_type}: {self._compact_sentence(delegation_goal, 20)}"
            status_note = f"{status_note} / 子agent干活中"

        def summarize_factors(items: List[tuple[str, int]], limit: int = 2) -> List[tuple[str, int]]:
            if not items:
                return []
            return sorted(items, key=lambda item: abs(item[1]), reverse=True)[:limit]

        return {
            "current_turn": current_turn,
            "react_step": react_step,
            "completed_rounds": completed_rounds,
            "pet_age": pet_age,
            "spirit": spirit,
            "energy": energy,
            "stability": stability,
            "bond": bond,
            "status_note": status_note,
            "spirit_explain": summarize_factors(spirit_factors),
            "energy_explain": summarize_factors(energy_factors),
            "stability_explain": summarize_factors(stability_factors),
            "bond_explain": summarize_factors(bond_factors),
            "reading_task": reading_task,
            "reading_recommendation": reading_recommendation,
            "reading_sufficiency": reading_sufficiency,
            "next_tool_intent": next_tool_intent,
            "recommended_tools": recommended_tools,
            "avoid_tools": avoid_tools,
            "delegation_running": delegation_running,
            "delegation_label": delegation_label,
            "feedback_loop_ready": feedback_loop_ready,
            "feedback_loop_type": feedback_loop_type,
            "feedback_loop_target": feedback_loop_target,
            "scope_frozen": scope_frozen,
            "scope_anchor": scope_anchor,
            "convergence_state": convergence_state,
            "stop_reason": stop_reason,
            "reading_task_label": humanize_reading_task(reading_task),
            "next_tool_intent_label": humanize_tool_intent(next_tool_intent),
            "recommended_tools_label": humanize_tool_chain(recommended_tools, limit=3),
            "avoid_tools_label": " / ".join(humanize_tool_name(name) for name in avoid_tools[:2]),
        }

    def _format_metric_explain(self, label: str, items: List[tuple[str, int]]) -> str:
        if not items:
            return f"[dim]  {label}: 平稳[/dim]"
        parts = []
        for item_label, delta in items:
            color = "green" if delta > 0 else "red"
            sign = "+" if delta > 0 else ""
            parts.append(f"[{color}]{item_label}{sign}{delta}[/{color}]")
        return f"[dim]  {label}: [/dim]" + "[dim] / [/dim]".join(parts)

    def _build_thought_text(self, width: int = 58, max_lines: int = 26) -> str:
        current = self._current_thought_stream.strip()
        if current:
            lines = current.splitlines()
        elif self._thought_history:
            lines = self._thought_history[-1].splitlines()
        else:
            lines = ["等待思考..."]

        cleaned: List[str] = []
        for raw in lines:
            line = raw.strip()
            if not line:
                if cleaned and cleaned[-1] != "":
                    cleaned.append("")
                continue
            cleaned.extend(self._wrap_text_cells(line, width))

        if len(cleaned) > max_lines:
            cleaned = cleaned[-max_lines:]
        return "\n".join(cleaned) or "等待思考..."

    def _build_live_thought_block(self, title: str, text: str, *, width: int = 68, max_lines: int = 8) -> List[str]:
        cleaned = self._sanitize_thought_text(text)
        if not cleaned:
            return []
        lines = [f"[yellow]{title}[/yellow]"]
        used = 0
        for raw in cleaned.splitlines():
            line = raw.strip()
            if not line:
                continue
            wrapped = self._wrap_text_cells(line, width)
            wrapped = wrapped if wrapped else [line]
            for chunk in wrapped:
                lines.append(chunk)
                used += 1
                if used >= max_lines:
                    return lines
        return lines

    def _pad_lines(self, lines: List[str], size: int, filler: str = "[dim]·[/dim]") -> List[str]:
        padded = list(lines[:size])
        if len(padded) < size:
            padded.extend([filler] * (size - len(padded)))
        return padded

    def _build_info_module(
        self,
        title: str,
        lines: List[str],
        *,
        border_style: str = "bright_black",
        filler: str = "[dim]·[/dim]",
    ) -> Panel:
        return Panel(
            Group(*[Text.from_markup(line) for line in self._pad_lines(lines, 3, filler=filler)]),
            title=title,
            border_style=border_style,
            box=ROUNDED,
            padding=(0, 1),
            expand=True,
        )

    def _build_stage_caption(self, runtime_metrics: Dict[str, Any]) -> List[str]:
        focus = runtime_metrics["next_tool_intent_label"] or runtime_metrics["reading_task_label"] or "等待下一步"
        anchor = self._compact_sentence(runtime_metrics["scope_anchor"], 26) or "未固定"
        tool_hint = runtime_metrics["recommended_tools_label"] or "按上下文选择"
        return [
            f"[cyan]焦点[/cyan]  [white]{self._compact_sentence(focus, 28)}[/white]",
            f"[magenta]锚点[/magenta]  [white]{anchor}[/white]",
            f"[green]建议[/green]  [white]{self._compact_sentence(tool_hint, 28)}[/white]",
        ]

    def _is_workspace_summary_line(self, text: str) -> bool:
        plain = re.sub(r"\[[^\]]+\]", "", (text or "")).strip()
        if not plain:
            return False
        noise_prefixes = (
            "Vibelution 模型：",
            "输入任务，或打开工作台菜单开始。",
            "Tasks",
            "记忆状态：",
            "--------------------------------------------------",
            "━━━━━━━━",
            "mode=",
        )
        if any(plain.startswith(prefix) for prefix in noise_prefixes):
            return False
        if plain.startswith("[PromptManager]"):
            return False
        return True

    def _build_workspace_summary_lines(self) -> List[str]:
        lines = [line for line in self._conversation_events if self._is_workspace_summary_line(line)]
        if not lines:
            return ["[dim]当前轮以工具探索为主，暂无自然语言结论。[/dim]"]
        return lines[-24:]

    def _chat_prompt_placeholder(self) -> str:
        return "输入消息..."

    def sanitize_chat_message_content(self, role: str, content: str) -> str:
        text = str(content or "").strip()
        normalized_role = str(role or "").strip().lower()
        if normalized_role != "assistant":
            return text
        text = re.sub(
            r"<(?:think|thinking)[^>]*>.*?</(?:think|thinking)>",
            "",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        text = re.sub(
            r"<(?:think|thinking)[^>]*>.*$",
            "",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        text = re.sub(r"<state[^>]*>.*?</state>", "", text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r"<state[^>]*>.*$", "", text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r"</?(?:think|thinking)[^>]*>", "", text, flags=re.IGNORECASE)
        text = re.sub(r"</?[\w:-]*tool_call[^>]*>", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _format_chat_kv_lines(
        self,
        label: str,
        value: str,
        *,
        width: int,
        value_style: str = "white",
        label_style: str = "grey70",
        max_lines: int = 3,
    ) -> List[str]:
        clean_label = str(label or "").strip()
        clean_value = str(value or "").strip()
        if not clean_label or not clean_value:
            return []
        content_width = max(8, width - cell_len(clean_label) - 2)
        wrapped = self._wrap_text_cells(clean_value, content_width)
        wrapped = wrapped if wrapped else [clean_value]
        lines = [
            f"[{label_style}]{rich_escape(clean_label)}[/{label_style}]  "
            f"[{value_style}]{rich_escape(wrapped[0])}[/{value_style}]"
        ]
        label_pad = " " * max(cell_len(clean_label), 1)
        for chunk in wrapped[1:max_lines]:
            lines.append(
                f"[{label_style}]{label_pad}[/{label_style}]  "
                f"[{value_style}]{rich_escape(chunk)}[/{value_style}]"
            )
        return lines

    def _build_chat_section_block(self, title: str, lines: List[str], *, width: int) -> Group:
        body = [Text.from_markup(line) for line in lines if str(line or "").strip()]
        if not body:
            body = [Text.from_markup("[dim]暂无内容[/dim]")]
        divider = Text.from_markup("[bright_black]" + ("─" * max(12, width - 4)) + "[/bright_black]")
        return Group(
            Text.from_markup(f"[bold #d7875f]{rich_escape(title)}[/bold #d7875f]"),
            divider,
            *body,
        )

    def _build_chat_task_snapshot(self, *, width: int = 32) -> Dict[str, Any]:
        task = dict(self._chat_task_snapshot or {})
        title = str(task.get("title") or "等待新的任务").strip()
        stage = str(task.get("status") or "idle").strip().lower()
        stage_label = {
            "idle": "待命",
            "planning": "规划中",
            "reading": "阅读中",
            "editing": "修改中",
            "verifying": "验证中",
            "done": "已完成",
            "blocked": "受阻",
            "needs_input": "待你决定",
        }.get(stage, "待命")
        stage_progress = {
            "idle": 5,
            "planning": 25,
            "reading": 45,
            "editing": 68,
            "verifying": 86,
            "done": 100,
            "blocked": 100,
            "needs_input": 92,
        }.get(stage, 5)
        verification_status = str(task.get("verification_status") or "").strip().lower()
        verification_summary = str(task.get("verification_summary") or "").strip()
        verification_label = "未运行"
        if verification_status == "passed":
            verification_label = "已通过"
        elif verification_status == "failed":
            verification_label = "失败"
        elif verification_summary:
            verification_label = verification_summary
        resumed = bool((task.get("metadata") or {}).get("resumed"))
        progress_label = "续接任务" if resumed else "新任务"
        latest_summary = self._compact_sentence(str(task.get("latest_summary") or "").strip(), max(18, width - 6))
        next_action = self._compact_sentence(str(task.get("next_action") or "").strip(), max(18, width - 6))
        read_count = len(list(task.get("read_files") or []))
        changed_count = len(list(task.get("changed_files") or []))
        return {
            "title": title,
            "stage": stage,
            "stage_label": stage_label,
            "stage_progress": stage_progress,
            "verification_label": verification_label,
            "progress_label": progress_label,
            "latest_summary": latest_summary,
            "next_action": next_action,
            "read_count": read_count,
            "changed_count": changed_count,
        }

    def _build_chat_recent_lines(self, *, max_messages: int = 6, width: int = 60) -> List[str]:
        if not self._chat_messages:
            return ["[dim]还没有最近对话[/dim]"]
        lines: List[str] = []
        line_budget = max_messages + 4
        for item in self._chat_messages[-max_messages:]:
            role = str(item.get("role") or "assistant").strip().lower()
            content = self.sanitize_chat_message_content(role, item.get("content") or "")
            if not content:
                continue
            role_label = "[cyan]你[/cyan]" if role == "user" else "[green]Agent[/green]"
            wrapped = self._wrap_text_cells(content, width)
            wrapped = wrapped if wrapped else [content]
            first_line = wrapped[0]
            lines.append(f"{role_label}  [white]{rich_escape(first_line)}[/white]")
            for chunk in wrapped[1:3]:
                lines.append(f"[dim]   ·[/dim] [white]{rich_escape(chunk)}[/white]")
            if len(lines) >= line_budget:
                break
        return lines[:line_budget] or ["[dim]还没有最近对话[/dim]"]

    def _normalize_chat_preview_line(self, text: str) -> str:
        line = str(text or "").strip()
        if not line:
            return ""
        if line.startswith(("```", "~~~")):
            return ""
        if re.fullmatch(r"[\-\=\*_`~:\s]+", line):
            return ""
        if "|" in line:
            cells = [cell.strip() for cell in line.split("|") if cell.strip()]
            if not cells:
                return ""
            if all(re.fullmatch(r"[-:]+", cell) for cell in cells):
                return ""
            line = " | ".join(cells[:4])
        line = re.sub(r"^#{1,6}\s*", "", line)
        line = re.sub(r"^\s*[-*+]\s+", "", line)
        line = re.sub(r"^\s*\d+[.)]\s+", "", line)
        line = re.sub(r"`{1,3}([^`]*)`{1,3}", r"\1", line)
        line = re.sub(r"\s+", " ", line).strip()
        return line

    def _build_chat_preview_lines(self, content: str, *, width: int, max_lines: int) -> List[str]:
        normalized_lines: List[str] = []
        raw_lines = [line for line in str(content or "").splitlines() if str(line).strip()]
        for raw_line in raw_lines:
            normalized = self._normalize_chat_preview_line(raw_line)
            if normalized:
                normalized_lines.append(normalized)
        if not normalized_lines:
            fallback = re.sub(r"\s+", " ", str(content or "").strip())
            if fallback:
                normalized_lines = [fallback]
        preview_lines: List[str] = []
        overflow = False
        for raw_line in normalized_lines:
            wrapped = self._wrap_text_cells(raw_line, width) or [self._fit_text_cells(raw_line, width)]
            for chunk in wrapped:
                if len(preview_lines) >= max_lines:
                    overflow = True
                    break
                preview_lines.append(chunk)
            if overflow:
                break
        if not preview_lines:
            return []
        if overflow or len(normalized_lines) > len(preview_lines):
            preview_lines[-1] = self._fit_text_cells(preview_lines[-1], max(2, width - 1))
            if not preview_lines[-1].endswith("…"):
                preview_lines[-1] = self._fit_text_cells(preview_lines[-1] + "…", width)
        return preview_lines

    @staticmethod
    def _chat_message_default_preview_lines(role: str) -> int:
        normalized_role = str(role or "").strip().lower()
        return 3 if normalized_role == "user" else 4

    def _chat_message_preview_body_lines(
        self,
        item: Dict[str, Any],
        *,
        bubble_width: int,
        max_body_lines: int | None = None,
    ) -> List[str]:
        role = str(item.get("role") or "assistant").strip().lower()
        content = self.sanitize_chat_message_content(role, item.get("content") or "")
        if not content:
            return []
        body_width = max(16, bubble_width - 4)
        full_lines: List[str] = []
        raw_lines = str(content or "").splitlines()
        if not raw_lines:
            raw_lines = [str(content or "")]
        for raw_line in raw_lines:
            if raw_line == "":
                full_lines.append("")
                continue
            wrapped = self._wrap_text_cells(raw_line, body_width)
            if wrapped:
                full_lines.extend(wrapped)
            else:
                full_lines.append("")
        if max_body_lines is None:
            return full_lines or [content]
        limit = max(1, int(max_body_lines or 1))
        return list(full_lines[:limit]) or [content]

    def _chat_message_tool_lines(self, item: Dict[str, Any], *, bubble_width: int) -> List[Text]:
        tool_calls = self._normalize_chat_message_tool_calls(item.get("tool_calls") or [])
        if not tool_calls:
            return []
        label = "工具"
        body_width = max(16, bubble_width - 4)
        content_width = max(8, body_width - cell_len(label) - 2)
        tool_text = " -> ".join(tool_calls)
        wrapped = self._wrap_text_cells(tool_text, content_width) or [tool_text]
        label_pad = " " * max(cell_len(label), 1)
        lines: List[Text] = []

        first_line = Text()
        first_line.append(label, style="grey70")
        first_line.append("  ")
        first_line.append(wrapped[0], style="magenta")
        lines.append(first_line)

        for chunk in wrapped[1:]:
            line = Text()
            line.append(label_pad, style="grey70")
            line.append("  ")
            line.append(chunk, style="magenta")
            lines.append(line)
        return lines

    def _format_chat_timestamp(self, timestamp: str) -> str:
        raw = str(timestamp or "").strip()
        if not raw:
            return "刚刚"
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            now = datetime.now(parsed.tzinfo) if parsed.tzinfo else datetime.now()
            if parsed.date() == now.date():
                return parsed.strftime("%H:%M")
            return parsed.strftime("%m-%d %H:%M")
        except Exception:
            return self._fit_text_cells(raw, 14)

    def _build_chat_message_card(
        self,
        item: Dict[str, Any],
        *,
        width: int,
        bubble_width: int,
        max_body_lines: int | None = None,
    ):
        role = str(item.get("role") or "assistant").strip().lower()
        content = self.sanitize_chat_message_content(role, item.get("content") or "")
        if not content:
            return None
        is_user = role == "user"
        role_label = "你" if is_user else "Agent"
        role_style = "cyan" if is_user else "green"
        body_lines_raw = self._chat_message_preview_body_lines(
            item,
            bubble_width=bubble_width,
            max_body_lines=max_body_lines,
        )
        body_lines = [Text(chunk, style="white") for chunk in (body_lines_raw or [content])]
        tool_lines = self._chat_message_tool_lines(item, bubble_width=bubble_width)
        header_line = (
            f"[{role_style}]{role_label}[/{role_style}]  "
            f"[grey70]{self._format_chat_timestamp(str(item.get('timestamp') or ''))}[/grey70]"
        )
        card_lines: List[Any] = [Text.from_markup(header_line), *body_lines]
        if tool_lines:
            card_lines.append(Text(""))
            card_lines.extend(tool_lines)
        message_panel = Panel(
            Group(*card_lines),
            border_style=role_style,
            box=ROUNDED,
            padding=(0, 1),
            width=max(20, int(bubble_width or 20)),
            expand=True,
        )
        return message_panel

    def _build_chat_status_section(self, *, width: int = 60) -> tuple[str, List[str]]:
        snapshot = self._build_chat_task_snapshot(width=width)
        lines: List[str] = []
        lines.extend(
            self._format_chat_kv_lines(
                "任务",
                snapshot["title"],
                width=width,
                value_style="bold white",
                max_lines=2,
            )
        )
        lines.append(
            f"[grey70]阶段[/grey70]  [cyan]{snapshot['stage_label']}[/cyan]  "
            f"[grey70]{snapshot['stage_progress']}%[/grey70]"
        )
        lines.append(
            f"[grey70]流程[/grey70]  [magenta]{self._make_bar(snapshot['stage_progress'], 100, 10)}[/magenta]"
        )
        lines.append(
            f"[grey70]文件[/grey70]  [cyan]读 {snapshot['read_count']}[/cyan]  "
            f"[green]改 {snapshot['changed_count']}[/green]"
        )
        lines.append(f"[grey70]验证[/grey70]  [white]{rich_escape(snapshot['verification_label'])}[/white]")
        lines.extend(self._build_chat_context_summary_lines(width=width))
        return (
            "当前状态",
            lines,
        )

    def _chat_status_panel_width(self) -> int:
        try:
            console_width = int(getattr(self.console, "width", 0) or 0)
        except Exception:
            console_width = 0
        if console_width <= 0:
            return 34
        left_ratio, right_ratio, _ = self._chat_home_layout_metrics()
        usable_width = max(console_width - 10, 48)
        left_width = int((usable_width * left_ratio) / max(left_ratio + right_ratio, 1))
        return max(30, min(left_width, 46))

    def _chat_avatar_art(self, *, max_width: int, max_height: int) -> str:
        compact_art = str(getattr(self.avatar.current, "TINY", "") or "").strip("\n")
        full_art = self.avatar.get_art("happy").strip("\n")
        candidates = []
        if compact_art:
            candidates.append(compact_art)
        candidates.append(full_art)
        for art in candidates:
            lines = [line.rstrip() for line in art.splitlines() if str(line).strip()]
            if not lines:
                continue
            art_width = max((cell_len(line) for line in lines), default=0)
            art_height = len(lines)
            if art_width <= max_width and art_height <= max_height:
                return "\n".join(lines)
        if compact_art:
            return compact_art
        return ""

    def _build_chat_pet_block(self, *, width: int):
        pet = self._get_pet_snapshot()
        preset_label = self.avatar.list_presets().get(self.avatar.preset_name, {}).get("name", self.avatar.preset_name)
        avatar_art = self._chat_avatar_art(max_width=max(12, width - 4), max_height=6)
        if avatar_art:
            avatar_text = Text(avatar_art, style="cyan")
            avatar_text.no_wrap = True
            return Group(Align.center(avatar_text))
        return Group(
            *(
                Text.from_markup(line)
                for line in self._format_chat_kv_lines("伙伴", str(pet["name"]), width=width, value_style="bold cyan")
            ),
            *(
                Text.from_markup(line)
                for line in self._format_chat_kv_lines("形象", str(preset_label), width=width, value_style="white")
            ),
        )

    def _build_chat_identity_block(self):
        section_width = self._chat_status_panel_width()
        total_messages = len(self._chat_messages)
        user_messages = sum(1 for item in self._chat_messages if str(item.get("role") or "").strip().lower() == "user")
        assistant_messages = sum(
            1 for item in self._chat_messages if str(item.get("role") or "").strip().lower() == "assistant"
        )
        mode_label = "Chat Coding" if self._chat_task_snapshot else "Chat Session"
        overview_lines: List[str] = []
        overview_lines.extend(
            self._format_chat_kv_lines("模式", mode_label, width=section_width, value_style="bold cyan")
        )
        overview_lines.extend(
            self._format_chat_kv_lines("状态", self._humanize_work_state(), width=section_width, value_style="cyan")
        )
        overview_lines.extend(
            self._format_chat_kv_lines(
                "会话",
                f"{max(user_messages, assistant_messages, 0)} 轮 / {total_messages} 条消息",
                width=section_width,
                value_style="white",
            )
        )
        overview_lines.extend(
            self._format_chat_kv_lines(
                "角色",
                f"你 {user_messages} / Agent {assistant_messages}",
                width=section_width,
                value_style="white",
            )
        )

        section_title, section_lines = self._build_chat_status_section(width=section_width)
        return Group(
            Text.from_markup("[bold #d7875f]Vibelution Chat[/bold #d7875f]"),
            Text.from_markup("[dim]会话概览[/dim]"),
            Text(""),
            self._build_chat_pet_block(width=section_width),
            Text(""),
            self._build_chat_section_block("概览", overview_lines, width=section_width),
            self._build_chat_section_block(section_title, section_lines, width=section_width),
        )

    def _chat_home_layout_metrics(self) -> tuple[int, int, int]:
        try:
            console_width = int(getattr(self.console, "width", 0) or 0)
        except Exception:
            console_width = 0
        if console_width >= 120:
            return (3, 8, 74)
        if console_width >= 100:
            return (3, 8, 68)
        return (4, 7, 56)

    def _chat_dialog_height_budget(self) -> int:
        try:
            console_height = int(getattr(self.console, "height", 0) or 0)
        except Exception:
            console_height = 0
        if console_height <= 0:
            return 0
        home_height = max(12, console_height - 4)
        return max(8, home_height - 7)

    def _measure_renderable_height(self, renderable: Any, *, width: int) -> int:
        try:
            options = self.console.options.update(width=max(20, int(width or 20)))
            lines = self.console.render_lines(renderable, options=options, pad=False, new_lines=False)
            return max(1, len(lines))
        except Exception:
            return 1

    def _visible_chat_message_cards(self, *, width: int, bubble_width: int, height_budget: int) -> List[Any]:
        selected_cards: List[Any] = []
        used_height = 0
        gap_height = 1
        for item in reversed(self._chat_messages):
            card = self._build_chat_message_card(
                item,
                width=width,
                bubble_width=bubble_width,
                max_body_lines=None,
            )
            if card is None:
                continue
            card_height = self._measure_renderable_height(card, width=width)
            needed = card_height if not selected_cards else card_height + gap_height
            if selected_cards and used_height + needed > height_budget:
                break
            if not selected_cards and card_height > height_budget:
                selected_cards.append(card)
                break
            selected_cards.append(card)
            used_height += needed
        selected_cards.reverse()
        return selected_cards

    def _build_chat_dialog_block(self, *, width: int, height_budget: int | None = None):
        total_messages = len(self._chat_messages)
        bubble_width = max(28, int(width or 28))
        header = Table.grid(expand=True)
        header.add_column(ratio=1)
        header.add_column(no_wrap=True)
        header.add_row(
            Text.from_markup("[bold #d7875f]最近对话[/bold #d7875f]"),
            Text.from_markup(f"[grey70]{total_messages} 条消息[/grey70]"),
        )

        cards: List[Any] = []
        if not self._chat_messages:
            cards.append(
                Panel(
                    Text.from_markup("[dim]还没有最近对话[/dim]"),
                    border_style="bright_black",
                    box=ROUNDED,
                    padding=(0, 1),
                    expand=True,
                )
            )
        else:
            if height_budget and height_budget > 0:
                visible_cards = self._visible_chat_message_cards(
                    width=width,
                    bubble_width=bubble_width,
                    height_budget=max(6, int(height_budget)),
                )
            else:
                visible_cards = [
                    card
                    for item in self._chat_messages
                    for card in [self._build_chat_message_card(item, width=width, bubble_width=bubble_width)]
                    if card is not None
                ]
            if not visible_cards:
                visible_cards = [
                    card
                    for item in self._chat_messages[-1:]
                    for card in [self._build_chat_message_card(item, width=width, bubble_width=bubble_width)]
                    if card is not None
                ]
            for card in visible_cards:
                cards.append(card)
                cards.append(Text(""))
            if cards and isinstance(cards[-1], Text) and cards[-1].plain == "":
                cards.pop()
        dialog_body = Group(*cards)
        return Group(
            header,
            Text.from_markup("[dim]完整消息保留；空间不足时减少显示条数，不截断单条消息[/dim]"),
            Text(""),
            Align(dialog_body, align="left", vertical="bottom"),
        )

    def _build_chat_home_panel(self):
        left_ratio, right_ratio, right_text_width = self._chat_home_layout_metrics()
        dialog_height_budget = self._chat_dialog_height_budget()
        inner = Layout()
        inner.split_row(
            Layout(self._build_chat_identity_block(), name="chat_status", ratio=left_ratio),
            Layout(VerticalDivider(), name="chat_divider", size=1),
            Layout(
                self._build_chat_dialog_block(width=right_text_width, height_budget=dialog_height_budget),
                name="chat_dialog",
                ratio=right_ratio,
            ),
        )
        return Panel(
            inner,
            border_style="#d7875f",
            box=ROUNDED,
            padding=(1, 2),
        )

    def _build_chat_input_panel(self) -> Panel:
        mode_label = "Chat Coding" if self._chat_task_snapshot else "Chat Session"
        header = Table.grid(expand=True)
        header.add_column(ratio=1)
        header.add_column(no_wrap=True)
        header.add_row(
            Text.from_markup("[bold #d7875f]消息输入[/bold #d7875f]"),
            Text.from_markup(f"[grey70]{mode_label}  Enter 发送  /back 返回[/grey70]"),
        )
        lines = [
            header,
            Text.from_markup(
                f"[cyan]你[/cyan]  [bright_black]│[/bright_black] "
                f"[dim]{self._chat_prompt_placeholder()}[/dim]"
            ),
        ]
        return Panel(
            Group(*lines),
            border_style="#d7875f",
            box=ROUNDED,
            padding=(0, 1),
            expand=True,
        )

    def _context_usage_ratio(self) -> tuple[int, int, int]:
        current = max(0, int(self._current_context_tokens or 0))
        limit = max(0, int(self._context_token_limit or 0))
        pct = int((current / limit) * 100) if limit > 0 else 0
        return current, limit, pct

    def _chat_context_status_markup(self) -> str:
        current, limit, pct = self._context_usage_ratio()
        if limit <= 0:
            return "[grey70]上下文[/grey70]  [dim]等待首轮请求[/dim]"
        if pct >= 90:
            pct_style = "bold red"
            bar_style = "red"
        elif pct >= 75:
            pct_style = "yellow"
            bar_style = "yellow"
        else:
            pct_style = "cyan"
            bar_style = "cyan"
        return (
            f"[grey70]上下文[/grey70]  "
            f"[{bar_style}]{self._make_bar(current, limit, 8)}[/{bar_style}]  "
            f"[white]{format_token_count(current)}[/white]"
            f"[dim] / {format_token_count(limit)}[/dim]  "
            f"[{pct_style}]{pct}%[/{pct_style}]"
        )

    def _build_chat_context_summary_lines(self, *, width: int) -> List[str]:
        current, limit, pct = self._context_usage_ratio()
        if limit <= 0:
            return self._format_chat_kv_lines("上下文", "等待首轮请求", width=width, value_style="dim", max_lines=2)
        usage_lines = self._format_chat_kv_lines(
            "上下文",
            f"{format_token_count(current)} / {format_token_count(limit)}",
            width=width,
            value_style="white",
            max_lines=2,
        )
        if pct >= 90:
            pct_style = "bold red"
            bar_style = "red"
        elif pct >= 75:
            pct_style = "yellow"
            bar_style = "yellow"
        else:
            pct_style = "cyan"
            bar_style = "cyan"
        usage_lines.append(
            f"[grey70]占比[/grey70]  [{pct_style}]{pct}%[/{pct_style}]  "
            f"[{bar_style}]{self._make_bar(current, limit, 8)}[/{bar_style}]"
        )
        return usage_lines

    def chat_prompt_label(self) -> str:
        try:
            width = int(getattr(self.console, "width", 0) or 0)
        except Exception:
            width = 0
        if width >= 120:
            indent = 66
        elif width >= 96:
            indent = 44
        elif width >= 80:
            indent = 24
        else:
            indent = 8
        return (" " * max(0, indent)) + "你"

    def _locate_chat_input_bounds(self) -> tuple[int, int, int] | None:
        if self._shell_mode != "chat":
            return None
        placeholder = self._chat_prompt_placeholder()
        try:
            renderable = self._status_renderable()
            lines = self.console.render_lines(
                renderable,
                options=self.console.options,
                pad=True,
                new_lines=False,
            )
        except Exception:
            return None
        plain_lines = ["".join(segment.text for segment in line) for line in lines]
        for row, line in enumerate(plain_lines):
            column = line.find(placeholder)
            if column >= 0:
                right_border = line.rfind("│")
                width = max(8, right_border - column - 1) if right_border > column else len(placeholder)
                return (column, row, width)
        return None

    def _locate_chat_prompt_cursor(self) -> tuple[int, int] | None:
        bounds = self._locate_chat_input_bounds()
        if bounds is None:
            return None
        column, row, _width = bounds
        return (column, row)

    def position_chat_prompt_cursor(self) -> bool:
        if self._shell_mode != "chat":
            return False
        controller = getattr(self.console, "control", None)
        if not callable(controller):
            return False
        try:
            bounds = self._locate_chat_input_bounds()
            if bounds is None:
                return False
            column, row, _width = bounds
            controller(
                Control.move_to(column, row),
            )
            return True
        except Exception:
            return False

    @staticmethod
    def _tail_fit_text_cells(text: str, width: int) -> str:
        if width <= 0:
            return ""
        fitted = ""
        for ch in reversed(text or ""):
            if cell_len(ch + fitted) > width:
                break
            fitted = ch + fitted
        return fitted

    def _paint_chat_input_buffer(self, text: str, bounds: tuple[int, int, int]) -> None:
        column, row, width = bounds
        prefix = "> "
        prefix_width = cell_len(prefix)
        visible = self._tail_fit_text_cells(text, max(0, width - prefix_width))
        display = prefix + visible
        padding = " " * max(0, width - cell_len(display))
        controller = getattr(self.console, "control", None)
        stream = getattr(self.console, "file", None)
        if not callable(controller) or stream is None:
            return
        controller(Control.move_to(column, row))
        stream.write(display + padding)
        stream.flush()
        controller(Control.move_to(column + cell_len(display), row))

    def _read_chat_input_inline_windows(self, bounds: tuple[int, int, int]) -> str:
        import msvcrt

        buffer = ""
        self._paint_chat_input_buffer(buffer, bounds)
        while True:
            ch = msvcrt.getwch()
            if ch in ("\r", "\n"):
                return buffer
            if ch == "\003":
                raise KeyboardInterrupt
            if ch in ("\b", "\x7f"):
                buffer = buffer[:-1]
                self._paint_chat_input_buffer(buffer, bounds)
                continue
            if ch in ("\x00", "\xe0"):
                _ = msvcrt.getwch()
                continue
            if not ch or not ch.isprintable():
                continue
            buffer += ch
            self._paint_chat_input_buffer(buffer, bounds)

    def _read_chat_input_inline_posix(self, bounds: tuple[int, int, int]) -> str:
        import termios
        import tty

        buffer = ""
        stream = sys.stdin
        fileno = stream.fileno()
        old_settings = termios.tcgetattr(fileno)
        self._paint_chat_input_buffer(buffer, bounds)
        try:
            tty.setraw(fileno)
            while True:
                ch = stream.read(1)
                if ch in ("\r", "\n"):
                    return buffer
                if ch == "\x03":
                    raise KeyboardInterrupt
                if ch in ("\x7f", "\b"):
                    buffer = buffer[:-1]
                    self._paint_chat_input_buffer(buffer, bounds)
                    continue
                if ch == "\x1b":
                    seq = stream.read(2)
                    if seq.startswith("["):
                        continue
                if not ch or not ch.isprintable():
                    continue
                buffer += ch
                self._paint_chat_input_buffer(buffer, bounds)
        finally:
            termios.tcsetattr(fileno, termios.TCSADRAIN, old_settings)

    def read_chat_input(self) -> str:
        if self._shell_mode != "chat":
            return self.console.input("> ", markup=False, emoji=False)
        bounds = self._locate_chat_input_bounds()
        if bounds is not None and getattr(sys.stdin, "isatty", lambda: False)():
            try:
                if sys.platform.startswith("win"):
                    return self._read_chat_input_inline_windows(bounds)
                return self._read_chat_input_inline_posix(bounds)
            except Exception:
                pass
        positioned = self.position_chat_prompt_cursor()
        if positioned and bounds is not None:
            self._paint_chat_input_buffer("", bounds)
            return self.console.input("", markup=False, emoji=False)
        fallback = self.chat_prompt_label().strip() or "你"
        return self.console.input(f"[bold white]{fallback}:[/bold white] ", markup=True, emoji=False)

    def _build_pet_panel(self):
        pet = self._get_pet_snapshot()
        runtime_metrics = self._derive_runtime_metrics(pet)
        exp_max = max(int(pet["exp_max"] or 100), 1)
        exp_pct = int((pet["exp"] / exp_max) * 100)
        turn_total_tokens = self._turn_input_tokens + self._turn_output_tokens
        all_total_tokens = self._total_input_tokens + self._total_output_tokens
        context_limit = max(0, int(self._context_token_limit or 0))
        context_current = max(0, int(self._current_context_tokens or 0))
        request_input = max(0, int(self._last_request_input_tokens or 0))
        context_pct = int((context_current / context_limit) * 100) if context_limit > 0 else 0
        context_limit_text = format_token_count(context_limit) if context_limit else "?"
        convergence_label = {
            "open": "开放",
            "narrowing": "收窄中",
            "ready_to_fix": "准备修复",
            "ready_to_verify": "准备验证",
            "ready_to_stop": "准备停止",
            "stopped": "已停止",
        }.get(runtime_metrics["convergence_state"], runtime_metrics["convergence_state"])

        identity_lines = [
            f"[bold cyan]Vibelution[/bold cyan]  [dim]{runtime_metrics['status_note']}[/dim]",
            f"[bold]{pet['name']}[/bold]  [dim]Lv.{pet['level']}[/dim]",
            f"[grey70]岁数[/grey70]  [magenta]{runtime_metrics['pet_age']} 岁[/magenta]  [grey70]状态[/grey70]  [cyan]{self._humanize_work_state()}[/cyan]",
        ]
        progress_lines = [
            f"[grey70]轮次[/grey70]  [cyan]第 {runtime_metrics['current_turn']} 轮[/cyan]",
            f"[grey70]ReAct步[/grey70]  [yellow]{runtime_metrics['react_step']}[/yellow]  [grey70]完成轮[/grey70]  [cyan]{runtime_metrics['completed_rounds']}[/cyan]",
            f"[grey70]成长[/grey70]  [dim]{self._make_bar(pet['exp'], exp_max, 10)}[/dim]  {exp_pct:>3}%",
        ]
        context_lines = [
            f"[grey70]请求上下文[/grey70]  [cyan]In {format_token_count(request_input)}[/cyan] [dim]/ {context_limit_text}[/dim]",
            f"[grey70]上下文当前[/grey70]  [cyan]{format_token_count(context_current)}[/cyan]  [grey70]占比[/grey70]  [yellow]{context_pct}%[/yellow]",
            f"[grey70]本轮消耗[/grey70]  [cyan]In {format_token_count(self._turn_input_tokens)}[/cyan]  [cyan]Out {format_token_count(self._turn_output_tokens)}[/cyan]  [cyan]Σ {format_token_count(turn_total_tokens)}[/cyan]  [grey70]累计 Token[/grey70]  [yellow]In {format_token_count(self._total_input_tokens)} Out {format_token_count(self._total_output_tokens)} Σ {format_token_count(all_total_tokens)}[/yellow]",
        ]

        runtime_focus: List[str] = []
        if self._pet_state.mental_mood:
            runtime_focus.append(f"[grey70]心智[/grey70]  [yellow]{self._compact_sentence(self._pet_state.mental_mood, 28)}[/yellow]")
        if runtime_metrics["delegation_running"]:
            delegate_detail = runtime_metrics["delegation_label"]
            delegate_label = "子 agent 干活中"
            if delegate_detail:
                delegate_label = f"{delegate_label} | {self._compact_sentence(delegate_detail, 18)}"
            runtime_focus.append(f"[grey70]委派[/grey70]  [bright_cyan]{delegate_label}[/bright_cyan]")
        if runtime_metrics["reading_task"] and runtime_metrics["reading_task"] != "locate":
            runtime_focus.append(f"[grey70]阅读[/grey70]  [cyan]{runtime_metrics['reading_task_label']}[/cyan]")
        if runtime_metrics["reading_sufficiency"]:
            runtime_focus.append(
                f"[grey70]充分性[/grey70]  [green]{self._compact_sentence(runtime_metrics['reading_sufficiency'], 28)}[/green]"
            )
        if runtime_metrics["next_tool_intent"]:
            runtime_focus.append(f"[grey70]决策[/grey70]  [yellow]{runtime_metrics['next_tool_intent_label']}[/yellow]")
        tool_line = runtime_metrics["recommended_tools_label"] or "按当前上下文选择"
        if runtime_metrics["avoid_tools"]:
            tool_line = f"{tool_line}  | 避免 {runtime_metrics['avoid_tools_label']}"
        if runtime_metrics["recommended_tools"] or runtime_metrics["avoid_tools"]:
            runtime_focus.append(f"[grey70]工具[/grey70]  [dim]{tool_line}[/dim]")
        if runtime_metrics["feedback_loop_ready"]:
            loop_type = runtime_metrics["feedback_loop_type"] or "active"
            runtime_focus.append(f"[grey70]反馈环[/grey70]  [green]{loop_type}[/green]")
        runtime_lines = self._pad_lines(runtime_focus, 3, filler="[dim]等待新的决策信号[/dim]")

        control_lines = [
            f"[grey70]收束[/grey70]  [magenta]{convergence_label}[/magenta]",
            f"[grey70]锚点[/grey70]  [dim]{self._compact_sentence(runtime_metrics['scope_anchor'], 28) or '未固定'}[/dim]",
            f"[grey70]工具[/grey70]  [dim]{tool_line}[/dim]",
        ]
        health_lines = [
            f"[grey70]心气[/grey70] [yellow]{runtime_metrics['spirit']:>3}[/yellow]  [grey70]精力[/grey70] [cyan]{runtime_metrics['energy']:>3}[/cyan]  [grey70]稳态[/grey70] [red]{runtime_metrics['stability']:>3}[/red]  [grey70]羁绊[/grey70] [magenta]{runtime_metrics['bond']:>3}[/magenta]",
            f"[grey70]摄食[/grey70]  [cyan]{format_token_count(pet['daily_tokens'])}[/cyan] [dim]今日[/dim] / [dim]{format_token_count(pet['total_tokens'])} 累计[/dim]",
            "[dim]状态指标已压缩为单行，便于快速扫读[/dim]",
        ]

        meta_layout = Layout()
        meta_layout.split_column(
            Layout(self._build_info_module("[cyan]身份[/cyan]", identity_lines), size=5),
            Layout(self._build_info_module("[white]进度[/white]", progress_lines), size=5),
            Layout(self._build_info_module("[yellow]上下文[/yellow]", context_lines), size=5),
            Layout(self._build_info_module("[magenta]决策态[/magenta]", runtime_lines), size=5),
            Layout(self._build_info_module("[green]体征[/green]", health_lines), size=5),
        )

        stage_caption = self._build_stage_caption(runtime_metrics)
        stage_text = Text.from_markup(self._render_pet_stage(), style="cyan")
        stage_text.no_wrap = True
        stage_text.overflow = "crop"
        stage_group = Group(
            *[Text.from_markup(line) for line in stage_caption],
            Text(""),
            stage_text,
        )

        stage_panel = Panel(
            stage_group,
            title="[cyan]舞台[/cyan]",
            border_style="bright_black",
            box=ROUNDED,
            padding=(0, 1),
            expand=True,
        )

        inner = Layout()
        inner.split_column(
            Layout(meta_layout, name="pet_meta", size=23),
            Layout(stage_panel, name="pet_stage", ratio=1),
        )
        return Panel(inner, title="宠物空间", border_style="magenta", box=ROUNDED, padding=(0, 1))

    def _build_conversation_panel(self):
        if self._shell_mode == "chat":
            return self._build_chat_home_panel()
        thought_lines: List[str] = []
        main_live = self._build_live_thought_block(
            "思考(进行中)",
            self._current_thought_stream,
            width=68,
            max_lines=5,
        )
        if main_live:
            thought_lines.extend(self._prefixed_agent_lines("main", "\n".join(main_live)))
        sub_live = self._build_live_thought_block(
            "子 agent 思路(进行中)",
            self._current_subagent_thought_stream,
            width=68,
            max_lines=5,
        )
        if sub_live:
            thought_lines.extend(self._prefixed_agent_lines("sub", "\n".join(sub_live)))
        if not thought_lines:
            thought_lines = ["[dim]等待思考...[/dim]"]
        output_lines = self._build_workspace_summary_lines()
        tool_lines = self._tool_activity_events[-28:] if self._tool_activity_events else ["[dim]工具调用尚未开始。[/dim]"]
        work_layout = Layout()
        work_layout.split_row(
            Layout(
                Panel(
                    Group(*[Text.from_markup(line) for line in output_lines]),
                    title="工作区",
                    border_style="bright_black",
                    box=ROUNDED,
                    padding=(0, 0),
                    expand=True,
                ),
                name="output",
                ratio=5,
            ),
            Layout(
                Panel(
                    Group(*[Text.from_markup(line) for line in tool_lines]),
                    title="工具调用",
                    border_style="cyan",
                    box=ROUNDED,
                    padding=(0, 0),
                    expand=True,
                ),
                name="tools",
                ratio=3,
            ),
        )
        inner = Layout()
        inner.split_column(
            Layout(
                Panel(
                    Group(*[Text.from_markup(line) for line in thought_lines]),
                    title="思考",
                    border_style="yellow",
                    box=ROUNDED,
                    padding=(0, 0),
                    expand=True,
                ),
                name="thought",
                size=6,
            ),
            Layout(
                work_layout,
                name="workspace",
                ratio=1,
            ),
        )
        return Panel(
            inner,
            title=f"任务流 | {self._shell_mode.upper()}",
            border_style="bright_black",
            box=ROUNDED,
            padding=(0, 0),
        )

    def _build_logs_panel(self):
        lines = self._system_logs[-6:] if self._system_logs else ["[dim]系统日志为空。[/dim]"]
        return Panel(
            Group(*[Text.from_markup(line) for line in lines]),
            title="系统日志",
            border_style="dim",
            box=ROUNDED,
            padding=(0, 0),
        )

    def _status_renderable(self):
        if self._shell_mode == "chat":
            layout = Layout()
            layout.split_column(
                Layout(self._build_conversation_panel(), name="chat_home", ratio=1),
                Layout(self._build_chat_input_panel(), name="chat_input", size=4),
            )
            return layout
        layout = Layout()
        layout.split_column(Layout(name="body", ratio=1), Layout(name="logs", size=7))
        layout["body"].split_row(Layout(name="pet", size=60), Layout(name="conversation", ratio=1))
        layout["pet"].update(self._build_pet_panel())
        layout["conversation"].update(self._build_conversation_panel())
        layout["logs"].update(self._build_logs_panel())
        return layout

    def render_shell_snapshot(self):
        return self._status_renderable()

    # ======================== Live ========================

    def start_live(self, transient: bool = False):
        if UIManager._test_mode:
            return
        self._ensure_terminal_footprint(self._shell_mode)
        if self._live is None:
            try:
                from core.logging.logger import reset_token_console

                reset_token_console()
            except Exception:
                pass

            self._live = Live(
                self._status_renderable(),
                console=self.console,
                refresh_per_second=6,
                transient=bool(transient),
                auto_refresh=False,
                redirect_stdout=False,
                redirect_stderr=False,
            )
            self._live.start()
            self._start_pet_animation()

    def stop_live(self):
        if UIManager._test_mode:
            return
        if self._live:
            self._stop_pet_animation()
            self._live.stop()
            self._live = None

    def _update_status_line(self):
        if self._live and not UIManager._test_mode:
            try:
                self._live.update(self._status_renderable(), refresh=True)
            except Exception:
                pass

    # ======================== 对外接口 ========================

    def update_status(
        self,
        status: str,
        generation: int = None,
        goal: str = None,
        iterations: int = None,
        tool_count: int = None,
        input_tokens: int = None,
        output_tokens: int = None,
    ):
        self._status = status.upper()
        if goal is not None:
            self._current_goal = goal
        if iterations is not None:
            self._iterations = iterations
        if tool_count is not None:
            self._tool_count = tool_count
        if input_tokens is not None:
            self._turn_input_tokens = max(0, int(input_tokens or 0))
        if output_tokens is not None:
            self._turn_output_tokens = max(0, int(output_tokens or 0))
        self._save_runtime_state()
        self._update_status_line()

    def refresh_pet_display(self):
        self._update_status_line()

    def set_task_board(self, markdown: str):
        if markdown:
            self._append_conversation("[bold yellow]Tasks[/bold yellow]")
            for line in markdown.splitlines():
                self._append_conversation(line)

    def increment_tool_count(self):
        self._tool_count += 1
        self._update_status_line()

    def add_content(self, text: str):
        if UIManager._test_mode:
            sys.__stdout__.write(str(text) + "\n")
            sys.__stdout__.flush()
            return
        self._append_conversation(text)

    def add_content_block(self, lines: List[str]):
        for line in lines:
            self.add_content(line)

    def clear_content(self):
        self._conversation_events.clear()
        self._update_status_line()

    def add_log(self, message: str, level: str = "INFO"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        try:
            icon = self.theme.get_log_icon(level.upper()) if self.theme else "--"
            color = self.theme.get_log_color(level.upper()) if self.theme else "white"
        except Exception:
            icon, color = "--", "white"
        self._append_log(f"[dim]{timestamp}[/dim] [{color}]{icon}[/{color}] {message}")

    @contextmanager
    def thinking(self, message: str = "思考中..."):
        original_status = self._status
        self._status = "THINKING"
        self.add_log(message, "LLM")
        self._update_status_line()

        if UIManager._test_mode:
            sys.__stdout__.write(f"[{message}]\n")
            sys.__stdout__.flush()
            try:
                yield
            finally:
                self._status = original_status
            return

        try:
            yield
        finally:
            self._status = original_status
            self._update_status_line()

    def print_tool_start(self, tool_name: str, args: Dict[str, Any] = None):
        self.increment_tool_count()
        if args:
            args_str = self._format_tool_args(args)
            line = f"[dim][主][/dim] [cyan]>[/cyan] [bold]{tool_name}[/bold] [dim]{args_str}[/dim]"
            self._append_tool_activity(line)
        else:
            line = f"[dim][主][/dim] [cyan]>[/cyan] [bold]{tool_name}[/bold]"
            self._append_tool_activity(line)

    def print_tool_start_log(self, tool_name: str, args: Dict[str, Any] = None):
        preview = self._format_tool_args(args)
        self.add_log(f"{tool_name} {preview}".strip(), "TOOL")

    def print_tool_result(self, tool_name: str, result: str, success: bool = True):
        icon = "ok" if success else "x"
        color = "green" if success else "red"
        summary = self._summarize_tool_result(result)
        line = f"[dim][主][/dim] [{color}]{icon}[/{color}] [bold]{tool_name}[/bold] [dim]{summary}[/dim]"
        self._append_tool_activity(line)
        if not success:
            for line in self._format_tool_result_lines(result)[1:3]:
                detail = f"[red dim]└[/red dim] {line}"
                self._append_tool_activity(detail)

    def print_tool_result_log(self, tool_name: str, success: bool = True):
        self.add_log(f"{tool_name} {'OK' if success else 'FAILED'}", "TOOL" if success else "ERROR")

    def print_header(self, model: str, generation: int = None, tools_count: int = 0):
        if generation is not None:
            self._iterations = generation
        if tools_count:
            self._tool_count = tools_count
        self._append_conversation(
            f"[bold]Vibelution[/bold] [dim]模型：[/dim] {model}  [dim]工具：[/dim] {tools_count}  "
            f"[dim]时间：[/dim] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        self._append_conversation("")

    def print_warning(self, message: str):
        self._append_conversation(f"[yellow]![/yellow] {message}")
        self.add_log(message, "WARN")

    def print_error(self, message: str, exc_info: str = None):
        self._append_conversation(f"[red]!! {message}[/red]")
        self.add_log(message, "ERROR")
        if exc_info:
            self._append_conversation(f"[red dim]{exc_info}[/red dim]")

    def print_success(self, message: str):
        self._append_conversation(f"[green]+[/green] {message}")
        self.add_log(message, "SUCCESS")

    def print_section(self, title: str):
        self._append_conversation(f"[bold cyan]--- {title} ---[/bold cyan]")

    def print_markdown(self, markdown_text: str):
        self._safe_console_render(Markdown(markdown_text), fallback_text=markdown_text)

    def print_code(self, code: str, language: str = "python"):
        self._safe_console_render(
            Syntax(code, language, theme="monokai", line_numbers=True),
            fallback_text=code,
        )

    def print_table(self, data: List[Dict[str, Any]], columns: List[str] = None):
        if not data:
            return
        if columns is None:
            columns = list(data[0].keys())
        table = Table(box=ROUNDED)
        for col in columns:
            table.add_column(col, style="cyan")
        for row in data:
            table.add_row(*[str(row.get(col, "")) for col in columns])
        fallback_lines = [" | ".join(columns)]
        fallback_lines.extend(" | ".join(str(row.get(col, "")) for col in columns) for row in data)
        self._safe_console_render(table, fallback_text="\n".join(fallback_lines))

    def print_task_checklist(self, tasks: List[Dict[str, Any]]):
        tree = Tree("[bold yellow]Tasks[/bold yellow]")
        for task in tasks:
            title = task.get("title", "")
            done = task.get("done", False)
            icon = "[green]+[/green]" if done else "[dim]o[/dim]"
            tree.add(f"{icon} {title}")
        fallback_lines = ["Tasks"]
        fallback_lines.extend(
            f"{'[x]' if task.get('done', False) else '[ ]'} {task.get('title', '')}" for task in tasks
        )
        self._safe_console_render(tree, fallback_text="\n".join(fallback_lines))

    def print_progress(self, description: str, completed: int, total: int):
        pct = completed / total if total > 0 else 0
        self._append_conversation(f"{description} {int(pct * 100)}%")

    def print_lobster_status(self, status: str = "happy", message: str = ""):
        self._append_conversation(f"[cyan]{self.avatar.get_art(status)}[/cyan]")
        if message:
            self._append_conversation(f"[dim]{message}[/dim]")

    def print_pet_status(self):
        try:
            text = self.pet.get_full_status_text()
            self._safe_console_render(
                Panel(text, title="宠物", border_style="magenta", box=ASCII2),
                fallback_text=str(text),
            )
        except Exception:
            self._safe_console_render("[dim]宠物系统暂时不可用[/dim]", fallback_text="宠物系统暂时不可用")

    def print_welcome_panel(self):
        try:
            from config import get_config

            model = get_config().llm.get_profile(role="primary").model
        except Exception:
            model = "?"
        self.print_header(model)
        self._append_conversation("[dim]输入任务，或打开工作台菜单开始。[/dim]")

    def clear(self):
        self.console.clear()


_ui: Optional[UIManager] = None


def get_ui() -> UIManager:
    global _ui
    if _ui is None:
        _ui = UIManager()
    return _ui


def ui_print_header(model: str, generation: int = None):
    get_ui().print_header(model, generation)


def ui_thinking(message: str = "思考中..."):
    return get_ui().thinking(message)


def ui_print_tool(tool_name: str, args: Dict = None, result: str = None, success: bool = True):
    if result is None:
        get_ui().print_tool_start(tool_name, args)
    else:
        get_ui().print_tool_result(tool_name, result, success)


def ui_warning(message: str):
    get_ui().print_warning(message)


def ui_error(message: str, exc_info: str = None):
    get_ui().print_error(message, exc_info)


def ui_success(message: str):
    get_ui().print_success(message)


def ui_log(message: str, level: str = "INFO"):
    get_ui().add_log(message, level)


def ui_update_status(
    status: str,
    generation: int = None,
    goal: str = None,
    iterations: int = None,
    tool_count: int = None,
    input_tokens: int = None,
    output_tokens: int = None,
):
    get_ui().update_status(
        status,
        generation,
        goal,
        iterations,
        tool_count,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def ui_task_board(markdown: str):
    get_ui().set_task_board(markdown)


def ui_lobster_status(status: str = "happy", message: str = ""):
    get_ui().print_lobster_status(status, message)


def ui_welcome():
    get_ui().print_welcome_panel()


def ui_print_welcome():
    get_ui().print_welcome_panel()


def run_interactive_mode(agent) -> bool:
    ui = get_ui()
    while True:
        try:
            user_input = input("Agent > ").strip()
            if not user_input:
                ui.start_live()
                agent.run_loop()
                ui.stop_live()
                break
            if user_input.lower() in ("/quit", "/exit", "/q"):
                print("Goodbye.")
                return True
            ui.start_live()
            agent.run_loop(initial_prompt=user_input)
            ui.stop_live()
        except KeyboardInterrupt:
            print("\nInterrupted.")
            return False
        except EOFError:
            return False
    return True
