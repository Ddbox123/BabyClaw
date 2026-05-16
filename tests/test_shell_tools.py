#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Shell 工具完整测试套件

测试 tools/shell_tools.py 中的所有核心功能。
"""

import os
import sys
import pytest
import time
import tempfile
import shutil
from unittest.mock import patch
from pathlib import Path
from datetime import datetime

import tools.shell_tools as shell_tools_module
from tools.shell_tools import (
    read_file, list_directory, create_file, edit_file,
    check_python_syntax, execute_shell_command, run_powershell,
    run_batch, get_agent_status, backup_project, cleanup_test_files,
    extract_symbols, self_test,
)


# ============================================================================
# 测试辅助函数
# ============================================================================

@pytest.fixture
def temp_test_dir():
    """创建临时测试目录"""
    temp_dir = tempfile.mkdtemp(prefix="xueba_test_")
    yield temp_dir
    # 清理
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)


@pytest.fixture
def sample_py_file(temp_test_dir):
    """创建示例 Python 文件"""
    file_path = os.path.join(temp_test_dir, "sample.py")
    content = '''#!/usr/bin/env python3
"""示例文件"""

class SampleClass:
    """示例类"""
    
    def __init__(self, name):
        self.name = name
    
    def greet(self):
        """打招呼"""
        return f"Hello, {self.name}!"

def helper_function(x, y):
    """辅助函数"""
    return x + y

SAMPLE_VAR = "test"
'''
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    return file_path


@pytest.fixture
def sample_txt_file(temp_test_dir):
    """创建示例文本文件"""
    file_path = os.path.join(temp_test_dir, "sample.txt")
    content = "这是第一行\n这是第二行\n这是第三行\n"
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    return file_path


# ============================================================================
# read_file 测试
# ============================================================================

class TestReadFile:
    """read_file 工具测试"""

    def test_read_existing_file(self, sample_txt_file):
        """测试读取存在的文件"""
        result = read_file(file_path=sample_txt_file)
        assert "第一行" in result
        assert "第二行" in result
        assert "第三行" in result
        assert "[区间]" in result

    def test_read_nonexistent_file(self):
        """读取不存在的文件应返回错误"""
        result = read_file(file_path="nonexistent_xyz_12345.txt")
        assert "错误" in result or "不存在" in result
        assert "nonexistent_xyz_12345.txt" in result

    def test_read_with_encoding(self, temp_test_dir):
        """测试读取不同编码文件"""
        # 创建 GBK 编码文件
        file_path = os.path.join(temp_test_dir, "gbk_file.txt")
        with open(file_path, 'w', encoding='gbk') as f:
            f.write("中文内容")
        
        result = read_file(file_path=file_path)
        assert "中文内容" in result

    def test_read_empty_file(self, temp_test_dir):
        """测试读取空文件"""
        file_path = os.path.join(temp_test_dir, "empty.txt")
        with open(file_path, 'w') as f:
            f.write("")
        
        result = read_file(file_path=file_path)
        # 空文件仍然返回格式化信息，但内容为空
        assert "[文件]" in result
        assert "--- End ---" in result

    def test_read_binary_file(self, temp_test_dir):
        """测试读取二进制文件（应自动处理）"""
        file_path = os.path.join(temp_test_dir, "binary.bin")
        with open(file_path, 'wb') as f:
            f.write(b'\x00\x01\x02\x03')
        
        # 应该能读取，但可能显示为乱码或编码错误
        result = read_file(file_path=file_path)
        assert isinstance(result, str)

    def test_read_file_returns_continuation_hint_when_paginated(self, temp_test_dir):
        file_path = os.path.join(temp_test_dir, "paged.txt")
        with open(file_path, "w", encoding="utf-8") as f:
            for i in range(1, 11):
                f.write(f"第{i}行\n")

        result = read_file(file_path=file_path, max_lines=3, offset=0)

        assert "[区间] 第 1-3 行" in result
        assert "[续读]" in result
        assert "offset=3" in result

    def test_read_file_adapts_page_size_for_large_file(self, temp_test_dir):
        file_path = os.path.join(temp_test_dir, "large.txt")
        with open(file_path, "w", encoding="utf-8") as f:
            for i in range(1, 6000):
                f.write(f"{i:04d} " + ("x" * 20) + "\n")

        result = read_file(file_path=file_path, max_lines=120, offset=0)

        assert "[续读]" in result
        assert "max_lines=80" in result


# ============================================================================
# list_directory 测试
# ============================================================================

class TestListDirectory:
    """list_directory 工具测试"""

    def test_list_current_dir(self):
        """测试列出当前目录"""
        result = list_directory(path=".")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_list_project_root(self):
        """测试列出项目根目录"""
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        result = list_directory(path=project_root)
        assert isinstance(result, str)
        assert "tools" in result or "core" in result or "agent.py" in result

    def test_list_with_pattern(self, temp_test_dir):
        """测试带模式匹配的目录列表"""
        # 创建不同类型文件
        open(os.path.join(temp_test_dir, "a.txt"), 'w').close()
        open(os.path.join(temp_test_dir, "b.txt"), 'w').close()
        open(os.path.join(temp_test_dir, "c.py"), 'w').close()
        
        result = list_directory(path=temp_test_dir)
        assert "a.txt" in result
        assert "b.txt" in result
        assert "c.py" in result

    def test_list_recursive(self, temp_test_dir):
        """测试递归列出目录"""
        subdir = os.path.join(temp_test_dir, "subdir")
        os.makedirs(subdir)
        open(os.path.join(subdir, "file.txt"), 'w').close()
        
        result = list_directory(path=temp_test_dir, recursive=True)
        assert "subdir" in result
        assert "file.txt" in result

    def test_list_nonexistent_dir(self):
        """列出不存在的目录应返回错误"""
        result = list_directory(path="/nonexistent/path/xyz")
        assert "错误" in result or "不存在" in result

    def test_list_as_file(self, temp_test_dir):
        """将文件作为目录列出应返回错误"""
        file_path = os.path.join(temp_test_dir, "file.txt")
        with open(file_path, 'w') as f:
            f.write("test")
        
        result = list_directory(path=file_path)
        assert "错误" in result or "不是目录" in result

    def test_list_relative_path_is_anchored_to_project_root(self, monkeypatch, temp_test_dir):
        """相对路径解析不应跟随 cwd 漂移"""
        monkeypatch.chdir(temp_test_dir)

        result = list_directory(path=".")

        monkeypatch.chdir(shell_tools_module.PROJECT_ROOT)
        assert str(shell_tools_module.PROJECT_ROOT).replace("\\", "\\\\") in result


# ============================================================================
# create_file 测试
# ============================================================================

class TestCreateFile:
    """create_file 工具测试"""

    def test_create_new_file(self, temp_test_dir):
        """测试创建新文件"""
        file_path = os.path.join(temp_test_dir, "new_file.txt")
        content = "测试内容\n第二行"
        
        result = create_file(file_path=file_path, content=content)
        # 返回值包含文件信息和成功标记
        assert ("成功" in result or "[OK]" in result or "created" in result.lower())
        assert os.path.exists(file_path)
        
        with open(file_path, 'r', encoding='utf-8') as f:
            saved = f.read()
        assert saved == content

    def test_overwrite_existing_file(self, temp_test_dir):
        """测试覆盖现有文件"""
        file_path = os.path.join(temp_test_dir, "existing.txt")
        with open(file_path, 'w') as f:
            f.write("旧内容")
        
        result = create_file(file_path=file_path, content="新内容")
        assert "覆盖" in result or "overwritten" in result.lower()
        
        with open(file_path, 'r') as f:
            saved = f.read()
        assert saved == "新内容"

    def test_create_file_with_unicode(self, temp_test_dir):
        """测试创建包含 Unicode 的文件"""
        file_path = os.path.join(temp_test_dir, "unicode.txt")
        content = "中文内容 🎉 Emoji 😀"
        
        create_file(file_path=file_path, content=content)
        
        with open(file_path, 'r', encoding='utf-8') as f:
            saved = f.read()
        assert saved == content

    def test_create_file_in_nested_dir(self, temp_test_dir):
        """测试在嵌套目录中创建文件（自动创建目录）"""
        nested_path = os.path.join(temp_test_dir, "a", "b", "c.txt")
        content = "嵌套目录"
        
        result = create_file(file_path=nested_path, content=content)
        assert os.path.exists(nested_path)

    def test_create_file_without_content(self, temp_test_dir):
        """测试创建空文件"""
        file_path = os.path.join(temp_test_dir, "empty.txt")
        
        result = create_file(file_path=file_path, content="")
        assert os.path.exists(file_path)
        
        with open(file_path, 'r') as f:
            assert f.read() == ""

    def test_create_file_relative_path_uses_project_workspace_not_cwd(self, monkeypatch, tmp_path):
        """默认创建相对路径时应落在项目 workspace，而不是当前 cwd"""
        fake_root = tmp_path / "project"
        fake_root.mkdir()
        fake_workspace = fake_root / "workspace"
        fake_workspace.mkdir()
        outside_cwd = tmp_path / "outside"
        outside_cwd.mkdir()

        monkeypatch.setattr(shell_tools_module, "PROJECT_ROOT", fake_root.resolve())
        monkeypatch.chdir(outside_cwd)

        result = create_file(file_path="nested/created.txt", content="ok")

        expected = fake_workspace / "nested" / "created.txt"
        assert expected.exists()
        assert str(expected) in result


class TestDeterministicPaths:
    """路径确定性测试"""

    def test_glob_files_nonexistent_search_dir_returns_empty(self):
        result = shell_tools_module.glob_files("*.py", search_dir="definitely_missing_search_dir_xyz")
        assert result == []

    def test_read_file_relative_path_is_anchored_to_project_root(self, monkeypatch, temp_test_dir):
        monkeypatch.chdir(temp_test_dir)

        result = read_file("agent.py", max_lines=1)

        monkeypatch.chdir(shell_tools_module.PROJECT_ROOT)
        assert str(shell_tools_module.PROJECT_ROOT / "agent.py") in result


# ============================================================================
# edit_file 测试
# ============================================================================

class TestEditFile:
    """edit_file 工具测试"""

    def test_simple_replace(self, temp_test_dir):
        """测试简单替换"""
        file_path = os.path.join(temp_test_dir, "edit.txt")
        with open(file_path, 'w') as f:
            f.write("Hello World")
        
        result = edit_file(file_path=file_path, search_string="World", replace_string="Python")
        assert ("成功" in result or "[OK]" in result or "替换" in result or "replaced" in result.lower())
        
        with open(file_path, 'r') as f:
            assert f.read() == "Hello Python"

    def test_multiple_occurrences(self, temp_test_dir):
        """测试多匹配时返回非唯一匹配提示。"""
        file_path = os.path.join(temp_test_dir, "multi.txt")
        with open(file_path, 'w') as f:
            f.write("a b a b a")
        
        result = edit_file(file_path=file_path, search_string="a", replace_string="X")
        assert "非唯一匹配" in result or "多个匹配" in result or "找到 3 个匹配项" in result

        with open(file_path, 'r') as f:
            content = f.read()
        assert content == "a b a b a"

    def test_replace_all_parameter_no_longer_supported(self, temp_test_dir):
        """当前 edit_file 不支持 replace-all 参数，应显式报 TypeError。"""
        file_path = os.path.join(temp_test_dir, "multi.txt")
        with open(file_path, 'w') as f:
            f.write("a b a b a")

        with pytest.raises(TypeError):
            edit_file(file_path=file_path, search_string="a", replace_string="X", count=0)

    def test_no_match(self, temp_test_dir):
        """测试未找到匹配"""
        file_path = os.path.join(temp_test_dir, "no_match.txt")
        with open(file_path, 'w') as f:
            f.write("Hello World")
        
        result = edit_file(file_path=file_path, search_string="XYZ", replace_string="123")
        assert "未找到" in result or "not found" in result.lower() or "失败" in result

    def test_empty_old_str(self, temp_test_dir):
        """测试空 search_string"""
        file_path = os.path.join(temp_test_dir, "test.txt")
        with open(file_path, 'w') as f:
            f.write("test")
        
        # edit_file 使用 search_string 和 replace_string 参数
        result = edit_file(file_path=file_path, search_string="", replace_string="X")
        assert "错误" in result or "不能为空" in result

    def test_multiline_replace(self, temp_test_dir):
        """测试多行替换"""
        file_path = os.path.join(temp_test_dir, "multiline.txt")
        content = "Line1\nLine2\nLine3"
        with open(file_path, 'w') as f:
            f.write(content)
        
        result = edit_file(file_path=file_path, search_string="Line2\nLine3", replace_string="NewLine")
        
        with open(file_path, 'r') as f:
            updated = f.read()
        assert updated == "Line1\nNewLine"

    def test_auto_backup_created(self, temp_test_dir):
        """测试编辑成功；当前实现不再强依赖显式备份文件副作用。"""
        file_path = os.path.join(temp_test_dir, "backup_test.txt")
        with open(file_path, 'w') as f:
            f.write("原始内容")
        
        result = edit_file(file_path=file_path, search_string="原始", replace_string="新")
        assert "成功" in result or "[OK]" in result or "替换" in result or "更新" in result
        with open(file_path, 'r', encoding='utf-8') as f:
            assert f.read() == "新内容"


# ============================================================================
# check_python_syntax 测试
# ============================================================================

class TestCheckPythonSyntax:
    """check_python_syntax 工具测试"""

    def test_valid_syntax(self, sample_py_file):
        """测试语法正确的文件"""
        result = check_python_syntax(file_path=sample_py_file)
        assert "正确" in result or "OK" in result or "通过" in result

    def test_syntax_error(self, temp_test_dir):
        """测试语法错误"""
        bad_file = os.path.join(temp_test_dir, "bad.py")
        with open(bad_file, 'w') as f:
            f.write("def foo(\n    pass\n")  # 括号未闭合
        
        result = check_python_syntax(file_path=bad_file)
        assert "错误" in result or "Error" in result or "失败" in result

    def test_nonexistent_file(self):
        """测试不存在的文件"""
        result = check_python_syntax(file_path="nonexistent_xyz.py")
        assert "错误" in result or "失败" in result or "not found" in result.lower()

    def test_syntax_warning(self, temp_test_dir):
        """测试语法警告（未使用变量等）"""
        warning_file = os.path.join(temp_test_dir, "warning.py")
        with open(warning_file, 'w') as f:
            f.write("x = 1\n")  # 未使用变量，但语法正确
        
        result = check_python_syntax(file_path=warning_file)
        assert "正确" in result or "OK" in result or "通过" in result

    def test_complex_valid_file(self, sample_py_file):
        """测试复杂但语法正确的文件"""
        result = check_python_syntax(file_path=sample_py_file)
        assert "正确" in result or "OK" in result


# ============================================================================
# execute_shell_command 测试
# ============================================================================

class TestExecuteShellCommand:
    """execute_shell_command 工具测试"""

    def test_simple_echo(self):
        """测试简单 echo 命令"""
        result = execute_shell_command(command="echo Hello World")
        assert "Hello World" in result

    def test_pwd(self):
        """测试 pwd 命令"""
        result = execute_shell_command(command="pwd")
        assert len(result.strip()) > 0
        assert os.path.exists(result.strip())

    def test_dir_ls(self):
        """测试列出目录"""
        result = execute_shell_command(command="dir")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_echo_only(self):
        """测试仅输出"""
        result = execute_shell_command(command="echo 'Test Message'")
        assert "Test Message" in result

    def test_command_with_pipe_is_allowed(self):
        """放宽模式下，包含管道符的常见命令应允许执行。"""
        result = execute_shell_command(command="echo test | findstr test")
        assert "test" in result.lower()

    def test_windows_unix_marker_command_returns_cross_platform_warning(self):
        """Windows 下遇到 Unix shell 片段应直接返回兼容警告，避免误判路径问题。"""
        with patch.object(shell_tools_module, "IS_WINDOWS", True), patch.object(shell_tools_module, "IS_UNIX", False):
            result = execute_shell_command(command="python -m pytest tests/ --collect-only -q 2>/dev/null | tail -5")
        assert "[跨平台警告]" in result
        assert "Unix shell 片段" in result

    def test_empty_command(self):
        """测试空命令"""
        result = execute_shell_command(command="")
        assert "错误" in result or "不能为空" in result

    def test_dangerous_command_blocked(self):
        """测试危险命令被拦截"""
        dangerous_commands = [
            "format C:",
            "del /S C:\\Windows",
            "rm -rf /",
        ]
        for cmd in dangerous_commands:
            result = execute_shell_command(command=cmd)
            assert ("错误" in result or "失败" in result or 
                    "禁止" in result or "危险" in result), f"应阻止命令: {cmd}"


# ============================================================================
# run_powershell 测试
# ============================================================================

class TestRunPowerShell:
    """run_powershell 工具测试"""

    def test_ps_get_process(self):
        """测试获取进程信息"""
        result = run_powershell(command="Get-Process | Select-Object -First 3")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_ps_get_service(self):
        """测试获取服务信息"""
        result = run_powershell(command="Get-Service | Select-Object -First 3")
        assert isinstance(result, str)

    def test_ps_get_childitem(self):
        """测试列出目录"""
        result = run_powershell(command="Get-ChildItem . | Select-Object -First 5")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_ps_invalid_cmdlet_is_allowed_in_relaxed_mode(self):
        """放宽模式下，不再因不在白名单而拦截。"""
        result = run_powershell(command="Invoke-Expression 'echo test'")
        assert "test" in result.lower()

    def test_ps_pipeline_is_allowed_in_relaxed_mode(self):
        """放宽模式下，PowerShell 管道默认允许。"""
        result = run_powershell(command="Get-Process | Select-Object -First 1")
        assert isinstance(result, str)
        assert len(result) > 0


# ============================================================================
# run_batch 测试
# ============================================================================

class TestRunBatch:
    """run_batch 工具测试"""

    def test_batch_multiple_commands(self):
        """测试批量执行多个命令"""
        commands = [
            "echo Command1",
            "pwd",
            "dir",
        ]
        result = run_batch(commands=commands)
        assert isinstance(result, str)
        assert "Command1" in result or "command1" in result.lower() or "command1" in result.lower()

    def test_batch_empty_list(self):
        """测试空命令列表"""
        result = run_batch(commands=[])
        assert "错误" in result or "空" in result or "失败" in result

    def test_batch_with_failure(self):
        """测试批量执行中某个命令失败"""
        commands = [
            "echo Success",
            "nonexistent_command_xyz_12345",  # 会失败
            "echo AfterFailure",
        ]
        result = run_batch(commands=commands)
        # 虽然某个命令失败，但整体应该继续执行
        assert "Success" in result or "AfterFailure" in result or "错误" in result

    def test_batch_sequential_execution(self):
        """测试命令按顺序执行"""
        commands = [
            "set TEST_VAR=value1",
            "echo %TEST_VAR%",
        ]
        result = run_batch(commands=commands)
        assert "value1" in result


# ============================================================================
# check_python_syntax 别名测试
# ============================================================================

class TestCheckSyntax:
    """check_python_syntax 测试"""

    def test_check_python_syntax_works(self, sample_py_file):
        """验证 check_python_syntax 是否可用"""
        from tools.shell_tools import check_python_syntax
        result = check_python_syntax(file_path=sample_py_file)
        assert "正确" in result or "OK" in result or "通过" in result or "Syntax OK" in result


# ============================================================================
# extract_symbols 测试
# ============================================================================

class TestExtractSymbols:
    """extract_symbols 工具测试"""

    def test_extract_from_valid_py(self, sample_py_file):
        """测试从有效 Python 文件提取符号"""
        result = extract_symbols(file_path=sample_py_file)
        assert isinstance(result, str)
        assert "SampleClass" in result
        assert "helper_function" in result
        assert "SAMPLE_VAR" in result

    def test_extract_from_complex_file(self, temp_test_dir):
        """测试从复杂文件提取"""
        complex_file = os.path.join(temp_test_dir, "complex.py")
        content = '''
"""模块文档"""

import os
import sys

CONSTANT = 100

class BaseClass:
    """基类"""
    def method(self):
        pass

class DerivedClass(BaseClass):
    """派生类"""
    def method(self):
        return super().method()

def standalone_func(arg1, arg2=None):
    """独立函数"""
    return arg1

async def async_func():
    """异步函数"""
    pass
'''
        with open(complex_file, 'w') as f:
            f.write(content)
        
        result = extract_symbols(file_path=complex_file)
        assert "BaseClass" in result
        assert "DerivedClass" in result
        assert "standalone_func" in result
        assert "async_func" in result
        assert "CONSTANT" in result

    def test_extract_from_non_py(self, temp_test_dir):
        """测试从非 Python 文件提取"""
        txt_file = os.path.join(temp_test_dir, "readme.txt")
        with open(txt_file, 'w') as f:
            f.write("Just a text file")
        
        result = extract_symbols(file_path=txt_file)
        # 非 Python 文件可能返回空或错误信息
        assert isinstance(result, str)

    def test_extract_nonexistent(self):
        """测试提取不存在的文件"""
        result = extract_symbols(file_path="nonexistent_xyz.py")
        assert "错误" in result or "不存在" in result


# ============================================================================
# backup_project 测试
# ============================================================================

class TestBackupProject:
    """backup_project 工具测试"""

    def test_backup_creates_zip(self):
        """测试备份创建 zip 文件"""
        result = backup_project(version_note="测试备份")
        assert "备份成功" in result or "backup" in result.lower()
        
        # 检查是否有备份文件
        backup_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "backups")
        if os.path.exists(backup_dir):
            backups = os.listdir(backup_dir)
            assert len(backups) > 0

    def test_backup_with_custom_reason(self):
        """测试带自定义原因的备份"""
        reason = f"测试备份 {datetime.now().strftime('%Y%m%d_%H%M%S')}"
        result = backup_project(version_note=reason)
        assert "备份" in result or "backup" in result.lower()

    def test_backup_contains_agent_py(self):
        """测试备份包含核心文件"""
        result = backup_project(version_note="验证备份内容")
        
        # 备份应该成功
        assert "成功" in result or "OK" in result or "backup" in result.lower()


# ============================================================================
# self_test 测试
# ============================================================================

class TestSelfTest:
    """self_test 工具测试"""

    def test_self_test_passes(self):
        """测试自检应通过"""
        result = self_test()
        assert isinstance(result, str)
        # 自检应该返回成功信息
        assert "通过" in result or "OK" in result or "正常" in result or "成功" in result

    def test_self_test_covers_core(self):
        """测试自检覆盖核心功能"""
        result = self_test()
        # 应该提及核心模块
        assert any(keyword in result for keyword in 
                   ["核心", "core", "工具", "tool", "安全", "安全", "模块"])


# ============================================================================
# get_agent_status 测试
# ============================================================================

class TestGetAgentStatus:
    """get_agent_status 工具测试"""

    def test_status_contains_required_fields(self):
        """测试状态信息包含必需字段"""
        result = get_agent_status()
        assert isinstance(result, str)
        # 状态应包含关键信息
        assert ("状态" in result or "status" in result.lower())


# ============================================================================
# 清理测试文件测试
# ============================================================================

class TestCleanupTestFiles:
    """cleanup_test_files 工具测试"""

    def test_cleanup_temp_files(self, temp_test_dir):
        """测试清理临时文件"""
        # 创建一些临时文件
        temp1 = os.path.join(temp_test_dir, "test_temp_123.txt")
        temp2 = os.path.join(temp_test_dir, "temp_file.pyc")
        open(temp1, 'w').close()
        open(temp2, 'w').close()
        
        result = cleanup_test_files(directory=temp_test_dir, dry_run=False)
        assert "清理" in result or "clean" in result.lower()

    def test_cleanup_dry_run(self, temp_test_dir):
        """测试演练模式（dry_run）"""
        temp1 = os.path.join(temp_test_dir, "test_temp_xyz.tmp")
        open(temp1, 'w').close()
        
        result = cleanup_test_files(directory=temp_test_dir, dry_run=True)
        assert ("演练" in result or "dry" in result.lower() or 
                "模拟" in result or "模拟" in result)
        # 文件应仍然存在
        assert os.path.exists(temp1)


# ============================================================================
# 集成测试
# ============================================================================

class TestShellToolsIntegration:
    """Shell 工具集成测试"""

    def test_read_modify_write_cycle(self, temp_test_dir):
        """测试读取-修改-写入完整流程"""
        # 1. 创建文件
        file_path = os.path.join(temp_test_dir, "cycle.txt")
        create_file(file_path=file_path, content="原始内容")
        
        # 2. 读取
        content = read_file(file_path=file_path)
        assert "原始内容" in content
        
        # 3. 修改
        edit_file(file_path=file_path, search_string="原始", replace_string="新")
        
        # 4. 验证
        new_content = read_file(file_path=file_path)
        assert "新内容" in new_content

    def test_list_and_read_workflow(self):
        """测试列出目录并读取文件流程"""
        # 列出项目根目录
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        files = list_directory(path=project_root)
        
        # 如果找到 py 文件，尝试读取
        if "agent.py" in files or "config.py" in files:
            result = get_agent_status()
            assert result is not None

    def test_syntax_check_before_execution(self, sample_py_file):
        """测试执行前语法检查"""
        # 先检查语法
        syntax_result = check_python_syntax(file_path=sample_py_file)
        assert "正确" in syntax_result or "OK" in syntax_result
        
        # 只有语法正确才执行（这里不实际执行，只是演示流程）
        assert True

    def test_backup_and_cleanup_workflow(self):
        """测试备份和清理流程"""
        # 1. 创建备份
        backup_result = backup_project(version_note="集成测试备份")
        assert "成功" in backup_result or "OK" in backup_result
        
        # 2. 获取状态
        status = get_agent_status()
        assert status is not None


# ============================================================================
# 安全测试
# ============================================================================

class TestSecurityFeatures:
    """安全功能测试"""

    def test_destructive_command_chain_still_blocked_by_blacklist(self):
        """放宽模式下，链式命令本身不拦，但破坏性命令仍被黑名单阻止。"""
        injection_attempts = [
            "echo test || format C:",
            "echo test; shutdown /s",
        ]
        for cmd in injection_attempts:
            result = execute_shell_command(command=cmd)
            assert ("错误" in result or "失败" in result or 
                    "危险" in result or "不允许" in result), f"应阻止: {cmd}"

    def test_path_traversal_blocked(self, temp_test_dir):
        """测试路径遍历攻击被阻止"""
        # 尝试访问上级目录
        result = execute_shell_command(
            command=f"cd .. && dir",
            cwd=temp_test_dir
        )
        # 安全模块应该限制路径
        assert ("错误" in result or "失败" in result or 
                "超出" in result or "不允许" in result or "沙箱" in result or
                "安全拦截" in result or "危险命令" in result)

    def test_forbidden_extensions(self, temp_test_dir):
        """测试禁止的文件扩展名"""
        # 尝试创建 .exe 文件
        exe_path = os.path.join(temp_test_dir, "malware.exe")
        content = "fake exe content"
        
        # 直接调用 create_file（内部会检查）
        # 应该被安全模块阻止
        try:
            from core.security import validate_file_operation
            is_safe, error = validate_file_operation(
                "write", exe_path, content
            )
            assert is_safe is False
            assert "禁止" in error or "extension" in error.lower()
        except ImportError:
            pytest.skip("安全模块未加载")


# ============================================================================
# 性能测试
# ============================================================================

class TestPerformance:
    """性能基准测试"""

    def test_read_file_performance(self, temp_test_dir):
        """测试读取大文件性能"""
        large_file = os.path.join(temp_test_dir, "large.txt")
        # 创建 1MB 文件
        with open(large_file, 'w', encoding='utf-8') as f:
            f.write("x" * 1024 * 1024)
        
        start = time.time()
        result = read_file(file_path=large_file)
        elapsed = time.time() - start
        
        assert len(result) >= 1024 * 1024
        assert "x" * 100 in result
        assert elapsed < 5.0  # 应该在 5 秒内完成

    def test_list_directory_performance(self):
        """测试列出大目录性能"""
        # 项目根目录可能有很多文件
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
        start = time.time()
        result = list_directory(path=project_root, recursive=False)
        elapsed = time.time() - start
        
        assert elapsed < 10.0  # 应该在 10 秒内完成

    def test_concurrent_execution(self):
        """测试并发执行（线程安全）"""
        from concurrent.futures import ThreadPoolExecutor
        
        def run_command(cmd):
            return execute_shell_command(command=cmd)
        
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(run_command, "echo test") for _ in range(10)]
            results = [f.result() for f in futures]
        
        assert all("test" in r for r in results)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
