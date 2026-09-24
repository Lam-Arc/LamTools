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
        "You must first show your reasoning in the following format!!!\n\n# Task\n"
    )
    assert (
        "# Task\n"
        "The shallow thinking block is a required prefix before any other output.\n"
        "Output one complete shallow thinking block before the main response, status text, or tool call.\n\n"
    ) in SHALLOW_THINKING_PROMPT
    assert (
        "# Order of execution\n"
        "1. Output the complete shallow thinking block first.\n"
        "2. Then output the final answer or status text, or continue with tool calls.\n\n"
    ) in SHALLOW_THINKING_PROMPT
    assert (
        "# Do not omit\n"
        "Do not omit the shallow thinking block even if the question is simple, you are merely continuing a prior turn, or you need to call a tool."
    ) in SHALLOW_THINKING_PROMPT
    assert (
        "# Task\n"
        "The shallow thinking block is a required prefix before any other output.\n"
        "Output one complete shallow thinking block before the main response, status text, or tool call.\n\n"
        "# Output format (MUST follow)\n\n"
    ) in SHALLOW_THINKING_PROMPT
    assert (
        "# Output format (MUST follow)\n\n"
        f"{SHALLOW_THINKING_START}\n"
        "[Known facts and problem definition]\n"
        "[Logic and reasoning]\n"
        "[Conclusion]\n"
        "[Verification]\n"
        f"{SHALLOW_THINKING_END}"
    ) in SHALLOW_THINKING_PROMPT
    assert "brief" not in SHALLOW_THINKING_PROMPT


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
