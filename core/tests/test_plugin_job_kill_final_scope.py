"""user:“第二阶段结束后 就继续开展第三阶段”+(停止作业结算后复核会话，失效时保守报告可能已变更)。"""
import asyncio
import pytest
from .test_plugin_working_directory import env


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['hidden','moved','label'])
async def test_kill_rechecks_scope_after_cleanup(env,tmp_path,change):
    ctx,store,_,_=env
    entered,closing,release=asyncio.Event(),asyncio.Event(),asyncio.Event()
    async def work(job):
        entered.set()
        try: await asyncio.Event().wait()
        finally:
            closing.set()
            await release.wait()
    job=ctx.jobs.start('task','owned',work,session_id='s')
    await entered.wait()
    task=asyncio.create_task(ctx.job_controller.kill('s',job.id))
    try:
        await asyncio.wait_for(closing.wait(),3)
        if change=='hidden': store._session_visible=lambda *_:False
        elif change=='moved':
            record,revision=await store.get_readonly_revision('s')
            await store.patch('s',metadata={**record.metadata,'work_root':str(tmp_path/'other')},expected_revision=revision)
        else: job.session_id='other'
        release.set()
        with pytest.raises(RuntimeError) as exc: await task
        assert exc.value.code=='job/write-uncertain' and exc.value.may_have_changed
        assert job._task.done() and job._status=='killed'
    finally:
        release.set()
        await asyncio.gather(task,return_exceptions=True)


@pytest.mark.asyncio
async def test_remote_kill_reports_uncertainty_without_returning_hidden_job(env,tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router,plugin_http_token
    ctx,store,_,_=env
    entered,closing,release=asyncio.Event(),asyncio.Event(),asyncio.Event()
    async def work(job):
        entered.set()
        try: await asyncio.Event().wait()
        finally:
            closing.set()
            await release.wait()
    job=ctx.jobs.start('task','private-job-label',work,session_id='s')
    await entered.wait()
    host,catalog,old=_host(tmp_path); configure(host); ctx._secret_store=old._secret_store
    host.backend_manager.context=ctx
    (host.get('hook-demo').root/'ops.py').write_text(
        "async def echo(request, *, context):\n    return {'job':await context.job_controller.kill('s',request.payload['body']['text'])}\n",encoding='utf8')
    catalog.unregister_owner('plugin:hook-demo'); register_plugin_operations(catalog,host)
    app=FastAPI(); app.include_router(create_plugin_http_router(lambda:host,lambda:catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        task=asyncio.create_task(client.post('/plugin-remote/hook-demo/demo/echo',json={'args':{'text':job.id}},
            headers={'x-plugin-token':plugin_http_token(host,'hook-demo')}))
        try:
            await asyncio.wait_for(closing.wait(),3)
            store._session_visible=lambda *_:False
            release.set()
            response=await task
            assert response.status_code==400 and response.json()['payload']['may_have_changed'] is True
            assert 'private-job-label' not in response.text and job._task.done()
        finally:
            release.set()
            await asyncio.gather(task,return_exceptions=True)


@pytest.mark.asyncio
async def test_repeated_cancel_joins_original_cleanup(env):
    ctx,_,_,_=env
    entered,closing,release=asyncio.Event(),asyncio.Event(),asyncio.Event()
    async def work(job):
        entered.set()
        try: await asyncio.Event().wait()
        finally:
            closing.set()
            await release.wait()
    job=ctx.jobs.start('task','owned',work,session_id='s'); await entered.wait()
    task=asyncio.create_task(ctx.job_controller.kill('s',job.id))
    try:
        await asyncio.wait_for(closing.wait(),3)
        task.cancel(); await asyncio.sleep(0); task.cancel(); await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError): await task
        assert job._task.done()
    finally:
        release.set()
        await asyncio.gather(task,return_exceptions=True)


@pytest.mark.asyncio
async def test_self_stop_preserves_explicit_pre_dispatch_error(env):
    ctx,_,_,_=env
    outcome=asyncio.Future()
    async def work(job):
        try: await ctx.job_controller.kill('s',job.id)
        except RuntimeError as error: outcome.set_result((error.code,error.may_have_changed))
    job=ctx.jobs.start('task','self',work,session_id='s')
    assert await asyncio.wait_for(outcome,3)==('job/self-stop',False)
    assert (await ctx.jobs.wait(job.id,timeout=3)).status=='completed'
