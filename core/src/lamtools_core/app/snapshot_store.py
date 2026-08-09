"""Generic thread snapshot storage for Core Agent hosts."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from lamtools_core.event import RunItemEvent
from lamtools_core.snapshot import (
    TERMINAL_STATUSES,
    apply_run_item_event_in_place,
    empty_thread_snapshot,
    reconcile_terminal_requests,
)

from .event_store import CORE_RUN_ITEM_METHOD, AppEventEnvelope

TERMINAL_ERROR_STATUSES = {"failed", "cancelled", "error"}
TERMINAL_TURN_STATUSES = {"completed", *TERMINAL_ERROR_STATUSES}


@dataclass
class CoreAppSnapshotProjector:
    member_defaults: dict[str, Any] = field(default_factory=dict)

    def empty(self, thread_id: str) -> dict[str, Any]:
        state = {
            "thread_id": thread_id,
            "snapshot_seq": 0,
            "seen_event_ids": [],
            "turns": {},
            "items": {},
            "item_order": [],
            "requests": {},
            "artifacts": {},
            "core": empty_thread_snapshot(thread_id),
            "status": "idle",
        }
        state.update(deepcopy(self.member_defaults))
        return state

    def apply(self, state: dict[str, Any] | None, event: AppEventEnvelope) -> dict[str, Any]:
        next_state = deepcopy(state) if state else self.empty(event.thread_id)
        return self.apply_in_place(next_state, event)

    def apply_in_place(self, state: dict[str, Any], event: AppEventEnvelope) -> dict[str, Any]:
        seen = set(state.get("seen_event_ids") or [])
        if event.event_id in seen:
            return state

        state["thread_id"] = event.thread_id
        state["snapshot_seq"] = max(int(state.get("snapshot_seq") or 0), int(event.seq or 0))
        state.setdefault("seen_event_ids", []).append(event.event_id)
        if len(state["seen_event_ids"]) > 2000:
            state["seen_event_ids"] = state["seen_event_ids"][-2000:]

        if event.method == "thread/started":
            self._apply_thread_started(state, event)
        elif event.method == "turn/accepted":
            self._apply_turn_accepted(state, event)
        elif event.method == "turn/started":
            self._apply_turn_started(state, event)
        elif event.method == "item/started":
            self._apply_item_started(state, event)
        elif event.method == "turn/interrupted":
            self._apply_turn_interrupted(state, event)
        elif event.method == "turn/steered":
            self._apply_turn_steered(state, event)
        elif event.method == "serverRequest/resolved":
            self._apply_server_request_resolved(state, event)
        elif event.method == "queue/itemAccepted":
            self._apply_queue_item(state, event, status="queued")
        elif event.method == "queue/itemUpdated":
            self._apply_queue_item(state, event)
        elif event.method == "queue/itemDispatched":
            self._apply_queue_item(state, event, status="dispatched")
        elif event.method == "queue/itemDeleted":
            self._delete_queue_item(state, event)
        elif event.method == CORE_RUN_ITEM_METHOD:
            self._apply_core_run_item(state, event)
            self._sync_status_from_core(state)
        return state

    def reduce(self, thread_id: str, events: list[AppEventEnvelope]) -> dict[str, Any]:
        state = self.empty(thread_id)
        for event in sorted(events, key=lambda item: item.seq):
            self.apply_in_place(state, event)
        return state

    def _apply_core_run_item(self, state: dict[str, Any], event: AppEventEnvelope) -> None:
        payload = dict(event.payload or {})
        if not payload.get("kind") or not payload.get("thread_id"):
            return
        # The payload seq is batch-relative (always 0/1); the envelope seq is
        # the thread's global ordering anchor. Override unconditionally so
        # item_order bisect insertion matches production order.
        payload["seq"] = event.seq
        core = state.get("core") if isinstance(state.get("core"), dict) else empty_thread_snapshot(event.thread_id)
        apply_run_item_event_in_place(core, RunItemEvent.from_dict(payload))
        state["core"] = core
        self._sync_turns_from_core(state)

    def _apply_thread_started(self, state: dict[str, Any], event: AppEventEnvelope) -> None:
        payload = dict(event.payload or {})
        state["status"] = str(payload.get("status") or state.get("status") or "idle")
        session = state.setdefault("session", {})
        if not isinstance(session, dict):
            session = {}
            state["session"] = session
        for key in ("member_id", "title"):
            if key in payload:
                session[key] = payload[key]

    def _apply_turn_accepted(self, state: dict[str, Any], event: AppEventEnvelope) -> None:
        payload = dict(event.payload or {})
        turn_id = str(event.turn_id or payload.get("turn_id") or payload.get("turnId") or "").strip()
        if not turn_id:
            return
        turns = state.setdefault("turns", {})
        turn = dict(turns.get(turn_id) or {})
        turn.update(
            {
                "turn_id": turn_id,
                "status": str(payload.get("status") or "running"),
                "seq": event.seq,
                "last_seq": event.seq,
                "last_method": event.method,
                "input": payload.get("input"),
                "work_root": payload.get("work_root") or payload.get("workRoot") or "",
            }
        )
        turn.setdefault("items", [])
        turns[turn_id] = turn
        state["status"] = "running"
        session = state.setdefault("session", {})
        if not isinstance(session, dict):
            session = {}
            state["session"] = session
        for key in ("member_id", "title"):
            if key in payload and key not in session:
                session[key] = payload[key]

    def _apply_turn_started(self, state: dict[str, Any], event: AppEventEnvelope) -> None:
        payload = dict(event.payload or {})
        turn_id = str(event.turn_id or payload.get("turn_id") or payload.get("turnId") or "").strip()
        if not turn_id:
            return
        turn = self._turn(state, turn_id)
        turn.update(payload)
        turn["status"] = str(payload.get("status") or "running")
        turn["seq"] = event.seq
        turn["last_seq"] = event.seq
        turn["last_method"] = event.method
        state["status"] = "running"

    def _apply_item_started(self, state: dict[str, Any], event: AppEventEnvelope) -> None:
        payload = dict(event.payload or {})
        item_id = str(event.item_id or payload.get("item_id") or payload.get("itemId") or "").strip()
        if not item_id:
            return
        turn_id = str(event.turn_id or payload.get("turn_id") or payload.get("turnId") or "").strip()
        items = state.setdefault("items", {})
        item = dict(items.get(item_id) or {})
        item.update(
            {
                "item_id": item_id,
                "turn_id": turn_id or None,
                "parent_item_id": event.parent_item_id,
                "type": str(payload.get("type") or "item"),
                "status": str(payload.get("status") or "running"),
                "content": payload.get("content", item.get("content", "")),
                "seq": min(int(item.get("seq") or event.seq), event.seq),
                "last_seq": event.seq,
                "last_method": event.method,
            }
        )
        item.setdefault("deltas", [])
        items[item_id] = item
        self._append_item_order(state, item_id)
        if turn_id:
            turn = self._turn(state, turn_id)
            if item_id not in turn["items"]:
                turn["items"].append(item_id)
            turn["last_seq"] = event.seq

    def _apply_turn_interrupted(self, state: dict[str, Any], event: AppEventEnvelope) -> None:
        payload = dict(event.payload or {})
        turn_id = str(event.turn_id or payload.get("turn_id") or payload.get("turnId") or "").strip()
        if turn_id:
            turn = self._turn(state, turn_id)
            if self._turn_is_terminal(state, turn_id):
                self._recompute_thread_status(state)
                return
            turn.update(payload)
            turn["status"] = "interrupting"
            turn["last_seq"] = event.seq
            turn["last_method"] = event.method
        state["status"] = "running"

    def _apply_turn_steered(self, state: dict[str, Any], event: AppEventEnvelope) -> None:
        payload = dict(event.payload or {})
        turn_id = str(event.turn_id or payload.get("turn_id") or payload.get("turnId") or "").strip()
        if not turn_id:
            return
        turn = self._turn(state, turn_id)
        turn.update({key: value for key, value in payload.items() if key != "status"})
        turn["seq"] = event.seq
        turn["last_seq"] = event.seq
        turn["last_method"] = event.method

    def _apply_server_request_resolved(self, state: dict[str, Any], event: AppEventEnvelope) -> None:
        payload = dict(event.payload or {})
        request_id = str(payload.get("request_id") or payload.get("requestId") or "").strip()
        if not request_id:
            return
        request = state.setdefault("requests", {}).setdefault(request_id, {"request_id": request_id})
        request.update(payload)
        request["status"] = "resolved"
        request.setdefault("turn_id", event.turn_id)
        request.setdefault("item_id", event.item_id)
        self._recompute_thread_status(state)

    def remove_turns(self, state: dict[str, Any], turn_ids: set[str]) -> dict[str, Any]:
        normalized = {str(turn_id) for turn_id in turn_ids if str(turn_id)}
        if not normalized:
            return state

        removed_item_ids = self._remove_turns_from_projection(state, normalized)
        core = state.get("core")
        if isinstance(core, dict):
            removed_item_ids.update(self._remove_turns_from_projection(core, normalized))
            self._remove_related_records(core, normalized, removed_item_ids)
            self._remove_queue_items(core, normalized)
            self._recompute_thread_status(core)

        self._remove_related_records(state, normalized, removed_item_ids)
        self._remove_queue_items(state, normalized)
        self._recompute_thread_status(state)
        return state

    def reconcile_status(self, state: dict[str, Any]) -> dict[str, Any]:
        """Rebuild derived status fields after loading an older persisted projection."""
        core = state.get("core")
        if isinstance(core, dict):
            reconcile_terminal_requests(core)
            self._recompute_thread_status(core)
            self._sync_turns_from_core(state)
        reconcile_terminal_requests(state)
        self._recompute_thread_status(state)
        return state

    def _append_item_order(self, state: dict[str, Any], item_id: str) -> None:
        order = state.setdefault("item_order", [])
        if item_id not in order:
            order.append(item_id)

    def _apply_queue_item(self, state: dict[str, Any], event: AppEventEnvelope, *, status: str | None = None) -> None:
        payload = dict(event.payload or {})
        queue_item_id = str(event.item_id or payload.get("queue_item_id") or payload.get("queueItemId") or "").strip()
        if not queue_item_id:
            return
        queue = list(state.get("queue") or [])
        existing_index = next(
            (index for index, item in enumerate(queue) if isinstance(item, dict) and item.get("queue_item_id") == queue_item_id),
            None,
        )
        current = dict(queue[existing_index]) if existing_index is not None else {"queue_item_id": queue_item_id}
        current.update(payload)
        current.update(
            {
                "queue_item_id": queue_item_id,
                "status": status or str(payload.get("status") or current.get("status") or "queued"),
                "mode": str(payload.get("mode") or current.get("mode") or "next_turn"),
                "input": payload.get("input", current.get("input")),
                "seq": event.seq,
                "last_method": event.method,
            }
        )
        if current.get("status") in {"cancelled", "deleted", "dispatched", "sent"}:
            state["queue"] = [
                item for item in queue
                if not isinstance(item, dict) or item.get("queue_item_id") != queue_item_id
            ]
            return
        if existing_index is None:
            queue.append(current)
        else:
            queue[existing_index] = current
        state["queue"] = queue

    def _delete_queue_item(self, state: dict[str, Any], event: AppEventEnvelope) -> None:
        payload = dict(event.payload or {})
        queue_item_id = str(event.item_id or payload.get("queue_item_id") or payload.get("queueItemId") or "").strip()
        if not queue_item_id:
            return
        state["queue"] = [
            item for item in list(state.get("queue") or [])
            if not isinstance(item, dict) or item.get("queue_item_id") != queue_item_id
        ]

    def _turn(self, state: dict[str, Any], turn_id: str) -> dict[str, Any]:
        turns = state.setdefault("turns", {})
        turn = dict(turns.get(turn_id) or {"turn_id": turn_id, "status": "running", "items": []})
        turn.setdefault("items", [])
        turns[turn_id] = turn
        return turn

    def _turn_is_terminal(self, state: dict[str, Any], turn_id: str) -> bool:
        turn = (state.get("turns") or {}).get(turn_id)
        if isinstance(turn, dict) and str(turn.get("status") or "") in TERMINAL_TURN_STATUSES:
            return True
        core_turn = ((state.get("core") or {}).get("turns") or {}).get(turn_id)
        return isinstance(core_turn, dict) and str(core_turn.get("status") or "") in TERMINAL_TURN_STATUSES

    def _remove_turns_from_projection(self, state: dict[str, Any], turn_ids: set[str]) -> set[str]:
        removed_item_ids: set[str] = set()
        turns = state.get("turns")
        if isinstance(turns, dict):
            for turn_id in turn_ids:
                turn = turns.pop(turn_id, None)
                if isinstance(turn, dict):
                    removed_item_ids.update(str(item_id) for item_id in turn.get("items", []) if str(item_id))

        items = state.get("items")
        if isinstance(items, dict):
            for item_id, item in list(items.items()):
                if str(item_id) in removed_item_ids or (isinstance(item, dict) and str(item.get("turn_id") or "") in turn_ids):
                    removed_item_ids.add(str(item_id))
                    items.pop(item_id, None)
        if isinstance(state.get("item_order"), list):
            state["item_order"] = [item_id for item_id in state["item_order"] if str(item_id) not in removed_item_ids]
        return removed_item_ids

    def _remove_related_records(self, state: dict[str, Any], turn_ids: set[str], item_ids: set[str]) -> None:
        for key in ("requests", "artifacts"):
            records = state.get(key)
            if not isinstance(records, dict):
                continue
            for record_id, record in list(records.items()):
                if not isinstance(record, dict):
                    continue
                if str(record.get("turn_id") or "") in turn_ids or str(record.get("item_id") or "") in item_ids:
                    records.pop(record_id, None)

    def _remove_queue_items(self, state: dict[str, Any], turn_ids: set[str]) -> None:
        if isinstance(state.get("queue"), list):
            state["queue"] = [
                item for item in state["queue"]
                if not (isinstance(item, dict) and str(item.get("turn_id") or "") in turn_ids)
            ]

    def _recompute_thread_status(self, state: dict[str, Any]) -> None:
        requests = state.get("requests")
        if isinstance(requests, dict) and any(
            isinstance(request, dict) and request.get("status") == "open" for request in requests.values()
        ):
            state["status"] = "waiting"
            return
        turns = [turn for turn in (state.get("turns") or {}).values() if isinstance(turn, dict)]
        if any(str(turn.get("status") or "") in {"running", "waiting", "interrupting"} for turn in turns):
            state["status"] = "running"
            return
        if turns:
            turns.sort(key=lambda turn: int(turn.get("last_seq") or turn.get("seq") or 0), reverse=True)
            latest = str(turns[0].get("status") or "")
            state["status"] = "failed" if latest in {"failed", "error"} else latest
            return
        state["status"] = "idle"

    def _sync_status_from_core(self, state: dict[str, Any]) -> None:
        self.sync_status_from_core(state)

    def _sync_turns_from_core(self, state: dict[str, Any]) -> None:
        core = state.get("core")
        core_turns = core.get("turns") if isinstance(core, dict) else None
        if not isinstance(core_turns, dict):
            return
        turns = state.setdefault("turns", {})
        for turn_id, core_turn in core_turns.items():
            if not isinstance(core_turn, dict):
                continue
            turn = dict(turns.get(turn_id) or {"turn_id": turn_id, "items": []})
            turn["status"] = str(core_turn.get("status") or turn.get("status") or "running")
            turn["last_seq"] = int(core_turn.get("last_seq") or turn.get("last_seq") or 0)
            if core_turn.get("run_id"):
                turn["run_id"] = str(core_turn["run_id"])
            turns[turn_id] = turn

    def sync_status_from_core(self, state: dict[str, Any]) -> None:
        core = state.get("core")
        core_status = core.get("status") if isinstance(core, dict) else None
        if not core_status:
            return
        status = str(core_status)
        if status == "cancelled":
            state["status"] = "cancelled"
        elif status in TERMINAL_ERROR_STATUSES:
            state["status"] = "failed"
        elif status in {"idle", "running", "waiting", "completed"}:
            state["status"] = status


def _already_projected(state: dict[str, Any], event: AppEventEnvelope) -> bool:
    """True when the event is already reflected in the snapshot, so replaying
    it must be skipped (applying it again would duplicate content — e.g. a
    live-sink event projected once that reappears in the turn boundary batch
    after the seen list was trimmed past 2000 entries).

    Streaming part events (metadata.runtime_phase == "runtime.part") are the
    exception: replaying a part event is harmless (the reducer appends its
    content once per event_id via seen-dedup), and treating it as projected
    would be wrong for snapshots persisted by older code that deferred part
    projection — those parts only reach the snapshot at the turn boundary,
    so their seq commonly trails the snapshot seq.
    """
    if int(state.get("snapshot_seq") or 0) < int(event.seq or 0):
        return False
    payload = event.payload if isinstance(event.payload, dict) else {}
    metadata = payload.get("metadata")
    if isinstance(metadata, dict) and metadata.get("runtime_phase") == "runtime.part":
        return False
    return True


class SqlAlchemyThreadSnapshotStore:
    """Incremental snapshot storage: items live in one row each.

    ``core_thread_snapshot_items`` (item rows) hold the thread's items; the
    snapshot row holds only the small derived state (seen_event_ids, turns,
    requests, queue, artifacts, status, session, top-level user items). A
    streaming part event therefore upserts a single item row instead of
    rewriting the whole thread JSON (1.3-2.3s on 55MB threads) — projection is
    incremental and can happen for every event, so there is no deferred
    intermediate state between "event written" and "snapshot projected".
    """

    def __init__(
        self,
        snapshot_model: type[Any],
        *,
        item_model: type[Any],
        projector: CoreAppSnapshotProjector | None = None,
    ) -> None:
        self.snapshot_model = snapshot_model
        self.item_model = item_model
        self.projector = projector or CoreAppSnapshotProjector()

    async def load(self, db: AsyncSession, thread_id: str) -> dict[str, Any]:
        row = await db.get(self.snapshot_model, thread_id)
        if row is None:
            return self.projector.empty(thread_id)
        return await self._assemble(db, row, thread_id)

    async def _assemble(self, db: AsyncSession, row: Any, thread_id: str) -> dict[str, Any]:
        """Full assembly: metadata row + every item row, ordered by seq.

        The result is byte-equivalent to the old single-JSON snapshot, so
        consumers (frontend, checkpoint, session stores) are unaffected.
        """
        state = dict(row.snapshot_json or self.projector.empty(thread_id))
        state["snapshot_seq"] = row.snapshot_seq
        items: dict[str, Any] = {}
        order: list[str] = []
        result = await db.execute(
            select(self.item_model)
            .where(self.item_model.thread_id == thread_id)
            .order_by(self.item_model.seq.asc(), self.item_model.item_id.asc())
        )
        for item_row in result.scalars():
            item = dict(item_row.item_json or {})
            item["seq"] = item_row.seq
            items[str(item_row.item_id)] = item
            order.append(str(item_row.item_id))
        core = state.get("core")
        if not isinstance(core, dict):
            core = empty_thread_snapshot(thread_id)
            state["core"] = core
        core["items"] = items
        core["item_order"] = order
        return self.projector.reconcile_status(state)

    async def _partial_state(
        self,
        db: AsyncSession,
        row: Any,
        thread_id: str,
        events: list[AppEventEnvelope],
    ) -> dict[str, Any]:
        """Partial assembly: metadata row + only the touched item rows.

        The reducer only mutates the items named by the batch's events (plus,
        for terminal status events, every item of the closing turn), so the
        untouched items never need to be loaded on the projection hot path.
        ``_item_seq_map`` (item_id -> first seq) is injected so item_order
        insertions still bisect against every item's anchor.
        """
        state = dict(row.snapshot_json or self.projector.empty(thread_id))
        state["snapshot_seq"] = row.snapshot_seq
        core = state.get("core")
        if not isinstance(core, dict):
            core = empty_thread_snapshot(thread_id)
            state["core"] = core
        touched = self._touched_item_ids(events, core)
        seq_map: dict[str, int] = {}
        result = await db.execute(
            select(self.item_model.item_id, self.item_model.seq).where(
                self.item_model.thread_id == thread_id
            )
        )
        order = list(core.get("item_order") or [])
        order_set = set(order)
        for item_id, seq in result.all():
            item_id = str(item_id)
            seq_map[item_id] = int(seq or 0)
            if item_id not in order_set:
                order.append(item_id)
                order_set.add(item_id)
        items: dict[str, Any] = {}
        if touched:
            result = await db.execute(
                select(self.item_model).where(
                    self.item_model.thread_id == thread_id,
                    self.item_model.item_id.in_(touched),
                )
            )
            for item_row in result.scalars():
                item = dict(item_row.item_json or {})
                item["seq"] = item_row.seq
                items[str(item_row.item_id)] = item
        core["items"] = items
        core["item_order"] = order
        core["_item_seq_map"] = seq_map
        return state

    @staticmethod
    def _touched_item_ids(events: list[AppEventEnvelope], core: dict[str, Any]) -> set[str]:
        touched: set[str] = set()
        for event in events:
            payload = event.payload if isinstance(event.payload, dict) else {}
            item_id = str(payload.get("item_id") or "")
            if item_id:
                touched.add(item_id)
            # Terminal status closes the turn: the reducer stamps every item of
            # that turn, so those rows must be loaded too.
            if payload.get("kind") == "status" and payload.get("status") in TERMINAL_STATUSES:
                turn_id = str(event.turn_id or "")
                turns = core.get("turns") or {}
                turn = turns.get(turn_id) if isinstance(turns, dict) else None
                if isinstance(turn, dict):
                    touched.update(str(iid) for iid in turn.get("items") or [])
        return touched

    async def apply(self, db: AsyncSession, event: AppEventEnvelope) -> dict[str, Any]:
        row = await db.get(self.snapshot_model, event.thread_id)
        if row is not None and row.snapshot_json:
            base = await self._partial_state(db, row, event.thread_id, [event])
            if _already_projected(base, event):
                return await self._assemble(db, row, event.thread_id)
            state = self.projector.apply(base, event)
        else:
            state = self.projector.apply(None, event)
            row = self.snapshot_model(thread_id=event.thread_id)
            db.add(row)
        await self._persist(db, row, state, event.thread_id)
        await db.flush()
        return state

    async def apply_many(
        self, db: AsyncSession, events: list[AppEventEnvelope]
    ) -> dict[str, Any] | None:
        if not events:
            return None
        thread_id = events[0].thread_id
        if any(event.thread_id != thread_id for event in events):
            raise ValueError("Snapshot batches must contain one thread")
        row = await db.get(self.snapshot_model, thread_id)
        if row is not None and row.snapshot_json:
            state = await self._partial_state(db, row, thread_id, events)
        else:
            state = self.projector.empty(thread_id)
        for event in sorted(events, key=lambda item: item.seq):
            if _already_projected(state, event):
                continue
            self.projector.apply_in_place(state, event)
        if row is None:
            row = self.snapshot_model(thread_id=thread_id)
            db.add(row)
        await self._persist(db, row, state, thread_id)
        await db.flush()
        return state

    async def find_request(
        self,
        db: AsyncSession,
        request_id: str,
        *,
        thread_id: str = "",
    ) -> tuple[str, dict[str, Any]] | None:
        if thread_id:
            state = await self.load(db, thread_id)
            request = (state.get("core") or {}).get("requests", {}).get(request_id)
            if not isinstance(request, dict):
                request = (state.get("requests") or {}).get(request_id)
            return (thread_id, dict(request)) if isinstance(request, dict) else None

        rows = list((await db.execute(select(self.snapshot_model))).scalars())
        matches: list[tuple[str, dict[str, Any]]] = []
        for row in rows:
            state = await self._assemble(db, row, str(row.thread_id))
            request = (state.get("core") or {}).get("requests", {}).get(request_id)
            if not isinstance(request, dict):
                request = (state.get("requests") or {}).get(request_id)
            if isinstance(request, dict):
                matches.append((str(row.thread_id), dict(request)))
        return matches[0] if len(matches) == 1 else None

    async def list_thread_ids(self, db: AsyncSession) -> list[str]:
        result = await db.execute(select(self.snapshot_model.thread_id))
        return [str(row[0]) for row in result.all() if row[0]]

    async def rebuild(
        self,
        db: AsyncSession,
        thread_id: str,
        events: list[AppEventEnvelope],
    ) -> dict[str, Any]:
        state = self.projector.reduce(thread_id, events)
        row = await db.get(self.snapshot_model, thread_id)
        if row is None:
            row = self.snapshot_model(thread_id=thread_id)
            db.add(row)
        await db.execute(delete(self.item_model).where(self.item_model.thread_id == thread_id))
        await self._persist(db, row, state, thread_id)
        await db.flush()
        return state

    async def write_full_projection(
        self,
        db: AsyncSession,
        thread_id: str,
        projection_payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Write a complete captured projection (checkpoint restore/fork).

        The payload's snapshot_json holds the full snapshot (items included);
        it is split back into item rows + metadata row, replacing any existing
        rows for the thread.
        """
        state = dict(projection_payload.get("snapshot_json") or {})
        state["snapshot_seq"] = int(projection_payload.get("snapshot_seq") or 0)
        row = await db.get(self.snapshot_model, thread_id)
        if row is None:
            row = self.snapshot_model(thread_id=thread_id)
            db.add(row)
        await db.execute(delete(self.item_model).where(self.item_model.thread_id == thread_id))
        await self._persist(db, row, state, thread_id)
        await db.flush()
        return state

    async def _persist(
        self,
        db: AsyncSession,
        row: Any,
        state: dict[str, Any],
        thread_id: str,
    ) -> None:
        """Write the projected state back incrementally.

        The touched item dicts (state["core"]["items"] — the partial assembly
        only holds those) are upserted one row each; the small metadata JSON is
        rewritten whole from a copy so the returned state keeps its items.
        flag_modified keeps the JSON column write honest (the shallow-copy
        projection mutates shared children, which SQLAlchemy's value-equality
        diff would otherwise miss).
        """
        core = state.get("core")
        items: dict[str, Any] = {}
        metadata_state = state
        if isinstance(core, dict):
            raw_items = core.get("items")
            if isinstance(raw_items, dict):
                items = raw_items
            metadata_state = dict(state)
            core_copy = dict(core)
            core_copy["items"] = {}
            core_copy.pop("_item_seq_map", None)
            metadata_state["core"] = core_copy
        metadata_state.pop("_item_seq_map", None)
        now = datetime.now()
        for item_id, item in items.items():
            seq = int(item.get("seq") or 0) if isinstance(item, dict) else 0
            existing = await db.get(self.item_model, (thread_id, str(item_id)))
            if existing is None:
                db.add(
                    self.item_model(
                        thread_id=thread_id,
                        item_id=str(item_id),
                        seq=seq,
                        item_json=item,
                        updated_at=now,
                    )
                )
            else:
                existing.seq = seq
                existing.item_json = item
                existing.updated_at = now
        row.snapshot_seq = int(state.get("snapshot_seq") or 0)
        row.snapshot_json = metadata_state
        if hasattr(row, "updated_at"):
            row.updated_at = now
        flag_modified(row, "snapshot_json")
        flag_modified(row, "snapshot_seq")
        # Keep the returned state clean of the internal anchor map.
        if isinstance(core, dict):
            core.pop("_item_seq_map", None)
        state.pop("_item_seq_map", None)


__all__ = [
    "CoreAppSnapshotProjector",
    "SqlAlchemyThreadSnapshotStore",
]
