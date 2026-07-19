from __future__ import annotations

import hashlib

import pytest

from lamtools_core.app.durable_operations import register_durable_operations
from lamtools_core.app.operation_catalog import OperationCatalog, OperationResult
from lamtools_core.runtime.arrange import ArrangeManager, InMemoryArrangeStore
from lamtools_core.runtime.goal import GoalManager, InMemoryGoalStore


@pytest.mark.asyncio
async def test_goal_operations_expose_full_lifecycle() -> None:
    catalog = OperationCatalog()
    register_durable_operations(
        catalog,
        goal_manager=GoalManager(InMemoryGoalStore()),
        arrange_manager=ArrangeManager(InMemoryArrangeStore()),
    )

    created = await catalog.execute(
        "goal.create",
        {
            "thread_id": "thread-1",
            "objective": "Verify the claim",
            "completion_criteria": ["primary source"],
        },
    )
    goal_id = created.payload["goal"]["id"]
    activated = await catalog.execute("goal.update", {"goal_id": goal_id, "status": "active"})
    listed = await catalog.execute("goal.list", {"thread_id": "thread-1", "status": "active"})

    assert activated.payload["goal"]["status"] == "active"
    assert [goal["id"] for goal in listed.payload["goals"]] == [goal_id]


@pytest.mark.asyncio
async def test_arrange_operations_validate_target_and_wake_runner() -> None:
    catalog = OperationCatalog()
    wakes: list[str] = []

    async def probe(request):
        return OperationResult(name=request.name, payload={"seen": True})

    catalog.register("probe.run", probe)
    register_durable_operations(
        catalog,
        goal_manager=GoalManager(InMemoryGoalStore()),
        arrange_manager=ArrangeManager(InMemoryArrangeStore()),
        wake_runner=lambda: wakes.append("wake"),
    )

    rejected = await catalog.execute(
        "arrange.create",
        {
            "thread_id": "thread-1",
            "kind": "routine",
            "operation": "missing.operation",
            "payload": {},
            "trigger": {"type": "once"},
        },
    )
    created = await catalog.execute(
        "arrange.create",
        {
            "thread_id": "thread-1",
            "kind": "routine",
            "operation": "probe.run",
            "payload": {"value": 1},
            "trigger": {"type": "once"},
        },
    )
    job_id = created.payload["job"]["id"]
    paused = await catalog.execute("arrange.pause", {"job_id": job_id})
    resumed = await catalog.execute("arrange.resume", {"job_id": job_id})

    assert rejected.status == "error"
    assert "not registered" in rejected.payload["error"]
    assert paused.payload["job"]["status"] == "paused"
    assert resumed.payload["job"]["status"] == "scheduled"
    assert wakes == ["wake", "wake"]


@pytest.mark.asyncio
async def test_arrange_signal_accepts_generic_event_envelope() -> None:
    catalog = OperationCatalog()

    async def probe(request):
        return OperationResult(name=request.name, payload={"seen": True})

    catalog.register("turn.start", probe)
    register_durable_operations(
        catalog,
        goal_manager=GoalManager(InMemoryGoalStore()),
        arrange_manager=ArrangeManager(InMemoryArrangeStore()),
    )
    created = await catalog.execute(
        "arrange.create",
        {
            "thread_id": "thread-1",
            "kind": "focus",
            "operation": "turn.start",
            "payload": {"message": "inspect"},
            "trigger": {"type": "event", "event_type": "artifact.changed"},
        },
    )
    result = await catalog.execute(
        "arrange.signal",
        {
            "event_id": "evt-operation",
            "event_type": "artifact.changed",
            "occurred_at": "2026-07-16T08:00:00Z",
            "source": "filesystem",
            "subject": "report.md",
            "data": {"path": "report.md", "digest": "abc"},
        },
    )

    assert result.status == "ok"
    assert result.payload["signal"]["event_id"] == "evt-operation"
    assert result.payload["signalled"] == 1
    assert result.payload["occurrences"][0]["job_id"] == created.payload["job"]["id"]


@pytest.mark.asyncio
async def test_agent_created_arrange_uses_core_owned_execution_thread_rule() -> None:
    catalog = OperationCatalog()
    catalog.register("turn.start", lambda request: OperationResult(name=request.name, payload={}))
    created_threads: list[tuple[str, str]] = []

    async def create_execution_thread(source_thread_id: str, instruction: str) -> str:
        created_threads.append((source_thread_id, instruction))
        return "execution-thread-1"

    register_durable_operations(
        catalog,
        goal_manager=GoalManager(InMemoryGoalStore()),
        arrange_manager=ArrangeManager(InMemoryArrangeStore()),
        create_execution_thread=create_execution_thread,
    )
    result = await catalog.execute(
        "arrange.create",
        {
            "thread_id": "source-thread-1",
            "kind": "routine",
            "operation": "turn.start",
            "payload": {"message": "prepare report"},
            "trigger": {"type": "once"},
        },
        metadata={"source": "agent_tool"},
    )

    assert result.payload["job"]["thread_id"] == "execution-thread-1"
    assert result.payload["job"]["source_thread_id"] == "source-thread-1"
    assert created_threads == [("source-thread-1", "prepare report")]


@pytest.mark.asyncio
async def test_arrange_operation_approves_observer_content_and_reconciles_runtime(tmp_path) -> None:
    catalog = OperationCatalog()
    catalog.register("turn.start", lambda request: OperationResult(name=request.name, payload={}))
    script = tmp_path / "observer.py"
    script.write_text("import time\ntime.sleep(1)\n", encoding="utf-8")
    wakes: list[str] = []

    register_durable_operations(
        catalog,
        goal_manager=GoalManager(InMemoryGoalStore()),
        arrange_manager=ArrangeManager(InMemoryArrangeStore()),
        wake_observers=lambda: wakes.append("wake"),
        observer_status=lambda _job_id: {"status": "running"},
    )
    result = await catalog.execute(
        "arrange.create",
        {
            "thread_id": "thread-1",
            "kind": "focus",
            "operation": "turn.start",
            "payload": {"message": "watch"},
            "trigger": {"type": "event", "event_type": "content.published"},
            "observer": {"entry": "observer.py"},
            "work_root": str(tmp_path),
        },
    )

    assert result.status == "ok"
    assert result.payload["job"]["observer"]["approved_sha256"] == hashlib.sha256(
        script.read_bytes()
    ).hexdigest()
    assert result.payload["job"]["observer_runtime"] == {"status": "running"}
    assert wakes == ["wake"]
