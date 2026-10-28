"""QQ messages enter a selected Sunday session as user turns or guidance."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from qqbot.session_target import SessionTargetClient


class FakeStore:
    def __init__(self) -> None:
        self.messages: list[SimpleNamespace] = []
        self.status = "completed"

    async def list_messages(self, session_id: str):
        return list(self.messages)

    async def get(self, session_id: str):
        return SimpleNamespace(id=session_id, status=self.status)


class FakeRegistry:
    def __init__(self) -> None:
        self.active = ""
        self.guidance: list[tuple] = []
        self.store = None

    def active_run_id(self, session_id: str) -> str:
        return self.active

    def inject_guidance(self, thread_id, text, *, run_id="", guidance_id="", metadata=None):
        self.guidance.append((thread_id, text, run_id, guidance_id))
        if self.store is not None:
            self.store.messages.append(
                SimpleNamespace(id=f"assistant-{len(self.store.messages)}", role="assistant", content="ok")
            )
            self.store.status = "completed"
        self.active = ""
        return True


class FakeContext:
    def __init__(
        self,
        store: FakeStore,
        registry: FakeRegistry,
        calls: list,
        *,
        turn_payload: dict | None = None,
        approval_payload: dict | None = None,
        live_service=None,
        event_bus=None,
    ) -> None:
        self.services = {"session_store": store}
        if live_service is not None:
            self.services["live_turn_service"] = live_service
        self.runtime_task_registry = registry
        self.event_bus = event_bus
        self._calls = calls
        self.turn_payload = turn_payload or {}
        self.approval_payload = approval_payload or {}

    def service(self, name, default=None):
        return self.services.get(name, default)

    def operation_executor(self):
        async def execute(name, payload, metadata=None):
            self._calls.append((name, payload))
            store = self.services["session_store"]
            if name in {"turn.start", "turn.steer"}:
                await asyncio.sleep(0)
                result_payload = dict(self.turn_payload)
                if not result_payload.get("events"):
                    store.messages.append(
                        SimpleNamespace(id=f"assistant-{len(store.messages)}", role="assistant", content="ok")
                    )
                return SimpleNamespace(status="ok", payload=result_payload)
            if name == "approval.respond":
                store.messages.append(
                    SimpleNamespace(id=f"assistant-{len(store.messages)}", role="assistant", content="done")
                )
                return SimpleNamespace(status="ok", payload=dict(self.approval_payload))
            return SimpleNamespace(status="ok", payload={})

        return execute


async def test_idle_target_uses_turn_start() -> None:
    store = FakeStore()
    registry = FakeRegistry()
    calls: list = []
    client = SessionTargetClient(FakeContext(store, registry, calls), timeout_ms=2000)

    result = await client.send(session_id="session-1", text="hello", client_message_id="m1")

    assert result["ok"] is True
    assert result["reply"] == "ok"
    assert [name for name, _ in calls] == ["turn.start"]
    assert calls[0][1]["thread_id"] == "session-1"
    assert calls[0][1]["message"] == "hello"
    assert calls[0][1]["input"] == [{"type": "text", "text": "hello"}]


async def test_running_target_uses_immediate_steering_not_queue() -> None:
    store = FakeStore()
    registry = FakeRegistry()
    registry.active = "session-1:turn:run-1"
    registry.store = store
    store.status = "running"
    calls: list = []
    client = SessionTargetClient(FakeContext(store, registry, calls), timeout_ms=2000)

    result = await client.send(session_id="session-1", text="change it", client_message_id="m2")

    assert result["ok"] is True
    assert registry.guidance == [("session-1", "change it", "session-1:turn:run-1", "m2")]
    assert not any(name.startswith("queue.") for name, _ in calls)


async def test_target_wait_forwards_approval_and_resumes() -> None:
    store = FakeStore()
    registry = FakeRegistry()
    calls: list = []
    request = {
        "request_id": "request-1",
        "tool_call_id": "call-1",
        "tool_name": "run_command",
        "arguments": {"command": "echo hi"},
        "request_kind": "permission",
        "message": "需要授权后才能执行命令：echo hi",
    }
    context = FakeContext(
        store,
        registry,
        calls,
        turn_payload={
            "decision": "wait",
            "events": [{"name": "runtime.approval_request", "payload": request}],
        },
    )
    client = SessionTargetClient(context, timeout_ms=2000)
    seen: list = []

    async def on_wait(item):
        seen.append(item)
        return {"decision": "approve", "guidance": ""}

    result = await client.send(
        session_id="session-1",
        text="do it",
        client_message_id="m3",
        on_wait=on_wait,
    )

    assert result["ok"] is True
    assert result["reply"] == "done"
    assert seen == [request]
    assert [name for name, _ in calls] == ["turn.start", "approval.respond"]
    assert calls[1][1]["request_id"] == "request-1"
    assert calls[1][1]["decision"] == "approve"


async def test_target_wait_without_handler_reports_error() -> None:
    store = FakeStore()
    registry = FakeRegistry()
    calls: list = []
    request = {"request_id": "request-1", "tool_name": "question", "request_kind": "question"}
    context = FakeContext(
        store,
        registry,
        calls,
        turn_payload={
            "decision": "wait",
            "events": [{"name": "runtime.approval_request", "payload": request}],
        },
    )
    client = SessionTargetClient(context, timeout_ms=2000)

    result = await client.send(session_id="session-1", text="ask", client_message_id="m4")

    assert result["ok"] is False
    assert "交互处理器" in result["error"]
    assert [name for name, _ in calls] == ["turn.start"]


def test_approval_request_ignores_resolved_and_keeps_latest() -> None:
    resolved = {"request_id": "r1", "tool_name": "run_command"}
    pending = {"request_id": "r2", "tool_name": "question"}
    payload = {
        "events": [
            {"name": "runtime.approval_request", "payload": resolved},
            {"name": "runtime.approval_response", "payload": {"request_id": "r1"}},
            {"name": "runtime.approval_request", "payload": pending},
        ]
    }
    assert SessionTargetClient._approval_request(payload) == pending
    assert SessionTargetClient._approval_request(
        {"events": [{"name": "runtime.approval_request", "payload": resolved},
                    {"name": "runtime.approval_response", "payload": {"request_id": "r1"}}]}
    ) is None


class FakeLiveService:
    def __init__(self) -> None:
        self.starts: list[dict] = []
        self.approvals: list[dict] = []

    async def start_turn(self, **kwargs):
        self.starts.append(kwargs)
        return {"ok": True, "turn_id": "turn-1", "run_id": "run-1", "result": {}}

    async def respond_approval(self, **kwargs):
        self.approvals.append(kwargs)
        return {"ok": True, "result": {}}


class FakeEventBus:
    def __init__(self) -> None:
        self.queues: dict[str, asyncio.Queue] = {}

    def subscribe(self, session_id: str):
        queue: asyncio.Queue = asyncio.Queue()
        self.queues[session_id] = queue
        return queue

    def unsubscribe(self, session_id: str, queue) -> None:
        if self.queues.get(session_id) is queue:
            self.queues.pop(session_id, None)


async def test_live_target_uses_event_bus_not_agent_turn_start() -> None:
    store = FakeStore()
    registry = FakeRegistry()
    calls: list = []
    live = FakeLiveService()
    bus = FakeEventBus()
    context = FakeContext(store, registry, calls, live_service=live, event_bus=bus)
    client = SessionTargetClient(context, timeout_ms=2000)

    task = asyncio.create_task(
        client.send(session_id="session-1", text="hello", client_message_id="m5")
    )
    await asyncio.sleep(0)
    queue = bus.queues["session-1"]
    await queue.put(
        SimpleNamespace(
            payload={
                "kind": "status",
                "turn_id": "turn-1",
                "run_id": "run-1",
                "payload": {"status": "completed", "message": "live reply"},
            }
        )
    )
    result = await task

    assert result == {"ok": True, "reply": "live reply", "mode": "live"}
    assert live.starts and live.starts[0]["thread_id"] == "session-1"
    assert calls == []


async def test_live_target_forwards_intermediate_agent_text_once() -> None:
    store = FakeStore()
    registry = FakeRegistry()
    calls: list = []
    live = FakeLiveService()
    bus = FakeEventBus()
    context = FakeContext(store, registry, calls, live_service=live, event_bus=bus)
    client = SessionTargetClient(context, timeout_ms=2000)
    replies: list[str] = []

    async def on_reply(text: str) -> None:
        replies.append(text)

    task = asyncio.create_task(
        client.send(
            session_id="session-1",
            text="hello",
            client_message_id="m6",
            on_reply=on_reply,
        )
    )
    await asyncio.sleep(0)
    queue = bus.queues["session-1"]
    await queue.put(
        SimpleNamespace(
            payload={
                "kind": "message",
                "turn_id": "turn-1",
                "run_id": "run-1",
                "item_id": "item-1",
                "status": "completed",
                "payload": {"type": "agentMessage", "content": "中间话"},
            }
        )
    )
    await queue.put(
        SimpleNamespace(
            payload={
                "kind": "status",
                "turn_id": "turn-1",
                "run_id": "run-1",
                "payload": {"status": "completed", "message": "中间话"},
            }
        )
    )
    result = await task

    assert replies == ["中间话"]
    assert result == {"ok": True, "reply": "", "mode": "live"}


async def test_forward_replies_does_not_return_final_twice() -> None:
    store = FakeStore()
    registry = FakeRegistry()
    calls: list = []
    live = FakeLiveService()
    bus = FakeEventBus()
    context = FakeContext(store, registry, calls, live_service=live, event_bus=bus)
    client = SessionTargetClient(context, timeout_ms=2000)

    task = asyncio.create_task(
        client.send(
            session_id="session-1",
            text="hello",
            client_message_id="m7",
            forward_replies=True,
        )
    )
    await asyncio.sleep(0)
    queue = bus.queues["session-1"]
    await queue.put(
        SimpleNamespace(
            payload={
                "kind": "status",
                "turn_id": "turn-1",
                "run_id": "run-1",
                "payload": {"status": "completed", "message": "final"},
            }
        )
    )
    result = await task

    assert result == {"ok": True, "reply": "", "mode": "live"}


async def test_idle_snapshot_ignores_stale_registry_run() -> None:
    class SnapshotLive:
        async def active_turn(self, *, thread_id: str):
            return {"status": "completed", "active_turn_id": ""}

    store = FakeStore()
    registry = FakeRegistry()
    registry.active = "stale-run"
    calls: list = []
    client = SessionTargetClient(
        FakeContext(store, registry, calls, live_service=SnapshotLive()),
        timeout_ms=2000,
    )

    assert await client._active_turn("session-1") == ""


async def test_busy_error_uses_payload_active_run_id() -> None:
    class BusyLive:
        async def active_turn(self, *, thread_id: str):
            return {"status": "completed", "active_turn_id": ""}

        async def start_turn(self, *, thread_id: str, text: str, client_message_id: str):
            return {
                "ok": False,
                "error": "session has an active turn",
                # Older hosts put the id under data; newer hosts also mirror it
                # at the top level. The plugin must accept both shapes.
                "data": {"active_run_id": "session-1:turn:run-1"},
            }

    store = FakeStore()
    registry = FakeRegistry()
    registry.store = store
    calls: list = []
    client = SessionTargetClient(
        FakeContext(store, registry, calls, live_service=BusyLive()),
        timeout_ms=2000,
    )

    result = await client.send(session_id="session-1", text="change it", client_message_id="m3")

    assert result["ok"] is True
    assert registry.guidance == [
        ("session-1", "change it", "session-1:turn:run-1", "m3")
    ]


async def test_idle_status_ignores_stale_registry_without_live_service() -> None:
    store = FakeStore()
    store.status = "completed"
    registry = FakeRegistry()
    registry.active = "stale-run"
    calls: list = []
    client = SessionTargetClient(FakeContext(store, registry, calls), timeout_ms=2000)

    assert await client._active_turn("session-1") == ""


async def test_deliver_message_replaces_plugin_state_inference() -> None:
    store = FakeStore()

    class DeliverLive:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        async def deliver_message(self, *, thread_id: str, text: str, client_message_id: str):
            self.calls.append(
                {"thread_id": thread_id, "text": text, "client_message_id": client_message_id}
            )
            store.messages.append(
                SimpleNamespace(id="assistant-delivered", role="assistant", content="ok")
            )
            store.status = "completed"
            return {"ok": True, "mode": "steered", "turn_id": "session-1:turn:run-1"}

    registry = FakeRegistry()
    registry.active = "stale-run"
    calls: list = []
    live = DeliverLive()
    client = SessionTargetClient(
        FakeContext(store, registry, calls, live_service=live),
        timeout_ms=2000,
    )

    result = await client.send(session_id="session-1", text="123456", client_message_id="m4")

    assert result["ok"] is True
    assert result["reply"] == "ok"
    assert live.calls == [
        {"thread_id": "session-1", "text": "123456", "client_message_id": "m4"}
    ]
    assert registry.guidance == []
