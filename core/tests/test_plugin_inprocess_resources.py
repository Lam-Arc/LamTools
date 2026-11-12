"""user:“第二阶段结束后 就继续开展第三阶段”+(当前插件可按原资源规则在进程内读取自身资源)。"""
import asyncio
import pytest
from .test_plugin_explicit_resources import resource_env
from lamtools_core.plugin_system.plugin_http import plugin_http_token

@pytest.fixture
async def local_resource_env(resource_env):
    host,catalog,app=resource_env; ctx=host.backend_manager.context; catalog.plugin_system_host=host; ctx.operation_catalog=catalog
    ctx._begin_registration_scope('hook-demo',1,manifest=host.get('hook-demo'))
    try:yield ctx,host,catalog,app
    finally:await ctx._registration_scope.dispose()

@pytest.mark.asyncio
async def test_in_process_read_uses_same_real_resource_get_and_head(local_resource_env):
    ctx,host,_,_=local_resource_env; plugin_http_token(host,'hook-demo')
    result=await ctx.plugin_resources.read('/a/b/c')
    head=await ctx.plugin_resources.read('/a/b/c',method='HEAD')
    assert result['status']==200 and result['body']==b'exact' and result['headers']['content-type'].startswith('text/plain')
    assert head['status']==200 and head['body']==b'' and head['headers']['content-length']=='5'
    assert not host._remote_stream_slots and ctx._registration_scope._idle.is_set()

@pytest.mark.asyncio
async def test_in_process_read_does_not_create_or_return_token(local_resource_env):
    ctx,host,_,_=local_resource_env
    result=await ctx.plugin_resources.read('/a/b/c')
    assert result['status']==401 and not host.backend_manager.context._secret_store.view('hook-demo').get('httpToken')
    assert 'httpToken' not in str(result)

@pytest.mark.asyncio
@pytest.mark.parametrize('method',['POST','',None])
async def test_in_process_read_rejects_wrong_method(local_resource_env,method):
    ctx,_,_,_=local_resource_env
    with pytest.raises(ValueError):await ctx.plugin_resources.read('/a/b/c',method=method)

@pytest.mark.asyncio
async def test_in_process_stream_reads_real_chunks_and_head_closes(local_resource_env):
    from .test_plugin_streaming_resources import enable_stream
    ctx,host,_,_=local_resource_env; plugin_http_token(host,'hook-demo'); enable_stream(host); root=host.get('hook-demo').root
    (root/'ops.py').write_text("async def exact(request, *, context):\n    async def content():\n        yield b'a'\n        yield b'b'\n    return {'content':content(), 'mime_type':'application/octet-stream'}\n",encoding='utf8')
    result=await ctx.plugin_resources.read('/a/b/c')
    head=await ctx.plugin_resources.read('/a/b/c',method='HEAD')
    assert result['status']==200 and result['body']==b'ab' and 'content-length' not in result['headers']
    assert head['status']==200 and head['body']==b'' and 'content-length' not in head['headers']
    assert not host._remote_stream_slots and ctx._registration_scope._idle.is_set()

@pytest.mark.asyncio
@pytest.mark.parametrize('path',['relative','/a/../b','/bad\\path','/'+('x'*2049)])
async def test_in_process_read_rejects_invalid_paths(local_resource_env,path):
    ctx,_,_,_=local_resource_env
    with pytest.raises(ValueError):await ctx.plugin_resources.read(path)

@pytest.mark.asyncio
async def test_in_process_read_rejects_replaced_host(local_resource_env):
    ctx,host,catalog,_=local_resource_env; plugin_http_token(host,'hook-demo'); api=ctx.plugin_resources
    catalog.plugin_system_host=object()
    with pytest.raises(RuntimeError):await api.read('/a/b/c')

@pytest.mark.asyncio
@pytest.mark.parametrize('stop',['cancel','revoke'])
async def test_in_process_read_joins_handler_cleanup_on_cancel_or_scope_revocation(local_resource_env,monkeypatch,stop):
    ctx,host,catalog,_=local_resource_env; plugin_http_token(host,'hook-demo'); entered,cleaning,release,closed=asyncio.Event(),asyncio.Event(),asyncio.Event(),asyncio.Event()
    async def gated(*args,**kwargs):
        entered.set()
        try:await asyncio.Event().wait()
        finally:cleaning.set(); await release.wait(); closed.set()
    monkeypatch.setattr(catalog,'execute',gated); task=asyncio.create_task(ctx.plugin_resources.read('/a/b/c'))
    try:
        await asyncio.wait_for(entered.wait(),3)
        if stop=='cancel':task.cancel()
        else:ctx._registration_scope.revoke()
        await asyncio.wait_for(cleaning.wait(),3)
        if stop=='cancel':task.cancel()
        await asyncio.sleep(0); assert not task.done() and not ctx._registration_scope._idle.is_set()
        release.set()
        with pytest.raises(asyncio.CancelledError if stop=='cancel' else RuntimeError):await task
        assert closed.is_set() and ctx._registration_scope._idle.is_set() and not host._remote_stream_slots
    finally:
        release.set()
        if not task.done():task.cancel()
        await asyncio.gather(task,return_exceptions=True)

@pytest.mark.asyncio
async def test_in_process_stream_failure_does_not_return_partial_bytes(local_resource_env,monkeypatch):
    from .test_plugin_streaming_resources import enable_stream
    from lamtools_core.app.operation_catalog import OperationResult
    ctx,host,catalog,_=local_resource_env; plugin_http_token(host,'hook-demo'); enable_stream(host); closed=asyncio.Event()
    class Source:
        def __init__(self):self.count=0
        def __aiter__(self):return self
        async def __anext__(self):
            self.count+=1
            return b'partial-secret' if self.count==1 else b'x'*(256*1024+1)
        async def aclose(self):closed.set()
    async def handler(name,*args,**kwargs):return OperationResult(name,{'content':Source(),'mime_type':'application/octet-stream'})
    monkeypatch.setattr(catalog,'execute',handler)
    with pytest.raises(ValueError):await ctx.plugin_resources.read('/a/b/c')
    assert closed.is_set() and not host._remote_stream_slots and ctx._registration_scope._idle.is_set()

@pytest.mark.asyncio
async def test_in_process_stream_revoke_closes_inflight_source(local_resource_env,monkeypatch):
    from .test_plugin_streaming_resources import enable_stream
    from lamtools_core.app.operation_catalog import OperationResult
    ctx,host,catalog,_=local_resource_env; plugin_http_token(host,'hook-demo'); enable_stream(host)
    entered,cleaning,release,closed=asyncio.Event(),asyncio.Event(),asyncio.Event(),asyncio.Event()
    class Source:
        def __aiter__(self):return self
        async def __anext__(self):entered.set(); await asyncio.Event().wait()
        async def aclose(self):cleaning.set(); await release.wait(); closed.set()
    async def handler(name,*args,**kwargs):return OperationResult(name,{'content':Source(),'mime_type':'application/octet-stream'})
    monkeypatch.setattr(catalog,'execute',handler); task=asyncio.create_task(ctx.plugin_resources.read('/a/b/c'))
    try:
        await asyncio.wait_for(entered.wait(),3); ctx._registration_scope.revoke(); await asyncio.wait_for(cleaning.wait(),3)
        assert not task.done() and host._remote_stream_slots and not ctx._registration_scope._idle.is_set()
        release.set()
        with pytest.raises(RuntimeError):await task
        assert closed.is_set() and not host._remote_stream_slots and ctx._registration_scope._idle.is_set()
    finally:
        release.set()
        if not task.done():task.cancel()
        await asyncio.gather(task,return_exceptions=True)

def test_in_process_resource_migration_reports_scope(tmp_path):
    import json
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root=source(tmp_path,{'index.ts':'export function apply(ctx) { ctx.webServer.readResource(); }'})
    output=tmp_path/'ported'; report=export_port(root,output); handoff=(output/'PORTING.md').read_text(encoding='utf8')
    assert 'context.plugin_resources.read' in handoff and report['runtimeVerified'] is False
    assert not json.loads((output/'plugin.json').read_text(encoding='utf8')).get('http',{}).get('resources')

@pytest.mark.asyncio
async def test_in_process_read_never_transfers_private_token_to_handler(local_resource_env):
    ctx,host,_,_=local_resource_env; token=plugin_http_token(host,'hook-demo'); root=host.get('hook-demo').root
    (root/'ops.py').write_text("def exact(request, *, context):\n    return {'content':str(request.payload['headers']).encode(), 'mime_type':'text/plain'}\n",encoding='utf8')
    result=await ctx.plugin_resources.read('/a/b/c')
    assert result['status']==200 and token.encode() not in result['body'] and b'x-plugin-token' not in result['body']

@pytest.mark.asyncio
async def test_in_process_resource_missing_host_is_not_fake_success(tmp_path):
    from lamtools_core.app.operation_catalog import OperationCatalog
    from lamtools_core.plugin_system.context import PluginContext
    ctx=PluginContext(tmp_path,operation_catalog=OperationCatalog());ctx._begin_registration_scope('missing',1)
    try:
        with pytest.raises(RuntimeError):await ctx.plugin_resources.read('/a')
    finally:await ctx._registration_scope.dispose()
