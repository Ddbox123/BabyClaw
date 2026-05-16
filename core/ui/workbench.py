#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一终端工作台入口。
"""

from __future__ import annotations

import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from typing import Any, Callable

from rich.panel import Panel
from rich.prompt import Prompt

from config import get_config
from core.evaluation.self_evolution_workbench import (
    DEFAULT_SELF_EVOLUTION_GOAL,
    build_self_evolution_preview,
    build_self_evolution_worktree_snapshot,
    format_self_evolution_audit_excerpt,
    format_self_evolution_transaction_history,
    list_recent_self_evolution_transactions,
)
from core.evaluation.supervised_workbench import (
    build_workbench_state,
    dataset_status_line,
    default_bundle_name,
    format_bundle_preview,
    format_decision_history,
    format_file_excerpt,
    format_lineage_summary,
    format_run_banner,
    list_dataset_choices,
    list_recent_decision_records,
    load_workbench_state,
    prepare_dataset_run,
    resolve_workbench_bundle_path,
    run_workbench_session,
    save_workbench_state,
    select_dataset_by_input,
    select_decision_record,
)
from core.evaluation.supervised_dashboard import generate_supervised_dashboard
from core.ui.cli_ui import get_ui


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PANEL_PORT = 8765


class AgentWorkbenchShell:
    """统一终端工作台。"""

    def __init__(self, config=None):
        self.config = config or get_config()
        self.ui = get_ui()
        self.ui.set_avatar_preset(self.config.avatar.preset)
        self._recent_status = "就绪"

    def _print_home(self):
        self.ui.clear()
        self.ui.console.print(
            Panel(
                "[bold cyan]Vibelution 工作台[/bold cyan]\n\n"
                "1. 对话\n"
                "2. 配置\n"
                "3. 重置\n"
                "4. 宠物空间\n"
                "5. 进化\n"
                "q. 退出",
                title="工作台",
                border_style="cyan",
            )
        )
        self.ui.console.print(f"[dim]状态：[/dim] {self._recent_status}")

    def run(self, agent_factory: Callable[[], object]) -> int:
        while True:
            self.ui.set_shell_mode("shell")
            self._print_home()
            choice = Prompt.ask("请选择", choices=["1", "2", "3", "4", "5", "q"], default="1")
            if choice == "1":
                self._run_chat(agent_factory)
            elif choice == "2":
                self._open_config_panel()
            elif choice == "3":
                self._run_reset_menu()
            elif choice == "4":
                self._show_pet_space()
            elif choice == "5":
                self._run_evolution_console(agent_factory)
            else:
                self._recent_status = "已退出工作台"
                return 0

    def _run_chat(self, agent_factory: Callable[[], object]):
        self.ui.reset_workspace()
        self.ui.set_shell_mode("chat")
        agent = agent_factory()
        self.ui.console.print(
            Panel(
                "进入一问一答对话模式。\n输入 `/back` 返回工作台。",
                title="对话",
                border_style="cyan",
            )
        )
        while True:
            task = Prompt.ask("对话", default="").strip()
            if not task:
                continue
            if task.lower() in {"/back", "/q", "/quit", "q"}:
                self._recent_status = "对话会话已结束"
                return
            if self._looks_like_evolution_request(task):
                self.ui.console.print(
                    Panel(
                        "自进化与监督进化请从 `进化` 入口进入；对话窗口当前只负责交流。",
                        title="已转交到进化入口",
                        border_style="yellow",
                    )
                )
                self._recent_status = "对话中拦截了进化请求"
                continue
            self.ui.start_live()
            try:
                agent.run_single_turn(initial_prompt=task)
            finally:
                self.ui.stop_live()
            self._recent_status = "对话已完成一轮"

    def _open_config_panel(self):
        panel_script = PROJECT_ROOT / "scripts" / "config_panel.py"
        url = f"http://127.0.0.1:{CONFIG_PANEL_PORT}/"
        cmd = [
            sys.executable,
            str(panel_script),
            "--host",
            "127.0.0.1",
            "--port",
            str(CONFIG_PANEL_PORT),
            "--no-browser",
        ]
        try:
            subprocess.Popen(
                cmd,
                cwd=str(PROJECT_ROOT),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            time.sleep(1.2)
        except Exception:
            pass
        webbrowser.open(url)
        self.ui.console.print(Panel(f"配置页面：{url}", title="配置", border_style="green"))
        self._recent_status = f"已打开配置页面：{url}"
        Prompt.ask("按回车返回", default="")

    def _run_reset_menu(self):
        import reset as reset_module

        self.ui.console.print(
            Panel(
                "正在进入重置菜单。\n完成既有重置流程后，再回到这里。",
                title="重置",
                border_style="yellow",
            )
        )
        self._recent_status = "已打开重置菜单"
        try:
            reset_module.interactive()
        except SystemExit:
            pass

    def _show_pet_space(self):
        self.ui.console.print(Panel("宠物空间", title="宠物空间", border_style="magenta"))
        try:
            self.ui.print_pet_status()
        except Exception:
            self.ui.console.print("[dim]宠物状态暂时不可用[/dim]")
        if self.ui._thought_history:
            self.ui.console.print("\n[bold]最近思绪气泡[/bold]")
            for idx, item in enumerate(self.ui._thought_history[-5:], start=1):
                self.ui.console.print(f"{idx}. {item[:200]}")
        self._recent_status = "已查看宠物空间"
        Prompt.ask("按回车返回", default="")

    def _run_evolution_console(self, agent_factory: Callable[[], object]):
        while True:
            self.ui.clear()
            self.ui.console.print(
                Panel(
                    "1. Agent 自进化\n"
                    "2. 监督进化\n"
                    "3. 历史与证据\n"
                    "q. 返回",
                    title="进化控制台",
                    border_style="blue",
                )
            )
            choice = Prompt.ask("请选择", choices=["1", "2", "3", "q"], default="1")
            if choice == "1":
                self._run_agent_self_evolution(agent_factory)
                continue
            if choice == "2":
                self._run_supervised_evolution()
                continue
            if choice == "3":
                self._run_evolution_history_menu()
                continue
            self._recent_status = "已返回工作台"
            return

    def _run_agent_self_evolution(self, agent_factory: Callable[[], object]):
        goal = DEFAULT_SELF_EVOLUTION_GOAL
        self.ui.console.print(
            Panel(
                build_self_evolution_preview(goal=goal),
                title="Agent 自进化预览",
                border_style="cyan",
            )
        )
        run_choice = Prompt.ask("开始运行？(Y/n)", choices=["y", "n"], default="y")
        if run_choice == "n":
            self._recent_status = "Agent 自进化已取消"
            return

        self.ui.reset_workspace()
        self.ui.set_shell_mode("self_evolution")
        agent = agent_factory()
        self.ui.start_live()
        try:
            agent.run_loop(initial_prompt=goal)
        finally:
            self.ui.stop_live()
        self._recent_status = "Agent 自进化会话已结束"

    def _run_evolution_history_menu(self):
        while True:
            self.ui.console.print(
                Panel(
                    build_self_evolution_preview(),
                    title="Agent 自进化证据",
                    border_style="magenta",
                )
            )
            self.ui.console.print(
                Panel(
                    "1. 查看自进化最近事务\n"
                    "2. 查看当前工作区快照\n"
                    "3. 查看自进化审计摘录\n"
                    "4. 查看监督进化历史\n"
                    "5. 打开监督进化进展页面\n"
                    "q. 返回进化控制台",
                    title="历史与证据",
                    border_style="cyan",
                )
            )
            choice = Prompt.ask("请选择", choices=["1", "2", "3", "4", "5", "q"], default="q")
            if choice == "1":
                records = list_recent_self_evolution_transactions(PROJECT_ROOT)
                self.ui.console.print(
                    Panel(
                        format_self_evolution_transaction_history(records),
                        title="自进化最近事务",
                        border_style="cyan",
                    )
                )
                self._recent_status = "已查看自进化最近事务"
                Prompt.ask("按回车继续", default="")
                continue
            if choice == "2":
                self.ui.console.print(
                    Panel(
                        build_self_evolution_worktree_snapshot(),
                        title="当前工作区快照",
                        border_style="cyan",
                    )
                )
                self._recent_status = "已查看当前工作区快照"
                Prompt.ask("按回车继续", default="")
                continue
            if choice == "3":
                self.ui.console.print(
                    Panel(
                        format_self_evolution_audit_excerpt(PROJECT_ROOT),
                        title="自进化审计摘录",
                        border_style="cyan",
                    )
                )
                self._recent_status = "已查看自进化审计摘录"
                Prompt.ask("按回车继续", default="")
                continue
            if choice == "4":
                self._run_supervised_history_menu()
                continue
            if choice == "5":
                self._open_supervised_dashboard()
                continue
            self._recent_status = "已返回进化控制台"
            return

    @staticmethod
    def _looks_like_evolution_request(text: str) -> bool:
        normalized = (text or "").strip().lower()
        if not normalized:
            return False
        markers = (
            "开始自主进化",
            "自主进化",
            "自进化",
            "监督进化",
            "trigger_self_restart_tool",
            "open_evolution_transaction_tool",
            "close_evolution_transaction_tool",
            "start self evolution",
            "self evolve",
            "self-evolution",
        )
        return any(marker in normalized for marker in markers)

    def _run_supervised_evolution(self):
        saved_state = load_workbench_state(PROJECT_ROOT)
        default_bundle = default_bundle_name()
        while True:
            self.ui.clear()
            self.ui.console.print(
                Panel(
                    "1. 选择已有数据集\n"
                    "2. 输入已有 bundle\n"
                    "q. 返回",
                    title="监督进化控制台",
                    border_style="blue",
                )
            )
            source_kind = Prompt.ask("请选择", choices=["1", "2", "q"], default="1")
            if source_kind == "q":
                self._recent_status = "已返回进化控制台"
                return

            bundle_name = default_bundle
            dataset_name = None
            dataset_limit = None
            if source_kind == "1":
                datasets = list_dataset_choices(PROJECT_ROOT)
                dataset_lines = []
                for idx, item in enumerate(datasets, start=1):
                    dataset_lines.append(dataset_status_line(item, idx))
                self.ui.console.print(
                    Panel("\n".join(dataset_lines) or "暂无数据集", title="数据集", border_style="cyan")
                )
                selected = None
                while selected is None:
                    raw = Prompt.ask(
                        "选择数据集编号或名称（回车选 1）",
                        default=str(saved_state.get("dataset_name") or ""),
                    )
                    selected = select_dataset_by_input(datasets, raw)
                    if selected is None:
                        self.ui.console.print("[yellow]选择无效，请重新输入。[/yellow]")
                dataset_name = selected["name"]
                default_limit = (
                    "" if saved_state.get("dataset_limit") is None else str(saved_state.get("dataset_limit"))
                )
                limit_text = Prompt.ask("导入 case 上限（留空表示全部）", default=default_limit)
                try:
                    dataset_limit = int(limit_text) if limit_text.strip() else None
                except ValueError:
                    self.ui.console.print(
                        Panel("导入 case 上限必须是整数或留空。", title="输入无效", border_style="yellow")
                    )
                    Prompt.ask("按回车继续", default="")
                    continue
                try:
                    prepared = prepare_dataset_run(PROJECT_ROOT, dataset_name, dataset_limit)
                except Exception as exc:
                    self.ui.console.print(
                        Panel(
                            f"数据集准备失败：{type(exc).__name__}: {exc}",
                            title="数据集不可用",
                            border_style="yellow",
                        )
                    )
                    Prompt.ask("按回车继续", default="")
                    continue
                self.ui.console.print(
                    Panel(
                        prepared.summary,
                        title="物化结果",
                        border_style="green" if prepared.runnable else "yellow",
                    )
                )
                if not prepared.runnable:
                    self.ui.console.print(
                        Panel(
                            prepared.blocked_message,
                            title="数据集暂不可运行",
                            border_style="yellow",
                        )
                    )
                    self._recent_status = "数据集需要专用 harness"
                    Prompt.ask("按回车继续", default="")
                    continue
                bundle_name = prepared.bundle_name
            else:
                bundle_name = Prompt.ask(
                    "监督进化 bundle",
                    default=str(saved_state.get("bundle_name") or default_bundle),
                )
            break

        bundle_path = resolve_workbench_bundle_path(PROJECT_ROOT, bundle_name)
        self.ui.console.print(
            Panel(format_bundle_preview(str(bundle_path)), title="运行预览", border_style="cyan")
        )
        run_choice = Prompt.ask("开始运行？(Y/n)", choices=["y", "n"], default="y")
        if run_choice == "n":
            self._recent_status = "监督进化已取消"
            return
        keep_choice = Prompt.ask(
            "保留 worktree 便于排查？(y/N)",
            choices=["y", "n"],
            default="y" if saved_state.get("keep_worktree") else "n",
        )
        keep_worktree = keep_choice == "y"
        save_workbench_state(
            PROJECT_ROOT,
            build_workbench_state(
                source_kind=source_kind,
                dataset_name=dataset_name,
                dataset_limit=dataset_limit,
                bundle_name=bundle_name,
                keep_worktree=keep_worktree,
            ),
        )
        self.ui.set_shell_mode("supervised_evolution")

        while True:
            self.ui.console.print(
                Panel(
                    format_run_banner(bundle_name, keep_worktree),
                    title="监督进化",
                    border_style="blue",
                )
            )
            try:
                result = run_workbench_session(
                    bundle_name=bundle_name,
                    keep_worktree=keep_worktree,
                    progress_callback=self._print_supervised_progress,
                )
                decision = result.decision
                self.ui.console.print(
                    Panel(
                        result.decision_summary,
                        title="监督进化结果",
                        border_style=result.result_border_style,
                    )
                )
                if result.lineage_index_path and result.lineage_summary:
                    self.ui.console.print(
                        Panel(
                            result.lineage_summary,
                            title="Lineage",
                            border_style="cyan",
                        )
                    )
                self._recent_status = f"监督进化完成：{decision.decision}"
                action = self._supervised_result_menu(decision, result.lineage_index_path)
                if action == "rerun":
                    continue
                return
            except Exception as exc:
                self.ui.console.print(
                    Panel(
                        f"监督进化运行失败：{type(exc).__name__}: {exc}",
                        title="监督进化失败",
                        border_style="red",
                    )
                )
                self._recent_status = "监督进化运行失败"
                retry = Prompt.ask("重试这次运行？(y/N)", choices=["y", "n"], default="n")
                if retry == "y":
                    continue
                return

    def _print_supervised_progress(self, event: dict[str, Any]) -> None:
        event_type = event.get("event")
        if event_type == "session_start":
            self.ui.console.print(
                Panel(
                    "\n".join(
                        [
                            f"session={event.get('session_id')}",
                            f"bundle={event.get('bundle_name')}",
                            f"cases={event.get('case_total')}",
                            "agent_consumption: observational",
                            "runtime_authorization: none",
                        ]
                    ),
                    title="监督进化观察",
                    border_style="blue",
                )
            )
            return
        if event_type == "role_start":
            self.ui.console.print(
                Panel(
                    "\n".join(
                        [
                            (
                                f"运行中：case {event.get('case_index')}/{event.get('case_total')} "
                                f"{event.get('case_id')} {event.get('role')}"
                            ),
                            f"scenario={event.get('scenario')} mode={event.get('mode')}",
                            f"timeout={event.get('timeout_seconds')}s keep_worktree={event.get('keep_worktree')}",
                            "正在等待 harness 返回；若耗时较久，这是正常的受控观察阶段。",
                        ]
                    ),
                    title="监督进化观察",
                    border_style="cyan",
                )
            )
            return
        if event_type == "role_finish":
            drift_warning = bool(event.get("drift_warning"))
            status = str(event.get("status") or "")
            border_style = "yellow" if drift_warning or status in {"failed", "timeout"} else "green"
            lines = [
                f"完成：{event.get('case_id')} {event.get('role')} status={status}",
                f"elapsed={event.get('elapsed_seconds')}s",
                f"reason={event.get('reason')}",
                f"report={event.get('report_path')}",
                f"worktree={event.get('worktree_path')}",
                "agent_consumption: observational",
                "runtime_authorization: none",
            ]
            if drift_warning:
                lines.insert(0, "疑似跑偏信号：检测到委派/subagent/相关失败线索，等待最终 gate 判定。")
            self.ui.console.print(
                Panel(
                    "\n".join(lines),
                    title="监督进化观察",
                    border_style=border_style,
                )
            )
            return
        if event_type == "session_error":
            self.ui.console.print(
                Panel(
                    "\n".join(
                        [
                            f"运行异常：case {event.get('case_index')}/{event.get('case_total')} {event.get('case_id')} {event.get('role')}",
                            f"{event.get('error_type')}: {event.get('error')}",
                            "agent_consumption: observational",
                            "runtime_authorization: none",
                        ]
                    ),
                    title="监督进化观察",
                    border_style="red",
                )
            )
            return
        if event_type == "session_finish":
            self.ui.console.print(
                Panel(
                    "\n".join(
                        [
                            f"decision={event.get('decision')}",
                            f"reason={event.get('reason')}",
                            f"record={event.get('decision_path')}",
                            f"policy={event.get('policy_action')}",
                        ]
                    ),
                    title="监督进化观察",
                    border_style="green",
                )
            )

    def _supervised_result_menu(self, decision, lineage_index_path: str | None) -> str:
        while True:
            self.ui.console.print(
                Panel(
                    "1. 查看 decision record\n"
                    "2. 查看 lineage 摘要\n"
                    "3. 使用相同配置再跑一次\n"
                    "q. 返回工作台",
                    title="结果操作",
                    border_style="cyan",
                )
            )
            action = Prompt.ask("请选择", choices=["1", "2", "3", "q"], default="q")
            if action == "1":
                self.ui.console.print(
                    Panel(
                        format_file_excerpt(decision.decision_path),
                        title=f"Decision: {decision.decision_path}",
                        border_style="cyan",
                    )
                )
            elif action == "2":
                if not lineage_index_path:
                    self.ui.console.print(
                        Panel("本次运行没有 lineage_index_path。", title="Lineage", border_style="yellow")
                    )
                    continue
                self.ui.console.print(
                    Panel(
                        format_lineage_summary(lineage_index_path, decision.bundle_name),
                        title="Lineage",
                        border_style="cyan",
                    )
                )
            elif action == "3":
                return "rerun"
            else:
                return "return"

    def _run_supervised_history_menu(self):
        records = list_recent_decision_records(PROJECT_ROOT)
        self.ui.console.print(
            Panel(format_decision_history(records), title="最近 decision", border_style="cyan")
        )
        if not records:
            self._recent_status = "暂无监督进化历史"
            Prompt.ask("按回车返回", default="")
            return

        selected = None
        while selected is None:
            raw = Prompt.ask("选择 decision 编号或 session_id（回车选 1）", default="")
            selected = select_decision_record(records, raw)
            if selected is None:
                self.ui.console.print("[yellow]选择无效，请重新输入。[/yellow]")

        self._recent_status = f"已查看监督进化历史：{selected.session_id}"
        self._supervised_result_menu(selected, selected.lineage_index_path)

    def _open_supervised_dashboard(self):
        dashboard = generate_supervised_dashboard(project_root=PROJECT_ROOT)
        webbrowser.open(Path(dashboard.html_path).resolve().as_uri())
        self.ui.console.print(
            Panel(
                "\n".join(
                    [
                        f"页面：{dashboard.html_path}",
                        f"session: {dashboard.session_count}",
                        f"跳过损坏记录：{dashboard.skipped_count}",
                        f"最近 decision: {dashboard.latest_decision}",
                        f"风险：{dashboard.risk_level}",
                        "agent_consumption: advisory",
                        "runtime_authorization: none",
                    ]
                ),
                title="监督进化进展页面",
                border_style="green",
            )
        )
        self._recent_status = f"已打开监督进化进展页面：{dashboard.html_path}"
        Prompt.ask("按回车返回", default="")
