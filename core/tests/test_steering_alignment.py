"""Main/child guidance contract checks with no provider calls."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from lamtools_core.app import CoreAgentPaths, CoreAgentSpec, create_core_agent_operations, open_core_app_db
from lamtools_core.app.event_store import AppEventInput
from lamtools_core.app.steering import pending_steering
from lamtools_core.event import CollectingEventSink
from lamtools_core.kernel import CoreLoopKernel
from lamtools_core.llm import LLMStreamEvent
from lamtools_core.runtime import InMemoryRuntimeStateStore, RuntimeState, RuntimeTaskRegistry, RuntimeTurnInput
from lamtools_core.sub_agent_supervisor import (
    SubAgentRecord, SubAgentSupervisor, acknowledge_parent_guidance, bound_child_identity, drain_parent_mailbox,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["main", "child"])
@pytest.mark.parametrize("checkpoint_fails", [False, True])
async def test_guidance_contract_preserves_id_and_acknowledges_only_checkpointed_input(tmp_path, kind, checkpoint_fails):
    if kind == "main":
        registry = RuntimeTaskRegistry()
        registry.accept_run("thread", "run")
        registry.register("thread", asyncio.current_task(), run_id="run")
        registry.accept_guidance("thread", "steer", run_id="run", guidance_id="g1")
        source = registry.guidance_source("thread", run_id="run", include_metadata=True)
        pending = lambda: len(registry._entries["thread"].guidance)
        acknowledge = lambda ids: registry.acknowledge_guidance("thread", run_id="run", guidance_ids=ids)
    else:
        supervisor = SubAgentSupervisor(parent_thread_id="thread", runner=SimpleNamespace(), database_path=tmp_path / "members.db")
        supervisor._mail("worker", "parent_to_child", "steer", message_key="g1")
        source = lambda: supervisor.consume_guidance("worker")
        pending = lambda: len(supervisor.pending_guidance("worker"))
        acknowledge = lambda ids: supervisor.acknowledge_guidance("worker", ids)
    sink = CollectingEventSink()
    history = []
    kernel = CoreLoopKernel(kit=SimpleNamespace(), llm_client=SimpleNamespace(),
                            state_store=InMemoryRuntimeStateStore(), event_sink=sink)
    async def save(_state):
        assert pending() == 1
        assert history[0].metadata["guidance_ids"]
        if checkpoint_fails:
            raise OSError("checkpoint failed")
    kernel._save_checkpoint = save
    turn = RuntimeTurnInput(guidance_source=source, guidance_acknowledger=acknowledge)
    try:
        if checkpoint_fails:
            with pytest.raises(OSError):
                await kernel._consume_guidance(RuntimeState(session_id="thread"), turn, history, 0)
            assert pending() == 1
            assert sink.events == []
        else:
            assert await kernel._consume_guidance(RuntimeState(session_id="thread"), turn, history, 0)
            assert pending() == 0
            assert [message.content for message in history] == ["steer"]
            assert sink.events[0].payload["metadata"]["guidance_id"] == history[0].metadata["guidance_ids"][0]
    finally:
        if kind == "main":
            registry.release_run("thread", run_id="run")


@pytest.mark.asyncio
@pytest.mark.parametrize("commit", [True, False])
async def test_final_boundary_waits_for_reserved_acceptance_then_commit_or_rollback(commit):
    registry = RuntimeTaskRegistry()
    registry.accept_run("thread", "run")
    registry.register("thread", asyncio.current_task(), run_id="run")
    registry.accept_guidance("thread", "steer", run_id="run", guidance_id="g1", ready=False)
    assert registry.offer_guidance("thread", run_id="run") == []
    finalizing = asyncio.create_task(registry.guidance_finalizer("thread", run_id="run", include_metadata=True)())
    await asyncio.sleep(0)  # let the finalizer reach its event wait, no wall-clock delay
    assert not finalizing.done()
    if commit:
        registry.publish_guidance("thread", run_id="run", guidance_id="g1")
        assert (await finalizing)[0]["metadata"]["guidance_id"] == "g1"
        registry.acknowledge_guidance("thread", run_id="run", guidance_ids=["g1"])
        assert await registry.guidance_finalizer("thread", run_id="run", include_metadata=True)() == []
    else:
        registry.retract_guidance("thread", run_id="run", guidance_id="g1")
        assert await finalizing == []
    assert registry.accept_guidance("thread", "too late", run_id="run", guidance_id="g2") == "closed"
    registry.release_run("thread", run_id="run")


@pytest.mark.asyncio
async def test_anonymous_guidance_has_distinct_ids_and_builtin_source_acknowledger():
    registry = RuntimeTaskRegistry()
    registry.accept_run("thread", "run")
    registry.register("thread", asyncio.current_task(), run_id="run")
    for text in ["one", "two"]:
        registry.inject_guidance("thread", text, run_id="run")
    source = registry.guidance_source("thread", run_id="run", include_metadata=True)
    offered = source()
    ids = [item["metadata"]["guidance_id"] for item in offered]
    assert len(set(ids)) == 2
    source.acknowledger(ids)
    assert registry._entries["thread"].guidance == []
    registry.release_run("thread", run_id="run")


@pytest.mark.asyncio
@pytest.mark.parametrize("receipt_role", ["user", "system"])
async def test_accepted_unconsumed_steering_is_restored_once_on_explicit_next_input(tmp_path, receipt_role):
    models = tmp_path / ".lam" / "config" / "models"
    models.mkdir(parents=True)
    (models / "fixture.jsonc").write_text('{"model_id":"fixture","capability":"text"}', encoding="utf-8")
    db = await open_core_app_db(tmp_path / "core.db")
    class LLM:
        requests = []
        async def complete(self, _request):
            raise AssertionError("no provider")
        async def stream(self, request):
            self.requests.append(request)
            yield LLMStreamEvent(kind="content_delta", content="done")
            yield LLMStreamEvent(kind="done")
    llm = LLM()
    async def accept(session):
        for message_id, payload in [
            ("g1", {"input": [{"type": "text", "text": "already checkpointed"}], "guidance_id": "g1"}),
            ("g2", {"input": [{"type": "text", "text": "undelivered instructions"}], "guidance_id": "g2"}),
            ("legacy", {"input": [{"type": "text", "text": "do not replay unmarked legacy input"}]}),
        ]:
            await db.persistence.append(session, AppEventInput(thread_id="thread", turn_id="old-turn",
                method="turn/steered", client_message_id=message_id, payload=payload))
    try:
        await db.persistence.write(accept)
        await db.runtime_state_store.append_history("thread", [{"role": receipt_role, "content": "already checkpointed",
                                                                "metadata": {"guidance_ids": ["g1"]}}])
        assert [item["id"] for item in await pending_steering(db.session_factory, "thread")] == ["g2"]
        operations = create_core_agent_operations(spec=CoreAgentSpec(default_model="fixture"),
            paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=tmp_path), model_provider=llm,
            runtime_state_store=db.runtime_state_store, db_session_factory=db.session_factory)
        assert llm.requests == []
        result = await operations.execute("turn.start", {"thread_id": "thread", "message": "newest instructions", "run_id": "new-run"})
        assert result.status == "ok"
        user = [message for message in llm.requests[0].messages if message.role == "user" and not message.metadata.get("internal")][-1]
        assert "undelivered instructions" in user.content
        assert user.content.endswith("newest instructions")
        assert "unmarked legacy" not in user.content
        assert await pending_steering(db.session_factory, "thread") == []
        result = await operations.execute("turn.start", {"thread_id": "thread", "message": "next instruction", "run_id": "later-run"})
        assert result.status == "ok"
        assert [message for message in llm.requests[-1].messages if message.role == "user" and not message.metadata.get("internal")][-1].content == "next instruction"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_injected_child_reply_receipt_waits_for_parent_checkpoint(tmp_path):
    injected = []
    def sink(*args):
        injected.append(args)
        return True
    sink.acknowledges_after_checkpoint = True
    supervisor = SubAgentSupervisor(parent_thread_id="parent", runner=SimpleNamespace(parent_guidance_sink=sink),
                                    database_path=tmp_path / "members.db")
    supervisor._save(SubAgentRecord(parent_thread_id="parent", type="execute", name="worker", model_id="fixture",
                                    reasoning_level="high", status="running", source_run_id="run"))
    with bound_child_identity(supervisor, child_type="execute", name="worker"):
        await supervisor.child_message("reply", message_id="message")
    assert len(drain_parent_mailbox(tmp_path / "members.db", "parent", mark_delivered=False)) == 1
    acknowledge_parent_guidance(tmp_path / "members.db", "parent", [injected[0][3]])
    assert drain_parent_mailbox(tmp_path / "members.db", "parent", mark_delivered=False) == []
