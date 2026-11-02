"""Global session-list notifications for turns that settle in the background.

The desktop sidebar renders each session's status from ``/sessions`` and only
refreshes that list when the server says something changed. A turn's terminal
run item is delivered to connections subscribed to that thread only, so a
session finishing in the background never reached a client watching another
session: its row kept spinning until the user opened it (reported 2026-10-31).

``settled_session_notice`` turns such a terminal turn status into the same
``session/updated`` notification every client already understands, and the hub
broadcasts it to all connections.
"""
from __future__ import annotations

from typing import Any

from .event_store import CORE_RUN_ITEM_METHOD

#: Turn statuses that settle a session row: the sidebar's busy ring must stop.
#: `paused` is included because a paused background session renders its own
#: pause icon instead of the running spinner.
SETTLED_TURN_STATUSES = frozenset({"completed", "failed", "cancelled", "paused"})

RUN_ITEM_METHOD = CORE_RUN_ITEM_METHOD


def settled_session_notice(event: Any) -> dict[str, Any] | None:
    """Return a global ``session/updated`` notice for a settled turn, else None.

    Only a turn-level ``status`` run item qualifies. Member lifecycle rows ride
    as ``kind="message"`` (or a non-turn payload type), and the member-wait row
    is non-terminal, so neither can settle the session row.
    """
    method = getattr(event, "method", "") or (event.get("method") if isinstance(event, dict) else "")
    if method != RUN_ITEM_METHOD:
        return None
    payload = getattr(event, "payload", None)
    if not isinstance(payload, dict) and isinstance(event, dict):
        payload = event.get("payload")
    if not isinstance(payload, dict):
        return None
    if payload.get("kind") != "status" or payload.get("parent_item_id"):
        return None
    inner = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
    if inner.get("type") not in (None, "", "turn"):
        return None
    status = str(inner.get("status") or payload.get("status") or "").strip().lower()
    if status not in SETTLED_TURN_STATUSES:
        return None
    turn_id = str(
        getattr(event, "turn_id", "")
        or (event.get("turn_id") if isinstance(event, dict) else "")
        or ""
    ).strip()
    # Slash commands (notably /compact) write a turn-shaped terminal status for a
    # synthetic turn while the real turn keeps running. Those must not settle the
    # session row: the sidebar would report "completed" mid-turn.
    if ":command:" in turn_id:
        return None
    thread_id = str(
        getattr(event, "thread_id", "")
        or (event.get("thread_id") if isinstance(event, dict) else "")
        or payload.get("thread_id")
        or ""
    ).strip()
    if not thread_id:
        return None
    return {
        "method": "session/updated",
        "thread_id": thread_id,
        # 只用于宿主侧去重（同一终态可能被投影与 pause/cancel 路径重复写入）；
        # 客户端只读 payload.session。
        "turn_id": turn_id,
        "payload": {"session": {"id": thread_id, "status": status}},
    }


__all__ = ["SETTLED_TURN_STATUSES", "settled_session_notice"]
