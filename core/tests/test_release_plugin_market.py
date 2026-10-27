"""user:“修完打包发布新版本…插件市场…自动通过网络拓展加速”+(验收发布前的进程与安装事务边界)。"""
import asyncio
import json
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from lamtools_core.plugin_system import PluginContext, PluginHost
from lamtools_core.plugin_system.backend_runtime import register_manager
from lamtools_core.plugin_system.management import install_or_update
from lamtools_core.plugin_system.process_runtime import ProcessBackend, ProcessBackendError


@pytest.mark.asyncio
async def test_stop_failure_preserves_live_process_for_retry(tmp_path):
    backend = ProcessBackend(SimpleNamespace(name="demo", root=tmp_path, raw={}), {}, None)
    class Child:
        returncode = None
        stdin = None
        def terminate(self): raise PermissionError("denied")
        def kill(self): raise PermissionError("denied")
    child = Child()
    backend._process = child
    backend.call = AsyncMock(return_value={})
    with pytest.raises((PermissionError, ProcessBackendError)):
        await backend.stop()
    assert backend.lifecycle_processes == (child,)


@pytest.mark.asyncio
async def test_cancelled_stop_remains_owned_until_exit(tmp_path):
    backend = ProcessBackend(SimpleNamespace(name="demo", root=tmp_path, raw={}), {}, None)
    entered, exit_ready = asyncio.Event(), asyncio.Event()
    class Child:
        returncode = None
        stdin = None
        def terminate(self): entered.set()
        async def wait(self):
            await exit_ready.wait()
            self.returncode = 0
            return 0
    child = Child()
    backend._process = child
    backend.call = AsyncMock(return_value={})
    task = asyncio.create_task(backend.stop())
    try:
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert backend.lifecycle_processes == (child,)
        assert backend.lifecycle_tasks
    finally:
        exit_ready.set()
        await backend.stop()
    assert not backend.lifecycle_processes


@pytest.mark.asyncio
async def test_completed_cleanup_is_not_reported_as_a_failed_runtime_task(tmp_path):
    # user:“修完打包发布新版本”+(停止后再次启用进程插件，不得把已完成的清理任务误判为运行任务死亡)。
    from tests.test_architecture_review_fixes import WORKER
    script = tmp_path / "worker.py"
    script.write_text(WORKER)
    backend = ProcessBackend(SimpleNamespace(name="demo", root=tmp_path, raw={}), {"command": [sys.executable, str(script)]}, None)
    try:
        await backend.start()
        await backend.stop()
        await backend.start()
        assert backend.health_check()["ready"]
        assert not any(task.done() for task in backend.lifecycle_tasks)
    finally:
        await backend.stop()


@pytest.mark.asyncio
async def test_long_stderr_cannot_block_rpc(tmp_path):
    script = tmp_path / "worker.py"
    script.write_text("import sys,json\nfor line in sys.stdin:\n r=json.loads(line)\n if r['method']=='noisy':\n  for i in range(100):\n   sys.stderr.write('x'*70000+'\\n');sys.stderr.flush()\n print(json.dumps({'id':r['id'],'result':{'ok':True}}),flush=True)\n if r['method']=='shutdown':break\n")
    backend = ProcessBackend(SimpleNamespace(name="demo", root=tmp_path, raw={}), {"command": [sys.executable, str(script)]}, None)
    try:
        await backend.start()
        assert (await backend.call("noisy", {}, timeout=3))["ok"]
        assert not backend._stderr_task.done()
    finally:
        # Drain independently on failure too, so a regression cannot leave a
        # blocked test child behind.
        process = backend._process
        cleanup = None
        if process and backend._stderr_task and backend._stderr_task.done():
            async def drain():
                while await process.stderr.read(65536): pass
            cleanup = asyncio.create_task(drain())
        await backend.stop()
        if cleanup: await cleanup


@pytest.mark.asyncio
async def test_failed_first_install_keeps_durable_transaction_until_cleanup(tmp_path):
    root, source = tmp_path / "plugins", tmp_path / "source"
    root.mkdir(); source.mkdir()
    (source / "plugin.json").write_text(json.dumps({"name": "demo", "version": "1", "backend": "./backend.py"}))
    (source / "backend.py").write_text("async def start(context): raise RuntimeError('start failed')\nasync def stop(): raise RuntimeError('stop failed')\n")
    host = PluginHost(roots=[root], state_path=tmp_path / "state.json")
    manager = register_manager(host, [], PluginContext(work_root=tmp_path, data_dir=tmp_path))
    with pytest.raises(Exception, match="recovery required"):
        await install_or_update(host, {"path": str(source)})
    assert manager.status("demo")["recovery_required"]
    journals = list(root.glob(".plugin-txn-*/transaction.json"))
    assert len(journals) == 1
    record = json.loads(journals[0].read_text())
    assert not record["committed"]
    # Simulate the owning process having exited; this backend owns no tasks or
    # processes, so the fresh host can exercise real crash recovery safely.
    record["pid"] = 0
    journals[0].write_text(json.dumps(record))
    fresh = PluginHost(roots=[root], state_path=tmp_path / "state.json")
    assert fresh.get("demo") is None
