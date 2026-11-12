"""user:“建立真实请求、错误、作用域、取消/流和清理验收”+(进程内资源查询沿用原资源处理器)。"""
import pytest
from .test_plugin_inprocess_resources import local_resource_env
from .test_plugin_explicit_resources import resource_env
from lamtools_core.plugin_system.plugin_http import plugin_http_token


@pytest.mark.asyncio
async def test_inprocess_query_reaches_declared_handler(local_resource_env):
    ctx, host, _, _ = local_resource_env
    plugin_http_token(host, 'hook-demo')
    (host.get('hook-demo').root / 'ops.py').write_text(
        "def exact(request, *, context):\n    return {'content':request.payload['query']['name'].encode(), 'mime_type':'text/plain'}\n", encoding='utf8')
    result = await ctx.plugin_resources.read('/a/b/c', query={'name': '中文 & value'})
    assert result['status'] == 200 and result['body'].decode() == '中文 & value'
    assert ctx._registration_scope._idle.is_set() and not host._remote_stream_slots


@pytest.mark.asyncio
async def test_inprocess_query_head_and_empty_query(local_resource_env):
    ctx, host, _, _ = local_resource_env
    plugin_http_token(host, 'hook-demo')
    (host.get('hook-demo').root / 'ops.py').write_text(
        "def exact(request, *, context):\n    return {'content':str(request.payload['query'].get('q', '')).encode(), 'mime_type':'text/plain'}\n", encoding='utf8')
    head = await ctx.plugin_resources.read('/a/b/c', method='HEAD', query={'q': 'test'})
    plain = await ctx.plugin_resources.read('/a/b/c')
    assert head['status'] == 200 and head['body'] == b'' and head['headers']['content-length'] == '4'
    assert plain['status'] == 200 and plain['body'] == b''


@pytest.mark.asyncio
@pytest.mark.parametrize('query', [[], {'x': 2}, {2: 'x'}, {'x': 'a' * 8192}, {'x': '中' * 1000}, {'x': '\ud800'}])
async def test_inprocess_query_rejects_invalid_before_dispatch(local_resource_env, monkeypatch, query):
    ctx, _, catalog, _ = local_resource_env
    async def fail(*args, **kwargs):
        pytest.fail('invalid query was dispatched')
    monkeypatch.setattr(catalog, 'execute', fail)
    with pytest.raises(ValueError):
        await ctx.plugin_resources.read('/a/b/c', query=query)
    assert ctx._registration_scope._idle.is_set()
