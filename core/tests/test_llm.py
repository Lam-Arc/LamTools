"""Tests for lamtools_core.llm module."""

from lamtools_core.llm import (
    ChatMessage,
    LLMClient,
    LLMClientProtocol,
    LLMRequest,
    LLMResponse,
    LLMStreamEvent,
    LLMToolCall,
    LLMUsage,
    merge_system_messages,
    sum_usage,
)
from lamtools_core.llm.retry import classify_model_error


class TestLLMTypes:
    def test_llm_tool_call_construction(self):
        tc = LLMToolCall(id="tc1", name="lookup_item", arguments={"item_id": "a"})
        assert tc.id == "tc1"
        assert tc.name == "lookup_item"
        assert tc.arguments == {"item_id": "a"}
        assert tc.raw is None

    def test_llm_tool_call_to_dict(self):
        tc = LLMToolCall(id="tc1", name="lookup_item", arguments={"item_id": "a"})
        d = tc.to_dict()
        assert d["id"] == "tc1"
        assert d["name"] == "lookup_item"
        assert d["arguments"] == {"item_id": "a"}

    def test_llm_tool_call_metadata_to_dict(self):
        tc = LLMToolCall(id="tc1", name="lookup_item", metadata={"source": "provider"})
        d = tc.to_dict()
        assert d["metadata"] == {"source": "provider"}

    def test_chat_message_construction(self):
        msg = ChatMessage(role="user", content="hello")
        assert msg.role == "user"
        assert msg.content == "hello"
        assert msg.tool_calls == []
        assert msg.metadata == {}

    def test_chat_message_with_tool_calls(self):
        tc = LLMToolCall(id="tc1", name="search", arguments={"q": "test"})
        msg = ChatMessage(role="assistant", content="", tool_calls=[tc])
        d = msg.to_dict()
        assert d["role"] == "assistant"
        assert len(d["tool_calls"]) == 1
        assert d["tool_calls"][0]["name"] == "search"

    def test_llm_usage(self):
        u = LLMUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30)
        d = u.to_dict()
        assert d["prompt_tokens"] == 10
        assert d["total_tokens"] == 30

    def test_llm_request_construction(self):
        req = LLMRequest(
            messages=[ChatMessage(role="user", content="hi")],
            model="test-model",
            temperature=0.7,
            max_tokens=100,
        )
        d = req.to_dict()
        assert d["model"] == "test-model"
        assert d["temperature"] == 0.7
        assert d["max_tokens"] == 100
        assert len(d["messages"]) == 1

    def test_llm_request_optional_fields_omitted(self):
        req = LLMRequest(messages=[])
        d = req.to_dict()
        assert "temperature" not in d
        assert "max_tokens" not in d
        assert "tools" not in d

    def test_llm_response_construction(self):
        resp = LLMResponse(content="world", finish_reason="stop", metadata={"provider": "fake"})
        d = resp.to_dict()
        assert d["content"] == "world"
        assert d["finish_reason"] == "stop"
        assert d["metadata"] == {"provider": "fake"}

    def test_llm_stream_event(self):
        evt = LLMStreamEvent(kind="content_delta", content="hello", metadata={"index": 1})
        d = evt.to_dict()
        assert d["kind"] == "content_delta"
        assert d["content"] == "hello"
        assert d["metadata"] == {"index": 1}

    def test_llm_client_protocol_is_runtime_checkable(self):
        assert isinstance("not_a_client", LLMClientProtocol) is False
        assert LLMClient is LLMClientProtocol


class TestMergeSystemMessages:
    def test_merge_consecutive_system(self):
        msgs = [
            ChatMessage(role="system", content="a"),
            ChatMessage(role="system", content="b"),
            ChatMessage(role="user", content="c"),
        ]
        result = merge_system_messages(msgs)
        assert len(result) == 2
        assert result[0].content == "a\nb"
        assert result[0].role == "system"
        assert result[1].role == "user"

    def test_no_merge_non_system(self):
        msgs = [
            ChatMessage(role="user", content="a"),
            ChatMessage(role="user", content="b"),
        ]
        result = merge_system_messages(msgs)
        assert len(result) == 2

    def test_empty_list(self):
        assert merge_system_messages([]) == []


class TestSumUsage:
    def test_sum_multiple(self):
        u1 = LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        u2 = LLMUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30)
        result = sum_usage([u1, u2])
        assert result.prompt_tokens == 30
        assert result.completion_tokens == 15
        assert result.total_tokens == 45


class TestClassifyModelError:
    """classify_model_error determines whether an error should be retried.

    Configuration errors (unknown model, etc.) must be classified as
    ``"fatal"`` so the retry loops bail out immediately instead of
    retrying 100 times — the bug that caused sub_agent calls with
    ``model="null"`` to stall for minutes before failing.
    """

    def test_model_not_found_is_fatal(self):
        exc = ValueError("model not found: null")
        assert classify_model_error(exc) == "fatal"

    def test_unknown_model_is_fatal(self):
        exc = ValueError("unknown model: some-bogus-id")
        assert classify_model_error(exc) == "fatal"

    def test_token_overflow_not_retried(self):
        exc = RuntimeError("context length exceeded")
        assert classify_model_error(exc) == "token_overflow"

    def test_rate_limit_is_retryable(self):
        exc = RuntimeError("rate limit exceeded (429)")
        assert classify_model_error(exc) == "rate_limit"

    def test_generic_error_is_retryable(self):
        exc = RuntimeError("connection reset")
        assert classify_model_error(exc) == "retryable"

    def test_structured_4xx_is_fatal(self):
        """4xx client errors must never be retried (audit 10 S2) — a bad API
        key or malformed request will not fix itself."""
        from lamtools_core.kernel.errors import LLMProviderError

        for status in (400, 401, 403, 404, 405, 422):
            assert classify_model_error(LLMProviderError(f"LLM API error {status}: boom", status)) == "fatal"

    def test_structured_5xx_is_retryable(self):
        from lamtools_core.kernel.errors import LLMProviderError

        for status in (500, 502, 503, 504):
            assert classify_model_error(LLMProviderError(f"LLM API error {status}: boom", status)) == "retryable"

    def test_structured_429_is_rate_limit_with_retry_after(self):
        from lamtools_core.kernel.errors import RateLimitError

        assert classify_model_error(RateLimitError("LLM API error 429: slow down", retry_after=5)) == "rate_limit"

    def test_structured_408_is_retryable(self):
        from lamtools_core.kernel.errors import LLMProviderError

        assert classify_model_error(LLMProviderError("LLM API error 408: timeout", 408)) == "retryable"
