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
from urllib.parse import quote

from lamtools_core.llm import (
    LLMRequest,
    LLMStreamEvent,
    LLMUsage,
    build_openai_payload,
    normalize_reasoning_level,
    normalize_usage,
    reasoning_level_from_legacy,
)


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


def strip_trailing_commas(text: str) -> str:
    """Remove JSON trailing commas without touching string literals.

    A plain regex like ``,(\\s*[}\\]])`` also rewrites ``",}"`` inside quoted
    values (audit 10 S3 — a URL or prompt ending in ``,}`` was silently
    corrupted). Only commas *outside* strings followed by a closing bracket
    are removed.
    """
    result: list[str] = []
    i = 0
    n = len(text)
    in_string = False
    quote = ""
    escaped = False
    while i < n:
        char = text[i]
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
        if char == ",":
            j = i + 1
            while j < n and text[j] in " \t\r\n":
                j += 1
            if j < n and text[j] in "}]":
                i = j
                continue
        result.append(char)
        i += 1
    return "".join(result)


def load_jsonc(path: Path) -> dict[str, Any]:
    # utf-8-sig: a BOM (common from old Notepad saves on Chinese Windows)
    # silently broke every config read — json.loads('\ufeff{...}') raises and
    # the stores fell back to {} / defaults (audit 09 S3).
    text = path.read_text(encoding="utf-8-sig")
    clean = strip_trailing_commas(strip_jsonc(text))
    return json.loads(clean)


def load_adapter_profiles_from_dirs(profile_dirs: list[Path]) -> dict[str, dict[str, Any]]:
    profiles: dict[str, dict[str, Any]] = {}
    for directory in profile_dirs:
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.jsonc")):
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
        _set_payload_path(payload, str(key), value)


def unset_payload_fields(payload: dict[str, Any], fields: list[str] | tuple[str, ...] | set[str]) -> None:
    for key in fields:
        _unset_payload_path(payload, str(key))


def _set_payload_path(payload: dict[str, Any], path: str, value: Any) -> None:
    parts = [part for part in path.split(".") if part]
    if not parts:
        return
    current = payload
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            child = {}
            current[part] = child
        current = child
    current[parts[-1]] = copy.deepcopy(value)


def _unset_payload_path(payload: dict[str, Any], path: str) -> None:
    parts = [part for part in path.split(".") if part]
    if not parts:
        return

    def remove(current: Any, index: int) -> bool:
        if not isinstance(current, dict):
            return False
        key = parts[index]
        if key not in current:
            return False
        if index == len(parts) - 1:
            del current[key]
        else:
            remove(current[key], index + 1)
            if isinstance(current.get(key), dict) and not current[key]:
                del current[key]
        return not current

    remove(payload, 0)


def _apply_reasoning_preset(
    payload: dict[str, Any],
    reasoning: dict[str, Any],
    *,
    level: str,
    variables: dict[str, Any],
) -> None:
    cleanup = reasoning.get("cleanup") or reasoning.get("cleanup_fields") or []
    if isinstance(cleanup, str):
        cleanup = [cleanup]
    if isinstance(cleanup, (list, tuple, set)):
        unset_payload_fields(payload, [str(item) for item in cleanup])

    presets = reasoning.get("presets")
    preset = presets.get(level) if isinstance(presets, dict) else None
    if isinstance(preset, dict):
        unset = preset.get("unset") or []
        if isinstance(unset, str):
            unset = [unset]
        if isinstance(unset, (list, tuple, set)):
            unset_payload_fields(payload, [str(item) for item in unset])
        fields = preset.get("set")
        if isinstance(fields, dict):
            set_payload_fields(payload, _render_template_values(fields, variables))
        # A compact preset can be written as {"reasoning_effort": "low"}.
        compact_fields = {
            str(key): value
            for key, value in preset.items()
            if key not in {"set", "unset"}
        }
        if compact_fields:
            set_payload_fields(payload, _render_template_values(compact_fields, variables))
        return

    # Alternate concise profile form:
    # {"field": "reasoning_effort", "values": {"light": "low"}}.
    field = str(reasoning.get("field") or "").strip()
    values = reasoning.get("values")
    if field and isinstance(values, dict):
        value = values.get(level)
        if value is None:
            _unset_payload_path(payload, field)
        else:
            _set_payload_path(payload, field, _render_template_values(value, variables))


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
    model_id: str = "",
    provider_name: str = "",
    provider_extra: dict[str, Any] | None = None,
    model_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    provider_extra = _extra_dict(provider_extra)
    model_extra = _extra_dict(model_extra)
    # A model-level explicit profile always wins.  When it is absent, a
    # shipped model matcher is more specific than a provider-wide profile;
    # this is important for OpenAI-compatible gateways that expose DeepSeek,
    # GLM, Kimi, Qwen, or Grok models through the same endpoint.
    profile = _profile_from_extra(model_extra, profiles)
    if profile is None and model_id:
        profile = _best_matching_profile(
            profiles,
            "match_model",
            model_id,
            api_type=api_type,
        )
    if profile is None:
        profile = _profile_from_extra(provider_extra, profiles)
    if profile is None and provider_name:
        profile = _best_matching_profile(
            profiles,
            "match_provider",
            provider_name,
            api_type=api_type,
        )
    if profile is None:
        profile = next(
            (
                copy.deepcopy(item)
                for item in profiles.values()
                if _profile_protocol_matches_api_type(item, api_type)
                and _matches_base_url(item, base_url)
            ),
            None,
        )
    if profile is None:
        normalized_api_type = str(api_type or "").strip().lower()
        if normalized_api_type in {"anthropic", "anthropic-messages"}:
            default_id = "anthropic-messages"
        elif normalized_api_type in {"responses", "openai-responses"}:
            default_id = "openai-responses"
        elif normalized_api_type in {"gemini", "gemini-generative-language"}:
            default_id = "gemini"
        elif normalized_api_type in {"openai-compatible", "grok", "xai"}:
            default_id = "openai-compatible"
        else:
            default_id = "openai-compatible"
        profile = copy.deepcopy(profiles.get(default_id, {"id": default_id}))

    for extra in (provider_extra, model_extra):
        override = extra.get("adapter_profile_override") or extra.get("llm_adapter_override")
        if isinstance(override, dict):
            profile = deep_merge(profile, override)
        # Model/provider jsonc may refine capability metadata without
        # duplicating the whole adapter profile (for example, marking a
        # particular model as always-on).  Keep this separate from request
        # mapping overrides so a model can only refine the selected profile's
        # reasoning semantics.
        reasoning_override = extra.get("reasoning")
        if isinstance(reasoning_override, dict):
            profile["reasoning"] = deep_merge(
                _extra_dict(profile.get("reasoning")),
                reasoning_override,
            )
    return profile


def strip_unsupported_content(messages: Any, capability: str) -> None:
    """Remove content blocks the model cannot process, in place.

    For text-only models (``capability == "text"``) this drops ``image_url`` /
    ``input_image`` parts from each message's content list, keeping text parts.
    A message whose content becomes empty is replaced with an empty string so
    the payload remains valid for providers that reject empty ``content`` lists.
    Multimodal models are left untouched.
    """
    cap = (capability or "").strip().lower()
    if cap != "text" or not isinstance(messages, list):
        return
    image_part_types = {"image_url", "input_image"}
    for message in messages:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        kept = [part for part in content if not (
            isinstance(part, dict) and part.get("type") in image_part_types
        )]
        if len(kept) == len(content):
            continue
        message["content"] = kept if kept else ""


def apply_thinking_payload(
    payload: dict[str, Any],
    *,
    profile: dict[str, Any],
    thinking_budget: int,
    reasoning_level: str = "",
    thinking_enabled: bool | None = None,
) -> None:
    request = _extra_dict(profile.get("request"))
    reasoning = _extra_dict(request.get("reasoning"))
    level = reasoning_level_from_legacy(
        reasoning_level=reasoning_level,
        thinking_enabled=thinking_enabled,
        fallback="high" if thinking_enabled else "off",
    )
    if level == "off" and not reasoning_off_supported(profile):
        level = normalize_reasoning_level(reasoning.get("off_fallback"), "light")
        if level == "off":
            level = "light"
    variables = {
        "thinking_budget": thinking_budget,
        # Anthropic rejects manual budgets below 1024.  Keep the product
        # presets valid even when an old model config contains a too-small
        # legacy budget.
        "thinking_budget_light": _reasoning_budget(thinking_budget, 2_048, minimum=1_024),
        "thinking_budget_high": _reasoning_budget(thinking_budget, 8_192, minimum=1_024),
        "thinking_budget_max": max(1_024, int(thinking_budget or 10_000)),
        "reasoning_level": level,
    }
    if reasoning:
        _apply_reasoning_preset(payload, reasoning, level=level, variables=variables)
    else:
        # Compatibility with custom profiles written before the four-level
        # contract.  New shipped profiles use ``request.reasoning.presets``.
        thinking = _extra_dict(request.get("thinking"))
        when_enabled = thinking.get("when_enabled")
        # Keep the historical no-argument behavior for callers that directly
        # use an old profile, but honor an explicit product-level ``off``.
        # ``reasoning_level`` is intentionally checked separately because an
        # explicit level can arrive without the legacy boolean.
        explicit_level = bool(str(reasoning_level or "").strip())
        legacy_enabled = (
            thinking_enabled is True
            or level != "off"
            or (thinking_enabled is None and not explicit_level)
        )
        if legacy_enabled and thinking_enabled is not False and isinstance(when_enabled, dict):
            fields = _render_template_values(when_enabled, variables)
            set_payload_fields(payload, fields)
    for key in request.get("unsupported_fields") or []:
        payload.pop(str(key), None)


def reasoning_off_supported(profile: dict[str, Any]) -> bool:
    """Whether the adapter can honor the product's ``off`` level."""

    value = get_path(profile, "reasoning.off_supported", True)
    return value is not False


def _reasoning_budget(value: int, target: int, *, minimum: int = 1) -> int:
    """Clamp a product budget preset to the model's configured maximum."""

    maximum = max(minimum, int(value or 10_000))
    return max(minimum, min(maximum, target))


def endpoint_path(
    profile: dict[str, Any],
    fallback: str,
    *,
    model: str = "",
    stream: bool = False,
) -> str:
    endpoint_key = "stream_endpoint" if stream and profile.get("stream_endpoint") else "endpoint"
    endpoint = str(profile.get(endpoint_key) or fallback)
    if not endpoint.startswith("/"):
        endpoint = "/" + endpoint
    if "{model}" in endpoint:
        model_ref = str(model or "").strip()
        if model_ref.startswith("models/"):
            model_ref = model_ref[7:]
        endpoint = endpoint.replace("{model}", quote(model_ref, safe="-_.~"))
    return endpoint


def response_path(profile: dict[str, Any], section: str, key: str, fallback: str) -> str:
    value = get_path(profile, f"{section}.{key}")
    return str(value) if value else fallback


def _provider_state_envelope(
    *,
    protocol: str,
    profile: dict[str, Any],
    model: str = "",
    **values: Any,
) -> dict[str, Any]:
    state: dict[str, Any] = {
        "protocol": protocol,
        "profile_id": str(profile.get("id") or ""),
    }
    if model:
        state["model"] = str(model)
    state.update(values)
    return state


def _provider_state_matches(
    state: Any,
    *,
    profile: dict[str, Any],
    protocol: str,
    model: str = "",
) -> bool:
    """Only replay opaque state to the protocol/profile/model that produced it."""

    if not isinstance(state, dict):
        return False
    if str(state.get("protocol") or "").strip().lower() != protocol.lower():
        return False
    state_profile = str(state.get("profile_id") or "").strip()
    current_profile = str(profile.get("id") or "").strip()
    if state_profile != current_profile:
        return False
    state_model = str(state.get("model") or "").strip()
    current_model = str(model or "").strip()
    if state_model != current_model:
        return False
    return True


def _openai_message_provider_state(
    message: Any,
    profile: dict[str, Any],
    *,
    model: str = "",
) -> dict[str, Any] | None:
    """Capture only known OpenAI-compatible continuation fields.

    A generic OpenAI-compatible endpoint must not receive guessed reasoning
    fields.  These values are replayed only when the originating profile and
    model match, so a provider's private response field cannot bleed into a
    different model selection.
    """

    if not isinstance(message, dict):
        return None
    fields: dict[str, Any] = {}
    for key in ("reasoning_content", "thinking", "reasoning"):
        value = message.get(key)
        if value not in (None, ""):
            fields[key] = copy.deepcopy(value)
    if not fields:
        return None
    return _provider_state_envelope(
        protocol="openai-chat-completions",
        profile=profile,
        model=model,
        message_fields=fields,
    )


def _openai_message_fields_from_state(
    state: Any,
    *,
    profile: dict[str, Any],
    model: str,
) -> dict[str, Any]:
    if not _provider_state_matches(
        state,
        profile=profile,
        protocol="openai-chat-completions",
        model=model,
    ):
        return {}
    fields = state.get("message_fields")
    return copy.deepcopy(fields) if isinstance(fields, dict) else {}


def _response_has_continuation_items(output: Any) -> bool:
    return isinstance(output, list) and any(
        isinstance(item, dict) and str(item.get("type") or "") in {"reasoning", "function_call"}
        for item in output
    )


def _responses_provider_state(
    output: Any,
    profile: dict[str, Any],
    *,
    model: str = "",
) -> dict[str, Any] | None:
    if not _response_has_continuation_items(output):
        return None
    return _provider_state_envelope(
        protocol="openai-responses",
        profile=profile,
        model=model,
        output=copy.deepcopy(output),
    )


def _responses_output_from_state(
    state: Any,
    *,
    profile: dict[str, Any],
    model: str,
) -> list[dict[str, Any]] | None:
    if not _provider_state_matches(
        state,
        profile=profile,
        protocol="openai-responses",
        model=model,
    ):
        return None
    output = state.get("output")
    if not isinstance(output, list):
        return None
    return copy.deepcopy(output)


def _anthropic_provider_state(
    blocks: Any,
    profile: dict[str, Any],
    *,
    model: str = "",
) -> dict[str, Any] | None:
    if not isinstance(blocks, list) or not any(
        isinstance(block, dict)
        and str(block.get("type") or "") in {"thinking", "redacted_thinking", "tool_use"}
        for block in blocks
    ):
        return None
    return _provider_state_envelope(
        protocol="anthropic-messages",
        profile=profile,
        model=model,
        content_blocks=copy.deepcopy(blocks),
    )


def _anthropic_blocks_from_state(
    state: Any,
    *,
    profile: dict[str, Any],
    model: str,
) -> list[dict[str, Any]] | None:
    if not _provider_state_matches(
        state,
        profile=profile,
        protocol="anthropic-messages",
        model=model,
    ):
        return None
    blocks = state.get("content_blocks")
    if not isinstance(blocks, list):
        return None
    return copy.deepcopy(blocks)


def _gemini_provider_state(
    content: Any,
    profile: dict[str, Any],
    *,
    model: str = "",
) -> dict[str, Any] | None:
    if not isinstance(content, dict):
        return None
    parts = content.get("parts")
    if not isinstance(parts, list) or not any(
        isinstance(part, dict)
        and (
            part.get("thought") is True
            or "thoughtSignature" in part
            or isinstance(part.get("functionCall"), dict)
        )
        for part in parts
    ):
        return None
    return _provider_state_envelope(
        protocol="gemini-generative-language",
        profile=profile,
        model=model,
        content=copy.deepcopy(content),
    )


def _gemini_content_from_state(
    state: Any,
    *,
    profile: dict[str, Any],
    model: str,
) -> dict[str, Any] | None:
    if not _provider_state_matches(
        state,
        profile=profile,
        protocol="gemini-generative-language",
        model=model,
    ):
        return None
    content = state.get("content")
    return copy.deepcopy(content) if isinstance(content, dict) else None


def update_provider_stream_state(
    current: Any,
    chunk: dict[str, Any],
    *,
    profile: dict[str, Any],
    protocol: str,
    model: str = "",
) -> Any:
    """Accumulate provider-native continuation data from a streaming response.

    The returned value is an internal snapshot suitable for attaching to a
    ``LLMStreamEvent``.  It intentionally keeps the raw provider blocks/items,
    while the public LLM types continue to expose provider-neutral text/tool
    fields.
    """

    normalized = protocol.strip().lower()
    if normalized in {"openai", "openai-chat", "openai-chat-completions"}:
        delta = get_path(chunk, response_path(profile, "stream_response", "delta", "choices.0.delta"), {})
        if not isinstance(delta, dict):
            return current
        fields = {
            key: copy.deepcopy(delta[key])
            for key in ("reasoning_content", "thinking", "reasoning")
            if delta.get(key) not in (None, "")
        }
        if not fields:
            return current
        state = current if _provider_state_matches(
            current,
            profile=profile,
            protocol="openai-chat-completions",
            model=model,
        ) else _provider_state_envelope(
            protocol="openai-chat-completions",
            profile=profile,
            model=model,
            message_fields={},
        )
        state = copy.deepcopy(state)
        message_fields = state.setdefault("message_fields", {})
        for key, value in fields.items():
            old = message_fields.get(key)
            if isinstance(old, str) and isinstance(value, str):
                message_fields[key] = old + value
            else:
                message_fields[key] = value
        return state

    if normalized == "anthropic-messages":
        event_type = str(chunk.get("type") or "")
        state = current if _provider_state_matches(
            current,
            profile=profile,
            protocol="anthropic-messages",
            model=model,
        ) else _provider_state_envelope(
            protocol="anthropic-messages",
            profile=profile,
            model=model,
            content_blocks=[],
        )
        state = copy.deepcopy(state)
        blocks = state.setdefault("content_blocks", [])
        if not isinstance(blocks, list):
            blocks = []
            state["content_blocks"] = blocks

        if event_type == "content_block_start":
            index = max(0, int(chunk.get("index") or 0))
            while len(blocks) <= index:
                blocks.append({})
            block = chunk.get("content_block")
            if isinstance(block, dict):
                blocks[index] = copy.deepcopy(block)
        elif event_type == "content_block_delta":
            index = max(0, int(chunk.get("index") or 0))
            while len(blocks) <= index:
                blocks.append({})
            block = blocks[index]
            if not isinstance(block, dict):
                block = {}
                blocks[index] = block
            delta = chunk.get("delta") if isinstance(chunk.get("delta"), dict) else {}
            delta_type = str(delta.get("type") or "")
            if delta_type == "thinking_delta":
                block["type"] = block.get("type") or "thinking"
                block["thinking"] = str(block.get("thinking") or "") + str(delta.get("thinking") or "")
            elif delta_type == "signature_delta":
                block["signature"] = str(block.get("signature") or "") + str(delta.get("signature") or "")
            elif delta_type == "text_delta":
                block["type"] = block.get("type") or "text"
                block["text"] = str(block.get("text") or "") + str(delta.get("text") or "")
            elif delta_type == "input_json_delta":
                raw = str(block.get("_lam_input_json") or "") + str(delta.get("partial_json") or "")
                block["_lam_input_json"] = raw
                try:
                    parsed = json.loads(raw)
                except (TypeError, json.JSONDecodeError):
                    parsed = None
                if isinstance(parsed, dict):
                    block["input"] = parsed
        return state

    if normalized in {"gemini", "gemini-generative-language"}:
        candidates = chunk.get("candidates")
        candidate = candidates[0] if isinstance(candidates, list) and candidates else None
        content = candidate.get("content") if isinstance(candidate, dict) else None
        incoming = content.get("parts") if isinstance(content, dict) else None
        if not isinstance(incoming, list):
            return current
        state = current if _provider_state_matches(
            current,
            profile=profile,
            protocol="gemini-generative-language",
            model=model,
        ) else _provider_state_envelope(
            protocol="gemini-generative-language",
            profile=profile,
            model=model,
            content={"role": "model", "parts": []},
        )
        state = copy.deepcopy(state)
        native_content = state.setdefault("content", {"role": "model", "parts": []})
        parts = native_content.setdefault("parts", []) if isinstance(native_content, dict) else []
        if not isinstance(parts, list):
            parts = []
            native_content["parts"] = parts
        for incoming_part in incoming:
            if not isinstance(incoming_part, dict):
                continue
            part = copy.deepcopy(incoming_part)
            if isinstance(part.get("functionCall"), dict):
                existing = next(
                    (
                        item for item in parts
                        if isinstance(item, dict)
                        and isinstance(item.get("functionCall"), dict)
                        and item.get("functionCall", {}).get("name") == part.get("functionCall", {}).get("name")
                    ),
                    None,
                )
                if existing is None:
                    parts.append(part)
                else:
                    existing["functionCall"] = copy.deepcopy(part["functionCall"])
                    for key in ("thought", "thoughtSignature"):
                        if key in part:
                            existing[key] = copy.deepcopy(part[key])
                continue
            if "text" in part and parts:
                previous = parts[-1]
                if isinstance(previous, dict) and "text" in previous and previous.get("thought") == part.get("thought"):
                    previous["text"] = str(previous.get("text") or "") + str(part.get("text") or "")
                    for key in ("thought", "thoughtSignature"):
                        if key in part:
                            previous[key] = copy.deepcopy(part[key])
                    continue
            parts.append(part)
        return state

    if normalized in {"responses", "openai-responses"}:
        response = chunk.get("response") if isinstance(chunk.get("response"), dict) else chunk
        output = response.get("output") if isinstance(response, dict) else None
        item = chunk.get("item") if isinstance(chunk.get("item"), dict) else None
        if isinstance(output, list) and _response_has_continuation_items(output):
            return _responses_provider_state(output, profile, model=model)
        if item is not None and str(item.get("type") or "") in {"reasoning", "function_call"}:
            state = current if _provider_state_matches(
                current,
                profile=profile,
                protocol="openai-responses",
                model=model,
            ) else _provider_state_envelope(
                protocol="openai-responses",
                profile=profile,
                model=model,
                output=[],
            )
            state = copy.deepcopy(state)
            state.setdefault("output", []).append(copy.deepcopy(item))
            return state
        if str(chunk.get("type") or "") == "response.function_call_arguments.delta":
            state = current if _provider_state_matches(
                current,
                profile=profile,
                protocol="openai-responses",
                model=model,
            ) else _provider_state_envelope(
                protocol="openai-responses",
                profile=profile,
                model=model,
                output=[],
            )
            state = copy.deepcopy(state)
            output_items = state.setdefault("output", [])
            call_id = str(chunk.get("call_id") or chunk.get("item_id") or "")
            existing = next(
                (
                    item
                    for item in output_items
                    if isinstance(item, dict)
                    and str(item.get("call_id") or item.get("id") or "") == call_id
                ),
                None,
            )
            if existing is None:
                existing = {"type": "function_call", "call_id": call_id, "arguments": ""}
                output_items.append(existing)
            existing["arguments"] = str(existing.get("arguments") or "") + str(chunk.get("delta") or "")
            return state
    return current


def finalize_provider_stream_state(state: Any) -> Any:
    """Remove stream-only bookkeeping before a state is persisted."""

    if not isinstance(state, dict):
        return None
    result = copy.deepcopy(state)
    blocks = result.get("content_blocks")
    if isinstance(blocks, list):
        has_continuation = any(
            isinstance(block, dict)
            and str(block.get("type") or "") in {"thinking", "redacted_thinking", "tool_use"}
            for block in blocks
        )
        if not has_continuation:
            result["content_blocks"] = []
            blocks = []
        for block in blocks:
            if isinstance(block, dict):
                block.pop("_lam_input_json", None)
    content = result.get("content")
    if isinstance(content, dict):
        parts = content.get("parts")
        has_continuation = isinstance(parts, list) and any(
            isinstance(part, dict)
            and (
                part.get("thought") is True
                or "thoughtSignature" in part
                or isinstance(part.get("functionCall"), dict)
            )
            for part in parts
        )
        if not has_continuation:
            result["content"] = {}
    if not result.get("message_fields") and not result.get("output") and not result.get("content_blocks"):
        content = result.get("content")
        if not isinstance(content, dict) or not content.get("parts"):
            return None
    return result


def _restore_openai_provider_state(
    payload_messages: Any,
    source_messages: list[Any],
    profile: dict[str, Any],
    *,
    model: str,
) -> None:
    """Restore provider fields only on the assistant message that produced them."""

    if not isinstance(payload_messages, list):
        return
    for index, payload_message in enumerate(payload_messages):
        if not isinstance(payload_message, dict) or index >= len(source_messages):
            continue
        source_message = source_messages[index]
        if getattr(source_message, "role", "") != "assistant":
            continue
        fields = _openai_message_fields_from_state(
            getattr(source_message, "provider_state", None),
            profile=profile,
            model=model,
        )
        if fields:
            payload_message.update(fields)


def build_profiled_openai_request(
    request: LLMRequest,
    profile: dict[str, Any],
    *,
    stream: bool = False,
    thinking_enabled: bool = False,
    thinking_budget: int = 0,
    reasoning_effort: str = "",
    reasoning_level: str = "",
    capability: str = "",
    endpoint_fallback: str = "/chat/completions",
) -> dict[str, Any]:
    payload = build_openai_payload(request, stream=stream)
    _restore_openai_provider_state(
        payload.get("messages"),
        request.messages,
        profile,
        model=request.model,
    )
    if capability.strip().lower() == "text":
        strip_unsupported_content(payload.get("messages"), capability)
    variables = {"thinking_budget": thinking_budget}
    apply_request_payload(payload, profile=profile, variables=variables)
    request_config = _extra_dict(profile.get("request"))
    has_reasoning_profile = isinstance(request_config.get("reasoning"), dict)
    if has_reasoning_profile or thinking_enabled:
        apply_thinking_payload(
            payload,
            profile=profile,
            thinking_budget=thinking_budget,
            reasoning_level=reasoning_level,
            thinking_enabled=thinking_enabled,
        )
    effective_level = reasoning_level_from_legacy(
        reasoning_level=reasoning_level,
        thinking_enabled=thinking_enabled,
        reasoning_effort=reasoning_effort,
        fallback="off",
    )
    if (
        effective_level != "off"
        and bool(request_config.get("omit_temperature_when_reasoning"))
        and not get_path(request_config, "body.temperature")
        and not get_path(request_config, "extra_body.temperature")
    ):
        payload.pop("temperature", None)
    # A legacy caller may still provide a literal effort.  Do not let it
    # override a selected four-level preset, and never emit it when the new
    # level is explicitly off.
    if reasoning_effort and not reasoning_level and effective_level != "off" and not has_reasoning_profile:
        payload["reasoning_effort"] = reasoning_effort
    return {
        "endpoint": endpoint_path(profile, endpoint_fallback, model=request.model, stream=stream),
        "payload": payload,
    }


def build_profiled_responses_request(
    request: LLMRequest,
    profile: dict[str, Any],
    *,
    stream: bool = False,
    thinking_enabled: bool = False,
    thinking_budget: int = 0,
    reasoning_effort: str = "",
    reasoning_level: str = "",
    capability: str = "",
    endpoint_fallback: str = "/responses",
) -> dict[str, Any]:
    """Build an OpenAI Responses request from the Core chat model.

    Responses has a different input/tool envelope from Chat Completions, so
    it must not be handled by merely changing the endpoint string.
    """

    chat_payload = build_openai_payload(request, stream=stream)
    messages = chat_payload.pop("messages", [])
    chat_payload.pop("stream_options", None)
    payload: dict[str, Any] = {
        key: value for key, value in chat_payload.items() if key != "tools"
    }
    payload["input"] = _responses_input_from_openai_messages(
        messages,
        provider_states=[message.provider_state for message in request.messages],
        profile=profile,
        model=request.model,
    )
    if request.tools:
        payload["tools"] = [_responses_tool_from_openai_tool(tool) for tool in request.tools]
    if request.tool_choice is not None:
        payload["tool_choice"] = _responses_tool_choice_from_openai_choice(request.tool_choice)

    variables = {"thinking_budget": thinking_budget}
    apply_request_payload(payload, profile=profile, variables=variables)
    request_config = _extra_dict(profile.get("request"))
    if isinstance(request_config.get("reasoning"), dict) or thinking_enabled:
        apply_thinking_payload(
            payload,
            profile=profile,
            thinking_budget=thinking_budget,
            reasoning_level=reasoning_level,
            thinking_enabled=thinking_enabled,
        )
    effective_level = reasoning_level_from_legacy(
        reasoning_level=reasoning_level,
        thinking_enabled=thinking_enabled,
        reasoning_effort=reasoning_effort,
        fallback="off",
    )
    if reasoning_effort and not reasoning_level and effective_level != "off" and not isinstance(request_config.get("reasoning"), dict):
        _set_payload_path(payload, "reasoning.effort", reasoning_effort)
    return {
        "endpoint": endpoint_path(profile, endpoint_fallback, model=request.model, stream=stream),
        "payload": payload,
    }


def _responses_input_from_openai_messages(
    messages: Any,
    *,
    provider_states: list[Any] | None = None,
    profile: dict[str, Any] | None = None,
    model: str = "",
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if not isinstance(messages, list):
        return result
    for message_index, message in enumerate(messages):
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "user")
        if role == "assistant" and isinstance(profile, dict):
            state = (
                provider_states[message_index]
                if provider_states is not None and message_index < len(provider_states)
                else None
            )
            restored = _responses_output_from_state(state, profile=profile, model=model)
            if restored is not None:
                result.extend(restored)
                continue
        if role == "tool":
            result.append({
                "type": "function_call_output",
                "call_id": str(message.get("tool_call_id") or ""),
                "output": _responses_output_value(message.get("content")),
            })
            continue
        if role == "assistant" and message.get("tool_calls"):
            for tool_call in message.get("tool_calls") or []:
                if not isinstance(tool_call, dict):
                    continue
                function = tool_call.get("function") if isinstance(tool_call.get("function"), dict) else {}
                arguments = function.get("arguments") or "{}"
                if not isinstance(arguments, str):
                    arguments = json.dumps(arguments, ensure_ascii=False)
                result.append({
                    "type": "function_call",
                    "call_id": str(tool_call.get("id") or ""),
                    "name": str(function.get("name") or ""),
                    "arguments": arguments,
                })
        content = message.get("content")
        content_blocks = _responses_content_from_openai_content(content, role=role)
        if content_blocks:
            result.append({
                "type": "message",
                "role": "developer" if role == "system" else role,
                "content": content_blocks,
            })
    return result


def _responses_content_from_openai_content(content: Any, *, role: str) -> list[dict[str, Any]]:
    if isinstance(content, str):
        if not content:
            return []
        return [{"type": "input_text", "text": content}]
    if not isinstance(content, list):
        return []
    result: list[dict[str, Any]] = []
    for part in content:
        if not isinstance(part, dict):
            result.append({"type": "input_text", "text": str(part)})
            continue
        part_type = str(part.get("type") or "")
        if part_type in {"text", "input_text", "output_text"}:
            result.append({"type": "input_text", "text": str(part.get("text") or "")})
        elif part_type in {"image_url", "input_image"}:
            result.append(copy.deepcopy(part) if part_type == "input_image" else {
                "type": "input_image",
                "image_url": _image_url_from_content_part(part),
            })
    return result


def _responses_output_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def _responses_tool_from_openai_tool(tool: dict[str, Any]) -> dict[str, Any]:
    function = tool.get("function") if isinstance(tool.get("function"), dict) else tool
    result: dict[str, Any] = {
        "type": "function",
        "name": str(function.get("name") or ""),
        "parameters": copy.deepcopy(function.get("parameters") or {"type": "object", "properties": {}}),
    }
    if function.get("description"):
        result["description"] = str(function["description"])
    if "strict" in function:
        result["strict"] = bool(function.get("strict"))
    return result


def _responses_tool_choice_from_openai_choice(choice: str | dict[str, Any]) -> Any:
    if isinstance(choice, dict):
        if choice.get("type") == "function":
            function = choice.get("function") if isinstance(choice.get("function"), dict) else {}
            return {"type": "function", "name": str(function.get("name") or "")}
        return copy.deepcopy(choice)
    return choice


def normalize_responses_response_with_profile(
    response: dict[str, Any],
    profile: dict[str, Any],
    *,
    model: str = "",
) -> dict[str, Any]:
    content = ""
    thinking = ""
    tool_calls: list[dict[str, Any]] = []
    output = response.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type") or "")
            if item_type == "reasoning":
                summaries = item.get("summary") or []
                if isinstance(summaries, list):
                    for summary in summaries:
                        if isinstance(summary, dict):
                            thinking += str(summary.get("text") or "")
            elif item_type == "message":
                for part in item.get("content") or []:
                    if isinstance(part, dict) and part.get("type") in {"output_text", "text"}:
                        content += str(part.get("text") or "")
            elif item_type == "function_call":
                arguments = item.get("arguments") or "{}"
                if not isinstance(arguments, str):
                    arguments = json.dumps(arguments, ensure_ascii=False)
                tool_calls.append({
                    "id": str(item.get("call_id") or item.get("id") or ""),
                    "type": "function",
                    "function": {
                        "name": str(item.get("name") or ""),
                        "arguments": arguments,
                    },
                })
    usage = _usage_from_raw(response.get("usage"))
    result: dict[str, Any] = {
        "content": content,
        "thinking": thinking,
        "usage": usage.to_dict() if usage is not None else None,
        "finish_reason": str(response.get("status") or response.get("stop_reason") or "stop"),
    }
    if tool_calls:
        result["tool_calls"] = tool_calls
    provider_state = _responses_provider_state(output, profile, model=model)
    if provider_state is not None:
        result["provider_state"] = provider_state
    return result


def normalize_responses_stream_event(event: dict[str, Any], profile: dict[str, Any]) -> LLMStreamEvent | None:
    event_type = str(event.get("type") or "")
    if event_type == "error":
        error = event.get("error")
        return LLMStreamEvent(kind="error", error=str(error.get("message") if isinstance(error, dict) else error or "Unknown error"), raw=event)
    if event_type in {"response.output_text.delta", "response.content_part.delta"}:
        content = event.get("delta") or event.get("text") or ""
        return LLMStreamEvent(kind="content_delta", content=str(content), raw=event) if content else None
    if event_type in {"response.reasoning_summary_text.delta", "response.reasoning_text.delta"}:
        content = event.get("delta") or event.get("text") or ""
        return LLMStreamEvent(kind="thinking_delta", content=str(content), raw=event) if content else None
    if event_type == "response.function_call_arguments.delta":
        delta = str(event.get("delta") or "")
        if not delta:
            return None
        index = int(event.get("output_index") or event.get("index") or 0)
        return LLMStreamEvent(
            kind="tool_call_delta",
            raw=event,
            metadata={"tool_calls_delta": [{
                "index": index,
                "id": str(event.get("call_id") or event.get("item_id") or ""),
                "type": "function",
                "function": {"arguments": delta},
            }]},
        )
    if event_type in {"response.completed", "response.done"}:
        response = event.get("response") if isinstance(event.get("response"), dict) else event
        usage = _usage_from_raw(response.get("usage")) if isinstance(response, dict) else None
        return LLMStreamEvent(kind="finish", finish_reason="stop", usage=usage, raw=event)
    return None


def build_profiled_gemini_request(
    request: LLMRequest,
    profile: dict[str, Any],
    *,
    stream: bool = False,
    thinking_enabled: bool = False,
    thinking_budget: int = 0,
    reasoning_effort: str = "",
    reasoning_level: str = "",
    capability: str = "",
    endpoint_fallback: str = "/v1beta/models/{model}:generateContent",
) -> dict[str, Any]:
    """Build a native Gemini Generative Language request.

    Gemini's native API is not OpenAI Chat-shaped: conversation turns live in
    ``contents``, system text is ``systemInstruction``, and sampling/output
    controls are nested under ``generationConfig``.  Keeping this conversion
    here also prevents a Gemini key from receiving OpenAI-only fields such as
    ``reasoning_effort`` at the root.
    """

    contents, system_parts = _gemini_contents_from_messages(
        [message.to_dict() for message in request.messages],
        profile=profile,
        model=request.model,
    )
    payload: dict[str, Any] = {"contents": contents}
    if system_parts:
        payload["systemInstruction"] = {"parts": system_parts}

    generation_config: dict[str, Any] = {}
    if request.temperature is not None:
        generation_config["temperature"] = request.temperature
    if request.top_p is not None:
        generation_config["topP"] = request.top_p
    if request.max_tokens is not None:
        generation_config["maxOutputTokens"] = request.max_tokens
    if request.response_format is not None:
        _apply_gemini_response_format(generation_config, request.response_format)
    if generation_config:
        payload["generationConfig"] = generation_config

    if request.tools:
        declarations = _gemini_function_declarations(request.tools)
        if declarations:
            payload["tools"] = [{"functionDeclarations": declarations}]
    if request.tool_choice is not None:
        tool_config = _gemini_tool_config(request.tool_choice)
        if tool_config is not None:
            payload["toolConfig"] = tool_config

    variables = {"thinking_budget": thinking_budget}
    apply_request_payload(payload, profile=profile, variables=variables)
    request_config = _extra_dict(profile.get("request"))
    if isinstance(request_config.get("reasoning"), dict) or thinking_enabled:
        apply_thinking_payload(
            payload,
            profile=profile,
            thinking_budget=thinking_budget,
            reasoning_level=reasoning_level,
            thinking_enabled=thinking_enabled,
        )
    # Preserve the legacy literal only for a custom profile that has no
    # reasoning mapping.  Native Gemini does not define this field, so shipped
    # Gemini profiles never take this branch.
    effective_level = reasoning_level_from_legacy(
        reasoning_level=reasoning_level,
        thinking_enabled=thinking_enabled,
        reasoning_effort=reasoning_effort,
        fallback="off",
    )
    if (
        reasoning_effort
        and effective_level != "off"
        and not reasoning_level
        and not isinstance(request_config.get("reasoning"), dict)
    ):
        payload["reasoning_effort"] = reasoning_effort

    return {
        "endpoint": endpoint_path(
            profile,
            endpoint_fallback,
            model=request.model,
            stream=stream,
        ),
        "payload": payload,
    }


def _gemini_contents_from_messages(
    messages: list[Any],
    *,
    profile: dict[str, Any] | None = None,
    model: str = "",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    contents: list[dict[str, Any]] = []
    system_parts: list[dict[str, Any]] = []
    if not isinstance(messages, list):
        return contents, system_parts

    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "user").strip().lower()
        parts = _gemini_parts_from_content(message.get("content"), role=role)
        if role == "system":
            system_parts.extend(parts)
            continue

        if role == "assistant":
            if isinstance(profile, dict):
                restored = _gemini_content_from_state(
                    message.get("provider_state"),
                    profile=profile,
                    model=model,
                )
                if restored is not None:
                    contents.append(restored)
                    continue
            for tool_call in message.get("tool_calls") or []:
                if not isinstance(tool_call, dict):
                    continue
                function = tool_call.get("function") if isinstance(tool_call.get("function"), dict) else {}
                arguments = function.get("arguments") or {}
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except json.JSONDecodeError:
                        arguments = {}
                parts.append({
                    "functionCall": {
                        "name": str(function.get("name") or ""),
                        "args": arguments if isinstance(arguments, dict) else {},
                    }
                })
            role_name = "model"
        elif role == "tool":
            tool_name = str(message.get("name") or message.get("tool_call_id") or "tool")
            raw_response = message.get("content")
            response: Any = raw_response
            if isinstance(raw_response, str):
                try:
                    response = json.loads(raw_response)
                except json.JSONDecodeError:
                    response = {"result": raw_response}
            if not isinstance(response, dict):
                response = {"result": response}
            parts = [{"functionResponse": {"name": tool_name, "response": response}}]
            role_name = "user"
        else:
            role_name = "user"

        if not parts:
            parts = [{"text": ""}]
        contents.append({"role": role_name, "parts": parts})
    return contents, system_parts


def _gemini_parts_from_content(content: Any, *, role: str) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [{"text": content}] if content else []
    if not isinstance(content, list):
        return [{"text": str(content)}] if content is not None else []

    parts: list[dict[str, Any]] = []
    for part in content:
        if not isinstance(part, dict):
            parts.append({"text": str(part)})
            continue
        part_type = str(part.get("type") or "")
        if part_type in {"text", "input_text", "output_text"}:
            parts.append({"text": str(part.get("text") or "")})
            continue
        if part_type in {"image_url", "input_image"}:
            raw = part.get("image_url")
            url = raw if isinstance(raw, str) else str((raw or {}).get("url") or "") if isinstance(raw, dict) else ""
            converted = _gemini_media_part(url)
            if converted is not None:
                parts.append(converted)
            continue
        if part_type == "inlineData" and isinstance(part.get("inlineData"), dict):
            parts.append(copy.deepcopy(part))
            continue
        if part_type == "fileData" and isinstance(part.get("fileData"), dict):
            parts.append(copy.deepcopy(part))
            continue
        if role == "assistant" and isinstance(part.get("functionCall"), dict):
            parts.append(copy.deepcopy(part))
    return parts


def _gemini_media_part(url: str) -> dict[str, Any] | None:
    data_url = re.match(r"^data:([^;,]+);base64,(.*)$", url, flags=re.DOTALL)
    if data_url:
        return {
            "inlineData": {
                "mimeType": data_url.group(1),
                "data": data_url.group(2),
            }
        }
    if url.startswith("http://") or url.startswith("https://"):
        return {"fileData": {"fileUri": url}}
    return None


def _gemini_function_declarations(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    declarations: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        function = tool.get("function") if isinstance(tool.get("function"), dict) else tool
        name = str(function.get("name") or "").strip()
        if not name:
            continue
        declaration: dict[str, Any] = {"name": name}
        if function.get("description"):
            declaration["description"] = str(function["description"])
        if isinstance(function.get("parameters"), dict):
            declaration["parameters"] = copy.deepcopy(function["parameters"])
        declarations.append(declaration)
    return declarations


def _gemini_tool_config(choice: str | dict[str, Any]) -> dict[str, Any] | None:
    if isinstance(choice, dict):
        if choice.get("type") == "function":
            function = choice.get("function") if isinstance(choice.get("function"), dict) else {}
            name = str(function.get("name") or "")
            return {"functionCallingConfig": {"mode": "ANY", "allowedFunctionNames": [name]}} if name else None
        choice = str(choice.get("mode") or choice.get("type") or "")
    mode = str(choice or "auto").strip().lower()
    mapped = {"auto": "AUTO", "required": "ANY", "any": "ANY", "none": "NONE"}.get(mode)
    return {"functionCallingConfig": {"mode": mapped}} if mapped else None


def _apply_gemini_response_format(generation_config: dict[str, Any], response_format: dict[str, Any]) -> None:
    kind = str(response_format.get("type") or "").strip().lower()
    if kind == "json_object":
        generation_config["responseMimeType"] = "application/json"
    elif kind == "json_schema":
        generation_config["responseMimeType"] = "application/json"
        schema = response_format.get("json_schema")
        if isinstance(schema, dict):
            generation_config["responseSchema"] = copy.deepcopy(schema.get("schema") or schema)


def normalize_gemini_response_with_profile(
    response: dict[str, Any],
    profile: dict[str, Any],
    *,
    model: str = "",
) -> dict[str, Any]:
    content, thinking, tool_calls, finish_reason = _gemini_candidate_values(response)
    usage = _gemini_usage(response.get("usageMetadata"))
    result: dict[str, Any] = {
        "content": content,
        "thinking": thinking,
        "usage": usage.to_dict() if usage is not None else None,
        "finish_reason": finish_reason,
    }
    if tool_calls:
        result["tool_calls"] = tool_calls
    candidates = response.get("candidates")
    first_content = (
        candidates[0].get("content")
        if isinstance(candidates, list)
        and candidates
        and isinstance(candidates[0], dict)
        else None
    )
    provider_state = _gemini_provider_state(first_content, profile, model=model)
    if provider_state is not None:
        result["provider_state"] = provider_state
    return result


def normalize_gemini_stream_event(event: dict[str, Any], profile: dict[str, Any]) -> LLMStreamEvent | None:
    del profile
    if isinstance(event.get("error"), dict):
        return LLMStreamEvent(
            kind="error",
            error=str(event["error"].get("message") or "Unknown error"),
            raw=event,
        )
    content, thinking, tool_calls, finish_reason = _gemini_candidate_values(event)
    usage = _gemini_usage(event.get("usageMetadata"))
    if tool_calls:
        return LLMStreamEvent(
            kind="tool_call_delta",
            raw=event,
            finish_reason=finish_reason if finish_reason != "stop" else None,
            usage=usage,
            metadata={"tool_calls_delta": tool_calls},
        )
    if thinking:
        return LLMStreamEvent(
            kind="thinking_delta",
            content=thinking,
            raw=event,
            finish_reason=finish_reason if finish_reason != "stop" else None,
            usage=usage,
        )
    if content:
        return LLMStreamEvent(
            kind="content_delta",
            content=content,
            raw=event,
            finish_reason=finish_reason if finish_reason != "stop" else None,
            usage=usage,
        )
    if usage is not None or finish_reason != "stop":
        return LLMStreamEvent(kind="finish", finish_reason=finish_reason, usage=usage, raw=event)
    return None


def _gemini_candidate_values(response: dict[str, Any]) -> tuple[str, str, list[dict[str, Any]], str]:
    content = ""
    thinking = ""
    tool_calls: list[dict[str, Any]] = []
    candidates = response.get("candidates")
    if not isinstance(candidates, list):
        candidates = []
    for candidate_index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            continue
        candidate_content = candidate.get("content") if isinstance(candidate.get("content"), dict) else {}
        parts = candidate_content.get("parts") if isinstance(candidate_content.get("parts"), list) else []
        for part in parts:
            if not isinstance(part, dict):
                continue
            if isinstance(part.get("functionCall"), dict):
                call = part["functionCall"]
                tool_calls.append({
                    "index": candidate_index,
                    "id": str(call.get("id") or call.get("name") or ""),
                    "type": "function",
                    "function": {
                        "name": str(call.get("name") or ""),
                        "arguments": json.dumps(call.get("args") or {}, ensure_ascii=False),
                    },
                })
                continue
            text = part.get("text")
            if text is None:
                continue
            if part.get("thought") is True:
                thinking += str(text)
            else:
                content += str(text)
    raw_finish = ""
    for candidate in candidates:
        if isinstance(candidate, dict) and candidate.get("finishReason"):
            raw_finish = str(candidate["finishReason"])
            break
    finish_reason = _normalize_gemini_finish_reason(raw_finish)
    return content, thinking, tool_calls, finish_reason


def _normalize_gemini_finish_reason(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"", "stop"}:
        return "stop"
    if normalized in {"max_tokens", "length"}:
        return "length"
    if normalized in {"safety", "recitation", "blocklist", "prohibited_content"}:
        return "content_filter"
    if "function" in normalized:
        return "tool_calls"
    return normalized


def _gemini_usage(raw: Any) -> LLMUsage | None:
    if not isinstance(raw, dict):
        return None
    mapped = {
        "prompt_tokens": raw.get("promptTokenCount"),
        "completion_tokens": raw.get("candidatesTokenCount"),
        "total_tokens": raw.get("totalTokenCount"),
        "cached_tokens": raw.get("cachedContentTokenCount"),
    }
    # Gemini frequently includes an empty ``usageMetadata`` object on stream
    # chunks.  Do not turn that absence of accounting into a synthetic
    # all-zero usage event.
    if not any(value is not None for value in mapped.values()):
        return None
    return _usage_from_raw(mapped)


def build_profiled_anthropic_request(
    messages: list[dict[str, Any]],
    profile: dict[str, Any],
    *,
    model: str,
    max_tokens: int,
    temperature: float,
    stream: bool = False,
    top_p: float | None = None,
    thinking_enabled: bool = False,
    thinking_budget: int = 0,
    reasoning_level: str = "",
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] | None = None,
    capability: str = "",
    endpoint_fallback: str = "/anthropic/v1/messages",
) -> dict[str, Any]:
    system_content = ""
    chat_messages: list[dict[str, Any]] = []
    for message in messages:
        if message.get("role") == "system":
            system_content += str(message.get("content") or "") + "\n"
        else:
            chat_messages.append(
                _anthropic_message_from_openai_message(
                    message,
                    profile=profile,
                    model=model,
                )
            )

    if capability.strip().lower() == "text":
        strip_unsupported_content(chat_messages, capability)

    payload: dict[str, Any] = {
        "model": model,
        "messages": chat_messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if top_p is not None:
        payload["top_p"] = top_p
    if stream:
        payload["stream"] = True
    if system_content:
        payload["system"] = system_content.strip()

    if tools:
        payload["tools"] = [_anthropic_tool_from_openai_tool(tool) for tool in tools]
    if tool_choice is not None:
        payload["tool_choice"] = _anthropic_tool_choice_from_openai_choice(tool_choice)

    chat_messages = _merge_anthropic_tool_result_messages(chat_messages)
    payload["messages"] = chat_messages

    variables = {"thinking_budget": thinking_budget}
    apply_request_payload(payload, profile=profile, variables=variables)
    apply_thinking_payload(
        payload,
        profile=profile,
        thinking_budget=thinking_budget,
        reasoning_level=reasoning_level,
        thinking_enabled=thinking_enabled,
    )
    request_config = _extra_dict(profile.get("request"))
    _enforce_anthropic_manual_thinking_limits(payload)
    thinking_active = _anthropic_thinking_is_active(payload)
    # Anthropic's thinking modes do not accept the usual low-temperature
    # sampling controls.  Newer models also reject non-default values even
    # when thinking is off, so profiles can opt into the unconditional form.
    if request_config.get("omit_sampling_always") or (
        request_config.get("omit_sampling_when_reasoning") and thinking_active
    ):
        for key in ("temperature", "top_p", "top_k"):
            payload.pop(key, None)
    return {
        "endpoint": endpoint_path(profile, endpoint_fallback),
        "payload": payload,
    }


def _anthropic_thinking_is_active(payload: dict[str, Any]) -> bool:
    thinking = payload.get("thinking")
    if not isinstance(thinking, dict):
        return False
    thinking_type = str(thinking.get("type") or "").strip().lower()
    return thinking_type not in {"", "disabled", "none", "off"}


def _enforce_anthropic_manual_thinking_limits(payload: dict[str, Any]) -> None:
    """Keep legacy Anthropic manual-thinking requests API-valid.

    Anthropic requires ``budget_tokens >= 1024`` and ``budget_tokens`` to be
    strictly less than ``max_tokens``.  The latter is easy to violate because
    Core historically used a 4096 output default while the old thinking
    default was 10000.  Expand the output ceiling only when needed so the
    selected thinking level is not silently weakened.
    """

    thinking = payload.get("thinking")
    if not isinstance(thinking, dict) or str(thinking.get("type") or "").strip().lower() != "enabled":
        return
    try:
        budget = max(1_024, int(thinking.get("budget_tokens") or 0))
    except (TypeError, ValueError):
        return
    thinking["budget_tokens"] = budget
    try:
        max_tokens = int(payload.get("max_tokens") or 0)
    except (TypeError, ValueError):
        max_tokens = 0
    if max_tokens <= budget:
        payload["max_tokens"] = budget + 1


def _anthropic_message_from_openai_message(
    message: dict[str, Any],
    *,
    profile: dict[str, Any] | None = None,
    model: str = "",
) -> dict[str, Any]:
    role = str(message.get("role") or "")
    if role == "tool":
        return {
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": str(message.get("tool_call_id") or ""),
                "content": _anthropic_tool_result_content(message.get("content")),
            }],
        }

    converted: dict[str, Any] = {
        key: copy.deepcopy(value)
        for key, value in message.items()
        if key not in {"metadata", "provider_state", "tool_calls", "content"}
    }
    converted["role"] = "assistant" if role == "assistant" else "user"
    if role == "assistant" and isinstance(profile, dict):
        restored = _anthropic_blocks_from_state(
            message.get("provider_state"),
            profile=profile,
            model=model,
        )
        if restored is not None:
            converted["content"] = restored
            return converted
    blocks = _anthropic_content_from_openai_content(message.get("content"))
    if role == "assistant":
        if not isinstance(blocks, list):
            blocks = [{"type": "text", "text": str(blocks or "")}]
        for tool_call in message.get("tool_calls") or []:
            if not isinstance(tool_call, dict):
                continue
            function = tool_call.get("function") if isinstance(tool_call.get("function"), dict) else {}
            arguments = function.get("arguments") or {}
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = {}
            blocks.append({
                "type": "tool_use",
                "id": str(tool_call.get("id") or ""),
                "name": str(function.get("name") or ""),
                "input": arguments if isinstance(arguments, dict) else {},
            })
        converted["content"] = blocks
    else:
        converted["content"] = blocks
    return converted


def _merge_anthropic_tool_result_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Coalesce adjacent tool results into one Anthropic user message."""

    result: list[dict[str, Any]] = []
    for message in messages:
        content = message.get("content") if isinstance(message, dict) else None
        is_tool_result = (
            isinstance(message, dict)
            and message.get("role") == "user"
            and isinstance(content, list)
            and bool(content)
            and all(
                isinstance(block, dict) and block.get("type") == "tool_result"
                for block in content
            )
        )
        previous_content = result[-1].get("content") if result else None
        previous_is_tool_result = (
            bool(result)
            and result[-1].get("role") == "user"
            and isinstance(previous_content, list)
            and bool(previous_content)
            and all(
                isinstance(block, dict) and block.get("type") == "tool_result"
                for block in previous_content
            )
        )
        if is_tool_result and previous_is_tool_result:
            previous_content.extend(copy.deepcopy(content))
        else:
            result.append(message)
    return result


def _anthropic_tool_result_content(content: Any) -> str | list[dict[str, Any]]:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return copy.deepcopy(content)
    return json.dumps(content, ensure_ascii=False, default=str)


def _anthropic_tool_from_openai_tool(tool: dict[str, Any]) -> dict[str, Any]:
    function = tool.get("function") if isinstance(tool.get("function"), dict) else tool
    result: dict[str, Any] = {
        "name": str(function.get("name") or ""),
        "input_schema": copy.deepcopy(function.get("parameters") or {"type": "object", "properties": {}}),
    }
    if function.get("description"):
        result["description"] = str(function["description"])
    return result


def _anthropic_tool_choice_from_openai_choice(choice: str | dict[str, Any]) -> dict[str, Any] | None:
    if isinstance(choice, dict):
        choice_type = str(choice.get("type") or "")
        if choice_type == "function":
            function = choice.get("function") if isinstance(choice.get("function"), dict) else {}
            return {"type": "tool", "name": str(function.get("name") or "")}
        if choice_type in {"auto", "any", "tool"}:
            return {"type": "auto" if choice_type == "auto" else choice_type}
        return copy.deepcopy(choice)
    if choice == "auto":
        return {"type": "auto"}
    if choice in {"required", "any"}:
        return {"type": "any"}
    if choice == "none":
        return None
    return {"type": "auto"}


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

    # Delta extraction must happen BEFORE the finish_reason check: some
    # providers send the final tool_call arguments fragment in the same
    # chunk that carries finish_reason.  If we check finish_reason first,
    # that last fragment is silently dropped and the tool-call JSON ends up
    # truncated (→ arguments_parse_error).
    tool_calls_delta = get_path(chunk, response_path(profile, "stream_response", "tool_calls_delta", "choices.0.delta.tool_calls"))
    if tool_calls_delta:
        return LLMStreamEvent(
            kind="tool_call_delta",
            content="",
            raw=chunk,
            finish_reason=str(finish_reason) if finish_reason else None,
            usage=_usage_from_raw(usage) if usage else None,
            metadata={
                "tool_calls_delta": tool_calls_delta,
                **({"finish_reason": finish_reason} if finish_reason else {}),
            },
        )

    reasoning = get_path(chunk, response_path(profile, "stream_response", "reasoning_delta", "choices.0.delta.reasoning_content"))
    if reasoning:
        return LLMStreamEvent(
            kind="thinking_delta",
            content=str(reasoning),
            raw=chunk,
            finish_reason=str(finish_reason) if finish_reason else None,
            usage=_usage_from_raw(usage) if usage else None,
            metadata={"finish_reason": finish_reason} if finish_reason else {},
        )

    content = get_path(chunk, response_path(profile, "stream_response", "content_delta", "choices.0.delta.content"))
    if content:
        return LLMStreamEvent(
            kind="content_delta",
            content=str(content),
            raw=chunk,
            finish_reason=str(finish_reason) if finish_reason else None,
            usage=_usage_from_raw(usage) if usage else None,
            metadata={"finish_reason": finish_reason} if finish_reason else {},
        )

    # A provider finish reason is not the end of the transport.  Usage may be
    # delivered in a later usage-only chunk before [DONE].
    if finish_reason:
        return LLMStreamEvent(
            kind="finish",
            raw=chunk,
            usage=_usage_from_raw(usage) if usage else None,
            finish_reason=str(finish_reason),
            metadata={"finish_reason": finish_reason},
        )

    return None


def normalize_response_with_profile(
    response: dict[str, Any],
    profile: dict[str, Any],
    *,
    model: str = "",
) -> dict[str, Any]:
    content_path = response_path(profile, "non_stream_response", "content", "choices.0.message.content")
    reasoning_path = response_path(profile, "non_stream_response", "reasoning", "choices.0.message.reasoning_content")
    tool_calls_path = response_path(profile, "non_stream_response", "tool_calls", "choices.0.message.tool_calls")
    finish_path = response_path(profile, "non_stream_response", "finish_reason", "choices.0.finish_reason")
    usage_path = response_path(profile, "non_stream_response", "usage", "usage")
    message_path = response_path(profile, "non_stream_response", "message", "choices.0.message")

    raw_content = get_path(response, content_path)
    raw_thinking = get_path(response, reasoning_path)
    raw_tool_calls = get_path(response, tool_calls_path)
    finish_reason = str(get_path(response, finish_path, "stop") or "stop")
    usage = _usage_from_raw(get_path(response, usage_path))

    result = {
        "content": raw_content if isinstance(raw_content, str) else ("" if raw_content is None else str(raw_content)),
        "thinking": raw_thinking if isinstance(raw_thinking, str) else ("" if raw_thinking is None else str(raw_thinking)),
        "tool_calls": raw_tool_calls if isinstance(raw_tool_calls, list) else None,
        "finish_reason": finish_reason,
        "usage": usage.to_dict() if usage is not None else None,
    }
    provider_state = _openai_message_provider_state(
        get_path(response, message_path, {}),
        profile,
        model=model,
    )
    if provider_state is not None:
        result["provider_state"] = provider_state
    return result


def normalize_anthropic_response_with_profile(
    response: dict[str, Any],
    profile: dict[str, Any],
    *,
    model: str = "",
) -> dict[str, Any]:
    blocks_path = response_path(profile, "non_stream_response", "content_blocks", "content")
    usage_path = response_path(profile, "non_stream_response", "usage", "usage")
    blocks = get_path(response, blocks_path, [])

    content = ""
    thinking = ""
    tool_calls: list[dict[str, Any]] = []
    if isinstance(blocks, list):
        for block in blocks:
            if not isinstance(block, dict):
                continue
            block_type = str(block.get("type") or "")
            if block_type == "thinking":
                thinking += str(block.get("thinking") or "")
            elif block_type == "text":
                content += str(block.get("text") or "")
            elif block_type == "tool_use":
                tool_calls.append({
                    "id": str(block.get("id") or ""),
                    "type": "function",
                    "function": {
                        "name": str(block.get("name") or ""),
                        "arguments": json.dumps(block.get("input") or {}, ensure_ascii=False),
                    },
                })

    usage = _usage_from_raw(get_path(response, usage_path))
    result = {
        "content": content,
        "thinking": thinking,
        "usage": usage.to_dict() if usage is not None else None,
        "finish_reason": str(response.get("stop_reason") or "stop"),
    }
    if tool_calls:
        result["tool_calls"] = tool_calls
    provider_state = _anthropic_provider_state(blocks, profile, model=model)
    if provider_state is not None:
        result["provider_state"] = provider_state
    return result


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
        # Literal substring match — treating the configured value as a regex
        # made "." and other metacharacters behave unexpectedly and let a
        # malformed pattern raise re.error (audit 10 S3).
        if text and text in lowered:
            return True
    return False


def _matches_model(profile: dict[str, Any], model_id: str) -> bool:
    return _matches_text_patterns(
        model_id,
        profile.get("match_model") or profile.get("match_model_id") or [],
    )


def _matches_provider(profile: dict[str, Any], provider_name: str) -> bool:
    return _matches_text_patterns(provider_name, profile.get("match_provider") or [])


def _matches_text_patterns(value: str, patterns: Any) -> bool:
    text = str(value or "").lower()
    if isinstance(patterns, str):
        patterns = [patterns]
    if not text or not isinstance(patterns, (list, tuple, set)):
        return False
    return any(str(pattern).lower() in text for pattern in patterns if str(pattern))


def _best_matching_profile(
    profiles: dict[str, dict[str, Any]],
    key: str,
    value: str,
    *,
    api_type: str = "",
) -> dict[str, Any] | None:
    candidates: list[tuple[int, dict[str, Any]]] = []
    for item in profiles.values():
        if not _profile_protocol_matches_api_type(item, api_type):
            continue
        patterns = item.get(key) or []
        if isinstance(patterns, str):
            patterns = [patterns]
        matched = [str(pattern) for pattern in patterns if str(pattern) and str(pattern).lower() in str(value).lower()]
        if matched:
            candidates.append((max(len(pattern) for pattern in matched), item))
    if not candidates:
        return None
    _, best = max(candidates, key=lambda candidate: candidate[0])
    return copy.deepcopy(best)


def _profile_protocol_matches_api_type(profile: dict[str, Any], api_type: str) -> bool:
    """Keep model-name matchers from crossing provider protocol boundaries."""

    protocol = str(profile.get("protocol") or "").strip().lower()
    api = str(api_type or "").strip().lower()
    if not protocol or not api:
        return True
    if api in {"anthropic", "anthropic-messages"}:
        return protocol == "anthropic-messages"
    if api in {"gemini", "gemini-generative-language", "google", "google-gemini"}:
        return protocol in {"gemini", "gemini-generative-language"}
    if api in {"responses", "openai-responses"}:
        return protocol in {"responses", "openai-responses"}
    if api in {"openai", "openai-chat", "openai-compatible", "grok", "xai"}:
        return protocol in {
            "openai",
            "openai-chat",
            "openai-chat-completions",
            "openai-compatible",
        }
    return True


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
    "build_profiled_gemini_request",
    "build_profiled_openai_request",
    "build_profiled_responses_request",
    "deep_merge",
    "endpoint_path",
    "get_path",
    "load_adapter_profiles_from_dirs",
    "load_jsonc",
    "normalize_anthropic_response_with_profile",
    "normalize_gemini_response_with_profile",
    "normalize_gemini_stream_event",
    "normalize_response_with_profile",
    "normalize_responses_response_with_profile",
    "normalize_responses_stream_event",
    "normalize_stream_chunk_with_profile",
    "reasoning_off_supported",
    "resolve_adapter_profile_from_profiles",
    "response_path",
    "set_payload_fields",
    "strip_jsonc",
    "strip_unsupported_content",
    "unset_payload_fields",
]
