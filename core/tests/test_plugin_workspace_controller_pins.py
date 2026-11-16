"""Acceptance tests for host-owned, current-project workspace pinning."""

import sqlite3

import pytest
from sqlalchemy import text

from lamtools_core.app import open_core_app_db
from lamtools_core.app.core_db import CoreThreadSnapshot
from .test_plugin_workspace_registry_current import workspace_env


@pytest.mark.asyncio
async def test_workspace_controller_pins_current_project_in_most_recent_order(workspace_env):
    # user:“宿主能力补齐和接口完善与文档更新”+(置顶次序由原Core项目存储持久化并按最近置顶优先返回)。
    ctx, db, _, project, _ = workspace_env
    first = (await db.project_store.list_sessions(project.id))[0]
    second = await db.project_store.create_session(project.id, title="Second")

    assert await ctx.workspace_controller.pin_session(first.id) == {"pinned_session_ids": [first.id]}
    assert await ctx.workspace_controller.pin_session(second.id) == {
        "pinned_session_ids": [second.id, first.id]
    }
    assert await ctx.workspace_controller.pin_session(first.id) == {
        "pinned_session_ids": [second.id, first.id]
    }


@pytest.mark.asyncio
async def test_workspace_controller_unpin_is_idempotent_and_project_scoped(workspace_env):
    # user:“每一个地方 sunday 都有等价或者近似接口”+(unpin对当前项目是幂等的，不能改动另一个项目的置顶)。
    ctx, db, _, project, other = workspace_env
    foreign = (await db.project_store.list_sessions(other.id))[0]
    await db.project_store.pin_session(other.id, foreign.id)

    assert await ctx.workspace_controller.unpin_session(foreign.id) == {"pinned_session_ids": []}
    assert await db.project_store.pinned_session_ids(other.id) == [foreign.id]
    assert await ctx.workspace_controller.unpin_session("missing-session") == {"pinned_session_ids": []}
    with pytest.raises(RuntimeError) as error:
        await ctx.workspace_controller.pin_session(foreign.id)
    assert error.value.code == "session/not-found"


@pytest.mark.asyncio
async def test_workspace_pin_uses_real_authenticated_remote_and_original_project_store(workspace_env, tmp_path):
    # user:“建立真实请求、错误、作用域、取消/流和清理验收”+(置顶只在原Core项目会话与认证Remote请求中提交)。
    import httpx
    from fastapi import FastAPI

    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token

    ctx, db, catalog, project, _ = workspace_env
    session = (await db.project_store.list_sessions(project.id))[0]
    host, _, original = _host(tmp_path)
    configure(host)
    ctx._secret_store = original._secret_store
    host.backend_manager.context = ctx
    (host.get("hook-demo").root / "ops.py").write_text(
        "async def echo(request, *, context):\n"
        "    return await context.workspace_controller.pin_session(request.payload['body']['text'])\n",
        encoding="utf8",
    )
    catalog.unregister_owner("plugin:hook-demo")
    register_plugin_operations(catalog, host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        url = "/plugin-remote/hook-demo/demo/echo"
        rejected = await client.post(url, json={"args": {"text": session.id}}, headers={"x-plugin-token": "wrong"})
        accepted = await client.post(url, json={"args": {"text": session.id}},
            headers={"x-plugin-token": plugin_http_token(host, "hook-demo")})

    assert rejected.status_code == 401
    assert accepted.status_code == 200
    assert accepted.json()["payload"] == {"pinned_session_ids": [session.id]}
    assert await db.project_store.pinned_session_ids(project.id) == [session.id]


@pytest.mark.asyncio
async def test_workspace_pin_cancellation_waits_for_original_store_commit(workspace_env, monkeypatch):
    # user:“建立真实请求、错误、作用域、取消/流和清理验收”+(写入派发后收到取消时，等待原Core置顶事务结算，再向调用方传播取消)。
    import asyncio

    ctx, db, _, project, _ = workspace_env
    session = (await db.project_store.list_sessions(project.id))[0]
    original = db.project_store.pin_session
    started, release = asyncio.Event(), asyncio.Event()

    async def delayed_pin(project_id, session_id):
        result = await original(project_id, session_id)
        started.set()
        await release.wait()
        return result

    monkeypatch.setattr(db.project_store, "pin_session", delayed_pin)
    call = asyncio.create_task(ctx.workspace_controller.pin_session(session.id))
    await asyncio.wait_for(started.wait(), timeout=2)
    call.cancel()
    await asyncio.sleep(0)
    assert not call.done()

    release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(call, timeout=2)
    assert await db.project_store.pinned_session_ids(project.id) == [session.id]


@pytest.mark.asyncio
async def test_workspace_pin_persists_across_database_reopen(tmp_path):
    # user:“建立真实请求、错误、作用域、取消/流和清理验收”+(旧库重开后置顶状态仍由原Core数据库保存)。
    path, root = tmp_path / "workspace-pins.db", tmp_path / "project"
    first_db = await open_core_app_db(path)
    project, _ = await first_db.project_store.create(root, name="Pinned")
    session = (await first_db.project_store.list_sessions(project.id))[0]
    await first_db.project_store.pin_session(project.id, session.id)
    await first_db.close()

    second_db = await open_core_app_db(path)
    try:
        assert await second_db.project_store.pinned_session_ids(project.id) == [session.id]
        async with second_db.project_store.session_factory() as db:
            row = await db.get(CoreThreadSnapshot, session.id)
            assert row.workspace_pin_order is not None
    finally:
        await second_db.close()


@pytest.mark.asyncio
async def test_workspace_pin_rejects_legacy_session_snapshot_without_pin_column(tmp_path):
    # user:“只运行本次新增相关测试”+(首次打开旧Core库时必须安全补齐置顶列，而不是等schema版本单向迁移)。
    path = tmp_path / "legacy-workspace-pins.db"
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE core_thread_snapshots ("
        "thread_id VARCHAR(64) PRIMARY KEY, snapshot_seq INTEGER NOT NULL DEFAULT 0, "
        "revision INTEGER NOT NULL DEFAULT 0, active_turn_id VARCHAR(64), "
        "snapshot_json JSON NOT NULL DEFAULT '{}', updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )
    connection.commit()
    connection.close()

    db = await open_core_app_db(path)
    try:
        async with db.project_store.session_factory() as session:
            columns = await session.execute(text("PRAGMA table_info(core_thread_snapshots)"))
            assert "workspace_pin_order" in {row[1] for row in columns}
    finally:
        await db.close()


def test_workspace_pin_migration_maps_only_the_scoped_near_equivalent(tmp_path):
    # user:“固定上游源码及手册”+(迁移报告标出当前项目置顶子集与全局Peer顺序差异)。
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port

    root = source(tmp_path, {"index.ts": "export function apply(ctx) { ctx.remote.workspace.pinSession({sessionId:'s'}); }"})
    report = export_port(root, tmp_path / "ported-workspace-pins")
    remote = next(row for row in report["remotes"] if row["name"] == "workspace.pinSession")
    assert remote["suggestedContract"] == "context.workspace_controller.pin_session"
    assert "当前项目" in remote["difference"] and "全局" in remote["difference"]
