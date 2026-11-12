"""user:“建立真实请求、错误、作用域、取消/流和清理验收”+(事件观察取消等待原来源实际清理)。"""
import asyncio
import pytest
from .test_plugin_working_directory import env

@pytest.mark.asyncio
async def test_event_observer_repeated_cancel_awaits_source_cleanup(env,monkeypatch):
    ctx,_,_,_=env; api=ctx.session_controller; entered=asyncio.Event(); cleaning=asyncio.Event(); release=asyncio.Event(); cleaned=asyncio.Event()
    async def source(*args,**kwargs):
        try:
            entered.set(); await asyncio.Event().wait()
            yield {}
        finally:
            cleaning.set(); await release.wait(); cleaned.set()
    monkeypatch.setattr(api,'follow',source)
    stream=api.observe_events('s',interval=.01); await anext(stream)
    task=asyncio.create_task(anext(stream))
    try:
        await asyncio.wait_for(entered.wait(),3); task.cancel(); await asyncio.wait_for(cleaning.wait(),3)
        task.cancel(); await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError): await task
        assert cleaned.is_set()
    finally:
        release.set(); await asyncio.gather(task,return_exceptions=True); await stream.aclose()

@pytest.mark.asyncio
async def test_real_event_observer_still_yields_and_cleans(env):
    ctx,_,_,_=env; api=ctx.session_controller; stream=api.observe_events('s',interval=.01)
    try:
        ready=await anext(stream); receipt=await api.prompt('s',request_id='owned-pull',text='hello')
        async with asyncio.timeout(3):
            while True:
                frame=await anext(stream)
                if frame['event']['seq']==receipt.event_seq: break
        assert frame['event']['seq']>ready['after_seq']
    finally: await stream.aclose()
    assert ctx._registration_scope._idle.is_set()
