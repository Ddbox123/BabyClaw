#!/usr/bin/env python3
"""
本地可视化配置面板（第一版）。
"""

from __future__ import annotations

import argparse
import copy
import html
import json
import os
import sys
import threading
import urllib.error
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.public_config import (  # noqa: E402
    CONFIG_PATH,
    HEADER_LINES,
    MODEL_LIBRARY_DETAIL_FIELDS,
    UNCONFIGURED_MODEL_REF,
    add_llm_model,
    add_llm_profile,
    apply_llm_model_preset,
    build_effective_config,
    delete_llm_model,
    inspect_public_config,
    list_llm_model_options,
    list_llm_model_preset_options,
    load_public_config,
    preserve_secret_blanks,
    public_config_hash,
    save_public_config,
    update_llm_model,
)  # noqa: E402
from config.llm_security import (  # noqa: E402
    coerce_llm_probe_timeout,
    redact_llm_probe_error,
    validate_llm_api_key_env,
    validate_llm_provider_target,
    validate_llm_public_config,
)
from config.settings import PUBLIC_INLINE_PROVIDER_FIELDS  # noqa: E402
from config.toml_writer import dumps_public_config  # noqa: E402


DEFAULT_LANG = "zh"
PANEL_BUILD_ID = "config-panel-toast-v2"


class ConfigConflictError(ValueError):
    """Raised when applying a draft against a stale saved config snapshot."""


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401, ANN001
        return None


RUNTIME_PROFILE_OPTIONS = ["safe_local", "safe_remote", "debug", "ci"]
AGENT_MODE_OPTIONS = ["chat", "self_evolution", "supervised_evolution"]
EVOLUTION_REQUEST_BEHAVIOR_OPTIONS = ["route_to_workbench", "reply_only"]
SEGMENTATION_STRATEGY_OPTIONS = ["task_contiguous"]
LLM_PROVIDER_OPTIONS = [
    "aliyun",
    "openai",
    "anthropic",
    "deepseek",
    "google",
    "zhipu",
    "ollama",
    "siliconflow",
    "groq",
    "minimax",
    "local",
]
LLM_PROVIDER_COMPAT_OPTIONS = ["openai", "native"]
LLM_PROVIDER_EDIT_FIELDS = tuple(field for field in PUBLIC_INLINE_PROVIDER_FIELDS if field != "api_key")
AVATAR_PRESET_OPTIONS = ["lobster", "shrimp", "crab", "cat", "chick", "bunny", "slime", "penguin", "moose"]

I18N = {
    "zh": {
        "html_lang": "zh-CN",
        "title": "Vibelution 配置面板",
        "panel_title": "配置面板",
        "panel_subtitle": "Vibelution Workbench / Config",
        "save": "应用配置",
        "reload": "重新加载",
        "diagnostics": "配置诊断",
        "blocking": "阻断问题",
        "warnings": "风险提示",
        "actions": "建议动作",
        "raw_toml": "原始 TOML",
        "raw_toml_summary": "查看当前写盘内容",
        "profile_id": "配置标识",
        "provider_id": "服务标识",
        "api_base": "API 地址",
        "open_runtime": "运行时设置",
        "open_model_library": "模型库",
        "provider": "服务配置",
        "provider_config": "服务配置",
        "provider_kind": "服务类型",
        "provider_base_url": "服务地址",
        "provider_api_key_env": "服务 API 密钥环境变量",
        "provider_compat_mode": "兼容模式",
        "provider_requires_api_key": "需要 API 密钥",
        "provider_context_window": "上下文窗口",
        "provider_extra_headers": "额外请求头(JSON)",
        "model": "模型",
        "profile": "智能体配置",
        "api_key_source": "密钥来源",
        "selectable_models": "可选模型",
        "none": "无",
        "save_failed": "保存失败",
        "save_success": "配置已应用并通过校验",
        "save_success_title": "应用成功",
        "save_failed_title": "保存失败",
        "confirm_success": "修改已确认，等待应用",
        "confirm_success_title": "已确认",
        "stale_config": "当前配置已被其他页面或进程改动，请重新加载后再应用这份已确认草稿",
        "language": "语言",
        "lang_zh": "中文",
        "lang_en": "English",
        "add_llm": "复制配置",
        "test_llm": "测试连接",
        "switch_provider": "切换",
        "test_provider": "测试",
        "switch_success": "主模型已切换",
        "test_success_title": "连接正常",
        "test_failed_title": "连接失败",
        "prompt_profile_id": "配置标识",
        "prompt_provider_id": "模型服务标识",
        "prompt_source_profile_id": "来源配置",
        "prompt_model_id": "选择模型",
        "prompt_model": "模型名称",
        "model_library": "通用模型库",
        "model_library_hint": "统一管理可选择的模型；各智能体配置从这里挑选模型，复制后保留各自独立的服务配置与微调参数。",
        "preset_template": "预设模板",
        "preset_template_hint": "选择主流厂商模板会自动填入服务配置、模型和默认参数；保存后写入统一配置结构。",
        "preset_custom": "手动配置",
        "custom_model": "自定义模型",
        "add_model": "添加模型",
        "edit_model": "编辑",
        "save_model": "确认",
        "cancel": "取消",
        "delete_model": "删除模型",
        "model_id": "模型标识",
        "model_label": "显示名称",
        "apply_model": "确认切换",
        "model_api_key": "模型 API 密钥",
        "api_key_configured": "已配置",
        "api_key_missing": "未配置",
        "api_key_pending": "待应用",
        "api_key_clear_pending": "待清除",
        "clear_api_key": "清除密钥",
        "api_key_hint": "保存后写入本机用户级环境变量；不会写入 config.toml。",
        "profile_group_unsupervised": "无监督进化",
        "profile_group_supervised": "监督进化",
        "required_field": "必填",
        "select_model_placeholder": "请选择模型",
        "profile_model_missing": "以下智能体必须选择模型后才能应用：",
    },
    "en": {
        "html_lang": "en",
        "title": "Vibelution Config Panel",
        "panel_title": "Config Panel",
        "panel_subtitle": "Vibelution Workbench / Config",
        "save": "Apply Config",
        "reload": "Reload",
        "diagnostics": "Configuration Diagnostics",
        "blocking": "Blocking Issues",
        "warnings": "Warnings",
        "actions": "Suggested Actions",
        "raw_toml": "Raw TOML",
        "raw_toml_summary": "View current persisted content",
        "profile_id": "Profile ID",
        "provider_id": "Provider ID",
        "api_base": "API Base",
        "open_runtime": "Runtime",
        "open_model_library": "Model Library",
        "provider": "Provider Config",
        "provider_config": "Provider Config",
        "provider_kind": "Provider Type",
        "provider_base_url": "Base URL",
        "provider_api_key_env": "Provider API Key Env",
        "provider_compat_mode": "Compatibility Mode",
        "provider_requires_api_key": "Requires API Key",
        "provider_context_window": "Context Window",
        "provider_extra_headers": "Extra Headers (JSON)",
        "model": "Model",
        "profile": "Agent Config",
        "api_key_source": "API Key Source",
        "selectable_models": "Selectable Models",
        "none": "None",
        "save_failed": "Save failed",
        "save_success": "Configuration applied and validated",
        "save_success_title": "Applied",
        "save_failed_title": "Save Failed",
        "confirm_success": "Changes confirmed and waiting to apply",
        "confirm_success_title": "Confirmed",
        "stale_config": "The saved config changed in another page or process. Reload before applying this confirmed draft.",
        "language": "Language",
        "lang_zh": "中文",
        "lang_en": "English",
        "add_llm": "Clone Config",
        "test_llm": "Test Connection",
        "switch_provider": "Switch",
        "test_provider": "Test",
        "switch_success": "Primary LLM switched",
        "test_success_title": "Connection OK",
        "test_failed_title": "Connection Failed",
        "prompt_profile_id": "profile_id",
        "prompt_provider_id": "provider_id",
        "prompt_source_profile_id": "source_profile_id",
        "prompt_model_id": "model_id",
        "prompt_model": "model",
        "model_library": "Model Library",
        "model_library_hint": "Manage selectable models once; agent configs pick from here, then keep their own provider copy and tuning.",
        "preset_template": "Preset Template",
        "preset_template_hint": "Choose a vendor preset to fill provider config, model, and defaults; saving still writes the normal config shape.",
        "preset_custom": "Manual",
        "custom_model": "Custom Model",
        "add_model": "Add Model",
        "edit_model": "Edit",
        "save_model": "Confirm",
        "cancel": "Cancel",
        "delete_model": "Delete Model",
        "model_id": "Model ID",
        "model_label": "Display Label",
        "apply_model": "Confirm Switch",
        "model_api_key": "Model API Key",
        "api_key_configured": "Configured",
        "api_key_missing": "Missing",
        "api_key_pending": "Pending",
        "api_key_clear_pending": "Pending Clear",
        "clear_api_key": "Clear Key",
        "api_key_hint": "Saved to the local user environment; never written to config.toml.",
        "profile_group_unsupervised": "Unsupervised Evolution",
        "profile_group_supervised": "Supervised Evolution",
        "required_field": "Required",
        "select_model_placeholder": "Select a model",
        "profile_model_missing": "Choose models for these agents before apply:",
    },
}

SECTION_LABELS = {
    "zh": {
        "runtime": "运行时",
        "avatar": "形象",
        "llm": "模型",
        "llm.providers": "模型服务",
        "llm.profiles": "模型档案",
        "llm.discovery": "模型发现",
        "agent": "智能体",
        "context_compression": "上下文压缩",
        "context_compression.levels": "压缩级别",
        "context_compression.summary_chars": "摘要字符预算",
        "context_compression.preservation": "压缩保留策略",
        "tools": "工具",
        "tools.file": "文件工具",
        "tools.shell": "命令行工具",
        "tools.search": "搜索工具",
        "tools.web": "网页工具",
        "security": "安全",
        "log": "日志",
        "log.third_party": "第三方日志",
        "network": "网络",
        "evolution": "进化",
        "memory": "记忆",
        "strategy": "策略",
        "analysis": "分析",
        "ui": "界面",
        "parser": "解析器",
        "prompt": "提示词",
        "debug": "调试",
        "compat": "兼容层",
        "pet": "宠物",
        "pet.gene": "宠物基因",
        "pet.heart": "宠物心跳",
        "pet.dream": "宠物梦境",
        "pet.personality": "宠物性格",
        "pet.hunger": "宠物饥饿",
        "pet.diary": "宠物日记",
        "pet.social": "宠物社交",
        "pet.health": "宠物健康",
        "pet.skin": "宠物皮肤",
        "pet.sound": "宠物声音",
    },
    "en": {
        "runtime": "Runtime",
        "avatar": "Avatar",
        "llm": "LLM",
        "llm.providers": "Providers",
        "llm.profiles": "LLM Profiles",
        "llm.discovery": "Model Discovery",
        "agent": "智能体",
        "context_compression": "Context Compression",
        "context_compression.levels": "Compression Levels",
        "context_compression.summary_chars": "Summary Character Budget",
        "context_compression.preservation": "Preservation Policy",
        "tools": "Tools",
        "tools.file": "File Tools",
        "tools.shell": "Shell Tools",
        "tools.search": "Search Tools",
        "tools.web": "Web Tools",
        "security": "Security",
        "log": "Logging",
        "log.third_party": "Third-Party Logging",
        "network": "Network",
        "evolution": "Evolution",
        "memory": "Memory",
        "strategy": "Strategy",
        "analysis": "Analysis",
        "ui": "UI",
        "parser": "Parser",
        "prompt": "Prompt",
        "debug": "Debug",
        "compat": "Compatibility",
        "pet": "Pet",
        "pet.gene": "Pet Gene",
        "pet.heart": "Pet Heart",
        "pet.dream": "Pet Dream",
        "pet.personality": "Pet Personality",
        "pet.hunger": "Pet Hunger",
        "pet.diary": "Pet Diary",
        "pet.social": "Pet Social",
        "pet.health": "Pet Health",
        "pet.skin": "Pet Skin",
        "pet.sound": "Pet Sound",
    },
}

FIELD_LABELS = {
    "zh": {
        "runtime.profile": "运行档案",
        "runtime.preflight_doctor": "启动前自检",
        "runtime.require_venv": "要求使用 .venv",
        "avatar.preset": "形象预设",
        "llm.providers.remote_main.kind": "服务类型",
        "llm.providers.remote_main.api_key": "API 密钥",
        "llm.providers.remote_main.api_key_env": "API 密钥环境变量",
        "llm.providers.remote_main.base_url": "API 地址",
        "llm.providers.remote_main.compat_mode": "兼容模式",
        "llm.providers.remote_main.requires_api_key": "要求 API 密钥",
        "llm.providers.remote_main.context_window": "上下文窗口",
        "llm.providers.local_main.kind": "本地服务类型",
        "llm.providers.local_main.base_url": "本地服务地址",
        "llm.profiles.primary.provider_id": "模型服务绑定",
        "llm.profiles.primary.model": "模型名称",
        "llm.profiles.primary.temperature": "温度",
        "llm.profiles.primary.max_output_tokens": "最大输出令牌数",
        "llm.profiles.primary.timeout": "API 超时（秒）",
        "llm.profiles.primary.connect_timeout": "连接超时（秒）",
        "llm.profiles.primary.streaming": "启用流式响应",
        "llm.profiles.primary.tool_calling_mode": "工具调用模式",
        "llm.model_library.api_key_env": "API 密钥环境变量",
        "llm.model_library.transport": "传输协议",
        "llm.model_library.contract": "交互协议",
        "llm.model_library.reasoning_state_field": "推理状态字段",
        "llm.model_library.temperature": "温度",
        "llm.model_library.max_output_tokens": "最大输出令牌数",
        "llm.model_library.timeout": "请求超时（秒）",
        "llm.model_library.connect_timeout": "连接超时（秒）",
        "llm.model_library.tool_calling_mode": "工具调用模式",
        "llm.model_library.strict_compatibility": "严格兼容性",
        "llm.model_library.streaming": "流式响应",
        "llm.model_library.discovery_enabled": "启用模型发现",
        "llm.model_library.transport.chat_completions": "聊天补全",
        "llm.model_library.transport.responses": "响应接口",
        "llm.model_library.contract.basic_chat": "基础对话",
        "llm.model_library.contract.tool_chat": "工具对话",
        "llm.model_library.contract.reasoning_chat": "推理对话",
        "llm.model_library.contract.responses_agent": "Responses 智能体",
        "llm.model_library.tool_calling_mode.auto": "自动",
        "llm.model_library.tool_calling_mode.disabled": "禁用",
        "llm.model_library.tool_calling_mode.required": "必需",
        "llm.model_library.tool_calling_mode.parallel": "并行",
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
        "llm.providers.remote_main.kind": "Provider Kind",
        "llm.providers.remote_main.api_key": "API Key",
        "llm.providers.remote_main.api_key_env": "API Key Env",
        "llm.providers.remote_main.base_url": "API Base URL",
        "llm.providers.remote_main.compat_mode": "Compatibility Mode",
        "llm.providers.remote_main.requires_api_key": "Requires API Key",
        "llm.providers.remote_main.context_window": "Context Window",
        "llm.providers.local_main.kind": "Local Provider Kind",
        "llm.providers.local_main.base_url": "Local Service URL",
        "llm.profiles.primary.provider_id": "Provider Binding",
        "llm.profiles.primary.model": "Model Name",
        "llm.profiles.primary.temperature": "Temperature",
        "llm.profiles.primary.max_output_tokens": "Max Output Tokens",
        "llm.profiles.primary.timeout": "API Timeout (s)",
        "llm.profiles.primary.connect_timeout": "Connect Timeout (s)",
        "llm.profiles.primary.streaming": "Streaming",
        "llm.profiles.primary.tool_calling_mode": "Tool Calling Mode",
        "llm.model_library.api_key_env": "API Key Env",
        "llm.model_library.transport": "Transport",
        "llm.model_library.contract": "Contract",
        "llm.model_library.reasoning_state_field": "Reasoning State Field",
        "llm.model_library.temperature": "Temperature",
        "llm.model_library.max_output_tokens": "Max Output Tokens",
        "llm.model_library.timeout": "Request Timeout (s)",
        "llm.model_library.connect_timeout": "Connect Timeout (s)",
        "llm.model_library.tool_calling_mode": "Tool Calling Mode",
        "llm.model_library.strict_compatibility": "Strict Compatibility",
        "llm.model_library.streaming": "Streaming",
        "llm.model_library.discovery_enabled": "Discovery Enabled",
        "llm.model_library.transport.chat_completions": "Chat Completions",
        "llm.model_library.transport.responses": "Responses API",
        "llm.model_library.contract.basic_chat": "Basic Chat",
        "llm.model_library.contract.tool_chat": "Tool Chat",
        "llm.model_library.contract.reasoning_chat": "Reasoning Chat",
        "llm.model_library.contract.responses_agent": "Responses Agent",
        "llm.model_library.tool_calling_mode.auto": "Auto",
        "llm.model_library.tool_calling_mode.disabled": "Disabled",
        "llm.model_library.tool_calling_mode.required": "Required",
        "llm.model_library.tool_calling_mode.parallel": "Parallel",
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

FIELD_HINTS = {
    "zh": {
        "runtime.profile": "决定默认运行策略，通常先从 safe_local 或 debug 开始。",
        "runtime.preflight_doctor": "启动前先做自检，适合排查环境漂移。",
        "llm.providers.remote_main.kind": "默认远程 provider 类型，决定接口族和认证约定。",
        "llm.providers.remote_main.base_url": "远程 provider 的基础地址，代理或兼容层接入时使用。",
        "llm.providers.remote_main.context_window": "provider 侧声明的上下文容量，用于发现与预算估算。",
        "llm.providers.local_main.base_url": "本地模型服务地址，通常是 http://127.0.0.1:* 。",
        "llm.profiles.primary.provider_id": "主 Agent 绑定到哪个 provider。",
        "llm.profiles.primary.model": "主模型标识，建议与 provider 保持匹配。",
        "llm.profiles.primary.max_output_tokens": "控制单次输出上限，过大可能增加成本与延迟。",
        "llm.profiles.primary.timeout": "请求等待总时长，网络不稳时优先检查这里。",
        "llm.profiles.primary.connect_timeout": "建立连接阶段的超时设置。",
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
        "llm.providers.remote_main.kind": "Default remote provider type. This drives auth and API-family behavior.",
        "llm.providers.remote_main.base_url": "Base URL for the remote provider or compatibility layer.",
        "llm.providers.remote_main.context_window": "Declared context capacity used for discovery and budgeting.",
        "llm.providers.local_main.base_url": "Local model service endpoint, usually http://127.0.0.1:* .",
        "llm.profiles.primary.provider_id": "Which provider the primary agent profile uses.",
        "llm.profiles.primary.model": "Primary model identifier. Keep it aligned with the provider.",
        "llm.profiles.primary.max_output_tokens": "Caps single-response length. Larger values increase latency and cost.",
        "llm.profiles.primary.timeout": "Total request timeout. Check this first when networking is unstable.",
        "llm.profiles.primary.connect_timeout": "Connection-establishment timeout.",
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

TOKEN_LABELS = {
    "zh": {
        "active": "活跃",
        "actions": "动作",
        "adjust": "调整",
        "agent": "Agent",
        "allowed": "允许",
        "analysis": "分析",
        "approved": "已批准",
        "archive": "归档",
        "art": "艺术字",
        "ascii": "ASCII",
        "auto": "自动",
        "avatar": "形象",
        "backup": "备份",
        "base": "基址",
        "blocking": "阻断",
        "cache": "缓存",
        "chars": "字符",
        "check": "检查",
        "command": "命令",
        "commands": "命令",
        "compat": "兼容",
        "component": "组件",
        "components": "组件",
        "compression": "压缩",
        "config": "配置",
        "connect": "连接",
        "context": "上下文",
        "cooldown": "冷却",
        "count": "数量",
        "create": "创建",
        "data": "数据",
        "date": "日期",
        "debug": "调试",
        "decay": "衰减",
        "default": "默认",
        "delay": "延迟",
        "delete": "删除",
        "detailed": "详细",
        "detect": "检测",
        "diary": "日记",
        "directories": "目录",
        "directory": "目录",
        "discovery": "发现",
        "dream": "梦境",
        "duration": "时长",
        "edit": "编辑",
        "effective": "生效",
        "enabled": "启用",
        "encoding": "编码",
        "entries": "条目",
        "error": "错误",
        "errors": "错误",
        "evolution": "进化",
        "extensions": "扩展名",
        "extract": "提取",
        "factor": "系数",
        "feedback": "反馈",
        "feed": "喂食",
        "file": "文件",
        "files": "文件",
        "forbidden": "禁止",
        "format": "格式",
        "friendship": "友谊",
        "gene": "基因",
        "health": "健康",
        "heart": "心跳",
        "history": "历史",
        "hunger": "饥饿",
        "idle": "空闲",
        "include": "包含",
        "inherit": "继承",
        "interval": "间隔",
        "issues": "问题",
        "keep": "保留",
        "key": "密钥",
        "knowledge": "知识",
        "language": "语言",
        "legacy": "旧版",
        "level": "级别",
        "levels": "级别",
        "limit": "上限",
        "lines": "行",
        "llm": "模型",
        "local": "本地",
        "log": "日志",
        "max": "最大",
        "memory": "记忆",
        "messages": "消息",
        "matches": "匹配数",
        "meal": "餐食",
        "mental": "心智",
        "minimax": "MiniMax",
        "model": "模型",
        "mood": "情绪",
        "name": "名称",
        "network": "网络",
        "other": "其他",
        "output": "输出",
        "path": "路径",
        "paths": "路径",
        "pattern": "模式",
        "patterns": "模式",
        "personality": "性格",
        "pet": "宠物",
        "preflight": "预检",
        "preservation": "保留",
        "primary": "主",
        "profile": "档案",
        "profiles": "档案",
        "prompt": "提示词",
        "provider": "服务",
        "providers": "服务",
        "rate": "速率",
        "raw": "原始",
        "read": "读取",
        "refresh": "刷新",
        "required": "必需",
        "reserve": "预留",
        "response": "响应",
        "remote": "远程",
        "restart": "重启",
        "result": "结果",
        "results": "结果",
        "retry": "重试",
        "runtime": "运行时",
        "save": "保存",
        "search": "搜索",
        "section": "分区",
        "sections": "分区",
        "secret": "机密",
        "security": "安全",
        "sentiment": "情感",
        "shell": "命令行",
        "show": "显示",
        "size": "大小",
        "skin": "皮肤",
        "social": "社交",
        "sound": "声音",
        "source": "来源",
        "ssl": "SSL",
        "standard": "标准",
        "storage": "存储",
        "strategy": "策略",
        "strip": "剥离",
        "suggested": "建议",
        "subagent": "子智能体",
        "summary": "摘要",
        "supervised": "监督",
        "syntax": "语法",
        "tags": "标签",
        "temperature": "温度",
        "test": "测试",
        "theme": "主题",
        "third": "第三方",
        "timeout": "超时",
        "token": "令牌",
        "tokens": "令牌",
        "tool": "工具",
        "tools": "工具",
        "trace": "追踪",
        "track": "跟踪",
        "tree": "树",
        "untracked": "未跟踪",
        "url": "URL",
        "usage": "使用情况",
        "user": "用户",
        "verify": "校验",
        "verbose": "详细",
        "volume": "音量",
        "warn": "警告",
        "warnings": "警告",
        "web": "网页",
        "welcome": "欢迎",
        "window": "窗口",
        "workspace": "工作区",
        "worker": "执行",
        "explorer": "探索",
        "baseline": "基线",
        "candidate": "候选",
        "main": "主",
        "safe": "安全",
    },
    "en": {
        "api": "API",
        "ascii": "ASCII",
        "llm": "LLM",
        "max": "Max",
        "ssl": "SSL",
        "url": "URL",
    },
}

IDENTIFIER_LABELS = {
    "zh": {
        "provider_id": {
            "remote_main": "远程主服务",
            "local_main": "本地主服务",
            "deepseek_main": "DeepSeek 主服务",
            "openai_main": "OpenAI 主服务",
            "anthropic_main": "Anthropic 主服务",
            "google_main": "Google 主服务",
            "dashscope_main": "阿里云主服务",
            "siliconflow_main": "硅基流动主服务",
            "minimax_main": "MiniMax 主服务",
        },
        "profile_id": {
            "primary": "主智能体",
            "mental_model": "心智模型",
            "subagent_worker": "执行子智能体",
            "subagent_explorer": "探索子智能体",
            "supervised_baseline": "监督基线",
            "supervised_candidate": "监督候选",
            "compression": "压缩模型",
        },
        "provider_kind": {
            "local": "本地",
            "deepseek": "DeepSeek",
            "minimax": "MiniMax",
            "openai": "OpenAI",
            "anthropic": "Anthropic",
            "google": "Google",
            "aliyun": "阿里云",
            "siliconflow": "硅基流动",
        },
    },
    "en": {
        "provider_id": {
            "remote_main": "Remote Main",
            "local_main": "Local Main",
            "deepseek_main": "DeepSeek Main",
            "openai_main": "OpenAI Main",
            "anthropic_main": "Anthropic Main",
            "google_main": "Google Main",
            "dashscope_main": "DashScope Main",
            "siliconflow_main": "SiliconFlow Main",
            "minimax_main": "MiniMax Main",
        },
        "profile_id": {
            "primary": "Primary Agent",
            "mental_model": "Mental Model",
            "subagent_worker": "Subagent Worker",
            "subagent_explorer": "Subagent Explorer",
            "supervised_baseline": "Supervised Baseline",
            "supervised_candidate": "Supervised Candidate",
            "compression": "Compression Model",
        },
        "provider_kind": {
            "local": "Local",
            "deepseek": "DeepSeek",
            "minimax": "MiniMax",
            "openai": "OpenAI",
            "anthropic": "Anthropic",
            "google": "Google",
            "aliyun": "Aliyun",
            "siliconflow": "SiliconFlow",
        },
    },
}


def resolve_lang(raw_lang: str | None) -> str:
    lang = (raw_lang or DEFAULT_LANG).strip().lower()
    return lang if lang in I18N else DEFAULT_LANG


def get_config_language(public_config: dict) -> str:
    ui = public_config.get("ui")
    if not isinstance(ui, dict):
        return DEFAULT_LANG
    return resolve_lang(ui.get("language"))


def _humanize_token(token: str, lang: str) -> str:
    lowered = token.lower()
    override = TOKEN_LABELS.get(lang, {}).get(lowered)
    if override:
        return override
    if lang == "zh":
        return token.upper() if token.isupper() else token
    return " ".join(part.upper() if part.isupper() else part.capitalize() for part in token.split())


def _localize_identifier(kind: str, value: str, lang: str) -> str:
    token = str(value or "").strip()
    if not token:
        return ""
    exact = IDENTIFIER_LABELS.get(lang, {}).get(kind, {}).get(token)
    if exact:
        return exact
    return localize_label(f"{kind}.{token}", token, lang)


def _display_provider_id(provider_id: str, lang: str) -> str:
    return _localize_identifier("provider_id", provider_id, lang)


def _display_profile_id(profile_id: str, lang: str) -> str:
    return _localize_identifier("profile_id", profile_id, lang)


def _display_provider_kind(provider_kind: str, lang: str) -> str:
    return _localize_identifier("provider_kind", provider_kind, lang)


def _public_provider(provider: dict | None) -> dict:
    if not isinstance(provider, dict):
        return {}
    payload = {}
    for key in LLM_PROVIDER_EDIT_FIELDS:
        if key in provider:
            payload[key] = copy.deepcopy(provider[key])
    return payload


def _provider_signature(provider: dict | None) -> str:
    return json.dumps(_public_provider(provider), ensure_ascii=False, sort_keys=True)


def _provider_field_label(field_name: str, lang: str) -> str:
    labels = {
        "kind": I18N[lang]["provider_kind"],
        "base_url": I18N[lang]["provider_base_url"],
        "api_key_env": I18N[lang]["provider_api_key_env"],
        "compat_mode": I18N[lang]["provider_compat_mode"],
        "requires_api_key": I18N[lang]["provider_requires_api_key"],
        "context_window": I18N[lang]["provider_context_window"],
        "extra_headers": I18N[lang]["provider_extra_headers"],
    }
    return labels.get(field_name, localize_label(f"provider.{field_name}", field_name, lang))


def _provider_summary(provider: dict | None, lang: str) -> str:
    entry = _public_provider(provider)
    parts = []
    kind = str(entry.get("kind", "")).strip()
    if kind:
        parts.append(_display_provider_kind(kind, lang))
    base_url = str(entry.get("base_url", "")).strip()
    if base_url:
        parts.append(base_url)
    return " / ".join(parts)


def localize_label(path: str, fallback: str, lang: str) -> str:
    exact = FIELD_LABELS.get(lang, {}).get(path)
    if exact:
        return exact

    token = fallback.strip()
    if not token:
        token = path.split(".")[-1]
    parts = [part for part in token.split("_") if part]
    if not parts:
        return token
    if lang == "zh":
        return "".join(_humanize_token(part, lang) for part in parts)
    return " ".join(_humanize_token(part, lang) for part in parts)


def localize_section_label(path: str, fallback: str, lang: str) -> str:
    exact = SECTION_LABELS.get(lang, {}).get(path)
    if exact:
        return exact
    return localize_label(path, fallback, lang)


def _model_library_field_label(field_name: str, lang: str) -> str:
    return localize_label(f"llm.model_library.{field_name}", field_name, lang)


def _model_library_option_label(field_name: str, value: str, lang: str) -> str:
    return localize_label(f"llm.model_library.{field_name}.{value}", value, lang)


def _render_model_library_options(field_name: str, values: tuple[str, ...], selected: str, lang: str) -> str:
    return "".join(
        f'<option value="{html.escape(value)}"{" selected" if value == selected else ""}>'
        f"{html.escape(_model_library_option_label(field_name, value, lang))}</option>"
        for value in values
    )


def _model_library_detail_summary(transport: str, contract: str, details: dict, lang: str) -> str:
    parts = []
    if transport:
        parts.append(_model_library_option_label("transport", transport, lang))
    if contract:
        parts.append(_model_library_option_label("contract", contract, lang))
    if "temperature" in details:
        parts.append(f'{_model_library_field_label("temperature", lang)} {details["temperature"]}')
    if "max_output_tokens" in details:
        parts.append(f'{details["max_output_tokens"]} {_humanize_token("tokens", lang)}')
    if "timeout" in details:
        parts.append(f'{details["timeout"]}{" 秒" if lang == "zh" else "s"}')
    return " / ".join(parts)


def _empty_draft_meta() -> dict[str, object]:
    return {
        "pending_api_keys": {},
        "pending_cleared_api_keys": [],
    }


def _normalize_draft_meta(meta: dict | None) -> dict[str, object]:
    payload = _empty_draft_meta()
    if not isinstance(meta, dict):
        return payload
    pending = meta.get("pending_api_keys", {})
    if isinstance(pending, dict):
        payload["pending_api_keys"] = {
            str(key).strip(): str(value)
            for key, value in pending.items()
            if str(key).strip() and str(value) != ""
        }
    cleared = meta.get("pending_cleared_api_keys", [])
    if isinstance(cleared, list):
        payload["pending_cleared_api_keys"] = [
            str(item).strip()
            for item in cleared
            if str(item).strip()
        ]
    return payload


def _move_pending_api_key_env(meta: dict[str, object], old_env: str, new_env: str) -> dict[str, object]:
    payload = _normalize_draft_meta(meta)
    old_env = str(old_env or "").strip()
    new_env = str(new_env or "").strip()
    if not old_env or old_env == new_env:
        return payload
    pending = payload["pending_api_keys"]
    cleared = payload["pending_cleared_api_keys"]
    if isinstance(pending, dict) and old_env in pending and new_env:
        pending[new_env] = pending.pop(old_env)
    elif isinstance(pending, dict):
        pending.pop(old_env, None)
    if isinstance(cleared, list):
        payload["pending_cleared_api_keys"] = [
            new_env if item == old_env and new_env else item
            for item in cleared
            if item != old_env or new_env
        ]
    return payload


def _api_key_display_state(api_key_env: str, configured: bool, draft_meta: dict | None) -> tuple[bool, str]:
    env_name = str(api_key_env or "").strip()
    meta = _normalize_draft_meta(draft_meta)
    pending = meta["pending_api_keys"]
    cleared = meta["pending_cleared_api_keys"]
    if env_name and isinstance(pending, dict) and env_name in pending:
        return True, "pending"
    if env_name and isinstance(cleared, list) and env_name in cleared:
        return False, "clear_pending"
    return configured, "configured" if configured else "missing"


def _selected_model_option(public_config: dict, profile: dict) -> dict | None:
    model_ref = str(profile.get("model_ref", "")).strip()
    if model_ref:
        if model_ref == UNCONFIGURED_MODEL_REF:
            return None
        for option in list_llm_model_options(public_config):
            if str(option.get("model_id", "")).strip() == model_ref:
                return option
        return None

    provider_signature = _provider_signature(profile.get("provider"))
    model = str(profile.get("model", "")).strip()
    if not provider_signature or not model:
        return None
    for option in list_llm_model_options(public_config):
        option_provider = _public_provider(option.get("provider", {}))
        if _provider_signature(option_provider) == provider_signature and str(option.get("model", "")).strip() == model:
            return option
    return None


def _missing_required_llm_profiles(public_config: dict) -> list[str]:
    llm = public_config.get("llm", {})
    profiles = llm.get("profiles", {}) if isinstance(llm, dict) else {}
    if not isinstance(profiles, dict):
        return []
    missing: list[str] = []
    for profile_id, profile in profiles.items():
        if not isinstance(profile, dict):
            missing.append(str(profile_id))
            continue
        if _selected_model_option(public_config, profile) is None:
            missing.append(str(profile_id))
    return missing


def _validate_required_llm_profiles(public_config: dict, lang: str) -> None:
    missing = _missing_required_llm_profiles(public_config)
    if not missing:
        return
    display_names = "、".join(_display_profile_id(profile_id, lang) for profile_id in missing)
    raise ValueError(f'{I18N[lang]["profile_model_missing"]} {display_names}')


def list_llm_profile_options(public_config: dict, lang: str = DEFAULT_LANG) -> list[dict[str, str]]:
    llm = public_config.get("llm", {})
    profiles = llm.get("profiles", {}) if isinstance(llm, dict) else {}
    options: list[dict[str, str]] = []
    if not isinstance(profiles, dict):
        return options
    for profile_id, profile in profiles.items():
        if not isinstance(profile, dict):
            continue
        model = str(profile.get("model", ""))
        options.append(
            {
                "profile_id": str(profile_id),
                "model": model,
                "label": _display_profile_id(str(profile_id), lang),
            }
        )
    return options


def _default_model_api_key_env(model_id: str) -> str:
    token = "".join(char if char.isalnum() else "_" for char in str(model_id or "").upper()).strip("_")
    return f"VIBELUTION_LLM_{token}_API_KEY" if token else "VIBELUTION_LLM_MODEL_API_KEY"


def _broadcast_windows_environment_change(timeout_ms: int = 5000) -> None:
    try:
        import ctypes
    except ImportError:
        return
    hwnd_broadcast = 0xFFFF
    wm_settingchange = 0x001A
    smto_abortifhung = 0x0002
    result = ctypes.c_size_t()
    try:
        ctypes.windll.user32.SendMessageTimeoutW(
            hwnd_broadcast,
            wm_settingchange,
            0,
            "Environment",
            smto_abortifhung,
            timeout_ms,
            ctypes.byref(result),
        )
    except Exception:
        return


def _write_windows_user_env_var(name: str, value: str | None) -> None:
    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
        if value is None:
            try:
                winreg.DeleteValue(key, name)
            except FileNotFoundError:
                pass
        else:
            reg_type = winreg.REG_EXPAND_SZ if "%" in value else winreg.REG_SZ
            winreg.SetValueEx(key, name, 0, reg_type, value)
    _broadcast_windows_environment_change()


def _set_user_env_var(name: str, value: str) -> None:
    name = validate_llm_api_key_env(name, required=True)
    os.environ[name] = value
    if os.name != "nt":
        return
    _write_windows_user_env_var(name, value)


def _delete_user_env_var(name: str) -> None:
    name = validate_llm_api_key_env(name, required=False)
    if not name:
        return
    os.environ.pop(name, None)
    if os.name != "nt":
        return
    _write_windows_user_env_var(name, None)


def set_llm_model_api_key(public_config: dict, model_id: str, api_key: str) -> str:
    llm = public_config.get("llm", {})
    model_library = llm.get("model_library", {}) if isinstance(llm, dict) else {}
    item = model_library.get(model_id, {}) if isinstance(model_library, dict) else {}
    if not isinstance(item, dict):
        raise ValueError(f"unknown LLM model: {model_id}")
    api_key_env = validate_llm_api_key_env(
        str(item.get("api_key_env") or _default_model_api_key_env(model_id)).strip(),
        required=True,
    )
    item["api_key_env"] = api_key_env
    _set_user_env_var(api_key_env, api_key)
    return api_key_env


def clear_llm_model_api_key(public_config: dict, model_id: str) -> str:
    llm = public_config.get("llm", {})
    model_library = llm.get("model_library", {}) if isinstance(llm, dict) else {}
    item = model_library.get(model_id, {}) if isinstance(model_library, dict) else {}
    if not isinstance(item, dict):
        raise ValueError(f"unknown LLM model: {model_id}")
    api_key_env = validate_llm_api_key_env(
        str(item.get("api_key_env") or _default_model_api_key_env(model_id)).strip(),
        required=True,
    )
    item["api_key_env"] = api_key_env
    _delete_user_env_var(api_key_env)
    return api_key_env


def _find_profile_id_for_provider(public_config: dict, provider_id: str) -> str:
    llm = public_config.get("llm", {})
    profiles = llm.get("profiles", {}) if isinstance(llm, dict) else {}
    if not isinstance(profiles, dict):
        raise ValueError("llm.profiles must be an object")
    for profile_id, profile in profiles.items():
        if isinstance(profile, dict) and profile.get("provider_id") == provider_id:
            return str(profile_id)
    raise ValueError(f"no LLM profile uses provider: {provider_id}")


def _probe_llm_http(provider, profile, api_key: str | None = None) -> dict:
    if provider.requires_api_key and not api_key:
        return {"ok": False, "message": f"missing API key for provider `{provider.provider_id}`"}
    if not provider.requires_api_key:
        api_key = None
    if not provider.base_url:
        return {"ok": False, "message": f"missing base_url for provider `{provider.provider_id}`"}
    try:
        validate_llm_provider_target(provider, context="probe", resolve_dns=True)
    except ValueError as exc:
        return {"ok": False, "message": str(exc)}

    base_url = provider.base_url.rstrip("/")
    url = f"{base_url}/chat/completions"
    payload = {
        "model": profile.model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
        "temperature": 0,
        "stream": False,
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        timeout = coerce_llm_probe_timeout(profile.connect_timeout, profile.timeout)
        opener = urllib.request.build_opener(_NoRedirectHandler)
        with opener.open(request, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            if 200 <= status < 300:
                return {"ok": True, "message": f"connected to {profile.model}"}
            return {"ok": False, "message": f"HTTP {status}"}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "message": f"HTTP {exc.code}: {exc.reason}"}
    except Exception as exc:
        return {"ok": False, "message": redact_llm_probe_error(str(exc), api_key=api_key)}


def test_llm_connection(public_config: dict, profile_id: str | None = None, draft_meta: dict | None = None) -> dict:
    validate_llm_public_config(public_config)
    effective = build_effective_config(public_config)
    profile = effective.llm.get_profile(profile_id=profile_id) if profile_id else effective.llm.get_profile(role="primary")
    provider = effective.llm.get_provider(profile.provider_id)
    api_key = effective.get_api_key_for_profile(profile_id=profile.profile_id)
    api_key_source = effective.llm.get_api_key_source_label_for_profile(profile_id=profile.profile_id)
    if not provider.requires_api_key:
        api_key = None
        api_key_source = "not-required"
    meta = _normalize_draft_meta(draft_meta)
    pending = meta["pending_api_keys"]
    cleared = meta["pending_cleared_api_keys"]
    profile_public = (
        public_config.get("llm", {}).get("profiles", {}).get(profile.profile_id, {})
        if isinstance(public_config.get("llm", {}), dict)
        else {}
    )
    profile_api_key_env = str(profile_public.get("api_key_env", "")).strip() if isinstance(profile_public, dict) else ""
    provider_api_key_env = str(getattr(provider, "api_key_env", "") or "").strip()
    if provider.requires_api_key:
        if isinstance(cleared, list) and profile_api_key_env and profile_api_key_env in cleared:
            api_key = None
            api_key_source = f"pending-clear:{profile_api_key_env}"
        elif isinstance(cleared, list) and provider_api_key_env and provider_api_key_env in cleared:
            api_key = None
            api_key_source = f"pending-clear:{provider_api_key_env}"
        elif isinstance(pending, dict) and profile_api_key_env and profile_api_key_env in pending:
            api_key = pending[profile_api_key_env]
            api_key_source = f"pending-env:{profile_api_key_env}"
        elif isinstance(pending, dict) and provider_api_key_env and provider_api_key_env in pending:
            api_key = pending[provider_api_key_env]
            api_key_source = f"pending-env:{provider_api_key_env}"
    try:
        result = _probe_llm_http(provider, profile, api_key)
    except TypeError:
        result = _probe_llm_http(provider, profile)
    return {
        **result,
        "profile_id": profile.profile_id,
        "provider_id": provider.provider_id,
        "provider_kind": provider.kind,
        "base_url": provider.base_url,
        "model": profile.model,
        "api_key_source": api_key_source,
    }


def test_llm_connection_by_provider(public_config: dict, provider_id: str) -> dict:
    profile_id = _find_profile_id_for_provider(public_config, provider_id)
    return test_llm_connection(public_config, profile_id)


def _json_for_attr(value) -> str:
    return html.escape(json.dumps(value, ensure_ascii=False))


def _original_value_attr(value) -> str:
    return f" data-original-value=\"{_json_for_attr(value)}\""


def _format_field_display_value(path: str, value) -> str:
    if _is_secret_path(path):
        return "(configured)" if value else "(empty)"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) if value else "(empty)"
    if value in ("", None):
        return "(empty)"
    return str(value)


def _field_hint(path: str, lang: str) -> str:
    return FIELD_HINTS.get(lang, {}).get(path, "")


def _is_secret_path(path: str) -> bool:
    return path.split(".")[-1] == "api_key"


def _field_kind(path: str, value, options: list[str] | None = None) -> tuple[str, str]:
    if isinstance(value, bool):
        return "toggle", "开关"
    if options:
        return "select", "选项" if path else "选项"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "timeout" in path or "interval" in path or "runtime" in path:
            return "number", "秒" if "." in path else "秒"
        if "tokens" in path or "token" in path or "context_window" in path:
            return "number", "令牌"
        return "number", "数值"
    if isinstance(value, list):
        return "list", "列表"
    if _is_secret_path(path):
        return "secret", "密钥"
    if "url" in path or "api_base" in path:
        return "url", "地址"
    if "path" in path or "workspace" in path:
        return "path", "路径"
    return "text", "文本"


def _badge_text(text: str, lang: str) -> str:
    if lang == "en":
        mapping = {
            "开关": "Toggle",
            "选项": "Option",
            "数值": "Number",
            "令牌": "Token",
            "列表": "List",
            "密钥": "Secret",
            "地址": "URL",
            "路径": "Path",
            "文本": "Text",
            "秒": "Seconds",
        }
        return mapping.get(text, text)
    return text


def _render_field_shell(path: str, label: str, lang: str, control_html: str, *, kind: str, badge: str, hint: str = "", value=None) -> str:
    safe_label = html.escape(localize_label(path, label, lang))
    hint_html = f'<div class="field-hint">{html.escape(hint)}</div>' if hint else '<div class="field-hint muted"> </div>'
    badge_html = f'<span class="field-badge">{html.escape(_badge_text(badge, lang))}</span>' if badge else ""
    safe_value = html.escape(_format_field_display_value(path, value))
    return (
        f'<div class="field field-{html.escape(kind)}">'
        f'<div class="field-head"><span class="field-label">{safe_label}</span>{badge_html}</div>'
        f"{hint_html}"
        f'<div class="field-view"><span class="field-value">{safe_value}</span></div>'
        f'<div class="field-editor" hidden>'
        f'<div class="field-control">{control_html}</div>'
        f"</div>"
        f"</div>"
    )


def _render_select(path: str, current: str, options: list[str], label: str, lang: str, onchange: str = "") -> str:
    attrs = f' data-path="{path}"{_original_value_attr(current)}'
    if onchange:
        attrs += f' onchange="{html.escape(onchange, quote=True)}"'
    options_html = "".join(
        f'<option value="{html.escape(option)}" {"selected" if option == current else ""}>{html.escape(option)}</option>'
        for option in options
    )
    kind, badge = _field_kind(path, current, options)
    control_html = f"<select{attrs}>{options_html}</select>"
    return _render_field_shell(path, label, lang, control_html, kind=kind, badge=badge, hint=_field_hint(path, lang), value=current)


def _render_input(path: str, value, label: str, lang: str) -> str:
    if path == "ui.language":
        control_html = (
            f'<select data-path="{path}"{_original_value_attr(str(value))} onchange="syncLanguageControls(this.value, \'body\')">'
            f'<option value="zh" {"selected" if resolve_lang(str(value)) == "zh" else ""}>{html.escape(I18N[lang]["lang_zh"])}</option>'
            f'<option value="en" {"selected" if resolve_lang(str(value)) == "en" else ""}>{html.escape(I18N[lang]["lang_en"])}</option>'
            f"</select>"
        )
        return _render_field_shell(path, label, lang, control_html, kind="select", badge="选项", hint=_field_hint(path, lang), value=value)
    if path == "runtime.profile":
        return _render_select(path, str(value), RUNTIME_PROFILE_OPTIONS, label, lang)
    if path == "avatar.preset":
        return _render_select(path, str(value), AVATAR_PRESET_OPTIONS, label, lang)
    if path in {"agent.default_mode", "agent.modes.default_shell_mode", "agent.modes.default_headless_mode"}:
        return _render_select(path, str(value), AGENT_MODE_OPTIONS, label, lang)
    if path == "agent.modes.explicit_evolution_request_behavior":
        return _render_select(path, str(value), EVOLUTION_REQUEST_BEHAVIOR_OPTIONS, label, lang)
    if path == "evolution.chat_dataset.segmentation_strategy":
        return _render_select(path, str(value), SEGMENTATION_STRATEGY_OPTIONS, label, lang)

    hint = _field_hint(path, lang)
    if isinstance(value, bool):
        checked = "checked" if value else ""
        control_html = (
            f'<label class="toggle-row"><input type="checkbox" data-path="{path}"{_original_value_attr(value)} {checked}>'
            f'<span class="toggle-pill"></span></label>'
        )
        return _render_field_shell(path, label, lang, control_html, kind="toggle", badge="开关", hint=hint, value=value)

    if isinstance(value, int) and not isinstance(value, bool):
        kind, badge = _field_kind(path, value)
        control_html = f'<input type="number" data-path="{path}"{_original_value_attr(value)} value="{html.escape(str(value))}">'
        return _render_field_shell(path, label, lang, control_html, kind=kind, badge=badge, hint=hint, value=value)

    if isinstance(value, float):
        kind, badge = _field_kind(path, value)
        control_html = f'<input type="number" step="any" data-path="{path}"{_original_value_attr(value)} value="{html.escape(str(value))}">'
        return _render_field_shell(path, label, lang, control_html, kind=kind, badge=badge, hint=hint, value=value)

    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        text = "\n".join(value)
        control_html = f'<textarea data-path="{path}" data-kind="string-list"{_original_value_attr(value)}>{html.escape(text)}</textarea>'
        return _render_field_shell(path, label, lang, control_html, kind="list", badge="列表", hint=hint, value=value)

    if isinstance(value, str) and _is_secret_path(path):
        placeholder = "(configured)" if value else ""
        control_html = f'<input type="password" data-path="{path}"{_original_value_attr("")} value="" placeholder="{html.escape(placeholder)}">'
        return _render_field_shell(path, label, lang, control_html, kind="secret", badge="密钥", hint=hint, value=value)

    kind, badge = _field_kind(path, value)
    input_type = "text"
    if kind in {"url", "path"}:
        input_type = "text"
    control_html = f'<input type="{input_type}" data-path="{path}"{_original_value_attr(value)} value="{html.escape(str(value))}">'
    return _render_field_shell(path, label, lang, control_html, kind=kind, badge=badge, hint=hint, value=value)


def _dom_id_from_path(path: str) -> str:
    return "".join(char if char.isalnum() else "-" for char in path).strip("-")


def _llm_profile_select(public_config: dict, selected_profile_id: str, select_id: str, lang: str) -> str:
    options = []
    for option in list_llm_profile_options(public_config, lang):
        profile_id = option["profile_id"]
        selected = " selected" if profile_id == selected_profile_id else ""
        options.append(
            f'<option value="{html.escape(profile_id)}"{selected}>{html.escape(option["label"])}</option>'
        )
    return f'<select id="{html.escape(select_id)}" class="card-profile-select">{"".join(options)}</select>'


def _llm_model_select(
    public_config: dict,
    selected_provider: dict | None,
    selected_model: str,
    select_id: str,
    profile_id: str,
    lang: str,
) -> str:
    selected_signature = _provider_signature(selected_provider)
    options = []
    matched = False
    for option in list_llm_model_options(public_config):
        option_provider = _public_provider(option.get("provider", {}))
        option_signature = _provider_signature(option_provider)
        option_model = str(option["model"])
        option_model_id = str(option["model_id"])
        option_label = str(option["label"])
        option_provider_kind = str(option["provider_kind"])
        selected = " selected" if option_signature == selected_signature and option_model == selected_model else ""
        if selected:
            matched = True
        details_json = html.escape(json.dumps(option.get("details", {}), ensure_ascii=False), quote=True)
        provider_json = html.escape(json.dumps(option_provider, ensure_ascii=False), quote=True)
        options.append(
            f'<option value="{html.escape(option_model_id)}"{selected} '
            f'data-provider="{provider_json}" '
            f'data-model="{html.escape(option_model)}" '
            f'data-label="{html.escape(option_label)}" '
            f'data-api-key-env="{html.escape(str(option.get("api_key_env", "")))}" '
            f'data-details="{details_json}">'
            f'{html.escape(option_label)} / {html.escape(_display_provider_kind(option_provider_kind, lang))}</option>'
        )
    disabled = " disabled" if not options else ""
    placeholder_selected = " selected" if not matched else ""
    placeholder = (
        f'<option value=""{placeholder_selected}>'
        f'{html.escape(I18N[lang]["select_model_placeholder"])}</option>'
    )
    required_class = " is-required" if not matched else ""
    return (
        f'<select id="{html.escape(select_id)}" class="card-profile-select{required_class}" '
        f'data-profile-id="{html.escape(profile_id)}"{disabled}>{placeholder}{"".join(options)}</select>'
    )


def _llm_model_id_select(public_config: dict, selected_model_id: str, select_id: str, lang: str) -> str:
    options = []
    for option in list_llm_model_options(public_config):
        option_model_id = str(option["model_id"])
        option_label = str(option["label"])
        option_provider_kind = str(option["provider_kind"])
        option_model = str(option["model"])
        selected = " selected" if option_model_id == selected_model_id else ""
        options.append(
            f'<option value="{html.escape(option_model_id)}"{selected}>'
            f'{html.escape(option_label)} / {html.escape(_display_provider_kind(option_provider_kind, lang))} / '
            f'{html.escape(option_model)}</option>'
        )
    disabled = " disabled" if not options else ""
    return f'<select id="{html.escape(select_id)}" class="card-profile-select"{disabled}>{"".join(options)}</select>'


def _primary_profile_id(public_config: dict) -> str:
    llm = public_config.get("llm", {})
    if not isinstance(llm, dict):
        return "primary"
    profiles = llm.get("profiles", {})
    if isinstance(profiles, dict) and "primary" in profiles:
        return "primary"
    if isinstance(profiles, dict) and profiles:
        return str(next(iter(profiles)))
    return "primary"


def _profile_group_key(profile_id: str) -> str:
    token = str(profile_id or "").strip()
    if token in {"supervised_baseline", "supervised_candidate"} or token.startswith("supervised_"):
        return "supervised"
    return "unsupervised"


def _profile_group_title(group_key: str, lang: str) -> str:
    mapping = {
        "unsupervised": I18N[lang]["profile_group_unsupervised"],
        "supervised": I18N[lang]["profile_group_supervised"],
    }
    return mapping.get(group_key, group_key)


def _group_profile_ids(profile_map: dict) -> dict[str, list[str]]:
    grouped = {"unsupervised": [], "supervised": []}
    for profile_id in profile_map.keys():
        grouped.setdefault(_profile_group_key(str(profile_id)), []).append(str(profile_id))
    return grouped


def _render_group_block(title: str, count: int, content_html: str, *, group_kind: str) -> str:
    return (
        f'<section class="llm-group-band" data-llm-group="{html.escape(group_kind)}">'
        f'<div class="llm-group-band-header">'
        f'<span class="llm-group-band-title">{html.escape(title)}</span>'
        f'<span class="section-count">{count}</span>'
        f"</div>"
        f'<div class="llm-group-band-content">{content_html}</div>'
        f"</section>"
    )


def _render_config_object_card(
    public_config: dict,
    path: str,
    value: dict,
    lang: str,
    *,
    title_override: str | None = None,
) -> str:
    if not isinstance(value, dict):
        raise ValueError(f"config path is not an object card: {path}")
    key = path.split(".")[-1] if path else ""
    title = title_override or localize_section_label(path, key, lang)
    if path == "llm.profiles":
        content_html = _render_llm_profile_groups(value, path, lang, public_config)
    else:
        parent_path = path.rsplit(".", 1)[0] if "." in path else ""
        if parent_path == "llm.providers":
            title = _display_provider_id(key, lang)
        elif parent_path == "llm.profiles":
            title = _display_profile_id(key, lang)
        content_html = _render_group_fields(value, path, lang, public_config)
    return _render_collapsible_card(
        path,
        title,
        content_html,
        count=len(value),
        actions_html=_card_actions(path, lang, public_config),
        lang=lang,
    )


def _render_llm_profile_card(public_config: dict, profile_id: str, lang: str) -> str:
    llm = public_config.get("llm", {})
    profiles = llm.get("profiles", {}) if isinstance(llm, dict) else {}
    if not isinstance(profiles, dict):
        raise ValueError("llm.profiles must be an object")
    value = profiles.get(profile_id, {})
    if not isinstance(value, dict):
        raise ValueError(f"unknown LLM profile: {profile_id}")
    path = f"llm.profiles.{profile_id}"
    return _render_config_object_card(public_config, path, value, lang)


def _lookup_config_path_value(public_config: dict, path: str):
    current = public_config
    for part in [token for token in str(path or "").split(".") if token]:
        if isinstance(current, dict):
            if part not in current:
                raise ValueError(f"unknown config path: {path}")
            current = current[part]
            continue
        if isinstance(current, list) and part.isdigit():
            index = int(part)
            if index < 0 or index >= len(current):
                raise ValueError(f"unknown config path: {path}")
            current = current[index]
            continue
        raise ValueError(f"unknown config path: {path}")
    return current


def _render_config_card_preview(public_config: dict, card_path: str, lang: str) -> str:
    resolved_path = str(card_path or "").strip()
    if not resolved_path:
        raise ValueError("card_path is required")
    value = _lookup_config_path_value(public_config, resolved_path)
    if not isinstance(value, dict):
        raise ValueError(f"config path is not an object card: {resolved_path}")
    return _render_config_object_card(public_config, resolved_path, value, lang)


def _render_llm_profile_groups(data: dict, prefix: str, lang: str, public_config: dict) -> str:
    cards: list[str] = [_render_inline_llm_profile_card(public_config, lang)]
    grouped = _group_profile_ids(data)
    for group_key in ("unsupervised", "supervised"):
        profile_ids = grouped.get(group_key, [])
        if not profile_ids:
            continue
        group_cards: list[str] = ['<div class="section-grid">']
        for profile_id in profile_ids:
            value = data.get(profile_id, {})
            if not isinstance(value, dict):
                continue
            group_cards.append(_render_llm_profile_card(public_config, profile_id, lang))
        group_cards.append("</div>")
        cards.append(
            _render_group_block(
                _profile_group_title(group_key, lang),
                len(profile_ids),
                "".join(group_cards),
                group_kind=group_key,
            )
        )
    return "".join(cards)


def _render_inline_llm_profile_card(public_config: dict, lang: str) -> str:
    t = I18N[lang]
    source_profile_options = "".join(
        f'<option value="{html.escape(str(option["profile_id"]))}">{html.escape(str(option["label"]))}</option>'
        for option in list_llm_profile_options(public_config, lang)
    )
    return (
        f'<div id="add-llm-profile-card" class="inline-add-card" hidden>'
        f'<div class="model-library-edit">'
        f'<label><span>{html.escape(t["prompt_profile_id"])}</span><input type="text" data-add-profile-field="profile_id"></label>'
        f'<label><span>{html.escape(t["prompt_source_profile_id"])}</span><select data-add-profile-field="source_profile_id">{source_profile_options}</select></label>'
        f'<label><span>{html.escape(t["prompt_model_id"])}</span>{_llm_model_id_select(public_config, "", "add-llm-profile-model", lang)}</label>'
        f'<div class="model-library-actions">'
        f'<button type="button" class="card-action subtle" onclick="saveInlineLlmProfile()">{html.escape(t["save_model"])}</button>'
        f'<button type="button" class="card-action" onclick="cancelInlineLlmProfile()">{html.escape(t["cancel"])}</button>'
        f"</div>"
        f"</div>"
        f"</div>"
    )


def _profile_card_actions(path: str, lang: str, public_config: dict) -> str:
    prefix = "llm.profiles."
    if not path.startswith(prefix) or path.count(".") != 2:
        return ""
    profile_id = path.removeprefix(prefix)
    safe_profile = html.escape(profile_id)
    select_id = f"llm-model-switch-{_dom_id_from_path(path)}"
    llm = public_config.get("llm", {})
    profile = llm.get("profiles", {}).get(profile_id, {}) if isinstance(llm, dict) and isinstance(llm.get("profiles", {}), dict) else {}
    selected_option = _selected_model_option(public_config, profile if isinstance(profile, dict) else {})
    if selected_option:
        selected_provider = _public_provider(selected_option.get("provider", {}))
        selected_model = str(selected_option.get("model", ""))
    else:
        selected_provider = _public_provider(profile.get("provider")) if isinstance(profile, dict) else {}
        selected_model = str(profile.get("model", "")) if isinstance(profile, dict) else ""
    missing_required = selected_option is None
    t = I18N[lang]
    required_badge = (
        f'<span class="required-indicator" data-profile-required="{safe_profile}">* {html.escape(t["required_field"])}</span>'
        if missing_required
        else ""
    )
    return (
        f'<div class="card-actions" data-profile-actions="{safe_profile}">'
        f'{_llm_model_select(public_config, selected_provider, selected_model, select_id, profile_id, lang)}'
        f"{required_badge}"
        f'<button type="button" class="card-action subtle" onclick="cloneLlmProfile(\'{safe_profile}\', \'{html.escape(select_id)}\')">{html.escape(t["add_llm"])}</button>'
        f'<button type="button" class="card-action subtle" onclick="applySelectedProfileModel(\'{html.escape(select_id)}\')">{html.escape(t["apply_model"])}</button>'
        f'<button type="button" class="card-action" onclick="testSelectedProfileModel(\'{html.escape(select_id)}\')">{html.escape(t["test_provider"])}</button>'
        f"</div>"
    )


def _provider_card_actions(path: str, lang: str, public_config: dict) -> str:
    return ""


def _card_actions(path: str, lang: str, public_config: dict) -> str:
    return _profile_card_actions(path, lang, public_config) or _provider_card_actions(path, lang, public_config)


def _render_collapsible_card(path: str, title: str, content_html: str, *, count: int | None = None, actions_html: str = "", lang: str = DEFAULT_LANG) -> str:
    safe_id = html.escape(_dom_id_from_path(path))
    safe_path = html.escape(path)
    safe_title = html.escape(title)
    count_html = f'<span class="section-count">{count}</span>' if count is not None else ""
    t = I18N[lang]
    card_controls = (
        f'<div class="card-edit-controls">'
        f'<button type="button" class="card-action subtle card-edit-button" onclick="editConfigCard(this)">{html.escape(t["edit_model"])}</button>'
        f'<button type="button" class="card-action subtle card-save-button" onclick="saveConfigCard(this)" hidden>{html.escape(t["save_model"])}</button>'
        f'<button type="button" class="card-action card-cancel-button" onclick="cancelConfigCard(this)" hidden>{html.escape(t["cancel"])}</button>'
        f"</div>"
    )
    return (
        f'<div id="config-card-{safe_id}" class="collapsible-card is-collapsed" '
        f'data-collapsible-card="true" data-card-path="{safe_path}">'
        f'<div class="card-header-shell">'
        f'<button class="card-header" type="button" aria-expanded="false" '
        f'aria-controls="card-content-{safe_id}" onclick="toggleSection(this)">'
        f'<span class="section-title-wrap"><span class="section-chevron" aria-hidden="true">›</span>'
        f'<span class="card-title">{safe_title}</span></span>'
        f"{count_html}"
        f"</button>"
        f"{actions_html}"
        f"{card_controls}"
        f"</div>"
        f'<div class="card-content" id="card-content-{safe_id}" hidden>'
        f"{content_html}"
        f"</div>"
        f"</div>"
    )


def _render_group_fields(data: dict, prefix: str, lang: str, public_config: dict) -> str:
    body: list[str] = ['<div class="section-grid">']
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            body.append(_render_config_object_card(public_config, path, value, lang))
        elif isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
            cards = [f'<div class="list-of-objects" data-path="{path}">']
            for idx, item in enumerate(value):
                item_path = f"{path}.{idx}"
                cards.append(
                    _render_config_object_card(
                        public_config,
                        item_path,
                        item,
                        lang,
                        title_override=f"{localize_section_label(path, key, lang)}[{idx}]",
                    )
                )
            cards.append("</div>")
            body.append("".join(cards))
        else:
            body.append(_render_input(path, value, key, lang))
    body.append("</div>")
    return "".join(body)


def _render_object(title: str, data: dict, prefix: str, lang: str, public_config: dict) -> str:
    section_title = html.escape(localize_section_label(prefix, title, lang))
    section_hint = html.escape(_field_hint(prefix, lang) or localize_section_label(prefix, title, lang))
    safe_prefix = html.escape(prefix)
    return (
        f'<section class="panel-section config-page" id="section-{safe_prefix}" data-config-page="{safe_prefix}">'
        f'<div class="section-header">'
        f'<span class="section-title-wrap">'
        f'<span><span class="section-title">{section_title}</span><span class="section-hint">{section_hint}</span></span></span>'
        f'<span class="section-count">{len(data)}</span>'
        f'</div>'
        f'<div class="section-content" id="section-content-{safe_prefix}">'
        f"{_render_group_fields(data, prefix, lang, public_config)}"
        f"</div>"
        f"</section>"
    )


def _provider_extra_headers_text(provider: dict | None) -> str:
    headers = _public_provider(provider).get("extra_headers")
    if headers in ("", None):
        return ""
    if isinstance(headers, str):
        return headers
    return json.dumps(headers, ensure_ascii=False)


def _render_provider_editor_fields(provider: dict | None, field_attr: str, lang: str) -> str:
    entry = _public_provider(provider)
    kind = str(entry.get("kind", "") or "openai").strip()
    base_url = str(entry.get("base_url", "")).strip()
    api_key_env = str(entry.get("api_key_env", "")).strip()
    compat_mode = str(entry.get("compat_mode", "") or "openai").strip()
    requires_api_key = bool(entry.get("requires_api_key", True))
    context_window = "" if entry.get("context_window") in ("", None) else str(entry.get("context_window"))
    extra_headers = _provider_extra_headers_text(entry)
    requires_checked = " checked" if requires_api_key else ""
    kind_options = "".join(
        f'<option value="{html.escape(option)}"{" selected" if option == kind else ""}>{html.escape(_display_provider_kind(option, lang) or option)}</option>'
        for option in LLM_PROVIDER_OPTIONS
    )
    compat_options = "".join(
        f'<option value="{html.escape(option)}"{" selected" if option == compat_mode else ""}>{html.escape(option)}</option>'
        for option in LLM_PROVIDER_COMPAT_OPTIONS
    )
    return (
        f'<label><span>{html.escape(_provider_field_label("kind", lang))}</span>'
        f'<select {field_attr}="provider_kind">{kind_options}</select></label>'
        f'<label><span>{html.escape(_provider_field_label("base_url", lang))}</span>'
        f'<input type="text" {field_attr}="provider_base_url" value="{html.escape(base_url)}"></label>'
        f'<label><span>{html.escape(_provider_field_label("api_key_env", lang))}</span>'
        f'<input type="text" {field_attr}="provider_api_key_env" value="{html.escape(api_key_env)}"></label>'
        f'<label><span>{html.escape(_provider_field_label("compat_mode", lang))}</span>'
        f'<select {field_attr}="provider_compat_mode">{compat_options}</select></label>'
        f'<label class="model-library-check"><input type="checkbox" {field_attr}="provider_requires_api_key"{requires_checked}> '
        f'<span>{html.escape(_provider_field_label("requires_api_key", lang))}</span></label>'
        f'<label><span>{html.escape(_provider_field_label("context_window", lang))}</span>'
        f'<input type="number" step="1" min="1" {field_attr}="provider_context_window" value="{html.escape(context_window)}"></label>'
        f'<label class="model-library-full"><span>{html.escape(_provider_field_label("extra_headers", lang))}</span>'
        f'<textarea {field_attr}="provider_extra_headers">{html.escape(extra_headers)}</textarea></label>'
    )


def _render_model_library_section(public_config: dict, lang: str, draft_meta: dict | None = None) -> str:
    t = I18N[lang]
    options = list_llm_model_options(public_config)
    presets = list_llm_model_preset_options()
    preset_options_html = (
        f'<option value="">{html.escape(t["preset_custom"])}</option>'
        + "".join(
            f'<option value="{html.escape(str(preset["preset_id"]))}">{html.escape(str(preset["label"]))}</option>'
            for preset in presets
        )
    )
    cards = []
    for option in options:
        provider = _public_provider(option.get("provider", {}))
        model = str(option["model"])
        label = str(option["label"])
        provider_kind = str(option["provider_kind"])
        model_id = str(option["model_id"])
        source = str(option.get("source", "model_library"))
        details = option.get("details", {}) if isinstance(option.get("details", {}), dict) else {}
        api_key_env = str(option.get("api_key_env", "") or details.get("api_key_env", "")).strip()
        api_key_configured = bool(option.get("api_key_configured"))
        api_key_configured, api_key_state = _api_key_display_state(api_key_env, api_key_configured, draft_meta)
        if api_key_state == "pending":
            api_key_status = t["api_key_pending"]
        elif api_key_state == "clear_pending":
            api_key_status = t["api_key_clear_pending"]
        else:
            api_key_status = t["api_key_configured"] if api_key_configured else t["api_key_missing"]
        tool_mode = str(details.get("tool_calling_mode", "auto"))
        tool_mode_options = _render_model_library_options(
            "tool_calling_mode",
            ("auto", "disabled", "required"),
            tool_mode,
            lang,
        )
        transport = str(details.get("transport", "chat_completions"))
        transport_options = _render_model_library_options(
            "transport",
            ("chat_completions", "responses"),
            transport,
            lang,
        )
        contract = str(details.get("contract", "tool_chat"))
        contract_options = _render_model_library_options(
            "contract",
            ("basic_chat", "tool_chat", "reasoning_chat", "responses_agent"),
            contract,
            lang,
        )
        strict_checked = " checked" if bool(details.get("strict_compatibility", True)) else ""
        streaming_checked = " checked" if bool(details.get("streaming", True)) else ""
        discovery_checked = " checked" if bool(details.get("discovery_enabled", True)) else ""
        detail_summary = _model_library_detail_summary(transport, contract, details, lang)
        provider_summary = _provider_summary(provider, lang)
        source_label = "通用模型" if lang == "zh" else "Library"
        if source != "model_library":
            source_label = "来自配置" if lang == "zh" else "Derived"
        cards.append(
            f'<div class="model-library-card" data-model-library-id="{html.escape(model_id)}" '
            f'data-provider="{_json_for_attr(provider)}" '
            f'data-model="{html.escape(model)}" '
            f'data-label="{html.escape(label)}" '
            f'data-details="{_json_for_attr(details)}" '
            f'data-api-key-env="{html.escape(api_key_env)}">'
            f'<div class="model-library-view">'
            f'<div><strong>{html.escape(label)}</strong>'
            f'<span>{html.escape(provider_summary or _display_provider_kind(provider_kind, lang))}</span>'
            f'<span>{html.escape(t["model_api_key"])}: {html.escape(api_key_status)}'
            f'{f" ({html.escape(api_key_env)})" if api_key_env else ""}</span>'
            f'<span>{html.escape(source_label)}</span>'
            f'{f"<span>{html.escape(detail_summary)}</span>" if detail_summary else ""}</div>'
            f'<code>{html.escape(model)}</code>'
            f'<div class="model-library-actions">'
            f'<button type="button" class="card-action subtle" onclick="editLlmModel(this)">{html.escape(t["edit_model"])}</button>'
            f'<button type="button" class="card-action" onclick="deleteLlmModel(\'{html.escape(model_id)}\')">{html.escape(t["delete_model"])}</button>'
            f"</div>"
            f"</div>"
            f'<div class="model-library-edit" hidden>'
            f"{_render_provider_editor_fields(provider, 'data-edit-field', lang)}"
            f'<label><span>{html.escape(t["prompt_model"])}</span>'
            f'<input type="text" data-edit-field="model" value="{html.escape(model)}"></label>'
            f'<label><span>{html.escape(t["model_label"])}</span>'
            f'<input type="text" data-edit-field="label" value="{html.escape(label)}"></label>'
            f'<label><span>{html.escape(_model_library_field_label("api_key_env", lang))}</span>'
            f'<input type="text" data-edit-field="api_key_env" value="{html.escape(api_key_env)}"></label>'
            f'<label><span>{html.escape(_model_library_field_label("transport", lang))}</span>'
            f'<select data-edit-field="transport">{transport_options}</select></label>'
            f'<label><span>{html.escape(_model_library_field_label("contract", lang))}</span>'
            f'<select data-edit-field="contract">{contract_options}</select></label>'
            f'<label><span>{html.escape(_model_library_field_label("reasoning_state_field", lang))}</span>'
            f'<input type="text" data-edit-field="reasoning_state_field" value="{html.escape(str(details.get("reasoning_state_field", "")))}"></label>'
            f'<label><span>{html.escape(t["model_api_key"])}</span>'
            f'<input type="password" data-edit-api-key autocomplete="off" placeholder="{html.escape(api_key_status)}"></label>'
            f'<label class="model-library-check"><input type="checkbox" data-clear-api-key> <span>{html.escape(t["clear_api_key"])}</span></label>'
            f'<span class="field-hint">{html.escape(t["api_key_hint"])}</span>'
            f'<label><span>{html.escape(_model_library_field_label("temperature", lang))}</span>'
            f'<input type="number" step="any" min="0" max="2" data-edit-field="temperature" value="{html.escape(str(details.get("temperature", "")))}"></label>'
            f'<label><span>{html.escape(_model_library_field_label("max_output_tokens", lang))}</span>'
            f'<input type="number" step="1" min="1" data-edit-field="max_output_tokens" value="{html.escape(str(details.get("max_output_tokens", "")))}"></label>'
            f'<label><span>{html.escape(_model_library_field_label("timeout", lang))}</span>'
            f'<input type="number" step="1" min="1" data-edit-field="timeout" value="{html.escape(str(details.get("timeout", "")))}"></label>'
            f'<label><span>{html.escape(_model_library_field_label("connect_timeout", lang))}</span>'
            f'<input type="number" step="1" min="1" data-edit-field="connect_timeout" value="{html.escape(str(details.get("connect_timeout", "")))}"></label>'
            f'<label><span>{html.escape(_model_library_field_label("tool_calling_mode", lang))}</span>'
            f'<select data-edit-field="tool_calling_mode">{tool_mode_options}</select></label>'
            f'<label class="model-library-check"><input type="checkbox" data-edit-field="strict_compatibility"{strict_checked}> <span>{html.escape(_model_library_field_label("strict_compatibility", lang))}</span></label>'
            f'<label class="model-library-check"><input type="checkbox" data-edit-field="streaming"{streaming_checked}> <span>{html.escape(_model_library_field_label("streaming", lang))}</span></label>'
            f'<label class="model-library-check"><input type="checkbox" data-edit-field="discovery_enabled"{discovery_checked}> <span>{html.escape(_model_library_field_label("discovery_enabled", lang))}</span></label>'
            f'<div class="model-library-actions">'
            f'<button type="button" class="card-action subtle" onclick="saveLlmModelEdit(this)">{html.escape(t["save_model"])}</button>'
            f'<button type="button" class="card-action" onclick="cancelLlmModelEdit(this)">{html.escape(t["cancel"])}</button>'
            f"</div>"
            f"</div>"
            f"</div>"
        )
    body = "".join(cards) or f'<div class="field-hint">{html.escape(t["none"])}</div>'
    add_card = (
        f'<div id="add-llm-model-card" class="model-library-card is-editing model-library-add-card" hidden>'
        f'<div class="model-library-edit">'
        f'<label><span>{html.escape(t["preset_template"])}</span>'
        f'<select data-add-model-preset onchange="applyLlmModelPreset(this.value)">{preset_options_html}</select></label>'
        f'<label><span>{html.escape(t["model_id"])}</span><input type="text" data-add-model-field="model_id"></label>'
        f"{_render_provider_editor_fields({'kind': 'openai', 'compat_mode': 'openai', 'requires_api_key': True}, 'data-add-model-field', lang)}"
        f'<label><span>{html.escape(t["prompt_model"])}</span><input type="text" data-add-model-field="model"></label>'
        f'<label><span>{html.escape(t["model_label"])}</span><input type="text" data-add-model-field="label"></label>'
        f'<label><span>{html.escape(_model_library_field_label("api_key_env", lang))}</span><input type="text" data-add-model-field="api_key_env"></label>'
        f'<label><span>{html.escape(_model_library_field_label("transport", lang))}</span><select data-add-model-field="transport">{_render_model_library_options("transport", ("chat_completions", "responses"), "chat_completions", lang)}</select></label>'
        f'<label><span>{html.escape(_model_library_field_label("contract", lang))}</span><select data-add-model-field="contract">{_render_model_library_options("contract", ("basic_chat", "tool_chat", "reasoning_chat", "responses_agent"), "tool_chat", lang)}</select></label>'
        f'<label><span>{html.escape(_model_library_field_label("reasoning_state_field", lang))}</span><input type="text" data-add-model-field="reasoning_state_field"></label>'
        f'<label><span>{html.escape(t["model_api_key"])}</span><input type="password" data-add-model-field="api_key" autocomplete="off"></label>'
        f'<label class="model-library-check"><input type="checkbox" data-add-model-field="strict_compatibility" checked> <span>{html.escape(_model_library_field_label("strict_compatibility", lang))}</span></label>'
        f'<span class="field-hint">{html.escape(t["preset_template_hint"])}</span>'
        f'<span class="field-hint">{html.escape(t["api_key_hint"])}</span>'
        f'<div class="model-library-actions">'
        f'<button type="button" class="card-action subtle" onclick="saveInlineLlmModel()">{html.escape(t["save_model"])}</button>'
        f'<button type="button" class="card-action" onclick="cancelInlineLlmModel()">{html.escape(t["cancel"])}</button>'
        f"</div></div></div>"
    )
    return (
        f'<section class="panel-section config-page is-active" id="section-llm-model-library" data-config-page="llm-model-library">'
        f'<div class="model-library-head">'
        f'<div><span class="section-title">{html.escape(t["model_library"])}</span>'
        f'<span class="section-hint">{html.escape(t["model_library_hint"])}</span></div>'
        f'<div class="model-library-actions">'
        f'<button type="button" class="card-action subtle" onclick="addLlmModel()">{html.escape(t["add_model"])}</button>'
        f'<button type="button" class="card-action" onclick="addCustomLlmModel()">{html.escape(t["custom_model"])}</button>'
        f"</div>"
        f"</div>"
        f'<div class="model-library-grid">{add_card}{body}</div>'
        f"</section>"
    )


def _inspect_panel_state(public_config: dict, lang: str) -> dict[str, object]:
    snapshot = inspect_public_config(public_config)
    diagnosis = copy.deepcopy(snapshot["diagnosis"])
    summary = copy.deepcopy(snapshot["summary"])
    missing_profiles = _missing_required_llm_profiles(public_config)
    if missing_profiles:
        display_names = "、".join(_display_profile_id(profile_id, lang) for profile_id in missing_profiles)
        blocking_message = f'{I18N[lang]["profile_model_missing"]} {display_names}'
        if blocking_message not in diagnosis["blocking_issues"]:
            diagnosis["blocking_issues"].append(blocking_message)
        summary["blocking_count"] = len(diagnosis["blocking_issues"])
    return {
        "effective": snapshot["effective"],
        "diagnosis": diagnosis,
        "summary": summary,
    }


def _with_config_language(public_config: dict, lang: str) -> dict:
    display_config = copy.deepcopy(public_config)
    display_config.setdefault("ui", {})
    if isinstance(display_config["ui"], dict):
        display_config["ui"]["language"] = lang
    return display_config


def _generic_public_config(display_config: dict) -> dict:
    generic_config = copy.deepcopy(display_config)
    if isinstance(generic_config.get("llm"), dict):
        generic_config["llm"].pop("model_library", None)
    return generic_config


def _render_sections_nav(display_config: dict, lang: str) -> str:
    t = I18N[lang]
    generic_config = _generic_public_config(display_config)
    return (
        f'<a href="#section-llm-model-library" class="is-active" data-config-nav="llm-model-library" '
        f'onclick="selectConfigPage(\'llm-model-library\', event)">{html.escape(t["model_library"])}</a>'
    ) + "".join(
        f'<a href="#section-{html.escape(name)}" data-config-nav="{html.escape(name)}" '
        f'onclick="selectConfigPage(\'{html.escape(name)}\', event)">{html.escape(localize_section_label(name, name, lang))}</a>'
        for name in generic_config.keys()
    )


def _render_config_content(display_config: dict, lang: str, draft_meta: dict[str, object]) -> str:
    generic_config = _generic_public_config(display_config)
    return _render_model_library_section(display_config, lang, draft_meta) + "".join(
        _render_object(name, value, name, lang, display_config) for name, value in generic_config.items()
    )


def _render_config_form_contents(
    public_config: dict,
    message: str,
    lang: str,
    draft_meta: dict[str, object],
    base_hash: str,
) -> str:
    display_config = _with_config_language(public_config, lang)
    resolved_base_hash = str(base_hash or public_config_hash(public_config)).strip()
    content = _render_config_content(display_config, lang, draft_meta)
    t = I18N[lang]
    return (
        f'<div class="toolbar">'
        f'<button type="button" onclick="saveConfig()">{html.escape(t["save"])}</button>'
        f'<button type="button" class="ghost" onclick="window.location.reload()">{html.escape(t["reload"])}</button>'
        f'<label>'
        f'<span style="font-size:13px;color:var(--muted);margin-right:6px;">{html.escape(t["language"])}</span>'
        f'<select id="lang-switch" onchange="switchLang(this.value)">'
        f'<option value="zh" {"selected" if lang == "zh" else ""}>{html.escape(t["lang_zh"])}</option>'
        f'<option value="en" {"selected" if lang == "en" else ""}>{html.escape(t["lang_en"])}</option>'
        f"</select>"
        f"</label>"
        f'<span class="message">{html.escape(message)}</span>'
        f"</div>"
        f'<input type="hidden" name="payload" id="payload">'
        f'<input type="hidden" name="base_hash" id="base-hash" value="{html.escape(resolved_base_hash)}">'
        f"{content}"
    )


def _render_diagnostics_aside(public_config: dict, lang: str) -> str:
    t = I18N[lang]
    snapshot = _inspect_panel_state(public_config, lang)
    diagnosis = snapshot["diagnosis"]
    raw_toml = dumps_public_config(public_config, HEADER_LINES)
    warnings_html = "".join(f"<li>{html.escape(item)}</li>" for item in diagnosis["warnings"]) or f"<li>{html.escape(t['none'])}</li>"
    blocking_html = "".join(f"<li>{html.escape(item)}</li>" for item in diagnosis["blocking_issues"]) or f"<li>{html.escape(t['none'])}</li>"
    actions_html = "".join(f"<li>{html.escape(item)}</li>" for item in diagnosis["suggested_actions"]) or f"<li>{html.escape(t['none'])}</li>"
    return (
        f'<div class="diag-block">'
        f'<h2>{html.escape(t["diagnostics"])}</h2>'
        f'<div class="diag-kv">'
        f'<div class="kv-item">{html.escape(t["provider"])}: <strong>{html.escape(diagnosis["identity"]["provider"])}</strong></div>'
        f'<div class="kv-item">{html.escape(t["model"])}: <strong>{html.escape(diagnosis["identity"]["model_name"])}</strong></div>'
        f'<div class="kv-item">{html.escape(t["profile"])}: <strong>{html.escape(diagnosis["identity"]["runtime_profile"])}</strong></div>'
        f'<div class="kv-item">{html.escape(t["api_key_source"])}: <strong>{html.escape(diagnosis["sources"]["api_key"])}</strong></div>'
        f"</div>"
        f"</div>"
        f'<div class="diag-block">'
        f'<h2 class="danger">{html.escape(t["blocking"])}</h2>'
        f"<ul>{blocking_html}</ul>"
        f"</div>"
        f'<div class="diag-block">'
        f'<h2 class="warn">{html.escape(t["warnings"])}</h2>'
        f"<ul>{warnings_html}</ul>"
        f"</div>"
        f'<div class="diag-block">'
        f'<h2>{html.escape(t["actions"])}</h2>'
        f"<ul>{actions_html}</ul>"
        f"</div>"
        f'<div class="diag-block">'
        f'<h2>{html.escape(t["raw_toml"])}</h2>'
        f"<details>"
        f'<summary>{html.escape(t["raw_toml_summary"])}</summary>'
        f"<pre>{html.escape(raw_toml)}</pre>"
        f"</details>"
        f"</div>"
    )


def render_panel_html(
    public_config: dict,
    message: str = "",
    lang: str | None = None,
    draft_meta: dict | None = None,
    base_hash: str | None = None,
) -> str:
    lang = resolve_lang(lang or get_config_language(public_config))
    draft_meta = _normalize_draft_meta(draft_meta)
    resolved_base_hash = str(base_hash or public_config_hash(public_config)).strip()
    display_config = _with_config_language(public_config, lang)
    display_json = json.dumps(display_config, ensure_ascii=False)
    draft_meta_json = json.dumps(draft_meta, ensure_ascii=False)
    base_hash_json = json.dumps(resolved_base_hash, ensure_ascii=False)
    preset_json = json.dumps({item["preset_id"]: item for item in list_llm_model_preset_options()}, ensure_ascii=False)
    t = I18N[lang]
    sections_nav = _render_sections_nav(display_config, lang)
    form_contents = _render_config_form_contents(public_config, message, lang, draft_meta, resolved_base_hash)
    aside_contents = _render_diagnostics_aside(public_config, lang)

    return f"""<!doctype html>
<html lang="{html.escape(t['html_lang'])}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(t['title'])}</title>
  <style>
    :root {{
      --bg: #f5f7fb;
      --panel: #ffffff;
      --panel-soft: #f8fbff;
      --muted: #5f6b7a;
      --text: #1f2937;
      --line: #d8e0ea;
      --accent: #2563eb;
      --accent-soft: #eff6ff;
      --warn: #b45309;
      --danger: #b91c1c;
      --success: #15803d;
      --shadow: 0 8px 24px rgba(15, 23, 42, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: "Segoe UI", system-ui, sans-serif; color: var(--text); background: var(--bg); }}
    .layout {{ display: grid; grid-template-columns: 240px minmax(0, 1fr) 320px; min-height: 100vh; gap: 16px; padding: 16px; }}
    .sidebar, .main, .aside {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; box-shadow: var(--shadow); }}
    .sidebar {{ padding: 16px; position: sticky; top: 16px; height: calc(100vh - 32px); overflow: auto; }}
    .sidebar h1 {{ font-size: 18px; margin: 0 0 12px; }}
    .panel-hero {{ margin-bottom: 14px; padding: 12px 14px; border: 1px solid #dbe7fb; border-radius: 8px; background: #eff6ff; }}
    .panel-hero strong {{ display: block; font-size: 16px; margin-bottom: 4px; }}
    .panel-hero span {{ color: var(--muted); font-size: 13px; }}
    .sidebar nav {{ display: flex; flex-direction: column; gap: 6px; }}
    .sidebar a {{ color: var(--muted); text-decoration: none; padding: 8px 10px; border-radius: 6px; }}
    .sidebar a:hover {{ background: #eef4ff; color: var(--accent); }}
    .sidebar a.is-active {{ background: var(--accent-soft); color: var(--accent); font-weight: 700; }}
    .main {{ padding: 16px; }}
    .toolbar {{ display: flex; gap: 10px; align-items: center; margin-bottom: 16px; flex-wrap: wrap; }}
    .toolbar button {{ background: var(--accent); color: #fff; border: 0; border-radius: 6px; padding: 10px 14px; cursor: pointer; }}
    .toolbar .ghost {{ background: #eef2f7; color: var(--text); }}
    .toolbar .subtle {{ background: #f8fbff; color: var(--accent); border: 1px solid var(--line); }}
    .toolbar select {{ padding: 9px 10px; border: 1px solid #c9d4e2; border-radius: 6px; background: #fff; }}
    .llm-switcher {{ display: inline-flex; align-items: center; gap: 8px; padding-left: 8px; border-left: 1px solid var(--line); }}
    .llm-switcher select {{ min-width: 260px; }}
    .message {{ margin-left: auto; color: var(--accent); font-size: 14px; }}
    .toast-stack {{ position: fixed; top: 18px; right: 18px; display: grid; gap: 10px; z-index: 1000; }}
    .toast {{ min-width: 240px; max-width: 360px; padding: 12px 14px; border-radius: 8px; box-shadow: var(--shadow); border: 1px solid var(--line); background: #fff; }}
    .toast.success {{ border-color: #bbf7d0; background: #f0fdf4; }}
    .toast.error {{ border-color: #fecaca; background: #fef2f2; }}
    .toast strong {{ display: block; margin-bottom: 4px; font-size: 14px; }}
    .toast span {{ display: block; color: var(--muted); font-size: 13px; line-height: 1.4; }}
    .config-page {{ display: none; }}
    .config-page.is-active {{ display: block; }}
    .panel-section {{ margin-bottom: 12px; border: 1px solid var(--line); border-radius: 8px; background: var(--panel); overflow: hidden; }}
    .section-header {{ width: 100%; display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 14px; border: 0; background: #fff; color: var(--text); text-align: left; }}
    .section-title-wrap {{ display: flex; align-items: center; gap: 10px; min-width: 0; }}
    .section-chevron {{ display: inline-flex; align-items: center; justify-content: center; width: 24px; height: 24px; border-radius: 6px; background: var(--accent-soft); color: var(--accent); font-size: 22px; line-height: 1; transition: transform 0.18s ease; }}
    .section-title {{ display: block; font-size: 18px; font-weight: 700; }}
    .section-hint {{ display: block; margin-top: 3px; color: var(--muted); font-size: 13px; }}
    .section-count {{ flex: 0 0 auto; min-width: 32px; padding: 4px 9px; border-radius: 999px; background: #eef2f7; color: var(--muted); font-size: 12px; text-align: center; }}
    .section-content {{ padding: 0 14px 14px; border-top: 1px solid var(--line); }}
    .panel-section:not(.is-collapsed) .section-chevron {{ transform: rotate(90deg); }}
    .section-grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; align-items: stretch; }}
    .llm-group-band {{ display: grid; gap: 12px; padding-top: 8px; }}
    .llm-group-band + .llm-group-band {{ margin-top: 4px; padding-top: 16px; border-top: 1px solid var(--line); }}
    .llm-group-band-header {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; }}
    .llm-group-band-title {{ font-size: 13px; font-weight: 700; color: var(--muted); }}
    .llm-group-band-content {{ display: grid; gap: 12px; }}
    .field, .field-group, .object-card {{ display: flex; flex-direction: column; gap: 10px; padding: 12px; border: 1px solid var(--line); border-radius: 6px; background: #fbfdff; }}
    .field {{ min-height: 144px; justify-content: space-between; }}
    .field.list, .field.field-list, .list-of-objects {{ grid-column: 1 / -1; }}
    .field-head {{ display: flex; align-items: center; justify-content: space-between; gap: 8px; }}
    .field-label {{ font-size: 13px; color: var(--text); font-weight: 600; }}
    .field-badge {{ display: inline-flex; align-items: center; padding: 3px 8px; border-radius: 999px; background: var(--accent-soft); color: var(--accent); font-size: 12px; }}
    .field-hint {{ min-height: 34px; font-size: 12px; line-height: 1.4; color: var(--muted); }}
    .field-hint.muted {{ visibility: hidden; }}
    .field-view {{ display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-top: auto; }}
    .field-value {{ min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text); font-size: 13px; }}
    .field-editor {{ display: grid; gap: 10px; margin-top: auto; }}
    .field-editor[hidden] {{ display: none; }}
    .collapsible-card.is-editing > .card-content .field-view {{ display: none; }}
    .collapsible-card.is-editing > .card-content .field-editor[hidden] {{ display: grid; }}
    .field-control {{ margin-top: auto; }}
    .field input, .field textarea, .field select {{ width: 100%; padding: 10px 12px; border: 1px solid #c9d4e2; border-radius: 6px; font: inherit; background: #fff; }}
    .field textarea {{ min-height: 120px; resize: none; }}
    .field-secret input {{ letter-spacing: 0.08em; }}
    .field-path input, .field-url input {{ font-family: Consolas, "Courier New", monospace; font-size: 12px; }}
    .field-group {{ grid-column: 1 / -1; background: #f8fafc; }}
    .group-title {{ margin: 0 0 10px; font-size: 13px; color: var(--muted); font-weight: 700; }}
    .field-group > .section-grid {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
    .collapsible-card {{ grid-column: 1 / -1; border: 1px solid var(--line); border-radius: 6px; background: #fbfdff; overflow: hidden; }}
    .card-header-shell {{ display: flex; align-items: center; gap: 8px; background: #fbfdff; }}
    .card-header {{ flex: 1; min-width: 0; display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 11px 12px; border: 0; background: transparent; color: var(--text); text-align: left; cursor: pointer; }}
    .card-header:hover {{ background: #f3f7fc; }}
    .card-header:focus-visible {{ outline: 2px solid var(--accent); outline-offset: -2px; }}
    .card-title {{ font-size: 13px; color: var(--text); font-weight: 700; }}
    .card-actions {{ display: inline-flex; align-items: center; gap: 8px; padding-right: 12px; }}
    .card-edit-controls {{ display: inline-flex; align-items: center; gap: 8px; padding-right: 12px; }}
    .collapsible-card.is-editing > .card-header-shell .card-edit-button {{ display: none; }}
    .collapsible-card.is-editing > .card-header-shell .card-save-button,
    .collapsible-card.is-editing > .card-header-shell .card-cancel-button {{ display: inline-flex; }}
    .card-profile-select {{ min-width: 230px; max-width: 36vw; height: 34px; border: 1px solid #c9d4e2; border-radius: 6px; background: #fff; color: var(--text); padding: 0 8px; font: inherit; font-size: 12px; }}
    .card-profile-select.is-required {{ border-color: #dc2626; box-shadow: inset 0 0 0 1px rgba(220, 38, 38, 0.08); }}
    .required-indicator {{ color: var(--danger); font-size: 12px; font-weight: 700; white-space: nowrap; }}
    .card-action {{ border: 1px solid #c9d4e2; background: #fff; color: var(--accent); border-radius: 6px; padding: 7px 10px; font: inherit; font-size: 12px; cursor: pointer; }}
    .card-action.subtle {{ background: var(--accent); border-color: var(--accent); color: #fff; }}
    .card-action:hover {{ filter: brightness(0.98); }}
    .card-content {{ padding: 12px; border-top: 1px solid var(--line); background: #f8fafc; }}
    .collapsible-card:not(.is-collapsed) .section-chevron {{ transform: rotate(90deg); }}
    .model-library-head {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 14px; border-bottom: 1px solid var(--line); }}
    .model-library-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; padding: 14px; }}
    .model-library-card {{ border: 1px solid var(--line); border-radius: 6px; background: #fbfdff; padding: 10px 12px; }}
    .inline-add-card {{ margin: -6px 0 16px; border: 1px solid var(--line); border-radius: 6px; background: #fbfdff; padding: 12px; }}
    .inline-add-card[hidden], .model-library-add-card[hidden] {{ display: none; }}
    .model-library-view {{ display: grid; grid-template-columns: minmax(0, 1fr) minmax(160px, auto) auto; align-items: center; gap: 12px; }}
    .model-library-card strong {{ display: block; font-size: 13px; }}
    .model-library-card span {{ display: block; color: var(--muted); font-size: 12px; margin-top: 3px; }}
    .model-library-card code {{ color: var(--text); font-family: Consolas, "Courier New", monospace; font-size: 12px; white-space: nowrap; }}
    .model-library-card.is-editing .model-library-view {{ display: none; }}
    .model-library-edit {{ display: grid; grid-template-columns: repeat(4, minmax(140px, 1fr)); align-items: end; gap: 10px; }}
    .model-library-edit[hidden] {{ display: none; }}
    .model-library-edit label {{ display: grid; gap: 5px; min-width: 0; }}
    .model-library-edit input, .model-library-edit select {{ width: 100%; min-width: 0; height: 34px; border: 1px solid #c9d4e2; border-radius: 6px; background: #fff; color: var(--text); padding: 0 8px; font: inherit; font-size: 13px; }}
    .model-library-edit .model-library-check {{ display: inline-flex; align-items: center; gap: 8px; height: 34px; }}
    .model-library-edit .model-library-check input {{ width: 18px; height: 18px; }}
    .model-library-actions {{ display: inline-flex; align-items: center; justify-content: flex-end; gap: 8px; }}
    .model-library-delete {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; padding-top: 10px; border-top: 1px solid var(--line); color: var(--danger); font-size: 13px; }}
    .list-of-objects {{ display: grid; gap: 10px; }}
    .toggle-row {{ display: inline-flex; align-items: center; gap: 0; cursor: pointer; }}
    .toggle-row input {{ position: absolute; opacity: 0; pointer-events: none; }}
    .toggle-pill {{ width: 48px; height: 28px; border-radius: 999px; background: #cbd5e1; position: relative; transition: background 0.2s ease; }}
    .toggle-pill::after {{ content: ""; position: absolute; top: 4px; left: 4px; width: 20px; height: 20px; border-radius: 999px; background: #fff; box-shadow: 0 1px 2px rgba(0,0,0,0.16); transition: transform 0.2s ease; }}
    .toggle-row input:checked + .toggle-pill {{ background: var(--accent); }}
    .toggle-row input:checked + .toggle-pill::after {{ transform: translateX(20px); }}
    .aside {{ padding: 16px; position: sticky; top: 16px; height: calc(100vh - 32px); overflow: auto; }}
    .diag-block {{ margin-bottom: 16px; padding: 12px; border: 1px solid var(--line); border-radius: 6px; background: #fbfdff; }}
    .diag-block h2 {{ margin: 0 0 10px; font-size: 16px; }}
    .diag-block ul {{ margin: 0; padding-left: 18px; }}
    .diag-kv {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; font-size: 14px; }}
    .diag-kv .kv-item {{ padding: 10px; border: 1px solid var(--line); border-radius: 6px; background: #fff; }}
    .warn {{ color: var(--warn); }}
    .danger {{ color: var(--danger); }}
    details pre {{ white-space: pre-wrap; word-break: break-word; font-size: 12px; background: #0f172a; color: #e2e8f0; padding: 12px; border-radius: 6px; }}
    @media (max-width: 1400px) {{ .section-grid, .field-group > .section-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} }}
    @media (max-width: 1200px) {{ .layout {{ grid-template-columns: 1fr; }} .sidebar, .aside {{ position: static; height: auto; }} .section-grid, .field-group > .section-grid, .diag-kv, .model-library-grid, .model-library-view, .model-library-edit {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body data-build="{PANEL_BUILD_ID}">
  <!-- {PANEL_BUILD_ID} -->
  <div id="toast-stack" class="toast-stack"></div>
  <div class="layout">
    <aside class="sidebar">
      <div class="panel-hero">
        <strong>{html.escape(t['title'])}</strong>
        <span>{html.escape(t['panel_subtitle'])}</span>
      </div>
      <h1>{html.escape(t['panel_title'])}</h1>
      <nav>{sections_nav}</nav>
    </aside>
    <main class="main">
      <form id="config-form" method="post" action="/save">{form_contents}</form>
    </main>
    <aside class="aside">{aside_contents}</aside>
  </div>
  <script>
    const LLM_MODEL_PRESETS = {preset_json};
    const INITIAL_PUBLIC_CONFIG = {display_json};
    const INITIAL_DRAFT_META = {draft_meta_json};
    const INITIAL_BASE_HASH = {base_hash_json};
    let draftPublicConfig = JSON.parse(JSON.stringify(INITIAL_PUBLIC_CONFIG));
    let draftMeta = JSON.parse(JSON.stringify(INITIAL_DRAFT_META));
    let draftBaseHash = INITIAL_BASE_HASH;

    function deepClone(value) {{
      return JSON.parse(JSON.stringify(value));
    }}

    function collectBaseHash() {{
      const field = document.getElementById("base-hash");
      if (field && field.value) {{
        draftBaseHash = field.value;
      }}
      return draftBaseHash || "";
    }}

    function assignPath(target, path, value) {{
      const parts = path.split(".");
      let current = target;
      for (let i = 0; i < parts.length; i++) {{
        const part = parts[i];
        const nextPart = parts[i + 1];
        const isLast = i === parts.length - 1;
        const isIndex = /^\\d+$/.test(part);
        if (isLast) {{
          if (isIndex) {{
            current[Number(part)] = value;
          }} else {{
            current[part] = value;
          }}
          return;
        }}
        const nextIsIndex = /^\\d+$/.test(nextPart || "");
        if (isIndex) {{
          const idx = Number(part);
          if (!Array.isArray(current)) {{
            throw new Error("Invalid array path: " + path);
          }}
          if (current[idx] === undefined) {{
            current[idx] = nextIsIndex ? [] : {{}};
          }}
          current = current[idx];
        }} else {{
          if (current[part] === undefined) {{
            current[part] = nextIsIndex ? [] : {{}};
          }}
          current = current[part];
        }}
      }}
    }}

    function getControlValue(el) {{
      if (el.type === "checkbox") {{
        return el.checked;
      }}
      if (el.dataset.kind === "string-list") {{
        return el.value.split(/\\r?\\n/).map((item) => item.trim()).filter(Boolean);
      }}
      if (el.type === "number") {{
        return el.step === "any" ? parseFloat(el.value || "0") : parseInt(el.value || "0", 10);
      }}
      return el.value;
    }}

    function collectPayload() {{
      return deepClone(draftPublicConfig);
    }}

    function collectDraftMeta() {{
      return deepClone(draftMeta);
    }}

    function applyCardValuesToDraft(card) {{
      if (!card) {{
        return;
      }}
      card.querySelectorAll("[data-path]").forEach((el) => {{
        assignPath(draftPublicConfig, el.dataset.path, getControlValue(el));
      }});
    }}

    function setControlValue(control, value) {{
      if (!control) {{
        return;
      }}
      if (control.type === "checkbox") {{
        control.checked = Boolean(value);
      }} else if (control.dataset.kind === "string-list") {{
        control.value = Array.isArray(value) ? value.join("\\n") : (value || "");
      }} else {{
        control.value = value === null || value === undefined ? "" : String(value);
      }}
    }}

    function restoreOriginalFieldValue(field) {{
      field.querySelectorAll("[data-path]").forEach((control) => {{
        if (!control.dataset.originalValue) {{
          return;
        }}
        try {{
          setControlValue(control, JSON.parse(control.dataset.originalValue));
        }} catch (_error) {{
          setControlValue(control, control.dataset.originalValue);
        }}
      }});
    }}

    function setCardExpanded(card, expanded) {{
      if (!card) {{
        return;
      }}
      const content = card.querySelector(":scope > .card-content");
      const header = card.querySelector(":scope > .card-header-shell .card-header");
      if (content) {{
        content.hidden = !expanded;
      }}
      if (header) {{
        header.setAttribute("aria-expanded", expanded ? "true" : "false");
      }}
      card.classList.toggle("is-collapsed", !expanded);
    }}

    function setCardEditing(card, editing) {{
      if (!card) {{
        return;
      }}
      setCardExpanded(card, true);
      card.classList.toggle("is-editing", editing);
      const saveButton = card.querySelector(":scope > .card-header-shell .card-save-button");
      const cancelButton = card.querySelector(":scope > .card-header-shell .card-cancel-button");
      if (saveButton) {{
        saveButton.hidden = !editing;
      }}
      if (cancelButton) {{
        cancelButton.hidden = !editing;
      }}
    }}

    function rememberCardState(card) {{
      return {{
        expanded: card ? !card.classList.contains("is-collapsed") : false,
        editing: card ? card.classList.contains("is-editing") : false
      }};
    }}

    function restoreCardState(card, state) {{
      if (!card) {{
        return;
      }}
      const nextState = state || {{ expanded: false, editing: false }};
      if (nextState.editing) {{
        setCardEditing(card, true);
        return;
      }}
      setCardEditing(card, false);
      setCardExpanded(card, !!nextState.expanded);
    }}

    function replaceCardHtml(card, htmlText) {{
      const template = document.createElement("template");
      template.innerHTML = (htmlText || "").trim();
      const nextCard = template.content.firstElementChild;
      if (!nextCard) {{
        throw new Error("Card HTML is empty");
      }}
      card.replaceWith(nextCard);
      return nextCard;
    }}

    function replaceConfigFormHtml(htmlText) {{
      const form = document.getElementById("config-form");
      if (!form) {{
        throw new Error("Config form not found");
      }}
      form.innerHTML = (htmlText || "").trim();
      return form;
    }}

    function replaceDiagnosticsHtml(htmlText) {{
      const aside = document.querySelector(".aside");
      if (!aside) {{
        throw new Error("Diagnostics aside not found");
      }}
      aside.innerHTML = (htmlText || "").trim();
      return aside;
    }}

    function applyPreviewState(result, pageId = "") {{
      if (result && typeof result.main_html === "string") {{
        replaceConfigFormHtml(result.main_html);
      }}
      if (result && typeof result.aside_html === "string") {{
        replaceDiagnosticsHtml(result.aside_html);
      }}
      if (result && result.public_config) {{
        draftPublicConfig = deepClone(result.public_config);
      }}
      if (result && result.draft_meta) {{
        draftMeta = deepClone(result.draft_meta);
      }}
      if (result && Object.prototype.hasOwnProperty.call(result, "base_hash")) {{
        draftBaseHash = String(result.base_hash || "");
      }}
      const baseHashField = document.getElementById("base-hash");
      if (baseHashField) {{
        baseHashField.value = draftBaseHash || "";
      }}
      if (result && result.lang) {{
        syncLanguageControls(result.lang, "toolbar");
      }}
      selectConfigPage(pageId || activeConfigPageId());
      return result;
    }}

    async function fetchPreviewState(path, fields) {{
      const response = await fetch(path, {{
        method: "POST",
        headers: {{ "Content-Type": "application/x-www-form-urlencoded" }},
        body: new URLSearchParams({{
          ...fields,
          base_hash: collectBaseHash(),
          response_mode: "fragments"
        }})
      }});
      const result = await response.json();
      if (!response.ok || !result.ok) {{
        throw new Error((result && result.message) || "Preview request failed");
      }}
      return result;
    }}

    async function postPreviewState(path, fields, pageId = "") {{
      const result = await fetchPreviewState(path, fields);
      applyPreviewState(result, pageId);
      return result;
    }}

    function editConfigCard(button) {{
      setCardEditing(button.closest(".collapsible-card"), true);
    }}

    function cancelConfigCard(button) {{
      const card = button.closest(".collapsible-card");
      if (!card) {{
        return;
      }}
      restoreOriginalFieldValue(card);
      setCardEditing(card, false);
    }}

    async function saveConfigCard(button) {{
      const card = button.closest(".collapsible-card");
      if (!card) {{
        setToolbarMessage("Config card not found", true);
        return;
      }}
      const lang = document.getElementById("lang-switch").value;
      const cardPath = card.dataset.cardPath || "";
      applyCardValuesToDraft(card);
      if (!draftPublicConfig.ui) {{
        draftPublicConfig.ui = {{}};
      }}
      draftPublicConfig.ui.language = lang;
      const response = await fetch("/preview-config-card", {{
        method: "POST",
        headers: {{ "Content-Type": "application/x-www-form-urlencoded" }},
        body: new URLSearchParams({{
          payload: JSON.stringify(collectPayload()),
          base_hash: collectBaseHash(),
          draft_meta: JSON.stringify(collectDraftMeta()),
          card_path: cardPath,
          lang
        }})
      }});
      const result = await response.json();
      if (!response.ok || !result.ok) {{
        setToolbarMessage("{html.escape(t['save_failed'])}: " + result.message, true);
        showToast("error", "{html.escape(t['save_failed_title'])}", result.message);
        return;
      }}
      const newCard = replaceCardHtml(card, result.html || "");
      restoreCardState(newCard, {{ expanded: true, editing: false }});
      setToolbarMessage(result.message || "{html.escape(t['confirm_success'])}", false);
      showToast("success", "{html.escape(t['confirm_success_title'])}", result.message || "{html.escape(t['confirm_success'])}");
    }}

    async function postConfig(payload, lang) {{
      const form = document.getElementById("config-form");
      return fetch(form.action, {{
        method: "POST",
        headers: {{ "Content-Type": "application/x-www-form-urlencoded" }},
        body: new URLSearchParams({{
          payload: JSON.stringify(payload),
          base_hash: collectBaseHash(),
          draft_meta: JSON.stringify(collectDraftMeta()),
          lang
        }})
      }});
    }}

    async function previewDraft(payload, lang, message = "") {{
      postHtmlNavigation("/preview", {{
        payload: JSON.stringify(payload),
        base_hash: collectBaseHash(),
        draft_meta: JSON.stringify(collectDraftMeta()),
        lang,
        message
      }});
    }}

    function setToolbarMessage(text, isError = false) {{
      const el = document.querySelector(".message");
      if (!el) {{
        return;
      }}
      el.textContent = text || "";
      el.style.color = isError ? "var(--danger)" : "var(--accent)";
    }}

    function showToast(kind, title, message) {{
      const stack = document.getElementById("toast-stack");
      if (!stack) {{
        return;
      }}
      const toast = document.createElement("div");
      toast.className = "toast " + kind;
      toast.innerHTML = "<strong>" + title + "</strong><span>" + message + "</span>";
      stack.appendChild(toast);
      window.setTimeout(() => {{
        toast.remove();
      }}, 2600);
    }}

    function activeConfigPageId(fallbackPageId = "llm-model-library") {{
      const activePage = document.querySelector("[data-config-page].is-active");
      if (activePage && activePage.dataset.configPage) {{
        return activePage.dataset.configPage;
      }}
      const fromHash = window.location.hash.replace(/^#section-/, "");
      return fromHash || fallbackPageId;
    }}

    function buildConfigRefreshUrl(lang, message = "", pageId = "") {{
      const nextUrl = new URL(window.location.origin + "/");
      if (message) {{
        nextUrl.searchParams.set("message", message);
      }}
      if (lang) {{
        nextUrl.searchParams.set("lang", lang);
      }}
      const resolvedPageId = pageId || activeConfigPageId();
      if (resolvedPageId) {{
        nextUrl.hash = "section-" + resolvedPageId;
      }}
      return nextUrl;
    }}

    function reloadConfigPage(lang, message = "", delay = 0, pageId = "") {{
      const nextUrl = buildConfigRefreshUrl(lang, message, pageId);
      const navigate = () => {{
        window.location.href = nextUrl.toString();
      }};
      if (delay > 0) {{
        window.setTimeout(navigate, delay);
        return;
      }}
      navigate();
    }}

    function postHtmlNavigation(path, fields) {{
      const resolvedFields = Object.assign({{ base_hash: collectBaseHash() }}, fields || {{}});
      const form = document.createElement("form");
      form.method = "POST";
      form.action = path + (window.location.hash || "");
      form.style.display = "none";
      Object.entries(resolvedFields).forEach(([key, value]) => {{
        const input = document.createElement("input");
        input.type = "hidden";
        input.name = key;
        input.value = value == null ? "" : String(value);
        form.appendChild(input);
      }});
      document.body.appendChild(form);
      form.submit();
    }}

    function syncLanguageControls(lang, source) {{
      const toolbar = document.getElementById("lang-switch");
      const bodyField = document.querySelector('[data-path="ui.language"]');
      if (toolbar && source !== "toolbar") {{
        toolbar.value = lang;
      }}
      if (bodyField && source !== "body") {{
        bodyField.value = lang;
      }}
    }}

    const MODEL_LIBRARY_DETAIL_FIELDS = {json.dumps(list(MODEL_LIBRARY_DETAIL_FIELDS), ensure_ascii=False)};

    function fieldByAttr(root, attrName, key) {{
      return root ? root.querySelector('[' + attrName + '="' + key + '"]') : null;
    }}

    function setFieldByAttr(root, attrName, key, value) {{
      const field = fieldByAttr(root, attrName, key);
      if (!field) {{
        return;
      }}
      if (field.type === "checkbox") {{
        field.checked = !!value;
        return;
      }}
      if (field.tagName === "SELECT") {{
        let option = Array.from(field.options).find((item) => item.value === String(value ?? ""));
        if (!option && value) {{
          option = new Option(String(value), String(value));
          field.add(option);
        }}
        field.value = value ?? "";
        return;
      }}
      field.value = value ?? "";
    }}

    function applyProviderFields(root, attrName, provider) {{
      const entry = provider || {{}};
      setFieldByAttr(root, attrName, "provider_kind", entry.kind || "openai");
      setFieldByAttr(root, attrName, "provider_base_url", entry.base_url || "");
      setFieldByAttr(root, attrName, "provider_api_key_env", entry.api_key_env || "");
      setFieldByAttr(root, attrName, "provider_compat_mode", entry.compat_mode || "openai");
      setFieldByAttr(root, attrName, "provider_requires_api_key", entry.requires_api_key !== false);
      setFieldByAttr(root, attrName, "provider_context_window", entry.context_window || "");
      const extraHeaders = entry.extra_headers
        ? (typeof entry.extra_headers === "string" ? entry.extra_headers : JSON.stringify(entry.extra_headers))
        : "";
      setFieldByAttr(root, attrName, "provider_extra_headers", extraHeaders);
    }}

    function collectProviderFields(root, attrName) {{
      const kind = (fieldByAttr(root, attrName, "provider_kind")?.value || "").trim();
      const baseUrl = (fieldByAttr(root, attrName, "provider_base_url")?.value || "").trim();
      const apiKeyEnv = (fieldByAttr(root, attrName, "provider_api_key_env")?.value || "").trim();
      const compatMode = (fieldByAttr(root, attrName, "provider_compat_mode")?.value || "").trim();
      const requiresApiKey = !!fieldByAttr(root, attrName, "provider_requires_api_key")?.checked;
      const contextWindowRaw = (fieldByAttr(root, attrName, "provider_context_window")?.value || "").trim();
      const extraHeadersRaw = (fieldByAttr(root, attrName, "provider_extra_headers")?.value || "").trim();
      const provider = {{}};
      if (kind) {{
        provider.kind = kind;
      }}
      if (baseUrl) {{
        provider.base_url = baseUrl;
      }}
      if (apiKeyEnv) {{
        provider.api_key_env = apiKeyEnv;
      }}
      if (compatMode) {{
        provider.compat_mode = compatMode;
      }}
      provider.requires_api_key = requiresApiKey;
      if (contextWindowRaw) {{
        provider.context_window = parseInt(contextWindowRaw, 10);
      }}
      if (extraHeadersRaw) {{
        try {{
          provider.extra_headers = JSON.parse(extraHeadersRaw);
        }} catch (error) {{
          throw new Error("provider_extra_headers must be valid JSON");
        }}
      }}
      return provider;
    }}

    function applyModelDetails(root, attrName, details) {{
      MODEL_LIBRARY_DETAIL_FIELDS.forEach((key) => {{
        const value = Object.prototype.hasOwnProperty.call(details || {{}}, key) ? details[key] : "";
        setFieldByAttr(root, attrName, key, value);
      }});
    }}

    function collectModelDetails(root, attrName) {{
      const details = {{}};
      root.querySelectorAll("[" + attrName + "]").forEach((field) => {{
        const key = field.getAttribute(attrName);
        if (!key || key.startsWith("provider_") || ["model_id", "model", "label", "api_key", "api_key_env"].includes(key)) {{
          return;
        }}
        if (field.type === "checkbox") {{
          details[key] = field.checked;
          return;
        }}
        const raw = (field.value || "").trim();
        if (!raw) {{
          return;
        }}
        if (["temperature"].includes(key)) {{
          details[key] = parseFloat(raw);
        }} else if (["max_output_tokens", "timeout", "connect_timeout"].includes(key)) {{
          details[key] = parseInt(raw, 10);
        }} else {{
          details[key] = raw;
        }}
      }});
      return details;
    }}

    function resetProfileModelDetails(profile) {{
      MODEL_LIBRARY_DETAIL_FIELDS.forEach((key) => {{
        delete profile[key];
      }});
    }}

    function applySelectedModelToProfile(profile, selected) {{
      resetProfileModelDetails(profile);
      delete profile.provider_id;
      profile.provider = selected.provider || {{}};
      profile.model = selected.model || "";
      if (selected.apiKeyEnv) {{
        profile.api_key_env = selected.apiKeyEnv;
      }} else {{
        delete profile.api_key_env;
      }}
      Object.entries(selected.details || {{}}).forEach(([key, value]) => {{
        profile[key] = value;
      }});
    }}

    function getSelectedModelOption(selectId) {{
      const select = document.getElementById(selectId);
      if (!select) {{
        setToolbarMessage("Model selector not found: " + selectId, true);
        return null;
      }}
      const option = select.selectedOptions[0];
      if (!option) {{
        setToolbarMessage("No model selected", true);
        return null;
      }}
      return {{
        select,
        profileId: select.dataset.profileId,
        modelId: option.value,
        provider: option.dataset.provider ? JSON.parse(option.dataset.provider) : {{}},
        model: option.dataset.model,
        label: option.dataset.label || option.dataset.model || option.value,
        apiKeyEnv: option.dataset.apiKeyEnv || "",
        details: option.dataset.details ? JSON.parse(option.dataset.details) : {{}}
      }};
    }}

    async function applySelectedProfileModel(selectId) {{
      const selected = getSelectedModelOption(selectId);
      if (!selected || !selected.profileId || !selected.model) {{
        return;
      }}
      const lang = document.getElementById("lang-switch").value;
      const card = selected.select.closest(".collapsible-card");
      if (!draftPublicConfig.llm) {{
        draftPublicConfig.llm = {{}};
      }}
      if (!draftPublicConfig.llm.profiles) {{
        draftPublicConfig.llm.profiles = {{}};
      }}
      if (!draftPublicConfig.llm.profiles[selected.profileId]) {{
        draftPublicConfig.llm.profiles[selected.profileId] = {{}};
      }}
      applySelectedModelToProfile(draftPublicConfig.llm.profiles[selected.profileId], selected);
      const state = rememberCardState(card);
      const response = await fetch("/preview-llm-profile-card", {{
        method: "POST",
        headers: {{ "Content-Type": "application/x-www-form-urlencoded" }},
        body: new URLSearchParams({{
          payload: JSON.stringify(collectPayload()),
          base_hash: collectBaseHash(),
          draft_meta: JSON.stringify(collectDraftMeta()),
          profile_id: selected.profileId,
          lang
        }})
      }});
      const result = await response.json();
      if (!result.ok) {{
        setToolbarMessage("{html.escape(t['save_failed'])}: " + result.message, true);
        showToast("error", "{html.escape(t['save_failed_title'])}", result.message);
        return;
      }}
      const newCard = replaceCardHtml(card, result.html || "");
      restoreCardState(newCard, state);
      setToolbarMessage(result.message || "{html.escape(t['confirm_success'])}", false);
      showToast("success", "{html.escape(t['confirm_success_title'])}", result.message || "{html.escape(t['confirm_success'])}");
    }}

    async function testSelectedProfileModel(selectId) {{
      const selected = getSelectedModelOption(selectId);
      if (!selected || !selected.profileId || !selected.model) {{
        return;
      }}
      const lang = document.getElementById("lang-switch").value;
      const payload = collectPayload();
      if (!payload.llm) {{
        payload.llm = {{}};
      }}
      if (!payload.llm.profiles) {{
        payload.llm.profiles = {{}};
      }}
      if (!payload.llm.profiles[selected.profileId]) {{
        payload.llm.profiles[selected.profileId] = {{}};
      }}
      applySelectedModelToProfile(payload.llm.profiles[selected.profileId], selected);
      const response = await fetch("/test-llm", {{
        method: "POST",
        headers: {{ "Content-Type": "application/x-www-form-urlencoded" }},
        body: new URLSearchParams({{
          payload: JSON.stringify(payload),
          base_hash: collectBaseHash(),
          draft_meta: JSON.stringify(collectDraftMeta()),
          profile_id: selected.profileId,
          lang
        }})
      }});
      const result = await response.json();
      const title = result.ok ? "{html.escape(t['test_success_title'])}" : "{html.escape(t['test_failed_title'])}";
      const routeDetail = [result.provider_kind || selected.provider.kind || "", result.base_url || "", result.api_key_source || ""].filter(Boolean).join(" · ");
      const detail = selected.profileId + " / " + (result.model || selected.model) + (routeDetail ? " [" + routeDetail + "]" : "") + ": " + result.message;
      setToolbarMessage(detail, !result.ok);
      showToast(result.ok ? "success" : "error", title, detail);
    }}

    function selectConfigPage(pageId, event) {{
      if (event) {{
        event.preventDefault();
      }}
      const pages = document.querySelectorAll("[data-config-page]");
      const navItems = document.querySelectorAll("[data-config-nav]");
      let matched = false;
      pages.forEach((page) => {{
        const isActive = page.dataset.configPage === pageId;
        page.classList.toggle("is-active", isActive);
        if (isActive) {{
          matched = true;
        }}
      }});
      if (!matched && pages.length > 0) {{
        pageId = pages[0].dataset.configPage;
        pages[0].classList.add("is-active");
      }}
      navItems.forEach((item) => {{
        item.classList.toggle("is-active", item.dataset.configNav === pageId);
      }});
      if (pageId) {{
        history.replaceState(null, "", "#section-" + pageId);
      }}
    }}

    function activateInitialConfigPage() {{
      const fromHash = window.location.hash.replace(/^#section-/, "");
      selectConfigPage(fromHash || "llm-model-library");
    }}

    function toggleSection(button) {{
      const section = button.closest("[data-collapsible-section], [data-collapsible-card]");
      if (!section) {{
        return;
      }}
      const content = document.getElementById(button.getAttribute("aria-controls"));
      const isExpanded = button.getAttribute("aria-expanded") === "true";
      button.setAttribute("aria-expanded", isExpanded ? "false" : "true");
      section.classList.toggle("is-collapsed", isExpanded);
      if (content) {{
        content.hidden = isExpanded;
      }}
    }}

    window.addEventListener("DOMContentLoaded", activateInitialConfigPage);
    window.addEventListener("hashchange", activateInitialConfigPage);

    function nextClonedProfileId(baseId, profiles) {{
      const root = (baseId || "profile").trim() || "profile";
      let candidate = root + "_copy";
      let suffix = 2;
      while (profiles && Object.prototype.hasOwnProperty.call(profiles, candidate)) {{
        candidate = root + "_copy_" + suffix;
        suffix += 1;
      }}
      return candidate;
    }}

    function cloneLlmProfile(sourceProfileId, selectId) {{
      const card = document.getElementById("add-llm-profile-card");
      const payload = collectPayload();
      const profiles = payload.llm && payload.llm.profiles ? payload.llm.profiles : {{}};
      const selected = selectId ? getSelectedModelOption(selectId) : null;
      if (!card) {{
        return;
      }}
      const profileIdField = card.querySelector('[data-add-profile-field="profile_id"]');
      const sourceField = card.querySelector('[data-add-profile-field="source_profile_id"]');
      const modelField = document.getElementById("add-llm-profile-model");
      if (profileIdField) {{
        profileIdField.value = nextClonedProfileId(sourceProfileId, profiles);
      }}
      if (sourceField) {{
        sourceField.value = sourceProfileId;
      }}
      if (modelField) {{
        modelField.value = (selected && selected.modelId) || "";
      }}
      card.hidden = false;
      card.scrollIntoView({{ behavior: "smooth", block: "nearest" }});
    }}

    function cancelInlineLlmProfile() {{
      const card = document.getElementById("add-llm-profile-card");
      if (!card) {{
        return;
      }}
      card.querySelectorAll("[data-add-profile-field]").forEach((field) => {{
        if (field.tagName === "SELECT") {{
          field.selectedIndex = 0;
        }} else {{
          field.value = "";
        }}
      }});
      const modelField = document.getElementById("add-llm-profile-model");
      if (modelField) {{
        modelField.selectedIndex = 0;
      }}
      card.hidden = true;
    }}

    async function saveInlineLlmProfile() {{
      const card = document.getElementById("add-llm-profile-card");
      const lang = document.getElementById("lang-switch").value;
      const profileId = (card.querySelector('[data-add-profile-field="profile_id"]')?.value || "").trim();
      const sourceProfileId = (card.querySelector('[data-add-profile-field="source_profile_id"]')?.value || "").trim();
      const modelId = (document.getElementById("add-llm-profile-model")?.value || "").trim();
      if (!profileId || !modelId) {{
        setToolbarMessage("{html.escape(t['save_failed'])}: profile_id and model_id are required", true);
        return;
      }}
      try {{
        const result = await postPreviewState(
          "/draft-add-llm-profile",
          {{
            payload: JSON.stringify(collectPayload()),
            draft_meta: JSON.stringify(collectDraftMeta()),
            profile_id: profileId,
            source_profile_id: sourceProfileId,
            model_id: modelId,
            lang
          }},
          activeConfigPageId("llm"),
        );
        setToolbarMessage(result.message || "{html.escape(t['confirm_success'])}", false);
        showToast("success", "{html.escape(t['confirm_success_title'])}", result.message || "{html.escape(t['confirm_success'])}");
      }} catch (error) {{
        setToolbarMessage("{html.escape(t['save_failed'])}: " + error.message, true);
        showToast("error", "{html.escape(t['save_failed_title'])}", error.message);
      }}
    }}

    function resetInlineLlmModelFields() {{
      const card = document.getElementById("add-llm-model-card");
      if (card) {{
        const preset = card.querySelector("[data-add-model-preset]");
        if (preset) {{
          preset.value = "";
        }}
        card.querySelectorAll("[data-add-model-field]").forEach((field) => {{
          if (field.type === "checkbox") {{
            field.checked = field.hasAttribute("checked");
            return;
          }}
          if (field.tagName === "SELECT") {{
            field.selectedIndex = 0;
          }} else {{
            field.value = "";
          }}
        }});
        applyProviderFields(card, "data-add-model-field", {{ kind: "openai", compat_mode: "openai", requires_api_key: true }});
        setAddModelField("strict_compatibility", true);
        setAddModelField("streaming", true);
        setAddModelField("discovery_enabled", true);
      }}
    }}

    function addLlmModel() {{
      const card = document.getElementById("add-llm-model-card");
      if (card) {{
        card.hidden = false;
      }}
    }}

    function addCustomLlmModel() {{
      const card = document.getElementById("add-llm-model-card");
      if (!card) {{
        return;
      }}
      card.hidden = false;
      resetInlineLlmModelFields();
      const modelIdField = card.querySelector('[data-add-model-field="model_id"]');
      if (modelIdField) {{
        modelIdField.focus();
      }}
    }}

    function setAddModelField(key, value) {{
      const field = document.querySelector('[data-add-model-field="' + key + '"]');
      if (!field) {{
        return;
      }}
      if (field.type === "checkbox") {{
        field.checked = !!value;
        return;
      }}
      if (field.tagName === "SELECT") {{
        let option = Array.from(field.options).find((item) => item.value === value);
        if (!option && value) {{
          option = new Option(value, value);
          field.add(option);
        }}
        field.value = value;
        return;
      }}
      field.value = value || "";
    }}

    function applyLlmModelPreset(presetId) {{
      const preset = LLM_MODEL_PRESETS[presetId];
      if (!preset) {{
        resetInlineLlmModelFields();
        return;
      }}
      const modelDefaults = preset.model || {{}};
      const providerDefaults = preset.provider || {{}};
      setAddModelField("model_id", preset.model_id || "");
      applyProviderFields(document.getElementById("add-llm-model-card"), "data-add-model-field", providerDefaults);
      setAddModelField("model", modelDefaults.model || "");
      setAddModelField("label", modelDefaults.label || preset.label || modelDefaults.model || "");
      setAddModelField("api_key_env", "");
      setAddModelField("transport", modelDefaults.transport || "chat_completions");
      setAddModelField("contract", modelDefaults.contract || "tool_chat");
      setAddModelField("reasoning_state_field", modelDefaults.reasoning_state_field || "");
      setAddModelField("strict_compatibility", modelDefaults.strict_compatibility !== false);
      setAddModelField("streaming", modelDefaults.streaming !== false);
      setAddModelField("discovery_enabled", modelDefaults.discovery_enabled !== false);
      setAddModelField("tool_calling_mode", modelDefaults.tool_calling_mode || "auto");
      setAddModelField("temperature", modelDefaults.temperature ?? "");
      setAddModelField("max_output_tokens", modelDefaults.max_output_tokens ?? "");
      setAddModelField("timeout", modelDefaults.timeout ?? "");
      setAddModelField("connect_timeout", modelDefaults.connect_timeout ?? "");
      setAddModelField("api_key", "");
    }}

    function cancelInlineLlmModel() {{
      const card = document.getElementById("add-llm-model-card");
      if (!card) {{
        return;
      }}
      resetInlineLlmModelFields();
      card.hidden = true;
    }}

    async function saveInlineLlmModel() {{
      const card = document.getElementById("add-llm-model-card");
      const lang = document.getElementById("lang-switch").value;
      const presetId = (card.querySelector("[data-add-model-preset]")?.value || "").trim();
      const modelId = (card.querySelector('[data-add-model-field="model_id"]')?.value || "").trim();
      const model = (card.querySelector('[data-add-model-field="model"]')?.value || "").trim();
      const label = (card.querySelector('[data-add-model-field="label"]')?.value || model).trim() || model;
      let provider;
      try {{
        provider = collectProviderFields(card, "data-add-model-field");
      }} catch (error) {{
        setToolbarMessage(error.message, true);
        return;
      }}
      const details = collectModelDetails(card, "data-add-model-field");
      const apiKeyEnv = String(fieldByAttr(card, "data-add-model-field", "api_key_env")?.value || "").trim();
      const apiKey = (card.querySelector('[data-add-model-field="api_key"]')?.value || "").trim();
      if (!modelId || !provider.kind || !model) {{
        setToolbarMessage("{html.escape(t['save_failed'])}: model_id, provider.kind and model are required", true);
        return;
      }}
      try {{
        const result = await postPreviewState(
          "/draft-add-llm-model",
          {{
            payload: JSON.stringify(collectPayload()),
            draft_meta: JSON.stringify(collectDraftMeta()),
            preset_id: presetId,
            model_id: modelId,
            provider: JSON.stringify(provider),
            model,
            label,
            details: JSON.stringify(details),
            api_key_env: apiKeyEnv,
            api_key: apiKey,
            lang
          }},
          activeConfigPageId("llm-model-library"),
        );
        setToolbarMessage(result.message || "{html.escape(t['confirm_success'])}", false);
        showToast("success", "{html.escape(t['confirm_success_title'])}", result.message || "{html.escape(t['confirm_success'])}");
      }} catch (error) {{
        setToolbarMessage("{html.escape(t['save_failed'])}: " + error.message, true);
        showToast("error", "{html.escape(t['save_failed_title'])}", error.message);
      }}
    }}

    function editLlmModel(button) {{
      const card = button.closest("[data-model-library-id]");
      if (!card) {{
        setToolbarMessage("Model card not found", true);
        return;
      }}
      const modelField = card.querySelector('[data-edit-field="model"]');
      const labelField = card.querySelector('[data-edit-field="label"]');
      const provider = card.dataset.provider ? JSON.parse(card.dataset.provider) : {{}};
      const details = card.dataset.details ? JSON.parse(card.dataset.details) : {{}};
      applyProviderFields(card, "data-edit-field", provider);
      applyModelDetails(card, "data-edit-field", details);
      if (modelField) {{
        modelField.value = card.dataset.model || "";
      }}
      if (labelField) {{
        labelField.value = card.dataset.label || card.dataset.model || "";
      }}
      setFieldByAttr(card, "data-edit-field", "api_key_env", card.dataset.apiKeyEnv || "");
      const editor = card.querySelector(".model-library-edit");
      if (editor) {{
        editor.hidden = false;
      }}
      card.classList.add("is-editing");
    }}

    function cancelLlmModelEdit(button) {{
      const card = button.closest("[data-model-library-id]");
      if (!card) {{
        return;
      }}
      const editor = card.querySelector(".model-library-edit");
      if (editor) {{
        editor.hidden = true;
      }}
      const deletePanel = card.querySelector(".model-library-delete");
      if (deletePanel) {{
        deletePanel.remove();
      }}
      card.classList.remove("is-editing", "is-deleting");
    }}

    async function saveLlmModelEdit(button) {{
      const card = button.closest("[data-model-library-id]");
      if (!card) {{
        setToolbarMessage("Model card not found", true);
        return;
      }}
      const modelId = card.dataset.modelLibraryId;
      const lang = document.getElementById("lang-switch").value;
      const model = (card.querySelector('[data-edit-field="model"]')?.value || "").trim();
      const label = (card.querySelector('[data-edit-field="label"]')?.value || model).trim() || model;
      const apiKey = (card.querySelector("[data-edit-api-key]")?.value || "").trim();
      const clearApiKey = card.querySelector("[data-clear-api-key]")?.checked ? "1" : "";
      let provider;
      try {{
        provider = collectProviderFields(card, "data-edit-field");
      }} catch (error) {{
        setToolbarMessage(error.message, true);
        return;
      }}
      const details = collectModelDetails(card, "data-edit-field");
      const apiKeyEnv = String(fieldByAttr(card, "data-edit-field", "api_key_env")?.value || "").trim();
      if (!provider.kind || !model) {{
        setToolbarMessage("{html.escape(t['save_failed'])}: provider.kind and model are required", true);
        return;
      }}
      try {{
        const result = await postPreviewState(
          "/draft-update-llm-model",
          {{
            payload: JSON.stringify(collectPayload()),
            draft_meta: JSON.stringify(collectDraftMeta()),
            model_id: modelId,
            provider: JSON.stringify(provider),
            model,
            label,
            details: JSON.stringify(details),
            api_key_env: apiKeyEnv,
            api_key: apiKey,
            clear_api_key: clearApiKey,
            lang
          }},
          activeConfigPageId("llm-model-library"),
        );
        setToolbarMessage(result.message || "{html.escape(t['confirm_success'])}", false);
        showToast("success", "{html.escape(t['confirm_success_title'])}", result.message || "{html.escape(t['confirm_success'])}");
      }} catch (error) {{
        setToolbarMessage("{html.escape(t['save_failed'])}: " + error.message, true);
        showToast("error", "{html.escape(t['save_failed_title'])}", error.message);
      }}
    }}

    function deleteLlmModel(modelId) {{
      const card = document.querySelector('[data-model-library-id="' + CSS.escape(modelId) + '"]');
      if (!card) {{
        setToolbarMessage("Model card not found: " + modelId, true);
        return;
      }}
      card.classList.add("is-editing", "is-deleting");
      const editor = card.querySelector(".model-library-edit");
      if (editor) {{
        editor.hidden = false;
      }}
      let deletePanel = card.querySelector(".model-library-delete");
      if (!deletePanel) {{
        deletePanel = document.createElement("div");
        deletePanel.className = "model-library-delete";
        deletePanel.innerHTML = '<span>{html.escape(t["delete_model"])}: ' + modelId + '</span><div class="model-library-actions"><button type="button" class="card-action subtle" onclick="confirmInlineLlmModelDelete(this)">{html.escape(t["delete_model"])}</button><button type="button" class="card-action" onclick="cancelLlmModelEdit(this)">{html.escape(t["cancel"])}</button></div>';
        card.appendChild(deletePanel);
      }}
    }}

    async function confirmInlineLlmModelDelete(button) {{
      const card = button.closest("[data-model-library-id]");
      const modelId = card ? card.dataset.modelLibraryId : "";
      const lang = document.getElementById("lang-switch").value;
      if (!modelId) {{
        return;
      }}
      try {{
        const result = await postPreviewState(
          "/draft-delete-llm-model",
          {{
            payload: JSON.stringify(collectPayload()),
            draft_meta: JSON.stringify(collectDraftMeta()),
            model_id: modelId,
            lang
          }},
          activeConfigPageId("llm-model-library"),
        );
        setToolbarMessage(result.message || "{html.escape(t['confirm_success'])}", false);
        showToast("success", "{html.escape(t['confirm_success_title'])}", result.message || "{html.escape(t['confirm_success'])}");
      }} catch (error) {{
        setToolbarMessage("{html.escape(t['save_failed'])}: " + error.message, true);
        showToast("error", "{html.escape(t['save_failed_title'])}", error.message);
      }}
    }}

    async function testProfileLlm(profileId) {{
      const lang = document.getElementById("lang-switch").value;
      const payload = collectPayload();
      const response = await fetch("/test-llm", {{
        method: "POST",
        headers: {{ "Content-Type": "application/x-www-form-urlencoded" }},
        body: new URLSearchParams({{
          payload: JSON.stringify(payload),
          base_hash: collectBaseHash(),
          draft_meta: JSON.stringify(collectDraftMeta()),
          profile_id: profileId,
          lang
        }})
      }});
      const result = await response.json();
      const title = result.ok ? "{html.escape(t['test_success_title'])}" : "{html.escape(t['test_failed_title'])}";
      const detail = profileId + " / " + (result.model || "") + ": " + result.message;
      setToolbarMessage(detail, !result.ok);
      showToast(result.ok ? "success" : "error", title, detail);
    }}

    async function testSelectedCardLlm(selectId) {{
      const select = document.getElementById(selectId);
      if (!select) {{
        setToolbarMessage("LLM selector not found: " + selectId, true);
        return;
      }}
      const lang = document.getElementById("lang-switch").value;
      const payload = collectPayload();
      const response = await fetch("/test-llm", {{
        method: "POST",
        headers: {{ "Content-Type": "application/x-www-form-urlencoded" }},
        body: new URLSearchParams({{
          payload: JSON.stringify(payload),
          base_hash: collectBaseHash(),
          draft_meta: JSON.stringify(collectDraftMeta()),
          profile_id: select.value,
          lang
        }})
      }});
      const result = await response.json();
      const title = result.ok ? "{html.escape(t['test_success_title'])}" : "{html.escape(t['test_failed_title'])}";
      const detail = (result.profile_id || select.value) + " / " + (result.model || "") + ": " + result.message;
      setToolbarMessage(detail, !result.ok);
      showToast(result.ok ? "success" : "error", title, detail);
    }}

    function switchLang(lang) {{
      if (!draftPublicConfig.ui) {{
        draftPublicConfig.ui = {{}};
      }}
      draftPublicConfig.ui.language = lang;
      previewDraft(draftPublicConfig, lang);
    }}

    async function saveConfig() {{
      const payload = collectPayload();
      document.getElementById("payload").value = JSON.stringify(payload);
      const lang = document.getElementById("lang-switch").value;
      if (!payload.ui) {{
        payload.ui = {{}};
      }}
      payload.ui.language = lang;
      const response = await postConfig(payload, lang);
      const result = await response.json();
      if (!result.ok) {{
        const fullMessage = "{html.escape(t['save_failed'])}: " + result.message;
        setToolbarMessage(fullMessage, true);
        showToast("error", "{html.escape(t['save_failed_title'])}", result.message);
        return;
      }}
      setToolbarMessage(result.message, false);
      showToast("success", "{html.escape(t['save_success_title'])}", result.message);
      reloadConfigPage(lang, result.message, 700);
    }}
  </script>
</body>
</html>"""


def _submitted_public_config(form: dict, old_public: dict) -> dict:
    payload = form.get("payload", [""])[0]
    submitted = json.loads(payload) if payload else copy.deepcopy(old_public)
    return preserve_secret_blanks(submitted, old_public)


def _submitted_base_hash(form: dict) -> str:
    return str(form.get("base_hash", [""])[0] or "").strip()


def _resolve_base_hash(form: dict, old_public: dict) -> str:
    submitted = _submitted_base_hash(form)
    return submitted or public_config_hash(old_public)


def _submitted_response_mode(form: dict) -> str:
    return str(form.get("response_mode", [""])[0] or "").strip().lower()


def _wants_fragment_preview(form: dict) -> bool:
    return _submitted_response_mode(form) == "fragments"


def _assert_base_hash_matches(base_hash: str, old_public: dict, lang: str) -> str:
    current_hash = public_config_hash(old_public)
    expected_hash = str(base_hash or "").strip()
    if expected_hash and expected_hash != current_hash:
        raise ConfigConflictError(I18N[lang]["stale_config"])
    return current_hash


def _submitted_draft_meta(form: dict) -> dict[str, object]:
    raw = form.get("draft_meta", ["{}"])[0] or "{}"
    return _normalize_draft_meta(json.loads(raw))


def _with_pending_api_key(meta: dict[str, object], api_key_env: str, api_key: str) -> dict[str, object]:
    payload = _normalize_draft_meta(meta)
    env_name = str(api_key_env or "").strip()
    if not env_name:
        return payload
    pending = payload["pending_api_keys"]
    cleared = payload["pending_cleared_api_keys"]
    if isinstance(pending, dict):
        pending[env_name] = api_key
    if isinstance(cleared, list):
        payload["pending_cleared_api_keys"] = [item for item in cleared if item != env_name]
    return payload


def _with_cleared_api_key(meta: dict[str, object], api_key_env: str) -> dict[str, object]:
    payload = _normalize_draft_meta(meta)
    env_name = str(api_key_env or "").strip()
    if not env_name:
        return payload
    pending = payload["pending_api_keys"]
    cleared = payload["pending_cleared_api_keys"]
    if isinstance(pending, dict):
        pending.pop(env_name, None)
    if isinstance(cleared, list) and env_name not in cleared:
        cleared.append(env_name)
    return payload


def _drop_api_key_state(meta: dict[str, object], api_key_env: str) -> dict[str, object]:
    payload = _normalize_draft_meta(meta)
    env_name = str(api_key_env or "").strip()
    if not env_name:
        return payload
    pending = payload["pending_api_keys"]
    cleared = payload["pending_cleared_api_keys"]
    if isinstance(pending, dict):
        pending.pop(env_name, None)
    if isinstance(cleared, list):
        payload["pending_cleared_api_keys"] = [item for item in cleared if item != env_name]
    return payload


def _render_preview_html(
    public_config: dict,
    lang: str,
    draft_meta: dict[str, object],
    message: str,
    base_hash: str,
) -> str:
    return render_panel_html(public_config, message, lang, draft_meta, base_hash=base_hash)


def _render_preview_state_payload(
    public_config: dict,
    lang: str,
    draft_meta: dict[str, object],
    message: str,
    base_hash: str,
) -> dict[str, object]:
    normalized_draft_meta = _normalize_draft_meta(draft_meta)
    updated_public_config = _with_config_language(public_config, lang)
    resolved_base_hash = str(base_hash or public_config_hash(public_config)).strip()
    return {
        "ok": True,
        "message": message,
        "lang": lang,
        "base_hash": resolved_base_hash,
        "public_config": updated_public_config,
        "draft_meta": normalized_draft_meta,
        "main_html": _render_config_form_contents(
            updated_public_config,
            message,
            lang,
            normalized_draft_meta,
            resolved_base_hash,
        ),
        "aside_html": _render_diagnostics_aside(updated_public_config, lang),
    }


def _render_profile_card_preview(public_config: dict, profile_id: str, lang: str) -> str:
    return _render_llm_profile_card(public_config, profile_id, lang)


class ConfigPanelHandler(BaseHTTPRequestHandler):
    def _send_html(self, html_text: str, status: int = 200) -> None:
        data = html_text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("X-Config-Panel-Build", PANEL_BUILD_ID)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, payload: dict, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/":
            self._send_json({"ok": False, "message": "Not found"}, status=404)
            return
        params = parse_qs(parsed.query)
        message = params.get("message", [""])[0]
        lang = resolve_lang(params.get("lang", [DEFAULT_LANG])[0])
        public_config = load_public_config()
        effective_lang = lang if "lang" in params else get_config_language(public_config)
        self._send_html(
            render_panel_html(
                public_config,
                message,
                effective_lang,
                base_hash=public_config_hash(public_config),
            )
        )

    def do_POST(self) -> None:
        if self.path not in {
            "/preview",
            "/preview-config-card",
            "/preview-llm-profile-card",
            "/save",
            "/add-llm-profile",
            "/add-llm-model",
            "/update-llm-model",
            "/delete-llm-model",
            "/draft-add-llm-profile",
            "/draft-add-llm-model",
            "/draft-update-llm-model",
            "/draft-delete-llm-model",
            "/test-llm",
        }:
            self._send_json({"ok": False, "message": "Not found"}, status=404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        form = parse_qs(raw)
        lang = resolve_lang(form.get("lang", [DEFAULT_LANG])[0])
        fragment_preview = _wants_fragment_preview(form)
        old_public: dict = {}
        current_base_hash = ""
        submitted_base_hash = _submitted_base_hash(form)
        try:
            old_public = load_public_config()
            current_base_hash = public_config_hash(old_public)
            if self.path == "/preview":
                submitted = _submitted_public_config(form, old_public)
                submitted.setdefault("ui", {})
                if isinstance(submitted["ui"], dict):
                    submitted["ui"]["language"] = lang
                draft_meta = _submitted_draft_meta(form)
                message = form.get("message", [""])[0]
                self._send_html(
                    _render_preview_html(
                        submitted,
                        lang,
                        draft_meta,
                        message,
                        _resolve_base_hash(form, old_public),
                    )
                )
                return

            if self.path == "/preview-config-card":
                submitted = _submitted_public_config(form, old_public)
                card_path = form.get("card_path", [""])[0]
                self._send_json(
                    {
                        "ok": True,
                        "html": _render_config_card_preview(submitted, card_path, lang),
                        "message": I18N[lang]["confirm_success"],
                    }
                )
                return

            if self.path == "/preview-llm-profile-card":
                submitted = _submitted_public_config(form, old_public)
                profile_id = form.get("profile_id", [""])[0]
                self._send_json(
                    {
                        "ok": True,
                        "html": _render_profile_card_preview(submitted, profile_id, lang),
                        "message": I18N[lang]["confirm_success"],
                    }
                )
                return

            if self.path in {"/add-llm-profile", "/draft-add-llm-profile"}:
                current = _submitted_public_config(form, old_public) if self.path.startswith("/draft-") else old_public
                updated = add_llm_profile(
                    current,
                    form.get("profile_id", [""])[0],
                    source_profile_id=form.get("source_profile_id", [""])[0],
                    model_id=form.get("model_id", [""])[0],
                )
                if self.path.startswith("/draft-"):
                    draft_meta = _submitted_draft_meta(form)
                    if fragment_preview:
                        self._send_json(
                            _render_preview_state_payload(
                                updated,
                                lang,
                                draft_meta,
                                I18N[lang]["confirm_success"],
                                _resolve_base_hash(form, old_public),
                            )
                        )
                    else:
                        self._send_html(
                            _render_preview_html(
                                updated,
                                lang,
                                draft_meta,
                                I18N[lang]["confirm_success"],
                                _resolve_base_hash(form, old_public),
                            )
                        )
                    return
                _assert_base_hash_matches(submitted_base_hash, old_public, lang)
                save_public_config(updated)
                self._send_json({"ok": True, "message": I18N[lang]["save_success"]})
                return

            if self.path in {"/add-llm-model", "/draft-add-llm-model"}:
                current = _submitted_public_config(form, old_public) if self.path.startswith("/draft-") else old_public
                draft_meta = _submitted_draft_meta(form) if self.path.startswith("/draft-") else _empty_draft_meta()
                preset_id = form.get("preset_id", [""])[0]
                details = json.loads(form.get("details", ["{}"])[0] or "{}")
                provider = json.loads(form.get("provider", ["{}"])[0] or "{}")
                before_keys = set(current.get("llm", {}).get("model_library", {}).keys()) if isinstance(current.get("llm", {}), dict) else set()
                if preset_id:
                    updated = apply_llm_model_preset(
                        current,
                        preset_id,
                        form.get("model_id", [""])[0],
                        provider,
                        form.get("model", [""])[0],
                        form.get("label", [""])[0],
                        details,
                        form.get("api_key_env", [""])[0],
                    )
                else:
                    updated = add_llm_model(
                        current,
                        form.get("model_id", [""])[0],
                        provider,
                        form.get("model", [""])[0],
                        form.get("label", [""])[0],
                        details,
                        api_key_env=form.get("api_key_env", [""])[0],
                    )
                after_library = updated.get("llm", {}).get("model_library", {}) if isinstance(updated.get("llm", {}), dict) else {}
                resolved_model_id = form.get("model_id", [""])[0].strip()
                if not resolved_model_id and isinstance(after_library, dict):
                    created = [key for key in after_library.keys() if key not in before_keys]
                    if created:
                        resolved_model_id = str(created[0])
                api_key_env = (
                    str(after_library.get(resolved_model_id, {}).get("api_key_env", "")).strip()
                    if isinstance(after_library, dict)
                    else ""
                )
                api_key = form.get("api_key", [""])[0]
                if self.path.startswith("/draft-"):
                    if api_key and api_key_env:
                        draft_meta = _with_pending_api_key(draft_meta, api_key_env, api_key)
                    if fragment_preview:
                        self._send_json(
                            _render_preview_state_payload(
                                updated,
                                lang,
                                draft_meta,
                                I18N[lang]["confirm_success"],
                                _resolve_base_hash(form, old_public),
                            )
                        )
                    else:
                        self._send_html(
                            _render_preview_html(
                                updated,
                                lang,
                                draft_meta,
                                I18N[lang]["confirm_success"],
                                _resolve_base_hash(form, old_public),
                            )
                        )
                    return
                _assert_base_hash_matches(submitted_base_hash, old_public, lang)
                if api_key and resolved_model_id:
                    set_llm_model_api_key(updated, resolved_model_id, api_key)
                save_public_config(updated)
                self._send_json({"ok": True, "message": I18N[lang]["save_success"]})
                return

            if self.path in {"/update-llm-model", "/draft-update-llm-model"}:
                current = _submitted_public_config(form, old_public) if self.path.startswith("/draft-") else old_public
                draft_meta = _submitted_draft_meta(form) if self.path.startswith("/draft-") else _empty_draft_meta()
                model_id = form.get("model_id", [""])[0]
                current_library = current.get("llm", {}).get("model_library", {}) if isinstance(current.get("llm", {}), dict) else {}
                old_item = current_library.get(model_id, {}) if isinstance(current_library, dict) else {}
                old_env = str(old_item.get("api_key_env", "")).strip() if isinstance(old_item, dict) else ""
                details = json.loads(form.get("details", ["{}"])[0] or "{}")
                provider = json.loads(form.get("provider", ["{}"])[0] or "{}")
                updated = update_llm_model(
                    current,
                    model_id,
                    provider,
                    form.get("model", [""])[0],
                    form.get("label", [""])[0],
                    details,
                    form.get("api_key_env", [""])[0],
                )
                updated_library = updated.get("llm", {}).get("model_library", {}) if isinstance(updated.get("llm", {}), dict) else {}
                new_item = updated_library.get(model_id, {}) if isinstance(updated_library, dict) else {}
                new_env = str(new_item.get("api_key_env", "")).strip() if isinstance(new_item, dict) else ""
                if self.path.startswith("/draft-"):
                    draft_meta = _move_pending_api_key_env(draft_meta, old_env, new_env)
                    if form.get("clear_api_key", [""])[0] in {"1", "true", "yes", "on"}:
                        draft_meta = _with_cleared_api_key(draft_meta, new_env)
                    elif form.get("api_key", [""])[0]:
                        draft_meta = _with_pending_api_key(draft_meta, new_env, form.get("api_key", [""])[0])
                    if fragment_preview:
                        self._send_json(
                            _render_preview_state_payload(
                                updated,
                                lang,
                                draft_meta,
                                I18N[lang]["confirm_success"],
                                _resolve_base_hash(form, old_public),
                            )
                        )
                    else:
                        self._send_html(
                            _render_preview_html(
                                updated,
                                lang,
                                draft_meta,
                                I18N[lang]["confirm_success"],
                                _resolve_base_hash(form, old_public),
                            )
                        )
                    return
                _assert_base_hash_matches(submitted_base_hash, old_public, lang)
                if form.get("clear_api_key", [""])[0] in {"1", "true", "yes", "on"}:
                    clear_llm_model_api_key(updated, model_id)
                elif form.get("api_key", [""])[0]:
                    set_llm_model_api_key(updated, model_id, form.get("api_key", [""])[0])
                save_public_config(updated)
                self._send_json({"ok": True, "message": I18N[lang]["save_success"]})
                return

            if self.path in {"/delete-llm-model", "/draft-delete-llm-model"}:
                current = _submitted_public_config(form, old_public) if self.path.startswith("/draft-") else old_public
                draft_meta = _submitted_draft_meta(form) if self.path.startswith("/draft-") else _empty_draft_meta()
                model_id = form.get("model_id", [""])[0]
                current_library = current.get("llm", {}).get("model_library", {}) if isinstance(current.get("llm", {}), dict) else {}
                old_item = current_library.get(model_id, {}) if isinstance(current_library, dict) else {}
                old_env = str(old_item.get("api_key_env", "")).strip() if isinstance(old_item, dict) else ""
                updated = delete_llm_model(current, model_id)
                if self.path.startswith("/draft-"):
                    draft_meta = _drop_api_key_state(draft_meta, old_env)
                    if fragment_preview:
                        self._send_json(
                            _render_preview_state_payload(
                                updated,
                                lang,
                                draft_meta,
                                I18N[lang]["confirm_success"],
                                _resolve_base_hash(form, old_public),
                            )
                        )
                    else:
                        self._send_html(
                            _render_preview_html(
                                updated,
                                lang,
                                draft_meta,
                                I18N[lang]["confirm_success"],
                                _resolve_base_hash(form, old_public),
                            )
                        )
                    return
                _assert_base_hash_matches(submitted_base_hash, old_public, lang)
                save_public_config(updated)
                self._send_json({"ok": True, "message": I18N[lang]["save_success"]})
                return

            if self.path == "/test-llm":
                profile_id = form.get("profile_id", [""])[0] or None
                submitted = _submitted_public_config(form, old_public)
                draft_meta = _submitted_draft_meta(form)
                result = test_llm_connection(submitted, profile_id, draft_meta)
                self._send_json(result, status=200 if result.get("ok") else 400)
                return

            submitted = _submitted_public_config(form, old_public)
            submitted.setdefault("ui", {})
            if isinstance(submitted["ui"], dict):
                submitted["ui"]["language"] = lang
            draft_meta = _submitted_draft_meta(form)
            _assert_base_hash_matches(submitted_base_hash, old_public, lang)
            validate_llm_public_config(submitted)
            _validate_required_llm_profiles(submitted, lang)
            build_effective_config(submitted)
            save_public_config(submitted)
            for env_name in draft_meta.get("pending_cleared_api_keys", []):
                _delete_user_env_var(str(env_name))
            for env_name, api_key in draft_meta.get("pending_api_keys", {}).items():
                _set_user_env_var(str(env_name), str(api_key))
            self._send_json({"ok": True, "message": I18N[lang]["save_success"]})
        except Exception as exc:
            html_preview_paths = {
                "/preview",
                "/draft-add-llm-profile",
                "/draft-add-llm-model",
                "/draft-update-llm-model",
                "/draft-delete-llm-model",
            }
            if self.path in {"/preview-config-card", "/preview-llm-profile-card"}:
                self._send_json({"ok": False, "message": str(exc)}, status=400)
                return
            if fragment_preview and self.path in html_preview_paths:
                self._send_json({"ok": False, "message": str(exc)}, status=400)
                return
            if self.path in html_preview_paths:
                try:
                    submitted = _submitted_public_config(form, old_public)
                except Exception:
                    submitted = copy.deepcopy(old_public)
                submitted.setdefault("ui", {})
                if isinstance(submitted["ui"], dict):
                    submitted["ui"]["language"] = lang
                draft_meta = _submitted_draft_meta(form)
                message = f'{I18N[lang]["save_failed"]}: {exc}'
                self._send_html(
                    _render_preview_html(
                        submitted,
                        lang,
                        draft_meta,
                        message,
                        submitted_base_hash or current_base_hash,
                    ),
                    status=400,
                )
                return
            status = 409 if isinstance(exc, ConfigConflictError) else 400
            self._send_json({"ok": False, "message": str(exc)}, status=status)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


def run_server(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), ConfigPanelHandler)
    url = f"http://{host}:{port}"
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    print(f"Config Panel running at {url}")
    server.serve_forever()
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="Vibelution Config Panel")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    run_server(host=args.host, port=args.port, open_browser=not args.no_browser)


if __name__ == "__main__":
    main()
