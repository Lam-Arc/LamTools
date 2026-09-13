from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from lamtools_core.plugins.bundled.workflow.backend.durable import (
    NodeExecutionPolicy,
    WorkflowRunEvent,
    WorkflowRunEventStore,
)
from lamtools_core.app.operation_catalog import OperationRequest
from lamtools_core.plugins.bundled.workflow.backend.operations import workflow_run
from lamtools_core.plugins.context import PluginContext
from lamtools_core.plugins.bundled.workflow.backend.queue import WorkflowQueueItem, WorkflowQueueStore, WorkflowRunQueue
from lamtools_core.plugins.bundled.workflow.backend.runtime import (
    WorkflowDef,
    WorkflowNode,
    WorkflowPort,
    WorkflowRunner,
)
from lamtools_core.plugins.bundled.workflow.backend.snapshots import WorkflowSnapshotStore


def _content_workflow(*, revision: int, value: str = "old") -> WorkflowDef:
    return WorkflowDef(
        id="workflow-stable",
        name="pinned",
        revision=revision,
        nodes=[
            WorkflowNode(
                id="value",
                kind="content",
                ports=[WorkflowPort(name="out", direction="out", value=value)],
            )
        ],
        output_port="value.out",
    )


def test_queue_item_v1_migration_defaults_are_wire_compatible() -> None:
    item = WorkflowQueueItem.from_dict({"id": "q1", "name": "legacy", "status": "queued"})
    assert item.workflow_revision == 0
    assert item.workflow_definition == {}
    assert item.to_dict()["workflow_revision"] == 0


@pytest.mark.asyncio
async def test_queue_pins_definition_revision_at_acceptance(tmp_path: Path) -> None:
    original = _content_workflow(revision=3, value="old")

    class Manager:
        async def get(self, *args, **kwargs):
            return _content_workflow(revision=4, value="new")

    queue = WorkflowRunQueue(
        manager=Manager(),
        runner=WorkflowRunner(),
        store=WorkflowQueueStore(path=tmp_path / "queue.json"),
        auto_start=False,
    )
    item = await queue.enqueue(original, run_id="run-pinned", auto_start=False)
    assert item.workflow_revision == 3
    await queue._execute_item(item)
    stored = await queue.get(item.queue_id)
    assert stored is not None
    assert stored.result is not None and stored.result.output == "old"
    assert stored.result.workflow_revision == 3


@pytest.mark.asyncio
async def test_event_journal_is_append_only_idempotent_and_projectable(tmp_path: Path) -> None:
    store = WorkflowRunEventStore(root=tmp_path)
    event = WorkflowRunEvent(
        event_id="run-1:start",
        run_id="run-1",
        kind="run.started",
        workflow_id="wf",
        workflow_revision=7,
        payload={"definition_digest": "abc"},
    )
    first = await store.append(event)
    duplicate = await store.append(event)
    await store.append(
        WorkflowRunEvent(event_id="run-1:done", run_id="run-1", kind="run.completed")
    )
    assert first.sequence == duplicate.sequence == 1
    assert [item.sequence for item in await store.list("run-1")] == [1, 2]
    projected = await store.project("run-1")
    assert projected is not None
    assert projected.status == "completed"
    assert projected.workflow_revision == 7
    assert projected.definition_digest == "abc"


@pytest.mark.asyncio
async def test_engine_retry_records_attempts_and_propagates_idempotency_keys(tmp_path: Path) -> None:
    contexts = []

    class AgentRunner:
        async def run(self, **kwargs):
            contexts.append(kwargs["execution_context"])
            if len(contexts) == 1:
                raise RuntimeError("transient")
            return SimpleNamespace(message='{"answer":"ok"}')

    workflow = WorkflowDef(
        id="wf-retry",
        name="retry",
        revision=2,
        nodes=[
            WorkflowNode(
                id="agent",
                kind="ai",
                config={"mode": "agent", "instruction": "answer", "execution": {"retry": {"retries": 1, "delays_seconds": [0]}}},
                ports=[WorkflowPort(name="answer", direction="out")],
            )
        ],
    )
    events = WorkflowRunEventStore(root=tmp_path)
    result = await WorkflowRunner(sub_agent_runner=AgentRunner(), event_store=events).run(
        workflow, run_id="run-retry", thread_id="thread-retry"
    )
    assert result.status == "completed"
    assert result.node_states["agent"].attempts == 2
    keys = [context.event_metadata["idempotency_key"] for context in contexts]
    assert len(set(keys)) == 2
    kinds = [event.kind for event in await events.list("run-retry")]
    assert kinds.count("attempt.started") == 2
    assert "attempt.failed" in kinds and "attempt.completed" in kinds


@pytest.mark.asyncio
async def test_repeated_terminal_run_id_returns_journaled_result_without_side_effect(tmp_path: Path) -> None:
    calls = 0

    class AgentRunner:
        async def run(self, **kwargs):
            nonlocal calls
            calls += 1
            return SimpleNamespace(message='{"answer":"once"}')

    workflow = WorkflowDef(
        id="wf-once",
        name="once",
        revision=1,
        nodes=[
            WorkflowNode(
                id="agent",
                kind="ai",
                config={"mode": "agent", "instruction": "answer"},
                ports=[WorkflowPort(name="answer", direction="out")],
            )
        ],
    )
    events = WorkflowRunEventStore(root=tmp_path)
    runner = WorkflowRunner(sub_agent_runner=AgentRunner(), event_store=events)
    first = await runner.run(workflow, run_id="same-run", thread_id="same-thread")
    second = await runner.run(workflow, run_id="same-run", thread_id="same-thread")
    assert first.status == second.status == "completed"
    assert second.values == first.values
    assert calls == 1


@pytest.mark.asyncio
async def test_resume_skips_completed_node_and_rejects_changed_revision(tmp_path: Path) -> None:
    calls = 0

    class AgentRunner:
        async def run(self, **kwargs):
            nonlocal calls
            calls += 1
            return SimpleNamespace(message='{"answer":"ok"}')

    workflow = WorkflowDef(
        id="wf-resume",
        name="resume",
        revision=1,
        nodes=[
            WorkflowNode(
                id="agent",
                kind="ai",
                config={"mode": "agent", "instruction": "answer"},
                ports=[WorkflowPort(name="answer", direction="out")],
            ),
            WorkflowNode(
                id="tail",
                kind="content",
                ports=[WorkflowPort(name="out", direction="out", value="done")],
            ),
        ],
        output_port="tail.out",
    )
    snapshots = WorkflowSnapshotStore(root=tmp_path)
    first = await WorkflowRunner(sub_agent_runner=AgentRunner(), snapshot_store=snapshots).run(
        workflow, run_id="run-resume", thread_id="thread-resume", max_steps=1
    )
    assert first.status == "paused" and calls == 1

    resumed = await WorkflowRunner(sub_agent_runner=AgentRunner(), snapshot_store=snapshots).run(
        workflow, run_id="run-resume", thread_id="thread-resume"
    )
    assert resumed.status == "completed" and resumed.values["tail.out"] == "done"
    assert calls == 1

    other = _content_workflow(revision=1)
    await WorkflowRunner(snapshot_store=snapshots).run(
        other, run_id="changed", thread_id="changed", max_steps=0
    )
    other.revision = 2
    rejected = await WorkflowRunner(snapshot_store=snapshots).run(
        other, run_id="changed", thread_id="changed"
    )
    assert rejected.status == "failed"
    assert "definition changed" in rejected.error


def test_engine_policy_normalizes_new_and_legacy_shapes() -> None:
    legacy = NodeExecutionPolicy.from_config({"retries": 2, "timeout": 3})
    modern = NodeExecutionPolicy.from_config(
        {"execution": {"timeout_seconds": 4, "retry": {"retries": 1, "delays_seconds": [0.5]}}}
    )
    assert (legacy.max_attempts, legacy.timeout_seconds) == (3, 3.0)
    assert modern.max_attempts == 2
    assert modern.timeout_seconds == 4.0
    assert modern.retry_delays_seconds == (0.5,)


@pytest.mark.asyncio
async def test_activation_run_fails_closed_when_revision_is_unavailable(tmp_path: Path) -> None:
    current = _content_workflow(revision=8)

    class Manager:
        async def get(self, *args, **kwargs):
            return current

    context = PluginContext(
        work_root=tmp_path,
        data_dir=tmp_path / "data",
        services={
            "workflow": SimpleNamespace(
                manager=Manager(),
                runner=WorkflowRunner(),
                watch_work_root=lambda value: None,
            )
        },
    )
    response = await workflow_run(
        OperationRequest(
            name="workflow.run",
            payload={
                "activation": {
                    "format": "lamtools.workflow.activation",
                    "workflow_id": current.id,
                    "workflow_name": current.name,
                    "workflow_revision": 7,
                    "trigger_id": "trigger-1",
                }
            },
        ),
        context=context,
    )
    assert response.status == "error"
    assert response.payload["error"] == "Workflow revision 7 is not available; current revision is 8"
