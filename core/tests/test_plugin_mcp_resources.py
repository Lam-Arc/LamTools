"""user:“给我把 2 阶段做完，前端除外”+(资源读取通过真实MCP子进程，取消和停用回收连接)。"""
import asyncio
import json
import sys

import pytest

from lamtools_core.plugin_system import PluginContext
from lamtools_core.plugin_system.manifest import load_manifest


@pytest.mark.asyncio
async def test_transport_close_failure_retains_actual_process_for_retry(ctx,monkeypatch):
    # user:“复用原宿主权威”+(原MCP传输关闭失败必须保留真实进程及读取任务引用，不能丢失后再报告重试成功)。
    handle = await ctx.mcp_resources.open("resources").__aenter__()
    await handle.list()
    process = handle._client._proc
    terminate = process.terminate
    attempts = []
    def fail_once():
        attempts.append(True)
        if len(attempts) == 1:
            raise PermissionError("controlled terminate failure")
        terminate()
    monkeypatch.setattr(process,"terminate",fail_once)
    try:
        with pytest.raises(PermissionError):
            await handle.aclose()
        assert handle._client._proc is process and process.returncode is None
        assert handle._client._reader_task is not None
        assert handle in handle._api._handles
        await handle.aclose()
        assert len(attempts) == 2 and process.returncode is not None
        assert handle._client._proc is None and handle._client._reader_task is None
        assert handle not in handle._api._handles
    finally:
        if process.returncode is None:
            terminate()
            await asyncio.wait_for(process.wait(),3)
        await handle._client.close()
        handle._api._handles.discard(handle)
        await ctx._registration_scope.dispose()


@pytest.mark.asyncio
async def test_failed_resource_close_retries_actual_transport_cleanup(ctx,monkeypatch):
    # user:“完成真实接口、参数/错误、作用域、取消/清理”+(清理失败保留连接所有权，重试必须重新执行真实关闭，不能永远复用失败任务)。
    handle = await ctx.mcp_resources.open("resources").__aenter__()
    await handle.list()
    process = handle._client._proc
    original = handle._client.close
    attempts = []
    async def fail_once():
        attempts.append(True)
        if len(attempts) == 1:
            raise RuntimeError("controlled close failure")
        await original()
    monkeypatch.setattr(handle._client,"close",fail_once)
    try:
        with pytest.raises(RuntimeError,match="controlled close failure"):
            await handle.aclose()
        assert handle in handle._api._handles and process.returncode is None
        await handle.aclose()
        assert len(attempts) == 2 and process.returncode is not None
        assert handle not in handle._api._handles
    finally:
        await original()
        handle._api._handles.discard(handle)
        await ctx._registration_scope.dispose()


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


@pytest.mark.asyncio
async def test_lost_resource_connection_never_reopens_its_process(ctx):
    # user:“审查当前代码，然后继续”+(连接已关闭后资源请求明确失败，防止与关闭竞争时重新启动进程)。
    from lamtools_core.plugin_system.mcp_resources import McpResourceError
    async with ctx.mcp_resources.open("resources") as resources:
        original = resources._client._proc
        await resources._client.close()
        assert original.returncode is not None
        with pytest.raises(McpResourceError):
            await resources.read("sample://one")
        assert resources._client._proc is None
    await ctx._registration_scope.dispose()
