from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_server import WriterAppEvent
from lamtools_core.app import AppEventInput as CoreAppEventInput
from lamtools_core.app import AppEventEnvelope as CoreAppEventEnvelope
from lamtools_core.app import SqlAlchemyAppEventStore

from .protocol import PROTOCOL_VERSION, AppendEventInput, WriterAppEventEnvelope

MAX_SEQ_ALLOCATE_ATTEMPTS = 5
_EVENT_STORE = SqlAlchemyAppEventStore(
    WriterAppEvent,
    protocol_version=PROTOCOL_VERSION,
    max_seq_allocate_attempts=MAX_SEQ_ALLOCATE_ATTEMPTS,
)


def _to_writer_event_input(event: AppendEventInput) -> CoreAppEventInput:
    return CoreAppEventInput(
        event_id=event.event_id,
        thread_id=event.thread_id,
        method=event.method,
        payload=dict(event.payload or {}),
        turn_id=event.turn_id,
        item_id=event.item_id,
        parent_item_id=event.parent_item_id,
        client_message_id=event.client_message_id,
    )


def _to_writer_envelope(event: CoreAppEventEnvelope) -> WriterAppEventEnvelope:
    return WriterAppEventEnvelope(
        event_id=event.event_id,
        seq=event.seq,
        thread_id=event.thread_id,
        turn_id=event.turn_id,
        item_id=event.item_id,
        parent_item_id=event.parent_item_id,
        client_message_id=event.client_message_id,
        method=event.method,
        payload=dict(event.payload or {}),
        created_at=event.created_at,
    )


async def list_events_after(db: AsyncSession, *, thread_id: str, after_seq: int = 0, limit: int = 500) -> list[WriterAppEventEnvelope]:
    from .persistence import list_events_after as list_persisted_events

    return await list_persisted_events(db, thread_id=thread_id, after_seq=after_seq, limit=limit)


async def list_thread_events(db: AsyncSession, *, thread_id: str, limit: int | None = None) -> list[WriterAppEventEnvelope]:
    from .persistence import list_thread_events as list_persisted_thread_events

    return await list_persisted_thread_events(db, thread_id=thread_id, limit=limit)
