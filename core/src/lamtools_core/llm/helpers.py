"""Provider-neutral LLM helper functions.

Pure transformation functions with no side effects. No network or
provider-specific imports. Converts Core LLM types to/from
OpenAI-compatible payload formats.
"""

from __future__ import annotations

import json
import re
from typing import Any

from lamtools_core.llm import (
    ChatMessage,
    LLMRequest,
    LLMResponse,
    LLMStreamEvent,
    LLMToolCall,
    LLMUsage,
)

# -- finish reason normalization --------------------------------------------


def normalize_finish_reason(reason: str | None) -> str:
    """Map provider-specific finish reasons to Core values.

    Core values: stop, tool_calls, length, content_filter, error

    Handles OpenAI, Anthropic, and common provider variants.
    """
    if reason is None:
        return "stop"

    r = reason.strip().lower()

    # OpenAI-compatible
    if r in ("stop", "tool_calls", "length", "content_filter"):
        return r

    # Anthropic
    if r in ("end_turn",):
        return "stop"
    if r in ("tool_use",):
        return "tool_calls"
    if r in ("max_tokens",):
        return "length"

    # Common error variants
    if "error" in r:
        return "error"

    # Unknown but non-empty — pass through
    return r


# -- tool call argument parsing ---------------------------------------------

_MARKDOWN_FENCE_RE = re.compile(r"^```(?:json)?\s*\n(.*?)\n```\s*$", re.DOTALL)


def parse_tool_call_arguments(args_str: str) -> dict[str, Any]:
    """Parse JSON arguments string, return {} on failure.

    Strips markdown code fences (```json ... ```) if present.
    """
    if not args_str or not args_str.strip():
        return {}

    # Strip markdown fences
    m = _MARKDOWN_FENCE_RE.match(args_str.strip())
    source = m.group(1) if m else args_str

    try:
        result = json.loads(source)
        if isinstance(result, dict):
            return result
        return {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _tool_call_argument_metadata(args_str: Any) -> dict[str, Any]:
    if not isinstance(args_str, str):
        return {}
    metadata: dict[str, Any] = {"raw_arguments": args_str}
    source = args_str.strip()
    if not source:
        return metadata
    fence_match = _MARKDOWN_FENCE_RE.match(source)
    source = fence_match.group(1) if fence_match else source
    try:
        parsed = json.loads(source)
    except (json.JSONDecodeError, TypeError):
        metadata["arguments_parse_error"] = True
        metadata["raw_arguments_chars"] = len(args_str)
        return metadata
    if not isinstance(parsed, dict):
        metadata["arguments_parse_error"] = True
        metadata["raw_arguments_chars"] = len(args_str)
    return metadata


def normalize_usage(raw: Any) -> LLMUsage | None:
    """Convert common provider usage shapes into ``LLMUsage``.

    Accepts dict-like OpenAI fields, input/output token aliases, existing
    ``LLMUsage`` instances, and simple objects with token attributes.

    Extracts cached-token counts from both OpenAI-style nested detail dicts
    (``prompt_tokens_details.cached_tokens``) and Anthropic-style top-level
    fields (``cache_read_input_tokens`` / ``cache_creation_input_tokens``).
    """
    if raw is None:
        return None
    if isinstance(raw, LLMUsage):
        return raw
    if isinstance(raw, dict) and not raw:
        return None

    prompt_tokens = _usage_int(raw, "prompt_tokens", "input_tokens")
    completion_tokens = _usage_int(raw, "completion_tokens", "output_tokens")
    total_tokens = _usage_int(raw, "total_tokens")
    cached_tokens = _cached_tokens_from_usage(raw)
    cache_creation_tokens = _cache_creation_tokens_from_usage(raw)
    return LLMUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        cached_tokens=cached_tokens,
        cache_creation_tokens=cache_creation_tokens,
    )


def _usage_int(raw: Any, *keys: str) -> int:
    for key in keys:
        value = raw.get(key) if isinstance(raw, dict) else getattr(raw, key, None)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
    return 0


def _cached_tokens_from_usage(raw: Any) -> int:
    """Extract cache-read token count across provider shapes."""
    # Anthropic / OpenAI-compatible top-level aliases; DeepSeek reports
    # prompt_cache_hit_tokens / prompt_cache_miss_tokens at the top level.
    direct = _usage_int(
        raw,
        "cache_read_input_tokens",
        "cached_tokens",
        "prompt_cache_hit_tokens",
    )
    if direct:
        return direct
    # OpenAI nested detail dicts
    if isinstance(raw, dict):
        details = raw.get("prompt_tokens_details") or raw.get("input_tokens_details")
        if isinstance(details, dict):
            return _usage_int(details, "cached_tokens", "cache_read_input_tokens")
    return 0


def _cache_creation_tokens_from_usage(raw: Any) -> int:
    """Extract cache-creation token count (Anthropic / compatible)."""
    return _usage_int(raw, "cache_creation_input_tokens")


# -- thinking content extraction --------------------------------------------


def extract_thinking_content(message: dict[str, Any]) -> str:
    """Extract thinking/reasoning content from a message dict.

    Checks fields in order: thinking, reasoning_content, delta.reasoning_content.
    """
    thinking = message.get("thinking")
    if thinking:
        return str(thinking) if not isinstance(thinking, str) else thinking

    reasoning = message.get("reasoning_content")
    if reasoning:
        return str(reasoning) if not isinstance(reasoning, str) else reasoning

    return ""


# -- OpenAI payload builder -------------------------------------------------


def _chat_message_to_openai(msg: ChatMessage) -> dict[str, Any]:
    """Convert a ChatMessage to an OpenAI-compatible message dict."""
    d: dict[str, Any] = {"role": msg.role}

    if isinstance(msg.content, str):
        d["content"] = msg.content
    else:
        d["content"] = msg.content  # passthrough list of content blocks

    if msg.role in ("user", "assistant") and msg.name:
        d["name"] = msg.name

    if msg.role == "tool" and msg.tool_call_id:
        d["tool_call_id"] = msg.tool_call_id

    if msg.tool_calls:
        d["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.name,
                    "arguments": (
                        json.dumps(tc.arguments, ensure_ascii=False)
                        if isinstance(tc.arguments, dict)
                        else tc.arguments
                    ),
                },
            }
            for tc in msg.tool_calls
        ]

    return d


def chat_message_from_openai(message: dict[str, Any]) -> ChatMessage:
    """Convert an OpenAI-style message dict into a Core ``ChatMessage``."""
    raw_tool_calls = message.get("tool_calls") or []
    tool_calls: list[LLMToolCall] = []
    for raw_call in raw_tool_calls:
        if not isinstance(raw_call, dict):
            continue
        fn = raw_call.get("function") if isinstance(raw_call.get("function"), dict) else {}
        raw_arguments = fn.get("arguments", "")
        tool_calls.append(
            LLMToolCall(
                id=str(raw_call.get("id") or ""),
                name=str(fn.get("name") or ""),
                arguments=parse_tool_call_arguments(raw_arguments) if isinstance(raw_arguments, str) else {},
                raw=raw_call,
                metadata=_tool_call_argument_metadata(raw_arguments),
            )
        )

    content = message.get("content")
    return ChatMessage(
        role=str(message.get("role") or "user"),
        content=content if isinstance(content, list) else str(content or ""),
        name=str(message.get("name") or ""),
        tool_call_id=str(message.get("tool_call_id") or ""),
        tool_calls=tool_calls,
    )


def build_openai_payload(
    request: LLMRequest,
    *,
    stream: bool = False,
) -> dict[str, Any]:
    """Convert LLMRequest to an OpenAI-compatible payload dict.

    Includes stream_options when stream=True.
    Handles tools, tool_choice, and response_format passthrough.
    """
    payload: dict[str, Any] = {
        "model": request.model,
        "messages": [_chat_message_to_openai(m) for m in request.messages],
    }

    if request.temperature is not None:
        payload["temperature"] = request.temperature
    if request.max_tokens is not None:
        payload["max_tokens"] = request.max_tokens
    if request.top_p is not None:
        payload["top_p"] = request.top_p

    if request.tools:
        payload["tools"] = request.tools
    if request.tool_choice is not None:
        payload["tool_choice"] = request.tool_choice
    if request.parallel_tool_calls is not None:
        payload["parallel_tool_calls"] = request.parallel_tool_calls
    if request.response_format is not None:
        payload["response_format"] = request.response_format

    if stream:
        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}

    return payload


# -- OpenAI response normalization ------------------------------------------


def normalize_openai_response(response: dict[str, Any]) -> LLMResponse:
    """Convert an OpenAI-compatible response dict to LLMResponse.

    Extracts content, thinking, tool_calls, usage, and finish_reason
    from the standard choices[0].message + usage structure.
    """
    choices = response.get("choices", [])
    choice = choices[0] if choices else {}

    message: dict[str, Any] = choice.get("message", {})
    content = message.get("content")
    content_str = str(content) if content not in (None, "") else ""

    thinking = ""
    # Extract thinking from message-level fields
    raw_thinking = message.get("reasoning_content") or message.get("thinking")
    if raw_thinking:
        thinking = raw_thinking if isinstance(raw_thinking, str) else str(raw_thinking)

    # Tool calls
    raw_tool_calls = message.get("tool_calls", [])
    tool_calls: list[LLMToolCall] = []
    for tc in raw_tool_calls or []:
        fn = tc.get("function", {})
        args_str = fn.get("arguments", "")
        args = parse_tool_call_arguments(args_str)
        tool_calls.append(
            LLMToolCall(
                id=tc.get("id", ""),
                name=fn.get("name", ""),
                arguments=args,
                raw=tc,
                metadata=_tool_call_argument_metadata(args_str),
            )
        )

    # Usage
    usage = normalize_usage(response.get("usage"))

    finish_reason = normalize_finish_reason(
        choice.get("finish_reason") or message.get("finish_reason")
    )

    return LLMResponse(
        content=content_str,
        thinking=thinking,
        tool_calls=tool_calls,
        usage=usage,
        finish_reason=finish_reason,
        raw=response,
    )


# -- internal helpers for stream chunk normalization ------------------------


def _parse_usage(usage_raw: dict[str, Any]) -> LLMUsage:
    """Parse a usage dict into LLMUsage."""
    return normalize_usage(usage_raw) or LLMUsage()


def _resolve_raw_tool_calls(raw_list: list[dict[str, Any]]) -> list[LLMToolCall]:
    """Convert an OpenAI-format tool_calls list (from a final chunk) to LLMToolCall list."""
    result: list[LLMToolCall] = []
    for tc in raw_list or []:
        fn = tc.get("function", {})
        args_str = fn.get("arguments", "")
        args = parse_tool_call_arguments(args_str)
        result.append(
            LLMToolCall(
                id=tc.get("id", ""),
                name=fn.get("name", ""),
                arguments=args,
                raw=tc,
                metadata=_tool_call_argument_metadata(args_str),
            )
        )
    return result


# -- stream chunk normalization ---------------------------------------------


def normalize_stream_chunk(chunk: dict[str, Any]) -> LLMStreamEvent | None:
    """Convert an OpenAI-compatible stream chunk to LLMStreamEvent.

    Handles: content_delta, thinking_delta, tool_call_delta, usage, done, error.
    Returns None for empty chunks with no meaningful data.
    """
    # Error first
    error = chunk.get("error")
    if error:
        return LLMStreamEvent(
            kind="error",
            error=str(error.get("message", error)) if isinstance(error, dict) else str(error),
            raw=chunk,
        )

    choices = chunk.get("choices", [])
    choice = choices[0] if choices else {}
    delta: dict[str, Any] = choice.get("delta", {})
    finish_reason = choice.get("finish_reason")

    # Usage event
    usage_raw = chunk.get("usage")
    if usage_raw:
        usage = normalize_usage(usage_raw)
        if usage is None:
            return None
        return LLMStreamEvent(
            kind="usage",
            usage=usage,
            raw=chunk,
        )

    # Tool call delta
    tool_calls_delta = delta.get("tool_calls")
    if tool_calls_delta:
        return LLMStreamEvent(
            kind="tool_call_delta",
            content="",  # tool call deltas carry structured data in raw
            raw=chunk,
            metadata={"tool_calls_delta": tool_calls_delta},
        )

    # Thinking delta (reasoning_content)
    thinking = delta.get("reasoning_content") or delta.get("thinking")
    if thinking:
        thinking_str = thinking if isinstance(thinking, str) else str(thinking)
        return LLMStreamEvent(
            kind="thinking_delta",
            content=thinking_str,
            raw=chunk,
        )

    # Refusal delta (content_filter scenarios)
    refusal = delta.get("refusal")
    if refusal:
        refusal_str = refusal if isinstance(refusal, str) else str(refusal)
        return LLMStreamEvent(
            kind="refusal_delta",
            refusal=refusal_str,
            raw=chunk,
        )

    # Content delta
    content = delta.get("content")
    if content:
        content_str = content if isinstance(content, str) else str(content)
        return LLMStreamEvent(
            kind="content_delta",
            content=content_str,
            raw=chunk,
        )

    # Done: finish_reason is set — also carry tool_calls and usage if present
    if finish_reason is not None:
        tool_calls_raw = choice.get("tool_calls") if isinstance(choice, dict) else None
        usage_raw = chunk.get("usage") if isinstance(chunk, dict) else None
        return LLMStreamEvent(
            kind="done",
            raw=chunk,
            tool_calls=_resolve_raw_tool_calls(tool_calls_raw) if tool_calls_raw else None,
            usage=_parse_usage(usage_raw) if usage_raw else None,
            metadata={"finish_reason": finish_reason},
        )

    # Nothing useful
    return None


# -- tool call delta merging ------------------------------------------------


def merge_tool_call_deltas(
    accumulated: dict[int, dict[str, Any]],
    delta: dict[str, Any],
) -> dict[int, dict[str, Any]]:
    """Merge a tool_call delta into accumulated dict keyed by tool index.

    The delta should be an OpenAI delta.tool_calls entry with:
      index, id, type, function.name, function.arguments

    Uses += for function.name and function.arguments concatenation
    (streaming tool calls arrive in fragments).
    """
    tool_calls: list[dict[str, Any]] = delta.get("tool_calls", [delta])

    for tc in tool_calls:
        index = tc.get("index", 0)

        if index not in accumulated:
            accumulated[index] = {
                "id": "",
                "type": "function",
                "function": {"name": "", "arguments": ""},
            }

        acc = accumulated[index]

        # Id may arrive in a later chunk
        tc_id = tc.get("id")
        if tc_id:
            acc["id"] = tc_id

        tc_type = tc.get("type")
        if tc_type:
            acc["type"] = tc_type

        fn = tc.get("function", {})
        if fn:
            name = fn.get("name")
            if name:
                acc["function"]["name"] += name

            args = fn.get("arguments")
            if args:
                acc["function"]["arguments"] += args

    return accumulated


def resolve_tool_calls(
    accumulated: dict[int, dict[str, Any]],
) -> list[LLMToolCall]:
    """Convert accumulated tool call dict to list of LLMToolCall.

    Sorts by index key, parses arguments JSON.
    Includes the raw arguments string in metadata.
    """
    result: list[LLMToolCall] = []

    for index in sorted(accumulated.keys()):
        acc = accumulated[index]
        fn = acc.get("function", {})
        args_str = fn.get("arguments", "")
        args = parse_tool_call_arguments(args_str)

        result.append(
            LLMToolCall(
                id=acc.get("id", ""),
                name=fn.get("name", ""),
                arguments=args,
                raw=acc,
                metadata=_tool_call_argument_metadata(args_str),
            )
        )

    return result


__all__ = [
    "normalize_finish_reason",
    "parse_tool_call_arguments",
    "normalize_usage",
    "extract_thinking_content",
    "chat_message_from_openai",
    "build_openai_payload",
    "normalize_openai_response",
    "normalize_stream_chunk",
    "merge_tool_call_deltas",
    "resolve_tool_calls",
]
