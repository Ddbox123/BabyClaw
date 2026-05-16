#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
模型动态发现模块

运行时向 API 端点发送请求，获取模型实际支持的 max_model_len，
并据此动态调整 max_tokens 和压缩阈值。

使用方式：
    discovery = ModelDiscovery(api_base="http://[::1]:8000/v1")
    model_info = await discovery.discover()
    print(f"max_model_len: {model_info.max_model_len}")
    print(f"suggested_max_tokens: {model_info.suggested_max_tokens}")
    print(f"compression_thresholds: {model_info.compression_thresholds}")
"""

from __future__ import annotations

import httpx
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from enum import Enum


from core.logging import debug_logger


class DiscoveryStatus(Enum):
    """发现状态"""
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"  # 部分成功
    SKIPPED = "skipped"  # 跳过（未启用或无端点）


@dataclass
class CompressionThresholds:
    """动态计算的压缩阈值"""
    max_token_limit: int = 16000
    light_threshold: float = 0.6
    standard_threshold: float = 0.8
    deep_threshold: float = 0.9
    emergency_threshold: float = 0.95

    # 各压缩级别的摘要字数（根据 max_token_limit 动态调整）
    light_summary_chars: int = 500
    standard_summary_chars: int = 1000
    deep_summary_chars: int = 2000
    emergency_summary_chars: int = 3000

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_token_limit": self.max_token_limit,
            "light_threshold": self.light_threshold,
            "standard_threshold": self.standard_threshold,
            "deep_threshold": self.deep_threshold,
            "emergency_threshold": self.emergency_threshold,
            "light_summary_chars": self.light_summary_chars,
            "standard_summary_chars": self.standard_summary_chars,
            "deep_summary_chars": self.deep_summary_chars,
            "emergency_summary_chars": self.emergency_summary_chars,
        }


@dataclass
class ModelInfo:
    """模型信息"""
    model_name: str = "unknown"
    max_model_len: int = 32768  # 默认值
    suggested_max_tokens: int = 4096  # 建议的 max_tokens
    provider: str = "unknown"
    status: DiscoveryStatus = DiscoveryStatus.SKIPPED
    error_message: Optional[str] = None
    compression_thresholds: CompressionThresholds = field(default_factory=CompressionThresholds)
    raw_response: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_name": self.model_name,
            "max_model_len": self.max_model_len,
            "suggested_max_tokens": self.suggested_max_tokens,
            "provider": self.provider,
            "status": self.status.value,
            "error_message": self.error_message,
            "compression_thresholds": self.compression_thresholds.to_dict(),
        }


class ModelDiscovery:
    """
    模型动态发现器

    向 API 端点发送请求，获取模型的实际参数。
    支持的 API 格式：
    - OpenAI 兼容格式: GET /models 或 GET /v1/models
    - 返回格式: {"data": [{"id": "xxx", "context_window": 32768}]}
    """

    # API 端点路径列表（按优先级排序）
    ENDPOINTS = [
        "/v1/models",
        "/models",
        "/api/models",
        "/v1/model_details",
    ]

    # 模型 ID 中的 context_window 字段名
    CONTEXT_WINDOW_FIELDS = [
        "context_window",
        "max_model_len",
        "max_tokens",
        "context_length",
        "max_position_embeddings",
    ]

    KNOWN_CONTEXT_WINDOWS = {
        "minimax-m2.7": 204800,
        "minimax_m2.7": 204800,
        "minimaxm2.7": 204800,
        "minimaxm27": 204800,
        "m2.7": 204800,
    }

    def __init__(
        self,
        api_base: str,
        model_name: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: int = 5,  # vLLM 响应很快，5秒足够
        enabled: bool = True,
    ):
        """
        初始化模型发现器

        Args:
            api_base: API 基础 URL
            model_name: 模型名称（用于匹配，如果 API 返回多个模型）
            timeout: 请求超时（秒）
            enabled: 是否启用自动发现
        """
        self.api_base = api_base.rstrip("/")
        self.model_name = model_name
        self.api_key = api_key or ""
        self.timeout = timeout
        self.enabled = enabled

        # 保留的配置（用于 fallback）
        self._fallback_max_tokens: Optional[int] = None
        self._fallback_max_token_limit: Optional[int] = None

    def set_fallback(
        self,
        max_tokens: Optional[int] = None,
        max_token_limit: Optional[int] = None,
    ) -> None:
        """
        设置 fallback 值（当发现失败时使用）

        Args:
            max_tokens: 备用 max_tokens
            max_token_limit: 备用 max_token_limit
        """
        self._fallback_max_tokens = max_tokens
        self._fallback_max_token_limit = max_token_limit

    async def discover(self) -> ModelInfo:
        """
        执行模型发现

        Returns:
            ModelInfo: 模型信息
        """
        if not self.enabled:
            debug_logger.info("模型动态发现已禁用，使用配置文件中的值")
            return self._create_skipped_info()

        # 尝试各个端点
        for endpoint in self.ENDPOINTS:
            try:
                result = await self._try_endpoint(endpoint)
                if result.status == DiscoveryStatus.SUCCESS:
                    return result
            except Exception as e:
                debug_logger.debug(f"尝试端点 {endpoint} 失败: {e}")
                continue

        # 所有端点都失败，返回 fallback
        debug_logger.warning("模型发现失败，使用 fallback 值")
        return self._create_fallback_info()

    async def _try_endpoint(self, endpoint: str) -> ModelInfo:
        """
        尝试指定端点

        Args:
            endpoint: API 端点路径

        Returns:
            ModelInfo: 模型信息
        """
        # 拼接 URL，避免 /v1 重复
        # api_base 如 "http://localhost:8000/v1"，endpoint 如 "/v1/models" 或 "/models"
        endpoint = endpoint.lstrip("/")
        if endpoint.startswith("v1/"):
            endpoint = endpoint[3:]  # 去掉 "v1/"
        url = f"{self.api_base}/{endpoint}"
        debug_logger.info(f"尝试模型发现: {url}")

        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        async with httpx.AsyncClient(timeout=self.timeout, headers=headers) as client:
            response = await client.get(url)
            response.raise_for_status()

            data = response.json()
            debug_logger.debug(f"收到响应: {data}")

            return self._parse_response(data, endpoint)

    def _parse_response(self, data: Dict[str, Any], source_endpoint: str) -> ModelInfo:
        """
        解析 API 响应

        Args:
            data: API 响应数据
            source_endpoint: 来源端点

        Returns:
            ModelInfo: 模型信息
        """
        # 尝试多种响应格式
        models = []

        # OpenAI 格式: {"data": [{"id": "xxx", ...}, ...]}
        if "data" in data and isinstance(data["data"], list):
            models = data["data"]

        # 简化格式: {"id": "xxx", ...}
        elif "id" in data:
            models = [data]

        # 数组格式: [...]
        elif isinstance(data, list):
            models = data

        # 查找匹配的模型
        target_model = None
        for model in models:
            model_id = model.get("id", "")
            if self.model_name and self.model_name.lower() in model_id.lower():
                target_model = model
                break

        if not target_model and models:
            # 如果没有精确匹配，使用第一个
            target_model = models[0] if models else {}

        if not target_model:
            return ModelInfo(
                status=DiscoveryStatus.FAILED,
                error_message="未找到模型信息",
            )

        # 提取 context_window
        context_window = self._extract_context_window(target_model)

        # 提取模型名称
        model_name = target_model.get("id", self.model_name or "unknown")

        # 计算建议值
        return self._calculate_suggestions(model_name, context_window, source_endpoint)

    def _extract_context_window(self, model: Dict[str, Any]) -> int:
        """
        从模型信息中提取 context_window

        Args:
            model: 模型信息字典

        Returns:
            int: context_window 值
        """
        for field_name in self.CONTEXT_WINDOW_FIELDS:
            if field_name in model:
                value = model[field_name]
                if isinstance(value, (int, float)):
                    return int(value)

        # 尝试在 created_by 或其他嵌套字段中查找
        for key, value in model.items():
            if isinstance(value, dict):
                result = self._extract_context_window(value)
                if result > 0:
                    return result

        known_context = self._lookup_known_context_window(model)
        if known_context > 0:
            debug_logger.info(f"使用已知模型上下文窗口: {known_context}")
            return known_context

        # 返回默认值
        debug_logger.warning("未找到 context_window，使用默认值 32768")
        return 32768

    def _lookup_known_context_window(self, model: Dict[str, Any]) -> int:
        candidates = [
            str(model.get("id", "") or ""),
            str(model.get("model", "") or ""),
            str(model.get("name", "") or ""),
            str(self.model_name or ""),
        ]
        for candidate in candidates:
            normalized = "".join(ch.lower() for ch in candidate if ch.isalnum() or ch in {".", "_", "-"})
            if not normalized:
                continue
            for key, value in self.KNOWN_CONTEXT_WINDOWS.items():
                if key in normalized:
                    return int(value)
        return 0

    def _calculate_suggestions(
        self,
        model_name: str,
        context_window: int,
        source_endpoint: str,
    ) -> ModelInfo:
        """
        根据 context_window 计算建议值

        Args:
            model_name: 模型名称
            context_window: 上下文窗口大小
            source_endpoint: 来源端点

        Returns:
            ModelInfo: 包含建议值的模型信息
        """
        # 计算 suggested_max_tokens
        # 规则：预留 12.5% 给输出（1/8），最多不超过 8192
        # 这样 32768 * 0.125 = 4096，与默认配置一致
        suggested_max_tokens = int(context_window * (1/8))
        suggested_max_tokens = min(suggested_max_tokens, 8192)
        suggested_max_tokens = max(suggested_max_tokens, 512)  # 最少 512

        # 计算压缩阈值
        # 规则：max_token_limit = context_window * 0.5（保留 50% 给压缩后内容）
        max_token_limit = int(context_window * 0.5)

        # 各阈值比例保持不变，但绝对值随 context_window 调整
        # 摘要字数按比例增加，但不超过 2 倍
        base_ratio = max_token_limit / 16000  # 基准是 16000
        light_summary = min(int(500 * base_ratio), 1000)
        standard_summary = min(int(1000 * base_ratio), 2000)
        deep_summary = min(int(2000 * base_ratio), 4000)
        emergency_summary = min(int(3000 * base_ratio), 6000)

        compression_thresholds = CompressionThresholds(
            max_token_limit=max_token_limit,
            light_threshold=0.6,
            standard_threshold=0.8,
            deep_threshold=0.9,
            emergency_threshold=0.95,
            light_summary_chars=light_summary,
            standard_summary_chars=standard_summary,
            deep_summary_chars=deep_summary,
            emergency_summary_chars=emergency_summary,
        )

        debug_logger.info(
            f"模型发现成功: {model_name}\n"
            f"  - context_window: {context_window}\n"
            f"  - suggested_max_tokens: {suggested_max_tokens}\n"
            f"  - max_token_limit: {max_token_limit}\n"
            f"  - 摘要字数: light={light_summary}, standard={standard_summary}, "
            f"deep={deep_summary}, emergency={emergency_summary}"
        )

        return ModelInfo(
            model_name=model_name,
            max_model_len=context_window,
            suggested_max_tokens=suggested_max_tokens,
            provider="auto-discovered",
            status=DiscoveryStatus.SUCCESS,
            compression_thresholds=compression_thresholds,
            raw_response={"source_endpoint": source_endpoint},
        )

    def _create_skipped_info(self) -> ModelInfo:
        """创建跳过的信息"""
        return ModelInfo(
            status=DiscoveryStatus.SKIPPED,
            error_message="动态发现已禁用",
        )

    def _create_fallback_info(self) -> ModelInfo:
        """创建 fallback 信息"""
        max_model_len = 32768  # 默认值

        if self._fallback_max_token_limit:
            max_token_limit = self._fallback_max_token_limit
        else:
            max_token_limit = int(max_model_len * 0.5)

        if self._fallback_max_tokens:
            suggested_max_tokens = self._fallback_max_tokens
        else:
            suggested_max_tokens = min(int(max_model_len * 0.2), 4096)

        return ModelInfo(
            model_name=self.model_name or "unknown",
            max_model_len=max_model_len,
            suggested_max_tokens=suggested_max_tokens,
            provider="fallback",
            status=DiscoveryStatus.FAILED,
            error_message="动态发现失败，使用 fallback 值",
            compression_thresholds=CompressionThresholds(
                max_token_limit=max_token_limit,
            ),
        )


# ============================================================================
# 便捷函数
# ============================================================================

async def get_dynamic_model_config(
    api_base: str,
    model_name: Optional[str] = None,
    api_key: Optional[str] = None,
    fallback_max_tokens: Optional[int] = None,
    fallback_max_token_limit: Optional[int] = None,
    timeout: int = 30,
    enabled: bool = True,
) -> ModelInfo:
    """
    获取动态模型配置

    这是一个便捷函数，结合发现和 fallback 逻辑。

    Args:
        api_base: API 基础 URL
        model_name: 模型名称
        fallback_max_tokens: 备用 max_tokens
        fallback_max_token_limit: 备用 max_token_limit
        timeout: 超时时间
        enabled: 是否启用

    Returns:
        ModelInfo: 模型信息
    """
    discovery = ModelDiscovery(
        api_base=api_base,
        model_name=model_name,
        api_key=api_key,
        timeout=timeout,
        enabled=enabled,
    )

    if fallback_max_tokens or fallback_max_token_limit:
        discovery.set_fallback(fallback_max_tokens, fallback_max_token_limit)

    return await discovery.discover()


def discover_model_sync(
    api_base: str,
    model_name: Optional[str] = None,
    api_key: Optional[str] = None,
    fallback_max_tokens: Optional[int] = None,
    fallback_max_token_limit: Optional[int] = None,
    timeout: int = 30,
    enabled: bool = True,
) -> ModelInfo:
    """同步获取动态模型配置，供非 async 启动路径和旧调用方使用。"""
    import asyncio

    coroutine = get_dynamic_model_config(
        api_base=api_base,
        model_name=model_name,
        api_key=api_key,
        fallback_max_tokens=fallback_max_tokens,
        fallback_max_token_limit=fallback_max_token_limit,
        timeout=timeout,
        enabled=enabled,
    )
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    try:
        return loop.run_until_complete(coroutine)
    finally:
        close = getattr(coroutine, "close", None)
        if close is not None:
            close()
