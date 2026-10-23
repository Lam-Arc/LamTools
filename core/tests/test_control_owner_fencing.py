"""user:“修 问题严重的话 就重新设计”+(真实执行与控制收尾必须绑定同一身份和唯一所有者)。"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.tests.test_turn_control_architecture_boundaries import context_for, ScriptedModel
from lamtools_core.app import open_core_app_db
from lamtools_core.app import live_operations as live
from lamtools_core.app.event_store import AppEventInput
from lamtools_core.app.sub_agent_recovery import reconcile_sub_agent_state
from lamtools_core.runtime import RuntimeState, RuntimeTaskRegistry
from lamtools_core.runtime_owner import owner_token
from lamtools_core.sub_agent_supervisor import (
    SubAgentSupervisor, SubAgentRecord, find_sub_agent_supervisor,
    get_sub_agent_supervisor, register_sub_agent_lifecycle_operations, _SUPERVISORS,
)


def member(parent, status="suspended"):
    return SubAgentRecord(parent_thread_id=parent, name="worker", type="execute",
        model_id="fixture", reasoning_level="off", status=status)


class Runner:
    def __init__(self, store):
        self.state_store = store
        self.calls = []

    async def resume_interrupted(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(decision="done", error="", message="real completion")


@pytest.fixture
async def env(tmp_path):
    db = await open_core_app_db(tmp_path / "core.db")
    ctx = await context_for(db, tmp_path, ScriptedModel("stream"))
    try:
        yield db, ctx
    finally:
        for key, sup in list(_SUPERVISORS.items()):
            if sup.database_path.is_relative_to(tmp_path):
                await sup.shutdown()
                _SUPERVISORS.pop(key, None)
        await ctx.runtime_task_registry.shutdown()
        await live.wait_live_background_tasks()
        await db.close()


async def seed_turn(db, thread="t", turn="logical", run="attempt"):
    await db.persistence.write(lambda session: db.persistence.append(session, AppEventInput(
        thread_id=thread, turn_id=turn, method="turn/accepted",
        payload={"status": "running", "input": [], "runtime_snapshot": {}},
    )))
    existing = await db.runtime_state_store.get(thread)
    if existing is None:
        await db.runtime_state_store.save(RuntimeState(session_id=thread, run_id=run, status="running",
            metadata={"turn_id": turn}))
    else:
        def replace(state):
            state.run_id = run
            state.status = "running"
            state.metadata = {"turn_id": turn}
        await db.runtime_state_store.patch(thread, replace)


@pytest.mark.asyncio
async def test_pause_uses_logical_identity_even_when_execution_id_differs(env):
    db, ctx = env
    await seed_turn(db)
    ctx.runtime_task_registry.accept_run("t", "attempt", turn_id="logical")
    await live.handle_turn_pause_operation(request_id=1, params={"thread_id": "t", "turn_id": "logical"}, context=ctx)
    await live.wait_live_background_tasks()
    async with db.session_factory() as session:
        snapshot = await db.persistence.load(session, "t")
        events = await db.event_store.list_thread(session, thread_id="t")
    assert set(snapshot["turns"]) == {"logical"}
    assert snapshot["turns"]["logical"]["status"] == "paused"
    paused = [event.payload for event in events if event.payload.get("status") == "paused"]
    assert paused and paused[-1]["run_id"] == "attempt"


@pytest.mark.asyncio
async def test_delayed_pause_cannot_modify_a_replacement_execution(env, monkeypatch):
    db, ctx = env
    await seed_turn(db)
    ctx.runtime_task_registry.accept_run("t", "attempt", turn_id="logical")
    held = []
    monkeypatch.setattr(live, "_spawn_live_background", lambda coro, **kwargs: held.append(coro))
    await live.handle_turn_pause_operation(request_id=1, params={"thread_id": "t", "turn_id": "logical"}, context=ctx)
    ctx.runtime_task_registry.release_run("t", run_id="attempt")
    ctx.runtime_task_registry.accept_run("t", "new-attempt", turn_id="new-logical")
    await seed_turn(db, turn="new-logical", run="new-attempt")
    for coro in held:
        await coro
    current = await db.runtime_state_store.get("t")
    assert current.status == "running"
    assert current.metadata.get("pause_reason") != "user_pause"
    async with db.session_factory() as session:
        snapshot = await db.persistence.load(session, "t")
    assert snapshot["turns"]["new-logical"]["status"] == "running"


@pytest.mark.asyncio
async def test_reconciliation_preserves_real_owner_and_stop_reaches_real_task(env, tmp_path):
    db, ctx = env
    runner = Runner(db.runtime_state_store)
    sup = await get_sub_agent_supervisor(parent_thread_id="parent", runner=runner, data_dir=tmp_path / "data")
    record = member("parent", "running")
    record.runtime_owner = owner_token()
    sup._save(record)
    task = asyncio.create_task(asyncio.Event().wait())
    sup._tasks["worker"] = task
    try:
        await reconcile_sub_agent_state(context=ctx, data_dir=tmp_path / "data")
        current = find_sub_agent_supervisor("parent")
        assert current is sup
        await current.interrupt_active(include_paused=True)
        assert task.done()
        assert current._required("worker").status == "terminated"
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_restart_resume_rebuilds_executable_owner_and_finishes(env, tmp_path):
    db, ctx = env
    data = tmp_path / "data"
    observer = SubAgentSupervisor(parent_thread_id="parent", runner=SimpleNamespace(state_store=db.runtime_state_store),
        database_path=data / "sub_agents.sqlite3")
    observer._save(member("parent"))
    runner = Runner(db.runtime_state_store)
    # Isolate the real lifecycle catalog from unrelated production providers.
    from lamtools_core.app import OperationCatalog
    ctx = live.CoreLiveContext(operations=OperationCatalog(), host=ctx.host)
    register_sub_agent_lifecycle_operations(ctx.operations, runner_factory=lambda: runner, data_dir=data)
    await reconcile_sub_agent_state(context=ctx, data_dir=data)
    await live._resume_session_members(context=ctx, thread_id="parent")
    sup = find_sub_agent_supervisor("parent")
    assert sup is not None
    await asyncio.gather(*list(sup._tasks.values()))
    assert len(runner.calls) == 1
    assert sup._required("worker").status == "idle"
    assert sup._required("worker").summary == "real completion"


@pytest.mark.asyncio
async def test_cold_terminate_reaches_durable_members_without_cached_owner(env, tmp_path):
    db, ctx = env
    data = tmp_path / "cold"
    observer = SubAgentSupervisor(parent_thread_id="cold-parent", runner=SimpleNamespace(), database_path=data / "sub_agents.sqlite3")
    observer._save(member("cold-parent"))
    from lamtools_core.app import OperationCatalog
    ctx = live.CoreLiveContext(operations=OperationCatalog(), host=ctx.host)
    register_sub_agent_lifecycle_operations(ctx.operations, runner_factory=lambda: Runner(db.runtime_state_store), data_dir=data)
    await live._interrupt_session_members(context=ctx, thread_id="cold-parent", include_paused=True, final_status="terminated")
    assert observer._required("worker").status == "terminated"


@pytest.mark.asyncio
async def test_owner_shutdown_does_not_leave_a_dead_cached_owner(env, tmp_path):
    db, ctx = env
    sup = await get_sub_agent_supervisor(parent_thread_id="closed-parent", runner=Runner(db.runtime_state_store), data_dir=tmp_path / "owners")
    await sup.shutdown()
    assert find_sub_agent_supervisor("closed-parent") is None


@pytest.mark.asyncio
async def test_pause_of_remaining_children_keeps_completed_parent_completed(env, tmp_path):
    db, ctx = env
    await seed_turn(db)
    await db.runtime_state_store.patch("t", lambda state: setattr(state, "status", "completed"))
    from lamtools_core.event import RunItemEvent
    await db.persistence.write(lambda session: db.persistence.append_batch(session, run_item_events=[RunItemEvent(
        thread_id="t", turn_id="logical", run_id="attempt", event_id="finished", item_id="finished", kind="status",
        status="completed", payload={"type": "turn", "status": "completed"},
    )]))
    sup = await get_sub_agent_supervisor(parent_thread_id="t", runner=Runner(db.runtime_state_store), data_dir=tmp_path / "members")
    sup._save(member("t", "running"))
    result = await live.handle_turn_pause_operation(request_id=1,
        params={"thread_id": "t", "turn_id": "logical"}, context=ctx)
    await live.wait_live_background_tasks()
    assert sup._required("worker").status == "suspended"
    async with db.session_factory() as session:
        snapshot = await db.persistence.load(session, "t")
    assert snapshot["turns"]["logical"]["status"] == "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["done", "wait", "cancelled", "failed"])
async def test_late_approval_result_cannot_replace_termination(tmp_path, decision):
    sup = SubAgentSupervisor(parent_thread_id="parent", runner=SimpleNamespace(),
        database_path=tmp_path / "members.sqlite3")
    sup._save(member("parent"))
    await sup.interrupt_active(include_paused=True)
    await sup.finalize_resumed("worker", SimpleNamespace(decision=decision, error="", message="late"))
    assert sup._required("worker").status == "terminated"
    assert await sup.resume_interrupted() == []
    await sup.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["running", "pending", "paused", "suspended", "interrupted"])
async def test_terminate_is_final_for_every_resumable_member_state(tmp_path, status):
    sup = SubAgentSupervisor(parent_thread_id="parent", runner=SimpleNamespace(), database_path=tmp_path / "members.db")
    sup._save(member("parent", status))
    await sup.interrupt_active(include_paused=True)
    assert sup._required("worker").status == "terminated"
    assert await sup.resume_interrupted() == []
    assert await sup.resume_suspended() == []
    await sup.shutdown()


def test_rejected_claim_cannot_change_current_turn_identity():
    registry = RuntimeTaskRegistry()
    assert registry.accept_run("t", "current")
    assert not registry.accept_run("t", "stale", turn_id="foreign")
    assert registry.active_turn_id("t") == ""


@pytest.mark.asyncio
async def test_observer_cannot_enter_execution_registry_through_factory(tmp_path):
    try:
        with pytest.raises(ValueError, match="execution"):
            await get_sub_agent_supervisor(parent_thread_id="observer", runner=SimpleNamespace(), data_dir=tmp_path)
        assert find_sub_agent_supervisor("observer", data_dir=tmp_path) is None
    finally:
        owner = find_sub_agent_supervisor("observer", data_dir=tmp_path)
        if owner is not None:
            await owner.shutdown()


@pytest.mark.asyncio
async def test_late_result_cannot_overwrite_a_recreated_member(tmp_path):
    sup = SubAgentSupervisor(parent_thread_id="parent", runner=SimpleNamespace(), database_path=tmp_path / "members.db")
    sup._save(member("parent"))
    old_token = sup.execution_token("worker")
    await sup.interrupt_active(include_paused=True)
    replacement = member("parent", "running")
    sup._save(replacement)
    await sup.finalize_resumed("worker", SimpleNamespace(decision="done", message="old", error=""), expected_token=old_token)
    assert sup._required("worker").status == "running"
    assert sup._required("worker").summary == ""
    await sup.shutdown()


@pytest.mark.asyncio
async def test_control_from_another_connection_fences_a_loaded_result(tmp_path):
    database = tmp_path / "members.db"
    first = SubAgentSupervisor(parent_thread_id="p", runner=SimpleNamespace(), database_path=database)
    second = SubAgentSupervisor(parent_thread_id="p", runner=SimpleNamespace(), database_path=database)
    first._save(member("p", "running"))
    pending_result = first._required("worker")
    token = pending_result.execution_token
    await second.interrupt_active(include_paused=True)
    pending_result.status = "idle"
    assert first._save_if_current(pending_result, token) is False
    assert first._required("worker").status == "terminated"
    await first.shutdown()
    await second.shutdown()


@pytest.mark.asyncio
async def test_member_pause_rechecks_control_after_waiting_for_lock(tmp_path):
    sup = SubAgentSupervisor(parent_thread_id="p", runner=SimpleNamespace(), database_path=tmp_path / "members.db")
    sup._save(member("p", "running"))
    valid = True
    await sup._lock.acquire()
    action = asyncio.create_task(sup.pause_active(control_guard=lambda: valid))
    await asyncio.sleep(0)
    valid = False
    sup._lock.release()
    assert await action == []
    assert not sup.pause_event.is_set()
    assert sup._required("worker").status == "running"
    await sup.shutdown()


@pytest.mark.asyncio
async def test_driver_cannot_restore_member_after_cancellation_is_consumed(tmp_path):
    started = asyncio.Event()
    class ConsumingRunner:
        async def resume_interrupted(self, **kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                return SimpleNamespace(decision="done", error="", message="too late")
    sup = SubAgentSupervisor(parent_thread_id="parent", runner=ConsumingRunner(), database_path=tmp_path / "members.db")
    sup._save(member("parent"))
    await sup.resume_suspended()
    await asyncio.wait_for(started.wait(), 2)
    await sup.interrupt_active(include_paused=True)
    assert sup._required("worker").status == "terminated"
    await sup.shutdown()


@pytest.mark.asyncio
async def test_mirror_does_not_bypass_a_failed_compare_and_swap(env, monkeypatch):
    db, ctx = env
    from lamtools_core.turn import Turn
    store = ctx.turn_store
    await store.create_turn(Turn(thread_id="t", turn_id="logical", status="running"))
    # Simulate a concurrent control decision winning the transaction.
    monkeypatch.setattr(store, "transition_turn", AsyncMock(return_value=None))
    save = AsyncMock()
    monkeypatch.setattr(store, "save_turn", save)
    await live._mirror_turn_status(context=ctx, thread_id="t", turn_id="logical", status="paused")
    save.assert_not_awaited()


@pytest.mark.asyncio
async def test_real_child_question_continues_after_answer_with_execution_fence(tmp_path, monkeypatch):
    from core.tests import test_sub_agent_takeover as fixtures
    from lamtools_core.runtime import InMemoryRuntimeStateStore
    import uuid
    thread = f"review-question-{uuid.uuid4().hex}"
    child = f"{thread}:sub:worker"
    monkeypatch.setattr(fixtures, "THREAD", thread)
    monkeypatch.setattr(fixtures, "CHILD_SESSION", child)
    model = fixtures.QuestionChildLLM()
    store = InMemoryRuntimeStateStore()
    catalog = fixtures._catalog(tmp_path, model, store)
    try:
        result = await catalog.execute("turn.start", {"thread_id": thread, "message": "delegate", "approval_policy": "require"})
        assert result.status == "ok"
        sent = await catalog.execute("sub_agent.message", {"thread_id": thread, "type": "execute", "name": "worker", "prompt": "report"})
        assert sent.status == "ok"
        sup = find_sub_agent_supervisor(thread)
        await asyncio.wait_for(asyncio.gather(*list(sup._tasks.values())), 5)
        pending = (await store.get(child)).metadata["pending_approval"]
        answered = await catalog.execute("approval.respond", {"thread_id": thread,
            "request_id": pending["request_id"], "decision": "approve_once", "guidance": "blue"})
        assert answered.status == "ok"
        assert model.child_calls == 2
        assert sup._required("worker").status == "idle"
        assert "blue" in model.answer_seen
    finally:
        sup = find_sub_agent_supervisor(thread)
        if sup is not None:
            await sup.shutdown()


@pytest.mark.asyncio
async def test_real_main_pause_resume_then_pause_keeps_one_logical_turn(tmp_path):
    from lamtools_core.llm import LLMStreamEvent
    class Model:
        def __init__(self):
            self.started = asyncio.Queue()
        async def complete(self, request):
            raise AssertionError("stream expected")
        async def stream(self, request):
            await self.started.put(True)
            await asyncio.Event().wait()
            yield LLMStreamEvent(kind="done")
    db = await open_core_app_db(tmp_path / "real.db")
    model = Model()
    ctx = await context_for(db, tmp_path, model)
    try:
        accepted = await live.handle_turn_start_operation(request_id=1,
            params={"thread_id": "real", "input": [{"type": "text", "text": "do work"}]}, context=ctx)
        turn = accepted.runtime_start["turn_id"]
        await asyncio.wait_for(model.started.get(), 3)
        for index in range(2):
            await live.handle_turn_pause_operation(request_id=2, params={"thread_id": "real", "turn_id": turn}, context=ctx)
            await live.wait_live_background_tasks()
            async with db.session_factory() as session:
                snap = await db.persistence.load(session, "real")
            assert set(snap["turns"]) == {turn}
            assert snap["turns"][turn]["status"] == "paused"
            if index == 0:
                resumed = await live.handle_turn_resume_operation(request_id=3,
                    params={"thread_id": "real", "turn_id": turn}, context=ctx)
                assert "error" not in resumed.response
                await asyncio.wait_for(model.started.get(), 3)
    finally:
        await ctx.runtime_task_registry.shutdown()
        await live.wait_live_background_tasks()
        await db.close()
