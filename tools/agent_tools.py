#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agent 工具 — 子代理启动

提供结构化的 spawn_agent()，通过子进程运行 agent.py 执行只读聚焦任务。
"""

from __future__ import annotations

import json
import os
import queue
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from core.orchestration.subagent_roles import ALLOWED_SUBAGENT_TASK_TYPES

# 子 agent 只允许由主 agent 派发一次，不允许继续级联委派。
_MAX_RECURSION_DEPTH = 1
_SUBAGENT_MARKER = "__VIBELUTION_SUBAGENT_RESULT__"
_stream_sink_local = threading.local()


def set_subagent_stream_sink(callback: Optional[Callable[[Dict[str, str]], None]]) -> None:
    """仅供主 agent 内部使用：注册子 agent 输出流回调。"""
    _stream_sink_local.callback = callback


def _emit_stream_event(stream: str, text: str) -> None:
    callback = getattr(_stream_sink_local, "callback", None)
    if not callback or not text:
        return
    try:
        callback({"stream": stream, "text": text})
    except Exception:
        return


def _subagent_process_group_kwargs() -> Dict[str, Any]:
    """Start subagents in a killable process group where the platform supports it."""

    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
    return {"start_new_session": True}


def _terminate_process_tree(process: subprocess.Popen) -> None:
    """Best-effort termination for the subagent and anything it spawned."""

    pid = getattr(process, "pid", None)
    if os.name == "nt" and pid:
        try:
            result = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            if getattr(result, "returncode", 1) == 0:
                return
        except Exception:
            pass
    elif pid:
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
            return
        except Exception:
            pass

    try:
        process.kill()
    except Exception:
        pass


def _get_recursion_depth() -> int:
    try:
        return int(os.environ.get("VIBELUTION_SUBAGENT_DEPTH", "0"))
    except (ValueError, TypeError):
        return 0


def _normalize_scope(scope: Any) -> Any:
    if scope is None:
        return ""
    if isinstance(scope, str):
        stripped = scope.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                return json.loads(stripped)
            except Exception:
                return stripped
        return stripped
    return scope


def _normalize_constraints(constraints: Any) -> Dict[str, Any]:
    if constraints is None or constraints == "":
        return {}
    if isinstance(constraints, dict):
        return dict(constraints)
    if isinstance(constraints, str):
        try:
            data = json.loads(constraints)
            return dict(data) if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def _normalize_deliverables(deliverables: Any) -> List[str]:
    if deliverables is None or deliverables == "":
        return []
    if isinstance(deliverables, list):
        return [str(item).strip() for item in deliverables if str(item).strip()]
    if isinstance(deliverables, str):
        stripped = deliverables.strip()
        if stripped.startswith("["):
            try:
                data = json.loads(stripped)
                if isinstance(data, list):
                    return [str(item).strip() for item in data if str(item).strip()]
            except Exception:
                pass
        return [part.strip() for part in stripped.split(",") if part.strip()]
    return []


def _normalize_context_pack(context_pack: Any) -> str:
    if context_pack is None:
        return ""
    if isinstance(context_pack, str):
        return context_pack.strip()
    return json.dumps(context_pack, ensure_ascii=False, indent=2)


def _extract_conversation_log_path(goal: str, scope: Any) -> Optional[Path]:
    candidates: List[str] = []
    goal_text = str(goal or "").strip()
    if goal_text:
        candidates.append(goal_text)
    if isinstance(scope, dict):
        for value in scope.values():
            if isinstance(value, str):
                candidates.append(value)
    elif isinstance(scope, str):
        candidates.append(scope)

    for text in candidates:
        stripped = str(text).strip().strip("'\"")
        direct_path = Path(stripped)
        if re.fullmatch(r"conversation_\d{8}_\d{6}(?:__.+)?\.jsonl", direct_path.name, flags=re.IGNORECASE):
            if direct_path.exists():
                return direct_path.resolve()
        match = re.search(
            r"(log_info[\\/]+conversation_\d{8}_\d{6}(?:__[^\\/]+)?\.jsonl)",
            text,
            flags=re.IGNORECASE,
        )
        if not match:
            continue
        path = Path(match.group(1).replace("/", os.sep).replace("\\", os.sep))
        if not path.is_absolute():
            path = (Path(__file__).resolve().parent.parent / path).resolve()
        if path.exists():
            return path
    return None


def _fast_diagnose_conversation_log(goal: str, scope: Any) -> Optional[Dict[str, Any]]:
    path = _extract_conversation_log_path(goal, scope)
    if path is None:
        return None

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return None

    findings: List[str] = []
    evidence: List[str] = []
    error_patterns = (
        "OSError:",
        "ValueError:",
        "RuntimeError:",
        "TimeoutError:",
        "主循环异常:",
        "[超时]",
    )
    for idx, line in enumerate(lines, start=1):
        if any(marker in line for marker in error_patterns):
            compact = line.strip()
            evidence.append(f"{path.name}:{idx}")
            findings.append(f"第 {idx} 行命中异常线索。")
            summary_match = re.search(
                r"(OSError:\s*\[Errno\s*\d+\][^\\n\"]*|ValueError:[^\\n\"]*|RuntimeError:[^\\n\"]*|TimeoutError:[^\\n\"]*|\[超时\][^\\n\"]*)",
                compact,
            )
            summary = summary_match.group(1).strip() if summary_match else compact[:240]
            return {
                "status": "completed",
                "summary": summary,
                "findings": findings[:3],
                "evidence": evidence[:3],
                "recommended_next_action": "主 agent 可依据异常行与 traceback 直接收束，不必继续委派。",
                "confidence": "high",
                "scope_touched": {"log": str(path)},
                "raw_output": compact[:800],
                "process_output": compact[:800],
                "exit_code": 0,
                "fast_path": "conversation_log_scan",
            }

    for idx, line in enumerate(lines, start=1):
        if "\"ok\": false" in line or "\"ok\":false" in line:
            evidence.append(f"{path.name}:{idx}")
            findings.append("session_end 显示本轮未成功完成。")
            return {
                "status": "partial",
                "summary": "session_end 显示 ok=false，但未直接命中异常行。",
                "findings": findings[:3],
                "evidence": evidence[:3],
                "recommended_next_action": "主 agent 读取命中的 session_end 附近行继续收束。",
                "confidence": "medium",
                "scope_touched": {"log": str(path)},
                "raw_output": lines[idx - 1][:800],
                "process_output": lines[idx - 1][:800],
                "exit_code": 0,
                "fast_path": "conversation_log_scan",
            }
    return None


def _build_legacy_prompt(task: str) -> str:
    return (
        "你现在是一个只读专项分析子 agent。\n"
        "你不写文件、不改 prompt、不改 memory、不做 git 操作、不做最终裁决。\n"
        "请围绕以下唯一任务开展分析，并在最后只输出一个 JSON 对象：\n\n"
        f"{task.strip()}\n\n"
        "JSON 至少包含: status, summary, findings, evidence, recommended_next_action, confidence"
    )


def _build_subagent_prompt(
    *,
    task: str = "",
    task_type: str = "",
    goal: str = "",
    scope: Any = None,
    constraints: Optional[Dict[str, Any]] = None,
    deliverables: Optional[List[str]] = None,
    context_pack: str = "",
) -> str:
    if task and not goal and not task_type:
        return _build_legacy_prompt(task)

    try:
        from core.prompt_manager import get_prompt_manager

        return get_prompt_manager().build_subagent_prompt(
            task_type=task_type or "inspect",
            goal=goal or task or "分析当前问题",
            scope=scope,
            constraints=constraints or {},
            deliverables=deliverables or [],
            context_pack=context_pack,
        )
    except Exception:
        merged_goal = goal or task or "分析当前问题"
        return _build_legacy_prompt(merged_goal)


def _infer_structured_fallback(raw_output: str, process_output: str, exit_code: int) -> Dict[str, Any]:
    haystack = ((process_output or "") + "\n" + (raw_output or "")).strip()
    if not haystack:
        return {}

    error_patterns = [
        r"(OSError:\s*\[Errno\s*\d+\][^\n]*)",
        r"(ValueError:[^\n]*)",
        r"(RuntimeError:[^\n]*)",
        r"(TimeoutError:[^\n]*)",
        r"(主循环异常:[^\n]*)",
        r"(\[超时\][^\n]*)",
    ]
    evidence: List[str] = []
    findings: List[str] = []
    for pattern in error_patterns:
        match = re.search(pattern, haystack, flags=re.IGNORECASE)
        if match:
            line = match.group(1).strip()
            evidence.append(line)
            findings.append(f"已从原始输出提取异常: {line}")
            break

    trace_match = re.search(r"(Traceback[\s\S]{0,1200})", haystack)
    if trace_match:
        findings.append("原始输出包含 traceback，可直接用于主 agent 收束归因。")

    if not evidence and not findings:
        conclusion_patterns = [
            (
                r"(验证已完成[\s\S]{0,500}?(?:不应该执行|不应执行|是否应执行\s*[:：]\s*否)[\s\S]{0,500}?(?:Windows 等价命令|PowerShell|结构化只读工具))",
                "子 agent 已给出平台兼容性结论。",
            ),
            (
                r"(命令平台识别[\s\S]{0,500}?(?:不应该执行|不应执行|是否应执行\s*[:：]\s*否)[\s\S]{0,500}?(?:Unix|Windows|PowerShell))",
                "子 agent 已给出命令平台识别结论。",
            ),
        ]
        for pattern, finding in conclusion_patterns:
            match = re.search(pattern, haystack, flags=re.IGNORECASE)
            if match:
                summary = re.sub(r"\s+", " ", match.group(1)).strip()
                findings.append(finding)
                if "`/dev/null`" in haystack or "/dev/null" in haystack:
                    evidence.append("输出指出 `/dev/null` 是 Unix 特有片段。")
                if "`tail`" in haystack or "tail" in haystack:
                    evidence.append("输出指出 `tail` 是 Unix 特有命令。")
                return {
                    "status": "partial" if exit_code == 0 else "failed",
                    "summary": summary[:500],
                    "findings": findings[:3],
                    "evidence": evidence[:3],
                    "recommended_next_action": "主 agent 可直接收束平台判断，不必继续委派。",
                    "confidence": "medium",
                }

    if not evidence and not findings:
        return {}

    summary = evidence[0] if evidence else "子 agent 未按 JSON 返回，但原始输出已包含异常线索。"
    return {
        "status": "partial" if exit_code == 0 else "failed",
        "summary": summary[:500],
        "findings": findings[:3],
        "evidence": evidence[:3],
        "recommended_next_action": "主 agent 根据已提取异常直接收束，不再继续委派。",
        "confidence": "medium" if evidence else "low",
    }


def _normalize_payload_with_fallback(payload: Dict[str, Any], raw_output: str, process_output: str, exit_code: int) -> Dict[str, Any]:
    summary = str(payload.get("summary") or "").strip()
    findings = payload.get("findings")
    evidence = payload.get("evidence")
    has_structured_content = bool(summary) and not summary.lower().startswith("<think>")
    has_evidence = bool(findings) or bool(evidence)
    if has_structured_content and has_evidence:
        return payload

    inferred = _infer_structured_fallback(raw_output, process_output, exit_code)
    if not inferred:
        return payload

    merged = dict(payload)
    for key, value in inferred.items():
        if key == "status":
            merged[key] = value
            continue
        current = merged.get(key)
        if current in (None, "", [], {}):
            merged[key] = value
        elif key in {"summary", "recommended_next_action", "confidence"} and str(current).strip().lower().startswith("<think>"):
            merged[key] = value
    if str(merged.get("summary") or "").strip().lower().startswith("<think>"):
        merged["summary"] = inferred.get("summary", merged.get("summary"))
    if not merged.get("findings"):
        merged["findings"] = inferred.get("findings", [])
    if not merged.get("evidence"):
        merged["evidence"] = inferred.get("evidence", [])
    if not merged.get("recommended_next_action"):
        merged["recommended_next_action"] = inferred.get("recommended_next_action", "")
    if not merged.get("confidence"):
        merged["confidence"] = inferred.get("confidence", "low")
    return merged


def _extract_structured_result(stdout: str, stderr: str, exit_code: int, task_type: str, goal: str, scope: Any) -> Dict[str, Any]:
    expected_keys = {"status", "summary", "findings", "evidence", "recommended_next_action", "confidence"}
    text = stdout or ""
    marker_idx = text.rfind(_SUBAGENT_MARKER)
    console_output = text[:marker_idx].strip() if marker_idx >= 0 else text.strip()
    raw_output = text.strip()
    if stderr:
        raw_output = (raw_output + f"\n\n[stderr]\n{stderr.strip()}").strip()
        console_output = (console_output + f"\n\n[stderr]\n{stderr.strip()}").strip()

    if marker_idx >= 0:
        payload_text = text[marker_idx + len(_SUBAGENT_MARKER):].strip()
        try:
            payload = json.loads(payload_text)
            if isinstance(payload, dict) and (expected_keys & set(payload.keys())):
                payload = _normalize_payload_with_fallback(payload, raw_output, console_output, exit_code)
                payload.setdefault("status", "completed" if exit_code == 0 else "failed")
                payload.setdefault("task_type", task_type or "inspect")
                payload.setdefault("goal", goal)
                payload.setdefault("scope_touched", scope)
                payload.setdefault("raw_output", raw_output[:8000])
                payload["process_output"] = console_output[:8000]
                payload.setdefault("exit_code", exit_code)
                return payload
        except Exception:
            pass

    match = re.search(r"\{[\s\S]*\}\s*$", text.strip())
    if match:
        try:
            payload = json.loads(match.group(0))
            if isinstance(payload, dict) and (expected_keys & set(payload.keys())):
                payload = _normalize_payload_with_fallback(payload, raw_output, console_output, exit_code)
                payload.setdefault("status", "completed" if exit_code == 0 else "failed")
                payload.setdefault("task_type", task_type or "inspect")
                payload.setdefault("goal", goal)
                payload.setdefault("scope_touched", scope)
                payload.setdefault("raw_output", raw_output[:8000])
                payload["process_output"] = console_output[:8000]
                payload.setdefault("exit_code", exit_code)
                return payload
        except Exception:
            pass

    inferred = _infer_structured_fallback(raw_output, console_output, exit_code)
    if inferred:
        inferred.setdefault("task_type", task_type or "inspect")
        inferred.setdefault("goal", goal)
        inferred.setdefault("scope_touched", scope)
        inferred.setdefault("raw_output", raw_output[:8000])
        inferred["process_output"] = console_output[:8000]
        inferred.setdefault("exit_code", exit_code)
        return inferred

    summary = raw_output[:500] if raw_output else "子 agent 未返回结构化结果"
    return {
        "status": "failed" if exit_code else "completed",
        "task_type": task_type or "inspect",
        "goal": goal,
        "summary": summary,
        "findings": [],
        "evidence": [],
        "recommended_next_action": "主 agent 接管并自行收束",
        "confidence": "low",
        "scope_touched": scope,
        "raw_output": raw_output[:8000],
        "process_output": console_output[:8000],
        "exit_code": exit_code,
    }


def spawn_agent(
    task: str = "",
    timeout: int = 120,
    task_type: str = "",
    goal: str = "",
    scope: Any = None,
    constraints: Any = None,
    deliverables: Any = None,
    context_pack: Any = None,
    _cancel_checker: Optional[Callable[[], str]] = None,
) -> str:
    """启动子 Agent 执行指定任务并返回结构化结果。"""
    normalized_constraints = _normalize_constraints(constraints)
    normalized_deliverables = _normalize_deliverables(deliverables)
    normalized_scope = _normalize_scope(scope)
    normalized_context_pack = _normalize_context_pack(context_pack)
    normalized_task_type = (task_type or "").strip().lower()
    fast_result = None
    if normalized_task_type and normalized_task_type not in ALLOWED_SUBAGENT_TASK_TYPES:
        return json.dumps(
            {
                "status": "error",
                "code": "UNSUPPORTED_SUBAGENT_TASK_TYPE",
                "message": f"子 agent 仅支持固定模式: {', '.join(sorted(ALLOWED_SUBAGENT_TASK_TYPES))}",
            },
            ensure_ascii=False,
        )
    if normalized_task_type == "diagnose" and (normalized_constraints or {}).get("readonly"):
        fast_result = _fast_diagnose_conversation_log(goal or task, normalized_scope)
    if fast_result:
        return json.dumps(fast_result, ensure_ascii=False)
    max_steps = 0
    try:
        max_steps = int((normalized_constraints or {}).get("max_steps") or 0)
    except (TypeError, ValueError):
        max_steps = 0

    if not task and not goal:
        return json.dumps(
            {"status": "error", "code": "MISSING_TASK", "message": "任务描述不能为空"},
            ensure_ascii=False,
        )

    depth = _get_recursion_depth()
    if depth >= _MAX_RECURSION_DEPTH:
        return json.dumps(
            {
                "status": "error",
                "code": "MAX_RECURSION",
                "message": "子 agent 不允许继续派发子 agent；请回到主 agent 收束。",
            },
            ensure_ascii=False,
        )

    agent_path = Path(__file__).parent.parent / "agent.py"
    if not agent_path.exists():
        return json.dumps(
            {
                "status": "error",
                "code": "AGENT_NOT_FOUND",
                "message": f"找不到 agent.py: {agent_path}",
            },
            ensure_ascii=False,
        )

    prompt = _build_subagent_prompt(
        task=task,
        task_type=normalized_task_type,
        goal=goal,
        scope=normalized_scope,
        constraints=normalized_constraints,
        deliverables=normalized_deliverables,
        context_pack=normalized_context_pack,
    )

    env = os.environ.copy()
    env["VIBELUTION_SUBAGENT_DEPTH"] = str(depth + 1)
    env["VIBELUTION_SUBAGENT_MODE"] = "readonly"
    env["PYTHONUNBUFFERED"] = "1"
    try:
        from core.logging.unified_logger import logger as unified_logger

        conversation = unified_logger.conversation
        parent_session_id = str(getattr(conversation, "_session_id", "") or "").strip()
        if parent_session_id:
            env["VIBELUTION_LOG_SESSION_ID"] = parent_session_id
            env["VIBELUTION_LOG_ACTOR"] = "subagent"
            env["VIBELUTION_LOG_PARENT_TURN"] = str(getattr(conversation, "_turn_count", 0) or 0)
            env["VIBELUTION_LOG_ACTOR_LABEL"] = (task_type or "inspect").strip() or "inspect"
    except Exception:
        pass

    try:
        process = subprocess.Popen(
            [
                sys.executable,
                "-u",
                str(agent_path),
                "--prompt",
                prompt,
                "--auto",
                "--skip-doctor",
                "--single-turn",
                "--subagent-json",
                *([ "--max-iterations", str(max_steps) ] if max_steps > 0 else []),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            cwd=str(agent_path.parent),
            env=env,
            **_subagent_process_group_kwargs(),
        )
    except Exception as e:
        return json.dumps(
            {
                "status": "error",
                "code": "SPAWN_FAILED",
                "message": f"无法启动子 Agent: {type(e).__name__}: {e}",
            },
            ensure_ascii=False,
        )

    output_queue: queue.Queue[tuple[str, Optional[str]]] = queue.Queue()
    stdout_parts: List[str] = []
    stderr_parts: List[str] = []
    stdout_console_parts: List[str] = []
    marker_seen = False

    def _reader(stream_name: str, pipe) -> None:
        try:
            while True:
                chunk = pipe.readline()
                if chunk == "":
                    break
                output_queue.put((stream_name, chunk))
        finally:
            try:
                pipe.close()
            except Exception:
                pass
            output_queue.put((stream_name, None))

    stdout_thread = threading.Thread(target=_reader, args=("stdout", process.stdout), daemon=True)
    stderr_thread = threading.Thread(target=_reader, args=("stderr", process.stderr), daemon=True)
    stdout_thread.start()
    stderr_thread.start()

    finished_streams = set()
    deadline = time.monotonic() + max(int(timeout), 1)
    timed_out = False
    cancelled_reason = ""

    while len(finished_streams) < 2:
        if callable(_cancel_checker):
            try:
                cancelled_reason = str(_cancel_checker() or "").strip()
            except Exception:
                cancelled_reason = ""
            if cancelled_reason:
                _terminate_process_tree(process)
                break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            timed_out = True
            _terminate_process_tree(process)
            break
        try:
            stream_name, chunk = output_queue.get(timeout=min(0.2, max(remaining, 0.01)))
        except queue.Empty:
            if process.poll() is not None and not stdout_thread.is_alive() and not stderr_thread.is_alive():
                break
            continue

        if chunk is None:
            finished_streams.add(stream_name)
            continue

        if stream_name == "stdout":
            visible = chunk
            if not marker_seen and _SUBAGENT_MARKER in visible:
                before, _sep, after = visible.partition(_SUBAGENT_MARKER)
                marker_seen = True
                visible = before
                stdout_parts.append(before + _SUBAGENT_MARKER + after)
            else:
                stdout_parts.append(chunk)
            if marker_seen and _SUBAGENT_MARKER not in chunk:
                visible = ""
            if visible:
                stdout_console_parts.append(visible)
                _emit_stream_event("stdout", visible.rstrip("\r\n"))
        else:
            stderr_parts.append(chunk)
            _emit_stream_event("stderr", chunk.rstrip("\r\n"))

    if cancelled_reason:
        stdout = "".join(stdout_parts).strip()
        stderr = "".join(stderr_parts).strip()
        process_output = "".join(stdout_console_parts).strip()
        raw_output = process_output
        if stderr:
            raw_output = (raw_output + f"\n\n[stderr]\n{stderr}").strip()
        try:
            process.wait(timeout=5)
        except Exception:
            _terminate_process_tree(process)
        return json.dumps(
            {
                "status": "cancelled",
                "task_type": task_type or "inspect",
                "goal": goal or task[:100],
                "summary": "子 Agent 已随停止请求终止。",
                "message": "子 Agent 已随停止请求终止。",
                "stop_reason": cancelled_reason,
                "scope_touched": normalized_scope,
                "raw_output": raw_output[:8000],
                "process_output": process_output[:8000],
            },
            ensure_ascii=False,
        )

    if timed_out:
        stdout = "".join(stdout_parts).strip()
        stderr = "".join(stderr_parts).strip()
        process_output = "".join(stdout_console_parts).strip()
        raw_output = process_output
        if stderr:
            raw_output = (raw_output + f"\n\n[stderr]\n{stderr}").strip()
        return json.dumps(
            {
                "status": "timeout",
                "task_type": task_type or "inspect",
                "goal": goal or task[:100],
                "summary": f"子 Agent 执行超时 ({timeout}s)",
                "message": f"子 Agent 执行超时 ({timeout}s)",
                "scope_touched": normalized_scope,
                "raw_output": raw_output[:8000],
                "process_output": process_output[:8000],
            },
            ensure_ascii=False,
        )

    try:
        returncode = process.wait(timeout=5)
    except Exception:
        _terminate_process_tree(process)
        returncode = process.wait(timeout=5)

    payload = _extract_structured_result(
        stdout="".join(stdout_parts),
        stderr="".join(stderr_parts),
        exit_code=returncode,
        task_type=task_type,
        goal=goal or task,
        scope=normalized_scope,
    )
    payload["depth"] = depth + 1
    return json.dumps(payload, ensure_ascii=False)
