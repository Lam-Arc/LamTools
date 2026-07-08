from __future__ import annotations

from pathlib import Path

from lamtools_core.llm import ChatMessage, LLMRequest
from lamtools_core.llm.profiles import (
    apply_thinking_payload,
    build_profiled_anthropic_request,
    build_profiled_openai_request,
    load_adapter_profiles_from_dirs,
    load_jsonc,
    normalize_anthropic_response_with_profile,
    normalize_response_with_profile,
    normalize_stream_chunk_with_profile,
    resolve_adapter_profile_from_profiles,
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
    assert done.kind == "done"
    assert done.usage is not None
    assert done.usage.total_tokens == 7


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
        "max_tokens": 100,
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
