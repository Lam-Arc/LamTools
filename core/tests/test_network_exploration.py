"""user:“实现这个插件，也正好实验我们的新插件架构”+(通过真实宿主装配和后台协议验收)。"""
import asyncio
import json
import hashlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import httpx

from lamtools_core.app import OperationCatalog
from lamtools_core.plugin_system import PluginHost
from lamtools_core.plugin_system.context import PluginContext
from lamtools_core.plugin_system.lifecycle import load_plugin_backend, start_plugin_backend, stop_plugin_backend
from lamtools_core.plugin_system.backend_runtime import remember_context, forget_context
from lamtools_core.plugin_system.operations import register_plugin_system_operations
from lamtools_core.plugin_system.ui import read_ui
from lamtools_core.tool.approval import ApprovalGate

ROOT = Path(__file__).resolve().parents[1] / 'src/lamtools_core/plugins/bundled/network-exploration'


def test_manifest_has_a_navigable_page_right_region_and_no_duplicate_agent_tools(tmp_path):
    host = PluginHost(roots=[ROOT.parent], state_path=tmp_path / 'ledger.json')
    plugin = host.get('network-exploration')
    assert plugin is not None
    ui = read_ui(plugin)
    assert any(page.id == 'network' and page.navigation for page in ui.pages)
    # user:“左侧入口就保留3个就行”+(左侧插件入口由可导航页面提供，不再声明空的 appRail 区域)。
    assert 'right' in {item.region for item in ui.regions}
    assert plugin.raw.get('tools', []) == []


def test_system_proxy_operations_are_auto_allowed_on_desktop(tmp_path):
    # user:“network-exploration.system.apply 修改或恢复所选网络配置；我不希望这个东西再出现了，桌面可把它自动允许掉”+(系统代理的应用与恢复不再逐次弹审批，其他系统操作仍按原权限)。
    from lamtools_core.plugin_system.operation_bridge import read_operations

    host = PluginHost(roots=[ROOT.parent], state_path=tmp_path / 'ledger.json')
    plugin = host.get('network-exploration')
    assert plugin is not None
    permissions = {spec.name: spec.permission for spec in read_operations(plugin)}
    assert permissions['network-exploration.system.apply'] == 'auto_allow'
    assert permissions['network-exploration.system.restore'] == 'auto_allow'


async def test_host_controls_one_rust_service_and_persistent_state(tmp_path):
    host = PluginHost(roots=[ROOT.parent], state_path=tmp_path / 'ledger.json')
    plugin = host.get('network-exploration')
    assert plugin is not None
    context = PluginContext(work_root=tmp_path, data_dir=tmp_path, permission_service=ApprovalGate(work_root=tmp_path, tool_permissions={}))
    handle = load_plugin_backend(plugin, context)
    await start_plugin_backend(handle, context)
    remember_context(plugin.name, handle.context)
    catalog = OperationCatalog()
    register_plugin_system_operations(catalog, host)
    try:
        states = await asyncio.gather(*(catalog.execute('network-exploration.status', {}) for _ in range(3)))
        assert all(result.status == 'ok' for result in states)
        assert len({result.payload['controller_pid'] for result in states}) == 1
        assert states[0].payload['proxy']['running'] is False
        config = await catalog.execute('network-exploration.settings.update', {'revision': 0, 'settings': {'sample_seconds': 5}})
        assert config.status == 'ok'
        stale = await catalog.execute('network-exploration.settings.update', {'revision': 0, 'settings': {'sample_seconds': 30}})
        assert stale.status == 'error'
        invalid = await catalog.execute('network-exploration.diagnose', {'target': 'example.com; whoami'})
        assert invalid.status == 'error'
        process = handle.value.process
    finally:
        await stop_plugin_backend(handle)
        forget_context(plugin.name)
    assert process.returncode is not None
    assert json.loads((handle.value.data_dir / 'state.json').read_text())['revision'] == 1


async def test_real_aria2_download_pause_restart_resume_and_hash(tmp_path):
    """Use a local Range server and the integrated engine; never change global networking."""
    content = bytes(range(256)) * 16384
    expected = hashlib.sha256(content).hexdigest()
    ranges = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            header = self.headers.get('Range', '')
            start, end = 0, len(content) - 1
            if header.startswith('bytes='):
                first, _, last = header[6:].partition('-')
                start = int(first or 0)
                if last:
                    end = min(end, int(last))
            ranges.append(start)
            self.send_response(206 if header else 200)
            self.send_header('Content-Length', str(end - start + 1))
            self.send_header('Accept-Ranges', 'bytes')
            if header:
                self.send_header('Content-Range', f'bytes {start}-{end}/{len(content)}')
            self.end_headers()
            try:
                self.wfile.write(content[start:end + 1])
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    host = PluginHost(roots=[ROOT.parent], state_path=tmp_path / 'ledger.json')
    context = PluginContext(work_root=tmp_path, data_dir=tmp_path)
    handle = load_plugin_backend(host.get('network-exploration'), context)
    await start_plugin_backend(handle, context)
    remember_context('network-exploration', handle.context)
    catalog = OperationCatalog()
    register_plugin_system_operations(catalog, host)

    async def invoke(method, params=None):
        result = await catalog.execute('network-exploration.' + method, params or {})
        assert result.status == 'ok', result.payload
        return result.payload

    async def wait_for_task(gid, predicate, attempts=100):
        for _ in range(attempts):
            result = await invoke('transfer.list')
            task = next((task for task in result['tasks'] if task['gid'] == gid), {})
            if predicate(task):
                return task
            await asyncio.sleep(0.1)
        pytest.fail('Download did not reach the expected state')

    try:
        result = await invoke('transfer.add', {'url': f'http://127.0.0.1:{server.server_port}/file.bin', 'filename': 'sample.bin', 'connections': 2, 'bytes_per_second': 524288, 'sha256': expected})
        gid = result['gid']
        await wait_for_task(gid, lambda task: int(task.get('completedLength', 0)) >= 1024 * 1024)
        await invoke('transfer.action', {'gid': gid, 'action': 'pause'})
        paused = await wait_for_task(gid, lambda task: task.get('status') == 'paused')
        assert 0 < int(paused['completedLength']) < len(content)
        await stop_plugin_backend(handle)
        await start_plugin_backend(handle, context)
        remember_context('network-exploration', handle.context)
        recovered = await wait_for_task(gid, lambda task: task.get('status') == 'paused')
        assert recovered['status'] == 'paused'
        ranges.clear()
        await invoke('transfer.action', {'gid': gid, 'action': 'resume'})
        await wait_for_task(gid, lambda task: task.get('status') == 'complete', attempts=150)
        verified = await invoke('transfer.verify', {'gid': gid})
        assert verified['verified'] is True
        assert verified['sha256'] == expected
        assert any(offset > 0 for offset in ranges), 'Resume must request remaining bytes rather than downloading everything again'
        state = await invoke('status')
        assert 'protected_request' not in json.dumps(state)
        assert (handle.value.data_dir / 'downloads/sample.bin').read_bytes() == content
    finally:
        await stop_plugin_backend(handle)
        forget_context('network-exploration')
        server.shutdown()
        server.server_close()
        worker.join()


async def test_integrated_mihomo_forwards_without_system_proxy_or_tun(tmp_path):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            body = b'Sunday local proxy verification'
            self.send_response(200)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    host = PluginHost(roots=[ROOT.parent], state_path=tmp_path / 'ledger.json')
    context = PluginContext(work_root=tmp_path, data_dir=tmp_path)
    handle = load_plugin_backend(host.get('network-exploration'), context)
    await start_plugin_backend(handle, context)
    remember_context('network-exploration', handle.context)
    catalog = OperationCatalog()
    register_plugin_system_operations(catalog, host)
    async def invoke(method, params=None):
        result = await catalog.execute('network-exploration.' + method, params or {})
        assert result.status == 'ok', result.payload
        return result.payload
    try:
        await invoke('proxy.config', {'content': 'mode: direct\nrules:\n  - MATCH,DIRECT\n'})
        result = await invoke('proxy.start')
        assert result['tun'] is False
        assert result['system_proxy'] is False
        async with httpx.AsyncClient(proxy='http://127.0.0.1:17890', trust_env=False) as client:
            response = await client.get(f'http://127.0.0.1:{server.server_port}/test')
        assert response.text == 'Sunday local proxy verification'
        inspected = await invoke('proxy.inspect')
        assert inspected['mode'] == 'direct'
        assert 'DIRECT' in inspected['proxies']
        state = await invoke('status')
        assert state['transactions'] == []
        await invoke('proxy.stop')
        assert (await invoke('status'))['proxy']['running'] is False
        assert not (handle.value.data_dir / 'runtime/mihomo.yaml').exists()
    finally:
        await stop_plugin_backend(handle)
        forget_context('network-exploration')
        server.shutdown()
        server.server_close()
        worker.join()
