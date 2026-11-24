from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from lamtools_core.app import open_core_app_db
from lamtools_core.app.live import runtime_tasks
from lamtools_core.app.live.background import wait_live_background_tasks
from lamtools_core.app.live.queue import handle_queue_create_operation, handle_queue_update_operation
from lamtools_core.app.live.queue_dispatch import _dispatch_next_queue_item

from .test_message_operation_retries import context_for, seed_transcript


async def enqueue(context, **options):
    return (await handle_queue_create_operation(
        request_id=1, context=context, params={
            "thread_id": "source", "input": [{"type": "text", "text": "original"}],
            "include_snapshot": False, **options,
        },
    )).response["result"]["queue_item"]["queue_item_id"]


async def metadata(db):
    async with db.session_factory() as session:
        return await db.persistence.load_metadata(session, "source")


async def sweep(context, root):
    await _dispatch_next_queue_item(
        context=context, thread_id="source", completed_turn_id="old-turn", work_root=str(root),
    )


# user:“及优化速度/逻辑”+(回合结束后才到达的排队消息也能派发，空队列检查无需读取完整历史)。
async def test_desktop_enqueue_after_completion_kicks_dispatch_without_full_snapshot(tmp_path, monkeypatch):
    db = await open_core_app_db(tmp_path / "queue.db")
    context = context_for(db)
    start = AsyncMock()
    try:
        await seed_transcript(db, tmp_path)
        await sweep(context, tmp_path)
        monkeypatch.setattr(runtime_tasks, "_start_runtime_task", start)
        monkeypatch.setattr(db.persistence, "load", AsyncMock(side_effect=AssertionError("full history read")))
        item_id = await enqueue(context, dispatch_if_idle=True)
        await asyncio.wait_for(wait_live_background_tasks(), 5)
        start.assert_awaited_once()
        assert start.await_args.kwargs["runtime_start"]["text"] == "original"
        assert (await metadata(db)).get("queue") == []
        async with db.session_factory() as session:
            events = await db.event_store.list_thread(session, thread_id="source")
        assert sum(event.method == "queue/itemDispatched" and event.item_id == item_id for event in events) == 1
    finally:
        context.runtime_task_registry.clear()
        await db.close()


async def test_queue_edit_cannot_recreate_an_item_dispatched_between_read_and_write(tmp_path, monkeypatch):
    db = await open_core_app_db(tmp_path / "queue.db")
    context = context_for(db)
    start = AsyncMock()
    try:
        await seed_transcript(db, tmp_path)
        item_id = await enqueue(context)
        monkeypatch.setattr(runtime_tasks, "_start_runtime_task", start)
        append = db.persistence.append_batch_atomic

        async def dispatch_before_atomic_append(**kwargs):
            if any(event.method == "queue/itemUpdated" for event in kwargs["app_events"]):
                await sweep(context, tmp_path)
                assert (await metadata(db)).get("queue") == []
            return await append(**kwargs)

        monkeypatch.setattr(db.persistence, "append_batch_atomic", dispatch_before_atomic_append)
        update = {"thread_id": "source", "queue_item_id": item_id, "text": "edited", "include_snapshot": False}
        await handle_queue_update_operation(request_id=2, context=context, params=update)
        await sweep(context, tmp_path)
        assert (await metadata(db)).get("queue") == []
        start.assert_awaited_once()
        assert start.await_args.kwargs["runtime_start"]["text"] == "edited"
        again = await handle_queue_update_operation(request_id=3, context=context, params=update)
        assert again.response["result"]["applied"] is False
    finally:
        context.runtime_task_registry.clear()
        await db.close()
