"""Startup helpers for the CLI agent entrypoint."""

from __future__ import annotations

import json
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Any, Callable

from config import AppConfig
from core.evaluation.supervised_cli import run_supervised_cli_from_args, should_handle_supervised_cli


def configure_console_encoding() -> None:
    """仅在真实 CLI 启动路径修复 Windows 控制台编码。"""
    if sys.platform != "win32":
        return

    import io

    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        buffer = getattr(stream, "buffer", None)
        if buffer is None:
            continue
        wrapped = io.TextIOWrapper(buffer, encoding="utf-8", errors="replace")
        setattr(sys, stream_name, wrapped)


def set_ui_test_mode(enabled: bool) -> None:
    """切换 CLI UI 的测试模式，避免自动化场景触发 Live 渲染。"""
    from core.ui.cli_ui import UIManager

    UIManager._test_mode = enabled


def initialize_ui_for_run(ui, *, test_mode: bool) -> None:
    """按运行模式初始化 UI。"""
    if test_mode:
        return
    ui.console.clear()
    ui.start_live()


def resolve_primary_model_name(config: AppConfig) -> str:
    """Return a primary model label across legacy and profile-based config."""

    llm = getattr(config, "llm", None)
    get_profile = getattr(llm, "get_profile", None)
    if callable(get_profile):
        profile = get_profile(role="primary")
        model = getattr(profile, "model", None)
        if model:
            return str(model)
    model_name = getattr(llm, "model_name", None)
    if model_name:
        return str(model_name)
    return "unknown-model"


def run_preflight_doctor(config: AppConfig, *, project_root: Path | None = None) -> None:
    """执行启动前环境自检，确保当前运行基线稳定。"""
    if not getattr(config.runtime, "preflight_doctor", True):
        return

    root = project_root or Path(__file__).resolve().parents[2]
    doctor_script = root / "scripts" / "doctor.ps1"
    if not doctor_script.exists():
        raise RuntimeError(f"缺少环境自检脚本: {doctor_script}")

    expected_python = root / ".venv" / "Scripts" / "python.exe"
    if config.runtime.require_venv and Path(sys.executable).resolve() != expected_python.resolve():
        raise RuntimeError(
            f"当前解释器不是项目 .venv: {sys.executable}\n"
            f"请使用: {expected_python}"
        )

    result = subprocess.run(
        [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(doctor_script),
            "-Json",
        ],
        capture_output=True,
        text=True,
        cwd=str(root),
        timeout=30,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "doctor 检查失败"
        raise RuntimeError(f"环境自检未通过:\n{detail}")


def run_agent_main(
    *,
    initial_prompt: str | None,
    args,
    parse_args_fn: Callable[[], Any],
    agent_cls,
    workbench_cls,
    get_ui_fn: Callable[[], Any],
    ui_error_fn: Callable[[str, str], Any],
    setup_logging_fn: Callable[..., Any],
    create_config_fn: Callable[[Any], AppConfig],
    set_ui_test_mode_fn: Callable[[bool], None],
    run_preflight_doctor_fn: Callable[[AppConfig], None],
    should_launch_workbench_fn: Callable[[Any, str | None], bool],
    initialize_ui_for_run_fn: Callable[..., None],
    extract_subagent_primary_goal_fn: Callable[[str | None], str],
    evolution_test_prompt: str,
    subagent_result_marker: str,
) -> None:
    """Run the CLI entrypoint with dependencies supplied by agent.py."""
    args = args or parse_args_fn()
    test_mode = bool(getattr(args, "test", False))
    subagent_json_mode = bool(getattr(args, "subagent_json", False))
    set_ui_test_mode_fn(test_mode)
    ui = get_ui_fn()

    config = create_config_fn(args)
    avatar_preset = getattr(getattr(config, "avatar", None), "preset", "lobster")
    ui.set_avatar_preset(avatar_preset)
    setup_logging_fn(level=config.log.level)
    if not test_mode:
        run_preflight_doctor_fn(config)

    if should_handle_supervised_cli(args):
        project_root = Path(__file__).resolve().parents[2]
        raise SystemExit(run_supervised_cli_from_args(args=args, project_root=project_root))

    if should_launch_workbench_fn(args, initial_prompt):
        ui.reset_workspace()
        shell = workbench_cls(config=config)
        try:
            return shell.run(agent_factory=lambda: agent_cls(config=config))
        except Exception as e:
            ui_error_fn(f"工作台启动异常: {type(e).__name__}: {e}", traceback.format_exc())
            sys.exit(1)

    initialize_ui_for_run_fn(ui, test_mode=(test_mode or subagent_json_mode))

    if test_mode:
        sys.__stdout__.write("=" * 60 + "\n  Self-Evolving Agent - Test Mode\n" + "=" * 60 + "\n")
        sys.__stdout__.flush()

    if not subagent_json_mode:
        ui.print_header(resolve_primary_model_name(config))

    try:
        agent = agent_cls(config=config)
        if not subagent_json_mode:
            ui.add_content(
                f"[dim]Tools:[/dim] {len(agent.key_tools)} loaded  [dim]Awake:[/dim] {config.agent.awake_interval}s"
            )
            ui.add_content("")

        if test_mode:
            sys.__stdout__.write(f"  Key Tools: {len(agent.key_tools)} loaded\n" + "-" * 60 + "\n")
            sys.__stdout__.flush()
            agent.run_loop(initial_prompt=initial_prompt or evolution_test_prompt)
        elif subagent_json_mode or getattr(args, "single_turn", False):
            goal_override = None
            if subagent_json_mode:
                goal_override = extract_subagent_primary_goal_fn(initial_prompt)
            result = agent.run_single_turn(initial_prompt=initial_prompt, goal_override=goal_override)
            if subagent_json_mode:
                print(f"{subagent_result_marker}{json.dumps(result, ensure_ascii=False)}")
        elif getattr(args, "auto", False) or initial_prompt:
            agent.run_loop(initial_prompt=initial_prompt)
        else:
            ui.add_content("[bold yellow]自动模式[/bold yellow] - 无外部输入，进入自主进化")
            agent.run_loop(initial_prompt=None)

    except Exception as e:
        ui_error_fn(f"启动异常: {type(e).__name__}: {e}", traceback.format_exc())
        ui.stop_live()
        sys.exit(1)
