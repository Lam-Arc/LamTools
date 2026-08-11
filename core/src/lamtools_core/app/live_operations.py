from __future__ import annotations

import asyncio
import logging
import sys
import time as time_module
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)

from sqlalchemy.ext.asyncio import AsyncSession

from lamtools_core.event import RunItemEvent
from lamtools_core.attachment import AttachmentService
from lamtools_core.composer_commands import (
    build_composer_command_catalog,
    default_core_resource_roots,
    normalize_command_name,
)
from lamtools_core.runtime import RuntimeStateConflictError, RuntimeStateStore, default_runtime_task_registry
from lamtools_core.tool.approval import load_access_tools, normalize_command_policies
from lamtools_core.tool.approval import PermissionMode, TierTools
from lamtools_core.tool.loadtools import LoadTools, default_load_tools, load_loadtools, mode_names

from .event_store import AppEventEnvelope, AppEventInput, CORE_RUN_ITEM_METHOD, SqlAlchemyAppEventStore
from .command_execution import execute_command_action
from .live_approval import normalize_approval_request
from .live_hub import CoreAppEventHub, hub as default_hub
from .live_member import DefaultCoreLiveMemberHooks, PreparedLiveInput
from .live_protocol import INVALID_REQUEST, rpc_error, rpc_result
from .operation_catalog import OperationCatalog, OperationHandler, OperationRequest, OperationResult
from .operation_groups import CORE_WORKBENCH_OPERATION_NAMES
from .persistence_host import AppPersistenceHost
from .queue_state import (
    ACTIVE_TURN_STATUSES,
    build_queue_guidance_plan,
    build_queue_update_plan,
    effective_thread_status,
    input_items_text,
    latest_active_turn_id,
    next_dispatchable_queue_item,
    queue_delete_payload,
    queue_dispatch_payload,
    queue_item_payload,
)
from .snapshot_store import SqlAlchemyThreadSnapshotStore
from .session_autotitle import generate_session_title, is_default_title
from .turn_acceptance import (
    QUEUE_ITEM_ACCEPTED_METHODS,
    TURN_ACCEPTED_METHODS,
    CoreAppEventSpec,
    build_cancelled_turn_event,
    build_turn_acceptance_plan,
)


TERMINAL_TURN_STATUSES = {"completed", "failed", "cancelled", "skipped"}




async def handle_command_catalog_operation(
    *, request_id: int | str | None, params: dict[str, Any], context: "CoreLiveContext"
) -> "CoreLiveOperationOutcome":
    commands = await _live_command_catalog(context=context, params=params)
    return CoreLiveOperationOutcome(response=rpc_result(request_id, {"commands": commands}))


async def handle_command_execute_operation(
    *, request_id: int | str | None, params: dict[str, Any], context: "CoreLiveContext"
) -> "CoreLiveOperationOutcome":
    thread_id = _thread_id_from_params(params)
    command = normalize_command_name(params.get("command"))
    if not thread_id or not command:
        return CoreLiveOperationOutcome(
            response=rpc_error(
                request_id,
                code=INVALID_REQUEST,
                message="thread_id and command are required",
            )
        )
    actions = context.host.member_hooks.command_action_handlers()
    catalog = {str(item.get("name") or ""): item for item in await _live_command_catalog(context=context, params=params)}
    definition = catalog.get(command)
    # Allow commands registered as actions even if the catalog (which may
    # go through operations) doesn't list them — e.g. "compact" registered
    # via member_hooks.command_action_handlers() or command.execute operation.
    if definition is None and command not in actions and not context.operations.has("command.execute"):
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message=f"Command not available: {command}")
        )
    if definition is not None and definition.get("action") != "run_action":
        return CoreLiveOperationOutcome(
            response=rpc_error(
                request_id,
                code=INVALID_REQUEST,
                message=f"Command is not executable as an action: {command}",
            )
        )
    work_root = str(params.get("work_root") or params.get("workRoot") or "")
    try:
        if command == "compact":
            result, snapshot = await _execute_compact_live_command(
                context=context,
                thread_id=thread_id,
                work_root=work_root,
                actions=actions,
                params=params,
            )
        else:
            result = await _execute_live_command_action(
                context=context,
                command=command,
                thread_id=thread_id,
                work_root=work_root,
                actions=actions,
                params=params,
            )
            async with context.session_factory() as db:
                snapshot = await context.persistence.load(db, thread_id)
    except (LookupError, RuntimeError, TypeError, ValueError) as exc:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc))
        )
    response_payload: dict[str, Any] = {"result": result}
    if params.get("include_snapshot") is not False:
        response_payload["snapshot"] = snapshot
    return CoreLiveOperationOutcome(response=rpc_result(request_id, response_payload))


async def handle_attachment_operation(
    *, request_id: int | str | None, params: dict[str, Any], context: "CoreLiveContext", operation: str
) -> "CoreLiveOperationOutcome":
    session_id = _thread_id_from_params(params)
    attachment_id = str(params.get("attachment_id") or params.get("attachmentId") or params.get("id") or "").strip()
    if operation == "list" and not session_id:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="session_id is required")
        )
    if operation != "list" and not attachment_id:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="attachment_id is required")
        )
    try:
        async with context.session_factory() as db:
            repository = context.host.member_hooks.attachment_repository(db)
            if repository is None:
                raise RuntimeError("Attachment storage is not configured")
            service = AttachmentService(repository)
            if operation == "list":
                result = {"attachments": await service.list(session_id)}
            elif operation == "get":
                result = {"attachment": await service.get_response(attachment_id)}
            elif operation == "preview":
                result = {"preview": await service.preview(attachment_id)}
            else:
                result = await service.open(attachment_id)
    except (FileNotFoundError, LookupError, RuntimeError, ValueError) as exc:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc))
        )
    return CoreLiveOperationOutcome(response=rpc_result(request_id, result))


async def handle_attachment_list_operation(**kwargs):
    return await handle_attachment_operation(**kwargs, operation="list")


async def handle_attachment_get_operation(**kwargs):
    return await handle_attachment_operation(**kwargs, operation="get")


async def handle_attachment_preview_operation(**kwargs):
    return await handle_attachment_operation(**kwargs, operation="preview")


async def handle_attachment_open_operation(**kwargs):
    return await handle_attachment_operation(**kwargs, operation="open")


@dataclass
class CoreLiveOperationHost:
    """Owns reusable live-operation dependencies and catalog handlers."""

    session_factory: Callable[[], Any]
    persistence: AppPersistenceHost
    hub: CoreAppEventHub = field(default_factory=lambda: default_hub)
    runtime_task_registry: Any = field(default_factory=default_runtime_task_registry)
    runtime_state_store: RuntimeStateStore | None = None
    product_operation_executors: dict[str, Any] = field(default_factory=dict)
    operation_executors: dict[str, Any] = field(default_factory=dict)
    member_hooks: Any = field(default_factory=DefaultCoreLiveMemberHooks)
    # Optional LLM client + model id used for side-channel tasks such as
    # auto-generating a session title from the first user message. May be None
    # when the host is constructed without a model provider (e.g. tests).
    llm_client: Any = None
    default_model_id: str = ""
    # Optional session store used to persist auto-generated titles. When None,
    # title generation still runs but the result is only broadcast, not stored.
    session_store: Any = None
    _handlers: dict[str, OperationHandler] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        product_executors = {**self.operation_executors, **self.product_operation_executors}
        forbidden = sorted(set(product_executors).intersection(CORE_WORKBENCH_OPERATION_NAMES))
        if forbidden:
            raise ValueError(f"base live operation executors cannot be overridden: {', '.join(forbidden)}")
        self.product_operation_executors = product_executors
        self.persistence.bind_session_factory(self.session_factory)
        names = {*CORE_WORKBENCH_OPERATION_NAMES, *self.product_operation_executors}
        self._handlers = {name: self._build_catalog_handler(name) for name in names}

    @property
    def event_store(self) -> SqlAlchemyAppEventStore:
        return self.persistence.event_store

    @property
    def snapshot_store(self) -> SqlAlchemyThreadSnapshotStore:
        return self.persistence.snapshot_store

    def operation_handlers(self) -> dict[str, OperationHandler]:
        return dict(self._handlers)

    async def execute(
        self,
        name: str,
        *,
        request_id: int | str | None,
        params: dict[str, Any],
        context: "CoreLiveContext",
    ) -> "CoreLiveOperationOutcome":
        if name == "approval.respond":
            try:
                params = (await normalize_approval_request(params)).to_dict()
            except ValueError as exc:
                return CoreLiveOperationOutcome(
                    response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc))
                )
        handler = _CORE_LIVE_OPERATION_EXECUTORS.get(name)
        if handler is not None:
            return await handler(request_id=request_id, params=params, context=context)
        handler = self.product_operation_executors.get(name)
        if handler is not None:
            return await handler(request_id=request_id, params=params, context=context)
        if not context.operations.has(name):
            raise KeyError(f"Unsupported core live operation: {name}")
        result = await context.operations.execute(name, params, metadata={"source": "core_live"})
        payload = dict(result.payload or {})
        if result.status != "ok":
            return CoreLiveOperationOutcome(
                response=rpc_error(
                    request_id,
                    code=INVALID_REQUEST,
                    message=str(payload.get("error") or result.status),
                    data=payload,
                )
            )
        return CoreLiveOperationOutcome(response=rpc_result(request_id, payload))

    def _build_catalog_handler(self, name: str) -> OperationHandler:
        async def handle(request: OperationRequest) -> OperationResult:
            connection = request.metadata.get("connection")
            rpc_request = request.metadata.get("rpc_request")
            params = dict(request.payload)
            if not _thread_id_from_params(params) and connection is not None:
                thread_id = getattr(connection, "thread_id", None)
                if thread_id:
                    params["thread_id"] = thread_id
            if connection is not None:
                thread_id = _thread_id_from_params(params)
                switch_subscription = getattr(connection, "switch_thread_subscription", None)
                if thread_id and callable(switch_subscription):
                    switch_subscription(thread_id)
            request_id = getattr(rpc_request, "id", None)
            context = getattr(connection, "context", None)
            if not isinstance(context, CoreLiveContext):
                raise TypeError("core live connection context is required")
            outcome = await self.execute(name, request_id=request_id, params=params, context=context)
            await connection.send_operation_outcome(outcome, publish_events=False)
            return OperationResult(name=request.name, metadata={"live_response_sent": True})

        return handle


@dataclass(frozen=True)
class CoreLiveContext:
    operations: OperationCatalog
    session_factory: Callable[[], Any] | None = None
    event_store: SqlAlchemyAppEventStore | None = None
    snapshot_store: SqlAlchemyThreadSnapshotStore | None = None
    hub: CoreAppEventHub = field(default_factory=lambda: default_hub)
    persistence: AppPersistenceHost | None = None
    runtime_task_registry: Any = field(default_factory=default_runtime_task_registry)
    runtime_state_store: RuntimeStateStore | None = None
    host: CoreLiveOperationHost | None = None

    def __post_init__(self) -> None:
        if self.host is not None:
            object.__setattr__(self, "session_factory", self.host.session_factory)
            object.__setattr__(self, "persistence", self.host.persistence)
            object.__setattr__(self, "event_store", self.host.event_store)
            object.__setattr__(self, "snapshot_store", self.host.snapshot_store)
            object.__setattr__(self, "hub", self.host.hub)
            object.__setattr__(self, "runtime_task_registry", self.host.runtime_task_registry)
            object.__setattr__(self, "runtime_state_store", self.host.runtime_state_store)
            return
        persistence = self.persistence
        if persistence is None:
            if self.event_store is None or self.snapshot_store is None:
                raise ValueError("event_store and snapshot_store are required when persistence is not provided")
            persistence = AppPersistenceHost(self.event_store, self.snapshot_store)
        if self.session_factory is None:
            raise ValueError("session_factory is required when host is not provided")
        object.__setattr__(self, "persistence", persistence)
        object.__setattr__(self, "event_store", persistence.event_store)
        object.__setattr__(self, "snapshot_store", persistence.snapshot_store)
        object.__setattr__(
            self,
            "host",
            CoreLiveOperationHost(
                session_factory=self.session_factory,
                persistence=persistence,
                hub=self.hub,
                runtime_task_registry=self.runtime_task_registry,
                runtime_state_store=self.runtime_state_store,
            ),
        )


@dataclass
class CoreLiveOperationOutcome:
    response: dict[str, Any]
    notify_events: list[AppEventEnvelope] = field(default_factory=list)
    publish_events: list[AppEventEnvelope] = field(default_factory=list)
    runtime_start: dict[str, Any] | None = None


async def handle_thread_resume_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    context: CoreLiveContext,
) -> CoreLiveOperationOutcome:
    thread_id = str(params.get("thread_id") or params.get("threadId") or "")
    if not thread_id:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="thread_id is required")
        )
    after_seq = _int_param(params.get("last_seen_seq") or params.get("lastSeenSeq"), default=0)
    page_limit = max(1, min(_int_param(params.get("limit"), default=500), 500))
    async with context.session_factory() as db:
        events = await context.persistence.list_after(db, thread_id=thread_id, after_seq=after_seq, limit=page_limit)
        snapshot = await context.persistence.load(db, thread_id)
    await _reconcile_cancelled_runtime_state(context=context, thread_id=thread_id, snapshot=snapshot)
    last_event_seq = max((event.seq for event in events), default=after_seq)
    snapshot_seq = _int_param(snapshot.get("snapshot_seq") if isinstance(snapshot, dict) else None, default=last_event_seq)
    has_more = bool(events) and last_event_seq < snapshot_seq
    return CoreLiveOperationOutcome(
        response=rpc_result(
            request_id,
            {
                "thread": {"id": thread_id},
                "events": [event.to_dict() for event in events],
                "snapshot": snapshot,
                "has_more": has_more,
                "next_after_seq": last_event_seq,
            },
        )
    )


async def handle_thread_read_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    context: CoreLiveContext,
) -> CoreLiveOperationOutcome:
    thread_id = str(params.get("thread_id") or params.get("threadId") or "")
    if not thread_id:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="thread_id is required")
        )
    async with context.session_factory() as db:
        snapshot = await context.persistence.load(db, thread_id)
        events = await context.persistence.list_thread(db, thread_id=thread_id)
        member_payload = await context.host.member_hooks.augment_thread_read(
            db=db,
            thread_id=thread_id,
            result={"snapshot": snapshot, "events": events},
        )
    await _reconcile_cancelled_runtime_state(context=context, thread_id=thread_id, snapshot=snapshot)
    return CoreLiveOperationOutcome(
        response=rpc_result(
            request_id,
            {
                "thread": {"id": thread_id},
                "events": [event.to_dict() for event in events],
                "snapshot": snapshot,
                **member_payload,
            },
        )
    )


async def handle_thread_start_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    context: CoreLiveContext,
) -> CoreLiveOperationOutcome:
    thread_id = _thread_id_from_params(params)
    if not thread_id:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="thread_id is required")
        )

    async def write(db: AsyncSession):
        member_payload = await context.host.member_hooks.materialize_thread(
            db=db,
            thread_id=thread_id,
            params=params,
        )
        event = await _append_app_event(
            db,
            context=context,
            event=AppEventInput(
                thread_id=thread_id,
                method="thread/started",
                payload={"type": "thread", "status": "idle", **params, **member_payload},
            ),
        )
        return event, await context.persistence.load(db, thread_id)

    event, snapshot = await context.persistence.write(write)
    await context.hub.publish(event)
    return CoreLiveOperationOutcome(
        response=rpc_result(
            request_id,
            {"thread": {"id": thread_id}, "event": event.to_dict(), "snapshot": snapshot},
        ),
        publish_events=[event],
    )


async def handle_turn_start_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    context: CoreLiveContext,
) -> CoreLiveOperationOutcome:
    thread_id = str(params.get("thread_id") or params.get("threadId") or params.get("session_id") or "").strip()
    client_message_id = str(params.get("client_message_id") or params.get("clientMessageId") or uuid.uuid4().hex)
    input_items = params.get("input")
    if not thread_id or not isinstance(input_items, list):
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="thread_id and input are required")
        )

    try:
        prepared = await context.host.member_hooks.prepare_turn_input(
            thread_id=thread_id,
            params=params,
            input_items=input_items,
        )
    except ValueError as exc:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc))
        )
    turn_id = str(params.get("turn_id") or params.get("turnId") or f"{thread_id}:turn:{uuid.uuid4().hex[:12]}")
    user_item_id = str(params.get("user_item_id") or params.get("userItemId") or f"{turn_id}:user")
    run_claimed = False

    async def write(db):
        nonlocal run_claimed
        _w0 = time_module.perf_counter()
        existing = await context.persistence.find_client_event(
            db,
            thread_id=thread_id,
            client_message_id=client_message_id,
            methods=TURN_ACCEPTED_METHODS,
        )
        _w1 = time_module.perf_counter()
        _logger.info("[PERF:turn_start:write] find_client_event=%.3fs", _w1 - _w0)
        if existing is not None:
            snapshot = await context.persistence.load(db, thread_id)
            return CoreLiveOperationOutcome(
                response=rpc_result(
                    request_id,
                    {
                        "events": [existing.to_dict()],
                        "snapshot": snapshot,
                    },
                ),
                notify_events=[existing],
            )

        _w2 = time_module.perf_counter()
        snapshot = await context.persistence.load(db, thread_id)
        _w3 = time_module.perf_counter()
        _logger.info("[PERF:turn_start:write] load#1=%.3fs snapshot_size=%s", _w3 - _w2, len(str(snapshot)) if isinstance(snapshot, dict) else 0)
        active_run_id = latest_active_turn_id(snapshot) or context.host.runtime_task_registry.active_run_id(thread_id)
        if active_run_id:
            return CoreLiveOperationOutcome(
                response=rpc_error(
                    request_id,
                    code=INVALID_REQUEST,
                    message="active turn already exists",
                    data={"reason": "active_turn_exists", "active_run_id": active_run_id},
                )
            )
        # Detect a first message: the snapshot has no items yet. Captured before
        # the user item is appended so it reflects the pre-turn state.
        prior_item_order = snapshot.get("item_order") if isinstance(snapshot, dict) else None
        is_first_message = not prior_item_order
        if not context.host.runtime_task_registry.accept_run(thread_id, turn_id):
            return CoreLiveOperationOutcome(
                response=rpc_error(
                    request_id,
                    code=INVALID_REQUEST,
                    message="active turn already exists",
                    data={
                        "reason": "active_turn_exists",
                        "active_run_id": context.host.runtime_task_registry.active_run_id(thread_id),
                    },
                )
            )

        run_claimed = True
        try:
            materialized = await context.host.member_hooks.materialize_turn(
                db=db,
                thread_id=thread_id,
                turn_id=turn_id,
                user_item_id=user_item_id,
                client_message_id=client_message_id,
                prepared=prepared,
                params=params,
            )
            if materialized.turn_id != turn_id or materialized.user_item_id != user_item_id:
                raise ValueError("member turn materialization must preserve Core acceptance ids")
            plan = build_turn_acceptance_plan(
                thread_id=thread_id,
                turn_id=turn_id,
                user_item_id=user_item_id,
                client_message_id=client_message_id,
                input_items=prepared.visible_input,
                work_root=prepared.work_root,
                turn_payload_extra=materialized.turn_payload_extra,
                user_payload_extra=materialized.user_payload_extra,
                include_turn_status=materialized.include_turn_status,
            )
            _w4 = time_module.perf_counter()
            envelopes, projected = await context.persistence.append_batch(
                db,
                app_events=[_app_event_input(plan.turn_accepted), _app_event_input(plan.user_item)],
                run_item_events=[plan.running_status],
                return_state=True,
            )
            _w5 = time_module.perf_counter()
            _logger.info("[PERF:turn_start:write] append_batch=%.3fs", _w5 - _w4)
            accepted, user, running = envelopes[0], envelopes[1], envelopes[2]
            # Reuse the in-memory projection from append_batch instead of
            # re-loading (and re-parsing) the whole snapshot row from the DB.
            # reconcile_status keeps the result byte-equivalent to load().
            snapshot = projected if isinstance(projected, dict) else await context.persistence.load(db, thread_id)
            if isinstance(projected, dict):
                snapshot["snapshot_seq"] = int(projected.get("snapshot_seq") or 0)
                context.persistence.snapshot_store.projector.reconcile_status(snapshot)
            _w6 = time_module.perf_counter()
            _logger.info("[PERF:turn_start:write] load#2=%.3fs", _w6 - _w5)
            return accepted, user, running, snapshot, materialized, is_first_message
        except BaseException:
            context.host.runtime_task_registry.release_run(thread_id, run_id=turn_id)
            run_claimed = False
            raise

    _t0 = time_module.perf_counter()
    try:
        write_result = await context.persistence.write(write)
    except BaseException:
        if run_claimed:
            context.host.runtime_task_registry.release_run(thread_id, run_id=turn_id)
        raise
    _t1 = time_module.perf_counter()
    _logger.info("[PERF:turn_start] persistence.write=%.3fs thread_id=%s", _t1 - _t0, thread_id)
    if isinstance(write_result, CoreLiveOperationOutcome):
        return write_result
    accepted, user, running, snapshot, materialized, is_first_message = write_result

    # Best-effort: generate a short title from the first user message. Runs in
    # the background so it never blocks the turn response; failures are logged
    # and swallowed inside the task.
    if is_first_message and context.host.llm_client and prepared.runtime_text:
        loop = _get_running_loop()
        loop.create_task(_auto_title_session(
            context=context,
            thread_id=thread_id,
            first_message=prepared.runtime_text,
        ))

    resolved = await _resolve_turn_approval_policy(context=context, params=params)
    imagegen_config = await _resolve_imagegen_config(context=context)
    runtime_start = {
        "thread_id": thread_id,
        "turn_id": turn_id,
        "user_message_id": user_item_id,
        "text": prepared.runtime_text,
        "input": prepared.runtime_input,
        "work_root": prepared.work_root,
        "approval_policy": resolved["approval_policy"],
        "active_tier": resolved["active_tier"],
        "tier_tools": resolved["tier_tools"],
        "active_mode": resolved["active_mode"],
        "allow_agent_install_skill": resolved.get("allow_agent_install_skill", False),
        "allow_agent_create_hooks": resolved.get("allow_agent_create_hooks", False),
        "allow_access_outside_workdir": resolved.get("allow_access_outside_workdir", False),
        "imagegen_config": imagegen_config,
        "model_id": str(params.get("model_id") or params.get("modelId") or ""),
        "thinking_enabled": params.get("thinking_enabled") if isinstance(params.get("thinking_enabled"), bool) else None,
        "thinking_budget": params.get("thinking_budget") if isinstance(params.get("thinking_budget"), int) else None,
        "reasoning_effort": str(params.get("reasoning_effort") or params.get("reasoningEffort") or ""),
        "shallow_thinking_enabled": (
            params.get("shallow_thinking_enabled")
            if isinstance(params.get("shallow_thinking_enabled"), bool)
            else None
        ),
        "context_window_tokens": (
            params.get("context_window_tokens")
            if isinstance(params.get("context_window_tokens"), int)
            and not isinstance(params.get("context_window_tokens"), bool)
            and params.get("context_window_tokens") > 0
            else None
        ),
        "goal_id": str(params.get("goal_id") or params.get("goalId") or "").strip(),
        "max_tokens": (
            params.get("max_tokens")
            if isinstance(params.get("max_tokens"), int)
            and not isinstance(params.get("max_tokens"), bool)
            and params.get("max_tokens") > 0
            else None
        ),
        "temperature": (
            float(params.get("temperature"))
            if isinstance(params.get("temperature"), (int, float))
            and not isinstance(params.get("temperature"), bool)
            else None
        ),
        "compact_trigger_tokens": (
            params.get("compact_trigger_tokens")
            if isinstance(params.get("compact_trigger_tokens"), int)
            and not isinstance(params.get("compact_trigger_tokens"), bool)
            and params.get("compact_trigger_tokens") > 0
            else None
        ),
        "compact_limit_tokens": (
            params.get("compact_limit_tokens")
            if isinstance(params.get("compact_limit_tokens"), int)
            and not isinstance(params.get("compact_limit_tokens"), bool)
            and params.get("compact_limit_tokens") > 0
            else None
        ),
        **prepared.runtime_extras,
        **materialized.runtime_extras,
    }
    events = [accepted, user, running]
    _t2 = time_module.perf_counter()
    for event in events:
        await context.hub.publish(event)
    _t3 = time_module.perf_counter()
    _logger.info("[PERF:turn_start] hub.publish(3)=%.3fs", _t3 - _t2)
    start_failure = await _start_runtime_task(context=context, runtime_start=runtime_start)
    _t4 = time_module.perf_counter()
    _logger.info("[PERF:turn_start] _start_runtime_task=%.3fs", _t4 - _t3)
    if start_failure is not None:
        failure_event, snapshot = start_failure
        events.append(failure_event)
    _logger.info("[PERF:turn_start] total=%.3fs thread_id=%s", _t4 - _t0, thread_id)
    _logger.info("[live:handle_turn_start] dispatched background task thread_id=%s turn_id=%s model=%s",
                  thread_id, turn_id, runtime_start.get("model_id") or "default")
    return CoreLiveOperationOutcome(
        response=rpc_result(
            request_id,
            {
                "events": [event.to_dict() for event in events],
                "snapshot": snapshot,
                "runtime_start": runtime_start,
            },
        ),
        notify_events=events,
        runtime_start=runtime_start,
    )


async def _resolve_turn_approval_policy(*, context: "CoreLiveContext", params: dict[str, Any]) -> dict[str, Any]:
    """Resolve approval policy, tier configuration, and loadtools mode for a turn.
    
    Returns dict with keys: approval_policy, active_tier, tier_tools, active_mode, load_tools
    """
    explicit = params.get("approval_policy") or params.get("approvalPolicy")
    active_mode = params.get("active_mode")
    if isinstance(active_mode, str) and active_mode.strip():
        active_mode = active_mode.strip()
    else:
        active_mode = None
    load_tools = _load_load_tools(context)
    default_result: dict[str, Any] = {
        "approval_policy": "require",
        "active_tier": None,
        "tier_tools": None,
        "active_mode": active_mode,
        "allow_agent_install_skill": False,
        "allow_agent_create_hooks": False,
        "allow_access_outside_workdir": False,
    }
    if explicit is not None:
        default_result["approval_policy"] = "auto_approve" if explicit == "auto_approve" else "require"
        return default_result
    if not context.operations.has("settings.get"):
        return default_result
    try:
        result = await context.operations.execute(
            "settings.get",
            {"namespace": "core.runtimeControls"},
            metadata={"source": "core_live"},
        )
    except Exception:
        return default_result
    if result.status != "ok":
        return default_result
    value = result.payload.get("value") if isinstance(result.payload, dict) else None
    if not isinstance(value, dict):
        return default_result
    permission_mode = value.get("permission_mode")
    if permission_mode not in ("read_only", "limited_edit", "full_edit"):
        return default_result
    active_tier: PermissionMode = permission_mode  # type: ignore[assignment]
    tier_tools = _load_tier_tools(context)
    approval_policy = "auto_approve" if active_tier == "full_edit" else "require"
    allow_agent_install_skill = bool(value.get("allow_agent_install_skill"))
    allow_agent_create_hooks = bool(value.get("allow_agent_create_hooks"))
    allow_access_outside_workdir = bool(value.get("allow_access_outside_workdir"))
    return {
        "approval_policy": approval_policy,
        "active_tier": active_tier,
        "tier_tools": tier_tools,
        "active_mode": active_mode,
        "allow_agent_install_skill": allow_agent_install_skill,
        "allow_agent_create_hooks": allow_agent_create_hooks,
        "allow_access_outside_workdir": allow_access_outside_workdir,
    }


async def _resolve_imagegen_config(*, context: "CoreLiveContext") -> dict[str, Any]:
    """Resolve generate_image runtime config from the core.imagegen settings namespace.

    Independent of the approval-policy resolution so explicit per-turn
    approval overrides (e.g. CLI --auto-approve) still apply imagegen settings.
    Missing/invalid settings → disabled (the tool is hidden from the model).
    """
    default: dict[str, Any] = {"enabled": False, "api_url": "", "api_key": "", "model": ""}
    if not context.operations.has("settings.get"):
        return default
    try:
        result = await context.operations.execute(
            "settings.get",
            {"namespace": "core.imagegen"},
            metadata={"source": "core_live"},
        )
    except Exception:
        return default
    if result.status != "ok":
        return default
    value = result.payload.get("value") if isinstance(result.payload, dict) else None
    if not isinstance(value, dict):
        return default
    return {
        "enabled": bool(value.get("enabled")),
        "api_url": str(value.get("api_url") or "").strip(),
        "api_key": str(value.get("api_key") or "").strip(),
        "model": str(value.get("model") or "").strip(),
    }


def _bundled_config_resources_dir() -> Path:
    """Directory of bundled tool-config resources (access_tools.jsonc, ...).

    Resolved relative to this file in dev; from ``_MEIPASS/config/resources``
    when frozen (PyInstaller).
    """
    if getattr(sys, "frozen", False):
        meipass = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return meipass / "config" / "resources"
    return Path(__file__).resolve().parent.parent.parent.parent / "config" / "resources"


def _load_tier_tools(context: "CoreLiveContext") -> TierTools | None:
    """Load access_tools.jsonc — prefer .lam/core/config/, then bundled."""
    from lamtools_core.config.root import core_config_file

    candidates: list[Path] = [core_config_file("access_tools.jsonc")]
    candidates.append(_bundled_config_resources_dir() / "access_tools.jsonc")
    for candidate in candidates:
        try:
            if candidate.exists():
                return load_access_tools(candidate)
        except (OSError, ValueError):
            continue
    return None


def _load_load_tools(context: "CoreLiveContext") -> LoadTools:
    """Load loadtools.jsonc — prefer .lam/core/config/, fallback to Core default."""
    from lamtools_core.config.root import core_config_file

    # Unified config directory (user-modifiable after packaging)
    candidate = core_config_file("loadtools.jsonc")
    try:
        if candidate.exists():
            member_tools = load_loadtools(candidate)
            if member_tools:
                return member_tools
    except (OSError, ValueError):
        pass
    # Fallback to Core built-in default
    return default_load_tools()


async def handle_turn_cancel_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    context: CoreLiveContext,
) -> CoreLiveOperationOutcome:
    thread_id = str(params.get("thread_id") or params.get("threadId") or params.get("session_id") or "").strip()
    if not thread_id:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="thread_id is required")
        )
    async def write(db):
        snapshot = await context.persistence.load(db, thread_id)
        requested_turn_id = str(params.get("turn_id") or params.get("turnId") or "")
        turn_id = requested_turn_id or latest_active_turn_id(snapshot) or ""
        # Fallback to the in-memory registry: when the snapshot has lost the
        # active turn (e.g. a sub-agent DB-lock error rewrote state before the
        # terminal event landed) the background task can still be running. The
        # registry is the source of truth for "is there a live task", so a
        # Stop click must still be able to target it — otherwise the user can
        # only kill the process (the 2b34c636 deadlock).
        if not turn_id:
            turn_id = context.host.runtime_task_registry.active_run_id(thread_id) or ""
        if requested_turn_id and not _is_active_turn(snapshot, requested_turn_id):
            turn_id = ""
        if not turn_id:
            payload: dict[str, Any] = {"status": "idle", "event": None}
            if params.get("include_snapshot") is not False:
                payload["snapshot"] = snapshot
            return CoreLiveOperationOutcome(response=rpc_result(request_id, payload))
        interrupted_input = AppEventInput(
            thread_id=thread_id,
            method="turn/interrupted",
            turn_id=turn_id,
            payload={"type": "turn", "reason": "user_interrupt"},
        )
        status_event = RunItemEvent(
            kind="status",
            thread_id=thread_id,
            event_id=f"{turn_id}:interrupting",
            run_id=turn_id,
            turn_id=turn_id,
            item_id=f"{turn_id}:interrupting",
            status="interrupting",
            payload={"type": "turn", "status": "interrupting", "raw_end_reason": "user_interrupt"},
        )
        envelopes = await context.persistence.append_batch(
            db,
            app_events=[interrupted_input],
            run_item_events=[status_event],
        )
        interrupted, status = envelopes[0], envelopes[1]
        snapshot = await context.persistence.load(db, thread_id)
        return interrupted, status, snapshot, turn_id

    write_result = await context.persistence.write(write)
    if isinstance(write_result, CoreLiveOperationOutcome):
        return write_result
    interrupted, status, snapshot, turn_id = write_result
    had_live_task = context.host.runtime_task_registry.active_run_id(thread_id) == turn_id
    context.host.runtime_task_registry.cancel(thread_id, run_id=turn_id or None, force=True)
    events = [interrupted, status]
    for event in events:
        await context.hub.publish(event)
    if not had_live_task:
        terminal = await _persist_cancelled_terminal(
            context=context,
            thread_id=thread_id,
            turn_id=turn_id,
        )
        if terminal is not None:
            events.append(terminal)
            async with context.session_factory() as db:
                snapshot = await context.persistence.load(db, thread_id)
    response_payload: dict[str, Any] = {"events": [event.to_dict() for event in events]}
    if params.get("include_snapshot") is not False:
        response_payload["snapshot"] = snapshot
    return CoreLiveOperationOutcome(
        response=rpc_result(request_id, response_payload),
        publish_events=events,
    )


async def handle_turn_force_reset_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    context: CoreLiveContext,
) -> CoreLiveOperationOutcome:
    """Force a turn back to a terminal/standby state, bypassing the
    active-turn guards that make ``turn.cancel`` a no-op once recovery has
    marked the turn ``cancelled``.

    This is the escape hatch for the stuck-state where the turn is durably
    terminal but trailing ``running`` tool_call events (e.g. a half-baked
    call left by an unexpected shutdown) keep the UI believing the turn is
    active. It unconditionally closes dangling items and writes/refreshes a
    terminal turn status, then reconciles the runtime state and cancels any
    in-memory task (a safe no-op when none exists).
    """
    thread_id = _thread_id_from_params(params)
    if not thread_id:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="thread_id is required")
        )
    requested_turn_id = str(params.get("turn_id") or params.get("turnId") or "").strip()

    async def write(db: AsyncSession) -> tuple[list[AppEventEnvelope], dict[str, Any]]:
        snapshot = await context.persistence.load(db, thread_id)
        turn_id = requested_turn_id or _latest_turn_id_any_status(snapshot)
        if not turn_id:
            return [], snapshot
        events: list[AppEventEnvelope] = []
        # 1. Close dangling non-terminal items (half-baked tool_calls etc.)
        # before the turn-level terminal event, so the per-item cancelled
        # status is recorded in the event log rather than masked by the
        # turn-terminal projection lock.
        for item_id in _collect_non_terminal_turn_item_ids(snapshot, turn_id):
            events.append(
                await _append_run_item(
                    db,
                    context=context,
                    event=_build_interrupted_tool_event(
                        thread_id=thread_id,
                        turn_id=turn_id,
                        item_id=item_id,
                        reason="force_reset",
                        message="Interrupted by force reset",
                    ),
                )
            )
        # 2. Write/refresh a turn-level cancelled status (skip if already
        # terminal AND we appended no per-item events — a terminal turn with
        # no dangling items needs no new turn event).
        already_terminal = _turn_is_terminal(snapshot, turn_id)
        if not already_terminal or events:
            status_event = await _append_run_item(
                db,
                context=context,
                event=RunItemEvent(
                    kind="status",
                    thread_id=thread_id,
                    event_id=f"{turn_id}:force_reset",
                    run_id=turn_id,
                    turn_id=turn_id,
                    item_id=f"{turn_id}:force_reset",
                    status="cancelled",
                    payload={
                        "type": "turn",
                        "status": "cancelled",
                        "raw_end_reason": "force_reset",
                        "message": "Force reset to standby",
                    },
                ),
            )
            events.append(status_event)
        snapshot = await context.persistence.load(db, thread_id)
        return events, snapshot

    write_result = await context.persistence.write(write)
    events, snapshot = write_result
    turn_id = requested_turn_id or _latest_turn_id_any_status(snapshot)
    if turn_id:
        await _persist_cancelled_runtime_state(context=context, thread_id=thread_id, turn_id=turn_id)
        context.host.runtime_task_registry.cancel(thread_id, run_id=turn_id or None, force=True)
    for event in events:
        await context.hub.publish(event)
    response_payload: dict[str, Any] = {"status": "reset", "events": [event.to_dict() for event in events]}
    if params.get("include_snapshot") is not False:
        response_payload["snapshot"] = snapshot
    return CoreLiveOperationOutcome(
        response=rpc_result(request_id, response_payload),
        publish_events=events,
    )


async def handle_turn_steer_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    context: CoreLiveContext,
) -> CoreLiveOperationOutcome:
    thread_id = _thread_id_from_params(params)
    turn_id = str(params.get("turn_id") or params.get("turnId") or "").strip()
    client_message_id = str(params.get("client_message_id") or params.get("clientMessageId") or uuid.uuid4().hex)
    input_items = params.get("input") if isinstance(params.get("input"), list) else params.get("input_items")
    if not thread_id or not turn_id or not isinstance(input_items, list):
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="thread_id, turn_id and input are required")
        )
    text = input_items_text(input_items)
    if not text:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="steer input must include text")
        )
    guidance_accepted = False

    async def write(db):
        nonlocal guidance_accepted
        existing = await context.persistence.find_client_event(
            db,
            thread_id=thread_id,
            client_message_id=client_message_id,
            methods={"turn/steered"},
        )
        if existing is not None:
            snapshot = await context.persistence.load(db, thread_id)
            return CoreLiveOperationOutcome(
                response=rpc_result(
                    request_id,
                    {"applied": True, "reason": "already_applied", "events": [existing.to_dict()], "snapshot": snapshot},
                )
            )
        snapshot = await context.persistence.load(db, thread_id)
        registry_run_id = context.host.runtime_task_registry.active_run_id(thread_id)
        if not _is_active_turn(snapshot, turn_id) and registry_run_id != turn_id:
            return CoreLiveOperationOutcome(
                response=rpc_result(request_id, {"applied": False, "reason": "active_turn_mismatch", "events": [], "snapshot": snapshot})
            )
        guidance_status = context.host.runtime_task_registry.accept_guidance(
            thread_id,
            text,
            run_id=turn_id,
            guidance_id=client_message_id,
        )
        if guidance_status not in {"accepted", "duplicate"}:
            return CoreLiveOperationOutcome(
                response=rpc_result(request_id, {"applied": False, "reason": "run_not_active", "events": [], "snapshot": snapshot})
            )
        if guidance_status == "accepted":
            guidance_accepted = True
        try:
            event = await _append_app_event(
                db,
                context=context,
                event=AppEventInput(
                    thread_id=thread_id,
                    method="turn/steered",
                    turn_id=turn_id,
                    client_message_id=client_message_id,
                    payload={"type": "turn", "input": input_items},
                ),
            )
            snapshot = await context.persistence.load(db, thread_id)
            return event, snapshot
        except BaseException:
            context.host.runtime_task_registry.retract_guidance(
                thread_id, run_id=turn_id, guidance_id=client_message_id
            )
            guidance_accepted = False
            raise

    try:
        write_result = await context.persistence.write(write)
    except BaseException:
        if guidance_accepted:
            context.host.runtime_task_registry.retract_guidance(
                thread_id, run_id=turn_id, guidance_id=client_message_id
            )
        raise
    if isinstance(write_result, CoreLiveOperationOutcome):
        return write_result
    event, snapshot = write_result
    await context.hub.publish(event)
    return CoreLiveOperationOutcome(
        response=rpc_result(
            request_id,
            {"applied": True, "reason": "", "events": [event.to_dict()], "snapshot": snapshot},
        ),
        publish_events=[event],
    )


async def handle_approval_respond_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    context: CoreLiveContext,
) -> CoreLiveOperationOutcome:
    if not context.operations.has("approval.respond"):
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="approval.respond operation is unavailable")
        )
    loop = asyncio.get_running_loop()
    decision_ready: asyncio.Future[dict[str, Any]] = loop.create_future()

    async def decision_durable(info: dict[str, Any]) -> None:
        thread_id = str(info.get("thread_id") or "").strip()
        run_id = str(info.get("run_id") or info.get("turn_id") or "").strip()
        task = asyncio.current_task()
        if str(info.get("decision") or "") != "deny":
            if task is None or not thread_id or not run_id:
                raise RuntimeError("approval continuation identity is unavailable")
            prior_task = context.host.runtime_task_registry.task(thread_id, run_id=run_id)
            if prior_task is not None and prior_task is not task:
                context.host.runtime_task_registry.release_run(thread_id, run_id=run_id)
            if not context.host.runtime_task_registry.accept_run(thread_id, run_id):
                raise RuntimeError("approval continuation runtime claim failed")
            if not context.host.runtime_task_registry.register(thread_id, task, run_id=run_id):
                context.host.runtime_task_registry.release_run(thread_id, run_id=run_id)
                raise RuntimeError("approval continuation task registration failed")
            if not decision_ready.done():
                decision_ready.set_result(dict(info))

    async def continue_approval() -> OperationResult:
        thread_id = ""
        run_id = ""
        try:
            resolved = await _resolve_turn_approval_policy(context=context, params={})
            approval_params = {
                **params,
                "approval_policy": resolved["approval_policy"],
                "active_tier": resolved["active_tier"],
                "tier_tools": resolved["tier_tools"],
                "allow_access_outside_workdir": resolved.get("allow_access_outside_workdir", False),
            }
            result = await context.operations.execute(
                "approval.respond",
                approval_params,
                metadata={
                    "source": "core_live",
                    "approval_decision_durable": decision_durable,
                },
            )
            payload = dict(result.payload or {})
            thread_id = str(payload.get("thread_id") or "").strip()
            run_id = str(payload.get("run_id") or payload.get("turn_id") or "").strip()
            if result.status == "ok" and str(payload.get("decision") or "") == "done" and thread_id:
                info = decision_ready.result() if decision_ready.done() and not decision_ready.cancelled() else {}
                await _dispatch_next_queue_item(
                    context=context,
                    thread_id=thread_id,
                    work_root=str(info.get("work_root") or ""),
                    completed_turn_id=run_id,
                )
            return result
        except asyncio.CancelledError:
            info = decision_ready.result() if decision_ready.done() and not decision_ready.cancelled() else {}
            thread_id = thread_id or str(info.get("thread_id") or "").strip()
            run_id = run_id or str(info.get("run_id") or info.get("turn_id") or "").strip()
            if thread_id and run_id:
                await asyncio.shield(
                    _persist_cancelled_terminal(
                        context=context,
                        thread_id=thread_id,
                        turn_id=run_id,
                    )
                )
            raise

    task = loop.create_task(continue_approval())
    done, _pending = await asyncio.wait(
        {decision_ready, task},
        return_when=asyncio.FIRST_COMPLETED,
    )
    if decision_ready in done:
        info = decision_ready.result()
        return CoreLiveOperationOutcome(
            response=rpc_result(
                request_id,
                {
                    "thread_id": info.get("thread_id"),
                    "run_id": info.get("run_id"),
                    "turn_id": info.get("turn_id"),
                    "decision": info.get("decision"),
                    "status": "accepted",
                    "snapshot": info.get("snapshot"),
                },
            )
        )

    result = task.result()
    payload = dict(result.payload or {})
    if result.status != "ok":
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message=str(payload.get("error") or result.status), data=payload)
        )
    if str(payload.get("decision") or "") in {"deny", "denied"}:
        thread_id = str(payload.get("thread_id") or _thread_id_from_params(params)).strip()
        run_id = str(payload.get("run_id") or payload.get("turn_id") or "").strip()
        if thread_id and run_id:
            context.host.runtime_task_registry.release_run(thread_id, run_id=run_id)
    return CoreLiveOperationOutcome(response=rpc_result(request_id, payload))


async def handle_queue_create_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    context: CoreLiveContext,
) -> CoreLiveOperationOutcome:
    thread_id = str(params.get("thread_id") or params.get("threadId") or params.get("session_id") or "").strip()
    input_items = params.get("input")
    if not thread_id or not isinstance(input_items, list):
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="thread_id and input are required")
        )
    try:
        prepared = await context.host.member_hooks.prepare_queue_input(
            thread_id=thread_id, params=params, input_items=input_items
        )
    except ValueError as exc:
        return CoreLiveOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    queue_item_id = str(params.get("queue_item_id") or params.get("queueItemId") or f"queue:{uuid.uuid4().hex[:12]}")
    client_message_id = str(params.get("client_message_id") or params.get("clientMessageId") or uuid.uuid4().hex)
    payload = queue_item_payload(
        queue_item_id=queue_item_id,
        input_items=prepared.visible_input,
        runtime_input_items=prepared.runtime_input,
        mode=str(params.get("mode") or "next_turn"),
    )
    async def write(db: AsyncSession):
        existing = await context.persistence.find_client_event(
            db,
            thread_id=thread_id,
            client_message_id=client_message_id,
            methods=QUEUE_ITEM_ACCEPTED_METHODS,
        )
        if existing is not None:
            snapshot = await context.persistence.load(db, thread_id)
            return existing, snapshot
        materialized = await context.host.member_hooks.materialize_queue(
            db=db,
            thread_id=thread_id,
            queue_item_id=queue_item_id,
            client_message_id=client_message_id,
            prepared=prepared,
            params=params,
        )
        event = await _append_app_event(
            db,
            context=context,
            event=AppEventInput(
                thread_id=thread_id,
                method="queue/itemAccepted",
                item_id=queue_item_id,
                client_message_id=client_message_id,
                payload={**payload, **materialized.payload_extra},
            ),
        )
        snapshot = await context.persistence.load(db, thread_id)
        return event, snapshot

    event, snapshot = await context.persistence.write(write)
    await context.hub.publish(event)
    queue_item = next(
        (item for item in snapshot.get("queue", []) if isinstance(item, dict) and item.get("queue_item_id") == queue_item_id),
        {"queue_item_id": queue_item_id, "status": "queued", "input": input_items},
    )
    return CoreLiveOperationOutcome(
        response=rpc_result(request_id, {"queue_item": queue_item, "events": [event.to_dict()], "snapshot": snapshot}),
        publish_events=[event],
    )


async def handle_queue_update_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    context: CoreLiveContext,
) -> CoreLiveOperationOutcome:
    thread_id = str(params.get("thread_id") or params.get("threadId") or params.get("session_id") or "").strip()
    queue_item_id = str(params.get("queue_item_id") or params.get("queueItemId") or "").strip()
    if not thread_id or not queue_item_id:
        return CoreLiveOperationOutcome(
            response=rpc_error(
                request_id,
                code=INVALID_REQUEST,
                message="thread_id, queue_item_id and text are required",
            )
        )
    input_items = params.get("input")
    if not isinstance(input_items, list):
        text = str(params.get("text") or "").strip()
        if not text:
            return CoreLiveOperationOutcome(
                response=rpc_error(
                    request_id,
                    code=INVALID_REQUEST,
                    message="thread_id, queue_item_id and text are required",
                )
            )
        input_items = [{"type": "text", "text": text}]
    try:
        prepared = await context.host.member_hooks.prepare_queue_input(
            thread_id=thread_id,
            params=params,
            input_items=input_items,
        )
    except ValueError as exc:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc))
        )
    async def write(
        db: AsyncSession,
    ) -> CoreLiveOperationOutcome | tuple[AppEventEnvelope, dict[str, Any]]:
        snapshot = await context.persistence.load(db, thread_id)
        plan = build_queue_update_plan(
            snapshot,
            queue_item_id=queue_item_id,
            input_items=prepared.visible_input,
            runtime_input_items=prepared.runtime_input,
            mode=str(params.get("mode") or "").strip() or None,
        )
        if not plan.applied:
            return CoreLiveOperationOutcome(
                response=rpc_result(
                    request_id,
                    {
                        "applied": False,
                        "reason": plan.reason,
                        "events": [],
                        "snapshot": snapshot,
                    },
                )
            )
        event = await _append_app_event(
            db,
            context=context,
            event=AppEventInput(
                thread_id=thread_id,
                method="queue/itemUpdated",
                item_id=queue_item_id,
                payload=plan.payload or {},
            ),
        )
        snapshot = await context.persistence.load(db, thread_id)
        return event, snapshot

    write_result = await context.persistence.write(write)
    if isinstance(write_result, CoreLiveOperationOutcome):
        return write_result
    event, snapshot = write_result
    await context.hub.publish(event)
    return CoreLiveOperationOutcome(
        response=rpc_result(request_id, {"events": [event.to_dict()], "snapshot": snapshot}),
        publish_events=[event],
    )


async def handle_queue_delete_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    context: CoreLiveContext,
) -> CoreLiveOperationOutcome:
    thread_id = str(params.get("thread_id") or params.get("threadId") or params.get("session_id") or "").strip()
    queue_item_id = str(params.get("queue_item_id") or params.get("queueItemId") or "").strip()
    if not thread_id or not queue_item_id:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="thread_id and queue_item_id are required")
        )
    async def write(db: AsyncSession) -> tuple[AppEventEnvelope, dict[str, Any]]:
        event = await _append_app_event(
            db,
            context=context,
            event=AppEventInput(
                thread_id=thread_id,
                method="queue/itemDeleted",
                item_id=queue_item_id,
                payload=queue_delete_payload(queue_item_id=queue_item_id, status="deleted"),
            ),
        )
        snapshot = await context.persistence.load(db, thread_id)
        return event, snapshot

    event, snapshot = await context.persistence.write(write)
    await context.hub.publish(event)
    return CoreLiveOperationOutcome(
        response=rpc_result(request_id, {"events": [event.to_dict()], "snapshot": snapshot}),
        publish_events=[event],
    )


async def handle_queue_guidance_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    context: CoreLiveContext,
) -> CoreLiveOperationOutcome:
    thread_id = str(params.get("thread_id") or params.get("threadId") or params.get("session_id") or "").strip()
    turn_id = str(params.get("turn_id") or params.get("turnId") or "").strip()
    queue_item_id = str(params.get("queue_item_id") or params.get("queueItemId") or "").strip()
    if not thread_id or not turn_id or not queue_item_id:
        return CoreLiveOperationOutcome(
            response=rpc_error(
                request_id,
                code=INVALID_REQUEST,
                message="thread_id, turn_id and queue_item_id are required",
            )
        )
    client_message_id = str(
        params.get("client_message_id") or params.get("clientMessageId") or f"queue-guide:{queue_item_id}"
    )
    replacement_text = params.get("text") if isinstance(params.get("text"), str) else None
    guidance_accepted = False

    async def write(
        db: AsyncSession,
    ) -> CoreLiveOperationOutcome | tuple[list[AppEventEnvelope], dict[str, Any], Any]:
        nonlocal guidance_accepted
        existing = await context.persistence.find_client_event(
            db,
            thread_id=thread_id,
            client_message_id=client_message_id,
            methods={"turn/steered"},
        )
        if existing is not None:
            snapshot = await context.persistence.load(db, thread_id)
            return CoreLiveOperationOutcome(
                response=rpc_result(
                    request_id,
                    {"applied": True, "reason": "already_applied", "events": [existing.to_dict()], "snapshot": snapshot},
                )
            )
        snapshot = await context.persistence.load(db, thread_id)
        plan = build_queue_guidance_plan(
            snapshot,
            thread_id=thread_id,
            turn_id=turn_id,
            queue_item_id=queue_item_id,
            client_message_id=client_message_id,
            replacement_text=replacement_text,
        )
        if plan.applied:
            guidance_text = input_items_text(plan.runtime_input_items)
            guidance_status = context.host.runtime_task_registry.accept_guidance(
                thread_id,
                guidance_text,
                run_id=turn_id,
                guidance_id=client_message_id,
            )
            if guidance_status not in {"accepted", "duplicate"}:
                return CoreLiveOperationOutcome(
                    response=rpc_result(
                        request_id,
                        {"applied": False, "reason": "run_not_active", "events": [], "snapshot": snapshot},
                    )
                )
            if guidance_status == "accepted":
                guidance_accepted = True
            events: list[AppEventEnvelope] = []
            try:
                app_event_inputs = [_app_event_input(spec) for spec in plan.events]
                if app_event_inputs:
                    events = await context.persistence.append_batch(db, app_events=app_event_inputs)
                snapshot = await context.persistence.load(db, thread_id)
            except BaseException:
                context.host.runtime_task_registry.retract_guidance(
                    thread_id, run_id=turn_id, guidance_id=client_message_id
                )
                guidance_accepted = False
                raise
            return events, snapshot, plan
        return [], snapshot, plan

    try:
        write_result = await context.persistence.write(write)
    except BaseException:
        if guidance_accepted:
            context.host.runtime_task_registry.retract_guidance(
                thread_id, run_id=turn_id, guidance_id=client_message_id
            )
        raise
    if isinstance(write_result, CoreLiveOperationOutcome):
        return write_result
    events, snapshot, plan = write_result
    for event in events:
        await context.hub.publish(event)
    return CoreLiveOperationOutcome(
        response=rpc_result(
            request_id,
            {
                "applied": plan.applied,
                "reason": plan.reason,
                "events": [event.to_dict() for event in events],
                "snapshot": snapshot,
            },
        ),
        publish_events=events,
    )


async def _append_app_event(
    db: AsyncSession,
    *,
    context: CoreLiveContext,
    event: AppEventInput,
) -> AppEventEnvelope:
    return await context.persistence.append(db, event)


def _app_event_input(spec: CoreAppEventSpec) -> AppEventInput:
    return AppEventInput(
        event_id=spec.event_id,
        thread_id=spec.thread_id,
        method=spec.method,
        payload=spec.payload,
        turn_id=spec.turn_id,
        item_id=spec.item_id,
        parent_item_id=spec.parent_item_id,
        client_message_id=spec.client_message_id,
    )


async def _append_run_item(
    db: AsyncSession,
    *,
    context: CoreLiveContext,
    event: RunItemEvent,
) -> AppEventEnvelope:
    return await context.persistence.append_run_item(db, event)


def _get_running_loop() -> asyncio.AbstractEventLoop:
    return asyncio.get_running_loop()


async def _auto_title_session(
    *,
    context: CoreLiveContext,
    thread_id: str,
    first_message: str,
) -> None:
    """Background task: derive a short title from the first user message.

    Best-effort — any failure is logged and swallowed so it can never affect
    the ongoing turn. Persists the title via the session store (when available)
    and broadcasts ``session/updated`` so frontends refresh their sidebar.
    """
    llm_client = context.host.llm_client
    model_id = context.host.default_model_id
    session_store = context.host.session_store
    if llm_client is None:
        return
    try:
        # Don't clobber a title the user already set manually.
        existing_title: str | None = None
        if session_store is not None:
            existing = await session_store.get(thread_id)
            existing_title = getattr(existing, "title", None) if existing else None
        if not is_default_title(existing_title, session_id=thread_id):
            return

        title = await generate_session_title(llm_client, model_id, first_message)
        if not title:
            return

        if session_store is not None:
            # Conditional patch: the earlier guard checked the title before the
            # LLM call, but the user may have renamed the session meanwhile.
            # only_if_title_default makes the check atomic with the write, so a
            # manual rename in that window is never clobbered. None means the
            # title was no longer default (or the session is gone) — nothing to
            # broadcast.
            patched = await session_store.patch(
                thread_id,
                title=title,
                only_if_title_default=True,
            )
            if patched is None:
                return

        await context.hub.publish({
            "method": "session/updated",
            "thread_id": thread_id,
            "payload": {"session": {"title": title}},
        })
        _logger.info("[autotitle] generated title for thread=%s title=%r", thread_id, title)
    except Exception:  # noqa: BLE001 — must never break the turn
        _logger.warning("[autotitle] failed for thread=%s", thread_id, exc_info=True)


async def _start_runtime_task(
    *, context: CoreLiveContext, runtime_start: dict[str, Any]
) -> tuple[AppEventEnvelope, dict[str, Any]] | None:
    thread_id = str(runtime_start.get("thread_id") or "")
    turn_id = str(runtime_start.get("turn_id") or "")
    if isinstance(context.host.member_hooks, DefaultCoreLiveMemberHooks) and not context.operations.has("turn.start"):
        return await _fail_runtime_start(
            context=context,
            thread_id=thread_id,
            turn_id=turn_id,
            message="turn.start operation is unavailable",
        )
    message = str(runtime_start.get("text") or "")
    if not thread_id or not message:
        return await _fail_runtime_start(
            context=context,
            thread_id=thread_id,
            turn_id=turn_id,
            message="runtime input is empty",
        )

    try:
        loop = _get_running_loop()
    except RuntimeError as exc:
        return await _fail_runtime_start(
            context=context,
            thread_id=thread_id,
            turn_id=turn_id,
            message=str(exc) or "no running event loop",
        )
    coroutine = _run_core_turn(context=context, runtime_start=runtime_start)
    try:
        task = loop.create_task(coroutine)
    except BaseException as exc:
        coroutine.close()
        return await _fail_runtime_start(
            context=context,
            thread_id=thread_id,
            turn_id=turn_id,
            message=str(exc) or "runtime task creation failed",
        )
    if task.done() or not context.host.runtime_task_registry.register(thread_id, task, run_id=turn_id):
        return await _fail_runtime_start(
            context=context,
            thread_id=thread_id,
            turn_id=turn_id,
            message="runtime task registration failed",
            task=task,
        )
    return None


async def _fail_runtime_start(
    *,
    context: CoreLiveContext,
    thread_id: str,
    turn_id: str,
    message: str,
    task: asyncio.Future[Any] | None = None,
) -> tuple[AppEventEnvelope, dict[str, Any]]:
    if task is not None:
        if not task.done():
            task.cancel()
        try:
            await task
        except BaseException:
            pass
    # Defer release_run until *after* the terminal event is durably
    # persisted. Releasing first opens a window where the registry no longer
    # reports an active run but the snapshot has no terminal status yet — a
    # subsequent turn.start then passes both the snapshot guard and the
    # registry guard and is accepted while the old turn's background work is
    # still flushing, which is exactly the race that deadlocked session
    # 2b34c636 (new turn's runtime_start raced the old turn's final
    # replace_history for the DB write lock). If the write itself fails we
    # still must release so the thread is not permanently stuck.
    async def write(
        db: AsyncSession,
    ) -> tuple[AppEventEnvelope, dict[str, Any]]:
        snapshot = await context.persistence.load(db, thread_id)
        if _turn_is_terminal(snapshot, turn_id):
            terminal_events = await context.persistence.list_after(db, thread_id=thread_id, after_seq=0)
            # Use a default to avoid StopIteration → PEP 479 RuntimeError
            # when no matching terminal event is found (can happen if the
            # snapshot is terminal but the event log has no CORE_RUN_ITEM
            # entry for this turn — e.g. after a revision conflict).
            event = next(
                (
                    event
                    for event in reversed(terminal_events)
                    if event.turn_id == turn_id and event.method == CORE_RUN_ITEM_METHOD
                ),
                None,
            )
            if event is not None:
                return event, snapshot
            # Fall through to the normal failed-event write below.
        core = snapshot.get("core") if isinstance(snapshot.get("core"), dict) else {}
        requests = core.get("requests") if isinstance(core, dict) else {}
        denied_request = any(
            isinstance(pending, dict)
            and str(pending.get("turn_id") or "") == turn_id
            and str(pending.get("status") or "") == "resolved"
            and str(pending.get("decision") or pending.get("action") or "") in {"deny", "denied"}
            for pending in (requests.values() if isinstance(requests, dict) else [])
        )
        if denied_request:
            prior_events = await context.persistence.list_after(db, thread_id=thread_id, after_seq=0)
            prior = next(
                (event for event in reversed(prior_events) if event.turn_id == turn_id),
                None,
            )
            if prior is not None:
                return prior, snapshot
            # Fall through to the normal failed-event write below.
        event = await _append_run_item(
            db,
            context=context,
            event=RunItemEvent(
                kind="status",
                thread_id=thread_id,
                event_id=f"{turn_id}:runtime-start-failed",
                run_id=turn_id,
                turn_id=turn_id,
                item_id=f"{turn_id}:runtime-start-failed",
                status="failed",
                payload={
                    "type": "turn",
                    "status": "failed",
                    "raw_end_reason": "runtime_start_failed",
                    "message": message,
                },
            ),
        )
        snapshot = await context.persistence.load(db, thread_id)
        return event, snapshot

    try:
        event, snapshot = await context.persistence.write(write)
    finally:
        # Release the run claim only once the terminal event is durably
        # written (or the write failed — either way the claim must not
        # outlive this function, or the thread would be stuck "active").
        context.host.runtime_task_registry.release_run(thread_id, run_id=turn_id)
    await context.hub.publish(event)
    return event, snapshot


async def _run_core_turn(*, context: CoreLiveContext, runtime_start: dict[str, Any]) -> None:
    thread_id = str(runtime_start.get("thread_id") or "")
    turn_id = str(runtime_start.get("turn_id") or "")
    _start_ts = time_module.time()
    _logger.info("[live:_run_core_turn] background task started thread_id=%s turn_id=%s", thread_id, turn_id)
    try:
        payload = {
            **runtime_start,
            "session_id": thread_id,
            "message": str(runtime_start.get("text") or ""),
        }

        async def execute_core_operation(operation_payload: dict[str, Any]) -> OperationResult:
            return await context.operations.execute(
                "turn.start", operation_payload, metadata={"source": "core_live"}
            )

        if isinstance(context.host.member_hooks, DefaultCoreLiveMemberHooks):
            payload["_core_operation"] = execute_core_operation
        _logger.info("[live:_run_core_turn] entering member_hooks.start_runtime thread_id=%s turn_id=%s",
                      thread_id, turn_id)
        result = await context.host.member_hooks.start_runtime(
            runtime_start=payload,
        )
        # Release the registry claim as soon as start_runtime returns — the
        # runtime has finished (terminal events are already persisted live)
        # and trailing cleanup (_persist_operation_result,
        # _ensure_turn_terminal, _dispatch_next_queue_item) must not keep the
        # active-turn guard blocking a subsequent turn.start from the client.
        # These steps do DB I/O that can yield the event loop, letting an SSE
        # round-trip race ahead and unblock the UI before release_run.
        context.host.runtime_task_registry.release_run(thread_id, run_id=turn_id)
        if isinstance(result, OperationResult):
            _elapsed = time_module.time() - _start_ts
            _logger.info("[live:_run_core_turn] turn completed thread_id=%s turn_id=%s status=%s elapsed=%.2fs",
                          thread_id, turn_id, result.status, _elapsed)
            await _persist_operation_result(context=context, thread_id=thread_id, turn_id=turn_id, result=result)
            await _ensure_turn_terminal(context=context, thread_id=thread_id, turn_id=turn_id)
        await _dispatch_next_queue_item(
            context=context,
            thread_id=thread_id,
            work_root=str(runtime_start.get("work_root") or ""),
            completed_turn_id=turn_id,
        )
    except BaseException as exc:
        _elapsed = time_module.time() - _start_ts
        _logger.exception("[live:_run_core_turn] turn failed thread_id=%s turn_id=%s elapsed=%.2fs",
                          thread_id, turn_id, _elapsed)
        cancel_requested = context.host.runtime_task_registry.get_cancel_event(thread_id).is_set()
        if cancel_requested:
            await asyncio.shield(
                _persist_cancelled_terminal(
                    context=context,
                    thread_id=thread_id,
                    turn_id=turn_id,
                )
            )
            raise
        await asyncio.shield(
            _fail_runtime_start(
                context=context,
                thread_id=thread_id,
                turn_id=turn_id,
                message=str(exc) or "member runtime failed",
            )
        )


async def _ensure_turn_terminal(
    *,
    context: CoreLiveContext,
    thread_id: str,
    turn_id: str,
) -> None:
    """After a normal turn completion, ensure the thread status reflects completion
    so that queued items can be dispatched.  This covers the case where member
    hooks persist events live and the terminal status may not be reflected in the
    snapshot store yet."""
    async with context.session_factory() as db:
        snapshot = await context.persistence.load(db, thread_id)
    queue = snapshot.get("queue")
    if not isinstance(queue, list) or not queue:
        return
    if effective_thread_status(snapshot) in {"completed", "idle"}:
        return
    # Check if the current turn is the last active turn
    core_state = snapshot.get("core") if isinstance(snapshot.get("core"), dict) else {}
    latest_active = latest_active_turn_id({"core": core_state, "turns": snapshot.get("turns", {})})
    if latest_active is not None and latest_active != turn_id:
        return
    # Write a completed terminal status event
    terminal = RunItemEvent(
        kind="status",
        thread_id=thread_id,
        event_id=f"{turn_id}:terminal",
        run_id=turn_id,
        turn_id=turn_id,
        item_id=f"{turn_id}:terminal",
        status="completed",
    )

    async def write(db):
        return await _append_run_item(db, context=context, event=terminal)

    try:
        event = await context.persistence.write(write)
        await context.hub.publish(event)
    except BaseException:
        _logger.exception(
            "[live:_ensure_turn_terminal] failed thread_id=%s turn_id=%s",
            thread_id, turn_id,
        )


async def _dispatch_next_queue_item(
    *,
    context: CoreLiveContext,
    thread_id: str,
    work_root: str,
    completed_turn_id: str,
) -> None:
    async with context.session_factory() as db:
        current_snapshot = await context.persistence.load(db, thread_id)
    if next_dispatchable_queue_item(current_snapshot) is None:
        return
    context.host.runtime_task_registry.release_run(thread_id, run_id=completed_turn_id)
    resolved = await _resolve_turn_approval_policy(context=context, params={})
    claimed_turn_id = ""

    async def write(db: AsyncSession):
        nonlocal claimed_turn_id
        snapshot = await context.persistence.load(db, thread_id)
        queued = next_dispatchable_queue_item(snapshot)
        dispatch = queue_dispatch_payload(queued) if queued is not None else None
        if dispatch is None:
            return None
        queue_item_id, visible_input, runtime_input, dispatch_payload = dispatch
        turn_id = f"{thread_id}:turn:{uuid.uuid4().hex[:12]}"
        user_item_id = f"{turn_id}:user"
        if not context.host.runtime_task_registry.accept_run(thread_id, turn_id):
            return None
        claimed_turn_id = turn_id
        try:
            queued_work_root = str(queued.get("work_root") or work_root)
            prepared = PreparedLiveInput(
                visible_input=visible_input,
                runtime_input=runtime_input,
                visible_text=input_items_text(visible_input),
                runtime_text=input_items_text(runtime_input),
                work_root=queued_work_root,
            )
            materialized = await context.host.member_hooks.materialize_turn(
                db=db,
                thread_id=thread_id,
                turn_id=turn_id,
                user_item_id=user_item_id,
                client_message_id=f"dispatch:{queue_item_id}",
                prepared=prepared,
                params={"work_root": work_root},
            )
            dispatched_input = AppEventInput(
                thread_id=thread_id,
                method="queue/itemDispatched",
                item_id=queue_item_id,
                client_message_id=f"dispatch:{queue_item_id}",
                payload=dispatch_payload,
            )
            plan = build_turn_acceptance_plan(
                thread_id=thread_id,
                turn_id=turn_id,
                user_item_id=user_item_id,
                client_message_id=f"dispatch:{queue_item_id}",
                input_items=prepared.visible_input,
                work_root=prepared.work_root,
                turn_payload_extra=materialized.turn_payload_extra,
                user_payload_extra=materialized.user_payload_extra,
                include_turn_status=materialized.include_turn_status,
            )
            envelopes = await context.persistence.append_batch(
                db,
                app_events=[dispatched_input, _app_event_input(plan.turn_accepted), _app_event_input(plan.user_item)],
                run_item_events=[plan.running_status],
            )
            dispatched, accepted, user, running = envelopes[0], envelopes[1], envelopes[2], envelopes[3]
            runtime_start = {
                "thread_id": thread_id,
                "turn_id": turn_id,
                "user_message_id": user_item_id,
                "text": prepared.runtime_text,
                "input": prepared.runtime_input,
                "work_root": prepared.work_root,
                "approval_policy": resolved["approval_policy"],
                "active_tier": resolved["active_tier"],
                "tier_tools": resolved["tier_tools"],
                "active_mode": resolved["active_mode"],
                "allow_agent_install_skill": resolved.get("allow_agent_install_skill", False),
                "allow_agent_create_hooks": resolved.get("allow_agent_create_hooks", False),
                **prepared.runtime_extras,
                **materialized.runtime_extras,
            }
            return [dispatched, accepted, user, running], runtime_start
        except BaseException:
            context.host.runtime_task_registry.release_run(thread_id, run_id=turn_id)
            claimed_turn_id = ""
            raise

    try:
        result = await context.persistence.write(write)
    except BaseException:
        if claimed_turn_id:
            context.host.runtime_task_registry.release_run(thread_id, run_id=claimed_turn_id)
        raise
    if result is None:
        return
    events, next_runtime_start = result
    for event in events:
        await context.hub.publish(event)
    await _start_runtime_task(context=context, runtime_start=next_runtime_start)


def _collect_non_terminal_turn_item_ids(snapshot: dict[str, Any], turn_id: str) -> list[str]:
    """Return item_ids under ``turn_id`` whose status is not terminal.

    Used by the crash-recovery and force-reset paths to find dangling
    tool_call / tool_result / message items left ``running`` / ``waiting``
    when the process died mid-turn. The snapshot projection closes these
    in-memory (``_close_turn_items``) once the turn itself flips terminal,
    but the *event log* retains the orphaned running events — this collects
    them so a terminal ``tool_result`` event can be appended per item,
    making the event stream self-consistent for replay.
    """
    core = snapshot.get("core") if isinstance(snapshot, dict) else None
    if not isinstance(core, dict):
        return []
    turns = core.get("turns") if isinstance(core.get("turns"), dict) else {}
    turn = turns.get(turn_id)
    if not isinstance(turn, dict):
        return []
    items = core.get("items") if isinstance(core.get("items"), dict) else {}
    result: list[str] = []
    for item_id in turn.get("items") or []:
        item = items.get(item_id)
        if not isinstance(item, dict):
            continue
        if str(item.get("status") or "") not in TERMINAL_TURN_STATUSES:
            result.append(item_id)
    return result


def _build_interrupted_tool_event(
    *,
    thread_id: str,
    turn_id: str,
    item_id: str,
    reason: str = "unexpected_shutdown",
    message: str = "Interrupted by unexpected shutdown",
) -> RunItemEvent:
    """Build a terminal ``tool_result`` event that closes a dangling tool_call.

    Shares the target item_id so projection (last-write-wins by item_id)
    flips that tool_call item to ``cancelled``. Use ``kind="tool_result"``
    (not ``status``) so the snapshot marks the *item* terminal rather than
    being treated as a turn-status event.
    """
    return RunItemEvent(
        kind="tool_result",
        thread_id=thread_id,
        event_id=f"{item_id}:{reason}",
        run_id=turn_id,
        turn_id=turn_id,
        item_id=item_id,
        status="cancelled",
        payload={
            "type": "dynamicToolCall",
            "status": "cancelled",
            "raw_end_reason": reason,
            "message": message,
        },
    )


async def _persist_cancelled_terminal(
    *,
    context: CoreLiveContext,
    thread_id: str,
    turn_id: str,
) -> AppEventEnvelope | None:
    await _persist_cancelled_runtime_state(context=context, thread_id=thread_id, turn_id=turn_id)

    async def write(db: AsyncSession) -> AppEventEnvelope | None:
        snapshot = await context.persistence.load(db, thread_id)
        if _turn_is_terminal(snapshot, turn_id):
            return None
        event = await _append_run_item(
            db,
            context=context,
            event=build_cancelled_turn_event(thread_id=thread_id, turn_id=turn_id),
        )
        return event

    event = await context.persistence.write(write)
    if event is None:
        return None
    await context.hub.publish(event)
    return event


async def _save_runtime_state_with_retry(
    store: RuntimeStateStore,
    thread_id: str,
    *,
    mutate: "Callable[[RuntimeState], None]",
    max_attempts: int = 5,
) -> None:
    """Load-mutate-save a RuntimeState with optimistic-retry on revision conflict.

    When recover/cancel paths and the main turn loop write the same session
    concurrently, the revision can change between ``get`` and ``save``.
    Instead of crashing, reload the latest state and retry.
    """
    for _ in range(max_attempts):
        state = await store.get(thread_id)
        if state is None:
            return
        mutate(state)
        try:
            await store.save(state)
            return
        except RuntimeStateConflictError:
            continue
    _logger.warning("[live] runtime state save exhausted %d retries thread_id=%s", max_attempts, thread_id)


async def _persist_cancelled_runtime_state(
    *, context: CoreLiveContext, thread_id: str, turn_id: str
) -> None:
    store = context.runtime_state_store
    if store is None:
        return

    def _mark_cancelled(state: Any) -> None:
        if state.run_id != turn_id:
            return
        state.status = "cancelled"
        state.loop_state = "failed"
        state.metadata.pop("pending_approval", None)
        state.metadata.pop("pending_waiting_request", None)

    await _save_runtime_state_with_retry(store, thread_id, mutate=_mark_cancelled)


async def _reconcile_cancelled_runtime_state(
    *, context: CoreLiveContext, thread_id: str, snapshot: dict[str, Any]
) -> None:
    core = snapshot.get("core")
    projected_status = str(core.get("status") or "") if isinstance(core, dict) else ""
    if projected_status != "cancelled" and str(snapshot.get("status") or "") != "cancelled":
        return
    store = context.runtime_state_store
    if store is None:
        return

    def _mark_cancelled(state: Any) -> None:
        if state.status == "cancelled":
            return
        state.status = "cancelled"
        state.loop_state = "failed"
        state.metadata.pop("pending_approval", None)
        state.metadata.pop("pending_waiting_request", None)

    await _save_runtime_state_with_retry(store, thread_id, mutate=_mark_cancelled)


async def recover_stale_active_turns(*, context: "CoreLiveContext") -> int:
    """Startup reaper mirroring ``ArrangeJobStore.recover_running``.

    An unexpected shutdown can leave a turn durably marked ``running`` /
    ``waiting`` / ``interrupting`` in the snapshot (the ``turn/accepted`` +
    ``running`` events commit before any terminal status is written). On
    restart the in-memory registry is empty, so the durable-snapshot guard in
    ``handle_turn_start_operation`` blocks every subsequent ``turn.start`` on
    that thread with "active turn already exists". This writes a ``cancelled``
    terminal run-item for every leftover active turn and reconciles the
    runtime state, unblocking the thread. Best-effort: never raises.
    """
    try:
        async with context.session_factory() as db:
            thread_ids = await context.persistence.list_thread_ids(db)
    except BaseException:
        _logger.exception("[live:recover] failed to enumerate threads")
        return 0

    recovered = 0
    for thread_id in thread_ids:
        async def write(db: AsyncSession, *, thread_id: str = thread_id) -> list[tuple[str, AppEventEnvelope]]:
            events: list[tuple[str, AppEventEnvelope]] = []
            seen: set[str] = set()
            while True:
                snapshot = await context.persistence.load(db, thread_id)
                active = latest_active_turn_id(snapshot)
                if not active or active in seen:
                    break
                seen.add(active)
                # Close out any dangling non-terminal items (e.g. a half-baked
                # tool_call whose arguments never finished streaming) BEFORE
                # writing the turn-level terminal event. The snapshot reducer's
                # turn-terminal lock would otherwise force-override item status
                # on later events, but the event log would still hold orphaned
                # ``running`` events — appending per-item cancelled tool_result
                # events here makes replay self-consistent.
                dangling = _collect_non_terminal_turn_item_ids(snapshot, active)
                for item_id in dangling:
                    tool_event = await _append_run_item(
                        db,
                        context=context,
                        event=_build_interrupted_tool_event(
                            thread_id=thread_id,
                            turn_id=active,
                            item_id=item_id,
                        ),
                    )
                    events.append((active, tool_event))
                    if len(events) > 50:  # guard against a runaway loop
                        break
                if len(events) > 50:
                    break
                event = await _append_run_item(
                    db,
                    context=context,
                    event=RunItemEvent(
                        kind="status",
                        thread_id=thread_id,
                        event_id=f"{active}:recovered",
                        run_id=active,
                        turn_id=active,
                        item_id=f"{active}:recovered",
                        status="cancelled",
                        payload={
                            "type": "turn",
                            "status": "cancelled",
                            "raw_end_reason": "unexpected_shutdown",
                            "message": "Recovered after unexpected shutdown",
                        },
                    ),
                )
                events.append((active, event))
                if len(events) > 50:  # guard against a runaway loop
                    break
            return events

        try:
            items = await context.persistence.write(write)
        except BaseException:
            _logger.exception("[live:recover] failed thread_id=%s", thread_id)
            continue
        for turn_id, event in items:
            try:
                await _persist_cancelled_runtime_state(
                    context=context, thread_id=thread_id, turn_id=turn_id
                )
            except BaseException:
                _logger.exception(
                    "[live:recover] runtime-state reconcile failed thread_id=%s turn_id=%s",
                    thread_id, turn_id,
                )
            try:
                await context.hub.publish(event)
            except BaseException:
                pass
        recovered += len(items)
    if recovered:
        _logger.info(
            "[live:recover] recovered %d stale active turn(s) after unexpected shutdown",
            recovered,
        )
    return recovered


def _turn_is_terminal(snapshot: dict[str, Any], turn_id: str) -> bool:
    core = snapshot.get("core")
    core_turns = core.get("turns") if isinstance(core, dict) else None
    core_turn = core_turns.get(turn_id) if isinstance(core_turns, dict) else None
    if isinstance(core_turn, dict) and str(core_turn.get("status") or "") in TERMINAL_TURN_STATUSES:
        return True
    turns = snapshot.get("turns")
    turn = turns.get(turn_id) if isinstance(turns, dict) else None
    return isinstance(turn, dict) and str(turn.get("status") or "") in TERMINAL_TURN_STATUSES


def _latest_turn_id_any_status(snapshot: dict[str, Any]) -> str:
    """Return the most recently created turn id, regardless of status.

    Unlike ``latest_active_turn_id`` this ignores the active-status guard —
    ``turn.force_reset`` must reach a turn even after recovery has marked it
    ``cancelled`` (the exact stuck-state where ``turn.cancel`` no-ops).
    """
    from .queue_state import _merged_turns  # local import to avoid cycle
    turns = _merged_turns(snapshot)
    best_id = ""
    best_seq = -1
    for turn_id, turn in turns.items():
        if not isinstance(turn, dict):
            continue
        seq = int(turn.get("last_seq") or 0)
        if seq > best_seq:
            best_seq = seq
            best_id = str(turn.get("turn_id") or turn_id)
    return best_id


async def _persist_operation_result(
    *,
    context: CoreLiveContext,
    thread_id: str,
    turn_id: str,
    result: Any,
) -> None:
    payload = dict(getattr(result, "payload", {}) or {})
    if payload.get("events_persisted_live") is True:
        return
    raw_items = payload.get("run_items")
    if not isinstance(raw_items, list):
        return
    async def write(db: AsyncSession) -> list[AppEventEnvelope]:
        run_item_list: list[RunItemEvent] = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            item = RunItemEvent.from_dict({**raw, "thread_id": raw.get("thread_id") or thread_id, "turn_id": raw.get("turn_id") or turn_id})
            run_item_list.append(item)
        if not run_item_list:
            return []
        return await context.persistence.append_batch(db, run_item_events=run_item_list)

    events = await context.persistence.write(write)
    for event in events:
        await context.hub.publish(event)


async def _live_command_catalog(
    *, context: CoreLiveContext, params: dict[str, Any]
) -> list[dict[str, Any]]:
    if isinstance(context.host.member_hooks, DefaultCoreLiveMemberHooks) and context.operations.has("command.catalog"):
        result = await context.operations.execute("command.catalog", params, metadata={"source": "core_live"})
        if result.status != "ok":
            raise ValueError(str(result.payload.get("error") or result.status))
        commands = result.payload.get("commands")
        return [dict(item) for item in commands if isinstance(item, dict)] if isinstance(commands, list) else []
    hooks = context.host.member_hooks
    work_root = params.get("work_root") or params.get("workRoot")
    commands = build_composer_command_catalog(
        core_roots=default_core_resource_roots(),
        member_roots=[Path(item) for item in hooks.command_member_roots()],
        work_root=work_root if isinstance(work_root, (str, Path)) else None,
        skill_registry=hooks.command_skill_registry(),
    )
    return [command.to_dict() for command in commands]


async def _execute_live_command_action(
    *,
    context: CoreLiveContext,
    command: str,
    thread_id: str,
    work_root: str,
    actions: dict[str, Any],
    params: dict[str, Any],
    on_event: Callable[[dict[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    if command in actions:
        return await execute_command_action(
            command=command,
            thread_id=thread_id,
            work_root=work_root,
            handlers=actions,
            on_event=on_event,
        )
    if not context.operations.has("command.execute"):
        raise ValueError(f"Command is not executable as an action: {command}")
    result = await context.operations.execute(
        "command.execute",
        {**params, "thread_id": thread_id, "command": command, "_on_event": on_event},
        metadata={"source": "core_live"},
    )
    if result.status != "ok":
        raise ValueError(str(result.payload.get("error") or result.status))
    nested = result.payload.get("result")
    return dict(nested) if isinstance(nested, dict) else dict(result.payload)


async def _execute_compact_live_command(
    *,
    context: CoreLiveContext,
    thread_id: str,
    work_root: str,
    actions: dict[str, Any],
    params: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    ids = _compact_command_ids(
        thread_id,
        client_command_id=str(params.get("client_command_id") or params.get("clientCommandId") or ""),
    )
    registry = context.host.runtime_task_registry
    if not registry.accept_run(thread_id, ids["run_id"]):
        raise RuntimeError("A context compaction is already running")
    operation_task = asyncio.create_task(_execute_claimed_compact_live_command(
        context=context,
        thread_id=thread_id,
        work_root=work_root,
        actions=actions,
        params=params,
        ids=ids,
    ))
    if not registry.register(thread_id, operation_task, run_id=ids["run_id"]):
        operation_task.cancel()
        try:
            await operation_task
        except asyncio.CancelledError:
            pass
        registry.release_run(thread_id, run_id=ids["run_id"])
        raise RuntimeError("A context compaction is already running")
    try:
        return await operation_task
    finally:
        registry.release_run(thread_id, run_id=ids["run_id"])


async def _execute_claimed_compact_live_command(
    *,
    context: CoreLiveContext,
    thread_id: str,
    work_root: str,
    actions: dict[str, Any],
    params: dict[str, Any],
    ids: dict[str, str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    _, snapshot = await _persist_command_run_item(
        context=context,
        event=_compact_command_event(thread_id, {}, ids=ids, status="running"),
    )

    terminal_emitted = False
    latest_snapshot = snapshot
    persisted_content_length = 0

    async def on_event(payload: dict[str, Any]) -> None:
        nonlocal terminal_emitted, latest_snapshot, persisted_content_length
        business_status = str(payload.get("status") or "running")
        cancelled = business_status == "cancelled" or str(payload.get("reason") or "") == "cancelled"
        event_status = (
            "cancelled"
            if cancelled
            else "failed"
            if business_status in {"failed", "error"}
            else "completed"
            if business_status in {"compacted", "not_needed"}
            else "running"
        )
        delta = str(payload.get("delta") or "")
        content = str(payload.get("content") or "")
        if event_status == "running" and delta:
            await _publish_transient_compaction_delta(
                context=context,
                thread_id=thread_id,
                ids=ids,
                payload=payload,
            )
            if len(content) - persisted_content_length < 64:
                return
            payload = {key: value for key, value in payload.items() if key != "delta"}
            persisted_content_length = len(content)
        _, latest_snapshot = await _persist_command_run_item(
            context=context,
            event=_compact_command_event(
                thread_id,
                payload,
                ids=ids,
                status=event_status,
            ),
        )
        if event_status in {"completed", "failed", "cancelled"} and not terminal_emitted:
            _, latest_snapshot = await _persist_command_run_item(
                context=context,
                event=_compact_command_terminal_event(
                    thread_id,
                    ids=ids,
                    status=event_status,
                    error=str(payload.get("error") or payload.get("message") or ""),
                ),
            )
            terminal_emitted = True

    try:
        result = await _execute_live_command_action(
            context=context,
            command="compact",
            thread_id=thread_id,
            work_root=work_root,
            actions=actions,
            params=params,
            on_event=on_event,
        )
    except asyncio.CancelledError:
        cancelled_result = {
            "status": "cancelled",
            "reason": "cancelled",
            "message": "上下文压缩已取消",
        }
        if not terminal_emitted:
            await on_event(cancelled_result)
        return cancelled_result, latest_snapshot
    except BaseException as exc:
        await _persist_command_run_item(
            context=context,
            event=_compact_command_event(
                thread_id,
                {"error": str(exc)},
                ids=ids,
                status="failed",
            ),
        )
        await _persist_command_run_item(
            context=context,
            event=_compact_command_terminal_event(
                thread_id, ids=ids, status="failed", error=str(exc)
            ),
        )
        raise
    if terminal_emitted:
        return result, latest_snapshot
    _, snapshot = await _persist_command_run_item(
        context=context,
        event=_compact_command_event(thread_id, result, ids=ids, status="completed"),
    )
    _, snapshot = await _persist_command_run_item(
        context=context,
        event=_compact_command_terminal_event(thread_id, ids=ids, status="completed"),
    )
    return result, snapshot


async def _publish_transient_compaction_delta(
    *,
    context: CoreLiveContext,
    thread_id: str,
    ids: dict[str, str],
    payload: dict[str, Any],
) -> None:
    event = _compact_command_event(thread_id, payload, ids=ids, status="running")
    await context.hub.publish(AppEventEnvelope(
        event_id=event.event_id,
        protocol_version="core.app_server.v1",
        seq=0,
        thread_id=thread_id,
        method=CORE_RUN_ITEM_METHOD,
        payload=event.to_dict(),
        created_at=datetime.now(timezone.utc),
        turn_id=event.turn_id or None,
        item_id=event.item_id or None,
        parent_item_id=event.parent_item_id or None,
        client_message_id=None,
    ))


async def _persist_command_run_item(
    *, context: CoreLiveContext, event: RunItemEvent
) -> tuple[AppEventEnvelope, dict[str, Any]]:
    async def write(db: AsyncSession):
        envelope = await _append_run_item(db, context=context, event=event)
        return envelope, await context.persistence.load(db, event.thread_id)

    envelope, snapshot = await context.persistence.write(write)
    await context.hub.publish(envelope)
    return envelope, snapshot


def _compact_command_ids(thread_id: str, *, client_command_id: str = "") -> dict[str, str]:
    suffix = client_command_id.strip()
    if not suffix or len(suffix) > 64 or not suffix.isalnum():
        suffix = uuid.uuid4().hex[:12]
    run_id = f"{thread_id}:command:compact:{suffix}"
    return {"run_id": run_id, "turn_id": run_id, "item_id": f"{run_id}:summary"}


def _compact_command_event(
    thread_id: str,
    result: dict[str, Any],
    *,
    ids: dict[str, str],
    status: str,
) -> RunItemEvent:
    content = str(result.get("content") or result.get("summary") or result.get("error") or "")
    cancelled = status == "cancelled" or str(result.get("reason") or "") == "cancelled"
    business_status = "cancelled" if cancelled else str(result.get("status") or status)
    default_label = (
        "正在压缩上下文"
        if status == "running"
        else "压缩已取消"
        if cancelled
        else "压缩未完成"
        if status == "failed"
        else "上下文已压缩"
    )
    payload: dict[str, Any] = {
        "type": "compaction",
        "label": "压缩已取消" if cancelled else str(result.get("label") or default_label),
        "trigger": "manual",
        "compaction_status": business_status,
    }
    if content:
        payload["content"] = content
    if result.get("delta"):
        payload["delta"] = str(result["delta"])
    if result.get("error"):
        payload["error"] = str(result["error"])
    for key in (
        "compacted_messages",
        "retained_messages",
        "before_tokens",
        "after_tokens",
        "limit_tokens",
        "phase",
        "segment",
        "segments",
        "reason",
        "message",
    ):
        if result.get(key) is not None:
            payload[key] = result[key]
    return RunItemEvent(
        kind="message",
        thread_id=thread_id,
        event_id=f"compact:{status}:{uuid.uuid4().hex[:16]}",
        run_id=ids["run_id"],
        turn_id=ids["turn_id"],
        item_id=ids["item_id"],
        status=status,
        payload=payload,
        source="command.execute",
        metadata={"command": "compact"},
    )


def _compact_command_terminal_event(
    thread_id: str,
    *,
    ids: dict[str, str],
    status: str,
    error: str = "",
) -> RunItemEvent:
    return RunItemEvent(
        kind="status",
        thread_id=thread_id,
        event_id=f"compact:{status}-status:{uuid.uuid4().hex[:16]}",
        run_id=ids["run_id"],
        turn_id=ids["turn_id"],
        status=status,
        payload={
            "type": "turn",
            "status": status,
            "raw_end_reason": "command_failed" if status == "failed" else status,
            "message": error,
        },
        source="command.execute",
        metadata={"command": "compact"},
    )


def _is_active_turn(snapshot: dict[str, Any], turn_id: str) -> bool:
    core = snapshot.get("core")
    turns = core.get("turns") if isinstance(core, dict) else snapshot.get("turns")
    turn = turns.get(turn_id) if isinstance(turns, dict) else None
    return isinstance(turn, dict) and str(turn.get("status") or "") in {"running", "waiting", "interrupting"}


def _thread_id_from_params(params: dict[str, Any]) -> str:
    return str(params.get("thread_id") or params.get("threadId") or params.get("session_id") or "").strip()


def _int_param(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


_CORE_LIVE_OPERATION_EXECUTORS = {
    "thread.start": handle_thread_start_operation,
    "thread.read": handle_thread_read_operation,
    "thread.resume": handle_thread_resume_operation,
    "turn.start": handle_turn_start_operation,
    "turn.cancel": handle_turn_cancel_operation,
    "turn.force_reset": handle_turn_force_reset_operation,
    "turn.steer": handle_turn_steer_operation,
    "approval.respond": handle_approval_respond_operation,
    "command.catalog": handle_command_catalog_operation,
    "command.execute": handle_command_execute_operation,
    "attachment.list": handle_attachment_list_operation,
    "attachment.get": handle_attachment_get_operation,
    "attachment.preview": handle_attachment_preview_operation,
    "attachment.open": handle_attachment_open_operation,
    "queue.create": handle_queue_create_operation,
    "queue.update": handle_queue_update_operation,
    "queue.delete": handle_queue_delete_operation,
    "queue.guide": handle_queue_guidance_operation,
}


__all__ = [
    "CoreLiveContext",
    "CoreLiveOperationHost",
    "CoreLiveOperationOutcome",
    "handle_queue_create_operation",
    "handle_queue_delete_operation",
    "handle_queue_guidance_operation",
    "handle_queue_update_operation",
    "handle_approval_respond_operation",
    "handle_thread_read_operation",
    "handle_thread_start_operation",
    "handle_thread_resume_operation",
    "handle_turn_cancel_operation",
    "handle_turn_force_reset_operation",
    "handle_turn_start_operation",
    "handle_turn_steer_operation",
]
