"""Canonical thread snapshot reducer.

The snapshot is the recoverable display state derived from Core ``RunItemEvent``
facts. Product members can project domain labels around it, but the reducer is
member-neutral and idempotent.
"""

from __future__ import annotations

import bisect
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from lamtools_core.event import RunItemEvent

TERMINAL_STATUSES = {"completed", "failed", "cancelled", "skipped"}


def empty_thread_snapshot(thread_id: str) -> dict[str, Any]:
    return {
        "thread_id": thread_id,
        "snapshot_seq": 0,
        "seen_event_ids": [],
        "turns": {},
        "items": {},
        "item_order": [],
        "requests": {},
        "artifacts": {},
        "status": "idle",
    }


def apply_run_item_event(state: dict[str, Any] | None, event: RunItemEvent) -> dict[str, Any]:
    next_state = deepcopy(state) if state else empty_thread_snapshot(event.thread_id)
    return apply_run_item_event_in_place(next_state, event)


def apply_run_item_event_in_place(state: dict[str, Any], event: RunItemEvent) -> dict[str, Any]:
    seen = set(state.get("seen_event_ids") or [])
    if event.event_id in seen:
        return state

    state["thread_id"] = event.thread_id
    state["snapshot_seq"] = max(
        int(state.get("snapshot_seq") or 0),
        int(event.seq or 0),
    )
    if event.seq == 0:
        state["snapshot_seq"] = int(state.get("snapshot_seq") or 0) + 1

    state.setdefault("seen_event_ids", []).append(event.event_id)
    if len(state["seen_event_ids"]) > 2000:
        state["seen_event_ids"] = state["seen_event_ids"][-2000:]

    if event.kind == "status":
        status = event.payload.get("status") or event.status
        existing_turn = (state.get("turns") or {}).get(event.turn_id) if event.turn_id else None
        existing_status = str(existing_turn.get("status") or "") if isinstance(existing_turn, dict) else ""
        turn = _upsert_turn(state, event)
        if existing_status in TERMINAL_STATUSES and status != existing_status:
            if turn is not None and event.usage:
                turn["usage"] = {**dict(turn.get("usage") or {}), **event.usage}
            _recompute_thread_status(state)
            return state
        if status:
            state["status"] = status
        if turn is not None and status:
            turn["status"] = status
        if turn is not None and event.usage:
            turn["usage"] = {**dict(turn.get("usage") or {}), **event.usage}
        if status in {"failed", "cancelled", "error"} and (
            event.payload.get("message") or event.payload.get("raw_end_reason")
        ):
            item = _upsert_item(state, event)
            if turn is not None and item["item_id"] not in turn.setdefault("items", []):
                turn["items"].append(item["item_id"])
            state["last_error"] = dict(event.payload)
        if turn is not None and status in TERMINAL_STATUSES:
            _close_turn_items(state, turn, status)
            reconcile_terminal_requests(state)
        return state

    if event.kind == "approval_response":
        _apply_approval_response(state, event)
        turn = _upsert_turn(state, event)
        if turn is not None and str(turn.get("status") or "") not in {"failed", "cancelled", "skipped"}:
            # Resolving a server request resumes the existing turn; it does not
            # complete that turn.  A later lifecycle/status item owns terminality.
            turn["status"] = "running"
        _recompute_thread_status(state)
        return state

    if event.kind == "usage":
        turn = _upsert_turn(state, event)
        if event.usage:
            if event.payload.get("replace") is True:
                turn["usage"] = dict(event.usage)
            else:
                turn["usage"] = _merge_dict_values(turn.get("usage"), event.usage)
        return state

    if event.kind == "artifact" or event.artifacts:
        _apply_artifact(state, event)

    existing_turn = (state.get("turns") or {}).get(event.turn_id) if event.turn_id else None
    terminal_turn_status = (
        str(existing_turn.get("status") or "")
        if isinstance(existing_turn, dict)
        and str(existing_turn.get("status") or "") in TERMINAL_STATUSES
        else ""
    )
    item = _upsert_item(state, event)
    if terminal_turn_status:
        item["status"] = terminal_turn_status
        turn = _upsert_turn(state, event)
        if event.item_id and turn is not None and event.item_id not in turn.setdefault("items", []):
            turn["items"].append(event.item_id)
        _recompute_thread_status(state)
        return state
    if event.kind == "approval_request":
        item["status"] = "waiting"
        state["status"] = "waiting"
        request_id = str(event.payload.get("request_id") or event.item_id or event.event_id)
        state.setdefault("requests", {})[request_id] = {
            "request_id": request_id,
            "status": "open",
            "item_id": item["item_id"],
            "turn_id": event.turn_id,
            **event.payload,
        }
    elif event.kind == "error":
        item["status"] = "failed"
        state["last_error"] = event.payload or {"message": item.get("content", "")}
        if _is_terminal_error_event(event):
            state["status"] = "failed"
    elif event.status == "waiting":
        item["status"] = "waiting"
        state["status"] = "waiting"
    elif event.status in TERMINAL_STATUSES:
        item["status"] = event.status
    else:
        item["status"] = event.status
        if event.turn_id:
            state["status"] = "running"

    turn = _upsert_turn(state, event)
    if event.item_id and turn is not None and event.item_id not in turn.setdefault("items", []):
        turn["items"].append(event.item_id)
    if turn is None:
        _recompute_thread_status(state)
        return state
    if event.kind == "approval_request":
        turn["status"] = "waiting"
        state["status"] = "waiting"
    elif _is_turn_terminal_event(event):
        turn["status"] = event.status
        reconcile_terminal_requests(state)
        _recompute_thread_status(state)
    elif event.status == "waiting":
        turn["status"] = "waiting"
        state["status"] = "waiting"
    elif event.turn_id and str(turn.get("status") or "") not in TERMINAL_STATUSES:
        turn["status"] = "running"
        _recompute_thread_status(state)
    return state


def reduce_run_item_events(thread_id: str, events: list[RunItemEvent]) -> dict[str, Any]:
    state = empty_thread_snapshot(thread_id)
    for event in sorted(events, key=lambda item: (item.seq or 0, item.created_at_ms, item.event_id)):
        apply_run_item_event_in_place(state, event)
    return state


@runtime_checkable
class SnapshotStore(Protocol):
    def get(self, thread_id: str) -> dict[str, Any] | None: ...
    def save(self, snapshot: dict[str, Any]) -> None: ...


@dataclass
class InMemorySnapshotStore:
    _snapshots: dict[str, dict[str, Any]] = field(default_factory=dict)

    def get(self, thread_id: str) -> dict[str, Any] | None:
        snapshot = self._snapshots.get(thread_id)
        return deepcopy(snapshot) if snapshot is not None else None

    def save(self, snapshot: dict[str, Any]) -> None:
        thread_id = str(snapshot.get("thread_id") or "")
        if not thread_id:
            raise ValueError("snapshot.thread_id is required")
        self._snapshots[thread_id] = deepcopy(snapshot)

    def apply(self, event: RunItemEvent) -> dict[str, Any]:
        snapshot = apply_run_item_event(self.get(event.thread_id), event)
        self.save(snapshot)
        return snapshot

    def clear(self) -> None:
        self._snapshots.clear()


def _upsert_turn(state: dict[str, Any], event: RunItemEvent) -> dict[str, Any] | None:
    if not event.turn_id:
        return None
    turn = state.setdefault("turns", {}).setdefault(
        event.turn_id,
        {"turn_id": event.turn_id, "status": "running", "items": []},
    )
    turn["last_kind"] = event.kind
    turn["last_seq"] = event.seq or state.get("snapshot_seq", 0)
    if event.run_id:
        turn["run_id"] = event.run_id
    return turn


def _close_turn_items(state: dict[str, Any], turn: dict[str, Any], status: str) -> None:
    items = state.get("items") or {}
    for item_id in turn.get("items") or []:
        item = items.get(item_id)
        if not isinstance(item, dict):
            continue
        if str(item.get("status") or "") not in TERMINAL_STATUSES:
            item["status"] = status


def _is_turn_terminal_event(event: RunItemEvent) -> bool:
    if event.status not in TERMINAL_STATUSES:
        return False
    if event.kind == "error":
        return _is_terminal_error_event(event)
    # Item completion is not turn completion. Intermediate assistant text,
    # verification, and tool items may all complete before more work begins.
    # The dedicated turn status event owns successful terminality.
    return False


def _is_terminal_error_event(event: RunItemEvent) -> bool:
    payload_type = str(event.payload.get("type") or "").lower()
    if payload_type in {"runtime", "turn"}:
        return True
    runtime_phase = str((event.metadata or {}).get("runtime_phase") or "")
    if runtime_phase == "runtime.failed":
        return True
    return not event.item_id


def _upsert_item(state: dict[str, Any], event: RunItemEvent) -> dict[str, Any]:
    item_id = event.item_id or f"{event.turn_id or event.thread_id}:{event.kind}:{event.event_id}"
    item = state.setdefault("items", {}).setdefault(
        item_id,
        {
            "item_id": item_id,
            "turn_id": event.turn_id,
            "parent_item_id": event.parent_item_id,
            "kind": event.kind,
            "content": "",
            "deltas": [],
            "status": event.status,
        },
    )
    if event.kind == "tool_result":
        item["kind"] = "tool_result"
    else:
        item["kind"] = item.get("kind") or event.kind
    item["last_kind"] = event.kind
    item["last_seq"] = event.seq or state.get("snapshot_seq", 0)
    item["status"] = event.status
    if event.payload:
        item.setdefault("payload", {}).update(event.payload)
    if event.artifacts:
        item["artifacts"] = event.artifacts
    if event.usage:
        item["usage"] = _merge_dict_values(item.get("usage"), event.usage)

    delta = event.payload.get("delta")
    content = event.payload.get("content", event.payload.get("text"))
    if isinstance(delta, str):
        if event.payload.get("replace") is True:
            item["deltas"] = [delta]
            item["content"] = delta
        else:
            item.setdefault("deltas", []).append(delta)
            item["content"] = f"{item.get('content', '')}{delta}"
    elif isinstance(content, str):
        item["content"] = content

    item_seq = int(event.seq or 0)
    if item_id not in state.setdefault("item_order", []):
        # Record the first event's seq as the ordering anchor and insert the
        # item at the correct position right away. Deferred part events are
        # projected at the turn boundary (after runtime-projected tool
        # results), so appending would leave the turn's items out of order;
        # inserting by seq keeps item_order equal to production order without
        # any post-hoc reordering.
        item["seq"] = item_seq
        order = state["item_order"]
        items = state.get("items") or {}
        index = bisect.bisect_right(
            [int((items.get(iid) or {}).get("seq") or 0) for iid in order],
            item_seq,
        )
        order.insert(index, item_id)
    elif "seq" not in item:
        item["seq"] = item_seq
    return item


def _apply_approval_response(state: dict[str, Any], event: RunItemEvent) -> None:
    request_id = str(event.payload.get("request_id") or event.item_id or "")
    if not request_id:
        return
    request = state.setdefault("requests", {}).setdefault(request_id, {"request_id": request_id})
    request.update(event.payload)
    request["status"] = event.payload.get("status") or "resolved"


def _apply_artifact(state: dict[str, Any], event: RunItemEvent) -> None:
    artifacts = event.artifacts or ([event.payload] if event.payload else [])
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        artifact_id = str(artifact.get("artifact_id") or artifact.get("id") or event.item_id or event.event_id)
        state.setdefault("artifacts", {})[artifact_id] = artifact


def _has_open_request(state: dict[str, Any]) -> bool:
    return any(
        isinstance(request, dict) and request.get("status") == "open"
        for request in (state.get("requests") or {}).values()
    )


def reconcile_terminal_requests(state: dict[str, Any]) -> dict[str, Any]:
    """Close stale server requests whose owning turn can no longer answer them."""
    turns = state.get("turns")
    requests = state.get("requests")
    if not isinstance(turns, dict) or not isinstance(requests, dict):
        return state
    terminal_statuses = {
        str(turn_id): str(turn.get("status") or "")
        for turn_id, turn in turns.items()
        if isinstance(turn, dict) and str(turn.get("status") or "") in TERMINAL_STATUSES
    }
    for request_id, request in list(requests.items()):
        if not isinstance(request, dict) or request.get("status") != "open":
            continue
        terminal_status = terminal_statuses.get(str(request.get("turn_id") or ""))
        if not terminal_status:
            continue
        requests[request_id] = {
            **request,
            "status": "cancelled" if terminal_status == "cancelled" else "resolved",
            "terminal_turn_status": terminal_status,
        }
    return state


def _latest_active_turn(state: dict[str, Any]) -> dict[str, Any] | None:
    turns = [
        turn for turn in (state.get("turns") or {}).values()
        if isinstance(turn, dict) and turn.get("status") in {"queued", "running", "waiting"}
    ]
    turns.sort(key=lambda item: int(item.get("last_seq") or 0), reverse=True)
    return turns[0] if turns else None


def _recompute_thread_status(state: dict[str, Any]) -> None:
    if _has_open_request(state):
        state["status"] = "waiting"
        return
    if _latest_active_turn(state) is not None:
        state["status"] = "running"
        return
    turns = [
        turn for turn in (state.get("turns") or {}).values()
        if isinstance(turn, dict)
    ]
    turns.sort(key=lambda item: int(item.get("last_seq") or 0), reverse=True)
    latest_status = str((turns[0] if turns else {}).get("status") or "")
    if latest_status == "completed":
        state["status"] = "completed"
    elif latest_status == "cancelled":
        state["status"] = "cancelled"
    elif latest_status == "failed":
        state["status"] = "failed"
    else:
        state["status"] = "idle"


def _merge_dict_values(current: Any, incoming: dict[str, Any]) -> dict[str, Any]:
    result = dict(current or {})
    for key, value in incoming.items():
        if isinstance(value, (int, float)) and isinstance(result.get(key), (int, float)):
            result[key] += value
        else:
            result[key] = value
    return result


__all__ = [
    "SnapshotStore",
    "InMemorySnapshotStore",
    "apply_run_item_event",
    "empty_thread_snapshot",
    "reconcile_terminal_requests",
    "reduce_run_item_events",
]
