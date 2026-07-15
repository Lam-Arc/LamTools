from __future__ import annotations

import asyncio

import pytest

from lamtools_core.app.live_client import CoreAppServerClient


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.inbound: asyncio.Queue[dict | None] = asyncio.Queue()
        self.closed = False

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)

    async def close(self) -> None:
        self.closed = True
        await self.inbound.put(None)

    def __aiter__(self):
        return self

    async def __anext__(self):
        item = await self.inbound.get()
        if item is None:
            raise StopAsyncIteration
        return item


async def wait_for_sent(websocket: FakeWebSocket, count: int) -> None:
    for _ in range(50):
        if len(websocket.sent) >= count:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"expected at least {count} sent messages, got {len(websocket.sent)}")


@pytest.mark.asyncio
async def test_core_app_server_client_connects_initializes_and_resumes_thread():
    websocket = FakeWebSocket()

    async def connect(url: str):
        assert url == "ws://core.test/api/core/app-server"
        return websocket

    client = CoreAppServerClient(
        "http://core.test",
        path="/api/core/app-server",
        client_info={"name": "core_cli", "version": "0.1.0"},
        websocket_connect=connect,
    )
    connect_task = asyncio.create_task(client.connect(thread_id="thread-1", last_seen_seq=7))
    await wait_for_sent(websocket, 1)
    assert websocket.sent[0] == {
        "id": 1,
        "method": "initialize",
        "params": {
            "clientInfo": {"name": "core_cli", "version": "0.1.0"},
            "threadId": "thread-1",
            "lastSeenSeq": 7,
        },
    }
    await websocket.inbound.put({"id": 1, "result": {"protocolVersion": "core.app_server.v1"}})
    await wait_for_sent(websocket, 2)
    assert websocket.sent[1] == {"id": 2, "method": "initialized", "params": {}}
    await websocket.inbound.put({"id": 2, "result": {"ok": True}})
    await wait_for_sent(websocket, 3)
    assert websocket.sent[2] == {
        "id": 3,
        "method": "thread/resume",
        "params": {"thread_id": "thread-1", "last_seen_seq": 7},
    }
    await websocket.inbound.put({
        "id": 3,
        "result": {
            "events": [
                {"event_id": "event-1", "thread_id": "thread-1", "seq": 8, "method": "item/started", "payload": {}}
            ]
        },
    })
    await connect_task

    event = await asyncio.wait_for(client._events.get(), timeout=1)
    assert event["data"]["event_id"] == "event-1"
    await client.close()


@pytest.mark.asyncio
async def test_core_app_server_client_deduplicates_response_and_socket_events():
    client = CoreAppServerClient("http://core.test")
    event = {
        "event_id": "event-1",
        "seq": 1,
        "thread_id": "thread-1",
        "method": "item/started",
        "payload": {"type": "userMessage"},
    }

    await client.put_app_server_event(event)
    await client.put_app_server_event(dict(event))

    queued = await asyncio.wait_for(client._events.get(), timeout=1)
    assert queued == {"event": "app_server_event", "data": event}
    assert client._events.empty()


@pytest.mark.asyncio
async def test_core_app_server_client_guides_queue_item_with_stable_id():
    client = CoreAppServerClient("http://core.test")
    calls: list[tuple[str, dict]] = []

    async def request(method: str, params: dict):
        calls.append((method, params))
        return {"applied": True, "reason": ""}

    client.request = request  # type: ignore[method-assign]
    result = await client.guide_queue_input(
        thread_id="thread-1",
        turn_id="turn-1",
        queue_item_id="queue-1",
        text="guide now",
    )

    assert result == {"applied": True, "reason": ""}
    assert calls == [("queue/guide", {
        "thread_id": "thread-1",
        "turn_id": "turn-1",
        "queue_item_id": "queue-1",
        "client_message_id": "queue-guide:queue-1",
        "text": "guide now",
    })]


@pytest.mark.asyncio
@pytest.mark.parametrize("event_count", [1201, 2501])
async def test_core_app_server_client_consumes_all_resume_pages_before_live_events(event_count: int):
    class PagedWebSocket(FakeWebSocket):
        async def send_json(self, payload: dict) -> None:
            await super().send_json(payload)
            method = payload["method"]
            if method == "initialize":
                await self.inbound.put({"id": payload["id"], "result": {"protocolVersion": "core.app_server.v1"}})
            elif method == "initialized":
                await self.inbound.put({"id": payload["id"], "result": {"ok": True}})
            elif method == "thread/resume":
                after = payload["params"]["last_seen_seq"]
                upper = min(after + 500, event_count)
                await self.inbound.put({
                    "id": payload["id"],
                    "result": {
                        "events": [
                            {"event_id": f"event-{seq}", "thread_id": "thread-1", "seq": seq, "method": "core/runItem", "payload": {}}
                            for seq in range(after + 1, upper + 1)
                        ],
                        "has_more": upper < event_count,
                        "next_after_seq": upper,
                        "snapshot": {"thread_id": "thread-1", "snapshot_seq": event_count},
                    },
                })

    websocket = PagedWebSocket()

    async def connect(_url: str):
        return websocket

    client = CoreAppServerClient("http://core.test", websocket_connect=connect)
    await client.connect(thread_id="thread-1")
    events = [await asyncio.wait_for(client._events.get(), timeout=1) for _ in range(event_count)]

    assert [event["data"]["seq"] for event in events] == list(range(1, event_count + 1))
    assert [payload["params"]["last_seen_seq"] for payload in websocket.sent if payload["method"] == "thread/resume"] == list(range(0, event_count, 500))
    await client.close()


@pytest.mark.asyncio
async def test_core_app_server_client_uses_caller_stable_client_message_id():
    client = CoreAppServerClient("http://core.test")
    calls: list[tuple[str, dict]] = []

    async def request(method: str, params: dict):
        calls.append((method, params))
        return {}

    client.request = request  # type: ignore[method-assign]
    await client.start_turn(
        thread_id="thread-1",
        input_items=[{"type": "text", "text": "hello"}],
        client_message_id="turn-message-1",
    )

    assert calls[0][1]["client_message_id"] == "turn-message-1"


@pytest.mark.asyncio
async def test_core_app_server_client_execute_command_returns_result_and_queues_response_events():
    class CommandWebSocket(FakeWebSocket):
        async def send_json(self, payload: dict) -> None:
            await super().send_json(payload)
            method = payload["method"]
            if method == "initialize":
                result = {"protocolVersion": "core.app_server.v1"}
            elif method == "initialized":
                result = {"ok": True}
            else:
                result = {
                    "result": {
                        "status": "not_needed",
                        "reason": "no_gain",
                        "before_tokens": 1200,
                        "after_tokens": 1200,
                    },
                    "events": [{
                        "event_id": "compact-final",
                        "thread_id": "thread-1",
                        "seq": 9,
                        "method": "core/runItem",
                        "payload": {
                            "item_id": "compact-1",
                            "kind": "message",
                            "status": "completed",
                            "payload": {
                                "type": "compaction",
                                "compaction_status": "not_needed",
                                "reason": "no_gain",
                            },
                        },
                    }],
                }
            await self.inbound.put({"id": payload["id"], "result": result})

    websocket = CommandWebSocket()

    async def connect(_url: str):
        return websocket

    client = CoreAppServerClient("http://core.test", websocket_connect=connect)
    await client.connect()

    result = await client.execute_command(thread_id="thread-1", command="compact")
    event = await asyncio.wait_for(client._events.get(), timeout=1)

    assert result == {
        "status": "not_needed",
        "reason": "no_gain",
        "before_tokens": 1200,
        "after_tokens": 1200,
    }
    assert websocket.sent[-1]["params"]["include_snapshot"] is False
    assert event["data"]["event_id"] == "compact-final"
    await client.close()


@pytest.mark.asyncio
async def test_core_app_server_client_sends_live_turn_options_and_queue_operations():
    client = CoreAppServerClient("http://core.test")
    calls: list[tuple[str, dict]] = []

    async def request(method: str, params: dict):
        calls.append((method, params))
        return {"events": [], "operation": method}

    client.request = request  # type: ignore[method-assign]

    await client.start_turn(
        thread_id="thread-1",
        input_items=[{"type": "text", "text": "start"}],
        thinking_enabled=False,
        thinking_budget=512,
        approval_policy="auto_approve",
        client_message_id="message-1",
    )
    steered = await client.steer_turn(
        thread_id="thread-1",
        turn_id="turn-1",
        input_items=[{"type": "text", "text": "steer"}],
    )
    await client.create_queue_input(
        thread_id="thread-1",
        input_items=[{"type": "text", "text": "queued"}],
        queue_item_id="queue-1",
        client_message_id="queue-message-1",
    )
    await client.update_queue_input(thread_id="thread-1", queue_item_id="queue-1", text="updated")
    await client.delete_queue_input(thread_id="thread-1", queue_item_id="queue-1")

    assert steered["operation"] == "turn/steer"
    assert calls == [
        ("turn.start", {
            "thread_id": "thread-1", "client_message_id": "message-1",
            "input": [{"type": "text", "text": "start"}], "work_root": "", "mode": "",
            "thinking_enabled": False, "thinking_budget": 512, "approval_policy": "auto_approve",
        }),
        ("turn/steer", {
            "thread_id": "thread-1", "turn_id": "turn-1",
            "client_message_id": calls[1][1]["client_message_id"],
            "input": [{"type": "text", "text": "steer"}],
        }),
        ("queue/create", {
            "thread_id": "thread-1", "input": [{"type": "text", "text": "queued"}],
            "queue_item_id": "queue-1", "client_message_id": "queue-message-1", "mode": "next_turn",
        }),
        ("queue/update", {"thread_id": "thread-1", "queue_item_id": "queue-1", "text": "updated"}),
        ("queue/delete", {"thread_id": "thread-1", "queue_item_id": "queue-1"}),
    ]


@pytest.mark.asyncio
async def test_core_app_server_client_passes_configured_path_and_bearer_token_to_connector():
    calls: list[tuple[str, dict[str, str]]] = []

    async def connect(url: str, *, headers: dict[str, str]):
        calls.append((url, headers))
        return FakeWebSocket()

    client = CoreAppServerClient(
        "https://core.test",
        path="/custom/live",
        token="secret-token",
        websocket_connect=connect,
    )
    await client._connect_websocket()

    assert calls == [("wss://core.test/custom/live", {"Authorization": "Bearer secret-token"})]
