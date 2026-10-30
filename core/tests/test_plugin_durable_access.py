"""user:“继续，把 2 阶段都做完”+(目标和定时任务接入原持久管理器/运行器，所有者与项目固定，不新造状态表)。"""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from lamtools_core.app import open_core_app_db
from lamtools_core.app.operation_catalog import OperationCatalog, OperationResult
from lamtools_core.app.durable_operations import register_durable_operations
from lamtools_core.plugin_system import PluginContext
from lamtools_core.runtime.goal import GoalManager
from lamtools_core.runtime.arrange import ArrangeManager, ArrangeRunner


@pytest.fixture
async def env(tmp_path):
    db = await open_core_app_db(tmp_path / "durable.db")
    catalog = OperationCatalog()
    calls = []
    async def task(request):
        calls.append(request.payload)
        return OperationResult(request.name, payload={"done": True})
    catalog.register("test.task", task)
    manager = ArrangeManager(db.arrange_store)
    goals = GoalManager(db.goal_store)
    async def execute(job):
        return (await catalog.execute(job.operation, job.payload)).payload
    runner = ArrangeRunner(db.arrange_store, execute, clock=lambda: datetime.now(timezone.utc) + timedelta(minutes=1))
    register_durable_operations(catalog, goal_manager=goals, arrange_manager=manager, wake_runner=runner.wake, cancel_running=runner.cancel)
    root = PluginContext(tmp_path, operation_catalog=catalog)
    root._begin_registration_scope("example", 1)
    try:
        yield root, db, runner, calls
    finally:
        await root._registration_scope.dispose()
        await runner.stop()
        await db.close()


@pytest.mark.asyncio
async def test_goal_create_retry_update_and_owner_filter_use_real_store(env, tmp_path):
    root, db, _, _ = env
    goal = await root.goals.create(thread_id="s", request_id="one", objective="Finish it", completion_criteria=["result exists"])
    repeated = await root.goals.create(thread_id="s", request_id="one", objective="changed retry")
    assert repeated["id"] == goal["id"] and repeated["objective"] == "Finish it"
    changed = await root.goals.update(goal["id"], status="blocked", status_reason="waiting")
    assert changed["status"] == "blocked"
    assert (await db.goal_store.get(goal["id"])).status == "blocked"
    other = PluginContext(tmp_path, operation_catalog=root.operation_catalog)
    other._begin_registration_scope("other", 1)
    try:
        from lamtools_core.plugin_system import DurableAccessError
        with pytest.raises(DurableAccessError):
            await other.goals.get(goal["id"])
        assert (await root.goals.list(thread_id="s"))["items"][0]["id"] == goal["id"]
    finally:
        await other._registration_scope.dispose()


@pytest.mark.asyncio
async def test_schedule_is_persistent_and_actual_runner_executes_existing_operation(env):
    root, db, runner, calls = env
    when = (datetime.now(timezone.utc) + timedelta(seconds=10)).isoformat()
    job = await root.schedule.create(thread_id="s", request_id="one", operation="test.task", payload={"x": 1},
        trigger={"type": "once", "at": when}, kind="focus", session_strategy="fixed")
    same = await root.schedule.create(thread_id="s", request_id="one", operation="test.task", payload={"x": 2},
        trigger={"type": "once", "at": when}, kind="focus", session_strategy="fixed")
    assert job["id"] == same["id"] and same["payload"] == {"x": 1}
    assert (await db.arrange_store.get(job["id"])).work_root == str(root.work_root)
    assert await runner.run_due_once() == 1
    for _ in range(200):
        if (await root.schedule.get(job["id"]))["status"] == "completed":
            break
        await asyncio.sleep(0.01)
    assert calls == [{"x": 1}]
    assert (await root.schedule.get(job["id"]))["status"] == "completed"


@pytest.mark.asyncio
async def test_stop_revokes_access_but_does_not_delete_durable_intent(env):
    from lamtools_core.plugin_system.services import ServiceError
    root, db, _, _ = env
    api = root.goals
    goal = await api.create(thread_id="s", request_id="one", objective="Persist")
    await root._registration_scope.dispose()
    with pytest.raises(ServiceError):
        await api.get(goal["id"])
    assert await db.goal_store.get(goal["id"]) is not None
