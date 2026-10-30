"""user:“给我把 2 阶段做完，前端除外”+(交互管道终端要能多次输入、读取并在取消或停用后回收，不冒充PTY)。"""
import asyncio
import os
import sys

import pytest

from lamtools_core.plugin_system import PluginContext


pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(os.name != "nt", reason="Windows Job owner")]


async def test_terminal_has_persistent_stdin_output_and_close_joins_owner(tmp_path):
    ctx = PluginContext(tmp_path)
    ctx._begin_registration_scope("terminal", 1)
    terminal = await ctx.terminals.open([sys.executable, "-u", "-c", "import sys\nfor line in sys.stdin:\n print('echo:'+line.strip(),flush=True)"], timeout=20)
    assert terminal.pty is False
    for message in ("first", "second"):
        await terminal.send((message + "\n").encode(), timeout=2)
        async with asyncio.timeout(3):
            while message.encode() not in terminal.read().stdout:
                await asyncio.sleep(0.01)
    outcome = await terminal.close()
    assert outcome.quiescent
    await ctx._registration_scope.dispose()


async def test_blocked_stdin_timeout_reclaims_process_before_returning(tmp_path):
    from lamtools_core.plugin_system.process_access import ProcessAccessError
    ctx = PluginContext(tmp_path)
    ctx._begin_registration_scope("terminal", 1)
    terminal = await ctx.terminals.open([sys.executable, "-c", "import time;time.sleep(20)"], timeout=25)
    with pytest.raises(ProcessAccessError) as error:
        await terminal.send(b"x" * 16384, timeout=0.1)
    assert error.value.code == "process/stdin-timeout"
    assert terminal._process._cleaned
    await ctx._registration_scope.dispose()


async def test_unload_closes_terminal_and_old_handle_cannot_write(tmp_path):
    ctx = PluginContext(tmp_path)
    ctx._begin_registration_scope("terminal", 1)
    terminal = await ctx.terminals.open([sys.executable, "-c", "import sys;sys.stdin.read()"], timeout=20)
    await ctx._registration_scope.dispose()
    assert terminal._process._cleaned
    with pytest.raises(Exception):
        await terminal.send(b"late", timeout=1)
