"""user:“继续，把 2 阶段都做完”+(文件监听须有实际变化、显式近似语义和停用清理，不能返回空监听句柄)。"""
import asyncio

import pytest

from lamtools_core.plugin_system import PluginContext, FilesystemError


@pytest.mark.asyncio
async def test_polling_watch_reports_create_change_delete_and_closes(tmp_path):
    ctx = PluginContext(tmp_path)
    ctx._begin_registration_scope("example", 1)
    received = asyncio.Queue()
    watch = await ctx.filesystem.watch("file", received.put_nowait, interval=0.01)
    try:
        (tmp_path / "file").write_text("first")
        assert (await asyncio.wait_for(received.get(), 3)).kind == "created"
        (tmp_path / "file").write_text("longer changed")
        assert (await asyncio.wait_for(received.get(), 3)).kind == "changed"
        (tmp_path / "file").unlink()
        assert (await asyncio.wait_for(received.get(), 3)).kind == "deleted"
        await watch.aclose()
        assert (await watch.wait()).changes == 3
    finally:
        await ctx._registration_scope.dispose()


@pytest.mark.asyncio
async def test_directory_direct_entry_watch_and_scope_disposal_are_real(tmp_path):
    ctx = PluginContext(tmp_path)
    ctx._begin_registration_scope("example", 1)
    changed = asyncio.Event()
    watch = await ctx.filesystem.watch(".", lambda event: changed.set(), interval=0.01)
    (tmp_path / "entry").write_text("x")
    await asyncio.wait_for(changed.wait(), 3)
    waiting = asyncio.create_task(watch.wait())
    await asyncio.sleep(0)
    await ctx._registration_scope.dispose()
    assert (await waiting).reason == "closed"


@pytest.mark.asyncio
async def test_callback_failure_stops_watch_and_reports_error(tmp_path):
    ctx = PluginContext(tmp_path)
    ctx._begin_registration_scope("example", 1)
    def broken(event):
        raise RuntimeError("callback failure")
    try:
        watch = await ctx.filesystem.watch("file", broken, interval=0.01)
        (tmp_path / "file").write_text("x")
        with pytest.raises(FilesystemError) as error:
            await asyncio.wait_for(watch.wait(), 3)
        assert error.value.code == "fs/watch-callback-failed"
    finally:
        await ctx._registration_scope.dispose()


@pytest.mark.asyncio
async def test_callback_can_close_its_own_watch_without_deadlock(tmp_path):
    # user:“继续，把 2 阶段都做完”+(回调关闭自身不能等待自身任务)。
    ctx = PluginContext(tmp_path)
    ctx._begin_registration_scope("example", 1)
    async def changed(event):
        await watch.aclose()
    try:
        watch = await ctx.filesystem.watch("file", changed, interval=0.01)
        (tmp_path / "file").write_text("x")
        assert (await asyncio.wait_for(watch.wait(), 3)).changes == 1
    finally:
        await ctx._registration_scope.dispose()
