"""Tests for the workflow build tools (graph → add/connect/delete/update)."""

from __future__ import annotations

from typing import Any

import pytest

from lamtools_core.app.operation_catalog import OperationResult
from lamtools_core.tool import ToolCall, ToolResult
from lamtools_core.plugins.bundled.workflow.backend.build_tools import workflow_build_tool_handlers, workflow_build_tool_specs
from lamtools_core.plugins.bundled.workflow.backend.registry import WorkflowNodeRegistry


def _call(arguments: dict, *, session_id: str = "wf_news") -> ToolCall:
    return ToolCall(
        id="call-1",
        name="workflow_add_node",
        arguments=arguments,
        metadata={"_runtime_session_id": session_id},
    )


class FakeWorkflowOps:
    """In-memory workflow.get/create/update emulation keyed by name."""

    def __init__(self) -> None:
        self.workflows: dict[str, dict[str, Any]] = {}
        self.calls: list[tuple[str, dict]] = []

    async def __call__(self, operation: str, payload: dict, meta: dict) -> OperationResult:
        self.calls.append((operation, payload))
        name = str(payload.get("name") or "")
        if operation == "workflow.get":
            wf = self.workflows.get(name)
            if wf is None:
                return OperationResult(name=operation, payload={"error": f"Workflow not found: {name}"}, status="error")
            return OperationResult(name=operation, payload={"workflow": wf}, status="ok")
        if operation == "workflow.create":
            wf = {"name": name, "nodes": [], "edges": [], "description": ""}
            self.workflows[name] = wf
            return OperationResult(name=operation, payload={"workflow": wf}, status="ok")
        if operation == "workflow.update":
            self.workflows[name] = dict(payload)
            return OperationResult(name=operation, payload={"workflow": dict(payload)}, status="ok")
        raise AssertionError(f"unexpected operation {operation}")


@pytest.fixture
def handlers() -> tuple[dict[str, Any], FakeWorkflowOps]:
    ops = FakeWorkflowOps()
    return workflow_build_tool_handlers(ops), ops


class TestWorkflowBuildSpecs:
    def test_specs_cover_five_editing_tools(self):
        names = [s.name for s in workflow_build_tool_specs()]
        assert names == [
            "workflow_graph",
            "workflow_add_node",
            "workflow_connect",
            "workflow_delete_node",
            "workflow_update_node",
        ]

    def test_port_value_has_a_model_schema_type(self):
        specs = {spec.name: spec for spec in workflow_build_tool_specs()}
        for name in ("workflow_add_node", "workflow_update_node"):
            value = specs[name].input_schema["properties"]["ports"]["items"]["properties"]["value"]
            assert value["type"] == "string"

    def test_node_config_declares_runtime_fields(self):
        specs = {spec.name: spec for spec in workflow_build_tool_specs()}
        config = specs["workflow_add_node"].input_schema["properties"]["config"]
        assert {"command", "script", "instruction", "workflow_name"} <= set(config["properties"])

    def test_node_kind_catalog_comes_from_supplied_registry(self):
        registry = WorkflowNodeRegistry()
        registry.register_schema(
            {"name": "trusted_custom", "input": {}, "output": {}},
            plugin_id="trusted-plugin",
            trusted=True,
        )
        specs = {spec.name: spec for spec in workflow_build_tool_specs(registry)}
        kinds = specs["workflow_add_node"].input_schema["properties"]["kind"]["enum"]
        assert "model" in kinds
        assert "trusted_custom" in kinds
        assert {"ai", "script", "content", "transform", "branch"}.isdisjoint(kinds)


class TestWorkflowGraph:
    async def test_empty_graph_when_missing(self, handlers):
        tool, ops = handlers
        result = await tool["workflow_graph"](_call({}))
        assert result.status == "ok"
        assert result.metadata["operation_payload"]["nodes"] == []

    async def test_reads_existing_graph(self, handlers):
        tool, ops = handlers
        ops.workflows["news"] = {
            "name": "news",
            "nodes": [{
                "id": "n1",
                "kind": "command",
                "config": {"command": "echo ok"},
                "position": {"x": 12, "y": 34},
            }],
            "edges": [],
        }
        result = await tool["workflow_graph"](_call({}))
        assert result.status == "ok"
        node = result.metadata["operation_payload"]["nodes"][0]
        assert node["id"] == "n1"
        assert node["params"] == {"command": "echo ok"}
        assert node["position"] == {"x": 12, "y": 34}

    async def test_fails_without_workflow_session(self, handlers):
        tool, ops = handlers
        result = await tool["workflow_graph"](_call({}, session_id=""))
        assert result.status == "failed"
        assert "no active workflow" in result.error


class TestWorkflowAddNode:
    async def test_adds_node_and_bootstraps_workflow(self, handlers):
        tool, ops = handlers
        result = await tool["workflow_add_node"](_call({
            "kind": "script",
            "title": "抓取脚本",
            "node_id": "n-script-1",
        }))
        assert result.status == "ok"
        assert ops.workflows["news"]["nodes"][0]["id"] == "n-script-1"
        # script kind auto-scaffolds a starter script with port comments
        script = ops.workflows["news"]["nodes"][0]["config"]["script"]
        assert "# 输入：" in script
        assert "# 输出：" in script

    async def test_default_ports_for_command_kind(self, handlers):
        tool, ops = handlers
        await tool["workflow_add_node"](_call({"kind": "command", "node_id": "n-cmd"}))

    async def test_duplicate_node_id_fails(self, handlers):
        tool, ops = handlers
        ops.workflows["news"] = {"name": "news", "nodes": [{"id": "dup", "kind": "command"}], "edges": []}
        result = await tool["workflow_add_node"](_call({"node_id": "dup"}))
        assert result.status == "failed"
        assert "already exists" in result.error

    @pytest.mark.parametrize("kind", ["model", "agent"])
    async def test_model_nodes_inherit_the_editing_turn_model(self, handlers, kind):
        tool, ops = handlers
        call = _call({"kind": kind, "node_id": f"{kind}-node", "config": {"model_id": None}})
        call.metadata["runtime_snapshot"] = {"model_id": "deepseek-v4-flash"}

        result = await tool["workflow_add_node"](call)

        assert result.status == "ok"
        assert ops.workflows["news"]["nodes"][0]["config"]["model_id"] == "deepseek-v4-flash"

    async def test_explicit_model_selection_is_preserved(self, handlers):
        tool, ops = handlers
        call = _call({"kind": "model", "node_id": "model-node", "config": {"model_id": "chosen"}})
        call.metadata["runtime_snapshot"] = {"model_id": "fallback"}

        await tool["workflow_add_node"](call)

        assert ops.workflows["news"]["nodes"][0]["config"]["model_id"] == "chosen"

    async def test_output_node_gets_a_terminal_port_and_workflow_output(self, handlers):
        tool, ops = handlers

        result = await tool["workflow_add_node"](_call({
            "kind": "output",
            "node_id": "result",
            "ports": [{"name": "in", "type": "string", "direction": "in"}],
        }))

        assert result.status == "ok"
        output_ports = [
            port for port in ops.workflows["news"]["nodes"][0]["ports"]
            if port["direction"] == "out"
        ]
        assert output_ports[0]["name"] == "output"
        assert ops.workflows["news"]["output_port"] == "result.output"


class TestWorkflowConnect:
    async def test_connects_existing_nodes(self, handlers):
        tool, ops = handlers
        ops.workflows["news"] = {
            "name": "news",
            "nodes": [{"id": "a", "kind": "command"}, {"id": "b", "kind": "command"}],
            "edges": [],
        }
        result = await tool["workflow_connect"](_call({
            "source": "a", "source_port": "out", "target": "b", "target_port": "in",
        }))
        assert result.status == "ok"
        edges = ops.workflows["news"]["edges"]
        assert len(edges) == 1
        assert edges[0]["source"] == "a"
        assert edges[0]["target"] == "b"

    async def test_missing_node_fails(self, handlers):
        tool, ops = handlers
        ops.workflows["news"] = {"name": "news", "nodes": [{"id": "a", "kind": "command"}], "edges": []}
        result = await tool["workflow_connect"](_call({
            "source": "a", "source_port": "out", "target": "ghost", "target_port": "in",
        }))
        assert result.status == "failed"
        assert "not found" in result.error


class TestWorkflowDeleteNode:
    async def test_delete_removes_node_and_incident_edges(self, handlers):
        tool, ops = handlers
        ops.workflows["news"] = {
            "name": "news",
            "nodes": [{"id": "a", "kind": "command"}, {"id": "b", "kind": "command"}],
            "edges": [{"id": "e1", "source": "a", "target": "b"}],
        }
        result = await tool["workflow_delete_node"](_call({"node_id": "a"}))
        assert result.status == "ok"
        assert [n["id"] for n in ops.workflows["news"]["nodes"]] == ["b"]
        assert ops.workflows["news"]["edges"] == []


class TestWorkflowUpdateNode:
    async def test_updates_title_and_config(self, handlers):
        tool, ops = handlers
        ops.workflows["news"] = {
            "name": "news",
            "nodes": [{"id": "n1", "kind": "command", "title": "旧标题", "config": {}}],
            "edges": [],
        }
        result = await tool["workflow_update_node"](_call({
            "node_id": "n1",
            "title": "新标题",
            "config": {"command": "python run.py"},
        }))
        assert result.status == "ok"
        node = ops.workflows["news"]["nodes"][0]
        assert node["title"] == "新标题"
        assert node["config"]["command"] == "python run.py"

    async def test_missing_node_fails(self, handlers):
        tool, ops = handlers
        ops.workflows["news"] = {"name": "news", "nodes": [], "edges": []}
        result = await tool["workflow_update_node"](_call({"node_id": "nope", "title": "x"}))
        assert result.status == "failed"
        assert "not found" in result.error


def test_substitute_env_vars_no_prefix_collision():
    """$INPUT_A must not be rewritten inside $INPUT_ABC (audit 07 S4)."""
    from lamtools_core.plugins.bundled.workflow.backend.runtime import _substitute_env_vars

    result = _substitute_env_vars(
        "echo $INPUT_A $INPUT_ABC ${INPUT_A}x",
        {"INPUT_A": "VA", "INPUT_ABC": "VABC"},
    )
    assert result == "echo VA VABC VAx"


def test_substitute_env_vars_unknown_tokens_left_untouched():
    from lamtools_core.plugins.bundled.workflow.backend.runtime import _substitute_env_vars

    assert _substitute_env_vars("echo $UNKNOWN $KNOWN", {"KNOWN": "ok"}) == "echo $UNKNOWN ok"
    assert _substitute_env_vars("echo ${UNKNOWN}", {"KNOWN": "ok"}) == "echo ${UNKNOWN}"


def test_eval_condition_rejects_dunder_attribute_escape():
    """x.__class__ chains are blocked while benign method calls survive (audit 07 S4)."""
    from lamtools_core.plugins.bundled.workflow.backend.runtime import _eval_condition

    assert _eval_condition("len(text) > 3 and source == 'A'", {"text": "hello", "source": "A"}) is True
    assert _eval_condition("text.strip() == 'hi'", {"text": "  hi  "}) is True
    assert _eval_condition("text.__class__.__name__", {"text": "hi"}) is False
    assert _eval_condition("quality >= 0.8", {"quality": 0.9}) is True
