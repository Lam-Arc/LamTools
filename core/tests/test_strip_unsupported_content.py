"""Tests for model capability content filtering in request payloads."""
from __future__ import annotations

import pytest

from lamtools_core.llm import ChatMessage, LLMRequest, LLMToolCall
from lamtools_core.llm.profiles import (
    build_profiled_openai_request,
    strip_unsupported_content,
)


def _image_block(url: str = "data:image/png;base64,AAAA") -> dict:
    return {"type": "image_url", "image_url": {"url": url, "detail": "auto"}}


def _text_block(text: str) -> dict:
    return {"type": "text", "text": text}


def test_strip_removes_image_blocks_for_text_model():
    messages = [
        {"role": "user", "content": [_text_block("hello"), _image_block(), _text_block("world")]},
    ]
    strip_unsupported_content(messages, "text")
    assert messages[0]["content"] == [_text_block("hello"), _text_block("world")]


def test_strip_keeps_image_blocks_for_multimodal_model():
    original = [_text_block("hello"), _image_block()]
    messages = [{"role": "user", "content": list(original)}]
    strip_unsupported_content(messages, "multimodal")
    assert messages[0]["content"] == original


def test_strip_noop_for_empty_or_unknown_capability():
    messages = [{"role": "user", "content": [_text_block("hi"), _image_block()]}]
    for cap in ("", "unknown"):
        strip_unsupported_content(messages, cap)
    # Nothing stripped for non-text capability.
    assert _image_block() in messages[0]["content"] or any(
        isinstance(p, dict) and p.get("type") == "image_url" for p in messages[0]["content"]
    )


def test_strip_replaces_all_image_message_with_empty_string():
    # A message that is ONLY an image becomes empty string (valid for providers).
    messages = [{"role": "user", "content": [_image_block()]}]
    strip_unsupported_content(messages, "text")
    assert messages[0]["content"] == ""


def test_strip_ignores_string_content_messages():
    messages = [{"role": "user", "content": "plain text message"}]
    strip_unsupported_content(messages, "text")
    assert messages[0]["content"] == "plain text message"


def test_strip_handles_non_list_messages_gracefully():
    messages = [{"role": "system", "content": "system"}, {"role": "user", "content": None}]
    # Should not raise.
    strip_unsupported_content(messages, "text")
    assert messages[1]["content"] is None


def test_build_profiled_openai_request_strips_images_for_text_capability():
    request = LLMRequest(
        messages=[
            ChatMessage(role="user", content=[_text_block("look"), _image_block()]),
        ],
        model="text-model",
    )
    profile = {"id": "openai-chat", "protocol": "openai-chat-completions"}
    result = build_profiled_openai_request(request, profile, capability="text")
    payload_messages = result["payload"]["messages"]
    content = payload_messages[0]["content"]
    assert isinstance(content, list)
    assert all(not (isinstance(p, dict) and p.get("type") == "image_url") for p in content)
    assert any(isinstance(p, dict) and p.get("type") == "text" for p in content)


def test_build_profiled_openai_request_keeps_images_for_multimodal_capability():
    request = LLMRequest(
        messages=[
            ChatMessage(role="user", content=[_text_block("look"), _image_block()]),
        ],
        model="mm-model",
    )
    profile = {"id": "openai-chat", "protocol": "openai-chat-completions"}
    result = build_profiled_openai_request(request, profile, capability="multimodal")
    content = result["payload"]["messages"][0]["content"]
    assert any(isinstance(p, dict) and p.get("type") == "image_url" for p in content)


def test_build_profiled_openai_request_default_capability_keeps_images():
    # Empty capability = unknown → conservative? No: only "text" strips.
    # Unknown models keep images (avoid surprising image loss).
    request = LLMRequest(
        messages=[ChatMessage(role="user", content=[_image_block()])],
        model="unknown-model",
    )
    profile = {"id": "openai-chat"}
    result = build_profiled_openai_request(request, profile, capability="")
    content = result["payload"]["messages"][0]["content"]
    assert any(isinstance(p, dict) and p.get("type") == "image_url" for p in content)
