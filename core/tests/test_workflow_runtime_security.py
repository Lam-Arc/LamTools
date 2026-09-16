from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from lamtools_core.plugins.bundled.workflow.backend.data_packet import WorkflowDataPacket
from lamtools_core.plugins.bundled.workflow.backend.credentials import CredentialRef
from lamtools_core.plugins.bundled.workflow.backend.registry import WorkflowNodeRegistry
from lamtools_core.plugins.bundled.workflow.backend.operations import _queue_item_payload
from lamtools_core.plugins.bundled.workflow.backend.queue import WorkflowQueueItem
from lamtools_core.plugins.bundled.workflow.backend.runtime import (
    WorkflowDef,
    WorkflowExecutionContext,
    WorkflowNode,
    WorkflowPort,
    WorkflowRunner,
    WorkflowNodeState,
    WorkflowRunResult,
)


def _node(kind: str, *, config: dict[str, Any] | None = None) -> WorkflowNode:
    return WorkflowNode(
        id="node",
        kind=kind,
        config=dict(config or {}),
        ports=[WorkflowPort(name="value", direction="in"), WorkflowPort(name="out", direction="out")],
    )


def _registry(executor: Any, *, capabilities: list[str] | None = None, resource_class: str = "default") -> WorkflowNodeRegistry:
    registry = WorkflowNodeRegistry()
    registry.register_plugin(
        "trusted.test",
        [{
            "name": "trusted.node",
            "input": {"required": {"value": {"type": "any"}}},
            "output": {"out": {"type": "any"}},
            "capabilities": capabilities or [],
            "resource_class": resource_class,
            "executor": executor,
        }],
        trusted=True,
    )
    return registry


class _Events:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def list(self, run_id: str) -> list[Any]:
        return [event for event in self.events if event.run_id == run_id]

    async def append(self, event: Any) -> None:
        self.events.append(event)


class _Snapshots:
    def __init__(self) -> None:
        self.values: list[dict[str, Any]] = []

    async def get_dict(self, thread_id: str, run_id: str) -> None:
        return None

    async def get(self, thread_id: str, run_id: str) -> None:
        return None

    async def save(self, thread_id: str, run_id: str, result: Any, **kwargs: Any) -> None:
        self.values.append(result.to_dict())

    async def delete(self, thread_id: str, run_id: str) -> None:
        return None


def test_public_run_and_queue_projections_remove_secrets_and_hidden_reasoning() -> None:
    state = WorkflowNodeState(
        node_id="agent",
        status="done",
        output={"answer": "safe", "access_token": "output-token"},
        attempts=1,
        audit={
            "tool_calls": [{"name": "web_search", "count": 2}],
            "model_rounds": 3,
            "reasoning": "hidden chain of thought",
            "thinking_content": "hidden thinking",
            "analysis": "hidden analysis",
        },
        attempt_history=[{
            "number": 1,
            "status": "completed",
            "api_key": "attempt-secret",
            "reasoning_content": "hidden attempt reasoning",
        }],
    )
    run = WorkflowRunResult(
        status="completed",
        output={"answer": "safe", "token": "result-token"},
        node_states={"agent": state},
        values={"agent.out": {"answer": "safe", "runtime_credentials": {"key": "secret"}}},
        run_id="run-safe",
    )
    item = WorkflowQueueItem(
        queue_id="queue-safe",
        workflow_id="workflow-safe",
        workflow_name="safe",
        run_id="run-safe",
        inputs={"prompt": "keep", "api_key": "input-secret"},
        prior_values={"upstream": {"access_token": "prior-token", "value": 42}},
        prior_node_states={
            "agent": WorkflowNodeState(
                node_id="agent", status="done",
                output={"value": 42, "token": "state-token"},
            )
        },
        result=run,
        metadata={
            "trace_id": "trace-safe",
            "runtime_credentials": {"provider": "metadata-secret"},
            "chainOfThought": "hidden metadata reasoning",
        },
    )

    public_run = run.to_public_dict()
    rpc_queue = _queue_item_payload(item)
    encoded_public = json.dumps({"run": public_run, "queue": rpc_queue})
    for secret in (
        "output-token", "attempt-secret", "result-token", "input-secret",
        "prior-token", "state-token", "metadata-secret", "hidden chain of thought",
        "hidden thinking", "hidden analysis", "hidden attempt reasoning",
        "hidden metadata reasoning",
    ):
        assert secret not in encoded_public
    assert rpc_queue["inputs"] == {"prompt": "keep"}
    assert rpc_queue["prior_values"] == {"upstream": {"value": 42}}
    assert rpc_queue["metadata"] == {"trace_id": "trace-safe"}
    assert rpc_queue["result"]["node_states"]["agent"]["audit"] == {
        "tool_calls": [{"name": "web_search", "count": 2}],
        "model_rounds": 3,
    }
    assert rpc_queue["status"] == "queued"
    assert rpc_queue["result"]["status"] == "completed"
    assert rpc_queue["result"]["output"] == {"answer": "safe"}

    # Persistence retains the original execution inputs; only the public/RPC
    # projection is filtered.
    stored = item.to_storage_dict()
    assert stored["inputs"]["api_key"] == "input-secret"
    assert stored["metadata"]["runtime_credentials"]["provider"] == "metadata-secret"


@pytest.mark.asyncio
async def test_credentials_are_node_local_and_never_persisted(tmp_path: Path) -> None:
    secret = "TOP-SECRET"
    observed: dict[str, Any] = {}

    class Resolver:
        async def resolve(self, credential: CredentialRef, *, context: Any = None) -> str:
            observed["resolver_context"] = context
            return secret

    class Executor:
        async def execute(self, node: Any, inputs: dict[str, Any], *, context: Any = None, packet: Any = None) -> dict[str, Any]:
            observed["context"] = context
            observed["config"] = node.config
            return {"out": {"value": secret}}

    ref = CredentialRef("production")
    node = _node("trusted.node", config={"credential": ref})
    context = WorkflowExecutionContext(cwd=str(tmp_path))
    events = _Events()
    snapshots = _Snapshots()
    runner = WorkflowRunner(
        node_registry=_registry(Executor()),
        credential_resolver=Resolver(),
        event_store=events,
        snapshot_store=snapshots,
    )
    result = await runner.run(
        WorkflowDef(name="secrets", nodes=[node]),
        execution_context=context,
        thread_id="thread",
        run_id="run",
        work_root=str(tmp_path),
    )

    assert result.status == "completed"
    assert observed["config"]["credential"] == secret
    assert observed["context"].runtime_credentials == {"production": secret}
    assert observed["context"] is not context
    assert context.runtime_credentials == {}
    assert "runtime_credentials" not in context.metadata()
    encoded_result = json.dumps(result.to_dict(), default=str)
    encoded_events = json.dumps([event.payload for event in events.events], default=str)
    encoded_snapshots = json.dumps(snapshots.values, default=str)
    assert secret not in encoded_result
    assert secret not in encoded_events
    assert secret not in encoded_snapshots
    assert node.config["credential"] == ref


@pytest.mark.asyncio
async def test_credential_reference_without_resolver_fails_closed(tmp_path: Path) -> None:
    runner = WorkflowRunner(node_registry=_registry(SimpleNamespace(execute=lambda **kwargs: {"out": "ok"})))
    result = await runner.run(
        WorkflowDef(name="missing-resolver", nodes=[_node("trusted.node", config={"credential": CredentialRef("missing")})]),
        work_root=str(tmp_path),
    )
    assert result.status == "failed"
    assert "credential resolver" in result.error


@pytest.mark.asyncio
async def test_capability_and_resource_declarations_require_host_grants(tmp_path: Path) -> None:
    calls: list[str] = []

    class Executor:
        async def execute(self, node: Any, inputs: dict[str, Any], *, context: Any = None) -> dict[str, Any]:
            calls.append("called")
            return {"out": "ok"}

    registry = _registry(Executor(), capabilities=["network"], resource_class="accelerated")
    workflow = WorkflowDef(name="gated", nodes=[_node("trusted.node", config={"value": "x"})])
    denied = await WorkflowRunner(node_registry=registry).run(
        workflow,
        work_root=str(tmp_path),
        execution_context=WorkflowExecutionContext(capabilities={"capabilities": ["network"]}),
    )
    assert denied.status == "failed"
    assert "resource class" in denied.error
    assert calls == []

    allowed = await WorkflowRunner(node_registry=registry).run(
        workflow,
        work_root=str(tmp_path),
        execution_context=WorkflowExecutionContext(
            capabilities={"capabilities": ["network"], "resources": {"accelerated": True}}
        ),
    )
    assert allowed.status == "completed"
    assert calls == ["called"]


@pytest.mark.asyncio
async def test_packet_view_preserves_lineage_and_legacy_inputs(tmp_path: Path) -> None:
    seen: dict[str, Any] = {}

    class Executor:
        async def execute(self, node: Any, inputs: dict[str, Any], *, packet: Any = None) -> dict[str, Any]:
            seen["inputs"] = inputs
            seen["packet"] = packet
            return packet

    packet = WorkflowDataPacket.from_dict({
        "format": "lamtools.workflow.data-packet",
        "version": 1,
        "items": [{"json": {"answer": 42}, "lineage": ["upstream"]}],
    })
    result = await WorkflowRunner(node_registry=_registry(Executor())).run(
        WorkflowDef(name="packet", nodes=[_node("trusted.node")]),
        inputs={"node.value": packet.to_dict()},
        work_root=str(tmp_path),
    )
    assert result.status == "completed"
    assert seen["inputs"]["value"] == packet.to_dict()
    assert seen["packet"].items[0].lineage == ("upstream",)
    assert result.output == {"answer": 42}


@pytest.mark.asyncio
async def test_custom_executor_without_packet_argument_keeps_legacy_boundary(tmp_path: Path) -> None:
    seen: dict[str, Any] = {}

    class LegacyExecutor:
        async def execute(self, node: Any, inputs: dict[str, Any], *, context: Any = None) -> dict[str, Any]:
            seen["inputs"] = inputs
            return {"out": inputs["value"]}

    result = await WorkflowRunner(node_registry=_registry(LegacyExecutor())).run(
        WorkflowDef(name="legacy", nodes=[_node("trusted.node")]),
        inputs={"node.value": "legacy-value"},
        work_root=str(tmp_path),
    )
    assert result.status == "completed"
    assert result.output == "legacy-value"
    assert seen["inputs"] == {"value": "legacy-value"}
