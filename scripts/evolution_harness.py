# -*- coding: utf-8 -*-
"""真实进化链路测试环境。

功能：
1. 为当前工作区创建一次 checkpoint 快照（优先用临时 git ref，不污染主分支）
2. 在临时 worktree 中运行真实 agent 链路
3. 监控 stdout/stderr、conversation/debug 日志、重启接力
4. 在失败或超时后自动清理临时 worktree，并输出结构化报告
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = PROJECT_ROOT / "log_info" / "harness_reports"
DEFAULT_TEST_PROMPT = "制定重启任务，然后对重启任务打勾，然后运行 `trigger_self_restart_tool` 重启你自己。"
DEFAULT_TRANSACTION_PROMPT = (
    "执行一轮非重启演化事务探针："
    "1) 调用 open_evolution_transaction_tool 开账，summary 写“harness transaction probe”；"
    "2) 调用 python_lint_tool 检查 scripts/evolution_harness.py；"
    "3) 根据 lint 结果调用 close_evolution_transaction_tool 关账，成功则 status=success；"
    "4) 只做事务和验证探针，不要修改文件，不要提交 git，不要触发重启。"
)
SAFE_MODIFY_TOOL_PATH_PLACEHOLDER = "{SAFE_MODIFY_ABSOLUTE_PATH}"
SAFE_MODIFY_PROBE_PATH = "tests/harness_safe_modify_probe.py"
SAFE_MODIFY_MARKER = "HARNESS_SAFE_MODIFY_MARKER"
SAFE_MODIFY_PROBE_CONTENT = (
    'HARNESS_SAFE_MODIFY_MARKER = "HARNESS_SAFE_MODIFY_MARKER"\n\n'
    "\n"
    "def probe_marker() -> str:\n"
    "    return HARNESS_SAFE_MODIFY_MARKER\n"
)
HARNESS_MANAGED_DIRTY_PATHS = {"config.harness.toml"}
DEFAULT_SAFE_MODIFY_PROMPT = (
    "执行一轮安全修改/回滚演化探针："
    "1) 调用 open_evolution_transaction_tool 开账，summary 写“harness safe modify probe”；"
    f"2) 调用 write_file_tool 写入 {SAFE_MODIFY_TOOL_PATH_PLACEHOLDER}，内容必须逐字等于："
    f"{SAFE_MODIFY_PROBE_CONTENT!r}；"
    f"3) 调用 python_lint_tool 检查 {SAFE_MODIFY_PROBE_PATH}；"
    "4) 根据 lint 结果调用 close_evolution_transaction_tool 关账，成功则 status=success；"
    "5) 必须由主 agent 直接完成，不要调用 spawn_agent_tool，不要委派子 agent；"
    "6) 不要提交 git，不要触发重启，不要修改除该探针文件之外的文件。"
)
DEFAULT_FULL_EVOLUTION_PROMPT = (
    "执行一轮完整自进化闭环探针："
    "1) 调用 open_evolution_transaction_tool 开账，summary 写“harness full evolution probe”；"
    f"2) 调用 write_file_tool 写入 {SAFE_MODIFY_TOOL_PATH_PLACEHOLDER}，内容必须逐字等于："
    f"{SAFE_MODIFY_PROBE_CONTENT!r}；"
    f"3) 调用 python_lint_tool 检查 {SAFE_MODIFY_PROBE_PATH}；"
    "4) 根据 lint 结果调用 close_evolution_transaction_tool 关账，成功则 status=success；"
    "5) 关账成功后立即调用 trigger_self_restart_tool 完成重启；"
    "6) 整个探针必须由主 agent 直接完成，不要调用 spawn_agent_tool，不要委派子 agent；"
    "7) 不要提交 git，不要读取无关文件，不要创建额外任务清单，不要在重启前扩散到无关工具。"
)

try:
    import psutil  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    psutil = None


@dataclass
class SnapshotInfo:
    base_head: str
    commit: str
    ref_name: Optional[str]
    tracked_dirty: bool
    untracked_files: List[str] = field(default_factory=list)


@dataclass
class ProcessRecord:
    pid: int
    role: str
    first_seen: str
    last_seen: str
    returncode: Optional[int] = None
    cmdline_preview: str = ""


@dataclass
class HarnessRunOptions:
    mode: str
    prompt: str
    expect_restart: bool
    scenario: str


@dataclass
class HarnessResult:
    harness_id: str
    status: str
    reason: str
    started_at: str
    ended_at: str
    repo_root: str
    worktree_path: str
    base_head: str
    checkpoint_commit: str
    checkpoint_ref: Optional[str]
    tracked_dirty: bool
    untracked_files: List[str]
    command: List[str]
    timeout_seconds: int
    restarts_observed: int
    normalized_restarts_observed: int
    restart_expected: bool
    restart_reentered: bool
    process_history: List[Dict[str, Any]]
    process_summary: Dict[str, Any]
    new_conversation_files: List[str]
    new_debug_files: List[str]
    stdout_tail: List[str]
    stderr_tail: List[str]
    agent_realtime_tail: List[str]
    last_observation: Dict[str, Any]
    post_restart_observation: Dict[str, Any]
    evolution_summary: Dict[str, Any]


def run_git(repo_root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed ({proc.returncode}): "
            f"{proc.stderr.strip() or proc.stdout.strip()}"
        )
    return proc.stdout.strip()


def git_status_porcelain(repo_root: Path) -> List[str]:
    text = run_git(repo_root, "status", "--porcelain")
    return [line for line in text.splitlines() if line.strip()]


def collect_untracked_files(repo_root: Path) -> List[str]:
    text = run_git(repo_root, "ls-files", "--others", "--exclude-standard")
    return [line.strip() for line in text.splitlines() if line.strip()]


def create_checkpoint_snapshot(repo_root: Path, harness_id: str) -> SnapshotInfo:
    base_head = run_git(repo_root, "rev-parse", "HEAD")
    status_lines = git_status_porcelain(repo_root)
    tracked_dirty = any(not line.startswith("?? ") for line in status_lines)
    untracked_files = collect_untracked_files(repo_root)

    if tracked_dirty:
        commit = run_git(repo_root, "stash", "create", f"harness checkpoint {harness_id}")
        if not commit:
            commit = base_head
            ref_name = None
        else:
            ref_name = f"refs/codex-harness/{harness_id}"
            run_git(repo_root, "update-ref", ref_name, commit)
    else:
        commit = base_head
        ref_name = None

    return SnapshotInfo(
        base_head=base_head,
        commit=commit,
        ref_name=ref_name,
        tracked_dirty=tracked_dirty,
        untracked_files=untracked_files,
    )


def copy_untracked_files(repo_root: Path, worktree_path: Path, files: Iterable[str]) -> None:
    for rel in files:
        src = repo_root / rel
        dst = worktree_path / rel
        if src.is_dir():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def mirror_venv_into_worktree(repo_root: Path, worktree_path: Path) -> None:
    source = repo_root / ".venv"
    target = worktree_path / ".venv"
    if target.exists():
        return

    if os.name == "nt":
        source_python = source / "Scripts" / "python.exe"
    else:
        source_python = source / "bin" / "python"

    if not source.exists() or not source_python.exists():
        build_synthetic_venv(worktree_path)
        return

    try:
        shutil.copytree(
            source,
            target,
            symlinks=True,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"),
        )
    except Exception:
        # 最差兜底：至少复制 python 入口，避免 environment smoke 直接因 .venv 缺失挂掉
        if os.name == "nt":
            dst_python = target / "Scripts" / "python.exe"
        else:
            dst_python = target / "bin" / "python"
        dst_python.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_python, dst_python)


def build_synthetic_venv(worktree_path: Path) -> None:
    target = worktree_path / ".venv"
    if target.exists():
        return

    subprocess.run(
        [
            sys.executable,
            "-m",
            "venv",
            "--system-site-packages",
            str(target),
        ],
        cwd=str(worktree_path),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )


def create_harness_config(worktree_path: Path) -> Optional[Path]:
    source = worktree_path / "config.toml"
    if not source.exists():
        return None

    lines = source.read_text(encoding="utf-8", errors="replace").splitlines()
    out_lines: List[str] = []
    current_section: Optional[str] = None
    runtime_keys_seen = set()
    saw_runtime_section = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if current_section == "runtime":
                if "profile" not in runtime_keys_seen:
                    out_lines.append('profile = ""')
                if "preflight_doctor" not in runtime_keys_seen:
                    out_lines.append("preflight_doctor = false")
                if "require_venv" not in runtime_keys_seen:
                    out_lines.append("require_venv = false")
            current_section = stripped.strip("[]").strip()
            if current_section == "runtime":
                saw_runtime_section = True
            runtime_keys_seen = set()
            out_lines.append(line)
            continue

        if current_section == "runtime" and "=" in line:
            key = line.split("=", 1)[0].strip()
            runtime_keys_seen.add(key)
            if key == "profile":
                out_lines.append('profile = ""')
                continue
            if key == "preflight_doctor":
                out_lines.append("preflight_doctor = false")
                continue
            if key == "require_venv":
                out_lines.append("require_venv = false")
                continue

        out_lines.append(line)

    if current_section == "runtime":
        if "profile" not in runtime_keys_seen:
            out_lines.append('profile = ""')
        if "preflight_doctor" not in runtime_keys_seen:
            out_lines.append("preflight_doctor = false")
        if "require_venv" not in runtime_keys_seen:
            out_lines.append("require_venv = false")
    elif not saw_runtime_section:
        out_lines.extend(
            [
                "",
                "[runtime]",
                'profile = ""',
                "preflight_doctor = false",
                "require_venv = false",
            ]
        )

    target = worktree_path / "config.harness.toml"
    target.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    return target


def create_worktree(repo_root: Path, snapshot: SnapshotInfo, harness_id: str) -> Path:
    worktree_path = Path(tempfile.mkdtemp(prefix=f"vibelution-harness-{harness_id[:8]}-"))
    try:
        run_git(repo_root, "worktree", "add", "--detach", str(worktree_path), snapshot.commit)
        if snapshot.untracked_files:
            copy_untracked_files(repo_root, worktree_path, snapshot.untracked_files)
        mirror_venv_into_worktree(repo_root, worktree_path)
        return worktree_path
    except Exception:
        shutil.rmtree(worktree_path, ignore_errors=True)
        raise


def remove_worktree(repo_root: Path, worktree_path: Path) -> None:
    subprocess.run(
        ["git", "worktree", "remove", "--force", str(worktree_path)],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    shutil.rmtree(worktree_path, ignore_errors=True)


def delete_checkpoint_ref(repo_root: Path, ref_name: Optional[str]) -> None:
    if not ref_name:
        return
    subprocess.run(
        ["git", "update-ref", "-d", ref_name],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def resolve_python_executable(repo_root: Path) -> str:
    if os.name == "nt":
        venv_python = repo_root / ".venv" / "Scripts" / "python.exe"
    else:
        venv_python = repo_root / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


def build_agent_command(
    mode: str,
    prompt: Optional[str],
    python_executable: Optional[str] = None,
    config_path: Optional[str] = None,
) -> List[str]:
    cmd = [python_executable or sys.executable, "agent.py", "--no-shell", "--skip-doctor"]
    if config_path:
        cmd.extend(["--config", config_path])
    if mode == "test":
        cmd.append("--test")
    elif mode == "single_turn":
        cmd.append("--single-turn")
        if prompt:
            cmd.extend(["--prompt", prompt])
    elif mode == "auto":
        cmd.append("--auto")
        if prompt:
            cmd.extend(["--prompt", prompt])
    else:
        raise ValueError(f"未知运行模式: {mode}")
    return cmd


def resolve_run_options(
    scenario: str,
    mode: str,
    prompt: Optional[str],
    expect_restart: bool,
) -> HarnessRunOptions:
    """把用户入口选项归一成实际 agent 运行模式。"""
    if scenario == "restart":
        normalized_mode = mode or "test"
        normalized_prompt = prompt or DEFAULT_TEST_PROMPT
        return HarnessRunOptions(
            mode=normalized_mode,
            prompt=normalized_prompt,
            expect_restart=expect_restart or normalized_mode == "test",
            scenario="restart",
        )

    if scenario == "transaction":
        normalized_prompt = prompt or DEFAULT_TRANSACTION_PROMPT
        return HarnessRunOptions(
            mode="single_turn",
            prompt=normalized_prompt,
            expect_restart=expect_restart,
            scenario="transaction",
        )

    if scenario == "modify_rollback":
        normalized_prompt = prompt or DEFAULT_SAFE_MODIFY_PROMPT
        return HarnessRunOptions(
            mode="single_turn",
            prompt=normalized_prompt,
            expect_restart=expect_restart,
            scenario="modify_rollback",
        )

    if scenario == "full_evolution":
        normalized_prompt = prompt or DEFAULT_FULL_EVOLUTION_PROMPT
        return HarnessRunOptions(
            mode="single_turn",
            prompt=normalized_prompt,
            expect_restart=True,
            scenario="full_evolution",
        )

    if scenario == "strategy":
        return HarnessRunOptions(
            mode="single_turn",
            prompt=prompt or "Run a read-only strategy analysis and return a concise answer.",
            expect_restart=False,
            scenario="strategy",
        )

    raise ValueError(f"未知测试场景: {scenario}")


def materialize_scenario_prompt(scenario: str, prompt: Optional[str], worktree_path: Path) -> Optional[str]:
    """把需要临时 worktree 绝对路径的场景 prompt 实体化。"""
    if prompt is None:
        return None
    if scenario not in {"modify_rollback", "full_evolution"}:
        return prompt
    probe_path = worktree_path / SAFE_MODIFY_PROBE_PATH
    return prompt.replace(SAFE_MODIFY_TOOL_PATH_PLACEHOLDER, str(probe_path))


def tail_lines(path: Path, limit: int = 40) -> List[str]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return lines[-limit:]


def read_conversation_events(path: Path) -> List[Dict[str, Any]]:
    """读取 conversation JSONL，忽略损坏行，供摘要与阶段检测共用。"""
    if not path.exists():
        return []

    events: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events


def is_restart_trigger_line(line: str) -> bool:
    markers = (
        "触发自我重启",
        "重启触发成功",
        "Windows: 已启动脱离进程",
        "Restarter 模块:",
        "检测到重启动作，当前进程退出，交由守护进程接管",
    )
    return any(marker in line for marker in markers)


def summarize_conversation_file(path: Path) -> Dict[str, Any]:
    summary: Dict[str, Any] = {
        "path": str(path),
        "last_type": None,
        "last_message": "",
        "last_tool_name": None,
        "turn_stats": None,
        "phase": "no_events",
        "prompt_build": {},
    }
    if not path.exists():
        return summary

    events = read_conversation_events(path)

    if not events:
        return summary

    last = events[-1]
    summary["last_type"] = last.get("type")
    summary["last_tool_name"] = last.get("tool_name")
    summary["turn_stats"] = last.get("stats") if last.get("type") == "turn_end" else None

    message = (
        last.get("message")
        or last.get("content")
        or last.get("tool_result")
        or last.get("summary")
        or ""
    )
    summary["last_message"] = str(message)[:400]
    summary["phase"] = infer_phase_from_events(events)
    summary["first_meaningful_event"] = infer_first_meaningful_event(events)
    summary["prompt_build"] = extract_prompt_build_from_events(events)
    return summary


def extract_prompt_build_from_events(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    for event in reversed(events):
        if event.get("type") != "debug":
            continue
        tag = str(event.get("tag") or "").strip()
        message = str(event.get("message") or "")
        if tag == "prompt_build" or "prompt_build" in message:
            return {
                "tag": tag or "prompt_build",
                "message": message[:400],
            }
    return {}


def infer_first_meaningful_event(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    for event in events:
        if event.get("type") == "tool_call":
            tool_name = event.get("tool_name") or "unknown_tool"
            message = str(event.get("tool_result") or event.get("summary") or "")[:240]
            return {
                "type": "tool_call",
                "phase": "first_" + classify_tool_event_phase(event),
                "tool_name": tool_name,
                "message": message,
            }

    for event in events:
        if event.get("type") == "llm_response":
            return {
                "type": "llm_response",
                "phase": "first_llm_response",
                "tool_name": None,
                "message": str(event.get("content") or "")[:240],
            }

    for event in events:
        if event.get("type") == "debug":
            message = str(event.get("message", ""))
            if "PromptManager" in message:
                return {
                    "type": "debug",
                    "phase": "first_prompt_refresh",
                    "tool_name": None,
                    "message": message[:240],
                }
    return {
        "type": None,
        "phase": "no_meaningful_event",
        "tool_name": None,
        "message": "",
    }


def infer_post_restart_phase(
    state_summary: Dict[str, Any],
    conversation_summary: Dict[str, Any],
    debug_summary: Dict[str, Any],
) -> str:
    state_phase = state_summary.get("phase")
    if state_phase not in {"", None, "no_state", "state_unreadable", "state_unknown"}:
        return str(state_phase)

    first_meaningful = conversation_summary.get("first_meaningful_event") or {}
    first_phase = first_meaningful.get("phase")
    if isinstance(first_phase, str) and (
        first_phase.startswith("first_tool:")
        or first_phase.startswith("first_guarded_tool:")
        or first_phase.startswith("first_restart_guarded_tool:")
    ):
        return first_phase

    return str(
        conversation_summary.get("phase")
        or debug_summary.get("phase")
        or "unknown"
    )


def build_post_restart_observation(
    *,
    live_agent_pids: List[int],
    reentered_agent_pids: List[int],
    reentered_processes: List[Dict[str, Any]],
    state_summary: Dict[str, Any],
    conversation_summary: Dict[str, Any],
    debug_summary: Dict[str, Any],
) -> Dict[str, Any]:
    first_meaningful = conversation_summary.get("first_meaningful_event") or {}
    first_child_event_phase = first_meaningful.get("phase") or "no_meaningful_event"
    first_child_tool_name = first_meaningful.get("tool_name")
    observed_phase = infer_post_restart_phase(
        state_summary,
        conversation_summary,
        debug_summary,
    )
    return {
        "phase": observed_phase if live_agent_pids else "process_reentered",
        "first_child_event_phase": first_child_event_phase,
        "first_child_tool_name": first_child_tool_name,
        "state": state_summary,
        "conversation": conversation_summary,
        "debug": debug_summary,
        "prompt_build": conversation_summary.get("prompt_build") or debug_summary.get("prompt_build") or {},
        "live_agent_pids": live_agent_pids,
        "reentered_agent_pids": reentered_agent_pids[:],
        "reentered_processes": reentered_processes,
    }


def should_finish_post_restart_observation(
    *,
    observation_phase: str,
    first_child_event_phase: str,
    elapsed_seconds: float,
    min_observe_seconds: int,
    max_observe_seconds: Optional[int] = None,
) -> bool:
    """决定是否结束重启后观察窗口。

    规则：
    - 先至少观察 min_observe_seconds
    - 如果已经拿到 child 的首个真实工具/响应事件，可提前在 min 达成后结束
    - 如果还只有 prompt_refresh/no_meaningful_event，则继续等到 max_observe_seconds
    """
    if elapsed_seconds < max(1, min_observe_seconds):
        return False

    meaningful_prefixes = (
        "first_tool:",
        "first_guarded_tool:",
        "first_restart_guarded_tool:",
        "first_llm_response",
    )
    non_terminal_phases = {"prompt_refresh", "process_reentered", "not_captured", "unknown"}
    non_terminal_first_events = {"no_meaningful_event", "first_prompt_refresh"}

    if (
        any(first_child_event_phase.startswith(prefix) for prefix in meaningful_prefixes)
        or observation_phase not in non_terminal_phases
        or first_child_event_phase not in non_terminal_first_events
    ):
        return True

    max_wait = max_observe_seconds or max(min_observe_seconds * 3, min_observe_seconds + 10)
    return elapsed_seconds >= max_wait


def infer_phase_from_events(events: List[Dict[str, Any]]) -> str:
    for event in reversed(events):
        event_type = event.get("type")
        if event_type == "session_end":
            return "session_end"
        if event_type == "turn_end":
            return "turn_end"
        if event_type == "tool_call":
            return classify_tool_event_phase(event)
        if event_type == "llm_response":
            return "llm_response"
        if event_type == "debug":
            message = str(event.get("message", ""))
            if "Restarter 守护进程启动" in message:
                return "restarter_boot"
            if "当前演化事务已成功关账" in message:
                return "turn_complete"
            if "收到中断，退出" in message:
                return "interrupt_exit"
            if "PromptManager" in message:
                return "prompt_refresh"
    return "unknown"


def summarize_debug_file(path: Path) -> Dict[str, Any]:
    summary = {
        "path": str(path),
        "last_line": "",
        "phase": "no_debug",
        "prompt_build": {},
    }
    lines = tail_lines(path, limit=80)
    if not lines:
        return summary
    summary["last_line"] = lines[-1]
    for line in reversed(lines):
        if "prompt_build" in line or "[prompt_build]" in line:
            summary["prompt_build"] = {
                "message": line[:400],
            }
            break
    summary["phase"] = infer_phase_from_debug_lines(lines)
    return summary


def summarize_agent_state_file(path: Path) -> Dict[str, Any]:
    summary: Dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "status": None,
        "current_action": "",
        "current_goal": "",
        "iteration_count": None,
        "tools_executed": None,
        "last_update": "",
        "phase": "no_state",
    }
    if not path.exists():
        return summary

    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        summary["phase"] = "state_unreadable"
        return summary

    status = payload.get("status")
    action = str(payload.get("current_action") or "")
    goal = str(payload.get("current_goal") or "")
    summary.update(
        {
            "status": status,
            "current_action": action[:240],
            "current_goal": goal[:240],
            "iteration_count": payload.get("iteration_count"),
            "tools_executed": payload.get("tools_executed"),
            "last_update": str(payload.get("last_update") or ""),
            "phase": infer_phase_from_agent_state(payload),
        }
    )
    return summary


def infer_phase_from_agent_state(payload: Dict[str, Any]) -> str:
    status = str(payload.get("status") or "").upper()
    if not status:
        return "state_unknown"
    action = str(payload.get("current_action") or "").strip()
    if action:
        return f"state:{status}:{action[:60]}"
    return f"state:{status}"


def infer_phase_from_debug_lines(lines: List[str]) -> str:
    for line in reversed(lines):
        if "Restarter 守护进程启动" in line:
            return "restarter_boot"
        if "[工具护栏]" in line and "重启测试模式" in line:
            return "restart_guarded_tool"
        if "[工具护栏]" in line or "[短路]" in line or "被短路" in line:
            return "guarded_tool"
        if "[TOOL] START" in line:
            return "tool_start"
        if "[TOOL] RESULT" in line:
            return "tool_result"
        if "[感知]" in line:
            return "mental_state"
        if "PromptManager" in line:
            return "prompt_refresh"
        if "收到中断，退出" in line:
            return "interrupt_exit"
        if "Turn " in line and "complete" in line:
            return "turn_end"
    return "debug_tail"


def classify_tool_event_phase(event: Dict[str, Any]) -> str:
    """把工具事件分类成普通执行、短路护栏、重启护栏三类。"""
    tool_name = event.get("tool_name") or "unknown_tool"
    status = event.get("status", "unknown")
    result_text = str(event.get("tool_result") or event.get("summary") or "")
    if _is_guarded_tool_result(result_text):
        if "重启测试模式" in result_text or "重启闭环" in result_text:
            return f"restart_guarded_tool:{tool_name}:{status}"
        return f"guarded_tool:{tool_name}:{status}"
    return f"tool:{tool_name}:{status}"


def _is_guarded_tool_result(result_text: str) -> bool:
    markers = (
        "[短路]",
        "[工具护栏]",
        "被短路",
        "本轮已被阻塞",
        "安全策略已拦截",
        "[安全拦截]",
    )
    return any(marker in result_text for marker in markers)


def _tool_result_json(event: Dict[str, Any]) -> Dict[str, Any]:
    text = str(event.get("tool_result") or "").strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _validation_passed_for_tool(
    *,
    tool_name: str,
    result_text: str,
    result_payload: Dict[str, Any],
) -> bool:
    """区分工具执行成功和验证目标通过。"""
    if tool_name == "python_lint_tool":
        try:
            issue_count = int(result_payload.get("issue_count") or 0)
        except (TypeError, ValueError):
            issue_count = 0
        return result_payload.get("status") == "ok" and issue_count == 0

    lower_result = result_text.lower()
    return (
        "passed" in lower_result
        or "通过" in result_text
        or "[命令执行完成，无输出]" in result_text
        or '"status": "ok"' in result_text
    ) and "failed" not in lower_result and "失败" not in result_text


def _safe_modify_probe_summary(worktree_path: Path, allowed_dirty_paths: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    """采集安全修改探针的文件证据，只观察 disposable worktree。"""
    probe_path = worktree_path / SAFE_MODIFY_PROBE_PATH
    allowed_paths = {
        str(path).replace("\\", "/").rstrip("/")
        for path in (allowed_dirty_paths or [])
    }

    def is_allowed_dirty_path(path: str) -> bool:
        normalized = path.replace("\\", "/").rstrip("/")
        return normalized in allowed_paths or any(item.startswith(f"{normalized}/") for item in allowed_paths)
    summary: Dict[str, Any] = {
        "path": SAFE_MODIFY_PROBE_PATH,
        "exists": probe_path.exists(),
        "marker_present": False,
        "size": 0,
        "git_dirty": False,
        "git_status": [],
        "dirty_paths": [],
        "out_of_scope_paths": [],
        "cleanup": "pending",
    }
    if probe_path.exists():
        try:
            content = probe_path.read_text(encoding="utf-8", errors="replace")
            summary["marker_present"] = SAFE_MODIFY_MARKER in content
            summary["size"] = probe_path.stat().st_size
        except Exception as exc:
            summary["read_error"] = f"{type(exc).__name__}: {exc}"

    try:
        status_text = run_git(worktree_path, "status", "--porcelain", "--", SAFE_MODIFY_PROBE_PATH)
        status_lines = [line for line in status_text.splitlines() if line.strip()]
        summary["git_status"] = status_lines
        summary["git_dirty"] = bool(status_lines)
    except Exception as exc:
        summary["git_status_error"] = f"{type(exc).__name__}: {exc}"

    try:
        all_status_text = run_git(worktree_path, "status", "--porcelain")
        dirty_paths = []
        for line in all_status_text.splitlines():
            if not line.strip():
                continue
            path_text = line[3:].strip().replace("\\", "/")
            dirty_paths.append(path_text)
        summary["dirty_paths"] = dirty_paths
        summary["out_of_scope_paths"] = [
            path for path in dirty_paths
            if path != SAFE_MODIFY_PROBE_PATH
            and path not in HARNESS_MANAGED_DIRTY_PATHS
            and not is_allowed_dirty_path(path)
        ]
    except Exception as exc:
        summary["dirty_paths_error"] = f"{type(exc).__name__}: {exc}"

    return summary


def infer_evolution_summary(
    events: List[Dict[str, Any]],
    debug_lines: List[str],
    stdout_lines: List[str],
    *,
    restart_expected: bool,
    restart_reentered: bool,
    child_first_event_phase: Optional[str] = None,
    safe_modify_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """把一次 harness 运行压缩成进化事务阶段摘要。"""
    task_created = 0
    task_updated = 0
    task_completed = 0
    validation_passed = 0
    validation_failed = 0
    last_validation: Optional[Dict[str, Any]] = None
    transaction_opened = False
    transaction_closed = False
    transaction_status: Optional[str] = None
    transaction_id: Optional[str] = None
    commit_detected = False
    commit_refs: List[str] = []
    tool_sequence: List[str] = []
    tool_phase_sequence: List[str] = []
    guarded_tool_count = 0
    restart_guarded_tool_count = 0

    for event in events:
        if event.get("type") != "tool_call":
            continue

        tool_name = str(event.get("tool_name") or "")
        if tool_name:
            tool_sequence.append(f"{tool_name}:{event.get('status', 'unknown')}")
        tool_phase = classify_tool_event_phase(event)
        tool_phase_sequence.append(tool_phase)
        if tool_phase.startswith("restart_guarded_tool:"):
            restart_guarded_tool_count += 1
            guarded_tool_count += 1
        elif tool_phase.startswith("guarded_tool:"):
            guarded_tool_count += 1
        tool_args = event.get("tool_args") or {}
        result_text = str(event.get("tool_result") or "")
        result_payload = _tool_result_json(event)
        command_text = str(tool_args.get("command") or tool_args.get("script") or "")

        if tool_name == "task_create_tool" and event.get("status") == "success":
            task_created += 1
        elif tool_name == "task_update_tool" and event.get("status") == "success":
            task_updated += 1
            if bool(tool_args.get("is_completed")):
                task_completed += 1

        if tool_name in {"open_evolution_transaction_tool", "close_evolution_transaction_tool"}:
            if tool_name == "open_evolution_transaction_tool" and event.get("status") == "success":
                transaction_opened = True
                transaction_id = str(result_payload.get("txn_id") or transaction_id or "")
            elif tool_name == "close_evolution_transaction_tool" and event.get("status") == "success":
                transaction_closed = True
                transaction_id = str(result_payload.get("txn_id") or transaction_id or "")
                transaction_status = str(result_payload.get("transaction_status") or tool_args.get("status") or "success")

        if tool_name in {"cli_tool", "run_powershell_tool", "run_batch_tool", "execute_shell_command_tool", "python_lint_tool"}:
            lower_command = command_text.lower()
            is_validation = (
                "pytest" in lower_command
                or "py_compile" in lower_command
                or tool_name == "python_lint_tool"
                or "ruff" in lower_command
                or "mypy" in lower_command
            )
            if is_validation:
                passed = _validation_passed_for_tool(
                    tool_name=tool_name,
                    result_text=result_text,
                    result_payload=result_payload,
                )
                if passed:
                    validation_passed += 1
                else:
                    validation_failed += 1
                last_validation = {
                    "tool": tool_name,
                    "passed": passed,
                    "summary": result_text[:240],
                }

        combined_text = f"{tool_name}\n{command_text}\n{result_text}"
        if "git commit" in combined_text.lower() or "commit_sha" in result_payload:
            commit_detected = True
            ref = result_payload.get("commit_sha") or result_payload.get("sha")
            if ref:
                commit_refs.append(str(ref))

    combined_lines = "\n".join([*debug_lines, *stdout_lines])
    if "当前演化事务已成功关账" in combined_lines:
        transaction_closed = True
        transaction_status = transaction_status or "success"
    if "validation:" in combined_lines or "VALIDATION_COMPLETED" in combined_lines:
        if "failed" in combined_lines.lower() or "失败" in combined_lines:
            validation_failed = max(validation_failed, 1)
        elif "passed" in combined_lines.lower() or "通过" in combined_lines:
            validation_passed = max(validation_passed, 1)

    restart_triggered = any(is_restart_trigger_line(line) for line in stdout_lines)
    meaningful_tools = [item for item in tool_sequence if not item.startswith("get_git_")]
    meaningful_tool_phases = [
        item for item in tool_phase_sequence
        if not item.startswith("tool:get_git_")
    ]

    summary = {
        "tasks": {
            "created": task_created,
            "updated": task_updated,
            "completed": task_completed,
        },
        "validation": {
            "passed": validation_passed,
            "failed": validation_failed,
            "last": last_validation,
        },
        "transaction": {
            "opened": transaction_opened,
            "closed": transaction_closed,
            "status": transaction_status,
            "txn_id": transaction_id or None,
        },
        "git": {
            "commit_detected": commit_detected,
            "commit_refs": commit_refs[-5:],
        },
        "restart": {
            "expected": restart_expected,
            "triggered": restart_triggered,
            "reentered": restart_reentered,
        },
        "child": {
            "first_event_phase": child_first_event_phase or "unknown",
        },
        "tool_sequence_tail": meaningful_tools[-12:],
        "tool_phase_sequence_tail": meaningful_tool_phases[-12:],
        "guarded_tools": {
            "total": guarded_tool_count,
            "restart_guarded": restart_guarded_tool_count,
        },
    }
    if safe_modify_summary is not None:
        summary["safe_modify"] = safe_modify_summary
    return summary


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def start_stream_reader(stream, sink_queue: queue.Queue, stream_name: str) -> threading.Thread:
    def _reader() -> None:
        try:
            for line in iter(stream.readline, ""):
                sink_queue.put((stream_name, line.rstrip("\n")))
        finally:
            try:
                stream.close()
            except Exception:
                pass

    thread = threading.Thread(target=_reader, daemon=True)
    thread.start()
    return thread


def find_agent_processes(worktree_path: Path) -> List[Dict[str, Any]]:
    if psutil is None:
        return []
    matched: List[Dict[str, Any]] = []
    worktree_str = str(worktree_path).lower()
    for proc in psutil.process_iter(["pid", "name", "cmdline", "cwd"]):
        try:
            cmdline = proc.info.get("cmdline") or []
            cwd = (proc.info.get("cwd") or "").lower()
            cmd_text = " ".join(cmdline).lower()
            if worktree_str not in cmd_text and worktree_str not in cwd:
                continue
            if "core.restarter_manager.restarter" in cmd_text or "restarter.py" in cmd_text:
                matched.append({"pid": proc.pid, "role": "restarter", "cmdline_preview": " ".join(cmdline)[:240]})
            elif "agent.py" in cmd_text:
                matched.append({"pid": proc.pid, "role": "agent", "cmdline_preview": " ".join(cmdline)[:240]})
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return matched


def summarize_process_history(
    process_history: Iterable[ProcessRecord],
    *,
    reentered_agent_pids: Optional[Iterable[int]] = None,
) -> Dict[str, Any]:
    """压缩 Windows 上容易重复显形的 Python 进程记录，保留原始 history 供深查。"""
    reentered_set = set(reentered_agent_pids or [])
    role_counts: Dict[str, int] = {}
    families: Dict[str, Dict[str, Any]] = {}

    for record in process_history:
        role_counts[record.role] = role_counts.get(record.role, 0) + 1
        family_key = _process_family_key(record)
        family = families.setdefault(
            family_key,
            {
                "role": record.role,
                "family": family_key.split(":", 1)[-1],
                "count": 0,
                "pids": [],
                "reentered_pids": [],
                "sample_cmdline_preview": record.cmdline_preview,
            },
        )
        family["count"] += 1
        family["pids"].append(record.pid)
        if record.pid in reentered_set:
            family["reentered_pids"].append(record.pid)

    unique_agent_families = [
        item for item in families.values()
        if item["role"] == "agent"
    ]
    unique_restarter_families = [
        item for item in families.values()
        if item["role"] == "restarter"
    ]
    duplicate_families = [
        item for item in families.values()
        if item["count"] > 1
    ]
    normalized_reentered_agent_count = sum(
        1 for item in unique_agent_families
        if item["reentered_pids"]
    )

    return {
        "raw_count": sum(role_counts.values()),
        "role_counts": role_counts,
        "unique_agent_families": len(unique_agent_families),
        "unique_restarter_families": len(unique_restarter_families),
        "normalized_reentered_agent_count": normalized_reentered_agent_count,
        "duplicate_families": duplicate_families,
        "families": list(families.values()),
    }


def _process_family_key(record: ProcessRecord) -> str:
    raw_preview = record.cmdline_preview.replace("\\", "/").lower()
    if "core.restarter_manager.restarter" in raw_preview or "restarter.py" in raw_preview:
        return f"{record.role}:restarter"
    if "agent.py" in raw_preview:
        mode = "agent"
        if "--single-turn" in raw_preview:
            mode = "agent_single_turn"
        elif "--test" in raw_preview:
            mode = "agent_test"
        return f"{record.role}:{mode}"
    return f"{record.role}:python_process"


def terminate_harness_processes(worktree_path: Path) -> None:
    if psutil is None:
        return
    pids = [item["pid"] for item in find_agent_processes(worktree_path)]
    for pid in pids:
        try:
            proc = psutil.Process(pid)
            proc.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    gone, alive = psutil.wait_procs(
        [psutil.Process(pid) for pid in pids if psutil.pid_exists(pid)],
        timeout=5,
    )
    for proc in alive:
        try:
            proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass


def detect_new_files(directory: Path, before: set[str], pattern: str) -> List[str]:
    now = {
        str(path.relative_to(directory))
        for path in directory.glob(pattern)
    }
    return sorted(now - before)


def summarize_latest_matching_file(directory: Path, pattern: str, summary_fn) -> Dict[str, Any]:
    candidates = sorted(directory.glob(pattern), key=lambda path: path.stat().st_mtime)
    if not candidates:
        return {}
    return summary_fn(candidates[-1])


def select_observation_files(files: List[str], *, expect_restart: bool) -> List[str]:
    """选择用于阶段归因的日志文件，保留报告里的完整文件清单。"""
    if expect_restart:
        return files
    return files[:1]


def should_stop_after_primary_exit(
    *,
    expect_restart: bool,
    primary_returncode: Optional[int],
) -> bool:
    """非重启场景以主进程退出为收束点，残留子进程由清理阶段处理。"""
    return not expect_restart and primary_returncode is not None


def infer_result_status(
    *,
    timed_out: bool,
    restart_expected: bool,
    restart_reentered: bool,
    primary_returncode: Optional[int],
    last_observation: Dict[str, Any],
    evolution_summary: Optional[Dict[str, Any]] = None,
) -> tuple[str, str]:
    if timed_out:
        phase = last_observation.get("phase") or "unknown"
        return "timeout", f"运行超时，最后观察阶段: {phase}"

    if evolution_summary and "safe_modify" in evolution_summary:
        safe_modify = evolution_summary.get("safe_modify") or {}
        transaction = evolution_summary.get("transaction") or {}
        validation = evolution_summary.get("validation") or {}
        if not safe_modify.get("exists"):
            return "failed", "安全修改探针未创建目标文件"
        if not safe_modify.get("marker_present"):
            return "failed", "安全修改探针文件缺少 marker"
        transaction_status = str(transaction.get("status") or "")
        if not transaction.get("closed"):
            return "failed", "安全修改探针事务未关账"
        if transaction_status == "failed":
            if int(validation.get("failed") or 0) >= 1:
                return "failed", "安全修改探针验证失败，事务已按失败状态关账"
            return "failed", "安全修改探针事务失败，但未记录验证失败"
        if int(validation.get("passed") or 0) < 1:
            return "failed", "安全修改探针未完成通过验证"
        if transaction_status != "success":
            return "failed", "安全修改探针事务状态未知"
        if safe_modify.get("out_of_scope_paths"):
            return "failed", "安全修改探针出现越界文件修改"
    if restart_expected:
        if restart_reentered:
            return "success", "已观察到真实重启接力并重新进入 agent 主线"
        return "failed", "预期重启，但未观察到新 agent 进程重新接力"
    if evolution_summary:
        transaction = evolution_summary.get("transaction") or {}
        validation = evolution_summary.get("validation") or {}
        if transaction.get("opened"):
            transaction_status = str(transaction.get("status") or "")
            if not transaction.get("closed"):
                return "failed", "事务探针未关账"
            if transaction_status == "failed":
                return "failed", "事务探针以失败状态关账"
            if transaction_status != "success":
                return "failed", "事务探针状态未知"
            if int(validation.get("passed") or 0) < 1:
                return "failed", "事务探针未完成通过验证"
    if primary_returncode == 0:
        return "success", "主进程正常结束"
    if last_observation.get("turn_stats"):
        return "success", "检测到完整回合结束统计"
    return "failed", f"主进程异常退出: {primary_returncode}"


def extend_deadline_for_restart_trigger(
    *,
    current_deadline: float,
    now: float,
    post_restart_observe_seconds: int,
) -> float:
    return max(current_deadline, now + max(1, post_restart_observe_seconds))


def write_report(result: HarnessResult, path: Optional[Path] = None) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    if path is None:
        path = REPORT_DIR / f"harness_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{result.harness_id[:8]}.json"
    path.write_text(json.dumps(asdict(result), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def run_harness(
    *,
    repo_root: Path,
    mode: str,
    prompt: Optional[str],
    timeout_seconds: int,
    expect_restart: bool,
    post_restart_observe_seconds: int,
    keep_worktree: bool,
    scenario: str = "restart",
) -> HarnessResult:
    harness_id = uuid.uuid4().hex
    started_at = now_iso()
    snapshot = create_checkpoint_snapshot(repo_root, harness_id)
    worktree_path = create_worktree(repo_root, snapshot, harness_id)
    harness_config = create_harness_config(worktree_path)
    prompt = materialize_scenario_prompt(scenario, prompt, worktree_path)
    command = build_agent_command(
        mode,
        prompt,
        python_executable=resolve_python_executable(worktree_path),
        config_path=str(harness_config) if harness_config else None,
    )

    log_info_dir = worktree_path / "log_info"
    logs_dir = worktree_path / "logs"
    state_file = worktree_path / "agent_state.json"
    log_info_dir.mkdir(exist_ok=True)
    logs_dir.mkdir(exist_ok=True)
    before_conversation = {
        str(path.relative_to(log_info_dir))
        for path in log_info_dir.glob("conversation_*.jsonl")
    }
    before_debug = {
        str(path.relative_to(log_info_dir))
        for path in log_info_dir.glob("debug_*.log")
    }

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["VIBELUTION_HARNESS_ID"] = harness_id

    process = subprocess.Popen(
        command,
        cwd=str(worktree_path),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        bufsize=1,
    )

    sink: queue.Queue = queue.Queue()
    stdout_thread = start_stream_reader(process.stdout, sink, "stdout")
    stderr_thread = start_stream_reader(process.stderr, sink, "stderr")

    stdout_tail: List[str] = []
    stderr_tail: List[str] = []
    process_history: Dict[int, ProcessRecord] = {
        process.pid: ProcessRecord(
            pid=process.pid,
            role="agent",
            first_seen=started_at,
            last_seen=started_at,
            cmdline_preview=" ".join(command)[:240],
        )
    }
    restart_reentered = False
    restarts_observed = 0
    primary_returncode: Optional[int] = None
    timed_out = False
    restart_observed_at: Optional[float] = None
    post_restart_observation: Dict[str, Any] = {}
    restart_triggered = False
    restart_triggered_at: Optional[float] = None
    pre_restart_agent_pids = {process.pid}
    reentered_agent_pids: List[int] = []
    deadline = time.time() + timeout_seconds

    try:
        while time.time() < deadline:
            while True:
                try:
                    stream_name, line = sink.get_nowait()
                except queue.Empty:
                    break
                if stream_name == "stdout":
                    stdout_tail.append(line)
                    stdout_tail[:] = stdout_tail[-120:]
                    if expect_restart and is_restart_trigger_line(line):
                        restart_triggered = True
                        if restart_triggered_at is None:
                            restart_triggered_at = time.time()
                            deadline = extend_deadline_for_restart_trigger(
                                current_deadline=deadline,
                                now=restart_triggered_at,
                                post_restart_observe_seconds=post_restart_observe_seconds,
                            )
                        pre_restart_agent_pids = {
                            pid for pid, record in process_history.items()
                            if record.role == "agent"
                        }
                else:
                    stderr_tail.append(line)
                    stderr_tail[:] = stderr_tail[-120:]

            current_returncode = process.poll()
            if current_returncode is not None and primary_returncode is None:
                primary_returncode = current_returncode
                process_history[process.pid].returncode = current_returncode

            for item in find_agent_processes(worktree_path):
                pid = item["pid"]
                role = item["role"]
                cmdline_preview = item.get("cmdline_preview", "")
                ts = now_iso()
                if pid not in process_history:
                    process_history[pid] = ProcessRecord(
                        pid=pid,
                        role=role,
                        first_seen=ts,
                        last_seen=ts,
                        cmdline_preview=cmdline_preview,
                    )
                    if role == "agent" and (
                        (restart_triggered and pid not in pre_restart_agent_pids)
                        or (pid != process.pid and primary_returncode is not None)
                    ):
                        restart_reentered = True
                        restarts_observed += 1
                        reentered_agent_pids.append(pid)
                        if restart_observed_at is None:
                            restart_observed_at = time.time()
                else:
                    process_history[pid].last_seen = ts

            if expect_restart and restart_reentered and restart_observed_at is not None:
                latest_conversation = summarize_latest_matching_file(
                    log_info_dir,
                    "conversation_*.jsonl",
                    summarize_conversation_file,
                )
                latest_debug = summarize_latest_matching_file(
                    log_info_dir,
                    "debug_*.log",
                    summarize_debug_file,
                )
                latest_state = summarize_agent_state_file(state_file)
                live_agent_pids = [
                    item["pid"] for item in find_agent_processes(worktree_path)
                    if item["role"] == "agent"
                ]
                reentered_processes = [
                    asdict(record)
                    for pid, record in process_history.items()
                    if pid in reentered_agent_pids
                ]
                post_restart_observation = build_post_restart_observation(
                    live_agent_pids=live_agent_pids,
                    reentered_agent_pids=reentered_agent_pids,
                    reentered_processes=reentered_processes,
                    state_summary=latest_state,
                    conversation_summary=latest_conversation,
                    debug_summary=latest_debug,
                )
                elapsed = time.time() - restart_observed_at
                if should_finish_post_restart_observation(
                    observation_phase=str(post_restart_observation.get("phase") or "unknown"),
                    first_child_event_phase=str(post_restart_observation.get("first_child_event_phase") or "no_meaningful_event"),
                    elapsed_seconds=elapsed,
                    min_observe_seconds=post_restart_observe_seconds,
                ):
                    break

            if should_stop_after_primary_exit(
                expect_restart=expect_restart,
                primary_returncode=primary_returncode,
            ):
                break

            time.sleep(1.0)
        else:
            timed_out = True
    finally:
        try:
            stdout_thread.join(timeout=0.5)
            stderr_thread.join(timeout=0.5)
        except Exception:
            pass

        terminate_harness_processes(worktree_path)

    new_conversation_files = detect_new_files(log_info_dir, before_conversation, "conversation_*.jsonl")
    new_debug_files = detect_new_files(log_info_dir, before_debug, "debug_*.log")

    conversation_summary = {}
    conversation_events: List[Dict[str, Any]] = []
    if new_conversation_files:
        selected_conversation_files = select_observation_files(
            new_conversation_files,
            expect_restart=expect_restart,
        )
        conversation_paths = [log_info_dir / item for item in selected_conversation_files]
        conversation_summary = summarize_conversation_file(conversation_paths[-1])
        for conversation_path in conversation_paths:
            conversation_events.extend(read_conversation_events(conversation_path))

    debug_summary = {}
    debug_lines: List[str] = []
    if new_debug_files:
        selected_debug_files = select_observation_files(
            new_debug_files,
            expect_restart=expect_restart,
        )
        debug_paths = [log_info_dir / item for item in selected_debug_files]
        debug_summary = summarize_debug_file(debug_paths[-1])
        for debug_path in debug_paths:
            debug_lines.extend(tail_lines(debug_path, limit=120))

    agent_realtime_path = logs_dir / "agent_realtime.log"
    agent_realtime_tail = tail_lines(agent_realtime_path, limit=80)

    last_observation = {
        "phase": conversation_summary.get("phase") or debug_summary.get("phase") or "unknown",
        "conversation": conversation_summary,
        "debug": debug_summary,
    }
    if not post_restart_observation and expect_restart:
        post_restart_observation = build_post_restart_observation(
            live_agent_pids=[],
            reentered_agent_pids=reentered_agent_pids,
            reentered_processes=[],
            state_summary=summarize_agent_state_file(state_file),
            conversation_summary={},
            debug_summary={},
        )
        post_restart_observation["phase"] = "not_captured"
    safe_modify_summary = (
        _safe_modify_probe_summary(worktree_path, allowed_dirty_paths=snapshot.untracked_files)
        if scenario in {"modify_rollback", "full_evolution"}
        else None
    )
    evolution_summary = infer_evolution_summary(
        conversation_events,
        debug_lines,
        stdout_tail,
        restart_expected=expect_restart,
        restart_reentered=restart_reentered,
        child_first_event_phase=post_restart_observation.get("first_child_event_phase"),
        safe_modify_summary=safe_modify_summary,
    )
    status, reason = infer_result_status(
        timed_out=timed_out,
        restart_expected=expect_restart,
        restart_reentered=restart_reentered,
        primary_returncode=primary_returncode,
        last_observation=last_observation,
        evolution_summary=evolution_summary,
    )
    process_summary = summarize_process_history(
        process_history.values(),
        reentered_agent_pids=reentered_agent_pids,
    )

    result = HarnessResult(
        harness_id=harness_id,
        status=status,
        reason=reason,
        started_at=started_at,
        ended_at=now_iso(),
        repo_root=str(repo_root),
        worktree_path=str(worktree_path),
        base_head=snapshot.base_head,
        checkpoint_commit=snapshot.commit,
        checkpoint_ref=snapshot.ref_name,
        tracked_dirty=snapshot.tracked_dirty,
        untracked_files=snapshot.untracked_files,
        command=command,
        timeout_seconds=timeout_seconds,
        restarts_observed=restarts_observed,
        normalized_restarts_observed=process_summary["normalized_reentered_agent_count"],
        restart_expected=expect_restart,
        restart_reentered=restart_reentered,
        process_history=[asdict(item) for item in process_history.values()],
        process_summary=process_summary,
        new_conversation_files=new_conversation_files,
        new_debug_files=new_debug_files,
        stdout_tail=stdout_tail[-80:],
        stderr_tail=stderr_tail[-80:],
        agent_realtime_tail=agent_realtime_tail,
        last_observation=last_observation,
        post_restart_observation=post_restart_observation,
        evolution_summary=evolution_summary,
    )

    report_path = write_report(result)
    print(f"[harness] report: {report_path}")

    if not keep_worktree:
        remove_worktree(repo_root, worktree_path)
        delete_checkpoint_ref(repo_root, snapshot.ref_name)
        if safe_modify_summary is not None:
            result.evolution_summary["safe_modify"]["cleanup"] = "worktree_removed"
            write_report(result, report_path)
    elif safe_modify_summary is not None:
        result.evolution_summary["safe_modify"]["cleanup"] = "worktree_kept"
        write_report(result, report_path)

    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Vibelution 真实进化链路测试环境")
    parser.add_argument("--scenario", choices=["restart", "transaction", "modify_rollback", "full_evolution", "strategy"], default="restart")
    parser.add_argument("--mode", choices=["test", "auto", "single_turn"], default="test")
    parser.add_argument("--prompt", default=None, help="初始提示词；为空时按 scenario 使用默认探针")
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--post-restart-observe-seconds", type=int, default=20)
    parser.add_argument("--expect-restart", action="store_true")
    parser.add_argument("--keep-worktree", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    options = resolve_run_options(
        scenario=args.scenario,
        mode=args.mode,
        prompt=args.prompt,
        expect_restart=args.expect_restart,
    )
    result = run_harness(
        repo_root=PROJECT_ROOT,
        mode=options.mode,
        prompt=options.prompt,
        scenario=options.scenario,
        timeout_seconds=args.timeout_seconds,
        expect_restart=options.expect_restart,
        post_restart_observe_seconds=args.post_restart_observe_seconds,
        keep_worktree=args.keep_worktree,
    )
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    return 0 if result.status == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
