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
            "model": {"type": ["string", "null"], "description": "Optional model override chosen by the running agent."},
            "expected_output": {
                "type": ["string", "null"],
                "description": "Concrete output expected from the sub session.",
            },
        },
        "required": ["task", "agent", "model", "expected_output"],
    },
    "permission": AUTO_ALLOW,
    "failure_modes": [{"type": "agent_failed", "message": "Agent execution failed"}],
    "recovery": "Simplify task description or provide a narrower delegated role.",
}


def build_sub_agent_prompt(
    *,
    member_name: str,
    agent_name: str = "",
    role: str,
    task: str,
    expected_output: str,
    context: Any,
    tools: tuple[str, ...] | list[str] = (),
    tool_policy: str = "",
    developer_instructions: str = "",
) -> str:
    available_tools = ", ".join(str(item) for item in tools if str(item).strip()) or "无"
    policy = tool_policy.strip() or "只能调用列出的工具；未列出的工具不可用。"
    agent_line = f"Agent：{agent_name}\n" if agent_name.strip() else ""
    instruction_block = (
        f"专用指令：\n{developer_instructions.strip()}\n"
        if developer_instructions.strip()
        else ""
    )
    return (
        f"你是 {member_name} 派出的临时 SubAgent，不是固定产品角色。\n"
        f"{agent_line}"
        "你没有继承主 Agent 的完整对话历史；只使用下面的任务包和你自己读取到的事实。\n"
        "只围绕委派任务工作；不要扩大任务范围，不要替主 Agent 做最终验收。\n"
        f"可用工具：{available_tools}\n"
        f"权限规则：{policy}\n"
        f"{instruction_block}"
        "需要事实依据时优先调用工具；工具结果不足时明确说明未知项。\n"
        "最终直接输出给主 Agent 的交接正文；可以使用简洁 Markdown。\n"
        "正文应包含：做了什么、关键发现、风险或未知项、建议主 Agent 下一步怎么处理。\n\n"
        f"角色：{role}\n"
        f"任务：{task}\n"
        f"期望输出：{expected_output}\n"
        f"上下文：{context}"
    )


__all__ = [
    "CoreAgentSpec",
    "SUB_AGENT_NAME",
    "SUB_AGENT_TOOL_NAME",
    "SUB_AGENT_SPEC",
    "SUB_AGENT_TOOL_SPEC",
    "build_sub_agent_prompt",
]
