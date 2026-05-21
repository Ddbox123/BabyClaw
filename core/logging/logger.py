"""
日志模块 - 统一管理 Agent 运行时的调试日志和对话记录

从 agent.py 中提取的日志组件，提供：
- DebugLogger: 基于 Rich 的 Claude Code 级调试输出
- ConversationLogger: 实时对话记录到 JSON 文件

注意：
- 统一的日志接口请使用 core.unified_logger.UnifiedLogger
- 此模块保留 DebugLogger 和 ConversationLogger 独立功能

使用方式:
    # 统一日志（推荐）
    from core.unified_logger import logger
    logger.log_llm_request(messages)

    # 调试日志
    from core.logger import debug
    debug.info("信息")
    debug.tool_start("read_file", {"path": "test.py"})

    # 向后兼容的 ConversationLogger
    from core.logger import conversation_logger
    conversation_logger.log_llm_response("response content")
"""

from __future__ import annotations

import os
import re
import threading
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, Callable

# ============================================================================
# UI 桥接 — 延迟获取 UIManager（打破循环导入）
# ============================================================================

def _get_ui():
    """获取 UI 实例（每次调用时解析，打破循环导入）"""
    try:
        from core.ui.cli_ui import get_ui
        return get_ui()
    except ImportError:
        return None


# ============================================================================
# 共享的 Token Console
# ============================================================================

_token_console = None


def _get_token_console():
    """获取共享的 Token Console（与 UIManager Live 共享同一 Console 实例）"""
    global _token_console
    if _token_console is None:
        from rich.console import Console
        ui = _get_ui()
        if ui is not None:
            _token_console = ui.console
        else:
            _token_console = Console(force_terminal=True)
    return _token_console


def reset_token_console():
    """重置 token console 实例（在 Live 重启时调用）"""
    global _token_console
    _token_console = None


# ============================================================================
# DebugLogger - 统一调试日志系统
# ============================================================================

class DebugLogger:
    """
    统一调试日志系统 - 基于 rich 的 Claude Code 级输出

    特性：
    - 带时间戳的格式化输出
    - 分类标签便于识别
    - 错误时自动附带上下文和堆栈
    - 线程安全
    - 可控制详细程度
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, '_initialized', False):
            return
        self._initialized = True
        self.verbose = True
        self.show_timestamps = True
        self._indent_level = 0
        self._indent_char = "  "
        self._file_handle = None

    def _timestamp(self) -> str:
        """获取带毫秒的时间戳"""
        now = datetime.now()
        return now.strftime("%H:%M:%S.%f")[:-3]

    def _indent(self) -> str:
        """获取当前缩进"""
        return self._indent_char * self._indent_level

    def _format(self, tag: str, msg: str) -> str:
        """格式化日志消息"""
        parts = []
        if self.show_timestamps:
            parts.append(f"[{self._timestamp()}]")
        parts.append(f"[{tag}]")
        parts.append(f"{self._indent()}{msg}")
        return " ".join(parts)

    def _ui_or_none(self):
        """获取 UI 实例，未就绪时返回 None"""
        return _get_ui()

    def start_session(self, session_id: str):
        """开始会话 — 打开 debug 日志文件"""
        try:
            log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'log_info')
            os.makedirs(log_dir, exist_ok=True)
            log_path = os.path.join(log_dir, f'debug_{session_id}.log')
            self._file_handle = open(log_path, 'a', encoding='utf-8', buffering=1)
            self._write_file("SYS", f"=== Debug session started: {session_id} ===")
        except Exception:
            self._file_handle = None

    def end_session(self):
        """结束会话 — 关闭 debug 日志文件"""
        if self._file_handle:
            try:
                self._write_file("SYS", "=== Debug session ended ===")
                self._file_handle.close()
            except Exception:
                pass
            self._file_handle = None

    def _write_file(self, tag: str, msg: str):
        """写入 debug 日志文件"""
        if self._file_handle:
            try:
                ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                self._file_handle.write(f"[{ts}] [{tag}] {msg}\n")
                self._file_handle.flush()
            except Exception:
                pass

    def debug(self, msg: str, tag: str = "DEBUG"):
        """调试信息"""
        self._write_file("DEBUG", msg)
        try:
            conversation_logger.log_debug(tag, msg, "DEBUG")
        except Exception:
            pass
        if self.verbose and (ui := self._ui_or_none()):
            ui.add_log(msg, "DEBUG")

    def info(self, msg: str, tag: str = "INFO"):
        """一般信息"""
        self._write_file("INFO", msg)
        try:
            conversation_logger.log_debug(tag, msg, "INFO")
        except Exception:
            pass
        if ui := self._ui_or_none():
            ui.add_log(msg, "INFO")

    def success(self, msg: str, tag: str = "OK"):
        """成功信息"""
        self._write_file("OK", msg)
        try:
            conversation_logger.log_debug(tag, msg, "OK")
        except Exception:
            pass
        if ui := self._ui_or_none():
            ui.add_log(msg, "SUCCESS")

    def warning(self, msg: str, tag: str = "WARN"):
        """警告信息"""
        self._write_file("WARN", msg)
        try:
            conversation_logger.log_debug(tag, msg, "WARN")
        except Exception:
            pass
        if ui := self._ui_or_none():
            ui.print_warning(msg)

    def error(self, msg: str, tag: str = "ERROR", exc_info: Optional[str] = None):
        """错误信息"""
        self._write_file("ERROR", msg)
        if exc_info:
            self._write_file("ERROR", exc_info)
        try:
            conversation_logger.log_debug(tag, f"{msg}\n{exc_info}" if exc_info else msg, "ERROR")
        except Exception:
            pass
        if ui := self._ui_or_none():
            ui.print_error(msg, exc_info)

    def system(self, msg: str, tag: str = "SYS"):
        """系统信息"""
        self._write_file("SYS", msg)
        try:
            conversation_logger.log_debug(tag, msg, "SYS")
        except Exception:
            pass
        if ui := self._ui_or_none():
            ui.add_log(msg, "SYS")

    def tool(self, name: str, status: str, details: str = ""):
        """工具执行日志"""
        self._write_file("TOOL", f"{name} {status} {details}")
        try:
            conversation_logger.log_debug("TOOL", f"{name} {status} {details}", "TOOL")
        except Exception:
            pass
        if ui := self._ui_or_none():
            ui.add_log(f"Tool: {name} {status} {details}", "TOOL")

    def llm(self, msg: str, details: str = ""):
        """LLM 调用日志"""
        self._write_file("LLM", f"{msg} {details}")
        try:
            conversation_logger.log_debug("LLM", f"{msg} {details}", "LLM")
        except Exception:
            pass
        if ui := self._ui_or_none():
            ui.add_log(f"{msg} {details}", "LLM")

    def llm_response(self, content: str, prefix: str = "LLM 回复"):
        """打印 LLM 响应摘要到日志面板"""
        preview = content[:80] if content else ""
        self._write_file("LLM", f"{prefix}: {preview}...")
        try:
            conversation_logger.log_debug("LLM", f"{prefix}: {preview}", "LLM")
        except Exception:
            pass
        ui = _get_ui()
        if ui is None:
            return
        ui.add_log(f"{prefix}: {preview}...", "LLM")

    def llm_thinking(self, content: str):
        """打印 LLM 的思考过程 — 完整写入内容区"""
        ui = _get_ui()
        if ui is None:
            return
        ui.stream_thought(content, done=True)

    def llm_thinking_log(self, content: str):
        """打印 LLM 思考摘要 — 仅写入日志面板"""
        ui = _get_ui()
        if ui is None:
            return
        ui.add_log(f"Thinking: {content[:60]}...", "THINK")

    def tool_start(self, tool_name: str, args: dict):
        """打印工具开始调用 — 内容区 + 日志区"""
        self._write_file("TOOL", f"START {tool_name} args={str(args)[:200]}")
        try:
            conversation_logger.log_debug("TOOL", f"START {tool_name} args={args}", "TOOL")
        except Exception:
            pass
        ui = _get_ui()
        if ui is None:
            return
        ui.print_tool_start(tool_name, args)
        ui.print_tool_start_log(tool_name, args)

    def tool_result(self, tool_name: str, result: str, success: bool = True):
        """打印工具执行结果 — 内容区 + 日志区"""
        status = "OK" if success else "FAIL"
        self._write_file("TOOL", f"RESULT {tool_name} {status} len={len(result) if result else 0}")
        try:
            conversation_logger.log_debug("TOOL", f"RESULT {tool_name} {status} len={len(result) if result else 0}", "TOOL")
        except Exception:
            pass
        ui = _get_ui()
        if ui is None:
            return
        ui.print_tool_result(tool_name, result, success)
        ui.print_tool_result_log(tool_name, success)

    def session_start(self, model: str, generation: int = 1):
        """开始会话 — 打印头部信息到控制台"""
        ui = _get_ui()
        if ui:
            ui.print_header(model, generation)

    def session_start_log(self, model: str, generation: int = 1):
        """开始会话 — 仅写入日志面板"""
        ui = _get_ui()
        if ui:
            ui.update_status("AWAKENING", generation=generation)

    def turn_end(self, turn_num: int, tool_count: int = 0):
        """结束一轮对话"""
        self._write_file("TURN", f"Turn {turn_num} complete | Tools: {tool_count}")
        try:
            conversation_logger.log_debug("TURN", f"Turn {turn_num} complete | Tools: {tool_count}", "TURN")
        except Exception:
            pass
        ui = _get_ui()
        if ui:
            ui.add_log(f"Turn {turn_num} complete | Tools: {tool_count}", "TURN")

    def section(self, title: str):
        """分节标题"""
        ui = _get_ui()
        if ui is None:
            return
        ui.add_content(f"\n[dim]--- {title} ---[/dim]")

    def divider(self, char: str = "-", length: int = 60):
        """分隔线"""
        ui = _get_ui()
        if ui is None:
            return
        ui.add_content(char * length)

    def kv(self, key: str, value: str):
        """键值对输出"""
        ui = _get_ui()
        if ui is None:
            return
        ui.add_content(f"  [dim]{key}[/dim]: {value}")

    def banner(self, title: str):
        """横幅"""
        ui = _get_ui()
        if ui is None:
            return
        ui.add_content(f"\n[dim]{chr(9472) * 50}[/dim]")
        ui.add_content(f"[bold]  {title}[/bold]")
        ui.add_content(f"[dim]{chr(9472) * 50}[/dim]\n")

    def indent(self):
        """增加缩进"""
        self._indent_level += 1

    def dedent(self):
        """减少缩进"""
        self._indent_level = max(0, self._indent_level - 1)

    def turn_start(self, turn_num: int, context: str = ""):
        """开始新的轮次"""
        ui = _get_ui()
        if ui is None:
            return
        ui.add_content(f"\n[dim]-- Turn {turn_num} --[/dim]")
        if context:
            ui.add_content(f"  {context}")
        ui.add_content("")


# 全局 DebugLogger 实例
debug = DebugLogger()

# 统一导出：from core.logging import logger
# 等价于 from core.logging.logger import debug
# 方便所有模块统一导入：logger.info(...) / logger.debug(...) / logger.error(...)
logger = debug


# ============================================================================
# ConversationLogger - 实时对话记录器
# ============================================================================

class ConversationLogger:
    """
    实时对话记录器 - 将 LLM 对话记录到文件

    特性：
    - 实时写入文件，不丢失任何记录
    - 按会话组织，方便调试和回溯
    - 包含完整的消息内容、工具调用、Token 用量等
    - 线程安全
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, '_initialized', False):
            return
        self._initialized = True
        self._session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._session_metadata: Dict[str, Any] = {}
        self._session_file_stem = ""
        self._actor = "main"
        self._actor_label = ""
        self._parent_turn = None
        self._delegation_depth = 0
        self._inherited_session = False
        self._log_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "log_info"
        )
        self._apply_env_context()
        self._ensure_log_dir()
        self._current_session_file = None
        self._turn_count = 0
        self._session_active = False

    def _apply_env_context(self):
        """从环境变量恢复跨进程日志上下文。"""
        actor = str(os.environ.get("VIBELUTION_LOG_ACTOR", "main") or "main").strip().lower()
        self._actor = actor or "main"
        self._actor_label = str(os.environ.get("VIBELUTION_LOG_ACTOR_LABEL", "") or "").strip()

        inherited_session_id = str(os.environ.get("VIBELUTION_LOG_SESSION_ID", "") or "").strip()
        if inherited_session_id:
            self._session_id = inherited_session_id
            self._inherited_session = True

        try:
            parent_turn = os.environ.get("VIBELUTION_LOG_PARENT_TURN", "")
            self._parent_turn = int(parent_turn) if str(parent_turn).strip() else None
        except (TypeError, ValueError):
            self._parent_turn = None

        try:
            self._delegation_depth = int(os.environ.get("VIBELUTION_SUBAGENT_DEPTH", "0") or 0)
        except (TypeError, ValueError):
            self._delegation_depth = 0

    def _ensure_log_dir(self):
        """确保日志目录存在"""
        os.makedirs(self._log_dir, exist_ok=True)

    @staticmethod
    def _compact_log_fragment(text: Any, *, limit: int = 36) -> str:
        raw = str(text or "").strip()
        if not raw:
            return ""

        pieces: list[str] = []
        last_was_sep = False
        for char in raw:
            if char.isalnum():
                pieces.append(char)
                last_was_sep = False
                continue
            if char in {"-", "_"}:
                if pieces and not last_was_sep:
                    pieces.append("_")
                    last_was_sep = True
                continue
            if char.isspace() or char in {"/", "\\", ":", ".", ",", "|", "，", "。", "、"}:
                if pieces and not last_was_sep:
                    pieces.append("_")
                    last_was_sep = True
                continue
            if pieces and not last_was_sep:
                pieces.append("_")
                last_was_sep = True

        slug = re.sub(r"_+", "_", "".join(pieces)).strip("_")
        if not slug:
            return ""
        return slug[:limit].strip("_")

    def _build_session_label(self) -> str:
        metadata = dict(self._session_metadata or {})
        topic_keys = (
            "agent_mode",
            "conversation_topic",
            "session_topic",
            "title",
            "goal",
            "summary",
        )
        fragments: list[str] = []
        for key in topic_keys:
            value = metadata.get(key)
            if not value:
                continue
            fragment = self._compact_log_fragment(value, limit=28)
            if fragment:
                fragments.append(fragment)
            if len(fragments) >= 2:
                break

        actor_label = self._compact_log_fragment(self._actor_label, limit=18)
        if actor_label:
            fragments.insert(0, actor_label)

        if not fragments and not self._inherited_session:
            fallback_parts = [
                self._compact_log_fragment(metadata.get("mode"), limit=18),
            ]
            fragments = [part for part in fallback_parts if part]

        fragments = [fragment for fragment in fragments if fragment]
        if not fragments:
            return ""
        return "__".join(fragments)

    def _get_session_file(self) -> str:
        """获取当前会话的日志文件路径"""
        if self._current_session_file is None:
            if self._inherited_session:
                stem = f"conversation_{self._session_id}"
            else:
                if not self._session_file_stem:
                    label = self._build_session_label()
                    if label:
                        self._session_file_stem = f"conversation_{self._session_id}__{label}"
                    else:
                        self._session_file_stem = f"conversation_{self._session_id}"
                stem = self._session_file_stem
            self._current_session_file = os.path.join(
                self._log_dir, f"{stem}.jsonl"
            )
        return self._current_session_file

    def _get_payload_dir(self) -> Path:
        payload_dir = Path(self._log_dir) / "payloads" / self._session_id
        payload_dir.mkdir(parents=True, exist_ok=True)
        return payload_dir

    @staticmethod
    def _make_preview(text: str, head: int = 280, tail: int = 180) -> str:
        raw = str(text or "")
        if len(raw) <= head + tail + 20:
            return raw
        return raw[:head] + "\n...\n" + raw[-tail:]

    def _spill_text_payload(self, kind: str, text: str, *, turn: Optional[int] = None, ext: str = "txt") -> str:
        payload_dir = self._get_payload_dir()
        safe_kind = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in kind)[:48]
        turn_label = f"turn_{turn if turn is not None else 'session'}"
        path = payload_dir / f"{turn_label}_{safe_kind}.{ext}"
        path.write_text(str(text or ""), encoding="utf-8")
        try:
            return str(path.relative_to(Path(self._log_dir)))
        except Exception:
            return str(path)

    def _pack_text_payload(
        self,
        *,
        field_name: str,
        text: str,
        kind: str,
        turn: Optional[int] = None,
        inline_limit: int = 600,
        ext: str = "txt",
    ) -> Dict[str, Any]:
        raw = str(text or "")
        payload = {
            f"{field_name}_length": len(raw),
            f"{field_name}_preview": self._make_preview(raw),
            f"{field_name}_inlined": len(raw) <= inline_limit,
        }
        if len(raw) <= inline_limit:
            payload[field_name] = raw
        else:
            payload[f"{field_name}_ref"] = self._spill_text_payload(kind, raw, turn=turn, ext=ext)
        return payload

    def _timestamp(self) -> str:
        """获取 ISO 格式的时间戳"""
        return datetime.now().isoformat(timespec="milliseconds")

    def _write(self, record: dict):
        """写入单条记录到文件（实时刷出）"""
        if not self._session_active:
            return
        try:
            record = dict(record)
            record.setdefault("session_id", self._session_id)
            record.setdefault("actor", self._actor)
            if self._actor_label:
                record.setdefault("actor_label", self._actor_label)
            if self._parent_turn is not None:
                record.setdefault("parent_turn", self._parent_turn)
            if self._delegation_depth:
                record.setdefault("delegation_depth", self._delegation_depth)
            with open(self._get_session_file(), "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                f.flush()
        except Exception as e:
            print(f"[ConversationLogger] 写入失败: {e}")

    def start_session(self, metadata: dict = None):
        """记录会话开始"""
        self._session_metadata = dict(metadata or {})
        self._session_file_stem = ""
        self._session_active = True
        record = {
            "type": "session_attach" if self._actor != "main" else "session_start",
            "timestamp": self._timestamp(),
            "session_id": self._session_id,
            "metadata": metadata or {},
            "session_label": self._build_session_label(),
        }
        self._write(record)

    def log_external_request(self, content: str):
        """记录外部任务输入"""
        self._turn_count += 1
        record = {
            "type": "external_request",
            "turn": self._turn_count,
            "timestamp": self._timestamp(),
        }
        record.update(
            self._pack_text_payload(
                field_name="content",
                text=content,
                kind="external_request",
                turn=self._turn_count,
                inline_limit=800,
            )
        )
        self._write(record)

    def log_llm_request(self, messages: list, model: str = None, iteration: int = 0):
        """记录发送给 LLM 的请求，同时实时显示输入 token 数"""
        msg_summaries = []
        total_input_tokens = 0
        try:
            from tools.token_manager import estimate_messages_tokens

            total_input_tokens = max(0, int(estimate_messages_tokens(messages) or 0))
        except Exception:
            total_input_tokens = 0

        for msg in messages:
            # 处理 dict 格式消息（如 build_system_message 返回的格式）
            if isinstance(msg, dict):
                msg_type = msg.get("role", "unknown")
                content_raw = msg.get("content", "")
                # content 可能是 content_blocks 列表
                if isinstance(content_raw, list):
                    text = "\n\n".join(
                        block.get("text", "") for block in content_raw
                        if isinstance(block, dict)
                    )
                else:
                    text = str(content_raw)
            else:
                msg_type = getattr(msg, "type", "unknown")
                content_raw = getattr(msg, "content", "")
                text = str(content_raw) if not isinstance(content_raw, str) else content_raw

            payload = {"type": msg_type}
            payload.update(
                self._pack_text_payload(
                    field_name="content",
                    text=text,
                    kind=f"llm_request_{msg_type}_{len(msg_summaries)}",
                    turn=self._turn_count,
                    inline_limit=500,
                )
            )
            msg_summaries.append(payload)

        # 通过 UI 显示 token 数
        ui = _get_ui()
        if ui:
            ui.add_log(f"TOKEN 输入: {total_input_tokens} | 消息: {len(messages)} | 模型: {model or '?'}", "TOKEN")

        record = {
            "type": "llm_request",
            "turn": self._turn_count,
            "timestamp": self._timestamp(),
            "iteration": iteration,
            "message_count": len(messages),
            "messages": msg_summaries,
            "model": model,
            "input_tokens": total_input_tokens,
        }
        self._write(record)

    def log_llm_response(self, response_content: str, raw_response: str = None,
                         input_tokens: int = 0, output_tokens: int = 0, tool_call_count: int = 0):
        """记录 LLM 的原始响应"""
        effective_raw = raw_response if raw_response is not None else response_content
        record = {
            "type": "llm_response",
            "turn": self._turn_count,
            "timestamp": self._timestamp(),
            "raw_length": len(effective_raw) if effective_raw else 0,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "tool_call_count": tool_call_count,
        }
        record.update(
            self._pack_text_payload(
                field_name="content",
                text=response_content,
                kind="llm_response",
                turn=self._turn_count,
                inline_limit=700,
            )
        )
        if raw_response:
            record.update(
                self._pack_text_payload(
                    field_name="raw_response",
                    text=raw_response,
                    kind="llm_response_raw",
                    turn=self._turn_count,
                    inline_limit=500,
                )
            )
        self._write(record)

    def log_tool_call(
        self,
        tool_name: str,
        tool_args: dict,
        tool_result: str = None,
        status: str = "success",
        tool_call_id: str = None,
    ):
        """记录工具调用"""
        record = {
            "type": "tool_call",
            "turn": self._turn_count,
            "timestamp": self._timestamp(),
            "tool_name": tool_name,
            "tool_args": tool_args,
            "tool_call_id": tool_call_id,
            "status": status,
        }
        if tool_result is not None:
            record.update(
                self._pack_text_payload(
                    field_name="tool_result",
                    text=tool_result,
                    kind=f"tool_result_{tool_name}",
                    turn=self._turn_count,
                    inline_limit=700,
                )
            )
        else:
            record["tool_result_length"] = 0
        self._write(record)

    def log_llm_intent(self, intent: str, content_preview: str = None):
        """记录 LLM 的意图/思考"""
        record = {
            "type": "llm_intent",
            "turn": self._turn_count,
            "timestamp": self._timestamp(),
            "intent": intent,
            "content_preview": (
                content_preview[:300] if content_preview and len(content_preview) > 300
                else content_preview
            ),
        }
        self._write(record)

    def log_compression(self, before_tokens: int, after_tokens: int, saved_tokens: int):
        """记录上下文压缩"""
        record = {
            "type": "compression",
            "turn": self._turn_count,
            "timestamp": self._timestamp(),
            "before_tokens": before_tokens,
            "after_tokens": after_tokens,
            "saved_tokens": saved_tokens,
            "ratio": f"{(saved_tokens / before_tokens * 100):.1f}%" if before_tokens > 0 else "0%",
        }
        self._write(record)

    def log_action(self, action: str, details: dict = None):
        """记录特殊动作（restart/hibernated/skip 等）"""
        record = {
            "type": "action",
            "turn": self._turn_count,
            "timestamp": self._timestamp(),
            "action": action,
            "details": details or {},
        }
        self._write(record)

    def log_error(self, error_type: str, error_msg: str, traceback: str = None, details: dict = None):
        """记录错误"""
        record = {
            "type": "error",
            "turn": self._turn_count,
            "timestamp": self._timestamp(),
            "error_type": error_type,
            "error_msg": error_msg,
            "traceback": traceback,
        }
        if details:
            record["details"] = details
        self._write(record)

    def log_system_prompt(self, prompt_text: str):
        """记录完整系统提示词"""
        record = {
            "type": "system_prompt",
            "turn": self._turn_count,
            "timestamp": self._timestamp(),
        }
        record.update(
            self._pack_text_payload(
                field_name="content",
                text=prompt_text,
                kind="system_prompt",
                turn=self._turn_count,
                inline_limit=700,
            )
        )
        self._write(record)

    def log_debug(self, tag: str, message: str, level: str = "INFO"):
        """记录 debug/warning/info/system 级别事件"""
        record = {
            "type": "debug",
            "turn": self._turn_count,
            "timestamp": self._timestamp(),
            "level": level,
            "tag": tag,
            "message": message,
        }
        self._write(record)

    def log_subagent_stream(
        self,
        stream: str,
        text: str,
        *,
        task_type: str = "",
        goal: str = "",
    ):
        """记录子 agent 实时输出流，便于与正式事件对齐追踪。"""
        record = {
            "type": "subagent_stream",
            "turn": self._turn_count,
            "timestamp": self._timestamp(),
            "stream": str(stream or "").strip().lower() or "stdout",
            "task_type": task_type or "",
            "goal_preview": (goal or "")[:200],
            "actor": "subagent",
        }
        record.update(
            self._pack_text_payload(
                field_name="content",
                text=text,
                kind=f"subagent_stream_{stream or 'stdout'}",
                turn=self._turn_count,
                inline_limit=500,
            )
        )
        self._write(record)

    def log_token_usage(self, input_tokens: int, output_tokens: int, turn: int = 0):
        """记录 token 用量"""
        record = {
            "type": "token_usage",
            "turn": turn or self._turn_count,
            "timestamp": self._timestamp(),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        }
        self._write(record)

    def log_turn_end(self, turn: int, stats: dict = None):
        """记录轮次汇总"""
        stats_payload = stats or {}
        summary_record = {
            "type": "round_summary",
            "turn": turn,
            "timestamp": self._timestamp(),
            "summary": {
                "session_id": self._session_id,
                "actor": self._actor,
                "actor_label": self._actor_label,
                "parent_turn": self._parent_turn,
                "delegation_depth": self._delegation_depth,
                "stats": stats_payload,
            },
        }
        self._write(summary_record)
        record = {
            "type": "turn_end",
            "turn": turn,
            "timestamp": self._timestamp(),
            "stats": stats_payload,
        }
        self._write(record)

    def end_session(self, summary: dict = None):
        """记录会话结束"""
        record = {
            "type": "session_detach" if self._actor != "main" else "session_end",
            "timestamp": self._timestamp(),
            "session_id": self._session_id,
            "total_turns": self._turn_count,
            "summary": summary or {},
        }
        self._write(record)

    def new_session(self):
        """开始新的会话（生成新的 session_id）"""
        if not self._inherited_session:
            self._session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._current_session_file = None
        self._session_file_stem = ""
        self._session_metadata = {}
        self._turn_count = 0
        self._session_active = True

    @property
    def _current_turn(self) -> int:
        """获取当前轮次编号"""
        return self._turn_count


# 全局 ConversationLogger 实例
conversation_logger = ConversationLogger()


# ============================================================================
# 便捷函数
# ============================================================================

def get_logger() -> DebugLogger:
    """获取调试日志实例"""
    return debug


def get_conversation_logger() -> ConversationLogger:
    """获取对话记录器实例"""
    return conversation_logger
