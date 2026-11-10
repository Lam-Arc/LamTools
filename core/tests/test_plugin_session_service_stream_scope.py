"""user:“复用原宿主权威”+(撤回的插件和替换的会话服务不得继续读取旧事件流)。"""
import asyncio
import pytest
from .test_plugin_session_control import host, append
from .test_plugin_session_query import env
from lamtools_core.app.plugin_sessions import install_plugin_session_services
from lamtools_core.plugin_system.context import PluginContext
from lamtools_core.plugin_system.sessions import SESSIONS
from lamtools_core.plugin_system.sessions import SessionError
from lamtools_core.plugin_system.services import ServiceError


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['requester', 'provider'])
async def test_service_stream_rechecks_lifetime_before_first_read(host, tmp_path, change):
    live, original = host
    await original.create(session_id='s')
    ctx = PluginContext(tmp_path)
    service = install_plugin_session_services(ctx, lambda: live)
    ctx._begin_registration_scope('reader', 1)
    stream = await ctx.bind_service(SESSIONS).call('follow', 's')
    try:
        if change == 'requester':
            await ctx._registration_scope.dispose()
        else:
            replacement = install_plugin_session_services(ctx, lambda: live)
        with pytest.raises(ServiceError):
            await asyncio.wait_for(anext(stream), 2)
    finally:
        await stream.aclose()
        service.shutdown()
        if change == 'provider':
            replacement.shutdown()
            await ctx._registration_scope.dispose()


@pytest.mark.asyncio
async def test_revoke_during_read_drops_event_and_closes_underlying_stream(host, tmp_path, monkeypatch):
    live, original = host
    await original.create(session_id='s')
    ctx = PluginContext(tmp_path)
    service = install_plugin_session_services(ctx, lambda: live)
    ctx._begin_registration_scope('reader', 1)
    entered, release = asyncio.Event(), asyncio.Event()
    events = service.events
    async def gated(*args, **kwargs):
        page = await events(*args, **kwargs)
        entered.set()
        await release.wait()
        return page
    monkeypatch.setattr(service, 'events', gated)
    stream = await ctx.bind_service(SESSIONS).call('follow', 's')
    pending = asyncio.create_task(anext(stream))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        await ctx._registration_scope.dispose()
        release.set()
        with pytest.raises(ServiceError): await asyncio.wait_for(pending, 2)
        with pytest.raises(StopAsyncIteration): await anext(stream)
    finally:
        release.set()
        await asyncio.gather(pending, return_exceptions=True)
        await stream.aclose()
        service.shutdown()


@pytest.mark.asyncio
async def test_revoke_between_buffered_events_does_not_publish_stale_page(host, tmp_path):
    live, original = host
    await original.create(session_id='s')
    await append(live, 's', 'custom/two')
    ctx = PluginContext(tmp_path)
    service = install_plugin_session_services(ctx, lambda: live)
    ctx._begin_registration_scope('reader', 1)
    stream = await ctx.bind_service(SESSIONS).call('follow', 's')
    try:
        assert (await anext(stream))['seq'] == 1
        await ctx._registration_scope.dispose()
        with pytest.raises(ServiceError): await anext(stream)
    finally:
        await stream.aclose()
        service.shutdown()


@pytest.mark.asyncio
async def test_cancel_pending_pull_closes_stream_without_closing_session(host, tmp_path):
    live, original = host
    await original.create(session_id='s')
    ctx = PluginContext(tmp_path)
    service = install_plugin_session_services(ctx, lambda: live)
    ctx._begin_registration_scope('reader', 1)
    stream = await ctx.bind_service(SESSIONS).call('follow', 's', after_seq=1)
    pending = asyncio.create_task(anext(stream))
    try:
        await asyncio.sleep(0.03)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError): await pending
        with pytest.raises(StopAsyncIteration): await anext(stream)
        assert (await service.state('s')).session_id == 's'
    finally:
        await stream.aclose()
        await ctx._registration_scope.dispose()
        service.shutdown()


@pytest.mark.asyncio
async def test_follow_rechecks_original_store_between_buffered_events(host):
    live, service = host
    await service.create(session_id='s')
    await append(live, 's', 'custom/two')
    stream = service.follow('s')
    old = live.host.session_store
    try:
        assert (await anext(stream))['seq'] == 1
        live.host.session_store = object()
        with pytest.raises(SessionError) as error: await anext(stream)
        assert error.value.code == 'session/host-changed'
    finally:
        live.host.session_store = old
        await stream.aclose()


@pytest.mark.asyncio
async def test_follow_does_not_publish_buffered_events_after_visibility_revoked(env):
    _, store, service = env
    live = service._context()
    await append(live, 'a', 'custom/one')
    await append(live, 'a', 'custom/two')
    stream = service.follow('a')
    try:
        assert (await anext(stream))['seq'] == 1
        store._session_visible = lambda sid, meta: False
        with pytest.raises(SessionError) as error: await anext(stream)
        assert error.value.code == 'session/not-found'
    finally:
        await stream.aclose()


@pytest.mark.asyncio
async def test_shutdown_during_buffered_event_visibility_check_ends_stream(env, monkeypatch):
    _, store, service = env
    await append(service._context(), 'a', 'custom/one')
    stream = service.follow('a')
    original = store.get
    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0
    async def gated(*args, **kwargs):
        nonlocal calls
        calls += 1
        result = await original(*args, **kwargs)
        if calls == 2:
            entered.set()
            await release.wait()
        return result
    monkeypatch.setattr(store, 'get', gated)
    pending = asyncio.create_task(anext(stream))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        service.shutdown()
        release.set()
        with pytest.raises(StopAsyncIteration): await asyncio.wait_for(pending, 2)
    finally:
        release.set()
        await asyncio.gather(pending, return_exceptions=True)
        await stream.aclose()
