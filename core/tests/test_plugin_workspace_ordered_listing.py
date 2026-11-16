"""user:“逐项核对固定上游源码及手册”+(工作区目录可选择有界稳定名称顺序)。"""
import asyncio
import os
from pathlib import Path

import pytest

from .test_plugin_working_directory import env


def reverse_scandir_for(monkeypatch, target):
    original = os.scandir

    class Entries:
        def __init__(self, entries):
            self.entries = iter(entries)

        def __enter__(self):
            return self.entries

        def __exit__(self, *_args):
            return False

    def scandir(path):
        if Path(path) != target:
            return original(path)
        with original(path) as entries:
            values = list(entries)
        return Entries(sorted(values, key=lambda item: item.name, reverse=True))

    monkeypatch.setattr(os, "scandir", scandir)


@pytest.mark.asyncio
async def test_ordered_listing_sorts_before_limit_and_preserves_default(env, monkeypatch):
    ctx, _, _, root = env
    target = root / "unordered"
    target.mkdir()
    for name in ("delta", "alpha", "charlie", "bravo"):
        (target / name).write_text(name, encoding="utf8")
    reverse_scandir_for(monkeypatch, target)
    api = ctx.workspace_files
    ordered = await api.list("s", "unordered", limit=2, ordered=True)
    assert [item["name"] for item in ordered["entries"]] == ["alpha", "bravo"]
    assert ordered["truncated"] is True
    raw = await api.list("s", "unordered", limit=2)
    assert [item["name"] for item in raw["entries"]] == ["delta", "charlie"]
    assert [item.name for item in ctx.filesystem.list_dir("unordered", limit=2).entries] == ["delta", "charlie"]


@pytest.mark.asyncio
async def test_ordered_listing_scan_limit_fails_without_partial_result(env, monkeypatch):
    from lamtools_core.plugin_system import filesystem_access

    ctx, _, _, root = env
    target = root / "unordered"
    target.mkdir()
    for name in ("d", "a", "c", "b"):
        (target / name).touch()
    monkeypatch.setattr(filesystem_access, "_ORDERED_LIST_SCAN_LIMIT", 3)
    with pytest.raises(ValueError) as error:
        await ctx.workspace_files.list("s", "unordered", limit=1, ordered=True)
    assert error.value.code == "fs/scan-limit"
    (target / "d").unlink()
    result = await ctx.workspace_files.list("s", "unordered", limit=2, ordered=True)
    assert [item["name"] for item in result["entries"]] == ["a", "b"] and result["truncated"]


@pytest.mark.asyncio
async def test_ordered_listing_uses_unicode_codepoint_order(env):
    ctx, _, _, root = env
    target = root / "unordered"
    target.mkdir()
    for name in ("中", "a", "Z"):
        (target / name).touch()
    result = await ctx.workspace_files.list("s", "unordered", limit=3, ordered=True)
    assert [item["name"] for item in result["entries"]] == ["Z", "a", "中"]
    assert result["truncated"] is False


@pytest.mark.asyncio
async def test_ordered_listing_repeated_cancel_waits_for_native_admission(env, monkeypatch):
    from lamtools_core.plugin_system.filesystem_access import PluginFilesystemAPI

    ctx, _, _, _ = env
    host = ctx.require_service("working_directory")
    original = host.call
    entered, cleaning, release, cleaned = (asyncio.Event() for _ in range(4))

    async def gated(*args, **kwargs):
        result = await original(*args, **kwargs)
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await release.wait()
            cleaned.set()
        return result

    def forbidden(*_args, **_kwargs):
        pytest.fail("cancelled session admission must not scan the directory")

    monkeypatch.setattr(host, "call", gated)
    monkeypatch.setattr(PluginFilesystemAPI, "_list_dir_ordered", forbidden)
    task = asyncio.create_task(ctx.workspace_files.list("s", ".", ordered=True))
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
@pytest.mark.parametrize("value", [1, "yes", None])
async def test_ordered_option_requires_boolean_before_directory_scan(env, monkeypatch, value):
    ctx, _, _, _ = env
    original = os.scandir

    def forbidden(path):
        if Path(path) == Path(ctx.work_root):
            pytest.fail("invalid option must not scan the workspace")
        return original(path)

    monkeypatch.setattr(os, "scandir", forbidden)
    with pytest.raises(ValueError):
        await ctx.workspace_files.list("s", ".", ordered=value)


@pytest.mark.asyncio
async def test_ordered_listing_uses_authenticated_remote_and_session_scope(env, monkeypatch, tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system import filesystem_access
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token

    ctx, _, _, root = env
    target = root / "unordered"
    target.mkdir()
    for name in ("c", "a", "b"):
        (target / name).touch()
    host, catalog, previous = _host(tmp_path)
    configure(host)
    ctx._secret_store = previous._secret_store
    host.backend_manager.context = ctx
    (host.get("hook-demo").root / "ops.py").write_text(
        "async def echo(request, *, context):\n"
        "    return await context.workspace_files.list(request.payload['body']['text'], 'unordered', limit=2, ordered=True)\n",
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
        with monkeypatch.context() as patch:
            patch.setattr(filesystem_access, "_ORDERED_LIST_SCAN_LIMIT", 2)
            limited = await client.post(url, json={"args": {"text": "s"}}, headers=headers)
    assert good.status_code == 200
    assert [item["name"] for item in good.json()["payload"]["entries"]] == ["a", "b"]
    assert hidden.status_code == 400 and denied.status_code == 401 and limited.status_code == 400


def test_migration_explains_bounded_ordered_listing(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port

    root = source(tmp_path, {"index.ts": "export function apply(ctx) { ctx.remote.workspaceFiles.list(); }"})
    report = export_port(root, tmp_path / "ported")
    row = next(item for item in report["remotes"] if item["name"] == "workspaceFiles.list")
    assert "ordered=True" in row["difference"] and "10000" in row["difference"]
    assert "ordered=True" in (tmp_path / "ported" / "PORTING.md").read_text(encoding="utf8")
