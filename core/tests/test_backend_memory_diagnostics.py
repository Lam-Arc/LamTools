"""user:“而且刚才为什么内存占用这么多，差不多 14g？”+(保存进程内存证据，日志不包含会话内容)。"""
import asyncio
import logging

import pytest

from lamtools_core.runtime import memory_diagnostics as diagnostics


def test_native_process_memory_reports_current_and_peak():
    sample = diagnostics.process_memory_sample()
    assert sample is not None
    assert sample["rss_bytes"] > 0
    assert sample["peak_rss_bytes"] >= sample["rss_bytes"]


@pytest.mark.asyncio
async def test_memory_log_is_rate_limited_but_reports_growth_and_coroutine_types(monkeypatch, caplog):
    memory = {"rss_bytes": 200_000_000, "private_bytes": 250_000_000, "peak_rss_bytes": 210_000_000}
    monkeypatch.setattr(diagnostics, "process_memory_sample", lambda: dict(memory))
    now = [0.0]
    monkeypatch.setattr(diagnostics.time, "monotonic", lambda: now[0])
    monitor = diagnostics.BackendMemoryDiagnostics()
    with caplog.at_level(logging.INFO, logger=diagnostics.__name__):
        monitor.sample()
        assert len(caplog.records) == 1
        for _ in range(10):
            monitor.sample()
        assert len(caplog.records) == 1
        now[0] = 5
        memory["private_bytes"] += 512 * 1024 * 1024
        monitor.sample()
        assert len(caplog.records) == 2
        assert "private_bytes" in caplog.text and "coroutines" in caplog.text
        assert "peak_rss_bytes" in caplog.text
        now[0] = 70
        monitor.sample()
        assert len(caplog.records) == 3


@pytest.mark.asyncio
async def test_cancel_control_uses_metadata_without_loading_conversation(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from lamtools_core.app.live import turn_cancel

    snapshot = {"core": {"turns": {"turn": {"status": "interrupting"}}}}
    metadata = AsyncMock(return_value=snapshot)
    full = AsyncMock(side_effect=AssertionError("control must not load the transcript"))

    async def write(action):
        return await action(None)

    context = SimpleNamespace(persistence=SimpleNamespace(load=full, load_metadata=metadata, write=write))
    assert await turn_cancel._append_interrupting_record(context=context, thread_id="thread",
        requested_turn_id="turn", expected_revision=None, live_turn_id="execution") == "turn"
    full.assert_not_awaited()


@pytest.mark.asyncio
async def test_terminal_control_uses_metadata_without_loading_conversation(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from lamtools_core.app.live import terminal_state, events

    snapshot = {"core": {"turns": {"turn": {"status": "running", "run_id": "execution"}}}}
    metadata = AsyncMock(return_value=snapshot)
    full = AsyncMock(side_effect=AssertionError("terminal control must not load transcript"))

    async def write(action):
        return await action(None)

    event = object()
    append = AsyncMock(return_value=event)
    monkeypatch.setattr(events, "_append_run_item", append)
    context = SimpleNamespace(runtime_state_store=None,
        persistence=SimpleNamespace(load=full, load_metadata=metadata, write=write),
        hub=SimpleNamespace(publish=AsyncMock()))
    assert await terminal_state._persist_cancelled_terminal(context=context,
        thread_id="thread", turn_id="turn") is event
    full.assert_not_awaited()
