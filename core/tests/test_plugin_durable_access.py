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


@pytest.mark.asyncio
@pytest.mark.parametrize("kind",["goals","schedule"])
@pytest.mark.parametrize("action",["get","list"])
@pytest.mark.parametrize("change",["host","scope"])
async def test_durable_reads_recheck_catalog_and_epoch_before_publication(env,monkeypatch,kind,action,change):
    # user:“完成真实接口、参数/错误、作用域、取消/清理”+(原持久查询返回前复核操作目录和启动代，失效后不得发布旧目标/计划结果)。
    from lamtools_core.plugin_system.durable_access import DurableAccessError
    from lamtools_core.plugin_system.services import ServiceError
    root, _, _, _ = env
    api = getattr(root,kind)
    fields = {"objective":"read boundary"} if kind == "goals" else {
        "operation":"test.task","payload":{},"trigger":{"type":"once","at":(datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat()}}
    row = await api.create(thread_id="s",request_id="read-boundary",**fields)
    catalog = root.operation_catalog
    original = catalog.execute
    entered, release = asyncio.Event(), asyncio.Event()
    async def gated(name,*args,**kwargs):
        result = await original(name,*args,**kwargs)
        if name == ("goal" if kind == "goals" else "arrange") + "." + action:
            entered.set()
            await release.wait()
        return result
    monkeypatch.setattr(catalog,"execute",gated)
    work = api.get(row["id"]) if action == "get" else api.list(thread_id="s")
    task = asyncio.create_task(work)
    try:
        await asyncio.wait_for(entered.wait(),3)
        if change == "host":
            root.operation_catalog = OperationCatalog()
        else:
            root._registration_scope.revoke()
        release.set()
        with pytest.raises(DurableAccessError if change == "host" else ServiceError) as error:
            await asyncio.wait_for(task,3)
        assert error.value.code == ("durable/host-changed" if change == "host" else "service/scope-closed")
        assert not root._registration_scope._calls
    finally:
        root.operation_catalog = catalog
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task,return_exceptions=True)


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
