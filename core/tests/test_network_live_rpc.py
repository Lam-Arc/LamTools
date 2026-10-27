"""user:“实现这个插件，也正好实验我们的新插件架构”+(通过启动后的真实宿主 WebSocket 和资源接口验收，不直接调用插件函数)。"""
from pathlib import Path

from fastapi.testclient import TestClient

from lamtools_core.app.http_agent_app import create_core_agent_http_app
from lamtools_core.plugin_system.state import PluginStateStore

ROOT = Path(__file__).resolve().parents[1] / 'src/lamtools_core/plugins/bundled'


def test_running_host_exposes_network_page_and_one_controller(tmp_path):
    data = tmp_path / 'core-data'
    ledger = PluginStateStore(data / 'plugin-system.jsonc')
    for manifest in ROOT.glob('*/plugin.json'):
        ledger.set_enabled(manifest.parent.name, manifest.parent.name == 'network-exploration')
    app = create_core_agent_http_app(core_db=tmp_path / 'core.db', data_dir=data, work_root=tmp_path / 'workspace', plugin_roots=(ROOT,))
    with TestClient(app) as client:
        with client.websocket_connect('/api/core/app-server') as websocket:
            sequence = 0
            def rpc(method, params=None):
                nonlocal sequence
                sequence += 1
                websocket.send_json({'id': sequence, 'method': method, 'params': params or {}})
                for _ in range(100):
                    reply = websocket.receive_json()
                    if reply.get('id') == sequence:
                        assert 'error' not in reply, reply
                        return reply['result']
                raise AssertionError('RPC response missing')
            rpc('initialize', {'clientInfo': {'name': 'network-plugin-verification'}})
            catalog = rpc('plugin.system.ui')
            page = next(page for page in catalog['pages'] if page['plugin'] == 'network-exploration')
            assert page['navigation'] is True
            assert client.get(page['entry_url']).status_code == 200
            config = rpc('plugin.system.config.get', {'name': 'network-exploration'})
            assert config['has_panel'] is True
            assert client.get(config['panel_url']).status_code == 200
            first = rpc('network-exploration.status')
            second = rpc('network-exploration.status')
            assert first['controller_pid'] == second['controller_pid']
            assert first['traffic_source'] == 'system_interfaces'
            assert first['proxy']['running'] is False
            connections = rpc('network-exploration.connections', {'filter': 'TCP'})
            assert connections['traffic_source'] == 'system_connections'
            assert connections['per_process_bytes_available'] is False
            interfaces = rpc('network-exploration.interfaces')['interfaces']
            assert interfaces
            snapshot = rpc('network-exploration.system.inspect', {'kind': 'dns', 'interface_index': interfaces[0]['index'], 'servers': ['1.1.1.1']})
            assert snapshot['adapter_guid']
            assert all(isinstance(row['manual'], bool) for row in snapshot['rows'])
