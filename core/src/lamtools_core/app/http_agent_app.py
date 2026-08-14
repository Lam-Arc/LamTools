"""FastAPI assembly for the standalone Core Agent HTTP app."""

from __future__ import annotations

import os
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any
import logging

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from lamtools_core.cli import (
    CoreHttpLLMClient,
    LLMConfig,
    _resolve_adapter_profile,
    _resolve_core_db,
    configure_model_store_context,
    list_llm_model_configs,
    load_llm_config,
)
from lamtools_core.http import create_core_router
from lamtools_core.llm import LLMRequest
from lamtools_core.config import build_config_operation_catalog
from lamtools_core.config.provider_store import ProviderConfig, ProviderStore, mask_api_key
from lamtools_core.config.root import ensure_projects_root
from lamtools_core.update.operations import build_update_operation_catalog
from lamtools_core.attachment import CoreAttachmentStore
from lamtools_core.attachment.service import MAX_ATTACHMENT_BYTES
from lamtools_core.runtime import RuntimeTaskRegistry
from lamtools_core.runtime.arrange import ArrangeManager, ArrangeRunner, arranged_operation_payload
from lamtools_core.runtime.goal import GoalManager
from lamtools_core.runtime.observer import ObserverSupervisor
from lamtools_core.runtime.workflow import WorkflowManager, WorkflowRunner
from lamtools_core.project.workflow_store import WorkflowStore
from lamtools_core.member import MemberKit, MemberManifest

from .core_db import open_core_app_db
from .core_session_store import CoreDbSessionStore
from .default_agent import CoreAgentPaths, CoreAgentSpec, create_core_agent_operations
from .durable_operations import register_durable_operations
from .workflow_operations import register_workflow_operations
from .event_store import AppEventInput
from .factory import add_spa_fallback, create_app
from .live_hub import CoreAppEventHub
from .live_member import DefaultCoreLiveMemberHooks
from .live_operations import CoreLiveContext, CoreLiveOperationHost, recover_stale_active_turns
from .project_store import ActiveProjectSessionsError, CoreProjectStore
from lamtools_core.artifact import ArtifactRegistry, kind_from_mime
from .live_router import create_core_live_router
from .operation_catalog import OperationCatalog, OperationRequest, OperationResult


_logger = logging.getLogger(__name__)


class CoreConfigRoutingLLMClient:
    """LLM client that resolves provider/model from jsonc config files per request."""

    def __init__(
        self,
        *,
        default_model_ref: str,
        adapter_dirs: tuple[Path | str, ...] = (),
        thinking_enabled: bool = True,
        thinking_budget: int = 10000,
        max_tokens: int | None = None,
        temperature: float = 0.2,
    ) -> None:
        self.default_model_ref = default_model_ref
        self.adapter_dirs = tuple(Path(item) for item in adapter_dirs)
        self.thinking_enabled = thinking_enabled
        self.thinking_budget = thinking_budget
        self.max_tokens = max_tokens
        self.temperature = temperature

    def with_runtime_options(
        self,
        *,
        model_id: str = "",
        thinking_enabled: bool | None = None,
        thinking_budget: int | None = None,
    ) -> "CoreConfigRoutingLLMClient":
        return CoreConfigRoutingLLMClient(
            default_model_ref=model_id or self.default_model_ref,
            adapter_dirs=self.adapter_dirs,
            thinking_enabled=self.thinking_enabled if thinking_enabled is None else thinking_enabled,
            thinking_budget=self.thinking_budget if thinking_budget is None else thinking_budget,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )

    async def complete(self, request: LLMRequest):
        config, client = self._client_for_request(request)
        return await client.complete(replace(request, model=config.model_id))

    async def stream(self, request: LLMRequest):
        config, client = self._client_for_request(request)
        async for event in client.stream(replace(request, model=config.model_id)):
            yield event

    def _client_for_request(self, request: LLMRequest) -> tuple[Any, CoreHttpLLMClient]:
        model_ref = str(request.model or self.default_model_ref or "").strip()
        try:
            config = load_llm_config(model_ref=model_ref)
        except ValueError:
            # Unknown model_ref — fall back to empty ref so the config
            # resolves the default model from the current config (not the
            # startup-cached default_model_ref). This prevents 100x retry
            # storms on a bad model parameter.
            config = load_llm_config(model_ref="")
        profile = _resolve_adapter_profile(config, self.adapter_dirs)
        metadata = request.metadata if isinstance(request.metadata, dict) else {}
        thinking_enabled = (
            metadata.get("thinking_enabled")
            if isinstance(metadata.get("thinking_enabled"), bool)
            else self.thinking_enabled
        )
        thinking_budget = (
            metadata.get("thinking_budget")
            if isinstance(metadata.get("thinking_budget"), int) and not isinstance(metadata.get("thinking_budget"), bool)
            else self.thinking_budget or config.thinking_budget
        )
        reasoning_effort = str(metadata.get("reasoning_effort") or "")
        return config, CoreHttpLLMClient(
            config=config,
            adapter_profile=profile,
            thinking_enabled=thinking_enabled,
            thinking_budget=thinking_budget,
            reasoning_effort=reasoning_effort,
            max_tokens=self.max_tokens or config.max_output_tokens,
            temperature=self.temperature if self.temperature is not None else config.temperature,
        )


class _MemberDefaultsHooks(DefaultCoreLiveMemberHooks):
    """Member hooks that inject member_defaults into thread materialization."""

    def __init__(self, member_defaults: dict[str, Any]) -> None:
        self._member_defaults = member_defaults

    async def materialize_thread(self, *, db, thread_id, params):
        session_defaults = self._member_defaults.get("session") if isinstance(self._member_defaults.get("session"), dict) else {}
        return dict(session_defaults) if session_defaults else {}

    async def materialize_turn(
        self, *, db, thread_id, turn_id, user_item_id, client_message_id, prepared, params
    ):
        materialized = await super().materialize_turn(
            db=db,
            thread_id=thread_id,
            turn_id=turn_id,
            user_item_id=user_item_id,
            client_message_id=client_message_id,
            prepared=prepared,
            params=params,
        )
        session_defaults = self._member_defaults.get("session") if isinstance(self._member_defaults.get("session"), dict) else {}
        if session_defaults:
            materialized = replace(
                materialized,
                turn_payload_extra={**materialized.turn_payload_extra, **session_defaults},
            )
        return materialized


def create_core_agent_http_app(
    *,
    agent_spec: CoreAgentSpec | None = None,
    member_kit: MemberKit | None = None,
    members: list[MemberManifest] | None = None,
    model_id: str = "",
    core_db: Path | str | None = None,
    data_dir: Path | str | None = None,
    work_root: Path | str | None = None,
    plugin_roots: tuple[Path | str, ...] = (),
    thinking_enabled: bool = True,
    thinking_budget: int = 10000,
    max_tokens: int | None = None,
    temperature: float = 0.2,
    frontend_dir: Path | str | None = None,
) -> FastAPI:
    try:
        config = load_llm_config(model_ref=model_id)
    except ValueError:
        # No usable model configured yet (no jsonc model/provider). Boot
        # with an unconfigured placeholder instead of crashing — the UI can
        # set up a real provider/model afterwards.
        _logger.warning(
            "Model %r not resolvable from jsonc config; booting with an unconfigured placeholder",
            model_id,
        )
        config = LLMConfig(
            provider_name="",
            provider_api_type="openai",
            base_url="",
            api_key="",
            model_record_id=str(model_id or ""),
            model_id=str(model_id or ""),
            display_name=str(model_id or ""),
        )
    llm_client = CoreConfigRoutingLLMClient(
        default_model_ref=model_id or config.model_record_id or config.model_id,
        thinking_enabled=thinking_enabled,
        thinking_budget=thinking_budget or config.thinking_budget,
        max_tokens=max_tokens,
        temperature=temperature if temperature is not None else config.temperature,
    )
    runtime_spec = agent_spec or CoreAgentSpec(
        default_model=config.model_id,
        instructions="You are LamTools Core Agent, a standalone general-purpose agent runtime.",
    )
    runtime_spec = replace(
        runtime_spec,
        default_model=runtime_spec.default_model or config.model_id,
        metadata={
            **runtime_spec.metadata,
            "provider": config.provider_name,
            "model_record_id": config.model_record_id,
            "thinking_enabled": thinking_enabled,
            "thinking_budget": thinking_budget or config.thinking_budget,
            "context_window": config.context_window,
            "capability": config.capability,
        },
    )

    core_db_path = _resolve_core_db(core_db)
    # Single work-root contract (audit 20 S4): unless explicitly overridden,
    # the agent work root is always projects_root/default — the Tauri shell
    # sets LAMTOOLS_PROJECTS_ROOT (prod: app_dir\lam_projects, dev/CLI:
    # repo\lam_projects), and desktop_backend.py no longer pre-sets a
    # divergent LAMTOOLS_CORE_WORK_ROOT, so dev/prod/CLI all converge here.
    resolved_work_root = Path(
        work_root
        or os.environ.get("LAMTOOLS_CORE_WORK_ROOT")
        or (ensure_projects_root() / "default")
    ).resolve()
    resolved_data_dir = Path(data_dir or os.environ.get("LAMTOOLS_CORE_DATA_DIR") or core_db_path.parent / "core-agent").resolve()
    resolved_work_root.mkdir(parents=True, exist_ok=True)
    resolved_data_dir.mkdir(parents=True, exist_ok=True)
    # Register the project work_root so load_llm_config resolves project-scoped
    # model jsonc files (models/providers are jsonc-only).
    configure_model_store_context(work_root=str(resolved_work_root))

    operations = OperationCatalog()
    app_state: dict[str, Any] = {}
    live_hub = CoreAppEventHub()
    runtime_task_registry = RuntimeTaskRegistry()
    session_store = CoreDbSessionStore(lambda: app_state["core_db"])

    async def execute_core_operation(request: OperationRequest) -> OperationResult:
        actual = app_state.get("operations")
        if not isinstance(actual, OperationCatalog):
            return OperationResult(name=request.name, status="error", payload={"error": "Core Agent is not ready"})
        return await actual.execute(request.name, request.payload, metadata=request.metadata)

    operations.register("turn.start", execute_core_operation)
    operations.register("approval.respond", execute_core_operation)

    # Expose config/project RPC operations directly so UI can query models/projects/sessions.

    async def _config_models_list(request: OperationRequest) -> OperationResult:
        del request
        return OperationResult(name="config.models.list", payload={
            "models": list_llm_model_configs(),
            "default_model_id": config.model_record_id,
        })

    async def _config_providers_list(request: OperationRequest) -> OperationResult:
        del request
        return OperationResult(name="config.providers.list", payload={
            "providers": _list_llm_provider_configs(),
        })

    async def _project_list(request: OperationRequest) -> OperationResult:
        del request
        return await execute_core_operation(OperationRequest(name="project.list", payload={}, metadata={}))

    async def _project_sessions_list(request: OperationRequest) -> OperationResult:
        return await execute_core_operation(OperationRequest(name="project.sessions.list", payload=request.payload, metadata={}))

    operations.register("config.models.list", _config_models_list)
    operations.register("config.providers.list", _config_providers_list)
    operations.register("project.list", _project_list)
    operations.register("project.sessions.list", _project_sessions_list)

    async def startup_core_agent() -> None:
        core_db_handle = await open_core_app_db(
            core_db_path,
            member_defaults={"session": {"member_id": runtime_spec.member_id}},
        )
        app_state["core_db"] = core_db_handle
        app_state["attachment_store"] = CoreAttachmentStore(core_db_handle.session_factory, resolved_data_dir)
        goal_manager = GoalManager(core_db_handle.goal_store)
        arrange_manager = ArrangeManager(core_db_handle.arrange_store)

        def _resolve_model_display(model_id: str) -> str:
            # jsonc-only: resolve "<provider>/<model>" from the model store.
            try:
                from lamtools_core.config.model_store import ModelStore

                model = ModelStore().get_sync(model_id)
                if model is None:
                    return ""
                if model.provider and model.display_name:
                    return f"{model.provider}/{model.display_name}"
                return model.display_name or model.model_id
            except Exception:
                return ""

        workflow_store = WorkflowStore()
        agent_operations = create_core_agent_operations(
            spec=runtime_spec,
            member_kit=member_kit,
            paths=CoreAgentPaths(data_dir=resolved_data_dir, work_root=resolved_work_root),
            model_provider=llm_client,
            plugin_roots=[Path(item) for item in plugin_roots],
            db_session_factory=core_db_handle.session_factory,
            app_event_store=core_db_handle.event_store,
            thread_snapshot_store=core_db_handle.snapshot_store,
            app_event_hub=live_hub,
            runtime_state_store=core_db_handle.runtime_state_store,
            runtime_task_registry=runtime_task_registry,
            goal_manager=goal_manager,
            arrange_manager=arrange_manager,
            workflow_store=workflow_store,
            enable_turn_checkpoints=True,
            model_display_resolver=_resolve_model_display,
            attachment_service=app_state.get("attachment_store"),
            memory_store=core_db_handle.memory_store,
        )
        _register_core_project_operations(agent_operations, project_store=core_db_handle.project_store)
        _register_core_artifact_operations(agent_operations, project_store=core_db_handle.project_store)
        _register_core_session_operations(agent_operations, session_store=session_store)
        _register_core_config_operations(
            agent_operations,
            default_model_id=config.model_record_id,
            work_root=resolved_work_root,
        )
        _register_missing_operations(agent_operations, build_config_operation_catalog(work_root=resolved_work_root, data_dir=resolved_data_dir))
        _register_missing_operations(agent_operations, build_update_operation_catalog())

        async def execute_arranged_job(job: Any) -> OperationResult:
            payload = arranged_operation_payload(job)
            if job.operation == "turn.start":
                payload["run_id"] = job.occurrence_id
                payload["turn_id"] = f"{job.thread_id}:turn:{job.occurrence_id}"
            if getattr(job, "model_id", ""):
                payload["model_id"] = job.model_id
            # Register new arrange threads as project sessions so the frontend
            # can associate them with the correct workspace.
            if job.session_strategy == "new":
                try:
                    session_title = job.title or f"Arrange: {(job.payload.get('message') or '')[:50]}"
                    await core_db_handle.project_store.ensure_session(
                        work_root=job.work_root,
                        session_id=job.thread_id,
                        title=session_title,
                    )
                    await live_hub.broadcast({
                        "method": "session/created",
                        "thread_id": job.thread_id,
                        "payload": {
                            "session_id": job.thread_id,
                            "title": session_title,
                            "work_root": job.work_root,
                        },
                    })
                except Exception:
                    pass  # best-effort registration; never block execution
            # Emit turn/accepted and item/started events so the arrange
            # instruction appears as a user message in the conversation,
            # matching the WebSocket turn-acceptance path exactly.
            if job.operation == "turn.start":
                message = (job.payload.get("message") or "").strip()
                if message:
                    turn_id = payload.get("turn_id", "")
                    thread_id = job.thread_id
                    user_item_id = f"{turn_id}:user"
                    client_message_id = uuid.uuid4().hex

                    async def _emit_arrange_turn_events(db):
                        envelopes = await core_db_handle.persistence.append_batch(
                            db,
                            app_events=[
                                AppEventInput(
                                    thread_id=thread_id,
                                    method="turn/accepted",
                                    turn_id=turn_id,
                                    client_message_id=client_message_id,
                                    payload={
                                        "type": "turn",
                                        "input": [{"type": "text", "text": message}],
                                        "work_root": job.work_root or "",
                                        "status": "running",
                                    },
                                ),
                                AppEventInput(
                                    thread_id=thread_id,
                                    method="item/started",
                                    turn_id=turn_id,
                                    item_id=user_item_id,
                                    client_message_id=client_message_id,
                                    payload={
                                        "type": "userMessage",
                                        "status": "completed",
                                        "content": [{"type": "text", "text": message}],
                                    },
                                ),
                            ],
                        )
                        return envelopes[0], envelopes[1]

                    try:
                        accepted_envelope, user_envelope = await core_db_handle.persistence.write(
                            _emit_arrange_turn_events
                        )
                        await live_hub.publish(accepted_envelope)
                        await live_hub.publish(user_envelope)
                    except Exception:
                        pass  # best-effort; never block arrange execution
            return await agent_operations.execute(
                job.operation,
                payload,
                metadata={
                    "source": "arrange",
                    "arrange_job_id": job.id,
                    "occurrence_id": job.occurrence_id,
                    **({"arrange_signal": job.signal} if job.signal else {}),
                },
            )

        arrange_runner = ArrangeRunner(
            core_db_handle.arrange_store,
            execute_arranged_job,
            new_thread_factory=lambda _job: f"arrange_thread_{uuid.uuid4().hex}",
        )
        observer_supervisor = ObserverSupervisor(
            core_db_handle.arrange_store,
            data_dir=resolved_data_dir,
            wake_runner=arrange_runner.wake,
        )
        register_durable_operations(
            agent_operations,
            goal_manager=goal_manager,
            arrange_manager=arrange_manager,
            wake_runner=arrange_runner.wake,
            cancel_running=arrange_runner.cancel,
            wake_observers=observer_supervisor.wake,
            observer_status=observer_supervisor.status,
        )
        app_state["operations"] = agent_operations
        app_state["arrange_runner"] = arrange_runner
        app_state["observer_supervisor"] = observer_supervisor
        # Reap turns left durably "running"/"waiting"/"interrupting" by an
        # unexpected shutdown, mirroring arrange job recovery. Without this the
        # durable-snapshot guard in turn.start blocks the thread with
        # "active turn already exists" until a manual turn.cancel.
        try:
            await recover_stale_active_turns(context=live_context())
        except BaseException:
            _logger.exception("[startup] stale active turn recovery failed (non-fatal)")
        await arrange_runner.start()
        await observer_supervisor.start()

        # Workflow mode: file-backed definitions + deterministic runner. The
        # runner streams per-node state as core/runItem events (the existing
        # GUI reducer renders them with no new channel) and cooperatively
        # cancels via the same runtime_task_registry the kernel uses. The
        # toolbox (built per-turn) reads enrolled workflows from the same store
        # via a cached provider so exposing one makes it callable next turn.
        workflow_manager = WorkflowManager(workflow_store)

        async def _emit_workflow_event(event: Any) -> None:
            async def _write(db: Any) -> Any:
                return await core_db_handle.persistence.append(
                    db,
                    AppEventInput(
                        thread_id=event.thread_id,
                        method="core/runItem",
                        turn_id=event.turn_id,
                        item_id=event.item_id,
                        client_message_id=uuid.uuid4().hex,
                        payload=event.to_dict(),
                    ),
                )

            try:
                envelope = await core_db_handle.persistence.write(_write)
                await live_hub.publish(envelope)
            except Exception:  # noqa: BLE001 — streaming must never break a run
                pass

        # Build a sub-agent runner for workflow Agent nodes. Lightweight: the
        # runner spins up a per-call CoreLoopKernel with the same LLM client and
        # work_root; Agent node configs may override model/mode per call.
        from lamtools_core.tool.sub_agent_runner import KernelSubAgentRunner

        workflow_sub_agent_runner = KernelSubAgentRunner(
            work_root=str(resolved_work_root),
            llm_client=llm_client,
            model_id=config.model_id,
            approval_policy="require",
            session_prefix="workflow-sub-agent",
        )

        workflow_runner = WorkflowRunner(
            llm_client=llm_client,
            sub_agent_runner=workflow_sub_agent_runner,
            emit=_emit_workflow_event,
            runtime_task_registry=runtime_task_registry,
            workflow_store=workflow_store,
        )

        def _list_tool_specs() -> list[Any]:
            try:
                from lamtools_core.tool.default_toolbox import default_core_tool_specs

                return default_core_tool_specs()
            except Exception:  # noqa: BLE001
                return []

        register_workflow_operations(
            agent_operations,
            workflow_manager=workflow_manager,
            runner=workflow_runner,
            runtime_task_registry=runtime_task_registry,
            list_tool_specs=_list_tool_specs,
        )
        app_state["workflow_store"] = workflow_store
        app_state["workflow_manager"] = workflow_manager
        app_state["workflow_runner"] = workflow_runner

        # File watcher: poll the workflow store mtime signature and broadcast
        # workflow/changed events so canvases refresh on external edits.
        from lamtools_core.runtime.workflow_watcher import WorkflowFileWatcher

        workflow_watcher = WorkflowFileWatcher(
            workflow_store,
            live_hub,
            poll_interval=2.0,
            work_roots=[str(resolved_work_root)],
        )
        await workflow_watcher.start()
        app_state["workflow_watcher"] = workflow_watcher

    async def shutdown_core_agent() -> None:
        workflow_watcher = app_state.get("workflow_watcher")
        if workflow_watcher is not None:
            await workflow_watcher.stop()
        observer_supervisor = app_state.get("observer_supervisor")
        if observer_supervisor is not None:
            await observer_supervisor.stop()
        arrange_runner = app_state.get("arrange_runner")
        if arrange_runner is not None:
            await arrange_runner.stop()
        await runtime_task_registry.shutdown()
        core_db_handle = app_state.get("core_db")
        if core_db_handle is not None:
            await core_db_handle.close()

    def live_context() -> CoreLiveContext:
        core_db_handle = app_state.get("core_db")
        actual_operations = app_state.get("operations")
        if core_db_handle is None or not isinstance(actual_operations, OperationCatalog):
            raise RuntimeError("Core Agent is not ready")
        return CoreLiveContext(
            operations=actual_operations,
            host=CoreLiveOperationHost(
                session_factory=core_db_handle.session_factory,
                persistence=core_db_handle.persistence,
                hub=live_hub,
                runtime_task_registry=runtime_task_registry,
                runtime_state_store=core_db_handle.runtime_state_store,
                llm_client=llm_client,
                default_model_id=config.model_id,
                session_store=session_store,
                member_hooks=_MemberDefaultsHooks(core_db_handle.member_defaults),
            ),
        )

    app = create_app(
        members=members,
        title=runtime_spec.name,
        enable_core_routes=False,
        frontend_dir=frontend_dir,
        health_payload=lambda: {
            "status": "ok",
            "agent": runtime_spec.member_id,
            "agent_id": runtime_spec.id,
            "agent_name": runtime_spec.name,
            "model": config.display_name or config.model_id,
            # Internal absolute paths (work_root / core_db) were previously
            # exposed to any loopback caller — auxiliary info for targeted
            # attacks (audit 03 S4). Nothing depends on those fields.
        },
        on_startup=[startup_core_agent],
        on_shutdown=[shutdown_core_agent],
    )
    app.include_router(
        create_core_router(
            session_store=session_store,
            operations=operations,
            project_store=lambda: app_state["core_db"].project_store,
            publish_event=live_hub.publish,
        ),
        prefix="/api/core",
    )
    app.include_router(create_core_live_router(live_context), prefix="/api/core")

    @app.get("/api/core/config/models")
    async def list_config_models() -> dict[str, Any]:
        return {"models": list_llm_model_configs()}

    @app.get("/api/core/config/providers")
    async def list_config_providers() -> dict[str, Any]:
        return {"providers": _list_llm_provider_configs()}

    def attachment_store() -> CoreAttachmentStore:
        store = app_state.get("attachment_store")
        if not isinstance(store, CoreAttachmentStore):
            raise HTTPException(status_code=503, detail="Core Agent is not ready")
        return store

    @app.post("/api/core/sessions/{session_id}/attachments")
    async def upload_attachment(
        session_id: str,
        file: UploadFile = File(...),
        project_id: str | None = Query(default=None),
    ) -> dict[str, Any]:
        # Reject oversized uploads before reading them into memory (the
        # service layer re-checks the actual byte count).
        if file.size is not None and file.size > MAX_ATTACHMENT_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Attachment exceeds the {MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB size limit",
            )
        record = await attachment_store().create(session_id, file.filename or "attachment", await file.read(), file.content_type)
        await register_uploaded_artifact(record, project_id)
        return record

    @app.get("/api/core/attachments/{attachment_id}/download")
    async def download_attachment(attachment_id: str) -> FileResponse:
        record = await attachment_store().get(attachment_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Attachment not found")
        path = Path(record.storage_path)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Attachment file missing")
        return FileResponse(path, media_type=record.mime_type, filename=record.filename)

    @app.get("/api/core/projects/{project_id}/artifacts/{artifact_id}/file")
    async def artifact_file(
        project_id: str,
        artifact_id: str,
        path: str | None = Query(default=None),
    ) -> FileResponse:
        """按 artifact id 读取产物文件（manifest 为权威路径，支持 workspace:// 与 attachment://）。

        ``path`` 为兜底：旧会话事件里的 artifact_id 是投影派生 id（artifact-{sha1}），
        无法直接命中 manifest，此时按 path 反查注册表。
        """
        project = await app_state["core_db"].project_store.get(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        registry = ArtifactRegistry(project.work_root)
        record = registry.get(artifact_id)
        if record is None and path:
            resolved_id = registry.resolve_artifact_id(path, work_root=project.work_root)
            if resolved_id:
                record = registry.get(resolved_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Artifact not found")
        if record.path.startswith("attachment://"):
            attachment = await attachment_store().get(record.path[len("attachment://"):])
            if attachment is None:
                raise HTTPException(status_code=404, detail="Attachment not found")
            path = Path(attachment.storage_path)
            filename = attachment.filename
            mime = attachment.mime_type
        elif record.path.startswith("workspace://"):
            rel = record.path[len("workspace://"):]
            path = Path(project.work_root) / rel
            filename = record.name
            mime = record.mime_type
        else:
            raise HTTPException(status_code=404, detail="Unsupported artifact path")
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Artifact file missing")
        return FileResponse(path, media_type=mime or None, filename=filename)

    async def register_uploaded_artifact(record: dict[str, Any], project_id: str | None) -> None:
        """上传即注册：把用户上传的附件登记到项目 artifact 注册表（best-effort，失败不影响上传）。"""
        if not project_id:
            return
        artifact_id = str(record.get("id") or "")
        if not artifact_id:
            return
        try:
            project = await app_state["core_db"].project_store.get(project_id)
            if project is None:
                return
            registry = ArtifactRegistry(project.work_root)
            registry.register(
                kind=kind_from_mime(str(record.get("mime_type") or "")),
                mime_type=str(record.get("mime_type") or ""),
                name=str(record.get("filename") or artifact_id),
                path=f"attachment://{artifact_id}",
                source="user_upload",
            )
        except Exception:  # noqa: BLE001 — registration must never break uploads
            pass

    @app.get("/api/core/sessions/{session_id}/attachments")
    async def list_attachments(session_id: str) -> dict[str, Any]:
        return {"attachments": await attachment_store().list(session_id)}

    @app.get("/api/core/attachments/{attachment_id}/preview")
    async def preview_attachment(attachment_id: str) -> dict[str, Any]:
        try:
            return await attachment_store().preview(attachment_id)
        except (LookupError, FileNotFoundError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/core/attachments/{attachment_id}/open")
    async def open_attachment(attachment_id: str) -> dict[str, str]:
        try:
            return await attachment_store().open(attachment_id)
        except (LookupError, FileNotFoundError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    app.state.core_agent_app_state = app_state
    app.state.core_agent_runtime_task_registry = runtime_task_registry
    app.state.core_agent_work_root = resolved_work_root
    app.state.core_agent_data_dir = resolved_data_dir

    # Register SPA fallback LAST so API routes take precedence.
    if frontend_dir is not None:
        add_spa_fallback(app, Path(frontend_dir))

    return app


def _register_core_project_operations(catalog: OperationCatalog, *, project_store: CoreProjectStore) -> None:
    async def project_list(request: OperationRequest) -> OperationResult:
        del request
        return OperationResult(
            name="project.list",
            payload={"projects": [project.to_dict() for project in await project_store.list()]},
        )

    async def project_create(request: OperationRequest) -> OperationResult:
        payload = request.payload
        work_root = str(payload.get("work_root") or payload.get("workRoot") or "").strip()
        if not work_root:
            return OperationResult(name=request.name, status="error", payload={"error": "work_root is required"})
        try:
            project, session, _ = await project_store.create_with_initial_session(
                work_root,
                name=payload.get("name") if "name" in payload else None,
            )
        except (OSError, ValueError) as exc:
            return OperationResult(name=request.name, status="error", payload={"error": str(exc)})
        return OperationResult(
            name=request.name,
            payload={"project": project.to_dict(), "session": session.to_dict()},
        )

    async def project_get(request: OperationRequest) -> OperationResult:
        project = await project_store.get(_project_id(request))
        if project is None:
            return OperationResult(name=request.name, status="error", payload={"error": "Project not found"})
        return OperationResult(name=request.name, payload={"project": project.to_dict()})

    async def project_update(request: OperationRequest) -> OperationResult:
        try:
            project = await project_store.rename(_project_id(request), str(request.payload.get("name") or ""))
        except (OSError, ValueError) as exc:
            return OperationResult(name=request.name, status="error", payload={"error": str(exc)})
        if project is None:
            return OperationResult(name=request.name, status="error", payload={"error": "Project not found"})
        return OperationResult(name=request.name, payload={"project": project.to_dict()})

    async def project_delete(request: OperationRequest) -> OperationResult:
        try:
            deleted = await project_store.delete_with_sessions(_project_id(request))
        except ActiveProjectSessionsError as exc:
            return OperationResult(name=request.name, status="error", payload={"error": str(exc), "code": 409})
        if not deleted:
            return OperationResult(name=request.name, status="error", payload={"error": "Project not found"})
        return OperationResult(name=request.name, payload={"deleted": True})

    async def project_sessions_list(request: OperationRequest) -> OperationResult:
        project_id = _project_id(request)
        if await project_store.get(project_id) is None:
            return OperationResult(name=request.name, status="error", payload={"error": "Project not found"})
        return OperationResult(
            name=request.name,
            payload={"sessions": [session.to_dict() for session in await project_store.list_sessions(project_id)]},
        )

    async def project_sessions_create(request: OperationRequest) -> OperationResult:
        try:
            session = await project_store.create_session(
                _project_id(request),
                title=str(request.payload.get("title") or "New Session"),
            )
        except LookupError as exc:
            return OperationResult(name=request.name, status="error", payload={"error": str(exc)})
        return OperationResult(name=request.name, payload={"session": session.to_dict()})

    async def project_agents_md_get(request: OperationRequest) -> OperationResult:
        try:
            agents_md = await project_store.read_agents_md(_project_id(request))
        except (OSError, ValueError) as exc:
            return OperationResult(name=request.name, status="error", payload={"error": str(exc)})
        if agents_md is None:
            return OperationResult(name=request.name, status="error", payload={"error": "Project not found"})
        return OperationResult(name=request.name, payload={"agents_md": agents_md})

    async def project_agents_md_update(request: OperationRequest) -> OperationResult:
        try:
            agents_md = await project_store.write_agents_md(
                _project_id(request),
                str(request.payload.get("content") or ""),
            )
        except (OSError, ValueError) as exc:
            return OperationResult(name=request.name, status="error", payload={"error": str(exc)})
        if agents_md is None:
            return OperationResult(name=request.name, status="error", payload={"error": "Project not found"})
        return OperationResult(name=request.name, payload={"agents_md": agents_md})

    handlers = {
        "project.list": project_list,
        "project.create": project_create,
        "project.get": project_get,
        "project.update": project_update,
        "project.delete": project_delete,
        "project.sessions.create": project_sessions_create,
        "project.sessions.list": project_sessions_list,
        "project.agents_md.get": project_agents_md_get,
        "project.agents_md.update": project_agents_md_update,
    }
    for name, handler in handlers.items():
        if not catalog.has(name):
            catalog.register(name, handler)


def _register_core_session_operations(catalog: OperationCatalog, *, session_store: Any) -> None:
    async def session_list(request: OperationRequest) -> OperationResult:
        sessions = await session_store.list()
        return OperationResult(name="session.list", payload={
            "sessions": [{"id": s.id, "title": s.title, "status": s.status} for s in sessions]
        })

    async def session_get(request: OperationRequest) -> OperationResult:
        sid = str(request.payload.get("session_id") or request.payload.get("sessionId") or request.payload.get("id") or "")
        s = await session_store.get(sid)
        if s is None:
            return OperationResult(name="session.get", status="error", payload={"error": "Not found"})
        return OperationResult(name="session.get", payload={"session": {"id": s.id, "title": s.title, "status": s.status}})

    async def session_delete(request: OperationRequest) -> OperationResult:
        sid = str(request.payload.get("session_id") or request.payload.get("sessionId") or request.payload.get("id") or "")
        await session_store.delete(sid)
        return OperationResult(name="session.delete", payload={"deleted": sid})

    for name, handler in [("session.list", session_list), ("session.get", session_get), ("session.delete", session_delete)]:
        if not catalog.has(name):
            catalog.register(name, handler)


def _project_id(request: OperationRequest) -> str:
    return str(request.payload.get("project_id") or request.payload.get("projectId") or request.payload.get("id") or "")


def _register_core_artifact_operations(catalog: OperationCatalog, *, project_store: CoreProjectStore) -> None:
    """artifact.* operations — per-project registry under ``{work_root}/.lam/artifact``."""

    async def _registry_for(request: OperationRequest) -> ArtifactRegistry | None:
        project = await project_store.get(_project_id(request))
        if project is None:
            return None
        return ArtifactRegistry(project.work_root)

    async def artifact_list(request: OperationRequest) -> OperationResult:
        registry = await _registry_for(request)
        if registry is None:
            return OperationResult(name=request.name, status="error", payload={"error": "Project not found"})
        include_deleted = bool(request.payload.get("include_deleted"))
        return OperationResult(
            name=request.name,
            payload={
                "artifacts": [record.to_dict() for record in registry.list(include_deleted=include_deleted)],
            },
        )

    async def artifact_read(request: OperationRequest) -> OperationResult:
        registry = await _registry_for(request)
        if registry is None:
            return OperationResult(name=request.name, status="error", payload={"error": "Project not found"})
        artifact_id = str(request.payload.get("artifact_id") or request.payload.get("artifactId") or "")
        record = registry.get(artifact_id)
        if record is None:
            return OperationResult(name=request.name, status="error", payload={"error": "Artifact not found"})
        return OperationResult(name=request.name, payload={"artifact": record.to_dict()})

    async def artifact_delete(request: OperationRequest) -> OperationResult:
        registry = await _registry_for(request)
        if registry is None:
            return OperationResult(name=request.name, status="error", payload={"error": "Project not found"})
        raw = request.payload.get("artifact_ids") or request.payload.get("artifactIds")
        artifact_ids = [str(item) for item in raw if str(item).strip()] if isinstance(raw, list) else []
        if not artifact_ids:
            return OperationResult(name=request.name, status="error", payload={"error": "artifact_ids is required"})
        deleted = registry.soft_delete(artifact_ids)
        return OperationResult(name=request.name, payload={"deleted": deleted})

    async def artifact_open(request: OperationRequest) -> OperationResult:
        registry = await _registry_for(request)
        if registry is None:
            return OperationResult(name=request.name, status="error", payload={"error": "Project not found"})
        artifact_id = str(request.payload.get("artifact_id") or request.payload.get("artifactId") or "")
        record = registry.get(artifact_id)
        if record is None:
            return OperationResult(name=request.name, status="error", payload={"error": "Artifact not found"})
        return OperationResult(name=request.name, payload={"path": record.path})

    handlers = {
        "artifact.list": artifact_list,
        "artifact.read": artifact_read,
        "artifact.delete": artifact_delete,
        "artifact.open": artifact_open,
    }
    for name, handler in handlers.items():
        if not catalog.has(name):
            catalog.register(name, handler)


def _register_core_config_operations(
    catalog: OperationCatalog,
    *,
    default_model_id: str,
    work_root: Path | str | None = None,
) -> None:
    async def config_models_list(request: OperationRequest) -> OperationResult:
        del request
        return OperationResult(
            name="config.models.list",
            payload={
                "models": list_llm_model_configs(),
                "default_model_id": default_model_id,
            },
        )

    async def config_providers_list(request: OperationRequest) -> OperationResult:
        del request
        return OperationResult(name="config.providers.list", payload={"providers": _list_llm_provider_configs()})

    async def config_resolved_get(request: OperationRequest) -> OperationResult:
        task_type = str(request.payload.get("task_type") or request.payload.get("taskType") or "core")
        model_ref = str(request.payload.get("model_id") or request.payload.get("modelId") or "")
        config = load_llm_config(model_ref=model_ref)
        return OperationResult(
            name="config.resolved.get",
            payload={
                "resolved": {
                    "task_type": task_type,
                    "model": {
                        "id": config.model_record_id,
                        "model_id": config.model_id,
                        "display_name": config.display_name,
                        "provider_id": "",
                        "context_window": config.context_window,
                        "max_output_tokens": config.max_output_tokens,
                        "thinking_supported": config.thinking_supported,
                        "thinking_budget": config.thinking_budget,
                        "temperature": config.temperature,
                    },
                    "provider": {
                        "name": config.provider_name,
                        "api_type": config.provider_api_type,
                        "base_url": config.base_url,
                    },
                },
            },
        )

    for name, handler in {
        "config.models.list": config_models_list,
        "config.providers.list": config_providers_list,
        "config.resolved.get": config_resolved_get,
    }.items():
        if not catalog.has(name):
            catalog.register(name, handler)

    _register_subagent_guide_operations(catalog, work_root=work_root)
    _register_model_operations(catalog, work_root=work_root)
    _register_loadtools_operations(catalog)


def _register_loadtools_operations(catalog: OperationCatalog) -> None:
    """config.loadtools.get/set — read & manage the mode tool-set config.

    ``loadtools.jsonc`` lives in the unified config directory; when it does
    not exist yet the built-in modes are served (and the UI saves a file on
    first edit). The catalog lists every known tool with its category so the
    UI can render a grouped checklist instead of a raw text editor.
    """
    from lamtools_core.config.root import core_config_file
    from lamtools_core.tool.default_toolbox import (
        DEFAULT_TOOL_CATEGORIES,
        default_core_tool_specs,
    )
    from lamtools_core.tool.durable_tools import durable_tool_specs
    from lamtools_core.tool.loadtools import (
        LoadToolMode,
        LoadTools,
        default_load_tools,
        load_loadtools,
        serialize_loadtools,
    )
    from lamtools_core.tool.workflow_build_tools import workflow_build_tool_specs

    def _config_path() -> Path:
        return core_config_file("loadtools.jsonc")

    def _current_modes() -> tuple[LoadTools, str]:
        path = _config_path()
        if path.is_file():
            loaded = load_loadtools(path)
            if loaded:
                return loaded, "config"
        return default_load_tools(), "builtin"

    def _catalog() -> list[dict[str, str]]:
        specs = [
            *default_core_tool_specs(),
            *durable_tool_specs(goal=True, arrange=True),
            *workflow_build_tool_specs(),
        ]
        seen: set[str] = set()
        result: list[dict[str, str]] = []
        for spec in specs:
            if spec.name in seen:
                continue
            seen.add(spec.name)
            result.append({
                "name": spec.name,
                "category": str(spec.metadata.get("category") or DEFAULT_TOOL_CATEGORIES.get(spec.name, "other")),
            })
        return result

    def _modes_payload(modes: LoadTools) -> dict[str, dict[str, object]]:
        return {
            name: {"description": mode.description, "tools": list(mode.tools)}
            for name, mode in modes.items()
        }

    async def loadtools_get(request: OperationRequest) -> OperationResult:
        del request
        modes, source = _current_modes()
        return OperationResult(name="config.loadtools.get", payload={
            "modes": _modes_payload(modes),
            "source": source,
            "catalog": _catalog(),
        })

    async def loadtools_set(request: OperationRequest) -> OperationResult:
        raw_modes = (request.payload or {}).get("modes")
        if not isinstance(raw_modes, dict):
            return OperationResult(name=request.name, status="error", payload={"error": "modes is required"})
        modes: LoadTools = {}
        for name, raw in raw_modes.items():
            name = str(name).strip()
            if not name:
                continue
            if not isinstance(raw, dict):
                return OperationResult(name=request.name, status="error", payload={"error": f"mode {name} must be an object"})
            description = str(raw.get("description") or "").strip()
            tools_raw = raw.get("tools")
            if not isinstance(tools_raw, list):
                return OperationResult(name=request.name, status="error", payload={"error": f"mode {name} tools must be a list"})
            tools = [str(t) for t in tools_raw if isinstance(t, str) and str(t).strip()]
            modes[name] = LoadToolMode(description=description, tools=tools)
        if not modes:
            return OperationResult(name=request.name, status="error", payload={"error": "at least one mode is required"})
        path = _config_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(serialize_loadtools(modes), encoding="utf-8")
        except OSError as exc:
            return OperationResult(name=request.name, status="error", payload={"error": str(exc)})
        return OperationResult(name="config.loadtools.set", payload={
            "modes": _modes_payload(modes),
            "source": "config",
        })

    for name, handler in {
        "config.loadtools.get": loadtools_get,
        "config.loadtools.set": loadtools_set,
    }.items():
        if not catalog.has(name):
            catalog.register(name, handler)


def _register_model_operations(
    catalog: OperationCatalog,
    *,
    work_root: Path | str | None = None,
) -> None:
    from lamtools_core.config.model_store import ModelConfig, ModelStore
    from lamtools_core.config.provider_store import ProviderStore
    from dataclasses import replace

    def _store() -> ModelStore:
        from lamtools_core.cli import _get_model_store

        return _get_model_store()

    def _resolve_provider_name(provider_id: str, fallback: str) -> str:
        """Resolve a provider display name from the jsonc provider store."""
        if fallback or not provider_id:
            return fallback
        provider = ProviderStore().get_sync(provider_id)
        return provider.name if provider is not None else fallback

    def _payload_model_config(model_id: str, payload: dict[str, Any]) -> ModelConfig:
        thinking = payload.get("thinking") if isinstance(payload.get("thinking"), dict) else {}
        request_body = payload.get("request_body") if isinstance(payload.get("request_body"), dict) else {}
        provider_id = str(payload.get("provider_id") or "")
        # Prefer resolving the provider name from the provider store by
        # provider_id so the jsonc file always carries the correct name even
        # if the UI's cached provider_name was stale. Fall back to the
        # payload-provided name.
        if provider_id:
            provider_name = _resolve_provider_name(provider_id, str(payload.get("provider") or payload.get("provider_name") or ""))
        else:
            provider_name = str(payload.get("provider") or payload.get("provider_name") or "")
        return ModelConfig(
            model_id=str(payload.get("model_id") or model_id),
            display_name=str(payload.get("display_name") or ""),
            provider=provider_name,
            provider_id=provider_id,
            context_window=int(payload.get("context_window") or 0),
            max_output_tokens=int(payload.get("max_output_tokens") or 4096),
            temperature=float(payload.get("temperature") or 0.2),
            thinking_supported=bool(thinking.get("supported", payload.get("thinking_supported") or False)),
            thinking_budget=int(thinking.get("budget", payload.get("thinking_budget") or 10000)),
            reasoning_effort=str(payload.get("reasoning_effort") or ""),
            adapter_profile_id=str(payload.get("adapter_profile_id") or ""),
            request_body=request_body,
            capability=str(payload.get("capability") or "").strip().lower(),
            notes=str(payload.get("notes") or "").strip(),
            is_default=bool(payload.get("is_default") or False),
        )

    async def models_upsert(request: OperationRequest) -> OperationResult:
        payload = request.payload if isinstance(request.payload, dict) else {}
        model_id = str(payload.get("model_id") or "").strip()
        if not model_id:
            return OperationResult(name=request.name, status="error", payload={"error": "model_id is required"})
        scope = str(payload.get("scope") or "global").strip()
        if scope not in ("project", "global"):
            return OperationResult(name=request.name, status="error", payload={"error": "scope must be 'project' or 'global'"})
        root = str(payload.get("work_root") or payload.get("workRoot") or "").strip() or work_root
        if scope == "project" and not root:
            return OperationResult(name=request.name, status="error", payload={"error": "work_root is required for project scope"})
        # Clear is_default on all other models when setting a new default.
        store = _store()
        model = _payload_model_config(model_id, payload)
        if model.is_default:
            for existing in store.list_sync(work_root=str(root) if root else None):
                if existing.model_id != model.model_id and existing.is_default:
                    existing.is_default = False
                    store.write(existing, scope=scope, work_root=root)
        path = store.write(model, scope=scope, work_root=root)
        return OperationResult(name=request.name, payload={"path": str(path), "model_id": model.model_id, "scope": scope})

    async def models_delete(request: OperationRequest) -> OperationResult:
        from pathlib import Path as _Path

        payload = request.payload if isinstance(request.payload, dict) else {}
        model_id = str(payload.get("model_id") or "").strip()
        scope = str(payload.get("scope") or "global").strip()
        if not model_id:
            return OperationResult(name=request.name, status="error", payload={"error": "model_id is required"})
        root = str(payload.get("work_root") or payload.get("workRoot") or "").strip() or work_root
        path = ModelStore.write_path(model_id, scope=scope, work_root=root)
        if not path.is_file():
            return OperationResult(name=request.name, status="error", payload={"error": f"no model file at {path}"})
        path.unlink()
        _store()._cached_signature = None  # invalidate cache
        _store()._cached_models = None
        return OperationResult(name=request.name, payload={"deleted": str(path)})

    async def models_set_default(request: OperationRequest) -> OperationResult:
        payload = request.payload if isinstance(request.payload, dict) else {}
        model_id = str(payload.get("model_id") or payload.get("model_record_id") or "").strip()
        if not model_id:
            return OperationResult(name=request.name, status="error", payload={"error": "model_id is required"})
        scope = str(payload.get("scope") or "global").strip()
        if scope not in ("project", "global"):
            return OperationResult(name=request.name, status="error", payload={"error": "scope must be 'project' or 'global'"})
        root = str(payload.get("work_root") or payload.get("workRoot") or "").strip() or work_root
        if scope == "project" and not root:
            return OperationResult(name=request.name, status="error", payload={"error": "work_root is required for project scope"})
        store = _store()
        model = store.get_sync(model_id, work_root=root)
        if model is None:
            return OperationResult(name=request.name, status="error", payload={"error": f"model not found: {model_id}"})
        # Clear other defaults, then mark this one.
        for existing in store.list_sync(work_root=root):
            if existing.model_id != model.model_id and existing.is_default:
                store.write(replace(existing, is_default=False), scope=scope, work_root=root)
        path = store.write(replace(model, is_default=True), scope=scope, work_root=root)
        return OperationResult(name=request.name, payload={"path": str(path), "model_id": model.model_id, "scope": scope})

    for name, handler in {
        "config.models.upsert": models_upsert,
        "config.models.delete": models_delete,
        "config.models.set_default": models_set_default,
    }.items():
        if not catalog.has(name):
            catalog.register(name, handler)


def _register_subagent_guide_operations(
    catalog: OperationCatalog,
    *,
    work_root: Path | str | None = None,
) -> None:
    from lamtools_core.config.subagent_prompt import (
        DEFAULT_SUBAGENT_GUIDE,
        guide_path_for_scope,
        load_subagent_guide,
        resolve_subagent_guide_path,
        write_subagent_guide,
    )

    async def subagent_guide_get(request: OperationRequest) -> OperationResult:
        # Payload may override the work root the server was started with.
        root = str(request.payload.get("work_root") or request.payload.get("workRoot") or "").strip()
        effective_root = root or work_root
        requested_scope = str(request.payload.get("scope") or "").strip().lower()

        # When a specific scope is requested, read only that level's file
        # (used by the global Settings UI which must not touch project scope).
        if requested_scope in ("project", "global"):
            path = guide_path_for_scope(requested_scope, effective_root)
            if path.is_file():
                try:
                    content = path.read_text(encoding="utf-8")
                except OSError:
                    content = ""
                return OperationResult(
                    name=request.name,
                    payload={
                        "content": content,
                        "scope": requested_scope,
                        "resolved_path": str(path),
                        "is_builtin": False,
                    },
                )
            return OperationResult(
                name=request.name,
                payload={
                    "content": DEFAULT_SUBAGENT_GUIDE,
                    "scope": "builtin",
                    "resolved_path": "",
                    "is_builtin": True,
                },
            )

        # Default: merged read (project > global > builtin) for CLI / project settings.
        from lamtools_core.config.subagent_prompt import subagent_guide_dirs

        dirs = subagent_guide_dirs(effective_root)
        resolved = resolve_subagent_guide_path(effective_root)
        if resolved is None:
            scope = "builtin"
        elif dirs and resolved == (dirs[0] / "guide.md"):
            scope = "project"
        else:
            scope = "global"
        content = load_subagent_guide(effective_root)
        return OperationResult(
            name=request.name,
            payload={
                "content": content,
                "scope": scope,
                "resolved_path": str(resolved) if resolved is not None else "",
                "is_builtin": resolved is None,
            },
        )

    async def subagent_guide_set(request: OperationRequest) -> OperationResult:
        content = str(request.payload.get("content") or "")
        scope = str(request.payload.get("scope") or "global").strip()
        if scope not in ("project", "global"):
            return OperationResult(
                name=request.name, status="error",
                payload={"error": "scope must be 'project' or 'global'"},
            )
        root = str(request.payload.get("work_root") or request.payload.get("workRoot") or "").strip()
        effective_root = root or work_root
        if scope == "project" and not effective_root:
            return OperationResult(
                name=request.name, status="error",
                payload={"error": "work_root is required to save a project-scoped guide"},
            )
        try:
            path = write_subagent_guide(content, scope=scope, work_root=effective_root)
        except OSError as exc:
            return OperationResult(
                name=request.name, status="error",
                payload={"error": f"failed to write guide: {exc}"},
            )
        return OperationResult(
            name=request.name,
            payload={"path": str(path), "scope": scope},
        )

    async def subagent_settings_get(request: OperationRequest) -> OperationResult:
        from lamtools_core.config.subagent_prompt import (
            DEFAULT_SUBAGENT_SETTINGS,
            load_subagent_settings,
            resolve_subagent_settings_path,
            settings_path_for_scope,
        )

        root = str(request.payload.get("work_root") or request.payload.get("workRoot") or "").strip()
        effective_root = root or work_root
        requested_scope = str(request.payload.get("scope") or "").strip().lower()

        # When a specific scope is requested, read only that level's file
        if requested_scope in ("project", "global"):
            path = settings_path_for_scope(requested_scope, effective_root)
            if path.is_file():
                try:
                    import json as _json
                    data = _json.loads(path.read_text(encoding="utf-8"))
                    settings = dict(DEFAULT_SUBAGENT_SETTINGS)
                    if isinstance(data, dict):
                        settings.update(data)
                except (OSError, ValueError):
                    settings = dict(DEFAULT_SUBAGENT_SETTINGS)
                return OperationResult(
                    name=request.name,
                    payload={
                        "settings": settings,
                        "scope": requested_scope,
                        "resolved_path": str(path),
                        "is_builtin": False,
                    },
                )
            return OperationResult(
                name=request.name,
                payload={
                    "settings": dict(DEFAULT_SUBAGENT_SETTINGS),
                    "scope": "builtin",
                    "resolved_path": "",
                    "is_builtin": True,
                },
            )

        # Default: merged read (project > global > builtin)
        resolved = resolve_subagent_settings_path(effective_root)
        settings = load_subagent_settings(effective_root)
        from lamtools_core.config.subagent_prompt import subagent_guide_dirs

        dirs = subagent_guide_dirs(effective_root)
        if resolved is None:
            scope = "builtin"
        elif dirs and resolved == (dirs[0] / "settings.json"):
            scope = "project"
        else:
            scope = "global"
        return OperationResult(
            name=request.name,
            payload={
                "settings": settings,
                "scope": scope,
                "resolved_path": str(resolved) if resolved is not None else "",
                "is_builtin": resolved is None,
            },
        )

    async def subagent_settings_set(request: OperationRequest) -> OperationResult:
        from lamtools_core.config.subagent_prompt import write_subagent_settings

        updates = request.payload.get("settings") if isinstance(request.payload.get("settings"), dict) else {}
        # Also accept top-level keys for convenience (e.g. {default_multimodal_model: "..."})
        for key in ("default_multimodal_model",):
            val = request.payload.get(key)
            if val is not None:
                updates[key] = str(val).strip()
        scope = str(request.payload.get("scope") or "global").strip()
        if scope not in ("project", "global"):
            return OperationResult(
                name=request.name, status="error",
                payload={"error": "scope must be 'project' or 'global'"},
            )
        root = str(request.payload.get("work_root") or request.payload.get("workRoot") or "").strip()
        effective_root = root or work_root
        if scope == "project" and not effective_root:
            return OperationResult(
                name=request.name, status="error",
                payload={"error": "work_root is required to save a project-scoped setting"},
            )
        try:
            path = write_subagent_settings(updates, scope=scope, work_root=effective_root)
        except OSError as exc:
            return OperationResult(
                name=request.name, status="error",
                payload={"error": f"failed to write settings: {exc}"},
            )
        return OperationResult(
            name=request.name,
            payload={"path": str(path), "scope": scope},
        )

    for name, handler in {
        "config.subagent.guide.get": subagent_guide_get,
        "config.subagent.guide.set": subagent_guide_set,
        "config.subagent.settings.get": subagent_settings_get,
        "config.subagent.settings.set": subagent_settings_set,
    }.items():
        if not catalog.has(name):
            catalog.register(name, handler)

    # ── Global AGENTS.md (additive instruction file, applies to all projects) ──
    async def agents_md_get(request: OperationRequest) -> OperationResult:
        del request
        from lamtools_core.config.agents_md import read_global_agents_md
        agents_md = read_global_agents_md()
        return OperationResult(name="config.agents_md.get", payload={"agents_md": agents_md})

    async def agents_md_set(request: OperationRequest) -> OperationResult:
        content = str(request.payload.get("content") or "")
        from lamtools_core.config.agents_md import write_global_agents_md
        agents_md = write_global_agents_md(content)
        return OperationResult(name="config.agents_md.set", payload={"agents_md": agents_md})

    for name, handler in {
        "config.agents_md.get": agents_md_get,
        "config.agents_md.set": agents_md_set,
    }.items():
        if not catalog.has(name):
            catalog.register(name, handler)

    _register_memory_operations(catalog)
    _register_load_context_operations(catalog)


def _register_memory_operations(catalog: OperationCatalog) -> None:
    """config.memory.get/set — read & write the global memory.md file.

    The file lives in the unified config directory and is injected into every
    workspace's prompt as the global memory tier (before the project
    MEMORY.md).
    """
    from lamtools_core.config.root import core_config_file

    async def memory_get(request: OperationRequest) -> OperationResult:
        del request
        path = core_config_file("memory.md")
        if not path.is_file():
            return OperationResult(name="config.memory.get", payload={"content": "", "exists": False})
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            content = path.read_text(encoding="utf-8", errors="replace")
        return OperationResult(name="config.memory.get", payload={"content": content, "exists": True})

    async def memory_set(request: OperationRequest) -> OperationResult:
        content = str(request.payload.get("content") or "")
        path = core_config_file("memory.md")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        except OSError as exc:
            return OperationResult(name=request.name, status="error", payload={"error": str(exc)})
        return OperationResult(name="config.memory.set", payload={"content": content, "exists": True})

    for name, handler in {
        "config.memory.get": memory_get,
        "config.memory.set": memory_set,
    }.items():
        if not catalog.has(name):
            catalog.register(name, handler)


def _register_load_context_operations(catalog: OperationCatalog) -> None:
    """config.load_context.get/set — read & write the global load_context.jsonc.

    The file lives in the unified config directory and stacks on top of each
    workspace's own load_context.jsonc (global additions + workspace additions;
    exceptions from either tier apply).
    """
    from lamtools_core.app.project_context import ContextConfig
    from lamtools_core.config.root import core_config_file

    def _payload(config: ContextConfig | None) -> dict[str, object]:
        return {
            "addition": [dict(item) for item in config.addition] if config is not None else [],
            "except": list(config.except_files) if config is not None else [],
        }

    async def load_context_get(request: OperationRequest) -> OperationResult:
        del request
        path = core_config_file("load_context.jsonc")
        config = ContextConfig.from_file(path) if path.is_file() else None
        return OperationResult(name="config.load_context.get", payload={
            **_payload(config),
            "exists": config is not None,
        })

    async def load_context_set(request: OperationRequest) -> OperationResult:
        raw = request.payload if isinstance(request.payload, dict) else {}
        addition_raw = raw.get("addition")
        except_raw = raw.get("except")
        if not isinstance(addition_raw, list) or not isinstance(except_raw, list):
            return OperationResult(
                name=request.name,
                status="error",
                payload={"error": "addition (list) and except (list) are required"},
            )
        additions: list[dict[str, object]] = []
        for item in addition_raw:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                return OperationResult(name=request.name, status="error", payload={"error": "addition items must be objects with a string name"})
            additions.append({
                "name": str(item["name"]).strip(),
                "priority": int(item.get("priority") or 50),
                "kind": str(item.get("kind") or "system"),
            })
        exceptions = [str(item).strip() for item in except_raw if isinstance(item, str) and str(item).strip()]
        path = core_config_file("load_context.jsonc")
        body = {
            "addition": additions,
            "except": exceptions,
        }
        from lamtools_core.config.defaults import DEFAULT_LOAD_CONTEXT_JSONC

        header = DEFAULT_LOAD_CONTEXT_JSONC.split("{", 1)[0] if "{" in DEFAULT_LOAD_CONTEXT_JSONC else ""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            import json as _json
            path.write_text(header + _json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except OSError as exc:
            return OperationResult(name=request.name, status="error", payload={"error": str(exc)})
        return OperationResult(name="config.load_context.set", payload={**_payload(ContextConfig(addition=additions, except_files=exceptions)), "exists": True})

    for name, handler in {
        "config.load_context.get": load_context_get,
        "config.load_context.set": load_context_set,
    }.items():
        if not catalog.has(name):
            catalog.register(name, handler)


def _register_missing_operations(target: OperationCatalog, source: OperationCatalog) -> None:
    for operation_name in source.list():
        if target.has(operation_name):
            continue

        async def execute(
            request: OperationRequest,
            name: str = operation_name,
        ) -> OperationResult:
            return await source.execute(name, request.payload, metadata=request.metadata)

        target.register(operation_name, execute)


def _list_llm_provider_configs() -> list[dict[str, Any]]:
    """List providers from the jsonc provider store (api keys masked)."""
    providers = ProviderStore().list_sync()
    return [
        {
            "id": provider.id,
            "name": provider.name,
            "api_type": provider.api_type,
            "base_url": provider.base_url,
            "api_key": mask_api_key(provider.api_key),
            "has_api_key": bool(provider.api_key),
            "is_default": provider.is_default,
            "extra": dict(provider.extra),
        }
        for provider in providers
    ]


def create_default_core_agent_http_app() -> FastAPI:
    # No built-in "default-model" anymore: empty model_id means "unconfigured",
    # and the app boots with a placeholder until the user sets up a model.
    model_id = os.environ.get("LAMTOOLS_CORE_MODEL_ID") or ""
    core_db = os.environ.get("LAMTOOLS_CORE_DB") or None
    data_dir = os.environ.get("LAMTOOLS_CORE_DATA_DIR") or None
    work_root = os.environ.get("LAMTOOLS_CORE_WORK_ROOT") or None
    return create_core_agent_http_app(
        model_id=model_id,
        core_db=core_db,
        data_dir=data_dir,
        work_root=work_root,
        thinking_enabled=_env_bool("LAMTOOLS_CORE_THINKING_ENABLED", default=True),
        thinking_budget=_env_int("LAMTOOLS_CORE_THINKING_BUDGET", default=10000),
        max_tokens=_env_int("LAMTOOLS_CORE_MAX_TOKENS", default=0) or None,
        temperature=_env_float("LAMTOOLS_CORE_TEMPERATURE", default=0.2),
    )


def _env_bool(name: str, *, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _env_int(name: str, *, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_float(name: str, *, default: float) -> float:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


__all__ = [
    "CoreConfigRoutingLLMClient",
    "create_core_agent_http_app",
    "create_default_core_agent_http_app",
]
