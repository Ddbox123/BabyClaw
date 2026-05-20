#!/usr/bin/env python3
"""
agent.py 协议层回归测试
"""

from types import SimpleNamespace
from unittest.mock import MagicMock
import json

import pytest
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

import agent as agent_module
from agent import (
    SelfEvolvingAgent,
    compact_tool_output_for_diagnosis,
    extract_subagent_primary_goal,
    infer_result_from_tool_outputs,
)
from config import Settings
from core.infrastructure.llm_utils import parse_tool_args, parse_xml_tool_calls
from core.infrastructure.runtime_input import build_external_request_message
from core.prompt_manager import build_restart_focus_state_memory
from core.orchestration.agent_modes import AgentMode, ModePolicy
from core.orchestration.delegation_governor import DelegationGovernor
from core.orchestration.round_state import RoundStateController
from core.orchestration.response_processor import ResponseProcessor
from core.orchestration.response_surface import ResponseSurfaceController
from core.orchestration.turn_outcome import TurnOutcomeController
from core.orchestration.tool_lifecycle import ToolLifecycleBridge
from tools.agent_tools import spawn_agent as spawn_agent_impl, set_subagent_stream_sink
from tools.Key_Tools import create_key_tools, create_llm_facing_tools


class TestToolMessageFlow:
    """工具消息协议测试"""

    def test_apply_active_components_request_updates_prompt_manager_and_logs(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        class DummyPromptManager:
            def __init__(self):
                self.override = None

            def select_components(self, components):
                self.override = list(components)

            def get_status(self):
                return {"active_sections_override": self.override}

        agent.prompt_manager = DummyPromptManager()
        processed = SimpleNamespace(active_components=["SOUL", "SPEC"])
        actions = []
        ui_events = []

        class DummyUI:
            def add_log(self, text, level="INFO"):
                ui_events.append((level, text))

        monkeypatch.setattr(agent_module.logger, "log_action", lambda action, details=None: actions.append((action, details)))
        monkeypatch.setattr(agent_module, "get_ui", lambda: DummyUI())

        agent._apply_active_components_request(processed)

        assert agent.prompt_manager.override == ["SOUL", "SPEC"]
        assert ui_events == [("INFO", "Prompt 组件切换: SOUL, SPEC")]
        assert actions == [("active_components", {"components": ["SOUL", "SPEC"]})]

    def test_handle_tool_result_uses_tool_message_when_id_present(self):
        messages = []

        ToolLifecycleBridge.handle_tool_result(
            {"name": "read_file_tool", "id": "call_123"},
            "tool result",
            None,
            messages,
        )

        assert len(messages) == 1
        assert isinstance(messages[0], ToolMessage)
        assert messages[0].tool_call_id == "call_123"

    def test_handle_tool_result_preserves_continuation_hint_when_truncated(self):
        messages = []
        long_result = (
            "[文件] demo.py\n"
            "[编码] utf-8 | [行数] 500 (已截断) | [大小] 12.0 KB\n"
            "[区间] 第 1-120 行 | 已显示 120 行 | 剩余 380 行\n"
            '[续读] read_file_tool(file_path="demo.py", offset=120, max_lines=120)\n\n'
            + ("X" * 5000)
        )

        ToolLifecycleBridge.handle_tool_result(
            {"name": "read_file_tool", "id": "call_456"},
            long_result,
            None,
            messages,
        )

        assert len(messages) == 1
        assert "建议续读" in messages[0].content
        assert "offset=120" in messages[0].content

    def test_invoke_llm_preserves_tool_messages(self, monkeypatch):
        captured = {}

        class DummyContext:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class DummyUI:
            def thinking(self, _label):
                return DummyContext()

            def add_log(self, *_args, **_kwargs):
                return None

        class DummyLLM:
            def invoke(self, msgs):
                captured["messages"] = msgs
                return SimpleNamespace(content="", tool_calls=[])

        monkeypatch.setattr(agent_module, "get_ui", lambda: DummyUI())

        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.llm_with_tools = DummyLLM()

        assistant_msg = AIMessage(
            content="calling tool",
            tool_calls=[{"name": "read_file_tool", "args": {"file_path": "a.py"}, "id": "call_1"}],
        )
        tool_msg = ToolMessage(content="file content", tool_call_id="call_1")

        result = agent._invoke_llm([assistant_msg, tool_msg])

        assert result is not None
        assert captured["messages"][0] is assistant_msg
        assert captured["messages"][1] is tool_msg

    def test_invoke_llm_streams_thought_and_hides_think_tags(self, monkeypatch):
        captured = {"thoughts": []}

        class DummyContext:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class DummyUI:
            def thinking(self, _label):
                return DummyContext()

            def add_log(self, *_args, **_kwargs):
                return None

            def stream_thought(self, text, done=False):
                captured["thoughts"].append((text, done))

        class DummyChunk:
            def __init__(self, content):
                self.content = content
                self.tool_calls = []

            def __add__(self, other):
                return DummyChunk((self.content or "") + (other.content or ""))

        class DummyLLM:
            def stream(self, msgs):
                captured["messages"] = msgs
                yield DummyChunk("<think>first")
                yield DummyChunk(" second</think>")

        monkeypatch.setattr(agent_module, "get_ui", lambda: DummyUI())

        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.config = SimpleNamespace(
            llm=SimpleNamespace(
                get_profile=lambda role="primary": SimpleNamespace(streaming=True)
            ),
        )
        agent.llm_with_tools = DummyLLM()

        result = agent._invoke_llm([AIMessage(content="hello")])

        assert result is not None
        assert captured["thoughts"]
        assert captured["thoughts"][-1][0] == "<think>first second</think>"
        assert captured["thoughts"][-1][1] is False

    def test_invoke_llm_stream_falls_back_to_accumulated_text_when_merged_chunk_is_empty(self, monkeypatch):
        captured = {"thoughts": []}

        class DummyContext:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class DummyUI:
            def thinking(self, _label):
                return DummyContext()

            def add_log(self, *_args, **_kwargs):
                return None

            def stream_thought(self, text, done=False):
                captured["thoughts"].append((text, done))

        class DummyChunk:
            def __init__(self, content, *, tool_calls=None, additional_kwargs=None, response_metadata=None):
                self.content = content
                self.tool_calls = tool_calls or []
                self.additional_kwargs = additional_kwargs or {}
                self.response_metadata = response_metadata or {}

            def __add__(self, other):
                return DummyChunk(
                    "",
                    tool_calls=self.tool_calls or other.tool_calls,
                    additional_kwargs=self.additional_kwargs or other.additional_kwargs,
                    response_metadata=self.response_metadata or other.response_metadata,
                )

        class DummyLLM:
            def stream(self, msgs):
                captured["messages"] = msgs
                yield DummyChunk("O")
                yield DummyChunk("K", response_metadata={"finish_reason": "stop"})

        monkeypatch.setattr(agent_module, "get_ui", lambda: DummyUI())

        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.config = SimpleNamespace(
            llm=SimpleNamespace(
                get_profile=lambda role="primary": SimpleNamespace(streaming=True)
            ),
        )
        agent.llm_with_tools = DummyLLM()

        result = agent._invoke_llm([AIMessage(content="hello")])

        assert result is not None
        assert result.content == "OK"
        assert result.response_metadata == {"finish_reason": "stop"}

    def test_invoke_llm_stream_aggregates_reasoning_content_for_followup_turns(self, monkeypatch):
        captured = {"thoughts": []}

        class DummyContext:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class DummyUI:
            def thinking(self, _label):
                return DummyContext()

            def add_log(self, *_args, **_kwargs):
                return None

            def stream_thought(self, text, done=False):
                captured["thoughts"].append((text, done))

        class DummyChunk:
            def __init__(self, content, *, additional_kwargs=None, tool_calls=None, response_metadata=None):
                self.content = content
                self.additional_kwargs = additional_kwargs or {}
                self.tool_calls = tool_calls or []
                self.response_metadata = response_metadata or {}

            def __add__(self, other):
                return DummyChunk(
                    (self.content or "") + (other.content or ""),
                    additional_kwargs=self.additional_kwargs or other.additional_kwargs,
                    tool_calls=self.tool_calls or other.tool_calls,
                    response_metadata=self.response_metadata or other.response_metadata,
                )

        class DummyLLM:
            def stream(self, msgs):
                captured["messages"] = msgs
                yield DummyChunk("", additional_kwargs={"reasoning_content_delta": "先看"})
                yield DummyChunk("", additional_kwargs={"reasoning_content_delta": "日志"})
                yield DummyChunk("结论", response_metadata={"finish_reason": "stop"})

        monkeypatch.setattr(agent_module, "get_ui", lambda: DummyUI())

        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.config = SimpleNamespace(
            llm=SimpleNamespace(
                get_profile=lambda role="primary": SimpleNamespace(streaming=True)
            ),
        )
        agent.llm_with_tools = DummyLLM()

        result = agent._invoke_llm([AIMessage(content="hello")])

        assert result is not None
        assert result.content == "结论"
        assert result.additional_kwargs["reasoning_content"] == "先看日志"
        assert captured["thoughts"][-1][0] == "先看日志"

    def test_get_llm_for_current_mode_rebinds_restart_whitelist(self):
        bound_tools = []

        class DummyBoundLLM:
            def __init__(self, tools):
                self.tools = tools

        class DummyBaseLLM:
            def bind_tools(self, tools):
                bound_tools.append([tool.name for tool in tools])
                return DummyBoundLLM(tools)

        def make_tool(name):
            return SimpleNamespace(name=name)

        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent._base_llm = DummyBaseLLM()
        agent.llm_with_tools = DummyBoundLLM([make_tool("run_test_for_tool")])
        agent._bound_llm_cache = {"default": agent.llm_with_tools}
        agent._active_goal = "制定重启任务，然后对重启任务打勾，然后运行 `trigger_self_restart_tool` 重启你自己。"
        agent.key_tools = [
            make_tool("task_create_tool"),
            make_tool("task_update_tool"),
            make_tool("task_list_tool"),
            make_tool("get_current_goal_tool"),
            make_tool("get_core_context_tool"),
            make_tool("get_memory_summary_tool"),
            make_tool("trigger_self_restart_tool"),
            make_tool("close_evolution_transaction_tool"),
            make_tool("run_test_for_tool"),
        ]
        agent._key_tool_map = {tool.name: tool for tool in agent.key_tools}

        rebound = agent._get_llm_for_current_mode()

        assert rebound is not agent.llm_with_tools
        assert bound_tools == [[
            "task_create_tool",
            "task_update_tool",
            "task_list_tool",
            "get_current_goal_tool",
            "get_core_context_tool",
            "get_memory_summary_tool",
            "trigger_self_restart_tool",
            "close_evolution_transaction_tool",
        ]]

    def test_restart_focus_state_memory_exposes_allowed_tools_only(self):
        memory = build_restart_focus_state_memory(SelfEvolvingAgent._restart_allowed_tool_names())

        assert "当前轮实际暴露给模型的工具只保留" in memory
        assert "`trigger_self_restart_tool`" in memory
        assert "`run_test_for_tool`" not in memory

    def test_restart_focus_mode_is_disabled_for_full_evolution_goal(self):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent._active_goal = (
            "执行一轮完整自进化闭环探针："
            "根据 lint 结果调用 close_evolution_transaction_tool 关账，"
            "关账成功后立即调用 trigger_self_restart_tool 完成重启。"
        )

        assert agent._is_restart_focus_mode() is False

    def test_ui_stream_thought_hides_state_and_tool_call_tags(self):
        from core.ui.cli_ui import UIManager

        ui = UIManager()
        ui.stream_thought(
            "继续查看测试。\n\n<state>\n{\"mood\":\"好奇\"}\n</state>\n</minimax:tool_call>",
            done=True,
        )

        assert "<state>" not in ui._current_thought_stream
        assert "</minimax:tool_call>" not in ui._current_thought_stream
        assert "继续查看测试" in ui._current_thought_stream

    def test_parse_xml_tool_calls_handles_valid_invoke_block(self):
        content = """
        before
        <invoke name="read_file_tool">
          <parameter name="file_path">workspace/demo.py</parameter>
        </invoke>
        after
        """

        tool_calls = parse_xml_tool_calls(content)

        assert tool_calls == [
            {
                "name": "read_file_tool",
                "args": {"file_path": "workspace/demo.py"},
                "id": "xml_0",
            }
        ]

    def test_parse_xml_tool_calls_ignores_partial_or_invalid_xml(self):
        content = '<invoke name="broken"><parameter name="x">1</parameter>'

        assert parse_xml_tool_calls(content) == []

    def test_parse_tool_args_coerces_numeric_bool_and_null_scalars(self):
        parsed = parse_tool_args(
            {
                "file_path": "demo.py",
                "offset": "30",
                "max_lines": "50",
                "show_line_numbers": "false",
                "timeout": "12.5",
                "meta": {"retry": "true", "note": "keep"},
                "empty": "null",
            }
        )

        assert parsed["file_path"] == "demo.py"
        assert parsed["offset"] == 30
        assert parsed["max_lines"] == 50
        assert parsed["show_line_numbers"] is False
        assert parsed["timeout"] == 12.5
        assert parsed["meta"]["retry"] is True
        assert parsed["meta"]["note"] == "keep"
        assert parsed["empty"] is None

    def test_response_processor_splits_standard_tool_calls_and_state_echo(self):
        processor = ResponseProcessor()
        response = SimpleNamespace(
            content="继续处理\n<state>{\"mood\":\"专注\"}</state>",
            tool_calls=[{"name": "read_file_tool", "args": {"file_path": "demo.py"}, "id": "call_1"}],
        )

        processed = processor.process(response)

        assert processed.tool_call_count == 1
        assert processed.has_tool_calls is True
        assert processed.xml_tool_calls == []
        assert "<state>" not in processed.raw_content_clean
        assert processed.visible_text == "继续处理"

    def test_response_processor_detects_xml_fallback_when_standard_tool_calls_missing(self):
        processor = ResponseProcessor()
        response = SimpleNamespace(
            content='<invoke name="read_file_tool"><parameter name="file_path">demo.py</parameter></invoke>',
            tool_calls=[],
        )

        processed = processor.process(response)

        assert processed.has_tool_calls is False
        assert len(processed.xml_tool_calls) == 1
        assert processed.xml_tool_calls[0]["name"] == "read_file_tool"

    def test_response_processor_extracts_active_components_and_strips_echo(self):
        processor = ResponseProcessor()
        response = SimpleNamespace(
            content=(
                "先收窄问题\n"
                "<active_components>SOUL, SPEC CODEBASE_MAP</active_components>\n"
                "<state>{\"mood\":\"专注\"}</state>"
            ),
            tool_calls=[],
        )

        processed = processor.process(response)

        assert processed.active_components == ["SOUL", "SPEC", "CODEBASE_MAP"]
        assert "<active_components>" not in processed.raw_content_clean
        assert "<state>" not in processed.raw_content_clean
        assert processed.visible_text == "先收窄问题"

    def test_response_processor_flattens_content_blocks(self):
        processor = ResponseProcessor()
        response = SimpleNamespace(
            content=[
                {"type": "text", "text": "继续"},
                {"type": "text", "text": "检查"},
            ],
            tool_calls=[],
        )

        processed = processor.process(response)

        assert processed.raw_content == "继续检查"
        assert processed.visible_text == "继续检查"

    def test_round_state_controller_tracks_progress_failures_and_stats(self):
        state = RoundStateController(max_iterations=5)

        assert state.next_iteration() == 1
        state.note_delegation(useful=False)
        assert state.no_new_evidence_steps == 1
        assert state.delegation_failures == 1

        state.note_progress()
        state.add_token_usage(10, 20)
        state.add_tool_calls(2)
        state.note_response_tools(0)

        assert state.total_input_tokens == 10
        assert state.total_output_tokens == 20
        assert state.total_tool_calls == 2
        assert state.no_new_evidence_steps == 2
        assert state.finish_success(False) is True
        assert state.final_stats()["tool_calls"] == 2

    def test_turn_outcome_controller_handles_lifecycle_and_finalization(self):
        state = RoundStateController(max_iterations=5)
        state.next_iteration()
        state.note_progress()
        state.add_tool_calls(2)
        controller = TurnOutcomeController(
            max_consecutive_failures=3,
            get_attention_snapshot=lambda: {},
        )

        decision = controller.handle_lifecycle_action("turn_complete")
        finalization = controller.finalize_round(round_state=state)

        assert decision.break_round is True
        assert decision.info_log
        assert finalization.turn_success is True
        assert finalization.ui_status == "SUCCESS"
        assert finalization.turn_stats["tool_calls"] == 2

    def test_close_transaction_turn_complete_can_be_suppressed_for_pending_post_close_action(self):
        action = ToolLifecycleBridge.derive_lifecycle_action(
            "close_evolution_transaction_tool",
            '{"status":"success","transaction_status":"success","txn_id":"demo"}',
            post_close_action_pending=True,
        )

        assert action is None

    def test_response_surface_controller_emits_visible_text_and_token_usage(self):
        captured = {"thoughts": [], "contents": [], "tokens": []}

        class DummyUI:
            def stream_thought(self, text, done=False):
                captured["thoughts"].append((text, done))

            def add_content(self, text):
                captured["contents"].append(text)

            def note_token_usage(self, *args, **kwargs):
                captured["tokens"].append((args, kwargs))

            def set_pet_mental_state(self, **_kwargs):
                return None

        class DummyPet:
            def record_tokens(self, *_args, **_kwargs):
                return None

            def trigger_heartbeat(self):
                return None

        token_logs = []
        controller = ResponseSurfaceController(
            estimate_tokens=lambda _messages: 100,
            ui_getter=lambda: DummyUI(),
            logger=SimpleNamespace(log_token_usage=lambda inp, out, turn: token_logs.append((inp, out, turn))),
            debug_logger=SimpleNamespace(info=lambda *_args, **_kwargs: None),
            pet_getter=lambda: DummyPet(),
            print_tokens=lambda *_args, **_kwargs: None,
        )
        round_state = RoundStateController(max_iterations=3)
        processed = SimpleNamespace(
            raw_content_clean="继续检查",
            state_info={},
            visible_text="第一行\n第二行",
        )
        response = SimpleNamespace(
            usage_metadata={"input_tokens": 12, "output_tokens": 34},
        )

        controller.apply_state_feedback(
            processed=processed,
            record_language_drift=lambda _text: None,
            record_inference_activity=lambda _text: None,
        )
        input_tokens, output_tokens = controller.record_token_usage(
            response=response,
            round_state=round_state,
            current_turn=7,
        )
        surface = controller.emit_visible_response(
            raw_content="继续检查",
            processed=processed,
            tool_call_count=0,
        )

        assert input_tokens == 12
        assert output_tokens == 34
        assert round_state.total_input_tokens == 12
        assert round_state.total_output_tokens == 34
        assert token_logs == [(12, 34, 7)]
        assert captured["thoughts"][-1] == ("第一行\n第二行", True)
        assert captured["contents"] == ["第一行", "第二行"]
        assert surface["last_visible_response_text"] == "第一行\n第二行"

    def test_response_surface_controller_accepts_prompt_and_completion_token_keys(self):
        captured = {"tokens": []}

        class DummyUI:
            def note_token_usage(self, *args, **kwargs):
                captured["tokens"].append((args, kwargs))

            def set_pet_mental_state(self, **_kwargs):
                return None

        class DummyPet:
            def record_tokens(self, *_args, **_kwargs):
                return None

            def trigger_heartbeat(self):
                return None

        token_logs = []
        controller = ResponseSurfaceController(
            estimate_tokens=lambda _messages: 100,
            ui_getter=lambda: DummyUI(),
            logger=SimpleNamespace(log_token_usage=lambda inp, out, turn: token_logs.append((inp, out, turn))),
            debug_logger=SimpleNamespace(info=lambda *_args, **_kwargs: None),
            pet_getter=lambda: DummyPet(),
            print_tokens=lambda *_args, **_kwargs: None,
        )
        round_state = RoundStateController(max_iterations=3)
        response = SimpleNamespace(
            usage_metadata={"prompt_tokens": 21, "completion_tokens": 9, "total_tokens": 30},
        )

        input_tokens, output_tokens = controller.record_token_usage(
            response=response,
            round_state=round_state,
            current_turn=8,
        )

        assert input_tokens == 21
        assert output_tokens == 9
        assert round_state.total_input_tokens == 21
        assert round_state.total_output_tokens == 9
        assert token_logs == [(21, 9, 8)]

    def test_response_surface_controller_reads_response_metadata_token_usage(self):
        captured = {"tokens": []}

        class DummyUI:
            def note_token_usage(self, *args, **kwargs):
                captured["tokens"].append((args, kwargs))

        controller = ResponseSurfaceController(
            estimate_tokens=lambda _messages: 100,
            ui_getter=lambda: DummyUI(),
            logger=SimpleNamespace(log_token_usage=lambda *_args, **_kwargs: None),
            debug_logger=SimpleNamespace(info=lambda *_args, **_kwargs: None),
            pet_getter=lambda: SimpleNamespace(record_tokens=lambda *_args, **_kwargs: None, trigger_heartbeat=lambda: None),
            print_tokens=lambda *_args, **_kwargs: None,
        )
        round_state = RoundStateController(max_iterations=3)
        response = SimpleNamespace(
            response_metadata={"token_usage": {"prompt_tokens": 44, "completion_tokens": 11}},
        )

        input_tokens, output_tokens = controller.record_token_usage(
            response=response,
            round_state=round_state,
            current_turn=9,
        )

        assert input_tokens == 44
        assert output_tokens == 11
        assert captured["tokens"][-1] == ((44, 11), {"observed": True})

    def test_response_surface_controller_estimates_tokens_when_usage_is_missing(self):
        captured = {"tokens": []}
        token_logs = []

        class DummyUI:
            def note_token_usage(self, *args, **kwargs):
                captured["tokens"].append((args, kwargs))

        controller = ResponseSurfaceController(
            estimate_tokens=lambda messages: 123 if messages else 0,
            ui_getter=lambda: DummyUI(),
            logger=SimpleNamespace(log_token_usage=lambda inp, out, turn: token_logs.append((inp, out, turn))),
            debug_logger=SimpleNamespace(info=lambda *_args, **_kwargs: None),
            pet_getter=lambda: SimpleNamespace(record_tokens=lambda *_args, **_kwargs: None, trigger_heartbeat=lambda: None),
            print_tokens=lambda *_args, **_kwargs: None,
        )
        round_state = RoundStateController(max_iterations=3)

        input_tokens, output_tokens = controller.record_token_usage(
            response=SimpleNamespace(),
            round_state=round_state,
            current_turn=10,
            messages=[SimpleNamespace(content="hello")],
            raw_content="answer",
            estimate_output_tokens=lambda text: len(text) + 5,
        )

        assert input_tokens == 123
        assert output_tokens == 11
        assert round_state.total_input_tokens == 123
        assert round_state.total_output_tokens == 11
        assert token_logs == [(123, 11, 10)]
        assert captured["tokens"][-1] == ((123, 11), {"observed": True})

    def test_execute_tools_parallel_returns_restart_action_and_stops_followups(self):
        messages = []
        calls = []

        def fake_execute(tool_name, _tool_args):
            calls.append(tool_name)
            if tool_name == "custom_restart_tool":
                return ("restart ok", "restart")
            return ("should not run", None)

        bridge = ToolLifecycleBridge(tool_executor_execute=fake_execute)

        action = bridge.execute_tools(
            [
                {"name": "custom_restart_tool"},
                {"name": "read_file_tool"},
            ],
            messages,
        )

        assert action == "restart"
        assert calls == ["custom_restart_tool"]

    def test_execute_tools_parallel_returns_turn_complete_after_successful_close_transaction(self):
        messages = []
        calls = []

        def fake_execute(tool_name, _tool_args):
            calls.append(tool_name)
            if tool_name == "close_evolution_transaction_tool":
                return (
                    '{"status":"success","txn_id":"txn_1","transaction_status":"success","summary":"done"}',
                    "turn_complete",
                )
            return ("should not run", None)

        bridge = ToolLifecycleBridge(tool_executor_execute=fake_execute)

        action = bridge.execute_tools(
            [
                {"name": "close_evolution_transaction_tool"},
                {"name": "read_file_tool"},
            ],
            messages,
        )

        assert action == "turn_complete"
        assert calls == ["close_evolution_transaction_tool"]

    def test_tool_lifecycle_bridge_derives_turn_complete_from_close_transaction(self):
        messages = []
        calls = []

        def fake_executor(tool_name, tool_args):
            calls.append((tool_name, tool_args))
            return (
                '{"status":"success","txn_id":"txn_1","transaction_status":"success","summary":"done"}',
                None,
            )

        bridge = ToolLifecycleBridge(
            tool_executor_execute=fake_executor,
            self_modified=False,
        )

        action = bridge.execute_tools(
            [{"name": "close_evolution_transaction_tool", "args": {"txn_id": "txn_1"}}],
            messages,
        )

        assert action == "turn_complete"
        assert calls[0][0] == "close_evolution_transaction_tool"
        assert isinstance(messages[0], AIMessage)

    def test_tool_lifecycle_bridge_can_short_circuit_via_guard(self):
        messages = []
        calls = []

        def fake_executor(tool_name, tool_args):
            calls.append((tool_name, tool_args))
            return ("should not run", None)

        bridge = ToolLifecycleBridge(
            tool_executor_execute=fake_executor,
            tool_guard=lambda tool_name, _tool_args: "[短路] restart focus" if tool_name == "read_file_tool" else None,
            self_modified=False,
        )

        result, action = bridge.execute_tool(
            {"name": "read_file_tool", "args": {"file_path": "demo.py"}, "id": "call_1"},
            messages,
        )

        assert action is None
        assert result.startswith("[短路]")
        assert calls == []

    def test_run_single_turn_starts_and_ends_log_sessions(self, monkeypatch):
        events = []
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.name = "tester"
        agent.config = SimpleNamespace(
            llm=SimpleNamespace(model_name="demo"),
            agent=SimpleNamespace(max_iterations=3, awake_interval=1),
        )
        agent._effective_max_token_limit = 1024
        agent.key_tools = [object(), object()]
        agent._last_turn_failed = False

        def fake_think_and_act(user_prompt=None, goal_override=None):
            events.append(("think", user_prompt))
            events.append(("goal_override", goal_override))
            agent._last_visible_response_text = "完成"
            agent._last_response_tool_calls = 2
            return True

        agent.think_and_act = fake_think_and_act

        monkeypatch.setattr(
            agent_module._debug_logger,
            "start_session",
            lambda session_id: events.append(("debug_start", session_id)),
        )
        monkeypatch.setattr(
            agent_module._debug_logger,
            "system",
            lambda *args, **kwargs: events.append(("debug_system", args, kwargs)),
        )
        monkeypatch.setattr(
            agent_module._debug_logger,
            "turn_end",
            lambda turn, tool_count=0: events.append(("debug_turn_end", turn, tool_count)),
        )
        monkeypatch.setattr(
            agent_module._debug_logger,
            "info",
            lambda *args, **kwargs: events.append(("debug_info", args, kwargs)),
        )
        monkeypatch.setattr(
            agent_module._debug_logger,
            "end_session",
            lambda: events.append(("debug_end",)),
        )
        monkeypatch.setattr(
            agent_module.logger,
            "start_session",
            lambda metadata=None, **kwargs: events.append(("conv_start", metadata, kwargs)),
        )
        monkeypatch.setattr(
            agent_module.logger,
            "end_session",
            lambda summary=None: events.append(("conv_end", summary)),
        )
        monkeypatch.setattr(
            agent_module,
            "get_session_state",
            lambda: SimpleNamespace(get_attention_snapshot=lambda: {}),
        )

        result = agent.run_single_turn(initial_prompt="probe")

        assert result["status"] == "completed"
        assert result["tool_call_count"] == 2
        assert events[0][0] == "debug_start"
        assert any(item[0] == "conv_start" and item[1]["mode"] == "single_turn" for item in events)
        assert ("think", "probe") in events
        assert not any(item[0] == "debug_turn_end" for item in events)
        assert any(item[0] == "conv_end" and item[1]["mode"] == "single_turn" for item in events)

    def test_run_single_turn_enriches_chat_result_contract_from_tool_trace(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.name = "tester"
        agent.config = SimpleNamespace(
            llm=SimpleNamespace(model_name="demo"),
            agent=SimpleNamespace(max_iterations=3, awake_interval=1),
        )
        agent.mode_policy = ModePolicy(
            mode=AgentMode.CHAT,
            orchestrator_kind="chat",
            keep_multi_turn_context=True,
            allow_auto_loop=False,
            capture_chat_dataset_candidates=False,
            route_explicit_evolution_requests=False,
            reset_context_before_turn=False,
            reset_context_between_cases=False,
            allow_direct_supervised_payload=False,
            finish_after_direct_response=False,
            runtime_input_builder=lambda text: text,
        )
        agent._effective_max_token_limit = 1024
        agent.key_tools = [object()]
        agent._last_turn_failed = False

        def fake_think_and_act(user_prompt=None, goal_override=None):
            agent._last_visible_response_text = "已修复并验证。"
            agent._last_response_tool_calls = 3
            agent._recent_tool_records = [
                {
                    "name": "read_file_tool",
                    "args": {"file_path": "core/ui/cli_ui.py"},
                    "result_preview": "read ok",
                },
                {
                    "name": "apply_diff_edit_tool",
                    "args": {"file_path": "core/ui/cli_ui.py"},
                    "result_preview": "patched",
                },
                {
                    "name": "run_test_for_tool",
                    "args": {"source_path": "core/ui/cli_ui.py"},
                    "result_preview": "3 passed in 0.40s",
                },
            ]
            return True

        agent.think_and_act = fake_think_and_act
        monkeypatch.setattr(
            agent_module.logger,
            "start_session",
            lambda metadata=None, **kwargs: None,
        )
        monkeypatch.setattr(
            agent_module.logger,
            "end_session",
            lambda summary=None: None,
        )
        monkeypatch.setattr(
            agent_module._debug_logger,
            "start_session",
            lambda session_id: None,
        )
        monkeypatch.setattr(
            agent_module._debug_logger,
            "system",
            lambda *args, **kwargs: None,
        )
        monkeypatch.setattr(
            agent_module._debug_logger,
            "info",
            lambda *args, **kwargs: None,
        )
        monkeypatch.setattr(
            agent_module._debug_logger,
            "end_session",
            lambda: None,
        )
        monkeypatch.setattr(
            agent_module,
            "get_session_state",
            lambda: SimpleNamespace(get_attention_snapshot=lambda: {}),
        )

        result = agent.run_single_turn(initial_prompt="probe")

        assert result["outcome"] == "done"
        assert result["read_files"] == ["core/ui/cli_ui.py"]
        assert result["changed_files"] == ["core/ui/cli_ui.py"]
        assert result["verification_status"] == "passed"
        assert result["no_change"] is False

    def test_run_single_turn_surfaces_llm_error_when_no_visible_reply(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.name = "tester"
        agent.config = SimpleNamespace(
            llm=SimpleNamespace(model_name="demo"),
            agent=SimpleNamespace(max_iterations=3, awake_interval=1),
        )
        agent.mode_policy = ModePolicy(
            mode=AgentMode.CHAT,
            orchestrator_kind="chat",
            keep_multi_turn_context=True,
            allow_auto_loop=False,
            capture_chat_dataset_candidates=False,
            route_explicit_evolution_requests=False,
            reset_context_before_turn=False,
            reset_context_between_cases=False,
            allow_direct_supervised_payload=False,
            finish_after_direct_response=False,
            runtime_input_builder=lambda text: text,
        )
        agent._effective_max_token_limit = 1024
        agent.key_tools = [object()]
        agent._last_turn_failed = False

        def fake_think_and_act(user_prompt=None, goal_override=None):
            agent._last_visible_response_text = ""
            agent._last_response_tool_calls = 0
            agent._recent_tool_records = []
            agent._last_llm_error_message = "configuration_error: LiteLLM 未安装，无法执行模型调用；请安装 litellm"
            agent._last_turn_failed = True
            return True

        agent.think_and_act = fake_think_and_act
        monkeypatch.setattr(agent_module.logger, "start_session", lambda metadata=None, **kwargs: None)
        monkeypatch.setattr(agent_module.logger, "end_session", lambda summary=None: None)
        monkeypatch.setattr(agent_module._debug_logger, "start_session", lambda session_id: None)
        monkeypatch.setattr(agent_module._debug_logger, "system", lambda *args, **kwargs: None)
        monkeypatch.setattr(agent_module._debug_logger, "info", lambda *args, **kwargs: None)
        monkeypatch.setattr(agent_module._debug_logger, "end_session", lambda: None)
        monkeypatch.setattr(
            agent_module,
            "get_session_state",
            lambda: SimpleNamespace(get_attention_snapshot=lambda: {}),
        )

        result = agent.run_single_turn(initial_prompt="probe")

        assert result["status"] == "failed"
        assert result["summary"] == "configuration_error: LiteLLM 未安装，无法执行模型调用；请安装 litellm"
        assert result["raw_output"] == result["summary"]
        assert result["error"] == result["summary"]

    def test_run_single_turn_keeps_full_visible_reply_text(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.name = "tester"
        agent.config = SimpleNamespace(
            llm=SimpleNamespace(model_name="demo"),
            agent=SimpleNamespace(max_iterations=3, awake_interval=1),
        )
        agent.mode_policy = ModePolicy(
            mode=AgentMode.CHAT,
            orchestrator_kind="chat",
            keep_multi_turn_context=True,
            allow_auto_loop=False,
            capture_chat_dataset_candidates=False,
            route_explicit_evolution_requests=False,
            reset_context_before_turn=False,
            reset_context_between_cases=False,
            allow_direct_supervised_payload=False,
            finish_after_direct_response=False,
            runtime_input_builder=lambda text: text,
        )
        agent._effective_max_token_limit = 1024
        agent.key_tools = [object()]
        agent._last_turn_failed = False
        long_reply = "已完成。" + ("细节说明" * 220)

        def fake_think_and_act(user_prompt=None, goal_override=None):
            agent._last_visible_response_text = long_reply
            agent._last_response_tool_calls = 0
            agent._recent_tool_records = []
            return True

        agent.think_and_act = fake_think_and_act
        monkeypatch.setattr(agent_module.logger, "start_session", lambda metadata=None, **kwargs: None)
        monkeypatch.setattr(agent_module.logger, "end_session", lambda summary=None: None)
        monkeypatch.setattr(agent_module._debug_logger, "start_session", lambda session_id: None)
        monkeypatch.setattr(agent_module._debug_logger, "system", lambda *args, **kwargs: None)
        monkeypatch.setattr(agent_module._debug_logger, "info", lambda *args, **kwargs: None)
        monkeypatch.setattr(agent_module._debug_logger, "end_session", lambda: None)
        monkeypatch.setattr(
            agent_module,
            "get_session_state",
            lambda: SimpleNamespace(get_attention_snapshot=lambda: {}),
        )

        result = agent.run_single_turn(initial_prompt="probe")

        assert result["summary"] == long_reply
        assert result["raw_output"] == long_reply

    def test_delegation_governor_apply_result_uses_injected_ui_and_session(self):
        captured = {"finish": []}

        class DummyUI:
            def add_log(self, *_args, **_kwargs):
                return None

            def add_content(self, *_args, **_kwargs):
                return None

            def add_delegation_evidence(self, *_args, **_kwargs):
                return None

            def finish_subagent_activity(self, *args, **kwargs):
                captured["finish"].append((args, kwargs))

        session = MagicMock()
        governor = DelegationGovernor(
            spawn_execute=lambda *_args, **_kwargs: ("{}", None),
            sync_runtime_state_memory=lambda: None,
            ui_getter=lambda: DummyUI(),
            session_getter=lambda: session,
        )

        payload = {"task_type": "diagnose", "goal": "分析重复调用", "scope": {"log": "a.jsonl"}}
        result = {
            "status": "completed",
            "summary": "已定位根因",
            "findings": ["重复调用 read_file_tool"],
            "evidence": ["recent_blockers"],
            "recommended_next_action": "主 agent 收束",
            "confidence": "high",
            "process_output": "子 agent 先读取 attention snapshot，再比对工具轨迹。",
        }

        outcome = governor.apply_result(payload, __import__("json").dumps(result, ensure_ascii=False), [])

        assert outcome["useful"] is True
        assert captured["finish"]
        assert "attention snapshot" in captured["finish"][0][1]["thought"]

    def test_run_loop_exits_process_after_restart_action(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.name = "tester"
        agent.config = SimpleNamespace(
            llm=SimpleNamespace(model_name="demo"),
            agent=SimpleNamespace(max_iterations=1, awake_interval=1),
        )
        agent.key_tools = []
        agent._effective_max_token_limit = 1024
        agent._last_turn_failed = False
        agent._consecutive_failed_turns = 0
        agent._pending_lifecycle_action = None
        agent.workspace_path = "."
        agent.mental_model = MagicMock()
        agent.start_time = agent_module.datetime.now()

        monkeypatch.setattr(agent_module._debug_logger, "start_session", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(agent_module._debug_logger, "system", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(agent_module._debug_logger, "kv", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(agent_module._debug_logger, "info", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(agent_module._debug_logger, "warning", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(agent_module._debug_logger, "error", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(agent_module._debug_logger, "end_session", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(agent_module, "_print_evolution_time_core", lambda: None)
        monkeypatch.setattr(agent_module.logger, "start_session", lambda **_kwargs: None)
        monkeypatch.setattr(agent_module.logger, "log_action", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(agent_module.logger, "log_error", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(agent_module.logger, "end_session", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(agent_module.logger, "_turn_count", 1, raising=False)

        state_manager = MagicMock()
        monkeypatch.setattr(agent_module, "get_state_manager", lambda: state_manager)

        cleaner_module = SimpleNamespace(
            auto_clean_session_debris=lambda *_args, **_kwargs: {"deleted_count": 0}
        )
        monkeypatch.setitem(__import__("sys").modules, "core.infrastructure.workspace_cleaner", cleaner_module)

        def fake_think_and_act(user_prompt=None, goal_override=None):
            agent._pending_lifecycle_action = "restart"
            return False

        agent.think_and_act = fake_think_and_act

        with pytest.raises(SystemExit) as exc_info:
            agent.run_loop(initial_prompt="demo")

        assert exc_info.value.code == 0

    def test_spawn_agent_structured_protocol_parses_marker_payload(self, monkeypatch):
        class FakePipe:
            def __init__(self, lines):
                self._lines = list(lines)

            def readline(self):
                if self._lines:
                    return self._lines.pop(0)
                return ""

            def close(self):
                return None

        class DummyPopen:
            def __init__(self, *_args, **_kwargs):
                self.stdout = FakePipe(
                    [
                        "subagent thinking line\n",
                        "noise before\n",
                        "__VIBELUTION_SUBAGENT_RESULT__"
                        '{"status":"completed","summary":"已定位根因","findings":["重复搜索"],'
                        '"evidence":["recent_blockers"],"recommended_next_action":"主 agent 收束","confidence":"high"}',
                    ]
                )
                self.stderr = FakePipe([])
                self.returncode = 0

            def poll(self):
                return 0

            def wait(self, timeout=None):
                return self.returncode

            def kill(self):
                self.returncode = -9

        monkeypatch.setattr("tools.agent_tools.subprocess.Popen", DummyPopen)

        result = spawn_agent_impl(
            task_type="diagnose",
            goal="分析为什么重复调用工具",
            scope='{"log":"log_info/demo.jsonl"}',
            constraints='{"readonly":true,"max_steps":4}',
            deliverables='["status","summary","findings","evidence","recommended_next_action","confidence"]',
        )

        payload = __import__("json").loads(result)
        assert payload["status"] == "completed"
        assert payload["summary"] == "已定位根因"
        assert payload["confidence"] == "high"
        assert "subagent thinking line" in payload["process_output"]

    def test_spawn_agent_infers_platform_conclusion_from_non_json_output(self, monkeypatch):
        class FakePipe:
            def __init__(self, lines):
                self._lines = list(lines)

            def readline(self):
                if self._lines:
                    return self._lines.pop(0)
                return ""

            def close(self):
                return None

        class DummyPopen:
            def __init__(self, *_args, **_kwargs):
                self.stdout = FakePipe([
                    "验证已完成。结果如下：\n",
                    "是否应执行：否，因为 `/dev/null` 和 `tail` 均为 Unix 特有。\n",
                    "Windows 等价命令：python -m pytest tests/ --collect-only -q 2>$null | Select-Object -Last 5\n",
                ])
                self.stderr = FakePipe([])
                self.returncode = 0

            def poll(self):
                return 0

            def wait(self, timeout=None):
                return self.returncode

            def kill(self):
                self.returncode = -9

        monkeypatch.setattr("tools.agent_tools.subprocess.Popen", DummyPopen)

        result = spawn_agent_impl(
            task_type="diagnose",
            goal="验证 Windows 命令平台识别",
            scope='{"goal":"判断 Unix 命令是否应执行"}',
            constraints='{"readonly":true,"max_steps":3}',
        )

        payload = __import__("json").loads(result)
        assert payload["status"] == "partial"
        assert "是否应执行：否" in payload["summary"]
        assert payload["findings"]
        assert payload["evidence"]

    def test_spawn_agent_timeout_preserves_partial_process_output(self, monkeypatch):
        class SlowPipe:
            def __init__(self, line):
                self._line = line
                self._emitted = False

            def readline(self):
                import time

                if self._emitted:
                    time.sleep(2.0)
                    return ""
                self._emitted = True
                time.sleep(0.05)
                return self._line

            def close(self):
                return None

        class TimeoutPopen:
            def __init__(self, *_args, **_kwargs):
                self.stdout = SlowPipe("step1\n")
                self.stderr = SlowPipe("timeout stderr\n")
                self.returncode = None

            def poll(self):
                return None

            def wait(self, timeout=None):
                return -9

            def kill(self):
                self.returncode = -9

        monkeypatch.setattr("tools.agent_tools.subprocess.Popen", TimeoutPopen)

        result = spawn_agent_impl(
            task_type="diagnose",
            goal="分析为什么超时",
            scope='{"log":"log_info/demo.jsonl"}',
            timeout=1,
        )

        payload = __import__("json").loads(result)
        assert payload["status"] == "timeout"
        assert "超时" in payload["summary"]
        assert "step1" in payload["process_output"]
        assert "timeout stderr" in payload["raw_output"]

    def test_spawn_agent_cancel_kills_process_and_returns_cancelled(self, monkeypatch):
        class SlowPipe:
            def readline(self):
                import time

                time.sleep(2.0)
                return ""

            def close(self):
                return None

        class CancellablePopen:
            killed = False
            kwargs = {}

            def __init__(self, *_args, **_kwargs):
                CancellablePopen.kwargs = dict(_kwargs)
                self.stdout = SlowPipe()
                self.stderr = SlowPipe()
                self.returncode = None
                self.pid = 43210

            def poll(self):
                return None

            def wait(self, timeout=None):
                self.returncode = -9
                return self.returncode

            def kill(self):
                CancellablePopen.killed = True
                self.returncode = -9

        taskkill_calls = []

        def fake_run(args, **kwargs):
            taskkill_calls.append((list(args), dict(kwargs)))
            return SimpleNamespace(returncode=0)

        monkeypatch.setattr("tools.agent_tools.subprocess.Popen", CancellablePopen)
        monkeypatch.setattr("tools.agent_tools.os.name", "nt")
        monkeypatch.setattr("tools.agent_tools.subprocess.run", fake_run)

        result = spawn_agent_impl(
            task_type="diagnose",
            goal="分析为什么停不下来",
            scope='{"log":"log_info/demo.jsonl"}',
            timeout=30,
            _cancel_checker=lambda: "操作者请求停止当前轮。",
        )

        payload = __import__("json").loads(result)
        assert payload["status"] == "cancelled"
        assert payload["stop_reason"] == "操作者请求停止当前轮。"
        assert CancellablePopen.killed is False
        assert CancellablePopen.kwargs["creationflags"] == __import__("subprocess").CREATE_NEW_PROCESS_GROUP
        assert taskkill_calls
        assert taskkill_calls[0][0] == ["taskkill", "/PID", "43210", "/T", "/F"]

    def test_spawn_agent_streams_live_stdout_before_final_marker(self, monkeypatch):
        class FakePipe:
            def __init__(self, lines):
                self._lines = list(lines)

            def readline(self):
                if self._lines:
                    return self._lines.pop(0)
                return ""

            def close(self):
                return None

        class DummyPopen:
            def __init__(self, *_args, **_kwargs):
                self.stdout = FakePipe(
                    [
                        "<think>先读取 attention snapshot\n",
                        "再看工具轨迹</think>\n",
                        "__VIBELUTION_SUBAGENT_RESULT__"
                        '{"status":"completed","summary":"已定位根因","findings":["重复搜索"],'
                        '"evidence":["recent_blockers"],"recommended_next_action":"主 agent 收束","confidence":"high"}',
                    ]
                )
                self.stderr = FakePipe([])
                self.returncode = 0

            def poll(self):
                return 0

            def wait(self, timeout=None):
                return self.returncode

            def kill(self):
                self.returncode = -9

        events = []
        monkeypatch.setattr("tools.agent_tools.subprocess.Popen", DummyPopen)
        set_subagent_stream_sink(lambda event: events.append(event))
        try:
            result = spawn_agent_impl(
                task_type="diagnose",
                goal="分析为什么重复调用工具",
                scope='{"log":"log_info/demo.jsonl"}',
            )
        finally:
            set_subagent_stream_sink(None)

        payload = __import__("json").loads(result)
        assert payload["status"] == "completed"
        assert any("attention snapshot" in item["text"] for item in events if item["stream"] == "stdout")
        assert all("__VIBELUTION_SUBAGENT_RESULT__" not in item["text"] for item in events)

    def test_spawn_agent_passes_max_iterations_from_constraints(self, monkeypatch):
        captured = {}

        class FakePipe:
            def readline(self):
                return ""

            def close(self):
                return None

        class DummyPopen:
            def __init__(self, args, **_kwargs):
                captured["args"] = list(args)
                self.stdout = FakePipe()
                self.stderr = FakePipe()
                self.returncode = 0

            def poll(self):
                return 0

            def wait(self, timeout=None):
                return self.returncode

            def kill(self):
                self.returncode = -9

        monkeypatch.setattr("tools.agent_tools.subprocess.Popen", DummyPopen)

        spawn_agent_impl(
            task_type="diagnose",
            goal="分析为什么超时",
            constraints={"readonly": True, "max_steps": 6},
            timeout=1,
        )

        assert "--max-iterations" in captured["args"]
        idx = captured["args"].index("--max-iterations")
        assert captured["args"][idx + 1] == "6"

    def test_spawn_agent_inherits_parent_conversation_log_context(self, monkeypatch):
        captured = {}

        class FakePipe:
            def readline(self):
                return ""

            def close(self):
                return None

        class DummyPopen:
            def __init__(self, args, **kwargs):
                captured["args"] = list(args)
                captured["env"] = dict(kwargs.get("env") or {})
                self.stdout = FakePipe()
                self.stderr = FakePipe()
                self.returncode = 0

            def poll(self):
                return 0

            def wait(self, timeout=None):
                return self.returncode

            def kill(self):
                self.returncode = -9

        class DummyConversation:
            _session_id = "parent_session_001"
            _turn_count = 4

        class DummyUnifiedLogger:
            conversation = DummyConversation()

        monkeypatch.setattr("tools.agent_tools.subprocess.Popen", DummyPopen)
        monkeypatch.setitem(__import__("sys").modules, "core.logging.unified_logger", SimpleNamespace(logger=DummyUnifiedLogger()))

        spawn_agent_impl(
            task_type="diagnose",
            goal="分析为什么超时",
            scope={"log": "log_info/demo.jsonl"},
            constraints={"max_steps": 2},
        )

        assert captured["env"]["VIBELUTION_LOG_SESSION_ID"] == "parent_session_001"
        assert captured["env"]["VIBELUTION_LOG_ACTOR"] == "subagent"
        assert captured["env"]["VIBELUTION_LOG_PARENT_TURN"] == "4"
        assert captured["env"]["VIBELUTION_LOG_ACTOR_LABEL"] == "diagnose"

    def test_extract_structured_result_infers_error_summary_from_raw_output(self):
        payload = spawn_agent_impl.__globals__["_extract_structured_result"](
            "<think>继续</think>\nTraceback ...\nOSError: [Errno 22] Invalid argument",
            "",
            0,
            "diagnose",
            "分析为什么超时",
            {"log": "demo.jsonl"},
        )

        assert payload["status"] == "partial"
        assert "OSError" in payload["summary"]
        assert payload["recommended_next_action"]

    def test_extract_structured_result_ignores_state_json_echo(self):
        payload = spawn_agent_impl.__globals__["_extract_structured_result"](
            "<think>继续分析</think>\n<state>{\"mood\":\"专注\"}</state>\nOSError: [Errno 22] Invalid argument",
            "",
            0,
            "diagnose",
            "分析为什么超时",
            {"log": "demo.jsonl"},
        )

        assert payload["status"] == "partial"
        assert "OSError" in payload["summary"]

    def test_spawn_agent_fast_path_scans_conversation_log(self, tmp_path):
        log_path = tmp_path / "conversation_20260511_162502.jsonl"
        log_path.write_text(
            "{\"event\":\"tool_call\",\"tool_result\":\"OSError: [Errno 22] Invalid argument\"}\n",
            encoding="utf-8",
        )

        result = json.loads(
            spawn_agent_impl(
                task_type="diagnose",
                goal=f"分析 {log_path} 中子 agent 为什么会超时，只做诊断，不要修改代码。",
                scope={"log": str(log_path)},
                constraints={"readonly": True, "max_steps": 3},
                timeout=1,
            )
        )

        assert result["status"] == "completed"
        assert "OSError" in result["summary"]
        assert result["fast_path"] == "conversation_log_scan"

    def test_apply_delegation_result_feeds_subagent_ui_blocks(self, monkeypatch):
        captured = {"start": [], "finish": []}

        class DummyUI:
            def add_log(self, *_args, **_kwargs):
                return None

            def add_content(self, *_args, **_kwargs):
                return None

            def add_delegation_evidence(self, *_args, **_kwargs):
                return None

            def start_subagent_activity(self, *args, **kwargs):
                captured["start"].append((args, kwargs))

            def finish_subagent_activity(self, *args, **kwargs):
                captured["finish"].append((args, kwargs))

        session = MagicMock()
        session.get_attention_snapshot.return_value = {}
        monkeypatch.setattr(agent_module, "get_ui", lambda: DummyUI())
        monkeypatch.setattr(agent_module, "get_session_state", lambda: session)

        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent._sync_runtime_state_memory = lambda: None

        payload = {"task_type": "diagnose", "goal": "分析重复调用", "scope": {"log": "a.jsonl"}}
        result = {
            "status": "completed",
            "summary": "已定位根因",
            "findings": ["重复调用 read_file_tool"],
            "evidence": ["recent_blockers"],
            "recommended_next_action": "主 agent 收束",
            "confidence": "high",
            "process_output": "子 agent 先读取 attention snapshot，再比对工具轨迹。",
        }

        ui = agent_module.get_ui()
        ui.start_subagent_activity(payload["task_type"], payload["goal"], payload["scope"])
        outcome = agent._apply_delegation_result(payload, __import__("json").dumps(result, ensure_ascii=False), [])

        assert outcome["useful"] is True
        assert captured["finish"]
        finish_kwargs = captured["finish"][0][1]
        assert finish_kwargs["summary"] == "已定位根因"
        assert "attention snapshot" in finish_kwargs["thought"]

    def test_maybe_delegate_passes_turn_stop_checker_to_spawn_tool(self):
        captured = {}

        class DummyUI:
            def add_log(self, *_args, **_kwargs):
                return None

            def add_content(self, *_args, **_kwargs):
                return None

            def add_delegation_evidence(self, *_args, **_kwargs):
                return None

            def start_subagent_activity(self, *_args, **_kwargs):
                return None

            def finish_subagent_activity(self, *_args, **_kwargs):
                return None

            def add_subagent_process(self, *_args, **_kwargs):
                return None

            def stream_subagent_thought(self, *_args, **_kwargs):
                return None

        class DummySession:
            def get_attention_snapshot(self):
                return {
                    "recent_blockers": [
                        {"kind": "duplicate_read", "summary": "core/infrastructure/tool_executor.py 第 1-80 行本轮已读过。"}
                    ],
                    "modified_paths": [],
                    "delegation_history": [],
                    "delegation_failures": [],
                    "last_validation_summary": "",
                    "last_validation_passed": False,
                    "diagnostic_drift": True,
                }

            def has_recent_delegation(self, *_args, **_kwargs):
                return False

            def record_delegation_start(self, *_args, **_kwargs):
                return None

            def record_delegation_result(self, *_args, **_kwargs):
                return None

            def record_delegation_failure(self, *_args, **_kwargs):
                return None

            def note_scope_completion(self, *_args, **_kwargs):
                return None

            def _normalize_scope_signature(self, scope):
                return str(scope)

        def fake_spawn_execute(_tool_name, tool_args):
            captured.update(tool_args)
            checker = tool_args.get("_cancel_checker")
            assert callable(checker)
            assert checker() == "操作者请求停止当前轮。"
            return (
                json.dumps(
                    {
                        "status": "cancelled",
                        "summary": "子 Agent 已随停止请求终止。",
                        "stop_reason": checker(),
                    },
                    ensure_ascii=False,
                ),
                None,
            )

        governor = DelegationGovernor(
            spawn_execute=fake_spawn_execute,
            sync_runtime_state_memory=lambda: None,
            ui_getter=lambda: DummyUI(),
            session_getter=lambda: DummySession(),
            turn_stop_checker=lambda: "操作者请求停止当前轮。",
        )

        outcome = governor.maybe_delegate(
            goal="继续完成同一个用户目标：继续吧",
            iteration=2,
            total_tool_calls=4,
            messages=[],
        )

        assert captured["_cancel_checker"]() == "操作者请求停止当前轮。"
        assert outcome["delegated"] is True
        assert outcome["useful"] is False

    def test_apply_delegation_result_surfaces_timeout_instead_of_parse_failure(self, monkeypatch):
        captured = {"finish": []}

        class DummyUI:
            def add_log(self, *_args, **_kwargs):
                return None

            def add_content(self, *_args, **_kwargs):
                return None

            def add_delegation_evidence(self, *_args, **_kwargs):
                return None

            def finish_subagent_activity(self, *args, **kwargs):
                captured["finish"].append((args, kwargs))

        session = MagicMock()
        monkeypatch.setattr(agent_module, "get_ui", lambda: DummyUI())
        monkeypatch.setattr(agent_module, "get_session_state", lambda: session)

        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent._sync_runtime_state_memory = lambda: None

        payload = {"task_type": "diagnose", "goal": "分析重复调用", "scope": {"log": "a.jsonl"}}
        outcome = agent._apply_delegation_result(
            payload,
            "[超时] spawn_agent_tool 执行超时 (30秒)",
            [],
        )

        assert outcome["useful"] is False
        assert captured["finish"]
        finish_kwargs = captured["finish"][0][1]
        assert finish_kwargs["status"] == "timeout"
        assert "超时" in finish_kwargs["summary"]

    def test_infer_result_from_tool_outputs_extracts_oserror(self):
        payload = infer_result_from_tool_outputs(
            [
                "普通输出",
                "Traceback ...\nOSError: [Errno 22] Invalid argument\n更多上下文",
            ]
        )

        assert payload["status"] == "partial"
        assert "OSError" in payload["summary"]
        assert payload["evidence"]

    def test_compact_tool_output_for_diagnosis_keeps_tail_evidence(self):
        raw = ("A" * 5000) + "\nOSError: [Errno 22] Invalid argument\n" + ("B" * 5000)

        compacted = compact_tool_output_for_diagnosis(raw, max_chars=200)

        assert "OSError: [Errno 22] Invalid argument" in compacted


class TestLocalProviderBootstrap:
    """本地 provider 启动测试"""

    def test_local_provider_without_api_key_can_bootstrap(self, monkeypatch):
        monkeypatch.setattr(agent_module.Key_Tools, "create_llm_facing_tools", lambda: [])
        monkeypatch.setattr(SelfEvolvingAgent, "_init_model_discovery", lambda self: 16000)
        monkeypatch.setattr(SelfEvolvingAgent, "_init_token_compressor", lambda self: None)

        def fake_init_llm(self):
            self.llm_with_tools = MagicMock()

        monkeypatch.setattr(SelfEvolvingAgent, "_init_llm", fake_init_llm)
        monkeypatch.setattr(agent_module, "get_prompt_manager", lambda: MagicMock())
        monkeypatch.setattr(agent_module, "get_state_manager", lambda: MagicMock())
        monkeypatch.setattr(agent_module, "get_event_bus", lambda: MagicMock())
        monkeypatch.setattr(agent_module, "get_tool_executor", lambda: MagicMock())
        monkeypatch.setattr(agent_module, "get_security_validator", lambda *_args, **_kwargs: MagicMock())
        monkeypatch.setattr(agent_module, "get_git_memory_service", lambda: MagicMock())

        mental_model = MagicMock()
        monkeypatch.setattr(agent_module, "get_mental_model", lambda **_kwargs: mental_model)

        config = Settings(
            None,
            **{
                "llm.profiles.primary.model": "",
                "llm.profiles.primary.api_key_env": "",
                "llm.profiles.primary.provider.kind": "local",
                "llm.profiles.primary.provider.api_key": "",
                "llm.profiles.primary.provider.api_key_env": "",
                "llm.profiles.primary.provider.base_url": "http://localhost:11434/v1",
                "llm.profiles.primary.provider.compat_mode": "openai",
                "llm.profiles.primary.provider.requires_api_key": False,
            },
        )
        agent = SelfEvolvingAgent(config=config.config)
        provider = agent.config.llm.get_provider(role="primary")

        assert provider.kind == "local"
        mental_model.set_shared_llm.assert_called_once_with(agent.llm_with_tools)


class TestDelegationExposure:
    def test_spawn_agent_tool_not_exposed_to_llm_tool_catalog(self):
        names = [tool.name for tool in create_key_tools()]

        assert "spawn_agent_tool" not in names

    def test_llm_facing_tools_hide_long_tail_admin_tools(self):
        names = [tool.name for tool in create_llm_facing_tools()]

        assert "task_start_tool" not in names
        assert "task_output_tool" not in names
        assert "task_stop_tool" not in names
        assert "update_self_model_tool" not in names
        assert "record_learning_tool" not in names
        assert "apply_diff_edit_tool" in names
        assert "read_file_tool" in names
        assert "run_test_for_tool" in names


class TestResolvedApiKeyUsage:
    """解析后的 API Key 使用一致性测试"""

    def test_agent_uses_provider_specific_resolved_key(self, monkeypatch):
        monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
        monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
        monkeypatch.setenv("MINIMAX_API_KEY", "minimax-test-key")

        monkeypatch.setattr(agent_module.Key_Tools, "create_llm_facing_tools", lambda: [])
        monkeypatch.setattr(SelfEvolvingAgent, "_init_model_discovery", lambda self: 16000)
        monkeypatch.setattr(SelfEvolvingAgent, "_init_token_compressor", lambda self: None)
        monkeypatch.setattr(agent_module, "get_prompt_manager", lambda: MagicMock())
        monkeypatch.setattr(agent_module, "get_state_manager", lambda: MagicMock())
        monkeypatch.setattr(agent_module, "get_event_bus", lambda: MagicMock())
        monkeypatch.setattr(agent_module, "get_tool_executor", lambda: MagicMock())
        monkeypatch.setattr(agent_module, "get_security_validator", lambda *_args, **_kwargs: MagicMock())
        monkeypatch.setattr(agent_module, "get_git_memory_service", lambda: MagicMock())

        mental_model = MagicMock()
        monkeypatch.setattr(agent_module, "get_mental_model", lambda **_kwargs: mental_model)

        captured = {}

        class DummyClient:
            def __init__(self, config=None, role=None, profile_id=None):
                captured.setdefault("calls", []).append(
                    {
                        "role": role,
                        "profile_id": profile_id,
                        "resolved_api_key": config.get_api_key(),
                    }
                )

            def bind_tools(self, _tools):
                return MagicMock()

        monkeypatch.setattr(
            agent_module,
            "get_llm_client",
            lambda role=None, profile_id=None, config=None: DummyClient(config=config, role=role, profile_id=profile_id),
        )

        config = Settings(
            None,
            **{
                "llm.profiles.primary.model": "",
                "llm.profiles.primary.api_key_env": "",
                "llm.profiles.primary.provider.kind": "minimax",
                "llm.profiles.primary.provider.api_key": "",
                "llm.profiles.primary.provider.api_key_env": "MINIMAX_API_KEY",
                "llm.profiles.primary.provider.base_url": "https://api.minimaxi.com/v1",
                "llm.profiles.primary.provider.compat_mode": "openai",
                "llm.profiles.primary.provider.requires_api_key": True,
            },
        )
        agent = SelfEvolvingAgent(config=config.config)

        assert agent.api_key == "minimax-test-key"
        assert agent.config.llm.api_key == "minimax-test-key"
        assert captured["calls"][0]["resolved_api_key"] == "minimax-test-key"


class TestRuntimeStateMemoryFlow:
    """运行时状态记忆闭环测试"""

    def test_sync_runtime_state_memory_combines_carryover_and_runtime(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.prompt_manager = MagicMock()
        agent._last_runtime_state_memory = ""
        agent._carryover_state_memory = "## 延续约束\n- 先补观测，再继续推理。"

        fake_session = SimpleNamespace(
            render_runtime_constraints=lambda: "### 当前轮强约束\n- `cli_tool:pipe` 已被阻塞"
        )
        monkeypatch.setattr(agent_module, "get_session_state", lambda: fake_session)

        agent._sync_runtime_state_memory()

        memory_text = agent.prompt_manager.update_state_memory.call_args[0][0]
        assert memory_text.index("### 当前轮强约束") < memory_text.index("## 延续约束")
        assert "### 当前轮强约束" in memory_text
        assert "## 延续约束" in memory_text
        assert agent.prompt_manager.update_state_memory.call_args.kwargs["persist"] is False

    def test_sync_runtime_state_memory_keeps_continuation_constraint_prominent(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.prompt_manager = MagicMock()
        agent._last_runtime_state_memory = ""
        agent._carryover_state_memory = ""

        fake_session = SimpleNamespace(
            render_runtime_constraints=lambda: (
                "### 当前轮强约束\n"
                "- 存在未完成续读：先补读 `core/demo.py`，暂不重新搜索、暂不直接归因。\n"
                "### 续读提示\n"
                "- 读局部片段（core/demo.py）：read_file_tool(file_path=\"core/demo.py\", offset=80, max_lines=80)"
            )
        )
        monkeypatch.setattr(agent_module, "get_session_state", lambda: fake_session)

        agent._sync_runtime_state_memory()

        memory_text = agent.prompt_manager.update_state_memory.call_args[0][0]
        assert memory_text.splitlines()[0] == "### 当前轮强约束"
        assert "先补读 `core/demo.py`" in memory_text
        assert agent.prompt_manager.update_state_memory.call_args.kwargs["persist"] is False

    def test_refresh_retrospective_state_memory_updates_carryover(self, monkeypatch, tmp_path):
        session_file = tmp_path / "conversation_demo.jsonl"
        session_file.write_text("{}", encoding="utf-8")

        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.prompt_manager = MagicMock()
        agent._last_runtime_state_memory = ""
        agent._carryover_state_memory = ""

        fake_report = SimpleNamespace(next_round_constraints=["后续自然语言说明默认回到中文。"])
        fake_analyzer = SimpleNamespace(
            analyze_evolution_session=lambda session_file=None: fake_report,
            build_next_round_state_memory=lambda report: "## 延续约束\n- 后续自然语言说明默认回到中文。",
        )
        monkeypatch.setattr(agent_module, "get_task_analyzer", lambda project_root=None: fake_analyzer)
        monkeypatch.setattr(
            agent_module,
            "logger",
            SimpleNamespace(conversation=SimpleNamespace(_get_session_file=lambda: str(session_file))),
        )
        monkeypatch.setattr(
            agent_module,
            "get_session_state",
            lambda: SimpleNamespace(render_runtime_constraints=lambda: ""),
        )

        agent._refresh_retrospective_state_memory()

        assert "后续自然语言说明默认回到中文" in agent._carryover_state_memory
        assert "默认回到中文" not in agent._last_runtime_state_memory
        assert agent.prompt_manager.update_state_memory.call_count == 2
        assert agent.prompt_manager.update_state_memory.call_args_list[0].kwargs["persist"] is False
        assert agent.prompt_manager.update_state_memory.call_args_list[1].kwargs["persist"] is True

    def test_sync_runtime_state_memory_filters_runtime_language_constraints(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.prompt_manager = MagicMock()
        agent._last_runtime_state_memory = ""
        agent._last_runtime_state_memory_key = ""
        agent._carryover_state_memory = ""

        summaries = iter([
            "### 语言纠偏\n- 本轮已出现 1 次英文自然语言漂移；后续说明默认回到中文。",
            "### 当前诊断纪律\n- 当前阶段：观测\n### 语言纠偏\n- 本轮已出现 2 次英文自然语言漂移；后续说明默认回到中文。",
        ])
        fake_session = SimpleNamespace(render_runtime_constraints=lambda: next(summaries))
        monkeypatch.setattr(agent_module, "get_session_state", lambda: fake_session)

        agent._sync_runtime_state_memory()
        agent.prompt_manager.clear_state_memory.assert_not_called()
        agent.prompt_manager.update_state_memory.assert_not_called()
        agent._sync_runtime_state_memory()

        agent.prompt_manager.update_state_memory.assert_called_once()
        assert "语言纠偏" not in agent._last_runtime_state_memory
        assert "默认回到中文" not in agent._last_runtime_state_memory
        assert "当前阶段：观测" in agent._last_runtime_state_memory
        assert agent.prompt_manager.update_state_memory.call_args.kwargs["persist"] is False

    def test_sync_runtime_state_memory_includes_restart_focus_guidance(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent.prompt_manager = MagicMock()
        agent._last_runtime_state_memory = ""
        agent._last_runtime_state_memory_key = ""
        agent._carryover_state_memory = ""
        agent._active_goal = "制定重启任务，然后对重启任务打勾，然后运行 `trigger_self_restart_tool` 重启你自己。"

        fake_session = SimpleNamespace(render_runtime_constraints=lambda: "")
        monkeypatch.setattr(agent_module, "get_session_state", lambda: fake_session)

        agent._sync_runtime_state_memory()

        memory_text = agent.prompt_manager.update_state_memory.call_args[0][0]
        assert "### 重启闭环纪律" in memory_text
        assert "不要先调用 `get_git_status_summary_tool`" in memory_text
        assert agent.prompt_manager.update_state_memory.call_args.kwargs["persist"] is False

    def test_think_and_act_sets_goal_before_first_prompt_build(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)

        captured = {}

        class DummyPromptManager:
            def __init__(self):
                self.current_goal = ""

            def update_current_goal(self, goal):
                self.current_goal = goal

            def clear_state_memory(self, persist=True):
                return None

            def build(self):
                captured["goal_seen_during_build"] = self.current_goal
                raise RuntimeError("stop_after_build")

        agent.prompt_manager = DummyPromptManager()
        agent.git_memory = SimpleNamespace(refresh_git_memory=lambda force=False: None)
        agent._sync_runtime_state_memory = lambda: None
        agent._system_prompt_written = False

        monkeypatch.setattr(agent_module, "get_ui", lambda: SimpleNamespace())
        monkeypatch.setattr(
            agent_module,
            "get_session_state",
            lambda: SimpleNamespace(reset_runtime_constraints=lambda: None),
        )

        with pytest.raises(RuntimeError, match="stop_after_build"):
            agent.think_and_act("制定重启任务，然后对重启任务打勾，然后运行 `trigger_self_restart_tool` 重启你自己。")

        assert "trigger_self_restart_tool" in captured["goal_seen_during_build"]

    def test_think_and_act_uses_goal_override_before_first_prompt_build(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)

        captured = {}

        class DummyPromptManager:
            def __init__(self):
                self.current_goal = ""

            def update_current_goal(self, goal):
                self.current_goal = goal

            def clear_state_memory(self, persist=True):
                return None

            def build(self):
                captured["goal_seen_during_build"] = self.current_goal
                raise RuntimeError("stop_after_build")

        agent.prompt_manager = DummyPromptManager()
        agent.git_memory = SimpleNamespace(refresh_git_memory=lambda force=False: None)
        agent._sync_runtime_state_memory = lambda: None
        agent._system_prompt_written = False

        monkeypatch.setattr(agent_module, "get_ui", lambda: SimpleNamespace())
        monkeypatch.setattr(
            agent_module,
            "get_session_state",
            lambda: SimpleNamespace(reset_runtime_constraints=lambda: None),
        )

        with pytest.raises(RuntimeError, match="stop_after_build"):
            agent.think_and_act(
                "## 子 Agent 基座\n- 当前唯一目标: 分析超时原因\n- 当前任务类型: diagnose",
                goal_override="分析超时原因",
            )

        assert captured["goal_seen_during_build"] == "分析超时原因"

    def test_extract_subagent_primary_goal_prefers_declared_goal(self):
        prompt = (
            "## 子 Agent 基座\n"
            "- 你是只读专项分析子 agent。\n"
            "## 主 Agent 任务指令\n"
            "- 当前唯一目标: 分析最近验证失败的根因\n"
            "- 当前任务类型: diagnose\n"
        )

        assert extract_subagent_primary_goal(prompt) == "分析最近验证失败的根因"

    def test_should_stop_after_llm_failure_handles_network_and_non_retryable(self):
        controller = TurnOutcomeController(
            max_consecutive_failures=3,
            get_attention_snapshot=lambda: {},
        )

        assert controller.should_stop_after_llm_failure(
            category="network_error",
            retryable=True,
            consecutive_failures=2,
            iteration=2,
        )
        assert controller.should_stop_after_llm_failure(
            category="auth_error",
            retryable=False,
            consecutive_failures=1,
            iteration=1,
        )
        assert controller.should_stop_after_llm_failure(
            category="network_error",
            retryable=True,
            consecutive_failures=1,
            iteration=1,
        ) is None

    def test_should_stop_for_convergence_when_no_new_evidence_accumulates(self):
        agent_snapshot = {"diagnostic_drift": False, "last_validation_summary": "", "recent_blockers": []}
        controller = TurnOutcomeController(
            max_consecutive_failures=3,
            get_attention_snapshot=lambda: agent_snapshot,
        )

        reason = controller.should_stop_for_convergence(
            iteration=3,
            no_new_evidence_steps=3,
            delegation_failures=0,
            total_tool_calls=2,
        )

        assert reason is not None
        assert "没有新增证据" in reason

    def test_should_stop_for_convergence_when_scope_frozen_without_new_evidence(self):
        agent_snapshot = {
            "diagnostic_drift": False,
            "last_validation_summary": "ruff lint 通过",
            "recent_blockers": [],
            "feedback_loop_ready": True,
            "scope_frozen": True,
            "convergence_state": "ready_to_fix",
            "stop_reason": "已锁定当前锚点",
        }
        controller = TurnOutcomeController(
            max_consecutive_failures=3,
            get_attention_snapshot=lambda: agent_snapshot,
        )

        reason = controller.should_stop_for_convergence(
            iteration=2,
            no_new_evidence_steps=2,
            delegation_failures=0,
            total_tool_calls=3,
        )

        assert reason is not None
        assert "范围已冻结" in reason

    def test_should_stop_for_convergence_when_feedback_loop_never_forms(self):
        agent_snapshot = {
            "diagnostic_drift": False,
            "last_validation_summary": "",
            "recent_blockers": [],
            "feedback_loop_ready": False,
            "scope_frozen": False,
            "convergence_state": "open",
        }
        controller = TurnOutcomeController(
            max_consecutive_failures=3,
            get_attention_snapshot=lambda: agent_snapshot,
        )

        reason = controller.should_stop_for_convergence(
            iteration=2,
            no_new_evidence_steps=2,
            delegation_failures=0,
            total_tool_calls=4,
        )

        assert reason is not None
        assert "未形成最小反馈环" in reason

    def test_readonly_platform_judgment_completion_is_detected(self):
        goal = (
            "验证 Windows 命令平台识别：请尝试判断 "
            "python -m pytest tests/ --collect-only -q 2>/dev/null | tail -5 "
            "在当前系统是否应该执行；不要修改代码，只做一次最小验证并给出结论。"
        )
        answer = (
            "结论：这个命令在当前 Windows 系统上不应该执行。"
            "`2>/dev/null` 和 `tail -5` 是 Unix shell 片段；"
            "Windows 等价命令应使用 `2>$null | Select-Object -Last 5`。"
        )

        assert TurnOutcomeController.is_readonly_platform_judgment_complete(goal, answer) is True

    def test_readonly_platform_judgment_requires_explicit_conclusion(self):
        goal = "验证 Windows 命令平台识别；不要修改代码，只做一次最小验证。"
        answer = "我需要继续查看 tests 目录，并确认当前项目结构。"

        assert TurnOutcomeController.is_readonly_platform_judgment_complete(goal, answer) is False

    def test_single_turn_direct_response_finishes_without_tool_calls(self):
        assert TurnOutcomeController.should_finish_single_turn_after_direct_response(
            single_turn_mode_active=True,
            tool_calls=[],
            visible_text="OK",
        ) is True
        assert TurnOutcomeController.should_finish_single_turn_after_direct_response(
            single_turn_mode_active=True,
            tool_calls=[{"name": "read_file_tool"}],
            visible_text="OK",
        ) is False
        assert TurnOutcomeController.should_finish_single_turn_after_direct_response(
            single_turn_mode_active=False,
            tool_calls=[],
            visible_text="OK",
        ) is False
        assert TurnOutcomeController.should_finish_single_turn_after_direct_response(
            single_turn_mode_active=True,
            tool_calls=[],
            visible_text="OK",
            active_evolution_txn_id="txn_1",
        ) is False

    def test_full_evolution_goal_detects_successful_close_without_restart(self):
        active_goal = (
            "执行一轮完整自进化闭环探针："
            "调用 close_evolution_transaction_tool 关账，"
            "关账成功后立即调用 trigger_self_restart_tool 完成重启。"
        )
        messages = [
            ToolMessage(
                content='{"status":"success","transaction_status":"success","txn_id":"demo"}',
                tool_call_id="call_close",
                name="close_evolution_transaction_tool",
            )
        ]

        assert TurnOutcomeController.should_skip_convergence_stop_for_pending_restart(
            expects_restart_after_transaction_close=DelegationGovernor.is_full_evolution_goal(active_goal),
            messages=messages,
        ) is True

        messages.append(
            ToolMessage(
                content="重启触发成功",
                tool_call_id="call_restart",
                name="trigger_self_restart_tool",
            )
        )

        assert TurnOutcomeController.should_skip_convergence_stop_for_pending_restart(
            expects_restart_after_transaction_close=DelegationGovernor.is_full_evolution_goal(active_goal),
            messages=messages,
        ) is False

    def test_pending_restart_skip_is_disabled_without_full_evolution_goal(self):
        active_goal = "执行非重启事务探针，不要调用 trigger_self_restart_tool。"
        messages = [
            ToolMessage(
                content='{"status":"success","transaction_status":"success","txn_id":"demo"}',
                tool_call_id="call_close",
                name="close_evolution_transaction_tool",
            )
        ]

        assert TurnOutcomeController.should_skip_convergence_stop_for_pending_restart(
            expects_restart_after_transaction_close=DelegationGovernor.is_full_evolution_goal(active_goal),
            messages=messages,
        ) is False

    def test_prepare_turn_messages_resumes_same_unfinished_goal(self):
        previous = [
            SystemMessage(content="old system"),
            build_external_request_message("开始自主进化"),
            AIMessage(content="上一轮观察"),
        ]

        messages, resumed = TurnOutcomeController.prepare_turn_messages(
            system_prompt="new system",
            user_prompt="开始自主进化",
            effective_goal="开始自主进化",
            active_turn_messages=previous,
            active_turn_goal="开始自主进化",
            build_system_message=agent_module.build_system_message,
            build_external_request_message=build_external_request_message,
        )

        assert resumed is True
        assert messages is not previous
        assert len(messages) == 3
        assert isinstance(messages[0], dict)
        assert messages[1:] == previous[1:]

    def test_prepare_turn_messages_starts_fresh_for_new_goal(self):
        previous = [
            SystemMessage(content="old system"),
            build_external_request_message("开始自主进化"),
            AIMessage(content="上一轮观察"),
        ]

        messages, resumed = TurnOutcomeController.prepare_turn_messages(
            system_prompt="new system",
            user_prompt="新的任务",
            effective_goal="新的任务",
            active_turn_messages=previous,
            active_turn_goal="开始自主进化",
            build_system_message=agent_module.build_system_message,
            build_external_request_message=build_external_request_message,
        )

        assert resumed is False
        assert len(messages) == 2
        assert isinstance(messages[1], SystemMessage)
        assert "外部任务输入" in messages[1].content
        assert "新的任务" in messages[1].content

    def test_prepare_turn_messages_appends_user_message_for_chat_context(self):
        previous = [
            SystemMessage(content="old system"),
            build_external_request_message("第一句"),
            AIMessage(content="第一轮回复"),
        ]

        messages, resumed = TurnOutcomeController.prepare_turn_messages(
            system_prompt="new system",
            user_prompt="第二句",
            effective_goal="第二句",
            active_turn_messages=previous,
            active_turn_goal="第一句",
            build_system_message=agent_module.build_system_message,
            build_external_request_message=build_external_request_message,
            allow_append_user_message=True,
        )

        assert resumed is True
        assert len(messages) == 4
        assert isinstance(messages[0], dict)
        assert messages[1:] == previous[1:] + [build_external_request_message("第二句")]

    def test_finish_turn_message_carryover_keeps_unfinished_context_and_clears_after_close(self):
        messages = [
            SystemMessage(content="system"),
            build_external_request_message("开始自主进化"),
            AIMessage(content="观察"),
        ]

        carryover = TurnOutcomeController.finish_turn_message_carryover(
            messages=messages,
            lifecycle_action=None,
            active_goal="开始自主进化",
        )

        assert carryover.goal == "开始自主进化"
        assert carryover.messages == messages

        carryover = TurnOutcomeController.finish_turn_message_carryover(
            messages=messages,
            lifecycle_action="turn_complete",
            active_goal="开始自主进化",
        )

        assert carryover.goal == ""
        assert carryover.messages is None

    def test_build_delegation_request_skips_broad_autonomous_goal_without_local_symptom(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        session = SimpleNamespace(
            get_attention_snapshot=lambda: {
                "recent_blockers": [],
                "modified_paths": [],
                "delegation_history": [],
                "last_validation_summary": "",
                "diagnostic_drift": False,
            },
            has_recent_delegation=lambda *args, **kwargs: False,
            _normalize_scope_signature=lambda scope: str(scope),
        )
        monkeypatch.setattr(agent_module, "get_session_state", lambda: session)

        payload = agent._build_delegation_request(
            goal="开始自主进化",
            iteration=2,
            total_tool_calls=4,
        )

        assert payload is None

    def test_build_delegation_request_narrows_broad_goal_to_local_blocker(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        session = SimpleNamespace(
            get_attention_snapshot=lambda: {
                "recent_blockers": [
                    {"kind": "diagnostic_drift", "summary": "连续多步没有新增证据，先检查 log_info/conversation_20260510_135821.jsonl"},
                ],
                "modified_paths": ["agent.py"],
                "delegation_history": [],
                "delegation_failures": [],
                "last_validation_summary": "",
                "diagnostic_drift": True,
                "pending_continuations": [],
            },
            has_recent_delegation=lambda *args, **kwargs: False,
            _normalize_scope_signature=lambda scope: str(scope),
        )
        monkeypatch.setattr(agent_module, "get_session_state", lambda: session)

        payload = agent._build_delegation_request(
            goal="开始自主进化",
            iteration=2,
            total_tool_calls=4,
        )

        assert payload is not None
        assert payload["task_type"] == "diagnose"
        assert payload["goal"] != "开始自主进化"
        assert "log_info/conversation_20260510_135821.jsonl" in payload["goal"]

    def test_build_delegation_request_skips_broad_drift_without_concrete_anchor_even_if_modified_paths_exist(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        session = SimpleNamespace(
            get_attention_snapshot=lambda: {
                "recent_blockers": [
                    {"kind": "diagnostic_drift", "summary": "连续多步没有新增证据"},
                ],
                "modified_paths": ["agent.py", "tools/agent_tools.py"],
                "delegation_history": [],
                "delegation_failures": [],
                "last_validation_summary": "",
                "diagnostic_drift": True,
                "pending_continuations": [],
            },
            has_recent_delegation=lambda *args, **kwargs: False,
            _normalize_scope_signature=lambda scope: str(scope),
        )
        monkeypatch.setattr(agent_module, "get_session_state", lambda: session)

        payload = agent._build_delegation_request(
            goal="开始自主进化",
            iteration=2,
            total_tool_calls=4,
        )

        assert payload is None

    def test_build_delegation_request_does_not_treat_pending_continuation_as_anchor(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        session = SimpleNamespace(
            get_attention_snapshot=lambda: {
                "recent_blockers": [
                    {"kind": "diagnostic_drift", "summary": "连续进行推理但没有新增观测，请先打印最小中间值或验证结果。"},
                ],
                "modified_paths": ["agent.py"],
                "delegation_history": [],
                "delegation_failures": [],
                "last_validation_summary": "",
                "diagnostic_drift": True,
                "pending_continuations": [
                    {
                        "tool_name": "read_file_tool",
                        "path": "tests/test_config_redaction.py",
                        "hint": 'read_file_tool(file_path="tests/test_config_redaction.py", offset=120, max_lines=30)',
                    }
                ],
            },
            has_recent_delegation=lambda *args, **kwargs: False,
            _normalize_scope_signature=lambda scope: str(scope),
        )
        monkeypatch.setattr(agent_module, "get_session_state", lambda: session)

        payload = agent._build_delegation_request(
            goal="开始自主进化",
            iteration=2,
            total_tool_calls=5,
        )

        assert payload is None

    def test_extract_live_thought_from_subagent_output_handles_open_and_closed_blocks(self):
        open_text = DelegationGovernor.extract_live_thought_from_subagent_output("<think>先看日志")
        closed_text = DelegationGovernor.extract_live_thought_from_subagent_output(
            "x<think>先看 attention snapshot\n再看工具轨迹</think>y"
        )

        assert open_text == "先看日志"
        assert "attention snapshot" in closed_text

    def test_build_delegation_request_skips_same_class_after_failed_timeout(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        failed_goal = "分析当前轮为什么出现：连续进行推理但没有新增观测，请先打印最小中间值或验证结果。"
        session = SimpleNamespace(
            get_attention_snapshot=lambda: {
                "recent_blockers": [
                    {"kind": "diagnostic_drift", "summary": "连续进行推理但没有新增观测，请先打印最小中间值或验证结果。"},
                    {"kind": "diagnostic_drift", "summary": "连续进行推理但没有新增观测，请先打印最小中间值或验证结果。"},
                ],
                "modified_paths": [],
                "delegation_history": [],
                "delegation_failures": [
                    {"task_type": "diagnose", "goal": failed_goal, "status": "failed"},
                ],
                "last_validation_summary": "tests/test_agent_protocol.py::test_x 失败",
                "diagnostic_drift": True,
                "pending_continuations": [],
            },
            has_recent_delegation=lambda *args, **kwargs: False,
            _normalize_scope_signature=lambda scope: str(scope),
        )
        monkeypatch.setattr(agent_module, "get_session_state", lambda: session)

        payload = agent._build_delegation_request(
            goal="开始自主进化",
            iteration=2,
            total_tool_calls=5,
        )

        assert payload is None

    def test_build_delegation_request_skips_fake_validation_failure_when_pytest_passed(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        session = SimpleNamespace(
            get_attention_snapshot=lambda: {
                "recent_blockers": [
                    {"kind": "diagnostic_drift", "summary": "连续多步没有新增证据。"},
                ],
                "modified_paths": [],
                "delegation_history": [],
                "delegation_failures": [],
                "last_validation_summary": "pytest 通过",
                "last_validation_passed": True,
                "diagnostic_drift": True,
                "pending_continuations": [],
            },
            has_recent_delegation=lambda *args, **kwargs: False,
            _normalize_scope_signature=lambda scope: str(scope),
        )
        monkeypatch.setattr(agent_module, "get_session_state", lambda: session)

        payload = agent._build_delegation_request(
            goal="开始自主进化",
            iteration=2,
            total_tool_calls=5,
        )

        assert payload is None

    def test_build_delegation_request_skips_restart_focused_goal(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        session = SimpleNamespace(
            get_attention_snapshot=lambda: {
                "recent_blockers": [{"kind": "diagnostic_drift", "summary": "连续进行推理但没有新增观测，请先打印最小中间值或验证结果。"}],
                "modified_paths": [],
                "delegation_history": [],
                "delegation_failures": [],
                "last_validation_summary": "",
                "last_validation_passed": False,
                "diagnostic_drift": True,
            },
            has_recent_delegation=lambda *args, **kwargs: False,
            _normalize_scope_signature=lambda scope: str(scope),
        )
        monkeypatch.setattr(agent_module, "get_session_state", lambda: session)

        payload = agent._build_delegation_request(
            goal="制定重启任务，然后对重启任务打勾，然后运行 `trigger_self_restart_tool` 重启你自己。",
            iteration=2,
            total_tool_calls=4,
        )

        assert payload is None

    def test_build_delegation_request_allows_first_readonly_diagnosis_attempt(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        session = SimpleNamespace(
            get_attention_snapshot=lambda: {
                "recent_blockers": [],
                "modified_paths": [],
                "delegation_history": [],
                "delegation_failures": [],
                "last_validation_summary": "",
                "last_validation_passed": False,
                "diagnostic_drift": False,
            },
            has_recent_delegation=lambda *args, **kwargs: False,
            _normalize_scope_signature=lambda scope: str(scope),
        )
        monkeypatch.setattr(agent_module, "get_session_state", lambda: session)

        payload = agent._build_delegation_request(
            goal="分析 log_info/conversation_20260511_162502.jsonl 中子 agent 为什么会超时，只做诊断，不要修改代码。",
            iteration=1,
            total_tool_calls=0,
        )

        assert payload is not None
        assert payload["task_type"] == "diagnose"

    def test_build_delegation_request_allows_summary_only_with_existing_evidence(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        session = SimpleNamespace(
            get_attention_snapshot=lambda: {
                "recent_blockers": [
                    {"kind": "diagnostic_drift", "summary": "重复搜索已堆积在 core/ui/cli_ui.py"},
                ],
                "modified_paths": ["core/ui/cli_ui.py"],
                "delegation_history": [],
                "delegation_failures": [],
                "delegation_evidence_digest": "已知证据: 重复搜索与重复读取都围绕同一文件。",
                "last_validation_summary": "pytest 通过，但仍未形成收束解释。",
                "last_validation_passed": True,
                "diagnostic_drift": False,
            },
            has_recent_delegation=lambda *args, **kwargs: False,
            _normalize_scope_signature=lambda scope: str(scope),
        )
        monkeypatch.setattr(agent_module, "get_session_state", lambda: session)

        payload = agent._build_delegation_request(
            goal="请总结一下当前已有证据，只做摘要，不要修改代码。",
            iteration=2,
            total_tool_calls=5,
        )

        assert payload is not None
        assert payload["task_type"] == "summarize"
        assert payload["scope"]["last_validation_summary"] == "pytest 通过，但仍未形成收束解释。"
        assert payload["role_need"]["trigger_reason"] == "evidence_compression_needed"
        assert "低熵压缩" in payload["role_need"]["why_now"]

    def test_build_delegation_request_blocks_summary_without_enough_evidence(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        session = SimpleNamespace(
            get_attention_snapshot=lambda: {
                "recent_blockers": [],
                "modified_paths": [],
                "delegation_history": [],
                "delegation_failures": [],
                "delegation_evidence_digest": "",
                "last_validation_summary": "",
                "last_validation_passed": False,
                "diagnostic_drift": False,
            },
            has_recent_delegation=lambda *args, **kwargs: False,
            _normalize_scope_signature=lambda scope: str(scope),
        )
        monkeypatch.setattr(agent_module, "get_session_state", lambda: session)

        payload = agent._build_delegation_request(
            goal="请总结一下当前状态，只做摘要，不要修改代码。",
            iteration=2,
            total_tool_calls=5,
        )

        assert payload is None

    def test_build_delegation_request_blocks_summary_when_goal_includes_mutation(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        session = SimpleNamespace(
            get_attention_snapshot=lambda: {
                "recent_blockers": [
                    {"kind": "diagnostic_drift", "summary": "重复搜索已堆积在 core/ui/cli_ui.py"},
                ],
                "modified_paths": ["core/ui/cli_ui.py"],
                "delegation_history": [],
                "delegation_failures": [],
                "delegation_evidence_digest": "已知证据: 重复搜索与重复读取都围绕同一文件。",
                "last_validation_summary": "pytest 通过，但仍未形成收束解释。",
                "last_validation_passed": True,
                "diagnostic_drift": False,
            },
            has_recent_delegation=lambda *args, **kwargs: False,
            _normalize_scope_signature=lambda scope: str(scope),
        )
        monkeypatch.setattr(agent_module, "get_session_state", lambda: session)

        payload = agent._build_delegation_request(
            goal="请总结一下当前证据，然后修改代码。",
            iteration=2,
            total_tool_calls=5,
        )

        assert payload is None

    def test_build_delegation_request_allows_explicit_inspect_with_reading_load(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        session = SimpleNamespace(
            get_attention_snapshot=lambda: {
                "recent_blockers": [
                    {"kind": "context", "summary": "需要对照 core/ui/cli_ui.py 与 core/orchestration/delegation_governor.py 的配置差异。"},
                ],
                "modified_paths": ["core/ui/cli_ui.py", "core/orchestration/delegation_governor.py"],
                "delegation_history": [],
                "delegation_failures": [],
                "delegation_evidence_digest": "",
                "last_validation_summary": "",
                "last_validation_passed": False,
                "diagnostic_drift": False,
            },
            has_recent_delegation=lambda *args, **kwargs: False,
            _normalize_scope_signature=lambda scope: str(scope),
        )
        monkeypatch.setattr(agent_module, "get_session_state", lambda: session)

        payload = agent._build_delegation_request(
            goal="检查当前配置链路是否一致，只做查看，不要修改代码。",
            iteration=2,
            total_tool_calls=2,
        )

        assert payload is not None
        assert payload["task_type"] == "inspect"
        assert payload["role_name"] == "局部状态探针"
        assert "静态阅读上的工作记忆负担" in payload["role_purpose"]
        assert payload["role_need"]["trigger_reason"] == "local_state_probe_needed"

    def test_build_delegation_request_blocks_low_value_inspect_without_reading_load(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        session = SimpleNamespace(
            get_attention_snapshot=lambda: {
                "recent_blockers": [],
                "modified_paths": ["core/ui/cli_ui.py"],
                "delegation_history": [],
                "delegation_failures": [],
                "delegation_evidence_digest": "",
                "last_validation_summary": "",
                "last_validation_passed": False,
                "diagnostic_drift": False,
            },
            has_recent_delegation=lambda *args, **kwargs: False,
            _normalize_scope_signature=lambda scope: str(scope),
        )
        monkeypatch.setattr(agent_module, "get_session_state", lambda: session)

        payload = agent._build_delegation_request(
            goal="检查一下当前文件，只做查看，不要修改代码。",
            iteration=2,
            total_tool_calls=2,
        )

        assert payload is None

    def test_build_delegation_request_keeps_failure_goal_on_diagnose_path(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        session = SimpleNamespace(
            get_attention_snapshot=lambda: {
                "recent_blockers": [
                    {"kind": "diagnostic_drift", "summary": "最近 traceback 指向 log_info/conversation_20260511_162502.jsonl"},
                ],
                "modified_paths": ["core/ui/cli_ui.py", "core/orchestration/delegation_governor.py"],
                "delegation_history": [],
                "delegation_failures": [],
                "delegation_evidence_digest": "",
                "last_validation_summary": "",
                "last_validation_passed": False,
                "diagnostic_drift": True,
            },
            has_recent_delegation=lambda *args, **kwargs: False,
            _normalize_scope_signature=lambda scope: str(scope),
        )
        monkeypatch.setattr(agent_module, "get_session_state", lambda: session)

        payload = agent._build_delegation_request(
            goal="检查为什么最近测试失败并出现 traceback，只做诊断，不要修改代码。",
            iteration=2,
            total_tool_calls=3,
        )

        assert payload is not None
        assert payload["task_type"] == "diagnose"

    def test_build_delegation_request_cools_down_repeated_unhelpful_diagnose_for_autonomous_goal(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        session = SimpleNamespace(
            get_attention_snapshot=lambda: {
                "recent_blockers": [
                    {"kind": "diagnostic_drift", "summary": "连续多步没有新增证据，先检查 log_info/conversation_20260510_135821.jsonl"},
                ],
                "modified_paths": [],
                "delegation_history": [
                    {"task_type": "diagnose", "status": "failed", "goal": "分析轮次A"},
                    {"task_type": "diagnose", "status": "failed", "goal": "分析轮次B"},
                ],
                "delegation_findings": [],
                "delegation_failures": [
                    {"task_type": "diagnose", "goal": "分析轮次A", "status": "failed"},
                    {"task_type": "diagnose", "goal": "分析轮次B", "status": "failed"},
                ],
                "delegation_evidence_digest": "",
                "last_validation_summary": "",
                "last_validation_passed": False,
                "diagnostic_drift": True,
            },
            has_recent_delegation=lambda *args, **kwargs: False,
            _normalize_scope_signature=lambda scope: str(scope),
        )
        monkeypatch.setattr(agent_module, "get_session_state", lambda: session)

        payload = agent._build_delegation_request(
            goal="开始自主进化",
            iteration=2,
            total_tool_calls=4,
        )

        assert payload is None

    def test_build_delegation_request_does_not_cooldown_after_recent_helpful_diagnose(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        session = SimpleNamespace(
            get_attention_snapshot=lambda: {
                "recent_blockers": [
                    {"kind": "diagnostic_drift", "summary": "连续多步没有新增证据，先检查 log_info/conversation_20260510_135821.jsonl"},
                ],
                "modified_paths": [],
                "delegation_history": [
                    {"task_type": "diagnose", "status": "failed", "goal": "分析轮次A"},
                    {
                        "task_type": "diagnose",
                        "status": "completed",
                        "goal": "分析轮次B",
                        "summary": "已定位 traceback 行号",
                        "findings": ["conversation_20260510_135821.jsonl:43"],
                        "confidence": "high",
                    },
                ],
                "delegation_findings": [
                    {
                        "task_type": "diagnose",
                        "status": "completed",
                        "goal": "分析轮次B",
                        "summary": "已定位 traceback 行号",
                        "findings": ["conversation_20260510_135821.jsonl:43"],
                        "confidence": "high",
                    },
                ],
                "delegation_failures": [],
                "delegation_evidence_digest": "已定位 traceback 行号",
                "last_validation_summary": "",
                "last_validation_passed": False,
                "diagnostic_drift": True,
            },
            has_recent_delegation=lambda *args, **kwargs: False,
            _normalize_scope_signature=lambda scope: str(scope),
        )
        monkeypatch.setattr(agent_module, "get_session_state", lambda: session)

        payload = agent._build_delegation_request(
            goal="开始自主进化",
            iteration=2,
            total_tool_calls=4,
        )

        assert payload is not None
        assert payload["task_type"] == "diagnose"

    def test_build_delegation_request_cools_down_repeated_low_value_inspect(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        session = SimpleNamespace(
            get_attention_snapshot=lambda: {
                "recent_blockers": [
                    {"kind": "context", "summary": "需要对照 core/ui/cli_ui.py 与 core/orchestration/delegation_governor.py 的配置差异。"},
                ],
                "modified_paths": ["core/ui/cli_ui.py", "core/orchestration/delegation_governor.py"],
                "delegation_history": [
                    {
                        "task_type": "inspect",
                        "status": "completed",
                        "goal": "检查链路A",
                        "summary": "",
                        "findings": [],
                        "confidence": "low",
                    },
                    {
                        "task_type": "inspect",
                        "status": "completed",
                        "goal": "检查链路B",
                        "summary": "",
                        "findings": [],
                        "confidence": "low",
                    },
                ],
                "delegation_findings": [],
                "delegation_failures": [],
                "delegation_evidence_digest": "",
                "last_validation_summary": "",
                "last_validation_passed": False,
                "diagnostic_drift": False,
            },
            has_recent_delegation=lambda *args, **kwargs: False,
            _normalize_scope_signature=lambda scope: str(scope),
        )
        monkeypatch.setattr(agent_module, "get_session_state", lambda: session)

        payload = agent._build_delegation_request(
            goal="开始自主进化",
            iteration=2,
            total_tool_calls=4,
        )

        assert payload is None

    def test_build_delegation_request_blocks_second_readonly_diagnosis_attempt_same_round(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        session = SimpleNamespace(
            get_attention_snapshot=lambda: {
                "recent_blockers": [
                    {"kind": "duplicate_read", "summary": "log_info/conversation_20260511_162502.jsonl 第 1-47 行与已读区间 1-47 高度重叠。"},
                ],
                "modified_paths": [],
                "delegation_history": [
                    {
                        "task_type": "diagnose",
                        "goal": "分析 log_info/conversation_20260511_162502.jsonl 中子 agent 为什么会超时，只做诊断，不要修改代码。",
                        "scope_signature": "goal=readonly",
                        "status": "completed",
                    }
                ],
                "delegation_failures": [],
                "last_validation_summary": "",
                "last_validation_passed": False,
                "diagnostic_drift": True,
            },
            has_recent_delegation=lambda *args, **kwargs: False,
            _normalize_scope_signature=lambda scope: str(scope),
        )
        monkeypatch.setattr(agent_module, "get_session_state", lambda: session)

        payload = agent._build_delegation_request(
            goal="分析 log_info/conversation_20260511_162502.jsonl 中子 agent 为什么会超时，只做诊断，不要修改代码。",
            iteration=2,
            total_tool_calls=0,
        )

        assert payload is None

    def test_restart_focus_detector_ignores_negative_restart_instruction(self):
        assert DelegationGovernor.is_restart_focused_goal(
            "执行非重启事务探针，不要调用 trigger_self_restart_tool。"
        ) is False
        assert DelegationGovernor.is_restart_focused_goal(
            "只做事务和验证探针，不要触发重启。"
        ) is False

    def test_full_evolution_goal_detector_requires_close_and_restart(self):
        assert DelegationGovernor.is_full_evolution_goal(
            "调用 close_evolution_transaction_tool 关账，关账成功后立即调用 trigger_self_restart_tool 完成重启。"
        ) is True
        assert DelegationGovernor.is_full_evolution_goal(
            "根据 lint 结果调用 close_evolution_transaction_tool 关账，成功则 status=success；关账成功后立即调用 trigger_self_restart_tool 完成重启。"
        ) is True
        assert DelegationGovernor.is_full_evolution_goal(
            "制定重启任务，然后调用 trigger_self_restart_tool 重启你自己。"
        ) is False
        assert DelegationGovernor.is_full_evolution_goal(
            "调用 close_evolution_transaction_tool 关账，不要触发重启。"
        ) is False

    def test_harness_probe_goal_is_not_delegated(self):
        governor = DelegationGovernor(
            spawn_execute=lambda *_args, **_kwargs: ("{}", None),
            sync_runtime_state_memory=lambda: None,
            ui_getter=lambda: None,
            session_getter=lambda: SimpleNamespace(get_attention_snapshot=lambda: {}),
        )

        request = governor.build_request(
            goal="执行一轮安全修改/回滚演化探针：写入 safe_modify_probe.py 并不要委派子 agent。",
            iteration=1,
            total_tool_calls=0,
        )

        assert request is None

    def test_gym_probe_goal_is_not_delegated(self):
        governor = DelegationGovernor(
            spawn_execute=lambda *_args, **_kwargs: ("{}", None),
            sync_runtime_state_memory=lambda: None,
            ui_getter=lambda: None,
            session_getter=lambda: SimpleNamespace(
                get_attention_snapshot=lambda: {
                    "diagnostic_drift": True,
                    "recent_blockers": [{"kind": "diagnostic_drift", "summary": "连续推理"}],
                }
            ),
        )

        request = governor.build_request(
            goal=(
                "Run this coordination workflow Gym probe in the main agent only. "
                "Do not call spawn_agent_tool. Do not delegate."
            ),
            iteration=2,
            total_tool_calls=2,
        )

        assert request is None

    def test_active_evolution_transaction_suppresses_autonomous_delegation(self):
        governor = DelegationGovernor(
            spawn_execute=lambda *_args, **_kwargs: ("{}", None),
            sync_runtime_state_memory=lambda: None,
            ui_getter=lambda: None,
            session_getter=lambda: SimpleNamespace(
                get_attention_snapshot=lambda: {
                    "active_evolution_txn_id": "txn_1",
                    "diagnostic_drift": True,
                    "recent_blockers": [{"kind": "diagnostic_drift", "summary": "连续推理"}],
                }
            ),
        )

        request = governor.build_request(
            goal="继续当前事务闭环",
            iteration=2,
            total_tool_calls=2,
        )

        assert request is None

    def test_readonly_subagent_process_never_delegates(self, monkeypatch):
        monkeypatch.setenv("VIBELUTION_SUBAGENT_MODE", "readonly")
        governor = DelegationGovernor(
            spawn_execute=lambda *_args, **_kwargs: ("{}", None),
            sync_runtime_state_memory=lambda: None,
            ui_getter=lambda: None,
            session_getter=lambda: SimpleNamespace(get_attention_snapshot=lambda: {}),
        )

        request = governor.build_request(
            goal="分析 log_info/conversation_20260511_162502.jsonl 中子 agent 为什么会超时，只做诊断。",
            iteration=1,
            total_tool_calls=0,
        )

        assert request is None

    def test_spawn_agent_rejects_nested_subagent_depth(self, monkeypatch):
        monkeypatch.setenv("VIBELUTION_SUBAGENT_DEPTH", "1")

        payload = json.loads(
            spawn_agent_impl(
                goal="分析最近日志",
                task_type="diagnose",
                constraints={"readonly": True},
            )
        )

        assert payload["status"] == "error"
        assert payload["code"] == "MAX_RECURSION"
        assert "不允许继续派发子 agent" in payload["message"]

    def test_spawn_agent_rejects_non_fixed_task_type(self):
        payload = json.loads(
            spawn_agent_impl(
                goal="顺手看一下",
                task_type="verify",
            )
        )

        assert payload["status"] == "error"
        assert payload["code"] == "UNSUPPORTED_SUBAGENT_TASK_TYPE"

    def test_apply_delegation_result_treats_partial_readonly_diagnosis_as_useful_and_stops(self):
        events = {"logs": [], "contents": [], "finished": []}

        class DummyUI:
            def add_log(self, text, level="INFO"):
                events["logs"].append((level, text))

            def add_content(self, text):
                events["contents"].append(text)

            def add_delegation_evidence(self, summary, next_action="", confidence=""):
                events["evidence"] = (summary, next_action, confidence)

            def finish_subagent_activity(self, **kwargs):
                events["finished"].append(kwargs)

        class DummySession:
            def record_delegation_result(self, *args, **kwargs):
                events["recorded_result"] = (args, kwargs)

            def note_diagnostic_observation(self, text):
                events["observation"] = text

            def note_scope_completion(self, reason=""):
                events["scope_completion"] = reason

        governor = DelegationGovernor(
            spawn_execute=lambda *_args, **_kwargs: ("{}", None),
            sync_runtime_state_memory=lambda: None,
            ui_getter=lambda: DummyUI(),
            session_getter=lambda: DummySession(),
        )
        payload = {
            "task_type": "diagnose",
            "goal": "分析当前轮为什么出现：log_info/conversation_20260511_162502.jsonl 第 1-47 行与已读区间 1-47 高度重叠。",
            "root_goal": "分析 log_info/conversation_20260511_162502.jsonl 中子 agent 为什么会超时，只做诊断，不要修改代码。",
            "scope": {"goal": "same"},
        }
        messages = []

        outcome = governor.apply_result(
            payload,
            json.dumps(
                {
                    "status": "partial",
                    "summary": "已确认日志截断导致诊断证据不足。",
                    "findings": ["日志是长行 JSONL", "read_file_tool 能读到 line 43 traceback"],
                    "evidence": ["conversation_20260511_162502.jsonl:43"],
                    "recommended_next_action": "主 agent 根据现有证据直接收束",
                    "confidence": "medium",
                },
                ensure_ascii=False,
            ),
            messages,
        )

        assert outcome["delegated"] is True
        assert outcome["useful"] is True
        assert outcome["break_round"] is True
        assert messages
        assert isinstance(messages[-1], SystemMessage)
        assert "委派证据" in messages[-1].content
        assert events["finished"]
        assert "observation" not in events
        assert events["scope_completion"]

    def test_apply_delegation_result_marks_fast_path_ui_hint(self):
        events = {"finished": []}

        class DummyUI:
            def add_log(self, *_args, **_kwargs):
                return None

            def add_content(self, *_args, **_kwargs):
                return None

            def add_delegation_evidence(self, *_args, **_kwargs):
                return None

            def finish_subagent_activity(self, **kwargs):
                events["finished"].append(kwargs)

        class DummySession:
            def record_delegation_result(self, *args, **kwargs):
                return None

            def note_diagnostic_observation(self, _text):
                return None

            def note_scope_completion(self, _reason=""):
                return None

        governor = DelegationGovernor(
            spawn_execute=lambda *_args, **_kwargs: ("{}", None),
            sync_runtime_state_memory=lambda: None,
            ui_getter=lambda: DummyUI(),
            session_getter=lambda: DummySession(),
        )

        payload = {
            "task_type": "diagnose",
            "goal": "分析当前轮为什么超时",
            "root_goal": "分析 log_info/conversation_20260511_162502.jsonl 中子 agent 为什么会超时，只做诊断，不要修改代码。",
            "scope": {"goal": "same"},
        }
        result = json.dumps(
            {
                "status": "completed",
                "summary": "OSError: [Errno 22] Invalid argument",
                "findings": ["第 43 行命中异常线索。"],
                "evidence": ["conversation_20260511_162502.jsonl:43"],
                "recommended_next_action": "主 agent 可依据异常行直接收束。",
                "confidence": "high",
                "fast_path": "conversation_log_scan",
            },
            ensure_ascii=False,
        )

        governor.apply_result(payload, result, [])

        assert events["finished"]
        assert events["finished"][0]["mode_hint"] == "快速日志诊断，未启动真实子 agent"

    def test_build_delegation_request_blocks_completed_same_goal_even_when_scope_changes(self, monkeypatch):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        goal = "分析当前轮为什么出现：core/infrastructure/tool_executor.py 第 561-640 行本轮已读过。"

        class DummySession:
            def get_attention_snapshot(self):
                return {
                    "recent_blockers": [
                        {"kind": "duplicate_read", "summary": "core/infrastructure/tool_executor.py 第 561-640 行本轮已读过。"},
                        {"kind": "observation", "summary": "子 agent 已返回: 已定位重复读取来自续读链断裂。"},
                    ],
                    "modified_paths": [],
                    "delegation_history": [
                        {
                            "task_type": "diagnose",
                            "goal": goal,
                            "scope_signature": "recent_blockers=['duplicate_read']",
                            "status": "completed",
                            "summary": "已定位重复读取来自续读链断裂。",
                            "confidence": "high",
                        }
                    ],
                    "delegation_findings": [
                        {
                            "task_type": "diagnose",
                            "goal": goal,
                            "status": "completed",
                            "summary": "已定位重复读取来自续读链断裂。",
                            "confidence": "high",
                        }
                    ],
                    "delegation_failures": [],
                    "delegation_evidence_digest": "已定位重复读取来自续读链断裂。",
                    "last_validation_summary": "",
                    "last_validation_passed": False,
                    "diagnostic_drift": True,
                }

            def has_recent_delegation(self, task_type, delegation_goal, scope):
                return delegation_goal == goal

            def _normalize_scope_signature(self, scope):
                return str(scope)

        monkeypatch.setattr(agent_module, "get_session_state", lambda: DummySession())

        payload = agent._build_delegation_request(
            goal="继续完成同一个用户目标：继续吧\n上一内部回合仍未完成用户目标（第 1 轮）。",
            iteration=3,
            total_tool_calls=8,
        )

        assert payload is None

    def test_apply_delegation_result_rejects_think_only_summary(self):
        events = {"logs": [], "finished": []}

        class DummyUI:
            def add_log(self, text, level="INFO"):
                events["logs"].append((level, text))

            def add_content(self, *_args, **_kwargs):
                return None

            def add_delegation_evidence(self, *_args, **_kwargs):
                return None

            def finish_subagent_activity(self, **kwargs):
                events["finished"].append(kwargs)

        class DummySession:
            def __init__(self):
                self.failures = []

            def record_delegation_result(self, *args, **kwargs):
                events["unexpected_success"] = (args, kwargs)

            def note_diagnostic_observation(self, _text):
                events["unexpected_observation"] = True

            def record_delegation_failure(self, *_args):
                self.failures.append(_args)

        session = DummySession()
        governor = DelegationGovernor(
            spawn_execute=lambda *_args, **_kwargs: ("{}", None),
            sync_runtime_state_memory=lambda: None,
            ui_getter=lambda: DummyUI(),
            session_getter=lambda: session,
        )
        payload = {
            "task_type": "diagnose",
            "goal": "分析重复调用",
            "root_goal": "分析重复调用，只做诊断，不要修改代码。",
            "scope": {"goal": "same"},
        }
        messages = []

        outcome = governor.apply_result(
            payload,
            json.dumps(
                {
                    "status": "completed",
                    "summary": "<think>Let me inspect more logs.</think>",
                    "findings": [],
                    "evidence": [],
                    "recommended_next_action": "",
                    "confidence": "",
                },
                ensure_ascii=False,
            ),
            messages,
        )

        assert outcome["delegated"] is True
        assert outcome["useful"] is False
        assert session.failures
        assert messages
        assert isinstance(messages[-1], SystemMessage)
        assert messages[-1].content.startswith("## 委派失败")
        assert "unexpected_success" not in events

    def test_restart_focus_guard_blocks_unrelated_file_edits(self):
        agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
        agent._active_goal = "制定重启任务，然后对重启任务打勾，然后运行 `trigger_self_restart_tool` 重启你自己。"

        blocked = agent._guard_tool_execution("apply_diff_edit_tool", {"file_path": "tools/agent_tools.py"})
        allowed = agent._guard_tool_execution("trigger_self_restart_tool", {"reason": "test"})

        assert blocked is not None
        assert "重启测试模式" in blocked
        assert allowed is None
