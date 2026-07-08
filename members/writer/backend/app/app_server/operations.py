from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.core.writer.git import WriterGitManager
from app.database import async_session
from app.models.app_server import WriterAppRequest
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
    create_session_checkpoint_response,
    list_session_checkpoint_responses,
    restore_session_checkpoint_response,
)
from app.services.commit_review_service import (
    WorktreeChangedError,
    decide_commit_review_response,
    get_commit_review_response,
)
from app.services.command_service import execute_writer_command, normalize_writer_command_name, writer_command_catalog
from app.services.composer_input_service import prepare_composer_input
from app.services.config_read import (
    list_adapter_profile_configs,
    list_model_configs,
    list_provider_configs,
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
    delete_writer_project,
    get_writer_project_response,
    list_project_session_summaries,
    list_writer_project_responses,
    read_project_agents_md,
    update_writer_project,
    write_project_agents_md,
)
from app.services.runtime_capabilities import runtime_capabilities_response
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
from app.services.session_rollback_service import rollback_session_turn_response
from app.services.session_undo_service import undo_session_changes_response, undo_session_file_change_response
from app.services.session_projection import session_response_projected
from app.services.subagent_config import delete_project_subagent_config, upsert_project_subagent_config
from lamtools_core.app import OperationCatalog, OperationRequest, OperationResult, normalize_operation_name
from lamtools_core.context_compaction import ContextCompactionError
from lamtools_core.event import RunItemEvent
from lamtools_core.runtime import default_runtime_task_registry

from .approvals import respond_to_approval
from .artifacts import open_artifact, read_artifact
from .event_store import append_event_and_load_snapshot, append_run_item_event_and_apply_snapshot
from .ledger import list_events_after
from .protocol import AppendEventInput, JsonRpcRequest, WriterAppEventEnvelope, rpc_error, rpc_result
from .queue import (
    ACTIVE_TURN_STATUSES,
    accept_queue_item,
    accept_turn_start,
    accept_turn_steer,
    delete_queue_item,
    effective_turn_status,
    input_attachment_ids,
    latest_active_turn_id,
    update_queue_item,
)
from .runtime_context import runtime_context_from_events
from .snapshot import load_snapshot


OperationRpcHandler = Callable[[JsonRpcRequest], Awaitable[None]]

INVALID_REQUEST = -32600
_SQLITE_LOCKED_MESSAGE = "数据库正忙，请稍后重试"
_SQLITE_LOCK_RETRY_DELAYS = (0.05, 0.15)
_git_manager = WriterGitManager()


@dataclass
class WriterOperationOutcome:
    response: dict[str, Any]
    notify_events: list[WriterAppEventEnvelope] = field(default_factory=list)
    publish_events: list[WriterAppEventEnvelope] = field(default_factory=list)
    continuation: dict[str, Any] | None = None
    runtime_start: dict[str, Any] | None = None


@dataclass(frozen=True)
class ApprovalResolution:
    event: WriterAppEventEnvelope
    was_open: bool


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


def _sqlite_locked_outcome(request_id: int | str | None) -> WriterOperationOutcome:
    return WriterOperationOutcome(
        response=rpc_error(request_id, code=INVALID_REQUEST, message=_SQLITE_LOCKED_MESSAGE)
    )

OPERATION_ALIASES = {
    "turn/interrupt": "turn.cancel",
    "turn.interrupt": "turn.cancel",
}


def operation_name(method: str) -> str:
    return normalize_operation_name(method, aliases=OPERATION_ALIASES)


def build_writer_operation_catalog(
    *,
    thread_read: OperationRpcHandler,
    thread_resume: OperationRpcHandler,
    thread_start: OperationRpcHandler,
    turn_start: OperationRpcHandler,
    turn_steer: OperationRpcHandler,
    turn_cancel: OperationRpcHandler,
    approval_respond: OperationRpcHandler,
    queue_create: OperationRpcHandler,
    queue_update: OperationRpcHandler,
    queue_delete: OperationRpcHandler,
    project_create: OperationRpcHandler,
    project_get: OperationRpcHandler,
    project_list: OperationRpcHandler,
    project_update: OperationRpcHandler,
    project_delete: OperationRpcHandler,
    project_agents_md_get: OperationRpcHandler,
    project_agents_md_update: OperationRpcHandler,
    project_sessions_list: OperationRpcHandler,
    attachment_list: OperationRpcHandler,
    attachment_get: OperationRpcHandler,
    attachment_preview: OperationRpcHandler,
    attachment_open: OperationRpcHandler,
    artifact_read: OperationRpcHandler,
    artifact_open: OperationRpcHandler,
    command_catalog: OperationRpcHandler,
    command_execute: OperationRpcHandler,
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
    settings_get: OperationRpcHandler,
    settings_update: OperationRpcHandler,
    config_providers_list: OperationRpcHandler,
    config_provider_create: OperationRpcHandler,
    config_provider_update: OperationRpcHandler,
    config_provider_delete: OperationRpcHandler,
    config_models_list: OperationRpcHandler,
    config_model_create: OperationRpcHandler,
    config_model_update: OperationRpcHandler,
    config_model_delete: OperationRpcHandler,
    config_import_env: OperationRpcHandler,
    config_resolved_get: OperationRpcHandler,
    config_adapter_profiles_list: OperationRpcHandler,
    config_runtime_capabilities_get: OperationRpcHandler,
    config_subagent_upsert: OperationRpcHandler,
    config_subagent_delete: OperationRpcHandler,
) -> OperationCatalog:
    catalog = OperationCatalog()
    catalog.register("thread.read", _handler(thread_read))
    catalog.register("thread.resume", _handler(thread_resume))
    catalog.register("thread.start", _handler(thread_start))
    catalog.register("turn.start", _handler(turn_start))
    catalog.register("turn.steer", _handler(turn_steer))
    catalog.register("turn.cancel", _handler(turn_cancel))
    catalog.register("approval.respond", _handler(approval_respond))
    catalog.register("queue.create", _handler(queue_create))
    catalog.register("queue.update", _handler(queue_update))
    catalog.register("queue.delete", _handler(queue_delete))
    catalog.register("project.create", _handler(project_create))
    catalog.register("project.get", _handler(project_get))
    catalog.register("project.list", _handler(project_list))
    catalog.register("project.update", _handler(project_update))
    catalog.register("project.delete", _handler(project_delete))
    catalog.register("project.agents_md.get", _handler(project_agents_md_get))
    catalog.register("project.agents_md.update", _handler(project_agents_md_update))
    catalog.register("project.sessions.list", _handler(project_sessions_list))
    catalog.register("attachment.list", _handler(attachment_list))
    catalog.register("attachment.get", _handler(attachment_get))
    catalog.register("attachment.preview", _handler(attachment_preview))
    catalog.register("attachment.open", _handler(attachment_open))
    catalog.register("artifact.read", _handler(artifact_read))
    catalog.register("artifact.open", _handler(artifact_open))
    catalog.register("command.catalog", _handler(command_catalog))
    catalog.register("command.execute", _handler(command_execute))
    catalog.register("session.create", _handler(session_create))
    catalog.register("session.get", _handler(session_get))
    catalog.register("session.list", _handler(session_list))
    catalog.register("session.update", _handler(session_update))
    catalog.register("session.delete", _handler(session_delete))
    catalog.register("session.fork", _handler(session_fork))
    catalog.register("session.git_graph.get", _handler(session_git_graph))
    catalog.register("session.changes.get", _handler(session_changes_get))
    catalog.register("session.checkpoints.list", _handler(session_checkpoints_list))
    catalog.register("session.checkpoint.create", _handler(session_checkpoint_create))
    catalog.register("session.checkpoint.restore", _handler(session_checkpoint_restore))
    catalog.register("session.commit_review.get", _handler(session_commit_review_get))
    catalog.register("session.commit_review.decide", _handler(session_commit_review_decide))
    catalog.register("session.agent_branches.list", _handler(session_agent_branches_list))
    catalog.register("session.agent_branch.diff", _handler(session_agent_branch_diff))
    catalog.register("session.agent_branch.merge", _handler(session_agent_branch_merge))
    catalog.register("session.agent_branch.abandon", _handler(session_agent_branch_abandon))
    catalog.register("session.rollback_turn", _handler(session_rollback_turn))
    catalog.register("session.changes.undo", _handler(session_changes_undo))
    catalog.register("session.change_file.open", _handler(session_change_file_open))
    catalog.register("session.change_file.undo", _handler(session_change_file_undo))
    catalog.register("settings.get", _handler(settings_get))
    catalog.register("settings.update", _handler(settings_update))
    catalog.register("config.providers.list", _handler(config_providers_list))
    catalog.register("config.provider.create", _handler(config_provider_create))
    catalog.register("config.provider.update", _handler(config_provider_update))
    catalog.register("config.provider.delete", _handler(config_provider_delete))
    catalog.register("config.models.list", _handler(config_models_list))
    catalog.register("config.model.create", _handler(config_model_create))
    catalog.register("config.model.update", _handler(config_model_update))
    catalog.register("config.model.delete", _handler(config_model_delete))
    catalog.register("config.import_env", _handler(config_import_env))
    catalog.register("config.resolved.get", _handler(config_resolved_get))
    catalog.register("config.adapter_profiles.list", _handler(config_adapter_profiles_list))
    catalog.register("config.runtime_capabilities.get", _handler(config_runtime_capabilities_get))
    catalog.register("config.subagent.upsert", _handler(config_subagent_upsert))
    catalog.register("config.subagent.delete", _handler(config_subagent_delete))
    return catalog


async def handle_thread_start_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    thread_id = str(params.get("thread_id") or params.get("threadId") or "")
    if not thread_id:
        return WriterOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="thread_id is required")
        )
    async with session_factory() as db:
        event, snapshot = await append_event_and_load_snapshot(
            db,
            AppendEventInput(
                thread_id=thread_id,
                method="thread/started",
                payload={"type": "thread", "status": "idle", **params},
            ),
        )
        await db.commit()
    return WriterOperationOutcome(
        response=rpc_result(
            request_id,
            {
                "thread": {"id": thread_id},
                "event": event.model_dump(mode="json"),
                "snapshot": snapshot,
            },
        ),
        publish_events=[event],
    )


async def handle_thread_resume_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    current_thread_id: str | None = None,
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    thread_id = str(params.get("thread_id") or params.get("threadId") or current_thread_id or "")
    if not thread_id:
        return WriterOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="thread_id is required")
        )
    after_seq = int(params.get("last_seen_seq") or params.get("lastSeenSeq") or 0)
    async with session_factory() as db:
        events = await list_events_after(db, thread_id=thread_id, after_seq=after_seq)
        snapshot = await load_snapshot(db, thread_id)
    return WriterOperationOutcome(
        response=rpc_result(
            request_id,
            {
                "thread": {"id": thread_id},
                "events": [event.model_dump(mode="json") for event in events],
                "snapshot": snapshot,
            },
        )
    )


async def handle_thread_read_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    current_thread_id: str | None = None,
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    thread_id = str(params.get("thread_id") or params.get("threadId") or current_thread_id or "")
    if not thread_id:
        return WriterOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="thread_id is required")
        )
    async with session_factory() as db:
        session = await db.get(WriterSession, thread_id)
        snapshot = await load_snapshot(db, thread_id)
        session_payload = await session_response_projected(db, session) if session is not None else None
    return WriterOperationOutcome(
        response=rpc_result(
            request_id,
            {
                "thread": {"id": thread_id},
                "session": session_payload,
                "snapshot": snapshot,
            },
        )
    )


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
    async with session_factory() as db:
        session = await create_writer_session(
            db,
            title=str(params.get("title") or "New Session"),
            work_root=str(params.get("work_root") or params.get("workRoot") or ""),
            mode=str(params.get("mode") or "EXECUTE"),
            project_id=(
                str(params.get("project_id") or params.get("projectId"))
                if params.get("project_id") or params.get("projectId")
                else None
            ),
            git_manager=_git_manager,
        )
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
        async with session_factory() as db:
            session = await update_writer_session(db, session_id, update_data, git_manager=_git_manager)
    except LookupError as exc:
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
        async with session_factory() as db:
            await delete_writer_session(db, session_id)
    except LookupError as exc:
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
        async with session_factory() as db:
            session = await fork_session_response(
                db,
                session_id,
                after_turn_id=after_turn_id,
                title=title,
                isolated_worktree=isolated_worktree,
            )
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
        async with session_factory() as db:
            checkpoint = await create_session_checkpoint_response(
                db,
                session_id,
                label=str(params.get("label") or "checkpoint"),
                reason=str(params.get("reason") or "手动保存检查点"),
                allow_empty=bool(params.get("allow_empty") if "allow_empty" in params else params.get("allowEmpty")),
            )
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
        async with session_factory() as db:
            result = await restore_session_checkpoint_response(db, session_id, commit=commit)
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
        async with session_factory() as db:
            review = await decide_commit_review_response(
                db,
                session_id,
                action=action,
                feedback=str(params.get("feedback") or ""),
                commit_message=(
                    str(params.get("commit_message") or params.get("commitMessage"))
                    if params.get("commit_message") or params.get("commitMessage")
                    else None
                ),
            )
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
        async with session_factory() as db:
            result = await rollback_session_turn_response(
                db,
                session_id,
                turn_id=turn_id,
                reason=reason,
            )
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
            await db.commit()
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
        async with session_factory() as db:
            project = await create_writer_project_response(
                db,
                work_root=str(params.get("work_root") or params.get("workRoot") or ""),
                git_manager=_git_manager,
            )
    except HTTPException as exc:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc.detail)))
    return WriterOperationOutcome(response=rpc_result(request_id, {"project": project}))


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
        async with session_factory() as db:
            project = await update_writer_project(db, project_id, update_data)
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
        async with session_factory() as db:
            await delete_writer_project(db, project_id)
    except LookupError as exc:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    return WriterOperationOutcome(response=rpc_result(request_id, {"ok": True}))


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
    return WriterOperationOutcome(response=rpc_result(request_id, result))


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
        async with session_factory() as db:
            result = await write_project_agents_md(db, project_id, content)
    except (LookupError, ValueError) as exc:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    return WriterOperationOutcome(response=rpc_result(request_id, result))


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
) -> WriterOperationOutcome:
    namespace = str(params.get("namespace") or "")
    if not namespace:
        return WriterOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="namespace is required")
        )
    async with session_factory() as db:
        setting = await get_app_setting_value(db, namespace)
    return WriterOperationOutcome(response=rpc_result(request_id, {"setting": setting}))


async def handle_settings_update_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    namespace = str(params.get("namespace") or "")
    value = params.get("value")
    if not namespace or not isinstance(value, dict):
        return WriterOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="namespace and value are required")
        )
    try:
        setting = await _retry_sqlite_locked_write(
            session_factory,
            lambda db: update_app_setting_value(db, namespace, value),
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
) -> WriterOperationOutcome:
    limit = _bounded_int(params.get("limit"), default=50, minimum=1, maximum=200)
    offset = _bounded_int(params.get("offset"), default=0, minimum=0, maximum=100000)
    async with session_factory() as db:
        providers = await list_provider_configs(db, limit=limit, offset=offset)
    return WriterOperationOutcome(response=rpc_result(request_id, {"providers": providers}))


async def handle_config_provider_create_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    required = ("name", "base_url", "api_key")
    missing = [key for key in required if not str(params.get(key) or "")]
    if missing:
        return WriterOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="name, base_url and api_key are required")
        )
    payload = {
        "name": str(params.get("name") or ""),
        "api_type": str(params.get("api_type") or "openai"),
        "base_url": str(params.get("base_url") or ""),
        "api_key": str(params.get("api_key") or ""),
        "extra": params.get("extra") if isinstance(params.get("extra"), dict) else None,
    }
    try:
        provider = await _retry_sqlite_locked_write(
            session_factory,
            lambda db: create_provider_config(db, payload),
        )
    except OperationalError as exc:
        if _is_sqlite_locked_error(exc):
            return _sqlite_locked_outcome(request_id)
        raise
    return WriterOperationOutcome(response=rpc_result(request_id, {"provider": provider}))


async def handle_config_provider_update_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    provider_id = str(params.get("provider_id") or params.get("providerId") or params.get("id") or "")
    if not provider_id:
        return WriterOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="provider_id is required")
        )
    update_data = {
        key: value
        for key, value in {
            "name": params.get("name"),
            "api_type": params.get("api_type"),
            "base_url": params.get("base_url"),
            "api_key": params.get("api_key"),
            "extra": params.get("extra"),
        }.items()
        if value is not None
    }
    try:
        provider = await _retry_sqlite_locked_write(
            session_factory,
            lambda db: update_provider_config(db, provider_id, update_data),
        )
    except OperationalError as exc:
        if _is_sqlite_locked_error(exc):
            return _sqlite_locked_outcome(request_id)
        raise
    except LookupError as exc:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    return WriterOperationOutcome(response=rpc_result(request_id, {"provider": provider}))


async def handle_config_provider_delete_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    provider_id = str(params.get("provider_id") or params.get("providerId") or params.get("id") or "")
    if not provider_id:
        return WriterOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="provider_id is required")
        )
    try:
        await _retry_sqlite_locked_write(
            session_factory,
            lambda db: delete_provider_config(db, provider_id),
        )
    except OperationalError as exc:
        if _is_sqlite_locked_error(exc):
            return _sqlite_locked_outcome(request_id)
        raise
    except LookupError as exc:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    return WriterOperationOutcome(response=rpc_result(request_id, {"ok": True}))


async def handle_config_models_list_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    limit = _bounded_int(params.get("limit"), default=50, minimum=1, maximum=200)
    offset = _bounded_int(params.get("offset"), default=0, minimum=0, maximum=100000)
    provider_id = params.get("provider_id") or params.get("providerId")
    async with session_factory() as db:
        models = await list_model_configs(
            db,
            provider_id=str(provider_id) if provider_id else None,
            limit=limit,
            offset=offset,
        )
    return WriterOperationOutcome(response=rpc_result(request_id, {"models": models}))


async def handle_config_model_create_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    required = ("provider_id", "model_id")
    missing = [key for key in required if not str(params.get(key) or "")]
    if missing:
        return WriterOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="provider_id and model_id are required")
        )
    payload = {
        "provider_id": str(params.get("provider_id") or ""),
        "model_id": str(params.get("model_id") or ""),
        "display_name": str(params.get("display_name") or ""),
        "context_window": int(params.get("context_window") or 128000),
        "max_output_tokens": int(params.get("max_output_tokens") or 16384),
        "thinking_supported": bool(params.get("thinking_supported")),
        "thinking_budget": int(params.get("thinking_budget") or 10000),
        "temperature": float(params.get("temperature") or 0.7),
        "extra": params.get("extra") if isinstance(params.get("extra"), dict) else None,
    }
    try:
        model = await _retry_sqlite_locked_write(
            session_factory,
            lambda db: create_model_config(db, payload),
        )
    except OperationalError as exc:
        if _is_sqlite_locked_error(exc):
            return _sqlite_locked_outcome(request_id)
        raise
    except LookupError as exc:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    return WriterOperationOutcome(response=rpc_result(request_id, {"model": model}))


async def handle_config_model_update_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    model_id = str(params.get("model_record_id") or params.get("id") or "")
    if not model_id:
        return WriterOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="model_record_id is required")
        )
    update_data = {
        key: value
        for key, value in {
            "provider_id": params.get("provider_id"),
            "model_id": params.get("model_id"),
            "display_name": params.get("display_name"),
            "context_window": params.get("context_window"),
            "max_output_tokens": params.get("max_output_tokens"),
            "thinking_supported": params.get("thinking_supported"),
            "thinking_budget": params.get("thinking_budget"),
            "temperature": params.get("temperature"),
            "extra": params.get("extra"),
        }.items()
        if value is not None
    }
    try:
        model = await _retry_sqlite_locked_write(
            session_factory,
            lambda db: update_model_config(db, model_id, update_data),
        )
    except OperationalError as exc:
        if _is_sqlite_locked_error(exc):
            return _sqlite_locked_outcome(request_id)
        raise
    except (LookupError, ValueError) as exc:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    return WriterOperationOutcome(response=rpc_result(request_id, {"model": model}))


async def handle_config_model_delete_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    model_id = str(params.get("model_record_id") or params.get("id") or "")
    if not model_id:
        return WriterOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="model_record_id is required")
        )
    try:
        await _retry_sqlite_locked_write(
            session_factory,
            lambda db: delete_model_config(db, model_id),
        )
    except OperationalError as exc:
        if _is_sqlite_locked_error(exc):
            return _sqlite_locked_outcome(request_id)
        raise
    except LookupError as exc:
        return WriterOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    return WriterOperationOutcome(response=rpc_result(request_id, {"ok": True}))


async def handle_config_import_env_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    _ = params
    try:
        imported = await _retry_sqlite_locked_write(
            session_factory,
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
) -> WriterOperationOutcome:
    task_type = str(params.get("task_type") or params.get("taskType") or "default")
    async with session_factory() as db:
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
) -> WriterOperationOutcome:
    work_root = params.get("work_root") or params.get("workRoot")
    async with session_factory() as db:
        capabilities = await runtime_capabilities_response(
            db,
            work_root=str(work_root) if work_root else None,
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


async def handle_turn_cancel_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    current_thread_id: str | None = None,
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    thread_id = str(params.get("thread_id") or params.get("threadId") or current_thread_id or "")
    turn_id = str(params.get("turn_id") or params.get("turnId") or "")
    if not thread_id:
        return WriterOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="thread_id is required")
        )
    async with session_factory() as db:
        snapshot = await load_snapshot(db, thread_id)
        if not turn_id:
            turn_id = latest_active_turn_id(snapshot) or ""
        else:
            if effective_turn_status(snapshot, turn_id) not in ACTIVE_TURN_STATUSES:
                turn_id = ""
        if not turn_id:
            return WriterOperationOutcome(
                response=rpc_result(
                    request_id,
                    {
                        "event": None,
                        "status": "idle",
                        "snapshot": snapshot,
                    },
                )
            )
        event, snapshot = await append_event_and_load_snapshot(
            db,
            AppendEventInput(
                thread_id=thread_id,
                turn_id=turn_id or None,
                method="turn/interrupted",
                payload={"type": "turn", "reason": "user_interrupt"},
            ),
        )
        core_event = await append_run_item_event_and_apply_snapshot(
            db,
            RunItemEvent(
                kind="status",
                thread_id=thread_id,
                event_id=f"{turn_id}:interrupting",
                turn_id=turn_id,
                status="interrupting",
                payload={"type": "turn", "status": "interrupting", "raw_end_reason": "user_interrupt"},
            ),
        )
        snapshot = await load_snapshot(db, thread_id)
        await db.commit()
    default_runtime_task_registry().cancel(thread_id, run_id=turn_id or None, force=True)
    return WriterOperationOutcome(
        response=rpc_result(
            request_id,
            {
                "event": event.model_dump(mode="json"),
                "snapshot": snapshot,
            },
        ),
        publish_events=[event, core_event],
    )


async def handle_turn_start_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    current_thread_id: str | None = None,
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    thread_id = str(params.get("thread_id") or params.get("threadId") or current_thread_id or "")
    client_message_id = str(params.get("client_message_id") or params.get("clientMessageId") or "")
    input_items = params.get("input")
    if not thread_id or not client_message_id or not isinstance(input_items, list):
        return WriterOperationOutcome(
            response=rpc_error(
                request_id,
                code=INVALID_REQUEST,
                message="thread_id, client_message_id and input are required",
            )
        )
    async with session_factory() as db:
        session = await db.get(WriterSession, thread_id)
        if session is None:
            return WriterOperationOutcome(
                response=rpc_error(request_id, code=INVALID_REQUEST, message="Thread/session not found")
            )
        work_root = params.get("work_root") or params.get("workRoot") or session.work_root
        try:
            prepared = prepare_composer_input(
                work_root=work_root,
                input_items=input_items,
            )
            events = await accept_turn_start(
                db,
                thread_id=thread_id,
                client_message_id=client_message_id,
                input_items=prepared.visible_items,
                work_root=work_root,
            )
        except ValueError as exc:
            return WriterOperationOutcome(
                response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc))
            )
        snapshot = await load_snapshot(db, thread_id)
        await db.commit()
    runtime_start = None
    turn_id, user_message_id = runtime_context_from_events(events)
    if turn_id and user_message_id and len(events) > 1:
        runtime_start = {
            "thread_id": thread_id,
            "turn_id": turn_id,
            "user_message_id": user_message_id,
            "text": prepared.runtime_text,
            "work_root": work_root,
            "thinking_enabled": params.get("thinking_enabled") if isinstance(params.get("thinking_enabled"), bool) else None,
            "thinking_budget": params.get("thinking_budget") if isinstance(params.get("thinking_budget"), int) else None,
            "shallow_thinking_enabled": params.get("shallow_thinking_enabled") if isinstance(params.get("shallow_thinking_enabled"), bool) else None,
            "model_id": params.get("model_id") if isinstance(params.get("model_id"), str) else None,
            "attachment_ids": input_attachment_ids(prepared.runtime_items),
        }
    return WriterOperationOutcome(
        response=rpc_result(
            request_id,
            {
                "events": [event.model_dump(mode="json") for event in events],
                "snapshot": snapshot,
            },
        ),
        notify_events=events,
        runtime_start=runtime_start,
    )


async def handle_turn_steer_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    current_thread_id: str | None = None,
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    thread_id = str(params.get("thread_id") or params.get("threadId") or current_thread_id or "")
    turn_id = str(params.get("turn_id") or params.get("turnId") or "")
    client_message_id = str(params.get("client_message_id") or params.get("clientMessageId") or "")
    input_items = params.get("input")
    if not thread_id or not turn_id or not client_message_id or not isinstance(input_items, list):
        return WriterOperationOutcome(
            response=rpc_error(
                request_id,
                code=INVALID_REQUEST,
                message="thread_id, turn_id, client_message_id and input are required",
            )
        )
    async with session_factory() as db:
        events = await accept_turn_steer(
            db,
            thread_id=thread_id,
            turn_id=turn_id,
            client_message_id=client_message_id,
            input_items=input_items,
        )
        snapshot = await load_snapshot(db, thread_id)
        await db.commit()
    return WriterOperationOutcome(
        response=rpc_result(
            request_id,
            {
                "events": [event.model_dump(mode="json") for event in events],
                "snapshot": snapshot,
            },
        ),
        notify_events=events,
    )


async def handle_queue_create_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    current_thread_id: str | None = None,
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    thread_id = str(params.get("thread_id") or params.get("threadId") or current_thread_id or "")
    client_message_id = str(params.get("client_message_id") or params.get("clientMessageId") or "")
    input_items = params.get("input")
    if not thread_id or not client_message_id or not isinstance(input_items, list):
        return WriterOperationOutcome(
            response=rpc_error(
                request_id,
                code=INVALID_REQUEST,
                message="thread_id, client_message_id and input are required",
            )
        )
    async with session_factory() as db:
        try:
            session = await db.get(WriterSession, thread_id)
            work_root = session.work_root if session is not None else None
            prepared = prepare_composer_input(work_root=work_root, input_items=input_items)
            events = await accept_queue_item(
                db,
                thread_id=thread_id,
                client_message_id=client_message_id,
                input_items=prepared.visible_items,
                runtime_input_items=prepared.runtime_items,
                mode=str(params.get("mode") or "next_turn"),
            )
        except ValueError as exc:
            return WriterOperationOutcome(
                response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc))
            )
        snapshot = await load_snapshot(db, thread_id)
        await db.commit()
    return WriterOperationOutcome(
        response=rpc_result(
            request_id,
            {
                "events": [event.model_dump(mode="json") for event in events],
                "snapshot": snapshot,
            },
        ),
        notify_events=events,
    )


async def handle_queue_update_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    current_thread_id: str | None = None,
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    thread_id = str(params.get("thread_id") or params.get("threadId") or current_thread_id or "")
    queue_item_id = str(params.get("queue_item_id") or params.get("queueItemId") or "")
    text = str(params.get("text") or "")
    if not thread_id or not queue_item_id or not text.strip():
        return WriterOperationOutcome(
            response=rpc_error(
                request_id,
                code=INVALID_REQUEST,
                message="thread_id, queue_item_id and text are required",
            )
        )
    async with session_factory() as db:
        events = await update_queue_item(
            db,
            thread_id=thread_id,
            queue_item_id=queue_item_id,
            text=text.strip(),
        )
        snapshot = await load_snapshot(db, thread_id)
        await db.commit()
    return WriterOperationOutcome(
        response=rpc_result(
            request_id,
            {
                "events": [event.model_dump(mode="json") for event in events],
                "snapshot": snapshot,
            },
        ),
        notify_events=events,
    )


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
    try:
        async with session_factory() as db:
            async def on_compaction_delta(delta: str) -> None:
                if not compact_ids or not delta:
                    return
                envelope = await append_run_item_event_and_apply_snapshot(
                    db,
                    _compact_command_run_item_event(
                        session_id,
                        {"delta": delta},
                        ids=compact_ids,
                        status="running",
                    ),
                )
                await db.commit()
                if emit_event is not None:
                    await emit_event(envelope)

            published_events: list[WriterAppEventEnvelope] = []
            if normalized_command == "compact":
                compact_ids = _compact_command_run_ids(session_id)
                running_event = await append_run_item_event_and_apply_snapshot(
                    db,
                    _compact_command_run_item_event(
                        session_id,
                        {},
                        ids=compact_ids,
                        status="running",
                    ),
                )
                await db.commit()
                if emit_event is not None:
                    await emit_event(running_event)
                else:
                    published_events.append(running_event)

            result = await execute_writer_command(
                db,
                session_id=session_id,
                command=command,
                work_root=params.get("work_root") or params.get("workRoot"),
                compact_session_context=(
                    writer_service.get("compact_session_context")
                    if isinstance(writer_service, dict)
                        else None
                ),
                on_compaction_delta=on_compaction_delta if normalized_command == "compact" else None,
            )
            if normalized_command == "compact" and result.get("status") in {"compacted", "skipped"}:
                completed_event = await append_run_item_event_and_apply_snapshot(
                    db,
                    _compact_command_run_item_event(
                        session_id,
                        result,
                        ids=compact_ids or _compact_command_run_ids(session_id),
                        status="completed",
                    ),
                )
                if emit_event is not None:
                    await db.commit()
                    await emit_event(completed_event)
                else:
                    published_events.append(completed_event)
            snapshot = await load_snapshot(db, session_id)
            await db.commit()
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
    async with session_factory() as db:
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
        await db.commit()
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


async def handle_queue_delete_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    current_thread_id: str | None = None,
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    thread_id = str(params.get("thread_id") or params.get("threadId") or current_thread_id or "")
    queue_item_id = str(params.get("queue_item_id") or params.get("queueItemId") or "")
    if not thread_id or not queue_item_id:
        return WriterOperationOutcome(
            response=rpc_error(
                request_id,
                code=INVALID_REQUEST,
                message="thread_id and queue_item_id are required",
            )
        )
    async with session_factory() as db:
        events = await delete_queue_item(db, thread_id=thread_id, queue_item_id=queue_item_id)
        snapshot = await load_snapshot(db, thread_id)
        await db.commit()
    return WriterOperationOutcome(
        response=rpc_result(
            request_id,
            {
                "events": [event.model_dump(mode="json") for event in events],
                "snapshot": snapshot,
            },
        ),
        notify_events=events,
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


async def resolve_approval_request(
    *,
    request_id: str,
    decision: str,
    guidance: str | None,
    session_factory: Any = async_session,
) -> ApprovalResolution:
    async with session_factory() as db:
        request_row = await db.get(WriterAppRequest, request_id)
        was_open = request_row is not None and request_row.status == "open"
        event = await respond_to_approval(
            db,
            request_id=request_id,
            decision=decision,
            guidance=guidance,
        )
        await db.commit()
    return ApprovalResolution(event=event, was_open=was_open)


async def handle_approval_respond_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    session_factory: Any = async_session,
) -> WriterOperationOutcome:
    approval_request_id = str(params.get("request_id") or params.get("requestId") or "")
    decision = str(params.get("decision") or "")
    guidance = params.get("guidance") if isinstance(params.get("guidance"), str) else None
    if not approval_request_id or not decision:
        return WriterOperationOutcome(
            response=rpc_error(
                request_id,
                code=INVALID_REQUEST,
                message="request_id and decision are required",
            )
        )
    try:
        resolution = await resolve_approval_request(
            request_id=approval_request_id,
            decision=decision,
            guidance=guidance,
            session_factory=session_factory,
        )
    except LookupError as exc:
        return WriterOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc))
        )
    except ValueError as exc:
        return WriterOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc))
        )
    event = resolution.event
    async with session_factory() as db:
        snapshot = await load_snapshot(db, event.thread_id)
    continuation = None
    if resolution.was_open:
        continuation = {
            "request_id": approval_request_id,
            "thread_id": event.thread_id,
            "decision": decision,
            "guidance": guidance or "",
        }
    return WriterOperationOutcome(
        response=rpc_result(
            request_id,
            {
                "event": event.model_dump(mode="json"),
                "snapshot": snapshot,
            },
        ),
        notify_events=[event],
        continuation=continuation,
    )


def _handler(handler: OperationRpcHandler):
    async def run(request: OperationRequest) -> OperationResult:
        rpc_request = request.metadata.get("rpc_request")
        if not isinstance(rpc_request, JsonRpcRequest):
            raise TypeError("rpc_request metadata is required")
        await handler(rpc_request)
        return OperationResult(name=request.name)

    return run


def _bounded_int(value: object, *, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


__all__ = [
    "OPERATION_ALIASES",
    "ApprovalResolution",
    "WriterOperationOutcome",
    "build_writer_operation_catalog",
    "handle_attachment_get_operation",
    "handle_attachment_list_operation",
    "handle_attachment_open_operation",
    "handle_attachment_preview_operation",
    "handle_artifact_open_operation",
    "handle_artifact_read_operation",
    "handle_approval_respond_operation",
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
    "handle_project_create_operation",
    "handle_project_agents_md_get_operation",
    "handle_project_agents_md_update_operation",
    "handle_project_delete_operation",
    "handle_project_get_operation",
    "handle_project_list_operation",
    "handle_project_sessions_list_operation",
    "handle_project_update_operation",
    "handle_queue_create_operation",
    "handle_queue_delete_operation",
    "handle_queue_update_operation",
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
    "handle_turn_cancel_operation",
    "handle_turn_start_operation",
    "handle_turn_steer_operation",
    "handle_thread_read_operation",
    "handle_thread_resume_operation",
    "handle_thread_start_operation",
    "operation_name",
    "resolve_approval_request",
]
