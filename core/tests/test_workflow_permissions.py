"""Workflow command/script nodes must use the host permission boundary."""

from __future__ import annotations

from pathlib import Path

import pytest

from lamtools_core.plugins.bundled.workflow.backend.runtime import (
    WorkflowDef,
    WorkflowNode,
    WorkflowPort,
    WorkflowRunner,
)


class DenyWorkflowExecution:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def check(self, tool_name: str, payload: dict) -> dict:
        self.calls.append((tool_name, payload))
        return {
            "allowed": False,
            "blocked": False,
            "requires_approval": True,
            "reason": "user approval required",
        }


def _node(node_id: str, kind: str, config: dict) -> WorkflowNode:
    return WorkflowNode(
        id=node_id,
        kind=kind,  # type: ignore[arg-type]
        ports=[WorkflowPort(name="out", type="string", direction="out")],
        config=config,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "config"),
    [
        ("command", {"command": "printf should-not-run"}),
        ("script", {"script": "out = 'should-not-run'"}),
    ],
)
async def test_workflow_execution_nodes_are_denied_by_permission_service(
    tmp_path: Path, kind: str, config: dict
) -> None:
    permission = DenyWorkflowExecution()
    workflow = WorkflowDef(name=f"deny-{kind}", nodes=[_node(kind, kind, config)])

    result = await WorkflowRunner(permission_service=permission).run(
        workflow,
        work_root=str(tmp_path),
        run_id=f"run-{kind}",
    )

    assert result.status == "failed"
    assert result.node_states[kind].status == "error"
    assert "approval required" in result.node_states[kind].error
    assert len(permission.calls) == 1
    tool_name, payload = permission.calls[0]
    assert tool_name == "run_command"
    assert payload["source"] == "workflow"
    assert payload["work_root"] == str(tmp_path)
    assert payload["node_id"] == kind
    assert payload["node_kind"] == kind
