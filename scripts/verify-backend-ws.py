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


def verify_ws(port: int) -> tuple[bool, str]:
    """Verify packaged WebSocket, Study, and dynamic plugin RPC surfaces.

    The websearch plugin ships disabled by default (`defaultEnabled: false` in its
    manifest) and a disabled plugin's operations answer "Unsupported method", so
    this enables it the way the panel does before calling its widget RPC. What the
    smoke proves stays the same — the bundled backend can load the plugin and serve
    its declared operations — without asserting the product's default.
    """
    import asyncio

    async def _run() -> tuple[bool, str]:
        import websockets

        async def receive_response(ws, request_id: int) -> dict:
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=8)
                message = json.loads(raw)
                if message.get("id") == request_id:
                    return message

        async def call(ws, request_id: int, method: str, params: dict) -> tuple[dict | None, str]:
            await ws.send(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "method": method,
                        "params": params,
                    }
                )
            )
            data = await receive_response(ws, request_id)
            if data.get("id") != request_id or "result" not in data:
                error = data.get("error") if isinstance(data.get("error"), dict) else {}
                return None, str(error.get("message") or f"{method} failed")
            return data.get("result") or {}, ""

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
            data = await receive_response(ws, 1)
            if data.get("id") != 1 or "result" not in data:
                return False, "WebSocket initialize failed"

            listing, listing_error = await call(ws, 2, "plugin.list", {})
            if listing is None:
                return False, listing_error
            plugins = listing.get("plugins") if isinstance(listing, dict) else None
            if not isinstance(plugins, list):
                return False, "plugin.list returned no plugins array"
            websearch = next(
                (item for item in plugins if isinstance(item, dict) and item.get("name") == "websearch"),
                None,
            )
            if websearch is None:
                return False, "websearch is missing from the packaged plugin registry"
            if websearch.get("enabled") is not True:
                enabled, enable_error = await call(ws, 3, "plugin.enable", {"name": "websearch"})
                if enabled is None:
                    return False, enable_error

            study, study_error = await call(ws, 4, "study.session", {"scope": "builder"})
            if study is None:
                return False, study_error
            if not study.get("session_id"):
                return False, "study.session returned no session_id"

            snapshot, snapshot_error = await call(ws, 5, "websearch.widget.snapshot", {})
            if snapshot is None:
                return False, snapshot_error
            if snapshot.get("schema_version") != 1:
                return False, "websearch.widget.snapshot returned no schema_version"
            return True, ""

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

        ws_ok, ws_error = verify_ws(args.port)
        if ws_ok:
            print(
                "[OK] WebSocket initialize + plugin.enable(websearch) + study.session + "
                "websearch.widget.snapshot round-trip succeeded"
            )
            return 0
        print(f"[FAIL] packaged WebSocket/Study RPC smoke failed: {ws_error}")
        return 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
