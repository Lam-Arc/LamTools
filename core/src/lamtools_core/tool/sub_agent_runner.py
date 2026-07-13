from __future__ import annotations

from pathlib import Path
from typing import Any

from lamtools_core.agent import SUB_AGENT_TOOL_NAME
from lamtools_core.app.base_agent import CoreBaseAgentConfig, CoreBaseAgentKit
from lamtools_core.event import CollectingEventSink
from lamtools_core.kernel import CoreLoopKernel, LoopPolicy
from lamtools_core.runtime import InMemoryRuntimeStateStore, RuntimeStateStore, RuntimeTurnInput
from lamtools_core.sub_session import normalize_sub_session_agent_name
from lamtools_core.tool import ToolSpec
from lamtools_core.tool.default_toolbox import ApprovalPolicy, build_core_toolbox
from lamtools_core.tool.mcp_tools import MCPToolCaller


class KernelSubAgentRunner:
    def __init__(
        self,
        *,
        work_root: str | Path,
        llm_client: Any,
        model_id: str = "",
        instructions: str = "",
        temperature: float = 0.2,
        max_tokens: int = 4096,
        thinking_enabled: bool | None = None,
        thinking_budget: int | None = None,
        approval_policy: ApprovalPolicy = "require",
        loaded_skill_roots: set[Path] | None = None,
        mcp_caller: MCPToolCaller | None = None,
        mcp_tool_specs: list[ToolSpec] | None = None,
        context_window_tokens: int | None = None,
        compact_trigger_ratio: float = 0.8,
        state_store: RuntimeStateStore | None = None,
        session_prefix: str = "core-sub-agent",
    ) -> None:
        self.work_root = Path(work_root)
        self.llm_client = llm_client
        self.model_id = model_id
        self.instructions = instructions
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.thinking_enabled = thinking_enabled
        self.thinking_budget = thinking_budget
        self.approval_policy = approval_policy
        self.loaded_skill_roots = set(loaded_skill_roots or set())
        self.mcp_caller = mcp_caller
        self.mcp_tool_specs = list(mcp_tool_specs or [])
        self.context_window_tokens = context_window_tokens
        self.compact_trigger_ratio = compact_trigger_ratio
        self.state_store = state_store or InMemoryRuntimeStateStore()
        self.session_prefix = str(session_prefix or "core-sub-agent")

    async def run(
        self,
        *,
        task: str,
        agent: str = "",
    ) -> str:
        disabled_tools = {SUB_AGENT_TOOL_NAME}
        toolbox = build_core_toolbox(
            work_root=self.work_root,
            approval_policy=self.approval_policy,
            loaded_skill_roots=self.loaded_skill_roots,
            mcp_caller=self.mcp_caller,
            mcp_tool_specs=self.mcp_tool_specs,
            disabled_tools=disabled_tools,
        )
        kernel = CoreLoopKernel(
            kit=CoreBaseAgentKit(
                work_root=self.work_root,
                config=CoreBaseAgentConfig(
                    model_id=self.model_id,
                    instructions=self.instructions,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    thinking_enabled=self.thinking_enabled,
                    thinking_budget=self.thinking_budget,
                    approval_policy=self.approval_policy,
                ),
                toolbox=toolbox,
            ),
            llm_client=self.llm_client,
            state_store=self.state_store,
            event_sink=CollectingEventSink(),
            policy=LoopPolicy(
                model_timeout_seconds=360,
                model_retries=3,
                persist_steps=True,
                context_window_tokens=self.context_window_tokens,
                compact_trigger_ratio=self.compact_trigger_ratio,
            ),
        )
        agent_name = normalize_sub_session_agent_name(agent)
        result = await kernel.run(
            RuntimeTurnInput(
                user_message=task,
                metadata={"session_id": f"{self.session_prefix}:sub:{agent_name}"},
            )
        )
        if result.message:
            return result.message
        if result.error:
            return f"SUB_AGENT ERROR: {result.error}"
        return ""

__all__ = ["KernelSubAgentRunner"]
