"""Coordinates app-event persistence with thread snapshot projection."""

from __future__ import annotations

import logging
import os
import time as _time
from collections.abc import Awaitable, Callable
from datetime import datetime
import json
import uuid
from typing import Any, Iterable, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from lamtools_core.event import RunItemEvent

from .event_store import CORE_RUN_ITEM_METHOD, AppEventEnvelope, AppEventInput, SqlAlchemyAppEventStore
from .rust_db import RustDbError, get_rust_db
from .snapshot_store import SqlAlchemyThreadSnapshotStore
from .sqlite_write import SQLiteWriteCoordinator, database_identity


T = TypeVar("T")
WriteCoordinatorFactory = Callable[[Any], SQLiteWriteCoordinator]

# 写入链路的细粒度追踪：默认关闭，LAMTOOLS_PERF_TRACE=1 时每次投影打一行，
# 用来判断长会话的写入耗时落在事件追加、投影还是元数据行回写上。
_TRACE = os.environ.get("LAMTOOLS_PERF_TRACE") == "1"
_trace_logger = logging.getLogger("lamtools_core.app.persistence_host")


class RevisionConflictError(RuntimeError):
    """Raised when a mutation was based on an outdated session revision."""

    def __init__(self, *, thread_id: str, expected_revision: int, current_revision: int) -> None:
        self.thread_id = str(thread_id)
        self.expected_revision = int(expected_revision)
        self.current_revision = int(current_revision)
        super().__init__(
            f"Revision conflict for {self.thread_id}: "
            f"expected {self.expected_revision}, current {self.current_revision}"
        )

    @property
    def data(self) -> dict[str, int | str]:
        return {
            "code": "REVISION_CONFLICT",
            "thread_id": self.thread_id,
            "expected_revision": self.expected_revision,
            "current_revision": self.current_revision,
        }


class AppPersistenceHost:
    """Persists events and applies their projections without committing a transaction."""

    def __init__(
        self,
        event_store: SqlAlchemyAppEventStore,
        snapshot_store: SqlAlchemyThreadSnapshotStore,
        *,
        session_factory: Any | None = None,
        write_coordinator: SQLiteWriteCoordinator | None = None,
        write_coordinator_factory: WriteCoordinatorFactory | None = None,
    ) -> None:
        self.event_store = event_store
        self.snapshot_store = snapshot_store
        self._write_coordinator_factory = write_coordinator_factory
        self._write_coordinator = write_coordinator
        if self._write_coordinator is None and session_factory is not None:
            self._write_coordinator = self._new_write_coordinator(session_factory)

    @property
    def write_coordinator(self) -> SQLiteWriteCoordinator | None:
        return self._write_coordinator

    def bind_session_factory(self, session_factory: Any) -> None:
        if (
            self._write_coordinator is None
            or self._write_coordinator.identity != database_identity(session_factory)
        ):
            self._write_coordinator = self._new_write_coordinator(session_factory)

    def _new_write_coordinator(self, session_factory: Any) -> SQLiteWriteCoordinator:
        if self._write_coordinator_factory is not None:
            return self._write_coordinator_factory(session_factory)
        return SQLiteWriteCoordinator(session_factory)

    def _active_rust_db(self) -> Any | None:
        rust_db = getattr(self.snapshot_store, "_rust_db", None)
        if rust_db is not None and rust_db.is_active:
            return rust_db
        rust_db = getattr(self.event_store, "_rust_db", None)
        if rust_db is not None and rust_db.is_active:
            return rust_db
        if self._write_coordinator is not None:
            return get_rust_db(getattr(self._write_coordinator, "session_factory", None))
        return None

    @property
    def can_use_rust_write(self) -> bool:
        return (
            self._active_rust_db() is not None
            and type(self).write is AppPersistenceHost.write
            and "write" not in self.__dict__
        )

    async def write(self, action: Callable[[AsyncSession], Awaitable[T]]) -> T:
        if self._write_coordinator is None:
            raise RuntimeError("AppPersistenceHost requires a session factory for writes")
        return await self._write_coordinator.run(action)

    async def append_batch_atomic(
        self,
        *,
        app_events: Iterable[AppEventInput] = (),
        run_item_events: Iterable[RunItemEvent] = (),
        return_state: bool = False,
        project_snapshot: bool = True,
        expected_revision: int | None = None,
        revision_thread_id: str | None = None,
        require_new: bool = False,
        only_new: bool = False,
    ) -> list[AppEventEnvelope] | tuple[list[AppEventEnvelope], dict[str, Any] | None]:
        """Run ``append_batch`` atomically in Rust when available, or fall back to ``write``."""
        app_event_list = list(app_events)
        run_item_list = list(run_item_events)
        if not app_event_list and not run_item_list:
            return ([], None) if return_state else []

        rust_db = self._active_rust_db() if self.can_use_rust_write else None
        if rust_db is not None:
            # user:“实现，我需要最后可感觉到的体验优化”+(事件批量写库与快照增量投影合并为 Rust 单次事务，提交后原地刷新缓存)。
            from .core_db import _json_safe

            serialized_events: list[dict[str, Any]] = []
            touched_threads: set[str] = set()
            for ev in app_event_list:
                eid = ev.event_id or uuid.uuid4().hex
                touched_threads.add(ev.thread_id)
                serialized_events.append(
                    {
                        "event_id": eid,
                        "thread_id": ev.thread_id,
                        "method": ev.method,
                        "turn_id": ev.turn_id,
                        "item_id": ev.item_id,
                        "parent_item_id": ev.parent_item_id,
                        "client_message_id": ev.client_message_id,
                        "payload": _json_safe(dict(ev.payload or {})),
                        "workspace_id": str(
                            ev.workspace_id or getattr(self.event_store, "workspace_id", "") or ""
                        ),
                        "entity_type": str(ev.entity_type or "thread.event"),
                        "event_type": str(ev.event_type or ev.method),
                    }
                )
            for item in run_item_list:
                eid = item.event_id or uuid.uuid4().hex
                touched_threads.add(item.thread_id)
                serialized_events.append(
                    {
                        "event_id": eid,
                        "thread_id": item.thread_id,
                        "method": CORE_RUN_ITEM_METHOD,
                        "turn_id": item.turn_id or None,
                        "item_id": item.item_id or None,
                        "parent_item_id": item.parent_item_id or None,
                        "client_message_id": None,
                        "payload": _json_safe(item.to_dict()),
                        "workspace_id": str(getattr(self.event_store, "workspace_id", "") or ""),
                        "entity_type": "thread.event",
                        "event_type": CORE_RUN_ITEM_METHOD,
                    }
                )
            projector = getattr(self.snapshot_store, "projector", None)
            member_defaults = getattr(projector, "member_defaults", None)
            emit_sync = getattr(self.event_store, "sync_change_model", None) is not None
            try:
                # user:“check，事件通道压力过高：可靠通道 32/64；已丢弃 257 帧可丢进度；正在自动恢复，无需操作”+(透传 only_new 并在无新增事件时免于清缓存/广播)
                res = await rust_db.call(
                    "append_and_project_batch",
                    {
                        "events": serialized_events,
                        "project_snapshot": bool(project_snapshot),
                        "expected_revision": int(expected_revision) if expected_revision is not None else None,
                        "revision_thread_id": revision_thread_id,
                        "workspace_id": str(getattr(self.event_store, "workspace_id", "") or ""),
                        "emit_sync": emit_sync,
                        "return_state": bool(return_state),
                        "require_new": bool(require_new),
                        "only_new": bool(only_new),
                        "member_defaults": member_defaults if isinstance(member_defaults, dict) else None,
                        "now_str": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
                    },
                )
            except RustDbError as exc:
                if exc.code == "conflict":
                    try:
                        info = json.loads(str(exc))
                    except ValueError:
                        info = {}
                    if info.get("code") == "SESSION_ALREADY_EXISTS":
                        return ([], None) if return_state else []
                    raise RevisionConflictError(
                        thread_id=str(info.get("thread_id") or revision_thread_id or ""),
                        expected_revision=int(info.get("expected_revision") or (expected_revision or 0)),
                        current_revision=int(info.get("current_revision") or 0),
                    ) from exc
                if exc.code == "invalid":
                    raise ValueError(str(exc)) from exc
                raise

            envelopes = [
                self.event_store._envelope_from_dict(row)
                for row in (res.get("envelopes") or [])
            ]
            py_cache = getattr(self.snapshot_store, "_metadata_cache", None)
            if isinstance(py_cache, dict) and envelopes:
                for tid in touched_threads:
                    py_cache.pop(tid, None)

            if return_state:
                return envelopes, res.get("state")
            return envelopes

        async def _fallback_write(db: AsyncSession):
            if require_new and app_event_list:
                snap_model = getattr(self.snapshot_store, "snapshot_model", None)
                if snap_model is not None and await db.get(snap_model, str(app_event_list[0].thread_id)) is not None:
                    return ([], None) if return_state else []
            filtered_app = app_event_list
            filtered_run = run_item_list
            if only_new:
                event_model = getattr(self.event_store, "event_model", None)
                if event_model is not None:
                    if expected_revision is not None:
                        target_tid = revision_thread_id or (
                            app_event_list[0].thread_id if app_event_list else run_item_list[0].thread_id
                        )
                        await self.assert_revision(db, target_tid, expected_revision)
                    seen_batch: dict[str, str] = {}
                    filtered_app = []
                    for ev in app_event_list:
                        eid = str(ev.event_id or "").strip()
                        if eid:
                            if eid in seen_batch:
                                if seen_batch[eid] != ev.thread_id:
                                    raise ValueError("Event identity belongs to another thread")
                                continue
                            existing = await db.get(event_model, eid)
                            if existing is not None:
                                if existing.thread_id != ev.thread_id:
                                    raise ValueError("Event identity belongs to another thread")
                                continue
                            seen_batch[eid] = ev.thread_id
                        filtered_app.append(ev)
                    filtered_run = []
                    for item in run_item_list:
                        eid = str(item.event_id or "").strip()
                        if eid:
                            if eid in seen_batch:
                                if seen_batch[eid] != item.thread_id:
                                    raise ValueError("Event identity belongs to another thread")
                                continue
                            existing = await db.get(event_model, eid)
                            if existing is not None:
                                if existing.thread_id != item.thread_id:
                                    raise ValueError("Event identity belongs to another thread")
                                continue
                            seen_batch[eid] = item.thread_id
                        filtered_run.append(item)
                    if not filtered_app and not filtered_run:
                        return ([], None) if return_state else []
            return await self.append_batch(
                db,
                app_events=filtered_app,
                run_item_events=filtered_run,
                return_state=return_state,
                project_snapshot=project_snapshot,
                expected_revision=expected_revision,
                revision_thread_id=revision_thread_id,
            )

        return await self.write(_fallback_write)

    async def assert_revision_atomic(
        self,
        thread_id: str,
        expected_revision: int | None,
    ) -> int:
        if expected_revision is None:
            return 0
        rust_db = self._active_rust_db() if self.can_use_rust_write else None
        if rust_db is not None:
            meta = await rust_db.call(
                "load_snapshot_metadata",
                {"thread_id": str(thread_id)},
            )
            current = max(0, int(((meta or {}).get("state") or {}).get("revision") or 0))
            if int(expected_revision) != current:
                raise RevisionConflictError(
                    thread_id=str(thread_id),
                    expected_revision=int(expected_revision),
                    current_revision=current,
                )
            return current
        return await self.write(lambda db: self.assert_revision(db, thread_id, expected_revision))

    async def _refresh_envelopes(
        self,
        db: AsyncSession,
        envelopes: list[AppEventEnvelope],
    ) -> list[AppEventEnvelope]:
        """Refresh store-owned fields when the event store supports it.

        The production SQLAlchemy store reloads rows after projection so fields
        such as the canonical revision are returned to callers.  Keeping the
        fallback here makes the persistence host usable with small in-memory
        or test doubles that already return complete envelopes.
        """

        refresh = getattr(self.event_store, "refresh_envelopes", None)
        if not callable(refresh):
            return envelopes
        return await refresh(db, envelopes)

    async def append(self, db: AsyncSession, event: AppEventInput) -> AppEventEnvelope:
        async with db.begin_nested():
            envelope = await self._append(db, event)
            refreshed = await self._refresh_envelopes(db, [envelope])
            return refreshed[0]

    async def append_run_item(self, db: AsyncSession, event: RunItemEvent) -> AppEventEnvelope:
        async with db.begin_nested():
            envelope = await self.event_store.append_run_item_event(db, event)
            await self.apply(db, envelope)
            refreshed = await self._refresh_envelopes(db, [envelope])
            return refreshed[0]

    async def append_many(
        self,
        db: AsyncSession,
        events: Iterable[AppEventInput],
        *,
        expected_revision: int | None = None,
        revision_thread_id: str | None = None,
    ) -> list[AppEventEnvelope]:
        app_events = list(events)
        if not app_events:
            return []
        return await self.append_batch(
            db,
            app_events=app_events,
            expected_revision=expected_revision,
            revision_thread_id=revision_thread_id,
        )

    async def append_batch(
        self,
        db: AsyncSession,
        *,
        app_events: Iterable[AppEventInput] = (),
        run_item_events: Iterable[RunItemEvent] = (),
        return_state: bool = False,
        project_snapshot: bool = True,
        expected_revision: int | None = None,
        revision_thread_id: str | None = None,
        require_new: bool = False,
    ) -> list[AppEventEnvelope] | tuple[list[AppEventEnvelope], dict[str, Any] | None]:
        """Append multiple events in one savepoint with a single batch projection.

        With ``project_snapshot=False`` events are appended to the event table
        only; the thread snapshot is NOT projected. Streaming emits many
        low-frequency state events (part start/end, status, usage) while a turn
        is running — projecting the full thread snapshot for each one costs
        1.3-2.3s on 55MB threads (measured) and stalls the stream. The snapshot
        is projected once at the turn boundary instead; clients keep rendering
        from the runItem event stream in the meantime.
        """
        app_event_list = list(app_events)
        run_item_list = list(run_item_events)
        if not app_event_list and not run_item_list:
            if return_state:
                return [], None
            return []
        _trace_started = _time.perf_counter()
        async with db.begin_nested():
            if expected_revision is not None:
                target_thread_id = revision_thread_id or (
                    app_event_list[0].thread_id if app_event_list else run_item_list[0].thread_id
                )
                await self.assert_revision(db, target_thread_id, expected_revision)
            envelopes: list[AppEventEnvelope] = []
            for event in app_event_list:
                envelope = await self.event_store.append(db, event)
                envelopes.append(envelope)
            for item in run_item_list:
                envelope = await self.event_store.append_run_item_event(db, item)
                envelopes.append(envelope)
            if _TRACE:
                _trace_logger.info(
                    "[PERF:append_batch] events=%.3fs app=%d run=%d thread_id=%s",
                    _time.perf_counter() - _trace_started,
                    len(app_event_list),
                    len(run_item_list),
                    envelopes[0].thread_id if envelopes else "",
                )
            if not project_snapshot:
                return await self._refresh_envelopes(db, envelopes)
            by_thread: dict[str, list[AppEventEnvelope]] = {}
            for envelope in envelopes:
                by_thread.setdefault(envelope.thread_id, []).append(envelope)
            state: dict[str, Any] | None = None
            for group in by_thread.values():
                state = await self.snapshot_store.apply_many(db, group)
            envelopes = await self._refresh_envelopes(db, envelopes)
            if return_state:
                # apply_many returns the partial projection (only touched
                # items); callers that hand the state to clients need the full
                # assembled snapshot.
                if state is not None:
                    state = await self.snapshot_store.load(db, state.get("thread_id") or "")
                return envelopes, state
            return envelopes

    async def _append(self, db: AsyncSession, event: AppEventInput) -> AppEventEnvelope:
        envelope = await self.event_store.append(db, event)
        await self.apply(db, envelope)
        return envelope

    async def apply(self, db: AsyncSession, event: AppEventEnvelope) -> dict[str, Any]:
        return await self.snapshot_store.apply(db, event)

    async def current_revision(self, db: AsyncSession, thread_id: str) -> int:
        """Return the durable revision for a thread, or zero if it is new."""

        row = await db.get(self.snapshot_store.snapshot_model, str(thread_id))
        if row is None:
            return 0
        value = getattr(row, "revision", None)
        if value is None:
            state = getattr(row, "snapshot_json", None)
            value = state.get("revision", 0) if isinstance(state, dict) else 0
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError):
            return 0

    async def assert_revision(
        self,
        db: AsyncSession,
        thread_id: str,
        expected_revision: int | None,
    ) -> int:
        """CAS-check a thread revision inside the caller's write transaction.

        ``None`` deliberately preserves the legacy read/modify/write behavior
        for local callers that have not opted into optimistic concurrency yet.
        An explicit zero is meaningful for a newly-created session and is not
        treated as an omitted value.
        """

        current = await self.current_revision(db, thread_id)
        if expected_revision is None:
            return current
        expected = int(expected_revision)
        if expected != current:
            raise RevisionConflictError(
                thread_id=thread_id,
                expected_revision=expected,
                current_revision=current,
            )
        return current

    async def load(self, db: AsyncSession, thread_id: str) -> dict[str, Any]:
        return await self.snapshot_store.load(db, thread_id)

    async def load_metadata(self, db: AsyncSession, thread_id: str) -> dict[str, Any]:
        """Load the metadata row only (turns/queue/requests/item_order).

        ``core.items`` is intentionally empty; never hand this to clients as a
        conversation snapshot.
        """
        return await self.snapshot_store.load_metadata(db, thread_id)

    async def load_page(
        self,
        db: AsyncSession,
        thread_id: str,
        *,
        before_seq: int | None = None,
        before_item_id: str | None = None,
        item_byte_budget: int | None = None,
    ) -> dict[str, Any]:
        """Load one conversation page: metadata + only the newest item rows.

        ``core.item_order`` still lists every item id, so the caller can report
        the paging envelope; ``core.items`` holds only the loaded rows.
        """
        kwargs: dict[str, Any] = {
            "before_seq": before_seq,
            "before_item_id": before_item_id,
        }
        if item_byte_budget is not None:
            kwargs["item_byte_budget"] = int(item_byte_budget)
        return await self.snapshot_store.load_page(db, thread_id, **kwargs)

    async def load_items_by_kind(
        self,
        db: AsyncSession,
        thread_id: str,
        *,
        text_marker: str,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Metadata plus only the item rows matching a text marker.

        See ``SqlAlchemyThreadSnapshotStore.load_items_by_kind``; the outline uses
        it to read the transcript's assistant bodies without materializing the
        thread's tool traffic.
        """
        kwargs: dict[str, Any] = {"text_marker": text_marker}
        if limit is not None:
            kwargs["limit"] = int(limit)
        return await self.snapshot_store.load_items_by_kind(db, thread_id, **kwargs)

    async def load_page_around(
        self,
        db: AsyncSession,
        thread_id: str,
        *,
        item_id: str,
        item_byte_budget: int | None = None,
    ) -> tuple[int | None, dict[str, Any]]:
        """Load the one page whose newest item is ``item_id`` (search jump).

        Directly locating a message replaces walking the history cursor page by
        page; see ``SqlAlchemyThreadSnapshotStore.load_page_around``.
        """
        kwargs: dict[str, Any] = {"item_id": item_id}
        if item_byte_budget is not None:
            kwargs["item_byte_budget"] = int(item_byte_budget)
        return await self.snapshot_store.load_page_around(db, thread_id, **kwargs)


    async def list_thread_ids(self, db: AsyncSession) -> list[str]:
        return await self.snapshot_store.list_thread_ids(db)

    async def list_active_thread_ids(self, db: AsyncSession) -> list[str]:
        return await self.snapshot_store.list_active_thread_ids(db)

    async def rebuild(self, db: AsyncSession, thread_id: str) -> dict[str, Any]:
        events = await self.list_thread(db, thread_id=thread_id)
        return await self.snapshot_store.rebuild(db, thread_id, events)

    async def list_after(
        self,
        db: AsyncSession,
        *,
        thread_id: str,
        after_seq: int = 0,
        limit: int = 500,
    ) -> list[AppEventEnvelope]:
        return await self.event_store.list_after(db, thread_id=thread_id, after_seq=after_seq, limit=limit)

    async def list_thread(
        self,
        db: AsyncSession,
        *,
        thread_id: str,
        limit: int | None = None,
    ) -> list[AppEventEnvelope]:
        return await self.event_store.list_thread(db, thread_id=thread_id, limit=limit)

    async def find_client_event(
        self,
        db: AsyncSession,
        *,
        thread_id: str,
        client_message_id: str,
        methods: set[str],
    ) -> AppEventEnvelope | None:
        return await self.event_store.find_client_event(
            db,
            thread_id=thread_id,
            client_message_id=client_message_id,
            methods=methods,
        )

    # user:“该修修，相关插件也要修”+(失败收尾查询目标回合，不能只检查会话的前五百条事件)。
    async def find_turn_event(
        self, db: AsyncSession, *, thread_id: str, turn_id: str,
        terminal_only: bool = False,
    ) -> AppEventEnvelope | None:
        return await self.event_store.find_turn_event(
            db, thread_id=thread_id, turn_id=turn_id, terminal_only=terminal_only,
        )


__all__ = ["AppPersistenceHost", "RevisionConflictError"]
