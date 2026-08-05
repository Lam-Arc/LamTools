from __future__ import annotations

import asyncio
import json
import os
import socket
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

import aiohttp
import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parents[2]


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _writer_server_process(*, port: int, data_dir: Path, config_db: Path, work_root: Path) -> subprocess.Popen[str]:
    env = os.environ.copy()
    env.update(
        {
            "LAMWRITER_DATA_DIR": str(data_dir),
            "LAMTOOLS_LLM_CONFIG_DB": str(config_db),
            "LAMWRITER_WRITER_WORK_ROOT": str(work_root),
            "PYTHONUTF8": "1",
            "PYTHONPATH": os.pathsep.join(
                [str(REPO_ROOT / "core" / "src"), str(BACKEND_DIR), env.get("PYTHONPATH", "")]
            ),
        }
    )
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=BACKEND_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


async def _wait_for_server(base_url: str, process: subprocess.Popen[str]) -> None:
    timeout = aiohttp.ClientTimeout(total=0.5)
    async with aiohttp.ClientSession(timeout=timeout) as client:
        for _ in range(100):
            if process.poll() is not None:
                output = process.stdout.read() if process.stdout is not None else ""
                raise AssertionError(f"Writer Uvicorn exited before becoming ready:\n{output}")
            try:
                async with client.get(f"{base_url}/api/health") as response:
                    if response.status == 200:
                        return
            except (aiohttp.ClientError, asyncio.TimeoutError):
                pass
            await asyncio.sleep(0.05)
    raise AssertionError("Writer Uvicorn did not become ready")


async def _rpc(
    websocket: aiohttp.ClientWebSocketResponse,
    request_id: int,
    method: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    await websocket.send_json({"id": request_id, "method": method, "params": params})
    for _ in range(20):
        message = await websocket.receive(timeout=5)
        assert message.type is aiohttp.WSMsgType.TEXT, message
        payload = json.loads(message.data)
        if payload.get("id") == request_id:
            assert "error" not in payload, payload
            result = payload.get("result")
            assert isinstance(result, dict), payload
            return result
    raise AssertionError(f"No JSON-RPC response for {method}")


def _persisted_methods(database: Path, thread_id: str) -> list[str]:
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            "select method from writer_app_events where thread_id = ? order by seq",
            (thread_id,),
        ).fetchall()
    return [str(row[0]) for row in rows]


@pytest.mark.asyncio
async def test_writer_app_server_network_round_trip_uses_core_host_and_persists_after_disconnect(tmp_path: Path) -> None:
    data_dir = tmp_path / "writer-data"
    config_db = tmp_path / "config" / "lamtools.db"
    work_root = tmp_path / "workspace"
    port = _free_local_port()
    base_url = f"http://127.0.0.1:{port}"
    thread_id = "network-thread"
    queue_item_id = "network-queue"
    process = _writer_server_process(
        port=port,
        data_dir=data_dir,
        config_db=config_db,
        work_root=work_root,
    )

    try:
        await _wait_for_server(base_url, process)
        async with aiohttp.ClientSession() as client:
            async with client.ws_connect(f"ws://127.0.0.1:{port}/api/app-server") as websocket:
                initialized = await _rpc(
                    websocket,
                    1,
                    "initialize",
                    {"clientInfo": {"name": "network-e2e"}, "lastSeenSeq": 0},
                )
                assert initialized["protocolVersion"] == "writer.app_server.v1"
                assert initialized["serverInfo"]["name"] == "writer_app_server"
                assert await _rpc(websocket, 2, "initialized", {}) == {"ok": True}

                started = await _rpc(
                    websocket,
                    3,
                    "thread.start",
                    {"thread_id": thread_id, "title": "Network E2E", "work_root": str(work_root)},
                )
                assert started["thread"] == {"id": thread_id}
                assert started["event"]["method"] == "thread/started"

                queued = await _rpc(
                    websocket,
                    4,
                    "queue.create",
                    {
                        "thread_id": thread_id,
                        "queue_item_id": queue_item_id,
                        "client_message_id": "network-queue-create",
                        "input": [{"type": "text", "text": "queued input"}],
                    },
                )
                assert queued["queue_item"]["queue_item_id"] == queue_item_id
                assert queued["queue_item"]["status"] == "queued"

                updated = await _rpc(
                    websocket,
                    5,
                    "queue.update",
                    {"thread_id": thread_id, "queue_item_id": queue_item_id, "text": "updated input"},
                )
                assert updated["events"][0]["method"] == "queue/itemUpdated"

                deleted = await _rpc(
                    websocket,
                    6,
                    "queue.delete",
                    {"thread_id": thread_id, "queue_item_id": queue_item_id},
                )
                assert deleted["events"][0]["method"] == "queue/itemDeleted"
                await websocket.close()
                assert websocket.closed

            async with client.ws_connect(f"ws://127.0.0.1:{port}/api/app-server") as reconnect:
                await _rpc(
                    reconnect,
                    7,
                    "initialize",
                    {"clientInfo": {"name": "network-e2e-reconnect"}, "threadId": thread_id},
                )
                await _rpc(reconnect, 8, "initialized", {})
                read = await _rpc(reconnect, 9, "thread.read", {"thread_id": thread_id})
                assert read["thread"] == {"id": thread_id}
                assert read["session"]["id"] == thread_id
                assert [event["method"] for event in read["events"]] == [
                    "thread/started",
                    "queue/itemAccepted",
                    "queue/itemUpdated",
                    "queue/itemDeleted",
                ]
    finally:
        if process.poll() is None:
            process.terminate()
            await asyncio.to_thread(process.wait, 10)

    assert process.returncode is not None
    assert not _is_port_open(port)
    database = data_dir / "lamwriter.db"
    assert database.exists()
    assert _persisted_methods(database, thread_id) == [
        "thread/started",
        "queue/itemAccepted",
        "queue/itemUpdated",
        "queue/itemDeleted",
    ]


def _is_port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
        client.settimeout(0.2)
        return client.connect_ex(("127.0.0.1", port)) == 0
