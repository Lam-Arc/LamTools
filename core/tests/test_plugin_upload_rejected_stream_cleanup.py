"""user:“建立真实请求、错误、作用域、取消/流和清理验收”+(异常响应流在拒绝未消费输入时也必须回收)。"""
import pytest
from .test_plugin_raw_upload_stream import upload_env, request
from .test_plugin_working_directory import env
from lamtools_core.plugin_system.plugin_http import plugin_http_token

@pytest.mark.asyncio
async def test_incomplete_upload_closes_unexpected_response_stream(upload_env):
    _,host,app=upload_env
    root=host.get('hook-demo').root
    (root/'ops.py').write_text(
        'from pathlib import Path\n'
        'from lamtools_core.app.operation_catalog import OperationResult\n'
        'async def echo(request, *, context):\n'
        '    async def source():\n'
        "        try: yield 'first'\n"
        "        finally: (Path(__file__).parent/'closed.txt').write_text('closed')\n"
        '    stream=source(); await anext(stream)\n'
        '    return OperationResult(request.name,stream)\n',encoding='utf8')
    token=plugin_http_token(host,'hook-demo')
    status,_,read=await request(app,token,1,[{'type':'http.request','body':b'a','more_body':False}])
    assert status in (400,502) and read==0
    assert (root/'closed.txt').read_text()=='closed'
    assert not host._remote_stream_slots

@pytest.mark.asyncio
async def test_revoked_binding_closes_unexpected_response_stream(upload_env,monkeypatch):
    from lamtools_core.plugin_system import remote_upload
    _,host,app=upload_env
    root=host.get('hook-demo').root
    (root/'ops.py').write_text(
        'from pathlib import Path\n'
        'from lamtools_core.app.operation_catalog import OperationResult\n'
        'async def echo(request, *, context):\n'
        "    async for _ in request.payload['body']['stream']: pass\n"
        '    async def source():\n'
        "        try: yield 'first'\n"
        "        finally: (Path(__file__).parent/'closed.txt').write_text('closed')\n"
        '    stream=source(); await anext(stream)\n'
        '    return OperationResult(request.name,stream)\n',encoding='utf8')
    original=remote_upload.dispatch_http_request
    async def revoke_after_dispatch(**kwargs):
        result=await original(**kwargs)
        app.state.providers['catalog']=None
        return result
    monkeypatch.setattr(remote_upload,'dispatch_http_request',revoke_after_dispatch)
    token=plugin_http_token(host,'hook-demo')
    status,_,_=await request(app,token,1,[{'type':'http.request','body':b'a','more_body':False}])
    assert status in (409,502)
    assert (root/'closed.txt').read_text()=='closed'
    assert not host._remote_stream_slots
