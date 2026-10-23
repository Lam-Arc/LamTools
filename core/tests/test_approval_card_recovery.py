"""A crash between the waiting checkpoint and the card must not strand the turn."""

from __future__ import annotations

import pytest

from lamtools_core.app import CoreAgentPaths, CoreAgentSpec, create_core_agent_operations, open_core_app_db
from lamtools_core.app.event_store import AppEventInput
from lamtools_core.app.live_hub import CoreAppEventHub
from lamtools_core.app.live_operations import (
    CoreLiveContext,
    _recover_missing_approval_card,
    recover_stale_active_turns,
)
from lamtools_core.runtime import RuntimeState, RuntimeTaskRegistry


async def _context(db, tmp_path):
    registry = RuntimeTaskRegistry()
    hub = CoreAppEventHub()
    operations = create_core_agent_operations(
        spec=CoreAgentSpec(default_model="fixture"),
        paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=tmp_path),
        model_provider=None,
        runtime_state_store=db.runtime_state_store,
        runtime_task_registry=registry,
        db_session_factory=db.session_factory,
        app_event_store=db.event_store,
        thread_snapshot_store=db.snapshot_store,
        app_event_hub=hub,
        write_coordinator=db.persistence.write_coordinator,
    )
    return CoreLiveContext(
        session_factory=db.session_factory,
        persistence=db.persistence,
        operations=operations,
        hub=hub,
        runtime_task_registry=registry,
        runtime_state_store=db.runtime_state_store,
    )


async def _seed_waiting_without_card(db, *, thread_id: str, turn_id: str) -> str:
    async def accept(session):
        await db.persistence.append(session, AppEventInput(
            thread_id=thread_id,
            turn_id=turn_id,
            method="turn/accepted",
            payload={"type": "turn", "status": "running", "input": [], "runtime_snapshot": {}},
        ))

    await db.persistence.write(accept)
    request_id = f"{thread_id}:{turn_id}:call_question"
    state = await db.runtime_state_store.get(thread_id) or RuntimeState(session_id=thread_id)
    state.run_id = turn_id
    state.status = "waiting"
    state.loop_state = "wait"
    state.metadata["turn_id"] = turn_id
    state.metadata["pending_approval"] = {
        "request_id": request_id,
        "tool_call": {"id": "call_question", "name": "question", "arguments": {"question": "which?"}},
        "response_index": 0,
        "status": "waiting",
        "asked_at_ms": 1,
        "request_payload": {
            "request_id": request_id,
            "tool_name": "question",
            "arguments": {"question": "which?"},
            "request_kind": "question",
            "message": "which?",
            "metadata": {},
            "options": [{"id": "option-1", "label": "A", "response": "A"}],
        },
    }
    state.metadata["pending_waiting_request"] = {
        "request_id": request_id,
        "request_kind": "question",
        "tool_call_id": "call_question",
        "tool_name": "question",
        "message": "which?",
    }
    await db.runtime_state_store.save(state)
    return request_id


@pytest.mark.asyncio
async def test_recovery_rebuilds_the_missing_card_exactly_once(tmp_path):
    db = await open_core_app_db(tmp_path / "core.db")
    context = await _context(db, tmp_path)
    thread_id = "thread-recover-card"
    turn_id = f"{thread_id}:turn:1"
    try:
        request_id = await _seed_waiting_without_card(db, thread_id=thread_id, turn_id=turn_id)

        assert await _recover_missing_approval_card(context=context, thread_id=thread_id)
        async with db.session_factory() as session:
            snapshot = await db.persistence.load(session, thread_id)
        assert request_id in snapshot["core"]["requests"]
        assert snapshot["core"]["requests"][request_id]["status"] == "open"

        # A second recovery pass must not create a second request identity.
        assert not await _recover_missing_approval_card(context=context, thread_id=thread_id)
        async with db.session_factory() as session:
            snapshot = await db.persistence.load(session, thread_id)
        assert list(snapshot["core"]["requests"]) == [request_id]

        # The startup reaper keeps this turn instead of cancelling it.
        assert await recover_stale_active_turns(context=context) == 0
        async with db.session_factory() as session:
            snapshot = await db.persistence.load(session, thread_id)
        assert snapshot["turns"][turn_id]["status"] == "waiting"
    finally:
        context.runtime_task_registry.clear()
        await db.close()
