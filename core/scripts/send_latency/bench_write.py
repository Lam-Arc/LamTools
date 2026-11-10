"""Attribute the per-send persistence cost inside the real projection path.

Runs against a copy of the harness database and breaks one acceptance batch
(the same three events ``turn/start`` writes) into its production steps:

    load_metadata -> event appends -> partial assembly -> projector apply
    -> metadata row serialise/flush -> commit

Usage:
    python core/scripts/send_latency/bench_write.py --db <copy.core.db> --thread perf-long
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

CORE_SRC = Path(__file__).resolve().parents[2] / "src"
if str(CORE_SRC) not in sys.path:
    sys.path.insert(0, str(CORE_SRC))

from lamtools_core.app.core_db import open_core_app_db  # noqa: E402
from lamtools_core.app.event_store import AppEventInput  # noqa: E402
from lamtools_core.app.turn_acceptance import build_turn_acceptance_plan  # noqa: E402

STEPS = (
    "load_metadata",
    "append_events",
    "partial_state",
    "apply_many",
    "persist_only",
    "commit",
    "write_total",
)


async def bench(db_path: Path, thread_id: str, rounds: int) -> dict[str, object]:
    db = await open_core_app_db(db_path)
    store = db.snapshot_store
    timings: dict[str, list[float]] = {step: [] for step in STEPS}
    timings["snapshot_json_bytes"] = []

    for round_index in range(rounds):
        turn_id = f"{thread_id}:bench:{round_index:04d}"
        plan = build_turn_acceptance_plan(
            thread_id=thread_id,
            turn_id=turn_id,
            user_item_id=f"{turn_id}:user",
            client_message_id=f"bench-{turn_id}",
            input_items=[{"type": "text", "text": "bench send"}],
            work_root="E:\\LamTools",
        )
        started = time.perf_counter()

        async def write(session):
            local: dict[str, float] = {}
            mark = time.perf_counter()
            await db.persistence.load_metadata(session, thread_id)
            local["load_metadata"] = time.perf_counter() - mark

            mark = time.perf_counter()
            envelopes = [
                await db.event_store.append(session, AppEventInput(
                    thread_id=thread_id,
                    method=plan.turn_accepted.method,
                    payload=plan.turn_accepted.payload,
                    turn_id=turn_id,
                    client_message_id=plan.turn_accepted.client_message_id,
                )),
                await db.event_store.append(session, AppEventInput(
                    thread_id=thread_id,
                    method=plan.user_item.method,
                    payload=plan.user_item.payload,
                    turn_id=turn_id,
                    item_id=plan.user_item.item_id,
                    client_message_id=plan.user_item.client_message_id,
                )),
                await db.event_store.append_run_item_event(session, plan.running_status),
            ]
            local["append_events"] = time.perf_counter() - mark

            row = await session.get(store.snapshot_model, thread_id)
            mark = time.perf_counter()
            partial = await store._partial_state(session, row, thread_id, envelopes)
            local["partial_state"] = time.perf_counter() - mark

            mark = time.perf_counter()
            await store.apply_many(session, envelopes)
            local["apply_many"] = time.perf_counter() - mark

            mark = time.perf_counter()
            fresh = await session.get(store.snapshot_model, thread_id)
            payload = fresh.snapshot_json or {}
            local["snapshot_json_bytes"] = float(
                len(json.dumps(payload, ensure_ascii=False))
            )
            local["persist_only"] = time.perf_counter() - mark
            return local

        local = await db.persistence.write(write)
        timings["write_total"].append(time.perf_counter() - started)
        for key in ("load_metadata", "append_events", "partial_state", "apply_many",
                    "persist_only", "snapshot_json_bytes"):
            timings[key].append(local[key])

    await db.close()

    def stats(values: list[float]) -> dict[str, float]:
        ordered = sorted(values)
        if not ordered:
            return {}
        return {"p50": round(statistics.median(ordered), 4), "max": round(ordered[-1], 4)}

    return {key: stats(values) for key, values in timings.items()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--thread", required=True)
    parser.add_argument("--rounds", type=int, default=8)
    args = parser.parse_args()

    source = Path(args.db)
    with tempfile.TemporaryDirectory(prefix="bench-write-") as temp_dir:
        copy = Path(temp_dir) / "core.db"
        shutil.copyfile(source, copy)
        result = asyncio.run(bench(copy, args.thread, args.rounds))
    print(args.thread, json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
