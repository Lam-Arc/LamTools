from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)

from fastapi import HTTPException
from lamtools_core.app.project_store import ActiveProjectSessionsError
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError

from app.config import settings
from app.database import async_session
from app.models.session import WriterSession
from app.services.attachment_service import (
    get_attachment_response,
    list_session_attachment_responses,
    open_attachment_response,
    preview_attachment_response,
)
from app.services.app_settings import get_app_setting_value, update_app_setting_value
from app.services.agent_branch_service import (
    abandon_agent_branch_response,
    get_agent_branch_diff_response,
    list_agent_branch_responses,
    merge_agent_branch_response,
)
from app.services.checkpoint_service import (
    claim_checkpoint_create,
    claim_checkpoint_restore,
    execute_checkpoint_create,
    execute_checkpoint_restore,
    list_session_checkpoint_responses,
    persist_checkpoint_create,
    persist_checkpoint_restore,
)
from app.services.commit_review_service import (
    WorktreeChangedError,
    claim_commit_review_approval,
    decide_commit_review_response,
    execute_commit_review_approval,
    get_commit_review_response,
    persist_commit_review_approval,
)
from app.services.command_service import execute_writer_command, normalize_writer_command_name, writer_command_catalog
from app.services.composer_input_service import prepare_composer_input
from app.services.config_read import (
    list_adapter_profile_configs,
    resolved_config_response,
)
from app.services.config_write import (
    create_model_config,
    create_provider_config,
    delete_model_config,
    delete_provider_config,
    import_env_provider_model_config,
    update_model_config,
    update_provider_config,
)
from app.services.project_management import (
    create_writer_project_response,
    create_writer_project_session,
    delete_writer_project,
    get_writer_project_response,
    list_project_session_summaries,
    list_writer_project_responses,
    read_project_agents_md,
    update_writer_project,
    write_project_agents_md,
)
from app.services.project_directory_picker import (
    ProjectDirectoryPickerUnavailable,
    pick_project_directory,
)
from app.services.runtime_capabilities import runtime_capabilities_response
from app.services.session_compaction_service import (
    apply_session_context_compaction,
    execute_session_context_compaction,
    prepare_session_context_compaction,
)
from app.services.session_management import (
    create_writer_session,
    delete_writer_session,
    get_writer_session_response,
    update_writer_session,
)
from app.services.session_git_queries import (
    get_git_graph_response,
    get_session_changes_response,
    open_session_change_file_response,
)
from app.services.session_fork_service import fork_session_response
from app.services.session_rollback_service import (
    claim_session_rollback,
    execute_session_rollback,
    persist_session_rollback,
)
from app.services.session_undo_service import undo_session_changes_response, undo_session_file_change_response
from app.services.session_projection import session_response_projected
from app.services.subagent_config import delete_project_subagent_config, upsert_project_subagent_config
from lamtools_core.app import (
    OperationCatalog,
    OperationRequest,
    OperationResult,
    build_member_operation_catalog,
    build_core_plugin_operation_catalog,
    build_core_approval_operation,
    normalize_operation_name,
)
from lamtools_core.config import build_shared_config_operation_catalog
from lamtools_core.context_compaction import ContextCompactionError
from lamtools_core.event import RunItemEvent
from .artifacts import open_artifact, read_artifact
from .event_store import append_event_and_load_snapshot, append_run_item_event_and_apply_snapshot
from .persistence import writer_persistence_host
from .ledger import list_events_after
from .protocol import AppendEventInput, JsonRpcRequest, WriterAppEventEnvelope, rpc_error, rpc_result
from .snapshot import load_snapshot


OperationRpcHandler = Callable[[JsonRpcRequest], Awaitable[None]]

INVALID_REQUEST = -32600
_SQLITE_LOCKED_MESSAGE = "数据库正忙，请稍后重试"
_SHARED_CONFIG_SESSION_REQUIRED_MESSAGE = "shared config session is required"
_SQLITE_LOCK_RETRY_DELAYS = (0.05, 0.15)
class _MissingSharedConfigSession(RuntimeError):
    pass


class _MissingSharedConfigSessionContext:
    async def __aenter__(self) -> Any:
        raise _MissingSharedConfigSession(_SHARED_CONFIG_SESSION_REQUIRED_MESSAGE)

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None


@dataclass
class WriterOperationOutcome:
    response: dict[str, Any]
    notify_events: list[WriterAppEventEnvelope] = field(default_factory=list)
    publish_events: list[WriterAppEventEnvelope] = field(default_factory=list)


def _is_sqlite_locked_error(exc: BaseException) -> bool:
    if not isinstance(exc, OperationalError):
        return False
    message = str(exc).lower()
    return "database is locked" in message or "database table is locked" in message


async def _retry_sqlite_locked_write(
    session_factory: Any,
    write: Callable[[Any], Awaitable[Any]],
) -> Any:
    for attempt in range(len(_SQLITE_LOCK_RETRY_DELAYS) + 1):
        try:
            async with session_factory() as db:
                return await write(db)
        except OperationalError as exc:
            if not _is_sqlite_locked_error(exc) or attempt >= len(_SQLITE_LOCK_RETRY_DELAYS):
                raise
            await asyncio.sleep(_SQLITE_LOCK_RETRY_DELAYS[attempt])
    raise RuntimeError("SQLite write retry exhausted")


def _require_config_session_factory(config_session_factory: Any | None) -> Any | None:
    return config_session_factory


def _shared_config_required_outcome(request_id: int | str | None) -> WriterOperationOutcome:
    return WriterOperationOutcome(
        response=rpc_error(request_id, code=INVALID_REQUEST, message=_SHARED_CONFIG_SESSION_REQUIRED_MESSAGE)
    )


async def _with_writer_and_config_sessions(
    session_factory: Any,
    config_session_factory: Any | None,
    action: Callable[[Any, Any], Awaitable[Any]],
) -> Any:
    if config_session_factory is None:
        raise ValueError(_SHARED_CONFIG_SESSION_REQUIRED_MESSAGE)
    async with session_factory() as db:
        async with config_session_factory() as config_db:
            return await action(db, config_db)


async def _retry_sqlite_locked_config_write(
    session_factory: Any,
    config_session_factory: Any | None,
    write: Callable[[Any, Any], Awaitable[Any]],
) -> Any:
    for attempt in range(len(_SQLITE_LOCK_RETRY_DELAYS) + 1):
        try:
            return await _with_writer_and_config_sessions(session_factory, config_session_factory, write)
        except OperationalError as exc:
            if not _is_sqlite_locked_error(exc) or attempt >= len(_SQLITE_LOCK_RETRY_DELAYS):
                raise
            await asyncio.sleep(_SQLITE_LOCK_RETRY_DELAYS[attempt])
    raise RuntimeError("SQLite write retry exhausted")


def _sqlite_locked_outcome(request_id: int | str | None) -> WriterOperationOutcome:
    return WriterOperationOutcome(
        response=rpc_error(request_id, code=INVALID_REQUEST, message=_SQLITE_LOCKED_MESSAGE)
    )


def _shared_config_operation_catalog(config_session_factory: Any) -> OperationCatalog:
    return build_shared_config_operation_catalog(
        config_session_factory,
        locked_message=_SQLITE_LOCKED_MESSAGE,
        create_provider=create_provider_config,
        update_provider=update_provider_config,
        delete_provider=delete_provider_config,
        create_model=create_model_config,
        update_model=update_model_config,
        delete_model=delete_model_config,
    )


async def _handle_shared_config_operation(
    *,
    request_id: int | str | None,
    operation: str,
    params: dict[str, Any],
    config_session_factory: Any | None,
) -> WriterOperationOutcome:
    config_factory = _require_config_session_factory(config_session_factory)
    session_factory = config_factory or (lambda: _MissingSharedConfigSessionContext())
    try:
        result = await _shared_config_operation_catalog(session_factory).execute(operation, params)
    except _MissingSharedConfigSession:
        return _shared_config_required_outcome(request_id)
    if result.status != "ok":
        return WriterOperationOutcome(
            response=rpc_error(
                request_id,
                code=INVALID_REQUEST,
                message=str(result.payload.get("error") or "shared config operation failed"),
            )
        )
    return WriterOperationOutcome(response=rpc_result(request_id, result.payload))

OPERATION_ALIASES = {
    "turn/interrupt": "turn.cancel",
    "turn.interrupt": "turn.cancel",
}


def operation_name(method: str) -> str:
    return normalize_operation_name(method, aliases=OPERATION_ALIASES)


WRITER_OVERLAY_OPERATION_NAMES: tuple[str, ...] = (
    "project.directory.pick",
    "attachment.list",
    "attachment.get",
    "attachment.preview",
    "attachment.open",
    "session.create",
    "session.get",
    "session.list",
    "session.update",
    "session.delete",
    "session.fork",
    "session.git_graph.get",
    "session.changes.get",
    "session.checkpoints.list",
    "session.checkpoint.create",
    "session.checkpoint.restore",
    "session.commit_review.get",
    "session.commit_review.decide",
    "session.agent_branches.list",
    "session.agent_branch.diff",
    "session.agent_branch.merge",
    "session.agent_branch.abandon",
    "session.rollback_turn",
    "session.changes.undo",
    "session.change_file.open",
    "session.change_file.undo",
)


def build_writer_operation_catalog(
    *,
    project_directory_pick: OperationRpcHandler,
    attachment_list: OperationRpcHandler,
    attachment_get: OperationRpcHandler,
    attachment_preview: OperationRpcHandler,
    attachment_open: OperationRpcHandler,
    session_create: OperationRpcHandler,
    session_get: OperationRpcHandler,
    session_list: OperationRpcHandler,
    session_update: OperationRpcHandler,
    session_delete: OperationRpcHandler,
    session_fork: OperationRpcHandler,
    session_git_graph: OperationRpcHandler,
    session_changes_get: OperationRpcHandler,
    session_checkpoints_list: OperationRpcHandler,
    session_checkpoint_create: OperationRpcHandler,
    session_checkpoint_restore: OperationRpcHandler,
    session_commit_review_get: OperationRpcHandler,
    session_commit_review_decide: OperationRpcHandler,
    session_agent_branches_list: OperationRpcHandler,
    session_agent_branch_diff: OperationRpcHandler,
    session_agent_branch_merge: OperationRpcHandler,
    session_agent_branch_abandon: OperationRpcHandler,
    session_rollback_turn: OperationRpcHandler,
    session_changes_undo: OperationRpcHandler,
    session_change_file_open: OperationRpcHandler,
    session_change_file_undo: OperationRpcHandler,
    core_handlers: Mapping[str, Any],
) -> OperationCatalog:
    writer_overlay_handlers = {
        "project.directory.pick": _handler(project_directory_pick),
        "attachment.list": _handler(attachment_list),
        "attachment.get": _handler(attachment_get),
        "attachment.preview": _handler(attachment_preview),
        "attachment.open": _handler(attachment_open),
        "session.create": _handler(session_create),
        "session.get": _handler(session_get),
        "session.list": _handler(session_list),
        "session.update": _handler(session_update),
        "session.delete": _handler(session_delete),
        "session.fork": _handler(session_fork),
        "session.git_graph.get": _handler(session_git_graph),
        "session.changes.get": _handler(session_changes_get),
        "session.checkpoints.list": _handler(session_checkpoints_list),
        "session.checkpoint.create": _handler(session_checkpoint_create),
        "session.checkpoint.restore": _handler(session_checkpoint_restore),
        "session.commit_review.get": _handler(session_commit_review_get),
        "session.commit_review.decide": _handler(session_commit_review_decide),
        "session.agent_branches.list": _handler(session_agent_branches_list),
        "session.agent_branch.diff": _handler(session_agent_branch_diff),
        "session.agent_branch.merge": _handler(session_agent_branch_merge),
        "session.agent_branch.abandon": _handler(session_agent_branch_abandon),
        "session.rollback_turn": _handler(session_rollback_turn),
        "session.changes.undo": _handler(session_changes_undo),
        "session.change_file.open": _handler(session_change_file_open),
        "session.change_file.undo": _handler(session_change_file_undo),
    }
    return build_member_operation_catalog(
        core_handlers=core_handlers,
        overlay_names=WRITER_OVERLAY_OPERATION_NAMES,
        overlay_handlers=writer_overlay_handlers,
    )


def build_writer_core_operation_adapter_catalog(
    *,
    session_factory: Any,
    config_session_factory: Any,
    runtime: Any,
    emit_event: Callable[[WriterAppEventEnvelope], Awaitable[None]],
) -> OperationCatalog:
    """Inject Writer storage and product behavior behind Core-owned operations."""

    catalog = OperationCatalog()
    shared_config = _shared_config_operation_catalog(config_session_factory)
    for name in shared_config.list():
        async def shared_config_handler(request: OperationRequest, operation: str = name) -> OperationResult:
            return await shared_config.execute(operation, request.payload, metadata=request.metadata)

        catalog.register(name, shared_config_handler)

    async def adapt(
        request: OperationRequest,
        handler: Callable[..., Awaitable[WriterOperationOutcome]],
        **kwargs: Any,
    ) -> OperationResult:
        outcome = await handler(request_id=None, params=request.payload, **kwargs)
        response = outcome.response
        if "error" in response:
            error = response.get("error") if isinstance(response.get("error"), dict) else {}
            payload = {"error": str(error.get("message") or "operation failed")}
            if error.get("data") is not None:
                payload["data"] = error["data"]
            return OperationResult(name=request.name, status="error", payload=payload)
        result = response.get("result")
        return OperationResult(
            name=request.name,
            payload=dict(result) if isinstance(result, dict) else {"result": result},
        )

    adapters: dict[str, Callable[[OperationRequest], Awaitable[OperationResult]]] = {
        "approval.respond": build_core_approval_operation(runtime.approval_coordinator),
        "artifact.read": lambda request: adapt(
            request, handle_artifact_read_operation, session_factory=session_factory,
        ),
        "artifact.open": lambda request: adapt(
            request, handle_artifact_open_operation, session_factory=session_factory,
        ),
        "command.catalog": lambda request: adapt(request, handle_command_catalog_operation),
        "command.execute": lambda request: adapt(
            request,
            handle_command_execute_operation,
            session_factory=session_factory,
            writer_service=runtime.writer_service_or_none(),
            emit_event=emit_event,
        ),
        "settings.get": lambda request: adapt(
            request,
            handle_settings_get_operation,
            session_factory=session_factory,
            config_session_factory=config_session_factory,
        ),
        "settings.update": lambda request: adapt(
            request,
            handle_settings_update_operation,
            session_factory=session_factory,
            config_session_factory=config_session_factory,
        ),
        "config.import_env": lambda request: adapt(
            request, handle_config_import_env_operation, config_session_factory=config_session_factory,
        ),
        "config.resolved.get": lambda request: adapt(
            request, handle_config_resolved_get_operation, config_session_factory=config_session_factory,
        ),
        "config.adapter_profiles.list": lambda request: adapt(
            request, handle_config_adapter_profiles_list_operation,
        ),
        "config.runtime_capabilities.get": lambda request: adapt(
            request,
            handle_config_runtime_capabilities_get_operation,
            session_factory=session_factory,
            config_session_factory=config_session_factory,
        ),
        "config.subagent.upsert": lambda request: adapt(
            request, handle_config_subagent_upsert_operation, session_factory=session_factory,
        ),
        "config.subagent.delete": lambda request: adapt(
            request, handle_config_subagent_delete_operation,
        ),
        "project.create": lambda request: adapt(
            request, handle_project_create_operation, session_factory=session_factory,
        ),
        "project.get": lambda request: adapt(
            request, handle_project_get_operation, session_factory=session_factory,
        ),
        "project.list": lambda request: adapt(
            request, handle_project_list_operation, session_factory=session_factory,
        ),
        "project.update": lambda request: adapt(
            request, handle_project_update_operation, session_factory=session_factory,
        ),
        "project.delete": lambda request: adapt(
            request, handle_project_delete_operation, session_factory=session_factory,
        ),
        "project.sessions.create": lambda request: adapt(
            request, handle_project_session_create_operation, session_factory=session_factory,
        ),
        "project.agents_md.get": lambda request: adapt(
            request, handle_project_agents_md_get_operation, session_factory=session_factory,
        ),
        "project.agents_md.update": lambda request: adapt(
            request, handle_project_agents_md_update_operation, session_factory=session_factory,
        ),
        "project.sessions.list": lambda request: adapt(
            request, handle_project_sessions_list_operation, session_factory=session_factory,
        ),
    }
    for operation in ("plugin.list", "plugin.enable", "plugin.disable", "hook.list", "hook.trust"):
        adapters[operation] = lambda request, name=operation: adapt(
            request, handle_plugin_catalog_operation, operation=name,
        )
    for name, handler in adapters.items():
        catalog.register(name, handler)
    return catalog


async def handle_session_list_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    limit = _bounded_int(params.get("limit"), default=50, minimum=1, maximum=200)
    offset = _bounded_int(params.get("offset"), default=0, minimum=0, maximum=100000)
    async with session_factory() as db:
        result = await db.execute(
            select(WriterSession)
            .order_by(WriterSession.updated_at.desc())
            .offset(offset)
            .limit(limit)
        )
        sessions = result.scalars().all()
        rows = [await session_response_projected(db, session) for session in sessions]
    return WriterOperationOutcome(response=rpc_result(request_id, {"sessions": rows}))


async def handle_session_create_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    if params.get("project_id") or params.get("projectId"):
        return WriterOperationOutcome(response=rpc_error(
            request_id,
            code=INVALID_REQUEST,
            message="Use project.sessions.create for project-owned sessions",
        ))
    persistence = writer_persistence_host(session_factory)
    async def write(db):
        return await create_writer_session(
            db,
            title=str(params.get("title") or "New Session"),
            work_root=str(params.get("work_root") or params.get("workRoot") or ""),
            mode=str(params.get("mode") or "EXECUTE"),
        )
    session = await persistence.write(write)
    return WriterOperationOutcome(response=rpc_result(request_id, {"session": session}))


async def handle_session_get_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    session_id = str(params.get("session_id") or params.get("sessionId") or params.get("id") or "")
    if not session_id:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message="session_id is required"))
    try:
        async with session_factory() as db:
            session = await get_writer_session_response(db, session_id)
    except (LookupError, ValueError) as exc:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    return WriterOperationOutcome(response=rpc_result(request_id, {"session": session}))


async def handle_session_update_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    session_id = str(params.get("session_id") or params.get("sessionId") or params.get("id") or "")
    if not session_id:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message="session_id is required"))
    work_root = params["work_root"] if "work_root" in params else params.get("workRoot")
    project_id = params["project_id"] if "project_id" in params else params.get("projectId")
    update_data = {
        key: value
        for key, value in {
            "title": params.get("title"),
            "mode": params.get("mode"),
            "work_root": work_root,
            "project_id": project_id,
        }.items()
        if value is not None
    }
    try:
        persistence = writer_persistence_host(session_factory)
        session = await persistence.write(
            lambda db: update_writer_session(db, session_id, update_data)
        )
    except (LookupError, ValueError) as exc:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    return WriterOperationOutcome(response=rpc_result(request_id, {"session": session}))


async def handle_session_delete_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    session_id = str(params.get("session_id") or params.get("sessionId") or params.get("id") or "")
    if not session_id:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message="session_id is required"))
    try:
        persistence = writer_persistence_host(session_factory)
        await persistence.write(lambda db: delete_writer_session(db, session_id))
    except (LookupError, ValueError) as exc:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    return WriterOperationOutcome(response=rpc_result(request_id, {"ok": True}))


async def handle_session_fork_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    session_id = str(params.get("session_id") or params.get("sessionId") or params.get("id") or "")
    if not session_id:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message="session_id is required"))
    after_turn_value = params.get("after_turn_id") if "after_turn_id" in params else params.get("afterTurnId")
    after_turn_id = str(after_turn_value) if after_turn_value else None
    title_value = params.get("title")
    title = str(title_value) if title_value else None
    isolated_worktree = bool(params.get("isolated_worktree") or params.get("isolatedWorktree") or False)
    try:
        persistence = writer_persistence_host(session_factory)
        async def write(db):
            return await fork_session_response(
                db,
                session_id,
                after_turn_id=after_turn_id,
                title=title,
                isolated_worktree=isolated_worktree,
            )
        session = await persistence.write(write)
    except (LookupError, ValueError) as exc:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    return WriterOperationOutcome(response=rpc_result(request_id, {"session": session}))


async def handle_session_git_graph_get_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    session_id = str(params.get("session_id") or params.get("sessionId") or params.get("id") or "")
    if not session_id:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message="session_id is required"))
    try:
        async with session_factory() as db:
            graph = await get_git_graph_response(db, session_id)
    except (LookupError, ValueError) as exc:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    return WriterOperationOutcome(response=rpc_result(request_id, {"graph": graph}))


async def handle_session_changes_get_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    session_id = str(params.get("session_id") or params.get("sessionId") or params.get("id") or "")
    if not session_id:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message="session_id is required"))
    try:
        async with session_factory() as db:
            changes = await get_session_changes_response(db, session_id)
    except (LookupError, ValueError) as exc:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    return WriterOperationOutcome(response=rpc_result(request_id, {"changes": changes}))


async def handle_session_checkpoints_list_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    session_id = str(params.get("session_id") or params.get("sessionId") or params.get("id") or "")
    if not session_id:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message="session_id is required"))
    try:
        async with session_factory() as db:
            checkpoints = await list_session_checkpoint_responses(db, session_id)
    except LookupError as exc:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    return WriterOperationOutcome(response=rpc_result(request_id, {"checkpoints": checkpoints}))


async def handle_session_checkpoint_create_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    session_id = str(params.get("session_id") or params.get("sessionId") or params.get("id") or "")
    if not session_id:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message="session_id is required"))
    try:
        persistence = writer_persistence_host(session_factory)
        claim = await persistence.write(lambda db: claim_checkpoint_create(
            db,
            session_id,
            label=str(params.get("label") or "checkpoint"),
            reason=str(params.get("reason") or "手动保存检查点"),
            allow_empty=bool(params.get("allow_empty") if "allow_empty" in params else params.get("allowEmpty")),
        ))
        record = await execute_checkpoint_create(claim)
        checkpoint = await persistence.write(lambda db: persist_checkpoint_create(db, claim, record))
    except (LookupError, ValueError) as exc:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    if checkpoint is None:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message="No checkpoint was created"))
    return WriterOperationOutcome(response=rpc_result(request_id, {"checkpoint": checkpoint}))


async def handle_session_checkpoint_restore_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    session_id = str(params.get("session_id") or params.get("sessionId") or params.get("id") or "")
    commit = str(params.get("commit") or "")
    if not session_id or not commit:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message="session_id and commit are required"))
    try:
        persistence = writer_persistence_host(session_factory)
        claim = await persistence.write(lambda db: claim_checkpoint_restore(db, session_id, commit=commit))
        execution = await execute_checkpoint_restore(claim)
        result = await persistence.write(lambda db: persist_checkpoint_restore(db, claim, execution))
    except (LookupError, ValueError) as exc:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    return WriterOperationOutcome(response=rpc_result(request_id, result))


async def handle_session_commit_review_get_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    session_id = str(params.get("session_id") or params.get("sessionId") or params.get("id") or "")
    if not session_id:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message="session_id is required"))
    try:
        async with session_factory() as db:
            review = await get_commit_review_response(db, session_id)
    except LookupError as exc:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    return WriterOperationOutcome(response=rpc_result(request_id, {"review": review}))


async def handle_session_commit_review_decide_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    session_id = str(params.get("session_id") or params.get("sessionId") or params.get("id") or "")
    action = str(params.get("action") or "")
    if not session_id or not action:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message="session_id and action are required"))
    try:
        persistence = writer_persistence_host(session_factory)
        feedback = str(params.get("feedback") or "")
        commit_message = (
            str(params.get("commit_message") or params.get("commitMessage"))
            if params.get("commit_message") or params.get("commitMessage")
            else None
        )
        if action.strip().lower() == "approve":
            claim = await persistence.write(lambda db: claim_commit_review_approval(
                db,
                session_id,
                feedback=feedback,
                commit_message=commit_message,
            ))
            committed = await execute_commit_review_approval(claim)
            review = await persistence.write(lambda db: persist_commit_review_approval(db, claim, committed))
        else:
            review = await persistence.write(lambda db: decide_commit_review_response(
                db,
                session_id,
                action=action,
                feedback=feedback,
                commit_message=commit_message,
            ))
    except (LookupError, ValueError, WorktreeChangedError) as exc:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    return WriterOperationOutcome(response=rpc_result(request_id, {"review": review}))


async def handle_session_agent_branches_list_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    session_id = str(params.get("session_id") or params.get("sessionId") or params.get("id") or "")
    if not session_id:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message="session_id is required"))
    try:
        async with session_factory() as db:
            branches = await list_agent_branch_responses(db, session_id)
    except LookupError as exc:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    return WriterOperationOutcome(response=rpc_result(request_id, {"branches": branches}))


async def handle_session_agent_branch_diff_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    session_id = str(params.get("session_id") or params.get("sessionId") or params.get("id") or "")
    branch = str(params.get("branch") or "")
    if not session_id or not branch:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message="session_id and branch are required"))
    try:
        async with session_factory() as db:
            diff = await get_agent_branch_diff_response(db, session_id, branch)
    except (LookupError, ValueError) as exc:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    return WriterOperationOutcome(response=rpc_result(request_id, diff))


async def handle_session_agent_branch_merge_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    session_id = str(params.get("session_id") or params.get("sessionId") or params.get("id") or "")
    branch = str(params.get("branch") or "")
    if not session_id or not branch:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message="session_id and branch are required"))
    try:
        async with session_factory() as db:
            result = await merge_agent_branch_response(db, session_id, branch)
    except (LookupError, ValueError, RuntimeError) as exc:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    return WriterOperationOutcome(response=rpc_result(request_id, result))


async def handle_session_agent_branch_abandon_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    session_id = str(params.get("session_id") or params.get("sessionId") or params.get("id") or "")
    branch = str(params.get("branch") or "")
    if not session_id or not branch:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message="session_id and branch are required"))
    try:
        async with session_factory() as db:
            result = await abandon_agent_branch_response(db, session_id, branch)
    except (LookupError, ValueError) as exc:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    return WriterOperationOutcome(response=rpc_result(request_id, result))


async def handle_session_rollback_turn_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    session_id = str(params.get("session_id") or params.get("sessionId") or params.get("id") or "")
    if not session_id:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message="session_id is required"))
    turn_id_value = params.get("turn_id") if "turn_id" in params else params.get("turnId")
    turn_id = str(turn_id_value) if turn_id_value else None
    reason = str(params.get("reason") or "")
    try:
        persistence = writer_persistence_host(session_factory)
        claim = await persistence.write(lambda db: claim_session_rollback(
            db,
            session_id,
            turn_id=turn_id,
            reason=reason,
        ))
        restore = await execute_session_rollback(claim)
        async def write(db):
            result = await persist_session_rollback(db, claim, restore)
            event, snapshot = await append_event_and_load_snapshot(
                db,
                AppendEventInput(
                    thread_id=session_id,
                    turn_id=result.get("target_turn_id"),
                    method="session/rollback_turn",
                    payload={
                        "type": "session",
                        "status": "idle",
                        "target_turn_id": result.get("target_turn_id"),
                        "rolled_back_turn_ids": result.get("rolled_back_turn_ids", []),
                        "restore": result.get("restore"),
                        "reason": reason,
                    },
                ),
            )
            return result, event, snapshot
        result, event, snapshot = await persistence.write(write)
    except (LookupError, ValueError) as exc:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    return WriterOperationOutcome(
        response=rpc_result(request_id, {**result, "event": event.model_dump(mode="json"), "snapshot": snapshot}),
        publish_events=[event],
    )


async def handle_session_changes_undo_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    session_id = str(params.get("session_id") or params.get("sessionId") or params.get("id") or "")
    if not session_id:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message="session_id is required"))
    try:
        async with session_factory() as db:
            result = await undo_session_changes_response(db, session_id)
    except (LookupError, ValueError) as exc:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    return WriterOperationOutcome(response=rpc_result(request_id, result))


async def handle_session_change_file_undo_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    session_id = str(params.get("session_id") or params.get("sessionId") or params.get("id") or "")
    path = str(params.get("path") or "")
    if not session_id or not path:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message="session_id and path are required"))
    try:
        async with session_factory() as db:
            result = await undo_session_file_change_response(db, session_id, path)
    except (LookupError, ValueError) as exc:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    return WriterOperationOutcome(response=rpc_result(request_id, result))


async def handle_session_change_file_open_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
    opener: Any = None,
    fallback_opener: Any = None,
) -> WriterOperationOutcome:
    session_id = str(params.get("session_id") or params.get("sessionId") or params.get("id") or "")
    path = str(params.get("path") or "")
    if not session_id or not path:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message="session_id and path are required"))
    try:
        async with session_factory() as db:
            kwargs: dict[str, Any] = {}
            if opener is not None:
                kwargs["opener"] = opener
            if fallback_opener is not None:
                kwargs["fallback_opener"] = fallback_opener
            result = await open_session_change_file_response(db, session_id, path, **kwargs)
    except (LookupError, ValueError, FileNotFoundError, OSError) as exc:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    return WriterOperationOutcome(response=rpc_result(request_id, result))


async def handle_project_list_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    limit = _bounded_int(params.get("limit"), default=50, minimum=1, maximum=200)
    offset = _bounded_int(params.get("offset"), default=0, minimum=0, maximum=100000)
    async with session_factory() as db:
        projects = await list_writer_project_responses(db, limit=limit, offset=offset)
    return WriterOperationOutcome(response=rpc_result(request_id, {"projects": projects}))


async def handle_project_create_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    try:
        persistence = writer_persistence_host(session_factory)
        async def create_project(db):
            project = await create_writer_project_response(
                db,
                work_root=str(params.get("work_root") or params.get("workRoot") or ""),
                name=params.get("name"),
            )
            sessions = await list_project_session_summaries(db, project["id"], limit=1)
            session = sessions[0] if sessions else await create_writer_session(
                db,
                title=project["name"],
                work_root=project["work_root"],
                project_id=project["id"],
            )
            return project, session

        project, session = await persistence.write(create_project)
    except HTTPException as exc:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc.detail)))
    return WriterOperationOutcome(response=rpc_result(request_id, {"project": project, "session": session}))


async def handle_project_directory_pick_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    directory_picker: Callable[[], str] = pick_project_directory,
) -> WriterOperationOutcome:
    _ = params
    try:
        selected = await asyncio.to_thread(directory_picker)
    except ProjectDirectoryPickerUnavailable as exc:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    except OSError as exc:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    return WriterOperationOutcome(response=rpc_result(request_id, {"path": selected}))


async def handle_project_get_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    project_id = str(params.get("project_id") or params.get("projectId") or params.get("id") or "")
    if not project_id:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message="project_id is required"))
    try:
        async with session_factory() as db:
            project = await get_writer_project_response(db, project_id)
    except LookupError as exc:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    return WriterOperationOutcome(response=rpc_result(request_id, {"project": project}))


async def handle_project_update_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    project_id = str(params.get("project_id") or params.get("projectId") or params.get("id") or "")
    if not project_id:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message="project_id is required"))
    work_root = params["work_root"] if "work_root" in params else params.get("workRoot")
    update_data = {
        key: value
        for key, value in {
            "name": params.get("name"),
            "work_root": work_root,
            "agents_md": params.get("agents_md") if "agents_md" in params else params.get("agentsMd"),
            "config": params.get("config"),
        }.items()
        if value is not None
    }
    try:
        persistence = writer_persistence_host(session_factory)
        project = await persistence.write(lambda db: update_writer_project(db, project_id, update_data))
    except LookupError as exc:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    return WriterOperationOutcome(response=rpc_result(request_id, {"project": project}))


async def handle_project_delete_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    project_id = str(params.get("project_id") or params.get("projectId") or params.get("id") or "")
    if not project_id:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message="project_id is required"))
    try:
        persistence = writer_persistence_host(session_factory)
        await persistence.write(lambda db: delete_writer_project(db, project_id))
    except ActiveProjectSessionsError as exc:
        return WriterOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc), data={"code": 409})
        )
    except LookupError as exc:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    return WriterOperationOutcome(response=rpc_result(request_id, {"deleted": True}))


async def handle_project_session_create_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    project_id = str(params.get("project_id") or params.get("projectId") or params.get("id") or "")
    if not project_id:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message="project_id is required"))
    try:
        persistence = writer_persistence_host(session_factory)
        session = await persistence.write(lambda db: create_writer_project_session(
            db,
            project_id,
            title=str(params.get("title") or "New Session"),
            mode=str(params.get("mode") or "EXECUTE"),
        ))
    except LookupError as exc:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    return WriterOperationOutcome(response=rpc_result(request_id, {"session": session}))


async def handle_project_agents_md_get_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    project_id = str(params.get("project_id") or params.get("projectId") or params.get("id") or "")
    if not project_id:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message="project_id is required"))
    try:
        async with session_factory() as db:
            result = await read_project_agents_md(db, project_id)
    except (LookupError, ValueError) as exc:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    return WriterOperationOutcome(response=rpc_result(request_id, {"agents_md": result}))


async def handle_project_agents_md_update_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    project_id = str(params.get("project_id") or params.get("projectId") or params.get("id") or "")
    content = params.get("content")
    if not project_id:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message="project_id is required"))
    if not isinstance(content, str):
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message="content is required"))
    try:
        persistence = writer_persistence_host(session_factory)
        result = await persistence.write(lambda db: write_project_agents_md(db, project_id, content))
    except (LookupError, ValueError) as exc:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    return WriterOperationOutcome(response=rpc_result(request_id, {"agents_md": result}))


async def handle_project_sessions_list_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    project_id = str(params.get("project_id") or params.get("projectId") or params.get("id") or "")
    if not project_id:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message="project_id is required"))
    limit = _bounded_int(params.get("limit"), default=50, minimum=1, maximum=200)
    offset = _bounded_int(params.get("offset"), default=0, minimum=0, maximum=100000)
    try:
        async with session_factory() as db:
            sessions = await list_project_session_summaries(
                db,
                project_id,
                limit=limit,
                offset=offset,
            )
    except LookupError as exc:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    return WriterOperationOutcome(response=rpc_result(request_id, {"sessions": sessions}))


async def handle_attachment_list_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    session_id = str(params.get("session_id") or params.get("sessionId") or "")
    if not session_id:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message="session_id is required"))
    try:
        async with session_factory() as db:
            attachments = await list_session_attachment_responses(db, session_id)
    except LookupError as exc:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    return WriterOperationOutcome(response=rpc_result(request_id, {"attachments": attachments}))


async def handle_attachment_get_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    attachment_id = str(params.get("attachment_id") or params.get("attachmentId") or params.get("id") or "")
    if not attachment_id:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message="attachment_id is required"))
    try:
        async with session_factory() as db:
            attachment = await get_attachment_response(db, attachment_id)
    except LookupError as exc:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    return WriterOperationOutcome(response=rpc_result(request_id, {"attachment": attachment}))


async def handle_attachment_preview_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    attachment_id = str(params.get("attachment_id") or params.get("attachmentId") or params.get("id") or "")
    if not attachment_id:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message="attachment_id is required"))
    try:
        async with session_factory() as db:
            preview = await preview_attachment_response(db, attachment_id)
    except (LookupError, FileNotFoundError) as exc:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    return WriterOperationOutcome(response=rpc_result(request_id, {"preview": preview}))


async def handle_attachment_open_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    attachment_id = str(params.get("attachment_id") or params.get("attachmentId") or params.get("id") or "")
    if not attachment_id:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message="attachment_id is required"))
    try:
        async with session_factory() as db:
            result = await open_attachment_response(db, attachment_id)
    except (LookupError, FileNotFoundError) as exc:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    return WriterOperationOutcome(response=rpc_result(request_id, result))


async def handle_settings_get_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
    config_session_factory: Any | None = None,
) -> WriterOperationOutcome:
    namespace = str(params.get("namespace") or "")
    if not namespace:
        return WriterOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="namespace is required")
        )
    if config_session_factory is None:
        return _shared_config_required_outcome(request_id)
    setting = await _with_writer_and_config_sessions(
        session_factory,
        config_session_factory,
        lambda db, config_db: get_app_setting_value(db, namespace, shared_db=config_db),
    )
    return WriterOperationOutcome(response=rpc_result(request_id, {"setting": setting}))


async def handle_settings_update_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
    config_session_factory: Any | None = None,
) -> WriterOperationOutcome:
    namespace = str(params.get("namespace") or "")
    value = params.get("value")
    if not namespace or not isinstance(value, dict):
        return WriterOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="namespace and value are required")
        )
    if config_session_factory is None:
        return _shared_config_required_outcome(request_id)
    try:
        setting = await _retry_sqlite_locked_config_write(
            session_factory,
            config_session_factory,
            lambda db, config_db: update_app_setting_value(
                db,
                namespace,
                value,
                shared_db=config_db,
            ),
        )
    except OperationalError as exc:
        if _is_sqlite_locked_error(exc):
            return _sqlite_locked_outcome(request_id)
        raise
    except ValueError as exc:
        return WriterOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc))
        )
    return WriterOperationOutcome(response=rpc_result(request_id, {"setting": setting}))


async def handle_config_providers_list_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
    config_session_factory: Any | None = None,
) -> WriterOperationOutcome:
    _ = session_factory
    return await _handle_shared_config_operation(
        request_id=request_id,
        operation="config.providers.list",
        params=params,
        config_session_factory=config_session_factory,
    )


async def handle_config_provider_create_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
    config_session_factory: Any | None = None,
) -> WriterOperationOutcome:
    _ = session_factory
    return await _handle_shared_config_operation(
        request_id=request_id,
        operation="config.provider.create",
        params=params,
        config_session_factory=config_session_factory,
    )


async def handle_config_provider_update_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
    config_session_factory: Any | None = None,
) -> WriterOperationOutcome:
    _ = session_factory
    return await _handle_shared_config_operation(
        request_id=request_id,
        operation="config.provider.update",
        params=params,
        config_session_factory=config_session_factory,
    )


async def handle_config_provider_delete_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
    config_session_factory: Any | None = None,
) -> WriterOperationOutcome:
    _ = session_factory
    return await _handle_shared_config_operation(
        request_id=request_id,
        operation="config.provider.delete",
        params=params,
        config_session_factory=config_session_factory,
    )


async def handle_config_models_list_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
    config_session_factory: Any | None = None,
) -> WriterOperationOutcome:
    _ = session_factory
    return await _handle_shared_config_operation(
        request_id=request_id,
        operation="config.models.list",
        params=params,
        config_session_factory=config_session_factory,
    )


async def handle_config_model_create_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
    config_session_factory: Any | None = None,
) -> WriterOperationOutcome:
    _ = session_factory
    return await _handle_shared_config_operation(
        request_id=request_id,
        operation="config.model.create",
        params=params,
        config_session_factory=config_session_factory,
    )


async def handle_config_model_update_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
    config_session_factory: Any | None = None,
) -> WriterOperationOutcome:
    _ = session_factory
    return await _handle_shared_config_operation(
        request_id=request_id,
        operation="config.model.update",
        params=params,
        config_session_factory=config_session_factory,
    )


async def handle_config_model_delete_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
    config_session_factory: Any | None = None,
) -> WriterOperationOutcome:
    _ = session_factory
    return await _handle_shared_config_operation(
        request_id=request_id,
        operation="config.model.delete",
        params=params,
        config_session_factory=config_session_factory,
    )


async def handle_config_import_env_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
    config_session_factory: Any | None = None,
) -> WriterOperationOutcome:
    _ = params
    config_factory = _require_config_session_factory(config_session_factory)
    if config_factory is None:
        return _shared_config_required_outcome(request_id)
    try:
        imported = await _retry_sqlite_locked_write(
            config_factory,
            import_env_provider_model_config,
        )
    except OperationalError as exc:
        if _is_sqlite_locked_error(exc):
            return _sqlite_locked_outcome(request_id)
        raise
    except ValueError as exc:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    return WriterOperationOutcome(response=rpc_result(request_id, imported))


async def handle_config_resolved_get_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
    config_session_factory: Any | None = None,
) -> WriterOperationOutcome:
    task_type = str(params.get("task_type") or params.get("taskType") or "default")
    config_factory = _require_config_session_factory(config_session_factory)
    if config_factory is None:
        return _shared_config_required_outcome(request_id)
    async with config_factory() as db:
        resolved = await resolved_config_response(db, task_type)
    if resolved is None:
        return WriterOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="No LLM config in DB")
        )
    return WriterOperationOutcome(response=rpc_result(request_id, {"resolved": resolved}))


async def handle_config_adapter_profiles_list_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
) -> WriterOperationOutcome:
    _ = params
    return WriterOperationOutcome(
        response=rpc_result(request_id, {"adapter_profiles": list_adapter_profile_configs()})
    )


async def handle_config_runtime_capabilities_get_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
    config_session_factory: Any | None = None,
) -> WriterOperationOutcome:
    work_root = params.get("work_root") or params.get("workRoot")
    if config_session_factory is None:
        return _shared_config_required_outcome(request_id)
    capabilities = await _with_writer_and_config_sessions(
        session_factory,
        config_session_factory,
        lambda db, config_db: runtime_capabilities_response(
            db,
            work_root=str(work_root) if work_root else None,
            shared_db=config_db,
        ),
    )
    return WriterOperationOutcome(response=rpc_result(request_id, {"runtime_capabilities": capabilities}))


async def handle_config_subagent_upsert_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    name = str(params.get("name") or "")
    if not name:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message="name is required"))
    try:
        async with session_factory() as db:
            subagent = await upsert_project_subagent_config(
                db,
                name=name,
                payload=params,
                work_root=str(params.get("work_root") or params.get("workRoot") or "") or None,
            )
    except ValueError as exc:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    return WriterOperationOutcome(response=rpc_result(request_id, {"subagent": subagent}))


async def handle_config_subagent_delete_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
) -> WriterOperationOutcome:
    name = str(params.get("name") or "")
    if not name:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message="name is required"))
    try:
        removed = delete_project_subagent_config(
            name=name,
            work_root=str(params.get("work_root") or params.get("workRoot") or "") or None,
        )
    except ValueError as exc:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    if not removed:
        return WriterOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="Project subagent definition not found")
        )
    return WriterOperationOutcome(response=rpc_result(request_id, {"ok": True}))

async def handle_command_catalog_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
) -> WriterOperationOutcome:
    work_root = params.get("work_root") or params.get("workRoot")
    return WriterOperationOutcome(
        response=rpc_result(
            request_id,
            {"commands": writer_command_catalog(work_root if isinstance(work_root, (str, Path)) else None)},
        )
    )


async def handle_plugin_catalog_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    operation: str,
) -> WriterOperationOutcome:
    project_root = _plugin_project_root(params)
    catalog = build_core_plugin_operation_catalog(
        data_dir=settings.data_dir,
        work_root=project_root or ".",
        include_user_plugins=True,
    )
    result = await catalog.execute(operation, params)
    if result.status != "ok":
        return WriterOperationOutcome(
            response=rpc_error(
                request_id,
                code=INVALID_REQUEST,
                message=str(result.payload.get("error") or "plugin operation failed"),
            )
        )
    return WriterOperationOutcome(response=rpc_result(request_id, result.payload))


def _plugin_project_root(params: dict[str, Any]) -> str:
    raw = (
        params.get("project_root")
        or params.get("projectRoot")
        or params.get("work_root")
        or params.get("workRoot")
        or ""
    )
    return str(raw).strip() if isinstance(raw, (str, Path)) else ""


async def handle_command_execute_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
    writer_service: Any | None = None,
    emit_event: Callable[[WriterAppEventEnvelope], Awaitable[None]] | None = None,
) -> WriterOperationOutcome:
    session_id = str(
        params.get("session_id")
        or params.get("sessionId")
        or params.get("thread_id")
        or params.get("threadId")
        or ""
    )
    command = str(params.get("command") or "")
    if not session_id or not command:
        return WriterOperationOutcome(
            response=rpc_error(
                request_id,
                code=INVALID_REQUEST,
                message="session_id and command are required",
            )
        )
    normalized_command = normalize_writer_command_name(command)
    compact_ids: dict[str, str] | None = None
    published_events: list[WriterAppEventEnvelope] = []
    try:
        if normalized_command == "compact":
            compact_ids = _compact_command_run_ids(session_id)
            persistence = writer_persistence_host(session_factory)

            async def persist_event(event: RunItemEvent):
                async def write(db):
                    envelope = await append_run_item_event_and_apply_snapshot(db, event)
                    return envelope, await load_snapshot(db, session_id)
                return await persistence.write(write)

            running_event, snapshot = await persist_event(
                _compact_command_run_item_event(session_id, {}, ids=compact_ids, status="running")
            )
            if emit_event is not None:
                await emit_event(running_event)
            else:
                published_events.append(running_event)

            async def on_compaction_delta(delta: str) -> None:
                if not delta:
                    return
                envelope, _snapshot = await persist_event(
                    _compact_command_run_item_event(
                        session_id, {"delta": delta}, ids=compact_ids, status="running",
                    )
                )
                if emit_event is not None:
                    await emit_event(envelope)

            compact = writer_service.get("compact_session_context") if isinstance(writer_service, dict) else None
            if callable(compact):
                result = await compact(session_id=session_id, on_summary_delta=on_compaction_delta)
            else:
                async with session_factory() as read_db:
                    plan = await prepare_session_context_compaction(read_db, session_id=session_id)
                _raw_result, payload = await execute_session_context_compaction(
                    plan, llm_client=None, on_summary_delta=on_compaction_delta,
                )
                result = await persistence.write(
                    lambda write_db: apply_session_context_compaction(write_db, plan=plan, payload=payload)
                )
            completed_event, snapshot = await persist_event(
                _compact_command_run_item_event(
                    session_id, result, ids=compact_ids, status="completed",
                )
            )
            if emit_event is not None:
                await emit_event(completed_event)
            else:
                published_events.append(completed_event)
        else:
            persistence = writer_persistence_host(session_factory)
            async def write(db):
                result = await execute_writer_command(
                    db,
                    session_id=session_id,
                    command=command,
                    work_root=params.get("work_root") or params.get("workRoot"),
                )
                return result, await load_snapshot(db, session_id)
            result, snapshot = await persistence.write(write)
    except (LookupError, ValueError, ContextCompactionError) as exc:
        if normalized_command == "compact" and compact_ids is not None:
            await _publish_compact_failed_event(
                session_factory=session_factory,
                session_id=session_id,
                ids=compact_ids,
                error=str(exc),
                emit_event=emit_event,
            )
        return WriterOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc))
        )
    return WriterOperationOutcome(
        response=rpc_result(request_id, {"result": result, "snapshot": snapshot}),
        publish_events=published_events,
    )


def _compact_command_run_ids(session_id: str) -> dict[str, str]:
    run_id = f"{session_id}:command:compact:{uuid4().hex[:12]}"
    return {
        "run_id": run_id,
        "turn_id": run_id,
        "item_id": f"{run_id}:summary",
    }


def _compact_command_run_item_event(
    session_id: str,
    result: dict[str, Any],
    *,
    ids: dict[str, str],
    status: str,
) -> RunItemEvent:
    event_id = f"compact:{status}:{uuid4().hex[:16]}"
    content = str(result.get("summary") or result.get("content") or "")
    delta = str(result.get("delta") or "")
    label = (
        "正在压缩"
        if status == "running"
        else "压缩失败"
        if status == "failed"
        else "暂无可压缩上下文"
        if result.get("status") == "skipped"
        else "上下文已压缩"
    )
    payload: dict[str, Any] = {
        "type": "compaction",
        "label": label,
        "trigger": "manual",
    }
    if content:
        payload["content"] = content
    if delta:
        payload["delta"] = delta
    if result.get("error"):
        payload["error"] = str(result.get("error"))
        payload["content"] = str(result.get("error"))
    if result.get("status"):
        payload["compaction_status"] = result.get("status")
    if result.get("reason"):
        payload["message"] = str(result.get("reason"))
    for key in ("compacted_messages", "retained_messages", "before_tokens", "after_tokens"):
        if result.get(key) is not None:
            payload[key] = result.get(key)
    return RunItemEvent(
        kind="message",
        thread_id=session_id,
        event_id=event_id,
        run_id=ids["run_id"],
        turn_id=ids["turn_id"],
        item_id=ids["item_id"],
        status=status if status in {"running", "completed", "failed"} else "running",
        payload=payload,
        source="command.execute",
        metadata={"command": "compact"},
    )


async def _publish_compact_failed_event(
    *,
    session_factory: Any,
    session_id: str,
    ids: dict[str, str],
    error: str,
    emit_event: Callable[[WriterAppEventEnvelope], Awaitable[None]] | None,
) -> WriterAppEventEnvelope | None:
    persistence = writer_persistence_host(session_factory)
    async def write(db):
        envelope = await append_run_item_event_and_apply_snapshot(
            db,
            _compact_command_run_item_event(
                session_id,
                {"error": error},
                ids=ids,
                status="failed",
            ),
        )
        terminal_envelope = await append_run_item_event_and_apply_snapshot(
            db,
            _compact_command_terminal_event(session_id, ids=ids, error=error),
        )
        return envelope, terminal_envelope
    envelope, terminal_envelope = await persistence.write(write)
    if emit_event is not None:
        await emit_event(envelope)
        await emit_event(terminal_envelope)
    return envelope


def _compact_command_terminal_event(
    session_id: str,
    *,
    ids: dict[str, str],
    error: str,
) -> RunItemEvent:
    return RunItemEvent(
        kind="status",
        thread_id=session_id,
        event_id=f"compact:failed-status:{uuid4().hex[:16]}",
        run_id=ids["run_id"],
        turn_id=ids["turn_id"],
        status="failed",
        payload={
            "type": "turn",
            "status": "failed",
            "raw_end_reason": "command_failed",
            "message": error,
        },
        source="command.execute",
        metadata={"command": "compact"},
    )


async def handle_artifact_read_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    current_thread_id: str | None = None,
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    thread_id = str(params.get("thread_id") or params.get("threadId") or current_thread_id or "")
    artifact_id = str(params.get("artifact_id") or params.get("artifactId") or "")
    if not thread_id or not artifact_id:
        return WriterOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="thread_id and artifact_id are required")
        )
    try:
        async with session_factory() as db:
            artifact = await read_artifact(db, thread_id=thread_id, artifact_id=artifact_id)
    except LookupError as exc:
        return WriterOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc))
        )
    return WriterOperationOutcome(response=rpc_result(request_id, {"artifact": artifact}))


async def handle_artifact_open_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    current_thread_id: str | None = None,
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    thread_id = str(params.get("thread_id") or params.get("threadId") or current_thread_id or "")
    artifact_id = str(params.get("artifact_id") or params.get("artifactId") or "")
    if not thread_id or not artifact_id:
        return WriterOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="thread_id and artifact_id are required")
        )
    try:
        async with session_factory() as db:
            artifact = await open_artifact(db, thread_id=thread_id, artifact_id=artifact_id)
    except (LookupError, ValueError, FileNotFoundError) as exc:
        return WriterOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc))
        )
    return WriterOperationOutcome(response=rpc_result(request_id, {"artifact": artifact}))


def _handler(handler: OperationRpcHandler):
    async def run(request: OperationRequest) -> OperationResult:
        rpc_request = request.metadata.get("rpc_request")
        if not isinstance(rpc_request, JsonRpcRequest):
            raise TypeError("rpc_request metadata is required")
        await handler(rpc_request)
        return OperationResult(name=request.name, metadata={"live_response_sent": True})

    return run


def _bounded_int(value: object, *, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


__all__ = [
    "OPERATION_ALIASES",
    "WRITER_OVERLAY_OPERATION_NAMES",
    "WriterOperationOutcome",
    "build_writer_core_operation_adapter_catalog",
    "build_writer_operation_catalog",
    "handle_attachment_get_operation",
    "handle_attachment_list_operation",
    "handle_attachment_open_operation",
    "handle_attachment_preview_operation",
    "handle_artifact_open_operation",
    "handle_artifact_read_operation",
    "handle_command_catalog_operation",
    "handle_command_execute_operation",
    "handle_config_adapter_profiles_list_operation",
    "handle_config_provider_create_operation",
    "handle_config_provider_delete_operation",
    "handle_config_provider_update_operation",
    "handle_config_model_create_operation",
    "handle_config_model_delete_operation",
    "handle_config_model_update_operation",
    "handle_config_models_list_operation",
    "handle_config_import_env_operation",
    "handle_config_providers_list_operation",
    "handle_config_resolved_get_operation",
    "handle_config_runtime_capabilities_get_operation",
    "handle_config_subagent_delete_operation",
    "handle_config_subagent_upsert_operation",
    "handle_plugin_catalog_operation",
    "handle_project_create_operation",
    "handle_project_session_create_operation",
    "handle_project_agents_md_get_operation",
    "handle_project_agents_md_update_operation",
    "handle_project_delete_operation",
    "handle_project_directory_pick_operation",
    "handle_project_get_operation",
    "handle_project_list_operation",
    "handle_project_sessions_list_operation",
    "handle_project_update_operation",
    "handle_session_create_operation",
    "handle_session_checkpoint_create_operation",
    "handle_session_checkpoint_restore_operation",
    "handle_session_checkpoints_list_operation",
    "handle_session_change_file_undo_operation",
    "handle_session_change_file_open_operation",
    "handle_session_changes_undo_operation",
    "handle_session_agent_branch_abandon_operation",
    "handle_session_changes_get_operation",
    "handle_session_agent_branch_diff_operation",
    "handle_session_agent_branch_merge_operation",
    "handle_session_agent_branches_list_operation",
    "handle_session_commit_review_decide_operation",
    "handle_session_commit_review_get_operation",
    "handle_session_delete_operation",
    "handle_session_fork_operation",
    "handle_session_get_operation",
    "handle_session_git_graph_get_operation",
    "handle_session_list_operation",
    "handle_session_rollback_turn_operation",
    "handle_session_update_operation",
    "handle_settings_get_operation",
    "handle_settings_update_operation",
    "operation_name",
]
