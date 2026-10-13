"""Queue mutations while a turn keeps appending events (regression).

The queue shares the session's optimistic-lock revision with everything else,
but adding, deleting and updating a queue row is an append-only, idempotent
event keyed by ``queue_item_id``: it does not read-modify-write any shared
field. A live turn appends events continuously and pushes the revision past the
value the client read before the RPC, so a CAS on these operations rejects a
legitimate delete/update with "revision conflict". This reproduces that and
locks the append-only rule for the queue operations.
"""
from __future__ import annotations

import pytest

from lamtools_core.app.live_operations import (
    handle_queue_create_operation,
    handle_queue_delete_operation,
    handle_queue_update_operation,
)
from lamtools_core.event import RunItemEvent

from .test_core_live import _context


async def _advance_revision(context, thread_id: str, *, seq: int = 2) -> int:
    """Append one event the way a live turn does, returning the new revision."""

    async def write(db):
        return await context.persistence.append_batch(
            db,
            run_item_events=[
                RunItemEvent(
                    kind="message",
                    thread_id=thread_id,
                    event_id=f"live:{seq}",
                    run_id="turn-live",
                    turn_id="turn-live",
                    item_id="turn-live:model_text",
                    status="running",
                    payload={"type": "agentMessage", "delta": "x"},
                )
            ],
        )

    await context.persistence.write(write)
    async with context.session_factory() as db:
        return await context.persistence.current_revision(db, thread_id)


@pytest.mark.asyncio
async def test_queue_delete_is_not_rejected_when_the_revision_advanced(tmp_path):
    engine, context = await _context(tmp_path)
    try:
        created = await handle_queue_create_operation(
            request_id=1,
            params={
                "thread_id": "thread-q",
                "client_message_id": "client-q",
                "input": [{"type": "text", "text": "queued guidance"}],
            },
            context=context,
        )
        item_id = created.response["result"]["queue_item"]["queue_item_id"]
        client_revision = await _advance_revision(context, "thread-q")
        # The client read its revision BEFORE the live event landed.
        stale = client_revision - 1

        deleted = await context.host.execute(
            "queue.delete",
            request_id=2,
            params={
                "thread_id": "thread-q",
                "queue_item_id": item_id,
                "expected_revision": stale,
                "include_snapshot": False,
            },
            context=context,
        )
        assert "result" in deleted.response, deleted.response
        async with context.session_factory() as db:
            snapshot = await context.persistence.load_metadata(db, "thread-q")
        assert snapshot["queue"] == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_queue_update_is_not_rejected_when_the_revision_advanced(tmp_path):
    engine, context = await _context(tmp_path)
    try:
        created = await handle_queue_create_operation(
            request_id=1,
            params={
                "thread_id": "thread-u",
                "client_message_id": "client-u",
                "input": [{"type": "text", "text": "before"}],
            },
            context=context,
        )
        item_id = created.response["result"]["queue_item"]["queue_item_id"]
        client_revision = await _advance_revision(context, "thread-u")
        stale = client_revision - 1

        updated = await context.host.execute(
            "queue.update",
            request_id=2,
            params={
                "thread_id": "thread-u",
                "queue_item_id": item_id,
                "text": "after",
                "expected_revision": stale,
                "include_snapshot": False,
            },
            context=context,
        )
        assert "result" in updated.response, updated.response
        assert updated.response["result"]["events"][0]["payload"]["input"] == [
            {"type": "text", "text": "after"}
        ]
    finally:
        await engine.dispose()
