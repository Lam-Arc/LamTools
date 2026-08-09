"""One-time migration: split snapshot JSON items into per-item rows.

The snapshot store now persists items in ``core_thread_snapshot_items`` (one
row per item, incremental writes) instead of inside
``core_thread_snapshots.snapshot_json``. This script migrates existing rows:
for each thread it extracts ``core.items`` into item rows (using the item's
``seq`` anchor, backfilling from the event table when missing) and strips
``core.items`` from the metadata JSON. Backs up the db first and verifies the
migration (row counts, item totals).
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import sys
import time
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "core.db"
BACKUP = DB.with_name("core.db.bak-before-item-rows")


def first_seqs_for_thread(conn: sqlite3.Connection, thread_id: str) -> dict[str, int]:
    first: dict[str, int] = {}
    rows = conn.execute(
        "SELECT payload_json, seq FROM core_app_events WHERE thread_id = ? ORDER BY seq ASC",
        (thread_id,),
    )
    for payload_json, seq in rows:
        try:
            payload = json.loads(payload_json)
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        item_id = payload.get("item_id")
        if item_id and item_id not in first:
            first[item_id] = int(seq or 0)
    return first


def migrate_thread(conn: sqlite3.Connection, thread_id: str) -> tuple[int, int, int]:
    """Return (items_migrated, seq_backfilled, metadata_updated)."""
    row = conn.execute(
        "SELECT snapshot_json FROM core_thread_snapshots WHERE thread_id = ?",
        (thread_id,),
    ).fetchone()
    if not row:
        return 0, 0, 0
    try:
        state = json.loads(row[0])
    except (TypeError, json.JSONDecodeError):
        return 0, 0, 0
    if not isinstance(state, dict):
        return 0, 0, 0
    core = state.get("core")
    if not isinstance(core, dict) or not isinstance(core.get("items"), dict):
        return 0, 0, 0
    items = core["items"]
    if not items:
        return 0, 0, 0
    first = first_seqs_for_thread(conn, thread_id)
    backfilled = 0
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    for item_id, item in items.items():
        if not isinstance(item, dict):
            continue
        seq = int(item.get("seq") or 0)
        if not seq and first.get(item_id):
            seq = int(first[item_id])
            item["seq"] = seq
            backfilled += 1
        conn.execute(
            "INSERT OR REPLACE INTO core_thread_snapshot_items"
            " (thread_id, item_id, seq, item_json, updated_at) VALUES (?, ?, ?, ?, ?)",
            (thread_id, item_id, seq, json.dumps(item, ensure_ascii=False), now),
        )
    core["items"] = {}
    conn.execute(
        "UPDATE core_thread_snapshots SET snapshot_json = ?, updated_at = ? WHERE thread_id = ?",
        (json.dumps(state, ensure_ascii=False), now, thread_id),
    )
    return len(items), backfilled, 1


def main() -> int:
    if not DB.exists():
        print(f"db not found: {DB}")
        return 1
    shutil.copy2(DB, BACKUP)
    print(f"backup -> {BACKUP}")

    conn = sqlite3.connect(DB)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS core_thread_snapshot_items ("
            "thread_id VARCHAR(64) NOT NULL,"
            "item_id VARCHAR(128) NOT NULL,"
            "seq INTEGER NOT NULL DEFAULT 0,"
            "item_json TEXT NOT NULL,"
            "updated_at DATETIME NOT NULL,"
            "PRIMARY KEY (thread_id, item_id)"
            ")"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_core_snapshot_items_thread_seq"
            " ON core_thread_snapshot_items (thread_id, seq)"
        )
        threads = conn.execute("SELECT thread_id FROM core_thread_snapshots").fetchall()
        print(f"threads to migrate: {len(threads)}")
        total_items = total_backfilled = migrated = 0
        started = time.time()
        for index, (thread_id,) in enumerate(threads, 1):
            items, backfilled, updated = migrate_thread(conn, thread_id)
            total_items += items
            total_backfilled += backfilled
            migrated += updated
            if index % 20 == 0:
                print(f"  {index}/{len(threads)} threads ({time.time() - started:.0f}s)")
        conn.commit()
        # Verify
        item_rows = conn.execute("SELECT COUNT(*) FROM core_thread_snapshot_items").fetchone()[0]
        print(
            f"done: {migrated} threads, {total_items} items migrated "
            f"({total_backfilled} seq backfilled), item rows now: {item_rows} "
            f"in {time.time() - started:.0f}s"
        )
        if item_rows != total_items:
            print(f"WARNING: item row count {item_rows} != migrated items {total_items}")
            return 2
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
