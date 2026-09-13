from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from lamtools_core.app.operation_catalog import OperationRequest
from lamtools_core.cli import build_parser
from lamtools_core.plugins.bundled.workflow.backend import cli as workflow_cli
from lamtools_core.plugins.bundled.workflow.backend import runtime as workflow_runtime
from lamtools_core.plugins.bundled.workflow.backend.durable import WorkflowRunEventStore
from lamtools_core.plugins.bundled.workflow.backend.operations import workflow_signal
from lamtools_core.plugins.bundled.workflow.backend.runtime import (
    WorkflowDef,
    WorkflowEdge,
    WorkflowNode,
    WorkflowPort,
    WorkflowRunner,
)
from lamtools_core.plugins.bundled.workflow.backend.snapshots import WorkflowSnapshotStore
from lamtools_core.plugins.context import PluginContext
from lamtools_core.plugins.registry import bundled_plugins_dir


def _wait_workflow(*, kind: str = "wait_event", timeout_seconds: float | None = None) -> WorkflowDef:
    config = {"event_type": "review.completed" if kind == "wait_event" else "approval"}
    if timeout_seconds is not None:
        config["timeout_seconds"] = timeout_seconds
    return WorkflowDef(
        id=f"wf-{kind}",
        name=kind,
        revision=4,
        nodes=[
            WorkflowNode(
                id="wait",
                kind=kind,
                config=config,
                ports=[WorkflowPort(name="result", direction="out", type="object")],
            ),
            WorkflowNode(
                id="after",
                kind="agent",
                config={"instruction": "continue"},
                ports=[
                    WorkflowPort(name="result", direction="in", type="object"),
                    WorkflowPort(name="answer", direction="out"),
                ],
            ),
        ],
        edges=[WorkflowEdge(id="wait-after", source="wait", source_port="result", target="after", target_port="result")],
        output_port="after.answer",
    )


@pytest.mark.asyncio
async def test_wait_pauses_without_blocking_and_signal_resumes_once(tmp_path: Path) -> None:
    calls = 0

    class AgentRunner:
        async def run(self, **kwargs):
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.03)
            return SimpleNamespace(message='{"answer":"continued"}')

    runner = WorkflowRunner(
        sub_agent_runner=AgentRunner(),
        snapshot_store=WorkflowSnapshotStore(root=tmp_path),
        event_store=WorkflowRunEventStore(root=tmp_path),
    )
    paused = await runner.run(
        _wait_workflow(), thread_id="thread-wait", run_id="run-wait"
    )
    assert paused.status == "paused"
    assert paused.node_states["wait"].status == "waiting"
    assert paused.wait_descriptor["event_type"] == "review.completed"
    assert calls == 0

    with pytest.raises(ValueError, match="resume token"):
        await runner.signal(
            thread_id="thread-wait", run_id="run-wait", resume_token="wrong",
            event_type="review.completed", payload={"id": 1},
        )
    with pytest.raises(ValueError, match="event type"):
        await runner.signal(
            thread_id="thread-wait", run_id="run-wait",
            resume_token=paused.wait_descriptor["resume_token"],
            event_type="wrong", payload={"id": 1},
        )

    completed, duplicate = await asyncio.gather(
        runner.signal(
            thread_id="thread-wait", run_id="run-wait",
            resume_token=paused.wait_descriptor["resume_token"],
            event_type="review.completed", payload={"id": 1},
        ),
        runner.signal(
            thread_id="thread-wait", run_id="run-wait",
            resume_token=paused.wait_descriptor["resume_token"],
            event_type="review.completed", payload={"id": 1},
        ),
    )
    assert completed.status == duplicate.status == "completed"
    assert completed.node_states["wait"].output == {
        "status": "received", "event_type": "review.completed", "payload": {"id": 1}
    }
    assert calls == 1
    assert runner._signal_locks == {}
    assert runner._signal_lock_users == {}
    assert workflow_runtime._PROCESS_SIGNAL_LOCKS == {}
    assert workflow_runtime._PROCESS_SIGNAL_LOCK_USERS == {}


@pytest.mark.asyncio
async def test_run_singleflight_cleans_locks_and_bounds_terminal_cache() -> None:
    calls = 0

    class AgentRunner:
        async def run(self, **kwargs):
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.02)
            return SimpleNamespace(message='{"answer":"once"}')

    workflow = WorkflowDef(
        id="wf-singleflight",
        name="singleflight",
        revision=1,
        nodes=[
            WorkflowNode(
                id="agent",
                kind="agent",
                config={"instruction": "once"},
                ports=[WorkflowPort(name="answer", direction="out")],
            )
        ],
    )
    runner = WorkflowRunner(sub_agent_runner=AgentRunner())
    runner._max_terminal_results = 2
    first, duplicate = await asyncio.gather(
        runner.run(workflow, thread_id="thread", run_id="run-1"),
        runner.run(workflow, thread_id="thread", run_id="run-1"),
    )
    assert first.to_dict() == duplicate.to_dict()
    assert calls == 1
    assert runner._run_locks == {}
    assert runner._run_lock_users == {}

    await runner.run(workflow, thread_id="thread", run_id="run-2")
    await runner.run(workflow, thread_id="thread", run_id="run-3")
    assert len(runner._terminal_results) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("decision", "expected"),
    [("approve", "approved"), ("reject", "rejected")],
)
async def test_approval_signal_returns_structured_decision(
    tmp_path: Path, decision: str, expected: str
) -> None:
    class AgentRunner:
        async def run(self, **kwargs):
            return SimpleNamespace(message='{"answer":"continued"}')

    runner = WorkflowRunner(
        sub_agent_runner=AgentRunner(),
        snapshot_store=WorkflowSnapshotStore(root=tmp_path / decision),
        event_store=WorkflowRunEventStore(root=tmp_path / decision),
    )
    paused = await runner.run(
        _wait_workflow(kind="approval"),
        thread_id=f"thread-{decision}", run_id=f"run-{decision}",
    )
    result = await runner.signal(
        thread_id=f"thread-{decision}", run_id=f"run-{decision}",
        resume_token=paused.wait_descriptor["resume_token"],
        event_type="approval", decision=decision, payload={"reviewer": "local-user"},
    )
    approval = result.node_states["wait"].output
    assert approval["status"] == expected
    assert approval["decision"] == decision
    assert approval["payload"] == {"reviewer": "local-user"}


@pytest.mark.asyncio
async def test_expired_wait_resumes_with_structured_timeout(tmp_path: Path) -> None:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def clock() -> datetime:
        return now

    class AgentRunner:
        async def run(self, **kwargs):
            return SimpleNamespace(message='{"answer":"continued"}')

    runner = WorkflowRunner(
        sub_agent_runner=AgentRunner(),
        snapshot_store=WorkflowSnapshotStore(root=tmp_path),
        event_store=WorkflowRunEventStore(root=tmp_path),
        clock=clock,
    )
    paused = await runner.run(
        _wait_workflow(timeout_seconds=5), thread_id="thread-timeout", run_id="run-timeout"
    )
    now += timedelta(seconds=6)
    result = await runner.signal(
        thread_id="thread-timeout", run_id="run-timeout",
        resume_token=paused.wait_descriptor["resume_token"],
        event_type="review.completed", payload={"late": True},
    )
    assert result.node_states["wait"].output == {
        "status": "timed_out", "event_type": "review.completed", "payload": None
    }


@pytest.mark.asyncio
async def test_workflow_signal_rpc_uses_durable_runner_contract(tmp_path: Path) -> None:
    class AgentRunner:
        async def run(self, **kwargs):
            return SimpleNamespace(message='{"answer":"continued"}')

    runner = WorkflowRunner(
        sub_agent_runner=AgentRunner(),
        snapshot_store=WorkflowSnapshotStore(root=tmp_path),
        event_store=WorkflowRunEventStore(root=tmp_path),
    )
    paused = await runner.run(
        _wait_workflow(), thread_id="rpc-thread", run_id="rpc-run"
    )
    context = PluginContext(
        work_root=tmp_path,
        data_dir=tmp_path / "data",
        services={"workflow": SimpleNamespace(runner=runner, queue=None)},
    )
    response = await workflow_signal(
        OperationRequest(
            name="workflow.signal",
            payload={
                "thread_id": "rpc-thread",
                "run_id": "rpc-run",
                "resume_token": paused.wait_descriptor["resume_token"],
                "event_type": "review.completed",
                "payload": {"source": "rpc"},
            },
        ),
        context=context,
    )
    assert response.status == "ok"
    assert response.payload["run"]["status"] == "completed"


@pytest.mark.asyncio
async def test_workflow_signal_cli_is_manifest_mounted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict]] = []

    class Client:
        async def request(self, method: str, payload: dict) -> dict:
            calls.append((method, payload))
            return {"run": {"status": "completed", "run_id": payload["run_id"]}}

    async def fake_invoke(args, operation):
        return await operation(Client())

    monkeypatch.setattr(workflow_cli, "_invoke_live", fake_invoke)
    parser = build_parser(
        plugin_roots=[bundled_plugins_dir()], plugin_state_path=tmp_path / "plugins.jsonc"
    )
    args = parser.parse_args(
        [
            "workflow", "signal", "thread-1", "run-1", "token-1", "approval",
            "--decision", "approve", "--payload", '{"reviewer":"me"}', "--raw",
        ]
    )
    assert await args.func(args) == 0
    assert calls == [
        (
            "workflow.signal",
            {
                "thread_id": "thread-1",
                "run_id": "run-1",
                "resume_token": "token-1",
                "event_type": "approval",
                "decision": "approve",
                "payload": {"reviewer": "me"},
            },
        )
    ]
