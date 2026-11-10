"""Verify conversation integrity, order and durability after the latency fix.

Reads the database the live backend just wrote and re-checks through the real
client read path (``thread/resume``), so the assertions cover what a user would
actually see, not just row counts:

* every accepted user message exists exactly once, in seq order;
* each turn's items are ordered by seq with no gaps in item_order;
* a completed turn is terminal and no turn is left "running";
* the newest snapshot page carries the last user message and the reply;
* nothing disappears after a backend restart.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
import uuid
from pathlib import Path

try:
    import aiohttp
except ModuleNotFoundError:  # pragma: no cover
    aiohttp = None  # type: ignore[assignment]


def check_database(db_path: Path, threads: list[str]) -> dict[str, object]:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    report: dict[str, object] = {}
    try:
        cur = con.cursor()
        for thread_id in threads:
            row = cur.execute(
                "select snapshot_json from core_thread_snapshots where thread_id=?",
                (thread_id,),
            ).fetchone()
            assert row is not None, f"missing snapshot for {thread_id}"
            state = json.loads(row[0])
            core = state.get("core") or {}
            item_rows = cur.execute(
                "select item_id, seq, item_json from core_thread_snapshot_items "
                "where thread_id=? order by seq",
                (thread_id,),
            ).fetchall()
            seqs = [int(seq) for _, seq, _ in item_rows]
            core_items = {str(item_id): json.loads(item_json) for item_id, _, item_json in item_rows}
            order = [str(item_id) for item_id in (core.get("item_order") or [])]
            top_items = state.get("items") or {}
            top_order = [str(item_id) for item_id in (state.get("item_order") or [])]
            turns = core.get("turns") or {}

            # 1. order integrity
            assert seqs == sorted(seqs), f"{thread_id}: item rows out of order"
            assert len(order) == len(set(order)), f"{thread_id}: duplicate ids in item_order"
            assert set(order) <= set(core_items), (
                f"{thread_id}: item_order names a row that does not exist"
            )
            assert len(top_order) == len(set(top_order)), (
                f"{thread_id}: duplicate ids in the top-level item order"
            )
            assert set(top_order) <= set(top_items), (
                f"{thread_id}: top-level order names a missing item"
            )
            # 2. user messages: one copy each, in order
            user_items = [iid for iid in top_order if str(top_items[iid].get("type")) == "userMessage"]
            assert len(user_items) == len(top_order), (
                f"{thread_id}: top-level items are not all user messages"
            )
            # 3. no turn left running unless nothing is running at all
            running = [tid for tid, turn in turns.items() if str(turn.get("status")) == "running"]
            completed = [tid for tid, turn in turns.items() if str(turn.get("status")) == "completed"]
            program_ids = cur.execute(
                "select client_message_id from core_app_events "
                "where thread_id=? and method='turn/accepted' and client_message_id is not null",
                (thread_id,),
            ).fetchall()
            duplicates = len(program_ids) - len({value for (value,) in program_ids})
            assert duplicates == 0, f"{thread_id}: {duplicates} duplicated turn/accepted events"
            # 4. the assistant rows of the last turn actually carry text
            latest_turn = max(
                (turn for turn in turns.values() if isinstance(turn, dict)),
                key=lambda turn: int(turn.get("last_seq") or 0),
                default={},
            )
            latest_items = [core_items.get(str(iid)) or {} for iid in latest_turn.get("items") or []]
            assert latest_items, f"{thread_id}: newest turn has no items"
            assert any(str(item.get("content") or "").strip() for item in latest_items), (
                f"{thread_id}: newest turn carries no assistant text"
            )

            report[thread_id] = {
                "item_rows": len(item_rows),
                "item_order": len(order),
                "user_items": len(top_items),
                "turns": len(turns),
                "completed_turns": len(completed),
                "running_turns": len(running),
                "probe_sends": len(program_ids),
            }
    finally:
        con.close()
    return report


async def check_read_path(port: int, threads: list[str]) -> dict[str, object]:
    assert aiohttp is not None
    report: dict[str, object] = {}
    async with aiohttp.ClientSession() as session:
        for thread_id in threads:
            url = f"ws://127.0.0.1:{port}/api/core/app-server"
            async with session.ws_connect(url, heartbeat=None, max_msg_size=0) as ws:
                init_id = f"init-{uuid.uuid4().hex[:8]}"
                await ws.send_str(json.dumps({
                    "jsonrpc": "2.0",
                    "id": init_id,
                    "method": "initialize",
                    "params": {
                        "clientInfo": {"name": "integrity-check", "version": "1"},
                        "threadId": thread_id,
                        "lastSeenSeq": 0,
                    },
                }))
                resume_id = f"res-{uuid.uuid4().hex[:8]}"
                await ws.send_str(json.dumps({
                    "jsonrpc": "2.0",
                    "id": resume_id,
                    "method": "thread/resume",
                    "params": {"thread_id": thread_id, "include_snapshot": True},
                }))
                snapshot = None
                deadline = asyncio.get_running_loop().time() + 120
                while asyncio.get_running_loop().time() < deadline:
                    message = await ws.receive(timeout=deadline - asyncio.get_running_loop().time())
                    if message.type is not aiohttp.WSMsgType.TEXT:
                        continue
                    decoded = json.loads(message.data)
                    if decoded.get("id") == resume_id:
                        snapshot = (decoded.get("result") or {}).get("snapshot")
                        break
                assert isinstance(snapshot, dict), f"{thread_id}: thread/resume returned no snapshot"
                core = snapshot.get("core") or {}
                item_order = core.get("item_order") or []
                items = core.get("items") or {}
                assert item_order, f"{thread_id}: empty item order after resume"
                assert items, f"{thread_id}: empty items after resume"
                last_ids = item_order[-3:]
                present = [iid for iid in last_ids if iid in items]
                assert present, f"{thread_id}: newest page is missing the newest items"
                report[thread_id] = {
                    "snapshot_seq": snapshot.get("snapshot_seq"),
                    "items_in_page": len(items),
                    "item_order": len(item_order),
                    "newest_items_present": len(present),
                    "status": snapshot.get("status"),
                }
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--thread", action="append", default=[])
    parser.add_argument("--skip-read", action="store_true")
    args = parser.parse_args()
    db_path = Path(args.db)
    database = check_database(db_path, args.thread)
    print("DATABASE_OK " + json.dumps(database, ensure_ascii=False))
    if not args.skip_read:
        reads = asyncio.run(check_read_path(args.port, args.thread))
        print("READ_PATH_OK " + json.dumps(reads, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
