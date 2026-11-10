"""user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(作业名册持续反映当前可见快照)。"""
import asyncio

import pytest
from .test_plugin_working_directory import env


@pytest.mark.asyncio
async def test_roster_reports_visible_changes_and_removal(env):
    ctx, _, _, _ = env
    gate = asyncio.Event()
    async def work(job):
        await gate.wait()
    stream = ctx.job_controller.watch_list('s', interval=0.01)
    try:
        assert (await anext(stream))['jobs'] == ()
        hidden = ctx.jobs.start('task', 'hidden', work, session_id='other')
        own = ctx.jobs.start('task', 'own', work, session_id='s')
        shared = ctx.jobs.start('task', 'shared', work)
        rows = (await asyncio.wait_for(anext(stream), 2))['jobs']
        assert {j.id for j in rows} == {own.id, shared.id}
        gate.set()
        await asyncio.gather(own._done.wait(), shared._done.wait(), hidden._done.wait())
        rows = (await asyncio.wait_for(anext(stream), 2))['jobs']
        assert all(j.status == 'completed' for j in rows)
        ctx.jobs.remove(own.id)
        assert [j.id for j in (await asyncio.wait_for(anext(stream), 2))['jobs']] == [shared.id]
    finally:
        gate.set()
        await stream.aclose()


@pytest.mark.asyncio
async def test_roster_rechecks_session_and_cancel_does_not_stop_job(env):
    ctx, _, _, _ = env
    gate = asyncio.Event()
    async def work(job): await gate.wait()
    job = ctx.jobs.start('task', 'own', work, session_id='s')
    stream = ctx.job_controller.watch_list('s', interval=0.01)
    try:
        await anext(stream)
        pending = asyncio.create_task(anext(stream))
        await asyncio.sleep(0.03)
        assert not pending.done()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError): await pending
        assert not job._task.done()
    finally:
        gate.set()
        await stream.aclose()


@pytest.mark.asyncio
async def test_roster_stops_when_session_visibility_is_revoked(env):
    ctx, store, _, _ = env
    stream = ctx.job_controller.watch_list('s', interval=0.01)
    try:
        await anext(stream)
        store._session_visible = lambda sid, _: False
        with pytest.raises(RuntimeError):
            await asyncio.wait_for(anext(stream), 2)
    finally:
        await stream.aclose()


@pytest.mark.asyncio
async def test_roster_consumer_cannot_mutate_previous_snapshot(env):
    ctx, _, _, _ = env
    async def work(job): return {'value': 1}
    job = ctx.jobs.start('task', 'finished', work, session_id='s')
    await job._done.wait()
    stream = ctx.job_controller.watch_list('s', interval=0.01)
    try:
        first = await anext(stream)
        first['jobs'][0].result['value'] = 2
        pending = asyncio.create_task(anext(stream))
        await asyncio.sleep(0.03)
        assert not pending.done()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError): await pending
    finally:
        await stream.aclose()


@pytest.mark.asyncio
async def test_roster_http_disconnect_cleans_stream_without_stopping_job(env, tmp_path):
    import json
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from .test_plugin_remote_binary import set_encoding
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
    ctx, _, _, _ = env
    gate, disconnected = asyncio.Event(), asyncio.Event()
    async def work(job): await gate.wait()
    job = ctx.jobs.start('task', 'idle', work, session_id='s')
    host, catalog, original = _host(tmp_path)
    configure(host)
    set_encoding(host, 'ndjson')
    ctx._secret_store = original._secret_store
    host.backend_manager.context = ctx
    (host.get('hook-demo').root / 'ops.py').write_text(
        'from lamtools_core.app.operation_catalog import OperationResult\n'
        'def echo(request, *, context):\n'
        "    return OperationResult(request.name, context.job_controller.watch_list('s', interval=0.01))\n", encoding='utf8')
    catalog.unregister_owner('plugin:hook-demo')
    register_plugin_operations(catalog, host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    delivered, frames = False, []
    async def receive():
        nonlocal delivered
        if not delivered:
            delivered = True
            return {'type': 'http.request', 'body': json.dumps({'args': {'text': 'x'}}).encode(), 'more_body': False}
        await disconnected.wait()
        return {'type': 'http.disconnect'}
    async def send(message):
        if message['type'] == 'http.response.body' and message.get('body'):
            frames.append(json.loads(message['body']))
            disconnected.set()
    token = plugin_http_token(host, 'hook-demo')
    scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1', 'method': 'POST',
        'scheme': 'http', 'path': '/plugin-remote/hook-demo/demo/echo', 'query_string': b'',
        'headers': [(b'content-type', b'application/json'), (b'x-plugin-token', token.encode())],
        'client': ('127.0.0.1', 123), 'server': ('test', 80)}
    try:
        async with asyncio.timeout(3): await app(scope, receive, send)
        assert frames[0]['payload']['jobs'][0]['id'] == job.id
        assert not host._remote_stream_slots and not job._task.done()
    finally:
        gate.set()


def test_list_migration_names_roster_stream(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root = source(tmp_path, {'index.ts': 'export function apply(ctx) { ctx.remote.job.list(); }'})
    report = export_port(root, tmp_path / 'ported')
    item = next(row for row in report['remotes'] if row['name'] == 'job.list')
    # job.list 是一次性快照；watch_list 是轮询变化流，不能拿来顶替 list。
    assert item['suggestedContract'] == 'context.job_controller.list'
    assert report['runtimeVerified'] is False


@pytest.mark.asyncio
@pytest.mark.parametrize('interval', [0, 3, True, float('nan'), 'slow'])
async def test_invalid_interval_rejected_before_host_access(env, monkeypatch, interval):
    ctx, _, _, _ = env
    monkeypatch.setattr(ctx.require_service('working_directory'), 'for_scope',
                        lambda *args: pytest.fail('invalid interval accessed host'))
    with pytest.raises(ValueError):
        await anext(ctx.job_controller.watch_list('s', interval=interval))
