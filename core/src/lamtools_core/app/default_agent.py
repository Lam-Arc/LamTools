"""Default Core Agent assembly."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lamtools_core.event import CollectingEventSink, EventSink
from lamtools_core.llm import ChatMessage
from lamtools_core.composer_commands import (
    build_composer_command_catalog,
    default_core_resource_roots,
    normalize_command_name,
)
from lamtools_core.checkpoint import CoreCheckpointCoordinator, register_checkpoint_operations
from lamtools_core.member import PromptFragment, StaticMemberKit
from lamtools_core.runtime import (
    InMemoryRuntimeStateStore,
    RuntimeApprovalStore,
    RuntimeStateConflictError,
    RuntimeStateStore,
    RuntimeTaskRegistry,
    RuntimeTurnInput,
    default_runtime_task_registry,
)
from lamtools_core.skills import SkillRegistry
from lamtools_core.session import InMemorySessionStore, SessionStore
from lamtools_core.snapshot import InMemorySnapshotStore, SnapshotStore
from lamtools_core.tool import ToolSpec

from .base_agent import (
    assemble_core_agent_plugins,
    build_core_plugin_operation_catalog,
    CoreBaseAgentConfig,
    CoreBaseAgentKit,
    core_events_to_run_items,
    core_events_to_snapshot,
)
from .command_execution import CommandActionHandler, compact_runtime_history, execute_command_action
from .approval_resolution import ApprovalResolutionLifecycle
from .agent_app import AgentApp, AgentSpec, ModelProvider, ModelTurnOutput, TurnInput
from .event_store import AppEventEnvelope, CORE_RUN_ITEM_METHOD, SqlAlchemyAppEventStore
from .live_approval import normalize_approval_request
from .operation_catalog import OperationCatalog, OperationRequest, OperationResult
from .persistence_host import AppPersistenceHost
from .snapshot_store import SqlAlchemyThreadSnapshotStore


@dataclass(frozen=True)
class CoreAgentSpec:
    id: str = "core-agent"
    member_id: str = "core"
    name: str = "Core Agent"
    instructions: str = "You are a general LamTools Core agent. Use available tools when useful."
    default_model: str = ""
    prompt_fragments: list[PromptFragment] = field(default_factory=list)
    tool_specs: list[ToolSpec] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CoreAgentPaths:
    data_dir: Path | str
    work_root: Path | str

    def __post_init__(self) -> None:
        object.__setattr__(self, "data_dir", Path(self.data_dir))
        object.__setattr__(self, "work_root", Path(self.work_root))


ModelProviderCallable = Callable[[Any], ModelTurnOutput | Awaitable[ModelTurnOutput]]


@dataclass(frozen=True)
class CoreAgentRuntimeOptions:
    model_id: str
    thinking_enabled: bool | None = None
    thinking_budget: int | None = None
    shallow_thinking_enabled: bool = False
    context_window_tokens: int | None = None


def create_core_agent_operations(
    *,
    spec: CoreAgentSpec | None = None,
    paths: CoreAgentPaths,
    model_provider: ModelProvider | ModelProviderCallable,
    plugin_roots: list[Path | str] | None = None,
    session_store: SessionStore | None = None,
    snapshot_store: SnapshotStore | None = None,
    db_session_factory: Callable[[], Any] | None = None,
    app_event_store: SqlAlchemyAppEventStore | None = None,
    thread_snapshot_store: SqlAlchemyThreadSnapshotStore | None = None,
    app_event_hub: Any | None = None,
    command_core_roots: list[Path | str] | None = None,
    command_member_roots: list[Path | str] | None = None,
    command_action_handlers: Mapping[str, CommandActionHandler] | None = None,
    runtime_state_store: RuntimeStateStore | None = None,
    runtime_task_registry: RuntimeTaskRegistry | None = None,
    enable_turn_checkpoints: bool = False,
) -> OperationCatalog:
    spec = spec or CoreAgentSpec()
    runtime_state_store = runtime_state_store or InMemoryRuntimeStateStore()
    runtime_task_registry = runtime_task_registry or default_runtime_task_registry()
    kit = StaticMemberKit(
        id=spec.member_id,
        display_name=spec.name,
        prompts=spec.prompt_fragments,
        tools=spec.tool_specs,
    )
    app = AgentApp(
        spec=AgentSpec(
            id=spec.id,
            name=spec.name,
            instructions=spec.instructions,
            default_model=spec.default_model,
            tools=spec.tool_specs,
            metadata={
                **spec.metadata,
                "data_dir": str(paths.data_dir),
                "work_root": str(paths.work_root),
            },
        ),
        kit=kit,
        model_provider=model_provider,
        session_store=session_store or InMemorySessionStore(),
        snapshot_store=snapshot_store or InMemorySnapshotStore(),
    )
    catalog = OperationCatalog()
    resolved_command_core_roots = [
        Path(item) for item in (command_core_roots or default_core_resource_roots())
    ]
    resolved_command_member_roots = [Path(item) for item in (command_member_roots or [])]

    def checkpoint_coordinator(work_root: Path | str) -> CoreCheckpointCoordinator | None:
        if db_session_factory is None or not enable_turn_checkpoints:
            return None
        return CoreCheckpointCoordinator(
            work_root=work_root,
            session_factory=db_session_factory,  # type: ignore[arg-type]
            storage_root=Path(paths.data_dir) / "checkpoints",
        )

    def command_skill_registry() -> SkillRegistry:
        plugin_assembly = assemble_core_agent_plugins(
            data_dir=paths.data_dir,
            work_root=paths.work_root,
            plugin_roots=plugin_roots,
        )
        return SkillRegistry(
            explicit_roots=[
                *resolved_command_member_roots,
                *resolved_command_core_roots,
                *plugin_assembly.get("skill_roots", []),
            ]
        )

    async def turn_start(request: OperationRequest) -> OperationResult:
        thread_id = str(request.payload.get("thread_id") or request.payload.get("session_id") or "").strip()
        message = str(request.payload.get("message") or request.payload.get("user_message") or "").strip()
        requested_turn_id = str(request.payload.get("turn_id") or request.payload.get("turnId") or "").strip()
        requested_run_id = str(request.payload.get("run_id") or request.payload.get("runId") or requested_turn_id).strip()
        effective_turn_id = requested_turn_id or (
            f"{thread_id}:turn:{requested_run_id}" if requested_run_id else ""
        )
        if not thread_id:
            return OperationResult(name=request.name, status="error", payload={"error": "thread_id is required"})
        if not message:
            return OperationResult(name=request.name, status="error", payload={"error": "message is required"})
        runtime_work_root = _work_root_from_request(paths, request)
        if _is_llm_client(model_provider):
            from lamtools_core.kernel.loop import CoreLoopKernel
            from lamtools_core.kernel.policy import LoopPolicy
            from lamtools_core.tool.default_toolbox import build_core_toolbox

            runtime_options = _runtime_options_from_request(spec, request)
            runtime_model_provider = _model_provider_for_runtime(
                model_provider,
                runtime_options=runtime_options,
            )

            async def live_callback(event: Any) -> None:
                await _persist_core_event_live(
                    event,
                    thread_id=thread_id,
                    db_session_factory=db_session_factory,
                    app_event_store=app_event_store,
                    thread_snapshot_store=thread_snapshot_store,
                    app_event_hub=app_event_hub,
                )

            sink = CollectingEventSink(
                live_callback if app_event_hub is not None else None,
                should_collect=_should_collect_core_event,
            )
            approval_policy = str(request.payload.get("approval_policy") or "require")
            if approval_policy not in {"require", "auto_approve"}:
                approval_policy = "require"
            plugin_assembly = assemble_core_agent_plugins(
                data_dir=paths.data_dir,
                work_root=runtime_work_root,
                plugin_roots=plugin_roots,
            )
            turn_checkpoint_coordinator = checkpoint_coordinator(runtime_work_root)
            toolbox, mcp_registry = await _build_core_runtime_toolbox(
                work_root=runtime_work_root,
                plugin_assembly=plugin_assembly,
                approval_policy=approval_policy,
                llm_client=runtime_model_provider,
                model_id=runtime_options.model_id,
                instructions=spec.instructions,
                context_window_tokens=runtime_options.context_window_tokens,
                thinking_enabled=runtime_options.thinking_enabled,
                thinking_budget=runtime_options.thinking_budget,
                sub_agent_state_store=runtime_state_store,
                sub_agent_session_prefix=thread_id,
                sub_agent_event_sink=sink,
                checkpoint_coordinator=turn_checkpoint_coordinator,
            )
            try:
                kernel = CoreLoopKernel(
                    kit=CoreBaseAgentKit(
                        work_root=runtime_work_root,
                        config=CoreBaseAgentConfig(
                            model_id=runtime_options.model_id,
                            instructions=spec.instructions,
                            thinking_enabled=runtime_options.thinking_enabled,
                            thinking_budget=runtime_options.thinking_budget,
                            approval_policy=approval_policy,  # type: ignore[arg-type]
                        ),
                        toolbox=toolbox,
                    ),
                    llm_client=runtime_model_provider,  # type: ignore[arg-type]
                    state_store=runtime_state_store,
                    event_sink=sink,
                    policy=LoopPolicy(
                        model_timeout_seconds=360,
                        model_retries=3,
                        persist_steps=True,
                        context_window_tokens=runtime_options.context_window_tokens,
                    ),
                    hook_engine=plugin_assembly["hook_engine"],
                    checkpoint_coordinator=turn_checkpoint_coordinator,
                )
                kernel_result = await kernel.run(
                    RuntimeTurnInput(
                        user_message=message,
                        run_id=requested_run_id,
                        turn_id=effective_turn_id,
                        guidance_source=runtime_task_registry.guidance_source(
                            thread_id,
                            run_id=requested_run_id or effective_turn_id,
                        ),
                        guidance_finalizer=runtime_task_registry.guidance_finalizer(
                            thread_id,
                            run_id=requested_run_id or effective_turn_id,
                        ),
                        metadata={
                            **request.metadata,
                            **dict(request.payload.get("metadata") or {}),
                            "session_id": thread_id,
                            "data_dir": str(paths.data_dir),
                            "work_root": str(runtime_work_root),
                            "model_id": runtime_options.model_id,
                            **(
                                {"thinking_enabled": runtime_options.thinking_enabled}
                                if runtime_options.thinking_enabled is not None
                                else {}
                            ),
                            **(
                                {"thinking_budget": runtime_options.thinking_budget}
                                if runtime_options.thinking_budget is not None
                                else {}
                            ),
                            "shallow_thinking_enabled": runtime_options.shallow_thinking_enabled,
                            **(
                                {"context_window_tokens": runtime_options.context_window_tokens}
                                if runtime_options.context_window_tokens is not None
                                else {}
                            ),
                        },
                    )
                )
            finally:
                await _close_mcp_registry(mcp_registry)
            run_items = core_events_to_run_items(sink.events, thread_id=thread_id)
            snapshot = await _persist_run_items(
                run_items,
                db_session_factory=db_session_factory,
                app_event_store=app_event_store,
                thread_snapshot_store=thread_snapshot_store,
            )
            if snapshot is None:
                snapshot = core_events_to_snapshot(sink.events, thread_id=thread_id)
            return OperationResult(
                name=request.name,
                status="ok" if kernel_result.decision in {"done", "wait"} else "error",
                payload={
                    "thread_id": kernel_result.session_id,
                    "run_id": kernel_result.run_id,
                    "turn_id": effective_turn_id or f"{kernel_result.session_id}:turn:{kernel_result.run_id}",
                    "message": kernel_result.message,
                    "decision": kernel_result.decision,
                    "snapshot": snapshot,
                    "run_items": [item.to_dict() for item in run_items],
                    "events": [event.to_dict() for event in sink.events],
                    **({"events_persisted_live": True} if app_event_hub is not None else {}),
                    **({"error": kernel_result.error} if kernel_result.error else {}),
                },
            )
        result = await app.run_turn(
            TurnInput(
                thread_id=thread_id,
                user_message=message,
                run_id=requested_run_id,
                turn_id=effective_turn_id,
                metadata={
                    **request.metadata,
                    **dict(request.payload.get("metadata") or {}),
                    "data_dir": str(paths.data_dir),
                    "work_root": str(runtime_work_root),
                },
            )
        )
        return OperationResult(
            name=request.name,
            payload={
                "thread_id": result.thread_id,
                "run_id": result.run_id,
                "turn_id": result.turn_id,
                "message": result.message,
                "snapshot": result.snapshot,
                "events": [event.to_dict() for event in result.events],
            },
        )

    async def approval_respond(request: OperationRequest) -> OperationResult:
        if _is_llm_client(model_provider):
            from lamtools_core.event import CoreEvent
            from lamtools_core.kernel.loop import CoreLoopKernel
            from lamtools_core.kernel.policy import LoopPolicy
            from lamtools_core.tool import ToolCall
            from lamtools_core.tool.approval_continuation import (
                ApprovedToolExecution,
                approved_tool_continuation_prompt,
                guidance_continuation_prompt,
                resolve_waiting_decision,
            )
            from lamtools_core.tool.default_toolbox import build_core_toolbox

            async def resolve_pending_request(thread_id: str) -> str | None:
                pending_state = await runtime_state_store.get(thread_id)
                pending = pending_state.metadata.get("pending_approval") if pending_state is not None else None
                pending_call = pending.get("tool_call") if isinstance(pending, dict) else None
                return str(
                    pending.get("request_id") if isinstance(pending, dict) else pending_call.get("id") if isinstance(pending_call, dict) else ""
                ) or None

            try:
                normalized = await normalize_approval_request(
                    request.payload,
                    resolve_pending_request=resolve_pending_request,
                )
            except ValueError as exc:
                return OperationResult(name=request.name, status="error", payload={"error": str(exc)})
            approval_request_id = normalized.request_id
            thread_id = normalized.thread_id
            state = await runtime_state_store.get(thread_id) if thread_id else None
            if state is None and approval_request_id and isinstance(runtime_state_store, RuntimeApprovalStore):
                state = await runtime_state_store.find_pending_approval(approval_request_id)
                thread_id = state.session_id if state is not None else ""
            if not thread_id:
                return OperationResult(
                    name=request.name,
                    status="error",
                    payload={"error": "thread_id or pending request_id is required"},
                )
            if state is None:
                return OperationResult(name=request.name, status="error", payload={"error": "thread state not found"})
            pending = state.metadata.get("pending_approval") if isinstance(state.metadata, dict) else None
            pending_call = pending.get("tool_call") if isinstance(pending, dict) else None
            if not isinstance(pending_call, dict):
                return OperationResult(name=request.name, status="error", payload={"error": "no pending approval"})
            expected_request_id = str(pending.get("request_id") or pending_call.get("id") or "")
            if approval_request_id and expected_request_id and approval_request_id != expected_request_id:
                return OperationResult(name=request.name, status="error", payload={"error": "approval request mismatch"})
            if str(pending.get("status") or "") == "executing":
                return OperationResult(
                    name=request.name,
                    status="error",
                    payload={"error": "approval already resolving"},
                )
            try:
                decision = resolve_waiting_decision(
                    normalized.decision,
                    normalized.guidance,
                )
            except ValueError as exc:
                return OperationResult(name=request.name, status="error", payload={"error": str(exc)})
            for claim_attempt in range(2):
                claimed_pending = dict(pending)
                claimed_pending["status"] = "executing"
                claimed_pending["decision"] = decision.action
                state.metadata["pending_approval"] = claimed_pending
                try:
                    await runtime_state_store.save(state)
                    break
                except RuntimeStateConflictError:
                    if claim_attempt > 0:
                        return OperationResult(
                            name=request.name,
                            status="error",
                            payload={"error": "approval already resolving"},
                        )
                    refreshed = await runtime_state_store.get(thread_id)
                    refreshed_pending = (
                        refreshed.metadata.get("pending_approval")
                        if refreshed is not None and isinstance(refreshed.metadata, dict)
                        else None
                    )
                    refreshed_call = (
                        refreshed_pending.get("tool_call")
                        if isinstance(refreshed_pending, dict)
                        else None
                    )
                    if (
                        refreshed is None
                        or not isinstance(refreshed_pending, dict)
                        or not isinstance(refreshed_call, dict)
                        or str(refreshed_pending.get("status") or "") != "waiting"
                        or str(refreshed_pending.get("request_id") or refreshed_call.get("id") or "")
                        != (expected_request_id or approval_request_id)
                    ):
                        return OperationResult(
                            name=request.name,
                            status="error",
                            payload={"error": "approval already resolving"},
                        )
                    state = refreshed
                    pending = refreshed_pending
                    pending_call = refreshed_call

            runtime_options = _runtime_options_from_state(spec, state)
            runtime_work_root = _work_root_from_state(paths, state)
            runtime_model_provider = _model_provider_for_runtime(
                model_provider,
                runtime_options=runtime_options,
            )

            lifecycle = ApprovalResolutionLifecycle(
                operation_name=request.name,
                thread_id=thread_id,
                state=state,
                state_store=runtime_state_store,
                request_id=expected_request_id or approval_request_id,
                tool_call=pending_call,
                decision=decision.action,
                guidance=decision.guidance_text,
                persist_run_items=lambda run_items: _persist_run_items(
                    run_items,
                    db_session_factory=db_session_factory,
                    app_event_store=app_event_store,
                    thread_snapshot_store=thread_snapshot_store,
                    app_event_hub=app_event_hub,
                ),
                run_items_from_events=lambda events: core_events_to_run_items(events, thread_id=thread_id),
                snapshot_from_events=lambda events: core_events_to_snapshot(events, thread_id=thread_id),
            )
            decision_failure = await lifecycle.persist_decision()
            if decision_failure is not None:
                return decision_failure
            decision_durable = request.metadata.get("approval_decision_durable")
            if callable(decision_durable):
                durable_result = decision_durable({
                    "thread_id": thread_id,
                    "run_id": state.run_id,
                    "turn_id": str(state.metadata.get("turn_id") or state.run_id),
                    "work_root": str(runtime_work_root),
                    "decision": decision.action,
                    "snapshot": lifecycle.decision_snapshot,
                })
                if inspect.isawaitable(durable_result):
                    await durable_result
            if decision.action == "deny":
                return await lifecycle.finalize_cancelled()

            try:
                await lifecycle.clear_pending_for_execution()
            except BaseException as exc:
                if isinstance(exc, asyncio.CancelledError):
                    raise
                return await lifecycle.finalize_failure(exc)
            state = lifecycle.state

            delegated_session = pending.get("delegated_session") if isinstance(pending, dict) else None
            if isinstance(delegated_session, dict) and decision.action == "approve":
                async def delegated_live_callback(event: Any) -> None:
                    await _persist_core_event_live(
                        event,
                        thread_id=thread_id,
                        db_session_factory=db_session_factory,
                        app_event_store=app_event_store,
                        thread_snapshot_store=thread_snapshot_store,
                        app_event_hub=app_event_hub,
                    )

                sink = CollectingEventSink(
                    delegated_live_callback if app_event_hub is not None else None,
                    should_collect=_should_collect_core_event,
                )
                mcp_registry = None
                try:
                    plugin_assembly = assemble_core_agent_plugins(
                        data_dir=paths.data_dir,
                        work_root=runtime_work_root,
                        plugin_roots=plugin_roots,
                    )
                    toolbox, mcp_registry = await _build_core_runtime_toolbox(
                        work_root=runtime_work_root,
                        plugin_assembly=plugin_assembly,
                        approval_policy="require",
                        llm_client=runtime_model_provider,
                        model_id=runtime_options.model_id,
                        instructions=spec.instructions,
                        context_window_tokens=runtime_options.context_window_tokens,
                        thinking_enabled=runtime_options.thinking_enabled,
                        thinking_budget=runtime_options.thinking_budget,
                        sub_agent_state_store=runtime_state_store,
                        sub_agent_session_prefix=thread_id,
                        sub_agent_event_sink=sink,
                    )
                    sub_agent_runner = toolbox.sub_agent_runner
                    if sub_agent_runner is None or not hasattr(sub_agent_runner, "resume_approved"):
                        raise RuntimeError("Sub-agent approval continuation is unavailable")
                    child_result = await sub_agent_runner.resume_approved(
                        session_id=str(delegated_session.get("session_id") or ""),
                        pending_call=pending_call,
                        task=str(delegated_session.get("task") or ""),
                        agent=str(delegated_session.get("agent") or ""),
                        parent_call_id=str(delegated_session.get("parent_call_id") or ""),
                        parent_run_id=str(delegated_session.get("parent_run_id") or state.run_id),
                        parent_turn_id=str(
                            delegated_session.get("parent_turn_id")
                            or state.metadata.get("turn_id")
                            or state.run_id
                        ),
                    )
                    if child_result.decision == "wait" and child_result.pending_approval:
                        await _close_mcp_registry(mcp_registry)
                        mcp_registry = None
                        state.metadata["pending_approval"] = {
                            **dict(child_result.pending_approval),
                            "delegated_session": dict(delegated_session),
                        }
                        if child_result.pending_waiting_request:
                            state.metadata["pending_waiting_request"] = dict(
                                child_result.pending_waiting_request
                            )
                        state.status = "waiting"
                        state.loop_state = "wait"
                        await runtime_state_store.save(state)

                        events = _without_approval_response_events(sink.events)
                        run_items = core_events_to_run_items(events, thread_id=thread_id)
                        snapshot = await _persist_run_items(
                            run_items,
                            db_session_factory=db_session_factory,
                            app_event_store=app_event_store,
                            thread_snapshot_store=thread_snapshot_store,
                        )
                        if snapshot is None:
                            snapshot = core_events_to_snapshot(events, thread_id=thread_id)
                        return OperationResult(
                            name=request.name,
                            status="ok",
                            payload={
                                "thread_id": thread_id,
                                "run_id": state.run_id,
                                "turn_id": str(
                                    state.metadata.get("turn_id")
                                    or f"{thread_id}:turn:{state.run_id}"
                                ),
                                "message": child_result.message,
                                "decision": "wait",
                                "snapshot": snapshot,
                                "run_items": [
                                    item.to_dict()
                                    for item in [*lifecycle.decision_run_items, *run_items]
                                ],
                                "events": [event.to_dict() for event in events],
                            },
                        )
                    if not child_result.succeeded:
                        raise RuntimeError(child_result.failure_message())
                    handoff_metadata = {
                        "agent": str(delegated_session.get("agent") or ""),
                        "sub_session_id": child_result.session_id,
                        "sub_run_id": child_result.run_id,
                        "decision": child_result.decision,
                        "model_id": child_result.model_id,
                        "tool_call_count": child_result.tool_call_count,
                        "ended_with_final_response": child_result.ended_with_final_response,
                    }
                    await sink.emit(CoreEvent(
                        name="runtime.tool.finished",
                        category="tool",
                        payload={
                            "tool_name": "sub_agent",
                            "call_id": str(delegated_session.get("parent_call_id") or ""),
                            "status": "ok",
                            "content": child_result.message,
                            "error": "",
                            "metadata": handoff_metadata,
                        },
                        session_id=thread_id,
                        run_id=state.run_id,
                        tags=["tool"],
                    ))
                    kernel = CoreLoopKernel(
                        kit=CoreBaseAgentKit(
                            work_root=runtime_work_root,
                            config=CoreBaseAgentConfig(
                                model_id=runtime_options.model_id,
                                instructions=spec.instructions,
                                thinking_enabled=runtime_options.thinking_enabled,
                                thinking_budget=runtime_options.thinking_budget,
                            ),
                            toolbox=toolbox,
                        ),
                        llm_client=runtime_model_provider,  # type: ignore[arg-type]
                        state_store=runtime_state_store,
                        event_sink=sink,
                        policy=LoopPolicy(
                            model_timeout_seconds=360,
                            model_retries=3,
                            persist_steps=True,
                            context_window_tokens=runtime_options.context_window_tokens,
                        ),
                        hook_engine=plugin_assembly["hook_engine"],
                    )
                    kernel_result = await kernel.run(
                        RuntimeTurnInput(
                            user_message=(
                                "Sub-agent completed the delegated task and handed off this result:\n"
                                f"{child_result.message}"
                            ),
                            state=state,
                            run_id=state.run_id,
                            turn_id=str(state.metadata.get("turn_id") or ""),
                            metadata={
                                **request.metadata,
                                **dict(request.payload.get("metadata") or {}),
                                "session_id": thread_id,
                                "data_dir": str(paths.data_dir),
                                "work_root": str(runtime_work_root),
                                "model_id": runtime_options.model_id,
                                **(
                                    {"thinking_enabled": runtime_options.thinking_enabled}
                                    if runtime_options.thinking_enabled is not None
                                    else {}
                                ),
                                **(
                                    {"thinking_budget": runtime_options.thinking_budget}
                                    if runtime_options.thinking_budget is not None
                                    else {}
                                ),
                            },
                        )
                    )
                except BaseException as exc:
                    if isinstance(exc, asyncio.CancelledError):
                        raise
                    try:
                        await _close_mcp_registry(mcp_registry)
                    except BaseException as close_exc:
                        return await lifecycle.finalize_failure(close_exc)
                    return await lifecycle.finalize_failure(exc)
                try:
                    await _close_mcp_registry(mcp_registry)
                except BaseException as exc:
                    return await lifecycle.finalize_failure(exc)
                events = _without_approval_response_events(sink.events)
                run_items = core_events_to_run_items(events, thread_id=thread_id)
                try:
                    snapshot = await _persist_run_items(
                        run_items,
                        db_session_factory=db_session_factory,
                        app_event_store=app_event_store,
                        thread_snapshot_store=thread_snapshot_store,
                    )
                except BaseException as exc:
                    return await lifecycle.finalize_failure(exc)
                if snapshot is None:
                    snapshot = core_events_to_snapshot(events, thread_id=thread_id)
                return OperationResult(
                    name=request.name,
                    status="ok" if kernel_result.decision in {"done", "wait"} else "error",
                    payload={
                        "thread_id": kernel_result.session_id,
                        "run_id": kernel_result.run_id,
                        "turn_id": str(
                            kernel_result.state.metadata.get("turn_id")
                            or f"{kernel_result.session_id}:turn:{kernel_result.run_id}"
                        ),
                        "message": kernel_result.message,
                        "decision": kernel_result.decision,
                        "snapshot": snapshot,
                        "run_items": [
                            item.to_dict()
                            for item in [*lifecycle.decision_run_items, *run_items]
                        ],
                        "events": [event.to_dict() for event in events],
                        **({"error": kernel_result.error} if kernel_result.error else {}),
                    },
                )

            original_task = str(state.metadata.get("original_user_message") or "")
            tool_name = str(pending_call.get("name") or "")
            tool_args = pending_call.get("arguments") if isinstance(pending_call.get("arguments"), dict) else {}
            if decision.action == "guide":
                try:
                    continuation = guidance_continuation_prompt(
                        original_task=original_task,
                        tool_name=tool_name,
                        tool_args=tool_args,
                        guidance_text=decision.guidance_text,
                    )
                except BaseException as exc:
                    return await lifecycle.finalize_failure(exc)
                approval_events: list[CoreEvent] = []
            else:
                mcp_registry = None
                try:
                    plugin_assembly = assemble_core_agent_plugins(
                        data_dir=paths.data_dir,
                        work_root=runtime_work_root,
                        plugin_roots=plugin_roots,
                    )
                    toolbox, mcp_registry = await _build_core_runtime_toolbox(
                        work_root=runtime_work_root,
                        plugin_assembly=plugin_assembly,
                        approval_policy="auto_approve",
                        llm_client=runtime_model_provider,
                        model_id=runtime_options.model_id,
                        instructions=spec.instructions,
                        context_window_tokens=runtime_options.context_window_tokens,
                        thinking_enabled=runtime_options.thinking_enabled,
                        thinking_budget=runtime_options.thinking_budget,
                        sub_agent_state_store=runtime_state_store,
                        sub_agent_session_prefix=thread_id,
                    )
                    call = ToolCall(
                        id=str(pending_call.get("id") or ""),
                        name=tool_name,
                        arguments=tool_args,
                        metadata={
                            **(pending_call.get("metadata") if isinstance(pending_call.get("metadata"), dict) else {}),
                            "approval": {"approved": True, "auto_approved": True},
                        },
                    )
                    tool_result = await toolbox.execute(call)
                except BaseException as exc:
                    if isinstance(exc, asyncio.CancelledError):
                        raise
                    try:
                        await _close_mcp_registry(mcp_registry)
                    except BaseException as close_exc:
                        return await lifecycle.finalize_failure(close_exc)
                    return await lifecycle.finalize_failure(exc)
                try:
                    await _close_mcp_registry(mcp_registry)
                except BaseException as exc:
                    return await lifecycle.finalize_failure(exc)
                approved_tool = ApprovedToolExecution(
                    tool_name=call.name,
                    tool_args=call.arguments,
                    tool_content=tool_result.content or tool_result.error,
                    tool_status="completed" if tool_result.status == "ok" else "failed",
                )
                approval_events = [
                    CoreEvent(
                        name="runtime.tool.finished",
                        category="tool",
                        payload={
                            "tool_name": call.name,
                            "call_id": call.id,
                            "status": tool_result.status,
                            "content": tool_result.content or "",
                            "error": tool_result.error or "",
                            "artifacts": [artifact.to_dict() for artifact in tool_result.artifacts],
                            "metadata": tool_result.metadata if isinstance(tool_result.metadata, dict) else {},
                        },
                        session_id=thread_id,
                        run_id=state.run_id,
                        tags=["tool"],
                    )
                ]
                if not approved_tool.completed:
                    return await lifecycle.finalize_failure(
                        approved_tool.tool_content,
                        tool_event=approval_events[-1],
                        tool_history=ChatMessage(
                            role="tool",
                            name=call.name,
                            tool_call_id=call.id,
                            content=tool_result.content or tool_result.error,
                        ),
                    )
                try:
                    await lifecycle.persist_tool_history(
                        ChatMessage(
                            role="tool",
                            name=call.name,
                            tool_call_id=call.id,
                            content=tool_result.content or tool_result.error,
                        )
                    )
                    continuation = approved_tool_continuation_prompt(
                        original_task=original_task,
                        approved_tool=approved_tool,
                    )
                except BaseException as exc:
                    return await lifecycle.finalize_failure(exc)

            async def approval_live_callback(event: Any) -> None:
                await _persist_core_event_live(
                    event,
                    thread_id=thread_id,
                    db_session_factory=db_session_factory,
                    app_event_store=app_event_store,
                    thread_snapshot_store=thread_snapshot_store,
                    app_event_hub=app_event_hub,
                )

            sink = CollectingEventSink(
                approval_live_callback if app_event_hub is not None else None,
                should_collect=_should_collect_core_event,
            )
            mcp_registry = None
            try:
                plugin_assembly = assemble_core_agent_plugins(
                    data_dir=paths.data_dir,
                    work_root=runtime_work_root,
                    plugin_roots=plugin_roots,
                )
                toolbox, mcp_registry = await _build_core_runtime_toolbox(
                    work_root=runtime_work_root,
                    plugin_assembly=plugin_assembly,
                    approval_policy="require",
                    llm_client=runtime_model_provider,
                    model_id=runtime_options.model_id,
                    instructions=spec.instructions,
                    context_window_tokens=runtime_options.context_window_tokens,
                    thinking_enabled=runtime_options.thinking_enabled,
                    thinking_budget=runtime_options.thinking_budget,
                    sub_agent_state_store=runtime_state_store,
                    sub_agent_session_prefix=thread_id,
                    sub_agent_event_sink=sink,
                )
                kernel = CoreLoopKernel(
                    kit=CoreBaseAgentKit(
                        work_root=runtime_work_root,
                        config=CoreBaseAgentConfig(
                            model_id=runtime_options.model_id,
                            instructions=spec.instructions,
                            thinking_enabled=runtime_options.thinking_enabled,
                            thinking_budget=runtime_options.thinking_budget,
                        ),
                        toolbox=toolbox,
                    ),
                    llm_client=runtime_model_provider,  # type: ignore[arg-type]
                    state_store=runtime_state_store,
                    event_sink=sink,
                    policy=LoopPolicy(
                        model_timeout_seconds=360,
                        model_retries=3,
                        persist_steps=True,
                        context_window_tokens=runtime_options.context_window_tokens,
                    ),
                    hook_engine=plugin_assembly["hook_engine"],
                )
                kernel_result = await kernel.run(
                    RuntimeTurnInput(
                        user_message=continuation,
                        user_content=continuation,
                        state=lifecycle.state,
                        run_id=lifecycle.state.run_id,
                        turn_id=str(lifecycle.state.metadata.get("turn_id") or ""),
                        metadata={
                            **request.metadata,
                            **dict(request.payload.get("metadata") or {}),
                            "session_id": thread_id,
                            "data_dir": str(paths.data_dir),
                            "work_root": str(runtime_work_root),
                            "model_id": runtime_options.model_id,
                            **(
                                {"thinking_enabled": runtime_options.thinking_enabled}
                                if runtime_options.thinking_enabled is not None
                                else {}
                            ),
                            **(
                                {"thinking_budget": runtime_options.thinking_budget}
                                if runtime_options.thinking_budget is not None
                                else {}
                            ),
                            "shallow_thinking_enabled": runtime_options.shallow_thinking_enabled,
                            **(
                                {"context_window_tokens": runtime_options.context_window_tokens}
                                if runtime_options.context_window_tokens is not None
                                else {}
                            ),
                        },
                    )
                )
            except BaseException as exc:
                if isinstance(exc, asyncio.CancelledError):
                    raise
                try:
                    await _close_mcp_registry(mcp_registry)
                except BaseException as close_exc:
                    return await lifecycle.finalize_failure(close_exc)
                return await lifecycle.finalize_failure(exc)
            try:
                await _close_mcp_registry(mcp_registry)
            except BaseException as exc:
                return await lifecycle.finalize_failure(exc)
            events = [*approval_events, *sink.events]
            run_items = core_events_to_run_items(events, thread_id=thread_id)
            try:
                snapshot = await _persist_run_items(
                    run_items,
                    db_session_factory=db_session_factory,
                    app_event_store=app_event_store,
                    thread_snapshot_store=thread_snapshot_store,
                )
            except BaseException as exc:
                return await lifecycle.finalize_failure(exc)
            if snapshot is None:
                snapshot = core_events_to_snapshot(events, thread_id=thread_id)
            return OperationResult(
                name=request.name,
                status="ok" if kernel_result.decision in {"done", "wait"} else "error",
                payload={
                    "thread_id": kernel_result.session_id,
                    "run_id": kernel_result.run_id,
                    "turn_id": str(kernel_result.state.metadata.get("turn_id") or f"{kernel_result.session_id}:turn:{kernel_result.run_id}"),
                    "message": kernel_result.message,
                    "decision": kernel_result.decision,
                    "snapshot": snapshot,
                    "run_items": [
                        item.to_dict()
                        for item in [*lifecycle.decision_run_items, *run_items]
                    ],
                    "events": [event.to_dict() for event in events],
                    **({"error": kernel_result.error} if kernel_result.error else {}),
                },
            )
        return OperationResult(
            name=request.name,
            status="error",
            payload={"error": "approval.respond requires a runtime with a pending approval"},
        )

    async def command_catalog(request: OperationRequest) -> OperationResult:
        work_root = request.payload.get("work_root") or request.payload.get("workRoot") or paths.work_root
        commands = build_composer_command_catalog(
            core_roots=resolved_command_core_roots,
            member_roots=resolved_command_member_roots,
            work_root=work_root,
            skill_registry=command_skill_registry(),
        )
        return OperationResult(
            name="command.catalog",
            payload={"commands": [command.to_dict() for command in commands]},
        )

    async def command_execute(request: OperationRequest) -> OperationResult:
        thread_id = str(
            request.payload.get("thread_id")
            or request.payload.get("threadId")
            or request.payload.get("session_id")
            or request.payload.get("sessionId")
            or ""
        ).strip()
        command = normalize_command_name(request.payload.get("command"))
        if not thread_id or not command:
            return OperationResult(
                name=request.name,
                status="error",
                payload={"error": "thread_id and command are required"},
            )
        available = {
            item.name: item
            for item in build_composer_command_catalog(
                core_roots=resolved_command_core_roots,
                member_roots=resolved_command_member_roots,
                work_root=request.payload.get("work_root") or request.payload.get("workRoot") or paths.work_root,
                skill_registry=command_skill_registry(),
            )
        }
        definition = available.get(command)
        if definition is None:
            return OperationResult(
                name=request.name,
                status="error",
                payload={"error": f"Command not available: {command}"},
            )
        if definition.action != "run_action":
            return OperationResult(
                name=request.name,
                status="error",
                payload={"error": f"Command is not executable as an action: {command}"},
            )
        handlers = dict(command_action_handlers or {})
        handlers.setdefault(
            "compact",
            lambda thread_id, on_event=None: compact_runtime_history(
                runtime_state_store=runtime_state_store,
                thread_id=thread_id,
                llm_client=model_provider if _is_llm_client(model_provider) else None,  # type: ignore[arg-type]
                model=spec.default_model,
                on_event=on_event,
            ),
        )
        try:
            result = await execute_command_action(
                command=command,
                thread_id=thread_id,
                work_root=str(request.payload.get("work_root") or request.payload.get("workRoot") or paths.work_root),
                handlers=handlers,
            )
        except (LookupError, RuntimeError, TypeError, ValueError) as exc:
            return OperationResult(name=request.name, status="error", payload={"error": str(exc)})
        return OperationResult(name=request.name, payload={"result": result})

    catalog.register("turn.start", turn_start)
    catalog.register("approval.respond", approval_respond)
    catalog.register("command.catalog", command_catalog)
    catalog.register("command.execute", command_execute)
    if db_session_factory is not None:
        register_checkpoint_operations(
            catalog,
            session_factory=db_session_factory,  # type: ignore[arg-type]
            data_dir=paths.data_dir,
            default_work_root=paths.work_root,
        )
    plugin_operations = build_core_plugin_operation_catalog(
        data_dir=paths.data_dir,
        work_root=paths.work_root,
        plugin_roots=plugin_roots,
    )
    for operation_name in plugin_operations.list():
        async def execute_plugin_operation(
            request: OperationRequest,
            name: str = operation_name,
        ) -> OperationResult:
            return await plugin_operations.execute(name, request.payload, metadata=request.metadata)

        catalog.register(operation_name, execute_plugin_operation)
    return catalog


def _is_llm_client(value: Any) -> bool:
    return callable(getattr(value, "complete", None)) and callable(getattr(value, "stream", None))


def _work_root_from_request(paths: CoreAgentPaths, request: OperationRequest) -> Path:
    payload = request.payload if isinstance(request.payload, dict) else {}
    metadata = request.metadata if isinstance(request.metadata, dict) else {}
    supplied = (
        payload.get("work_root")
        or payload.get("workRoot")
        or metadata.get("work_root")
        or metadata.get("workRoot")
    )
    return Path(supplied or paths.work_root).expanduser().resolve()


def _work_root_from_state(paths: CoreAgentPaths, state: Any) -> Path:
    metadata = state.metadata if isinstance(getattr(state, "metadata", None), dict) else {}
    return Path(metadata.get("work_root") or paths.work_root).expanduser().resolve()


def _runtime_options_from_request(spec: CoreAgentSpec, request: OperationRequest) -> CoreAgentRuntimeOptions:
    payload = request.payload if isinstance(request.payload, dict) else {}
    metadata = request.metadata if isinstance(request.metadata, dict) else {}
    model_id = str(
        payload.get("model_id")
        or payload.get("modelId")
        or metadata.get("model_id")
        or spec.default_model
        or ""
    )
    thinking_enabled = _optional_bool(
        payload.get("thinking_enabled"),
        payload.get("thinkingEnabled"),
        metadata.get("thinking_enabled"),
        spec.metadata.get("thinking_enabled"),
    )
    thinking_budget = _optional_int(
        payload.get("thinking_budget"),
        payload.get("thinkingBudget"),
        metadata.get("thinking_budget"),
        spec.metadata.get("thinking_budget"),
    )
    shallow_thinking_enabled = bool(
        _optional_bool(
            payload.get("shallow_thinking_enabled"),
            payload.get("shallowThinkingEnabled"),
            metadata.get("shallow_thinking_enabled"),
            spec.metadata.get("shallow_thinking_enabled"),
        )
    )
    context_window_tokens = _optional_int(
        payload.get("context_window_tokens"),
        payload.get("contextWindowTokens"),
        payload.get("context_window"),
        metadata.get("context_window_tokens"),
        metadata.get("contextWindowTokens"),
        metadata.get("context_window"),
        spec.metadata.get("context_window"),
    )
    return CoreAgentRuntimeOptions(
        model_id=model_id,
        thinking_enabled=thinking_enabled,
        thinking_budget=thinking_budget,
        shallow_thinking_enabled=shallow_thinking_enabled,
        context_window_tokens=context_window_tokens,
    )


def _runtime_options_from_state(spec: CoreAgentSpec, state: Any) -> CoreAgentRuntimeOptions:
    metadata = state.metadata if isinstance(getattr(state, "metadata", None), dict) else {}
    model_id = str(metadata.get("model_id") or spec.default_model or "")
    return CoreAgentRuntimeOptions(
        model_id=model_id,
        thinking_enabled=_optional_bool(metadata.get("thinking_enabled"), spec.metadata.get("thinking_enabled")),
        thinking_budget=_optional_int(metadata.get("thinking_budget"), spec.metadata.get("thinking_budget")),
        shallow_thinking_enabled=bool(
            _optional_bool(
                metadata.get("shallow_thinking_enabled"),
                spec.metadata.get("shallow_thinking_enabled"),
            )
        ),
        context_window_tokens=_optional_int(
            metadata.get("context_window_tokens"),
            metadata.get("context_window"),
            spec.metadata.get("context_window"),
        ),
    )


def _optional_bool(*values: Any) -> bool | None:
    for value in values:
        if isinstance(value, bool):
            return value
    return None


def _optional_int(*values: Any) -> int | None:
    for value in values:
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def _model_provider_for_runtime(model_provider: Any, *, runtime_options: CoreAgentRuntimeOptions) -> Any:
    provider = model_provider
    with_runtime_options = getattr(provider, "with_runtime_options", None)
    if callable(with_runtime_options):
        maybe_provider = with_runtime_options(
            model_id=runtime_options.model_id,
            thinking_enabled=runtime_options.thinking_enabled,
            thinking_budget=runtime_options.thinking_budget,
        )
        if maybe_provider is not None:
            provider = maybe_provider
    if runtime_options.shallow_thinking_enabled:
        from lamtools_core.llm.shallow_thinking import ShallowThinkingClient

        provider = ShallowThinkingClient(provider)
    return provider


async def _persist_run_items(
    run_items: list[Any],
    *,
    db_session_factory: Callable[[], Any] | None,
    app_event_store: SqlAlchemyAppEventStore | None,
    thread_snapshot_store: SqlAlchemyThreadSnapshotStore | None,
    app_event_hub: Any | None = None,
) -> dict[str, Any] | None:
    if not run_items or db_session_factory is None or app_event_store is None or thread_snapshot_store is None:
        return None
    persistence = AppPersistenceHost(
        app_event_store,
        thread_snapshot_store,
        session_factory=db_session_factory,
    )

    async def write(db):
        envelopes = []
        for item in run_items:
            envelopes.append(await persistence.append_run_item(db, item))
        return await persistence.load(db, run_items[-1].thread_id), envelopes

    snapshot, envelopes = await persistence.write(write)
    if app_event_hub is not None:
        publish = getattr(app_event_hub, "publish", None)
        if callable(publish):
            for envelope in envelopes:
                published = publish(envelope)
                if inspect.isawaitable(published):
                    await published
    return snapshot


def _should_collect_core_event(event: Any) -> bool:
    return getattr(event, "metadata", {}).get("delivery") != "transient"


async def _persist_core_event_live(
    event: Any,
    *,
    thread_id: str,
    db_session_factory: Callable[[], Any] | None,
    app_event_store: SqlAlchemyAppEventStore | None,
    thread_snapshot_store: SqlAlchemyThreadSnapshotStore | None,
    app_event_hub: Any | None,
) -> None:
    if getattr(event, "metadata", {}).get("delivery") == "transient":
        if app_event_hub is None:
            return
        run_items = core_events_to_run_items([event], thread_id=thread_id, include_transient=True)
        for item in run_items:
            await app_event_hub.publish(AppEventEnvelope(
                event_id=item.event_id,
                protocol_version="core.app_server.v1",
                seq=0,
                thread_id=item.thread_id,
                method=CORE_RUN_ITEM_METHOD,
                payload=item.to_dict(),
                created_at=datetime.fromtimestamp(
                    item.created_at_ms / 1000,
                    timezone.utc,
                ),
                turn_id=item.turn_id or None,
                item_id=item.item_id or None,
                parent_item_id=item.parent_item_id or None,
                client_message_id=None,
            ))
        return
    if db_session_factory is None or app_event_store is None or thread_snapshot_store is None:
        return
    run_items = core_events_to_run_items([event], thread_id=thread_id)
    if not run_items:
        return
    persistence = AppPersistenceHost(
        app_event_store,
        thread_snapshot_store,
        session_factory=db_session_factory,
    )

    async def write(db):
        envelopes: list[Any] = []
        for item in run_items:
            envelopes.append(await persistence.append_run_item(db, item))
        return envelopes

    envelopes = await persistence.write(write)
    if app_event_hub is None:
        return
    for envelope in envelopes:
        publish = getattr(app_event_hub, "publish", None)
        if callable(publish):
            result = publish(envelope)
            if hasattr(result, "__await__"):
                await result


async def _build_core_runtime_toolbox(
    *,
    work_root: Path | str,
    plugin_assembly: dict[str, Any],
    approval_policy: str,
    llm_client: Any | None = None,
    model_id: str = "",
    instructions: str = "",
    context_window_tokens: int | None = None,
    temperature: float = 0.2,
    max_tokens: int = 4096,
    thinking_enabled: bool | None = None,
    thinking_budget: int | None = None,
    sub_agent_state_store: RuntimeStateStore | None = None,
    sub_agent_session_prefix: str = "core-sub-agent",
    sub_agent_event_sink: EventSink | None = None,
    checkpoint_coordinator: Any | None = None,
):
    from lamtools_core.mcp import MCPToolRegistry
    from lamtools_core.tool.sub_agent_runner import KernelSubAgentRunner
    from lamtools_core.tool.default_toolbox import build_core_toolbox

    registry = MCPToolRegistry(work_root, config_files=plugin_assembly.get("mcp_files") or [])
    await registry.load()
    mcp_tool_specs = registry.tool_specs()
    hook_engine = plugin_assembly.get("hook_engine")
    if hook_engine is not None:
        hook_engine.set_mcp_caller(registry if mcp_tool_specs else None)
    normalized_policy = approval_policy if approval_policy in {"require", "auto_approve"} else "require"
    skill_roots = set(plugin_assembly.get("skill_roots") or [])
    sub_agent_runner = None
    if llm_client is not None:
        sub_agent_runner = KernelSubAgentRunner(
            work_root=work_root,
            llm_client=llm_client,
            model_id=model_id,
            instructions=instructions,
            temperature=temperature,
            max_tokens=max_tokens,
            thinking_enabled=thinking_enabled,
            thinking_budget=thinking_budget,
            approval_policy=normalized_policy,
            loaded_skill_roots=skill_roots,
            mcp_caller=registry if mcp_tool_specs else None,
            mcp_tool_specs=mcp_tool_specs,
            context_window_tokens=context_window_tokens,
            state_store=sub_agent_state_store,
            session_prefix=sub_agent_session_prefix,
            parent_event_sink=sub_agent_event_sink,
            checkpoint_coordinator=checkpoint_coordinator,
        )
    toolbox = build_core_toolbox(
        work_root=work_root,
        approval_policy=normalized_policy,
        loaded_skill_roots=skill_roots,
        mcp_caller=registry if mcp_tool_specs else None,
        mcp_tool_specs=mcp_tool_specs,
        sub_agent_runner=sub_agent_runner,
    )
    return toolbox, registry


async def _close_mcp_registry(registry: Any) -> None:
    close = getattr(registry, "close", None)
    if close is None:
        return
    result = close()
    if hasattr(result, "__await__"):
        await result


def _without_approval_response_events(events: list[Any]) -> list[Any]:
    return [event for event in events if event.name != "runtime.approval_response"]


__all__ = [
    "CoreAgentPaths",
    "CoreAgentSpec",
    "create_core_agent_operations",
]
