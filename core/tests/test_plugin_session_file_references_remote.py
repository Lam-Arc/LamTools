"""user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(文件引用按可见会话的原执行目录查找)。"""
import asyncio
import threading

import httpx
import pytest
from fastapi import FastAPI

from .test_plugin_working_directory import env
from .test_plugin_http_routes import _host
from .test_plugin_remote_gateway import configure
from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token


@pytest.mark.asyncio
async def test_candidates_use_session_execution_directory_and_hide_session(env):
    ctx, _, _, root = env
    (root / "outside.txt").write_text("outside")
    (root / "one" / "inside.txt").write_text("inside")
    state = await ctx.working_directory.get("s")
    await ctx.working_directory.set("s", "one", expected_revision=state.revision)
    result = await ctx.session_file_references.list("s", "txt")
    assert [item["path"] for item in result["items"]] == ["inside.txt"]
    with pytest.raises((ValueError, RuntimeError)):
        await ctx.session_file_references.list("hidden", "txt")


@pytest.mark.asyncio
async def test_visible_session_from_other_project_is_rejected(env, tmp_path):
    from lamtools_core.session import SessionRecord
    ctx, store, _, _ = env
    other = tmp_path / "other-project"
    other.mkdir()
    await store.create(SessionRecord("foreign", "core", "Foreign", "idle", metadata={"work_root": str(other)}))
    with pytest.raises(ValueError) as error:
        await ctx.session_file_references.list("foreign")
    assert error.value.code == "workspace-file/outside-workspace"


@pytest.mark.asyncio
@pytest.mark.parametrize("query,limit", [(None, 5), ("x" * 513, 5), ("\x00", 5), ("x", 0), ("x", True)])
async def test_invalid_query_does_not_request_session_admission(env, monkeypatch, query, limit):
    ctx, _, _, _ = env
    host = ctx.require_service("working_directory")
    def forbidden(*args, **kwargs): pytest.fail("invalid query must not enter original host")
    monkeypatch.setattr(host, "for_scope", forbidden)
    with pytest.raises(ValueError): await ctx.session_file_references.list("s", query, limit=limit)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["host", "scope", "root", "cancel"])
async def test_cancel_or_withdraw_waits_for_original_worker_and_discards_result(env, monkeypatch, change, tmp_path):
    from lamtools_core.plugin_system import content_access
    ctx, _, _, root = env
    (root / "file.txt").write_text("x")
    original = content_access.os.scandir
    entered, release = threading.Event(), threading.Event()
    def gated(path):
        entered.set()
        release.wait()
        return original(path)
    monkeypatch.setattr(content_access.os, "scandir", gated)
    api = ctx.session_file_references
    task = asyncio.create_task(api.list("s"))
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        if change == "host": ctx.set_service("working_directory", object())
        elif change == "scope": ctx._registration_scope.revoke()
        elif change == "root": ctx.work_root = tmp_path / "changed"
        else:
            task.cancel()
            await asyncio.sleep(0.02)
            assert not task.done()
        release.set()
        if change == "cancel":
            with pytest.raises(asyncio.CancelledError): await task
        else:
            with pytest.raises((ValueError, RuntimeError)): await task
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_actual_session_references_cross_explicit_http(env, tmp_path):
    ctx, _, _, root = env
    (root / "find.txt").write_text("x")
    host, catalog, original_context = _host(tmp_path)
    configure(host)
    ctx._secret_store = original_context._secret_store
    host.backend_manager.context = ctx
    (host.get("hook-demo").root / "ops.py").write_text(
        "async def echo(request, *, context):\n"
        "    return await context.session_file_references.list(request.payload['body']['text'], 'find')\n", encoding="utf8")
    catalog.unregister_owner("plugin:hook-demo")
    register_plugin_operations(catalog, host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        async def read(session):
            return await client.post("/plugin-remote/hook-demo/demo/echo", json={"args": {"text": session}},
                headers={"x-plugin-token": plugin_http_token(host, "hook-demo")})
        response = await read("s")
        assert response.status_code == 200 and response.json()["payload"]["items"][0]["path"] == "find.txt"
        assert (await read("hidden")).status_code == 400


def test_migration_handoff_identifies_session_based_file_candidates(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root = source(tmp_path, {"index.ts": "export function apply(ctx) { ctx.remote.fileReferences.list(); }"})
    report = export_port(root, tmp_path / "ported")
    item = next(row for row in report["remotes"] if row["name"] == "fileReferences.list")
    assert item["suggestedContract"] == "context.session_file_references.list"
    assert "执行目录" in item["difference"] and report["runtimeVerified"] is False
