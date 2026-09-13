"""Runtime integration tests for versioned Workflow expression ASTs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lamtools_core.plugins.bundled.workflow.backend.expressions import (
    EXPRESSION_SCHEMA,
    EXPRESSION_VERSION,
)
from lamtools_core.plugins.bundled.workflow.backend.runtime import (
    SKIP_SENTINEL,
    WorkflowDef,
    WorkflowEdge,
    WorkflowExecutionContext,
    WorkflowNode,
    WorkflowPort,
    WorkflowRunner,
)


def _literal(value: object) -> dict[str, object]:
    return {"type": "literal", "value": value}


def _path(root: str, *segments: str | int) -> dict[str, object]:
    return {"type": "path", "root": root, "segments": list(segments)}


def _content(node_id: str, value: object, *, inputs: list[str] = []) -> WorkflowNode:
    ports = [WorkflowPort(name=name, direction="in") for name in inputs]
    ports.append(WorkflowPort(name="value", direction="out", value=value))
    return WorkflowNode(id=node_id, kind="content", ports=ports)


@pytest.mark.asyncio
async def test_template_node_evaluates_ast_with_input_item_node_and_env_roots(tmp_path: Path) -> None:
    template = {
        "type": "template",
        "parts": [
            {"text": "Hello "},
            {"expr": _path("input", "name")},
            {"text": " from "},
            {"expr": _path("node", "kind")},
            {"text": " / "},
            {"expr": _path("env", "GREETING")},
        ],
    }
    workflow = WorkflowDef(
        name="expression-template",
        nodes=[
            _content("source", "Ada"),
            WorkflowNode(
                id="template",
                kind="template",
                config={"template": template},
                ports=[WorkflowPort(name="name", direction="in"), WorkflowPort(name="text", direction="out")],
            ),
        ],
        edges=[WorkflowEdge(id="edge", source="source", source_port="value", target="template", target_port="name")],
        output_port="template.text",
    )
    result = await WorkflowRunner().run(
        workflow,
        work_root=str(tmp_path),
        execution_context=WorkflowExecutionContext(environment={"GREETING": "welcome", "API_TOKEN": "must-not-pass"}),
    )
    assert result.status == "completed", result.error
    assert result.output == "Hello Ada from template / welcome"


@pytest.mark.asyncio
async def test_condition_ast_routes_without_invoking_legacy_python_fallback(tmp_path: Path) -> None:
    condition = {
        "type": "binary",
        "op": "==",
        "left": _path("input", "value"),
        "right": _literal("Ada"),
    }
    workflow = WorkflowDef(
        name="expression-condition",
        nodes=[
            _content("source", "Ada"),
            WorkflowNode(
                id="branch",
                kind="condition",
                config={"expression": condition},
                ports=[
                    WorkflowPort(name="value", direction="in"),
                    WorkflowPort(name="true", direction="out"),
                    WorkflowPort(name="false", direction="out"),
                ],
            ),
        ],
        edges=[WorkflowEdge(id="edge", source="source", source_port="value", target="branch", target_port="value")],
    )
    result = await WorkflowRunner().run(workflow, work_root=str(tmp_path))
    assert result.status == "completed", result.error
    assert result.values["branch.true"] == "Ada"
    assert result.values["branch.false"] == SKIP_SENTINEL


@pytest.mark.asyncio
async def test_edge_condition_and_transform_ast_use_source_input_and_item_value(tmp_path: Path) -> None:
    condition = _path("input", "enabled")
    transform = _path("item", "name")
    source = _content("source", {"name": "Ada"}, inputs=["enabled"])
    sink = WorkflowNode(
        id="sink",
        kind="template",
        config={"template": _path("input", "name")},
        ports=[WorkflowPort(name="name", direction="in"), WorkflowPort(name="text", direction="out")],
    )
    edge = WorkflowEdge(
        id="edge",
        source="source",
        source_port="value",
        target="sink",
        target_port="name",
        condition=condition,
        transform=transform,
    )
    # The wire model must retain structured values; this was previously
    # coerced to text by WorkflowEdge.from_dict.
    round_tripped = WorkflowEdge.from_dict(edge.to_dict())
    assert round_tripped.condition == condition
    assert round_tripped.transform == transform
    workflow = WorkflowDef(name="expression-edge", nodes=[source, sink], edges=[round_tripped], output_port="sink.text")
    result = await WorkflowRunner().run(workflow, inputs={"source.enabled": True}, work_root=str(tmp_path))
    assert result.status == "completed", result.error
    assert result.output == "Ada"


@pytest.mark.asyncio
async def test_expression_error_is_exposed_as_structured_failed_node_state(tmp_path: Path) -> None:
    workflow = WorkflowDef(
        name="expression-error",
        nodes=[
            WorkflowNode(
                id="template",
                kind="template",
                config={"template": _path("input", "password")},
                ports=[WorkflowPort(name="text", direction="out")],
            )
        ],
        output_port="template.text",
    )
    result = await WorkflowRunner().run(workflow, work_root=str(tmp_path))
    assert result.status == "failed"
    assert result.node_states["template"].status == "error"
    error = json.loads(result.node_states["template"].error)
    assert error["schema"] == "lamtools.workflow.expression-error"
    assert error["code"] == "forbidden_path"
    assert error["stage"] == "validate"


@pytest.mark.asyncio
async def test_edge_expression_error_fails_target_node_with_structured_error(tmp_path: Path) -> None:
    source = _content("source", "Ada")
    target = WorkflowNode(
        id="target",
        kind="template",
        config={"template": "{{ value }}"},
        ports=[WorkflowPort(name="value", direction="in"), WorkflowPort(name="text", direction="out")],
    )
    edge = WorkflowEdge(
        id="edge",
        source="source",
        source_port="value",
        target="target",
        target_port="value",
        condition=_path("input", "password"),
    )
    result = await WorkflowRunner().run(
        WorkflowDef(name="edge-expression-error", nodes=[source, target], edges=[edge]),
        work_root=str(tmp_path),
    )
    assert result.status == "failed"
    assert result.node_states["target"].status == "error"
    assert json.loads(result.error)["code"] == "forbidden_path"


def test_expression_envelope_metadata_is_stable() -> None:
    assert EXPRESSION_SCHEMA == "lamtools.workflow.expression"
    assert EXPRESSION_VERSION == 1
