# -*- coding: utf-8 -*-
"""统一 LLM client。"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, Iterator, List, Optional

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, SystemMessage, ToolMessage

from config import AppConfig, get_config

from .adapters import get_provider_adapter
from .discovery import discover_model
from .errors import classify_exception
from .streaming import extract_message_tool_calls, extract_text_content
from .types import LLMCapabilities, LLMError, StreamChunk, UsageStats


def _default_completion_backend(payload: Dict[str, Any]) -> Any:
    try:
        from litellm import completion
    except Exception as exc:  # pragma: no cover
        raise LLMError(
            "configuration_error",
            "LiteLLM 未安装，无法执行模型调用；请安装 litellm",
            retryable=False,
        ) from exc
    return completion(**payload)


def _normalize_tool_calls(tool_calls: Any) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for index, raw_tool in enumerate(tool_calls or []):
        if isinstance(raw_tool, dict):
            function = raw_tool.get("function") if isinstance(raw_tool.get("function"), dict) else None
            if function is not None:
                normalized.append(
                    {
                        "id": str(raw_tool.get("id") or f"tool_{index}"),
                        "type": str(raw_tool.get("type") or "function"),
                        "function": {
                            "name": str(function.get("name") or ""),
                            "arguments": (
                                function.get("arguments")
                                if isinstance(function.get("arguments"), str)
                                else json.dumps(function.get("arguments") or {}, ensure_ascii=False)
                            ),
                        },
                    }
                )
                continue
            normalized.append(
                {
                    "id": str(raw_tool.get("id") or f"tool_{index}"),
                    "type": "function",
                    "function": {
                        "name": str(raw_tool.get("name") or ""),
                        "arguments": json.dumps(raw_tool.get("args") or {}, ensure_ascii=False),
                    },
                }
            )
            continue
        normalized.append(
            {
                "id": f"tool_{index}",
                "type": "function",
                "function": {"name": "", "arguments": "{}"},
            }
        )
    return normalized


def _message_to_openai_dict(
    message: Any,
    *,
    preserve_structured_content: bool = False,
    preserve_reasoning_content: bool = False,
) -> Dict[str, Any]:
    def content_value(value: Any) -> Any:
        if preserve_structured_content and isinstance(value, list):
            return value
        return extract_text_content(value)

    def maybe_attach_reasoning(payload: Dict[str, Any], value: Any) -> Dict[str, Any]:
        if not preserve_reasoning_content or payload.get("role") != "assistant":
            return payload
        reasoning_text = extract_text_content(value)
        if reasoning_text.strip():
            payload["reasoning_content"] = reasoning_text
        return payload

    if isinstance(message, SystemMessage):
        return {"role": "system", "content": content_value(message.content)}
    if isinstance(message, ToolMessage):
        payload = {"role": "tool", "content": content_value(message.content)}
        if getattr(message, "tool_call_id", None):
            payload["tool_call_id"] = message.tool_call_id
        return payload
    if isinstance(message, AIMessage):
        payload = {"role": "assistant", "content": content_value(message.content)}
        tool_calls = _normalize_tool_calls(getattr(message, "tool_calls", []) or [])
        if tool_calls:
            payload["tool_calls"] = tool_calls
        additional_kwargs = getattr(message, "additional_kwargs", None) or {}
        return maybe_attach_reasoning(payload, additional_kwargs.get("reasoning_content"))
    if isinstance(message, BaseMessage):
        return {"role": getattr(message, "type", "user"), "content": content_value(getattr(message, "content", ""))}
    if isinstance(message, dict):
        payload = {"role": str(message.get("role") or "user"), "content": content_value(message.get("content"))}
        if payload["role"] == "assistant":
            tool_calls = _normalize_tool_calls(message.get("tool_calls") or [])
            if tool_calls:
                payload["tool_calls"] = tool_calls
        if payload["role"] == "tool" and message.get("tool_call_id"):
            payload["tool_call_id"] = message.get("tool_call_id")
        reasoning = message.get("reasoning_content")
        if reasoning in (None, "") and isinstance(message.get("additional_kwargs"), dict):
            reasoning = message["additional_kwargs"].get("reasoning_content")
        return maybe_attach_reasoning(payload, reasoning)
    return {"role": "user", "content": content_value(message)}


def _tool_to_schema(tool: Any) -> Dict[str, Any]:
    if isinstance(tool, dict) and tool.get("type") == "function":
        return tool
    schema = getattr(tool, "args_schema", None)
    parameters = {"type": "object", "properties": {}, "required": []}
    if schema is not None and hasattr(schema, "model_json_schema"):
        parameters = schema.model_json_schema()
    return {
        "type": "function",
        "function": {
            "name": str(getattr(tool, "name", "")),
            "description": str(getattr(tool, "description", "")),
            "parameters": parameters,
        },
    }


class LLMClient:
    """项目统一 LLM client。"""

    def __init__(
        self,
        *,
        config: Optional[AppConfig] = None,
        role: str = "primary",
        profile_id: Optional[str] = None,
        bound_tools: Optional[List[Any]] = None,
        backend: Any = None,
    ) -> None:
        self.config = config or get_config()
        self.role = role
        self.profile_id = profile_id or self.config.llm.get_role_profile_id(role)
        self.profile = self.config.llm.get_profile(self.profile_id)
        self.provider = self.config.llm.get_provider(self.profile.provider_id)
        self.bound_tools = list(bound_tools or [])
        self._backend = backend or _default_completion_backend
        self.adapter = get_provider_adapter(self.provider, self.profile)
        self._resolved_spec = discover_model(self.config, self.profile_id)

    @property
    def capabilities(self) -> LLMCapabilities:
        return self._resolved_spec.capabilities

    @property
    def resolved_spec(self):
        return self._resolved_spec

    def bind_tools(self, tools: List[Any], *, binding_name: str = "default") -> "LLMClient":
        return LLMClient(
            config=self.config,
            role=self.role,
            profile_id=self.profile_id,
            bound_tools=list(tools or []),
            backend=self._backend,
        )

    def _build_payload(self, messages: List[Any], *, tools: Optional[List[Any]] = None, stream: bool = False) -> Dict[str, Any]:
        selected_tools = list(self.bound_tools)
        if tools is not None:
            selected_tools = list(tools or [])
        normalized_messages = [
            _message_to_openai_dict(
                item,
                preserve_structured_content=self.adapter.preserves_structured_content,
                preserve_reasoning_content=self.adapter.should_preserve_reasoning_content(),
            )
            for item in messages
        ]
        payload = {
            "model": self.adapter.litellm_model_name(),
            "messages": self.adapter.messages(normalized_messages),
            "temperature": self.profile.temperature,
            "max_tokens": self.profile.max_output_tokens,
            "timeout": self.profile.timeout,
            "stream": stream,
            "api_key": self.config.get_api_key_for_profile(profile_id=self.profile_id),
            "base_url": self.provider.base_url,
        }
        headers = self.provider.extra_headers or {}
        if headers:
            payload["extra_headers"] = headers
        if selected_tools:
            if not self.capabilities.supports_tool_calling:
                raise LLMError("capability_error", f"profile `{self.profile_id}` 不支持 tool calling", retryable=False)
            payload["tools"] = [
                self.adapter.sanitize_tool_schema(_tool_to_schema(tool))
                for tool in selected_tools
            ]
            payload["tool_choice"] = "auto"
        return payload

    def _usage_from_response(self, response: Any, latency_ms: int) -> UsageStats:
        usage = getattr(response, "usage", None)
        if usage is None and isinstance(response, dict):
            usage = response.get("usage")
        usage = usage or {}
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or usage.get("prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or usage.get("completion_tokens", 0) or 0)
        total_tokens = int(getattr(usage, "total_tokens", 0) or usage.get("total_tokens", 0) or (prompt_tokens + completion_tokens))
        return UsageStats(
            input_tokens=prompt_tokens,
            output_tokens=completion_tokens,
            total_tokens=total_tokens,
            provider_raw_usage=usage if isinstance(usage, dict) else dict(usage),
            estimated_cost=0.0,
            latency_ms=latency_ms,
        )

    def _choice_message(self, response: Any) -> Dict[str, Any]:
        if isinstance(response, dict):
            choices = response.get("choices") or []
            return (choices[0] or {}).get("message") or {}
        choices = getattr(response, "choices", None) or []
        if not choices:
            return {}
        choice = choices[0]
        message = getattr(choice, "message", None)
        if message is None and isinstance(choice, dict):
            message = choice.get("message")
        if hasattr(message, "model_dump"):
            return message.model_dump()
        if isinstance(message, dict):
            return message
        if message is not None:
            return {
                "role": getattr(message, "role", "assistant"),
                "content": getattr(message, "content", ""),
                "tool_calls": getattr(message, "tool_calls", []),
            }
        return {}

    def invoke(self, messages: List[Any], *, tools: Optional[List[Any]] = None, metadata: Optional[Dict[str, Any]] = None) -> AIMessage:
        start = time.time()
        payload = self._build_payload(messages, tools=tools, stream=False)
        try:
            response = self._backend(payload)
        except Exception as exc:
            raise classify_exception(exc) from exc
        latency_ms = int((time.time() - start) * 1000)
        message = self._choice_message(response)
        tool_calls = extract_message_tool_calls(message)
        usage = self._usage_from_response(response, latency_ms)
        additional_kwargs = {"tool_calls_raw": [call.provider_payload for call in tool_calls]}
        reasoning_content = extract_text_content(message.get("reasoning_content") or "")
        if reasoning_content.strip():
            additional_kwargs["reasoning_content"] = reasoning_content
        return AIMessage(
            content=extract_text_content(message.get("content") or ""),
            tool_calls=[
                {"id": call.id, "name": call.name, "args": call.arguments}
                for call in tool_calls
            ],
            response_metadata={
                "role": self.role,
                "profile_id": self.profile_id,
                "provider": self.provider.kind,
                "model": self.profile.model,
                "usage": usage.provider_raw_usage,
                "latency_ms": latency_ms,
                "capabilities": self.capabilities.__dict__,
                "metadata": metadata or {},
            },
            additional_kwargs=additional_kwargs,
        )

    def _response_metadata(self, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {
            "role": self.role,
            "profile_id": self.profile_id,
            "provider": self.provider.kind,
            "model": self.profile.model,
            "metadata": metadata or {},
        }

    def stream_events(
        self,
        messages: List[Any],
        *,
        tools: Optional[List[Any]] = None,
    ) -> Iterator[StreamChunk]:
        """Yield normalized stream events independent of LangChain chunks."""
        payload = self._build_payload(messages, tools=tools, stream=True)
        try:
            iterator = self._backend(payload)
        except Exception as exc:
            raise classify_exception(exc) from exc
        try:
            yield from self.adapter.stream_normalizer().events(iterator)
        except Exception as exc:
            raise classify_exception(exc) from exc

    def stream(self, messages: List[Any], *, tools: Optional[List[Any]] = None, metadata: Optional[Dict[str, Any]] = None) -> Iterator[AIMessageChunk]:
        response_metadata = self._response_metadata(metadata)
        for event in self.stream_events(messages, tools=tools):
            if event.type == "text_delta":
                yield AIMessageChunk(content=event.text, response_metadata=response_metadata)
            elif event.type == "reasoning_delta":
                yield AIMessageChunk(
                    content="",
                    additional_kwargs={"reasoning_content_delta": event.text},
                    response_metadata=response_metadata,
                )
            elif event.type == "tool_call_final" and event.tool_calls:
                yield AIMessageChunk(
                    content="",
                    tool_calls=[
                        {"id": call.id, "name": call.name, "args": call.arguments}
                        for call in event.tool_calls
                    ],
                    response_metadata=response_metadata,
                )


def get_llm_client(role: Optional[str] = None, profile_id: Optional[str] = None, *, config: Optional[AppConfig] = None) -> LLMClient:
    return LLMClient(config=config or get_config(), role=role or "primary", profile_id=profile_id)


def list_profiles(config: Optional[AppConfig] = None) -> List[str]:
    return sorted((config or get_config()).llm.profiles.keys())
