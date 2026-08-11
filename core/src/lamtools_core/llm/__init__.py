"""LLM protocol types and client interface.

Sub-modules:
  helpers   - provider-neutral transformation functions
  adapter   - LLMAdapter protocol + OpenAICompatibleAdapter
  policy    - transport-level retry policy types
"""

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Literal, Protocol, runtime_checkable

MessageRole = Literal["system", "user", "assistant", "tool"]


@dataclass
class LLMToolCall:
    id: str
    name: str
    arguments: dict[str, Any] | str = field(default_factory=dict)
    raw: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "arguments": self.arguments,
        }
        if self.metadata:
            d["metadata"] = self.metadata
        return d


@dataclass
class ChatMessage:
    role: MessageRole
    content: str | list[dict[str, Any]] = ""
    name: str = ""
    tool_call_id: str = ""
    tool_calls: list[LLMToolCall] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.name:
            d["name"] = self.name
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        if self.tool_calls:
            d["tool_calls"] = [tc.to_dict() for tc in self.tool_calls]
        if self.metadata:
            d["metadata"] = self.metadata
        return d


@dataclass
class LLMUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0
    cache_creation_tokens: int = 0

    def __post_init__(self) -> None:
        if not self.total_tokens and (self.prompt_tokens or self.completion_tokens):
            self.total_tokens = self.prompt_tokens + self.completion_tokens

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }
        if self.cached_tokens:
            d["cached_tokens"] = self.cached_tokens
        if self.cache_creation_tokens:
            d["cache_creation_tokens"] = self.cache_creation_tokens
        return d


@dataclass
class LLMRequest:
    messages: list[ChatMessage] = field(default_factory=list)
    model: str = ""
    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None
    tools: list[dict[str, Any]] = field(default_factory=list)
    tool_choice: str | dict[str, Any] | None = None
    parallel_tool_calls: bool | None = None
    response_format: dict[str, Any] | None = None
    timeout: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "messages": [m.to_dict() for m in self.messages],
            "model": self.model,
        }
        if self.temperature is not None:
            d["temperature"] = self.temperature
        if self.max_tokens is not None:
            d["max_tokens"] = self.max_tokens
        if self.top_p is not None:
            d["top_p"] = self.top_p
        if self.tools:
            d["tools"] = self.tools
        if self.tool_choice is not None:
            d["tool_choice"] = self.tool_choice
        if self.parallel_tool_calls is not None:
            d["parallel_tool_calls"] = self.parallel_tool_calls
        if self.response_format is not None:
            d["response_format"] = self.response_format
        if self.timeout is not None:
            d["timeout"] = self.timeout
        if self.metadata:
            d["metadata"] = self.metadata
        return d


@dataclass
class LLMResponse:
    content: str = ""
    thinking: str = ""
    tool_calls: list[LLMToolCall] = field(default_factory=list)
    usage: LLMUsage | None = None
    finish_reason: str = "stop"
    raw: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "content": self.content,
            "finish_reason": self.finish_reason,
        }
        if self.thinking:
            d["thinking"] = self.thinking
        if self.tool_calls:
            d["tool_calls"] = [tc.to_dict() for tc in self.tool_calls]
        if self.usage is not None:
            d["usage"] = self.usage.to_dict()
        if self.metadata:
            d["metadata"] = self.metadata
        return d


StreamEventKind = Literal[
    "content_delta",
    "thinking_delta",
    "refusal_delta",
    "tool_call_delta",
    "tool_calls",
    "usage",
    "done",
    "error",
]


@dataclass
class LLMStreamEvent:
    kind: StreamEventKind
    content: str = ""
    refusal: str = ""
    tool_calls: list[LLMToolCall] = field(default_factory=list)
    usage: LLMUsage | None = None
    error: str = ""
    raw: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"kind": self.kind}
        if self.content:
            d["content"] = self.content
        if self.refusal:
            d["refusal"] = self.refusal
        if self.tool_calls:
            d["tool_calls"] = [tc.to_dict() for tc in self.tool_calls]
        if self.usage is not None:
            d["usage"] = self.usage.to_dict()
        if self.error:
            d["error"] = self.error
        if self.metadata:
            d["metadata"] = self.metadata
        return d


@runtime_checkable
class LLMClientProtocol(Protocol):
    async def complete(self, request: LLMRequest) -> LLMResponse: ...
    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamEvent]: ...


LLMClient = LLMClientProtocol


def merge_system_messages(messages: list[ChatMessage]) -> list[ChatMessage]:
    if not messages:
        return []
    result: list[ChatMessage] = []
    for msg in messages:
        if msg.role == "system" and result and result[-1].role == "system":
            prev = result[-1]
            prev_content = prev.content if isinstance(prev.content, str) else str(prev.content)
            cur_content = msg.content if isinstance(msg.content, str) else str(msg.content)
            merged = prev_content + "\n" + cur_content
            result[-1] = ChatMessage(
                role="system",
                content=merged,
                metadata={**prev.metadata, **msg.metadata},
            )
        else:
            result.append(msg)
    return result


def sum_usage(usages: list[LLMUsage]) -> LLMUsage:
    return LLMUsage(
        prompt_tokens=sum(u.prompt_tokens for u in usages),
        completion_tokens=sum(u.completion_tokens for u in usages),
        total_tokens=sum(u.total_tokens or (u.prompt_tokens + u.completion_tokens) for u in usages),
        cached_tokens=sum(u.cached_tokens for u in usages),
        cache_creation_tokens=sum(u.cache_creation_tokens for u in usages),
    )


from lamtools_core.llm.adapter import LLMAdapter, OpenAICompatibleAdapter
from lamtools_core.llm.helpers import (
    build_openai_payload,
    chat_message_from_openai,
    extract_thinking_content,
    merge_tool_call_deltas,
    normalize_finish_reason,
    normalize_openai_response,
    normalize_stream_chunk,
    normalize_usage,
    parse_tool_call_arguments,
    resolve_tool_calls,
)
from lamtools_core.llm.policy import RetryPolicy


__all__ = [
    # Core types
    "MessageRole",
    "LLMToolCall",
    "ChatMessage",
    "LLMUsage",
    "LLMRequest",
    "LLMResponse",
    "StreamEventKind",
    "LLMStreamEvent",
    "LLMClient",
    "LLMClientProtocol",
    # Functions
    "merge_system_messages",
    "sum_usage",
    "LLMAdapter",
    "OpenAICompatibleAdapter",
    "build_openai_payload",
    "chat_message_from_openai",
    "extract_thinking_content",
    "merge_tool_call_deltas",
    "normalize_finish_reason",
    "normalize_openai_response",
    "normalize_stream_chunk",
    "normalize_usage",
    "parse_tool_call_arguments",
    "resolve_tool_calls",
    "RetryPolicy",
]
