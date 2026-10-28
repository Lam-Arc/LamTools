"""OpenCode prompt-cache affinity header behavior."""

from __future__ import annotations

import pytest

from lamtools_core.llm import ChatMessage, LLMRequest
from lamtools_core.llm.http_client import CoreHttpLLMClient, LLMConfig


def _client(
    *,
    provider_name: str = "opencode-go",
    base_url: str = "https://opencode.ai/inference/go/v1",
) -> CoreHttpLLMClient:
    return CoreHttpLLMClient(
        config=LLMConfig(
            provider_name=provider_name,
            provider_api_type="openai",
            base_url=base_url,
            api_key="sk-test",
            model_record_id="opencode-go:test-model",
            model_id="test-model",
            display_name="test-model",
        ),
        adapter_profile={"id": "opencode", "protocol": "openai-chat-completions"},
        thinking_enabled=False,
        thinking_budget=0,
        max_tokens=128,
        temperature=0.2,
    )


def _request(**metadata: object) -> LLMRequest:
    return LLMRequest(
        messages=[ChatMessage(role="user", content="hello")],
        model="test-model",
        metadata=dict(metadata),
    )


def test_opencode_main_request_sends_its_session_id() -> None:
    headers = _client()._headers(_request(_runtime_session_id="main-session"))

    assert headers["x-opencode-session"] == "main-session"


def test_opencode_sub_agent_request_reuses_parent_session_id() -> None:
    headers = _client()._headers(
        _request(
            _runtime_session_id="main-session:sub:worker",
            _provider_session_affinity="main-session",
        )
    )

    assert headers["x-opencode-session"] == "main-session"


def test_opencode_child_request_without_explicit_affinity_derives_root() -> None:
    headers = _client()._headers(
        _request(_runtime_session_id="main-session:sub:worker:sub:reviewer")
    )

    assert headers["x-opencode-session"] == "main-session"


def test_opencode_parent_metadata_wins_over_child_runtime_session() -> None:
    headers = _client()._headers(
        _request(
            _runtime_session_id="main-session:sub:worker",
            parent_session_id="main-session",
        )
    )

    assert headers["x-opencode-session"] == "main-session"


def test_non_opencode_provider_does_not_send_opencode_session_header() -> None:
    headers = _client(
        provider_name="example",
        base_url="https://api.example.test/v1",
    )._headers(_request(_runtime_session_id="main-session"))

    assert "x-opencode-session" not in headers


def test_opencode_request_without_any_session_still_fails_locally() -> None:
    with pytest.raises(ValueError, match="stable conversation session ID"):
        _client()._headers(_request())
