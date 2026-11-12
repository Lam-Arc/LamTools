"""user:“建立真实请求、错误、作用域、取消/流和清理验收”+(处理器暂未读取输入时也须响应令牌撤回)。"""
import asyncio
import pytest
from .test_plugin_raw_upload_stream import upload_env
from .test_plugin_working_directory import env
from lamtools_core.plugin_system.plugin_http import plugin_http_token

@pytest.mark.asyncio
async def test_revocation_during_idle_handler_cancels_and_joins_cleanup(upload_env):
    ctx,host,app=upload_env; root=host.get('hook-demo').root
    (root/'ops.py').write_text(
        'import asyncio\nfrom pathlib import Path\n'
        'async def echo(request, *, context):\n'
        "    (Path(__file__).parent/'entered').touch()\n"
        '    try: await asyncio.Event().wait()\n'
        "    finally: (Path(__file__).parent/'closed').touch()\n",encoding='utf8')
    token=plugin_http_token(host,'hook-demo'); sent=[]; reads=0
    async def receive():
        nonlocal reads
        reads+=1
        await asyncio.Event().wait()
    async def send(message): sent.append(message)
    scope={'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':'POST','scheme':'http',
        'path':'/plugin-upload/hook-demo/files','query_string':b'',
        'headers':[(b'content-type',b'application/octet-stream'),(b'x-upload-size',b'1'),(b'x-plugin-token',token.encode())],
        'client':('127.0.0.1',123),'server':('test',80)}
    task=asyncio.create_task(app(scope,receive,send))
    try:
        async with asyncio.timeout(3):
            while not (root/'entered').exists(): await asyncio.sleep(.01)
        ctx._secret_store.view('hook-demo').delete('httpToken')
        await asyncio.wait_for(asyncio.shield(task),2)
        assert (root/'closed').exists() and reads==0
        assert next(x['status'] for x in sent if x['type']=='http.response.start')==409
        assert not host._remote_stream_slots
    finally:
        if not task.done(): task.cancel()
        await asyncio.gather(task,return_exceptions=True)

@pytest.mark.asyncio
async def test_revocation_awaits_handler_cleanup_before_releasing_slot(upload_env):
    ctx,host,app=upload_env; root=host.get('hook-demo').root
    (root/'ops.py').write_text(
        'import asyncio\nfrom pathlib import Path\n'
        'async def echo(request, *, context):\n'
        "    root=Path(__file__).parent; (root/'entered').touch()\n"
        '    try: await asyncio.Event().wait()\n'
        '    finally:\n'
        "        (root/'cleaning').touch()\n"
        "        while not (root/'release').exists(): await asyncio.sleep(.01)\n"
        "        (root/'closed').touch()\n",encoding='utf8')
    token=plugin_http_token(host,'hook-demo'); sent=[]
    async def receive(): await asyncio.Event().wait()
    async def send(message): sent.append(message)
    scope={'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':'POST','scheme':'http',
        'path':'/plugin-upload/hook-demo/files','query_string':b'',
        'headers':[(b'content-type',b'application/octet-stream'),(b'x-upload-size',b'1'),(b'x-plugin-token',token.encode())],
        'client':('127.0.0.1',123),'server':('test',80)}
    task=asyncio.create_task(app(scope,receive,send))
    try:
        async with asyncio.timeout(3):
            while not (root/'entered').exists(): await asyncio.sleep(.01)
        ctx._secret_store.view('hook-demo').delete('httpToken')
        async with asyncio.timeout(3):
            while not (root/'cleaning').exists(): await asyncio.sleep(.01)
        assert not task.done() and host._remote_stream_slots
        task.cancel(); task.cancel(); (root/'release').touch()
        result=await asyncio.gather(task,return_exceptions=True)
        assert isinstance(result[0],asyncio.CancelledError)
        assert (root/'closed').exists() and not host._remote_stream_slots
    finally:
        (root/'release').touch()
        if not task.done(): task.cancel()
        await asyncio.gather(task,return_exceptions=True)
