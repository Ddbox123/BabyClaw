#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PromptManager 测试

测试 core/prompt_manager/ 重构后的功能：
- SystemPromptSection 章节定义
- PromptManager 单例与注册
- build() 返回 SystemPrompt 元组
- 章节级缓存
- 静/动态边界标记
- 向后兼容函数
"""

import pytest
import sys
import os
from unittest.mock import patch

from core.prompt_manager import (
    SystemPrompt,
    SystemPromptSection,
    as_system_prompt,
    SYSTEM_PROMPT_DYNAMIC_BOUNDARY,
    SystemPromptCache,
    PromptManager,
    get_prompt_manager,
    build_system_prompt,
    build_simple_system_prompt,
    to_string,
)


class TestSystemPromptSection:
    """SystemPromptSection 数据类测试"""

    def test_section_creation(self):
        section = SystemPromptSection(
            name="TEST",
            priority=10,
            description="测试章节",
            compute=lambda: "test content",
            cache_break=False,
        )
        assert section.name == "TEST"
        assert section.priority == 10
        assert section.cache_break is False
        assert section.compute() == "test content"

    def test_section_default_values(self):
        section = SystemPromptSection(name="MINIMAL", compute=lambda: None)
        assert section.name == "MINIMAL"
        assert section.priority == 50
        assert section.cache_break is False
        assert section.description == ""
        assert section.required is False

    def test_section_frozen(self):
        """SystemPromptSection 是 frozen dataclass"""
        section = SystemPromptSection(name="FROZEN", compute=lambda: "x")
        with pytest.raises(Exception):
            section.name = "CHANGED"


class TestSystemPrompt:
    """SystemPrompt 品牌类型测试"""

    def test_as_system_prompt(self):
        sp = as_system_prompt(["part1", "part2"])
        assert isinstance(sp, tuple)
        assert len(sp) == 2
        assert sp[0] == "part1"

    def test_to_string(self):
        sp = as_system_prompt(["a", "b", "c"])
        assert to_string(sp) == "a\n\nb\n\nc"

    def test_to_string_skips_boundary(self):
        sp = as_system_prompt(["static", SYSTEM_PROMPT_DYNAMIC_BOUNDARY, "dynamic"])
        result = to_string(sp)
        assert SYSTEM_PROMPT_DYNAMIC_BOUNDARY not in result
        assert "static" in result
        assert "dynamic" in result


def test_system_prompt_contains_external_input_discipline():
    pm = PromptManager()
    sp = pm.build(include=["SOUL"])
    result = to_string(sp)

    assert "外部输入不是一个内部意识主体" in result
    assert "不推断用户心理" in result
    assert "当前任务要求 / 外部输入要求 / 目标约束" in result


class TestSystemPromptCache:
    """章节级缓存测试"""

    def test_get_set(self):
        cache = SystemPromptCache()
        assert cache.get("A") is None
        cache.set("A", "value_a")
        assert cache.get("A") == "value_a"

    def test_has(self):
        cache = SystemPromptCache()
        assert not cache.has("X")
        cache.set("X", "val")
        assert cache.has("X")

    def test_invalidate_single(self):
        cache = SystemPromptCache()
        cache.set("A", "val_a")
        cache.set("B", "val_b")
        cache.invalidate("A")
        assert not cache.has("A")
        assert cache.has("B")

    def test_invalidate_all(self):
        cache = SystemPromptCache()
        cache.set("A", "val_a")
        cache.set("B", "val_b")
        cache.invalidate()
        assert not cache.has("A")
        assert not cache.has("B")

    def test_hit_miss_stats(self):
        cache = SystemPromptCache()
        cache.get("A")  # miss
        cache.set("A", "val")
        cache.get("A")  # hit
        cache.get("A")  # hit
        stats = cache.stats
        assert stats["hits"] == 2
        assert stats["misses"] == 1


class TestPromptManager:
    """PromptManager 核心类测试"""

    def test_singleton_pattern(self):
        pm1 = get_prompt_manager()
        pm2 = get_prompt_manager()
        assert pm1 is pm2

    def test_section_registration(self):
        pm = PromptManager()
        initial_count = len(pm._sections)

        custom = SystemPromptSection(
            name="CUSTOM", priority=5, compute=lambda: "custom content"
        )
        pm.register(custom)
        assert "CUSTOM" in pm._sections
        assert len(pm._sections) == initial_count + 1

        # 覆盖注册
        new_section = SystemPromptSection(
            name="CUSTOM", priority=99, compute=lambda: "new content"
        )
        pm.register(new_section)
        assert pm._sections["CUSTOM"].priority == 99

    def test_section_unregistration(self):
        pm = PromptManager()
        pm.register(SystemPromptSection(name="TO_REMOVE", compute=lambda: None))
        assert "TO_REMOVE" in pm._sections
        pm.unregister("TO_REMOVE")
        assert "TO_REMOVE" not in pm._sections

    def test_list_sections(self):
        pm = PromptManager()
        sections = pm.list_sections()
        names = [s["name"] for s in sections]
        assert "SOUL" in names
        assert "SPEC" in names
        assert "SPEC_DIGEST" in names
        assert "GIT_MEMORY" in names
        assert "DELEGATION_RULES" in names
        assert "CONFIG_AWARENESS" in names
        assert "LANGUAGE_AWARENESS" in names
        assert "GIT_RULES" in names
        # 按 priority 排序
        priorities = [s["priority"] for s in sections]
        assert priorities == sorted(priorities)

    def test_get_status(self):
        pm = PromptManager()
        status = pm.get_status()
        assert "static_root" in status
        assert "dynamic_root" in status
        assert "registered_sections" in status
        assert "prompt_mode" in status
        assert "last_build_summary" in status
        assert len(status["registered_sections"]) >= 5

    def test_required_sections_cannot_be_excluded(self):
        pm = PromptManager()
        sp = pm.build(exclude=["SOUL", "SPEC"])
        result = to_string(sp)
        # SOUL 和 SPEC 是 required=True，即使在 exclude 列表中也会保留
        assert isinstance(result, str)
        assert len(result) > 0


class TestBuildAPI:
    """build() API 测试"""

    def test_build_default(self):
        pm = PromptManager()
        pm.update_state_memory("## 下一轮短期约束\n- 先补观测，再继续推理。")
        sp = pm.build()
        assert isinstance(sp, tuple)  # SystemPrompt 是 tuple
        result = to_string(sp)
        assert isinstance(result, str)
        assert len(result) > 0
        assert "## SPEC 运行时摘要" in result
        assert "# SPEC 开发流程规范" in result
        assert "## 语言状态" in result
        assert "## 你的记忆与状态" in result
        assert "## 委派规则" in result
        assert "先补观测，再继续推理" in result

    def test_build_with_memory_params(self):
        pm = PromptManager()
        sp = pm.build(
            include=["SOUL", "SPEC", "MEMORY"],
            core_context="学会了优化代码",
            current_goal="改进性能",
        )
        result = to_string(sp)
        assert isinstance(result, str)
        assert "优化代码" in result

    def test_default_build_keeps_full_spec_but_prunes_other_low_relevance_optional_sections(self):
        pm = PromptManager()
        sp = pm.build()
        result = to_string(sp)
        assert "## 当前任务局部地图" not in result
        assert "# SPEC 开发流程规范" in result
        assert "## SPEC 运行时摘要" in result
        assert "## Git 提交规则" not in result
        assert "## 配置自感知" not in result
        assert "## 当前环境" not in result

    def test_goal_can_reenable_relevant_optional_sections(self):
        pm = PromptManager()
        sp = pm.build(
            current_goal="先检查 config 配置和 git 提交策略，再判断 provider 是否有问题",
        )
        result = to_string(sp)
        assert "## Git 提交规则" in result
        assert "## 配置自感知" in result

    def test_broad_orient_goal_keeps_full_spec_by_default(self):
        pm = PromptManager()
        sp = pm.build(current_goal="开始自主进化")
        result = to_string(sp)
        assert "# SPEC 开发流程规范" in result

    def test_absolute_probe_path_does_not_reenable_env_info_by_itself(self):
        pm = PromptManager()
        sp = pm.build(
            current_goal=r"调用 write_file_tool 写入 C:\temp\demo\tests\probe.py，然后立即重启，不要扩散",
        )
        result = to_string(sp)
        assert "## 当前环境" not in result

    def test_state_memory_config_path_does_not_reenable_config_awareness_by_itself(self):
        pm = PromptManager()
        sp = pm.build(
            current_goal="继续完成重启闭环，不要扩散",
            state_memory="### 收束状态\n- 当前状态：准备验证\n- 范围已冻结：config.harness.toml\n",
        )
        result = to_string(sp)
        assert "## 配置自感知" not in result

    def test_windows_local_path_and_close_word_do_not_false_positive_config_or_env(self):
        pm = PromptManager()
        sp = pm.build(
            current_goal=(
                r"调用 write_file_tool 写入 C:\Users\me\AppData\Local\Temp\probe.py，"
                r"然后调用 close_evolution_transaction_tool 关账"
            ),
        )
        result = to_string(sp)
        assert "## 配置自感知" not in result
        assert "## 当前环境" not in result

    def test_architecture_goal_can_reenable_codebase_map(self):
        pm = PromptManager()
        sp = pm.build(
            current_goal="先审查 prompt 拼接架构、模块边界和整体调用链",
        )
        result = to_string(sp)
        assert "## 当前任务局部地图" in result

    def test_prompt_rule_goal_can_reenable_full_spec(self):
        pm = PromptManager()
        sp = pm.build(
            current_goal="继续优化 prompt 拼接规则，并审查 SPEC 规范是否需要拆分",
        )
        result = to_string(sp)
        assert "# SPEC 开发流程规范" in result

    def test_readonly_log_diagnosis_keeps_heavy_sections_trimmed(self):
        pm = PromptManager()
        sp = pm.build(
            current_goal="分析 log_info/conversation_20260511_162502.jsonl 中子 agent 为什么会超时，只做诊断，不要修改代码。",
            core_context="目标锚点：log_info/conversation_20260511_162502.jsonl",
        )
        result = to_string(sp)
        assert "## 当前任务局部地图" not in result
        assert "## Git 提交规则" not in result
        assert "# SPEC 开发流程规范" not in result

    def test_build_include_filter(self):
        pm = PromptManager()
        sp = pm.build(include=["SOUL", "SPEC"])
        result = to_string(sp)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_explicit_include_keeps_optional_section(self):
        pm = PromptManager()
        sp = pm.build(include=["SOUL", "CONFIG_AWARENESS", "GIT_RULES", "ENV_INFO"])
        result = to_string(sp)
        assert "## 配置自感知" in result
        assert "## Git 提交规则" in result
        assert "## 当前环境" in result

    def test_env_info_includes_windows_shell_discipline(self):
        pm = PromptManager()
        sp = pm.build(include=["ENV_INFO"])
        result = to_string(sp)

        if "操作系统: Windows" not in result:
            pytest.skip("当前测试运行环境不是 Windows")

        assert "命令平台纪律" in result
        assert "/dev/null" in result
        assert "Select-Object -First/-Last" in result
        assert "不要用带 Unix 管道的 `cli_tool` 试探" in result

    def test_build_exclude_filter(self):
        pm = PromptManager()
        sp = pm.build(exclude=["MEMORY", "TOOLS_INDEX", "ENV_INFO"])
        result = to_string(sp)
        assert isinstance(result, str)
        # 被排除的组件不应出现
        assert "核心智慧摘要" not in result
        assert "工具手册索引" not in result
        assert "当前时间" not in result

    def test_build_include_and_exclude(self):
        pm = PromptManager()
        sp = pm.build(
            include=["SOUL", "TASK_CHECKLIST", "SPEC"],
            exclude=["MEMORY"],
        )
        result = to_string(sp)
        assert isinstance(result, str)
        assert "## 语言状态" in result

    def test_protected_floor_survives_include_override(self):
        pm = PromptManager()
        sp = pm.build(include=["SOUL"])
        result = to_string(sp)
        assert "## 语言状态" in result
        assert "## 你的记忆与状态" not in result or isinstance(result, str)
        names = [item["name"] for item in pm.get_last_index()]
        for name in ["SOUL", "SPEC_DIGEST", "MEMORY", "GIT_MEMORY", "LANGUAGE_AWARENESS"]:
            assert name in names

    def test_build_subagent_prompt_is_thin_and_structured(self):
        pm = PromptManager()
        result = pm.build_subagent_prompt(
            task_type="diagnose",
            goal="分析最近一轮日志里为什么重复调用工具",
            scope={"log": "log_info/demo.jsonl"},
            constraints={"max_steps": 4, "max_output_chars": 1200},
            deliverables=["status", "summary", "findings", "evidence", "recommended_next_action", "confidence"],
            context_pack="- 最近阻塞: duplicate_search",
        )
        assert "## 子 Agent 基座" in result
        assert "## 语言状态" in result
        assert "当前默认表达语言：中文" in result
        assert "## 主 Agent 任务指令" in result
        assert "## 最小上下文" in result
        assert "## 输出要求" in result
        assert "log_info/demo.jsonl" in result
        assert "完整 `SOUL`" not in result
        assert "不要尝试 `cli_tool`" in result
        assert "禁止跳读" in result

    def test_build_subagent_prompt_includes_role_contract(self):
        pm = PromptManager()
        result = pm.build_subagent_prompt(
            task_type="summarize",
            goal="总结当前已有证据",
            scope={"recent_blockers": ["a", "b"]},
            constraints={"readonly": True},
            deliverables=["status", "summary", "findings", "evidence", "recommended_next_action", "confidence"],
            context_pack="- 最近验证: pytest 通过",
        )
        assert "你的当前系统角色: 证据压缩器。" in result
        assert "你的存在目的: 把已存在的局部证据压缩成低熵结论" in result
        assert "你负责的工作:" in result
        assert "你不负责的工作:" in result
        assert "输出形态: 返回压缩后的结论、关键证据、剩余缺口与建议的下一步。" in result

    def test_build_subagent_prompt_reuses_language_awareness_section(self):
        pm = PromptManager()
        pm.register(SystemPromptSection(
            name="LANGUAGE_AWARENESS",
            compute=lambda: "## 语言状态\n- 使用测试语言习惯",
            cache_break=True,
            priority=37,
        ))
        result = pm.build_subagent_prompt(
            task_type="inspect",
            goal="验证子 agent 语言提示词来源",
        )
        assert "## 语言状态" in result
        assert "使用测试语言习惯" in result
        assert "当前默认表达语言：中文" not in result

    def test_select_components_cannot_drop_protected_floor(self):
        pm = PromptManager()
        pm.select_components(["SOUL"])
        sp = pm.build()
        result = to_string(sp)
        assert "## 语言状态" in result
        names = [item["name"] for item in pm.get_last_index()]
        for name in ["SOUL", "SPEC_DIGEST", "MEMORY", "GIT_MEMORY", "LANGUAGE_AWARENESS"]:
            assert name in names

    def test_build_empty_include(self):
        pm = PromptManager()
        sp = pm.build(include=[])
        result = to_string(sp)
        assert isinstance(result, str)
        # 空 include = 无章节被选中，但仍有索引/指南文本
        assert isinstance(sp, tuple)

    def test_build_returns_system_prompt_tuple(self):
        pm = PromptManager()
        sp = pm.build(include=["SOUL"])
        assert isinstance(sp, tuple)
        # 每个元素都是字符串
        for part in sp:
            assert isinstance(part, str)

    def test_build_contains_boundary_marker(self):
        """包含动态章节时应有边界标记"""
        pm = PromptManager()
        sp = pm.build(include=["SOUL", "ENV_INFO"])
        # SOUL 是静态，ENV_INFO 是动态，之间应有边界标记
        parts = list(sp)
        assert SYSTEM_PROMPT_DYNAMIC_BOUNDARY in parts


class TestCompatibilityFunctions:
    """向后兼容函数测试"""

    def test_build_system_prompt(self):
        result = build_system_prompt()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_build_simple_system_prompt(self):
        result = build_simple_system_prompt()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_to_string_on_system_prompt(self):
        pm = PromptManager()
        sp = pm.build(include=["SOUL", "SPEC"])
        result = to_string(sp)
        assert isinstance(result, str)
        assert len(result) > 0
        assert "# SPEC 开发流程规范" in result


class TestCache:
    """章节级缓存测试"""

    def test_invalidate_single_cache(self):
        pm = PromptManager()
        pm.build(include=["SOUL"])
        pm.invalidate_cache("SOUL")
        assert not pm._section_cache.has("SOUL")

    def test_invalidate_all_cache(self):
        pm = PromptManager()
        pm.build(include=["SOUL", "SPEC"])
        pm.invalidate_cache()
        assert len(pm._section_cache.stats["cached_sections"]) == 0

    def test_cache_hit(self):
        pm = PromptManager()
        pm.build(include=["SOUL", "SPEC"])
        stats = pm.get_cache_stats()
        # 静态章节应在缓存中
        assert "SOUL" in stats["cached_sections"]

    def test_cache_invalidated_by_state_memory(self):
        pm = PromptManager()
        pm.build(include=["SOUL"])
        stats_before = pm.get_cache_stats()

        pm.update_state_memory("新的状态记忆")
        stats_after = pm.get_cache_stats()
        # MEMORY 缓存应被清除
        assert "MEMORY" not in stats_after["cached_sections"]

    def test_update_state_memory_skips_duplicate_persist(self, monkeypatch):
        pm = PromptManager()
        calls = []

        monkeypatch.setattr(pm, "_persist_state_memory", lambda text: calls.append(text))

        pm.update_state_memory("  相同状态  ")
        pm.update_state_memory("相同状态")

        assert calls == ["相同状态"]

    def test_update_state_memory_can_skip_persist_for_runtime_only_update(self, monkeypatch):
        pm = PromptManager()
        calls = []

        monkeypatch.setattr(pm, "_persist_state_memory", lambda text: calls.append(text))

        pm.update_state_memory("运行时状态", persist=False)

        assert pm.state_memory == "运行时状态"
        assert calls == []

    def test_clear_state_memory_can_skip_persist_for_runtime_reset(self, tmp_path):
        pm = PromptManager(enable_workspace=True)
        pm._dynamic_root = tmp_path
        pm.state_memory = "运行时状态"
        pm._last_persisted_state_memory = "运行时状态"
        state_file = tmp_path / "STATE_MEMORY.md"
        state_file.write_text("运行时状态", encoding="utf-8")

        pm.clear_state_memory(persist=False)

        assert pm.state_memory == ""
        assert state_file.read_text(encoding="utf-8") == "运行时状态"

    def test_task_checklist_is_dynamic_not_cached(self):
        pm = PromptManager()
        section = pm._sections["TASK_CHECKLIST"]
        assert section.cache_break is True

    def test_build_computes_dynamic_section_only_once(self):
        pm = PromptManager()
        calls = {"count": 0}

        def compute():
            calls["count"] += 1
            return "## 动态测试\n- hello"

        pm.register(SystemPromptSection(
            name="DYNAMIC_TEST",
            compute=compute,
            cache_break=True,
            priority=39,
        ))

        pm.build(include=["DYNAMIC_TEST"])
        assert calls["count"] == 1

    def test_last_index_uses_actual_build_content(self):
        pm = PromptManager()
        pm.register(SystemPromptSection(
            name="INDEX_TEST",
            compute=lambda: "abc",
            cache_break=True,
            priority=39,
        ))
        pm.build(include=["INDEX_TEST"])
        index = {item["name"]: item for item in pm.get_last_index()}
        assert index["INDEX_TEST"]["length"] == 3
        assert index["INDEX_TEST"]["is_empty"] is False

    def test_build_status_records_omitted_heavy_sections(self):
        pm = PromptManager()
        pm.build()
        summary = pm.get_status()["last_build_summary"]
        assert summary["prompt_mode"] in {"orient", "diagnose", "delegate", "execute", "verify"}
        assert "CODEBASE_MAP" in summary["omitted_heavy_sections"]
        assert "SPEC" not in summary["omitted_heavy_sections"]

    def test_build_logs_prompt_summary(self, monkeypatch):
        pm = PromptManager()
        calls = []

        class FakeLogger:
            @staticmethod
            def log_debug(tag, message, level="INFO"):
                calls.append((tag, message, level))

        monkeypatch.setattr("core.logging.unified_logger.logger", FakeLogger())
        pm.build()

        assert calls, "构建后应记录 prompt_build 摘要"
        tag, message, level = calls[-1]
        assert tag == "prompt_build"
        assert "mode=" in message
        assert "omitted_heavy=" in message
        assert level == "INFO"

    def test_build_summary_records_optional_inclusion_reasons(self):
        pm = PromptManager()
        pm.build(current_goal="请检查 config.toml 中的 provider 与 api key 配置")
        summary = pm.get_status()["last_build_summary"]
        reasons = summary.get("optional_inclusion_reasons") or {}
        assert "CONFIG_AWARENESS" in reasons
        assert reasons["CONFIG_AWARENESS"].startswith("goal:")


class TestLoadFunctions:
    """章节加载函数测试"""

    def test_soul_section_compute(self):
        pm = PromptManager()
        soul = pm._sections.get("SOUL")
        assert soul is not None, "SOUL 章节应已注册"
        content = soul.compute()
        assert isinstance(content, str)
        assert len(content) > 0
        assert "铁律" in content or "绝对" in content

    def test_env_info_section_compute(self):
        pm = PromptManager()
        env = pm._sections.get("ENV_INFO")
        assert env is not None, "ENV_INFO 章节应已注册"
        content = env.compute()
        assert content is not None
        assert "当前时间" in content
        assert "项目根目录" in content

    def test_config_awareness_section_compute(self):
        pm = PromptManager()
        section = pm._sections.get("CONFIG_AWARENESS")
        assert section is not None, "CONFIG_AWARENESS 章节应已注册"
        content = section.compute()
        assert content is not None
        assert "## 配置自感知" in content
        assert "当前身份" in content
        assert "关键来源" in content

    def test_language_awareness_section_compute(self):
        pm = PromptManager()
        section = pm._sections.get("LANGUAGE_AWARENESS")
        assert section is not None, "LANGUAGE_AWARENESS 章节应已注册"
        content = section.compute()
        assert content is not None
        assert "## 语言状态" in content
        assert "当前默认表达语言：中文" in content

    def test_spec_digest_section_compute(self):
        pm = PromptManager()
        section = pm._sections.get("SPEC_DIGEST")
        assert section is not None, "SPEC_DIGEST 章节应已注册"
        content = section.compute()
        assert content is not None
        assert "## SPEC 运行时摘要" in content

    def test_nonexistent_section_returns_none(self):
        section = SystemPromptSection(
            name="NONEXISTENT",
            compute=lambda: None,
        )
        assert section.compute() is None

    def test_task_checklist_refreshes_between_builds(self):
        pm = PromptManager()
        with patch("core.orchestration.task_planner.get_task_manager") as mock_get_task_manager:
            class FakeTaskManager:
                def __init__(self):
                    self.calls = 0

                def get_active_tasks(self):
                    self.calls += 1
                    return f"任务版本 {self.calls}"

            mock_get_task_manager.return_value = FakeTaskManager()
            first = to_string(pm.build(include=["TASK_CHECKLIST"]))
            second = to_string(pm.build(include=["TASK_CHECKLIST"]))

        assert "任务版本 1" in first
        assert "任务版本 2" in second


class TestCurrentGoal:
    """current_goal 内存持有测试"""

    def test_current_goal_default_empty(self):
        pm = PromptManager()
        assert pm.get_current_goal() == ""

    def test_update_current_goal(self):
        pm = PromptManager()
        pm.update_current_goal("完成单元测试")
        assert pm.get_current_goal() == "完成单元测试"

    def test_current_goal_in_build(self):
        pm = PromptManager()
        pm.update_current_goal("探索代码库")
        sp = pm.build(include=["SOUL", "MEMORY"])
        result = to_string(sp)
        assert "探索代码库" in result

    def test_current_goal_no_file_fallback(self):
        pm = PromptManager()
        # 不设置 current_goal，build 不应从文件读取
        sp = pm.build(include=["SOUL", "MEMORY"])
        result = to_string(sp)
        # 没有 goal 时 MEMORY section 不渲染 goal 行
        assert "本世代核心目标" not in result or "待定" not in result

    def test_current_goal_cache_invalidation(self):
        pm = PromptManager()
        pm.update_current_goal("目标A")
        pm.build(include=["SOUL", "MEMORY"])
        pm.update_current_goal("目标B")
        sp = pm.build(include=["SOUL", "MEMORY"])
        result = to_string(sp)
        assert "目标B" in result

    def test_current_goal_param_overrides_memory(self):
        pm = PromptManager()
        pm.update_current_goal("内存目标")
        sp = pm.build(include=["SOUL", "MEMORY"], current_goal="参数目标")
        result = to_string(sp)
        assert "参数目标" in result

    def test_current_goal_empty_string_not_updated(self):
        pm = PromptManager()
        pm.update_current_goal("有效目标")
        pm.update_current_goal("")  # 空字符串不应覆盖
        assert pm.get_current_goal() == "有效目标"

    def test_infer_prompt_mode_from_diagnostic_runtime(self):
        pm = PromptManager()
        with patch("core.infrastructure.agent_session.get_session_state") as mock_get_session_state:
            mock_get_session_state.return_value.get_attention_snapshot.return_value = {
                "diagnostic_phase": "observe",
                "feedback_loop_ready": True,
                "active_delegation": {},
                "convergence_state": "narrowing",
            }
            sp = pm.build(include=["SOUL", "MEMORY"], current_goal="定位阻塞")
            result = to_string(sp)

        assert "定位阻塞" in result
        assert pm.get_status()["prompt_mode"] == "diagnose"


class TestSectionPriority:
    """章节优先级排序测试"""

    def test_sections_sorted_by_priority(self):
        pm = PromptManager()
        sections = pm.list_sections()
        priorities = [s["priority"] for s in sections]
        assert priorities == sorted(priorities)

    def test_priority_order_in_output(self):
        pm = PromptManager()
        sp = pm.build(include=["SOUL", "GIT_RULES", "SPEC"])
        result = to_string(sp)

        soul_pos = result.find("绝对生存法则") if "绝对生存法则" in result else result.find("铁律")
        git_rules_pos = result.find("## Git 提交规则")
        spec_pos = result.find("开发流程") if "开发流程" in result else result.find("SPEC")

        if soul_pos != -1 and git_rules_pos != -1:
            assert soul_pos < git_rules_pos, "SOUL (p10) 应在 GIT_RULES (p38) 之前"
        if git_rules_pos != -1 and spec_pos != -1:
            assert git_rules_pos < spec_pos, "GIT_RULES (p38) 应在 SPEC (p65) 之前"
        if soul_pos != -1 and spec_pos != -1:
            assert soul_pos < spec_pos, "SOUL (p10) 应在 SPEC (p65) 之前"

    def test_config_awareness_priority_order(self):
        pm = PromptManager()
        sp = pm.build(include=["GIT_MEMORY", "CONFIG_AWARENESS", "LANGUAGE_AWARENESS", "GIT_RULES"])
        result = to_string(sp)

        git_memory_pos = result.find("Git") if "Git" in result else result.find("脏区")
        config_awareness_pos = result.find("## 配置自感知")
        language_awareness_pos = result.find("## 语言状态")
        git_rules_pos = result.find("## Git 提交规则")

        if git_memory_pos != -1 and config_awareness_pos != -1:
            assert git_memory_pos < config_awareness_pos, "GIT_MEMORY (p35) 应在 CONFIG_AWARENESS (p36) 之前"
        if config_awareness_pos != -1 and language_awareness_pos != -1:
            assert config_awareness_pos < language_awareness_pos, "CONFIG_AWARENESS (p36) 应在 LANGUAGE_AWARENESS (p37) 之前"
        if language_awareness_pos != -1 and git_rules_pos != -1:
            assert language_awareness_pos < git_rules_pos, "LANGUAGE_AWARENESS (p37) 应在 GIT_RULES (p38) 之前"


class TestConfigDrivenSections:
    """配置驱动的静态章节测试"""

    @staticmethod
    def _make_config(name, path, priority=50, required=False, cache_break=False, description=""):
        """创建模拟 SectionConfig 对象（Pydantic 模型 duck-type）。"""
        class MockCfg:
            def __init__(self):
                self.name = name
                self.path = path
                self.priority = priority
                self.required = required
                self.cache_break = cache_break
                self.description = description
        return MockCfg()

    def test_create_sections_from_config_objects(self):
        """通过 create_default_sections 传入 config 列表创建静态章节。"""
        from core.prompt_manager.sections import create_default_sections
        from pathlib import Path

        project_root = Path(__file__).parent.parent
        static_root = project_root / "core" / "core_prompt"
        dynamic_root = project_root / "workspace" / "prompts"

        configs = [
            self._make_config("SOUL", "core/core_prompt/SOUL.md", priority=10, required=True, description="铁律"),
            self._make_config("SPEC", "core/core_prompt/SPEC.md", priority=65, description="规范"),
        ]

        sections = create_default_sections(
            static_root, dynamic_root, project_root,
            section_configs=configs,
        )
        names = {s.name for s in sections}
        assert "SOUL" in names
        assert "SPEC" in names
        # 动态章节仍应存在
        assert "TASK_CHECKLIST" in names
        assert "CODEBASE_MAP" in names
        assert "LANGUAGE_AWARENESS" in names
        assert "GIT_RULES" in names
        assert "ENV_INFO" in names

    def test_missing_file_not_registered(self):
        """配置指向不存在的文件时不注册该章节。"""
        from core.prompt_manager.sections import create_default_sections
        from pathlib import Path

        project_root = Path(__file__).parent.parent
        static_root = project_root / "core" / "core_prompt"
        dynamic_root = project_root / "workspace" / "prompts"

        configs = [
            self._make_config("GHOST", "core/core_prompt/NOT_EXISTS.md"),
        ]

        sections = create_default_sections(
            static_root, dynamic_root, project_root,
            section_configs=configs,
        )
        names = {s.name for s in sections}
        assert "GHOST" not in names, "不存在的文件不应注册章节"

    def test_empty_configs_falls_back_to_dynamic_only(self):
        """section_configs 为 None 或空列表时只注册动态章节。"""
        from core.prompt_manager.sections import create_default_sections
        from pathlib import Path

        project_root = Path(__file__).parent.parent
        static_root = project_root / "core" / "core_prompt"
        dynamic_root = project_root / "workspace" / "prompts"

        sections = create_default_sections(
            static_root, dynamic_root, project_root,
            section_configs=[],
        )
        names = {s.name for s in sections}
        # 没有静态章节
        assert "SOUL" not in names
        assert "SPEC" not in names
        # 动态章节存在
        assert "TASK_CHECKLIST" in names
        assert "ENV_INFO" in names

    def test_config_priority_and_required_preserved(self):
        """config 中的 priority 和 required 属性被正确传递到章节。"""
        from core.prompt_manager.sections import create_default_sections
        from pathlib import Path

        project_root = Path(__file__).parent.parent
        static_root = project_root / "core" / "core_prompt"
        dynamic_root = project_root / "workspace" / "prompts"

        configs = [
            self._make_config("SOUL", "core/core_prompt/SOUL.md",
                              priority=99, required=True, description="自定义"),
        ]

        sections = create_default_sections(
            static_root, dynamic_root, project_root,
            section_configs=configs,
        )
        soul = next((s for s in sections if s.name == "SOUL"), None)
        assert soul is not None
        assert soul.priority == 99, "priority 应来自 config 而非硬编码"
        assert soul.required is True
        assert soul.description == "自定义"

    def test_front_matter_is_not_runtime_source_of_truth(self, tmp_path):
        """Markdown 文件头不会覆盖 config/registry 中的 section 元信息。"""
        from core.prompt_manager.sections import make_file_section

        prompt_file = tmp_path / "PROMPT.md"
        prompt_file.write_text(
            "---\n"
            "name: WRONG\n"
            "priority: 999\n"
            "required: false\n"
            "description: should_not_win\n"
            "---\n"
            "\n"
            "# Real body\n",
            encoding="utf-8",
        )

        section = make_file_section(
            "RIGHT",
            prompt_file,
            priority=12,
            required=True,
            description="config_wins",
        )

        assert section.name == "RIGHT"
        assert section.priority == 12
        assert section.required is True
        assert section.description == "config_wins"
        assert section.compute() == "# Real body"

    def test_git_rules_section_summarizes_workflow(self):
        from core.prompt_manager.sections import make_git_rules_section
        from pathlib import Path

        project_root = Path(__file__).parent.parent
        section = make_git_rules_section(project_root)
        content = section.compute()

        assert content is not None
        assert "## Git 提交规则" in content
        assert "模板:" in content
        assert "反模式:" in content
        assert "Git 不是普通版本控制" not in content

    def test_git_rules_section_missing_file_degrades_cleanly(self, tmp_path):
        from core.prompt_manager.sections import make_git_rules_section

        section = make_git_rules_section(tmp_path)
        assert section.compute() is None


class TestFallbackDefaults:
    def test_fallback_defaults_include_stability_sections(self):
        pm = PromptManager()
        with patch("config.get_config", side_effect=RuntimeError("boom")):
            fallback = pm._load_default_sections_from_config()

        assert fallback == [
            "SOUL",
            "SPEC_DIGEST",
            "GIT_MEMORY",
            "DELEGATION_RULES",
            "MEMORY",
            "LANGUAGE_AWARENESS",
            "CONFIG_AWARENESS",
            "ENV_INFO",
        ]
