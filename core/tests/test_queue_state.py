from __future__ import annotations

from lamtools_core.app.queue_state import (
    build_queue_guidance_plan,
    effective_thread_status,
    effective_turn_status,
    input_item_attachment_ids,
    input_items_text,
    latest_active_turn_id,
    next_dispatchable_queue_item,
    queue_delete_payload,
    queue_dispatch_payload,
    queue_item_payload,
)


def test_queue_guidance_plan_consumes_only_after_active_turn_match() -> None:
    snapshot = {
        "status": "running",
        "turns": {"turn-1": {"turn_id": "turn-1", "status": "running", "seq": 4}},
        "queue": [{
            "queue_item_id": "queue-1",
            "status": "queued",
            "input": [{"type": "text", "text": "old text"}],
        }],
    }

    applied = build_queue_guidance_plan(
        snapshot,
        thread_id="thread-1",
        turn_id="turn-1",
        queue_item_id="queue-1",
        client_message_id="queue-guide:queue-1",
        replacement_text="updated text",
    )
    expired = build_queue_guidance_plan(
        snapshot,
        thread_id="thread-1",
        turn_id="turn-finished",
        queue_item_id="queue-1",
        client_message_id="queue-guide:queue-1",
    )

    assert applied.applied is True
    assert applied.reason == ""
    assert applied.input_items == [{"type": "text", "text": "updated text"}]
    assert [event.method for event in applied.events] == ["turn/steered", "queue/itemDeleted"]
    assert [event.event_id for event in applied.events] == [
        "queue-guide:queue-1:steer",
        "queue-guide:queue-1:consume",
    ]
    assert applied.events[0].payload["input"] == applied.input_items
    assert applied.events[1].payload["status"] == "sent"
    assert expired.applied is False
    assert expired.reason == "active_turn_mismatch"
    assert expired.events == ()


def test_effective_status_prefers_core_runtime_state() -> None:
    snapshot = {
        "status": "idle",
        "turns": {"turn-1": {"turn_id": "turn-1", "status": "completed"}},
        "core": {
            "status": "running",
            "turns": {"turn-1": {"turn_id": "turn-1", "status": "waiting"}},
        },
    }

    assert effective_thread_status(snapshot) == "running"
    assert effective_turn_status(snapshot, "turn-1") == "waiting"


def test_latest_active_turn_id_uses_newest_active_turn() -> None:
    snapshot = {
        "turns": {
            "turn-1": {"turn_id": "turn-1", "status": "running", "seq": 2},
            "turn-2": {"turn_id": "turn-2", "status": "completed", "seq": 9},
        },
        "core": {
            "turns": {
                "turn-3": {"turn_id": "turn-3", "status": "waiting", "last_seq": 7},
            },
        },
    }

    assert latest_active_turn_id(snapshot) == "turn-3"


def test_latest_active_turn_id_ignores_stale_waiting_turn_after_thread_cancelled() -> None:
    snapshot = {
        "status": "cancelled",
        "core": {
            "status": "cancelled",
            "turns": {
                "turn-stale": {"turn_id": "turn-stale", "status": "waiting", "last_seq": 10},
                "turn-cancelled": {"turn_id": "turn-cancelled", "status": "cancelled", "last_seq": 11},
            },
        },
    }

    assert latest_active_turn_id(snapshot) is None


def test_next_dispatchable_queue_item_requires_idle_or_completed_thread() -> None:
    running_snapshot = {
        "status": "running",
        "queue": [{"queue_item_id": "queue-1", "status": "queued", "mode": "next_turn", "seq": 1}],
    }
    idle_snapshot_with_history = {
        "status": "idle",
        "turns": {"turn-1": {"turn_id": "turn-1", "status": "completed"}},
        "queue": [{"queue_item_id": "queue-1", "status": "queued", "mode": "next_turn", "seq": 1}],
    }
    completed_snapshot = {
        "status": "completed",
        "queue": [
            {"queue_item_id": "queue-2", "status": "queued", "mode": "next_turn", "seq": 2},
            {"queue_item_id": "queue-1", "status": "queued", "mode": "next_turn", "seq": 1},
        ],
    }

    assert next_dispatchable_queue_item(running_snapshot) is None
    assert next_dispatchable_queue_item(idle_snapshot_with_history) is None
    assert next_dispatchable_queue_item(completed_snapshot) == completed_snapshot["queue"][1]


def test_input_items_text_and_attachment_ids_are_core_rules() -> None:
    items = [
        {"type": "text", "text": "看 "},
        {"type": "attachment", "attachment_id": "att-1"},
        {"type": "attachment", "attachmentId": "att-1"},
        {"type": "attachment", "id": "att-2"},
        {"type": "text", "text": "这里"},
    ]

    assert input_items_text(items) == "看 这里"
    assert input_item_attachment_ids(items) == ["att-1", "att-2"]


def test_queue_payload_helpers_preserve_runtime_input_and_terminal_payloads() -> None:
    visible = [{"type": "text", "text": "/review"}]
    runtime = [{"type": "text", "text": "REVIEW BODY"}]

    assert queue_item_payload(queue_item_id="queue-1", input_items=visible, runtime_input_items=runtime) == {
        "type": "queue",
        "queue_item_id": "queue-1",
        "status": "queued",
        "mode": "next_turn",
        "input": visible,
        "runtime_input": runtime,
    }
    assert queue_delete_payload(queue_item_id="queue-1") == {
        "type": "queue",
        "queue_item_id": "queue-1",
        "status": "cancelled",
    }
    assert queue_dispatch_payload({
        "queue_item_id": "queue-1",
        "input": visible,
        "runtime_input": runtime,
    }) == (
        "queue-1",
        visible,
        runtime,
        {
            "type": "queue",
            "queue_item_id": "queue-1",
            "status": "dispatched",
            "mode": "next_turn",
            "input": visible,
            "runtime_input": runtime,
        },
    )


def test_queue_payload_preserves_attachments_for_durable_dispatch() -> None:
    items = [
        {"type": "text", "text": "review this"},
        {"type": "attachment", "attachment_id": "att-1", "name": "draft.md"},
    ]

    payload = queue_item_payload(queue_item_id="queue-attachment", input_items=items)
    dispatched = queue_dispatch_payload(payload)

    assert payload["input"] == items
    assert payload["runtime_input"] == items
    assert dispatched is not None
    assert dispatched[1] == items
    assert dispatched[2] == items
