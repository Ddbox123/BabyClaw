# -*- coding: utf-8 -*-
"""系统提示词章节工厂函数

为每个提示词章节提供工厂函数，返回 SystemPromptSection。
静态章节 cache_break=False（全会话计算一次），
动态章节 cache_break=True（每轮重新计算）。
"""

from __future__ import annotations

import re
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List

from core.prompt_manager.types import SystemPromptSection, BuildContext


_FRONT_MATTER_RE = re.compile(r'^---\s*\n.*?\n---(\n)?', re.DOTALL)


def _strip_front_matter(content: str) -> str:
    """移除 Markdown front matter。

    注意：
    - section 的运行时元信息（name/priority/required/description）只来自
      config/registry；
    - 文件头 front matter 仅视为可选文件注释，不参与 section 注册决策。
    """
    match = _FRONT_MATTER_RE.match(content)
    return content[match.end():].strip() if match else content.strip()


def _build_git_rules_summary(content: str) -> Optional[str]:
    """从 Git 工作流文档提取精简运行时摘要。"""
    body = _strip_front_matter(content)
    if not body:
        return None

    section_map = {
        "## 提交模板": "模板",
        "## 拆提交规则": "拆分",
        "## 高风险改动": "高风险",
        "## 反模式": "反模式",
    }
    wanted = list(section_map.keys())
    current: Optional[str] = None
    buckets: Dict[str, List[str]] = {key: [] for key in wanted}

    for raw_line in body.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped in section_map:
            current = stripped
            continue
        if stripped.startswith("## "):
            current = None
            continue
        if not current or not stripped:
            continue
        if stripped.startswith(("- ", "* ", "`")) and len(buckets[current]) < 4:
            buckets[current].append(stripped)

    lines = ["## Git 提交规则"]
    for heading in wanted:
        items = buckets.get(heading) or []
        if items:
            lines.append(f"- {section_map[heading]}:")
            for item in items:
                prefix = item[2:] if item.startswith(("- ", "* ")) else item
                lines.append(f"  - {prefix}")

    return "\n".join(lines) if len(lines) > 1 else None


# ═══════════════════════════════════════════════════════════════════════════════
# 通用文件章节工厂
# ═══════════════════════════════════════════════════════════════════════════════


def make_file_section(
    name: str,
    path: Path,
    priority: int = 50,
    cache_break: bool = False,
    description: str = "",
    required: bool = False,
) -> SystemPromptSection:
    """从 Markdown 文件创建章节。

    文件正文会剥离 front matter 后再注入 prompt，避免把文件注释误当成
    section 运行时元信息。
    """

    # 仅静态文件章节在注册时预估空态；动态章节避免固化陈旧 empty 元信息
    empty = False if cache_break else True
    if not cache_break and path.exists():
        try:
            raw = path.read_text(encoding="utf-8")
            body = _strip_front_matter(raw)
            empty = not bool(body)
        except Exception:
            empty = True

    def compute() -> Optional[str]:
        if not path.exists():
            return None
        try:
            content = _strip_front_matter(path.read_text(encoding="utf-8"))
            return content or None
        except Exception:
            return None

    return SystemPromptSection(
        name=name,
        compute=compute,
        cache_break=cache_break,
        priority=priority,
        description=description,
        required=required,
        is_empty=empty,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 静态章节工厂（cache_break=False）
# ═══════════════════════════════════════════════════════════════════════════════


def make_task_checklist_section() -> SystemPromptSection:
    """任务清单 — 从 TaskManager 动态加载。"""

    def compute() -> Optional[str]:
        try:
            from core.orchestration.task_planner import get_task_manager
            tm = get_task_manager()
            return tm.get_active_tasks() or None
        except Exception:
            return None

    return SystemPromptSection(
        name="TASK_CHECKLIST",
        compute=compute,
        cache_break=True,
        priority=20,
        description="当前激活的任务清单",
    )


def make_codebase_map_section() -> SystemPromptSection:
    """代码库认知地图 — 读取缓存文件（由 ToolExecutor 钩子自动更新）。"""

    def compute() -> Optional[str]:
        try:
            from core.prompt_manager.codebase_map_builder import get_codebase_map
            return get_codebase_map(force_refresh=False) or None
        except Exception:
            return None

    return SystemPromptSection(
        name="CODEBASE_MAP",
        compute=compute,
        cache_break=False,
        priority=30,
        description="代码库结构认知地图（自动更新）",
    )


def make_tools_index_section(project_root: Path) -> SystemPromptSection:
    """工具索引 — 从 Key_Tools.create_key_tools() 动态提取已注册工具。"""

    def compute() -> Optional[str]:
        try:
            from tools.Key_Tools import create_key_tools
            tools = create_key_tools()
            if not tools:
                return None
            lines = ["## 工具索引", f"共 {len(tools)} 个已注册工具：", ""]
            for t in tools:
                desc = getattr(t, 'description', '') or ''
                first_line = desc.strip().split('\n')[0].strip()
                if first_line:
                    lines.append(f"- `{t.name}`: {first_line}")
                else:
                    lines.append(f"- `{t.name}`")
            return "\n".join(lines)
        except Exception:
            return None

    return SystemPromptSection(
        name="TOOLS_INDEX",
        compute=compute,
        cache_break=False,
        priority=90,
        description="已注册工具索引（动态生成）",
    )


def make_git_rules_section(project_root: Path) -> SystemPromptSection:
    """Git 提交规则摘要 — 从工作流文档提炼运行时提醒。"""
    workflow_path = project_root / "workspace" / "prompts" / "GIT_WORKFLOW.md"

    def compute() -> Optional[str]:
        if not workflow_path.exists():
            return None
        try:
            return _build_git_rules_summary(workflow_path.read_text(encoding="utf-8"))
        except Exception:
            return None

    is_empty = True
    if workflow_path.exists():
        try:
            is_empty = not bool(_build_git_rules_summary(workflow_path.read_text(encoding="utf-8")))
        except Exception:
            is_empty = True

    return SystemPromptSection(
        name="GIT_RULES",
        compute=compute,
        cache_break=False,
        priority=38,
        description="Git 提交纪律摘要（从工作流文档提炼）",
        is_empty=is_empty,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 动态章节工厂（cache_break=True）
# ═══════════════════════════════════════════════════════════════════════════════


def make_env_info_section(project_root: Path) -> SystemPromptSection:
    """环境信息 — 时间以 5 分钟粒度稳定，保持缓存友好。"""

    def command_discipline(os_name: str) -> List[str]:
        if os_name == "Windows":
            return [
                "- 命令平台纪律: 当前是 Windows，生成命令前先确认 PowerShell/cmd 兼容性。",
                "- 不要直接执行 Unix shell 片段：`/dev/null`、`tail/head`、`grep -n/-e`、`xargs`、`$(pwd)`。",
                "- 需要等价能力时改用 PowerShell：`2>$null`、`Select-Object -First/-Last`、`Select-String`、`Get-Location`。",
                "- 读文件/搜索优先结构化工具；不要用带 Unix 管道的 `cli_tool` 试探。",
            ]
        if os_name in {"Linux", "macOS"}:
            return [
                f"- 命令平台纪律: 当前是 {os_name}，不要直接执行 Windows 专用命令。",
                "- 避免 `dir`、`type`、`findstr`、PowerShell cmdlet；需要时改用 Unix 等价命令或结构化工具。",
            ]
        return [
            "- 命令平台纪律: 当前系统无法稳定归类，执行 shell 前先选择最保守的结构化工具。",
        ]

    def compute() -> Optional[str]:
        now = datetime.now()
        rounded_minute = (now.minute // 5) * 5
        rounded_time = now.replace(minute=rounded_minute, second=0, microsecond=0)
        current_time = rounded_time.strftime("%Y-%m-%d %H:%M")

        import platform
        system_name = platform.system()
        os_name = {"windows": "Windows", "darwin": "macOS", "linux": "Linux"}.get(
            system_name.lower(), system_name
        )

        return "\n".join([
            "## 当前环境",
            f"- 当前时间: {current_time}",
            f"- 操作系统: {os_name} ({platform.version()}) [{platform.machine()}]",
            *command_discipline(os_name),
            f"- 项目根目录: {project_root}",
            f"- 静态提示词位置: core/core_prompt/",
            f"- 动态提示词位置: workspace/prompts/",
        ])

    return SystemPromptSection(
        name="ENV_INFO",
        compute=compute,
        cache_break=True,
        priority=100,
        description="系统环境信息",
    )


def make_memory_section(ctx: BuildContext) -> SystemPromptSection:
    """记忆章节 — 参数驱动，每轮重新计算。注入元认知干预。"""

    def compute() -> Optional[str]:
        core_context = ctx.core_context
        current_goal = ctx.current_goal
        state_memory = ctx.state_memory

        # ── 元认知干预 ──
        intervention = ""
        try:
            from core.mental_model_flags import is_mental_model_enabled

            if not is_mental_model_enabled():
                raise RuntimeError("mental model disabled for this turn")
            from core.infrastructure.mental_model import get_mental_model

            mm = get_mental_model()
            intervention = mm.get_intervention_for_prompt()
        except Exception:
            pass

        if not core_context and not current_goal and not state_memory and not intervention:
            return None

        lines = [
            "## 你的记忆与状态",
        ]
        if core_context:
            lines.append(f"- 核心智慧摘要: {core_context}")
        if current_goal:
            lines.append(f"- 当前核心目标: {current_goal}")
        if state_memory:
            lines.append(f"- 状态记忆:\n{state_memory}")

        # 元认知干预追加到末尾
        if intervention:
            lines.append(intervention)

        return "\n".join(lines)

    return SystemPromptSection(
        name="MEMORY",
        compute=compute,
        cache_break=True,
        priority=80,
        description="Agent 记忆与状态 + 元认知干预",
    )


def make_git_memory_section() -> SystemPromptSection:
    """Git 变化记忆章节 — 每轮读取最近变化与当前脏区。"""

    def compute() -> Optional[str]:
        try:
            from core.infrastructure.git_memory import get_git_memory_service
            return get_git_memory_service().format_prompt_context() or None
        except Exception:
            return None

    return SystemPromptSection(
        name="GIT_MEMORY",
        compute=compute,
        cache_break=True,
        priority=35,
        description="Git 事实变化、当前脏区、关注实体与最近验证摘要",
    )


def make_config_awareness_section() -> SystemPromptSection:
    """配置自感知章节 — 每轮读取当前配置身份、风险与建议动作。"""

    def compute() -> Optional[str]:
        try:
            from config import get_config
            return get_config().format_config_awareness_prompt()
        except Exception:
            return None

    return SystemPromptSection(
        name="CONFIG_AWARENESS",
        compute=compute,
        cache_break=True,
        priority=36,
        description="当前配置身份、关键来源、风险提示与建议动作",
    )


def make_delegation_rules_section() -> SystemPromptSection:
    """委派规则章节 — 主脑调度与子代理边界。"""

    def compute() -> Optional[str]:
        try:
            from core.infrastructure.agent_session import get_session_state
            return get_session_state().render_delegation_rules()
        except Exception:
            return None

    return SystemPromptSection(
        name="DELEGATION_RULES",
        compute=compute,
        cache_break=True,
        priority=36,
        description="主脑调度、子代理边界、结果回收与失败接管规则",
    )


def make_language_awareness_section() -> SystemPromptSection:
    """语言自感知章节 — 稳定压制自然语言输出向英文漂移。"""

    def compute() -> str:
        return (
            "## 语言状态\n"
            "- 当前默认表达语言：中文\n"
            "- 除代码、命令、路径、类名、函数名、API 名称、协议字段、必要报错原文外，自然语言说明应使用中文\n"
            "- 若本轮自然语言开始滑向英文，应自行拉回中文\n"
        )

    return SystemPromptSection(
        name="LANGUAGE_AWARENESS",
        compute=compute,
        cache_break=True,
        priority=37,
        description="当前默认语言、保留原文边界与英文漂移自纠偏",
    )


def make_spec_digest_section(ctx: BuildContext) -> SystemPromptSection:
    """SPEC 运行时摘要层 — 只保留当前模式最关键的硬纪律。"""

    def compute() -> str:
        mode = (ctx.prompt_mode or "orient").strip().lower()
        mode_title = {
            "orient": "定向",
            "diagnose": "诊断",
            "delegate": "委派",
            "execute": "执行",
            "verify": "验证",
        }.get(mode, mode or "运行时")

        common = [
            "- 默认中文；代码、命令、路径、协议字段、必要报错可保留原文。",
            "- 同轮同类失败不重复；被拦截的工具模式立即换路。",
        ]
        mode_rules = {
            "orient": [
                "- 先看 Git 变化与当前目标，再决定是否需要全局地图或配置上下文。",
                "- 没有明确锚点时先收窄问题，不要把大段规则和全局上下文一起常驻。",
            ],
            "diagnose": [
                "- 先复现，再观测，再读代码，最后推理；没有新增观测时停止长推理。",
                "- 已形成反馈环后优先围绕单一锚点收窄，禁止横向扩散。",
                "- 读文件优先结构化工具，不要回退到带 pipe 的 cli_tool 试探。",
            ],
            "delegate": [
                "- 只把边界清晰、阅读量大的问题委派给只读子 agent。",
                "- 子 agent 只返回结构化证据，最终裁决仍由主 agent 自己做。",
                "- 同轮已有有效委派结果时，禁止重复派发同类问题。",
            ],
            "execute": [
                "- 只在当前冻结范围内做最小修改，不顺手扩改无关路径。",
                "- Python 修改后先 lint，再 py_compile / pytest，验证不过不提交。",
                "- 高风险业务逻辑尽量留在 core/，不要把实现重新堆回 agent.py。",
            ],
            "verify": [
                "- 优先完成当前验证闭环；验证通过后直接收束，不开新支线。",
                "- 提交前确认修改范围、验证结果和当前脏区一致，不夹带无关变更。",
            ],
        }

        lines = [f"## SPEC 运行时摘要（{mode_title}）", *common, *(mode_rules.get(mode) or mode_rules["orient"])]
        return "\n".join(lines)

    return SystemPromptSection(
        name="SPEC_DIGEST",
        compute=compute,
        cache_break=True,
        priority=60,
        description="当前模式下最关键的运行时规则摘要",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 默认章节列表创建
# ═══════════════════════════════════════════════════════════════════════════════


def create_default_sections(
    static_root: Path,
    dynamic_root: Path,
    project_root: Path,
    enable_workspace: bool = False,
    section_configs: Optional[List[Any]] = None,
) -> List[SystemPromptSection]:
    """创建默认章节列表（不含 MEMORY，它依赖 BuildContext 在 build 时动态创建）。

    Args:
        section_configs: [[prompt.sections]] 配置列表，每项含 name/path/priority 等属性。
            静态章节由此驱动；为 None 或空列表时不注册任何静态章节。
    """

    sections: List[SystemPromptSection] = []

    # ── 静态章节（由 config.toml [[prompt.sections]] 驱动）──

    for cfg in (section_configs or []):
        section_path = project_root / cfg.path
        if section_path.exists():
            sections.append(make_file_section(
                cfg.name,
                section_path,
                priority=getattr(cfg, 'priority', 50),
                cache_break=getattr(cfg, 'cache_break', False),
                description=getattr(cfg, 'description', ''),
                required=getattr(cfg, 'required', False),
            ))

    # ── 内置动态章节 ──

    sections.append(make_task_checklist_section())
    sections.append(make_codebase_map_section())
    sections.append(make_git_memory_section())
    sections.append(make_delegation_rules_section())
    sections.append(make_config_awareness_section())
    sections.append(make_language_awareness_section())
    sections.append(make_git_rules_section(project_root))

    sections.append(make_tools_index_section(project_root))

    # ── 动态章节 ──

    sections.append(make_env_info_section(project_root))

    # ── Workspace 章节（仅在启用时注册）──

    if enable_workspace:
        for fname, pri, desc in [
            ("IDENTITY.md", 50, "Agent 身份定义"),
            ("USER.md", 70, "外部宿主环境与交互偏好"),
            ("DYNAMIC.md", 40, "动态提示词区域"),
        ]:
            fpath = dynamic_root / fname
            name = fname.replace(".md", "")
            if fpath.exists():
                sections.append(make_file_section(
                    name, fpath, priority=pri, cache_break=True, description=desc,
                ))
            # 文件不存在则不注册（不再注册空占位章节）

    return sections


# ═══════════════════════════════════════════════════════════════════════════════
# 辅助
# ═══════════════════════════════════════════════════════════════════════════════

