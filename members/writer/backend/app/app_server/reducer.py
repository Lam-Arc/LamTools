from __future__ import annotations

from copy import deepcopy
from typing import Any

from lamtools_core.app import AppEventEnvelope as CoreAppEventEnvelope
from lamtools_core.app import CoreAppSnapshotProjector

from .protocol import CORE_RUN_ITEM_METHOD, WriterAppEventEnvelope

_CORE_PROJECTOR = CoreAppSnapshotProjector(member_defaults={"queue": []})
_GENERIC_EVENT_METHODS = {
    "thread/started",
    "turn/accepted",
    "turn/started",
    "item/started",
    "turn/interrupted",
    "turn/steered",
    "serverRequest/resolved",
    "queue/itemAccepted",
    "queue/itemUpdated",
    "queue/itemDispatched",
    "queue/itemDeleted",
    CORE_RUN_ITEM_METHOD,
}


def empty_thread_state(thread_id: str) -> dict[str, Any]:
    return _CORE_PROJECTOR.empty(thread_id)


def apply_event(state: dict[str, Any] | None, event: WriterAppEventEnvelope) -> dict[str, Any]:
    next_state = deepcopy(state) if state else empty_thread_state(event.thread_id)
    return apply_event_in_place(next_state, event)


def apply_event_in_place(state: dict[str, Any], event: WriterAppEventEnvelope) -> dict[str, Any]:
    if event.method in _GENERIC_EVENT_METHODS:
        return _CORE_PROJECTOR.apply_in_place(state, _to_core_envelope(event))

    _CORE_PROJECTOR.apply_in_place(state, _to_core_envelope(event))
    if event.method == "session/rollback_turn":
        _CORE_PROJECTOR.remove_turns(state, _rolled_back_turn_ids(event.payload))
    return state


def _rolled_back_turn_ids(payload: dict[str, Any]) -> set[str]:
    turn_ids = {
        str(turn_id)
        for turn_id in payload.get("rolled_back_turn_ids", [])
        if str(turn_id)
    }
    if not turn_ids:
        target = str(payload.get("target_turn_id") or "")
        if target:
            turn_ids.add(target)
    return turn_ids


def reduce_events(thread_id: str, events: list[WriterAppEventEnvelope]) -> dict[str, Any]:
    state = empty_thread_state(thread_id)
    for event in sorted(events, key=lambda item: item.seq):
        apply_event_in_place(state, event)
    return state


def reconcile_status(state: dict[str, Any]) -> dict[str, Any]:
    return _CORE_PROJECTOR.reconcile_status(deepcopy(state))


def _to_core_envelope(event: WriterAppEventEnvelope) -> CoreAppEventEnvelope:
    return CoreAppEventEnvelope(
        event_id=event.event_id,
        protocol_version=event.protocol_version,
        seq=event.seq,
        thread_id=event.thread_id,
        method=event.method,
        payload=dict(event.payload or {}),
        created_at=event.created_at,
        turn_id=event.turn_id,
        item_id=event.item_id,
        parent_item_id=event.parent_item_id,
        client_message_id=event.client_message_id,
    )
