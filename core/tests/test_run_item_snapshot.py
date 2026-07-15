"""Tests for canonical run item events and snapshots."""

from lamtools_core.event import RunItemEvent
from lamtools_core.snapshot import (
    InMemorySnapshotStore,
    apply_run_item_event,
    empty_thread_snapshot,
    reduce_run_item_events,
)


def test_run_item_event_round_trip():
    event = RunItemEvent(
        kind="tool_call",
        thread_id="thread-1",
        event_id="event-1",
        run_id="run-1",
        turn_id="turn-1",
        item_id="item-1",
        parent_item_id="parent-1",
        seq=7,
        status="running",
        payload={"tool": "search"},
        artifacts=[{"artifact_id": "artifact-1", "kind": "json"}],
        usage={"input_tokens": 12},
        source="kernel",
        created_at_ms=12345,
        metadata={"agent": "base"},
    )

    restored = RunItemEvent.from_dict(event.to_dict())

    assert restored == event


def test_snapshot_is_idempotent_by_event_id():
    event = RunItemEvent(
        kind="message",
        thread_id="thread-1",
        event_id="event-1",
        turn_id="turn-1",
        item_id="message-1",
        payload={"delta": "hello"},
    )

    snapshot = apply_run_item_event(None, event)
    duplicate = apply_run_item_event(snapshot, event)

    assert duplicate["items"]["message-1"]["content"] == "hello"
    assert duplicate["items"]["message-1"]["deltas"] == ["hello"]
    assert duplicate["snapshot_seq"] == snapshot["snapshot_seq"]
    assert duplicate["seen_event_ids"] == ["event-1"]


def test_snapshot_accumulates_message_deltas_and_turn_items():
    events = [
        RunItemEvent(
            kind="message",
            thread_id="thread-1",
            event_id="event-1",
            turn_id="turn-1",
            item_id="message-1",
            seq=1,
            payload={"delta": "hel"},
        ),
        RunItemEvent(
            kind="message",
            thread_id="thread-1",
            event_id="event-2",
            turn_id="turn-1",
            item_id="message-1",
            seq=2,
            status="completed",
            payload={"delta": "lo"},
        ),
    ]

    snapshot = reduce_run_item_events("thread-1", events)

    assert snapshot["items"]["message-1"]["content"] == "hello"
    assert snapshot["items"]["message-1"]["deltas"] == ["hel", "lo"]
    assert snapshot["turns"]["turn-1"]["items"] == ["message-1"]
    assert snapshot["status"] == "running"


def test_completed_intermediate_message_does_not_complete_the_turn():
    events = [
        RunItemEvent(
            kind="message",
            thread_id="thread-1",
            event_id="message-completed",
            turn_id="turn-1",
            item_id="message-1",
            seq=1,
            status="completed",
            payload={"type": "agentMessage", "content": "I will continue with tools."},
        ),
        RunItemEvent(
            kind="tool_call",
            thread_id="thread-1",
            event_id="tool-started",
            turn_id="turn-1",
            item_id="tool-1",
            seq=2,
            status="running",
            payload={"type": "dynamicToolCall", "tool_name": "read_file"},
        ),
    ]

    snapshot = reduce_run_item_events("thread-1", events)

    assert snapshot["turns"]["turn-1"]["status"] == "running"
    assert snapshot["status"] == "running"


def test_snapshot_persists_terminal_status_usage_on_the_turn():
    event = RunItemEvent(
        kind="status",
        thread_id="thread-1",
        event_id="event-terminal",
        turn_id="turn-1",
        item_id="turn-1:terminal",
        status="completed",
        payload={"status": "completed"},
        usage={"estimated_prompt_tokens": 120, "context_window_tokens": 128_000},
    )

    snapshot = apply_run_item_event(None, event)

    assert snapshot["turns"]["turn-1"]["usage"] == event.usage


def test_terminal_status_metrics_preserve_exact_usage_without_double_counting_calls():
    usage = RunItemEvent(
        kind="usage",
        thread_id="thread-1",
        event_id="event-usage",
        turn_id="turn-1",
        seq=1,
        usage={"input_tokens": 20, "output_tokens": 5, "llm_calls": 1},
    )
    terminal = RunItemEvent(
        kind="status",
        thread_id="thread-1",
        event_id="event-terminal",
        turn_id="turn-1",
        seq=2,
        status="completed",
        payload={"status": "completed"},
        usage={"estimated_prompt_tokens": 30, "context_window_tokens": 128_000, "llm_calls": 1},
    )

    snapshot = reduce_run_item_events("thread-1", [usage, terminal])

    assert snapshot["turns"]["turn-1"]["usage"] == {
        "input_tokens": 20,
        "output_tokens": 5,
        "estimated_prompt_tokens": 30,
        "context_window_tokens": 128_000,
        "llm_calls": 1,
    }


def test_snapshot_tracks_tool_call_and_result_items():
    events = [
        RunItemEvent(
            kind="tool_call",
            thread_id="thread-1",
            event_id="event-1",
            turn_id="turn-1",
            item_id="tool-1",
            seq=1,
            payload={"name": "read_file", "arguments": {"path": "README.md"}},
        ),
        RunItemEvent(
            kind="tool_result",
            thread_id="thread-1",
            event_id="event-2",
            turn_id="turn-1",
            item_id="tool-result-1",
            parent_item_id="tool-1",
            seq=2,
            status="completed",
            payload={"content": "ok"},
        ),
    ]

    snapshot = reduce_run_item_events("thread-1", events)

    assert snapshot["item_order"] == ["tool-1", "tool-result-1"]
    assert snapshot["items"]["tool-1"]["payload"]["name"] == "read_file"
    assert snapshot["items"]["tool-result-1"]["parent_item_id"] == "tool-1"
    assert snapshot["items"]["tool-result-1"]["content"] == "ok"


def test_terminal_tool_result_replaces_waiting_content_for_the_same_item():
    events = [
        RunItemEvent(
            kind="tool_result",
            thread_id="thread-1",
            event_id="event-waiting",
            turn_id="turn-1",
            item_id="sub-agent-1",
            seq=1,
            status="waiting",
            payload={"delta": "Sub-agent is waiting for approval."},
        ),
        RunItemEvent(
            kind="tool_result",
            thread_id="thread-1",
            event_id="event-completed",
            turn_id="turn-1",
            item_id="sub-agent-1",
            seq=2,
            status="completed",
            payload={"delta": "Child completed the task.", "replace": True},
        ),
    ]

    snapshot = reduce_run_item_events("thread-1", events)

    assert snapshot["items"]["sub-agent-1"]["content"] == "Child completed the task."
    assert snapshot["items"]["sub-agent-1"]["deltas"] == ["Child completed the task."]


def test_snapshot_preserves_tool_input_preview():
    event = RunItemEvent(
        kind="tool_call",
        thread_id="thread-1",
        event_id="event-1",
        turn_id="turn-1",
        item_id="thread-1:run-1:call-1:tool",
        seq=1,
        status="running",
        payload={
            "type": "dynamicToolCall",
            "tool_name": "write_file",
            "arguments": {"path": "index.html"},
            "input_preview": {
                "field": "content",
                "content": "<html>",
                "chars": 6,
                "truncated": False,
            },
        },
    )

    snapshot = reduce_run_item_events("thread-1", [event])
    item = snapshot["items"]["thread-1:run-1:call-1:tool"]

    assert item["payload"]["input_preview"]["content"] == "<html>"


def test_snapshot_tool_input_preview_does_not_clear_existing_arguments():
    events = [
        RunItemEvent(
            kind="tool_call",
            thread_id="thread-1",
            event_id="event-1",
            turn_id="turn-1",
            item_id="tool-1",
            seq=1,
            status="running",
            payload={
                "type": "dynamicToolCall",
                "tool_name": "write_file",
                "arguments": {"path": "index.html"},
            },
        ),
        RunItemEvent(
            kind="tool_call",
            thread_id="thread-1",
            event_id="event-2",
            turn_id="turn-1",
            item_id="tool-1",
            seq=2,
            status="running",
            payload={
                "type": "dynamicToolCall",
                "tool_name": "write_file",
                "input_preview": {
                    "field": "content",
                    "content": "<html>",
                    "chars": 6,
                    "truncated": False,
                },
            },
        ),
    ]

    snapshot = reduce_run_item_events("thread-1", events)

    assert snapshot["items"]["tool-1"]["payload"]["arguments"] == {"path": "index.html"}
    assert snapshot["items"]["tool-1"]["payload"]["input_preview"]["content"] == "<html>"


def test_snapshot_promotes_same_tool_item_to_tool_result():
    events = [
        RunItemEvent(
            kind="tool_call",
            thread_id="thread-1",
            event_id="event-1",
            turn_id="turn-1",
            item_id="tool-1",
            seq=1,
            status="running",
            payload={"type": "dynamicToolCall", "tool_name": "run_command", "arguments": {"command": "echo ok"}},
        ),
        RunItemEvent(
            kind="tool_result",
            thread_id="thread-1",
            event_id="event-2",
            turn_id="turn-1",
            item_id="tool-1",
            seq=2,
            status="running",
            payload={
                "type": "dynamicToolCall",
                "tool_name": "run_command",
                "tool_result": "[stdout]\nok",
                "delta": "[stdout]\nok",
            },
        ),
    ]

    snapshot = reduce_run_item_events("thread-1", events)
    item = snapshot["items"]["tool-1"]

    assert item["kind"] == "tool_result"
    assert item["last_kind"] == "tool_result"
    assert item["status"] == "running"
    assert item["payload"]["tool_result"] == "[stdout]\nok"


def test_snapshot_indexes_tool_result_artifacts():
    event = RunItemEvent(
        kind="tool_result",
        thread_id="thread-1",
        event_id="event-1",
        turn_id="turn-1",
        item_id="tool-1",
        status="completed",
        payload={"content": "created"},
        artifacts=[
            {
                "artifact_id": "artifact-1",
                "item_id": "tool-1",
                "kind": "file_create",
                "path": "notes.md",
            }
        ],
    )

    snapshot = apply_run_item_event(None, event)

    assert snapshot["artifacts"]["artifact-1"]["path"] == "notes.md"
    assert snapshot["items"]["tool-1"]["artifacts"][0]["artifact_id"] == "artifact-1"


def test_snapshot_resolves_approval_request():
    request = RunItemEvent(
        kind="approval_request",
        thread_id="thread-1",
        event_id="event-1",
        turn_id="turn-1",
        item_id="approval-1",
        seq=1,
        payload={"request_id": "request-1", "reason": "run command"},
    )
    response = RunItemEvent(
        kind="approval_response",
        thread_id="thread-1",
        event_id="event-2",
        turn_id="turn-1",
        seq=2,
        status="completed",
        payload={"request_id": "request-1", "approved": True},
    )

    waiting = apply_run_item_event(None, request)
    resolved = apply_run_item_event(waiting, response)

    assert waiting["status"] == "waiting"
    assert waiting["requests"]["request-1"]["status"] == "open"
    assert resolved["status"] == "running"
    assert resolved["turns"]["turn-1"]["status"] == "running"
    assert resolved["requests"]["request-1"]["status"] == "resolved"
    assert resolved["requests"]["request-1"]["approved"] is True


def test_snapshot_tracks_error_as_failed_thread():
    event = RunItemEvent(
        kind="error",
        thread_id="thread-1",
        event_id="event-1",
        turn_id="turn-1",
        item_id="error-1",
        status="failed",
        payload={"type": "runtime", "message": "boom"},
    )

    snapshot = apply_run_item_event(None, event)

    assert snapshot["status"] == "failed"
    assert snapshot["turns"]["turn-1"]["status"] == "failed"
    assert snapshot["items"]["error-1"]["status"] == "failed"
    assert snapshot["last_error"] == {"type": "runtime", "message": "boom"}


def test_snapshot_persists_terminal_status_error_for_reconnect_display():
    event = RunItemEvent(
        kind="status",
        thread_id="thread-1",
        event_id="event-terminal",
        turn_id="turn-1",
        item_id="turn-1:terminal",
        status="failed",
        payload={
            "type": "turn",
            "status": "failed",
            "raw_end_reason": "invalid_tool_arguments",
            "message": "Invalid tool arguments: path must be a string",
        },
    )

    snapshot = apply_run_item_event(None, event)

    assert snapshot["status"] == "failed"
    assert snapshot["turns"]["turn-1"]["items"] == ["turn-1:terminal"]
    assert snapshot["items"]["turn-1:terminal"]["payload"]["message"] == (
        "Invalid tool arguments: path must be a string"
    )
    assert snapshot["last_error"]["raw_end_reason"] == "invalid_tool_arguments"


def test_cancelled_turn_closes_running_items_and_ignores_late_child_events():
    events = [
        RunItemEvent(
            kind="tool_call",
            thread_id="thread-1",
            event_id="sub-agent-started",
            run_id="parent-run",
            turn_id="turn-1",
            item_id="sub-agent-tool",
            seq=1,
            status="running",
            payload={"type": "dynamicToolCall", "tool_name": "sub_agent"},
        ),
        RunItemEvent(
            kind="status",
            thread_id="thread-1",
            event_id="parent-cancelled",
            run_id="parent-run",
            turn_id="turn-1",
            item_id="turn-1:cancelled",
            seq=2,
            status="cancelled",
            payload={"type": "turn", "status": "cancelled", "raw_end_reason": "user_interrupt"},
        ),
        RunItemEvent(
            kind="status",
            thread_id="thread-1",
            event_id="late-child-done",
            run_id="parent-run",
            turn_id="turn-1",
            item_id="child-terminal",
            seq=3,
            status="completed",
            payload={"type": "turn", "status": "completed"},
        ),
        RunItemEvent(
            kind="tool_result",
            thread_id="thread-1",
            event_id="late-child-output",
            run_id="parent-run",
            turn_id="turn-1",
            item_id="sub-agent-tool",
            seq=4,
            status="running",
            payload={"type": "dynamicToolCall", "delta": "late output"},
        ),
    ]

    snapshot = reduce_run_item_events("thread-1", events)

    assert snapshot["status"] == "cancelled"
    assert snapshot["turns"]["turn-1"]["status"] == "cancelled"
    assert snapshot["items"]["sub-agent-tool"]["status"] == "cancelled"


def test_recoverable_item_error_does_not_fail_running_turn():
    error = RunItemEvent(
        kind="message",
        thread_id="thread-1",
        event_id="event-1",
        turn_id="turn-1",
        item_id="error-1",
        seq=1,
        status="failed",
        payload={"type": "error", "content": "LLM API error 503"},
    )
    retry = RunItemEvent(
        kind="message",
        thread_id="thread-1",
        event_id="event-2",
        turn_id="turn-1",
        item_id="retry-1",
        seq=2,
        status="running",
        payload={"type": "status", "content": "模型请求重试中 (1/9)"},
    )

    after_error = apply_run_item_event(None, error)
    snapshot = apply_run_item_event(after_error, retry)

    assert after_error["status"] == "running"
    assert after_error["turns"]["turn-1"]["status"] == "running"
    assert after_error["items"]["error-1"]["status"] == "failed"
    assert snapshot["status"] == "running"
    assert snapshot["turns"]["turn-1"]["status"] == "running"
    assert snapshot["items"]["retry-1"]["content"] == "模型请求重试中 (1/9)"


def test_snapshot_indexes_artifacts_and_merges_usage():
    events = [
        RunItemEvent(
            kind="artifact",
            thread_id="thread-1",
            event_id="event-1",
            turn_id="turn-1",
            item_id="artifact-item-1",
            seq=1,
            status="completed",
            artifacts=[{"artifact_id": "artifact-1", "kind": "file"}],
        ),
        RunItemEvent(
            kind="usage",
            thread_id="thread-1",
            event_id="event-2",
            turn_id="turn-1",
            seq=2,
            status="completed",
            usage={"input_tokens": 10, "output_tokens": 3},
        ),
        RunItemEvent(
            kind="usage",
            thread_id="thread-1",
            event_id="event-3",
            turn_id="turn-1",
            seq=3,
            status="completed",
            usage={"input_tokens": 5, "total_tokens": 18},
        ),
    ]

    snapshot = reduce_run_item_events("thread-1", events)

    assert snapshot["artifacts"]["artifact-1"] == {"artifact_id": "artifact-1", "kind": "file"}
    assert snapshot["turns"]["turn-1"]["usage"] == {
        "input_tokens": 15,
        "output_tokens": 3,
        "total_tokens": 18,
    }


def test_snapshot_replaces_usage_when_requested():
    events = [
        RunItemEvent(
            kind="usage",
            thread_id="thread-1",
            event_id="event-1",
            turn_id="turn-1",
            seq=1,
            usage={"input_tokens": 10, "total_tokens": 13},
        ),
        RunItemEvent(
            kind="usage",
            thread_id="thread-1",
            event_id="event-2",
            turn_id="turn-1",
            seq=2,
            payload={"replace": True},
            usage={"duration_ms": 12_300, "total_tokens": 42},
        ),
    ]

    snapshot = reduce_run_item_events("thread-1", events)

    assert snapshot["turns"]["turn-1"]["usage"] == {
        "duration_ms": 12_300,
        "total_tokens": 42,
    }


def test_reduce_orders_events_by_sequence():
    events = [
        RunItemEvent(
            kind="message",
            thread_id="thread-1",
            event_id="event-2",
            turn_id="turn-1",
            item_id="message-1",
            seq=2,
            status="completed",
            payload={"delta": "second"},
        ),
        RunItemEvent(
            kind="message",
            thread_id="thread-1",
            event_id="event-1",
            turn_id="turn-1",
            item_id="message-1",
            seq=1,
            payload={"delta": "first "},
        ),
    ]

    snapshot = reduce_run_item_events("thread-1", events)

    assert snapshot["items"]["message-1"]["content"] == "first second"


def test_in_memory_snapshot_store_applies_and_copies_state():
    store = InMemorySnapshotStore()
    event = RunItemEvent(
        kind="message",
        thread_id="thread-1",
        event_id="event-1",
        turn_id="turn-1",
        item_id="message-1",
        payload={"content": "saved"},
        status="completed",
    )

    applied = store.apply(event)
    applied["items"]["message-1"]["content"] = "mutated"
    loaded = store.get("thread-1")

    assert loaded is not None
    assert loaded["items"]["message-1"]["content"] == "saved"


def test_empty_snapshot_shape_is_member_neutral():
    snapshot = empty_thread_snapshot("thread-1")

    assert snapshot == {
        "thread_id": "thread-1",
        "snapshot_seq": 0,
        "seen_event_ids": [],
        "turns": {},
        "items": {},
        "item_order": [],
        "requests": {},
        "artifacts": {},
        "status": "idle",
    }
