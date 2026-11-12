"""user:“继续”+(分块接收仍交给原附件权威，取消不能留下半成品)。"""
import asyncio
from pathlib import Path
import pytest
from .test_plugin_session_data import env


@pytest.mark.asyncio
async def test_chunks_save_original_attachment_and_close_source(env):
    ctx,_,_,_=env; closed=asyncio.Event(); chunks=[b'a'*200000,b'b'*200000,b'c'*200000]
    async def source():
        try:
            for chunk in chunks: yield chunk
        finally: closed.set()
    result=await ctx.file_uploads.save_chunks('s',filename='chunks.bin',source=source(),size=600000)
    assert closed.is_set() and Path(result['path']).read_bytes()==b''.join(chunks)
    assert (await ctx.attachments.get('s',result['id']))['id']==result['id']


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['cancel','hidden','host'])
async def test_upload_aborted_before_commit_closes_source_without_attachment(env,change):
    ctx,store,_,_=env; entered,release,closed=asyncio.Event(),asyncio.Event(),asyncio.Event()
    original_host=ctx.require_service('session_data'); original_visible=store._session_visible
    async def source():
        try:
            yield b'a'
            entered.set(); await release.wait(); yield b'b'
        finally: closed.set()
    task=asyncio.create_task(ctx.file_uploads.save_chunks('s',filename='must-not-exist',source=source(),size=2))
    try:
        await asyncio.wait_for(entered.wait(),3)
        if change=='cancel': task.cancel()
        elif change=='hidden': store._session_visible=lambda *_:False
        else: ctx.set_service('session_data',object())
        release.set()
        with pytest.raises(asyncio.CancelledError if change=='cancel' else RuntimeError): await task
        assert closed.is_set()
        store._session_visible=original_visible; ctx.set_service('session_data',original_host)
        assert not (await ctx.attachments.list('s'))['items']
    finally:
        release.set(); await asyncio.gather(task,return_exceptions=True)


@pytest.mark.asyncio
async def test_empty_input_and_encoded_entry_still_use_original_storage(env):
    ctx,_,_,_=env
    async def empty():
        if False: yield b''
    empty_result=await ctx.file_uploads.save_chunks('s',filename='empty',source=empty(),size=0)
    encoded=await ctx.file_uploads.save_encoded('s',filename='encoded',content_base64='YQ==')
    assert Path(empty_result['path']).read_bytes()==b'' and Path(encoded['path']).read_bytes()==b'a'


@pytest.mark.asyncio
async def test_chunk_count_limit_rejects_without_commit(env,monkeypatch):
    from lamtools_core.plugin_system import file_uploads
    monkeypatch.setattr(file_uploads,'MAX_UPLOAD_CHUNKS',2)
    ctx,_,_,_=env; closed=asyncio.Event()
    async def source():
        try:
            yield b''; yield b''; yield b''
        finally: closed.set()
    with pytest.raises(RuntimeError): await ctx.file_uploads.save_chunks('s',filename='too-many',source=source(),size=0)
    assert closed.is_set() and not (await ctx.attachments.list('s'))['items']


@pytest.mark.asyncio
@pytest.mark.parametrize('size',[-1,8*1024*1024+1,True,'4'])
async def test_invalid_declared_size_rejected_before_reading_source(env,size):
    ctx,_,_,_=env; started=False
    async def source():
        nonlocal started
        started=True
        yield b'a'
    with pytest.raises(RuntimeError): await ctx.file_uploads.save_chunks('s',filename='invalid',source=source(),size=size)
    assert not started and not (await ctx.attachments.list('s'))['items']


@pytest.mark.asyncio
async def test_source_error_closes_without_saving_partial_bytes(env):
    ctx,_,_,_=env; closed=asyncio.Event()
    async def source():
        try:
            yield b'a'
            raise OSError('source failed')
        finally: closed.set()
    with pytest.raises(OSError): await ctx.file_uploads.save_chunks('s',filename='failed',source=source(),size=2)
    assert closed.is_set() and not (await ctx.attachments.list('s'))['items']


@pytest.mark.asyncio
async def test_chunks_via_explicit_remote_uses_original_storage(env,tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router,plugin_http_token
    ctx,_,_,_=env; host,catalog,old=_host(tmp_path); configure(host)
    ctx._secret_store=old._secret_store; host.backend_manager.context=ctx
    (host.get('hook-demo').root/'ops.py').write_text(
        "async def echo(request, *, context):\n"
        "    raw=request.payload['body']['text'].encode('utf8')\n"
        "    async def source():\n        yield raw[:1]\n        yield raw[1:]\n"
        "    value=await context.file_uploads.save_chunks('s',filename='remote',source=source(),size=len(raw))\n"
        "    return {'id':value['id']}\n",encoding='utf8')
    catalog.unregister_owner('plugin:hook-demo'); register_plugin_operations(catalog,host)
    app=FastAPI(); app.include_router(create_plugin_http_router(lambda:host,lambda:catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        endpoint='/plugin-remote/hook-demo/demo/echo'; body={'args':{'text':'remote bytes'}}
        denied=await client.post(endpoint,json=body,headers={'x-plugin-token':'wrong'})
        assert denied.status_code==401 and not (await ctx.attachments.list('s'))['items']
        response=await client.post(endpoint,json=body,headers={'x-plugin-token':plugin_http_token(host,'hook-demo')})
    assert response.status_code==200
    assert Path((await ctx.attachments.get('s',response.json()['payload']['id']))['path']).read_bytes()==b'remote bytes'


@pytest.mark.asyncio
@pytest.mark.parametrize('chunks,size', [([b'a'],2),([b'abc'],2),([b'a','bad'],2),([b'a'*262145],262145)])
async def test_invalid_chunks_never_commit(env,chunks,size):
    ctx,_,_,_=env; closed=asyncio.Event()
    async def source():
        try:
            for chunk in chunks: yield chunk
        finally: closed.set()
    with pytest.raises(RuntimeError): await ctx.file_uploads.save_chunks('s',filename='invalid',source=source(),size=size)
    assert closed.is_set() and not (await ctx.attachments.list('s'))['items']


@pytest.mark.asyncio
async def test_repeated_cancel_awaits_source_cleanup(env):
    ctx,_,_,_=env; entered,closing,release=asyncio.Event(),asyncio.Event(),asyncio.Event()
    async def source():
        try:
            entered.set(); await asyncio.Event().wait(); yield b'a'
        finally:
            closing.set(); await release.wait()
    task=asyncio.create_task(ctx.file_uploads.save_chunks('s',filename='cancel',source=source(),size=1))
    try:
        await asyncio.wait_for(entered.wait(),3)
        task.cancel(); await asyncio.wait_for(closing.wait(),3)
        task.cancel(); await asyncio.sleep(.02)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError): await task
        assert not (await ctx.attachments.list('s'))['items']
    finally:
        release.set(); await asyncio.gather(task,return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['scope','hidden','host','root'])
async def test_idle_source_is_stopped_when_scope_or_session_is_revoked(env,change,tmp_path):
    ctx,store,_,_=env; entered,closed,release=asyncio.Event(),asyncio.Event(),asyncio.Event()
    async def source():
        try:
            entered.set(); await release.wait(); yield b'a'
        finally: closed.set()
    task=asyncio.create_task(ctx.file_uploads.save_chunks('s',filename='idle',source=source(),size=1))
    try:
        await asyncio.wait_for(entered.wait(),3)
        if change=='scope': ctx._registration_scope.revoke()
        elif change=='hidden': store._session_visible=lambda *_:False
        elif change=='host': ctx.set_service('session_data',object())
        else: ctx.work_root=tmp_path/'other'
        done,_=await asyncio.wait({task},timeout=1.5)
        assert task in done and closed.is_set()
        with pytest.raises(RuntimeError): await task
    finally:
        release.set(); await asyncio.gather(task,return_exceptions=True)


@pytest.mark.asyncio
async def test_scope_disposal_joins_idle_source_cleanup(env):
    ctx,_,_,_=env; entered,closed=asyncio.Event(),asyncio.Event()
    async def source():
        try:
            entered.set(); await asyncio.Event().wait(); yield b'a'
        finally: closed.set()
    task=asyncio.create_task(ctx.file_uploads.save_chunks('s',filename='idle',source=source(),size=1))
    try:
        await asyncio.wait_for(entered.wait(),3)
        await asyncio.wait_for(ctx._registration_scope.dispose(),3)
        assert task.done() and closed.is_set()
        with pytest.raises(RuntimeError): await task
    finally:
        if not task.done(): task.cancel()
        await asyncio.gather(task,return_exceptions=True)


def test_upload_migration_mentions_bounded_chunks_without_staged_receipt(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root=source(tmp_path,{'index.ts':'export function apply(ctx) { ctx.fileUploads.upload(); }'})
    report=export_port(root,tmp_path/'ported'); row=next(x for x in report['services'] if x['name']=='fileUploads')
    assert '分块' in row['difference'] and '暂存' in row['difference'] and report['runtimeVerified'] is False


@pytest.mark.asyncio
async def test_repeated_cancel_after_dispatch_waits_for_native_commit(env,monkeypatch):
    ctx,_,_,_=env; host=ctx.require_service('session_data'); original=host.call
    entered,release=asyncio.Event(),asyncio.Event()
    async def gated(*args,**kwargs):
        if args[3]=='create': entered.set(); await release.wait()
        return await original(*args,**kwargs)
    monkeypatch.setattr(host,'call',gated)
    async def source(): yield b'data'
    task=asyncio.create_task(ctx.file_uploads.save_chunks('s',filename='committed',source=source(),size=4))
    try:
        await asyncio.wait_for(entered.wait(),3)
        task.cancel(); await asyncio.sleep(0); task.cancel(); await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError): await task
        assert any(x['filename']=='committed' for x in (await ctx.attachments.list('s'))['items'])
    finally:
        release.set(); await asyncio.gather(task,return_exceptions=True)
