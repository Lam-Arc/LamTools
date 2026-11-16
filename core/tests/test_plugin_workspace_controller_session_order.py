"""Acceptance tests for host-owned, current-project session ordering."""

import asyncio
import sqlite3

import pytest
from sqlalchemy import select, text

from lamtools_core.app import open_core_app_db
from .test_plugin_workspace_registry_current import workspace_env


@pytest.mark.asyncio
async def test_insert_session_before_reorders_the_original_current_project_sessions(workspace_env):
    # user:“建立真实请求、错误、作用域、取消/流和清理验收”+(手动顺序写入原Core会话行，并影响同一项目的原列表)。
    ctx, db, _, project, _ = workspace_env
    initial = [session.id for session in await db.project_store.list_sessions(project.id)]
    second = await db.project_store.create_session(project.id, title="Second")
    third = await db.project_store.create_session(project.id, title="Third")
    before = [session.id for session in await db.project_store.list_sessions(project.id)]
    assert before == [*initial, second.id, third.id]

    assert await ctx.workspace_controller.insert_session_before(third.id, second.id) == {
        "session_ids": [*initial, third.id, second.id]
    }
    assert [session.id for session in await db.project_store.list_sessions(project.id)] == [
        *initial, third.id, second.id
    ]


@pytest.mark.asyncio
async def test_insert_session_before_can_append_and_self_anchor_is_a_noop(workspace_env):
    # user:“按依赖推进工作区/会话/文件”+(向后移通过省略锚点追加；把会话放到自身之前不改变顺序)。
    ctx, db, _, project, _ = workspace_env
    first = (await db.project_store.list_sessions(project.id))[0]
    second = await db.project_store.create_session(project.id, title="Second")
    third = await db.project_store.create_session(project.id, title="Third")

    assert await ctx.workspace_controller.insert_session_before(second.id, first.id) == {
        "session_ids": [second.id, first.id, third.id]
    }
    assert await ctx.workspace_controller.insert_session_before(first.id, first.id) == {
        "session_ids": [second.id, first.id, third.id]
    }
    assert await ctx.workspace_controller.insert_session_before(second.id) == {
        "session_ids": [first.id, third.id, second.id]
    }


@pytest.mark.asyncio
async def test_insert_session_before_rejects_foreign_or_hidden_sessions(workspace_env):
    # user:“真实请求、错误、作用域”+(目标和锚点都必须是当前项目内对插件可见的原会话)。
    ctx, db, _, project, other = workspace_env
    own = (await db.project_store.list_sessions(project.id))[0]
    foreign = (await db.project_store.list_sessions(other.id))[0]

    for target, anchor in ((foreign.id, None), (own.id, foreign.id), ("missing", None)):
        with pytest.raises(RuntimeError) as error:
            await ctx.workspace_controller.insert_session_before(target, anchor)
        assert error.value.code == "workspace/move-invalid"


@pytest.mark.asyncio
async def test_insert_session_before_preserves_hidden_session_slots(workspace_env, monkeypatch):
    # user:“复用原宿主权威”+(重排可见会话时保留原存储中隐藏会话的位置与相对顺序)。
    ctx, db, _, project, _ = workspace_env
    first = (await db.project_store.list_sessions(project.id))[0]
    hidden = await db.project_store.create_session(project.id, title="Hidden")
    third = await db.project_store.create_session(project.id, title="Third")
    hidden.metadata["owner_plugin"] = "another-plugin"
    async with db.project_store.session_factory() as session:
        from lamtools_core.app.core_db import CoreThreadSnapshot
        from lamtools_core.app.core_session_store import session_snapshot

        row = await session.get(CoreThreadSnapshot, hidden.id)
        row.snapshot_json = session_snapshot(hidden)
        await session.commit()

    monkeypatch.setattr(db.project_store, "_is_session_visible", lambda session: session.id != hidden.id)
    visible_before = [row.id for row in await db.project_store.list_sessions(project.id)]
    assert visible_before == [first.id, third.id]
    result = await ctx.workspace_controller.insert_session_before(third.id, first.id)

    assert result == {"session_ids": [third.id, first.id]}
    assert [row.id for row in await db.project_store.list_sessions(project.id)] == [third.id, first.id]
    async with db.project_store.session_factory() as session:
        from lamtools_core.app.core_db import CoreThreadSnapshot

        rows = (await session.execute(
            select(CoreThreadSnapshot).where(
                CoreThreadSnapshot.thread_id.in_([first.id, hidden.id, third.id])
            ).order_by(CoreThreadSnapshot.workspace_session_order)
        )).scalars().all()
        assert [row.thread_id for row in rows] == [third.id, hidden.id, first.id]


@pytest.mark.asyncio
async def test_session_order_persists_after_database_reopen(tmp_path):
    # user:“宿主能力补齐和接口完善与文档更新”+(会话顺序写入Core数据库，重开后仍由同一宿主读取)。
    path, root = tmp_path / "workspace-session-order.db", tmp_path / "project"
    first_db = await open_core_app_db(path)
    project, _ = await first_db.project_store.create(root, name="Ordered")
    first = (await first_db.project_store.list_sessions(project.id))[0]
    second = await first_db.project_store.create_session(project.id, title="Second")
    third = await first_db.project_store.create_session(project.id, title="Third")
    await first_db.project_store.insert_session_before(project.id, third.id, second.id)
    await first_db.close()

    second_db = await open_core_app_db(path)
    try:
        assert [row.id for row in await second_db.project_store.list_sessions(project.id)] == [
            first.id, third.id, second.id
        ]
    finally:
        await second_db.close()


@pytest.mark.asyncio
async def test_legacy_core_database_gets_session_order_column(tmp_path):
    # user:“继续推进第三阶段”+(旧Core库打开时由原数据库补列机制添加会话顺序字段)。
    path = tmp_path / "legacy-session-order.db"
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
            result = await session.execute(text("PRAGMA table_info(core_thread_snapshots)"))
            columns = {row[1] for row in result}
        assert "workspace_session_order" in columns
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_session_order_uses_real_authenticated_remote(workspace_env, tmp_path):
    # user:“建立真实请求、错误、作用域、取消/流和清理验收”+(只通过显式插件Remote和原token改变Core项目中的真实顺序)。
    import httpx
    from fastapi import FastAPI
    import json

    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token

    ctx, db, catalog, project, _ = workspace_env
    first = (await db.project_store.list_sessions(project.id))[0]
    second = await db.project_store.create_session(project.id, title="Second")
    third = await db.project_store.create_session(project.id, title="Third")
    host, _, original = _host(tmp_path)
    configure(host)
    manifest_path = host.get("hook-demo").root / "plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf8"))
    manifest["http"]["remote"][0]["argsSchema"] = {
        "type": "object",
        "properties": {
            "session_id": {"type": "string"},
            "before_session_id": {"type": "string"},
        },
        "required": ["session_id", "before_session_id"],
        "additionalProperties": False,
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf8")
    host._invalidate()
    from lamtools_core.plugin_system.remote_gateway import read_remote_methods
    read_remote_methods(host.get("hook-demo"))
    ctx._secret_store = original._secret_store
    host.backend_manager.context = ctx
    (host.get("hook-demo").root / "ops.py").write_text(
        "async def echo(request, *, context):\n"
        "    body = request.payload['body']\n"
        "    return await context.workspace_controller.insert_session_before("
        "body['session_id'], body.get('before_session_id'))\n",
        encoding="utf8",
    )
    catalog.unregister_owner("plugin:hook-demo")
    register_plugin_operations(catalog, host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        url = "/plugin-remote/hook-demo/demo/echo"
        rejected = await client.post(url, json={"args": {"session_id": third.id, "before_session_id": first.id}},
            headers={"x-plugin-token": "wrong"})
        accepted = await client.post(url, json={"args": {"session_id": third.id, "before_session_id": first.id}},
            headers={"x-plugin-token": plugin_http_token(host, "hook-demo")})

    assert rejected.status_code == 401
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["payload"] == {"session_ids": [third.id, first.id, second.id]}
    assert [row.id for row in await db.project_store.list_sessions(project.id)] == [third.id, first.id, second.id]


@pytest.mark.asyncio
async def test_session_order_cancellation_waits_for_original_store_commit(workspace_env, monkeypatch):
    # user:“建立真实请求、错误、作用域、取消/流和清理验收”+(派发后取消须等待Core原顺序写入结算，再释放调用租约)。
    ctx, db, _, project, _ = workspace_env
    first = (await db.project_store.list_sessions(project.id))[0]
    second = await db.project_store.create_session(project.id, title="Second")
    third = await db.project_store.create_session(project.id, title="Third")
    original = db.project_store.insert_session_before
    started, release = asyncio.Event(), asyncio.Event()

    async def delayed_insert(project_id, session_id, before_session_id=None):
        result = await original(project_id, session_id, before_session_id)
        started.set()
        await release.wait()
        return result

    monkeypatch.setattr(db.project_store, "insert_session_before", delayed_insert)
    call = asyncio.create_task(ctx.workspace_controller.insert_session_before(third.id, first.id))
    await asyncio.wait_for(started.wait(), timeout=2)
    call.cancel()
    await asyncio.sleep(0)
    assert not call.done()

    release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(call, timeout=2)
    assert [row.id for row in await db.project_store.list_sessions(project.id)] == [third.id, first.id, second.id]


def test_insert_session_before_migration_reports_current_project_scope(tmp_path):
    # user:“固定上游源码及手册”+(迁移报告只给当前项目顺序近似，不冒充全局Peer权限或事件流)。
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port

    root = source(tmp_path, {"index.ts": "export function apply(ctx) { ctx.remote.workspace.insertSessionBefore({workspaceId:'p',sessionId:'s'}); }"})
    report = export_port(root, tmp_path / "ported-session-order")
    remote = next(row for row in report["remotes"] if row["name"] == "workspace.insertSessionBefore")
    assert remote["suggestedContract"] == "context.workspace_controller.insert_session_before"
    assert "当前项目" in remote["difference"] and "全局" in remote["difference"]
