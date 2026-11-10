"""user:“复用原宿主权威”+(调用方关闭尚未消费的流也须回收原提供方)。"""
import pytest
from lamtools_core.plugin_system.context import PluginContext
from lamtools_core.plugin_system.services import ServiceKey


@pytest.mark.asyncio
async def test_close_before_first_pull_closes_already_started_provider(tmp_path):
    closed = []
    class Provider:
        async def open(self):
            async def source():
                try:
                    yield 'setup'
                    yield 'event'
                finally:
                    closed.append(True)
            stream = source()
            assert await anext(stream) == 'setup'
            return stream
    ctx = PluginContext(tmp_path)
    ctx.set_service('stream-provider', Provider())
    ctx._begin_registration_scope('reader', 1)
    try:
        stream = await ctx.bind_service(ServiceKey('stream-provider')).call('open')
        await stream.aclose()
        assert closed == [True]
        with pytest.raises(StopAsyncIteration): await anext(stream)
        await stream.aclose()
        assert closed == [True]
    finally:
        await ctx._registration_scope.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('withdraw', [False, True])
async def test_first_public_event_and_withdrawal_cleanup(tmp_path, withdraw):
    from lamtools_core.plugin_system.services import ServiceError
    closed = []
    class Provider:
        async def open(self):
            async def source():
                try:
                    yield 'ready'
                    yield 'real-event'
                finally:
                    closed.append(True)
            stream = source()
            await anext(stream)
            return stream
    ctx = PluginContext(tmp_path)
    ctx.set_service('stream-provider', Provider())
    ctx._begin_registration_scope('reader', 1)
    stream = await ctx.bind_service(ServiceKey('stream-provider')).call('open')
    try:
        if withdraw:
            await ctx._registration_scope.dispose()
            with pytest.raises(ServiceError): await anext(stream)
        else:
            assert await anext(stream) == 'real-event'
            with pytest.raises(StopAsyncIteration): await anext(stream)
        assert closed == [True]
    finally:
        await stream.aclose()
        await ctx._registration_scope.dispose()


@pytest.mark.asyncio
async def test_wrapped_stream_crosses_real_ndjson_http(tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from .test_plugin_remote_binary import set_encoding
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
    closed = []
    class Provider:
        async def open(self):
            async def source():
                try:
                    yield {'message': 'actual'}
                finally:
                    closed.append(True)
            return source()
    host, catalog, ctx = _host(tmp_path)
    configure(host)
    set_encoding(host, 'ndjson')
    ctx.set_service('stream-provider', Provider())
    ctx._begin_registration_scope('hook-demo', 1)
    (host.get('hook-demo').root / 'ops.py').write_text(
        'from lamtools_core.app.operation_catalog import OperationResult\n'
        'async def echo(request, *, context):\n'
        "    stream = await context.bind_service('stream-provider').call('open')\n"
        '    return OperationResult(request.name, stream)\n', encoding='utf8')
    catalog.unregister_owner('plugin:hook-demo')
    register_plugin_operations(catalog, host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            response = await client.post('/plugin-remote/hook-demo/demo/echo', json={'args': {'text': 'x'}},
                headers={'x-plugin-token': plugin_http_token(host, 'hook-demo')})
        import json
        frames = [json.loads(line) for line in response.iter_lines()]
        assert response.status_code == 200
        assert frames == [{'kind': 'item', 'payload': {'message': 'actual'}}, {'kind': 'end'}]
        assert closed == [True] and not host._remote_stream_slots
    finally:
        await ctx._registration_scope.dispose()
