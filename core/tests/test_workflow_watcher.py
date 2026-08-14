"""Tests for the workflow file watcher (poll + broadcast on change)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from lamtools_core.runtime.workflow_watcher import WorkflowFileWatcher


class FakeHub:
    def __init__(self) -> None:
        self.broadcasts: list[dict[str, Any]] = []

    async def broadcast(self, event: dict[str, Any]) -> None:
        self.broadcasts.append(event)


class FakeStore:
    """Signatures returned from a mutable dict; count access for determinism."""

    def __init__(self, sigs: dict[str, Any]) -> None:
        self.sigs = sigs
        self.accesses = 0

    def _signature(self, work_root: str | None) -> Any:
        self.accesses += 1
        return self.sigs.get(work_root or "")


@pytest.mark.asyncio
async def test_broadcasts_on_signature_change():
    store = FakeStore({"": "sig-1"})
    hub = FakeHub()
    watcher = WorkflowFileWatcher(store, hub, poll_interval=0.1)
    await watcher.start()
    try:
        # First poll only records the baseline (no broadcast).
        watcher.wake()
        await asyncio.sleep(0.15)
        assert hub.broadcasts == []

        store.sigs[""] = "sig-2"
        watcher.wake()
        await asyncio.sleep(0.15)
        assert len(hub.broadcasts) == 1
        assert hub.broadcasts[0]["method"] == "workflow/changed"
        assert hub.broadcasts[0]["payload"]["work_root"] == ""

        # Same signature again → no repeat broadcast.
        watcher.wake()
        await asyncio.sleep(0.15)
        assert len(hub.broadcasts) == 1
    finally:
        await watcher.stop()


@pytest.mark.asyncio
async def test_watches_project_roots_and_broadcasts_per_root():
    store = FakeStore({"proj-a": "a-1", "proj-b": "b-1"})
    hub = FakeHub()
    watcher = WorkflowFileWatcher(store, hub, poll_interval=0.1, work_roots=["proj-a", "proj-b"])
    await watcher.start()
    try:
        watcher.wake()
        await asyncio.sleep(0.15)
        assert hub.broadcasts == []

        store.sigs["proj-b"] = "b-2"
        watcher.wake()
        await asyncio.sleep(0.15)
        assert [b["payload"]["work_root"] for b in hub.broadcasts] == ["proj-b"]
    finally:
        await watcher.stop()


@pytest.mark.asyncio
async def test_add_work_root_mid_run():
    store = FakeStore({"": "s-1", "late": "l-1"})
    hub = FakeHub()
    watcher = WorkflowFileWatcher(store, hub, poll_interval=0.1)
    await watcher.start()
    try:
        watcher.wake()
        await asyncio.sleep(0.15)
        # Adding a root switches the watch list to the explicit roots — the
        # baseline for the new root is recorded without a broadcast.
        watcher.add_work_root("late")
        await asyncio.sleep(0.15)
        assert "late" in watcher._work_roots
        assert hub.broadcasts == []

        store.sigs["late"] = "l-2"
        watcher.wake()
        await asyncio.sleep(0.15)
        assert [b["payload"]["work_root"] for b in hub.broadcasts] == ["late"]
    finally:
        await watcher.stop()


@pytest.mark.asyncio
async def test_stop_terminates_poll_loop():
    store = FakeStore({"": "s-1"})
    hub = FakeHub()
    watcher = WorkflowFileWatcher(store, hub, poll_interval=0.05)
    await watcher.start()
    before = store.accesses
    await asyncio.sleep(0.15)
    assert store.accesses > before
    await watcher.stop()
    after_stop = store.accesses
    await asyncio.sleep(0.15)
    assert store.accesses == after_stop
