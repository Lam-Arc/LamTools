"""user:“实现这个插件，也正好实验我们的新插件架构”+(后台网络操作必须经过宿主的一次性审批)。"""
import json
from pathlib import Path

import pytest

from lamtools_core.app import OperationCatalog
from lamtools_core.plugin_system import PluginHost
from lamtools_core.plugin_system.backend_runtime import remember_context, forget_context
from lamtools_core.plugin_system.context import PluginContext
from lamtools_core.plugin_system.operations import register_plugin_system_operations
from lamtools_core.tool.approval import ApprovalGate


@pytest.fixture
def protected(tmp_path):
    root = tmp_path / 'plugins' / 'consent-demo'
    root.mkdir(parents=True)
    (root / 'plugin.json').write_text(json.dumps({'name': 'consent-demo', 'version': '1', 'operations': ['./operations.json']}))
    (root / 'operations.json').write_text(json.dumps({'operations': [{'name': 'consent-demo.change', 'handler': 'ops:change', 'permission': 'ask_user', 'impact': '改变系统代理'}]}))
    (root / 'ops.py').write_text("async def change(request):\n    return {'executed': request.payload}\n")
    host = PluginHost(roots=[root.parent], state_path=tmp_path / 'state.json')
    gate = ApprovalGate(work_root=tmp_path, tool_permissions={'consent-demo.change': 'ask_user'})
    remember_context('consent-demo', PluginContext(work_root=tmp_path, permission_service=gate))
    catalog = OperationCatalog()
    register_plugin_system_operations(catalog, host)
    yield catalog, host, gate
    forget_context('consent-demo')


async def test_direct_call_cannot_forge_consent(protected):
    catalog, _, _ = protected
    result = await catalog.execute('consent-demo.change', {'value': 1, 'confirmed': True}, metadata={'approved': True})
    assert result.status == 'approval_required'
    assert 'executed' not in result.payload
    assert result.payload['approval']['impact'] == '改变系统代理'


async def test_approval_runs_only_captured_payload_once(protected):
    catalog, _, _ = protected
    payload = {'value': 1}
    pending = await catalog.execute('consent-demo.change', payload)
    payload['value'] = 99
    request_id = pending.payload['approval']['id']
    result = await catalog.execute('plugin.system.operation.respond', {'id': request_id, 'decision': 'approve', 'value': 99})
    assert result.payload['executed'] == {'value': 1}
    replay = await catalog.execute('plugin.system.operation.respond', {'id': request_id, 'decision': 'approve'})
    assert replay.status == 'error'


async def test_denial_never_executes(protected):
    catalog, _, _ = protected
    pending = await catalog.execute('consent-demo.change', {})
    result = await catalog.execute('plugin.system.operation.respond', {'id': pending.payload['approval']['id'], 'decision': 'deny'})
    assert result.status == 'cancelled'
    assert 'executed' not in result.payload


async def test_disable_invalidates_pending_approval(protected):
    catalog, host, _ = protected
    pending = await catalog.execute('consent-demo.change', {})
    host.disable('consent-demo')
    host.enable('consent-demo')
    result = await catalog.execute('plugin.system.operation.respond', {'id': pending.payload['approval']['id'], 'decision': 'approve'})
    assert result.status == 'error'


async def test_hard_block_survives_manual_approval(protected):
    catalog, _, gate = protected
    pending = await catalog.execute('consent-demo.change', {})
    gate.manifest_hard_block_tools.add('consent-demo.change')
    result = await catalog.execute('plugin.system.operation.respond', {'id': pending.payload['approval']['id'], 'decision': 'approve'})
    assert result.status == 'blocked'


async def test_missing_permission_service_fails_closed(protected):
    catalog, _, _ = protected
    forget_context('consent-demo')
    result = await catalog.execute('consent-demo.change', {})
    assert result.status == 'blocked'


async def test_uninstall_stops_backend_before_removing_files(protected):
    catalog, host, _ = protected
    stopped = []
    class Manager:
        async def stop(self, name):
            stopped.append(name)
    host.backend_manager = Manager()
    original = host.uninstall
    def remove(name, **kwargs):
        assert stopped == ['consent-demo']
        return original(name, **kwargs)
    host.uninstall = remove
    result = await catalog.execute('plugin.system.uninstall', {'name': 'consent-demo'})
    assert result.status == 'ok'


async def test_expired_approval_does_not_execute(protected):
    catalog, host, _ = protected
    pending = await catalog.execute('consent-demo.change', {})
    request_id = pending.payload['approval']['id']
    _, spec, captured, fingerprint = host.operation_consent.pending[request_id]
    host.operation_consent.pending[request_id] = (0, spec, captured, fingerprint)
    result = await catalog.execute('plugin.system.operation.respond', {'id': request_id, 'decision': 'approve'})
    assert result.status == 'error'


async def test_existing_host_authorization_does_not_prompt_again(protected):
    catalog, _, gate = protected
    gate.permission_preset = 'full_access'
    result = await catalog.execute('consent-demo.change', {'value': 2})
    assert result.payload['executed'] == {'value': 2}


async def test_confirmation_only_exposes_declared_non_sensitive_arguments(protected):
    from dataclasses import replace
    from lamtools_core.app import OperationRequest
    from lamtools_core.plugin_system.operation_bridge import read_operations
    catalog, host, _ = protected
    spec = replace(read_operations(host.get('consent-demo'))[0], approval_fields=('value',))
    result = host.operation_consent.check(spec, OperationRequest(spec.name, {'value': 3, 'secret': 'must-stay-private'}))
    assert '3' in result.payload['approval']['impact']
    assert 'must-stay-private' not in json.dumps(result.payload)
