"""One-off snapshot repair: replay unseen events into thread snapshots.

Run with backends stopped (tauri + 5172) to avoid concurrent writes.
Backs up the db first, then for every thread replays all events whose
event_id is not in the snapshot's seen_event_ids (in seq order) and writes
the snapshot back. Idempotent: re-running is a no-op once caught up.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import sys
from datetime import datetime

from lamtools_core.app.event_store import AppEventEnvelope
from lamtools_core.app.snapshot_store import CoreAppSnapshotProjector

DB = r"E:\LamTools\data\core.db"


def main() -> int:
    backup = DB + ".bak-before-fix"
    shutil.copy2(DB, backup)
    print(f"backup written: {backup}")

    con = sqlite3.connect(DB, timeout=60)
    con.execute("PRAGMA busy_timeout=30000")
    projector = CoreAppSnapshotProjector()
    threads = [r[0] for r in con.execute("SELECT thread_id FROM core_thread_snapshots")]
    total = 0
    for tid in threads:
        row = con.execute(
            "SELECT snapshot_seq, snapshot_json FROM core_thread_snapshots WHERE thread_id=?", (tid,)
        ).fetchone()
        if not row:
            continue
        state = json.loads(row[1])
        seen = set(state.get("seen_event_ids") or [])
        events = con.execute(
            "SELECT seq, event_id, method, turn_id, item_id, payload_json "
            "FROM core_app_events WHERE thread_id=? ORDER BY seq",
            (tid,),
        ).fetchall()
        unseen = [e for e in events if e[1] not in seen]
        if not unseen:
            continue
        envs = []
        for seq, eid, method, turn, item, payload in unseen:
            p = json.loads(payload) if isinstance(payload, str) else payload
            envs.append(
                AppEventEnvelope(
                    event_id=eid,
                    protocol_version="v1",
                    seq=seq,
                    thread_id=tid,
                    method=method,
                    payload=p,
                    created_at=datetime.now(),
                    turn_id=turn,
                    item_id=item,
                )
            )
        for env in sorted(envs, key=lambda e: e.seq):
            projector.apply_in_place(state, env)
        new_json = json.dumps(state, ensure_ascii=False)
        con.execute(
            "UPDATE core_thread_snapshots SET snapshot_json=?, snapshot_seq=?, updated_at=? WHERE thread_id=?",
            (new_json, int(state.get("snapshot_seq") or 0), datetime.now().isoformat(), tid),
        )
        total += len(envs)
        print(f"  {tid[:12]}...: replayed {len(envs)} unseen -> seq={state.get('snapshot_seq')}")
    con.commit()
    con.close()
    print(f"done, total unseen events replayed: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
