"""user:“继续，把 2 阶段都做完”+(检查点公开接口走原数据库与恢复操作，不恢复工作区文件、不伪造DSH日志)。"""
import pytest

from lamtools_core.checkpoint import register_checkpoint_operations
from lamtools_core.app.core_db import CoreRuntimeSession
from .test_plugin_working_directory import env
from .test_core_checkpoint_graph import _append_production_turn, _runtime, _tool_call_history


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
