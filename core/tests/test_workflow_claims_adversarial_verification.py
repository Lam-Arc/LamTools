"""Adversarial acceptance checks for Phase 2 durable workflow claims.

These checks intentionally exercise independent runner/process state.  They
are verification fixtures only; the production claim/runtime implementation is
not modified here.
"""

from __future__ import annotations

import asyncio
import json
import multiprocessing
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from lamtools_core.plugins.bundled.workflow.backend.claims import (
    ClaimAcquireResult,
    WorkflowClaimLease,
    WorkflowClaimStore,
)
from lamtools_core.plugins.bundled.workflow.backend.credentials import CredentialRef
from lamtools_core.plugins.bundled.workflow.backend.durable import WorkflowRunEvent, WorkflowRunEventStore
from lamtools_core.plugins.bundled.workflow.backend.registry import WorkflowNodeRegistry
from lamtools_core.plugins.bundled.workflow.backend.runtime import (
    WorkflowDef,
    WorkflowEdge,
    WorkflowNode,
    WorkflowPort,
    WorkflowRunner,
)
from lamtools_core.plugins.bundled.workflow.backend.snapshots import WorkflowSnapshotStore


def _wait_workflow(*, workflow_id: str = "signal-claims", revision: int = 1) -> WorkflowDef:
    fixed_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return WorkflowDef(
        id=workflow_id,
        name=workflow_id,
        revision=revision,
        nodes=[
            WorkflowNode(
                id="wait",
                kind="wait_event",
                config={"event_type": "go"},
                ports=[WorkflowPort(name="result", direction="out", type="object")],
            ),
            WorkflowNode(
                id="side",
                kind="agent",
                config={"instruction": "side effect"},
                ports=[
                    WorkflowPort(name="result", direction="in", type="object"),
                    WorkflowPort(name="answer", direction="out"),
                ],
            ),
        ],
        edges=[WorkflowEdge(
            id="wait-side",
            source="wait",
            source_port="result",
            target="side",
            target_port="result",
        )],
        output_port="side.answer",
        created_at=fixed_time,
        updated_at=fixed_time,
    )


def _simple_workflow(*, workflow_id: str = "run-claims", revision: int = 1, instruction: str = "once") -> WorkflowDef:
    fixed_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return WorkflowDef(
        id=workflow_id,
        name=workflow_id,
        revision=revision,
        nodes=[WorkflowNode(
            id="side",
            kind="agent",
            config={"instruction": instruction},
            ports=[WorkflowPort(name="answer", direction="out")],
        )],
        output_port="side.answer",
        created_at=fixed_time,
        updated_at=fixed_time,
    )


class _Agent:
    async def run(self, **kwargs):
        return SimpleNamespace(message='{"answer":"once"}')


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("resume_token", "event_type"),
    [("wrong-token", "go"), ("", "wrong-event")],
)
async def test_completed_signal_claim_does_not_bypass_input_validation(
    tmp_path: Path, resume_token: str, event_type: str,
) -> None:
    """A completed claim is not authorization for a different signal."""
    events = WorkflowRunEventStore(root=tmp_path)
    snapshots = WorkflowSnapshotStore(root=tmp_path)
    workflow = _wait_workflow()
    first = WorkflowRunner(sub_agent_runner=_Agent(), event_store=events, snapshot_store=snapshots)
    paused = await first.run(workflow, thread_id="thread", run_id="run")
    assert paused.status == "paused"
    valid_token = str(paused.wait_descriptor["resume_token"])
    completed = await first.signal(
        thread_id="thread", run_id="run", resume_token=valid_token,
        event_type="go", payload={"source": "valid"},
    )
    assert completed.status == "completed"

    second = WorkflowRunner(sub_agent_runner=_Agent(), event_store=events, snapshot_store=snapshots)
    with pytest.raises(ValueError):
        await second.signal(
            thread_id="thread", run_id="run",
            resume_token=resume_token or valid_token,
            event_type=event_type,
            payload={"source": "invalid"},
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["workflow_id", "revision", "digest"])
async def test_completed_run_claim_does_not_bypass_workflow_identity(
    tmp_path: Path, variant: str,
) -> None:
    """A terminal run result belongs only to its pinned workflow definition."""
    events = WorkflowRunEventStore(root=tmp_path)
    workflow = _simple_workflow()
    first = WorkflowRunner(sub_agent_runner=_Agent(), event_store=events)
    completed = await first.run(workflow, thread_id="thread", run_id="run")
    assert completed.status == "completed"

    if variant == "workflow_id":
        changed = _simple_workflow(workflow_id="other-workflow")
    elif variant == "revision":
        changed = _simple_workflow(revision=2)
    else:
        changed = _simple_workflow(instruction="different-effect")

    second = WorkflowRunner(sub_agent_runner=_Agent(), event_store=events)
    result = await second.run(changed, thread_id="thread", run_id="run")
    assert result.status == "failed"
    assert "changed" in result.error


@pytest.mark.asyncio
async def test_stale_fencing_token_cannot_renew_complete_or_release(tmp_path: Path) -> None:
    path = tmp_path / "claims.sqlite3"
    store = WorkflowClaimStore(path, namespace="test", lease_seconds=1)
    first = await store.acquire("run", "thread", "run", owner_id="first")
    assert first.lease is not None
    time.sleep(1.1)
    second = await store.acquire("run", "thread", "run", owner_id="second")
    assert second.lease is not None
    assert second.lease.fencing_token > first.lease.fencing_token
    assert await store.renew(first.lease) is None
    assert await store.complete(first.lease, {"answer": "stale"}) is False
    assert await store.release(first.lease) is False
    assert await store.count() == 1


@pytest.mark.asyncio
async def test_completed_claim_cleanup_is_bounded(tmp_path: Path) -> None:
    store = WorkflowClaimStore(tmp_path / "claims.sqlite3", namespace="test", max_completed_claims=16)
    for index in range(24):
        acquired = await store.acquire("run", f"thread-{index}", f"run-{index}")
        assert acquired.lease is not None
        assert await store.complete(acquired.lease, {"index": index}) is True
    assert await store.count() <= 16


@pytest.mark.asyncio
async def test_runtime_fails_closed_when_heartbeat_fence_is_lost(tmp_path: Path) -> None:
    lease = WorkflowClaimLease(
        namespace="test",
        kind="run",
        thread_id="thread",
        run_id="run",
        owner_id="owner",
        fencing_token=1,
        lease_expires_at=time.time() + 1,
    )

    class LostFenceStore:
        lease_seconds = 1

        async def acquire(self, kind, thread_id, run_id):
            return ClaimAcquireResult("acquired", lease=lease)

        async def renew(self, current):
            return None

        async def release(self, current):
            return False

        async def complete(self, current, result):
            return False

    class BlockingAgent:
        async def run(self, **kwargs):
            await asyncio.Event().wait()

    workflow = _simple_workflow()
    with pytest.raises(RuntimeError, match="lease was lost"):
        await WorkflowRunner(
            sub_agent_runner=BlockingAgent(),
            event_store=WorkflowRunEventStore(root=tmp_path),
            claim_store=LostFenceStore(),
        ).run(workflow, thread_id="thread", run_id="run")


class _BarrierEventStore(WorkflowRunEventStore):
    def __init__(self, *args, barrier, **kwargs):
        super().__init__(*args, **kwargs)
        self._barrier = barrier
        self._waited = False

    def _read_sync(self, run_id: str):
        events = super()._read_sync(run_id)
        if run_id == "cross-process" and not self._waited:
            self._waited = True
            self._barrier.wait(timeout=15)
        return events


def _append_event_worker(root: str, barrier, index: int, output) -> None:
    async def _main() -> None:
        store = _BarrierEventStore(root=root, barrier=barrier)
        event = WorkflowRunEvent(
            event_id=f"event-{index}",
            run_id="cross-process",
            kind="attempt.started",
            payload={"index": index},
        )
        appended = await store.append(event)
        output.put((appended.event_id, appended.sequence))

    asyncio.run(_main())


def test_cross_process_jsonl_append_preserves_unique_sequence_numbers(tmp_path: Path) -> None:
    """Concurrent writers must not produce duplicate event sequence values."""
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(4)
    output = context.Queue()
    processes = [
        context.Process(target=_append_event_worker, args=(str(tmp_path), barrier, index, output))
        for index in range(4)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=20)
        assert process.exitcode == 0

    observed = [output.get(timeout=2) for _ in processes]
    assert {event_id for event_id, _ in observed} == {f"event-{index}" for index in range(4)}
    path = WorkflowRunEventStore(root=tmp_path).event_path("cross-process")
    lines = path.read_text(encoding="utf-8").splitlines()
    parsed = [json.loads(line) for line in lines]
    assert len(parsed) == 4
    assert {item["event_id"] for item in parsed} == {f"event-{index}" for index in range(4)}
    assert sorted(item["sequence"] for item in parsed) == [1, 2, 3, 4]
    assert len({item["sequence"] for item in parsed}) == 4


@pytest.mark.asyncio
async def test_claim_storage_does_not_persist_runtime_secret(tmp_path: Path) -> None:
    """The result cached by a claim must follow the runtime redaction boundary."""
    events = WorkflowRunEventStore(root=tmp_path)
    secret = "claim-secret-value"

    class Resolver:
        async def resolve(self, credential, *, context=None):
            return secret

    class Executor:
        async def execute(self, node, inputs, *, context=None, packet=None):
            return {"out": {"answer": context.runtime_credentials["production"]}}

    registry = WorkflowNodeRegistry()
    registry.register_plugin(
        "trusted.test",
        [{
            "name": "trusted.node",
            "input": {"required": {}},
            "output": {"out": {"type": "any"}},
            "executor": Executor(),
        }],
        trusted=True,
    )
    workflow = WorkflowDef(
        id="secret-claims",
        name="secret-claims",
        nodes=[WorkflowNode(
            id="node",
            kind="trusted.node",
            config={"credential": CredentialRef("production")},
            ports=[WorkflowPort(name="out", direction="out")],
        )],
        output_port="node.out",
    )
    result = await WorkflowRunner(
        node_registry=registry,
        credential_resolver=Resolver(),
        event_store=events,
    ).run(
        workflow, thread_id="thread", run_id="run",
    )
    assert result.status == "completed"
    claims_path = tmp_path / ".lam" / "workflow" / "claims.sqlite3"
    with sqlite3.connect(claims_path) as connection:
        row = connection.execute(
            "SELECT result_json FROM workflow_claims WHERE namespace=?",
            (str(tmp_path / ".lam" / "workflow").casefold(),),
        ).fetchone()
    assert row is not None
    assert secret not in str(row[0])
