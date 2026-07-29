from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from lamtools_core.agent import SUB_AGENT_TOOL_NAME, SubAgentRunResult
from lamtools_core.app.base_agent import CoreBaseAgentConfig, CoreBaseAgentKit
from lamtools_core.event import CoreEvent, EventSink
from lamtools_core.kernel import CoreLoopKernel, LoopPolicy
from lamtools_core.llm import ChatMessage
from lamtools_core.runtime import (
    InMemoryRuntimeStateStore,
    RuntimeCheckpointStore,
    RuntimeStateStore,
    RuntimeTurnInput,
)
from lamtools_core.sub_agent import SubAgentEventForwardingSink
from lamtools_core.sub_session import normalize_sub_session_agent_name
from lamtools_core.tool import ToolCall, ToolSpec
from lamtools_core.tool.approval_continuation import ApprovedToolExecution, approved_tool_continuation_prompt
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
        max_tokens: int | None = None,
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
        parent_event_sink: EventSink | None = None,
        checkpoint_coordinator: Any | None = None,
        activated_mcp_servers: set[str] | None = None,
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
        self.parent_event_sink = parent_event_sink
        self.checkpoint_coordinator = checkpoint_coordinator
        self.activated_mcp_servers = activated_mcp_servers or set()

    async def run(
        self,
        *,
        task: str,
        agent: str = "",
        parent_call_id: str = "",
        parent_run_id: str = "",
        parent_turn_id: str = "",
    ) -> SubAgentRunResult:
        disabled_tools = {SUB_AGENT_TOOL_NAME}
        toolbox = build_core_toolbox(
            work_root=self.work_root,
            approval_policy=self.approval_policy,
            loaded_skill_roots=self.loaded_skill_roots,
            mcp_caller=self.mcp_caller,
            mcp_tool_specs=self.mcp_tool_specs,
            disabled_tools=disabled_tools,
            activated_mcp_servers=self.activated_mcp_servers,
        )
        agent_name = normalize_sub_session_agent_name(agent)
        child_sink = SubAgentEventForwardingSink(
            parent_sink=self.parent_event_sink,
            parent_session_id=self.session_prefix,
            agent=agent_name,
            task=task,
            parent_call_id=parent_call_id,
            parent_run_id=parent_run_id,
            parent_turn_id=parent_turn_id,
        )
        kernel = self._build_kernel(toolbox=toolbox, event_sink=child_sink)
        result = await kernel.run(
            RuntimeTurnInput(
                user_message=task,
                metadata={
                    "session_id": f"{self.session_prefix}:sub:{agent_name}",
                    "model_id": self.model_id,
                    "thinking_enabled": self.thinking_enabled,
                    "thinking_budget": self.thinking_budget,
                    "actor_kind": "sub_agent",
                },
            )
        )
        return self._result_from_kernel(result)

    def _build_kernel(self, *, toolbox: Any, event_sink: EventSink) -> CoreLoopKernel:
        return CoreLoopKernel(
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
            event_sink=event_sink,
            checkpoint_coordinator=self.checkpoint_coordinator,
            policy=LoopPolicy(
                model_timeout_seconds=360,
                context_window_tokens=self.context_window_tokens,
                compact_trigger_ratio=self.compact_trigger_ratio,
            ),
        )

    def _result_from_kernel(self, result: Any) -> SubAgentRunResult:
        last_turn = result.steps[-1].turn if result.steps else None
        ended_with_final_response = bool(
            result.decision == "done"
            and result.message.strip()
            and last_turn is not None
            and not last_turn.tool_calls
            and last_turn.reply.strip()
        )
        logged_steps = result.state.metadata.get("kernel_steps")
        tool_call_count = (
            sum(
                len(step.get("tool_calls") or [])
                for step in logged_steps
                if isinstance(step, dict)
            )
            if isinstance(logged_steps, list)
            else sum(len(step.tool_steps) for step in result.steps)
        )
        return SubAgentRunResult(
            session_id=result.session_id,
            run_id=result.run_id,
            decision=result.decision,
            model_id=self.model_id,
            message=result.message,
            error=result.error,
            tool_call_count=tool_call_count,
            ended_with_final_response=ended_with_final_response,
            pending_approval=dict(result.state.metadata.get("pending_approval") or {}),
            pending_waiting_request=dict(result.state.metadata.get("pending_waiting_request") or {}),
        )

    async def resume_approved(
        self,
        *,
        session_id: str,
        pending_call: dict[str, Any],
        task: str,
        agent: str,
        parent_call_id: str,
        parent_run_id: str = "",
        parent_turn_id: str = "",
    ) -> SubAgentRunResult:
        state = await self.state_store.get(session_id)
        if state is None:
            raise ValueError("Sub-agent runtime state not found")
        call = ToolCall(
            id=str(pending_call.get("id") or ""),
            name=str(pending_call.get("name") or ""),
            arguments=(
                dict(pending_call.get("arguments"))
                if isinstance(pending_call.get("arguments"), dict)
                else {}
            ),
            metadata={
                **(
                    dict(pending_call.get("metadata"))
                    if isinstance(pending_call.get("metadata"), dict)
                    else {}
                ),
                "approval": {"approved": True, "auto_approved": True},
            },
        )
        child_sink = SubAgentEventForwardingSink(
            parent_sink=self.parent_event_sink,
            parent_session_id=self.session_prefix,
            agent=normalize_sub_session_agent_name(agent),
            task=task,
            parent_call_id=parent_call_id,
            parent_run_id=parent_run_id,
            parent_turn_id=parent_turn_id,
        )
        await child_sink.emit(CoreEvent(
            name="runtime.approval_response",
            category="decision",
            payload={
                "request_id": call.id,
                "tool_call_id": call.id,
                "decision": "approve",
                "action": "approve",
                "status": "resolved",
            },
            session_id=session_id,
            run_id=state.run_id,
            tags=["approval", "resolved"],
        ))
        approval_toolbox = build_core_toolbox(
            work_root=self.work_root,
            approval_policy="auto_approve",
            loaded_skill_roots=self.loaded_skill_roots,
            mcp_caller=self.mcp_caller,
            mcp_tool_specs=self.mcp_tool_specs,
            disabled_tools={SUB_AGENT_TOOL_NAME},
            activated_mcp_servers=self.activated_mcp_servers,
        )
        tool_result = await approval_toolbox.execute(call)
        await child_sink.emit(CoreEvent(
            name="runtime.tool.finished",
            category="tool",
            payload={
                "tool_name": call.name,
                "call_id": call.id,
                "status": tool_result.status,
                "content": tool_result.content or "",
                "error": tool_result.error or "",
                "artifacts": [artifact.to_dict() for artifact in tool_result.artifacts],
                "metadata": tool_result.metadata,
            },
            session_id=session_id,
            run_id=state.run_id,
            tags=["tool"],
        ))
        if tool_result.status != "ok":
            raise RuntimeError(tool_result.error or tool_result.content or "Approved sub-agent tool failed")

        state.metadata.pop("pending_approval", None)
        state.metadata.pop("pending_waiting_request", None)
        state.status = "running"
        state.loop_state = "continue"
        if isinstance(self.state_store, RuntimeCheckpointStore):
            history = await self.state_store.get_history(session_id)
            history.append(
                ChatMessage(
                    role="tool",
                    name=call.name,
                    tool_call_id=call.id,
                    content=tool_result.content or tool_result.error,
                ).to_dict()
            )
            await self.state_store.save_checkpoint(state, history)
        else:
            await self.state_store.save(state)

        approved_tool = ApprovedToolExecution(
            tool_name=call.name,
            tool_args=call.arguments,
            tool_content=tool_result.content or tool_result.error,
            tool_status="completed",
        )
        continuation = approved_tool_continuation_prompt(
            original_task=task,
            approved_tool=approved_tool,
        )
        resumed = await self._run_turn(
            task=continuation,
            agent=agent,
            parent_call_id=parent_call_id,
            session_id=session_id,
            state=state,
            parent_run_id=parent_run_id,
            parent_turn_id=parent_turn_id,
        )
        return replace(resumed, tool_call_count=resumed.tool_call_count + 1)

    async def _run_turn(
        self,
        *,
        task: str,
        agent: str,
        parent_call_id: str,
        session_id: str,
        state: Any,
        parent_run_id: str = "",
        parent_turn_id: str = "",
    ) -> SubAgentRunResult:
        disabled_tools = {SUB_AGENT_TOOL_NAME}
        toolbox = build_core_toolbox(
            work_root=self.work_root,
            approval_policy=self.approval_policy,
            loaded_skill_roots=self.loaded_skill_roots,
            mcp_caller=self.mcp_caller,
            mcp_tool_specs=self.mcp_tool_specs,
            disabled_tools=disabled_tools,
            activated_mcp_servers=self.activated_mcp_servers,
        )
        agent_name = normalize_sub_session_agent_name(agent)
        child_sink = SubAgentEventForwardingSink(
            parent_sink=self.parent_event_sink,
            parent_session_id=self.session_prefix,
            agent=agent_name,
            task=task,
            parent_call_id=parent_call_id,
            parent_run_id=parent_run_id,
            parent_turn_id=parent_turn_id,
        )
        kernel = self._build_kernel(toolbox=toolbox, event_sink=child_sink)
        result = await kernel.run(
            RuntimeTurnInput(
                user_message=task,
                state=state,
                run_id=state.run_id,
                metadata={
                    "session_id": session_id,
                    "model_id": self.model_id,
                    "thinking_enabled": self.thinking_enabled,
                    "thinking_budget": self.thinking_budget,
                },
            )
        )
        return self._result_from_kernel(result)

__all__ = ["KernelSubAgentRunner"]
