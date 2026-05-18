#!/usr/bin/env python3
"""
启动链路稳定性回归测试
"""

import importlib
import io
from types import SimpleNamespace
from unittest.mock import MagicMock

import agent as agent_module
from core.infrastructure import cli_utils


def make_args(**overrides):
    base = {
        "test": False,
        "prompt": None,
        "auto": False,
        "shell": False,
        "no_shell": False,
        "supervised_evolution": False,
        "post_restart_observe_seconds": 20,
        "bundle": None,
        "dataset": None,
        "choose_dataset": False,
        "dataset_limit": None,
        "list_datasets": False,
        "keep_worktree": False,
        "config_path": None,
        "model_name": None,
        "temperature": None,
        "awake_interval": None,
        "mode": None,
        "name": None,
        "log_level": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_import_has_no_stdout_side_effect(monkeypatch):
    fake_stdout = io.StringIO()
    fake_stderr = io.StringIO()
    monkeypatch.setattr(agent_module.sys, "stdout", fake_stdout)
    monkeypatch.setattr(agent_module.sys, "stderr", fake_stderr)

    reloaded = importlib.reload(agent_module)

    assert reloaded.sys.stdout is fake_stdout
    assert reloaded.sys.stderr is fake_stderr


def test_initialize_ui_for_run_skips_live_in_test_mode():
    ui = MagicMock()

    agent_module.initialize_ui_for_run(ui, test_mode=True)

    ui.console.clear.assert_not_called()
    ui.start_live.assert_not_called()


def test_initialize_ui_for_run_starts_live_in_normal_mode():
    ui = MagicMock()

    agent_module.initialize_ui_for_run(ui, test_mode=False)

    ui.console.clear.assert_called_once_with()
    ui.start_live.assert_called_once_with()


def test_create_config_from_args_applies_cli_overrides(monkeypatch):
    captured = {}

    class FakeSettings:
        def __init__(self, *, config_path=None, **kwargs):
            captured["config_path"] = config_path
            captured["kwargs"] = kwargs
            self.config = SimpleNamespace(log=SimpleNamespace(level="INFO"))

    monkeypatch.setattr(cli_utils, "Settings", FakeSettings)

    agent_module.create_config_from_args(
        make_args(
            config_path="custom.toml",
            model_name="gpt-test",
            temperature=0.3,
            awake_interval=9,
            name="Tester",
            log_level="DEBUG",
            profile="safe_local",
            skip_doctor=True,
        )
    )

    assert captured["config_path"] == "custom.toml"
    assert captured["kwargs"] == {
        "llm.profiles.primary.model": "gpt-test",
        "llm.profiles.primary.temperature": 0.3,
        "agent.awake_interval": 9,
        "agent.name": "Tester",
        "log.level": "DEBUG",
        "runtime.profile": "safe_local",
        "runtime.preflight_doctor": False,
    }


def test_main_test_mode_uses_headless_bootstrap(monkeypatch):
    ui = MagicMock()
    config = SimpleNamespace(
        log=SimpleNamespace(level="INFO"),
        llm=SimpleNamespace(
            get_profile=lambda role="primary": SimpleNamespace(model="local-model")
        ),
        agent=SimpleNamespace(awake_interval=30),
    )
    created = {}

    class DummyAgent:
        def __init__(self, config):
            created["config"] = config
            self.key_tools = ["a", "b"]

        def run_loop(self, initial_prompt=None):
            created["initial_prompt"] = initial_prompt

    monkeypatch.setattr(agent_module, "get_ui", lambda: ui)
    monkeypatch.setattr(agent_module, "create_config_from_args", lambda _args: config)
    monkeypatch.setattr(agent_module, "setup_logging", lambda **_kwargs: None)
    monkeypatch.setattr(agent_module, "SelfEvolvingAgent", DummyAgent)
    monkeypatch.setattr(agent_module, "set_ui_test_mode", lambda enabled: created.setdefault("test_mode", enabled))
    monkeypatch.setattr(agent_module.sys, "__stdout__", io.StringIO())
    monkeypatch.setattr(agent_module, "should_launch_workbench", lambda *_args, **_kwargs: False)

    agent_module.main(args=make_args(test=True))

    assert created["test_mode"] is True
    assert created["config"] is config
    assert created["initial_prompt"] == agent_module.EVOLUTION_TEST_PROMPT
    ui.console.clear.assert_not_called()
    ui.start_live.assert_not_called()


def test_main_runs_preflight_doctor_in_normal_mode(monkeypatch):
    ui = MagicMock()
    created = {}
    config = SimpleNamespace(
        log=SimpleNamespace(level="INFO"),
        llm=SimpleNamespace(
            get_profile=lambda role="primary": SimpleNamespace(model="local-model")
        ),
        agent=SimpleNamespace(awake_interval=30),
        runtime=SimpleNamespace(preflight_doctor=True, require_venv=True),
    )

    class DummyAgent:
        def __init__(self, config):
            self.key_tools = []

        def run_loop(self, initial_prompt=None):
            created["initial_prompt"] = initial_prompt

    monkeypatch.setattr(agent_module, "get_ui", lambda: ui)
    monkeypatch.setattr(agent_module, "create_config_from_args", lambda _args: config)
    monkeypatch.setattr(agent_module, "setup_logging", lambda **_kwargs: None)
    monkeypatch.setattr(agent_module, "SelfEvolvingAgent", DummyAgent)
    monkeypatch.setattr(agent_module, "run_preflight_doctor", lambda _config: created.setdefault("doctor_ran", True))
    monkeypatch.setattr(agent_module, "should_launch_workbench", lambda *_args, **_kwargs: False)

    agent_module.main(args=make_args(auto=True))

    assert created["doctor_ran"] is True


def test_should_launch_workbench_defaults_to_true_without_task():
    assert agent_module.should_launch_workbench(make_args(), None) is True
    assert agent_module.should_launch_workbench(make_args(auto=True), None) is False
    assert agent_module.should_launch_workbench(make_args(test=True), None) is False
    assert agent_module.should_launch_workbench(make_args(supervised_evolution=True), None) is False
    assert agent_module.should_launch_workbench(make_args(choose_dataset=True), None) is False
    assert agent_module.should_launch_workbench(make_args(list_datasets=True), None) is False
    assert agent_module.should_launch_workbench(make_args(no_shell=True), None) is False
    assert agent_module.should_launch_workbench(make_args(), "hello") is False


def test_should_launch_workbench_skips_shell_after_restart(monkeypatch):
    monkeypatch.setenv("AGENT_RESTART_REASON", "code_update")
    assert agent_module.should_launch_workbench(make_args(), None) is False


def test_main_launches_workbench_when_idle(monkeypatch):
    ui = MagicMock()
    config = SimpleNamespace(
        log=SimpleNamespace(level="INFO"),
        llm=SimpleNamespace(
            get_profile=lambda role="primary": SimpleNamespace(model="local-model")
        ),
        runtime=SimpleNamespace(preflight_doctor=True, require_venv=True),
    )
    shell = MagicMock()

    monkeypatch.setattr(agent_module, "get_ui", lambda: ui)
    monkeypatch.setattr(agent_module, "create_config_from_args", lambda _args: config)
    monkeypatch.setattr(agent_module, "setup_logging", lambda **_kwargs: None)
    monkeypatch.setattr(agent_module, "run_preflight_doctor", lambda _config: None)
    monkeypatch.setattr(agent_module, "AgentWorkbenchShell", lambda config=None: shell)
    monkeypatch.setattr(agent_module, "should_launch_workbench", lambda *_args, **_kwargs: True)

    agent_module.main(args=make_args())

    shell.run.assert_called_once()
    ui.reset_workspace.assert_called_once()


def test_main_routes_supervised_evolution_through_agent_entry(monkeypatch):
    from core.infrastructure import boot_pipeline

    ui = MagicMock()
    config = SimpleNamespace(
        log=SimpleNamespace(level="INFO"),
        llm=SimpleNamespace(get_profile=lambda role="primary": SimpleNamespace(model="local-model")),
        runtime=SimpleNamespace(preflight_doctor=True, require_venv=True),
    )
    captured = {}

    monkeypatch.setattr(agent_module, "get_ui", lambda: ui)
    monkeypatch.setattr(agent_module, "create_config_from_args", lambda _args: config)
    monkeypatch.setattr(agent_module, "setup_logging", lambda **_kwargs: None)
    monkeypatch.setattr(agent_module, "run_preflight_doctor", lambda _config: captured.setdefault("doctor_ran", True))
    def fake_supervised_cli(*, args, project_root):
        captured["args"] = args
        captured["project_root"] = project_root
        return 0

    monkeypatch.setattr(boot_pipeline, "run_supervised_cli_from_args", fake_supervised_cli)

    try:
        agent_module.main(args=make_args(supervised_evolution=True, choose_dataset=True))
    except SystemExit as exc:
        exit_code = exc.code
    else:
        exit_code = None

    assert exit_code == 0
    assert captured["doctor_ran"] is True
    assert captured["args"].supervised_evolution is True
    ui.reset_workspace.assert_not_called()


def test_main_restarted_process_bypasses_workbench_and_reenters_agent_loop(monkeypatch):
    ui = MagicMock()
    created = {}
    config = SimpleNamespace(
        log=SimpleNamespace(level="INFO"),
        llm=SimpleNamespace(
            get_profile=lambda role="primary": SimpleNamespace(model="local-model")
        ),
        agent=SimpleNamespace(awake_interval=30),
    )

    class DummyAgent:
        def __init__(self, config):
            created["config"] = config
            self.key_tools = ["tool"]

        def run_loop(self, initial_prompt=None):
            created["initial_prompt"] = initial_prompt

    monkeypatch.setenv("AGENT_RESTART_REASON", "code_update")
    monkeypatch.setattr(agent_module, "get_ui", lambda: ui)
    monkeypatch.setattr(agent_module, "create_config_from_args", lambda _args: config)
    monkeypatch.setattr(agent_module, "setup_logging", lambda **_kwargs: None)
    monkeypatch.setattr(agent_module, "SelfEvolvingAgent", DummyAgent)
    monkeypatch.setattr(agent_module, "run_preflight_doctor", lambda _config: created.setdefault("doctor_ran", True))
    monkeypatch.setattr(agent_module, "AgentWorkbenchShell", lambda config=None: created.setdefault("shell_created", True))

    agent_module.main(args=make_args())

    assert created["doctor_ran"] is True
    assert created["config"] is config
    assert created["initial_prompt"] is None
    assert "shell_created" not in created
    ui.reset_workspace.assert_not_called()


def test_main_passes_resolved_agent_mode_when_supported(monkeypatch):
    ui = MagicMock()
    created = {}
    config = SimpleNamespace(
        log=SimpleNamespace(level="INFO"),
        llm=SimpleNamespace(
            get_profile=lambda role="primary": SimpleNamespace(model="local-model")
        ),
        agent=SimpleNamespace(
            awake_interval=30,
            default_mode="self_evolution",
            modes=SimpleNamespace(
                default_headless_mode="self_evolution",
                default_shell_mode="chat",
            ),
        ),
        runtime=SimpleNamespace(preflight_doctor=False, require_venv=False),
    )

    class DummyAgent:
        def __init__(self, config, mode=None):
            created["mode"] = mode
            self.key_tools = []

        def run_loop(self, initial_prompt=None):
            created["initial_prompt"] = initial_prompt

    monkeypatch.setattr(agent_module, "get_ui", lambda: ui)
    monkeypatch.setattr(agent_module, "create_config_from_args", lambda _args: config)
    monkeypatch.setattr(agent_module, "setup_logging", lambda **_kwargs: None)
    monkeypatch.setattr(agent_module, "SelfEvolvingAgent", DummyAgent)
    monkeypatch.setattr(agent_module, "should_launch_workbench", lambda *_args, **_kwargs: False)

    agent_module.main(args=make_args(auto=True, mode="chat"))

    assert created["mode"] == "chat"
    assert created["initial_prompt"] is None
