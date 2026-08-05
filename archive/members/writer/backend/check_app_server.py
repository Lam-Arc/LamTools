"""Direct app-server check for a given session/thread ID."""
from __future__ import annotations

import asyncio
import json
import sys

from writer_cli.app_server_client import AppServerClient


async def check(thread_id: str) -> int:
    client = AppServerClient("http://127.0.0.1:6173")
    try:
        await client.connect(thread_id=thread_id, last_seen_seq=0)
        # Ask for the thread snapshot via the app-server protocol
        snapshot = await client.request("thread/read", {"thread_id": thread_id})
        print(json.dumps(snapshot, indent=2, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(f"app-server check failed: {exc}", file=sys.stderr)
        return 1
    finally:
        await client.close()


if __name__ == "__main__":
    tid = sys.argv[1] if len(sys.argv) > 1 else "1782272706383"
    raise SystemExit(asyncio.run(check(tid)))
