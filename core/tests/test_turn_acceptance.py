from __future__ import annotations

from lamtools_core.app.turn_acceptance import (
    TURN_ACCEPT_DEDUPE_METHODS,
    build_cancelled_turn_event,
    build_turn_acceptance_plan,
)


def test_turn_acceptance_plan_builds_common_events_and_running_status() -> None:
    plan = build_turn_acceptance_plan(
        thread_id="thread-1",
        turn_id="turn-1",
        user_item_id="user-1",
        client_message_id="client-1",
        input_items=[{"type": "text", "text": "hello"}],
        work_root="E:/work",
    )

    assert TURN_ACCEPT_DEDUPE_METHODS == {"turn/accepted", "queue/itemAccepted"}
    assert plan.turn_accepted.method == "turn/accepted"
    assert plan.turn_accepted.payload == {
        "type": "turn",
        "status": "running",
        "input": [{"type": "text", "text": "hello"}],
        "work_root": "E:/work",
    }
    assert plan.user_item.method == "item/started"
    assert plan.user_item.item_id == "user-1"
    assert plan.user_item.payload["type"] == "userMessage"
    assert plan.running_status.kind == "status"
    assert plan.running_status.item_id == "turn-1:running"
    assert plan.running_status.payload == {"type": "turn", "status": "running"}


def test_turn_acceptance_plan_allows_member_payload_overlay() -> None:
    plan = build_turn_acceptance_plan(
        thread_id="thread-1",
        turn_id="turn-1",
        user_item_id="user-1",
        client_message_id="client-1",
        input_items=[{"type": "text", "text": "hello"}],
        include_turn_status=False,
        turn_payload_extra={"transcript_turn_id": "turn-1"},
        user_payload_extra={"message_id": "user-1"},
    )

    assert "status" not in plan.turn_accepted.payload
    assert plan.turn_accepted.payload["transcript_turn_id"] == "turn-1"
    assert plan.user_item.payload["message_id"] == "user-1"


def test_cancelled_turn_event_uses_accepted_id_for_run_and_turn() -> None:
    event = build_cancelled_turn_event(
        thread_id="thread-1",
        turn_id="accepted-turn-1",
        message="stopped",
    )

    assert event.event_id == "accepted-turn-1:cancelled"
    assert event.run_id == "accepted-turn-1"
    assert event.turn_id == "accepted-turn-1"
    assert event.item_id == "accepted-turn-1:cancelled"
    assert event.status == "cancelled"
    assert event.payload == {
        "type": "turn",
        "status": "cancelled",
        "raw_end_reason": "user_interrupt",
        "message": "stopped",
    }
