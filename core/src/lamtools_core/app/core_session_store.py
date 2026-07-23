"""Session resource adapter backed by the Core thread snapshot directory."""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from sqlalchemy import delete, select

from lamtools_core.session import MessageRecord, SessionRecord

from .core_db import CoreAppDb, CoreAppEvent, CoreRuntimeSession, CoreThreadSnapshot
from .snapshot_store import CoreAppSnapshotProjector


class CoreDbSessionStore:
    def __init__(self, db_provider: Callable[[], CoreAppDb]) -> None:
        self._db_provider = db_provider

    async def create(self, session: SessionRecord) -> SessionRecord:
        db = self._db_provider()

        async def write(connection):
            if await connection.get(CoreThreadSnapshot, session.id) is not None:
                raise ValueError(f"Session '{session.id}' already exists")
            state = session_snapshot(session, projector=db.snapshot_store.projector)
            connection.add(
                CoreThreadSnapshot(
                    thread_id=session.id,
                    snapshot_seq=0,
                    snapshot_json=state,
                    updated_at=session.updated_at,
                )
            )
            await connection.flush()

        await db.persistence.write(write)
        return session

    async def get(self, session_id: str) -> SessionRecord | None:
        db = self._db_provider()
        async with db.session_factory() as connection:
            row = await connection.get(CoreThreadSnapshot, session_id)
            return session_record_from_snapshot(row) if row is not None else None

    async def list(self, member_id: str | None = None) -> list[SessionRecord]:
        db = self._db_provider()
        async with db.session_factory() as connection:
            rows = (
                await connection.execute(
                    select(CoreThreadSnapshot).order_by(CoreThreadSnapshot.updated_at.desc())
                )
            ).scalars().all()
        records = [session_record_from_snapshot(row) for row in rows]
        return [record for record in records if member_id is None or record.member_id == member_id]

    async def update(self, session: SessionRecord) -> SessionRecord:
        db = self._db_provider()
        session.updated_at = datetime.now()

        async def write(connection):
            row = await connection.get(CoreThreadSnapshot, session.id)
            if row is None:
                raise KeyError(session.id)
            existing = session_record_from_snapshot(row)
            session.metadata = _canonicalize_project_metadata(existing.metadata, session.metadata)
            state = dict(row.snapshot_json or {})
            state.update(_session_state(session, messages=state.get("messages")))
            row.snapshot_json = state
            row.updated_at = session.updated_at
            await connection.flush()

        await db.persistence.write(write)
        return session

    async def patch(
        self,
        session_id: str,
        *,
        title: str | None = None,
        status: str | None = None,
        metadata: dict | None = None,
    ) -> SessionRecord | None:
        db = self._db_provider()

        async def write(connection):
            row = await connection.get(CoreThreadSnapshot, session_id)
            if row is None:
                return None
            record = session_record_from_snapshot(row)
            if title is not None:
                record.title = title
            if status is not None:
                record.status = status
            if metadata is not None:
                record.metadata = _canonicalize_project_metadata(record.metadata, metadata)
            record.updated_at = datetime.now()
            state = dict(row.snapshot_json or {})
            state.update(_session_state(record, messages=state.get("messages")))
            row.snapshot_json = state
            row.updated_at = record.updated_at
            await connection.flush()
            return record

        return await db.persistence.write(write)

    async def delete(self, session_id: str) -> bool:
        db = self._db_provider()

        async def write(connection):
            row = await connection.get(CoreThreadSnapshot, session_id)
            if row is None:
                return False
            await delete_session_records(connection, [session_id])
            return True

        return bool(await db.persistence.write(write))

    async def add_message(self, message: MessageRecord) -> MessageRecord:
        db = self._db_provider()

        async def write(connection):
            row = await connection.get(CoreThreadSnapshot, message.session_id)
            if row is None:
                raise KeyError(message.session_id)
            state = dict(row.snapshot_json or {})
            messages = list(state.get("messages") or [])
            messages.append(message.to_dict())
            state["messages"] = messages
            row.snapshot_json = state
            row.updated_at = datetime.now()
            await connection.flush()

        await db.persistence.write(write)
        return message

    async def list_messages(self, session_id: str) -> list[MessageRecord]:
        db = self._db_provider()
        async with db.session_factory() as connection:
            row = await connection.get(CoreThreadSnapshot, session_id)
        if row is None:
            return []
        raw_messages = (row.snapshot_json or {}).get("messages") or []
        records = [_message_from_dict(item) for item in raw_messages if isinstance(item, dict)]
        return sorted(records, key=lambda item: item.created_at)


def _session_state(session: SessionRecord, *, messages=None) -> dict:
    state = {
        "thread_id": session.id,
        "status": session.status,
        "session": {
            "member_id": session.member_id,
            "title": session.title,
            "metadata": session.metadata,
            "created_at": session.created_at.isoformat(),
        },
    }
    if messages is not None:
        state["messages"] = messages
    return state


def _canonicalize_project_metadata(existing: dict, requested: dict) -> dict:
    work_root = existing.get("work_root")
    if not isinstance(work_root, str) or not work_root:
        if "work_root" in requested:
            raise ValueError("Use the project session endpoint for project-owned sessions")
        return dict(requested)
    metadata = dict(requested)
    metadata["work_root"] = str(work_root)
    return metadata


def session_snapshot(
    session: SessionRecord,
    *,
    projector: CoreAppSnapshotProjector | None = None,
) -> dict:
    state = (projector or CoreAppSnapshotProjector()).empty(session.id)
    state.update(_session_state(session))
    return state


async def delete_session_records(connection, session_ids: list[str]) -> None:
    if not session_ids:
        return
    await connection.execute(delete(CoreAppEvent).where(CoreAppEvent.thread_id.in_(session_ids)))
    await connection.execute(delete(CoreRuntimeSession).where(CoreRuntimeSession.thread_id.in_(session_ids)))
    await connection.execute(delete(CoreThreadSnapshot).where(CoreThreadSnapshot.thread_id.in_(session_ids)))


def session_record_from_snapshot(row: CoreThreadSnapshot) -> SessionRecord:
    state = dict(row.snapshot_json or {})
    session = state.get("session") if isinstance(state.get("session"), dict) else {}
    updated_at = row.updated_at or datetime.now()
    return SessionRecord(
        id=str(row.thread_id),
        member_id=str(session.get("member_id") or "core"),
        title=str(session.get("title") or row.thread_id),
        status=str(state.get("status") or "idle"),
        metadata=dict(session.get("metadata") or {}),
        created_at=_datetime(session.get("created_at"), fallback=updated_at),
        updated_at=updated_at,
    )


def _message_from_dict(value: dict) -> MessageRecord:
    return MessageRecord(
        id=str(value.get("id") or ""),
        session_id=str(value.get("session_id") or ""),
        role=str(value.get("role") or ""),
        content=str(value.get("content") or ""),
        parts=list(value.get("parts") or []),
        metadata=dict(value.get("metadata") or {}),
        created_at=_datetime(value.get("created_at"), fallback=datetime.now()),
    )


def _datetime(value, *, fallback: datetime) -> datetime:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return fallback


__all__ = [
    "CoreDbSessionStore",
    "delete_session_records",
    "session_record_from_snapshot",
    "session_snapshot",
]
