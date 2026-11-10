"""user:“完成真实接口、参数/错误、作用域、取消/清理”+(撤回时停止等待中的服务流并回收提供方)。"""
import asyncio
import pytest
from lamtools_core.plugin_system.context import PluginContext
from lamtools_core.plugin_system.services import ServiceError


@pytest.mark.asyncio
async def test_requester_revocation_interrupts_pending_stream_and_cleans_up(tmp_path):
    entered, cleaned = asyncio.Event(), asyncio.Event()
    class Provider:
        async def follow(self):
            try:
                entered.set()
                await asyncio.Event().wait()
                yield 'unreachable'
            finally:
                cleaned.set()
    ctx = PluginContext(tmp_path)
    ctx.set_service('source', Provider())
    ctx._begin_registration_scope('reader', 1)
    stream = await ctx.bind_service('source').call('follow')
    pending = asyncio.create_task(anext(stream))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        await ctx._registration_scope.dispose()
        with pytest.raises(ServiceError) as error:
            await asyncio.wait_for(pending, 1)
        assert error.value.code == 'service/requester-stopped'
        assert cleaned.is_set()
    finally:
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
        await stream.aclose()


@pytest.mark.asyncio
async def test_provider_revocation_interrupts_pending_stream(tmp_path):
    from .test_plugin_owned_services import handle
    from lamtools_core.plugin_system.lifecycle import start_plugin_backend, stop_plugin_backend
    entered, cleaned = asyncio.Event(), asyncio.Event()
    class Provider:
        async def follow(self):
            try:
                entered.set()
                await asyncio.Event().wait()
                yield 'unreachable'
            finally:
                cleaned.set()
    root = PluginContext(tmp_path)
    plugin = handle(root, 'provider', lambda ctx: ctx.register_service('source', Provider()))
    await start_plugin_backend(plugin, root)
    reader = root.for_work_root(tmp_path)
    reader._begin_registration_scope('reader', 1)
    stream = await reader.bind_service('source').call('follow')
    pending = asyncio.create_task(anext(stream))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        await stop_plugin_backend(plugin)
        with pytest.raises(ServiceError) as error: await asyncio.wait_for(pending, 1)
        assert error.value.code == 'service/unavailable' and cleaned.is_set()
    finally:
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
        await stream.aclose()
        await reader._registration_scope.dispose()


@pytest.mark.asyncio
async def test_repeated_cancellation_waits_for_provider_cleanup(tmp_path):
    entered, cleanup_started, release, cleaned = (asyncio.Event() for _ in range(4))
    class Provider:
        async def follow(self):
            try:
                entered.set()
                await asyncio.Event().wait()
                yield 'unreachable'
            finally:
                cleanup_started.set()
                await release.wait()
                cleaned.set()
    ctx = PluginContext(tmp_path)
    ctx.set_service('source', Provider())
    ctx._begin_registration_scope('reader', 1)
    stream = await ctx.bind_service('source').call('follow')
    pending = asyncio.create_task(anext(stream))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        pending.cancel()
        await asyncio.wait_for(cleanup_started.wait(), 2)
        pending.cancel()
        await asyncio.sleep(0)
        assert not pending.done() and not cleaned.is_set()
        release.set()
        with pytest.raises(asyncio.CancelledError): await asyncio.wait_for(pending, 2)
        assert cleaned.is_set()
    finally:
        release.set()
        await asyncio.gather(pending, return_exceptions=True)
        await stream.aclose()
        await ctx._registration_scope.dispose()


@pytest.mark.asyncio
async def test_normal_frames_and_completion_remain_unchanged(tmp_path):
    class Provider:
        async def follow(self):
            yield 'one'
            yield 'two'
    ctx = PluginContext(tmp_path)
    ctx.set_service('source', Provider())
    ctx._begin_registration_scope('reader', 1)
    stream = await ctx.bind_service('source').call('follow')
    try:
        assert [item async for item in stream] == ['one', 'two']
    finally:
        await stream.aclose()
        await ctx._registration_scope.dispose()


@pytest.mark.asyncio
async def test_requester_revocation_ends_real_http_stream(tmp_path):
    import json
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from .test_plugin_remote_binary import set_encoding
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
    closed, done = asyncio.Event(), asyncio.Event()
    class Provider:
        async def follow(self):
            try:
                yield {'state': 'opened'}
                await asyncio.Event().wait()
            finally:
                closed.set()
    host, catalog, ctx = _host(tmp_path)
    configure(host)
    set_encoding(host, 'ndjson')
    ctx.set_service('source', Provider())
    ctx._begin_registration_scope('hook-demo', 1)
    (host.get('hook-demo').root / 'ops.py').write_text(
        'from lamtools_core.app.operation_catalog import OperationResult\n'
        'async def echo(request, *, context):\n'
        "    return OperationResult(request.name, await context.bind_service('source').call('follow'))\n", encoding='utf8')
    catalog.unregister_owner('plugin:hook-demo')
    register_plugin_operations(catalog, host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    frames, delivered = [], False
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
            if len(frames) == 1: ctx._registration_scope.revoke()
            if not message.get('more_body', False): done.set()
    token = plugin_http_token(host, 'hook-demo')
    scope = {'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':'POST',
        'scheme':'http','path':'/plugin-remote/hook-demo/demo/echo','query_string':b'',
        'headers':[(b'content-type',b'application/json'),(b'x-plugin-token',token.encode())],
        'client':('127.0.0.1',123),'server':('test',80)}
    try:
        async with asyncio.timeout(2): await app(scope, receive, send)
        assert frames[0]['payload']['state'] == 'opened'
        assert frames[-1]['kind'] == 'error' and closed.is_set()
        assert not host._remote_stream_slots
    finally:
        done.set()
        await ctx._registration_scope.dispose()


from .test_plugin_session_control import host


@pytest.mark.asyncio
async def test_pending_original_session_follow_ends_on_requester_revocation(host, tmp_path):
    from lamtools_core.app.plugin_sessions import install_plugin_session_services
    from lamtools_core.plugin_system.sessions import SESSIONS
    live, original = host
    await original.create(session_id='s')
    ctx = PluginContext(tmp_path)
    service = install_plugin_session_services(ctx, lambda: live)
    ctx._begin_registration_scope('reader', 1)
    stream = await ctx.bind_service(SESSIONS).call('follow', 's', after_seq=1)
    pending = asyncio.create_task(anext(stream))
    try:
        await asyncio.sleep(0.03)
        await ctx._registration_scope.dispose()
        with pytest.raises(ServiceError) as error: await asyncio.wait_for(pending, 1)
        assert error.value.code == 'service/requester-stopped'
        assert (await service.state('s')).session_id == 's'
    finally:
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
        await stream.aclose()
        service.shutdown()
