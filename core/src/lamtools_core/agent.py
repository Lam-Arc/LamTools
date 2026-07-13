"""Shared agent contracts.

Core owns generic delegation concepts. Product members decide when to invoke
them and what context to pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from lamtools_core.tool.permission import AUTO_ALLOW, PermissionTier

SUB_AGENT_NAME = "sub"
SUB_AGENT_TOOL_NAME = "sub_agent"


@dataclass(frozen=True)
class CoreAgentSpec:
    name: str
    tool_name: str
    description: str
    modes: tuple[str, ...] = ("auto", "low", "medium", "high")
    capabilities: tuple[str, ...] = ()
    permission: PermissionTier = AUTO_ALLOW
    max_depth: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)


SUB_AGENT_SPEC = CoreAgentSpec(
    name=SUB_AGENT_NAME,
    tool_name=SUB_AGENT_TOOL_NAME,
    description="Delegate one focused task to a reusable sub session controlled by the running agent.",
    capabilities=("delegated_reasoning", "bounded_tool_use", "focused_handoff"),
)


SUB_AGENT_TOOL_SPEC: dict[str, Any] = {
    "name": SUB_AGENT_TOOL_NAME,
    "description": SUB_AGENT_SPEC.description,
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "task": {"type": "string", "description": "Self-contained task for the sub-agent."},
            "agent": {
                "type": ["string", "null"],
                "description": "Stable sub-session name chosen by the running agent; leave null to use the default sub session.",
            },
        },
        "required": ["task", "agent"],
    },
    "permission": AUTO_ALLOW,
    "failure_modes": [{"type": "agent_failed", "message": "Agent execution failed"}],
    "recovery": "Simplify task description or provide a narrower delegated role.",
}


__all__ = [
    "CoreAgentSpec",
    "SUB_AGENT_NAME",
    "SUB_AGENT_TOOL_NAME",
    "SUB_AGENT_SPEC",
    "SUB_AGENT_TOOL_SPEC",
]
