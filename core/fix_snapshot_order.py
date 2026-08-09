"""One-time data fix: reorder snapshot items by first-event seq.

Deferred streaming part events (thinking/message) were projected at the turn
boundary *after* tool results projected at runtime, so core.item_order listed
all tool calls before the thinking/message they belong to. This script rebuilds
each thread's item order from the event table (append order == production
order), records each item's first-event seq as its ordering anchor (the reducer
now does this at creation time), and rewrites the snapshot JSON with native
sqlite3 (bypassing SQLAlchemy JSON dirty-detection, same as fix_snapshots.py).

Backs up the db first.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import sys
import time
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "core.db"
BACKUP = DB.with_name("core.db.bak-before-order")


def first_seqs_for_thread(conn: sqlite3.Connection, thread_id: str) -> dict[str, int]:
    """item_id -> first event seq (event-table append order == production order)."""
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


def reorder_core(core: dict, first: dict[str, int]) -> bool:
    order = core.get("item_order")
    items = core.get("items")
    if not isinstance(order, list) or not isinstance(items, dict):
        return False
    unknown = float("inf")
    sorted_order = sorted(
        enumerate(order),
        key=lambda pair: (first.get(pair[1], unknown), pair[0]),
    )
    new_order = [item_id for _, item_id in sorted_order]
    # Record each item's first-event seq as its ordering anchor (matches the
    # reducer's creation-time behavior) and keep items key order aligned.
    changed = new_order != order
    for item_id, item in items.items():
        seq = first.get(item_id)
        if seq is None:
            continue
        if not isinstance(item, dict):
            continue
        if item.get("seq") != seq:
            item["seq"] = seq
            changed = True
    if changed:
        core["item_order"] = new_order
        core["items"] = {item_id: items[item_id] for item_id in new_order if item_id in items}
    return changed


def main() -> int:
    if not DB.exists():
        print(f"db not found: {DB}")
        return 1
    shutil.copy2(DB, BACKUP)
    print(f"backup -> {BACKUP}")

    conn = sqlite3.connect(DB)
    try:
        threads = conn.execute("SELECT thread_id FROM core_thread_snapshots").fetchall()
        print(f"threads to fix: {len(threads)}")
        fixed = 0
        started = time.time()
        for index, (thread_id,) in enumerate(threads, 1):
            row = conn.execute(
                "SELECT snapshot_json FROM core_thread_snapshots WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()
            if not row:
                continue
            try:
                state = json.loads(row[0])
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(state, dict):
                continue
            core = state.get("core")
            if not isinstance(core, dict):
                continue
            first = first_seqs_for_thread(conn, thread_id)
            if reorder_core(core, first):
                conn.execute(
                    "UPDATE core_thread_snapshots SET snapshot_json = ?, updated_at = ? WHERE thread_id = ?",
                    (json.dumps(state, ensure_ascii=False), time.strftime("%Y-%m-%d %H:%M:%S"), thread_id),
                )
                fixed += 1
            if index % 20 == 0:
                elapsed = time.time() - started
                print(f"  {index}/{len(threads)} threads, {fixed} reordered ({elapsed:.0f}s)")
        conn.commit()
        print(f"done: {fixed}/{len(threads)} threads reordered in {time.time() - started:.0f}s")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
