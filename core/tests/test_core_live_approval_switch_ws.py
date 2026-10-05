"""Wire-level check: a pending approval survives switching sessions.

The desktop client switches sessions by ``thread/resume``-ing another thread
and then resuming the original one; the approval is answered afterwards. This
test drives that exact sequence against a real uvicorn app-server over a real
websocket, using the same client the app uses.
"""

from __future__ import annotations

import asyncio
import socket
from dataclasses import dataclass
from pathlib import Path

import pytest

uvicorn = pytest.importorskip("uvicorn")

from lamtools_core.app import CoreAppServerClient
from lamtools_core.app.http_agent_app import CoreConfigRoutingLLMClient, create_core_agent_http_app
from lamtools_core.llm import LLMResponse, LLMStreamEvent, LLMToolCall

THREAD_ID = "thread-ws-approval"
OTHER_THREAD_ID = "thread-ws-other"
REQUEST_ID = "call-ws-approval"


def _write_jsonc_config(config_root: Path) -> None:
    provider_dir = config_root / "providers"
    provider_dir.mkdir(parents=True, exist_ok=True)
    (provider_dir / "provider-1.jsonc").write_text(
        '{\n'
        '  "id": "provider-1",\n'
        '  "name": "Provider",\n'
        '  "api_type": "openai",\n'
        '  "base_url": "https://example.test/v1",\n'
        '  "api_key": "secret"\n'
        '}\n',
        encoding="utf-8",
    )
    model_dir = config_root / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "model-record.jsonc").write_text(
        '{\n'
        '  "model_id": "model-record",\n'
        '  "display_name": "Model Name",\n'
        '  "provider": "Provider",\n'
        '  "provider_id": "provider-1",\n'
        '  "context_window": 128000,\n'
        '  "max_output_tokens": 4096,\n'
        '  "temperature": 0.2,\n'
        '  "thinking": {"supported": true, "budget": 10000}\n'
        '}\n',
        encoding="utf-8",
    )


def _pending_request_items(snapshot: dict) -> list[dict]:
    found = []
    for item in ((snapshot.get("core") or {}).get("items") or {}).values():
        if not isinstance(item, dict):
            continue
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        if str(payload.get("type") or item.get("type") or "") != "serverRequest":
            continue
        if str(item.get("status") or "") == "waiting":
            found.append(item)
    return found


async def _wait_for_waiting(client: CoreAppServerClient, thread_id: str) -> None:
    for _ in range(200):
        snapshot = (await client.read_thread(thread_id=thread_id)).get("snapshot") or {}
        if (snapshot.get("core") or {}).get("status") == "waiting":
            return
        await asyncio.sleep(0.01)
    raise AssertionError("approval request did not become pending")


async def _wait_for_terminal(client: CoreAppServerClient, thread_id: str, *, timeout: float = 10.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    last: dict = {}
    while asyncio.get_running_loop().time() < deadline:
        snapshot = (await client.read_thread(thread_id=thread_id)).get("snapshot") or {}
        last = snapshot
        if (snapshot.get("core") or {}).get("status") in {"completed", "cancelled", "failed"}:
            return
        await asyncio.sleep(0.02)
    raise AssertionError(f"{thread_id} never reached a terminal state: {last}")


@dataclass
class _RunningServer:
    server: uvicorn.Server
    task: asyncio.Task
    port: int

    async def stop(self) -> None:
        self.server.should_exit = True
        await asyncio.wait_for(self.task, timeout=15)


async def _start_server(*, core_db: Path, data_dir: Path, work_root: Path) -> _RunningServer:
    app = create_core_agent_http_app(
        model_id="model-record",
        core_db=core_db,
        data_dir=data_dir,
        work_root=work_root,
    )
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        port = int(listener.getsockname()[1])
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    task = asyncio.create_task(server.serve())
    for _ in range(300):
        if server.started:
            break
        await asyncio.sleep(0.01)
    assert server.started, "app server did not start"
    return _RunningServer(server=server, task=task, port=port)


def _scripted_llm_model(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """Patch the routing LLM so turn 1 asks for an approval-gated write."""
    calls = {"count": 0}

    async def stream(self, request):
        calls["count"] += 1
        if calls["count"] == 1:
            yield LLMStreamEvent(
                kind="done",
                tool_calls=[
                    LLMToolCall(
                        id=REQUEST_ID,
                        name="write_file",
                        arguments={"path": "approved.md", "content": "approved\n"},
                    )
                ],
            )
            return
        yield LLMStreamEvent(kind="content_delta", content="done")
        yield LLMStreamEvent(kind="done")

    async def complete(self, request):
        # Non-streaming callers (session auto-title) must not fail the run.
        return LLMResponse(content="title")

    monkeypatch.setattr(CoreConfigRoutingLLMClient, "stream", stream)
    monkeypatch.setattr(CoreConfigRoutingLLMClient, "complete", complete)
    return calls


@pytest.mark.asyncio
async def test_pending_approval_survives_switching_sessions_over_the_wire(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_config_root: Path
) -> None:
    _write_jsonc_config(isolated_config_root)
    _scripted_llm_model(monkeypatch)
    work_root = tmp_path / "work"
    running = await _start_server(
        core_db=tmp_path / "core.db", data_dir=tmp_path / "data", work_root=work_root
    )
    try:
        client = CoreAppServerClient(f"http://127.0.0.1:{running.port}")
        try:
            await client.connect()
            await client.start_turn(
                thread_id=THREAD_ID,
                client_message_id="start-approval",
                input_items=[{"type": "text", "text": "approval please"}],
            )
            await _wait_for_waiting(client, THREAD_ID)

            # Switch away to another session, then come back — exactly what the
            # client does when the user leaves the session and returns.
            await client.request("thread.start", {"thread_id": OTHER_THREAD_ID})
            await client.request(
                "thread.resume", {"thread_id": OTHER_THREAD_ID, "last_seen_seq": 0}
            )
            switched_back = await client.request(
                "thread.resume", {"thread_id": THREAD_ID, "last_seen_seq": 0}
            )
            snapshot = switched_back.get("snapshot") or {}
            assert _pending_request_items(snapshot), "the resumed snapshot lost the pending request"

            await client.respond_approval(
                thread_id=THREAD_ID,
                request_id=REQUEST_ID,
                decision="approve_once",
            )
            await _wait_for_terminal(client, THREAD_ID)
            assert (work_root / "approved.md").read_text(encoding="utf-8") == "approved\n"
        finally:
            await client.close()
    finally:
        await running.stop()


@pytest.mark.asyncio
async def test_pending_approval_survives_an_app_restart_over_the_wire(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_config_root: Path
) -> None:
    """Closing Sunday during an approval and reopening it must leave the request
    visible and answerable (the reported failure)."""
    _write_jsonc_config(isolated_config_root)
    calls = _scripted_llm_model(monkeypatch)
    work_root = tmp_path / "work"
    core_db = tmp_path / "core.db"
    data_dir = tmp_path / "data"

    first = await _start_server(core_db=core_db, data_dir=data_dir, work_root=work_root)
    try:
        client = CoreAppServerClient(f"http://127.0.0.1:{first.port}")
        try:
            await client.connect()
            await client.start_turn(
                thread_id=THREAD_ID,
                client_message_id="start-approval",
                input_items=[{"type": "text", "text": "approval please"}],
            )
            await _wait_for_waiting(client, THREAD_ID)
        finally:
            await client.close()
    finally:
        await first.stop()

    # Reopen: a fresh app server over the same database, then the client
    # reconnects and resumes the session.
    second = await _start_server(core_db=core_db, data_dir=data_dir, work_root=work_root)
    try:
        client = CoreAppServerClient(f"http://127.0.0.1:{second.port}")
        try:
            await client.connect()
            resumed = await client.request(
                "thread.resume", {"thread_id": THREAD_ID, "last_seen_seq": 0}
            )
            snapshot = resumed.get("snapshot") or {}
            assert _pending_request_items(snapshot), (
                "reopening Sunday lost the approval the user was about to answer"
            )

            await client.respond_approval(
                thread_id=THREAD_ID,
                request_id=REQUEST_ID,
                decision="approve_once",
            )
            await _wait_for_terminal(client, THREAD_ID)
            assert (work_root / "approved.md").read_text(encoding="utf-8") == "approved\n"
            assert calls["count"] == 2
        finally:
            await client.close()
    finally:
        await second.stop()

