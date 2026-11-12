"""user:“建立真实请求、错误、作用域、取消/流和清理验收”+(等待输出不应把同一原助手消息重复完成当作多条)。"""
import pytest
from .test_plugin_working_directory import env
from .test_plugin_checkpoint_access import setup
from lamtools_core.event import RunItemEvent

@pytest.mark.asyncio
async def test_wait_output_deduplicates_same_native_item(setup):
    ctx,_,_,_,db=setup
    async with db.session_factory() as session:
        for text in ['draft','final']:
            await db.event_store.append_run_item_event(session,RunItemEvent(kind='message',thread_id='s',turn_id='turn',item_id='assistant-one',status='completed',payload={'type':'agentMessage','content':text}))
        await db.event_store.append_run_item_event(session,RunItemEvent(kind='message',thread_id='s',turn_id='turn',item_id='assistant-two',status='completed',payload={'type':'agentMessage','content':'second'}))
        events=await db.event_store.list_thread(session,thread_id='s'); await db.snapshot_store.apply_many(session,events); await session.commit()
    result=await ctx.session_controller.wait_with_output('s',timeout=0,max_messages=2)
    assert [row['text'] for row in result['messages']]==['second','final']
    assert result['scan_complete'] and not result['truncated']

@pytest.mark.asyncio
async def test_missing_item_identifiers_remain_distinct(setup):
    ctx,_,_,_,db=setup
    async with db.session_factory() as session:
        for text in ['one','two']:
            await db.event_store.append_run_item_event(session,RunItemEvent(kind='message',thread_id='s',turn_id='turn',status='completed',payload={'type':'agentMessage','content':text}))
        events=await db.event_store.list_thread(session,thread_id='s'); await db.snapshot_store.apply_many(session,events); await session.commit()
    result=await ctx.session_controller.wait_with_output('s',timeout=0,max_messages=2)
    assert [row['text'] for row in result['messages']]==['two','one'] and not result['truncated']

@pytest.mark.asyncio
async def test_deduplicated_output_crosses_real_remote(setup,tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router,plugin_http_token
    ctx,_,_,_,db=setup
    async with db.session_factory() as session:
        for text in ['old','new']:
            await db.event_store.append_run_item_event(session,RunItemEvent(kind='message',thread_id='s',turn_id='turn',item_id='assistant-one',status='completed',payload={'type':'agentMessage','content':text}))
        events=await db.event_store.list_thread(session,thread_id='s'); await db.snapshot_store.apply_many(session,events); await session.commit()
    host,catalog,old=_host(tmp_path); configure(host); ctx._secret_store=old._secret_store; host.backend_manager.context=ctx
    (host.get('hook-demo').root/'ops.py').write_text("async def echo(request, *, context):\n    return await context.session_controller.wait_with_output('s',timeout=0,max_messages=1)\n",encoding='utf8')
    catalog.unregister_owner('plugin:hook-demo'); register_plugin_operations(catalog,host)
    app=FastAPI(); app.include_router(create_plugin_http_router(lambda:host,lambda:catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        response=await client.post('/plugin-remote/hook-demo/demo/echo',json={'args':{'text':'x'}},headers={'x-plugin-token':plugin_http_token(host,'hook-demo')})
    assert response.status_code==200
    output=response.json()['payload']; assert [x['text'] for x in output['messages']]==['new'] and not output['truncated']
