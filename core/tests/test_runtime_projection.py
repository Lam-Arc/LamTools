"""Tests for runtime fact to RunItemEvent projection."""

from datetime import datetime, timezone

from lamtools_core.event.runtime_projection import (
    RuntimeProjectionBuffer,
    RuntimeProjectionInput,
    extract_tool_input_preview,
    event_model_call_id,
    raw_tool_call_id_from_payload,
    runtime_fact_to_run_item_events,
    runtime_group_from_event_name,
    runtime_payload_preview,
    runtime_projection_to_run_item_events,
    runtime_summary_from_event_name,
    tool_args_from_payload,
    tool_call_id_from_payload,
    usage_tokens,
    visible_runtime_part_content,
)


def _part_fact(event_id: str, content: str) -> RuntimeProjectionInput:
    return RuntimeProjectionInput(
        id=event_id,
        thread_id="thread-1",
        group="runtime",
        source="core",
        phase="runtime.part",
        status="running",
        sequence=1,
        summary=content,
        preview=content,
        full_text=content,
        metadata={
            "payload": {
                "turn_id": "turn-1",
                "part_id": "reasoning-1",
                "part_type": "reasoning",
                "content": content,
            }
        },
        created_at=datetime.now(timezone.utc),
    )


def test_runtime_projection_accumulates_tool_input_delta_preview():
    first = runtime_fact_to_run_item_events(
        thread_id="thread-1",
        event_id="evt-1",
        group="runtime",
        source="core",
        phase="runtime.part",
        status="running",
        sequence=1,
        summary="",
        metadata={
            "payload": {
                "part_type": "tool_call",
                "status": "running",
                "tool_name": "write_file",
                "call_id": "call-1",
                "tool_args": {"path": "index.html"},
                "run_id": "run-1",
                "turn_id": "turn-1",
            }
        },
    )
    second = runtime_fact_to_run_item_events(
        thread_id="thread-1",
        event_id="evt-2",
        group="runtime",
        source="core",
        phase="runtime.part",
        status="running",
        sequence=2,
        summary="",
        metadata={
            "payload": {
                "part_type": "tool_input_delta",
                "status": "running",
                "tool_name": "write_file",
                "call_id": "call-1",
                "delta": '{"path":"index.html","content":"<html>',
                "arguments_text": '{"path":"index.html","content":"<html>',
                "run_id": "run-1",
                "turn_id": "turn-1",
            }
        },
    )

    assert first is not None
    assert second is not None
    assert first[0].item_id == second[0].item_id
    assert "arguments" not in second[0].payload
    assert second[0].payload["input_preview"]["field"] == "content"
    assert second[0].payload["input_preview"]["content"] == "<html>"


def test_runtime_projection_gives_tool_input_growth_unique_event_ids():
    buffer = RuntimeProjectionBuffer()
    first = buffer.merge_part_growth(RuntimeProjectionInput(
        id="fact-1",
        thread_id="thread-1",
        group="runtime",
        source="core",
        phase="runtime.part",
        status="running",
        sequence=1,
        metadata={
            "payload": {
                "part_type": "tool_input_delta",
                "status": "running",
                "tool_name": "write_file",
                "call_id": "call-1",
                "part_id": "run-1:response-0:tool-call-0:input",
                "arguments_text": '{"path":"README.md","content":"#',
                "run_id": "run-1",
                "turn_id": "turn-1",
            }
        },
        created_at=datetime.now(timezone.utc),
    ))
    first_events = runtime_projection_to_run_item_events(first)

    second = buffer.merge_part_growth(RuntimeProjectionInput(
        id="fact-2",
        thread_id="thread-1",
        group="runtime",
        source="core",
        phase="runtime.part",
        status="running",
        sequence=2,
        metadata={
            "payload": {
                "part_type": "tool_input_delta",
                "status": "running",
                "tool_name": "write_file",
                "call_id": "call-1",
                "part_id": "run-1:response-0:tool-call-0:input",
                "arguments_text": '{"path":"README.md","content":"# Title',
                "run_id": "run-1",
                "turn_id": "turn-1",
            }
        },
        created_at=datetime.now(timezone.utc),
    ))
    second_events = runtime_projection_to_run_item_events(second)

    assert first_events is not None
    assert second_events is not None
    assert first_events[0].item_id == second_events[0].item_id
    assert first_events[0].event_id != second_events[0].event_id
    assert second_events[0].payload["input_preview"]["content"] == "# Title"


def test_extract_tool_input_preview_write_file_content():
    preview = extract_tool_input_preview(
        "write_file",
        '{"path":"index.html","content":"hello\\nworld',
    )

    assert preview == {
        "field": "content",
        "content": "hello\nworld",
        "chars": 11,
        "truncated": False,
    }


def test_extract_tool_input_preview_edit_file_new_text():
    preview = extract_tool_input_preview(
        "edit_file",
        '{"path":"main.py","old_text":"old","new_text":"new\\nvalue',
    )

    assert preview == {
        "field": "new_text",
        "content": "new\nvalue",
        "chars": 9,
        "truncated": False,
    }


def test_extract_tool_input_preview_ignores_read_tools():
    assert extract_tool_input_preview("read_file", '{"path":"a.py"}') is None


def test_runtime_projection_maps_tool_lifecycle():
    events = runtime_fact_to_run_item_events(
        thread_id="thread-1",
        event_id="event-1",
        group="tool",
        source="core",
        phase="runtime.tool.started",
        status="running",
        sequence=7,
        summary="read file",
        metadata={
            "payload": {
                "turn_id": "turn-1",
                "tool_name": "read_file",
                "call_id": "call-1",
                "arguments": {"path": "README.md"},
            }
        },
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert events is not None
    assert len(events) == 1
    event = events[0]
    assert event.kind == "tool_call"
    assert event.thread_id == "thread-1"
    assert event.turn_id == "turn-1"
    assert event.item_id == "thread-1:turn-1:call-1:tool"
    assert event.seq == 7
    assert event.payload["tool_name"] == "read_file"
    assert event.payload["arguments"] == {"path": "README.md"}


def test_runtime_projection_preserves_tool_result_metadata():
    events = runtime_fact_to_run_item_events(
        thread_id="thread-1",
        event_id="event-1",
        group="tool",
        source="core",
        phase="runtime.tool.finished",
        status="ok",
        sequence=8,
        preview="done",
        metadata={
            "payload": {
                "turn_id": "turn-1",
                "tool_name": "sub_agent",
                "call_id": "call-1",
                "content": "agent result",
                "metadata": {
                    "agent_name": "reviewer",
                    "agent_index": "001",
                },
            }
        },
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert events is not None
    assert len(events) == 1
    event = events[0]
    assert event.kind == "tool_result"
    assert event.payload["metadata"] == {
        "agent_name": "reviewer",
        "agent_index": "001",
    }
    assert event.payload["tool_result"] == "agent result"


def test_runtime_part_tool_result_projects_as_running_tool_result():
    events = runtime_fact_to_run_item_events(
        thread_id="thread-1",
        event_id="event-1",
        group="tool",
        source="core",
        phase="runtime.part",
        status="running",
        sequence=9,
        preview="[stdout]\nline 1",
        metadata={
            "payload": {
                "turn_id": "turn-1",
                "part_id": "call-1:result",
                "part_type": "tool_result",
                "status": "running",
                "content": "[stdout]\nline 1",
                "tool_name": "run_command",
                "call_id": "call-1",
                "metadata": {
                    "command": "echo line 1",
                },
            }
        },
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert events is not None
    assert len(events) == 1
    event = events[0]
    assert event.kind == "tool_result"
    assert event.item_id == "thread-1:turn-1:call-1:tool"
    assert event.status == "running"
    assert event.payload["tool_name"] == "run_command"
    assert event.payload["tool_result"] == "[stdout]\nline 1"
    assert event.payload["metadata"]["command"] == "echo line 1"


def test_runtime_projection_scopes_reused_tool_call_ids_by_run():
    first = runtime_fact_to_run_item_events(
        thread_id="thread-1",
        event_id="event-1",
        group="tool",
        source="core",
        phase="runtime.part",
        status="running",
        sequence=1,
        metadata={
            "payload": {
                "turn_id": "turn-1",
                "run_id": "run-1",
                "part_type": "tool_call",
                "tool_name": "write_file",
                "call_id": "functions.write_file:0",
                "content": "准备调用 write_file",
            }
        },
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    second = runtime_fact_to_run_item_events(
        thread_id="thread-1",
        event_id="event-2",
        group="tool",
        source="core",
        phase="runtime.part",
        status="running",
        sequence=2,
        metadata={
            "payload": {
                "turn_id": "turn-2",
                "run_id": "run-2",
                "part_type": "tool_call",
                "tool_name": "write_file",
                "call_id": "functions.write_file:0",
                "content": "准备调用 write_file",
            }
        },
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert first is not None
    assert second is not None
    assert first[0].item_id == "thread-1:run-1:functions.write_file:0:tool"
    assert second[0].item_id == "thread-1:run-2:functions.write_file:0:tool"


def test_runtime_projection_keeps_tool_call_and_result_part_on_same_run_item():
    call_events = runtime_fact_to_run_item_events(
        thread_id="thread-1",
        event_id="event-1",
        group="tool",
        source="core",
        phase="runtime.part",
        status="running",
        sequence=1,
        metadata={
            "payload": {
                "turn_id": "turn-1",
                "run_id": "run-1",
                "part_type": "tool_call",
                "tool_name": "run_command",
                "call_id": "functions.run_command:0",
                "content": "准备调用 run_command",
            }
        },
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    progress_events = runtime_fact_to_run_item_events(
        thread_id="thread-1",
        event_id="event-2",
        group="tool",
        source="core",
        phase="runtime.part",
        status="running",
        sequence=2,
        metadata={
            "payload": {
                "turn_id": "turn-1",
                "run_id": "run-1",
                "part_type": "tool_result",
                "tool_name": "run_command",
                "call_id": "functions.run_command:0",
                "content": "[stdout]\nline 1",
            }
        },
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert call_events is not None
    assert progress_events is not None
    assert call_events[0].item_id == progress_events[0].item_id


def test_runtime_projection_omits_forwarded_sub_agent_events_from_main_timeline():
    events = runtime_fact_to_run_item_events(
        thread_id="thread-1",
        event_id="event-1",
        group="plan",
        source="core",
        phase="runtime.part",
        status="completed",
        sequence=9,
        preview="nested result",
        metadata={
            "payload": {
                "turn_id": "turn-1",
                "part_id": "child-run:response-0:text",
                "part_type": "text",
                "content": "nested result",
                "sub_agent": {
                    "sub_line_id": "subline-1",
                    "agent": "reviewer",
                },
            }
        },
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert events == []


def test_runtime_projection_maps_terminal_status():
    events = runtime_fact_to_run_item_events(
        thread_id="thread-1",
        event_id="event-1",
        group="system",
        source="core",
        phase="runtime.done",
        status="completed",
        sequence=11,
        summary="finished",
        metadata={
            "payload": {
                "turn_id": "turn-1",
                "decision": "done",
                "runtime_metrics": {"total_tokens": 42},
            }
        },
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert events is not None
    assert len(events) == 1
    event = events[0]
    assert event.kind == "status"
    assert event.status == "completed"
    assert event.payload == {
        "type": "turn",
        "status": "completed",
        "raw_end_reason": "done",
        "message": "finished",
        "runtime_metrics": {"total_tokens": 42},
    }


def test_runtime_projection_maps_usage_metrics():
    events = runtime_fact_to_run_item_events(
        thread_id="thread-1",
        event_id="event-1",
        group="usage",
        source="core",
        phase="runtime.usage",
        status="completed",
        sequence=3,
        metadata={
            "payload": {
                "turn_id": "turn-1",
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "prompt_tokens_details": {"cached_tokens": 4},
                },
            }
        },
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert events is not None
    assert len(events) == 1
    event = events[0]
    assert event.kind == "usage"
    assert event.usage == {
        "input_tokens": 10,
        "output_tokens": 5,
        "total_tokens": 15,
        "cached_tokens": 4,
        "cache_hit_rate": 0.4,
        "llm_calls": 1,
    }


def test_runtime_projection_buffer_reuses_first_fact_id_and_updates_content():
    buffer = RuntimeProjectionBuffer()

    first = buffer.merge_part_growth(_part_fact("event-1", "用"))
    grown = buffer.merge_part_growth(_part_fact("event-2", "用户提供的视频里，思考块不应该只剩两个字。"))

    assert first is grown
    assert grown.id == "event-1"
    run_items = runtime_projection_to_run_item_events(grown)
    assert len(run_items) == 1
    assert run_items[0].item_id == "reasoning-1"
    assert run_items[0].payload["content"] == "用户提供的视频里，思考块不应该只剩两个字。"


def test_runtime_projection_preserves_compaction_display_metadata():
    fact = RuntimeProjectionInput(
        id="compact-event-1",
        thread_id="thread-1",
        group="runtime",
        source="core",
        phase="runtime.part",
        status="completed",
        sequence=9,
        summary="[Compacted Context]\n1. Current Goal\n- Continue.",
        preview="[Compacted Context]\n1. Current Goal\n- Continue.",
        full_text="[Compacted Context]\n1. Current Goal\n- Continue.",
        metadata={
            "payload": {
                "turn_id": "turn-1",
                "part_id": "turn-1:context-compaction",
                "part_type": "compaction",
                "content": "[Compacted Context]\n1. Current Goal\n- Continue.",
                "label": "上下文已压缩",
                "before_tokens": 351051,
                "after_tokens": 153000,
                "target_tokens": 153600,
                "removed_messages": 42,
                "trigger": "auto",
            }
        },
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    run_items = runtime_projection_to_run_item_events(fact)

    assert len(run_items) == 1
    assert run_items[0].payload["type"] == "compaction"
    assert run_items[0].payload["label"] == "上下文已压缩"
    assert run_items[0].payload["before_tokens"] == 351051
    assert run_items[0].payload["after_tokens"] == 153000
    assert run_items[0].payload["target_tokens"] == 153600
    assert run_items[0].payload["removed_messages"] == 42
    assert run_items[0].payload["trigger"] == "auto"


def test_runtime_event_name_helpers_are_member_neutral():
    assert runtime_group_from_event_name("runtime.tool.started") == "tool"
    assert runtime_group_from_event_name("runtime.verification") == "verification"
    assert runtime_group_from_event_name("runtime.done") == "system"
    assert runtime_group_from_event_name("runtime.context_compacted") == "plan"

    assert runtime_summary_from_event_name("runtime.tool.started", {"tool_name": "read_file"}) == "开始执行工具：read_file"
    assert runtime_summary_from_event_name("runtime.failed", {"error": "boom"}) == "boom"
    assert runtime_summary_from_event_name("runtime.unknown", {"message": "working"}) == "working"


def test_runtime_payload_preview_bounds_nested_payloads():
    preview = runtime_payload_preview(
        {
            **{f"k{i}": i for i in range(45)},
            "nested": [{"text": "abcdef"}, {"value": object()}],
        },
        max_text_chars=3,
    )

    assert len(preview) == 40
    assert preview["k0"] == 0
    nested = runtime_payload_preview({"nested": [{"text": "abcdef"}, {"value": object()}]}, max_text_chars=3)
    assert nested["nested"][0]["text"] == "abc"
    assert isinstance(nested["nested"][1]["value"], str)


def test_runtime_payload_helpers_normalize_response_and_tool_ids():
    assert event_model_call_id(
        {"payload": {"run_id": "run-1", "response_index": 2}},
        fallback_run_id="fallback",
    ) == "run-1:response-2"

    payload = {"part_id": "part-call-1", "arguments": {"path": "a.md"}}
    storage_id = tool_call_id_from_payload(
        payload,
        fallback_call_id="model-call-1",
        sequence=3,
        turn_id="turn-1",
    )

    assert storage_id == "model-call-1:call-1"
    assert raw_tool_call_id_from_payload(payload, storage_id) == "call-1"
    assert tool_args_from_payload(payload) == {"path": "a.md"}


def test_runtime_payload_helpers_parse_usage_and_visible_content():
    assert usage_tokens({"prompt_tokens": "12"}, "input_tokens", "prompt_tokens") == 12
    assert visible_runtime_part_content(
        {"content": "runtime.part", "detail": "visible"},
        full_text="",
        preview="",
        summary="",
    ) == "visible"
