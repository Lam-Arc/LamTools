from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import replace
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Mapping

from lamtools_core.agent import SUB_AGENT_TOOL_NAME, SubAgentRunResult
from lamtools_core.app.base_agent import CoreBaseAgentConfig, CoreBaseAgentKit
from lamtools_core.attachment.service import AttachmentRecord, build_capability_aware_attachment_input
from lamtools_core.event import CoreEvent, EventSink
from lamtools_core.kernel import CoreLoopKernel, LoopPolicy
from lamtools_core.llm import ChatMessage
from lamtools_core.runtime import (
    InMemoryRuntimeStateStore,
    RuntimeCheckpointStore,
    RuntimeStateStore,
    RuntimeTurnInput,
)
from lamtools_core.skills import SkillRegistry
from lamtools_core.sub_agent import SubAgentEventForwardingSink
from lamtools_core.sub_session import normalize_sub_session_agent_name
from lamtools_core.tool import ToolCall, ToolSpec
from lamtools_core.tool.approval_continuation import ApprovedToolExecution, approved_tool_continuation_prompt
from lamtools_core.tool.default_toolbox import ApprovalPolicy, CoreToolbox, build_core_toolbox
from lamtools_core.tool.loadtools import LoadTools, mode_names
from lamtools_core.tool.mcp_tools import MCPToolCaller

# Type alias for the attachment-lookup protocol (duck-typed AttachmentService.get).
AttachmentServiceLike = Any


_WORKFLOW_CONTEXT_KEYS = (
    "parent_session_id",
    "parent_run_id",
    "parent_turn_id",
    "parent_call_id",
    "cwd",
    "pause_on_cancel",
    "permissions",
    "runtime_permissions",
    "event_metadata",
    "attachments",
    "runtime_snapshot",
    "snapshot",
    "environment",
    "capabilities",
    "trace_id",
    "traceId",
    "correlation_id",
    "actor_id",
    "actor_kind",
    "lineage",
    "parent_lineage",
    "workflow_stack",
    "active_workflows",
    "depth",
    "nesting_depth",
    "max_depth",
    "max_nesting_depth",
)


def _workflow_context_metadata(
    execution_context: Any | None,
    *,
    attachments: list[str] | None = None,
) -> dict[str, Any]:
    """Normalize a workflow context for the RuntimeTurnInput envelope.

    The production path supplies :class:`WorkflowExecutionContext`, while
    adapters and tests may pass a serialized mapping or a small duck-typed
    object.  Supporting all three here keeps the runner boundary independent
    of the workflow plugin's concrete class and preserves aliases used by
    older hosts.
    """
    if execution_context is None:
        result: dict[str, Any] = {}
    else:
        metadata_method = getattr(execution_context, "metadata", None)
        if callable(metadata_method):
            try:
                raw = metadata_method()
            except Exception:  # noqa: BLE001 - optional context cannot break delegation
                raw = {}
        elif isinstance(execution_context, Mapping):
            raw = execution_context
        else:
            raw = {
                key: getattr(execution_context, key)
                for key in _WORKFLOW_CONTEXT_KEYS
                if hasattr(execution_context, key)
            }
        source = dict(raw) if isinstance(raw, Mapping) else {}
        nested = source.get("workflow_execution", source.get("execution_context"))
        if callable(getattr(nested, "metadata", None)):
            try:
                nested = nested.metadata()
            except Exception:  # noqa: BLE001
                nested = None
        result = deepcopy(dict(nested)) if isinstance(nested, Mapping) else {}
        for key in _WORKFLOW_CONTEXT_KEYS:
            if key in source:
                result[key] = deepcopy(source[key])

    # A direct runner caller can provide attachments as the normal sub-agent
    # argument rather than embedding them in a WorkflowExecutionContext.
    if attachments and not result.get("attachments"):
        result["attachments"] = deepcopy(list(attachments))
    return result


def _resolve_model_id_for_capability(model_ref: str) -> str:
    """Resolve a model reference (model_id or display_name) to canonical model_id.

    The ``model`` parameter passed to ``sub_agent`` may be a display_name
    (e.g. "Kimi-K2.6") rather than a model_id (e.g. "xopkimik26"). Capability
    tables and config lookups key on model_id, so callers should resolve
    display_names to model_id as early as possible and use the canonical form
    throughout.
    """
    ref = (model_ref or "").strip()
    if not ref or ref.lower() in ("null", "none", "undefined"):
        return ""
    try:
        from lamtools_core.config.model_store import ModelStore
        store = ModelStore()
        # Exact model_id match
        model = store.get_sync(ref)
        if model is not None:
            return model.model_id
        # Try matching by display_name (case-insensitive)
        all_models = store.list_sync()
        ref_lower = ref.lower()
        for m in all_models:
            if (m.display_name or "").lower() == ref_lower:
                return m.model_id
    except Exception:
        pass
    return ref


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
        reasoning_level: str = "",
        thinking_enabled: bool | None = None,
        thinking_budget: int | None = None,
        approval_policy: ApprovalPolicy = "require",
        permission_preset: str = "ask",
        active_tier: str | None = None,
        tier_tools: dict[str, Any] | None = None,
        runtime_snapshot: dict[str, Any] | None = None,
        loaded_skill_roots: Iterable[Path] | None = None,
        skill_registry: SkillRegistry | None = None,
        mcp_caller: MCPToolCaller | None = None,
        mcp_tool_specs: list[ToolSpec] | None = None,
        context_window_tokens: int | None = None,
        compact_trigger_ratio: float = 0.8,
        state_store: RuntimeStateStore | None = None,
        session_prefix: str = "core-sub-agent",
        parent_event_sink: EventSink | None = None,
        checkpoint_coordinator: Any | None = None,
        activated_mcp_servers: set[str] | None = None,
        active_mode: str | None = None,
        load_tools: LoadTools | None = None,
        attachment_service: AttachmentServiceLike = None,
        imagegen_config: dict | None = None,
        allow_access_outside_workdir: bool = False,
        runtime_permissions_provider: Callable[[], Mapping[str, Any] | None] | None = None,
        model_context_sink: Any | None = None,
    ) -> None:
        self.work_root = Path(work_root)
        self.llm_client = llm_client
        self.model_id = model_id
        self.instructions = instructions
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.reasoning_level = reasoning_level
        self.thinking_enabled = thinking_enabled
        self.thinking_budget = thinking_budget
        self.approval_policy = approval_policy
        self.permission_preset = str(permission_preset or "ask")
        self.active_tier = active_tier
        self.tier_tools = deepcopy(tier_tools) if isinstance(tier_tools, dict) else tier_tools
        self.runtime_snapshot = deepcopy(runtime_snapshot) if isinstance(runtime_snapshot, dict) else None
        if loaded_skill_roots is None and skill_registry is None:
            from lamtools_core.skill_runtime import create_skill_runtime

            skill_runtime = create_skill_runtime()
            self.loaded_skill_roots = skill_runtime.roots
            self.skill_registry = skill_runtime.registry
        else:
            self.loaded_skill_roots = tuple(
                dict.fromkeys(Path(root).resolve() for root in (loaded_skill_roots or ()))
            )
            self.skill_registry = skill_registry or SkillRegistry(
                explicit_roots=self.loaded_skill_roots
            )
        self.mcp_caller = mcp_caller
        self.mcp_tool_specs = list(mcp_tool_specs or [])
        self.context_window_tokens = context_window_tokens
        self.compact_trigger_ratio = compact_trigger_ratio
        self.state_store = state_store or InMemoryRuntimeStateStore()
        self.session_prefix = str(session_prefix or "core-sub-agent")
        self.parent_event_sink = parent_event_sink
        self.checkpoint_coordinator = checkpoint_coordinator
        self.activated_mcp_servers = activated_mcp_servers or set()
        self.active_mode = active_mode
        self.load_tools = load_tools
        self.attachment_service = attachment_service
        self.imagegen_config = imagegen_config
        self.allow_access_outside_workdir = allow_access_outside_workdir
        self.runtime_permissions_provider = runtime_permissions_provider
        self.model_context_sink = model_context_sink
        # Per-session serialization: parallel sub_agent calls with the same
        # agent name share one child session id, so concurrent runs would
        # interleave history writes (audit 02 S2).  Keyed by session id, which
        # keeps the dict bounded by the number of distinct agent names.
        self._session_locks: dict[str, asyncio.Lock] = {}

    def _disabled_tools(self) -> set[str]:
        """Sub-agent disabled set: never sub_agent itself; generate_image only
        when the 生图 setting is disabled (mirrors the main agent)."""
        disabled = {SUB_AGENT_TOOL_NAME}
        if not bool((self.imagegen_config or {}).get("enabled")):
            disabled.add("generate_image")
        return disabled

    def _build_toolbox(self, disabled_tools: set[str], *, active_mode: str | None) -> CoreToolbox:
        return build_core_toolbox(
            work_root=self.work_root,
            approval_policy=self.approval_policy,
            active_tier=self.active_tier,
            tier_tools=self.tier_tools,
            loaded_skill_roots=self.loaded_skill_roots,
            skill_registry=self.skill_registry,
            mcp_caller=self.mcp_caller,
            mcp_tool_specs=self.mcp_tool_specs,
            disabled_tools=disabled_tools,
            imagegen_config=self.imagegen_config,
            activated_mcp_servers=self.activated_mcp_servers,
            load_tools=self.load_tools,
            active_mode=active_mode,
            allow_access_outside_workdir=self.allow_access_outside_workdir,
            runtime_permissions_provider=self.runtime_permissions_provider,
        )

    def _resolve_mode(self, mode: str) -> str | None:
        """Resolve a per-call mode override against the configured loadtools.

        An empty override falls back to the runner's baseline ``active_mode``.
        A non-empty mode that is not a known loadtools mode is treated as no
        filtering (full access) so an unknown name never silently locks the
        sub-agent out of its tools.
        """
        candidate = (mode or "").strip() or self.active_mode
        if not candidate:
            return None
        if self.load_tools and candidate not in mode_names(self.load_tools):
            return None
        return candidate

    async def _fetch_attachment_content(
        self, task: str, attachment_ids: list[str], model_id: str = ""
    ) -> str | list[dict[str, Any]]:
        """Build the sub-agent user message, optionally with attachment content blocks.

        Uses capability-aware splitting: attachments the sub-agent's model can
        process (e.g. images for a multimodal model) become content blocks;
        unsupported ones are deferred as IDs (rare for sub-agents, but handled).
        """
        if not attachment_ids or self.attachment_service is None:
            return task
        records: list[AttachmentRecord] = []
        for att_id in attachment_ids:
            att_id = str(att_id or "").strip()
            if not att_id:
                continue
            try:
                record = await self.attachment_service.get(att_id)
            except Exception:
                record = None
            if record is not None:
                records.append(record)
        if not records:
            return task
        # Resolve the sub-agent model's capability from its jsonc definition
        # (jsonc is the single source of truth; model_id alone is insufficient).
        from lamtools_core.config.model_store import resolve_model_capability

        capability = resolve_model_capability(model_id or self.model_id, work_root=str(self.work_root))
        index_text, content_blocks, _deferred = build_capability_aware_attachment_input(
            records, [r.id for r in records], capability
        )
        if not content_blocks:
            return task
        # Text block first (the task + attachment index), then content blocks.
        return [{"type": "text", "text": task + (index_text or "")}, *content_blocks]

    async def run(
        self,
        *,
        task: str,
        agent: str = "",
        model: str = "",
        mode: str = "",
        attachments: list[str] | None = None,
        parent_call_id: str = "",
        parent_run_id: str = "",
        parent_turn_id: str = "",
        allowed_tools: list[str] | None = None,
        execution_context: Any | None = None,
    ) -> SubAgentRunResult:
        agent_name = normalize_sub_session_agent_name(agent)
        lock = self._session_locks.setdefault(
            f"{self.session_prefix}:sub:{agent_name}", asyncio.Lock()
        )
        async with lock:
            return await self._run_locked(
                task=task,
                agent=agent,
                model=model,
                mode=mode,
                attachments=attachments,
                parent_call_id=parent_call_id,
                parent_run_id=parent_run_id,
                parent_turn_id=parent_turn_id,
                allowed_tools=allowed_tools,
                execution_context=execution_context,
            )

    async def _run_locked(
        self,
        *,
        task: str,
        agent: str = "",
        model: str = "",
        mode: str = "",
        attachments: list[str] | None = None,
        parent_call_id: str = "",
        parent_run_id: str = "",
        parent_turn_id: str = "",
        allowed_tools: list[str] | None = None,
        execution_context: Any | None = None,
    ) -> SubAgentRunResult:
        # Resolve model early: the LLM may pass a display_name (e.g. "Kimi-K2.6")
        # instead of a model_id (e.g. "xopkimik26"). Translate to canonical
        # model_id once so the entire downstream chain (capability lookup,
        # kernel config, metadata, result) uses the same value.
        effective_model = _resolve_model_id_for_capability(
            (model or "").strip() or self.model_id
        )
        effective_mode = self._resolve_mode(mode)
        user_content = await self._fetch_attachment_content(task, list(attachments or []), model_id=effective_model)
        disabled_tools = self._disabled_tools()
        if allowed_tools:
            allowed = {str(name).strip() for name in allowed_tools if str(name).strip()}
            if allowed:
                # An explicit tool allow-list: disable everything else.  The
                # full name set is the toolbox's own spec set (audit 18 S2 —
                # cfg.tools/allowed_tools from plugin UIs must be honored by
                # the runner rather than only persisted in the session.
                probe = self._build_toolbox(disabled_tools, active_mode=effective_mode)
                full_names = {spec.name for spec in probe.tool_specs()}
                disabled_tools |= full_names - allowed
        toolbox = self._build_toolbox(disabled_tools, active_mode=effective_mode)
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
        kernel = self._build_kernel(
            toolbox=toolbox,
            event_sink=child_sink,
            model_id=effective_model,
            active_mode=effective_mode,
        )
        workflow_metadata = _workflow_context_metadata(
            execution_context,
            attachments=list(attachments or []),
        )
        result = await kernel.run(
            RuntimeTurnInput(
                user_message=task,
                user_content=user_content if user_content is not task else None,
                metadata={
                    **deepcopy(workflow_metadata),
                    "session_id": f"{self.session_prefix}:sub:{agent_name}",
                    "model_id": effective_model,
                    "active_mode": effective_mode,
                    "reasoning_level": self.reasoning_level,
                    "thinking_enabled": self.thinking_enabled,
                    "thinking_budget": self.thinking_budget,
                    **({"workflow_execution": workflow_metadata} if workflow_metadata else {}),
                    "actor_kind": "sub_agent",
                    **(
                        {
                            "runtime_snapshot": deepcopy(self.runtime_snapshot),
                            "runtime_snapshot_fresh": True,
                        }
                        if self.runtime_snapshot is not None and "runtime_snapshot" not in workflow_metadata
                        else {}
                    ),
                },
            )
        )
        return self._result_from_kernel(result, model_id=effective_model)

    def _build_kernel(
        self,
        *,
        toolbox: Any,
        event_sink: EventSink,
        model_id: str = "",
        active_mode: str | None = None,
    ) -> CoreLoopKernel:
        return CoreLoopKernel(
            kit=CoreBaseAgentKit(
                work_root=self.work_root,
                config=CoreBaseAgentConfig(
                    model_id=model_id or self.model_id,
                    instructions=self.instructions,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    reasoning_level=self.reasoning_level,
                    thinking_enabled=self.thinking_enabled,
                    thinking_budget=self.thinking_budget,
                    approval_policy=self.approval_policy,
                    active_mode=active_mode,
                ),
                toolbox=toolbox,
            ),
            llm_client=self.llm_client,
            state_store=self.state_store,
            event_sink=event_sink,
            checkpoint_coordinator=self.checkpoint_coordinator,
            policy=LoopPolicy(
                **{
                    **self._retry_policy_overrides(),
                    "model_timeout_seconds": 360,
                    "context_window_tokens": self.context_window_tokens,
                    "compact_trigger_ratio": self.compact_trigger_ratio,
                }
            ),
            retry_policy=self._retry_policy(),
            model_context_sink=self.model_context_sink,
        )

    def _retry_policy_overrides(self) -> dict[str, Any]:
        """LoopPolicy retry knobs from model_retry.jsonc (config-file defaults)."""
        from lamtools_core.config.retry_store import (
            load_model_retry_config,
            loop_policy_overrides,
        )

        return loop_policy_overrides(load_model_retry_config())

    def _retry_policy(self) -> Any:
        """Transport RetryPolicy from model_retry.jsonc."""
        from lamtools_core.config.retry_store import (
            load_model_retry_config,
            retry_policy_from_config,
        )

        return retry_policy_from_config(load_model_retry_config())

    def _result_from_kernel(self, result: Any, *, model_id: str = "") -> SubAgentRunResult:
        last_turn = result.steps[-1].turn if result.steps else None
        ended_with_final_response = bool(
            result.decision == "done"
            and result.message.strip()
            and last_turn is not None
            and not last_turn.tool_calls
            and last_turn.reply.strip()
        )
        logged_steps = result.state.metadata.get("kernel_steps")
        if isinstance(logged_steps, list):
            tool_call_count = sum(
                len(step.get("tool_calls") or [])
                for step in logged_steps
                if isinstance(step, dict)
            )
        else:
            tool_call_count = sum(len(step.tool_steps) for step in result.steps)
        model_rounds = len(result.steps)
        tool_call_breakdown = self._extract_tool_call_breakdown(result)
        death_scene = self._extract_death_scene(result)
        return SubAgentRunResult(
            session_id=result.session_id,
            run_id=result.run_id,
            decision=result.decision,
            model_id=model_id or self.model_id,
            message=result.message,
            error=result.error,
            tool_call_count=tool_call_count,
            ended_with_final_response=ended_with_final_response,
            pending_approval=dict(result.state.metadata.get("pending_approval") or {}),
            pending_waiting_request=dict(result.state.metadata.get("pending_waiting_request") or {}),
            model_rounds=model_rounds,
            tool_call_breakdown=tool_call_breakdown,
            death_scene=death_scene,
        )

    @staticmethod
    def _extract_tool_call_breakdown(result: Any) -> dict[str, int]:
        """Aggregate tool call counts by tool name across all kernel steps."""
        breakdown: dict[str, int] = {}
        logged_steps = result.state.metadata.get("kernel_steps")
        if isinstance(logged_steps, list):
            for step in logged_steps:
                if not isinstance(step, dict):
                    continue
                for tc in step.get("tool_calls") or []:
                    if isinstance(tc, dict):
                        name = str(tc.get("name") or "")
                        if name:
                            breakdown[name] = breakdown.get(name, 0) + 1
        else:
            for step in result.steps:
                for ts in step.tool_steps:
                    name = ts.call.name
                    breakdown[name] = breakdown.get(name, 0) + 1
        return breakdown

    @staticmethod
    def _extract_death_scene(result: Any) -> str:
        """Build a compact summary of the last model round for failure forwarding.

        Captures the model's last reply (truncated) and the tools it called in
        that round along with their execution status, so the parent agent can
        understand *why* the sub-agent died instead of seeing only a generic
        'failed without a final response' message.
        """
        if not result.steps:
            return ""
        last_step = result.steps[-1]
        lines = ["--- Sub-agent death scene (last model round) ---"]
        turn = last_step.turn
        if turn is not None and turn.reply.strip():
            reply = turn.reply.strip()
            if len(reply) > 500:
                reply = reply[:500] + "…"
            lines.append(f"Model reply: {reply}")
        else:
            lines.append("Model reply: (empty — no text produced)")
        if last_step.tool_steps:
            lines.append("Tools called this round:")
            for ts in last_step.tool_steps:
                status = ts.result.status if ts.result else "unknown"
                entry = f"  - {ts.call.name} → {status}"
                if ts.result and ts.result.error:
                    err = ts.result.error.strip()
                    if len(err) > 200:
                        err = err[:200] + "…"
                    entry += f": {err}"
                lines.append(entry)
        else:
            lines.append("Tools called this round: (none)")
        if last_step.error:
            lines.append(f"Step error: {last_step.error}")
        return "\n".join(lines)

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
        model: str = "",
        mode: str = "",
        attachments: list[str] | None = None,
        execution_context: Any | None = None,
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
            approval_policy=self.approval_policy,
            active_tier=self.active_tier,
            tier_tools=self.tier_tools,
            loaded_skill_roots=self.loaded_skill_roots,
            skill_registry=self.skill_registry,
            mcp_caller=self.mcp_caller,
            mcp_tool_specs=self.mcp_tool_specs,
            disabled_tools=self._disabled_tools(),
            imagegen_config=self.imagegen_config,
            activated_mcp_servers=self.activated_mcp_servers,
            load_tools=self.load_tools,
            active_mode=self.active_mode,
            allow_access_outside_workdir=self.allow_access_outside_workdir,
            runtime_permissions_provider=self.runtime_permissions_provider,
        )
        call = approval_toolbox.prepare_approved_call(call)
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
            tool_msg = ChatMessage(
                role="tool",
                name=call.name,
                tool_call_id=call.id,
                content=tool_result.content or tool_result.error,
            ).to_dict()
            await self.state_store.append_history(session_id, [tool_msg])
            await self.state_store.save(state)
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
            model=model,
            mode=mode,
            attachments=attachments,
            execution_context=execution_context,
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
        model: str = "",
        mode: str = "",
        attachments: list[str] | None = None,
        execution_context: Any | None = None,
    ) -> SubAgentRunResult:
        # Same early resolution as run() — translate display_name to model_id.
        effective_model = _resolve_model_id_for_capability(
            (model or "").strip() or self.model_id
        )
        effective_mode = self._resolve_mode(mode)
        user_content = await self._fetch_attachment_content(task, list(attachments or []), model_id=effective_model)
        disabled_tools = self._disabled_tools()
        toolbox = build_core_toolbox(
            work_root=self.work_root,
            approval_policy=self.approval_policy,
            active_tier=self.active_tier,
            tier_tools=self.tier_tools,
            loaded_skill_roots=self.loaded_skill_roots,
            skill_registry=self.skill_registry,
            mcp_caller=self.mcp_caller,
            mcp_tool_specs=self.mcp_tool_specs,
            disabled_tools=disabled_tools,
            imagegen_config=self.imagegen_config,
            activated_mcp_servers=self.activated_mcp_servers,
            load_tools=self.load_tools,
            active_mode=effective_mode,
            allow_access_outside_workdir=self.allow_access_outside_workdir,
            runtime_permissions_provider=self.runtime_permissions_provider,
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
        kernel = self._build_kernel(
            toolbox=toolbox,
            event_sink=child_sink,
            model_id=effective_model,
            active_mode=effective_mode,
        )
        workflow_metadata = _workflow_context_metadata(
            execution_context,
            attachments=list(attachments or []),
        )
        result = await kernel.run(
            RuntimeTurnInput(
                user_message=task,
                user_content=user_content if user_content is not task else None,
                state=state,
                run_id=state.run_id,
                metadata={
                    **deepcopy(workflow_metadata),
                    "session_id": session_id,
                    "model_id": effective_model,
                    "active_mode": effective_mode,
                    "reasoning_level": self.reasoning_level,
                    "thinking_enabled": self.thinking_enabled,
                    "thinking_budget": self.thinking_budget,
                    **({"workflow_execution": workflow_metadata} if workflow_metadata else {}),
                    **(
                        {"runtime_snapshot": deepcopy(self.runtime_snapshot)}
                        if self.runtime_snapshot is not None and "runtime_snapshot" not in workflow_metadata
                        else {}
                    ),
                },
            )
        )
        return self._result_from_kernel(result, model_id=effective_model)

__all__ = ["KernelSubAgentRunner"]
