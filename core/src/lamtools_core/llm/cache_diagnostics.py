"""Small, privacy-preserving diagnostics for provider prompt-cache misses."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

_SIGNING_KEY = secrets.token_bytes(32)
_TRACKER_LOCK = threading.Lock()
_MAX_TRACKED_SESSIONS = 128
_MAX_COMPARED_MESSAGES = 512
_LOW_HIT_RATE = 0.50
_SUDDEN_DROP = 0.30


@dataclass(frozen=True)
class _RequestShape:
    model: str
    message_count: int
    message_comparison_limited: bool
    message_signatures: tuple[str, ...]
    message_roles: tuple[str, ...]
    message_content_lengths: tuple[int, ...]
    tool_signature: str
    tool_count: int
    options_signature: str
    provider: str
    protocol: str
    routed_model: str
    endpoint_host: str
    session_affinity_header: bool


@dataclass(frozen=True)
class _Observation:
    request: _RequestShape
    cache_hit_rate: float | None
    forensic_record_id: str | None = None


_OBSERVATIONS: OrderedDict[str, _Observation] = OrderedDict()


def record_cache_observation(
    session_id: str,
    request: Any,
    usage: Any,
    route: Any = None,
) -> dict[str, Any] | None:
    """Remember a successful request and describe unusually low cache hits.

    Prompt text and fingerprints never leave process memory. The returned
    diagnostic contains only counts, lengths, roles, and observed changes.
    """
    forensic_id = route.get("forensic_record_id") if isinstance(route, dict) else None
    shape = _request_shape(request, route)
    rate = _reported_hit_rate(usage)
    key = str(session_id or "").strip()

    with _TRACKER_LOCK:
        previous = _OBSERVATIONS.get(key) if key else None
        if key:
            _OBSERVATIONS[key] = _Observation(
                request=shape,
                forensic_record_id=forensic_id,
                cache_hit_rate=(rate if rate is not None else (previous.cache_hit_rate if previous else None)),
            )
            _OBSERVATIONS.move_to_end(key)
            while len(_OBSERVATIONS) > _MAX_TRACKED_SESSIONS:
                _OBSERVATIONS.popitem(last=False)

    if rate is None:
        return None

    previous_rate = previous.cache_hit_rate if previous else None
    drop = previous_rate - rate if previous_rate is not None else None
    low = rate < _LOW_HIT_RATE
    sudden_drop = drop is not None and drop >= _SUDDEN_DROP
    if not low and not sudden_drop:
        return None

    diagnostic: dict[str, Any] = {
        "version": 1,
        "forensic_record_id": forensic_id,
        "previous_forensic_record_id": previous.forensic_record_id if previous else None,
        "trigger": "low_hit_rate" if low else "sudden_hit_rate_drop",
        "cache_hit_rate": round(rate, 4),
        "previous_cache_hit_rate": round(previous_rate, 4) if previous_rate is not None else None,
        "drop_percentage_points": round(drop * 100, 1) if drop is not None else None,
        "prompt_tokens": _usage_int(usage, "prompt_tokens"),
        "cached_tokens": _usage_int(usage, "cached_tokens"),
        "cache_creation_tokens": _usage_int(usage, "cache_creation_tokens"),
        "request_model": shape.model,
        "provider": shape.provider or None,
        "protocol": shape.protocol or None,
        "routed_model": shape.routed_model or None,
        "endpoint_host": shape.endpoint_host or None,
        "session_affinity_header": shape.session_affinity_header,
        "message_count": shape.message_count,
        "message_comparison_limited": shape.message_comparison_limited,
        "tool_count": shape.tool_count,
        "baseline_available": previous is not None,
    }

    if previous is None:
        diagnostic["comparison"] = "no_prior_successful_request_in_this_process"
        diagnostic["observed_changes"] = ["no_comparable_request_baseline"]
        return diagnostic

    old = previous.request
    common = 0
    for before, now in zip(old.message_signatures, shape.message_signatures):
        if before != now:
            break
        common += 1

    first_changed = common if common < min(len(old.message_signatures), len(shape.message_signatures)) else None
    comparison_complete = not (old.message_comparison_limited or shape.message_comparison_limited)
    prior_is_prefix = (
        comparison_complete and first_changed is None and old.message_count < shape.message_count
    )
    current_is_prefix = (
        comparison_complete and first_changed is None and shape.message_count < old.message_count
    )
    toolset_changed = old.tool_signature != shape.tool_signature
    options_changed = old.options_signature != shape.options_signature
    model_changed = old.model != shape.model or old.routed_model != shape.routed_model
    provider_changed = (
        old.provider != shape.provider
        or old.protocol != shape.protocol
        or old.endpoint_host != shape.endpoint_host
        or old.session_affinity_header != shape.session_affinity_header
    )

    changes: list[str] = []
    if model_changed:
        changes.append("model_changed")
    if provider_changed:
        changes.append("provider_protocol_or_endpoint_changed")
    if first_changed is not None:
        old_role = old.message_roles[first_changed]
        new_role = shape.message_roles[first_changed]
        if first_changed == 0 and "system" in {old_role, new_role}:
            changes.append("system_prompt_changed_at_0")
        else:
            changes.append(f"message_prefix_changed_at_{first_changed}")
    elif prior_is_prefix:
        changes.append("request_extended_at_tail")
    elif current_is_prefix:
        changes.append("request_truncated_after_common_prefix")
    elif old.message_count != shape.message_count:
        changes.append("message_count_changed")
    if not comparison_complete:
        changes.append(f"message_comparison_limited_to_first_{_MAX_COMPARED_MESSAGES}")
    if toolset_changed:
        changes.append("toolset_changed")
    if options_changed:
        changes.append("request_options_changed")
    if not changes:
        changes.append("request_shape_stable; check provider_cache_pool_ttl_routing_or_policy")

    diagnostic.update({
        "comparison": "previous_successful_request_in_this_process",
        "previous_request_model": old.model,
        "previous_provider": old.provider or None,
        "previous_protocol": old.protocol or None,
        "previous_routed_model": old.routed_model or None,
        "previous_endpoint_host": old.endpoint_host or None,
        "previous_session_affinity_header": old.session_affinity_header,
        "previous_message_count": old.message_count,
        "previous_message_comparison_limited": old.message_comparison_limited,
        "message_comparison_limit": _MAX_COMPARED_MESSAGES,
        "common_prefix_messages": common,
        "first_changed_message_index": first_changed,
        "prior_request_is_prefix": prior_is_prefix,
        "current_request_is_prefix": current_is_prefix,
        "toolset_changed": toolset_changed,
        "tool_count_before": old.tool_count,
        "tool_count_after": shape.tool_count,
        "observed_changes": changes,
    })
    if first_changed is not None:
        diagnostic["first_changed_message"] = {
            "index": first_changed,
            "previous_role": old.message_roles[first_changed],
            "current_role": shape.message_roles[first_changed],
            "previous_content_chars": old.message_content_lengths[first_changed],
            "current_content_chars": shape.message_content_lengths[first_changed],
        }
    return diagnostic


def _request_shape(request: Any, route: Any) -> _RequestShape:
    all_messages = list(getattr(request, "messages", None) or [])
    messages = all_messages[:_MAX_COMPARED_MESSAGES]
    message_signatures = tuple(_message_signature(message) for message in messages)
    route_data = route if isinstance(route, dict) else {}
    provider = _safe_label(route_data.get("provider"))
    protocol = _safe_label(route_data.get("protocol"))
    routed_model = _safe_label(route_data.get("model"))
    return _RequestShape(
        model=_safe_label(getattr(request, "model", "")),
        message_count=len(all_messages),
        message_comparison_limited=len(all_messages) > _MAX_COMPARED_MESSAGES,
        message_signatures=message_signatures,
        message_roles=tuple(_safe_label(getattr(message, "role", "")) for message in messages),
        message_content_lengths=tuple(_content_length(getattr(message, "content", "")) for message in messages),
        tool_signature=_private_digest(list(getattr(request, "tools", None) or [])),
        tool_count=len(getattr(request, "tools", None) or []),
        options_signature=_private_digest({
            "tool_choice": getattr(request, "tool_choice", None),
            "parallel_tool_calls": getattr(request, "parallel_tool_calls", None),
            "response_format": getattr(request, "response_format", None),
        }),
        provider=provider,
        protocol=protocol,
        routed_model=routed_model,
        endpoint_host=_safe_label(route_data.get("endpoint_host")),
        session_affinity_header=bool(route_data.get("session_affinity_header")),
    )


def _message_signature(message: Any) -> str:
    # Tail/historical markers are adapter routing decisions, not provider
    # bytes; including them would flag a cache "change" when a tail update is
    # retyped in place on the next request.
    material = {
        "role": getattr(message, "role", ""),
        "content": getattr(message, "content", ""),
        "name": getattr(message, "name", ""),
        "tool_call_id": getattr(message, "tool_call_id", ""),
        "tool_calls": [call.to_dict() for call in (getattr(message, "tool_calls", None) or [])],
        "provider_state": getattr(message, "provider_state", None),
    }
    return _private_digest(material)


def _private_digest(value: Any) -> str:
    digest = hmac.new(_SIGNING_KEY, digestmod=hashlib.sha256)
    encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    for chunk in encoder.iterencode(value):
        digest.update(chunk.encode("utf-8", errors="replace"))
    return digest.hexdigest()


def _reported_hit_rate(usage: Any) -> float | None:
    if usage is None:
        return None
    reported = bool(getattr(usage, "cache_usage_reported", False))
    prompt_tokens = _usage_int(usage, "prompt_tokens")
    cached_tokens = _usage_int(usage, "cached_tokens")
    if not reported or prompt_tokens <= 0:
        return None
    return min(1.0, max(0.0, cached_tokens / prompt_tokens))


def _usage_int(usage: Any, field: str) -> int:
    try:
        return max(0, int(getattr(usage, field, 0) or 0))
    except (TypeError, ValueError):
        return 0


def _content_length(value: Any) -> int:
    if isinstance(value, str):
        return len(value)
    if isinstance(value, dict):
        return sum(_content_length(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return sum(_content_length(item) for item in value)
    return 0


def _safe_label(value: Any) -> str:
    return str(value or "").strip()[:160]
