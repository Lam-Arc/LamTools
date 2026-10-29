"""user:“每一个地方 sunday 都有等价或者近似接口”+(先验收宿主服务注册、依赖、代际撤回与资源清理，再移植 DSH 消费方)。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Protocol, runtime_checkable

import pytest

from lamtools_core.plugin_system.context import PluginContext
from lamtools_core.plugin_system.services import ServiceError, ServiceKey
from lamtools_core.plugin_system.lifecycle import (
    PluginLifecycleError, PluginRuntimeHandle, start_plugin_backend, stop_plugin_backend,
)
from lamtools_core.plugin_system.manifest import PluginManifest


@runtime_checkable
class Echo(Protocol):
    def echo(self, text: str) -> str: ...


ECHO = ServiceKey[Echo]("demo.echo", protocol=Echo)


class EchoService:
    def echo(self, text: str) -> str:
        return text


def handle(root: PluginContext, name: str, start, stop=None, health=None):
    context = root.for_work_root(root.work_root)
    return PluginRuntimeHandle(
        PluginManifest(name, "1", root=Path(root.work_root)),
        {"start": start, **({"stop": stop} if stop else {}), **({"health_check": health} if health else {})},
        context=context,
    )


@pytest.mark.asyncio
async def test_startup_stages_services_until_health_and_atomically_publishes(tmp_path):
    root = PluginContext(tmp_path)
    entered, release = asyncio.Event(), asyncio.Event()
    service = EchoService()
    async def start(ctx):
        ctx.register_service(ECHO, service)
        assert ctx.require_service(ECHO.name) is service
        entered.set()
        await release.wait()
    plugin = handle(root, "provider", start)
    task = asyncio.create_task(start_plugin_backend(plugin, root))
    await entered.wait()
    assert root.service(ECHO.name) is None
    release.set()
    await task
    try:
        ref = root.bind_service(ECHO)
        assert await ref.call("echo", "hello") == "hello"
        row = next(r for r in root.describe_host()["services"] if r["name"] == ECHO.name)
        assert row["owner"] == "provider" and row["version"] == 1 and row["epoch"] == 1
    finally:
        await stop_plugin_backend(plugin)


@pytest.mark.asyncio
async def test_missing_dependency_prevents_publication_and_releases_effects(tmp_path):
    root = PluginContext(tmp_path)
    cleaned = []
    def start(ctx):
        ctx.on_dispose(lambda: cleaned.append("closed"))
        ctx.register_service(ECHO, EchoService())
        ctx.bind_service(ServiceKey("missing"))
    plugin = handle(root, "consumer", start)
    with pytest.raises(PluginLifecycleError, match="missing"):
        await start_plugin_backend(plugin, root)
    assert root.service(ECHO.name) is None
    await stop_plugin_backend(plugin)
    assert cleaned == ["closed"]


@pytest.mark.asyncio
async def test_health_failure_never_publishes_registered_services(tmp_path):
    root = PluginContext(tmp_path)
    plugin = handle(root, "bad", lambda ctx: ctx.register_service(ECHO, EchoService()), health=lambda: False)
    with pytest.raises(PluginLifecycleError):
        await start_plugin_backend(plugin, root)
    assert root.service(ECHO.name) is None
    await stop_plugin_backend(plugin)


@pytest.mark.asyncio
async def test_conflict_rolls_back_entire_new_publication_without_overwriting_host(tmp_path):
    root = PluginContext(tmp_path, services={"reserved": object()})
    original = root.service("reserved")
    def start(ctx):
        ctx.register_service(ECHO, EchoService())
        ctx.register_service("reserved", object())
    plugin = handle(root, "conflict", start)
    with pytest.raises(PluginLifecycleError, match="reserved"):
        await start_plugin_backend(plugin, root)
    assert root.service(ECHO.name) is None and root.service("reserved") is original
    await stop_plugin_backend(plugin)


@pytest.mark.asyncio
async def test_old_registration_and_reference_cannot_affect_restarted_epoch(tmp_path):
    root = PluginContext(tmp_path)
    registrations = []
    service = EchoService()
    plugin = handle(root, "provider", lambda ctx: registrations.append(ctx.register_service(ECHO, service)))
    await start_plugin_backend(plugin, root)
    old = root.bind_service(ECHO)
    await stop_plugin_backend(plugin)
    with pytest.raises(ServiceError):
        await old.call("echo", "old")
    await start_plugin_backend(plugin, root)
    try:
        registrations[0]()
        assert root.service(ECHO.name) is service
        assert await root.bind_service(ECHO).call("echo", "new") == "new"
        with pytest.raises(ServiceError):
            await old.call("echo", "still old")
    finally:
        await stop_plugin_backend(plugin)


@pytest.mark.asyncio
async def test_unload_drains_active_service_call_before_running_stop_or_effects(tmp_path):
    root = PluginContext(tmp_path)
    entered, release = asyncio.Event(), asyncio.Event()
    cleaned = []
    class Slow:
        async def echo(self, text):
            entered.set()
            await release.wait()
            return text
    def start(ctx):
        ctx.register_service(ECHO, Slow())
        ctx.on_dispose(lambda: cleaned.append("effect"))
    plugin = handle(root, "slow", start, stop=lambda: cleaned.append("stop"))
    await start_plugin_backend(plugin, root)
    ref = root.bind_service(ECHO)
    calling = asyncio.create_task(ref.call("echo", "done"))
    await entered.wait()
    stopping = asyncio.create_task(stop_plugin_backend(plugin))
    await asyncio.sleep(0)
    assert root.service(ECHO.name) is None and cleaned == [] and not stopping.done()
    with pytest.raises(ServiceError):
        await ref.call("echo", "new")
    release.set()
    assert await calling == "done"
    await stopping
    assert cleaned == ["stop", "effect"]


@pytest.mark.asyncio
async def test_cleanup_is_lifo_async_and_idempotent_even_when_stop_raises(tmp_path):
    root = PluginContext(tmp_path)
    order = []
    async def last():
        await asyncio.sleep(0)
        order.append(2)
    def start(ctx):
        ctx.effect(lambda: lambda: order.append(1))
        ctx.on_dispose(last)
    def stop():
        raise ValueError("stop failed")
    plugin = handle(root, "cleanup", start, stop=stop)
    await start_plugin_backend(plugin, root)
    with pytest.raises(PluginLifecycleError, match="stop failed"):
        await stop_plugin_backend(plugin)
    assert order == [2, 1]
    # Retrying legacy stop may fail again; owned effects must not repeat.
    with pytest.raises(PluginLifecycleError):
        await stop_plugin_backend(plugin)
    assert order == [2, 1]


@pytest.mark.asyncio
async def test_one_failed_disposer_does_not_skip_others_and_can_be_retried(tmp_path):
    root = PluginContext(tmp_path)
    order, fail = [], True
    def flaky():
        nonlocal fail
        if fail:
            fail = False
            raise ValueError("cleanup retry")
        order.append("retried")
    def start(ctx):
        ctx.on_dispose(lambda: order.append("first"))
        ctx.on_dispose(flaky)
        ctx.on_dispose(lambda: order.append("last"))
    plugin = handle(root, "flaky", start)
    await start_plugin_backend(plugin, root)
    with pytest.raises(PluginLifecycleError):
        await stop_plugin_backend(plugin)
    assert order == ["last", "first"]
    await stop_plugin_backend(plugin)
    assert order == ["last", "first", "retried"]


@pytest.mark.asyncio
async def test_version_protocol_and_scope_checks_are_explicit(tmp_path):
    root = PluginContext(tmp_path)
    with pytest.raises(ServiceError, match="managed startup"):
        root.register_service(ECHO, EchoService())
    def start(ctx):
        with pytest.raises(TypeError):
            ctx.register_service(ECHO, object())
        ctx.register_service(ServiceKey("versioned", version=2), EchoService())
    plugin = handle(root, "provider", start)
    await start_plugin_backend(plugin, root)
    try:
        with pytest.raises(ServiceError, match="version"):
            root.bind_service(ServiceKey("versioned", version=1))
        assert await root.bind_service(ServiceKey("versioned", version=2)).call("echo", "v2") == "v2"
    finally:
        await stop_plugin_backend(plugin)


@pytest.mark.asyncio
async def test_scoped_secrets_do_not_leak_into_shared_registry_and_hosts_are_isolated(tmp_path):
    root = PluginContext(tmp_path, scoped_services={"private": "root-only"})
    other = PluginContext(tmp_path)
    plugin = handle(root, "provider", lambda ctx: ctx.register_service(ECHO, EchoService()))
    await start_plugin_backend(plugin, root)
    try:
        assert other.service(ECHO.name) is None
        private = root.for_work_root(tmp_path)
        private.set_scoped_service(ECHO.name, EchoService())
        assert private.bind_service(ECHO).get() is private.service(ECHO.name)
        assert root.bind_service(ECHO).get() is not private.service(ECHO.name)
    finally:
        await stop_plugin_backend(plugin)


@pytest.mark.asyncio
async def test_dependency_removed_during_consumer_start_aborts_its_publication(tmp_path):
    root = PluginContext(tmp_path)
    provider = handle(root, "provider", lambda ctx: ctx.register_service(ECHO, EchoService()))
    entered, release = asyncio.Event(), asyncio.Event()
    async def start(ctx):
        ctx.bind_service(ECHO)
        ctx.register_service("consumer.ready", object())
        entered.set()
        await release.wait()
    consumer = handle(root, "consumer", start)
    await start_plugin_backend(provider, root)
    task = asyncio.create_task(start_plugin_backend(consumer, root))
    await entered.wait()
    await stop_plugin_backend(provider)
    release.set()
    with pytest.raises(PluginLifecycleError):
        await task
    assert root.service("consumer.ready") is None
    await stop_plugin_backend(consumer)


@pytest.mark.asyncio
async def test_requester_reference_is_invalid_after_requester_restart(tmp_path):
    root = PluginContext(tmp_path)
    provider = handle(root, "provider", lambda ctx: ctx.register_service(ECHO, EchoService()))
    references = []
    consumer = handle(root, "consumer", lambda ctx: references.append(ctx.bind_service(ECHO)))
    await start_plugin_backend(provider, root)
    await start_plugin_backend(consumer, root)
    await stop_plugin_backend(consumer)
    await start_plugin_backend(consumer, root)
    try:
        with pytest.raises(ServiceError):
            await references[0].call("echo", "old")
        assert await references[1].call("echo", "current") == "current"
    finally:
        await stop_plugin_backend(consumer)
        await stop_plugin_backend(provider)


@pytest.mark.asyncio
async def test_provider_health_revocation_invalidates_service_reference_immediately(tmp_path):
    from lamtools_core.plugin_system.lifecycle import _failed
    root = PluginContext(tmp_path)
    plugin = handle(root, "provider", lambda ctx: ctx.register_service(ECHO, EchoService()))
    await start_plugin_backend(plugin, root)
    ref = root.bind_service(ECHO)
    _failed(plugin, "health", RuntimeError("provider died"))
    assert root.service(ECHO.name) is None
    with pytest.raises(ServiceError):
        ref.get()
    await stop_plugin_backend(plugin)


@pytest.mark.asyncio
async def test_cancellation_of_cleanup_caller_does_not_cancel_owned_cleanup(tmp_path):
    root = PluginContext(tmp_path)
    entered, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()
    async def cleanup():
        entered.set()
        await release.wait()
        finished.set()
    plugin = handle(root, "provider", lambda ctx: ctx.on_dispose(cleanup))
    await start_plugin_backend(plugin, root)
    stopping = asyncio.create_task(stop_plugin_backend(plugin))
    await entered.wait()
    stopping.cancel()
    with pytest.raises(asyncio.CancelledError):
        await stopping
    assert not finished.is_set()
    release.set()
    await stop_plugin_backend(plugin)
    assert finished.is_set()


@pytest.mark.asyncio
async def test_context_views_share_registration_owner_but_unrelated_plugins_cannot_register_after_stop(tmp_path):
    root = PluginContext(tmp_path)
    views = []
    def start(ctx):
        view = ctx.for_work_root(tmp_path / "project")
        views.append(view)
        view.register_service(ECHO, EchoService())
    plugin = handle(root, "provider", start)
    await start_plugin_backend(plugin, root)
    await stop_plugin_backend(plugin)
    with pytest.raises(ServiceError):
        views[0].register_service("late", object())
    assert root.service("late") is None


@pytest.mark.asyncio
async def test_self_stop_is_rejected_without_waiting_for_its_own_call(tmp_path):
    root = PluginContext(tmp_path)
    class SelfStopping:
        async def close(self):
            await stop_plugin_backend(plugin)
    plugin = handle(root, "provider", lambda ctx: ctx.register_service("selfstop", SelfStopping()))
    await start_plugin_backend(plugin, root)
    with pytest.raises(PluginLifecycleError, match="own active service call"):
        await root.bind_service("selfstop").call("close")
    await stop_plugin_backend(plugin)


@pytest.mark.asyncio
async def test_manual_host_withdrawal_invalidates_even_provider_local_reference(tmp_path):
    root = PluginContext(tmp_path)
    refs = []
    def start(ctx):
        ctx.register_service(ECHO, EchoService())
        refs.append(ctx.bind_service(ECHO))
    plugin = handle(root, "provider", start)
    await start_plugin_backend(plugin, root)
    try:
        with pytest.raises(ServiceError, match="conflict"):
            root.set_service(ECHO.name, object())
        root.remove_service(ECHO.name)
        with pytest.raises(ServiceError):
            refs[0].get()
    finally:
        await stop_plugin_backend(plugin)


@pytest.mark.asyncio
async def test_actual_loader_startup_failure_unwinds_effects_automatically(tmp_path):
    import json
    from lamtools_core.plugin_system.lifecycle import load_enabled_plugin_backends, await_plugin_backends
    from lamtools_core.plugin_system.manifest import load_manifest
    plugin_root = tmp_path / "plugin"
    plugin_root.mkdir()
    (plugin_root / "plugin.json").write_text(json.dumps({"name": "failed-plugin", "version": "1", "backend": "./backend.py"}))
    (plugin_root / "backend.py").write_text('''
def create_plugin(ctx):
    class Runtime:
        def start(self, context):
            context.on_dispose(lambda: context.require_service('cleanup_log').append('disposed'))
            context.register_service('test.staged', object())
            raise ValueError('initialization failed')
    return Runtime()
''')
    log = []
    root = PluginContext(tmp_path, services={"cleanup_log": log})
    handles = load_enabled_plugin_backends([load_manifest(plugin_root / "plugin.json")], root, start=True)
    await await_plugin_backends(handles)
    assert log == ["disposed"]
    assert root.service("test.staged") is None
    assert handles[0].state == "failed"


@pytest.mark.asyncio
async def test_health_monitor_failure_automatically_cleans_owned_effects(tmp_path):
    root = PluginContext(tmp_path)
    cleaned = []
    health_calls = 0
    def health():
        nonlocal health_calls
        health_calls += 1
        return health_calls == 1
    def start(ctx):
        ctx.register_service(ECHO, EchoService())
        ctx.on_dispose(lambda: cleaned.append("closed"))
    plugin = handle(root, "provider", start, health=health)
    await start_plugin_backend(plugin, root)
    await plugin.monitor_task
    assert root.service(ECHO.name) is None
    assert cleaned == ["closed"] and plugin.state == "failed"


@pytest.mark.asyncio
async def test_existing_supervisor_owns_dynamic_services_across_disable_enable(tmp_path):
    import json
    from lamtools_core.plugin_system.host import PluginHost
    from lamtools_core.plugin_system.backend_runtime import register_manager
    plugin_root = tmp_path / "plugins" / "real-provider"
    plugin_root.mkdir(parents=True)
    (plugin_root / "plugin.json").write_text(json.dumps({"name": "real-provider", "version": "1", "backend": "./backend.py"}))
    (plugin_root / "backend.py").write_text('''
class Runtime:
    def start(self, ctx):
        ctx.register_service('real.echo', self)
    def echo(self, value):
        return value
def create_plugin(ctx):
    return Runtime()
''')
    root = PluginContext(tmp_path)
    host = PluginHost(roots=[tmp_path / "plugins"], state_path=tmp_path / "state.json")
    manager = register_manager(host, [], root)
    assert await manager.start("real-provider")
    old = root.bind_service("real.echo")
    assert await old.call("echo", "first") == "first"
    assert await manager.stop("real-provider")
    assert root.service("real.echo") is None
    assert await manager.start("real-provider")
    try:
        with pytest.raises(ServiceError):
            await old.call("echo", "old")
        assert await root.bind_service("real.echo").call("echo", "second") == "second"
    finally:
        await manager.stop("real-provider")


@pytest.mark.asyncio
async def test_ready_plugin_can_register_and_withdraw_a_service_without_affecting_siblings(tmp_path):
    root = PluginContext(tmp_path)
    contexts = []
    plugin = handle(root, "provider", lambda ctx: contexts.append(ctx))
    await start_plugin_backend(plugin, root)
    try:
        context = contexts[0]
        unregister = context.register_service("late.echo", EchoService())
        context.register_service("sibling", object())
        ref = root.bind_service("late.echo")
        assert await ref.call("echo", "late") == "late"
        unregister()
        unregister()
        assert root.service("sibling") is not None
        with pytest.raises(ServiceError):
            ref.get()
    finally:
        await stop_plugin_backend(plugin)
    assert root.service("sibling") is None


@pytest.mark.asyncio
async def test_restart_is_blocked_until_previous_failed_cleanup_finishes(tmp_path):
    root = PluginContext(tmp_path)
    failed = False
    def cleanup():
        nonlocal failed
        if not failed:
            failed = True
            raise RuntimeError("try again")
    def start(ctx):
        ctx.register_service(ECHO, EchoService())
        ctx.on_dispose(cleanup)
    plugin = handle(root, "provider", start)
    await start_plugin_backend(plugin, root)
    with pytest.raises(PluginLifecycleError):
        await stop_plugin_backend(plugin)
    with pytest.raises(PluginLifecycleError, match="finish cleanup"):
        await start_plugin_backend(plugin, root)
    assert root.service(ECHO.name) is None
    await stop_plugin_backend(plugin)
    await start_plugin_backend(plugin, root)
    assert root.service(ECHO.name) is not None
    await stop_plugin_backend(plugin)
