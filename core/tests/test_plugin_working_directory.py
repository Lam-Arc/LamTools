"""user:“继续，把 2 阶段都做完”+(会话执行目录持久保存，但不能改变原项目身份、模型配置或已有执行视图)。"""
import asyncio
from pathlib import Path

import pytest

from lamtools_core.app.core_db import open_core_app_db
from lamtools_core.app.core_session_store import CoreDbSessionStore
from lamtools_core.app.live_operations import CoreLiveContext
from lamtools_core.app.live_hub import CoreAppEventHub
from lamtools_core.app.operation_catalog import OperationCatalog
from lamtools_core.app.plugin_sessions import install_plugin_session_services
from lamtools_core.plugin_system import PluginContext
from lamtools_core.session import SessionRecord


@pytest.mark.asyncio
@pytest.mark.parametrize("operation",["get","set","runtime"])
@pytest.mark.parametrize("change",["shutdown","store"])
async def test_directory_read_wait_cannot_cross_invalidated_host_or_write_old_store(env,monkeypatch,operation,change):
    # user:“复用原宿主权威”+(目录读取、修改和运行时恢复都必须在读取后复核宿主，不能写回已替换的旧存储)。
    from lamtools_core.plugin_system.working_directory import WorkingDirectoryError
    from lamtools_core.plugin_system.sessions import SessionError
    ctx, store, sessions, project = env
    api = ctx.working_directory
    host = sessions._context().host
    original = store.get_readonly_revision
    if operation == "runtime":
        record, revision = await original("s")
        await store.patch("s",metadata={**record.metadata,"execution_directory":str(project / "missing")},expected_revision=revision)
    before = await original("s")
    entered, release = asyncio.Event(), asyncio.Event()
    async def gated(session_id):
        result = await original(session_id)
        entered.set()
        await release.wait()
        return result
    monkeypatch.setattr(store,"get_readonly_revision",gated)
    if operation == "get":
        work = api.get("s")
    elif operation == "set":
        work = api.set("s","one",expected_revision=before[1])
    else:
        work = api._host.runtime_path("s",project)
    task = asyncio.create_task(work)
    try:
        await asyncio.wait_for(entered.wait(),3)
        if change == "shutdown":
            sessions.shutdown()
        else:
            host.session_store = object()
        release.set()
        with pytest.raises((WorkingDirectoryError,SessionError)) as error:
            await asyncio.wait_for(task,3)
        expected = "session/closed" if operation == "runtime" and change == "shutdown" else "working-directory/" + ("closed" if change == "shutdown" else "host-changed")
        assert error.value.code == expected
        assert await original("s") == before
    finally:
        host.session_store = store
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task,return_exceptions=True)


@pytest.fixture
async def env(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "one").mkdir()
    (project / "two").mkdir()
    db = await open_core_app_db(tmp_path / "working.db")
    store = CoreDbSessionStore(lambda: db)
    await store.create(SessionRecord("s", "core", "Example", "idle", metadata={"work_root": str(project), "project_id": "original"}))
    await store.create(SessionRecord("hidden", "core", "Hidden", "idle", metadata={"work_root": str(project)}))
    store._session_visible = lambda sid, _: sid != "hidden"
    live = CoreLiveContext(session_factory=db.session_factory, persistence=db.persistence, operations=OperationCatalog(), hub=CoreAppEventHub())
    live.host.session_store = store
    context = PluginContext(project, data_dir=tmp_path / "data")
    sessions = install_plugin_session_services(context, lambda: live)
    context._begin_registration_scope("example", 1)
    try:
        yield context, store, sessions, project
    finally:
        sessions.shutdown()
        await context._registration_scope.dispose()
        await db.close()


@pytest.mark.asyncio
async def test_directory_save_survives_new_scope_without_rebinding_project(env):
    ctx, store, _, project = env
    original = await ctx.working_directory.get("s")
    assert original.path == str(project) and original.exists
    updated = await ctx.working_directory.set("s", "one", expected_revision=original.revision)
    assert updated.path == str(project / "one") and updated.revision > original.revision
    record = await store.get_readonly("s")
    assert record.metadata["work_root"] == str(project)
    assert record.metadata["project_id"] == "original"
    await ctx._registration_scope.dispose()
    ctx._begin_registration_scope("example", 2)
    assert (await ctx.working_directory.get("s")).path == updated.path


@pytest.mark.asyncio
async def test_concurrent_set_conflicts_and_does_not_lose_other_metadata(env):
    from lamtools_core.plugin_system.working_directory import WorkingDirectoryError
    ctx, store, _, project = env
    state = await ctx.working_directory.get("s")
    results = await asyncio.gather(*[ctx.working_directory.set("s", name, expected_revision=state.revision)
                                     for name in ("one", "two")], return_exceptions=True)
    assert sum(isinstance(row, WorkingDirectoryError) and row.code == "working-directory/conflict" for row in results) == 1
    assert (await store.get_readonly("s")).metadata["project_id"] == "original"
    with pytest.raises(WorkingDirectoryError):
        await ctx.working_directory.set("s", "../", expected_revision=state.revision)


@pytest.mark.asyncio
async def test_missing_directory_ensure_restores_original_and_old_view_stays_pinned(env):
    ctx, _, _, project = env
    state = await ctx.working_directory.get("s")
    await ctx.working_directory.set("s", "one", expected_revision=state.revision)
    first = await ctx.for_session("s")
    assert first.work_root == project and first.filesystem.root == project / "one"
    assert first.processes._root == project / "one"
    assert first.llm._root == str(project)
    state = await ctx.working_directory.get("s")
    await ctx.working_directory.set("s", "two", expected_revision=state.revision)
    second = await ctx.for_session("s")
    assert first.filesystem.root == project / "one"
    assert second.filesystem.root == project / "two"
    assert second.shell._root == str(project / "two")
    (project / "two").rmdir()
    state = await ctx.working_directory.get("s")
    assert not state.exists
    restored = await ctx.working_directory.ensure("s", expected_revision=state.revision)
    assert restored.path == str(project) and restored.exists


@pytest.mark.asyncio
async def test_hidden_unknown_closed_and_stopped_facades_fail_explicitly(env):
    from lamtools_core.plugin_system.working_directory import WorkingDirectoryError
    from lamtools_core.plugin_system.services import ServiceError
    ctx, _, sessions, _ = env
    api = ctx.working_directory
    for sid in ("hidden", "unknown"):
        with pytest.raises(WorkingDirectoryError) as error:
            await api.get(sid)
        assert error.value.code == "working-directory/not-found"
    sessions.shutdown()
    with pytest.raises(WorkingDirectoryError) as error:
        await api.get("s")
    assert error.value.code == "working-directory/closed"
    await ctx._registration_scope.dispose()
    with pytest.raises(ServiceError):
        await api.get("s")


@pytest.mark.asyncio
async def test_cancelled_directory_commit_finishes_before_cancellation_returns(env, monkeypatch):
    ctx, store, _, project = env
    state = await ctx.working_directory.get("s")
    entered, release = asyncio.Event(), asyncio.Event()
    original = store.patch
    async def delayed(*args, **kwargs):
        entered.set()
        await release.wait()
        return await original(*args, **kwargs)
    monkeypatch.setattr(store, "patch", delayed)
    task = asyncio.create_task(ctx.working_directory.set("s", "one", expected_revision=state.revision))
    await asyncio.wait_for(entered.wait(), 3)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (await ctx.working_directory.get("s")).path == str(project / "one")


@pytest.mark.asyncio
async def test_old_native_process_keeps_its_cwd_after_session_directory_changes(env):
    import os
    import sys
    if os.name != "nt":
        pytest.skip("Owned native process implementation is Windows desktop")
    ctx, _, _, project = env
    state = await ctx.working_directory.get("s")
    await ctx.working_directory.set("s", "one", expected_revision=state.revision)
    first = await ctx.for_session("s")
    process = await first.processes.spawn([sys.executable, "-c", "import os,time; print(os.getcwd(),flush=True); time.sleep(0.3); print(os.getcwd())"], timeout=10)
    state = await ctx.working_directory.get("s")
    await ctx.working_directory.set("s", "two", expected_revision=state.revision)
    assert (await process.wait()).quiescent
    assert process.read_output().stdout.decode().splitlines() == [str(project / "one")] * 2
