"""user:“建立真实请求、错误、作用域、取消/流和清理验收”+(验证受管插件内的嵌套资源读取)。"""
import asyncio
import json

import pytest

from .test_plugin_explicit_resources import resource_env
from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
from lamtools_core.plugin_system.plugin_http import plugin_http_token


@pytest.mark.asyncio
async def test_managed_plugin_operation_reads_own_resource_and_stops(resource_env):
    host, catalog, _ = resource_env
    root = host.get('hook-demo').root
    path = root / 'plugin.json'
    manifest = json.loads(path.read_text(encoding='utf8'))
    manifest['backend'] = './backend.py'
    manifest['operations'].append({'name': 'hook-demo.read', 'handler': 'ops:read', 'permission': 'auto_allow'})
    path.write_text(json.dumps(manifest), encoding='utf8')
    (root / 'backend.py').write_text('class Runtime:\n    async def start(self, context): pass\n    async def stop(self): pass\ndef create_plugin(context): return Runtime()\n', encoding='utf8')
    with (root / 'ops.py').open('a', encoding='utf8') as stream:
        stream.write("async def read(request, *, context):\n    result = await context.plugin_resources.read('/a/b/c')\n    return {'body': result['body'], 'status': result['status']}\n")
    host._invalidate()
    catalog.unregister_owner('plugin:hook-demo')
    register_plugin_operations(catalog, host)
    catalog.plugin_system_host = host
    host.backend_manager.context.operation_catalog = catalog
    plugin_http_token(host, 'hook-demo')
    assert await host.backend_manager.start('hook-demo')
    handle = host.backend_manager.get('hook-demo')
    try:
        result = await asyncio.wait_for(catalog.execute('hook-demo.read'), 3)
        assert result.status == 'ok' and result.payload == {'body': b'exact', 'status': 200}
        assert host.backend_manager._active['hook-demo'] == 0
        assert not host._remote_stream_slots and handle.context._registration_scope._idle.is_set()
    finally:
        await host.backend_manager.stop('hook-demo')
    assert not host.backend_manager.get('hook-demo')


@pytest.mark.asyncio
async def test_managed_stop_joins_inflight_nested_resource_cleanup(resource_env):
    host, catalog, _ = resource_env
    root = host.get('hook-demo').root
    path = root / 'plugin.json'
    manifest = json.loads(path.read_text(encoding='utf8'))
    manifest['backend'] = './backend.py'
    manifest['operations'].append({'name': 'hook-demo.read', 'handler': 'ops:read', 'permission': 'auto_allow'})
    path.write_text(json.dumps(manifest), encoding='utf8')
    (root / 'backend.py').write_text('class Runtime:\n    async def start(self, context): pass\n    async def stop(self): pass\ndef create_plugin(context): return Runtime()\n', encoding='utf8')
    (root / 'ops.py').write_text("async def exact(request, *, context):\n    entered, cleaning, release, closed = context.service('test.events')\n    entered.set()\n    try: await release.wait()\n    finally:\n        cleaning.set()\n        await release.wait()\n        closed.set()\n    return {'content': b'old', 'mime_type': 'text/plain'}\nasync def read(request, *, context):\n    return await context.plugin_resources.read('/a/b/c')\n", encoding='utf8')
    host._invalidate()
    catalog.unregister_owner('plugin:hook-demo')
    register_plugin_operations(catalog, host)
    catalog.plugin_system_host = host
    context = host.backend_manager.context
    context.operation_catalog = catalog
    entered, cleaning, release, closed = events = tuple(asyncio.Event() for _ in range(4))
    context.services['test.events'] = events
    plugin_http_token(host, 'hook-demo')
    assert await host.backend_manager.start('hook-demo')
    handle = host.backend_manager.get('hook-demo')
    call = asyncio.create_task(catalog.execute('hook-demo.read'))
    stop = None
    try:
        await asyncio.wait_for(entered.wait(), 3)
        stop = asyncio.create_task(host.backend_manager.stop('hook-demo'))
        await asyncio.wait_for(cleaning.wait(), 3)
        assert not stop.done() and not closed.is_set()
        release.set()
        result = await asyncio.wait_for(call, 3)
        await asyncio.wait_for(stop, 3)
        assert result.status == 'error' and b'old' not in str(result.payload).encode()
        assert closed.is_set() and handle.context._registration_scope.disposed
        assert host.backend_manager._active['hook-demo'] == 0 and not host._remote_stream_slots
    finally:
        release.set()
        if not call.done(): call.cancel()
        await asyncio.gather(call, return_exceptions=True)
        if stop is not None: await asyncio.gather(stop, return_exceptions=True)
        elif host.backend_manager.get('hook-demo'): await host.backend_manager.stop('hook-demo')
