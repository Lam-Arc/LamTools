"""user:“该修修，该重构重构，有必要就重新设计架构或者迁到 Rust”+(验收恢复后终止、取消事务与有限收尾)。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from lamtools_core.app.live import background, interactions, runtime_tasks, terminal_state, turn_cancel, turn_pause
from lamtools_core.app.sqlite_write import SQLiteWriteCoordinator
from lamtools_core.kernel import CoreLoopKernel
from lamtools_core.runtime import RuntimeTaskRegistry


def context(registry):
    return SimpleNamespace(host=SimpleNamespace(runtime_task_registry=registry))


async def running(registry, run="execution-2", turn="turn-1"):
    started = asyncio.Event()

    async def work():
        started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(work())
    registry.register("thread", task, run_id=run, turn_id=turn)
    await started.wait()
    return task


@pytest.mark.asyncio
async def test_resumed_turn_is_cancelled_by_logical_turn_id(monkeypatch):
    registry = RuntimeTaskRegistry()
    task = await running(registry)
    finalizer = AsyncMock()
    monkeypatch.setattr(turn_cancel, "_turn_cancel_finalizer", finalizer)
    try:
        await turn_cancel.handle_turn_terminate_operation(request_id=1,
            params={"thread_id": "thread", "turn_id": "turn-1"}, context=context(registry))
        assert registry.get_cancel_event("thread").is_set()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await background.wait_live_background_tasks()


@pytest.mark.asyncio
async def test_stale_termination_never_schedules_session_cleanup(monkeypatch):
    registry = RuntimeTaskRegistry()
    task = await running(registry)
    finalizer = AsyncMock()
    monkeypatch.setattr(turn_cancel, "_turn_cancel_finalizer", finalizer)
    try:
        result = await turn_cancel.handle_turn_terminate_operation(request_id=1,
            params={"thread_id": "thread", "turn_id": "old-turn"}, context=context(registry))
        await background.wait_live_background_tasks()
        assert result.response["result"]["status"] == "stale_target"
        finalizer.assert_not_called()
        assert not registry.get_cancel_event("thread").is_set()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_repeated_termination_has_only_one_finalizer(monkeypatch):
    registry = RuntimeTaskRegistry()
    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0

    async def finalize(**kwargs):
        nonlocal calls
        calls += 1
        entered.set()
        await release.wait()

    monkeypatch.setattr(turn_cancel, "_turn_cancel_finalizer", finalize)
    ctx = context(registry)
    try:
        await turn_cancel.handle_turn_terminate_operation(request_id=1,
            params={"thread_id": "thread", "turn_id": "turn-1"}, context=ctx)
        await entered.wait()
        for i in range(20):
            await turn_cancel.handle_turn_terminate_operation(request_id=i+2,
                params={"thread_id": "thread", "turn_id": "turn-1"}, context=ctx)
        await asyncio.sleep(0)
        assert calls == 1
    finally:
        release.set()
        await background.wait_live_background_tasks()


@pytest.mark.asyncio
async def test_database_failure_does_not_skip_members_or_other_cleanup(monkeypatch):
    registry = RuntimeTaskRegistry()
    order = []

    async def record(**kwargs):
        order.append("database")
        raise RuntimeError("database is locked")

    async def members(**kwargs):
        order.append("members")

    monkeypatch.setattr(turn_cancel, "_append_interrupting_record", record)
    monkeypatch.setattr(turn_cancel, "_interrupt_session_members", members)
    settle, close, terminal, mirror = (AsyncMock() for _ in range(4))
    monkeypatch.setattr(turn_pause, "_settle_thread_continuations", settle)
    monkeypatch.setattr(interactions, "_close_open_interactions", close)
    monkeypatch.setattr(terminal_state, "_persist_cancelled_terminal", terminal)
    monkeypatch.setattr(runtime_tasks, "_mirror_turn_status", mirror)
    with pytest.raises(ExceptionGroup) as failure:
        await turn_cancel._turn_cancel_finalizer(context=context(registry), thread_id="thread",
            requested_turn_id="turn-1", expected_revision=None, live_turn_id="",
            preempted_live_task=False, terminate=True)
    assert "database is locked" in str(failure.value.exceptions[0])
    assert order[:2] == ["members", "database"]
    settle.assert_awaited_once()
    close.assert_awaited_once()
    terminal.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancel_before_kernel_trace_initialization_preserves_cancellation(monkeypatch):
    kernel = CoreLoopKernel(kit=None, llm_client=None, state_store=None, event_sink=None)
    entered = asyncio.Event()

    async def setup(self, turn_input):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(CoreLoopKernel, "_run", setup)
    persist = AsyncMock()
    monkeypatch.setattr(CoreLoopKernel, "_persist_external_cancellation", persist)
    task = asyncio.create_task(kernel.run(SimpleNamespace()))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.gather(*kernel._background_finalizers)
    persist.assert_awaited_once()


@pytest.mark.asyncio
async def test_repeated_cancel_drains_database_transaction_before_releasing_writer(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'cancel.db'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    writer = SQLiteWriteCoordinator(factory)
    async with engine.begin() as db:
        await db.execute(text("CREATE TABLE evidence (value INTEGER)"))
    entered, release, follower_entered, interrupted = (asyncio.Event() for _ in range(4))

    async def action(db):
        await db.execute(text("INSERT INTO evidence VALUES (1)"))
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            interrupted.set()
            raise

    async def follower(db):
        follower_entered.set()
        await db.execute(text("INSERT INTO evidence VALUES (2)"))

    task = asyncio.create_task(writer.run(action))
    other = None
    try:
        await entered.wait()
        task.cancel()
        await asyncio.sleep(0)
        assert not interrupted.is_set(), "task cancellation must not reach the database driver"
        task.cancel()
        await asyncio.sleep(0)
        other = asyncio.create_task(writer.run(follower))
        await asyncio.sleep(0)
        assert not task.done(), "the cancelled writer must drain its transaction"
        assert not follower_entered.is_set(), "a second writer cannot overtake rollback"
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        await other
        async with factory() as db:
            assert list((await db.execute(text("SELECT value FROM evidence"))).scalars()) == [2]
    finally:
        release.set()
        await asyncio.gather(task, *([other] if other else []), return_exceptions=True)
        await engine.dispose()


@pytest.mark.asyncio
async def test_resumed_termination_reaches_durable_cancelled_state(tmp_path):
    from lamtools_core.app import OperationCatalog, open_core_app_db
    from lamtools_core.app.live.context import CoreLiveContext
    from lamtools_core.app.live_hub import CoreAppEventHub
    from lamtools_core.event import RunItemEvent
    from lamtools_core.runtime import InMemoryRuntimeStateStore, RuntimeState

    db = await open_core_app_db(tmp_path / "real.db")
    registry = RuntimeTaskRegistry()
    store = InMemoryRuntimeStateStore()
    await store.save(RuntimeState(session_id="thread", run_id="execution-2", status="running",
        metadata={"turn_id": "turn-1"}))
    ctx = CoreLiveContext(operations=OperationCatalog(), session_factory=db.session_factory,
        persistence=db.persistence, runtime_state_store=store, runtime_task_registry=registry,
        hub=CoreAppEventHub())

    async def seed(session):
        await db.persistence.append_run_item(session, RunItemEvent(kind="status", thread_id="thread",
            event_id="execution-2:running", run_id="execution-2", turn_id="turn-1",
            item_id="turn-1:status", status="running", payload={"type": "turn", "status": "running"}))

    await db.persistence.write(seed)
    task = await running(registry)
    try:
        result = await turn_cancel.handle_turn_terminate_operation(request_id=1,
            params={"thread_id": "thread", "turn_id": "turn-1"}, context=ctx)
        assert result.response["result"]["status"] == "cancelling"
        await background.wait_live_background_tasks()
        assert task.cancelled()
        assert not registry.active_run_id("thread")
        assert (await store.get("thread")).status == "cancelled"
        async with db.session_factory() as session:
            snapshot = await db.persistence.load(session, "thread")
        assert snapshot["core"]["turns"]["turn-1"]["status"] == "cancelled"
        assert not turn_cancel._CANCEL_FINALIZERS
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await background.wait_live_background_tasks()
        await db.close()


@pytest.mark.asyncio
async def test_late_finalizer_cannot_touch_a_new_generation(monkeypatch):
    registry = RuntimeTaskRegistry()
    registry.accept_run("thread", "old-execution", turn_id="old-turn")
    old_generation = registry.control_generation("thread")
    registry.release_run("thread", run_id="old-execution")
    task = await running(registry, run="new-execution", turn="new-turn")
    members, record = AsyncMock(), AsyncMock()
    monkeypatch.setattr(turn_cancel, "_interrupt_session_members", members)
    monkeypatch.setattr(turn_cancel, "_append_interrupting_record", record)
    try:
        await turn_cancel._turn_cancel_finalizer(context=context(registry), thread_id="thread",
            requested_turn_id="old-turn", live_turn_id="old-execution", expected_revision=None,
            preempted_live_task=True, terminate=True, generation=old_generation)
        members.assert_not_called()
        record.assert_not_called()
        assert registry.active_run_id("thread") == "new-execution"
        assert not registry.get_cancel_event("thread").is_set()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
