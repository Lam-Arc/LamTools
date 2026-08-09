from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import sqlite3
import sys
import time
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from lamtools_core.app.base_agent import assemble_core_agent_plugins, CoreBaseAgentConfig, CoreBaseAgentKit
from lamtools_core.app.base_agent import core_events_to_run_items
from lamtools_core.app.cli_live import (
    CliLiveFormatter,
    OutputChunk,
    approval_decision_from_reply,
    execute_compaction_command_live,
    format_compaction_result,
    watch_live_events,
)
from lamtools_core.app.core_db import (
    list_core_sessions,
    open_core_app_db,
    persist_core_run_items,
    show_core_session,
)
from lamtools_core.app.live_client import CoreAppServerClient
from lamtools_core.event import CollectingEventSink, RunItemEvent
from lamtools_core.kernel import CoreLoopKernel, LoopPolicy
from lamtools_core.llm import (
    LLMRequest,
    LLMResponse,
    LLMStreamEvent,
    LLMToolCall,
    normalize_usage,
)
from lamtools_core.llm.shallow_thinking import ShallowThinkingClient
from lamtools_core.llm.profiles import (
    build_profiled_openai_request,
    load_adapter_profiles_from_dirs,
    normalize_response_with_profile,
    normalize_stream_chunk_with_profile,
    resolve_adapter_profile_from_profiles,
)
from lamtools_core.llm.model_capabilities import resolve_capability
from lamtools_core.config.migrate_models import migrate_models_from_db
from lamtools_core.config.model_store import ModelConfig, ModelStore
from lamtools_core.config.root import ensure_projects_root
from lamtools_core.runtime import RuntimeTurnInput
from lamtools_core.tool.default_toolbox import ApprovalPolicy, build_core_toolbox

SQLITE_CONFIG_READ_TIMEOUT_SECONDS = 0.2
SQLITE_CONFIG_LOCK_RETRY_DELAYS = (0.05, 0.15)

# Process-level model-store context. The HTTP app (create_core_agent_http_app)
# configures the shared work_root so load_llm_config can resolve project-scoped
# model jsonc files. Falls back to global-only when unset.
_default_model_store: ModelStore | None = None
_model_store_work_root: str | None = None
_model_migration_done: set[Path] = set()


def configure_model_store_context(*, work_root: str | None, store: ModelStore | None = None) -> None:
    """Register the shared ModelStore + work_root for the running process."""
    global _default_model_store, _model_store_work_root
    _model_store_work_root = work_root
    if store is not None:
        _default_model_store = store


def _get_model_store() -> ModelStore:
    return _default_model_store if _default_model_store is not None else ModelStore()


@dataclass(frozen=True)
class CoreCliRunOptions:
    message: str
    model_id: str = ""
    work_root: Path | str = "."
    run_dir: Path | str | None = None
    core_db: Path | str | None = None
    thread_id: str = ""
    config_db: Path | str | None = None
    adapter_dirs: tuple[Path | str, ...] = ()
    plugin_roots: tuple[Path | str, ...] = ()
    thinking_enabled: bool = True
    thinking_budget: int = 10000
    shallow_thinking_enabled: bool = False
    max_tokens: int | None = None
    compact_trigger_tokens: int | None = None
    compact_limit_tokens: int | None = None
    temperature: float = 0.2
    approval_policy: ApprovalPolicy = "require"
    raw: bool = False
    verbose: bool = False
    # --- Workflow mode (mirrors the frontend "工作流模式" path) ---
    # When set, the build tools (workflow_graph/add_node/connect/...) become
    # available and loadtools "workflow" whitelist is applied — identical to the
    # HTTP app's active_mode="workflow". An operation_catalog may be supplied
    # directly; otherwise one is assembled from workflow_store + the runner.
    active_mode: str = ""
    instructions: str = ""
    workflow_store: Any = None
    operation_catalog: Any = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "work_root", Path(self.work_root))
        if self.run_dir is not None:
            object.__setattr__(self, "run_dir", Path(self.run_dir))
        if self.core_db is not None:
            object.__setattr__(self, "core_db", Path(self.core_db))
        if self.config_db is not None:
            object.__setattr__(self, "config_db", Path(self.config_db))
        object.__setattr__(self, "adapter_dirs", tuple(Path(item) for item in self.adapter_dirs))
        object.__setattr__(self, "plugin_roots", tuple(Path(item) for item in self.plugin_roots))
        if self.compact_trigger_tokens is not None and self.compact_trigger_tokens <= 0:
            raise ValueError("compact trigger tokens must be positive")
        if self.compact_limit_tokens is not None and self.compact_limit_tokens <= 0:
            raise ValueError("compact limit tokens must be positive")
        if (
            self.compact_trigger_tokens is not None
            and self.compact_limit_tokens is not None
            and self.compact_limit_tokens > self.compact_trigger_tokens
        ):
            raise ValueError("compact limit tokens cannot exceed compact trigger tokens")


@dataclass(frozen=True)
class LLMConfig:
    provider_name: str
    provider_api_type: str
    base_url: str
    api_key: str
    model_record_id: str
    model_id: str
    display_name: str
    context_window: int = 0
    max_output_tokens: int = 4096
    temperature: float = 0.2
    thinking_supported: bool = False
    thinking_budget: int = 10000
    capability: str = ""  # "text" | "multimodal" | "" (resolved at request time)
    provider_extra: dict[str, Any] = field(default_factory=dict)
    model_extra: dict[str, Any] = field(default_factory=dict)


class CoreHttpLLMClient:
    def __init__(
        self,
        *,
        config: LLMConfig,
        adapter_profile: dict[str, Any],
        thinking_enabled: bool,
        thinking_budget: int,
        reasoning_effort: str = "",
        max_tokens: int,
        temperature: float,
    ) -> None:
        self.config = config
        self.adapter_profile = adapter_profile
        self.thinking_enabled = thinking_enabled
        self.thinking_budget = thinking_budget
        self.reasoning_effort = reasoning_effort
        self.max_tokens = max_tokens
        self.temperature = temperature

    async def complete(self, request: LLMRequest) -> LLMResponse:
        assembled = build_profiled_openai_request(
            self._request_with_defaults(request),
            self.adapter_profile,
            thinking_enabled=self.thinking_enabled,
            thinking_budget=self.thinking_budget,
            reasoning_effort=self.reasoning_effort,
            capability=self.config.capability,
        )
        async with httpx.AsyncClient(timeout=httpx.Timeout(360.0, connect=30.0)) as client:
            response = await client.post(
                f"{self.config.base_url.rstrip('/')}{assembled['endpoint']}",
                json=assembled["payload"],
                headers=self._headers(),
            )
        if response.status_code >= 400:
            raise RuntimeError(f"LLM API error {response.status_code}: {response.text[:300]}")
        normalized = normalize_response_with_profile(response.json(), self.adapter_profile)
        return LLMResponse(
            content=str(normalized.get("content") or ""),
            thinking=str(normalized.get("thinking") or ""),
            tool_calls=_llm_tool_calls_from_raw(normalized.get("tool_calls")),
            usage=normalize_usage(normalized.get("usage")),
            finish_reason=str(normalized.get("finish_reason") or "stop"),
            raw=None,
        )

    async def stream(self, request: LLMRequest):
        assembled = build_profiled_openai_request(
            self._request_with_defaults(request),
            self.adapter_profile,
            stream=True,
            thinking_enabled=self.thinking_enabled,
            thinking_budget=self.thinking_budget,
            reasoning_effort=self.reasoning_effort,
            capability=self.config.capability,
        )
        async with httpx.AsyncClient(timeout=httpx.Timeout(360.0, connect=30.0)) as client:
            async with client.stream(
                "POST",
                f"{self.config.base_url.rstrip('/')}{assembled['endpoint']}",
                json=assembled["payload"],
                headers=self._headers(),
            ) as response:
                if response.status_code >= 400:
                    text = await response.aread()
                    raise RuntimeError(
                        f"LLM API error {response.status_code}: {text.decode('utf-8', errors='replace')[:300]}"
                    )
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data == "[DONE]":
                        yield LLMStreamEvent(kind="done", metadata={"finish_reason": "stop"})
                        return
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    event = normalize_stream_chunk_with_profile(chunk, self.adapter_profile)
                    if event is not None:
                        yield event

    def _request_with_defaults(self, request: LLMRequest) -> LLMRequest:
        return LLMRequest(
            messages=request.messages,
            model=request.model or self.config.model_id,
            temperature=request.temperature if request.temperature is not None else self.temperature,
            max_tokens=request.max_tokens if request.max_tokens is not None else self.max_tokens,
            top_p=request.top_p,
            tools=request.tools,
            tool_choice=request.tool_choice,
            parallel_tool_calls=request.parallel_tool_calls,
            response_format=request.response_format,
            timeout=request.timeout,
            metadata=dict(request.metadata),
        )

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }


async def run_core_cli_task(
    options: CoreCliRunOptions,
    *,
    llm_client: Any | None = None,
) -> dict[str, Any]:
    run_dir = Path(options.run_dir) if options.run_dir is not None else _default_run_dir()
    work_root = Path(options.work_root)
    core_db_path = _resolve_core_db(options.core_db)
    thread_id = _resolve_thread_id(options.thread_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    work_root.mkdir(parents=True, exist_ok=True)

    resolved_model_id = options.model_id
    context_window_tokens: int | None = None
    model_context: dict[str, Any] = {"model_id": resolved_model_id}
    if llm_client is None:
        config_db = _resolve_config_db(options.config_db)
        config = load_llm_config(config_db, model_ref=options.model_id)
        profile = _resolve_adapter_profile(config, options.adapter_dirs)
        resolved_model_id = config.model_id
        context_window_tokens = config.context_window or None
        model_context = {
            "model_record_id": config.model_record_id,
            "model_id": config.model_id,
            "display_name": config.display_name,
            "provider": config.provider_name,
            "thinking_enabled": options.thinking_enabled,
            "thinking_budget": options.thinking_budget or config.thinking_budget,
            "shallow_thinking_enabled": options.shallow_thinking_enabled,
        }
        llm_client = CoreHttpLLMClient(
            config=config,
            adapter_profile=profile,
            thinking_enabled=options.thinking_enabled,
            thinking_budget=options.thinking_budget or config.thinking_budget,
            max_tokens=options.max_tokens or config.max_output_tokens,
            temperature=options.temperature if options.temperature is not None else config.temperature,
        )
    if options.shallow_thinking_enabled:
        llm_client = ShallowThinkingClient(llm_client)

    sink = CollectingEventSink()
    plugin_assembly = assemble_core_agent_plugins(
        data_dir=run_dir,
        work_root=work_root,
        plugin_roots=options.plugin_roots or None,
    )
    from lamtools_core.mcp import MCPToolRegistry

    mcp_registry = MCPToolRegistry(work_root, config_files=plugin_assembly.get("mcp_files") or [])
    await mcp_registry.load()
    mcp_tool_specs = mcp_registry.tool_specs()
    if plugin_assembly["hook_engine"] is not None:
        plugin_assembly["hook_engine"].set_mcp_caller(mcp_registry if mcp_tool_specs else None)
    from lamtools_core.tool.sub_agent_runner import KernelSubAgentRunner

    core_db = await open_core_app_db(core_db_path)
    await core_db.project_store.ensure_session(
        work_root,
        thread_id,
        title=options.message,
    )
    run_id = uuid.uuid4().hex[:12]
    turn_id = f"{thread_id}:turn:{run_id}"
    await persist_core_run_items(
        core_db,
        [
            RunItemEvent(
                kind="message",
                thread_id=thread_id,
                event_id=f"{run_id}:user",
                run_id=run_id,
                turn_id=turn_id,
                item_id=f"{turn_id}:user",
                status="completed",
                payload={
                    "type": "userMessage",
                    "status": "completed",
                    "content": [{"type": "text", "text": options.message}],
                },
                source="core.cli",
            )
        ],
    )
    core_instructions = "You are LamTools Core Agent, a standalone general-purpose agent runtime."
    if options.instructions:
        core_instructions = options.instructions
    context_window_tokens = int(getattr(llm_client, "context_window", 0) or 0) or context_window_tokens

    sub_agent_runner = KernelSubAgentRunner(
        work_root=work_root,
        llm_client=llm_client,
        model_id=resolved_model_id,
        instructions=core_instructions,
        temperature=options.temperature,
        max_tokens=options.max_tokens,
        thinking_enabled=options.thinking_enabled,
        thinking_budget=options.thinking_budget,
        approval_policy=options.approval_policy,
        loaded_skill_roots=set(plugin_assembly["skill_roots"]),
        mcp_caller=mcp_registry if mcp_tool_specs else None,
        mcp_tool_specs=mcp_tool_specs,
        context_window_tokens=context_window_tokens,
        state_store=core_db.runtime_state_store,
        session_prefix=thread_id,
        parent_event_sink=sink,
    )

    # --- Workflow mode assembly (mirrors http_agent_app's active_mode="workflow") ---
    # When a workflow_store is supplied, register the workflow.* operations and
    # expose the 5 graph-editing build tools so the agent can build a workflow
    # from natural language — identical to the frontend "工作流模式" path.
    workflow_store = options.workflow_store
    operation_catalog = options.operation_catalog
    load_tools_obj = None
    active_mode = options.active_mode or None
    if workflow_store is not None:
        from lamtools_core.tool.loadtools import default_load_tools

        from lamtools_core.runtime.workflow import WorkflowManager, WorkflowRunner
        from lamtools_core.app.workflow_operations import register_workflow_operations
        from lamtools_core.app.operation_catalog import OperationCatalog

        load_tools_obj = default_load_tools()
        if operation_catalog is None:
            operation_catalog = OperationCatalog()
        workflow_manager = WorkflowManager(workflow_store)
        if not operation_catalog.has("workflow.run"):
            workflow_runner = WorkflowRunner(
                llm_client=llm_client,
                sub_agent_runner=sub_agent_runner,
                workflow_store=workflow_store,
            )
            register_workflow_operations(
                operation_catalog,
                workflow_manager=workflow_manager,
                runner=workflow_runner,
                runtime_task_registry=None,
                list_tool_specs=lambda: [],
            )
        if active_mode is None:
            active_mode = "workflow"

    async def execute_operation(name: str, payload: dict[str, Any], metadata: dict[str, Any]) -> Any:
        if operation_catalog is None:
            raise RuntimeError("operation catalog is not configured")
        return await operation_catalog.execute(name, payload, metadata=metadata)

    workflow_provider = None
    if workflow_store is not None and operation_catalog is not None:
        from lamtools_core.tool.workflow_tools import workflow_tool_provider

        workflow_provider = workflow_tool_provider(workflow_store, execute_operation, work_root=work_root)

    toolbox = build_core_toolbox(
        work_root=work_root,
        approval_policy=options.approval_policy,
        loaded_skill_roots=set(plugin_assembly["skill_roots"]),
        mcp_caller=mcp_registry if mcp_tool_specs else None,
        mcp_tool_specs=mcp_tool_specs,
        sub_agent_runner=sub_agent_runner,
        operation_executor=execute_operation if operation_catalog is not None else None,
        workflow_build=workflow_store is not None,
        workflow_tool_provider=workflow_provider,
        load_tools=load_tools_obj,
    )
    kit = CoreBaseAgentKit(
        work_root=work_root,
        config=CoreBaseAgentConfig(
            model_id=resolved_model_id,
            instructions=core_instructions,
            temperature=options.temperature,
            max_tokens=options.max_tokens,
            thinking_enabled=options.thinking_enabled,
            thinking_budget=options.thinking_budget,
            approval_policy=options.approval_policy,
            active_mode=active_mode,
        ),
        toolbox=toolbox,
    )
    try:
        kernel = CoreLoopKernel(
            kit=kit,
            llm_client=llm_client,
            state_store=core_db.runtime_state_store,
            event_sink=sink,
            policy=LoopPolicy(
                model_timeout_seconds=360,
                persist_steps=True,
                context_window_tokens=context_window_tokens,
                compact_trigger_tokens=options.compact_trigger_tokens,
                compact_limit_tokens=options.compact_limit_tokens,
                parallel_tool_names=("sub_agent",),
            ),
            hook_engine=plugin_assembly["hook_engine"],
        )
        result = await kernel.run(
            RuntimeTurnInput(
                user_message=options.message,
                run_id=run_id,
                turn_id=turn_id,
                metadata={
                    "session_id": thread_id,
                    "model_id": resolved_model_id,
                    "thinking_enabled": options.thinking_enabled,
                    "thinking_budget": options.thinking_budget,
                    "shallow_thinking_enabled": options.shallow_thinking_enabled,
                    **(
                        {"context_window_tokens": context_window_tokens}
                        if context_window_tokens is not None
                        else {}
                    ),
                },
            )
        )
        await persist_core_run_items(
            core_db,
            core_events_to_run_items(sink.events, thread_id=result.session_id),
        )
    finally:
        await mcp_registry.close()
        await core_db.close()

    summary = _build_summary(
        result=result,
        events=sink.events,
        model_context=model_context,
        run_dir=run_dir,
    )
    events_path = run_dir / "events-redacted.json"
    summary_path = run_dir / "summary.json"
    events_path.write_text(
        json.dumps([_redact_event(event) for event in sink.events], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    summary["artifacts"] = {
        "run_dir": str(run_dir),
        "core_db": str(core_db_path),
        "summary_json": str(summary_path),
        "events_redacted_json": str(events_path),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def load_llm_config(config_db: Path, *, model_ref: str = "") -> LLMConfig:
    if not config_db.exists():
        raise FileNotFoundError(f"LLM config database not found: {config_db}")

    # Lazy one-time migration: if the ModelStore has no files yet but the DB
    # llm_models table has rows, export them to jsonc so the file path wins.
    _maybe_migrate_from_db(config_db)

    # Try the file-backed (jsonc) path first. Falls back to the legacy DB path
    # when no jsonc model is resolvable, preserving backward compatibility.
    file_config = _load_llm_config_from_files(config_db, model_ref=model_ref)
    if file_config is not None:
        return file_config

    locked_error: sqlite3.OperationalError | None = None
    for attempt in range(len(SQLITE_CONFIG_LOCK_RETRY_DELAYS) + 1):
        try:
            return _load_llm_config_from_connection(
                _connect_config_db(config_db, nolock=False),
                model_ref=model_ref,
            )
        except sqlite3.OperationalError as exc:
            if not _is_sqlite_locked_message(exc):
                raise
            locked_error = exc
            if attempt < len(SQLITE_CONFIG_LOCK_RETRY_DELAYS):
                time.sleep(SQLITE_CONFIG_LOCK_RETRY_DELAYS[attempt])
                continue
            break

    try:
        return _load_llm_config_from_connection(
            _connect_config_db(config_db, nolock=True),
            model_ref=model_ref,
        )
    except sqlite3.OperationalError:
        if locked_error is not None:
            raise locked_error
        raise


def _maybe_migrate_from_db(config_db: Path) -> None:
    """Export DB models to jsonc once per process when the ModelStore is empty."""
    global _model_migration_done
    config_db = config_db.resolve()
    if config_db in _model_migration_done:
        return
    _model_migration_done.add(config_db)
    try:
        store = _get_model_store()
        # Only migrate when nothing is loaded yet (avoid clobbering user files).
        if store.list_sync(work_root=_model_store_work_root):
            return
        migrate_models_from_db(config_db, model_store=store, work_root=_model_store_work_root, scope="global")
    except Exception:
        # Migration is best-effort; never block config loading on it.
        import logging

        logging.getLogger(__name__).debug("model migration skipped", exc_info=True)


def _load_llm_config_from_files(config_db: Path, *, model_ref: str) -> LLMConfig | None:
    """Resolve a model from jsonc files + provider connection from the DB.

    Returns ``None`` when the model_ref cannot be resolved from files (caller
    falls back to the legacy DB-join path).
    """
    store = _get_model_store()
    ref = model_ref.strip()
    if not ref:
        ref = store.default_model_id_sync(work_root=_model_store_work_root)
    if not ref:
        return None
    model = store.get_sync(ref, work_root=_model_store_work_root)
    if model is None:
        return None
    # Resolve the provider connection from the DB by name or provider_id.
    con = _connect_config_db(config_db, nolock=True)
    try:
        provider_row = _read_provider_row(con, model)
    finally:
        con.close()
    if provider_row is None:
        return None
    capability = model.resolved_capability
    return LLMConfig(
        provider_name=str(provider_row.get("name") or model.provider or ""),
        provider_api_type=str(provider_row.get("api_type") or "openai"),
        base_url=str(provider_row.get("base_url") or "").rstrip("/"),
        api_key=str(provider_row.get("api_key") or ""),
        model_record_id=model.model_id,
        model_id=model.model_id,
        display_name=model.display_name or model.model_id,
        context_window=model.context_window,
        max_output_tokens=model.max_output_tokens,
        temperature=model.temperature,
        thinking_supported=model.thinking_supported,
        thinking_budget=model.thinking_budget,
        capability=capability,
        provider_extra=_json_dict(provider_row.get("extra")),
        model_extra=model.to_extra(),
    )


def _read_provider_row(con: sqlite3.Connection, model: ModelConfig) -> dict[str, Any] | None:
    """Look up a provider by the model's provider_id then by name."""
    try:
        if model.provider_id:
            row = con.execute(
                "select name, api_type, base_url, api_key, extra from llm_providers where id=? limit 1",
                (model.provider_id,),
            ).fetchone()
            if row is not None:
                return dict(row)
        if model.provider:
            row = con.execute(
                "select name, api_type, base_url, api_key, extra from llm_providers where name=? limit 1",
                (model.provider,),
            ).fetchone()
            if row is not None:
                return dict(row)
        # Last resort: the single configured provider (works for single-provider setups).
        row = con.execute(
            "select name, api_type, base_url, api_key, extra from llm_providers order by is_default desc, created_at asc limit 1"
        ).fetchone()
        return dict(row) if row is not None else None
    except sqlite3.OperationalError:
        return None


def list_llm_model_configs(config_db: Path) -> list[dict[str, Any]]:
    # Prefer file-backed (jsonc) model definitions when available; fall back to
    # the legacy DB list when no jsonc models are configured yet.
    store = _get_model_store()
    models = store.list_sync(work_root=_model_store_work_root)
    if models:
        # Resolve each model's provider_id (DB uuid) from the DB by matching
        # the provider name recorded in the jsonc file. jsonc model files store
        # ``provider`` (a name) rather than ``provider_id`` (a DB id), so we
        # build a name → (id, api_type) map here. Also resolves the per-model
        # api_type instead of falling back to the first provider.
        provider_map: dict[str, tuple[str, str]] = {}
        con = None
        try:
            con = _connect_config_db(config_db, nolock=True)
            prow_rows = con.execute(
                "select id,name,api_type from llm_providers order by created_at asc"
            ).fetchall()
            for prow in prow_rows:
                name = str(prow["name"] or "").strip()
                if name:
                    provider_map[name] = (str(prow["id"] or ""), str(prow["api_type"] or "openai"))
        except (sqlite3.OperationalError, FileNotFoundError):
            pass
        finally:
            if con is not None:
                con.close()
        return [
            {
                "id": m.model_id,
                "provider_id": (
                    m.provider_id
                    or provider_map.get(m.provider, ("", ""))[0]
                ),
                "provider_name": m.provider,
                "provider_api_type": provider_map.get(m.provider, ("", "openai"))[1],
                "model_id": m.model_id,
                "display_name": m.display_name,
                "context_window": m.context_window,
                "max_output_tokens": m.max_output_tokens,
                "thinking_supported": m.thinking_supported,
                "thinking_budget": m.thinking_budget,
                "temperature": m.temperature,
                "capability": m.resolved_capability,
                "notes": m.notes,
                "is_default": m.is_default,
                "adapter_profile_id": m.adapter_profile_id,
            }
            for m in models
        ]

    if not config_db.exists():
        raise FileNotFoundError(f"LLM config database not found: {config_db}")

    locked_error: sqlite3.OperationalError | None = None
    for attempt in range(len(SQLITE_CONFIG_LOCK_RETRY_DELAYS) + 1):
        try:
            return _list_llm_model_configs_from_connection(_connect_config_db(config_db, nolock=False))
        except sqlite3.OperationalError as exc:
            if not _is_sqlite_locked_message(exc):
                raise
            locked_error = exc
            if attempt < len(SQLITE_CONFIG_LOCK_RETRY_DELAYS):
                time.sleep(SQLITE_CONFIG_LOCK_RETRY_DELAYS[attempt])
                continue
            break

    try:
        return _list_llm_model_configs_from_connection(_connect_config_db(config_db, nolock=True))
    except sqlite3.OperationalError:
        if locked_error is not None:
            raise locked_error
        raise


def _connect_config_db(config_db: Path, *, nolock: bool) -> sqlite3.Connection:
    query = "mode=ro&nolock=1" if nolock else "mode=ro"
    raw_path = str(config_db.resolve()).replace("\\", "/")
    uri = f"file:{quote(raw_path, safe=':/')}?{query}"
    con = sqlite3.connect(uri, timeout=SQLITE_CONFIG_READ_TIMEOUT_SECONDS, uri=True)
    con.row_factory = sqlite3.Row
    return con


def _load_llm_config_from_connection(con: sqlite3.Connection, *, model_ref: str = "") -> LLMConfig:
    try:
        resolved_ref = model_ref.strip() or _model_ref_from_routing(con)
        if not resolved_ref:
            raise ValueError("model id is required when no routing setting is available")
        row = con.execute(
            """
            select m.id,m.provider_id,m.model_id,m.display_name,m.context_window,m.max_output_tokens,
                   m.thinking_supported,m.thinking_budget,m.temperature,m.extra as model_extra,
                   p.name as provider_name,p.api_type as provider_api_type,p.base_url,p.api_key,
                   p.extra as provider_extra
            from llm_models m join llm_providers p on p.id=m.provider_id
            where m.id=? or m.model_id=? or m.display_name=?
            order by m.created_at asc
            limit 1
            """,
            (resolved_ref, resolved_ref, resolved_ref),
        ).fetchone()
    finally:
        con.close()
    if row is None:
        raise ValueError(f"model not found: {model_ref}")
    data = dict(row)
    model_id = str(data.get("model_id") or "")
    model_extra = _json_dict(data.get("model_extra"))
    # Capability: prefer the DB extra field, else resolve from the model's
    # jsonc definition (jsonc is the single source of truth).
    capability = ""
    if isinstance(model_extra.get("capability"), str):
        capability = str(model_extra["capability"]).strip().lower()
    if capability not in ("text", "multimodal"):
        from lamtools_core.config.model_store import resolve_model_capability

        capability = resolve_model_capability(model_id)
    return LLMConfig(
        provider_name=str(data.get("provider_name") or ""),
        provider_api_type=str(data.get("provider_api_type") or "openai"),
        base_url=str(data.get("base_url") or "").rstrip("/"),
        api_key=str(data.get("api_key") or ""),
        model_record_id=str(data.get("id") or ""),
        model_id=model_id,
        display_name=str(data.get("display_name") or ""),
        context_window=int(data.get("context_window") or 0),
        max_output_tokens=int(data.get("max_output_tokens") or 4096),
        temperature=float(data.get("temperature") or 0.2),
        thinking_supported=bool(data.get("thinking_supported")),
        thinking_budget=int(data.get("thinking_budget") or 10000),
        capability=capability,
        provider_extra=_json_dict(data.get("provider_extra")),
        model_extra=model_extra,
    )


def _list_llm_model_configs_from_connection(con: sqlite3.Connection) -> list[dict[str, Any]]:
    try:
        rows = con.execute(
            """
            select m.id,m.provider_id,m.model_id,m.display_name,m.context_window,m.max_output_tokens,
                   m.thinking_supported,m.thinking_budget,m.temperature,
                   p.name as provider_name,p.api_type as provider_api_type
            from llm_models m join llm_providers p on p.id=m.provider_id
            order by m.created_at asc
            """
        ).fetchall()
    finally:
        con.close()
    return [
        {
            "id": str(row["id"] or ""),
            "provider_id": str(row["provider_id"] or ""),
            "provider_name": str(row["provider_name"] or ""),
            "provider_api_type": str(row["provider_api_type"] or ""),
            "model_id": str(row["model_id"] or ""),
            "display_name": str(row["display_name"] or ""),
            "context_window": int(row["context_window"] or 0),
            "max_output_tokens": int(row["max_output_tokens"] or 0),
            "thinking_supported": bool(row["thinking_supported"]),
            "thinking_budget": int(row["thinking_budget"] or 0),
            "temperature": float(row["temperature"] or 0.0),
        }
        for row in rows
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="core", description="LamTools Core Agent CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="Run the Core Agent HTTP app")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=5172)
    serve.add_argument("--model-id", default="")
    serve.add_argument("--config-db", default="")
    serve.add_argument("--core-db", default="")
    serve.add_argument("--data-dir", default="")
    serve.add_argument("--work-root", "--project", dest="work_root", default="")
    serve.add_argument("--frontend-dir", default="", help="Path to built frontend SPA directory (desktop/packaged mode)")
    serve.add_argument("--thinking", choices=("enabled", "disabled"), default="enabled")
    serve.add_argument("--thinking-budget", type=int, default=10000)
    serve.add_argument("--max-tokens", type=int, default=None)
    serve.add_argument("--temperature", type=float, default=0.2)
    serve.add_argument("--raw", action="store_true")
    serve.add_argument("--reload", action="store_true", help="Enable auto-reload on code changes")
    serve.set_defaults(func=cmd_serve)

    setup = sub.add_parser("setup", help="Initialize the lam_projects directory for default project workspaces")
    setup.set_defaults(func=cmd_setup)

    migrate = sub.add_parser(
        "migrate-projects",
        help="Migrate existing project workspaces into lam_projects/",
    )
    migrate.add_argument("--core-db", default="", help="Core-owned SQLite runtime database")
    migrate.add_argument("--apply", action="store_true", help="Apply the migration (default is a dry-run preview)")
    migrate.set_defaults(func=cmd_migrate_projects)

    run = sub.add_parser("run", help="Start a Core Agent task")
    run.add_argument("message", nargs="+")
    run.add_argument("--model-id", default="", help="Model record id, provider model id, or display name")
    run.add_argument("--thread-id", default="", help="Stable Core thread/session id")
    run.add_argument("--goal-id", default="", help="Durable Goal ID to verify on completion")
    run.add_argument("--work-root", "--project", dest="work_root", default="")
    run.add_argument("--config-db", default="", help="Path to LLM config DB for resolving model context window")
    run.add_argument("--thinking-budget", type=int, default=10000)
    run.add_argument("--no-thinking", action="store_true")
    run.add_argument("--shallow-thinking", action="store_true", help="Require a prompt-based shallow thinking block")
    run.add_argument("--auto-approve", action="store_true", help="Run approval-gated Core tools without prompting")
    run.add_argument("--max-tokens", type=int, default=None)
    run.add_argument("--compact-trigger-tokens", type=int, default=None, help="Session-only automatic compaction trigger")
    run.add_argument("--compact-limit-tokens", type=int, default=None, help="Session-only post-compaction upper limit")
    run.add_argument("--temperature", type=float, default=0.2)
    run.add_argument("--raw", action="store_true")
    run.add_argument("--verbose", action="store_true")
    _add_live_connection_arguments(run)
    run.add_argument("--heartbeat-interval", type=int, default=30)
    run.add_argument("--event-timeout", type=_positive_timeout_or_none, default=None)
    run.add_argument("--max-reconnects", type=int, default=3)
    run.add_argument("--interactive-decisions", action="store_true")
    run.add_argument("--approval-decision", choices=("approve_once", "deny", "other_guidance"))
    run.set_defaults(func=cmd_run)

    run_local = sub.add_parser("run-local", help="Run a Core Agent task directly without a server")
    run_local.add_argument("message", nargs="+")
    run_local.add_argument("--model-id", default="", help="Model record id, provider model id, or display name")
    run_local.add_argument("--thread-id", default="", help="Stable Core thread/session id")
    run_local.add_argument("--work-root", "--project", dest="work_root", default="")
    run_local.add_argument("--run-dir", default="", help="Output directory for run artifacts (summary.json etc.)")
    run_local.add_argument("--core-db", default="", help="Path to Core agent database")
    run_local.add_argument("--config-db", default="", help="Path to LLM config database")
    run_local.add_argument("--thinking-budget", type=int, default=10000)
    run_local.add_argument("--no-thinking", action="store_true")
    run_local.add_argument("--shallow-thinking", action="store_true", help="Require a prompt-based shallow thinking block")
    run_local.add_argument("--auto-approve", action="store_true", help="Run approval-gated tools without prompting")
    run_local.add_argument("--max-tokens", type=int, default=None)
    run_local.add_argument("--compact-trigger-tokens", type=int, default=None, help="Session-only automatic compaction trigger")
    run_local.add_argument("--compact-limit-tokens", type=int, default=None, help="Session-only post-compaction upper limit")
    run_local.add_argument("--temperature", type=float, default=0.2)
    run_local.add_argument("--raw", action="store_true")
    run_local.add_argument("--verbose", action="store_true")
    run_local.set_defaults(func=cmd_run_local)

    watch = sub.add_parser("watch", help="Watch a Core app-server thread")
    watch.add_argument("thread_id")
    watch.add_argument("--base-url", default=os.environ.get("LAMTOOLS_CORE_API_URL", "http://127.0.0.1:5172"))
    watch.add_argument("--ws-path", default=os.environ.get("LAMTOOLS_CORE_WS_PATH", "/api/core/app-server"))
    watch.add_argument("--token", default=os.environ.get("LAMTOOLS_CORE_TOKEN", ""))
    watch.add_argument("--raw", action="store_true")
    watch.add_argument("--verbose", action="store_true")
    watch.add_argument("--heartbeat-interval", type=int, default=30)
    watch.add_argument("--event-timeout", type=_positive_timeout_or_none, default=None)
    watch.add_argument("--max-reconnects", type=int, default=3)
    watch.add_argument("--interactive-decisions", action="store_true")
    watch.add_argument("--approval-decision", choices=("approve_once", "deny", "other_guidance"))
    watch.set_defaults(func=cmd_watch)

    start = sub.add_parser("start", help="Start a live Core Agent turn")
    start.add_argument("thread_id")
    start.add_argument("message", nargs="+")
    start.add_argument("--goal-id", default="", help="Durable Goal ID")
    _add_live_connection_arguments(start)
    start.add_argument("--work-root", "--project", dest="work_root", default="")
    start.add_argument("--model-id", default="")
    start.add_argument("--thinking", choices=("enabled", "disabled"), default="enabled")
    start.add_argument("--thinking-budget", type=int, default=10000)
    start.add_argument("--shallow", action="store_true")
    start.add_argument("--approval-policy", choices=("require", "auto_approve"), default=None)
    start.add_argument("--client-message-id", default="")
    start.add_argument("--watch", action="store_true")
    start.add_argument("--raw", action="store_true")
    start.add_argument("--verbose", action="store_true")
    start.add_argument("--heartbeat-interval", type=int, default=30)
    start.add_argument("--event-timeout", type=_positive_timeout_or_none, default=None)
    start.add_argument("--max-reconnects", type=int, default=3)
    start.add_argument("--interactive-decisions", action="store_true")
    start.add_argument("--approval-decision", choices=("approve_once", "deny", "other_guidance"))
    start.set_defaults(func=cmd_start)

    cancel = sub.add_parser("cancel", help="Cancel a live Core Agent turn")
    cancel.add_argument("thread_id")
    cancel.add_argument("--turn-id", default="")
    _add_live_connection_arguments(cancel)
    cancel.add_argument("--raw", action="store_true")
    cancel.set_defaults(func=cmd_cancel)

    steer = sub.add_parser("steer", help="Steer a live Core Agent turn")
    steer.add_argument("thread_id")
    steer.add_argument("turn_id")
    steer.add_argument("message", nargs="+")
    _add_live_connection_arguments(steer)
    steer.add_argument("--raw", action="store_true")
    steer.set_defaults(func=cmd_steer)

    queue = sub.add_parser("queue", help="Manage live Core Agent queued input")
    queue_sub = queue.add_subparsers(dest="queue_command", required=True)
    queue_create = queue_sub.add_parser("create", help="Queue input for the next turn")
    queue_create.add_argument("thread_id")
    queue_create.add_argument("message", nargs="+")
    _add_live_connection_arguments(queue_create)
    queue_create.add_argument("--raw", action="store_true")
    queue_create.set_defaults(func=cmd_queue_create)
    queue_update = queue_sub.add_parser("update", help="Update queued input")
    queue_update.add_argument("thread_id")
    queue_update.add_argument("queue_item_id")
    queue_update.add_argument("message", nargs="+")
    _add_live_connection_arguments(queue_update)
    queue_update.add_argument("--raw", action="store_true")
    queue_update.set_defaults(func=cmd_queue_update)
    queue_delete = queue_sub.add_parser("delete", help="Delete queued input")
    queue_delete.add_argument("thread_id")
    queue_delete.add_argument("queue_item_id")
    _add_live_connection_arguments(queue_delete)
    queue_delete.add_argument("--raw", action="store_true")
    queue_delete.set_defaults(func=cmd_queue_delete)
    queue_guide = queue_sub.add_parser("guide", help="Use queued input to steer the active turn")
    queue_guide.add_argument("thread_id")
    queue_guide.add_argument("turn_id")
    queue_guide.add_argument("queue_item_id")
    queue_guide.add_argument("message", nargs="*")
    _add_live_connection_arguments(queue_guide)
    queue_guide.add_argument("--raw", action="store_true")
    queue_guide.set_defaults(func=cmd_queue_guide)

    approval = sub.add_parser("approval", help="Respond to a live Core Agent approval")
    approval_sub = approval.add_subparsers(dest="approval_command", required=True)
    approval_respond = approval_sub.add_parser("respond", help="Respond to a pending Core approval")
    approval_respond.add_argument("thread_id")
    approval_respond.add_argument("action", choices=("approve", "deny", "guide"))
    approval_respond.add_argument("response", nargs="*")
    _add_live_connection_arguments(approval_respond)
    approval_respond.add_argument("--raw", action="store_true")
    approval_respond.set_defaults(func=cmd_approval_respond)

    command = sub.add_parser("command", help="Use the Core command system")
    command_sub = command.add_subparsers(dest="command_action", required=True)
    command_catalog = command_sub.add_parser("catalog", help="List commands and skills")
    command_catalog.add_argument("--work-root", default="")
    _add_live_connection_arguments(command_catalog)
    command_catalog.add_argument("--raw", action="store_true")
    command_catalog.set_defaults(func=cmd_command_catalog)
    command_execute = command_sub.add_parser("execute", help="Execute a Core command action")
    command_execute.add_argument("thread_id")
    command_execute.add_argument("name")
    command_execute.add_argument("--work-root", default="")
    _add_live_connection_arguments(command_execute)
    command_execute.add_argument("--raw", action="store_true")
    command_execute.set_defaults(func=cmd_command_execute)

    attachment = sub.add_parser("attachment", help="Use Core attachment upload and storage")
    attachment_sub = attachment.add_subparsers(dest="attachment_action", required=True)
    attachment_upload = attachment_sub.add_parser("upload", help="Upload an attachment to a Core session")
    attachment_upload.add_argument("thread_id")
    attachment_upload.add_argument("file")
    _add_live_connection_arguments(attachment_upload)
    attachment_upload.add_argument("--raw", action="store_true")
    attachment_upload.set_defaults(func=cmd_attachment_upload)

    imagegen = sub.add_parser("imagegen", help="Manage the generate_image tool configuration (设置 → 生图)")
    imagegen_sub = imagegen.add_subparsers(dest="imagegen_command", required=True)
    imagegen_show = imagegen_sub.add_parser("show", help="Show the current image generation configuration")
    imagegen_show.add_argument("--config-db", default="", help="LLM config database (default: data/lamtools.db)")
    imagegen_show.set_defaults(func=cmd_imagegen_show)
    imagegen_config = imagegen_sub.add_parser("config", help="Update the image generation configuration")
    imagegen_config.add_argument(
        "--enabled", choices=["true", "false"], default=None,
        help="Enable or disable the generate_image tool (disabled tools are hidden from the model)",
    )
    imagegen_config.add_argument("--api-url", default=None, help="Image generation API base URL")
    imagegen_config.add_argument("--api-key", default=None, help="API key (stored in plaintext in the config database)")
    imagegen_config.add_argument("--model", default=None, help="Image model id")
    imagegen_config.add_argument("--config-db", default="", help="LLM config database (default: data/lamtools.db)")
    imagegen_config.set_defaults(func=cmd_imagegen_config)

    artifact = sub.add_parser("artifact", help="Manage project artifacts (.lam/artifact/)")
    artifact_sub = artifact.add_subparsers(dest="artifact_command", required=True)
    artifact_list = artifact_sub.add_parser("list", help="List artifacts of a project workspace")
    artifact_list.add_argument("--work-root", default="", help="Project work_root (default: current directory)")
    artifact_list.add_argument("--include-deleted", action="store_true", help="Also list soft-deleted tombstones")
    artifact_list.set_defaults(func=cmd_artifact_list)
    artifact_show = artifact_sub.add_parser("show", help="Show a single artifact manifest")
    artifact_show.add_argument("artifact_id")
    artifact_show.add_argument("--work-root", default="", help="Project work_root (default: current directory)")
    artifact_show.set_defaults(func=cmd_artifact_show)
    artifact_delete = artifact_sub.add_parser("delete", help="Soft-delete artifacts (id/manifest 保留)")
    artifact_delete.add_argument("artifact_ids", nargs="+")
    artifact_delete.add_argument("--work-root", default="", help="Project work_root (default: current directory)")
    artifact_delete.set_defaults(func=cmd_artifact_delete)

    session = sub.add_parser("session", help="Query Core Agent sessions")
    session_sub = session.add_subparsers(dest="session_command", required=True)
    session_list = session_sub.add_parser("list", help="List Core Agent sessions")
    session_list.add_argument("--core-db", default="", help="Core-owned SQLite runtime database")
    session_list.add_argument("--raw", action="store_true")
    session_list.set_defaults(func=cmd_session_list)
    session_ls = session_sub.add_parser("ls", help="List Core Agent sessions")
    session_ls.add_argument("--core-db", default="", help="Core-owned SQLite runtime database")
    session_ls.add_argument("--raw", action="store_true")
    session_ls.set_defaults(session_command="list", func=cmd_session_list)
    session_show = session_sub.add_parser("show", help="Show a Core Agent session")
    session_show.add_argument("thread_id")
    session_show.add_argument("--core-db", default="", help="Core-owned SQLite runtime database")
    session_show.add_argument("--raw", action="store_true")
    session_show.set_defaults(func=cmd_session_show)
    session_checkpoints = session_sub.add_parser("checkpoints", help="List session rollback checkpoints")
    session_checkpoints.add_argument("thread_id")
    _add_live_connection_arguments(session_checkpoints)
    session_checkpoints.add_argument("--raw", action="store_true")
    session_checkpoints.set_defaults(func=cmd_session_checkpoints)
    session_rollback = session_sub.add_parser("rollback", help="Restore conversation and files to a checkpoint")
    session_rollback.add_argument("thread_id")
    session_rollback.add_argument("checkpoint_id")
    _add_live_connection_arguments(session_rollback)
    session_rollback.add_argument("--raw", action="store_true")
    session_rollback.set_defaults(func=cmd_session_rollback)

    project = sub.add_parser("project", help="Manage Core project workspaces")
    project_sub = project.add_subparsers(dest="project_command", required=True)
    project_list = project_sub.add_parser("list", help="List project workspaces")
    project_list.add_argument("--core-db", default="", help="Core-owned SQLite runtime database")
    project_list.set_defaults(func=cmd_project_list)
    project_create = project_sub.add_parser("create", help="Create or reuse a project workspace")
    project_create.add_argument("work_root")
    project_create.add_argument("--name", default=None)
    project_create.add_argument("--core-db", default="", help="Core-owned SQLite runtime database")
    project_create.set_defaults(func=cmd_project_create)
    project_show = project_sub.add_parser("show", help="Show a project workspace")
    project_show.add_argument("project_id")
    project_show.add_argument("--core-db", default="", help="Core-owned SQLite runtime database")
    project_show.set_defaults(func=cmd_project_show)
    project_rename = project_sub.add_parser("rename", help="Rename a project workspace")
    project_rename.add_argument("project_id")
    project_rename.add_argument("name")
    project_rename.add_argument("--core-db", default="", help="Core-owned SQLite runtime database")
    project_rename.set_defaults(func=cmd_project_rename)
    project_delete = project_sub.add_parser("delete", help="Delete a project record")
    project_delete.add_argument("project_id")
    project_delete.add_argument("--core-db", default="", help="Core-owned SQLite runtime database")
    project_delete.set_defaults(func=cmd_project_delete)
    project_agents = project_sub.add_parser("agents", help="Manage project AGENTS.md")
    project_agents_sub = project_agents.add_subparsers(dest="project_agents_command", required=True)
    project_agents_get = project_agents_sub.add_parser("get", help="Read project AGENTS.md")
    project_agents_get.add_argument("project_id")
    project_agents_get.add_argument("--core-db", default="", help="Core-owned SQLite runtime database")
    project_agents_get.set_defaults(func=cmd_project_agents_get)
    project_agents_set = project_agents_sub.add_parser("set", help="Set project AGENTS.md from a UTF-8 file")
    project_agents_set.add_argument("project_id")
    project_agents_set.add_argument("source_file")
    project_agents_set.add_argument("--core-db", default="", help="Core-owned SQLite runtime database")
    project_agents_set.set_defaults(func=cmd_project_agents_set)

    goal = sub.add_parser("goal", help="Manage durable goals")
    goal_sub = goal.add_subparsers(dest="goal_command")
    goal_create = goal_sub.add_parser("new", help="Create a new goal")
    goal_create.add_argument("thread_id", help="Thread ID")
    goal_create.add_argument("objective", nargs="+", help="Goal objective text")
    goal_create.add_argument("--base-url", default=os.environ.get("LAMTOOLS_CORE_API_URL", "http://127.0.0.1:5172"))
    goal_create.add_argument("--ws-path", default=os.environ.get("LAMTOOLS_CORE_WS_PATH", "/api/core/app-server"))
    goal_create.add_argument("--token", default=os.environ.get("LAMTOOLS_CORE_TOKEN", ""))
    goal_create.set_defaults(func=cmd_goal_create, raw=False)
    goal_list = goal_sub.add_parser("ls", help="List goals")
    goal_list.add_argument("--base-url", default=os.environ.get("LAMTOOLS_CORE_API_URL", "http://127.0.0.1:5172"))
    goal_list.add_argument("--ws-path", default=os.environ.get("LAMTOOLS_CORE_WS_PATH", "/api/core/app-server"))
    goal_list.add_argument("--token", default=os.environ.get("LAMTOOLS_CORE_TOKEN", ""))
    goal_list.set_defaults(func=cmd_goal_list, thread_id="", raw=False)
    goal_show = goal_sub.add_parser("describe", help="Show a goal")
    goal_show.add_argument("goal_id", help="Goal ID")
    goal_show.add_argument("--base-url", default=os.environ.get("LAMTOOLS_CORE_API_URL", "http://127.0.0.1:5172"))
    goal_show.add_argument("--ws-path", default=os.environ.get("LAMTOOLS_CORE_WS_PATH", "/api/core/app-server"))
    goal_show.add_argument("--token", default=os.environ.get("LAMTOOLS_CORE_TOKEN", ""))
    goal_show.set_defaults(func=cmd_goal_show, thread_id="", raw=False)
    goal_update = goal_sub.add_parser("set", help="Set goal status")
    goal_update.add_argument("goal_id", help="Goal ID")
    goal_update.add_argument("--status", default="", help="New status: active/blocked/archived")
    goal_update.add_argument("--base-url", default=os.environ.get("LAMTOOLS_CORE_API_URL", "http://127.0.0.1:5172"))
    goal_update.add_argument("--ws-path", default=os.environ.get("LAMTOOLS_CORE_WS_PATH", "/api/core/app-server"))
    goal_update.add_argument("--token", default=os.environ.get("LAMTOOLS_CORE_TOKEN", ""))
    goal_update.set_defaults(func=cmd_goal_update, thread_id="", raw=False)

    arrange = sub.add_parser("arrange", help="Manage durable arrangements")
    arrange_sub = arrange.add_subparsers(dest="arrange_command")
    arrange_create = arrange_sub.add_parser("new", help="Create a new arrangement")
    arrange_create.add_argument("message", nargs="+", help="Arrangement instruction text")
    arrange_create.add_argument("--work-root", required=True, default="", help="Project work root absolute path (required)")
    arrange_create.add_argument("--thread-id", default="", help="Target thread ID (uses source thread if omitted)")
    arrange_create.add_argument("--title", default="", help="Card title (defaults to first 40 chars of message)")
    arrange_create.add_argument("--session-strategy", choices=["fixed", "new"], default="new", help="Session strategy: fixed or new (default: new)")
    arrange_create.add_argument("--kind", choices=["routine", "focus"], default="routine", help="Arrangement kind (default: routine)")
    arrange_create.add_argument("--trigger-once", default="", help="One-time run at local datetime (e.g. 2026-12-31T08:00)")
    arrange_create.add_argument("--trigger-daily", default="", help="Daily at wall-clock time HH:MM (e.g. 09:00)")
    arrange_create.add_argument("--trigger-monthly", default="", help="Monthly at DAY:HH:MM (e.g. 5:09:00)")
    arrange_create.add_argument("--trigger-event", default="", help="Event-triggered by event type name")
    arrange_create.add_argument("--timezone", default="Asia/Shanghai", help="Timezone for calendar triggers")
    arrange_create.add_argument("--model-id", default="", help="Default model for new sessions (strategy=new)")
    arrange_create.add_argument("--max-runs", type=int, default=None, help="Maximum run count")
    arrange_create.add_argument("--base-url", default=os.environ.get("LAMTOOLS_CORE_API_URL", "http://127.0.0.1:5172"))
    arrange_create.add_argument("--ws-path", default=os.environ.get("LAMTOOLS_CORE_WS_PATH", "/api/core/app-server"))
    arrange_create.add_argument("--token", default=os.environ.get("LAMTOOLS_CORE_TOKEN", ""))
    arrange_create.set_defaults(func=cmd_arrange_create, raw=False)
    arrange_list = arrange_sub.add_parser("ls", help="List arrangements")
    arrange_list.add_argument("--work-root", default="", help="Filter by project work_root")
    arrange_list.add_argument("--base-url", default=os.environ.get("LAMTOOLS_CORE_API_URL", "http://127.0.0.1:5172"))
    arrange_list.add_argument("--ws-path", default=os.environ.get("LAMTOOLS_CORE_WS_PATH", "/api/core/app-server"))
    arrange_list.add_argument("--token", default=os.environ.get("LAMTOOLS_CORE_TOKEN", ""))
    arrange_list.set_defaults(func=cmd_arrange_list, thread_id="", raw=False)
    arrange_show = arrange_sub.add_parser("describe", help="Show an arrangement")
    arrange_show.add_argument("job_id", help="Job ID")
    arrange_show.add_argument("--base-url", default=os.environ.get("LAMTOOLS_CORE_API_URL", "http://127.0.0.1:5172"))
    arrange_show.add_argument("--ws-path", default=os.environ.get("LAMTOOLS_CORE_WS_PATH", "/api/core/app-server"))
    arrange_show.add_argument("--token", default=os.environ.get("LAMTOOLS_CORE_TOKEN", ""))
    arrange_show.set_defaults(func=cmd_arrange_show, thread_id="", raw=False)
    arrange_update = arrange_sub.add_parser("set", help="Set arrangement status")
    arrange_update.add_argument("job_id", help="Job ID")
    arrange_update.add_argument("--status", default="", help="New status: scheduled/paused/cancelled")
    arrange_update.add_argument("--base-url", default=os.environ.get("LAMTOOLS_CORE_API_URL", "http://127.0.0.1:5172"))
    arrange_update.add_argument("--ws-path", default=os.environ.get("LAMTOOLS_CORE_WS_PATH", "/api/core/app-server"))
    arrange_update.add_argument("--token", default=os.environ.get("LAMTOOLS_CORE_TOKEN", ""))
    arrange_update.set_defaults(func=cmd_arrange_update, thread_id="", raw=False)
    arrange_edit = arrange_sub.add_parser("edit", help="Edit arrangement fields")
    arrange_edit.add_argument("job_id", help="Job ID")
    arrange_edit.add_argument("--title", default="", help="New title")
    arrange_edit.add_argument("--instruction", default="", help="New instruction text")
    arrange_edit.add_argument("--session-strategy", choices=["fixed", "new"], default="", help="Session strategy")
    arrange_edit.add_argument("--model-id", default="", help="Default model for new sessions")
    arrange_edit.add_argument("--trigger-once", default="", help="New one-time trigger")
    arrange_edit.add_argument("--trigger-daily", default="", help="New daily trigger HH:MM")
    arrange_edit.add_argument("--trigger-monthly", default="", help="New monthly trigger DAY:HH:MM")
    arrange_edit.add_argument("--trigger-event", default="", help="New event type")
    arrange_edit.add_argument("--timezone", default="Asia/Shanghai", help="Timezone for calendar triggers")
    arrange_edit.add_argument("--base-url", default=os.environ.get("LAMTOOLS_CORE_API_URL", "http://127.0.0.1:5172"))
    arrange_edit.add_argument("--ws-path", default=os.environ.get("LAMTOOLS_CORE_WS_PATH", "/api/core/app-server"))
    arrange_edit.add_argument("--token", default=os.environ.get("LAMTOOLS_CORE_TOKEN", ""))
    arrange_edit.set_defaults(func=cmd_arrange_edit, raw=False)

    workflow = sub.add_parser("workflow", help="Manage workflow node graphs")
    workflow_sub = workflow.add_subparsers(dest="workflow_command")
    wf_new = workflow_sub.add_parser("new", help="Create a workflow from a JSON definition file")
    wf_new.add_argument("--name", default="", help="Workflow name (overrides the name in --from-file)")
    wf_new.add_argument("--from-file", required=True, help="Path to a JSON workflow definition")
    wf_new.add_argument("--work-root", required=True, default="", help="Project work root absolute path (required)")
    wf_new.add_argument("--exposed", action="store_true", help="Expose this workflow as an agent tool immediately")
    wf_new.add_argument("--base-url", default=os.environ.get("LAMTOOLS_CORE_API_URL", "http://127.0.0.1:5172"))
    wf_new.add_argument("--ws-path", default=os.environ.get("LAMTOOLS_CORE_WS_PATH", "/api/core/app-server"))
    wf_new.add_argument("--token", default=os.environ.get("LAMTOOLS_CORE_TOKEN", ""))
    wf_new.set_defaults(func=cmd_workflow_new, raw=False)
    wf_list = workflow_sub.add_parser("ls", help="List workflows")
    wf_list.add_argument("--work-root", default="", help="Filter by project work_root")
    wf_list.add_argument("--base-url", default=os.environ.get("LAMTOOLS_CORE_API_URL", "http://127.0.0.1:5172"))
    wf_list.add_argument("--ws-path", default=os.environ.get("LAMTOOLS_CORE_WS_PATH", "/api/core/app-server"))
    wf_list.add_argument("--token", default=os.environ.get("LAMTOOLS_CORE_TOKEN", ""))
    wf_list.set_defaults(func=cmd_workflow_list, raw=False)
    wf_show = workflow_sub.add_parser("describe", help="Show a workflow definition")
    wf_show.add_argument("name", help="Workflow name")
    wf_show.add_argument("--work-root", default="", help="Project work root")
    wf_show.add_argument("--base-url", default=os.environ.get("LAMTOOLS_CORE_API_URL", "http://127.0.0.1:5172"))
    wf_show.add_argument("--ws-path", default=os.environ.get("LAMTOOLS_CORE_WS_PATH", "/api/core/app-server"))
    wf_show.add_argument("--token", default=os.environ.get("LAMTOOLS_CORE_TOKEN", ""))
    wf_show.set_defaults(func=cmd_workflow_describe, raw=False)
    wf_run = workflow_sub.add_parser("run", help="Run a workflow")
    wf_run.add_argument("name", help="Workflow name")
    wf_run.add_argument("--work-root", default="", help="Project work root")
    wf_run.add_argument("--input", action="append", default=[], metavar="KEY=VALUE", help="Workflow input (repeatable; VALUE parsed as JSON if possible)")
    wf_run.add_argument("--max-steps", type=int, default=None, help="Run at most N nodes (single-step debugging)")
    wf_run.add_argument("--start-node", default=None, help="Start running from this node (sub-graph; nodes before it are skipped)")
    wf_run.add_argument("--single-node", default=None, help="Run exactly this one node in isolation")
    wf_run.add_argument("--base-url", default=os.environ.get("LAMTOOLS_CORE_API_URL", "http://127.0.0.1:5172"))
    wf_run.add_argument("--ws-path", default=os.environ.get("LAMTOOLS_CORE_WS_PATH", "/api/core/app-server"))
    wf_run.add_argument("--token", default=os.environ.get("LAMTOOLS_CORE_TOKEN", ""))
    wf_run.set_defaults(func=cmd_workflow_run, raw=False)
    wf_expose = workflow_sub.add_parser("expose", help="Expose a workflow as an agent tool")
    wf_expose.add_argument("name", help="Workflow name")
    wf_expose.add_argument("--work-root", default="", help="Project work root")
    wf_expose.add_argument("--base-url", default=os.environ.get("LAMTOOLS_CORE_API_URL", "http://127.0.0.1:5172"))
    wf_expose.add_argument("--ws-path", default=os.environ.get("LAMTOOLS_CORE_WS_PATH", "/api/core/app-server"))
    wf_expose.add_argument("--token", default=os.environ.get("LAMTOOLS_CORE_TOKEN", ""))
    wf_expose.set_defaults(func=cmd_workflow_expose, raw=False)
    wf_unexpose = workflow_sub.add_parser("unexpose", help="Unexpose a workflow (no longer an agent tool)")
    wf_unexpose.add_argument("name", help="Workflow name")
    wf_unexpose.add_argument("--work-root", default="", help="Project work root")
    wf_unexpose.add_argument("--base-url", default=os.environ.get("LAMTOOLS_CORE_API_URL", "http://127.0.0.1:5172"))
    wf_unexpose.add_argument("--ws-path", default=os.environ.get("LAMTOOLS_CORE_WS_PATH", "/api/core/app-server"))
    wf_unexpose.add_argument("--token", default=os.environ.get("LAMTOOLS_CORE_TOKEN", ""))
    wf_unexpose.set_defaults(func=cmd_workflow_unexpose, raw=False)

    subagent = sub.add_parser("subagent", help="Manage sub-agent delegation guide")
    subagent_sub = subagent.add_subparsers(dest="subagent_command", required=True)
    sa_guide = subagent_sub.add_parser("guide", help="Show or edit the sub-agent delegation guide")
    sa_guide_sub = sa_guide.add_subparsers(dest="subagent_guide_command", required=True)
    sa_guide_show = sa_guide_sub.add_parser("show", help="Print the effective sub-agent guide")
    sa_guide_show.add_argument("--work-root", default="", help="Project work root")
    sa_guide_show.add_argument("--scope", choices=("project", "global"), default="", help="Show only a specific scope")
    sa_guide_show.set_defaults(func=cmd_subagent_guide_show)
    sa_guide_set = sa_guide_sub.add_parser("set", help="Write the guide from a UTF-8 file or stdin")
    sa_guide_set.add_argument("source_file", help="Path to a markdown file, or '-' for stdin")
    sa_guide_set.add_argument("--scope", choices=("project", "global"), default="global", help="Write scope")
    sa_guide_set.add_argument("--work-root", default="", help="Project work root (required for --scope project)")
    sa_guide_set.set_defaults(func=cmd_subagent_guide_set)
    sa_guide_edit = sa_guide_sub.add_parser("edit", help="Open the guide in $EDITOR")
    sa_guide_edit.add_argument("--scope", choices=("project", "global"), default="global", help="Edit scope")
    sa_guide_edit.add_argument("--work-root", default="", help="Project work root (required for --scope project)")
    sa_guide_edit.set_defaults(func=cmd_subagent_guide_edit)

    models = sub.add_parser("models", help="Manage model definitions (jsonc-backed)")
    models_sub = models.add_subparsers(dest="models_command", required=True)
    models_list = models_sub.add_parser("list", help="List configured models")
    models_list.add_argument("--work-root", default="")
    models_list.set_defaults(func=cmd_models_list)
    models_show = models_sub.add_parser("show", help="Show a model definition")
    models_show.add_argument("model_id")
    models_show.add_argument("--work-root", default="")
    models_show.set_defaults(func=cmd_models_show)
    models_set = models_sub.add_parser("set", help="Update a model field (e.g. capability)")
    models_set.add_argument("model_id")
    models_set.add_argument("--field", required=True, help="Field to set: capability|is_default|adapter_profile_id|context_window|max_output_tokens|temperature")
    models_set.add_argument("--value", required=True)
    models_set.add_argument("--scope", choices=("project", "global"), default="global")
    models_set.add_argument("--work-root", default="")
    models_set.set_defaults(func=cmd_models_set)
    models_default = models_sub.add_parser("default", help="Set the default model")
    models_default.add_argument("model_id")
    models_default.add_argument("--scope", choices=("project", "global"), default="global")
    models_default.add_argument("--work-root", default="")
    models_default.set_defaults(func=cmd_models_default)
    models_import = models_sub.add_parser("import-from-db", help="Export DB llm_models rows to jsonc")
    models_import.add_argument("--config-db", required=True)
    models_import.add_argument("--scope", choices=("project", "global"), default="global")
    models_import.add_argument("--work-root", default="")
    models_import.add_argument("--force", action="store_true")
    models_import.set_defaults(func=cmd_models_import_from_db)

    loadtools = sub.add_parser("loadtools", help="Manage mode tool-set configuration (loadtools.jsonc)")
    loadtools_sub = loadtools.add_subparsers(dest="loadtools_command", required=True)
    loadtools_show = loadtools_sub.add_parser("show", help="Print the effective mode tool-sets")
    loadtools_show.set_defaults(func=cmd_loadtools_show)
    loadtools_edit = loadtools_sub.add_parser("edit-mode", help="Create or update a mode's tool whitelist")
    loadtools_edit.add_argument("--mode", required=True, help="Mode name (e.g. consider)")
    loadtools_edit.add_argument("--description", default="", help="Mode description shown in the system prompt")
    loadtools_edit.add_argument("--tools", default="", help="Comma-separated tool names; empty means all tools allowed")
    loadtools_edit.add_argument("--no-limit", action="store_true", help="Full access: empty tools list (all tools allowed)")
    loadtools_edit.set_defaults(func=cmd_loadtools_edit_mode)
    loadtools_delete = loadtools_sub.add_parser("delete-mode", help="Remove a mode from the configuration")
    loadtools_delete.add_argument("--mode", required=True)
    loadtools_delete.set_defaults(func=cmd_loadtools_delete_mode)

    memory = sub.add_parser("memory", help="Read or write the global memory.md (unified config dir)")
    memory_sub = memory.add_subparsers(dest="memory_command", required=True)
    memory_get = memory_sub.add_parser("get", help="Print the global memory.md content")
    memory_get.set_defaults(func=cmd_memory_get)
    memory_set = memory_sub.add_parser("set", help="Write the global memory.md from a UTF-8 file or stdin")
    memory_set.add_argument("source_file", help="Path to a markdown file, or '-' for stdin")
    memory_set.set_defaults(func=cmd_memory_set)

    load_context = sub.add_parser("load-context", help="Read or write the global load_context.jsonc (unified config dir)")
    load_context_sub = load_context.add_subparsers(dest="load_context_command", required=True)
    load_context_get = load_context_sub.add_parser("get", help="Print the parsed global load_context (addition/except)")
    load_context_get.set_defaults(func=cmd_load_context_get)
    load_context_set = load_context_sub.add_parser("set", help="Write global load_context from a JSON file or stdin")
    load_context_set.add_argument("source_file", help="Path to a JSON file, or '-' for stdin")
    load_context_set.set_defaults(func=cmd_load_context_set)
    return parser


def _add_live_connection_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--base-url", default=os.environ.get("LAMTOOLS_CORE_API_URL", "http://127.0.0.1:5172"))
    parser.add_argument("--ws-path", default=os.environ.get("LAMTOOLS_CORE_WS_PATH", "/api/core/app-server"))
    parser.add_argument("--token", default=os.environ.get("LAMTOOLS_CORE_TOKEN", ""))


async def _invoke_live(args: argparse.Namespace, operation: Any) -> dict[str, Any]:
    client = CoreAppServerClient(args.base_url, path=args.ws_path, token=args.token)
    try:
        await client.connect()
        return await operation(client)
    finally:
        await client.close()


def _print_live_result(args: argparse.Namespace, result: dict[str, Any], message: str) -> None:
    if args.raw:
        print(json.dumps(result, ensure_ascii=False), flush=True)
    else:
        print(message, flush=True)


async def cmd_serve(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s [%(name)s] %(message)s",
        force=True,
    )
    try:
        import uvicorn
    except ImportError as exc:
        raise RuntimeError("serve requires uvicorn; install the Core HTTP server dependencies") from exc
    # Seed the unified config directory with built-in defaults on first run
    # (idempotent; user edits are never overwritten).
    from lamtools_core.config.defaults import ensure_default_config_files

    ensure_default_config_files()
    from lamtools_core.app.http_agent_app import create_core_agent_http_app

    app = create_core_agent_http_app(
        model_id=args.model_id,
        config_db=args.config_db or None,
        core_db=args.core_db or None,
        data_dir=args.data_dir or None,
        work_root=args.work_root or None,
        frontend_dir=args.frontend_dir or None,
        thinking_enabled=args.thinking == "enabled",
        thinking_budget=args.thinking_budget,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
    )
    url = f"http://{args.host}:{args.port}"
    _print_live_result(args, {"url": url}, f"serving {url}")
    server = uvicorn.Server(uvicorn.Config(app, host=args.host, port=args.port, reload=bool(args.reload)))
    await server.serve()
    return 0


async def cmd_setup(args: argparse.Namespace) -> int:
    del args
    root = ensure_projects_root()
    # Seed the unified config directory with built-in defaults (idempotent).
    from lamtools_core.config.defaults import ensure_default_config_files

    ensure_default_config_files()
    print(json.dumps({"lam_projects": str(root), "created": True}, ensure_ascii=False), flush=True)
    return 0


async def cmd_migrate_projects(args: argparse.Namespace) -> int:
    from lamtools_core.config.migrate_projects import migrate_projects

    db = await open_core_app_db(_resolve_core_db(args.core_db or None))
    try:
        report = await migrate_projects(db, apply=bool(args.apply))
    finally:
        await db.close()
    label = "migrated" if report.applied else "dry-run"
    print(json.dumps({"status": label, **report.to_dict()}, ensure_ascii=False, sort_keys=True), flush=True)
    return 0


async def cmd_start(args: argparse.Namespace) -> int:
    async def start(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.start_turn(
            thread_id=args.thread_id,
            input_items=[{"type": "text", "text": " ".join(args.message)}],
            work_root=args.work_root,
            model_id=args.model_id or None,
            goal_id=args.goal_id or None,
            thinking_enabled=args.thinking == "enabled",
            thinking_budget=args.thinking_budget,
            shallow_thinking_enabled=bool(args.shallow),
            approval_policy=args.approval_policy,
            client_message_id=args.client_message_id or None,
        )

    if args.watch:
        return await _watch_live_cli(args, thread_id=args.thread_id, on_connected=start)
    result = await _invoke_live(args, start)
    _print_live_result(args, result, f"started {args.thread_id}")
    return 0


async def cmd_cancel(args: argparse.Namespace) -> int:
    result = await _invoke_live(args, lambda client: client.cancel_turn(thread_id=args.thread_id, turn_id=args.turn_id))
    _print_live_result(args, result, f"cancel requested {args.thread_id}")
    return 0


async def cmd_steer(args: argparse.Namespace) -> int:
    result = await _invoke_live(
        args,
        lambda client: client.steer_turn(
            thread_id=args.thread_id,
            turn_id=args.turn_id,
            input_items=[{"type": "text", "text": " ".join(args.message)}],
        ),
    )
    _print_live_result(args, result, f"steered {args.thread_id}")
    return 0


async def cmd_queue_create(args: argparse.Namespace) -> int:
    result = await _invoke_live(
        args,
        lambda client: client.create_queue_input(
            thread_id=args.thread_id,
            input_items=[{"type": "text", "text": " ".join(args.message)}],
        ),
    )
    _print_live_result(args, result, f"queued {args.thread_id}")
    return 0


async def cmd_queue_update(args: argparse.Namespace) -> int:
    result = await _invoke_live(
        args,
        lambda client: client.update_queue_input(
            thread_id=args.thread_id,
            queue_item_id=args.queue_item_id,
            text=" ".join(args.message),
        ),
    )
    _print_live_result(args, result, f"updated queue item {args.queue_item_id}")
    return 0


async def cmd_queue_delete(args: argparse.Namespace) -> int:
    result = await _invoke_live(
        args,
        lambda client: client.delete_queue_input(thread_id=args.thread_id, queue_item_id=args.queue_item_id),
    )
    _print_live_result(args, result, f"deleted queue item {args.queue_item_id}")
    return 0


async def cmd_queue_guide(args: argparse.Namespace) -> int:
    result = await _invoke_live(
        args,
        lambda client: client.guide_queue_input(
            thread_id=args.thread_id,
            turn_id=args.turn_id,
            queue_item_id=args.queue_item_id,
            text=" ".join(args.message) or None,
        ),
    )
    _print_live_result(args, result, f"guided {args.thread_id}")
    return 0


async def cmd_approval_respond(args: argparse.Namespace) -> int:
    result = await _invoke_live(
        args,
        lambda client: client.request(
            "approval.respond",
            {"thread_id": args.thread_id, "action": args.action, "response": " ".join(args.response)},
        ),
    )
    _print_live_result(args, result, f"approval {args.action} sent")
    return 0


async def cmd_command_catalog(args: argparse.Namespace) -> int:
    result = await _invoke_live(
        args,
        lambda client: client.request("command.catalog", {"work_root": args.work_root}),
    )
    message = "\n".join(
        f"/{item['name']}\t{item.get('description', '')}"
        for item in result.get("commands", [])
        if isinstance(item, dict) and item.get("name")
    )
    _print_live_result(args, result, message)
    return 0


async def cmd_command_execute(args: argparse.Namespace) -> int:
    if args.name == "compact":
        formatter = CliLiveFormatter()

        def output(chunk: OutputChunk) -> None:
            print(str(chunk), end=chunk.end, flush=chunk.flush)

        result, saw_terminal = await execute_compaction_command_live(
            client_factory=lambda: CoreAppServerClient(args.base_url, path=args.ws_path, token=args.token),
            thread_id=args.thread_id,
            work_root=args.work_root,
            formatter=formatter,
            output=output,
            raw=bool(args.raw),
        )
        if args.raw:
            print(json.dumps(result, ensure_ascii=False), flush=True)
        elif not saw_terminal:
            print(format_compaction_result(result), flush=True)
        return 0
    result = await _invoke_live(
        args,
        lambda client: client.request(
            "command.execute",
            {"thread_id": args.thread_id, "command": args.name, "work_root": args.work_root},
        ),
    )
    _print_live_result(args, result, f"/{args.name} completed for {args.thread_id}")
    return 0


async def cmd_attachment_upload(args: argparse.Namespace) -> int:
    path = Path(args.file).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Attachment file not found: {path}")
    headers = {"Authorization": f"Bearer {args.token}"} if args.token else {}
    async with httpx.AsyncClient(timeout=60.0, headers=headers) as client:
        with path.open("rb") as stream:
            response = await client.post(
                f"{args.base_url.rstrip('/')}/api/core/sessions/{quote(args.thread_id, safe='')}/attachments",
                files={"file": (path.name, stream)},
            )
        response.raise_for_status()
        result = response.json()
    _print_live_result(args, result, f"uploaded {path.name} ({result.get('id', '-')})")
    return 0


async def cmd_run(args: argparse.Namespace) -> int:
    compact_trigger_tokens = getattr(args, "compact_trigger_tokens", None)
    compact_limit_tokens = getattr(args, "compact_limit_tokens", None)
    if compact_trigger_tokens is not None and compact_trigger_tokens <= 0:
        raise ValueError("--compact-trigger-tokens must be positive")
    if compact_limit_tokens is not None and compact_limit_tokens <= 0:
        raise ValueError("--compact-limit-tokens must be positive")
    if (
        compact_trigger_tokens is not None
        and compact_limit_tokens is not None
        and compact_limit_tokens > compact_trigger_tokens
    ):
        raise ValueError("--compact-limit-tokens cannot exceed --compact-trigger-tokens")
    thread_id = _resolve_thread_id(args.thread_id)
    context_window_tokens = _resolve_cli_context_window(args)
    if not args.raw:
        print(f"[session] {thread_id}", flush=True)
    async def start(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.start_turn(
            thread_id=thread_id,
            input_items=[{"type": "text", "text": " ".join(args.message)}],
            work_root=str(args.work_root or _default_work_root()),
            model_id=args.model_id or None,
            goal_id=args.goal_id or None,
            thinking_enabled=not bool(args.no_thinking),
            thinking_budget=args.thinking_budget,
            shallow_thinking_enabled=bool(args.shallow_thinking),
            max_tokens=int(args.max_tokens) if args.max_tokens is not None else None,
            temperature=float(args.temperature),
            compact_trigger_tokens=compact_trigger_tokens,
            compact_limit_tokens=compact_limit_tokens,
            context_window_tokens=context_window_tokens,
            approval_policy="auto_approve" if bool(args.auto_approve) else "require",
        )


    return await _watch_live_cli(args, thread_id=thread_id, on_connected=start)


async def cmd_run_local(args: argparse.Namespace) -> int:
    compact_trigger_tokens = getattr(args, "compact_trigger_tokens", None)
    compact_limit_tokens = getattr(args, "compact_limit_tokens", None)
    if compact_trigger_tokens is not None and compact_trigger_tokens <= 0:
        raise ValueError("--compact-trigger-tokens must be positive")
    if compact_limit_tokens is not None and compact_limit_tokens <= 0:
        raise ValueError("--compact-limit-tokens must be positive")
    if (
        compact_trigger_tokens is not None
        and compact_limit_tokens is not None
        and compact_limit_tokens > compact_trigger_tokens
    ):
        raise ValueError("--compact-limit-tokens cannot exceed --compact-trigger-tokens")
    options = CoreCliRunOptions(
        message=" ".join(args.message),
        model_id=args.model_id or "",
        work_root=args.work_root or _default_work_root(),
        run_dir=args.run_dir or None,
        core_db=args.core_db or None,
        thread_id=args.thread_id or _resolve_thread_id(""),
        config_db=args.config_db or None,
        adapter_dirs=(),
        plugin_roots=(),
        thinking_enabled=not bool(args.no_thinking),
        thinking_budget=args.thinking_budget,
        shallow_thinking_enabled=bool(args.shallow_thinking),
        max_tokens=int(args.max_tokens) if args.max_tokens is not None else None,
        compact_trigger_tokens=compact_trigger_tokens,
        compact_limit_tokens=compact_limit_tokens,
        temperature=float(args.temperature),
        approval_policy="auto_approve" if bool(args.auto_approve) else "require",
        raw=bool(args.raw),
        verbose=bool(args.verbose),
    )
    summary = await run_core_cli_task(options)
    if args.raw:
        print(json.dumps(summary, ensure_ascii=False), flush=True)
    else:
        ok = summary.get("ok", False)
        status = "done" if ok else "failed"
        model_info = summary.get("model", {})
        model_name = model_info.get("display_name") or model_info.get("model_id", "?")
        steps = summary.get("result", {}).get("steps_count", "?")
        print(f"[{status}] model={model_name} steps={steps}")
        artifacts = summary.get("artifacts", {})
        if artifacts.get("summary_json"):
            print(f"  summary: {artifacts['summary_json']}")
        if artifacts.get("events_redacted_json"):
            print(f"  events:  {artifacts['events_redacted_json']}")
        if artifacts.get("run_dir"):
            print(f"  run_dir: {artifacts['run_dir']}")
    return 0


async def cmd_watch(args: argparse.Namespace) -> int:
    return await _watch_live_cli(args, thread_id=args.thread_id)


async def _watch_live_cli(
    args: argparse.Namespace,
    *,
    thread_id: str,
    on_connected: Any | None = None,
) -> int:
    formatter = CliLiveFormatter(
        verbose=bool(getattr(args, "verbose", False)),
        heartbeat_interval=int(getattr(args, "heartbeat_interval", 30) or 30),
    )

    def output(chunk: OutputChunk) -> None:
        print(str(chunk), end=chunk.end, flush=chunk.flush)

    approval = None
    approval_decision = None
    if getattr(args, "approval_decision", None):
        approval = lambda: args.approval_decision
        approval_decision = lambda value: value
    elif not args.raw and (getattr(args, "interactive_decisions", False) or sys.stdin.isatty()):
        approval = lambda: asyncio.to_thread(input, "reply> ")
        approval_decision = approval_decision_from_reply

    if not args.raw:
        output(OutputChunk(formatter.line("watch", thread_id)))
    result = await watch_live_events(
        client_factory=lambda: CoreAppServerClient(args.base_url, path=args.ws_path, token=args.token),
        thread_id=thread_id,
        formatter=formatter,
        output=output,
        raw=bool(args.raw),
        approval=approval,
        approval_decision=approval_decision,
        on_connected=on_connected,
        event_timeout=getattr(args, "event_timeout", None),
        max_reconnects=int(getattr(args, "max_reconnects", 3)),
    )
    return result.exit_code


async def cmd_session_list(args: argparse.Namespace) -> int:
    sessions = await list_core_cli_sessions(core_db=args.core_db or None)
    if args.raw:
        print(json.dumps({"sessions": sessions}, ensure_ascii=False, indent=2), flush=True)
    else:
        for session in sessions:
            print(
                f"{session['thread_id']} {session.get('status') or '-'} "
                f"seq={session.get('snapshot_seq') or 0} updated={session.get('updated_at') or '-'}",
                flush=True,
            )
    return 0


async def cmd_session_checkpoints(args: argparse.Namespace) -> int:
    result = await _invoke_live(
        args,
        lambda client: client.request(
            "session.checkpoints.list",
            {"session_id": args.thread_id},
        ),
    )
    message = "\n".join(
        f"{item.get('id', '-')} {item.get('actor_kind', '-')} turn={item.get('turn_id', '-')}"
        for item in result.get("checkpoints", [])
        if isinstance(item, dict)
    )
    _print_live_result(args, result, message)
    return 0


async def cmd_session_rollback(args: argparse.Namespace) -> int:
    result = await _invoke_live(
        args,
        lambda client: client.request(
            "session.rollback",
            {"session_id": args.thread_id, "checkpoint_id": args.checkpoint_id},
        ),
    )
    _print_live_result(args, result, f"rollback {result.get('status', '-')} ({result.get('operation_id', '-')})")
    return 0


async def cmd_session_show(args: argparse.Namespace) -> int:
    detail = await show_core_cli_session(args.thread_id, core_db=args.core_db or None)
    if args.raw:
        print(json.dumps(detail, ensure_ascii=False, indent=2), flush=True)
    else:
        snapshot = detail.get("snapshot") if isinstance(detail.get("snapshot"), dict) else {}
        print(f"[session] {detail['thread_id']}", flush=True)
        print(f"[status] {snapshot.get('status') or '-'} seq={snapshot.get('snapshot_seq') or 0}", flush=True)
        print(f"[events] {len(detail.get('events') or [])}", flush=True)
    return 0


async def list_core_cli_sessions(*, core_db: Path | str | None = None) -> list[dict[str, Any]]:
    db = await open_core_app_db(_resolve_core_db(core_db))
    try:
        return await list_core_sessions(db)
    finally:
        await db.close()


async def show_core_cli_session(thread_id: str, *, core_db: Path | str | None = None) -> dict[str, Any]:
    db = await open_core_app_db(_resolve_core_db(core_db))
    try:
        return await show_core_session(db, thread_id)
    finally:
        await db.close()


def _print_project_result(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), flush=True)


async def cmd_project_list(args: argparse.Namespace) -> int:
    db = await open_core_app_db(_resolve_core_db(args.core_db or None))
    try:
        _print_project_result({"projects": [project.to_dict() for project in await db.project_store.list()]})
    finally:
        await db.close()
    return 0


async def cmd_project_create(args: argparse.Namespace) -> int:
    db = await open_core_app_db(_resolve_core_db(args.core_db or None))
    try:
        project, session, created = await db.project_store.create_with_initial_session(args.work_root, name=args.name)
        _print_project_result({"created": created, "project": project.to_dict(), "session": session.to_dict()})
    finally:
        await db.close()
    return 0


async def cmd_project_show(args: argparse.Namespace) -> int:
    db = await open_core_app_db(_resolve_core_db(args.core_db or None))
    try:
        project = await db.project_store.get(args.project_id)
        if project is None:
            raise RuntimeError("Project not found")
        _print_project_result({"project": project.to_dict()})
    finally:
        await db.close()
    return 0


async def cmd_project_rename(args: argparse.Namespace) -> int:
    db = await open_core_app_db(_resolve_core_db(args.core_db or None))
    try:
        project = await db.project_store.rename(args.project_id, args.name)
        if project is None:
            raise RuntimeError("Project not found")
        _print_project_result({"project": project.to_dict()})
    finally:
        await db.close()
    return 0


async def cmd_project_delete(args: argparse.Namespace) -> int:
    db = await open_core_app_db(_resolve_core_db(args.core_db or None))
    try:
        if not await db.project_store.delete_with_sessions(args.project_id):
            raise RuntimeError("Project not found")
        _print_project_result({"deleted": True, "project_id": args.project_id})
    finally:
        await db.close()
    return 0


async def cmd_project_agents_get(args: argparse.Namespace) -> int:
    db = await open_core_app_db(_resolve_core_db(args.core_db or None))
    try:
        agents_md = await db.project_store.read_agents_md(args.project_id)
        if agents_md is None:
            raise RuntimeError("Project not found")
        _print_project_result({"agents_md": agents_md})
    finally:
        await db.close()
    return 0


async def cmd_project_agents_set(args: argparse.Namespace) -> int:
    content = Path(args.source_file).read_text(encoding="utf-8")
    db = await open_core_app_db(_resolve_core_db(args.core_db or None))
    try:
        agents_md = await db.project_store.write_agents_md(args.project_id, content)
        if agents_md is None:
            raise RuntimeError("Project not found")
        _print_project_result({"agents_md": agents_md})
    finally:
        await db.close()
    return 0


async def cmd_goal_create(args: argparse.Namespace) -> int:
    async def op(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request("goal.create", {"thread_id": args.thread_id, "objective": " ".join(args.objective)})
    result = await _invoke_live(args, op)
    goal = result.get("goal", {}) if isinstance(result, dict) else {}
    gid = str(goal.get("id") or goal.get("goal_id") or "")
    print(f"[goal] {gid}")
    if not args.raw:
        obj = str(goal.get("objective") or " ".join(args.objective))
        print(f"  objective: {obj}")
    return 0


async def cmd_goal_list(args: argparse.Namespace) -> int:
    async def op(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request("goal.list", {})
    result = await _invoke_live(args, op)
    goals = result.get("goals", []) if isinstance(result, dict) else []
    if isinstance(goals, list):
        for g in goals:
            if isinstance(g, dict):
                sid = str(g.get("id") or g.get("goal_id") or "")[:16]
                obj = str(g.get("objective") or "")[:80]
                st = str(g.get("status") or "?")
                print(f"{sid}  {st:12s} {obj}")
    return 0


async def cmd_goal_show(args: argparse.Namespace) -> int:
    async def op(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request("goal.get", {"goal_id": args.goal_id})
    result = await _invoke_live(args, op)
    goal = result.get("goal", {}) if isinstance(result, dict) else {}
    if isinstance(goal, dict):
        for k in ("id", "objective", "status", "created_at"):
            v = goal.get(k)
            if v is not None:
                print(f"  {k}: {v}")
    return 0


async def cmd_goal_update(args: argparse.Namespace) -> int:
    if not args.status:
        print("error: --status is required (active/blocked/archived)", file=sys.stderr)
        return 1
    async def op(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request("goal.update", {"goal_id": args.goal_id, "status": args.status})
    result = await _invoke_live(args, op)
    goal = result.get("goal", {}) if isinstance(result, dict) else {}
    print(f"[goal] {str(goal.get('id') or args.goal_id)} status={args.status}")
    return 0


async def cmd_arrange_create(args: argparse.Namespace) -> int:
    trigger: dict[str, Any] = {}
    if args.trigger_once:
        trigger = {"type": "once", "local_at": args.trigger_once, "timezone": args.timezone}
    elif args.trigger_daily:
        trigger = {"type": "calendar", "frequency": "daily", "time": args.trigger_daily, "timezone": args.timezone}
    elif args.trigger_monthly:
        parts = args.trigger_monthly.split(":", 1)
        day = int(parts[0])
        time_val = parts[1] if len(parts) > 1 else "09:00"
        trigger = {"type": "calendar", "frequency": "monthly", "day": day, "time": time_val, "timezone": args.timezone}
    elif args.trigger_event:
        trigger = {"type": "event", "event_type": args.trigger_event}
    else:
        trigger = {"type": "once", "local_at": "", "timezone": args.timezone}
    thread_id = str(args.thread_id or "").strip()
    if not thread_id:
        thread_id = args.work_root  # fallback: use work_root as source_thread_id
    payload = {
        "work_root": args.work_root,
        "thread_id": thread_id,
        "kind": args.kind,
        "operation": "turn.start",
        "payload": {"message": " ".join(args.message)},
        "trigger": trigger,
        "title": str(args.title or "").strip(),
        "session_strategy": args.session_strategy,
        "model_id": str(args.model_id or "").strip(),
    }
    if args.max_runs is not None:
        payload["max_runs"] = args.max_runs
    async def op(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request("arrange.create", payload)
    result = await _invoke_live(args, op)
    job = result.get("job", {}) if isinstance(result, dict) else {}
    jid = str(job.get("id") or job.get("job_id") or "")
    print(f"[arrange] {jid}")
    if not args.raw:
        instruction = " ".join(args.message)
        print(f"  instruction: {instruction}")
        print(f"  trigger: {json.dumps(trigger, ensure_ascii=False)}")
    return 0


async def cmd_arrange_list(args: argparse.Namespace) -> int:
    params: dict[str, Any] = {}
    work_root = str(args.work_root or "").strip()
    if work_root:
        params["work_root"] = work_root
    async def op(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request("arrange.list", params)
    result = await _invoke_live(args, op)
    jobs = result.get("jobs", []) if isinstance(result, dict) else []
    if isinstance(jobs, list):
        for j in jobs:
            if isinstance(j, dict):
                sid = str(j.get("id") or j.get("job_id") or "")[:16]
                msg = str((j.get("payload") or {}).get("message") or "?")[:80]
                st = str(j.get("status") or "?")
                print(f"{sid}  {st:12s} {msg}")
    return 0


async def cmd_arrange_show(args: argparse.Namespace) -> int:
    async def op(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request("arrange.get", {"job_id": args.job_id})
    result = await _invoke_live(args, op)
    job = result.get("job", {}) if isinstance(result, dict) else {}
    if isinstance(job, dict):
        for k in ("id", "thread_id", "kind", "status", "run_count", "last_error", "next_run_at", "created_at", "updated_at"):
            v = job.get(k)
            if v is not None:
                print(f"  {k}: {v}")
        trigger = job.get("trigger", {})
        if isinstance(trigger, dict) and trigger:
            print(f"  trigger: {json.dumps(trigger, ensure_ascii=False)}")
        payload = job.get("payload", {})
        if isinstance(payload, dict):
            msg = payload.get("message", "")
            if msg:
                print(f"  message: {msg}")
    return 0


async def cmd_arrange_update(args: argparse.Namespace) -> int:
    if not args.status:
        print("error: --status is required (scheduled/paused/cancelled)", file=sys.stderr)
        return 1
    operation = {"scheduled": "arrange.resume", "paused": "arrange.pause", "cancelled": "arrange.cancel"}.get(args.status, "")
    if not operation:
        print(f"error: unsupported status '{args.status}' (use scheduled/paused/cancelled)", file=sys.stderr)
        return 1
    async def op(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request(operation, {"job_id": args.job_id})
    result = await _invoke_live(args, op)
    job = result.get("job", {}) if isinstance(result, dict) else {}
    print(f"[arrange] {str(job.get('id') or args.job_id)} status={args.status}")
    return 0


async def cmd_arrange_edit(args: argparse.Namespace) -> int:
    payload: dict[str, Any] = {"job_id": args.job_id}
    if args.title:
        payload["title"] = args.title
    if args.instruction:
        payload["instruction"] = args.instruction
    if args.session_strategy:
        payload["session_strategy"] = args.session_strategy
    if args.model_id:
        payload["model_id"] = args.model_id
    if args.trigger_once:
        payload["trigger"] = {"type": "once", "local_at": args.trigger_once, "timezone": args.timezone}
    elif args.trigger_daily:
        payload["trigger"] = {"type": "calendar", "frequency": "daily", "time": args.trigger_daily, "timezone": args.timezone}
    elif args.trigger_monthly:
        parts = args.trigger_monthly.split(":", 1)
        day = int(parts[0])
        time_val = parts[1] if len(parts) > 1 else "09:00"
        payload["trigger"] = {"type": "calendar", "frequency": "monthly", "day": day, "time": time_val, "timezone": args.timezone}
    elif args.trigger_event:
        payload["trigger"] = {"type": "event", "event_type": args.trigger_event}
    if len(payload) <= 1:
        print("error: no fields to update", file=sys.stderr)
        return 1
    async def op(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request("arrange.update", payload)
    result = await _invoke_live(args, op)
    job = result.get("job", {}) if isinstance(result, dict) else {}
    jid = str(job.get("id") or args.job_id)
    print(f"[arrange] {jid} updated")
    return 0


def _parse_workflow_inputs(items: list[str]) -> dict[str, Any]:
    inputs: dict[str, Any] = {}
    for item in items or []:
        if "=" not in item:
            print(f"warning: ignoring malformed --input '{item}' (expected KEY=VALUE)", file=sys.stderr)
            continue
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            continue
        parsed: Any = value
        stripped = value.strip()
        if stripped and stripped[0] in "{[" and stripped[-1] in "}]":
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                parsed = value  # keep raw string
        elif stripped.lower() in {"true", "false"}:
            parsed = stripped.lower() == "true"
        elif _looks_like_int(stripped):
            parsed = int(stripped)
        inputs[key] = parsed
    return inputs


def _looks_like_int(text: str) -> bool:
    try:
        int(text)
        return True
    except ValueError:
        return False


async def cmd_workflow_new(args: argparse.Namespace) -> int:
    with open(args.from_file, "r", encoding="utf-8") as fh:
        definition = json.loads(fh.read())
    if not isinstance(definition, dict):
        print("error: --from-file must contain a JSON object", file=sys.stderr)
        return 1
    if args.name:
        definition["name"] = args.name
    definition["work_root"] = args.work_root
    if args.exposed:
        definition["exposed"] = True
    async def op(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request("workflow.create", definition)
    result = await _invoke_live(args, op)
    wf = result.get("workflow", {}) if isinstance(result, dict) else {}
    print(f"[workflow] created {wf.get('name', '?')}")
    print(f"  nodes: {len(wf.get('nodes') or [])}  edges: {len(wf.get('edges') or [])}")
    if wf.get("exposed"):
        print(f"  exposed as tool: {wf.get('tool_name') or ''}")
    return 0


async def cmd_workflow_list(args: argparse.Namespace) -> int:
    params: dict[str, Any] = {}
    if args.work_root:
        params["work_root"] = args.work_root
    async def op(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request("workflow.list", params)
    result = await _invoke_live(args, op)
    workflows = result.get("workflows", []) if isinstance(result, dict) else []
    if isinstance(workflows, list):
        for w in workflows:
            if isinstance(w, dict):
                name = str(w.get("name") or "?")[:32]
                nodes = len(w.get("nodes") or [])
                exposed = "exposed" if w.get("exposed") else "-"
                print(f"{name:32s}  nodes={nodes:<3d} {exposed}")
    return 0


async def cmd_workflow_describe(args: argparse.Namespace) -> int:
    params: dict[str, Any] = {"name": args.name}
    if args.work_root:
        params["work_root"] = args.work_root
    async def op(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request("workflow.get", params)
    result = await _invoke_live(args, op)
    wf = result.get("workflow", {}) if isinstance(result, dict) else {}
    if isinstance(wf, dict):
        print(f"  name: {wf.get('name')}")
        print(f"  description: {wf.get('description', '')}")
        print(f"  nodes: {len(wf.get('nodes') or [])}")
        for n in (wf.get("nodes") or []):
            if isinstance(n, dict):
                print(f"    - [{n.get('kind')}] {n.get('id')} {n.get('title') or ''}")
        print(f"  edges: {len(wf.get('edges') or [])}")
        print(f"  output_port: {wf.get('output_port', '')}")
        print(f"  exposed: {wf.get('exposed', False)}")
        if wf.get("exposed"):
            print(f"  tool_name: {wf.get('tool_name', '')}")
    return 0


async def cmd_workflow_run(args: argparse.Namespace) -> int:
    payload: dict[str, Any] = {"name": args.name}
    if args.work_root:
        payload["work_root"] = args.work_root
    if args.max_steps is not None:
        payload["max_steps"] = args.max_steps
    if getattr(args, "start_node", None):
        payload["start_node"] = args.start_node
    if getattr(args, "single_node", None):
        payload["single_node"] = args.single_node
    inputs = _parse_workflow_inputs(args.input)
    if inputs:
        payload["inputs"] = inputs
    async def op(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request("workflow.run", payload)
    result = await _invoke_live(args, op)
    run = result.get("run", {}) if isinstance(result, dict) else {}
    status = str(run.get("status") or "?")
    print(f"[workflow] run status={status} run_id={run.get('run_id', '')}")
    states = run.get("node_states") or {}
    if isinstance(states, dict):
        for nid, state in states.items():
            if isinstance(state, dict):
                print(f"  {nid}: {state.get('status')} attempts={state.get('attempts')}" + (f" error={state.get('error')}" if state.get("error") else ""))
    if run.get("error"):
        print(f"  error: {run['error']}", file=sys.stderr)
    output = run.get("output")
    if output is not None:
        if isinstance(output, str) and len(output) > 500:
            print(f"  output: {output[:500]}…")
        else:
            print(f"  output: {json.dumps(output, ensure_ascii=False) if not isinstance(output, str) else output}")
    return 0 if status == "completed" else (0 if status == "paused" else 1)


async def cmd_workflow_expose(args: argparse.Namespace) -> int:
    payload: dict[str, Any] = {"name": args.name}
    if args.work_root:
        payload["work_root"] = args.work_root
    async def op(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request("workflow.expose", payload)
    result = await _invoke_live(args, op)
    wf = result.get("workflow", {}) if isinstance(result, dict) else {}
    print(f"[workflow] {wf.get('name', args.name)} exposed as tool: {wf.get('tool_name', '')}")
    return 0


async def cmd_workflow_unexpose(args: argparse.Namespace) -> int:
    payload: dict[str, Any] = {"name": args.name}
    if args.work_root:
        payload["work_root"] = args.work_root
    async def op(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request("workflow.unexpose", payload)
    result = await _invoke_live(args, op)
    wf = result.get("workflow", {}) if isinstance(result, dict) else {}
    print(f"[workflow] {wf.get('name', args.name)} unexposed")
    return 0


async def cmd_subagent_guide_show(args: argparse.Namespace) -> int:
    from lamtools_core.config.subagent_prompt import (
        DEFAULT_SUBAGENT_GUIDE,
        load_subagent_guide,
        resolve_subagent_guide_path,
    )

    work_root = args.work_root or None
    if args.scope == "project" and not work_root:
        print("error: --work-root is required for --scope project", file=sys.stderr)
        return 1
    if args.scope:
        from lamtools_core.config.subagent_prompt import subagent_guide_dirs

        dirs = subagent_guide_dirs(work_root)
        path = dirs[0] / "guide.md" if args.scope == "project" and dirs else (dirs[-1] / "guide.md" if dirs else None)
        if path is None or not path.is_file():
            print(f"[subagent] no {args.scope} guide configured; builtin shown below:")
            print(DEFAULT_SUBAGENT_GUIDE)
            return 0
        print(path.read_text(encoding="utf-8"))
        return 0
    resolved = resolve_subagent_guide_path(work_root)
    content = load_subagent_guide(work_root)
    if resolved is None:
        print("[subagent] no project/global guide configured; builtin shown below:")
    else:
        print(f"[subagent] guide from {resolved}")
    print(content)
    return 0


async def cmd_subagent_guide_set(args: argparse.Namespace) -> int:
    from lamtools_core.config.subagent_prompt import write_subagent_guide

    if args.scope == "project" and not args.work_root:
        print("error: --work-root is required for --scope project", file=sys.stderr)
        return 1
    if args.source_file == "-":
        content = sys.stdin.read()
    else:
        content = Path(args.source_file).read_text(encoding="utf-8")
    path = write_subagent_guide(content, scope=args.scope, work_root=args.work_root or None)
    print(f"[subagent] guide written to {path} (scope={args.scope})")
    return 0


async def cmd_subagent_guide_edit(args: argparse.Namespace) -> int:
    from lamtools_core.config.subagent_prompt import guide_path_for_scope

    if args.scope == "project" and not args.work_root:
        print("error: --work-root is required for --scope project", file=sys.stderr)
        return 1
    path = guide_path_for_scope(args.scope, args.work_root or None)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        from lamtools_core.config.subagent_prompt import DEFAULT_SUBAGENT_GUIDE

        path.write_text(DEFAULT_SUBAGENT_GUIDE, encoding="utf-8")
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")
    if not editor:
        print("error: $EDITOR (or $VISUAL) is not set", file=sys.stderr)
        return 1
    import shutil
    import subprocess

    exe = shutil.which(editor) or editor
    subprocess.run([exe, str(path)], check=False)
    print(f"[subagent] edited {path} (scope={args.scope})")
    return 0


async def cmd_models_list(args: argparse.Namespace) -> int:
    from lamtools_core.cli import _get_model_store

    store = _get_model_store()
    models = store.list_sync(work_root=args.work_root or None)
    if not models:
        print("[models] no model definitions configured (run 'core models import-from-db' to migrate)")
        return 0
    default_id = store.default_model_id_sync(work_root=args.work_root or None)
    print(f"[models] {len(models)} configured (default: {default_id or 'none'})")
    for model in models:
        star = "★ " if model.is_default else "  "
        print(f"{star}{model.model_id}  {model.display_name}  [{model.resolved_capability}]  provider={model.provider or '?'}  ctx={model.context_window}")
    return 0


async def cmd_models_show(args: argparse.Namespace) -> int:
    from lamtools_core.cli import _get_model_store

    store = _get_model_store()
    model = store.get_sync(args.model_id, work_root=args.work_root or None)
    if model is None:
        print(f"[models] not found: {args.model_id}", file=sys.stderr)
        return 1
    print(f"model_id:        {model.model_id}")
    print(f"display_name:    {model.display_name}")
    print(f"provider:        {model.provider or model.provider_id or '?'}")
    print(f"capability:      {model.capability or '(builtin)'} -> {model.resolved_capability}")
    print(f"context_window:  {model.context_window}")
    print(f"max_output:      {model.max_output_tokens}")
    print(f"temperature:     {model.temperature}")
    print(f"thinking:        supported={model.thinking_supported} budget={model.thinking_budget}")
    print(f"adapter_profile: {model.adapter_profile_id or '(none)'}")
    print(f"is_default:      {model.is_default}")
    print(f"source:          {model.source_path or '(none)'}")
    return 0


async def cmd_models_set(args: argparse.Namespace) -> int:
    from lamtools_core.cli import _get_model_store

    store = _get_model_store()
    model = store.get_sync(args.model_id, work_root=args.work_root or None)
    if model is None:
        print(f"[models] not found: {args.model_id}", file=sys.stderr)
        return 1
    field = args.field
    value = args.value
    if field == "capability":
        if value not in ("text", "multimodal", ""):
            print(f"[models] capability must be 'text', 'multimodal', or ''", file=sys.stderr)
            return 1
        model = replace(model, capability=value)
    elif field == "is_default":
        model = replace(model, is_default=value.lower() in ("1", "true", "yes"))
    elif field == "adapter_profile_id":
        model = replace(model, adapter_profile_id=value)
    elif field == "context_window":
        model = replace(model, context_window=int(value))
    elif field == "max_output_tokens":
        model = replace(model, max_output_tokens=int(value))
    elif field == "temperature":
        model = replace(model, temperature=float(value))
    else:
        print(f"[models] unsupported field: {field}", file=sys.stderr)
        return 1
    path = store.write(model, scope=args.scope, work_root=args.work_root or None)
    print(f"[models] set {field}={value} for {model.model_id} -> {path}")
    return 0


async def cmd_models_default(args: argparse.Namespace) -> int:
    from lamtools_core.cli import _get_model_store

    store = _get_model_store()
    model = store.get_sync(args.model_id, work_root=args.work_root or None)
    if model is None:
        print(f"[models] not found: {args.model_id}", file=sys.stderr)
        return 1
    # Clear other defaults first.
    for existing in store.list_sync(work_root=args.work_root or None):
        if existing.model_id != model.model_id and existing.is_default:
            store.write(replace(existing, is_default=False), scope=args.scope, work_root=args.work_root or None)
    path = store.write(replace(model, is_default=True), scope=args.scope, work_root=args.work_root or None)
    print(f"[models] default set to {model.model_id} -> {path}")
    return 0


async def cmd_models_import_from_db(args: argparse.Namespace) -> int:
    from lamtools_core.config.migrate_models import migrate_models_from_db

    count, paths = migrate_models_from_db(
        Path(args.config_db),
        work_root=args.work_root or None,
        scope=args.scope,
        force=args.force,
    )
    print(f"[models] exported {count} models to {args.scope} scope")
    for path in paths:
        print(f"  {path}")
    return 0


def _loadtools_for_cli() -> tuple[LoadTools, Path, bool]:
    """Load the effective mode tool-sets: config file when present, else built-in."""
    from lamtools_core.config.root import core_config_file
    from lamtools_core.tool.loadtools import LoadTools, default_load_tools, load_loadtools

    path = core_config_file("loadtools.jsonc")
    if path.is_file():
        loaded = load_loadtools(path)
        if loaded:
            return loaded, path, True
    return default_load_tools(), path, False


def _imagegen_db(args: argparse.Namespace) -> sqlite3.Connection | None:
    """Open the config database (lamtools.db) where app_settings lives."""
    try:
        con = sqlite3.connect(_resolve_config_db(getattr(args, "config_db", "") or None))
        con.row_factory = sqlite3.Row
        return con
    except (FileNotFoundError, sqlite3.OperationalError) as exc:
        print(f"[imagegen] cannot open config database: {exc}", file=sys.stderr)
        return None


def _imagegen_settings(con: sqlite3.Connection) -> dict[str, Any]:
    try:
        row = con.execute("select value from app_settings where namespace=?", ("core.imagegen",)).fetchone()
    except sqlite3.OperationalError:
        return {}
    return _json_dict(row["value"] if row is not None else None)


def _mask_api_key(api_key: str) -> str:
    if not api_key:
        return ""
    if len(api_key) > 8:
        return api_key[:4] + "****" + api_key[-4:]
    return "****"


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


async def cmd_imagegen_show(args: argparse.Namespace) -> int:
    con = _imagegen_db(args)
    if con is None:
        return 1
    try:
        value = _imagegen_settings(con)
    finally:
        con.close()
    enabled = bool(value.get("enabled"))
    print(f"enabled:  {'yes' if enabled else 'no'}")
    print(f"api_url:  {value.get('api_url') or '(未配置)'}")
    print(f"api_key:  {_mask_api_key(str(value.get('api_key') or '')) or '(未配置)'}")
    print(f"model:    {value.get('model') or '(默认)'}")
    print("说明:     未启用时 generate_image 工具不会上传到工具集（execute 模式留空=全部工具），模型调用会被拦截")
    return 0


async def cmd_imagegen_config(args: argparse.Namespace) -> int:
    con = _imagegen_db(args)
    if con is None:
        return 1
    try:
        value = _imagegen_settings(con)
        changed = False
        if args.enabled is not None:
            value["enabled"] = args.enabled == "true"
            changed = True
        if args.api_url is not None:
            value["api_url"] = args.api_url.strip()
            changed = True
        if args.api_key is not None:
            value["api_key"] = args.api_key.strip()
            changed = True
        if args.model is not None:
            value["model"] = args.model.strip()
            changed = True
        if not changed:
            print("error: nothing to change (pass --enabled / --api-url / --api-key / --model)", file=sys.stderr)
            return 1
        con.execute(
            "insert into app_settings(namespace, value, updated_at) values(?, ?, ?) "
            "on conflict(namespace) do update set value = excluded.value, updated_at = excluded.updated_at",
            ("core.imagegen", json.dumps(value, ensure_ascii=False), _now_iso()),
        )
        con.commit()
    except sqlite3.OperationalError as exc:
        print(f"[imagegen] cannot update settings: {exc}", file=sys.stderr)
        return 1
    finally:
        con.close()
    print(f"[imagegen] saved: enabled={bool(value.get('enabled'))} api_url={value.get('api_url') or ''} "
          f"api_key={_mask_api_key(str(value.get('api_key') or ''))} model={value.get('model') or ''}")
    return 0


def _artifact_registry_for_cli(work_root: str) -> ArtifactRegistry:
    from lamtools_core.artifact import ArtifactRegistry

    root = Path(work_root).resolve() if work_root else Path.cwd().resolve()
    return ArtifactRegistry(root)


def _artifact_work_root(args: argparse.Namespace) -> str:
    return str(getattr(args, "work_root", "") or "")


def _format_artifact(record: Any, *, with_prompt: bool = False) -> str:
    marker = "🗑" if record.deleted else ("🧊" if record.source == "user_upload" else "✨")
    line = (
        f"{marker} {record.artifact_id[:8]}  {record.kind:<8} {record.name}  "
        f"[{record.source}] {record.created_at or '-'}"
    )
    if record.parent_ids:
        line += f"  parents={','.join(p[:8] for p in record.parent_ids)}"
    if with_prompt and record.prompt:
        line += f"\n    prompt: {record.prompt[:200]}"
    return line


async def cmd_artifact_list(args: argparse.Namespace) -> int:
    registry = _artifact_registry_for_cli(_artifact_work_root(args))
    records = registry.list(include_deleted=bool(args.include_deleted))
    if not records:
        print(f"[artifact] 无任何 artifact（registry: {registry.root}）")
        return 0
    print(f"[artifact] {len(records)} 个（{registry.root}）")
    for record in records:
        print(_format_artifact(record, with_prompt=True))
    return 0


async def cmd_artifact_show(args: argparse.Namespace) -> int:
    registry = _artifact_registry_for_cli(_artifact_work_root(args))
    record = registry.get(args.artifact_id)
    if record is None:
        print(f"[artifact] not found: {args.artifact_id}", file=sys.stderr)
        return 1
    print(f"artifact_id: {record.artifact_id}")
    print(f"kind:        {record.kind}")
    print(f"mime_type:   {record.mime_type}")
    print(f"name:        {record.name}")
    print(f"path:        {record.path}")
    print(f"source:      {record.source}")
    print(f"prompt:      {record.prompt or '-'}")
    print(f"parent_ids:  {', '.join(record.parent_ids) or '-'}")
    print(f"children_ids:{', '.join(record.children_ids) or '-'}")
    print(f"created_at:  {record.created_at or '-'}")
    print(f"deleted:     {record.deleted}")
    return 0


async def cmd_artifact_delete(args: argparse.Namespace) -> int:
    registry = _artifact_registry_for_cli(_artifact_work_root(args))
    deleted = registry.soft_delete(args.artifact_ids)
    print(f"[artifact] 已软删 {deleted} 个（manifest 保留，id 不清理）")
    return 0


async def cmd_loadtools_show(args: argparse.Namespace) -> int:
    modes, path, from_config = _loadtools_for_cli()
    source = "config" if from_config else "builtin"
    print(f"[loadtools] source={source}  file={path}")
    for name, mode in modes.items():
        tool_text = ", ".join(mode.tools) if mode.tools else "(all tools — no limit)"
        print(f"  {name}: {mode.description or '(no description)'}")
        print(f"    tools: {tool_text}")
    return 0


async def cmd_loadtools_edit_mode(args: argparse.Namespace) -> int:
    from lamtools_core.tool.loadtools import LoadToolMode, serialize_loadtools

    modes, path, _ = _loadtools_for_cli()
    name = args.mode.strip()
    if not name:
        print("error: --mode is required", file=sys.stderr)
        return 1
    if args.no_limit:
        tools: list[str] = []
    elif args.tools.strip():
        tools = [t.strip() for t in args.tools.split(",") if t.strip()]
    else:
        existing = modes.get(name)
        tools = list(existing.tools) if existing is not None else []
    description = args.description.strip() or (modes.get(name).description if modes.get(name) else "")
    modes[name] = LoadToolMode(description=description, tools=tools)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(serialize_loadtools(modes), encoding="utf-8")
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"[loadtools] mode '{name}' saved to {path}")
    return 0


async def cmd_loadtools_delete_mode(args: argparse.Namespace) -> int:
    from lamtools_core.tool.loadtools import serialize_loadtools

    modes, path, from_config = _loadtools_for_cli()
    name = args.mode.strip()
    if name not in modes:
        print(f"error: mode '{name}' not found", file=sys.stderr)
        return 1
    del modes[name]
    if not modes:
        print("error: cannot delete the last mode", file=sys.stderr)
        return 1
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(serialize_loadtools(modes), encoding="utf-8")
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"[loadtools] mode '{name}' deleted; file={path}")
    return 0


async def cmd_memory_get(args: argparse.Namespace) -> int:
    from lamtools_core.config.root import core_config_file

    path = core_config_file("memory.md")
    if not path.is_file():
        print("[memory] (no global memory.md yet)", flush=True)
        return 0
    print(path.read_text(encoding="utf-8", errors="replace"), end="")
    return 0


async def cmd_memory_set(args: argparse.Namespace) -> int:
    from lamtools_core.config.root import core_config_file

    if args.source_file == "-":
        content = sys.stdin.read()
    else:
        try:
            content = Path(args.source_file).read_text(encoding="utf-8")
        except OSError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    path = core_config_file("memory.md")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"[memory] saved {len(content)} chars to {path}")
    return 0


async def cmd_load_context_get(args: argparse.Namespace) -> int:
    from lamtools_core.app.project_context import ContextConfig
    from lamtools_core.config.root import core_config_file

    path = core_config_file("load_context.jsonc")
    config = ContextConfig.from_file(path) if path.is_file() else None
    print(json.dumps(
        {
            "path": str(path),
            "exists": config is not None,
            "addition": [dict(item) for item in config.addition] if config is not None else [],
            "except": list(config.except_files) if config is not None else [],
        },
        ensure_ascii=False,
        indent=2,
    ), flush=True)
    return 0


async def cmd_load_context_set(args: argparse.Namespace) -> int:
    import json as _json

    from lamtools_core.config.root import core_config_file

    if args.source_file == "-":
        raw_text = sys.stdin.read()
    else:
        try:
            raw_text = Path(args.source_file).read_text(encoding="utf-8")
        except OSError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    try:
        data = _json.loads(raw_text)
    except _json.JSONDecodeError as exc:
        print(f"error: invalid JSON: {exc}", file=sys.stderr)
        return 1
    if not isinstance(data, dict):
        print("error: expected a JSON object with addition/except", file=sys.stderr)
        return 1
    additions: list[dict[str, object]] = []
    for item in data.get("addition") or []:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            print("error: addition items must be objects with a string name", file=sys.stderr)
            return 1
        additions.append({
            "name": str(item["name"]).strip(),
            "priority": int(item.get("priority") or 50),
            "kind": str(item.get("kind") or "system"),
        })
    exceptions = [str(item).strip() for item in (data.get("except") or []) if isinstance(item, str) and str(item).strip()]
    path = core_config_file("load_context.jsonc")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_json.dumps({"addition": additions, "except": exceptions}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"[load-context] saved {len(additions)} additions, {len(exceptions)} exceptions to {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(asyncio.run(args.func(args)))
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _build_summary(
    *,
    result: Any,
    events: list[Any],
    model_context: dict[str, Any],
    run_dir: Path,
) -> dict[str, Any]:
    parts = [_part_summary(event) for event in events if getattr(event, "name", "") == "runtime.part"]
    reasoning = [part["content_len"] for part in parts if part["part_type"] == "reasoning"]
    text = [part["content_len"] for part in parts if part["part_type"] == "text"]
    tool_names = [
        str(part["tool_name"])
        for part in parts
        if part["part_type"] in {"tool_call", "tool_input_delta"} and part.get("tool_name")
    ]
    response_indexes = sorted({part["response_index"] for part in parts if part["response_index"] is not None})
    usage_by_round = [
        dict(event.payload.get("usage"))
        for event in events
        if getattr(event, "name", "") == "runtime.reply_delta"
        and isinstance(getattr(event, "payload", {}).get("usage"), dict)
    ]
    state = result.state
    document_path = str(state.metadata.get("document_path") or "") if state is not None else ""
    document_line_count = int(state.metadata.get("document_line_count") or 0) if state is not None else 0
    summary = {
        "ok": False,
        "model": dict(model_context),
        "result": {
            "decision": result.decision,
            "steps_count": len(result.steps),
            "run_id": result.run_id,
            "session_id": result.session_id,
            "final_message": result.message,
        },
        "proof": {
            "has_reasoning_block": any(length > 0 for length in reasoning),
            "max_reasoning_chars": max(reasoning) if reasoning else 0,
            "has_text_block": any(length > 0 for length in text),
            "max_text_chars": max(text) if text else 0,
            "has_tool_call_block": bool(tool_names),
            "tool_names": sorted(set(tool_names)),
            "response_indexes": response_indexes,
            "model_rounds_from_steps": len(result.steps),
            "usage_by_round": usage_by_round,
            "document_path": document_path,
            "document_line_count": document_line_count,
        },
        "artifacts": {"run_dir": str(run_dir)},
    }
    summary["ok"] = result.decision == "done"
    return summary


def _part_summary(event: Any) -> dict[str, Any]:
    payload = event.payload if isinstance(event.payload, dict) else {}
    return {
        "response_index": payload.get("response_index"),
        "part_type": str(payload.get("part_type") or ""),
        "status": payload.get("status"),
        "tool_name": payload.get("tool_name"),
        "content_len": len(str(payload.get("content") or "")),
    }


def _redact_event(event: Any) -> dict[str, Any]:
    data = event.to_dict()
    payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}
    if payload.get("part_type") == "reasoning":
        content = str(payload.get("content") or "")
        payload["content_len"] = len(content)
        payload["content_sha256"] = hashlib.sha256(content.encode("utf-8")).hexdigest() if content else ""
        payload.pop("content", None)
    payload.pop("raw", None)
    data["payload"] = payload
    return data


def _llm_tool_calls_from_raw(raw_tool_calls: Any) -> list[LLMToolCall]:
    calls: list[LLMToolCall] = []
    if not isinstance(raw_tool_calls, list):
        return calls
    for item in raw_tool_calls:
        if not isinstance(item, dict):
            continue
        fn = item.get("function") if isinstance(item.get("function"), dict) else {}
        args: Any = fn.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        calls.append(
            LLMToolCall(
                id=str(item.get("id") or uuid.uuid4().hex),
                name=str(fn.get("name") or ""),
                arguments=args if isinstance(args, dict) else {},
                raw=item,
            )
        )
    return calls


def _resolve_adapter_profile(config: LLMConfig, adapter_dirs: tuple[Path | str, ...]) -> dict[str, Any]:
    profiles = load_adapter_profiles_from_dirs([*_default_adapter_dirs(), *[Path(item) for item in adapter_dirs]])
    return resolve_adapter_profile_from_profiles(
        profiles,
        api_type=config.provider_api_type,
        base_url=config.base_url,
        provider_extra=config.provider_extra,
        model_extra=config.model_extra,
    )


def _default_adapter_dirs() -> list[Path]:
    dirs: list[Path] = []
    if getattr(sys, "frozen", False):
        # PyInstaller: adapter profiles are bundled under _MEIPASS/config/.
        meipass = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        dirs.append(meipass / "config" / "llm_adapters")
    else:
        dirs.append(_repo_root() / "core" / "config" / "llm_adapters")
    env_dir = os.environ.get("LAMTOOLS_LLM_ADAPTER_DIR")
    if env_dir:
        dirs.append(Path(env_dir))
    return dirs


def _resolve_config_db(value: Path | str | None) -> Path:
    if value:
        return Path(value)
    env = os.environ.get("LAMTOOLS_LLM_CONFIG_DB")
    if env:
        return Path(env)
    candidates = [
        _repo_root() / "data" / "lamtools.db",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("No LLM config database found. Pass --config-db.")


def _resolve_core_db(value: Path | str | None) -> Path:
    if value:
        return Path(value)
    env = os.environ.get("LAMTOOLS_CORE_DB")
    if env:
        return Path(env)
    return _repo_root() / "data" / "core.db"


def _resolve_cli_context_window(args: argparse.Namespace) -> int | None:
    config_db_str = getattr(args, "config_db", "") or os.environ.get("LAMTOOLS_LLM_CONFIG_DB") or ""
    model_id = getattr(args, "model_id", "") or ""
    if not config_db_str and not model_id:
        return None
    try:
        config_db = _resolve_config_db(config_db_str if config_db_str else None)
        config = load_llm_config(config_db, model_ref=model_id)
        return config.context_window if config.context_window > 0 else None
    except Exception:
        return None


def _resolve_thread_id(value: str | None) -> str:
    clean = str(value or "").strip()
    return clean or f"core-cli-{uuid.uuid4().hex[:8]}"


def _positive_timeout_or_none(value: str) -> float | None:
    timeout = float(value)
    return timeout if timeout > 0 else None


def _is_sqlite_locked_message(exc: BaseException) -> bool:
    message = str(exc).lower()
    return "database is locked" in message or "database table is locked" in message


def _model_ref_from_routing(con: sqlite3.Connection) -> str:
    try:
        row = con.execute("select value from app_settings where namespace=?", ("lamtools.modelRouting",)).fetchone()
    except sqlite3.OperationalError:
        row = None
    if row is not None:
        data = _json_dict(row["value"])
        routes = data.get("routes") if isinstance(data.get("routes"), dict) else {}
        for route_name in ("core", "default"):
            route = routes.get(route_name) if isinstance(routes.get(route_name), dict) else {}
            model_id = str(route.get("model_id") or "").strip()
            if model_id:
                return model_id
    try:
        row = con.execute("select id from llm_models order by is_default desc, created_at asc limit 1").fetchone()
    except sqlite3.OperationalError:
        row = None
    return str(row["id"] or "") if row is not None else ""


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_run_dir() -> Path:
    return _repo_root() / "tmp" / f"core-cli-run-{time.strftime('%Y%m%d-%H%M%S')}"


def _default_work_root() -> Path:
    return ensure_projects_root() / "default"


def _safe_relative_path(value: str) -> Path:
    clean = value.replace("\\", "/").lstrip("/").strip()
    path = Path(clean or "core-agent-proof.md")
    if not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        return Path("core-agent-proof.md")
    return path


def _non_empty_line_count(text: str) -> int:
    return len([line for line in text.splitlines() if line.strip()])


def _fallback_document() -> str:
    return "\n".join(f"Line {index}: Core Agent proof document." for index in range(1, 12)) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
