"""Provider adapter profile helpers.

Pure profile parsing and payload transformation functions for LLM providers.
Members may decide where profile files live, but profile semantics belong to
Core so product members do not each parse provider payloads.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

from lamtools_core.llm import LLMRequest, LLMStreamEvent, LLMUsage, build_openai_payload, normalize_usage


def strip_jsonc(text: str) -> str:
    """Remove JSONC comments while preserving strings."""
    result: list[str] = []
    i = 0
    in_string = False
    quote = ""
    escaped = False
    while i < len(text):
        char = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if in_string:
            result.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                in_string = False
            i += 1
            continue
        if char in {'"', "'"}:
            in_string = True
            quote = char
            result.append(char)
            i += 1
            continue
        if char == "/" and nxt == "/":
            i += 2
            while i < len(text) and text[i] not in "\r\n":
                i += 1
            continue
        if char == "/" and nxt == "*":
            i += 2
            while i + 1 < len(text) and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        result.append(char)
        i += 1
    return "".join(result)


def load_jsonc(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    clean = re.sub(r",(\s*[}\]])", r"\1", strip_jsonc(text))
    return json.loads(clean)


def load_adapter_profiles_from_dirs(profile_dirs: list[Path]) -> dict[str, dict[str, Any]]:
    profiles: dict[str, dict[str, Any]] = {}
    for directory in profile_dirs:
        if not directory.exists():
            continue
        for path in sorted([*directory.glob("*.json"), *directory.glob("*.jsonc")]):
            try:
                profile = load_jsonc(path)
            except (OSError, json.JSONDecodeError):
                continue
            profile_id = str(profile.get("id") or path.stem)
            profile["id"] = profile_id
            profiles[profile_id] = profile
    return profiles


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def get_path(data: Any, path: str, default: Any = None) -> Any:
    current = data
    for part in path.split("."):
        if part == "":
            continue
        if isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return default
        elif isinstance(current, dict):
            if part not in current:
                return default
            current = current[part]
        else:
            return default
    return current


def set_payload_fields(payload: dict[str, Any], fields: dict[str, Any]) -> None:
    for key, value in fields.items():
        payload[key] = copy.deepcopy(value)


def apply_request_payload(
    payload: dict[str, Any],
    *,
    profile: dict[str, Any],
    variables: dict[str, Any] | None = None,
) -> None:
    request = _extra_dict(profile.get("request"))
    body = request.get("body") or request.get("extra_body") or {}
    if isinstance(body, dict):
        fields = _render_template_values(body, variables or {})
        if isinstance(fields, dict):
            set_payload_fields(payload, fields)
    for key in request.get("unsupported_fields") or []:
        payload.pop(str(key), None)


def resolve_adapter_profile_from_profiles(
    profiles: dict[str, dict[str, Any]],
    *,
    api_type: str,
    base_url: str,
    provider_extra: dict[str, Any] | None = None,
    model_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    provider_extra = _extra_dict(provider_extra)
    model_extra = _extra_dict(model_extra)
    profile = _profile_from_extra(model_extra, profiles) or _profile_from_extra(provider_extra, profiles)
    if profile is None:
        profile = next(
            (copy.deepcopy(item) for item in profiles.values() if _matches_base_url(item, base_url)),
            None,
        )
    if profile is None:
        default_id = "anthropic-messages" if api_type == "anthropic" else "openai-chat"
        profile = copy.deepcopy(profiles.get(default_id, {"id": default_id}))

    for extra in (provider_extra, model_extra):
        override = extra.get("adapter_profile_override") or extra.get("llm_adapter_override")
        if isinstance(override, dict):
            profile = deep_merge(profile, override)
    return profile


def apply_thinking_payload(
    payload: dict[str, Any],
    *,
    profile: dict[str, Any],
    thinking_budget: int,
) -> None:
    thinking = _extra_dict(_extra_dict(profile.get("request")).get("thinking"))
    when_enabled = thinking.get("when_enabled")
    if isinstance(when_enabled, dict):
        fields = _render_template_values(when_enabled, {"thinking_budget": thinking_budget})
        set_payload_fields(payload, fields)
    for key in _extra_dict(profile.get("request")).get("unsupported_fields") or []:
        payload.pop(str(key), None)


def endpoint_path(profile: dict[str, Any], fallback: str) -> str:
    endpoint = str(profile.get("endpoint") or fallback)
    if not endpoint.startswith("/"):
        endpoint = "/" + endpoint
    return endpoint


def response_path(profile: dict[str, Any], section: str, key: str, fallback: str) -> str:
    value = get_path(profile, f"{section}.{key}")
    return str(value) if value else fallback


def build_profiled_openai_request(
    request: LLMRequest,
    profile: dict[str, Any],
    *,
    stream: bool = False,
    thinking_enabled: bool = False,
    thinking_budget: int = 0,
    endpoint_fallback: str = "/chat/completions",
) -> dict[str, Any]:
    payload = build_openai_payload(request, stream=stream)
    variables = {"thinking_budget": thinking_budget}
    apply_request_payload(payload, profile=profile, variables=variables)
    if thinking_enabled:
        apply_thinking_payload(payload, profile=profile, thinking_budget=thinking_budget)
    return {
        "endpoint": endpoint_path(profile, endpoint_fallback),
        "payload": payload,
    }


def build_profiled_anthropic_request(
    messages: list[dict[str, Any]],
    profile: dict[str, Any],
    *,
    model: str,
    max_tokens: int,
    temperature: float,
    thinking_enabled: bool = False,
    thinking_budget: int = 0,
    endpoint_fallback: str = "/anthropic/v1/messages",
) -> dict[str, Any]:
    system_content = ""
    chat_messages: list[dict[str, Any]] = []
    for message in messages:
        if message.get("role") == "system":
            system_content += str(message.get("content") or "") + "\n"
        else:
            chat_messages.append(_anthropic_message_from_openai_message(message))

    payload: dict[str, Any] = {
        "model": model,
        "messages": chat_messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if system_content:
        payload["system"] = system_content.strip()

    variables = {"thinking_budget": thinking_budget}
    apply_request_payload(payload, profile=profile, variables=variables)
    if thinking_enabled:
        apply_thinking_payload(payload, profile=profile, thinking_budget=thinking_budget)
    return {
        "endpoint": endpoint_path(profile, endpoint_fallback),
        "payload": payload,
    }


def _anthropic_message_from_openai_message(message: dict[str, Any]) -> dict[str, Any]:
    converted = copy.deepcopy(message)
    converted["content"] = _anthropic_content_from_openai_content(message.get("content"))
    return converted


def _anthropic_content_from_openai_content(content: Any) -> Any:
    if not isinstance(content, list):
        return copy.deepcopy(content)
    blocks: list[dict[str, Any]] = []
    for part in content:
        if not isinstance(part, dict):
            blocks.append({"type": "text", "text": str(part)})
            continue
        part_type = part.get("type")
        if part_type in ("text", "input_text"):
            blocks.append({"type": "text", "text": str(part.get("text") or "")})
            continue
        if part_type in ("image_url", "input_image"):
            image_url = _image_url_from_content_part(part)
            image_block = _anthropic_image_block_from_url(image_url)
            blocks.append(image_block if image_block is not None else copy.deepcopy(part))
            continue
        blocks.append(copy.deepcopy(part))
    return blocks


def _image_url_from_content_part(part: dict[str, Any]) -> str:
    raw = part.get("image_url")
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        return str(raw.get("url") or "")
    return ""


def _anthropic_image_block_from_url(url: str) -> dict[str, Any] | None:
    data_url = re.match(r"^data:([^;,]+);base64,(.*)$", url, flags=re.DOTALL)
    if data_url:
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": data_url.group(1),
                "data": data_url.group(2),
            },
        }
    if url.startswith("http://") or url.startswith("https://"):
        return {
            "type": "image",
            "source": {
                "type": "url",
                "url": url,
            },
        }
    return None


def normalize_stream_chunk_with_profile(
    chunk: dict[str, Any],
    profile: dict[str, Any],
) -> LLMStreamEvent | None:
    if "error" in chunk and isinstance(chunk["error"], dict):
        err = chunk["error"]
        return LLMStreamEvent(
            kind="error",
            error=str(err.get("message", "Unknown error")),
            raw=chunk,
            metadata={"error": err},
        )

    finish_reason = get_path(chunk, response_path(profile, "stream_response", "finish_reason", "choices.0.finish_reason"))
    usage = get_path(chunk, response_path(profile, "stream_response", "usage", "usage"))
    if usage and not get_path(chunk, "choices.0.delta") and not finish_reason:
        return LLMStreamEvent(kind="usage", usage=_usage_from_raw(usage), raw=chunk)

    if finish_reason:
        return LLMStreamEvent(
            kind="done",
            usage=_usage_from_raw(usage) if usage else None,
            raw=chunk,
            metadata={"finish_reason": finish_reason},
        )

    tool_calls_delta = get_path(chunk, response_path(profile, "stream_response", "tool_calls_delta", "choices.0.delta.tool_calls"))
    if tool_calls_delta:
        return LLMStreamEvent(
            kind="tool_call_delta",
            content="",
            raw=chunk,
            metadata={"tool_calls_delta": tool_calls_delta},
        )

    reasoning = get_path(chunk, response_path(profile, "stream_response", "reasoning_delta", "choices.0.delta.reasoning_content"))
    if reasoning:
        return LLMStreamEvent(kind="thinking_delta", content=str(reasoning), raw=chunk)

    content = get_path(chunk, response_path(profile, "stream_response", "content_delta", "choices.0.delta.content"))
    if content:
        return LLMStreamEvent(kind="content_delta", content=str(content), raw=chunk)

    return None


def normalize_response_with_profile(response: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    content_path = response_path(profile, "non_stream_response", "content", "choices.0.message.content")
    reasoning_path = response_path(profile, "non_stream_response", "reasoning", "choices.0.message.reasoning_content")
    tool_calls_path = response_path(profile, "non_stream_response", "tool_calls", "choices.0.message.tool_calls")
    finish_path = response_path(profile, "non_stream_response", "finish_reason", "choices.0.finish_reason")
    usage_path = response_path(profile, "non_stream_response", "usage", "usage")

    raw_content = get_path(response, content_path)
    raw_thinking = get_path(response, reasoning_path)
    raw_tool_calls = get_path(response, tool_calls_path)
    finish_reason = str(get_path(response, finish_path, "stop") or "stop")
    usage = _usage_from_raw(get_path(response, usage_path))

    return {
        "content": raw_content if isinstance(raw_content, str) else ("" if raw_content is None else str(raw_content)),
        "thinking": raw_thinking if isinstance(raw_thinking, str) else ("" if raw_thinking is None else str(raw_thinking)),
        "tool_calls": raw_tool_calls if isinstance(raw_tool_calls, list) else None,
        "finish_reason": finish_reason,
        "usage": usage.to_dict() if usage is not None else None,
    }


def normalize_anthropic_response_with_profile(response: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    blocks_path = response_path(profile, "non_stream_response", "content_blocks", "content")
    usage_path = response_path(profile, "non_stream_response", "usage", "usage")
    blocks = get_path(response, blocks_path, [])

    content = ""
    thinking = ""
    if isinstance(blocks, list):
        for block in blocks:
            if not isinstance(block, dict):
                continue
            block_type = str(block.get("type") or "")
            if block_type == "thinking":
                thinking += str(block.get("thinking") or "")
            elif block_type == "text":
                content += str(block.get("text") or "")

    usage = _usage_from_raw(get_path(response, usage_path))
    return {
        "content": content,
        "thinking": thinking,
        "usage": usage.to_dict() if usage is not None else None,
        "finish_reason": str(response.get("stop_reason") or "stop"),
    }


def _extra_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _profile_from_extra(extra: dict[str, Any], profiles: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    raw = extra.get("adapter_profile") or extra.get("llm_adapter")
    if isinstance(raw, dict):
        return copy.deepcopy(raw)
    if isinstance(raw, str) and raw in profiles:
        return copy.deepcopy(profiles[raw])
    raw_id = extra.get("adapter_profile_id") or extra.get("llm_adapter_id")
    if isinstance(raw_id, str) and raw_id in profiles:
        return copy.deepcopy(profiles[raw_id])
    return None


def _matches_base_url(profile: dict[str, Any], base_url: str) -> bool:
    lowered = base_url.lower()
    patterns = profile.get("match_base_url") or []
    if isinstance(patterns, str):
        patterns = [patterns]
    for pattern in patterns:
        text = str(pattern).lower()
        if text and re.search(text, lowered):
            return True
    return False


def _render_template_values(value: Any, variables: dict[str, Any]) -> Any:
    if isinstance(value, str) and value.startswith("$"):
        return variables.get(value[1:], value)
    if isinstance(value, dict):
        return {key: _render_template_values(item, variables) for key, item in value.items()}
    if isinstance(value, list):
        return [_render_template_values(item, variables) for item in value]
    return value


def _usage_from_raw(raw: Any) -> LLMUsage | None:
    return normalize_usage(raw)


__all__ = [
    "apply_request_payload",
    "apply_thinking_payload",
    "build_profiled_anthropic_request",
    "build_profiled_openai_request",
    "deep_merge",
    "endpoint_path",
    "get_path",
    "load_adapter_profiles_from_dirs",
    "load_jsonc",
    "normalize_anthropic_response_with_profile",
    "normalize_response_with_profile",
    "normalize_stream_chunk_with_profile",
    "resolve_adapter_profile_from_profiles",
    "response_path",
    "set_payload_fields",
    "strip_jsonc",
]
