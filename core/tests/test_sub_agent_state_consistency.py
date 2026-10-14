"""Deterministic delivery/recovery regressions; no provider or app process needed."""
from __future__ import annotations

import asyncio
import sqlite3
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from lamtools_core.app import CoreAgentPaths, CoreAgentSpec, create_core_agent_operations, open_core_app_db
from lamtools_core.app.core_db import CoreAppEvent
from lamtools_core.app.live_hub import CoreAppEventHub
from lamtools_core.app.live_operations import CoreLiveContext
from lamtools_core.app.operation_catalog import OperationCatalog
from lamtools_core.app.sub_agent_recovery import reconcile_sub_agent_state
from lamtools_core.event import CollectingEventSink
from lamtools_core.kernel import CoreLoopKernel
from lamtools_core.llm import LLMStreamEvent
from lamtools_core.runtime import InMemoryRuntimeStateStore, RuntimeState, RuntimeTurnInput
from lamtools_core.runtime_owner import owner_token
from lamtools_core.agent import SubAgentRunResult
from lamtools_core.sub_agent_supervisor import SubAgentRecord, SubAgentSupervisor, peek_member_events
from lamtools_core.tool.sub_agent_runner import KernelSubAgentRunner


class BoundaryLLM:
    def __init__(self):
        self.requests = []
        self.sampling = asyncio.Event()
        self.release = asyncio.Event()

    async def complete(self, _request):
        raise AssertionError("no external completion")

    async def stream(self, request):
        self.requests.append(request)
        if len(self.requests) == 1:
            self.sampling.set()
            await self.release.wait()
        yield LLMStreamEvent(kind="content_delta", content="answer")
        yield LLMStreamEvent(kind="done")


def seed_model(root):
    directory = root / ".lam" / "config" / "models"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "fixture.jsonc").write_text('{"model_id":"fixture","capability":"text"}', encoding="utf-8")


@pytest.mark.asyncio
async def test_running_child_guidance_reaches_same_run_and_receipt_follows_history(tmp_path):
    seed_model(tmp_path)
    llm = BoundaryLLM()
    store = InMemoryRuntimeStateStore()
    runner = KernelSubAgentRunner(work_root=tmp_path, llm_client=llm, model_id="fixture",
                                  session_prefix="parent", state_store=store)
    supervisor = SubAgentSupervisor(parent_thread_id="parent", runner=runner, database_path=tmp_path / "members.db")
    await supervisor.create(type="execute", name="worker", model="fixture", reasoning_level="high")
    await supervisor.message(type="execute", name="worker", prompt="initial")
    task = supervisor._tasks["worker"]
    await asyncio.wait_for(llm.sampling.wait(), 2)
    await supervisor.message(type="execute", name="worker", prompt="changed instructions",
                             source_ids={"run_id": "parent-run", "call_id": "steer"})
    receipt = supervisor.pending_guidance("worker")
    assert [row["body"] for row in receipt] == ["changed instructions"]
    llm.release.set()
    await asyncio.wait_for(task, 3)
    assert len(llm.requests) == 2  # guidance prevented the first final answer from sealing the run
    assert any(message.content == "changed instructions" for message in llm.requests[1].messages)
    assert supervisor.pending_guidance("worker") == []
    history = await store.get_history("parent:sub:worker")
    assert sum(row["content"] == "changed instructions" for row in history) == 1
    assert next(row for row in history if row["content"] == "changed instructions")["metadata"]["guidance_ids"] == [receipt[0]["id"]]
    assert (await supervisor.list())[0]["status"] == "idle"
    await supervisor.shutdown()


@pytest.mark.asyncio
async def test_failed_checkpoint_keeps_mail_durable_and_replay_is_idempotent(tmp_path):
    database = tmp_path / "members.db"
    supervisor = SubAgentSupervisor(parent_thread_id="parent", runner=SimpleNamespace(), database_path=database)
    supervisor._mail("worker", "parent_to_child", "steer", message_key="stable-id")
    state = RuntimeState(session_id="parent:sub:worker")
    history = []
    kernel = CoreLoopKernel(kit=SimpleNamespace(), llm_client=SimpleNamespace(),
                            state_store=InMemoryRuntimeStateStore(), event_sink=CollectingEventSink())
    turn = RuntimeTurnInput(guidance_source=lambda: supervisor.consume_guidance("worker"),
                            guidance_acknowledger=lambda ids: supervisor.acknowledge_guidance("worker", ids))
    async def fail(_state):
        raise OSError("fixture checkpoint failure")
    kernel._save_checkpoint = fail
    with pytest.raises(OSError):
        await kernel._consume_guidance(state, turn, history, 0)
    assert len(supervisor.pending_guidance("worker")) == 1
    assert kernel.event_sink.events == []  # no delivery event before the checkpoint commits
    reopened = SubAgentSupervisor(parent_thread_id="parent", runner=SimpleNamespace(), database_path=database)
    turn.guidance_source = lambda: reopened.consume_guidance("worker")
    committed = []
    async def commit(_state):
        committed.extend(history)
        assert len(reopened.pending_guidance("worker")) == 1
    kernel._save_checkpoint = commit
    await kernel._consume_guidance(state, turn, history, 1)
    assert [message.content for message in committed] == ["steer"]
    assert reopened.pending_guidance("worker") == []


async def context_for(tmp_path):
    db = await open_core_app_db(tmp_path / "core.db")
    store = InMemoryRuntimeStateStore()
    context = CoreLiveContext(operations=OperationCatalog(), session_factory=db.session_factory,
                              persistence=db.persistence, runtime_state_store=store, hub=CoreAppEventHub())
    return db, context, store


@pytest.mark.asyncio
async def test_recovery_aligns_registry_child_runtime_and_parent_projection_idempotently(tmp_path):
    db, context, store = await context_for(tmp_path)
    supervisor = SubAgentSupervisor(parent_thread_id="parent", runner=SimpleNamespace(), database_path=tmp_path / "sub_agents.sqlite3")
    supervisor._save(SubAgentRecord(parent_thread_id="parent", type="execute", name="worker", model_id="fixture",
                                    reasoning_level="high", status="running", started_at=1,
                                    sub_session_id="parent:sub:worker", source_turn_id="parent-turn", source_run_id="parent-turn"))
    await store.save(RuntimeState(session_id="parent:sub:worker", status="running", run_id="child-run"))
    await store.save(RuntimeState(session_id="parent", status="completed", run_id="parent-turn"))
    try:
        assert await reconcile_sub_agent_state(context=context, data_dir=tmp_path) == 1
        assert supervisor._required("worker").status == "interrupted"
        assert (await store.get("parent:sub:worker")).status == "cancelled"
        assert (await store.get("parent")).status == "completed"
        assert peek_member_events(tmp_path / "sub_agents.sqlite3", "parent")[0]["payload"]["event"] == "member_interrupted"
        async with db.session_factory() as session:
            snapshot = await db.persistence.load(session, "parent")
            count = await session.scalar(select(func.count()).select_from(CoreAppEvent))
        statuses = [item["payload"]["sub_agent"]["status"] for item in snapshot["core"]["items"].values()
                    if item.get("payload", {}).get("type") == "subAgentStatus"]
        assert statuses == ["interrupted"]
        assert await reconcile_sub_agent_state(context=context, data_dir=tmp_path) == 0
        async with db.session_factory() as session:
            assert await session.scalar(select(func.count()).select_from(CoreAppEvent)) == count
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_recovery_does_not_interrupt_a_live_other_owner(tmp_path):
    db, context, store = await context_for(tmp_path)
    supervisor = SubAgentSupervisor(parent_thread_id="parent", runner=SimpleNamespace(), database_path=tmp_path / "sub_agents.sqlite3")
    supervisor._save(SubAgentRecord(parent_thread_id="parent", type="execute", name="worker", model_id="fixture",
                                    reasoning_level="high", status="running", runtime_owner=owner_token(),
                                    sub_session_id="parent:sub:worker"))
    await store.save(RuntimeState(session_id="parent:sub:worker", status="running", metadata={"runtime_owner": owner_token()}))
    try:
        assert await reconcile_sub_agent_state(context=context, data_dir=tmp_path) == 0
        assert supervisor._required("worker").status == "running"
        assert (await store.get("parent:sub:worker")).status == "running"
        assert peek_member_events(tmp_path / "sub_agents.sqlite3", "parent") == []
        with pytest.raises(ValueError, match="another running process"):
            await supervisor.message(type="execute", name="worker", prompt="must not steal")
        assert supervisor.pending_guidance("worker") == []
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_legacy_receipt_backfill_requires_exact_history_and_counts_repeated_bodies(tmp_path):
    db, context, _store = await context_for(tmp_path)
    supervisor = SubAgentSupervisor(parent_thread_id="parent", runner=SimpleNamespace(), database_path=tmp_path / "sub_agents.sqlite3")
    supervisor._save(SubAgentRecord(parent_thread_id="parent", type="execute", name="worker", model_id="fixture",
                                    reasoning_level="high", status="interrupted", completed_at=2,
                                    sub_session_id="parent:sub:worker"))
    for key in ["first", "second"]:
        supervisor._mail("worker", "parent_to_child", "same body", message_key=key)
    supervisor._mail("worker", "parent_to_child", "not delivered", message_key="third")
    await db.runtime_state_store.append_history("parent:sub:worker", [{"role": "user", "content": "same body"}])
    try:
        await reconcile_sub_agent_state(context=context, data_dir=tmp_path, acknowledge_legacy_mail=True)
        assert [row["body"] for row in supervisor.pending_guidance("worker")] == ["same body", "not delivered"]
        await reconcile_sub_agent_state(context=context, data_dir=tmp_path, acknowledge_legacy_mail=True)
        assert len(supervisor.pending_guidance("worker")) == 2
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_next_parent_input_contains_pending_interruption_without_automatic_model_call(tmp_path):
    seed_model(tmp_path)
    data_dir = tmp_path / "data"
    supervisor = SubAgentSupervisor(parent_thread_id="parent", runner=SimpleNamespace(), database_path=data_dir / "sub_agents.sqlite3")
    record = SubAgentRecord(parent_thread_id="parent", type="execute", name="worker", model_id="fixture",
                             reasoning_level="high", status="interrupted", completed_at=2)
    supervisor._save(record)
    supervisor._write_member_event(record, "member_interrupted", detail="fixture process restart")
    llm = BoundaryLLM()
    llm.release.set()
    operations = create_core_agent_operations(spec=CoreAgentSpec(default_model="fixture"),
        paths=CoreAgentPaths(data_dir=data_dir, work_root=tmp_path), model_provider=llm,
        runtime_state_store=InMemoryRuntimeStateStore())
    assert llm.requests == []
    result = await operations.execute("turn.start", {"thread_id": "parent", "message": "continue"})
    assert result.status == "ok"
    assert any("worker" in str(message.content) and "fixture process restart" in str(message.content)
               for message in llm.requests[0].messages)
    assert peek_member_events(data_dir / "sub_agents.sqlite3", "parent") == []


@pytest.mark.asyncio
async def test_message_during_drive_closeout_starts_work_instead_of_stranding_mail(tmp_path):
    seed_model(tmp_path)
    class Runner:
        work_root = tmp_path
        calls = []
        async def run(self, **kwargs):
            self.calls.append(kwargs["task"])
            return SubAgentRunResult(session_id="parent:sub:worker", run_id="child",
                decision="done", model_id="fixture", message="done")
    runner = Runner()
    supervisor = SubAgentSupervisor(parent_thread_id="parent", runner=runner, database_path=tmp_path / "members.db")
    closing, release = asyncio.Event(), asyncio.Event()
    async def pause_closeout(*, exclude=""):
        if len(runner.calls) == 1:
            closing.set()
            await release.wait()
    supervisor._maybe_report_members_drained = pause_closeout
    await supervisor.create(type="execute", name="worker", model="fixture", reasoning_level="high")
    await supervisor.message(type="execute", name="worker", prompt="first")
    first = supervisor._tasks["worker"]
    await asyncio.wait_for(closing.wait(), 1)
    await supervisor.message(type="execute", name="worker", prompt="second")
    second = supervisor._tasks["worker"]
    assert second is not first
    await asyncio.wait_for(second, 1)
    release.set()
    await asyncio.wait_for(first, 1)
    assert runner.calls == ["first", "second"]
    assert supervisor.pending_guidance("worker") == []
    assert (await supervisor.list())[0]["status"] == "idle"
    await supervisor.shutdown()


def test_reconciling_an_existing_outbox_fact_does_not_reschedule_watchdog(tmp_path, monkeypatch):
    import lamtools_core.sub_agent_supervisor as module
    notified = []
    monkeypatch.setattr(module, "_notify_member_event", lambda: notified.append(True))
    supervisor = SubAgentSupervisor(parent_thread_id="parent", runner=SimpleNamespace(), database_path=tmp_path / "members.db")
    record = SubAgentRecord(parent_thread_id="parent", type="execute", name="worker", model_id="fixture",
                             reasoning_level="high", status="interrupted", completed_at=2)
    supervisor._write_member_event(record, "member_interrupted")
    supervisor._write_member_event(record, "member_interrupted")
    assert notified == [True]
    assert len(peek_member_events(tmp_path / "members.db", "parent")) == 1
