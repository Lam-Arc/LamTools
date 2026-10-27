"""user:“该修修 如果是架构问题就重构”+(验收生命周期互斥、失败恢复、进程通信和精确信任)。"""
import asyncio
import json
import sys
from pathlib import Path

import pytest

from lamtools_core.app import OperationCatalog
from lamtools_core.plugin_system import PluginContext, PluginHost
from lamtools_core.plugin_system.backend_runtime import register_manager
from lamtools_core.plugin_system.management import install_or_update, set_enabled
from lamtools_core.plugin_system.operations import register_plugin_system_operations
from lamtools_core.plugin_system.process_runtime import ProcessBackend, ProcessBackendError
from lamtools_core.tool.approval import ApprovalGate
from lamtools_core.tool.operation_trust import OperationTrustStore


def source(folder, version="1", backend=None):
    folder.mkdir(parents=True)
    raw = {"name": "demo", "version": version}
    if backend is not None:
        raw["backend"] = "./backend.py"
        (folder / "backend.py").write_text(backend, encoding="utf-8")
    (folder / "plugin.json").write_text(json.dumps(raw), encoding="utf-8")
    return folder


async def boot(tmp_path, backend=None):
    folder = source(tmp_path / "plugins" / "demo", backend=backend)
    host = PluginHost(roots=[folder.parent], state_path=tmp_path / "state.json")
    manager = register_manager(host, [], PluginContext(work_root=tmp_path, data_dir=tmp_path))
    await manager.start("demo")
    catalog = OperationCatalog()
    register_plugin_system_operations(catalog, host)
    return host, manager, catalog


@pytest.mark.asyncio
async def test_reload_closes_admission_and_serializes_mutations(tmp_path, monkeypatch):
    host, manager, catalog = await boot(tmp_path)
    draining = asyncio.Event()
    original = manager.drain

    async def drain(name):
        draining.set()
        await original(name)

    monkeypatch.setattr(manager, "drain", drain)
    task = None
    try:
        async with manager.lease("demo"):
            task = asyncio.create_task(catalog.execute("plugin.system.reload", {"name": "demo"}))
            await asyncio.wait_for(draining.wait(), 2)
            assert manager.mutation_lock.locked()
            with pytest.raises(RuntimeError, match="not ready"):
                async with manager.lease("demo"):
                    pytest.fail("reload admitted a new call")
            disable = asyncio.create_task(set_enabled(host, "demo", False))
            await asyncio.sleep(0)
            assert not disable.done()
        assert (await task).status == "ok"
        await disable
        assert not host.available("demo")
        assert not manager.transitioning
    finally:
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_failed_update_retains_recovery_and_restores_old_version_on_retry(tmp_path):
    host, manager, _ = await boot(tmp_path, "async def start(context): pass\nasync def stop(): pass\n")
    data = host.get("demo").root / "data"
    data.mkdir()
    (data / "record.txt").write_text("original data")
    marker = tmp_path / "allow-cleanup"
    incoming = source(tmp_path / "incoming", "2", (
        "from pathlib import Path\n"
        "async def start(context): raise RuntimeError('startup failed')\n"
        f"async def stop():\n    if not Path({str(marker)!r}).exists(): raise RuntimeError('cleanup failed')\n"
    ))
    try:
        with pytest.raises(Exception, match="recovery|恢复"):
            await install_or_update(host, {"path": str(incoming)}, update=True)
        assert manager.status("demo")["state"] == "failed"
        assert manager.status("demo")["recovery_required"]
        assert manager.status("demo")["error"]["code"] == "PLUGIN_RECOVERY_REQUIRED"
        assert not host.available("demo")
        with pytest.raises(Exception):
            await set_enabled(host, "demo", True)
        assert manager.status("demo")["recovery_required"]
        assert list((tmp_path / "plugins").glob(".plugin-txn-*"))
        marker.touch()
        await set_enabled(host, "demo", True)
        assert host.get("demo").version == "1"
        assert host.available("demo")
        assert not manager.status("demo")["recovery_required"]
        assert (data / "record.txt").read_text() == "original data"
        assert not list((tmp_path / "plugins").glob(".plugin-txn-*"))
    finally:
        marker.touch()
        await manager.stop("demo")


@pytest.mark.asyncio
async def test_failed_update_with_clean_stop_rolls_back_immediately(tmp_path):
    host, manager, _ = await boot(tmp_path, "async def start(context): pass\nasync def stop(): pass\n")
    incoming = source(tmp_path / "incoming", "2", "async def start(context): raise RuntimeError('startup failed')\nasync def stop(): pass\n")
    try:
        with pytest.raises(Exception, match="startup failed"):
            await install_or_update(host, {"path": str(incoming)}, update=True)
        assert host.get("demo").version == "1"
        assert host.available("demo")
    finally:
        await manager.stop("demo")


WORKER = '''import sys, json
for line in sys.stdin:
    row = json.loads(line)
    method = row['method']
    if method == 'large':
        result = {'text': 'x' * 70000}
    elif method == 'oversized':
        result = {'text': 'x' * (9 * 1024 * 1024)}
    else:
        result = {'ok': True}
    print(json.dumps({'jsonrpc': '2.0', 'id': row['id'], 'result': result}), flush=True)
    if method == 'shutdown': break
'''


@pytest.mark.asyncio
async def test_process_accepts_large_response_and_remains_usable(tmp_path):
    host, _, _ = await boot(tmp_path)
    script = tmp_path / "worker.py"
    script.write_text(WORKER)
    backend = ProcessBackend(host.get("demo"), {"command": [sys.executable, str(script)]}, None)
    try:
        await backend.start()
        result = await backend.call("large", {}, timeout=3)
        assert len(result["text"]) == 70000
        assert (await backend.call("health", {}, timeout=3))["ok"]
        assert backend.health_check()["ready"]
    finally:
        await backend.stop()


@pytest.mark.asyncio
async def test_process_reports_oversized_message_without_claiming_process_exit(tmp_path):
    host, _, _ = await boot(tmp_path)
    script = tmp_path / "worker.py"
    script.write_text(WORKER)
    backend = ProcessBackend(host.get("demo"), {"command": [sys.executable, str(script)]}, None)
    try:
        await backend.start()
        with pytest.raises(ProcessBackendError, match="exceeds|too large"):
            await backend.call("oversized", {}, timeout=5)
        assert not backend.health_check()["ready"]
        with pytest.raises(ProcessBackendError, match="exceeds|too large"):
            await backend.call("health", {}, timeout=1)
    finally:
        await backend.stop()


def test_mcp_trust_persists_only_for_selected_target(tmp_path):
    store = OperationTrustStore(tmp_path / "trust.json")
    def gate():
        return ApprovalGate(work_root=tmp_path, tool_permissions={}, trust_store=store,
                            mcp_call_level=lambda name, args: 3, permission_preset="auto")
    args = {"action": "run", "tool_name": "mcp__demo__write", "arguments": {"path": "x"}}
    assert gate().trust_operation("mcp", args) == 2
    assert gate().check("mcp", args).allowed
    assert gate().check("mcp", {**args, "tool_name": "mcp__other__write"}).requires_approval
    restricted = gate()
    restricted.available_level = 1
    assert restricted.check("mcp", args).blocked
    row = store.list()[0]
    store.revoke(row["key"])
    assert gate().check("mcp", args).requires_approval


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["reload", "enable", "disable", "uninstall", "update"])
async def test_cancelled_mutation_releases_admission_and_lock(tmp_path, monkeypatch, method):
    host, manager, catalog = await boot(tmp_path)
    draining = asyncio.Event()
    original = manager.drain

    async def drain(name):
        draining.set()
        await original(name)

    monkeypatch.setattr(manager, "drain", drain)
    payload = {"name": "demo"}
    if method == "update":
        payload = {"path": str(source(tmp_path / "incoming", "2"))}
    async with manager.lease("demo"):
        task = asyncio.create_task(catalog.execute(f"plugin.system.{method}", payload))
        try:
            await asyncio.wait_for(draining.wait(), 2)
            assert manager.mutation_lock.locked()
            assert not host.available("demo")
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    assert not manager.transitioning
    assert not manager.mutation_lock.locked()
    assert host.available("demo")
    assert host.get("demo").version == "1"
