"""user:“继续，把 2 阶段都做完”+(检查点公开接口走原数据库与恢复操作，不恢复工作区文件、不伪造DSH日志)。"""
import pytest

from lamtools_core.checkpoint import register_checkpoint_operations
from lamtools_core.app.core_db import CoreRuntimeSession
from .test_plugin_working_directory import env
from .test_core_checkpoint_graph import _append_production_turn, _runtime, _tool_call_history


@pytest.mark.asyncio
@pytest.mark.parametrize("change",["shutdown","catalog"])
async def test_already_dispatched_checkpoint_write_still_settles_original_commit(setup,monkeypatch,change):
    # user:“复用原宿主权威”+(已通过准入并派发的检查点写入继续按原提交事实收尾，不把失效检查变成提交后伪回滚)。
    import asyncio
    from lamtools_core.app.operation_catalog import OperationCatalog
    ctx, _, sessions, _, _ = setup
    api, catalog = ctx.checkpoints, ctx.operation_catalog
    original = catalog.execute
    entered, release = asyncio.Event(), asyncio.Event()
    async def gated(name,*args,**kwargs):
        if name == "session.checkpoints.create":
            entered.set()
            await release.wait()
        return await original(name,*args,**kwargs)
    monkeypatch.setattr(catalog,"execute",gated)
    task = asyncio.create_task(api.create("s",label="accepted-before-invalidation"))
    try:
        await asyncio.wait_for(entered.wait(),3)
        if change == "shutdown":
            sessions.shutdown()
        else:
            ctx.operation_catalog = OperationCatalog()
        release.set()
        result = await asyncio.wait_for(task,3)
        saved = await original("session.checkpoints.list",{"session_id":"s"})
        assert any(row["id"] == result["checkpoint"]["id"] for row in saved.payload["checkpoints"])
        assert result["checkpoint"]["label"] == "accepted-before-invalidation"
    finally:
        ctx.operation_catalog = catalog
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task,return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation",["list","create"])
@pytest.mark.parametrize("change",["shutdown","catalog","store"])
async def test_checkpoint_visibility_wait_rechecks_original_authority_before_dispatch(setup,monkeypatch,operation,change):
    # user:“复用原宿主权威”+(检查点可见性读取期间宿主失效后，不能再向旧操作目录提交读取或恢复写入)。
    import asyncio
    from lamtools_core.app.operation_catalog import OperationCatalog
    from lamtools_core.plugin_system.checkpoint_access import CheckpointAccessError
    ctx, store, sessions, _, _ = setup
    api, catalog = ctx.checkpoints, ctx.operation_catalog
    host = sessions._context().host
    original_read, original_execute = store.get_readonly, catalog.execute
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []
    async def gated(session_id):
        result = await original_read(session_id)
        entered.set()
        await release.wait()
        return result
    async def observed(*args,**kwargs):
        calls.append(args[0])
        return await original_execute(*args,**kwargs)
    monkeypatch.setattr(store,"get_readonly",gated)
    monkeypatch.setattr(catalog,"execute",observed)
    work = api.list("s") if operation == "list" else api.create("s",label="must-not-dispatch")
    task = asyncio.create_task(work)
    try:
        await asyncio.wait_for(entered.wait(),3)
        if change == "shutdown":
            sessions.shutdown()
        elif change == "catalog":
            ctx.operation_catalog = OperationCatalog()
        else:
            host.session_store = object()
        release.set()
        with pytest.raises(CheckpointAccessError) as error:
            await asyncio.wait_for(task,3)
        assert error.value.code == "checkpoint/" + ("closed" if change == "shutdown" else "host-changed")
        assert calls == []
        result = await original_execute("session.checkpoints.list",{"session_id":"s"})
        assert result.payload["checkpoints"] == []
    finally:
        ctx.operation_catalog = catalog
        host.session_store = store
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task,return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("change",["shutdown","catalog","store","scope"])
async def test_checkpoint_list_rechecks_authority_after_native_operation(setup,monkeypatch,change):
    # user:“完成真实接口、参数/错误、作用域、取消/清理”+(检查点只读结果发布前复核宿主和启动代，写入仍按原已接收提交收尾)。
    import asyncio
    from lamtools_core.app.operation_catalog import OperationCatalog
    from lamtools_core.plugin_system.checkpoint_access import CheckpointAccessError
    from lamtools_core.plugin_system.services import ServiceError
    ctx, store, sessions, _, _ = setup
    api, catalog = ctx.checkpoints, ctx.operation_catalog
    host = sessions._context().host
    original = catalog.execute
    entered, release = asyncio.Event(), asyncio.Event()
    async def gated(*args,**kwargs):
        result = await original(*args,**kwargs)
        entered.set()
        await release.wait()
        return result
    monkeypatch.setattr(catalog,"execute",gated)
    task = asyncio.create_task(api.list("s"))
    try:
        await asyncio.wait_for(entered.wait(),3)
        if change == "shutdown":
            sessions.shutdown()
        elif change == "catalog":
            ctx.operation_catalog = OperationCatalog()
        elif change == "store":
            host.session_store = object()
        else:
            ctx._registration_scope.revoke()
        release.set()
        with pytest.raises(ServiceError if change == "scope" else CheckpointAccessError) as error:
            await asyncio.wait_for(task,3)
        assert error.value.code == ("service/scope-closed" if change == "scope" else "checkpoint/closed" if change == "shutdown" else "checkpoint/host-changed")
    finally:
        ctx.operation_catalog = catalog
        host.session_store = store
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task,return_exceptions=True)


@pytest.fixture
async def setup(env):
    ctx, store, sessions, project = env
    db = store._db_provider()
    catalog = sessions._context().operations
    ctx.operation_catalog = catalog
    register_checkpoint_operations(catalog, session_factory=db.session_factory, default_work_root=project,
                                   app_event_store=db.event_store, thread_snapshot_store=db.snapshot_store)
    return ctx, store, sessions, project, db


@pytest.mark.asyncio
async def test_real_checkpoint_restore_and_fork_preserve_workspace_files(setup):
    ctx, store, _, project, db = setup
    await _runtime(db, "s", history=_tool_call_history("one"))
    await _append_production_turn(db, "s", "turn-1", "one")
    checkpoint = (await ctx.checkpoints.create("s", label="Before change"))["checkpoint"]
    assert checkpoint["work_root"] == str(project)
    assert any(c["id"] == checkpoint["id"] for c in (await ctx.checkpoints.list("s"))["checkpoints"])
    await _runtime(db, "s", history=[*_tool_call_history("one"), *_tool_call_history("two")])
    await _append_production_turn(db, "s", "turn-2", "two")
    file = project / "keep.txt"
    file.write_text("current content")
    restored = await ctx.checkpoints.restore("s", checkpoint["id"])
    assert restored["scope"] == "conversation"
    assert file.read_text() == "current content"
    history = await db.runtime_state_store.get_history("s")
    assert [{k: v for k, v in message.items() if k != "metadata"} for message in history] == _tool_call_history("one")
    forked = await ctx.checkpoints.fork("s", checkpoint_id=checkpoint["id"], new_session_id="fork", title="Fork")
    assert forked["session_id"] == "fork"
    assert (await store.get_readonly("fork")).metadata["work_root"] == str(project)
    async with db.session_factory() as connection:
        runtime = await connection.get(CoreRuntimeSession, "fork")
        assert runtime is not None
    history = await db.runtime_state_store.get_history("fork")
    assert [{k: v for k, v in message.items() if k != "metadata"} for message in history] == _tool_call_history("one")


@pytest.mark.asyncio
async def test_checkpoint_rejects_hidden_sessions_wrong_checkpoint_and_revoked_facades(setup):
    from lamtools_core.plugin_system.checkpoint_access import CheckpointAccessError
    from lamtools_core.plugin_system.services import ServiceError
    ctx, _, _, _, _ = setup
    api = ctx.checkpoints
    with pytest.raises(CheckpointAccessError) as error:
        await api.list("hidden")
    assert error.value.code == "checkpoint/not-found"
    with pytest.raises(CheckpointAccessError):
        await api.restore("s", "unknown-checkpoint")
    with pytest.raises(CheckpointAccessError):
        await api.fork("s", checkpoint_id="a", turn_id="b")
    await ctx._registration_scope.dispose()
    with pytest.raises(ServiceError):
        await api.list("s")


@pytest.mark.asyncio
async def test_native_turn_fork_uses_actual_history_and_running_session_is_rejected(setup):
    from lamtools_core.plugin_system.checkpoint_access import CheckpointAccessError
    ctx, store, sessions, _, db = setup
    await _runtime(db, "s", history=_tool_call_history("one"))
    await _append_production_turn(db, "s", "turn-1", "one")
    forked = await ctx.checkpoints.fork("s", turn_id="turn-1", new_session_id="turn-fork")
    assert forked["mode"] == "conversation_only"
    registry = sessions._context().host.runtime_task_registry
    assert registry.accept_run("s", "active", turn_id="active")
    try:
        with pytest.raises(CheckpointAccessError) as error:
            await ctx.checkpoints.restore("s", "any-checkpoint")
        assert error.value.code == "checkpoint/active-session"
    finally:
        registry.release_run("s", run_id="active")


@pytest.mark.asyncio
async def test_checkpoint_cancellation_joins_native_operation_before_return(setup, monkeypatch):
    import asyncio
    ctx, _, _, _, _ = setup
    catalog = ctx.operation_catalog
    original = catalog.execute
    entered, release = asyncio.Event(), asyncio.Event()
    async def delayed(name, payload, **kwargs):
        if name == "session.checkpoints.create":
            entered.set()
            await release.wait()
        return await original(name, payload, **kwargs)
    monkeypatch.setattr(catalog, "execute", delayed)
    task = asyncio.create_task(ctx.checkpoints.create("s", label="cancelled-observer"))
    await asyncio.wait_for(entered.wait(), 3)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert any(c["label"] == "cancelled-observer" for c in (await ctx.checkpoints.list("s"))["checkpoints"])
