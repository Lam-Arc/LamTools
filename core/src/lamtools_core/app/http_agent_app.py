"""FastAPI assembly for the standalone Core Agent HTTP app."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from typing import Any

from fastapi import FastAPI
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

from .core_db import open_core_app_db
from .core_session_store import CoreDbSessionStore
from .default_agent import CoreAgentPaths, CoreAgentSpec, create_core_agent_operations
from .factory import create_app
from .live_hub import CoreAppEventHub
from .live_operations import CoreLiveContext, CoreLiveOperationHost
from .persistence_host import AppPersistenceHost
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
        max_tokens: int = 4096,
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
    model_id: str = "",
    config_db: Path | str | None = None,
    core_db: Path | str | None = None,
    data_dir: Path | str | None = None,
    work_root: Path | str | None = None,
    plugin_roots: tuple[Path | str, ...] = (),
    thinking_enabled: bool = True,
    thinking_budget: int = 10000,
    max_tokens: int = 4096,
    temperature: float = 0.2,
) -> FastAPI:
    config_db_path = _resolve_config_db(config_db)
    config = load_llm_config(config_db_path, model_ref=model_id)
    llm_client = CoreConfigRoutingLLMClient(
        config_db_path=config_db_path,
        default_model_ref=model_id or config.model_record_id or config.model_id,
        thinking_enabled=thinking_enabled,
        thinking_budget=thinking_budget or config.thinking_budget,
        max_tokens=max_tokens or config.max_output_tokens,
        temperature=temperature if temperature is not None else config.temperature,
    )

    core_db_path = _resolve_core_db(core_db)
    resolved_work_root = Path(work_root or os.environ.get("LAMTOOLS_CORE_WORK_ROOT") or Path.cwd()).resolve()
    resolved_data_dir = Path(data_dir or os.environ.get("LAMTOOLS_CORE_DATA_DIR") or core_db_path.parent / "core-agent").resolve()
    resolved_work_root.mkdir(parents=True, exist_ok=True)
    resolved_data_dir.mkdir(parents=True, exist_ok=True)

    operations = OperationCatalog()
    app_state: dict[str, Any] = {}
    live_hub = CoreAppEventHub()
    session_store = CoreDbSessionStore(lambda: app_state["core_db"])

    async def execute_core_operation(request: OperationRequest) -> OperationResult:
        actual = app_state.get("operations")
        if not isinstance(actual, OperationCatalog):
            return OperationResult(name=request.name, status="error", payload={"error": "Core Agent is not ready"})
        return await actual.execute(request.name, request.payload, metadata=request.metadata)

    operations.register("turn.start", execute_core_operation)
    operations.register("approval.respond", execute_core_operation)

    async def startup_core_agent() -> None:
        core_db_handle = await open_core_app_db(core_db_path)
        app_state["core_db"] = core_db_handle
        agent_operations = create_core_agent_operations(
            spec=CoreAgentSpec(
                default_model=config.model_id,
                instructions="You are LamTools Core Agent, a standalone general-purpose agent runtime.",
                metadata={
                    "provider": config.provider_name,
                    "model_record_id": config.model_record_id,
                    "thinking_enabled": thinking_enabled,
                    "thinking_budget": thinking_budget or config.thinking_budget,
                },
            ),
            paths=CoreAgentPaths(data_dir=resolved_data_dir, work_root=resolved_work_root),
            model_provider=llm_client,
            plugin_roots=[Path(item) for item in plugin_roots],
            db_session_factory=core_db_handle.session_factory,
            app_event_store=core_db_handle.event_store,
            thread_snapshot_store=core_db_handle.snapshot_store,
            app_event_hub=live_hub,
            runtime_state_store=core_db_handle.runtime_state_store,
        )
        _register_core_config_operations(agent_operations, config_db_path=config_db_path)
        config_engine = create_async_engine(f"sqlite+aiosqlite:///{config_db_path}")
        config_session_factory = async_sessionmaker(config_engine, expire_on_commit=False)
        _register_missing_operations(
            agent_operations,
            build_shared_config_operation_catalog(config_session_factory),
        )
        app_state["config_engine"] = config_engine
        app_state["operations"] = agent_operations

    async def shutdown_core_agent() -> None:
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
            ),
        )

    app = create_app(
        title="LamTools Core Agent",
        enable_core_routes=False,
        health_payload=lambda: {
            "status": "ok",
            "agent": "core",
            "model": config.display_name or config.model_id,
            "work_root": str(resolved_work_root),
            "core_db": str(core_db_path),
        },
        on_startup=[startup_core_agent],
        on_shutdown=[shutdown_core_agent],
    )
    app.include_router(create_core_router(session_store=session_store, operations=operations), prefix="/api/core")
    app.include_router(create_core_live_router(live_context), prefix="/api/core")

    @app.get("/api/core/config/models")
    async def list_config_models() -> dict[str, Any]:
        return {"models": list_llm_model_configs(config_db_path)}

    @app.get("/api/core/config/providers")
    async def list_config_providers() -> dict[str, Any]:
        return {"providers": _list_llm_provider_configs(config_db_path)}

    app.state.core_agent_app_state = app_state
    app.state.core_agent_work_root = resolved_work_root
    app.state.core_agent_data_dir = resolved_data_dir
    return app


def _register_core_config_operations(catalog: OperationCatalog, *, config_db_path: Path) -> None:
    async def config_models_list(request: OperationRequest) -> OperationResult:
        del request
        return OperationResult(name="config.models.list", payload={"models": list_llm_model_configs(config_db_path)})

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
        max_tokens=_env_int("LAMTOOLS_CORE_MAX_TOKENS", default=4096),
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
