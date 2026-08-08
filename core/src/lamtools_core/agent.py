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
            return self.error.strip()
        if self.decision == "wait":
            return "Sub-agent is waiting and did not produce a final response."
        if self.decision == "done":
            return "Sub-agent ended without a final response after tool use."
        return "Sub-agent failed without a final response."


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
            "task": {
                "type": "string",
                "description": (
                    "Self-contained complete task for the sub-agent, including every delegated "
                    "deliverable and required tool action. At minimum make clear the scope, goal "
                    "and output format; keep it bounded and non-overlapping with the main agent."
                ),
            },
            "agent": {
                "type": ["string", "null"],
                "description": (
                    "Stable sub-session name chosen by the running agent; leave null to use the "
                    "default sub session. Each name is a reusable session: follow-up calls with "
                    "the same name resume its conversation history."
                ),
            },
            "model": {
                "type": ["string", "null"],
                "description": (
                    "Optional model override for this sub-agent (model_id or display_name); leave "
                    "null/empty to follow the main agent's model. Specify only when the task "
                    "needs a different capability (e.g. stronger reasoning, longer context)."
                ),
            },
            "mode": {
                "type": ["string", "null"],
                "description": (
                    "Optional loadtools mode constraining this sub-agent's tools. Use \"consider\" "
                    "for read-only research (avoids accidental file changes), \"execute\" or "
                    "null/empty for full access, or any custom mode defined in loadtools.jsonc. "
                    "Leave null/empty when write/command access is required."
                ),
            },
            "attachments": {
                "type": ["array", "null"],
                "items": {"type": "string"},
                "description": (
                    "Optional list of attachment IDs to forward to the sub-agent (e.g. image, "
                    "audio, document attachments from the main session). The sub-agent receives "
                    "their content blocks directly — use this to delegate multimodal analysis "
                    "(images, etc.) to a sub-agent running a model that supports those input "
                    "types when the main agent's model does not."
                ),
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
    "SubAgentRunResult",
    "SUB_AGENT_NAME",
    "SUB_AGENT_TOOL_NAME",
    "SUB_AGENT_SPEC",
    "SUB_AGENT_TOOL_SPEC",
]
