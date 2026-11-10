"""user:“第二阶段结束后 就继续开展第三阶段”+(真实会话重命名复用原标题CAS与项目范围)。"""
import json
import httpx
import pytest
from fastapi import FastAPI
from .test_plugin_working_directory import env
from .test_plugin_http_routes import _host
from .test_plugin_remote_gateway import configure
from lamtools_core.session import SessionRecord
from lamtools_core.app.operation_catalog import OperationCatalog
from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
from lamtools_core.plugin_system.plugin_http import create_plugin_http_router,plugin_http_token

@pytest.mark.asyncio
async def test_native_session_title_cas_crosses_http_and_rejects_other_project(env,tmp_path):
    ctx,store,_,_=env
    other=tmp_path/'other'; other.mkdir()
    await store.create(SessionRecord('foreign','core','Other','idle',metadata={'work_root':str(other)}))
    rev=(await ctx.session_title.get('s'))['revision']
    host,_,original=_host(tmp_path); configure(host)
    path=host.get('hook-demo').root/'plugin.json'; manifest=json.loads(path.read_text(encoding='utf8'))
    schema=manifest['http']['remote'][0]['argsSchema']; schema['properties'].update({'title':{'type':'string'},'revision':{'type':'integer'}}); schema['required']+=['title','revision']
    path.write_text(json.dumps(manifest),encoding='utf8'); host._invalidate()
    ctx._secret_store=original._secret_store; host.backend_manager.context=ctx
    (host.get('hook-demo').root/'ops.py').write_text(
        "async def echo(request, *, context):\n    b=request.payload['body']\n    return await context.session_title.set(b['text'], b['title'], expected_revision=b['revision'])\n",encoding='utf8')
    catalog=OperationCatalog(); register_plugin_operations(catalog,host)
    app=FastAPI(); app.include_router(create_plugin_http_router(lambda:host,lambda:catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        path='/plugin-remote/hook-demo/demo/echo'; headers={'x-plugin-token':plugin_http_token(host,'hook-demo')}
        async def call(sid,title,revision,headers=headers):
            return await client.post(path,json={'args':{'text':sid,'title':title,'revision':revision}},headers=headers)
        denied=await call('s','Denied',rev,{'x-plugin-token':'wrong'})
        foreign=await call('foreign','Denied',rev)
        ok=await call('s','Renamed',rev)
        stale=await call('s','Lost',rev)
    assert denied.status_code==401 and foreign.status_code!=200 and ok.status_code==200 and stale.status_code!=200
    assert (await store.get_readonly('s')).title=='Renamed' and (await store.get_readonly('foreign')).title=='Other'
    assert ok.json()['payload']['revision']>rev

def test_migration_identifies_native_session_title_cas(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root=source(tmp_path,{'index.ts':'export function apply(ctx) { ctx.remote.session.rename(); }'})
    report=export_port(root,tmp_path/'ported'); row=next(r for r in report['remotes'] if r['name']=='session.rename')
    assert row['suggestedContract']=='context.session_title.set' and row['conversion']=='agent-required'
    assert report['runtimeVerified'] is False
