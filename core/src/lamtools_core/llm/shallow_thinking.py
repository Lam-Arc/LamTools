from __future__ import annotations

import inspect
from dataclasses import dataclass, replace
from typing import Any, AsyncIterator

from lamtools_core.llm import ChatMessage, LLMClient, LLMRequest, LLMResponse, LLMStreamEvent

SHALLOW_THINKING_START = "[>SHALLOW_thinking_START<]"
SHALLOW_THINKING_END = "[>SHALLOW_thinking_END<]"

SHALLOW_THINKING_PROMPT = f"""你在必须先按照以下格式展示你的推理过程！！！

# 任务
shallow thinking 块是无论输出什么内容都必须先输出的固定前缀。
先输出一个 shallow thinking 块，再继续正文、状态文字或工具调用。

# 输出格式（MUST遵循）

{SHALLOW_THINKING_START}
[已知信息与问题界定]
[逻辑与推理]
[结论]
[验证]
{SHALLOW_THINKING_END}

# 执行顺序
1. 先输出完整 shallow thinking 块。
2. 再输出最终答案、状态文字，或继续工具调用流程。

# 不要省略
问题很简单、只是继续上一轮、或需要调用工具时，也不要省略 shallow thinking 块。
"""


@dataclass(frozen=True)
class ShallowThinkingExtraction:
    thinking: str
    content: str
    extracted: bool


def extract_shallow_thinking(text: str) -> ShallowThinkingExtraction:
    start_index = text.find(SHALLOW_THINKING_START)
    if start_index < 0:
        return ShallowThinkingExtraction(thinking="", content=text, extracted=False)
    thinking_start = start_index + len(SHALLOW_THINKING_START)
    end_index = text.find(SHALLOW_THINKING_END, thinking_start)
    if end_index < 0:
        return ShallowThinkingExtraction(thinking="", content=text, extracted=False)

    thinking = text[thinking_start:end_index].strip()
    content = (text[:start_index] + text[end_index + len(SHALLOW_THINKING_END):]).strip()
    return ShallowThinkingExtraction(thinking=thinking, content=content, extracted=True)


def with_shallow_thinking_prompt(request: LLMRequest) -> LLMRequest:
    messages = list(request.messages)
    insert_at = 0
    while insert_at < len(messages) and messages[insert_at].role == "system":
        insert_at += 1
    messages.insert(
        insert_at,
        ChatMessage(
            role="system",
            content=SHALLOW_THINKING_PROMPT,
            metadata={"key": "shallow_thinking", "kind": "instruction"},
        ),
    )
    return replace(request, messages=messages)


def _merge_thinking(native: str, shallow: str) -> str:
    native = native.strip()
    shallow = shallow.strip()
    if native and shallow:
        return f"{native}\n\n{shallow}"
    return native or shallow


class ShallowThinkingClient:
    def __init__(self, inner: LLMClient) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def complete(self, request: LLMRequest) -> LLMResponse:
        response = await self._inner.complete(with_shallow_thinking_prompt(request))
        transformed = _transform_complete_response(response)
        if _response_has_thinking(transformed) or not _response_needs_thinking(response):
            return transformed
        return replace(
            transformed,
            metadata={**(transformed.metadata or {}), "shallow_thinking_missing": True},
        )

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamEvent]:
        stream = self._inner.stream(with_shallow_thinking_prompt(request))
        if inspect.isawaitable(stream):
            stream = await stream

        splitter = _ShallowThinkingStreamSplitter()
        async for event in stream:
            if event.kind == "content_delta" and event.content:
                for transformed in splitter.feed(event.content, raw=event.raw):
                    yield transformed
                continue
            if event.kind == "thinking_delta" and event.content:
                splitter.mark_has_thinking()
                yield event
                for transformed in splitter.release_pending_content(raw=event.raw):
                    yield transformed
                continue
            if event.kind == "tool_call_delta" and not splitter.has_thinking:
                for transformed in splitter.finish(raw=event.raw):
                    yield transformed
                yield _mark_shallow_missing(event)
                continue
            if event.kind == "done":
                if not splitter.has_thinking and _done_event_needs_thinking(event, splitter):
                    for transformed in splitter.finish(raw=event.raw):
                        yield transformed
                    yield _mark_shallow_missing(event)
                else:
                    for transformed in splitter.finish(raw=event.raw):
                        yield transformed
                    yield event
                continue
            yield event

        for transformed in splitter.finish(raw=None):
            yield transformed


class _ShallowThinkingStreamSplitter:
    def __init__(self) -> None:
        self._state = "before"
        self._buffer = ""
        self._thinking_buffer = ""
        self._prefix_buffer = ""
        self._has_thinking = False

    @property
    def has_thinking(self) -> bool:
        return self._has_thinking

    @property
    def has_pending_content(self) -> bool:
        return bool(self._buffer or self._prefix_buffer or self._thinking_buffer)

    def mark_has_thinking(self) -> None:
        self._has_thinking = True
        if self._state == "before":
            self._state = "after"

    def release_pending_content(self, *, raw: Any = None) -> list[LLMStreamEvent]:
        content = self._prefix_buffer + self._buffer
        self._prefix_buffer = ""
        self._buffer = ""
        self._thinking_buffer = ""
        self._state = "after"
        return [_content_event(content, raw=raw)] if content else []

    def feed(self, text: str, *, raw: Any = None) -> list[LLMStreamEvent]:
        self._buffer += text
        events: list[LLMStreamEvent] = []

        while self._buffer:
            if self._state == "before":
                start_index = self._buffer.find(SHALLOW_THINKING_START)
                if start_index >= 0:
                    self._prefix_buffer += self._buffer[:start_index]
                    self._buffer = self._buffer[start_index + len(SHALLOW_THINKING_START):]
                    self._state = "thinking"
                    continue
                keep = _trailing_marker_prefix_len(self._buffer, SHALLOW_THINKING_START)
                if keep:
                    self._prefix_buffer += self._buffer[:-keep]
                else:
                    self._prefix_buffer += self._buffer
                self._buffer = self._buffer[-keep:] if keep else ""
                break

            if self._state == "thinking":
                end_index = self._buffer.find(SHALLOW_THINKING_END)
                if end_index >= 0:
                    self._thinking_buffer += self._buffer[:end_index]
                    thinking = self._thinking_buffer.strip()
                    if thinking:
                        self._has_thinking = True
                        events.append(LLMStreamEvent(
                            kind="thinking_delta",
                            content=thinking,
                            raw=raw,
                            metadata={"shallow_thinking": True},
                        ))
                    self._buffer = _strip_one_leading_newline(
                        self._buffer[end_index + len(SHALLOW_THINKING_END):]
                    )
                    self._thinking_buffer = ""
                    self._state = "after"
                    if self._prefix_buffer or self._buffer:
                        content = self._prefix_buffer + self._buffer
                        self._prefix_buffer = ""
                        self._buffer = ""
                        events.append(_content_event(content, raw=raw))
                    continue
                keep = _trailing_marker_prefix_len(self._buffer, SHALLOW_THINKING_END)
                if keep:
                    self._thinking_buffer += self._buffer[:-keep]
                    self._buffer = self._buffer[-keep:]
                else:
                    self._thinking_buffer += self._buffer
                    self._buffer = ""
                break

            if self._buffer:
                events.append(_content_event(self._buffer, raw=raw))
            self._buffer = ""
            break

        return events

    def finish(self, *, raw: Any = None) -> list[LLMStreamEvent]:
        if not self._buffer and not self._thinking_buffer and not self._prefix_buffer:
            return []
        if self._state == "thinking":
            content = self._prefix_buffer + SHALLOW_THINKING_START + self._thinking_buffer + self._buffer
        else:
            content = self._prefix_buffer + self._buffer
        self._buffer = ""
        self._thinking_buffer = ""
        self._prefix_buffer = ""
        self._state = "after"
        return [_content_event(content, raw=raw)] if content else []


def _transform_complete_response(response: LLMResponse) -> LLMResponse:
    extracted = extract_shallow_thinking(response.content or "")
    if not extracted.extracted:
        return response
    return replace(
        response,
        content=extracted.content,
        thinking=_merge_thinking(response.thinking or "", extracted.thinking),
        metadata={**(response.metadata or {}), "shallow_thinking": True},
    )


def _response_has_thinking(response: LLMResponse) -> bool:
    return bool(str(response.thinking or "").strip())


def _response_needs_thinking(response: LLMResponse) -> bool:
    return bool(str(response.content or "").strip() or response.tool_calls)


def _done_event_needs_thinking(event: LLMStreamEvent, splitter: _ShallowThinkingStreamSplitter) -> bool:
    return bool(event.tool_calls or splitter.has_pending_content)


def _mark_shallow_missing(event: LLMStreamEvent) -> LLMStreamEvent:
    return replace(
        event,
        metadata={**(event.metadata or {}), "shallow_thinking_missing": True},
    )


def _content_event(content: str, *, raw: Any = None) -> LLMStreamEvent:
    return LLMStreamEvent(kind="content_delta", content=content, raw=raw)


def _trailing_marker_prefix_len(text: str, marker: str) -> int:
    max_len = min(len(text), len(marker) - 1)
    for length in range(max_len, 0, -1):
        if marker.startswith(text[-length:]):
            return length
    return 0


def _strip_one_leading_newline(text: str) -> str:
    if text.startswith("\r\n"):
        return text[2:]
    if text.startswith("\n"):
        return text[1:]
    return text


__all__ = [
    "SHALLOW_THINKING_END",
    "SHALLOW_THINKING_PROMPT",
    "SHALLOW_THINKING_START",
    "ShallowThinkingClient",
    "ShallowThinkingExtraction",
    "extract_shallow_thinking",
    "with_shallow_thinking_prompt",
]
