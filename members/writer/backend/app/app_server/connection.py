from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.database import async_session
from lamtools_core.app import OperationCatalog

from .hub import hub
from .operations import (
    build_writer_operation_catalog,
    handle_config_adapter_profiles_list_operation,
    handle_config_provider_create_operation,
    handle_config_provider_delete_operation,
    handle_config_provider_update_operation,
    handle_config_runtime_capabilities_get_operation,
    handle_config_subagent_delete_operation,
    handle_config_subagent_upsert_operation,
    handle_config_model_create_operation,
    handle_config_model_delete_operation,
    handle_config_model_update_operation,
    handle_config_models_list_operation,
    handle_config_import_env_operation,
    handle_config_providers_list_operation,
    handle_config_resolved_get_operation,
    handle_attachment_get_operation,
    handle_attachment_list_operation,
    handle_attachment_open_operation,
    handle_attachment_preview_operation,
    handle_artifact_open_operation,
    handle_artifact_read_operation,
    handle_approval_respond_operation,
    handle_command_catalog_operation,
    handle_command_execute_operation,
    handle_project_create_operation,
    handle_project_agents_md_get_operation,
    handle_project_agents_md_update_operation,
    handle_project_delete_operation,
    handle_project_get_operation,
    handle_project_list_operation,
    handle_project_sessions_list_operation,
    handle_project_update_operation,
    handle_queue_create_operation,
    handle_queue_delete_operation,
    handle_queue_update_operation,
    handle_session_create_operation,
    handle_session_delete_operation,
    handle_session_changes_get_operation,
    handle_session_checkpoint_create_operation,
    handle_session_checkpoint_restore_operation,
    handle_session_checkpoints_list_operation,
    handle_session_commit_review_decide_operation,
    handle_session_commit_review_get_operation,
    handle_session_agent_branch_abandon_operation,
    handle_session_agent_branch_diff_operation,
    handle_session_agent_branch_merge_operation,
    handle_session_agent_branches_list_operation,
    handle_session_change_file_open_operation,
    handle_session_change_file_undo_operation,
    handle_session_changes_undo_operation,
    handle_session_fork_operation,
    handle_session_git_graph_get_operation,
    handle_session_get_operation,
    handle_session_list_operation,
    handle_session_rollback_turn_operation,
    handle_session_update_operation,
    handle_settings_get_operation,
    handle_settings_update_operation,
    handle_thread_read_operation,
    handle_thread_resume_operation,
    handle_thread_start_operation,
    handle_turn_cancel_operation,
    handle_turn_start_operation,
    handle_turn_steer_operation,
    operation_name,
    resolve_approval_request,
)
from .protocol import InitializeParams, JsonRpcRequest, event_notification, rpc_error, rpc_result
from .runtime import WriterRuntimeLifecycle
from .snapshot import load_snapshot


NOT_INITIALIZED = -32002
OVERLOADED = -32001
SERVER_ERROR = -32000
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
logger = logging.getLogger(__name__)


class WriterAppServerConnection:
    def __init__(
        self,
        websocket: WebSocket,
        *,
        outbound_limit: int = 256,
        runtime: WriterRuntimeLifecycle | None = None,
    ) -> None:
        self.websocket = websocket
        self.initialized = False
        self.thread_id: str | None = None
        self.last_seen_seq = 0
        self.outbound: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=outbound_limit)
        self.subscription: asyncio.Queue | None = None
        self.runtime = runtime or WriterRuntimeLifecycle(session_factory=async_session)

    async def run(self) -> None:
        await self.websocket.accept()
        sender = asyncio.create_task(self._sender())
        hub_reader = asyncio.create_task(self._hub_reader())
        try:
            while True:
                try:
                    raw = await self.websocket.receive_json()
                except WebSocketDisconnect:
                    break
                await self._handle_raw(raw)
        finally:
            sender.cancel()
            hub_reader.cancel()
            self._unsubscribe()

    async def _sender(self) -> None:
        while True:
            message = await self.outbound.get()
            await self.websocket.send_json(message)

    async def _send(self, message: dict[str, Any]) -> None:
        try:
            self.outbound.put_nowait(message)
        except asyncio.QueueFull:
            await self.websocket.close(code=1013, reason="Server overloaded; retry later.")

    async def _send_snapshot(self, thread_id: str) -> None:
        async with async_session() as db:
            snapshot = await load_snapshot(db, thread_id)
        await self._send({"method": "thread/snapshot", "params": snapshot})

    async def _hub_reader(self) -> None:
        while True:
            if self.subscription is None:
                await asyncio.sleep(0.05)
                continue
            event = await self.subscription.get()
            if event is not None:
                await self._send(event_notification(event))
                await self._send_snapshot(event.thread_id)

    def _subscribe(self, thread_id: str) -> None:
        if self.thread_id == thread_id and self.subscription is not None:
            return
        self._unsubscribe()
        self.thread_id = thread_id
        self.subscription = hub.subscribe(thread_id)

    def _unsubscribe(self) -> None:
        if self.thread_id and self.subscription is not None:
            hub.unsubscribe(self.thread_id, self.subscription)
        self.subscription = None

    async def _handle_raw(self, raw: dict[str, Any]) -> None:
        if (
            isinstance(raw, dict)
            and "method" not in raw
            and "id" in raw
            and ("result" in raw or "error" in raw)
        ):
            await self._handle_client_response(raw)
            return

        try:
            request = JsonRpcRequest.model_validate(raw)
        except ValidationError as exc:
            await self._send(rpc_error(raw.get("id") if isinstance(raw, dict) else None, code=INVALID_REQUEST, message="Invalid request", data={"errors": exc.errors()}))
            return

        if request.method == "initialized":
            await self._send(rpc_result(request.id, {"ok": True}))
            return

        if request.method == "initialize":
            await self._initialize(request)
            return

        if not self.initialized:
            await self._send(rpc_error(request.id, code=NOT_INITIALIZED, message="Not initialized"))
            return

        operation = self._operation_catalog()
        normalized_operation_name = operation_name(request.method)
        if operation.has(normalized_operation_name):
            try:
                await operation.execute(normalized_operation_name, metadata={"rpc_request": request})
            except Exception as exc:
                logger.exception("Writer app-server operation failed: %s", normalized_operation_name)
                await self._send(rpc_error(request.id, code=SERVER_ERROR, message=str(exc)))
            return

        await self._send(rpc_error(request.id, code=METHOD_NOT_FOUND, message=f"Unsupported method: {request.method}"))

    def _operation_catalog(self) -> OperationCatalog:
        return build_writer_operation_catalog(
            thread_read=self._thread_read,
            thread_resume=self._thread_resume,
            thread_start=self._thread_start,
            turn_start=self._turn_start,
            turn_steer=self._turn_steer,
            turn_cancel=self._turn_interrupt,
            approval_respond=self._approval_respond,
            queue_create=self._queue_create,
            queue_update=self._queue_update,
            queue_delete=self._queue_delete,
            project_create=self._project_create,
            project_get=self._project_get,
            project_list=self._project_list,
            project_update=self._project_update,
            project_delete=self._project_delete,
            project_agents_md_get=self._project_agents_md_get,
            project_agents_md_update=self._project_agents_md_update,
            project_sessions_list=self._project_sessions_list,
            attachment_list=self._attachment_list,
            attachment_get=self._attachment_get,
            attachment_preview=self._attachment_preview,
            attachment_open=self._attachment_open,
            artifact_read=self._artifact_read,
            artifact_open=self._artifact_open,
            command_catalog=self._command_catalog,
            command_execute=self._command_execute,
            session_create=self._session_create,
            session_get=self._session_get,
            session_list=self._session_list,
            session_update=self._session_update,
            session_delete=self._session_delete,
            session_fork=self._session_fork,
            session_git_graph=self._session_git_graph,
            session_changes_get=self._session_changes_get,
            session_checkpoints_list=self._session_checkpoints_list,
            session_checkpoint_create=self._session_checkpoint_create,
            session_checkpoint_restore=self._session_checkpoint_restore,
            session_commit_review_get=self._session_commit_review_get,
            session_commit_review_decide=self._session_commit_review_decide,
            session_agent_branches_list=self._session_agent_branches_list,
            session_agent_branch_diff=self._session_agent_branch_diff,
            session_agent_branch_merge=self._session_agent_branch_merge,
            session_agent_branch_abandon=self._session_agent_branch_abandon,
            session_rollback_turn=self._session_rollback_turn,
            session_changes_undo=self._session_changes_undo,
            session_change_file_open=self._session_change_file_open,
            session_change_file_undo=self._session_change_file_undo,
            settings_get=self._settings_get,
            settings_update=self._settings_update,
            config_providers_list=self._config_providers_list,
            config_provider_create=self._config_provider_create,
            config_provider_update=self._config_provider_update,
            config_provider_delete=self._config_provider_delete,
            config_models_list=self._config_models_list,
            config_model_create=self._config_model_create,
            config_model_update=self._config_model_update,
            config_model_delete=self._config_model_delete,
            config_import_env=self._config_import_env,
            config_resolved_get=self._config_resolved_get,
            config_adapter_profiles_list=self._config_adapter_profiles_list,
            config_runtime_capabilities_get=self._config_runtime_capabilities_get,
            config_subagent_upsert=self._config_subagent_upsert,
            config_subagent_delete=self._config_subagent_delete,
        )

    async def _handle_client_response(self, raw: dict[str, Any]) -> None:
        request_id = str(raw.get("id") or "")
        result = raw.get("result") if isinstance(raw.get("result"), dict) else {}
        decision = str(result.get("decision") or "")
        if not request_id or not decision:
            return
        guidance = result.get("guidance") if isinstance(result.get("guidance"), str) else None
        try:
            resolution = await resolve_approval_request(
                request_id=request_id,
                decision=decision,
                guidance=guidance,
                session_factory=async_session,
            )
        except (LookupError, ValueError):
            return
        event = resolution.event
        await self._send(event_notification(event))
        await self._send_snapshot(event.thread_id)
        if resolution.was_open:
            asyncio.create_task(
                self._continue_resolved_approval(
                    request_id=request_id,
                    thread_id=event.thread_id,
                    decision=decision,
                    guidance=guidance or "",
                )
            )

    async def _initialize(self, request: JsonRpcRequest) -> None:
        if self.initialized:
            await self._send(rpc_error(request.id, code=INVALID_REQUEST, message="Already initialized"))
            return
        try:
            params = InitializeParams.model_validate(request.params)
        except ValidationError as exc:
            await self._send(rpc_error(request.id, code=INVALID_REQUEST, message="Invalid initialize params", data={"errors": exc.errors()}))
            return
        self.initialized = True
        if params.threadId:
            self._subscribe(params.threadId)
        self.last_seen_seq = params.lastSeenSeq or 0
        await self._send(
            rpc_result(
                request.id,
                {
                    "protocolVersion": "writer.app_server.v1",
                    "serverInfo": {"name": "writer_app_server", "title": "Writer App Server"},
                },
            )
        )

    async def _thread_start(self, request: JsonRpcRequest) -> None:
        thread_id = str(request.params.get("thread_id") or request.params.get("threadId") or "")
        outcome = await handle_thread_start_operation(
            request_id=request.id,
            params=request.params,
            session_factory=async_session,
        )
        await self._send(outcome.response)
        if not outcome.publish_events:
            return
        self._subscribe(thread_id)
        for event in outcome.publish_events:
            await hub.publish(event)

    async def _thread_resume(self, request: JsonRpcRequest) -> None:
        thread_id = str(request.params.get("thread_id") or request.params.get("threadId") or self.thread_id or "")
        outcome = await handle_thread_resume_operation(
            request_id=request.id,
            params=request.params,
            current_thread_id=self.thread_id,
            session_factory=async_session,
        )
        if thread_id:
            self._subscribe(thread_id)
        await self._send(outcome.response)

    async def _thread_read(self, request: JsonRpcRequest) -> None:
        outcome = await handle_thread_read_operation(
            request_id=request.id,
            params=request.params,
            current_thread_id=self.thread_id,
            session_factory=async_session,
        )
        await self._send(outcome.response)

    async def _session_list(self, request: JsonRpcRequest) -> None:
        outcome = await handle_session_list_operation(
            request_id=request.id,
            params=request.params,
            session_factory=async_session,
        )
        await self._send(outcome.response)

    async def _session_create(self, request: JsonRpcRequest) -> None:
        outcome = await handle_session_create_operation(
            request_id=request.id,
            params=request.params,
            session_factory=async_session,
        )
        await self._send(outcome.response)

    async def _session_get(self, request: JsonRpcRequest) -> None:
        outcome = await handle_session_get_operation(
            request_id=request.id,
            params=request.params,
            session_factory=async_session,
        )
        await self._send(outcome.response)

    async def _session_update(self, request: JsonRpcRequest) -> None:
        outcome = await handle_session_update_operation(
            request_id=request.id,
            params=request.params,
            session_factory=async_session,
        )
        await self._send(outcome.response)

    async def _session_delete(self, request: JsonRpcRequest) -> None:
        outcome = await handle_session_delete_operation(
            request_id=request.id,
            params=request.params,
            session_factory=async_session,
        )
        await self._send(outcome.response)

    async def _session_fork(self, request: JsonRpcRequest) -> None:
        outcome = await handle_session_fork_operation(
            request_id=request.id,
            params=request.params,
            session_factory=async_session,
        )
        await self._send(outcome.response)

    async def _session_git_graph(self, request: JsonRpcRequest) -> None:
        outcome = await handle_session_git_graph_get_operation(
            request_id=request.id,
            params=request.params,
            session_factory=async_session,
        )
        await self._send(outcome.response)

    async def _session_changes_get(self, request: JsonRpcRequest) -> None:
        outcome = await handle_session_changes_get_operation(
            request_id=request.id,
            params=request.params,
            session_factory=async_session,
        )
        await self._send(outcome.response)

    async def _session_checkpoints_list(self, request: JsonRpcRequest) -> None:
        outcome = await handle_session_checkpoints_list_operation(
            request_id=request.id,
            params=request.params,
            session_factory=async_session,
        )
        await self._send(outcome.response)

    async def _session_checkpoint_create(self, request: JsonRpcRequest) -> None:
        outcome = await handle_session_checkpoint_create_operation(
            request_id=request.id,
            params=request.params,
            session_factory=async_session,
        )
        await self._send(outcome.response)

    async def _session_checkpoint_restore(self, request: JsonRpcRequest) -> None:
        outcome = await handle_session_checkpoint_restore_operation(
            request_id=request.id,
            params=request.params,
            session_factory=async_session,
        )
        await self._send(outcome.response)

    async def _session_commit_review_get(self, request: JsonRpcRequest) -> None:
        outcome = await handle_session_commit_review_get_operation(
            request_id=request.id,
            params=request.params,
            session_factory=async_session,
        )
        await self._send(outcome.response)

    async def _session_commit_review_decide(self, request: JsonRpcRequest) -> None:
        outcome = await handle_session_commit_review_decide_operation(
            request_id=request.id,
            params=request.params,
            session_factory=async_session,
        )
        await self._send(outcome.response)

    async def _session_agent_branches_list(self, request: JsonRpcRequest) -> None:
        outcome = await handle_session_agent_branches_list_operation(
            request_id=request.id,
            params=request.params,
            session_factory=async_session,
        )
        await self._send(outcome.response)

    async def _session_agent_branch_diff(self, request: JsonRpcRequest) -> None:
        outcome = await handle_session_agent_branch_diff_operation(
            request_id=request.id,
            params=request.params,
            session_factory=async_session,
        )
        await self._send(outcome.response)

    async def _session_agent_branch_merge(self, request: JsonRpcRequest) -> None:
        outcome = await handle_session_agent_branch_merge_operation(
            request_id=request.id,
            params=request.params,
            session_factory=async_session,
        )
        await self._send(outcome.response)

    async def _session_agent_branch_abandon(self, request: JsonRpcRequest) -> None:
        outcome = await handle_session_agent_branch_abandon_operation(
            request_id=request.id,
            params=request.params,
            session_factory=async_session,
        )
        await self._send(outcome.response)

    async def _session_rollback_turn(self, request: JsonRpcRequest) -> None:
        outcome = await handle_session_rollback_turn_operation(
            request_id=request.id,
            params=request.params,
            session_factory=async_session,
        )
        await self._send(outcome.response)
        for event in outcome.publish_events:
            await hub.publish(event)

    async def _session_changes_undo(self, request: JsonRpcRequest) -> None:
        outcome = await handle_session_changes_undo_operation(
            request_id=request.id,
            params=request.params,
            session_factory=async_session,
        )
        await self._send(outcome.response)

    async def _session_change_file_open(self, request: JsonRpcRequest) -> None:
        outcome = await handle_session_change_file_open_operation(
            request_id=request.id,
            params=request.params,
            session_factory=async_session,
        )
        await self._send(outcome.response)

    async def _session_change_file_undo(self, request: JsonRpcRequest) -> None:
        outcome = await handle_session_change_file_undo_operation(
            request_id=request.id,
            params=request.params,
            session_factory=async_session,
        )
        await self._send(outcome.response)

    async def _project_list(self, request: JsonRpcRequest) -> None:
        outcome = await handle_project_list_operation(
            request_id=request.id,
            params=request.params,
            session_factory=async_session,
        )
        await self._send(outcome.response)

    async def _project_create(self, request: JsonRpcRequest) -> None:
        outcome = await handle_project_create_operation(
            request_id=request.id,
            params=request.params,
            session_factory=async_session,
        )
        await self._send(outcome.response)

    async def _project_get(self, request: JsonRpcRequest) -> None:
        outcome = await handle_project_get_operation(
            request_id=request.id,
            params=request.params,
            session_factory=async_session,
        )
        await self._send(outcome.response)

    async def _project_update(self, request: JsonRpcRequest) -> None:
        outcome = await handle_project_update_operation(
            request_id=request.id,
            params=request.params,
            session_factory=async_session,
        )
        await self._send(outcome.response)

    async def _project_delete(self, request: JsonRpcRequest) -> None:
        outcome = await handle_project_delete_operation(
            request_id=request.id,
            params=request.params,
            session_factory=async_session,
        )
        await self._send(outcome.response)

    async def _project_agents_md_get(self, request: JsonRpcRequest) -> None:
        outcome = await handle_project_agents_md_get_operation(
            request_id=request.id,
            params=request.params,
            session_factory=async_session,
        )
        await self._send(outcome.response)

    async def _project_agents_md_update(self, request: JsonRpcRequest) -> None:
        outcome = await handle_project_agents_md_update_operation(
            request_id=request.id,
            params=request.params,
            session_factory=async_session,
        )
        await self._send(outcome.response)

    async def _project_sessions_list(self, request: JsonRpcRequest) -> None:
        outcome = await handle_project_sessions_list_operation(
            request_id=request.id,
            params=request.params,
            session_factory=async_session,
        )
        await self._send(outcome.response)

    async def _attachment_list(self, request: JsonRpcRequest) -> None:
        outcome = await handle_attachment_list_operation(
            request_id=request.id,
            params=request.params,
            session_factory=async_session,
        )
        await self._send(outcome.response)

    async def _attachment_get(self, request: JsonRpcRequest) -> None:
        outcome = await handle_attachment_get_operation(
            request_id=request.id,
            params=request.params,
            session_factory=async_session,
        )
        await self._send(outcome.response)

    async def _attachment_preview(self, request: JsonRpcRequest) -> None:
        outcome = await handle_attachment_preview_operation(
            request_id=request.id,
            params=request.params,
            session_factory=async_session,
        )
        await self._send(outcome.response)

    async def _attachment_open(self, request: JsonRpcRequest) -> None:
        outcome = await handle_attachment_open_operation(
            request_id=request.id,
            params=request.params,
            session_factory=async_session,
        )
        await self._send(outcome.response)

    async def _settings_get(self, request: JsonRpcRequest) -> None:
        outcome = await handle_settings_get_operation(
            request_id=request.id,
            params=request.params,
            session_factory=async_session,
        )
        await self._send(outcome.response)

    async def _settings_update(self, request: JsonRpcRequest) -> None:
        outcome = await handle_settings_update_operation(
            request_id=request.id,
            params=request.params,
            session_factory=async_session,
        )
        await self._send(outcome.response)

    async def _config_providers_list(self, request: JsonRpcRequest) -> None:
        outcome = await handle_config_providers_list_operation(
            request_id=request.id,
            params=request.params,
            session_factory=async_session,
        )
        await self._send(outcome.response)

    async def _config_provider_create(self, request: JsonRpcRequest) -> None:
        outcome = await handle_config_provider_create_operation(
            request_id=request.id,
            params=request.params,
            session_factory=async_session,
        )
        await self._send(outcome.response)

    async def _config_provider_update(self, request: JsonRpcRequest) -> None:
        outcome = await handle_config_provider_update_operation(
            request_id=request.id,
            params=request.params,
            session_factory=async_session,
        )
        await self._send(outcome.response)

    async def _config_provider_delete(self, request: JsonRpcRequest) -> None:
        outcome = await handle_config_provider_delete_operation(
            request_id=request.id,
            params=request.params,
            session_factory=async_session,
        )
        await self._send(outcome.response)

    async def _config_models_list(self, request: JsonRpcRequest) -> None:
        outcome = await handle_config_models_list_operation(
            request_id=request.id,
            params=request.params,
            session_factory=async_session,
        )
        await self._send(outcome.response)

    async def _config_model_create(self, request: JsonRpcRequest) -> None:
        outcome = await handle_config_model_create_operation(
            request_id=request.id,
            params=request.params,
            session_factory=async_session,
        )
        await self._send(outcome.response)

    async def _config_model_update(self, request: JsonRpcRequest) -> None:
        outcome = await handle_config_model_update_operation(
            request_id=request.id,
            params=request.params,
            session_factory=async_session,
        )
        await self._send(outcome.response)

    async def _config_model_delete(self, request: JsonRpcRequest) -> None:
        outcome = await handle_config_model_delete_operation(
            request_id=request.id,
            params=request.params,
            session_factory=async_session,
        )
        await self._send(outcome.response)

    async def _config_import_env(self, request: JsonRpcRequest) -> None:
        outcome = await handle_config_import_env_operation(
            request_id=request.id,
            params=request.params,
            session_factory=async_session,
        )
        await self._send(outcome.response)

    async def _config_resolved_get(self, request: JsonRpcRequest) -> None:
        outcome = await handle_config_resolved_get_operation(
            request_id=request.id,
            params=request.params,
            session_factory=async_session,
        )
        await self._send(outcome.response)

    async def _config_adapter_profiles_list(self, request: JsonRpcRequest) -> None:
        outcome = await handle_config_adapter_profiles_list_operation(
            request_id=request.id,
            params=request.params,
        )
        await self._send(outcome.response)

    async def _config_runtime_capabilities_get(self, request: JsonRpcRequest) -> None:
        outcome = await handle_config_runtime_capabilities_get_operation(
            request_id=request.id,
            params=request.params,
            session_factory=async_session,
        )
        await self._send(outcome.response)

    async def _config_subagent_upsert(self, request: JsonRpcRequest) -> None:
        outcome = await handle_config_subagent_upsert_operation(
            request_id=request.id,
            params=request.params,
            session_factory=async_session,
        )
        await self._send(outcome.response)

    async def _config_subagent_delete(self, request: JsonRpcRequest) -> None:
        outcome = await handle_config_subagent_delete_operation(
            request_id=request.id,
            params=request.params,
        )
        await self._send(outcome.response)

    async def _turn_start(self, request: JsonRpcRequest) -> None:
        outcome = await handle_turn_start_operation(
            request_id=request.id,
            params=request.params,
            current_thread_id=self.thread_id,
            session_factory=async_session,
        )
        await self._send(outcome.response)
        for event in outcome.notify_events:
            await self._send(event_notification(event))
        if outcome.runtime_start:
            self._start_writer_runtime(**outcome.runtime_start)

    def _start_writer_runtime(
        self,
        *,
        thread_id: str,
        turn_id: str,
        user_message_id: str,
        text: str,
        work_root: object = None,
        thinking_enabled: bool | None = None,
        thinking_budget: int | None = None,
        shallow_thinking_enabled: bool | None = None,
        model_id: str | None = None,
        attachment_ids: list[str] | None = None,
    ) -> None:
        self.runtime.start(
            thread_id=thread_id,
            turn_id=turn_id,
            user_message_id=user_message_id,
            text=text,
            work_root=work_root,
            thinking_enabled=thinking_enabled,
            thinking_budget=thinking_budget,
            shallow_thinking_enabled=shallow_thinking_enabled,
            model_id=model_id,
            attachment_ids=attachment_ids,
        )

    async def _approval_respond(self, request: JsonRpcRequest) -> None:
        outcome = await handle_approval_respond_operation(
            request_id=request.id,
            params=request.params,
            session_factory=async_session,
        )
        await self._send(outcome.response)
        for event in outcome.notify_events:
            await self._send(event_notification(event))
        if outcome.continuation:
            asyncio.create_task(
                self._continue_resolved_approval(
                    request_id=outcome.continuation["request_id"],
                    thread_id=outcome.continuation["thread_id"],
                    decision=outcome.continuation["decision"],
                    guidance=outcome.continuation["guidance"],
                )
            )

    async def _artifact_read(self, request: JsonRpcRequest) -> None:
        outcome = await handle_artifact_read_operation(
            request_id=request.id,
            params=request.params,
            current_thread_id=self.thread_id,
            session_factory=async_session,
        )
        await self._send(outcome.response)

    async def _artifact_open(self, request: JsonRpcRequest) -> None:
        outcome = await handle_artifact_open_operation(
            request_id=request.id,
            params=request.params,
            current_thread_id=self.thread_id,
            session_factory=async_session,
        )
        await self._send(outcome.response)

    async def _command_catalog(self, request: JsonRpcRequest) -> None:
        outcome = await handle_command_catalog_operation(
            request_id=request.id,
            params=request.params,
        )
        await self._send(outcome.response)

    async def _command_execute(self, request: JsonRpcRequest) -> None:
        thread_id = str(
            request.params.get("thread_id")
            or request.params.get("threadId")
            or request.params.get("session_id")
            or request.params.get("sessionId")
            or self.thread_id
            or ""
        )
        if thread_id:
            self._subscribe(thread_id)
        outcome = await handle_command_execute_operation(
            request_id=request.id,
            params=request.params,
            session_factory=async_session,
            writer_service=self.runtime.writer_service_or_none(),
            emit_event=hub.publish,
        )
        await self._send(outcome.response)
        for event in outcome.publish_events:
            await self._send(event_notification(event))

    async def _dispatch_next_queue_item(self, *, thread_id: str, work_root: object = None) -> None:
        await self.runtime.dispatch_next_queue_item(thread_id=thread_id, work_root=work_root)

    async def _continue_resolved_approval(
        self,
        *,
        request_id: str,
        thread_id: str,
        decision: str,
        guidance: str = "",
    ) -> None:
        await self.runtime.continue_resolved_approval(
            request_id=request_id,
            thread_id=thread_id,
            decision=decision,
            guidance=guidance,
        )

    async def _queue_create(self, request: JsonRpcRequest) -> None:
        outcome = await handle_queue_create_operation(
            request_id=request.id,
            params=request.params,
            current_thread_id=self.thread_id,
            session_factory=async_session,
        )
        await self._send(outcome.response)
        for event in outcome.notify_events:
            await self._send(event_notification(event))

    async def _turn_steer(self, request: JsonRpcRequest) -> None:
        outcome = await handle_turn_steer_operation(
            request_id=request.id,
            params=request.params,
            current_thread_id=self.thread_id,
            session_factory=async_session,
        )
        await self._send(outcome.response)
        for event in outcome.notify_events:
            await self._send(event_notification(event))

    async def _turn_interrupt(self, request: JsonRpcRequest) -> None:
        outcome = await handle_turn_cancel_operation(
            request_id=request.id,
            params=request.params,
            current_thread_id=self.thread_id,
            session_factory=async_session,
        )
        await self._send(outcome.response)
        for event in outcome.publish_events:
            await hub.publish(event)

    async def _queue_update(self, request: JsonRpcRequest) -> None:
        outcome = await handle_queue_update_operation(
            request_id=request.id,
            params=request.params,
            current_thread_id=self.thread_id,
            session_factory=async_session,
        )
        await self._send(outcome.response)
        for event in outcome.notify_events:
            await self._send(event_notification(event))

    async def _queue_delete(self, request: JsonRpcRequest) -> None:
        outcome = await handle_queue_delete_operation(
            request_id=request.id,
            params=request.params,
            current_thread_id=self.thread_id,
            session_factory=async_session,
        )
        await self._send(outcome.response)
        for event in outcome.notify_events:
            await self._send(event_notification(event))
