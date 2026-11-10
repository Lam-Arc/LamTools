"""Remove session-family records whose root has no persisted thread snapshot.

The cleanup is deliberately routed through ``delete_session_records`` so the
same ownership rules are used by the HTTP session-delete path.  It is safe to
re-run: after a successful run, the candidate root list is empty.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from sqlalchemy import select

from lamtools_core.app.core_db import (
    CoreAppEvent,
    CoreAttachment,
    CoreArrangeJob,
    CoreCheckpoint,
    CoreCheckpointV2,
    CoreGoal,
    CoreHistoryEntry,
    CoreRestoreOperation,
    CoreRuntimeSession,
    CoreThreadSnapshot,
    CoreThreadSnapshotItem,
    open_core_app_db,
)
from lamtools_core.app.core_session_store import delete_session_records


_SESSION_ID_COLUMNS = (
    (CoreRuntimeSession, CoreRuntimeSession.thread_id),
    (CoreAppEvent, CoreAppEvent.thread_id),
    (CoreHistoryEntry, CoreHistoryEntry.thread_id),
    (CoreThreadSnapshotItem, CoreThreadSnapshotItem.thread_id),
    (CoreThreadSnapshot, CoreThreadSnapshot.thread_id),
    (CoreAttachment, CoreAttachment.session_id),
    (CoreGoal, CoreGoal.thread_id),
    (CoreArrangeJob, CoreArrangeJob.thread_id),
    (CoreCheckpoint, CoreCheckpoint.root_session_id),
    (CoreCheckpointV2, CoreCheckpointV2.root_session_id),
    (CoreRestoreOperation, CoreRestoreOperation.root_session_id),
)


def _root_session_id(value: object) -> str:
    return str(value or "").split(":sub:", 1)[0].strip()


async def find_orphan_roots(session) -> list[str]:
    snapshot_ids = {
        str(value)
        for value in (await session.execute(select(CoreThreadSnapshot.thread_id))).scalars().all()
        if value
    }
    roots: set[str] = set()
    for model, column in _SESSION_ID_COLUMNS:
        values = (await session.execute(select(column))).scalars().all()
        roots.update(
            root
            for value in values
            if (root := _root_session_id(value)) and root not in snapshot_ids
        )
    return sorted(roots)


async def clean(path: Path, *, dry_run: bool = False) -> dict[str, object]:
    db = await open_core_app_db(path)
    try:
        async with db.session_factory() as session:
            roots = await find_orphan_roots(session)
        if roots and not dry_run:
            await db.persistence.write(
                lambda session: delete_session_records(session, roots)
            )
        async with db.session_factory() as session:
            remaining = await find_orphan_roots(session)
        return {
            "dry_run": dry_run,
            "roots": roots,
            "root_count": len(roots),
            "remaining_root_count": len(remaining) if not dry_run else len(roots),
        }
    finally:
        await db.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(clean(args.db, dry_run=args.dry_run)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
