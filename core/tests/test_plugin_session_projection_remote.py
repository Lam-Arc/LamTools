"""user:“复用原宿主权威”+(会话投影经原有限摘要和认证入口访问)。"""
import httpx
import pytest
from fastapi import FastAPI

from .test_plugin_working_directory import env
from .test_plugin_http_routes import _host
from .test_plugin_remote_gateway import configure
from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token


@pytest.mark.asyncio
async def test_original_projection_via_remote_respects_visibility(env, tmp_path):
    ctx, _, _, _ = env
    host, catalog, original = _host(tmp_path)
    configure(host)
    ctx._secret_store = original._secret_store
    host.backend_manager.context = ctx
    (host.get('hook-demo').root / 'ops.py').write_text(
        'async def echo(request, *, context):\n'
        '    return await context.session_projections.get(request.payload["body"]["text"])\n', encoding='utf8')
    catalog.unregister_owner('plugin:hook-demo')
    register_plugin_operations(catalog, host)
    app = FastAPI(); app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        url = '/plugin-remote/hook-demo/demo/echo'
        async def request(sid, token):
            return await client.post(url, json={'args': {'text': sid}}, headers={'x-plugin-token': token})
        token = plugin_http_token(host, 'hook-demo')
        denied = await request('s', 'wrong')
        hidden = await request('hidden', token)
        visible = await request('s', token)
    assert denied.status_code == 401 and hidden.status_code != 200
    assert visible.status_code == 200 and visible.json()['payload']['title'] == 'Example'


def test_projection_migration_names_limited_original_summary(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root = source(tmp_path, {'index.ts': 'export function apply(ctx) { ctx.remote.session.projections(); }'})
    report = export_port(root, tmp_path / 'ported')
    row = next(item for item in report['remotes'] if item['name'] == 'session.projections')
    assert row['suggestedContract'] == 'context.session_projections.get'
    assert '有限' in row['difference'] and report['runtimeVerified'] is False
