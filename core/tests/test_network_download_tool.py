"""user:“把 download 给做成一个工具，传参下载链接，可指定为前台和后台，以及路径”+(下载工具声明与前后台行为验收)。"""
import json
from pathlib import Path

from lamtools_core.plugin_system import PluginHost
from lamtools_core.plugin_system.capabilities import read_capabilities
from lamtools_core.plugin_system.context import PluginContext
from lamtools_core.plugin_system.lifecycle import load_plugin_backend
from lamtools_core.tool import ToolCall
from lamtools_core.tool.approval import ApprovalGate

ROOT = Path(__file__).resolve().parents[1] / 'src/lamtools_core/plugins/bundled/network-exploration'


def _runtime(tmp_path):
    host = PluginHost(roots=[ROOT.parent], state_path=tmp_path / 'ledger.json')
    plugin = host.get('network-exploration')
    assert plugin is not None
    context = PluginContext(
        work_root=tmp_path,
        data_dir=tmp_path,
        permission_service=ApprovalGate(work_root=tmp_path, tool_permissions={}),
    )
    handle = load_plugin_backend(plugin, context)
    return read_capabilities(plugin), handle.value, handle


def test_download_tool_is_declared_for_agent_use(tmp_path):
    capabilities, _, handle = _runtime(tmp_path)
    tool = next(item for item in capabilities.tools if item.name == 'network_download')
    assert tool.permission == 'ask_user'
    assert tool.timeout and tool.timeout >= 900
    assert tool.input_schema['required'] == ['url']
    assert {'directory', 'foreground', 'wait_seconds', 'connections'} <= set(tool.input_schema['properties'])
    assert 'network_download' in handle.tool_handlers


async def test_download_tool_queues_in_background_and_reports_foreground_completion(tmp_path):
    _, runtime, _ = _runtime(tmp_path)
    calls = []

    async def fake_call(method, params):
        calls.append((method, params))
        if method == 'transfer.add':
            return {'gid': 'g1', 'filename': 'My File.zip' if 'My%20' in params['url'] else 'file.bin', 'directory': params.get('directory', str(tmp_path)), 'status': 'waiting'}
        if method == 'transfer.list':
            return {'tasks': [{'gid': 'g1', 'status': 'complete', 'totalLength': '8'}]}
        raise AssertionError(method)

    runtime.call = fake_call
    tool = runtime.tool_handlers['network_download']
    queued = await tool(ToolCall(id='1', name='network_download', arguments={'url': 'https://example.com/My%20File.zip'}))
    assert queued.status == 'ok'
    assert json.loads(queued.content)['status'] == 'waiting'
    assert 'filename' not in calls[0][1]
    assert 'connections' not in calls[0][1]

    completed = await tool(ToolCall(id='2', name='network_download', arguments={
        'url': 'https://example.com/file.bin',
        'directory': str(tmp_path),
        'foreground': True,
        'wait_seconds': 1,
        'connections': 4,
    }))
    assert completed.status == 'ok'
    payload = json.loads(completed.content)
    assert payload['status'] == 'complete'
    assert payload['path'] == str(tmp_path / 'file.bin')
    add_calls = [params for method, params in calls if method == 'transfer.add']
    assert add_calls[-1]['connections'] == 4


async def test_download_tool_rejects_a_relative_directory(tmp_path):
    _, runtime, _ = _runtime(tmp_path)
    async def reject_relative(method, params):
        raise ValueError('下载目录必须是绝对路径')
    runtime.call = reject_relative
    result = await runtime.tool_handlers['network_download'](ToolCall(
        id='1',
        name='network_download',
        arguments={'url': 'https://example.com/file.bin', 'directory': 'relative/path'},
    ))
    assert result.status == 'failed'
    assert '绝对路径' in result.error


async def test_unified_download_tool_passes_options_to_shared_service_and_returns_paused(tmp_path):
    # user:“修”+(工具只透传下载参数；暂停状态不得伪装成仍在下载)。
    _, runtime, _ = _runtime(tmp_path)
    calls = []
    async def fake_call(method, params):
        calls.append((method, params))
        if method == 'transfer.add':
            return {'gid': 'g1', 'filename': 'My File%ZZ.zip', 'directory': str(tmp_path), 'status': 'waiting'}
        return {'tasks': [{'gid': 'g1', 'status': 'paused'}]}
    runtime.call = fake_call
    result = await runtime.network_download(ToolCall(id='unified', name='network_download', arguments={
        'url': 'https://example.com/My%20File%ZZ.zip', 'foreground': True,
        'route': 'auto', 'sha256': 'a' * 64, 'bytes_per_second': 1024,
    }))
    assert result.status == 'ok'
    payload = calls[0][1]
    assert 'filename' not in payload
    assert 'connections' not in payload
    assert payload['route'] == 'auto'
    assert payload['sha256'] == 'a' * 64
    assert payload['bytes_per_second'] == 1024
    content = json.loads(result.content)
    assert content['filename'] == 'My File%ZZ.zip'
    assert content['status'] == 'paused'
    assert content['still_running'] is False


def test_unified_download_active_aria_accepts_route_updates(tmp_path):
    # user:“修”+(用随插件提供的真实内核验证运行中切换下载线路，仅访问本机模拟站点)。
    import http.server
    import socket
    import subprocess
    import threading
    import time
    import urllib.request
    received = threading.Event()
    release = threading.Event()
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            received.set()
            release.wait(10)
            self.send_response(200)
            self.send_header('Content-Length', '2')
            self.end_headers()
            self.wfile.write(b'ok')
        def log_message(self, *args):
            pass
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    with socket.socket() as reserve:
        reserve.bind(('127.0.0.1', 0))
        rpc_port = reserve.getsockname()[1]
    process = subprocess.Popen([
        str(ROOT / 'resources/engines/aria2c.exe'), '--enable-rpc=true',
        '--rpc-listen-all=false', f'--rpc-listen-port={rpc_port}', '--rpc-secret=unified-test',
        '--enable-dht=false', '--enable-peer-exchange=false', '--bt-enable-lpd=false',
        '--console-log-level=error', '--summary-interval=0', f'--dir={tmp_path}',
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def rpc(method, params=None):
        request = urllib.request.Request(f'http://127.0.0.1:{rpc_port}/jsonrpc',
            data=json.dumps({'jsonrpc':'2.0','id':'test','method':'aria2.'+method,'params':['token:unified-test', *(params or [])]}).encode(),
            headers={'Content-Type':'application/json'})
        with opener.open(request, timeout=2) as response:
            value = json.load(response)
        assert 'error' not in value, value
        return value['result']
    try:
        deadline = time.monotonic() + 10
        while True:
            try:
                rpc('getVersion')
                break
            except OSError:
                if process.poll() is not None or time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)
        gid = rpc('addUri', [[f'http://127.0.0.1:{server.server_port}/file.bin'], {'out':'route-test.bin', 'all-proxy':''}])
        assert received.wait(5)
        assert rpc('tellStatus', [gid, ['status']])['status'] == 'active'
        assert rpc('changeOption', [gid, {'all-proxy':'http://127.0.0.1:9'}]) == 'OK'
        assert rpc('changeOption', [gid, {'all-proxy':''}]) == 'OK'
        release.set()
        deadline = time.monotonic() + 5
        while rpc('tellStatus', [gid, ['status']])['status'] != 'complete':
            assert time.monotonic() < deadline
            time.sleep(0.05)
        assert (tmp_path / 'route-test.bin').read_bytes() == b'ok'
    finally:
        release.set()
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=5)
        server.shutdown()
        server.server_close()
