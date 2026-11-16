"""user:“建立真实请求、错误、作用域、取消/流和清理验收”+(上传会话读取重复取消等待原清理)。"""
import asyncio

import pytest

from .test_plugin_session_data import env


class UploadSource:
    def __init__(self):
        self.pulls = 0
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        self.pulls += 1
        if self.pulls == 1:
            return b"a"
        raise StopAsyncIteration

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["initial", "chunk"])
async def test_chunk_session_read_repeated_cancel_waits_before_source_close(env, monkeypatch, stage):
    ctx, _, _, _ = env
    host = ctx.require_service("session_data")
    original = host._read
    entered, cleaning, release, cleaned = asyncio.Event(), asyncio.Event(), asyncio.Event(), asyncio.Event()
    calls = 0
    source = UploadSource()

    async def gated(*args, **kwargs):
        nonlocal calls
        result = await original(*args, **kwargs)
        calls += 1
        if calls == (1 if stage == "initial" else 2):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaning.set()
                await release.wait()
                cleaned.set()
        return result

    monkeypatch.setattr(host, "_read", gated)
    task = asyncio.create_task(ctx.file_uploads.save_chunks("s", filename="cancel.bin", source=source, size=1))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        task.cancel()
        await asyncio.wait_for(cleaning.wait(), 3)
        task.cancel()
        for _ in range(5):
            await asyncio.sleep(0)
        assert not task.done() and not ctx._registration_scope._idle.is_set()
        assert not source.closed
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cleaned.is_set() and source.closed and ctx._registration_scope._idle.is_set()
        assert not (await ctx.attachments.list("s"))["items"]
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["encoded", "chunks"])
async def test_post_commit_lookup_repeated_cancel_waits_and_preserves_attachment(env, monkeypatch, method):
    ctx, _, _, _ = env
    host = ctx.require_service("session_data")
    original = host.call
    entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    saved = []
    source = UploadSource()

    async def gated(*args, **kwargs):
        result = await original(*args, **kwargs)
        if args[3] == "create":
            saved.append(result)
        elif args[3] == "get":
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaning.set()
                await release.wait()
        return result

    monkeypatch.setattr(host, "call", gated)
    call = (ctx.file_uploads.save_encoded("s", filename="saved.bin", content_base64="YQ==")
            if method == "encoded" else ctx.file_uploads.save_chunks("s", filename="saved.bin", source=source, size=1))
    task = asyncio.create_task(call)
    try:
        await asyncio.wait_for(entered.wait(), 3)
        assert saved
        task.cancel()
        await asyncio.wait_for(cleaning.wait(), 3)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done() and not ctx._registration_scope._idle.is_set()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert ctx._registration_scope._idle.is_set()
        assert any(item["id"] == saved[0]["id"] for item in (await ctx.attachments.list("s"))["items"])
        if method == "chunks":
            assert source.closed
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_real_remote_cancel_waits_for_post_commit_lookup(env, monkeypatch, tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token

    ctx, _, _, _ = env
    host, catalog, previous = _host(tmp_path)
    configure(host)
    ctx._secret_store = previous._secret_store
    host.backend_manager.context = ctx
    (host.get("hook-demo").root / "ops.py").write_text(
        "async def echo(request, *, context):\n"
        "    return await context.file_uploads.save_encoded('s', filename='remote.bin', content_base64='YQ==')\n",
        encoding="utf8")
    catalog.unregister_owner("plugin:hook-demo")
    register_plugin_operations(catalog, host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    session_host = ctx.require_service("session_data")
    original = session_host.call
    entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    saved = []

    async def gated(*args, **kwargs):
        result = await original(*args, **kwargs)
        if args[3] == "create":
            saved.append(result)
        elif args[3] == "get":
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaning.set()
                await release.wait()
        return result

    monkeypatch.setattr(session_host, "call", gated)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        task = asyncio.create_task(client.post("/plugin-remote/hook-demo/demo/echo", json={"args": {"text": "s"}},
            headers={"x-plugin-token": plugin_http_token(host, "hook-demo")}))
        try:
            await asyncio.wait_for(entered.wait(), 3)
            task.cancel()
            await asyncio.wait_for(cleaning.wait(), 3)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done() and not ctx._registration_scope._idle.is_set()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert saved and any(item["id"] == saved[0]["id"] for item in (await ctx.attachments.list("s"))["items"])
            assert ctx._registration_scope._idle.is_set()
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_normal_uploads_still_use_original_attachment_store(env):
    from pathlib import Path

    ctx, _, _, _ = env
    source = UploadSource()
    chunked = await ctx.file_uploads.save_chunks("s", filename="chunked.bin", source=source, size=1)
    encoded = await ctx.file_uploads.save_encoded("s", filename="encoded.bin", content_base64="YQ==")
    assert source.closed and Path(chunked["path"]).read_bytes() == Path(encoded["path"]).read_bytes() == b"a"
    with pytest.raises(RuntimeError):
        await ctx.file_uploads.save_encoded("hidden", filename="hidden.bin", content_base64="YQ==")


def test_migration_records_upload_read_cleanup(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port

    root = source(tmp_path, {"index.ts": "export function apply(ctx) { ctx.fileUploads.upload(); }"})
    export_port(root, tmp_path / "ported")
    assert "上传会话读取重复取消" in (tmp_path / "ported" / "PORTING.md").read_text(encoding="utf8")
