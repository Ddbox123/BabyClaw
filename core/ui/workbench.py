#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一终端工作台入口。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any, Callable

from rich.panel import Panel
from rich.prompt import Prompt

from config import get_config
from core.chat import (
    format_chat_reply,
    load_chat_session,
    save_chat_session,
)
from core.evaluation.self_evolution_workbench import (
    DEFAULT_SELF_EVOLUTION_GOAL,
    build_self_evolution_preview,
    build_self_evolution_run_prompt,
    build_self_evolution_worktree_snapshot,
    format_self_evolution_audit_excerpt,
    format_self_evolution_transaction_history,
    list_recent_self_evolution_transactions,
)
from core.evaluation.chat_dataset_capture import (
    approve_chat_candidate,
    format_candidate_preview,
    format_structured_sample_preview,
    load_candidate_payload,
    reject_chat_candidate,
    resolve_chat_dataset_paths,
)
from core.evaluation.chat_review_queue import get_review_item, list_review_items
from core.evaluation.supervised_workbench import (
    build_workbench_state,
    dataset_status_line,
    default_bundle_name,
    format_bundle_preview,
    format_decision_history,
    format_file_excerpt,
    format_gym_promotion_lifecycle,
    format_lineage_summary,
    format_run_banner,
    execute_gym_promotion_action,
    list_dataset_choices,
    list_recent_decision_records,
    load_gym_promotion_lifecycle,
    load_workbench_state,
    prepare_dataset_run,
    resolve_workbench_bundle_path,
    run_workbench_session,
    save_workbench_state,
    select_dataset_by_input,
    select_decision_record,
)
from core.evaluation.supervised_dashboard import generate_supervised_dashboard
from core.orchestration.agent_modes import looks_like_explicit_evolution_request
from core.ui.cli_ui import get_ui


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PANEL_PORT = 8765
CONFIG_PANEL_BROWSER_PROFILE_DIR = PROJECT_ROOT / ".runtime" / "config_panel_browser"


def _config_panel_is_ready(url: str, timeout: float = 0.75) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            status = int(getattr(response, "status", 200) or 200)
            return 200 <= status < 500
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False


def _preferred_config_panel_browser() -> str | None:
    candidates: list[str] = []
    for name in ("msedge.exe", "msedge", "chrome.exe", "chrome"):
        resolved = shutil.which(name)
        if resolved:
            candidates.append(resolved)
    for env_name, relative in (
        ("ProgramFiles(x86)", r"Microsoft\Edge\Application\msedge.exe"),
        ("ProgramFiles", r"Microsoft\Edge\Application\msedge.exe"),
        ("LocalAppData", r"Google\Chrome\Application\chrome.exe"),
        ("ProgramFiles", r"Google\Chrome\Application\chrome.exe"),
        ("ProgramFiles(x86)", r"Google\Chrome\Application\chrome.exe"),
    ):
        root = os.environ.get(env_name, "").strip()
        if not root:
            continue
        candidate = Path(root) / relative
        if candidate.exists():
            candidates.append(str(candidate))
    seen: set[str] = set()
    for candidate in candidates:
        normalized = str(Path(candidate))
        if normalized in seen:
            continue
        seen.add(normalized)
        if Path(normalized).exists():
            return normalized
    return None


def _close_stale_config_panel_windows() -> None:
    if os.name != "nt":
        return
    marker = str(CONFIG_PANEL_BROWSER_PROFILE_DIR.resolve()).replace("'", "''")
    command = (
        f"$marker = [System.IO.Path]::GetFullPath('{marker}'); "
        "$targets = Get-CimInstance Win32_Process | Where-Object { "
        "$_.CommandLine -and $_.CommandLine.Contains($marker) -and "
        "$_.Name -match '^(msedge|chrome)(\\.exe)?$' }; "
        "foreach ($proc in $targets) { "
        "try { Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop } catch {} "
        "}"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        pass


def _open_config_panel_page(url: str) -> None:
    browser = _preferred_config_panel_browser()
    if browser:
        CONFIG_PANEL_BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        _close_stale_config_panel_windows()
        try:
            subprocess.Popen(
                [
                    browser,
                    f"--user-data-dir={CONFIG_PANEL_BROWSER_PROFILE_DIR}",
                    "--new-window",
                    "--no-first-run",
                    f"--app={url}",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return
        except Exception:
            pass
    webbrowser.open(url)


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

    @staticmethod
    def _create_agent(agent_factory: Callable[[], object], mode: str):
        try:
            return agent_factory(mode=mode)
        except TypeError:
            return agent_factory()

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
        agent = self._create_agent(agent_factory, "chat")
        session = self._load_chat_session()
        messages = list(session.messages)
        if hasattr(self.ui, "load_chat_messages"):
            self.ui.load_chat_messages(messages)
        self._set_chat_task_snapshot(None)
        self._restore_chat_context(agent, messages)
        if hasattr(self.ui, "add_log"):
            self.ui.add_log("对话模式已开启；输入 /back 返回工作台。", "INFO")
        while True:
            self._render_chat_shell()
            input_reader = getattr(self.ui, "read_chat_input", None)
            if callable(input_reader):
                task = str(input_reader() or "").strip()
            else:
                prompt_positioned = False
                cursor_setter = getattr(self.ui, "position_chat_prompt_cursor", None)
                if callable(cursor_setter):
                    prompt_positioned = bool(cursor_setter())
                prompt_label = "你"
                label_builder = getattr(self.ui, "chat_prompt_label", None)
                if not prompt_positioned and callable(label_builder):
                    prompt_label = str(label_builder() or "你")
                task = Prompt.ask(prompt_label, default="").strip()
            if not task:
                continue
            if task.lower() in {"/back", "/q", "/quit", "q"}:
                self._recent_status = "对话会话已结束"
                return
            if self._should_route_explicit_evolution_request() and self._looks_like_evolution_request(task):
                self.ui.console.print(
                    Panel(
                        "检测到显式进化请求，已退出 chat 并返回工作台首页。\n如需继续，请从 `5. 进化` 进入。",
                        title="已返回工作台",
                        border_style="yellow",
                    )
                )
                self._recent_status = "对话请求已返回工作台首页"
                return "evolution"
            self.ui.add_chat_message("user", task)
            messages.append(self._make_chat_message("user", task))
            session.messages = list(messages)
            self._save_chat_session(session)
            self.ui.start_live(transient=True)
            try:
                result = agent.run_single_turn(initial_prompt=task)
            finally:
                self.ui.stop_live()
            if isinstance(result, dict) and result.get("evolution_route_requested"):
                self.ui.console.print(
                    Panel(
                        "当前请求更适合走 `进化` 控制台，chat 已退出并返回工作台首页。\n如需继续，请从 `5. 进化` 进入。",
                        title="已返回工作台",
                        border_style="yellow",
                    )
                )
                self._recent_status = "agent 请求已返回工作台首页"
                return "evolution"
            reply = self._chat_reply_text(result)
            tool_calls = self._extract_chat_tool_calls(result)
            self.ui.add_chat_message("assistant", reply, tool_calls=tool_calls)
            messages.append(self._make_chat_message("assistant", reply, tool_calls=tool_calls))
            session.messages = list(messages)
            self._save_chat_session(session)
            self._recent_status = "对话已完成一轮"

    def _should_route_explicit_evolution_request(self) -> bool:
        modes_cfg = getattr(getattr(self.config, "agent", None), "modes", None)
        behavior = str(
            getattr(modes_cfg, "explicit_evolution_request_behavior", "route_to_workbench")
            or "route_to_workbench"
        ).strip().lower()
        return behavior == "route_to_workbench"

    def _chat_reply_text(self, result: Any) -> str:
        if not isinstance(result, dict):
            return "本轮没有产生可见回复。"
        sanitizer = getattr(self.ui, "sanitize_chat_message_content", None)
        visible = str(
            result.get("raw_output") or result.get("summary") or result.get("error") or result.get("message") or ""
        ).strip()
        if callable(sanitizer):
            visible = str(sanitizer("assistant", visible) or "").strip()
        if visible and not self._looks_like_structured_payload(visible):
            return visible
        summary = format_chat_reply(result)
        if callable(sanitizer):
            summary = str(sanitizer("assistant", summary) or "").strip()
        if not summary:
            summary = "本轮没有产生可见回复。"
        return summary

    @staticmethod
    def _normalize_chat_tool_calls(items: Any) -> list[str]:
        tool_calls: list[str] = []
        for item in list(items or []):
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

    @classmethod
    def _extract_chat_tool_calls(cls, result: Any) -> list[str]:
        if not isinstance(result, dict):
            return []
        tool_calls = cls._normalize_chat_tool_calls(result.get("tool_trace") or [])
        if tool_calls:
            return tool_calls
        return cls._normalize_chat_tool_calls(
            result.get("tool_calls") or result.get("tools") or []
        )

    @staticmethod
    def _looks_like_structured_payload(text: str) -> bool:
        candidate = str(text or "").strip()
        if not candidate:
            return False
        if not (
            (candidate.startswith("{") and candidate.endswith("}"))
            or (candidate.startswith("[") and candidate.endswith("]"))
        ):
            return False
        try:
            parsed = json.loads(candidate)
        except Exception:
            return False
        return isinstance(parsed, (dict, list))

    def _load_chat_session(self):
        return load_chat_session(PROJECT_ROOT)

    def _save_chat_session(self, session) -> None:
        save_chat_session(PROJECT_ROOT, session)

    def _set_chat_task_snapshot(self, snapshot: dict[str, Any] | None) -> None:
        setter = getattr(self.ui, "set_chat_task_snapshot", None)
        if callable(setter):
            setter(snapshot)

    @staticmethod
    def _make_chat_message(role: str, content: str, tool_calls: list[str] | None = None) -> dict[str, Any]:
        message: dict[str, Any] = {
            "role": str(role or "").strip().lower(),
            "content": str(content or "").strip(),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        normalized_tool_calls = AgentWorkbenchShell._normalize_chat_tool_calls(tool_calls or [])
        if normalized_tool_calls:
            message["tool_calls"] = normalized_tool_calls
        return message

    def _load_chat_messages(self) -> list[dict[str, Any]]:
        session = self._load_chat_session()
        return list(session.messages)

    def _save_chat_messages(self, messages: list[dict[str, Any]]) -> None:
        session = self._load_chat_session()
        session.messages = list(messages)
        self._save_chat_session(session)

    def _restore_chat_context(self, agent: Any, messages: list[dict[str, str]]) -> None:
        restore = getattr(agent, "seed_chat_history", None)
        if callable(restore):
            restore(messages)

    def _render_chat_shell(self) -> None:
        self.ui.clear()
        render = getattr(self.ui, "render_shell_snapshot", None)
        if callable(render):
            self.ui.console.print(render())

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
        if not _config_panel_is_ready(url):
            try:
                subprocess.Popen(
                    cmd,
                    cwd=str(PROJECT_ROOT),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                deadline = time.time() + 3.0
                while time.time() < deadline:
                    if _config_panel_is_ready(url):
                        break
                    time.sleep(0.2)
            except Exception:
                pass
        _open_config_panel_page(url)
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
                    "3. 对话数据审核\n"
                    "4. 历史与证据\n"
                    "q. 返回",
                    title="进化控制台",
                    border_style="blue",
                )
            )
            choice = Prompt.ask("请选择", choices=["1", "2", "3", "4", "q"], default="1")
            if choice == "1":
                self._run_agent_self_evolution(agent_factory)
                continue
            if choice == "2":
                self._run_supervised_evolution()
                continue
            if choice == "3":
                self._run_chat_dataset_review()
                continue
            if choice == "4":
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

        initial_prompt = build_self_evolution_run_prompt(goal=goal)
        self.ui.reset_workspace()
        self.ui.set_shell_mode("self_evolution")
        agent = self._create_agent(agent_factory, "self_evolution")
        self.ui.start_live()
        try:
            agent.run_loop(initial_prompt=initial_prompt)
        finally:
            self.ui.stop_live()
        self._recent_status = "Agent 自进化会话已结束"

    def _run_chat_dataset_review(self):
        paths = resolve_chat_dataset_paths(project_root=PROJECT_ROOT, config=self.config)
        while True:
            pending = list_review_items(paths.review_queue_path, status="pending")
            total = list_review_items(paths.review_queue_path)
            approved = [item for item in total if str(item.get("status") or "") == "approved"]
            rejected = [item for item in total if str(item.get("status") or "") == "rejected"]
            lines = [
                f"pending: {len(pending)}",
                f"approved: {len(approved)}",
                f"rejected: {len(rejected)}",
                "",
            ]
            if pending:
                for idx, item in enumerate(pending[:8], start=1):
                    lines.append(
                        f"{idx}. {item.get('topic_summary') or item.get('candidate_id')} "
                        f"[{item.get('start_turn')}-{item.get('end_turn')}] "
                        f"signals={','.join(item.get('quality_signals') or []) or '-'}"
                    )
                if len(pending) > 8:
                    lines.append(f"... 还有 {len(pending) - 8} 条 pending")
            else:
                lines.append("当前没有待审核的 chat 候选。")
            lines.append("")
            lines.append("q. 返回")
            self.ui.console.print(
                Panel(
                    "\n".join(lines),
                    title="对话数据审核",
                    border_style="cyan",
                )
            )
            if not pending:
                Prompt.ask("按回车返回", default="")
                self._recent_status = "当前没有待审核 chat 候选"
                return
            raw = Prompt.ask("选择候选编号或输入 q 返回", default="q")
            if raw.strip().lower() == "q":
                self._recent_status = "已退出对话数据审核"
                return
            if not raw.strip().isdigit():
                self.ui.console.print("[yellow]请输入编号或 q。[/yellow]")
                continue
            index = int(raw.strip())
            if index < 1 or index > min(len(pending), 8):
                self.ui.console.print("[yellow]编号超出范围。[/yellow]")
                continue
            item = pending[index - 1]
            self._review_chat_candidate(item, paths)

    def _review_chat_candidate(self, item: dict[str, Any], paths) -> None:
        candidate_id = str(item.get("candidate_id") or "").strip()
        current = get_review_item(candidate_id, paths.review_queue_path)
        if current is None:
            self.ui.console.print(Panel("候选不存在或已损坏。", title="审核失败", border_style="yellow"))
            return
        payload = load_candidate_payload(str(current.get("raw_excerpt_path") or ""))
        while True:
            sample_preview = payload.get("structured_sample_preview") if isinstance(payload.get("structured_sample_preview"), dict) else {}
            self.ui.console.print(
                Panel(
                    format_candidate_preview(payload),
                    title="候选片段",
                    border_style="cyan",
                )
            )
            self.ui.console.print(
                Panel(
                    format_structured_sample_preview(sample_preview),
                    title="结构化样本预览",
                    border_style="green",
                )
            )
            self.ui.console.print(
                Panel(
                    "1. 批准\n"
                    "2. 拒绝\n"
                    "q. 返回",
                    title="审核动作",
                    border_style="cyan",
                )
            )
            action = Prompt.ask("请选择", choices=["1", "2", "q"], default="q")
            if action == "q":
                self._recent_status = f"已查看 chat 候选：{candidate_id}"
                return
            note = Prompt.ask("审核备注（可留空）", default="")
            if action == "1":
                sample = approve_chat_candidate(
                    candidate_payload=payload,
                    project_root=PROJECT_ROOT,
                    reviewer_note=note,
                    config=self.config,
                )
                self.ui.console.print(
                    Panel(
                        format_structured_sample_preview(sample),
                        title="已批准并写入数据集",
                        border_style="green",
                    )
                )
                self._recent_status = f"已批准 chat 候选：{candidate_id}"
                return
            reject_chat_candidate(
                candidate_payload=payload,
                project_root=PROJECT_ROOT,
                reviewer_note=note,
                config=self.config,
            )
            self.ui.console.print(
                Panel(
                    f"已拒绝候选 {candidate_id}",
                    title="审核完成",
                    border_style="yellow",
                )
            )
            self._recent_status = f"已拒绝 chat 候选：{candidate_id}"
            return

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
        return looks_like_explicit_evolution_request(text)

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
            advisory_lines = event.get("active_advisory_lines") if isinstance(event.get("active_advisory_lines"), list) else []
            lines = [
                f"session={event.get('session_id')}",
                f"bundle={event.get('bundle_name')}",
                f"cases={event.get('case_total')}",
                "agent_consumption: observational",
                "runtime_authorization: none",
            ]
            if advisory_lines:
                lines.append("agent view:")
                lines.extend(advisory_lines)
            self.ui.console.print(
                Panel(
                    "\n".join(lines),
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

    def _supervised_result_menu(self, decision, lineage_index_path: str | None, *, allow_rerun: bool = True) -> str:
        while True:
            lifecycle = load_gym_promotion_lifecycle(decision, project_root=PROJECT_ROOT)
            option_lines = [
                "1. 查看 decision record",
                "2. 查看 lineage 摘要",
                "3. 查看 Gym proposal 状态",
            ]
            choice_list = ["1", "2", "3", "q"]
            action_map: dict[str, str] = {}
            next_index = 4
            for proposal_action in lifecycle.available_actions:
                label = {
                    "apply": "apply Gym proposal",
                    "activate": "activate Gym proposal",
                    "rollback": "rollback Gym proposal",
                }.get(proposal_action, proposal_action)
                key = str(next_index)
                next_index += 1
                choice_list.insert(-1, key)
                action_map[key] = proposal_action
                option_lines.append(f"{key}. {label}")
            rerun_key = None
            if allow_rerun:
                rerun_key = str(next_index)
                choice_list.insert(-1, rerun_key)
                option_lines.append(f"{rerun_key}. 使用相同配置再跑一次")
            option_lines.append("q. 返回")
            self.ui.console.print(
                Panel(
                    "\n".join(option_lines),
                    title="结果操作",
                    border_style="cyan",
                )
            )
            action = Prompt.ask("请选择", choices=choice_list, default="q")
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
                self.ui.console.print(
                    Panel(
                        format_gym_promotion_lifecycle(lifecycle),
                        title="Gym proposal 状态",
                        border_style="cyan" if not lifecycle.error else "yellow",
                    )
                )
            elif action in action_map:
                result = execute_gym_promotion_action(decision, action_map[action], project_root=PROJECT_ROOT)
                self.ui.console.print(
                    Panel(
                        result.summary,
                        title=f"Gym proposal {result.action}",
                        border_style="green",
                    )
                )
                self.ui.console.print(
                    Panel(
                        format_gym_promotion_lifecycle(result.lifecycle),
                        title="Gym proposal 状态",
                        border_style="cyan",
                    )
                )
                self._recent_status = f"已执行 Gym proposal {result.action}"
            elif rerun_key is not None and action == rerun_key:
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
        self._supervised_result_menu(selected, selected.lineage_index_path, allow_rerun=False)

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
