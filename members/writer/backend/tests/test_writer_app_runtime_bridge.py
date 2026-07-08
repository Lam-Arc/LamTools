from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.app_server.queue import accept_turn_start
from app.app_server.ledger import list_events_after
from app.app_server.runtime_bridge import (
    persist_run_item_events_as_app_events,
)
from app.app_server.snapshot import load_snapshot
from app.config import Settings
from app.database import Base
from app.models.message import WriterMessage
from app.models.app_server import WriterArtifact
from app.models.session import WriterSession
from app.models.transcript import WriterTranscriptTurn
import app.services.writer_service as writer_service_module
from app.services.writer_service import writer_orchestrate
from lamtools_core.event import RunItemEvent
from lamtools_core.event.runtime_projection import runtime_fact_to_run_item_events
from lamtools_core.kernel import KernelResult


def runtime_fact(event_id: str, phase: str, payload: dict, **overrides) -> dict:
    return {
        "thread_id": overrides.pop("session_id", "thread-1"),
        "event_id": event_id,
        "group": overrides.pop("group", "runtime"),
        "source": overrides.pop("source", "core"),
        "phase": phase,
        "status": overrides.pop("status", "running"),
        "sequence": overrides.pop("sequence", 1),
        "summary": overrides.pop("summary", ""),
        "preview": overrides.pop("preview", ""),
        "full_text": overrides.pop("full_text", ""),
        "metadata": {"payload": payload},
        "created_at": datetime.now(timezone.utc),
    }


def run_items_from_runtime_fact(fact: dict):
    return runtime_fact_to_run_item_events(**fact) or []


def _projection_inputs_from_runtime_fact(fact: dict):
    return []


async def persist_projection_from_runtime_fact(db, fact: dict):
    return await persist_run_item_events_as_app_events(db, run_items_from_runtime_fact(fact))


def test_reply_delta_maps_to_agent_message_delta():
    event = runtime_fact(
        "runtime-1",
        "runtime.reply_delta",
        {"turn_id": "turn-1", "part_id": "agent-1", "content": "hello"},
    )

    mapped = _projection_inputs_from_runtime_fact(event)
    run_items = run_items_from_runtime_fact(event)

    assert mapped == []
    assert len(run_items) == 1
    assert run_items[0].item_id == "agent-1"
    assert run_items[0].payload == {"type": "agentMessage", "delta": "hello"}


def test_runtime_fact_maps_to_core_run_item_before_app_projection():
    event = runtime_fact(
        "runtime-1",
        "runtime.reply_delta",
        {"turn_id": "turn-1", "part_id": "agent-1", "content": "hello"},
    )

    run_items = run_items_from_runtime_fact(event)

    assert run_items is not None
    assert len(run_items) == 1
    assert run_items[0].kind == "message"
    assert run_items[0].thread_id == "thread-1"
    assert run_items[0].turn_id == "turn-1"
    assert run_items[0].item_id == "agent-1"
    assert run_items[0].payload == {"type": "agentMessage", "delta": "hello"}
    assert _projection_inputs_from_runtime_fact(event) == []


def test_empty_reply_delta_does_not_render_summary_as_text():
    event = runtime_fact(
        "runtime-empty-delta",
        "runtime.reply_delta",
        {"turn_id": "turn-1", "content": ""},
        summary="整理过程说明。",
    )

    mapped = _projection_inputs_from_runtime_fact(event)

    assert mapped == []


def test_reply_delta_without_part_id_starts_stable_agent_message_item():
    event = runtime_fact(
        "runtime-1",
        "runtime.reply_delta",
        {"turn_id": "turn-1", "content": "hello"},
    )

    mapped = _projection_inputs_from_runtime_fact(event)
    run_items = run_items_from_runtime_fact(event)

    assert mapped == []
    assert len(run_items) == 1
    assert run_items[0].item_id
    assert run_items[0].payload == {"type": "agentMessage", "delta": "hello"}


def test_tool_started_and_finished_map_to_item_lifecycle():
    started = runtime_fact(
        "runtime-tool-start",
        "runtime.tool.started",
        {"turn_id": "turn-1", "tool_call_id": "call-1", "tool_name": "shell", "arguments": {"cmd": "pwd"}},
    )
    finished = runtime_fact(
        "runtime-tool-finish",
        "runtime.tool.finished",
        {"turn_id": "turn-1", "tool_call_id": "call-1", "tool_name": "shell"},
        status="ok",
        preview="E:/LamTools",
    )

    mapped = _projection_inputs_from_runtime_fact(started) + _projection_inputs_from_runtime_fact(finished)
    run_items = run_items_from_runtime_fact(started) + run_items_from_runtime_fact(finished)

    assert mapped == []
    assert [item.kind for item in run_items] == ["tool_call", "tool_result"]
    assert run_items[0].payload["type"] == "dynamicToolCall"
    assert run_items[0].payload["tool_name"] == "shell"
    assert run_items[0].payload["arguments"] == {"cmd": "pwd"}


def test_empty_tool_call_id_uses_stable_item_id_across_lifecycle():
    started = runtime_fact(
        "runtime-empty-tool-start",
        "runtime.tool.started",
        {"turn_id": "turn-1", "tool_name": "", "arguments": {}, "response_index": 2},
        sequence=10,
    )
    finished = runtime_fact(
        "runtime-empty-tool-finish",
        "runtime.tool.finished",
        {"turn_id": "turn-1", "tool_name": "", "response_index": 2},
        status="failed",
        sequence=11,
        preview="工具调用格式无效",
    )

    mapped = _projection_inputs_from_runtime_fact(started) + _projection_inputs_from_runtime_fact(finished)
    run_items = run_items_from_runtime_fact(started) + run_items_from_runtime_fact(finished)

    assert mapped == []
    assert [item.kind for item in run_items] == ["tool_call", "tool_result"]
    assert run_items[0].payload["tool_name"] == "invalid_tool_call"


def test_runtime_tool_part_is_not_projected_as_a_second_process_item():
    event = runtime_fact(
        "runtime-tool-part",
        "runtime.part",
        {
            "turn_id": "turn-1",
            "part_id": "part-functions.write_file:0",
            "part_type": "tool_call",
            "status": "completed",
            "tool_name": "write_file",
            "tool_result": "Created notes.md",
        },
        status="completed",
        summary="runtime.part",
    )

    mapped = _projection_inputs_from_runtime_fact(event)

    assert mapped == []


def test_running_runtime_tool_part_projects_as_tool_started_item():
    event = runtime_fact(
        "runtime-tool-draft",
        "runtime.part",
        {
            "turn_id": "turn-1",
            "part_id": "run-1:response-0:tool-call-0",
            "part_type": "tool_call",
            "status": "running",
            "tool_name": "write_file",
            "call_id": "functions.write_file:0",
            "tool_args": {
                "path": "blog/index.html",
                "content": {"chars": 5758, "preview": "<!DOCTYPE html>"},
            },
            "content": "准备调用 write_file",
            "detail": "path: blog/index.html; content: 5758 chars",
        },
        status="running",
        summary="runtime.part",
    )

    mapped = _projection_inputs_from_runtime_fact(event)
    run_items = run_items_from_runtime_fact(event)

    assert mapped == []
    assert len(run_items) == 1
    assert run_items[0].kind == "tool_call"
    assert run_items[0].item_id == "thread-1:turn-1:functions.write_file:0:tool"
    assert run_items[0].payload["type"] == "dynamicToolCall"
    assert run_items[0].payload["tool_name"] == "write_file"
    assert run_items[0].payload["arguments"]["path"] == "blog/index.html"
    assert run_items[0].payload["arguments"]["content"] == {"chars": 5758, "preview": "<!DOCTYPE html>"}
    assert run_items[0].payload["message"] == "path: blog/index.html; content: 5758 chars"


def test_runtime_part_without_visible_content_is_not_projected():
    event = runtime_fact(
        "runtime-empty-part",
        "runtime.part",
        {
            "turn_id": "turn-1",
            "part_id": "empty-part",
            "part_type": "text",
        },
        status="running",
        summary="runtime.part",
        preview="runtime.part",
    )

    mapped = _projection_inputs_from_runtime_fact(event)

    assert mapped == []


def test_completed_runtime_part_uses_full_preview_when_payload_content_is_truncated():
    full = "完整回复" + "。" * 1800
    event = runtime_fact(
        "runtime-final-part",
        "runtime.part",
        {
            "turn_id": "turn-1",
            "part_id": "final-1",
            "part_type": "text",
            "status": "completed",
            "content": full[:1200],
        },
        status="completed",
        preview=full,
    )

    mapped = _projection_inputs_from_runtime_fact(event)
    run_items = run_items_from_runtime_fact(event)

    assert mapped == []
    assert len(run_items) == 1
    assert run_items[0].payload["content"] == full


def test_runtime_done_uses_full_preview_for_completed_turn_message():
    full = "最终回复" + "。" * 1800
    event = runtime_fact(
        "runtime-done",
        "runtime.done",
        {"turn_id": "turn-1"},
        status="completed",
        summary=full[:1200],
        preview=full,
    )

    mapped = _projection_inputs_from_runtime_fact(event)
    run_items = run_items_from_runtime_fact(event)

    assert mapped == []
    assert len(run_items) == 1
    assert run_items[0].kind == "status"
    assert run_items[0].status == "completed"
    assert run_items[0].payload["message"] == full


def test_runtime_usage_maps_to_turn_metrics():
    event = runtime_fact(
        "runtime-usage",
        "runtime.usage",
        {
            "turn_id": "turn-1",
            "usage": {
                "prompt_tokens": 120,
                "completion_tokens": 45,
                "total_tokens": 165,
                "prompt_tokens_details": {"cached_tokens": 60},
            },
        },
    )

    mapped = _projection_inputs_from_runtime_fact(event)

    run_items = run_items_from_runtime_fact(event)

    assert mapped == []
    assert len(run_items) == 1
    assert run_items[0].kind == "usage"
    assert run_items[0].usage == {
        "input_tokens": 120,
        "output_tokens": 45,
        "total_tokens": 165,
        "cached_tokens": 60,
        "cache_hit_rate": 0.5,
        "llm_calls": 1,
    }


def test_runtime_metrics_maps_to_replacing_turn_metrics():
    event = runtime_fact(
        "runtime-metrics",
        "runtime.metrics",
        {
            "turn_id": "turn-1",
            "runtime_metrics": {
                "duration_ms": 12_300,
                "input_tokens": 120,
                "output_tokens": 45,
                "total_tokens": 165,
                "cache_hit_rate": 0.5,
                "llm_calls": 2,
            },
        },
    )

    mapped = _projection_inputs_from_runtime_fact(event)

    run_items = run_items_from_runtime_fact(event)

    assert mapped == []
    assert len(run_items) == 1
    assert run_items[0].kind == "usage"
    assert run_items[0].payload["replace"] is True
    assert run_items[0].usage["duration_ms"] == 12_300


def test_approval_maps_to_core_request():
    event = runtime_fact(
        "runtime-approval",
        "runtime.approval_request",
        {
            "turn_id": "turn-1",
            "tool_call_id": "call-1",
            "tool_name": "shell",
            "request_id": "request-1",
            "message": "Allow command?",
            "options": [{"id": "approve_once"}],
        },
    )

    mapped = _projection_inputs_from_runtime_fact(event)
    run_items = run_items_from_runtime_fact(event)

    assert mapped == []
    assert len(run_items) == 1
    assert run_items[0].kind == "approval_request"
    assert run_items[0].payload["request_id"] == "request-1"
    assert run_items[0].payload["message"] == "Allow command?"
    assert run_items[0].payload["options"] == [{"id": "approve_once"}]


def test_approval_without_options_uses_standard_decisions():
    event = runtime_fact(
        "runtime-approval",
        "runtime.approval_request",
        {
            "turn_id": "turn-1",
            "tool_call_id": "call-1",
            "tool_name": "shell",
            "request_id": "request-1",
            "message": "Allow command?",
        },
    )

    mapped = _projection_inputs_from_runtime_fact(event)
    run_items = run_items_from_runtime_fact(event)

    assert mapped == []
    assert len(run_items) == 1
    assert run_items[0].kind == "approval_request"
    option_ids = [item["id"] for item in run_items[0].payload["options"]]
    assert option_ids == ["approve", "deny"]


def test_permission_waiting_does_not_duplicate_approval_request():
    event = runtime_fact(
        "runtime-waiting",
        "runtime.waiting",
        {
            "turn_id": "turn-1",
            "tool_call_id": "call-1",
            "tool_name": "shell",
            "request_kind": "permission",
            "message": "Allow command?",
        },
    )

    mapped = _projection_inputs_from_runtime_fact(event)

    assert mapped == []


@pytest.mark.asyncio
async def test_run_item_events_are_the_primary_app_projection_input(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'run-item-projection.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        async with session_factory() as db:
            envelopes = await persist_run_item_events_as_app_events(
                db,
                [
                    RunItemEvent(
                        kind="message",
                        thread_id="thread-1",
                        event_id="run-item-1",
                        turn_id="turn-1",
                        item_id="agent-1",
                        payload={"type": "agentMessage", "delta": "hello"},
                    )
                ],
            )
            await db.commit()

            snapshot = await load_snapshot(db, "thread-1")

            assert [item.method for item in envelopes] == ["core/runItem"]
            assert snapshot["items"] == {}
            assert snapshot["core"]["items"]["agent-1"]["content"] == "hello"
            assert snapshot["core"]["turns"]["turn-1"]["items"] == ["agent-1"]
    finally:
        await engine.dispose()

@pytest.mark.asyncio
async def test_runtime_bridge_persists_events_and_updates_snapshot(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'bridge.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        async with session_factory() as db:
            event = runtime_fact(
                "runtime-1",
                "runtime.tool.started",
                {"turn_id": "turn-1", "tool_call_id": "call-1", "tool_name": "shell"},
            )
            envelopes = await persist_projection_from_runtime_fact(db, event)
            await db.commit()

            snapshot = await load_snapshot(db, "thread-1")
            assert [item.method for item in envelopes] == ["core/runItem"]
            assert snapshot["items"] == {}
            assert snapshot["core"]["items"]["thread-1:turn-1:call-1:tool"]["payload"]["tool_name"] == "shell"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_runtime_bridge_persists_tool_artifacts_as_core_facts(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'bridge-artifact.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        async with session_factory() as db:
            artifact_path = tmp_path / "report.md"
            event = runtime_fact(
                "runtime-tool-artifact",
                "runtime.tool.finished",
                {
                    "turn_id": "turn-1",
                    "tool_call_id": "write-1",
                    "tool_name": "write_file",
                    "artifacts": [
                        {
                            "artifact_type": "file_create",
                            "path": str(artifact_path),
                            "description": "Created report",
                            "metadata": {"source": "test"},
                        }
                    ],
                },
                status="ok",
                preview="Created report.md",
            )
            envelopes = await persist_projection_from_runtime_fact(db, event)
            await db.commit()

            snapshot = await load_snapshot(db, "thread-1")
            artifact_id = next(iter(snapshot["core"]["artifacts"]))
            artifact = await db.get(WriterArtifact, artifact_id)

            assert [item.method for item in envelopes] == ["core/runItem"]
            assert artifact is not None
            assert artifact.thread_id == "thread-1"
            assert artifact.path == str(artifact_path)
            assert snapshot["items"] == {}
            assert snapshot["artifacts"] == {}
            assert snapshot["core"]["artifacts"][artifact.artifact_id]["path"] == str(artifact_path)
            assert snapshot["core"]["items"]["thread-1:turn-1:write-1:tool"]["content"] == "Created report.md"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_runtime_bridge_persists_explicit_artifact_as_core_fact(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'bridge-explicit-artifact.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        async with session_factory() as db:
            artifact_path = tmp_path / "notes.md"
            event = RunItemEvent(
                kind="artifact",
                thread_id="thread-1",
                event_id="artifact-event-1",
                turn_id="turn-1",
                item_id="artifact-item-1",
                status="completed",
                payload={
                    "artifact_id": "artifact-1",
                    "kind": "file_create",
                    "name": "notes.md",
                    "path": str(artifact_path),
                    "metadata": {"source": "explicit"},
                },
            )
            envelopes = await persist_run_item_events_as_app_events(db, [event])
            await db.commit()

            snapshot = await load_snapshot(db, "thread-1")
            artifact = await db.get(WriterArtifact, "artifact-1")

            assert [item.method for item in envelopes] == ["core/runItem"]
            assert artifact is not None
            assert artifact.path == str(artifact_path)
            assert snapshot["artifacts"] == {}
            assert snapshot["core"]["artifacts"]["artifact-1"]["path"] == str(artifact_path)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_runtime_bridge_persists_error_as_core_fact(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'bridge-error.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        async with session_factory() as db:
            event = RunItemEvent(
                kind="error",
                thread_id="thread-1",
                event_id="error-event-1",
                turn_id="turn-1",
                item_id="error-item-1",
                status="failed",
                payload={"type": "runtime", "message": "model transport closed"},
            )
            envelopes = await persist_run_item_events_as_app_events(db, [event])
            await db.commit()

            snapshot = await load_snapshot(db, "thread-1")

            assert [item.method for item in envelopes] == ["core/runItem"]
            assert "last_error" not in snapshot
            assert snapshot["items"] == {}
            assert snapshot["core"]["status"] == "failed"
            assert snapshot["core"]["last_error"]["message"] == "model transport closed"
            assert snapshot["core"]["items"]["error-item-1"]["status"] == "failed"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_runtime_bridge_persists_usage_as_core_facts(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'bridge-usage.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        async with session_factory() as db:
            usage = runtime_fact(
                "runtime-usage",
                "runtime.usage",
                {
                    "turn_id": "turn-1",
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 3,
                        "total_tokens": 13,
                    },
                },
            )
            metrics = runtime_fact(
                "runtime-metrics",
                "runtime.metrics",
                {
                    "turn_id": "turn-1",
                    "runtime_metrics": {
                        "duration_ms": 12_300,
                        "input_tokens": 12,
                        "output_tokens": 4,
                        "total_tokens": 16,
                    },
                },
                sequence=2,
            )

            usage_envelopes = await persist_projection_from_runtime_fact(db, usage)
            metric_envelopes = await persist_projection_from_runtime_fact(db, metrics)
            await db.commit()

            snapshot = await load_snapshot(db, "thread-1")

            assert [item.method for item in usage_envelopes + metric_envelopes] == ["core/runItem", "core/runItem"]
            assert snapshot["turns"] == {}
            assert snapshot["core"]["turns"]["turn-1"]["usage"] == {
                "duration_ms": 12_300,
                "input_tokens": 12,
                "output_tokens": 4,
                "total_tokens": 16,
            }
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_runtime_bridge_persists_status_as_core_fact(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'bridge-status.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        async with session_factory() as db:
            event = runtime_fact(
                "runtime-done",
                "runtime.done",
                {"turn_id": "turn-1", "decision": "done"},
                status="completed",
                summary="short",
                preview="complete answer",
            )
            envelopes = await persist_projection_from_runtime_fact(db, event)
            await db.commit()

            snapshot = await load_snapshot(db, "thread-1")

            assert [item.method for item in envelopes] == ["core/runItem"]
            assert snapshot["status"] == "completed"
            assert snapshot["turns"] == {}
            assert snapshot["core"]["status"] == "completed"
            assert snapshot["core"]["turns"]["turn-1"]["status"] == "completed"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_runtime_part_growth_appends_new_events_instead_of_deduping_same_runtime_id(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'part-growth.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        async with session_factory() as db:
            event = runtime_fact(
                "runtime-part-1",
                "runtime.part",
                {"turn_id": "turn-1", "part_id": "reasoning-1", "part_type": "reasoning", "content": "用"},
                status="running",
            )
            await persist_projection_from_runtime_fact(db, event)

            event["full_text"] = "用户提供的视频里，思考块不应该只剩两个字。"
            event["metadata"] = {
                "payload": {
                    "turn_id": "turn-1",
                    "part_id": "reasoning-1",
                    "part_type": "reasoning",
                    "content": "用户提供的视频里，思考块不应该只剩两个字。",
                }
            }
            await persist_projection_from_runtime_fact(db, event)
            await db.commit()

            replay = await list_events_after(db, thread_id="thread-1")
            snapshot = await load_snapshot(db, "thread-1")

            assert [item.method for item in replay] == ["core/runItem", "core/runItem"]
            assert replay[0].event_id != replay[1].event_id
            assert replay[0].item_id == replay[1].item_id == "reasoning-1"
            assert snapshot["items"] == {}
            assert snapshot["core"]["items"]["reasoning-1"]["content"] == "用户提供的视频里，思考块不应该只剩两个字。"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_tool_input_delta_growth_appends_new_events_instead_of_deduping_same_runtime_id(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'tool-input-growth.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        async with session_factory() as db:
            event = runtime_fact(
                "runtime-tool-input-1",
                "runtime.part",
                {
                    "turn_id": "turn-1",
                    "part_id": "run-1:response-0:tool-call-0:input",
                    "part_type": "tool_input_delta",
                    "tool_name": "write_file",
                    "call_id": "write-1",
                    "arguments_text": '{"path":"README.md","content":"#',
                },
                status="running",
            )
            await persist_projection_from_runtime_fact(db, event)

            event["metadata"] = {
                "payload": {
                    "turn_id": "turn-1",
                    "part_id": "run-1:response-0:tool-call-0:input",
                    "part_type": "tool_input_delta",
                    "tool_name": "write_file",
                    "call_id": "write-1",
                    "arguments_text": '{"path":"README.md","content":"# Title',
                }
            }
            await persist_projection_from_runtime_fact(db, event)
            await db.commit()

            replay = await list_events_after(db, thread_id="thread-1")
            snapshot = await load_snapshot(db, "thread-1")

            assert [item.method for item in replay] == ["core/runItem", "core/runItem"]
            assert replay[0].event_id != replay[1].event_id
            assert replay[0].item_id == replay[1].item_id == "thread-1:turn-1:write-1:tool"
            assert snapshot["items"] == {}
            assert snapshot["core"]["items"]["thread-1:turn-1:write-1:tool"]["payload"]["input_preview"]["content"] == "# Title"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_agent_message_delta_is_not_orphaned(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'agent-started.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        async with session_factory() as db:
            event = runtime_fact(
                "runtime-delta-1",
                "runtime.reply_delta",
                {"turn_id": "turn-1", "content": "hello"},
                sequence=7,
            )
            await persist_projection_from_runtime_fact(db, event)
            await db.commit()

            replay = await list_events_after(db, thread_id="thread-1")
            snapshot = await load_snapshot(db, "thread-1")

            assert [item.method for item in replay] == ["core/runItem"]
            assert snapshot["items"] == {}
            assert snapshot["core"]["items"][replay[0].item_id]["content"] == "hello"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_writer_service_reuses_app_server_message_and_turn(monkeypatch, tmp_path):
    async def _fake_resolve_llm_config(db, route=None, model_id=None):
        return {"provider": "test", "model": "test-model"}

    def _fake_build_llm_client(resolved, thinking_enabled=None, thinking_budget=None):
        return object()

    async def _fake_run_core_kernel(**kwargs):
        return KernelResult(
            session_id=kwargs["session_id"],
            run_id="run-app-server-bridge",
            decision="done",
            message="done",
            metadata={"core_events": [], "steps_count": 0},
        )

    monkeypatch.setattr(writer_service_module, "resolve_llm_config", _fake_resolve_llm_config)
    monkeypatch.setattr(writer_service_module, "build_llm_client", _fake_build_llm_client)
    monkeypatch.setattr(writer_service_module, "run_core_kernel", _fake_run_core_kernel)

    settings = Settings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'service-reuse.db'}",
        llm_api_key="test",
    )
    engine = create_async_engine(settings.database_url, future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        services = writer_orchestrate(settings)
        async with session_factory() as db:
            db.add(WriterSession(id="thread-1", title="Test", work_root=str(tmp_path / "workspace")))
            await db.commit()

            events = await accept_turn_start(
                db,
                thread_id="thread-1",
                client_message_id="client-1",
                input_items=[{"type": "text", "text": "hello"}],
            )
            await db.commit()
            turn_id = events[0].turn_id
            user_message_id = events[0].payload["user_message_id"]

            await services["run_turn"](
                db=db,
                session_id="thread-1",
                user_message="hello",
                user_message_id=user_message_id,
                transcript_turn_id=turn_id,
            )

            user_count = (
                await db.execute(
                    select(func.count())
                    .select_from(WriterMessage)
                    .where(WriterMessage.session_id == "thread-1", WriterMessage.role == "user")
                )
            ).scalar_one()
            turn_count = (
                await db.execute(
                    select(func.count())
                    .select_from(WriterTranscriptTurn)
                    .where(WriterTranscriptTurn.session_id == "thread-1")
                )
            ).scalar_one()
            turn = await db.get(WriterTranscriptTurn, turn_id)

            assert user_count == 1
            assert turn_count == 1
            assert turn is not None
            assert turn.user_message_id == user_message_id
    finally:
        await engine.dispose()
