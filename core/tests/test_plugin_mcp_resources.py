"""user:“给我把 2 阶段做完，前端除外”+(资源读取通过真实MCP子进程，取消和停用回收连接)。"""
import asyncio
import json
import sys

import pytest

from lamtools_core.plugin_system import PluginContext
from lamtools_core.plugin_system.manifest import load_manifest


SERVER = '''
import json, sys
for line in sys.stdin:
    m = json.loads(line)
    if 'id' not in m: continue
    method = m['method']; params = m.get('params', {})
    if method == 'resources/list': result = {'resources': [{'uri':'sample://one','name':'one'}], 'nextCursor':'next'}
    elif method == 'resources/templates/list': result = {'resourceTemplates':[{'uriTemplate':'sample://{id}','name':'sample'}]}
    elif method == 'resources/read': result = {'contents':[{'uri':params['uri'],'text':'actual resource content'}]}
    else: result = {'capabilities':{'resources':{}}}
    print(json.dumps({'jsonrpc':'2.0','id':m['id'],'result':result}), flush=True)
'''


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    from lamtools_core.config import root
    monkeypatch.setattr(root, "core_config_file", lambda _: tmp_path / "absent.json")
    monkeypatch.delenv("LAMTOOLS_MCP_CONFIG", raising=False)
    script = tmp_path / "server.py"
    script.write_text(SERVER, encoding="utf8")
    config = {"mcpServers": {"resources": {"command": sys.executable, "args": [str(script)], "transport": "json_lines", "timeout": 3}}}
    (tmp_path / "mcp.json").write_text(json.dumps(config), encoding="utf8")
    manifest = tmp_path / "plugin.json"
    manifest.write_text(json.dumps({"name": "probe", "version": "1", "mcp": "./mcp.json"}), encoding="utf8")
    context = PluginContext(tmp_path)
    context._begin_registration_scope("probe", 1, manifest=load_manifest(manifest))
    return context


@pytest.mark.asyncio
async def test_actual_resource_protocol_pages_templates_and_read(ctx):
    assert "resources" in ctx.mcp_resources.servers()
    async with ctx.mcp_resources.open("resources") as resources:
        page = await resources.list(cursor="earlier")
        assert page["resources"][0]["uri"] == "sample://one"
        assert page["nextCursor"] == "next"
        assert (await resources.templates())["resourceTemplates"][0]["uriTemplate"] == "sample://{id}"
        assert (await resources.read("sample://one"))["contents"][0]["text"] == "actual resource content"
        process = resources._client._proc
    assert process.returncode is not None
    await ctx._registration_scope.dispose()


@pytest.mark.asyncio
async def test_unload_closes_open_process_and_revokes_old_handles(ctx):
    from lamtools_core.plugin_system.services import ServiceError
    handle = await ctx.mcp_resources.open("resources").__aenter__()
    await handle.list()
    process = handle._client._proc
    await ctx._registration_scope.dispose()
    assert process.returncode is not None
    with pytest.raises(ServiceError):
        await handle.read("sample://one")


@pytest.mark.asyncio
async def test_unknown_server_invalid_uri_and_unentered_handle_fail(ctx):
    from lamtools_core.plugin_system.mcp_resources import McpResourceError
    with pytest.raises(McpResourceError):
        ctx.mcp_resources.open("unknown")
    resources = ctx.mcp_resources.open("resources")
    with pytest.raises(McpResourceError):
        await resources.list()
    async with resources:
        with pytest.raises(McpResourceError):
            await resources.read("file:\x00bad")
    await ctx._registration_scope.dispose()
