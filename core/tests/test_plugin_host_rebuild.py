"""user:“该重建就重建”+(从真实宿主入口验证状态、更新事务与恢复，先锁定验收契约)。"""
import asyncio
import json
from pathlib import Path

import pytest

from lamtools_core.app import OperationCatalog
from lamtools_core.plugin_system import PluginContext, PluginHost
from lamtools_core.plugin_system.backend_runtime import register_manager
from lamtools_core.plugin_system.lifecycle import load_enabled_plugin_backends, await_plugin_backends
from lamtools_core.plugin_system.operations import register_plugin_system_operations


def plugin(folder, version="1", *, backend=True, **extra):
    folder.mkdir(parents=True, exist_ok=True)
    raw = {"name": "demo", "version": version, "operations": [{"name": "demo.read", "handler": "ops:read"}], **extra}
    if backend:
        raw["backend"] = "./backend.py"
        (folder / "backend.py").write_text("def create_plugin(context):\n    return {'generation': " + repr(version) + "}\n", encoding="utf-8")
    (folder / "plugin.json").write_text(json.dumps(raw), encoding="utf-8")
    (folder / "ops.py").write_text("def read(request, *, context=None):\n    return {'generation': " + repr(version) + "}\n", encoding="utf-8")
    return folder


async def boot(tmp_path, *, backend=True):
    folder = plugin(tmp_path / "plugins" / "demo", backend=backend)
    host = PluginHost(roots=[folder.parent], state_path=tmp_path / "state.json")
    context = PluginContext(work_root=tmp_path, data_dir=tmp_path)
    handles = load_enabled_plugin_backends(host.discover(), context, start=True)
    manager = register_manager(host, handles, context)
    await await_plugin_backends(manager.handles)
    catalog = OperationCatalog()
    context.operation_catalog = catalog
    register_plugin_system_operations(catalog, host)
    return host, manager, catalog, folder


def test_update_failure_preserves_data(tmp_path, monkeypatch):
    folder = plugin(tmp_path / "plugins" / "demo")
    (folder / "data").mkdir()
    (folder / "data" / "record").write_text("keep me")
    incoming = plugin(tmp_path / "incoming", "2")
    host = PluginHost(roots=[folder.parent], state_path=tmp_path / "state.json")
    import lamtools_core.plugin_system.host as module
    def locked(*args):
        raise PermissionError("directory is occupied")
    monkeypatch.setattr(module.os, "replace", locked)
    with pytest.raises(PermissionError):
        host.update_from_directory(incoming)
    assert (folder / "data" / "record").read_text() == "keep me"
    assert host.get("demo").version == "1"


@pytest.mark.asyncio
async def test_failed_load_is_reloaded_and_never_published_empty(tmp_path):
    host, manager, catalog, folder = await boot(tmp_path)
    await manager.stop("demo")
    # Force a fresh load failure, then repair the same path without restarting Core.
    manager.forget("demo")
    (folder / "backend.py").write_text("raise RuntimeError('load failed')\n")
    result = await catalog.execute("plugin.system.enable", {"name": "demo"})
    assert result.status == "error"
    assert not manager.is_enabled("demo")
    assert not catalog.has("demo.read")
    diagnostic = manager.status("demo")["last_error"]
    (folder / "backend.py").write_text("def create_plugin(context): return {'repaired': True}\n")
    result = await catalog.execute("plugin.system.enable", {"name": "demo"})
    assert result.status == "ok"
    assert manager.get("demo").value == {"repaired": True}
    assert manager.status("demo")["last_error"] == diagnostic
    await manager.stop("demo")


@pytest.mark.asyncio
async def test_update_rebinds_handlers_and_keeps_live_handle_list(tmp_path):
    host, manager, catalog, folder = await boot(tmp_path)
    live = manager.handles
    assert (await catalog.execute("demo.read")).payload["generation"] == "1"
    incoming = plugin(tmp_path / "incoming", "2")
    result = await catalog.execute("plugin.system.update", {"path": str(incoming)})
    assert result.status == "ok", result.payload
    assert manager.handles is live
    assert manager.get("demo").value["generation"] == "2"
    assert (await catalog.execute("demo.read")).payload["generation"] == "2"
    await manager.stop("demo")


@pytest.mark.asyncio
async def test_failed_replacement_rolls_back_code_runtime_and_data(tmp_path):
    host, manager, catalog, folder = await boot(tmp_path)
    (folder / "data").mkdir()
    (folder / "data" / "record").write_text("original")
    incoming = plugin(tmp_path / "incoming", "2")
    (incoming / "backend.py").write_text("def create_plugin(context): raise RuntimeError('bad replacement')\n")
    result = await catalog.execute("plugin.system.update", {"path": str(incoming)})
    assert result.status == "error"
    assert host.get("demo").version == "1"
    assert manager.is_enabled("demo")
    assert (await catalog.execute("demo.read")).payload["generation"] == "1"
    assert (folder / "data" / "record").read_text() == "original"
    await manager.stop("demo")


@pytest.mark.asyncio
async def test_inflight_operation_drains_before_update(tmp_path):
    host, manager, catalog, folder = await boot(tmp_path)
    entered, release = asyncio.Event(), asyncio.Event()
    manager.context.services.update(entered=entered, release=release)
    (folder / "ops.py").write_text("async def read(request, *, context):\n    context.service('entered').set()\n    await context.service('release').wait()\n    return {'generation': '1'}\n")
    call = asyncio.create_task(catalog.execute("demo.read"))
    await asyncio.wait_for(entered.wait(), 2)
    incoming = plugin(tmp_path / "incoming", "2")
    update = asyncio.create_task(catalog.execute("plugin.system.update", {"path": str(incoming)}))
    await asyncio.sleep(0)
    assert not update.done()
    release.set()
    assert (await call).payload["generation"] == "1"
    assert (await update).status == "ok"
    assert (await catalog.execute("demo.read")).payload["generation"] == "2"
    await manager.stop("demo")


@pytest.mark.asyncio
async def test_install_publishes_new_operations_without_restart(tmp_path):
    roots = tmp_path / "plugins"
    host = PluginHost(roots=[roots], state_path=tmp_path / "state.json")
    context = PluginContext(work_root=tmp_path)
    manager = register_manager(host, [], context)
    catalog = OperationCatalog()
    register_plugin_system_operations(catalog, host)
    incoming = plugin(tmp_path / "incoming")
    result = await catalog.execute("plugin.system.install", {"path": str(incoming)})
    assert result.status == "ok", result.payload
    assert (await catalog.execute("demo.read")).payload["generation"] == "1"
    await manager.stop("demo")


@pytest.mark.asyncio
async def test_status_and_failure_gate_are_shared(tmp_path):
    host, manager, catalog, folder = await boot(tmp_path)
    manager.get("demo").state = "failed"
    listing = await catalog.execute("plugin.system.list")
    item = listing.payload["plugins"][0]
    assert item["enabled"] and not item["available"]
    assert item["backend"]["state"] == "failed"
    assert not catalog.has("demo.read")
    await manager.stop("demo")


def test_uninstall_then_reinstall_reuses_retained_data(tmp_path):
    folder = plugin(tmp_path / "plugins" / "demo", backend=False)
    (folder / "data").mkdir()
    (folder / "data" / "record").write_text("keep me")
    host = PluginHost(roots=[folder.parent], state_path=tmp_path / "state.json")
    host.uninstall("demo")
    assert host.get("demo") is None
    incoming = plugin(tmp_path / "incoming", "2", backend=False)
    installed = host.install_from_directory(incoming)
    assert (installed / "data" / "record").read_text() == "keep me"


def test_safe_mode_never_executes_plugin_backend(tmp_path, monkeypatch):
    folder = plugin(tmp_path / "plugins" / "demo")
    (folder / "backend.py").write_text("raise AssertionError('plugin code executed in safe mode')\n")
    host = PluginHost(roots=[folder.parent], state_path=tmp_path / "state.json")
    monkeypatch.setenv("LAMTOOLS_SAFE_MODE", "1")
    context = PluginContext(work_root=tmp_path)
    assert load_enabled_plugin_backends(host.discover(), context) == []
    catalog = OperationCatalog()
    register_plugin_system_operations(catalog, host)
    assert not catalog.has("demo.read")
    assert (host.get("demo")).enabled  # Recovery does not rewrite user intent.


def test_boot_and_runtime_agree_on_default_disabled(tmp_path):
    from lamtools_boot.overrides import load_boot_overrides
    folder = plugin(tmp_path / "plugins" / "demo", defaultEnabled=False,
                    overrides={"lamtools_core.prompt": "./replacement.py"})
    (folder / "replacement.py").write_text("")
    overrides, errors = load_boot_overrides(roots=[folder.parent], state_path=tmp_path / "state.json", environ={})
    assert overrides == {} and errors == []


@pytest.mark.asyncio
async def test_host_contexts_are_isolated_even_for_same_plugin_name(tmp_path):
    one, m1, c1, _ = await boot(tmp_path / "one")
    two, m2, c2, _ = await boot(tmp_path / "two")
    assert m1.context is not m2.context
    m1.context.set_service("identity", "one")
    m2.context.set_service("identity", "two")
    for host, manager, catalog in [(one, m1, c1), (two, m2, c2)]:
        path = host.get("demo").root / "ops.py"
        path.write_text("def read(request, *, context): return {'identity':context.service('identity')}\n")
        assert (await catalog.execute("demo.read")).payload["identity"] == manager.context.service("identity")
        await manager.stop("demo")


@pytest.mark.asyncio
async def test_stop_failure_prevents_code_replacement(tmp_path):
    host, manager, catalog, folder = await boot(tmp_path)
    handle = manager.get("demo")
    async def refuse_stop():
        raise RuntimeError("cleanup did not finish")
    handle.value["stop"] = refuse_stop
    incoming = plugin(tmp_path / "incoming", "2")
    result = await catalog.execute("plugin.system.update", {"path": str(incoming)})
    assert result.status == "error"
    assert host.get("demo").version == "1"
    assert handle in manager.handles
    assert not host.available("demo")
    handle.value.pop("stop")
    await manager.stop("demo")


@pytest.mark.asyncio
async def test_update_removes_old_operations_and_registers_new_ones(tmp_path):
    host, manager, catalog, folder = await boot(tmp_path)
    incoming = plugin(tmp_path / "incoming", "2", operations=[{"name": "demo.new", "handler": "ops:read"}])
    result = await catalog.execute("plugin.system.update", {"path": str(incoming)})
    assert result.status == "ok"
    assert not catalog.has("demo.read")
    assert (await catalog.execute("demo.new")).payload["generation"] == "2"
    await manager.stop("demo")


@pytest.mark.asyncio
async def test_data_identity_survives_update_uninstall_and_reinstall(tmp_path):
    host, manager, catalog, folder = await boot(tmp_path)
    data = folder / "data"
    data.mkdir(exist_ok=True)
    (data / "config.jsonc").write_text('{"kept":true}')
    incoming = plugin(tmp_path / "incoming", "2")
    await catalog.execute("plugin.system.update", {"path": str(incoming)})
    stable = host.data_path("demo")
    assert data.resolve() == stable
    assert stable.is_relative_to(tmp_path)
    assert not stable.is_relative_to(folder)
    await catalog.execute("plugin.system.uninstall", {"name": "demo"})
    assert (stable / "config.jsonc").exists() and not folder.exists()
    await catalog.execute("plugin.system.install", {"path": str(incoming)})
    assert (folder / "data" / "config.jsonc").read_text() == '{"kept":true}'
    await manager.stop("demo")


@pytest.mark.asyncio
async def test_drain_deadline_does_not_replace_running_code(tmp_path):
    host, manager, catalog, folder = await boot(tmp_path)
    manager.context.set_service("plugin.lifecycle.drain_timeout", 0.01)
    incoming = plugin(tmp_path / "incoming", "2")
    async with manager.lease("demo"):
        result = await catalog.execute("plugin.system.update", {"path": str(incoming)})
        assert result.status == "error"
        assert host.get("demo").version == "1"
    assert host.available("demo")
    await manager.stop("demo")


@pytest.mark.asyncio
async def test_ready_gate_applies_to_ui_and_assets_and_safe_mode(tmp_path, monkeypatch):
    from lamtools_core.plugin_system.assets import resolve_plugin_asset
    host, manager, catalog, folder = await boot(tmp_path)
    (folder / "page.mjs").write_text("export function mount(){}")
    raw = json.loads((folder / "plugin.json").read_text())
    raw["ui"] = {"pages": [{"id": "page", "title": "Page", "entry": "./page.mjs"}]}
    (folder / "plugin.json").write_text(json.dumps(raw))
    host._invalidate()
    assert (await catalog.execute("plugin.system.ui")).payload["pages"]
    manager.get("demo").state = "failed"
    assert (await catalog.execute("plugin.system.ui")).payload["pages"] == []
    assert resolve_plugin_asset(host, "demo", "page.mjs") is None
    monkeypatch.setenv("LAMTOOLS_SAFE_MODE", "1")
    assert not catalog.has("demo.read")
    assert (await catalog.execute("plugin.system.ui")).payload["pages"] == []
    await manager.stop("demo")


@pytest.mark.asyncio
async def test_plugin_resources_close_before_code_unloads(tmp_path):
    host, manager, catalog, folder = await boot(tmp_path)
    closed = []
    async def close():
        closed.append("closed")
    manager.own_resource("demo", close)
    result = await catalog.execute("plugin.system.disable", {"name": "demo"})
    assert result.status == "ok"
    assert closed == ["closed"]
    assert not manager.is_enabled("demo")


@pytest.mark.asyncio
async def test_old_toolbox_cannot_execute_updated_plugin_code(tmp_path):
    from lamtools_core.tool import ToolCall
    from lamtools_core.tool.default_toolbox import CoreToolbox
    from lamtools_core.plugin_system.runtime import PluginSystemRuntime
    host, manager, catalog, folder = await boot(tmp_path)
    (folder / "tool.py").write_text("from lamtools_core.tool import ToolResult\ndef read(call): return ToolResult(call_id=call.id,name=call.name,status='ok',content='old')\n")
    raw = json.loads((folder / "plugin.json").read_text())
    (folder / "tools.json").write_text(json.dumps({"tools": [{"name": "demo_tool", "description": "demo", "handler": "tool:read", "permission": "auto_allow",
                     "input_schema": {"type": "object", "properties": {}}}]}))
    raw["tools"] = ["./tools.json"]
    (folder / "plugin.json").write_text(json.dumps(raw))
    host._invalidate()
    toolbox = CoreToolbox(work_root=tmp_path, plugin_tool_specs=PluginSystemRuntime(host).assemble().tools,
                          plugin_availability=manager.is_enabled)
    assert "demo_tool" in toolbox._handlers
    before = await toolbox._handlers["demo_tool"](ToolCall(id="before", name="demo_tool", arguments={}))
    assert before.content == "old"
    incoming = plugin(tmp_path / "incoming", "2")
    assert (await catalog.execute("plugin.system.update", {"path": str(incoming)})).status == "ok"
    result = await toolbox._handlers["demo_tool"](ToolCall(id="old", name="demo_tool", arguments={}))
    assert result.status == "blocked"
    await manager.stop("demo")


@pytest.mark.asyncio
async def test_locked_code_swap_restores_old_backend(tmp_path, monkeypatch):
    host, manager, catalog, folder = await boot(tmp_path)
    incoming = plugin(tmp_path / "incoming", "2")
    import lamtools_core.plugin_system.storage as storage
    original = storage.os.replace
    def occupied(src, dst):
        if Path(src) == folder:
            raise PermissionError("occupied")
        return original(src, dst)
    monkeypatch.setattr(storage.os, "replace", occupied)
    result = await catalog.execute("plugin.system.update", {"path": str(incoming)})
    assert result.status == "error"
    assert host.get("demo").version == "1" and host.available("demo")
    await manager.stop("demo")


def test_interrupted_swap_recovers_old_code_on_next_host_start(tmp_path):
    folder = plugin(tmp_path / "plugins" / "demo")
    incoming = plugin(tmp_path / "incoming", "2")
    host = PluginHost(roots=[folder.parent], state_path=tmp_path / "state.json")
    import subprocess, sys
    code = "from lamtools_core.plugin_system import PluginHost; import os; h=PluginHost(roots=["+repr(str(folder.parent))+"], state_path="+repr(str(tmp_path / "state.json"))+"); h.begin_update("+repr(str(incoming))+"); os._exit(0)"
    subprocess.run([sys.executable, "-c", code], check=True, timeout=10)
    recovered = PluginHost(roots=[folder.parent], state_path=tmp_path / "state.json")
    assert recovered.get("demo").version == "1"
    assert not list(folder.parent.glob(".plugin-txn-*"))



@pytest.mark.asyncio
async def test_cancelled_mutation_waits_for_filesystem_and_rolls_back(tmp_path, monkeypatch):
    import threading
    host, manager, catalog, folder = await boot(tmp_path)
    incoming = plugin(tmp_path / "incoming", "2")
    entered, release = threading.Event(), threading.Event()
    original = host.begin_update
    def slow(source):
        entered.set()
        assert release.wait(3)
        return original(source)
    monkeypatch.setattr(host, "begin_update", slow)
    task = asyncio.create_task(catalog.execute("plugin.system.update", {"path": str(incoming)}))
    assert await asyncio.to_thread(entered.wait, 2)
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert host.get("demo").version == "1" and host.available("demo")
    assert not manager.mutation_lock.locked()
    await manager.stop("demo")


@pytest.mark.asyncio
async def test_main_application_catalog_shares_supervisor_and_aliases(tmp_path, monkeypatch):
    from lamtools_core.app import CoreAgentPaths, CoreAgentSpec, create_core_agent_operations
    monkeypatch.setenv("LAMTOOLS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("LAMTOOLS_CORE_CONFIG_ROOT", str(tmp_path / "config"))
    import lamtools_core.plugin_system.paths as paths
    monkeypatch.setattr(paths, "bundled_plugins_dir", lambda: tmp_path / "empty-bundled")
    folder = plugin(tmp_path / "plugins" / "demo")
    class Model:
        async def complete(self, request):
            raise AssertionError("plugin management must not call a model")
        async def stream(self, request):
            if False:
                yield None
    catalog = create_core_agent_operations(spec=CoreAgentSpec(), paths=CoreAgentPaths(data_dir=tmp_path / "app-data", work_root=tmp_path),
                                          model_provider=Model(), plugin_roots=[folder.parent])
    host = catalog.plugin_system_host
    manager = host.backend_manager
    assert catalog.plugin_runtimes is manager.handles
    assert (await catalog.execute("plugin.disable", {"name": "demo"})).status == "ok"
    assert not catalog.has("demo.read")
    assert (await catalog.execute("plugin.enable", {"name": "demo"})).status == "ok"
    incoming = plugin(tmp_path / "incoming", "2")
    assert (await catalog.execute("plugin.update", {"path": str(incoming)})).status == "ok"
    assert (await catalog.execute("demo.read")).payload["generation"] == "2"
    assert (await catalog.execute("plugin.uninstall", {"name": "demo"})).status == "ok"
    assert not catalog.has("demo.read")


def test_committed_transaction_cleanup_failure_keeps_new_version(tmp_path, monkeypatch):
    # user:“该重建就重建”+(已提交版本不因旧文件清理失败而回滚)。
    import lamtools_core.plugin_system.storage as storage
    folder = plugin(tmp_path / "plugins" / "demo")
    incoming = plugin(tmp_path / "incoming", "2")
    transaction = storage.CodeTransaction(folder, incoming, tmp_path / "data")
    original = storage.remove_tree
    monkeypatch.setattr(storage, "remove_tree", lambda path: (_ for _ in ()).throw(PermissionError("occupied")))
    transaction.commit()
    assert json.loads((folder / "plugin.json").read_text())["version"] == "2"
    assert json.loads((transaction.work / "transaction.json").read_text())["committed"]
    storage.recover_transactions(folder.parent)
    assert transaction.work.exists()
    monkeypatch.setattr(storage, "remove_tree", original)
    storage.recover_transactions(folder.parent)
    assert not transaction.work.exists()


@pytest.mark.asyncio
async def test_unavailable_backend_config_uses_repair_form_and_toggle_warns_restart(tmp_path):
    # user:“该重建就重建”+(坏后端可修配置，涉及界面模块的开关提示重启)。
    host, manager, catalog, folder = await boot(tmp_path)
    (folder / "schema.json").write_text('{"type":"object","properties":{}}')
    (folder / "panel.js").write_text('export function mount() {}')
    raw = json.loads((folder / "plugin.json").read_text())
    raw.update(config={"schema": "./schema.json", "panel": "./panel.js"}, ui={})
    (folder / "plugin.json").write_text(json.dumps(raw))
    host._invalidate()
    manager.get("demo").state = "failed"
    result = await catalog.execute("plugin.system.config.get", {"name": "demo"})
    assert result.status == "ok" and result.payload["has_schema"]
    assert not result.payload["has_panel"] and result.payload["panel_url"] is None
    raw["ui"] = {"pages": [{"id": "probe", "title": "Probe", "entry": "./panel.js"}]}
    (folder / "plugin.json").write_text(json.dumps(raw))
    host._invalidate()
    result = await catalog.execute("plugin.system.disable", {"name": "demo"})
    assert result.status == "ok" and result.payload["restart_required"]


@pytest.mark.asyncio
async def test_reload_reimports_backend_and_operation_handlers(tmp_path):
    host, manager, catalog, folder = await boot(tmp_path)
    assert manager.get("demo").value["generation"] == "1"
    assert (await catalog.execute("demo.read")).payload["generation"] == "1"

    (folder / "backend.py").write_text("def create_plugin(context):\n    return {'generation': '2'}\n", encoding="utf-8")
    (folder / "ops.py").write_text(
        "def read(request, *, context=None):\n    return {'generation': '2'}\n",
        encoding="utf-8",
    )

    result = await catalog.execute("plugin.system.reload", {"name": "demo"})

    assert result.status == "ok", result.payload
    assert result.payload["reloaded"] is True
    assert manager.get("demo").value["generation"] == "2"
    assert (await catalog.execute("demo.read")).payload["generation"] == "2"
    await manager.stop("demo")
