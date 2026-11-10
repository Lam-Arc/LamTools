"""Benchmark Sunday's history paging over the real app-server RPC.

Measures what the desktop client actually pays when it opens a long thread and
walks backwards through it:

    first_page   ``thread/resume`` with the snapshot (what switchThread does)
    page_n       ``thread/history`` following the before_item_id/before_seq cursor
    outline      ``thread/outline`` (the outline rail)
    locate       jumping straight to an old message (``thread/pageAround``)

and reports the wire bytes of each response next to the full materialized
snapshot size, which is what the pre-paging client shipped.

Usage:
    python core/scripts/message_paging/bench_history.py --port 5918 \
        --thread perf-long --pages 5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import statistics
import sys
import time
import uuid
from pathlib import Path
from typing import Any

try:
    import aiohttp
except ModuleNotFoundError:  # pragma: no cover - harness convenience
    aiohttp = None  # type: ignore[assignment]


def _stats(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"p50": 0.0, "p95": 0.0, "max": 0.0, "n": 0}
    ordered = sorted(values)
    p95_index = max(0, min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1)))))
    return {
        "p50": round(statistics.median(ordered), 1),
        "p95": round(ordered[p95_index], 1),
        "max": round(ordered[-1], 1),
        "n": len(ordered),
    }


class Rpc:
    def __init__(self, ws: Any) -> None:
        self.ws = ws

    async def call(self, method: str, params: dict[str, Any], timeout: float = 120.0) -> tuple[dict[str, Any], int, float]:
        request_id = f"bench-{uuid.uuid4().hex[:12]}"
        frame = json.dumps(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
            ensure_ascii=False,
        )
        started = time.perf_counter()
        await self.ws.send_str(frame)
        payload_bytes = 0
        deadline = started + timeout
        while time.perf_counter() < deadline:
            message = await self.ws.receive(timeout=max(0.1, deadline - time.perf_counter()))
            if message.type is not aiohttp.WSMsgType.TEXT:
                continue
            payload_bytes += len(message.data.encode("utf-8"))
            decoded = json.loads(message.data)
            if decoded.get("id") != request_id:
                # Server-pushed event frame interleaved with the response.
                continue
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            if decoded.get("error"):
                raise RuntimeError(f"{method} failed: {decoded['error']}")
            return decoded.get("result") or {}, payload_bytes, elapsed_ms
        raise TimeoutError(f"{method} timed out after {timeout:.0f}s")


def _db_facts(db_path: Path, thread_id: str) -> dict[str, Any]:
    """Full-materialized size: what the pre-paging client used to receive."""
    facts: dict[str, Any] = {}
    if not db_path.exists():
        return facts
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        row = connection.execute(
            "select length(snapshot_json) from core_thread_snapshots where thread_id = ?",
            (thread_id,),
        ).fetchone()
        facts["metadata_bytes"] = int(row[0] or 0) if row else 0
        row = connection.execute(
            "select count(*), coalesce(sum(length(item_json)), 0) from core_thread_snapshot_items where thread_id = ?",
            (thread_id,),
        ).fetchone()
        facts["item_rows"] = int(row[0] or 0) if row else 0
        facts["item_bytes"] = int(row[1] or 0) if row else 0
        try:
            row = connection.execute(
                "select count(*) from core_app_events where thread_id = ?",
                (thread_id,),
            ).fetchone()
            facts["event_rows"] = int(row[0] or 0) if row else 0
        except sqlite3.OperationalError:
            facts["event_rows"] = None
        facts["full_snapshot_bytes"] = facts["metadata_bytes"] + facts["item_bytes"]
    finally:
        connection.close()
    return facts


def _page_facts(page: dict[str, Any]) -> dict[str, Any]:
    core = page.get("core") or {}
    items = core.get("items") or {}
    top = page.get("items") or {}
    history = page.get("history_page") or {}
    turns = core.get("turns") or {}
    return {
        "core_items": len(items),
        "top_items": len(top),
        "turns": len(turns),
        "history_page": {
            key: history.get(key)
            for key in (
                "item_count", "total_items", "has_more", "turn_count",
                "byte_count", "next_before_item_id", "next_before_seq",
            )
        },
    }


async def run(args: argparse.Namespace) -> int:
    if aiohttp is None:
        print("aiohttp is required", file=sys.stderr)
        return 2
    report: dict[str, Any] = {
        "thread": args.thread,
        "db": _db_facts(Path(args.db), args.thread),
        "first_load_ms": [],
        "page_ms": [],
        "page_bytes": [],
        "locate_ms": [],
        "locate_bytes": [],
    }
    async with aiohttp.ClientSession() as session:
        url = f"ws://127.0.0.1:{args.port}/api/core/app-server"
        async with session.ws_connect(url, heartbeat=None, max_msg_size=0) as ws:
            rpc = Rpc(ws)
            await rpc.call("initialize", {
                "clientInfo": {"name": "message-paging-bench", "version": "1"},
                "threadId": args.thread,
                "lastSeenSeq": 0,
            })

            first_page: dict[str, Any] = {}
            for _ in range(args.rounds):
                result, payload_bytes, elapsed_ms = await rpc.call("thread/resume", {
                    "thread_id": args.thread,
                    "last_seen_seq": 0,
                    "include_snapshot": True,
                    "turn_limit": args.turn_limit,
                })
                first_page = result.get("snapshot") or {}
                report["first_load_ms"].append(elapsed_ms)
                report["first_page_bytes"] = payload_bytes
                report["first_page"] = _page_facts(first_page)
                await asyncio.sleep(0.2)

            # Walk backwards through the cursor the client follows.
            page = first_page
            cursor_item = ""
            cursor_seq = 0
            pages_seen = 0
            while pages_seen < args.pages:
                history = page.get("history_page") or {}
                next_item = str(history.get("next_before_item_id") or "")
                next_seq = int(history.get("next_before_seq") or 0)
                if not history.get("has_more") or (not next_item and next_seq <= 0):
                    break
                params: dict[str, Any] = {
                    "thread_id": args.thread,
                    "turn_limit": args.turn_limit,
                }
                if next_item:
                    params["before_item_id"] = next_item
                params["before_seq"] = next_seq
                result, payload_bytes, elapsed_ms = await rpc.call("thread/history", params)
                page = result.get("snapshot_page") or {}
                report["page_ms"].append(elapsed_ms)
                report["page_bytes"].append(payload_bytes)
                cursor_item, cursor_seq = next_item, next_seq
                pages_seen += 1
                if not page:
                    break

            outline_result, outline_bytes, outline_ms = await rpc.call(
                "thread.outline", {"thread_id": args.thread}
            )
            report["outline_ms"] = round(outline_ms, 1)
            report["outline_bytes"] = outline_bytes
            report["outline_turns"] = len(
                (outline_result.get("outline") or {}).get("turns") or []
            )

            # Jump straight to an old message. The baseline (scroll-and-load)
            # is the same operation without a direct locator: pages p95 × n.
            if args.locate_item_id:
                for _ in range(args.rounds):
                    result, payload_bytes, elapsed_ms = await rpc.call(
                        "thread/pageAround",
                        {
                            "thread_id": args.thread,
                            "item_id": args.locate_item_id,
                            "turn_limit": args.turn_limit,
                        },
                    )
                    report["locate_ms"].append(elapsed_ms)
                    report["locate_bytes"].append(payload_bytes)
                    await asyncio.sleep(0.1)
                report["locate_found"] = bool(
                    ((result.get("snapshot_page") or {}).get("core") or {}).get("items")
                )

    report["first_load_stats"] = _stats(report["first_load_ms"])
    report["page_stats"] = _stats([float(value) for value in report["page_bytes"]])
    report["page_latency_stats"] = _stats(report["page_ms"])
    report["locate_stats"] = _stats(report["locate_ms"])
    full = int(report["db"].get("full_snapshot_bytes") or 0)
    first = int(report.get("first_page_bytes") or 0)
    report["first_page_vs_full"] = {
        "full_snapshot_bytes": full,
        "first_page_bytes": first,
        "reduction_ratio": round(1 - first / full, 4) if full else None,
    }
    print("BENCH_JSON " + json.dumps(report, ensure_ascii=False), flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--db", required=True)
    parser.add_argument("--thread", default="perf-long")
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--pages", type=int, default=5)
    parser.add_argument("--turn-limit", type=int, default=10)
    parser.add_argument("--locate-item-id", default="")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
