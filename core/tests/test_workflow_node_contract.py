"""Acceptance contracts for the open, schema-driven workflow node system.

These tests intentionally exercise public registry, document, runner and
operation surfaces.  They are kept separate from the older five-node tests so
compatibility coverage can remain explicit while the catalog grows.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from lamtools_core.app.base_agent import build_core_plugin_operation_catalog
from lamtools_core.app.operation_catalog import OperationRequest
from lamtools_core.plugins.bundled.workflow.backend.document import (
    document_from_workflow_def,
    export_comfyui,
    import_comfyui,
    workflow_def_from_document,
)
from lamtools_core.plugins.bundled.workflow.backend.executors import WorkflowExecutorRegistry
from lamtools_core.plugins.bundled.workflow.backend.registry import WorkflowNodeRegistry
from lamtools_core.plugins.bundled.workflow.backend.runtime import (
    WorkflowDef,
    WorkflowExecutionContext,
    WorkflowNode,
    WorkflowPort,
    WorkflowRunner,
)
from lamtools_core.plugins.context import PluginContext
from lamtools_core.plugins.registry import bundled_plugins_dir


def _node(
    node_id: str,
    kind: str,
    *,
    config: dict[str, Any] | None = None,
    inputs: tuple[str, ...] = (),
    outputs: tuple[str, ...] = ("out",),
) -> WorkflowNode:
    return WorkflowNode(
        id=node_id,
        kind=kind,
        title=node_id,
        config=dict(config or {}),
        ports=[
            *[WorkflowPort(name=name, type="any", direction="in") for name in inputs],
            *[WorkflowPort(name=name, type="any", direction="out") for name in outputs],
        ],
    )


def test_object_info_exposes_open_catalog_and_marks_legacy_aliases() -> None:
    registry = WorkflowNodeRegistry()
    info = registry.object_info()
    assert {
        "model", "agent", "command", "python", "constant", "input", "output",
        "template", "condition", "merge", "join", "subgraph",
    } <= set(info)
    assert {"ai", "script", "content"} <= set(info)
    assert info["model"]["executor"] == "model"
    assert info["agent"]["executor"] == "agent"
    assert info["model"]["category"] == "workflow/model"
    assert info["agent"]["category"] == "workflow/agent"
    # Legacy names remain queryable for old documents, but should not be
    # offered as the default add-node choices by a schema-driven catalog.
    for legacy in ("ai", "script", "content"):
        assert info[legacy].get("legacy") is True
        assert info[legacy].get("hidden") is True


@pytest.mark.asyncio
async def test_model_and_agent_nodes_use_independent_public_invokers(tmp_path: Path) -> None:
    calls: list[tuple[str, Any]] = []

    class Model:
        async def invoke(self, request: Any, **kwargs: Any) -> Any:
            calls.append(("model", kwargs.get("context")))
            return SimpleNamespace(content="model-result")

    class Agent:
        async def run(self, **kwargs: Any) -> Any:
            calls.append(("agent", kwargs.get("execution_context")))
            return SimpleNamespace(message="agent-result")

    runner = WorkflowRunner(model_invoker=Model(), agent_invoker=Agent())
    model_result = await runner.run(
        WorkflowDef(name="model", nodes=[_node("m", "model", config={"instruction": "one"})]),
        work_root=str(tmp_path), run_id="model-run",
    )
    agent_result = await runner.run(
        WorkflowDef(name="agent", nodes=[_node("a", "agent", config={"instruction": "two"})]),
        work_root=str(tmp_path), run_id="agent-run",
    )
    assert model_result.status == "completed"
    assert model_result.output == "model-result"
    assert agent_result.status == "completed"
    assert agent_result.output == "agent-result"
    assert [kind for kind, _ in calls] == ["model", "agent"]


@pytest.mark.asyncio
async def test_model_and_agent_nodes_inherit_run_model(tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    class Model:
        async def invoke(self, request: Any, **kwargs: Any) -> Any:
            captured["model"] = request.model
            return SimpleNamespace(content="model-result")

    class Agent:
        async def run(self, **kwargs: Any) -> Any:
            captured["agent"] = kwargs.get("model", "")
            return SimpleNamespace(message="agent-result")

    context = WorkflowExecutionContext(event_metadata={"model_id": "session-model"})
    runner = WorkflowRunner(model_invoker=Model(), agent_invoker=Agent())
    await runner.run(
        WorkflowDef(name="model", nodes=[_node("m", "model", config={"instruction": "one"})]),
        work_root=str(tmp_path), run_id="model-run", execution_context=context,
    )
    await runner.run(
        WorkflowDef(name="agent", nodes=[_node("a", "agent", config={"instruction": "two"})]),
        work_root=str(tmp_path), run_id="agent-run", execution_context=context,
    )

    assert captured == {"model": "session-model", "agent": "session-model"}


@pytest.mark.asyncio
async def test_legacy_ai_modes_still_route_to_model_and_agent(tmp_path: Path) -> None:
    calls: list[str] = []

    class Model:
        async def invoke(self, request: Any, **kwargs: Any) -> Any:
            calls.append("model")
            return SimpleNamespace(content="legacy-model")

    class Agent:
        async def run(self, **kwargs: Any) -> Any:
            calls.append("agent")
            return SimpleNamespace(message="legacy-agent")

    runner = WorkflowRunner(model_invoker=Model(), agent_invoker=Agent())
    for mode, expected in (("single", "legacy-model"), ("agent", "legacy-agent")):
        result = await runner.run(
            WorkflowDef(
                name=f"legacy-{mode}",
                nodes=[_node("legacy", "ai", config={"mode": mode, "instruction": "old"})],
            ),
            work_root=str(tmp_path), run_id=f"legacy-{mode}",
        )
        assert result.status == "completed"
        assert result.output == expected
    assert calls == ["model", "agent"]


@pytest.mark.asyncio
async def test_legacy_script_and_content_aliases_remain_executable(tmp_path: Path) -> None:
    script = WorkflowDef(
        name="legacy-script",
        nodes=[_node("script", "script", config={"script": "out = 'legacy-script'"})],
    )
    content = WorkflowDef(
        name="legacy-content",
        nodes=[WorkflowNode(
            id="content",
            kind="content",
            ports=[WorkflowPort(name="out", direction="out", value="legacy-content")],
        )],
    )
    script_result = await WorkflowRunner().run(script, work_root=str(tmp_path), run_id="legacy-script")
    content_result = await WorkflowRunner().run(content, work_root=str(tmp_path), run_id="legacy-content")
    assert script_result.status == "completed"
    assert script_result.output == "legacy-script"
    assert content_result.status == "completed"
    assert content_result.output == "legacy-content"


@pytest.mark.asyncio
async def test_trusted_dynamic_node_executes_and_schema_only_node_is_rejected(tmp_path: Path) -> None:
    registry = WorkflowNodeRegistry()
    awaitable_calls: list[dict[str, Any]] = []

    class Echo:
        async def execute(self, node: Any, inputs: dict[str, Any], *, context: Any = None) -> dict[str, Any]:
            awaitable_calls.append({"node": node.id, "context": context})
            return {"out": inputs["value"]}

    registry.register_plugin(
        "trusted-plugin",
        [{
            "name": "vendor.echo",
            "display_name": "Vendor Echo",
            "category": "vendor/test",
            "input": {"required": {"value": {"type": "any"}}},
            "output": {"out": {"type": "any"}},
            "executor": Echo(),
        }],
        trusted=True,
    )
    runner = WorkflowRunner(
        node_registry=registry,
        executor_registry=WorkflowExecutorRegistry(registry),
    )
    dynamic = WorkflowDef(name="dynamic", nodes=[_node("echo", "vendor.echo", inputs=("value",))])
    dynamic_result = await runner.run(dynamic, inputs={"echo.value": "ok"}, work_root=str(tmp_path))
    assert dynamic_result.status == "completed"
    assert dynamic_result.output == "ok"
    assert awaitable_calls and awaitable_calls[0]["node"] == "echo"

    schema_only = WorkflowNodeRegistry()
    schema_only.register_schema(
        {"name": "vendor.schema_only", "input": {}, "output": {"out": {"type": "any"}}},
        plugin_id="trusted-plugin", trusted=True,
    )
    rejected = await WorkflowRunner(node_registry=schema_only).run(
        WorkflowDef(name="schema-only", nodes=[_node("foreign", "vendor.schema_only")]),
        work_root=str(tmp_path),
    )
    assert rejected.status == "failed"
    assert "executor" in rejected.error


def test_model_and_agent_type_ids_round_trip_through_v2_and_comfyui() -> None:
    definition = WorkflowDef(
        name="split",
        nodes=[
            _node("model", "model", config={"instruction": "m"}),
            _node("agent", "agent", config={"instruction": "a"}),
        ],
    )
    document = document_from_workflow_def(definition)
    restored = workflow_def_from_document(document)
    assert [node.kind for node in restored.nodes] == ["model", "agent"]
    for version in ("0.4", "1"):
        imported = import_comfyui(export_comfyui(document, version=version), name="split")
        assert [node["type"]["id"] for node in imported["graph"]["nodes"]] == ["model", "agent"]
        assert all(node["execution"]["schema_only"] is False for node in imported["graph"]["nodes"])


@pytest.mark.asyncio
async def test_object_info_operation_matches_registry_and_cli_surface(tmp_path: Path) -> None:
    context = PluginContext(
        work_root=tmp_path,
        data_dir=tmp_path / "data",
        services={"workflow_store": object()},
    )
    # The operation reads the runtime's node registry; use the same public
    # runtime wiring as the host rather than calling a private helper.
    catalog = build_core_plugin_operation_catalog(
        data_dir=tmp_path / "data",
        work_root=tmp_path,
        plugin_roots=[bundled_plugins_dir()],
        context=context,
    )
    # Registry mounting is host-owned; this assertion only requires that the
    # manifest operation is present and returns the same schema envelope.
    assert catalog.has("workflow.object_info")
    result = await catalog.execute("workflow.object_info", {})
    assert result.status == "ok"
    info = result.payload.get("object_info") or result.payload.get("node_types")
    assert isinstance(info, dict)
    assert {"model", "agent", "command", "content", "subgraph"} <= set(info)
