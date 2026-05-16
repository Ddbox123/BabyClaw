# -*- coding: utf-8 -*-
"""
core/prompt_manager/prompt_manager.py — 系统提示词管理器

基于 SystemPromptSection 架构的提示词组装引擎。

职责：
- 章节注册与管理（SystemPromptSection 注册表）
- 参数驱动拼接：build(include=[...], exclude=[...])
- 章节级缓存（静态章节全会话计算一次，动态章节每轮重算）
- 单例全局访问
- 状态记忆持久化
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional, List, Dict, Any

from core.prompt_manager.types import (
    SystemPrompt,
    SystemPromptSection,
    BuildContext,
    PromptBuildResult,
    as_system_prompt,
    SYSTEM_PROMPT_DYNAMIC_BOUNDARY,
)
from core.prompt_manager.section_cache import SystemPromptCache
from core.prompt_manager.sections import (
    create_default_sections,
    make_memory_section,
    make_spec_digest_section,
)
from core.prompt_manager.builder import (
    get_system_prompt,
    to_string,
    split_sys_prompt_prefix,
)


def drop_runtime_language_constraints(summary: str) -> str:
    """运行时不再把语言偏好作为强制约束跨轮回灌。"""
    text = (summary or "").replace("\r\n", "\n")
    if not text.strip():
        return ""
    lines = text.splitlines()
    filtered: List[str] = []
    skip_language_block = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("### ") or stripped.startswith("## "):
            skip_language_block = "语言纠偏" in stripped
            if skip_language_block:
                continue
        if skip_language_block:
            continue
        if "默认回到中文" in stripped or "语言漂移" in stripped:
            continue
        filtered.append(line)
    return "\n".join(filtered).strip()


def build_state_memory_key(summary: str) -> str:
    """构建用于去噪比较的状态记忆键，忽略低价值抖动。"""
    text = drop_runtime_language_constraints(summary)
    if not text:
        return ""
    text = text.replace("\r\n", "\n")
    text = re.sub(r"已拒绝扩散：\s*\d+\s*次", "已拒绝扩散", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def build_restart_focus_state_memory(allowed_tool_names: tuple[str, ...]) -> str:
    """生成重启闭环轮次的短期状态记忆。"""
    allowed_tools = " / ".join(f"`{name}`" for name in allowed_tool_names)
    return (
        "### 重启闭环纪律\n"
        "- 当前轮处于重启测试模式；不要先调用 `get_git_status_summary_tool` 或 `get_recent_changes_tool`。\n"
        f"- 当前轮实际暴露给模型的工具只保留：{allowed_tools}。\n"
        "- 先使用任务与记忆工具完成闭环：`task_create_tool` / `task_update_tool` / `task_list_tool` / "
        "`get_current_goal_tool` / `get_core_context_tool`。\n"
        "- 一旦任务闭环已完成，立即调用 `trigger_self_restart_tool`，不要先扩散到通用代码感知。"
    )


def compose_state_memory(
    *,
    runtime_summary: str = "",
    carryover_state_memory: str = "",
    restart_focus_state_memory: str = "",
) -> str:
    """组合跨轮次约束与本轮即时约束。"""
    runtime = drop_runtime_language_constraints(runtime_summary)
    carryover = drop_runtime_language_constraints(carryover_state_memory)
    restart_focus = (restart_focus_state_memory or "").strip()

    parts: List[str] = []
    if runtime:
        parts.append(runtime)
    if restart_focus:
        parts.append(restart_focus)
    if carryover:
        parts.append(carryover)

    if not parts:
        return ""

    merged_lines: List[str] = []
    seen_bullets = set()
    for block in parts:
        for raw_line in block.splitlines():
            line = raw_line.rstrip()
            stripped = line.strip()
            if not stripped:
                if merged_lines and merged_lines[-1] != "":
                    merged_lines.append("")
                continue
            if stripped.startswith("- "):
                if stripped in seen_bullets:
                    continue
                seen_bullets.add(stripped)
            if merged_lines and merged_lines[-1] == "" and stripped.startswith("### "):
                merged_lines.pop()
            merged_lines.append(line)

    while merged_lines and merged_lines[-1] == "":
        merged_lines.pop()

    merged = "\n".join(merged_lines).strip()
    if len(merged) > 1200:
        merged = merged[:1197].rstrip() + "..."
    return merged


# ═══════════════════════════════════════════════════════════════════════════════
# 路径解析
# ═══════════════════════════════════════════════════════════════════════════════


def _get_static_root() -> Path:
    return Path(__file__).parent.parent / "core_prompt"


def _get_dynamic_root() -> Path:
    project_root = _resolve_project_root()
    return project_root / "workspace" / "prompts"


def _resolve_project_root() -> Path:
    import sys
    for name, mod in list(sys.modules.items()):
        if name == "agent" and mod and getattr(mod, '__file__', None):
            return Path(mod.__file__).parent.resolve()

    for sp in sys.path:
        p = os.path.join(sp, "agent.py")
        if os.path.exists(p):
            return Path(sp).resolve()

    return Path(__file__).parent.parent.parent.resolve()


# ═══════════════════════════════════════════════════════════════════════════════
# PromptManager
# ═══════════════════════════════════════════════════════════════════════════════


class PromptManager:
    """系统提示词管理器。

    基于 SystemPromptSection 注册表 + 章节级缓存。
    通过 build() 组装 SystemPrompt（字符串元组），
    支持 include/exclude 过滤、LLM 动态切换、状态记忆。
    """

    _DYNAMIC_FILES = {"IDENTITY.md", "USER.md", "DYNAMIC.md", "COMPRESS_SUMMARY.md"}
    _PROTECTED_FLOOR_SECTIONS = [
        "SOUL",
        "SPEC_DIGEST",
        "MEMORY",
        "GIT_MEMORY",
        "LANGUAGE_AWARENESS",
    ]
    _FALLBACK_DEFAULT_SECTIONS = [
        "SOUL",
        "SPEC_DIGEST",
        "GIT_MEMORY",
        "DELEGATION_RULES",
        "MEMORY",
        "LANGUAGE_AWARENESS",
        "CONFIG_AWARENESS",
        "ENV_INFO",
    ]
    _PREFERRED_SECTION_ORDER = [
        "SOUL",
        "TASK_CHECKLIST",
        "CODEBASE_MAP",
        "GIT_MEMORY",
        "DELEGATION_RULES",
        "CONFIG_AWARENESS",
        "LANGUAGE_AWARENESS",
        "GIT_RULES",
        "SPEC_DIGEST",
        "SPEC",
        "MEMORY",
        "ENV_INFO",
    ]
    _OPTIONAL_RELEVANCE_SECTIONS = {"ENV_INFO", "CONFIG_AWARENESS", "GIT_RULES", "SPEC"}
    _HEAVY_SECTIONS = {"CODEBASE_MAP", "SPEC", "ENV_INFO", "CONFIG_AWARENESS", "GIT_RULES"}
    _MODE_HINTS = {
        "orient": "全局定向",
        "diagnose": "诊断收束",
        "delegate": "委派验收",
        "execute": "局部执行",
        "verify": "验证收口",
    }

    def __init__(self, enable_workspace: bool = False):
        self._workspace_enabled = enable_workspace
        self._static_root = _get_static_root()
        self._dynamic_root = _get_dynamic_root()
        self._project_root = _resolve_project_root()

        if enable_workspace:
            self._dynamic_root.mkdir(parents=True, exist_ok=True)
            for fname in self._DYNAMIC_FILES:
                self._ensure_dynamic_file(fname)

        # 章节注册表
        self._sections: Dict[str, SystemPromptSection] = {}

        # 章节级缓存
        self._section_cache = SystemPromptCache()

        # 构建上下文（每轮 build 前更新，MEMORY 章节的 compute 从中读取）
        self._build_context = BuildContext()

        # 状态记忆（内存持有，按需落盘）
        self.state_memory: str = ""
        self._last_persisted_state_memory: str = ""

        # 当前目标（内存持有，每次动态生成，不从文件加载）
        self.current_goal: str = ""

        # LLM 动态覆盖
        self._active_sections_override: Optional[List[str]] = None

        # 从 config.toml 读取默认章节列表
        self._default_sections = self._load_default_sections_from_config()

        from core.logging import debug_logger
        debug_logger.info(
            f"[PromptManager] 初始化 - 静态: {self._static_root}, "
            f"workspace={'启用' if enable_workspace else '禁用'}"
        )

        # 注册默认章节（含 MEMORY，其 compute 引用 self._build_context）
        self._register_default_sections()

        if enable_workspace:
            self._load_persisted_state_memory()

        # 最近一次 build 的索引
        self._last_index: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------------
    # 章节注册
    # ------------------------------------------------------------------------

    def _register_default_sections(self):
        """注册所有默认章节。

        静态章节由 config.toml [[prompt.sections]] 驱动；
        动态章节（TASK_CHECKLIST、CODEBASE_MAP、ENV_INFO 等）由代码内置注册。
        """
        # 从 config 读取静态章节定义
        try:
            from config import get_config
            section_configs = get_config().prompt.sections
        except Exception:
            section_configs = []

        sections = create_default_sections(
            self._static_root,
            self._dynamic_root,
            self._project_root,
            enable_workspace=self._workspace_enabled,
            section_configs=section_configs,
        )
        for s in sections:
            self._sections[s.name] = s

        self._sections["SPEC_DIGEST"] = make_spec_digest_section(self._build_context)
        # MEMORY 章节：compute 引用 self._build_context
        self._sections["MEMORY"] = make_memory_section(self._build_context)

        from core.logging import debug_logger
        debug_logger.debug(
            f"[PromptManager] 注册默认章节: {list(self._sections.keys())}"
        )

    def register(self, section: SystemPromptSection):
        """注册或覆盖一个章节。"""
        self._sections[section.name] = section
        self._section_cache.invalidate(section.name)
        from core.logging import debug_logger
        debug_logger.debug(
            f"[PromptManager] 注册章节: {section.name} "
            f"(priority={section.priority}, cache_break={section.cache_break})"
        )

    def unregister(self, name: str):
        """取消注册一个章节。"""
        if name in self._sections:
            del self._sections[name]
            self._section_cache.invalidate(name)

    # ------------------------------------------------------------------------
    # build() — 核心组装入口
    # ------------------------------------------------------------------------

    def build(
        self,
        include: Optional[List[str]] = None,
        exclude: Optional[List[str]] = None,
        core_context: Optional[str] = None,
        current_goal: Optional[str] = None,
        state_memory: Optional[str] = None,
    ) -> SystemPrompt:
        """组装系统提示词。

        Args:
            include: 只包含这些章节（None 时使用默认列表或 override）。
            exclude: 排除这些章节（required=True 的无法排除）。
            core_context: 核心记忆。
            current_goal: 当前目标。
            state_memory: 状态记忆（None 时使用 self.state_memory）。

        Returns:
            SystemPrompt — 不可变字符串元组。
        """
        # 更新构建上下文（MEMORY 章节的 compute 从中读取）
        effective_state_memory = (
            state_memory if state_memory is not None else self.state_memory
        )
        effective_current_goal = (
            current_goal if current_goal is not None else self.current_goal
        )
        self._build_context.core_context = core_context
        self._build_context.current_goal = effective_current_goal
        self._build_context.state_memory = effective_state_memory
        self._build_context.prompt_mode = self._infer_prompt_mode()

        # 筛选章节
        selected = self._select_sections(include, exclude)

        # 组装
        all_ordered_sections = self._order_sections(list(self._sections.values()))
        build_result = get_system_prompt(
            selected,
            self._section_cache,
            all_sections=all_ordered_sections,
        )
        sp = build_result.prompt

        # 记录索引（复用本次真实构建结果，避免二次 compute）
        self._last_index = [
            {
                "name": result.name,
                "length": len(result.content or ""),
                "cache_break": result.cache_break,
                "required": result.required,
                "is_empty": result.is_empty,
            }
            for result in build_result.section_results
        ]
        self._last_build_summary = self._build_summary(
            selected=selected,
            all_sections=all_ordered_sections,
            build_result=build_result,
        )

        from core.logging import debug_logger
        debug_logger.info(
            f"[PromptManager] 构建完成 (sections={len(selected)}, "
            f"len={len(to_string(sp))}, "
            f"cache={self._section_cache.stats})"
        )
        self._log_build_summary()
        return sp

    def _select_sections(
        self,
        include: Optional[List[str]],
        exclude: Optional[List[str]],
    ) -> List[SystemPromptSection]:
        """根据 include/exclude 规则选择章节。

        优先级：
        1. include 非空 → 直接使用（参数优先）
        2. _active_sections_override 非空 → 使用 override（LLM 标签驱动）
        3. 使用 _default_sections
        """
        if include is not None:
            effective_include = include
        elif self._active_sections_override is not None:
            effective_include = self._active_sections_override
        else:
            effective_include = self._default_sections

        all_sections = list(self._sections.values())

        if effective_include != ["*"]:
            names = set(effective_include)
            all_sections = [s for s in all_sections if s.name in names]

        if exclude is not None:
            excluded = set(exclude)
            all_sections = [
                s for s in all_sections
                if s.name not in excluded or s.required
            ]

        all_sections = self._apply_protected_floor(
            all_sections,
            exclude=exclude,
        )
        ordered = self._order_sections(all_sections)
        return self._prune_optional_sections(
            ordered,
            include=include,
            active_override=self._active_sections_override if include is None else None,
        )

    def _apply_protected_floor(
        self,
        sections: List[SystemPromptSection],
        exclude: Optional[List[str]],
    ) -> List[SystemPromptSection]:
        floor_excluded = set(exclude or [])
        section_map = {s.name: s for s in sections}
        for name in self._PROTECTED_FLOOR_SECTIONS:
            if name in floor_excluded:
                continue
            if name not in section_map and name in self._sections:
                section_map[name] = self._sections[name]
        return list(section_map.values())

    def _order_sections(self, sections: List[SystemPromptSection]) -> List[SystemPromptSection]:
        order_map = {name: idx for idx, name in enumerate(self._PREFERRED_SECTION_ORDER)}
        return sorted(
            sections,
            key=lambda s: (order_map.get(s.name, len(order_map)), s.priority, s.name),
        )

    def _prune_optional_sections(
        self,
        sections: List[SystemPromptSection],
        include: Optional[List[str]],
        active_override: Optional[List[str]],
    ) -> List[SystemPromptSection]:
        """按当前任务相关性裁剪高噪声可选 section。"""
        explicit_names = set(include or active_override or [])
        pruned: List[SystemPromptSection] = []
        for section in sections:
            if section.name not in (self._OPTIONAL_RELEVANCE_SECTIONS | {"CODEBASE_MAP"}):
                pruned.append(section)
                continue
            if section.name in explicit_names:
                pruned.append(section)
                continue
            if self._is_optional_section_relevant(section.name):
                pruned.append(section)
        return pruned

    def _is_optional_section_relevant(self, section_name: str) -> bool:
        goal = (self._build_context.current_goal or "").lower()
        core_context = (self._build_context.core_context or "").lower()
        state_memory = (self._build_context.state_memory or "").lower()
        prompt_mode = (self._build_context.prompt_mode or "orient").lower()
        full_context = "\n".join(part for part in [goal, core_context, state_memory] if part)
        focused_context = "\n".join(part for part in [goal, core_context] if part)

        if section_name == "CODEBASE_MAP":
            if self._is_readonly_log_diagnosis(prompt_mode, goal, core_context):
                try:
                    from core.infrastructure.agent_session import get_session_state
                    snapshot = get_session_state().get_attention_snapshot()
                    modified_paths = snapshot.get("modified_paths") or []
                    if len(modified_paths) >= 3:
                        return True
                except Exception:
                    return False
                return False
            map_keywords = (
                "架构", "全局", "整体", "全貌", "目录", "模块", "调用链", "链路", "结构",
                "入口", "影响面", "地图", "map", "codebase", "slim", "refactor", "重构",
                "orchestration", "prompt", "section", "拼接",
            )
            if any(keyword in full_context for keyword in map_keywords):
                return True
            try:
                from core.infrastructure.agent_session import get_session_state
                snapshot = get_session_state().get_attention_snapshot()
                modified_paths = snapshot.get("modified_paths") or []
                if len(modified_paths) >= 3:
                    return True
                if snapshot.get("active_delegation"):
                    return True
            except Exception:
                return False
            return False

        if section_name == "SPEC":
            if self._is_readonly_log_diagnosis(prompt_mode, goal, core_context):
                return False
            if prompt_mode == "orient":
                return True
            spec_keywords = (
                "spec", "规范", "规则", "提示词", "prompt", "section", "拼接",
                "core first", "提交规范", "git 提交规范", "运行时摘要",
            )
            if self._context_has_keywords(focused_context, spec_keywords):
                return True
            try:
                from core.infrastructure.agent_session import get_session_state
                snapshot = get_session_state().get_attention_snapshot()
                modified_paths = [str(path) for path in (snapshot.get("modified_paths") or [])]
                if any(
                    path.endswith("agent.py")
                    or "core/prompt_manager" in path.replace("\\", "/")
                    or path.replace("\\", "/").endswith("core/core_prompt/SPEC.md")
                    for path in modified_paths
                ):
                    return True
            except Exception:
                return False
            return False

        if section_name == "ENV_INFO":
            env_keywords = (
                "环境", "os", "系统", "python 版本", "解释器", "venv",
                "编码", "端口", "localhost", "环境变量", "依赖",
            )
            return self._context_has_keywords(focused_context, env_keywords)

        if section_name == "CONFIG_AWARENESS":
            config_keywords = ("config", "配置", "provider", "model", "api", "api key", "api_key", "profile", "key", "llm.local", "本地模型")
            focused_hit = self._context_has_keywords(focused_context, config_keywords)
            if focused_hit:
                return True
            try:
                from config import get_config
                diagnosis = get_config().diagnose_config()
                warnings = diagnosis.get("warnings") or []
                blocking_issues = diagnosis.get("blocking_issues") or []
                filtered_blockers = [
                    issue for issue in blocking_issues
                    if "缺少可用 API Key" not in str(issue)
                ]
                # 配置告警只在诊断/定向配置问题时作为辅助面，而不是默认常驻。
                if prompt_mode in {"diagnose", "verify"} and focused_hit:
                    return bool(warnings or filtered_blockers)
                return False
            except Exception:
                return False

        if section_name == "GIT_RULES":
            if self._is_readonly_log_diagnosis(prompt_mode, goal, core_context):
                try:
                    from core.infrastructure.agent_session import get_session_state
                    snapshot = get_session_state().get_attention_snapshot()
                    modified_paths = snapshot.get("modified_paths") or []
                    if modified_paths or snapshot.get("active_evolution_txn_id") or snapshot.get("dirty_since"):
                        return True
                except Exception:
                    return False
                return False
            git_keywords = ("git", "commit", "提交", "回滚", "diff", "worktree", "事务", "transaction", "重启")
            if self._context_has_keywords(focused_context, git_keywords):
                return True
            try:
                from core.infrastructure.agent_session import get_session_state
                snapshot = get_session_state().get_attention_snapshot()
                modified_paths = snapshot.get("modified_paths") or []
                return bool(
                    modified_paths
                    or snapshot.get("active_evolution_txn_id")
                    or snapshot.get("dirty_since")
                )
            except Exception:
                return False

        return True

    def _optional_section_reason(self, section_name: str) -> Optional[str]:
        goal = (self._build_context.current_goal or "").lower()
        core_context = (self._build_context.core_context or "").lower()
        prompt_mode = (self._build_context.prompt_mode or "orient").lower()

        if self._is_readonly_log_diagnosis(prompt_mode, goal, core_context):
            if section_name in {"GIT_RULES", "SPEC", "CODEBASE_MAP"}:
                return None

        if section_name == "ENV_INFO":
            keywords = (
                "环境", "os", "系统", "python 版本", "解释器", "venv",
                "编码", "端口", "localhost", "环境变量", "依赖",
            )
            for source_name, text in (("goal", goal), ("core", core_context)):
                matched = self._matching_keywords(text, keywords)
                if matched:
                    return f"{source_name}:{'/'.join(matched[:2])}"
            return None

        if section_name == "CONFIG_AWARENESS":
            keywords = ("config", "配置", "provider", "model", "api", "api key", "api_key", "profile", "key", "llm.local", "本地模型")
            for source_name, text in (("goal", goal), ("core", core_context)):
                matched = self._matching_keywords(text, keywords)
                if matched:
                    return f"{source_name}:{'/'.join(matched[:2])}"
            if prompt_mode in {"diagnose", "verify"}:
                return f"{prompt_mode}:diagnosis"
            return None

        if section_name in {"GIT_RULES", "SPEC", "CODEBASE_MAP"}:
            if section_name == "SPEC" and prompt_mode == "orient":
                return "orient:discipline"
            return "runtime:relevance"

        return None

    @staticmethod
    def _is_readonly_log_diagnosis(prompt_mode: str, goal: str, core_context: str) -> bool:
        text = "\n".join(part for part in [goal or "", core_context or ""] if part).lower()
        if "log_info" not in text:
            return False
        if "conversation_" not in text and "debug_" not in text:
            return False
        readonly_markers = (
            "只做诊断",
            "只做分析",
            "只读",
            "不要修改代码",
            "不要改代码",
            "不修改代码",
            "read-only",
            "do not modify code",
        )
        negated_mutation_markers = (
            "不要修改代码",
            "不要改代码",
            "不修改代码",
            "do not modify code",
        )
        mutate_markers = (
            "修改代码",
            "修复代码",
            "落地修复",
            "实现修复",
            "apply patch",
            "提交",
            "commit",
        )
        has_readonly = any(marker in text for marker in readonly_markers)
        mutation_text = text
        for marker in negated_mutation_markers:
            mutation_text = mutation_text.replace(marker, "")
        has_mutation = any(marker in mutation_text for marker in mutate_markers)
        return has_readonly and not has_mutation

    @staticmethod
    def _matching_keywords(text: str, keywords: tuple[str, ...]) -> List[str]:
        matched: List[str] = []
        lowered = (text or "").lower()
        for keyword in keywords:
            candidate = keyword.lower()
            if re.fullmatch(r"[a-z0-9_ .:+/-]+", candidate):
                pattern = rf"(?<![a-z0-9_]){re.escape(candidate)}(?![a-z0-9_])"
                if re.search(pattern, lowered):
                    matched.append(keyword)
            elif candidate in lowered:
                matched.append(keyword)
        return matched

    @classmethod
    def _context_has_keywords(cls, text: str, keywords: tuple[str, ...]) -> bool:
        return bool(cls._matching_keywords(text, keywords))

    def _infer_prompt_mode(self) -> str:
        """基于当前会话状态推断本轮提示词工作模式。"""
        try:
            from core.infrastructure.agent_session import get_session_state
            snapshot = get_session_state().get_attention_snapshot()
        except Exception:
            snapshot = {}

        if snapshot.get("active_delegation"):
            return "delegate"

        diagnostic_phase = str(snapshot.get("diagnostic_phase") or "idle")
        if snapshot.get("feedback_loop_ready") or diagnostic_phase in {"build_loop", "reproduce", "observe", "inspect", "infer"}:
            return "diagnose"

        convergence_state = str(snapshot.get("convergence_state") or "open")
        if convergence_state in {"ready_to_verify"} or snapshot.get("last_validation_summary"):
            return "verify"

        if (
            snapshot.get("scope_frozen")
            or convergence_state in {"ready_to_fix", "ready_to_stop"}
            or snapshot.get("active_evolution_txn_id")
            or (snapshot.get("modified_paths") or [])
        ):
            return "execute"

        return "orient"

    def _build_summary(
        self,
        *,
        selected: List[SystemPromptSection],
        all_sections: List[SystemPromptSection],
        build_result: PromptBuildResult,
    ) -> Dict[str, Any]:
        selected_names = [section.name for section in selected]
        rendered_names = [result.name for result in build_result.section_results if not result.is_empty]
        omitted_names = [section.name for section in all_sections if section.name not in selected_names]
        omitted_heavy = [name for name in omitted_names if name in self._HEAVY_SECTIONS]
        dynamic_names = [result.name for result in build_result.section_results if result.cache_break and not result.is_empty]
        inclusion_reasons = {
            name: reason
            for name in rendered_names
            if name in self._OPTIONAL_RELEVANCE_SECTIONS or name == "CODEBASE_MAP"
            for reason in [self._optional_section_reason(name)]
            if reason
        }
        return {
            "prompt_mode": self._build_context.prompt_mode,
            "selected_sections": selected_names,
            "rendered_sections": rendered_names,
            "omitted_sections": omitted_names,
            "omitted_heavy_sections": omitted_heavy,
            "dynamic_sections": dynamic_names,
            "optional_inclusion_reasons": inclusion_reasons,
            "content_length": len(to_string(build_result.prompt)),
        }

    def _log_build_summary(self):
        summary = getattr(self, "_last_build_summary", None) or {}
        if not summary:
            return
        message = (
            f"mode={summary.get('prompt_mode', 'unknown')} "
            f"len={summary.get('content_length', 0)} "
            f"rendered={','.join(summary.get('rendered_sections', [])) or '-'} "
            f"omitted_heavy={','.join(summary.get('omitted_heavy_sections', [])) or '-'}"
        )
        inclusion_reasons = summary.get("optional_inclusion_reasons") or {}
        if inclusion_reasons:
            reason_text = ",".join(f"{name}:{reason}" for name, reason in inclusion_reasons.items())
            message += f" reasons={reason_text}"
        try:
            from core.logging.unified_logger import logger as unified_logger
            unified_logger.log_debug("prompt_build", message, level="INFO")
        except Exception:
            pass
        try:
            from core.logging import debug_logger
            debug_logger.info(f"[prompt_build] {message}")
        except Exception:
            pass

    # ------------------------------------------------------------------------
    # LLM 动态章节切换
    # ------------------------------------------------------------------------

    def select_components(self, components: List[str]):
        """由 LLM 通过 <active_components> 标签调用，动态切换章节。

        Args:
            components: 要激活的章节名称列表，如 ["SOUL", "SPEC", "MEMORY"]
        """
        if not components:
            from core.logging import debug_logger
            debug_logger.debug("[PromptManager] select_components 收到空列表，重置为默认")
            self._active_sections_override = None
            return

        known = [c for c in components if c in self._sections]
        if known:
            self._active_sections_override = known
            from core.logging import debug_logger
            debug_logger.info(f"[PromptManager] 动态切换章节: {known}")
        else:
            from core.logging import debug_logger
            debug_logger.warning(
                f"[PromptManager] 未知章节: {components}，保持当前不变"
            )

    # ------------------------------------------------------------------------
    # 状态记忆
    # ------------------------------------------------------------------------

    def update_current_goal(self, goal: str):
        """更新当前目标（仅内存，不落盘），触发缓存失效。

        与 state_memory 不同，current_goal 不持久化到文件——
        每次 Agent 苏醒时由 LLM 动态决定，仅存于内存中。
        """
        if not goal or not goal.strip():
            return

        self.current_goal = goal
        self._section_cache.invalidate("MEMORY")
        from core.logging import debug_logger
        debug_logger.debug(
            f"[PromptManager] current_goal 更新: {goal[:80]}"
        )

    def get_current_goal(self) -> str:
        """获取当前目标（内存值）。"""
        return self.current_goal

    def update_state_memory(self, memory_text: str, persist: bool = True):
        """更新状态记忆（内存即时更新，按需落盘），触发缓存失效。"""
        if not memory_text or not memory_text.strip():
            return
        normalized = memory_text.strip()
        current = (self.state_memory or "").strip()
        changed = normalized != current

        if changed:
            self.state_memory = normalized
            self._section_cache.invalidate("MEMORY")
            from core.logging import debug_logger
            debug_logger.debug(
                f"[PromptManager] state_memory 更新，长度={len(normalized)}"
            )

        if persist and self._last_persisted_state_memory != normalized:
            self._persist_state_memory(normalized)
            self._last_persisted_state_memory = normalized

    def clear_state_memory(self, persist: bool = True):
        """清空短期状态记忆（内存即时清空，按需落盘），触发缓存失效。"""
        if not self.state_memory:
            if persist and self._last_persisted_state_memory:
                try:
                    state_memory_path = self._dynamic_root / "STATE_MEMORY.md"
                    state_memory_path.write_text("", encoding="utf-8")
                except Exception:
                    pass
                self._last_persisted_state_memory = ""
            return
        self.state_memory = ""
        self._section_cache.invalidate("MEMORY")
        if persist:
            try:
                state_memory_path = self._dynamic_root / "STATE_MEMORY.md"
                state_memory_path.write_text("", encoding="utf-8")
            except Exception:
                pass
            self._last_persisted_state_memory = ""

    def _persist_state_memory(self, memory_text: str):
        try:
            state_memory_path = self._dynamic_root / "STATE_MEMORY.md"
            state_memory_path.write_text(memory_text, encoding="utf-8")
            from core.logging import debug_logger
            debug_logger.info(f"[PromptManager] state_memory 已落盘: {state_memory_path}")
        except Exception as e:
            from core.logging import debug_logger
            debug_logger.warning(f"[PromptManager] state_memory 落盘失败: {e}")

    def _load_persisted_state_memory(self):
        try:
            state_memory_path = self._dynamic_root / "STATE_MEMORY.md"
            if state_memory_path.exists():
                content = state_memory_path.read_text(encoding="utf-8").strip()
                match = re.match(r'^---\s*\n.*?\n---(\n)?', content, re.DOTALL)
                if match:
                    content = content[match.end():].strip()
                if content:
                    self.state_memory = content
                    self._last_persisted_state_memory = content
                    from core.logging import debug_logger
                    debug_logger.info(
                        f"[PromptManager] 从会话恢复 state_memory，长度={len(content)}"
                    )
        except Exception as e:
            from core.logging import debug_logger
            debug_logger.warning(f"[PromptManager] 恢复 state_memory 失败: {e}")

    # ------------------------------------------------------------------------
    # 默认配置
    # ------------------------------------------------------------------------

    def _load_default_sections_from_config(self) -> List[str]:
        try:
            from config import get_config
            components = get_config().prompt.default_components
            if components:
                from core.logging import debug_logger
                debug_logger.info(f"[PromptManager] 从 config 加载默认章节: {components}")
                return components
        except Exception:
            pass
        return list(self._FALLBACK_DEFAULT_SECTIONS)

    # ------------------------------------------------------------------------
    # Workspace 文件管理
    # ------------------------------------------------------------------------

    def _ensure_dynamic_file(self, name: str) -> bool:
        path = self._dynamic_root / name
        if path.exists():
            return True

        default_content = self._get_default_template(name)
        if default_content is None:
            return True

        try:
            path.write_text(default_content, encoding="utf-8")
            from core.logging import debug_logger
            debug_logger.info(f"[PromptManager] 自动生成默认模板: workspace/prompts/{name}")
            return False
        except Exception as e:
            from core.logging import debug_logger
            debug_logger.warning(f"[PromptManager] 生成 {name} 失败: {e}")
            return False

    def _get_default_template(self, name: str) -> Optional[str]:
        # 这些模板头部只用于文件自描述；运行时 section 元信息仍以 config/registry 为准。
        templates = {
            "DYNAMIC.md": (
                "---\nname: DYNAMIC\npriority: 40\nrequired: false\n"
                "description: 动态提示词区域，由 Agent 在每个世代开始时动态生成\n---\n"
            ),
            "COMPRESS_SUMMARY.md": (
                "---\nname: MEMORY\npriority: 80\nrequired: false\n"
                "description: 上下文压缩摘要，记录历史对话中的关键信息和结论\n---\n"
            ),
            "IDENTITY.md": (
                "---\nname: IDENTITY\npriority: 50\nrequired: false\n"
                "description: Agent 身份定义，由 Agent 运行时自行维护\n---\n"
            ),
            "USER.md": (
                "---\nname: USER\npriority: 70\nrequired: false\n"
                "description: 外部宿主环境与交互偏好，由 Agent 运行时自行维护\n---\n"
            ),
        }
        return templates.get(name)

    # ------------------------------------------------------------------------
    # 缓存管理
    # ------------------------------------------------------------------------

    def invalidate_cache(self, name: Optional[str] = None):
        """清除章节缓存。name 为 None 则清除全部。"""
        self._section_cache.invalidate(name)
        from core.logging import debug_logger
        debug_logger.debug(
            f"[PromptManager] 清除缓存: {name or '全部'}"
        )

    def get_cache_stats(self) -> Dict[str, Any]:
        return self._section_cache.stats

    def _render_subagent_language_awareness(self) -> str:
        """复用主 agent 的语言习惯提示词，避免子 agent 语言规则漂移。"""
        section = self._sections.get("LANGUAGE_AWARENESS")
        if section is None:
            return ""
        try:
            return (section.compute() or "").strip()
        except Exception:
            return ""

    def build_subagent_prompt(
        self,
        *,
        task_type: str,
        goal: str,
        scope: Any = None,
        constraints: Optional[Dict[str, Any]] = None,
        deliverables: Optional[List[str]] = None,
        context_pack: Optional[str] = None,
    ) -> str:
        """构建子 agent 的瘦提示词。"""
        from core.orchestration.subagent_roles import get_subagent_role_spec

        constraints = dict(constraints or {})
        deliverables = list(deliverables or [])

        scope_lines: List[str] = []
        if isinstance(scope, dict):
            for key in sorted(scope.keys()):
                value = scope.get(key)
                if value in (None, "", [], {}):
                    continue
                scope_lines.append(f"- {key}: {value}")
        elif isinstance(scope, (list, tuple, set)):
            for item in scope:
                text = str(item).strip()
                if text:
                    scope_lines.append(f"- {text}")
        elif scope:
            scope_lines.append(f"- {scope}")

        deliverable_lines = deliverables or [
            "status",
            "summary",
            "findings",
            "evidence",
            "recommended_next_action",
            "confidence",
        ]
        example_lines: List[str] = []
        for name in deliverable_lines:
            if name in {"findings", "evidence"}:
                example_lines.append(f'  "{name}": [""]')
            else:
                example_lines.append(f'  "{name}": ""')

        max_steps = constraints.get("max_steps", 6)
        max_output_chars = constraints.get("max_output_chars", 4000)
        stop_rule = constraints.get(
            "stop_rule",
            "证据已足够时立即停止；若证据不足，明确返回缺口，不扩散任务。",
        )
        role_spec = get_subagent_role_spec(task_type or "inspect")
        language_awareness = self._render_subagent_language_awareness()

        parts = [
            "## 子 Agent 基座",
            "- 你是只读专项分析子 agent。",
            "- 你只允许以 `diagnose` / `inspect` / `summarize` 三种固定模式工作。",
            f"- 你的当前系统角色: {role_spec.role_name}。",
            f"- 你的存在目的: {role_spec.system_purpose}",
            "- 你不做最终裁决。",
            "- 你不写文件、不改 prompt、不改 memory、不做 git 操作。",
            "- 你绝不能继续派发新的 agent；证据不足时直接返回缺口，由主 agent 接管。",
            "- 你只在给定 scope 内行动，不扩散任务。",
            "- 只读模式下不要尝试 `cli_tool`、shell、`git diff`、`pytest`、`head` 等命令链路。",
            "- 优先使用结构化只读工具：read/search/entity/log/context 类工具。",
            "- 若 `read_file_tool` 返回续读提示，必须严格按提示的下一个 offset 顺序继续，禁止跳读。",
            "- 你负责的工作:",
            f"  - {role_spec.owned_work[0]}",
            f"  - {role_spec.owned_work[1]}",
            "- 你不负责的工作:",
            f"  - {role_spec.forbidden_work[0]}",
            f"  - {role_spec.forbidden_work[1]}",
            "",
        ]
        if language_awareness:
            parts.extend([language_awareness, ""])
        parts.extend([
            "## 主 Agent 任务指令",
            f"- 当前唯一目标: {(goal or '').strip()}",
            f"- 当前任务类型: {(task_type or 'inspect').strip()}",
            f"- 最大步数: {max_steps}",
            f"- 最大输出长度: {max_output_chars} 字符",
            "- 停止条件:",
            f"  - {stop_rule}",
        ])
        if scope_lines:
            parts.append("- 当前 scope:")
            parts.extend(f"  {line}" for line in scope_lines)
        if context_pack:
            parts.extend(["", "## 最小上下文", context_pack.strip()])
        parts.extend([
            "",
            "## 输出要求",
            "- 只返回一个 JSON 对象，不要附加解释性前后文。",
            "- 若证据不足，仍返回结构化 JSON，并在 findings/evidence 中说明缺口。",
            f"- 输出形态: {role_spec.return_shape}",
            "- JSON 模板:",
            "{",
            ",\n".join(example_lines),
            "}",
        ])
        return "\n".join(parts).strip()

    # ------------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        return {
            "static_root": str(self._static_root),
            "dynamic_root": str(self._dynamic_root),
            "registered_sections": list(self._sections.keys()),
            "state_memory_length": len(self.state_memory) if self.state_memory else 0,
            "current_goal": self.current_goal,
            "prompt_mode": self._build_context.prompt_mode,
            "prompt_mode_label": self._MODE_HINTS.get(self._build_context.prompt_mode, self._build_context.prompt_mode),
            "active_sections_override": self._active_sections_override,
            "section_cache": self._section_cache.stats,
            "last_index": self._last_index,
            "last_build_summary": getattr(self, "_last_build_summary", {}),
        }

    def list_sections(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": s.name,
                "description": s.description,
                "priority": s.priority,
                "required": s.required,
                "cache_break": s.cache_break,
                "is_empty": s.is_empty,
            }
            for s in sorted(self._sections.values(), key=lambda x: x.priority)
        ]

    def get_last_index(self) -> List[Dict[str, Any]]:
        """返回最近一次 build() 的章节索引。"""
        return self._last_index


# ═══════════════════════════════════════════════════════════════════════════════
# 全局单例
# ═══════════════════════════════════════════════════════════════════════════════

_prompt_manager: Optional[PromptManager] = None


def get_prompt_manager() -> PromptManager:
    global _prompt_manager
    if _prompt_manager is None:
        _prompt_manager = PromptManager()
    return _prompt_manager


# ═══════════════════════════════════════════════════════════════════════════════
# 便捷函数（向后兼容）
# ═══════════════════════════════════════════════════════════════════════════════


def build_system_prompt(
    core_context: Optional[str] = None,
    current_goal: Optional[str] = None,
) -> str:
    """构建系统提示词字符串（向后兼容）。"""
    sp = get_prompt_manager().build(
        core_context=core_context,
        current_goal=current_goal,
    )
    return to_string(sp)


def build_simple_system_prompt() -> str:
    """简化版系统提示词（向后兼容）。"""
    return build_system_prompt(
        core_context="",
        current_goal="",
    )
