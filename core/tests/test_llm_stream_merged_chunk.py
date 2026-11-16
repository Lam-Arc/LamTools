"""同一 SSE chunk 同时携带正文与思考/工具时，正文不能被丢掉。

user:“查询 constant 近期日志，有时会丢失回复开头的部分信息，请确认为 sunday 侧原因还是
API 侧原因”+(OpenAI 兼容网关会把思考尾部与第一段正文、或把整段旁白与 tool_call 合并进
同一个 chunk。规范化层如果一个 chunk 只产出一个事件，正文就会被静默丢弃，表现就是回复
开头缺几个字，或者整段「旁白」消失，只剩后面的内容)。
"""

from __future__ import annotations

import json

import httpx
import pytest

from lamtools_core.llm import ChatMessage, LLMRequest
from lamtools_core.llm import http_client as http_client_module
from lamtools_core.llm.http_client import CoreHttpLLMClient, LLMConfig
from lamtools_core.llm.profiles import (
    normalize_stream_chunk_events_with_profile,
    normalize_stream_chunk_with_profile,
)


def _merged(*, content: str = "", reasoning: str = "", tool: bool = False) -> dict:
    delta: dict[str, object] = {}
    if content:
        delta["content"] = content
    if reasoning:
        delta["reasoning_content"] = reasoning
    if tool:
        delta["tool_calls"] = [
            {
                "index": 0,
                "id": "call_merged",
                "type": "function",
                "function": {"name": "query_build", "arguments": ""},
            }
        ]
    return {"choices": [{"index": 0, "delta": delta}]}


def test_merged_reasoning_and_content_chunk_keeps_both() -> None:
    events = normalize_stream_chunk_events_with_profile(
        _merged(content="现在", reasoning="然后调用工具。"), {}
    )

    assert [event.kind for event in events] == ["thinking_delta", "content_delta"]
    assert events[0].content == "然后调用工具。"
    assert events[1].content == "现在"


def test_merged_content_and_tool_call_chunk_keeps_content_before_tool() -> None:
    events = normalize_stream_chunk_events_with_profile(
        _merged(content="查询 build 的构建状态。", tool=True), {}
    )

    assert [event.kind for event in events] == ["content_delta", "tool_call_delta"]
    assert events[0].content == "查询 build 的构建状态。"
    assert events[1].metadata["tool_calls_delta"][0]["function"]["name"] == "query_build"


def test_merged_chunk_carries_usage_and_finish_reason_once() -> None:
    chunk = _merged(content="查询构建状态。", reasoning="先说明动作。", tool=True)
    chunk["choices"][0]["finish_reason"] = "tool_calls"
    chunk["usage"] = {"prompt_tokens": 5, "completion_tokens": 6, "total_tokens": 11}

    events = normalize_stream_chunk_events_with_profile(chunk, {})

    assert [event.kind for event in events] == [
        "thinking_delta",
        "content_delta",
        "tool_call_delta",
    ]
    carrying_usage = [event for event in events if event.usage is not None]
    carrying_finish = [event for event in events if event.finish_reason]
    assert len(carrying_usage) == 1
    assert carrying_usage[0].usage.total_tokens == 11
    assert [event.finish_reason for event in carrying_finish] == ["tool_calls"]


def test_single_event_normalizer_keeps_legacy_priority() -> None:
    """一次只取一个事件的老入口保持原有优先级，避免影响既有调用方。"""

    chunk = _merged(content="查询构建状态。", tool=True)

    event = normalize_stream_chunk_with_profile(chunk, {})

    assert event is not None
    assert event.kind == "tool_call_delta"


def test_single_event_normalizer_still_returns_content_for_plain_chunk() -> None:
    event = normalize_stream_chunk_with_profile(_merged(content="纯正文。"), {})

    assert event is not None
    assert event.kind == "content_delta"
    assert event.content == "纯正文。"


def _client() -> CoreHttpLLMClient:
    return CoreHttpLLMClient(
        config=LLMConfig(
            provider_name="gateway",
            provider_id="gateway",
            provider_api_type="openai",
            base_url="https://gateway.example/v1",
            **{"api_key": "test"},
            model_record_id="deepseek-chat",
            model_id="deepseek-chat",
            display_name="deepseek-chat",
            thinking_supported=True,
            thinking_budget=10000,
        ),
        adapter_profile={"id": "deepseek-chat", "protocol": "openai-chat-completions"},
        thinking_enabled=False,
        thinking_budget=10000,
        reasoning_level="off",
        max_tokens=100,
        temperature=0.2,
    )


def _request() -> LLMRequest:
    return LLMRequest(
        messages=[ChatMessage(role="user", content="检查构建状态")],
        model="deepseek-chat",
        temperature=0.2,
        max_tokens=100,
    )


@pytest.mark.asyncio
async def test_client_stream_keeps_every_content_segment_of_merged_chunks(monkeypatch) -> None:
    """端到端：同一份 SSE 字节，供应商写下的正文必须完整到达调用方。"""

    sse = "\n".join(
        [
            'data: {"choices":[{"delta":{"reasoning_content":"先想一下。"}}]}',
            'data: {"choices":[{"delta":{"content":"现在","reasoning_content":"调用工具。"}}]}',
            'data: {"choices":[{"delta":{"content":"查询构建状态。","tool_calls":'
            '[{"index":0,"id":"call_1","type":"function","function":{"name":"query_build","arguments":""}}]}}]}',
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\\"topic\\":\\"build\\"}"}}]}}]}',
            'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}',
            "data: [DONE]",
            "",
        ]
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=sse.encode("utf-8"),
        )

    real_async_client = http_client_module.httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(http_client_module.httpx, "AsyncClient", client_factory)
    client = _client()

    events = [event async for event in client.stream(_request())]
    content = "".join(event.content for event in events if event.kind == "content_delta")
    thinking = "".join(event.content for event in events if event.kind == "thinking_delta")

    assert content == "现在查询构建状态。"
    assert thinking == "先想一下。调用工具。"
    kinds = [event.kind for event in events]
    assert kinds.index("tool_call_delta") > kinds.index("content_delta")
    assert kinds[-2:] == ["finish", "done"]
