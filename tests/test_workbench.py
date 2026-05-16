#!/usr/bin/env python3
"""工作台模式入口测试"""

import json
from types import SimpleNamespace
from pathlib import Path

from core.ui.workbench import AgentWorkbenchShell


class _FakeConsole:
    def __init__(self):
        self.items = []

    def print(self, *args, **kwargs):
        self.items.append((args, kwargs))
        return None


class _FakeUI:
    def __init__(self):
        self.console = _FakeConsole()
        self.shell_modes = []
        self.reset_workspace_calls = 0
        self.start_live_calls = 0
        self.stop_live_calls = 0

    def set_avatar_preset(self, preset):
        return None

    def set_shell_mode(self, mode):
        self.shell_modes.append(mode)

    def clear(self):
        return None

    def reset_workspace(self):
        self.reset_workspace_calls += 1

    def start_live(self):
        self.start_live_calls += 1

    def stop_live(self):
        self.stop_live_calls += 1


def test_workbench_config_panel_uses_default_panel_port(monkeypatch):
    shell = AgentWorkbenchShell(config=SimpleNamespace(avatar=SimpleNamespace(preset="default")))
    shell.ui = _FakeUI()
    opened = {}

    class FakeProcess:
        pass

    def fake_popen(cmd, **kwargs):
        opened["cmd"] = cmd
        opened["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr("core.ui.workbench.subprocess.Popen", fake_popen)
    monkeypatch.setattr("core.ui.workbench.webbrowser.open", lambda url: opened.setdefault("url", url))
    monkeypatch.setattr("core.ui.workbench.time.sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("core.ui.workbench.Prompt.ask", lambda *args, **kwargs: "")

    shell._open_config_panel()

    assert opened["url"] == "http://127.0.0.1:8765/"
    assert "--port" in opened["cmd"]
    assert opened["cmd"][opened["cmd"].index("--port") + 1] == "8765"
    assert shell._recent_status == "已打开配置页面：http://127.0.0.1:8765/"


def test_workbench_supervised_evolution_path_updates_status(monkeypatch):
    shell = AgentWorkbenchShell(config=SimpleNamespace(avatar=SimpleNamespace(preset="default")))
    fake_ui = _FakeUI()
    shell.ui = fake_ui

    prompts = iter(["2", "demo_bundle", "y", "n", "q"])
    monkeypatch.setattr("core.ui.workbench.Prompt.ask", lambda *args, **kwargs: next(prompts))

    class Decision:
        session_id = "supervised_demo"
        bundle_name = "demo_bundle"
        started_at = "2026-05-14T00:00:00Z"
        ended_at = "2026-05-14T00:00:01Z"
        benchmark = "dry"
        baseline_runs = []
        candidate_runs = []
        baseline_summary = SimpleNamespace(
            total=1,
            successes=1,
            avg_wall_clock_seconds=1.0,
            validation_passed=1,
            validation_failed=0,
            total_guarded_tools=2,
        )
        candidate_summary = SimpleNamespace(
            total=1,
            successes=1,
            avg_wall_clock_seconds=1.0,
            validation_passed=1,
            validation_failed=0,
            total_guarded_tools=2,
        )
        case_summaries = []
        gates = []
        decision = "HOLD"
        baseline_success_rate = 1.0
        candidate_success_rate = 1.0
        score_delta = 0.0
        reason = "tie"
        summary = {}
        decision_path = "workspace/supervised_evolution/decisions/demo.json"
        policy_action = {"action": "HOLD", "summary": "已将 1 个 case 放入观察池"}

    monkeypatch.setattr(
        "core.evaluation.supervised_evolution.run_supervised_evolution_session",
        lambda **kwargs: Decision(),
    )

    shell._run_supervised_evolution()

    assert "supervised_evolution" in fake_ui.shell_modes
    assert shell._recent_status == "监督进化完成：HOLD"


def test_workbench_home_routes_option_five_to_evolution_console(monkeypatch):
    shell = AgentWorkbenchShell(config=SimpleNamespace(avatar=SimpleNamespace(preset="default")))
    fake_ui = _FakeUI()
    shell.ui = fake_ui
    calls = []

    prompts = iter(["5", "q"])
    monkeypatch.setattr("core.ui.workbench.Prompt.ask", lambda *args, **kwargs: next(prompts))
    shell._run_evolution_console = lambda agent_factory: calls.append(agent_factory)

    assert shell.run(agent_factory=lambda: SimpleNamespace()) == 0
    assert len(calls) == 1


def test_workbench_agent_self_evolution_entry_runs_agent_loop(monkeypatch):
    shell = AgentWorkbenchShell(config=SimpleNamespace(avatar=SimpleNamespace(preset="default")))
    fake_ui = _FakeUI()
    shell.ui = fake_ui
    launched = {}
    asked = []
    preview_goal = {}

    class DummyAgent:
        def run_loop(self, initial_prompt=None):
            launched["initial_prompt"] = initial_prompt

    def fake_prompt(label, *args, **kwargs):
        asked.append(label)
        return "y"

    monkeypatch.setattr("core.ui.workbench.Prompt.ask", fake_prompt)

    def fake_preview(goal=None):
        preview_goal["value"] = goal
        return f"preview:{goal}"

    monkeypatch.setattr("core.ui.workbench.build_self_evolution_preview", fake_preview)

    shell._run_agent_self_evolution(lambda: DummyAgent())

    assert launched["initial_prompt"] == "开始自主进化"
    assert preview_goal["value"] == "开始自主进化"
    assert "self_evolution" in fake_ui.shell_modes
    assert fake_ui.reset_workspace_calls == 1
    assert fake_ui.start_live_calls == 1
    assert fake_ui.stop_live_calls == 1
    assert asked == ["开始运行？(Y/n)"]
    assert shell._recent_status == "Agent 自进化会话已结束"


def test_workbench_chat_redirects_evolution_request(monkeypatch):
    shell = AgentWorkbenchShell(config=SimpleNamespace(avatar=SimpleNamespace(preset="default")))
    fake_ui = _FakeUI()
    shell.ui = fake_ui
    prompts = iter(["开始自主进化", "/back"])
    calls = []

    class DummyAgent:
        def run_single_turn(self, initial_prompt=None):
            calls.append(initial_prompt)

    monkeypatch.setattr("core.ui.workbench.Prompt.ask", lambda *args, **kwargs: next(prompts))

    shell._run_chat(lambda: DummyAgent())

    printed = "\n".join(str(getattr(args[0], "renderable", args[0])) for args, _kwargs in fake_ui.console.items)
    assert "`进化` 入口" in printed
    assert calls == []
    assert shell._recent_status == "对话会话已结束"


def test_workbench_evolution_history_menu_shows_self_evolution_evidence(monkeypatch):
    shell = AgentWorkbenchShell(config=SimpleNamespace(avatar=SimpleNamespace(preset="default")))
    fake_ui = _FakeUI()
    shell.ui = fake_ui

    prompts = iter(["1", "", "2", "", "3", "", "q"])
    monkeypatch.setattr("core.ui.workbench.Prompt.ask", lambda *args, **kwargs: next(prompts))
    monkeypatch.setattr("core.ui.workbench.build_self_evolution_preview", lambda goal=None: "fitness: ready")
    monkeypatch.setattr(
        "core.ui.workbench.list_recent_self_evolution_transactions",
        lambda project_root: [SimpleNamespace()],
    )
    monkeypatch.setattr(
        "core.ui.workbench.format_self_evolution_transaction_history",
        lambda records: "transactions: ready",
    )
    monkeypatch.setattr(
        "core.ui.workbench.build_self_evolution_worktree_snapshot",
        lambda: "worktree: ready",
    )
    monkeypatch.setattr(
        "core.ui.workbench.format_self_evolution_audit_excerpt",
        lambda project_root: "audit: ready",
    )

    shell._run_evolution_history_menu()

    printed = "\n".join(str(getattr(args[0], "renderable", args[0])) for args, _kwargs in fake_ui.console.items)
    assert "fitness: ready" in printed
    assert "transactions: ready" in printed
    assert "worktree: ready" in printed
    assert "audit: ready" in printed
    assert shell._recent_status == "已返回进化控制台"


def test_workbench_supervised_evolution_prints_progress_events(monkeypatch):
    shell = AgentWorkbenchShell(config=SimpleNamespace(avatar=SimpleNamespace(preset="default")))
    fake_ui = _FakeUI()
    shell.ui = fake_ui

    prompts = iter(["2", "demo_bundle", "y", "n", "q"])
    monkeypatch.setattr("core.ui.workbench.Prompt.ask", lambda *args, **kwargs: next(prompts))

    class Decision:
        session_id = "supervised_demo"
        bundle_name = "demo_bundle"
        decision = "HOLD"
        decision_path = "workspace/supervised_evolution/decisions/demo.json"
        policy_action = {}

    def fake_run_workbench_session(*, bundle_name, keep_worktree, progress_callback=None):
        progress_callback(
            {
                "event": "role_start",
                "case_index": 1,
                "case_total": 2,
                "case_id": "transaction_probe",
                "role": "baseline",
                "scenario": "transaction",
                "mode": "single_turn",
                "timeout_seconds": 300,
                "keep_worktree": keep_worktree,
                "observational": True,
            }
        )
        progress_callback(
            {
                "event": "role_finish",
                "case_id": "transaction_probe",
                "role": "baseline",
                "status": "failed",
                "reason": "delegation/subagent detected",
                "elapsed_seconds": 42.0,
                "worktree_path": "C:/tmp/worktree",
                "report_path": "workspace/report.json",
                "drift_warning": True,
                "observational": True,
            }
        )
        return SimpleNamespace(
            decision=Decision(),
            decision_summary="summary:HOLD",
            result_border_style="green",
            lineage_index_path=None,
            lineage_summary=None,
        )

    monkeypatch.setattr("core.ui.workbench.run_workbench_session", fake_run_workbench_session)

    shell._run_supervised_evolution()

    printed = "\n".join(str(getattr(args[0], "renderable", args[0])) for args, _kwargs in fake_ui.console.items)
    assert "运行中：case 1/2 transaction_probe baseline" in printed
    assert "elapsed=42.0s" in printed
    assert "疑似跑偏信号" in printed
    assert "workspace/report.json" in printed


def test_workbench_supervised_evolution_dataset_selection_blocks_nonrunnable(monkeypatch):
    shell = AgentWorkbenchShell(config=SimpleNamespace(avatar=SimpleNamespace(preset="default")))
    fake_ui = _FakeUI()
    shell.ui = fake_ui

    prompts = iter(["1", "swe_bench_lite", "", "", "q"])
    labels = []

    def fake_prompt(label, *args, **kwargs):
        labels.append(label)
        return next(prompts)

    monkeypatch.setattr("core.ui.workbench.Prompt.ask", fake_prompt)
    monkeypatch.setattr(
        "core.evaluation.dataset_registry.list_dataset_status",
        lambda project_root: [
            {
                "name": "swe_bench_lite",
                "available": False,
                "runnable": False,
                "adapter_status": "requires_swe_harness",
                "bundle_name": "swe_bench_lite_v1",
            }
        ],
    )

    class Materialized:
        runnable = False
        adapter_status = "requires_swe_harness"
        bundle_name = "swe_bench_lite_v1"

    monkeypatch.setattr(
        "core.evaluation.dataset_registry.materialize_dataset_bundle",
        lambda *args, **kwargs: Materialized(),
    )

    shell._run_supervised_evolution()

    assert shell._recent_status == "已返回进化控制台"
    assert labels.count("请选择") == 2


def test_workbench_supervised_evolution_dataset_prepare_error_returns_to_menu(monkeypatch):
    shell = AgentWorkbenchShell(config=SimpleNamespace(avatar=SimpleNamespace(preset="default")))
    fake_ui = _FakeUI()
    shell.ui = fake_ui

    prompts = iter(["1", "custom_prompt_jsonl", "", "", "q"])
    labels = []

    def fake_prompt(label, *args, **kwargs):
        labels.append(label)
        return next(prompts)

    monkeypatch.setattr("core.ui.workbench.Prompt.ask", fake_prompt)
    monkeypatch.setattr(
        "core.ui.workbench.list_dataset_choices",
        lambda project_root: [
            {
                "name": "custom_prompt_jsonl",
                "available": False,
                "runnable": True,
                "adapter_status": "ready",
                "bundle_name": "custom_prompt_jsonl_v1",
            }
        ],
    )
    monkeypatch.setattr(
        "core.ui.workbench.prepare_dataset_run",
        lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError("missing jsonl")),
    )

    shell._run_supervised_evolution()

    assert shell._recent_status == "已返回进化控制台"
    assert labels.count("请选择") == 2


def test_workbench_supervised_evolution_dataset_run_persists_state(monkeypatch, tmp_path: Path):
    shell = AgentWorkbenchShell(config=SimpleNamespace(avatar=SimpleNamespace(preset="default")))
    fake_ui = _FakeUI()
    shell.ui = fake_ui

    prompts = iter(["1", "custom_prompt_jsonl", "2", "y", "y", "q"])
    monkeypatch.setattr("core.ui.workbench.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("core.ui.workbench.Prompt.ask", lambda *args, **kwargs: next(prompts))
    monkeypatch.setattr(
        "core.evaluation.dataset_registry.list_dataset_status",
        lambda project_root: [
            {
                "name": "custom_prompt_jsonl",
                "available": True,
                "runnable": True,
                "adapter_status": "ready",
                "bundle_name": "custom_prompt_jsonl_v1",
            }
        ],
    )

    class Materialized:
        dataset_name = "custom_prompt_jsonl"
        runnable = True
        adapter_status = "ready"
        bundle_name = "custom_prompt_jsonl_v1"
        case_count = 2
        bundle_path = str(tmp_path / "workspace" / "evaluation" / "bundles" / "custom_prompt_jsonl_v1.json")

    monkeypatch.setattr(
        "core.evaluation.dataset_registry.materialize_dataset_bundle",
        lambda *args, **kwargs: Materialized(),
    )

    class Decision:
        session_id = "supervised_demo"
        bundle_name = "custom_prompt_jsonl_v1"
        started_at = "2026-05-14T00:00:00Z"
        ended_at = "2026-05-14T00:00:01Z"
        benchmark = "dry"
        baseline_runs = []
        candidate_runs = []
        baseline_summary = SimpleNamespace(
            total=1,
            successes=1,
            avg_wall_clock_seconds=1.0,
            validation_passed=1,
            validation_failed=0,
            total_guarded_tools=2,
        )
        candidate_summary = SimpleNamespace(
            total=1,
            successes=1,
            avg_wall_clock_seconds=1.0,
            validation_passed=1,
            validation_failed=0,
            total_guarded_tools=2,
        )
        case_summaries = []
        gates = []
        decision = "HOLD"
        baseline_success_rate = 1.0
        candidate_success_rate = 1.0
        score_delta = 0.0
        reason = "tie"
        summary = {}
        decision_path = str(tmp_path / "workspace" / "supervised_evolution" / "decisions" / "demo.json")
        policy_action = {}

    monkeypatch.setattr(
        "core.evaluation.supervised_evolution.run_supervised_evolution_session",
        lambda **kwargs: Decision(),
    )

    shell._run_supervised_evolution()

    state_path = tmp_path / "workspace" / "supervised_evolution" / "workbench_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state == {
        "source": "dataset",
        "dataset_name": "custom_prompt_jsonl",
        "dataset_limit": 2,
        "bundle_name": "custom_prompt_jsonl_v1",
        "keep_worktree": True,
    }


def test_workbench_supervised_evolution_dataset_flow_uses_saved_defaults(monkeypatch, tmp_path: Path):
    state_path = tmp_path / "workspace" / "supervised_evolution" / "workbench_state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps(
            {
                "source": "dataset",
                "dataset_name": "saved_dataset",
                "dataset_limit": 3,
                "bundle_name": "saved_dataset_v1",
                "keep_worktree": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    shell = AgentWorkbenchShell(config=SimpleNamespace(avatar=SimpleNamespace(preset="default")))
    fake_ui = _FakeUI()
    shell.ui = fake_ui
    defaults = {}

    answers = iter(["1", "saved_dataset", "3", "n"])

    def fake_prompt(label, *args, **kwargs):
        defaults[label] = kwargs.get("default")
        return next(answers)

    monkeypatch.setattr("core.ui.workbench.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("core.ui.workbench.Prompt.ask", fake_prompt)
    monkeypatch.setattr(
        "core.evaluation.dataset_registry.list_dataset_status",
        lambda project_root: [
            {
                "name": "saved_dataset",
                "available": True,
                "runnable": True,
                "adapter_status": "ready",
                "bundle_name": "saved_dataset_v1",
            }
        ],
    )
    monkeypatch.setattr(
        "core.evaluation.dataset_registry.materialize_dataset_bundle",
        lambda *args, **kwargs: SimpleNamespace(
            dataset_name="saved_dataset",
            runnable=True,
            adapter_status="ready",
            bundle_name="saved_dataset_v1",
            case_count=3,
            bundle_path=str(tmp_path / "workspace" / "evaluation" / "bundles" / "saved_dataset_v1.json"),
        ),
    )

    shell._run_supervised_evolution()

    assert defaults["选择数据集编号或名称（回车选 1）"] == "saved_dataset"
    assert defaults["导入 case 上限（留空表示全部）"] == "3"


def test_workbench_supervised_evolution_bundle_flow_persists_and_uses_saved_defaults(monkeypatch, tmp_path: Path):
    state_path = tmp_path / "workspace" / "supervised_evolution" / "workbench_state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps(
            {
                "source": "bundle",
                "bundle_name": "saved_bundle",
                "keep_worktree": True,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    shell = AgentWorkbenchShell(config=SimpleNamespace(avatar=SimpleNamespace(preset="default")))
    fake_ui = _FakeUI()
    shell.ui = fake_ui
    defaults = {}

    answers = iter(["2", "saved_bundle", "y", "y", "q"])

    def fake_prompt(label, *args, **kwargs):
        defaults[label] = kwargs.get("default")
        return next(answers)

    class Decision:
        session_id = "supervised_demo"
        bundle_name = "saved_bundle"
        started_at = "2026-05-14T00:00:00Z"
        ended_at = "2026-05-14T00:00:01Z"
        benchmark = "dry"
        baseline_runs = []
        candidate_runs = []
        baseline_summary = SimpleNamespace(
            total=1,
            successes=1,
            avg_wall_clock_seconds=1.0,
            validation_passed=1,
            validation_failed=0,
            total_guarded_tools=2,
        )
        candidate_summary = SimpleNamespace(
            total=1,
            successes=1,
            avg_wall_clock_seconds=1.0,
            validation_passed=1,
            validation_failed=0,
            total_guarded_tools=2,
        )
        case_summaries = []
        gates = []
        decision = "HOLD"
        baseline_success_rate = 1.0
        candidate_success_rate = 1.0
        score_delta = 0.0
        reason = "tie"
        summary = {}
        decision_path = str(tmp_path / "workspace" / "supervised_evolution" / "decisions" / "demo.json")
        policy_action = {}

    monkeypatch.setattr("core.ui.workbench.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("core.ui.workbench.Prompt.ask", fake_prompt)
    monkeypatch.setattr(
        "core.evaluation.supervised_evolution.run_supervised_evolution_session",
        lambda **kwargs: Decision(),
    )

    shell._run_supervised_evolution()

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert defaults["监督进化 bundle"] == "saved_bundle"
    assert defaults["保留 worktree 便于排查？(y/N)"] == "y"
    assert state == {
        "source": "bundle",
        "bundle_name": "saved_bundle",
        "keep_worktree": True,
    }


def test_workbench_supervised_evolution_result_menu_can_rerun(monkeypatch):
    shell = AgentWorkbenchShell(config=SimpleNamespace(avatar=SimpleNamespace(preset="default")))
    fake_ui = _FakeUI()
    shell.ui = fake_ui

    prompts = iter(["2", "demo_bundle", "y", "n", "3", "q"])
    monkeypatch.setattr("core.ui.workbench.Prompt.ask", lambda *args, **kwargs: next(prompts))

    class Decision:
        session_id = "supervised_demo"
        bundle_name = "demo_bundle"
        started_at = "2026-05-14T00:00:00Z"
        ended_at = "2026-05-14T00:00:01Z"
        benchmark = "dry"
        baseline_runs = []
        candidate_runs = []
        baseline_summary = SimpleNamespace(
            total=1,
            successes=1,
            avg_wall_clock_seconds=1.0,
            validation_passed=1,
            validation_failed=0,
            total_guarded_tools=2,
        )
        candidate_summary = SimpleNamespace(
            total=1,
            successes=1,
            avg_wall_clock_seconds=1.0,
            validation_passed=1,
            validation_failed=0,
            total_guarded_tools=2,
        )
        case_summaries = []
        gates = []
        decision = "HOLD"
        baseline_success_rate = 1.0
        candidate_success_rate = 1.0
        score_delta = 0.0
        reason = "tie"
        summary = {}
        decision_path = "workspace/supervised_evolution/decisions/demo.json"
        policy_action = {}

    calls = []
    monkeypatch.setattr(
        "core.evaluation.supervised_evolution.run_supervised_evolution_session",
        lambda **kwargs: calls.append(kwargs) or Decision(),
    )

    shell._run_supervised_evolution()

    assert len(calls) == 2
    assert all(item["bundle_name"] == "demo_bundle" for item in calls)


def test_workbench_supervised_evolution_history_menu_reads_recent_decision(monkeypatch, tmp_path: Path):
    shell = AgentWorkbenchShell(config=SimpleNamespace(avatar=SimpleNamespace(preset="default")))
    fake_ui = _FakeUI()
    shell.ui = fake_ui
    decisions_dir = tmp_path / "workspace" / "supervised_evolution" / "decisions"
    decisions_dir.mkdir(parents=True)
    decision_path = decisions_dir / "supervised_1.json"
    decision_path.write_text(
        json.dumps(
            {
                "session_id": "supervised_1",
                "bundle_name": "demo_bundle",
                "decision": "HOLD",
                "reason": "tie",
                "ended_at": "2026-05-15T00:00:00Z",
                "policy_action": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    prompts = iter(["1", "1", "q"])
    monkeypatch.setattr("core.ui.workbench.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("core.ui.workbench.Prompt.ask", lambda *args, **kwargs: next(prompts))

    shell._run_supervised_history_menu()

    assert shell._recent_status == "已查看监督进化历史：supervised_1"
    printed = "\n".join(str(getattr(args[0], "renderable", args[0])) for args, _kwargs in fake_ui.console.items)
    assert "supervised_1" in printed


def test_workbench_supervised_evolution_dashboard_menu_opens_page(monkeypatch, tmp_path: Path):
    shell = AgentWorkbenchShell(config=SimpleNamespace(avatar=SimpleNamespace(preset="default")))
    fake_ui = _FakeUI()
    shell.ui = fake_ui
    opened = {}

    class Dashboard:
        html_path = str(tmp_path / "workspace" / "supervised_evolution" / "dashboard" / "index.html")
        session_count = 1
        skipped_count = 0
        latest_decision = "HOLD"
        risk_level = "low"

    prompts = iter([""])
    monkeypatch.setattr("core.ui.workbench.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("core.ui.workbench.Prompt.ask", lambda *args, **kwargs: next(prompts))
    monkeypatch.setattr("core.ui.workbench.generate_supervised_dashboard", lambda **kwargs: Dashboard())
    monkeypatch.setattr("core.ui.workbench.webbrowser.open", lambda url: opened.setdefault("url", url))

    shell._open_supervised_dashboard()

    assert opened["url"].endswith("index.html")
    assert shell._recent_status == f"已打开监督进化进展页面：{Dashboard.html_path}"
    printed = "\n".join(str(getattr(args[0], "renderable", args[0])) for args, _kwargs in fake_ui.console.items)
    assert "页面：" in printed
    assert "agent_consumption: advisory" in printed
