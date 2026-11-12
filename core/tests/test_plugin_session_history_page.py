"""user:“复用原宿主权威”+(会话历史页使用桌面端原持久分页)。"""
import asyncio
import json

import pytest
from .test_plugin_checkpoint_access import setup
from .test_plugin_working_directory import env
from .test_core_checkpoint_graph import _append_production_turn


@pytest.mark.asyncio
async def test_history_pages_read_native_turns_and_continue_backward(setup):
    ctx, _, _, _, db = setup
    for number in range(3):
        await _append_production_turn(db, 's', f'turn{number}', f'message{number}')
    latest = await ctx.session_controller.history_page('s', turn_limit=1)
    assert 'message2' in json.dumps(latest) and latest['page']['has_more']
    cursor = latest['page']['next_before_seq']
    previous = await ctx.session_controller.history_page('s', before_seq=cursor, turn_limit=1)
    assert 'message1' in json.dumps(previous) and 'message2' not in json.dumps(previous)
    assert 'session' not in latest and 'queue' not in latest


@pytest.mark.asyncio
@pytest.mark.parametrize('before,turns,bytes_limit', [(True, 1, 65536), (-1, 1, 65536), (None, 0, 65536), (None, 51, 65536), (None, 1, 1024)])
async def test_history_page_validates_budgets(setup, before, turns, bytes_limit):
    ctx, _, _, _, _ = setup
    with pytest.raises(ValueError):
        await ctx.session_controller.history_page('s', before_seq=before, turn_limit=turns, max_bytes=bytes_limit)


@pytest.mark.asyncio
async def test_missing_bounded_native_history_is_not_replaced_by_full_load(setup, monkeypatch):
    ctx, _, sessions, _, _ = setup
    persistence = sessions._context().persistence
    monkeypatch.setattr(persistence, 'load_page', None)
    with pytest.raises(RuntimeError) as error:
        await ctx.session_controller.history_page('s')
    assert error.value.code == 'session-controller/unavailable'


@pytest.mark.asyncio
async def test_history_page_revocation_after_native_read_rejects_result(setup, monkeypatch):
    from lamtools_core.app.live import threads
    ctx, store, _, _, db = setup
    await _append_production_turn(db, 's', 'one', 'secret')
    original = threads._load_thread_page
    entered, release = asyncio.Event(), asyncio.Event()
    async def gated(*args, **kwargs):
        result = await original(*args, **kwargs)
        entered.set(); await release.wait()
        return result
    monkeypatch.setattr(threads, '_load_thread_page', gated)
    task = asyncio.create_task(ctx.session_controller.history_page('s'))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        store._session_visible = lambda *_: False
        release.set()
        with pytest.raises(RuntimeError): await task
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_history_page_rechecks_host_after_page_assembly(setup, monkeypatch):
    from lamtools_core.app import thread_history
    ctx, store, sessions, _, db = setup
    await _append_production_turn(db, 's', 'one', 'secret')
    host = sessions._context().host
    original = thread_history._character_page_snapshot
    def replaced(*args, **kwargs):
        result = original(*args, **kwargs)
        host.session_store = object()
        return result
    monkeypatch.setattr(thread_history, '_character_page_snapshot', replaced)
    try:
        with pytest.raises(RuntimeError): await ctx.session_controller.history_page('s')
    finally:
        host.session_store = store


@pytest.mark.asyncio
async def test_history_page_rechecks_visibility_after_page_assembly(setup, monkeypatch):
    from lamtools_core.app import thread_history
    ctx, store, _, _, db = setup
    await _append_production_turn(db, 's', 'one', 'secret')
    original = thread_history._character_page_snapshot
    def hidden(*args, **kwargs):
        result = original(*args, **kwargs)
        store._session_visible = lambda *_: False
        return result
    monkeypatch.setattr(thread_history, '_character_page_snapshot', hidden)
    with pytest.raises(RuntimeError): await ctx.session_controller.history_page('s')


@pytest.mark.asyncio
async def test_repeated_cancel_waits_for_history_read_cleanup(setup, monkeypatch):
    from lamtools_core.app.live import threads
    ctx, _, _, _, _ = setup
    entered, cleaning, release, closed = (asyncio.Event() for _ in range(4))
    async def gated(*args, **kwargs):
        entered.set()
        try: await asyncio.Event().wait()
        finally: cleaning.set(); await release.wait(); closed.set()
    monkeypatch.setattr(threads, '_load_thread_page', gated)
    task = asyncio.create_task(ctx.session_controller.history_page('s'))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        task.cancel(); await asyncio.wait_for(cleaning.wait(), 3); task.cancel()
        assert not task.done() and not ctx._registration_scope._idle.is_set()
        release.set()
        with pytest.raises(asyncio.CancelledError): await task
        assert closed.is_set() and ctx._registration_scope._idle.is_set()
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_oversized_original_item_does_not_bypass_remote_budget(setup):
    ctx, _, _, _, db = setup
    await _append_production_turn(db, 's', 'large', 'x' * 180000)
    with pytest.raises(RuntimeError) as error:
        await ctx.session_controller.history_page('s', max_bytes=65536)
    assert error.value.code == 'session-controller/history-too-large'


@pytest.mark.asyncio
async def test_history_page_via_authenticated_remote(setup, tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
    ctx, _, _, _, db = setup
    await _append_production_turn(db, 's', 'http', 'real history')
    host, catalog, original = _host(tmp_path); configure(host)
    ctx._secret_store = original._secret_store; host.backend_manager.context = ctx
    (host.get('hook-demo').root / 'ops.py').write_text(
        'async def echo(request, *, context):\n'
        '    return await context.session_controller.history_page(request.payload["body"]["text"])\n', encoding='utf8')
    catalog.unregister_owner('plugin:hook-demo'); register_plugin_operations(catalog, host)
    app = FastAPI(); app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        url = '/plugin-remote/hook-demo/demo/echo'
        async def request(sid, token):
            return await client.post(url, json={'args': {'text': sid}}, headers={'x-plugin-token': token})
        token = plugin_http_token(host, 'hook-demo')
        denied = await request('s', 'wrong'); hidden = await request('hidden', token); result = await request('s', token)
    assert denied.status_code == 401 and hidden.status_code != 200 and result.status_code == 200
    assert 'real history' in result.text and 'snapshot_page' not in result.text


def test_history_page_migration_distinguishes_native_snapshot(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root = source(tmp_path, {'index.ts': 'export function apply(ctx) { ctx.remote.session.page(); }'})
    report = export_port(root, tmp_path / 'ported')
    row = next(item for item in report['remotes'] if item['name'] == 'session.page')
    assert row['suggestedContract'] == 'context.session_controller.history_page'
    assert '非DSH' in row['difference'] and report['runtimeVerified'] is False
