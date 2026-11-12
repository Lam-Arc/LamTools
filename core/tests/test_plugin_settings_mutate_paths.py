"""user:“第二阶段结束后 就继续开展第三阶段”+(逐路径配置编辑保留原CAS与脱敏)。"""
import pytest
from .test_plugin_settings_update_patch import patch_env


@pytest.mark.asyncio
async def test_ordered_mutations_preserve_secrets_and_handle_array_indices(patch_env):
    ctx=patch_env; api=ctx.settings_controller
    before=api.replace({'secret':'local-test-secret','nested':{'a':1,'b':2},'items':[1,2,3]},expected_revision=api.describe()['revision'])
    after=api.mutate([{'op':'unset','path':['nested','b']},{'op':'set','path':['nested','a'],'value':7},
        {'op':'unset','path':['items','1']},{'op':'set','path':['items','2'],'value':9}],expected_revision=before['revision'])
    assert after['values']=={'secret':'<redacted>','nested':{'a':7},'items':[1,3,9]}
    assert ctx.settings.read().values['secret']=='local-test-secret' and 'local-test-secret' not in repr(after)
    with pytest.raises(RuntimeError): api.mutate([{'op':'set','path':['nested','a'],'value':4}],expected_revision=before['revision'])
    assert ctx.settings.read().values['nested']=={'a':7}


@pytest.mark.asyncio
@pytest.mark.parametrize('ops', [[],[{'op':'unset','path':[]}],[{'op':'set','path':['items','01'],'value':5}],
    [{'op':'set','path':['items','4'],'value':5}],[{'op':'set','path':['nested','a'],'value':'wrong'}],
    [{'op':'set','path':['missing','child'],'value':1}],[{'op':'explode','path':['items']}],
    [{'op':[],'path':['items']}],[{'op':'set','path':['nested','a'],'value':1,'extra':2}]])
async def test_invalid_edits_never_commit(patch_env,ops):
    api=patch_env.settings_controller
    before=api.replace({'nested':{'a':1,'b':2},'items':[1,2]},expected_revision=api.describe()['revision'])
    with pytest.raises(RuntimeError): api.mutate(ops,expected_revision=before['revision'])
    assert api.describe()['revision']==before['revision']


@pytest.mark.asyncio
async def test_mutate_does_not_overwrite_concurrent_update(patch_env,monkeypatch):
    api=patch_env.settings_controller
    before=api.replace({'nested':{'a':1,'b':2}},expected_revision=api.describe()['revision'])
    original=api._settings.read
    def concurrent():
        old=original()
        api._settings.replace({'nested':{'a':1,'b':7}},expected_revision=old.revision)
        return old
    monkeypatch.setattr(api._settings,'read',concurrent)
    with pytest.raises(RuntimeError): api.mutate([{'op':'set','path':['nested','a'],'value':3}],expected_revision=before['revision'])
    monkeypatch.setattr(api._settings,'read',original)
    assert api._settings.read().values['nested']=={'a':1,'b':7}


@pytest.mark.asyncio
async def test_mutate_crosses_remote_without_revealing_secret(patch_env,tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router,plugin_http_token
    ctx=patch_env; api=ctx.settings_controller
    api.replace({'secret':'temp-secret','items':[1,2,3]},expected_revision=api.describe()['revision'])
    host,catalog,old=_host(tmp_path); configure(host); ctx._secret_store=old._secret_store
    host.backend_manager.context=ctx
    (host.get('hook-demo').root/'ops.py').write_text(
        "def echo(request, *, context):\n    api=context.settings_controller\n    return api.mutate([{'op':'unset','path':['items','1']}], expected_revision=api.describe()['revision'])\n",encoding='utf8')
    catalog.unregister_owner('plugin:hook-demo'); register_plugin_operations(catalog,host)
    app=FastAPI(); app.include_router(create_plugin_http_router(lambda:host,lambda:catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        endpoint='/plugin-remote/hook-demo/demo/echo'; body={'args':{'text':'go'}}
        denied=await client.post(endpoint,json=body,headers={'x-plugin-token':'wrong'})
        assert denied.status_code==401 and ctx.settings.read().values['items']==[1,2,3]
        response=await client.post(endpoint,json=body,headers={'x-plugin-token':plugin_http_token(host,'hook-demo')})
    assert response.status_code==200 and response.json()['payload']['values']['items']==[1,3]
    assert 'temp-secret' not in response.text and ctx.settings.read().values['secret']=='temp-secret'


def test_mutate_migration_names_bounded_candidate(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root=source(tmp_path,{'index.ts':'export function apply(ctx) { ctx.remote.settings.mutate(); }'})
    report=export_port(root,tmp_path/'ported'); row=next(x for x in report['remotes'] if x['name']=='settings.mutate')
    assert row['suggestedContract']=='context.settings_controller.mutate' and row['conversion']=='agent-required'
