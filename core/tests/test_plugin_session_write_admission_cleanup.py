"""user:“建立真实请求、错误、作用域、取消/流和清理验收”+(会话控制准入重复取消等待原读取清理)。"""
import asyncio

import pytest

from .test_plugin_working_directory import env


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["prompt", "queue", "cancel", "fork", "model"])
async def test_write_admission_repeated_cancel_waits_before_dispatch(env, monkeypatch, method):
    ctx, store, _, _ = env
    api = ctx.session_controller
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

    async def forbidden(*args, **kwargs):
        pytest.fail("cancelled admission must not dispatch a session operation")

    monkeypatch.setattr(host, "call", gated)
    monkeypatch.setattr(api._sessions, "call", forbidden)
    if method == "prompt":
        call = api.prompt("s", request_id="not-dispatched", text="hello")
    elif method == "queue":
        call = api.update_queue("s", "queue-id", text="hello")
    elif method == "cancel":
        call = api.cancel("s")
    elif method == "fork":
        call = api.fork("s", new_session_id="not-created")
    else:
        call = api.select_model("s", "model-id", expected_revision=0)
    task = asyncio.create_task(call)
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
        assert await store.get_readonly("not-created") is None
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_post_prompt_admission_cancel_waits_and_keeps_original_commit(env, monkeypatch):
    ctx, _, _, _ = env
    api = ctx.session_controller
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
    task = asyncio.create_task(api.prompt("s", request_id="committed-before-cancel", text="hello"))
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
        assert (await api.state("s")).queued_count == 1
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_authenticated_remote_cancel_waits_for_session_admission(env, monkeypatch, tmp_path):
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
        "    return await context.session_controller.prompt('s', request_id='not-dispatched', text='hello')\n",
        encoding="utf8")
    catalog.unregister_owner("plugin:hook-demo")
    register_plugin_operations(catalog, host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    directory = ctx.require_service("working_directory")
    original = directory.call
    entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def gated(*args, **kwargs):
        result = await original(*args, **kwargs)
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await release.wait()
        return result

    monkeypatch.setattr(directory, "call", gated)
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
            assert ctx._registration_scope._idle.is_set()
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_scope_disposal_waits_for_cancelled_session_admission(env, monkeypatch):
    ctx, _, _, _ = env
    api = ctx.session_controller
    host = ctx.require_service("working_directory")
    original = host.call
    entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def gated(*args, **kwargs):
        result = await original(*args, **kwargs)
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await release.wait()
        return result

    monkeypatch.setattr(host, "call", gated)
    task = asyncio.create_task(api.prompt("s", request_id="not-dispatched", text="hello"))
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
async def test_normal_prompt_still_uses_visible_native_session(env):
    ctx, _, _, _ = env
    api = ctx.session_controller
    with pytest.raises(RuntimeError):
        await api.prompt("hidden", request_id="hidden", text="hello")
    result = await api.prompt("s", request_id="visible", text="hello")
    assert result.accepted and (await api.state("s")).queued_count == 1


def test_migration_records_session_control_admission_cleanup(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port

    root = source(tmp_path, {"index.ts": "export function apply(ctx) { ctx.remote.session.prompt(); }"})
    export_port(root, tmp_path / "ported")
    assert "会话控制准入重复取消" in (tmp_path / "ported" / "PORTING.md").read_text(encoding="utf8")
