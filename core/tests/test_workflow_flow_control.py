from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from lamtools_core.plugins.bundled.workflow.backend.document import canonicalize_document
from lamtools_core.plugins.bundled.workflow.backend.flow_control import (
    FlowControlError,
    FlowControlStore,
    canonicalize_flow_control,
    stable_scope_key,
)
from lamtools_core.plugins.bundled.workflow.backend.queue import WorkflowQueueItem, WorkflowQueueStore, WorkflowRunQueue
from lamtools_core.plugins.bundled.workflow.backend.runtime import WorkflowDef, WorkflowRunResult


def test_flow_control_policy_is_strict_and_canonical() -> None:
    value = canonicalize_flow_control(
        {
            "concurrency": {"key": "provider", "max": 2.0},
            "rateLimit": {"count": 3, "windowSeconds": 10},
            "throttle": {"minIntervalSeconds": 0.5},
            "debounce": {"windowSeconds": 2, "mode": "last"},
            "priority": -4,
        }
    )
    assert value == {
        "concurrency": {"key": "provider", "max": 2},
        "rate_limit": {"count": 3, "window_seconds": 10.0},
        "throttle": {"min_interval_seconds": 0.5},
        "debounce": {"window_seconds": 2.0, "mode": "trailing"},
        "priority": -4,
    }
    with pytest.raises(FlowControlError):
        canonicalize_flow_control({"rate_limit": {"count": 1, "window_seconds": 0}})
    with pytest.raises(FlowControlError):
        canonicalize_flow_control({"debounce": {"window_seconds": 1}})
    with pytest.raises(FlowControlError):
        canonicalize_flow_control({"concurrency": {"key": "x", "max": 1}, "unknown": True})


def test_document_policy_canonicalization_keeps_legacy_extensions() -> None:
    value = {
        "format": "lamtools.workflow",
        "version": 2,
        "resource": {"name": "flow"},
        "graph": {"nodes": [], "links": []},
        "interface": {},
        "exposure": {},
        "canvas": {},
        "policies": {
            "timeout_seconds": 5,
            "concurrency": {"key": "global", "max": 1},
        },
    }
    normalized = canonicalize_document(value)
    assert normalized["policies"] == {
        "timeout_seconds": 5,
        "concurrency": {"key": "global", "max": 1},
    }


@pytest.mark.asyncio
async def test_flow_control_store_atomic_concurrency_and_expiry(tmp_path: Path) -> None:
    path = tmp_path / "flow.sqlite3"
    policy = {"concurrency": {"key": "worker", "max": 1}}
    first, second = await asyncio.gather(
        FlowControlStore(path, lease_seconds=10).acquire(policy, scope_key="project", lease_id="one", owner_id="a", now=100),
        FlowControlStore(path, lease_seconds=10).acquire(policy, scope_key="project", lease_id="two", owner_id="b", now=100),
    )
    assert sorted([first.acquired, second.acquired]) == [False, True]
    winner = first if first.acquired else second
    loser = second if first.acquired else first
    assert loser.reason == "concurrency" and loser.retry_at == 110
    assert await FlowControlStore(path, lease_seconds=10).release(winner.lease, now=100) is True
    after = await FlowControlStore(path, lease_seconds=10).acquire(policy, scope_key="project", lease_id="three", owner_id="c", now=100)
    assert after.acquired


@pytest.mark.asyncio
async def test_rate_throttle_debounce_and_stale_fencing(tmp_path: Path) -> None:
    path = tmp_path / "flow.sqlite3"
    rate = {"rate_limit": {"count": 1, "window_seconds": 5}}
    store = FlowControlStore(path, lease_seconds=1)
    first = await store.acquire(rate, scope_key="s", lease_id="same", owner_id="owner", now=10)
    assert first.acquired
    assert (await store.check(rate, scope_key="s", now=11)).reason == "rate_limit"
    second = await store.acquire(rate, scope_key="s", lease_id="next", owner_id="owner", now=15)
    assert second.acquired

    # Reusing an expired lease id receives a new fencing token; an old lease
    # object must not be able to release the replacement.
    expired = await store.acquire({"concurrency": {"key": "x", "max": 1}}, scope_key="f", lease_id="reuse", owner_id="same", now=20)
    replacement = await store.acquire({"concurrency": {"key": "x", "max": 1}}, scope_key="f", lease_id="reuse", owner_id="same", now=22)
    assert expired.lease is not None and replacement.lease is not None
    assert replacement.lease.fencing_token > expired.lease.fencing_token
    assert await store.release(expired.lease, now=22) is False
    assert await store.release(replacement.lease, now=22) is True

    debounce = {"debounce": {"window_seconds": 2, "mode": "leading"}}
    assert (await store.acquire(debounce, scope_key="d", lease_id="d1", now=30)).acquired
    blocked = await store.acquire(debounce, scope_key="d", lease_id="d2", now=31)
    assert blocked.reason == "debounce" and blocked.reserved
    assert (await store.acquire(debounce, scope_key="d", lease_id="d3", now=32)).acquired


def test_stable_scope_key_is_order_independent() -> None:
    assert stable_scope_key({"b": 2, "a": 1}) == stable_scope_key({"a": 1, "b": 2})
    assert stable_scope_key("project") != stable_scope_key("other")


@pytest.mark.asyncio
async def test_queue_priority_persists_and_legacy_json_migrates(tmp_path: Path) -> None:
    path = tmp_path / "queue.json"
    old = {"version": 2, "items": [{"id": "legacy", "name": "old", "status": "queued"}]}
    path.write_text(json.dumps(old), encoding="utf-8")
    queue = WorkflowRunQueue(store=WorkflowQueueStore(path=path), auto_start=False)
    legacy = await queue.get("legacy")
    assert legacy is not None and legacy.priority == 0
    low = await queue.enqueue(WorkflowDef(name="low"), priority=-1, auto_start=False)
    high = await queue.enqueue(WorkflowDef(name="high"), priority=5, auto_start=False)
    assert [item.queue_id for item in await queue.list(status="queued")] == [high.queue_id, "legacy", low.queue_id]
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert all("priority" in item for item in payload["items"])


@pytest.mark.asyncio
async def test_queue_start_keeps_durable_wait_paused(tmp_path: Path) -> None:
    item = WorkflowQueueItem(
        queue_id="wait",
        workflow_name="waiting",
        result=WorkflowRunResult(status="paused", wait_descriptor={"kind": "signal", "token": "x"}),
        status="paused",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    store = WorkflowQueueStore(path=tmp_path / "queue.json")
    await store.save(item)
    queue = WorkflowRunQueue(store=store, auto_start=False)
    await queue.start()
    try:
        current = await queue.get("wait")
        assert current is not None and current.status == "paused"
    finally:
        await queue.stop()
