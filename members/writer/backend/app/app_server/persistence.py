from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from lamtools_core.app import AppPersistenceHost
from lamtools_core.event import RunItemEvent

from app.database import async_session, writer_write_coordinator

from .ledger import _EVENT_STORE, _to_writer_envelope, _to_writer_event_input
from .protocol import AppendEventInput, WriterAppEventEnvelope
from .snapshot import _SNAPSHOT_STORE, _to_core_envelope


def writer_persistence_host(session_factory=async_session) -> AppPersistenceHost:
    return AppPersistenceHost(
        _EVENT_STORE,
        _SNAPSHOT_STORE,
        session_factory=session_factory,
        write_coordinator=writer_write_coordinator(session_factory),
        write_coordinator_factory=writer_write_coordinator,
    )


_PERSISTENCE_HOST = writer_persistence_host()


async def append_event_and_apply_snapshot(
    db: AsyncSession,
    event: AppendEventInput,
) -> WriterAppEventEnvelope:
    return _to_writer_envelope(await _PERSISTENCE_HOST.append(db, _to_writer_event_input(event)))


async def append_event_and_load_snapshot(
    db: AsyncSession,
    event: AppendEventInput,
) -> tuple[WriterAppEventEnvelope, dict]:
    envelope = await append_event_and_apply_snapshot(db, event)
    return envelope, await _PERSISTENCE_HOST.load(db, envelope.thread_id)


async def append_events_and_apply_snapshot(
    db: AsyncSession,
    events: list[AppendEventInput],
) -> list[WriterAppEventEnvelope]:
    envelopes = await _PERSISTENCE_HOST.append_many(db, [_to_writer_event_input(event) for event in events])
    return [_to_writer_envelope(event) for event in envelopes]


async def append_run_item_event_and_apply_snapshot(
    db: AsyncSession,
    event: RunItemEvent,
) -> WriterAppEventEnvelope:
    return _to_writer_envelope(await _PERSISTENCE_HOST.append_run_item(db, event))


async def apply_event_to_snapshot(db: AsyncSession, event: WriterAppEventEnvelope) -> dict:
    return await _PERSISTENCE_HOST.apply(db, _to_core_envelope(event))


async def load_snapshot(db: AsyncSession, thread_id: str) -> dict:
    return await _PERSISTENCE_HOST.load(db, thread_id)


async def rebuild_snapshot(db: AsyncSession, thread_id: str) -> dict:
    return await _PERSISTENCE_HOST.rebuild(db, thread_id)


async def list_events_after(
    db: AsyncSession,
    *,
    thread_id: str,
    after_seq: int = 0,
    limit: int = 500,
) -> list[WriterAppEventEnvelope]:
    return [
        _to_writer_envelope(event)
        for event in await _PERSISTENCE_HOST.list_after(db, thread_id=thread_id, after_seq=after_seq, limit=limit)
    ]


async def list_thread_events(
    db: AsyncSession,
    *,
    thread_id: str,
    limit: int | None = None,
) -> list[WriterAppEventEnvelope]:
    return [
        _to_writer_envelope(event)
        for event in await _PERSISTENCE_HOST.list_thread(db, thread_id=thread_id, limit=limit)
    ]



__all__ = [
    "append_event_and_apply_snapshot",
    "append_event_and_load_snapshot",
    "append_events_and_apply_snapshot",
    "append_run_item_event_and_apply_snapshot",
    "apply_event_to_snapshot",
    "list_events_after",
    "list_thread_events",
    "load_snapshot",
    "rebuild_snapshot",
    "writer_persistence_host",
]
