"""Measure Sunday's send confirmation over the real app-server RPC.

The desktop talks to Core over a WebSocket at ``/api/core/app-server`` speaking
JSON-RPC. This script opens that same socket, initialises it, and sends
``turn/start`` the way the composer does (``include_snapshot: false``), timing:

    t_request   the frame is written to the socket
    t_accepted  the ``turn/start`` result frame arrives      -> Core confirmed
    t_first     the first ``core/runItem`` frame for the turn -> Agent started

Usage:
    python core/scripts/send_latency/measure.py --port 5918 --rounds 10 \
        --thread perf-short --thread perf-mid --thread perf-long
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import uuid
from typing import Any

try:  # aiohttp ships with Core; fall back to the stdlib client if absent.
    import aiohttp
except ModuleNotFoundError:  # pragma: no cover - harness convenience
    aiohttp = None  # type: ignore[assignment]

import asyncio


class _Measurement:
    def __init__(self) -> None:
        self.accept_ms: list[float] = []
        self.first_ms: list[float] = []
        self.request_bytes: list[int] = []
        self.response_bytes: list[int] = []

    def summary(self) -> dict[str, Any]:
        def stats(values: list[float]) -> dict[str, float]:
            if not values:
                return {"p50": 0.0, "p95": 0.0, "max": 0.0, "min": 0.0, "n": 0}
            ordered = sorted(values)
            p95_index = max(0, min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1)))))
            return {
                "p50": round(statistics.median(ordered), 1),
                "p95": round(ordered[p95_index], 1),
                "max": round(ordered[-1], 1),
                "min": round(ordered[0], 1),
                "n": len(ordered),
            }

        return {
            "accept_ms": stats(self.accept_ms),
            "first_item_ms": stats(self.first_ms),
            "request_bytes": stats([float(v) for v in self.request_bytes]),
            "response_bytes": stats([float(v) for v in self.response_bytes]),
        }


async def _send_turn(
    ws: Any,
    *,
    thread_id: str,
    text: str,
    timeout: float,
) -> tuple[float, float, int, int]:
    """Send one turn and return (accept_ms, first_item_ms, req_bytes, resp_bytes)."""

    request_id = f"perf-{uuid.uuid4().hex[:12]}"
    client_message_id = uuid.uuid4().hex
    payload = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "turn/start",
        "params": {
            "thread_id": thread_id,
            "client_message_id": client_message_id,
            "input": [{"type": "text", "text": text}],
            "include_snapshot": False,
            "work_root": "E:\\LamTools",
            # The composer always names the model it is showing; the harness
            # does the same so the runtime does not have to guess.
            "model_id": "stub-chat",
        },
    }
    frame = json.dumps(payload, ensure_ascii=False)
    request_bytes = len(frame.encode("utf-8"))
    started = time.perf_counter()
    await ws.send_str(frame)
    accept_ms = -1.0
    first_ms = -1.0
    response_bytes = 0
    deadline = started + timeout
    while time.perf_counter() < deadline:
        remaining = deadline - time.perf_counter()
        try:
            message = await ws.receive(timeout=remaining)
        except asyncio.TimeoutError:
            break
        if message.type is not aiohttp.WSMsgType.TEXT:
            continue
        response_bytes += len(message.data)
        try:
            decoded = json.loads(message.data)
        except ValueError:
            continue
        now = time.perf_counter()
        if decoded.get("id") == request_id and accept_ms < 0:
            accept_ms = (now - started) * 1000.0
            error = decoded.get("error")
            if error:
                return accept_ms, -1.0, request_bytes, response_bytes
            # The turn id rides the accepted event; watch for its first item.
            continue
        method = decoded.get("method")
        if accept_ms >= 0 and method in {"core/runItem", "turn/started", "item/started"}:
            first_ms = (now - started) * 1000.0
            break
    return accept_ms, first_ms, request_bytes, response_bytes


async def _settle(ws: Any, *, quiet: float = 0.6, timeout: float = 60.0) -> None:
    """Drain frames until the turn goes quiet, so rounds do not overlap."""

    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        try:
            message = await ws.receive(timeout=quiet)
        except asyncio.TimeoutError:
            return
        if message.type is aiohttp.WSMsgType.CLOSED:
            return


async def run(args: argparse.Namespace) -> int:
    if aiohttp is None:
        print("aiohttp is required for the harness", file=sys.stderr)
        return 2
    results: dict[str, dict[str, Any]] = {}
    async with aiohttp.ClientSession() as session:
        for thread_id in args.thread:
            url = f"ws://127.0.0.1:{args.port}/api/core/app-server"
            async with session.ws_connect(url, heartbeat=None, max_msg_size=0) as ws:
                init_id = f"init-{uuid.uuid4().hex[:8]}"
                await ws.send_str(json.dumps({
                    "jsonrpc": "2.0",
                    "id": init_id,
                    "method": "initialize",
                    "params": {
                        "clientInfo": {"name": "send-latency-harness", "version": "1"},
                        "threadId": thread_id,
                        "lastSeenSeq": 0,
                    },
                }))
                while True:
                    message = await ws.receive(timeout=60)
                    if message.type is not aiohttp.WSMsgType.TEXT:
                        continue
                    decoded = json.loads(message.data)
                    if decoded.get("id") == init_id:
                        break
                await _settle(ws, quiet=0.8, timeout=30)
                measurement = _Measurement()
                for round_index in range(args.rounds):
                    text = f"发送延迟测量第 {round_index + 1} 轮"
                    accept_ms, first_ms, req_bytes, resp_bytes = await _send_turn(
                        ws, thread_id=thread_id, text=text, timeout=args.timeout,
                    )
                    if accept_ms < 0:
                        print(f"  ! round {round_index} got no accept frame", file=sys.stderr)
                        break
                    measurement.accept_ms.append(accept_ms)
                    if args.verbose:
                        print(
                            f"  round {round_index:02d} {thread_id}: accept={accept_ms:.1f}ms "
                            f"first={first_ms:.1f}ms resp={resp_bytes}B",
                            flush=True,
                        )
                    if first_ms > 0:
                        measurement.first_ms.append(first_ms)
                    measurement.request_bytes.append(req_bytes)
                    measurement.response_bytes.append(resp_bytes)
                    await _settle(ws, quiet=0.5 if args.rounds > 3 else 0.8)
                results[thread_id] = measurement.summary()
                print(f"{thread_id}: {json.dumps(results[thread_id], ensure_ascii=False)}", flush=True)
    print("RESULT_JSON " + json.dumps(results, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--thread", action="append", default=[])
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
