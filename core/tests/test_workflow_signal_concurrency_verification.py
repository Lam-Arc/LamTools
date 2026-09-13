"""Adversarial verification for durable signal de-duplication.

This test intentionally uses two runner instances to model two RPC workers (or
two processes) sharing the same local durable stores.  A per-Runner asyncio
lock is not a durable atomic claim and must not permit duplicate downstream
side effects.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from lamtools_core.plugins.bundled.workflow.backend.durable import (
    WorkflowRunEvent,
    WorkflowRunEventStore,
    attempt_identity,
    definition_digest,
)
from lamtools_core.plugins.bundled.workflow.backend.runtime import (
    WorkflowDef,
    WorkflowEdge,
    WorkflowNode,
    WorkflowNodeState,
    WorkflowPort,
    WorkflowRunResult,
    WorkflowRunner,
)
from lamtools_core.plugins.bundled.workflow.backend.snapshots import WorkflowSnapshotStore


def _wait_workflow() -> WorkflowDef:
    return WorkflowDef(
        id="signal-race",
        name="signal-race",
        revision=1,
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
        edges=[
            WorkflowEdge(
                id="wait-side",
                source="wait",
                source_port="result",
                target="side",
                target_port="result",
            )
        ],
        output_port="side.answer",
    )


class _VisibilityBarrierEventStore(WorkflowRunEventStore):
    """Hold the first two signal reads before wait.signalled is visible."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.gate_enabled = False
        self._reads = 0
        self._both_read = asyncio.Event()

    async def list(self, run_id: str, *, after_sequence: int = 0):
        if self.gate_enabled and self._reads < 2:
            self._reads += 1
            if self._reads == 2:
                self._both_read.set()
            await self._both_read.wait()
        return await super().list(run_id, after_sequence=after_sequence)


@pytest.mark.asyncio
async def test_duplicate_signal_across_runner_instances_does_not_repeat_side_effect(
    tmp_path: Path,
) -> None:
    calls = 0

    class AgentRunner:
        async def run(self, **kwargs):
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.01)
            return SimpleNamespace(message='{"answer":"once"}')

    event_store = _VisibilityBarrierEventStore(root=tmp_path)
    snapshot_store = WorkflowSnapshotStore(root=tmp_path)
    first_runner = WorkflowRunner(
        sub_agent_runner=AgentRunner(),
        event_store=event_store,
        snapshot_store=snapshot_store,
    )
    paused = await first_runner.run(_wait_workflow(), thread_id="thread", run_id="run")
    assert paused.status == "paused"

    # Different Runner objects model independent RPC workers.  Their in-memory
    # signal locks cannot establish a cross-worker atomic claim.
    second_runner = WorkflowRunner(
        sub_agent_runner=first_runner.sub_agent_runner,
        event_store=event_store,
        snapshot_store=snapshot_store,
    )
    event_store.gate_enabled = True
    token = paused.wait_descriptor["resume_token"]
    first, second = await asyncio.gather(
        first_runner.signal(
            thread_id="thread",
            run_id="run",
            resume_token=token,
            event_type="go",
            payload={"source": "race"},
        ),
        second_runner.signal(
            thread_id="thread",
            run_id="run",
            resume_token=token,
            event_type="go",
            payload={"source": "race"},
        ),
    )

    assert first.status == second.status == "completed"
    assert calls == 1


@pytest.mark.asyncio
async def test_crash_recovery_reuses_interrupted_attempt_identity(tmp_path: Path) -> None:
    observed: list[str] = []
    workflow = WorkflowDef(
        id="crash-recovery",
        name="crash-recovery",
        revision=1,
        nodes=[
            WorkflowNode(
                id="side",
                kind="agent",
                config={"instruction": "resume safely"},
                ports=[WorkflowPort(id="answer", name="answer", direction="out")],
            )
        ],
        output_port="side.answer",
    )
    digest = definition_digest(workflow.to_dict())
    attempt_id, idempotency_key = attempt_identity("run", "side", 1)
    events = WorkflowRunEventStore(root=tmp_path)
    snapshots = WorkflowSnapshotStore(root=tmp_path)
    await events.append(
        WorkflowRunEvent(
            event_id="run:started",
            run_id="run",
            kind="run.started",
            workflow_id=workflow.id,
            workflow_revision=workflow.revision,
            payload={"definition_digest": digest},
        )
    )
    await events.append(
        WorkflowRunEvent(
            event_id=f"{attempt_id}:started",
            run_id="run",
            kind="attempt.started",
            workflow_id=workflow.id,
            workflow_revision=workflow.revision,
            node_id="side",
            attempt_id=attempt_id,
            payload={"number": 1, "idempotency_key": idempotency_key},
        )
    )
    await snapshots.save(
        "thread",
        "run",
        WorkflowRunResult(
            status="paused",
            run_id="run",
            workflow_id=workflow.id,
            workflow_revision=workflow.revision,
            node_states={
                "side": WorkflowNodeState(
                    node_id="side",
                    status="running",
                    attempts=1,
                    attempt_id=attempt_id,
                    idempotency_key=idempotency_key,
                    error="interrupted",
                )
            },
        ),
        workflow_id=workflow.id,
        workflow_name=workflow.name,
        workflow_revision=workflow.revision,
        definition_digest=digest,
        workflow_definition=workflow.to_dict(),
    )

    class AgentRunner:
        async def run(self, **kwargs):
            observed.append(kwargs["execution_context"].event_metadata["idempotency_key"])
            return SimpleNamespace(message='{"answer":"resumed"}')

    result = await WorkflowRunner(
        sub_agent_runner=AgentRunner(),
        event_store=events,
        snapshot_store=snapshots,
    ).run(workflow, thread_id="thread", run_id="run")

    assert result.status == "completed"
    assert observed == [idempotency_key]


@pytest.mark.asyncio
async def test_duplicate_run_across_runner_instances_does_not_repeat_side_effect(
    tmp_path: Path,
) -> None:
    calls = 0

    class AgentRunner:
        async def run(self, **kwargs):
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.01)
            return SimpleNamespace(message='{"answer":"once"}')

    event_store = _VisibilityBarrierEventStore(root=tmp_path)
    workflow = WorkflowDef(
        id="run-race",
        name="run-race",
        revision=1,
        nodes=[
            WorkflowNode(
                id="side",
                kind="agent",
                config={"instruction": "side effect"},
                ports=[WorkflowPort(name="answer", direction="out")],
            )
        ],
        output_port="side.answer",
    )
    agent = AgentRunner()
    first_runner = WorkflowRunner(sub_agent_runner=agent, event_store=event_store)
    second_runner = WorkflowRunner(sub_agent_runner=agent, event_store=event_store)
    event_store.gate_enabled = True

    first, second = await asyncio.gather(
        first_runner.run(workflow, thread_id="thread", run_id="run"),
        second_runner.run(workflow, thread_id="thread", run_id="run"),
    )

    assert first.status == second.status == "completed"
    assert calls == 1
