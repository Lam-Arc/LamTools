from __future__ import annotations

import json
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from lamtools_core.plugins.bundled.workflow.backend import cli as workflow_cli
from lamtools_core.plugins.bundled.workflow.backend.runtime import (
    WorkflowConflictError,
    WorkflowDef,
    WorkflowExecutionContext,
    WorkflowNode,
    WorkflowPort,
    WorkflowRunner,
    WorkflowManager,
)
from lamtools_core.plugins.bundled.workflow.backend.store import WorkflowStore


def _content(node_id: str, value: object) -> WorkflowNode:
    return WorkflowNode(
        id=node_id,
        kind="content",
        ports=[WorkflowPort(name="out", direction="out", value=value)],
    )


@pytest.mark.asyncio
async def test_step_run_resumes_server_snapshot_and_preserves_full_state(tmp_path: Path) -> None:
    workflow = WorkflowDef(name="steps", nodes=[_content("one", 1), _content("two", 2)])
    runner = WorkflowRunner()

    first = await runner.run(
        workflow, work_root=str(tmp_path), thread_id="workflow:steps", run_id="same", max_steps=1
    )
    second = await runner.run(
        workflow, work_root=str(tmp_path), thread_id="workflow:steps", run_id="same", max_steps=1
    )

    assert first.status == "paused"
    assert second.status == "completed"
    assert second.values == {"one.out": 1, "two.out": 2}
    assert second.node_states["one"].attempts == 1
    assert second.node_states["two"].attempts == 1
    assert second.started_at == first.started_at
    assert second.finished_at is not None


@pytest.mark.asyncio
async def test_agent_adapter_receives_parent_cwd_permissions_and_event_context(tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    class AgentRunner:
        async def run(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(message='{"answer":"ok"}')

    node = WorkflowNode(
        id="agent",
        kind="ai",
        config={"mode": "agent", "instruction": "answer"},
        ports=[WorkflowPort(name="answer", direction="out")],
    )
    context = WorkflowExecutionContext(
        parent_session_id="parent-session",
        parent_run_id="parent-run",
        parent_turn_id="parent-turn",
        parent_call_id="parent-call",
        cwd=str(tmp_path),
        permissions={"allow": ["read"]},
        event_metadata={"trace_id": "trace-1"},
    )
    result = await WorkflowRunner(sub_agent_runner=AgentRunner()).run(
        WorkflowDef(name="agent", nodes=[node]), execution_context=context,
        thread_id="workflow:agent", run_id="workflow-run", work_root=str(tmp_path),
    )

    assert result.status == "completed"
    assert captured["parent_run_id"] == "parent-run"
    assert captured["parent_turn_id"] == "parent-turn"
    assert captured["parent_call_id"] == "parent-call"
    assert captured["execution_context"] is context
    assert context.metadata()["cwd"] == str(tmp_path)
    assert context.metadata()["permissions"] == {"allow": ["read"]}
    assert context.metadata()["trace_id"] == "trace-1"


@pytest.mark.asyncio
async def test_nested_run_observes_shared_cooperative_cancellation(tmp_path: Path) -> None:
    cancelled = asyncio.Event()

    class AgentRunner:
        async def run(self, **kwargs):
            await asyncio.sleep(30)

    child = WorkflowDef(
        name="child",
        nodes=[WorkflowNode(id="wait", kind="ai", config={"mode": "agent", "instruction": "wait"})],
    )

    class Store:
        async def get(self, name, *, work_root=None):
            return child if name == "child" else None

    parent = WorkflowDef(
        name="parent",
        nodes=[WorkflowNode(id="nested", kind="subgraph", config={"workflow_name": "child"})],
    )
    context = WorkflowExecutionContext(cwd=str(tmp_path), cancellation=cancelled)
    task = asyncio.create_task(
        WorkflowRunner(sub_agent_runner=AgentRunner(), workflow_store=Store()).run(
            parent, execution_context=context, work_root=str(tmp_path),
            thread_id="workflow:parent", run_id="parent-run",
        )
    )
    await asyncio.sleep(0)
    cancelled.set()
    result = await asyncio.wait_for(task, timeout=2)

    assert result.status == "cancelled", result.error
    assert result.node_states["nested"].status == "cancelled"


@pytest.mark.asyncio
async def test_execution_context_can_explicitly_block_command_without_host_bypass(tmp_path: Path) -> None:
    node = WorkflowNode(id="command", kind="command", config={"command": "echo unsafe"})
    result = await WorkflowRunner().run(
        WorkflowDef(name="blocked", nodes=[node]), work_root=str(tmp_path),
        execution_context=WorkflowExecutionContext(
            cwd=str(tmp_path), permissions={"run_command": False}
        ),
    )
    assert result.status == "failed"
    assert "blocked by execution context" in result.error


@pytest.mark.asyncio
async def test_legacy_definition_gets_stable_id_and_revision_round_trips(tmp_path: Path) -> None:
    root = tmp_path / ".lam" / "workflows"
    root.mkdir(parents=True)
    legacy = root / "legacy.json"
    legacy.write_text(json.dumps({"name": "legacy", "nodes": []}), encoding="utf-8")
    store = WorkflowStore()

    first = await store.get("legacy", work_root=str(tmp_path))
    second = await store.get("legacy", work_root=str(tmp_path))

    assert first is not None and second is not None
    assert first.id == second.id
    assert first.revision == 0
    await store.save(WorkflowDef.from_dict({**first.to_dict(), "revision": 7, "work_root": str(tmp_path)}))
    saved = await store.get("legacy", work_root=str(tmp_path))
    assert saved is not None and saved.id == first.id and saved.revision == 7


@pytest.mark.asyncio
async def test_manager_revision_compare_and_swap_rejects_stale_writer(tmp_path: Path) -> None:
    store = WorkflowStore()
    manager = WorkflowManager(store)
    created = await manager.create(WorkflowDef(name="cas", work_root=str(tmp_path)))
    assert created.revision == 1
    updated = await manager.update_fields(
        "cas", work_root=str(tmp_path), description="new", expected_revision=1
    )
    assert updated.revision == 2
    with pytest.raises(WorkflowConflictError):
        await manager.update_fields(
            "cas", work_root=str(tmp_path), description="stale", expected_revision=1
        )


@pytest.mark.asyncio
async def test_manager_revision_compare_and_swap_is_atomic_for_concurrent_writers(
    tmp_path: Path,
) -> None:
    store = WorkflowStore()
    manager_a = WorkflowManager(store)
    manager_b = WorkflowManager(store)
    created = await manager_a.create(WorkflowDef(name="cas-concurrent", work_root=str(tmp_path)))

    async def write(manager: WorkflowManager, description: str):
        try:
            return "ok", await manager.update_fields(
                "cas-concurrent",
                work_root=str(tmp_path),
                description=description,
                expected_revision=created.revision,
            )
        except WorkflowConflictError:
            return "conflict", None

    first, second = await asyncio.gather(
        write(manager_a, "first"),
        write(manager_b, "second"),
    )
    assert sorted(result[0] for result in (first, second)) == ["conflict", "ok"]
    saved = await store.get("cas-concurrent", work_root=str(tmp_path))
    assert saved is not None and saved.revision == created.revision + 1


@pytest.mark.asyncio
async def test_cancel_cli_calls_manifest_operation(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    async def fake_invoke(args, operation):
        class Client:
            async def request(self, name, payload):
                seen.update(name=name, payload=payload)
                return {"cancelled": True}

        return await operation(Client())

    monkeypatch.setattr(workflow_cli, "_invoke_live", fake_invoke)
    code = await workflow_cli.workflow_cancel(
        SimpleNamespace(thread_id="workflow:one", run_id="run-1", raw=True)
    )
    assert code == 0
    assert seen == {
        "name": "workflow.cancel",
        "payload": {"thread_id": "workflow:one", "run_id": "run-1"},
    }
