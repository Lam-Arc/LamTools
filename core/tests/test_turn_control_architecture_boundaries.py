"""Acceptance blockers for the turn-control redesign.

user:“你的审查要涵盖绝大部分的边界行为，而且，这个是代码缺陷还是架构缺陷？如果是架构缺陷的话，就需要重新设计架构”
+这六项曾经是严格 xfail 的迁移阻断项，现按身份约束与单一写入权修复，作为真实验收保留；
不能再用 xfail 或镜像兜底冒充通过。
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from lamtools_core.app import CoreAgentPaths, CoreAgentSpec, create_core_agent_operations, open_core_app_db
from lamtools_core.app import live_operations as live
from lamtools_core.app.event_store import AppEventInput
from lamtools_core.app.live_hub import CoreAppEventHub
from lamtools_core.llm import LLMStreamEvent
from lamtools_core.runtime import RuntimeState, RuntimeTaskRegistry
from lamtools_core.sub_agent_supervisor import SubAgentRecord, SubAgentSupervisor
from lamtools_core.turn import Turn

class ScriptedModel:
    def __init__(self, mode):
        self.requests = []

    async def complete(self, request):
        raise AssertionError("use the local scripted stream")

    async def stream(self, request):
        self.requests.append(request)
        yield LLMStreamEvent(kind="content_delta", content="Completed after resume")
        yield LLMStreamEvent(kind="done")


async def context_for(db, root, model):
    registry, hub = RuntimeTaskRegistry(), CoreAppEventHub()
    operations = create_core_agent_operations(
        spec=CoreAgentSpec(default_model="fixture"),
        paths=CoreAgentPaths(data_dir=root / "data", work_root=root), model_provider=model,
        runtime_state_store=db.runtime_state_store, runtime_task_registry=registry,
        db_session_factory=db.session_factory, app_event_store=db.event_store,
        thread_snapshot_store=db.snapshot_store, app_event_hub=hub,
        write_coordinator=db.persistence.write_coordinator,
    )
    return live.CoreLiveContext(
        session_factory=db.session_factory, persistence=db.persistence, operations=operations,
        hub=hub, runtime_task_registry=registry, runtime_state_store=db.runtime_state_store,
    )


@pytest.mark.asyncio
async def test_stale_pause_never_cancels_a_new_turn():
    registry = RuntimeTaskRegistry()
    task = asyncio.create_task(asyncio.Event().wait())
    registry.accept_run("thread", "new-turn")
    registry.register("thread", task, run_id="new-turn")
    context = SimpleNamespace(
        host=SimpleNamespace(runtime_task_registry=registry), runtime_state_store=None,
    )
    try:
        # Suppress only detached persistence: observe the immediate actuator.
        with patch.object(live, "_spawn_live_background", side_effect=lambda coro, **kw: coro.close()):
            await live.handle_turn_pause_operation(
                request_id=1, params={"thread_id": "thread", "turn_id": "old-turn"}, context=context,
            )
        await asyncio.sleep(0)
        assert not task.cancelled()
    finally:
        await registry.shutdown()


@pytest.mark.asyncio
async def test_terminated_children_cannot_be_resumed(tmp_path):
    supervisor = SubAgentSupervisor(
        parent_thread_id="parent", runner=SimpleNamespace(), database_path=tmp_path / "children.sqlite3",
    )
    supervisor._save(SubAgentRecord(
        parent_thread_id="parent", name="worker", type="execute", model_id="fixture",
        reasoning_level="off", status="suspended",
    ))
    try:
        await supervisor.interrupt_active(include_paused=True)
        assert await supervisor.resume_interrupted() == []
    finally:
        await supervisor.shutdown()


@pytest.mark.asyncio
async def test_restart_resume_restores_durable_paused_children(tmp_path):
    # user:“修 问题严重的话 就重新设计”+(恢复验收等到真实执行完成，不能只断言调度瞬间的 running)。
    from lamtools_core.sub_agent_supervisor import find_sub_agent_supervisor
    db = await open_core_app_db(tmp_path / "restart.db")
    context = await context_for(db, tmp_path, ScriptedModel("stream"))
    child_session = "restart-parent:sub:worker"
    observer = SubAgentSupervisor(
        parent_thread_id="restart-parent", runner=SimpleNamespace(),
        database_path=tmp_path / "data" / "sub_agents.sqlite3",
    )
    observer._save(SubAgentRecord(
        parent_thread_id="restart-parent", name="worker", type="execute", model_id="fixture",
        reasoning_level="off", status="suspended", sub_session_id=child_session,
    ))
    await db.runtime_state_store.save(RuntimeState(
        session_id=child_session, run_id="old-child-attempt", status="paused", loop_state="paused",
        metadata={"actor_kind": "sub_agent", "delegated_session": {
            "task": "finish original child task", "agent": "worker", "model": "fixture", "mode": "execute",
        }},
    ))
    try:
        await observer.recover()
        await live._resume_session_members(context=context, thread_id="restart-parent")
        owner = find_sub_agent_supervisor("restart-parent")
        assert owner is not None
        await asyncio.wait_for(asyncio.gather(*list(owner._tasks.values())), 5)
        assert owner._required("worker").status == "idle"
        assert owner._required("worker").summary == "Completed after resume"
        assert (await db.runtime_state_store.get(child_session)).status == "completed"
    finally:
        owner = find_sub_agent_supervisor("restart-parent")
        if owner is not None:
            await owner.shutdown()
        await context.runtime_task_registry.shutdown()
        await live.wait_live_background_tasks()
        await db.close()


@pytest.mark.asyncio
async def test_early_pause_resume_preserves_original_and_supplement(tmp_path):
    db = await open_core_app_db(tmp_path / "core.db")
    model = ScriptedModel("stream")
    model.requests.append(None)  # The first actual model call should finish immediately.
    context = await context_for(db, tmp_path, model)
    try:
        accepted = await live.handle_turn_start_operation(request_id=1, params={
            "thread_id": "thread", "input": [{"type": "text", "text": "ORIGINAL_TASK"}],
            "include_snapshot": False,
        }, context=context)
        turn_id = accepted.runtime_start["turn_id"]
        await live.handle_turn_pause_operation(
            request_id=2, params={"thread_id": "thread", "turn_id": turn_id}, context=context,
        )
        await live.wait_live_background_tasks()
        resumed = await live.handle_turn_resume_operation(request_id=3, params={
            "thread_id": "thread", "turn_id": turn_id,
            "input": [{"type": "text", "text": "SUPPLEMENT"}],
        }, context=context)
        assert "error" not in resumed.response
        task = context.runtime_task_registry.task("thread")
        if task is not None:
            await task
        actual_input = str(model.requests[-1].messages)
        assert "SUPPLEMENT" in actual_input
        assert "ORIGINAL_TASK" in actual_input
    finally:
        await context.runtime_task_registry.shutdown()
        await live.wait_live_background_tasks()
        await db.close()


@pytest.mark.asyncio
async def test_parent_pause_keeps_child_question_pending(tmp_path):
    from lamtools_core.turn import Interaction

    db = await open_core_app_db(tmp_path / "core.db")
    context = await context_for(db, tmp_path, ScriptedModel("stream"))
    try:
        await context.turn_store.create_interaction(Interaction(
            interaction_id="child-question", thread_id="parent", turn_id="parent-turn",
            scope="agent:parent:sub:worker", kind="question", status="open",
        ))
        await live._close_open_interactions(context=context, thread_id="parent", reason="turn_paused")
        interaction = await context.turn_store.get_interaction("child-question")
        assert interaction.status in {"open", "deferred"}
    finally:
        await context.runtime_task_registry.shutdown()
        await db.close()


@pytest.mark.asyncio
async def test_cancelled_approval_cannot_invent_a_turn_during_pause_settlement(tmp_path):
    db = await open_core_app_db(tmp_path / "core.db")
    context = await context_for(db, tmp_path, ScriptedModel("stream"))
    thread, turn_id, run_id = "thread", "logical-turn", "execution-attempt"
    try:
        async def seed(session):
            await db.persistence.append(session, AppEventInput(
                thread_id=thread, turn_id=turn_id, method="turn/accepted",
                payload={"status": "running", "input": [], "runtime_snapshot": {}},
            ))

        await db.persistence.write(seed)
        await db.runtime_state_store.save(RuntimeState(
            session_id=thread, run_id=run_id, status="running", loop_state="continue",
            metadata={"turn_id": turn_id},
        ))
        # Control intent is already settled in the turn model while the old
        # worker checkpoint lags. This is the ordering that must be fenced.
        await context.turn_store.create_turn(Turn(
            thread_id=thread, turn_id=turn_id, status="paused", epoch=2,
        ))

        async def cancelled(*args, **kwargs):
            raise asyncio.CancelledError()

        with patch.object(context.operations, "execute", new=cancelled):
            with pytest.raises(asyncio.CancelledError):
                await live._execute_continuation_job(context=context, job={
                    "job_id": "job", "thread_id": thread, "turn_id": turn_id, "run_id": run_id,
                    "kind": "approval.respond", "payload": {"params": {"thread_id": thread}},
                })
        async with db.session_factory() as session:
            snapshot = await db.persistence.load(session, thread)
        assert run_id not in snapshot.get("turns", {})
    finally:
        await context.runtime_task_registry.shutdown()
        await db.close()
