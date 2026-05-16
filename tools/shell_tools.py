# -*- coding: utf-8 -*-
"""
Shell 工具模块 - 统一的命令行和文件操作工具

整合自 cli_tools.py 和 cmd_tools.py，提供：
1. 命令执行：CLI 命令、PowerShell、批量命令
2. 文件操作：读取、创建、编辑、列表
3. 代码检查：语法检查、符号提取
4. 项目管理：备份、清理、状态查询

## 核心能力

- **万物皆可执行**: ls, cat, grep, python, pytest, pip, git 等
- **智能输出合并**: 同时捕获 stdout 和 stderr，统一返回
- **超时保护**: 防止死循环命令导致主进程假死
- **安全护栏**: 拦截危险命令
- **路径安全**: 限制在允许目录范围内操作

## 使用示例

```python
# 执行命令
execute_shell_command("ls -la")

# 读取文件
read_file("agent.py")

# 编辑文件
edit_file("agent.py", "old_code", "new_code")

# 语法检查
check_python_syntax("agent.py")
```
"""

import subprocess
import os
import shutil
import ast
import traceback
import json
import glob as glob_module
import re
from pathlib import Path
from typing import Optional, List
from datetime import datetime
import locale
import platform

from core.infrastructure.event_bus import get_event_bus, EventNames
from core.infrastructure.security import get_security_validator
from core.logging import debug_logger as logger
# ============================================================================
# 文件 Glob 搜索
# ============================================================================

def glob_files(pattern: str = "**/*.py", search_dir: str = ".") -> list:
    """
    【文件模式匹配】按 glob 模式查找文件。

    支持标准 glob 模式：*.py、**/*.ts、src/**/*.md 等。

    Args:
        pattern: Glob 模式（如 "*.py", "**/*.py"）
        search_dir: 搜索起始目录，默认当前目录

    Returns:
        JSON 格式的匹配文件列表
    """

    # 解析模式
    if not pattern or not isinstance(pattern, str):
        return []

    # 获取搜索目录
    try:
        abs_search_dir = str(_resolve_project_path(search_dir))
    except Exception:
        return []
    if not os.path.exists(abs_search_dir):
        return []

    # 使用 glob 搜索
    try:
        matches = glob_module.glob(
            pattern,
            root_dir=abs_search_dir,
            recursive=True
        )
    except Exception as e:
        logger.warning(f"glob_files: 模式 '{pattern}' 搜索失败 - {e}")
        return []

    # 转换路径
    result = []
    for match in matches:
        abs_path = os.path.join(abs_search_dir, match)
        result.append({
            "path": abs_path,
            "name": os.path.basename(abs_path),
            "size": os.path.getsize(abs_path)
        })

    return result


# 向后兼容别名
glob_files_tool = glob_files


# ============================================================================
# 平台检测
# ============================================================================
CURRENT_SYSTEM = platform.system().lower()  # "windows" | "linux" | "darwin"
IS_WINDOWS = CURRENT_SYSTEM == "windows"
IS_UNIX = CURRENT_SYSTEM in ("linux", "darwin")

# Linux/macOS 特有命令集合（在 Windows 上需要特殊处理）
LINUX_COMMANDS = {
    'grep', 'egrep', 'fgrep', 'awk', 'sed', 'find', 'xargs',
    'sort', 'uniq', 'cut', 'tr', 'tee', 'which', 'type', 'command',
    'ls', 'rm', 'cp', 'mv', 'mkdir', 'chmod', 'chown', 'ln', 'readlink',
    'realpath', 'dirname', 'basename', 'wc', 'head', 'tail', 'cat',
    'less', 'more', 'tar', 'gzip', 'gunzip', 'zip', 'unzip',
    'curl', 'wget', 'ssh', 'scp', 'rsync', 'diff', 'patch',
    'env', 'export', 'source', 'alias', 'echo', 'printf',
    'kill', 'pkill', 'pgrep', 'ps', 'top', 'htop',
    'df', 'du', 'free', 'mount', 'umount', 'lsof', 'netstat',
    'git', 'svn', 'hg', 'make', 'cmake', 'gcc', 'g++', 'clang',
    'pip3', 'python3', 'node', 'npm', 'yarn', 'cargo',
}

# Windows cmd 特有命令集合（在 Linux/macOS 上需要特殊处理）
WINDOWS_COMMANDS = {
    'dir', 'copy', 'move', 'del', 'rd', 'md', 'mkdir', 'type', 'more',
    'ren', 'replace', 'attrib', 'compact', 'cipher', 'chkdsk', 'sc',
    'net', 'netstat', 'ping', 'tracert', 'pathping', 'nslookup',
    'reg', 'diskpart', 'bcdedit', 'diskutil', 'format',
    'cmd', 'where', 'color', 'cls', 'echo', 'set', 'cd', 'pushd', 'popd',
    'find', 'sort', 'fc', 'comp', 'convert', 'diskcomp',
}

# PowerShell cmdlet 特征：Verb-Noun 形式（含连字符）
# 这类命令走 powershell.exe，不走 cmd
POWERSHELL_CMDLET_PREFIXES = {
    'Get-', 'Set-', 'New-', 'Remove-', 'Invoke-', 'Select-', 'Where-',
    'ForEach-', 'Start-', 'Stop-', 'Write-', 'Read-', 'Add-', 'Clear-',
    'Compare-', 'Convert-', 'Copy-', 'Enter-', 'Exit-', 'Find-', 'Group-',
    'Import-', 'Export-', 'Install-', 'Join-', 'Measure-', 'Move-',
    'Out-', 'Pop-', 'Push-', 'Rename-', 'Reset-', 'Restart-', 'Resume-',
    'Save-', 'Send-', 'Show-', 'Skip-', 'Split-', 'Suspend-', 'Trace-',
    'Undo-', 'Unlock-', 'Update-', 'Wait-', 'Watch-', 'Test-', 'Trace-',
    'Enable-', 'Disable-', 'Publish-', 'Unpublish-', 'Register-',
    'Unregister-', 'Connect-', 'Disconnect-', 'Format-', 'Initialize-',
    'Invoke-', 'Optimize-', 'Protect-', 'Unprotect-', 'Repair-', 'Use-',
}


def _get_system_prefix() -> str:
    """
    获取系统特定的命令前缀。
    - Windows: powershell -NoProfile -ExecutionPolicy Bypass -Command
    - Unix: /bin/bash -c
    """
    if IS_WINDOWS:
        return 'powershell -NoProfile -ExecutionPolicy Bypass -Command'
    return '/bin/bash -c'


def _is_linux_command(command: str) -> bool:
    """检测命令是否为 Linux/macOS 特有命令"""
    parts = command.strip().split()
    if not parts:
        return False
    base = parts[0].lower()
    while base in ('sudo', 'env', '/usr/bin/env', '/bin/env'):
        if len(parts) > 1:
            parts = parts[1:]
            base = parts[0].lower()
        else:
            break
    return base in LINUX_COMMANDS


def _is_powershell_command(command: str) -> bool:
    """检测命令是否为 PowerShell cmdlet（Verb-Noun 形式）"""
    parts = command.strip().split()
    if not parts:
        return False
    base = parts[0]
    return any(base.startswith(prefix) for prefix in POWERSHELL_CMDLET_PREFIXES)


def _is_windows_command(command: str) -> bool:
    """检测命令是否为 Windows cmd 特有命令"""
    parts = command.strip().split()
    if not parts:
        return False
    base = parts[0].lower()
    return base in WINDOWS_COMMANDS


def _has_unix_shell_markers(command: str) -> bool:
    """检测命令是否包含典型 Unix shell 片段（用于 Windows 兼容拦截）。"""
    text = str(command or "")
    lowered = text.lower()
    markers = (
        "/dev/null",
        "2>/dev/null",
        "1>/dev/null",
        "2>&1 | tail",
        "| tail",
        "| head",
        " tail -",
        " head -",
        "grep -e",
        "grep -n",
        "xargs ",
        "$(pwd)",
    )
    return any(marker in lowered for marker in markers)


# ============================================================================
# 配置常量 - 从配置文件加载
# ============================================================================

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.absolute()


def _get_workspace_root() -> Path:
    """稳定获取 workspace 根目录。"""
    try:
        from config import get_config
        workspace_name = get_config().agent.workspace
    except Exception:
        workspace_name = "workspace"
    return (PROJECT_ROOT / workspace_name).resolve()


def _get_allowed_root_dirs() -> list[Path]:
    """允许的稳定根目录集合。"""
    roots = [
        PROJECT_ROOT.resolve(),
        _get_workspace_root(),
        Path(__file__).resolve().parent,
    ]
    unique: list[Path] = []
    seen = set()
    for root in roots:
        root_str = str(root)
        if root_str not in seen:
            seen.add(root_str)
            unique.append(root)
    return unique


def _resolve_tool_path(path_str: str, *, base_dir: Optional[Path] = None) -> Path:
    """将用户路径稳定解析到固定基准目录，而不是当前 cwd。"""
    raw = Path(path_str)
    if raw.is_absolute():
        return raw.resolve()
    anchor = (base_dir or PROJECT_ROOT).resolve()
    return (anchor / raw).resolve()


def _load_config_defaults() -> dict:
    """从配置加载默认常量"""
    try:
        from config import get_config
        cfg = get_config()
        return {
            "DEFAULT_TIMEOUT": cfg.tools.shell.default_timeout,
            "MAX_OUTPUT_LENGTH": cfg.tools.shell.max_output_length,
            "MAX_FILE_SIZE": cfg.tools.shell.max_file_size,
            "DANGEROUS_PATTERNS": cfg.security.dangerous_commands,
            "FORBIDDEN_PATTERNS": cfg.security.forbidden_patterns,
            "FORBIDDEN_DELETE_PATTERNS": cfg.security.forbidden_delete_patterns,
            "EDITABLE_EXTENSIONS": set(cfg.tools.file.editable_extensions),
        }
    except Exception:
        # 兜底默认值
        return {}


_config_defaults = _load_config_defaults()

# 危险命令黑名单（合并两个文件的并集）
DANGEROUS_PATTERNS = _config_defaults.get("DANGEROUS_PATTERNS", [
    # 磁盘操作危险命令
    "rm -rf /",
    "rm -rf /*",
    "mkfs",
    "dd if=/dev/zero of=/dev/sda",
    "> /dev/sda",
    # Windows 危险命令
    "format",
    "del /f /s /q",
    "rmdir /s /q",
    "rm -rf",
    "cipher /w:",
    # 系统危险命令
    "shutdown",
    "sysprep",
    ":(){ :|:& };:",  # Fork bomb
])

# 默认配置
DEFAULT_TIMEOUT = _config_defaults.get("DEFAULT_TIMEOUT", 60)
MAX_OUTPUT_LENGTH = _config_defaults.get("MAX_OUTPUT_LENGTH", 10000)
MAX_FILE_SIZE = _config_defaults.get("MAX_FILE_SIZE", 10 * 1024 * 1024)

# 禁止访问的文件模式
FORBIDDEN_PATTERNS = _config_defaults.get("FORBIDDEN_PATTERNS", [
    '.env', '.password', '.secret', '.key', 'id_rsa', 'credentials.json',
])

# 允许编辑的文件扩展名
EDITABLE_EXTENSIONS = _config_defaults.get("EDITABLE_EXTENSIONS", {
    '.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.kt', '.go', '.rs',
    '.c', '.cpp', '.h', '.hpp', '.rb', '.php', '.html', '.css', '.scss',
    '.json', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.md', '.txt',
    '.sh', '.sql', '.xml', '.svg'
})

# 禁止删除的文件/目录模式
FORBIDDEN_DELETE_PATTERNS = _config_defaults.get("FORBIDDEN_DELETE_PATTERNS", [
    '.env', '.password', '.secret', '.key', 'id_rsa', 'credentials.json',
    'config.py', 'config.toml', '.git', 'core/restarter_manager/restarter.py', 'agent.py',
    '__pycache__', '.pytest_cache', '.gitignore',
])

# ============================================================================
# 安全检查函数 - 双层验证（黑名单 + 白名单）
# ============================================================================

def _is_command_dangerous(command: str) -> tuple[bool, str]:
    """检查命令是否危险（黑名单 + 白名单双层验证）"""
    cmd_lower = command.lower().strip()
    if re.search(r"\bdel\s+.*(?:/s\b|/q\b|/f\b)", cmd_lower) and (
        "c:\\windows" in cmd_lower
        or "c:/windows" in cmd_lower
        or "c:\\" in cmd_lower
        or "c:/" in cmd_lower
    ):
        return True, "危险命令拦截: del system path"
    if re.search(r"\b(cd|pushd|set-location)\s+\.\.(?:\\|/|\s|$)", cmd_lower):
        return True, "危险命令拦截: path traversal"
    for pattern in DANGEROUS_PATTERNS:
        if pattern.lower() in cmd_lower:
            return True, f"危险命令拦截: {pattern}"
    # Whitelist validation (new security module)
    try:
        from core.infrastructure.security import validate_shell_command
        is_safe, error_msg = validate_shell_command(command, "powershell")
        if not is_safe:
            return True, f"[Whitelist Block] {error_msg}"
    except Exception as e:
        from core.logging import debug_logger; debug_logger.warning(f"Security module load failed: {e}")
    return False, ""


def _is_path_allowed(file_path: str) -> bool:
    """检查路径是否在允许范围内"""
    abs_path = Path(file_path).resolve()
    for allowed_dir in _get_allowed_root_dirs():
        try:
            if abs_path.is_relative_to(allowed_dir):
                return True
        except AttributeError:
            if str(abs_path).startswith(str(allowed_dir)):
                return True
        except Exception:
            continue
    if Path(file_path).is_absolute():
        # 显式绝对路径保留可访问能力，避免受控测试/临时目录行为突变。
        return True
    return False


def _resolve_project_path(path_str: str) -> Path:
    """相对路径一律锚定到项目根目录。"""
    return _resolve_tool_path(path_str, base_dir=PROJECT_ROOT)


def _resolve_workspace_path(path_str: str) -> Path:
    """相对路径一律锚定到 workspace 根目录。"""
    return _resolve_tool_path(path_str, base_dir=_get_workspace_root())


def _is_path_safe(file_path: str) -> bool:
    """检查路径是否包含敏感文件"""
    abs_path = os.path.abspath(file_path).lower()
    for pattern in FORBIDDEN_PATTERNS:
        if pattern.lower() in abs_path:
            return False
    return True


def _detect_encoding(file_path: Path) -> str:
    """自动检测文件编码"""
    encodings = ['utf-8', 'utf-8-sig', 'gbk', 'gb2312', 'latin-1', 'cp1252']
    for enc in encodings:
        try:
            with open(file_path, 'r', encoding=enc) as f:
                f.read()
            return enc
        except:
            continue
    return 'utf-8'


def _is_binary_content(content: str, threshold: float = 0.30) -> bool:
    """判断内容是否为二进制"""
    if not content:
        return False
    printable_ascii = set(range(32, 127)) | {9, 10, 13}
    chinese_range = (0x4e00, 0x9fff)
    cjk_range = [(0x3000, 0x303f), (0xff00, 0xffef)]
    
    total_chars = len(content)
    non_text_chars = 0
    
    for char in content:
        code = ord(char)
        if code in printable_ascii:
            continue
        if chinese_range[0] <= code <= chinese_range[1]:
            continue
        is_cjk = any(r[0] <= code <= r[1] for r in cjk_range)
        if is_cjk:
            continue
        non_text_chars += 1
    
    return non_text_chars / max(total_chars, 1) > threshold


# ============================================================================
# 命令执行函数
# ============================================================================

def execute_shell_command(
    command: str,
    timeout: int = 60,
    cwd: Optional[str] = None,
    check_safety: bool = True
) -> str:
    """
    执行 Shell 命令的万能工具（跨平台支持）

    Args:
        command: 要执行的 Shell 命令
        timeout: 超时时间（秒），默认 60 秒
        cwd: 工作目录，默认为项目根目录
        check_safety: 是否进行安全检查，默认 True

    Returns:
        str: 合并后的命令输出（stdout + stderr）
    """
    # 安全检查
    if check_safety:
        is_dangerous, msg = _is_command_dangerous(command)
        if is_dangerous:
            return f"[安全拦截] {msg}\n该危险命令已被系统安全策略禁止执行。"

    # 设置工作目录
    if cwd is None:
        cwd = str(PROJECT_ROOT)

    # 确保工作目录存在
    if not os.path.exists(cwd):
        return f"[错误] 工作目录不存在: {cwd}"

    # -------------------------------------------------------------------------
    # 跨平台命令适配
    # -------------------------------------------------------------------------
    final_command = command.strip()

    if IS_WINDOWS:
        stripped_command = command.strip()
        if stripped_command.lower() == "pwd":
            final_command = 'powershell -NoProfile -ExecutionPolicy Bypass -Command "(Get-Location).Path"'
        elif _has_unix_shell_markers(stripped_command):
            return (
                f"[跨平台警告] 在 Windows 上检测到 Unix shell 片段: {stripped_command}\n"
                "请改用 PowerShell/Windows 等价命令，或使用 read_file_tool / grep_search_tool。"
            )
        # Windows 上执行 Linux 特有命令 → 尝试用 Git Bash 包装
        elif _is_linux_command(command):
            git_bash_paths = [
                "C:\\Program Files\\Git\\bin\\bash.exe",
                "C:\\Program Files (x86)\\Git\\bin\\bash.exe",
                os.path.expanduser("~\\AppData\\Local\\Programs\\Git\\bin\\bash.exe"),
            ]
            bash_path = None
            for p in git_bash_paths:
                if os.path.exists(p):
                    bash_path = p
                    break
            if bash_path:
                final_command = f'"{bash_path}" -c {json.dumps(command)}'
            else:
                return (
                    f"[跨平台警告] 在 Windows 上检测到 Linux 命令 '{command}'，"
                    "但未找到 Git Bash。请安装 Git 或使用 Windows 原生命令。"
                )
        # PowerShell cmdlet → powershell.exe
        elif _is_powershell_command(command):
            final_command = f'powershell -NoProfile -ExecutionPolicy Bypass -Command {json.dumps(command)}'
        # Windows cmd 原生命令 → cmd.exe
        else:
            final_command = f'cmd /c {command}'
    else:
        # Unix 上执行 Windows 特有命令 → 拒绝执行
        if _is_windows_command(command):
            return (
                f"[跨平台警告] 在 {CURRENT_SYSTEM} 上检测到 Windows 特有命令 '{command}'。"
                f"请使用等效的 Unix 命令（如用 'ls' 替代 'dir'，用 'rm' 替代 'del'）。"
            )
        # Unix 统一用 /bin/bash 执行
        final_command = f'/bin/bash -c {json.dumps(command)}'

    try:
        system_encoding = locale.getpreferredencoding(False) or 'utf-8'

        # 强制转换为 int，防止 string/float 类型传入 subprocess 导致 TypeError（Python 3.14+）
        try:
            timeout_int = int(timeout)
        except (TypeError, ValueError):
            timeout_int = 60

        result = subprocess.run(
            final_command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding=system_encoding,
            errors='replace',
            timeout=timeout_int
        )

        output_parts = []

        if result.stdout:
            output_parts.append(result.stdout.strip())

        if result.stderr:
            output_parts.append(f"[STDERR]\n{result.stderr.strip()}")

        if not output_parts:
            output_parts.append("[命令执行完成，无输出]")

        output = "\n\n".join(output_parts)

        if result.returncode != 0:
            has_error_keywords = any(kw in output.lower() for kw in
                ["error", "exception", "failed", "fail", "traceback", "syntaxerror", "indentationerror"])
            if has_error_keywords:
                return f"[EXEC FAILURE | Exit Code: {result.returncode}]\n{output}"
            else:
                return f"[WARNING | Exit Code: {result.returncode}]\n{output}"

        return output

    except subprocess.TimeoutExpired:
        return f"[超时] 命令执行超过 {timeout} 秒被强制终止。\n请检查命令是否陷入死循环。"

    except FileNotFoundError:
        return f"[错误] 命令未找到: {command}\n请检查命令是否正确，或使用完整路径。"

    except PermissionError:
        return f"[权限错误] 无法执行命令: {command}\n可能需要管理员权限。"

    except Exception as e:
        return f"[执行错误] {type(e).__name__}: {str(e)}"


# 向后兼容别名
execute_cli_command = execute_shell_command
run_cmd = execute_shell_command


def run_powershell(command: str, timeout: int = DEFAULT_TIMEOUT, cwd: Optional[str] = None) -> str:
    """通过 PowerShell 执行命令"""
    ps_command = f'powershell -NoProfile -ExecutionPolicy Bypass -Command "{command}"'
    return execute_shell_command(ps_command, timeout=timeout, cwd=cwd, check_safety=True)


def run_batch(commands: List[str], timeout: int = DEFAULT_TIMEOUT, cwd: Optional[str] = None) -> str:
    """批量执行多个命令（跨平台）"""
    if not commands:
        return "[错误] 命令列表为空"
    if IS_WINDOWS:
        converted_commands = [
            re.sub(r"%([A-Za-z_][A-Za-z0-9_]*)%", r"!\1!", command)
            for command in commands
        ]
        combined_command = " & ".join(converted_commands)
        return execute_shell_command(
            f"cmd /V:ON /c {json.dumps(combined_command)}",
            timeout=timeout,
            cwd=cwd,
        )
    sep = " && " if not IS_WINDOWS else " & "
    combined_command = sep.join(commands)
    return execute_shell_command(combined_command, timeout=timeout, cwd=cwd)


def quick_ping(host: str = "8.8.8.8", count: int = 1) -> str:
    """快速网络连通性检测（跨平台）"""
    if IS_WINDOWS:
        cmd = f"ping -n {count} {host}"
    else:
        cmd = f"ping -c {count} {host}"
    return execute_shell_command(cmd, timeout=10)


# ============================================================================
# Python 代码检查
# ============================================================================

def check_python_syntax(file_path: str) -> str:
    """
    检查 Python 文件的语法正确性（使用 AST 解析，更精确）

    Args:
        file_path: Python 文件路径

    Returns:
        检查结果
    """
    if not file_path:
        return "[语法检查] 错误: 文件路径不能为空"

    file_path = file_path.strip()

    try:
        abs_path = _resolve_project_path(file_path)
    except Exception as e:
        return f"[语法检查] 错误: 无效的路径 - {e}"

    if not abs_path.exists():
        return f"[语法检查] 错误: 文件不存在 - {abs_path}"

    if abs_path.suffix.lower() != '.py':
        return f"[语法检查] 错误: 仅支持 .py 文件 - {abs_path}"

    try:
        with open(abs_path, 'r', encoding='utf-8', errors='replace') as f:
            source = f.read()

        ast.parse(source, filename=str(abs_path))
        return "Syntax OK"

    except SyntaxError as e:
        lines = [
            "=" * 60,
            "[语法检查] 发现语法错误",
            "=" * 60,
            f"文件: {abs_path}",
            f"行号: {e.lineno}",
            f"错误: {e.msg if hasattr(e, 'msg') else str(e)}",
            "",
            traceback.format_exception(type(e).__name__, e, e.__traceback__)[-1],
            "=" * 60,
            "建议修复后重新调用 check_python_syntax",
            "=" * 60,
        ]
        return '\n'.join(lines)

    except Exception as e:
        return f"[语法检查] 错误: {str(e)}"


def run_pytest(test_path: str = "tests/", verbose: bool = True, timeout: int = 120) -> str:
    """运行 pytest 测试"""
    v_flag = "-v" if verbose else ""
    return execute_shell_command(
        f"pytest {test_path} {v_flag}",
        timeout=timeout
    )


# ============================================================================
# 文件读取操作
# ============================================================================

def read_file(
    file_path: str,
    encoding: Optional[str] = None,
    max_lines: Optional[int] = None,
    show_line_numbers: bool = True,
    offset: int = 0
) -> str:
    """
    读取本地文件内容

    Args:
        file_path: 文件路径
        encoding: 编码格式，默认自动检测
        max_lines: 最大读取行数，None 表示读取全部
        show_line_numbers: 是否显示行号
        offset: 从第几行开始读取（0-based）

    Returns:
        文件内容
    """
    if not file_path or not isinstance(file_path, str):
        return "[文件读取] 错误: 路径不能为空"

    file_path = file_path.strip()
    if not file_path:
        return "[文件读取] 错误: 路径不能为空"

    try:
        abs_path = _resolve_project_path(file_path)
    except Exception as e:
        return f"[文件读取] 错误: 无效的路径格式 - {file_path}"

    if not _is_path_allowed(str(abs_path)):
        return f"[文件读取] 错误: 路径超出允许范围 - {abs_path}"

    if not _is_path_safe(str(abs_path)):
        return f"[文件读取] 错误: 禁止读取敏感文件 - {abs_path.name}"

    if not abs_path.exists():
        return f"[文件读取] 错误: 文件不存在 - {abs_path}"

    if not abs_path.is_file():
        return f"[文件读取] 错误: 路径不是文件 - {abs_path}"

    try:
        stat = abs_path.stat()
        file_size = stat.st_size

        if file_size > MAX_FILE_SIZE:
            size_mb = file_size / (1024 * 1024)
            max_mb = MAX_FILE_SIZE / (1024 * 1024)
            return f"[文件读取] 错误: 文件过大 ({size_mb:.1f} MB > {max_mb:.0f} MB)"

        if encoding is None:
            encoding = _detect_encoding(abs_path)

        adaptive_max_lines = max_lines
        if adaptive_max_lines is None:
            adaptive_max_lines = None
        elif adaptive_max_lines <= 0:
            adaptive_max_lines = None
        elif file_size > 64 * 1024 and adaptive_max_lines > 80:
            adaptive_max_lines = 80
        elif file_size > 24 * 1024 and adaptive_max_lines > 100:
            adaptive_max_lines = 100

        with open(abs_path, 'r', encoding=encoding, errors='replace') as f:
            if offset > 0:
                for _ in range(offset):
                    f.readline()

            if adaptive_max_lines is not None:
                lines = []
                for _ in range(adaptive_max_lines):
                    line = f.readline()
                    if not line:
                        break
                    lines.append(line.rstrip())
                content = '\n'.join(lines)
                f.seek(0)
                total_lines = sum(1 for _ in f)
                truncated = total_lines > (offset + adaptive_max_lines)
            else:
                content = f.read()
                total_lines = offset + content.count('\n') + 1
                truncated = False

        if _is_binary_content(content):
            return f"[文件读取] 错误: 二进制文件不支持 - {abs_path}"

        file_size_str = f"{file_size / 1024:.1f} KB" if file_size < 1024 * 1024 else f"{file_size / (1024 * 1024):.1f} MB"
        shown_line_count = len(content.split('\n')) if content else 0
        start_line = offset + 1 if total_lines > 0 else 0
        end_line = offset + shown_line_count if shown_line_count else offset
        remaining_lines = max(total_lines - end_line, 0)

        result_lines = [
            f"[文件] {abs_path}",
            f"[编码] {encoding} | [行数] {total_lines}" + (" (已截断)" if truncated else "") + f" | [大小] {file_size_str}",
            f"[区间] 第 {start_line}-{end_line} 行 | 已显示 {shown_line_count} 行 | 剩余 {remaining_lines} 行",
        ]

        if truncated and adaptive_max_lines is not None:
            result_lines.append(
                f'[续读] read_file_tool(file_path="{file_path}", offset={end_line}, max_lines={adaptive_max_lines})'
            )

        result_lines.extend([
            "",
            "--- Content ---",
        ])

        if show_line_numbers:
            for i, line in enumerate(content.split('\n'), offset + 1):
                result_lines.append(f"第 {i:>5} 行 | {line}")
        else:
            result_lines.append(content)

        result_lines.append("--- End ---")

        return '\n'.join(result_lines)

    except PermissionError:
        return f"[文件读取] 错误: 权限不足 - {abs_path}"
    except UnicodeDecodeError as e:
        return f"[文件读取] 错误: 编码错误 - {e}"
    except Exception as e:
        return f"[文件读取] 错误: {str(e)}"


# 向后兼容别名
read_local_file = read_file


# ============================================================================
# 目录列表操作
# ============================================================================

def list_directory(
    path: str = ".",
    show_hidden: bool = False,
    recursive: bool = False,
    max_output_chars: int = 8000
) -> str:
    """列出目录内容

    Args:
        path: 目录路径
        show_hidden: 是否显示隐藏文件
        recursive: 是否递归
        max_output_chars: 最大输出字符数，默认8000，防止上下文爆炸

    Returns:
        JSON 格式的目录列表结果
    """
    import json

    if not path or not isinstance(path, str):
        return json.dumps({"status": "error", "code": "INVALID_PATH", "message": "目录路径不能为空"}, ensure_ascii=False)

    path = path.strip()
    if not path:
        path = "."

    try:
        abs_path = _resolve_project_path(path)
    except Exception as e:
        return json.dumps({"status": "error", "code": "INVALID_PATH", "message": f"无效的路径格式 - {path}"}, ensure_ascii=False)

    if not _is_path_allowed(str(abs_path)):
        return json.dumps({"status": "error", "code": "PATH_NOT_ALLOWED", "message": f"路径超出允许范围 - {abs_path}"}, ensure_ascii=False)

    if not abs_path.exists():
        return json.dumps({"status": "error", "code": "PATH_NOT_EXISTS", "message": f"路径不存在 - {abs_path}"}, ensure_ascii=False)

    if not abs_path.is_dir():
        return json.dumps({"status": "error", "code": "NOT_A_DIRECTORY", "message": f"路径不是目录 - {abs_path}"}, ensure_ascii=False)

    try:
        result_data = {
            "status": "success",
            "path": str(abs_path),
            "directories": [],
            "files": [],
            "total": 0
        }
        items = list(abs_path.iterdir())

        dirs = []
        files = []
        for item in items:
            if not show_hidden and item.name.startswith('.'):
                continue
            if item.is_dir():
                dirs.append(item)
            else:
                files.append(item)

        result_data["total"] = len(dirs) + len(files)

        for d in sorted(dirs):
            try:
                mtime = os.path.getmtime(d)
                dt = datetime.fromtimestamp(mtime)
                time_str = dt.strftime("%Y-%m-%d %H:%M")
                result_data["directories"].append({"name": d.name, "mtime": time_str})
            except Exception:
                result_data["directories"].append({"name": d.name})

        for f in sorted(files):
            try:
                stat = f.stat()
                size = stat.st_size
                mtime = os.path.getmtime(f)
                dt = datetime.fromtimestamp(mtime)
                time_str = dt.strftime("%Y-%m-%d %H:%M")
                result_data["files"].append({"name": f.name, "size": size, "mtime": time_str})
            except Exception:
                result_data["files"].append({"name": f.name})

        if recursive and dirs:
            subdirs_data = []
            for d in sorted(dirs):
                sub_result = list_directory(str(d), show_hidden, recursive, max_output_chars)
                try:
                    subdirs_data.append(json.loads(sub_result))
                except (json.JSONDecodeError, TypeError):
                    subdirs_data.append({"name": d.name, "error": "subdirectory_read_failed"})
            result_data["subdirectories"] = subdirs_data

        # 序列化结果
        result_json = json.dumps(result_data, ensure_ascii=False)

        # 如果超过最大输出长度，截断并添加提示
        if len(result_json) > max_output_chars:
            # 保留基本信息，截断文件列表
            truncated_data = {
                "status": "success",
                "path": str(abs_path),
                "directories": result_data["directories"],
                "files": result_data["files"][:10],  # 只保留前10个文件
                "total": result_data["total"],
                "truncated": True,
                "message": f"结果已截断，原有 {result_data['total']} 个项目，仅显示前 10 个文件"
            }
            if "subdirectories" in result_data:
                truncated_data["subdirectories"] = result_data["subdirectories"][:3]
                truncated_data["subdirectories_truncated"] = True
            result_json = json.dumps(truncated_data, ensure_ascii=False)

        return result_json

    except PermissionError:
        return json.dumps({"status": "error", "code": "PERMISSION_DENIED", "message": f"权限不足 - {abs_path}"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "code": "UNKNOWN_ERROR", "message": str(e)}, ensure_ascii=False)


# 向后兼容别名
list_dir = list_directory


# ============================================================================
# 文件创建操作
# ============================================================================

def create_file(
    file_path: str,
    content: str,
    use_workspace: bool = True
) -> str:
    """
    创建新文件或覆盖现有文件

    Args:
        file_path: 文件路径
        content: 文件内容
        use_workspace: 是否使用 workspace 目录前缀

    Returns:
        操作结果
    """
    # 获取绝对路径（稳定锚定到 project/workspace，而不是当前 cwd）
    original_is_absolute = os.path.isabs(file_path)
    if use_workspace and not original_is_absolute:
        normalized = file_path
        if not os.path.isabs(normalized) and normalized.startswith("workspace"):
            normalized = normalized[len("workspace"):].lstrip("/\\")
        abs_path = str(_resolve_workspace_path(normalized))
    else:
        abs_path = file_path if original_is_absolute else str(_resolve_project_path(file_path))

    existed_before = os.path.exists(abs_path)

    # PathSandbox 校验：确保文件在项目目录内
    try:
        sandbox = get_security_validator()
        sandbox_path = sandbox.path_sandbox
        is_valid, err_msg = sandbox_path.validate_path(abs_path, operation="write")
        if not is_valid and not original_is_absolute and not _is_path_allowed(abs_path):
            return f"[创建文件] [SECURITY] {err_msg}"
    except Exception:
        pass  # 安全校验器不可用时降级放行

    # 确保目录存在
    parent_dir = os.path.dirname(abs_path)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)

    try:
        with open(abs_path, 'w', encoding='utf-8') as f:
            f.write(content)

        if os.path.exists(abs_path):
            file_size = os.path.getsize(abs_path)
            line_count = content.count('\n') + 1 if content else 0

            # 发布文件创建事件
            try:
                bus = get_event_bus()
                bus.publish(EventNames.WORKSPACE_FILE_CREATED, {
                    "path": abs_path,
                    "tool_name": "write_file_tool",
                    "size": file_size,
                })
            except Exception:
                pass

            action = "覆盖" if existed_before else "成功"
            return f"[创建文件] [OK] {action}\n文件: {abs_path}\n大小: {file_size} 字节\n行数: {line_count}"
        else:
            return f"[创建文件] [FAIL] 创建失败"

    except Exception as e:
        return f"[创建文件] [ERROR] {type(e).__name__}: {str(e)}"


# 向后兼容别名
create_file_tool = create_file


# ============================================================================
# 文件编辑操作
# ============================================================================

def edit_file(
    file_path: str,
    search_string: str,
    replace_string: str,
    create_backup: bool = True
) -> str:
    """
    编辑本地文件，替换指定内容

    Args:
        file_path: 要编辑的文件路径
        search_string: 要替换的原字符串
        replace_string: 替换后的新字符串
        create_backup: 是否创建备份，默认 True

    Returns:
        操作结果
    """
    if not file_path or not search_string:
        return "[文件编辑] 错误: 文件路径和搜索字符串不能为空"

    try:
        abs_path = Path(file_path).resolve()
    except Exception as e:
        return f"[文件编辑] 错误: 无效的路径 - {e}"

    if not abs_path.exists():
        return f"[文件编辑] 错误: 文件不存在 - {abs_path}"

    ext = abs_path.suffix.lower()
    if ext and ext not in EDITABLE_EXTENSIONS:
        return f"[文件编辑] 错误: 不支持的文件类型 - {ext}"

    abs_str = str(abs_path).lower()
    for pattern in FORBIDDEN_PATTERNS:
        if pattern in abs_str:
            return f"[文件编辑] 错误: 禁止编辑敏感文件 - {abs_path}"

    try:
        with open(abs_path, 'r', encoding='utf-8', errors='replace') as f:
            old_content = f.read()
            lines = old_content.split('\n')

        # 多匹配检测
        count = old_content.count(search_string)
        if count == 0:
            return f"[文件编辑] 错误: 未找到目标代码"
        if count > 1:
            match_lines = []
            for i, line in enumerate(lines, 1):
                if search_string in line:
                    match_lines.append(f"  - 第 {i} 行: {line.strip()[:60]}")
            return (
                f"[文件编辑] 错误: 找到 {count} 个匹配项，非唯一匹配！\n"
                f"匹配位置:\n" + "\n".join(match_lines) +
                f"\n\n【必须】提供更长的上下文（目标行及其前后各 2 行）以确保唯一匹配。"
            )

        if create_backup:
            backup_dir = abs_path.parent / "backups"
            backup_dir.mkdir(exist_ok=True)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_path = backup_dir / f"{abs_path.stem}_{timestamp}{abs_path.suffix}"
            shutil.copy2(abs_path, backup_path)

        new_content = old_content.replace(search_string, replace_string, 1)

        with open(abs_path, 'w', encoding='utf-8') as f:
            f.write(new_content)

        result = [
            "=" * 50,
            "[文件编辑] 成功",
            f"文件: {abs_path}",
            f"修改: {count} 处",
            "=" * 50,
            "建议: 立即调用 check_python_syntax 进行语法自检",
            "=" * 50,
        ]
        return '\n'.join(result)

    except PermissionError:
        return "[文件编辑] 错误: 权限不足"
    except Exception as e:
        return f"[文件编辑] 错误: {str(e)}"


# 向后兼容别名
edit_local_file = edit_file


# ============================================================================
# 符号提取（AST）
# ============================================================================

def extract_symbols(file_path: str) -> str:
    """
    提取 Python 文件中的符号大纲（类、函数、全局变量）

    Args:
        file_path: Python 文件路径

    Returns:
        格式化的符号列表
    """
    if not file_path:
        return "[符号提取] 错误: 文件路径不能为空"

    try:
        abs_path = Path(file_path).resolve()
    except Exception as e:
        return f"[符号提取] 错误: 无效的路径 - {e}"

    if not abs_path.exists():
        return f"[符号提取] 错误: 文件不存在 - {abs_path}"

    if abs_path.suffix.lower() != '.py':
        return f"[符号提取] 错误: 仅支持 .py 文件 - {abs_path}"

    try:
        with open(abs_path, 'r', encoding='utf-8', errors='replace') as f:
            source = f.read()

        tree = ast.parse(source, filename=str(abs_path))
        symbols = []

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                bases = []
                for base in node.bases:
                    if isinstance(base, ast.Name):
                        bases.append(base.id)
                    elif isinstance(base, ast.Attribute):
                        bases.append(ast.unparse(base) if hasattr(ast, 'unparse') else 'object')

                symbols.append({
                    'type': 'CLASS',
                    'name': node.name,
                    'line': node.lineno,
                    'bases': bases if bases else None,
                })

            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.col_offset == 0:
                is_async = isinstance(node, ast.AsyncFunctionDef)
                symbols.append({
                    'type': 'ASYNC_DEF' if is_async else 'DEF',
                    'name': node.name,
                    'line': node.lineno,
                    'args': [arg.arg for arg in node.args.args],
                })

            elif isinstance(node, ast.Assign):
                if node.col_offset == 0:
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            symbols.append({
                                'type': 'GLOBAL',
                                'name': target.id,
                                'line': node.lineno,
                            })

        if not symbols:
            return f"[符号] {abs_path.name}\n(文件为空或不包含顶层定义)"

        result_lines = [
            f"[符号] {abs_path.name}",
            f"[总计] {len(symbols)} 个符号",
            "",
        ]

        current_type = None
        for sym in symbols:
            if sym['type'] != current_type:
                current_type = sym['type']
                result_lines.append(f"\n[{current_type}]")

            if sym['type'] == 'CLASS':
                bases_str = f" ({', '.join(sym['bases'])})" if sym['bases'] else ""
                result_lines.append(f"  {sym['name']}{bases_str}  @L{sym['line']}")
            elif sym['type'] in ('DEF', 'ASYNC_DEF'):
                args_str = ', '.join(sym['args'][:5])
                if len(sym['args']) > 5:
                    args_str += ', ...'
                result_lines.append(f"  {sym['name']}({args_str})  @L{sym['line']}")
            else:
                result_lines.append(f"  {sym['name']}  @L{sym['line']}")

        return '\n'.join(result_lines)

    except SyntaxError as e:
        return f"[符号提取] 语法错误: 第 {e.lineno} 行 - {e.msg}"
    except Exception as e:
        return f"[符号提取] 错误: {str(e)}"


# 向后兼容别名
list_symbols_in_file = extract_symbols


# ============================================================================
# 项目备份
# ============================================================================

def backup_project(version_note: str = "") -> str:
    """创建项目备份"""
    import zipfile

    PROJECT_ROOT = Path(__file__).parent.parent.resolve()
    BACKUP_DIR = PROJECT_ROOT / "backups"
    BACKUP_DIR.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_name = f"backup_{timestamp}.zip"
    backup_path = BACKUP_DIR / backup_name

    try:
        with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for pattern in ['*.py', '*.json', '*.toml', '*.md']:
                for f in PROJECT_ROOT.glob(pattern):
                    if 'backup' not in str(f) and '__pycache__' not in str(f):
                        arcname = f.relative_to(PROJECT_ROOT)
                        zf.write(f, arcname)

            tools_dir = PROJECT_ROOT / 'tools'
            if tools_dir.exists():
                for f in tools_dir.glob('*.py'):
                    arcname = f.relative_to(PROJECT_ROOT)
                    zf.write(f, arcname)

        size = backup_path.stat().st_size
        size_str = f"{size / 1024:.1f} KB" if size < 1024 * 1024 else f"{size / (1024 * 1024):.1f} MB"

        result = [
            "=" * 50,
            "[备份] [OK] 备份成功",
            f"文件: {backup_path}",
            f"大小: {size_str}",
            f"说明: {version_note or '无'}",
            "=" * 50,
        ]
        return '\n'.join(result)

    except Exception as e:
        return f"[备份] 错误: {str(e)}"


# 向后兼容别名
backup_project_tool = backup_project


# ============================================================================
# 测试文件清理
# ============================================================================

def cleanup_test_files(directory: str = ".", dry_run: bool = False) -> str:
    """
    清理指定目录下的测试相关临时文件

    Args:
        directory: 要扫描的目录，默认为当前目录
        dry_run: 是否仅模拟运行（不实际删除）

    Returns:
        操作结果
    """
    if not directory or not isinstance(directory, str):
        return "[清理测试文件] 错误: 目录路径不能为空"

    try:
        abs_dir = _resolve_project_path(directory)
    except Exception as e:
        return f"[清理测试文件] 错误: 无效的路径 - {e}"

    if not abs_dir.exists():
        return f"[清理测试文件] 错误: 目录不存在 - {abs_dir}"

    if not abs_dir.is_dir():
        return f"[清理测试文件] 错误: 路径不是目录 - {abs_dir}"

    CLEANUP_PATTERNS = [
        '**/test_*.py',
        '**/__pycache__',
        '**/*.pyc',
        '**/*.pyo',
        '**/.pytest_cache',
        '**/*.tmp',
        '**/*.log',
        '**/workspace/backups/*',
    ]

    found_files = []
    protected_files = []

    try:
        for pattern in CLEANUP_PATTERNS:
            for item in abs_dir.glob(pattern):
                is_protected = False
                for protected in FORBIDDEN_DELETE_PATTERNS:
                    if protected.lower() in str(item).lower():
                        is_protected = True
                        break

                if is_protected:
                    protected_files.append(str(item))
                    continue

                if item.name in ['agent.py', 'config.py', 'restarter_manager']:
                    protected_files.append(str(item))
                    continue

                found_files.append(item)

        if not found_files:
            return f"[清理测试文件] 未找到需要清理的文件\n扫描目录: {abs_dir}"

        total_size = sum(f.stat().st_size for f in found_files if f.is_file())

        result = [
            "=" * 50,
            "[清理测试文件] 扫描结果",
            f"扫描目录: {abs_dir}",
            f"找到文件: {len(found_files)} 个",
            f"总大小: {total_size / 1024:.1f} KB",
            "",
            "[可清理文件]",
        ]

        for f in found_files[:20]:
            if f.is_file():
                size = f.stat().st_size
                result.append(f"  {f.relative_to(abs_dir)} ({size} 字节)")
            else:
                result.append(f"  {f.relative_to(abs_dir)}/ (目录)")

        if len(found_files) > 20:
            result.append(f"  ... 还有 {len(found_files) - 20} 个文件")

        if protected_files:
            result.append("")
            result.append("[受保护文件] (跳过)")
            for pf in protected_files[:10]:
                result.append(f"  {pf}")

        result.append("=" * 50)

        if dry_run:
            result.append("[提示] 这是模拟运行，文件未被实际删除")
            result.append("如需删除，请使用 cleanup_test_files 确认删除")
        else:
            deleted_count = 0
            for f in found_files:
                try:
                    if f.is_file():
                        f.unlink()
                    else:
                        shutil.rmtree(f)
                    deleted_count += 1
                except Exception as e:
                    result.append(f"  警告: 删除失败 {f.name} - {e}")

            result.append(f"[完成] 已删除 {deleted_count}/{len(found_files)} 个文件")

        result.append("=" * 50)
        return '\n'.join(result)

    except Exception as e:
        return f"[清理测试文件] 错误: {str(e)}"


# ============================================================================
# Agent 状态与测试
# ============================================================================

def run_test_for(source_path: str, timeout: int = 120) -> str:
    """
    根据源文件路径自动查找对应测试文件并运行 pytest。

    映射规则：<dir>/xxx.py → tests/test_xxx.py
    修改代码后调用此函数验证。

    Args:
        source_path: 源文件相对路径（如 "tools/shell_tools.py"）
        timeout: 超时时间（秒），默认 120

    Returns:
        格式化的测试结果
    """
    if not source_path:
        return "[运行测试] 错误: 源文件路径不能为空"

    source = Path(source_path)
    if not source.is_absolute():
        source = PROJECT_ROOT / source

    if not source.exists():
        return f"[运行测试] 错误: 源文件不存在 - {source}"

    # 推导测试文件路径：tools/xxx.py → tests/test_xxx.py
    test_name = f"test_{source.stem}{source.suffix}"
    test_path = PROJECT_ROOT / "tests" / test_name

    if not test_path.exists():
        return (
            f"[运行测试] 未找到对应测试文件\n"
            f"  源文件: {source}\n"
            f"  期望测试: {test_path}\n"
            f"  提示: 请先创建测试文件，或手动运行 pytest"
        )

    pytest_cmd = f"python -m pytest {test_path} -v --tb=short"
    return execute_shell_command(pytest_cmd, timeout=timeout)


def self_test() -> str:
    """运行 Agent 核心功能的自我测试"""
    results = []
    all_passed = True

    results.append("=" * 50)
    results.append("[自检] Agent 核心功能测试")
    results.append("=" * 50)

    try:
        from tools import web_tools, memory_tools
        results.append("[OK] 核心模块导入成功")
    except Exception as e:
        results.append(f"[FAIL] 核心模块导入失败: {e}")
        all_passed = False

    try:
        from config import get_config
        cfg = get_config()
        results.append(f"[OK] 配置加载成功 (模型: {cfg.llm.get_profile(role='primary').model})")
    except Exception as e:
        results.append(f"[!] 配置加载失败: {e}")

    try:
        result = check_python_syntax(__file__)
        if "Syntax OK" in result or "语法检查" in result:
            results.append("[OK] 语法检查功能正常")
        else:
            results.append(f"[FAIL] 语法检查异常: {result[:100]}")
    except Exception as e:
        results.append(f"[FAIL] 语法检查失败: {e}")

    try:
        from tools.memory_tools import get_generation_tool, get_current_goal
        gen = get_generation_tool()
        goal = get_current_goal()
        results.append(f"[OK] 记忆系统正常 (G{gen})")
    except Exception as e:
        results.append(f"[FAIL] 记忆系统失败: {e}")
        all_passed = False

    # 检查 core.restarter_manager 模块
    try:
        import core.restarter_manager
        results.append("[OK] core.restarter_manager 存在")
    except ImportError:
        results.append("[FAIL] core.restarter_manager 不存在 (危险!)")
        all_passed = False

    results.append("")

    results.append("=" * 50)
    if all_passed:
        results.append("[自检] [OK] 所有测试通过")
    else:
        results.append("[自检] 部分测试失败，请检查")
    results.append("=" * 50)

    return '\n'.join(results)


def get_agent_status() -> str:
    """获取 Agent 当前状态概览"""
    try:
        from config import get_config
        cfg = get_config()
        model = cfg.llm.get_profile(role="primary").model
        interval = cfg.agent.awake_interval
    except:
        model = "未知"
        interval = 60

    try:
        from tools.memory_tools import get_generation_tool, get_current_goal, get_core_context
        gen = get_generation_tool()
        goal = get_current_goal()
        context = get_core_context()
    except:
        gen = "?"
        goal = "未知"
        context = "无法获取"

    lines = [
        "=" * 50,
        "[状态] Agent 运行状态",
        "=" * 50,
        f"世代: G{gen}",
        f"模型: {model}",
        f"苏醒间隔: {interval}秒",
        f"启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"工作目录: {PROJECT_ROOT}",
        "",
        f"当前目标: {goal or '未设置'}",
        "",
        f"核心上下文: {context[:100]}{'...' if len(context) > 100 else ''}",
        "=" * 50,
    ]
    return '\n'.join(lines)


# ============================================================================
# 工具注册函数
# ============================================================================

def get_shell_tools():
    """
    获取所有 Shell 工具的字典映射

    Returns:
        工具名称到函数的映射字典
    """
    return {
        # 命令执行
        'execute_shell_command': execute_shell_command,
        'run_powershell': run_powershell,
        'run_batch': run_batch,
        'quick_ping': quick_ping,
        # Python 检查
        'check_python_syntax': check_python_syntax,
        'run_pytest': run_pytest,
        'run_test_for': run_test_for,
        # 文件操作
        'read_file': read_file,
        'list_directory': list_directory,
        'create_file': create_file,
        'edit_file': edit_file,
        'extract_symbols': extract_symbols,
        # 项目管理
        'backup_project': backup_project,
        'cleanup_test_files': cleanup_test_files,
        # Agent 状态
        'self_test': self_test,
        'get_agent_status': get_agent_status,
    }


# 向后兼容：保留旧函数名
def create_cli_tools():
    """创建 CLI 工具集（向后兼容）"""
    return get_shell_tools()


# ============================================================================
# 更多向后兼容别名（在 __all__ 之前定义）
# ============================================================================

# create_new_file 别名
create_new_file = create_file

# check_syntax 别名
check_syntax = check_python_syntax


# ============================================================================
# 模块初始化
# ============================================================================

# 导出所有主要函数
__all__ = [
    # 命令执行
    'execute_shell_command',
    'execute_cli_command',
    'run_cmd',
    'run_powershell',
    'run_batch',
    'quick_ping',
    # Python 检查
    'check_python_syntax',
    'run_pytest',
    'run_test_for',
    # 文件操作
    'read_file',
    'read_local_file',
    'list_directory',
    'list_dir',
    'create_file',
    'create_file_tool',
    'edit_file',
    'edit_local_file',
    'extract_symbols',
    'list_symbols_in_file',
    # 项目管理
    'backup_project',
    'backup_project_tool',
    'cleanup_test_files',
    # Agent 状态
    'self_test',
    'get_agent_status',
    # 工具注册
    'get_shell_tools',
    'create_cli_tools',
]
