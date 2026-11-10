"""user:“第二阶段结束后 就继续开展第三阶段”+(真实会话写入经原宿主和显式HTTP验收)。"""
import httpx
import json
import pytest
from fastapi import FastAPI
from .test_plugin_session_control import host, append
from .test_plugin_http_routes import _host
from .test_plugin_remote_gateway import configure
from lamtools_core.app.plugin_sessions import install_plugin_session_services
from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token


@pytest.mark.asyncio
async def test_prompt_queue_mutation_and_cancel_cross_real_http(host, tmp_path):
    live, service = host
    await service.create(session_id='s')
    plugin_host, catalog, ctx = _host(tmp_path)
    configure(plugin_host)
    manifest = plugin_host.get('hook-demo').root / 'plugin.json'
    spec = json.loads(manifest.read_text(encoding='utf8'))
    spec['http']['remote'][0]['argsSchema']['properties']['item'] = {'type': 'string'}
    spec['http']['remote'][0]['argsSchema']['required'].append('item')
    manifest.write_text(json.dumps(spec), encoding='utf8')
    plugin_host._invalidate()
    installed = install_plugin_session_services(ctx, lambda: live)
    ctx._begin_registration_scope('hook-demo', 1)
    (plugin_host.get('hook-demo').root / 'ops.py').write_text(
        'from lamtools_core.app.operation_catalog import OperationResult\n'
        'from lamtools_core.plugin_system.sessions import SESSIONS\n'
        'async def echo(request, *, context):\n'
        "    body = request.payload['body']\n"
        "    op = body['text']\n"
        "    api = context.bind_service(SESSIONS)\n"
        "    if op == 'prompt': value = await api.call('prompt', 's', request_id=body['item'] or 'r', text='hello')\n"
        "    elif op == 'update': value = await api.call('update_queue', 's', body['item'], text='changed')\n"
        "    elif op == 'delete': value = await api.call('update_queue', 's', body['item'], delete=True)\n"
        "    elif op == 'cancel': value = await api.call('cancel', 's')\n"
        "    else: raise ValueError('bad operation')\n"
        '    return OperationResult(request.name, value)\n', encoding='utf8')
    catalog.unregister_owner('plugin:hook-demo')
    register_plugin_operations(catalog, plugin_host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: plugin_host, lambda: catalog))
    headers = {'x-plugin-token': plugin_http_token(plugin_host, 'hook-demo')}
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            async def call(body, headers=headers):
                return await client.post('/plugin-remote/hook-demo/demo/echo', json={'args': {'item': '', **body}}, headers=headers)
            denied = await call({'text': 'prompt'}, {'x-plugin-token': 'wrong'})
            assert denied.status_code in (401, 403), denied.text
            assert (await service.state('s')).queued_count == 0
            first = await call({'text': 'prompt'})
            assert first.status_code == 200
            receipt = first.json()['payload']
            assert receipt['accepted'] and not receipt['completed'] and receipt['queue_item_id']
            retry = await call({'text': 'prompt'})
            assert retry.json()['payload']['event_seq'] == receipt['event_seq']
            update = await call({'text': 'update', 'item': receipt['queue_item_id']})
            assert update.status_code == 200 and update.json()['payload']['applied']
            cancel = await call({'text': 'cancel'})
            assert cancel.status_code == 200 and cancel.json()['payload']['status'] == 'idle'
            assert (await service.state('s')).queued_count == 1
            events = await service.events('s')
            assert len([e for e in events.events if e['method'] == 'queue/itemAccepted']) == 1
            edited = [e for e in events.events if e['method'] == 'queue/itemUpdated']
            assert edited[-1]['payload']['input'][0]['text'] == 'changed'
            deleted = await call({'text': 'delete', 'item': receipt['queue_item_id']})
            assert deleted.status_code == 200 and deleted.json()['payload']['applied']
            assert (await service.state('s')).queued_count == 0
            await append(live, 's', 'turn/started', {'status': 'running', 'type': 'turn'}, 'turn-a')
            live.host.runtime_task_registry.accept_run('s', 'run-a', turn_id='turn-a')
            assert (await call({'text': 'prompt', 'item': 'next'})).status_code == 200
            active_cancel = await call({'text': 'cancel'})
            assert active_cancel.status_code == 200
            assert active_cancel.json()['payload']['status'] == 'cancelling'
            assert not active_cancel.json()['payload']['completed']
            assert (await service.state('s')).queued_count == 1
    finally:
        installed.shutdown()
        await ctx._registration_scope.dispose()
