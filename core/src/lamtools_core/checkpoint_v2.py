"""Safe, resumable migration helpers for legacy checkpoint rows.

This module intentionally does not delete or rewrite ``conversation_json``.
It can be run repeatedly and is suitable for a separately scheduled migration
job after the V2 restore path has been validated.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from .app.core_db import (
    CoreAppEvent,
    CoreCheckpoint,
    CoreCheckpointV2,
    CoreCheckpointV2Materialized,
    CoreHistoryEntry,
)
from .app.sqlite_write import SQLiteWriteCoordinator


@dataclass(frozen=True)
class CheckpointMigrationReport:
    scanned: int
    migrated: int
    skipped: int
    repaired: int = 0
    materialized: int = 0


async def load_checkpoint_v2(session_factory: async_sessionmaker, checkpoint_id: str) -> dict[str, Any]:
    """Materialize the facts addressed by a V2 checkpoint for restore/import."""
    async with session_factory() as db:
        checkpoint = await db.get(CoreCheckpointV2, checkpoint_id)
        if checkpoint is None or checkpoint.status != "ready":
            raise LookupError("Checkpoint V2 not found")
        events = list((await db.execute(
            select(CoreAppEvent).where(
                CoreAppEvent.thread_id == checkpoint.session_id,
                CoreAppEvent.seq <= checkpoint.event_seq,
            ).order_by(CoreAppEvent.seq.asc())
        )).scalars())
        history = list((await db.execute(
            select(CoreHistoryEntry).where(
                CoreHistoryEntry.thread_id == checkpoint.session_id,
                CoreHistoryEntry.seq <= checkpoint.history_seq,
            ).order_by(CoreHistoryEntry.seq.asc())
        )).scalars())
    return {
        "checkpoint": {
            "id": checkpoint.id,
            "session_id": checkpoint.session_id,
            "root_session_id": checkpoint.root_session_id,
            "parent_checkpoint_id": checkpoint.parent_checkpoint_id,
            "event_seq": checkpoint.event_seq,
            "history_seq": checkpoint.history_seq,
            "runtime_state": dict(checkpoint.runtime_state_json or {}),
            "workspace_manifest_id": checkpoint.workspace_manifest_id,
        },
        "events": [_row_dict(row) for row in events],
        "history": [dict(row.message_json or {}) for row in history],
    }


async def migrate_legacy_checkpoints(
    session_factory: async_sessionmaker,
    *,
    write_coordinator: SQLiteWriteCoordinator | None = None,
    batch_size: int = 100,
) -> CheckpointMigrationReport:
    """Populate V2 metadata in small idempotent batches.

    Sequence watermarks are read from the fact tables, never inferred from or
    copied out of the legacy conversation blob.  Existing V2 rows are left
    untouched so the operation is restart-safe.
    """
    coordinator = write_coordinator or SQLiteWriteCoordinator(session_factory)
    async with session_factory() as db:
        legacy_ids = [
            str(value) for (value,) in (await db.execute(
                select(CoreCheckpoint.id).order_by(CoreCheckpoint.created_at.asc(), CoreCheckpoint.id.asc())
            )).all()
        ]
    migrated = skipped = repaired = materialized = 0
    for offset in range(0, len(legacy_ids), max(1, batch_size)):
        batch_ids = legacy_ids[offset : offset + max(1, batch_size)]

        async def write(db: Any) -> None:
            nonlocal migrated, skipped, repaired, materialized
            for checkpoint_id in batch_ids:
                # Load one legacy JSON payload at a time.  A batch must never
                # materialize the 1+ GiB checkpoint column in one process.
                old = await db.get(CoreCheckpoint, checkpoint_id)
                if old is None:
                    continue
                payload = old.conversation_json if isinstance(old.conversation_json, dict) else {}
                event_seq, history_seq = legacy_watermarks(payload)
                legacy_runtime = payload.get("runtime")
                legacy_runtime = legacy_runtime if isinstance(legacy_runtime, dict) else {}
                expected_runtime = dict(legacy_runtime.get("runtime_state_json") or {})
                existing = await db.get(CoreCheckpointV2, old.id)
                if existing is not None:
                    changed = (
                        existing.event_seq != event_seq
                        or existing.history_seq != history_seq
                        or dict(existing.runtime_state_json or {}) != expected_runtime
                    )
                    if changed:
                        existing.event_seq = event_seq
                        existing.history_seq = history_seq
                        existing.runtime_state_json = expected_runtime
                        existing.metadata_json = {"legacy_checkpoint_id": old.id, "migrated": True}
                        repaired += 1
                    else:
                        skipped += 1
                else:
                    db.add(CoreCheckpointV2(
                        id=old.id,
                        root_session_id=old.root_session_id,
                        session_id=old.session_id,
                        parent_checkpoint_id=old.parent_checkpoint_id,
                        turn_id=old.turn_id,
                        actor_kind=old.actor_kind,
                        reason=old.reason,
                        status=old.status,
                        event_seq=event_seq,
                        history_seq=history_seq,
                        runtime_state_json=expected_runtime,
                        workspace_manifest_id=old.manifest_hash,
                        metadata_json={"legacy_checkpoint_id": old.id, "migrated": True},
                        created_at=old.created_at,
                    ))
                    migrated += 1

                # Preserve the exact branch only where the mutable fact table
                # cannot provide it.  Projection and history are retained as
                # explicit base material for every legacy checkpoint because
                # they include state that older projectors did not emit as
                # replayable events.
                legacy_runtime_raw = payload.get("runtime")
                runtime_present = isinstance(legacy_runtime_raw, dict)
                history_json = (
                    list(legacy_runtime_raw.get("history_json") or [])
                    if runtime_present and isinstance(legacy_runtime_raw.get("history_json"), list)
                    else []
                )
                projection_present = "projection" in payload
                projection_json = payload.get("projection") if isinstance(payload.get("projection"), dict) else None
                legacy_events = payload.get("events")
                events_present = isinstance(legacy_events, list)
                events_json = None
                if events_present and not await _events_match(db, old.session_id, legacy_events):
                    events_json = list(legacy_events)

                material = await db.get(CoreCheckpointV2Materialized, old.id)
                material_values = {
                    "runtime_present": runtime_present,
                    "runtime_json": dict(legacy_runtime_raw) if runtime_present else None,
                    "history_json": history_json,
                    "projection_present": projection_present,
                    "projection_json": projection_json,
                    "events_present": events_present,
                    "events_json": events_json,
                    "created_at": old.created_at,
                }
                if material is None:
                    db.add(CoreCheckpointV2Materialized(checkpoint_id=old.id, **material_values))
                    materialized += 1
                elif any(getattr(material, key) != value for key, value in material_values.items()):
                    for key, value in material_values.items():
                        setattr(material, key, value)
                    repaired += 1

        await coordinator.run(write)
    return CheckpointMigrationReport(len(legacy_ids), migrated, skipped, repaired, materialized)


async def _events_match(db: Any, session_id: str, legacy_events: list[Any]) -> bool:
    """Check whether the current fact log is the same branch as a legacy list."""
    statement = select(CoreAppEvent).where(CoreAppEvent.thread_id == session_id)
    if legacy_events:
        max_seq = max((_positive_int(item.get("seq")) for item in legacy_events if isinstance(item, dict)), default=0)
        if max_seq <= 0:
            return False
        statement = statement.where(CoreAppEvent.seq <= max_seq).order_by(CoreAppEvent.seq.asc())
    else:
        statement = statement.order_by(CoreAppEvent.seq.asc())
    rows = list((await db.execute(statement)).scalars())
    if len(rows) != len(legacy_events):
        return False
    return all(_event_signature(row) == _legacy_event_signature(item) for row, item in zip(rows, legacy_events))


def _event_signature(row: CoreAppEvent) -> tuple[Any, ...]:
    return (
        str(row.event_id),
        int(row.seq or 0),
        str(row.turn_id or ""),
        str(row.item_id or ""),
        str(row.parent_item_id or ""),
        str(row.client_message_id or ""),
        str(row.method),
        dict(row.payload_json or {}),
    )


def _legacy_event_signature(value: Any) -> tuple[Any, ...]:
    if not isinstance(value, dict):
        return ("", 0, "", "", "", "", "", {})
    return (
        str(value.get("event_id") or ""),
        _positive_int(value.get("seq")),
        str(value.get("turn_id") or ""),
        str(value.get("item_id") or ""),
        str(value.get("parent_item_id") or ""),
        str(value.get("client_message_id") or ""),
        str(value.get("method") or ""),
        dict(value.get("payload") or {}),
    )


def legacy_watermarks(conversation: Any) -> tuple[int, int]:
    """Extract checkpoint-local watermarks from the legacy payload."""
    if not isinstance(conversation, dict):
        return 0, 0
    runtime = conversation.get("runtime") if isinstance(conversation.get("runtime"), dict) else {}
    projection = conversation.get("projection") if isinstance(conversation.get("projection"), dict) else {}
    event_seq = _positive_int(runtime.get("last_event_seq"))
    events = conversation.get("events")
    if isinstance(events, list):
        event_seq = max(
            [_positive_int(item.get("seq")) for item in events if isinstance(item, dict)] + [event_seq]
        )
    history = runtime.get("history_json")
    history_seq = 0
    if isinstance(history, list):
        markers = [
            item.get("metadata", {}).get("history_seq")
            for item in history
            if isinstance(item, dict) and isinstance(item.get("metadata"), dict)
        ]
        history_seq = max([_positive_int(item) for item in markers] + [len(history)])
    if not event_seq:
        event_seq = _positive_int(projection.get("snapshot_seq"))
    return event_seq, history_seq


def _positive_int(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


def _row_dict(row: Any) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


__all__ = ["CheckpointMigrationReport", "legacy_watermarks", "load_checkpoint_v2", "migrate_legacy_checkpoints"]
