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


def test_runtime_tool_started_edit_file_arguments_include_input_preview():
    events = runtime_fact_to_run_item_events(
        thread_id="thread-1",
        event_id="event-edit-started",
        group="tool",
        source="core",
        phase="runtime.tool.started",
        status="running",
        sequence=1,
        metadata={
            "payload": {
                "turn_id": "turn-1",
                "tool_name": "edit_file",
                "call_id": "edit-1",
                "arguments": {
                    "path": "main.py",
                    "old_text": "old",
                    "new_text": "new\nvalue",
                },
            }
        },
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert events is not None
    assert events[0].payload["input_preview"] == {
        "field": "new_text",
        "content": "new\nvalue",
        "chars": 9,
        "truncated": False,
    }


def test_runtime_part_edit_file_tool_args_include_input_preview():
    events = runtime_fact_to_run_item_events(
        thread_id="thread-1",
        event_id="event-edit-part",
        group="runtime",
        source="core",
        phase="runtime.part",
        status="running",
        sequence=1,
        metadata={
            "payload": {
                "turn_id": "turn-1",
                "run_id": "run-1",
                "part_type": "tool_call",
                "tool_name": "edit_file",
                "call_id": "edit-1",
                "tool_args": {
                    "path": "main.py",
                    "old_text": "old",
                    "new_text": "new\nvalue",
                },
            }
        },
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert events is not None
    assert events[0].payload["input_preview"]["field"] == "new_text"
    assert events[0].payload["input_preview"]["content"] == "new\nvalue"


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


def test_runtime_projection_preserves_file_artifact_content():
    diff = "--- a/notes.txt\n+++ b/notes.txt\n@@ -1 +1 @@\n-old\n+new"
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
            "run_id": "run-1",
            "payload": {
                "turn_id": "turn-1",
                "tool_name": "edit_file",
                "call_id": "call-1",
                "content": "Edited notes.txt",
                "artifacts": [{
                    "kind": "file_change",
                    "uri": "notes.txt",
                    "content": diff,
                    "metadata": {"path": "notes.txt", "action": "edit"},
                }],
            }
        },
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert events is not None
    artifact = events[0].artifacts[0]
    assert artifact["uri"] == "notes.txt"
    assert artifact["path"] == "notes.txt"
    assert artifact["content"] == diff
    assert artifact["metadata"]["action"] == "edit"


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


def test_runtime_projection_nests_forwarded_sub_agent_text_under_parent_call():
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
            "run_id": "run-1",
            "payload": {
                "turn_id": "turn-1",
                "part_id": "child-run:response-0:text",
                "part_type": "text",
                "content": "nested result",
                "sub_agent": {
                    "agent": "reviewer",
                    "session_id": "child-session-1",
                    "run_id": "child-run-1",
                    "parent_call_id": "call-sub-1",
                },
            }
        },
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert events is not None
    assert len(events) == 1
    assert events[0].kind == "message"
    assert events[0].payload == {"type": "agentMessage", "content": "nested result"}
    assert events[0].parent_item_id == "thread-1:run-1:call-sub-1:tool"
    assert events[0].metadata["sub_agent"] == {
        "agent": "reviewer",
        "session_id": "child-session-1",
        "run_id": "child-run-1",
        "parent_call_id": "call-sub-1",
    }


def test_forwarded_sub_agent_lifecycle_does_not_set_parent_turn_terminal():
    events = runtime_fact_to_run_item_events(
        thread_id="thread-1",
        event_id="child-done",
        group="system",
        source="sub_agent",
        phase="runtime.done",
        status="completed",
        sequence=10,
        preview="child finished",
        metadata={
            "run_id": "parent-run",
            "turn_id": "parent-turn",
            "payload": {
                "message": "child finished",
                "sub_agent": {
                    "agent": "qa",
                    "session_id": "thread-1:sub:qa",
                    "run_id": "child-run",
                    "parent_call_id": "call-sub-1",
                },
            },
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
    assert event.usage == {"total_tokens": 42}


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
        "cache_creation_tokens": 0,
        "cache_hit_rate": 0.4,
        "llm_calls": 1,
    }


def test_runtime_projection_maps_flattened_cached_tokens_from_llm_usage_to_dict():
    """The kernel emits ``LLMUsage.to_dict()`` which carries a flat
    ``cached_tokens`` key (no nested ``prompt_tokens_details``). The projection
    must still extract the cache count so the UI cache-hit-rate works."""
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
                    "prompt_tokens": 1000,
                    "completion_tokens": 50,
                    "total_tokens": 1050,
                    "cached_tokens": 950,
                },
            }
        },
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert events is not None
    assert len(events) == 1
    event = events[0]
    assert event.kind == "usage"
    assert event.usage["cached_tokens"] == 950
    assert event.usage["cache_hit_rate"] == 0.95


def test_runtime_projection_maps_deepseek_prompt_cache_hit_tokens():
    """DeepSeek usage reports cache reads as ``prompt_cache_hit_tokens``;
    the projection must count them so the UI cache-hit-rate works."""
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
                    "prompt_tokens": 1000,
                    "completion_tokens": 50,
                    "prompt_cache_hit_tokens": 800,
                    "prompt_cache_miss_tokens": 200,
                },
            }
        },
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert events is not None
    assert len(events) == 1
    event = events[0]
    assert event.kind == "usage"
    assert event.usage["cached_tokens"] == 800
    assert event.usage["cache_hit_rate"] == 0.8


def test_runtime_projection_maps_nested_deepseek_cache_hit_tokens():
    """Some OpenAI-compatible gateways (opencode zen included) fold DeepSeek's
    ``prompt_cache_hit_tokens`` into ``prompt_tokens_details`` — the projection
    must still count them."""
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
                    "prompt_tokens": 1000,
                    "completion_tokens": 50,
                    "prompt_tokens_details": {"prompt_cache_hit_tokens": 800},
                },
            }
        },
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert events is not None
    assert len(events) == 1
    event = events[0]
    assert event.kind == "usage"
    assert event.usage["cached_tokens"] == 800
    assert event.usage["cache_hit_rate"] == 0.8


def test_runtime_projection_maps_opencode_style_nested_cache_tokens():
    """opencode-style usage carries cache reads/writes under
    ``tokens.cache.read`` / ``tokens.cache.write``."""
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
                    "prompt_tokens": 1000,
                    "completion_tokens": 50,
                    "tokens": {
                        "input": 1000,
                        "output": 50,
                        "cache": {"read": 700, "write": 200},
                    },
                },
            }
        },
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert events is not None
    assert len(events) == 1
    event = events[0]
    assert event.kind == "usage"
    assert event.usage["cached_tokens"] == 700
    assert event.usage["cache_creation_tokens"] == 200
    assert event.usage["cache_hit_rate"] == 0.7


def test_runtime_projection_keeps_stream_terminal_usage_without_text():
    events = runtime_fact_to_run_item_events(
        thread_id="thread-1",
        event_id="event-usage",
        group="message",
        source="core",
        phase="runtime.reply_delta",
        status="completed",
        sequence=4,
        metadata={
            "payload": {
                "turn_id": "turn-1",
                "content": "",
                "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15},
            }
        },
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert events is not None
    assert len(events) == 1
    assert events[0].kind == "usage"
    assert events[0].usage["input_tokens"] == 12
    assert events[0].usage["output_tokens"] == 3


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
                "limit_tokens": 153600,
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
    assert run_items[0].payload["limit_tokens"] == 153600
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
