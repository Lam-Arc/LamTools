"""Usage-anchored prompt measurement for the compaction trigger.

Automatic compaction is a pre-sampling decision: it must be made *before* a
request is sent, while provider token counts only arrive *after* it.  Local
estimators close that gap, but their error can be large (CJK/emoji-heavy text,
provider framing), so a context can grow far past the window while the trigger
keeps seeing a small number.

Every successful response, however, reports the true prompt size of the request
that was just sent.  That number is an *anchor*: as long as the next request
only appends messages to the anchored prefix and keeps the same request-level
overhead (tool definitions and response format), the real prompt size is

    anchor_prompt_tokens + estimate(messages after the anchored prefix)

The bulk of the prompt is then provider-exact and only the appended tail —
usually one assistant turn plus its tool results — has to be estimated.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from lamtools_core.context_compaction_budget import (
    TokenMeasurement,
    measure_for_compaction_trigger,
)
from lamtools_core.llm import ChatMessage, LLMRequest
from lamtools_core.tokens import estimate_message_tokens

#: ``state.metadata`` key holding the most recent provider usage anchor.
USAGE_ANCHOR_METADATA_KEY = "context_usage_anchor"

#: ``TokenMeasurement.source`` value for an anchor-backed measurement.
USAGE_ANCHOR_SOURCE = "provider_anchor"

_FINGERPRINT_BYTES = 16
_FINGERPRINT_SEPARATOR = b"\x1e"


@dataclass(frozen=True, slots=True)
class RequestPrefix:
    """The send-time shape of a request, cheap to re-verify later."""

    message_count: int
    prefix_digest: str
    overhead_digest: str


def _canonical_message(message: ChatMessage) -> str:
    """Serialise the provider-visible payload of one message.

    ``metadata`` is deliberately excluded: it is application bookkeeping (and is
    stripped before dispatch anyway), so message identity must not depend on it
    — otherwise an anchor recorded for the sent request would never match the
    same message rebuilt from durable history.
    """
    tool_calls = [
        {
            "id": str(call.id or ""),
            "name": str(call.name or ""),
            "arguments": call.arguments,
        }
        for call in (message.tool_calls or [])
    ]
    return json.dumps(
        {
            "role": str(message.role or ""),
            "content": message.content,
            "name": str(message.name or ""),
            "tool_call_id": str(message.tool_call_id or ""),
            "tool_calls": tool_calls,
            "provider_state": message.provider_state,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=repr,
    )


def _digest(parts: Sequence[str]) -> str:
    hasher = hashlib.blake2b(digest_size=_FINGERPRINT_BYTES)
    for part in parts:
        hasher.update(part.encode("utf-8"))
        hasher.update(_FINGERPRINT_SEPARATOR)
    return hasher.hexdigest()


def message_prefix_digest(messages: Sequence[ChatMessage]) -> str:
    """Return a digest of the provider-visible payload of *messages*."""
    return _digest([_canonical_message(message) for message in messages])


def request_overhead_digest(request: LLMRequest) -> str:
    """Digest the non-message part of a request that still counts as prompt.

    Tool definitions and the response format are part of every prompt; when
    they change, the anchored prefix no longer explains the whole prompt.
    """
    return _digest([
        json.dumps(
            {
                "tools": request.tools,
                "tool_choice": request.tool_choice,
                "response_format": request.response_format,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=repr,
        )
    ])


def describe_request(request: LLMRequest) -> RequestPrefix:
    """Capture the shape of a request as it is about to be dispatched."""
    return RequestPrefix(
        message_count=len(request.messages),
        prefix_digest=message_prefix_digest(request.messages),
        overhead_digest=request_overhead_digest(request),
    )


def effective_prompt_tokens(
    *,
    prompt_tokens: int,
    cached_tokens: int = 0,
    cache_creation_tokens: int = 0,
) -> int:
    """Resolve the real input size from provider usage counters.

    OpenAI-style usage counts cache reads *inside* ``prompt_tokens``.  Providers
    that report cache reads as separate fields (Anthropic-style ``input_tokens``
    excludes them) would otherwise be undercounted, which is the dangerous
    direction for a context-window trigger.  Cache counters are therefore added
    only when they exceed the reported prompt — unambiguous evidence that they
    sit outside it — which can never lower the result.
    """
    reported = max(0, int(prompt_tokens or 0))
    cache_total = max(0, int(cached_tokens or 0)) + max(
        0, int(cache_creation_tokens or 0)
    )
    return max(reported, cache_total)


def build_usage_anchor(
    prefix: RequestPrefix,
    *,
    prompt_tokens: int,
    cached_tokens: int = 0,
    cache_creation_tokens: int = 0,
    model_id: str = "",
) -> dict[str, Any] | None:
    """Build the durable anchor for a completed request, or ``None``.

    ``None`` means the provider gave us nothing usable to anchor on; callers
    then keep whatever anchor they had (usage often includes cached-token
    variants, but a zero/absent prompt count is not a measurement).
    """
    tokens = effective_prompt_tokens(
        prompt_tokens=prompt_tokens,
        cached_tokens=cached_tokens,
        cache_creation_tokens=cache_creation_tokens,
    )
    if tokens <= 0 or prefix.message_count <= 0:
        return None
    return {
        "prompt_tokens": tokens,
        "message_count": prefix.message_count,
        "prefix_digest": prefix.prefix_digest,
        "overhead_digest": prefix.overhead_digest,
        "model_id": str(model_id or ""),
    }


def measure_with_usage_anchor(
    messages: Sequence[ChatMessage],
    anchor: Mapping[str, Any] | None,
    *,
    trigger_tokens: int,
    model_id: str = "",
    overhead_digest: str = "",
) -> TokenMeasurement | None:
    """Measure *messages* from an anchor, or ``None`` when it does not apply.

    The anchor applies only while it still describes a prefix of the current
    request: same model, same request overhead, and a byte-identical
    provider-visible prefix.  Any mismatch means the stored number no longer
    explains this prompt, and the caller must fall back to local estimation
    rather than trust a stale count.
    """
    if not isinstance(anchor, Mapping):
        return None
    try:
        prompt_tokens = int(anchor.get("prompt_tokens") or 0)
        message_count = int(anchor.get("message_count") or 0)
    except (TypeError, ValueError):
        return None
    if prompt_tokens <= 0 or message_count <= 0:
        return None
    if message_count > len(messages):
        return None
    if str(anchor.get("model_id") or "") != str(model_id or ""):
        return None
    if str(anchor.get("overhead_digest") or "") != str(overhead_digest or ""):
        return None
    anchored_prefix = list(messages)[:message_count]
    if str(anchor.get("prefix_digest") or "") != message_prefix_digest(anchored_prefix):
        return None
    if prompt_tokens >= trigger_tokens:
        # Already over the trigger: the decision does not depend on the tail, so
        # skip estimating it.  The reported number is the provider count of the
        # anchored prefix, never a local estimate.
        return TokenMeasurement(
            tokens=prompt_tokens,
            exact=True,
            source=USAGE_ANCHOR_SOURCE,
        )
    tail = list(messages)[message_count:]
    tail_measurement = measure_for_compaction_trigger(
        tail,
        # The tail only has to answer "does it push the anchor over the
        # trigger", so it inherits the shared fast-near-threshold policy.
        trigger_tokens=max(1, trigger_tokens - prompt_tokens),
        fast_estimate=lambda current: estimate_message_tokens(
            [message.to_dict() for message in current],
            fast=True,
        ),
        exact_estimate=lambda current: estimate_message_tokens(
            [message.to_dict() for message in current],
        ),
    )
    return TokenMeasurement(
        tokens=prompt_tokens + tail_measurement.tokens,
        exact=True,
        source=USAGE_ANCHOR_SOURCE,
    )


__all__ = [
    "RequestPrefix",
    "USAGE_ANCHOR_METADATA_KEY",
    "USAGE_ANCHOR_SOURCE",
    "build_usage_anchor",
    "describe_request",
    "effective_prompt_tokens",
    "measure_with_usage_anchor",
    "message_prefix_digest",
    "request_overhead_digest",
]
