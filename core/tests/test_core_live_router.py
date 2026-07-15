from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import DateTime, Integer, JSON, String, UniqueConstraint
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from lamtools_core.app import CoreAppSnapshotProjector, OperationCatalog, OperationRequest, OperationResult
from lamtools_core.app.event_store import SqlAlchemyAppEventStore
from lamtools_core.app.live_hub import CoreAppEventGap, CoreAppEventHub
from lamtools_core.app.live_operations import CoreLiveContext
from lamtools_core.app.live_operations import handle_thread_resume_operation
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


class DummyWebSocket:
    def __init__(self):
        self.close_calls = []

    async def accept(self):
        return None

    async def send_json(self, message):
        return None

    async def close(self, code=1000, reason=""):
        self.close_calls.append((code, reason))


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
        accepted = websocket.receive_json()
        assert accepted["id"] == 2
        assert accepted["result"]["snapshot"]["status"] == "running"

        snapshot = websocket.receive_json()
        assert snapshot["method"] == "thread/snapshot"
        assert snapshot["params"]["thread_id"] == "thread-1"


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
