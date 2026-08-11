"""Tests for lamtools_core.llm.helpers module.

Covers helper functions with edge cases and realistic sample data.
"""

import json

import pytest

from lamtools_core.llm import (
    ChatMessage,
    LLMRequest,
    LLMResponse,
    LLMStreamEvent,
    LLMToolCall,
    LLMUsage,
)
from lamtools_core.llm.helpers import (
    build_openai_payload,
    chat_message_from_openai,
    extract_thinking_content,
    merge_tool_call_deltas,
    normalize_finish_reason,
    normalize_openai_response,
    normalize_stream_chunk,
    normalize_usage,
    parse_tool_call_arguments,
    resolve_tool_calls,
)


# ---------------------------------------------------------------------------
# normalize_finish_reason
# ---------------------------------------------------------------------------


class TestNormalizeFinishReason:
    def test_none_returns_stop(self):
        assert normalize_finish_reason(None) == "stop"

    def test_stop_passthrough(self):
        assert normalize_finish_reason("stop") == "stop"

    def test_tool_calls_passthrough(self):
        assert normalize_finish_reason("tool_calls") == "tool_calls"

    def test_length_passthrough(self):
        assert normalize_finish_reason("length") == "length"

    def test_content_filter_passthrough(self):
        assert normalize_finish_reason("content_filter") == "content_filter"

    def test_anthropic_end_turn_to_stop(self):
        assert normalize_finish_reason("end_turn") == "stop"

    def test_anthropic_tool_use_to_tool_calls(self):
        assert normalize_finish_reason("tool_use") == "tool_calls"

    def test_anthropic_max_tokens_to_length(self):
        assert normalize_finish_reason("max_tokens") == "length"

    def test_contains_error_maps_to_error(self):
        assert normalize_finish_reason("some_error") == "error"

    def test_strips_whitespace(self):
        assert normalize_finish_reason("  stop  ") == "stop"

    def test_unknown_non_empty_passthrough(self):
        assert normalize_finish_reason("custom_reason") == "custom_reason"


# ---------------------------------------------------------------------------
# parse_tool_call_arguments
# ---------------------------------------------------------------------------


class TestParseToolCallArguments:
    def test_valid_json(self):
        result = parse_tool_call_arguments('{"key": "value", "num": 1}')
        assert result == {"key": "value", "num": 1}

    def test_json_array_returns_empty(self):
        result = parse_tool_call_arguments('[1, 2, 3]')
        assert result == {}

    def test_empty_string_returns_empty(self):
        assert parse_tool_call_arguments("") == {}

    def test_whitespace_only_returns_empty(self):
        assert parse_tool_call_arguments("   ") == {}

    def test_invalid_json_returns_empty(self):
        assert parse_tool_call_arguments("not json") == {}

    def test_markdown_fence_with_json_tag(self):
        s = '```json\n{"key": "val"}\n```'
        assert parse_tool_call_arguments(s) == {"key": "val"}

    def test_markdown_fence_without_language_tag(self):
        s = '```\n{"a": 1}\n```'
        assert parse_tool_call_arguments(s) == {"a": 1}

    def test_markdown_fence_with_extra_whitespace(self):
        s = '```json  \n{"x": "y"}  \n```'
        assert parse_tool_call_arguments(s) == {"x": "y"}

    def test_none_argument(self):
        # pyright: ignore
        assert parse_tool_call_arguments(None) == {}  # type: ignore[arg-type]

    def test_complex_nested_json(self):
        s = json.dumps({"outer": {"inner": [1, 2, 3]}})
        assert parse_tool_call_arguments(s) == {"outer": {"inner": [1, 2, 3]}}


# ---------------------------------------------------------------------------
# extract_thinking_content
# ---------------------------------------------------------------------------


class TestExtractThinkingContent:
    def test_extracts_thinking_field(self):
        msg = {"thinking": "Let me think about this..."}
        assert extract_thinking_content(msg) == "Let me think about this..."

    def test_extracts_reasoning_content_field(self):
        msg = {"reasoning_content": "Step-by-step reasoning"}
        assert extract_thinking_content(msg) == "Step-by-step reasoning"

    def test_thinking_priority_over_reasoning(self):
        msg = {"thinking": "first", "reasoning_content": "second"}
        assert extract_thinking_content(msg) == "first"

    def test_empty_when_no_fields(self):
        assert extract_thinking_content({}) == ""

    def test_empty_when_think_is_empty_string(self):
        assert extract_thinking_content({"thinking": ""}) == ""

    def test_handles_non_string_thinking(self):
        msg = {"thinking": 42}
        assert extract_thinking_content(msg) == "42"


# ---------------------------------------------------------------------------
# normalize_usage
# ---------------------------------------------------------------------------


class TestNormalizeUsage:
    def test_usage_dict(self):
        usage = normalize_usage({"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12})
        assert usage is not None
        assert usage.prompt_tokens == 10
        assert usage.completion_tokens == 2
        assert usage.total_tokens == 12

    def test_usage_input_output_aliases(self):
        usage = normalize_usage({"input_tokens": 7, "output_tokens": 3})
        assert usage is not None
        assert usage.prompt_tokens == 7
        assert usage.completion_tokens == 3
        assert usage.total_tokens == 10

    def test_usage_object(self):
        class UsageObject:
            prompt_tokens = 5
            completion_tokens = 6
            total_tokens = 11

        usage = normalize_usage(UsageObject())
        assert usage is not None
        assert usage.prompt_tokens == 5
        assert usage.completion_tokens == 6
        assert usage.total_tokens == 11

    def test_empty_usage_returns_none(self):
        assert normalize_usage({}) is None

    def test_openai_nested_cached_tokens(self):
        usage = normalize_usage({
            "prompt_tokens": 1000,
            "completion_tokens": 50,
            "prompt_tokens_details": {"cached_tokens": 900},
        })
        assert usage is not None
        assert usage.cached_tokens == 900
        assert usage.cache_creation_tokens == 0

    def test_anthropic_top_level_cache_fields(self):
        usage = normalize_usage({
            "input_tokens": 1200,
            "output_tokens": 80,
            "cache_read_input_tokens": 1100,
            "cache_creation_input_tokens": 200,
        })
        assert usage is not None
        assert usage.cached_tokens == 1100
        assert usage.cache_creation_tokens == 200

    def test_deepseek_prompt_cache_hit_tokens(self):
        """DeepSeek reports cache reads as prompt_cache_hit_tokens at the
        top level of usage — these must count as cached_tokens."""
        usage = normalize_usage({
            "prompt_tokens": 1000,
            "completion_tokens": 50,
            "prompt_cache_hit_tokens": 800,
            "prompt_cache_miss_tokens": 200,
        })
        assert usage is not None
        assert usage.cached_tokens == 800

    def test_deepseek_prompt_cache_hit_tokens_round_trip(self):
        """normalize_usage(to_dict(normalize_usage(raw))) keeps the DeepSeek
        cache count across the kernel → projection boundary."""
        raw = {
            "prompt_tokens": 1000,
            "completion_tokens": 50,
            "prompt_cache_hit_tokens": 800,
            "prompt_cache_miss_tokens": 200,
        }
        first = normalize_usage(raw)
        assert first is not None
        round_tripped = normalize_usage(first.to_dict())
        assert round_tripped is not None
        assert round_tripped.cached_tokens == 800

    def test_flattened_cached_tokens_from_to_dict(self):
        """LLMUsage.to_dict() emits a flat cached_tokens key — normalize_usage
        should round-trip it so the kernel→projection path preserves cache data."""
        original = LLMUsage(prompt_tokens=500, completion_tokens=10, cached_tokens=480)
        round_tripped = normalize_usage(original.to_dict())
        assert round_tripped is not None
        assert round_tripped.cached_tokens == 480

    def test_to_dict_omits_zero_cache_fields(self):
        usage = LLMUsage(prompt_tokens=100, completion_tokens=5)
        d = usage.to_dict()
        assert "cached_tokens" not in d
        assert "cache_creation_tokens" not in d

    def test_to_dict_includes_cache_fields_when_present(self):
        usage = LLMUsage(prompt_tokens=100, completion_tokens=5, cached_tokens=90, cache_creation_tokens=10)
        d = usage.to_dict()
        assert d["cached_tokens"] == 90
        assert d["cache_creation_tokens"] == 10


# ---------------------------------------------------------------------------
# build_openai_payload
# ---------------------------------------------------------------------------


class TestBuildOpenaiPayload:
    def test_basic_request(self):
        req = LLMRequest(
            messages=[ChatMessage(role="user", content="hello")],
            model="gpt-4",
        )
        payload = build_openai_payload(req)
        assert payload["model"] == "gpt-4"
        assert len(payload["messages"]) == 1
        assert payload["messages"][0]["role"] == "user"
        assert payload["messages"][0]["content"] == "hello"

    def test_with_temperature_and_max_tokens(self):
        req = LLMRequest(
            messages=[],
            model="test",
            temperature=0.7,
            max_tokens=200,
            top_p=0.9,
        )
        payload = build_openai_payload(req)
        assert payload["temperature"] == 0.7
        assert payload["max_tokens"] == 200
        assert payload["top_p"] == 0.9

    def test_optional_fields_omitted(self):
        req = LLMRequest(messages=[])
        payload = build_openai_payload(req)
        assert "temperature" not in payload
        assert "max_tokens" not in payload
        assert "top_p" not in payload

    def test_with_tools(self):
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "search",
                    "description": "Search the web",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]
        req = LLMRequest(messages=[], model="test", tools=tools, tool_choice="auto")
        payload = build_openai_payload(req)
        assert payload["tools"] == tools
        assert payload["tool_choice"] == "auto"

    def test_tool_choice_none_omitted(self):
        req = LLMRequest(messages=[])
        payload = build_openai_payload(req)
        assert "tool_choice" not in payload

    def test_response_format_json_object(self):
        req = LLMRequest(
            messages=[],
            model="test",
            response_format={"type": "json_object"},
        )
        payload = build_openai_payload(req)
        assert payload["response_format"] == {"type": "json_object"}

    def test_stream_mode(self):
        req = LLMRequest(messages=[], model="test")
        payload = build_openai_payload(req, stream=True)
        assert payload["stream"] is True
        assert payload["stream_options"] == {"include_usage": True}

    def test_stream_mode_false_by_default(self):
        req = LLMRequest(messages=[], model="test")
        payload = build_openai_payload(req, stream=False)
        assert "stream" not in payload
        assert "stream_options" not in payload

    def test_assistant_message_with_tool_calls(self):
        tc = LLMToolCall(id="call_1", name="search", arguments={"q": "test"})
        msg = ChatMessage(role="assistant", content="", tool_calls=[tc])
        req = LLMRequest(messages=[msg], model="test")
        payload = build_openai_payload(req)

        msg_payload = payload["messages"][0]
        assert msg_payload["role"] == "assistant"
        assert len(msg_payload["tool_calls"]) == 1
        assert msg_payload["tool_calls"][0]["id"] == "call_1"
        assert msg_payload["tool_calls"][0]["type"] == "function"
        assert msg_payload["tool_calls"][0]["function"]["name"] == "search"
        assert msg_payload["tool_calls"][0]["function"]["arguments"] == '{"q": "test"}'

    def test_tool_message_with_tool_call_id(self):
        msg = ChatMessage(role="tool", content="result", tool_call_id="call_1")
        req = LLMRequest(messages=[msg], model="test")
        payload = build_openai_payload(req)

        msg_payload = payload["messages"][0]
        assert msg_payload["role"] == "tool"
        assert msg_payload["tool_call_id"] == "call_1"

    def test_message_with_name(self):
        msg = ChatMessage(role="user", content="hi", name="Alice")
        req = LLMRequest(messages=[msg], model="test")
        payload = build_openai_payload(req)

        msg_payload = payload["messages"][0]
        assert msg_payload["name"] == "Alice"


class TestChatMessageFromOpenai:
    def test_basic_message(self):
        msg = chat_message_from_openai({"role": "user", "content": "hello", "name": "Alice"})
        assert msg.role == "user"
        assert msg.content == "hello"
        assert msg.name == "Alice"

    def test_multimodal_content_passthrough(self):
        blocks = [{"type": "text", "text": "describe"}, {"type": "image_url", "image_url": {"url": "x"}}]
        msg = chat_message_from_openai({"role": "user", "content": blocks})
        assert msg.content == blocks

    def test_tool_calls_parse_arguments(self):
        msg = chat_message_from_openai({
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "call-1", "function": {"name": "search", "arguments": "{\"q\":\"cat\"}"}},
            ],
        })
        assert len(msg.tool_calls) == 1
        assert msg.tool_calls[0].id == "call-1"
        assert msg.tool_calls[0].name == "search"
        assert msg.tool_calls[0].arguments == {"q": "cat"}

    def test_tool_call_arguments_as_string_passthrough(self):
        tc = LLMToolCall(id="call_2", name="calc", arguments='{"a": 1}')
        msg = ChatMessage(role="assistant", content="", tool_calls=[tc])
        req = LLMRequest(messages=[msg], model="test")
        payload = build_openai_payload(req)

        tc_payload = payload["messages"][0]["tool_calls"][0]
        assert tc_payload["function"]["arguments"] == '{"a": 1}'


# ---------------------------------------------------------------------------
# normalize_openai_response
# ---------------------------------------------------------------------------


class TestNormalizeOpenaiResponse:
    def test_content_response(self):
        response = {
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Hello!"},
                    "finish_reason": "stop",
                }
            ],
        }
        result = normalize_openai_response(response)
        assert result.content == "Hello!"
        assert result.finish_reason == "stop"
        assert result.thinking == ""
        assert result.tool_calls == []

    def test_response_with_thinking(self):
        response = {
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "The answer is 42",
                        "reasoning_content": "Let me calculate...",
                    },
                    "finish_reason": "stop",
                }
            ],
        }
        result = normalize_openai_response(response)
        assert result.content == "The answer is 42"
        assert result.thinking == "Let me calculate..."

    def test_response_with_alternative_thinking_field(self):
        response = {
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "ok",
                        "thinking": "deep reasoning",
                    },
                    "finish_reason": "stop",
                }
            ],
        }
        result = normalize_openai_response(response)
        assert result.thinking == "deep reasoning"

    def test_response_with_tool_calls(self):
        response = {
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_abc",
                                "type": "function",
                                "function": {
                                    "name": "search",
                                    "arguments": '{"query": "test"}',
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
        }
        result = normalize_openai_response(response)
        assert result.finish_reason == "tool_calls"
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].id == "call_abc"
        assert result.tool_calls[0].name == "search"
        assert result.tool_calls[0].arguments == {"query": "test"}

    def test_response_with_usage(self):
        response = {
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Hi"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 2,
                "total_tokens": 12,
            },
        }
        result = normalize_openai_response(response)
        assert result.usage is not None
        assert result.usage.prompt_tokens == 10
        assert result.usage.completion_tokens == 2
        assert result.usage.total_tokens == 12

    def test_empty_choices_returns_default(self):
        response = {"choices": []}
        result = normalize_openai_response(response)
        assert result.content == ""
        assert result.finish_reason == "stop"
        assert result.usage is None

    def test_response_with_anthropic_finish_reason(self):
        response = {
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "done"},
                    "finish_reason": "end_turn",
                }
            ],
        }
        result = normalize_openai_response(response)
        assert result.finish_reason == "stop"

    def test_null_content_becomes_empty_string(self):
        response = {
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": None},
                    "finish_reason": "stop",
                }
            ],
        }
        result = normalize_openai_response(response)
        assert result.content == ""


# ---------------------------------------------------------------------------
# normalize_stream_chunk
# ---------------------------------------------------------------------------


class TestNormalizeStreamChunk:
    def test_content_delta(self):
        chunk = {
            "choices": [
                {"index": 0, "delta": {"content": "Hello"}, "finish_reason": None}
            ]
        }
        event = normalize_stream_chunk(chunk)
        assert event is not None
        assert event.kind == "content_delta"
        assert event.content == "Hello"

    def test_thinking_delta_from_reasoning_content(self):
        chunk = {
            "choices": [
                {
                    "index": 0,
                    "delta": {"reasoning_content": "Step 1..."},
                    "finish_reason": None,
                }
            ]
        }
        event = normalize_stream_chunk(chunk)
        assert event is not None
        assert event.kind == "thinking_delta"
        assert event.content == "Step 1..."

    def test_thinking_delta_from_thinking_field(self):
        chunk = {
            "choices": [
                {
                    "index": 0,
                    "delta": {"thinking": "deep"},
                    "finish_reason": None,
                }
            ]
        }
        event = normalize_stream_chunk(chunk)
        assert event is not None
        assert event.kind == "thinking_delta"
        assert event.content == "deep"

    def test_tool_call_delta(self):
        chunk = {
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_xyz",
                                "type": "function",
                                "function": {"name": "search", "arguments": '{"q": "'},
                            }
                        ]
                    },
                    "finish_reason": None,
                }
            ]
        }
        event = normalize_stream_chunk(chunk)
        assert event is not None
        assert event.kind == "tool_call_delta"

    def test_usage_event(self):
        chunk = {
            "choices": [
                {"index": 0, "delta": {}, "finish_reason": None}
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            },
        }
        event = normalize_stream_chunk(chunk)
        assert event is not None
        assert event.kind == "usage"
        assert event.usage is not None
        assert event.usage.total_tokens == 15

    def test_done_event(self):
        chunk = {
            "choices": [
                {"index": 0, "delta": {}, "finish_reason": "stop"}
            ]
        }
        event = normalize_stream_chunk(chunk)
        assert event is not None
        assert event.kind == "done"
        assert event.metadata["finish_reason"] == "stop"

    def test_error_event(self):
        chunk = {
            "error": {
                "message": "Rate limit exceeded",
                "type": "rate_limit_error",
            }
        }
        event = normalize_stream_chunk(chunk)
        assert event is not None
        assert event.kind == "error"
        assert "Rate limit" in event.error

    def test_empty_chunk_returns_none(self):
        chunk = {
            "choices": [
                {"index": 0, "delta": {}, "finish_reason": None}
            ]
        }
        event = normalize_stream_chunk(chunk)
        assert event is None

    def test_no_choices_returns_none(self):
        chunk = {"choices": []}
        event = normalize_stream_chunk(chunk)
        assert event is None

    def test_usage_takes_priority_over_delta(self):
        """Usage chunks may also have a delta (empty), usage should win."""
        chunk = {
            "choices": [
                {"index": 0, "delta": {"content": "x"}, "finish_reason": None}
            ],
            "usage": {"total_tokens": 100},
        }
        event = normalize_stream_chunk(chunk)
        assert event is not None
        assert event.kind == "usage"


# ---------------------------------------------------------------------------
# merge_tool_call_deltas
# ---------------------------------------------------------------------------


class TestMergeToolCallDeltas:
    def test_merge_first_chunk_with_id(self):
        accumulated: dict[int, dict] = {}
        chunk = {
            "object": "chat.completion.chunk",
            "choices": [{
                "index": 0,
                "delta": {
                    "tool_calls": [{
                        "index": 0,
                        "id": "call_abc",
                        "type": "function",
                        "function": {"name": "", "arguments": ""},
                    }]
                },
            }],
        }
        delta = chunk["choices"][0]["delta"]
        merged = merge_tool_call_deltas(accumulated, delta)
        assert merged[0]["id"] == "call_abc"
        assert "name" in merged[0]["function"]

    def test_merge_name_fragments(self):
        accumulated: dict[int, dict] = {}
        # Simulate first fragment: id arrives
        chunk1_delta = {
            "tool_calls": [{
                "index": 0,
                "id": "call_1",
                "type": "function",
                "function": {"name": "", "arguments": ""},
            }]
        }
        merge_tool_call_deltas(accumulated, chunk1_delta)

        # Second fragment: partial name
        chunk2_delta = {
            "tool_calls": [{
                "index": 0,
                "id": None,
                "type": None,
                "function": {"name": "sear", "arguments": ""},
            }]
        }
        merge_tool_call_deltas(accumulated, chunk2_delta)

        # Third fragment: rest of name
        chunk3_delta = {
            "tool_calls": [{
                "index": 0,
                "function": {"name": "ch", "arguments": ""},
            }]
        }
        merge_tool_call_deltas(accumulated, chunk3_delta)

        assert accumulated[0]["function"]["name"] == "search"

    def test_merge_arguments_fragments(self):
        accumulated: dict[int, dict] = {}
        chunk1_delta = {
            "tool_calls": [{
                "index": 0,
                "id": "call_x",
                "type": "function",
                "function": {"name": "calc", "arguments": '{"a":'},
            }]
        }
        merge_tool_call_deltas(accumulated, chunk1_delta)

        chunk2_delta = {
            "tool_calls": [{
                "index": 0,
                "function": {"arguments": "1"},
            }]
        }
        merge_tool_call_deltas(accumulated, chunk2_delta)

        assert accumulated[0]["function"]["arguments"] == '{"a":1'

    def test_multiple_tool_indices(self):
        accumulated: dict[int, dict] = {}
        chunk_delta = {
            "tool_calls": [
                {
                    "index": 0,
                    "id": "call_a",
                    "type": "function",
                    "function": {"name": "fn_a", "arguments": ""},
                },
                {
                    "index": 1,
                    "id": "call_b",
                    "type": "function",
                    "function": {"name": "fn_b", "arguments": ""},
                },
            ]
        }
        merge_tool_call_deltas(accumulated, chunk_delta)
        assert len(accumulated) == 2
        assert accumulated[0]["id"] == "call_a"
        assert accumulated[1]["id"] == "call_b"

    def test_delta_without_tool_calls_list(self):
        """Delta without explicit tool_calls list, using delta as tool call entry."""
        accumulated: dict[int, dict] = {}
        delta: dict[str, Any] = {
            "index": 2,
            "id": "call_z",
            "type": "function",
            "function": {"name": "tool_z", "arguments": "{}"},
        }
        merged = merge_tool_call_deltas(accumulated, delta)
        assert 2 in merged
        assert merged[2]["id"] == "call_z"
        assert merged[2]["function"]["name"] == "tool_z"


# ---------------------------------------------------------------------------
# resolve_tool_calls
# ---------------------------------------------------------------------------


class TestResolveToolCalls:
    def test_empty_accumulated(self):
        result = resolve_tool_calls({})
        assert result == []

    def test_single_tool_call(self):
        accumulated = {
            0: {
                "id": "call_1",
                "type": "function",
                "function": {"name": "search", "arguments": '{"q": "test"}'},
            }
        }
        result = resolve_tool_calls(accumulated)
        assert len(result) == 1
        assert result[0].id == "call_1"
        assert result[0].name == "search"
        assert result[0].arguments == {"q": "test"}
        assert "raw_arguments" in result[0].metadata

    def test_sorted_by_index(self):
        accumulated = {
            2: {
                "id": "c2",
                "type": "function",
                "function": {"name": "third", "arguments": "{}"},
            },
            0: {
                "id": "c0",
                "type": "function",
                "function": {"name": "first", "arguments": "{}"},
            },
            1: {
                "id": "c1",
                "type": "function",
                "function": {"name": "second", "arguments": "{}"},
            },
        }
        result = resolve_tool_calls(accumulated)
        assert len(result) == 3
        assert result[0].name == "first"
        assert result[1].name == "second"
        assert result[2].name == "third"

    def test_invalid_arguments_returns_empty_dict(self):
        accumulated = {
            0: {
                "id": "call_bad",
                "type": "function",
                "function": {"name": "bad", "arguments": "not json"},
            }
        }
        result = resolve_tool_calls(accumulated)
        assert len(result) == 1
        assert result[0].arguments == {}
        assert result[0].metadata["raw_arguments"] == "not json"

    def test_preserves_raw(self):
        accumulated = {
            0: {
                "id": "call_r",
                "type": "function",
                "function": {"name": "raw_tool", "arguments": '{"x": 1}'},
            }
        }
        result = resolve_tool_calls(accumulated)
        assert result[0].raw is accumulated[0]


# ---------------------------------------------------------------------------
# Regression: tool_call arguments truncated when final fragment shares a
# chunk with finish_reason (profiles.py path).  This simulates the full
# streaming flow: multiple delta chunks + a terminal chunk that carries
# both the last arguments fragment and finish_reason=tool_calls.
# ---------------------------------------------------------------------------


class TestStreamToolCallCompletion:
    def test_final_fragment_with_finish_reason_is_not_lost(self):
        """The terminal chunk sends the last arguments fragment together
        with finish_reason.  The merged result must be complete JSON."""
        accumulated: dict[int, dict] = {}

        # Chunk 1: tool call header + first half of arguments
        accumulated = merge_tool_call_deltas(accumulated, {
            "tool_calls": [{
                "index": 0,
                "id": "call_1",
                "type": "function",
                "function": {"name": "sub_agent", "arguments": '{"task": "do work", "agent": "worker", "model": null, "mode": "consider", "attachments":'},
            }]
        })

        # Chunk 2: terminal — last arguments fragment + finish_reason
        accumulated = merge_tool_call_deltas(accumulated, {
            "tool_calls": [{
                "index": 0,
                "function": {"arguments": ' null}'},
            }]
        })

        result = resolve_tool_calls(accumulated)
        assert len(result) == 1
        assert result[0].name == "sub_agent"
        # The full JSON must be parseable — no truncation
        assert result[0].arguments == {
            "task": "do work",
            "agent": "worker",
            "model": None,
            "mode": "consider",
            "attachments": None,
        }
        # No parse error
        assert not result[0].metadata.get("arguments_parse_error")
