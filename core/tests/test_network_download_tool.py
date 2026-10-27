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
            return {'gid': 'g1', 'filename': params['filename'], 'directory': params.get('directory', str(tmp_path))}
        if method == 'transfer.list':
            return {'tasks': [{'gid': 'g1', 'status': 'complete', 'totalLength': '8'}]}
        raise AssertionError(method)

    runtime.call = fake_call
    tool = runtime.tool_handlers['network_download']
    queued = await tool(ToolCall(id='1', name='network_download', arguments={'url': 'https://example.com/My%20File.zip'}))
    assert queued.status == 'ok'
    assert json.loads(queued.content)['status'] == 'queued'
    assert calls[0][1]['filename'] == 'My File.zip'
    assert calls[0][1]['connections'] == 8

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
    runtime.call = None
    result = await runtime.tool_handlers['network_download'](ToolCall(
        id='1',
        name='network_download',
        arguments={'url': 'https://example.com/file.bin', 'directory': 'relative/path'},
    ))
    assert result.status == 'failed'
    assert '绝对路径' in result.error
