"""Backend readiness is independent of the installed/enabled preference."""

import asyncio
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
import pytest_asyncio

from lamtools_core.app.operation_catalog import OperationResult
from lamtools_core.plugins.context import PluginContext
from lamtools_core.plugins.lifecycle import (
    PluginLifecycleError, PluginRuntimeManager, await_plugin_backends,
    load_enabled_plugin_backends, shutdown_plugin_backends, start_plugin_backend,
)
from lamtools_core.plugins.operations import build_plugin_operation_catalog
from lamtools_core.plugins.registry import PluginRegistry, PluginStateStore
from lamtools_core.plugins.trust import HookTrustStore


SOURCE = '''
import asyncio
class Runtime:
    def __init__(self):
        self.calls = self.stops = 0
        self.fail = False
        self.gate = None
        self.healthy = True
        self.lifecycle_tasks = []
        self.lifecycle_processes = []
        self.services = {"test": self}
    async def start(self, context):
        self.calls += 1
        if self.gate is not None:
            await self.gate.wait()
        if self.fail:
            raise ValueError("startup exploded")
    async def stop(self):
        self.stops += 1
    def health_check(self):
        return {"ready": self.healthy, "error": "health probe failed"}
def create_plugin(context):
    return Runtime()
'''


@pytest_asyncio.fixture
async def plugin_host(tmp_path, monkeypatch):
    all_handles = []
    sequence = 0
    def make(*, source=SOURCE, start=True):
        nonlocal sequence
        sequence += 1
        root = tmp_path / str(sequence)
        plugin = root / "plugins" / "example"
        plugin.mkdir(parents=True)
        (plugin / "backend.py").write_text(source, encoding="utf-8")
        (plugin / "entry.ts").write_text("export default {}", encoding="utf-8")
        (plugin / "operations.json").write_text(json.dumps({"operations": [{
            "name": "example.check", "handler": "startup_contract_example:operation",
        }]}), encoding="utf-8")
        (plugin / "plugin.json").write_text(json.dumps({
            "name": "example", "version": "1.0", "backend": "./backend.py",
            "operations": ["./operations.json"],
            "ui": {"modes": [{"id": "example", "title": "Example", "entry": "./entry.ts"}]},
        }), encoding="utf-8")
        state = PluginStateStore(root / "state.jsonc")
        registry = PluginRegistry(plugin_roots=[plugin.parent], state_store=state)
        context = PluginContext(work_root=root, services={
            "plugin.lifecycle.start_timeout": .05,
            "plugin.lifecycle.stop_timeout": .05,
            "plugin.lifecycle.health_timeout": .05,
        })
        handles = load_enabled_plugin_backends(registry.discover(), context, start=start)
        all_handles.extend(handles)
        module = ModuleType("startup_contract_example")
        async def operation(request, **kwargs):
            return OperationResult(name=request.name, payload={"working": True})
        module.operation = operation
        monkeypatch.setitem(sys.modules, module.__name__, module)
        catalog = build_plugin_operation_catalog(
            plugin_registry=registry, plugin_state_store=state,
            hook_registry_factory=lambda: SimpleNamespace(load=lambda: []),
            hook_trust_store=HookTrustStore(root / "trust.json"), context=context,
            plugin_runtimes=handles, work_root=root, data_dir=root,
        )
        return SimpleNamespace(context=context, handles=handles, handle=handles[0],
            manager=context.service("plugin.runtime_manager"), catalog=catalog,
            registry=registry, state=state, plugin_dir=plugin)
    yield make
    await shutdown_plugin_backends(all_handles)


@pytest.mark.asyncio
async def test_starting_is_not_ready_or_published_until_start_and_health_finish(plugin_host):
    host = plugin_host()
    host.handle.value.gate = asyncio.Event()
    assert not host.manager.is_enabled("example")
    assert host.context.service("example") is None
    assert not host.catalog.has("example.check")
    assert (await host.catalog.execute("plugin.ui.list")).payload["modes"] == []
    host.handle.value.gate.set()
    await await_plugin_backends(host.handles)
    assert host.manager.is_enabled("example")
    assert host.handle.started and host.handle.state == "ready"
    assert host.context.service("example") is host.handle.value
    assert host.catalog.has("example.check")
    assert (await host.catalog.execute("example.check")).payload["working"]


@pytest.mark.asyncio
async def test_start_exception_keeps_enabled_preference_but_revokes_availability_and_reports_error(plugin_host):
    host = plugin_host()
    host.handle.value.fail = True
    await await_plugin_backends(host.handles)
    assert host.handle.state == "failed" and not host.handle.started
    assert not host.manager.is_enabled("example")
    assert host.context.service("example") is None
    assert host.context.service("example.test") is None
    assert host.handle.value.stops == 1
    row = (await host.catalog.execute("plugin.list")).payload["plugins"][0]
    assert row["enabled"] is True and row["available"] is False
    assert "startup exploded" in row["backend"]["error"]["message"]
    assert row["backend"]["error"]["type"] == "ValueError"
    with pytest.raises(KeyError):
        await host.catalog.execute("example.check")
    response = await host.catalog.execute("plugin.enable", {"name": "example"})
    assert response.status == "error" and not response.payload["available"]
    assert response.payload["backend"]["state"] == "failed"
    assert "startup exploded" in response.payload["error"]


@pytest.mark.asyncio
async def test_retry_reuses_runtime_and_publishes_only_after_success(plugin_host):
    host = plugin_host()
    runtime = host.handle.value
    runtime.fail = True
    await await_plugin_backends(host.handles)
    runtime.fail = False
    responses = await asyncio.gather(*(host.catalog.execute("plugin.enable", {"name": "example"}) for _ in range(2)))
    assert all(result.status == "ok" and result.payload["available"] for result in responses)
    assert host.handle.value is runtime and runtime.calls == 2
    assert host.handle.error is None and "startup exploded" in host.handle.last_error["message"]
    assert host.catalog.has("example.check")
    assert len((await host.catalog.execute("plugin.ui.list")).payload["modes"]) == 1


@pytest.mark.asyncio
async def test_factory_failure_is_listed_and_can_reload_on_retry(plugin_host, monkeypatch):
    host = plugin_host(source="raise ImportError('missing dependency')")
    assert host.handle.value is None and host.handle.state == "failed"
    row = (await host.catalog.execute("plugin.list")).payload["plugins"][0]
    assert "missing dependency" in row["backend"]["error"]["message"]
    assert not row["available"]
    # Repair the factory; module loading retries the failed entry.
    (host.plugin_dir / "backend.py").write_text(SOURCE, encoding="utf-8")
    response = await host.catalog.execute("plugin.enable", {"name": "example"})
    assert response.status == "ok" and response.payload["available"]
    assert host.handle.value.calls == 1


@pytest.mark.asyncio
async def test_start_timeout_is_observable_and_cooperative_retry_succeeds(plugin_host):
    host = plugin_host()
    host.handle.value.gate = asyncio.Event()
    await asyncio.wait_for(await_plugin_backends(host.handles), .5)
    assert host.handle.state == "failed" and not host.manager.is_enabled("example")
    assert host.handle.error["code"] == "PLUGIN_BACKEND_TIMEOUT"
    assert host.context.service("example") is None
    host.handle.value.gate.set()
    assert await host.manager.start("example")
    assert host.handle.state == "ready" and host.handle.started


@pytest.mark.asyncio
async def test_late_uncancellable_start_cannot_publish_ready_or_overlap_retry(plugin_host):
    source = SOURCE.replace('await self.gate.wait()', '''
            try:
                await self.gate.wait()
            except asyncio.CancelledError:
                await self.gate.wait()''')
    host = plugin_host(source=source)
    host.handle.value.gate = asyncio.Event()
    await asyncio.wait_for(await_plugin_backends(host.handles), .5)
    assert host.handle.state == "failed" and host.handle.pending_tasks
    with pytest.raises(PluginLifecycleError):
        await host.manager.start("example")
    assert host.handle.value.calls == 1 and not host.manager.is_enabled("example")
    host.handle.value.gate.set()
    await asyncio.gather(*host.handle.pending_tasks)
    await asyncio.sleep(0)
    assert host.handle.state == "failed" and host.context.service("example") is None
    assert await host.manager.start("example")


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", ["exit", "error", "cancel"])
async def test_registered_critical_task_termination_revokes_stale_capabilities(plugin_host, ending):
    host = plugin_host()
    await await_plugin_backends(host.handles)
    task = asyncio.get_running_loop().create_future()
    host.handle.value.lifecycle_tasks.append(task)
    if ending == "error":
        task.set_exception(RuntimeError("critical loop crashed"))
    elif ending == "cancel":
        task.cancel()
    else:
        task.set_result(None)
    assert not host.manager.is_enabled("example")
    assert host.handle.state == "failed" and host.handle.error["phase"] == "health"
    assert not host.catalog.has("example.check")
    assert (await host.catalog.execute("plugin.ui.list")).payload["modes"] == []
    assert host.context.service("example") is None
    host.handle.value.lifecycle_tasks.clear()
    assert await host.manager.start("example")


@pytest.mark.asyncio
async def test_health_monitor_detects_asynchronous_failure_without_an_rpc_poll(plugin_host):
    host = plugin_host()
    await await_plugin_backends(host.handles)
    host.handle.value.healthy = False
    async def failed():
        while host.handle.state != "failed":
            await asyncio.sleep(.01)
    await asyncio.wait_for(failed(), 2)
    assert "health probe failed" in host.handle.error["message"]
    assert host.context.service("example") is None
    host.handle.value.healthy = True
    assert await host.manager.start("example")


@pytest.mark.asyncio
async def test_real_registered_process_exit_and_restart(plugin_host):
    source = SOURCE.replace('self.calls += 1', '''self.calls += 1
        import sys
        process = await asyncio.create_subprocess_exec(sys.executable, "-c", "import time; time.sleep(30)")
        self.lifecycle_processes = [process]''')
    host = plugin_host(source=source)
    host.context.set_service("plugin.lifecycle.start_timeout", 3)
    host.context.set_service("plugin.lifecycle.stop_timeout", 3)
    await await_plugin_backends(host.handles)
    assert host.manager.is_enabled("example")
    process = host.handle.value.lifecycle_processes[0]
    process.terminate()
    await process.wait()
    assert not host.manager.is_enabled("example")
    assert "process terminated" in host.handle.error["message"]
    assert await host.manager.start("example")
    replacement = host.handle.value.lifecycle_processes[0]
    assert replacement is not process and replacement.returncode is None
    await host.manager.stop("example")
    assert replacement.returncode is not None


@pytest.mark.asyncio
async def test_shutdown_cancels_startup_and_never_attaches_a_late_service(plugin_host):
    host = plugin_host()
    host.handle.value.gate = asyncio.Event()
    await asyncio.sleep(0)
    await shutdown_plugin_backends(host.handles)
    host.handle.value.gate.set()
    await asyncio.sleep(0)
    assert host.handle.state == "stopped" and not host.manager.is_enabled("example")
    assert host.context.service("example") is None
    assert host.handle.startup_task.done()
    assert host.handle.value.stops == 1


@pytest.mark.asyncio
async def test_factory_only_embedding_keeps_legacy_behavior_and_explicit_start_works(plugin_host):
    host = plugin_host(start=False)
    assert host.handle.state == "ready" and not host.handle.managed
    assert host.handle.value.calls == 0 and not host.handle.started
    assert host.manager.is_enabled("example")
    await start_plugin_backend(host.handle, host.context)
    assert host.handle.started and host.handle.value.calls == 1


@pytest.mark.asyncio
async def test_no_start_hook_and_generic_awaitable_are_supported(plugin_host):
    host = plugin_host(source="def create_runtime(context):\n    return object()")
    await await_plugin_backends(host.handles)
    assert host.manager.is_enabled("example") and host.handle.started
    other = plugin_host(start=False)
    def start(context):
        future = asyncio.get_running_loop().create_future()
        future.set_result(None)
        return future
    other.handle.value.start = start
    await start_plugin_backend(other.handle, other.context)
    assert other.handle.started


@pytest.mark.asyncio
async def test_declarative_plugin_remains_available_without_backend(plugin_host):
    host = plugin_host()
    await await_plugin_backends(host.handles)
    raw = json.loads((host.plugin_dir / "plugin.json").read_text(encoding="utf-8"))
    raw.pop("backend")
    (host.plugin_dir / "backend.py").unlink()
    (host.plugin_dir / "plugin.json").write_text(json.dumps(raw), encoding="utf-8")
    manager = PluginRuntimeManager([], host.context, plugin_resolver=lambda name: host.registry.discover()[0])
    assert manager.is_enabled("example") and await manager.start("example")
    assert manager.status("example")["state"] == "not_required"


@pytest.mark.asyncio
async def test_failed_backend_gates_existing_toolbox_and_recovers_it(plugin_host):
    from lamtools_core.plugins.tools import complete_plugin_tool_specs
    from lamtools_core.plugins.models import PluginToolSpec
    from lamtools_core.tool.default_toolbox import build_core_toolbox
    from lamtools_core.tool import ToolCall, ToolResult
    host = plugin_host()
    await await_plugin_backends(host.handles)
    async def echo(call):
        return ToolResult(call_id=call.id, name=call.name, status="ok", content="working")
    specs = complete_plugin_tool_specs([PluginToolSpec(name="startup_echo", permission="auto_allow", handler="unused:echo")], plugin_name="example", plugin_root=host.plugin_dir)
    toolbox = build_core_toolbox(work_root=host.context.work_root, plugin_tool_specs=specs, plugin_tool_handlers={"startup_echo": echo}, plugin_availability=host.manager.is_enabled)
    assert "startup_echo" in {spec.name for spec in toolbox.tool_specs()}
    critical = asyncio.get_running_loop().create_future()
    host.handle.value.lifecycle_tasks = [critical]
    critical.set_exception(RuntimeError("crashed"))
    assert "startup_echo" not in {spec.name for spec in toolbox.tool_specs()}
    result = await toolbox.execute(ToolCall(id="call", name="startup_echo", arguments={}))
    assert result.status != "ok"
    host.handle.value.lifecycle_tasks = []
    assert await host.manager.start("example")
    assert "startup_echo" in {spec.name for spec in toolbox.tool_specs()}


@pytest.mark.asyncio
async def test_stop_failure_revokes_availability_before_returning_an_error(plugin_host):
    host = plugin_host()
    await await_plugin_backends(host.handles)
    async def stop():
        assert not host.manager.is_enabled("example")
        raise RuntimeError("cleanup failed")
    host.handle.value.stop = stop
    response = await host.catalog.execute("plugin.disable", {"name": "example"})
    assert response.status == "error" and not response.payload["enabled"]
    assert not response.payload["available"] and "cleanup failed" in response.payload["error"]
    assert host.context.service("example") is None
    assert host.handle.state == "failed"
    host.handle.value.stop = lambda: None


@pytest.mark.asyncio
async def test_sync_start_exception_and_initial_health_failure_are_not_ready(plugin_host):
    host = plugin_host()
    def fail(context):
        raise RuntimeError("sync start failed")
    host.handle.value.start = fail
    await await_plugin_backends(host.handles)
    assert host.handle.state == "failed" and "sync start failed" in host.handle.error["message"]
    other = plugin_host()
    other.handle.value.healthy = False
    await await_plugin_backends(other.handles)
    assert not other.manager.is_enabled("example")
    assert other.context.service("example") is None


@pytest.mark.asyncio
async def test_cancelled_health_future_is_failure_not_a_silently_dead_monitor(plugin_host):
    host = plugin_host()
    await await_plugin_backends(host.handles)
    def health():
        future = asyncio.get_running_loop().create_future()
        future.cancel()
        return future
    host.handle.value.health_check = health
    async def failed():
        while host.handle.state != "failed":
            await asyncio.sleep(.01)
    await asyncio.wait_for(failed(), 2)
    assert "callback was cancelled" in host.handle.error["message"]


@pytest.mark.asyncio
async def test_bad_factory_and_a_failing_backend_do_not_prevent_other_startups(plugin_host):
    broken = plugin_host(source="async def create_plugin(context):\n    return object()")
    failing = plugin_host()
    failing.handle.value.fail = True
    healthy = plugin_host()
    await await_plugin_backends(broken.handles + failing.handles + healthy.handles)
    assert broken.handle.state == "failed" and "factory must be synchronous" in broken.handle.error["message"]
    assert failing.handle.state == "failed"
    assert healthy.manager.is_enabled("example")


@pytest.mark.asyncio
async def test_stop_timeout_is_bounded_and_retry_waits_for_termination(plugin_host):
    host = plugin_host()
    await await_plugin_backends(host.handles)
    gate = asyncio.Event()
    async def stop():
        await gate.wait()
    host.handle.value.stop = stop
    response = await asyncio.wait_for(host.catalog.execute("plugin.disable", {"name": "example"}), .5)
    assert response.status == "error" and response.payload["code"] == "PLUGIN_BACKEND_TIMEOUT"
    assert not host.manager.is_enabled("example") and host.handle.state == "failed"
    host.handle.value.stop = lambda: None
    await asyncio.sleep(0)
    assert (await host.catalog.execute("plugin.enable", {"name": "example"})).payload["available"]


@pytest.mark.asyncio
async def test_cli_lists_backend_failure_separately_from_enabled_preference(plugin_host, monkeypatch, capsys):
    from lamtools_core import cli
    host = plugin_host()
    host.handle.value.fail = True
    await await_plugin_backends(host.handles)
    result = (await host.catalog.execute("plugin.list")).payload
    async def invoke(*args, **kwargs):
        return result
    monkeypatch.setattr(cli, "_invoke_live", invoke)
    assert await cli.cmd_plugin_list(SimpleNamespace(raw=False)) == 0
    output = capsys.readouterr().out
    assert "enabled, backend=failed" in output and "startup exploded" in output


@pytest.mark.asyncio
async def test_startup_gated_operations_defer_module_import_until_recovery(plugin_host, monkeypatch):
    host = plugin_host()
    module_name = "lazy_startup_contract_example"
    monkeypatch.delitem(sys.modules, module_name, raising=False)
    (host.plugin_dir / f"{module_name}.py").write_text(
        'from lamtools_core.app import OperationResult\n'
        'async def operation(request):\n'
        '    return OperationResult(name=request.name, payload={"recovered": True})\n', encoding="utf-8")
    (host.plugin_dir / "operations.json").write_text(json.dumps({"operations": [{
        "name": "example.recovered", "handler": f"{module_name}:operation",
    }]}), encoding="utf-8")
    catalog = build_plugin_operation_catalog(
        plugin_registry=host.registry, plugin_state_store=host.state,
        hook_registry_factory=lambda: SimpleNamespace(load=lambda: []),
        hook_trust_store=HookTrustStore(host.context.work_root / "trust.json"),
        context=host.context, plugin_runtimes=host.handles,
    )
    try:
        assert module_name not in sys.modules
        host.handle.value.fail = True
        await await_plugin_backends(host.handles)
        assert not catalog.has("example.recovered") and module_name not in sys.modules
        host.handle.value.fail = False
        assert (await catalog.execute("plugin.enable", {"name": "example"})).status == "ok"
        assert (await catalog.execute("example.recovered")).payload["recovered"]
        assert module_name in sys.modules
    finally:
        sys.modules.pop(module_name, None)


@pytest.mark.asyncio
async def test_runnable_example_starts_reports_state_and_recovers_after_task_exit(tmp_path):
    root = Path(__file__).resolve().parents[1] / "examples" / "plugins"
    state = PluginStateStore(tmp_path / "state.jsonc")
    registry = PluginRegistry(plugin_roots=[root], state_store=state)
    context = PluginContext(work_root=tmp_path)
    handles = load_enabled_plugin_backends(registry.discover(), context, start=True)
    catalog = build_plugin_operation_catalog(
        plugin_registry=registry, plugin_state_store=state,
        hook_registry_factory=lambda: SimpleNamespace(load=lambda: []),
        hook_trust_store=HookTrustStore(tmp_path / "trust.json"), context=context,
        plugin_runtimes=handles,
    )
    try:
        await await_plugin_backends(handles)
        row = (await catalog.execute("plugin.list")).payload["plugins"][0]
        assert row["name"] == "lifecycle-demo" and row["available"]
        assert "ticks" in (await catalog.execute("lifecycle_demo.status")).payload
        critical = handles[0].value.lifecycle_tasks[0]
        critical.cancel()
        await asyncio.gather(critical, return_exceptions=True)
        assert not catalog.has("lifecycle_demo.status")
        assert (await catalog.execute("plugin.list")).payload["plugins"][0]["backend"]["state"] == "failed"
        assert (await catalog.execute("plugin.enable", {"name": "lifecycle-demo"})).payload["available"]
        assert "ticks" in (await catalog.execute("lifecycle_demo.status")).payload
    finally:
        await shutdown_plugin_backends(handles)
