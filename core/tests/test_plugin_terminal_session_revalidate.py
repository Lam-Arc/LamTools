"""user:“完成真实接口、参数/错误、作用域、取消/清理”+(启动后会话失效时先回收真实终端)。"""
import asyncio
import os
import sys
import pytest
from .test_plugin_working_directory import env


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != 'nt', reason='original managed process is Windows-only')
@pytest.mark.parametrize('change', ['hidden', 'directory'])
async def test_session_change_after_real_spawn_joins_process(env, monkeypatch, change):
    from lamtools_core.plugin_system.terminal_access import PluginTerminalsAPI
    ctx, store, _, _ = env
    original = PluginTerminalsAPI.open
    entered, release, created = asyncio.Event(), asyncio.Event(), []
    async def gated(self, *args, **kwargs):
        terminal = await original(self, *args, **kwargs)
        created.append(terminal)
        entered.set()
        await release.wait()
        return terminal
    monkeypatch.setattr(PluginTerminalsAPI, 'open', gated)
    task = asyncio.create_task(ctx.terminal_controller.open('s', [sys.executable, '-c', 'import time;time.sleep(20)'], timeout=25))
    try:
        await asyncio.wait_for(entered.wait(), 4)
        if change == 'hidden':
            store._session_visible = lambda sid, _: sid != 's'
        else:
            state = await ctx.working_directory.get('s')
            await ctx.working_directory.set('s', 'one', expected_revision=state.revision)
        release.set()
        with pytest.raises((ValueError, RuntimeError)): await task
        assert created[0]._process._cleaned
    finally:
        release.set()
        result = await asyncio.gather(task, return_exceptions=True)
        if created and not created[0]._process._cleaned: await created[0].close()


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != 'nt', reason='original managed process is Windows-only')
async def test_unchanged_session_returns_real_process(env):
    ctx, _, _, _ = env
    terminal = await ctx.terminal_controller.open('s', [sys.executable, '-c', 'print(123)'], timeout=10)
    try:
        result = await terminal.wait()
        assert result.exit_code == 0
    finally:
        await terminal.close()


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != 'nt', reason='original managed process is Windows-only')
async def test_repeated_cancel_in_final_admission_waits_for_real_close(env, monkeypatch):
    from lamtools_core.plugin_system.terminal_access import PluginTerminalsAPI, PluginTerminal
    ctx, store, _, _ = env
    read_original, open_original, close_original = store.get_readonly_revision, PluginTerminalsAPI.open, PluginTerminal.close
    checking, close_started, release_close = asyncio.Event(), asyncio.Event(), asyncio.Event()
    count, created = 0, []
    async def gated_read(sid):
        nonlocal count
        count += 1
        if count == 2:
            checking.set()
            await asyncio.Event().wait()
        return await read_original(sid)
    async def observe_open(self, *args, **kwargs):
        terminal = await open_original(self, *args, **kwargs)
        created.append(terminal)
        return terminal
    async def gated_close(self):
        close_started.set()
        await release_close.wait()
        return await close_original(self)
    monkeypatch.setattr(store, 'get_readonly_revision', gated_read)
    monkeypatch.setattr(PluginTerminalsAPI, 'open', observe_open)
    monkeypatch.setattr(PluginTerminal, 'close', gated_close)
    task = asyncio.create_task(ctx.terminal_controller.open('s', [sys.executable, '-c', 'import time;time.sleep(20)'], timeout=25))
    try:
        await asyncio.wait_for(checking.wait(), 4)
        task.cancel()
        await asyncio.wait_for(close_started.wait(), 3)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release_close.set()
        with pytest.raises(asyncio.CancelledError): await asyncio.wait_for(task, 4)
        assert created[0]._process._cleaned
    finally:
        release_close.set()
        await asyncio.gather(task, return_exceptions=True)
        if created and not created[0]._process._cleaned: await close_original(created[0])
