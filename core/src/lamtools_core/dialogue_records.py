"""Append-only dialogue control records (compaction / rollback).

A thread's model-visible history is a dialogue log.  Compaction and rollback
change *which* part of that log the model sees, but today they do it by
rewriting the log in place, so the change itself leaves no durable trace.  This
module defines the durable control record that is appended *in addition to*
(never instead of) the existing rewrite behaviour: one record per compaction and
one per rollback, carrying everything a later replay needs.

A compaction record is self-sufficient for the *active* history it produced:

* ``summary``: the full, untruncated summary text (the UI card truncates to
  20k; replay must not),
* ``folded``: identity of every message that was folded into the summary,
* ``retained``: the ordered messages that stayed in the model's view, stored
  inline so the record can be verified against what was actually sent,
* ``params``: trigger, target/threshold tokens, retained steps, before/after
  token and message counts, segment count, strategy and execution model,
* ``watermark``: the highest history sequence number the compaction considered.

Two digests prove the recorded product reproduces the sent product exactly:

* ``sent_digest`` is computed from the actual messages placed in the model
  request (an independent read of the request), and
* ``effective_digest`` is computed from the record's own fields (summary +
  retained).  Equality is the "record rebuilds what was sent" contract.

The rollback record is a marker, not a delete (this batch keeps the delete):
it names the target watermark, the detached range, and the new branch epoch
(monotonic per thread), so a future replay can detach a suffix without losing
it.

Identity: prefer a message's stable id (``metadata.message_id`` / ``metadata.id``),
fall back to its history sequence number (``metadata.history_seq``).  Messages
with neither (created inside the current run and not yet persisted) are stored
inline only and marked ``unidentified``.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Callable

from lamtools_core.llm import ChatMessage

COMPACTION_RECORD = "compaction"
ROLLBACK_RECORD = "rollback"

# Wire-relevant message fields.  ``metadata`` is application bookkeeping the
# model never sees, so it is excluded from the "what was sent" digest.
_WIRE_FIELDS = ("role", "content", "name", "tool_call_id", "tool_calls", "provider_state")

_STABLE_ID_KEYS = ("message_id", "id")


__all__ = [
    "COMPACTION_RECORD",
    "ROLLBACK_RECORD",
    "build_compaction_record",
    "build_rollback_record",
    "canonical_message",
    "effective_digest",
    "message_identity",
    "message_ref",
    "verify_compaction_record",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _message_dict(message: ChatMessage | dict[str, Any]) -> dict[str, Any]:
    if isinstance(message, ChatMessage):
        return message.to_dict()
    return dict(message) if isinstance(message, dict) else {}


def canonical_message(message: ChatMessage | dict[str, Any]) -> dict[str, Any]:
    """Return the wire-relevant projection of ``message`` (metadata dropped).

    The result is what a digest over "what the model saw" must be built from:
    role/content plus the tool call and provider-continuation material, and
    nothing from the application's bookkeeping metadata.
    """
    raw = _message_dict(message)
    result: dict[str, Any] = {}
    for field in _WIRE_FIELDS:
        if field in raw:
            value = raw[field]
            if field == "content" and value is None:
                value = ""
            result[field] = value
    result.setdefault("role", str(raw.get("role") or ""))
    result.setdefault("content", raw.get("content") if raw.get("content") is not None else "")
    return result


def message_identity(message: ChatMessage | dict[str, Any]) -> str | None:
    """Stable identity string for a message, or ``None`` when it has no anchor."""
    metadata = (
        message.metadata
        if isinstance(message, ChatMessage)
        else (message.get("metadata") if isinstance(message, dict) else None)
    )
    if not isinstance(metadata, dict):
        return None
    for key in _STABLE_ID_KEYS:
        raw = metadata.get(key)
        value = str(raw or "").strip()
        if value:
            return f"message_id:{value}"
    raw_seq = metadata.get("history_seq")
    try:
        seq = int(raw_seq)
    except (TypeError, ValueError):
        return None
    return f"history_seq:{seq}" if seq > 0 else None


def message_ref(message: ChatMessage | dict[str, Any]) -> dict[str, Any]:
    """A compact identity descriptor for a folded message."""
    identity = message_identity(message)
    canonical = canonical_message(message)
    content_text = canonical.get("content")
    if not isinstance(content_text, str):
        content_text = json.dumps(content_text, ensure_ascii=False, default=str)
    return {
        "ref": identity,
        "unidentified": identity is None,
        "role": str(canonical.get("role") or ""),
        "chars": len(content_text),
        "digest": _digest(canonical),
    }


def _retained_entry(message: ChatMessage | dict[str, Any]) -> dict[str, Any]:
    return {
        "ref": message_identity(message),
        "message": canonical_message(message),
    }


def effective_digest(messages: list[ChatMessage | dict[str, Any]]) -> str:
    """Digest of an ordered message list using the wire-relevant projection."""
    return _digest([canonical_message(message) for message in messages])


def _max_history_seq(messages: list[ChatMessage | dict[str, Any]]) -> int:
    highest = 0
    for message in messages:
        metadata = (
            message.metadata
            if isinstance(message, ChatMessage)
            else (message.get("metadata") if isinstance(message, dict) else None)
        )
        if not isinstance(metadata, dict):
            continue
        try:
            seq = int(metadata.get("history_seq"))
        except (TypeError, ValueError):
            continue
        if seq > highest:
            highest = seq
    return highest


def build_compaction_record(
    *,
    trigger: str,
    summary_message: ChatMessage,
    retained: list[ChatMessage],
    folded: list[ChatMessage],
    sent_messages: list[ChatMessage],
    prefix_count: int = 0,
    limit_tokens: int = 0,
    trigger_tokens: int = 0,
    retained_steps: int = 0,
    before_tokens: int = 0,
    after_tokens: int = 0,
    before_messages: int = 0,
    after_messages: int = 0,
    segments: int = 0,
    strategy: str = "",
    execution_model: str = "",
    recent_user_messages: list[str] | None = None,
) -> dict[str, Any]:
    """Build one complete compaction control record.

    ``sent_messages`` is the exact ordered list the model request carried for
    the history portion (``[summary, *retained]``).  It is digested independently
    of the record's own fields so ``effective_digest == sent_digest`` is a real
    fidelity check rather than a tautology.
    """
    retained_entries = [_retained_entry(message) for message in retained]
    record_digest = effective_digest([summary_message, *retained])
    sent = effective_digest(sent_messages)
    watermark = _max_history_seq([summary_message, *retained, *folded])
    return {
        "kind": COMPACTION_RECORD,
        "trigger": str(trigger or ""),
        "summary": str(getattr(summary_message, "content", "") or ""),
        "summary_message": canonical_message(summary_message),
        "folded": {
            "count": len(folded),
            "items": [message_ref(message) for message in folded],
        },
        "retained": retained_entries,
        "prefix_count": int(prefix_count),
        "params": {
            "trigger": str(trigger or ""),
            "limit_tokens": int(limit_tokens),
            "trigger_tokens": int(trigger_tokens),
            "retained_steps": int(retained_steps),
            "before_tokens": int(before_tokens),
            "after_tokens": int(after_tokens),
            "before_messages": int(before_messages),
            "after_messages": int(after_messages),
            "segments": int(segments),
            "strategy": str(strategy or ""),
            "execution_model": str(execution_model or ""),
        },
        "watermark": int(watermark),
        "recent_user_messages": list(recent_user_messages or []),
        "effective_digest": record_digest,
        "sent_digest": sent,
        "digest_match": record_digest == sent,
        "created_at": _now_iso(),
    }


def verify_compaction_record(record: dict[str, Any]) -> dict[str, Any]:
    """Recompute the record's digest and re-check it against the sent digest.

    Returns ``{"integrity": bool, "fidelity": bool, ...}``.  ``integrity`` means
    the record's own fields still hash to ``effective_digest``; ``fidelity``
    means that digest equals the independently captured ``sent_digest``.
    """
    summary_message = record.get("summary_message")
    if not isinstance(summary_message, dict):
        return {
            "integrity": False,
            "fidelity": False,
            "detail": "summary_message missing",
        }
    retained = record.get("retained")
    retained_messages: list[Any] = []
    for entry in retained if isinstance(retained, list) else []:
        if isinstance(entry, dict) and isinstance(entry.get("message"), dict):
            retained_messages.append(entry["message"])
    recomputed = effective_digest([summary_message, *retained_messages])
    stored = str(record.get("effective_digest") or "")
    sent = str(record.get("sent_digest") or "")
    integrity = bool(stored) and recomputed == stored
    fidelity = integrity and sent == recomputed
    return {
        "integrity": integrity,
        "fidelity": fidelity,
        "effective_digest": stored,
        "recomputed_digest": recomputed,
        "sent_digest": sent,
    }


def build_rollback_record(
    *,
    scope: str,
    target_event_seq: int,
    target_history_seq: int,
    detached_event_count: int = 0,
    detached_event_min: int = 0,
    detached_event_max: int = 0,
    detached_history_count: int = 0,
    detached_history_min: int = 0,
    detached_history_max: int = 0,
    branch_epoch: int = 1,
    operation_id: str = "",
) -> dict[str, Any]:
    """Build one rollback marker record.

    The record does not carry the detached content; the append-only dialogue log
    keeps that.  It records the target watermarks, the range that was detached,
    and the new branch epoch so a later replay can detach the suffix without
    deleting it.
    """
    return {
        "kind": ROLLBACK_RECORD,
        "scope": str(scope or "all"),
        "operation_id": str(operation_id or ""),
        "target_event_seq": max(0, int(target_event_seq)),
        "target_history_seq": max(0, int(target_history_seq)),
        "detached": {
            "events": {
                "count": max(0, int(detached_event_count)),
                "min": max(0, int(detached_event_min)),
                "max": max(0, int(detached_event_max)),
            },
            "history": {
                "count": max(0, int(detached_history_count)),
                "min": max(0, int(detached_history_min)),
                "max": max(0, int(detached_history_max)),
            },
        },
        "branch_epoch": max(1, int(branch_epoch)),
        "created_at": _now_iso(),
    }
