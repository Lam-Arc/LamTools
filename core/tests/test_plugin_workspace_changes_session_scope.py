"""user:“完成真实接口、参数/错误、作用域、取消/清理”+(会话不再可见或切换目录时停止原文件监听)。"""
import asyncio
import pytest
from .test_plugin_working_directory import env


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['hidden', 'directory'])
async def test_idle_stream_stops_when_session_scope_changes(env, change):
    ctx, store, _, root = env
    (root / 'one' / 'watch.txt').write_text('one')
    state = await ctx.working_directory.get('s')
    await ctx.working_directory.set('s', 'one', expected_revision=state.revision)
    stream = await ctx.workspace_files.changes('s', 'watch.txt', interval=0.01)
    try:
        assert (await anext(stream))['kind'] == 'ready'
        if change == 'hidden':
            store._session_visible = lambda sid, _: sid != 's'
        else:
            state = await ctx.working_directory.get('s')
            await ctx.working_directory.set('s', 'two', expected_revision=state.revision)
        await asyncio.wait_for(asyncio.shield(stream._watch._task), 2)
        with pytest.raises((ValueError, RuntimeError)): await anext(stream)
        assert not stream._fs._watches
        assert stream not in stream._state['streams']
    finally:
        await stream.aclose()


@pytest.mark.asyncio
async def test_ready_rechecks_session_before_first_frame(env):
    ctx, store, _, root = env
    (root / 'watch.txt').write_text('x')
    stream = await ctx.workspace_files.changes('s', 'watch.txt', interval=0.01)
    try:
        store._session_visible = lambda sid, _: sid != 's'
        with pytest.raises((ValueError, RuntimeError)): await anext(stream)
        assert stream._watch._task.done()
    finally:
        await stream.aclose()


@pytest.mark.asyncio
async def test_pending_pull_wakes_and_cleans_up_when_session_hidden(env):
    ctx, store, _, root = env
    (root / 'watch.txt').write_text('before')
    stream = await ctx.workspace_files.changes('s', 'watch.txt', interval=0.01)
    try:
        await anext(stream)
        pending = asyncio.create_task(anext(stream))
        await asyncio.sleep(0)
        store._session_visible = lambda sid, _: sid != 's'
        with pytest.raises((ValueError, RuntimeError)): await asyncio.wait_for(pending, 2)
        assert stream._watch._task.done()
    finally:
        await stream.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('disposal', ['close', 'scope'])
async def test_close_joins_session_guard_and_watch(env, disposal):
    ctx, _, _, root = env
    (root / 'watch.txt').write_text('before')
    stream = await ctx.workspace_files.changes('s', 'watch.txt', interval=0.01)
    await anext(stream)
    if disposal == 'scope': await ctx._registration_scope.dispose()
    else: await stream.aclose()
    assert stream._guard_task.done() and stream._watch._task.done()
    assert not stream._fs._watches


@pytest.mark.asyncio
async def test_authorized_change_still_arrives(env):
    ctx, _, _, root = env
    path = root / 'watch.txt'
    path.write_text('before')
    stream = await ctx.workspace_files.changes('s', 'watch.txt', interval=0.01)
    try:
        assert (await anext(stream))['kind'] == 'ready'
        path.write_text('longer after')
        frame = await asyncio.wait_for(anext(stream), 3)
        assert frame['kind'] == 'change' and frame['change']['bytes'] == len('longer after')
    finally:
        await stream.aclose()


@pytest.mark.asyncio
async def test_scope_disposal_waits_for_session_guard_cleanup(env, monkeypatch):
    ctx, _, _, root = env
    (root / 'watch.txt').write_text('x')
    stream = await ctx.workspace_files.changes('s', 'watch.txt', interval=0.01)
    entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    original = stream._validate_session
    async def gated():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await release.wait()
    await anext(stream)
    monkeypatch.setattr(stream, '_validate_session', gated)
    stopping = None
    try:
        await asyncio.wait_for(entered.wait(), 2)
        stopping = asyncio.create_task(ctx._registration_scope.dispose())
        await asyncio.wait_for(cleaning.wait(), 2)
        await asyncio.sleep(0.02)
        assert not stopping.done() and not stream._guard_task.done()
        release.set()
        await asyncio.wait_for(stopping, 2)
        assert stream._guard_task.done() and stream._watch._task.done()
    finally:
        release.set()
        if stopping is not None: await asyncio.gather(stopping, return_exceptions=True)
        monkeypatch.setattr(stream, '_validate_session', original)
        await stream.aclose()


@pytest.mark.asyncio
async def test_hidden_session_ends_real_http_stream(env, tmp_path):
    import json
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from .test_plugin_remote_binary import set_encoding
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
    ctx, store, _, root = env
    (root / 'watch.txt').write_text('x')
    host, catalog, original = _host(tmp_path)
    configure(host)
    set_encoding(host, 'ndjson')
    ctx._secret_store = original._secret_store
    host.backend_manager.context = ctx
    (host.get('hook-demo').root / 'ops.py').write_text(
        'from lamtools_core.app.operation_catalog import OperationResult\n'
        'async def echo(request, *, context):\n'
        "    return OperationResult(request.name, await context.workspace_files.changes('s', 'watch.txt', interval=0.01))\n", encoding='utf8')
    catalog.unregister_owner('plugin:hook-demo')
    register_plugin_operations(catalog, host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    done, frames, delivered = asyncio.Event(), [], False
    async def receive():
        nonlocal delivered
        if not delivered:
            delivered = True
            return {'type':'http.request','body':json.dumps({'args':{'text':'x'}}).encode(),'more_body':False}
        await done.wait()
        return {'type':'http.disconnect'}
    async def send(message):
        if message['type'] == 'http.response.body' and message.get('body'):
            frames.append(json.loads(message['body']))
            if len(frames) == 1: store._session_visible = lambda sid, _: sid != 's'
            if not message.get('more_body', False): done.set()
    token = plugin_http_token(host, 'hook-demo')
    scope = {'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':'POST',
        'scheme':'http','path':'/plugin-remote/hook-demo/demo/echo','query_string':b'',
        'headers':[(b'content-type',b'application/json'),(b'x-plugin-token',token.encode())],
        'client':('127.0.0.1',123),'server':('test',80)}
    try:
        async with asyncio.timeout(3): await app(scope, receive, send)
        assert frames[0]['payload']['kind'] == 'ready' and frames[-1]['kind'] == 'error'
        assert not host._remote_stream_slots and not ctx._registration_scope._workspace_file_changes['streams']
    finally:
        done.set()
