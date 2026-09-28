"""FastAPI assembly for the standalone Core Agent HTTP app."""

from __future__ import annotations

import asyncio
import os
import uuid
from dataclasses import replace
from pathlib import Path
from time import perf_counter
from typing import Any
import logging
from urllib.parse import quote

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
from lamtools_core.llm.profiles import reasoning_off_supported
from lamtools_core.config import build_config_operation_catalog
from lamtools_core.config.provider_store import ProviderConfig, ProviderStore, mask_api_key
from lamtools_core.config.root import fallback_project_root
from lamtools_core.update.operations import build_update_operation_catalog
from lamtools_core.attachment import CoreAttachmentStore
from lamtools_core.export import ConversationExportService, build_handoff_context
from lamtools_core.attachment.service import MAX_ATTACHMENT_BYTES
from lamtools_core.runtime import RuntimeTaskRegistry
from lamtools_core.runtime.arrange import ArrangeManager, ArrangeRunner, arranged_operation_payload
from lamtools_core.runtime.goal import GoalManager
from lamtools_core.runtime.plan_package import PlanManager
from lamtools_core.runtime.observer import ObserverSupervisor
from lamtools_core.member import MemberKit, MemberManifest
from lamtools_core.session import build_session_record
from lamtools_core.plugins.lifecycle import shutdown_plugin_backends
from lamtools_core.plugins.registry import PluginStateStore, bundled_plugins_dir
from lamtools_core.plugins.session_visibility import PluginSessionVisibility
from lamtools_core.config.root import core_plugins_root

from .base_agent import DEFAULT_CORE_INSTRUCTIONS, default_core_agent_plugin_roots
from .core_db import open_core_app_db
from .core_session_store import CoreDbSessionStore
from .desktop_plugin_session_store import DesktopPluginSessionStore
from .default_agent import CoreAgentPaths, CoreAgentSpec, create_core_agent_operations
from .durable_operations import register_durable_operations
from .plan_operations import register_plan_operations
from .event_store import AppEventInput
from .factory import add_spa_fallback, create_app
from .live_hub import CoreAppEventHub
from .live_member import DefaultCoreLiveMemberHooks
from .live_operations import CoreLiveContext, CoreLiveOperationHost, recover_stale_active_turns
from .project_store import ActiveProjectSessionsError, CoreProjectStore
from lamtools_core.artifact import ArtifactRegistry, ArtifactStore, kind_from_mime
from lamtools_core.tool.command_runner import warm_command_shell
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
        reasoning_level: str = "",
        max_tokens: int | None = None,
        temperature: float = 0.2,
    ) -> None:
        self.default_model_ref = default_model_ref
        self.adapter_dirs = tuple(Path(item) for item in adapter_dirs)
        self.thinking_enabled = thinking_enabled
        self.thinking_budget = thinking_budget
        self.reasoning_level = reasoning_level
        self.max_tokens = max_tokens
        self.temperature = temperature

    def with_runtime_options(
        self,
        *,
        model_id: str = "",
        thinking_enabled: bool | None = None,
        thinking_budget: int | None = None,
        reasoning_level: str | None = None,
    ) -> "CoreConfigRoutingLLMClient":
        return CoreConfigRoutingLLMClient(
            default_model_ref=model_id or self.default_model_ref,
            adapter_dirs=self.adapter_dirs,
            thinking_enabled=self.thinking_enabled if thinking_enabled is None else thinking_enabled,
            thinking_budget=self.thinking_budget if thinking_budget is None else thinking_budget,
            reasoning_level=self.reasoning_level if reasoning_level is None else reasoning_level,
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
        # An explicit model is part of the caller's routing contract.  Never
        # hide an invalid/misconfigured selection by silently switching to a
        # different default model; fatal config errors are already excluded
        # from the shared retry loop.
        config = load_llm_config(model_ref=model_ref)
        profile = _resolve_adapter_profile(config, self.adapter_dirs)
        metadata = request.metadata if isinstance(request.metadata, dict) else {}
        thinking_enabled = (
            metadata.get("thinking_enabled")
            if isinstance(metadata.get("thinking_enabled"), bool)
            else self.thinking_enabled
        )
        thinking_enabled = bool(thinking_enabled) and bool(config.thinking_supported)
        thinking_budget = (
            metadata.get("thinking_budget")
            if isinstance(metadata.get("thinking_budget"), int) and not isinstance(metadata.get("thinking_budget"), bool)
            else self.thinking_budget or config.thinking_budget
        )
        reasoning_level = str(metadata.get("reasoning_level") or self.reasoning_level or "")
        reasoning_effort = str(metadata.get("reasoning_effort") or config.reasoning_effort or "")
        return config, CoreHttpLLMClient(
            config=config,
            adapter_profile=profile,
            thinking_enabled=thinking_enabled,
            thinking_budget=thinking_budget,
            reasoning_effort=reasoning_effort,
            reasoning_level=reasoning_level,
            max_tokens=self.max_tokens or config.max_output_tokens,
            temperature=self.temperature if self.temperature is not None else config.temperature,
        )


class _MemberDefaultsHooks(DefaultCoreLiveMemberHooks):
    """Member hooks that inject member_defaults into thread materialization."""

    def __init__(
        self,
        member_defaults: dict[str, Any],
        *,
        skill_registry_factory: Any = None,
        skill_state_store_factory: Any = None,
    ) -> None:
        super().__init__(
            skill_registry_factory=skill_registry_factory,
            skill_state_store_factory=skill_state_store_factory,
        )
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
    reasoning_level: str = "",
    max_tokens: int | None = None,
    temperature: float = 0.2,
    frontend_dir: Path | str | None = None,
) -> FastAPI:
    # Resolve the command shell while the server starts. Windows automatic
    # selection runs a bounded WSL probe whose cost must not land on the first
    # model request; the cached decision is what the prompt and run_command use.
    warm_command_shell()
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
        reasoning_level=reasoning_level,
        max_tokens=max_tokens,
        temperature=temperature if temperature is not None else config.temperature,
    )
    runtime_spec = agent_spec or CoreAgentSpec(
        default_model=config.model_id,
        instructions=DEFAULT_CORE_INSTRUCTIONS,
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
            "reasoning_level": reasoning_level,
            "context_window": config.context_window,
            "capability": config.capability,
        },
    )

    core_db_path = _resolve_core_db(core_db)
    # Single work-root contract: unless explicitly overridden, the agent work
    # root is the app-side MyProject fallback. LAMTOOLS_PROJECTS_ROOT still
    # identifies the managed-project container; its parent identifies the app
    # directory consistently in packaged and development environments.
    resolved_work_root = Path(
        work_root
        or os.environ.get("LAMTOOLS_CORE_WORK_ROOT")
        or fallback_project_root()
    ).resolve()
    resolved_data_dir = Path(data_dir or os.environ.get("LAMTOOLS_CORE_DATA_DIR") or core_db_path.parent / "core-agent").resolve()
    resolved_work_root.mkdir(parents=True, exist_ok=True)
    resolved_data_dir.mkdir(parents=True, exist_ok=True)
    # Register the project work_root so load_llm_config resolves project-scoped
    # model jsonc files (models/providers are jsonc-only).
    configure_model_store_context(work_root=str(resolved_work_root))

    # A session may belong to an optional plugin resource rather than Core
    # chat. Keep such sessions out of every normal session read path unless
    # their owning plugin is currently enabled. The gate is generic; Core
    # never names a concrete plugin type here.
    session_plugin_roots = (
        [Path(item) for item in plugin_roots]
        if plugin_roots
        else default_core_agent_plugin_roots(resolved_work_root)
    )
    if core_plugins_root() not in session_plugin_roots:
        session_plugin_roots.insert(0, core_plugins_root())
    if bundled_plugins_dir() not in session_plugin_roots:
        session_plugin_roots.append(bundled_plugins_dir())
    plugin_session_visibility = PluginSessionVisibility(
        plugin_roots=session_plugin_roots,
        state_store=PluginStateStore(resolved_data_dir / "plugins.jsonc"),
    )

    operations = OperationCatalog()
    app_state: dict[str, Any] = {}
    live_hub = CoreAppEventHub()
    runtime_task_registry = RuntimeTaskRegistry()
    session_store = CoreDbSessionStore(
        lambda: app_state["core_db"],
        session_visible=plugin_session_visibility,
        fallback_work_root=resolved_work_root,
    )
    desktop_plugin_session_store = DesktopPluginSessionStore(resolved_data_dir / "desktop-plugin-sessions.json")
    desktop_plugin_session_lock = asyncio.Lock()

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
        startup_started = perf_counter()
        phase_started = startup_started
        core_db_handle = await open_core_app_db(
            core_db_path,
            member_defaults={"session": {"member_id": runtime_spec.member_id}},
            project_roots=[resolved_work_root],
            project_roots_file=resolved_data_dir / "project-roots.json",
        )
        _logger.info("[startup] database ready in %.3fs", perf_counter() - phase_started)
        phase_started = perf_counter()
        existing_project_roots = core_db_handle.project_store.project_roots()
        if str(resolved_work_root) not in existing_project_roots:
            core_db_handle.project_store.set_project_roots([
                resolved_work_root,
                *existing_project_roots,
            ])
        await core_db_handle.project_store.ensure_fallback_project(
            resolved_work_root,
            name="MyProject",
            reconcile_once=True,
        )
        _logger.info("[startup] project reconciliation ready in %.3fs", perf_counter() - phase_started)
        phase_started = perf_counter()
        app_state["core_db"] = core_db_handle
        session_store.set_sync_journal(core_db_handle.sync_journal)
        session_store.set_sync_publisher(lambda change: live_hub.broadcast(change))
        core_db_handle.project_store.set_session_visibility(plugin_session_visibility)
        core_db_handle.project_store.set_sync_publisher(
            lambda change: live_hub.broadcast(change)
        )
        core_db_handle.runtime_state_store.set_sync_publisher(
            lambda change: live_hub.broadcast(change)
        )
        app_state["attachment_store"] = CoreAttachmentStore(core_db_handle.session_factory, resolved_data_dir)
        goal_manager = GoalManager(core_db_handle.goal_store)
        plan_manager = PlanManager(core_db_handle.plan_store)
        arrange_manager = ArrangeManager(core_db_handle.arrange_store)

        async def capture_model_context(state: Any, request: Any) -> None:
            """Persist the exact semantic request context before model I/O."""
            payload = build_handoff_context(getattr(request, "messages", []))
            await core_db_handle.handoff_context_store.save(state.session_id, payload)

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

        agent_operations = create_core_agent_operations(
            spec=runtime_spec,
            member_kit=member_kit,
            paths=CoreAgentPaths(data_dir=resolved_data_dir, work_root=resolved_work_root),
            session_store=session_store,
            model_provider=llm_client,
            plugin_roots=[Path(item) for item in plugin_roots],
            db_session_factory=core_db_handle.session_factory,
            app_event_store=core_db_handle.event_store,
            thread_snapshot_store=core_db_handle.snapshot_store,
            app_event_hub=live_hub,
            write_coordinator=core_db_handle.persistence.write_coordinator,
            runtime_state_store=core_db_handle.runtime_state_store,
            runtime_task_registry=runtime_task_registry,
            goal_manager=goal_manager,
            arrange_manager=arrange_manager,
            start_plugin_lifecycle=True,
            enable_turn_checkpoints=True,
            model_display_resolver=_resolve_model_display,
            attachment_service=app_state.get("attachment_store"),
            memory_store=core_db_handle.memory_store,
            model_context_sink=capture_model_context,
        )
        _logger.info("[startup] operation catalog ready in %.3fs", perf_counter() - phase_started)
        phase_started = perf_counter()
        _register_core_project_operations(agent_operations, project_store=core_db_handle.project_store)
        _register_core_artifact_operations(
            agent_operations,
            project_store=core_db_handle.project_store,
            artifact_store=core_db_handle.artifact_store,
        )
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
        register_plan_operations(agent_operations, plan_manager=plan_manager)
        app_state["plan_manager"] = plan_manager
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
        _logger.info("[startup] stale-turn recovery ready in %.3fs", perf_counter() - phase_started)
        await arrange_runner.start()
        await observer_supervisor.start()
        _logger.info("[startup] backend ready in %.3fs", perf_counter() - startup_started)

        # Optional plugin backends are loaded and started by
        # create_core_agent_operations via the generic plugin lifecycle. Keep
        # only the handles in app state so shutdown uses the same boundary.
        app_state["plugin_runtimes"] = getattr(agent_operations, "plugin_runtimes", [])

    async def shutdown_core_agent() -> None:
        from lamtools_core.sub_agent_supervisor import shutdown_sub_agent_supervisors

        await shutdown_sub_agent_supervisors()
        await shutdown_plugin_backends(app_state.get("plugin_runtimes") or [])
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
                sync_journal=core_db_handle.sync_journal,
                session_actors=core_db_handle.session_actors,
                member_hooks=_MemberDefaultsHooks(
                    core_db_handle.member_defaults,
                    skill_registry_factory=getattr(actual_operations, "command_skill_registry_factory", None),
                    skill_state_store_factory=getattr(actual_operations, "command_skill_state_store_factory", None),
                ),
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
            export_service=lambda: ConversationExportService(
                app_state["core_db"].session_factory,
                handoff_context_store=app_state["core_db"].handoff_context_store,
            ),
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

    async def _desktop_plugin_entries(*, enabled_only: bool = True) -> list[dict[str, Any]]:
        actual = app_state.get("operations")
        if not isinstance(actual, OperationCatalog):
            raise HTTPException(status_code=503, detail="Core Agent is not ready")
        result = await actual.execute("plugin.list", {})
        if result.status != "ok":
            raise HTTPException(status_code=503, detail=str(result.payload.get("error") or "Plugin registry unavailable"))
        plugins = result.payload.get("plugins") if isinstance(result.payload, dict) else []
        if not isinstance(plugins, list):
            return []
        return [
            item
            for item in plugins
            if isinstance(item, dict)
            and isinstance(item.get("desktop"), dict)
            and (not enabled_only or item.get("enabled") is True)
        ]

    @app.get("/api/core/desktop-plugins")
    async def list_desktop_plugins() -> dict[str, Any]:
        plugins: list[dict[str, Any]] = []
        for item in await _desktop_plugin_entries():
            desktop = dict(item["desktop"])
            entry = Path(str(desktop.get("entry") or ""))
            if not entry.is_file():
                continue
            name = str(item.get("name") or "")
            plugins.append({
                "name": name,
                "title": str(desktop.get("title") or name),
                "entry_url": (
                    f"/api/core/desktop-plugins/{quote(name, safe='')}/assets/"
                    f"{quote(entry.name, safe='')}"
                ),
                "window": desktop.get("window") if isinstance(desktop.get("window"), dict) else {},
                "fileDrop": desktop.get("fileDrop") is True,
            })
        return {"plugins": plugins}

    @app.post("/api/core/desktop-plugins/{plugin_id}/session")
    async def ensure_desktop_plugin_session(plugin_id: str) -> dict[str, Any]:
        plugin_id = str(plugin_id).strip()
        candidates = await _desktop_plugin_entries(enabled_only=False)
        plugin = next(
            (item for item in candidates if str(item.get("name") or "") == plugin_id),
            None,
        )
        if plugin is None or plugin.get("enabled") is not True:
            raise HTTPException(status_code=404, detail="Enabled desktop plugin not found")

        async with desktop_plugin_session_lock:
            mapped_session_id = desktop_plugin_session_store.get(plugin_id)
            if mapped_session_id:
                existing = await session_store.get(mapped_session_id)
                if existing is not None:
                    return {
                        "plugin_id": plugin_id,
                        "session_id": existing.id,
                        "created": False,
                        "session": existing.to_dict(),
                    }
                desktop_plugin_session_store.delete(plugin_id)

            desktop = plugin.get("desktop") if isinstance(plugin.get("desktop"), dict) else {}
            record = build_session_record(
                member_id=runtime_spec.member_id,
                title=str(desktop.get("title") or plugin_id),
                metadata={"desktop_plugin_id": plugin_id, "source": "desktop_plugin"},
            )
            await session_store.create(record)
            desktop_plugin_session_store.set(plugin_id, record.id)
            return {
                "plugin_id": plugin_id,
                "session_id": record.id,
                "created": True,
                "session": record.to_dict(),
            }

    @app.get("/api/core/desktop-plugins/{plugin_name}/assets/{asset_path:path}")
    async def desktop_plugin_asset(plugin_name: str, asset_path: str) -> FileResponse:
        plugin = next(
            (item for item in await _desktop_plugin_entries() if str(item.get("name") or "") == plugin_name),
            None,
        )
        if plugin is None:
            raise HTTPException(status_code=404, detail="Desktop plugin not found")
        desktop = plugin.get("desktop")
        entry = Path(str(desktop.get("entry") or "")).resolve() if isinstance(desktop, dict) else Path()
        desktop_root = entry.parent
        target = (desktop_root / asset_path).resolve()
        if not target.is_relative_to(desktop_root) or not target.is_file():
            raise HTTPException(status_code=404, detail="Desktop plugin asset not found")
        # Desktop plugins can be updated independently while Core keeps the
        # same loopback route. Do not let WebView2 pin stale HTML/JS in its
        # memory cache across host reloads.
        return FileResponse(target, headers={"Cache-Control": "no-store"})

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
        revision_id: str | None = Query(default=None),
    ) -> FileResponse:
        """按 Artifact ID 读取不可变 Revision；无快照时兼容底层文件路径。

        ``path`` 为兜底：旧会话事件里的 artifact_id 是投影派生 id（artifact-{sha1}），
        无法直接命中 V2 事实层时按路径解析旧 manifest 别名。
        """
        project = await app_state["core_db"].project_store.get(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        store: ArtifactStore = app_state["core_db"].artifact_store
        await store.migrate_legacy(project_id=project_id, work_root=project.work_root)
        record = await store.get(artifact_id)
        if record is None and path:
            registry = ArtifactRegistry(project.work_root)
            resolved_id = registry.resolve_artifact_id(path, work_root=project.work_root)
            if resolved_id:
                record = await store.get(resolved_id)
        if record is None or record.project_id != project_id:
            raise HTTPException(status_code=404, detail="Artifact not found")
        target_revision_id = revision_id or record.latest_revision_id
        if target_revision_id:
            historical = await store.revision_path(record.artifact_id, target_revision_id)
            if historical is None or not historical.is_file():
                raise HTTPException(status_code=404, detail="Artifact revision not found")
            path = historical
            filename = record.name
            mime = record.mime_type
        elif record.path.startswith("attachment://"):
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
        """上传即登记为项目输入 Artifact（best-effort，失败不影响上传）。"""
        if not project_id:
            return
        artifact_id = str(record.get("id") or "")
        if not artifact_id:
            return
        try:
            project = await app_state["core_db"].project_store.get(project_id)
            if project is None:
                return
            store: ArtifactStore = app_state["core_db"].artifact_store
            attachment_record = await attachment_store().get(artifact_id)
            attachment_path = Path(attachment_record.storage_path) if attachment_record is not None else Path()
            await store.register(
                project_id=project_id,
                work_root=project.work_root,
                kind=kind_from_mime(str(record.get("mime_type") or "")),
                mime_type=str(record.get("mime_type") or ""),
                name=str(record.get("filename") or artifact_id),
                path=f"attachment://{artifact_id}",
                source="user_upload",
                role="input",
                preferred_id=artifact_id,
                content=attachment_path.read_bytes() if attachment_path.is_file() else None,
                provenance={"attachment_id": artifact_id},
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
    async def project_roots_get(request: OperationRequest) -> OperationResult:
        del request
        return OperationResult(
            name="project.roots.get",
            payload={"roots": project_store.project_roots()},
        )

    async def project_roots_set(request: OperationRequest) -> OperationResult:
        raw_roots = request.payload.get("roots")
        if not isinstance(raw_roots, list) or not all(isinstance(item, str) for item in raw_roots):
            return OperationResult(
                name=request.name,
                status="error",
                payload={"error": "roots must be a list of paths"},
            )
        try:
            roots = project_store.set_project_roots(raw_roots)
        except (OSError, ValueError) as exc:
            return OperationResult(name=request.name, status="error", payload={"error": str(exc)})
        return OperationResult(name=request.name, payload={"roots": roots})

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
        visual: dict[str, Any] = {}
        if "icon_key" in payload or "iconKey" in payload:
            visual["icon_key"] = payload.get("icon_key", payload.get("iconKey"))
        if "color_key" in payload or "colorKey" in payload:
            visual["color_key"] = payload.get("color_key", payload.get("colorKey"))
        try:
            project, session, _ = await project_store.create_with_initial_session(
                work_root,
                name=payload.get("name") if "name" in payload else None,
                **visual,
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
        payload = request.payload
        try:
            project = await project_store.update(
                _project_id(request),
                name=payload.get("name") if "name" in payload else None,
                icon_key=(
                    payload.get("icon_key", payload.get("iconKey"))
                    if "icon_key" in payload or "iconKey" in payload
                    else None
                ),
                color_key=(
                    payload.get("color_key", payload.get("colorKey"))
                    if "color_key" in payload or "colorKey" in payload
                    else None
                ),
            )
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
        "project.roots.get": project_roots_get,
        "project.roots.set": project_roots_set,
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
        from lamtools_core.sub_agent_supervisor import shutdown_parent_sub_agents

        await shutdown_parent_sub_agents(sid)
        await session_store.delete(sid)
        return OperationResult(name="session.delete", payload={"deleted": sid})

    for name, handler in [("session.list", session_list), ("session.get", session_get), ("session.delete", session_delete)]:
        if not catalog.has(name):
            catalog.register(name, handler)


def _project_id(request: OperationRequest) -> str:
    return str(request.payload.get("project_id") or request.payload.get("projectId") or request.payload.get("id") or "")


def _register_core_artifact_operations(
    catalog: OperationCatalog,
    *,
    project_store: CoreProjectStore,
    artifact_store: ArtifactStore,
) -> None:
    """Artifact V2 operations backed by the Core runtime database."""

    async def _project_for(request: OperationRequest) -> Any | None:
        project = await project_store.get(_project_id(request))
        if project is not None:
            await artifact_store.migrate_legacy(project_id=project.id, work_root=project.work_root)
        return project

    async def artifact_list(request: OperationRequest) -> OperationResult:
        project = await _project_for(request)
        if project is None:
            return OperationResult(name=request.name, status="error", payload={"error": "Project not found"})
        records = await artifact_store.list(project.id, include_deleted=bool(request.payload.get("include_deleted")))
        return OperationResult(name=request.name, payload={"artifacts": [record.to_dict() for record in records]})

    async def artifact_read(request: OperationRequest) -> OperationResult:
        project = await _project_for(request)
        if project is None:
            return OperationResult(name=request.name, status="error", payload={"error": "Project not found"})
        artifact_id = str(request.payload.get("artifact_id") or request.payload.get("artifactId") or "")
        record = await artifact_store.get(artifact_id)
        if record is None or record.project_id != project.id:
            return OperationResult(name=request.name, status="error", payload={"error": "Artifact not found"})
        return OperationResult(name=request.name, payload={"artifact": record.to_dict()})

    async def artifact_revisions(request: OperationRequest) -> OperationResult:
        read = await artifact_read(request)
        if read.status == "error":
            return read
        artifact = read.payload["artifact"]
        revisions = await artifact_store.revisions(str(artifact["artifact_id"]))
        return OperationResult(name=request.name, payload={"artifact": artifact, "revisions": [r.to_dict() for r in revisions]})

    async def artifact_remove(request: OperationRequest) -> OperationResult:
        project = await _project_for(request)
        if project is None:
            return OperationResult(name=request.name, status="error", payload={"error": "Project not found"})
        raw = request.payload.get("artifact_ids") or request.payload.get("artifactIds")
        ids = [str(item) for item in raw if str(item).strip()] if isinstance(raw, list) else []
        if not ids:
            return OperationResult(name=request.name, status="error", payload={"error": "artifact_ids is required"})
        return OperationResult(
            name=request.name,
            payload={"deleted": await artifact_store.soft_remove(ids, project_id=project.id)},
        )

    async def artifact_restore(request: OperationRequest) -> OperationResult:
        project = await _project_for(request)
        if project is None:
            return OperationResult(name=request.name, status="error", payload={"error": "Project not found"})
        raw = request.payload.get("artifact_ids") or request.payload.get("artifactIds")
        ids = [str(item) for item in raw if str(item).strip()] if isinstance(raw, list) else []
        return OperationResult(
            name=request.name,
            payload={
                "restored": await artifact_store.soft_remove(
                    ids,
                    deleted=False,
                    project_id=project.id,
                )
            },
        )

    async def artifact_revision_restore(request: OperationRequest) -> OperationResult:
        project = await _project_for(request)
        if project is None:
            return OperationResult(name=request.name, status="error", payload={"error": "Project not found"})
        try:
            record = await artifact_store.restore_revision(
                str(request.payload.get("artifact_id") or request.payload.get("artifactId") or ""),
                str(request.payload.get("revision_id") or request.payload.get("revisionId") or ""),
                project_id=project.id,
            )
        except (LookupError, OSError, ValueError) as exc:
            return OperationResult(name=request.name, status="error", payload={"error": str(exc)})
        return OperationResult(name=request.name, payload={"artifact": record.to_dict()})

    async def artifact_open(request: OperationRequest) -> OperationResult:
        project = await _project_for(request)
        if project is None:
            return OperationResult(name=request.name, status="error", payload={"error": "Project not found"})
        artifact_id = str(request.payload.get("artifact_id") or request.payload.get("artifactId") or "")
        record = await artifact_store.get(artifact_id) if artifact_id else None
        if record is not None and record.project_id != project.id:
            record = None
        artifact_path = record.path if record is not None else str(request.payload.get("path") or "").strip()
        if not artifact_path:
            return OperationResult(name=request.name, status="error", payload={"error": "Artifact path not found"})
        if artifact_path.startswith("attachment://"):
            return OperationResult(name=request.name, status="error", payload={"error": "Attachment-backed artifacts must use attachment.open"})
        root = Path(project.work_root).resolve()
        candidate = (root / artifact_path.removeprefix("workspace://")).resolve()
        try:
            candidate.relative_to(root)
            if not candidate.is_file():
                raise FileNotFoundError(candidate)
            from lamtools_core.attachment import open_with_default_app
            open_with_default_app(candidate)
        except (FileNotFoundError, OSError, ValueError) as exc:
            return OperationResult(name=request.name, status="error", payload={"error": str(exc)})
        return OperationResult(name=request.name, payload={"status": "opened", "path": artifact_path})

    handlers = {
        "artifact.list": artifact_list,
        "artifact.read": artifact_read,
        "artifact.show": artifact_read,
        "artifact.revisions": artifact_revisions,
        "artifact.delete": artifact_remove,
        "artifact.remove": artifact_remove,
        "artifact.restore": artifact_restore,
        "artifact.revision.restore": artifact_revision_restore,
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
        adapter_profile = _resolve_adapter_profile(config, ())
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
                        "reasoning_off_supported": reasoning_off_supported(adapter_profile),
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
        ]
        # Plugin backends contribute their own model-facing tools. Read the
        # normalized runtime handles exposed by the generic operation catalog
        # instead of importing any plugin implementation from Core.
        for handle in getattr(catalog, "plugin_runtimes", []) or []:
            runtime_specs = getattr(handle.value, "tool_specs", [])
            if callable(runtime_specs):
                runtime_specs = runtime_specs()
            if isinstance(runtime_specs, (list, tuple)):
                specs.extend(runtime_specs)
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
    from lamtools_core.config.model_group_store import ModelGroupStore
    from lamtools_core.config.model_store import ModelConfig, ModelStore, make_model_record_id
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

    def _payload_model_config(record_id: str, payload: dict[str, Any]) -> ModelConfig:
        thinking = payload.get("thinking") if isinstance(payload.get("thinking"), dict) else {}
        extra = payload.get("extra") if isinstance(payload.get("extra"), dict) else {}
        request_body = (
            payload.get("request_body")
            if isinstance(payload.get("request_body"), dict)
            else extra.get("request_body") if isinstance(extra.get("request_body"), dict) else {}
        )
        profile_override = (
            payload.get("adapter_profile_override")
            if isinstance(payload.get("adapter_profile_override"), dict)
            else extra.get("adapter_profile_override")
            if isinstance(extra.get("adapter_profile_override"), dict)
            else {}
        )
        reasoning = (
            payload.get("reasoning")
            if isinstance(payload.get("reasoning"), dict)
            else extra.get("reasoning") if isinstance(extra.get("reasoning"), dict) else {}
        )
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
            id=record_id,
            model_id=str(payload.get("model_id") or record_id),
            display_name=str(payload.get("display_name") or ""),
            provider=provider_name,
            provider_id=provider_id,
            context_window=int(payload.get("context_window") or 0),
            max_output_tokens=int(payload.get("max_output_tokens") or 4096),
            temperature=float(payload.get("temperature") or 0.2),
            thinking_supported=bool(thinking.get("supported", payload.get("thinking_supported") or False)),
            thinking_budget=int(thinking.get("budget", payload.get("thinking_budget") or 10000)),
            reasoning_effort=str(payload.get("reasoning_effort") or ""),
            adapter_profile_id=str(payload.get("adapter_profile_id") or extra.get("adapter_profile_id") or ""),
            request_body=request_body,
            adapter_profile_override=dict(profile_override),
            reasoning=dict(reasoning),
            capability=str(payload.get("capability") or extra.get("capability") or "").strip().lower(),
            notes=str(payload.get("notes") or "").strip(),
            is_default=bool(payload.get("is_default") or False),
        )

    async def models_upsert(request: OperationRequest) -> OperationResult:
        payload = request.payload if isinstance(request.payload, dict) else {}
        upstream_model_id = str(payload.get("model_id") or "").strip()
        if not upstream_model_id:
            return OperationResult(name=request.name, status="error", payload={"error": "model_id is required"})
        scope = str(payload.get("scope") or "global").strip()
        if scope not in ("project", "global"):
            return OperationResult(name=request.name, status="error", payload={"error": "scope must be 'project' or 'global'"})
        root = str(payload.get("work_root") or payload.get("workRoot") or "").strip() or work_root
        if scope == "project" and not root:
            return OperationResult(name=request.name, status="error", payload={"error": "work_root is required for project scope"})
        # Clear is_default on all other models when setting a new default.
        store = _store()
        record_id = str(payload.get("model_record_id") or payload.get("id") or "").strip()
        existing = store.get_sync(record_id, work_root=str(root) if root else None) if record_id else None
        if existing is not None:
            record_id = existing.id
        if not record_id:
            provider_ref = str(payload.get("provider_id") or payload.get("provider") or payload.get("provider_name") or "")
            base_id = make_model_record_id(provider_ref, upstream_model_id)
            record_id = base_id
            suffix = 2
            while store.get_sync(record_id, work_root=str(root) if root else None) is not None:
                record_id = f"{base_id[:124]}-{suffix}"
                suffix += 1
        model = _payload_model_config(record_id, payload)
        if model.is_default:
            for existing in store.list_sync(work_root=str(root) if root else None):
                if existing.id != model.id and existing.is_default:
                    existing.is_default = False
                    store.write(existing, scope=scope, work_root=root)
        path = store.write(model, scope=scope, work_root=root)
        return OperationResult(name=request.name, payload={
            "path": str(path),
            "id": model.id,
            "model_record_id": model.id,
            "model_id": model.model_id,
            "scope": scope,
        })

    async def models_delete(request: OperationRequest) -> OperationResult:
        from pathlib import Path as _Path

        payload = request.payload if isinstance(request.payload, dict) else {}
        model_ref = str(payload.get("model_record_id") or payload.get("model_id") or "").strip()
        scope = str(payload.get("scope") or "global").strip()
        if not model_ref:
            return OperationResult(name=request.name, status="error", payload={"error": "model_id is required"})
        root = str(payload.get("work_root") or payload.get("workRoot") or "").strip() or work_root
        store = _store()
        model = store.get_sync(model_ref, work_root=str(root) if root else None)
        if model is None:
            return OperationResult(name=request.name, status="error", payload={"error": f"model not found: {model_ref}"})
        path = _Path(model.source_path) if model.source_path else ModelStore.write_path(model.id, scope=scope, work_root=root)
        if not path.is_file():
            return OperationResult(name=request.name, status="error", payload={"error": f"no model file at {path}"})
        path.unlink()
        store._cached_signature = None  # invalidate cache
        store._cached_models = None
        ModelGroupStore().remove_model_ids([model.id])
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
            if existing.id != model.id and existing.is_default:
                store.write(replace(existing, is_default=False), scope=scope, work_root=root)
        path = store.write(replace(model, is_default=True), scope=scope, work_root=root)
        return OperationResult(name=request.name, payload={
            "path": str(path),
            "id": model.id,
            "model_record_id": model.id,
            "model_id": model.model_id,
            "scope": scope,
        })

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
        effective_root = root or str(work_root or "").strip() or None
        requested_scope = str(request.payload.get("scope") or "").strip().lower()
        if requested_scope == "project" and not effective_root:
            return OperationResult(
                name=request.name,
                status="error",
                payload={"error": "work_root is required to read a project-scoped guide"},
            )

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
        effective_root = root or str(work_root or "").strip() or None
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
            DELEGATION_STRATEGY_KEY,
            ROLE_ASSIGNMENTS_KEY,
            load_effective_delegation_strategy,
            load_effective_role_assignments,
            load_global_delegation_strategy,
            load_local_subagent_settings,
            load_subagent_settings,
            normalize_delegation_strategy,
            resolve_subagent_settings_path,
            settings_path_for_scope,
        )

        root = str(request.payload.get("work_root") or request.payload.get("workRoot") or "").strip()
        effective_root = root or str(work_root or "").strip() or None
        requested_scope = str(request.payload.get("scope") or "").strip().lower()
        if requested_scope == "project" and not effective_root:
            return OperationResult(
                name=request.name,
                status="error",
                payload={"error": "work_root is required to read project-scoped settings"},
            )

        # When a specific scope is requested, read only that level's file
        if requested_scope in ("project", "global"):
            path = settings_path_for_scope(requested_scope, effective_root)
            local_settings = load_local_subagent_settings(
                requested_scope, effective_root
            )
            role_assignments_inherited = ROLE_ASSIGNMENTS_KEY not in local_settings
            delegation_strategy_inherited = (
                DELEGATION_STRATEGY_KEY not in local_settings
            )
            settings = {**DEFAULT_SUBAGENT_SETTINGS, **local_settings}
            # The scoped editor always receives local rows. An absent field is
            # represented as [] plus the inheritance marker, never as an
            # effective value that could be written back accidentally.
            settings[ROLE_ASSIGNMENTS_KEY] = local_settings.get(
                ROLE_ASSIGNMENTS_KEY, []
            )
            local_strategy: str | None = None
            if not delegation_strategy_inherited:
                try:
                    local_strategy = normalize_delegation_strategy(
                        local_settings[DELEGATION_STRATEGY_KEY]
                    )
                except ValueError:
                    local_strategy = None
            settings[DELEGATION_STRATEGY_KEY] = local_strategy
            return OperationResult(
                name=request.name,
                payload={
                    "settings": settings,
                    "effective_role_assignments": load_effective_role_assignments(
                        effective_root
                    ),
                    "role_assignments_inherited": role_assignments_inherited,
                    "effective_delegation_strategy": load_effective_delegation_strategy(
                        effective_root
                    ),
                    "global_delegation_strategy": load_global_delegation_strategy(),
                    "delegation_strategy_inherited": delegation_strategy_inherited,
                    "scope": requested_scope,
                    "resolved_path": str(path) if path.is_file() else "",
                    "is_builtin": not path.is_file(),
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
                "effective_role_assignments": load_effective_role_assignments(
                    effective_root
                ),
                "role_assignments_inherited": False,
                "effective_delegation_strategy": load_effective_delegation_strategy(
                    effective_root
                ),
                "global_delegation_strategy": load_global_delegation_strategy(),
                "delegation_strategy_inherited": False,
                "scope": scope,
                "resolved_path": str(resolved) if resolved is not None else "",
                "is_builtin": resolved is None,
            },
        )

    async def subagent_settings_set(request: OperationRequest) -> OperationResult:
        from lamtools_core.config.subagent_prompt import (
            DELEGATION_STRATEGY_KEY,
            normalize_delegation_strategy,
            normalize_role_assignments,
            write_subagent_settings,
        )

        updates = (
            dict(request.payload["settings"])
            if isinstance(request.payload.get("settings"), dict)
            else {}
        )
        # Also accept top-level keys for convenience (e.g. {default_multimodal_model: "..."})
        for key in ("default_multimodal_model",):
            val = request.payload.get(key)
            if val is not None:
                updates[key] = str(val).strip()
        if DELEGATION_STRATEGY_KEY in request.payload:
            updates[DELEGATION_STRATEGY_KEY] = request.payload[
                DELEGATION_STRATEGY_KEY
            ]
        scope = str(request.payload.get("scope") or "global").strip()
        if scope not in ("project", "global"):
            return OperationResult(
                name=request.name, status="error",
                payload={"error": "scope must be 'project' or 'global'"},
            )
        root = str(request.payload.get("work_root") or request.payload.get("workRoot") or "").strip()
        effective_root = root or str(work_root or "").strip() or None
        if scope == "project" and not effective_root:
            return OperationResult(
                name=request.name, status="error",
                payload={"error": "work_root is required to save a project-scoped setting"},
            )
        if "role_assignments" in updates:
            try:
                updates["role_assignments"] = normalize_role_assignments(
                    updates["role_assignments"]
                )
            except ValueError as exc:
                return OperationResult(
                    name=request.name,
                    status="error",
                    payload={"error": str(exc)},
                )
        if DELEGATION_STRATEGY_KEY in updates and updates[DELEGATION_STRATEGY_KEY] is not None:
            try:
                updates[DELEGATION_STRATEGY_KEY] = normalize_delegation_strategy(
                    updates[DELEGATION_STRATEGY_KEY]
                )
            except ValueError as exc:
                return OperationResult(
                    name=request.name,
                    status="error",
                    payload={"error": str(exc)},
                )
        try:
            path = write_subagent_settings(updates, scope=scope, work_root=effective_root)
        except (OSError, ValueError) as exc:
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
