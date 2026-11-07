#!/usr/bin/env python3
"""Look inside the running webview through the DevTools protocol.

`uiautomator dump` only exposes what accessibility decided to publish: it cannot say
whether a click handler ran, what a request returned, or why a promise rejected. The
Tauri debug build exposes `webview_devtools_remote_<pid>`, so the honest way to debug
the real UI is to attach to it instead of guessing from pixels.

This is an observation channel for diagnosing the shipped UI, not a test shortcut: the
flows themselves are still driven by `android_ui.py` through the real screen.

Usage
    android_cdp.py eval "document.title"
    android_cdp.py logs 10                # print console logs for 10 seconds
    android_cdp.py info                   # page list and connection details

Requires `adb forward tcp:9222 localabstract:webview_devtools_remote_<pid>`, which
`android_ui.py cdp-forward` performs.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import urllib.error
import urllib.request

DEFAULT_ENDPOINT = "http://127.0.0.1:9222"


def page_ws(endpoint: str) -> str:
    # The devtools endpoint is on localhost, but a system-wide HTTP proxy answers for
    # it with 502 Bad Gateway. Every request here goes through an opener that ignores
    # the environment's proxy settings.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"{endpoint}/json/list", timeout=10) as response:
            pages = json.load(response)
    except (urllib.error.URLError, TimeoutError) as error:
        raise SystemExit(f"devtools endpoint {endpoint} is not reachable: {error}")
    for page in pages:
        if page.get("type") == "page":
            return page["webSocketDebuggerUrl"]
    raise SystemExit("devtools endpoint has no page target")


async def call(ws_url: str, method: str, params: dict, timeout: float = 30) -> dict:
    import websockets

    # `proxy=None` matters: a newer websockets release picks up the environment's
    # proxy on its own, and a system-wide proxy cannot reach the adb-forwarded port.
    async with websockets.connect(ws_url, max_size=64 * 1024 * 1024, proxy=None) as ws:
        await ws.send(json.dumps({"id": 1, "method": method, "params": params}))
        async with asyncio.timeout(timeout):
            while True:
                message = json.loads(await ws.recv())
                if message.get("id") == 1:
                    return message
    raise SystemExit(f"{method} returned no reply")


async def evaluate(ws_url: str, expression: str) -> dict:
    reply = await call(
        ws_url,
        "Runtime.evaluate",
        {"expression": expression, "returnByValue": True, "awaitPromise": True, "userGesture": True},
    )
    return reply.get("result", {})


async def stream_logs(ws_url: str, seconds: float) -> None:
    import websockets

    async with websockets.connect(ws_url, max_size=64 * 1024 * 1024, proxy=None) as ws:
        for domain in ("Runtime.enable", "Log.enable"):
            await ws.send(json.dumps({"id": domain, "method": domain, "params": {}}))
        deadline = asyncio.get_running_loop().time() + seconds
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
            except TimeoutError:
                return
            message = json.loads(raw)
            method = message.get("method")
            if method == "Runtime.consoleAPICalled":
                kind = message["params"].get("type", "?")
                text = " ".join(
                    str(arg.get("value", arg.get("description", "")))
                    for arg in message["params"].get("args", [])
                )
                print(f"[console.{kind}] {text}")
            elif method == "Log.entryAdded":
                entry = message["params"]["entry"]
                print(f"[{entry.get('level', '?')}] {entry.get('text', '')}")
            elif method == "Runtime.exceptionThrown":
                detail = message["params"]["exceptionDetails"]
                print(f"[exception] {detail.get('text', '')} {detail.get('exception', {}).get('description', '')}")


def forward(port: int = 9222) -> None:
    """Point localhost at the running webview's devtools socket.

    The socket name carries the app's pid, which changes on every restart, so the
    forward has to be re-established rather than cached.
    """
    adb = find_adb()
    listing = subprocess.run(
        [adb, "shell", "cat /proc/net/unix"], capture_output=True, text=True, timeout=60
    ).stdout
    names = [line.rsplit(" ", 1)[-1] for line in listing.splitlines() if "webview_devtools_remote" in line]
    if not names:
        raise SystemExit("no webview devtools socket: is the app running and debuggable?")
    # The listing prints the abstract socket with a leading "@"; adb wants the name
    # without it, and forwarding to "localabstract:@name" silently accepts the
    # forward and then drops every connection.
    name = names[-1].strip().lstrip("@")
    subprocess.run([adb, "forward", f"tcp:{port}", f"localabstract:{name}"], check=True, timeout=60)
    print(f"tcp:{port} -> {name}")


def find_adb() -> str:
    import os
    from pathlib import Path

    for candidate in (os.environ.get("ANDROID_HOME"), os.environ.get("ANDROID_SDK_ROOT"), r"E:\Environment\AndroidSDK"):
        if candidate and (Path(candidate) / "platform-tools").exists():
            return str(Path(candidate) / "platform-tools" / ("adb.exe" if os.name == "nt" else "adb"))
    return "adb"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["eval", "logs", "info", "forward"])
    parser.add_argument("argument", nargs="?", default="")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    args = parser.parse_args(argv)

    if args.command == "forward":
        forward()
        return 0

    ws_url = page_ws(args.endpoint)

    if args.command == "info":
        print(json.dumps({"websocket": ws_url}, indent=2))
        return 0

    if args.command == "eval":
        if not args.argument:
            print("eval needs an expression", file=sys.stderr)
            return 2
        result = asyncio.run(evaluate(ws_url, args.argument))
        if "exceptionDetails" in result:
            print(json.dumps(result["exceptionDetails"], ensure_ascii=False, indent=2), file=sys.stderr)
            return 4
        value = result.get("result", {})
        # Prefer the plain value; fall back to the description so functions and
        # objects still print something readable.
        print(value.get("value") if "value" in value else value.get("description", ""))
        return 0

    if args.command == "logs":
        seconds = float(args.argument or 10)
        asyncio.run(stream_logs(ws_url, seconds))
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
