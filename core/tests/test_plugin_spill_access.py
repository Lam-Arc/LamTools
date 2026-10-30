"""user:“继续，把 2 阶段都做完”+(长文本必须真实落盘、精确字节数、不把失败伪装为定位信息)。"""
from pathlib import Path

import pytest

from lamtools_core.plugin_system import PluginContext
from lamtools_core.plugin_system.services import ServiceError


@pytest.mark.asyncio
async def test_spill_persists_exact_utf8_and_safe_owner_grouped_locator(tmp_path):
    ctx = PluginContext(tmp_path, data_dir=tmp_path / "data")
    ctx._begin_registration_scope("example", 1)
    api = ctx.spill_store
    text = "中文\r\n" * 10000
    result = await api.save_text(text, session_id="../session", suggested_name="../../bad.txt",
                                 source={"kind": "tool", "tool_name": "fetch", "call_id": "call", "label": "result"})
    location = Path(result.locator)
    assert location.is_relative_to(tmp_path / "data")
    assert result.bytes == len(text.encode("utf-8"))
    assert location.read_bytes() == text.encode("utf-8")
    assert result.retrieval_hint and location.name.endswith("bad.txt")
    await ctx._registration_scope.dispose()
    assert location.exists()
    with pytest.raises(ServiceError):
        await api.save_text("old", session_id="s")


@pytest.mark.asyncio
async def test_spill_bad_content_and_publication_failure_are_explicit(tmp_path, monkeypatch):
    from lamtools_core.plugin_system.spill_access import SpillAccessError
    ctx = PluginContext(tmp_path, data_dir=tmp_path / "data")
    ctx._begin_registration_scope("example", 1)
    try:
        with pytest.raises(SpillAccessError):
            await ctx.spill_store.save_text("\ud800", session_id="s")
        with pytest.raises(SpillAccessError):
            await ctx.spill_store.save_text("x" * (8 * 1024 * 1024 + 1), session_id="s")
        def broken(path, content):
            raise OSError("private path and credentials")
        monkeypatch.setattr("lamtools_core.plugin_system.spill_access.atomic_write_bytes", broken)
        with pytest.raises(SpillAccessError) as error:
            await ctx.spill_store.save_text("text", session_id="s")
        assert error.value.code == "spill/write-failed"
        assert "credentials" not in str(error.value)
    finally:
        await ctx._registration_scope.dispose()


@pytest.mark.asyncio
async def test_spill_cancellation_joins_publication_before_return(tmp_path, monkeypatch):
    import asyncio
    import threading
    from lamtools_core.plugin_system import spill_access
    entered, release = threading.Event(), threading.Event()
    original = spill_access.atomic_write_bytes
    def delayed(path, content):
        entered.set()
        assert release.wait(3)
        original(path, content)
    monkeypatch.setattr(spill_access, "atomic_write_bytes", delayed)
    ctx = PluginContext(tmp_path, data_dir=tmp_path / "data")
    ctx._begin_registration_scope("example", 1)
    task = asyncio.create_task(ctx.spill_store.save_text("saved", session_id="s"))
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        files = list((tmp_path / "data").rglob("*.txt"))
        assert len(files) == 1 and files[0].read_bytes() == b"saved"
    finally:
        release.set()
        await ctx._registration_scope.dispose()
