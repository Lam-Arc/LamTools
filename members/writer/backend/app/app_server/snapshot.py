from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_server import WriterThreadSnapshot
from lamtools_core.app import AppEventEnvelope as CoreAppEventEnvelope
from lamtools_core.app import SqlAlchemyThreadSnapshotStore

from .protocol import PROTOCOL_VERSION, WriterAppEventEnvelope
from .reducer import apply_event, empty_thread_state, reconcile_status, reduce_events


class _WriterSnapshotProjector:
    def empty(self, thread_id: str) -> dict:
        return empty_thread_state(thread_id)

    def apply(self, state: dict | None, event: CoreAppEventEnvelope) -> dict:
        return apply_event(state, _to_writer_envelope(event))

    def reduce(self, thread_id: str, events: list[CoreAppEventEnvelope]) -> dict:
        return reduce_events(thread_id, [_to_writer_envelope(event) for event in events])

    def reconcile_status(self, state: dict) -> dict:
        return reconcile_status(state)


_SNAPSHOT_STORE = SqlAlchemyThreadSnapshotStore(
    WriterThreadSnapshot,
    projector=_WriterSnapshotProjector(),
)


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


def _to_writer_envelope(event: CoreAppEventEnvelope) -> WriterAppEventEnvelope:
    return WriterAppEventEnvelope(
        event_id=event.event_id,
        protocol_version=PROTOCOL_VERSION,
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


async def load_snapshot(db: AsyncSession, thread_id: str) -> dict:
    from .persistence import load_snapshot as load_persisted_snapshot

    return await load_persisted_snapshot(db, thread_id)


async def apply_event_to_snapshot(db: AsyncSession, event: WriterAppEventEnvelope) -> dict:
    from .persistence import apply_event_to_snapshot as apply_persisted_event

    return await apply_persisted_event(db, event)


async def rebuild_snapshot(db: AsyncSession, thread_id: str) -> dict:
    from .persistence import rebuild_snapshot as rebuild_persisted_snapshot

    return await rebuild_persisted_snapshot(db, thread_id)
