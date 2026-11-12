"""user:“第二阶段结束后 就继续开展第三阶段”+(已交付的受管终端随原会话可见性失效回收)。"""
import asyncio
import os
import sys
import pytest
from .test_plugin_working_directory import env


@pytest.mark.asyncio
@pytest.mark.skipif(os.name!='nt',reason='original managed process is Windows-only')
@pytest.mark.parametrize('change',['hidden','moved','deleted'])
async def test_delivered_terminal_reclaimed_on_session_loss(env,tmp_path,change):
    ctx, store, _, _ = env
    terminal=await ctx.terminal_controller.open('s',[sys.executable,'-c','import time;time.sleep(20)'],timeout=25)
    try:
        if change=='hidden': store._session_visible=lambda *_:False
        elif change=='moved':
            record,revision=await store.get_readonly_revision('s')
            await store.patch('s',metadata={**record.metadata,'work_root':str(tmp_path/'other')},expected_revision=revision)
        else:
            assert await store.delete('s')
        await asyncio.wait_for(asyncio.shield(terminal._process._task),4)
        assert terminal._process._cleaned
    finally:
        await terminal.close()


@pytest.mark.asyncio
@pytest.mark.skipif(os.name!='nt',reason='original managed process is Windows-only')
async def test_scope_dispose_joins_process_and_watcher(env):
    ctx, _, _, _ = env
    scope=ctx._registration_scope
    terminal=await ctx.terminal_controller.open('s',[sys.executable,'-c','import time;time.sleep(20)'],timeout=25)
    watchers=tuple(scope._session_terminal_watchers)
    assert len(watchers)==1
    await asyncio.wait_for(scope.dispose(),4)
    assert terminal._process._cleaned and all(task.done() for task in watchers)
    assert not scope._session_terminal_watchers


@pytest.mark.asyncio
@pytest.mark.skipif(os.name!='nt',reason='original managed process is Windows-only')
async def test_dispose_waits_for_inflight_session_check_before_cleanup(env,monkeypatch):
    ctx, store, _, _ = env
    terminal=await ctx.terminal_controller.open('s',[sys.executable,'-c','import time;time.sleep(20)'],timeout=25)
    original=store.get_readonly_revision
    entered,release=asyncio.Event(),asyncio.Event()
    async def gated(sid):
        result=await original(sid)
        entered.set()
        await release.wait()
        return result
    monkeypatch.setattr(store,'get_readonly_revision',gated)
    task=None
    try:
        await asyncio.wait_for(entered.wait(),3)
        task=asyncio.create_task(ctx._registration_scope.dispose())
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        await asyncio.wait_for(task,4)
        assert terminal._process._cleaned and not ctx._registration_scope._session_terminal_watchers
    finally:
        release.set()
        if task is not None: await asyncio.gather(task,return_exceptions=True)
        await terminal.close()


@pytest.mark.asyncio
@pytest.mark.skipif(os.name!='nt',reason='original managed process is Windows-only')
async def test_directory_change_does_not_retarget_existing_process(env):
    ctx, _, _, _ = env
    terminal=await ctx.terminal_controller.open('s',[sys.executable,'-c','import time;time.sleep(20)'],timeout=25)
    try:
        directory=await ctx.working_directory.get('s')
        await ctx.working_directory.set('s','one',expected_revision=directory.revision)
        await asyncio.sleep(.5)
        assert not terminal._process._task.done()
    finally:
        await terminal.close()


@pytest.mark.asyncio
@pytest.mark.skipif(os.name!='nt',reason='original managed process is Windows-only')
async def test_natural_exit_releases_monitor(env):
    ctx, _, _, _ = env
    terminal=await ctx.terminal_controller.open('s',[sys.executable,'-c','print(123)'],timeout=10)
    try:
        assert (await terminal.wait()).exit_code==0
        for _ in range(30):
            if not getattr(ctx._registration_scope,'_session_terminal_watchers',None): break
            await asyncio.sleep(.05)
        assert not ctx._registration_scope._session_terminal_watchers
    finally:
        await terminal.close()
