#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
安全模块测试

测试 core/security.py 中的：
- 命令白名单验证
- 路径沙箱限制
- 参数安全检查
"""

import os
import sys
import pytest
from pathlib import Path

from core.infrastructure.security import (
    SecurityValidator,
    PathSandbox,
    get_security_validator,
    validate_shell_command,
    validate_file_path,
    SAFE_POWERSHELL_COMMANDS,
    FORBIDDEN_COMMANDS,
)

# 动态获取项目根目录（避免硬编码路径）
_PROJECT_ROOT = str(Path(__file__).parent.parent)


# ============================================================================
# PathSandbox 测试
# ============================================================================

class TestPathSandbox:
    """路径沙箱测试"""

    @pytest.fixture
    def sandbox(self):
        """创建测试用的沙箱实例"""
        project_root = _PROJECT_ROOT
        return PathSandbox(project_root)

    def test_init(self, sandbox):
        """测试初始化"""
        assert sandbox.project_root is not None
        assert len(sandbox._allowed_dirs) >= 1

    def test_is_within_project_valid(self, sandbox):
        """测试合法路径"""
        valid_paths = [
            _PROJECT_ROOT + "\\agent.py",
            _PROJECT_ROOT + "\\core\\security.py",
            _PROJECT_ROOT + "\\tools\\shell_tools.py",
            _PROJECT_ROOT + "\\workspace\\memory\\test.json",
        ]
        for path in valid_paths:
            assert sandbox.is_within_project(path) is True, f"路径应该在项目内：{path}"

    def test_is_within_project_invalid(self, sandbox):
        """测试非法路径"""
        invalid_paths = [
            "C:\\Windows\\System32\\cmd.exe",
            "C:\\Program Files\\Python\\python.exe",
            "C:\\Users\\Public\\Documents\\other_project\\file.txt",
            "D:\\Some\\Other\\Drive\\file.txt",
        ]
        for path in invalid_paths:
            assert sandbox.is_within_project(path) is False, f"路径应该在项目外：{path}"

    def test_path_traversal_attack(self, sandbox):
        """测试路径遍历攻击防护"""
        attack_paths = [
            _PROJECT_ROOT + "\\..\\..\\Windows\\system32",
            _PROJECT_ROOT + "\\..\\..\\..\\..\\Windows",
            "..\\..\\Windows\\system32",
        ]
        for path in attack_paths:
            is_valid, error = sandbox.validate_path(path)
            assert is_valid is False, f"应该阻止路径遍历：{path}"
            assert "路径遍历" in error or "超出项目沙箱" in error

    def test_validate_path_empty(self, sandbox):
        """测试空路径"""
        is_valid, error = sandbox.validate_path("")
        assert is_valid is False
        assert "路径不能为空" in error

    def test_safe_join(self, sandbox):
        """测试安全路径连接"""
        base = _PROJECT_ROOT
        
        # 合法连接
        safe_path, error = sandbox.safe_join(base, "core", "security.py")
        assert safe_path is not None
        assert "security.py" in safe_path
        assert error == ""

        # 非法连接（包含 ..）
        unsafe_path, error = sandbox.safe_join(base, "..", "Windows", "system32")
        assert unsafe_path is None
        assert error != ""


# ============================================================================
# SecurityValidator 测试
# ============================================================================

class TestSecurityValidator:
    """安全验证器测试"""

    @pytest.fixture
    def validator(self):
        """创建测试用的验证器实例"""
        project_root = _PROJECT_ROOT
        return SecurityValidator(project_root)

    def test_init(self, validator):
        """测试初始化"""
        assert validator.path_sandbox is not None

    def test_validate_command_empty(self, validator):
        """测试空命令"""
        is_safe, error = validator.validate_command("")
        assert is_safe is False
        assert "命令不能为空" in error

    def test_validate_command_forbidden(self, validator):
        """测试黑名单命令"""
        forbidden_commands = [
            "format C:",
            "fdisk",
            "sudo rm -rf /",
            "netcat 192.168.1.1 8080",
            "nmap -sS 192.168.1.1",
        ]
        for cmd in forbidden_commands:
            is_safe, error = validator.validate_command(cmd)
            assert is_safe is False, f"应该阻止命令：{cmd}"

    def test_validate_command_allows_common_pipes_and_command_chains(self, validator):
        """放宽模式下，常见 pipe / command chain 应允许通过。"""
        allowed_commands = [
            "Get-Content file.txt | Select-Object -First 20",
            "git diff --stat | head -20",
            "cd workspace && dir",
        ]
        for cmd in allowed_commands:
            is_safe, error = validator.validate_command(cmd)
            assert is_safe is True, f"应允许命令：{cmd} | {error}"

    def test_validate_command_allows_parentheses_inside_quoted_git_message(self, validator):
        """提交信息中的括号不应被误判为注入。"""
        cmd = 'git commit -m "feat(prompt): add language awareness section"'
        is_safe, error = validator.validate_command(cmd)
        assert is_safe is True, f"带括号的 commit message 应被允许: {error}"

    def test_validate_command_allows_safe_git_subcommands(self, validator):
        """常用只读/可控 Git 子命令应被允许。"""
        for cmd in ["git status", "git diff --stat", 'git commit -m "feat(prompt): ok"', "git add core/infrastructure/security.py"]:
            is_safe, error = validator.validate_command(cmd)
            assert is_safe is True, f"应允许 Git 子命令: {cmd} | {error}"

    def test_validate_command_allows_function_name_inside_quoted_git_message(self, validator):
        """提交正文中的函数名括号位于引号内时应允许。"""
        cmd = 'git commit -m "What: add make_language_awareness_section() to prompt manager"'
        is_safe, error = validator.validate_command(cmd)
        assert is_safe is True, f"引号内函数名括号应被允许: {error}"

    def test_validate_command_allows_semicolon_inside_quoted_git_message(self, validator):
        """提交信息中的分号位于引号内时不应误判。"""
        cmd = 'git commit -m "fix(prompt): keep Chinese; reduce English drift"'
        is_safe, error = validator.validate_command(cmd)
        assert is_safe is True, f"引号内分号应被允许: {error}"

    def test_validate_command_allows_powershell_subexpression_in_relaxed_mode(self, validator):
        """放宽模式下，PowerShell 子表达式不再因语法特征被拦截。"""
        cmd = "Write-Host $(Get-Date)"
        is_safe, error = validator.validate_command(cmd)
        assert is_safe is True, error

    def test_validate_command_blocks_forbidden_git_subcommands(self, validator):
        """破坏性或高风险 Git 子命令应被拦截。"""
        for cmd in ["git reset --hard", "git clean -fdx", "git push origin main"]:
            is_safe, error = validator.validate_command(cmd)
            assert is_safe is False, f"应阻止 Git 子命令: {cmd}"
            assert "Git 子命令" in error

    def test_validate_command_whitelist_allowed(self, validator):
        """测试白名单允许的命令"""
        allowed_commands = [
            f"Get-Content {_PROJECT_ROOT}\\agent.py",
            f"Set-Content {_PROJECT_ROOT}\\test.txt -Value 'hello'",
            f"Get-ChildItem {_PROJECT_ROOT}",
            f"python {_PROJECT_ROOT}\\agent.py",
            "git status",
            "pytest tests/",
            "Select-String -Pattern 'test' -Path file.txt",
        ]
        for cmd in allowed_commands:
            is_safe, error = validator.validate_command(cmd)
            assert is_safe is True, f"应该允许命令：{cmd}"

    def test_validate_command_relaxed_mode_allows_unknown_non_blacklisted_commands(self, validator):
        """放宽模式下，未知但非黑名单命令默认允许。"""
        commands = [
            "Invoke-Expression 'echo ok'",
            "Start-Process notepad.exe",
            "New-Object System.Text.StringBuilder",
        ]
        for cmd in commands:
            is_safe, error = validator.validate_command(cmd)
            assert is_safe is True, f"应该允许命令：{cmd} | {error}"


# ============================================================================
# 文件操作安全测试
# ============================================================================

class TestFileOperationSecurity:
    """文件操作安全测试"""

    @pytest.fixture
    def validator(self):
        project_root = _PROJECT_ROOT
        return SecurityValidator(project_root)

    def test_validate_file_read(self, validator):
        """测试文件读取"""
        is_safe, error = validator.validate_file_operation(
            "read",
            _PROJECT_ROOT + "\\agent.py"
        )
        assert is_safe is True

    def test_validate_file_write_forbidden_ext(self, validator):
        """测试禁止的文件扩展名"""
        forbidden_extensions = [
            _PROJECT_ROOT + "\\malware.exe",
            _PROJECT_ROOT + "\\script.bat",
            _PROJECT_ROOT + "\\payload.dll",
        ]
        for path in forbidden_extensions:
            is_safe, error = validator.validate_file_operation("write", path)
            assert is_safe is False, f"应该阻止 {path}"
            assert "禁止操作" in error

    def test_validate_file_dangerous_content(self, validator):
        """测试危险内容检测"""
        dangerous_contents = [
            "os.system('malicious command')",
            "subprocess.run('cmd', shell=True)",
            "eval('malicious code')",
            "exec('malicious code')",
            "__import__('os').system('rm -rf /')",
        ]
        for content in dangerous_contents:
            is_safe, error = validator.validate_file_operation(
                "write",
                _PROJECT_ROOT + "\\test.py",
                content
            )
            assert is_safe is False, f"应该阻止危险内容：{content}"
            assert "危险代码" in error


# ============================================================================
# 便捷函数测试
# ============================================================================

class TestConvenienceFunctions:
    """便捷函数测试"""

    def test_validate_shell_command(self):
        """测试 validate_shell_command 函数"""
        # 合法命令（需要完整路径）
        is_safe, error = validate_shell_command(
            f"Get-ChildItem {_PROJECT_ROOT}"
        )
        assert is_safe is True, f"应该允许 Get-ChildItem: {error}"

        # 非法命令
        is_safe, error = validate_shell_command("format C:")
        assert is_safe is False, f"应该阻止 format: {error}"

    def test_validate_file_path(self):
        """测试 validate_file_path 函数"""
        # 合法路径
        is_valid, error = validate_file_path(
            _PROJECT_ROOT + "\\agent.py"
        )
        assert is_valid is True

        # 非法路径
        is_valid, error = validate_file_path("C:\\Windows\\system32")
        assert is_valid is False


# ============================================================================
# 集成测试
# ============================================================================

class TestIntegration:
    """集成测试"""

    def test_full_workflow(self):
        """测试完整工作流程"""
        # 1. 创建验证器
        validator = get_security_validator(
            _PROJECT_ROOT
        )

        # 2. 验证命令
        is_safe, error = validator.validate_command(
            f"Get-Content {_PROJECT_ROOT}\\agent.py"
        )
        assert is_safe is True

        # 3. 验证路径
        is_valid, error = validator.path_sandbox.validate_path(
            _PROJECT_ROOT + "\\core\\security.py"
        )
        assert is_valid is True

        # 4. 验证文件操作
        is_safe, error = validator.validate_file_operation(
            "read",
            _PROJECT_ROOT + "\\README.md"
        )
        assert is_safe is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
