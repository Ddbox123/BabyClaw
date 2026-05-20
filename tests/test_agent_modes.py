#!/usr/bin/env python3
"""Agent mode 分层回归测试。"""

from types import SimpleNamespace

import agent as agent_module
from agent import SelfEvolvingAgent
from core.orchestration.agent_modes import AgentMode, looks_like_explicit_evolution_request, resolve_mode_policy


def _make_config():
    return SimpleNamespace(
        agent=SimpleNamespace(
            default_mode="self_evolution",
            modes=SimpleNamespace(
                chat_enabled=True,
                self_evolution_enabled=True,
                supervised_evolution_enabled=True,
                default_shell_mode="chat",
                default_headless_mode="self_evolution",
                explicit_evolution_request_behavior="route_to_workbench",
            ),
        ),
    )


def test_resolve_mode_policy_keeps_mode_logic_in_core():
    config = _make_config()

    chat = resolve_mode_policy("chat", config)
    supervised = resolve_mode_policy("supervised_evolution", config)

    assert chat.orchestrator_kind == "chat"
    assert chat.allow_auto_loop is False
    assert chat.capture_chat_dataset_candidates is True
    assert supervised.orchestrator_kind == "evolution"
    assert supervised.reset_context_between_cases is True
    assert supervised.allow_direct_supervised_payload is True


def test_chat_mode_routes_explicit_evolution_request_without_running_orchestrator():
    agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
    agent.config = _make_config()
    agent.mode = AgentMode.CHAT
    agent.mode_policy = resolve_mode_policy("chat", agent.config)
    agent._last_visible_response_text = ""
    agent._last_response_tool_calls = 0
    agent._last_turn_metadata = {}
    agent._run_orchestrated_turn = lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("should not run"))

    ok = agent._run_chat_turn(user_prompt="开始自主进化", goal_override=None)

    assert ok is True
    assert looks_like_explicit_evolution_request("开始自主进化") is True
    assert agent._last_turn_metadata["evolution_route_requested"] is True
    assert agent._last_turn_metadata["route_target"] == "workbench_evolution"


def test_seed_chat_history_seeds_mental_conversation_context():
    agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
    agent.config = _make_config()
    agent.mode = AgentMode.CHAT
    agent.mode_policy = resolve_mode_policy("chat", agent.config)
    captured = {}
    agent.mental_model = SimpleNamespace(
        seed_conversation_context=lambda messages: captured.setdefault("messages", list(messages))
    )

    agent.seed_chat_history([
        {
            "role": "user",
            "content": "你话还没说完",
            "timestamp": "2026-05-20T14:00:00",
        },
        {
            "role": "assistant",
            "content": "这是一个被截断的心智模型回答。",
            "mental_snapshot": {
                "mood": "沉思",
                "feeling": "正在延续心智模型话题。",
            },
            "timestamp": "2026-05-20T14:01:00",
        },
    ])

    assert captured["messages"][0]["content"] == "你话还没说完"
    assert captured["messages"][1]["mental_snapshot"]["mood"] == "沉思"
    assert agent._active_turn_goal == "__chat_session__"


def test_seed_chat_history_clears_mental_context_outside_chat_mode():
    agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
    agent.config = _make_config()
    agent.mode = AgentMode.SELF_EVOLUTION
    agent.mode_policy = resolve_mode_policy("self_evolution", agent.config)
    called = {}
    agent.mental_model = SimpleNamespace(clear_conversation_context=lambda: called.setdefault("cleared", True))

    agent.seed_chat_history([{"role": "user", "content": "不应恢复到自进化模式"}])

    assert called["cleared"] is True


def test_supervised_case_reset_clears_short_term_context(monkeypatch):
    agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
    agent.config = _make_config()
    agent.mode = AgentMode.SUPERVISED_EVOLUTION
    agent.mode_policy = resolve_mode_policy("supervised_evolution", agent.config)
    agent._active_turn_messages = ["a", "b"]
    agent._active_turn_goal = "goal"
    agent._active_goal = "goal"
    agent._carryover_state_memory = "memory"
    agent._last_runtime_state_memory = "memory"
    agent._last_runtime_state_memory_key = "key"
    agent._chat_turn_records = [object()]
    agent._active_supervised_case_id = "case_1"
    agent.prompt_manager = SimpleNamespace(
        clear_state_memory=lambda persist=False: None,
        update_current_goal=lambda goal: None,
    )

    session = SimpleNamespace(
        reset_runtime_constraints=lambda: setattr(agent, "_runtime_constraints_reset", True),
        set_active_evolution_txn=lambda txn_id: setattr(agent, "_txn_reset", txn_id),
    )
    monkeypatch.setattr(agent_module, "get_session_state", lambda: session)

    agent._reset_mode_context_for_supervised_case("case_2")

    assert agent._active_turn_messages is None
    assert agent._active_turn_goal == ""
    assert agent._active_goal == ""
    assert agent._carryover_state_memory == ""
    assert agent._chat_turn_records == []
    assert agent._active_supervised_case_id == "case_2"
    assert agent._runtime_constraints_reset is True
    assert agent._txn_reset is None
