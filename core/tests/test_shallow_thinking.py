import pytest

from lamtools_core.llm import ChatMessage, LLMRequest, LLMResponse, LLMStreamEvent, LLMToolCall
from lamtools_core.llm.shallow_thinking import (
    SHALLOW_THINKING_END,
    SHALLOW_THINKING_PROMPT,
    SHALLOW_THINKING_START,
    ShallowThinkingClient,
    extract_shallow_thinking,
)


def test_extract_shallow_thinking_removes_complete_marker_block():
    text = (
        f"{SHALLOW_THINKING_START}\n"
        "[已知信息与问题界定]\n用户需要一个短答。\n"
        "[逻辑与推理]\n先确认目标，再给结论。\n"
        f"{SHALLOW_THINKING_END}\n\n"
        "最终答案。"
    )

    extracted = extract_shallow_thinking(text)

    assert extracted.extracted is True
    assert extracted.thinking == "[已知信息与问题界定]\n用户需要一个短答。\n[逻辑与推理]\n先确认目标，再给结论。"
    assert extracted.content == "最终答案。"


def test_extract_shallow_thinking_keeps_incomplete_marker_text_visible():
    text = f"{SHALLOW_THINKING_START}\n[逻辑与推理]\n还没结束"

    extracted = extract_shallow_thinking(text)

    assert extracted.extracted is False
    assert extracted.thinking == ""
    assert extracted.content == text


def test_shallow_thinking_prompt_starts_with_strong_format_instruction():
    assert SHALLOW_THINKING_PROMPT.startswith(
        "你在必须先按照以下格式展示你的推理过程！！！\n\n# 任务\n"
    )
    assert (
        "# 任务\n"
        "shallow thinking 块是无论输出什么内容都必须先输出的固定前缀。\n"
        "先输出一个 shallow thinking 块，再继续正文、状态文字或工具调用。\n\n"
    ) in SHALLOW_THINKING_PROMPT
    assert (
        "# 执行顺序\n"
        "1. 先输出完整 shallow thinking 块。\n"
        "2. 再输出最终答案、状态文字，或继续工具调用流程。\n\n"
    ) in SHALLOW_THINKING_PROMPT
    assert (
        "# 不要省略\n"
        "问题很简单、只是继续上一轮、或需要调用工具时，也不要省略 shallow thinking 块。"
    ) in SHALLOW_THINKING_PROMPT
    assert (
        "# 任务\n"
        "shallow thinking 块是无论输出什么内容都必须先输出的固定前缀。\n"
        "先输出一个 shallow thinking 块，再继续正文、状态文字或工具调用。\n\n"
        "# 输出格式（MUST遵循）\n\n"
    ) in SHALLOW_THINKING_PROMPT
    assert (
        "# 输出格式（MUST遵循）\n\n"
        f"{SHALLOW_THINKING_START}\n"
        "[已知信息与问题界定]\n"
        "[逻辑与推理]\n"
        "[结论]\n"
        "[验证]\n"
        f"{SHALLOW_THINKING_END}"
    ) in SHALLOW_THINKING_PROMPT
    assert "简短" not in SHALLOW_THINKING_PROMPT
    assert "每次回复都必须先输出上面的 shallow thinking 块" not in SHALLOW_THINKING_PROMPT
    assert "如果需要调用工具，也必须先完整输出 shallow thinking 块" not in SHALLOW_THINKING_PROMPT


@pytest.mark.asyncio
async def test_shallow_thinking_client_injects_prompt_and_strips_complete_response():
    class RecordingClient:
        def __init__(self):
            self.requests = []

        async def complete(self, request):
            self.requests.append(request)
            return LLMResponse(
                content=(
                    f"{SHALLOW_THINKING_START}\n"
                    "[结论]\n需要保留为思考块。\n"
                    f"{SHALLOW_THINKING_END}\n"
                    "只把这句作为正文。"
                ),
                thinking="native summary",
            )

        async def stream(self, request):
            raise NotImplementedError

    inner = RecordingClient()
    client = ShallowThinkingClient(inner)

    response = await client.complete(LLMRequest(messages=[ChatMessage(role="user", content="hi")]))

    assert response.content == "只把这句作为正文。"
    assert response.thinking == "native summary\n\n[结论]\n需要保留为思考块。"
    assert len(inner.requests) == 1
    assert any(
        SHALLOW_THINKING_START in str(message.content)
        for message in inner.requests[0].messages
        if message.role == "system"
    )


@pytest.mark.asyncio
async def test_shallow_thinking_client_stream_converts_marker_block_to_thinking_delta():
    class StreamingClient:
        async def complete(self, request):
            raise NotImplementedError

        async def stream(self, request):
            chunks = [
                SHALLOW_THINKING_START[:10],
                SHALLOW_THINKING_START[10:] + "\n[验证]\n先验证。",
                f"\n{SHALLOW_THINKING_END}\n",
                "最终正文",
            ]
            for chunk in chunks:
                yield LLMStreamEvent(kind="content_delta", content=chunk)
            yield LLMStreamEvent(kind="done")

    client = ShallowThinkingClient(StreamingClient())

    events = [event async for event in client.stream(LLMRequest(messages=[ChatMessage(role="user", content="hi")]))]

    assert [(event.kind, event.content) for event in events] == [
        ("thinking_delta", "[验证]\n先验证。"),
        ("content_delta", "最终正文"),
        ("done", ""),
    ]


@pytest.mark.asyncio
async def test_shallow_thinking_client_stream_emits_thinking_before_preface_text():
    class StreamingClient:
        async def complete(self, request):
            raise NotImplementedError

        async def stream(self, request):
            yield LLMStreamEvent(kind="content_delta", content="我先处理这个任务。\n")
            yield LLMStreamEvent(
                kind="content_delta",
                content=(
                    f"{SHALLOW_THINKING_START}\n"
                    "[结论]\n先确认动作，再执行。\n"
                    f"{SHALLOW_THINKING_END}\n"
                    "现在开始。"
                ),
            )
            yield LLMStreamEvent(kind="done")

    client = ShallowThinkingClient(StreamingClient())

    events = [event async for event in client.stream(LLMRequest(messages=[ChatMessage(role="user", content="hi")]))]

    assert [(event.kind, event.content) for event in events] == [
        ("thinking_delta", "[结论]\n先确认动作，再执行。"),
        ("content_delta", "我先处理这个任务。\n现在开始。"),
        ("done", ""),
    ]


@pytest.mark.asyncio
async def test_shallow_thinking_client_complete_marks_missing_without_retry():
    tool_call = LLMToolCall(id="call-1", name="write_file", arguments={"path": "a.txt"})

    class RecordingClient:
        def __init__(self):
            self.requests = []
            self.calls = 0

        async def complete(self, request):
            self.requests.append(request)
            self.calls += 1
            return LLMResponse(tool_calls=[tool_call], finish_reason="tool_calls")

        async def stream(self, request):
            raise NotImplementedError

    inner = RecordingClient()
    client = ShallowThinkingClient(inner)

    response = await client.complete(LLMRequest(messages=[ChatMessage(role="user", content="hi")]))

    assert inner.calls == 1
    assert response.tool_calls == [tool_call]
    assert response.metadata == {"shallow_thinking_missing": True}
    assert all("previous response skipped shallow thinking" not in str(message.content) for message in inner.requests[0].messages)


@pytest.mark.asyncio
async def test_shallow_thinking_client_stream_marks_missing_without_retry():
    class StreamingClient:
        def __init__(self):
            self.calls = 0

        async def complete(self, request):
            raise NotImplementedError

        async def stream(self, request):
            self.calls += 1
            yield LLMStreamEvent(
                kind="tool_call_delta",
                metadata={"tool_calls_delta": [{"index": 0, "function": {"name": "write_file"}}]},
            )
            yield LLMStreamEvent(kind="done")

    inner = StreamingClient()
    client = ShallowThinkingClient(inner)

    events = [event async for event in client.stream(LLMRequest(messages=[ChatMessage(role="user", content="hi")]))]

    assert inner.calls == 1
    assert [(event.kind, event.content) for event in events] == [
        ("tool_call_delta", ""),
        ("done", ""),
    ]
    assert events[0].metadata["shallow_thinking_missing"] is True


@pytest.mark.asyncio
async def test_shallow_thinking_client_stream_flushes_incomplete_marker_as_content():
    class StreamingClient:
        async def complete(self, request):
            raise NotImplementedError

        async def stream(self, request):
            yield LLMStreamEvent(kind="content_delta", content=f"{SHALLOW_THINKING_START}\n未闭合")
            yield LLMStreamEvent(kind="done")

    client = ShallowThinkingClient(StreamingClient())

    events = [event async for event in client.stream(LLMRequest(messages=[ChatMessage(role="user", content="hi")]))]

    assert [(event.kind, event.content) for event in events] == [
        ("content_delta", f"{SHALLOW_THINKING_START}\n未闭合"),
        ("done", ""),
    ]
