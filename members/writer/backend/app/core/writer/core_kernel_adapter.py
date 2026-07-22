"""Writer CoreLoopKernel adapter.

**Boundary contract:**

- ``WriterLLMClientAdapter`` wraps the existing Writer ``llm_client`` (which
  exposes ``.chat_full(messages, tools=...)``) so it satisfies the Core
  ``LLMClient`` protocol (``.complete(request) -> LLMResponse``).  For
  testing, callers can inject any object that satisfies ``LLMClient``.

- ``WriterKit`` implements ``lamtools_core.kernel.RuntimeKit``:

  * **text-only done** — model replies with plain text, no tool calls → done.
  * **ask_clarification / needs_user_input → wait** — Kit detects
    ``ask_clarification`` action type and returns ``LoopDecision="wait"``.
  * **tool_calls → execute_tool → format_tool_result_for_model → continue/done** —
    Kit delegates tool execution to an injectable ``tool_executor``, formats
    the result as a tool-role ``ChatMessage``, and continues unless the model
    signals done.

- ``ReadOnlyToolExecutor`` provides safe read-only tools (read_file, list_dir,
  search_files, search_content) bounded to a ``work_root`` directory.  All
  paths are validated to prevent traversal outside work_root.  Output is
  limited (item counts, text length) to prevent context explosion.  No write,
  command, or git operations are exposed.

- ``ReadWriteToolExecutor`` extends ``ReadOnlyToolExecutor`` with safe write,
  edit, and test-run tools (write_file, edit_file, run_tests), also bounded
  to ``work_root``:

  * **write_file** — create or overwrite a file.  Content length is capped.
    Parent directories are created automatically.  Path must stay inside
    work_root.
  * **edit_file** — replace an exact text segment (old_string → new_string)
    in an existing file.  Fails if old_string is not found or is ambiguous
    (appears more than once).  Path must stay inside work_root.
  * **run_tests** — execute a test command inside work_root through the
    stable bounded command runner.  Secured by path validation, timeout,
    and output truncation.  Exit code is returned in metadata.

  No run_command, git, or other dangerous operations are exposed.

- ``run_core_kernel`` is the top-level entry point. It assembles a
  ``CoreLoopKernel`` and runs it, returning a ``KernelResult``. When
  ``work_root`` is provided, bounded read/write/test tools are enabled by
  default. An injected ``tool_executor`` (dict or callable) takes priority.
  Without ``work_root``, no real file operations are available.

Tool execution uses an injectable ``tool_executor`` (dict or callable).
When ``work_root`` is set, read-write file tools are available by default.
No command/git operations are performed by the default tools.

**Core / WriterKit boundary:**
  - CoreLoopKernel owns the loop skeleton (load state → call model → parse →
    execute tools → verify → decide → writeback → save).
  - WriterKit owns all Writer-specific business logic (how to parse
    model output, what counts as done/wait, how to execute tools).
  - Kernel never branches on product name; Kit never reaches into Kernel
    internals.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any, Callable, Awaitable

from lamtools_core.context_compaction import COMPACTION_PREFIX
from lamtools_core.tool.command_runner import command_shell_prompt
from lamtools_core.event import CollectingEventSink, CoreEvent, EventSink, InMemoryEventLog
from lamtools_core.kernel import (
    CoreLoopKernel,
    KernelResult,
    KernelStep,
    KernelTurn,
    LoopDecision,
    LoopPolicy,
    RuntimeKit,
    VerificationResult,
    build_response_blocks_for_summary,
    compact_core_events_for_summary,
)
from lamtools_core.llm import (
    ChatMessage,
    LLMClient,
    LLMRequest,
    LLMResponse,
    LLMStreamEvent,
    LLMUsage,
)
from lamtools_core.mem import format_session_memory_summary
from lamtools_core.app import assemble_core_agent_plugins
from lamtools_core.prompt import PromptContext, format_prompt_sections
from lamtools_core.app.project_context import ProjectContextLoader
from lamtools_core.runtime import InMemoryRuntimeStateStore, RuntimeState, RuntimeStateStore, RuntimeTurnInput
from lamtools_core.runtime.goal import GoalCompletionGate, GoalManager, ModelGoalEvaluator
from lamtools_core.sub_session import SubSessionRuntimeStateStore, normalize_sub_session_agent_name
from lamtools_core.sub_agent import SubAgentEventForwardingSink
from lamtools_core.tool import ToolCall, ToolResult
from lamtools_core.tool.command import run_subprocess as _run_subprocess
from lamtools_core.tool.command import validate_command_paths as _validate_command_paths
from lamtools_core.tool.sub_agent_runner import KernelSubAgentRunner
from lamtools_core.tool.verification import verify_written_tool_results
from lamtools_core.tool.workspace import is_within_path as _is_within_path
from lamtools_core.tool.workspace import validate_workspace_path as _validate_path

from app.config import settings
from app.core.prompt_assembler import WRITER_TOOLS, get_writer_execution_discipline
from app.core.writer.agent_types import AgentCall
from app.core.writer.failure_specs import failure_recovery_instruction
from app.core.writer.llm_bridge import WriterLLMClientAdapter
from app.core.writer.permission import command_permission_decision
from app.core.writer.read_tools import ReadOnlyToolExecutor
from app.core.writer.runtime_resources import (
    cached_mcp_registry,
    close_writer_runtime_resources,
    runtime_now_prompt,
    schedule_writer_startup_prewarm,
    static_prompt_messages,
    stream_http_client,
)
from app.core.writer.sub_agent_projection import project_sub_agent_result
from app.core.writer.task_plan import (
    apply_checklist_update as _apply_checklist_update,
    auto_advance_plan as _auto_advance_plan,
    has_delivery_progress as _has_delivery_progress,
    new_plan_revision as _new_plan_revision,
    plan_to_active_plan as _plan_to_active_plan,
)
from app.core.writer.tool_failure import (
    looks_like_test_assertion_failure,
    should_stop_repeated_failure,
    tool_failure_context,
    tool_failure_signature,
)
from app.core.writer.tool_outcomes import record_tool_outcomes
from app.core.writer.tool_feedback import format_tool_result_for_model as _format_tool_result_for_model
from app.core.writer.tools import ReadWriteToolExecutor, resolve_tool_executor as _resolve_tool_executor
logger = logging.getLogger(__name__)


def _build_plugin_hook_engine(work_root: str | None):
    project_root = str(work_root or ".").strip() or "."
    return assemble_core_agent_plugins(
        data_dir=settings.data_dir,
        work_root=project_root,
        plugin_roots=None,
        include_user_plugins=True,
    )["hook_engine"]


def _exception_summary(exc: BaseException) -> str:
    """Return a non-empty diagnostic string for exceptions with blank messages."""
    message = str(exc).strip()
    if message:
        return f"{type(exc).__name__}: {message}"
    return type(exc).__name__


# ---------------------------------------------------------------------------
# 2. WriterKit
# ---------------------------------------------------------------------------

# Action types that signal the model wants user input
_WAIT_ACTION_TYPES = frozenset({"ask_clarification", "needs_user_input"})

class WriterKit:
    """RuntimeKit implementation for Writer CoreLoopKernel.

    Implements ``lamtools_core.kernel.RuntimeKit``:

    - **parse_model_output**: Detects tool calls from LLMResponse and maps
      Writer action types.  ``ask_clarification`` / ``needs_user_input`` →
      ``decision_hint="wait"``.  No tool calls and finish_reason="stop" →
      ``decision_hint="done"``.
    - **build_model_request**: Injects persona (writer identity), execution
      discipline, and tool schemas so the model knows it can read/write/edit
      files, run tests, check git status, and more.
    - **execute_tool**: Delegates to the injectable ``tool_executor``.
    - **verify**: Checks file existence for write_file/edit_file calls and
      inspects written content for stubs/TODOs.
    - **decide_next**: Applies drift detection (consecutive reads, repeated
      tools, failure cascade, turn budget) before returning decision.
    - **writeback**: Tracks recent tools, statuses, and failures in state
      metadata for drift detection.
    - Other hooks are no-ops.
    """

    name: str = "writer-kit"

    def __init__(
        self,
        tool_executor: dict[str, Callable[..., Awaitable[ToolResult]]]
        | Callable[[ToolCall], Awaitable[ToolResult]]
        | None = None,
        initial_history: list[ChatMessage] | None = None,
        work_root: str = "",
        agent_llm_client: Any = None,
        runtime_controls: dict[str, dict[str, bool]] | None = None,
        core_event_callback: Callable[[CoreEvent], Awaitable[None]] | None = None,
        tool_allowlist: set[str] | frozenset[str] | None = None,
        context_window_tokens: int | None = None,
        compact_trigger_ratio: float = 0.8,
        cancel_event: asyncio.Event | None = None,
        runtime_state_store: RuntimeStateStore | None = None,
    ) -> None:
        """Initialise with optional tool_executor, initial_history, work_root, and agent_llm_client.

        Args:
            tool_executor: Either a dict mapping tool names to async callables,
                or a single async callable that accepts a ToolCall and returns
                a ToolResult.  If None, tool execution returns a stub ok result.
            initial_history: Prior conversation turns as ChatMessage objects.
                Only ``user`` and ``assistant`` roles are expected.  These
                messages are prepended to the kernel's internal history so the
                LLM sees the full multi-turn context.  The current user
                message (managed by CoreLoopKernel) must NOT be included here
                — the kernel appends it automatically.
            work_root: Working directory for file operations (used by verify
                to check written files exist on disk).
            agent_llm_client: The raw Writer LLM client (with .chat_full) for
                sub-agent execution. When None, sub-agent tools are not
                advertised.
        """
        self._tool_executor = tool_executor
        self._initial_history: list[ChatMessage] = list(initial_history) if initial_history else []
        self._work_root = work_root
        self._agent_llm_client = agent_llm_client
        self._runtime_controls = runtime_controls or {}
        self._core_event_callback = core_event_callback
        self._tool_allowlist = frozenset(tool_allowlist) if tool_allowlist is not None else None
        self._context_window_tokens = context_window_tokens
        self._compact_trigger_ratio = compact_trigger_ratio
        self._cancel_event = cancel_event
        self._runtime_state_store = runtime_state_store
        self._intervention_pending: str = ""

        # MCP integration — loaded lazily on first run_start
        self._mcp_registry: Any = None
        self._mcp_loaded: bool = False

        self._effective_tools = self._filter_effective_tools(WRITER_TOOLS)

    def _filter_effective_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Advertise only tools that can actually be executed in this runtime."""
        if not isinstance(self._tool_executor, dict):
            filtered = [
                tool for tool in tools
                if self._model_tool_enabled(str(tool.get("function", {}).get("name", "")))
            ]
            if self._tool_allowlist is None:
                return filtered
            return [
                tool for tool in filtered
                if str(tool.get("function", {}).get("name", "")) in self._tool_allowlist
            ]

        executable = set(self._tool_executor.keys())
        executable.add("mcp_tool")

        filtered = [
            tool for tool in tools
            if str(tool.get("function", {}).get("name", "")) in executable
            and self._model_tool_enabled(str(tool.get("function", {}).get("name", "")))
        ]
        if self._tool_allowlist is None:
            return filtered
        return [
            tool for tool in filtered
            if str(tool.get("function", {}).get("name", "")) in self._tool_allowlist
        ]

    def _model_tool_enabled(self, name: str) -> bool:
        return self._tool_enabled(name)

    def _tool_enabled(self, name: str) -> bool:
        controls = self._runtime_controls.get("tools", {})
        return bool(controls.get(name, True))

    def _command_policies(self) -> dict[str, object]:
        controls = self._runtime_controls.get("command_policies", {})
        return controls if isinstance(controls, dict) else {}

    def _annotate_command_permission(self, call: ToolCall) -> ToolCall:
        if call.name == "arrange":
            action = str((call.arguments or {}).get("action") or "").strip().lower()
            if action not in {"list", "get"}:
                call.requires_approval = True
                call.metadata.update({
                    "permission_group": "durable_write",
                    "approval_policy": "ask_user",
                    "policy_reason": "创建或修改长期安排需要确认",
                })
            return call
        if call.name not in {"run_command", "run_tests"}:
            return call
        args = call.arguments if isinstance(call.arguments, dict) else {}
        command = args.get("command")
        if not isinstance(command, str) or not command.strip():
            return call
        decision = command_permission_decision(command, self._command_policies())
        call.metadata.update({
            "permission_group": decision.group,
            "approval_policy": decision.policy,
        })
        call.requires_approval = decision.requires_approval
        if decision.reason:
            call.metadata["policy_reason"] = decision.reason
        return call

    def _tool_enabled(self, name: str) -> bool:
        controls = self._runtime_controls.get("tools", {})
        return bool(controls.get(name, True))

    async def _run_sub_agent_kernel(
        self,
        agent_name: str,
        call: AgentCall,
        prompt: str,
        available_tools: frozenset[str],
    ) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        llm_client = self._agent_llm_client
        if llm_client is None:
            raise RuntimeError("SubAgent runtime has no LLM client")

        if hasattr(llm_client, "complete"):
            core_llm = llm_client
        elif hasattr(llm_client, "chat_full"):
            core_llm = WriterLLMClientAdapter(writer_client=llm_client)
        else:
            raise RuntimeError("SubAgent LLM client must have .chat_full() or .complete()")

        work_root = str(self._work_root or "")
        tool_executor = _resolve_tool_executor(self._tool_executor, work_root or None)

        sub_session_id = str(call.options.get("_sub_session_id") or "")
        if not sub_session_id:
            sub_session_id = f"sub:{agent_name}:{uuid.uuid4().hex[:8]}"
        option_state_store = call.options.get("_sub_session_state_store")
        if hasattr(option_state_store, "get") and hasattr(option_state_store, "save"):
            state_store = option_state_store
        else:
            state_store = InMemoryRuntimeStateStore()
        nested_kit = WriterKit(
            tool_executor=tool_executor,
            work_root=work_root,
            agent_llm_client=None,
            runtime_controls=self._runtime_controls,
            tool_allowlist=available_tools,
            core_event_callback=self._core_event_callback,
            context_window_tokens=self._context_window_tokens,
            compact_trigger_ratio=self._compact_trigger_ratio,
            cancel_event=self._cancel_event,
        )
        parent_session_id = str(call.options.get("_parent_session_id") or "")
        parent_run_id = str(call.options.get("_parent_run_id") or "")
        parent_turn_id = str(call.options.get("_parent_turn_id") or parent_run_id)
        parent_call_id = str(call.options.get("_parent_tool_call_id") or "")
        parent_sink = (
            CollectingEventSink(live_callback=self._core_event_callback, should_collect=lambda _event: False)
            if self._core_event_callback is not None
            else None
        )
        event_sink = SubAgentEventForwardingSink(
            parent_sink=parent_sink,
            parent_session_id=parent_session_id,
            agent=agent_name,
            task=call.task,
            parent_call_id=parent_call_id,
            parent_run_id=parent_run_id,
            parent_turn_id=parent_turn_id,
        )
        kernel = CoreLoopKernel(
            kit=nested_kit,
            llm_client=core_llm,
            state_store=state_store,
            event_sink=event_sink,
            policy=LoopPolicy(
                context_window_tokens=self._context_window_tokens,
                compact_trigger_ratio=self._compact_trigger_ratio,
                parallel_tool_names=(),
            ),
            hook_engine=_build_plugin_hook_engine(work_root),
        )
        watcher_task = None
        if self._cancel_event is not None:
            async def _cancel_watcher() -> None:
                await self._cancel_event.wait()
                kernel.cancel()
            watcher_task = asyncio.create_task(_cancel_watcher())
        try:
            result = await kernel.run(RuntimeTurnInput(
                user_message=prompt,
                metadata={"session_id": sub_session_id},
            ))
        finally:
            if watcher_task is not None:
                watcher_task.cancel()
        child_state = await state_store.get(sub_session_id)
        if child_state is not None:
            child_state.metadata.setdefault("initial_task", call.task)
            child_state.metadata["sub_agent_link"] = {
                "agent": agent_name,
                "session_id": sub_session_id,
                "parent_call_id": parent_call_id,
                "parent_run_id": parent_run_id,
                "parent_turn_id": parent_turn_id,
                "tools": sorted(available_tools),
            }
            await state_store.save(child_state)
        nested_events = event_sink.events
        data, tool_records, reasoning_blocks, diagnostics = project_sub_agent_result(result, nested_events)
        if result.decision == "wait":
            child_state = await state_store.get(sub_session_id)
            pending = child_state.metadata.get("pending_approval") if child_state is not None else None
            waiting = child_state.metadata.get("pending_waiting_request") if child_state is not None else None
            if isinstance(pending, dict):
                delegated = {
                    **pending,
                    "delegated_session": {
                        "agent": agent_name,
                        "session_id": sub_session_id,
                        "task": call.task,
                        "tools": sorted(available_tools),
                        "agent_run_id": str(call.options.get("_agent_run_id") or ""),
                        "sub_line_id": str(call.options.get("_sub_line_id") or ""),
                        "parent_tool_call_id": str(call.options.get("_parent_tool_call_id") or ""),
                        "parent_call_id": parent_call_id,
                        "parent_run_id": parent_run_id,
                        "parent_turn_id": parent_turn_id,
                    },
                }
                parent_state = getattr(state_store, "parent_state", None)
                if parent_state is not None:
                    parent_state.metadata["pending_approval"] = delegated
                    if isinstance(waiting, dict):
                        parent_state.metadata["pending_waiting_request"] = dict(waiting)
                    persist_parent = getattr(state_store, "persist_parent", None)
                    if callable(persist_parent):
                        await persist_parent()
                diagnostics["pending_approval"] = delegated
        return data, tool_records, reasoning_blocks, diagnostics

    # -- RuntimeKit protocol --------------------------------------------------

    def _build_project_context_parts(self):
        loader = ProjectContextLoader()
        return loader.to_prompt_parts(self._work_root)

    async def on_run_start(
        self, state: RuntimeState, turn_input: RuntimeTurnInput
    ) -> None:
        if state.metadata is None:
            state.metadata = {}
        for key in ("model_id", "project_id", "thinking_enabled", "thinking_budget", "shallow_thinking_enabled"):
            if key in turn_input.metadata:
                state.metadata[key] = turn_input.metadata[key]
        if turn_input.user_message:
            state.metadata["current_task"] = turn_input.user_message
            state.metadata["original_task"] = turn_input.user_message
        if not self._mcp_loaded:
            try:
                self._mcp_registry = await cached_mcp_registry(self._work_root)
            except Exception as exc:
                logger.warning("MCP load failed: %s", exc)
                self._mcp_registry = None
            self._mcp_loaded = True

    async def build_context(
        self,
        state: RuntimeState,
        turn_input: RuntimeTurnInput,
        history: list[ChatMessage],
        step_index: int,
    ) -> PromptContext:
        return PromptContext(
            session_id=state.session_id,
            user_message=turn_input.user_message,
            history=history,
            state=state,
        )

    async def build_model_request(
        self, state: RuntimeState, context: PromptContext
    ) -> LLMRequest:
        # Stable prefix first. Current time, task/session state, history,
        # approvals, and queued input stay out of the cache.
        messages = await static_prompt_messages(self._work_root)
        context_parts = self._build_project_context_parts()
        for part in context_parts:
            messages.append(ChatMessage(
                role="system",
                content=part.content,
                metadata={"key": part.key, "kind": part.kind},
            ))
        messages.append(ChatMessage(
            role="system",
            content=runtime_now_prompt(),
            metadata={"key": "runtime_now", "kind": "context"},
        ))
        messages.append(ChatMessage(
            role="system",
            content=f"当前项目: {state.metadata.get('project_id', '')}, 当前会话: {state.session_id}, 当前模型: {state.metadata.get('model_id', 'default')}",
            metadata={"key": "session_context", "kind": "context"},
        ))
        messages.append(ChatMessage(
            role="system",
            content=command_shell_prompt(),
            metadata={"key": "command_shell", "kind": "context"},
        ))
        # 3.5 Inject path exhaustion intervention (consumed once per turn)
        if self._intervention_pending:
            messages.append(ChatMessage(
                role="system",
                content=self._intervention_pending,
                metadata={"key": "intervention", "kind": "instruction"},
            ))
            self._intervention_pending = ""

        # 4. Inject runtime context from state.metadata and context.metadata.
        #    state.metadata is populated by writeback (recent_tools, failures,
        #    drift_warning) and by the service (project_rules, git_state).
        #    context.metadata comes from CoreLoopKernel.
        hook_sources: list[dict] = [context.metadata or {}]
        if state.metadata:
            hook_sources.append(state.metadata)
        merged_context: dict[str, Any] = {}
        for src in hook_sources:
            merged_context.update(src)

        if merged_context:
            context_parts: list[str] = []
            if "project_rules" in merged_context:
                context_parts.append(f"[Project Rules]\n{merged_context['project_rules']}")
            if "plan_progress" in merged_context:
                pp = merged_context["plan_progress"]
                context_parts.append(f"[Plan Progress] {pp.get('completed_steps', 0)}/{pp.get('total_steps', 0)} steps completed. Current: {pp.get('current_step', 'none')}")
            if "recent_failures" in merged_context:
                failures = merged_context["recent_failures"]
                context_parts.append(f"[Recent Failures]\n" + "\n".join(f"- {f}" for f in failures[:5]))
                recovery = failure_recovery_instruction([str(f) for f in failures[:5]])
                if recovery:
                    context_parts.append(f"[Failure Recovery]\n{recovery}")
            if "session_memory_summary" in merged_context:
                ms = merged_context["session_memory_summary"]
                if isinstance(ms, dict):
                    context_parts.append(format_session_memory_summary(ms))
            if "git_context" in merged_context:
                gc = merged_context["git_context"]
                context_parts.append(f"[Git] branch={gc.get('branch', '?')}, head={gc.get('head', '?')}, dirty={gc.get('dirty_files_count', 0)}")
            elif "git_state" in merged_context:
                gs = merged_context["git_state"]
                current = gs.get("current") or {}
                parts = []
                if gs.get("task_branch"):
                    parts.append(f"task_branch={gs['task_branch']}")
                if current.get("branch"):
                    parts.append(f"branch={current['branch']}")
                if current.get("head"):
                    parts.append(f"head={current['head'][:12]}")
                if parts:
                    context_parts.append(f"[Git] {' '.join(parts)}")
            # Inject active plan from state metadata
            if "active_plan" in merged_context:
                ap = merged_context["active_plan"]
                plan_lines = []
                if ap.get("plan_summary"):
                    plan_lines.append(f"Summary: {ap['plan_summary']}")
                if ap.get("plan_files"):
                    plan_lines.append(f"Planned files: {', '.join(ap['plan_files'])}")
                if ap.get("plan_steps"):
                    for s in ap["plan_steps"]:
                        sid = s.get("id", "?")
                        desc = s.get("description", "")
                        status = s.get("status", "pending")
                        plan_lines.append(f"  [{sid}] ({status}) {desc}")
                if plan_lines:
                    context_parts.append("[Active Plan — follow this step by step]\n" + "\n".join(plan_lines))
            if "drift_warning" in merged_context:
                context_parts.append(f"[Drift Warning] {merged_context['drift_warning']}")
            if "empty_stop_retry_instruction" in merged_context:
                context_parts.append(
                    "[Empty Stop Recovery]\n"
                    f"{merged_context['empty_stop_retry_instruction']}"
                )
            if context_parts:
                messages.append(ChatMessage(
                    role="system",
                    content=format_prompt_sections("[Writer Context]", context_parts),
                    metadata={"key": "hook_context", "kind": "constraint"},
                ))

        # 5. Conversation history last. This is the most volatile part of the
        # request and should not precede stable system content.
        if self._initial_history:
            messages.extend(self._initial_history)
        messages.extend(context.history)

        # Fallback: if no messages at all, use user_message from context.
        if not messages and context.user_message:
            messages.append(ChatMessage(role="user", content=context.user_message))

        tools = list(self._effective_tools)
        # Append MCP tools when registry is loaded
        if self._mcp_registry is not None and self._mcp_loaded:
            mcp_defs = self._mcp_registry.tool_definitions()
            if mcp_defs:
                if self._tool_allowlist is not None:
                    mcp_defs = [
                        tool for tool in mcp_defs
                        if str(tool.get("function", {}).get("name", "")) in self._tool_allowlist
                    ]
                tools = tools + mcp_defs
        return LLMRequest(messages=messages, tools=tools)

    async def parse_model_output(
        self, state: RuntimeState, response: LLMResponse
    ) -> KernelTurn:
        """Parse LLMResponse into a KernelTurn.

        Decision logic:
        - If response has tool_calls → continue (tool execution follows).
        - If finish_reason is "stop" and no tool_calls → check for
          wait-signalling action types.  Since this is a text-only response
          we treat it as ``done`` unless the content contains a wait signal.
        - If finish_reason is "length" → continue.
        """
        if state.metadata is None:
            state.metadata = {}

        tool_calls: list[ToolCall] = []
        decision_hint: LoopDecision = "continue"
        wait_reason = ""

        if response.tool_calls:
            state.metadata.pop("empty_stop_count", None)
            state.metadata.pop("empty_stop_without_delivery_count", None)
            state.metadata.pop("empty_stop_retry_instruction", None)
            for index, tc in enumerate(response.tool_calls):
                tool_name = str(tc.name or "").strip()
                # Clarification/user-input actions are control decisions, not
                # executable tools in this minimal experiment.
                if tool_name in _WAIT_ACTION_TYPES:
                    decision_hint = "wait"
                    wait_reason = f"Model requested: {tool_name}"
                    continue
                arguments = tc.arguments if isinstance(tc.arguments, dict) else {}
                call_id = str(tc.id or "").strip()
                if not tool_name:
                    raw_arguments = ""
                    if isinstance(tc.metadata, dict):
                        raw_arguments = str(tc.metadata.get("raw_arguments") or "")
                    arguments = {
                        "reason": "empty_tool_name",
                        "raw_arguments": raw_arguments,
                    }
                    tool_name = "invalid_tool_call"
                    call_id = call_id or f"invalid-tool-call-{index}"
                elif not call_id:
                    call_id = f"functions.{tool_name}:{index}"

                call = ToolCall(
                    id=call_id,
                    name=tool_name,
                    arguments=arguments,
                )
                call = self._annotate_command_permission(call)
                tool_calls.append(call)
        elif response.finish_reason == "stop":
            # Text-only response — check if content signals wait
            content = (response.content or "").lower()
            if any(signal in content for signal in ("ask_clarification", "needs_user_input")):
                decision_hint = "wait"
                wait_reason = "Model text signals wait"
            elif not content.strip():
                attempts = int((state.metadata or {}).get("empty_stop_count", 0))
                has_delivery = _has_delivery_progress(state.metadata or {})
                if attempts <= 0:
                    state.metadata["empty_stop_count"] = 1
                    state.metadata["empty_stop_retry_instruction"] = (
                        "The previous model turn stopped with no final text and no tool calls. "
                        + (
                            "Deliverables already exist, so provide a concise visible final answer "
                            "summarizing completed files, verification, and any caveats. Do not call "
                            "more tools unless required to verify the final answer."
                            if has_delivery
                            else
                            "Continue the task now: either call the needed tools to create and verify "
                            "deliverables, or provide a visible failure reason if the task cannot proceed."
                        )
                    )
                    decision_hint = "continue"
                else:
                    state.metadata["empty_stop_count"] = attempts + 1
                    decision_hint = "failed"
                    wait_reason = "Model stopped twice with no content and no tools."
            else:
                state.metadata.pop("empty_stop_count", None)
                state.metadata.pop("empty_stop_without_delivery_count", None)
                state.metadata.pop("empty_stop_retry_instruction", None)
                decision_hint = "done"
        elif response.finish_reason == "length":
            decision_hint = "continue"
        else:
            # Unknown finish reason — treat as done to avoid infinite loop
            decision_hint = "done"

        reply = response.content or ""
        if decision_hint == "failed" and not reply:
            reply = (
                "模型连续两次返回空结果：没有正文，也没有工具调用。"
                "本次任务已中断，避免把未完成任务误标记为完成。"
            )

        return KernelTurn(
            reply=reply,
            tool_calls=tool_calls,
            decision_hint=decision_hint,
            wait_reason=wait_reason,
        )

    async def execute_tool(
        self, state: RuntimeState, call: ToolCall
    ) -> ToolResult:
        """Execute a tool call via the injectable tool_executor."""
        if call.name == "invalid_tool_call":
            return ToolResult(
                call_id=call.id,
                name=call.name,
                status="failed",
                error="模型返回了无效工具调用：工具名为空。",
                content="请重新选择一个已注册工具，并提供完整参数。",
                metadata=dict(call.arguments if isinstance(call.arguments, dict) else {}),
            )

        if call.requires_approval:
            return ToolResult(
                call_id=call.id,
                name=call.name,
                status="blocked",
                error=(
                    "命令需要运行前确认；当前运行通道未收到用户批准。"
                    "可在设置中将该命令组改为自动允许，或通过审批流程后再执行。"
                ),
                metadata=dict(call.metadata),
            )

        pending_test_repair = ""
        if isinstance(state.metadata, dict):
            pending_test_repair = str(state.metadata.get("test_assertion_repair_required") or "").strip()
        if pending_test_repair and call.name in {"run_command", "run_tests"}:
            return ToolResult(
                call_id=call.id,
                name=call.name,
                status="failed",
                error="Test assertion repair is pending; edit production code before running more commands.",
                content=(
                    "A test command already reached the suite and failed an assertion. "
                    "The next useful action is to modify the relevant production file with edit_file/write_file, "
                    "then rerun the same or equivalent test.\n\n"
                    f"Failure evidence:\n{pending_test_repair}"
                ),
                metadata={"error_type": "TestAssertionRepairPending"},
            )

        if self._tool_executor is None:
            return ToolResult(
                call_id=call.id,
                name=call.name,
                status="ok",
                content=f"[stub] {call.name} executed",
            )

        try:
            if isinstance(self._tool_executor, dict):
                logger.info(f"Executing tool: {call.name} args={call.arguments}")
                handler = self._tool_executor.get(call.name)
                if handler is None:
                    # Return a clear message for tools that are defined in
                    # WRITER_TOOLS but not yet implemented in the executor.
                    # Missing execution is a tool failure, not a successful no-op.
                    return ToolResult(
                        call_id=call.id,
                        name=call.name,
                        status="failed",
                        error=f"工具 {call.name} 不可用：请求了当前环境没有注册的工具。",
                        content=f"可用工具：{', '.join(sorted(self._tool_executor.keys()))}",
                    )
                runtime_keys = {
                    "_runtime_session_id": state.session_id,
                    "_runtime_run_id": state.run_id,
                }
                sentinel = object()
                previous = {key: call.metadata.get(key, sentinel) for key in runtime_keys}
                call.metadata.update(runtime_keys)
                try:
                    result = handler(call)
                    if asyncio.iscoroutine(result):
                        result = await result
                    activated_goal_id = str(result.metadata.get("activate_goal_id") or "").strip()
                    if result.status == "ok" and activated_goal_id:
                        state.metadata["goal_id"] = activated_goal_id
                    return result
                finally:
                    for key, value in previous.items():
                        if value is sentinel:
                            call.metadata.pop(key, None)
                        else:
                            call.metadata[key] = value
            else:
                # Single callable
                result = self._tool_executor(call)
                if asyncio.iscoroutine(result):
                    result = await result
                return result
        except Exception as exc:
            return ToolResult(
                call_id=call.id,
                name=call.name,
                status="failed",
                error=f"Tool execution error: {_exception_summary(exc)}",
                metadata={"error_type": type(exc).__name__},
            )

    async def preflight_tool_calls(
        self,
        state: RuntimeState,
        calls: list[ToolCall],
    ) -> dict[str, ToolResult]:
        _ = state, calls
        return {}

    # -- Agent dispatch --------------------------------------------------------

    async def format_tool_result_for_model(
        self, state: RuntimeState, call: ToolCall, result: ToolResult
    ) -> ChatMessage:
        """Format a ToolResult as a tool-role ChatMessage for the model.

        On failure, includes the original tool call context (name + arguments)
        and actionable guidance so the model can correct course instead of
        blindly retrying the same call.
        """
        _ = state
        return _format_tool_result_for_model(call, result)

    async def verify(
        self,
        state: RuntimeState,
        turn: KernelTurn,
        tool_results: list[ToolResult],
    ) -> VerificationResult:
        """Verify tool execution results.

        Checks performed:
        - If write_file/edit_file was called successfully, verify the file
          actually exists on disk.
        - If files were written, check first 500 chars for stub indicators.
        - If any tool failed, mark verification as failed.
        """
        # Check for tool failures first
        failed = [r for r in tool_results if r.status == "failed"]
        if failed:
            names = ", ".join(r.name for r in failed)
            assertion_failures = [r for r in failed if looks_like_test_assertion_failure(r)]
            if assertion_failures and not _has_delivery_progress(state.metadata):
                failure_context = tool_failure_context(assertion_failures[-1])
                state.metadata["test_assertion_repair_required"] = failure_context
                self._intervention_pending = (
                    "TEST ASSERTION FAILURE DETECTED.\n"
                    "The command reached the test suite and failed an assertion, so this is product feedback, "
                    "not a command/path discovery problem.\n"
                    "Next required action: edit the relevant production file with edit_file or write_file using "
                    "the smallest fix, then rerun an equivalent test command. Do not keep changing Python paths, "
                    "working directories, or equivalent pytest invocations unless the latest output failed before "
                    "tests were collected.\n\n"
                    f"Failure evidence:\n{failure_context}"
                )
            return VerificationResult(
                passed=False,
                required=True,
                summary=f"{len(failed)} tool(s) failed: {names}",
                repair_prompt=f"Tool execution failed: {names}. Check errors and retry.",
                attempt=0,
                max_attempts=3,
            )

        return verify_written_tool_results(self._work_root, tool_results)

    async def decide_next(
        self,
        state: RuntimeState,
        turn: KernelTurn,
        verification: VerificationResult,
        step: KernelStep,
    ) -> LoopDecision:
        """Return the model's decision hint directly.

        The model can stop only by returning a no-tool final response. Any
        tool call is handled by the Core loop as more work, even if this Kit
        accidentally returns ``done``.

        One safety net: if the exact same tool call failure repeats 5+
        consecutive times, stop as failed so it cannot masquerade as done.
        """
        hint = turn.decision_hint

        if any(
            tool_step.result is not None
            and bool(tool_step.result.metadata.get("delegated_approval_pending"))
            for tool_step in step.tool_steps
        ):
            return "wait"

        if self._should_stop_repeated_failure(state, step):
            return "failed"

        if verification.required and not verification.passed:
            if verification.attempt >= verification.max_attempts:
                return "failed"
            return "continue"

        return hint

    def _should_stop_repeated_failure(self, state: RuntimeState, step: KernelStep) -> bool:
        return should_stop_repeated_failure(state.metadata, step.tool_steps)

    @staticmethod
    def _tool_failure_signature(call: ToolCall, result: ToolResult | None) -> str:
        return tool_failure_signature(call, result)

    @staticmethod
    def _tool_failure_context(result: ToolResult) -> str:
        return tool_failure_context(result)

    @staticmethod
    def _looks_like_test_assertion_failure(result: ToolResult) -> bool:
        return looks_like_test_assertion_failure(result)

    async def writeback(
        self,
        state: RuntimeState,
        turn: KernelTurn,
        tool_results: list[ToolResult],
        verification: VerificationResult,
        decision: LoopDecision,
    ) -> None:
        """Track tool calls, statuses, failures, and category-level outcomes."""
        if state.metadata is None:
            state.metadata = {}

        record_tool_outcomes(state.metadata, list(turn.tool_calls), tool_results)

        plan_changed = False

        # Create active plan from write_checklist results
        for tr in tool_results:
            if tr.name == "write_checklist" and tr.status == "ok" and tr.metadata:
                task_plan = tr.metadata.get("task_plan") or {}
                if isinstance(task_plan, dict):
                    task_plan.setdefault("revision", 0)
                    _new_plan_revision(task_plan, "initial checklist created", "create_plan", {
                        "files": task_plan.get("files", []),
                    })
                    state.metadata["task_plan"] = task_plan
                    plan_changed = True
                break

        # Apply explicit incremental checklist updates.
        for tr in tool_results:
            if tr.name != "update_checklist" or tr.status != "ok" or not tr.metadata:
                continue
            update = tr.metadata.get("checklist_update")
            if isinstance(update, dict):
                current_plan = state.metadata.get("task_plan")
                state.metadata["task_plan"] = _apply_checklist_update(
                    current_plan if isinstance(current_plan, dict) else None,
                    update,
                )
                plan_changed = True

        # Auto-complete the current step when its declared deliverables were produced.
        current_plan = state.metadata.get("task_plan")
        if isinstance(current_plan, dict) and _auto_advance_plan(current_plan, tool_results):
            state.metadata["task_plan"] = current_plan
            plan_changed = True

        if plan_changed and isinstance(state.metadata.get("task_plan"), dict):
            state.metadata["active_plan"] = _plan_to_active_plan(state.metadata["task_plan"])

    async def on_run_end(
        self, state: RuntimeState, result: KernelResult
    ) -> None:
        pass


# ---------------------------------------------------------------------------
# 4. run_core_kernel — top-level entry point
# ---------------------------------------------------------------------------


async def run_core_kernel(
    goal: str,
    session_id: str,
    llm_client: Any | None = None,
    tool_executor: dict[str, Callable[..., Awaitable[ToolResult]]]
    | Callable[[ToolCall], Awaitable[ToolResult]]
    | None = None,
    work_root: str | None = None,
    history: list[dict[str, str]] | None = None,
    state_store: RuntimeStateStore | None = None,
    live_event_callback: Callable[[CoreEvent], Awaitable[None]] | None = None,
    runtime_controls: dict[str, dict[str, bool]] | None = None,
    cancel_event: asyncio.Event | None = None,
    guidance_source: Callable[[], list[str]] | None = None,
    guidance_finalizer: Callable[[], list[str] | None] | None = None,
    user_content: str | list[dict[str, Any]] | None = None,
    run_id: str = "",
    turn_id: str = "",
    operation_executor: Callable[[str, dict[str, Any], dict[str, Any]], Awaitable[Any]] | None = None,
    goal_manager: GoalManager | None = None,
    goal_id: str = "",
    project_id: str = "",
    model_id: str = "",
) -> KernelResult:
    """Run Writer through CoreLoopKernel.

    Args:
        goal: The user's task / message.
        session_id: Session identifier.
        user_content: Optional provider-neutral current user content blocks
            for model-visible multimodal input. ``goal`` remains the plain
            text task used by Writer state and planning logic.
        llm_client: Writer llm_client (has .chat_full) or Core LLMClient.
            If None, a ``WriterLLMClientAdapter`` must be constructable —
            but for testing you should always pass one explicitly.
        tool_executor: Injectable tool executor — either a dict mapping
            tool names to async callables, or a single async callable.
            If None and *work_root* is provided, the bounded read-write
            default tool executor is used. If None and *work_root* is also
            None, tool execution returns stub ok results.
            When both *tool_executor* and *work_root* are provided, the
            injected executor takes priority but the defaults are merged
            underneath — so an injected dict can override individual
            tools while still falling back to default handlers for the rest.
        work_root: Working directory root for file tools.  When provided
            (and *tool_executor* is None or a dict), default tool handlers
            are enabled.  When omitted, no real file operations are
            available — only stub results or the injected executor.
        history: Prior conversation turns as ``[{"role": ..., "content":
            "..."}]`` dicts. ``system`` summary blocks are preserved;
            ``user`` and ``assistant`` roles remain part of the visible
            conversation; ``tool``, ``internal``, or other roles are
            filtered out. These messages are prepended to the LLM request
            so the model sees the full multi-turn context. The current
            user message (``goal``) must NOT be included here — the
            kernel appends it automatically. Token-driven compaction handles
            context pressure; history is not truncated by message count.
        state_store: Optional Core runtime state store. Services should pass
            their persistent member-backed store; tests may rely on the
            in-memory default.
        live_event_callback: Optional callback invoked as each Core event is
            emitted. Services use it to bridge runtime progress to SSE.

    Returns:
        KernelResult with the final decision, message, and step history.
    """
    # Build LLMClient adapter
    if llm_client is None:
        raise ValueError("llm_client must be provided")

    # Keep a reference to the raw Writer LLM client before wrapping for CoreLLMClient
    raw_writer_client: Any = None
    if hasattr(llm_client, "complete"):
        # Already a Core LLMClient
        core_llm = llm_client
        raw_writer_client = llm_client
    elif hasattr(llm_client, "chat_full"):
        # Writer-style client
        raw_writer_client = llm_client
        core_llm = WriterLLMClientAdapter(writer_client=llm_client)
    else:
        raise ValueError(
            "llm_client must have .chat_full() or .complete() method"
        )

    # Resolve effective tool_executor
    sub_agent_runner = KernelSubAgentRunner(
        llm_client=core_llm,
        work_root=work_root,
    )
    effective_executor = _resolve_tool_executor(
        tool_executor,
        work_root,
        live_event_callback,
        operation_executor,
        sub_agent_runner=sub_agent_runner,
    )

    # Build state store before Kit so sub sessions can reuse the same storage.
    effective_state_store = state_store or InMemoryRuntimeStateStore()

    # Convert history dicts to ChatMessage objects. Keep summary system entries
    # model-visible after capping, then use the remaining slots for the latest
    # conversation turns while preserving original order in the final list.
    initial_history: list[ChatMessage] = []
    if history:
        filtered_history: list[tuple[int, ChatMessage]] = []
        for index, entry in enumerate(history):
            role = entry.get("role", "")
            content = entry.get("content", "")
            if not content:
                continue
            if role in ("system", "user", "assistant"):
                metadata: dict[str, Any] = {}
                message_id = str(entry.get("id") or entry.get("message_id") or "").strip()
                if message_id:
                    metadata["message_id"] = message_id
                    metadata["writer_message_id"] = message_id
                if role == "system" and str(content).startswith(COMPACTION_PREFIX):
                    metadata["key"] = "context_compaction_summary"
                    metadata["kind"] = "history"
                filtered_history.append((index, ChatMessage(role=role, content=content, metadata=metadata)))
        initial_history.extend(message for _, message in filtered_history)

    context_window = int(getattr(raw_writer_client, "context_window", 0) or 0)
    context_window_tokens = context_window if context_window > 0 else None
    compact_trigger_ratio = 0.8

    # Build Kit with initial_history, work_root, and agent_llm_client for agent support
    kit = WriterKit(
        tool_executor=effective_executor,
        initial_history=initial_history,
        work_root=work_root or "",
        agent_llm_client=raw_writer_client,
        runtime_controls=runtime_controls,
        core_event_callback=live_event_callback,
        context_window_tokens=context_window_tokens,
        compact_trigger_ratio=compact_trigger_ratio,
        cancel_event=cancel_event,
        runtime_state_store=effective_state_store,
    )

    # Build event sink (collects events in memory)
    event_log = InMemoryEventLog()

    class _EventSink:
        async def emit(self, event: CoreEvent) -> None:
            event_log.append(event)
            if live_event_callback is not None:
                await live_event_callback(event)

    # Build policy
    policy = LoopPolicy(
        context_window_tokens=context_window_tokens,
        compact_trigger_ratio=compact_trigger_ratio,
        parallel_tool_names=(),
    )

    # Build kernel. WriterKit handles all lifecycle logic: persona, tools,
    # verification, drift detection, and writeback.
    kernel = CoreLoopKernel(
        kit=kit,
        llm_client=core_llm,
        state_store=effective_state_store,
        event_sink=_EventSink(),
        policy=policy,
        hook_engine=_build_plugin_hook_engine(work_root),
        completion_gate=(
            GoalCompletionGate(
                goal_manager,
                goal_id,
                ModelGoalEvaluator(core_llm),
            )
            if goal_manager is not None
            else None
        ),
    )

    # Wire cancel event: if provided, set it on the kernel so the loop
    # checks it each iteration
    if cancel_event is not None:
        # We need to monitor the external cancel event and forward to kernel
        async def _cancel_watcher():
            await cancel_event.wait()
            kernel.cancel()
        watcher_task = asyncio.create_task(_cancel_watcher())
    else:
        watcher_task = None

    # Build turn input
    turn_input = RuntimeTurnInput(
        user_message=goal,
        user_content=user_content,
        run_id=run_id,
        turn_id=turn_id,
        metadata={"session_id": session_id, "goal_id": str(goal_id or ""),
                    "project_id": str(project_id or ""), "model_id": str(model_id or "").strip()},
        guidance_source=guidance_source,
        guidance_finalizer=guidance_finalizer,
    )

    # Run
    result = await kernel.run(turn_input)

    # Clean up cancel watcher
    if watcher_task is not None and not watcher_task.done():
        watcher_task.cancel()
        try:
            await watcher_task
        except asyncio.CancelledError:
            pass

    # --- Observability: enrich KernelResult.metadata from event_log ---
    # Collect all CoreEvents from the InMemoryEventLog (no global variables).
    all_events = [evt for _, evt in event_log.replay_since()]

    # Build core_events summary list (lightweight dicts, no full prompt/output).
    # Streaming events are compacted to logical blocks so page refresh does not
    # reconstruct one UI card per token/delta.
    core_events_summary = compact_core_events_for_summary(all_events)
    response_blocks_summary = build_response_blocks_for_summary(core_events_summary)

    # Build tool_results_summary from steps
    tool_results_summary: list[dict[str, Any]] = []
    for step in result.steps:
        for ts in step.tool_steps:
            entry: dict[str, Any] = {
                "call_id": ts.call.id,
                "tool_name": ts.call.name,
                "status": ts.result.status,
            }
            if ts.call.arguments:
                entry["args"] = dict(ts.call.arguments)
            exit_code = ts.result.metadata.get("exit_code")
            if isinstance(exit_code, int):
                entry["exit_code"] = exit_code
            # Include tool output for display (unlimited)
            if ts.result.content:
                entry["content_preview"] = ts.result.content
            if ts.result.status == "failed" and ts.result.error:
                entry["error"] = ts.result.error[:200]
            if ts.result.artifacts:
                entry["artifacts"] = [artifact.to_dict() for artifact in ts.result.artifacts]
            if ts.result.metadata:
                entry["metadata"] = dict(ts.result.metadata)
            tool_results_summary.append(entry)

    # Build verification_summaries from steps
    verification_summaries: list[dict[str, Any]] = []
    for step in result.steps:
        if step.verification is not None:
            verification_summaries.append({
                "passed": step.verification.passed,
                "required": step.verification.required,
                "summary": step.verification.summary,
                "attempt": step.verification.attempt,
                "max_attempts": step.verification.max_attempts,
            })

    usage_prompt_tokens = 0
    usage_completion_tokens = 0
    usage_total_tokens = 0
    usage_cached_tokens = 0
    for event in all_events:
        payload = event.payload or {}
        if event.name == "runtime.usage":
            usage = payload.get("usage")
        elif event.name == "runtime.reply_delta":
            usage = payload.get("usage")
        else:
            continue
        if not isinstance(usage, dict):
            continue
        prompt_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
        total_tokens = int(usage.get("total_tokens") or (prompt_tokens + completion_tokens) or 0)
        usage_prompt_tokens += prompt_tokens
        usage_completion_tokens += completion_tokens
        usage_total_tokens += total_tokens
        prompt_details = usage.get("prompt_tokens_details") or usage.get("input_tokens_details") or {}
        if isinstance(prompt_details, dict):
            usage_cached_tokens += int(
                prompt_details.get("cached_tokens")
                or prompt_details.get("cache_read_input_tokens")
                or 0
            )

    duration_ms = 0
    if all_events:
        duration_ms = max(0, all_events[-1].timestamp_ms - all_events[0].timestamp_ms)
    cache_hit_rate = (
        round(usage_cached_tokens / usage_prompt_tokens, 4)
        if usage_prompt_tokens > 0 and usage_cached_tokens > 0
        else None
    )
    context_metrics = {}
    state_metadata = result.state.metadata if result.state and isinstance(result.state.metadata, dict) else {}
    raw_context_metrics = state_metadata.get("runtime_context_metrics")
    if isinstance(raw_context_metrics, dict):
        context_metrics = dict(raw_context_metrics)

    # Enrich metadata (KernelResult.metadata is dict[str, Any])
    result.metadata["core_events"] = core_events_summary
    result.metadata["response_blocks"] = response_blocks_summary
    result.metadata["steps_count"] = len(result.steps)
    result.metadata["tool_results_summary"] = tool_results_summary
    result.metadata["verification_summaries"] = verification_summaries
    result.metadata["runtime_metrics"] = {
        "duration_ms": duration_ms,
        "input_tokens": usage_prompt_tokens,
        "output_tokens": usage_completion_tokens,
        "total_tokens": usage_total_tokens,
        "cache_hit_rate": cache_hit_rate,
        "llm_calls": len(result.steps),
        **context_metrics,
    }
    if result.decision:
        result.metadata["decision"] = result.decision
    if result.error:
        result.metadata["error"] = result.error

    return result


async def run_sub_agent_turn(
    *,
    parent_state: RuntimeState,
    delegated_session: dict[str, Any],
    prompt: str,
    llm_client: Any,
    work_root: str,
    runtime_controls: dict[str, dict[str, bool]] | None = None,
    live_event_callback: Callable[[CoreEvent], Awaitable[None]] | None = None,
    parent_state_store: Any | None = None,
) -> KernelResult:
    """Continue an existing delegated session with one user-authored turn."""
    return await _run_existing_sub_agent_turn(
        parent_state=parent_state,
        delegated_session=delegated_session,
        prompt=prompt,
        llm_client=llm_client,
        work_root=work_root,
        runtime_controls=runtime_controls,
        live_event_callback=live_event_callback,
        clear_pending=False,
        parent_state_store=parent_state_store,
    )


async def resume_sub_agent_turn(
    *,
    parent_state: RuntimeState,
    delegated_session: dict[str, Any],
    prompt: str,
    llm_client: Any,
    work_root: str,
    runtime_controls: dict[str, dict[str, bool]] | None = None,
    live_event_callback: Callable[[CoreEvent], Awaitable[None]] | None = None,
    parent_state_store: Any | None = None,
) -> KernelResult:
    """Resume a delegated session after its pending approval is resolved."""
    return await _run_existing_sub_agent_turn(
        parent_state=parent_state,
        delegated_session=delegated_session,
        prompt=prompt,
        llm_client=llm_client,
        work_root=work_root,
        runtime_controls=runtime_controls,
        live_event_callback=live_event_callback,
        clear_pending=True,
        parent_state_store=parent_state_store,
    )


async def _run_existing_sub_agent_turn(
    *,
    parent_state: RuntimeState,
    delegated_session: dict[str, Any],
    prompt: str,
    llm_client: Any,
    work_root: str,
    runtime_controls: dict[str, dict[str, bool]] | None,
    live_event_callback: Callable[[CoreEvent], Awaitable[None]] | None,
    clear_pending: bool,
    parent_state_store: Any | None,
) -> KernelResult:
    raw_writer_client = llm_client
    core_llm = llm_client if hasattr(llm_client, "complete") else WriterLLMClientAdapter(writer_client=llm_client)
    context_window = int(getattr(raw_writer_client, "context_window", 0) or 0)
    context_window_tokens = context_window if context_window > 0 else None
    available_tools = frozenset(str(item) for item in delegated_session.get("tools", []) if str(item))
    agent_name = normalize_sub_session_agent_name(str(delegated_session.get("agent") or ""))
    sub_session_id = str(delegated_session.get("session_id") or "")
    if not sub_session_id:
        raise ValueError("Delegated session id is required")

    state_store = SubSessionRuntimeStateStore(
        parent_state,
        parent_state_store=parent_state_store,
    )
    child_state = await state_store.get(sub_session_id)
    if child_state is None:
        raise ValueError("Delegated runtime state not found")
    if not clear_pending and (
        child_state.metadata.get("pending_approval")
        or child_state.metadata.get("pending_waiting_request")
    ):
        raise ValueError("Sub-agent is waiting for user approval")
    if clear_pending:
        child_state.metadata.pop("pending_approval", None)
        child_state.metadata.pop("pending_waiting_request", None)
    child_state.status = "running"
    child_state.loop_state = "continue"
    history = await state_store.get_history(sub_session_id)
    await state_store.save_checkpoint(child_state, history)

    effective_executor = _resolve_tool_executor(None, work_root, live_event_callback)
    nested_kit = WriterKit(
        tool_executor=effective_executor,
        work_root=work_root,
        agent_llm_client=None,
        runtime_controls=runtime_controls,
        tool_allowlist=available_tools,
        core_event_callback=live_event_callback,
        context_window_tokens=context_window_tokens,
        compact_trigger_ratio=0.8,
    )
    parent_call_id = str(
        delegated_session.get("parent_call_id")
        or delegated_session.get("parent_tool_call_id")
        or ""
    )
    parent_run_id = str(delegated_session.get("parent_run_id") or parent_state.run_id)
    parent_turn_id = str(delegated_session.get("parent_turn_id") or parent_run_id)
    call = AgentCall(
        name="sub",
        task=str(delegated_session.get("task") or prompt),
        options={
            "_agent_run_id": str(delegated_session.get("agent_run_id") or ""),
            "_sub_line_id": str(delegated_session.get("sub_line_id") or ""),
            "_parent_session_id": parent_state.session_id,
            "_parent_run_id": parent_run_id,
            "_parent_tool_call_id": parent_call_id,
        },
    )
    parent_sink = (
        CollectingEventSink(live_callback=live_event_callback, should_collect=lambda _event: False)
        if live_event_callback is not None
        else None
    )
    event_sink = SubAgentEventForwardingSink(
        parent_sink=parent_sink,
        parent_session_id=parent_state.session_id,
        agent=agent_name,
        task=str(delegated_session.get("task") or prompt),
        parent_call_id=parent_call_id,
        parent_run_id=parent_run_id,
        parent_turn_id=parent_turn_id,
    )
    kernel = CoreLoopKernel(
        kit=nested_kit,
        llm_client=core_llm,
        state_store=state_store,
        event_sink=event_sink,
        policy=LoopPolicy(
            context_window_tokens=context_window_tokens,
            compact_trigger_ratio=0.8,
            parallel_tool_names=(),
        ),
        hook_engine=_build_plugin_hook_engine(work_root),
    )
    result = await kernel.run(RuntimeTurnInput(
        user_message=prompt,
        metadata={"session_id": sub_session_id},
    ))
    if result.decision == "wait":
        child_state = await state_store.get(sub_session_id)
        pending = child_state.metadata.get("pending_approval") if child_state is not None else None
        waiting = child_state.metadata.get("pending_waiting_request") if child_state is not None else None
        if isinstance(pending, dict):
            parent_state.metadata["pending_approval"] = {
                **pending,
                "delegated_session": delegated_session,
            }
            if isinstance(waiting, dict):
                parent_state.metadata["pending_waiting_request"] = dict(waiting)
    return result


