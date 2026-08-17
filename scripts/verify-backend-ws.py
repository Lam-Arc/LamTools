# -*- mode: python ; coding: utf-8 -*-
"""Verify a packaged LamCore backend can serve real WebSocket traffic.

Used by:
  - Local packaging flow (scripts/package.ps1 follow-up)
  - CI smoke test (release.yml) to catch missing websockets/wsproto deps

Usage:
  python scripts/verify-backend-ws.py --exe <path-to-LamCore.exe> --port 6233
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request


def wait_health(port: int, timeout_s: int = 60) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as r:
                if r.status == 200:
                    return True
        except OSError:
            pass
        time.sleep(0.5)
    return False


def verify_ws(port: int) -> bool:
    """Real WebSocket handshake + initialize round-trip using the websockets lib."""
    import asyncio

    async def _run() -> bool:
        import websockets

        url = f"ws://127.0.0.1:{port}/api/core/app-server"
        async with websockets.connect(url, open_timeout=8) as ws:
            await ws.send(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "clientInfo": {"name": "verify-ws", "version": "1"},
                            "threadId": "verify-thread",
                            "lastSeenSeq": 0,
                        },
                    }
                )
            )
            resp = await asyncio.wait_for(ws.recv(), timeout=8)
            data = json.loads(resp)
            return data.get("id") == 1 and "result" in data

    return asyncio.run(_run())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", required=True, help="Path to packaged LamCore.exe")
    parser.add_argument("--port", type=int, default=6233)
    args = parser.parse_args()

    if not os.path.isfile(args.exe):
        print(f"[FAIL] backend exe not found: {args.exe}")
        return 1

    tmp_home = tempfile.mkdtemp(prefix="lamcore-verify-")
    env = os.environ.copy()
    env["LAMCORE_PORT"] = str(args.port)
    env["LAMTOOLS_HOME"] = tmp_home

    proc = subprocess.Popen(
        [args.exe],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        if not wait_health(args.port):
            print("[FAIL] backend did not reach /api/health")
            return 1
        print("[OK] REST /api/health reachable")

        if verify_ws(args.port):
            print("[OK] WebSocket handshake + initialize round-trip succeeded")
            return 0
        print("[FAIL] WebSocket handshake/initialize failed (missing websockets dep?)")
        return 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
