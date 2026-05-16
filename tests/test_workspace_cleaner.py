#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Workspace Cleaner 测试

测试 core/infrastructure/workspace_cleaner.py 中的：
- classify_file: 文件分类逻辑
- _is_variant_filename: 版本增殖检测
- scan_workspace_debris: 碎片扫描
- clean_debris: 碎片清理 (dry-run + confirmed)
- auto_clean_session_debris: 会话自动清理
- list_workspace_debris_tool / clean_workspace_debris_tool: Agent 工具
"""

import os
import json
import sys
import pytest
from pathlib import Path

from core.infrastructure.workspace_cleaner import (
    classify_file,
    scan_workspace_debris,
    clean_debris,
    auto_clean_session_debris,
    list_workspace_debris_tool,
    clean_workspace_debris_tool,
    get_session_files_tool,
    _is_variant_filename,
    LEGITIMATE_DIRS,
    LEGITIMATE_ROOT_FILES,
)


# ============================================================================
# classify_file 测试
# ============================================================================

class TestClassifyFile:
    """文件分类测试"""

    def test_legitimate_root_file(self, tmp_path):
        """白名单根文件被正确识别"""
        ws = tmp_path / "workspace"
        ws.mkdir()
        (ws / "agent_brain.db").write_text("")
        assert classify_file(str(ws / "agent_brain.db"), str(ws)) == "legitimate"

    def test_legitimate_subdir(self, tmp_path):
        """白名单子目录文件被正确识别"""
        ws = tmp_path / "workspace"
        ws.mkdir()
        (ws / "memory").mkdir()
        (ws / "memory" / "test.json").write_text("{}")
        assert classify_file(str(ws / "memory" / "test.json"), str(ws)) == "legitimate"

    def test_debris_root_py(self, tmp_path):
        """工作区根目录普通 .py 文件被识别为 root_py 碎片"""
        ws = tmp_path / "workspace"
        ws.mkdir()
        (ws / "test_script.py").write_text("print('hello')")
        assert classify_file(str(ws / "test_script.py"), str(ws)) == "debris_root_py"

    def test_debris_variant(self, tmp_path):
        """版本增殖文件被识别"""
        ws = tmp_path / "workspace"
        ws.mkdir()
        (ws / "fix_v2.py").write_text("")
        assert classify_file(str(ws / "fix_v2.py"), str(ws)) == "debris_variant"

    def test_debris_mirror_core(self, tmp_path):
        """镜像子树被识别"""
        ws = tmp_path / "workspace"
        ws.mkdir()
        (ws / "core").mkdir(parents=True)
        (ws / "core" / "test.py").write_text("")
        assert classify_file(str(ws / "core" / "test.py"), str(ws)) == "debris_mirror"

    def test_debris_mirror_tests(self, tmp_path):
        """镜像 tests 目录被识别"""
        ws = tmp_path / "workspace"
        ws.mkdir()
        (ws / "tests").mkdir()
        (ws / "tests" / "test_x.py").write_text("")
        assert classify_file(str(ws / "tests" / "test_x.py"), str(ws)) == "debris_mirror"

    def test_unknown_dir(self, tmp_path):
        """未知子目录被识别"""
        ws = tmp_path / "workspace"
        ws.mkdir()
        (ws / "random_stuff").mkdir()
        (ws / "random_stuff" / "data.bin").write_text("")
        assert classify_file(str(ws / "random_stuff" / "data.bin"), str(ws)) == "debris_unknown"


# ============================================================================
# _is_variant_filename 测试
# ============================================================================

class TestVariantDetection:
    """版本增殖检测测试"""

    @pytest.mark.parametrize("fname,expected", [
        ("fix_v2.py", True),
        ("fix_v3.py", True),
        ("patch_agent.py", True),
        ("temp_debug.py", True),
        ("debug_line.py", True),
        ("something_fix.py", True),
        ("fix_final.py", True),
        ("old_code.py", True),
        ("normal_file.py", False),
        ("agent.py", False),
        ("test_workspace.py", False),
    ])
    def test_variant_patterns(self, fname, expected):
        """参数化测试版本增殖模式"""
        assert _is_variant_filename(fname) == expected


# ============================================================================
# scan_workspace_debris 测试
# ============================================================================

class TestScanWorkspace:
    """碎片扫描测试"""

    def test_empty_workspace(self, tmp_path):
        """空工作区扫描"""
        ws = tmp_path / "workspace"
        ws.mkdir()
        report = scan_workspace_debris(str(ws))
        assert report["total_files"] == 0
        assert report["debris_count"] == 0

    def test_legitimate_only(self, tmp_path):
        """仅含合法文件的工作区（白名单目录内文件不计数，根文件计为合法）"""
        ws = tmp_path / "workspace"
        ws.mkdir()
        (ws / "agent_brain.db").write_text("")
        (ws / "memory").mkdir()
        (ws / "memory" / "data.json").write_text("{}")
        (ws / "prompts").mkdir()
        (ws / "prompts" / "SOUL.md").write_text("# SOUL")

        report = scan_workspace_debris(str(ws))
        # agent_brain.db 在白名单中，memory/prompts 目录内容被跳过
        assert report["legitimate_count"] >= 1
        assert report["debris_count"] == 0

    def test_detects_debris(self, tmp_path):
        """检测到碎片文件"""
        ws = tmp_path / "workspace"
        ws.mkdir()
        (ws / "hello.py").write_text("")
        (ws / "script_v2.py").write_text("")
        (ws / "core").mkdir(parents=True)
        (ws / "core" / "something.py").write_text("")

        report = scan_workspace_debris(str(ws))
        assert report["debris_count"] == 3
        assert "debris_root_py" in report["debris_by_category"]
        assert "debris_variant" in report["debris_by_category"]
        assert "debris_mirror" in report["debris_by_category"]

    def test_skips_legitimate_dirs_content(self, tmp_path):
        """扫描时跳过白名单目录内容"""
        ws = tmp_path / "workspace"
        ws.mkdir()
        (ws / "memory").mkdir(parents=True)
        (ws / "memory" / "archives").mkdir()
        (ws / "memory" / "archives" / "old.json").write_text("{}")
        (ws / "mental_model").mkdir()
        (ws / "mental_model" / "rules.json").write_text("{}")

        report = scan_workspace_debris(str(ws))
        # 白名单目录内的文件不计入 report
        assert report["debris_count"] == 0


# ============================================================================
# clean_debris 测试
# ============================================================================

class TestCleanDebris:
    """碎片清理测试"""

    def test_dry_run_no_delete(self, tmp_path):
        """confirm=False 时不删除文件"""
        ws = tmp_path / "workspace"
        ws.mkdir()
        f = ws / "fix_agent.py"
        f.write_text("print('hello')")

        report = clean_debris(str(ws), confirmed=False)
        assert report["mode"] == "dry_run"
        assert f.exists()  # 文件仍然存在

    def test_confirm_deletes_debris(self, tmp_path):
        """confirm=True 时删除碎片"""
        ws = tmp_path / "workspace"
        ws.mkdir()
        f = ws / "fix_agent.py"
        f.write_text("print('hello')")

        report = clean_debris(str(ws), confirmed=True)
        assert report["mode"] == "confirmed"
        assert report["deleted_count"] >= 1
        assert not f.exists()

    def test_legitimate_files_survive(self, tmp_path):
        """白名单文件不被删除"""
        ws = tmp_path / "workspace"
        ws.mkdir()
        db = ws / "agent_brain.db"
        db.write_text("")
        (ws / "memory").mkdir()
        mem = ws / "memory" / "data.json"
        mem.write_text("{}")

        report = clean_debris(str(ws), confirmed=True)
        assert db.exists()
        assert mem.exists()

    def test_category_filter(self, tmp_path):
        """按类别过滤清理"""
        ws = tmp_path / "workspace"
        ws.mkdir()
        f_py = ws / "hello.py"
        f_py.write_text("")
        (ws / "core").mkdir(parents=True)
        f_mirror = ws / "core" / "x.py"
        f_mirror.write_text("")

        # 只清理 root_py 类别
        report = clean_debris(str(ws), categories=["debris_root_py"], confirmed=True)
        assert not f_py.exists()  # 被清理
        assert f_mirror.exists()  # 保留

    def test_session_files_filter(self, tmp_path):
        """session_files 过滤——只清理会话创建的文件"""
        ws = tmp_path / "workspace"
        ws.mkdir()
        session_file = ws / "fix_agent.py"
        session_file.write_text("")
        other_file = ws / "old_script.py"
        other_file.write_text("")

        session_set = {str(session_file.resolve())}
        report = clean_debris(str(ws), confirmed=True, session_files=session_set)
        assert not session_file.exists()  # 会话文件被清理
        assert other_file.exists()  # 非会话文件保留

    def test_clean_removes_empty_debris_dirs(self, tmp_path):
        """清理后删除空碎片目录"""
        ws = tmp_path / "workspace"
        ws.mkdir()
        (ws / "core" / "core_prompt").mkdir(parents=True)
        f = ws / "core" / "core_prompt" / "SOUL.md"
        f.write_text("# old SOUL")

        clean_debris(str(ws), confirmed=True)
        assert not f.exists()
        assert not (ws / "core" / "core_prompt").exists()
        assert not (ws / "core").exists()


# ============================================================================
# auto_clean_session_debris 测试
# ============================================================================

class TestAutoCleanSession:
    """会话自动清理测试"""

    def test_no_files_no_op(self, tmp_path):
        """无会话文件时无操作"""
        ws = tmp_path / "workspace"
        ws.mkdir()
        report = auto_clean_session_debris(str(ws), mental_model=None)
        assert report["deleted_count"] == 0

    def test_cleans_session_debris(self, tmp_path):
        """清理本次会话创建的碎片文件"""
        ws = tmp_path / "workspace"
        ws.mkdir()
        f = ws / "fix_agent.py"
        f.write_text("")

        # 模拟 MentalModel 返回此文件
        class FakeMentalModel:
            def get_agent_created_files(self):
                return {str(f.resolve()): {"path": str(f), "is_variant": False}}

        report = auto_clean_session_debris(str(ws), mental_model=FakeMentalModel())
        assert report["deleted_count"] == 1
        assert not f.exists()


# ============================================================================
# Agent 工具函数测试
# ============================================================================

class TestAgentTools:
    """Agent 可调用工具测试"""

    def test_list_workspace_debris_tool_valid_json(self, tmp_path):
        """list_workspace_debris_tool 返回有效 JSON"""
        ws = tmp_path / "workspace"
        ws.mkdir()
        (ws / "agent_brain.db").write_text("")

        result = list_workspace_debris_tool(directory=str(ws))
        parsed = json.loads(result)
        assert "debris_count" in parsed
        assert "debris_by_category" in parsed

    def test_get_session_files_tool(self):
        """get_session_files_tool 返回有效 JSON（MentalModel 不可用时降级）"""
        result = get_session_files_tool()
        parsed = json.loads(result)
        assert "total_files" in parsed
