"""user:“复用原宿主权威”+(技能发现完成后不得发布已隐藏会话的旧目录技能)。"""
import asyncio
import pytest
from .test_plugin_working_directory import env
from .test_plugin_session_skill_catalog import provider


@pytest.mark.asyncio
async def test_hidden_session_during_original_registry_scan_rejects_result(provider, env, monkeypatch):
    ctx, registry, _, _, _ = provider
    _, store, _, _ = env
    original = registry.available
    def hide_after_read(path):
        result = original(path)
        store._session_visible = lambda sid, _: sid != 's'
        return result
    monkeypatch.setattr(registry, 'available', hide_after_read)
    with pytest.raises((ValueError, RuntimeError)):
        await ctx.session_skill_catalog.list('s')


@pytest.mark.asyncio
async def test_unchanged_real_registry_still_returns_metadata(provider):
    ctx, _, _, _, _ = provider
    result = await ctx.session_skill_catalog.list('s')
    assert [skill['name'] for skill in result['skills']] == ['allowed']
    assert 'SECRET BODY' not in repr(result)


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['directory', 'cancel'])
async def test_final_session_read_rechecks_directory_and_releases_scope(provider, env, monkeypatch, change):
    ctx, _, _, _, _ = provider
    _, store, _, _ = env
    original = store.get_readonly_revision
    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0
    async def gated(sid):
        nonlocal calls
        calls += 1
        if calls == 2:
            entered.set()
            await release.wait()
        return await original(sid)
    monkeypatch.setattr(store, 'get_readonly_revision', gated)
    task = asyncio.create_task(ctx.session_skill_catalog.list('s'))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        if change == 'directory':
            state = await ctx.working_directory.get('s')
            await ctx.working_directory.set('s', 'one', expected_revision=state.revision)
            release.set()
            with pytest.raises(RuntimeError) as error: await task
            assert error.value.code == 'session-skill/directory-changed'
        else:
            task.cancel()
            with pytest.raises(asyncio.CancelledError): await task
        assert not ctx._registration_scope._calls
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_hidden_during_discovery_is_not_returned_over_http(provider, env, monkeypatch, tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
    ctx, registry, _, _, _ = provider
    _, store, _, _ = env
    original = registry.available
    def hide(path):
        result = original(path)
        store._session_visible = lambda sid, _: sid != 's'
        return result
    monkeypatch.setattr(registry, 'available', hide)
    host, catalog, previous = _host(tmp_path)
    configure(host)
    ctx._secret_store = previous._secret_store
    host.backend_manager.context = ctx
    (host.get('hook-demo').root / 'ops.py').write_text(
        "async def echo(request, *, context):\n    return await context.session_skill_catalog.list('s')\n", encoding='utf8')
    catalog.unregister_owner('plugin:hook-demo')
    register_plugin_operations(catalog, host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/plugin-remote/hook-demo/demo/echo', json={'args': {'text': 'x'}},
            headers={'x-plugin-token': plugin_http_token(host, 'hook-demo')})
    assert response.status_code == 400 and 'allowed' not in response.text and 'SECRET BODY' not in response.text


@pytest.mark.asyncio
async def test_changed_enablement_during_final_session_read_rejects_old_view(provider, env, monkeypatch):
    ctx, _, state, _, _ = provider
    _, store, _, _ = env
    original = store.get_readonly_revision
    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0
    async def gated(sid):
        nonlocal calls
        calls += 1
        if calls == 2:
            entered.set()
            await release.wait()
        return await original(sid)
    monkeypatch.setattr(store, 'get_readonly_revision', gated)
    task = asyncio.create_task(ctx.session_skill_catalog.list('s'))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        state.set_enabled('allowed', False)
        release.set()
        with pytest.raises(RuntimeError) as error: await task
        assert error.value.code == 'session-skill/state-changed'
        assert (await ctx.session_skill_catalog.list('s'))['skills'] == []
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
