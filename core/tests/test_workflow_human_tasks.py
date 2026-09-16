from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from lamtools_core.app.operation_catalog import OperationRequest, OperationResult
from lamtools_core.plugins.bundled.workflow.backend import operations as workflow_operations
from lamtools_core.plugins.bundled.workflow.backend.durable import WorkflowRunEventStore
from lamtools_core.plugins.bundled.workflow.backend.human_tasks import HumanTaskCenter
from lamtools_core.plugins.bundled.workflow.backend.runtime import (
    WorkflowDef,
    WorkflowEdge,
    WorkflowNode,
    WorkflowPort,
    WorkflowRunner,
)
from lamtools_core.plugins.bundled.workflow.backend.snapshots import WorkflowSnapshotStore
from lamtools_core.plugins.context import PluginContext


def _workflow(*, name: str = "review", timeout_seconds: float | None = None) -> WorkflowDef:
    config: dict[str, Any] = {
        "event_type": "review.completed",
        "title": "Review request",
        "assignee": "alice",
        "group": "quality",
        "form_schema": {
            "type": "object",
            "properties": {"note": {"type": "string"}},
            "api_key": "form-secret",
            "resumeToken": "camel-resume-secret",
        },
    }
    if timeout_seconds is not None:
        config["timeout_seconds"] = timeout_seconds
    return WorkflowDef(
        id=f"workflow-{name}",
        name=name,
        revision=3,
        nodes=[
            WorkflowNode(
                id="review",
                kind="wait_event",
                config=config,
                ports=[WorkflowPort(name="result", direction="out", type="object")],
            )
        ],
    )


def _contains_private_key(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            key.lower().replace("-", "_") in {"resume_token", "continuation_token", "token"}
            or _contains_private_key(nested)
            for key, nested in value.items()
        )
    if isinstance(value, list):
        return any(_contains_private_key(item) for item in value)
    return False


@pytest.mark.asyncio
async def test_human_task_center_projects_secret_free_tasks_and_idempotent_completion(
    tmp_path: Path,
) -> None:
    snapshots = WorkflowSnapshotStore(root=tmp_path)
    events = WorkflowRunEventStore(root=tmp_path)
    runner = WorkflowRunner(snapshot_store=snapshots, event_store=events)
    paused = await runner.run(
        _workflow(),
        work_root=tmp_path,
        thread_id="review-thread",
        run_id="review-run",
    )
    assert paused.status == "paused"
    resume_token = paused.wait_descriptor["resume_token"]

    center = HumanTaskCenter(
        snapshot_store=snapshots,
        event_store=events,
        runner=runner,
        work_root=tmp_path,
    )
    pending = await center.list(include_audit=True)
    assert len(pending) == 1
    task = pending[0]
    assert task["task_id"] == "review-run:review"
    assert task["status"] == "pending"
    assert task["title"] == "Review request"
    assert task["assignee"] == "alice"
    assert task["group"] == "quality"
    assert task["form"]["api_key"] == "[REDACTED]"
    assert not _contains_private_key(task)
    assert resume_token not in json.dumps(task, ensure_ascii=False)
    assert "camel-resume-secret" not in json.dumps(task, ensure_ascii=False)
    assert [event["kind"] for event in task["audit"]].count("wait.created") == 1

    completed = await center.complete(
        task["task_id"],
        payload={"note": "looks good"},
    )
    assert completed["task"]["status"] == "completed"
    assert completed["task"]["outcome"]["status"] == "received"
    assert not _contains_private_key(completed)
    assert resume_token not in json.dumps(completed, ensure_ascii=False)

    duplicate = await center.complete(task["task_id"], decision="reject", payload={"late": True})
    assert duplicate["idempotent"] is True
    assert duplicate["task"]["outcome"]["status"] == "received"
    assert len(await center.list(status="pending")) == 0
    assert len(await center.list(status="completed")) == 1


@pytest.mark.asyncio
async def test_human_task_center_hydrates_workflow_metadata_from_store(tmp_path: Path) -> None:
    snapshots = WorkflowSnapshotStore(root=tmp_path)
    events = WorkflowRunEventStore(root=tmp_path)
    runner = WorkflowRunner(snapshot_store=snapshots, event_store=events)
    workflow = _workflow(name="stored-review")
    await runner.run(
        workflow,
        work_root=tmp_path,
        thread_id="stored-review-thread",
        run_id="stored-review-run",
    )

    class WorkflowStore:
        async def list(self, *, work_root: str | None = None) -> list[dict[str, Any]]:
            assert Path(str(work_root)).resolve() == tmp_path.resolve()
            return [workflow.to_dict()]

    center = HumanTaskCenter(
        snapshot_store=snapshots,
        event_store=events,
        workflow_store=WorkflowStore(),
        runner=runner,
        work_root=tmp_path,
    )

    tasks = await center.list()
    assert len(tasks) == 1
    assert tasks[0]["workflow_id"] == workflow.id
    assert tasks[0]["workflow_name"] == workflow.name


@pytest.mark.asyncio
async def test_human_task_complete_operation_returns_resumed_terminal_snapshot(
    tmp_path: Path,
) -> None:
    snapshots = WorkflowSnapshotStore(root=tmp_path)
    events = WorkflowRunEventStore(root=tmp_path)
    runner = WorkflowRunner(snapshot_store=snapshots, event_store=events)
    workflow = WorkflowDef(
        id="workflow-approval-chain",
        name="approval-chain",
        revision=1,
        nodes=[
            WorkflowNode(
                id="review", kind="approval",
                config={"event_type": "review.completed"},
                ports=[WorkflowPort(name="result", direction="out", type="object")],
            ),
            WorkflowNode(
                id="after", kind="content",
                ports=[
                    WorkflowPort(name="review", direction="in", type="object"),
                    WorkflowPort(name="out", direction="out", value="continued"),
                ],
            ),
        ],
        edges=[WorkflowEdge(
            id="review-after", source="review", source_port="result",
            target="after", target_port="review",
        )],
    )
    paused = await runner.run(
        workflow, work_root=str(tmp_path), thread_id="approval-thread", run_id="approval-run"
    )
    assert paused.status == "paused"
    runtime = SimpleNamespace(runner=runner, store=None)
    context = PluginContext(work_root=tmp_path, services={"workflow": runtime})

    response = await workflow_operations.workflow_human_task_complete(
        OperationRequest(
            name="workflow.human_task.complete",
            payload={
                "task_id": "approval-run:review",
                "decision": "approve",
                "payload": {"note": "approved"},
            },
        ),
        context=context,
    )

    assert response.status == "ok"
    assert response.payload["run"]["status"] == "completed"
    assert response.payload["run"]["output"] == "continued"
    assert response.payload["run"]["node_states"]["review"]["status"] == "done"
    assert response.payload["run"]["node_states"]["after"]["status"] == "done"
    assert not _contains_private_key(response.payload)


@pytest.mark.asyncio
async def test_human_task_center_scopes_projects_and_times_out_due_tasks(tmp_path: Path) -> None:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    roots = [tmp_path / "project-a", tmp_path / "project-b"]
    centers: list[HumanTaskCenter] = []
    for index, root in enumerate(roots):
        snapshots = WorkflowSnapshotStore(root=root)
        events = WorkflowRunEventStore(root=root)
        runner = WorkflowRunner(
            snapshot_store=snapshots,
            event_store=events,
            clock=lambda: now,
        )
        await runner.run(
            _workflow(name=f"review-{index}", timeout_seconds=5),
            work_root=root,
            thread_id=f"thread-{index}",
            run_id=f"run-{index}",
        )
        centers.append(
            HumanTaskCenter(
                snapshot_store=snapshots,
                event_store=events,
                runner=runner,
                work_root=root,
                clock=lambda: now,
            )
        )

    merged = HumanTaskCenter(
        snapshot_stores=[center.snapshot_stores[0] for center in centers],
        event_stores=[center.event_stores[0] for center in centers],
        work_root=roots[0],
    )
    assert [item["run_id"] for item in await merged.list()] == ["run-0"]
    assert {item["run_id"] for item in await merged.list(include_all=True)} == {"run-0", "run-1"}

    # Use the first runner-backed center for the timeout operation.  Before
    # the deadline it is a stable no-op; after the deadline it resumes through
    # the normal signal path and projects a timed-out outcome.
    not_due = await centers[0].timeout("run-0:review")
    assert not_due["not_due"] is True
    now += timedelta(seconds=6)
    timed_out = await centers[0].timeout("run-0:review")
    assert timed_out["timed_out"] is True
    assert timed_out["task"]["status"] == "completed"
    assert timed_out["task"]["outcome"]["status"] == "timed_out"
    assert (await centers[0].timeout("run-0:review"))["idempotent"] is True


@pytest.mark.asyncio
async def test_human_task_timeout_arrange_payload_is_stable_and_secret_free(tmp_path: Path) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    jobs: dict[str, dict[str, Any]] = {}

    class Catalog:
        async def execute(
            self,
            name: str,
            payload: dict[str, Any],
            *,
            metadata: dict[str, Any] | None = None,
        ) -> OperationResult:
            del metadata
            calls.append((name, payload))
            if name == "arrange.get":
                job_id = str(payload["job_id"])
                return OperationResult(name=name, payload={"job": jobs.get(job_id)})
            if name == "arrange.create":
                job_id = str(payload["job_id"])
                if job_id in jobs:
                    return OperationResult(name=name, status="error", payload={"error": "already exists"})
                jobs[job_id] = dict(payload)
                return OperationResult(name=name, payload={"job": payload})
            raise AssertionError(f"unexpected operation: {name}")

    context = PluginContext(work_root=tmp_path, operation_catalog=Catalog())
    descriptor = {
        "node_id": "review",
        "deadline": "2026-01-01T00:00:05+00:00",
        "resume_token": "do-not-copy-this-token",
    }
    await workflow_operations._schedule_human_task_timeout(
        context,
        work_root=str(tmp_path),
        thread_id="thread-1",
        run_id="run-1",
        descriptor=descriptor,
    )
    await workflow_operations._schedule_human_task_timeout(
        context,
        work_root=str(tmp_path),
        thread_id="thread-1",
        run_id="run-1",
        descriptor=descriptor,
    )

    assert [name for name, _ in calls] == [
        "arrange.get",
        "arrange.create",
        "arrange.get",
    ]
    create_payload = calls[1][1]
    assert create_payload["job_id"] == "workflow_human_task_timeout:run-1:review"
    assert create_payload["payload"] == {
        "task_id": "run-1:review",
        "thread_id": "thread-1",
        "run_id": "run-1",
        "node_id": "review",
        "work_root": str(tmp_path.resolve()),
    }
    assert "do-not-copy-this-token" not in json.dumps(create_payload, ensure_ascii=False)
