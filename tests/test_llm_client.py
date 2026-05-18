from langchain_core.messages import AIMessage

from config import Settings
from core.orchestration.response_processor import ResponseProcessor
from core.llm.client import LLMClient
from core.llm.errors import classify_exception
from core.llm.recovery import plan_recovery
from core.llm.routing import attach_recovery_fallback, select_recovery_profile


def make_config(**kwargs):
    return Settings(None, **kwargs).config


def test_litellm_payload_prefixes_minimax_model():
    config = make_config(
        **{
            "llm.providers.default.kind": "minimax",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.minimaxi.com/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "MiniMax-M2.7",
        }
    )

    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload([{"role": "user", "content": "ping"}])

    assert payload["model"] == "minimax/MiniMax-M2.7"


def test_minimax_payload_converts_runtime_system_messages_after_first_to_user():
    config = make_config(
        **{
            "llm.providers.default.kind": "minimax",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.minimaxi.com/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "MiniMax-M2.7",
        }
    )

    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload(
        [
            {"role": "system", "content": "system prompt"},
            {"role": "system", "content": "## 外部任务输入\n开始自主进化"},
        ]
    )

    assert [item["role"] for item in payload["messages"]] == ["system", "user"]


def test_litellm_payload_prefixes_openai_compatible_local_model():
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
        }
    )

    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload([{"role": "user", "content": "ping"}])

    assert payload["model"] == "openai/qwen-32b-awq"


def test_openai_compatible_payload_prefixes_model_names_that_contain_slash():
    config = make_config(
        **{
            "llm.providers.default.kind": "siliconflow",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.siliconflow.cn/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "deepseek-ai/DeepSeek-V3",
        }
    )

    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload([{"role": "user", "content": "ping"}])

    assert payload["model"] == "openai/deepseek-ai/DeepSeek-V3"


def test_payload_does_not_double_prefix_litellm_qualified_model():
    config = make_config(
        **{
            "llm.providers.default.kind": "minimax",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.minimaxi.com/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "minimax/MiniMax-M2.7",
        }
    )

    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload([{"role": "user", "content": "ping"}])

    assert payload["model"] == "minimax/MiniMax-M2.7"


def test_deepseek_payload_preserves_reasoning_content_for_assistant_history():
    config = make_config(
        **{
            "llm.providers.default.kind": "deepseek",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.deepseek.com/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "deepseek-chat",
        }
    )

    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload(
        [
            AIMessage(
                content="",
                tool_calls=[{"id": "call_1", "name": "read_file", "args": {"path": "agent.py"}}],
                additional_kwargs={"reasoning_content": "先读文件再决定"},
            )
        ]
    )

    assert payload["messages"][0]["role"] == "assistant"
    assert payload["messages"][0]["reasoning_content"] == "先读文件再决定"
    assert payload["messages"][0]["tool_calls"][0]["id"] == "call_1"


def test_deepseek_payload_omits_explicit_tool_choice_in_thinking_mode():
    config = make_config(
        **{
            "llm.providers.default.kind": "deepseek",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.deepseek.com",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "deepseek-v4-pro",
        }
    )

    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload(
        [{"role": "user", "content": "ping"}],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read one file",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
    )

    assert "tools" in payload
    assert "tool_choice" not in payload


def test_invoke_preserves_reasoning_content_in_ai_message():
    config = make_config(
        **{
            "llm.providers.default.kind": "deepseek",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.deepseek.com/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "deepseek-chat",
        }
    )

    def backend(_payload):
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "已完成",
                        "reasoning_content": "先分析再作答",
                    }
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

    client = LLMClient(config=config, backend=backend)
    message = client.invoke([{"role": "user", "content": "hi"}])

    assert message.content == "已完成"
    assert message.additional_kwargs["reasoning_content"] == "先分析再作答"


def test_native_anthropic_payload_preserves_structured_content_blocks_by_default():
    config = make_config(
        **{
            "llm.providers.default.kind": "anthropic",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.anthropic.com",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "claude-3-5-sonnet-20241022",
        }
    )

    content = [{"type": "text", "text": "cached", "cache_control": {"type": "ephemeral"}}]
    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload([{"role": "system", "content": content}])

    assert payload["model"] == "anthropic/claude-3-5-sonnet-20241022"
    assert payload["messages"][0]["content"] == content


def test_openai_compatible_payload_flattens_structured_content_blocks():
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
        }
    )

    content = [{"type": "text", "text": "plain", "cache_control": {"type": "ephemeral"}}]
    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload([{"role": "system", "content": content}])

    assert payload["messages"][0]["content"] == "plain"


def test_openai_codex_model_uses_known_context_window():
    config = make_config(
        **{
            "llm.providers.default.kind": "openai",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.openai.com/v1",
            "llm.providers.default.context_window": 123456,
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.3-codex",
        }
    )

    client = LLMClient(config=config, backend=lambda payload: payload)

    assert client.resolved_spec.context_window == 400000


def test_openai_gpt_5_5_uses_known_context_window():
    config = make_config(
        **{
            "llm.providers.default.kind": "openai",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.openai.com/v1",
            "llm.providers.default.context_window": 123456,
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.5",
        }
    )

    client = LLMClient(config=config, backend=lambda payload: payload)

    assert client.resolved_spec.context_window == 1050000


def test_tool_schema_is_sanitized_before_payload():
    class ArgsSchema:
        @staticmethod
        def model_json_schema():
            return {
                "title": "Args",
                "type": "object",
                "$defs": {"Ignored": {"type": "string"}},
                "properties": {
                    "file path": {
                        "title": "Path",
                        "type": "string",
                        "description": "target",
                        "examples": ["a.py"],
                    }
                },
                "required": ["file path"],
            }

    class Tool:
        name = "read file!*"
        description = "x" * 2000
        args_schema = ArgsSchema

    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
        }
    )

    client = LLMClient(config=config, backend=lambda payload: payload)
    payload = client._build_payload([{"role": "user", "content": "read"}], tools=[Tool()])
    function = payload["tools"][0]["function"]

    assert function["name"] == "read_file"
    assert len(function["description"]) == 1024
    assert "title" not in function["parameters"]
    assert "$defs" not in function["parameters"]
    assert "examples" not in function["parameters"]["properties"]["file path"]


def test_stream_merges_tool_call_argument_deltas():
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
        }
    )
    chunks = [
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "function": {"name": "read_file", "arguments": "{\"path\""},
                            }
                        ]
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "function": {"arguments": ": \"agent.py\"}"},
                            }
                        ]
                    }
                }
            ]
        },
    ]

    client = LLMClient(config=config, backend=lambda payload: iter(chunks))
    streamed = list(client.stream([{"role": "user", "content": "read"}]))

    assert streamed[-1].tool_calls[0]["id"] == "call_1"
    assert streamed[-1].tool_calls[0]["name"] == "read_file"
    assert streamed[-1].tool_calls[0]["args"] == {"path": "agent.py"}
    assert all(not chunk.tool_calls for chunk in streamed[:-1])


def test_stream_chunks_merge_without_duplicate_tool_calls():
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
        }
    )
    chunks = [
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "function": {"name": "read_file", "arguments": "{\"path\""},
                            }
                        ]
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "function": {"arguments": ": \"agent.py\"}"},
                            }
                        ]
                    }
                }
            ]
        },
    ]

    client = LLMClient(config=config, backend=lambda payload: iter(chunks))
    full_chunk = None
    for chunk in client.stream([{"role": "user", "content": "read"}]):
        full_chunk = ResponseProcessor.merge_stream_chunk(full_chunk, chunk)

    assert len(full_chunk.tool_calls) == 1
    assert full_chunk.tool_calls[0]["id"] == "call_1"
    assert full_chunk.tool_calls[0]["name"] == "read_file"


def test_stream_events_expose_tool_calls_only_after_finalization():
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
        }
    )
    chunks = [
        {"choices": [{"delta": {"content": "读"}}]},
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "function": {"name": "read_file", "arguments": "{\"path\""},
                            }
                        ]
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "function": {"arguments": ": \"agent.py\"}"},
                            }
                        ]
                    }
                }
            ]
        },
    ]

    client = LLMClient(config=config, backend=lambda payload: iter(chunks))
    events = list(client.stream_events([{"role": "user", "content": "read"}]))

    assert [event.type for event in events] == ["text_delta", "tool_call_final", "done"]
    assert events[0].text == "读"
    assert events[1].tool_calls[0].id == "call_1"
    assert events[1].tool_calls[0].arguments == {"path": "agent.py"}


def test_stream_exposes_reasoning_deltas_without_polluting_content():
    config = make_config(
        **{
            "llm.providers.default.kind": "deepseek",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.deepseek.com/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "deepseek-chat",
        }
    )
    chunks = [
        {"choices": [{"delta": {"reasoning_content": "先看"}}]},
        {"choices": [{"delta": {"reasoning_content": "日志"}}]},
        {"choices": [{"delta": {"content": "结论"}}]},
    ]

    client = LLMClient(config=config, backend=lambda payload: iter(chunks))
    streamed = list(client.stream([{"role": "user", "content": "read"}]))

    assert streamed[0].content == ""
    assert streamed[0].additional_kwargs["reasoning_content_delta"] == "先看"
    assert streamed[1].additional_kwargs["reasoning_content_delta"] == "日志"
    assert streamed[2].content == "结论"


def test_stream_events_drop_incomplete_tool_calls_with_empty_name():
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
        }
    )
    chunks = [
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_empty",
                                "function": {"arguments": "{\"limit\": 10}"},
                            }
                        ]
                    }
                }
            ]
        }
    ]

    client = LLMClient(config=config, backend=lambda payload: iter(chunks))
    events = list(client.stream_events([{"role": "user", "content": "read"}]))

    assert [event.type for event in events] == ["done"]
    assert list(client.stream([{"role": "user", "content": "read"}])) == []


def test_transcript_replay_duplicate_tool_call_id_regression():
    config = make_config(
        **{
            "llm.providers.default.kind": "minimax",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.minimaxi.com/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "MiniMax-M2.7",
        }
    )
    chunks = [
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_function_8euvktt1r7y4_1",
                                "function": {"name": "get_git_status_summary_tool", "arguments": "{}"},
                            }
                        ]
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 1,
                                "id": "call_function_8euvktt1r7y4_2",
                                "function": {"arguments": "{\"limit\": 10}"},
                            }
                        ]
                    }
                }
            ]
        },
    ]

    client = LLMClient(config=config, backend=lambda payload: iter(chunks))
    full_chunk = None
    for chunk in client.stream([{"role": "user", "content": "开始自主进化"}]):
        full_chunk = ResponseProcessor.merge_stream_chunk(full_chunk, chunk)

    assert len(full_chunk.tool_calls) == 1
    assert full_chunk.tool_calls[0]["id"] == "call_function_8euvktt1r7y4_1"
    assert full_chunk.tool_calls[0]["name"] == "get_git_status_summary_tool"


def test_bad_request_wrapped_as_connection_error_is_protocol_error():
    error = Exception("APIConnectionError: MinimaxException - bad_request_error invalid params, chat content is empty (2013)")

    normalized = classify_exception(error)

    assert normalized.category == "empty_content_error"
    assert normalized.retryable is False


def test_duplicate_tool_call_error_classified_as_tool_protocol_error():
    error = Exception("invalid params, duplicate tool_call id: call_function_8euvktt1r7y4_1")

    normalized = classify_exception(error)

    assert normalized.category == "tool_protocol_error"
    assert normalized.retryable is False


def test_recovery_policy_disables_tools_for_tool_protocol_error():
    error = Exception("invalid params, duplicate tool_call id: call_function_8euvktt1r7y4_1")

    decision = plan_recovery(error, attempt=1, max_attempts=5)

    assert decision.category == "tool_protocol_error"
    assert decision.action == "disable_tools_and_retry_without_streaming"
    assert decision.disable_tools is True
    assert decision.disable_streaming is True
    assert decision.stop_current_turn is False


def test_recovery_policy_uses_longer_backoff_for_rate_limit():
    error = Exception("429 rate limit exceeded")

    decision = plan_recovery(error, attempt=2, max_attempts=5)

    assert decision.category == "rate_limit"
    assert decision.action == "retry_after_backoff"
    assert decision.wait_seconds == 20
    assert decision.stop_current_turn is False


def test_recovery_policy_requests_context_compression():
    error = Exception("maximum context length exceeded")

    decision = plan_recovery(error, attempt=1, max_attempts=5)

    assert decision.category == "context_length_error"
    assert decision.action == "compress_context"
    assert decision.request_context_compression is True
    assert decision.stop_current_turn is False


def test_recovery_routing_prefers_no_tool_non_streaming_profile():
    config = make_config(
        **{
            "llm.providers.default.kind": "minimax",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.minimaxi.com/v1",
            "llm.providers.plain.kind": "local",
            "llm.providers.plain.requires_api_key": False,
            "llm.providers.plain.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "MiniMax-M2.7",
            "llm.profiles.fallback_plain.provider_id": "plain",
            "llm.profiles.fallback_plain.model": "qwen-32b-awq",
            "llm.profiles.fallback_plain.streaming": False,
            "llm.profiles.fallback_plain.tool_calling_mode": "disabled",
        }
    )

    fallback = select_recovery_profile(
        config,
        current_profile_id="primary",
        action="disable_tools_and_retry_without_streaming",
    )

    assert fallback == "fallback_plain"


def test_recovery_decision_attaches_fallback_profile():
    config = make_config(
        **{
            "llm.providers.default.kind": "minimax",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://api.minimaxi.com/v1",
            "llm.providers.backup.kind": "local",
            "llm.providers.backup.requires_api_key": False,
            "llm.providers.backup.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "MiniMax-M2.7",
            "llm.profiles.fallback_backup.provider_id": "backup",
            "llm.profiles.fallback_backup.model": "qwen-32b-awq",
            "llm.profiles.fallback_backup.streaming": False,
            "llm.profiles.fallback_backup.tool_calling_mode": "disabled",
        }
    )
    decision = plan_recovery(
        Exception("invalid params, duplicate tool_call id: call_1"),
        attempt=1,
        max_attempts=5,
    )

    enriched = attach_recovery_fallback(
        decision,
        config=config,
        current_profile_id="primary",
    )

    assert enriched.fallback_profile_id == "fallback_backup"


def test_context_recovery_uses_larger_context_profile_only():
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.context_window": 32768,
            "llm.providers.large.kind": "local",
            "llm.providers.large.requires_api_key": False,
            "llm.providers.large.context_window": 131072,
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
            "llm.profiles.long_context.provider_id": "large",
            "llm.profiles.long_context.model": "qwen-plus",
        }
    )

    fallback = select_recovery_profile(
        config,
        current_profile_id="primary",
        action="compress_context",
    )

    current_window = config.llm.get_provider(config.llm.get_profile("primary").provider_id).context_window
    selected_window = config.llm.get_provider(config.llm.get_profile(fallback).provider_id).context_window
    assert fallback is not None
    assert selected_window > current_window
