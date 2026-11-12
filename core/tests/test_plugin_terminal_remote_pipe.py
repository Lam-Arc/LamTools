"""user:“第二阶段结束后 就继续开展第三阶段”+(会话显式远程入口可交互原受管管道并清理)。"""
import asyncio
import base64
import os
import sys
import pytest
from .test_plugin_working_directory import env


@pytest.mark.asyncio
@pytest.mark.skipif(os.name!='nt',reason='original managed process is Windows-only')
async def test_managed_pipe_interacts_and_is_scoped(env):
    ctx,_,_,_=env; api=ctx.terminal_controller
    created=await api.create_pipe('s',[sys.executable,'-u','-c','import sys; print(input(),flush=True)'],timeout=10)
    tid=created['id']
    try:
        with pytest.raises(RuntimeError): await api.read_pipe('hidden',tid)
        with pytest.raises(RuntimeError): await api.send_pipe('s','unknown',base64.b64encode(b'x').decode())
        assert (await api.send_pipe('s',tid,base64.b64encode(b'hello\n').decode()))['written']==6
        for _ in range(100):
            output=await api.read_pipe('s',tid)
            if output['complete']: break
            await asyncio.sleep(.03)
        assert b'hello' in base64.b64decode(output['stdout_base64']) and output['complete']
    finally:
        await api.close_pipe('s',tid)
    with pytest.raises(RuntimeError): await api.read_pipe('s',tid)


@pytest.mark.asyncio
@pytest.mark.skipif(os.name!='nt',reason='original managed process is Windows-only')
async def test_pipe_scope_disposal_closes_real_process(env):
    ctx,_,_,_=env; api=ctx.terminal_controller
    tid=(await api.create_pipe('s',[sys.executable,'-c','import time; time.sleep(20)'],timeout=25))['id']
    terminal=ctx._registration_scope._session_terminal_pipes[tid][1]
    await asyncio.wait_for(ctx._registration_scope.dispose(),4)
    assert terminal._process._cleaned and not ctx._registration_scope._session_terminal_pipes


@pytest.mark.asyncio
@pytest.mark.parametrize('limit',[0,262145,True,'bad'])
async def test_invalid_output_limit_does_not_spawn(env,monkeypatch,limit):
    ctx,_,_,_=env; api=ctx.terminal_controller
    async def forbidden(*args,**kwargs): pytest.fail('invalid limit started process')
    monkeypatch.setattr(api,'open',forbidden)
    with pytest.raises(RuntimeError) as exc:
        await api.create_pipe('s',[sys.executable],timeout=1,max_output_bytes=limit)
    assert exc.value.code=='terminal/invalid-limit'


@pytest.mark.asyncio
@pytest.mark.skipif(os.name!='nt',reason='original managed process is Windows-only')
async def test_pipe_invalid_input_and_post_send_scope_change(env,monkeypatch):
    from lamtools_core.plugin_system.terminal_access import PluginTerminal
    ctx,store,_,_=env; api=ctx.terminal_controller
    tid=(await api.create_pipe('s',[sys.executable,'-u','-c','import sys,time; input(); time.sleep(20)'],timeout=25))['id']
    original=PluginTerminal.send; entered,release=asyncio.Event(),asyncio.Event()
    async def gated(self,*args,**kwargs):
        n=await original(self,*args,**kwargs)
        entered.set(); await release.wait(); return n
    monkeypatch.setattr(PluginTerminal,'send',gated)
    try:
        with pytest.raises(RuntimeError) as error: await api.send_pipe('s',tid,'not-base64!')
        assert error.value.code=='terminal/invalid-input'
        task=asyncio.create_task(api.send_pipe('s',tid,base64.b64encode(b'go\n').decode()))
        await asyncio.wait_for(entered.wait(),3)
        store._session_visible=lambda *_:False
        release.set()
        with pytest.raises(RuntimeError) as error: await task
        assert error.value.code=='terminal/write-uncertain' and error.value.may_have_changed
    finally:
        release.set()
        await api.close_pipe('s',tid)


@pytest.mark.asyncio
@pytest.mark.skipif(os.name!='nt',reason='original managed process is Windows-only')
async def test_pipe_interaction_crosses_explicit_remote(env,tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router,plugin_http_token
    ctx,_,_,_=env; host,catalog,old=_host(tmp_path); configure(host)
    ctx._secret_store=old._secret_store; host.backend_manager.context=ctx
    (host.get('hook-demo').root/'ops.py').write_text(
        'import json,sys\n'
        'async def echo(request, *, context):\n'
        "    api=context.terminal_controller; value=json.loads(request.payload['body']['text'])\n"
        "    if value['op']=='create': return await api.create_pipe('s',[sys.executable,'-u','-c','print(input(),flush=True)'],timeout=10)\n"
        "    if value['op']=='send': return await api.send_pipe('s',value['id'],value['data'])\n"
        "    if value['op']=='read': return await api.read_pipe('s',value['id'])\n"
        "    await api.close_pipe('s',value['id']); return {'closed':True}\n",encoding='utf8')
    catalog.unregister_owner('plugin:hook-demo'); register_plugin_operations(catalog,host)
    app=FastAPI(); app.include_router(create_plugin_http_router(lambda:host,lambda:catalog))
    import json
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        path='/plugin-remote/hook-demo/demo/echo'; headers={'x-plugin-token':plugin_http_token(host,'hook-demo')}
        async def call(value,token=headers):
            return await client.post(path,json={'args':{'text':json.dumps(value)}},headers=token)
        assert (await call({'op':'create'},{'x-plugin-token':'wrong'})).status_code==401
        created=await call({'op':'create'}); assert created.status_code==200
        tid=created.json()['payload']['id']
        try:
            assert (await call({'op':'send','id':tid,'data':base64.b64encode(b'remote\n').decode()})).status_code==200
            for _ in range(100):
                output=await call({'op':'read','id':tid})
                assert output.status_code==200
                if output.json()['payload']['complete']: break
                await asyncio.sleep(.03)
            assert b'remote' in base64.b64decode(output.json()['payload']['stdout_base64'])
        finally:
            assert (await call({'op':'close','id':tid})).status_code==200


@pytest.mark.asyncio
@pytest.mark.skipif(os.name!='nt',reason='original managed process is Windows-only')
async def test_close_cancellation_waits_for_original_process_cleanup(env,monkeypatch):
    from lamtools_core.plugin_system.terminal_access import PluginTerminal
    ctx,_,_,_=env; api=ctx.terminal_controller
    tid=(await api.create_pipe('s',[sys.executable,'-c','import time;time.sleep(20)'],timeout=25))['id']
    terminal=ctx._registration_scope._session_terminal_pipes[tid][1]
    original=PluginTerminal.close; entered,release=asyncio.Event(),asyncio.Event()
    async def gated(self):
        entered.set(); await release.wait(); return await original(self)
    monkeypatch.setattr(PluginTerminal,'close',gated)
    task=asyncio.create_task(api.close_pipe('s',tid))
    try:
        await asyncio.wait_for(entered.wait(),3)
        task.cancel(); await asyncio.sleep(0); task.cancel(); await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError): await task
        assert terminal._process._cleaned and tid not in ctx._registration_scope._session_terminal_pipes
    finally:
        release.set(); await asyncio.gather(task,return_exceptions=True)
        if not terminal._process._cleaned: await original(terminal)


def test_terminal_migration_describes_pipe_and_duplex_limit(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root=source(tmp_path,{'index.ts':'export function apply(ctx) { ctx.remote.terminal.create(); ctx.remote.terminal.attach(); ctx.remote.terminal.close(); }'})
    report=export_port(root,tmp_path/'ported'); rows={x['name']:x for x in report['remotes']}
    assert rows['terminal.create']['suggestedContract']=='context.terminal_controller.create_pipe'
    assert rows['terminal.attach']['suggestedContract']=='context.terminal_controller.send_pipe/follow_pipe'
    assert rows['terminal.close']['suggestedContract']=='context.terminal_controller.close_pipe'
    assert report['runtimeVerified'] is False
