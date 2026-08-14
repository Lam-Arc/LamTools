from __future__ import annotations

import asyncio
import json
from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import DateTime, Integer, JSON, String, UniqueConstraint, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from lamtools_core.app import (
    AppPersistenceHost,
    CORE_WORKBENCH_OPERATION_NAMES,
    CoreAppSnapshotProjector,
    CoreLiveOperationHost,
    OperationCatalog,
    OperationResult,
)
from lamtools_core.app.default_agent import CoreAgentPaths, create_core_agent_operations
from lamtools_core.app.event_store import SqlAlchemyAppEventStore
from lamtools_core.app.live_hub import CoreAppEventHub
from lamtools_core.app.live_operations import (
    CoreLiveContext,
    _ensure_turn_terminal,
    handle_queue_create_operation,
    handle_queue_delete_operation,
    handle_queue_guidance_operation,
    handle_queue_update_operation,
    handle_thread_resume_operation,
    handle_thread_start_operation,
    handle_turn_cancel_operation,
    handle_turn_force_reset_operation,
    handle_turn_start_operation,
    handle_turn_steer_operation,
    handle_command_execute_operation,
    recover_stale_active_turns,
)
from lamtools_core.app.live_member import DefaultCoreLiveMemberHooks
from lamtools_core.event import RunItemEvent
from lamtools_core.app.snapshot_store import SqlAlchemyThreadSnapshotStore
import lamtools_core.app.live_operations as live_operations_module
from lamtools_core.llm import LLMRequest, LLMResponse, LLMStreamEvent
from lamtools_core.runtime import InMemoryRuntimeStateStore, RuntimeTaskRegistry


class Base(DeclarativeBase):
    pass


class AppEventRow(Base):
    __tablename__ = "test_core_live_app_events"
    __table_args__ = (
        UniqueConstraint("thread_id", "seq", name="uq_test_core_live_app_events_thread_seq"),
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
    __tablename__ = "test_core_live_thread_snapshots"

    thread_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    snapshot_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)


class SnapshotItemRow(Base):
    __tablename__ = "test_core_live_thread_snapshot_items"

    thread_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    item_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    item_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)



async def _context(tmp_path) -> tuple[object, CoreLiveContext]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'core-live.db'}", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    event_store = SqlAlchemyAppEventStore(AppEventRow, protocol_version="core.app_server.v1")
    snapshot_store = SqlAlchemyThreadSnapshotStore(ThreadSnapshotRow, item_model=SnapshotItemRow, projector=CoreAppSnapshotProjector(member_defaults={"queue": []}))
    return engine, CoreLiveContext(
        session_factory=session_factory,
        event_store=event_store,
        snapshot_store=snapshot_store,
        operations=OperationCatalog(),
        hub=CoreAppEventHub(),
    )


@pytest.mark.asyncio
async def test_thread_start_uses_core_transaction_and_member_materialization(tmp_path):
    engine, context = await _context(tmp_path)

    class MemberHooks:
        async def materialize_thread(self, *, db, thread_id, params):
            del db, params
            return {"member_session_id": thread_id}

    context.host.member_hooks = MemberHooks()
    try:
        outcome = await handle_thread_start_operation(
            request_id=1,
            params={"thread_id": "thread-start", "title": "Atomic"},
            context=context,
        )

        assert outcome.response["result"]["snapshot"]["snapshot_seq"] == 1
        assert outcome.response["result"]["event"]["method"] == "thread/started"
        assert outcome.response["result"]["event"]["payload"]["member_session_id"] == "thread-start"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_approval_respond_uses_operation_catalog_without_member_lifecycle_hook(tmp_path):
    engine, context = await _context(tmp_path)
    calls = []

    async def respond(request):
        calls.append(request.payload)
        return OperationResult(name=request.name, payload={"decision": "approve"})

    context.operations.register("approval.respond", respond)
    try:
        outcome = await context.host.execute(
            "approval.respond",
            request_id=1,
            params={"thread_id": "thread-1", "request_id": "request-1", "decision": "approve"},
            context=context,
        )
        assert outcome.response["result"]["decision"] == "approve"
        assert calls == [{
            "thread_id": "thread-1", "request_id": "request-1",
            "decision": "approve", "guidance": "",
            "approval_policy": "require",
            "active_tier": None,
            "tier_tools": None,
            "allow_access_outside_workdir": False,
        }]
        assert not hasattr(context.host.member_hooks, "continue_approval")
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_denied_approval_releases_stale_runtime_claim_before_next_turn(tmp_path):
    engine, context = await _context(tmp_path)
    stale_release = asyncio.Event()
    next_release = _register_blocking_turn_start(context)
    stale_task = asyncio.create_task(stale_release.wait())
    assert context.runtime_task_registry.accept_run("thread-deny", "turn-denied")
    assert context.runtime_task_registry.register("thread-deny", stale_task, run_id="turn-denied")

    async def respond(request):
        return OperationResult(
            name=request.name,
            payload={"thread_id": "thread-deny", "run_id": "turn-denied", "decision": "denied"},
        )

    context.operations.register("approval.respond", respond)
    try:
        denied = await context.host.execute(
            "approval.respond",
            request_id=1,
            params={"thread_id": "thread-deny", "request_id": "request-1", "decision": "deny"},
            context=context,
        )
        assert denied.response["result"]["decision"] == "denied"
        assert context.runtime_task_registry.active_run_id("thread-deny") is None

        started = await handle_turn_start_operation(
            request_id=2,
            params={
                "thread_id": "thread-deny",
                "client_message_id": "client-after-deny",
                "input": [{"type": "text", "text": "continue"}],
            },
            context=context,
        )
        assert "result" in started.response
    finally:
        stale_release.set()
        next_release.set()
        await stale_task
        next_task = context.runtime_task_registry.task("thread-deny")
        if next_task is not None:
            await next_task
        await engine.dispose()


@pytest.mark.asyncio
async def test_thread_start_retries_whole_member_event_snapshot_transaction(tmp_path):
    engine, context = await _context(tmp_path)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE member_threads (id TEXT PRIMARY KEY)"))
    attempts = 0

    class RetryThreadHooks:
        async def materialize_thread(self, *, db, thread_id, params):
            nonlocal attempts
            del params
            attempts += 1
            await db.execute(text("INSERT INTO member_threads(id) VALUES (:id)"), {"id": thread_id})
            if attempts == 1:
                raise OperationalError("member", {}, Exception("database is locked"))
            return {}

    context.host.member_hooks = RetryThreadHooks()
    try:
        outcome = await handle_thread_start_operation(
            request_id=1, params={"thread_id": "retry-thread"}, context=context,
        )
        async with context.session_factory() as db:
            member_count = (await db.execute(text("SELECT COUNT(*) FROM member_threads"))).scalar_one()
            events = await context.persistence.list_thread(db, thread_id="retry-thread")
        assert attempts == 2
        assert member_count == 1
        assert len(events) == 1
        assert outcome.response["result"]["snapshot"]["snapshot_seq"] == 1
    finally:
        await engine.dispose()


@pytest.mark.parametrize("operation_name", ["turn.start", "command.catalog", "config.models.list"])
def test_core_live_host_rejects_base_operation_executor_override(tmp_path, operation_name):
    async def forbidden_override(**_kwargs):
        raise AssertionError("base lifecycle override must never run")

    with pytest.raises(ValueError, match="base live operation"):
        CoreLiveOperationHost(
            session_factory=lambda: None,
            persistence=SimpleNamespace(bind_session_factory=lambda _factory: None),
            product_operation_executors={operation_name: forbidden_override},
        )


@pytest.mark.asyncio
async def test_core_compact_command_failure_persists_terminal_projection(tmp_path):
    engine, context = await _context(tmp_path)

    class Hooks(DefaultCoreLiveMemberHooks):
        def command_action_handlers(self):
            async def fail(**_kwargs):
                raise RuntimeError("compact failed")

            return {"compact": fail}

    context.host.member_hooks = Hooks()
    try:
        outcome = await handle_command_execute_operation(
            request_id=1,
            params={"thread_id": "thread-compact-fail", "command": "compact"},
            context=context,
        )
        async with context.session_factory() as db:
            snapshot = await context.persistence.load(db, "thread-compact-fail")

        assert outcome.response["error"]["message"] == "compact failed"
        turn = next(iter(snapshot["core"]["turns"].values()))
        assert turn["status"] == "failed"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_core_compact_command_can_omit_large_snapshot_from_response(tmp_path):
    engine, context = await _context(tmp_path)

    class Hooks(DefaultCoreLiveMemberHooks):
        def command_action_handlers(self):
            async def compact(**_kwargs):
                return {"status": "not_needed", "reason": "no_gain"}

            return {"compact": compact}

    context.host.member_hooks = Hooks()
    try:
        outcome = await handle_command_execute_operation(
            request_id=1,
            params={
                "thread_id": "thread-compact-small-response",
                "command": "compact",
                "include_snapshot": False,
            },
            context=context,
        )

        assert outcome.response["result"]["result"] == {
            "status": "not_needed",
            "reason": "no_gain",
        }
        assert "snapshot" not in outcome.response["result"]
        async with context.session_factory() as db:
            snapshot = await context.persistence.load(db, "thread-compact-small-response")
        turn = next(iter(snapshot["core"]["turns"].values()))
        assert turn["status"] == "completed"
        release = _register_blocking_turn_start(context)
        started = await handle_turn_start_operation(
            request_id=2,
            params={
                "thread_id": "thread-compact-small-response",
                "client_message_id": "after-compact",
                "input": [{"type": "text", "text": "continue"}],
            },
            context=context,
        )
        assert "error" not in started.response
        task = context.runtime_task_registry.task("thread-compact-small-response")
        release.set()
        if task is not None:
            await task
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_core_compact_command_forwards_operation_delta_to_live_events(tmp_path):
    engine, context = await _context(tmp_path)
    live_events = context.hub.subscribe("thread-compact-delta")

    async def execute(request):
        on_event = request.payload.get("_on_event")
        assert callable(on_event)
        for delta, content in (("摘", "摘"), ("要", "摘要"), ("增量", "摘要增量")):
            await on_event({
                "status": "running",
                "phase": "segment",
                "delta": delta,
                "content": content,
            })
        return OperationResult(
            name=request.name,
            payload={"result": {
                "status": "compacted",
                "summary": "摘要增量",
                "before_tokens": 1000,
                "after_tokens": 500,
            }},
        )

    context.operations.register("command.execute", execute)
    try:
        outcome = await handle_command_execute_operation(
            request_id=1,
            params={
                "thread_id": "thread-compact-delta",
                "command": "compact",
                "client_command_id": "current123",
            },
            context=context,
        )
        async with context.session_factory() as db:
            rows = (
                await db.execute(
                    text(
                        "select payload_json from test_core_live_app_events "
                        "where thread_id='thread-compact-delta' order by seq"
                    )
                )
            ).scalars().all()

        assert outcome.response["result"]["result"]["status"] == "compacted"
        payloads = [json.loads(row) if isinstance(row, str) else row for row in rows]
        published = []
        while not live_events.empty():
            published.append(live_events.get_nowait())
        native_deltas = [
            event.payload.get("payload", {}).get("delta")
            for event in published
            if getattr(event, "seq", -1) == 0 and event.payload.get("payload", {}).get("delta")
        ]
        assert native_deltas == ["摘", "要", "增量"]
        assert not any(row.get("payload", {}).get("delta") for row in payloads)
        assert any(row.get("payload", {}).get("content") == "摘要增量" for row in payloads)
        assert {
            row.get("turn_id") for row in payloads
        } == {"thread-compact-delta:command:compact:current123"}
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_core_compact_command_cancelled_releases_active_projection(tmp_path):
    engine, context = await _context(tmp_path)

    class Hooks(DefaultCoreLiveMemberHooks):
        def command_action_handlers(self):
            async def compact(on_event=None, **_kwargs):
                await on_event({"status": "failed", "reason": "cancelled", "message": "cancelled"})
                raise asyncio.CancelledError

            return {"compact": compact}

    context.host.member_hooks = Hooks()
    try:
        outcome = await handle_command_execute_operation(
            request_id=1,
            params={"thread_id": "thread-compact-cancelled", "command": "compact"},
            context=context,
        )
        assert outcome.response["result"]["result"]["status"] == "cancelled"
        async with context.session_factory() as db:
            snapshot = await context.persistence.load(db, "thread-compact-cancelled")
            events = await context.persistence.list_thread(db, thread_id="thread-compact-cancelled")

        turn = next(iter(snapshot["core"]["turns"].values()))
        assert turn["status"] == "cancelled"
        compaction_statuses = [
            event.payload.get("payload", {}).get("compaction_status")
            for event in events
            if event.method == "core/runItem"
            and event.payload.get("payload", {}).get("type") == "compaction"
        ]
        assert "failed" not in compaction_statuses
        assert "cancelled" in compaction_statuses
        cancelled_item = next(
            event.payload["payload"]
            for event in events
            if event.method == "core/runItem"
            and event.payload.get("payload", {}).get("compaction_status") == "cancelled"
        )
        assert cancelled_item["label"] == "压缩已取消"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_core_compact_command_rejects_overlapping_compaction_and_releases_claim(tmp_path):
    engine, context = await _context(tmp_path)
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    calls = 0

    class Hooks(DefaultCoreLiveMemberHooks):
        def command_action_handlers(self):
            async def compact(**_kwargs):
                nonlocal calls
                calls += 1
                if calls == 1:
                    first_started.set()
                    await release_first.wait()
                return {"status": "not_needed", "reason": "no_gain"}

            return {"compact": compact}

    context.host.member_hooks = Hooks()
    first = asyncio.create_task(handle_command_execute_operation(
        request_id=1,
        params={"thread_id": "thread-compact-exclusive", "command": "compact"},
        context=context,
    ))
    try:
        await asyncio.wait_for(first_started.wait(), timeout=1)
        overlapping = await handle_command_execute_operation(
            request_id=2,
            params={"thread_id": "thread-compact-exclusive", "command": "compact"},
            context=context,
        )
        assert overlapping.response["error"]["message"] == "A context compaction is already running"
        assert calls == 1

        release_first.set()
        completed = await first
        assert completed.response["result"]["result"]["status"] == "not_needed"

        next_run = await handle_command_execute_operation(
            request_id=3,
            params={"thread_id": "thread-compact-exclusive", "command": "compact"},
            context=context,
        )
        assert next_run.response["result"]["result"]["status"] == "not_needed"
        assert calls == 2
    finally:
        release_first.set()
        if not first.done():
            await first
        await engine.dispose()


@pytest.mark.asyncio
async def test_core_compact_stop_cancels_the_real_operation_without_late_failure(tmp_path):
    engine, context = await _context(tmp_path)
    started = asyncio.Event()
    handler_cancelled = asyncio.Event()
    calls = 0

    class Hooks(DefaultCoreLiveMemberHooks):
        def command_action_handlers(self):
            async def compact(**_kwargs):
                nonlocal calls
                calls += 1
                if calls > 1:
                    return {"status": "not_needed", "reason": "no_gain"}
                started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    handler_cancelled.set()
                    raise

            return {"compact": compact}

    context.host.member_hooks = Hooks()
    operation = asyncio.create_task(handle_command_execute_operation(
        request_id=1,
        params={"thread_id": "thread-compact-stop", "command": "compact", "client_command_id": "stop123"},
        context=context,
    ))
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
        run_id = "thread-compact-stop:command:compact:stop123"
        assert context.runtime_task_registry.task("thread-compact-stop", run_id=run_id) is not None

        await handle_turn_cancel_operation(
            request_id=2,
            params={"thread_id": "thread-compact-stop", "turn_id": run_id},
            context=context,
        )
        cancelled = await asyncio.wait_for(operation, timeout=1)
        assert cancelled.response["result"]["result"]["status"] == "cancelled"
        assert handler_cancelled.is_set()

        async with context.session_factory() as db:
            events = await context.persistence.list_thread(db, thread_id="thread-compact-stop")
        compact_statuses = [
            str(event.payload.get("status") or "")
            for event in events
            if event.turn_id == run_id and event.method == "core/runItem"
        ]
        assert "failed" not in compact_statuses

        next_run = await handle_command_execute_operation(
            request_id=3,
            params={"thread_id": "thread-compact-stop", "command": "compact"},
            context=context,
        )
        assert next_run.response["result"]["result"]["status"] == "not_needed"
    finally:
        if not operation.done():
            operation.cancel()
            with pytest.raises(asyncio.CancelledError):
                await operation
        await engine.dispose()


@pytest.mark.asyncio
async def test_turn_start_orders_member_prepare_transaction_commit_then_runtime_start(tmp_path):
    engine, context = await _context(tmp_path)
    order: list[str] = []

    class MemberHooks:
        async def prepare_turn_input(self, **kwargs):
            order.append("prepare")
            return SimpleNamespace(
                visible_input=kwargs["input_items"],
                runtime_input=kwargs["input_items"],
                visible_text="hello",
                runtime_text="hello",
                work_root="",
                runtime_extras={},
            )

        async def materialize_turn(self, **kwargs):
            order.append("materialize")
            return SimpleNamespace(
                turn_id=kwargs["turn_id"],
                user_item_id=kwargs["user_item_id"],
                turn_payload_extra={},
                user_payload_extra={},
                include_turn_status=True,
                runtime_extras={},
            )

        async def start_runtime(self, **_kwargs):
            order.append("runtime_start")

    context.host.member_hooks = MemberHooks()
    real_write = context.persistence.write

    async def recording_write(callback):
        result = await real_write(callback)
        order.append("commit")
        return result

    context.persistence.write = recording_write
    try:
        outcome = await handle_turn_start_operation(
            request_id=1,
            params={
                "thread_id": "thread-hook-order",
                "client_message_id": "client-hook-order",
                "input": [{"type": "text", "text": "hello"}],
            },
            context=context,
        )
        await asyncio.sleep(0)

        assert "result" in outcome.response
        assert order == ["prepare", "materialize", "commit", "runtime_start"]
    finally:
        context.runtime_task_registry.clear()
        await engine.dispose()


def _register_blocking_turn_start(context: CoreLiveContext) -> asyncio.Event:
    release = asyncio.Event()

    async def turn_start(_request):
        await release.wait()
        return OperationResult(name="turn.start")

    context.operations.register("turn.start", turn_start)
    return release


class BlockingCoreLLM:
    def __init__(self) -> None:
        import asyncio

        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise AssertionError("live Core run should stream when available")

    async def stream(self, request: LLMRequest):
        self.requests.append(request)
        self.started.set()
        await self.release.wait()
        yield LLMStreamEvent(kind="content_delta", content="completed")
        yield LLMStreamEvent(kind="done")


class GuidedCoreLLM(BlockingCoreLLM):
    async def stream(self, request: LLMRequest):
        self.requests.append(request)
        if len(self.requests) == 1:
            self.started.set()
            await self.release.wait()
            yield LLMStreamEvent(kind="content_delta", content="first final")
            yield LLMStreamEvent(kind="done")
            return
        yield LLMStreamEvent(kind="content_delta", content="guided final")
        yield LLMStreamEvent(kind="done")


async def _live_core_context(tmp_path, llm: BlockingCoreLLM) -> tuple[object, CoreLiveContext]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'core-live-kernel.db'}", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    event_store = SqlAlchemyAppEventStore(AppEventRow, protocol_version="core.app_server.v1")
    snapshot_store = SqlAlchemyThreadSnapshotStore(
        ThreadSnapshotRow,
        item_model=SnapshotItemRow,
        projector=CoreAppSnapshotProjector(member_defaults={"queue": []}),
    )
    hub = CoreAppEventHub()
    runtime_task_registry = RuntimeTaskRegistry()
    runtime_state_store = InMemoryRuntimeStateStore()
    operations = create_core_agent_operations(
        paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=tmp_path / "work"),
        model_provider=llm,
        db_session_factory=session_factory,
        app_event_store=event_store,
        thread_snapshot_store=snapshot_store,
        app_event_hub=hub,
        runtime_state_store=runtime_state_store,
        runtime_task_registry=runtime_task_registry,
    )
    context = CoreLiveContext(
        session_factory=session_factory,
        event_store=event_store,
        snapshot_store=snapshot_store,
        operations=operations,
        hub=hub,
        runtime_task_registry=runtime_task_registry,
        runtime_state_store=runtime_state_store,
    )
    return engine, context


@pytest.mark.asyncio
async def test_core_live_turn_start_accepts_input_before_runtime_completion(tmp_path):
    engine, context = await _context(tmp_path)
    release = _register_blocking_turn_start(context)
    try:
        outcome = await handle_turn_start_operation(
            request_id=1,
            params={
                "thread_id": "thread-1",
                "client_message_id": "client-1",
                "input": [{"type": "text", "text": "hello"}],
                "thinking_enabled": True,
                "thinking_budget": 6000,
                "shallow_thinking_enabled": True,
                "context_window_tokens": 256000,
                "model_id": "xopkimik26",
                "max_tokens": 8192,
                "temperature": 0.3,
                "compact_trigger_tokens": 150000,
                "compact_limit_tokens": 100000,
            },
            context=context,
        )

        result = outcome.response["result"]
        assert result["snapshot"]["status"] == "running"
        assert result["snapshot"]["turns"][result["runtime_start"]["turn_id"]]["status"] == "running"
        assert result["snapshot"]["items"][result["runtime_start"]["user_message_id"]]["type"] == "userMessage"
        assert result["snapshot"]["item_order"] == [result["runtime_start"]["user_message_id"]]
        assert result["events"][0]["method"] == "turn/accepted"
        assert result["runtime_start"]["thinking_enabled"] is True
        assert result["runtime_start"]["thinking_budget"] == 6000
        assert result["runtime_start"]["shallow_thinking_enabled"] is True
        assert result["runtime_start"]["context_window_tokens"] == 256000
        assert result["runtime_start"]["model_id"] == "xopkimik26"
        assert result["runtime_start"]["max_tokens"] == 8192
        assert result["runtime_start"]["temperature"] == 0.3
        assert result["runtime_start"]["compact_trigger_tokens"] == 150000
        assert result["runtime_start"]["compact_limit_tokens"] == 100000

        resumed = await handle_thread_resume_operation(
            request_id=2,
            params={"thread_id": "thread-1", "last_seen_seq": 0},
            context=context,
        )
        methods = [event["method"] for event in resumed.response["result"]["events"]]
        assert methods == ["turn/accepted", "item/started", "core/runItem"]
    finally:
        task = context.runtime_task_registry.task("thread-1")
        release.set()
        if task is not None:
            await task
        await engine.dispose()


@pytest.mark.asyncio
async def test_turn_start_uses_shared_auto_allow_setting_when_policy_is_omitted(tmp_path):
    engine, context = await _context(tmp_path)
    release = _register_blocking_turn_start(context)

    async def get_settings(request):
        assert request.payload == {"namespace": "core.runtimeControls"}
        return OperationResult(
            name=request.name,
            payload={
                "namespace": "core.runtimeControls",
                "value": {
                    "permission_mode": "full_edit",
                },
            },
        )

    context.operations.register("settings.get", get_settings)
    try:
        outcome = await handle_turn_start_operation(
            request_id=1,
            params={
                "thread_id": "thread-auto-allow",
                "client_message_id": "client-auto-allow",
                "input": [{"type": "text", "text": "write a file"}],
            },
            context=context,
        )

        assert outcome.response["result"]["runtime_start"]["approval_policy"] == "auto_approve"
    finally:
        task = context.runtime_task_registry.task("thread-auto-allow")
        release.set()
        if task is not None:
            await task
        await engine.dispose()


@pytest.mark.asyncio
async def test_turn_start_releases_runtime_claim_before_retrying_locked_transaction(tmp_path, monkeypatch):
    engine, context = await _context(tmp_path)
    release = _register_blocking_turn_start(context)
    original_append = live_operations_module._append_app_event
    append_calls = 0

    async def locked_once(*args, **kwargs):
        nonlocal append_calls
        event = await original_append(*args, **kwargs)
        append_calls += 1
        if append_calls == 1:
            raise OperationalError("INSERT core_app_events", {}, Exception("database is locked"))
        return event

    monkeypatch.setattr(live_operations_module, "_append_app_event", locked_once)
    try:
        outcome = await handle_turn_start_operation(
            request_id=1,
            params={"thread_id": "thread-start-retry", "input": [{"type": "text", "text": "start"}]},
            context=context,
        )

        assert outcome.response["result"]["runtime_start"]["thread_id"] == "thread-start-retry"
        assert [event["method"] for event in outcome.response["result"]["events"]] == [
            "turn/accepted",
            "item/started",
            "core/runItem",
        ]
    finally:
        task = context.runtime_task_registry.task("thread-start-retry")
        release.set()
        if task is not None:
            await task
        await engine.dispose()


@pytest.mark.asyncio
async def test_turn_steer_retracts_guidance_before_retrying_locked_transaction(tmp_path, monkeypatch):
    engine, context = await _context(tmp_path)
    release = _register_blocking_turn_start(context)
    try:
        started = await handle_turn_start_operation(
            request_id=1,
            params={"thread_id": "thread-steer-retry", "input": [{"type": "text", "text": "start"}]},
            context=context,
        )
        turn_id = started.response["result"]["runtime_start"]["turn_id"]
        original_append = live_operations_module._append_app_event
        append_calls = 0

        async def locked_once(*args, **kwargs):
            nonlocal append_calls
            event = await original_append(*args, **kwargs)
            append_calls += 1
            if append_calls == 1:
                raise OperationalError("INSERT core_app_events", {}, Exception("database is locked"))
            return event

        monkeypatch.setattr(live_operations_module, "_append_app_event", locked_once)
        outcome = await handle_turn_steer_operation(
            request_id=2,
            params={
                "thread_id": "thread-steer-retry",
                "turn_id": turn_id,
                "client_message_id": "steer-retry",
                "input": [{"type": "text", "text": "guide"}],
            },
            context=context,
        )

        assert [event["method"] for event in outcome.response["result"]["events"]] == ["turn/steered"]
    finally:
        task = context.runtime_task_registry.task("thread-steer-retry")
        release.set()
        if task is not None:
            await task
        await engine.dispose()


@pytest.mark.asyncio
async def test_turn_steer_persists_consumed_guidance_after_locked_commit_retry(tmp_path, monkeypatch):
    engine, context = await _context(tmp_path)
    release = _register_blocking_turn_start(context)
    failure_injected = False
    consumed: list[str] = []
    accepted_statuses: list[str] = []
    try:
        started = await handle_turn_start_operation(
            request_id=1,
            params={
                "thread_id": "thread-steer-consumed-retry",
                "client_message_id": "start-steer-consumed-retry",
                "input": [{"type": "text", "text": "complete this"}],
            },
            context=context,
        )
        turn_id = started.response["result"]["runtime_start"]["turn_id"]
        task = context.runtime_task_registry.task("thread-steer-consumed-retry", run_id=turn_id)
        assert task is not None

        original_accept = context.runtime_task_registry.accept_guidance
        original_commit = AsyncSession.commit

        def record_accept(*args, **kwargs):
            status = original_accept(*args, **kwargs)
            accepted_statuses.append(status)
            return status

        async def fail_commit_after_runtime_consumes(db):
            nonlocal failure_injected
            if not failure_injected:
                failure_injected = True
                consumed.extend(context.runtime_task_registry.consume_guidance(
                    "thread-steer-consumed-retry", run_id=turn_id
                ))
                raise OperationalError("COMMIT core_app_events", {}, Exception("database is locked"))
            return await original_commit(db)

        monkeypatch.setattr(context.runtime_task_registry, "accept_guidance", record_accept)
        monkeypatch.setattr(AsyncSession, "commit", fail_commit_after_runtime_consumes)
        steered = await handle_turn_steer_operation(
            request_id=2,
            params={
                "thread_id": "thread-steer-consumed-retry",
                "turn_id": turn_id,
                "client_message_id": "steer-consumed-retry",
                "input": [{"type": "text", "text": "use the safer path"}],
            },
            context=context,
        )

        result = steered.response["result"]
        assert result["applied"] is True
        assert result["reason"] == ""
        assert [event["method"] for event in result["events"]] == ["turn/steered"]
        assert accepted_statuses == ["accepted", "duplicate"]
        assert consumed == ["use the safer path"]

        async with context.session_factory() as db:
            events = await context.persistence.list_thread(db, thread_id="thread-steer-consumed-retry")
            snapshot = await context.persistence.load(db, "thread-steer-consumed-retry")
        assert [event.method for event in events].count("turn/steered") == 1
        assert snapshot["snapshot_seq"] == events[-1].seq
    finally:
        task = context.runtime_task_registry.task("thread-steer-consumed-retry")
        release.set()
        if task is not None:
            await task
        await engine.dispose()


@pytest.mark.asyncio
async def test_queue_guidance_persists_consumed_guidance_after_locked_commit_retry(tmp_path, monkeypatch):
    engine, context = await _context(tmp_path)
    release = _register_blocking_turn_start(context)
    failure_injected = False
    consumed: list[str] = []
    accepted_statuses: list[str] = []
    try:
        started = await handle_turn_start_operation(
            request_id=1,
            params={
                "thread_id": "thread-queue-consumed-retry",
                "client_message_id": "start-queue-consumed-retry",
                "input": [{"type": "text", "text": "complete this"}],
            },
            context=context,
        )
        turn_id = started.response["result"]["runtime_start"]["turn_id"]
        task = context.runtime_task_registry.task("thread-queue-consumed-retry", run_id=turn_id)
        assert task is not None
        queued = await handle_queue_create_operation(
            request_id=2,
            params={
                "thread_id": "thread-queue-consumed-retry",
                "client_message_id": "queue-consumed-retry",
                "input": [{"type": "text", "text": "queued guidance"}],
            },
            context=context,
        )
        queue_item_id = queued.response["result"]["queue_item"]["queue_item_id"]

        original_accept = context.runtime_task_registry.accept_guidance
        original_commit = AsyncSession.commit

        def record_accept(*args, **kwargs):
            status = original_accept(*args, **kwargs)
            accepted_statuses.append(status)
            return status

        async def fail_commit_after_runtime_consumes(db):
            nonlocal failure_injected
            if not failure_injected:
                failure_injected = True
                consumed.extend(context.runtime_task_registry.consume_guidance(
                    "thread-queue-consumed-retry", run_id=turn_id
                ))
                raise OperationalError("COMMIT core_app_events", {}, Exception("database is locked"))
            return await original_commit(db)

        monkeypatch.setattr(context.runtime_task_registry, "accept_guidance", record_accept)
        monkeypatch.setattr(AsyncSession, "commit", fail_commit_after_runtime_consumes)
        guided = await handle_queue_guidance_operation(
            request_id=3,
            params={
                "thread_id": "thread-queue-consumed-retry",
                "turn_id": turn_id,
                "queue_item_id": queue_item_id,
                "client_message_id": "queue-guide-consumed-retry",
            },
            context=context,
        )

        result = guided.response["result"]
        assert result["applied"] is True
        assert result["reason"] == ""
        assert [event["method"] for event in result["events"]] == ["turn/steered", "item/started", "queue/itemDeleted"]
        assert accepted_statuses == ["accepted", "duplicate"]
        assert consumed == ["queued guidance"]

        async with context.session_factory() as db:
            events = await context.persistence.list_thread(db, thread_id="thread-queue-consumed-retry")
            snapshot = await context.persistence.load(db, "thread-queue-consumed-retry")
        assert [event.method for event in events].count("turn/steered") == 1
        assert [event.method for event in events].count("queue/itemDeleted") == 1
        assert snapshot["queue"] == []
    finally:
        task = context.runtime_task_registry.task("thread-queue-consumed-retry")
        release.set()
        if task is not None:
            await task
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation_name", ["turn.steer", "queue.guide"])
async def test_consumed_guidance_survives_exhausted_commit_retries_for_client_retry(
    tmp_path, monkeypatch, operation_name
):
    engine, context = await _context(tmp_path)
    release = _register_blocking_turn_start(context)
    thread_id = f"thread-client-retry-{operation_name}"
    client_message_id = f"client-retry-{operation_name}"
    try:
        started = await handle_turn_start_operation(
            request_id=1,
            params={"thread_id": thread_id, "input": [{"type": "text", "text": "start"}]},
            context=context,
        )
        turn_id = started.response["result"]["runtime_start"]["turn_id"]
        params = {
            "thread_id": thread_id,
            "turn_id": turn_id,
            "client_message_id": client_message_id,
        }
        handler = handle_turn_steer_operation
        if operation_name == "turn.steer":
            params["input"] = [{"type": "text", "text": "retry guidance"}]
        else:
            queued = await handle_queue_create_operation(
                request_id=2,
                params={"thread_id": thread_id, "input": [{"type": "text", "text": "queued guidance"}]},
                context=context,
            )
            params["queue_item_id"] = queued.response["result"]["queue_item"]["queue_item_id"]
            handler = handle_queue_guidance_operation

        original_commit = AsyncSession.commit
        consumed = False

        async def fail_every_commit_after_consumption(db):
            nonlocal consumed
            if not consumed:
                consumed = True
                context.runtime_task_registry.consume_guidance(thread_id, run_id=turn_id)
            raise OperationalError("COMMIT core_app_events", {}, Exception("database is locked"))

        monkeypatch.setattr(AsyncSession, "commit", fail_every_commit_after_consumption)
        with pytest.raises(OperationalError, match="database is locked"):
            await handler(request_id=3, params=params, context=context)

        monkeypatch.setattr(AsyncSession, "commit", original_commit)
        retried = await handler(request_id=4, params=params, context=context)
        result = retried.response["result"]
        assert result["applied"] is True
        assert result["reason"] == ""
        expected_methods = ["turn/steered"]
        if operation_name == "queue.guide":
            expected_methods = ["turn/steered", "item/started", "queue/itemDeleted"]
        assert [event["method"] for event in result["events"]] == expected_methods

        async with context.session_factory() as db:
            events = await context.persistence.list_thread(db, thread_id=thread_id)
            snapshot = await context.persistence.load(db, thread_id)
        assert [event.method for event in events].count("turn/steered") == 1
        if operation_name == "queue.guide":
            assert snapshot["queue"] == []
    finally:
        task = context.runtime_task_registry.task(thread_id)
        release.set()
        if task is not None:
            await task
        await engine.dispose()


@pytest.mark.asyncio
async def test_queue_guidance_retracts_pending_guidance_after_exhausted_commit_retries(tmp_path, monkeypatch):
    engine, context = await _context(tmp_path)
    release = _register_blocking_turn_start(context)
    accepted_statuses: list[str] = []
    try:
        started = await handle_turn_start_operation(
            request_id=1,
            params={"thread_id": "thread-queue-pending-retry", "input": [{"type": "text", "text": "start"}]},
            context=context,
        )
        turn_id = started.response["result"]["runtime_start"]["turn_id"]
        queued = await handle_queue_create_operation(
            request_id=2,
            params={"thread_id": "thread-queue-pending-retry", "input": [{"type": "text", "text": "queued"}]},
            context=context,
        )
        queue_item_id = queued.response["result"]["queue_item"]["queue_item_id"]
        params = {
            "thread_id": "thread-queue-pending-retry",
            "turn_id": turn_id,
            "queue_item_id": queue_item_id,
            "client_message_id": "queue-pending-retry",
        }
        original_accept = context.runtime_task_registry.accept_guidance
        original_commit = AsyncSession.commit

        def record_accept(*args, **kwargs):
            status = original_accept(*args, **kwargs)
            accepted_statuses.append(status)
            return status

        async def fail_every_commit(_db):
            raise OperationalError("COMMIT core_app_events", {}, Exception("database is locked"))

        monkeypatch.setattr(context.runtime_task_registry, "accept_guidance", record_accept)
        monkeypatch.setattr(AsyncSession, "commit", fail_every_commit)
        with pytest.raises(OperationalError, match="database is locked"):
            await handle_queue_guidance_operation(request_id=3, params=params, context=context)

        monkeypatch.setattr(AsyncSession, "commit", original_commit)
        retried = await handle_queue_guidance_operation(request_id=4, params=params, context=context)
        result = retried.response["result"]
        assert result["applied"] is True
        assert result["reason"] == ""
        assert [event["method"] for event in result["events"]] == ["turn/steered", "item/started", "queue/itemDeleted"]
        assert accepted_statuses[0] == "accepted"
        assert accepted_statuses[-1] == "accepted"
    finally:
        task = context.runtime_task_registry.task("thread-queue-pending-retry")
        release.set()
        if task is not None:
            await task
        await engine.dispose()


@pytest.mark.asyncio
async def test_live_turn_reuses_accepted_id_for_core_events_terminal_and_task_registry(tmp_path):
    llm = BlockingCoreLLM()
    engine, context = await _live_core_context(tmp_path, llm)
    try:
        outcome = await handle_turn_start_operation(
            request_id=1,
            params={
                "thread_id": "thread-live-id",
                "client_message_id": "client-live-id",
                "input": [{"type": "text", "text": "finish this"}],
            },
            context=context,
        )
        accepted_turn_id = outcome.response["result"]["events"][0]["turn_id"]
        await llm.started.wait()
        task = context.runtime_task_registry.task("thread-live-id", run_id=accepted_turn_id)
        assert task is not None

        llm.release.set()
        await task
        assert len(llm.requests) == 1

        resumed = await handle_thread_resume_operation(
            request_id=2,
            params={"thread_id": "thread-live-id", "last_seen_seq": 0},
            context=context,
        )
        result = resumed.response["result"]
        core_events = [event for event in result["events"] if event["method"] == "core/runItem"]

        assert core_events
        assert {event["turn_id"] for event in core_events} == {accepted_turn_id}
        assert {event["payload"].get("run_id") for event in core_events} == {accepted_turn_id}
        assert result["snapshot"]["status"] == "completed"
        assert result["snapshot"]["core"]["status"] == "completed"
        assert set(result["snapshot"]["core"]["turns"]) == {accepted_turn_id}
        assert result["snapshot"]["core"]["turns"][accepted_turn_id]["status"] == "completed"
        assert not any(
            turn["status"] == "running"
            for turn in result["snapshot"]["core"]["turns"].values()
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_live_turn_steer_reaches_the_next_model_call_before_a_no_tool_final(tmp_path):
    llm = GuidedCoreLLM()
    engine, context = await _live_core_context(tmp_path, llm)
    try:
        started = await handle_turn_start_operation(
            request_id=1,
            params={
                "thread_id": "thread-steer-live",
                "client_message_id": "client-steer-live",
                "input": [{"type": "text", "text": "complete this"}],
            },
            context=context,
        )
        turn_id = started.response["result"]["events"][0]["turn_id"]
        task = context.runtime_task_registry.task("thread-steer-live", run_id=turn_id)
        assert task is not None
        await llm.started.wait()

        steered = await handle_turn_steer_operation(
            request_id=2,
            params={
                "thread_id": "thread-steer-live",
                "turn_id": turn_id,
                "client_message_id": "client-steer-now",
                "input": [{"type": "text", "text": "use the safer path"}],
            },
            context=context,
        )
        assert steered.response["result"]["applied"] is True
        assert steered.response["result"]["events"][0]["method"] == "turn/steered"

        llm.release.set()
        await task

        assert len(llm.requests) == 2
        assert any(message.content == "use the safer path" for message in llm.requests[1].messages)
        resumed = await handle_thread_resume_operation(
            request_id=3,
            params={"thread_id": "thread-steer-live", "last_seen_seq": 0},
            context=context,
        )
        assert any(event["method"] == "turn/steered" for event in resumed.response["result"]["events"])
        assert context.runtime_task_registry.inject_guidance(
            "thread-steer-live", "late", run_id=turn_id
        ) is False
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_live_queue_guidance_reaches_the_next_model_call(tmp_path):
    llm = GuidedCoreLLM()
    engine, context = await _live_core_context(tmp_path, llm)
    try:
        started = await handle_turn_start_operation(
            request_id=1,
            params={
                "thread_id": "thread-queue-guide-live",
                "client_message_id": "client-queue-guide-live",
                "input": [{"type": "text", "text": "complete this"}],
            },
            context=context,
        )
        turn_id = started.response["result"]["events"][0]["turn_id"]
        task = context.runtime_task_registry.task("thread-queue-guide-live", run_id=turn_id)
        assert task is not None
        await llm.started.wait()
        queued = await handle_queue_create_operation(
            request_id=2,
            params={
                "thread_id": "thread-queue-guide-live",
                "input": [{"type": "text", "text": "queued guidance"}],
            },
            context=context,
        )
        queue_item_id = queued.response["result"]["queue_item"]["queue_item_id"]
        guided = await handle_queue_guidance_operation(
            request_id=3,
            params={
                "thread_id": "thread-queue-guide-live",
                "turn_id": turn_id,
                "queue_item_id": queue_item_id,
            },
            context=context,
        )
        assert guided.response["result"]["applied"] is True

        llm.release.set()
        await task

        assert len(llm.requests) == 2
        assert any(message.content == "queued guidance" for message in llm.requests[1].messages)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_live_turn_duplicate_client_message_returns_accepted_turn_without_second_runtime_task(tmp_path):
    engine, context = await _context(tmp_path)
    try:
        first = await handle_turn_start_operation(
            request_id=1,
            params={
                "thread_id": "thread-dedup",
                "client_message_id": "client-dedup",
                "input": [{"type": "text", "text": "once"}],
            },
            context=context,
        )
        duplicate = await handle_turn_start_operation(
            request_id=2,
            params={
                "thread_id": "thread-dedup",
                "client_message_id": "client-dedup",
                "input": [{"type": "text", "text": "once"}],
            },
            context=context,
        )

        assert duplicate.runtime_start is None
        assert duplicate.response["result"]["events"][0]["turn_id"] == first.response["result"]["events"][0]["turn_id"]
        assert duplicate.response["result"]["snapshot"]["snapshot_seq"] == first.response["result"]["snapshot"]["snapshot_seq"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_live_turn_rejects_second_active_start_without_overwriting_registry(tmp_path):
    llm = BlockingCoreLLM()
    engine, context = await _live_core_context(tmp_path, llm)
    try:
        first = await handle_turn_start_operation(
            request_id=1,
            params={
                "thread_id": "thread-active-start",
                "client_message_id": "client-first",
                "input": [{"type": "text", "text": "first"}],
            },
            context=context,
        )
        first_turn_id = first.response["result"]["runtime_start"]["turn_id"]
        await llm.started.wait()
        first_task = context.runtime_task_registry.task("thread-active-start", run_id=first_turn_id)
        assert first_task is not None

        second = await handle_turn_start_operation(
            request_id=2,
            params={
                "thread_id": "thread-active-start",
                "client_message_id": "client-second",
                "input": [{"type": "text", "text": "second"}],
            },
            context=context,
        )
        duplicate = await handle_turn_start_operation(
            request_id=3,
            params={
                "thread_id": "thread-active-start",
                "client_message_id": "client-first",
                "input": [{"type": "text", "text": "first"}],
            },
            context=context,
        )

        assert second.response["error"]["data"]["reason"] == "active_turn_exists"
        assert duplicate.response["result"]["events"][0]["turn_id"] == first_turn_id
        assert context.runtime_task_registry.active_run_id("thread-active-start") == first_turn_id
        assert context.runtime_task_registry.task("thread-active-start", run_id=first_turn_id) is first_task
    finally:
        llm.release.set()
        if 'first_task' in locals() and first_task is not None:
            await first_task
        await engine.dispose()


@pytest.mark.asyncio
async def test_sealed_active_snapshot_rejects_steer_and_queue_guidance_without_events(tmp_path):
    engine, context = await _context(tmp_path)
    release = _register_blocking_turn_start(context)
    try:
        started = await handle_turn_start_operation(
            request_id=1,
            params={
                "thread_id": "thread-sealed-window",
                "client_message_id": "client-start",
                "input": [{"type": "text", "text": "start"}],
            },
            context=context,
        )
        turn_id = started.response["result"]["runtime_start"]["turn_id"]
        assert context.runtime_task_registry.close_guidance_if_empty(
            "thread-sealed-window", run_id=turn_id
        ) == []
        queued = await handle_queue_create_operation(
            request_id=2,
            params={
                "thread_id": "thread-sealed-window",
                "input": [{"type": "text", "text": "queued"}],
            },
            context=context,
        )
        queue_item_id = queued.response["result"]["queue_item"]["queue_item_id"]

        steered = await handle_turn_steer_operation(
            request_id=3,
            params={
                "thread_id": "thread-sealed-window",
                "turn_id": turn_id,
                "client_message_id": "client-late-steer",
                "input": [{"type": "text", "text": "late steer"}],
            },
            context=context,
        )
        guided = await handle_queue_guidance_operation(
            request_id=4,
            params={
                "thread_id": "thread-sealed-window",
                "turn_id": turn_id,
                "queue_item_id": queue_item_id,
                "client_message_id": "client-late-queue",
            },
            context=context,
        )

        assert steered.response["result"]["applied"] is False
        assert steered.response["result"]["reason"] == "run_not_active"
        assert guided.response["result"]["applied"] is False
        assert guided.response["result"]["reason"] == "run_not_active"
        resumed = await handle_thread_resume_operation(
            request_id=5,
            params={"thread_id": "thread-sealed-window", "last_seen_seq": 0},
            context=context,
        )
        events = resumed.response["result"]["events"]
        assert not any(event["method"] == "turn/steered" for event in events)
        assert [item["queue_item_id"] for item in resumed.response["result"]["snapshot"]["queue"]] == [queue_item_id]
    finally:
        task = context.runtime_task_registry.task("thread-sealed-window")
        release.set()
        if task is not None:
            await task
        await engine.dispose()


@pytest.mark.asyncio
async def test_core_live_turn_cancel_publishes_interrupting_status(tmp_path):
    engine, context = await _context(tmp_path)
    _register_blocking_turn_start(context)
    task = None
    try:
        started = await handle_turn_start_operation(
            request_id=1,
            params={
                "thread_id": "thread-1",
                "client_message_id": "client-1",
                "input": [{"type": "text", "text": "hello"}],
            },
            context=context,
        )
        turn_id = started.response["result"]["runtime_start"]["turn_id"]
        task = context.runtime_task_registry.task("thread-1", run_id=turn_id)

        outcome = await handle_turn_cancel_operation(
            request_id=2,
            params={"thread_id": "thread-1", "include_snapshot": False},
            context=context,
        )

        result = outcome.response["result"]
        assert "snapshot" not in result
        assert [event["method"] for event in result["events"]] == ["turn/interrupted", "core/runItem"]
        assert result["events"][1]["payload"]["status"] == "interrupting"
    finally:
        if task is not None:
            with pytest.raises(asyncio.CancelledError):
                await task
        await engine.dispose()


@pytest.mark.asyncio
async def test_core_live_turn_cancel_closes_persisted_run_without_live_task(tmp_path):
    engine, context = await _context(tmp_path)
    _register_blocking_turn_start(context)
    task = None
    try:
        started = await handle_turn_start_operation(
            request_id=1,
            params={
                "thread_id": "thread-stale-running",
                "client_message_id": "client-stale-running",
                "input": [{"type": "text", "text": "hello"}],
            },
            context=context,
        )
        turn_id = started.response["result"]["runtime_start"]["turn_id"]
        task = context.runtime_task_registry.task("thread-stale-running", run_id=turn_id)
        assert task is not None

        # Simulate a process restart: persistence still says running, while the
        # new process has no in-memory task capable of emitting a terminal item.
        context.runtime_task_registry.release_run("thread-stale-running", run_id=turn_id)

        outcome = await handle_turn_cancel_operation(
            request_id=2,
            params={"thread_id": "thread-stale-running", "turn_id": turn_id},
            context=context,
        )

        result = outcome.response["result"]
        assert [event["method"] for event in result["events"]] == [
            "turn/interrupted",
            "core/runItem",
            "core/runItem",
        ]
        assert result["events"][-1]["payload"]["status"] == "cancelled"
        assert result["snapshot"]["turns"][turn_id]["status"] == "cancelled"
        assert result["snapshot"]["core"]["turns"][turn_id]["status"] == "cancelled"
    finally:
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await engine.dispose()


@pytest.mark.asyncio
async def test_core_live_turn_cancel_falls_back_to_registry_when_no_turn_id(tmp_path):
    """When the caller omits turn_id and the snapshot has no active turn,
    cancel must still target the registry's active run (Fix #3a).

    This is the 2b34c636 scenario: a sub-agent DB-lock error rewrote the
    snapshot so the turn no longer looks active, but the background task is
    still registered. Without the registry fallback, cancel returns idle and
    the user can only kill the process.
    """
    engine, context = await _context(tmp_path)
    release = _register_blocking_turn_start(context)
    task = None
    try:
        started = await handle_turn_start_operation(
            request_id=1,
            params={
                "thread_id": "thread-registry-fallback",
                "client_message_id": "client-registry-fallback",
                "input": [{"type": "text", "text": "hello"}],
            },
            context=context,
        )
        turn_id = started.response["result"]["runtime_start"]["turn_id"]
        task = context.runtime_task_registry.task("thread-registry-fallback", run_id=turn_id)
        assert task is not None

        # Cancel WITHOUT passing turn_id. The snapshot does carry the turn
        # here, but the point is that even if it didn't, the registry
        # fallback resolves turn_id. Assert we get an interrupting event,
        # not the idle "no active turn" response.
        outcome = await handle_turn_cancel_operation(
            request_id=2,
            params={"thread_id": "thread-registry-fallback", "include_snapshot": False},
            context=context,
        )
        result = outcome.response["result"]
        assert "status" not in result or result.get("status") != "idle"
        assert [event["method"] for event in result["events"]] == ["turn/interrupted", "core/runItem"]
        assert result["events"][1]["payload"]["status"] == "interrupting"
    finally:
        release.set()
        if task is not None:
            with pytest.raises(asyncio.CancelledError):
                await task
        await engine.dispose()


@pytest.mark.asyncio
async def test_force_cancel_persists_and_publishes_cancelled_terminal(tmp_path):
    llm = BlockingCoreLLM()
    engine, context = await _live_core_context(tmp_path, llm)
    thread_id = "thread-force-cancel"
    subscription = context.hub.subscribe(thread_id)
    try:
        started = await handle_turn_start_operation(
            request_id=1,
            params={
                "thread_id": thread_id,
                "client_message_id": "client-force-cancel",
                "input": [{"type": "text", "text": "block until cancelled"}],
            },
            context=context,
        )
        turn_id = started.response["result"]["runtime_start"]["turn_id"]
        await asyncio.wait_for(llm.started.wait(), timeout=1)
        task = context.runtime_task_registry.task(thread_id, run_id=turn_id)
        assert task is not None
        while not subscription.empty():
            subscription.get_nowait()

        interrupt = await handle_turn_cancel_operation(
            request_id=2,
            params={"thread_id": thread_id, "turn_id": turn_id},
            context=context,
        )
        assert interrupt.response["result"]["snapshot"]["core"]["turns"][turn_id]["status"] == "interrupting"

        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0)

        resumed = await handle_thread_resume_operation(
            request_id=3,
            params={"thread_id": thread_id, "last_seen_seq": 0},
            context=context,
        )
        result = resumed.response["result"]
        cancelled_events = [
            event
            for event in result["events"]
            if event["method"] == "core/runItem"
            and event["payload"].get("kind") == "status"
            and event["payload"].get("status") == "cancelled"
        ]
        published = []
        while not subscription.empty():
            published.append(subscription.get_nowait())

        assert len(cancelled_events) == 1
        assert cancelled_events[0]["turn_id"] == turn_id
        assert result["snapshot"]["turns"][turn_id]["status"] == "cancelled"
        assert result["snapshot"]["core"]["turns"][turn_id]["status"] == "cancelled"
        assert result["snapshot"]["status"] == "cancelled"
        assert result["snapshot"]["core"]["status"] == "cancelled"
        assert any(
            event.method == "core/runItem"
            and event.payload.get("status") == "cancelled"
            for event in published
        )
        runtime_state = await context.host.runtime_state_store.get(thread_id)
        assert runtime_state is not None
        assert runtime_state.status == "cancelled"

        runtime_state.status = "running"
        await context.host.runtime_state_store.save(runtime_state)
        await handle_thread_resume_operation(
            request_id=4,
            params={"thread_id": thread_id, "last_seen_seq": 0},
            context=context,
        )
        reconciled_state = await context.host.runtime_state_store.get(thread_id)
        assert reconciled_state is not None
        assert reconciled_state.status == "cancelled"
        assert context.runtime_task_registry.task(thread_id, run_id=turn_id) is None
    finally:
        context.hub.unsubscribe(thread_id, subscription)
        await engine.dispose()


@pytest.mark.asyncio
async def test_internal_cancelled_error_is_failed_not_user_interrupted(tmp_path):
    engine, context = await _context(tmp_path)

    async def turn_start(_request):
        raise asyncio.CancelledError("provider stream cancelled internally")

    context.operations.register("turn.start", turn_start)
    thread_id = "thread-internal-cancel"
    try:
        started = await handle_turn_start_operation(
            request_id=1,
            params={
                "thread_id": thread_id,
                "client_message_id": "client-internal-cancel",
                "input": [{"type": "text", "text": "start"}],
            },
            context=context,
        )
        turn_id = started.response["result"]["runtime_start"]["turn_id"]
        task = context.runtime_task_registry.task(thread_id, run_id=turn_id)
        assert task is not None
        await task

        resumed = await handle_thread_resume_operation(
            request_id=2,
            params={"thread_id": thread_id, "last_seen_seq": 0},
            context=context,
        )
        events = resumed.response["result"]["events"]
        terminal = [
            event for event in events
            if event["method"] == "core/runItem"
            and event["payload"].get("kind") == "status"
            and event["payload"].get("status") in {"failed", "cancelled"}
        ]

        assert [event["payload"]["status"] for event in terminal] == ["failed"]
        assert not any(event["method"] == "turn/interrupted" for event in events)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_cancelled_terminal_fallback_is_idempotent(tmp_path):
    engine, context = await _context(tmp_path)
    release = _register_blocking_turn_start(context)
    thread_id = "thread-cancel-idempotent"
    try:
        started = await handle_turn_start_operation(
            request_id=1,
            params={
                "thread_id": thread_id,
                "client_message_id": "client-cancel-idempotent",
                "input": [{"type": "text", "text": "cancel once"}],
            },
            context=context,
        )
        turn_id = started.response["result"]["runtime_start"]["turn_id"]

        await live_operations_module._persist_cancelled_terminal(
            context=context,
            thread_id=thread_id,
            turn_id=turn_id,
        )
        first = await handle_thread_resume_operation(
            request_id=2,
            params={"thread_id": thread_id, "last_seen_seq": 0},
            context=context,
        )
        await live_operations_module._persist_cancelled_terminal(
            context=context,
            thread_id=thread_id,
            turn_id=turn_id,
        )
        second = await handle_thread_resume_operation(
            request_id=3,
            params={"thread_id": thread_id, "last_seen_seq": 0},
            context=context,
        )

        cancelled_events = [
            event
            for event in second.response["result"]["events"]
            if event["method"] == "core/runItem" and event["payload"].get("status") == "cancelled"
        ]
        assert len(cancelled_events) == 1
        assert second.response["result"]["snapshot"]["snapshot_seq"] == first.response["result"]["snapshot"]["snapshot_seq"]
    finally:
        task = context.runtime_task_registry.task(thread_id)
        release.set()
        if task is not None:
            await task
        await engine.dispose()


@pytest.mark.asyncio
async def test_core_live_operation_host_uses_injected_persistence_and_runtime_registry(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'core-live-operation-host.db'}", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    event_store = SqlAlchemyAppEventStore(AppEventRow, protocol_version="core.app_server.v1")
    snapshot_store = SqlAlchemyThreadSnapshotStore(
        ThreadSnapshotRow,
        item_model=SnapshotItemRow,
        projector=CoreAppSnapshotProjector(member_defaults={"queue": []}),
    )

    class RuntimeRegistry:
        def __init__(self) -> None:
            self.cancel_calls: list[tuple[str, str | None, bool]] = []
            self.run_id: str | None = None

        def active_run_id(self, thread_id):
            _ = thread_id
            return self.run_id

        def accept_run(self, thread_id, run_id):
            _ = thread_id
            if self.run_id not in {None, run_id}:
                return False
            self.run_id = run_id
            return True

        def release_run(self, thread_id, *, run_id):
            _ = thread_id
            if self.run_id == run_id:
                self.run_id = None

        def register(self, thread_id, task, *, run_id=None) -> bool:
            _ = (thread_id, task, run_id)
            return True

        def cancel(self, thread_id, *, run_id=None, force=False) -> None:
            self.cancel_calls.append((thread_id, run_id, force))

    runtime_registry = RuntimeRegistry()
    persistence = AppPersistenceHost(event_store, snapshot_store)
    host = CoreLiveOperationHost(
        session_factory=session_factory,
        persistence=persistence,
        hub=CoreAppEventHub(),
        runtime_task_registry=runtime_registry,
    )
    context = CoreLiveContext(host=host, operations=OperationCatalog())

    async def turn_start(_request):
        return OperationResult(name="turn.start")

    context.operations.register("turn.start", turn_start)
    try:
        assert context.persistence is persistence
        assert set(host.operation_handlers()) == set(CORE_WORKBENCH_OPERATION_NAMES)

        started = await handle_turn_start_operation(
            request_id=1,
            params={
                "thread_id": "thread-host",
                "client_message_id": "client-host",
                "input": [{"type": "text", "text": "hello"}],
            },
            context=context,
        )
        turn_id = started.response["result"]["runtime_start"]["turn_id"]
        await handle_turn_cancel_operation(
            request_id=2,
            params={"thread_id": "thread-host", "turn_id": turn_id},
            context=context,
        )

        assert runtime_registry.cancel_calls == [("thread-host", turn_id, True)]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure_mode",
    ["empty_message", "no_running_loop", "create_task_error", "register_rejected", "task_done"],
)
async def test_core_live_runtime_start_failure_releases_run_and_persists_failed_terminal(
    tmp_path, monkeypatch, failure_mode
):
    engine, context = await _context(tmp_path)

    async def turn_start(_request):
        return OperationResult(name="turn.start")

    context.operations.register("turn.start", turn_start)
    real_loop = asyncio.get_running_loop()
    input_items = [] if failure_mode == "empty_message" else [{"type": "text", "text": "start"}]

    if failure_mode == "no_running_loop":
        monkeypatch.setattr(live_operations_module, "_get_running_loop", lambda: (_ for _ in ()).throw(RuntimeError("no loop")))
    elif failure_mode == "create_task_error":
        class RaisingLoop:
            def create_task(self, coroutine):
                coroutine.close()
                raise RuntimeError("create task failed")

        monkeypatch.setattr(live_operations_module, "_get_running_loop", lambda: RaisingLoop())
    elif failure_mode == "register_rejected":
        monkeypatch.setattr(context.runtime_task_registry, "register", lambda *_args, **_kwargs: False)
    elif failure_mode == "task_done":
        class CompletedTaskLoop:
            def create_task(self, coroutine):
                coroutine.close()
                task = real_loop.create_future()
                task.set_result(None)
                return task

        monkeypatch.setattr(live_operations_module, "_get_running_loop", lambda: CompletedTaskLoop())

    thread_id = f"core-start-failure-{failure_mode}"
    try:
        failed = await handle_turn_start_operation(
            request_id=1,
            params={
                "thread_id": thread_id,
                "client_message_id": f"client-{failure_mode}",
                "input": input_items,
            },
            context=context,
        )
        turn_id = failed.response["result"]["runtime_start"]["turn_id"]

        assert context.runtime_task_registry.active_run_id(thread_id) is None
        assert failed.response["result"]["snapshot"]["status"] == "failed"
        assert failed.response["result"]["snapshot"]["turns"][turn_id]["status"] == "failed"

        monkeypatch.undo()
        retried = await handle_turn_start_operation(
            request_id=2,
            params={
                "thread_id": thread_id,
                "client_message_id": f"client-{failure_mode}-retry",
                "input": [{"type": "text", "text": "retry"}],
            },
            context=context,
        )
        assert "result" in retried.response
    finally:
        context.runtime_task_registry.clear()
        await engine.dispose()


@pytest.mark.asyncio
async def test_core_live_queue_operations_project_snapshot(tmp_path):
    engine, context = await _context(tmp_path)
    try:
        created = await handle_queue_create_operation(
            request_id=1,
            params={
                "thread_id": "thread-queue",
                "client_message_id": "client-queue",
                "input": [
                    {"type": "text", "text": "继续补充"},
                    {"type": "attachment", "attachment_id": "att-queue", "name": "draft.md"},
                ],
            },
            context=context,
        )
        queue_item = created.response["result"]["queue_item"]
        assert queue_item["status"] == "queued"
        assert created.response["result"]["snapshot"]["queue"][0]["queue_item_id"] == queue_item["queue_item_id"]
        assert created.response["result"]["snapshot"]["queue"][0]["input"][1]["attachment_id"] == "att-queue"

        updated = await handle_queue_update_operation(
            request_id=2,
            params={
                "thread_id": "thread-queue",
                "queue_item_id": queue_item["queue_item_id"],
                "text": "改成这个",
            },
            context=context,
        )
        assert updated.response["result"]["snapshot"]["queue"][0]["input"] == [{"type": "text", "text": "改成这个"}]

        deleted = await handle_queue_delete_operation(
            request_id=3,
            params={
                "thread_id": "thread-queue",
                "queue_item_id": queue_item["queue_item_id"],
            },
            context=context,
        )
        assert deleted.response["result"]["snapshot"]["queue"] == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_core_live_queue_update_rejects_unavailable_item_without_writing_event(tmp_path):
    engine, context = await _context(tmp_path)
    try:
        created = await handle_queue_create_operation(
            request_id=1,
            params={
                "thread_id": "thread-queue-stale",
                "client_message_id": "client-queue-stale",
                "input": [{"type": "text", "text": "before"}],
            },
            context=context,
        )
        queue_item_id = created.response["result"]["queue_item"]["queue_item_id"]
        await handle_queue_delete_operation(
            request_id=2,
            params={"thread_id": "thread-queue-stale", "queue_item_id": queue_item_id},
            context=context,
        )
        async with context.session_factory() as db:
            before_events = await context.persistence.list_thread(db, thread_id="thread-queue-stale")
            before_snapshot = await context.persistence.load(db, "thread-queue-stale")

        stale = await handle_queue_update_operation(
            request_id=3,
            params={
                "thread_id": "thread-queue-stale",
                "queue_item_id": queue_item_id,
                "text": "after",
            },
            context=context,
        )

        result = stale.response["result"]
        assert result["applied"] is False
        assert result["reason"] == "queue_item_unavailable"
        assert result["events"] == []
        assert result["snapshot"] == before_snapshot
        async with context.session_factory() as db:
            after_events = await context.persistence.list_thread(db, thread_id="thread-queue-stale")
        assert [event.event_id for event in after_events] == [event.event_id for event in before_events]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_core_live_queue_guidance_does_not_consume_when_the_runtime_task_is_not_active(tmp_path):
    engine, context = await _context(tmp_path)
    release = _register_blocking_turn_start(context)
    task = None
    try:
        started = await handle_turn_start_operation(
            request_id=1,
            params={"thread_id": "thread-guide", "input": [{"type": "text", "text": "start"}]},
            context=context,
        )
        turn_id = started.response["result"]["events"][0]["turn_id"]
        task = context.runtime_task_registry.task("thread-guide", run_id=turn_id)
        context.runtime_task_registry.release_run("thread-guide", run_id=turn_id)
        created = await handle_queue_create_operation(
            request_id=2,
            params={"thread_id": "thread-guide", "input": [{"type": "text", "text": "queued"}]},
            context=context,
        )
        queue_item_id = created.response["result"]["queue_item"]["queue_item_id"]

        guided = await handle_queue_guidance_operation(
            request_id=3,
            params={
                "thread_id": "thread-guide",
                "turn_id": turn_id,
                "queue_item_id": queue_item_id,
                "text": "edited guidance",
            },
            context=context,
        )

        assert guided.response["result"]["applied"] is False
        assert guided.response["result"]["reason"] == "run_not_active"
        assert guided.response["result"]["events"] == []
        assert [item["queue_item_id"] for item in guided.response["result"]["snapshot"]["queue"]] == [queue_item_id]

        created_again = await handle_queue_create_operation(
            request_id=4,
            params={"thread_id": "thread-guide", "input": [{"type": "text", "text": "keep me"}]},
            context=context,
        )
        queue_item_id_2 = created_again.response["result"]["queue_item"]["queue_item_id"]
        rejected = await handle_queue_guidance_operation(
            request_id=5,
            params={
                "thread_id": "thread-guide",
                "turn_id": "wrong-turn",
                "queue_item_id": queue_item_id_2,
            },
            context=context,
        )

        assert rejected.response["result"]["applied"] is False
        assert rejected.response["result"]["reason"] == "active_turn_mismatch"
        assert [item["queue_item_id"] for item in rejected.response["result"]["snapshot"]["queue"]] == [
            queue_item_id,
            queue_item_id_2,
        ]
    finally:
        release.set()
        if task is not None:
            await task
        await engine.dispose()


# ---------------------------------------------------------------------------
# recover_stale_active_turns: close dangling tool_call items on restart
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recover_closes_non_terminal_tool_call_items(tmp_path):
    """On restart, recover must append a cancelled tool_result event for every
    non-terminal tool_call left by an unexpected shutdown, so the event stream
    is self-consistent (no orphaned ``running`` items)."""
    engine, context = await _context(tmp_path)
    try:
        thread_id = "thread-recover"
        turn_id = f"{thread_id}:turn:abc123"
        tool_item_id = f"{thread_id}:{turn_id}:call_halfbaked:tool"
        # Build a running turn + a running tool_call directly (simulating a
        # crash mid-stream, with no live runtime task to clean up).
        async def write_running(db):
            return await context.persistence.append_batch(
                db,
                run_item_events=[
                    RunItemEvent(
                        kind="status",
                        thread_id=thread_id,
                        event_id=f"{turn_id}:running",
                        run_id=turn_id,
                        turn_id=turn_id,
                        item_id=f"{turn_id}:running",
                        status="running",
                        payload={"type": "turn", "status": "running"},
                    ),
                    RunItemEvent(
                        kind="tool_call",
                        thread_id=thread_id,
                        event_id="tool-halfbaked",
                        run_id=turn_id,
                        turn_id=turn_id,
                        item_id=tool_item_id,
                        status="running",
                        payload={"type": "dynamicToolCall", "tool_name": "run_command", "arguments": {}},
                    ),
                ],
            )
        await context.persistence.write(write_running)

        recovered = await recover_stale_active_turns(context=context)
        assert recovered >= 1

        async with context.session_factory() as db:
            snapshot = await context.persistence.load(db, thread_id)
            events = await context.persistence.list_thread(db, thread_id=thread_id)

        # The turn is now cancelled.
        assert snapshot["core"]["turns"][turn_id]["status"] == "cancelled"
        # The dangling tool_call item is now cancelled in the snapshot.
        tool_item = snapshot["core"]["items"].get(tool_item_id)
        assert tool_item is not None
        assert tool_item["status"] == "cancelled"
        # A per-item cancelled tool_result event was appended to the event log.
        # The envelope payload is RunItemEvent.to_dict(): top-level "status" +
        # nested "payload" dict holding raw_end_reason.
        tool_events = [e for e in events if e.item_id == tool_item_id]
        assert any(
            e.payload.get("status") == "cancelled"
            and e.payload.get("payload", {}).get("raw_end_reason") == "unexpected_shutdown"
            for e in tool_events
        ), "expected a per-item cancelled tool_result event in the event log"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_force_reset_closes_dangling_items_on_already_cancelled_turn(tmp_path):
    """turn.force_reset must reach a turn even after recovery marked it
    cancelled (where turn.cancel returns idle), closing any remaining
    dangling items and returning the refreshed snapshot."""
    engine, context = await _context(tmp_path)
    try:
        thread_id = "thread-reset"
        turn_id = f"{thread_id}:turn:def456"
        tool_item_id = f"{thread_id}:{turn_id}:call_orphan:tool"
        async def write_running(db):
            return await context.persistence.append_batch(
                db,
                run_item_events=[
                    RunItemEvent(
                        kind="status",
                        thread_id=thread_id,
                        event_id=f"{turn_id}:running",
                        run_id=turn_id,
                        turn_id=turn_id,
                        item_id=f"{turn_id}:running",
                        status="running",
                        payload={"type": "turn", "status": "running"},
                    ),
                    RunItemEvent(
                        kind="tool_call",
                        thread_id=thread_id,
                        event_id="tool-orphan",
                        run_id=turn_id,
                        turn_id=turn_id,
                        item_id=tool_item_id,
                        status="running",
                        payload={"type": "dynamicToolCall", "tool_name": "run_command", "arguments": {}},
                    ),
                ],
            )
        await context.persistence.write(write_running)
        # Recover first (marks the turn cancelled + closes the orphan).
        await recover_stale_active_turns(context=context)

        # turn.cancel should now return idle (the stuck-state).
        cancel_outcome = await handle_turn_cancel_operation(
            request_id=2,
            params={"thread_id": thread_id, "turn_id": turn_id},
            context=context,
        )
        assert cancel_outcome.response["result"]["status"] == "idle"

        # force_reset bypasses the active guard and resets.
        reset_outcome = await handle_turn_force_reset_operation(
            request_id=3,
            params={"thread_id": thread_id, "turn_id": turn_id},
            context=context,
        )
        result = reset_outcome.response["result"]
        assert result["status"] == "reset"
        assert result["snapshot"]["core"]["turns"][turn_id]["status"] == "cancelled"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_force_reset_on_idle_thread_returns_reset_with_no_events(tmp_path):
    """force_reset on a thread with no turns at all should not crash."""
    engine, context = await _context(tmp_path)
    try:
        outcome = await handle_turn_force_reset_operation(
            request_id=1,
            params={"thread_id": "thread-empty"},
            context=context,
        )
        result = outcome.response["result"]
        assert result["status"] == "reset"
        assert result["events"] == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_turn_start_releases_registry_claim_before_trailing_cleanup(tmp_path):
    """After start_runtime returns (turn completed, terminal events persisted
    live), the registry claim must be released *before* trailing cleanup
    (_persist_operation_result, _ensure_turn_terminal, _dispatch_next_queue_item)
    runs. Those steps do DB I/O that yields the event loop; if release_run is
    deferred to after them, an SSE round-trip can race ahead and let the client
    fire a new turn.start that hits "active turn already exists" from the
    stale registry entry."""
    engine, context = await _context(tmp_path)

    # Track whether trailing cleanup has started yet when the registry claim
    # is released. If release_run runs after start_runtime returns but before
    # cleanup, the claim is gone before cleanup begins.
    cleanup_started = asyncio.Event()
    registry_released_before_cleanup = asyncio.Event()

    async def turn_start(_request):
        return OperationResult(name="turn.start")

    context.operations.register("turn.start", turn_start)

    # Wrap _dispatch_next_queue_item to signal that trailing cleanup has begun.
    original_dispatch = live_operations_module._dispatch_next_queue_item

    async def tracking_dispatch(*args, **kwargs):
        cleanup_started.set()
        if context.runtime_task_registry.active_run_id(kwargs.get("completed_turn_id", "")) is None:
            registry_released_before_cleanup.set()
        return await original_dispatch(*args, **kwargs)

    live_operations_module._dispatch_next_queue_item = tracking_dispatch
    try:
        outcome = await handle_turn_start_operation(
            request_id=1,
            params={
                "thread_id": "thread-race",
                "client_message_id": "client-1",
                "input": [{"type": "text", "text": "hello"}],
            },
            context=context,
        )
        turn_id = outcome.response["result"]["runtime_start"]["turn_id"]

        # Wait for the background task to complete.
        task = context.runtime_task_registry.task("thread-race")
        if task is not None:
            await task

        # The registry claim must be released by now.
        assert context.runtime_task_registry.active_run_id("thread-race") is None

        # And it must have been released *before* trailing cleanup began.
        assert registry_released_before_cleanup.is_set(), (
            "release_run did not run before trailing cleanup — "
            "the race window that causes 'active turn already exists' is still open"
        )
    finally:
        live_operations_module._dispatch_next_queue_item = original_dispatch
        context.runtime_task_registry.clear()
        await engine.dispose()


@pytest.mark.asyncio
async def test_completed_turn_does_not_block_next_turn_start(tmp_path):
    """After a turn completes normally and its terminal status is persisted to
    the snapshot, a new turn.start on the same thread must succeed — the
    registry claim must already be released so the active-turn guard does not
    reject it with 'active turn already exists'."""
    llm = BlockingCoreLLM()
    engine, context = await _live_core_context(tmp_path, llm)
    try:
        # Start first turn.
        outcome = await handle_turn_start_operation(
            request_id=1,
            params={
                "thread_id": "thread-consecutive",
                "client_message_id": "client-1",
                "input": [{"type": "text", "text": "hello"}],
            },
            context=context,
        )
        assert "result" in outcome.response

        # Let the turn complete.
        await llm.started.wait()
        llm.release.set()
        task = context.runtime_task_registry.task("thread-consecutive")
        if task is not None:
            await task

        # Registry claim must be gone.
        assert context.runtime_task_registry.active_run_id("thread-consecutive") is None

        # Second turn.start must succeed, not hit "active turn already exists".
        second = await handle_turn_start_operation(
            request_id=2,
            params={
                "thread_id": "thread-consecutive",
                "client_message_id": "client-2",
                "input": [{"type": "text", "text": "again"}],
            },
            context=context,
        )
        assert "result" in second.response, (
            f"second turn.start was rejected: {second.response.get('error', {}).get('message')}"
        )
        second_task = context.runtime_task_registry.task("thread-consecutive")
        if second_task is not None:
            context.runtime_task_registry.clear()
    finally:
        context.runtime_task_registry.clear()
        await engine.dispose()


async def test_ensure_turn_terminal_does_not_complete_waiting_turn(tmp_path):
    """Audit 01 S1 regression: a turn waiting for approval must not be
    backfilled as completed, or the queue would dispatch the next item
    without approval and two kernels would run concurrently."""
    llm = BlockingCoreLLM()
    engine, context = await _live_core_context(tmp_path, llm)
    thread_id = "thread-waiting-approval"
    turn_id = "turn-waiting-1"

    async def write_initial(db):
        envelopes = []
        envelopes.append(await live_operations_module._append_run_item(db, context=context, event=RunItemEvent(
            kind="queue", thread_id=thread_id, event_id="q1-accept", item_id="q1",
            payload={"queue_item_id": "q1", "status": "queued", "mode": "next_turn",
                     "input": [{"type": "text", "text": "next"}]},
        )))
        envelopes.append(await live_operations_module._append_run_item(db, context=context, event=RunItemEvent(
            kind="status", thread_id=thread_id, event_id="t-running", turn_id=turn_id,
            item_id=f"{turn_id}:running", status="running", payload={"type": "turn"},
        )))
        envelopes.append(await live_operations_module._append_run_item(db, context=context, event=RunItemEvent(
            kind="status", thread_id=thread_id, event_id="t-waiting", turn_id=turn_id,
            item_id=f"{turn_id}:waiting", status="waiting", payload={"type": "turn"},
        )))
        return envelopes

    await context.persistence.write(write_initial)

    await _ensure_turn_terminal(context=context, thread_id=thread_id, turn_id=turn_id)

    async with context.session_factory() as db:
        snapshot = await context.persistence.load(db, thread_id)
        events = await context.persistence.list_after(db, thread_id=thread_id, after_seq=0)
    assert snapshot["core"]["turns"][turn_id]["status"] == "waiting"
    # Thread-level status must not be flipped to completed either.
    assert snapshot["core"]["status"] != "completed"
    assert not any(
        env.payload.get("event_id") == f"{turn_id}:terminal"
        for env in events
    ), "waiting turn was wrongly marked completed"
    await engine.dispose()
