"""user:“完成真实接口、参数/错误、作用域、取消/清理”+(服务停用等待正在读取的流真实退出)。"""
import asyncio
import pytest
from .test_plugin_owned_services import handle
from lamtools_core.plugin_system.context import PluginContext
from lamtools_core.plugin_system.lifecycle import start_plugin_backend, stop_plugin_backend
from lamtools_core.plugin_system.services import ServiceError


@pytest.mark.asyncio
@pytest.mark.parametrize('who', ['provider', 'requester'])
async def test_scope_disposal_waits_for_inflight_stream_cleanup(tmp_path, who):
    entered, cleanup_started, release, cleaned, disposed = (asyncio.Event() for _ in range(5))
    class Provider:
        async def follow(self):
            try:
                entered.set()
                await asyncio.Event().wait()
                yield 'unreachable'
            finally:
                cleanup_started.set()
                await release.wait()
                cleaned.set()
    root = PluginContext(tmp_path)
    def start(ctx):
        ctx.register_service('source', Provider())
        ctx.on_dispose(disposed.set)
    plugin = handle(root, 'provider', start)
    await start_plugin_backend(plugin, root)
    reader = root.for_work_root(tmp_path)
    reader._begin_registration_scope('reader', 1)
    if who == 'requester': reader.on_dispose(disposed.set)
    stream = await reader.bind_service('source').call('follow')
    pending = asyncio.create_task(anext(stream))
    stopping = None
    try:
        await asyncio.wait_for(entered.wait(), 2)
        stopping = asyncio.create_task(stop_plugin_backend(plugin) if who == 'provider' else reader._registration_scope.dispose())
        await asyncio.wait_for(cleanup_started.wait(), 2)
        await asyncio.sleep(0)
        assert not stopping.done() and not disposed.is_set()
        release.set()
        await asyncio.wait_for(stopping, 2)
        with pytest.raises(ServiceError): await asyncio.wait_for(pending, 2)
        assert cleaned.is_set() and disposed.is_set()
    finally:
        release.set()
        await asyncio.gather(pending, *( [stopping] if stopping else [] ), return_exceptions=True)
        await stream.aclose()
        await reader._registration_scope.dispose()
        await stop_plugin_backend(plugin)


@pytest.mark.asyncio
async def test_stream_provider_cannot_stop_its_own_active_scope(tmp_path):
    from lamtools_core.plugin_system.lifecycle import PluginLifecycleError
    root = PluginContext(tmp_path)
    rejected = asyncio.Event()
    class Provider:
        async def follow(self):
            try:
                await stop_plugin_backend(plugin)
            except PluginLifecycleError as error:
                assert 'own active service call' in str(error)
                rejected.set()
                yield 'unreachable after withdrawal'
    plugin = handle(root, 'provider', lambda ctx: ctx.register_service('source', Provider()))
    await start_plugin_backend(plugin, root)
    stream = await root.bind_service('source').call('follow')
    try:
        with pytest.raises(ServiceError): await asyncio.wait_for(anext(stream), 1)
        assert rejected.is_set()
    finally:
        await stream.aclose()
        await stop_plugin_backend(plugin)


@pytest.mark.asyncio
async def test_caller_cancel_releases_lease_after_real_cleanup(tmp_path):
    entered, closing, release = (asyncio.Event() for _ in range(3))
    class Provider:
        async def follow(self):
            try:
                entered.set()
                await asyncio.Event().wait()
                yield 'unreachable'
            finally:
                closing.set()
                await release.wait()
    ctx = PluginContext(tmp_path)
    ctx.set_service('source', Provider())
    ctx._begin_registration_scope('reader', 1)
    stream = await ctx.bind_service('source').call('follow')
    pending = asyncio.create_task(anext(stream))
    stopping = None
    try:
        await asyncio.wait_for(entered.wait(), 2)
        pending.cancel()
        await asyncio.wait_for(closing.wait(), 2)
        stopping = asyncio.create_task(ctx._registration_scope.dispose())
        await asyncio.sleep(0)
        assert not stopping.done()
        release.set()
        with pytest.raises(asyncio.CancelledError): await asyncio.wait_for(pending, 2)
        await asyncio.wait_for(stopping, 2)
    finally:
        release.set()
        await asyncio.gather(pending, *( [stopping] if stopping else [] ), return_exceptions=True)
        await stream.aclose()
        await ctx._registration_scope.dispose()
