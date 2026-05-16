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
import tomllib
import urllib.error
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import AppConfig, denormalize_config_dict, normalize_public_config_dict  # noqa: E402
from config.profiles import apply_runtime_profile  # noqa: E402
from config.toml_writer import dumps_public_config  # noqa: E402
from core.llm import assert_llm_compatibility  # noqa: E402


CONFIG_PATH = PROJECT_ROOT / "config.toml"
DEFAULT_LANG = "zh"
PANEL_BUILD_ID = "config-panel-toast-v2"
MODEL_LIBRARY_DETAIL_FIELDS = (
    "api_key_env",
    "transport",
    "contract",
    "reasoning_state_field",
    "strict_compatibility",
    "temperature",
    "max_output_tokens",
    "timeout",
    "connect_timeout",
    "streaming",
    "tool_calling_mode",
    "discovery_enabled",
)
LLM_MODEL_PRESETS = {
    "openai_gpt_5_4": {
        "label": "OpenAI GPT-5.4",
        "provider_id": "openai_main",
        "model_id": "openai_gpt_5_4",
        "provider": {
            "kind": "openai",
            "api_key_env": "OPENAI_API_KEY",
            "base_url": "https://api.openai.com/v1",
            "compat_mode": "openai",
            "requires_api_key": True,
            "context_window": 1047576,
        },
        "model": {
            "model": "gpt-5.4",
            "label": "OpenAI GPT-5.4",
            "transport": "chat_completions",
            "contract": "tool_chat",
            "temperature": 0.7,
            "max_output_tokens": 128000,
            "timeout": 120,
            "connect_timeout": 20,
            "streaming": True,
            "tool_calling_mode": "auto",
            "discovery_enabled": True,
        },
    },
    "anthropic_claude_sonnet": {
        "label": "Anthropic Claude Sonnet",
        "provider_id": "anthropic_main",
        "model_id": "anthropic_claude_sonnet",
        "provider": {
            "kind": "anthropic",
            "api_key_env": "ANTHROPIC_API_KEY",
            "base_url": "https://api.anthropic.com",
            "compat_mode": "native",
            "requires_api_key": True,
            "context_window": 200000,
        },
        "model": {
            "model": "claude-sonnet-4-6",
            "label": "Anthropic Claude Sonnet",
            "transport": "chat_completions",
            "contract": "tool_chat",
            "temperature": 0.7,
            "max_output_tokens": 8192,
            "timeout": 120,
            "connect_timeout": 20,
            "streaming": True,
            "tool_calling_mode": "auto",
            "discovery_enabled": True,
        },
    },
    "deepseek_v4_pro": {
        "label": "DeepSeek V4 Pro",
        "provider_id": "deepseek_main",
        "model_id": "deepseek_v4_pro",
        "provider": {
            "kind": "deepseek",
            "api_key_env": "DEEPSEEK_API_KEY",
            "base_url": "https://api.deepseek.com",
            "compat_mode": "openai",
            "requires_api_key": True,
            "context_window": 131072,
        },
        "model": {
            "model": "deepseek-v4-pro",
            "label": "DeepSeek V4 Pro",
            "transport": "chat_completions",
            "contract": "tool_chat",
            "temperature": 0.7,
            "max_output_tokens": 8192,
            "timeout": 120,
            "connect_timeout": 20,
            "streaming": True,
            "tool_calling_mode": "auto",
            "discovery_enabled": True,
        },
    },
    "google_gemini_flash": {
        "label": "Google Gemini Flash",
        "provider_id": "google_main",
        "model_id": "google_gemini_flash",
        "provider": {
            "kind": "google",
            "api_key_env": "GOOGLE_API_KEY",
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
            "compat_mode": "openai",
            "requires_api_key": True,
            "context_window": 1048576,
        },
        "model": {
            "model": "gemini-3-flash-preview",
            "label": "Google Gemini Flash",
            "transport": "chat_completions",
            "contract": "tool_chat",
            "temperature": 0.7,
            "max_output_tokens": 8192,
            "timeout": 120,
            "connect_timeout": 20,
            "streaming": True,
            "tool_calling_mode": "auto",
            "discovery_enabled": True,
        },
    },
    "minimax_m2_7": {
        "label": "MiniMax M2.7",
        "provider_id": "minimax_main",
        "model_id": "minimax_m2_7",
        "provider": {
            "kind": "minimax",
            "api_key_env": "MINIMAX_API_KEY",
            "base_url": "https://api.minimax.io/v1",
            "compat_mode": "openai",
            "requires_api_key": True,
            "context_window": 204800,
        },
        "model": {
            "model": "MiniMax-M2.7",
            "label": "MiniMax M2.7",
            "transport": "chat_completions",
            "contract": "tool_chat",
            "temperature": 1.0,
            "max_output_tokens": 8192,
            "timeout": 120,
            "connect_timeout": 20,
            "streaming": True,
            "tool_calling_mode": "auto",
            "discovery_enabled": True,
        },
    },
    "dashscope_qwen3_6_plus": {
        "label": "阿里云 DashScope Qwen3.6 Plus",
        "provider_id": "dashscope_main",
        "model_id": "dashscope_qwen3_6_plus",
        "provider": {
            "kind": "aliyun",
            "api_key_env": "DASHSCOPE_API_KEY",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "compat_mode": "openai",
            "requires_api_key": True,
            "context_window": 131072,
        },
        "model": {
            "model": "qwen3.6-plus",
            "label": "阿里云 DashScope Qwen3.6 Plus",
            "transport": "chat_completions",
            "contract": "tool_chat",
            "temperature": 0.7,
            "max_output_tokens": 8192,
            "timeout": 120,
            "connect_timeout": 20,
            "streaming": True,
            "tool_calling_mode": "auto",
            "discovery_enabled": True,
        },
    },
    "siliconflow_glm_4_7": {
        "label": "硅基流动 GLM-4.7",
        "provider_id": "siliconflow_main",
        "model_id": "siliconflow_glm_4_7",
        "provider": {
            "kind": "siliconflow",
            "api_key_env": "SILICONFLOW_API_KEY",
            "base_url": "https://api.siliconflow.cn/v1",
            "compat_mode": "openai",
            "requires_api_key": True,
            "context_window": 131072,
        },
        "model": {
            "model": "Pro/zai-org/GLM-4.7",
            "label": "硅基流动 GLM-4.7",
            "transport": "chat_completions",
            "contract": "tool_chat",
            "temperature": 0.7,
            "max_output_tokens": 8192,
            "timeout": 120,
            "connect_timeout": 20,
            "streaming": True,
            "tool_calling_mode": "auto",
            "discovery_enabled": True,
        },
    },
    "local_openai_compatible": {
        "label": "本地 OpenAI-compatible",
        "provider_id": "local_main",
        "model_id": "local_openai_compatible",
        "provider": {
            "kind": "local",
            "api_key_env": "",
            "base_url": "http://localhost:11434/v1/",
            "compat_mode": "openai",
            "requires_api_key": False,
            "context_window": 65536,
        },
        "model": {
            "model": "llama3.2",
            "label": "本地 OpenAI-compatible",
            "transport": "chat_completions",
            "contract": "basic_chat",
            "temperature": 0.3,
            "max_output_tokens": 2048,
            "timeout": 45,
            "connect_timeout": 5,
            "streaming": False,
            "tool_calling_mode": "disabled",
            "discovery_enabled": False,
        },
    },
}
HEADER_LINES = [
    "# ============================================================",
    "# Self-Evolving Agent 主配置",
    "# ============================================================",
    "# 本文件是项目的完整主配置面。想知道项目当前如何运行，先看这里。",
    "# 模型默认值仅作为最低优先级兜底。",
    "# 配置优先级：命令行参数(kwargs) > 环境变量 > config.toml > 默认值",
    "# ============================================================",
]

RUNTIME_PROFILE_OPTIONS = ["safe_local", "safe_remote", "debug", "ci"]
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
AVATAR_PRESET_OPTIONS = ["lobster", "shrimp", "crab", "cat", "chick", "bunny", "slime", "penguin", "moose"]

I18N = {
    "zh": {
        "html_lang": "zh-CN",
        "title": "Vibelution 配置面板",
        "panel_title": "配置面板",
        "panel_subtitle": "Vibelution Workbench / Config",
        "save": "保存到 config.toml",
        "reload": "重新加载",
        "diagnostics": "配置诊断",
        "blocking": "阻断问题",
        "warnings": "风险提示",
        "actions": "建议动作",
        "raw_toml": "原始 TOML",
        "raw_toml_summary": "查看当前写盘内容",
        "overview": "运行概览",
        "effective_config": "实际生效配置",
        "profile_id": "模型档案",
        "provider_id": "服务标识",
        "api_base": "API 地址",
        "open_runtime": "运行时设置",
        "open_model_library": "模型库",
        "provider": "服务提供方",
        "model": "模型",
        "profile": "运行档案",
        "api_key_source": "密钥来源",
        "none": "无",
        "save_failed": "保存失败",
        "save_success": "配置已保存并通过校验",
        "save_success_title": "保存成功",
        "save_failed_title": "保存失败",
        "language": "语言",
        "lang_zh": "中文",
        "lang_en": "English",
        "add_llm": "复制档案",
        "test_llm": "测试连接",
        "switch_provider": "切换",
        "test_provider": "测试",
        "switch_success": "主模型已切换",
        "test_success_title": "连接正常",
        "test_failed_title": "连接失败",
        "prompt_profile_id": "模型档案标识",
        "prompt_provider_id": "模型服务标识",
        "prompt_model": "模型名称",
        "model_library": "通用模型库",
        "model_library_hint": "统一管理可选择的模型；各模型档案只引用这里的模型，再在自己的卡片里微调参数。",
        "preset_template": "预设模板",
        "preset_template_hint": "选择主流厂商模板会自动填入 provider、model 和默认参数；保存后仍写入普通配置结构。",
        "preset_custom": "手动配置",
        "add_model": "添加模型",
        "edit_model": "编辑",
        "save_model": "保存",
        "cancel": "取消",
        "delete_model": "删除模型",
        "model_id": "模型标识",
        "model_label": "显示名称",
        "apply_model": "应用模型",
        "model_api_key": "模型 API 密钥",
        "api_key_configured": "已配置",
        "api_key_missing": "未配置",
        "clear_api_key": "清除密钥",
        "api_key_hint": "保存后写入本机用户级环境变量；不会写入 config.toml。",
        "profile_group_unsupervised": "无监督进化",
        "profile_group_supervised": "监督进化",
    },
    "en": {
        "html_lang": "en",
        "title": "Vibelution Config Panel",
        "panel_title": "Config Panel",
        "panel_subtitle": "Vibelution Workbench / Config",
        "save": "Save to config.toml",
        "reload": "Reload",
        "diagnostics": "Configuration Diagnostics",
        "blocking": "Blocking Issues",
        "warnings": "Warnings",
        "actions": "Suggested Actions",
        "raw_toml": "Raw TOML",
        "raw_toml_summary": "View current persisted content",
        "overview": "Overview",
        "effective_config": "Effective Config",
        "profile_id": "Profile",
        "provider_id": "Provider ID",
        "api_base": "API Base",
        "open_runtime": "Runtime",
        "open_model_library": "Model Library",
        "provider": "provider",
        "model": "model",
        "profile": "profile",
        "api_key_source": "api_key source",
        "none": "None",
        "save_failed": "Save failed",
        "save_success": "Configuration saved and validated",
        "save_success_title": "Saved",
        "save_failed_title": "Save Failed",
        "language": "Language",
        "lang_zh": "中文",
        "lang_en": "English",
        "add_llm": "Clone Profile",
        "test_llm": "Test Connection",
        "switch_provider": "Switch",
        "test_provider": "Test",
        "switch_success": "Primary LLM switched",
        "test_success_title": "Connection OK",
        "test_failed_title": "Connection Failed",
        "prompt_profile_id": "profile_id",
        "prompt_provider_id": "provider_id",
        "prompt_model": "model",
        "model_library": "Model Library",
        "model_library_hint": "Manage selectable models once; model plans reference these models and keep their own tuning.",
        "preset_template": "Preset Template",
        "preset_template_hint": "Choose a provider preset to fill provider, model, and defaults; saving still writes the normal config shape.",
        "preset_custom": "Manual",
        "add_model": "Add Model",
        "edit_model": "Edit",
        "save_model": "Save",
        "cancel": "Cancel",
        "delete_model": "Delete Model",
        "model_id": "Model ID",
        "model_label": "Display Label",
        "apply_model": "Apply Model",
        "model_api_key": "Model API Key",
        "api_key_configured": "Configured",
        "api_key_missing": "Missing",
        "clear_api_key": "Clear Key",
        "api_key_hint": "Saved to the local user environment; never written to config.toml.",
        "profile_group_unsupervised": "Unsupervised Evolution",
        "profile_group_supervised": "Supervised Evolution",
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
        "agent.auto_restart_threshold": "达到阈值后触发热重启。",
        "context_compression.keep_recent_steps": "压缩后仍然保留的最近步骤数。",
        "context_compression.max_compressions_per_session": "单会话允许的最大压缩次数。",
        "tools.shell.allowed_shells": "允许使用的 shell 类型，直接影响跨平台行为。",
        "tools.shell.max_output_length": "终端输出截断上限，过小会影响诊断。",
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
        "agent.auto_restart_threshold": "Threshold that triggers hot restart.",
        "context_compression.keep_recent_steps": "How many recent steps survive compression.",
        "context_compression.max_compressions_per_session": "Compression cap per session.",
        "tools.shell.allowed_shells": "Allowed shell types. This directly affects cross-platform behavior.",
        "tools.shell.max_output_length": "Terminal output cap. Too small will hide diagnostics.",
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


def load_public_config(config_path: Path = CONFIG_PATH) -> dict:
    raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    return denormalize_config_dict(normalize_public_config_dict(raw))


def build_effective_config(public_config: dict) -> AppConfig:
    normalized = normalize_public_config_dict(public_config)
    config = AppConfig.model_validate(normalized)
    effective = apply_runtime_profile(config)
    assert_llm_compatibility(effective)
    return effective


def list_llm_profile_options(public_config: dict, lang: str = DEFAULT_LANG) -> list[dict[str, str]]:
    llm = public_config.get("llm", {})
    profiles = llm.get("profiles", {}) if isinstance(llm, dict) else {}
    options: list[dict[str, str]] = []
    if not isinstance(profiles, dict):
        return options
    for profile_id, profile in profiles.items():
        if not isinstance(profile, dict):
            continue
        provider_id = str(profile.get("provider_id", ""))
        model = str(profile.get("model", ""))
        options.append(
            {
                "profile_id": str(profile_id),
                "provider_id": provider_id,
                "model": model,
                "label": _display_profile_id(str(profile_id), lang),
            }
        )
    return options


def _model_library_id(provider_id: str, model: str) -> str:
    raw = f"{provider_id}-{model}".strip("-").lower()
    return "".join(char if char.isalnum() else "_" for char in raw).strip("_") or "model"


def _default_model_api_key_env(model_id: str) -> str:
    token = "".join(char if char.isalnum() else "_" for char in str(model_id or "").upper()).strip("_")
    return f"VIBELUTION_LLM_{token}_API_KEY" if token else "VIBELUTION_LLM_MODEL_API_KEY"


def _read_env_var(name: str) -> str:
    return os.environ.get(name, "")


def _broadcast_windows_environment_change(timeout_ms: int = 5000) -> None:
    try:
        import ctypes
    except ImportError:
        return
    HWND_BROADCAST = 0xFFFF
    WM_SETTINGCHANGE = 0x001A
    SMTO_ABORTIFHUNG = 0x0002
    result = ctypes.c_size_t()
    try:
        ctypes.windll.user32.SendMessageTimeoutW(
            HWND_BROADCAST,
            WM_SETTINGCHANGE,
            0,
            "Environment",
            SMTO_ABORTIFHUNG,
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
    name = (name or "").strip()
    if not name:
        raise ValueError("api_key_env is required")
    os.environ[name] = value
    if os.name != "nt":
        return
    _write_windows_user_env_var(name, value)


def _delete_user_env_var(name: str) -> None:
    name = (name or "").strip()
    if not name:
        return
    os.environ.pop(name, None)
    if os.name != "nt":
        return
    _write_windows_user_env_var(name, None)


def _coerce_model_library_detail(key: str, value):
    if value in ("", None):
        return None
    if key == "api_key_env":
        return str(value).strip()
    if key in {"transport", "contract", "reasoning_state_field"}:
        return str(value).strip()
    if key == "temperature":
        return float(value)
    if key in {"max_output_tokens", "timeout", "connect_timeout"}:
        return int(value)
    if key in {"streaming", "discovery_enabled", "strict_compatibility"}:
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}
    return str(value).strip()


def _model_library_details(item: dict) -> dict:
    details = {}
    for key in MODEL_LIBRARY_DETAIL_FIELDS:
        if key not in item:
            continue
        value = _coerce_model_library_detail(key, item.get(key))
        if value is not None:
            details[key] = value
    return details


def _model_library_entry(provider_id: str, model: str, label: str, details: dict | None = None) -> dict:
    entry = {
        "provider_id": provider_id,
        "model": model,
        "label": label or model,
    }
    if details:
        entry.update(_model_library_details(details))
    return entry


def list_llm_model_preset_options() -> list[dict[str, object]]:
    return [
        {
            "preset_id": preset_id,
            "label": str(preset["label"]),
            "provider_id": str(preset["provider_id"]),
            "model_id": str(preset["model_id"]),
            "provider": copy.deepcopy(preset["provider"]),
            "model": copy.deepcopy(preset["model"]),
        }
        for preset_id, preset in LLM_MODEL_PRESETS.items()
    ]


def apply_llm_model_preset(
    public_config: dict,
    preset_id: str,
    model_id: str = "",
    provider_id: str = "",
    model: str = "",
    label: str = "",
    details: dict | None = None,
    api_key_env: str = "",
) -> dict:
    preset_id = (preset_id or "").strip()
    if preset_id not in LLM_MODEL_PRESETS:
        raise ValueError(f"unknown LLM model preset: {preset_id}")

    preset = LLM_MODEL_PRESETS[preset_id]
    resolved_model_id = (model_id or str(preset["model_id"])).strip()
    resolved_provider_id = (provider_id or str(preset["provider_id"])).strip()
    model_defaults = copy.deepcopy(preset["model"])
    model_defaults.update(_model_library_details(details or {}))
    resolved_model = (model or str(model_defaults.get("model", ""))).strip()
    resolved_label = (label or str(model_defaults.get("label", "")) or resolved_model).strip()
    if not resolved_model_id:
        raise ValueError("model_id is required")
    if not resolved_provider_id:
        raise ValueError("provider_id is required")
    if not resolved_model:
        raise ValueError("model is required")

    updated = copy.deepcopy(public_config)
    llm = updated.setdefault("llm", {})
    providers = llm.setdefault("providers", {})
    if not isinstance(providers, dict):
        raise ValueError("llm.providers must be an object")
    provider_entry = providers.setdefault(resolved_provider_id, {})
    if not isinstance(provider_entry, dict):
        raise ValueError(f"llm.providers.{resolved_provider_id} must be an object")
    provider_entry.update(copy.deepcopy(preset["provider"]))
    provider_entry["provider_id"] = resolved_provider_id

    model_library = llm.setdefault("model_library", {})
    if not isinstance(model_library, dict):
        raise ValueError("llm.model_library must be an object")
    if resolved_model_id in model_library:
        raise ValueError(f"LLM model already exists: {resolved_model_id}")

    model_defaults["model"] = resolved_model
    model_defaults["label"] = resolved_label
    entry = _model_library_entry(resolved_provider_id, resolved_model, resolved_label, model_defaults)
    entry["api_key_env"] = (api_key_env or _default_model_api_key_env(resolved_model_id)).strip()
    model_library[resolved_model_id] = entry
    build_effective_config(updated)
    return updated


def list_llm_model_options(public_config: dict) -> list[dict[str, object]]:
    llm = public_config.get("llm", {})
    providers = llm.get("providers", {}) if isinstance(llm, dict) else {}
    profiles = llm.get("profiles", {}) if isinstance(llm, dict) else {}
    model_library = llm.get("model_library", {}) if isinstance(llm, dict) else {}
    options: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    if isinstance(model_library, dict):
        for model_id, item in model_library.items():
            if not isinstance(item, dict):
                continue
            provider_id = str(item.get("provider_id", "")).strip()
            model = str(item.get("model", "")).strip()
            if not provider_id or not model:
                continue
            label = str(item.get("label", "")).strip() or model
            options.append(
                {
                    "model_id": str(model_id),
                    "provider_id": provider_id,
                    "provider_kind": str(providers.get(provider_id, {}).get("kind", provider_id)) if isinstance(providers, dict) else provider_id,
                    "model": model,
                    "label": label,
                    "details": _model_library_details(item),
                    "api_key_env": str(item.get("api_key_env", "")).strip(),
                    "api_key_configured": bool(_read_env_var(str(item.get("api_key_env", "")).strip())),
                }
            )
            seen.add((provider_id, model))

    if isinstance(profiles, dict):
        for profile in profiles.values():
            if not isinstance(profile, dict):
                continue
            provider_id = str(profile.get("provider_id", "")).strip()
            model = str(profile.get("model", "")).strip()
            if not provider_id or not model or (provider_id, model) in seen:
                continue
            provider_kind = str(providers.get(provider_id, {}).get("kind", provider_id)) if isinstance(providers, dict) else provider_id
            options.append(
                {
                    "model_id": _model_library_id(provider_id, model),
                    "provider_id": provider_id,
                    "provider_kind": provider_kind,
                    "model": model,
                    "label": model,
                    "details": _model_library_details(profile),
                    "api_key_env": _default_model_api_key_env(_model_library_id(provider_id, model)),
                    "api_key_configured": False,
                }
            )
            seen.add((provider_id, model))
    return options


def add_llm_model(public_config: dict, model_id: str, provider_id: str, model: str, label: str = "", details: dict | None = None, api_key_env: str = "") -> dict:
    model_id = (model_id or "").strip()
    provider_id = (provider_id or "").strip()
    model = (model or "").strip()
    label = (label or "").strip()
    if not model_id:
        raise ValueError("model_id is required")
    if not provider_id:
        raise ValueError("provider_id is required")
    if not model:
        raise ValueError("model is required")

    updated = copy.deepcopy(public_config)
    llm = updated.setdefault("llm", {})
    providers = llm.setdefault("providers", {})
    if not isinstance(providers, dict) or provider_id not in providers:
        raise ValueError(f"unknown LLM provider: {provider_id}")
    model_library = llm.setdefault("model_library", {})
    if not isinstance(model_library, dict):
        raise ValueError("llm.model_library must be an object")
    if model_id in model_library:
        raise ValueError(f"LLM model already exists: {model_id}")
    entry = _model_library_entry(provider_id, model, label or model, details)
    entry["api_key_env"] = (api_key_env or entry.get("api_key_env") or _default_model_api_key_env(model_id)).strip()
    model_library[model_id] = entry
    build_effective_config(updated)
    return updated


def update_llm_model(public_config: dict, model_id: str, provider_id: str, model: str, label: str = "", details: dict | None = None, api_key_env: str = "") -> dict:
    model_id = (model_id or "").strip()
    provider_id = (provider_id or "").strip()
    model = (model or "").strip()
    label = (label or "").strip()
    if not model_id:
        raise ValueError("model_id is required")
    if not provider_id:
        raise ValueError("provider_id is required")
    if not model:
        raise ValueError("model is required")

    updated = copy.deepcopy(public_config)
    llm = updated.setdefault("llm", {})
    providers = llm.setdefault("providers", {})
    if not isinstance(providers, dict) or provider_id not in providers:
        raise ValueError(f"unknown LLM provider: {provider_id}")
    model_library = llm.setdefault("model_library", {})
    if not isinstance(model_library, dict):
        raise ValueError("llm.model_library must be an object")
    existing = model_library.get(model_id, {}) if isinstance(model_library.get(model_id, {}), dict) else {}
    entry = _model_library_entry(provider_id, model, label or model, details)
    entry["api_key_env"] = (api_key_env or entry.get("api_key_env") or existing.get("api_key_env") or _default_model_api_key_env(model_id)).strip()
    model_library[model_id] = entry
    build_effective_config(updated)
    return updated


def delete_llm_model(public_config: dict, model_id: str) -> dict:
    updated = copy.deepcopy(public_config)
    llm = updated.setdefault("llm", {})
    model_library = llm.get("model_library", {})
    if isinstance(model_library, dict):
        model_library.pop(model_id, None)
    else:
        llm["model_library"] = {}
    build_effective_config(updated)
    return updated


def set_llm_model_api_key(public_config: dict, model_id: str, api_key: str) -> str:
    llm = public_config.get("llm", {})
    model_library = llm.get("model_library", {}) if isinstance(llm, dict) else {}
    item = model_library.get(model_id, {}) if isinstance(model_library, dict) else {}
    if not isinstance(item, dict):
        raise ValueError(f"unknown LLM model: {model_id}")
    api_key_env = str(item.get("api_key_env") or _default_model_api_key_env(model_id)).strip()
    item["api_key_env"] = api_key_env
    _set_user_env_var(api_key_env, api_key)
    return api_key_env


def clear_llm_model_api_key(public_config: dict, model_id: str) -> str:
    llm = public_config.get("llm", {})
    model_library = llm.get("model_library", {}) if isinstance(llm, dict) else {}
    item = model_library.get(model_id, {}) if isinstance(model_library, dict) else {}
    if not isinstance(item, dict):
        raise ValueError(f"unknown LLM model: {model_id}")
    api_key_env = str(item.get("api_key_env") or _default_model_api_key_env(model_id)).strip()
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


def add_llm_profile(public_config: dict, profile_id: str, provider_id: str, model: str) -> dict:
    profile_id = (profile_id or "").strip()
    provider_id = (provider_id or "").strip()
    model = (model or "").strip()
    if not profile_id:
        raise ValueError("profile_id is required")
    if not provider_id:
        raise ValueError("provider_id is required")
    if not model:
        raise ValueError("model is required")

    updated = copy.deepcopy(public_config)
    llm = updated.setdefault("llm", {})
    providers = llm.setdefault("providers", {})
    profiles = llm.setdefault("profiles", {})
    if not isinstance(providers, dict) or provider_id not in providers:
        raise ValueError(f"unknown LLM provider: {provider_id}")
    if not isinstance(profiles, dict):
        raise ValueError("llm.profiles must be an object")
    if profile_id in profiles:
        raise ValueError(f"LLM profile already exists: {profile_id}")

    source_id = "primary" if "primary" in profiles else next(iter(profiles), "")
    source_profile = profiles.get(source_id, {}) if isinstance(profiles.get(source_id, {}), dict) else {}
    new_profile = copy.deepcopy(source_profile)
    new_profile["provider_id"] = provider_id
    new_profile["model"] = model
    profiles[profile_id] = new_profile
    build_effective_config(updated)
    return updated


def _probe_llm_http(provider, profile, api_key: str | None = None) -> dict:
    if provider.requires_api_key and not api_key:
        return {"ok": False, "message": f"missing API key for provider `{provider.provider_id}`"}
    if not provider.base_url:
        return {"ok": False, "message": f"missing base_url for provider `{provider.provider_id}`"}

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
        with urllib.request.urlopen(request, timeout=min(profile.connect_timeout, profile.timeout)) as response:
            status = getattr(response, "status", 200)
            if 200 <= status < 300:
                return {"ok": True, "message": f"connected to {profile.model}"}
            return {"ok": False, "message": f"HTTP {status}"}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "message": f"HTTP {exc.code}: {exc.reason}"}
    except Exception as exc:
        return {"ok": False, "message": str(exc)}


def test_llm_connection(public_config: dict, profile_id: str | None = None) -> dict:
    effective = build_effective_config(public_config)
    profile = effective.llm.get_profile(profile_id=profile_id) if profile_id else effective.llm.get_profile(role="primary")
    provider = effective.llm.get_provider(profile.provider_id)
    api_key = effective.get_api_key_for_profile(profile_id=profile.profile_id)
    try:
        result = _probe_llm_http(provider, profile, api_key)
    except TypeError:
        result = _probe_llm_http(provider, profile)
    return {
        **result,
        "profile_id": profile.profile_id,
        "provider_id": provider.provider_id,
        "model": profile.model,
        "api_key_source": effective.llm.get_api_key_source_label_for_profile(profile_id=profile.profile_id),
    }


def test_llm_connection_by_provider(public_config: dict, provider_id: str) -> dict:
    profile_id = _find_profile_id_for_provider(public_config, provider_id)
    return test_llm_connection(public_config, profile_id)


def preserve_secret_blanks(new_public: dict, old_public: dict) -> dict:
    result = copy.deepcopy(new_public)

    def walk(new_node, old_node):
        if isinstance(new_node, dict) and isinstance(old_node, dict):
            for key, value in new_node.items():
                if key not in old_node:
                    continue
                if key == "api_key" and value == "" and isinstance(old_node[key], str) and old_node[key]:
                    new_node[key] = old_node[key]
                else:
                    walk(value, old_node[key])
        elif isinstance(new_node, list) and isinstance(old_node, list):
            for idx, item in enumerate(new_node):
                if idx < len(old_node):
                    walk(item, old_node[idx])

    walk(result, old_public)
    return result


def save_public_config(public_config: dict, config_path: Path = CONFIG_PATH) -> None:
    cleaned_public_config = denormalize_config_dict(normalize_public_config_dict(public_config))
    config_path.with_suffix(config_path.suffix + ".bak").write_text(
        config_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    config_path.write_text(dumps_public_config(cleaned_public_config, HEADER_LINES), encoding="utf-8")


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
    selected_provider_id: str,
    selected_model: str,
    select_id: str,
    profile_id: str,
    lang: str,
    provider_filter: str | None = None,
) -> str:
    options = []
    for option in list_llm_model_options(public_config):
        option_provider_id = str(option["provider_id"])
        option_model = str(option["model"])
        option_model_id = str(option["model_id"])
        option_label = str(option["label"])
        option_provider_kind = str(option["provider_kind"])
        if provider_filter and option_provider_id != provider_filter:
            continue
        selected = " selected" if option_provider_id == selected_provider_id and option_model == selected_model else ""
        details_json = html.escape(json.dumps(option.get("details", {}), ensure_ascii=False), quote=True)
        options.append(
            f'<option value="{html.escape(option_model_id)}"{selected} '
            f'data-provider-id="{html.escape(option_provider_id)}" '
            f'data-model="{html.escape(option_model)}" '
            f'data-details="{details_json}">'
            f'{html.escape(option_label)} / {html.escape(_display_provider_kind(option_provider_kind, lang))}</option>'
        )
    disabled = " disabled" if not options else ""
    return (
        f'<select id="{html.escape(select_id)}" class="card-profile-select" '
        f'data-profile-id="{html.escape(profile_id)}"{disabled}>{"".join(options)}</select>'
    )


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
            path = f"{prefix}.{profile_id}"
            group_cards.append(
                _render_collapsible_card(
                    path,
                    _display_profile_id(profile_id, lang),
                    _render_group_fields(value, path, lang, public_config),
                    count=len(value),
                    actions_html=_card_actions(path, lang, public_config),
                    lang=lang,
                )
            )
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
    llm = public_config.get("llm", {})
    providers = llm.get("providers", {}) if isinstance(llm, dict) else {}
    add_profile_provider_options = "".join(
        f'<option value="{html.escape(str(provider_id))}">{html.escape(_display_provider_id(str(provider_id), lang))}</option>'
        for provider_id in providers
    )
    return (
        f'<div id="add-llm-profile-card" class="inline-add-card" hidden>'
        f'<div class="model-library-edit">'
        f'<label><span>{html.escape(t["prompt_profile_id"])}</span><input type="text" data-add-profile-field="profile_id"></label>'
        f'<label><span>{html.escape(t["prompt_provider_id"])}</span><select data-add-profile-field="provider_id">{add_profile_provider_options}</select></label>'
        f'<label><span>{html.escape(t["prompt_model"])}</span><input type="text" data-add-profile-field="model"></label>'
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
    selected_provider_id = str(profile.get("provider_id", "")) if isinstance(profile, dict) else ""
    selected_model = str(profile.get("model", "")) if isinstance(profile, dict) else ""
    t = I18N[lang]
    return (
        f'<div class="card-actions" data-profile-actions="{safe_profile}">'
        f'{_llm_model_select(public_config, selected_provider_id, selected_model, select_id, profile_id, lang)}'
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
        f'<div class="collapsible-card is-collapsed" data-collapsible-card="true">'
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
            if path == "llm.profiles":
                body.append(
                    _render_collapsible_card(
                        path,
                        localize_section_label(path, key, lang),
                        _render_llm_profile_groups(value, path, lang, public_config),
                        count=len(value),
                        actions_html=_card_actions(path, lang, public_config),
                        lang=lang,
                    )
                )
                continue
            nested_content = _render_group_fields(value, path, lang, public_config)
            section_title = localize_section_label(path, key, lang)
            if prefix == "llm.providers":
                section_title = _display_provider_id(key, lang)
            elif prefix == "llm.profiles":
                section_title = _display_profile_id(key, lang)
            body.append(
                _render_collapsible_card(
                    path,
                    section_title,
                    nested_content,
                    count=len(value),
                    actions_html=_card_actions(path, lang, public_config),
                    lang=lang,
                )
            )
        elif isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
            cards = [f'<div class="list-of-objects" data-path="{path}">']
            for idx, item in enumerate(value):
                item_path = f"{path}.{idx}"
                cards.append(
                    _render_collapsible_card(
                        item_path,
                        f"{localize_section_label(path, key, lang)}[{idx}]",
                        _render_group_fields(item, item_path, lang, public_config),
                        count=len(item),
                        lang=lang,
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


def _render_model_library_section(public_config: dict, lang: str) -> str:
    t = I18N[lang]
    options = list_llm_model_options(public_config)
    presets = list_llm_model_preset_options()
    llm = public_config.get("llm", {})
    providers = llm.get("providers", {}) if isinstance(llm, dict) else {}
    provider_options = []
    if isinstance(providers, dict):
        for provider_id in providers.keys():
            safe_provider_id = html.escape(str(provider_id))
            provider_options.append(f'<option value="{safe_provider_id}">{html.escape(_display_provider_id(str(provider_id), lang))}</option>')
    provider_options_html = "".join(provider_options)
    preset_options_html = (
        f'<option value="">{html.escape(t["preset_custom"])}</option>'
        + "".join(
            f'<option value="{html.escape(str(preset["preset_id"]))}">{html.escape(str(preset["label"]))}</option>'
            for preset in presets
        )
    )
    cards = []
    for option in options:
        provider_id = str(option["provider_id"])
        model = str(option["model"])
        label = str(option["label"])
        provider_kind = str(option["provider_kind"])
        model_id = str(option["model_id"])
        details = option.get("details", {}) if isinstance(option.get("details", {}), dict) else {}
        api_key_env = str(option.get("api_key_env", "") or details.get("api_key_env", "")).strip()
        api_key_configured = bool(option.get("api_key_configured"))
        api_key_status = t["api_key_configured"] if api_key_configured else t["api_key_missing"]
        selected_provider_options = provider_options_html.replace(
            f'value="{html.escape(provider_id)}"',
            f'value="{html.escape(provider_id)}" selected',
            1,
        )
        tool_mode = str(details.get("tool_calling_mode", "auto"))
        tool_mode_options = "".join(
            f'<option value="{html.escape(value)}"{" selected" if value == tool_mode else ""}>{html.escape(value)}</option>'
            for value in ("auto", "disabled", "required")
        )
        transport = str(details.get("transport", "chat_completions"))
        transport_options = "".join(
            f'<option value="{html.escape(value)}"{" selected" if value == transport else ""}>{html.escape(value)}</option>'
            for value in ("chat_completions", "responses")
        )
        contract = str(details.get("contract", "tool_chat"))
        contract_options = "".join(
            f'<option value="{html.escape(value)}"{" selected" if value == contract else ""}>{html.escape(value)}</option>'
            for value in ("basic_chat", "tool_chat", "reasoning_chat", "responses_agent")
        )
        strict_checked = " checked" if bool(details.get("strict_compatibility", True)) else ""
        streaming_checked = " checked" if bool(details.get("streaming", True)) else ""
        discovery_checked = " checked" if bool(details.get("discovery_enabled", True)) else ""
        detail_summary = " / ".join(
            item
            for item in (
                f"{transport}" if transport else "",
                f"{contract}" if contract else "",
                f'temp {details["temperature"]}' if "temperature" in details else "",
                f'{details["max_output_tokens"]} tokens' if "max_output_tokens" in details else "",
                f'{details["timeout"]}s' if "timeout" in details else "",
            )
            if item
        )
        cards.append(
            f'<div class="model-library-card" data-model-library-id="{html.escape(model_id)}" '
            f'data-provider-id="{html.escape(provider_id)}" '
            f'data-model="{html.escape(model)}" '
            f'data-label="{html.escape(label)}" '
            f'data-api-key-env="{html.escape(api_key_env)}">'
            f'<div class="model-library-view">'
            f'<div><strong>{html.escape(label)}</strong>'
            f'<span>{html.escape(_display_provider_kind(provider_kind, lang))} / {html.escape(_display_provider_id(provider_id, lang))}</span>'
            f'<span>{html.escape(t["model_api_key"])}: {html.escape(api_key_status)}'
            f'{f" ({html.escape(api_key_env)})" if api_key_env else ""}</span>'
            f'{f"<span>{html.escape(detail_summary)}</span>" if detail_summary else ""}</div>'
            f'<code>{html.escape(model)}</code>'
            f'<div class="model-library-actions">'
            f'<button type="button" class="card-action subtle" onclick="editLlmModel(this)">{html.escape(t["edit_model"])}</button>'
            f'<button type="button" class="card-action" onclick="deleteLlmModel(\'{html.escape(model_id)}\')">{html.escape(t["delete_model"])}</button>'
            f"</div>"
            f"</div>"
            f'<div class="model-library-edit" hidden>'
            f'<label><span>{html.escape(t["prompt_provider_id"])}</span>'
            f'<select data-edit-field="provider_id">{selected_provider_options}</select></label>'
            f'<label><span>{html.escape(t["prompt_model"])}</span>'
            f'<input type="text" data-edit-field="model" value="{html.escape(model)}"></label>'
            f'<label><span>{html.escape(t["model_label"])}</span>'
            f'<input type="text" data-edit-field="label" value="{html.escape(label)}"></label>'
            f'<label><span>api_key_env</span>'
            f'<input type="text" data-edit-field="api_key_env" value="{html.escape(api_key_env)}"></label>'
            f'<label><span>transport</span>'
            f'<select data-edit-field="transport">{transport_options}</select></label>'
            f'<label><span>contract</span>'
            f'<select data-edit-field="contract">{contract_options}</select></label>'
            f'<label><span>reasoning_state_field</span>'
            f'<input type="text" data-edit-field="reasoning_state_field" value="{html.escape(str(details.get("reasoning_state_field", "")))}"></label>'
            f'<label><span>{html.escape(t["model_api_key"])}</span>'
            f'<input type="password" data-edit-api-key autocomplete="off" placeholder="{html.escape(api_key_status)}"></label>'
            f'<label class="model-library-check"><input type="checkbox" data-clear-api-key> <span>{html.escape(t["clear_api_key"])}</span></label>'
            f'<span class="field-hint">{html.escape(t["api_key_hint"])}</span>'
            f'<label><span>temperature</span>'
            f'<input type="number" step="any" min="0" max="2" data-edit-field="temperature" value="{html.escape(str(details.get("temperature", "")))}"></label>'
            f'<label><span>max_output_tokens</span>'
            f'<input type="number" step="1" min="1" data-edit-field="max_output_tokens" value="{html.escape(str(details.get("max_output_tokens", "")))}"></label>'
            f'<label><span>timeout</span>'
            f'<input type="number" step="1" min="1" data-edit-field="timeout" value="{html.escape(str(details.get("timeout", "")))}"></label>'
            f'<label><span>connect_timeout</span>'
            f'<input type="number" step="1" min="1" data-edit-field="connect_timeout" value="{html.escape(str(details.get("connect_timeout", "")))}"></label>'
            f'<label><span>tool_calling_mode</span>'
            f'<select data-edit-field="tool_calling_mode">{tool_mode_options}</select></label>'
            f'<label class="model-library-check"><input type="checkbox" data-edit-field="strict_compatibility"{strict_checked}> <span>strict_compatibility</span></label>'
            f'<label class="model-library-check"><input type="checkbox" data-edit-field="streaming"{streaming_checked}> <span>streaming</span></label>'
            f'<label class="model-library-check"><input type="checkbox" data-edit-field="discovery_enabled"{discovery_checked}> <span>discovery_enabled</span></label>'
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
        f'<label><span>{html.escape(t["prompt_provider_id"])}</span><select data-add-model-field="provider_id">{provider_options_html}</select></label>'
        f'<label><span>{html.escape(t["prompt_model"])}</span><input type="text" data-add-model-field="model"></label>'
        f'<label><span>{html.escape(t["model_label"])}</span><input type="text" data-add-model-field="label"></label>'
        f'<label><span>api_key_env</span><input type="text" data-add-model-field="api_key_env"></label>'
        f'<label><span>transport</span><select data-add-model-field="transport"><option value="chat_completions">chat_completions</option><option value="responses">responses</option></select></label>'
        f'<label><span>contract</span><select data-add-model-field="contract"><option value="basic_chat">basic_chat</option><option value="tool_chat" selected>tool_chat</option><option value="reasoning_chat">reasoning_chat</option><option value="responses_agent">responses_agent</option></select></label>'
        f'<label><span>reasoning_state_field</span><input type="text" data-add-model-field="reasoning_state_field"></label>'
        f'<label><span>{html.escape(t["model_api_key"])}</span><input type="password" data-add-model-field="api_key" autocomplete="off"></label>'
        f'<label class="model-library-check"><input type="checkbox" data-add-model-field="strict_compatibility" checked> <span>strict_compatibility</span></label>'
        f'<span class="field-hint">{html.escape(t["preset_template_hint"])}</span>'
        f'<span class="field-hint">{html.escape(t["api_key_hint"])}</span>'
        f'<div class="model-library-actions">'
        f'<button type="button" class="card-action subtle" onclick="saveInlineLlmModel()">{html.escape(t["save_model"])}</button>'
        f'<button type="button" class="card-action" onclick="cancelInlineLlmModel()">{html.escape(t["cancel"])}</button>'
        f"</div></div></div>"
    )
    return (
        f'<section class="panel-section config-page" id="section-llm-model-library" data-config-page="llm-model-library">'
        f'<div class="model-library-head">'
        f'<div><span class="section-title">{html.escape(t["model_library"])}</span>'
        f'<span class="section-hint">{html.escape(t["model_library_hint"])}</span></div>'
        f'<button type="button" class="card-action subtle" onclick="addLlmModel()">{html.escape(t["add_model"])}</button>'
        f"</div>"
        f'<div class="model-library-grid">{add_card}{body}</div>'
        f"</section>"
    )


def _render_overview_section(diagnosis: dict, lang: str) -> str:
    t = I18N[lang]
    identity = diagnosis["identity"]
    sources = diagnosis["sources"]
    status = diagnosis["status"]
    runtime_profile_label = localize_label("runtime.profile", identity["runtime_profile"], lang)
    rows = [
        (t["profile"], runtime_profile_label),
        (t["profile_id"], _display_profile_id(identity.get("profile_id", ""), lang)),
        (t["provider_id"], _display_provider_id(identity.get("provider_id", ""), lang)),
        (t["provider"], _display_provider_kind(identity["provider"], lang)),
        (t["model"], identity["model_name"]),
        (t["api_base"], identity["api_base"]),
        (t["api_key_source"], sources["api_key"]),
        ("prompt sections", str(status["prompt_sections_count"])),
    ]
    rows_html = "".join(
        f'<div class="overview-item"><span>{html.escape(label)}</span><strong>{html.escape(str(value))}</strong></div>'
        for label, value in rows
    )
    return (
        f'<section class="panel-section config-page is-active" id="section-overview" data-config-page="overview">'
        f'<div class="section-header">'
        f'<span class="section-title-wrap"><span><span class="section-title">{html.escape(t["effective_config"])}</span>'
        f'<span class="section-hint">{html.escape(t["panel_subtitle"])}</span></span></span>'
        f'<span class="section-count">{html.escape(runtime_profile_label)}</span>'
        f'</div>'
        f'<div class="section-content">'
        f'<div class="overview-grid">{rows_html}</div>'
        f'<div class="overview-actions">'
        f'<button type="button" class="card-action" onclick="selectConfigPage(\'llm-model-library\')">{html.escape(t["open_model_library"])}</button>'
        f'<button type="button" class="card-action" onclick="selectConfigPage(\'runtime\')">{html.escape(t["open_runtime"])}</button>'
        f'</div>'
        f'</div>'
        f'</section>'
    )


def render_panel_html(public_config: dict, message: str = "", lang: str | None = None) -> str:
    lang = resolve_lang(lang or get_config_language(public_config))
    display_config = copy.deepcopy(public_config)
    display_config.setdefault("ui", {})
    if isinstance(display_config["ui"], dict):
        display_config["ui"]["language"] = lang
    generic_config = copy.deepcopy(display_config)
    if isinstance(generic_config.get("llm"), dict):
        generic_config["llm"].pop("model_library", None)
    display_json = json.dumps(display_config, ensure_ascii=False)
    preset_json = json.dumps({item["preset_id"]: item for item in list_llm_model_preset_options()}, ensure_ascii=False)
    t = I18N[lang]
    effective = build_effective_config(public_config)
    diagnosis = effective.diagnose_config()
    raw_toml = dumps_public_config(public_config, HEADER_LINES)
    blocking_count = len(diagnosis["blocking_issues"])
    warning_count = len(diagnosis["warnings"])
    action_count = len(diagnosis["suggested_actions"])
    sections_nav = (
        f'<a href="#section-overview" class="is-active" data-config-nav="overview" '
        f'onclick="selectConfigPage(\'overview\', event)">{html.escape(t["overview"])}</a>'
        f'<a href="#section-llm-model-library" data-config-nav="llm-model-library" '
        f'onclick="selectConfigPage(\'llm-model-library\', event)">{html.escape(t["model_library"])}</a>'
    ) + "".join(
        f'<a href="#section-{html.escape(name)}" data-config-nav="{html.escape(name)}" '
        f'onclick="selectConfigPage(\'{html.escape(name)}\', event)">{html.escape(localize_section_label(name, name, lang))}</a>'
        for name in generic_config.keys()
    )
    content = _render_overview_section(diagnosis, lang) + _render_model_library_section(display_config, lang) + "".join(
        _render_object(name, value, name, lang, display_config) for name, value in generic_config.items()
    )
    warnings_html = "".join(f"<li>{html.escape(item)}</li>" for item in diagnosis["warnings"]) or f"<li>{html.escape(t['none'])}</li>"
    blocking_html = "".join(f"<li>{html.escape(item)}</li>" for item in diagnosis["blocking_issues"]) or f"<li>{html.escape(t['none'])}</li>"
    actions_html = "".join(f"<li>{html.escape(item)}</li>" for item in diagnosis["suggested_actions"]) or f"<li>{html.escape(t['none'])}</li>"

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
    .summary-strip {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 16px; }}
    .summary-card {{ background: var(--panel-soft); border: 1px solid var(--line); border-radius: 8px; padding: 12px; min-height: 86px; display: flex; flex-direction: column; justify-content: space-between; }}
    .summary-card .label {{ font-size: 12px; color: var(--muted); text-transform: uppercase; }}
    .summary-card .value {{ font-size: 18px; font-weight: 700; }}
    .summary-card .meta {{ font-size: 12px; color: var(--muted); }}
    .summary-card.alert .value {{ color: var(--danger); }}
    .summary-card.warn .value {{ color: var(--warn); }}
    .summary-card.ok .value {{ color: var(--success); }}
    .overview-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; padding-top: 14px; }}
    .overview-item {{ display: grid; gap: 5px; min-width: 0; padding: 12px; border: 1px solid var(--line); border-radius: 6px; background: #fbfdff; }}
    .overview-item span {{ color: var(--muted); font-size: 12px; }}
    .overview-item strong {{ min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 14px; }}
    .overview-actions {{ display: flex; flex-wrap: wrap; gap: 8px; padding-top: 12px; }}
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
    @media (max-width: 1400px) {{ .section-grid, .field-group > .section-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} .summary-strip {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} }}
    @media (max-width: 1200px) {{ .layout {{ grid-template-columns: 1fr; }} .sidebar, .aside {{ position: static; height: auto; }} .section-grid, .field-group > .section-grid, .summary-strip, .diag-kv, .overview-grid, .model-library-grid, .model-library-view, .model-library-edit {{ grid-template-columns: 1fr; }} }}
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
      <form id="config-form" method="post" action="/save">
        <div class="toolbar">
          <button type="button" onclick="saveConfig()">{html.escape(t['save'])}</button>
          <button type="button" class="ghost" onclick="window.location.reload()">{html.escape(t['reload'])}</button>
          <label>
            <span style="font-size:13px;color:var(--muted);margin-right:6px;">{html.escape(t['language'])}</span>
            <select id="lang-switch" onchange="switchLang(this.value)">
              <option value="zh" {"selected" if lang == "zh" else ""}>{html.escape(t['lang_zh'])}</option>
              <option value="en" {"selected" if lang == "en" else ""}>{html.escape(t['lang_en'])}</option>
            </select>
          </label>
          <span class="message">{html.escape(message)}</span>
        </div>
        <div class="summary-strip">
          <div class="summary-card">
            <span class="label">{html.escape(t['provider'])}</span>
            <span class="value">{html.escape(diagnosis["identity"]["provider"])}</span>
            <span class="meta">{html.escape(diagnosis["identity"]["model_name"])}</span>
          </div>
          <div class="summary-card">
            <span class="label">{html.escape(t['profile'])}</span>
            <span class="value">{html.escape(diagnosis["identity"]["runtime_profile"])}</span>
            <span class="meta">{html.escape(t['api_key_source'])}: {html.escape(diagnosis["sources"]["api_key"])}</span>
          </div>
          <div class="summary-card alert">
            <span class="label">{html.escape(t['blocking'])}</span>
            <span class="value">{blocking_count}</span>
            <span class="meta">{html.escape(t['actions'])}: {action_count}</span>
          </div>
          <div class="summary-card warn">
            <span class="label">{html.escape(t['warnings'])}</span>
            <span class="value">{warning_count}</span>
            <span class="meta">{html.escape(t['raw_toml'])} / config.toml</span>
          </div>
        </div>
        <input type="hidden" name="payload" id="payload">
        {content}
      </form>
    </main>
    <aside class="aside">
      <div class="diag-block">
        <h2>{html.escape(t['diagnostics'])}</h2>
        <div class="diag-kv">
          <div class="kv-item">{html.escape(t['provider'])}: <strong>{html.escape(diagnosis["identity"]["provider"])}</strong></div>
          <div class="kv-item">{html.escape(t['model'])}: <strong>{html.escape(diagnosis["identity"]["model_name"])}</strong></div>
          <div class="kv-item">{html.escape(t['profile'])}: <strong>{html.escape(diagnosis["identity"]["runtime_profile"])}</strong></div>
          <div class="kv-item">{html.escape(t['api_key_source'])}: <strong>{html.escape(diagnosis["sources"]["api_key"])}</strong></div>
        </div>
      </div>
      <div class="diag-block">
        <h2 class="danger">{html.escape(t['blocking'])}</h2>
        <ul>{blocking_html}</ul>
      </div>
      <div class="diag-block">
        <h2 class="warn">{html.escape(t['warnings'])}</h2>
        <ul>{warnings_html}</ul>
      </div>
      <div class="diag-block">
        <h2>{html.escape(t['actions'])}</h2>
        <ul>{actions_html}</ul>
      </div>
      <div class="diag-block">
        <h2>{html.escape(t['raw_toml'])}</h2>
        <details>
          <summary>{html.escape(t['raw_toml_summary'])}</summary>
          <pre>{html.escape(raw_toml)}</pre>
        </details>
      </div>
    </aside>
  </div>
  <script>
    const LLM_MODEL_PRESETS = {preset_json};
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

    function collectPayload() {{
      const root = {display_json};
      document.querySelectorAll("[data-path]").forEach((el) => {{
        const path = el.dataset.path;
        let value;
        if (el.type === "checkbox") {{
          value = el.checked;
        }} else if (el.dataset.kind === "string-list") {{
          value = el.value.split(/\\r?\\n/).map((item) => item.trim()).filter(Boolean);
        }} else if (el.type === "number") {{
          value = el.step === "any" ? parseFloat(el.value || "0") : parseInt(el.value || "0", 10);
        }} else {{
          value = el.value;
        }}
        assignPath(root, path, value);
      }});
      return root;
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

    function setCardEditing(card, editing) {{
      if (!card) {{
        return;
      }}
      const content = card.querySelector(":scope > .card-content");
      const header = card.querySelector(":scope > .card-header-shell .card-header");
      if (content) {{
        content.hidden = false;
      }}
      if (header) {{
        header.setAttribute("aria-expanded", "true");
      }}
      card.classList.remove("is-collapsed");
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
      const lang = document.getElementById("lang-switch").value;
      const payload = collectPayload();
      if (!payload.ui) {{
        payload.ui = {{}};
      }}
      payload.ui.language = lang;
      const response = await postConfig(payload, lang);
      const result = await response.json();
      if (!result.ok) {{
        setToolbarMessage("{html.escape(t['save_failed'])}: " + result.message, true);
        showToast("error", "{html.escape(t['save_failed_title'])}", result.message);
        return;
      }}
      setToolbarMessage(result.message, false);
      showToast("success", "{html.escape(t['save_success_title'])}", result.message);
      let pageId = "";
      if (card && card.querySelector("[data-path]")) {{
        pageId = card.querySelector("[data-path]").dataset.path.split(".")[0];
      }}
      reloadConfigPage(lang, result.message, 500, pageId);
    }}

    async function postConfig(payload, lang) {{
      const form = document.getElementById("config-form");
      return fetch(form.action, {{
        method: "POST",
        headers: {{ "Content-Type": "application/x-www-form-urlencoded" }},
        body: new URLSearchParams({{ payload: JSON.stringify(payload), lang }})
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

    function activeConfigPageId(fallbackPageId = "overview") {{
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
        providerId: option.dataset.providerId,
        model: option.dataset.model,
        details: option.dataset.details ? JSON.parse(option.dataset.details) : {{}}
      }};
    }}

    async function applySelectedProfileModel(selectId) {{
      const selected = getSelectedModelOption(selectId);
      if (!selected || !selected.profileId || !selected.providerId || !selected.model) {{
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
      payload.llm.profiles[selected.profileId].provider_id = selected.providerId;
      payload.llm.profiles[selected.profileId].model = selected.model;
      Object.entries(selected.details || {{}}).forEach(([key, value]) => {{
        payload.llm.profiles[selected.profileId][key] = value;
      }});
      const response = await postConfig(payload, lang);
      const result = await response.json();
      if (!result.ok) {{
        setToolbarMessage(result.message, true);
        showToast("error", "{html.escape(t['save_failed_title'])}", result.message);
        return;
      }}
      setToolbarMessage(result.message, false);
      showToast("success", "{html.escape(t['save_success_title'])}", result.message);
      reloadConfigPage(lang, result.message, 500);
    }}

    async function testSelectedProfileModel(selectId) {{
      const selected = getSelectedModelOption(selectId);
      if (!selected || !selected.profileId || !selected.providerId || !selected.model) {{
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
      payload.llm.profiles[selected.profileId].provider_id = selected.providerId;
      payload.llm.profiles[selected.profileId].model = selected.model;
      Object.entries(selected.details || {{}}).forEach(([key, value]) => {{
        payload.llm.profiles[selected.profileId][key] = value;
      }});
      const response = await fetch("/test-llm", {{
        method: "POST",
        headers: {{ "Content-Type": "application/x-www-form-urlencoded" }},
        body: new URLSearchParams({{ payload: JSON.stringify(payload), profile_id: selected.profileId, lang }})
      }});
      const result = await response.json();
      const title = result.ok ? "{html.escape(t['test_success_title'])}" : "{html.escape(t['test_failed_title'])}";
      const detail = selected.profileId + " / " + (result.model || selected.model) + ": " + result.message;
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
      selectConfigPage(fromHash || "overview");
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
      const sourceProfile = profiles[sourceProfileId] || {{}};
      const selected = selectId ? getSelectedModelOption(selectId) : null;
      if (!card) {{
        return;
      }}
      const profileIdField = card.querySelector('[data-add-profile-field="profile_id"]');
      const providerField = card.querySelector('[data-add-profile-field="provider_id"]');
      const modelField = card.querySelector('[data-add-profile-field="model"]');
      if (profileIdField) {{
        profileIdField.value = nextClonedProfileId(sourceProfileId, profiles);
      }}
      if (providerField) {{
        providerField.value = (selected && selected.providerId) || sourceProfile.provider_id || "";
      }}
      if (modelField) {{
        modelField.value = (selected && selected.model) || sourceProfile.model || "";
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
      card.hidden = true;
    }}

    async function saveInlineLlmProfile() {{
      const card = document.getElementById("add-llm-profile-card");
      const lang = document.getElementById("lang-switch").value;
      const profileId = (card.querySelector('[data-add-profile-field="profile_id"]')?.value || "").trim();
      const providerId = (card.querySelector('[data-add-profile-field="provider_id"]')?.value || "").trim();
      const model = (card.querySelector('[data-add-profile-field="model"]')?.value || "").trim();
      if (!profileId || !providerId || !model) {{
        setToolbarMessage("{html.escape(t['save_failed'])}: profile_id, provider_id and model are required", true);
        return;
      }}
      const response = await fetch("/add-llm-profile", {{
        method: "POST",
        headers: {{ "Content-Type": "application/x-www-form-urlencoded" }},
        body: new URLSearchParams({{ profile_id: profileId, provider_id: providerId, model, lang }})
      }});
      const result = await response.json();
      if (!result.ok) {{
        setToolbarMessage(result.message, true);
        showToast("error", "{html.escape(t['save_failed_title'])}", result.message);
        return;
      }}
      setToolbarMessage(result.message, false);
      showToast("success", "{html.escape(t['save_success_title'])}", result.message);
      reloadConfigPage(lang, result.message, 500);
    }}

    function addLlmModel() {{
      const card = document.getElementById("add-llm-model-card");
      if (card) {{
        card.hidden = false;
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
        return;
      }}
      const modelDefaults = preset.model || {{}};
      setAddModelField("model_id", preset.model_id || "");
      setAddModelField("provider_id", preset.provider_id || "");
      setAddModelField("model", modelDefaults.model || "");
      setAddModelField("label", modelDefaults.label || preset.label || modelDefaults.model || "");
      setAddModelField("api_key_env", "");
      setAddModelField("transport", modelDefaults.transport || "chat_completions");
      setAddModelField("contract", modelDefaults.contract || "tool_chat");
      setAddModelField("reasoning_state_field", modelDefaults.reasoning_state_field || "");
      setAddModelField("strict_compatibility", modelDefaults.strict_compatibility !== false);
      setAddModelField("api_key", "");
    }}

    function cancelInlineLlmModel() {{
      const card = document.getElementById("add-llm-model-card");
      if (!card) {{
        return;
      }}
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
      card.hidden = true;
    }}

    async function saveInlineLlmModel() {{
      const card = document.getElementById("add-llm-model-card");
      const lang = document.getElementById("lang-switch").value;
      const presetId = (card.querySelector("[data-add-model-preset]")?.value || "").trim();
      const modelId = (card.querySelector('[data-add-model-field="model_id"]')?.value || "").trim();
      const providerId = (card.querySelector('[data-add-model-field="provider_id"]')?.value || "").trim();
      const model = (card.querySelector('[data-add-model-field="model"]')?.value || "").trim();
      const label = (card.querySelector('[data-add-model-field="label"]')?.value || model).trim() || model;
      const details = {{}};
      card.querySelectorAll("[data-add-model-field]").forEach((field) => {{
        const key = field.dataset.addModelField;
        if (["model_id", "provider_id", "model", "label", "api_key"].includes(key)) {{
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
      const apiKeyEnv = String(details.api_key_env || "").trim();
      delete details.api_key_env;
      const apiKey = (card.querySelector('[data-add-model-field="api_key"]')?.value || "").trim();
      if (!modelId || !providerId || !model) {{
        setToolbarMessage("{html.escape(t['save_failed'])}: model_id, provider_id and model are required", true);
        return;
      }}
      const response = await fetch("/add-llm-model", {{
        method: "POST",
        headers: {{ "Content-Type": "application/x-www-form-urlencoded" }},
        body: new URLSearchParams({{ preset_id: presetId, model_id: modelId, provider_id: providerId, model, label, details: JSON.stringify(details), api_key_env: apiKeyEnv, api_key: apiKey, lang }})
      }});
      const result = await response.json();
      if (!result.ok) {{
        setToolbarMessage(result.message, true);
        showToast("error", "{html.escape(t['save_failed_title'])}", result.message);
        return;
      }}
      setToolbarMessage(result.message, false);
      showToast("success", "{html.escape(t['save_success_title'])}", result.message);
      reloadConfigPage(lang, result.message, 500);
    }}

    function editLlmModel(button) {{
      const card = button.closest("[data-model-library-id]");
      if (!card) {{
        setToolbarMessage("Model card not found", true);
        return;
      }}
      const providerField = card.querySelector('[data-edit-field="provider_id"]');
      const modelField = card.querySelector('[data-edit-field="model"]');
      const labelField = card.querySelector('[data-edit-field="label"]');
      if (providerField) {{
        providerField.value = card.dataset.providerId || providerField.value;
      }}
      if (modelField) {{
        modelField.value = card.dataset.model || "";
      }}
      if (labelField) {{
        labelField.value = card.dataset.label || card.dataset.model || "";
      }}
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
      const providerId = (card.querySelector('[data-edit-field="provider_id"]')?.value || "").trim();
      const model = (card.querySelector('[data-edit-field="model"]')?.value || "").trim();
      const label = (card.querySelector('[data-edit-field="label"]')?.value || model).trim() || model;
      const apiKey = (card.querySelector("[data-edit-api-key]")?.value || "").trim();
      const clearApiKey = card.querySelector("[data-clear-api-key]")?.checked ? "1" : "";
      const details = {{}};
      card.querySelectorAll("[data-edit-field]").forEach((field) => {{
        const key = field.dataset.editField;
        if (["provider_id", "model", "label"].includes(key)) {{
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
      if (!providerId || !model) {{
        setToolbarMessage("{html.escape(t['save_failed'])}: provider_id and model are required", true);
        return;
      }}
      const response = await fetch("/update-llm-model", {{
        method: "POST",
        headers: {{ "Content-Type": "application/x-www-form-urlencoded" }},
        body: new URLSearchParams({{ model_id: modelId, provider_id: providerId, model, label, details: JSON.stringify(details), api_key: apiKey, clear_api_key: clearApiKey, lang }})
      }});
      const result = await response.json();
      if (!result.ok) {{
        setToolbarMessage(result.message, true);
        showToast("error", "{html.escape(t['save_failed_title'])}", result.message);
        return;
      }}
      setToolbarMessage(result.message, false);
      showToast("success", "{html.escape(t['save_success_title'])}", result.message);
      reloadConfigPage(lang, result.message, 500, "llm-model-library");
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
      const response = await fetch("/delete-llm-model", {{
        method: "POST",
        headers: {{ "Content-Type": "application/x-www-form-urlencoded" }},
        body: new URLSearchParams({{ model_id: modelId, lang }})
      }});
      const result = await response.json();
      if (!result.ok) {{
        setToolbarMessage(result.message, true);
        showToast("error", "{html.escape(t['save_failed_title'])}", result.message);
        return;
      }}
      setToolbarMessage(result.message, false);
      showToast("success", "{html.escape(t['save_success_title'])}", result.message);
      reloadConfigPage(lang, result.message, 500);
    }}

    async function testProfileLlm(profileId) {{
      const lang = document.getElementById("lang-switch").value;
      const payload = collectPayload();
      const response = await fetch("/test-llm", {{
        method: "POST",
        headers: {{ "Content-Type": "application/x-www-form-urlencoded" }},
        body: new URLSearchParams({{ payload: JSON.stringify(payload), profile_id: profileId, lang }})
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
        body: new URLSearchParams({{ payload: JSON.stringify(payload), profile_id: select.value, lang }})
      }});
      const result = await response.json();
      const title = result.ok ? "{html.escape(t['test_success_title'])}" : "{html.escape(t['test_failed_title'])}";
      const detail = (result.profile_id || select.value) + " / " + (result.model || "") + ": " + result.message;
      setToolbarMessage(detail, !result.ok);
      showToast(result.ok ? "success" : "error", title, detail);
    }}

    function switchLang(lang) {{
      reloadConfigPage(lang);
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
        self._send_html(render_panel_html(public_config, message, effective_lang))

    def do_POST(self) -> None:
        if self.path not in {
            "/save",
            "/add-llm-profile",
            "/add-llm-model",
            "/update-llm-model",
            "/delete-llm-model",
            "/test-llm",
        }:
            self._send_json({"ok": False, "message": "Not found"}, status=404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        form = parse_qs(raw)
        lang = resolve_lang(form.get("lang", [DEFAULT_LANG])[0])
        try:
            if self.path == "/add-llm-profile":
                old_public = load_public_config()
                updated = add_llm_profile(
                    old_public,
                    form.get("profile_id", [""])[0],
                    form.get("provider_id", [""])[0],
                    form.get("model", [""])[0],
                )
                save_public_config(updated)
                self._send_json({"ok": True, "message": I18N[lang]["save_success"]})
                return

            if self.path == "/add-llm-model":
                old_public = load_public_config()
                preset_id = form.get("preset_id", [""])[0]
                details = json.loads(form.get("details", ["{}"])[0] or "{}")
                if preset_id:
                    updated = apply_llm_model_preset(
                        old_public,
                        preset_id,
                        form.get("model_id", [""])[0],
                        form.get("provider_id", [""])[0],
                        form.get("model", [""])[0],
                        form.get("label", [""])[0],
                        details,
                        form.get("api_key_env", [""])[0],
                    )
                else:
                    updated = add_llm_model(
                        old_public,
                        form.get("model_id", [""])[0],
                        form.get("provider_id", [""])[0],
                        form.get("model", [""])[0],
                        form.get("label", [""])[0],
                        details,
                        api_key_env=form.get("api_key_env", [""])[0],
                    )
                if form.get("api_key", [""])[0]:
                    set_llm_model_api_key(updated, form.get("model_id", [""])[0], form.get("api_key", [""])[0])
                save_public_config(updated)
                self._send_json({"ok": True, "message": I18N[lang]["save_success"]})
                return

            if self.path == "/update-llm-model":
                old_public = load_public_config()
                details = json.loads(form.get("details", ["{}"])[0] or "{}")
                updated = update_llm_model(
                    old_public,
                    form.get("model_id", [""])[0],
                    form.get("provider_id", [""])[0],
                    form.get("model", [""])[0],
                    form.get("label", [""])[0],
                    details,
                )
                if form.get("clear_api_key", [""])[0] in {"1", "true", "yes", "on"}:
                    clear_llm_model_api_key(updated, form.get("model_id", [""])[0])
                elif form.get("api_key", [""])[0]:
                    set_llm_model_api_key(updated, form.get("model_id", [""])[0], form.get("api_key", [""])[0])
                save_public_config(updated)
                self._send_json({"ok": True, "message": I18N[lang]["save_success"]})
                return

            if self.path == "/delete-llm-model":
                old_public = load_public_config()
                updated = delete_llm_model(old_public, form.get("model_id", [""])[0])
                save_public_config(updated)
                self._send_json({"ok": True, "message": I18N[lang]["save_success"]})
                return

            if self.path == "/test-llm":
                payload = form.get("payload", [""])[0]
                profile_id = form.get("profile_id", [""])[0] or None
                submitted = json.loads(payload) if payload else load_public_config()
                result = test_llm_connection(submitted, profile_id)
                self._send_json(result, status=200 if result.get("ok") else 400)
                return

            payload = form.get("payload", [""])[0]
            old_public = load_public_config()
            submitted = json.loads(payload)
            submitted.setdefault("ui", {})
            if isinstance(submitted["ui"], dict):
                submitted["ui"]["language"] = lang
            merged = preserve_secret_blanks(submitted, old_public)
            build_effective_config(merged)
            save_public_config(merged)
            self._send_json({"ok": True, "message": I18N[lang]["save_success"]})
        except Exception as exc:
            self._send_json({"ok": False, "message": str(exc)}, status=400)

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
