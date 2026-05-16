#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
安全模块 - 白名单机制与路径沙箱

提供：
- 命令白名单验证
- 路径沙箱限制
- 参数安全检查
"""

from __future__ import annotations

import os
import re
import shlex
from pathlib import Path
from typing import List, Set, Optional, Tuple
from dataclasses import dataclass


# ============================================================================
# 命令白名单配置
# ============================================================================

@dataclass
class CommandPattern:
    """命令模式定义"""
    pattern: str
    description: str
    allow_args: bool = True
    max_args: int = 5


# 安全的 PowerShell 命令白名单
SAFE_POWERSHELL_COMMANDS: List[CommandPattern] = [
    # 文件操作
    CommandPattern(r"^Get-Content\s+.+$", "读取文件内容"),
    CommandPattern(r"^Set-Content\s+.+$", "写入文件内容"),
    CommandPattern(r"^Add-Content\s+.+$", "追加文件内容"),
    CommandPattern(r"^Copy-Item\s+.+$", "复制文件/目录"),
    CommandPattern(r"^Move-Item\s+.+$", "移动文件/目录"),
    CommandPattern(r"^Remove-Item\s+.+$", "删除文件/目录"),
    CommandPattern(r"^New-Item\s+.+$", "创建文件/目录"),
    CommandPattern(r"^Test-Path\s+.+$", "检查路径存在"),
    CommandPattern(r"^Get-ChildItem\s*.+$", "列出目录内容"),
    
    # 系统信息
    CommandPattern(r"^Get-Process\s*.+$", "获取进程信息"),
    CommandPattern(r"^Get-Service\s*.+$", "获取服务信息"),
    CommandPattern(r"^Get-EventLog\s*.+$", "获取事件日志"),
    CommandPattern(r"^Get-Location$", "获取当前路径"),
    CommandPattern(r"^Set-Location\s+.+$", "切换路径"),
    CommandPattern(r"^pwd$", "打印当前路径"),
    CommandPattern(r"^dir$", "列出目录"),
    CommandPattern(r"^ls$", "列出目录"),
    
    # 文本处理
    CommandPattern(r"^Select-String\s+.+$", "搜索文本内容"),
    CommandPattern(r"^Measure-Object\s+.+$", "统计对象数量"),
    CommandPattern(r"^Sort-Object\s+.+$", "排序对象"),
    CommandPattern(r"^Where-Object\s+.+$", "过滤对象"),
    CommandPattern(r"^ForEach-Object\s+.+$", "遍历对象"),
    
    # 网络（受限）
    CommandPattern(r"^Invoke-WebRequest\s+-Uri\s+https?://.+$", "HTTP 请求（仅 GET）"),
    CommandPattern(r"^Test-Connection\s+.+$", "Ping 测试"),
    
    # Python 相关
    CommandPattern(r"^python\s+.+$", "执行 Python 脚本"),
    CommandPattern(r"^python3\s+.+$", "执行 Python3 脚本"),
    CommandPattern(r"^pip\s+.+$", "pip 包管理"),
    CommandPattern(r"^pip3\s+.+$", "pip3 包管理"),
    
    # Git 相关
    CommandPattern(r"^git\s+.+$", "Git 版本控制"),
    
    # 测试相关
    CommandPattern(r"^pytest\s+.+$", "运行 pytest 测试"),
    CommandPattern(r"^python\s+-m\s+pytest\s+.+$", "运行 pytest 测试"),
]

# 明确禁止的命令黑名单（即使符合白名单模式也禁止）
FORBIDDEN_COMMANDS: Set[str] = {
    # 系统破坏
    "format", "fdisk", "diskpart", "cipher",
    # 权限提升
    "runas", "sudo", "elevate",
    # 网络攻击
    "netcat", "nc", "nmap", "telnet",
    # 数据泄露
    "curl.*-d", "wget.*--post",
    # 进程注入
    "inject", "hook", "patch",
}

FORBIDDEN_GIT_SUBCOMMANDS: Set[str] = {
    "reset", "clean", "rebase", "push", "pull", "fetch", "checkout", "switch",
    "restore", "cherry-pick", "merge", "stash", "tag", "rm",
}


PROJECT_ROOT = Path(__file__).resolve().parents[2]


# ============================================================================
# 路径沙箱
# ============================================================================

class PathSandbox:
    """
    路径沙箱验证器
    
    限制所有文件操作只能在项目目录内进行。
    """

    def __init__(self, project_root: str):
        """
        初始化路径沙箱

        Args:
            project_root: 项目根目录路径
        """
        self.project_root = Path(project_root).resolve()
        self._allowed_dirs: Set[Path] = {self.project_root}

    def add_allowed_directory(self, dir_path: str):
        """添加允许的目录（项目目录的子目录）"""
        resolved = Path(dir_path).resolve()
        if self.is_within_project(resolved):
            self._allowed_dirs.add(resolved)

    def is_within_project(self, path: str) -> bool:
        """
        检查路径是否在项目目录内

        Args:
            path: 要检查的路径

        Returns:
            True: 路径安全，False: 路径超出沙箱
        """
        try:
            resolved = Path(path).resolve()
            # 检查是否在项目根目录内
            return self.project_root in resolved.parents or resolved == self.project_root
        except (OSError, ValueError):
            return False

    def validate_path(self, path: str, operation: str = "access") -> Tuple[bool, str]:
        """
        验证路径访问权限

        Args:
            path: 要验证的路径
            operation: 操作类型 (read, write, execute, delete)

        Returns:
            (is_valid, error_message)
        """
        if not path:
            return (False, "路径不能为空")

        # 检查是否包含路径遍历攻击
        if ".." in path:
            return (False, "禁止使用路径遍历 (..)")

        # 检查是否在沙箱内
        if not self.is_within_project(path):
            return (False, f"路径超出项目沙箱范围：{path}")

        # 特殊目录保护
        protected_dirs = {
            "C:\\Windows",
            "C:\\Program Files",
            "C:\\Program Files (x86)",
            "C:\\Users\\Public",
        }
        try:
            resolved = Path(path).resolve()
            for protected in protected_dirs:
                if protected in str(resolved):
                    return (False, f"禁止访问系统目录：{protected}")
        except (OSError, ValueError):
            return (False, "路径解析失败")

        return (True, "")

    def safe_join(self, base_path: str, *paths: str) -> Tuple[Optional[str], str]:
        """
        安全地连接路径

        Args:
            base_path: 基础路径
            *paths: 要连接的路径片段

        Returns:
            (safe_path, error_message)
        """
        try:
            result = Path(base_path).resolve()
            for p in paths:
                # 检查路径遍历攻击
                if ".." in p:
                    return (None, "禁止使用路径遍历 (..)")
                # 移除绝对路径前缀，防止绕过
                p_clean = p.lstrip("\\/")
                result = result / p_clean

            # 验证最终路径
            is_valid, error = self.validate_path(str(result))
            if not is_valid:
                return (None, error)

            return (str(result), "")
        except Exception as e:
            return (None, f"路径连接失败：{e}")


# ============================================================================
# 安全验证器
# ============================================================================

class SecurityValidator:
    """
    安全验证器
    
    提供命令和参数的综合安全检查。
    """

    def __init__(self, project_root: str):
        self.path_sandbox = PathSandbox(project_root)
        self._command_cache: dict = {}

    def validate_command(self, command: str, shell_type: str = "powershell") -> Tuple[bool, str]:
        """
        验证命令是否安全

        Args:
            command: 要执行的命令
            shell_type: shell 类型 (powershell, cmd, bash)

        Returns:
            (is_safe, error_message)
        """
        # 检查空命令
        if not command or not command.strip():
            return (False, "命令不能为空")

        # 检查黑名单
        for forbidden in FORBIDDEN_COMMANDS:
            if re.search(rf"\b{re.escape(forbidden)}\b", command, re.IGNORECASE):
                return (False, f"禁止使用命令：{forbidden}")

        command_family = self._detect_command_family(command)
        if command_family == "git":
            return self._validate_git_command(command)

        # 默认采用黑名单模式：只拦明显危险命令，其余命令允许通过。
        return (True, "允许：黑名单模式已通过")

    def _contains_unquoted_token(self, command: str, token: str) -> bool:
        """检查 token 是否出现在引号外部。"""
        in_single = False
        in_double = False
        i = 0
        token_len = len(token)

        while i < len(command):
            ch = command[i]
            prev = command[i - 1] if i > 0 else ""

            if ch == "'" and not in_double and prev != "`":
                in_single = not in_single
                i += 1
                continue

            if ch == '"' and not in_single and prev != "`":
                in_double = not in_double
                i += 1
                continue

            if not in_single and not in_double and command[i:i + token_len] == token:
                return True

            i += 1

        return False

    def _detect_command_family(self, command: str) -> str:
        """检测命令族。"""
        try:
            parts = shlex.split(command, posix=False)
        except ValueError:
            return "unknown"
        if not parts:
            return "unknown"
        head = parts[0].strip().lower()
        return head

    def _validate_git_command(self, command: str) -> Tuple[bool, str]:
        """Git 命令专项校验。"""
        try:
            parts = shlex.split(command, posix=False)
        except ValueError as e:
            return (False, f"Git 命令解析失败：{e}")

        if len(parts) < 2:
            return (False, "Git 命令缺少子命令")

        subcommand = parts[1].strip().lower()
        if subcommand in FORBIDDEN_GIT_SUBCOMMANDS:
            return (False, f"禁止使用 Git 子命令：{subcommand}")

        return (True, f"允许：Git {subcommand}")

    def validate_file_operation(
        self,
        operation: str,
        file_path: str,
        content: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        验证文件操作是否安全

        Args:
            operation: 操作类型 (read, write, create, delete)
            file_path: 文件路径
            content: 文件内容（写操作时）

        Returns:
            (is_safe, error_message)
        """
        # 验证路径
        is_valid, error = self.path_sandbox.validate_path(file_path, operation)
        if not is_valid:
            return (False, error)

        # 检查文件扩展名黑名单
        forbidden_extensions = {".exe", ".dll", ".bat", ".cmd", ".com", ".scr", ".ps1"}
        file_ext = Path(file_path).suffix.lower()
        if file_ext in forbidden_extensions:
            return (False, f"禁止操作 {file_ext} 文件")

        # 写操作内容检查
        if operation in ("write", "create") and content:
            if self._contains_dangerous_content(content):
                return (False, "文件内容包含危险代码")

        return (True, "")

    def _contains_dangerous_content(self, content: str) -> bool:
        """检查文件内容是否包含危险代码"""
        dangerous_patterns = [
            r"os\.system\s*\(",
            r"subprocess\..*shell\s*=\s*True",
            r"eval\s*\(",
            r"exec\s*\(",
            r"__import__\s*\(",
            r"import\s+os\b",
            r"import\s+subprocess\b",
        ]

        for pattern in dangerous_patterns:
            if re.search(pattern, content, re.IGNORECASE):
                return True

        return False


# ============================================================================
# 全局安全实例
# ============================================================================

_security_validator: Optional[SecurityValidator] = None


def get_security_validator(project_root: Optional[str] = None) -> SecurityValidator:
    """获取全局安全验证器实例"""
    global _security_validator
    
    if _security_validator is None:
        if project_root is None:
            project_root = str(PROJECT_ROOT)
        _security_validator = SecurityValidator(project_root)
    
    return _security_validator


def validate_shell_command(command: str, shell_type: str = "powershell") -> Tuple[bool, str]:
    """便捷函数：验证 shell 命令"""
    validator = get_security_validator()
    return validator.validate_command(command, shell_type)


def validate_file_path(file_path: str) -> Tuple[bool, str]:
    """便捷函数：验证文件路径是否在允许范围内"""
    validator = get_security_validator()
    return validator.path_sandbox.validate_path(file_path)
