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
SUB_AGENT_MESSAGE_TOOL_NAME = "sub_agent_message"
SUB_AGENT_CHILD_MESSAGE_TOOL_NAME = "message"


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


@dataclass(frozen=True)
class SubAgentRunResult:
    session_id: str
    run_id: str
    decision: str
    model_id: str = ""
    message: str = ""
    error: str = ""
    tool_call_count: int = 0
    ended_with_final_response: bool = False
    pending_approval: dict[str, Any] = field(default_factory=dict)
    pending_waiting_request: dict[str, Any] = field(default_factory=dict)
    # Diagnostics forwarded to the parent agent on failure so it can make an
    # informed decision (retry with different wording, take over, etc.).
    model_rounds: int = 0  # total model call rounds (= len(kernel steps))
    tool_call_breakdown: dict[str, int] = field(default_factory=dict)  # {tool_name: count}
    death_scene: str = ""  # last model round: reply + tools called + statuses

    @property
    def succeeded(self) -> bool:
        return (
            self.decision == "done"
            and bool(self.message.strip())
            and self.ended_with_final_response
            and not self.error
        )

    def failure_message(self) -> str:
        if self.error.strip():
            message = self.error.strip()
        elif self.decision == "wait":
            message = "Sub-agent is waiting and did not produce a final response."
        elif self.decision == "done":
            message = "Sub-agent ended without a final response after tool use."
        else:
            message = "Sub-agent failed without a final response."
        # Attach the death scene (last model round: reply + tool statuses) so
        # the parent agent sees *why* the sub-agent failed, not just that it did.
        if self.death_scene:
            return f"{message}\n\n{self.death_scene}"
        return message


SUB_AGENT_SPEC = CoreAgentSpec(
    name=SUB_AGENT_NAME,
    tool_name=SUB_AGENT_TOOL_NAME,
    description="Delegate one focused task to a reusable sub session controlled by the running agent.",
    capabilities=("delegated_reasoning", "bounded_tool_use", "focused_handoff"),
)


SUB_AGENT_TOOL_SPEC: dict[str, Any] = {
    "name": SUB_AGENT_TOOL_NAME,
    "description": "Create or close one reusable, non-blocking sub-agent.",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "action": {"type": "string", "enum": ["create", "close"]},
            "type": {"type": "string", "enum": ["consider", "execute"]},
            "name": {"type": "string", "pattern": "^[a-z][a-z0-9_]{0,63}$"},
            "model": {
                "type": "string",
                "description": "Exact model_id or a unique exact display_name.",
            },
            "reasoning_level": {
                "type": "string",
                "enum": ["off", "light", "medium", "Medium", "high", "xhigh", "xh", "max"],
            },
        },
        "required": ["action", "type", "name", "model", "reasoning_level"],
    },
    "permission": AUTO_ALLOW,
    "failure_modes": [{"type": "agent_failed", "message": "Agent execution failed"}],
    "recovery": "Simplify task description or provide a narrower delegated role.",
}

SUB_AGENT_MESSAGE_TOOL_SPEC: dict[str, Any] = {
    "name": SUB_AGENT_MESSAGE_TOOL_NAME,
    "description": "Send guidance to an active reusable sub-agent without blocking.",
    "input_schema": {
        "type": "object", "additionalProperties": False,
        "properties": {
            "type": {"type": "string", "enum": ["consider", "execute"]},
            "name": {"type": "string", "pattern": "^[a-z][a-z0-9_]{0,63}$"},
            "prompt": {"type": "string", "minLength": 1},
        },
        "required": ["type", "name", "prompt"],
    },
    "permission": AUTO_ALLOW,
}

SUB_AGENT_CHILD_MESSAGE_TOOL_SPEC: dict[str, Any] = {
    "name": SUB_AGENT_CHILD_MESSAGE_TOOL_NAME,
    "description": "Send a persistent message to the parent agent.",
    "input_schema": {
        "type": "object", "additionalProperties": False,
        "properties": {"message": {"type": "string", "minLength": 1}},
        "required": ["message"],
    },
    "permission": AUTO_ALLOW,
}


__all__ = [
    "CoreAgentSpec",
    "SubAgentRunResult",
    "SUB_AGENT_NAME",
    "SUB_AGENT_TOOL_NAME",
    "SUB_AGENT_MESSAGE_TOOL_NAME",
    "SUB_AGENT_CHILD_MESSAGE_TOOL_NAME",
    "SUB_AGENT_SPEC",
    "SUB_AGENT_TOOL_SPEC",
    "SUB_AGENT_MESSAGE_TOOL_SPEC",
    "SUB_AGENT_CHILD_MESSAGE_TOOL_SPEC",
]
