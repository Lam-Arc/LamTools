"""One-time data fix: backfill snapshot items missing from item rows.

Old code deferred part projection and skipped the turn-boundary projection
for interrupted/steered turns, so some turns' items never reached the
snapshot (event rows exist, item rows don't — item_order still references
them and the UI silently drops the message). This script replays each
thread's full event stream through the projector and inserts the missing
item rows (plus their seq anchor), leaving existing rows untouched.

Backs up the db first.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
import sys
import time
from pathlib import Path

from sqlalchemy import delete, select

from lamtools_core.app.core_db import (
    CoreAppEvent,
    CoreThreadSnapshot,
    CoreThreadSnapshotItem,
    open_core_app_db,
)
from lamtools_core.app.event_store import SqlAlchemyAppEventStore
from lamtools_core.app.snapshot_store import CoreAppSnapshotProjector

DB = Path(__file__).resolve().parent.parent / "data" / "core.db"
BACKUP = DB.with_name("core.db.bak-before-integrity")


async def main() -> int:
    if not DB.exists():
        print(f"db not found: {DB}")
        return 1
    shutil.copy2(DB, BACKUP)
    print(f"backup -> {BACKUP}")

    db = await open_core_app_db(DB)
    projector = CoreAppSnapshotProjector()
    event_store = SqlAlchemyAppEventStore(CoreAppEvent)
    try:
        async with db.session_factory() as session:
            thread_rows = (await session.execute(select(CoreThreadSnapshot.thread_id))).scalars().all()
            print(f"threads: {len(thread_rows)}")
            total_missing = 0
            fixed_threads = 0
            started = time.time()
            for index, thread_id in enumerate(thread_rows, 1):
                thread_id = str(thread_id)
                events = await event_store.list_thread(session, thread_id=thread_id)
                if not events:
                    continue
                # Replay the full stream in memory.
                state = projector.reduce(thread_id, events)
                replayed = state.get("core") or state
                replayed_items = replayed.get("items") or {}
                if not replayed_items:
                    continue
                existing = {
                    str(row[0])
                    for row in (
                        await session.execute(
                            select(CoreThreadSnapshotItem.item_id).where(
                                CoreThreadSnapshotItem.thread_id == thread_id
                            )
                        )
                    ).all()
                }
                missing = [iid for iid in replayed_items if iid not in existing]
                if not missing:
                    continue
                now = None
                for item_id in missing:
                    item = replayed_items[item_id]
                    if now is None:
                        from datetime import datetime

                        now = datetime.now()
                    session.add(
                        CoreThreadSnapshotItem(
                            thread_id=thread_id,
                            item_id=item_id,
                            seq=int(item.get("seq") or 0) if isinstance(item, dict) else 0,
                            item_json=item,
                            updated_at=now,
                        )
                    )
                # Merge the missing ids into the metadata item_order (by seq).
                row = await session.get(CoreThreadSnapshot, thread_id)
                if row is not None and isinstance(row.snapshot_json, dict):
                    meta = dict(row.snapshot_json)
                    core = meta.get("core")
                    if isinstance(core, dict):
                        order = list(core.get("item_order") or [])
                        order_set = set(order)
                        seq_map = {
                            iid: int((replayed_items.get(iid) or {}).get("seq") or 0)
                            for iid in missing
                        }
                        for iid in missing:
                            if iid in order_set:
                                continue
                            seq = seq_map.get(iid, 0)
                            pos = next(
                                (i for i, existing_id in enumerate(order)
                                 if int((replayed_items.get(existing_id) or {}).get("seq") or 0) > seq),
                                len(order),
                            )
                            order.insert(pos, iid)
                        core["item_order"] = order
                        row.snapshot_json = meta
                total_missing += len(missing)
                fixed_threads += 1
                if index % 20 == 0:
                    print(f"  {index}/{len(thread_rows)} threads ({time.time() - started:.0f}s)")
                if index % 50 == 0:
                    await session.commit()
            await session.commit()
            print(f"done: {fixed_threads} threads, {total_missing} items backfilled in {time.time() - started:.0f}s")
    finally:
        await db.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
