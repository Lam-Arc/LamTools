from __future__ import annotations

import asyncio
import multiprocessing
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from lamtools_core.plugins.bundled.workflow.backend.claims import WorkflowClaimStore
from lamtools_core.plugins.bundled.workflow.backend.durable import WorkflowRunEventStore
from lamtools_core.plugins.bundled.workflow.backend.runtime import (
    WorkflowDef,
    WorkflowEdge,
    WorkflowNode,
    WorkflowPort,
    WorkflowRunner,
)
from lamtools_core.plugins.bundled.workflow.backend.snapshots import WorkflowSnapshotStore


def _workflow(*, wait: bool) -> WorkflowDef:
    fixed_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    side = WorkflowNode(
        id="side",
        kind="agent",
        config={"instruction": "effect"},
        ports=[
            WorkflowPort(name="result", direction="in", type="object"),
            WorkflowPort(name="answer", direction="out"),
        ],
    )
    if not wait:
        side.ports = [WorkflowPort(name="answer", direction="out")]
        return WorkflowDef(
            id="multiprocess-run", name="multiprocess-run", revision=1,
            nodes=[side], output_port="side.answer", created_at=fixed_time, updated_at=fixed_time,
        )
    return WorkflowDef(
        id="multiprocess-signal", name="multiprocess-signal", revision=1,
        nodes=[
            WorkflowNode(
                id="wait", kind="wait_event", config={"event_type": "go"},
                ports=[WorkflowPort(name="result", direction="out", type="object")],
            ),
            side,
        ],
        edges=[WorkflowEdge(id="wait-side", source="wait", source_port="result", target="side", target_port="result")],
        output_port="side.answer",
        created_at=fixed_time,
        updated_at=fixed_time,
    )


class _FileEffectAgent:
    def __init__(self, effect_path: str) -> None:
        self.effect_path = effect_path

    async def run(self, **kwargs):
        with Path(self.effect_path).open("a", encoding="utf-8") as handle:
            handle.write("effect\n")
            handle.flush()
        await asyncio.sleep(0.1)
        return SimpleNamespace(message='{"answer":"once"}')


def _runner(root: str, effect_path: str) -> WorkflowRunner:
    return WorkflowRunner(
        sub_agent_runner=_FileEffectAgent(effect_path),
        event_store=WorkflowRunEventStore(root=root),
        snapshot_store=WorkflowSnapshotStore(root=root),
    )


def _run_worker(root: str, effect_path: str, start, output) -> None:
    async def _main() -> None:
        await asyncio.to_thread(start.wait)
        result = await _runner(root, effect_path).run(
            _workflow(wait=False), thread_id="thread", run_id="run"
        )
        output.put((result.status, result.error))

    asyncio.run(_main())


def _signal_worker(root: str, effect_path: str, token: str, start, output) -> None:
    async def _main() -> None:
        await asyncio.to_thread(start.wait)
        result = await _runner(root, effect_path).signal(
            thread_id="thread", run_id="run", resume_token=token,
            event_type="go", payload={"source": "process"},
        )
        output.put((result.status, result.error))

    asyncio.run(_main())


def _abandon_claim_worker(path: str, namespace: str, output) -> None:
    async def _main() -> None:
        store = WorkflowClaimStore(path, namespace=namespace, lease_seconds=1)
        acquired = await store.acquire("run", "thread", "run")
        output.put(acquired.lease.fencing_token if acquired.lease else 0)

    asyncio.run(_main())


def _join(processes: list[multiprocessing.Process]) -> None:
    for process in processes:
        process.join(timeout=20)
        assert process.exitcode == 0


@pytest.mark.parametrize("mode", ["run", "signal"])
def test_multiprocess_run_and_signal_are_single_flight(tmp_path: Path, mode: str) -> None:
    context = multiprocessing.get_context("spawn")
    root = str(tmp_path)
    effect_path = str(tmp_path / "effects.txt")
    token = ""
    if mode == "signal":
        paused = asyncio.run(
            _runner(root, effect_path).run(
                _workflow(wait=True), thread_id="thread", run_id="run"
            )
        )
        token = paused.wait_descriptor["resume_token"]
    start = context.Event()
    output = context.Queue()
    target = _signal_worker if mode == "signal" else _run_worker
    args = (root, effect_path, token, start, output) if mode == "signal" else (root, effect_path, start, output)
    processes = [context.Process(target=target, args=args) for _ in range(2)]
    for process in processes:
        process.start()
    start.set()
    _join(processes)
    results = [output.get(timeout=2), output.get(timeout=2)]
    assert sorted(status for status, _ in results) == ["completed", "completed"], results
    assert Path(effect_path).read_text(encoding="utf-8").splitlines() == ["effect"]


def test_expired_claim_is_taken_over_with_higher_fence(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    path = str(tmp_path / "claims.sqlite3")
    output = context.Queue()
    process = context.Process(target=_abandon_claim_worker, args=(path, "test", output))
    process.start()
    _join([process])
    assert output.get(timeout=2) == 1
    time.sleep(1.1)

    async def _takeover() -> int:
        store = WorkflowClaimStore(path, namespace="test", lease_seconds=1)
        acquired = await store.acquire("run", "thread", "run")
        assert acquired.lease is not None
        return acquired.lease.fencing_token

    assert asyncio.run(_takeover()) == 2
