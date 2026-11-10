"""user:“第二阶段结束后 就继续开展第三阶段”+(目录控制器复用原项目内浏览能力与真实回收)。"""
import asyncio
import threading
import pytest
from .test_plugin_working_directory import env


@pytest.mark.asyncio
async def test_real_browse_create_errors_and_native_unavailable(env):
    ctx, _, _, root = env
    api = ctx.directory_picker_controller
    assert api.capability() == {'kind': 'browse'}
    listing = await api.list()
    assert listing['path'] == str(root) and {x['name'] for x in listing['entries']} == {'one', 'two'}
    created = await api.create_directory(str(root), 'created')
    assert created == str(root / 'created') and (root / 'created').is_dir()
    with pytest.raises(RuntimeError) as error: await api.create_directory(str(root), 'created')
    assert error.value.code == 'directory-picker/exists'
    with pytest.raises(RuntimeError) as error: await api.list(str(root.parent))
    assert error.value.code == 'directory-picker/unreadable'
    with pytest.raises(RuntimeError) as error: await api.pick()
    assert error.value.code == 'directory-picker/unavailable'


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['cancel', 'scope', 'root'])
async def test_inflight_browse_settles_before_cancellation_or_withdrawal(env, monkeypatch, tmp_path, change):
    ctx, _, _, _ = env
    api = ctx.directory_picker_controller
    original = api._picker.list
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    def gated(*args, **kwargs):
        entered.set()
        release.wait()
        try: return original(*args, **kwargs)
        finally: finished.set()
    monkeypatch.setattr(api._picker, 'list', gated)
    task = asyncio.create_task(api.list())
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        if change == 'cancel':
            task.cancel()
            await asyncio.sleep(0.02)
            task.cancel()
            assert not task.done()
        elif change == 'scope': ctx._registration_scope.revoke()
        else: ctx.work_root = tmp_path / 'different'
        release.set()
        with pytest.raises(asyncio.CancelledError if change == 'cancel' else RuntimeError): await task
        assert finished.is_set()
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_write_completed_after_root_change_reports_uncertainty(env, monkeypatch, tmp_path):
    ctx, _, _, root = env
    api = ctx.directory_picker_controller
    original = api._picker.create_directory
    entered, release = threading.Event(), threading.Event()
    def gated(*args, **kwargs):
        result = original(*args, **kwargs)
        entered.set()
        release.wait()
        return result
    monkeypatch.setattr(api._picker, 'create_directory', gated)
    task = asyncio.create_task(api.create_directory(str(root), 'created-before-change'))
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        ctx.work_root = tmp_path / 'different'
        release.set()
        with pytest.raises(RuntimeError) as error: await task
        assert error.value.code == 'directory-picker/host-changed' and error.value.may_have_changed
        assert (root / 'created-before-change').is_dir()
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('limit', [True, 0, 1001])
async def test_invalid_limit_fails_before_native_browse(env, monkeypatch, limit):
    ctx, _, _, _ = env
    api = ctx.directory_picker_controller
    monkeypatch.setattr(api._picker, 'list', lambda *a, **k: pytest.fail('invalid limit entered picker'))
    with pytest.raises(ValueError): await api.list(limit=limit)


@pytest.mark.asyncio
async def test_cancelling_dispatched_creation_waits_for_original_result(env, monkeypatch):
    ctx, _, _, root = env
    api = ctx.directory_picker_controller
    original = api._picker.create_directory
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    def gated(*args, **kwargs):
        result = original(*args, **kwargs)
        entered.set()
        release.wait()
        finished.set()
        return result
    monkeypatch.setattr(api._picker, 'create_directory', gated)
    task = asyncio.create_task(api.create_directory(str(root), 'cancelled-after-create'))
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        task.cancel()
        await asyncio.sleep(0.02)
        task.cancel()
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError): await task
        assert finished.is_set() and (root / 'cancelled-after-create').is_dir()
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_failed_creation_after_binding_change_reports_possible_write(env, monkeypatch, tmp_path):
    from lamtools_core.plugin_system.directory_picker import DirectoryPickerError
    ctx, _, _, root = env
    api = ctx.directory_picker_controller
    entered, release = threading.Event(), threading.Event()
    def gated(*args, **kwargs):
        entered.set()
        release.wait()
        raise DirectoryPickerError('directory-create-failed', 'write outcome unknown')
    monkeypatch.setattr(api._picker, 'create_directory', gated)
    task = asyncio.create_task(api.create_directory(str(root), 'uncertain'))
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        ctx.work_root = tmp_path / 'different'
        release.set()
        with pytest.raises(RuntimeError) as error: await task
        assert error.value.code == 'directory-picker/host-changed' and error.value.may_have_changed
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_unclassified_native_create_failure_marks_possible_write(env, monkeypatch):
    from lamtools_core.plugin_system.directory_picker import DirectoryPickerError
    ctx, _, _, root = env
    api = ctx.directory_picker_controller
    def failed(*args, **kwargs): raise DirectoryPickerError('directory-create-failed', 'native error')
    monkeypatch.setattr(api._picker, 'create_directory', failed)
    with pytest.raises(RuntimeError) as error: await api.create_directory(str(root), 'unknown')
    assert error.value.code == 'directory-picker/create-failed' and error.value.may_have_changed


def test_migration_names_browse_and_explicit_unavailable_native(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root = source(tmp_path, {'index.ts': 'export function apply(ctx) { ctx.remote.directoryPicker.list(); ctx.remote.directoryPicker.createDirectory(); ctx.remote.directoryPicker.pick(); }'})
    report = export_port(root, tmp_path / 'ported')
    methods = {row['name']: row for row in report['remotes']}
    assert methods['directoryPicker.list']['suggestedContract'] == 'context.directory_picker_controller.list'
    assert methods['directoryPicker.createDirectory']['suggestedContract'] == 'context.directory_picker_controller.create_directory'
    assert 'unavailable' in methods['directoryPicker.pick']['difference']
    assert report['runtimeVerified'] is False


@pytest.mark.asyncio
async def test_real_http_browse_and_creation_require_valid_token(env, tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
    ctx, _, _, root = env
    host, catalog, original = _host(tmp_path)
    configure(host)
    ctx._secret_store = original._secret_store
    host.backend_manager.context = ctx
    (host.get('hook-demo').root / 'ops.py').write_text(
        'async def echo(request, *, context):\n'
        "    name = request.payload['body']['text']\n"
        "    if name == 'list': return await context.directory_picker_controller.list()\n"
        '    return {"path": await context.directory_picker_controller.create_directory(str(context.work_root), name)}\n', encoding='utf8')
    catalog.unregister_owner('plugin:hook-demo')
    register_plugin_operations(catalog, host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        path = '/plugin-remote/hook-demo/demo/echo'
        denied = await client.post(path, json={'args': {'text': 'should-not-exist'}}, headers={'x-plugin-token': 'bad'})
        assert denied.status_code == 401 and not (root / 'should-not-exist').exists()
        headers = {'x-plugin-token': plugin_http_token(host, 'hook-demo')}
        listing = await client.post(path, json={'args': {'text': 'list'}}, headers=headers)
        assert listing.status_code == 200 and listing.json()['payload']['path'] == str(root)
        created = await client.post(path, json={'args': {'text': 'http-created'}}, headers=headers)
        assert created.status_code == 200 and (root / 'http-created').is_dir()
