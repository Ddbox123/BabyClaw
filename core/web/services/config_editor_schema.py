"""Shared config editor schema helpers for the web workbench."""

from __future__ import annotations

import copy
from typing import Any


RUNTIME_PROFILE_OPTIONS = ["safe_local", "safe_remote", "debug", "ci"]
AGENT_MODE_OPTIONS = ["chat", "self_evolution", "supervised_evolution"]
EVOLUTION_REQUEST_BEHAVIOR_OPTIONS = ["route_to_workbench", "reply_only"]
SEGMENTATION_STRATEGY_OPTIONS = ["task_contiguous"]
AVATAR_PRESET_OPTIONS = ["lobster", "shrimp", "crab", "cat", "chick", "bunny", "slime", "penguin", "moose"]

SECTION_LABELS = {
    "zh": {
        "runtime": "运行时",
        "avatar": "形象",
        "llm.profiles": "模型档案",
        "llm.discovery": "模型发现",
        "agent": "智能体",
        "context_compression": "上下文压缩",
        "tools": "工具",
        "security": "安全",
        "log": "日志",
        "network": "网络",
        "evolution": "进化",
        "memory": "记忆",
        "strategy": "策略",
        "analysis": "分析",
        "ui": "界面",
        "parser": "解析器",
        "prompt": "提示词",
        "debug": "调试",
        "pet": "宠物",
    },
    "en": {
        "runtime": "Runtime",
        "avatar": "Avatar",
        "llm.profiles": "LLM Profiles",
        "llm.discovery": "Model Discovery",
        "agent": "Agent",
        "context_compression": "Context Compression",
        "tools": "Tools",
        "security": "Security",
        "log": "Logging",
        "network": "Network",
        "evolution": "Evolution",
        "memory": "Memory",
        "strategy": "Strategy",
        "analysis": "Analysis",
        "ui": "UI",
        "parser": "Parser",
        "prompt": "Prompt",
        "debug": "Debug",
        "pet": "Pet",
    },
}

FIELD_LABELS = {
    "zh": {
        "runtime.profile": "运行档案",
        "runtime.preflight_doctor": "启动前自检",
        "runtime.require_venv": "要求使用 .venv",
        "avatar.preset": "形象预设",
        "llm.profiles.primary.provider_id": "模型服务绑定",
        "llm.profiles.primary.model": "模型名称",
        "llm.profiles.primary.temperature": "温度",
        "llm.profiles.primary.max_output_tokens": "最大输出令牌数",
        "llm.profiles.primary.timeout": "API 超时（秒）",
        "llm.profiles.primary.connect_timeout": "连接超时（秒）",
        "llm.profiles.primary.streaming": "启用流式响应",
        "llm.profiles.primary.tool_calling_mode": "工具调用模式",
        "llm.discovery.enabled": "启用模型发现",
        "llm.discovery.timeout": "发现超时（秒）",
        "llm.discovery.fallback_max_tokens": "回退最大令牌数",
        "llm.discovery.fallback_max_token_limit": "回退上下文上限",
        "llm.discovery.auto_adjust": "自动调整",
        "llm.discovery.output_reserve_ratio": "输出预留比例",
        "agent.name": "智能体名称",
        "agent.workspace": "工作目录",
        "agent.awake_interval": "苏醒间隔（秒）",
        "agent.max_iterations": "最大工具调用数",
        "agent.max_runtime": "最大运行时长（秒）",
        "agent.auto_backup": "自动备份",
        "agent.backup_interval": "备份间隔（秒）",
        "agent.auto_restart_threshold": "自动重启阈值",
        "agent.exploration_mode": "探索模式",
        "agent.default_mode": "默认运行模式",
        "agent.modes.chat_enabled": "启用 chat 模式",
        "agent.modes.self_evolution_enabled": "启用自进化模式",
        "agent.modes.supervised_evolution_enabled": "启用监督进化模式",
        "agent.modes.default_shell_mode": "工作台默认模式",
        "agent.modes.default_headless_mode": "无交互默认模式",
        "agent.modes.explicit_evolution_request_behavior": "显式进化请求处理方式",
        "context_compression.keep_recent_steps": "保留最近步骤数",
        "context_compression.max_compressions_per_session": "每会话最大压缩次数",
        "context_compression.effectiveness_threshold": "压缩有效性阈值",
        "context_compression.preservation.keep_ai_messages": "保留 AI 消息数",
        "context_compression.preservation.preserve_errors": "保留错误",
        "context_compression.preservation.extract_key_decisions": "提取关键决策",
        "tools.file.encoding_priority": "编码优先级",
        "tools.file.editable_extensions": "可编辑扩展名",
        "tools.shell.max_output_length": "最大输出长度",
        "tools.shell.safety_check": "安全检查",
        "tools.shell.dangerous_pattern_check": "危险模式检查",
        "tools.shell.allowed_shells": "允许的 Shell",
        "tools.search.max_matches_per_file": "单文件最大匹配数",
        "tools.search.skip_directories": "跳过目录",
        "tools.search.skip_extensions": "跳过扩展名",
        "ui.language": "界面语言",
        "ui.theme": "主题",
        "ui.max_log_entries": "最大日志条目数",
        "ui.refresh_rate": "刷新频率",
        "ui.show_ascii_art": "显示 ASCII Art",
        "ui.show_welcome": "显示欢迎面板",
        "prompt.default_components": "默认提示词组件",
        "evolution.chat_dataset.enabled": "启用 chat 数据采样",
        "evolution.chat_dataset.source_modes": "采样来源模式",
        "evolution.chat_dataset.auto_capture": "自动采样",
        "evolution.chat_dataset.segmentation_strategy": "分段策略",
        "evolution.chat_dataset.min_turns": "最少轮数",
        "evolution.chat_dataset.max_turns": "最多轮数",
        "evolution.chat_dataset.require_tool_call_or_analysis_or_conclusion": "要求工具/分析/结论信号",
        "evolution.chat_dataset.exclude_pure_chitchat": "排除纯闲聊",
        "evolution.chat_dataset.candidate_dir": "候选目录",
        "evolution.chat_dataset.review_queue_path": "审核队列路径",
        "evolution.chat_dataset.approved_raw_dir": "已批准原始目录",
        "evolution.chat_dataset.approved_jsonl_path": "已批准数据集路径",
        "evolution.chat_dataset.rejected_log_path": "拒绝审计路径",
    },
    "en": {
        "runtime.profile": "Runtime Profile",
        "runtime.preflight_doctor": "Preflight Doctor",
        "runtime.require_venv": "Require .venv",
        "avatar.preset": "Avatar Preset",
        "llm.profiles.primary.provider_id": "Provider Binding",
        "llm.profiles.primary.model": "Model Name",
        "llm.profiles.primary.temperature": "Temperature",
        "llm.profiles.primary.max_output_tokens": "Max Output Tokens",
        "llm.profiles.primary.timeout": "API Timeout (s)",
        "llm.profiles.primary.connect_timeout": "Connect Timeout (s)",
        "llm.profiles.primary.streaming": "Streaming",
        "llm.profiles.primary.tool_calling_mode": "Tool Calling Mode",
        "llm.discovery.enabled": "Enable Discovery",
        "llm.discovery.timeout": "Discovery Timeout (s)",
        "llm.discovery.fallback_max_tokens": "Fallback Max Tokens",
        "llm.discovery.fallback_max_token_limit": "Fallback Token Limit",
        "llm.discovery.auto_adjust": "Auto Adjust",
        "llm.discovery.output_reserve_ratio": "Output Reserve Ratio",
        "agent.name": "Agent Name",
        "agent.workspace": "Workspace",
        "agent.awake_interval": "Wake Interval (s)",
        "agent.max_iterations": "Max Tool Calls",
        "agent.max_runtime": "Max Runtime (s)",
        "agent.auto_backup": "Auto Backup",
        "agent.backup_interval": "Backup Interval (s)",
        "agent.auto_restart_threshold": "Auto Restart Threshold",
        "agent.exploration_mode": "Exploration Mode",
        "agent.default_mode": "Default Agent Mode",
        "agent.modes.chat_enabled": "Enable Chat Mode",
        "agent.modes.self_evolution_enabled": "Enable Self Evolution",
        "agent.modes.supervised_evolution_enabled": "Enable Supervised Evolution",
        "agent.modes.default_shell_mode": "Default Workbench Mode",
        "agent.modes.default_headless_mode": "Default Headless Mode",
        "agent.modes.explicit_evolution_request_behavior": "Explicit Evolution Request Behavior",
        "context_compression.keep_recent_steps": "Recent Steps to Keep",
        "context_compression.max_compressions_per_session": "Max Compressions Per Session",
        "context_compression.effectiveness_threshold": "Compression Effectiveness Threshold",
        "context_compression.preservation.keep_ai_messages": "AI Messages to Keep",
        "context_compression.preservation.preserve_errors": "Preserve Errors",
        "context_compression.preservation.extract_key_decisions": "Extract Key Decisions",
        "tools.file.encoding_priority": "Encoding Priority",
        "tools.file.editable_extensions": "Editable Extensions",
        "tools.shell.max_output_length": "Max Output Length",
        "tools.shell.safety_check": "Safety Check",
        "tools.shell.dangerous_pattern_check": "Dangerous Pattern Check",
        "tools.shell.allowed_shells": "Allowed Shells",
        "tools.search.max_matches_per_file": "Max Matches Per File",
        "tools.search.skip_directories": "Skip Directories",
        "tools.search.skip_extensions": "Skip Extensions",
        "ui.language": "Interface Language",
        "ui.theme": "Theme",
        "ui.max_log_entries": "Max Log Entries",
        "ui.refresh_rate": "Refresh Rate",
        "ui.show_ascii_art": "Show ASCII Art",
        "ui.show_welcome": "Show Welcome Panel",
        "prompt.default_components": "Default Prompt Components",
        "evolution.chat_dataset.enabled": "Enable Chat Dataset Capture",
        "evolution.chat_dataset.source_modes": "Capture Source Modes",
        "evolution.chat_dataset.auto_capture": "Auto Capture",
        "evolution.chat_dataset.segmentation_strategy": "Segmentation Strategy",
        "evolution.chat_dataset.min_turns": "Minimum Turns",
        "evolution.chat_dataset.max_turns": "Maximum Turns",
        "evolution.chat_dataset.require_tool_call_or_analysis_or_conclusion": "Require Tool/Analysis/Conclusion Signal",
        "evolution.chat_dataset.exclude_pure_chitchat": "Exclude Pure Chitchat",
        "evolution.chat_dataset.candidate_dir": "Candidate Directory",
        "evolution.chat_dataset.review_queue_path": "Review Queue Path",
        "evolution.chat_dataset.approved_raw_dir": "Approved Raw Directory",
        "evolution.chat_dataset.approved_jsonl_path": "Approved Dataset Path",
        "evolution.chat_dataset.rejected_log_path": "Rejected Audit Path",
    },
}

FIELD_SUFFIX_LABELS = {
    "zh": {
        "provider": "服务提供方",
        "kind": "类型",
        "provider.kind": "服务商类型",
        "api_key_env": "密钥环境变量",
        "provider.api_key_env": "服务商密钥环境变量",
        "base_url": "基础地址",
        "provider.base_url": "服务商基础地址",
        "compat_mode": "兼容模式",
        "provider.compat_mode": "服务商兼容模式",
        "context_window": "上下文窗口",
        "provider.context_window": "服务商上下文窗口",
        "requires_api_key": "需要 API Key",
        "provider.requires_api_key": "服务商需要 API Key",
        "transport": "传输协议",
        "contract": "交互契约",
        "reasoning_state_field": "推理状态字段",
        "tool_calling_mode": "工具调用模式",
        "strict_compatibility": "严格兼容",
        "temperature": "温度",
        "max_output_tokens": "最大输出令牌数",
        "timeout": "超时（秒）",
        "connect_timeout": "连接超时（秒）",
        "streaming": "启用流式响应",
        "discovery_enabled": "启用模型发现",
        "label": "显示名",
        "model": "模型名称",
        "model_id": "模型 ID",
    },
    "en": {
        "provider": "Provider",
        "kind": "Kind",
        "provider.kind": "Provider Kind",
        "api_key_env": "API Key Env",
        "provider.api_key_env": "Provider API Key Env",
        "base_url": "Base URL",
        "provider.base_url": "Provider Base URL",
        "compat_mode": "Compat Mode",
        "provider.compat_mode": "Provider Compat Mode",
        "context_window": "Context Window",
        "provider.context_window": "Provider Context Window",
        "requires_api_key": "Requires API Key",
        "provider.requires_api_key": "Provider Requires API Key",
        "transport": "Transport",
        "contract": "Contract",
        "reasoning_state_field": "Reasoning State Field",
        "tool_calling_mode": "Tool Calling Mode",
        "strict_compatibility": "Strict Compatibility",
        "temperature": "Temperature",
        "max_output_tokens": "Max Output Tokens",
        "timeout": "Timeout (s)",
        "connect_timeout": "Connect Timeout (s)",
        "streaming": "Streaming",
        "discovery_enabled": "Discovery Enabled",
        "label": "Label",
        "model": "Model Name",
        "model_id": "Model ID",
    },
}

BADGE_LABELS = {
    "zh": {
        "Group": "分组",
        "List": "列表",
        "Toggle": "开关",
        "Option": "选项",
        "Seconds": "秒",
        "Token": "令牌",
        "Number": "数字",
        "JSON": "JSON",
        "Secret": "密钥",
        "URL": "地址",
        "Path": "路径",
        "Text": "文本",
    },
    "en": {
        "Group": "Group",
        "List": "List",
        "Toggle": "Toggle",
        "Option": "Option",
        "Seconds": "Seconds",
        "Token": "Token",
        "Number": "Number",
        "JSON": "JSON",
        "Secret": "Secret",
        "URL": "URL",
        "Path": "Path",
        "Text": "Text",
    },
}

FIELD_HINTS = {
    "zh": {
        "runtime.profile": "决定默认运行策略，通常先从 safe_local 或 debug 开始。",
        "runtime.preflight_doctor": "启动前先做自检，适合排查环境漂移。",
        "agent.awake_interval": "自主模式两次苏醒之间的间隔。",
        "agent.max_iterations": "单轮最多允许多少次工具动作。",
        "agent.max_runtime": "单轮可持续的最长运行时间。",
        "agent.default_mode": "决定默认启动为 chat、自进化还是监督进化。",
        "agent.modes.default_shell_mode": "工作台入口默认采用的 agent mode。",
        "agent.modes.default_headless_mode": "命令行无交互运行时默认采用的 agent mode。",
        "agent.modes.explicit_evolution_request_behavior": "chat 中遇到显式进化请求时，决定是转交进化入口还是只回复说明。",
        "agent.auto_restart_threshold": "达到阈值后触发热重启。",
        "context_compression.keep_recent_steps": "压缩后仍然保留的最近步骤数。",
        "context_compression.max_compressions_per_session": "单会话允许的最大压缩次数。",
        "tools.shell.allowed_shells": "允许使用的 shell 类型，直接影响跨平台行为。",
        "tools.shell.max_output_length": "终端输出截断上限，过小会影响诊断。",
        "evolution.chat_dataset.source_modes": "哪些 agent mode 产生的对话可以被静默采样进入审核队列。",
        "evolution.chat_dataset.segmentation_strategy": "chat 采样如何切分连续多轮上下文。",
        "ui.refresh_rate": "终端工作台刷新频率。",
        "ui.max_log_entries": "UI 内部保留的日志条目数。",
    },
    "en": {
        "runtime.profile": "Sets the default runtime posture. Start with safe_local or debug in most cases.",
        "runtime.preflight_doctor": "Runs startup checks before execution to catch environment drift.",
        "agent.awake_interval": "Delay between autonomous wake cycles.",
        "agent.max_iterations": "Maximum tool actions allowed in one round.",
        "agent.max_runtime": "Maximum duration for a single round.",
        "agent.default_mode": "Selects whether the agent defaults to chat, self-evolution, or supervised evolution.",
        "agent.modes.default_shell_mode": "Agent mode used by default when entering the interactive workbench.",
        "agent.modes.default_headless_mode": "Agent mode used by default for non-interactive CLI runs.",
        "agent.modes.explicit_evolution_request_behavior": "Controls whether chat reroutes explicit evolution requests or only explains the routing.",
        "agent.auto_restart_threshold": "Threshold that triggers hot restart.",
        "context_compression.keep_recent_steps": "How many recent steps survive compression.",
        "context_compression.max_compressions_per_session": "Compression cap per session.",
        "tools.shell.allowed_shells": "Allowed shell types. This directly affects cross-platform behavior.",
        "tools.shell.max_output_length": "Terminal output cap. Too small will hide diagnostics.",
        "evolution.chat_dataset.source_modes": "Which agent modes may silently contribute conversation samples to the review queue.",
        "evolution.chat_dataset.segmentation_strategy": "How chat capture segments contiguous multi-turn context.",
        "ui.refresh_rate": "Refresh cadence for the terminal workbench.",
        "ui.max_log_entries": "How many UI log entries are retained.",
    },
}

EDITOR_SECTION_SPECS = [
    ("runtime", "runtime"),
    ("avatar", "avatar"),
    ("llm-profiles", "llm.profiles"),
    ("llm-discovery", "llm.discovery"),
    ("agent", "agent"),
    ("context-compression", "context_compression"),
    ("tools", "tools"),
    ("security", "security"),
    ("log", "log"),
    ("network", "network"),
    ("evolution", "evolution"),
    ("memory", "memory"),
    ("strategy", "strategy"),
    ("analysis", "analysis"),
    ("ui", "ui"),
    ("parser", "parser"),
    ("prompt", "prompt"),
    ("debug", "debug"),
    ("pet", "pet"),
]


def _humanize_token(token: str) -> str:
    cleaned = str(token or "").strip()
    if not cleaned:
        return ""
    return " ".join(part.upper() if part.isupper() else part.capitalize() for part in cleaned.split("_") if part)


def localize_label(path: str, fallback: str, lang: str) -> str:
    exact = FIELD_LABELS.get(lang, {}).get(path)
    if exact:
        return exact
    parts = [part for part in str(path or "").split(".") if part]
    suffix_map = FIELD_SUFFIX_LABELS.get(lang, {})
    for token_count in (2, 1):
        if len(parts) >= token_count:
            suffix = ".".join(parts[-token_count:])
            mapped = suffix_map.get(suffix)
            if mapped:
                return mapped
    token = str(fallback or "").strip() or str(path or "").split(".")[-1]
    parts = [part for part in token.split("_") if part]
    if not parts:
        return token
    return " ".join(_humanize_token(part) for part in parts)


def localize_section_label(path: str, fallback: str, lang: str) -> str:
    exact = SECTION_LABELS.get(lang, {}).get(path)
    if exact:
        return exact
    return localize_label(path, fallback, lang)


def field_hint(path: str, lang: str) -> str:
    return FIELD_HINTS.get(lang, {}).get(path, "")


def localize_badge(label: str, lang: str) -> str:
    return BADGE_LABELS.get(lang, {}).get(label, label)


def _is_secret_path(path: str) -> bool:
    return str(path or "").split(".")[-1] == "api_key"


def _field_options(path: str, lang: str) -> list[dict[str, str]]:
    if path == "ui.language":
        return [
            {"value": "zh", "label": "中文" if lang == "zh" else "Chinese"},
            {"value": "en", "label": "English"},
        ]
    if path == "runtime.profile":
        return [{"value": value, "label": value} for value in RUNTIME_PROFILE_OPTIONS]
    if path == "avatar.preset":
        return [{"value": value, "label": value} for value in AVATAR_PRESET_OPTIONS]
    if path in {"agent.default_mode", "agent.modes.default_shell_mode", "agent.modes.default_headless_mode"}:
        return [{"value": value, "label": value} for value in AGENT_MODE_OPTIONS]
    if path == "agent.modes.explicit_evolution_request_behavior":
        return [{"value": value, "label": value} for value in EVOLUTION_REQUEST_BEHAVIOR_OPTIONS]
    if path == "evolution.chat_dataset.segmentation_strategy":
        return [{"value": value, "label": value} for value in SEGMENTATION_STRATEGY_OPTIONS]
    return []


def _field_kind(path: str, value: Any, options: list[dict[str, str]] | None = None) -> tuple[str, str]:
    if isinstance(value, bool):
        return "boolean", "Toggle"
    if options:
        return "select", "Option"
    if isinstance(value, int) and not isinstance(value, bool):
        if any(token in path for token in ("timeout", "interval", "runtime")):
            return "number", "Seconds"
        if any(token in path for token in ("tokens", "token", "context_window")):
            return "number", "Token"
        return "number", "Number"
    if isinstance(value, float):
        return "number", "Number"
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return "string_list", "List"
    if isinstance(value, list):
        return "json", "JSON"
    if _is_secret_path(path):
        return "secret", "Secret"
    if any(token in path for token in ("url", "api_base", "base_url")):
        return "url", "URL"
    if any(token in path for token in ("path", "workspace", "directory", "directories", "file", "log")):
        return "path", "Path"
    return "text", "Text"


def _lookup_path_value(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for part in [token for token in str(path or "").split(".") if token]:
        if isinstance(current, dict):
            current = current[part]
            continue
        if isinstance(current, list) and part.isdigit():
            current = current[int(part)]
            continue
        raise KeyError(path)
    return current


def _count_leaf_fields(value: Any) -> int:
    if isinstance(value, dict):
        return sum(_count_leaf_fields(item) for item in value.values())
    if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
        return sum(_count_leaf_fields(item) for item in value)
    return 1


def _walk_editor_meta(value: Any, path: str, lang: str, into: dict[str, dict[str, Any]]) -> None:
    label = localize_section_label(path, path.split(".")[-1] if path else "", lang)
    hint = field_hint(path, lang)
    if isinstance(value, dict):
        into[path] = {
            "path": path,
            "label": label,
            "hint": hint,
            "kind": "object",
            "badge": localize_badge("Group", lang),
            "options": [],
        }
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else key
            _walk_editor_meta(child, child_path, lang, into)
        return
    if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
        into[path] = {
            "path": path,
            "label": label,
            "hint": hint,
            "kind": "object_list",
            "badge": localize_badge("List", lang),
            "options": [],
        }
        for index, child in enumerate(value):
            child_path = f"{path}.{index}"
            _walk_editor_meta(child, child_path, lang, into)
        return
    options = _field_options(path, lang)
    kind, badge = _field_kind(path, value, options)
    into[path] = {
        "path": path,
        "label": localize_label(path, path.split(".")[-1] if path else "", lang),
        "hint": hint,
        "kind": kind,
        "badge": localize_badge(badge, lang),
        "options": options,
    }


def build_editor_meta(public_config: dict[str, Any], lang: str) -> dict[str, dict[str, Any]]:
    meta: dict[str, dict[str, Any]] = {}
    for _, path in EDITOR_SECTION_SPECS:
        try:
            section_value = _lookup_path_value(public_config, path)
        except KeyError:
            continue
        _walk_editor_meta(copy.deepcopy(section_value), path, lang, meta)
    return meta


def build_editor_sections(public_config: dict[str, Any], lang: str) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    for section_id, path in EDITOR_SECTION_SPECS:
        try:
            value = _lookup_path_value(public_config, path)
        except KeyError:
            continue
        title = localize_section_label(path, path.split(".")[-1], lang)
        sections.append(
            {
                "id": section_id,
                "path": path,
                "title": title,
                "summary": field_hint(path, lang)
                or (
                    "结构化编辑并确认这个配置分区，再统一应用。"
                    if lang == "zh"
                    else "Edit and confirm this config block before the global apply step."
                ),
                "fieldCount": _count_leaf_fields(value),
            }
        )
    return sections
