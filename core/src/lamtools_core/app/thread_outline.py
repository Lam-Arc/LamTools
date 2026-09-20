"""Build a compact, read-only outline for a Core conversation thread.

The app-server snapshot keeps user-facing ``userMessage`` items outside the
runtime ``core`` projection.  This module deliberately works on that snapshot
shape instead of rendering the full transcript: user prompts are paired with
the last visible ``agentMessage`` text that follows them in the same global
item timeline.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from .queue_state import input_items_text


DEFAULT_THREAD_OUTLINE_CHAR_LIMIT = 240
MAX_THREAD_OUTLINE_CHAR_LIMIT = 4_096


def normalize_thread_outline_char_limit(value: Any = None) -> int:
    """Return a bounded Unicode-character limit for outline text fields."""

    try:
        limit = int(value) if value is not None and value != "" else DEFAULT_THREAD_OUTLINE_CHAR_LIMIT
    except (TypeError, ValueError):
        limit = DEFAULT_THREAD_OUTLINE_CHAR_LIMIT
    return max(1, min(limit, MAX_THREAD_OUTLINE_CHAR_LIMIT))


def build_thread_outline(
    snapshot: Mapping[str, Any] | None,
    *,
    thread_id: str | None = None,
    char_limit: int = DEFAULT_THREAD_OUTLINE_CHAR_LIMIT,
) -> dict[str, Any]:
    """Return the stable lightweight outline contract for one thread.

    Ordering uses item sequence anchors used by the frontend, with
    deterministic order-list/source fallbacks for legacy rows that do not have
    an anchor.
    """

    state = snapshot if isinstance(snapshot, Mapping) else {}
    resolved_thread_id = str(thread_id or state.get("thread_id") or "")
    limit = normalize_thread_outline_char_limit(char_limit)
    timeline = _timeline_items(state)

    turn_by_id = _turn_metadata(state)
    outlines: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for entry in timeline:
        item = entry["item"]
        item_type = _item_type(item)
        if entry["source"] == "outer" and item_type == "userMessage" and not _parent_item_id(item):
            if current is not None:
                outlines.append(current)
            turn_id = _item_turn_id(item, turn_by_id, item_id=entry["item_id"])
            turn = turn_by_id.get(turn_id) if turn_id else None
            current = {
                "message_id": entry["item_id"],
                "turn_id": turn_id,
                "seq": entry["seq"],
                "timestamp": _item_timestamp(
                    item,
                    turn,
                ),
                "prompt": _bound_text(_input_text(item), limit),
                "response_excerpt": "",
            }
            if item.get("status") == "queued":
                current["_queued"] = True
            continue

        if (
            current is None
            or item_type != "agentMessage"
            or _parent_item_id(item)
            or current.get("_queued") is True
        ):
            continue
        text = _item_text(item).strip()
        if not text or _is_protocol_envelope_text(text):
            continue
        # The frontend keeps the latest non-protocol agentMessage body as the
        # assistant segment's compatibility ``content``.  Keep the same
        # last-message semantics rather than concatenating tool/stream bodies.
        current["response_excerpt"] = _bound_text(text, limit)

    if current is not None:
        outlines.append(current)
    for item in outlines:
        item.pop("_queued", None)
    return {"thread": {"id": resolved_thread_id}, "items": outlines}


def _timeline_items(
    state: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Merge outer and core item orders on their thread-global sequence."""

    outer_items = _mapping(state.get("items"))
    core_state = _mapping(state.get("core"))
    core_items = _mapping(core_state.get("items"))
    rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for source_rank, (source, items, raw_order) in enumerate(
        (
            ("outer", outer_items, state.get("item_order")),
            ("core", core_items, core_state.get("item_order")),
        )
    ):
        order = _order_ids(raw_order, items)
        for order_rank, item_id in enumerate(order, 1):
            if item_id in seen_ids:
                # The frontend resolves duplicate ids to the canonical core
                # item; ordinary snapshots never duplicate ids, but ignoring a
                # later duplicate keeps legacy data deterministic.
                continue
            item = items.get(item_id)
            if not isinstance(item, Mapping):
                continue
            seen_ids.add(item_id)
            raw_seq = _item_seq(item)
            rows.append(
                {
                    "source": source,
                    "source_rank": source_rank,
                    "order_rank": order_rank,
                    "item_id": item_id,
                    "item": item,
                    "raw_seq": raw_seq,
                    # A missing sequence anchor is intentionally sorted after
                    # anchored items, with outer items before core items like
                    # the UI's outerSeqAnchor/coreSeqAnchor fallback.
                    "sort_key": (
                        0 if raw_seq is not None else 1,
                        raw_seq if raw_seq is not None else 0,
                        source_rank,
                        order_rank,
                        item_id,
                    ),
                }
            )

    rows.sort(key=lambda row: row["sort_key"])
    for fallback_seq, row in enumerate(rows, 1):
        row["seq"] = row["raw_seq"] if row["raw_seq"] is not None else fallback_seq
    return rows


def _turn_metadata(state: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for value in (state.get("turns"), _mapping(state.get("core")).get("turns")):
        if not isinstance(value, Mapping):
            continue
        for raw_id, turn in value.items():
            if isinstance(turn, Mapping):
                turn_id = str(turn.get("turn_id") or raw_id or "")
                if turn_id and turn_id not in result:
                    result[turn_id] = turn
    return result


def _item_turn_id(
    item: Mapping[str, Any],
    turns: Mapping[str, Mapping[str, Any]],
    *,
    item_id: str = "",
) -> str:
    direct = str(item.get("turn_id") or item.get("turnId") or "").strip()
    if direct:
        return direct
    item_id = item_id or str(item.get("item_id") or "")
    for turn_id, turn in turns.items():
        if item_id and item_id in {str(value) for value in (turn.get("items") or [])}:
            return turn_id
    return ""


def _item_timestamp(
    item: Mapping[str, Any],
    turn: Mapping[str, Any] | None,
) -> str | None:
    for value in (
        item.get("timestamp"),
        item.get("created_at"),
        _mapping(item.get("payload")).get("timestamp"),
        _mapping(item.get("payload")).get("created_at"),
        turn.get("timestamp") if turn else None,
        turn.get("created_at") if turn else None,
    ):
        normalized = _timestamp_value(value)
        if normalized:
            return normalized
    return None


def _timestamp_value(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return None


def _order_ids(raw_order: Any, items: Mapping[str, Any]) -> list[str]:
    if isinstance(raw_order, list):
        ordered = [str(value) for value in raw_order if str(value)]
        known = set(ordered)
        ordered.extend(str(value) for value in items if str(value) not in known)
        return ordered
    return [str(value) for value in items if str(value)]


def _item_seq(item: Mapping[str, Any]) -> int | None:
    for key in ("seq", "last_seq"):
        value = item.get(key)
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    return None


def _item_type(item: Mapping[str, Any]) -> str:
    direct = str(item.get("type") or "").strip()
    if direct:
        return direct
    payload = _mapping(item.get("payload"))
    return str(payload.get("type") or "").strip()


def _parent_item_id(item: Mapping[str, Any]) -> str:
    direct = str(item.get("parent_item_id") or item.get("parentItemId") or "").strip()
    if direct:
        return direct
    metadata = _mapping(item.get("metadata"))
    return str(metadata.get("parent_item_id") or metadata.get("parentItemId") or "").strip()


def _input_text(item: Mapping[str, Any]) -> str:
    value = item.get("content")
    if value is None:
        value = _mapping(item.get("payload")).get("content")
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return input_items_text([entry for entry in value if isinstance(entry, dict)])
    if isinstance(value, Mapping):
        return str(value.get("text") or "").strip()
    return ""


def _item_text(item: Mapping[str, Any]) -> str:
    for value in (
        item.get("content"),
        _mapping(item.get("payload")).get("content"),
        item.get("text"),
        _mapping(item.get("payload")).get("text"),
    ):
        if isinstance(value, str):
            return value
    deltas = item.get("deltas")
    if isinstance(deltas, list):
        return "".join(str(value) for value in deltas if isinstance(value, str))
    return ""


def _is_protocol_envelope_text(content: str) -> bool:
    text = content.strip()
    if not text.startswith("{") or not text.endswith("}"):
        return False
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return False
    if not isinstance(value, dict):
        return False
    if value.get("jsonrpc") == "2.0" and any(key in value for key in ("method", "result", "error")):
        return True
    return isinstance(value.get("event"), str) and ("payload" in value or "params" in value)


def _bound_text(value: str, limit: int) -> str:
    return str(value or "")[:limit]


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


__all__ = [
    "DEFAULT_THREAD_OUTLINE_CHAR_LIMIT",
    "MAX_THREAD_OUTLINE_CHAR_LIMIT",
    "build_thread_outline",
    "normalize_thread_outline_char_limit",
]
