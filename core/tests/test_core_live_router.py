from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, WebSocketDisconnect
from fastapi.testclient import TestClient
from sqlalchemy import DateTime, Integer, JSON, String, UniqueConstraint
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from lamtools_core.app import CoreAppSnapshotProjector, OperationCatalog, OperationRequest, OperationResult
from lamtools_core.app.event_store import SqlAlchemyAppEventStore
from lamtools_core.app.live_hub import CoreAppEventGap, CoreAppEventHub
from lamtools_core.app.live_operations import CoreLiveContext, CoreLiveOperationOutcome
from lamtools_core.app.live_operations import handle_thread_resume_operation
from lamtools_core.app.live_protocol import rpc_result
from lamtools_core.app.live_router import (
    CoreLiveConnection,
    CoreLiveConnectionAdapter,
    _handle_core_client_response,
    create_core_live_router,
)
from lamtools_core.app.snapshot_store import SqlAlchemyThreadSnapshotStore


class Base(DeclarativeBase):
    pass


class AppEventRow(Base):
    __tablename__ = "test_core_live_router_app_events"
    __table_args__ = (
        UniqueConstraint("thread_id", "seq", name="uq_test_core_live_router_app_events_thread_seq"),
    )

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    turn_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    item_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    parent_item_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    client_message_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    method: Mapped[str] = mapped_column(String(100), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)


class ThreadSnapshotRow(Base):
    __tablename__ = "test_core_live_router_thread_snapshots"

    thread_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    snapshot_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)


class SnapshotItemRow(Base):
    __tablename__ = "test_core_live_router_thread_snapshot_items"

    thread_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    item_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    item_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)



class DummyWebSocket:
    def __init__(self):
        self.close_calls = []

    async def accept(self):
        return None

    async def send_json(self, message):
        return None

    async def close(self, code=1000, reason=""):
        self.close_calls.append((code, reason))


def test_core_live_connection_processes_interrupt_while_long_command_is_running() -> None:
    async def run() -> None:
        class QueueWebSocket(DummyWebSocket):
            def __init__(self) -> None:
                super().__init__()
                self.incoming: asyncio.Queue[dict | None] = asyncio.Queue()
                self.sent: list[dict] = []

            async def receive_json(self):
                message = await self.incoming.get()
                if message is None:
                    raise WebSocketDisconnect()
                return message

            async def send_json(self, message):
                self.sent.append(message)

        class Hub:
            def subscribe(self, _thread_id: str):
                return asyncio.Queue()

            def unsubscribe(self, _thread_id: str, _subscription) -> None:
                return None

        command_started = asyncio.Event()
        command_release = asyncio.Event()
        interrupt_handled = asyncio.Event()

        class Host:
            def operation_handlers(self):
                return {"command.execute", "turn.cancel"}

            async def execute(self, method, *, request_id, params, context):
                del params, context
                if method == "command.execute":
                    command_started.set()
                    await command_release.wait()
                elif method == "turn.cancel":
                    interrupt_handled.set()
                    command_release.set()
                return CoreLiveOperationOutcome(
                    response={"id": request_id, "result": {"ok": True}},
                )

        websocket = QueueWebSocket()
        context = SimpleNamespace(
            host=Host(),
            hub=Hub(),
            operations=SimpleNamespace(has=lambda _method: False),
        )
        connection = CoreLiveConnection(websocket, context=context)
        connection.initialized = True
        serving = asyncio.create_task(connection.run())
        await websocket.incoming.put({
            "id": 1,
            "method": "command.execute",
            "params": {"thread_id": "thread-1", "command": "compact"},
        })
        await command_started.wait()

        await websocket.incoming.put({
            "id": 2,
            "method": "turn/interrupt",
            "params": {"thread_id": "thread-1", "turn_id": "turn-command"},
        })
        await asyncio.wait_for(interrupt_handled.wait(), timeout=0.1)

        await websocket.incoming.put(None)
        await serving

    asyncio.run(run())


def test_core_live_client_response_uses_approval_operation_and_sends_snapshot() -> None:
    async def run() -> None:
        catalog = OperationCatalog()

        async def respond(request: OperationRequest) -> OperationResult:
            assert request.payload == {
                "request_id": "request-1",
                "thread_id": "",
                "decision": "approve",
                "guidance": "yes",
            }
            return OperationResult(
                name=request.name,
                payload={"snapshot": {"thread_id": "thread-1", "snapshot_seq": 7}},
            )

        catalog.register("approval.respond", respond)
        connection = CoreLiveConnection(
            DummyWebSocket(),
            context=SimpleNamespace(operations=catalog),
            adapter=CoreLiveConnectionAdapter(handle_client_response=_handle_core_client_response),
        )

        await connection.handle_raw(
            {"id": "request-1", "result": {"decision": "approve_once", "guidance": "yes"}}
        )

        notification = await connection.outbound.get()
        assert notification["method"] == "thread/snapshot"
        assert notification["params"]["snapshot_seq"] == 7

    asyncio.run(run())


def test_core_live_connection_closes_on_hub_gap_signal() -> None:
    async def run() -> None:
        websocket = DummyWebSocket()
        connection = CoreLiveConnection(websocket, context=SimpleNamespace())
        connection.subscription = asyncio.Queue()
        await connection.subscription.put(CoreAppEventGap(thread_id="thread-1"))

        await asyncio.wait_for(connection._hub_reader(), timeout=0.1)

        assert websocket.close_calls == [(1013, "Event stream overflow; reconnect to resume.")]

    asyncio.run(run())


def test_core_live_connection_sends_run_item_without_snapshot_reload() -> None:
    async def run() -> None:
        connection = CoreLiveConnection(DummyWebSocket(), context=SimpleNamespace())
        connection.subscription = asyncio.Queue()
        await connection.subscription.put({
            "event_id": "delta-1",
            "thread_id": "thread-1",
            "seq": 0,
            "method": "core/runItem",
            "payload": {},
            "created_at": "2026-07-15T00:00:00+00:00",
            "transient": False,
        })
        reader = asyncio.create_task(connection._hub_reader())
        try:
            notification = await asyncio.wait_for(connection.outbound.get(), timeout=0.1)
            assert notification["method"] == "core/runItem"
            assert notification["params"]["method"] == "core/runItem"
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(connection.outbound.get(), timeout=0.02)
        finally:
            reader.cancel()
            with pytest.raises(asyncio.CancelledError):
                await reader

    asyncio.run(run())


def test_core_live_connection_skips_snapshot_for_non_boundary_event() -> None:
    async def run() -> None:
        class BoomSessionFactory:
            async def __aenter__(self):
                raise AssertionError("snapshot must not be loaded for a non-boundary event")

            async def __aexit__(self, *args):
                return None

        connection = CoreLiveConnection(
            DummyWebSocket(),
            context=SimpleNamespace(session_factory=BoomSessionFactory()),
        )
        connection.subscription = asyncio.Queue()
        await connection.subscription.put({
            "event_id": "title-1",
            "thread_id": "thread-1",
            "seq": 0,
            "method": "session/updated",
            "payload": {"session": {"title": "renamed"}},
            "created_at": "2026-07-15T00:00:00+00:00",
            "transient": False,
        })
        reader = asyncio.create_task(connection._hub_reader())
        try:
            notification = await asyncio.wait_for(connection.outbound.get(), timeout=0.1)
            assert notification["method"] == "session/updated"
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(connection.outbound.get(), timeout=0.02)
        finally:
            reader.cancel()
            with pytest.raises(asyncio.CancelledError):
                await reader

    asyncio.run(run())


def test_core_live_connection_sends_throttled_snapshot_for_boundary_event() -> None:
    async def run() -> None:
        class SessionFactory:
            async def __aenter__(self):
                return object()

            async def __aexit__(self, *args):
                return None

        class SnapshotStore:
            def __init__(self):
                self.loads = 0

            async def load(self, _db, thread_id: str):
                self.loads += 1
                return {"thread_id": thread_id, "snapshot_seq": 1}

        snapshot_store = SnapshotStore()
        connection = CoreLiveConnection(
            DummyWebSocket(),
            context=SimpleNamespace(
                session_factory=SessionFactory,
                snapshot_store=snapshot_store,
            ),
        )
        connection.subscription = asyncio.Queue()
        # Two boundary events back-to-back: the first triggers a snapshot, the
        # second is throttled (SNAPSHOT_MIN_INTERVAL_SECONDS=1s).
        for seq, event_id in [(0, "queue-1"), (1, "queue-2")]:
            await connection.subscription.put({
                "event_id": event_id,
                "thread_id": "thread-1",
                "seq": seq,
                "method": "queue/itemAccepted",
                "payload": {},
                "created_at": "2026-07-15T00:00:00+00:00",
                "transient": False,
            })
        reader = asyncio.create_task(connection._hub_reader())
        try:
            first = await asyncio.wait_for(connection.outbound.get(), timeout=0.1)
            assert first["method"] == "queue/itemAccepted"
            second = await asyncio.wait_for(connection.outbound.get(), timeout=0.1)
            assert second["method"] == "thread/snapshot"
            assert second["params"]["thread_id"] == "thread-1"
            third = await asyncio.wait_for(connection.outbound.get(), timeout=0.1)
            assert third["method"] == "queue/itemAccepted"
            # Second boundary event within the throttle window: no snapshot.
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(connection.outbound.get(), timeout=0.02)
            assert snapshot_store.loads == 1
        finally:
            reader.cancel()
            with pytest.raises(asyncio.CancelledError):
                await reader

    asyncio.run(run())


def test_core_live_connection_drops_message_when_outbound_full() -> None:
    async def run() -> None:
        websocket = DummyWebSocket()
        connection = CoreLiveConnection(websocket, context=SimpleNamespace(), outbound_limit=1)
        await connection.outbound.put({"id": "first"})
        await connection._send({"id": "second"})
        assert connection.outbound.qsize() == 1
        assert websocket.close_calls == []
        message = connection.outbound.get_nowait()
        assert message["id"] == "first"

    asyncio.run(run())


def _run_item_event(event_id: str, delta: str, *, kind: str = "message") -> dict:
    return {
        "event_id": event_id,
        "thread_id": "thread-1",
        "seq": 0,
        "method": "core/runItem",
        "payload": {
            "item_id": "item-1",
            "kind": kind,
            "event_id": event_id,
            "payload": {"delta": delta},
        },
        "created_at": "2026-07-15T00:00:00+00:00",
        "transient": False,
    }


def test_core_live_connection_coalesces_run_item_deltas_into_one_message() -> None:
    async def run() -> None:
        connection = CoreLiveConnection(DummyWebSocket(), context=SimpleNamespace())
        connection.subscription = asyncio.Queue()
        connection._run_item_flush_interval = 1.0  # window open long enough to prove buffering
        for i in range(5):
            await connection.subscription.put(_run_item_event(f"delta-{i + 1}", f"chunk{i + 1}"))
        reader = asyncio.create_task(connection._hub_reader())
        try:
            # No message may hit the wire while the coalescing window is open.
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(connection.outbound.get(), timeout=0.05)
            await connection._flush_run_item_buffer()
            notification = await asyncio.wait_for(connection.outbound.get(), timeout=0.1)
            assert notification["method"] == "core/runItem"
            params = notification["params"]
            value = params["payload"]
            assert value["item_id"] == "item-1"
            assert value["kind"] == "message"
            assert value["payload"]["delta"] == "chunk1chunk2chunk3chunk4chunk5"
            assert value["event_id"] == "delta-1"
            assert value["_coalesced_event_ids"] == [f"delta-{i}" for i in range(1, 6)]
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(connection.outbound.get(), timeout=0.02)
        finally:
            reader.cancel()
            if connection._run_item_flush_task is not None:
                connection._run_item_flush_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await reader

    asyncio.run(run())


def test_core_live_connection_sends_non_delta_run_item_immediately_after_buffered_deltas() -> None:
    async def run() -> None:
        connection = CoreLiveConnection(DummyWebSocket(), context=SimpleNamespace())
        connection.subscription = asyncio.Queue()
        connection._run_item_flush_interval = 10.0  # never flushes on its own
        await connection.subscription.put(_run_item_event("delta-1", "hello"))
        await connection.subscription.put(_run_item_event("delta-2", " world"))
        await connection.subscription.put({
            "event_id": "result-1",
            "thread_id": "thread-1",
            "seq": 0,
            "method": "core/runItem",
            "payload": {"item_id": "item-1", "kind": "tool_result", "payload": {"ok": True}},
            "created_at": "2026-07-15T00:00:00+00:00",
            "transient": False,
        })
        reader = asyncio.create_task(connection._hub_reader())
        try:
            merged = await asyncio.wait_for(connection.outbound.get(), timeout=0.1)
            assert merged["params"]["payload"]["payload"]["delta"] == "hello world"
            tool = await asyncio.wait_for(connection.outbound.get(), timeout=0.1)
            assert tool["params"]["payload"]["kind"] == "tool_result"
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(connection.outbound.get(), timeout=0.02)
        finally:
            reader.cancel()
            with pytest.raises(asyncio.CancelledError):
                await reader

    asyncio.run(run())


def test_core_live_connection_flushes_run_item_buffer_before_other_events() -> None:
    async def run() -> None:
        class SessionFactory:
            async def __aenter__(self):
                return object()

            async def __aexit__(self, *args):
                return None

        class SnapshotStore:
            async def load(self, _db, thread_id: str):
                return {"thread_id": thread_id, "snapshot_seq": 1}

        connection = CoreLiveConnection(
            DummyWebSocket(),
            context=SimpleNamespace(
                session_factory=SessionFactory,
                snapshot_store=SnapshotStore(),
            ),
        )
        connection.subscription = asyncio.Queue()
        connection._run_item_flush_interval = 10.0  # never flushes on its own
        await connection.subscription.put(_run_item_event("delta-1", "partial"))
        await connection.subscription.put({
            "event_id": "interrupt-1",
            "thread_id": "thread-1",
            "seq": 0,
            "method": "turn/interrupted",
            "payload": {"turn_id": "turn-1"},
            "created_at": "2026-07-15T00:00:00+00:00",
            "transient": False,
        })
        reader = asyncio.create_task(connection._hub_reader())
        try:
            merged = await asyncio.wait_for(connection.outbound.get(), timeout=0.1)
            assert merged["method"] == "core/runItem"
            assert merged["params"]["payload"]["payload"]["delta"] == "partial"
            interrupt = await asyncio.wait_for(connection.outbound.get(), timeout=0.1)
            assert interrupt["method"] == "turn/interrupted"
            snapshot = await asyncio.wait_for(connection.outbound.get(), timeout=0.1)
            assert snapshot["method"] == "thread/snapshot"
        finally:
            reader.cancel()
            with pytest.raises(asyncio.CancelledError):
                await reader

    asyncio.run(run())


def test_core_live_connection_does_not_resend_snapshot_after_rpc_response() -> None:
    async def run() -> None:
        class Hub:
            def subscribe(self, _thread_id: str):
                return asyncio.Queue()

            def unsubscribe(self, _thread_id: str, _subscription) -> None:
                return None

        class Host:
            def operation_handlers(self):
                return set()

            async def execute(self, method, *, request_id, params, context):
                return CoreLiveOperationOutcome(
                    response=rpc_result(request_id, {"snapshot": {"thread_id": "thread-1", "snapshot_seq": 1}})
                )

        class Operations:
            def has(self, method):
                return True

        connection = CoreLiveConnection(
            DummyWebSocket(),
            context=SimpleNamespace(host=Host(), operations=Operations(), hub=Hub()),
        )
        connection.initialized = True
        await connection.handle_raw({
            "id": 1,
            "method": "thread.read",
            "params": {"thread_id": "thread-1"},
        })
        response = await asyncio.wait_for(connection.outbound.get(), timeout=0.1)
        assert response["id"] == 1
        assert response["result"]["snapshot"]["thread_id"] == "thread-1"
        # The response already carries result.snapshot — no duplicate
        # thread/snapshot notification may follow.
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(connection.outbound.get(), timeout=0.02)

    asyncio.run(run())


def test_core_live_resume_response_exposes_page_cursor() -> None:
    class SessionFactory:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *args):
            return None

    class Persistence:
        async def list_after(self, _db, *, thread_id: str, after_seq: int, limit: int = 500):
            assert thread_id == "thread-1"
            assert limit == 500
            return [
                SimpleNamespace(seq=seq, to_dict=lambda seq=seq: {"event_id": f"event-{seq}", "seq": seq})
                for seq in range(after_seq + 1, min(after_seq + limit, 1201) + 1)
            ]

        async def load(self, _db, thread_id: str):
            return {"thread_id": thread_id, "snapshot_seq": 1201}

    async def run() -> dict:
        outcome = await handle_thread_resume_operation(
            request_id=1,
            params={"thread_id": "thread-1", "last_seen_seq": 0},
            context=SimpleNamespace(session_factory=SessionFactory, persistence=Persistence()),
        )
        return outcome.response["result"]

    result = asyncio.run(run())

    assert len(result["events"]) == 500
    assert result["has_more"] is True
    assert result["next_after_seq"] == 500


def test_core_live_router_accepts_turn_start_over_websocket(tmp_path):
    async def make_context() -> CoreLiveContext:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'core-live-router.db'}", future=True)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        operations = OperationCatalog()

        async def turn_start(_request):
            return OperationResult(name="turn.start")

        operations.register("turn.start", turn_start)
        return CoreLiveContext(
            session_factory=session_factory,
            event_store=SqlAlchemyAppEventStore(AppEventRow, protocol_version="core.app_server.v1"),
            snapshot_store=SqlAlchemyThreadSnapshotStore(
                ThreadSnapshotRow,
                item_model=SnapshotItemRow,
                projector=CoreAppSnapshotProjector(member_defaults={"queue": []}),
            ),
            operations=operations,
            hub=CoreAppEventHub(),
        )

    app = FastAPI()
    app.include_router(create_core_live_router(make_context), prefix="/api/core")
    client = TestClient(app)

    with client.websocket_connect("/api/core/app-server") as websocket:
        websocket.send_json({
            "id": 1,
            "method": "initialize",
            "params": {"clientInfo": {"name": "test"}},
        })
        initialized = websocket.receive_json()
        assert initialized["result"]["protocolVersion"] == "core.app_server.v1"

        websocket.send_json({
            "id": 2,
            "method": "turn/start",
            "params": {
                "thread_id": "thread-1",
                "client_message_id": "client-1",
                "input": [{"type": "text", "text": "hello"}],
            },
        })
        accepted = None
        for _ in range(9):
            message = websocket.receive_json()
            if message.get("id") == 2:
                accepted = message
            if accepted is not None:
                break

        assert accepted is not None
        assert accepted["result"]["snapshot"]["status"] == "running"
        assert accepted["result"]["snapshot"]["thread_id"] == "thread-1"
        # No separate thread/snapshot notification: the RPC response already
        # carries result.snapshot, and re-sending it doubled snapshot traffic.
        assert all(message.get("method") != "thread/snapshot" for message in [accepted])


def test_core_live_router_accepts_initialized_ack_from_core_client(tmp_path):
    async def make_context() -> CoreLiveContext:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'core-live-router-initialized.db'}", future=True)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        return CoreLiveContext(
            session_factory=session_factory,
            event_store=SqlAlchemyAppEventStore(AppEventRow, protocol_version="core.app_server.v1"),
            snapshot_store=SqlAlchemyThreadSnapshotStore(
                ThreadSnapshotRow,
                item_model=SnapshotItemRow,
                projector=CoreAppSnapshotProjector(member_defaults={"queue": []}),
            ),
            operations=OperationCatalog(),
            hub=CoreAppEventHub(),
        )

    app = FastAPI()
    app.include_router(create_core_live_router(make_context), prefix="/api/core")
    client = TestClient(app)

    with client.websocket_connect("/api/core/app-server") as websocket:
        websocket.send_json({
            "id": 1,
            "method": "initialize",
            "params": {"clientInfo": {"name": "core_cli"}},
        })
        websocket.receive_json()

        websocket.send_json({"id": 2, "method": "initialized", "params": {}})
        acknowledged = websocket.receive_json()

    assert acknowledged == {"id": 2, "result": {"ok": True}}


def test_core_live_router_dispatches_catalog_operations(tmp_path):
    async def make_context() -> CoreLiveContext:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'core-live-router-catalog.db'}", future=True)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        operations = OperationCatalog()

        async def approval_respond(request: OperationRequest) -> OperationResult:
            return OperationResult(
                name=request.name,
                payload={
                    "decision": "approved",
                    "snapshot": {
                        "thread_id": request.payload["thread_id"],
                        "snapshot_seq": 1,
                        "status": "running",
                    },
                },
            )

        operations.register("approval.respond", approval_respond)
        return CoreLiveContext(
            session_factory=session_factory,
            event_store=SqlAlchemyAppEventStore(AppEventRow, protocol_version="core.app_server.v1"),
            snapshot_store=SqlAlchemyThreadSnapshotStore(
                ThreadSnapshotRow,
                item_model=SnapshotItemRow,
                projector=CoreAppSnapshotProjector(member_defaults={"queue": []}),
            ),
            operations=operations,
            hub=CoreAppEventHub(),
        )

    app = FastAPI()
    app.include_router(create_core_live_router(make_context), prefix="/api/core")
    client = TestClient(app)

    with client.websocket_connect("/api/core/app-server") as websocket:
        websocket.send_json({
            "id": 1,
            "method": "initialize",
            "params": {"clientInfo": {"name": "test"}},
        })
        websocket.receive_json()

        websocket.send_json({
            "id": 2,
            "method": "approval/respond",
            "params": {
                "thread_id": "thread-approval",
                "request_id": "request-approval",
                "action": "approve",
            },
        })
        response = websocket.receive_json()

        assert response["id"] == 2
        assert response["result"]["decision"] == "approved"
        assert response["result"]["snapshot"]["thread_id"] == "thread-approval"


def test_core_live_router_delegates_context_operations_to_the_host(tmp_path) -> None:
    async def run() -> None:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'core-live-router-host-dispatch.db'}", future=True)
        async with engine.begin() as db_connection:
            await db_connection.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        operations = OperationCatalog()

        async def command_catalog(request: OperationRequest) -> OperationResult:
            return OperationResult(name=request.name, payload={"commands": []})

        operations.register("command.catalog", command_catalog)
        context = CoreLiveContext(
            session_factory=session_factory,
            event_store=SqlAlchemyAppEventStore(AppEventRow, protocol_version="core.app_server.v1"),
            snapshot_store=SqlAlchemyThreadSnapshotStore(
                ThreadSnapshotRow,
                item_model=SnapshotItemRow,
                projector=CoreAppSnapshotProjector(member_defaults={"queue": []}),
            ),
            operations=operations,
            hub=CoreAppEventHub(),
        )
        calls: list[str] = []
        original_execute = context.host.execute

        async def observe_execute(name, **kwargs):
            calls.append(name)
            return await original_execute(name, **kwargs)

        context.host.execute = observe_execute
        connection = CoreLiveConnection(DummyWebSocket(), context=context)
        connection.initialized = True
        await connection.handle_raw({"id": 1, "method": "command.catalog", "params": {}})

        response = await connection.outbound.get()
        assert response == {"id": 1, "result": {"commands": []}}
        assert calls == ["command.catalog"]
        await engine.dispose()

    asyncio.run(run())


def test_core_live_connection_adapter_handles_member_client_response(tmp_path):
    async def make_context() -> CoreLiveContext:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'core-live-router-adapter.db'}", future=True)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        return CoreLiveContext(
            session_factory=session_factory,
            event_store=SqlAlchemyAppEventStore(AppEventRow, protocol_version="core.app_server.v1"),
            snapshot_store=SqlAlchemyThreadSnapshotStore(
                ThreadSnapshotRow,
                item_model=SnapshotItemRow,
                projector=CoreAppSnapshotProjector(member_defaults={"queue": []}),
            ),
            operations=OperationCatalog(),
            hub=CoreAppEventHub(),
        )

    async def handle_client_response(connection: CoreLiveConnection, raw: dict) -> bool:
        if "result" not in raw:
            return False
        await connection.send({"method": "member/response", "params": {"id": raw["id"]}})
        return True

    import asyncio

    async def run() -> None:
        context = await make_context()
        connection = CoreLiveConnection(
            DummyWebSocket(),
            context=context,
            adapter=CoreLiveConnectionAdapter(handle_client_response=handle_client_response),
        )
        await connection.handle_raw({"id": "request-1", "result": {"decision": "approve"}})

        message = await connection.outbound.get()
        assert message == {"method": "member/response", "params": {"id": "request-1"}}

    asyncio.run(run())


def test_core_live_connection_adapter_handles_member_operation_request(tmp_path):
    async def make_context() -> CoreLiveContext:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'core-live-router-member-op.db'}", future=True)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        return CoreLiveContext(
            session_factory=session_factory,
            event_store=SqlAlchemyAppEventStore(AppEventRow, protocol_version="core.app_server.v1"),
            snapshot_store=SqlAlchemyThreadSnapshotStore(
                ThreadSnapshotRow,
                item_model=SnapshotItemRow,
                projector=CoreAppSnapshotProjector(member_defaults={"queue": []}),
            ),
            operations=OperationCatalog(),
            hub=CoreAppEventHub(),
        )

    async def handle_operation_request(connection: CoreLiveConnection, request) -> bool:
        if request.method != "member/do":
            return False
        await connection.send({"id": request.id, "result": {"handled": True}})
        return True

    import asyncio

    async def run() -> None:
        context = await make_context()
        connection = CoreLiveConnection(
            DummyWebSocket(),
            context=context,
            adapter=CoreLiveConnectionAdapter(handle_operation_request=handle_operation_request),
        )
        connection.initialized = True
        await connection.handle_raw({"id": 7, "method": "member/do", "params": {}})

        message = await connection.outbound.get()
        assert message == {"id": 7, "result": {"handled": True}}

    asyncio.run(run())


def test_core_live_connection_adapter_dispatches_member_operation_catalog(tmp_path):
    async def make_context() -> CoreLiveContext:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'core-live-router-member-catalog.db'}", future=True)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        return CoreLiveContext(
            session_factory=session_factory,
            event_store=SqlAlchemyAppEventStore(AppEventRow, protocol_version="core.app_server.v1"),
            snapshot_store=SqlAlchemyThreadSnapshotStore(
                ThreadSnapshotRow,
                item_model=SnapshotItemRow,
                projector=CoreAppSnapshotProjector(member_defaults={"queue": []}),
            ),
            operations=OperationCatalog(),
            hub=CoreAppEventHub(),
        )

    def operation_catalog(connection: CoreLiveConnection) -> OperationCatalog:
        catalog = OperationCatalog()

        async def member_handler(request: OperationRequest) -> OperationResult:
            assert request.metadata["rpc_request"].method == "member/do"
            assert request.metadata["connection"] is connection
            return OperationResult(name=request.name, payload={"handled": True})

        catalog.register("member.do", member_handler)
        return catalog

    import asyncio

    async def run() -> None:
        context = await make_context()
        connection = CoreLiveConnection(
            DummyWebSocket(),
            context=context,
            adapter=CoreLiveConnectionAdapter(
                operation_catalog_factory=operation_catalog,
                handle_unknown_operations=True,
            ),
        )
        connection.initialized = True
        await connection.handle_raw({"id": 11, "method": "member/do", "params": {}})

        message = await connection.outbound.get()
        assert message == {"id": 11, "result": {"handled": True}}

    asyncio.run(run())


def test_core_live_connection_dispatches_operation_outcome_hooks(tmp_path):
    async def make_context() -> CoreLiveContext:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'core-live-router-outcome.db'}", future=True)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        return CoreLiveContext(
            session_factory=session_factory,
            event_store=SqlAlchemyAppEventStore(AppEventRow, protocol_version="core.app_server.v1"),
            snapshot_store=SqlAlchemyThreadSnapshotStore(
                ThreadSnapshotRow,
                item_model=SnapshotItemRow,
                projector=CoreAppSnapshotProjector(member_defaults={"queue": []}),
            ),
            operations=OperationCatalog(),
            hub=CoreAppEventHub(),
        )

    class Outcome:
        response = {"id": 21, "result": {"ok": True}}
        notify_events = [{"thread_id": "thread-1", "method": "member/event"}]
        publish_events = []
        runtime_start = {"thread_id": "thread-1", "turn_id": "turn-1"}
        continuation = {"request_id": "request-1", "thread_id": "thread-1"}

    calls: dict[str, dict] = {}

    def start_runtime(connection: CoreLiveConnection, runtime_start: dict) -> None:
        calls["runtime_start"] = runtime_start

    async def continue_approval(connection: CoreLiveConnection, continuation: dict) -> None:
        calls["continuation"] = continuation

    import asyncio

    async def run() -> None:
        context = await make_context()
        connection = CoreLiveConnection(
            DummyWebSocket(),
            context=context,
            adapter=CoreLiveConnectionAdapter(
                start_runtime=start_runtime,
                continue_approval=continue_approval,
            ),
        )
        await connection.send_operation_outcome(Outcome())
        await asyncio.sleep(0)

        response = await connection.outbound.get()
        event = await connection.outbound.get()
        assert response == {"id": 21, "result": {"ok": True}}
        assert event == {"method": "member/event", "params": {"thread_id": "thread-1", "method": "member/event"}}
        assert calls["runtime_start"] == {"thread_id": "thread-1", "turn_id": "turn-1"}
        assert calls["continuation"] == {"request_id": "request-1", "thread_id": "thread-1"}

    asyncio.run(run())


def test_core_live_resume_switches_connection_subscription_before_replaying(tmp_path):
    async def run() -> None:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'core-live-router-resume.db'}", future=True)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        context = CoreLiveContext(
            session_factory=session_factory,
            event_store=SqlAlchemyAppEventStore(AppEventRow, protocol_version="core.app_server.v1"),
            snapshot_store=SqlAlchemyThreadSnapshotStore(
                ThreadSnapshotRow,
                item_model=SnapshotItemRow,
                projector=CoreAppSnapshotProjector(member_defaults={"queue": []}),
            ),
            operations=OperationCatalog(),
            hub=CoreAppEventHub(),
        )

        def catalog(connection: CoreLiveConnection) -> OperationCatalog:
            operation_catalog = OperationCatalog()
            for name, handler in connection.context.host.operation_handlers().items():
                operation_catalog.register(name, handler)
            return operation_catalog

        connection = CoreLiveConnection(
            DummyWebSocket(),
            context=context,
            adapter=CoreLiveConnectionAdapter(operation_catalog_factory=catalog, handle_unknown_operations=True),
        )
        connection.initialized = True
        connection._subscribe("thread-a")
        old_subscription = connection.subscription

        await connection.handle_raw(
            {"id": 1, "method": "thread.resume", "params": {"thread_id": "thread-b", "last_seen_seq": 0}}
        )

        assert connection.thread_id == "thread-b"
        assert old_subscription not in context.hub._subscribers["thread-a"]
        assert connection.subscription in context.hub._subscribers["thread-b"]
        await context.hub.publish({"thread_id": "thread-b", "method": "event/b"})
        assert await connection.subscription.get() == {"thread_id": "thread-b", "method": "event/b"}
        await context.hub.publish({"thread_id": "thread-a", "method": "event/a"})
        assert connection.subscription.empty()
        response = await connection.outbound.get()
        assert response["id"] == 1
        assert response["result"]["thread"] == {"id": "thread-b"}
        assert response["result"]["events"] == []
        assert response["result"]["snapshot"]["thread_id"] == "thread-b"
        await engine.dispose()

    import asyncio

    asyncio.run(run())


def test_core_live_subscribes_before_running_a_thread_operation(tmp_path):
    async def run() -> None:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'core-live-router-stream.db'}", future=True)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        operations = OperationCatalog()
        started = asyncio.Event()
        release = asyncio.Event()

        async def long_operation(request: OperationRequest) -> OperationResult:
            started.set()
            await release.wait()
            return OperationResult(name=request.name, payload={"ok": True})

        operations.register("member.long", long_operation)
        context = CoreLiveContext(
            session_factory=session_factory,
            event_store=SqlAlchemyAppEventStore(AppEventRow, protocol_version="core.app_server.v1"),
            snapshot_store=SqlAlchemyThreadSnapshotStore(
                ThreadSnapshotRow,
                item_model=SnapshotItemRow,
                projector=CoreAppSnapshotProjector(member_defaults={"queue": []}),
            ),
            operations=operations,
            hub=CoreAppEventHub(),
        )
        connection = CoreLiveConnection(DummyWebSocket(), context=context)
        connection.initialized = True
        operation = asyncio.create_task(connection.handle_raw({
            "id": 1,
            "method": "member.long",
            "params": {"thread_id": "thread-stream"},
        }))
        await started.wait()

        assert connection.thread_id == "thread-stream"
        assert connection.subscription is not None

        release.set()
        await operation
        await engine.dispose()

    asyncio.run(run())
