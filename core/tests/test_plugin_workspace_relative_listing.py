"""user:“逐项核对固定上游源码及手册”+(目录清单可返回相对于原会话执行目录的路径)。"""
import asyncio
from pathlib import Path

import pytest

from .test_plugin_working_directory import env


@pytest.mark.asyncio
async def test_relative_listing_uses_session_root_and_preserves_default_path(env):
    ctx, _, _, root = env
    nested = root / "one" / "中文 folder"
    nested.mkdir()
    (nested / "item.txt").write_text("data", encoding="utf8")
    api = ctx.workspace_files

    root_page = await api.list("s", ".", relative_path=True)
    assert root_page["path"] == "" and str(root) not in repr(root_page)
    nested_page = await api.list("s", str(nested), ordered=True, relative_path=True)
    assert nested_page["path"] == "one/中文 folder"
    assert [item["name"] for item in nested_page["entries"]] == ["item.txt"]
    default_page = await api.list("s", "one", ordered=True)
    assert Path(default_page["path"]) == root / "one"

    state = await ctx.working_directory.get("s")
    await ctx.working_directory.set("s", "one", expected_revision=state.revision)
    page = await api.list("s", "中文 folder", relative_path=True)
    assert page["path"] == "中文 folder" and str(root) not in repr(page)
    assert (await api.list("s", ".", relative_path=True))["path"] == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [None, 0, "true"])
async def test_relative_path_option_rejects_non_boolean_before_native_lookup(env, monkeypatch, value):
    ctx, _, _, _ = env

    async def forbidden(*_args, **_kwargs):
        pytest.fail("invalid option must not read a session")

    monkeypatch.setattr(ctx.require_service("working_directory"), "call", forbidden)
    with pytest.raises(ValueError):
        await ctx.workspace_files.list("s", ".", relative_path=value)


@pytest.mark.asyncio
async def test_relative_listing_keeps_original_session_and_directory_boundaries(env, tmp_path):
    ctx, _, _, root = env
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(RuntimeError):
        await ctx.workspace_files.list("hidden", ".", relative_path=True)
    with pytest.raises(ValueError):
        await ctx.workspace_files.list("s", str(outside), relative_path=True)
    with pytest.raises(ValueError):
        await ctx.workspace_files.list("s", "../outside", relative_path=True)
    assert (await ctx.workspace_files.list("s", str(root), relative_path=True))["path"] == ""


@pytest.mark.asyncio
async def test_relative_listing_cancel_waits_for_final_session_recheck(env, monkeypatch):
    ctx, _, _, _ = env
    host = ctx.require_service("working_directory")
    original = host.call
    entered, cleaning, release, cleaned = (asyncio.Event() for _ in range(4))
    calls = 0

    async def gated(*args, **kwargs):
        nonlocal calls
        result = await original(*args, **kwargs)
        calls += 1
        if calls == 2:
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaning.set()
                await release.wait()
                cleaned.set()
        return result

    monkeypatch.setattr(host, "call", gated)
    task = asyncio.create_task(ctx.workspace_files.list("s", "one", relative_path=True))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        task.cancel()
        await asyncio.wait_for(cleaning.wait(), 3)
        task.cancel()
        for _ in range(5):
            await asyncio.sleep(0)
        assert not task.done() and not ctx._registration_scope._idle.is_set()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cleaned.is_set() and ctx._registration_scope._idle.is_set()
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_relative_listing_crosses_authenticated_remote(env, tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token

    ctx, _, _, root = env
    (root / "one" / "item.txt").write_text("hello", encoding="utf8")
    host, catalog, previous = _host(tmp_path)
    configure(host)
    ctx._secret_store = previous._secret_store
    host.backend_manager.context = ctx
    (host.get("hook-demo").root / "ops.py").write_text(
        "async def echo(request, *, context):\n"
        "    return await context.workspace_files.list(request.payload['body']['text'], 'one', ordered=True, relative_path=True)\n",
        encoding="utf8")
    catalog.unregister_owner("plugin:hook-demo")
    register_plugin_operations(catalog, host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        url = "/plugin-remote/hook-demo/demo/echo"
        headers = {"x-plugin-token": plugin_http_token(host, "hook-demo")}
        good = await client.post(url, json={"args": {"text": "s"}}, headers=headers)
        hidden = await client.post(url, json={"args": {"text": "hidden"}}, headers=headers)
        denied = await client.post(url, json={"args": {"text": "s"}}, headers={"x-plugin-token": "wrong"})
    assert good.status_code == 200 and good.json()["payload"]["path"] == "one"
    assert str(root) not in good.text and hidden.status_code == 400 and denied.status_code == 401


def test_migration_describes_relative_listing_path(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port

    root = source(tmp_path, {"index.ts": "export function apply(ctx) { ctx.remote.workspaceFiles.list(); }"})
    report = export_port(root, tmp_path / "ported")
    row = next(item for item in report["remotes"] if item["name"] == "workspaceFiles.list")
    assert "relative_path=True" in row["difference"] and "relative_path=True" in (tmp_path / "ported" / "PORTING.md").read_text(encoding="utf8")
