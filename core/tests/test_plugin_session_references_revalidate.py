"""user:“完成真实接口、参数/错误、作用域、取消/清理”+(会话隐藏或执行目录改变后不能返回旧目录文件)。"""
import asyncio
import threading
import pytest
from .test_plugin_working_directory import env


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['hidden', 'directory'])
async def test_scan_cannot_publish_after_session_changes(env, monkeypatch, change):
    from lamtools_core.plugin_system import content_access
    ctx, store, _, root = env
    (root / 'one' / 'old-secret.txt').write_text('old')
    state = await ctx.working_directory.get('s')
    await ctx.working_directory.set('s', 'one', expected_revision=state.revision)
    original = content_access.os.scandir
    entered, release = threading.Event(), threading.Event()
    def gated(path):
        entered.set()
        release.wait()
        return original(path)
    monkeypatch.setattr(content_access.os, 'scandir', gated)
    task = asyncio.create_task(ctx.session_file_references.list('s', 'secret'))
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        if change == 'hidden':
            store._session_visible = lambda sid, _: sid != 's'
        else:
            state = await ctx.working_directory.get('s')
            await ctx.working_directory.set('s', 'two', expected_revision=state.revision)
        release.set()
        with pytest.raises((ValueError, RuntimeError)): await task
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_unchanged_session_returns_real_candidates(env):
    ctx, _, _, root = env
    (root / 'visible.txt').write_text('x')
    result = await ctx.session_file_references.list('s', 'visible')
    assert [item['path'] for item in result['items']] == ['visible.txt']


@pytest.mark.asyncio
async def test_cancellation_during_final_session_check_releases_scope(env, monkeypatch):
    ctx, store, _, root = env
    (root / 'visible.txt').write_text('x')
    original = store.get_readonly_revision
    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0
    async def gated(sid):
        nonlocal calls
        calls += 1
        result = await original(sid)
        if calls == 2:
            entered.set()
            await release.wait()
        return result
    monkeypatch.setattr(store, 'get_readonly_revision', gated)
    task = asyncio.create_task(ctx.session_file_references.list('s', 'visible'))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
        assert not ctx._registration_scope._calls
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_hidden_during_scan_is_not_returned_over_http(env, tmp_path, monkeypatch):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system import content_access
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
    ctx, store, _, root = env
    (root / 'secret.txt').write_text('x')
    original = content_access.os.scandir
    entered, release = threading.Event(), threading.Event()
    def gated(path):
        if str(path) == str(root):
            entered.set()
            release.wait()
        return original(path)
    monkeypatch.setattr(content_access.os, 'scandir', gated)
    host, catalog, previous = _host(tmp_path)
    configure(host)
    ctx._secret_store = previous._secret_store
    host.backend_manager.context = ctx
    (host.get('hook-demo').root / 'ops.py').write_text(
        "async def echo(request, *, context):\n    return await context.session_file_references.list('s', 'secret')\n", encoding='utf8')
    catalog.unregister_owner('plugin:hook-demo')
    register_plugin_operations(catalog, host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            task = asyncio.create_task(client.post('/plugin-remote/hook-demo/demo/echo', json={'args': {'text': 'x'}},
                headers={'x-plugin-token': plugin_http_token(host, 'hook-demo')}))
            assert await asyncio.to_thread(entered.wait, 3)
            store._session_visible = lambda sid, _: sid != 's'
            release.set()
            response = await asyncio.wait_for(task, 3)
        assert response.status_code == 400 and 'secret.txt' not in response.text
    finally:
        release.set()
