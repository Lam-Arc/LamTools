from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ResolvedWaitingRequest:
    action: str
    guidance_text: str = ""


@dataclass
class ApprovedToolExecution:
    tool_name: str
    tool_args: dict[str, Any]
    tool_content: str
    tool_status: str

    @property
    def completed(self) -> bool:
        return self.tool_status == "completed"


def normalize_waiting_action(value: str) -> str:
    normalized_action = (value or "").strip().lower()
    if normalized_action in {"approve_once", "approve_for_session"}:
        normalized_action = "approve"
    if normalized_action in {"confirm", "continue", "yes"}:
        normalized_action = "approve"
    if normalized_action in {"other", "guidance", "other_guidance"}:
        normalized_action = "guide"
    if normalized_action not in {"approve", "deny", "guide"}:
        raise ValueError("Unsupported waiting request decision")
    return normalized_action


def resolve_waiting_decision(action: str, response: str = "") -> ResolvedWaitingRequest:
    normalized_action = normalize_waiting_action(action or response)
    guidance_text = (response or "").strip()
    if normalized_action == "guide" and not guidance_text:
        raise ValueError("Guidance decision requires response text")
    return ResolvedWaitingRequest(action=normalized_action, guidance_text=guidance_text)


def guidance_continuation_prompt(
    *,
    original_task: str,
    tool_name: str,
    tool_args: dict[str, Any],
    guidance_text: str,
) -> str:
    return (
        "继续完成同一个用户任务。当前停在等待用户介入的工具调用处，"
        "用户没有直接批准原动作，而是给出了新的引导。\n\n"
        f"原始任务：{original_task}\n"
        f"等待中的工具：{tool_name}\n"
        f"等待中的工具参数：{json.dumps(tool_args, ensure_ascii=False)}\n"
        f"用户引导：{guidance_text}\n\n"
        "请严格根据用户引导重新判断下一步；不要默认执行刚才等待审批的工具。"
    )


def approved_tool_continuation_prompt(
    *,
    original_task: str,
    approved_tool: ApprovedToolExecution,
) -> str:
    return (
        "继续完成同一个用户任务。用户已经批准并由后端执行了等待中的工具调用。\n\n"
        f"原始任务：{original_task}\n"
        f"已执行工具：{approved_tool.tool_name}\n"
        f"工具参数：{json.dumps(approved_tool.tool_args, ensure_ascii=False)}\n"
        f"工具结果：{approved_tool.tool_content[:4000]}\n\n"
        "请基于这个真实工具结果继续后续步骤；如果已经完成，请给出最终回复。"
    )
