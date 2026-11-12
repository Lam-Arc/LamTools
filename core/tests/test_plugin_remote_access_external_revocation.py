"""user:“第三阶段先做Remote/网关的后端访问控制与明确方法名单”+(外部操作声明撤回后不发布旧方法清单)。"""
import json
import pytest
from .test_plugin_remote_access_inventory import remote_env
from lamtools_core.plugin_system.operation_bridge import register_plugin_operations

@pytest.mark.parametrize('permission',['hard_block','ask_user'])
def test_external_operation_permission_change_during_read_is_not_advertised(remote_env,monkeypatch,permission):
    from lamtools_core.plugin_system import remote_access
    ctx,host,catalog=remote_env; path=host.get('hook-demo').root/'plugin.json'; raw=json.loads(path.read_text(encoding='utf8'))
    external=path.parent/'operations.json'; external.write_text(json.dumps({'operations':raw['operations']}),encoding='utf8')
    raw['operations']=['./operations.json']; path.write_text(json.dumps(raw),encoding='utf8'); host._invalidate()
    catalog.unregister_owner('plugin:hook-demo'); register_plugin_operations(catalog,host)
    original=remote_access.read_operations
    def changed(manifest):
        result=original(manifest); updated=json.loads(external.read_text(encoding='utf8'))
        updated['operations'][0]['permission']=permission; external.write_text(json.dumps(updated),encoding='utf8')
        return result
    monkeypatch.setattr(remote_access,'read_operations',changed)
    with pytest.raises(RuntimeError): ctx.remote_access.declared_methods()

def test_unchanged_external_operation_stays_advertised(remote_env):
    ctx,host,catalog=remote_env; path=host.get('hook-demo').root/'plugin.json'; raw=json.loads(path.read_text(encoding='utf8'))
    external=path.parent/'operations.json'; external.write_text(json.dumps({'operations':raw['operations']}),encoding='utf8')
    raw['operations']=['./operations.json']; path.write_text(json.dumps(raw),encoding='utf8'); host._invalidate()
    catalog.unregister_owner('plugin:hook-demo'); register_plugin_operations(catalog,host)
    assert ctx.remote_access.declared_methods()['methods'][0]['method']=='echo'

@pytest.mark.asyncio
async def test_external_revocation_is_not_published_over_http(remote_env,monkeypatch):
    import httpx
    from fastapi import FastAPI
    from lamtools_core.plugin_system import remote_access
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router,plugin_http_token
    ctx,host,catalog=remote_env; host.backend_manager.context=ctx
    path=host.get('hook-demo').root/'plugin.json'; raw=json.loads(path.read_text(encoding='utf8'))
    external=path.parent/'operations.json'; external.write_text(json.dumps({'operations':raw['operations']}),encoding='utf8')
    raw['operations']=['./operations.json']; path.write_text(json.dumps(raw),encoding='utf8'); host._invalidate()
    (path.parent/'ops.py').write_text('def echo(request, *, context):\n    return context.remote_access.declared_methods()\n',encoding='utf8')
    catalog.unregister_owner('plugin:hook-demo'); register_plugin_operations(catalog,host)
    original=remote_access.read_operations
    def changed(manifest):
        result=original(manifest); updated=json.loads(external.read_text(encoding='utf8'))
        updated['operations'][0]['permission']='hard_block'; external.write_text(json.dumps(updated),encoding='utf8'); return result
    monkeypatch.setattr(remote_access,'read_operations',changed)
    app=FastAPI(); app.include_router(create_plugin_http_router(lambda:host,lambda:catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        response=await client.post('/plugin-remote/hook-demo/demo/echo',json={'args':{'text':'x'}},headers={'x-plugin-token':plugin_http_token(host,'hook-demo')})
    assert response.status_code>=400 and '"method":"echo"' not in response.text

def test_operation_replacement_during_final_read_rejects_old_inventory(remote_env,monkeypatch):
    from lamtools_core.plugin_system import remote_access
    from lamtools_core.app.operation_catalog import OperationResult
    ctx,_,catalog=remote_env; original=remote_access.read_operations; calls=0
    def changed(manifest):
        nonlocal calls
        result=original(manifest); calls+=1
        if calls==2:
            catalog.unregister_owner('plugin:hook-demo')
            catalog.register('hook-demo.echo',lambda req:OperationResult(req.name,{}),owner='plugin:hook-demo')
        return result
    monkeypatch.setattr(remote_access,'read_operations',changed)
    with pytest.raises(RuntimeError): ctx.remote_access.declared_methods()
