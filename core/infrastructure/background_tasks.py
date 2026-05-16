#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
后台任务管理系统

提供：
- BackgroundTaskManager: 线程池后台任务执行
- 任务状态追踪（running/completed/failed/cancelled）
- 线程安全的注册表
"""

from __future__ import annotations

import os
import sys
import json
import uuid
import time
import threading
import subprocess
from pathlib import Path
from typing import Dict, Optional, Any
from concurrent.futures import ThreadPoolExecutor, Future


class BackgroundTaskManager:
    """后台任务管理器 — 基于 ThreadPoolExecutor"""

    def __init__(self, max_workers: int = 4):
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._tasks: Dict[str, dict] = {}
        self._lock = threading.Lock()

    def _execute_task(self, task_id: str, command: str, timeout: int):
        """在线程中执行命令并捕获输出"""
        try:
            # Windows 兼容策略：
            # - 默认使用 shell=False（避免 Windows cmd 不识别 Unix 命令如 head）
            # - 仅当命令包含 shell 特殊字符（|, >, <, &, &&, ||, $() 等）时启用 shell
            needs_shell = any(c in command for c in ('|', '>', '<', '&', '$', '`'))
            result = subprocess.run(
                command,
                shell=needs_shell,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=os.getcwd(),
            )
            with self._lock:
                if task_id in self._tasks:
                    self._tasks[task_id]["status"] = "completed"
                    self._tasks[task_id]["exit_code"] = result.returncode
                    self._tasks[task_id]["output"] = result.stdout
                    self._tasks[task_id]["stderr"] = result.stderr
                    self._tasks[task_id]["end_time"] = time.time()
        except subprocess.TimeoutExpired:
            with self._lock:
                if task_id in self._tasks:
                    self._tasks[task_id]["status"] = "failed"
                    self._tasks[task_id]["output"] = f"[超时] 任务执行超过 {timeout} 秒"
                    self._tasks[task_id]["end_time"] = time.time()
        except Exception as e:
            with self._lock:
                if task_id in self._tasks:
                    self._tasks[task_id]["status"] = "failed"
                    self._tasks[task_id]["output"] = f"[错误] {type(e).__name__}: {e}"
                    self._tasks[task_id]["end_time"] = time.time()

    def start_task(self, command: str, timeout: int = 300) -> str:
        """
        启动后台任务

        Args:
            command: 要执行的 Shell 命令
            timeout: 超时时间（秒），默认 300

        Returns:
            task_id 字符串
        """
        if not command or not command.strip():
            return json.dumps({"status": "error", "code": "MISSING_COMMAND", "message": "命令不能为空"})

        task_id = str(uuid.uuid4())[:8]

        with self._lock:
            self._tasks[task_id] = {
                "id": task_id,
                "command": command.strip(),
                "timeout": timeout,
                "status": "running",
                "start_time": time.time(),
                "end_time": None,
                "exit_code": None,
                "output": "",
                "stderr": "",
            }

        future = self._executor.submit(self._execute_task, task_id, command.strip(), timeout)
        self._tasks[task_id]["_future"] = future

        return json.dumps({
            "status": "started",
            "task_id": task_id,
            "command": command.strip(),
            "timeout": timeout,
            "message": f"后台任务已启动，使用 task_output_tool('{task_id}') 获取结果",
        }, ensure_ascii=False)

    def get_task_output(self, task_id: str) -> str:
        """
        获取后台任务输出/状态

        Args:
            task_id: 任务 ID

        Returns:
            任务状态和输出
        """
        with self._lock:
            task = self._tasks.get(task_id)

        if task is None:
            return json.dumps({"status": "error", "code": "NOT_FOUND", "message": f"任务不存在: {task_id}"}, ensure_ascii=False)

        elapsed = time.time() - task["start_time"]
        result = {
            "task_id": task_id,
            "command": task["command"],
            "status": task["status"],
            "elapsed_seconds": round(elapsed, 1),
            "exit_code": task.get("exit_code"),
        }

        if task["status"] == "running":
            result["message"] = f"任务仍在执行中 (已运行 {elapsed:.0f}s)"
        elif task["status"] == "completed":
            result["output"] = task.get("output", "")
            if task.get("stderr"):
                result["stderr"] = task["stderr"]
        elif task["status"] == "cancelled":
            result["message"] = "任务已被取消"
        elif task["status"] == "failed":
            result["output"] = task.get("output", "未知错误")

        return json.dumps(result, ensure_ascii=False)

    def stop_task(self, task_id: str) -> str:
        """
        停止后台任务

        Args:
            task_id: 任务 ID

        Returns:
            操作结果
        """
        with self._lock:
            task = self._tasks.get(task_id)

        if task is None:
            return json.dumps({"status": "error", "code": "NOT_FOUND", "message": f"任务不存在: {task_id}"}, ensure_ascii=False)

        if task["status"] != "running":
            return json.dumps({"status": "error", "code": "NOT_RUNNING", "message": f"任务已结束 (状态: {task['status']})"}, ensure_ascii=False)

        future = task.get("_future")
        if future and not future.done():
            cancelled = future.cancel()
            with self._lock:
                self._tasks[task_id]["status"] = "cancelled"
                self._tasks[task_id]["end_time"] = time.time()
            return json.dumps({"status": "cancelled", "task_id": task_id, "message": "任务已取消"}, ensure_ascii=False)
        else:
            return json.dumps({"status": "error", "code": "ALREADY_DONE", "message": "任务已完成，无法取消"}, ensure_ascii=False)

    def list_tasks(self) -> str:
        """列出所有后台任务"""
        with self._lock:
            tasks = list(self._tasks.values())

        if not tasks:
            return json.dumps({"status": "empty", "tasks": [], "message": "无后台任务"}, ensure_ascii=False)

        task_list = []
        for t in tasks:
            elapsed = time.time() - t["start_time"] if t.get("end_time") is None else t.get("end_time", 0) - t["start_time"]
            task_list.append({
                "id": t["id"],
                "command": t["command"][:80],
                "status": t["status"],
                "elapsed": f"{elapsed:.0f}s",
            })

        return json.dumps({"status": "ok", "count": len(task_list), "tasks": task_list}, ensure_ascii=False)


# 全局单例
_bg_task_manager: Optional[BackgroundTaskManager] = None


def get_background_task_manager() -> BackgroundTaskManager:
    """获取后台任务管理器单例"""
    global _bg_task_manager
    if _bg_task_manager is None:
        _bg_task_manager = BackgroundTaskManager()
    return _bg_task_manager
