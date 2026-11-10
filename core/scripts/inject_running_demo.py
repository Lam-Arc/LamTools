"""Inject a permanent running process-group into the Core DB for UI demo.

Creates a session whose thread contains:
  - a user message
  - a running turn (status=running)
  - two running read_file tool_call items

The UI renders the two read_file parts as a process group with the
summary "读取了2个文件…" and — because the parts stay `running` — the
running-state flowing-text animation stays active until the backend
restarts (startup recovery cancels stale running turns).

Run while the backend is running, with the same interpreter the backend
uses (py -3.14) and cwd=core:

    py -3.14 -m scripts.inject_running_demo      # or python scripts/inject_running_demo.py
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from lamtools_core.app.core_db import open_core_app_db
from lamtools_core.app.core_session_store import CoreDbSessionStore
from lamtools_core.app.event_store import AppEventInput
from lamtools_core.event.run_item import RunItemEvent
from lamtools_core.session import SessionRecord

THREAD_ID = "flow-demo"
TURN_ID = f"{THREAD_ID}:turn:demo"
DB_PATH = "data/core.db"


async def main() -> None:
    app_db = await open_core_app_db(DB_PATH)
    try:
        session_store = CoreDbSessionStore(lambda: app_db)
        existing = await session_store.get(THREAD_ID)
        if existing is None:
            await session_store.create(
                SessionRecord(
                    id=THREAD_ID,
                    member_id="core",
                    title="流光演示",
                    status="idle",
                    created_at=datetime.now(),
                    updated_at=datetime.now(),
                )
            )
            print(f"session created: {THREAD_ID}")
        else:
            print(f"session already exists: {THREAD_ID}")

        async def write(db):
            return await app_db.persistence.append_batch(
                db,
                app_events=[
                    AppEventInput(
                        thread_id=THREAD_ID,
                        method="turn/accepted",
                        turn_id=TURN_ID,
                        payload={"type": "turn", "status": "running", "input": [{"type": "text", "text": "读取两个文件看看"}]},
                    ),
                    AppEventInput(
                        thread_id=THREAD_ID,
                        method="item/started",
                        turn_id=TURN_ID,
                        item_id=f"{TURN_ID}:user",
                        payload={"type": "userMessage", "status": "completed", "content": [{"type": "text", "text": "读取两个文件看看"}]},
                    ),
                ],
                run_item_events=[
                    RunItemEvent(
                        kind="status",
                        thread_id=THREAD_ID,
                        event_id=f"{TURN_ID}:running",
                        run_id=TURN_ID,
                        turn_id=TURN_ID,
                        item_id=f"{TURN_ID}:running",
                        status="running",
                        payload={"type": "turn", "status": "running"},
                    ),
                    RunItemEvent(
                        kind="message",
                        thread_id=THREAD_ID,
                        event_id=f"{TURN_ID}:text",
                        run_id=TURN_ID,
                        turn_id=TURN_ID,
                        item_id=f"{TURN_ID}:text",
                        status="running",
                        payload={"type": "agentMessage", "delta": "正在读取项目文件…"},
                    ),
                    RunItemEvent(
                        kind="tool_call",
                        thread_id=THREAD_ID,
                        event_id=f"{TURN_ID}:call1",
                        run_id=TURN_ID,
                        turn_id=TURN_ID,
                        item_id=f"{TURN_ID}:call1:tool",
                        status="running",
                        payload={
                            "type": "dynamicToolCall",
                            "tool_name": "read_file",
                            "arguments": {"path": "E:/LamTools/core/ui/src/types.ts"},
                            "summary": "read_file",
                            "message": "读取 E:/LamTools/core/ui/src/types.ts",
                        },
                    ),
                    RunItemEvent(
                        kind="tool_call",
                        thread_id=THREAD_ID,
                        event_id=f"{TURN_ID}:call2",
                        run_id=TURN_ID,
                        turn_id=TURN_ID,
                        item_id=f"{TURN_ID}:call2:tool",
                        status="running",
                        payload={
                            "type": "dynamicToolCall",
                            "tool_name": "read_file",
                            "arguments": {"path": "E:/LamTools/core/ui/src/store.ts"},
                            "summary": "read_file",
                            "message": "读取 E:/LamTools/core/ui/src/store.ts",
                        },
                    ),
                ],
            )

        envelopes = await app_db.persistence.write(write)
        print(f"appended {len(envelopes)} events (seq 1..{len(envelopes)})")

        async with app_db.session_factory() as db:
            snapshot = await app_db.persistence.load(db, THREAD_ID)
        core = snapshot.get("core") or {}
        items = core.get("items") or {}
        turns = core.get("turns") or {}
        print(f"turn status: {turns.get(TURN_ID, {}).get('status')}")
        print(f"items: {[(i, v.get('kind'), v.get('status')) for i, v in list(items.items())[:6]]}")
    finally:
        await app_db.close()


if __name__ == "__main__":
    asyncio.run(main())
