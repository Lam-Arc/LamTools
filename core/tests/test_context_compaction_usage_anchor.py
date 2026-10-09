"""Tests for provider-usage-anchored compaction measurement."""

from __future__ import annotations

from dataclasses import replace

import pytest

from lamtools_core.context_compaction import (
    USAGE_ANCHOR_SOURCE,
    build_usage_anchor,
    describe_request,
    effective_prompt_tokens,
    measure_with_usage_anchor,
    message_prefix_digest,
    request_overhead_digest,
)
from lamtools_core.llm import ChatMessage, LLMRequest, LLMToolCall
from lamtools_core.tokens import estimate_message_tokens


def _request(
    messages: list[ChatMessage],
    *,
    model: str = "model-a",
    tools: list[dict] | None = None,
    response_format: dict | None = None,
) -> LLMRequest:
    return LLMRequest(
        messages=list(messages),
        model=model,
        tools=list(tools or []),
        response_format=response_format,
    )


def _anchored_request(
    messages: list[ChatMessage],
    *,
    prompt_tokens: int,
    model: str = "model-a",
    tools: list[dict] | None = None,
    response_format: dict | None = None,
) -> tuple[LLMRequest, dict]:
    request = _request(
        messages,
        model=model,
        tools=tools,
        response_format=response_format,
    )
    anchor = build_usage_anchor(
        describe_request(request),
        prompt_tokens=prompt_tokens,
        model_id=model,
    )
    assert anchor is not None
    return request, anchor


def _measure(
    messages: list[ChatMessage],
    anchor: dict,
    *,
    model: str = "model-a",
    trigger_tokens: int = 1_000_000,
    request: LLMRequest | None = None,
):
    reference = request or _request(messages, model=model)
    return measure_with_usage_anchor(
        messages,
        anchor,
        trigger_tokens=trigger_tokens,
        model_id=model,
        overhead_digest=request_overhead_digest(reference),
    )


def test_appended_tail_is_estimated_on_top_of_provider_count():
    messages = [
        ChatMessage(role="system", content="stable prefix"),
        ChatMessage(role="user", content="hello"),
    ]
    _, anchor = _anchored_request(messages, prompt_tokens=500_000)
    grown = [
        *messages,
        ChatMessage(role="assistant", content="ok"),
        ChatMessage(role="user", content="next request"),
    ]

    measurement = _measure(grown, anchor)

    assert measurement is not None
    assert measurement.source == USAGE_ANCHOR_SOURCE
    assert measurement.exact is True
    # The anchored bulk is provider truth; only the appended tail is estimated,
    # so the result stays within a small delta of the reported count.
    assert 500_000 <= measurement.tokens < 501_000
    # The local estimator sees only a handful of short messages — this is the
    # undercount the anchor exists to replace.
    local_only = estimate_message_tokens([message.to_dict() for message in grown])
    assert measurement.tokens > local_only * 100


def test_unchanged_request_measures_at_provider_count_exactly():
    messages = [ChatMessage(role="user", content="only message")]
    _, anchor = _anchored_request(messages, prompt_tokens=123_456)

    measurement = _measure(messages, anchor)

    assert measurement is not None
    assert measurement.tokens == 123_456


def test_anchor_over_trigger_skips_tail_estimation():
    messages = [ChatMessage(role="user", content="start")]
    _, anchor = _anchored_request(messages, prompt_tokens=900_000)
    grown = [*messages, ChatMessage(role="user", content="x" * 20_000)]

    measurement = _measure(grown, anchor, trigger_tokens=800_000)

    assert measurement is not None
    assert measurement.tokens == 900_000
    assert measurement.source == USAGE_ANCHOR_SOURCE


def test_changed_prefix_message_invalidates_anchor():
    messages = [
        ChatMessage(role="system", content="stable prefix"),
        ChatMessage(role="user", content="hello"),
    ]
    _, anchor = _anchored_request(messages, prompt_tokens=500_000)
    rewritten = [
        messages[0],
        ChatMessage(role="user", content="hello, but rewritten"),
    ]

    assert _measure(rewritten, anchor) is None


def test_shortened_history_invalidates_anchor():
    messages = [
        ChatMessage(role="system", content="stable prefix"),
        ChatMessage(role="user", content="hello"),
        ChatMessage(role="assistant", content="ok"),
    ]
    _, anchor = _anchored_request(messages, prompt_tokens=500_000)

    assert _measure(messages[:1], anchor) is None


def test_changed_tool_definitions_invalidate_anchor():
    messages = [ChatMessage(role="user", content="hello")]
    _, anchor = _anchored_request(messages, prompt_tokens=500_000)
    with_tools = _request(messages, tools=[{"type": "function", "function": {"name": "x"}}])

    assert _measure(messages, anchor, request=with_tools) is None


def test_changed_response_format_invalidates_anchor():
    messages = [ChatMessage(role="user", content="hello")]
    _, anchor = _anchored_request(messages, prompt_tokens=500_000)
    with_format = _request(messages, response_format={"type": "json_object"})

    assert _measure(messages, anchor, request=with_format) is None


def test_model_switch_invalidates_anchor():
    messages = [ChatMessage(role="user", content="hello")]
    _, anchor = _anchored_request(messages, prompt_tokens=500_000, model="model-a")

    assert _measure(messages, anchor, model="model-b") is None


def test_zero_prompt_usage_builds_no_anchor():
    request = _request([ChatMessage(role="user", content="hello")])

    assert build_usage_anchor(describe_request(request), prompt_tokens=0) is None
    assert build_usage_anchor(describe_request(request), prompt_tokens=0, cached_tokens=0) is None


def test_empty_request_builds_no_anchor():
    request = _request([])

    assert build_usage_anchor(describe_request(request), prompt_tokens=1_000) is None


def test_cache_reads_reported_outside_prompt_are_counted():
    # Anthropic-style: input_tokens excludes cache reads/creations.
    assert effective_prompt_tokens(
        prompt_tokens=100,
        cached_tokens=50_000,
        cache_creation_tokens=2_000,
    ) == 52_000
    # OpenAI-style: prompt_tokens already contains cache reads.
    assert effective_prompt_tokens(
        prompt_tokens=100_000,
        cached_tokens=50_000,
    ) == 100_000


def test_anchor_is_rebuilt_from_history_without_bookkeeping_metadata():
    """Metadata is stripped before dispatch and re-added on reload.

    Folding it into the digest would make every anchor recorded for a sent
    request unusable for the same message rebuilt from durable history.
    """
    sent = [
        ChatMessage(role="user", content="hello", metadata={"history_seq": 7}),
        ChatMessage(
            role="assistant",
            content="ok",
            tool_calls=[LLMToolCall(id="c1", name="read_file", arguments={"path": "a"})],
            metadata={"history_seq": 8},
        ),
    ]
    _, anchor = _anchored_request(sent, prompt_tokens=500_000)
    reloaded = [
        replace(message, metadata={}) for message in sent
    ]

    assert message_prefix_digest(sent) == message_prefix_digest(reloaded)
    measurement = _measure(reloaded, anchor)
    assert measurement is not None
    assert measurement.source == USAGE_ANCHOR_SOURCE


def test_malformed_anchor_is_ignored():
    messages = [ChatMessage(role="user", content="hello")]

    assert _measure(messages, {"prompt_tokens": "not-a-number"}) is None
    assert _measure(messages, {"message_count": 1}) is None
    assert _measure(messages, {"prompt_tokens": 10, "message_count": 0}) is None


@pytest.mark.parametrize("anchor", [None, {}, "not-a-mapping", 5])
def test_missing_anchor_never_measures(anchor):
    messages = [ChatMessage(role="user", content="hello")]

    assert _measure(messages, anchor) is None
