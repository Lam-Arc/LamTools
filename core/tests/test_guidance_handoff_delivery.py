from __future__ import annotations

import asyncio

import pytest

from lamtools_core.app import open_core_app_db
from lamtools_core.app.event_store import AppEventInput
from lamtools_core.app.live import queue, steering, turn_start
from lamtools_core.app.live.context import CoreLiveContext
from lamtools_core.app.live_hub import CoreAppEventHub
from lamtools_core.app.live_operations import wait_live_background_tasks
from lamtools_core.app.operation_catalog import OperationCatalog
from lamtools_core.app.steering import pending_steering
from lamtools_core.runtime import RuntimeTaskRegistry

from .test_core_live import _register_blocking_turn_start


# user:“去找消息发送/引导/排队/分叉/编辑中最应优化/重构的地方”+(引导转交失败要保留，成功要有持久凭据，不能夹带其他回合的引导)。
@pytest.mark.parametrize("destination", ["failed", "queue", "turn", "lost_response"])
async def test_guidance_handoff_tracks_only_durably_delivered_input(tmp_path, monkeypatch, destination):
    db = await open_core_app_db(tmp_path / "core.db")
    registry = RuntimeTaskRegistry()
    context = CoreLiveContext(
        session_factory=db.session_factory,
        persistence=db.persistence,
        operations=OperationCatalog(),
        hub=CoreAppEventHub(),
        runtime_task_registry=registry,
    )
    release = _register_blocking_turn_start(context)
    thread_id = "handoff-thread"
    completed_turn_id = f"{thread_id}:turn:completed"

    async def append_guidance(session):
        for turn_id, message_id in [("completed", "g1"), (completed_turn_id, "g2"), ("other", "g3")]:
            await db.persistence.append(session, AppEventInput(
                thread_id=thread_id, turn_id=turn_id, method="turn/steered",
                client_message_id=message_id,
                payload={"guidance_id": message_id, "input": [{"type": "text", "text": message_id}]},
            ))

    try:
        await db.persistence.write(append_guidance)
        if destination == "failed":
            async def fail_delivery(**_kwargs):
                raise OSError("could not persist the handoff")

            monkeypatch.setattr(turn_start, "handle_turn_start_operation", fail_delivery)
            monkeypatch.setattr(queue, "handle_queue_create_operation", fail_delivery)
        elif destination == "queue":
            assert registry.accept_run(thread_id, "other")
        elif destination == "lost_response":
            start = turn_start.handle_turn_start_operation

            async def lose_response(**kwargs):
                await start(**kwargs)
                raise OSError("response interrupted after commit")

            monkeypatch.setattr(turn_start, "handle_turn_start_operation", lose_response)

        outcome = await steering.hand_off_pending_guidance(
            context=context, thread_id=thread_id, completed_turn_id=completed_turn_id,
        )
        assert outcome["delivered"] is (destination != "failed")
        expected_pending = ["g1", "g2", "g3"] if destination == "failed" else ["g3"]
        assert [item["id"] for item in await pending_steering(db.session_factory, thread_id)] == expected_pending
        assert outcome["guidance_ids"] == ["g1", "g2"]

        if destination != "failed":
            retry = await steering.hand_off_pending_guidance(
                context=context, thread_id=thread_id, completed_turn_id=completed_turn_id,
            )
            assert retry["guidance_ids"] == []
        async with db.session_factory() as session:
            events = await db.event_store.list_after(session, thread_id=thread_id, after_seq=0)
        accepted = [event for event in events if event.method in {"turn/accepted", "queue/itemAccepted"}]
        if destination == "failed":
            assert accepted == []
        else:
            assert len(accepted) == 1
            assert accepted[0].method == ("queue/itemAccepted" if destination == "queue" else "turn/accepted")
            assert [item["text"] for item in accepted[0].payload["input"]] == ["g1", "g2"]
    finally:
        release.set()
        await asyncio.wait_for(wait_live_background_tasks(), timeout=5)
        registry.clear()
        await db.close()
