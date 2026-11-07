"""Guidance consumption is a durable event fact, not a property of history rows.

Reported 2026-11-01: after a pause, every historical steering message was sent
to the model again in one round. The pause writes the compaction *view* back as
a full history replace, so receipt rows (``metadata.guidance_ids``) that lived
in the compacted prefix disappear; ``pending_steering`` could no longer tell
they had been consumed. These tests pin the replacement contract: consumption
is recorded in the app event log and survives any history rewrite.
"""
from __future__ import annotations

import asyncio

import pytest

from lamtools_core.app import CoreAgentPaths, CoreAgentSpec, create_core_agent_operations, open_core_app_db
from lamtools_core.app.event_store import AppEventInput
from lamtools_core.app.live_hub import CoreAppEventHub
from lamtools_core.app.live_operations import (
    CoreLiveContext,
    handle_turn_pause_operation,
    handle_turn_resume_operation,
    handle_turn_start_operation,
    handle_turn_steer_operation,
    wait_live_background_tasks,
)
from lamtools_core.app.steering import GUIDANCE_CONSUMED_METHOD, pending_steering, record_consumed_guidance
from lamtools_core.event import RunItemEvent
from lamtools_core.kernel import CoreLoopKernel
from lamtools_core.llm import LLMStreamEvent, LLMToolCall
from lamtools_core.runtime import RuntimeState, RuntimeTaskRegistry
from lamtools_core.tool import ToolResult


async def context_for(db, tmp_path, model):
    registry = RuntimeTaskRegistry()
    hub = CoreAppEventHub()
    operations = create_core_agent_operations(
        spec=CoreAgentSpec(default_model="fixture"),
        paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=tmp_path), model_provider=model,
        runtime_state_store=db.runtime_state_store, runtime_task_registry=registry,
        db_session_factory=db.session_factory, app_event_store=db.event_store,
        thread_snapshot_store=db.snapshot_store, app_event_hub=hub,
        write_coordinator=db.persistence.write_coordinator,
    )
    return CoreLiveContext(session_factory=db.session_factory, persistence=db.persistence,
        operations=operations, hub=hub, runtime_task_registry=registry,
        runtime_state_store=db.runtime_state_store)


def _model_dir(tmp_path):
    models = tmp_path / ".lam" / "config" / "models"
    models.mkdir(parents=True)
    (models / "fixture.jsonc").write_text('{"model_id":"fixture","capability":"text"}', encoding="utf-8")


async def _finish_turn(db, thread_id: str, turn_id: str) -> None:
    async def write(session):
        await db.persistence.append_run_item(session, RunItemEvent(
            kind="status", thread_id=thread_id, turn_id=turn_id, run_id=turn_id,
            event_id=f"{turn_id}:done", item_id=f"{turn_id}:done", status="completed",
            payload={"type": "turn", "status": "completed"},
        ))
    await db.persistence.write(write)


async def _append_steered(db, thread_id: str, guidance_id: str, text: str, *, turn_id: str = "t1") -> None:
    async def write(session):
        await db.persistence.append(session, AppEventInput(
            thread_id=thread_id, turn_id=turn_id, method="turn/steered",
            client_message_id=guidance_id,
            payload={"type": "turn", "guidance_id": guidance_id,
                     "input": [{"type": "text", "text": text}],
                     "runtime_input": [{"type": "text", "text": text}]},
        ))
    await db.persistence.write(write)


@pytest.mark.asyncio
async def test_pending_steering_uses_the_durable_consumption_fact(tmp_path):
    db = await open_core_app_db(tmp_path / "core.db")
    try:
        await _append_steered(db, "thread", "g1", "CONSUMED_ONE")
        await _append_steered(db, "thread", "g2", "STILL_PENDING")
        await record_consumed_guidance(
            db.session_factory, thread_id="thread", turn_id="t1", guidance_ids=["g1"],
            event_store=db.event_store, write_coordinator=db.persistence.write_coordinator,
        )
        assert [item["id"] for item in await pending_steering(db.session_factory, "thread")] == ["g2"]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_legacy_history_receipts_are_backfilled_before_a_rewrite(tmp_path):
    db = await open_core_app_db(tmp_path / "core.db")
    try:
        await _append_steered(db, "thread", "g1", "CONSUMED_ONE")
        await _append_steered(db, "thread", "g2", "STILL_PENDING")
        await db.runtime_state_store.append_history("thread", [
            {"role": "user", "content": "CONSUMED_ONE", "metadata": {"guidance_ids": ["g1"]}},
        ])
        pending = await pending_steering(
            db.session_factory, "thread",
            event_store=db.event_store, write_coordinator=db.persistence.write_coordinator,
        )
        assert [item["id"] for item in pending] == ["g2"]
        async with db.session_factory() as session:
            events = await db.persistence.list_after(session, thread_id="thread", after_seq=0)
        markers = [event for event in events if event.method == GUIDANCE_CONSUMED_METHOD]
        assert "g1" in [gid for event in markers for gid in event.payload.get("guidance_ids") or []]

        # A later pause settles by replacing history with its compaction view.
        await db.runtime_state_store.replace_history("thread", [])
        assert [item["id"] for item in await pending_steering(db.session_factory, "thread")] == ["g2"]
    finally:
        await db.close()


class LiveModel:
    """First call asks for a tool, so accepted steering is consumed at a step boundary."""
    def __init__(self) -> None:
        self.requests = []
        self.started = asyncio.Event()

    async def complete(self, request):
        raise AssertionError("scripted stream only")

    async def stream(self, request):
        self.requests.append(request)
        self.started.set()
        if len(self.requests) == 1:
            yield LLMStreamEvent(kind="done", tool_calls=[
                LLMToolCall(id="step-1", name="list_dir", arguments={"path": "."}),
            ])
            return
        yield LLMStreamEvent(kind="content_delta", content="finished")
        yield LLMStreamEvent(kind="done")


@pytest.mark.asyncio
async def test_live_ack_writes_the_durable_consumption_fact(tmp_path, monkeypatch):
    _model_dir(tmp_path)
    model = LiveModel()
    async def tool(self, state, call, **kwargs):
        return ToolResult(call_id=call.id, name=call.name, status="ok", content="ok")
    monkeypatch.setattr(CoreLoopKernel, "_execute_tool", tool)
    db = await open_core_app_db(tmp_path / "core.db")
    context = await context_for(db, tmp_path, model)
    try:
        accepted = await handle_turn_start_operation(request_id=1, params={
            "thread_id": "thread", "input": [{"type": "text", "text": "task"}],
            "model_id": "fixture", "permission_preset": "full_access", "include_snapshot": False,
        }, context=context)
        turn_id = accepted.runtime_start["turn_id"]
        await asyncio.wait_for(model.started.wait(), 10)
        steered = await handle_turn_steer_operation(request_id=2, params={
            "thread_id": "thread", "turn_id": turn_id, "client_message_id": "g-live",
            "input": [{"type": "text", "text": "LIVE_GUIDANCE"}], "include_snapshot": False,
        }, context=context)
        assert steered.response["result"]["applied"] is True
        task = context.runtime_task_registry.task("thread")
        await asyncio.wait_for(task, 10)
        await wait_live_background_tasks()
        async with db.session_factory() as session:
            events = await db.persistence.list_after(session, thread_id="thread", after_seq=0)
        consumed = [event for event in events if event.method == GUIDANCE_CONSUMED_METHOD]
        assert consumed, "a checkpointed acknowledgement must leave a durable consumption event"
        assert "g-live" in [gid for event in consumed for gid in event.payload.get("guidance_ids") or []]
        assert await pending_steering(db.session_factory, "thread") == []
        history = await db.runtime_state_store.get_history("thread")
        assert "LIVE_GUIDANCE" in str(history)
    finally:
        context.runtime_task_registry.clear()
        await wait_live_background_tasks()
        await db.close()


class ImmediateModel:
    def __init__(self) -> None:
        self.requests = []

    async def complete(self, request):
        raise AssertionError("scripted stream only")

    async def stream(self, request):
        self.requests.append(request)
        yield LLMStreamEvent(kind="content_delta", content="ok")
        yield LLMStreamEvent(kind="done")


@pytest.mark.asyncio
async def test_recovery_prefix_ack_writes_the_consumption_fact(tmp_path):
    """Uncheckpointed steering folded into the next user message is consumed there."""
    _model_dir(tmp_path)
    model = ImmediateModel()
    db = await open_core_app_db(tmp_path / "core.db")
    context = await context_for(db, tmp_path, model)
    try:
        await _append_steered(db, "thread", "g-recovered", "RECOVERED_ONCE")
        await _finish_turn(db, "thread", "t1")
        accepted = await handle_turn_start_operation(request_id=1, params={
            "thread_id": "thread", "input": [{"type": "text", "text": "NEXT_TASK"}],
            "model_id": "fixture", "permission_preset": "full_access", "include_snapshot": False,
        }, context=context)
        assert "error" not in accepted.response, accepted.response
        task = context.runtime_task_registry.task("thread")
        if task:
            await asyncio.wait_for(task, 10)
        await wait_live_background_tasks()
        assert "Previously accepted steering not yet checkpointed" in str(model.requests[0].messages)
        assert await pending_steering(db.session_factory, "thread") == []
        async with db.session_factory() as session:
            events = await db.persistence.list_after(session, thread_id="thread", after_seq=0)
        consumed = [event for event in events if event.method == GUIDANCE_CONSUMED_METHOD]
        assert "g-recovered" in [gid for event in consumed for gid in event.payload.get("guidance_ids") or []]
    finally:
        context.runtime_task_registry.clear()
        await wait_live_background_tasks()
        await db.close()


class BlockingModel:
    def __init__(self) -> None:
        self.requests = []
        self.entered = asyncio.Event()

    async def complete(self, request):
        raise AssertionError("scripted stream only")

    async def stream(self, request):
        self.requests.append(request)
        self.entered.set()
        await asyncio.Event().wait()
        yield LLMStreamEvent(kind="content_delta", content="never")
        yield LLMStreamEvent(kind="done")


@pytest.mark.asyncio
async def test_pause_after_compaction_does_not_replay_consumed_guidance(tmp_path):
    _model_dir(tmp_path)
    model = BlockingModel()
    db = await open_core_app_db(tmp_path / "core.db")
    context = await context_for(db, tmp_path, model)
    thread_id = "thread"
    try:
        # An older completed turn whose guidance receipts sit in the compacted
        # prefix, plus one accepted steer that was never checkpointed.
        await db.runtime_state_store.append_history(thread_id, [
            {"role": "user", "content": "ORIGINAL_TASK", "metadata": {"turn_id": "t1"}},
            {"role": "assistant", "content": "worked", "metadata": {}},
            {"role": "user", "content": "GUIDE_OLD", "metadata": {"guidance_ids": ["g-old"]}},
            {"role": "assistant", "content": "step", "metadata": {}},
            {"role": "user", "content": "GUIDE_OLD_2", "metadata": {"guidance_ids": ["g-old-2"]}},
            {"role": "assistant", "content": "done", "metadata": {}},
        ])
        await _append_steered(db, thread_id, "g-old", "GUIDE_OLD")
        await _append_steered(db, thread_id, "g-old-2", "GUIDE_OLD_2")
        await _finish_turn(db, thread_id, "t1")
        await record_consumed_guidance(
            db.session_factory, thread_id=thread_id, turn_id="t1",
            guidance_ids=["g-old", "g-old-2"],
            event_store=db.event_store, write_coordinator=db.persistence.write_coordinator,
        )
        state = await db.runtime_state_store.get(thread_id) or RuntimeState(session_id=thread_id)
        state.run_id = "t1"
        state.status = "completed"
        state.loop_state = "done"
        state.metadata["turn_id"] = "t1"
        state.metadata["context_compaction"] = {
            "summary": "SUMMARY_OF_OLD_TURN",
            "summary_seq": 2,
            "compacted_history_seqs": [3, 5],
        }
        await db.runtime_state_store.save(state)

        accepted = await handle_turn_start_operation(request_id=1, params={
            "thread_id": thread_id, "input": [{"type": "text", "text": "NEW_TASK"}],
            "model_id": "fixture", "permission_preset": "full_access", "include_snapshot": False,
        }, context=context)
        turn_id = accepted.runtime_start["turn_id"]
        await asyncio.wait_for(model.entered.wait(), 10)
        model.entered.clear()
        # Accepted while the model call is in flight: no step boundary has
        # checkpointed it yet, so this one is genuinely undelivered.
        steered = await handle_turn_steer_operation(request_id=2, params={
            "thread_id": thread_id, "turn_id": turn_id, "client_message_id": "g-pending",
            "input": [{"type": "text", "text": "PENDING_ONCE"}], "include_snapshot": False,
        }, context=context)
        assert steered.response["result"]["applied"] is True
        await handle_turn_pause_operation(
            request_id=3, params={"thread_id": thread_id, "turn_id": turn_id}, context=context
        )
        await wait_live_background_tasks()

        # The pause may drop the receipt rows, but consumption is still a fact.
        assert [item["id"] for item in await pending_steering(db.session_factory, thread_id)] == ["g-pending"]

        resumed = await handle_turn_resume_operation(
            request_id=4, params={"thread_id": thread_id, "turn_id": turn_id}, context=context
        )
        assert "error" not in resumed.response, resumed.response
        await asyncio.wait_for(model.entered.wait(), 10)
        resumed_request = model.requests[-1]
        messages = [str(message.content) for message in resumed_request.messages]
        assert not any("GUIDE_OLD" in content for content in messages), "consumed guidance must not be replayed"
        assert sum(content.count("PENDING_ONCE") for content in messages) == 1, "only genuinely pending guidance is recovered"
    finally:
        if context.runtime_task_registry.task(thread_id):
            await handle_turn_pause_operation(
                request_id=4, params={"thread_id": thread_id}, context=context
            )
        context.runtime_task_registry.clear()
        await wait_live_background_tasks()
        await db.close()
