"""Generic thread snapshot storage for Core Agent hosts."""

from __future__ import annotations

import logging
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from lamtools_core.event import RunItemEvent
from lamtools_core.snapshot import (
    TERMINAL_STATUSES,
    apply_run_item_event_in_place,
    empty_thread_snapshot,
    reconcile_terminal_requests,
    recompute_thread_status,
)
from lamtools_core.turn.model import LIVE_RUNTIME_STATUSES

from .event_store import CORE_RUN_ITEM_METHOD, AppEventEnvelope
from .queue_state import effective_thread_status, queue_order_key

logger = logging.getLogger(__name__)

TERMINAL_ERROR_STATUSES = {"failed", "cancelled", "error"}
TERMINAL_TURN_STATUSES = {"completed", *TERMINAL_ERROR_STATUSES}

#: Byte budget for one bounded conversation-page item read. The page builder
#: caps a served page at ``MAX_THREAD_HISTORY_PAGE_BYTES`` (3 MiB), so this
#: leaves headroom to fill a page while never materializing a whole thread.
DEFAULT_PAGE_ITEM_BYTES = 6 * 1024 * 1024

#: Row cap for the same read: a count guard for threads made of tiny items.
MAX_PAGE_ITEM_ROWS = 4000


@dataclass
class CoreAppSnapshotProjector:
    member_defaults: dict[str, Any] = field(default_factory=dict)

    def empty(self, thread_id: str) -> dict[str, Any]:
        state = {
            "thread_id": thread_id,
            "snapshot_seq": 0,
            "revision": 0,
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
        elif event.method == "queue/itemReordered":
            self._apply_queue_reordered(state, event)
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
        self._sync_turns_from_core(state, only_turn_id=str(payload.get("turn_id") or "") or None)
        self._apply_member_wait_flag(state, payload)

    def _apply_member_wait_flag(self, state: dict[str, Any], payload: dict[str, Any]) -> None:
        """Lift the member-wait fact onto the turn as ``waiting_on_members``.

        ``runtime.sub_agent_wait`` / ``runtime.sub_agent_report`` project a
        ``subAgents`` status item; the meaningful bit for a client is whether the
        turn is currently held open for background members, which is a property
        of the turn, not of one row. Reading it off the turn lets the UI tell
        "the main agent is still working" from "the main agent is done and only
        its members are still running" without scanning for a private item id.
        """
        inner = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
        if str(inner.get("type") or "") != "subAgents":
            return
        turn_id = str(payload.get("turn_id") or inner.get("turn_id") or "")
        if not turn_id:
            return
        turn = state.setdefault("turns", {}).setdefault(
            turn_id, {"turn_id": turn_id, "status": "running", "items": []}
        )
        turn["waiting_on_members"] = bool(inner.get("waiting_on_members"))
        raw_members = inner.get("members")
        turn["running_members"] = [
            str(member.get("name") or "")
            for member in raw_members
            if isinstance(member, dict) and member.get("name")
        ] if isinstance(raw_members, list) else []

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
                "created_at": event.created_at.isoformat(),
                "input": payload.get("input"),
                "work_root": payload.get("work_root") or payload.get("workRoot") or "",
            }
        )
        runtime_snapshot = payload.get("runtime_snapshot")
        if isinstance(runtime_snapshot, dict):
            # The accepted event is the durable authority for this turn.  Do
            # not derive these fields again from current Composer/settings.
            turn["runtime_snapshot"] = deepcopy(runtime_snapshot)
        # Provenance of an automatic (non-user) turn, e.g. "member_wake": kept on
        # the turn so the interface can mark its input as a system event.
        origin = str(payload.get("origin") or "").strip()
        if origin:
            turn["origin"] = origin
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
        if payload.get("resumed") is True:
            # Only explicit Resume reopens a terminal turn. Ordinary late
            # runtime frames retain the existing terminal-state protection.
            core = state.setdefault("core", empty_thread_snapshot(event.thread_id))
            core_turn = core.setdefault("turns", {}).setdefault(turn_id, {"turn_id": turn_id, "items": []})
            core_turn.update({"status": "running", "run_id": payload.get("run_id"), "last_seq": event.seq})
            core["status"] = "running"
            core.pop("last_error", None)

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
        # Automatic-turn provenance rides the input item too, so the interface
        # can mark this bubble as a system event without joining to the turn.
        origin = str(payload.get("origin") or "").strip()
        if origin:
            item["origin"] = origin
            if payload.get("role"):
                item["role"] = str(payload["role"])
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
        turns = state.get("turns") if isinstance(state.get("turns"), dict) else {}
        existing = turns.get(turn_id) if isinstance(turns, dict) else None
        terminal = {"completed", "failed", "cancelled", "skipped"}
        if not isinstance(existing, dict) or str(existing.get("status") or "") in terminal:
            # user:“旧回合错误显示运行中”+(引导事件绝不允许凭空造出一个
            # 「运行中」的回合：投影里没有这个回合、或它已经有终态时，这条追加输入
            # 不改变任何状态，更不能把 last_seq 顶到最新、让界面把旧回合当成当前的
            # 活动回合去继续引导)。
            return
        turn = self._turn(state, turn_id)
        # user:“把它作为一个引导信息发进去”+(引导是追加输入，不得覆盖原任务；
        # 早停后重启仍须能分别恢复原任务与未消费的引导)。
        turn.update({key: value for key, value in payload.items()
                     if key not in {"status", "input", "runtime_input"}})
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

    def _apply_queue_reordered(self, state: dict[str, Any], event: AppEventEnvelope) -> None:
        # user:“排队项可拖拽上下移动重新排序”+(重排序事件携带拖拽后的完整顺序：
        #   给点名的排队条目写 position 并重排快照列表；没被点名的条目（并发新排队）
        #   必须清掉旧 position，分发与托盘排序才会把它按 seq 垫在已定位条目之后)。
        payload = dict(event.payload or {})
        order = payload.get("order")
        if not isinstance(order, list):
            return
        queue = list(state.get("queue") or [])
        position_by_id: dict[str, int] = {}
        next_position = 0
        for entry in order:
            queue_item_id = str(entry or "").strip()
            if queue_item_id and queue_item_id not in position_by_id:
                position_by_id[queue_item_id] = next_position
                next_position += 1
        for item in queue:
            if not isinstance(item, dict):
                continue
            # 未点名条目若保留旧 position，会插到已定位条目中间，与“新排队按 seq
            # 垫底”的排序契约相反。
            item.pop("position", None)
            queue_item_id = str(item.get("queue_item_id") or "")
            if queue_item_id in position_by_id:
                item["position"] = position_by_id[queue_item_id]
        queue.sort(key=queue_order_key)
        state["queue"] = queue

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
        """Delegate to the one canonical derivation.

        This used to be a second copy, and the copies drifted: the local one
        tested the open requests before the turns, so a paused turn that still
        held an unanswered question read back as ``waiting`` on every load. The
        client reads that container status, kept believing the session was
        active, and (before the client-side escalation was removed) terminated
        the turn the user had just paused (2026-10-14).
        """
        recompute_thread_status(state)

    def _sync_status_from_core(self, state: dict[str, Any]) -> None:
        self.sync_status_from_core(state)

    def _sync_turns_from_core(
        self, state: dict[str, Any], *, only_turn_id: str | None = None
    ) -> None:
        """Mirror core turn status/usage onto the flattened turn map.

        ``only_turn_id`` restricts the mirror to the turn the projected event
        belongs to. A single runtime event can only change its own turn, and the
        full walk copies and deep-copies every historical turn's usage: on a
        600-turn thread that was ~10ms of every projected write.
        """
        core = state.get("core")
        core_turns = core.get("turns") if isinstance(core, dict) else None
        if not isinstance(core_turns, dict):
            return
        turns = state.setdefault("turns", {})
        if only_turn_id is not None:
            selected = core_turns.get(only_turn_id)
            pairs = ((only_turn_id, selected),) if selected is not None else ()
        else:
            pairs = core_turns.items()
        for turn_id, core_turn in pairs:
            if not isinstance(core_turn, dict):
                continue
            turn = dict(turns.get(turn_id) or {"turn_id": turn_id, "items": []})
            turn["status"] = str(core_turn.get("status") or turn.get("status") or "running")
            turn["last_seq"] = int(core_turn.get("last_seq") or turn.get("last_seq") or 0)
            if core_turn.get("run_id"):
                turn["run_id"] = str(core_turn["run_id"])
            if isinstance(core_turn.get("usage"), dict):
                turn["usage"] = deepcopy(core_turn["usage"])
            if isinstance(core_turn.get("context_metrics"), dict):
                turn["context_metrics"] = deepcopy(core_turn["context_metrics"])
            turns[turn_id] = turn

    def sync_status_from_core(self, state: dict[str, Any]) -> None:
        core = state.get("core")
        core_status = core.get("status") if isinstance(core, dict) else None
        if not core_status:
            return
        status = str(core_status)
        if status == "paused":
            # A paused turn owns the session: the list, the composer and the
            # sidebar all read the flattened status, so it has to say paused.
            state["status"] = "paused"
        elif status == "cancelled":
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

    #: How many threads' parsed metadata rows stay cached. The metadata row is
    #: the one part of a thread that grows with its whole item list
    #: (core.item_order + every turn's items), so on a 100k-item thread it is
    #: tens of MB and decoding it is the dominant cost of every page read.
    #: Two entries cover "the open thread plus the one being left"; anything
    #: more would hold several such rows resident.
    METADATA_CACHE_LIMIT = 2

    def __init__(
        self,
        snapshot_model: type[Any],
        *,
        item_model: type[Any],
        projector: CoreAppSnapshotProjector | None = None,
        event_model: type[Any] | None = None,
    ) -> None:
        self.snapshot_model = snapshot_model
        self.item_model = item_model
        self.projector = projector or CoreAppSnapshotProjector()
        self.event_model = event_model
        # thread_id -> (revision, snapshot_seq, parsed metadata state).
        self._metadata_cache: dict[str, tuple[int, int, dict[str, Any]]] = {}

    def invalidate_metadata_cache(self, thread_id: str | None = None) -> None:
        """Drop the parsed-metadata cache for one thread (or all of them)."""
        if thread_id is None:
            self._metadata_cache.clear()
        else:
            self._metadata_cache.pop(thread_id, None)

    def _remember_metadata(
        self, thread_id: str, revision: int, snapshot_seq: int, state: dict[str, Any]
    ) -> None:
        while len(self._metadata_cache) >= self.METADATA_CACHE_LIMIT:
            oldest = next(iter(self._metadata_cache))
            self._metadata_cache.pop(oldest, None)
        self._metadata_cache[thread_id] = (revision, snapshot_seq, state)

    @staticmethod
    def _copy_metadata_state(state: dict[str, Any]) -> dict[str, Any]:
        """A writable view of a cached metadata row.

        Readers decorate the state they were handed (``snapshot_seq``,
        ``core.items``, repaired turns) and one of them
        (``prune_orphan_turns``) pops turn ids. Copy the containers those
        writes land in so a cached row is never mutated by a reader; the turn
        dicts themselves are treated as immutable by every read path.
        """
        copy = dict(state)
        core = copy.get("core")
        if isinstance(core, dict):
            core = dict(core)
            copy["core"] = core
            turns = core.get("turns")
            if isinstance(turns, dict):
                core["turns"] = dict(turns)
        turns = copy.get("turns")
        if isinstance(turns, dict):
            copy["turns"] = dict(turns)
        return copy

    def _probe_supported(self) -> bool:
        """Whether this store's row model can answer the cheap revision probe.

        ``revision`` was added after the first schema; hosts (and tests) that
        build a lighter row model keep the full read, uncached, exactly as
        before.
        """
        return hasattr(self.snapshot_model, "revision")

    async def _probe_metadata_row(
        self, db: AsyncSession, thread_id: str
    ) -> tuple[int, int, str] | None:
        """``(revision, snapshot_seq, active_turn_id)`` without the JSON payload.

        ``active_turn_id`` is the storage layer's own derived index (maintained
        by the model's before_insert/before_update hook), so it answers "is any
        turn still active" without reading a single turn.
        """
        model = self.snapshot_model
        columns: list[Any] = [model.revision]
        columns.append(model.snapshot_seq)
        has_active_column = hasattr(model, "active_turn_id")
        if has_active_column:
            columns.append(model.active_turn_id)
        result = await db.execute(select(*columns).where(model.thread_id == thread_id))
        found = result.first()
        if found is None:
            return None
        revision = _row_revision(None, {"revision": found[0]})
        snapshot_seq = int(found[1] or 0)
        active_turn_id = str(found[2] or "") if has_active_column else ""
        return revision, snapshot_seq, active_turn_id

    async def _metadata_state(
        self, db: AsyncSession, thread_id: str
    ) -> tuple[int, int, str, dict[str, Any]] | None:
        """``(revision, snapshot_seq, active_turn_id, writable metadata copy)``.

        A cache hit costs one primary-key probe and skips loading/decoding the
        metadata JSON entirely. The revision only moves forward on a write, so a
        match means the cached row is current; the write path also invalidates
        explicitly (see ``_persist``).
        """
        if self._probe_supported():
            probe = await self._probe_metadata_row(db, thread_id)
            if probe is None:
                self._metadata_cache.pop(thread_id, None)
                return None
            revision, snapshot_seq, active_turn_id = probe
            cached = self._metadata_cache.get(thread_id)
            if cached is not None and cached[0] == revision:
                return revision, snapshot_seq, active_turn_id, self._copy_metadata_state(cached[2])
        row = await db.get(self.snapshot_model, thread_id)
        if row is None:
            return None
        base = dict(row.snapshot_json or self.projector.empty(thread_id))
        revision = _row_revision(row, base)
        snapshot_seq = int(row.snapshot_seq or 0)
        if self._probe_supported():
            self._remember_metadata(thread_id, revision, snapshot_seq, dict(base))
            return revision, snapshot_seq, active_turn_id, self._copy_metadata_state(base)
        # Legacy/lightweight row model: no revision to validate a cached entry
        # and no derived active-turn index, so the read-time repairs always run
        # (``None`` forces them) and nothing is cached.
        legacy_active_turn: str | None = str(
            getattr(row, "active_turn_id", "") or ""
        ) or None
        return revision, snapshot_seq, legacy_active_turn, base

    def _finish_state(
        self, state: dict[str, Any], active_turn_id: str | None
    ) -> dict[str, Any]:
        """Strip inline image copies and run the read-time repairs when needed.

        ``reconcile_status`` and ``prune_orphan_turns`` each walk the thread's
        whole turn table; they undo damage left by older builds (a turn nothing
        owns stuck at "running", a stale thread status). ``active_turn_id`` is
        derived on every write, so "no active turn and a settled status" already
        proves there is nothing to repair — a long idle thread must not pay
        three full turn walks on every page read.
        """
        state = _strip_inline_image_copies(state)
        if _projection_needs_repair(state, active_turn_id):
            return prune_orphan_turns(self.projector.reconcile_status(state))
        return state

    def _remember_hydrated(self, thread_id: str, state: dict[str, Any]) -> None:
        """Carry the usage-hydration marker back into the cached metadata row.

        ``_hydrate_resource_usage`` replays every usage event of the thread and
        then stamps ``core.resource_usage_version`` so it never runs twice. It
        stamps the caller's copy, so without this the cached base would stay
        unmarked and every page read of a never-rewritten thread would replay
        the whole usage journal again.
        """
        cached = self._metadata_cache.get(thread_id)
        if cached is None:
            return
        core = state.get("core")
        cached_state = cached[2]
        cached_core = cached_state.get("core")
        if (
            isinstance(core, dict)
            and isinstance(cached_core, dict)
            and core.get("resource_usage_version") == 1
        ):
            cached_core["resource_usage_version"] = 1

    async def load(self, db: AsyncSession, thread_id: str) -> dict[str, Any]:
        meta = await self._metadata_state(db, thread_id)
        if meta is None:
            return self.projector.empty(thread_id)
        return await self._assemble_metadata(db, meta, thread_id)

    async def _assemble(
        self,
        db: AsyncSession,
        row: Any,
        thread_id: str,
    ) -> dict[str, Any]:
        return await self._assemble_metadata(
            db,
            (_row_revision(row, None), int(getattr(row, "snapshot_seq", 0) or 0),
             None, dict(row.snapshot_json or self.projector.empty(thread_id))),
            thread_id,
        )

    async def _assemble_metadata(
        self,
        db: AsyncSession,
        meta: tuple[int, int, str | None, dict[str, Any]],
        thread_id: str,
    ) -> dict[str, Any]:
        """Full assembly: metadata row + every item row, ordered by seq.

        The result is byte-equivalent to the old single-JSON snapshot, so
        consumers (frontend, checkpoint, session stores) are unaffected.
        """
        revision, snapshot_seq, active_turn_id, state = meta
        state["snapshot_seq"] = snapshot_seq
        state["revision"] = revision
        await self._hydrate_resource_usage(db, state, thread_id)
        self._remember_hydrated(thread_id, state)
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
        decisions = await self._load_open_interactions(db, thread_id)
        core["decisions"] = decisions
        core["interactions"] = decisions
        core["task_plan"] = await self._load_active_plan(db, thread_id)
        return self._finish_state(state, active_turn_id)

    async def load_metadata(self, db: AsyncSession, thread_id: str) -> dict[str, Any]:
        """Load only the metadata row: turns/queue/requests/registry/item_order.

        Callers that need turn status, queue membership, or the top-level user
        item order — but not the per-item conversation content — avoid the
        full item-table scan and JSON parse here. ``core.items`` is empty by
        design; consumers must not treat this as a complete snapshot.
        """
        meta = await self._metadata_state(db, thread_id)
        if meta is None:
            return self.projector.empty(thread_id)
        revision, snapshot_seq, active_turn_id, state = meta
        state["snapshot_seq"] = snapshot_seq
        state["revision"] = revision
        await self._hydrate_resource_usage(db, state, thread_id)
        self._remember_hydrated(thread_id, state)
        core = state.get("core")
        if not isinstance(core, dict):
            core = empty_thread_snapshot(thread_id)
            state["core"] = core
        core.setdefault("items", {})
        core.setdefault("item_order", [])
        decisions = await self._load_open_interactions(db, thread_id)
        core["decisions"] = decisions
        core["interactions"] = decisions
        core["task_plan"] = await self._load_active_plan(db, thread_id)
        return self._finish_state(state, active_turn_id)

    async def _load_active_plan(self, db: AsyncSession, thread_id: str) -> dict[str, Any] | None:
        """The thread's durable checklist, read straight from the runtime row.

        user:“重启之后想要继续，往往需要发一条用户指令，这样就会让以前的 checklist
        消失吗？我认为这是不对的”+(checklist 与轮次解耦：快照每次读取都带上
        runtime 会话行里的权威 task_plan，前端在消息流扫描落空（历史窗口裁剪/
        重启后新指令）时兜底显示，卡不再消失)。

        Mirrors `_load_open_interactions`: the plan's source of truth is the
        runtime session row (saved on every kernel checkpoint), not the message
        tree. One primary-key read; a missing row (foreign thread stores, tests
        with lightweight schemas) simply yields no plan.
        """
        try:
            from .core_db import CoreRuntimeSession

            row = (
                await db.execute(
                    select(CoreRuntimeSession.runtime_state_json).where(
                        CoreRuntimeSession.thread_id == thread_id
                    )
                )
            ).scalar()
        except Exception:
            # 只吞查询失败（轻量 schema/外部线程库）；CancelledError 必须继续上抛，
            # 否则请求/关停时任务无法取消。
            return None
        payload = row if isinstance(row, dict) else {}
        metadata = payload.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        task_plan = metadata.get("task_plan")
        return task_plan if isinstance(task_plan, dict) else None

    async def _load_open_interactions(
        self, db: AsyncSession, thread_id: str
    ) -> list[dict[str, Any]]:
        """Open decisions as a first-class snapshot field.

        The transcript window may not include the turn that owns an older
        card; the composer must still be able to answer it.  This query is
        indexed by (thread_id, status) and only returns open/deferred rows.

        用户要求（原文）：“池子的持久化做了吗”
        池子的事实源是 core_turn_interactions（创建即落库，回答/取消即终态），
        快照每次读取都用本查询覆盖 core.decisions / core.interactions；
        不依赖消息树，也不依赖快照 JSON 里的事件归约结果。
        """
        try:
            from .core_db import CoreTurnInteraction

            rows = (
                await db.execute(
                    select(CoreTurnInteraction)
                    .where(
                        CoreTurnInteraction.thread_id == thread_id,
                        CoreTurnInteraction.status.in_(
                            ("open", "deferred", "processing")
                        ),
                    )
                    .order_by(CoreTurnInteraction.created_seq.asc())
                )
            ).scalars().all()
        except BaseException:
            return []
        return [
            {
                "interaction_id": str(row.interaction_id),
                "turn_id": str(row.turn_id),
                "run_id": str(row.run_id or ""),
                "scope": str(row.scope or "main"),
                "kind": str(row.kind),
                "status": str(row.status),
                "lifecycle": (
                    "processing" if str(row.status) == "processing" else "appearing"
                ),
                "decision_id": "dec_"
                + __import__("hashlib")
                .sha256(str(row.interaction_id).encode("utf-8"))
                .hexdigest()[:32],
                "sequence": int(row.created_seq or 0),
                "project_id": str(
                    (row.metadata_json or {}).get("project_id") or ""
                ),
                "agent_name": str(
                    (row.metadata_json or {}).get("agent_name") or ""
                ),
                "agent_session_id": str(
                    (row.metadata_json or {}).get("agent_session_id") or ""
                ),
                "delivered_by": str(
                    (row.metadata_json or {}).get("delivered_by") or "main"
                ),
                "tool_call_id": str(row.tool_call_id or ""),
                "title": str(row.title or ""),
                "body": str(row.body or ""),
                "context": str(row.context_text or ""),
                "options": list(row.options_json or []),
                "expires_at_ms": int(row.expires_at_ms or 0),
                "answer": row.answer_json,
                "metadata": dict(row.metadata_json or {}),
            }
            for row in rows
        ]

    async def load_page(
        self,
        db: AsyncSession,
        thread_id: str,
        *,
        before_seq: int | None = None,
        before_item_id: str | None = None,
        item_byte_budget: int = DEFAULT_PAGE_ITEM_BYTES,
    ) -> dict[str, Any]:
        """Metadata plus only the item rows one conversation page needs.

        The item table holds one row per item, and long threads run to thousands
        of rows of conversation content. Assembling every row to answer the first
        screen is what made a session open cost tens of seconds on a cold cache,
        so this read walks the ``(thread_id, seq)`` index backwards from the
        cursor and stops once the accumulated ``item_json`` bytes reach
        ``item_byte_budget``. ``core.item_order`` keeps the full metadata order
        (every item id, loaded or not), so the caller can still report
        ``history_page.total_items`` / ``has_more`` from the metadata alone.

        Top-level (user) items live inside the metadata row, so they are always
        present; only the per-item conversation rows are bounded.
        """
        state, core, active_turn_id = await self._page_state(db, thread_id)
        if state is None:
            return self.projector.empty(thread_id)
        if before_seq is None and before_item_id:
            before_seq = await self._item_seq(db, thread_id, before_item_id)
        loaded = await self._load_item_rows(
            db, thread_id, before_seq=before_seq, item_byte_budget=item_byte_budget
        )
        core["items"] = loaded
        core["_page_has_older_items"] = await self._has_older_items(
            db, thread_id, loaded, before_seq=before_seq
        )
        # Exact loaded-or-not item total without walking the metadata order:
        # item rows and top-level (user) items are disjoint by construction —
        # ``_persist`` only upserts ``core.items``, so a user message never gets
        # a row here. The page builder needs it for ``total_items`` and would
        # otherwise union two id lists that are as long as the whole thread.
        core["_page_total_items"] = await self._item_row_count(db, thread_id)
        # 决策池必须随分页快照一起下发：会话重开/断线重连走的是 load_page，
        # 之前只有完整 load 才注入 interactions，客户端只好退回消息树兜底，
        # 桌宠与主界面都会丢掉审批/提问的标题、选项和子代理来源。
        decisions = await self._load_open_interactions(db, thread_id)
        core["decisions"] = decisions
        core["interactions"] = decisions
        core["task_plan"] = await self._load_active_plan(db, thread_id)
        return self._finish_state(state, active_turn_id)

    async def _page_state(
        self, db: AsyncSession, thread_id: str
    ) -> tuple[dict[str, Any] | None, dict[str, Any], str]:
        """Shared front half of the bounded reads: metadata row + core container.

        The third value is the row's ``active_turn_id``: the repair gate the
        caller passes to ``_finish_state``.
        """
        meta = await self._metadata_state(db, thread_id)
        if meta is None:
            return None, {}, ""
        revision, snapshot_seq, active_turn_id, state = meta
        state["snapshot_seq"] = snapshot_seq
        state["revision"] = revision
        await self._hydrate_resource_usage(db, state, thread_id)
        self._remember_hydrated(thread_id, state)
        core = state.get("core")
        if not isinstance(core, dict):
            core = empty_thread_snapshot(thread_id)
            state["core"] = core
        core.setdefault("item_order", [])
        return state, core, active_turn_id

    async def _has_older_items(
        self,
        db: AsyncSession,
        thread_id: str,
        loaded: dict[str, Any],
        *,
        before_seq: int | None,
    ) -> bool:
        """Whether any item row exists older than what this read materialized.

        One index probe, so the caller can report ``has_more`` correctly without
        loading the rest of the thread. An empty read (nothing newer than the
        cursor) means nothing is left.
        """
        if not loaded:
            return False
        oldest = min(int(item.get("seq") or 0) for item in loaded.values())
        stmt = select(self.item_model.item_id).where(
            self.item_model.thread_id == thread_id,
            self.item_model.seq < oldest,
        )
        if before_seq is not None:
            stmt = stmt.where(self.item_model.seq < int(before_seq))
        result = await db.execute(stmt.limit(1))
        return result.scalar() is not None

    async def _item_seq(self, db: AsyncSession, thread_id: str, item_id: str) -> int | None:
        result = await db.execute(
            select(self.item_model.seq).where(
                self.item_model.thread_id == thread_id,
                self.item_model.item_id == item_id,
            )
        )
        value = result.scalar()
        return int(value) if value is not None else None

    async def load_items_by_kind(
        self,
        db: AsyncSession,
        thread_id: str,
        *,
        text_marker: str,
        limit: int = 200_000,
    ) -> dict[str, Any]:
        """Metadata plus only the item rows whose stored JSON mentions a marker.

        The outline needs each turn's closing assistant message and nothing
        else, but the rows carry tool traffic that is 95% of a thread's bytes
        (measured: 561MB of item rows for 48k items, of which ~480MB is tool
        output). Matching on the raw JSON text keeps the filter in SQLite's C
        code — no row is JSON-decoded unless it can matter — and the caller gets
        the same metadata row it would get from ``load_metadata``.

        ``text_marker`` must be a literal that appears only in the rows the
        caller wants (for an agent message: ``"agentMessage"``).
        """
        if not text_marker:
            return await self.load_metadata(db, thread_id)
        state = await self.load_metadata(db, thread_id)
        if not state or not state.get("thread_id"):
            return state
        core = state.get("core")
        if not isinstance(core, dict):
            core = {}
            state["core"] = core
        model = self.item_model
        stmt = (
            select(model)
            .where(
                model.thread_id == thread_id,
                model.item_json.like(f'%"{text_marker}"%'),
            )
            .order_by(model.seq.asc(), model.item_id.asc())
            .limit(limit)
        )
        items: dict[str, Any] = {}
        for item_row in (await db.execute(stmt)).scalars():
            item = dict(item_row.item_json or {})
            item["seq"] = item_row.seq
            items[str(item_row.item_id)] = item
        core["items"] = items
        return state

    async def resolve_item_seq(
        self, db: AsyncSession, thread_id: str, item_id: str
    ) -> int | None:
        """Thread-global seq of any item id, or ``None`` when it is not here.

        Assistant process items have a row in the item table; user/system
        messages live in the metadata row's ``items``. Both are addressed by the
        same seq timeline, so a locator needs the same answer for either.
        """
        if not item_id:
            return None
        seq = await self._item_seq(db, thread_id, item_id)
        if seq is not None:
            return seq
        meta = await self._metadata_state(db, thread_id)
        if meta is None:
            return None
        state = meta[3]
        core = state.get("core") if isinstance(state.get("core"), dict) else {}
        for container in (state, core):
            items = container.get("items")
            if isinstance(items, dict):
                item = items.get(item_id)
                if isinstance(item, dict):
                    value = item.get("seq", item.get("last_seq"))
                    try:
                        return int(value) if value is not None else None
                    except (TypeError, ValueError):
                        return None
            order = container.get("item_order")
            if isinstance(order, list):
                try:
                    index = order.index(item_id)
                except ValueError:
                    continue
                # Same convention the page builder uses for an item with no
                # seq: its 1-based position in the stored order.
                return index + 1
        return None

    async def load_page_around(
        self,
        db: AsyncSession,
        thread_id: str,
        *,
        item_id: str,
        item_byte_budget: int = DEFAULT_PAGE_ITEM_BYTES,
    ) -> tuple[int | None, dict[str, Any]]:
        """One bounded page ending at ``item_id``, i.e. the window containing it.

        Jumping to a search hit used to walk the history cursor one page at a
        time until the target appeared, which costs one round trip per page for
        a hit deep in a long thread. Resolving the target's seq turns that into
        a single bounded read: everything older than the target (inclusive) is
        what the page ends at, so the caller can show the hit immediately.

        Returns ``(seq, snapshot)``; a ``None`` seq means the id is not in this
        thread, and an empty page is returned.
        """
        seq = await self.resolve_item_seq(db, thread_id, item_id)
        if seq is None:
            return None, self.projector.empty(thread_id)
        # ``before_seq`` is exclusive, so +1 makes the page end at the target.
        state = await self.load_page(
            db,
            thread_id,
            before_seq=seq + 1,
            item_byte_budget=item_byte_budget,
        )
        return seq, state

    async def _load_item_rows(
        self,
        db: AsyncSession,
        thread_id: str,
        *,
        before_seq: int | None,
        item_byte_budget: int,
    ) -> dict[str, Any]:
        """Newest-first item rows up to the byte budget.

        Two phases, because the budget has to stop the read *before* the rows
        are decoded: the driver hands back everything the statement matched, so
        a single ``select(model)`` with a row LIMIT still JSON-decodes every
        matched row (measured: 4000 rows / 46MB decoded to serve a 40-item
        page). Phase one reads ``(seq, item_id, length(item_json))`` — no JSON
        is decoded — and decides where the budget stops; phase two fetches only
        the rows inside that boundary.
        """
        budget = max(1, int(item_byte_budget))
        model = self.item_model
        sizes = select(model.seq, model.item_id, func.length(model.item_json)).where(
            model.thread_id == thread_id
        )
        if before_seq is not None:
            sizes = sizes.where(model.seq < int(before_seq))
        sizes = sizes.order_by(model.seq.desc(), model.item_id.desc()).limit(
            MAX_PAGE_ITEM_ROWS
        )
        chosen: list[int] = []
        total = 0
        for seq, _item_id, size in (await db.execute(sizes)).all():
            chosen.append(int(seq))
            total += int(size or 0)
            if total >= budget:
                break
        if not chosen:
            return {}
        oldest = min(chosen)
        rows = select(model).where(
            model.thread_id == thread_id,
            model.seq >= oldest,
        )
        if before_seq is not None:
            rows = rows.where(model.seq < int(before_seq))
        rows = rows.order_by(model.seq.asc(), model.item_id.asc())
        items: dict[str, Any] = {}
        for item_row in (await db.execute(rows)).scalars():
            item = dict(item_row.item_json or {})
            item["seq"] = item_row.seq
            items[str(item_row.item_id)] = item
        return items


    async def _hydrate_resource_usage(self, db: AsyncSession, state: dict[str, Any], thread_id: str) -> None:
        """Recover per-call usage from the journal for pre-history snapshots only."""
        core = state.get("core")
        if not isinstance(core, dict) or core.get("resource_usage_version") == 1 or self.event_model is None:
            return
        if not core.get("turns"):
            core["resource_usage_version"] = 1
            return
        model = self.event_model
        result = await db.execute(select(model).where(
            model.thread_id == thread_id,
            model.seq <= int(state.get("snapshot_seq") or 0),
            model.method == CORE_RUN_ITEM_METHOD,
            model.payload_json["kind"].as_string() == "usage",
        ).order_by(model.seq.asc()))
        usage_state = empty_thread_snapshot(thread_id)
        for event_row in result.scalars():
            payload = dict(event_row.payload_json or {})
            payload["seq"] = event_row.seq
            apply_run_item_event_in_place(usage_state, RunItemEvent.from_dict(payload))
        for turn_id, resources in usage_state["turns"].items():
            turn = core.setdefault("turns", {}).setdefault(turn_id, {"turn_id": turn_id})
            for key in ("usage", "usage_calls", "child_context_metrics"):
                if key in resources:
                    turn[key] = resources[key]
        core["resource_usage_version"] = 1
        self.projector._sync_turns_from_core(state)

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
        state["revision"] = _row_revision(row, state)
        await self._hydrate_resource_usage(db, state, thread_id)
        core = state.get("core")
        if not isinstance(core, dict):
            core = empty_thread_snapshot(thread_id)
            state["core"] = core
        touched = self._touched_item_ids(events, core)
        seq_map: dict[str, int] = {}
        order = list(core.get("item_order") or [])
        order_set = set(order)
        # user:“发送耗时原则上不应随历史会话长度显著增长”+(这份全量 item 索引扫描只
        # 为两件事：修复 item_order 里漏掉的条目、给快照还没见过的新条目按 seq 定位
        # 插入点。批次里没有新条目时两件都不需要，而扫描本身是 O(会话条目数)——
        # 2400 条时每次写入白扫 13ms。一次 COUNT 就能替代“要不要修复”的判断。
        needs_anchors = any(item_id not in order_set for item_id in touched)
        if needs_anchors or await self._item_row_count(db, thread_id) != len(order):
            needs_anchors = True
            result = await db.execute(
                select(self.item_model.item_id, self.item_model.seq).where(
                    self.item_model.thread_id == thread_id
                )
            )
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
        if needs_anchors:
            core["_item_seq_map"] = seq_map
        else:
            core.pop("_item_seq_map", None)
        return _strip_inline_image_copies(state)

    async def _item_row_count(self, db: AsyncSession, thread_id: str) -> int:
        """Item rows for one thread; the cheap repair signal for item_order."""
        result = await db.execute(
            select(func.count()).select_from(self.item_model).where(
                self.item_model.thread_id == thread_id
            )
        )
        return int(result.scalar_one() or 0)

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
            state["revision"] = _row_revision(row, base) + 1
        else:
            state = self.projector.apply(None, event)
            state["revision"] = 1
            row = self.snapshot_model(thread_id=event.thread_id)
            db.add(row)
        await self._persist(
            db,
            row,
            state,
            event.thread_id,
            event_revisions={event.event_id: int(state.get("revision") or 0)},
        )
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
        import os as _perf_os
        import time as _perf_time

        _perf_trace = _perf_os.environ.get("LAMTOOLS_PERF_TRACE") == "1"
        _perf_mark = _perf_time.perf_counter()

        def _perf_last(label: str) -> None:
            nonlocal _perf_mark
            if _perf_trace:
                logger.info(
                    "[PERF:apply_many] %s=%.3fs thread_id=%s",
                    label,
                    _perf_time.perf_counter() - _perf_mark,
                    thread_id,
                )
                _perf_mark = _perf_time.perf_counter()

        row = await db.get(self.snapshot_model, thread_id)
        if row is not None and row.snapshot_json:
            state = await self._partial_state(db, row, thread_id, events)
        else:
            state = self.projector.empty(thread_id)
        _perf_last("partial_state")
        revision = _row_revision(row, state) if row is not None else 0
        event_revisions: dict[str, int] = {}
        for event in sorted(events, key=lambda item: item.seq):
            if _already_projected(state, event):
                continue
            self.projector.apply_in_place(state, event)
            revision += 1
            state["revision"] = revision
            event_revisions[event.event_id] = revision
        if row is None:
            row = self.snapshot_model(thread_id=thread_id)
            db.add(row)
        state.setdefault("revision", revision)
        await self._persist(
            db,
            row,
            state,
            thread_id,
            event_revisions=event_revisions,
        )
        _perf_last("persist_build")
        await db.flush()
        _perf_last("flush")
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

    async def list_active_thread_ids(self, db: AsyncSession) -> list[str]:
        """Return only snapshots that can require unexpected-shutdown repair."""
        if not hasattr(self.snapshot_model, "active_turn_id"):
            return await self.list_thread_ids(db)
        result = await db.execute(
            select(self.snapshot_model.thread_id).where(
                self.snapshot_model.active_turn_id.isnot(None)
            )
        )
        return [str(row[0]) for row in result.all() if row[0]]

    async def rebuild(
        self,
        db: AsyncSession,
        thread_id: str,
        events: list[AppEventEnvelope],
    ) -> dict[str, Any]:
        state = self.projector.reduce(thread_id, events)
        row = await db.get(self.snapshot_model, thread_id)
        prior_revision = _row_revision(row, {}) if row is not None else 0
        if row is None:
            row = self.snapshot_model(thread_id=thread_id)
            db.add(row)
        event_revision = max((int(event.revision or 0) for event in events), default=0)
        state["revision"] = max(prior_revision, event_revision, len(events))
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
        if "revision" not in state:
            state["revision"] = int(
                projection_payload.get("revision")
                or (_row_revision(row, {}) if row is not None else 0)
            )
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
        *,
        event_revisions: dict[str, int] | None = None,
    ) -> None:
        """Write the projected state back incrementally.

        The touched item dicts (state["core"]["items"] — the partial assembly
        only holds those) are upserted one row each; the small metadata JSON is
        rewritten whole from a copy so the returned state keeps its items.
        flag_modified keeps the JSON column write honest (the shallow-copy
        projection mutates shared children, which SQLAlchemy's value-equality
        diff would otherwise miss). The artifact registry copy written into
        the metadata row is slimmed of legacy inline image bytes, so rows
        written before that rule shrink on the thread's next natural write.
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
        metadata_state = slim_registry_inline_images(metadata_state)
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
        if hasattr(row, "revision"):
            # 修订号是客户端的乐观锁期望值，只能前进：一旦写回一个更低的值，
            # 已经见过更高值的客户端就再也改不动这个会话（客户端丢弃回退的
            # 快照，CAS 永远失败）。回填/重建快照等路径传入的 state 可能没有
            # 修订号，这里取行上已有值与新值的较大者。
            row.revision = max(
                _row_revision(row, state),
                max(0, int(state.get("revision") or 0)),
            )
        row.snapshot_json = metadata_state
        # The parsed-metadata cache holds the pre-write row; this write replaces
        # it, so drop it instead of serving a stale turn list / item order.
        self.invalidate_metadata_cache(thread_id)
        if hasattr(row, "updated_at"):
            row.updated_at = now
        flag_modified(row, "snapshot_json")
        flag_modified(row, "snapshot_seq")
        if hasattr(row, "revision"):
            flag_modified(row, "revision")
        if self.event_model is not None and event_revisions:
            for event_id, revision in event_revisions.items():
                event_row = await db.get(self.event_model, event_id)
                if event_row is None:
                    continue
                if hasattr(event_row, "revision"):
                    event_row.revision = max(0, int(revision))
                if hasattr(event_row, "event_seq") and hasattr(event_row, "seq"):
                    event_row.event_seq = int(event_row.seq or 0)
        # Keep the returned state clean of the internal anchor map.
        if isinstance(core, dict):
            core.pop("_item_seq_map", None)
        state.pop("_item_seq_map", None)


__all__ = [
    "CoreAppSnapshotProjector",
    "SqlAlchemyThreadSnapshotStore",
    "slim_registry_inline_images",
]

# read_file 风格的图片 artifact 曾把同一份 base64 data URL 存三份：条目 payload
# 元数据、条目 artifacts 列表、core.artifacts 登记表。UI 只从条目 artifacts 渲染
# （messageParts 的 part.artifacts），其余两份是每次装载/写回/序列化的纯重量。
# 新写入不再记录冗余副本（runtime_projection / _apply_artifact）；旧库行在读取时
# 就地剥离，并在下一次自然写回元数据行时落盘变瘦（slim_registry_inline_images）。
_INLINE_IMAGE_METADATA_KEY = "image_data_url"


def _slim_registry_inline_images(registry: Any) -> Any:
    """Drop legacy inline image bytes from artifact registry copies before the
    metadata row is written back.

    New projections never record them (snapshot._apply_artifact strips the
    registry copy), but rows written before that rule carried the base64 in
    the registry metadata and every partial projection copied it forward
    verbatim. Stripping at write time slims those rows lazily on the thread's
    next natural write — no migration, no rewrite of untouched history. Read
    behavior is unchanged: _strip_inline_image_copies already removed these
    copies from every loaded state, so nothing ever observed them.

    Content bodies are deliberately NOT stripped here: a payload-only artifact
    (an event with no per-item artifacts list) can carry the snapshot's only
    body copy, and a metadata write-back must not load the item table to prove
    otherwise — stripping it would change read semantics. Inline image bytes
    carry no such risk: every read path already drops the registry copy
    (``_strip_inline_image_copies``), so removing it at write time cannot change
    what any reader sees. Affected entries are copied before stripping — the
    caller's state shares them.
    """
    if not isinstance(registry, dict):
        return registry
    stripped: dict[str, Any] | None = None
    for artifact_id, artifact in registry.items():
        if not isinstance(artifact, dict):
            continue
        metadata = artifact.get("metadata")
        if not (isinstance(metadata, dict) and _INLINE_IMAGE_METADATA_KEY in metadata):
            continue
        if stripped is None:
            stripped = dict(registry)
        slim_entry = dict(artifact)
        slim_entry["metadata"] = {
            key: value for key, value in metadata.items() if key != _INLINE_IMAGE_METADATA_KEY
        }
        stripped[artifact_id] = slim_entry
    return stripped if stripped is not None else registry


def slim_registry_inline_images(state: Any) -> Any:
    """Return ``state`` with legacy inline image bytes dropped from its artifact
    registry copies; a state that carries none is returned unchanged.

    Every natural write-back of a session metadata row passes its state through
    here — snapshot projections (``_persist``), session metadata updates, and
    project ownership writes. Rows written before the write-side dedup rule
    still hold the base64 data URL in the registry; the next ordinary write of
    that session rewrites the row without it, so history shrinks on use. No
    migration pass, no direct rewrite of untouched rows. Readers are unaffected:
    ``_strip_inline_image_copies`` already removed these copies from every
    loaded state, so nothing ever observed them.
    """
    if not isinstance(state, dict):
        return state
    slim_state: dict[str, Any] | None = None
    core = state.get("core")
    if isinstance(core, dict):
        registry = core.get("artifacts")
        slimmed = _slim_registry_inline_images(registry)
        if slimmed is not registry:
            slim_state = dict(state)
            slim_core = dict(core)
            slim_core["artifacts"] = slimmed
            slim_state["core"] = slim_core
    base = slim_state if slim_state is not None else state
    top_level = base.get("artifacts")
    if isinstance(top_level, dict):
        slimmed = _slim_registry_inline_images(top_level)
        if slimmed is not top_level:
            if slim_state is None:
                slim_state = dict(state)
            slim_state["artifacts"] = slimmed
    return slim_state if slim_state is not None else state


def _strip_inline_image_metadata(metadata: Any) -> Any:
    if isinstance(metadata, dict) and _INLINE_IMAGE_METADATA_KEY in metadata:
        return {k: v for k, v in metadata.items() if k != _INLINE_IMAGE_METADATA_KEY}
    return metadata


_REPAIR_STATUSES = frozenset({"running", "waiting", "interrupting", "paused"})


def _projection_needs_repair(state: dict[str, Any], active_turn_id: str | None) -> bool:
    """Whether the read-time status repairs can possibly change this row.

    ``reconcile_status`` and ``prune_orphan_turns`` fix a projection damaged by
    an older build: a turn nothing owns stuck at ``running``, or a thread status
    that never settled. Both walk every turn of the thread, and a long thread
    has tens of thousands of them, so a page read must not pay for them unless
    the damage is actually possible.

    ``active_turn_id`` is derived from the projection on every write (see
    ``_sync_snapshot_active_turn_index``) and answers "is any turn still open"
    without touching a single turn. No open turn plus a settled status means
    there is nothing to repair; ``None`` forces the repair for callers that hold
    only a projection and no row.
    """
    if active_turn_id is None:
        return True
    if active_turn_id:
        return True
    return effective_thread_status(state) in _REPAIR_STATUSES


def prune_orphan_turns(state: dict[str, Any]) -> dict[str, Any]:
    """Drop an invented turn and settle the thread status (read-time repair).

    An approval response used to name a turn derived from a delegated child's
    run, which created a turn nothing owns and nothing closes: it stayed
    `running` forever, so a session whose work had finished kept reading as
    running. New rows cannot be created any more (the emitter names the answered
    turn and the projector only resumes turns that exist); this removes the ones
    already stored, on every read, so a reload shows the truth. The rule is
    deliberately narrow: only an active turn with no items whose last event was
    an approval response can match, and no real turn looks like that.

    The two containers hold the same turn id with different fields (the core
    copy carries ``last_kind``), so the evidence is merged per turn id before
    the test and both copies are dropped together.
    """
    turns = state.get("turns")
    core = state.get("core")
    core_turns = core.get("turns") if isinstance(core, dict) else None
    containers = [item for item in (turns, core_turns) if isinstance(item, dict)]
    active = LIVE_RUNTIME_STATUSES
    evidence: dict[str, dict[str, Any]] = {}
    for container in containers:
        for turn_id, turn in container.items():
            if not isinstance(turn, dict):
                continue
            merged = evidence.setdefault(str(turn_id), {"statuses": set(), "kinds": set(), "items": 0})
            status = str(turn.get("status") or "")
            if status:
                merged["statuses"].add(status)
            kind = str(turn.get("last_kind") or "")
            if kind:
                merged["kinds"].add(kind)
            merged["items"] += len(turn.get("items") or ())
    for turn_id, merged in evidence.items():
        statuses = merged["statuses"]
        if not statuses or any(status not in active for status in statuses):
            continue
        if merged["items"]:
            continue
        if merged["kinds"] != {"approval_response"}:
            continue
        for container in containers:
            container.pop(turn_id, None)
    if _no_active_turn(turns) and _no_active_turn(core_turns):
        latest = None
        for container in (turns, core_turns):
            if not isinstance(container, dict):
                continue
            for turn in container.values():
                if not isinstance(turn, dict):
                    continue
                if latest is None or int(turn.get("last_seq") or 0) >= int(latest.get("last_seq") or 0):
                    latest = turn
        status = str((latest or {}).get("status") or "")
        settled = {"completed": "completed", "cancelled": "cancelled", "failed": "failed"}.get(status)
        if settled and str(state.get("status") or "") in {"running", "waiting", "interrupting"}:
            state["status"] = settled
            if isinstance(core, dict):
                core["status"] = settled
    return state


def _no_active_turn(container: Any) -> bool:
    if not isinstance(container, dict):
        return True
    return not any(
        str((turn or {}).get("status") or "") in {"running", "waiting", "interrupting"}
        for turn in container.values()
        if isinstance(turn, dict)
    )


def _strip_inline_image_copies(state: dict[str, Any]) -> dict[str, Any]:
    """Drop redundant inline image copies from an assembled/loaded state."""
    core = state.get("core") if isinstance(state.get("core"), dict) else None
    registry = core.get("artifacts") if isinstance(core, dict) else None
    if isinstance(registry, dict):
        for artifact in registry.values():
            if not isinstance(artifact, dict):
                continue
            stripped = _strip_inline_image_metadata(artifact.get("metadata"))
            if stripped is not None:
                artifact["metadata"] = stripped
    items = core.get("items") if isinstance(core, dict) else None
    if isinstance(items, dict):
        for item in items.values():
            if not isinstance(item, dict):
                continue
            payload = item.get("payload")
            if not isinstance(payload, dict):
                continue
            stripped = _strip_inline_image_metadata(payload.get("metadata"))
            if stripped is not None:
                payload["metadata"] = stripped
    return state


def _row_revision(row: Any | None, state: dict[str, Any] | None = None) -> int:
    """Read revision from both current and legacy snapshot row shapes."""

    value = getattr(row, "revision", None) if row is not None else None
    if value is None and isinstance(state, dict):
        value = state.get("revision")
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0
