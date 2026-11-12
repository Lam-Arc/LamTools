"""user:“第二阶段结束后 就继续开展第三阶段”+(局部设置合并复用原持久化及脱敏)。"""
import json
import pytest
from lamtools_core.plugin_system.context import PluginContext
from lamtools_core.plugin_system.manifest import PluginManifest


@pytest.fixture
async def patch_env(tmp_path):
    root=tmp_path/'plugin'; root.mkdir()
    schema={'type':'object','additionalProperties':False,'properties':{
        'secret':{'type':'string','writeOnly':True},
        'nested':{'type':'object','properties':{'a':{'type':'integer'},'b':{'type':'integer'}}},
        'items':{'type':'array','items':{'type':'integer'}}}}
    (root/'schema.json').write_text(json.dumps(schema),encoding='utf8')
    manifest=PluginManifest('settings-test','1',root=root,raw={'config':{'schema':'./schema.json'}})
    ctx=PluginContext(root,data_dir=tmp_path/'data'); ctx._begin_registration_scope('settings-test',1,manifest=manifest)
    try: yield ctx
    finally: await ctx._registration_scope.dispose()


@pytest.mark.asyncio
async def test_update_merges_nested_and_replaces_array_without_revealing_secret(patch_env):
    ctx=patch_env; api=ctx.settings_controller
    rev=api.describe()['revision']
    saved=api.replace({'secret':'test-private-value','nested':{'a':1,'b':2},'items':[1,2]},expected_revision=rev)
    result=api.update({'nested':{'a':3},'items':[9]},expected_revision=saved['revision'])
    assert result['values']=={'secret':'<redacted>','nested':{'a':3,'b':2},'items':[9]}
    assert 'test-private-value' not in repr(result)
    assert ctx.settings.read().values['secret']=='test-private-value'
    with pytest.raises(RuntimeError): api.update({'nested':{'b':8}},expected_revision=saved['revision'])
    assert ctx.settings.read().values['nested']=={'a':3,'b':2}


@pytest.mark.asyncio
async def test_update_invalid_patch_does_not_commit(patch_env):
    api=patch_env.settings_controller; before=api.describe()
    with pytest.raises(RuntimeError): api.update({'nested':{'a':'wrong'}},expected_revision=before['revision'])
    assert api.describe()['revision']==before['revision']


@pytest.mark.asyncio
@pytest.mark.parametrize('patch', [None, [], {'secret':'\ud800'}, {'nested':{'a':float('nan')}}])
async def test_update_rejects_non_json_patch_before_write(patch_env, patch):
    api=patch_env.settings_controller; before=api.describe()
    with pytest.raises(RuntimeError): api.update(patch,expected_revision=before['revision'])
    assert api.describe()['revision']==before['revision']


@pytest.mark.asyncio
async def test_update_does_not_overwrite_concurrent_commit(patch_env, monkeypatch):
    api=patch_env.settings_controller
    before=api.replace({'nested':{'a':1,'b':2}},expected_revision=api.describe()['revision'])
    original=api._settings.read
    def concurrent():
        prior=original()
        api._settings.replace({'nested':{'a':1,'b':7}},expected_revision=prior.revision)
        return prior
    monkeypatch.setattr(api._settings,'read',concurrent)
    with pytest.raises(RuntimeError): api.update({'nested':{'a':3}},expected_revision=before['revision'])
    monkeypatch.setattr(api._settings,'read',original)
    assert api._settings.read().values['nested']=={'a':1,'b':7}


@pytest.mark.asyncio
async def test_update_crosses_remote_and_retains_redaction(patch_env,tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router,plugin_http_token
    ctx=patch_env; api=ctx.settings_controller
    api.replace({'secret':'temp-http-secret','nested':{'a':1,'b':2}},expected_revision=api.describe()['revision'])
    host,catalog,old=_host(tmp_path); configure(host); ctx._secret_store=old._secret_store
    host.backend_manager.context=ctx
    (host.get('hook-demo').root/'ops.py').write_text(
        "def echo(request, *, context):\n    api=context.settings_controller\n    return api.update({'nested':{'a':3}}, expected_revision=api.describe()['revision'])\n",encoding='utf8')
    catalog.unregister_owner('plugin:hook-demo'); register_plugin_operations(catalog,host)
    app=FastAPI(); app.include_router(create_plugin_http_router(lambda:host,lambda:catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        denied=await client.post('/plugin-remote/hook-demo/demo/echo',json={'args':{'text':'go'}},headers={'x-plugin-token':'wrong'})
        assert denied.status_code==401 and ctx.settings.read().values['nested']=={'a':1,'b':2}
        response=await client.post('/plugin-remote/hook-demo/demo/echo',json={'args':{'text':'go'}},
            headers={'x-plugin-token':plugin_http_token(host,'hook-demo')})
    assert response.status_code==200 and response.json()['payload']['values']['nested']=={'a':3,'b':2}
    assert 'temp-http-secret' not in response.text and ctx.settings.read().values['secret']=='temp-http-secret'


def test_update_migration_reports_manual_scope(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root=source(tmp_path,{'index.ts':'export function apply(ctx) { ctx.remote.settings.update(); }'})
    report=export_port(root,tmp_path/'ported'); row=next(x for x in report['remotes'] if x['name']=='settings.update')
    assert row['suggestedContract']=='context.settings_controller.update' and row['conversion']=='agent-required'
