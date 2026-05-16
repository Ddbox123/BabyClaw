"""
LLM 模型预设注册表

定义所有支持的 LLM 模型预设，包含 OpenAI、Anthropic、DeepSeek、阿里云百炼等。
每个预设包含模型的基本信息、API 端点和默认参数。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple


@dataclass
class ModelPreset:
    """
    LLM 模型预设

    Attributes:
        name: 显示名称
        provider: 提供商标识符
        model_name: API 使用的模型名称
        api_base: API 端点 URL
        api_key_env: API Key 对应的环境变量名
        default_temperature: 默认采样温度
        max_tokens: 最大输出 token 数
        description: 模型描述
        supports_function_call: 是否支持函数调用
    """
    name: str
    provider: str
    model_name: str
    api_base: str
    api_key_env: str
    default_temperature: float
    max_tokens: int
    description: str
    supports_function_call: bool = True


# ============================================================================
# 模型预设注册表
# ============================================================================

MODEL_PRESETS: Dict[str, ModelPreset] = {
    # ========================================================================
    # OpenAI 系列
    # ========================================================================
    "gpt-4o": ModelPreset(
        name="GPT-4o",
        provider="openai",
        model_name="gpt-4o",
        api_base="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
        default_temperature=0.7,
        max_tokens=4096,
        description="OpenAI 最新旗舰模型，支持函数调用，速度更快",
    ),
    "gpt-4-turbo": ModelPreset(
        name="GPT-4 Turbo",
        provider="openai",
        model_name="gpt-4-turbo",
        api_base="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
        default_temperature=0.7,
        max_tokens=4096,
        description="OpenAI 高性能 GPT-4 模型",
    ),
    "gpt-4": ModelPreset(
        name="GPT-4",
        provider="openai",
        model_name="gpt-4",
        api_base="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
        default_temperature=0.7,
        max_tokens=4096,
        description="OpenAI 最强模型，适合复杂推理",
    ),
    "gpt-3.5-turbo": ModelPreset(
        name="GPT-3.5 Turbo",
        provider="openai",
        model_name="gpt-3.5-turbo",
        api_base="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
        default_temperature=0.7,
        max_tokens=4096,
        description="快速、便宜的 ChatGPT 模型",
    ),

    # ========================================================================
    # Anthropic 系列
    # ========================================================================
    "claude-3-opus": ModelPreset(
        name="Claude 3 Opus",
        provider="anthropic",
        model_name="claude-3-opus-20240229",
        api_base="https://api.anthropic.com/v1",
        api_key_env="ANTHROPIC_API_KEY",
        default_temperature=1.0,
        max_tokens=4096,
        description="Anthropic 最强模型，适合复杂任务",
    ),
    "claude-3-sonnet": ModelPreset(
        name="Claude 3 Sonnet",
        provider="anthropic",
        model_name="claude-3-sonnet-20240229",
        api_base="https://api.anthropic.com/v1",
        api_key_env="ANTHROPIC_API_KEY",
        default_temperature=1.0,
        max_tokens=4096,
        description="Anthropic 平衡模型，性价比高",
    ),
    "claude-3": ModelPreset(
        name="Claude 3",
        provider="anthropic",
        model_name="claude-3-haiku-20240307",
        api_base="https://api.anthropic.com/v1",
        api_key_env="ANTHROPIC_API_KEY",
        default_temperature=1.0,
        max_tokens=4096,
        description="Anthropic 快速模型",
    ),
    "claude-3.5": ModelPreset(
        name="Claude 3.5 Sonnet",
        provider="anthropic",
        model_name="claude-3-5-sonnet-20241022",
        api_base="https://api.anthropic.com/v1",
        api_key_env="ANTHROPIC_API_KEY",
        default_temperature=1.0,
        max_tokens=8192,
        description="Anthropic 最新模型，能力超越 GPT-4",
    ),

    # ========================================================================
    # Google 系列
    # ========================================================================
    "gemini-pro": ModelPreset(
        name="Gemini Pro",
        provider="google",
        model_name="gemini-pro",
        api_base="https://generativelanguage.googleapis.com/v1beta",
        api_key_env="GOOGLE_API_KEY",
        default_temperature=0.9,
        max_tokens=4096,
        description="Google Gemini Pro 模型",
    ),
    "gemini-2": ModelPreset(
        name="Gemini 2.0 Flash",
        provider="google",
        model_name="gemini-2.0-flash",
        api_base="https://generativelanguage.googleapis.com/v1beta",
        api_key_env="GOOGLE_API_KEY",
        default_temperature=0.9,
        max_tokens=8192,
        description="Google 最新 Gemini 模型",
    ),

    # ========================================================================
    # DeepSeek 系列
    # ========================================================================
    "deepseek": ModelPreset(
        name="DeepSeek V3",
        provider="deepseek",
        model_name="deepseek-chat",
        api_base="https://api.deepseek.com/v1",
        api_key_env="DEEPSEEK_API_KEY",
        default_temperature=0.7,
        max_tokens=4096,
        description="深度求索大模型，性价比高",
    ),
    "deepseek-coder": ModelPreset(
        name="DeepSeek Coder",
        provider="deepseek",
        model_name="deepseek-coder",
        api_base="https://api.deepseek.com/v1",
        api_key_env="DEEPSEEK_API_KEY",
        default_temperature=0.7,
        max_tokens=4096,
        description="深度求索代码模型",
    ),

    # ========================================================================
    # 阿里云百炼 (通义千问)
    # ========================================================================
    "qwen-plus": ModelPreset(
        name="Qwen Plus (通义千问 Plus)",
        provider="aliyun",
        model_name="qwen-plus",
        api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key_env="DASHSCOPE_API_KEY",
        default_temperature=0.7,
        max_tokens=4096,
        description="阿里云百炼 Qwen Plus，性能均衡",
    ),
    "qwen-plus-rear": ModelPreset(
        name="Qwen Plus (兜底)",
        provider="aliyun",
        model_name="qwen-plus-rear",
        api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key_env="DASHSCOPE_API_KEY",
        default_temperature=0.7,
        max_tokens=4096,
        description="阿里云百炼 Qwen Plus 兜底版本",
    ),
    "qwen-turbo": ModelPreset(
        name="Qwen Turbo (通义千问 Turbo)",
        provider="aliyun",
        model_name="qwen-turbo",
        api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key_env="DASHSCOPE_API_KEY",
        default_temperature=0.7,
        max_tokens=4096,
        description="阿里云百炼 Qwen Turbo，速度更快",
    ),
    "qwen-max": ModelPreset(
        name="Qwen Max (通义千问 Max)",
        provider="aliyun",
        model_name="qwen-max",
        api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key_env="DASHSCOPE_API_KEY",
        default_temperature=0.7,
        max_tokens=4096,
        description="阿里云百炼 Qwen Max，最强版本",
    ),
    "qwen-max-longcontext": ModelPreset(
        name="Qwen Max (长上下文)",
        provider="aliyun",
        model_name="qwen-max-longcontext",
        api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key_env="DASHSCOPE_API_KEY",
        default_temperature=0.7,
        max_tokens=8192,
        description="阿里云百炼 Qwen Max，支持长上下文",
    ),
    "qwen-coder-plus": ModelPreset(
        name="Qwen Coder Plus (通义千问 Coder)",
        provider="aliyun",
        model_name="qwen-coder-plus",
        api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key_env="DASHSCOPE_API_KEY",
        default_temperature=0.7,
        max_tokens=4096,
        description="阿里云百炼代码模型，专为编程优化",
    ),
    "qwen": ModelPreset(
        name="Qwen Plus (qwen 别名)",
        provider="aliyun",
        model_name="qwen-plus",
        api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key_env="DASHSCOPE_API_KEY",
        default_temperature=0.7,
        max_tokens=4096,
        description="阿里云通义千问 Plus (qwen 别名)",
    ),

    # ========================================================================
    # 智谱 GLM
    # ========================================================================
    "glm": ModelPreset(
        name="GLM-4",
        provider="zhipu",
        model_name="glm-4",
        api_base="https://open.bigmodel.cn/api/paas/v4",
        api_key_env="ZHIPU_API_KEY",
        default_temperature=0.9,
        max_tokens=4096,
        description="智谱 GLM-4 大模型",
    ),

    # ========================================================================
    # 本地模型 (Ollama)
    # ========================================================================
    "ollama-llama3": ModelPreset(
        name="Ollama Llama3",
        provider="ollama",
        model_name="llama3",
        api_base="http://localhost:11434/v1",
        api_key_env="",  # 本地模型不需要 API Key
        default_temperature=0.7,
        max_tokens=4096,
        description="Ollama 本地 Llama3 模型",
        supports_function_call=False,
    ),
    "ollama-qwen": ModelPreset(
        name="Ollama Qwen",
        provider="ollama",
        model_name="qwen2.5",
        api_base="http://localhost:11434/v1",
        api_key_env="",
        default_temperature=0.7,
        max_tokens=4096,
        description="Ollama 本地 Qwen 模型",
        supports_function_call=False,
    ),
    "ollama-codellama": ModelPreset(
        name="Ollama CodeLlama",
        provider="ollama",
        model_name="codellama",
        api_base="http://localhost:11434/v1",
        api_key_env="",
        default_temperature=0.7,
        max_tokens=4096,
        description="Ollama 本地代码模型",
        supports_function_call=False,
    ),

    # ========================================================================
    # SiliconFlow / 硅基流动
    # ========================================================================
    "siliconflow-gpt": ModelPreset(
        name="SiliconFlow GPT",
        provider="siliconflow",
        model_name="gpt-4o",
        api_base="https://api.siliconflow.cn/v1",
        api_key_env="SILICONFLOW_API_KEY",
        default_temperature=0.7,
        max_tokens=4096,
        description="硅基流动平台 GPT-4o",
    ),
    "siliconflow-deepseek": ModelPreset(
        name="SiliconFlow DeepSeek",
        provider="siliconflow",
        model_name="deepseek-ai/DeepSeek-V3",
        api_base="https://api.siliconflow.cn/v1",
        api_key_env="SILICONFLOW_API_KEY",
        default_temperature=0.7,
        max_tokens=4096,
        description="硅基流动平台 DeepSeek",
    ),

    # ========================================================================
    # Groq
    # ========================================================================
    "groq-llama3": ModelPreset(
        name="Groq Llama3",
        provider="groq",
        model_name="llama-3.1-70b-versatile",
        api_base="https://api.groq.com/openai/v1",
        api_key_env="GROQ_API_KEY",
        default_temperature=0.7,
        max_tokens=4096,
        description="Groq 超快 Llama 模型",
    ),

    # ========================================================================
    # MiniMax
    # ========================================================================
    "minimax-m2": ModelPreset(
        name="MiniMax M2",
        provider="minimax",
        model_name="MiniMax-M2.7",
        api_base="https://api.minimaxi.com/v1",
        api_key_env="MINIMAX_API_KEY",
        default_temperature=1.0,
        max_tokens=8192,
        description="MiniMax M2 大模型，支持长上下文",
    ),
}


# ============================================================================
# 提供商元数据
# ============================================================================

PROVIDER_METADATA: Dict[str, Dict[str, str]] = {
    "openai": {
        "name": "OpenAI",
        "website": "https://openai.com",
        "docs": "https://platform.openai.com/docs",
    },
    "anthropic": {
        "name": "Anthropic",
        "website": "https://anthropic.com",
        "docs": "https://docs.anthropic.com",
    },
    "google": {
        "name": "Google AI",
        "website": "https://ai.google.dev",
        "docs": "https://ai.google.dev/docs",
    },
    "deepseek": {
        "name": "DeepSeek",
        "website": "https://deepseek.com",
        "docs": "https://platform.deepseek.com/docs",
    },
    "aliyun": {
        "name": "阿里云百炼",
        "website": "https://bailian.console.aliyun.com",
        "docs": "https://help.aliyun.com/model-studio",
    },
    "zhipu": {
        "name": "智谱 AI",
        "website": "https://www.zhipuai.cn",
        "docs": "https://open.bigmodel.cn/doc/api",
    },
    "ollama": {
        "name": "Ollama (本地)",
        "website": "https://ollama.com",
        "docs": "https://github.com/ollama/ollama",
    },
    "siliconflow": {
        "name": "硅基流动",
        "website": "https://siliconflow.cn",
        "docs": "https://docs.siliconflow.cn",
    },
    "groq": {
        "name": "Groq",
        "website": "https://groq.com",
        "docs": "https://console.groq.com/docs",
    },
    "minimax": {
        "name": "MiniMax",
        "website": "https://www.minimax.io",
        "docs": "https://www.minimaxi.com/document",
    },
}


# ============================================================================
# 工具函数
# ============================================================================

def list_models() -> List[Dict[str, str]]:
    """
    列出所有可用模型

    Returns:
        模型信息列表，每个元素包含 id, name, provider, description
    """
    return [
        {
            "id": key,
            "name": preset.name,
            "provider": preset.provider,
            "description": preset.description,
        }
        for key, preset in MODEL_PRESETS.items()
    ]


def list_models_by_provider(provider: str) -> List[Dict[str, str]]:
    """
    按提供商筛选模型

    Args:
        provider: 提供商标识符

    Returns:
        该提供商下的所有模型列表
    """
    return [
        {
            "id": key,
            "name": preset.name,
            "model_name": preset.model_name,
            "description": preset.description,
        }
        for key, preset in MODEL_PRESETS.items()
        if preset.provider == provider
    ]


def get_model_preset(model_id: str) -> Optional[ModelPreset]:
    """
    获取模型预设

    Args:
        model_id: 模型 ID

    Returns:
        ModelPreset 对象，如果不存在返回 None
    """
    return MODEL_PRESETS.get(model_id)


def get_provider_models(provider: str) -> List[str]:
    """
    获取指定提供商的所有模型 ID

    Args:
        provider: 提供商标识符

    Returns:
        模型 ID 列表
    """
    return [
        key
        for key, preset in MODEL_PRESETS.items()
        if preset.provider == provider
    ]


def show_model_info(model_id: str) -> Optional[str]:
    """
    格式化显示模型详细信息

    Args:
        model_id: 模型 ID

    Returns:
        格式化的模型信息，未找到返回 None
    """
    preset = MODEL_PRESETS.get(model_id)
    if not preset:
        return None

    lines = [
        f"模型: {preset.name}",
        f"ID: {model_id}",
        f"提供商: {preset.provider}",
        f"模型名: {preset.model_name}",
        f"API 端点: {preset.api_base or '(默认)'}",
        f"API Key 环境变量: {preset.api_key_env or '(无需)'}",
        f"默认温度: {preset.default_temperature}",
        f"最大 tokens: {preset.max_tokens}",
        f"支持函数调用: {'是' if preset.supports_function_call else '否'}",
        "",
        f"描述: {preset.description}",
    ]

    return '\n'.join(lines)


# ============================================================================
# 别名映射（用于便捷访问）
# ============================================================================

MODEL_ALIASES: Dict[str, str] = {
    # OpenAI 别名
    "gpt4": "gpt-4",
    "gpt-4o": "gpt-4o",
    "gpt3.5": "gpt-3.5-turbo",
    "gpt-3.5": "gpt-3.5-turbo",

    # Anthropic 别名
    "claude": "claude-3.5",
    "claude3": "claude-3.5",
    "claude-3.5": "claude-3.5",
    "claude3.5": "claude-3.5",
    "opus": "claude-3-opus",
    "sonnet": "claude-3-sonnet",

    # Google 别名
    "gemini": "gemini-2",
    "gemini-pro": "gemini-pro",

    # DeepSeek 别名
    "deepseek-v3": "deepseek",
    "ds": "deepseek",

    # 阿里云百炼别名
    "qwen": "qwen-plus",
    "qwen-plus": "qwen-plus",
    "qwen-turbo": "qwen-turbo",
    "qwen-max": "qwen-max",
    "qwen-coder": "qwen-coder-plus",

    # 智谱别名
    "glm4": "glm",
    "zhipu": "glm",

    # Ollama 别名
    "ollama": "ollama-llama3",
    "local": "ollama-llama3",

    # MiniMax 别名
    "minimax": "minimax-m2",
    "m2": "minimax-m2",
}


def resolve_model_alias(model_id: str) -> str:
    """
    解析模型别名

    Args:
        model_id: 模型 ID 或别名

    Returns:
        解析后的模型 ID
    """
    return MODEL_ALIASES.get(model_id, model_id)


# ============================================================================
# 模型动态发现
# ============================================================================

def init_model_discovery(
    config: Any,
    debug_logger: Optional[Any] = None,
) -> Tuple[int, Optional[Any]]:
    """
    执行模型动态发现，返回 effective_max_token_limit。

    Args:
        config: AppConfig 实例，主要读取 llm.providers / llm.profiles /
                llm.discovery / context_compression 配置
        debug_logger: 可选的 debug logger 对象，拥有 .success() 和 .warning() 方法。
                      若为 None，则静默执行。

    Returns:
        (effective_max_token_limit, model_info)
    """
    # 避免循环导入
    from core.infrastructure.model_discovery import discover_model_sync, DiscoveryStatus

    model_info = None

    profile = config.llm.get_profile(role="primary")
    provider = config.llm.get_provider(profile.provider_id)
    api_base = provider.base_url or ''
    api_key = config.get_api_key_for_profile(profile_id=profile.profile_id) or ''
    discovery_enabled = bool(config.llm.discovery.enabled and profile.discovery_enabled and api_base)

    if not discovery_enabled:
        return getattr(config.context_compression, 'max_token_limit', 16000), None

    try:
        model_info = discover_model_sync(
            api_base=api_base,
            model_name=profile.model,
            api_key=api_key,
            fallback_max_tokens=profile.max_output_tokens,
            fallback_max_token_limit=getattr(config.context_compression, 'max_token_limit', 16000),
            timeout=config.llm.discovery.timeout,
            enabled=True,
        )

        if model_info.status == DiscoveryStatus.SUCCESS:
            if debug_logger:
                debug_logger.success(
                    f"模型发现成功: {model_info.model_name}\n"
                    f"  context_window: {model_info.max_model_len}\n"
                    f"  建议 max_tokens: {model_info.suggested_max_tokens}\n"
                    f"  压缩阈值 max_token_limit: {model_info.compression_thresholds.max_token_limit}",
                    tag="MODEL_DISCOVERY",
                )
            return model_info.compression_thresholds.max_token_limit, model_info
        else:
            if debug_logger:
                debug_logger.warning(
                    f"模型发现失败: {model_info.error_message or '未知错误'}，使用配置文件的值",
                    tag="MODEL_DISCOVERY",
                )
    except Exception as e:
        if debug_logger:
            debug_logger.warning(f"模型发现异常: {e}，使用配置文件的值", tag="MODEL_DISCOVERY")

    return getattr(config.context_compression, 'max_token_limit', 16000), model_info


# ============================================================================
# 导出
# ============================================================================

__all__ = [
    "ModelPreset",
    "MODEL_PRESETS",
    "PROVIDER_METADATA",
    "MODEL_ALIASES",
    # 工具函数
    "list_models",
    "list_models_by_provider",
    "get_model_preset",
    "get_provider_models",
    "show_model_info",
    "resolve_model_alias",
    "init_model_discovery",
]
