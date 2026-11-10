"""Seed one very long thread for the message-paging benchmark.

Reuses the send-latency item shapes so the rows the benchmark reads are exactly
what production writes: one item row per runtime item, the metadata row from the
real projection, the journal from ``append_batch``.

Turns are written in batches. A per-turn append rewrites the whole metadata row
(``core.turns`` + ``core.item_order``) on every turn, which is quadratic in the
thread length and made a 12k-turn seed take hours; batching keeps the same rows
in the same order while amortizing that write. It also mirrors production,
where one ``append_batch`` carries a burst of runtime events.

Usage:
    python core/scripts/message_paging/seed_long.py \
        --home E:/LamTools/tmp/perf-message-paging --turns 12000
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

CORE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(CORE_ROOT / "src"))
sys.path.insert(0, str(CORE_ROOT / "scripts" / "send_latency"))

from lamtools_core.app.core_db import open_core_app_db  # noqa: E402
from lamtools_core.app.event_store import AppEventInput  # noqa: E402
from lamtools_core.app.turn_acceptance import build_turn_acceptance_plan  # noqa: E402
from lamtools_core.event import RunItemEvent  # noqa: E402
from seed_threads import _turn_items  # noqa: E402
from sqlalchemy.orm.attributes import flag_modified  # noqa: E402

DEFAULT_TURNS = 12_000
THREAD_ID = "perf-long"


async def seed(
    db_path: Path,
    thread_id: str,
    turns: int,
    *,
    title: str,
    work_root: str,
    batch: int = 25,
) -> dict[str, int]:
    db = await open_core_app_db(db_path)
    project = str(Path(work_root).resolve())

    async def append(app_events, run_items):
        async def write(session):
            return await db.persistence.append_batch(
                session, app_events=app_events, run_item_events=run_items
            )

        return await db.persistence.write(write)

    await append(
        [AppEventInput(
            thread_id=thread_id,
            method="thread/started",
            payload={"status": "idle", "member_id": "default", "title": title},
        )],
        [],
    )

    app_events: list[AppEventInput] = []
    run_items: list[RunItemEvent] = []
    started = time.perf_counter()
    for index in range(turns):
        turn_id = f"{thread_id}:turn:{index:06d}"
        user_item_id = f"{turn_id}:user"
        input_items = [{
            "type": "text",
            "text": f"第 {index} 条用户消息：帮我看一下这个模块的发送链路。",
        }]
        if index % 11 == 0:
            input_items.append({
                "type": "attachment",
                "attachment_id": f"att_{index:04d}",
                "name": f"screenshot-{index}.png",
                "mime_type": "image/png",
                "size_bytes": 184_320,
            })
        plan = build_turn_acceptance_plan(
            thread_id=thread_id,
            turn_id=turn_id,
            user_item_id=user_item_id,
            client_message_id=f"seed-{turn_id}",
            input_items=input_items,
            work_root=project,
            turn_payload_extra={
                "runtime_snapshot": {
                    "permission_preset": "ask",
                    "model_id": "stub-chat",
                },
                "duration_ms": 1_500 + index,
            },
            include_turn_status=True,
        )
        app_events.append(AppEventInput(
            thread_id=thread_id,
            method=plan.turn_accepted.method,
            payload=plan.turn_accepted.payload,
            turn_id=turn_id,
            client_message_id=plan.turn_accepted.client_message_id,
        ))
        app_events.append(AppEventInput(
            thread_id=thread_id,
            method=plan.user_item.method,
            payload=plan.user_item.payload,
            turn_id=turn_id,
            item_id=user_item_id,
            client_message_id=plan.user_item.client_message_id,
        ))
        run_items.extend(_turn_items(thread_id, turn_id, index))
        run_items.append(RunItemEvent(
            kind="status",
            thread_id=thread_id,
            event_id=f"{turn_id}:terminal",
            run_id=turn_id,
            turn_id=turn_id,
            item_id=f"{turn_id}:terminal",
            status="completed",
            payload={"type": "turn", "status": "completed", "duration_ms": 1_500 + index},
        ))
        if (index + 1) % batch == 0 or index == turns - 1:
            await append(app_events, run_items)
            app_events, run_items = [], []
            if (index + 1) % (batch * 20) == 0:
                print(
                    f"[seed] {index + 1}/{turns} turns "
                    f"({time.perf_counter() - started:.0f}s)",
                    flush=True,
                )

    # The session record the runtime reads is derived from the snapshot row's
    # session block, so the project root has to live there too: the runtime
    # refuses a turn whose session project is missing or non-canonical.
    async def stamp_project(session):
        row = await session.get(db.snapshot_store.snapshot_model, thread_id)
        state = dict(row.snapshot_json or {})
        block = dict(state.get("session") or {})
        block["member_id"] = block.get("member_id") or "core"
        block["title"] = block.get("title") or title
        block["metadata"] = {
            **dict(block.get("metadata") or {}),
            "work_root": project,
            "execution_directory": project,
        }
        state["session"] = block
        row.snapshot_json = state
        flag_modified(row, "snapshot_json")
        await session.flush()
        return state

    await db.persistence.write(stamp_project)

    rows = {}

    async def count(session):
        from sqlalchemy import func, select

        items = await session.execute(
            select(func.count()).select_from(db.snapshot_store.item_model)
        )
        rows["items"] = int(items.scalar_one() or 0)
        return rows

    await db.persistence.write(count)
    async with db.session_factory() as session:
        await session.rollback()
    await db.close()
    return {"turns": turns, "items": rows.get("items", 0)}


async def _run(args: argparse.Namespace) -> int:
    home = Path(args.home)
    home.mkdir(parents=True, exist_ok=True)
    db_path = home / "core.db"
    started = time.perf_counter()
    result = await seed(
        db_path,
        THREAD_ID,
        args.turns,
        title="消息分页压测会话",
        work_root=args.work_root,
        batch=args.batch,
    )
    result["seconds"] = round(time.perf_counter() - started, 1)
    result["db"] = str(db_path)
    print("SEED_JSON " + json.dumps(result, ensure_ascii=False), flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", default="E:/LamTools/tmp/perf-message-paging")
    parser.add_argument("--turns", type=int, default=DEFAULT_TURNS)
    parser.add_argument("--batch", type=int, default=25)
    parser.add_argument("--work-root", default=str(CORE_ROOT.parent))
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
