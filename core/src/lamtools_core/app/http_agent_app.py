"""FastAPI assembly for the standalone Core Agent HTTP app."""

from __future__ import annotations

import os
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from lamtools_core.cli import (
    CoreHttpLLMClient,
    _resolve_adapter_profile,
    _resolve_config_db,
    _resolve_core_db,
    list_llm_model_configs,
    load_llm_config,
)
from lamtools_core.http import create_core_router
from lamtools_core.llm import LLMRequest
from lamtools_core.config import build_shared_config_operation_catalog
from lamtools_core.attachment import CoreAttachmentStore
from lamtools_core.runtime import RuntimeTaskRegistry
from lamtools_core.runtime.arrange import ArrangeManager, ArrangeRunner, arranged_operation_payload
from lamtools_core.runtime.goal import GoalManager
from lamtools_core.runtime.observer import ObserverSupervisor
from lamtools_core.member import MemberKit, MemberManifest

from .core_db import open_core_app_db
from .core_session_store import CoreDbSessionStore
from .default_agent import CoreAgentPaths, CoreAgentSpec, create_core_agent_operations
from .durable_operations import register_durable_operations
from .factory import create_app
from .live_hub import CoreAppEventHub
from .live_operations import CoreLiveContext, CoreLiveOperationHost
from .persistence_host import AppPersistenceHost
from .project_store import ActiveProjectSessionsError, CoreProjectStore
from .live_router import create_core_live_router
from .operation_catalog import OperationCatalog, OperationRequest, OperationResult


class CoreConfigRoutingLLMClient:
    """LLM client that resolves provider/model from the shared config DB per request."""

    def __init__(
        self,
        *,
        config_db_path: Path,
        default_model_ref: str,
        adapter_dirs: tuple[Path | str, ...] = (),
        thinking_enabled: bool = True,
        thinking_budget: int = 10000,
        max_tokens: int | None = None,
        temperature: float = 0.2,
    ) -> None:
        self.config_db_path = Path(config_db_path)
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
            config_db_path=self.config_db_path,
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
        config = load_llm_config(self.config_db_path, model_ref=model_ref)
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
        return config, CoreHttpLLMClient(
            config=config,
            adapter_profile=profile,
            thinking_enabled=thinking_enabled,
            thinking_budget=thinking_budget,
            max_tokens=self.max_tokens or config.max_output_tokens,
            temperature=self.temperature if self.temperature is not None else config.temperature,
        )


def create_core_agent_http_app(
    *,
    agent_spec: CoreAgentSpec | None = None,
    member_kit: MemberKit | None = None,
    members: list[MemberManifest] | None = None,
    model_id: str = "",
    config_db: Path | str | None = None,
    core_db: Path | str | None = None,
    data_dir: Path | str | None = None,
    work_root: Path | str | None = None,
    plugin_roots: tuple[Path | str, ...] = (),
    thinking_enabled: bool = True,
    thinking_budget: int = 10000,
    max_tokens: int | None = None,
    temperature: float = 0.2,
) -> FastAPI:
    config_db_path = _resolve_config_db(config_db)
    config = load_llm_config(config_db_path, model_ref=model_id)
    llm_client = CoreConfigRoutingLLMClient(
        config_db_path=config_db_path,
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
        },
    )

    core_db_path = _resolve_core_db(core_db)
    resolved_work_root = Path(work_root or os.environ.get("LAMTOOLS_CORE_WORK_ROOT") or Path.cwd()).resolve()
    resolved_data_dir = Path(data_dir or os.environ.get("LAMTOOLS_CORE_DATA_DIR") or core_db_path.parent / "core-agent").resolve()
    resolved_work_root.mkdir(parents=True, exist_ok=True)
    resolved_data_dir.mkdir(parents=True, exist_ok=True)

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

    async def startup_core_agent() -> None:
        core_db_handle = await open_core_app_db(
            core_db_path,
            member_defaults={"session": {"member_id": runtime_spec.member_id}},
        )
        app_state["core_db"] = core_db_handle
        app_state["attachment_store"] = CoreAttachmentStore(core_db_handle.session_factory, resolved_data_dir)
        goal_manager = GoalManager(core_db_handle.goal_store)
        arrange_manager = ArrangeManager(core_db_handle.arrange_store)
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
            enable_turn_checkpoints=True,
        )
        _register_core_project_operations(agent_operations, project_store=core_db_handle.project_store)
        _register_core_config_operations(
            agent_operations,
            config_db_path=config_db_path,
            default_model_id=config.model_record_id,
        )
        config_engine = create_async_engine(f"sqlite+aiosqlite:///{config_db_path}")
        config_session_factory = async_sessionmaker(config_engine, expire_on_commit=False)
        _register_missing_operations(
            agent_operations,
            build_shared_config_operation_catalog(config_session_factory),
        )

        async def execute_arranged_job(job: Any) -> OperationResult:
            payload = arranged_operation_payload(job)
            if job.operation == "turn.start":
                payload["run_id"] = job.occurrence_id
                payload["turn_id"] = f"{job.thread_id}:turn:{job.occurrence_id}"
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
        app_state["config_engine"] = config_engine
        app_state["operations"] = agent_operations
        app_state["arrange_runner"] = arrange_runner
        app_state["observer_supervisor"] = observer_supervisor
        await arrange_runner.start()
        await observer_supervisor.start()

    async def shutdown_core_agent() -> None:
        observer_supervisor = app_state.get("observer_supervisor")
        if observer_supervisor is not None:
            await observer_supervisor.stop()
        arrange_runner = app_state.get("arrange_runner")
        if arrange_runner is not None:
            await arrange_runner.stop()
        await runtime_task_registry.shutdown()
        config_engine = app_state.get("config_engine")
        if config_engine is not None:
            await config_engine.dispose()
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
            ),
        )

    app = create_app(
        members=members,
        title=runtime_spec.name,
        enable_core_routes=False,
        health_payload=lambda: {
            "status": "ok",
            "agent": runtime_spec.member_id,
            "agent_id": runtime_spec.id,
            "agent_name": runtime_spec.name,
            "model": config.display_name or config.model_id,
            "work_root": str(resolved_work_root),
            "core_db": str(core_db_path),
        },
        on_startup=[startup_core_agent],
        on_shutdown=[shutdown_core_agent],
    )
    app.include_router(
        create_core_router(
            session_store=session_store,
            operations=operations,
            project_store=lambda: app_state["core_db"].project_store,
        ),
        prefix="/api/core",
    )
    app.include_router(create_core_live_router(live_context), prefix="/api/core")

    @app.get("/api/core/config/models")
    async def list_config_models() -> dict[str, Any]:
        return {"models": list_llm_model_configs(config_db_path)}

    @app.get("/api/core/config/providers")
    async def list_config_providers() -> dict[str, Any]:
        return {"providers": _list_llm_provider_configs(config_db_path)}

    def attachment_store() -> CoreAttachmentStore:
        store = app_state.get("attachment_store")
        if not isinstance(store, CoreAttachmentStore):
            raise HTTPException(status_code=503, detail="Core Agent is not ready")
        return store

    @app.post("/api/core/sessions/{session_id}/attachments")
    async def upload_attachment(session_id: str, file: UploadFile = File(...)) -> dict[str, Any]:
        return await attachment_store().create(session_id, file.filename or "attachment", await file.read(), file.content_type)

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


def _project_id(request: OperationRequest) -> str:
    return str(request.payload.get("project_id") or request.payload.get("projectId") or request.payload.get("id") or "")


def _register_core_config_operations(
    catalog: OperationCatalog,
    *,
    config_db_path: Path,
    default_model_id: str,
) -> None:
    async def config_models_list(request: OperationRequest) -> OperationResult:
        del request
        return OperationResult(
            name="config.models.list",
            payload={
                "models": list_llm_model_configs(config_db_path),
                "default_model_id": default_model_id,
            },
        )

    async def config_providers_list(request: OperationRequest) -> OperationResult:
        del request
        return OperationResult(name="config.providers.list", payload={"providers": _list_llm_provider_configs(config_db_path)})

    async def config_resolved_get(request: OperationRequest) -> OperationResult:
        task_type = str(request.payload.get("task_type") or request.payload.get("taskType") or "core")
        model_ref = str(request.payload.get("model_id") or request.payload.get("modelId") or "")
        config = load_llm_config(config_db_path, model_ref=model_ref)
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


def _list_llm_provider_configs(config_db_path: Path) -> list[dict[str, Any]]:
    import sqlite3

    con = sqlite3.connect(config_db_path)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            """
            select id,name,api_type,base_url
            from llm_providers
            order by created_at asc
            """
        ).fetchall()
    finally:
        con.close()
    return [
        {
            "id": str(row["id"] or ""),
            "name": str(row["name"] or ""),
            "api_type": str(row["api_type"] or ""),
            "base_url": str(row["base_url"] or ""),
        }
        for row in rows
    ]


def create_default_core_agent_http_app() -> FastAPI:
    model_id = os.environ.get("LAMTOOLS_CORE_MODEL_ID") or "xopkimik26"
    config_db = os.environ.get("LAMTOOLS_LLM_CONFIG_DB") or None
    core_db = os.environ.get("LAMTOOLS_CORE_DB") or None
    data_dir = os.environ.get("LAMTOOLS_CORE_DATA_DIR") or None
    work_root = os.environ.get("LAMTOOLS_CORE_WORK_ROOT") or None
    return create_core_agent_http_app(
        model_id=model_id,
        config_db=config_db,
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
