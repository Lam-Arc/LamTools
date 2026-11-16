"""user:“建立真实请求、错误、作用域、取消/流和清理验收”+(文件监听会话准入取消等待原读取和监听回收)。"""
import asyncio

import pytest

from .test_plugin_working_directory import env


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["open", "next"])
async def test_repeated_cancel_waits_for_watch_session_admission(env, monkeypatch, stage):
    ctx, _, _, root = env
    (root / "watch.txt").write_text("before", encoding="utf8")
    api = ctx.workspace_files
    stream = await api.changes("s", "watch.txt", interval=2) if stage == "next" else None
    host = ctx.require_service("working_directory")
    original = host.call
    entered, cleaning, release, cleaned = (asyncio.Event() for _ in range(4))

    async def gated(*args, **kwargs):
        value = await original(*args, **kwargs)
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await release.wait()
            cleaned.set()
        return value

    monkeypatch.setattr(host, "call", gated)
    task = asyncio.create_task(api.changes("s", "watch.txt", interval=2) if stream is None else anext(stream))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        task.cancel()
        await asyncio.wait_for(cleaning.wait(), 3)
        task.cancel()
        for _ in range(5):
            await asyncio.sleep(0)
        assert not task.done() and not ctx._registration_scope._idle.is_set()
        if stream is not None:
            assert not stream._watch._task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cleaned.is_set() and ctx._registration_scope._idle.is_set()
        if stream is not None:
            assert stream._watch._task.done() and not stream._fs._watches
        else:
            assert not getattr(ctx._registration_scope, "_workspace_file_changes", {}).get("streams")
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        if stream is not None:
            await stream.aclose()


@pytest.mark.asyncio
async def test_watch_real_change_and_hidden_session_still_use_native_authority(env):
    ctx, _, _, root = env
    path = root / "watch.txt"
    path.write_text("before", encoding="utf8")
    with pytest.raises(RuntimeError):
        await ctx.workspace_files.changes("hidden", "watch.txt")
    stream = await ctx.workspace_files.changes("s", "watch.txt", interval=0.01)
    try:
        assert await anext(stream) == {"kind": "ready"}
        path.write_text("changed", encoding="utf8")
        frame = await asyncio.wait_for(anext(stream), 3)
        assert frame["kind"] == "change" and frame["change"]["bytes"] == 7
    finally:
        await stream.aclose()
    assert stream._watch._task.done()


@pytest.mark.asyncio
async def test_real_remote_cancel_waits_for_watch_open_admission(env, monkeypatch, tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from .test_plugin_remote_binary import set_encoding
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token

    ctx, _, _, root = env
    (root / "watch.txt").write_text("before", encoding="utf8")
    host, catalog, previous = _host(tmp_path)
    configure(host)
    set_encoding(host, "ndjson")
    ctx._secret_store = previous._secret_store
    host.backend_manager.context = ctx
    (host.get("hook-demo").root / "ops.py").write_text(
        "from lamtools_core.app.operation_catalog import OperationResult\n"
        "async def echo(request, *, context):\n"
        "    return OperationResult(request.name, await context.workspace_files.changes('s', 'watch.txt'))\n",
        encoding="utf8")
    catalog.unregister_owner("plugin:hook-demo")
    register_plugin_operations(catalog, host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    session_host = ctx.require_service("working_directory")
    original = session_host.call
    entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def gated(*args, **kwargs):
        value = await original(*args, **kwargs)
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await release.wait()
        return value

    monkeypatch.setattr(session_host, "call", gated)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        task = asyncio.create_task(client.post("/plugin-remote/hook-demo/demo/echo", json={"args": {"text": "s"}},
            headers={"x-plugin-token": plugin_http_token(host, "hook-demo")}))
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
            assert ctx._registration_scope._idle.is_set() and not host._remote_stream_slots
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_scope_disposal_waits_for_cancelled_watch_open_read(env, monkeypatch):
    ctx, _, _, root = env
    (root / "watch.txt").write_text("before", encoding="utf8")
    host = ctx.require_service("working_directory")
    original = host.call
    entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def gated(*args, **kwargs):
        value = await original(*args, **kwargs)
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await release.wait()
        return value

    monkeypatch.setattr(host, "call", gated)
    task = asyncio.create_task(ctx.workspace_files.changes("s", "watch.txt"))
    disposal = None
    try:
        await asyncio.wait_for(entered.wait(), 3)
        task.cancel()
        await asyncio.wait_for(cleaning.wait(), 3)
        task.cancel()
        disposal = asyncio.create_task(ctx._registration_scope.dispose())
        await asyncio.sleep(0)
        assert not task.done() and not disposal.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        await disposal
        assert ctx._registration_scope._idle.is_set()
    finally:
        release.set()
        await asyncio.gather(task, *(tuple([disposal]) if disposal else ()), return_exceptions=True)


@pytest.mark.asyncio
async def test_watch_close_waits_for_guard_session_read_cleanup(env, monkeypatch):
    ctx, _, _, root = env
    (root / "watch.txt").write_text("before", encoding="utf8")
    stream = await ctx.workspace_files.changes("s", "watch.txt", interval=0.01)
    host = ctx.require_service("working_directory")
    original = host.call
    entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def gated(*args, **kwargs):
        value = await original(*args, **kwargs)
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await release.wait()
        return value

    monkeypatch.setattr(host, "call", gated)
    close = None
    try:
        await asyncio.wait_for(entered.wait(), 3)
        close = asyncio.create_task(stream.aclose())
        await asyncio.wait_for(cleaning.wait(), 3)
        close.cancel()
        close.cancel()
        await asyncio.sleep(0)
        assert not close.done() and not ctx._registration_scope._idle.is_set()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await close
        assert stream._watch._task.done() and not stream._fs._watches
    finally:
        release.set()
        if close is not None:
            await asyncio.gather(close, return_exceptions=True)
        await stream.aclose()


def test_migration_records_watch_admission_cleanup(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port

    root = source(tmp_path, {"index.ts": "export function apply(ctx) { ctx.remote.workspaceFiles.changes(); }"})
    export_port(root, tmp_path / "ported")
    assert "文件监听准入重复取消" in (tmp_path / "ported" / "PORTING.md").read_text(encoding="utf8")
