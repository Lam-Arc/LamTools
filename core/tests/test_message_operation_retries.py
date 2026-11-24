from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from lamtools_core.app import open_core_app_db
from lamtools_core.app.core_session_store import CoreDbSessionStore
from lamtools_core.app.live.context import CoreLiveContext
from lamtools_core.app.live.queue import handle_queue_create_operation, handle_queue_delete_operation, handle_queue_update_operation
from lamtools_core.app.live_hub import CoreAppEventHub
from lamtools_core.app.live_operations import wait_live_background_tasks
from lamtools_core.app.operation_catalog import OperationCatalog
from lamtools_core.checkpoint import register_checkpoint_operations
from lamtools_core.runtime import RuntimeTaskRegistry

from .test_core_checkpoint_graph import SessionRecord, _append_production_turn, _runtime, _tool_call_history
from .test_core_live import _register_blocking_turn_start


def context_for(db):
    return CoreLiveContext(
        session_factory=db.session_factory, persistence=db.persistence, operations=OperationCatalog(),
        hub=CoreAppEventHub(), runtime_task_registry=RuntimeTaskRegistry(), runtime_state_store=db.runtime_state_store,
    )


async def seed_transcript(db, work_root):
    await CoreDbSessionStore(lambda: db).create(SessionRecord(
        id="source", member_id="core", title="Source", status="idle", metadata={"work_root": str(work_root)},
    ))
    await _append_production_turn(db, "source", "old-turn", "original")
    await _runtime(db, "source", history=_tool_call_history("original"))


# user:“全做”+(写入编辑消息失败时回退一并取消，成功重试时保留同一条新消息)。
async def test_edit_acceptance_rolls_back_atomically_and_deduplicates(tmp_path, monkeypatch):
    db = await open_core_app_db(tmp_path / "core.db")
    context = context_for(db)
    release = _register_blocking_turn_start(context)
    params = {"thread_id": "source", "replace_turn_id": "old-turn", "work_root": str(tmp_path),
              "client_message_id": "edit-1", "input": [{"type": "text", "text": "replacement"}],
              "include_snapshot": False}

    async def events():
        async with db.session_factory() as session:
            return await db.event_store.list_thread(session, thread_id="source")

    async def replace(request_id):
        return await context.host.execute("turn.replace", request_id=request_id, params=params, context=context)

    try:
        await seed_transcript(db, tmp_path)
        async with db.session_factory() as session:
            params["expected_revision"] = await db.persistence.current_revision(session, "source")
        before_events = await events()
        before_history = await db.runtime_state_store.get_history("source")
        async def fail_after_truncate(session, **_kwargs):
            uncommitted = await db.event_store.list_thread(session, thread_id="source")
            assert all(event.turn_id != "old-turn" for event in uncommitted)
            raise OSError("replacement write failed")

        with monkeypatch.context() as patch:
            patch.setattr(db.persistence, "append_batch", fail_after_truncate)
            with pytest.raises(OSError, match="replacement write failed"):
                await replace(1)
        assert await events() == before_events
        assert await db.runtime_state_store.get_history("source") == before_history
        assert context.runtime_task_registry.active_run_id("source") is None

        # Exercise a retry after the write body completed but its transaction rolled back.
        write = db.persistence.write

        async def replay_transaction(action):
            async def fail_commit(session):
                await action(session)
                raise OSError("transaction did not commit")

            with pytest.raises(OSError, match="transaction did not commit"):
                await write(fail_commit)
            return await write(action)

        with monkeypatch.context() as patch:
            patch.setattr(db.persistence, "write", replay_transaction)
            assert "result" in (await replace(2)).response
        assert "result" in (await replace(3)).response
        after = await events()
        async with db.session_factory() as session:
            assert await db.persistence.current_revision(session, "source") > params["expected_revision"]
        assert sum(event.method == "session/rollback" for event in after) == 1
        accepted = [event for event in after if event.method == "turn/accepted"]
        assert len(accepted) == 1 and accepted[0].client_message_id == "edit-1"
        assert accepted[0].payload["input"] == params["input"]
        assert all(event.turn_id != "old-turn" for event in after)
        assert await db.runtime_state_store.get_history("source") == []
    finally:
        task = context.runtime_task_registry.task("source")
        release.set()
        if task is not None:
            await asyncio.wait_for(asyncio.shield(task), timeout=5)
        await asyncio.wait_for(wait_live_background_tasks(), timeout=5)
        context.runtime_task_registry.clear()
        await db.close()


async def test_fork_retry_returns_original_session_even_if_source_changes(tmp_path):
    db = await open_core_app_db(tmp_path / "core.db")
    catalog = OperationCatalog()
    register_checkpoint_operations(catalog, session_factory=db.session_factory, default_work_root=tmp_path)
    try:
        await seed_transcript(db, tmp_path)
        params = {"session_id": "source", "turn_id": "old-turn", "client_request_id": "fork-1"}
        results = await asyncio.gather(*(catalog.execute("session.fork", params) for _ in range(2)))
        assert all(result.status == "ok" for result in results), results
        assert results[0].payload == results[1].payload
        original_session = results[0].payload["session_id"]
        another = await catalog.execute("session.fork", {**params, "client_request_id": "fork-2"})
        assert another.status == "ok" and another.payload["session_id"] != original_session
        assert (await catalog.execute("session.rollback", params)).status == "ok"
        retry = await catalog.execute("session.fork", params)
        assert retry.status == "ok" and retry.payload == results[0].payload
    finally:
        await db.close()


async def test_queue_create_retry_uses_current_item_and_does_not_recreate_deleted_item(tmp_path, monkeypatch):
    db = await open_core_app_db(tmp_path / "core.db")
    context = context_for(db)
    publish = AsyncMock()
    monkeypatch.setattr(context.hub, "publish", publish)
    create = {"thread_id": "source", "client_message_id": "queue-1", "include_snapshot": False,
              "input": [{"type": "text", "text": "original"}]}
    try:
        initial = (await handle_queue_create_operation(request_id=1, params=create, context=context)).response["result"]
        item_id = initial["queue_item"]["queue_item_id"]
        item = {"thread_id": "source", "queue_item_id": item_id, "include_snapshot": False}
        await handle_queue_update_operation(request_id=2, params={**item, "text": "updated"}, context=context)
        count = publish.await_count
        retry = (await handle_queue_create_operation(request_id=3, params=create, context=context)).response["result"]
        assert retry["queue_item"]["queue_item_id"] == item_id
        assert retry["queue_item"]["input"] == [{"type": "text", "text": "updated"}]
        assert retry["replayed"] is True
        assert publish.await_count == count
        await handle_queue_delete_operation(request_id=4, params=item, context=context)
        retry = (await handle_queue_create_operation(request_id=5, params=create, context=context)).response["result"]
        assert retry["queue_item"] is None
        assert retry["events"][0]["client_message_id"] == "queue-1"
    finally:
        await db.close()
