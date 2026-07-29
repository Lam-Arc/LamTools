from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .turn_acceptance import CoreAppEventSpec


ACTIVE_TURN_STATUSES = {"running", "waiting", "interrupting"}
QUEUE_TERMINAL_STATUSES = {"cancelled", "deleted", "dispatched", "sent"}


@dataclass(frozen=True)
class QueueGuidancePlan:
    applied: bool
    reason: str
    input_items: list[dict[str, Any]]
    runtime_input_items: list[dict[str, Any]]
    events: tuple[CoreAppEventSpec, ...]


@dataclass(frozen=True)
class QueueUpdatePlan:
    applied: bool
    reason: str
    payload: dict[str, Any] | None = None


def build_queue_guidance_plan(
    snapshot: dict[str, Any],
    *,
    thread_id: str,
    turn_id: str,
    queue_item_id: str,
    client_message_id: str,
    replacement_text: str | None = None,
) -> QueueGuidancePlan:
    queue = snapshot.get("queue")
    item = next(
        (
            value
            for value in queue if isinstance(value, dict) and str(value.get("queue_item_id") or "") == queue_item_id
        ),
        None,
    ) if isinstance(queue, list) else None
    if item is None or str(item.get("status") or "") != "queued":
        return QueueGuidancePlan(False, "queue_item_unavailable", [], [], ())
    if latest_active_turn_id(snapshot) != turn_id:
        return QueueGuidancePlan(False, "active_turn_mismatch", [], [], ())

    raw_input = item.get("input")
    input_items = [dict(value) for value in raw_input if isinstance(value, dict)] if isinstance(raw_input, list) else []
    raw_runtime_input = item.get("runtime_input")
    runtime_input_items = (
        [dict(value) for value in raw_runtime_input if isinstance(value, dict)]
        if isinstance(raw_runtime_input, list)
        else input_items
    )
    if replacement_text is not None and replacement_text.strip():
        input_items = [{"type": "text", "text": replacement_text.strip()}]
        runtime_input_items = input_items
    if not input_items:
        return QueueGuidancePlan(False, "queue_input_unavailable", [], [], ())

    user_item_id = f"{turn_id}:user:guide:{queue_item_id}"
    events = (
        CoreAppEventSpec(
            event_id=f"{client_message_id}:steer",
            thread_id=thread_id,
            method="turn/steered",
            turn_id=turn_id,
            client_message_id=client_message_id,
            payload={"type": "turn", "input": input_items},
        ),
        CoreAppEventSpec(
            event_id=f"{client_message_id}:usermsg",
            thread_id=thread_id,
            method="item/started",
            turn_id=turn_id,
            item_id=user_item_id,
            client_message_id=client_message_id,
            payload={"type": "userMessage", "status": "completed", "content": input_items},
        ),
        CoreAppEventSpec(
            event_id=f"{client_message_id}:consume",
            thread_id=thread_id,
            method="queue/itemDeleted",
            turn_id=turn_id,
            item_id=queue_item_id,
            client_message_id=client_message_id,
            payload=queue_delete_payload(queue_item_id=queue_item_id, status="sent"),
        ),
    )
    return QueueGuidancePlan(True, "", input_items, runtime_input_items, events)


def build_queue_update_plan(
    snapshot: dict[str, Any],
    *,
    queue_item_id: str,
    input_items: list[dict[str, Any]],
    runtime_input_items: list[dict[str, Any]] | None = None,
    mode: str | None = None,
) -> QueueUpdatePlan:
    queue = snapshot.get("queue")
    item = next(
        (
            value
            for value in queue
            if isinstance(value, dict) and str(value.get("queue_item_id") or "") == queue_item_id
        ),
        None,
    ) if isinstance(queue, list) else None
    if item is None or str(item.get("status") or "") != "queued":
        return QueueUpdatePlan(False, "queue_item_unavailable")
    return QueueUpdatePlan(
        True,
        "",
        queue_item_payload(
            queue_item_id=queue_item_id,
            input_items=input_items,
            runtime_input_items=runtime_input_items,
            mode=mode or str(item.get("mode") or "next_turn"),
        ),
    )


def input_items_text(input_items: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for item in input_items:
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(str(item.get("text") or ""))
    return "".join(parts).strip()


def input_item_attachment_ids(input_items: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for item in input_items:
        if not isinstance(item, dict) or item.get("type") != "attachment":
            continue
        raw_id = item.get("attachment_id") or item.get("attachmentId") or item.get("id")
        attachment_id = str(raw_id or "").strip()
        if not attachment_id:
            raise ValueError("attachment_id is required")
        if attachment_id in seen:
            continue
        seen.add(attachment_id)
        ids.append(attachment_id)
    return ids


def queue_item_payload(
    *,
    queue_item_id: str,
    input_items: list[dict[str, Any]],
    runtime_input_items: list[dict[str, Any]] | None = None,
    mode: str = "next_turn",
    status: str = "queued",
) -> dict[str, Any]:
    runtime_items = runtime_input_items if runtime_input_items is not None else input_items
    return {
        "type": "queue",
        "queue_item_id": queue_item_id,
        "status": status,
        "mode": mode,
        "input": input_items,
        "runtime_input": runtime_items,
    }


def queue_delete_payload(*, queue_item_id: str, status: str = "cancelled") -> dict[str, Any]:
    return {
        "type": "queue",
        "queue_item_id": queue_item_id,
        "status": status,
    }


def queue_dispatch_payload(
    item: dict[str, Any],
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]] | None:
    queue_item_id = str(item.get("queue_item_id") or "")
    input_items = item.get("input")
    runtime_input_items = item.get("runtime_input")
    if not queue_item_id or not isinstance(input_items, list):
        return None
    if not isinstance(runtime_input_items, list):
        runtime_input_items = input_items
    payload = queue_item_payload(
        queue_item_id=queue_item_id,
        input_items=input_items,
        runtime_input_items=runtime_input_items,
        mode=str(item.get("mode") or "next_turn"),
        status="dispatched",
    )
    return queue_item_id, input_items, runtime_input_items, payload


def effective_thread_status(snapshot: dict[str, Any]) -> str:
    core = snapshot.get("core")
    core_status = core.get("status") if isinstance(core, dict) else None
    if core_status and core_status != "idle":
        return str(core_status)
    return str(snapshot.get("status") or "idle")


def effective_turn_status(snapshot: dict[str, Any], turn_id: str) -> str:
    core = snapshot.get("core")
    core_turns = core.get("turns") if isinstance(core, dict) else None
    core_turn = core_turns.get(turn_id) if isinstance(core_turns, dict) else None
    core_status = core_turn.get("status") if isinstance(core_turn, dict) else None
    if core_status:
        return str(core_status)

    turns = snapshot.get("turns")
    turn = turns.get(turn_id) if isinstance(turns, dict) else None
    if isinstance(turn, dict):
        return str(turn.get("status") or "")
    return ""


def latest_active_turn_id(snapshot: dict[str, Any]) -> str | None:
    core = snapshot.get("core")
    has_thread_status = bool(snapshot.get("status")) or (
        isinstance(core, dict) and bool(core.get("status"))
    )
    if has_thread_status and effective_thread_status(snapshot) not in ACTIVE_TURN_STATUSES:
        return None
    turns = _merged_turns(snapshot)
    active: list[dict[str, Any]] = []
    for turn_id, turn in turns.items():
        if not isinstance(turn, dict):
            continue
        turn_status = effective_turn_status(snapshot, str(turn.get("turn_id") or turn_id))
        if turn_status in ACTIVE_TURN_STATUSES:
            active.append({**turn, "turn_id": turn.get("turn_id") or turn_id})
    if not active:
        return None
    active.sort(key=lambda item: int(item.get("last_seq") or item.get("seq") or 0), reverse=True)
    return str(active[0].get("turn_id") or "") or None


def next_dispatchable_queue_item(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    status = effective_thread_status(snapshot)
    if status not in {"completed", "idle"}:
        return None
    if status == "idle" and snapshot.get("turns"):
        return None

    queue = snapshot.get("queue")
    if not isinstance(queue, list):
        return None
    queued = [
        item
        for item in queue
        if isinstance(item, dict)
        and item.get("status") == "queued"
        and str(item.get("mode") or "next_turn") == "next_turn"
    ]
    if not queued:
        return None
    queued.sort(key=lambda item: (int(item.get("seq") or 0), str(item.get("queue_item_id") or "")))
    return queued[0]


def _merged_turns(snapshot: dict[str, Any]) -> dict[str, Any]:
    turns: dict[str, Any] = {}
    outer = snapshot.get("turns")
    if isinstance(outer, dict):
        turns.update(outer)
    core = snapshot.get("core")
    core_turns = core.get("turns") if isinstance(core, dict) else None
    if isinstance(core_turns, dict):
        turns.update(core_turns)
    return turns


__all__ = [
    "ACTIVE_TURN_STATUSES",
    "QUEUE_TERMINAL_STATUSES",
    "QueueGuidancePlan",
    "QueueUpdatePlan",
    "build_queue_guidance_plan",
    "build_queue_update_plan",
    "effective_thread_status",
    "effective_turn_status",
    "input_item_attachment_ids",
    "input_items_text",
    "latest_active_turn_id",
    "next_dispatchable_queue_item",
    "queue_delete_payload",
    "queue_dispatch_payload",
    "queue_item_payload",
]
