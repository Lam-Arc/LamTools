from __future__ import annotations

import asyncio
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from lamtools_core.plugins.bundled.workflow.backend.document import (
    document_from_workflow_def,
    workflow_def_from_document,
)
from lamtools_core.plugins.bundled.workflow.backend.flow_control import (
    FlowControlDecision,
    FlowControlLease,
    FlowControlStore,
)
from lamtools_core.plugins.bundled.workflow.backend.runtime import (
    WorkflowDef,
    WorkflowNode,
    WorkflowNodeState,
    WorkflowPort,
    WorkflowRunner,
)


def _workflow(policy: dict[str, object], *, two_nodes: bool = False) -> WorkflowDef:
    nodes = [
        WorkflowNode(
            id="value",
            kind="content",
            ports=[WorkflowPort(name="out", direction="out", value="ok")],
        )
    ]
    if two_nodes:
        nodes.append(
            WorkflowNode(
                id="tail",
                kind="content",
                ports=[WorkflowPort(name="out", direction="out", value="done")],
            )
        )
    definition = WorkflowDef(
        id="flow-control-workflow",
        name="flow-control",
        revision=4,
        nodes=nodes,
        output_port="tail.out" if two_nodes else "value.out",
    )
    document = document_from_workflow_def(definition)
    document["policies"] = policy
    return workflow_def_from_document(document)


def _agent_workflow(policy: dict[str, object]) -> WorkflowDef:
    definition = WorkflowDef(
        id="flow-control-agent",
        name="flow-control-agent",
        revision=1,
        nodes=[
            WorkflowNode(
                id="agent",
                kind="ai",
                config={"mode": "agent", "instruction": "wait"},
                ports=[WorkflowPort(name="answer", direction="out")],
            )
        ],
        output_port="agent.answer",
    )
    document = document_from_workflow_def(definition)
    document["policies"] = policy
    return workflow_def_from_document(document)


class _GateAgent:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0

    async def run(self, **_: object) -> SimpleNamespace:
        self.calls += 1
        self.started.set()
        await self.release.wait()
        return SimpleNamespace(message='{"answer":"ok"}')


class _ImmediateAgent:
    async def run(self, **_: object) -> SimpleNamespace:
        return SimpleNamespace(message='{"answer":"ok"}')


@pytest.mark.asyncio
async def test_two_runners_share_concurrency_and_return_a_retryable_pause(tmp_path: Path) -> None:
    workflow = _agent_workflow({"concurrency": {"key": "worker", "max": 1}})
    store = FlowControlStore(tmp_path / "flow.sqlite3", lease_seconds=5)
    first_agent = _GateAgent()
    first_runner = WorkflowRunner(sub_agent_runner=first_agent, flow_control_store=store)
    second_runner = WorkflowRunner(sub_agent_runner=_ImmediateAgent(), flow_control_store=store)

    first_task = asyncio.create_task(
        first_runner.run(
            workflow,
            work_root=str(tmp_path),
            thread_id="thread-1",
            run_id="run-1",
        )
    )
    await asyncio.wait_for(first_agent.started.wait(), timeout=2)

    started = time.monotonic()
    blocked = await second_runner.run(
        workflow,
        work_root=str(tmp_path),
        thread_id="thread-2",
        run_id="run-2",
    )
    elapsed = time.monotonic() - started

    assert elapsed < 0.5
    assert blocked.status == "paused"
    assert blocked.wait_descriptor["kind"] == "flow_control"
    assert blocked.wait_descriptor["type"] == "flow_control"
    assert blocked.wait_descriptor["reason"] == "concurrency"
    assert blocked.wait_descriptor["blocked_by"] == "concurrency"
    assert blocked.wait_descriptor["scope_key"]
    assert blocked.wait_descriptor["lease_id"]
    assert blocked.wait_descriptor["workflow_id"] == workflow.id
    assert blocked.wait_descriptor["workflow_revision"] == workflow.revision
    assert blocked.wait_descriptor["definition_digest"] == blocked.definition_digest
    assert blocked.wait_descriptor["thread_id"] == "thread-2"
    assert blocked.wait_descriptor["run_id"] == "run-2"
    assert blocked.wait_descriptor["retry_at"] is not None
    assert blocked.wait_descriptor["policy"] == {"concurrency": {"key": "worker", "max": 1}}
    assert first_agent.calls == 1

    first_agent.release.set()
    assert (await first_task).status == "completed"
    resumed = await asyncio.wait_for(
        second_runner.run(
            workflow,
            work_root=str(tmp_path),
            thread_id="thread-2",
            run_id="run-2",
        ),
        timeout=2,
    )
    assert resumed.status == "completed"


@pytest.mark.asyncio
async def test_flow_control_lease_releases_after_completion_and_cancellation(tmp_path: Path) -> None:
    workflow = _workflow({"concurrency": {"key": "worker", "max": 1}})
    store = FlowControlStore(tmp_path / "flow.sqlite3", lease_seconds=5)
    runner = WorkflowRunner(flow_control_store=store)
    scope_key = runner._flow_control_scope_key(workflow, workflow.id, str(tmp_path))

    completed = await runner.run(
        workflow,
        work_root=str(tmp_path),
        thread_id="thread-complete",
        run_id="run-complete",
    )
    assert completed.status == "completed"
    assert await store.count(scope_key=scope_key) == 0

    agent = _GateAgent()
    cancelling_runner = WorkflowRunner(sub_agent_runner=agent, flow_control_store=store)
    long_workflow = _agent_workflow({"concurrency": {"key": "worker", "max": 1}})
    task = asyncio.create_task(
        cancelling_runner.run(
            long_workflow,
            work_root=str(tmp_path),
            thread_id="thread-cancel",
            run_id="run-cancel",
        )
    )
    await asyncio.wait_for(agent.started.wait(), timeout=2)
    task.cancel()
    cancelled = await asyncio.wait_for(task, timeout=2)
    assert cancelled.status == "cancelled"
    cancel_scope = cancelling_runner._flow_control_scope_key(
        long_workflow, long_workflow.id, str(tmp_path)
    )
    assert await store.count(scope_key=cancel_scope) == 0


class _RenewingStore:
    lease_seconds = 0.03

    def __init__(self, *, lose: bool = False) -> None:
        self.renew_count = 0
        self.release_count = 0
        self.lose = lose

    async def acquire(self, policy, scope_key, lease_id):
        lease = FlowControlLease(
            namespace="test",
            scope_key=scope_key,
            lease_id=lease_id,
            owner_id="test-owner",
            fencing_token=1,
            acquired_at=0,
            lease_expires_at=1,
        )
        return FlowControlDecision("acquired", lease=lease)

    async def renew(self, lease):
        self.renew_count += 1
        if self.lose:
            return None
        return replace(lease, lease_expires_at=lease.lease_expires_at + 1)

    async def release(self, lease):
        self.release_count += 1
        return True


@pytest.mark.asyncio
async def test_flow_control_heartbeat_renews_and_lease_loss_fails_closed(tmp_path: Path) -> None:
    workflow = _agent_workflow({"concurrency": {"key": "worker", "max": 1}})
    store = _RenewingStore()
    agent = _GateAgent()
    runner = WorkflowRunner(sub_agent_runner=agent, flow_control_store=store)
    task = asyncio.create_task(
        runner.run(workflow, work_root=str(tmp_path), thread_id="renew", run_id="run-renew")
    )
    await agent.started.wait()
    await asyncio.sleep(0.1)
    agent.release.set()
    result = await asyncio.wait_for(task, timeout=2)
    assert result.status == "completed"
    assert store.renew_count >= 2
    assert store.release_count == 1

    losing_store = _RenewingStore(lose=True)
    losing_agent = _GateAgent()
    losing_runner = WorkflowRunner(sub_agent_runner=losing_agent, flow_control_store=losing_store)
    losing_task = asyncio.create_task(
        losing_runner.run(
            workflow,
            work_root=str(tmp_path),
            thread_id="lost",
            run_id="run-lost",
        )
    )
    await asyncio.wait_for(losing_agent.started.wait(), timeout=2)
    await asyncio.sleep(0.08)
    losing_agent.release.set()
    lost = await asyncio.wait_for(losing_task, timeout=2)
    assert lost.status == "failed"
    assert "flow-control lease was lost" in lost.error
    assert losing_store.release_count == 1


class _ClockedFlowControlStore(FlowControlStore):
    def __init__(self, path: Path) -> None:
        super().__init__(path, lease_seconds=30)
        self.now = 100.0

    async def acquire(self, policy=None, scope_key=None, lease_id=None, **kwargs):
        return await super().acquire(
            policy=policy,
            scope_key=scope_key,
            lease_id=lease_id,
            now=self.now,
            **kwargs,
        )

    async def release(self, lease, **kwargs):
        return await super().release(lease, now=self.now, **kwargs)


@pytest.mark.asyncio
async def test_rate_throttle_and_debounce_policies_pause_at_admission(tmp_path: Path) -> None:
    cases = [
        ({"rate_limit": {"count": 1, "window_seconds": 10}}, "rate_limit", False),
        ({"throttle": {"min_interval_seconds": 10}}, "throttle", False),
        ({"debounce": {"window_seconds": 10, "mode": "trailing"}}, "debounce", True),
    ]
    for index, (policy, reason, reserved) in enumerate(cases):
        store = _ClockedFlowControlStore(tmp_path / f"{reason}.sqlite3")
        runner = WorkflowRunner(flow_control_store=store)
        workflow = _workflow(policy)
        first = await runner.run(
            workflow,
            work_root=str(tmp_path),
            thread_id=f"thread-{index}-1",
            run_id=f"run-{index}-1",
        )
        assert first.status == "completed"
        store.now = 101
        blocked = await runner.run(
            workflow,
            work_root=str(tmp_path),
            thread_id=f"thread-{index}-2",
            run_id=f"run-{index}-2",
        )
        assert blocked.status == "paused"
        assert blocked.wait_descriptor["reason"] == reason
        assert blocked.wait_descriptor.get("reserved", False) is reserved
        store.now = 111
        resumed = await runner.run(
            workflow,
            work_root=str(tmp_path),
            thread_id=f"thread-{index}-3",
            run_id=f"run-{index}-3",
        )
        assert resumed.status == "completed"


@pytest.mark.asyncio
async def test_flow_control_pause_preserves_prior_values_and_states(tmp_path: Path) -> None:
    workflow = _workflow(
        {"rate_limit": {"count": 1, "window_seconds": 100}},
        two_nodes=True,
    )
    store = _ClockedFlowControlStore(tmp_path / "preserve.sqlite3")
    runner = WorkflowRunner(flow_control_store=store)
    first = await runner.run(
        workflow,
        work_root=str(tmp_path),
        thread_id="preserve",
        run_id="run-preserve",
        max_steps=1,
    )
    assert first.status == "paused"
    assert first.values["value.out"] == "ok"
    assert first.node_states["value"].status == "done"

    store.now = 101
    blocked = await runner.run(
        workflow,
        work_root=str(tmp_path),
        thread_id="preserve",
        run_id="run-preserve-2",
        prior_values=first.values,
        prior_node_states=first.node_states,
    )
    assert blocked.status == "paused"
    assert blocked.values == first.values
    assert blocked.node_states["value"].to_dict() == first.node_states["value"].to_dict()


@pytest.mark.asyncio
async def test_legacy_workflow_without_document_policy_is_unchanged(tmp_path: Path) -> None:
    class FailingStore:
        async def acquire(self, **_: object):
            raise AssertionError("legacy workflow must not invoke flow control")

    workflow = WorkflowDef(
        id="legacy-flow",
        name="legacy-flow",
        nodes=[
            WorkflowNode(
                id="value",
                kind="content",
                ports=[WorkflowPort(name="out", direction="out", value="legacy")],
            )
        ],
        output_port="value.out",
    )
    result = await WorkflowRunner(flow_control_store=FailingStore()).run(
        workflow,
        work_root=str(tmp_path),
        thread_id="legacy",
        run_id="legacy-run",
    )
    assert result.status == "completed"
    assert result.output == "legacy"
