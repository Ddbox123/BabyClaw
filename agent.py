import os
import json
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ============================================================================
# 导入配置
# ============================================================================
from config import AppConfig
from config.settings import get_config

# ============================================================================
# 导入日志模块
# ============================================================================
from core.logging.logger import debug as _debug_logger
from core.logging.unified_logger import logger
from core.logging.setup import setup_logging, print_evolution_time as _print_evolution_time_core

# ============================================================================
# 导入核心模块（Core First）
# ============================================================================
from core.infrastructure.state import AgentState, get_state_manager
from core.infrastructure.event_bus import get_event_bus
from core.infrastructure.tool_result import truncate_result  # noqa: F401
from core.infrastructure.tool_result import (
    compact_tool_output_for_diagnosis,
    infer_result_from_tool_outputs,
)
from core.infrastructure.security import get_security_validator
from core.infrastructure.agent_session import get_session_state
from core.infrastructure.tool_executor import get_tool_executor
from core.infrastructure.git_memory import get_git_memory_service
from core.infrastructure.llm_utils import (
    build_system_message,
    MAX_CONSECUTIVE_FAILURES,
    parse_tool_args,
    plan_llm_recovery,
)
from core.infrastructure.cli_utils import create_config_from_args, parse_args, should_launch_workbench
from core.infrastructure.boot_pipeline import (
    configure_console_encoding,
    initialize_ui_for_run,
    run_agent_main,
    run_preflight_doctor,
    set_ui_test_mode,
)

# LangChain 核心组件
from langchain_core.messages import AIMessage, AIMessageChunk, SystemMessage, ToolMessage

from core.infrastructure.runtime_input import (
    build_chat_user_message,
    build_external_request_message,
    build_runtime_notice_message,
)
from core.evaluation.chat_dataset_capture import ChatDatasetCaptureService
from core.evaluation.chat_segmenter import ChatTurnRecord
from core.chat.chat_result_contract import build_chat_coding_result_contract

from core.llm import get_llm_client, discover_model, doctor_llm_profile

# 导入工具
from tools import Key_Tools
from tools.token_manager import (
    EnhancedTokenCompressor, estimate_messages_tokens, estimate_tokens_precise,
    is_compression_requested, consume_compression_request, request_compression,
)
from tools.compression_strategy import CompressionLevel, get_compression_strategy
from tools.memory_tools import get_current_goal
from tools.rebirth_tools import handle_restart_request  # noqa: F401
from tools.agent_tools import set_subagent_stream_sink  # noqa: F401

# 导入 CLI UI
from core.ui.cli_ui import get_ui, ui_error
from core.ui.workbench import AgentWorkbenchShell
from core.ui.token_display import print_tokens
from core.prompt_manager import (
    build_restart_focus_state_memory,
    build_state_memory_key,
    compose_state_memory,
    get_prompt_manager,
    to_string,
)
from core.prompt_manager.task_analyzer import get_task_analyzer
from core.orchestration.delegation_governor import DelegationGovernor
from core.orchestration.agent_modes import (
    AgentMode,
    ModePolicy,
    looks_like_explicit_evolution_request,
    normalize_agent_mode,
    resolve_mode_policy,
)
from core.orchestration.round_state import RoundStateController
from core.orchestration.response_processor import ResponseProcessor, ResponseProcessingResult
from core.orchestration.response_surface import ResponseSurfaceController
from core.orchestration.turn_outcome import TurnOutcomeController
from core.orchestration.tool_lifecycle import ToolLifecycleBridge
from core.orchestration.subagent_roles import extract_subagent_primary_goal
from core.infrastructure.mental_model import get_mental_model

# 导入宠物系统
from core.pet_system import get_pet_system

# 进化测试提示
EVOLUTION_TEST_PROMPT = "制定重启任务，然后对重启任务打勾，然后运行 `trigger_self_restart_tool` 重启你自己。"
SUBAGENT_RESULT_MARKER = "__VIBELUTION_SUBAGENT_RESULT__"


class TurnStopRequested(Exception):
    """Raised when the active single turn received a web stop request."""

# ============================================================================
# Self-Evolving Agent 主类
# ============================================================================

class SelfEvolvingAgent:
    """
    自我进化 Agent 主类

    基于 LangChain 框架构建，使用 ReAct 风格的 Agent 架构。
    支持定时苏醒，主动思考优化方向。
    """

    def __init__(self, config: Optional[AppConfig] = None, mode: Optional[str] = None) -> None:
        """初始化 Agent 实例"""
        self.config = config or get_config()
        self.name = self.config.agent.name
        self.mode = normalize_agent_mode(mode or getattr(self.config.agent, "default_mode", None))
        self.mode_policy = resolve_mode_policy(self.mode, self.config)

        # API Key 检查
        self.api_key = self.config.get_api_key()
        if not self.api_key:
            provider = self.config.llm.get_provider(role="primary")
            if provider.requires_api_key:
                raise ValueError(
                    "未设置 API Key。\n"
                    "请在 llm.providers.<provider_id>.api_key 中配置，或设置对应环境变量。"
                )
        self.config.set_api_key(self.api_key or "")

        # 创建主要工具
        self.key_tools = Key_Tools.create_llm_facing_tools()
        self.key_tool_maps = {tool.name for tool in self.key_tools}
        self._key_tool_map = {
            tool.name: tool for tool in self.key_tools if getattr(tool, "name", "")
        }
        self._bound_llm_cache: Dict[str, Any] = {}

        # 模型动态发现
        self._effective_max_token_limit = self._init_model_discovery()
        # LLM 初始化（使用工厂）
        self._init_llm()
        # Token 压缩器
        self._init_token_compressor()
        # Prompt 管理器
        self.prompt_manager = get_prompt_manager()

        # 全局状态
        self.global_recent_actions = []
        self.global_consecutive_count = 0
        self._self_modified = False
        self.start_time = datetime.now()

        # 压缩追踪
        self._compression_count_this_turn = 0
        self._last_compression_iteration = 0
        self._compression_min_iteration_gap = 2

        # 网络退避追踪
        self._last_turn_failed = False
        self._consecutive_failed_turns = 0

        # 工作区域
        workspace_dir = getattr(self.config.agent, 'workspace', 'workspace')
        project_root = os.path.dirname(os.path.abspath(__file__))
        self.project_root = project_root
        self.workspace_path = os.path.join(project_root, workspace_dir)
        os.makedirs(self.workspace_path, exist_ok=True)

        # 核心组件
        self.state_manager = get_state_manager()
        self.event_bus = get_event_bus()
        self.tool_executor = get_tool_executor()
        self.security_validator = get_security_validator(project_root)
        self.git_memory = get_git_memory_service()
        self.tool_lifecycle = ToolLifecycleBridge(
            tool_executor_execute=self.tool_executor.execute,
            tool_guard=self._guard_tool_execution,
            tool_result_observer=self._remember_tool_output,
            post_close_action_pending=self._expects_restart_after_transaction_close,
            self_modified=self._self_modified,
        )
        self.delegation_governor = DelegationGovernor(
            spawn_execute=self.tool_executor.execute,
            sync_runtime_state_memory=self._sync_runtime_state_memory,
            ui_getter=get_ui,
            session_getter=get_session_state,
        )
        self.response_processor = ResponseProcessor()

        # 心智模型（元认知引擎 — 必须在 EventBus 之后初始化）
        self.mental_model = get_mental_model(workspace_root=self.workspace_path)
        # 共享 LLM 给感知层（同一实例，不同提示词）
        self.mental_model.set_shared_llm(self.llm_with_tools)

        self._system_prompt_written = False
        self._last_runtime_state_memory = ""
        self._last_runtime_state_memory_key = ""
        self._carryover_state_memory = ""
        self._pending_lifecycle_action: Optional[str] = None
        self._last_llm_error_category: Optional[str] = None
        self._last_llm_error_retryable: bool = False
        self._last_llm_recovery_action: Optional[str] = None
        self._last_llm_error_message: str = ""
        self._last_visible_response_text: str = ""
        self._last_response_tool_calls: int = 0
        self._recent_tool_outputs: List[str] = []
        self._recent_tool_records: List[Dict[str, Any]] = []
        self._active_goal: str = ""
        self._active_turn_messages: Optional[List[Any]] = None
        self._active_turn_goal: str = ""
        self._single_turn_mode_active: bool = False
        self._last_turn_metadata: Dict[str, Any] = {}
        self._turn_interrupt_checker = None
        self._chat_turn_records: List[ChatTurnRecord] = []
        self._active_supervised_case_id: str = ""
        self._pending_supervised_case_id: Optional[str] = None
        self.chat_dataset_capture = ChatDatasetCaptureService(
            project_root=Path(self.project_root),
            config=self.config,
        )
        self._load_previous_session_constraints()

    def _init_model_discovery(self):
        """模型动态发现，返回 effective_max_token_limit"""
        primary_profile_id = self.config.llm.get_role_profile_id("primary")
        doctor = doctor_llm_profile(self.config, primary_profile_id)
        for warning in doctor.warnings:
            _debug_logger.warning(warning, tag="LLM")
        if doctor.errors:
            for item in doctor.errors:
                _debug_logger.error(item, tag="LLM")
        self.model_info = discover_model(self.config, primary_profile_id)
        self._effective_max_token_limit = int(
            self.model_info.context_window * 0.5
        )
        self.config.context_compression.max_token_limit = self._effective_max_token_limit
        self._context_window_limit = int(
            getattr(getattr(self, "model_info", None), "context_window", 0)
            or self._effective_max_token_limit
        )
        try:
            from core.pet_system import get_pet_system
            get_pet_system().update_context_window(self._context_window_limit)
        except Exception:
            pass
        return self._effective_max_token_limit

    def _init_llm(self):
        """初始化统一 LLM client。"""
        llm = get_llm_client(role="primary", config=self.config)
        self._base_llm = llm
        self.llm_with_tools = llm.bind_tools(self.key_tools)
        self._bound_llm_cache = {"default": self.llm_with_tools}

    @staticmethod
    def _restart_allowed_tool_names() -> tuple[str, ...]:
        return (
            "task_create_tool",
            "task_update_tool",
            "task_list_tool",
            "get_current_goal_tool",
            "get_core_context_tool",
            "get_memory_summary_tool",
            "trigger_self_restart_tool",
            "close_evolution_transaction_tool",
        )

    def _get_llm_for_current_mode(
        self,
        *,
        disable_tools: bool = False,
        profile_id: Optional[str] = None,
    ):
        base_llm = getattr(self, "_base_llm", None) or self.llm_with_tools
        if profile_id and profile_id != getattr(base_llm, "profile_id", None):
            base_llm = get_llm_client(profile_id=profile_id, config=self.config)
        if disable_tools:
            return base_llm
        if not self._is_restart_focus_mode():
            if not hasattr(self, "_base_llm"):
                return self.llm_with_tools
            if base_llm is getattr(self, "_base_llm", None):
                return self.llm_with_tools
            return base_llm.bind_tools(self.key_tools)

        if base_llm is not getattr(self, "_base_llm", None):
            allowed_tools = [
                self._key_tool_map[name]
                for name in self._restart_allowed_tool_names()
                if name in self._key_tool_map
            ]
            return base_llm.bind_tools(allowed_tools) if allowed_tools else base_llm
        cached = self._bound_llm_cache.get("restart_focus")
        if cached is not None:
            return cached

        allowed_tools = [
            self._key_tool_map[name]
            for name in self._restart_allowed_tool_names()
            if name in self._key_tool_map
        ]
        if not allowed_tools:
            return self.llm_with_tools

        rebound = self._base_llm.bind_tools(allowed_tools)
        self._bound_llm_cache["restart_focus"] = rebound
        return rebound

    def _should_stream_llm(self) -> bool:
        config = getattr(self, "config", None)
        if config is None:
            return hasattr(self.llm_with_tools, "stream")
        llm_cfg = getattr(config, "llm", None)
        if llm_cfg is not None and hasattr(llm_cfg, "get_profile"):
            return bool(llm_cfg.get_profile(role="primary").streaming)
        return True

    def _sync_runtime_state_memory(self):
        """将会话级短期约束同步到 MEMORY/state_memory。"""
        try:
            runtime_summary = get_session_state().render_runtime_constraints()
            restart_focus = (
                build_restart_focus_state_memory(self._restart_allowed_tool_names())
                if self._is_restart_focus_mode()
                else ""
            )
            summary = compose_state_memory(
                runtime_summary=runtime_summary,
                carryover_state_memory=self._carryover_state_memory,
                restart_focus_state_memory=restart_focus,
            )
            summary_key = build_state_memory_key(summary)
            if summary_key == getattr(self, "_last_runtime_state_memory_key", ""):
                return
            self._last_runtime_state_memory = summary
            self._last_runtime_state_memory_key = summary_key
            if summary:
                self.prompt_manager.update_state_memory(summary, persist=False)
            else:
                self.prompt_manager.clear_state_memory(persist=False)
        except Exception:
            pass

    def _load_previous_session_constraints(self):
        """从最近一次会话分析中恢复下一轮短期约束。"""
        try:
            analyzer = get_task_analyzer(project_root=os.path.dirname(os.path.abspath(__file__)))
            report = analyzer.analyze_evolution_session()
            if not report.next_round_constraints:
                return
            self._carryover_state_memory = analyzer.build_next_round_state_memory(report)
            _debug_logger.info("[Retrospective] 已加载上一会话的短期约束", tag="STATE")
        except Exception:
            self._carryover_state_memory = ""

    def _refresh_retrospective_state_memory(self):
        """根据当前会话日志刷新下一轮短期约束。"""
        try:
            conversation_logger = getattr(logger, "conversation", None)
            if conversation_logger is None:
                return
            session_file = conversation_logger._get_session_file()
            if not session_file or not Path(session_file).exists():
                return
            analyzer = get_task_analyzer(project_root=os.path.dirname(os.path.abspath(__file__)))
            report = analyzer.analyze_evolution_session(session_file=Path(session_file))
            self._carryover_state_memory = (
                analyzer.build_next_round_state_memory(report)
                if report.next_round_constraints
                else ""
            )
            self._sync_runtime_state_memory()
            if self._last_runtime_state_memory:
                self.prompt_manager.update_state_memory(self._last_runtime_state_memory, persist=True)
            else:
                self.prompt_manager.clear_state_memory(persist=True)
        except Exception:
            pass

    def _record_language_drift(self, raw_text: str):
        """语言偏好只由提示词表达，运行时不再强制纠偏。"""
        return

    def _record_inference_activity(self, raw_text: str):
        """在无新增工具动作时记录推理行为，识别诊断漂移。"""
        cleaned = (raw_text or "").strip()
        if not cleaned:
            return
        if cleaned.startswith("<think>") or len(cleaned) > 80:
            session = get_session_state()
            session.note_diagnostic_inference()
            if session.has_diagnostic_drift():
                session.record_blocker(
                    "diagnostic_drift",
                    "连续进行推理但没有新增观测，请先打印最小中间值或验证结果。",
                    "先复现 -> 再观测 -> 再读代码"
                )
            self._sync_runtime_state_memory()

    def _remember_tool_output(self, _tool_call: Dict[str, Any], result: Any, _action: Optional[str]) -> None:
        text = str(result or "").strip()
        tool_name = str((_tool_call or {}).get("name") or "").strip()
        tool_args = parse_tool_args(
            (_tool_call or {}).get("args") or (_tool_call or {}).get("arguments") or {}
        )
        record = {
            "name": tool_name,
            "args": tool_args,
            "action": str(_action or "").strip(),
            "result_preview": compact_tool_output_for_diagnosis(text, max_chars=1200) if text else "",
        }
        self._recent_tool_records.append(record)
        if len(self._recent_tool_records) > 20:
            self._recent_tool_records = self._recent_tool_records[-20:]
        if not text:
            return
        self._recent_tool_outputs.append(compact_tool_output_for_diagnosis(text, max_chars=6000))
        if len(self._recent_tool_outputs) > 6:
            self._recent_tool_outputs = self._recent_tool_outputs[-6:]

    def _build_delegation_request(
        self,
        *,
        goal: str,
        iteration: int,
        total_tool_calls: int,
    ) -> Optional[Dict[str, Any]]:
        governor = self._get_delegation_governor()
        return governor.build_request(
            goal=goal,
            iteration=iteration,
            total_tool_calls=total_tool_calls,
        )

    def _apply_delegation_result(
        self,
        payload: Dict[str, Any],
        result_text: str,
        messages: list,
    ) -> Dict[str, Any]:
        governor = self._get_delegation_governor()
        return governor.apply_result(payload, result_text, messages)

    def _maybe_delegate(
        self,
        *,
        goal: str,
        iteration: int,
        total_tool_calls: int,
        messages: list,
    ) -> Optional[Dict[str, Any]]:
        governor = self._get_delegation_governor()
        return governor.maybe_delegate(
            goal=goal,
            iteration=iteration,
            total_tool_calls=total_tool_calls,
            messages=messages,
        )

    def _get_delegation_governor(self) -> DelegationGovernor:
        governor = getattr(self, "delegation_governor", None)
        if governor is not None:
            return governor

        tool_executor = getattr(self, "tool_executor", None)
        spawn_execute = getattr(tool_executor, "execute", None)
        if spawn_execute is None:
            def spawn_execute(_tool_name: str, _tool_args: dict):
                return ("[错误] delegation governor 未初始化", None)

        governor = DelegationGovernor(
            spawn_execute=spawn_execute,
            sync_runtime_state_memory=self._sync_runtime_state_memory,
            ui_getter=get_ui,
            session_getter=get_session_state,
        )
        self.delegation_governor = governor
        return governor

    def _get_turn_outcome_controller(self) -> TurnOutcomeController:
        controller = getattr(self, "turn_outcome_controller", None)
        if controller is not None:
            return controller

        controller = TurnOutcomeController(
            max_consecutive_failures=MAX_CONSECUTIVE_FAILURES,
            get_attention_snapshot=lambda: get_session_state().get_attention_snapshot(),
        )
        self.turn_outcome_controller = controller
        return controller

    def _get_response_surface_controller(self) -> ResponseSurfaceController:
        controller = getattr(self, "response_surface_controller", None)
        if controller is not None:
            return controller

        controller = ResponseSurfaceController(
            estimate_tokens=estimate_messages_tokens,
            ui_getter=get_ui,
            logger=logger,
            debug_logger=_debug_logger,
            pet_getter=get_pet_system,
            print_tokens=print_tokens,
        )
        self.response_surface_controller = controller
        return controller

    def _expects_restart_after_transaction_close(self) -> bool:
        """当前目标是否明确要求关账成功后继续触发自我重启。"""
        goal = getattr(self, "_active_goal", "") or ""
        return DelegationGovernor.is_full_evolution_goal(goal)

    def _init_token_compressor(self):
        """初始化 Token 压缩器"""
        self.token_compressor = EnhancedTokenCompressor(
            token_budget=self._effective_max_token_limit,
            compression_llm=get_llm_client(role="compression", config=self.config),
        )

    def _compress_messages(self, messages: list, iteration: int, reason: str = ""):
        """执行消息压缩。返回 (messages, should_break)。"""
        ui = get_ui()

        # Guard: 压缩未启用
        if not self.config.context_compression.enabled:
            return messages, False

        # Guard: 消息太少
        if len(messages) <= 4:
            return messages, False

        # Guard: 速率限制
        if self._last_compression_iteration > 0:
            if iteration - self._last_compression_iteration < self._compression_min_iteration_gap:
                return messages, False

        # Guard: 超过最大压缩次数
        max_comp = getattr(self.config.context_compression, "max_compressions_per_session", 3)
        if self._compression_count_this_turn >= max_comp:
            return messages, False

        # 估算 Token
        current_tokens = estimate_messages_tokens(messages)
        budget = self._effective_max_token_limit

        # 确定压缩级别
        strategy = get_compression_strategy()
        level = strategy.determine_level_with_iteration(
            current_tokens, budget, iteration, self._compression_count_this_turn
        )

        # 获取级别配置
        comp_config = strategy.get_config(level, current_tokens, budget)

        # 执行压缩
        combined_reason = reason or f"Level: {level.value}"
        use_llm = level in (CompressionLevel.DEEP, CompressionLevel.EMERGENCY)
        compressed, summary = self.token_compressor.compress(
            messages,
            max_chars=comp_config.summary_max_chars,
            reason=combined_reason,
            keep_count=comp_config.keep_ai_messages,
            preserve_errors=comp_config.preserve_errors,
            use_llm_summary=use_llm,
        )

        # 日志
        after_tokens = estimate_messages_tokens(compressed)
        token_saved = current_tokens - after_tokens
        ui.add_log(
            f"[压缩] {level.value.upper()} | {token_saved:+d} tokens "
            f"({current_tokens} -> {after_tokens}) | {combined_reason[:60]}",
            "INFO",
        )

        # 写入 COMPRESS_SUMMARY.md
        if summary:
            try:
                self.prompt_manager.update_state_memory(
                    f"[压缩摘要 | iter={iteration} | {level.value}]\n{summary}"
                )
            except Exception:
                pass

        # 更新状态
        try:
            get_state_manager().set_state(AgentState.COMPRESSING,
                action=f"压缩 {level.value} (iter={iteration})")
        except Exception:
            pass

        self._compression_count_this_turn += 1
        self._last_compression_iteration = iteration

        # 提前结束判断
        should_break = False
        if level == CompressionLevel.EMERGENCY:
            should_break = True
            ui.add_log("紧急压缩触发，提前结束当前轮次", "WARN")
        elif iteration > 30:
            should_break = True
            ui.add_log(f"迭代次数过多 ({iteration})，提前结束当前轮次", "WARN")

        return compressed, should_break

    @staticmethod
    def _fallback_mode_policy() -> ModePolicy:
        return ModePolicy(
            mode=AgentMode.SELF_EVOLUTION,
            orchestrator_kind="evolution",
            keep_multi_turn_context=True,
            allow_auto_loop=True,
            capture_chat_dataset_candidates=False,
            route_explicit_evolution_requests=False,
            reset_context_before_turn=False,
            reset_context_between_cases=False,
            allow_direct_supervised_payload=False,
            finish_after_direct_response=False,
            runtime_input_builder=build_external_request_message,
        )

    def _get_mode_policy(self) -> ModePolicy:
        policy = getattr(self, "mode_policy", None)
        if isinstance(policy, ModePolicy):
            return policy
        config = getattr(self, "config", None)
        try:
            if config is not None:
                resolved = resolve_mode_policy(getattr(self, "mode", None), config)
                self.mode_policy = resolved
                self.mode = resolved.mode
                return resolved
        except Exception:
            pass
        fallback = self._fallback_mode_policy()
        self.mode_policy = fallback
        self.mode = fallback.mode
        return fallback

    def seed_chat_history(self, messages: List[Dict[str, Any]]) -> None:
        """为 chat 模式恢复一段已持久化的对话历史。"""
        policy = self._get_mode_policy()
        if policy.mode != AgentMode.CHAT:
            return
        restored: List[Any] = [SystemMessage(content="")]
        for item in list(messages or []):
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip().lower()
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            if role == "user":
                restored.append(build_chat_user_message(content))
            elif role == "assistant":
                restored.append(AIMessage(content=content))
        if len(restored) <= 1:
            self._active_turn_messages = None
            self._active_turn_goal = ""
            return
        self._active_turn_messages = restored
        self._active_turn_goal = "__chat_session__"

    def export_turn_carryover(self) -> Dict[str, Any]:
        messages = self._serialize_turn_messages(self._active_turn_messages)
        goal = str(getattr(self, "_active_turn_goal", "") or "").strip()
        if not messages or not goal:
            return {}
        return {
            "messages": messages,
            "goal": goal,
        }

    def seed_turn_carryover(self, payload: Dict[str, Any] | None) -> None:
        if not isinstance(payload, dict):
            return
        goal = str(payload.get("goal") or "").strip()
        messages = self._deserialize_turn_messages(payload.get("messages") or [])
        if not goal or not messages:
            return
        self._active_turn_messages = messages
        self._active_turn_goal = goal

    def _serialize_turn_messages(self, messages: Optional[List[Any]]) -> List[Dict[str, Any]]:
        serialized: List[Dict[str, Any]] = []
        for item in list(messages or []):
            payload = self._serialize_turn_message(item)
            if payload:
                serialized.append(payload)
        return serialized

    def _serialize_turn_message(self, message: Any) -> Dict[str, Any]:
        if isinstance(message, AIMessage):
            payload: Dict[str, Any] = {
                "kind": "ai",
                "content": message.content,
                "tool_calls": list(getattr(message, "tool_calls", []) or []),
            }
            additional_kwargs = getattr(message, "additional_kwargs", None) or {}
            if additional_kwargs:
                payload["additional_kwargs"] = dict(additional_kwargs)
            response_metadata = getattr(message, "response_metadata", None) or {}
            if response_metadata:
                payload["response_metadata"] = dict(response_metadata)
            return payload
        if isinstance(message, ToolMessage):
            return {
                "kind": "tool",
                "content": message.content,
                "tool_call_id": str(getattr(message, "tool_call_id", "") or ""),
            }
        if isinstance(message, SystemMessage):
            return {
                "kind": "system",
                "content": message.content,
            }
        if isinstance(message, dict):
            payload = dict(message)
            payload["kind"] = "dict"
            return payload
        content = getattr(message, "content", None)
        if content not in (None, ""):
            return {
                "kind": "system",
                "content": content,
            }
        return {}

    def _deserialize_turn_messages(self, messages: List[Dict[str, Any]]) -> List[Any]:
        restored: List[Any] = []
        for item in list(messages or []):
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind") or "").strip().lower()
            if kind == "ai":
                restored.append(
                    AIMessage(
                        content=item.get("content", ""),
                        tool_calls=list(item.get("tool_calls") or []),
                        additional_kwargs=dict(item.get("additional_kwargs") or {}),
                        response_metadata=dict(item.get("response_metadata") or {}),
                    )
                )
                continue
            if kind == "tool":
                restored.append(
                    ToolMessage(
                        content=item.get("content", ""),
                        tool_call_id=str(item.get("tool_call_id") or ""),
                    )
                )
                continue
            if kind == "system":
                restored.append(SystemMessage(content=item.get("content", "")))
                continue
            if kind == "dict":
                payload = dict(item)
                payload.pop("kind", None)
                restored.append(payload)
        return restored

    def _reset_mode_context_for_supervised_case(self, case_id: Optional[str] = None) -> None:
        self._active_turn_messages = None
        self._active_turn_goal = ""
        self._active_goal = ""
        self._carryover_state_memory = ""
        self._last_runtime_state_memory = ""
        self._last_runtime_state_memory_key = ""
        self._chat_turn_records = []
        self._active_supervised_case_id = str(case_id or "").strip()
        try:
            session = get_session_state()
            session.reset_runtime_constraints()
            session.set_active_evolution_txn(None)
        except Exception:
            pass
        try:
            self.prompt_manager.clear_state_memory(persist=False)
            self.prompt_manager.update_current_goal("")
        except Exception:
            pass

    def _maybe_reset_supervised_case_context(self) -> None:
        policy = self._get_mode_policy()
        if policy.mode != AgentMode.SUPERVISED_EVOLUTION:
            return
        case_id = str(getattr(self, "_pending_supervised_case_id", None) or "").strip()
        if case_id:
            if case_id != getattr(self, "_active_supervised_case_id", ""):
                self._reset_mode_context_for_supervised_case(case_id)
            return
        if (
            getattr(self, "_active_supervised_case_id", "")
            or getattr(self, "_active_turn_messages", None)
            or getattr(self, "_active_goal", "")
        ):
            self._reset_mode_context_for_supervised_case(None)

    def _capture_chat_dataset_candidate_if_needed(
        self,
        *,
        user_prompt: str,
        current_turn: int,
        tool_names: List[str],
        delegated: bool,
    ) -> None:
        policy = self._get_mode_policy()
        if not policy.capture_chat_dataset_candidates:
            return
        service = getattr(self, "chat_dataset_capture", None)
        if service is None or not service.should_capture_mode(policy.mode.value):
            return
        assistant_text = (getattr(self, "_last_visible_response_text", "") or "").strip()
        record = ChatTurnRecord(
            turn_number=int(current_turn or 0),
            user_message=(user_prompt or "").strip(),
            assistant_message=assistant_text,
            tool_calls=list(dict.fromkeys(tool_names or [])),
            tool_call_count=int(getattr(self, "_last_response_tool_calls", 0) or 0),
            had_delegation=bool(delegated),
            had_explicit_conclusion=bool("结论" in assistant_text or "总结" in assistant_text or "最终" in assistant_text),
            had_next_action=bool("下一步" in assistant_text or "建议" in assistant_text or "接下来" in assistant_text),
            metadata={"mode": policy.mode.value},
        )
        self._chat_turn_records.append(record)
        conversation_logger = getattr(logger, "conversation", None)
        source_log_path = ""
        session_id = ""
        if conversation_logger is not None:
            try:
                source_log_path = str(conversation_logger._get_session_file())
                session_id = str(getattr(conversation_logger, "_session_id", "") or "")
            except Exception:
                source_log_path = ""
                session_id = ""
        try:
            service.capture_candidate(
                mode=policy.mode.value,
                session_id=session_id or "chat_session",
                source_log_path=source_log_path,
                turns=self._chat_turn_records,
            )
        except Exception as exc:
            _debug_logger.warning(f"chat candidate capture skipped: {type(exc).__name__}: {exc}", tag="CHAT")

    def _run_chat_turn(self, user_prompt: str = None, goal_override: str = None) -> bool:
        policy = self._get_mode_policy()
        if policy.route_explicit_evolution_requests and looks_like_explicit_evolution_request(user_prompt or ""):
            self._last_visible_response_text = "当前请求已标记为显式进化请求，请从进化入口继续。"
            self._last_response_tool_calls = 0
            self._last_turn_metadata = {
                "status": "routed",
                "evolution_route_requested": True,
                "route_target": "workbench_evolution",
            }
            return True
        return self._run_orchestrated_turn(user_prompt=user_prompt, goal_override=goal_override)

    def _run_evolution_turn(self, user_prompt: str = None, goal_override: str = None) -> bool:
        self._maybe_reset_supervised_case_context()
        return self._run_orchestrated_turn(user_prompt=user_prompt, goal_override=goal_override)

    def think_and_act(self, user_prompt: str = None, goal_override: str = None) -> bool:
        policy = self._get_mode_policy()
        if policy.orchestrator_kind == "chat":
            return self._run_chat_turn(user_prompt=user_prompt, goal_override=goal_override)
        return self._run_evolution_turn(user_prompt=user_prompt, goal_override=goal_override)

    def _run_orchestrated_turn(self, user_prompt: str = None, goal_override: str = None) -> bool:
        """苏醒时执行一次思考和行动。

        Returns:
            True: 继续运行, False: 结束当前主循环
        """
        ui = get_ui()
        policy = self._get_mode_policy()
        if user_prompt is None:
            user_prompt = "开始自主进化"
        effective_goal = (goal_override or user_prompt or "").strip() or user_prompt
        self._active_goal = effective_goal
        self._last_turn_metadata = {}
        self.prompt_manager.update_current_goal(effective_goal)
        self._pending_lifecycle_action = None
        context_limit = getattr(
            self,
            "_context_window_limit",
            getattr(self, "_effective_max_token_limit", 16000),
        )
        get_session_state().reset_runtime_constraints()
        self._last_runtime_state_memory = ""
        self._last_runtime_state_memory_key = ""
        self.prompt_manager.clear_state_memory(persist=False)
        self.git_memory.refresh_git_memory(force=True)
        self._sync_runtime_state_memory()
        sp = self.prompt_manager.build()
        self._cached_system_prompt = to_string(sp)
        messages, resumed_messages = TurnOutcomeController.prepare_turn_messages(
            system_prompt=sp,
            user_prompt=user_prompt,
            effective_goal=effective_goal,
            active_turn_messages=self._active_turn_messages,
            active_turn_goal=self._active_turn_goal,
            build_system_message=build_system_message,
            build_external_request_message=policy.runtime_input_builder,
            allow_append_user_message=policy.mode == AgentMode.CHAT and policy.keep_multi_turn_context,
        )
        try:
            get_ui().note_context_window(
                estimate_messages_tokens(messages),
                context_limit,
            )
        except Exception:
            pass

        if not self._system_prompt_written:
            logger.write_system_prompt(self._cached_system_prompt)
            self._system_prompt_written = True

        logger.log_external_request(user_prompt)
        if resumed_messages:
            ui.add_log("承接上一轮未完成上下文继续推进。", "INFO")
        current_turn = logger._turn_count
        logger.start_turn(current_turn)
        ui.note_turn_start(current_turn)
        llm_config = self.config.llm
        model_name = (
            llm_config.get_profile(role="primary").model
            if hasattr(llm_config, "get_profile")
            else getattr(llm_config, "model_name", "unknown")
        )
        logger.log_llm_request(messages, model=model_name)
        self._compression_count_this_turn = 0
        self._last_compression_iteration = 0

        round_state = self._create_round_state()
        lifecycle_action: Optional[str] = None
        turn_tool_names: List[str] = []
        delegated_this_turn = False
        try:
            self._raise_if_turn_stop_requested()
            for _ in range(round_state.max_iterations):
                self._raise_if_turn_stop_requested()
                iteration = round_state.next_iteration()
                ui.update_status(
                    "THINKING",
                    **round_state.thinking_status(user_prompt),
                )
                self.git_memory.refresh_git_memory()
                self._sync_runtime_state_memory()
                current_sp = self.prompt_manager.build()
                current_prompt = to_string(current_sp)
                if current_prompt != self._cached_system_prompt:
                    messages[0] = build_system_message(current_sp)
                    self._cached_system_prompt = current_prompt
                try:
                    ui.note_context_window(
                        estimate_messages_tokens(messages),
                        context_limit,
                    )
                except Exception:
                    pass

                delegated = self._maybe_delegate(
                    goal=user_prompt,
                    iteration=iteration,
                    total_tool_calls=round_state.total_tool_calls,
                    messages=messages,
                )
                self._raise_if_turn_stop_requested()
                if delegated:
                    delegated_this_turn = True
                    round_state.note_delegation(bool(delegated.get("useful")))
                    if delegated.get("break_round"):
                        ui.add_log("只读委派已返回结构化结论，本轮直接收束。", "INFO")
                        break
                    stop_reason = self._get_turn_outcome_controller().should_stop_for_convergence(
                        iteration=iteration,
                        no_new_evidence_steps=round_state.no_new_evidence_steps,
                        delegation_failures=round_state.delegation_failures,
                        total_tool_calls=round_state.total_tool_calls,
                    )
                    if stop_reason:
                        ui.add_log(stop_reason, "WARN")
                        break
                    continue

                # 硬限制：超出最大上下文时强制压缩
                current_tokens = estimate_messages_tokens(messages)
                if current_tokens > self._effective_max_token_limit * 0.95:
                    messages, should_break = self._compress_messages(
                        messages, iteration, reason="超出最大上下文限制"
                    )
                    try:
                        ui.note_context_window(
                            estimate_messages_tokens(messages),
                            context_limit,
                        )
                    except Exception:
                        pass
                    if should_break:
                        break
                    # 告知 agent 压缩已发生，让它了解上下文变化
                    after_tokens = estimate_messages_tokens(messages)
                    messages.append(build_runtime_notice_message(
                        f"由于上下文超过最大承受能力，现在强制进行了一次压缩"
                        f"（{current_tokens} → {after_tokens} tokens）。"
                    ))
                self._raise_if_turn_stop_requested()
                response = self._invoke_llm(messages)
                if response is None:
                    consecutive_failures = round_state.note_llm_failure()
                    self._last_turn_failed = True
                    ui.update_status(
                        "ERROR",
                        **round_state.current_status(),
                    )
                    ui.add_log(
                        f"LLM 调用失败（第 {consecutive_failures} 次连续失败）", "ERROR"
                    )
                    stop_reason = self._get_turn_outcome_controller().should_stop_after_llm_failure(
                        category=self._last_llm_error_category,
                        retryable=self._last_llm_error_retryable,
                        consecutive_failures=consecutive_failures,
                        iteration=iteration,
                    )
                    if stop_reason:
                        ui.add_log(stop_reason, "WARN")
                        break
                    if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                        ui.add_log(
                            f"连续失败达到 {MAX_CONSECUTIVE_FAILURES} 次，停止运行。",
                            "ERROR",
                        )
                        break
                    continue

# 调试：打印原始 content 长度
                processed = self._get_response_processor().process(response)
                raw_content = processed.raw_content
                _debug_logger.debug(f"content 长度={len(raw_content)}", tag="RAW")
                tool_call_count = processed.tool_call_count
                has_tool_calls = processed.has_tool_calls
                # 检测 XML 格式工具调用（模型有时输出 <invoke> 标签而非标准 tool_calls）
                if processed.xml_tool_calls:
                    _debug_logger.info(
                        f"[XML工具调用] 检测到 {len(processed.xml_tool_calls)} 个 XML 工具调用",
                        tag="LLM"
                    )
                    round_state.add_xml_tool_calls(len(processed.xml_tool_calls))
                    for xtc in processed.xml_tool_calls:
                        tool_name = str(xtc.get("name") or "").strip()
                        if tool_name:
                            turn_tool_names.append(tool_name)
                        ui.update_status(
                            "ACTING",
                            **round_state.current_status(),
                        )
                        self._raise_if_turn_stop_requested()
                        self.tool_lifecycle.execute_tool(xtc, messages)
                    messages.append(AIMessage(content=raw_content))
                    continue

                # ── 感知层触发 ──
                state_block_str = self._get_response_surface_controller().build_state_block(
                    raw_content=raw_content,
                    has_tool_calls=has_tool_calls,
                    consecutive_failures=round_state.consecutive_failures,
                    iteration=iteration,
                    messages=messages,
                    mental_model=self.mental_model,
                    effective_max_token_limit=self._effective_max_token_limit,
                )

# <state> 注入：剥离模型输出中的回显，防止雪球效应
                processed = self._get_response_processor().process(response, state_block_str)
                self._apply_active_components_request(processed)
                self._get_response_surface_controller().apply_state_feedback(
                    processed=processed,
                    record_language_drift=self._record_language_drift,
                    record_inference_activity=self._record_inference_activity,
                )
                # 进展标记
                round_state.note_progress()

                # Token 使用统计
                input_tokens, output_tokens = self._get_response_surface_controller().record_token_usage(
                    response=response,
                    round_state=round_state,
                    current_turn=current_turn,
                    messages=messages,
                    raw_content=raw_content,
                    estimate_output_tokens=estimate_tokens_precise,
                )

                logger.log_llm_response(
                    raw_content,
                    raw_response=raw_content,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    tool_call_count=tool_call_count,
                )

                # 输出思考内容到 UI
                response_surface = self._get_response_surface_controller().emit_visible_response(
                    raw_content=raw_content,
                    processed=processed,
                    tool_call_count=tool_call_count,
                )
                self._last_visible_response_text = response_surface["last_visible_response_text"]
                self._last_response_tool_calls = response_surface["last_response_tool_calls"]
                reasoning_content = ResponseProcessor.coerce_content_text(
                    (getattr(response, "additional_kwargs", None) or {}).get("reasoning_content", "")
                ).strip()
                if reasoning_content:
                    self._last_turn_metadata = {
                        **dict(getattr(self, "_last_turn_metadata", {}) or {}),
                        "reasoning_content": reasoning_content,
                    }
                if processed.state_info:
                    self._last_turn_metadata = {
                        **dict(getattr(self, "_last_turn_metadata", {}) or {}),
                        "state_info": dict(processed.state_info),
                    }

                tool_calls = processed.tool_calls
                round_state.note_response_tools(tool_call_count)
                for tool_call in tool_calls:
                    tool_name = str(tool_call.get("name") or "").strip()
                    if tool_name:
                        turn_tool_names.append(tool_name)
                if tool_calls:
                    ui.update_status(
                        "ACTING",
                        **round_state.acting_status(len(tool_calls)),
                    )
                else:
                    ui.update_status(
                        "SUCCESS",
                        **round_state.current_status(),
                    )
                messages.append(processed.build_ai_message(response))
                self._raise_if_turn_stop_requested()
                if not tool_calls and TurnOutcomeController.is_readonly_platform_judgment_complete(
                    getattr(self, "_active_goal", "") or "",
                    self._last_visible_response_text,
                ):
                    get_session_state().note_scope_completion("只读平台判断已给出明确结论。")
                    ui.add_log("只读平台判断已完成，本轮直接收束。", "INFO")
                    break
                if TurnOutcomeController.should_finish_single_turn_after_direct_response(
                    single_turn_mode_active=self._single_turn_mode_active,
                    tool_calls=tool_calls,
                    visible_text=self._last_visible_response_text,
                    active_evolution_txn_id=get_session_state().get_active_evolution_txn(),
                ):
                    ui.add_log("单轮请求已给出直接回答，本轮收束。", "INFO")
                    break
                round_state.add_tool_calls(len(tool_calls))
                self._raise_if_turn_stop_requested()
                lifecycle_action = self.tool_lifecycle.execute_tools(tool_calls, messages)
                self._raise_if_turn_stop_requested()
                if lifecycle_action == "turn_complete":
                    get_session_state().note_scope_completion("当前事务已完成，停止当前轮继续扩散。")
                lifecycle_decision = self._get_turn_outcome_controller().handle_lifecycle_action(lifecycle_action)
                if lifecycle_decision.pending_action:
                    self._pending_lifecycle_action = lifecycle_decision.pending_action
                if lifecycle_decision.info_log:
                    ui.add_log(lifecycle_decision.info_log, "INFO")
                if not lifecycle_decision.continue_main_loop:
                    return False
                if lifecycle_decision.break_round:
                    break
                if tool_calls:
                    ui.update_status(
                        "WORKING",
                        **round_state.current_status(),
                    )

                # 检查压缩请求（compress_context_tool 设置的标志）
                if is_compression_requested():
                    reason = consume_compression_request()
                    _debug_logger.info(f"[压缩] 感知层请求压缩: {reason}", tag="STATE")
                    messages, _ = self._compress_messages(messages, iteration, reason=reason)
                    self._raise_if_turn_stop_requested()

                stop_reason = self._get_turn_outcome_controller().should_stop_for_convergence(
                    iteration=iteration,
                    no_new_evidence_steps=round_state.no_new_evidence_steps,
                    delegation_failures=round_state.delegation_failures,
                    total_tool_calls=round_state.total_tool_calls,
                )
                if stop_reason:
                    if TurnOutcomeController.should_skip_convergence_stop_for_pending_restart(
                        expects_restart_after_transaction_close=self._expects_restart_after_transaction_close(),
                        messages=messages,
                    ):
                        ui.add_log(
                            "full_evolution 已成功关账但尚未触发重启，跳过本次收敛停止。",
                            "INFO",
                        )
                    else:
                        ui.add_log(stop_reason, "WARN")
                        break

        except TurnStopRequested as stop_request:
            self._last_turn_metadata = {
                **dict(getattr(self, "_last_turn_metadata", {}) or {}),
                "status": "stopped",
                "stop_requested": True,
                "stop_reason": str(stop_request or "").strip(),
            }
            self._last_visible_response_text = ""
            ui.add_log("收到网页终止请求，本轮在安全点收束。", "WARN")
        except Exception as e:
            self._last_turn_failed = True
            ui.update_status(
                "ERROR",
                **round_state.current_status(),
            )
            _debug_logger.error(f"主循环异常: {type(e).__name__}: {e}", exc_info=traceback.format_exc())
        finally:
            # 轮次结束统计（无论正常结束还是异常，都记录）
            finalization = self._get_turn_outcome_controller().finalize_round(round_state=round_state)
            self._last_turn_failed = finalization.last_turn_failed
            ui.note_turn_result(success=finalization.turn_success, had_progress=round_state.turn_had_progress)
            ui.update_status(
                finalization.ui_status,
                **round_state.current_status(),
            )
            logger.log_turn_end(current_turn, finalization.turn_stats)
            carryover = TurnOutcomeController.finish_turn_message_carryover(
                messages=messages,
                lifecycle_action=lifecycle_action,
                active_goal=self._active_goal,
            )
            self._active_turn_messages = carryover.messages
            self._active_turn_goal = carryover.goal
            self._capture_chat_dataset_candidate_if_needed(
                user_prompt=user_prompt,
                current_turn=current_turn,
                tool_names=turn_tool_names,
                delegated=delegated_this_turn,
            )
            self._refresh_retrospective_state_memory()
            _debug_logger.turn_end(current_turn, tool_count=round_state.total_tool_calls)

        return True

    def _invoke_llm(self, messages: list) -> Optional[Any]:
        """调用 LLM（带错误分类、自动重试）"""
        ui = get_ui()
        self._last_llm_error_category = None
        self._last_llm_error_retryable = False
        self._last_llm_recovery_action = None
        self._last_llm_error_message = ""
        clean_messages = []
        for msg in messages:
            if isinstance(msg, AIMessage):
                clean_messages.append(msg)
            elif isinstance(msg, ToolMessage):
                clean_messages.append(msg)
            elif isinstance(msg, SystemMessage):
                clean_messages.append(SystemMessage(content=msg.content or ""))
            elif isinstance(msg, dict) and msg.get("role") == "system":
                # build_system_message 返回 dict 格式（带 cache_control），
                # 提取文本转为 SystemMessage
                content = msg.get("content", "")
                if isinstance(content, list):
                    text = "\n\n".join(
                        block.get("text", "") for block in content
                        if isinstance(block, dict)
                    )
                else:
                    text = str(content)
                clean_messages.append(SystemMessage(content=text))
            else:
                clean_messages.append(msg)

        with ui.thinking("?? 思考中..."):
            attempt = 0
            disable_streaming_for_retry = False
            disable_tools_for_retry = False
            fallback_profile_id_for_retry = None
            while attempt < MAX_CONSECUTIVE_FAILURES:
                try:
                    self._raise_if_turn_stop_requested()
                    llm_for_turn = self._get_llm_for_current_mode(
                        disable_tools=disable_tools_for_retry,
                        profile_id=fallback_profile_id_for_retry,
                    )
                    if (
                        not disable_streaming_for_retry
                        and self._should_stream_llm()
                        and hasattr(llm_for_turn, "stream")
                    ):
                        full_chunk = None
                        streamed_text = ""
                        streamed_reasoning = ""
                        for chunk in llm_for_turn.stream(clean_messages):
                            self._raise_if_turn_stop_requested()
                            full_chunk = ResponseProcessor.merge_stream_chunk(full_chunk, chunk)
                            chunk_kwargs = getattr(chunk, "additional_kwargs", None) or {}
                            chunk_reasoning = str(chunk_kwargs.get("reasoning_content_delta") or "")
                            chunk_text = getattr(chunk, "content", "") or ""
                            if isinstance(chunk_text, list):
                                chunk_text = "".join(
                                    part.get("text", "") if isinstance(part, dict) else str(part)
                                    for part in chunk_text
                                )
                            if chunk_reasoning:
                                streamed_reasoning += chunk_reasoning
                                ui.stream_thought(streamed_reasoning, done=False)
                            if chunk_text:
                                streamed_text += str(chunk_text)
                                stream_response = getattr(ui, "stream_response", None)
                                if callable(stream_response):
                                    stream_response(streamed_text, done=False)
                                elif not streamed_reasoning:
                                    ui.stream_thought(streamed_text, done=False)
                        if full_chunk is not None:
                            final_content = ResponseProcessor.coerce_content_text(
                                getattr(full_chunk, "content", "")
                            )
                            if not final_content.strip() and streamed_text.strip():
                                final_content = streamed_text
                            final_kwargs = dict(getattr(full_chunk, "additional_kwargs", None) or {})
                            final_kwargs.pop("reasoning_content_delta", None)
                            if streamed_reasoning.strip():
                                final_kwargs["reasoning_content"] = streamed_reasoning
                            return AIMessageChunk(
                                content=final_content,
                                tool_calls=list(getattr(full_chunk, "tool_calls", []) or []),
                                additional_kwargs=final_kwargs,
                                response_metadata=getattr(full_chunk, "response_metadata", None) or {},
                            )
                    self._raise_if_turn_stop_requested()
                    return llm_for_turn.invoke(clean_messages)
                except TurnStopRequested:
                    raise
                except KeyboardInterrupt:
                    raise
                except Exception as e:
                    attempt += 1
                    recovery = plan_llm_recovery(
                        e,
                        attempt=attempt,
                        max_attempts=MAX_CONSECUTIVE_FAILURES,
                        config=getattr(self, "config", None),
                        role="primary",
                        current_profile_id=getattr(getattr(self, "_base_llm", None), "profile_id", None),
                    )
                    category = recovery.category
                    is_retryable = recovery.retryable
                    user_msg = recovery.user_message
                    self._last_llm_error_category = category
                    self._last_llm_error_retryable = is_retryable
                    self._last_llm_recovery_action = recovery.action
                    self._last_llm_error_message = f"{category}: {user_msg}".strip(": ")
                    disable_streaming_for_retry = disable_streaming_for_retry or recovery.disable_streaming
                    disable_tools_for_retry = disable_tools_for_retry or recovery.disable_tools
                    fallback_profile_id_for_retry = (
                        recovery.fallback_profile_id or fallback_profile_id_for_retry
                    )
                    exception_type = type(e).__name__
                    exception_message = str(e)
                    llm_error_traceback = traceback.format_exc()
                    error_details = {
                        "exception_type": exception_type,
                        "exception_message": exception_message[:4000],
                        "retryable": is_retryable,
                        "recovery_action": recovery.action,
                        "stop_current_turn": recovery.stop_current_turn,
                        "disable_streaming_next_attempt": disable_streaming_for_retry,
                        "disable_tools_next_attempt": disable_tools_for_retry,
                        "request_context_compression": recovery.request_context_compression,
                        "fallback_profile_id": recovery.fallback_profile_id,
                        "attempt": attempt,
                        "max_attempts": MAX_CONSECUTIVE_FAILURES,
                        "model": getattr(self.config.llm, "model_name", ""),
                        "provider": getattr(self.config.llm, "provider", ""),
                        "api_base": getattr(self.config.llm, "api_base", ""),
                        "api_timeout": getattr(self.config.llm, "api_timeout", None),
                        "streaming_enabled": bool(self._should_stream_llm()),
                        "message_count": len(clean_messages),
                    }
                    try:
                        from tools.token_manager import estimate_messages_tokens

                        error_details["estimated_input_tokens"] = max(
                            0, int(estimate_messages_tokens(clean_messages) or 0)
                        )
                    except Exception:
                        error_details["estimated_input_tokens"] = 0

                    _debug_logger.error(
                        f"LLM 调用失败 [{attempt}/{MAX_CONSECUTIVE_FAILURES}] "
                        f"{category}: {user_msg} | action={recovery.action} | "
                        f"fallback={recovery.fallback_profile_id or '-'} | "
                        f"{exception_type}: {exception_message[:300]}",
                        tag="LLM",
                    )
                    logger.log_error(
                        "llm_error",
                        f"{category}: {user_msg}",
                        traceback=llm_error_traceback,
                        details=error_details,
                    )

                    if recovery.request_context_compression:
                        request_compression(
                            f"LLM provider reported context limit: {category}"
                        )
                        return None

                    if recovery.stop_current_turn:
                        return None

                    if attempt < MAX_CONSECUTIVE_FAILURES:
                        wait = recovery.wait_seconds
                        ui.add_log(
                            f"LLM 恢复策略 `{recovery.action}`，等待 {wait}s 后重试"
                            f"（第 {attempt} 次）...",
                            "WARN",
                        )
                        if wait > 0:
                            time.sleep(wait)

            _debug_logger.error(
                f"LLM 连续 {MAX_CONSECUTIVE_FAILURES} 次调用失败", tag="LLM"
            )
            ui.add_log(
                f"LLM 连续 {MAX_CONSECUTIVE_FAILURES} 次调用失败，请检查网络和 API 配置。",
                "ERROR",
            )
            return None

    def _get_response_processor(self) -> ResponseProcessor:
        processor = getattr(self, "response_processor", None)
        if processor is None:
            processor = ResponseProcessor()
            self.response_processor = processor
        return processor

    def _apply_active_components_request(self, processed: ResponseProcessingResult) -> None:
        components = list(getattr(processed, "active_components", []) or [])
        if not components:
            return
        before = list((self.prompt_manager.get_status() or {}).get("active_sections_override") or [])
        self.prompt_manager.select_components(components)
        after = list((self.prompt_manager.get_status() or {}).get("active_sections_override") or [])
        if after == before:
            return
        joined = ", ".join(components)
        _debug_logger.info(f"[PromptManager] LLM 请求切换组件: {joined}", tag="PROMPT")
        try:
            get_ui().add_log(f"Prompt 组件切换: {', '.join(after)}", "INFO")
        except Exception:
            pass
        try:
            logger.log_action("active_components", {"components": components})
        except Exception:
            pass

    def _create_round_state(self) -> RoundStateController:
        return RoundStateController(max_iterations=self.config.agent.max_iterations)

    def _is_restart_focus_mode(self) -> bool:
        if self._expects_restart_after_transaction_close():
            return False
        return DelegationGovernor.is_restart_focused_goal(getattr(self, "_active_goal", ""))

    def _guard_tool_execution(self, tool_name: str, tool_args: Dict[str, Any]) -> Optional[str]:
        if not self._is_restart_focus_mode():
            return None

        allowed_tools = set(self._restart_allowed_tool_names())
        if tool_name in allowed_tools:
            return None

        return (
            "[短路] 当前处于重启测试模式，只允许任务管理与重启闭环工具。"
            "请优先：创建任务 -> 勾选任务 -> 调用 trigger_self_restart_tool。"
        )

    def set_turn_interrupt_checker(self, checker=None) -> None:
        self._turn_interrupt_checker = checker

    def _current_turn_stop_reason(self) -> str:
        checker = getattr(self, "_turn_interrupt_checker", None)
        if not callable(checker):
            return ""
        try:
            reason = checker()
        except Exception:
            return ""
        return str(reason or "").strip()

    def _raise_if_turn_stop_requested(self) -> None:
        reason = self._current_turn_stop_reason()
        if reason:
            raise TurnStopRequested(reason)

    def run_loop(self, initial_prompt: str = None) -> None:
        policy = self._get_mode_policy()
        session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        _debug_logger.start_session(session_id)
        _debug_logger.system("主循环开始", tag=self.name)

        llm_config = self.config.llm
        model_name = (
            llm_config.get_profile(role="primary").model
            if hasattr(llm_config, "get_profile")
            else getattr(llm_config, "model_name", "unknown")
        )
        logger.start_session(metadata={
            "model": model_name,
            "agent_mode": policy.mode.value,
            "token_limit": self._effective_max_token_limit,
            "tools_count": len(self.key_tools),
            "max_iterations": self.config.agent.max_iterations,
            "awake_interval": self.config.agent.awake_interval,
        })
        logger.log_action("会话开始", f"模型: {model_name}")
        get_state_manager().set_state(AgentState.AWAKENING, action="主循环启动")

        try:
            _debug_logger.kv("记忆状态", f"{get_current_goal()[:50]}")
            _print_evolution_time_core()

            external_request = initial_prompt

            while True:
                self._last_turn_failed = False
                result = self.think_and_act(user_prompt=external_request)
                external_request = None

                if not result:
                    break
                if not policy.allow_auto_loop:
                    break

                _debug_logger.system("执行完成，准备下一轮...", tag="AGENT")

                # 网络退避：连续失败的轮次越多，等待越久
                if self._last_turn_failed:
                    self._consecutive_failed_turns += 1
                    backoff = min(30 * self._consecutive_failed_turns, 300)
                    _debug_logger.warning(
                        f"上一轮 LLM 连续失败，等待 {backoff}s 后重试 "
                        f"(连续失败轮次: {self._consecutive_failed_turns})", tag="AGENT"
                    )
                    time.sleep(backoff)
                else:
                    self._consecutive_failed_turns = 0

                # 检查 Cron 到期任务
                try:
                    from core.infrastructure.cron_scheduler import get_cron_scheduler
                    from core.infrastructure.background_tasks import get_background_task_manager
                    sched = get_cron_scheduler()
                    due_jobs = sched.get_due_jobs()
                    if due_jobs:
                        mgr = get_background_task_manager()
                        for job in due_jobs:
                            mgr.start_task(command=job["command"], timeout=300)
                            _debug_logger.info(f"Cron 触发: {job['name']} ({job['id']})", tag="CRON")
                except Exception:
                    pass

                time.sleep(2)

        except KeyboardInterrupt:
            _debug_logger.info("收到中断，退出", tag="AGENT")
        except Exception as e:
            _debug_logger.error(f"主循环异常: {type(e).__name__}: {e}", exc_info=traceback.format_exc())
            logger.log_error("main_loop_exception", str(e), traceback.format_exc())
        finally:
            # 会话结束自动清理碎片
            try:
                from core.infrastructure.workspace_cleaner import auto_clean_session_debris
                ws_path = str(self.workspace_path)
                result = auto_clean_session_debris(ws_path, mental_model=self.mental_model)
                if result.get("deleted_count", 0) > 0:
                    _debug_logger.info(
                        f"[AutoClean] 已清理 {result['deleted_count']} 个碎片文件",
                        tag="CLEANER"
                    )
            except Exception:
                pass

            uptime = datetime.now() - self.start_time
            _debug_logger.info(f"运行结束 (运行时长: {uptime})", tag=self.name)
            get_state_manager().set_state(AgentState.IDLE, action="系统已关闭")
            _debug_logger.end_session()
            logger.end_session({
                "uptime_seconds": uptime.total_seconds(),
                "total_turns": logger._turn_count,
            })

        if self._pending_lifecycle_action == "restart":
            _debug_logger.info("检测到重启动作，当前进程退出，交由守护进程接管", tag="RESTART")
            raise SystemExit(0)

        if self._pending_lifecycle_action == "hibernated":
            _debug_logger.info("休眠动作已完成，当前主循环返回", tag="HIBERNATION")

    def run_single_turn(
        self,
        initial_prompt: str = None,
        goal_override: str = None,
        case_id: str = None,
    ) -> Dict[str, Any]:
        """执行单轮思考并返回结构化摘要。"""
        policy = self._get_mode_policy()
        session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        _debug_logger.start_session(session_id)
        _debug_logger.system("单轮主循环开始", tag=self.name)
        llm_config = self.config.llm
        model_name = (
            llm_config.get_profile(role="primary").model
            if hasattr(llm_config, "get_profile")
            else getattr(llm_config, "model_name", "unknown")
        )
        logger.start_session(metadata={
            "mode": "single_turn",
            "agent_mode": policy.mode.value,
            "model": model_name,
            "token_limit": self._effective_max_token_limit,
            "tools_count": len(self.key_tools),
            "max_iterations": self.config.agent.max_iterations,
            "awake_interval": self.config.agent.awake_interval,
        })
        self._last_visible_response_text = ""
        self._last_response_tool_calls = 0
        self._recent_tool_outputs = []
        self._recent_tool_records = []
        self._last_turn_metadata = {}
        self._last_llm_error_message = ""
        session = get_session_state()
        ok = False
        try:
            self._single_turn_mode_active = True
            self._pending_supervised_case_id = case_id
            ok = self.think_and_act(user_prompt=initial_prompt, goal_override=goal_override)
            snapshot = session.get_attention_snapshot()
            latest_delegation = None
            if snapshot.get("delegation_findings"):
                latest_delegation = snapshot["delegation_findings"][-1]
            summary = (self._last_visible_response_text or "").strip()
            error_message = str(getattr(self, "_last_llm_error_message", "") or "").strip()
            parsed_payload: Dict[str, Any] = {}
            if summary.startswith("{") and summary.endswith("}"):
                try:
                    candidate = json.loads(summary)
                    if isinstance(candidate, dict):
                        parsed_payload = candidate
                except Exception:
                    parsed_payload = {}
            inferred_payload: Dict[str, Any] = {}
            if not parsed_payload:
                inferred_payload = infer_result_from_tool_outputs(getattr(self, "_recent_tool_outputs", []))
            status = "completed"
            if self._last_turn_failed:
                status = "failed"
            elif not ok:
                status = "stopped"
            if not summary:
                if error_message:
                    summary = error_message
                elif status == "failed":
                    summary = "当前轮执行失败，请检查 LLM 配置或日志。"
                elif status == "stopped":
                    summary = "当前轮已停止，未产生可见回复。"
            result = {
                "status": status,
                "summary": summary,
                "findings": [],
                "evidence": [],
                "recommended_next_action": (
                    latest_delegation.get("recommended_next_action", "")
                    if isinstance(latest_delegation, dict)
                    else ""
                ),
                "confidence": "medium" if summary else "low",
                "raw_output": summary,
                "tool_call_count": self._last_response_tool_calls,
                "tool_trace": list(getattr(self, "_recent_tool_records", []) or []),
            }
            if error_message:
                result["error"] = error_message
            if parsed_payload:
                result.update(parsed_payload)
                result.setdefault("raw_output", summary)
                result["status"] = result.get("status") or status
            elif inferred_payload:
                result.update(inferred_payload)
                result.setdefault("raw_output", summary)
                result["status"] = result.get("status") or status
            if self._last_turn_metadata:
                result.update(self._last_turn_metadata)
                result["status"] = result.get("status") or status
            if policy.mode == AgentMode.CHAT:
                result.update(build_chat_coding_result_contract(result))
            return result
        finally:
            self._single_turn_mode_active = False
            self._pending_supervised_case_id = None
            self._turn_interrupt_checker = None
            _debug_logger.info("单轮运行结束", tag=self.name)
            _debug_logger.end_session()
            logger.end_session({
                "mode": "single_turn",
                "agent_mode": policy.mode.value,
                "total_turns": logger._turn_count,
                "tool_calls": self._last_response_tool_calls,
                "ok": ok,
            })


def main(initial_prompt: str = None, args=None):
    """Agent 主入口函数。"""
    return run_agent_main(
        initial_prompt=initial_prompt,
        args=args,
        parse_args_fn=parse_args,
        agent_cls=SelfEvolvingAgent,
        workbench_cls=AgentWorkbenchShell,
        get_ui_fn=get_ui,
        ui_error_fn=ui_error,
        setup_logging_fn=setup_logging,
        create_config_fn=create_config_from_args,
        set_ui_test_mode_fn=set_ui_test_mode,
        run_preflight_doctor_fn=run_preflight_doctor,
        should_launch_workbench_fn=should_launch_workbench,
        initialize_ui_for_run_fn=initialize_ui_for_run,
        extract_subagent_primary_goal_fn=extract_subagent_primary_goal,
        evolution_test_prompt=EVOLUTION_TEST_PROMPT,
        subagent_result_marker=SUBAGENT_RESULT_MARKER,
    )


if __name__ == "__main__":
    configure_console_encoding()
    _print_evolution_time_core()
    cli_args = parse_args()
    main(initial_prompt=getattr(cli_args, "prompt", None), args=cli_args)
