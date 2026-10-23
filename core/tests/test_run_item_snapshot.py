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
        payload={
            "status": "completed",
            "duration_ms": 12_300,
            "runtime_metrics": {
                "estimated_prompt_tokens": 120,
                "context_window_tokens": 128_000,
            },
        },
        usage={"estimated_prompt_tokens": 120, "context_window_tokens": 128_000},
    )

    snapshot = apply_run_item_event(None, event)

    assert snapshot["turns"]["turn-1"]["context_metrics"] == event.usage
    assert snapshot["turns"]["turn-1"]["duration_ms"] == 12_300
    assert "usage" not in snapshot["turns"]["turn-1"]


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
        payload={
            "status": "completed",
            "runtime_metrics": {
                "estimated_prompt_tokens": 30,
                "context_window_tokens": 128_000,
                "steps_total": 1,
            },
        },
        usage={"estimated_prompt_tokens": 30, "context_window_tokens": 128_000, "steps_total": 1},
    )

    snapshot = reduce_run_item_events("thread-1", [usage, terminal])

    assert snapshot["turns"]["turn-1"]["usage"] == {
        "input_tokens": 20,
        "output_tokens": 5,
        "llm_calls": 1,
    }
    assert snapshot["turns"]["turn-1"]["context_metrics"] == {
        "estimated_prompt_tokens": 30,
        "context_window_tokens": 128_000,
        "steps_total": 1,
    }


def test_snapshot_sums_one_call_for_each_model_usage_event():
    events = [
        RunItemEvent(
            kind="usage",
            thread_id="thread-1",
            event_id="event-call-1",
            turn_id="turn-1",
            seq=1,
            usage={"input_tokens": 10, "llm_calls": 1},
        ),
        RunItemEvent(
            kind="usage",
            thread_id="thread-1",
            event_id="event-call-2",
            turn_id="turn-1",
            seq=2,
            usage={"input_tokens": 20, "llm_calls": 1},
        ),
    ]

    snapshot = reduce_run_item_events("thread-1", events)

    assert snapshot["turns"]["turn-1"]["usage"]["llm_calls"] == 2
    assert snapshot["turns"]["turn-1"]["usage"]["input_tokens"] == 30


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


def test_replace_flagged_usage_item_is_stored_as_context_metrics():
    # `runtime.metrics` items (`replace: true`) carry session-cumulative
    # context state — they are not per-call usage deltas, so they must not
    # wipe the accumulated per-call aggregation or overwrite `llm_calls`.
    events = [
        RunItemEvent(
            kind="usage",
            thread_id="thread-1",
            event_id="event-1",
            turn_id="turn-1",
            seq=1,
            usage={"input_tokens": 10, "total_tokens": 13, "llm_calls": 1},
        ),
        RunItemEvent(
            kind="usage",
            thread_id="thread-1",
            event_id="event-2",
            turn_id="turn-1",
            seq=2,
            payload={"replace": True},
            usage={"steps_total": 1, "estimated_prompt_tokens": 30},
        ),
    ]

    snapshot = reduce_run_item_events("thread-1", events)

    assert snapshot["turns"]["turn-1"]["usage"] == {
        "input_tokens": 10,
        "total_tokens": 13,
        "llm_calls": 1,
    }
    assert snapshot["turns"]["turn-1"]["context_metrics"] == {
        "steps_total": 1,
        "estimated_prompt_tokens": 30,
    }


def test_provider_usage_envelope_does_not_become_context_metrics():
    event = RunItemEvent(
        kind="usage",
        thread_id="thread-1",
        event_id="event-provider-usage",
        turn_id="turn-1",
        payload={"type": "turn", "runtime_metrics": {"input_tokens": 12}},
        usage={"input_tokens": 12, "output_tokens": 3, "total_tokens": 15},
    )

    snapshot = apply_run_item_event(None, event)

    assert snapshot["turns"]["turn-1"]["usage"] == event.usage
    assert "context_metrics" not in snapshot["turns"]["turn-1"]


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
        "deleted_agents": {},
        "status": "idle",
    }


def test_guidance_user_item_keeps_its_text_body():
    """Mid-turn guidance arrives as a userMessage run item carrying typed input
    parts.  The durable record must keep the flat body on ``content`` — that is
    what the transcript projection reads — while the payload keeps the parts."""
    event = RunItemEvent(
        kind="message",
        thread_id="thread-1",
        event_id="event-guide",
        turn_id="turn-1",
        item_id="turn-1:user:guide:event-guide",
        seq=42,
        status="completed",
        payload={
            "type": "userMessage",
            "status": "completed",
            "content": [{"type": "text", "text": "改成蓝色"}],
        },
    )

    snapshot = apply_run_item_event(None, event)
    item = snapshot["items"]["turn-1:user:guide:event-guide"]

    assert item["content"] == "改成蓝色"
    assert item["payload"]["content"] == [{"type": "text", "text": "改成蓝色"}]


def test_guidance_user_item_without_text_leaves_content_empty():
    """A parts array with no text contributes no body; the parts stay in the
    payload so readers that need the structure (attachments) still see them."""
    event = RunItemEvent(
        kind="message",
        thread_id="thread-1",
        event_id="event-guide-attachment",
        turn_id="turn-1",
        item_id="turn-1:user:guide:event-guide-attachment",
        seq=43,
        status="completed",
        payload={
            "type": "userMessage",
            "status": "completed",
            "content": [{"type": "attachment", "attachment_id": "a-1"}],
        },
    )

    snapshot = apply_run_item_event(None, event)
    item = snapshot["items"]["turn-1:user:guide:event-guide-attachment"]

    assert item["content"] == ""
    assert item["payload"]["content"] == [{"type": "attachment", "attachment_id": "a-1"}]


def test_sub_agent_interactive_request_survives_the_main_turn_terminal_transition():
    """A sub-agent's question/approval card must stay answerable.

    The main turn can finish while a delegated sub-agent is still paused on a
    question or an approval (the supervising kernel reports the member as paused
    and ends the parent turn).  The sub-agent's request is anchored to the parent
    turn, so the parent turn's terminal transition used to close it: the request
    was marked resolved and its item forced completed, leaving the interface
    with no answerable card even though the child was still waiting (and
    `approval.respond` would still resume it).  The request belongs to the
    sub-agent's lifecycle, so the parent turn's ending must leave it open.
    """
    running = RunItemEvent(
        kind="status",
        thread_id="thread-1",
        event_id="turn-running",
        turn_id="turn-1",
        item_id="turn-1:running",
        status="running",
        payload={"type": "turn", "status": "running"},
    )
    child_question = RunItemEvent(
        kind="approval_request",
        thread_id="thread-1",
        event_id="child-question",
        run_id="turn-1",
        turn_id="turn-1",
        item_id="thread-1:sub:worker:call-9:tool",
        status="waiting",
        parent_item_id="thread-1:turn-1:call-0:tool",
        payload={
            "type": "serverRequest",
            "request_id": "call-9",
            "kind": "permission",
            "tool_name": "question",
            "message": "哪个颜色？",
            "options": [],
            "sub_agent": {"name": "worker", "type": "execute", "sub_session_id": "thread-1:sub:worker"},
        },
    )
    parent_terminal = RunItemEvent(
        kind="status",
        thread_id="thread-1",
        event_id="turn-terminal",
        turn_id="turn-1",
        item_id="turn-1:terminal",
        status="completed",
        payload={"type": "turn", "status": "completed"},
    )

    snapshot = reduce_run_item_events(
        "thread-1", [running, child_question, parent_terminal]
    )

    assert snapshot["turns"]["turn-1"]["status"] == "completed"
    # The main turn is over, but the sub-agent's card is still waiting.
    assert snapshot["requests"]["call-9"]["status"] == "open"
    assert snapshot["requests"]["call-9"]["sub_agent"]["name"] == "worker"
    assert snapshot["items"]["thread-1:sub:worker:call-9:tool"]["status"] == "waiting"

    # The sub-agent's own response closes it, not the parent turn.
    child_response = RunItemEvent(
        kind="approval_response",
        thread_id="thread-1",
        event_id="child-response",
        run_id="turn-1",
        turn_id="turn-1",
        status="completed",
        payload={"request_id": "call-9", "approved": True, "sub_agent": {"name": "worker"}},
    )
    resolved = apply_run_item_event(snapshot, child_response)
    assert resolved["requests"]["call-9"]["status"] == "resolved"


def test_resource_calls_isolate_children_and_replace_same_call_id():
    events = [
        RunItemEvent(kind="usage", thread_id="t", turn_id="turn", item_id="main", event_id="e1", seq=1,
                     usage={"llm_calls": 1, "input_tokens": 100, "cached_tokens": 80}),
        RunItemEvent(kind="usage", thread_id="t", turn_id="turn", item_id="child", parent_item_id="delegate", event_id="e2", seq=2,
                     usage={"llm_calls": 1, "input_tokens": 900, "cached_tokens": 0}),
        RunItemEvent(kind="usage", thread_id="t", turn_id="turn", item_id="main", event_id="e3", seq=3,
                     usage={"llm_calls": 1, "input_tokens": 200, "cached_tokens": 100}),
        RunItemEvent(kind="usage", thread_id="t", turn_id="turn", item_id="child-context", parent_item_id="delegate", event_id="e4", seq=4,
                     payload={"replace": True}, usage={"estimated_prompt_tokens": 700, "context_window_tokens": 1000}),
    ]
    turn = reduce_run_item_events("t", events)["turns"]["turn"]
    assert turn["usage"]["llm_calls"] == 1
    assert turn["usage"]["input_tokens"] == 200
    assert turn["usage"]["cache_hit_rate"] == 0.5
    assert len(turn["usage_calls"]) == 2
    assert turn["child_context_metrics"]["delegate"]["context_window_tokens"] == 1000
    assert "context_metrics" not in turn


def test_decision_pool_lifecycle_processing_then_ending():
    snapshot = empty_thread_snapshot("thread-1")
    processing = RunItemEvent(
        kind="interaction_update",
        thread_id="thread-1",
        event_id="event-processing",
        item_id="dec-a",
        status="processing",
        seq=1,
        payload={
            "type": "serverRequest",
            "request_id": "dec-a",
            "interaction_id": "dec-a",
            "kind": "question",
            "state": "processing",
            "lifecycle": "processing",
            "status": "processing",
            "decision_id": "dec_hash",
            "sequence": 4,
            "title": "Pick one",
            "options": [{"id": "option-1", "label": "A"}],
            "delivered_by": "agent:reader",
            "agent_name": "reader",
            "project_id": "project-1",
        },
    )
    updated = apply_run_item_event(snapshot, processing)
    assert updated["requests"]["dec-a"]["status"] == "processing"
    pool = updated.get("interactions") or []
    assert pool[0]["lifecycle"] == "processing"
    assert pool[0]["decision_id"] == "dec_hash"
    assert pool[0]["sequence"] == 4
    assert pool[0]["delivered_by"] == "agent:reader"

    ending = RunItemEvent(
        kind="approval_response",
        thread_id="thread-1",
        event_id="event-ending",
        item_id="dec-a",
        status="completed",
        seq=2,
        payload={
            "type": "serverRequest",
            "request_id": "dec-a",
            "interaction_id": "dec-a",
            "state": "ending",
            "lifecycle": "ending",
            "status": "resolved",
            "decision": "approve_once",
        },
    )
    ended = apply_run_item_event(updated, ending)
    assert ended["requests"]["dec-a"]["status"] == "resolved"
    assert ended.get("interactions") == []


def test_duplicate_approval_request_cannot_erase_options():
    """A restated request keeps the choices the original card carried."""
    first = RunItemEvent(
        kind="approval_request",
        thread_id="thread-1",
        event_id="event-1",
        turn_id="turn-1",
        item_id="approval-1",
        seq=1,
        status="waiting",
        payload={
            "type": "serverRequest",
            "request_id": "request-1",
            "tool_call_id": "call-1",
            "kind": "question",
            "message": "先检查文件还是先看报告？",
            "options": [
                {"id": "option-1", "label": "先检查文件"},
                {"id": "option-2", "label": "先看报告"},
            ],
        },
    )
    restated = RunItemEvent(
        kind="approval_request",
        thread_id="thread-1",
        event_id="event-2",
        turn_id="turn-1",
        item_id="approval-1",
        seq=2,
        status="waiting",
        payload={
            "type": "serverRequest",
            "request_id": "request-1",
            "tool_call_id": "call-1",
            "kind": "question",
            "message": "",
            "options": [],
        },
    )

    snapshot = reduce_run_item_events("thread-1", [first, restated])

    item = snapshot["items"]["approval-1"]
    assert item["status"] == "waiting"
    assert item["payload"]["options"] == [
        {"id": "option-1", "label": "先检查文件"},
        {"id": "option-2", "label": "先看报告"},
    ]
    assert item["payload"]["message"] == "先检查文件还是先看报告？"
    # The composite id and its tool-call alias describe one record.
    assert len(snapshot["requests"]) == 2
    assert snapshot["requests"]["request-1"] is snapshot["requests"]["call-1"]
    assert snapshot["requests"]["request-1"]["status"] == "open"
    assert snapshot["requests"]["request-1"]["options"] == [
        {"id": "option-1", "label": "先检查文件"},
        {"id": "option-2", "label": "先看报告"},
    ]


def test_late_approval_request_cannot_reopen_an_answered_card():
    """Ending is terminal: a duplicate after the answer changes nothing."""
    request = RunItemEvent(
        kind="approval_request",
        thread_id="thread-1",
        event_id="event-1",
        turn_id="turn-1",
        item_id="approval-1",
        seq=1,
        status="waiting",
        payload={
            "type": "serverRequest",
            "request_id": "request-1",
            "tool_call_id": "call-1",
            "kind": "question",
            "message": "先检查文件还是先看报告？",
            "options": [{"id": "option-1", "label": "先检查文件"}],
        },
    )
    answered = RunItemEvent(
        kind="approval_response",
        thread_id="thread-1",
        event_id="event-2",
        turn_id="turn-1",
        item_id="approval-1",
        seq=2,
        status="completed",
        payload={
            "request_id": "request-1",
            "interaction_id": "request-1",
            "state": "ending",
            "lifecycle": "ending",
            "status": "resolved",
            "decision": "guide",
            "guidance": "先看报告",
        },
    )
    late_repeat = RunItemEvent(
        kind="approval_request",
        thread_id="thread-1",
        event_id="event-3",
        turn_id="turn-1",
        item_id="approval-1",
        seq=3,
        status="waiting",
        payload={
            "type": "serverRequest",
            "request_id": "request-1",
            "tool_call_id": "call-1",
            "kind": "question",
            "message": "先检查文件还是先看报告？",
            "options": [],
        },
    )

    snapshot = reduce_run_item_events("thread-1", [request, answered, late_repeat])

    assert snapshot["requests"]["request-1"]["status"] == "resolved"
    assert snapshot["items"]["approval-1"]["status"] == "completed"
    assert snapshot["items"]["approval-1"].get("last_kind") != "approval_request"


def test_late_interaction_update_cannot_reinsert_an_ended_card():
    """The pool may not regain an interaction after its ending event."""
    request = RunItemEvent(
        kind="approval_request",
        thread_id="thread-1",
        event_id="event-1",
        turn_id="turn-1",
        item_id="approval-1",
        seq=1,
        status="waiting",
        payload={
            "type": "serverRequest",
            "request_id": "request-1",
            "kind": "approval",
            "options": [{"id": "approve", "label": "批准执行"}],
        },
    )
    answered = RunItemEvent(
        kind="approval_response",
        thread_id="thread-1",
        event_id="event-2",
        turn_id="turn-1",
        item_id="approval-1",
        seq=2,
        status="completed",
        payload={
            "request_id": "request-1",
            "interaction_id": "request-1",
            "state": "ending",
            "status": "resolved",
        },
    )
    late_update = RunItemEvent(
        kind="interaction_update",
        thread_id="thread-1",
        event_id="event-3",
        turn_id="turn-1",
        item_id="interaction:request-1",
        seq=3,
        status="pending",
        payload={
            "request_id": "request-1",
            "interaction_id": "request-1",
            "kind": "approval",
            "state": "appearing",
            "options": [{"id": "approve", "label": "批准执行"}],
        },
    )

    snapshot = reduce_run_item_events("thread-1", [request, answered, late_update])

    assert not snapshot.get("interactions")
    assert snapshot["requests"]["request-1"]["status"] == "resolved"
