"""Generic app-event storage for Core Agent hosts."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from lamtools_core.event import RunItemEvent

CORE_RUN_ITEM_METHOD = "core/runItem"
MAX_SEQ_ALLOCATE_ATTEMPTS = 5


def _new_event_id() -> str:
    return uuid.uuid4().hex[:16]


@dataclass(frozen=True)
class AppEventInput:
    thread_id: str
    method: str
    payload: dict[str, Any] = field(default_factory=dict)
    event_id: str | None = None
    turn_id: str | None = None
    item_id: str | None = None
    parent_item_id: str | None = None
    client_message_id: str | None = None


@dataclass(frozen=True)
class AppEventEnvelope:
    event_id: str
    protocol_version: str
    seq: int
    thread_id: str
    method: str
    payload: dict[str, Any]
    created_at: datetime
    turn_id: str | None = None
    item_id: str | None = None
    parent_item_id: str | None = None
    client_message_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = {
            "event_id": self.event_id,
            "protocol_version": self.protocol_version,
            "thread_id": self.thread_id,
            "method": self.method,
            "payload": dict(self.payload or {}),
            "created_at": self.created_at.isoformat(),
            "turn_id": self.turn_id,
            "item_id": self.item_id,
            "parent_item_id": self.parent_item_id,
            "client_message_id": self.client_message_id,
        }
        # seq=0 means "no persisted anchor" (transient stream deltas published
        # with a placeholder seq). Omitting it keeps clients from treating 0
        # as a real ordering anchor — they must fall back to the item's
        # existing seq (or leave it unset) until a real event lands.
        if self.seq:
            data["seq"] = self.seq
        return data


class SqlAlchemyAppEventStore:
    def __init__(
        self,
        event_model: type[Any],
        *,
        protocol_version: str = "core.agent.v1",
        max_seq_allocate_attempts: int = MAX_SEQ_ALLOCATE_ATTEMPTS,
    ) -> None:
        self.event_model = event_model
        self.protocol_version = protocol_version
        self.max_seq_allocate_attempts = max_seq_allocate_attempts

    async def append(self, db: AsyncSession, event: AppEventInput) -> AppEventEnvelope:
        event_id = event.event_id or _new_event_id()
        return await self._append_once(db, event, event_id=event_id)

    async def _append_once(self, db: AsyncSession, event: AppEventInput, *, event_id: str) -> AppEventEnvelope:
        existing = await db.get(self.event_model, event_id)
        if existing is not None:
            return self._to_envelope(existing)

        last_error: IntegrityError | None = None
        for attempt in range(self.max_seq_allocate_attempts):
            result = await db.execute(
                select(func.coalesce(func.max(self.event_model.seq), 0)).where(
                    self.event_model.thread_id == event.thread_id
                )
            )
            next_seq = int(result.scalar_one()) + 1
            row = self.event_model(
                **self._row_kwargs(
                    event,
                    event_id=event_id,
                    seq=next_seq,
                )
            )
            try:
                async with db.begin_nested():
                    db.add(row)
                    await db.flush()
            except IntegrityError as exc:
                last_error = exc
                existing = await db.get(self.event_model, event_id)
                if existing is not None:
                    return self._to_envelope(existing)
                if attempt < self.max_seq_allocate_attempts - 1:
                    continue
                raise
            return self._to_envelope(row)

        if last_error is not None:
            raise last_error
        raise RuntimeError("Failed to allocate app event sequence")

    async def append_run_item_event(self, db: AsyncSession, event: RunItemEvent) -> AppEventEnvelope:
        return await self.append(
            db,
            AppEventInput(
                event_id=event.event_id,
                thread_id=event.thread_id,
                method=CORE_RUN_ITEM_METHOD,
                turn_id=event.turn_id or None,
                item_id=event.item_id or None,
                parent_item_id=event.parent_item_id or None,
                payload=event.to_dict(),
            ),
        )

    async def list_after(
        self,
        db: AsyncSession,
        *,
        thread_id: str,
        after_seq: int = 0,
        limit: int = 500,
    ) -> list[AppEventEnvelope]:
        result = await db.execute(
            select(self.event_model)
            .where(self.event_model.thread_id == thread_id, self.event_model.seq > after_seq)
            .order_by(self.event_model.seq.asc())
            .limit(limit)
        )
        return [self._to_envelope(row) for row in result.scalars().all()]

    async def list_thread(
        self,
        db: AsyncSession,
        *,
        thread_id: str,
        limit: int | None = None,
    ) -> list[AppEventEnvelope]:
        query = (
            select(self.event_model)
            .where(self.event_model.thread_id == thread_id)
            .order_by(self.event_model.seq.asc())
        )
        if limit is not None:
            query = query.limit(limit)
        result = await db.execute(query)
        return [self._to_envelope(row) for row in result.scalars().all()]

    async def find_client_event(
        self,
        db: AsyncSession,
        *,
        thread_id: str,
        client_message_id: str,
        methods: set[str],
    ) -> AppEventEnvelope | None:
        result = await db.execute(
            select(self.event_model)
            .where(
                self.event_model.thread_id == thread_id,
                self.event_model.client_message_id == client_message_id,
                self.event_model.method.in_(methods),
            )
            .order_by(self.event_model.seq.asc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        return self._to_envelope(row) if row is not None else None

    def _to_envelope(self, row: Any) -> AppEventEnvelope:
        return AppEventEnvelope(
            event_id=str(row.event_id),
            protocol_version=self.protocol_version,
            seq=int(row.seq),
            thread_id=str(row.thread_id),
            method=str(row.method),
            payload=dict(row.payload_json or {}),
            created_at=row.created_at,
            turn_id=getattr(row, "turn_id", None),
            item_id=getattr(row, "item_id", None),
            parent_item_id=getattr(row, "parent_item_id", None),
            client_message_id=getattr(row, "client_message_id", None),
        )

    def _row_kwargs(self, event: AppEventInput, *, event_id: str, seq: int) -> dict[str, Any]:
        values = {
            "event_id": event_id,
            "thread_id": event.thread_id,
            "seq": seq,
            "turn_id": event.turn_id,
            "item_id": event.item_id,
            "parent_item_id": event.parent_item_id,
            "client_message_id": event.client_message_id,
            "method": event.method,
            "payload_json": dict(event.payload or {}),
        }
        columns = set(self.event_model.__table__.columns.keys())
        return {key: value for key, value in values.items() if key in columns}


__all__ = [
    "AppEventEnvelope",
    "AppEventInput",
    "CORE_RUN_ITEM_METHOD",
    "SqlAlchemyAppEventStore",
]
