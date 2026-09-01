from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

import lamtools_core.cli as cli_module
from lamtools_core.cli import CoreHttpLLMClient, LLMConfig
from lamtools_core.llm import ChatMessage, LLMRequest
from lamtools_core.llm.profiles import (
    apply_thinking_payload,
    build_profiled_anthropic_request,
    build_profiled_gemini_request,
    build_profiled_openai_request,
    build_profiled_responses_request,
    load_adapter_profiles_from_dirs,
    load_jsonc,
    normalize_gemini_response_with_profile,
    normalize_gemini_stream_event,
    normalize_anthropic_response_with_profile,
    normalize_response_with_profile,
    normalize_responses_response_with_profile,
    normalize_stream_chunk_with_profile,
    reasoning_off_supported,
    resolve_adapter_profile_from_profiles,
    update_provider_stream_state,
    finalize_provider_stream_state,
)


def test_load_jsonc_preserves_comment_like_text(tmp_path):
    path = Path(tmp_path) / "profile.jsonc"
    path.write_text(
        r'''
        {
          "id": "sample",
          "url": "https://example.com//v1",
          /* block comment */
          "text": "not /* a comment */",
        }
        ''',
        encoding="utf-8",
    )

    assert load_jsonc(path) == {
        "id": "sample",
        "url": "https://example.com//v1",
        "text": "not /* a comment */",
    }


def test_resolve_profile_from_extra_and_apply_thinking_payload(tmp_path):
    profile_dir = tmp_path / "profiles"
    profile_dir.mkdir()
    (profile_dir / "custom-gateway.jsonc").write_text(
        """
        {
          "id": "custom-gateway",
          "request": {
            "thinking": {
              "when_enabled": {
                "custom_thinking": {
                  "budget": "$thinking_budget"
                }
              }
            }
          }
        }
        """,
        encoding="utf-8",
    )
    profiles = load_adapter_profiles_from_dirs([profile_dir])

    profile = resolve_adapter_profile_from_profiles(
        profiles,
        api_type="openai",
        base_url="https://example.invalid/v1",
        provider_extra={"adapter_profile": "custom-gateway"},
    )
    payload: dict[str, object] = {}
    apply_thinking_payload(payload, profile=profile, thinking_budget=4321)

    assert profile["id"] == "custom-gateway"
    assert payload == {"custom_thinking": {"budget": 4321}}


def test_model_reasoning_override_refines_selected_profile():
    profiles = {
        "base": {
            "id": "base",
            "protocol": "openai-chat-completions",
            "reasoning": {"off_supported": True},
        }
    }
    resolved = resolve_adapter_profile_from_profiles(
        profiles,
        api_type="openai",
        base_url="https://gateway.example/v1",
        model_extra={
            "adapter_profile_id": "base",
            "reasoning": {"off_supported": False},
        },
    )

    assert resolved["reasoning"]["off_supported"] is False


def test_stream_chunk_uses_profile_paths():
    profile = {
        "stream_response": {
            "reasoning_delta": "data.reason",
            "content_delta": "data.text",
            "finish_reason": "data.done",
            "usage": "data.usage",
        }
    }

    thinking = normalize_stream_chunk_with_profile({"data": {"reason": "inspect"}}, profile)
    content = normalize_stream_chunk_with_profile({"data": {"text": "answer"}}, profile)
    done = normalize_stream_chunk_with_profile(
        {"data": {"done": "stop", "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7}}},
        profile,
    )

    assert thinking is not None
    assert thinking.kind == "thinking_delta"
    assert thinking.content == "inspect"
    assert content is not None
    assert content.kind == "content_delta"
    assert content.content == "answer"
    assert done is not None
    assert done.kind == "finish"
    assert done.finish_reason == "stop"
    assert done.usage is not None
    assert done.usage.total_tokens == 7


def test_stream_chunk_tool_call_delta_not_dropped_when_finish_reason_present():
    """A terminal chunk that carries BOTH the final tool_call arguments
    fragment AND finish_reason must yield a tool_call_delta event, not a
    done event.  Otherwise the last arguments fragment is silently lost
    and the tool-call JSON ends up truncated.

    Regression test for the bug that caused sub_agent calls to fail with
    ``arguments_parse_error`` when the provider (e.g. xfyun/GLM) sent the
    last arguments fragment alongside ``finish_reason=tool_calls``.
    """
    profile = {}  # empty profile → all defaults (choices.0.delta.tool_calls etc.)

    chunk = {
        "choices": [
            {
                "index": 0,
                "delta": {
                    "tool_calls": [
                        {
                            "index": 0,
                            "function": {"arguments": '"key": "value"}'},
                        }
                    ]
                },
                "finish_reason": "tool_calls",
            }
        ]
    }
    event = normalize_stream_chunk_with_profile(chunk, profile)

    assert event is not None
    assert event.kind == "tool_call_delta"
    assert event.metadata["tool_calls_delta"] == chunk["choices"][0]["delta"]["tool_calls"]


def test_stream_chunk_pure_finish_reason_yields_finish():
    """A finish reason ends generation but not the provider transport."""
    profile = {}

    chunk = {
        "choices": [
            {"index": 0, "delta": {}, "finish_reason": "stop"}
        ]
    }
    event = normalize_stream_chunk_with_profile(chunk, profile)

    assert event is not None
    assert event.kind == "finish"
    assert event.finish_reason == "stop"
    assert event.metadata["finish_reason"] == "stop"


def test_stream_chunk_preserves_usage_on_finish_event():
    event = normalize_stream_chunk_with_profile(
        {
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
        },
        {},
    )

    assert event is not None
    assert event.kind == "finish"
    assert event.usage is not None
    assert event.usage.prompt_tokens == 100
    assert event.usage.completion_tokens == 20


def test_stream_chunk_keeps_finish_reason_on_terminal_content_and_tool_deltas():
    content = normalize_stream_chunk_with_profile(
        {
            "choices": [{"delta": {"content": "OK"}, "finish_reason": "stop"}],
        },
        {},
    )
    tool = normalize_stream_chunk_with_profile(
        {
            "choices": [{
                "delta": {"tool_calls": [{"index": 0, "function": {"arguments": "}"}}]},
                "finish_reason": "tool_calls",
            }],
        },
        {},
    )

    assert content is not None
    assert content.kind == "content_delta"
    assert content.finish_reason == "stop"
    assert tool is not None
    assert tool.kind == "tool_call_delta"
    assert tool.finish_reason == "tool_calls"


def test_stream_chunk_keeps_inline_usage_on_terminal_content_delta():
    event = normalize_stream_chunk_with_profile(
        {
            "choices": [{"delta": {"content": "OK"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
        },
        {},
    )

    assert event is not None
    assert event.kind == "content_delta"
    assert event.finish_reason == "stop"
    assert event.usage is not None
    assert event.usage.total_tokens == 120


def test_non_stream_response_uses_profile_paths():
    profile = {
        "non_stream_response": {
            "content": "data.message.text",
            "reasoning": "data.message.reason",
            "tool_calls": "data.message.calls",
            "finish_reason": "data.finish",
            "usage": "data.tokens",
        }
    }
    response = {
        "data": {
            "message": {
                "text": "answer",
                "reason": "inspect",
                "calls": [{"id": "call-1", "function": {"name": "read_file"}}],
            },
            "finish": "tool_calls",
            "tokens": {"prompt_tokens": 5, "completion_tokens": 6, "total_tokens": 11},
        }
    }

    normalized = normalize_response_with_profile(response, profile)

    assert normalized == {
        "content": "answer",
        "thinking": "inspect",
        "tool_calls": [{"id": "call-1", "function": {"name": "read_file"}}],
        "finish_reason": "tool_calls",
        "usage": {"prompt_tokens": 5, "completion_tokens": 6, "total_tokens": 11},
    }


def test_build_profiled_openai_request_applies_endpoint_body_thinking_and_stream():
    profile = {
        "endpoint": "custom/chat",
        "request": {
            "body": {
                "custom_mode": "coding",
                "budget": "$thinking_budget",
            },
            "thinking": {
                "when_enabled": {
                    "custom_thinking": {
                        "budget": "$thinking_budget",
                    }
                }
            },
            "unsupported_fields": ["temperature"],
        },
    }

    assembled = build_profiled_openai_request(
        LLMRequest(
            messages=[ChatMessage(role="user", content="hello")],
            model="model-1",
            temperature=0.7,
            max_tokens=100,
        ),
        profile,
        stream=True,
        thinking_enabled=True,
        thinking_budget=2048,
    )

    assert assembled["endpoint"] == "/custom/chat"
    assert assembled["payload"] == {
        "model": "model-1",
        "messages": [{"role": "user", "content": "hello"}],
        "max_tokens": 100,
        "stream": True,
        "stream_options": {"include_usage": True},
        "custom_mode": "coding",
        "budget": 2048,
        "custom_thinking": {"budget": 2048},
    }


def test_anthropic_request_and_response_use_profile_paths():
    profile = {
        "endpoint": "messages",
        "request": {
            "thinking": {
                "when_enabled": {
                    "thinking": {
                        "type": "enabled",
                        "budget_tokens": "$thinking_budget",
                    }
                }
            }
        },
        "non_stream_response": {
            "content_blocks": "data.blocks",
            "usage": "data.usage",
        },
    }

    assembled = build_profiled_anthropic_request(
        [
            {"role": "system", "content": "system one"},
            {"role": "system", "content": "system two"},
            {"role": "user", "content": "hello"},
        ],
        profile,
        model="claude-test",
        max_tokens=100,
        temperature=0.2,
        thinking_enabled=True,
        thinking_budget=4096,
    )

    assert assembled["endpoint"] == "/messages"
    assert assembled["payload"] == {
        "model": "claude-test",
        "messages": [{"role": "user", "content": "hello"}],
        # Manual Anthropic thinking requires budget_tokens < max_tokens; the
        # builder expands an undersized legacy output ceiling to keep this
        # request valid.
        "max_tokens": 4097,
        "temperature": 0.2,
        "system": "system one\nsystem two",
        "thinking": {"type": "enabled", "budget_tokens": 4096},
    }

    normalized = normalize_anthropic_response_with_profile(
        {
            "data": {
                "blocks": [
                    {"type": "thinking", "thinking": "inspect"},
                    {"type": "text", "text": "answer"},
                ],
                "usage": {"input_tokens": 7, "output_tokens": 8},
            },
            "stop_reason": "end_turn",
        },
        profile,
    )

    assert normalized == {
        "content": "answer",
        "thinking": "inspect",
        "usage": {"prompt_tokens": 7, "completion_tokens": 8, "total_tokens": 15},
        "finish_reason": "end_turn",
        "provider_state": {
            "protocol": "anthropic-messages",
            "profile_id": "",
            "content_blocks": [
                {"type": "thinking", "thinking": "inspect"},
                {"type": "text", "text": "answer"},
            ],
        },
    }


def test_anthropic_request_converts_openai_image_url_content_blocks():
    assembled = build_profiled_anthropic_request(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "describe"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,AA==", "detail": "auto"},
                    },
                ],
            }
        ],
        {},
        model="claude-test",
        max_tokens=100,
        temperature=0.2,
    )

    assert assembled["payload"]["messages"] == [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "describe"},
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": "AA==",
                    },
                },
            ],
        }
    ]


def _builtin_profiles() -> dict[str, dict[str, object]]:
    profile_dir = Path(__file__).resolve().parents[1] / "config" / "llm_adapters"
    return load_adapter_profiles_from_dirs([profile_dir])


def _text_request(model: str) -> LLMRequest:
    return LLMRequest(
        messages=[
            ChatMessage(role="system", content="system"),
            ChatMessage(role="user", content="hello"),
        ],
        model=model,
        temperature=0.2,
        max_tokens=100,
    )


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("gpt-5", {"reasoning_effort": "medium"}),
        ("deepseek-chat", {"thinking": {"type": "enabled"}, "reasoning_effort": "high"}),
        ("glm-5", {"thinking": {"type": "enabled"}, "reasoning_effort": "high"}),
        ("kimi-k2", {"reasoning_effort": "high"}),
        ("qwen3", {"enable_thinking": True, "reasoning_effort": "medium"}),
        ("grok-4", {"reasoning_effort": "medium"}),
    ],
)
def test_builtin_openai_compatible_profiles_emit_final_reasoning_json(model, expected):
    profiles = _builtin_profiles()
    profile = resolve_adapter_profile_from_profiles(
        profiles,
        api_type="openai",
        base_url="https://gateway.example/v1",
        model_id=model,
    )

    assembled = build_profiled_openai_request(
        _text_request(model),
        profile,
        reasoning_level="high",
    )

    payload = assembled["payload"]
    assert {key: payload.get(key) for key in expected} == expected
    assert "reasoning" not in payload


def test_builtin_openai_and_responses_off_have_no_reasoning_field():
    profiles = _builtin_profiles()

    openai_profile = resolve_adapter_profile_from_profiles(
        profiles,
        api_type="openai",
        base_url="https://gateway.example/v1",
        model_id="gpt-5",
    )
    openai_payload = build_profiled_openai_request(
        _text_request("gpt-5"),
        openai_profile,
        reasoning_level="off",
    )["payload"]
    assert "reasoning_effort" not in openai_payload
    assert "thinking" not in openai_payload

    responses_profile = resolve_adapter_profile_from_profiles(
        profiles,
        api_type="responses",
        base_url="https://gateway.example/v1",
        model_id="gpt-5",
    )
    responses_payload = build_profiled_responses_request(
        _text_request("gpt-5"),
        responses_profile,
        reasoning_level="off",
    )["payload"]
    assert "reasoning" not in responses_payload
    assert "reasoning_effort" not in responses_payload


def test_builtin_responses_profile_uses_nested_reasoning_effort():
    profiles = _builtin_profiles()
    profile = resolve_adapter_profile_from_profiles(
        profiles,
        api_type="responses",
        base_url="https://gateway.example/v1",
        model_id="gpt-5",
    )

    assembled = build_profiled_responses_request(
        _text_request("gpt-5"),
        profile,
        reasoning_level="high",
    )

    assert assembled["endpoint"] == "/responses"
    assert assembled["payload"]["reasoning"] == {"effort": "medium"}
    assert "messages" not in assembled["payload"]
    assert assembled["payload"]["input"][0]["role"] == "developer"


def test_builtin_anthropic_profiles_emit_budget_or_adaptive_reasoning_json():
    profiles = _builtin_profiles()
    profile = resolve_adapter_profile_from_profiles(
        profiles,
        api_type="anthropic",
        base_url="https://api.anthropic.example",
        model_id="claude-3-5-sonnet",
    )
    assembled = build_profiled_anthropic_request(
        [message.to_dict() for message in _text_request("claude-3-5-sonnet").messages],
        profile,
        model="claude-3-5-sonnet",
        max_tokens=100,
        temperature=0.2,
        reasoning_level="high",
        thinking_budget=10000,
    )
    assert assembled["payload"]["thinking"] == {
        "type": "enabled",
        "budget_tokens": 8192,
    }

    adaptive = build_profiled_anthropic_request(
        [message.to_dict() for message in _text_request("claude-opus-4").messages],
        profiles["anthropic-adaptive"],
        model="claude-opus-4",
        max_tokens=100,
        temperature=0.2,
        reasoning_level="max",
    )
    assert adaptive["payload"]["thinking"] == {"type": "adaptive"}
    assert adaptive["payload"]["output_config"] == {"effort": "max"}

    disabled = build_profiled_anthropic_request(
        [message.to_dict() for message in _text_request("claude-3-5-sonnet").messages],
        profile,
        model="claude-3-5-sonnet",
        max_tokens=100,
        temperature=0.2,
        reasoning_level="off",
    )
    assert "thinking" not in disabled["payload"]


def test_anthropic_manual_thinking_is_valid_and_drops_sampling_controls():
    profiles = _builtin_profiles()
    profile = profiles["anthropic-messages"]

    assembled = build_profiled_anthropic_request(
        [message.to_dict() for message in _text_request("claude-haiku-4-5").messages],
        profile,
        model="claude-haiku-4-5",
        max_tokens=100,
        temperature=0.2,
        top_p=0.8,
        reasoning_level="light",
        thinking_budget=512,
    )

    assert assembled["payload"]["thinking"] == {
        "type": "enabled",
        "budget_tokens": 1024,
    }
    assert assembled["payload"]["max_tokens"] == 1025
    assert "temperature" not in assembled["payload"]
    assert "top_p" not in assembled["payload"]


def test_anthropic_model_generation_profiles_are_not_overbroad():
    profiles = _builtin_profiles()

    def resolve(model: str) -> str:
        return resolve_adapter_profile_from_profiles(
            profiles,
            api_type="anthropic",
            base_url="https://api.codex666ai.com",
            model_id=model,
        )["id"]

    assert resolve("claude-opus-4-6") == "anthropic-adaptive"
    assert resolve("claude-sonnet-5") == "anthropic-adaptive"
    assert resolve("claude-opus-5-thinking") == "anthropic-always-on"
    assert resolve("claude-haiku-4-5") == "anthropic-messages"

    adaptive_off = build_profiled_anthropic_request(
        [message.to_dict() for message in _text_request("claude-opus-4-6").messages],
        profiles["anthropic-adaptive"],
        model="claude-opus-4-6",
        max_tokens=100,
        temperature=0.2,
        reasoning_level="off",
    )["payload"]
    assert "thinking" not in adaptive_off
    assert "temperature" not in adaptive_off


def test_builtin_gemini_profiles_separate_25_flash_3_and_non_reasoning_models():
    profiles = _builtin_profiles()

    flash = resolve_adapter_profile_from_profiles(
        profiles,
        api_type="gemini",
        base_url="https://generativelanguage.googleapis.com",
        model_id="gemini-2.5-flash",
    )
    flash_high = build_profiled_gemini_request(
        _text_request("gemini-2.5-flash"), flash, reasoning_level="high"
    )["payload"]
    flash_off = build_profiled_gemini_request(
        _text_request("gemini-2.5-flash"), flash, reasoning_level="off"
    )["payload"]
    assert flash["id"] == "gemini-25-flash"
    assert flash_high["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 8192}
    assert flash_off["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 0}

    flash3 = resolve_adapter_profile_from_profiles(
        profiles,
        api_type="gemini",
        base_url="https://generativelanguage.googleapis.com",
        model_id="gemini-3-flash-preview",
    )
    flash3_payload = build_profiled_gemini_request(
        _text_request("gemini-3-flash-preview"), flash3, reasoning_level="light"
    )["payload"]
    assert flash3["id"] == "gemini-3-flash"
    assert flash3_payload["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "MINIMAL"}

    non_reasoning = resolve_adapter_profile_from_profiles(
        profiles,
        api_type="gemini",
        base_url="https://generativelanguage.googleapis.com",
        model_id="gemini-2.0-flash",
    )
    non_reasoning_payload = build_profiled_gemini_request(
        _text_request("gemini-2.0-flash"), non_reasoning, reasoning_level="max"
    )["payload"]
    assert non_reasoning["id"] == "gemini-non-reasoning"
    assert "thinkingConfig" not in non_reasoning_payload.get("generationConfig", {})


def test_builtin_gemini_profile_uses_native_contents_and_thinking_config():
    profiles = _builtin_profiles()
    profile = resolve_adapter_profile_from_profiles(
        profiles,
        api_type="gemini",
        base_url="https://generativelanguage.googleapis.com",
        model_id="gemini-2.5-pro",
    )
    assembled = build_profiled_gemini_request(
        _text_request("gemini-2.5-pro"),
        profile,
        reasoning_level="high",
    )

    assert assembled["endpoint"] == "/v1beta/models/gemini-2.5-pro:generateContent"
    assert assembled["payload"]["systemInstruction"] == {"parts": [{"text": "system"}]}
    assert assembled["payload"]["contents"] == [
        {"role": "user", "parts": [{"text": "hello"}]},
    ]
    assert assembled["payload"]["generationConfig"]["thinkingConfig"] == {
        "thinkingBudget": 8192,
    }
    assert "reasoning_effort" not in assembled["payload"]


def test_media_profile_never_injects_reasoning_fields():
    profiles = _builtin_profiles()
    profile = resolve_adapter_profile_from_profiles(
        profiles,
        api_type="gemini",
        base_url="https://generativelanguage.googleapis.com",
        model_id="gemini-3-pro-image",
    )
    assembled = build_profiled_gemini_request(
        _text_request("gemini-3-pro-image"),
        profile,
        thinking_enabled=True,
        reasoning_effort="high",
    )

    payload = assembled["payload"]
    assert profile["id"] == "gemini-media"
    assert "reasoning_effort" not in payload
    assert "reasoning" not in payload
    assert "thinking" not in payload
    assert "enable_thinking" not in payload
    assert "thinkingConfig" not in payload.get("generationConfig", {})


def test_gemini_empty_usage_metadata_is_absent():
    response = normalize_gemini_response_with_profile(
        {"candidates": [], "usageMetadata": {}},
        {},
    )
    assert response["usage"] is None
    assert normalize_gemini_stream_event({"usageMetadata": {}}, {}) is None


def test_legacy_profile_honors_reasoning_level_and_explicit_off():
    profile = {
        "request": {
            "thinking": {
                "when_enabled": {
                    "thinking": {"type": "enabled", "budget_tokens": "$thinking_budget"},
                },
            },
        },
    }

    high: dict[str, object] = {}
    apply_thinking_payload(
        high,
        profile=profile,
        thinking_budget=4321,
        reasoning_level="high",
    )
    assert high == {"thinking": {"type": "enabled", "budget_tokens": 4321}}

    off: dict[str, object] = {}
    apply_thinking_payload(
        off,
        profile=profile,
        thinking_budget=4321,
        reasoning_level="off",
    )
    assert off == {}


def test_client_forces_reasoning_off_when_model_does_not_support_thinking():
    config = LLMConfig(
        provider_name="gateway",
        provider_api_type="openai",
        base_url="https://gateway.example/v1",
        api_key="secret",
        model_record_id="plain-model",
        model_id="plain-model",
        display_name="Plain model",
        thinking_supported=False,
    )
    client = CoreHttpLLMClient(
        config=config,
        adapter_profile=_builtin_profiles()["openai-chat"],
        thinking_enabled=True,
        thinking_budget=10000,
        reasoning_level="high",
        max_tokens=100,
        temperature=0.2,
    )

    assembled = client._assemble_request(_text_request("plain-model"), stream=False)

    assert client.reasoning_level == "off"
    assert "reasoning_effort" not in assembled["payload"]
    assert "thinking" not in assembled["payload"]


def test_always_on_profile_reports_off_as_unsupported():
    assert reasoning_off_supported(_builtin_profiles()["glm"]) is False
    assert reasoning_off_supported(_builtin_profiles()["kimi"]) is False
    assert reasoning_off_supported(_builtin_profiles()["always-on"]) is False


def test_openai_provider_state_round_trips_only_for_the_same_model_and_profile():
    profile = {"id": "deepseek-chat", "protocol": "openai-chat-completions"}
    state = {
        "protocol": "openai-chat-completions",
        "profile_id": "deepseek-chat",
        "model": "deepseek-chat",
        "message_fields": {"reasoning_content": "opaque reasoning"},
    }
    request = LLMRequest(
        model="deepseek-chat",
        messages=[
            ChatMessage(role="user", content="continue"),
            ChatMessage(role="assistant", content="tool next", provider_state=state),
        ],
    )

    replayed = build_profiled_openai_request(request, profile)["payload"]["messages"]
    assert replayed[1]["reasoning_content"] == "opaque reasoning"

    wrong_model = build_profiled_openai_request(
        LLMRequest(model="other-model", messages=request.messages),
        profile,
    )["payload"]["messages"]
    assert "reasoning_content" not in wrong_model[1]


def test_anthropic_provider_state_and_tool_results_round_trip():
    profile = {"id": "anthropic-messages", "protocol": "anthropic-messages"}
    state = {
        "protocol": "anthropic-messages",
        "profile_id": "anthropic-messages",
        "model": "claude-test",
        "content_blocks": [
            {"type": "thinking", "thinking": "opaque", "signature": "sig"},
            {"type": "text", "text": "calling tools"},
            {"type": "tool_use", "id": "tool-1", "name": "one", "input": {"a": 1}},
            {"type": "tool_use", "id": "tool-2", "name": "two", "input": {"b": 2}},
        ],
    }
    payload = build_profiled_anthropic_request(
        [
            {"role": "user", "content": "run both"},
            {"role": "assistant", "content": "calling tools", "provider_state": state},
            {"role": "tool", "tool_call_id": "tool-1", "content": "one result"},
            {"role": "tool", "tool_call_id": "tool-2", "content": "two result"},
        ],
        profile,
        model="claude-test",
        max_tokens=100,
        temperature=0.2,
    )["payload"]

    assert payload["messages"][1] == {
        "role": "assistant",
        "content": state["content_blocks"],
    }
    assert payload["messages"][2] == {
        "role": "user",
        "content": [
            {"type": "tool_result", "tool_use_id": "tool-1", "content": "one result"},
            {"type": "tool_result", "tool_use_id": "tool-2", "content": "two result"},
        ],
    }
    assert "provider_state" not in str(payload)


def test_responses_provider_state_replaces_synthesized_assistant_items():
    profile = {"id": "openai-responses", "protocol": "openai-responses"}
    output = [
        {"type": "reasoning", "id": "reason-1", "summary": [{"type": "summary_text", "text": "opaque"}]},
        {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "call"}]},
        {"type": "function_call", "id": "fc-1", "call_id": "fc-1", "name": "lookup", "arguments": "{}"},
    ]
    state = {
        "protocol": "openai-responses",
        "profile_id": "openai-responses",
        "model": "gpt-5",
        "output": output,
    }
    request = LLMRequest(
        model="gpt-5",
        messages=[
            ChatMessage(role="user", content="lookup"),
            ChatMessage(role="assistant", content="call", provider_state=state),
            ChatMessage(role="tool", tool_call_id="fc-1", content="found"),
        ],
    )

    payload = build_profiled_responses_request(request, profile)["payload"]
    assert payload["input"] == [
        {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "lookup"}]},
        *output,
        {"type": "function_call_output", "call_id": "fc-1", "output": "found"},
    ]


def test_gemini_provider_state_restores_thought_signature_and_function_call():
    profile = {"id": "gemini", "protocol": "gemini-generative-language"}
    native_content = {
        "role": "model",
        "parts": [
            {"thought": True, "text": "opaque", "thoughtSignature": "sig"},
            {"functionCall": {"name": "lookup", "args": {"q": "x"}}, "thoughtSignature": "sig"},
        ],
    }
    request = LLMRequest(
        model="gemini-3-flash-preview",
        messages=[
            ChatMessage(role="user", content="lookup"),
            ChatMessage(
                role="assistant",
                content="calling",
                provider_state={
                    "protocol": "gemini-generative-language",
                    "profile_id": "gemini",
                    "model": "gemini-3-flash-preview",
                    "content": native_content,
                },
            ),
            ChatMessage(role="tool", name="lookup", content="result"),
        ],
    )

    payload = build_profiled_gemini_request(request, profile)["payload"]
    assert payload["contents"][1] == native_content


def test_provider_state_is_extracted_from_non_stream_responses():
    openai = normalize_response_with_profile(
        {"choices": [{"message": {"content": "ok", "reasoning_content": "opaque"}}]},
        {"id": "deepseek-chat"},
        model="deepseek-chat",
    )
    assert openai["provider_state"]["message_fields"] == {"reasoning_content": "opaque"}

    responses = normalize_responses_response_with_profile(
        {"output": [{"type": "reasoning", "id": "r1", "summary": []}]},
        {"id": "openai-responses"},
        model="gpt-5",
    )
    assert responses["provider_state"]["output"][0]["id"] == "r1"

    gemini = normalize_gemini_response_with_profile(
        {
            "candidates": [{
                "content": {"role": "model", "parts": [{"thought": True, "text": "opaque", "thoughtSignature": "sig"}]},
            }],
        },
        {"id": "gemini"},
        model="gemini-3-flash-preview",
    )
    assert gemini["provider_state"]["content"]["parts"][0]["thoughtSignature"] == "sig"


def test_stream_provider_state_accumulates_and_hides_text_only_snapshots():
    profile = {"id": "anthropic-messages"}
    state = update_provider_stream_state(
        None,
        {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": "a"}},
        profile=profile,
        protocol="anthropic-messages",
        model="claude-test",
    )
    state = update_provider_stream_state(
        state,
        {"type": "content_block_delta", "index": 0, "delta": {"type": "signature_delta", "signature": "sig"}},
        profile=profile,
        protocol="anthropic-messages",
        model="claude-test",
    )
    assert finalize_provider_stream_state(state)["content_blocks"][0]["signature"] == "sig"

    text_only = update_provider_stream_state(
        None,
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": "answer"}},
        profile=profile,
        protocol="anthropic-messages",
        model="claude-test",
    )
    assert finalize_provider_stream_state(text_only) is None


def _http_client_for_test(*, model: str = "deepseek-chat") -> CoreHttpLLMClient:
    profiles = _builtin_profiles()
    return CoreHttpLLMClient(
        config=LLMConfig(
            provider_name="gateway",
            provider_api_type="openai",
            base_url="https://gateway.example/v1",
            api_key="secret",
            model_record_id=model,
            model_id=model,
            display_name=model,
            thinking_supported=True,
            thinking_budget=10000,
        ),
        adapter_profile=profiles["deepseek-chat"],
        thinking_enabled=False,
        thinking_budget=10000,
        reasoning_level="off",
        max_tokens=100,
        temperature=0.2,
    )


@pytest.mark.asyncio
async def test_core_http_llm_client_complete_sends_profile_payload_and_keeps_provider_state(monkeypatch):
    requests: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [{
                    "message": {
                        "content": "answer",
                        "reasoning_content": "opaque",
                    },
                    "finish_reason": "stop",
                }],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            },
        )

    real_async_client = cli_module.httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(cli_module.httpx, "AsyncClient", client_factory)
    client = _http_client_for_test()

    response = await client.complete(_text_request("deepseek-chat"))

    assert requests[0]["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in requests[0]
    assert response.content == "answer"
    assert response.thinking == "opaque"
    assert response.usage is not None and response.usage.total_tokens == 5
    assert response.provider_state == {
        "protocol": "openai-chat-completions",
        "profile_id": "deepseek-chat",
        "model": "deepseek-chat",
        "message_fields": {"reasoning_content": "opaque"},
    }


@pytest.mark.asyncio
async def test_core_http_llm_client_stream_accumulates_state_and_emits_done_after_done_marker(monkeypatch):
    requests: list[dict[str, object]] = []
    sse = "\n".join([
        'data: {"choices":[{"delta":{"reasoning_content":"think"}}]}',
        'data: {"choices":[{"delta":{"content":"answer"}}]}',
        'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
        'data: {"choices":[],"usage":{"prompt_tokens":4,"completion_tokens":3,"total_tokens":7}}',
        "data: [DONE]",
        "",
    ])

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=sse.encode("utf-8"),
        )

    real_async_client = cli_module.httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(cli_module.httpx, "AsyncClient", client_factory)
    client = _http_client_for_test()

    events = [event async for event in client.stream(_text_request("deepseek-chat"))]

    assert [event.kind for event in events] == [
        "thinking_delta",
        "content_delta",
        "finish",
        "usage",
        "done",
    ]
    assert requests[0]["stream"] is True
    assert events[-1].provider_state["message_fields"] == {"reasoning_content": "think"}
    assert events[-1].provider_state["model"] == "deepseek-chat"
    assert events[3].usage is not None and events[3].usage.total_tokens == 7


@pytest.mark.asyncio
async def test_core_http_llm_client_does_not_replay_provider_state_after_model_switch(monkeypatch):
    requests: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    real_async_client = cli_module.httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(cli_module.httpx, "AsyncClient", client_factory)
    client = _http_client_for_test()
    state = {
        "protocol": "openai-chat-completions",
        "profile_id": "deepseek-chat",
        "model": "deepseek-chat",
        "message_fields": {"reasoning_content": "must-not-leak"},
    }
    request = LLMRequest(
        model="other-model",
        messages=[
            ChatMessage(role="user", content="continue"),
            ChatMessage(role="assistant", content="previous", provider_state=state),
        ],
    )

    await client.complete(request)

    assert "reasoning_content" not in requests[0]["messages"][1]
