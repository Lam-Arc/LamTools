"""Compare legacy and V2 restore results without committing either restore."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any
from types import SimpleNamespace

from sqlalchemy import select

from lamtools_core.app.core_db import (
    CoreAppEvent,
    CoreCheckpoint,
    CoreCheckpointV2,
    CoreCheckpointV2Materialized,
    CoreHistoryEntry,
    CoreRuntimeSession,
    CoreThreadSnapshotItem,
    open_core_app_db,
)
from lamtools_core.checkpoint import CoreCheckpointConversationBackend


def _clean_message(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    result = dict(value)
    metadata = result.get("metadata")
    if isinstance(metadata, dict):
        result["metadata"] = {key: item for key, item in metadata.items() if key not in {"history_seq", "lam_compaction_resume"}}
    return result


async def compare(path: Path, checkpoint_ids: list[str]) -> list[dict[str, Any]]:
    db = await open_core_app_db(path)
    results: list[dict[str, Any]] = []
    try:
        async with db.session_factory() as connection:
            for checkpoint_id in checkpoint_ids:
                legacy = await connection.get(CoreCheckpoint, checkpoint_id)
                v2 = await connection.get(CoreCheckpointV2, checkpoint_id)
                if legacy is None or v2 is None:
                    results.append({"id": checkpoint_id, "ok": False, "error": "missing legacy or v2 row"})
                    continue
                conversation = legacy.conversation_json if isinstance(legacy.conversation_json, dict) else {}
                materialized = await connection.get(CoreCheckpointV2Materialized, checkpoint_id)
                if conversation:
                    legacy_runtime = conversation.get("runtime")
                    legacy_runtime_present = isinstance(legacy_runtime, dict)
                    legacy_runtime = legacy_runtime if legacy_runtime_present else {}
                    legacy_history = legacy_runtime.get("history_json") if isinstance(legacy_runtime.get("history_json"), list) else []
                    legacy_events: list[Any] | None = conversation.get("events") if isinstance(conversation.get("events"), list) else []
                    legacy_projection = conversation.get("projection") if isinstance(conversation.get("projection"), dict) else {}
                    events_are_comparable = True
                elif materialized is not None:
                    legacy_runtime_present = bool(materialized.runtime_present)
                    legacy_runtime = dict(materialized.runtime_json or {}) if legacy_runtime_present else {}
                    legacy_history = list(materialized.history_json or [])
                    legacy_events = list(materialized.events_json) if materialized.events_json is not None else None
                    legacy_projection = dict(materialized.projection_json or {}) if materialized.projection_present else {}
                    events_are_comparable = legacy_events is not None
                else:
                    results.append({"id": checkpoint_id, "ok": False, "error": "missing V2 materialized recovery row"})
                    continue
                legacy_snapshot = legacy_projection.get("snapshot_json") if isinstance(legacy_projection.get("snapshot_json"), dict) else {}
                legacy_core = legacy_snapshot.get("core") if isinstance(legacy_snapshot.get("core"), dict) else legacy_snapshot
                legacy_items = legacy_core.get("items") if isinstance(legacy_core.get("items"), dict) else {}
                session_id = legacy.session_id
                checkpoint_data = SimpleNamespace(
                    id=v2.id,
                    session_id=v2.session_id,
                    event_seq=v2.event_seq,
                    history_seq=v2.history_seq,
                    runtime_state_json=dict(v2.runtime_state_json or {}),
                )
                event_seq_v2 = int(v2.event_seq)
                history_seq_v2 = int(v2.history_seq)
                await connection.rollback()
                transaction = await connection.begin()
                try:
                    await CoreCheckpointConversationBackend(db.session_factory).restore_v2(connection, session_id, checkpoint_data)
                    # ``restore_v2`` is normally followed by a coordinator
                    # commit.  Flush here too so deleted runtime rows are not
                    # returned from this session's identity map as if they
                    # were still persisted.
                    await connection.flush()
                    runtime = await connection.get(CoreRuntimeSession, session_id)
                    history_rows = list((await connection.execute(
                        select(CoreHistoryEntry).where(CoreHistoryEntry.thread_id == session_id).order_by(CoreHistoryEntry.seq.asc())
                    )).scalars())
                    event_rows = list((await connection.execute(
                        select(CoreAppEvent).where(CoreAppEvent.thread_id == session_id).order_by(CoreAppEvent.seq.asc())
                    )).scalars())
                    item_count = len((await connection.execute(
                        select(CoreThreadSnapshotItem.item_id).where(CoreThreadSnapshotItem.thread_id == session_id)
                    )).all())
                    actual_history = [_clean_message(row.message_json) for row in history_rows]
                    expected_history = [_clean_message(item) for item in legacy_history if isinstance(item, dict)]
                    expected_event_ids = (
                        [str(item.get("event_id") or "") for item in legacy_events if isinstance(item, dict)]
                        if events_are_comparable and legacy_events is not None
                        else None
                    )
                    actual_event_ids = [str(row.event_id) for row in event_rows]
                    runtime_matches = (
                        runtime is not None
                        and dict(runtime.runtime_state_json or {}) == dict(legacy_runtime.get("runtime_state_json") or {})
                        if legacy_runtime_present
                        else runtime is None
                    )
                    checks = {
                        "history": actual_history == expected_history,
                        "events": actual_event_ids == expected_event_ids if expected_event_ids is not None else True,
                        "snapshot_items": item_count == len(legacy_items),
                        "runtime": runtime_matches,
                    }
                    results.append({
                        "id": checkpoint_id,
                        "session_id": session_id,
                        "event_seq": event_seq_v2,
                        "history_seq": history_seq_v2,
                        "expected_history": len(expected_history),
                        "actual_history": len(actual_history),
                        "expected_events": len(expected_event_ids) if expected_event_ids is not None else None,
                        "actual_events": len(actual_event_ids),
                        "expected_snapshot_items": len(legacy_items),
                        "actual_snapshot_items": item_count,
                        "checks": checks,
                        "ok": all(checks.values()),
                    })
                finally:
                    await transaction.rollback()
    finally:
        await db.close()
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("checkpoint", nargs="+")
    args = parser.parse_args()
    results = asyncio.run(compare(args.db, args.checkpoint))
    print(json.dumps(results, ensure_ascii=False, indent=2))
    raise SystemExit(0 if all(item.get("ok") for item in results) else 1)


if __name__ == "__main__":
    main()
