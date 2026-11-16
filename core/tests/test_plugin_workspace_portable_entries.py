"""user:“逐项核对固定上游源码及手册”+(目录条目可选择有限的上游字段近似)。"""
import asyncio

import pytest

from .test_plugin_working_directory import env


@pytest.mark.asyncio
async def test_portable_entries_project_native_file_and_directory(env):
    ctx, _, _, root = env
    target = root / "one"
    (target / "folder").mkdir()
    (target / "item.txt").write_bytes(b"hello")
    api = ctx.workspace_files
    result = await api.list("s", "one", ordered=True, relative_path=True, portable_entries=True)
    assert result == {"path": "one", "entries": [
        {"name": "folder", "type": "directory"},
        {"name": "item.txt", "type": "file", "size": 5},
    ], "truncated": False}
    native = await api.list("s", "one", ordered=True)
    assert native["entries"][0]["kind"] == "directory" and "modified_ns" in native["entries"][0]
    assert native["entries"][1]["kind"] == "file" and native["entries"][1]["size"] == 5


@pytest.mark.asyncio
async def test_portable_entries_preserve_empty_file_size_and_empty_directory(env):
    ctx, _, _, root = env
    target = root / "one"
    (target / "empty.txt").touch()
    (target / "empty-dir").mkdir()
    listing = await ctx.workspace_files.list("s", "one", ordered=True, portable_entries=True)
    assert listing["entries"] == [
        {"name": "empty-dir", "type": "directory"},
        {"name": "empty.txt", "type": "file", "size": 0},
    ]
    empty = await ctx.workspace_files.list("s", "one/empty-dir", portable_entries=True)
    assert empty["entries"] == [] and empty["truncated"] is False


@pytest.mark.asyncio
async def test_portable_symlink_is_other_without_following_target(env, tmp_path):
    ctx, _, _, root = env
    outside = tmp_path / "outside-secret.txt"
    outside.write_bytes(b"outside-content")
    link = root / "one" / "outside-link"
    try:
        link.symlink_to(outside)
    except OSError as error:
        pytest.skip(f"native symlink creation unavailable: {type(error).__name__}")
    portable = await ctx.workspace_files.list("s", "one", portable_entries=True)
    assert portable["entries"] == [{"name": "outside-link", "type": "other"}]
    native = await ctx.workspace_files.list("s", "one")
    assert native["entries"][0]["kind"] == "link"
    with pytest.raises(ValueError):
        await ctx.workspace_files.read("s", "one/outside-link")


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [None, 1, "true"])
async def test_portable_entries_requires_boolean_before_native_admission(env, monkeypatch, value):
    ctx, _, _, _ = env

    async def forbidden(*_args, **_kwargs):
        pytest.fail("invalid option must not read a session")

    monkeypatch.setattr(ctx.require_service("working_directory"), "call", forbidden)
    with pytest.raises(ValueError):
        await ctx.workspace_files.list("s", "one", portable_entries=value)


@pytest.mark.asyncio
async def test_portable_entries_cancel_waits_for_original_final_admission(env, monkeypatch):
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
    task = asyncio.create_task(ctx.workspace_files.list("s", "one", portable_entries=True))
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
async def test_portable_entries_cross_authenticated_remote(env, tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token

    ctx, _, _, root = env
    (root / "one" / "item.txt").write_bytes(b"hello")
    host, catalog, previous = _host(tmp_path)
    configure(host)
    ctx._secret_store = previous._secret_store
    host.backend_manager.context = ctx
    (host.get("hook-demo").root / "ops.py").write_text(
        "async def echo(request, *, context):\n"
        "    return await context.workspace_files.list(request.payload['body']['text'], 'one', "
        "ordered=True, relative_path=True, portable_entries=True)\n", encoding="utf8")
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
    assert good.status_code == 200 and good.json()["payload"] == {
        "path": "one", "entries": [{"name": "item.txt", "type": "file", "size": 5}], "truncated": False}
    assert str(root) not in good.text and hidden.status_code == 400 and denied.status_code == 401


def test_migration_describes_portable_entries_and_link_difference(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port

    root = source(tmp_path, {"index.ts": "export function apply(ctx) { ctx.remote.workspaceFiles.list(); }"})
    report = export_port(root, tmp_path / "ported")
    row = next(item for item in report["remotes"] if item["name"] == "workspaceFiles.list")
    assert "portable_entries=True" in row["difference"] and "链接" in row["difference"]
    assert "portable_entries=True" in (tmp_path / "ported" / "PORTING.md").read_text(encoding="utf8")
