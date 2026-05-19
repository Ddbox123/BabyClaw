"""Low-level workbench lifecycle helpers used by the runtime manager."""

from __future__ import annotations

import json
import locale
import os
import subprocess
import tempfile
import urllib.error
import urllib.request
from typing import Any

from .constants import DEFAULT_HEALTH_URL, DEFAULT_URL, LAUNCHER_SCRIPT_PATH, LAUNCHER_STATE_PATH, PROJECT_ROOT


def _is_process_alive_windows(pid: int) -> bool:
    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_INFORMATION = 0x0400
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = None
    for access in (PROCESS_QUERY_LIMITED_INFORMATION, PROCESS_QUERY_INFORMATION):
        handle = kernel32.OpenProcess(access, False, int(pid))
        if handle:
            break
    if not handle:
        return False

    try:
        exit_code = wintypes.DWORD()
        if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)) == 0:
            return False
        return int(exit_code.value) == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _is_process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            return _is_process_alive_windows(int(pid))
        except OSError:
            return False
    try:
        os.kill(int(pid), 0)
    except OSError:
        return False
    return True


def _load_launcher_state() -> dict[str, Any]:
    if not LAUNCHER_STATE_PATH.exists():
        return {}
    try:
        payload = json.loads(LAUNCHER_STATE_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _health_url_for(url: str) -> str:
    normalized = str(url or DEFAULT_URL).rstrip("/")
    return f"{normalized}/api/health"


def _is_backend_healthy(url: str) -> bool:
    try:
        with urllib.request.urlopen(_health_url_for(url), timeout=2.0) as response:
            return int(getattr(response, "status", 0) or 0) == 200
    except (urllib.error.URLError, TimeoutError, ValueError):
        return False


def observe_workbench() -> dict[str, Any]:
    launcher_state = _load_launcher_state()
    url = str(launcher_state.get("url") or DEFAULT_URL).strip() or DEFAULT_URL
    backend_pid = int(launcher_state.get("backendPid") or 0)
    browser_launch_pid = int(launcher_state.get("browserLaunchPid") or 0)
    browser_window_pid = int(launcher_state.get("browserWindowPid") or 0)
    browser_managed = bool(launcher_state.get("browserManaged", True))

    backend_alive = _is_process_alive(backend_pid)
    health_probe_url = url if launcher_state else DEFAULT_URL
    healthy = _is_backend_healthy(health_probe_url)
    browser_window_alive = _is_process_alive(browser_window_pid)
    if not healthy:
        observed_state = "closed"
    elif not launcher_state:
        observed_state = "open"
    elif not browser_managed:
        observed_state = "open"
    elif browser_window_alive:
        observed_state = "open"
    else:
        observed_state = "closed"

    return {
        "launcherStatePresent": bool(launcher_state),
        "sessionId": str(launcher_state.get("sessionId") or "").strip(),
        "backendPid": backend_pid,
        "browserLaunchPid": browser_launch_pid,
        "browserWindowPid": browser_window_pid,
        "browserManaged": browser_managed,
        "url": url,
        "healthUrl": _health_url_for(health_probe_url),
        "backendAlive": backend_alive,
        "backendHealthy": healthy,
        "browserWindowAlive": browser_window_alive,
        "observedState": observed_state,
    }


def _creation_flags() -> int:
    flags = 0
    for name in ("CREATE_NO_WINDOW",):
        flags |= int(getattr(subprocess, name, 0))
    return flags


def _read_capture_file(path: str) -> str:
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError:
        return ""
    encoding = locale.getpreferredencoding(False) or "utf-8"
    return raw.decode(encoding, errors="replace")


def run_launcher_action(action: str, *, no_browser: bool = False) -> subprocess.CompletedProcess[str]:
    args = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(LAUNCHER_SCRIPT_PATH),
        "-Action",
        str(action),
    ]
    if no_browser:
        args.append("-NoBrowser")
    stdout_fd, stdout_path = tempfile.mkstemp(prefix="vibelution-launcher-stdout-", suffix=".log")
    stderr_fd, stderr_path = tempfile.mkstemp(prefix="vibelution-launcher-stderr-", suffix=".log")
    try:
        with os.fdopen(stdout_fd, "w+b") as stdout_handle, os.fdopen(stderr_fd, "w+b") as stderr_handle:
            result = subprocess.run(
                args,
                cwd=str(PROJECT_ROOT),
                stdin=subprocess.DEVNULL,
                stdout=stdout_handle,
                stderr=stderr_handle,
                creationflags=_creation_flags(),
                check=False,
            )
        return subprocess.CompletedProcess(
            args=result.args,
            returncode=result.returncode,
            stdout=_read_capture_file(stdout_path),
            stderr=_read_capture_file(stderr_path),
        )
    finally:
        for capture_path in (stdout_path, stderr_path):
            try:
                os.remove(capture_path)
            except OSError:
                pass


def open_workbench(*, no_browser: bool = False) -> subprocess.CompletedProcess[str]:
    return run_launcher_action("internal-start", no_browser=no_browser)


def close_workbench() -> subprocess.CompletedProcess[str]:
    return run_launcher_action("internal-stop")


def restart_workbench(*, no_browser: bool = False) -> subprocess.CompletedProcess[str]:
    result = run_launcher_action("internal-restart", no_browser=no_browser)
    return result
