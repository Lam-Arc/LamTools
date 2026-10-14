from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import logging
import os
import sys
import time as time_module
import uuid
from collections.abc import Callable, Coroutine, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)

from sqlalchemy.ext.asyncio import AsyncSession

from lamtools_core.event import RunItemEvent
from lamtools_core.snapshot import is_sub_agent_child_item
from lamtools_core.attachment import AttachmentService
from lamtools_core.composer_commands import (
    build_composer_command_catalog,
    default_core_resource_roots,
    normalize_command_name,
)
from lamtools_core.runtime import (
    RuntimeStateConflictError,
    RuntimeStateStore,
    default_runtime_task_registry,
    normalize_run_id,
)
from lamtools_core.runtime.background_processes import (
    default_background_process_registry,
    status_to_dict,
)
from lamtools_core.runtime.memory_guard import (
    HOST_MEMORY_EXHAUSTED,
    ensure_pending_memory_resume,
    memory_exhausted_message_for,
    state_is_memory_exhaustion,
)
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
from .persistence_host import AppPersistenceHost, RevisionConflictError
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
from .session_actor import SessionActorBusyError, SessionActorRegistry
from .sync_store import SYNC_CURSOR_EXPIRED
from .session_autotitle import generate_session_title, is_default_title
from .thread_outline import build_thread_outline, normalize_thread_outline_char_limit
from .turn_acceptance import (
    QUEUE_ITEM_ACCEPTED_METHODS,
    TURN_ACCEPTED_METHODS,
    CoreAppEventSpec,
    build_cancelled_turn_event,
    build_turn_acceptance_plan,
)
from .runtime_permissions import (
    RUNTIME_PERMISSION_KEYS,
    load_global_runtime_controls,
    normalize_permission_preset,
    normalize_permission_mode,
    permissions_from_snapshot,
    resolve_permission_preset,
    resolve_session_permissions,
    runtime_snapshot as build_runtime_snapshot,
    session_runtime_preferences,
    with_session_runtime_preferences,
)


TERMINAL_TURN_STATUSES = {"completed", "failed", "cancelled", "skipped"}
# History paging bounds.
#
# Every live paging path (thread.resume / thread.read / thread.history) routes
# through ``_character_page_snapshot``, which now budgets the page by
# *serialized bytes*. Items are selected newest-first and accumulation stops
# once the next item would cross the byte budget, so a page may end inside a
# turn — the before_item_id/before_seq cursor already addresses that, and the
# client already loops thread.history with it.
#
# One item is one tool exchange: a tool_call and its tool_result share an item id
# (see runtime_projection._tool_item_id), so an item-boundary cut can never
# strand a result without its call.
#
# ``char_limit`` and ``turn_limit`` are retained as informational / turn-count
# upper bounds only; ``MAX_THREAD_HISTORY_CHAR_LIMIT`` is still not a size guard.
# The byte budget is deliberately well under the 4 MiB single-message cap most
# clients enforce. A single item that exceeds the budget on its own (an oversized
# body that should not ride with the page) still yields one page of at least that
# item, so paging always makes progress; that separate case is not solved here.
DEFAULT_THREAD_HISTORY_CHAR_LIMIT = 200_000
MAX_THREAD_HISTORY_CHAR_LIMIT = 1_000_000
DEFAULT_THREAD_HISTORY_TURN_LIMIT = 10
MAX_THREAD_HISTORY_TURN_LIMIT = 100
DEFAULT_THREAD_HISTORY_PAGE_BYTES = 2 * 1024 * 1024
MAX_THREAD_HISTORY_PAGE_BYTES = 3 * 1024 * 1024
MIN_THREAD_HISTORY_PAGE_BYTES = 64 * 1024
# Inline artifact bodies (notably ``metadata.image_data_url`` on tool results)
# are the only thing that can push a single item past the page budget. When one
# exceeds this, the page carries a reference instead: the durable snapshot, the
# event row and the database keep the body byte for byte, and only the serialized
# page swaps it for an identifier + mime type + byte size with
# ``availability == "reference"``, resolved on demand through the existing
# artifact path/read. See the "single oversized item" design note.
MAX_INLINE_ARTIFACT_BYTES = 256 * 1024
ARTIFACT_AVAILABILITY_REFERENCE = "reference"

SERIALIZED_SESSION_OPERATIONS = frozenset({
    "thread.start",
    "turn.start",
    "turn.resume",
    "turn.pause",
    "turn.cancel",
    "turn.terminate",
    "turn.force_reset",
    "turn.steer",
    "approval.respond",
    "queue.create",
    "queue.update",
    "queue.delete",
    "queue.guide",
    "command.execute",
})


class SessionBusyError(RuntimeError):
    """A live operation cannot start because its session is already busy."""

    def __init__(
        self,
        *,
        reason: str,
        message: str = "session is busy",
        active_run_id: str = "",
    ) -> None:
        self.reason = str(reason or "active_operation_exists")
        self.active_run_id = str(active_run_id or "")
        super().__init__(message)

    @property
    def data(self) -> dict[str, str]:
        payload = {
            "code": "SESSION_BUSY",
            "reason": self.reason,
        }
        if self.active_run_id:
            payload["active_run_id"] = self.active_run_id
        return payload




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
    catalog = {
        normalize_command_name(item.get("name")): item
        for item in await _live_command_catalog(context=context, params=params)
        if isinstance(item, dict) and normalize_command_name(item.get("name"))
    }
    definition = catalog.get(command)
    # Allow commands registered as actions even if the catalog (which may
    # go through operations) doesn't list them — e.g. "compact" registered
    # via member_hooks.command_action_handlers() or command.execute operation.
    if definition is None and command not in actions and not context.operations.has("command.execute"):
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message=f"Command not available: {command}")
        )
    if definition is not None and _command_kind(definition) != "action":
        return CoreLiveOperationOutcome(
            response=rpc_error(
                request_id,
                code=INVALID_REQUEST,
                message=f"Command is not executable as an action: {command}",
            )
        )
    arguments = _command_arguments(params)
    if definition is not None and arguments and not bool(definition.get("accepts_args")):
        return CoreLiveOperationOutcome(
            response=rpc_error(
                request_id,
                code=INVALID_REQUEST,
                message=f"Command does not accept arguments: {command}",
            )
        )
    try:
        expected_revision = _expected_revision(params)
    except ValueError as exc:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc))
        )
    work_root = str(params.get("work_root") or params.get("workRoot") or "")
    try:
        # The CAS check is deliberately made immediately before dispatching
        # the action.  The live host serializes ordinary commands for this
        # session, while compact uses the runtime registry because it must
        # remain cancellable by turn.cancel.
        await context.persistence.write(
            lambda db: context.persistence.assert_revision(db, thread_id, expected_revision)
        )
        if command == "compact":
            result, snapshot = await _execute_compact_live_command(
                context=context,
                thread_id=thread_id,
                work_root=work_root,
                actions=actions,
                params={**params, "arguments": arguments},
            )
        else:
            result = await _execute_live_command_action(
                context=context,
                command=command,
                thread_id=thread_id,
                work_root=work_root,
                actions=actions,
                params=params,
                arguments=arguments,
            )
            async with context.session_factory() as db:
                snapshot = await context.persistence.load(db, thread_id)
    except RevisionConflictError as exc:
        return CoreLiveOperationOutcome(
            response=rpc_error(
                request_id,
                code=INVALID_REQUEST,
                message="Revision conflict; refresh the session and retry explicitly",
                data=exc.data,
            )
        )
    except SessionBusyError as exc:
        return CoreLiveOperationOutcome(
            response=rpc_error(
                request_id,
                code=INVALID_REQUEST,
                message=str(exc),
                data=exc.data,
            )
        )
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


def _background_process_registry_of(context: CoreLiveContext):
    registry = getattr(context.host.runtime_task_registry, "background_process_registry", None)
    return registry if registry is not None else default_background_process_registry()


def _process_scope_thread_id(params: dict[str, Any]) -> str:
    return _thread_id_from_params(params)


async def _publish_process_changed(
    context: CoreLiveContext,
    thread_id: str,
    pid: int,
    action: str,
) -> None:
    envelope = AppEventEnvelope(
        event_id=f"{thread_id}:process-changed:{action}:{pid}:{uuid.uuid4().hex[:8]}",
        protocol_version="core.app_server.v1",
        seq=0,
        thread_id=thread_id,
        method="process/changed",
        payload={"pid": pid, "action": action},
        created_at=datetime.now(timezone.utc),
    )
    await context.hub.publish(envelope)


def _invalid_pid_response(request_id: int | str | None, raw: Any):
    return CoreLiveOperationOutcome(
        response=rpc_error(request_id, code=INVALID_REQUEST, message=f"pid must be an integer, got {raw!r}")
    )


async def handle_process_list_operation(
    *, request_id: int | str | None = None, params: dict[str, Any] | None = None, context: CoreLiveContext
) -> CoreLiveOperationOutcome:
    params = params or {}
    thread_id = _process_scope_thread_id(params)
    if not thread_id:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="thread_id is required")
        )
    registry = _background_process_registry_of(context)
    statuses = registry.list_status(session_id=thread_id)
    return CoreLiveOperationOutcome(
        response=rpc_result(request_id, {"processes": [status_to_dict(status) for status in statuses]})
    )


async def handle_process_kill_operation(
    *, request_id: int | str | None = None, params: dict[str, Any] | None = None, context: CoreLiveContext
) -> CoreLiveOperationOutcome:
    params = params or {}
    thread_id = _process_scope_thread_id(params)
    if not thread_id:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="thread_id is required")
        )
    try:
        pid = int(params.get("pid"))
    except (TypeError, ValueError):
        return _invalid_pid_response(request_id, params.get("pid"))
    if pid <= 0:
        return _invalid_pid_response(request_id, params.get("pid"))
    registry = _background_process_registry_of(context)
    outcome = registry.kill(thread_id, pid)
    if outcome == "not_owned":
        return CoreLiveOperationOutcome(
            response=rpc_error(
                request_id,
                code=INVALID_REQUEST,
                message=(
                    f"Process {pid} was registered before the last backend restart; "
                    "it cannot be terminated safely."
                ),
                data={"code": "PROCESS_NOT_OWNED", "pid": pid},
            )
        )
    if outcome != "terminated":
        return CoreLiveOperationOutcome(
            response=rpc_error(
                request_id,
                code=INVALID_REQUEST,
                message=f"No registered background process with pid {pid} in this session.",
                data={"code": "PROCESS_NOT_FOUND", "pid": pid},
            )
        )
    await _publish_process_changed(context, thread_id, pid, "killed")
    return CoreLiveOperationOutcome(response=rpc_result(request_id, {"pid": pid, "terminated": True}))


async def handle_process_forget_operation(
    *, request_id: int | str | None = None, params: dict[str, Any] | None = None, context: CoreLiveContext
) -> CoreLiveOperationOutcome:
    params = params or {}
    thread_id = _process_scope_thread_id(params)
    if not thread_id:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="thread_id is required")
        )
    try:
        pid = int(params.get("pid"))
    except (TypeError, ValueError):
        return _invalid_pid_response(request_id, params.get("pid"))
    if pid <= 0:
        return _invalid_pid_response(request_id, params.get("pid"))
    registry = _background_process_registry_of(context)
    removed = registry.forget(thread_id, pid)
    if removed:
        await _publish_process_changed(context, thread_id, pid, "forgotten")
    return CoreLiveOperationOutcome(response=rpc_result(request_id, {"pid": pid, "removed": removed}))


async def handle_process_log_operation(
    *, request_id: int | str | None = None, params: dict[str, Any] | None = None, context: CoreLiveContext
) -> CoreLiveOperationOutcome:
    params = params or {}
    thread_id = _process_scope_thread_id(params)
    if not thread_id:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="thread_id is required")
        )
    try:
        pid = int(params.get("pid"))
    except (TypeError, ValueError):
        return _invalid_pid_response(request_id, params.get("pid"))
    if pid <= 0:
        return _invalid_pid_response(request_id, params.get("pid"))
    stream = str(params.get("stream") or "stdout").strip().lower()
    if stream in {"out", "stdout", ""}:
        stream = "stdout"
    elif stream in {"err", "stderr"}:
        stream = "stderr"
    else:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="stream must be 'stdout' or 'stderr'")
        )
    try:
        max_bytes = int(params.get("max_bytes") or 8192)
    except (TypeError, ValueError):
        max_bytes = 8192
    max_bytes = max(256, min(max_bytes, 262144))
    registry = _background_process_registry_of(context)
    status = next(
        (item for item in registry.list_status(session_id=thread_id) if item.record.pid == pid),
        None,
    )
    if status is None:
        return CoreLiveOperationOutcome(
            response=rpc_error(
                request_id,
                code=INVALID_REQUEST,
                message=f"No registered background process with pid {pid} in this session.",
                data={"code": "PROCESS_NOT_FOUND", "pid": pid},
            )
        )
    path_text = status.record.stdout_log if stream == "stdout" else status.record.stderr_log
    path = Path(path_text) if path_text else None
    if path is None or not path.is_file():
        return CoreLiveOperationOutcome(
            response=rpc_result(request_id, {
                "pid": pid,
                "stream": stream,
                "path": path_text,
                "content": "",
                "truncated": False,
                "missing": True,
            })
        )
    size = path.stat().st_size
    truncated = size > max_bytes
    with path.open("rb") as handle:
        if truncated:
            handle.seek(-max_bytes, os.SEEK_END)
        content = handle.read(max_bytes).decode("utf-8", errors="replace")
    if truncated:
        newline = content.find("\n")
        if 0 <= newline < len(content) - 1:
            content = content[newline + 1:]
    return CoreLiveOperationOutcome(
        response=rpc_result(request_id, {
            "pid": pid,
            "stream": stream,
            "path": str(path),
            "content": content,
            "truncated": truncated,
            "missing": False,
        })
    )


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
    # Global journal used by Local-First mobile clients. It is optional so the
    # operation host remains usable in focused unit tests.
    sync_journal: Any = None
    # Shared by every live connection created for this host.  The registry
    # serializes only short state mutations; it never owns the long-running
    # Agent task, which continues through RuntimeTaskRegistry.
    session_actors: SessionActorRegistry = field(default_factory=SessionActorRegistry)
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

        async def invoke() -> CoreLiveOperationOutcome:
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

        try:
            actor_key = _serialized_actor_key(name, params)
            if actor_key:
                if name == "turn.start":
                    # 会话已有活跃回合时，答案不会随等待改变（回合结束前一直活跃），
                    # 而排队在 session actor / 写协调器后面会先等数秒再回 busy（实测
                    # 1.6s / 13.1s / 26.5s）。注册表里的 run 认领就是排他依据，所以在
                    # 进入串行化之前先短路：SESSION_BUSY 立即可答。排他性不变——若注册
                    # 表没有认领，仍旧走原来的 actor + 写内判定（含 client_message_id
                    # 去重）。带同一 client_message_id 的重试先做索引回执查询，
                    # 已接受的提交返回原回执；其他请求仍立即 SESSION_BUSY。
                    active_run_id = self.runtime_task_registry.active_run_id(
                        _thread_id_from_params(params)
                    )
                    if active_run_id:
                        client_id = str(params.get("client_message_id") or params.get("clientMessageId") or "")
                        if client_id:
                            async with context.session_factory() as db:
                                accepted = await context.persistence.find_client_event(
                                    db, thread_id=_thread_id_from_params(params),
                                    client_message_id=client_id, methods=TURN_ACCEPTED_METHODS,
                                )
                            if accepted is not None:
                                return CoreLiveOperationOutcome(response=rpc_result(
                                    request_id, {"events": [accepted.to_dict()]},
                                ))
                        return CoreLiveOperationOutcome(
                            response=rpc_error(
                                request_id,
                                code=INVALID_REQUEST,
                                message="session has an active turn",
                                data={
                                    "code": "SESSION_BUSY",
                                    "reason": "active_turn_exists",
                                    "active_run_id": active_run_id,
                                },
                            )
                        )
                # Ordinary composer commands are short state mutations. Do
                # not queue a second request behind one that may be waiting
                # on an external command; report the conflict immediately.
                if name == "command.execute":
                    return await self.session_actors.try_run(actor_key, invoke)
                return await self.session_actors.run(actor_key, invoke)
            return await invoke()
        except SessionActorBusyError:
            return CoreLiveOperationOutcome(
                response=rpc_error(
                    request_id,
                    code=INVALID_REQUEST,
                    message="session has an active operation",
                    data={
                        "code": "SESSION_BUSY",
                        "reason": "active_operation_exists",
                    },
                )
            )
        except RevisionConflictError as exc:
            return CoreLiveOperationOutcome(
                response=rpc_error(
                    request_id,
                    code=INVALID_REQUEST,
                    message="Revision conflict; refresh the session and retry explicitly",
                    data=exc.data,
                )
            )

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
    session_actors: SessionActorRegistry = field(default_factory=SessionActorRegistry)
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
            object.__setattr__(
                self,
                "session_actors",
                getattr(self.host, "session_actors", self.session_actors),
            )
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
                session_actors=self.session_actors,
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
    host = getattr(context, "host", None)
    session_store = getattr(host, "session_store", None)
    if session_store is not None and await session_store.get(thread_id) is None:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="thread not found")
        )
    include_snapshot = params.get("include_snapshot") is not False
    full_journal = params.get("full_journal") is True
    page_limit = max(1, min(_int_param(params.get("limit"), default=500), 500))
    before_item_id, before_seq = _history_cursor(params)
    async with context.session_factory() as db:
        # The snapshot is the durable authority for everything up to its
        # snapshot_seq.  Journal paging therefore starts after that seq unless
        # the client opts out of the snapshot or explicitly asks for the raw
        # journal (replay-style clients that rebuild state from events).
        # Re-delivering events the snapshot already covers made every session
        # switch fetch and serialize up to 500 stale events (~8.5MB on long
        # threads) that snapshot-hydrating clients immediately discard.
        snapshot = await _load_thread_page(
            context=context,
            db=db,
            thread_id=thread_id,
            params=params,
            page_bytes=_history_byte_budget(params),
        )
        journal_after_seq = after_seq
        if include_snapshot and not full_journal:
            projected_seq = _int_param(
                snapshot.get("snapshot_seq") if isinstance(snapshot, dict) else None,
                default=0,
            )
            journal_after_seq = max(after_seq, projected_seq)
        events = await context.persistence.list_after(
            db, thread_id=thread_id, after_seq=journal_after_seq, limit=page_limit
        )
    await _reconcile_cancelled_runtime_state(context=context, thread_id=thread_id, snapshot=snapshot)
    last_event_seq = max((event.seq for event in events), default=journal_after_seq)
    snapshot_seq = _int_param(snapshot.get("snapshot_seq") if isinstance(snapshot, dict) else None, default=last_event_seq)
    if include_snapshot and not full_journal:
        # Projection writes share the event's transaction, so the journal tail
        # past the snapshot is normally empty.  A full page is the only honest
        # "more may exist" signal that does not depend on that invariant.
        has_more = bool(events) and len(events) >= page_limit
    else:
        has_more = bool(events) and last_event_seq < snapshot_seq
    result: dict[str, Any] = {
        "thread": {"id": thread_id},
        "events": [event.to_dict() for event in events],
        "has_more": has_more,
        "next_after_seq": last_event_seq,
    }
    if include_snapshot:
        result["snapshot"] = _character_page_snapshot(
            snapshot,
            before_item_id=before_item_id,
            before_seq=before_seq,
            char_limit=_history_char_limit(params),
            turn_limit=_history_turn_limit(params),
            byte_limit=_history_byte_budget(params),
        )
    return CoreLiveOperationOutcome(
        response=rpc_result(request_id, result)
    )


async def handle_sync_start_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    context: "CoreLiveContext",
) -> "CoreLiveOperationOutcome":
    """Return one atomic Local-First snapshot or a bounded journal delta."""
    journal = getattr(getattr(context, "host", None), "sync_journal", None)
    if journal is None:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="sync journal is unavailable")
        )
    raw_cursor = params.get("cursor")
    cursor: int | None
    if raw_cursor is None or raw_cursor == "":
        cursor = None
    else:
        try:
            cursor = int(raw_cursor)
        except (TypeError, ValueError):
            return CoreLiveOperationOutcome(
                response=rpc_error(request_id, code=INVALID_REQUEST, message="cursor must be an integer or null")
            )
        if cursor < 0:
            return CoreLiveOperationOutcome(
                response=rpc_error(request_id, code=INVALID_REQUEST, message="cursor must be non-negative")
            )
    result = await journal.sync(cursor=cursor, limit=int(params.get("limit") or 500))
    # Cursor expiry is a protocol result, rather than a transport failure. It
    # lets the mobile client atomically replace its local database with the
    # next snapshot and keeps the long-lived tunnel alive.
    return CoreLiveOperationOutcome(response=rpc_result(request_id, result))


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
    session_store = getattr(getattr(context, "host", None), "session_store", None)
    if session_store is not None and await session_store.get(thread_id) is None:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="thread not found")
        )
    before_item_id, before_seq = _history_cursor(params)
    async with context.session_factory() as db:
        snapshot = await _load_thread_page(
            context=context,
            db=db,
            thread_id=thread_id,
            params=params,
            page_bytes=_history_byte_budget(params),
        )
        events = []
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
                "snapshot": _character_page_snapshot(
                    snapshot,
                    before_item_id=before_item_id,
                    before_seq=before_seq,
                    char_limit=_history_char_limit(params),
                    turn_limit=_history_turn_limit(params),
                    byte_limit=_history_byte_budget(params),
                ),
                **member_payload,
            },
        )
    )


async def handle_thread_history_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    context: CoreLiveContext,
) -> CoreLiveOperationOutcome:
    """Return one older complete-turn page for an already opened thread."""
    thread_id = str(params.get("thread_id") or params.get("threadId") or "").strip()
    before_item_id = str(params.get("before_item_id") or params.get("beforeItemId") or "").strip()
    before_seq = _int_param(params.get("before_seq") or params.get("beforeSeq"), default=0)
    if not thread_id or (not before_item_id and before_seq <= 0):
        return CoreLiveOperationOutcome(
            response=rpc_error(
                request_id,
                code=INVALID_REQUEST,
                message="thread_id and a history cursor are required",
            )
        )
    session_store = getattr(getattr(context, "host", None), "session_store", None)
    if session_store is not None and await session_store.get(thread_id) is None:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="thread not found")
        )
    async with context.session_factory() as db:
        snapshot = await _load_thread_page(
            context=context,
            db=db,
            thread_id=thread_id,
            params=params,
            page_bytes=_history_byte_budget(params),
        )
    return CoreLiveOperationOutcome(
        response=rpc_result(
            request_id,
            {
                "thread": {"id": thread_id},
                "snapshot_page": _character_page_snapshot(
                    snapshot,
                    before_item_id=before_item_id or None,
                    before_seq=before_seq,
                    char_limit=_history_char_limit(params),
                    turn_limit=_history_turn_limit(params),
                    byte_limit=_history_byte_budget(params),
                ),
            },
        )
    )


async def handle_thread_outline_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    context: CoreLiveContext,
) -> CoreLiveOperationOutcome:
    """Return a bounded conversation outline without exposing transcript bodies."""

    thread_id = str(params.get("thread_id") or params.get("threadId") or "").strip()
    if not thread_id:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="thread_id is required")
        )
    # Keep existence and access behavior identical to thread.history/read.  In
    # the production host the session store is the authoritative thread
    # namespace; focused operation tests may construct a host without one.
    session_store = getattr(getattr(context, "host", None), "session_store", None)
    if session_store is not None and await session_store.get(thread_id) is None:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="thread not found")
        )
    limit = normalize_thread_outline_char_limit(
        params.get("char_limit") or params.get("charLimit")
    )
    async with context.session_factory() as db:
        # The outline needs each turn's own closing assistant body, which can sit
        # arbitrarily deep inside a turn that ends with child output (measured:
        # 200 items deep on the longest development thread). A bounded read
        # cannot reproduce it, and a wrong or empty excerpt is worse than a slow
        # panel, so this one read stays complete.
        snapshot = await context.persistence.load(db, thread_id)
    outline = build_thread_outline(
        snapshot,
        thread_id=thread_id,
        char_limit=limit,
    )
    return CoreLiveOperationOutcome(response=rpc_result(request_id, outline))


def _history_char_limit(params: dict[str, Any]) -> int:
    """Clamp the requested character budget.

    Informational only on every live path: it is handed to
    ``_character_page_snapshot`` together with a ``turn_limit``, and turn-limit
    mode never splits a turn by characters.  It surfaces as
    ``history_page.char_limit`` and drives selection only in the legacy
    character-only mode that direct callers can reach by passing
    ``turn_limit=None`` (no live RPC does).  See the constants block above.
    """
    raw = params.get("char_limit") or params.get("charLimit")
    return max(1_000, min(_int_param(raw, default=DEFAULT_THREAD_HISTORY_CHAR_LIMIT), MAX_THREAD_HISTORY_CHAR_LIMIT))


def _history_turn_limit(params: dict[str, Any]) -> int:
    """Clamp the requested page size in turns (an upper bound, not the size guard)."""
    raw = params.get("turn_limit") or params.get("turnLimit")
    return max(1, min(_int_param(raw, default=DEFAULT_THREAD_HISTORY_TURN_LIMIT), MAX_THREAD_HISTORY_TURN_LIMIT))


def _history_byte_budget(params: dict[str, Any]) -> int:
    """Clamp the requested page byte budget (the real response-size guard).

    Defaults to ``DEFAULT_THREAD_HISTORY_PAGE_BYTES`` (well under the 4 MiB
    client cap) and is bounded above by ``MAX_THREAD_HISTORY_PAGE_BYTES`` so a
    caller cannot ask for a page that would defeat the guard.
    """
    raw = params.get("page_bytes") or params.get("pageBytes")
    requested = _int_param(raw, default=DEFAULT_THREAD_HISTORY_PAGE_BYTES)
    return max(MIN_THREAD_HISTORY_PAGE_BYTES, min(requested, MAX_THREAD_HISTORY_PAGE_BYTES))


def _history_cursor(params: dict[str, Any]) -> tuple[str | None, int | None]:
    """Optional before cursor shared by thread.read/resume/history.

    ``(None, None)`` means "newest page". Passing it explicitly lets the same
    continuation loop the client already runs against ``thread.history`` also
    walk the snapshot embedded in ``thread.read`` / ``thread.resume``.
    """
    before_item_id = str(params.get("before_item_id") or params.get("beforeItemId") or "").strip() or None
    raw_seq = params.get("before_seq") or params.get("beforeSeq")
    before_seq = None if raw_seq is None or raw_seq == "" else _int_param(raw_seq, default=0)
    return before_item_id, before_seq


def _mime_from_data_url(value: str) -> str:
    """Extract the media type from a ``data:<mime>;base64,...`` URL."""
    if not value.startswith("data:"):
        return ""
    header = value[5:].split(",", 1)[0]
    return header.split(";", 1)[0].strip()


def _decoded_data_url_size(value: str) -> int:
    """Approximate decoded byte size of a base64 data URL."""
    if "," not in value:
        return 0
    payload = value.split(",", 1)[1]
    padding = payload.count("=", max(0, len(payload) - 2))
    return max(0, (len(payload) * 3) // 4 - padding)


def _artifact_has_large_inline_body(artifact: Mapping[str, Any]) -> bool:
    """True when an artifact carries an inline body worth referencing out.

    Only data-URL bodies over ``MAX_INLINE_ARTIFACT_BYTES`` count; a small inline
    body is left alone so ordinary cards stay self-contained.
    """
    def _is_large(value: Any) -> bool:
        return isinstance(value, str) and value.startswith("data:") and len(value) > MAX_INLINE_ARTIFACT_BYTES

    if _is_large(artifact.get("content")):
        return True
    metadata = artifact.get("metadata")
    if isinstance(metadata, Mapping):
        return any(_is_large(value) for value in metadata.values())
    return False


def _artifact_reference(artifact: Mapping[str, Any]) -> dict[str, Any]:
    """Replace an oversized inline body with an explicit reference marker.

    The durable artifact is untouched: this returns a new dict holding the
    artifact's identity (``artifact_id``) plus, explicitly, a mime type and a
    byte size, with ``availability == "reference"`` and the bulky data URL
    dropped. The client resolves the body on demand through the existing
    artifact path/read, so nothing needs a new fetch call.
    """
    reference = dict(artifact)
    mime = str(artifact.get("mime_type") or "")
    size = artifact.get("size_bytes")
    inline_bytes = 0
    metadata = artifact.get("metadata")
    if not isinstance(size, int) and isinstance(metadata, Mapping):
        # The artifact's own file size is the most useful display size; fall back
        # to decoding the data URL only when it is absent.
        declared = metadata.get("size_bytes")
        if isinstance(declared, int):
            size = declared

    if isinstance(metadata, Mapping):
        trimmed: dict[str, Any] = {}
        for key, value in metadata.items():
            if isinstance(value, str) and value.startswith("data:"):
                inline_bytes += len(value)
                mime = mime or _mime_from_data_url(value)
                if not isinstance(size, int):
                    size = _decoded_data_url_size(value)
                continue
            trimmed[key] = value
        reference["metadata"] = trimmed

    content = artifact.get("content")
    if isinstance(content, str) and content.startswith("data:") and len(content) > MAX_INLINE_ARTIFACT_BYTES:
        inline_bytes += len(content)
        mime = mime or _mime_from_data_url(content)
        if not isinstance(size, int):
            size = _decoded_data_url_size(content)
        reference.pop("content", None)

    reference["availability"] = ARTIFACT_AVAILABILITY_REFERENCE
    if mime:
        reference["mime_type"] = mime
    if isinstance(size, int):
        reference["size_bytes"] = size
    reference["inline_bytes"] = inline_bytes
    return reference


def _reference_oversized_item_artifacts(item: dict[str, Any]) -> dict[str, Any]:
    """Return the wire view of an item: original, or a copy with bodies referenced.

    The copy is shallow and fresh (a new artifact list) so the shared snapshot
    item — and therefore the durable row — is never mutated.
    """
    artifacts = item.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        return item
    replaced: list[Any] | None = None
    for index, artifact in enumerate(artifacts):
        if isinstance(artifact, Mapping) and _artifact_has_large_inline_body(artifact):
            if replaced is None:
                replaced = list(artifacts)
            replaced[index] = _artifact_reference(artifact)
    if replaced is None:
        return item
    view = dict(item)
    view["artifacts"] = replaced
    return view


def _character_page_snapshot(
    snapshot: dict[str, Any],
    *,
    before_item_id: str | None,
    before_seq: int | None,
    char_limit: int,
    turn_limit: int | None = None,
    byte_limit: int = DEFAULT_THREAD_HISTORY_PAGE_BYTES,
) -> dict[str, Any]:
    """Keep snapshot metadata but include only one newest-first, byte-bounded page.

    Items are selected newest-first and accumulation stops once the next item
    would push the page past ``byte_limit`` serialized bytes, so a page may end
    inside a turn (the before_item_id/before_seq cursor the client already loops
    on addresses that). ``turn_limit`` is a turn-count upper bound and
    ``char_limit`` is informational only. A single item larger than
    ``byte_limit`` still yields a page containing at least that one item, so
    paging always makes progress; that oversized-body case is not solved here.
    Artifact bodies are available through artifact operations and never ride with
    conversation pages.

    The page is assembled without cloning the snapshot: every key the page
    replaces is rebuilt into a fresh container, so the input snapshot is never
    mutated, while untouched branches — including the exposed item dicts — are
    shared with the caller. The page is meant to be serialized into a response
    immediately, not stored or mutated by callers. Item sizes are measured lazily
    per item instead of serializing the whole thread up front (tens of MB on long
    sessions); bytes are measured so the budget is a real wire-size bound.
    """
    core = snapshot.get("core") if isinstance(snapshot.get("core"), dict) else {}
    raw_core_items = core.get("items") if isinstance(core.get("items"), dict) else {}
    raw_core_order = (
        core.get("item_order")
        if isinstance(core.get("item_order"), list)
        else list(raw_core_items)
    )
    raw_top_items = snapshot.get("items") if isinstance(snapshot.get("items"), dict) else {}
    raw_top_order = (
        snapshot.get("item_order")
        if isinstance(snapshot.get("item_order"), list)
        else list(raw_top_items)
    )
    turn_id_by_item: dict[str, str] = {}
    for raw_turns in (snapshot.get("turns"), core.get("turns")):
        if not isinstance(raw_turns, dict):
            continue
        for raw_turn_id, raw_turn in raw_turns.items():
            if not isinstance(raw_turn, dict):
                continue
            turn_id = str(raw_turn.get("turn_id") or raw_turn_id)
            for raw_item_id in raw_turn.get("items") or []:
                turn_id_by_item.setdefault(str(raw_item_id), turn_id)

    char_sizes: dict[str, int] = {}
    byte_sizes: dict[str, int] = {}
    wired_top: dict[str, dict[str, Any]] = {}
    wired_core: dict[str, dict[str, Any]] = {}

    def _wire(item_id: str, items: dict[str, Any], cache: dict[str, dict[str, Any]]) -> Any:
        # The wire view is the item with any oversized inline artifact body
        # swapped for a reference. Sizes and the page both use this view, so the
        # budget bounds what is actually sent while the durable item is untouched.
        item = items.get(item_id)
        if not isinstance(item, dict):
            return item
        cached = cache.get(item_id)
        if cached is None:
            cached = _reference_oversized_item_artifacts(item)
            cache[item_id] = cached
        return cached

    def _item_chars(item_id: str) -> int:
        # Mirrors the merged-timeline semantics: an item id present in both the
        # top-level and core maps contributes both serialized sizes.
        cached = char_sizes.get(item_id)
        if cached is None:
            cached = 0
            item = _wire(item_id, raw_top_items, wired_top)
            if isinstance(item, dict):
                cached += len(json.dumps(item, ensure_ascii=False, separators=(",", ":")))
            item = _wire(item_id, raw_core_items, wired_core)
            if isinstance(item, dict):
                cached += len(json.dumps(item, ensure_ascii=False, separators=(",", ":")))
            char_sizes[item_id] = cached
        return cached

    def _item_bytes(item_id: str) -> int:
        # UTF-8 byte length, not characters: the budget must bound what actually
        # goes on the wire (CJK content is 3 bytes per character).
        cached = byte_sizes.get(item_id)
        if cached is None:
            cached = 0
            item = _wire(item_id, raw_top_items, wired_top)
            if isinstance(item, dict):
                cached += len(json.dumps(item, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            item = _wire(item_id, raw_core_items, wired_core)
            if isinstance(item, dict):
                cached += len(json.dumps(item, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            byte_sizes[item_id] = cached
        return cached

    # User messages live in the top-level item map while assistant process
    # items live in ``core``. Paging only the latter made the user side of a
    # large turn unreachable: its id could never become a history cursor.
    # Build one thread-global timeline, matching the UI's seq-based merge.
    ordered_by_id: dict[str, tuple[int, int, int, str, str]] = {}
    for source_rank, (raw_order, raw_items) in enumerate(
        ((raw_top_order, raw_top_items), (raw_core_order, raw_core_items))
    ):
        for index, raw_id in enumerate(raw_order, 1):
            item_id = str(raw_id)
            item = raw_items.get(item_id)
            if not isinstance(item, dict):
                continue
            seq = _int_param(item.get("seq") or item.get("last_seq"), default=index)
            turn_id = str(item.get("turn_id") or turn_id_by_item.get(item_id) or "")
            previous = ordered_by_id.get(item_id)
            if previous is None:
                ordered_by_id[item_id] = (seq, source_rank, index, item_id, turn_id)
            else:
                ordered_by_id[item_id] = (*previous[:4], previous[4] or turn_id)
    full_order = sorted(ordered_by_id.values(), key=lambda entry: entry[:4])
    # How many items the thread actually has. A bounded read materializes only
    # the newest page of conversation rows, so the envelope must come from the
    # metadata's item orders rather than from the loaded items — otherwise a
    # thread with thousands of items would report has_more=false after the first
    # page and the older turns would become unreachable.
    total_items = len(set(raw_top_order) | set(raw_core_order) | set(ordered_by_id))

    before_index = None
    if before_item_id:
        before_index = next(
            (index for index, entry in enumerate(full_order) if entry[3] == before_item_id),
            None,
        )
    if before_index is not None:
        ordered = full_order[:before_index]
    elif before_seq is not None:
        ordered = [entry for entry in full_order if entry[0] < before_seq]
    else:
        ordered = full_order

    selected: list[tuple[int, int, int, str, str]] = []
    if turn_limit is not None:
        # Byte-budgeted selection, newest-first. Accumulation stops before the
        # next item would cross the budget, so a page may end inside a turn; the
        # cursor below is what the client already follows. ``turn_limit`` stays a
        # turn-count upper bound. At least one item is always taken so a page
        # never comes back empty (progress even when one item alone is oversized).
        selected_turns: set[str] = set()
        selected_bytes = 0
        for entry in reversed(ordered):
            turn_key = entry[4] or f"item:{entry[3]}"
            if turn_key not in selected_turns and len(selected_turns) >= turn_limit:
                continue
            item_bytes = _item_bytes(entry[3])
            if selected and selected_bytes + item_bytes > byte_limit:
                break
            selected.append(entry)
            selected_bytes += item_bytes
            selected_turns.add(turn_key)
        selected.reverse()
    else:
        character_count = 0
        for entry in reversed(ordered):
            item_chars = _item_chars(entry[3])
            if selected and character_count + item_chars > char_limit:
                break
            selected.append(entry)
            character_count += item_chars
        selected.reverse()
    selected_ids = {entry[3] for entry in selected}
    earliest_seq = min((entry[0] for entry in selected), default=None)
    # ``selected``/``ordered`` cover only the items this read materialized: a
    # bounded read returns the newest page of rows, so "is there older content"
    # is either an unselected loaded item or the store's probe for rows older
    # than the loaded prefix. ``total_items`` still reports the thread's full
    # item count from the metadata, which is what progress/paging UI reads.
    has_more = len(selected) < len(ordered) or bool(core.get("_page_has_older_items"))

    # If a page begins inside an assistant turn, retain the user inputs that
    # causally precede the visible assistant items. They are lightweight turn
    # anchors, do not affect the contiguous history cursor, and prevent an
    # assistant-only first render for a large single-turn thread.
    selected_turn_max_seq: dict[str, int] = {}
    for seq, _, _, item_id, _turn_id in selected:
        item = raw_core_items.get(item_id)
        turn_id = str(item.get("turn_id") or "") if isinstance(item, dict) else ""
        if turn_id:
            selected_turn_max_seq[turn_id] = max(selected_turn_max_seq.get(turn_id, seq), seq)
    context_user_ids: set[str] = set()
    for index, raw_id in enumerate(raw_top_order, 1):
        item_id = str(raw_id)
        item = raw_top_items.get(item_id)
        if not isinstance(item, dict) or str(item.get("type") or "") != "userMessage":
            continue
        turn_id = str(item.get("turn_id") or "")
        max_seq = selected_turn_max_seq.get(turn_id)
        seq = _int_param(item.get("seq") or item.get("last_seq"), default=index)
        if max_seq is not None and seq <= max_seq:
            context_user_ids.add(item_id)
    visible_ids = selected_ids | context_user_ids
    character_count = sum(_item_chars(entry[3]) for entry in selected) + sum(
        len(json.dumps(raw_top_items[item_id], ensure_ascii=False, separators=(",", ":")))
        for item_id in context_user_ids - selected_ids
    )

    def filtered_turns(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        result: dict[str, Any] = {}
        for turn_id, raw_turn in value.items():
            if not isinstance(raw_turn, dict):
                continue
            turn_items = [str(item_id) for item_id in raw_turn.get("items") or []]
            kept = [item_id for item_id in turn_items if item_id in visible_ids]
            if kept or str(raw_turn.get("status") or "") in ACTIVE_TURN_STATUSES:
                result[str(turn_id)] = {**raw_turn, "items": kept}
        return result

    page_core = dict(core)
    # Private store hint for the paging envelope; never part of the wire page.
    page_core.pop("_page_has_older_items", None)
    page_core["items"] = {
        item_id: _wire(item_id, raw_core_items, wired_core)
        for item_id in selected_ids
        if isinstance(raw_core_items.get(item_id), dict)
    }
    page_core["item_order"] = [
        str(item_id) for item_id in raw_core_order if str(item_id) in selected_ids
    ]
    page_core["turns"] = filtered_turns(core.get("turns"))
    page_core["artifacts"] = {}
    page_core["seen_event_ids"] = []
    page = dict(snapshot)
    page["core"] = page_core
    page["items"] = {
        item_id: _wire(item_id, raw_top_items, wired_top)
        for item_id in visible_ids
        if isinstance(raw_top_items.get(item_id), dict)
    }
    page["item_order"] = [
        str(item_id) for item_id in raw_top_order if str(item_id) in visible_ids
    ]
    page["turns"] = filtered_turns(snapshot.get("turns"))
    page["artifacts"] = {}
    page["seen_event_ids"] = []
    # Serialized bytes of the selected items, the quantity the budget bounds. The
    # page also carries a few metadata keys, so this under-reports the exact wire
    # size; the budget leaves ample headroom under the client cap for them.
    page_bytes = sum(_item_bytes(entry[3]) for entry in selected)
    page["history_page"] = {
        "char_limit": char_limit,
        "character_count": character_count,
        "byte_limit": byte_limit,
        "byte_count": page_bytes,
        "turn_limit": turn_limit,
        "turn_count": len({entry[4] or f"item:{entry[3]}" for entry in selected}),
        "item_count": len(visible_ids),
        "total_items": total_items,
        "has_more": has_more,
        "next_before_item_id": selected[0][3] if has_more and selected else None,
        "next_before_seq": earliest_seq if has_more else None,
    }
    return page


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
    try:
        expected_revision = _expected_revision(params)
    except ValueError as exc:
        return CoreLiveOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))

    async def write(db: AsyncSession):
        await context.persistence.assert_revision(db, thread_id, expected_revision)
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
    # Provenance of an automatic (non-user) turn, e.g. "member_wake". It rides the
    # acceptance and runtime payloads so the projection can mark the turn and its
    # input item, and the kernel can preserve the wake as a marked system-history
    # entry at the model boundary.
    turn_origin = str(params.get("origin") or params.get("turn_origin") or "").strip()
    input_items = params.get("input")
    if not thread_id or not isinstance(input_items, list):
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="thread_id and input are required")
        )
    try:
        _expected_revision(params)  # 形状校验；回合创建是幂等追加，见 write 说明
    except ValueError as exc:
        return CoreLiveOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))

    turn_id = str(params.get("turn_id") or params.get("turnId") or f"{thread_id}:turn:{uuid.uuid4().hex[:12]}")
    user_item_id = str(params.get("user_item_id") or params.get("userItemId") or f"{turn_id}:user")
    run_claimed = False

    # Capture the session's initial permission state in the acceptance event.
    # Running toolboxes refresh these fields from the session before each tool
    # boundary, while the remaining runtime options stay turn-scoped.
    try:
        resolved = await _resolve_turn_approval_policy(context=context, params={**params, "thread_id": thread_id})
    except ValueError as exc:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc))
        )
    # Clients and automatic continuations need not repeat the project path on
    # every message. Resolve it before composer preparation and persist the
    # same root that the tools/runtime will receive.
    if not (params.get("work_root") or params.get("workRoot")) and resolved.get("work_root"):
        params = {**params, "work_root": resolved["work_root"]}
    try:
        prepared = await context.host.member_hooks.prepare_turn_input(
            thread_id=thread_id, params=params, input_items=input_items,
        )
    except ValueError as exc:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc))
        )
    turn_runtime_snapshot = _runtime_snapshot_with_turn_options(
        resolved["runtime_snapshot"],
        params=params,
        active_mode=resolved.get("active_mode"),
    )


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
            return ("existing", existing, None, None, None, False)

        _w2 = time_module.perf_counter()
        # 回合创建是幂等追加（client_message_id 去重）：它只追加 turn/accepted、
        # user item 与 running 状态，不读改写任何共享字段，真正的并发保护是下面的
        # 活跃回合判定（注册表 + 元数据行）。因此这里不做修订号 CAS：活跃回合持续
        # 追加事件会把会话修订号一路推高，而本写又要排队数秒才执行，客户端在发起
        # RPC 前读到的修订号几乎必然落后，CAS 会把一条合法的新回合打成
        # REVISION_CONFLICT，还盖住了本该返回的 SESSION_BUSY（2026-10-12）。
        # 只需要轮次状态与顶层用户条目顺序（活跃轮判定 + 首条消息判定），
        # 全部存放在元数据行——这里曾装配整个会话的条目表，大会话上阻塞写锁秒级。
        snapshot = await context.persistence.load_metadata(db, thread_id)
        _w3 = time_module.perf_counter()
        _logger.info("[PERF:turn_start:write] load_metadata=%.3fs", _w3 - _w2)
        active_run_id = latest_active_turn_id(snapshot) or context.host.runtime_task_registry.active_run_id(thread_id)
        if active_run_id:
            return CoreLiveOperationOutcome(
                response=rpc_error(
                    request_id,
                    code=INVALID_REQUEST,
                    message="session has an active turn",
                    data={
                        "code": "SESSION_BUSY",
                        "reason": "active_turn_exists",
                        "active_run_id": active_run_id,
                    },
                )
            )
        # A continuation of the paused turn runs through this same executor, so
        # the gate below must let its own resume pass and only refuse a *new*
        # turn started behind the paused one.
        is_continuation = str(
            params.get("origin") or params.get("turn_origin") or ""
        ).strip() == "turn_resume"
        paused_turn_id = "" if is_continuation else _paused_turn_id(snapshot)
        if paused_turn_id:
            # One session, one turn: a paused turn owns the session until the
            # user continues or terminates it. Clients turn a send into a
            # continue, so reaching here means a caller tried to start a second
            # turn behind the paused one.
            return CoreLiveOperationOutcome(
                response=rpc_error(
                    request_id,
                    code=INVALID_REQUEST,
                    message="session has a paused turn",
                    data={
                        "code": "SESSION_PAUSED",
                        "reason": "paused_turn_exists",
                        "paused_turn_id": paused_turn_id,
                    },
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
                    message="session has an active turn",
                    data={
                        "code": "SESSION_BUSY",
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
                turn_payload_extra={
                    **materialized.turn_payload_extra,
                    "runtime_snapshot": turn_runtime_snapshot,
                    **({"origin": turn_origin} if turn_origin else {}),
                },
                user_payload_extra={
                    **materialized.user_payload_extra,
                    **(
                        # An automatic turn's input is a SYSTEM message, not the
                        # user's: the interface must not render it as their text.
                        {"origin": turn_origin, "type": "systemMessage", "role": "system"}
                        if turn_origin
                        else {}
                    ),
                },
                include_turn_status=materialized.include_turn_status,
            )
            _w4 = time_module.perf_counter()
            envelopes = await context.persistence.append_batch(
                db,
                app_events=[_app_event_input(plan.turn_accepted), _app_event_input(plan.user_item)],
                run_item_events=[plan.running_status],
            )
            _w5 = time_module.perf_counter()
            _logger.info("[PERF:turn_start:write] append_batch=%.3fs", _w5 - _w4)
            accepted, user, running = envelopes[0], envelopes[1], envelopes[2]
            # 响应快照不再在写锁内装配（曾有一次全量 load + 一次 return_state 全量
            # load）；需要快照的调用方在事务提交后于锁外装配。
            return ("applied", accepted, user, running, materialized, is_first_message)
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
    include_snapshot = _include_snapshot_param(params)
    response_snapshot: dict[str, Any] | None = None
    outcome_kind, accepted, user, running, materialized, is_first_message = write_result
    if include_snapshot:
        response_snapshot = await _load_snapshot_outside_write_lock(context, thread_id)
    if outcome_kind == "existing":
        response_payload: dict[str, Any] = {"events": [accepted.to_dict()]}
        if response_snapshot is not None:
            response_payload["snapshot"] = response_snapshot
        return CoreLiveOperationOutcome(
            response=rpc_result(request_id, response_payload),
            notify_events=[accepted],
        )

    # Best-effort: generate a short title from the first user message.
    if is_first_message and context.host.llm_client and prepared.runtime_text:
        loop = _get_running_loop()
        loop.create_task(_auto_title_session(
            context=context,
            thread_id=thread_id,
            first_message=prepared.runtime_text,
            model_id=str(params.get("model_id") or params.get("modelId") or "").strip(),
        ))

    imagegen_config = await _resolve_imagegen_config(context=context)
    runtime_start = {
        "thread_id": thread_id,
        "turn_id": turn_id,
        "user_message_id": user_item_id,
        "text": prepared.runtime_text,
        "input": prepared.runtime_input,
        "work_root": prepared.work_root,
        "approval_policy": turn_runtime_snapshot["approval_policy"],
        "active_tier": turn_runtime_snapshot["active_tier"],
        "tier_tools": resolved["tier_tools"],
        "active_mode": resolved["active_mode"],
        "instructions": str(params.get("instructions") or ""),
        "request_local_late_context": str(params.get("request_local_late_context") or ""),
        "allow_access_outside_workdir": turn_runtime_snapshot["allow_access_outside_workdir"],
        "permission_preset": turn_runtime_snapshot["permission_preset"],
        "runtime_snapshot": turn_runtime_snapshot,
        "imagegen_config": imagegen_config,
        "model_id": str(params.get("model_id") or params.get("modelId") or ""),
        "reasoning_level": str(params.get("reasoning_level") or params.get("reasoningLevel") or ""),
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
        **({"origin": turn_origin} if turn_origin else {}),
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
        failure_event, failure_snapshot = start_failure
        events.append(failure_event)
        # 失败终态快照比提交后的常规快照更新（含 failed 终态），必须覆盖。
        if include_snapshot:
            response_snapshot = failure_snapshot
    _logger.info("[PERF:turn_start] total=%.3fs thread_id=%s", _t4 - _t0, thread_id)
    _logger.info("[live:handle_turn_start] dispatched background task thread_id=%s turn_id=%s model=%s",
                  thread_id, turn_id, runtime_start.get("model_id") or "default")
    response_payload = {
        "events": [event.to_dict() for event in events],
        "runtime_start": runtime_start,
    }
    if response_snapshot is not None:
        response_payload["snapshot"] = response_snapshot
    return CoreLiveOperationOutcome(
        response=rpc_result(request_id, response_payload),
        notify_events=events,
        runtime_start=runtime_start,
    )


async def _latest_persisted_active_mode(*, context: "CoreLiveContext", thread_id: str) -> str | None:
    """Return the newest non-empty active mode persisted for this thread."""
    session_factory = getattr(context, "session_factory", None)
    persistence = getattr(context, "persistence", None)
    load_metadata = getattr(persistence, "load_metadata", None)
    if not thread_id or not callable(session_factory) or not callable(load_metadata):
        return None
    try:
        async with session_factory() as db:
            snapshot = await load_metadata(db, thread_id)
    except Exception:
        # Mode inheritance is best-effort; an unavailable snapshot must not
        # prevent an automatic continuation from starting.
        return None
    if not isinstance(snapshot, Mapping):
        return None

    # Turn acceptance stores the authoritative runtime snapshot in `turns`.
    # Older snapshots may expose only the core projection, so use it only when
    # the canonical turn map is unavailable.
    raw_turns = snapshot.get("turns")
    core = snapshot.get("core")
    core_turns = core.get("turns") if isinstance(core, Mapping) else None
    if not isinstance(raw_turns, Mapping):
        raw_turns = core_turns
    if not isinstance(raw_turns, Mapping):
        return None

    def turn_sequence(turn: Mapping[str, Any]) -> int:
        try:
            return int(turn.get("last_seq") or turn.get("seq") or 0)
        except (TypeError, ValueError):
            return 0

    ordered_turns = sorted(
        (turn for turn in raw_turns.values() if isinstance(turn, Mapping)),
        key=turn_sequence,
        reverse=True,
    )
    for turn in ordered_turns:
        runtime_snapshot = turn.get("runtime_snapshot")
        if not isinstance(runtime_snapshot, Mapping):
            continue
        active_mode = runtime_snapshot.get("active_mode")
        if isinstance(active_mode, str) and active_mode.strip():
            return active_mode.strip()
    return None


async def _resolve_turn_approval_policy(*, context: "CoreLiveContext", params: dict[str, Any]) -> dict[str, Any]:
    """Resolve approval policy, tier configuration, and loadtools mode for a turn.

    Returns dict with keys: approval_policy, active_tier, tier_tools, active_mode, load_tools
    """
    explicit = params.get("approval_policy") or params.get("approvalPolicy")
    thread_id = str(
        params.get("thread_id")
        or params.get("threadId")
        or params.get("session_id")
        or params.get("sessionId")
        or ""
    ).strip()
    active_mode = params.get("active_mode")
    if isinstance(active_mode, str) and active_mode.strip():
        active_mode = active_mode.strip()
    else:
        active_mode = None
    automatic_origin = str(params.get("origin") or params.get("turn_origin") or "").strip()
    if active_mode is None and automatic_origin:
        active_mode = await _latest_persisted_active_mode(context=context, thread_id=thread_id)
    load_tools = _load_load_tools(context)
    global_controls: dict[str, Any] = load_global_runtime_controls()
    global_value: dict[str, Any] = {}
    if context.operations.has("settings.get"):
        try:
            result = await context.operations.execute(
                "settings.get",
                {"namespace": "core.runtimeControls"},
                metadata={"source": "core_live"},
            )
            value = result.payload.get("value") if result.status == "ok" and isinstance(result.payload, dict) else None
            if isinstance(value, dict):
                global_value = dict(value)
                global_controls = {
                    **global_controls,
                    **{
                        "base_tier": normalize_permission_mode(
                            value.get("permission_mode"),
                            default=global_controls["base_tier"],
                        ),
                        "base_allow_access_outside_workdir": (
                            value.get("allow_access_outside_workdir")
                            if isinstance(value.get("allow_access_outside_workdir"), bool)
                            else global_controls["base_allow_access_outside_workdir"]
                        ),
                        "permission_preset": (
                            value.get("permission_preset")
                            if value.get("permission_preset") in {"ask", "auto", "full_access"}
                            else global_controls["permission_preset"]
                        ),
                    },
                }
        except Exception:
            global_value = {}

    session_metadata: dict[str, Any] = {}
    session_store = getattr(getattr(context, "host", None), "session_store", None)
    if thread_id and session_store is not None:
        try:
            session = session_store.get(thread_id)
            if inspect.isawaitable(session):
                session = await session
            raw_metadata = getattr(session, "metadata", None)
            if isinstance(raw_metadata, dict):
                session_metadata = dict(raw_metadata)
                if "runtime_preferences" not in session_metadata:
                    canonical = with_session_runtime_preferences(
                        session_metadata,
                        global_controls=global_value or global_controls,
                    )
                    patch = getattr(session_store, "patch", None)
                    if callable(patch):
                        patched = patch(thread_id, metadata=canonical)
                        if inspect.isawaitable(patched):
                            await patched
                    session_metadata = canonical
        except Exception:
            session_metadata = {}

    preferences = session_runtime_preferences(
        session_metadata,
        global_controls=global_value or global_controls,
    )
    # New clients submit only the preset.  Legacy callers may still provide
    # the expanded fields; those are accepted only when no new preset exists.
    raw_preset = params.get("permission_preset")
    legacy_active_tier = params.get("active_tier")
    legacy_outside = params.get("allow_access_outside_workdir")
    if raw_preset is not None:
        preset = normalize_permission_preset(raw_preset)
        base_tier = preferences["base_tier"]
        base_outside = preferences["base_allow_access_outside_workdir"]
    elif explicit is not None or legacy_active_tier is not None or isinstance(legacy_outside, bool):
        policy = "auto_approve" if explicit == "auto_approve" else "require"
        preset = "auto" if policy == "auto_approve" else "ask"
        base_tier = normalize_permission_mode(legacy_active_tier, default=preferences["base_tier"])
        base_outside = legacy_outside if isinstance(legacy_outside, bool) else preferences[
            "base_allow_access_outside_workdir"
        ]
    else:
        preset = preferences["permission_preset"]
        base_tier = preferences["base_tier"]
        base_outside = preferences["base_allow_access_outside_workdir"]

    tier_tools = _load_tier_tools(context)
    permissions = resolve_session_permissions(
        preset=preset,
        base_tier=base_tier,
        base_allow_access_outside_workdir=base_outside,
        tier_tools=tier_tools,
        global_controls=global_value or global_controls,
    )
    return {
        **permissions.to_dict(),
        "work_root": str(session_metadata.get("work_root") or ""),
        "tier_tools": permissions.tier_tools,
        "active_mode": active_mode,
        "runtime_snapshot": build_runtime_snapshot(permissions=permissions, active_mode=active_mode),
    }


def _page_item_byte_budget(page_bytes: int) -> int:
    """Read budget for one conversation page: a small multiple of its wire cap.

    The page itself is capped at ``page_bytes``, so reading a few times that is
    enough to fill it (the extra absorbs items the selector skips) while keeping
    the read bounded no matter how long the thread is.
    """
    return max(2 * 1024 * 1024, min(16 * 1024 * 1024, int(page_bytes) * 3))


async def _load_thread_page(
    *,
    context: CoreLiveContext,
    db: Any,
    thread_id: str,
    params: dict[str, Any],
    page_bytes: int,
) -> dict[str, Any]:
    """Load one conversation page instead of the whole thread.

    Every transcript read (open, read, history) serves at most one page, so
    materializing every item row first made the first screen of a long thread
    cost as much as reading all of it. Hosts without the bounded read keep the
    full assembly so the operation stays usable everywhere.
    """
    before_item_id, before_seq = _history_cursor(params)
    loader = getattr(context.persistence, "load_page", None)
    if not callable(loader):
        return await context.persistence.load(db, thread_id)
    return await loader(
        db,
        thread_id,
        before_item_id=before_item_id,
        before_seq=before_seq,
        item_byte_budget=_page_item_byte_budget(page_bytes),
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
    try:
        expected_revision = _expected_revision(params)
    except ValueError as exc:
        return CoreLiveOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))

    async def write(db: AsyncSession):
        await context.persistence.assert_revision(db, thread_id, expected_revision)
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


async def handle_turn_resume_operation(
    *, request_id: int | str | None, params: dict[str, Any], context: CoreLiveContext,
) -> CoreLiveOperationOutcome:
    """Explicit continuation of the latest interrupted turn, using committed history."""
    thread_id = _thread_id_from_params(params)
    requested = str(params.get("turn_id") or params.get("turnId") or "")
    registry = context.host.runtime_task_registry
    if not thread_id:
        return CoreLiveOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message="thread_id is required"))
    try:
        _expected_revision(params)  # append operation, same validation as turn.start
    except ValueError as exc:
        return CoreLiveOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    # Stop acknowledges before settlement. Do not race its detached writers or
    # claim release, particularly when the logical Turn ID is reused. A settling
    # task can spawn another terminal writer, so drain the thread's set fully.
    while True:
        pending = [task for task in tuple(_LIVE_BACKGROUND_TASKS)
                   if not task.done() and task.get_name().endswith(f":{thread_id}")]
        if not pending:
            break
        await asyncio.gather(*(asyncio.shield(task) for task in pending), return_exceptions=True)
    client_id = str(params.get("client_message_id") or params.get("clientMessageId") or uuid.uuid4().hex)
    resolved = await _resolve_turn_approval_policy(context=context, params={"thread_id": thread_id})
    imagegen_config = await _resolve_imagegen_config(context=context)
    # The text typed while the turn was paused. It rides the same turn as a
    # supplementary user input, which is the whole point of sending instead of
    # pressing Continue: one action, and the model sees both.
    raw_input = params.get("input")
    extra_input = [dict(item) for item in raw_input if isinstance(item, dict)] if isinstance(raw_input, list) else []
    claimed = ""

    async def write(db):
        nonlocal claimed
        existing = await context.persistence.find_client_event(
            db, thread_id=thread_id, client_message_id=client_id, methods={"turn/started"},
        )
        if existing is not None:
            return existing, None
        snapshot = await context.persistence.load_metadata(db, thread_id)
        turns = snapshot.get("turns") or {}
        latest = max(turns.values(), key=lambda turn: int(turn.get("seq") or 0), default={})
        turn_id = str(latest.get("turn_id") or "")
        if (not turn_id or (requested and requested != turn_id)
                or latest.get("status") != "paused"):
            # Only a paused turn continues. A terminated one is final on
            # purpose: the user asked for it, and re-running it silently would
            # undo that decision.
            raise ValueError("latest turn is not resumable")
        if latest_active_turn_id(snapshot) or registry.active_run_id(thread_id):
            raise ValueError("session has an active turn")
        state = await context.runtime_state_store.get(thread_id) if context.runtime_state_store else None
        from lamtools_core.runtime_owner import LIVE_RUN_STATES, owner_is_live, read_owner
        if state is not None and state.status in LIVE_RUN_STATES and owner_is_live(read_owner(state.metadata)):
            raise ValueError("previous execution is still settling")
        runtime_snapshot = deepcopy(latest.get("runtime_snapshot") or {})
        for key in RUNTIME_PERMISSION_KEYS:
            if key in resolved["runtime_snapshot"]:
                runtime_snapshot[key] = resolved["runtime_snapshot"][key]
        if not registry.accept_run(thread_id, turn_id):
            raise ValueError("session has an active turn")
        claimed = turn_id
        execution_id = uuid.uuid4().hex
        get_history = getattr(context.runtime_state_store, "get_history", None)
        history = await get_history(thread_id) if callable(get_history) else []
        original_committed = any(
            row.get("role") in {"user", "system"}
            and row.get("metadata", {}).get("turn_id") == turn_id
            and row.get("metadata", {}).get("origin") != "turn_resume"
            for row in history
        )
        from .queue_state import input_item_attachment_ids
        # Stop can win before the initial kernel input checkpoint. The accepted
        # input is already committed; use it as system continuation context then.
        original_input = (latest.get("input") or []) if not original_committed else []
        original_text = ""
        if original_input:
            prepared = await context.host.member_hooks.prepare_turn_input(
                thread_id=thread_id, params={**runtime_snapshot, "work_root": latest.get("work_root") or ""},
                input_items=original_input,
            )
            original_text = prepared.runtime_text
        extra_text = ""
        if extra_input:
            prepared_extra = await context.host.member_hooks.prepare_turn_input(
                thread_id=thread_id, params={**runtime_snapshot, "work_root": latest.get("work_root") or ""},
                input_items=extra_input,
            )
            extra_text = prepared_extra.runtime_text
        event = await context.persistence.append(db, AppEventInput(
            thread_id=thread_id, turn_id=turn_id, method="turn/started", client_message_id=client_id,
            payload={"status": "running", "resumed": True, "run_id": execution_id},
        ))
        runtime_start = {
            **runtime_snapshot, "runtime_snapshot": runtime_snapshot,
            "thread_id": thread_id, "turn_id": turn_id, "run_id": execution_id,
            # Pure continuation: the committed history already carries the task
            # and every finished step, so the resumed run adds no synthetic
            # instruction. Two inputs do ride along — what the user typed while
            # the turn was paused, and the original task text when the pause won
            # the race against the first checkpoint.
            "text": extra_text or (original_text if original_input else ""),
            "input": extra_input,
            "user_item_id": f"{turn_id}:input:{client_id}" if extra_input else "",
            "attachment_ids": input_item_attachment_ids(extra_input or original_input),
            "goal_id": runtime_snapshot.get("goal_id") or (
                state.metadata.get("goal_id", "") if state is not None
                and str(state.metadata.get("turn_id") or state.run_id) == turn_id else ""
            ),
            "origin": "turn_resume", "imagegen_config": imagegen_config, "work_root": latest.get("work_root") or resolved.get("work_root") or "",
        }
        return event, runtime_start

    try:
        event, runtime_start = await context.persistence.write(write)
    except BaseException as exc:
        if claimed:
            registry.release_run(thread_id, run_id=claimed)
        if isinstance(exc, ValueError):
            return CoreLiveOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
        raise
    # The parked turn is about to run again: clear the pause request so the
    # resumed kernel does not immediately park on the same signal.
    reset_pause = getattr(context.host.runtime_task_registry, "reset_pause_event", None)
    if callable(reset_pause):
        reset_pause(thread_id)
    await context.hub.publish(event)
    if runtime_start is None:
        return CoreLiveOperationOutcome(response=rpc_result(request_id, {
            "turn_id": event.turn_id, "events": [event.to_dict()],
        }))
    failure = await _start_runtime_task(context=context, runtime_start=runtime_start)
    # One press continues the whole session: the members a pause parked start
    # again from their own committed history. Members waiting on a question are
    # untouched, that card is still the user's to answer. Detached so the
    # response never waits on member bookkeeping.
    _spawn_live_background(
        _resume_session_members(context=context, thread_id=thread_id),
        label="resume-session-members",
        thread_id=thread_id,
    )
    events = [event] + ([failure[0]] if failure else [])
    return CoreLiveOperationOutcome(
        response=rpc_result(request_id, {"turn_id": runtime_start["turn_id"], "events": [item.to_dict() for item in events]}),
        notify_events=events, runtime_start=runtime_start,
    )


async def handle_turn_start_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    context: CoreLiveContext,
) -> CoreLiveOperationOutcome:
    thread_id = str(params.get("thread_id") or params.get("threadId") or params.get("session_id") or "").strip()
    client_message_id = str(params.get("client_message_id") or params.get("clientMessageId") or uuid.uuid4().hex)
    # Provenance of an automatic (non-user) turn, e.g. "member_wake". It rides the
    # acceptance and runtime payloads so the projection can mark the turn and its
    # input item, and the kernel can preserve the wake as a marked system-history
    # entry at the model boundary.
    turn_origin = str(params.get("origin") or params.get("turn_origin") or "").strip()
    input_items = params.get("input")
    if not thread_id or not isinstance(input_items, list):
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="thread_id and input are required")
        )
    try:
        _expected_revision(params)  # 形状校验；回合创建是幂等追加，见 write 说明
    except ValueError as exc:
        return CoreLiveOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))

    turn_id = str(params.get("turn_id") or params.get("turnId") or f"{thread_id}:turn:{uuid.uuid4().hex[:12]}")
    user_item_id = str(params.get("user_item_id") or params.get("userItemId") or f"{turn_id}:user")
    run_claimed = False

    # Capture the session's initial permission state in the acceptance event.
    # Running toolboxes refresh these fields from the session before each tool
    # boundary, while the remaining runtime options stay turn-scoped.
    try:
        resolved = await _resolve_turn_approval_policy(context=context, params={**params, "thread_id": thread_id})
    except ValueError as exc:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc))
        )
    # Clients and automatic continuations need not repeat the project path on
    # every message. Resolve it before composer preparation and persist the
    # same root that the tools/runtime will receive.
    if not (params.get("work_root") or params.get("workRoot")) and resolved.get("work_root"):
        params = {**params, "work_root": resolved["work_root"]}
    try:
        prepared = await context.host.member_hooks.prepare_turn_input(
            thread_id=thread_id, params=params, input_items=input_items,
        )
    except ValueError as exc:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc))
        )
    turn_runtime_snapshot = _runtime_snapshot_with_turn_options(
        resolved["runtime_snapshot"],
        params=params,
        active_mode=resolved.get("active_mode"),
    )


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
            return ("existing", existing, None, None, None, False)

        _w2 = time_module.perf_counter()
        # 回合创建是幂等追加（client_message_id 去重）：它只追加 turn/accepted、
        # user item 与 running 状态，不读改写任何共享字段，真正的并发保护是下面的
        # 活跃回合判定（注册表 + 元数据行）。因此这里不做修订号 CAS：活跃回合持续
        # 追加事件会把会话修订号一路推高，而本写又要排队数秒才执行，客户端在发起
        # RPC 前读到的修订号几乎必然落后，CAS 会把一条合法的新回合打成
        # REVISION_CONFLICT，还盖住了本该返回的 SESSION_BUSY（2026-10-12）。
        # 只需要轮次状态与顶层用户条目顺序（活跃轮判定 + 首条消息判定），
        # 全部存放在元数据行——这里曾装配整个会话的条目表，大会话上阻塞写锁秒级。
        snapshot = await context.persistence.load_metadata(db, thread_id)
        _w3 = time_module.perf_counter()
        _logger.info("[PERF:turn_start:write] load_metadata=%.3fs", _w3 - _w2)
        active_run_id = latest_active_turn_id(snapshot) or context.host.runtime_task_registry.active_run_id(thread_id)
        if active_run_id:
            return CoreLiveOperationOutcome(
                response=rpc_error(
                    request_id,
                    code=INVALID_REQUEST,
                    message="session has an active turn",
                    data={
                        "code": "SESSION_BUSY",
                        "reason": "active_turn_exists",
                        "active_run_id": active_run_id,
                    },
                )
            )
        # A continuation of the paused turn runs through this same executor, so
        # the gate below must let its own resume pass and only refuse a *new*
        # turn started behind the paused one.
        is_continuation = str(
            params.get("origin") or params.get("turn_origin") or ""
        ).strip() == "turn_resume"
        paused_turn_id = "" if is_continuation else _paused_turn_id(snapshot)
        if paused_turn_id:
            # One session, one turn: a paused turn owns the session until the
            # user continues or terminates it. Clients turn a send into a
            # continue, so reaching here means a caller tried to start a second
            # turn behind the paused one.
            return CoreLiveOperationOutcome(
                response=rpc_error(
                    request_id,
                    code=INVALID_REQUEST,
                    message="session has a paused turn",
                    data={
                        "code": "SESSION_PAUSED",
                        "reason": "paused_turn_exists",
                        "paused_turn_id": paused_turn_id,
                    },
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
                    message="session has an active turn",
                    data={
                        "code": "SESSION_BUSY",
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
                turn_payload_extra={
                    **materialized.turn_payload_extra,
                    "runtime_snapshot": turn_runtime_snapshot,
                    **({"origin": turn_origin} if turn_origin else {}),
                },
                user_payload_extra={
                    **materialized.user_payload_extra,
                    **(
                        # An automatic turn's input is a SYSTEM message, not the
                        # user's: the interface must not render it as their text.
                        {"origin": turn_origin, "type": "systemMessage", "role": "system"}
                        if turn_origin
                        else {}
                    ),
                },
                include_turn_status=materialized.include_turn_status,
            )
            _w4 = time_module.perf_counter()
            envelopes = await context.persistence.append_batch(
                db,
                app_events=[_app_event_input(plan.turn_accepted), _app_event_input(plan.user_item)],
                run_item_events=[plan.running_status],
            )
            _w5 = time_module.perf_counter()
            _logger.info("[PERF:turn_start:write] append_batch=%.3fs", _w5 - _w4)
            accepted, user, running = envelopes[0], envelopes[1], envelopes[2]
            # 响应快照不再在写锁内装配（曾有一次全量 load + 一次 return_state 全量
            # load）；需要快照的调用方在事务提交后于锁外装配。
            return ("applied", accepted, user, running, materialized, is_first_message)
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
    include_snapshot = _include_snapshot_param(params)
    response_snapshot: dict[str, Any] | None = None
    outcome_kind, accepted, user, running, materialized, is_first_message = write_result
    if include_snapshot:
        response_snapshot = await _load_snapshot_outside_write_lock(context, thread_id)
    if outcome_kind == "existing":
        response_payload: dict[str, Any] = {"events": [accepted.to_dict()]}
        if response_snapshot is not None:
            response_payload["snapshot"] = response_snapshot
        return CoreLiveOperationOutcome(
            response=rpc_result(request_id, response_payload),
            notify_events=[accepted],
        )

    # Best-effort: generate a short title from the first user message.
    if is_first_message and context.host.llm_client and prepared.runtime_text:
        loop = _get_running_loop()
        loop.create_task(_auto_title_session(
            context=context,
            thread_id=thread_id,
            first_message=prepared.runtime_text,
            model_id=str(params.get("model_id") or params.get("modelId") or "").strip(),
        ))

    imagegen_config = await _resolve_imagegen_config(context=context)
    runtime_start = {
        "thread_id": thread_id,
        "turn_id": turn_id,
        "user_message_id": user_item_id,
        "text": prepared.runtime_text,
        "input": prepared.runtime_input,
        "work_root": prepared.work_root,
        "approval_policy": turn_runtime_snapshot["approval_policy"],
        "active_tier": turn_runtime_snapshot["active_tier"],
        "tier_tools": resolved["tier_tools"],
        "active_mode": resolved["active_mode"],
        "instructions": str(params.get("instructions") or ""),
        "request_local_late_context": str(params.get("request_local_late_context") or ""),
        "allow_access_outside_workdir": turn_runtime_snapshot["allow_access_outside_workdir"],
        "permission_preset": turn_runtime_snapshot["permission_preset"],
        "runtime_snapshot": turn_runtime_snapshot,
        "imagegen_config": imagegen_config,
        "model_id": str(params.get("model_id") or params.get("modelId") or ""),
        "reasoning_level": str(params.get("reasoning_level") or params.get("reasoningLevel") or ""),
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
        **({"origin": turn_origin} if turn_origin else {}),
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
        failure_event, failure_snapshot = start_failure
        events.append(failure_event)
        # 失败终态快照比提交后的常规快照更新（含 failed 终态），必须覆盖。
        if include_snapshot:
            response_snapshot = failure_snapshot
    _logger.info("[PERF:turn_start] total=%.3fs thread_id=%s", _t4 - _t0, thread_id)
    _logger.info("[live:handle_turn_start] dispatched background task thread_id=%s turn_id=%s model=%s",
                  thread_id, turn_id, runtime_start.get("model_id") or "default")
    response_payload = {
        "events": [event.to_dict() for event in events],
        "runtime_start": runtime_start,
    }
    if response_snapshot is not None:
        response_payload["snapshot"] = response_snapshot
    return CoreLiveOperationOutcome(
        response=rpc_result(request_id, response_payload),
        notify_events=events,
        runtime_start=runtime_start,
    )


async def _latest_persisted_active_mode(*, context: "CoreLiveContext", thread_id: str) -> str | None:
    """Return the newest non-empty active mode persisted for this thread."""
    session_factory = getattr(context, "session_factory", None)
    persistence = getattr(context, "persistence", None)
    load_metadata = getattr(persistence, "load_metadata", None)
    if not thread_id or not callable(session_factory) or not callable(load_metadata):
        return None
    try:
        async with session_factory() as db:
            snapshot = await load_metadata(db, thread_id)
    except Exception:
        # Mode inheritance is best-effort; an unavailable snapshot must not
        # prevent an automatic continuation from starting.
        return None
    if not isinstance(snapshot, Mapping):
        return None

    # Turn acceptance stores the authoritative runtime snapshot in `turns`.
    # Older snapshots may expose only the core projection, so use it only when
    # the canonical turn map is unavailable.
    raw_turns = snapshot.get("turns")
    core = snapshot.get("core")
    core_turns = core.get("turns") if isinstance(core, Mapping) else None
    if not isinstance(raw_turns, Mapping):
        raw_turns = core_turns
    if not isinstance(raw_turns, Mapping):
        return None

    def turn_sequence(turn: Mapping[str, Any]) -> int:
        try:
            return int(turn.get("last_seq") or turn.get("seq") or 0)
        except (TypeError, ValueError):
            return 0

    ordered_turns = sorted(
        (turn for turn in raw_turns.values() if isinstance(turn, Mapping)),
        key=turn_sequence,
        reverse=True,
    )
    for turn in ordered_turns:
        runtime_snapshot = turn.get("runtime_snapshot")
        if not isinstance(runtime_snapshot, Mapping):
            continue
        active_mode = runtime_snapshot.get("active_mode")
        if isinstance(active_mode, str) and active_mode.strip():
            return active_mode.strip()
    return None


async def _resolve_turn_approval_policy(*, context: "CoreLiveContext", params: dict[str, Any]) -> dict[str, Any]:
    """Resolve approval policy, tier configuration, and loadtools mode for a turn.
    
    Returns dict with keys: approval_policy, active_tier, tier_tools, active_mode, load_tools
    """
    explicit = params.get("approval_policy") or params.get("approvalPolicy")
    thread_id = str(
        params.get("thread_id")
        or params.get("threadId")
        or params.get("session_id")
        or params.get("sessionId")
        or ""
    ).strip()
    active_mode = params.get("active_mode")
    if isinstance(active_mode, str) and active_mode.strip():
        active_mode = active_mode.strip()
    else:
        active_mode = None
    automatic_origin = str(params.get("origin") or params.get("turn_origin") or "").strip()
    if active_mode is None and automatic_origin:
        active_mode = await _latest_persisted_active_mode(context=context, thread_id=thread_id)
    load_tools = _load_load_tools(context)
    global_controls: dict[str, Any] = load_global_runtime_controls()
    global_value: dict[str, Any] = {}
    if context.operations.has("settings.get"):
        try:
            result = await context.operations.execute(
                "settings.get",
                {"namespace": "core.runtimeControls"},
                metadata={"source": "core_live"},
            )
            value = result.payload.get("value") if result.status == "ok" and isinstance(result.payload, dict) else None
            if isinstance(value, dict):
                global_value = dict(value)
                global_controls = {
                    **global_controls,
                    **{
                        "base_tier": normalize_permission_mode(
                            value.get("permission_mode"),
                            default=global_controls["base_tier"],
                        ),
                        "base_allow_access_outside_workdir": (
                            value.get("allow_access_outside_workdir")
                            if isinstance(value.get("allow_access_outside_workdir"), bool)
                            else global_controls["base_allow_access_outside_workdir"]
                        ),
                        "permission_preset": (
                            value.get("permission_preset")
                            if value.get("permission_preset") in {"ask", "auto", "full_access"}
                            else global_controls["permission_preset"]
                        ),
                    },
                }
        except Exception:
            global_value = {}

    session_metadata: dict[str, Any] = {}
    session_store = getattr(getattr(context, "host", None), "session_store", None)
    if thread_id and session_store is not None:
        try:
            session = session_store.get(thread_id)
            if inspect.isawaitable(session):
                session = await session
            raw_metadata = getattr(session, "metadata", None)
            if isinstance(raw_metadata, dict):
                session_metadata = dict(raw_metadata)
                if "runtime_preferences" not in session_metadata:
                    canonical = with_session_runtime_preferences(
                        session_metadata,
                        global_controls=global_value or global_controls,
                    )
                    patch = getattr(session_store, "patch", None)
                    if callable(patch):
                        patched = patch(thread_id, metadata=canonical)
                        if inspect.isawaitable(patched):
                            await patched
                    session_metadata = canonical
        except Exception:
            session_metadata = {}

    preferences = session_runtime_preferences(
        session_metadata,
        global_controls=global_value or global_controls,
    )
    # New clients submit only the preset.  Legacy callers may still provide
    # the expanded fields; those are accepted only when no new preset exists.
    raw_preset = params.get("permission_preset")
    legacy_active_tier = params.get("active_tier")
    legacy_outside = params.get("allow_access_outside_workdir")
    if raw_preset is not None:
        preset = normalize_permission_preset(raw_preset)
        base_tier = preferences["base_tier"]
        base_outside = preferences["base_allow_access_outside_workdir"]
    elif explicit is not None or legacy_active_tier is not None or isinstance(legacy_outside, bool):
        policy = "auto_approve" if explicit == "auto_approve" else "require"
        preset = "auto" if policy == "auto_approve" else "ask"
        base_tier = normalize_permission_mode(legacy_active_tier, default=preferences["base_tier"])
        base_outside = legacy_outside if isinstance(legacy_outside, bool) else preferences[
            "base_allow_access_outside_workdir"
        ]
    else:
        preset = preferences["permission_preset"]
        base_tier = preferences["base_tier"]
        base_outside = preferences["base_allow_access_outside_workdir"]

    tier_tools = _load_tier_tools(context)
    permissions = resolve_session_permissions(
        preset=preset,
        base_tier=base_tier,
        base_allow_access_outside_workdir=base_outside,
        tier_tools=tier_tools,
        global_controls=global_value or global_controls,
    )
    return {
        **permissions.to_dict(),
        "work_root": str(session_metadata.get("work_root") or ""),
        "tier_tools": permissions.tier_tools,
        "active_mode": active_mode,
        "runtime_snapshot": build_runtime_snapshot(permissions=permissions, active_mode=active_mode),
    }


def _runtime_snapshot_with_turn_options(
    permission_snapshot: dict[str, Any],
    *,
    params: dict[str, Any],
    active_mode: str | None,
) -> dict[str, Any]:
    """Add model/thinking options to an already-resolved permission snapshot."""
    result = dict(permission_snapshot)
    result["active_mode"] = active_mode
    scalar_keys = (
        "model_id",
        "reasoning_level",
        "thinking_enabled",
        "thinking_budget",
        "reasoning_effort",
        "shallow_thinking_enabled",
        "context_window_tokens",
        "max_tokens",
        "temperature",
        "compact_trigger_tokens",
        "compact_limit_tokens",
        "instructions",
        "request_local_late_context",
        "goal_id",
    )
    for key in scalar_keys:
        value = params.get(key)
        if value is not None and not (isinstance(value, str) and not value.strip()):
            result[key] = value
    from copy import deepcopy

    return deepcopy(result)


def _queue_runtime_snapshot(item: dict[str, Any]) -> dict[str, Any]:
    """Return the queue item's persisted runtime snapshot.

    New queue records always contain the canonical snapshot written by
    ``queue/create``.  Older records may not have one; their compatibility
    fallback is deliberately conservative. Dispatch overlays the current
    session permission fields before starting the queued turn.
    """
    raw = item.get("runtime_snapshot") if isinstance(item, dict) else None
    if isinstance(raw, dict):
        permissions = permissions_from_snapshot(raw)
        if permissions is not None:
            snapshot = build_runtime_snapshot(
                permissions=permissions,
                active_mode=(
                    str(raw.get("active_mode") or "").strip()
                    if raw.get("active_mode") is not None
                    else None
                ),
            )
            for key in (
                "model_id",
                "reasoning_level",
                "thinking_enabled",
                "thinking_budget",
                "reasoning_effort",
                "shallow_thinking_enabled",
                "context_window_tokens",
                "max_tokens",
                "temperature",
                "compact_trigger_tokens",
                "compact_limit_tokens",
                "instructions",
                "request_local_late_context",
            ):
                if key in raw and raw[key] is not None:
                    snapshot[key] = deepcopy(raw[key])
            return snapshot
    return {
        "permission_preset": "ask",
        "active_tier": None,
        "tier_tools": None,
        "approval_policy": "require",
        "allow_access_outside_workdir": False,
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


CANCEL_ESCALATION_DELAYS_SECONDS: tuple[float, ...] = (1.0, 8.0)
CANCEL_FINALIZER_TASK_WAIT_CAP_SECONDS = 60.0

_LIVE_BACKGROUND_TASKS: set[asyncio.Task[None]] = set()


def _spawn_live_background(
    coro: Coroutine[Any, Any, None],
    *,
    label: str,
    thread_id: str = "",
) -> asyncio.Task[None]:
    """Run a fire-and-forget finalizer with ownership and failure logging.

    The cancel paths never await persistence inline any more: the RPC/task
    must return immediately while bookkeeping settles in the background
    (Codex-style "ack first, settle later"). The task set keeps a strong
    reference so the loop cannot GC the work mid-flight; use
    ``wait_live_background_tasks`` in tests to drain it.
    """
    task = asyncio.create_task(coro, name=f"{label}:{thread_id}")
    _LIVE_BACKGROUND_TASKS.add(task)

    def _done(done: asyncio.Task[None]) -> None:
        _LIVE_BACKGROUND_TASKS.discard(done)
        if not done.cancelled() and done.exception() is not None:
            _logger.error(
                "[live] background task %s failed thread_id=%s: %s",
                label,
                thread_id,
                done.exception(),
            )

    task.add_done_callback(_done)
    return task


async def wait_live_background_tasks() -> None:
    """Wait for spawned background finalizers (test/introspection hook)."""
    while True:
        pending = [t for t in tuple(_LIVE_BACKGROUND_TASKS) if not t.done()]
        if not pending:
            return
        await asyncio.gather(*pending, return_exceptions=True)


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
    try:
        expected_revision = _expected_revision(params)
    except ValueError as exc:
        return CoreLiveOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    requested_turn_id = str(params.get("turn_id") or params.get("turnId") or "")
    registry = context.host.runtime_task_registry
    live_turn_id = registry.active_run_id(thread_id) or ""
    # Interrupt provider I/O before any persistence work.  Previously the
    # task was cancelled only after append_batch/load completed, which made
    # Stop appear inert for several seconds under write contention.
    preempted_live_task = False
    request_cancel = getattr(registry, "request_cancel", None)
    if (
        callable(request_cancel)
        and live_turn_id
        and (not requested_turn_id or requested_turn_id == live_turn_id)
    ):
        preempted_live_task = request_cancel(
            thread_id,
            run_id=live_turn_id,
            force=True,
        )
    # Acknowledge immediately — the durable interrupting record, the watchdog
    # escalation and the claim release all settle in the background task
    # below.  Waiting inline made Stop ride behind the turn's own terminal
    # writes: on a huge session the serialized write queue held the
    # interrupt for minutes and the UI timed out (30s transport limit) while
    # the turn was in fact being torn down.
    matched_live = bool(live_turn_id) and (
        not requested_turn_id or requested_turn_id == live_turn_id
    )
    _spawn_live_background(
        _turn_cancel_finalizer(
            context=context,
            thread_id=thread_id,
            requested_turn_id=requested_turn_id,
            expected_revision=expected_revision,
            live_turn_id=live_turn_id,
            preempted_live_task=preempted_live_task,
        ),
        label="turn-cancel-finalizer",
        thread_id=thread_id,
    )
    status = "cancelling" if matched_live else "idle"
    return CoreLiveOperationOutcome(
        response=rpc_result(request_id, {"status": status, "event": None})
    )


async def handle_turn_terminate_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    context: CoreLiveContext,
) -> CoreLiveOperationOutcome:
    """Terminate the session's live work for good (the long-press action).

    Same contract as ``turn.cancel``: the turn ends terminal (``cancelled``),
    every member is interrupted with it, and nothing is offered to continue it
    later. Named separately so the desktop's long-press confirm has an explicit
    wire method instead of overloading the pause a single click sends.
    """
    return await handle_turn_cancel_operation(
        request_id=request_id, params=params, context=context
    )


async def handle_turn_pause_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    context: CoreLiveContext,
) -> CoreLiveOperationOutcome:
    """Pause the session's live turn instead of stopping it.

    A pause keeps the turn's place: the step it cut leaves no half-written
    answer, the tools that already produced a result stay, and the durable state
    becomes ``paused`` so ``turn.resume`` continues the same turn from the
    committed history. Members are parked the same way, and a member waiting on
    a question keeps its card, that answer is still the user's to give.
    """
    thread_id = _thread_id_from_params(params)
    if not thread_id:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="thread_id is required")
        )
    try:
        _expected_revision(params)
    except ValueError as exc:
        return CoreLiveOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    reason = str(params.get("reason") or params.get("pause_reason") or "user_pause").strip() or "user_pause"
    registry = context.host.runtime_task_registry
    live_turn_id = registry.active_run_id(thread_id) or ""
    request_pause = getattr(registry, "request_pause", None)
    if callable(request_pause) and live_turn_id:
        # ``force`` aborts a tool that never checks the pause event; the kernel
        # tells that teardown apart from a cancel and still parks the turn.
        request_pause(thread_id, run_id=live_turn_id, force=True, reason=reason)
    elif callable(getattr(registry, "get_pause_event", None)):
        # No live task: members may still be working, and a pause must stop them
        # too. Setting the event covers the kernels that pick it up later.
        registry.get_pause_event(thread_id).set()
    _mark_pause_reason(context=context, thread_id=thread_id, reason=reason)
    _spawn_live_background(
        _turn_pause_finalizer(
            context=context,
            thread_id=thread_id,
            live_turn_id=live_turn_id,
            reason=reason,
        ),
        label="turn-pause-finalizer",
        thread_id=thread_id,
    )
    return CoreLiveOperationOutcome(
        response=rpc_result(request_id, {"status": "pausing" if live_turn_id else "paused", "event": None})
    )


def _mark_pause_reason(*, context: CoreLiveContext, thread_id: str, reason: str) -> None:
    """Remember why this session paused, for the log and for a later reader.

    The durable status is written by the run that actually parks; this annotates
    the reason so an operator can tell a user pause from the memory watchdog in
    the log and in the runtime state.
    """
    store = context.runtime_state_store
    if store is None or not thread_id:
        return

    def _mutate(state: Any) -> None:
        if not isinstance(getattr(state, "metadata", None), dict):
            state.metadata = {}
        state.metadata["pause_reason"] = reason

    task = asyncio.get_running_loop().create_task(
        _save_runtime_state_with_retry(store, thread_id, mutate=_mutate)
    )

    def _done(done: asyncio.Task[None]) -> None:
        if not done.cancelled() and done.exception() is not None:
            _logger.warning(
                "[live:pause] could not record the pause reason thread_id=%s: %s",
                thread_id,
                done.exception(),
            )

    task.add_done_callback(_done)


async def _turn_pause_finalizer(
    *,
    context: CoreLiveContext,
    thread_id: str,
    live_turn_id: str,
    reason: str,
) -> None:
    """Settle a pause off the RPC path: close the cut step, park the members.

    Idempotent: a turn that already reads ``paused`` is left alone, and a member
    that is already parked reports nothing.
    """
    registry = context.host.runtime_task_registry
    task = None
    if live_turn_id:
        task_getter = getattr(registry, "task", None)
        task = task_getter(thread_id, run_id=live_turn_id) if callable(task_getter) else None
    if task is not None and not task.done():
        await _escalate_and_wait_cancel(thread_id, task)
    # The kernel writes the paused state itself, but it does so from a detached
    # finalizer when the pause had to cancel the task. Settling the state here
    # closes that race: a Continue issued right after the pause must not read
    # "the previous execution is still settling".
    await _settle_paused_runtime_state(
        context=context, thread_id=thread_id, reason=reason
    )
    await _ensure_paused_status(
        context=context, thread_id=thread_id, live_turn_id=live_turn_id, reason=reason
    )
    await _pause_session_members(context=context, thread_id=thread_id, reason=reason)


async def _settle_paused_runtime_state(
    *, context: CoreLiveContext, thread_id: str, reason: str
) -> None:
    """Move the thread's runtime state to ``paused`` unless it already ended.

    Idempotent and conservative: a state the runtime already declared terminal
    is never rewritten, so a pause racing a completion cannot revive a turn that
    finished on its own.
    """
    store = context.runtime_state_store
    if store is None or not thread_id:
        return

    def _mutate(state: Any) -> None:
        if str(getattr(state, "status", "") or "") in {"completed", "failed", "cancelled", "paused"}:
            return
        state.status = "paused"
        state.loop_state = "paused"
        if not isinstance(getattr(state, "metadata", None), dict):
            state.metadata = {}
        state.metadata["pause_reason"] = reason

    try:
        await _save_runtime_state_with_retry(store, thread_id, mutate=_mutate)
    except BaseException:
        _logger.exception("[live:pause] failed to settle the runtime state thread_id=%s", thread_id)


async def _ensure_paused_status(
    *,
    context: CoreLiveContext,
    thread_id: str,
    live_turn_id: str,
    reason: str,
) -> None:
    """Close the paused turn's dangling step and make sure it reads ``paused``.

    Two writes, both idempotent: a terminal ``tool_result`` per tool row the
    pause cut, so the transcript shows an interrupted step instead of a row that
    spins forever, then the paused status item itself. That second write is a
    no-op when the kernel already wrote it, and the only writer when no live task
    existed to park.
    """
    async with context.session_factory() as session:
        snapshot = await context.persistence.load(session, thread_id)
    core = snapshot.get("core") if isinstance(snapshot.get("core"), dict) else {}
    turns = core.get("turns") if isinstance(core.get("turns"), dict) else {}
    # A repeat pause finds the turn already paused, which is not an "active"
    # turn: without the paused fallback the second press resolves no turn at all
    # and writes nothing, so the live client never learns about it.
    turn_id = live_turn_id or latest_active_turn_id(snapshot) or _paused_turn_id(snapshot) or ""
    if not turn_id or _turn_is_terminal(snapshot, turn_id):
        return

    async def write(db: AsyncSession):
        appended = []
        current = await context.persistence.load(db, thread_id)
        for item_id in _collect_non_terminal_turn_item_ids(current, turn_id, skip_child_items=True):
            appended.append(
                await _append_run_item(
                    db,
                    context=context,
                    event=_build_interrupted_tool_event(
                        thread_id=thread_id,
                        turn_id=turn_id,
                        item_id=item_id,
                        reason="user_pause",
                        message="已暂停，未完成的步骤会在继续后重新执行。",
                    ),
                )
            )
        # Always written. This write is also the projection for the paused turn:
        # nothing else projects it, because a paused turn is not terminal and the
        # streaming path deliberately keeps the snapshot out of its hot loop. A
        # skipped write therefore left the transcript ending at the previous
        # 已中断 row, with no paused row for a reload to serve (2026-10-14).
        appended.append(
            await _append_run_item(
                db,
                context=context,
                event=_build_paused_status_event(
                    snapshot, thread_id=thread_id, turn_id=turn_id, reason=reason
                ),
            )
        )
        return appended

    published = await context.persistence.write(write)
    for event in published:
        try:
            await context.hub.publish(event)
        except BaseException:
            pass


def _build_paused_status_event(
    snapshot: dict[str, Any],
    *,
    thread_id: str,
    turn_id: str,
    reason: str,
) -> RunItemEvent:
    """Status item that moves a turn to ``paused`` without ending it."""
    execution_id = _turn_execution_id(snapshot, turn_id)
    return RunItemEvent(
        kind="status",
        thread_id=thread_id,
        # A fresh event id per pause, a stable item id. Pausing the same turn
        # twice (pause, continue, pause) otherwise reuses the identity of the
        # first pause: the live client drops the repeat as already seen, the
        # button never leaves the state of the previous run, and only a reload
        # shows the truth (2026-10-14). The item id stays stable so the row is
        # replaced instead of stacking.
        event_id=f"{execution_id}:paused:{uuid.uuid4().hex[:8]}",
        run_id=execution_id,
        turn_id=turn_id,
        item_id=f"{execution_id}:paused",
        status="paused",
        payload={
            "type": "turn",
            "status": "paused",
            "raw_end_reason": "user_pause",
            "pause_reason": reason,
            "message": "已暂停。",
        },
    )


async def _resume_session_members(*, context: CoreLiveContext, thread_id: str) -> None:
    """Continue the members a pause parked, after the turn itself resumed."""
    from lamtools_core.sub_agent_supervisor import find_sub_agent_supervisor

    supervisor = find_sub_agent_supervisor(thread_id)
    if supervisor is None:
        return
    resume_suspended = getattr(supervisor, "resume_suspended", None)
    if not callable(resume_suspended):
        return
    try:
        resumed = await resume_suspended()
    except BaseException:
        _logger.exception("[live:resume] failed to continue members thread_id=%s", thread_id)
        return
    if resumed:
        _logger.info(
            "[live:resume] continued %d member(s) thread_id=%s", len(resumed), thread_id
        )


async def _pause_session_members(*, context: CoreLiveContext, thread_id: str, reason: str) -> None:
    """Park every active member of a paused session.

    Members waiting on an unanswered question are left alone: their card is
    still the user's, and the answer queues until the session continues.
    Failures are logged, never raised, because a pause must not fail just
    because a member could not be parked.
    """
    from lamtools_core.sub_agent_supervisor import find_sub_agent_supervisor

    supervisor = find_sub_agent_supervisor(thread_id)
    if supervisor is None:
        return
    pause_active = getattr(supervisor, "pause_active", None)
    if not callable(pause_active):
        return
    try:
        parked = await pause_active()
    except BaseException:
        _logger.exception("[live:pause] failed to park members thread_id=%s", thread_id)
        return
    if parked:
        _logger.info(
            "[live:pause] parked %d member(s) thread_id=%s reason=%s",
            len(parked),
            thread_id,
            reason,
        )


async def _turn_cancel_finalizer(
    *,
    context: CoreLiveContext,
    thread_id: str,
    requested_turn_id: str,
    expected_revision: int | None,
    live_turn_id: str,
    preempted_live_task: bool,
) -> None:
    """Settle a turn interrupt off the RPC critical path.

    Idempotent: concurrent/repeated interrupts re-check inside the write
    transaction, so only the first lands the interrupting record.  A request
    naming a turn that is not the live run never touches the live task — the
    old inline flow returned idle before any registry mutation, and so does
    the finalizer.
    """
    registry = context.host.runtime_task_registry
    targets_live_run = bool(live_turn_id) and (
        not requested_turn_id or requested_turn_id == live_turn_id
    )
    task = None
    if targets_live_run:
        task_getter = getattr(registry, "task", None)
        task = task_getter(thread_id, run_id=live_turn_id) if callable(task_getter) else None
    had_live_task = bool(preempted_live_task or task is not None)
    recorded_turn_id = await _append_interrupting_record(
        context=context,
        thread_id=thread_id,
        requested_turn_id=requested_turn_id,
        expected_revision=expected_revision,
        live_turn_id=live_turn_id,
    )
    if task is not None and not task.done():
        await _escalate_and_wait_cancel(thread_id, task)
    # Release the claim only after the record landed (and the task had its
    # grace): turn.start stays blocked while the old turn is still dying.
    # Skipped entirely when the request targeted a foreign/stale turn.
    if targets_live_run or recorded_turn_id:
        registry.cancel(
            thread_id,
            run_id=recorded_turn_id or live_turn_id or None,
            force=True,
        )
    if recorded_turn_id and (not had_live_task or task is None or task.done()):
        # A task cancelled before its coroutine starts cannot emit a terminal
        # item. Also cover a restart with no task. The terminal write is
        # idempotent when the runtime already settled normally.
        await _persist_cancelled_terminal(
            context=context,
            thread_id=thread_id,
            turn_id=recorded_turn_id,
        )
    # A user Stop pauses the whole session: the members this session left
    # running are interrupted too, so one Stop leaves nothing working behind it
    # (and one Resume brings everything back). Members waiting on an unanswered
    # question are deliberately left alone — that card is still the user's.
    await _interrupt_session_members(context=context, thread_id=thread_id)


async def _interrupt_session_members(*, context: CoreLiveContext, thread_id: str) -> None:
    """Interrupt every active member of a session after a user Stop.

    The supervisor owns member tasks, and only the process that owns them can
    cancel them; a session whose members live in another process keeps them
    (that process settles its own work). Failures are logged, never raised: a
    Stop must not fail because a member could not be interrupted.
    """
    from lamtools_core.sub_agent_supervisor import find_sub_agent_supervisor

    supervisor = find_sub_agent_supervisor(thread_id)
    if supervisor is None:
        return
    try:
        victims = await supervisor.interrupt_active()
    except BaseException:
        _logger.exception("[live:cancel] member interruption failed thread_id=%s", thread_id)
        return
    if victims:
        _logger.info(
            "[live:cancel] interrupted %d member(s) thread_id=%s names=%s",
            len(victims),
            thread_id,
            ",".join(str(record.get("name") or "") for record in victims),
        )


async def _append_interrupting_record(
    *,
    context: CoreLiveContext,
    thread_id: str,
    requested_turn_id: str,
    expected_revision: int | None,
    live_turn_id: str,
) -> str:
    """Durably record the user interrupt for the active turn and publish it.

    Returns the resolved turn id, or "" when nothing was recorded (turn
    already terminal, already recorded as interrupting, or the requested id
    does not match an active turn).

    The client revision CAS is intentionally absent here: by the time the
    background finalizer runs, the turn itself has written new revisions, so
    the request-time revision is always stale.  Idempotency comes from the
    interrupting-record check inside the transaction instead.
    """
    del expected_revision  # validated at request time only

    async def write_action(db: AsyncSession):
        snapshot = await context.persistence.load(db, thread_id)
        turn_id = requested_turn_id or latest_active_turn_id(snapshot) or _paused_turn_id(snapshot) or live_turn_id
        # Fallback to the in-memory registry: when the snapshot has lost the
        # active turn (e.g. a sub-agent DB-lock error rewrote state before the
        # terminal event landed) the background task can still be running. The
        # registry is the source of truth for "is there a live task", so a
        # Stop click must still be able to target it — otherwise the user can
        # only kill the process (the 2b34c636 deadlock).
        if not turn_id:
            turn_id = context.host.runtime_task_registry.active_run_id(thread_id) or ""
        if requested_turn_id and not _is_stoppable_turn(snapshot, requested_turn_id):
            turn_id = ""
        if not turn_id:
            return "", []
        if _turn_is_terminal(snapshot, turn_id):
            return "", []
        core = snapshot.get("core") if isinstance(snapshot.get("core"), dict) else {}
        turns = core.get("turns") if isinstance(core.get("turns"), dict) else {}
        turn_view = turns.get(turn_id) if isinstance(turns.get(turn_id), dict) else {}
        if str(turn_view.get("status") or "") == "interrupting":
            # A previous interrupt (this one or a duplicate click) already
            # recorded the interrupting state — do not append it twice.
            return turn_id, []
        interrupted_input = AppEventInput(
            thread_id=thread_id,
            method="turn/interrupted",
            turn_id=turn_id,
            payload={"type": "turn", "reason": "user_interrupt"},
        )
        execution_id = _turn_execution_id(snapshot, turn_id)
        status_event = RunItemEvent(
            kind="status",
            thread_id=thread_id,
            event_id=f"{execution_id}:interrupting",
            run_id=execution_id,
            turn_id=turn_id,
            item_id=f"{execution_id}:interrupting",
            status="interrupting",
            payload={"type": "turn", "status": "interrupting", "raw_end_reason": "user_interrupt"},
        )
        envelopes = await context.persistence.append_batch(
            db,
            app_events=[interrupted_input],
            run_item_events=[status_event],
        )
        return turn_id, list(envelopes)

    turn_id, envelopes = await context.persistence.write(write_action)
    # Publish after the write transaction committed, matching the old inline
    # ordering so hub subscribers never observe an uncommitted record.
    for envelope in envelopes:
        await context.hub.publish(envelope)
    return turn_id


async def _escalate_and_wait_cancel(thread_id: str, task: asyncio.Task[Any]) -> None:
    """Give the cancelled turn task a short grace, then break through shields.

    The terminal persistence now runs as detached tasks, so a second
    ``task.cancel()`` can no longer strand the interrupting state — it only
    breaks the task out of an await that ignored the first cancel.
    """
    async def _escalate() -> None:
        for delay in CANCEL_ESCALATION_DELAYS_SECONDS:
            await asyncio.sleep(delay)
            if not task.done():
                _logger.warning(
                    "[live] turn task still running %ss after cancel; escalating thread_id=%s",
                    delay,
                    thread_id,
                )
                task.cancel()

    escalation = asyncio.create_task(_escalate())
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=CANCEL_FINALIZER_TASK_WAIT_CAP_SECONDS)
    except asyncio.CancelledError:
        # Normal exit path: the turn task ends cancelled. (Also covers the
        # finalizer itself being cancelled — cleanup below still runs.)
        pass
    except asyncio.TimeoutError:
        pass
    except Exception:
        _logger.exception("[live] turn task raised during cancel unwind thread_id=%s", thread_id)
    finally:
        escalation.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await escalation
    if not task.done():
        _logger.warning(
            "[live] turn task did not exit within %ss of cancel; releasing claim anyway thread_id=%s",
            CANCEL_FINALIZER_TASK_WAIT_CAP_SECONDS,
            thread_id,
        )
        task.cancel()


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
    try:
        expected_revision = _expected_revision(params)
    except ValueError as exc:
        return CoreLiveOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    requested_turn_id = str(params.get("turn_id") or params.get("turnId") or "").strip()

    async def write(db: AsyncSession) -> tuple[list[AppEventEnvelope], dict[str, Any]]:
        snapshot = await context.persistence.load(db, thread_id)
        turn_id = requested_turn_id or _latest_turn_id_any_status(snapshot)
        if not turn_id:
            return [], snapshot
        await context.persistence.assert_revision(db, thread_id, expected_revision)
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
                        message="已中断",
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
                    # Same identity as the kernel's terminal projection: a
                    # force reset refreshes the turn's single cancel row
                    # instead of stacking a second one.
                    item_id=f"{turn_id}:terminal",
                    status="cancelled",
                    payload={
                        "type": "turn",
                        "status": "cancelled",
                        "raw_end_reason": "force_reset",
                        "message": "已中断。",
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
    # Force reset is the strongest Stop: the session's active members stop with
    # it, exactly like an ordinary user Stop.
    await _interrupt_session_members(context=context, thread_id=thread_id)
    for event in events:
        await context.hub.publish(event)
    response_payload: dict[str, Any] = {"status": "reset", "events": [event.to_dict() for event in events]}
    if params.get("include_snapshot") is not False:
        response_payload["snapshot"] = snapshot
    return CoreLiveOperationOutcome(
        response=rpc_result(request_id, response_payload),
        publish_events=events,
    )


def _activate_stored_guidance(context: "CoreLiveContext", event: AppEventEnvelope) -> None:
    """Idempotently activate only durably accepted steering (also on RPC retry)."""
    registry = context.host.runtime_task_registry
    guidance_id = str(event.client_message_id or "")
    if not registry.has_guidance(event.thread_id, run_id=str(event.turn_id or ""), guidance_id=guidance_id):
        registry.accept_guidance(
            event.thread_id, input_items_text(event.payload.get("runtime_input") or event.payload.get("input") or []),
            run_id=str(event.turn_id or ""), guidance_id=guidance_id,
        )
    registry.publish_guidance(event.thread_id, run_id=str(event.turn_id or ""), guidance_id=guidance_id)


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
    try:
        _expected_revision(params)  # Validate the optional event cursor only.
    except ValueError as exc:
        return CoreLiveOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    text = input_items_text(input_items)
    if not text:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="steer input must include text")
        )
    guidance_accepted = False
    include_snapshot = _include_snapshot_param(params)

    async def write(db):
        nonlocal guidance_accepted
        existing = await context.persistence.find_client_event(
            db,
            thread_id=thread_id,
            client_message_id=client_message_id,
            methods={"turn/steered"},
        )
        if existing is not None:
            return "existing", existing
        # Guidance is an idempotent append scoped to turn_id. Live progress
        # changes the session revision between the client's read and this
        # transaction, without invalidating the requested guidance. Check the
        # target run below instead; retain client-message deduplication above.
        registry_run_id = context.host.runtime_task_registry.active_run_id(thread_id)
        # run id 有两种写法（`<thread>:turn:<run>` 与 `<run>`）：这里必须归一后比较，
        # 否则写法不同就会被判成"轮次不匹配"而把一条合法引导挡在门外（2026-10-09）。
        turn_is_active = normalize_run_id(thread_id, registry_run_id) == normalize_run_id(thread_id, turn_id)
        if not turn_is_active:
            # 轮次状态只存于元数据行（turns/requests）；正在运行的回合在这里
            # 直接命中注册表，一次条目表扫描都不需要。
            metadata_state = await context.persistence.load_metadata(db, thread_id)
            if not _is_active_turn(metadata_state, turn_id):
                return "mismatch", None
        guidance_status = context.host.runtime_task_registry.accept_guidance(
            thread_id,
            text,
            run_id=turn_id,
            guidance_id=client_message_id,
            ready=False,
        )
        if guidance_status not in {"accepted", "duplicate"}:
            return "run_not_active", None
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
                    payload={"type": "turn", "input": input_items, "guidance_id": client_message_id},
                ),
            )
        except BaseException:
            context.host.runtime_task_registry.retract_guidance(
                thread_id, run_id=turn_id, guidance_id=client_message_id
            )
            guidance_accepted = False
            raise
        return "applied", event

    try:
        write_result = await context.persistence.write(write)
    except BaseException:
        if guidance_accepted:
            context.host.runtime_task_registry.retract_guidance(
                thread_id, run_id=turn_id, guidance_id=client_message_id
            )
        raise
    outcome_kind, payload = write_result
    if outcome_kind in {"existing", "applied"}:
        _activate_stored_guidance(context, payload)
    snapshot: dict[str, Any] | None = None
    if include_snapshot:
        snapshot = await _load_snapshot_outside_write_lock(context, thread_id)
    if outcome_kind == "existing":
        assert isinstance(payload, AppEventEnvelope)
        response_payload: dict[str, Any] = {
            "applied": True,
            "reason": "already_applied",
            "events": [payload.to_dict()],
        }
        if snapshot is not None:
            response_payload["snapshot"] = snapshot
        return CoreLiveOperationOutcome(response=rpc_result(request_id, response_payload))
    if outcome_kind == "mismatch":
        response_payload = {"applied": False, "reason": "active_turn_mismatch", "events": []}
        if snapshot is not None:
            response_payload["snapshot"] = snapshot
        return CoreLiveOperationOutcome(response=rpc_result(request_id, response_payload))
    if outcome_kind == "run_not_active":
        response_payload = {"applied": False, "reason": "run_not_active", "events": []}
        if snapshot is not None:
            response_payload["snapshot"] = snapshot
        return CoreLiveOperationOutcome(response=rpc_result(request_id, response_payload))
    event = payload
    await context.hub.publish(event)
    response_payload = {"applied": True, "reason": "", "events": [event.to_dict()]}
    if snapshot is not None:
        response_payload["snapshot"] = snapshot
    return CoreLiveOperationOutcome(
        response=rpc_result(request_id, response_payload),
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
    try:
        expected_revision = _expected_revision(params)
    except ValueError as exc:
        return CoreLiveOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    loop = asyncio.get_running_loop()
    decision_ready: asyncio.Future[dict[str, Any]] = loop.create_future()

    async def decision_durable(info: dict[str, Any]) -> None:
        thread_id = str(info.get("thread_id") or "").strip()
        run_id = str(info.get("run_id") or info.get("turn_id") or "").strip()
        # A child continuation is admitted against the CHILD session, not the
        # parent thread: it writes the child's state and only publishes onto the
        # parent's timeline, so claiming the parent would let one child's answer
        # block another child's (and block a new parent turn) for as long as the
        # first child keeps working.
        claim_thread_id = str(info.get("claim_thread_id") or "").strip() or thread_id
        task = asyncio.current_task()
        if str(info.get("decision") or "") != "deny":
            if task is None or not thread_id or not run_id:
                raise RuntimeError("approval continuation identity is unavailable")
            registry = context.host.runtime_task_registry
            prior_task = registry.task(claim_thread_id, run_id=run_id)
            if prior_task is not None and prior_task is not task:
                registry.release_run(claim_thread_id, run_id=run_id)
            if not registry.accept_run(claim_thread_id, run_id):
                raise RuntimeError("approval continuation runtime claim failed")
            if not registry.register(claim_thread_id, task, run_id=run_id):
                registry.release_run(claim_thread_id, run_id=run_id)
                raise RuntimeError("approval continuation task registration failed")
            if not decision_ready.done():
                decision_ready.set_result(dict(info))

    async def continue_approval() -> OperationResult:
        thread_id = ""
        run_id = ""
        try:
            # Keep the paused turn's model/runtime options, but overlay the
            # session's current permission state before continuing.
            approval_params = dict(params)
            approval_thread_id = _thread_id_from_params(approval_params)
            approval_params.setdefault("approval_policy", "require")
            approval_params.setdefault("active_tier", None)
            approval_params.setdefault("tier_tools", None)
            approval_params.setdefault("allow_access_outside_workdir", False)
            state_store = context.host.runtime_state_store
            if state_store is not None:
                approval_state = None
                if approval_thread_id:
                    approval_state = await state_store.get(approval_thread_id)
                if approval_state is None:
                    approval_request_id = str(
                        approval_params.get("request_id")
                        or approval_params.get("requestId")
                        or ""
                    ).strip()
                    finder = getattr(state_store, "find_pending_approval", None)
                    if approval_request_id and callable(finder):
                        approval_state = await finder(approval_request_id)
                if approval_state is not None and not approval_thread_id:
                    approval_thread_id = str(approval_state.session_id or "").strip()
                raw_snapshot = (
                    approval_state.metadata.get("runtime_snapshot")
                    if approval_state is not None and isinstance(approval_state.metadata, dict)
                    else None
                )
                if approval_thread_id:
                    current_permissions = await _resolve_turn_approval_policy(
                        context=context,
                        params={"thread_id": approval_thread_id},
                    )
                    current_snapshot = current_permissions["runtime_snapshot"]
                    merged_snapshot = deepcopy(raw_snapshot) if isinstance(raw_snapshot, dict) else {}
                    for key in RUNTIME_PERMISSION_KEYS:
                        if key in current_snapshot:
                            merged_snapshot[key] = deepcopy(current_snapshot[key])
                    approval_params["runtime_snapshot"] = merged_snapshot
                    approval_params.update({
                        key: deepcopy(current_snapshot[key])
                        for key in RUNTIME_PERMISSION_KEYS
                        if key in current_snapshot
                    })
            if approval_thread_id and expected_revision is not None:
                await context.persistence.write(
                    lambda db: context.persistence.assert_revision(
                        db, approval_thread_id, expected_revision
                    )
                )
                thread_id = approval_thread_id
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


async def handle_session_permissions_set_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    context: CoreLiveContext,
) -> CoreLiveOperationOutcome:
    """Persist a live session preset and release an existing approval."""
    thread_id = _thread_id_from_params(params)
    if not thread_id:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="thread_id is required")
        )
    try:
        preset = normalize_permission_preset(
            params.get("permission_preset", params.get("permissionPreset"))
        )
        expected_revision = _expected_revision(params)
    except ValueError as exc:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc))
        )

    session_store = context.host.session_store
    if session_store is None:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="session store is unavailable")
        )
    record = await session_store.get(thread_id)
    if record is None:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="session not found")
        )
    metadata = with_session_runtime_preferences(
        record.metadata,
        permission_preset=preset,
    )
    patch = getattr(session_store, "patch", None)
    if not callable(patch):
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="session update is unavailable")
        )
    updated = await patch(
        thread_id,
        metadata=metadata,
        expected_revision=expected_revision,
    )
    if updated is None:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="session not found")
        )

    session_event = {
        "method": "session/updated",
        "thread_id": thread_id,
        "payload": {
            "session": {
                "id": updated.id,
                "metadata": updated.metadata,
            }
        },
    }
    await context.hub.publish(session_event)

    approval_status = "not_pending"
    if preset in {"auto", "full_access"} and context.host.runtime_state_store is not None:
        state = await context.host.runtime_state_store.get(thread_id)
        pending = (
            state.metadata.get("pending_approval")
            if state is not None and isinstance(state.metadata, dict)
            else None
        )
        pending_call = pending.get("tool_call") if isinstance(pending, dict) else None
        pending_status = str(pending.get("status") or "waiting") if isinstance(pending, dict) else ""
        approval_request_id = str(
            (
                pending.get("request_id")
                or (pending_call.get("id") if isinstance(pending_call, dict) else "")
            )
            if isinstance(pending, dict)
            else ""
        ).strip()
        if isinstance(pending_call, dict) and str(pending_call.get("name") or "") == "question":
            approval_status = "user_input_required"
        if (
            isinstance(pending_call, dict)
            and str(pending_call.get("name") or "") != "question"
            and pending_status == "waiting"
            and approval_request_id
        ):
            approval_outcome = await handle_approval_respond_operation(
                request_id=None,
                params={
                    "thread_id": thread_id,
                    "request_id": approval_request_id,
                    "decision": "approve_once",
                    "guidance": "",
                },
                context=context,
            )
            approval_status = (
                "accepted"
                if isinstance(approval_outcome.response, dict)
                and "result" in approval_outcome.response
                else "failed"
            )

    return CoreLiveOperationOutcome(
        response=rpc_result(
            request_id,
            {
                "thread_id": thread_id,
                "permission_preset": preset,
                "approval_status": approval_status,
                "session": updated.to_dict(),
            },
        )
    )


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
        # 仅校验参数形状；排队是幂等追加，不参与修订号 CAS（见下方 write 的说明）。
        _expected_revision(params)
    except ValueError as exc:
        return CoreLiveOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    queue_item_id = str(params.get("queue_item_id") or params.get("queueItemId") or f"queue:{uuid.uuid4().hex[:12]}")
    client_message_id = str(params.get("client_message_id") or params.get("clientMessageId") or uuid.uuid4().hex)
    # Resolve permissions at queue acceptance time.  The queue item must carry
    # its own immutable runtime snapshot because Composer/session settings may
    # change before this item is dispatched.
    try:
        resolved = await _resolve_turn_approval_policy(
            context=context,
            params={**params, "thread_id": thread_id},
        )
    except ValueError as exc:
        return CoreLiveOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    if not (params.get("work_root") or params.get("workRoot")) and resolved.get("work_root"):
        params = {**params, "work_root": resolved["work_root"]}
    try:
        prepared = await context.host.member_hooks.prepare_queue_input(
            thread_id=thread_id, params=params, input_items=input_items,
        )
    except ValueError as exc:
        return CoreLiveOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    queue_runtime_snapshot = _runtime_snapshot_with_turn_options(
        resolved["runtime_snapshot"],
        params=params,
        active_mode=resolved.get("active_mode"),
    )
    payload = queue_item_payload(
        queue_item_id=queue_item_id,
        input_items=prepared.visible_input,
        runtime_input_items=prepared.runtime_input,
        mode=str(params.get("mode") or "next_turn"),
        runtime_snapshot=queue_runtime_snapshot,
    )
    payload["work_root"] = prepared.work_root
    async def write(db: AsyncSession):
        existing = await context.persistence.find_client_event(
            db,
            thread_id=thread_id,
            client_message_id=client_message_id,
            methods=QUEUE_ITEM_ACCEPTED_METHODS,
        )
        if existing is not None:
            return existing, None
        # 排队是"只增"的幂等追加：条目自带 queue_item_id 与 runtime_snapshot，
        # 写入在事务内读的是最新快照，客户端传进来的期望修订号不参与任何读改写。
        # 因此这里刻意不做 CAS：主回合等待后台子代理期间，会话修订号会被持续追加
        # 的事件推高（本轮事件、成员转发事件），客户端在发起 RPC 前读到的修订号
        # 几乎必然落后，CAS 会把一条完全合法的消息打成"Revision conflict"（用户
        # 只能刷新重试才能发出）。真正需要乐观锁的是读改写类变更（turn.start、
        # command.execute、queue.update/delete/guide、会话设置），它们各自的 CAS
        # 一个都没有动，这里移除的只针对幂等追加。expected_revision 仍按参数校验
        # （见本函数入口），但不再作为拒绝依据（2026-10-12）。
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
        return event, materialized

    event, materialized = await context.persistence.write(write)
    await context.hub.publish(event)
    # Response queue item is rebuilt from the payload we just wrote; the queue
    # lives in the metadata row, so no full snapshot assembly is required.
    queue_item = {
        **payload,
        **(materialized.payload_extra if materialized is not None else {}),
        "queue_item_id": queue_item_id,
        "status": "queued",
        "mode": str(payload.get("mode") or "next_turn"),
        "input": prepared.visible_input,
        "seq": event.seq,
        "last_method": "queue/itemAccepted",
    }
    response_payload: dict[str, Any] = {"queue_item": queue_item, "events": [event.to_dict()]}
    if _include_snapshot_param(params):
        response_payload["snapshot"] = await _load_snapshot_outside_write_lock(context, thread_id)
    return CoreLiveOperationOutcome(
        response=rpc_result(request_id, response_payload),
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
    try:
        _expected_revision(params)  # 形状校验；写事件是幂等追加，见 write 说明
    except ValueError as exc:
        return CoreLiveOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
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
    ) -> tuple[str, AppEventEnvelope | None]:
        # 队列条目本身存放在元数据行；更新计划不需要逐条装配会话内容。
        snapshot = await context.persistence.load_metadata(db, thread_id)
        plan = build_queue_update_plan(
            snapshot,
            queue_item_id=queue_item_id,
            input_items=prepared.visible_input,
            runtime_input_items=prepared.runtime_input,
            mode=str(params.get("mode") or "").strip() or None,
        )
        if not plan.applied:
            return plan.reason, None
        # 更新排队条目是幂等追加（queue_item_id 为键），计划在事务内基于最新元数据
        # 行构建，客户端期望修订号不参与任何读改写。这里不做 CAS：活跃回合持续追加
        # 事件会让客户端读到的修订号必然落后，CAS 会把合法的编辑打成修订冲突
        # （2026-10-12，与 queue.create 同一原因）。
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
        return "applied", event

    outcome_kind, payload = await context.persistence.write(write)
    if outcome_kind != "applied":
        response_payload = {"applied": False, "reason": outcome_kind, "events": []}
        if _include_snapshot_param(params):
            response_payload["snapshot"] = await _load_snapshot_outside_write_lock(context, thread_id)
        return CoreLiveOperationOutcome(response=rpc_result(request_id, response_payload))
    event = payload
    await context.hub.publish(event)
    response_payload = {"events": [event.to_dict()]}
    if _include_snapshot_param(params):
        response_payload["snapshot"] = await _load_snapshot_outside_write_lock(context, thread_id)
    return CoreLiveOperationOutcome(
        response=rpc_result(request_id, response_payload),
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
    try:
        _expected_revision(params)  # 形状校验；删除是幂等追加，见 write 说明
    except ValueError as exc:
        return CoreLiveOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    async def write(db: AsyncSession) -> AppEventEnvelope:
        # 删除排队条目只追加一个 queue_item_id 为键的 tombstone 事件，不读改写任何
        # 共享字段；活跃回合持续追加事件时客户端修订号必然落后，CAS 会让用户根本删
        # 不掉这条排队消息（2026-10-12）。因此与 queue.create 一致，不做修订号 CAS。
        return await _append_app_event(
            db,
            context=context,
            event=AppEventInput(
                thread_id=thread_id,
                method="queue/itemDeleted",
                item_id=queue_item_id,
                payload=queue_delete_payload(queue_item_id=queue_item_id, status="deleted"),
            ),
        )

    event = await context.persistence.write(write)
    await context.hub.publish(event)
    response_payload: dict[str, Any] = {"events": [event.to_dict()]}
    if _include_snapshot_param(params):
        response_payload["snapshot"] = await _load_snapshot_outside_write_lock(context, thread_id)
    return CoreLiveOperationOutcome(
        response=rpc_result(request_id, response_payload),
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
    try:
        _expected_revision(params)  # 形状校验；引导是幂等追加，见 write 说明
    except ValueError as exc:
        return CoreLiveOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    client_message_id = str(
        params.get("client_message_id") or params.get("clientMessageId") or f"queue-guide:{queue_item_id}"
    )
    replacement_text = params.get("text") if isinstance(params.get("text"), str) else None
    guidance_accepted = False

    async def write(
        db: AsyncSession,
    ) -> tuple[str, Any, Any]:
        """Return (kind, payload, plan): kind is existing/mismatch/applied/not_applied."""
        nonlocal guidance_accepted
        existing = await context.persistence.find_client_event(
            db,
            thread_id=thread_id,
            client_message_id=client_message_id,
            methods={"turn/steered"},
        )
        if existing is not None:
            return "existing", existing, None
        # 引导计划只需要队列与轮次状态（元数据行），不需要装配全部会话条目。
        snapshot = await context.persistence.load_metadata(db, thread_id)
        plan = build_queue_guidance_plan(
            snapshot,
            thread_id=thread_id,
            turn_id=turn_id,
            queue_item_id=queue_item_id,
            client_message_id=client_message_id,
            replacement_text=replacement_text,
        )
        if plan.applied:
            # 引导把排队条目转成两枚追加事件（turn/steered + itemDeleted）并在内存
            # 注册表登记，不读改写共享的持久字段。活跃回合持续追加事件会让客户端修订
            # 号落后，CAS 会把合法的引导打成修订冲突（2026-10-12，同 queue.create）。
            guidance_text = input_items_text(plan.runtime_input_items)
            guidance_status = context.host.runtime_task_registry.accept_guidance(
                thread_id,
                guidance_text,
                run_id=turn_id,
                guidance_id=client_message_id,
                ready=False,
            )
            if guidance_status not in {"accepted", "duplicate"}:
                return "run_not_active", None, plan
            if guidance_status == "accepted":
                guidance_accepted = True
            try:
                app_event_inputs = [_app_event_input(spec) for spec in plan.events]
                for event_input in app_event_inputs:
                    if event_input.method == "turn/steered":
                        event_input.payload["guidance_id"] = client_message_id
                        event_input.payload["runtime_input"] = plan.runtime_input_items
                events: list[AppEventEnvelope] = []
                if app_event_inputs:
                    events = await context.persistence.append_batch(db, app_events=app_event_inputs)
            except BaseException:
                context.host.runtime_task_registry.retract_guidance(
                    thread_id, run_id=turn_id, guidance_id=client_message_id
                )
                guidance_accepted = False
                raise
            return "applied", events, plan
        return "not_applied", None, plan

    try:
        write_result = await context.persistence.write(write)
    except BaseException:
        if guidance_accepted:
            context.host.runtime_task_registry.retract_guidance(
                thread_id, run_id=turn_id, guidance_id=client_message_id
            )
        raise
    outcome_kind, payload, plan = write_result
    if outcome_kind == "existing":
        _activate_stored_guidance(context, payload)
    elif outcome_kind == "applied":
        for stored_event in payload:
            if stored_event.method == "turn/steered":
                _activate_stored_guidance(context, stored_event)
    snapshot: dict[str, Any] | None = None
    if _include_snapshot_param(params):
        snapshot = await _load_snapshot_outside_write_lock(context, thread_id)

    def _guidance_response(**extra: Any) -> CoreLiveOperationOutcome:
        response_payload: dict[str, Any] = {
            "applied": plan.applied if plan is not None else outcome_kind == "applied",
            "reason": plan.reason if plan is not None else "",
            **extra,
        }
        if snapshot is not None:
            response_payload["snapshot"] = snapshot
        return CoreLiveOperationOutcome(response=rpc_result(request_id, response_payload))

    if outcome_kind == "existing":
        assert isinstance(payload, AppEventEnvelope)
        return _guidance_response(applied=True, reason="already_applied", events=[payload.to_dict()])
    if outcome_kind == "run_not_active":
        return _guidance_response(applied=False, reason="run_not_active", events=[])
    events = payload if outcome_kind == "applied" else []
    for event in events:
        await context.hub.publish(event)
    return CoreLiveOperationOutcome(
        response=rpc_result(
            request_id,
            {
                "applied": plan.applied,
                "reason": plan.reason,
                "events": [event.to_dict() for event in events],
                **({"snapshot": snapshot} if snapshot is not None else {}),
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
    model_id: str = "",
) -> None:
    """Background task: derive a short title from the first user message.

    Best-effort — any failure is logged and swallowed so it can never affect
    the ongoing turn. Persists the title via the session store (when available)
    and broadcasts ``session/updated`` so frontends refresh their sidebar.
    """
    llm_client = context.host.llm_client
    session_store = context.host.session_store
    if llm_client is None:
        return
    try:
        # Don't clobber a title the user already set manually.
        existing_title: str | None = None
        existing: Any = None
        if session_store is not None:
            existing = await session_store.get(thread_id)
            existing_title = getattr(existing, "title", None) if existing else None
        if not is_default_title(existing_title, session_id=thread_id):
            return

        resolved_model = model_id
        if not resolved_model and existing is not None:
            metadata = getattr(existing, "metadata", None)
            if isinstance(metadata, dict):
                resolved_model = str(metadata.get("model_id") or "").strip()
        if not resolved_model:
            # Background work follows the background scene, never the main
            # conversation's model and never a boot-time "default".
            from lamtools_core.config.model_selection import (
                ModelResolutionError,
                SCENE_BACKGROUND,
                record_model_notice,
                resolve_scene_model,
            )

            try:
                resolved_model = resolve_scene_model(SCENE_BACKGROUND).model_id
            except ModelResolutionError:
                # Auto-title is best-effort and must not fail the turn; make the
                # skipped title visible instead of borrowing another model.
                record_model_notice("后台任务没有可用模型，已跳过会话标题生成；请先添加供应商/模型")
                return

        title = await generate_session_title(
            llm_client,
            resolved_model,
            first_message,
            session_id=thread_id,
        )
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
    # A continuation of a paused turn carries no new text on purpose: the
    # committed history already holds the task and every finished step. Only a
    # turn that has nothing else to run on is an error.
    continuation = str(runtime_start.get("origin") or "") == "turn_resume"
    if not thread_id or (not message and not continuation):
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
            if result.status != "ok":
                # Setup/validation can return an error before the kernel emits
                # any terminal event. Never leave that accepted turn running.
                # Existing recorded terminal reasons are preserved by this helper.
                await _fail_runtime_start(
                    context=context, thread_id=thread_id, turn_id=turn_id,
                    message=str(result.payload.get("error") or result.status),
                )
            await _ensure_turn_terminal(context=context, thread_id=thread_id, turn_id=turn_id)
        await _dispatch_next_queue_item(
            context=context,
            thread_id=thread_id,
            work_root=str(runtime_start.get("work_root") or ""),
            completed_turn_id=turn_id,
        )
    except BaseException as exc:
        _elapsed = time_module.time() - _start_ts
        get_cancel_event = getattr(context.host.runtime_task_registry, "get_cancel_event", None)
        cancel_requested = bool(callable(get_cancel_event) and get_cancel_event(thread_id).is_set())
        get_pause_event = getattr(context.host.runtime_task_registry, "get_pause_event", None)
        pause_requested = bool(callable(get_pause_event) and get_pause_event(thread_id).is_set())
        if pause_requested and not cancel_requested:
            # The pause aborted the task (a tool that never checks the pause
            # event). The kernel's detached pause finalizer writes the resumable
            # state; marking the turn failed here would overwrite it.
            _logger.info(
                "[live:_run_core_turn] turn paused thread_id=%s turn_id=%s elapsed=%.2fs",
                thread_id,
                turn_id,
                _elapsed,
            )
            raise
        if cancel_requested:
            _logger.info(
                "[live:_run_core_turn] turn cancelled thread_id=%s turn_id=%s elapsed=%.2fs",
                thread_id,
                turn_id,
                _elapsed,
            )
            # Detached: the turn task must exit now so the registry claim is
            # released immediately; the terminal record settles in the
            # background like every other cancel-path write.
            _spawn_live_background(
                _persist_cancelled_terminal(
                    context=context,
                    thread_id=thread_id,
                    turn_id=turn_id,
                ),
                label="turn-cancelled-terminal",
                thread_id=thread_id,
            )
            raise
        _logger.exception(
            "[live:_run_core_turn] turn failed thread_id=%s turn_id=%s elapsed=%.2fs",
            thread_id,
            turn_id,
            _elapsed,
        )
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
    if effective_thread_status(snapshot) in {"completed", "idle", "waiting", "paused"}:
        return
    # Check if the current turn is the last active turn
    core_state = snapshot.get("core") if isinstance(snapshot.get("core"), dict) else {}
    latest_active = latest_active_turn_id({"core": core_state, "turns": snapshot.get("turns", {})})
    if latest_active is not None and latest_active != turn_id:
        return
    # The turn itself must already be terminal before we backfill a completed
    # status — a turn still waiting for approval (or otherwise non-terminal)
    # must never be marked completed, or the queue would dispatch the next
    # item without approval and two kernels would run concurrently
    # (audit 01 S1).
    if _turn_is_terminal(snapshot, turn_id):
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


async def _session_current_model(context: CoreLiveContext, thread_id: str) -> str:
    """Return the model the session is currently using (its last turn's model)."""
    store = context.runtime_state_store
    if store is None or not thread_id:
        return ""
    try:
        state = await store.get(thread_id)
    except Exception:
        return ""
    metadata = getattr(state, "metadata", None)
    if not isinstance(metadata, dict):
        return ""
    snapshot = metadata.get("runtime_snapshot")
    if isinstance(snapshot, dict):
        model = str(snapshot.get("model_id") or "").strip()
        if model:
            return model
    return str(metadata.get("model_id") or "").strip()


async def _dispatch_next_queue_item(
    *,
    context: CoreLiveContext,
    thread_id: str,
    work_root: str,
    completed_turn_id: str,
) -> None:
    async with context.session_factory() as db:
        current_snapshot = await context.persistence.load(db, thread_id)
    queued_candidate = next_dispatchable_queue_item(current_snapshot)
    if queued_candidate is None:
        return
    live_permissions = await _resolve_turn_approval_policy(
        context=context,
        params={"thread_id": thread_id},
    )
    live_permission_snapshot = live_permissions["runtime_snapshot"]
    context.host.runtime_task_registry.release_run(thread_id, run_id=completed_turn_id)
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
            runtime_snapshot = _queue_runtime_snapshot(queued)
            # A queued message carries a snapshot from the moment it was queued.
            # If the session's model changed since then, the queued snapshot's
            # model must not win: the turn runs with the model the session is
            # currently on (what the UI shows), and the alignment is announced.
            queued_model = str(runtime_snapshot.get("model_id") or "").strip()
            current_model = await _session_current_model(context, thread_id)
            if current_model and current_model != queued_model:
                runtime_snapshot["model_id"] = current_model
                if queued_model:
                    from lamtools_core.config.model_selection import record_model_notice

                    record_model_notice(
                        f"排队消息原定的模型「{queued_model}」与当前模型不一致，"
                        f"已按当前模型「{current_model}」执行"
                    )
            for key in RUNTIME_PERMISSION_KEYS:
                if key in live_permission_snapshot:
                    runtime_snapshot[key] = deepcopy(live_permission_snapshot[key])
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
                params={"work_root": queued_work_root, **runtime_snapshot},
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
                turn_payload_extra={
                    **materialized.turn_payload_extra,
                    "runtime_snapshot": runtime_snapshot,
                },
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
                "approval_policy": runtime_snapshot.get("approval_policy", "require"),
                "active_tier": runtime_snapshot.get("active_tier"),
                "tier_tools": runtime_snapshot.get("tier_tools"),
                "active_mode": runtime_snapshot.get("active_mode"),
                "instructions": str(runtime_snapshot.get("instructions") or ""),
                "request_local_late_context": str(
                    runtime_snapshot.get("request_local_late_context") or ""
                ),
                "allow_access_outside_workdir": bool(
                    runtime_snapshot.get("allow_access_outside_workdir", False)
                ),
                "permission_preset": runtime_snapshot.get("permission_preset", "ask"),
                "runtime_snapshot": runtime_snapshot,
                **prepared.runtime_extras,
                **materialized.runtime_extras,
            }
            for key in (
                "model_id",
                "reasoning_level",
                "thinking_enabled",
                "thinking_budget",
                "reasoning_effort",
                "shallow_thinking_enabled",
                "context_window_tokens",
                "max_tokens",
                "temperature",
                "compact_trigger_tokens",
                "compact_limit_tokens",
            ):
                if key in runtime_snapshot:
                    runtime_start[key] = runtime_snapshot[key]
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


def _paused_turn_id(snapshot: dict[str, Any]) -> str:
    """The turn a session is currently paused on, if any.

    A paused turn is not "active" (nothing is executing), but it still owns the
    session: the next user input continues it instead of starting a new turn.
    """
    core = snapshot.get("core") if isinstance(snapshot, dict) else None
    turns = core.get("turns") if isinstance(core, dict) else None
    if not isinstance(turns, dict):
        return ""
    for turn_id, turn in turns.items():
        if isinstance(turn, dict) and str(turn.get("status") or "") == "paused":
            return str(turn_id)
    return ""


def _collect_non_terminal_turn_item_ids(
    snapshot: dict[str, Any], turn_id: str, *, skip_child_items: bool = False
) -> list[str]:
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
        if skip_child_items and is_sub_agent_child_item(item):
            # A member's timeline outlives the parent turn, exactly as the
            # terminal path already assumes: its waiting question belongs to the
            # user, so a pause must not close it (2026-10-14).
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
    message: str = "已中断",
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
        terminal = build_cancelled_turn_event(thread_id=thread_id, turn_id=turn_id)
        execution_id = _turn_execution_id(snapshot, turn_id)
        terminal.run_id = execution_id
        terminal.event_id = f"{execution_id}:cancelled"
        terminal.item_id = f"{execution_id}:terminal"
        event = await _append_run_item(db, context=context, event=terminal)
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
    *, context: CoreLiveContext, thread_id: str, turn_id: str, reason: str = "user_cancelled"
) -> None:
    store = context.runtime_state_store
    if store is None:
        return

    def _mark_cancelled(state: Any) -> None:
        if str(state.metadata.get("turn_id") or state.run_id) != turn_id:
            return
        state.status = "cancelled"
        state.loop_state = "failed"
        state.metadata["cancellation_reason"] = reason
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


async def _active_thread_ids(*, context: "CoreLiveContext") -> list[str]:
    """Thread ids whose snapshot still holds a non-terminal turn."""
    try:
        async with context.session_factory() as db:
            list_active = getattr(context.persistence, "list_active_thread_ids", None)
            if callable(list_active):
                return list(await list_active(db))
            return list(await context.persistence.list_thread_ids(db))
    except BaseException:
        _logger.exception("[live:reconcile] failed to enumerate threads")
        return []


async def _close_active_turns(
    db: AsyncSession,
    *,
    context: "CoreLiveContext",
    thread_id: str,
    verdict_for: "Callable[[str, dict[str, Any]], tuple[str, str, str] | None]",
) -> list[tuple[str, AppEventEnvelope]]:
    """Close a thread's leftover active turns with the verdict ``verdict_for`` returns.

    The dangling non-terminal items (a half-streamed tool_call, for instance)
    are closed BEFORE the turn-level terminal event: the snapshot reducer's
    turn-terminal lock would otherwise force-override item status on later
    events while the event log still held orphaned ``running`` events, leaving
    replay inconsistent. A ``None`` verdict leaves that turn alone.
    """
    events: list[tuple[str, AppEventEnvelope]] = []
    seen: set[str] = set()
    while True:
        snapshot = await context.persistence.load(db, thread_id)
        active = latest_active_turn_id(snapshot)
        if not active or active in seen:
            break
        verdict = verdict_for(active, snapshot)
        if verdict is None:
            break
        seen.add(active)
        status, reason, message = verdict
        execution_id = _turn_execution_id(snapshot, active)
        dangling = _collect_non_terminal_turn_item_ids(snapshot, active)
        for item_id in dangling:
            tool_event = await _append_run_item(
                db,
                context=context,
                event=_build_interrupted_tool_event(
                    thread_id=thread_id,
                    turn_id=active,
                    item_id=item_id,
                    reason=reason,
                    message=message,
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
                event_id=f"{execution_id}:{reason}",
                run_id=execution_id,
                turn_id=active,
                # Same identity as the kernel's terminal projection: the
                # reaper refreshes the turn's single cancel row rather than
                # appending another "recovered" bubble on every incident.
                item_id=f"{execution_id}:terminal",
                status=status,
                payload={
                    "type": "turn",
                    "status": status,
                    "raw_end_reason": reason,
                    "message": message,
                },
            ),
        )
        events.append((active, event))
        if len(events) > 50:
            break
    return events


def _terminal_verdict(state: Any) -> tuple[str, str, str] | None:
    """Terminal ``(status, reason, message)`` for a state the runtime already ended.

    ``None`` while the state is not terminal: a live turn owns its own ending,
    and a state that has not been written is not evidence of anything.
    """
    status = str(getattr(state, "status", "") or "")
    if status not in {"failed", "cancelled"}:
        return None
    metadata = getattr(state, "metadata", None)
    metadata = metadata if isinstance(metadata, dict) else {}
    if state_is_memory_exhaustion(state):
        # Includes states written before the code existed: the interruption is
        # still memory, so the user gets the same explanation and the same
        # armed resume rather than a generic "ended unexpectedly".
        message = str(metadata.get("failure_message") or "").strip() or memory_exhausted_message_for(state)
        return status, HOST_MEMORY_EXHAUSTED, message
    code = str(metadata.get("failure_code") or "")
    message = str(metadata.get("failure_message") or "").strip()
    if not message:
        message = "已中断。"
    return status, code or ("user_interrupt" if status == "cancelled" else "failed"), message


async def _arm_pending_memory_resume(
    *,
    context: "CoreLiveContext",
    thread_id: str,
    state: Any,
    verdict: tuple[str, str, str] | None,
) -> bool:
    """Arm the auto resume for a turn whose recorded ending was memory exhaustion.

    Idempotent and best-effort: arming is what lets the watchdog continue the
    turn once the machine can afford it, so it must survive the restart that
    interrupted the write.
    """
    if verdict is None or verdict[1] != HOST_MEMORY_EXHAUSTED:
        return False
    store = context.runtime_state_store
    if store is None:
        return False
    try:
        if not ensure_pending_memory_resume(state):
            return False
        await _save_runtime_state_with_retry(
            store, thread_id, mutate=ensure_pending_memory_resume
        )
    except BaseException:
        _logger.exception("[live:reconcile] arming the memory resume failed thread_id=%s", thread_id)
        return False
    _logger.warning("[live:reconcile] armed the memory resume thread_id=%s", thread_id)
    return True


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

    A turn parked on a user decision (tool approval / question) is exempt: its
    approval is durable and ``approval.respond`` can still resume it, so the
    user can answer it after the restart. Reaping that turn wrote a cancelled
    terminal over the request the user was about to answer, which is how
    closing Sunday mid-approval lost the approval entirely (2026-10-01).

    ``reconcile_terminal_turns`` runs after this and repairs the turns whose
    runtime state already recorded *why* they ended.
    """
    recovered = 0
    for thread_id in await _active_thread_ids(context=context):
        if await _active_turn_awaits_user_decision(context=context, thread_id=thread_id):
            _logger.info(
                "[live:recover] keeping thread_id=%s parked on a user decision", thread_id
            )
            continue

        # Ask the durable state first. When the runtime already recorded why the
        # turn ended (a memory exhaustion, for instance) that reason is the
        # truth; stamping the generic "unexpected shutdown" over it buried the
        # cause AND swallowed the auto resume — the interrupted PV session was
        # closed as an anonymous cancellation that way (2026-10-10).
        store = context.runtime_state_store
        state = None
        try:
            if store is not None:
                state = await store.get(thread_id)
        except BaseException:
            _logger.exception("[live:recover] runtime-state read failed thread_id=%s", thread_id)
            continue
        from lamtools_core.runtime_owner import LIVE_RUN_STATES, owner_is_live, read_owner
        if (state is not None and state.status in LIVE_RUN_STATES
                and owner_is_live(read_owner(state.metadata))):
            _logger.info("[live:recover] keeping thread_id=%s owned by a live process", thread_id)
            continue
        state_verdict = _terminal_verdict(state) if state is not None else None
        recorded_run_id = str(state.metadata.get("turn_id") or state.run_id or "") if state is not None else ""
        fallback_verdict = ("cancelled", "unexpected_shutdown", "已中断。")
        from_record = False

        def _verdict_for(active: str, _snapshot: dict[str, Any]) -> tuple[str, str, str] | None:
            nonlocal from_record
            if state_verdict is not None and (not recorded_run_id or active == recorded_run_id):
                from_record = True
                return state_verdict
            return fallback_verdict

        async def write(
            db: AsyncSession, *, thread_id: str = thread_id
        ) -> list[tuple[str, AppEventEnvelope]]:
            return await _close_active_turns(
                db,
                context=context,
                thread_id=thread_id,
                verdict_for=_verdict_for,
            )

        try:
            items = await context.persistence.write(write)
        except BaseException:
            _logger.exception("[live:recover] failed thread_id=%s", thread_id)
            continue
        if state_verdict is not None and state is not None:
            await _arm_pending_memory_resume(
                context=context, thread_id=thread_id, state=state, verdict=state_verdict
            )
        for turn_id, event in items:
            if not from_record:
                # Only a turn we closed ourselves needs the state reconciled to
                # "cancelled"; a verdict that came from the state must not be
                # overwritten by the very cleanup that reads it.
                try:
                    await _persist_cancelled_runtime_state(
                        context=context, thread_id=thread_id, turn_id=turn_id, reason="unexpected_shutdown"
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


async def reconcile_terminal_turns(*, context: "CoreLiveContext") -> int:
    """Close turns the runtime already ended but the snapshot still calls active.

    The runtime writes its terminal state (``failed`` / ``cancelled``) before it
    writes the terminal event, so anything that stops it in between leaves the
    durable state terminal and the snapshot ``running`` forever: the session
    keeps showing a spinner and a half-finished tool row, no error is ever
    shown, and the pending guidance is never handed back. A host-memory crash
    during that write is the usual cause (2026-10-10), and nothing repaired it
    short of the next restart.

    Only states the runtime itself declared terminal are reconciled — never a
    guess based on how long a turn has been quiet, which would kill legitimate
    long tools (a 25-minute video generation looks identical from the outside).
    Best-effort: never raises.
    """
    store = context.runtime_state_store
    if store is None:
        return 0
    registry = context.runtime_task_registry
    reconciled = 0
    for thread_id in await _active_thread_ids(context=context):
        try:
            if registry is not None and registry.is_running(thread_id):
                continue  # a live turn owns this thread and will write its own ending
            state = await store.get(thread_id)
            if state is None:
                continue
            verdict = _terminal_verdict(state)
            if verdict is None:
                continue
            await _arm_pending_memory_resume(
                context=context, thread_id=thread_id, state=state, verdict=verdict
            )

            async def write(
                db: AsyncSession,
                *,
                thread_id: str = thread_id,
                verdict: tuple[str, str, str] = verdict,
                expected_run_id: str = str(state.metadata.get("turn_id") or state.run_id or ""),
            ) -> list[tuple[str, AppEventEnvelope]]:
                return await _close_active_turns(
                    db,
                    context=context,
                    thread_id=thread_id,
                    verdict_for=lambda active, _snapshot: (
                        None if expected_run_id and active != expected_run_id else verdict
                    ),
                )

            items = await context.persistence.write(write)
        except BaseException:
            _logger.exception("[live:reconcile] failed thread_id=%s", thread_id)
            continue
        for _turn_id, event in items:
            try:
                await context.hub.publish(event)
            except BaseException:
                pass
        if items:
            reconciled += len(items)
            _logger.warning(
                "[live:reconcile] closed %d item(s) of an already-terminal turn thread_id=%s reason=%s",
                len(items), thread_id, verdict[1],
            )
    return reconciled


async def _active_turn_awaits_user_decision(*, context: "CoreLiveContext", thread_id: str) -> bool:
    """Whether the thread's active turn is durably waiting for the user.

    Only a turn whose runtime state still holds a *resumable* pending approval
    qualifies — that is exactly what ``approval.respond`` continues from. Every
    other leftover (a turn stuck mid-execution, a wait with no answerable
    request, or one whose approval is already past the point of no return)
    stays a crash leftover for the reaper.
    """
    store = context.runtime_state_store
    if store is None:
        return False
    try:
        state = await store.get(thread_id)
    except BaseException:
        _logger.exception("[live:recover] runtime-state read failed thread_id=%s", thread_id)
        return False
    if state is None or str(getattr(state, "loop_state", "") or "") != "wait":
        return False
    run_id = str(getattr(state, "run_id", "") or "")
    if not run_id:
        return False
    metadata = state.metadata if isinstance(getattr(state, "metadata", None), dict) else {}
    pending = metadata.get("pending_approval")
    if not isinstance(pending, dict):
        return False
    if not isinstance(pending.get("tool_call"), dict):
        return False
    # "executing" means the decision was already recorded durably and only the
    # continuation was cut short. approval.respond refuses that state, so
    # keeping it would block the thread with nothing the user could answer.
    if str(pending.get("status") or "waiting") != "waiting":
        return False
    try:
        async with context.session_factory() as db:
            snapshot = await context.persistence.load(db, thread_id)
    except BaseException:
        _logger.exception("[live:recover] snapshot read failed thread_id=%s", thread_id)
        return False
    return latest_active_turn_id(snapshot) == run_id


def _turn_execution_id(snapshot: dict[str, Any], turn_id: str) -> str:
    turn = (snapshot.get("turns") or {}).get(turn_id) or {}
    core_turn = ((snapshot.get("core") or {}).get("turns") or {}).get(turn_id) or {}
    return str(turn.get("run_id") or core_turn.get("run_id") or turn_id)


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
        skill_state_store=(
            hooks.command_skill_state_store()
            if callable(getattr(hooks, "command_skill_state_store", None))
            else None
        ),
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
    arguments: str = "",
    on_event: Callable[[dict[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    if command in actions:
        return await execute_command_action(
            command=command,
            thread_id=thread_id,
            work_root=work_root,
            arguments=arguments,
            handlers=actions,
            on_event=on_event,
        )
    if not context.operations.has("command.execute"):
        raise ValueError(f"Command is not executable as an action: {command}")
    result = await context.operations.execute(
        "command.execute",
        {
            **params,
            "thread_id": thread_id,
            "command": command,
            "arguments": arguments,
            "_on_event": on_event,
        },
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
        raise SessionBusyError(
            reason="active_turn_exists",
            message="A context compaction is already running",
            active_run_id=registry.active_run_id(thread_id) or "",
        )
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
        raise SessionBusyError(
            reason="active_turn_exists",
            message="A context compaction is already running",
            active_run_id=registry.active_run_id(thread_id) or "",
        )
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
            arguments=_command_arguments(params),
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


def _is_stoppable_turn(snapshot: dict[str, Any], turn_id: str) -> bool:
    """Whether a Stop-type request may target this turn.

    A paused turn is not executing, but it is exactly what a single click parks
    and what the long-press confirm has to terminate, so it is stoppable.
    """
    if _is_active_turn(snapshot, turn_id):
        return True
    core = snapshot.get("core")
    turns = core.get("turns") if isinstance(core, dict) else snapshot.get("turns")
    turn = turns.get(turn_id) if isinstance(turns, dict) else None
    return isinstance(turn, dict) and str(turn.get("status") or "") == "paused"


def _is_active_turn(snapshot: dict[str, Any], turn_id: str) -> bool:
    core = snapshot.get("core")
    turns = core.get("turns") if isinstance(core, dict) else snapshot.get("turns")
    turn = turns.get(turn_id) if isinstance(turns, dict) else None
    return isinstance(turn, dict) and str(turn.get("status") or "") in {"running", "waiting", "interrupting"}


def _thread_id_from_params(params: dict[str, Any]) -> str:
    return str(params.get("thread_id") or params.get("threadId") or params.get("session_id") or "").strip()


def _serialized_actor_key(name: str, params: dict[str, Any]) -> str:
    """Return the actor key for commands that mutate shared state.

    Reads and long-running runtime workers intentionally bypass this lock.
    Manual context compaction also bypasses it: it owns a RuntimeTaskRegistry
    slot so turn.cancel can acquire the session actor and cancel the real task.
    Project operations use their own key when no session id is available so a
    project mutation cannot race another live connection's project command.
    """

    normalized = str(name or "").strip()
    if normalized == "command.execute" and normalize_command_name(params.get("command")) == "compact":
        return ""
    if normalized not in SERIALIZED_SESSION_OPERATIONS and not (
        normalized.startswith("session.") or normalized.startswith("project.")
    ):
        return ""
    thread_id = _thread_id_from_params(params)
    if thread_id:
        return f"session:{thread_id}"
    project_id = str(params.get("project_id") or params.get("projectId") or "").strip()
    if project_id:
        return f"project:{project_id}"
    return ""


def _command_arguments(params: dict[str, Any]) -> str:
    value = params.get("arguments")
    if value is None:
        value = params.get("args")
    return str(value or "").strip()


def _command_kind(definition: dict[str, Any]) -> str:
    raw_kind = str(definition.get("kind") or "").strip().lower()
    if raw_kind in {"action", "skill"}:
        return raw_kind
    # Compatibility for command catalogs produced before the explicit kind
    # field was introduced.
    return "skill" if definition.get("action") in {"insert_token", "expand_on_send"} else "action"


def _int_param(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _expected_revision(params: dict[str, Any]) -> int | None:
    """Parse the optional CAS revision without treating zero as absent."""

    marker = object()
    value = params.get("expected_revision", marker)
    if value is marker:
        value = params.get("expectedRevision", marker)
    if value is marker or value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("expected_revision must be a non-negative integer")
    try:
        revision = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("expected_revision must be a non-negative integer") from exc
    if revision < 0:
        raise ValueError("expected_revision must be a non-negative integer")
    return revision


def _include_snapshot_param(params: dict[str, Any]) -> bool:
    """Mutation responses embed the full snapshot unless the caller opts out.

    The desktop UI opts out everywhere: the response's event list already
    carries the state change and the revision, so a 48MB snapshot parse per
    send/guide on large threads was pure latency (measured 0.6-1.6s round
    trips on a 509-item session). CLI/mobile callers keep the legacy default.
    """
    return params.get("include_snapshot") is not False


async def _load_snapshot_outside_write_lock(context: CoreLiveContext, thread_id: str) -> dict[str, Any]:
    """Assemble the full snapshot after the write transaction committed.

    Full assembly scans every item row; doing it inside the global SQLite
    write lock stalled concurrent sends/streaming for its whole duration.
    Reading after commit is monotonic for clients (revision only moves
    forward), so the tiny race window is harmless.
    """
    async with context.session_factory() as db:
        return await context.persistence.load(db, thread_id)


_CORE_LIVE_OPERATION_EXECUTORS = {
    "sync.start": handle_sync_start_operation,
    "thread.start": handle_thread_start_operation,
    "thread.read": handle_thread_read_operation,
    "thread.resume": handle_thread_resume_operation,
    "thread.history": handle_thread_history_operation,
    "thread.outline": handle_thread_outline_operation,
    "turn.start": handle_turn_start_operation,
    "turn.resume": handle_turn_resume_operation,
    "turn.pause": handle_turn_pause_operation,
    # ``turn.cancel`` keeps its terminal meaning for clients that still send it
    # (mobile); the desktop sends ``turn.terminate`` for the explicit stop.
    "turn.cancel": handle_turn_cancel_operation,
    "turn.terminate": handle_turn_terminate_operation,
    "turn.force_reset": handle_turn_force_reset_operation,
    "turn.steer": handle_turn_steer_operation,
    "approval.respond": handle_approval_respond_operation,
    "session.permissions.set": handle_session_permissions_set_operation,
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
    "process.list": handle_process_list_operation,
    "process.kill": handle_process_kill_operation,
    "process.forget": handle_process_forget_operation,
    "process.log": handle_process_log_operation,
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
    "handle_session_permissions_set_operation",
    "handle_thread_read_operation",
    "handle_thread_history_operation",
    "handle_thread_outline_operation",
    "handle_thread_start_operation",
    "handle_thread_resume_operation",
    "handle_sync_start_operation",
    "handle_turn_cancel_operation",
    "handle_turn_force_reset_operation",
    "handle_turn_start_operation",
    "handle_turn_resume_operation",
    "handle_turn_steer_operation",
    "handle_process_list_operation",
    "handle_process_kill_operation",
    "handle_process_forget_operation",
    "handle_process_log_operation",
]
