"""Focused coverage for the Workflow runtime service package."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from lamtools_core.plugins.bundled.workflow.backend.cache import WorkflowContentCache
from lamtools_core.plugins.bundled.workflow.backend.queue import WorkflowRunQueue
from lamtools_core.plugins.bundled.workflow.backend.registry import WorkflowNodeRegistry
from lamtools_core.plugins.bundled.workflow.backend.runtime import (
    WorkflowDef,
    WorkflowEdge,
    WorkflowNode,
    WorkflowPort,
    WorkflowRunner,
)
from lamtools_core.plugins.bundled.workflow.backend.snapshots import WorkflowSnapshotStore


def _workflow(name: str = "service") -> WorkflowDef:
    return WorkflowDef(
        name=name,
        nodes=[
            WorkflowNode(
                id="one",
                kind="content",
                ports=[WorkflowPort(name="out", direction="out", value=1)],
            ),
            WorkflowNode(
                id="two",
                kind="content",
                ports=[WorkflowPort(name="out", direction="out", value=2)],
            ),
        ],
    )


def test_node_registry_is_schema_only_and_requires_trust_for_extensions() -> None:
    registry = WorkflowNodeRegistry()
    assert {item.type_id for item in registry.list()} >= {
        "ai",
        "model",
        "agent",
        "command",
        "content",
        "constant",
        "script",
        "python",
        "subgraph",
    }
    assert set(registry.object_info()) == set(item.type_id for item in registry.list())
    with pytest.raises(PermissionError):
        registry.register_schema({"name": "external"})
    registered = registry.register_plugin(
        "trusted-plugin",
        [{"name": "external", "input": {}, "output": {"value": {"type": "string"}}}],
        trusted=True,
    )
    assert registered[0].plugin_id == "trusted-plugin"
    assert registry.object_info("external")["external"]["plugin_id"] == "trusted-plugin"


def test_node_registry_exposes_canonical_types_and_hidden_legacy_aliases() -> None:
    info = WorkflowNodeRegistry().object_info()
    visible = {name for name, item in info.items() if not item.get("hidden")}
    assert {"model", "agent", "command", "python", "constant", "input", "output", "template", "condition", "merge", "join", "subgraph"} <= visible
    assert info["ai"]["legacy"] is True and info["ai"]["hidden"] is True
    assert info["script"]["canonical_type"] == "python"
    assert info["content"]["canonical_type"] == "constant"


@pytest.mark.asyncio
async def test_first_class_model_and_agent_keep_legacy_ai_compatible(tmp_path: Path) -> None:
    model_requests = []
    agent_tasks = []

    class Model:
        async def complete(self, request):
            model_requests.append(request)
            return SimpleNamespace(content="model-ok")

    class Agent:
        async def run(self, **kwargs):
            agent_tasks.append(kwargs)
            return SimpleNamespace(message="agent-ok")

    workflow = WorkflowDef(name="new-ai", nodes=[
        WorkflowNode(id="model", kind="model", config={"instruction": "answer"}, ports=[WorkflowPort(name="out", direction="out")]),
        WorkflowNode(id="agent", kind="agent", config={"instruction": "act"}, ports=[WorkflowPort(name="out", direction="out")]),
        WorkflowNode(id="legacy", kind="ai", config={"mode": "single", "instruction": "legacy"}, ports=[WorkflowPort(name="out", direction="out")]),
    ])
    result = await WorkflowRunner(llm_client=Model(), sub_agent_runner=Agent()).run(workflow, work_root=str(tmp_path))
    assert result.status == "completed"
    assert result.values["model.out"] == "model-ok"
    assert result.values["agent.out"] == "agent-ok"
    assert result.values["legacy.out"] == "model-ok"
    assert len(model_requests) == 2 and len(agent_tasks) == 1


@pytest.mark.asyncio
async def test_template_condition_and_merge_execute_as_registered_builtins(tmp_path: Path) -> None:
    workflow = WorkflowDef(
        name="data-control",
        nodes=[
            WorkflowNode(id="source", kind="constant", ports=[WorkflowPort(name="value", direction="out", value="Ada")]),
            WorkflowNode(id="template", kind="template", config={"template": "Hello {{name}}"}, ports=[WorkflowPort(name="name", direction="in"), WorkflowPort(name="text", direction="out")]),
            WorkflowNode(id="branch", kind="condition", config={"expression": "value.startswith('Hello')"}, ports=[WorkflowPort(name="value", direction="in"), WorkflowPort(name="true", direction="out"), WorkflowPort(name="false", direction="out")]),
            WorkflowNode(id="merge", kind="merge", ports=[WorkflowPort(name="values", direction="in"), WorkflowPort(name="out", direction="out")]),
        ],
        edges=[
            WorkflowEdge(id="a", source="source", source_port="value", target="template", target_port="name"),
            WorkflowEdge(id="b", source="template", source_port="text", target="branch", target_port="value"),
            WorkflowEdge(id="c", source="branch", source_port="true", target="merge", target_port="values"),
            WorkflowEdge(id="d", source="branch", source_port="false", target="merge", target_port="values"),
        ],
        output_port="merge.out",
    )
    result = await WorkflowRunner().run(workflow, work_root=str(tmp_path))
    assert result.status == "completed", result.error
    assert result.output == "Hello Ada"


@pytest.mark.asyncio
async def test_snapshot_store_continues_after_runner_recreation(tmp_path: Path) -> None:
    workflow = _workflow()
    snapshots = WorkflowSnapshotStore(root=tmp_path)
    first = await WorkflowRunner(snapshot_store=snapshots).run(
        workflow,
        work_root=str(tmp_path),
        thread_id="workflow:service",
        run_id="restart",
        max_steps=1,
    )
    assert first.status == "paused"
    second = await WorkflowRunner(snapshot_store=snapshots).run(
        workflow,
        work_root=str(tmp_path),
        thread_id="workflow:service",
        run_id="restart",
        max_steps=1,
    )
    assert second.status == "completed"
    assert second.values == {"one.out": 1, "two.out": 2}
    assert await snapshots.get("workflow:service", "restart") is None


@pytest.mark.asyncio
async def test_content_cache_reports_hit_and_command_defaults_to_bypass(tmp_path: Path) -> None:
    workflow = _workflow("cache")
    cache = WorkflowContentCache(root=tmp_path)
    runner = WorkflowRunner(cache_store=cache)
    first = await runner.run(workflow, work_root=str(tmp_path), run_id="cache-1")
    second = await runner.run(workflow, work_root=str(tmp_path), run_id="cache-2")
    assert first.cache["one"]["status"] == "miss"
    assert second.cache["one"]["status"] == "hit"

    command = WorkflowDef(
        name="uncached",
        nodes=[WorkflowNode(id="command", kind="command", config={"command": "printf ok"})],
    )
    uncached = await runner.run(command, work_root=str(tmp_path), run_id="uncached")
    assert uncached.status == "completed"
    assert uncached.node_states["command"].cache_status == "bypass"


@pytest.mark.asyncio
async def test_queue_is_fifo_persistent_and_clear_requires_confirmation(tmp_path: Path) -> None:
    queue = WorkflowRunQueue(root=tmp_path, auto_start=False)
    first = await queue.enqueue(_workflow("fifo"), work_root=tmp_path, auto_start=False)
    second = await queue.enqueue(_workflow("fifo"), work_root=tmp_path, auto_start=False)
    assert [item.queue_id for item in await queue.list()] == [first.queue_id, second.queue_id]
    assert (await WorkflowRunQueue(root=tmp_path, auto_start=False).get(first.queue_id)) is not None
    with pytest.raises(ValueError):
        await queue.clear()
    assert await queue.cancel(first.queue_id) is not None
    assert await queue.clear(confirm=True) == 1
    remaining = await queue.list()
    assert [item.queue_id for item in remaining] == [second.queue_id]


@pytest.mark.asyncio
async def test_queue_events_include_lifecycle_statuses_and_ids(tmp_path: Path) -> None:
    events = []

    class Manager:
        async def get(self, name: str, *, work_root: str | None = None):
            del work_root
            return _workflow(name)

    queue = WorkflowRunQueue(
        root=tmp_path,
        manager=Manager(),
        runner=WorkflowRunner(),
        emit=events.append,
    )
    item = await queue.enqueue(workflow_name="events", work_root=tmp_path, max_steps=1)
    await asyncio.sleep(0.2)
    await queue.stop()
    statuses = {event.payload["status"] for event in events}
    assert {"queued", "running", "paused", "progress"} <= statuses
    assert all(event.payload["queue_id"] == item.queue_id for event in events)
    assert all(event.payload["run_id"] == item.run_id for event in events)


@pytest.mark.asyncio
async def test_queue_stop_persists_interrupted_snapshot_and_start_resumes(tmp_path: Path) -> None:
    class Manager:
        async def get(self, name: str, *, work_root: str | None = None):
            del work_root
            return WorkflowDef(
                name=name,
                nodes=[
                    WorkflowNode(
                        id="slow",
                        kind="script",
                        ports=[WorkflowPort(name="out", direction="out", value=None)],
                        config={"script": "import time\ntime.sleep(2)\nout = 3"},
                    )
                ],
            )

    from lamtools_core.plugins.bundled.workflow.backend.snapshots import WorkflowSnapshotStore

    manager = Manager()
    runner = WorkflowRunner(snapshot_store=WorkflowSnapshotStore(root=tmp_path))
    queue = WorkflowRunQueue(root=tmp_path, manager=manager, runner=runner)
    item = await queue.enqueue(
        workflow_name="slow",
        work_root=tmp_path,
        metadata={"permissions": {"run_command": True}},
    )
    for _ in range(100):
        current = await queue.get(item.queue_id)
        if current is not None and current.status == "running":
            break
        await asyncio.sleep(0.01)
    assert current is not None and current.status == "running"
    await queue.stop()

    interrupted = await queue.get(item.queue_id)
    assert interrupted is not None and interrupted.status == "paused"
    snapshot = await runner.snapshot_store.get(item.thread_id, item.run_id)
    assert snapshot is not None and snapshot.status == "paused"

    resumed = WorkflowRunQueue(root=tmp_path, manager=manager, runner=runner)
    await resumed.start()
    completed = await resumed.wait(item.queue_id, timeout=5)
    await resumed.stop()
    assert completed is not None and completed.status == "completed"
    assert completed.result is not None and completed.result.output == 3

    # An explicit user cancellation must remain terminal even though the same
    # queue uses resumable interruption for host shutdown.
    await resumed.start()
    cancelled_item = await resumed.enqueue(
        workflow_name="slow",
        work_root=tmp_path,
        metadata={"permissions": {"run_command": True}},
    )
    for _ in range(100):
        current = await resumed.get(cancelled_item.queue_id)
        if current is not None and current.status == "running":
            break
        await asyncio.sleep(0.01)
    assert current is not None and current.status == "running"
    cancelled = await resumed.cancel(cancelled_item.queue_id)
    await resumed.stop()
    assert cancelled is not None and cancelled.status == "cancelled"
