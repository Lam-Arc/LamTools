"""user:“第二阶段结束后 就继续开展第三阶段”+(外部进程调用失败不能假定副作用已回滚)。"""
import json
import pytest
import httpx
from fastapi import FastAPI
from .test_process_runtime import make_plugin, WORKER
from lamtools_core.app import OperationCatalog
from lamtools_core.plugin_system import PluginContext, PluginHost
from lamtools_core.plugin_system.backend_runtime import register_manager
from lamtools_core.plugin_system.lifecycle import await_plugin_backends, load_enabled_plugin_backends
from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
from lamtools_core.plugin_system.secrets import PluginSecretStore


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['rpc_error', 'exit'])
async def test_process_commit_then_error_is_uncertain_over_remote(tmp_path, mode):
    folder = make_plugin(tmp_path / 'plugins' / 'demo-process')
    failure = ('sys.stdout.write(json.dumps({"jsonrpc":"2.0", "id":request_id, "error":{"message":"write failed"}})+"\\n"); sys.stdout.flush(); continue'
               if mode == 'rpc_error' else 'break')
    worker = WORKER.replace('    elif method == "operations/call":\n',
        '    elif method == "operations/call":\n        open("saved.txt", "w").write("saved")\n        ' + failure + '\n')
    (folder / 'worker.py').write_text(worker, encoding='utf8')
    path = folder / 'plugin.json'
    manifest = json.loads(path.read_text(encoding='utf8'))
    manifest['http'] = {'routes': [{'method':'POST','path':'/op','operation':'demo-process.ping'}],
        'remote':[{'namespace':'demo','method':'ping','route':'/op','argsSchema':{'type':'object','properties':{},'required':[],'additionalProperties':False}}]}
    path.write_text(json.dumps(manifest), encoding='utf8')
    host = PluginHost(roots=[folder.parent], state_path=tmp_path / 'state.json')
    ctx = PluginContext(work_root=tmp_path, data_dir=tmp_path)
    ctx._secret_store = PluginSecretStore(tmp_path / 'secrets')
    handles = load_enabled_plugin_backends(host.discover(), ctx, start=True)
    manager = register_manager(host, handles, ctx)
    try:
        await await_plugin_backends(manager.handles)
        catalog = OperationCatalog()
        ctx.operation_catalog = catalog
        register_plugin_operations(catalog, host)
        app = FastAPI()
        app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            response = await client.post('/plugin-remote/demo-process/demo/ping', json={'args':{}},
                headers={'x-plugin-token':plugin_http_token(host, 'demo-process')})
        assert response.status_code == 400
        assert response.json()['payload']['may_have_changed'] is True
        assert (folder / 'saved.txt').read_text() == 'saved'
    finally:
        await manager.stop('demo-process')
