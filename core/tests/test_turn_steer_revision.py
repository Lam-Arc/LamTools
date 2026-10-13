"""Live guidance is scoped to a turn, not to the session event cursor."""
from __future__ import annotations

import asyncio
import contextlib

import pytest

from .test_core_live import _context, _register_blocking_turn_start
from lamtools_core.app.live_operations import handle_turn_start_operation, wait_live_background_tasks
from lamtools_core.event import RunItemEvent


@pytest.mark.asyncio
async def test_live_steer_accepts_stale_revision_once_and_checks_target_turn(tmp_path):
    engine, context = await _context(tmp_path)
    release = _register_blocking_turn_start(context)
    thread_id = "thread-steer-revision"
    try:
        started = await handle_turn_start_operation(
            request_id=1,
            params={"thread_id": thread_id, "input": [{"type": "text", "text": "start"}]},
            context=context,
        )
        result = started.response["result"]
        turn_id = result["runtime_start"]["turn_id"]
        revision = result["snapshot"]["revision"]

        async def append_progress(db):
            return await context.persistence.append_run_item(
                db,
                RunItemEvent(
                    kind="message", thread_id=thread_id, event_id="progress:1",
                    run_id=turn_id, turn_id=turn_id, item_id=f"{turn_id}:text",
                    status="running", payload={"type": "agentMessage", "text": "working"},
                ),
            )

        await context.persistence.write(append_progress)
        async with context.session_factory() as db:
            assert await context.persistence.current_revision(db, thread_id) > revision

        params = {
            "thread_id": thread_id, "turn_id": turn_id,
            "client_message_id": "guidance:1", "expected_revision": revision,
            "input": [{"type": "text", "text": "change direction"}],
            "include_snapshot": False,
        }
        steered = await context.host.execute("turn.steer", request_id=2, params=params, context=context)
        assert "result" in steered.response, steered.response
        assert steered.response["result"]["applied"] is True

        duplicate = await context.host.execute("turn.steer", request_id=3, params=params, context=context)
        assert duplicate.response["result"]["reason"] == "already_applied"
        async with context.session_factory() as db:
            events = await context.persistence.list_thread(db, thread_id=thread_id)
        assert sum(event.method == "turn/steered" for event in events) == 1
        assert context.runtime_task_registry.consume_guidance(thread_id, run_id=turn_id) == ["change direction"]
        assert context.runtime_task_registry.consume_guidance(thread_id, run_id=turn_id) == []

        mismatch = await context.host.execute(
            "turn.steer", request_id=4,
            params={**params, "turn_id": "old-turn", "client_message_id": "guidance:2"},
            context=context,
        )
        assert mismatch.response["result"]["applied"] is False
        assert mismatch.response["result"]["reason"] == "active_turn_mismatch"
    finally:
        release.set()
        task = context.runtime_task_registry.task(thread_id)
        if task is not None:
            await task
        await engine.dispose()


@pytest.mark.asyncio
async def test_send_then_stop_with_stale_revision_still_targets_only_the_requested_turn(tmp_path):
    engine, context = await _context(tmp_path)
    release = _register_blocking_turn_start(context)
    thread_id = "thread-send-stop-revision"
    task = None
    try:
        await context.host.execute(
            "thread.start", request_id=1, params={"thread_id": thread_id}, context=context,
        )
        async with context.session_factory() as db:
            assert await context.persistence.current_revision(db, thread_id) > 0
        started = await context.host.execute(
            "turn.start", request_id=2,
            params={
                "thread_id": thread_id, "client_message_id": "send:1",
                "expected_revision": 0, "input": [{"type": "text", "text": "start"}],
            },
            context=context,
        )
        assert "result" in started.response, started.response
        turn_id = started.response["result"]["runtime_start"]["turn_id"]
        task = context.runtime_task_registry.task(thread_id, run_id=turn_id)
        assert task is not None
        # A stale Stop targeting another turn must leave this task alive.
        foreign = await context.host.execute(
            "turn.cancel", request_id=3,
            params={"thread_id": thread_id, "turn_id": "old-turn", "expected_revision": 0},
            context=context,
        )
        assert foreign.response["result"]["status"] == "idle"
        await wait_live_background_tasks()
        assert not task.done() and not task.cancelling()

        stopped = await context.host.execute(
            "turn.cancel", request_id=4,
            params={"thread_id": thread_id, "turn_id": turn_id, "expected_revision": 0},
            context=context,
        )
        assert stopped.response["result"]["status"] == "cancelling"
        await wait_live_background_tasks()
        assert task.cancelled()
        assert context.runtime_task_registry.active_run_id(thread_id) is None
        async with context.session_factory() as db:
            events = await context.persistence.list_thread(db, thread_id=thread_id)
        assert sum(event.method == "turn/interrupted" for event in events) == 1
    finally:
        release.set()
        if task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await wait_live_background_tasks()
        await engine.dispose()
