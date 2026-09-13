from __future__ import annotations

from pathlib import Path

import pytest

from lamtools_core.app.operation_catalog import OperationRequest, OperationResult
from lamtools_core.llm import LLMRequest, LLMResponse, LLMStreamEvent, LLMToolCall
from lamtools_core.plugins.bundled.workflow.backend.operations import _execution_context
from lamtools_core.plugins.bundled.workflow.backend.runtime import (
    WorkflowDef,
    WorkflowExecutionContext,
    WorkflowNode,
    WorkflowPort,
    WorkflowRunner,
)
from lamtools_core.plugins.bundled.workflow.backend.tools import (
    workflow_tool_handlers,
    workflow_tool_specs,
)
from lamtools_core.tool.default_toolbox import build_core_toolbox
from lamtools_core.tool.sub_agent_runner import KernelSubAgentRunner


class _WorkflowToolLLM:
    def __init__(self, tool_name: str) -> None:
        self.tool_name = tool_name
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise AssertionError("the sub-agent runner should use streaming")

    async def stream(self, request: LLMRequest):
        self.requests.append(request)
        if len(self.requests) == 1:
            yield LLMStreamEvent(
                kind="done",
                tool_calls=[
                    LLMToolCall(
                        id="workflow-tool-call",
                        name=self.tool_name,
                        arguments={},
                    )
                ],
            )
            return
        yield LLMStreamEvent(kind="content_delta", content="workflow completed")
        yield LLMStreamEvent(kind="done")


@pytest.mark.asyncio
async def test_sub_agent_workflow_tool_preserves_execution_context(tmp_path: Path) -> None:
    """The production runner path must retain the parent context at the tool boundary."""
    workflow = WorkflowDef(name="probe")
    tool_name = workflow.effective_tool_name()
    captured: dict[str, object] = {}

    async def execute_operation(
        name: str, payload: dict[str, object], metadata: dict[str, object]
    ) -> OperationResult:
        captured["metadata"] = metadata
        captured["context"] = _execution_context(
            OperationRequest(name=name, payload=payload, metadata=metadata),
            None,
            str(tmp_path),
            "workflow-thread",
            "workflow-run",
        )
        return OperationResult(
            name=name,
            payload={"run": {"status": "completed", "output": "ok"}},
        )

    spec = workflow_tool_specs([workflow])[0]
    handlers = workflow_tool_handlers(
        [workflow], execute_operation, work_root=tmp_path
    )
    llm = _WorkflowToolLLM(tool_name)
    runner = KernelSubAgentRunner(
        work_root=tmp_path,
        llm_client=llm,
        model_id="test-model",
        approval_policy="auto_approve",
    )

    # KernelSubAgentRunner intentionally owns the normal toolbox assembly. A
    # plugin host can inject its enrolled workflow tools at that seam.
    def build_toolbox(disabled_tools: set[str], *, active_mode: str | None):
        return build_core_toolbox(
            work_root=tmp_path,
            approval_policy="auto_approve",
            disabled_tools=disabled_tools,
            active_mode=active_mode,
            plugin_tool_specs=[spec],
            plugin_tool_handlers=handlers,
        )

    runner._build_toolbox = build_toolbox  # type: ignore[method-assign]
    parent = WorkflowExecutionContext(
        parent_session_id="parent-session",
        parent_run_id="parent-run",
        parent_turn_id="parent-turn",
        parent_call_id="parent-call",
        cwd=str(tmp_path),
        attachments=["attachment-1"],
        runtime_snapshot={"snapshot": "runtime"},
        environment={"name": "test"},
        capabilities={"tools": [tool_name]},
        permissions={"run_command": False},
        trace_id="trace-1",
        lineage=("lineage-1",),
        workflow_stack=("outer-workflow",),
        depth=2,
        max_depth=7,
    )

    result = await runner.run(task="invoke workflow", agent="worker", execution_context=parent)

    assert result.succeeded is True
    context = captured["context"]
    assert isinstance(context, WorkflowExecutionContext)
    assert context.attachments == ["attachment-1"]
    assert context.runtime_snapshot == {"snapshot": "runtime"}
    assert context.environment == {"name": "test"}
    assert context.capabilities == {"tools": [tool_name]}
    assert context.permissions == {"run_command": False}
    assert context.lineage == ("lineage-1",)
    assert context.workflow_stack == ("outer-workflow",)

    operation_metadata = captured["metadata"]
    assert isinstance(operation_metadata, dict)
    nested = operation_metadata["execution_context"]
    assert isinstance(nested, dict)
    for key in (
        "attachments",
        "runtime_snapshot",
        "environment",
        "capabilities",
        "permissions",
        "lineage",
        "workflow_stack",
    ):
        assert nested[key] == operation_metadata[key]


@pytest.mark.asyncio
async def test_external_workflow_stack_cannot_claim_current_workflow(tmp_path: Path) -> None:
    workflow = WorkflowDef(
        name="same",
        id="workflow-same",
        nodes=[
            WorkflowNode(
                id="out",
                kind="content",
                ports=[WorkflowPort(name="value", direction="out", value="ok")],
            )
        ],
    )
    external = await WorkflowRunner().run(
        workflow,
        work_root=str(tmp_path),
        execution_context=WorkflowExecutionContext(
            workflow_stack=("workflow-same",),
        ),
    )
    assert external.status == "failed"
    assert "cycle" in external.error

    # An internal child context marks its already-entered target so the child
    # Runner does not append the same identity a second time.
    internal = WorkflowExecutionContext().enter_workflow("workflow-same")
    child = await WorkflowRunner().run(
        workflow,
        work_root=str(tmp_path),
        execution_context=internal,
    )
    assert child.status == "completed"
