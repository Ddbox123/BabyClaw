"""
配置加载与单例管理

负责从 TOML 配置文件、环境变量加载配置，并对外提供统一的单例访问接口。
支持配置热更新和环境变量覆盖。
"""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Optional, Dict, Any
from .models import (
    AppConfig,
    LLMConfig,
    AgentConfig,
    WebChatConfig,
    ContextCompressionConfig,
    ToolConfig,
    LogConfig,
NetworkConfig,
    ParserConfig,
    EvolutionConfig,
    MemoryConfig,
    StrategyConfig,
    UIConfig,
    DebugConfig,
    SecurityConfig,    # 宠物系统配置
    PetConfig,
    GeneConfig,
    HeartConfig,
    DreamConfig,
    PersonalityConfig,
    HungerConfig,
    DiaryConfig,
    SocialConfig,
    HealthConfig,
    SkinConfig,
    SoundConfig,
    PromptConfig,
get_provider_api_key_env,)
from .providers import (
    MODEL_PRESETS,
    get_model_preset,
    resolve_model_alias,
    list_models,
    show_model_info,
)

# TOML 库兼容处理
try:
    import tomllib
except ImportError:
    try:
        import toml as tomllib
    except ImportError:
        tomllib = None


# ============================================================================
# 配置文件路径
# ============================================================================

DEFAULT_CONFIG_PATH = "config.toml"
INLINE_PROVIDER_FIELDS = (
    "kind",
    "api_key",
    "api_key_env",
    "base_url",
    "extra_headers",
    "compat_mode",
    "requires_api_key",
    "context_window",
)
PUBLIC_INLINE_PROVIDER_FIELDS = tuple(field for field in INLINE_PROVIDER_FIELDS if field != "api_key")
PROFILE_REFERENCE_OVERRIDE_FIELDS = (
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
UNCONFIGURED_MODEL_REF = "__unconfigured__"


def _materialize_role_bound_profiles(llm_section: Dict[str, Any]) -> None:
    # Legacy public configs may still declare llm.role_bindings; fold them into
    # same-named concrete profiles so the runtime stays strictly two-layered.
    bindings = llm_section.pop("role_bindings", None)
    profiles = llm_section.get("profiles")
    if not isinstance(bindings, dict) or not isinstance(profiles, dict):
        return

    for role, source_profile_id in bindings.items():
        role_id = str(role or "").strip()
        source_id = str(source_profile_id or "").strip()
        if not role_id or not source_id:
            continue
        source_profile = profiles.get(source_id)
        if not isinstance(source_profile, dict):
            continue
        if role_id == source_id and role_id in profiles:
            continue
        migrated = copy.deepcopy(source_profile)
        migrated["profile_id"] = role_id
        profiles[role_id] = migrated


def _inline_provider_payload(provider: Any) -> Dict[str, Any]:
    if not isinstance(provider, dict):
        return {}
    payload: Dict[str, Any] = {}
    for key in INLINE_PROVIDER_FIELDS:
        if key in provider:
            payload[key] = copy.deepcopy(provider[key])
    return payload


def _public_inline_provider_payload(provider: Any) -> Dict[str, Any]:
    if not isinstance(provider, dict):
        return {}
    payload: Dict[str, Any] = {}
    for key in PUBLIC_INLINE_PROVIDER_FIELDS:
        if key in provider:
            payload[key] = copy.deepcopy(provider[key])
    return payload


def _profile_reference_override_payload(overrides: Any) -> Dict[str, Any]:
    if not isinstance(overrides, dict):
        return {}
    payload: Dict[str, Any] = {}
    for key in PROFILE_REFERENCE_OVERRIDE_FIELDS:
        if key in overrides:
            payload[key] = copy.deepcopy(overrides[key])
    return payload


def _unconfigured_profile_stub() -> Dict[str, Any]:
    return {
        "provider": {
            "kind": "local",
            "api_key_env": "",
            "base_url": "http://localhost:11434/v1",
            "compat_mode": "openai",
            "requires_api_key": False,
            "context_window": 65536,
        },
        "model": "",
        "transport": "chat_completions",
        "contract": "basic_chat",
        "strict_compatibility": False,
        "temperature": 0.0,
        "max_output_tokens": 1,
        "timeout": 5,
        "connect_timeout": 5,
        "streaming": False,
        "tool_calling_mode": "disabled",
        "discovery_enabled": False,
    }


def _materialize_model_ref_profiles(llm_section: Dict[str, Any]) -> None:
    model_library = llm_section.get("model_library")
    profiles = llm_section.get("profiles")
    if not isinstance(model_library, dict) or not isinstance(profiles, dict):
        return

    for profile in profiles.values():
        if not isinstance(profile, dict):
            continue
        if "model_ref" not in profile and "overrides" not in profile:
            continue

        model_ref = str(profile.get("model_ref", "") or "").strip()
        overrides = _profile_reference_override_payload(profile.get("overrides"))
        materialized: Dict[str, Any] = {}

        if model_ref and model_ref != UNCONFIGURED_MODEL_REF:
            item = model_library.get(model_ref, {})
            if isinstance(item, dict):
                provider = _inline_provider_payload(item.get("provider"))
                if provider:
                    materialized["provider"] = provider
                model_name = str(item.get("model", "") or "").strip()
                if model_name:
                    materialized["model"] = model_name
                for key in PROFILE_REFERENCE_OVERRIDE_FIELDS:
                    if key in item:
                        materialized[key] = copy.deepcopy(item[key])

        if not materialized:
            materialized = _unconfigured_profile_stub()

        profile.pop("provider", None)
        profile.pop("provider_id", None)
        profile.pop("model_ref", None)
        profile.pop("overrides", None)
        profile.update(materialized)
        profile.update(overrides)


def _resolve_owner_provider_payload(
    owner: Dict[str, Any],
    legacy_providers: Dict[str, Any] | None,
) -> Dict[str, Any]:
    inline_provider = _inline_provider_payload(owner.get("provider"))
    if inline_provider:
        return inline_provider
    provider_id = str(owner.get("provider_id", "")).strip()
    if provider_id and isinstance(legacy_providers, dict):
        return _inline_provider_payload(legacy_providers.get(provider_id))
    return {}


def _runtime_provider_id(owner_kind: str, owner_id: str) -> str:
    return f"inline_{owner_kind}_{owner_id}"


def _materialize_inline_llm_providers(llm_section: Dict[str, Any]) -> None:
    legacy_providers = llm_section.get("providers")
    runtime_providers: Dict[str, Any] = {}

    model_library = llm_section.get("model_library")
    if isinstance(model_library, dict):
        for model_id, item in model_library.items():
            if not isinstance(item, dict):
                continue
            provider_payload = _resolve_owner_provider_payload(item, legacy_providers)
            item.pop("provider", None)
            item.pop("provider_id", None)
            if not provider_payload:
                continue
            runtime_id = _runtime_provider_id("model", str(model_id))
            provider_payload["provider_id"] = runtime_id
            runtime_providers[runtime_id] = provider_payload
            item["provider_id"] = runtime_id

    profiles = llm_section.get("profiles")
    if isinstance(profiles, dict):
        for profile_id, profile in profiles.items():
            if not isinstance(profile, dict):
                continue
            provider_payload = _resolve_owner_provider_payload(profile, legacy_providers)
            profile.pop("provider", None)
            profile.pop("provider_id", None)
            if not provider_payload:
                continue
            runtime_id = _runtime_provider_id("profile", str(profile_id))
            provider_payload["provider_id"] = runtime_id
            runtime_providers[runtime_id] = provider_payload
            profile["provider_id"] = runtime_id

    if runtime_providers or "providers" in llm_section:
        llm_section["providers"] = runtime_providers


def normalize_public_config_dict(config: Dict[str, Any]) -> Dict[str, Any]:
    """将公开 TOML 结构转换为运行时模型结构。"""
    result = copy.deepcopy(config)

    if "llm" in result and isinstance(result["llm"], dict):
        llm_section = result["llm"]
        legacy_llm_keys = {
            "provider",
            "model_name",
            "api_key",
            "api_base",
            "temperature",
            "max_tokens",
            "api_timeout",
            "connect_timeout",
            "local",
        }
        found_legacy = sorted(key for key in legacy_llm_keys if key in llm_section)
        if found_legacy:
            raise ValueError(
                "Legacy [llm] config keys are no longer supported: "
                + ", ".join(found_legacy)
                + ". Use [llm.profiles.<id>.provider] / [llm.model_library.<id>.provider] / [llm.discovery]."
            )
        # Accept role_bindings only as an input compatibility shim; it is
        # normalized away before the config reaches the runtime/UI layers.
        supported_llm_keys = {"providers", "profiles", "role_bindings", "discovery", "model_library"}
        unknown_llm_keys = sorted(key for key in llm_section if key not in supported_llm_keys)
        if unknown_llm_keys:
            raise ValueError(
                "Unsupported [llm] config keys: "
                + ", ".join(unknown_llm_keys)
                + ". Use [llm.profiles.<id>] / [llm.model_library.<id>] / [llm.discovery]."
            )
        _materialize_role_bound_profiles(llm_section)
        _materialize_model_ref_profiles(llm_section)
        _materialize_inline_llm_providers(llm_section)

    if "pet" in result and isinstance(result["pet"], dict):
        pet_section = result["pet"]
        pet_subsections = (
            "gene",
            "heart",
            "dream",
            "personality",
            "hunger",
            "diary",
            "social",
            "health",
            "skin",
            "sound",
        )
        for sub_key in pet_subsections:
            if sub_key in pet_section:
                result[f"pet_{sub_key}"] = pet_section.pop(sub_key)

    return result


def denormalize_config_dict(config: Dict[str, Any]) -> Dict[str, Any]:
    """将运行时模型结构转换为公开 TOML 结构。"""
    result = copy.deepcopy(config)
    if "llm" in result and isinstance(result["llm"], dict):
        llm_section = result["llm"]
        for legacy_key in (
            "provider",
            "model_name",
            "api_key",
            "api_base",
            "temperature",
            "max_tokens",
            "api_timeout",
            "connect_timeout",
        ):
            llm_section.pop(legacy_key, None)

        runtime_providers = llm_section.get("providers", {})
        profiles = llm_section.get("profiles")
        if isinstance(profiles, dict):
            for profile in profiles.values():
                if not isinstance(profile, dict):
                    continue
                provider_id = str(profile.pop("provider_id", "")).strip()
                provider_payload = _public_inline_provider_payload(
                    runtime_providers.get(provider_id, {}) if isinstance(runtime_providers, dict) else {}
                )
                if provider_payload:
                    profile["provider"] = provider_payload

        model_library = llm_section.get("model_library")
        if isinstance(model_library, dict):
            for item in model_library.values():
                if not isinstance(item, dict):
                    continue
                provider_id = str(item.pop("provider_id", "")).strip()
                provider_payload = _public_inline_provider_payload(
                    runtime_providers.get(provider_id, {}) if isinstance(runtime_providers, dict) else {}
                )
                if provider_payload:
                    item["provider"] = provider_payload

        llm_section.pop("providers", None)

    pet_section = result.setdefault("pet", {})
    for sub_key in (
        "gene",
        "heart",
        "dream",
        "personality",
        "hunger",
        "diary",
        "social",
        "health",
        "skin",
        "sound",
    ):
        runtime_key = f"pet_{sub_key}"
        if runtime_key in result:
            pet_section[sub_key] = result.pop(runtime_key)

    return result


# ============================================================================
# 全局单例
# ============================================================================

_settings: Optional[AppConfig] = None
_config_path: Optional[str] = None


# ============================================================================
# 配置加载器
# ============================================================================

class ConfigLoader:
    """
    配置加载器

    负责从 TOML 文件、环境变量加载配置到 Pydantic 模型。
    配置优先级：命令行参数(kwargs) > 环境变量 > TOML > 默认值
    """

    def __init__(self, config_path: Optional[str] = None) -> None:
        """
        初始化加载器

        Args:
            config_path: 配置文件路径，为 None 时使用默认路径
        """
        self.config_path = config_path

    def _find_config_file(self) -> Optional[Path]:
        """
        查找配置文件

        查找顺序：
        1. 指定的 config_path
        2. 项目根目录的 config.toml
        3. 当前目录的 config.toml

        Returns:
            配置文件路径，不存在返回 None
        """
        # 1. 指定的路径
        if self.config_path:
            path = Path(self.config_path)
            if path.exists():
                return path.resolve()

        # 2. 项目根目录
        project_root = Path(__file__).parent.parent
        default_path = project_root / DEFAULT_CONFIG_PATH
        if default_path.exists():
            return default_path.resolve()

        # 3. 当前目录
        cwd_path = Path.cwd() / DEFAULT_CONFIG_PATH
        if cwd_path.exists():
            return cwd_path.resolve()

        return None

    def _load_from_toml(self) -> Dict[str, Any]:
        """
        从 TOML 文件加载配置

        Returns:
            配置字典
        """
        config_file = self._find_config_file()
        if not config_file:
            return {}

        if tomllib is None:
            print("警告: 需要安装 toml 库来读取配置文件 (pip install toml)")
            return {}

        try:
            with open(config_file, 'rb') as f:
                config = tomllib.load(f)
            # 转换 TOML 嵌套键为 Pydantic 字段格式
            return self._normalize_toml_keys(config)
        except Exception as e:
            print(f"警告: 读取配置文件失败: {e}")
            return {}

    def _normalize_toml_keys(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        将公开 TOML 结构转换为运行时模型结构。

        新版公开配置以 `llm.profiles.<id>.provider` 与
        `llm.model_library.<id>.provider` 为主入口，
        旧版 `llm.providers.*` 会在加载时兼容迁移。

        Args:
            config: TOML 解析后的配置字典

        Returns:
            转换后的配置字典
        """
        return normalize_public_config_dict(config)

    def _load_from_env(
        self,
        prefix: str = "AGENT_",
        base_provider: str = "",
    ) -> Dict[str, Any]:
        """
        从环境变量加载配置

        支持的环境变量格式：
        - AGENT_LLM__PROFILES__PRIMARY__MODEL -> llm.profiles.primary.model
        - AGENT_LLM__PROVIDERS__REMOTE_MAIN__BASE_URL -> llm.providers.remote_main.base_url
        - AGENT_AGENT_NAME -> agent.name
        - AGENT_LOG_LEVEL -> log.level
        - AGENT_TOOLS_SHELL_DEFAULT_TIMEOUT -> tools.shell.default_timeout

        Args:
            prefix: 环境变量前缀

        Returns:
            配置字典
        """
        config: Dict[str, Any] = {}
        touched = False

        deprecated_llm_env_vars = {
            f"{prefix}LLM_PROVIDER",
            f"{prefix}LLM_MODEL_NAME",
            f"{prefix}LLM_API_KEY",
            f"{prefix}LLM_API_BASE",
            f"{prefix}LLM_TEMPERATURE",
            f"{prefix}LLM_MAX_TOKENS",
            f"{prefix}LLM_API_TIMEOUT",
            f"{prefix}LLM_CONNECT_TIMEOUT",
            f"{prefix}LLM_DISCOVERY_ENABLED",
            f"{prefix}LLM_DISCOVERY_TIMEOUT",
            f"{prefix}LLM_DISCOVERY_FALLBACK_MAX_TOKENS",
            f"{prefix}LLM_DISCOVERY_FALLBACK_MAX_TOKEN_LIMIT",
            f"{prefix}LLM_DISCOVERY_AUTO_ADJUST",
            f"{prefix}LLM_DISCOVERY_OUTPUT_RESERVE_RATIO",
            f"{prefix}LLM_LOCAL_URL",
            f"{prefix}LLM_LOCAL_MODEL",
            f"{prefix}LLM_LOCAL_REQUIRE_API_KEY",
            f"{prefix}LLM_LOCAL_API_KEY",
            f"{prefix}LLM_LOCAL_STREAMING",
            f"{prefix}LLM_LOCAL_CONTEXT_WINDOW",
            f"{prefix}LLM_LOCAL_AUTO_DETECT_MODEL",
            f"{prefix}LLM_LOCAL_MODEL_REFRESH_INTERVAL",
            f"{prefix}LLM_LOCAL_MAX_RETRIES",
            f"{prefix}LLM_LOCAL_RETRY_DELAY",
        }
        active_deprecated = sorted(name for name in deprecated_llm_env_vars if os.environ.get(name) is not None)
        if active_deprecated:
            raise ValueError(
                "Legacy LLM environment variables are no longer supported: "
                + ", ".join(active_deprecated)
                + ". Use double-underscore paths such as "
                f"{prefix}LLM__PROFILES__PRIMARY__MODEL."
            )

        env_mappings = {
            # === Runtime 配置 ===
            f"{prefix}RUNTIME_PROFILE": "runtime.profile",
            f"{prefix}RUNTIME_PREFLIGHT_DOCTOR": "runtime.preflight_doctor",
            f"{prefix}RUNTIME_REQUIRE_VENV": "runtime.require_venv",

            # === Agent 配置 ===
            f"{prefix}AGENT_NAME": "agent.name",
            f"{prefix}AGENT_WORKSPACE": "agent.workspace",
            f"{prefix}AGENT_AWAKE_INTERVAL": "agent.awake_interval",
            f"{prefix}AGENT_MAX_ITERATIONS": "agent.max_iterations",
            f"{prefix}AGENT_MAX_RUNTIME": "agent.max_runtime",
            f"{prefix}AGENT_AUTO_BACKUP": "agent.auto_backup",
            f"{prefix}AGENT_BACKUP_INTERVAL": "agent.backup_interval",
            f"{prefix}AGENT_AUTO_RESTART_THRESHOLD": "agent.auto_restart_threshold",
            f"{prefix}AGENT_EXPLORATION_MODE": "agent.exploration_mode",
            f"{prefix}AGENT_DEFAULT_MODE": "agent.default_mode",
            f"{prefix}AGENT_MODES_CHAT_ENABLED": "agent.modes.chat_enabled",
            f"{prefix}AGENT_MODES_SELF_EVOLUTION_ENABLED": "agent.modes.self_evolution_enabled",
            f"{prefix}AGENT_MODES_SUPERVISED_EVOLUTION_ENABLED": "agent.modes.supervised_evolution_enabled",
            f"{prefix}AGENT_MODES_DEFAULT_SHELL_MODE": "agent.modes.default_shell_mode",
            f"{prefix}AGENT_MODES_DEFAULT_HEADLESS_MODE": "agent.modes.default_headless_mode",
            f"{prefix}AGENT_MODES_EXPLICIT_EVOLUTION_REQUEST_BEHAVIOR": "agent.modes.explicit_evolution_request_behavior",

            # === Web Chat 配置 ===
            f"{prefix}WEB_CHAT_MAX_CONTINUATION_TURNS": "web_chat.max_continuation_turns",

            # === 上下文压缩配置 ===
            f"{prefix}COMPRESSION_ENABLED": "context_compression.enabled",
            f"{prefix}COMPRESSION_MAX_TOKEN_LIMIT": "context_compression.max_token_limit",
            f"{prefix}COMPRESSION_KEEP_RECENT_STEPS": "context_compression.keep_recent_steps",
            f"{prefix}COMPRESSION_SUMMARY_MAX_CHARS": "context_compression.summary_max_chars",
            f"{prefix}COMPRESSION_MODEL": "context_compression.compression_model",
            f"{prefix}COMPRESSION_TEMPERATURE": "context_compression.compression_temperature",
            f"{prefix}COMPRESSION_MAX_COMPRESSIONS": "context_compression.max_compressions_per_session",
            f"{prefix}COMPRESSION_EFFECTIVENESS_THRESHOLD": "context_compression.effectiveness_threshold",

            # === 压缩级别阈值 ===
            f"{prefix}COMPRESSION_LEVEL_LIGHT": "context_compression.levels.light",
            f"{prefix}COMPRESSION_LEVEL_STANDARD": "context_compression.levels.standard",
            f"{prefix}COMPRESSION_LEVEL_DEEP": "context_compression.levels.deep",
            f"{prefix}COMPRESSION_LEVEL_EMERGENCY": "context_compression.levels.emergency",

            # === 压缩摘要字数 ===
            f"{prefix}COMPRESSION_SUMMARY_LIGHT": "context_compression.summary_chars.light",
            f"{prefix}COMPRESSION_SUMMARY_STANDARD": "context_compression.summary_chars.standard",
            f"{prefix}COMPRESSION_SUMMARY_DEEP": "context_compression.summary_chars.deep",
            f"{prefix}COMPRESSION_SUMMARY_EMERGENCY": "context_compression.summary_chars.emergency",

            # === 压缩保留策略 ===
            f"{prefix}COMPRESSION_KEEP_AI_MESSAGES": "context_compression.preservation.keep_ai_messages",
            f"{prefix}COMPRESSION_KEEP_TOOL_RESULTS": "context_compression.preservation.keep_tool_results",
            f"{prefix}COMPRESSION_PRESERVE_ERRORS": "context_compression.preservation.preserve_errors",
            f"{prefix}COMPRESSION_EXTRACT_KEY_DECISIONS": "context_compression.preservation.extract_key_decisions",

            # === 文件工具配置 ===
            f"{prefix}TOOLS_FILE_EDIT_ENABLED": "tools.file.edit_enabled",
            f"{prefix}TOOLS_FILE_CREATE_ENABLED": "tools.file.create_enabled",
            f"{prefix}TOOLS_FILE_SYNTAX_CHECK_ENABLED": "tools.file.syntax_check_enabled",
            f"{prefix}TOOLS_FILE_MAX_READ_LINES": "tools.file.max_read_lines",
            f"{prefix}TOOLS_FILE_MAX_READ_CHARS": "tools.file.max_read_chars",

            # === Shell 工具配置 ===
            f"{prefix}TOOLS_SHELL_ENABLED": "tools.shell.enabled",
            f"{prefix}TOOLS_SHELL_DEFAULT_TIMEOUT": "tools.shell.default_timeout",
            f"{prefix}TOOLS_SHELL_MAX_OUTPUT_LENGTH": "tools.shell.max_output_length",
            f"{prefix}TOOLS_SHELL_MAX_FILE_SIZE": "tools.shell.max_file_size",
            f"{prefix}TOOLS_SHELL_SAFETY_CHECK": "tools.shell.safety_check",
            f"{prefix}TOOLS_SHELL_DANGEROUS_PATTERN_CHECK": "tools.shell.dangerous_pattern_check",

            # === 搜索工具配置 ===
            f"{prefix}TOOLS_SEARCH_MAX_FILE_SIZE": "tools.search.max_file_size",
            f"{prefix}TOOLS_SEARCH_MAX_MATCHES_PER_FILE": "tools.search.max_matches_per_file",
            f"{prefix}TOOLS_SEARCH_MAX_RESULTS": "tools.search.max_results",
            f"{prefix}TOOLS_SEARCH_CONTEXT_LINES": "tools.search.context_lines",

            # === 网络工具配置 ===
            f"{prefix}TOOLS_WEB_SEARCH_ENABLED": "tools.web.search_enabled",
            f"{prefix}TOOLS_WEB_MAX_SEARCH_RESULTS": "tools.web.max_search_results",
            f"{prefix}TOOLS_WEB_SEARCH_TIMEOUT": "tools.web.search_timeout",

            # === 安全配置 ===
            f"{prefix}SECURITY_ENABLED": "security.enabled",

            # === 日志配置 ===
            f"{prefix}LOG_LEVEL": "log.level",
            f"{prefix}LOG_FILE_ENABLED": "log.file_enabled",
            f"{prefix}LOG_FILE_PATH": "log.file_path",
            f"{prefix}LOG_FORMAT": "log.format",
            f"{prefix}LOG_DATE_FORMAT": "log.date_format",
            f"{prefix}LOG_MAX_FILE_SIZE": "log.max_file_size",
            f"{prefix}LOG_BACKUP_COUNT": "log.backup_count",
            f"{prefix}LOG_DETAILED_TRACEBACK": "log.detailed_traceback",

            # === 网络配置 ===
            f"{prefix}NETWORK_TIMEOUT": "network.timeout",
            f"{prefix}NETWORK_MAX_RETRIES": "network.max_retries",
            f"{prefix}NETWORK_RETRY_DELAY": "network.retry_delay",
            f"{prefix}NETWORK_USER_AGENT": "network.user_agent",
            f"{prefix}NETWORK_VERIFY_SSL": "network.verify_ssl",

            # === 进化引擎配置 ===
            f"{prefix}EVOLUTION_ENABLED": "evolution.enabled",
            f"{prefix}EVOLUTION_CONFIG_PATH": "evolution.config_path",
            f"{prefix}EVOLUTION_ARCHIVE_DIR": "evolution.archive_dir",
            f"{prefix}EVOLUTION_BACKUP_DIR": "evolution.backup_dir",
            f"{prefix}EVOLUTION_TEST_GATE_ENABLED": "evolution.test_gate_enabled",
            f"{prefix}EVOLUTION_TEST_GATE_TIMEOUT": "evolution.test_gate_timeout",
            f"{prefix}EVOLUTION_TEST_COMMAND": "evolution.test_command",
            f"{prefix}EVOLUTION_CHAT_DATASET_ENABLED": "evolution.chat_dataset.enabled",
            f"{prefix}EVOLUTION_CHAT_DATASET_AUTO_CAPTURE": "evolution.chat_dataset.auto_capture",
            f"{prefix}EVOLUTION_CHAT_DATASET_SEGMENTATION_STRATEGY": "evolution.chat_dataset.segmentation_strategy",
            f"{prefix}EVOLUTION_CHAT_DATASET_MIN_TURNS": "evolution.chat_dataset.min_turns",
            f"{prefix}EVOLUTION_CHAT_DATASET_MAX_TURNS": "evolution.chat_dataset.max_turns",
            f"{prefix}EVOLUTION_CHAT_DATASET_REQUIRE_SIGNAL": "evolution.chat_dataset.require_tool_call_or_analysis_or_conclusion",
            f"{prefix}EVOLUTION_CHAT_DATASET_EXCLUDE_PURE_CHITCHAT": "evolution.chat_dataset.exclude_pure_chitchat",
            f"{prefix}EVOLUTION_CHAT_DATASET_CANDIDATE_DIR": "evolution.chat_dataset.candidate_dir",
            f"{prefix}EVOLUTION_CHAT_DATASET_REVIEW_QUEUE_PATH": "evolution.chat_dataset.review_queue_path",
            f"{prefix}EVOLUTION_CHAT_DATASET_APPROVED_RAW_DIR": "evolution.chat_dataset.approved_raw_dir",
            f"{prefix}EVOLUTION_CHAT_DATASET_APPROVED_JSONL_PATH": "evolution.chat_dataset.approved_jsonl_path",
            f"{prefix}EVOLUTION_CHAT_DATASET_REJECTED_LOG_PATH": "evolution.chat_dataset.rejected_log_path",

            # === 记忆系统配置 ===
            f"{prefix}MEMORY_STORAGE_DIR": "memory.storage_dir",
            f"{prefix}MEMORY_MEMORY_FILE": "memory.memory_file",
            f"{prefix}MEMORY_ARCHIVE_DIR": "memory.archive_dir",
            f"{prefix}MEMORY_MAX_ENTRIES": "memory.max_entries",

            # === 策略系统配置 ===
            f"{prefix}STRATEGY_DATA_DIR": "strategy.data_dir",
            f"{prefix}STRATEGY_EXPLORATION_RATE": "strategy.exploration_rate",
            f"{prefix}STRATEGY_LEARNING_ENABLED": "strategy.learning_enabled",
            f"{prefix}STRATEGY_LEARNING_DATA_PATH": "strategy.learning_data_path",

            # === 代码分析配置 ===
            f"{prefix}ANALYSIS_DATA_DIR": "analysis.data_dir",
            f"{prefix}ANALYSIS_FEEDBACK_DIR": "analysis.feedback_dir",
            f"{prefix}ANALYSIS_KNOWLEDGE_GRAPH_PATH": "analysis.knowledge_graph_path",
            f"{prefix}ANALYSIS_PATTERN_LIBRARY_PATH": "analysis.pattern_library_path",

            # === UI 配置 ===
            f"{prefix}UI_LANGUAGE": "ui.language",
            f"{prefix}UI_THEME": "ui.theme",
            f"{prefix}UI_MAX_LOG_ENTRIES": "ui.max_log_entries",
            f"{prefix}UI_REFRESH_RATE": "ui.refresh_rate",
            f"{prefix}UI_SHOW_ASCII_ART": "ui.show_ascii_art",
            f"{prefix}UI_SHOW_WELCOME": "ui.show_welcome",

            # === 调试配置 ===
            f"{prefix}DEBUG_ENABLED": "debug.enabled",
            f"{prefix}DEBUG_VERBOSE": "debug.verbose",
            f"{prefix}DEBUG_TRACE_LLM": "debug.trace_llm",
            f"{prefix}DEBUG_TRACE_TOOLS": "debug.trace_tools",
            f"{prefix}DEBUG_TRACK_TOKEN_USAGE": "debug.track_token_usage",

        }

        # 布尔类型配置项
        bool_keys = {
            "llm.discovery.enabled", "llm.discovery.auto_adjust",
            "agent.auto_backup", "agent.exploration_mode",
            "agent.modes.chat_enabled", "agent.modes.self_evolution_enabled", "agent.modes.supervised_evolution_enabled",
            "context_compression.enabled", "context_compression.preservation.keep_tool_results",
            "context_compression.preservation.preserve_errors", "context_compression.preservation.extract_key_decisions",
            "tools.file.edit_enabled", "tools.file.create_enabled", "tools.file.syntax_check_enabled",
            "tools.shell.enabled", "tools.shell.safety_check", "tools.shell.dangerous_pattern_check",
            "tools.web.search_enabled",
            "security.enabled",
            "log.file_enabled", "log.detailed_traceback",
            "network.verify_ssl",
            "evolution.enabled", "evolution.test_gate_enabled",
            "evolution.chat_dataset.enabled", "evolution.chat_dataset.auto_capture",
            "evolution.chat_dataset.require_tool_call_or_analysis_or_conclusion",
            "evolution.chat_dataset.exclude_pure_chitchat",
            "strategy.learning_enabled",
            "ui.show_ascii_art", "ui.show_welcome",
            "debug.enabled", "debug.verbose", "debug.trace_llm", "debug.trace_tools", "debug.track_token_usage",
        }

        # 浮点类型配置项
        float_keys = {
            "llm.discovery.output_reserve_ratio",
            "context_compression.compression_temperature", "context_compression.effectiveness_threshold",
            "context_compression.levels.light", "context_compression.levels.standard",
            "context_compression.levels.deep", "context_compression.levels.emergency",
            "context_compression.preservation.keep_ai_messages",
            "network.retry_delay",
            "strategy.exploration_rate",
        }

        def assign_path(target: Dict[str, Any], path: str, value: Any) -> None:
            current = target
            parts = path.split(".")
            for part in parts[:-1]:
                current = current.setdefault(part, {})
            current[parts[-1]] = value

        def remap_legacy_provider_path(path: str) -> str:
            legacy_prefix = "llm.providers.default."
            if path.startswith(legacy_prefix):
                return "llm.profiles.primary.provider." + path[len(legacy_prefix):]
            return path

        for env_var, path in env_mappings.items():
            value = os.environ.get(env_var)
            if value is not None:
                path = remap_legacy_provider_path(path)
                if path in bool_keys:
                    value = value.lower() in ("true", "1", "yes", "on")
                elif path in float_keys:
                    try:
                        value = float(value)
                    except ValueError:
                        value = value
                elif path.split(".")[-1] in ("max_output_tokens", "timeout", "connect_timeout",
                            "awake_interval", "max_iterations", "max_runtime",
                            "max_continuation_turns",
                            "backup_interval", "auto_restart_threshold",
                            "min_turns", "max_turns",
                            "max_retries", "max_token_limit",
                            "keep_recent_steps", "summary_max_chars",
                            "max_compressions_per_session", "max_read_lines",
                            "max_read_chars", "default_timeout", "max_output_length",
                            "max_file_size", "max_matches_per_file", "max_results",
                            "context_lines", "max_search_results", "search_timeout",
                            "max_file_size", "backup_count", "max_entries",
                            "test_gate_timeout", "max_log_entries", "refresh_rate"):
                    try:
                        value = int(value)
                    except ValueError:
                        value = value

                assign_path(config, path, value)
                touched = True

        llm_prefix = f"{prefix}LLM__"
        for env_var, raw_value in os.environ.items():
            if not env_var.startswith(llm_prefix):
                continue
            path = remap_legacy_provider_path(env_var[len(prefix):].lower().replace("__", "."))
            value = raw_value
            if path in bool_keys:
                value = value.lower() in ("true", "1", "yes", "on")
            elif path in float_keys:
                try:
                    value = float(value)
                except ValueError:
                    pass
            elif path.split(".")[-1] in (
                "context_window", "max_output_tokens", "timeout", "connect_timeout",
                "max_attempts", "fallback_max_tokens", "fallback_max_token_limit",
            ):
                try:
                    value = int(value)
                except ValueError:
                    pass
            assign_path(config, path, value)
            touched = True

        effective_provider = base_provider
        provider_env_var = get_provider_api_key_env(effective_provider)
        if provider_env_var:
            provider_api_key = os.environ.get(provider_env_var)
            if provider_api_key:
                assign_path(config, "llm.profiles.primary.provider.api_key", provider_api_key)
                touched = True

        if not touched:
            return {}
        return config

    def load(self, **kwargs) -> AppConfig:
        """
        加载完整配置

        优先级：命令行参数(kwargs) > 环境变量 > TOML > 默认值

        Args:
            **kwargs: 直接指定的配置项，如
                     llm.profiles.primary.model="gpt-4"
                     支持点号分隔的嵌套键，如 context_compression.max_token_limit=16000

        Returns:
            AppConfig 实例
        """
        # 1. 创建默认配置
        config = AppConfig()

        # 2. 从 TOML 加载
        toml_config = self._load_from_toml()
        if toml_config:
            config = self._apply_dict(config, toml_config)

        # 3. 从环境变量加载（较高优先级，会覆盖 TOML）
        env_config = self._load_from_env(
            base_provider=config.llm.get_provider(role="primary").kind,
        )
        if env_config:
            config = self._apply_dict(config, env_config)

        # 4. 从 kwargs 加载，让 runtime.profile 参与 profile 解析
        kwargs_config = None
        if kwargs:
            kwargs_config = self._flatten_kwargs(kwargs)
            config = self._apply_dict(config, kwargs_config)

        from .profiles import apply_runtime_profile
        config = apply_runtime_profile(config)

        # 5. profile 提供运行基线，显式 kwargs 仍保持最高优先级
        if kwargs_config:
            config = self._apply_dict(config, kwargs_config)
            if config.runtime.profile:
                runtime_overrides = {
                    key: value
                    for key, value in kwargs_config.get("runtime", {}).items()
                    if key != "profile"
                }
                config = apply_runtime_profile(config)
                if runtime_overrides:
                    config = self._apply_dict(config, {"runtime": runtime_overrides})

        for provider in config.llm.providers.values():
            resolved_api_key = provider.resolve_api_key()
            if resolved_api_key:
                provider.api_key = resolved_api_key
        return config

    def _flatten_kwargs(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """
        将 kwargs 展平为嵌套字典

        Args:
            kwargs: 可能包含点号或双下划线分隔的嵌套键
                   支持格式：'llm.profiles.primary.model'、
                            'llm__profiles__primary__model'

        Returns:
            展平后的配置字典（Pydantic 字段格式）
        """
        result: Dict[str, Any] = {}
        for key, value in kwargs.items():
            normalized_key = key.replace('__', '.')
            if '.' not in normalized_key and '_' in normalized_key:
                raise ValueError(
                    f"Unsupported legacy config override '{key}'. "
                    "Use dotted paths like 'llm.profiles.primary.model' or "
                    "double-underscore paths like 'llm__profiles__primary__model'."
                )
            if '.' in normalized_key:
                parts = normalized_key.split('.')
                current = result
                for part in parts[:-1]:
                    if part not in current:
                        current[part] = {}
                    current = current[part]
                current[parts[-1]] = value
            else:
                result[normalized_key] = value

        # 转换嵌套格式为 Pydantic 字段格式（与 _normalize_toml_keys 一致）
        return self._normalize_toml_keys(result)

    def _apply_dict(self, config: AppConfig, data: Dict[str, Any]) -> AppConfig:
        """
        将字典应用到配置对象（深度合并）

        Args:
            config: 原始配置
            data: 要应用的数据

        Returns:
            更新后的配置
        """
        data = normalize_public_config_dict(data)
        # 深度合并字典
        current = config.model_dump()

        def deep_merge(base: Dict, update: Dict) -> Dict:
            """深度合并两个字典"""
            result = base.copy()
            for key, value in update.items():
                if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                    result[key] = deep_merge(result[key], value)
                else:
                    result[key] = value
            return result

        merged = deep_merge(current, data)

        if merged != current:
            config = AppConfig.model_validate(merged)

        return config


# ============================================================================
# 配置管理器
# ============================================================================

class Settings:
    """
    配置管理器

    提供配置的单例访问，支持动态更新和模型切换。
    这是新架构中的主要配置访问入口。

    Example:
        # 获取配置
        settings = Settings()
        config = settings.config

        # 访问 LLM 配置
        print(config.llm.get_profile(role="primary").model)

        # 切换模型
        settings = get_settings()
    """

    def __init__(self, config_path: Optional[str] = None, **kwargs) -> None:
        """
        初始化配置管理器

        Args:
            config_path: 配置文件路径
            **kwargs: 直接指定的配置项（最高优先级）
                     如 llm.profiles.primary.model="gpt-4",
                        context_compression.max_token_limit=16000
        """
        self._loader = ConfigLoader(config_path)
        self._config: Optional[AppConfig] = None
        self._kwargs = kwargs

    @property
    def config(self) -> AppConfig:
        """获取当前配置（延迟加载）"""
        if self._config is None:
            self._config = self._loader.load(**self._kwargs)
        return self._config

    def reload(self, config_path: Optional[str] = None, **kwargs) -> AppConfig:
        """
        重新加载配置

        Args:
            config_path: 新的配置文件路径
            **kwargs: 直接指定的配置项（最高优先级）

        Returns:
            重新加载后的配置
        """
        if config_path:
            self._loader = ConfigLoader(config_path)
        self._kwargs = kwargs
        self._config = self._loader.load(**self._kwargs)
        return self._config

    def get_api_key(self) -> Optional[str]:
        """
        获取当前配置的 API Key

        Returns:
            API Key，未设置返回 None
        """
        return self.config.get_api_key()

    def __repr__(self) -> str:
        primary = self.config.llm.get_profile(role="primary")
        provider = self.config.llm.get_provider(primary.provider_id)
        return f"Settings(model={primary.model}, provider={provider.kind})"


# ============================================================================
# 全局单例访问
# ============================================================================

def get_settings(config_path: Optional[str] = None, **kwargs) -> Settings:
    """
    获取 Settings 单例

    Args:
        config_path: 配置文件路径，首次调用后忽略
        **kwargs: 直接指定的配置项（最高优先级）

    Returns:
        Settings 实例
    """
    global _settings, _config_path

    if _settings is None or config_path is not None or kwargs:
        _settings = Settings(config_path, **kwargs)
        _config_path = config_path

    return _settings


def get_config(**kwargs) -> AppConfig:
    """
    获取当前配置（便捷函数）

    Args:
        **kwargs: 直接指定的配置项（最高优先级）
                 如 get_config(**{"llm.profiles.primary.model": "gpt-4"})

    Returns:
        AppConfig 实例
    """
    if kwargs:
        # 使用 kwargs 创建新配置
        return get_settings(**kwargs).config
    return get_settings().config


# ============================================================================
# 便捷配置访问函数
# ============================================================================

def get_llm_config() -> LLMConfig:
    """获取 LLM 配置"""
    return get_config().llm


def get_agent_config() -> AgentConfig:
    """获取 Agent 配置"""
    return get_config().agent


def get_web_chat_config() -> WebChatConfig:
    """获取 Web Chat 配置"""
    return get_config().web_chat


def get_compression_config() -> ContextCompressionConfig:
    """获取压缩配置"""
    return get_config().context_compression


def get_tools_config() -> ToolConfig:
    """获取工具配置"""
    return get_config().tools


def get_log_config() -> LogConfig:
    """获取日志配置"""
    return get_config().log


def get_network_config() -> NetworkConfig:
    """获取网络配置"""
    return get_config().network


def get_security_config() -> SecurityConfig:
    """获取安全配置"""
    return get_config().security


def get_evolution_config() -> EvolutionConfig:
    """获取进化引擎配置"""
    return get_config().evolution


def get_memory_config() -> MemoryConfig:
    """获取记忆系统配置"""
    return get_config().memory


def get_strategy_config() -> StrategyConfig:
    """获取策略系统配置"""
    return get_config().strategy


def get_ui_config() -> UIConfig:
    """获取 UI 配置"""
    return get_config().ui


def get_parser_config() -> "ParserConfig":
    """获取响应解析器配置"""
    return get_config().parser


def get_prompt_config() -> "PromptConfig":
    """获取提示词管理器配置"""
    return get_config().prompt


def get_debug_config() -> DebugConfig:
    """获取调试配置"""
    return get_config().debug


def get_pet_config() -> PetConfig:
    """获取宠物系统主配置"""
    return get_config().pet


def get_pet_gene_config() -> GeneConfig:
    """获取宠物基因系统配置"""
    return get_config().pet_gene


def get_pet_heart_config() -> HeartConfig:
    """获取宠物心跳系统配置"""
    return get_config().pet_heart


def get_pet_dream_config() -> DreamConfig:
    """获取宠物梦境系统配置"""
    return get_config().pet_dream


def get_pet_personality_config() -> PersonalityConfig:
    """获取宠物性格系统配置"""
    return get_config().pet_personality


def get_pet_hunger_config() -> HungerConfig:
    """获取宠物饥饿系统配置"""
    return get_config().pet_hunger


def get_pet_diary_config() -> DiaryConfig:
    """获取宠物日记系统配置"""
    return get_config().pet_diary


def get_pet_social_config() -> SocialConfig:
    """获取宠物社交系统配置"""
    return get_config().pet_social


def get_pet_health_config() -> HealthConfig:
    """获取宠物健康系统配置"""
    return get_config().pet_health


def get_pet_skin_config() -> SkinConfig:
    """获取宠物装扮系统配置"""
    return get_config().pet_skin


def get_pet_sound_config() -> SoundConfig:
    """获取宠物声音系统配置"""
    return get_config().pet_sound


# ============================================================================
# 导出
# ============================================================================

__all__ = [
    # 核心类
    "AppConfig",
    "ConfigLoader",
    "Settings",
    "normalize_public_config_dict",
    "denormalize_config_dict",
    # 函数
    "get_settings",
    "get_config",
    # 便捷配置访问函数
    "get_llm_config",
    "get_agent_config",
    "get_web_chat_config",
    "get_compression_config",
    "get_tools_config",
    "get_log_config",
    "get_network_config",
    "get_security_config",
    "get_evolution_config",
    "get_memory_config",
    "get_strategy_config",
    "get_ui_config",
    "get_parser_config",
    "get_prompt_config",
    "get_debug_config",
    # 从 providers 导出
    "MODEL_PRESETS",
    "get_model_preset",
    "list_models",
    "show_model_info",
    "resolve_model_alias",
]
