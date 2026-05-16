#!/usr/bin/env python3
"""
进化重启闸门回归测试
"""

from types import SimpleNamespace

from tools import rebirth_tools as rebirth_module


def test_handle_restart_request_blocks_when_environment_smoke_fails(monkeypatch):
    close_calls = []

    monkeypatch.setattr(
        rebirth_module,
        "trigger_self_restart_tool",
        lambda **_kwargs: "should not restart",
    )
    monkeypatch.setattr(rebirth_module, "_open_restart_transaction", lambda _reason="": "txn_1")
    monkeypatch.setattr(
        rebirth_module,
        "_close_restart_transaction",
        lambda txn_id, status, summary="": close_calls.append((txn_id, status, summary)),
    )

    monkeypatch.setitem(
        __import__("sys").modules,
        "tools.memory_tools",
        SimpleNamespace(check_restart_block=lambda: (False, "")),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "core.infrastructure.test_gate",
        SimpleNamespace(check_environment_ready=lambda: (False, "environment broken")),
    )

    result, action = rebirth_module.handle_restart_request(
        tool_args={"reason": "test"},
        messages=[],
        self_modified=False,
    )

    assert action is None
    assert "[ENVIRONMENT GATE FAILED]" in result
    assert close_calls and close_calls[-1][1] == "failed"


def test_handle_restart_request_runs_full_test_gate_after_environment_smoke(monkeypatch):
    calls = []
    close_calls = []

    monkeypatch.setattr(
        rebirth_module,
        "trigger_self_restart_tool",
        lambda **_kwargs: "restart ok",
    )
    monkeypatch.setattr(rebirth_module, "_open_restart_transaction", lambda _reason="": "txn_2")
    monkeypatch.setattr(
        rebirth_module,
        "_close_restart_transaction",
        lambda txn_id, status, summary="": close_calls.append((txn_id, status, summary)),
    )

    monkeypatch.setitem(
        __import__("sys").modules,
        "tools.memory_tools",
        SimpleNamespace(check_restart_block=lambda: (False, "")),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "core.infrastructure.test_gate",
        SimpleNamespace(
            check_environment_ready=lambda: (calls.append("env") or True, "env ok"),
            check_evolution_ready=lambda: (calls.append("full") or True, "full ok"),
        ),
    )

    result, action = rebirth_module.handle_restart_request(
        tool_args={"reason": "test"},
        messages=[],
        self_modified=True,
    )

    assert action == "restart"
    assert result == "restart ok"
    assert calls == ["env", "full"]
    assert close_calls and close_calls[-1][1] == "success"


def test_handle_restart_request_does_not_restart_when_trigger_fails(monkeypatch):
    close_calls = []

    monkeypatch.setattr(
        rebirth_module,
        "trigger_self_restart_tool",
        lambda **_kwargs: "错误: 启动重启进程失败",
    )
    monkeypatch.setattr(rebirth_module, "_open_restart_transaction", lambda _reason="": "txn_3")
    monkeypatch.setattr(
        rebirth_module,
        "_close_restart_transaction",
        lambda txn_id, status, summary="": close_calls.append((txn_id, status, summary)),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "tools.memory_tools",
        SimpleNamespace(check_restart_block=lambda: (False, "")),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "core.infrastructure.test_gate",
        SimpleNamespace(check_environment_ready=lambda: (True, "env ok")),
    )

    result, action = rebirth_module.handle_restart_request(
        tool_args={"reason": "test"},
        messages=[],
        self_modified=False,
    )

    assert action is None
    assert "错误" in result
    assert close_calls and close_calls[-1][1] == "failed"
