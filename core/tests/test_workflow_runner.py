"""Safety-net coverage for the deterministic Workflow runner."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

from lamtools_core.plugins.bundled.workflow.backend.runtime import (
    WorkflowDef,
    WorkflowEdge,
    WorkflowNode,
    WorkflowPort,
    WorkflowRunner,
)
import lamtools_core.plugins.bundled.workflow.backend.runtime as workflow_runtime
import lamtools_core.tool.command_runner as command_runner
from lamtools_core.runtime import RuntimeTaskRegistry
from lamtools_core.tool.command_runner import CommandShell


def _node(
    node_id: str,
    kind: str,
    *,
    inputs: list[tuple[str, str]] = [],
    outputs: list[tuple[str, str, object | None]] = [],
    config: dict | None = None,
) -> WorkflowNode:
    ports = [
        WorkflowPort(name=name, type=type_name, direction="in")
        for name, type_name in inputs
    ]
    ports.extend(
        WorkflowPort(name=name, type=type_name, direction="out", value=value)
        for name, type_name, value in outputs
    )
    return WorkflowNode(
        id=node_id,
        kind=kind,  # type: ignore[arg-type]
        title=node_id,
        config=dict(config or {}),
        ports=ports,
    )


@pytest.mark.asyncio
async def test_workflow_wsl_forwards_only_explicit_env_and_inputs(monkeypatch, tmp_path: Path) -> None:
    shell = CommandShell(name="WSL", executable="wsl.exe", kind="wsl")
    captured: dict[str, object] = {}

    async def fake_create(argv, *, cwd, env):
        captured.update(argv=argv, cwd=cwd, env=env)

        class FakeProcess:
            returncode = 0

            async def communicate(self, _payload):
                return b"ok", b""

        return FakeProcess()

    monkeypatch.setattr(workflow_runtime.sys, "platform", "win32")
    monkeypatch.setattr(workflow_runtime, "_create_workflow_process", fake_create)
    monkeypatch.setattr(workflow_runtime, "_python3_shim_dir", lambda: pytest.fail("WSL must use Linux python3"))
    monkeypatch.setattr(command_runner, "resolve_command_shell", lambda: shell)
    monkeypatch.setenv("WSLENV", "KEEP/p:PATH/p")
    monkeypatch.setenv("UNRELATED_SECRET", "do-not-forward")

    result = await WorkflowRunner()._run_command(
        {
            "command": "printf '%s %s' $INPUT_QUERY $CUSTOM_TOKEN",
            "env": {"CUSTOM_TOKEN": "visible-value"},
        },
        {"query": "bound-value"},
        str(tmp_path),
    )

    assert result == "ok"
    argv = captured["argv"]
    assert isinstance(argv, list)
    assert argv[:3] == ["wsl.exe", "--cd", str(tmp_path)]
    assert argv[-1] == "printf '%s %s' bound-value $CUSTOM_TOKEN"
    env = captured["env"]
    assert isinstance(env, dict)
    wslenv_entries = env["WSLENV"].split(":")
    assert wslenv_entries[0] == "KEEP/p"
    assert wslenv_entries == ["KEEP/p", "CUSTOM_TOKEN", "INPUT_QUERY"]
    assert "UNRELATED_SECRET" not in env["WSLENV"]
    assert env["PATH"] == os.environ["PATH"]


def _edge(source: str, source_port: str, target: str, target_port: str) -> WorkflowEdge:
    return WorkflowEdge(
        id=f"{source}-{target}",
        source=source,
        source_port=source_port,
        target=target,
        target_port=target_port,
    )


@pytest.mark.asyncio
async def test_runner_executes_content_script_content_dag(tmp_path: Path) -> None:
    workflow = WorkflowDef(
        name="dag",
        nodes=[
            _node("source", "content", outputs=[("value", "number", 2)]),
            _node(
                "double",
                "script",
                inputs=[("x", "number")],
                outputs=[("y", "number", None)],
                config={"script": "y = x * 2"},
            ),
            _node(
                "sink",
                "content",
                inputs=[("y", "number")],
                outputs=[("result", "string", "done")],
            ),
        ],
        edges=[
            _edge("source", "value", "double", "x"),
            _edge("double", "y", "sink", "y"),
        ],
    )

    result = await WorkflowRunner().run(
        workflow,
        work_root=str(tmp_path),
        thread_id="runner-dag",
        run_id="run-dag",
    )

    assert result.status == "completed"
    assert [result.node_states[node_id].status for node_id in ("source", "double", "sink")] == [
        "done",
        "done",
        "done",
    ]
    assert result.values["source.value"] == 2
    assert result.values["double.y"] == 4
    assert result.output == "done"


@pytest.mark.asyncio
async def test_runner_records_script_failure_on_node(tmp_path: Path) -> None:
    workflow = WorkflowDef(
        name="failure",
        nodes=[
            _node(
                "broken",
                "script",
                outputs=[("out", "string", None)],
                config={"script": "raise RuntimeError('boom')"},
            )
        ],
    )

    result = await WorkflowRunner().run(workflow, work_root=str(tmp_path), run_id="run-failure")

    assert result.status == "failed"
    assert result.node_states["broken"].status == "error"
    assert "boom" in result.node_states["broken"].error


@pytest.mark.asyncio
async def test_runner_command_success_nonzero_and_timeout(tmp_path: Path, monkeypatch) -> None:
    if sys.platform == "win32":
        # Keep this POSIX fixture on the same shell used before the persisted
        # auto preference was introduced.
        monkeypatch.setenv("LAMTOOLS_COMMAND_SHELL", "git-bash")
        success_command = "printf ok"
        failure_command = "exit 7"
        timeout_command = "sleep 0.2"
    else:
        success_command = "printf ok"
        failure_command = "exit 7"
        timeout_command = "sleep 0.2"

    success = WorkflowDef(
        name="command-success",
        nodes=[_node("command", "command", outputs=[("out", "string", None)], config={"command": success_command})],
    )
    result = await WorkflowRunner().run(success, work_root=str(tmp_path), run_id="run-command-ok")
    assert result.status == "completed"
    assert result.output == "ok"

    failure = WorkflowDef(
        name="command-failure",
        nodes=[_node("command", "command", outputs=[("out", "string", None)], config={"command": failure_command})],
    )
    result = await WorkflowRunner().run(failure, work_root=str(tmp_path), run_id="run-command-fail")
    assert result.status == "failed"
    assert result.node_states["command"].status == "error"

    timeout = WorkflowDef(
        name="command-timeout",
        nodes=[
            _node(
                "command",
                "command",
                outputs=[("out", "string", None)],
                config={"command": timeout_command, "timeout": 0.02},
            )
        ],
    )
    result = await WorkflowRunner().run(timeout, work_root=str(tmp_path), run_id="run-command-timeout")
    assert result.status == "failed"
    assert "timed out" in result.node_states["command"].error


@pytest.mark.asyncio
async def test_runner_cancel_kills_command_and_returns_cancelled_node_state(tmp_path: Path, monkeypatch) -> None:
    """A cancelled command must not leave the workflow task or subprocess alive."""
    if sys.platform == "win32":
        monkeypatch.setenv("LAMTOOLS_COMMAND_SHELL", "git-bash")
    workflow = WorkflowDef(
        name="command-cancel",
        nodes=[
            _node(
                "command",
                "command",
                outputs=[("out", "string", None)],
                config={"command": "sleep 30"},
            ),
            _node(
                "after",
                "content",
                outputs=[("out", "string", "after")],
            ),
        ],
    )
    registry = RuntimeTaskRegistry()
    runner = WorkflowRunner(runtime_task_registry=registry)
    thread_id = "workflow-cancel-thread"
    run_id = "workflow-cancel-run"
    task = asyncio.create_task(
        runner.run(
            workflow,
            work_root=str(tmp_path),
            thread_id=thread_id,
            run_id=run_id,
        )
    )
    assert registry.accept_run(thread_id, run_id)
    assert registry.register(thread_id, task, run_id=run_id)
    try:
        await asyncio.sleep(0.15)
        registry.cancel(thread_id, run_id=run_id, force=True)
        result = await asyncio.wait_for(task, timeout=3.0)
    finally:
        await registry.shutdown()

    assert result.status == "cancelled"
    assert result.node_states["command"].status == "cancelled"
    assert result.node_states["after"].status == "cancelled"
    assert not runner._active_tasks
    assert not runner._active_runs


@pytest.mark.asyncio
async def test_runner_rejects_unknown_start_node(tmp_path: Path) -> None:
    workflow = WorkflowDef(name="start", nodes=[_node("only", "content", outputs=[("out", "string", "ok")])])

    result = await WorkflowRunner().run(
        workflow,
        work_root=str(tmp_path),
        start_node="missing",
        run_id="run-start",
    )

    assert result.status == "failed"
    assert "unknown node" in result.error


class _SubgraphStore:
    def __init__(self, definition: WorkflowDef) -> None:
        self.definition = definition

    async def get(self, name: str, *, work_root: str | None = None) -> WorkflowDef | None:
        del work_root
        return self.definition if name == self.definition.name else None


def _child_workflow() -> WorkflowDef:
    return WorkflowDef(
        name="child",
        nodes=[
            _node(
                "step",
                "script",
                inputs=[("x", "number")],
                outputs=[("y", "number", None)],
                config={"script": "y = x + 1"},
            )
        ],
    )


@pytest.mark.asyncio
async def test_runner_subgraph_propagates_child_output(tmp_path: Path) -> None:
    child = _child_workflow()
    parent = WorkflowDef(
        name="parent",
        nodes=[
            _node(
                "sub",
                "subgraph",
                inputs=[("value", "number")],
                outputs=[("out", "number", None)],
                config={"workflow_name": "child"},
            )
        ],
    )

    result = await WorkflowRunner(workflow_store=_SubgraphStore(child)).run(
        parent,
        inputs={"sub.value": 2},
        work_root=str(tmp_path),
        run_id="run-subgraph",
    )

    assert result.status == "completed"
    assert result.output == 3


@pytest.mark.asyncio
async def test_runner_subgraph_failure_aborts_parent(tmp_path: Path) -> None:
    child = WorkflowDef(
        name="broken-child",
        nodes=[
            _node(
                "broken",
                "script",
                outputs=[("out", "string", None)],
                config={"script": "raise RuntimeError('child boom')"},
            )
        ],
    )
    parent = WorkflowDef(
        name="parent-with-broken-child",
        nodes=[
            _node(
                "sub",
                "subgraph",
                outputs=[("out", "string", None)],
                config={"workflow_name": child.name},
            )
        ],
    )

    result = await WorkflowRunner(workflow_store=_SubgraphStore(child)).run(
        parent,
        work_root=str(tmp_path),
        run_id="run-subgraph-failure",
    )

    assert result.status == "failed"
    assert result.node_states["sub"].status == "error"
    assert "broken-child" in result.node_states["sub"].error
    assert "child boom" in result.error


@pytest.mark.asyncio
async def test_runner_events_carry_complete_workflow_envelope(tmp_path: Path) -> None:
    events = []

    async def emit(event) -> None:
        events.append(event)

    workflow = WorkflowDef(
        name="event-envelope",
        nodes=[_node("step", "content", outputs=[("out", "string", "ok")])],
    )
    result = await WorkflowRunner(emit=emit).run(
        workflow,
        work_root=str(tmp_path),
        thread_id="workflow:event-thread",
        run_id="event-run",
    )

    assert result.status == "completed"
    assert events
    assert {event.payload["status"] for event in events} == {"running", "completed"}
    for event in events:
        assert event.source == "plugin:workflow"
        assert event.thread_id == "workflow:event-thread"
        assert event.run_id == "event-run"
        assert event.turn_id == "event-run"
        assert event.item_id == "step"
        assert event.payload["plugin_id"] == "workflow"
        assert event.payload["workflow_id"] == workflow.id
        assert event.payload["run_id"] == "event-run"
        assert event.payload["node_id"] == "step"
        assert event.metadata == {
            "plugin_id": "workflow",
            "workflow_id": workflow.id,
            "run_id": "event-run",
            "node_id": "step",
        }


@pytest.mark.asyncio
async def test_runner_loop_feeds_output_into_next_iteration(tmp_path: Path) -> None:
    child = _child_workflow()
    parent = WorkflowDef(
        name="loop-parent",
        nodes=[
            _node(
                "loop",
                "subgraph",
                inputs=[("value", "number")],
                outputs=[("out", "number", None)],
                config={
                    "workflow_name": "child",
                    "iterate": "loop",
                    "condition": "value >= 3",
                    "max_iterations": 5,
                },
            )
        ],
    )

    result = await WorkflowRunner(workflow_store=_SubgraphStore(child)).run(
        parent,
        inputs={"loop.value": 0},
        work_root=str(tmp_path),
        run_id="run-loop",
    )

    assert result.status == "completed"
    assert result.output == 3
