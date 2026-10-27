"""Fault injection at commit/notification and acceptance boundaries."""
import asyncio
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event
from sqlalchemy.exc import OperationalError

from lamtools_core.app import OperationCatalog, open_core_app_db
from lamtools_core.app.core_session_store import CoreDbSessionStore
from lamtools_core.app.live_operations import CoreLiveContext, wait_live_background_tasks
from lamtools_core.app.operation_catalog import OperationResult
from lamtools_core.runtime import RuntimeState, RuntimeTaskRegistry
from lamtools_core.session import SessionRecord


@pytest.mark.asyncio
async def test_169_steps_reuse_connections_under_concurrent_reads_and_writes(tmp_path):
    db = await open_core_app_db(tmp_path / "core.db")
    connections = []
    event.listen(db.engine.sync_engine, "connect", lambda *args: connections.append(1))
    try:
        async def write_steps(worker):
            state = RuntimeState(session_id=f"child-{worker}", run_id=f"run-{worker}", status="running")
            for step in range(169):
                state.metadata["step"] = step
                await db.runtime_state_store.save(state)

        async def read_steps():
            for _ in range(169):
                await db.sync_journal.sync(cursor=0, limit=10)

        results = await asyncio.gather(*(write_steps(i) for i in range(3)), read_steps(), read_steps(), return_exceptions=True)
        assert not [r for r in results if isinstance(r, BaseException)], results
        assert len(connections) <= 8, "connection setup must be bounded across a long turn"
        for i in range(3):
            assert (await db.runtime_state_store.get(f"child-{i}")).metadata["step"] == 168
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_failed_terminal_write_is_repaired_before_next_message(tmp_path, monkeypatch):
    db = await open_core_app_db(tmp_path / "core.db")
    operations = OperationCatalog()
    release = asyncio.Event()
    second_release = asyncio.Event()
    original_write = db.persistence.write
    calls = 0
    async def run(request):
        nonlocal calls
        calls += 1
        await release.wait()
        if calls == 1:
            async def fail_terminal(action):
                monkeypatch.setattr(db.persistence, "write", original_write)
                raise OperationalError("BEGIN IMMEDIATE", {}, Exception("database is locked"))
            monkeypatch.setattr(db.persistence, "write", fail_terminal)
            raise RuntimeError("runtime failed")
        await second_release.wait()
        return OperationResult(name="turn.start", status="error", payload={"error": "finished"})
    operations.register("turn.start", run)
    context = CoreLiveContext(session_factory=db.session_factory, persistence=db.persistence,
        operations=operations, runtime_task_registry=RuntimeTaskRegistry())
    params = {"thread_id": "failed-turn", "client_message_id": "first", "include_snapshot": False,
        "input": [{"type": "text", "text": "task"}]}
    try:
        first = await context.host.execute("turn.start", request_id=1, params=params, context=context)
        old_turn = first.runtime_start["turn_id"]
        task = context.runtime_task_registry.task("failed-turn")
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        assert context.runtime_task_registry.active_run_id("failed-turn") is None
        next_message = await context.host.execute("turn.start", request_id=2,
            params={**params, "client_message_id": "second"}, context=context)
        assert "error" not in next_message.response, next_message.response
        async with db.session_factory() as session:
            snapshot = await db.persistence.load_metadata(session, "failed-turn")
        assert snapshot["turns"][old_turn]["status"] == "failed"
        assert (await context.turn_store.get_turn(old_turn)).status == "failed"
        assert not context.host.pending_terminal_failures
    finally:
        release.set()
        second_release.set()
        monkeypatch.setattr(db.persistence, "write", original_write)
        task = context.runtime_task_registry.task("failed-turn")
        if task:
            await asyncio.gather(task, return_exceptions=True)
        context.runtime_task_registry.clear()
        await wait_live_background_tasks()
        await db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["read", "publish"])
async def test_sync_notification_failure_does_not_fail_committed_writes(tmp_path, monkeypatch, failure):
    db = await open_core_app_db(tmp_path / "core.db")
    publisher = AsyncMock()
    sessions = CoreDbSessionStore(lambda: db, sync_publisher=publisher)
    sessions.set_sync_journal(db.sync_journal)
    db.runtime_state_store.set_sync_publisher(publisher)
    db.project_store.set_sync_publisher(publisher)
    original_get = db.sync_journal.get_change
    if failure == "read":
        monkeypatch.setattr(db.sync_journal, "get_change", AsyncMock(side_effect=OperationalError(
            "SELECT core_sync_changes", {}, Exception("database is locked"),
        )))
    else:
        publisher.side_effect = RuntimeError("notification unavailable")
    try:
        await db.runtime_state_store.save(RuntimeState(session_id="failed", run_id="run", status="failed"))
        await sessions.create(SessionRecord(id="session", member_id="core", status="idle", title="Saved"))
        project, _ = await db.project_store.create(tmp_path / "workspace", name="Saved project")
        assert (await db.runtime_state_store.get("failed")).status == "failed"
        assert (await sessions.get("session")).title == "Saved"
        assert project.name == "Saved project"
        # Notification loss must retain durable changes for cursor replay.
        monkeypatch.setattr(db.sync_journal, "get_change", original_get)
        delta = await db.sync_journal.sync(cursor=0)
        assert {c["entity_type"] for c in delta["changes"]} >= {"thread", "project"}
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_retry_during_uncommitted_acceptance_gets_receipt_not_busy(tmp_path, monkeypatch):
    db = await open_core_app_db(tmp_path / "core.db")
    operations = OperationCatalog()
    runtime_started = asyncio.Event()
    finish = asyncio.Event()
    async def hold(request):
        runtime_started.set()
        await finish.wait()
        return OperationResult(name="turn.start", status="ok")
    operations.register("turn.start", hold)
    context = CoreLiveContext(session_factory=db.session_factory, persistence=db.persistence,
        operations=operations, runtime_task_registry=RuntimeTaskRegistry())
    claimed, commit = asyncio.Event(), asyncio.Event()
    original_append = db.persistence.append_batch
    async def hold_acceptance(*args, **kwargs):
        claimed.set()
        await commit.wait()
        return await original_append(*args, **kwargs)
    monkeypatch.setattr(db.persistence, "append_batch", hold_acceptance)
    params = {"thread_id": "race", "client_message_id": "once", "include_snapshot": False,
        "input": [{"type": "text", "text": "task"}]}
    first = asyncio.create_task(context.host.execute("turn.start", request_id=1, params=params, context=context))
    retry = None
    try:
        await claimed.wait()
        # Force the retry's receipt lookup to observe the pre-commit state.
        looked_up = asyncio.Event()
        original_find = db.persistence.find_client_event
        async def observe_lookup(*args, **kwargs):
            result = await original_find(*args, **kwargs)
            looked_up.set()
            return result
        monkeypatch.setattr(db.persistence, "find_client_event", observe_lookup)
        retry = asyncio.create_task(context.host.execute("turn.start", request_id=2, params=params, context=context))
        await looked_up.wait()
        commit.set()
        accepted, repeated = await asyncio.gather(first, retry)
        assert "error" not in repeated.response, repeated.response
        assert repeated.response["result"]["events"][0]["turn_id"] == accepted.runtime_start["turn_id"]
        assert repeated.runtime_start is None
    finally:
        commit.set()
        task = context.runtime_task_registry.task("race")
        finish.set()
        await asyncio.gather(*(t for t in (first, retry) if t is not None), return_exceptions=True)
        if task:
            await task
        context.runtime_task_registry.clear()
        await wait_live_background_tasks()
        await db.close()
