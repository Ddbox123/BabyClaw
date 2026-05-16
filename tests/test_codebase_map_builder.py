#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from types import SimpleNamespace
from pathlib import Path

from core.prompt_manager import codebase_map_builder as cmb


def test_extract_markdown_section():
    content = "## A\n1\n\n## B\n2\n3\n\n## C\n4"
    assert cmb._extract_markdown_section(content, "B") == "## B\n2\n3"


def test_build_task_focused_view_prefers_goal_and_hot_paths(monkeypatch, tmp_path):
    (tmp_path / "core" / "prompt_manager").mkdir(parents=True)
    (tmp_path / "core" / "infrastructure").mkdir(parents=True)
    (tmp_path / "agent.py").write_text('"""entry"""\n', encoding="utf-8")
    pm_file = tmp_path / "core" / "prompt_manager" / "prompt_manager.py"
    pm_file.write_text('"""prompt orchestration"""\n', encoding="utf-8")
    infra_file = tmp_path / "core" / "infrastructure" / "tool_executor.py"
    infra_file.write_text('"""tool runtime"""\n', encoding="utf-8")

    monkeypatch.setattr(cmb, "_collect_python_files", lambda _root: [pm_file, infra_file, tmp_path / "agent.py"])
    monkeypatch.setattr(
        cmb,
        "_scan_file",
        lambda path: {
            "docstring": "prompt orchestration" if "prompt_manager.py" in str(path) else "tool runtime",
            "imports": ["core.prompt_manager"] if "prompt_manager.py" in str(path) else ["core.infrastructure"],
        },
    )
    monkeypatch.setattr(
        cmb,
        "_get_prompt_runtime_context",
        lambda: ("优化 prompt manager 的 section 选择", "## 延续约束\n- 先检查 tool executor"),
    )
    monkeypatch.setattr(
        "core.infrastructure.agent_session.get_session_state",
        lambda: SimpleNamespace(get_attention_snapshot=lambda: {
            "modified_paths": ["core/prompt_manager/prompt_manager.py"],
            "modified_entities": ["PromptManager._select_sections"],
            "last_validation_summary": "tests passed",
        }),
    )

    class DummyGitMemory:
        def get_recent_project_changes(self, limit=4):
            return [SimpleNamespace(path="core/prompt_manager/prompt_manager.py", change_type="modified", subject="prompt work")]

    monkeypatch.setattr("core.infrastructure.git_memory.get_git_memory_service", lambda: DummyGitMemory())

    full_content = (
        "## 子系统概览\n| 子系统 | 路径 | 文件 | 风险 |\n"
        "|--------|------|------|------|\n| 提示词引擎 | `core/prompt_manager/` | 5 | `core` |\n\n"
        "## 核心依赖 (被依赖最多的模块 Top-10)\n- `core/prompt_manager/prompt_manager.py` ← 3 文件\n"
        "- `core/infrastructure/tool_executor.py` ← 2 文件\n\n"
        "## 测试覆盖\n覆盖率: 80% (8/10) | 未覆盖: 2 个模块\n"
    )

    rendered = cmb._build_task_focused_view(tmp_path, full_content)

    assert "## 当前任务局部地图" in rendered
    assert "## 影响链路" in rendered
    assert "当前目标: 优化 prompt manager 的 section 选择" in rendered
    assert "`core/prompt_manager/prompt_manager.py`" in rendered
    assert "## 全局骨架摘要" in rendered
    assert "## 子系统概览" in rendered


def test_build_impact_chain_view_shows_dependents_and_tests(monkeypatch, tmp_path):
    (tmp_path / "core" / "prompt_manager").mkdir(parents=True)
    (tmp_path / "core" / "infrastructure").mkdir(parents=True)
    target = tmp_path / "core" / "prompt_manager" / "prompt_manager.py"
    caller = tmp_path / "core" / "infrastructure" / "tool_executor.py"
    target.write_text('"""prompt orchestration"""\n', encoding="utf-8")
    caller.write_text('"""tool runtime"""\n', encoding="utf-8")

    monkeypatch.setattr(
        cmb,
        "_scan_file",
        lambda path: {
            "docstring": "prompt orchestration" if path == target else "tool runtime",
            "imports": [] if path == target else ["core.prompt_manager.prompt_manager"],
        },
    )

    rendered = cmb._build_impact_chain_view([target], [target, caller], tmp_path)

    assert "## 影响链路" in rendered
    assert "`core/prompt_manager/prompt_manager.py`" in rendered
    assert "`core/infrastructure/tool_executor.py`" in rendered
    assert "`tests/test_prompt_manager.py`" in rendered
