"""user:“每一个地方 sunday 都有等价或者近似接口”+(提供受当前插件项目范围约束的会话列表近似，不冒充全局Peer可见列表)。"""
import asyncio

import httpx
import pytest
from fastapi import FastAPI

from .test_plugin_workspace_registry_current import workspace_env
from .test_plugin_workspace_sessions import populated


@pytest.mark.asyncio
async def test_session_controller_lists_only_current_project_sessions_in_bounded_pages(populated):
    # user:“每一个地方 sunday 都有等价或者近似接口”+(沿用原工作区会话扫描，不打开冷Agent或泄露其他项目会话)。
    ctx, _, _, project, _, _ = populated
    page = await ctx.session_controller.list_current_project(limit=1)
    found = {row.session_id for row in page.items}
    while page.has_more:
        page = await ctx.session_controller.list_current_project(limit=1, cursor=page.next_cursor)
        found.update(row.session_id for row in page.items)
    assert {"a", "b"} <= found
    assert "hidden" not in found
    assert "private" not in found
    assert page.has_more is False


@pytest.mark.asyncio
async def test_session_controller_current_project_list_uses_real_authenticated_remote(tmp_path, populated):
    # user:“建立真实请求、错误、作用域、取消/流和清理验收”+(从认证HTTP执行到原SQLite会话查询并保持项目隔离)。
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token

    ctx, _, catalog, project, _, _ = populated
    host, _, original = _host(tmp_path)
    configure(host)
    ctx._secret_store = original._secret_store
    host.backend_manager.context = ctx
    (host.get("hook-demo").root / "ops.py").write_text(
        "from lamtools_core.app.operation_catalog import OperationResult\n"
        "async def echo(request, *, context):\n"
        "    page = await context.session_controller.list_current_project(limit=50)\n"
        "    return OperationResult(request.name, {'items': [{'session_id': row.session_id} for row in page.items], 'has_more': page.has_more})\n",
        encoding="utf8",
    )
    catalog.unregister_owner("plugin:hook-demo")
    register_plugin_operations(catalog, host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        url = "/plugin-remote/hook-demo/demo/echo"
        rejected = await client.post(url, json={"args": {"text": "list"}}, headers={"x-plugin-token": "wrong"})
        accepted = await client.post(url, json={"args": {"text": "list"}},
            headers={"x-plugin-token": plugin_http_token(host, "hook-demo")})
    assert rejected.status_code == 401
    assert accepted.status_code == 200
    assert {item["session_id"] for item in accepted.json()["payload"]["items"]} >= {"a", "b"}
    assert "hidden" not in accepted.text and "private" not in accepted.text


@pytest.mark.asyncio
async def test_session_controller_list_repeated_cancel_waits_for_original_scan(populated, monkeypatch):
    # user:“建立真实请求、错误、作用域、取消/流和清理验收”+(重复取消必须等原扫描收尾，避免提前释放插件作用域)。
    ctx, _, _, _, _, store = populated
    entered, release = asyncio.Event(), asyncio.Event()
    cleaned = asyncio.Event()
    original = store.scan_readonly

    async def gated(**kwargs):
        try:
            result = await original(**kwargs)
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                # Model a scan already accepted by the host that cannot be stopped immediately.
                await release.wait()
            return result
        finally:
            cleaned.set()

    monkeypatch.setattr(store, "scan_readonly", gated)
    task = asyncio.create_task(ctx.session_controller.list_current_project(limit=50))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert cleaned.is_set() is False
        assert ctx._registration_scope._calls
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cleaned.is_set()
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_session_controller_list_repeated_cancel_waits_for_project_resolution(populated, monkeypatch):
    # user:“建立真实请求、错误、作用域、取消/流和清理验收”+(重复取消必须等当前项目原生解析结算且不能把已取消读取变成成功结果)。
    ctx, _, catalog, _, _, _ = populated
    original = catalog.execute
    entered, release, cleaned = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def gated(name, *args, **kwargs):
        result = await original(name, *args, **kwargs)
        if name == "project.resolve":
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                # This accepted host read cannot be interrupted immediately.
                while not release.is_set():
                    try:
                        await release.wait()
                    except asyncio.CancelledError:
                        continue
            finally:
                cleaned.set()
        return result

    monkeypatch.setattr(catalog, "execute", gated)
    task = asyncio.create_task(ctx.session_controller.list_current_project(limit=50))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert cleaned.is_set() is False
        assert ctx._registration_scope._calls
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cleaned.is_set()
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def test_session_list_migration_names_project_scoped_near_equivalent(tmp_path):
    # user:“逐项核对固定上游源码及手册”+(迁移提示准确标出上游全局列表与Sunday当前项目子集的差异)。
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port

    root = source(tmp_path, {"index.ts": "export function apply(ctx) { ctx.remote.session.list({}); }"})
    report = export_port(root, tmp_path / "ported-session-list")
    method = next(row for row in report["remotes"] if row["name"] == "session.list")
    assert method["suggestedContract"] == "context.session_controller.list_current_project"
    assert "当前项目" in method["difference"] and "全局" in method["difference"]
