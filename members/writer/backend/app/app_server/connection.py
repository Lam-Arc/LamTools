from __future__ import annotations

import asyncio
from typing import Any

from fastapi import WebSocket

from app.database import async_session
from app.shared_config_database import shared_config_session
from lamtools_core.app import (
    CoreLiveConnection,
    CoreLiveConnectionAdapter,
    CoreLiveContext,
    CoreLiveOperationHost,
    OperationCatalog,
)
from lamtools_core.runtime import default_runtime_task_registry

from .hub import hub
from .operations import (
    build_writer_core_operation_adapter_catalog,
    build_writer_operation_catalog,
    handle_attachment_get_operation,
    handle_attachment_list_operation,
    handle_attachment_open_operation,
    handle_attachment_preview_operation,
    handle_project_create_operation,
    handle_project_agents_md_get_operation,
    handle_project_agents_md_update_operation,
    handle_project_delete_operation,
    handle_project_directory_pick_operation,
    handle_project_get_operation,
    handle_project_list_operation,
    handle_project_sessions_list_operation,
    handle_project_update_operation,
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
    operation_name,
)
from .protocol import PROTOCOL_VERSION, JsonRpcRequest
from .runtime import WriterRuntimeLifecycle
from .member_adapter import WriterLiveMemberAdapter
from .persistence import _PERSISTENCE_HOST


NOT_INITIALIZED = -32002
SERVER_ERROR = -32000
METHOD_NOT_FOUND = -32601


def _writer_live_operation_host(*, member_hooks: WriterLiveMemberAdapter, runtime_task_registry: Any) -> CoreLiveOperationHost:
    return CoreLiveOperationHost(
        session_factory=async_session,
        persistence=_PERSISTENCE_HOST,
        hub=hub,
        runtime_task_registry=runtime_task_registry,
        member_hooks=member_hooks,
    )


async def _writer_handle_client_response(connection: CoreLiveConnection, raw: dict[str, Any]) -> bool:
    if (
        isinstance(raw, dict)
        and "method" not in raw
        and "id" in raw
        and ("result" in raw or "error" in raw)
    ):
        await connection._resolve_client_response(raw)
        return True
    return False


def _writer_after_initialize(connection: CoreLiveConnection, params: Any) -> None:
    connection.last_seen_seq = params.lastSeenSeq or 0


class WriterAppServerConnection(CoreLiveConnection):
    def __init__(
        self,
        websocket: WebSocket,
        *,
        outbound_limit: int = 256,
        runtime: WriterRuntimeLifecycle | None = None,
    ) -> None:
        runtime_lifecycle = runtime or WriterRuntimeLifecycle(session_factory=async_session)
        member_hooks = WriterLiveMemberAdapter(
            session_factory=lambda: async_session(),
            runtime=runtime_lifecycle,
        )
        core_operation_adapters = build_writer_core_operation_adapter_catalog(
            session_factory=async_session,
            config_session_factory=shared_config_session,
            runtime=runtime_lifecycle,
            emit_event=hub.publish,
        )
        super().__init__(
            websocket,
            context=CoreLiveContext(
                operations=core_operation_adapters,
                host=_writer_live_operation_host(
                    member_hooks=member_hooks,
                    runtime_task_registry=getattr(
                        runtime_lifecycle, "runtime_task_registry", default_runtime_task_registry()
                    ),
                ),
            ),
            outbound_limit=outbound_limit,
            adapter=CoreLiveConnectionAdapter(
                protocol_version=PROTOCOL_VERSION,
                server_name="writer_app_server",
                server_title="Writer App Server",
                accept_initialized_ack=True,
                invalid_request_message="Invalid request",
                not_initialized_code=NOT_INITIALIZED,
                not_initialized_message="Not initialized",
                handle_client_response=_writer_handle_client_response,
                after_initialize=_writer_after_initialize,
                operation_catalog_factory=lambda connection: connection._operation_catalog(),
                normalize_operation_name=operation_name,
                handle_unknown_operations=True,
                operation_error_code=SERVER_ERROR,
                method_not_found_code=METHOD_NOT_FOUND,
            ),
        )
        self.last_seen_seq = 0
        self.runtime = runtime_lifecycle

    def _operation_catalog(self) -> OperationCatalog:
        core_handlers = self.context.host.operation_handlers()
        return build_writer_operation_catalog(
            project_create=self._project_create,
            project_directory_pick=self._project_directory_pick,
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
            core_handlers=core_handlers,
        )

    async def _resolve_client_response(self, raw: dict[str, Any]) -> None:
        request_id = str(raw.get("id") or "")
        result = raw.get("result") if isinstance(raw.get("result"), dict) else {}
        if not request_id:
            return
        params = dict(result)
        params.setdefault("request_id", request_id)
        outcome = await self.context.host.execute(
            "approval.respond",
            request_id=None,
            params=params,
            context=self.context,
        )
        await self.send_operation_outcome(
            outcome,
            send_response="error" in outcome.response,
            publish_events=False,
            send_snapshot=True,
        )

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

    async def _project_directory_pick(self, request: JsonRpcRequest) -> None:
        outcome = await handle_project_directory_pick_operation(
            request_id=request.id,
            params=request.params,
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
