"""Fault-injection contracts for required Workflow queue and recovery writes."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from lamtools_core.app.operation_catalog import OperationRequest
from lamtools_core.plugin_system.context import PluginContext
from lamtools_core.plugins.bundled.workflow.backend import operations
from lamtools_core.plugins.bundled.workflow.backend.cache import WorkflowContentCache
from lamtools_core.plugins.bundled.workflow.backend.durable import WorkflowRunEventStore
from lamtools_core.plugins.bundled.workflow.backend.persistence import WorkflowPersistenceError
from lamtools_core.plugins.bundled.workflow.backend.queue import WorkflowQueueItem, WorkflowQueueStore, WorkflowRunQueue
from lamtools_core.plugins.bundled.workflow.backend.runtime import WorkflowDef, WorkflowNode, WorkflowPort, WorkflowRunner, WorkflowRunResult
from lamtools_core.plugins.bundled.workflow.backend.snapshots import WorkflowSnapshotStore
from lamtools_core.plugins.bundled.workflow.backend.store import WorkflowStore


def unavailable(*args, **kwargs):
    raise OSError("disk full")


def definition(tmp_path: Path) -> WorkflowDef:
    return WorkflowDef(id="wf-persist", name="persist", work_root=str(tmp_path), nodes=[
        WorkflowNode(id="one", kind="content", ports=[WorkflowPort(name="out", direction="out", value=1)]),
    ])


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["create", "update", "delete", "clear"])
async def test_queue_failed_mutation_preserves_committed_state_and_retries(tmp_path, monkeypatch, mutation):
    store = WorkflowQueueStore(path=tmp_path / "queue.json")
    saved = WorkflowQueueItem(queue_id="q", workflow_name="persist")
    await store.save(saved)
    before = store.path.read_bytes()
    writer = store._write_sync
    monkeypatch.setattr(store, "_write_sync", unavailable)

    async def mutate():
        if mutation == "create":
            await store.save(WorkflowQueueItem(queue_id="new", workflow_name="persist"))
        elif mutation == "update":
            saved.status = "completed"
            await store.save(saved)
        elif mutation == "delete":
            await store.delete("q")
        else:
            await store.clear(predicate=lambda item: True, confirm=True)

    with pytest.raises(WorkflowPersistenceError, match="disk full"):
        await mutate()
    assert store.path.read_bytes() == before
    assert (await store.get("q")).status == "queued"
    assert await store.get("new") is None
    monkeypatch.setattr(store, "_write_sync", writer)
    await mutate()
    fresh = WorkflowQueueStore(path=store.path)
    assert [item.to_storage_dict() for item in await store.values()] == [item.to_storage_dict() for item in await fresh.values()]


@pytest.mark.asyncio
@pytest.mark.parametrize("contents", ["broken", "{}", "12", '{"items":[12]}'])
async def test_invalid_queue_is_not_silently_overwritten_and_can_be_repaired(tmp_path, contents):
    path = tmp_path / "queue.json"
    path.write_text(contents, encoding="utf-8")
    store = WorkflowQueueStore(path=path)
    with pytest.raises(WorkflowPersistenceError):
        await store.save(WorkflowQueueItem(queue_id="new"))
    assert path.read_text(encoding="utf-8") == contents
    path.write_text(json.dumps({"version": 3, "items": [{"queue_id": "old", "priority": 0}]}), encoding="utf-8")
    await store.save(WorkflowQueueItem(queue_id="new"))
    assert {item.queue_id for item in await store.values()} == {"old", "new"}


@pytest.mark.asyncio
async def test_failed_fsync_leaves_original_file_and_removes_temp_file(tmp_path, monkeypatch):
    store = WorkflowQueueStore(path=tmp_path / "queue.json")
    await store.save(WorkflowQueueItem(queue_id="old"))
    before = store.path.read_bytes()
    monkeypatch.setattr("lamtools_core.plugins.bundled.workflow.backend.queue.os.fsync", unavailable)
    with pytest.raises(WorkflowPersistenceError):
        await store.save(WorkflowQueueItem(queue_id="new"))
    assert store.path.read_bytes() == before
    assert not list(tmp_path.glob(".workflow-queue-*.tmp"))
    assert await store.get("new") is None


@pytest.mark.asyncio
async def test_cancelled_writer_holds_lock_until_filesystem_commit_settles(tmp_path, monkeypatch):
    store = WorkflowQueueStore(path=tmp_path / "queue.json")
    entered, release = threading.Event(), threading.Event()
    original = store._write_sync

    def blocked_write():
        entered.set()
        assert release.wait(3)
        original()

    monkeypatch.setattr(store, "_write_sync", blocked_write)
    write = asyncio.create_task(store.save(WorkflowQueueItem(queue_id="q")))
    assert await asyncio.to_thread(entered.wait, 3)
    write.cancel()
    read = asyncio.create_task(store.values())
    await asyncio.sleep(0)
    assert not read.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await write
    assert [item.queue_id for item in await read] == ["q"]
    assert (await WorkflowQueueStore(path=store.path).get("q")) is not None


def context_for(tmp_path, queue):
    wf = definition(tmp_path)
    class Manager:
        async def get(self, *args, **kwargs):
            return wf
    return PluginContext(work_root=tmp_path, services={"workflow": SimpleNamespace(manager=Manager(), queue=queue)})


@pytest.mark.asyncio
async def test_enqueue_rpc_failure_reports_error_without_acceptance_or_execution(tmp_path, monkeypatch):
    events = []
    queue = WorkflowRunQueue(root=tmp_path, emit=events.append, auto_start=False)
    monkeypatch.setattr(queue.store, "_write_sync", unavailable)
    response = await operations.workflow_queue_enqueue(OperationRequest(name="workflow.queue.enqueue", payload={"name": "persist"}), context=context_for(tmp_path, queue))
    assert response.status == "error"
    assert response.payload["code"] == "WORKFLOW_PERSISTENCE_FAILED"
    assert response.payload["retryable"] is True
    assert events == []
    assert await queue.list() == []
    assert queue._worker is None


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["cancel", "clear"])
async def test_queue_mutation_rpc_failure_has_no_success_payload(tmp_path, monkeypatch, operation):
    queue = WorkflowRunQueue(root=tmp_path, auto_start=False)
    item = await queue.enqueue(definition(tmp_path), queue_id="q", auto_start=False)
    monkeypatch.setattr(queue.store, "_write_sync", unavailable)
    handler = getattr(operations, f"workflow_queue_{operation}")
    response = await handler(OperationRequest(name=f"workflow.queue.{operation}", payload={"queue_id": item.queue_id, "confirm": True, "all": True}), context=context_for(tmp_path, queue))
    assert response.status == "error"
    assert response.payload["code"] == "WORKFLOW_PERSISTENCE_FAILED"
    assert (await queue.store.get(item.queue_id)).status == "queued"


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_status", ["running", "completed", "failed", "paused", "cancelled"])
async def test_worker_survives_write_failure_and_recovers_without_repeating_execution(tmp_path, monkeypatch, failed_status):
    calls = 0
    failure_seen = asyncio.Event()
    events = []
    store = WorkflowQueueStore(path=tmp_path / "queue.json")
    original = store._write_sync
    broken = True

    def write():
        if broken and any(item.status == failed_status for item in store._items.values()):
            raise OSError("disk full")
        original()

    class Runner:
        async def run(self, wf, **kwargs):
            nonlocal calls
            calls += 1
            # Execution is permitted only after its running state is durable.
            assert (await WorkflowQueueStore(path=store.path).get("q")).status == "running"
            return WorkflowRunResult(status="completed" if failed_status == "running" else failed_status, run_id=kwargs["run_id"], values={"one.out": 1}, output=1)

    async def emit(event):
        events.append(event)
        if event.payload.get("persistence_error"):
            failure_seen.set()

    monkeypatch.setattr(store, "_write_sync", write)
    queue = WorkflowRunQueue(store=store, manager=object(), runner=Runner(), emit=emit)
    item = await queue.enqueue(definition(tmp_path), queue_id="q")
    try:
        await asyncio.wait_for(failure_seen.wait(), 3)
        assert not queue._worker.done()
        assert calls == (0 if failed_status == "running" else 1)
        projection = await queue.get("q")
        assert projection.status == "failed"
        assert projection.metadata["persistence_error"]["retry_pending"]
        assert [entry.queue_id for entry in await queue.list(status="failed", include_history=False)] == ["q"]
        assert [entry.queue_id for entry in await queue.history(status="failed")] == ["q"]
        with pytest.raises(WorkflowPersistenceError):
            await queue.wait("q", timeout=1)
        assert not any(event.payload["status"] == failed_status for event in events if not event.payload.get("persistence_error"))
        broken = False
        # Poll the durable state rather than bypassing the worker's retry loop.
        async def recovered():
            while "q" in queue._persistence_failures or (await queue.store.get("q")).status == "queued":
                await asyncio.sleep(.01)
        await asyncio.wait_for(recovered(), 4)
        expected = "completed" if failed_status == "running" else failed_status
        assert (await queue.wait("q", timeout=3)).status == expected
        assert (await WorkflowQueueStore(path=store.path).get("q")).status == expected
        assert calls == 1
        assert item.run_id == (await queue.get("q")).run_id
    finally:
        broken = False
        await queue.stop()


@pytest.mark.asyncio
async def test_failed_startup_recovery_does_not_start_worker_and_is_retryable(tmp_path, monkeypatch):
    store = WorkflowQueueStore(path=tmp_path / "queue.json")
    await store.save(WorkflowQueueItem(queue_id="q", workflow_name="persist", status="running"))
    original = store._write_sync
    monkeypatch.setattr(store, "_write_sync", unavailable)
    queue = WorkflowRunQueue(store=store, auto_start=False)
    with pytest.raises(WorkflowPersistenceError):
        await queue.start()
    assert not queue._started and queue._worker is None
    assert (await store.get("q")).status == "running"
    monkeypatch.setattr(store, "_write_sync", original)
    await queue.start()
    await queue.stop()


@pytest.mark.asyncio
async def test_snapshot_failed_save_or_delete_preserves_committed_checkpoint(tmp_path, monkeypatch):
    snapshots = WorkflowSnapshotStore(root=tmp_path)
    first = WorkflowRunResult(status="paused", run_id="r", values={"one.out": 1})
    await snapshots.save("t", "r", first)
    original = snapshots._write_sync
    monkeypatch.setattr(snapshots, "_write_sync", unavailable)
    with pytest.raises(WorkflowPersistenceError):
        await snapshots.save("t", "r", WorkflowRunResult(status="paused", values={"one.out": 2}))
    assert (await snapshots.get("t", "r")).values == first.values
    assert (await WorkflowSnapshotStore(root=tmp_path).get("t", "r")).values == first.values
    monkeypatch.setattr(snapshots, "_write_sync", original)
    await snapshots.save("t", "r", WorkflowRunResult(status="paused", values={"one.out": 2}))
    original_unlink = Path.unlink
    def unlink(path, *args, **kwargs):
        if path == snapshots.snapshot_path("t", "r"):
            raise OSError("read only")
        return original_unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", unlink)
    with pytest.raises(WorkflowPersistenceError):
        await snapshots.delete("t", "r")
    assert (await snapshots.get("t", "r")).values == {"one.out": 2}


@pytest.mark.asyncio
async def test_pre_effect_snapshot_failure_never_invokes_executor(tmp_path, monkeypatch):
    calls = 0
    class Agent:
        async def run(self, **kwargs):
            nonlocal calls
            calls += 1
            return SimpleNamespace(message='{"out":1}')
    wf = definition(tmp_path)
    wf.nodes[0].kind = "ai"
    wf.nodes[0].config = {"mode": "agent", "instruction": "execute"}
    snapshots = WorkflowSnapshotStore(root=tmp_path)
    monkeypatch.setattr(snapshots, "_write_sync", unavailable)
    runner = WorkflowRunner(sub_agent_runner=Agent(), snapshot_store=snapshots, event_store=WorkflowRunEventStore(root=tmp_path))
    with pytest.raises(WorkflowPersistenceError):
        await runner.run(wf, thread_id="t", run_id="r")
    assert calls == 0


@pytest.mark.asyncio
async def test_unreadable_snapshot_and_journal_are_errors_not_missing_state(tmp_path, monkeypatch):
    snapshots = WorkflowSnapshotStore(root=tmp_path)
    await snapshots.save("t", "r", WorkflowRunResult(status="paused"))
    journal = WorkflowRunEventStore(root=tmp_path)
    snapshot_path, journal_path = snapshots.snapshot_path("t", "r"), journal.event_path("r")
    original_read = Path.read_text
    def read(path, *args, **kwargs):
        if path in (snapshot_path, journal_path):
            raise OSError("access denied")
        return original_read(path, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", read)
    fresh = WorkflowSnapshotStore(root=tmp_path)
    with pytest.raises(WorkflowPersistenceError):
        await fresh.get("t", "r")
    with pytest.raises(WorkflowPersistenceError):
        await journal.list("r")
    monkeypatch.setattr(Path, "read_text", original_read)
    assert (await fresh.get("t", "r")).status == "paused"


@pytest.mark.asyncio
async def test_stop_flushes_pending_terminal_result_instead_of_pausing_finished_work(tmp_path, monkeypatch):
    queue = WorkflowRunQueue(root=tmp_path, auto_start=False)
    item = await queue.enqueue(definition(tmp_path), auto_start=False)
    item.status = "running"
    await queue.store.save(item)
    item.status = "completed"
    item.result = WorkflowRunResult(status="completed", output=1, run_id=item.run_id)
    writer = queue.store._write_sync
    monkeypatch.setattr(queue.store, "_write_sync", unavailable)
    with pytest.raises(WorkflowPersistenceError):
        await queue._save_execution_update(item)
    assert item.queue_id in queue._pending_updates
    monkeypatch.setattr(queue.store, "_write_sync", writer)
    # A worker may still own the item while awaiting the failed commit.
    queue._active_tasks[item.queue_id] = asyncio.create_task(asyncio.sleep(0))
    await queue.stop()
    fresh = await WorkflowQueueStore(path=queue.store.path).get(item.queue_id)
    assert fresh.status == "completed" and fresh.result.output == 1


@pytest.mark.asyncio
async def test_stop_during_terminal_write_keeps_completed_result(tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    store = WorkflowQueueStore(root=tmp_path)
    original = store._write_sync
    calls = 0
    def blocked_write():
        if any(item.status == "completed" for item in store._items.values()):
            entered.set()
            assert release.wait(3)
        original()
    class Runner:
        async def run(self, wf, **kwargs):
            nonlocal calls
            calls += 1
            return WorkflowRunResult(status="completed", output=1, run_id=kwargs["run_id"])
    monkeypatch.setattr(store, "_write_sync", blocked_write)
    queue = WorkflowRunQueue(store=store, manager=object(), runner=Runner())
    item = await queue.enqueue(definition(tmp_path))
    assert await asyncio.to_thread(entered.wait, 3)
    stop = asyncio.create_task(queue.stop())
    await asyncio.sleep(0)
    release.set()
    await asyncio.wait_for(stop, 3)
    fresh = await WorkflowQueueStore(path=store.path).get(item.queue_id)
    assert fresh.status == "completed" and fresh.result.output == 1
    assert calls == 1


@pytest.mark.asyncio
async def test_concurrent_explicit_cancel_and_stop_remains_terminal(tmp_path):
    entered = asyncio.Event()
    class Runner:
        async def run(self, wf, **kwargs):
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                # Let shutdown overlap the explicit cancellation.
                await asyncio.sleep(0)
                raise
    queue = WorkflowRunQueue(root=tmp_path, manager=object(), runner=Runner())
    item = await queue.enqueue(definition(tmp_path))
    await asyncio.wait_for(entered.wait(), 3)
    cancel = asyncio.create_task(queue.cancel(item.queue_id))
    await asyncio.sleep(0)
    stop = asyncio.create_task(queue.stop())
    results = await asyncio.wait_for(asyncio.gather(cancel, stop), 3)
    assert results[0].status == "cancelled"
    assert (await WorkflowQueueStore(path=queue.store.path).get(item.queue_id)).status == "cancelled"


@pytest.mark.asyncio
async def test_embedded_runner_shutdown_cancellation_preserves_partial_progress(tmp_path):
    entered = asyncio.Event()
    class Runner:
        async def run(self, wf, **kwargs):
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                return WorkflowRunResult(status="cancelled", values={"one.out": 1}, run_id=kwargs["run_id"])
    queue = WorkflowRunQueue(root=tmp_path, manager=object(), runner=Runner())
    item = await queue.enqueue(definition(tmp_path))
    await asyncio.wait_for(entered.wait(), 3)
    await queue.stop()
    fresh = await WorkflowQueueStore(path=queue.store.path).get(item.queue_id)
    assert fresh.status == "paused" and fresh.prior_values == {"one.out": 1}


@pytest.mark.asyncio
async def test_out_of_band_signal_result_keeps_pending_commit_for_write_only_retry(tmp_path, monkeypatch):
    queue = WorkflowRunQueue(root=tmp_path, auto_start=False)
    item = await queue.enqueue(definition(tmp_path), auto_start=False)
    item.status = "paused"
    await queue.store.save(item)
    writer = queue.store._write_sync
    monkeypatch.setattr(queue.store, "_write_sync", unavailable)
    with pytest.raises(WorkflowPersistenceError):
        await queue.update_from_result(item.run_id, WorkflowRunResult(status="completed", output=42, run_id=item.run_id))
    assert (await queue.store.get(item.queue_id)).status == "paused"
    assert (await queue.get(item.queue_id)).status == "failed"
    monkeypatch.setattr(queue.store, "_write_sync", writer)
    await queue._flush_pending_updates()
    fresh = await WorkflowQueueStore(path=queue.store.path).get(item.queue_id)
    assert fresh.status == "completed" and fresh.result.output == 42


@pytest.mark.asyncio
async def test_post_effect_snapshot_failure_is_not_replayed_after_runner_recreation(tmp_path, monkeypatch):
    calls = 0
    class Agent:
        async def run(self, **kwargs):
            nonlocal calls
            calls += 1
            return SimpleNamespace(message='{"out":1}')
    wf = definition(tmp_path)
    wf.nodes[0].kind = "ai"
    wf.nodes[0].config = {"mode": "agent", "instruction": "execute"}
    snapshots = WorkflowSnapshotStore(root=tmp_path)
    events = WorkflowRunEventStore(root=tmp_path)
    write = snapshots._write_sync
    def fail_after_execution(*args):
        if calls:
            raise OSError("disk full")
        write(*args)
    monkeypatch.setattr(snapshots, "_write_sync", fail_after_execution)
    runner = WorkflowRunner(sub_agent_runner=Agent(), snapshot_store=snapshots, event_store=events)
    with pytest.raises(WorkflowPersistenceError):
        await runner.run(wf, thread_id="t", run_id="r")
    assert calls == 1
    fresh = WorkflowRunner(sub_agent_runner=Agent(), snapshot_store=WorkflowSnapshotStore(root=tmp_path), event_store=WorkflowRunEventStore(root=tmp_path))
    result = await fresh.run(wf, thread_id="t", run_id="r")
    assert result.status == "failed" and "persistence failed" in result.error.lower()
    assert calls == 1


@pytest.mark.asyncio
async def test_terminal_journal_failure_never_emits_completed_run(tmp_path, monkeypatch):
    events = WorkflowRunEventStore(root=tmp_path)
    append = events._append_sync
    def write(path, line):
        if '"kind":"run.completed"' in line:
            raise OSError("disk full")
        append(path, line)
    monkeypatch.setattr(events, "_append_sync", write)
    emitted = []
    runner = WorkflowRunner(event_store=events, snapshot_store=WorkflowSnapshotStore(root=tmp_path), emit=emitted.append, emit_lifecycle_events=True)
    with pytest.raises(WorkflowPersistenceError):
        await runner.run(definition(tmp_path), thread_id="t", run_id="r")
    assert not any(event.payload.get("status") == "completed" and not event.payload.get("node_id") for event in emitted)


@pytest.mark.asyncio
async def test_attempt_result_journal_failure_does_not_retry_executor(tmp_path, monkeypatch):
    events = WorkflowRunEventStore(root=tmp_path)
    write = events._append_sync
    calls = 0
    def append(path, line):
        if '"kind":"attempt.completed"' in line:
            raise OSError("disk full")
        write(path, line)
    class Agent:
        async def run(self, **kwargs):
            nonlocal calls
            calls += 1
            return SimpleNamespace(message='{"out":1}')
    wf = definition(tmp_path)
    wf.nodes[0].kind = "ai"
    wf.nodes[0].config = {"mode": "agent", "instruction": "execute", "execution": {"retry": {"retries": 2, "delays_seconds": [0]}}}
    monkeypatch.setattr(events, "_append_sync", append)
    with pytest.raises(WorkflowPersistenceError):
        await WorkflowRunner(sub_agent_runner=Agent(), snapshot_store=WorkflowSnapshotStore(root=tmp_path), event_store=events).run(wf, thread_id="t", run_id="r")
    assert calls == 1


@pytest.mark.asyncio
async def test_journal_coordinator_failure_uses_the_same_persistence_error_contract(tmp_path, monkeypatch):
    from lamtools_core.plugins.bundled.workflow.backend.durable import WorkflowRunEvent
    journal = WorkflowRunEventStore(root=tmp_path)
    def locked(*args):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(journal, "_append_coordinated_sync", locked)
    with pytest.raises(WorkflowPersistenceError, match="database is locked"):
        await journal.append(WorkflowRunEvent(event_id="e", run_id="r", kind="run.started"))


@pytest.mark.asyncio
async def test_concurrent_enqueue_starts_only_one_serial_worker(tmp_path):
    active = maximum = calls = 0
    class Runner:
        async def run(self, wf, **kwargs):
            nonlocal active, maximum, calls
            active += 1
            calls += 1
            maximum = max(maximum, active)
            await asyncio.sleep(.01)
            active -= 1
            return WorkflowRunResult(status="completed", run_id=kwargs["run_id"])
    queue = WorkflowRunQueue(root=tmp_path, manager=object(), runner=Runner())
    items = await asyncio.gather(queue.enqueue(definition(tmp_path)), queue.enqueue(definition(tmp_path)))
    try:
        results = await asyncio.gather(*(queue.wait(item.queue_id, timeout=3) for item in items))
        assert all(result.status == "completed" for result in results)
        assert calls == 2 and maximum == 1
    finally:
        await queue.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["delete", "clear", "clear_sync"])
async def test_explicit_cache_mutations_fail_without_false_success(tmp_path, monkeypatch, mutation):
    cache = WorkflowContentCache(path=tmp_path / "cache.json")
    await cache.set("k", {"out": 1})
    writer = cache._write_sync
    monkeypatch.setattr(cache, "_write_sync", unavailable)
    with pytest.raises(WorkflowPersistenceError):
        if mutation == "delete":
            await cache.delete("k")
        elif mutation == "clear":
            await cache.clear(confirm=True)
        else:
            cache.clear_sync(confirm=True)
    assert (await cache.lookup("k")).hit
    assert (await WorkflowContentCache(path=cache.path).lookup("k")).hit
    monkeypatch.setattr(cache, "_write_sync", writer)
    assert await cache.clear(confirm=True) == 1
    assert not (await WorkflowContentCache(path=cache.path).lookup("k")).hit


@pytest.mark.asyncio
async def test_definition_delete_failure_is_reported_and_definition_remains(tmp_path, monkeypatch):
    store = WorkflowStore()
    wf = definition(tmp_path)
    await store.save(wf)
    monkeypatch.setattr("lamtools_core.plugins.bundled.workflow.backend.store.shutil.rmtree", unavailable)
    with pytest.raises(WorkflowPersistenceError):
        await store.delete(wf.name, work_root=str(tmp_path))
    assert await WorkflowStore().get(wf.name, work_root=str(tmp_path)) is not None
