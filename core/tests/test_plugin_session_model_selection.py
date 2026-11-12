"""user:“复用原宿主权威”+(会话模型选择使用原会话输入参数事务)。"""
import asyncio
import json
from pathlib import Path

import pytest

from .test_plugin_working_directory import env
from lamtools_core.config.model_store import ModelStore
from lamtools_core.config.provider_store import ProviderStore
from lamtools_core.plugin_system.model_catalog import ModelCatalogService
from lamtools_core.app.composer_state import composer_state_from_metadata
from lamtools_core.session import SessionRecord


@pytest.fixture
def configured_model(env, monkeypatch):
    ctx, _, _, root = env
    model_dir, provider_dir = root / 'test-models', root / 'test-providers'
    model_dir.mkdir(); provider_dir.mkdir()
    (model_dir / 'one.jsonc').write_text(json.dumps({'id': 'model-one', 'model_id': 'wire-one', 'provider_id': 'provider-one', 'provider': 'Provider'}), encoding='utf8')
    (provider_dir / 'one.jsonc').write_text(json.dumps({'id': 'provider-one', 'name': 'Provider', 'base_url': 'https://example.invalid/v1'}), encoding='utf8')
    monkeypatch.setattr(ModelStore, '_candidate_dirs', lambda self, work_root: [model_dir])
    monkeypatch.setattr(ProviderStore, '_candidate_dirs', lambda self, work_root: [provider_dir])
    ctx.set_service('model_catalog', ModelCatalogService(work_root=root))
    return ctx


@pytest.mark.asyncio
async def test_model_selection_uses_original_session_transaction_without_approval_change(env, configured_model, monkeypatch):
    from lamtools_core.app.live import permissions
    ctx, store, _, _ = env
    async def forbidden(*args, **kwargs): pytest.fail('model selection must not release approvals')
    monkeypatch.setattr(permissions, 'release_pending_approval_for_preset', forbidden)
    _, revision = await store.get_readonly_revision('s')
    result = await ctx.session_controller.select_model('s', 'model-one', expected_revision=revision)
    assert result['model_id'] == 'model-one'
    saved, new_revision = await store.get_readonly_revision('s')
    assert composer_state_from_metadata(saved.metadata)['model_id'] == 'model-one' and new_revision > revision


@pytest.mark.asyncio
async def test_normal_composer_operation_still_checks_approvals(env, monkeypatch):
    from lamtools_core.app.live import composer, permissions
    _, store, sessions, _ = env
    _, revision = await store.get_readonly_revision('s')
    observed = []
    async def track(**kwargs):
        observed.append(kwargs['thread_id'])
        return 'checked'
    monkeypatch.setattr(permissions, 'release_pending_approval_for_preset', track)
    result = await composer.handle_session_composer_set_operation(
        request_id=1, params={'thread_id': 's', 'model_id': 'model-one', 'expected_revision': revision},
        context=sessions._context())
    assert observed == ['s'] and result.response['result']['approval_status'] == 'checked'


@pytest.mark.asyncio
async def test_selection_rejects_unavailable_and_other_project_before_write(env, configured_model, tmp_path):
    ctx, store, _, _ = env
    other = tmp_path / 'other'; other.mkdir()
    await store.create(SessionRecord('other', 'core', 'Other', 'idle', metadata={'work_root': str(other)}))
    _, revision = await store.get_readonly_revision('s')
    with pytest.raises(RuntimeError): await ctx.session_controller.select_model('s', 'missing', expected_revision=revision)
    with pytest.raises(RuntimeError): await ctx.session_controller.select_model('other', 'model-one', expected_revision=revision)
    assert (await store.get_readonly_revision('s'))[1] == revision


@pytest.mark.asyncio
async def test_missing_provider_is_not_treated_as_available(env, configured_model):
    ctx, store, _, root = env
    _, revision = await store.get_readonly_revision('s')
    (root / 'test-providers/one.jsonc').unlink()
    with pytest.raises(RuntimeError):
        await ctx.session_controller.select_model('s', 'model-one', expected_revision=revision)
    assert (await store.get_readonly_revision('s'))[1] == revision


@pytest.mark.asyncio
@pytest.mark.parametrize('model_id,revision', [(None, 0), ('', 0), ('x' * 257, 0), ('\ud800', 0), ('model-one', True), ('model-one', -1)])
async def test_invalid_model_selection_is_rejected_before_dispatch(env, configured_model, model_id, revision):
    ctx, store, _, _ = env
    _, before = await store.get_readonly_revision('s')
    with pytest.raises(ValueError):
        await ctx.session_controller.select_model('s', model_id, expected_revision=revision)
    assert (await store.get_readonly_revision('s'))[1] == before


@pytest.mark.asyncio
async def test_selection_cancel_waits_for_original_write(env, configured_model, monkeypatch):
    from lamtools_core.app.live import composer
    ctx, store, _, _ = env
    _, revision = await store.get_readonly_revision('s')
    original = composer.handle_session_composer_set_operation
    entered, release = asyncio.Event(), asyncio.Event()
    async def gated(*args, **kwargs):
        entered.set()
        await release.wait()
        return await original(*args, **kwargs)
    monkeypatch.setattr(composer, 'handle_session_composer_set_operation', gated)
    task = asyncio.create_task(ctx.session_controller.select_model('s', 'model-one', expected_revision=revision))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        task.cancel(); await asyncio.sleep(0); task.cancel()
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError): await task
        record, _ = await store.get_readonly_revision('s')
        assert composer_state_from_metadata(record.metadata)['model_id'] == 'model-one'
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_model_removed_before_dispatch_does_not_write(env, configured_model, monkeypatch):
    ctx, store, _, root = env
    _, revision = await store.get_readonly_revision('s')
    api = ctx.session_controller
    original = api._admit
    entered, release = asyncio.Event(), asyncio.Event()
    count = 0
    async def gated(session_id):
        nonlocal count
        count += 1
        if count == 2: entered.set(); await release.wait()
        return await original(session_id)
    monkeypatch.setattr(api, '_admit', gated)
    task = asyncio.create_task(api.select_model('s', 'model-one', expected_revision=revision))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        (root / 'test-models/one.jsonc').unlink()
        release.set()
        with pytest.raises(RuntimeError): await task
        assert (await store.get_readonly_revision('s'))[1] == revision
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_model_selection_stale_revision_does_not_overwrite(env, configured_model):
    ctx, store, _, _ = env
    _, revision = await store.get_readonly_revision('s')
    await ctx.session_controller.select_model('s', 'model-one', expected_revision=revision)
    with pytest.raises(RuntimeError) as error:
        await ctx.session_controller.select_model('s', 'model-one', expected_revision=revision)
    assert error.value.may_have_changed


@pytest.mark.asyncio
async def test_model_selection_scope_change_after_write_is_uncertain(env, configured_model, monkeypatch):
    from lamtools_core.app.live import composer
    ctx, store, _, _ = env
    _, revision = await store.get_readonly_revision('s')
    original = composer.handle_session_composer_set_operation
    async def revoked(*args, **kwargs):
        result = await original(*args, **kwargs)
        ctx._registration_scope.revoke()
        return result
    monkeypatch.setattr(composer, 'handle_session_composer_set_operation', revoked)
    with pytest.raises(RuntimeError) as error:
        await ctx.session_controller.select_model('s', 'model-one', expected_revision=revision)
    assert error.value.may_have_changed
    assert composer_state_from_metadata((await store.get_readonly_revision('s'))[0].metadata)['model_id'] == 'model-one'


@pytest.mark.asyncio
async def test_provider_replaced_during_final_model_check_is_uncertain(env, configured_model, monkeypatch):
    from lamtools_core.plugin_system.model_access import PluginModelAPI
    ctx, store, _, _ = env
    _, revision = await store.get_readonly_revision('s')
    original = PluginModelAPI.select
    calls = 0
    def replaced(api, *args, **kwargs):
        nonlocal calls
        result = original(api, *args, **kwargs)
        calls += 1
        if calls == 3: ctx.set_service('model_catalog', object())
        return result
    monkeypatch.setattr(PluginModelAPI, 'select', replaced)
    with pytest.raises(RuntimeError) as error:
        await ctx.session_controller.select_model('s', 'model-one', expected_revision=revision)
    assert error.value.may_have_changed


@pytest.mark.asyncio
async def test_model_selection_crosses_authenticated_remote(env, configured_model, tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
    ctx, store, _, _ = env
    _, revision = await store.get_readonly_revision('s')
    host, catalog, original = _host(tmp_path)
    configure(host)
    ctx._secret_store = original._secret_store
    host.backend_manager.context = ctx
    (host.get('hook-demo').root / 'ops.py').write_text(
        'async def echo(request, *, context):\n'
        f"    return await context.session_controller.select_model('s', request.payload['body']['text'], expected_revision={revision})\n", encoding='utf8')
    catalog.unregister_owner('plugin:hook-demo')
    register_plugin_operations(catalog, host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        url, body = '/plugin-remote/hook-demo/demo/echo', {'args': {'text': 'model-one'}}
        denied = await client.post(url, json=body, headers={'x-plugin-token': 'wrong'})
        assert denied.status_code == 401 and (await store.get_readonly_revision('s'))[1] == revision
        response = await client.post(url, json=body, headers={'x-plugin-token': plugin_http_token(host, 'hook-demo')})
    assert response.status_code == 200 and response.json()['payload']['model_id'] == 'model-one'
    assert composer_state_from_metadata((await store.get_readonly_revision('s'))[0].metadata)['model_id'] == 'model-one'


def test_selection_migration_reports_next_turn_and_revision(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root = source(tmp_path, {'index.ts': 'export function apply(ctx) { ctx.remote.session.selectModel(); }'})
    report = export_port(root, tmp_path / 'ported')
    row = next(item for item in report['remotes'] if item['name'] == 'session.selectModel')
    assert row['suggestedContract'] == 'context.session_controller.select_model'
    assert '修订' in row['difference'] and report['runtimeVerified'] is False
