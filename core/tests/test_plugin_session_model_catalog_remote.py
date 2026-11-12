"""user:“第三阶段先做Remote/网关的后端访问控制与明确方法名单”+(模型目录只返回原项目配置元数据)。"""
import json
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from lamtools_core.config.model_store import ModelStore
from lamtools_core.plugin_system.context import PluginContext
from lamtools_core.plugin_system.model_catalog import ModelCatalogService
from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
from .test_plugin_http_routes import _host
from .test_plugin_remote_gateway import configure


@pytest.mark.asyncio
async def test_real_configured_model_metadata_crosses_remote_without_claiming_availability(tmp_path, monkeypatch):
    project = tmp_path / 'project'
    models = project / '.lam/config/models'
    models.mkdir(parents=True)
    record = models / 'test.jsonc'
    record.write_text(json.dumps({'id': 'model-one', 'model_id': 'wire-one', 'display_name': 'Local model',
                                  'provider_id': 'missing-provider', 'provider': 'Missing'}), encoding='utf8')
    monkeypatch.setattr(ModelStore, '_candidate_dirs', lambda self, work_root: [Path(work_root) / '.lam/config/models'])
    host, catalog, original = _host(tmp_path)
    configure(host)
    ctx = PluginContext(project, operation_catalog=catalog, _secret_store=original._secret_store)
    ctx.set_service('model_catalog', ModelCatalogService(work_root=project))
    ctx._begin_registration_scope('hook-demo', 1, manifest=host.get('hook-demo'))
    host.backend_manager.context = ctx
    (host.get('hook-demo').root / 'ops.py').write_text(
        "def echo(request, *, context):\n    return {'configured_models': context.models.list()}\n", encoding='utf8')
    catalog.unregister_owner('plugin:hook-demo')
    register_plugin_operations(catalog, host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            url = '/plugin-remote/hook-demo/demo/echo'
            body = {'args': {'text': 'ignored'}}
            denied = await client.post(url, json=body, headers={'x-plugin-token': 'wrong'})
            ok = await client.post(url, json=body, headers={'x-plugin-token': plugin_http_token(host, 'hook-demo')})
            assert denied.status_code == 401 and ok.status_code == 200
            rows = ok.json()['payload']['configured_models']
            assert len(rows) == 1 and rows[0]['id'] == 'model-one' and rows[0]['provider_id'] == 'missing-provider'
            assert all(k not in rows[0] for k in ('api_key', 'base_url', 'available', 'routable'))
            record.unlink()
            empty = await client.post(url, json=body, headers={'x-plugin-token': plugin_http_token(host, 'hook-demo')})
            assert empty.json()['payload']['configured_models'] == []
    finally:
        await ctx._registration_scope.dispose()


def test_session_catalog_migration_marks_configured_only(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root = source(tmp_path, {'index.ts': 'export function apply(ctx) { ctx.remote.session.modelCatalog(); }'})
    report = export_port(root, tmp_path / 'ported')
    row = next(item for item in report['remotes'] if item['name'] == 'session.modelCatalog')
    assert row['suggestedContract'] == 'context.models.list'
    assert '不代表' in row['difference'] and report['runtimeVerified'] is False


def test_model_catalog_does_not_publish_when_scope_revoked_during_native_read(tmp_path, monkeypatch):
    project = tmp_path / 'project'
    models = project / '.lam/config/models'
    models.mkdir(parents=True)
    (models / 'one.jsonc').write_text(json.dumps({'id': 'one', 'model_id': 'one'}), encoding='utf8')
    monkeypatch.setattr(ModelStore, '_candidate_dirs', lambda self, work_root: [Path(work_root) / '.lam/config/models'])
    ctx = PluginContext(project)
    ctx.set_service('model_catalog', ModelCatalogService(work_root=project))
    scope = ctx._begin_registration_scope('model-test', 1)
    original = ModelStore.list_sync
    def revoked(store, *args, **kwargs):
        result = original(store, *args, **kwargs)
        scope.revoke()
        return result
    monkeypatch.setattr(ModelStore, 'list_sync', revoked)
    with pytest.raises(RuntimeError): ctx.models.list()


def test_model_selection_does_not_publish_when_scope_revoked_during_provider_check(tmp_path, monkeypatch):
    from lamtools_core.config import model_selection
    project = tmp_path / 'project'
    models = project / '.lam/config/models'
    models.mkdir(parents=True)
    (models / 'one.jsonc').write_text(json.dumps({'id': 'one', 'model_id': 'one'}), encoding='utf8')
    monkeypatch.setattr(ModelStore, '_candidate_dirs', lambda self, work_root: [Path(work_root) / '.lam/config/models'])
    ctx = PluginContext(project)
    ctx.set_service('model_catalog', ModelCatalogService(work_root=project))
    scope = ctx._begin_registration_scope('model-test', 1)
    def revoked(*args, **kwargs):
        scope.revoke()
        return True
    monkeypatch.setattr(model_selection, 'model_is_usable', revoked)
    with pytest.raises(RuntimeError): ctx.models.select('chat', ref='one')
