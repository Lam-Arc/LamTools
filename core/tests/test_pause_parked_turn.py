"""Pausing a session whose turn is parked (waiting) must park the turn too.

Reported 2026-10-14: with the parent turn parked on a question and its member
still working, pressing Stop left the turn reading as active, and the client's
stop-grace timer then terminated it. The pause has to settle the parked turn
into the paused state on its own, because nothing is executing to write it.
"""
from __future__ import annotations

import pytest

from lamtools_core.app import CoreAgentPaths, CoreAgentSpec, create_core_agent_operations, open_core_app_db
from lamtools_core.app.live_hub import CoreAppEventHub
from lamtools_core.app.live_operations import (
    CoreLiveContext,
    handle_turn_pause_operation,
    handle_turn_resume_operation,
    wait_live_background_tasks,
)
from lamtools_core.app.event_store import AppEventInput
from lamtools_core.app.queue_state import effective_thread_status
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


async def _seed_parked_turn(db, *, thread_id: str, turn_id: str) -> None:
    """A turn that parked on a question: waiting status, open request, no task."""
    async def write(session):
        await db.persistence.append(session, AppEventInput(
            thread_id=thread_id,
            turn_id=turn_id,
            method="turn/accepted",
            payload={"type": "turn", "status": "running", "input": [], "runtime_snapshot": {}},
        ))
    await db.persistence.write(write)
    async def wait(session):
        await db.persistence.append(session, AppEventInput(
            thread_id=thread_id,
            turn_id=turn_id,
            method="turn/started",
            payload={"status": "running", "run_id": turn_id},
        ))
    await db.persistence.write(wait)
    # The question itself: an open request is what holds the session in the
    # waiting state while the turn's own row still says running.
    from lamtools_core.event import RunItemEvent

    async def ask(session):
        await db.persistence.append_run_item(session, RunItemEvent(
            kind="approval_request",
            thread_id=thread_id,
            turn_id=turn_id,
            run_id=turn_id,
            event_id=f"{turn_id}:question",
            item_id=f"{turn_id}:question",
            status="waiting",
            payload={
                "type": "serverRequest",
                "request_id": "call_question",
                "kind": "question",
                "message": "先做哪一块？",
                "tool_name": "question",
            },
        ))
    await db.persistence.write(ask)
    state = await db.runtime_state_store.get(thread_id) or RuntimeState(session_id=thread_id)
    state.run_id = turn_id
    state.status = "waiting"
    state.loop_state = "wait"
    state.metadata["turn_id"] = turn_id
    state.metadata["pending_waiting_request"] = {"request_id": "call_question"}
    await db.runtime_state_store.save(state)


@pytest.mark.asyncio
async def test_pausing_a_parked_turn_writes_the_paused_state(tmp_path):
    db = await open_core_app_db(tmp_path / "core.db")
    context = await _context(db, tmp_path)
    thread_id = "thread-parked"
    turn_id = f"{thread_id}:turn:parked"
    try:
        await _seed_parked_turn(db, thread_id=thread_id, turn_id=turn_id)
        async with db.session_factory() as session:
            before = await db.persistence.load(session, thread_id)
        # Parked on a question: the turn and the session both read waiting, and
        # no task is running to write anything on its own.
        assert before["turns"][turn_id]["status"] == "waiting"
        assert effective_thread_status(before) == "waiting"
        assert not context.runtime_task_registry.is_running(thread_id)

        paused = await handle_turn_pause_operation(
            request_id=1, params={"thread_id": thread_id, "turn_id": turn_id}, context=context
        )
        assert "error" not in paused.response, paused.response
        await wait_live_background_tasks()

        async with db.session_factory() as session:
            after = await db.persistence.load(session, thread_id)
        assert after["turns"][turn_id]["status"] == "paused", after["turns"]
        assert after["core"]["turns"][turn_id]["status"] == "paused"
        # The pause must win over the still-open question: the client reads this
        # container status, and "waiting" there is an active status.
        assert after["core"]["status"] == "paused"
        assert effective_thread_status(after) == "paused", "the session must read paused, not waiting"
        assert after["status"] == "paused"

        state = await db.runtime_state_store.get(thread_id)
        assert state is not None and state.status == "paused"
        assert state.metadata.get("pause_reason") == "user_pause"

        # The paused status must be readable as a row, because that is what a
        # reloaded transcript serves; the streaming path keeps the snapshot out
        # of its hot loop and a paused turn never reaches a terminal boundary.
        async with db.session_factory() as session:
            paged = await db.persistence.load_page(session, thread_id)
        # A second pause of the same turn must be a fresh event: the live client
        # skips an event id it has already seen, and a repeat left the button on
        # the previous run's state until a reload (2026-10-14).
        await handle_turn_pause_operation(
            request_id=3, params={"thread_id": thread_id, "turn_id": turn_id}, context=context
        )
        await wait_live_background_tasks()
        async with db.session_factory() as session:
            events = await db.persistence.list_after(session, thread_id=thread_id, after_seq=0)
        paused_event_ids = [
            str(event.payload.get("event_id") or "")
            for event in events
            if isinstance(event.payload, dict)
            and str(event.payload.get("status") or "") == "paused"
        ]
        assert len(paused_event_ids) >= 2, paused_event_ids
        assert len(set(paused_event_ids)) == len(paused_event_ids), paused_event_ids
        # The status is what a reload serves; the paused *row* is not an item
        # row yet (the turn-level status event carries no item dict), which is a
        # known display gap recorded separately.
        assert paged["core"]["status"] == "paused"
        assert paged["core"]["turns"][turn_id]["status"] == "paused"
    finally:
        context.runtime_task_registry.clear()
        await wait_live_background_tasks()
        await db.close()


@pytest.mark.asyncio
async def test_pausing_a_parked_turn_leaves_it_resumable(tmp_path):
    db = await open_core_app_db(tmp_path / "core.db")
    context = await _context(db, tmp_path)
    thread_id = "thread-parked-resume"
    turn_id = f"{thread_id}:turn:parked"
    try:
        await _seed_parked_turn(db, thread_id=thread_id, turn_id=turn_id)
        await handle_turn_pause_operation(
            request_id=1, params={"thread_id": thread_id, "turn_id": turn_id}, context=context
        )
        await wait_live_background_tasks()

        resumed = await handle_turn_resume_operation(
            request_id=2, params={"thread_id": thread_id, "turn_id": turn_id}, context=context
        )
        assert "error" not in resumed.response, resumed.response
        assert resumed.runtime_start["turn_id"] == turn_id
        task = context.runtime_task_registry.task(thread_id)
        if task is not None:
            await task
    finally:
        context.runtime_task_registry.clear()
        await wait_live_background_tasks()
        await db.close()

@pytest.mark.asyncio
async def test_pausing_keeps_a_member_question_answerable(tmp_path):
    """A pause must not close a member's waiting question.

    Reported 2026-10-14: after a pause the forwarded sub-agent question card
    disappeared. The pause closed every non-terminal row of the turn, member
    rows included, and a closed question row is not a pending decision any more.
    """
    db = await open_core_app_db(tmp_path / "core.db")
    context = await _context(db, tmp_path)
    thread_id = "thread-member-question"
    turn_id = f"{thread_id}:turn:chat"
    try:
        await _seed_parked_turn(db, thread_id=thread_id, turn_id=turn_id)
        # Re-label the question as a member's own row: that is the shape the
        # forwarding sink stamps.
        async def mark_child(session):
            from lamtools_core.event import RunItemEvent

            await db.persistence.append_run_item(session, RunItemEvent(
                kind="approval_request",
                thread_id=thread_id,
                turn_id=turn_id,
                run_id=turn_id,
                event_id=f"{turn_id}:child-question",
                item_id=f"{turn_id}:child-question",
                status="waiting",
                parent_item_id=f"{turn_id}:delegate",
                payload={
                    "type": "serverRequest",
                    "request_id": "child_question",
                    "kind": "question",
                    "message": "子代理的提问",
                    "tool_name": "question",
                    "sub_agent": {"name": "asker", "status": "paused"},
                },
            ))
        await db.persistence.write(mark_child)

        await handle_turn_pause_operation(
            request_id=1, params={"thread_id": thread_id, "turn_id": turn_id}, context=context
        )
        await wait_live_background_tasks()

        async with db.session_factory() as session:
            events = await db.persistence.list_after(session, thread_id=thread_id, after_seq=0)
        child_rows = [
            event for event in events
            if isinstance(event.payload, dict)
            and str(event.payload.get("item_id") or "") in {f"{turn_id}:child-question"}
        ]
        assert child_rows, "the member's question row must survive the pause"
        last = child_rows[-1].payload
        assert str(last.get("kind")) == "approval_request", last
        assert str(last.get("status")) == "waiting", last
    finally:
        context.runtime_task_registry.clear()
        await wait_live_background_tasks()
        await db.close()


def test_an_answer_does_not_revive_a_paused_turn():
    """The stuck-running defect: answering a member's question flipped a paused
    turn back to running although no run existed to close it."""
    from lamtools_core.event import RunItemEvent
    from lamtools_core.snapshot import apply_run_item_event_in_place, empty_thread_snapshot

    thread_id = "thread-revive"
    turn_id = f"{thread_id}:turn:one"
    state = empty_thread_snapshot(thread_id)
    state["turns"] = {turn_id: {"turn_id": turn_id, "status": "paused", "items": []}}
    state["status"] = "paused"
    apply_run_item_event_in_place(state, RunItemEvent.from_dict({
        "kind": "approval_response",
        "thread_id": thread_id,
        "turn_id": turn_id,
        "run_id": "child-run",
        "item_id": "child-question",
        "seq": 5,
        "status": "completed",
        "payload": {"request_id": "child_question", "decision": "guide", "status": "resolved"},
    }))

    assert state["turns"][turn_id]["status"] == "paused"
    assert state["status"] == "paused"
    assert state["requests"]["child_question"]["status"] == "resolved"
