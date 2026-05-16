#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
模型动态发现模块测试
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from core.infrastructure.model_discovery import (
    ModelDiscovery,
    ModelInfo,
    CompressionThresholds,
    DiscoveryStatus,
    discover_model_sync,
    get_dynamic_model_config,
)


class TestModelDiscovery:
    """ModelDiscovery 测试"""

    def test_init(self):
        """测试初始化"""
        discovery = ModelDiscovery(
            api_base="http://localhost:8000/v1",
            model_name="qwen-32b",
            timeout=30,
        )
        assert discovery.api_base == "http://localhost:8000/v1"
        assert discovery.model_name == "qwen-32b"
        assert discovery.timeout == 30
        assert discovery.enabled is True

    def test_init_disabled(self):
        """测试禁用状态"""
        discovery = ModelDiscovery(
            api_base="http://localhost:8000/v1",
            enabled=False,
        )
        assert discovery.enabled is False

    def test_set_fallback(self):
        """测试 fallback 设置"""
        discovery = ModelDiscovery(api_base="http://localhost:8000/v1")
        discovery.set_fallback(max_tokens=4096, max_token_limit=16000)

        assert discovery._fallback_max_tokens == 4096
        assert discovery._fallback_max_token_limit == 16000

    def test_extract_context_window_direct(self):
        """测试直接提取 context_window"""
        discovery = ModelDiscovery(api_base="http://localhost:8000/v1")
        model = {"id": "qwen-32b", "context_window": 32768}

        result = discovery._extract_context_window(model)
        assert result == 32768

    def test_extract_context_window_max_tokens(self):
        """测试提取 max_tokens"""
        discovery = ModelDiscovery(api_base="http://localhost:8000/v1")
        model = {"id": "qwen-32b", "max_tokens": 16384}

        result = discovery._extract_context_window(model)
        assert result == 16384

    def test_extract_context_window_context_length(self):
        """测试提取 context_length"""
        discovery = ModelDiscovery(api_base="http://localhost:8000/v1")
        model = {"id": "qwen-32b", "context_length": 8192}

        result = discovery._extract_context_window(model)
        assert result == 8192

    def test_extract_context_window_nested(self):
        """测试嵌套字段提取"""
        discovery = ModelDiscovery(api_base="http://localhost:8000/v1")
        model = {
            "id": "qwen-32b",
            "model_settings": {
                "context_window": 32768
            }
        }

        result = discovery._extract_context_window(model)
        assert result == 32768

    def test_extract_context_window_default(self):
        """测试默认值"""
        discovery = ModelDiscovery(api_base="http://localhost:8000/v1")
        model = {"id": "qwen-32b"}

        result = discovery._extract_context_window(model)
        assert result == 32768

    def test_extract_context_window_uses_known_minimax_window_when_field_missing(self):
        discovery = ModelDiscovery(
            api_base="https://api.minimaxi.com/v1",
            model_name="MiniMax-M2.7",
        )
        model = {"id": "MiniMax-M2.7"}

        result = discovery._extract_context_window(model)
        assert result == 204800

    def test_parse_response_openai_format(self):
        """测试解析 OpenAI 格式响应"""
        discovery = ModelDiscovery(
            api_base="http://localhost:8000/v1",
            model_name="qwen-32b"
        )
        data = {
            "data": [
                {"id": "qwen-32b-awq", "context_window": 32768},
                {"id": "qwen-plus", "context_window": 131072},
            ]
        }

        result = discovery._parse_response(data, "/v1/models")
        assert result.status == DiscoveryStatus.SUCCESS
        assert result.max_model_len == 32768
        assert result.suggested_max_tokens == 4096  # 32768 * 0.2

    def test_parse_response_simple_format(self):
        """测试解析简化格式"""
        discovery = ModelDiscovery(api_base="http://localhost:8000/v1")
        data = {"id": "llama-3-70b", "context_window": 8192}

        result = discovery._parse_response(data, "/models")
        assert result.status == DiscoveryStatus.SUCCESS
        assert result.max_model_len == 8192

    def test_parse_response_array_format(self):
        """测试解析数组格式"""
        discovery = ModelDiscovery(api_base="http://localhost:8000/v1")
        data = [
            {"id": "model-1", "context_window": 4096},
            {"id": "model-2", "context_window": 8192},
        ]

        result = discovery._parse_response(data, "/models")
        assert result.status == DiscoveryStatus.SUCCESS
        assert result.max_model_len == 4096

    def test_parse_response_not_found(self):
        """测试解析未找到模型"""
        discovery = ModelDiscovery(
            api_base="http://localhost:8000/v1",
            model_name="nonexistent"
        )
        data = {"data": [{"id": "other-model", "context_window": 4096}]}

        result = discovery._parse_response(data, "/v1/models")
        # 应该使用第一个模型
        assert result.status == DiscoveryStatus.SUCCESS

    def test_calculate_suggestions_large_context(self):
        """测试大上下文窗口计算"""
        discovery = ModelDiscovery(api_base="http://localhost:8000/v1")

        result = discovery._calculate_suggestions(
            model_name="qwen-max",
            context_window=131072,
            source_endpoint="/v1/models",
        )

        assert result.max_model_len == 131072
        # suggested_max_tokens = min(131072 * 0.2, 8192) = 8192
        assert result.suggested_max_tokens == 8192
        # max_token_limit = 131072 * 0.5 = 65536
        assert result.compression_thresholds.max_token_limit == 65536

    def test_calculate_suggestions_small_context(self):
        """测试小上下文窗口计算"""
        discovery = ModelDiscovery(api_base="http://localhost:8000/v1")

        result = discovery._calculate_suggestions(
            model_name="tiny-model",
            context_window=2048,
            source_endpoint="/v1/models",
        )

        assert result.max_model_len == 2048
        # suggested_max_tokens = min(2048 * 0.2, 8192) = 512
        assert result.suggested_max_tokens == 512
        # max_token_limit = 2048 * 0.5 = 1024
        assert result.compression_thresholds.max_token_limit == 1024
        # 摘要字数也会按比例缩小
        assert result.compression_thresholds.light_summary_chars < 500

    def test_calculate_suggestions_very_large_context(self):
        """测试超大上下文窗口（验证上限）"""
        discovery = ModelDiscovery(api_base="http://localhost:8000/v1")

        result = discovery._calculate_suggestions(
            model_name="claude-3-200k",
            context_window=200000,
            source_endpoint="/v1/models",
        )

        # suggested_max_tokens 上限 8192
        assert result.suggested_max_tokens == 8192
        # max_token_limit = 200000 * 0.5 = 100000
        assert result.compression_thresholds.max_token_limit == 100000
        # 摘要字数上限
        assert result.compression_thresholds.deep_summary_chars == 4000  # 上限

    def test_create_skipped_info(self):
        """测试创建跳过信息"""
        discovery = ModelDiscovery(api_base="http://localhost:8000/v1", enabled=False)
        result = discovery._create_skipped_info()

        assert result.status == DiscoveryStatus.SKIPPED
        assert "禁用" in result.error_message

    def test_create_fallback_info(self):
        """测试创建 fallback 信息"""
        discovery = ModelDiscovery(api_base="http://localhost:8000/v1")
        discovery.set_fallback(max_tokens=4096, max_token_limit=16000)

        result = discovery._create_fallback_info()

        assert result.status == DiscoveryStatus.FAILED
        assert "fallback" in result.error_message
        assert result.suggested_max_tokens == 4096

    def test_create_fallback_info_no_fallback(self):
        """测试无 fallback 值时的默认行为"""
        discovery = ModelDiscovery(api_base="http://localhost:8000/v1")
        # 不设置 fallback

        result = discovery._create_fallback_info()

        assert result.status == DiscoveryStatus.FAILED
        assert result.suggested_max_tokens == 4096  # min(32768 * 0.2, 4096)

    def test_to_dict(self):
        """测试 ModelInfo.to_dict()"""
        info = ModelInfo(
            model_name="test-model",
            max_model_len=32768,
            suggested_max_tokens=4096,
            provider="test",
            status=DiscoveryStatus.SUCCESS,
        )

        result = info.to_dict()

        assert result["model_name"] == "test-model"
        assert result["max_model_len"] == 32768
        assert result["suggested_max_tokens"] == 4096
        assert result["status"] == "success"
        assert "compression_thresholds" in result


class TestCompressionThresholds:
    """CompressionThresholds 测试"""

    def test_defaults(self):
        """测试默认值"""
        thresholds = CompressionThresholds()

        assert thresholds.max_token_limit == 16000
        assert thresholds.light_threshold == 0.6
        assert thresholds.standard_threshold == 0.8
        assert thresholds.deep_threshold == 0.9
        assert thresholds.emergency_threshold == 0.95

    def test_to_dict(self):
        """测试转换为字典"""
        thresholds = CompressionThresholds(
            max_token_limit=32768,
            light_threshold=0.5,
        )

        result = thresholds.to_dict()

        assert result["max_token_limit"] == 32768
        assert result["light_threshold"] == 0.5
        assert result["light_summary_chars"] == 500  # 默认值

    def test_custom_summary_chars(self):
        """测试自定义摘要字数"""
        thresholds = CompressionThresholds(
            max_token_limit=65536,
            light_summary_chars=1000,
            standard_summary_chars=2000,
        )

        assert thresholds.light_summary_chars == 1000
        assert thresholds.standard_summary_chars == 2000


@pytest.mark.asyncio
class TestAsyncDiscovery:
    """异步发现测试"""

    async def test_discover_disabled(self):
        """测试禁用时的发现"""
        discovery = ModelDiscovery(
            api_base="http://localhost:8000/v1",
            enabled=False,
        )

        result = await discovery.discover()

        assert result.status == DiscoveryStatus.SKIPPED

    async def test_discover_success(self):
        """测试成功发现"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {"id": "qwen-32b-awq", "context_window": 32768}
            ]
        }
        mock_response.raise_for_status = MagicMock()

        discovery = ModelDiscovery(
            api_base="http://localhost:8000/v1",
            model_name="qwen-32b",
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await discovery.discover()

            assert result.status == DiscoveryStatus.SUCCESS
            assert result.max_model_len == 32768
            assert result.suggested_max_tokens == 4096

    async def test_discover_sends_bearer_auth_header(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {"id": "MiniMax-M2.7"}
            ]
        }
        mock_response.raise_for_status = MagicMock()
        captured = {}

        class DummyClient:
            def __init__(self, *args, **kwargs):
                captured["headers"] = kwargs.get("headers") or {}

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, _url):
                return mock_response

        discovery = ModelDiscovery(
            api_base="https://api.minimaxi.com/v1",
            model_name="MiniMax-M2.7",
            api_key="demo-key",
        )

        with patch("httpx.AsyncClient", DummyClient):
            result = await discovery.discover()

        assert captured["headers"]["Authorization"] == "Bearer demo-key"
        assert result.max_model_len == 204800

    async def test_discover_all_endpoints_fail(self):
        """测试所有端点都失败"""
        discovery = ModelDiscovery(
            api_base="http://localhost:8000/v1",
            enabled=True,
        )
        discovery.set_fallback(max_tokens=2048)

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                side_effect=Exception("Connection failed")
            )

            result = await discovery.discover()

            assert result.status == DiscoveryStatus.FAILED
            assert result.suggested_max_tokens == 2048  # fallback


class TestConvenienceFunctions:
    """便捷函数测试"""

    def test_discover_model_sync(self):
        """测试同步版本"""
        with patch("asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value.run_until_complete = lambda x: ModelInfo(
                model_name="test",
                max_model_len=32768,
                suggested_max_tokens=4096,
                status=DiscoveryStatus.SUCCESS,
            )

            result = discover_model_sync(
                api_base="http://localhost:8000/v1",
                model_name="test",
            )

            assert result.model_name == "test"

    @pytest.mark.asyncio
    async def test_get_dynamic_model_config(self):
        """测试动态配置获取"""
        result = await get_dynamic_model_config(
            api_base="http://localhost:8000/v1",
            model_name="qwen-32b",
            api_key="demo-key",
            fallback_max_tokens=4096,
            fallback_max_token_limit=16000,
            enabled=False,
        )

        assert result.status == DiscoveryStatus.SKIPPED


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
