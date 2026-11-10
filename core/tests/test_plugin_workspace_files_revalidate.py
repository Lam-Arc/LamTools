"""user:“复用原宿主权威”+(会话隐藏或工作目录变化后不发布旧文件内容)。"""
import asyncio
import pytest
from .test_plugin_working_directory import env
from lamtools_core.plugin_system.workspace_files import PluginWorkspaceFilesAPI


@pytest.mark.asyncio
@pytest.mark.parametrize('method', ['stat', 'list', 'read', 'read_bytes'])
async def test_hidden_after_file_operation_does_not_publish(env, monkeypatch, method):
    ctx, store, _, root = env
    (root / 'secret.txt').write_text('private content')
    target = '_list' if method == 'list' else '_stat'
    original = getattr(PluginWorkspaceFilesAPI, target)
    def hide(*args, **kwargs):
        result = original(*args, **kwargs)
        store._session_visible = lambda sid, _: sid != 's'
        return result
    monkeypatch.setattr(PluginWorkspaceFilesAPI, target, staticmethod(hide))
    api = ctx.workspace_files
    with pytest.raises((ValueError, RuntimeError)):
        await (api.list('s') if method == 'list' else getattr(api, method)('s', 'secret.txt'))


@pytest.mark.asyncio
async def test_root_binding_change_after_read_rejects_old_content(env, monkeypatch, tmp_path):
    ctx, _, _, root = env
    (root / 'secret.txt').write_text('private')
    original = PluginWorkspaceFilesAPI._stat
    def moved(*args, **kwargs):
        result = original(*args, **kwargs)
        ctx.work_root = tmp_path / 'other-project'
        return result
    monkeypatch.setattr(PluginWorkspaceFilesAPI, '_stat', staticmethod(moved))
    with pytest.raises(ValueError) as error: await ctx.workspace_files.read('s', 'secret.txt')
    assert error.value.code == 'workspace-file/host-changed'


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['directory', 'host', 'scope', 'cancel'])
async def test_final_session_check_handles_directory_change_or_cancel(env, monkeypatch, change):
    ctx, store, _, root = env
    (root / 'secret.txt').write_text('private')
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
    task = asyncio.create_task(ctx.workspace_files.read('s', 'secret.txt'))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        if change == 'directory':
            state = await ctx.working_directory.get('s')
            await ctx.working_directory.set('s', 'one', expected_revision=state.revision)
            release.set()
            with pytest.raises(ValueError) as error: await task
            assert error.value.code == 'workspace-file/session-directory-changed'
        elif change == 'host':
            ctx.set_service('working_directory', object())
            release.set()
            with pytest.raises((ValueError, RuntimeError)): await task
        elif change == 'scope':
            ctx._registration_scope.revoke()
            release.set()
            with pytest.raises((ValueError, RuntimeError)): await task
        else:
            task.cancel()
            with pytest.raises(asyncio.CancelledError): await task
        assert not ctx._registration_scope._calls
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_hidden_during_read_is_not_returned_over_real_http(env, monkeypatch, tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
    ctx, store, _, root = env
    (root / 'secret.txt').write_text('private payload')
    original_stat = PluginWorkspaceFilesAPI._stat
    def hide(*args, **kwargs):
        result = original_stat(*args, **kwargs)
        store._session_visible = lambda sid, _: sid != 's'
        return result
    monkeypatch.setattr(PluginWorkspaceFilesAPI, '_stat', staticmethod(hide))
    host, catalog, previous = _host(tmp_path)
    configure(host)
    ctx._secret_store = previous._secret_store
    host.backend_manager.context = ctx
    (host.get('hook-demo').root / 'ops.py').write_text(
        "async def echo(request, *, context):\n    return await context.workspace_files.read('s', 'secret.txt')\n", encoding='utf8')
    catalog.unregister_owner('plugin:hook-demo')
    register_plugin_operations(catalog, host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/plugin-remote/hook-demo/demo/echo', json={'args': {'text': 'x'}},
            headers={'x-plugin-token': plugin_http_token(host, 'hook-demo')})
    assert response.status_code == 400 and 'private payload' not in response.text


@pytest.mark.asyncio
async def test_unchanged_session_returns_original_bytes(env):
    ctx, _, _, root = env
    (root / 'data.bin').write_bytes(b'\x00\xff')
    assert (await ctx.workspace_files.read_bytes('s', 'data.bin'))['data'] == b'\x00\xff'
