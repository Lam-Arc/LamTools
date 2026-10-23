"""Regression contracts for the turn-control review findings.

These tests target the structural defects, not only the happy path:

* a delegated member's approval ending must never revive or cancel the parent
  turn;
* the snapshot reducer must never let a child-scoped item change a turn status;
* paused turns must not leave an invisible, still-answerable request behind.
"""

from __future__ import annotations

import pytest

from lamtools_core.app.approval_resolution import ApprovalResolutionLifecycle
from lamtools_core.app.base_agent import core_events_to_run_items
from lamtools_core.event import CoreEvent, RunItemEvent
from lamtools_core.runtime import RuntimeState
from lamtools_core.snapshot import apply_run_item_event_in_place, empty_thread_snapshot


class _MemoryStateStore:
    def __init__(self, state: RuntimeState) -> None:
        self.state = state

    async def get(self, session_id: str):
        return self.state if session_id == self.state.session_id else None

    async def save(self, state: RuntimeState) -> None:
        self.state = state


@pytest.mark.asyncio
async def test_child_approval_denial_never_creates_a_parent_terminal():
    parent_turn = "thread:turn:parent"
    child_run = "child-run"
    state = RuntimeState(
        session_id="thread:sub:researcher",
        run_id=child_run,
        status="waiting",
        metadata={
            "turn_id": "thread:sub:researcher:turn:child",
            "actor_kind": "sub_agent",
            "delegated_session": {
                "agent": "researcher",
                "name": "researcher",
                "task": "find sources",
                "session_id": "thread:sub:researcher",
                "run_id": child_run,
                "parent_call_id": "call-sub",
                "parent_run_id": parent_turn,
                "parent_turn_id": parent_turn,
            },
        },
    )
    events: list[CoreEvent] = []

    def run_items_from_events(items):
        events.extend(items)
        return core_events_to_run_items(items, thread_id="thread")

    lifecycle = ApprovalResolutionLifecycle(
        operation_name="approval.respond",
        thread_id="thread",
        state=state,
        state_store=_MemoryStateStore(state),
        request_id="thread:child-run:call_1",
        tool_call={"id": "call_1", "name": "run_command", "arguments": {"command": "rm -rf build"}},
        decision="deny",
        guidance="",
        persist_run_items=lambda items: _collect(items, []),
        run_items_from_events=run_items_from_events,
        snapshot_from_events=lambda items: {},
    )

    result = await lifecycle.persist_decision()
    assert result is None
    result = await lifecycle.finalize_cancelled()
    assert result.status == "ok"

    cancellation = [event for event in events if event.name == "runtime.cancelled"]
    assert cancellation, "the child must still receive a terminal fact"
    event = cancellation[0]
    assert event.turn_id == parent_turn
    assert isinstance(event.payload.get("sub_agent"), dict)
    assert event.payload["sub_agent"]["session_id"] == "thread:sub:researcher"

    # Replay through the real reducer: the parent turn must not be created or
    # changed by a delegated member's ending.
    snapshot = empty_thread_snapshot("thread")
    snapshot["turns"][parent_turn] = {"turn_id": parent_turn, "status": "completed", "items": []}
    snapshot["status"] = "completed"
    for item in core_events_to_run_items(events, thread_id="thread"):
        apply_run_item_event_in_place(snapshot, item)
    assert snapshot["turns"][parent_turn]["status"] == "completed"
    assert snapshot["turns"][parent_turn]["status"] != "cancelled"
    assert set(snapshot["turns"]) == {parent_turn}, "no phantom child turn may be invented"


@pytest.mark.asyncio
async def test_child_approval_request_does_not_reopen_a_completed_parent_turn():
    parent_turn = "thread:turn:parent"
    snapshot = empty_thread_snapshot("thread")
    snapshot["turns"][parent_turn] = {"turn_id": parent_turn, "status": "completed", "items": []}
    snapshot["status"] = "completed"

    child_request = RunItemEvent(
        kind="approval_request",
        thread_id="thread",
        turn_id=parent_turn,
        run_id=parent_turn,
        item_id="child-question",
        parent_item_id="thread:parent-run:call-sub:tool",
        event_id="child-question",
        status="waiting",
        payload={
            "type": "serverRequest",
            "request_id": "child-request",
            "kind": "question",
            "message": "which source?",
            "tool_name": "question",
            "sub_agent": {"agent": "researcher", "name": "researcher", "session_id": "thread:sub:researcher"},
        },
    )
    apply_run_item_event_in_place(snapshot, child_request)
    assert snapshot["turns"][parent_turn]["status"] == "completed"
    assert snapshot["status"] == "completed"

    child_response = RunItemEvent(
        kind="approval_response",
        thread_id="thread",
        turn_id=parent_turn,
        run_id=parent_turn,
        item_id="child-question",
        parent_item_id="thread:parent-run:call-sub:tool",
        event_id="child-response",
        status="completed",
        payload={
            "type": "serverRequest",
            "request_id": "child-request",
            "status": "resolved",
            "decision": "approve",
            "sub_agent": {"agent": "researcher", "name": "researcher", "session_id": "thread:sub:researcher"},
        },
    )
    apply_run_item_event_in_place(snapshot, child_response)
    assert snapshot["turns"][parent_turn]["status"] == "completed"
    assert snapshot["status"] == "completed"


async def _collect(items, sink: list[CoreEvent]):
    sink.extend(items)
    return None


def test_deleted_member_is_recorded_in_the_snapshot():
    snapshot = empty_thread_snapshot("thread")
    event = RunItemEvent(
        kind="message",
        thread_id="thread",
        turn_id="turn",
        run_id="run",
        item_id="deleted-status",
        event_id="deleted-status",
        status="completed",
        payload={
            "type": "subAgentStatus",
            "sub_agent": {
                "name": "researcher",
                "status": "deleted",
                "session_id": "thread:sub:researcher",
            },
        },
    )
    apply_run_item_event_in_place(snapshot, event)
    assert snapshot["deleted_agents"]["researcher"] is True
    assert snapshot["deleted_agents"]["thread:sub:researcher"] is True
