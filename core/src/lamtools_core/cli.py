from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sqlite3
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from lamtools_core.app.base_agent import assemble_core_agent_plugins, CoreBaseAgentConfig, CoreBaseAgentKit
from lamtools_core.app.base_agent import core_events_to_run_items
from lamtools_core.app.cli_live import CliLiveFormatter, OutputChunk, approval_decision_from_reply, watch_live_events
from lamtools_core.app.core_db import (
    list_core_sessions,
    open_core_app_db,
    persist_core_run_items,
    show_core_session,
)
from lamtools_core.app.live_client import CoreAppServerClient
from lamtools_core.event import CollectingEventSink
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
from lamtools_core.runtime import RuntimeTurnInput
from lamtools_core.tool.default_toolbox import ApprovalPolicy, build_core_toolbox

SQLITE_CONFIG_READ_TIMEOUT_SECONDS = 0.2
SQLITE_CONFIG_LOCK_RETRY_DELAYS = (0.05, 0.15)


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
    max_tokens: int = 4096
    temperature: float = 0.2
    approval_policy: ApprovalPolicy = "require"
    raw: bool = False
    verbose: bool = False

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
        max_tokens: int,
        temperature: float,
    ) -> None:
        self.config = config
        self.adapter_profile = adapter_profile
        self.thinking_enabled = thinking_enabled
        self.thinking_budget = thinking_budget
        self.max_tokens = max_tokens
        self.temperature = temperature

    async def complete(self, request: LLMRequest) -> LLMResponse:
        assembled = build_profiled_openai_request(
            self._request_with_defaults(request),
            self.adapter_profile,
            thinking_enabled=self.thinking_enabled,
            thinking_budget=self.thinking_budget,
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
    model_context: dict[str, Any] = {"model_id": resolved_model_id}
    if llm_client is None:
        config_db = _resolve_config_db(options.config_db)
        config = load_llm_config(config_db, model_ref=options.model_id)
        profile = _resolve_adapter_profile(config, options.adapter_dirs)
        resolved_model_id = config.model_id
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

    sub_agent_runner = KernelSubAgentRunner(
        work_root=work_root,
        llm_client=llm_client,
        model_id=resolved_model_id,
        approval_policy=options.approval_policy,
        loaded_skill_roots=set(plugin_assembly["skill_roots"]),
        agent_roots=tuple(plugin_assembly.get("agent_roots") or ()),
        mcp_caller=mcp_registry if mcp_tool_specs else None,
        mcp_tool_specs=mcp_tool_specs,
    )
    toolbox = build_core_toolbox(
        work_root=work_root,
        approval_policy=options.approval_policy,
        loaded_skill_roots=set(plugin_assembly["skill_roots"]),
        mcp_caller=mcp_registry if mcp_tool_specs else None,
        mcp_tool_specs=mcp_tool_specs,
        sub_agent_runner=sub_agent_runner,
    )
    kit = CoreBaseAgentKit(
        work_root=work_root,
        config=CoreBaseAgentConfig(
            model_id=resolved_model_id,
            instructions="You are LamTools Core Agent, a standalone general-purpose agent runtime.",
            temperature=options.temperature,
            max_tokens=options.max_tokens,
            thinking_enabled=options.thinking_enabled,
            thinking_budget=options.thinking_budget,
            approval_policy=options.approval_policy,
        ),
        toolbox=toolbox,
    )
    core_db = await open_core_app_db(core_db_path)
    try:
        kernel = CoreLoopKernel(
            kit=kit,
            llm_client=llm_client,
            state_store=core_db.runtime_state_store,
            event_sink=sink,
            policy=LoopPolicy(model_timeout_seconds=360, model_retries=3, persist_steps=True),
            hook_engine=plugin_assembly["hook_engine"],
        )
        result = await kernel.run(
            RuntimeTurnInput(
                user_message=options.message,
                metadata={
                    "session_id": thread_id,
                    "model_id": resolved_model_id,
                    "thinking_enabled": options.thinking_enabled,
                    "thinking_budget": options.thinking_budget,
                    "shallow_thinking_enabled": options.shallow_thinking_enabled,
                },
            )
        )
        await persist_core_run_items(core_db, core_events_to_run_items(sink.events, thread_id=result.session_id))
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


def list_llm_model_configs(config_db: Path) -> list[dict[str, Any]]:
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
    return LLMConfig(
        provider_name=str(data.get("provider_name") or ""),
        provider_api_type=str(data.get("provider_api_type") or "openai"),
        base_url=str(data.get("base_url") or "").rstrip("/"),
        api_key=str(data.get("api_key") or ""),
        model_record_id=str(data.get("id") or ""),
        model_id=str(data.get("model_id") or ""),
        display_name=str(data.get("display_name") or ""),
        context_window=int(data.get("context_window") or 0),
        max_output_tokens=int(data.get("max_output_tokens") or 4096),
        temperature=float(data.get("temperature") or 0.2),
        thinking_supported=bool(data.get("thinking_supported")),
        thinking_budget=int(data.get("thinking_budget") or 10000),
        provider_extra=_json_dict(data.get("provider_extra")),
        model_extra=_json_dict(data.get("model_extra")),
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
    serve.add_argument("--thinking", choices=("enabled", "disabled"), default="enabled")
    serve.add_argument("--thinking-budget", type=int, default=10000)
    serve.add_argument("--max-tokens", type=int, default=4096)
    serve.add_argument("--temperature", type=float, default=0.2)
    serve.add_argument("--raw", action="store_true")
    serve.set_defaults(func=cmd_serve)

    run = sub.add_parser("run", help="Start a Core Agent task")
    run.add_argument("message", nargs="+")
    run.add_argument("--model-id", default="", help="Model record id, provider model id, or display name")
    run.add_argument("--config-db", default="", help="SQLite config database containing llm_providers/llm_models")
    run.add_argument("--core-db", default="", help="Core-owned SQLite runtime database")
    run.add_argument("--thread-id", default="", help="Stable Core thread/session id")
    run.add_argument("--work-root", "--project", dest="work_root", default="")
    run.add_argument("--run-dir", default="")
    run.add_argument("--adapter-dir", action="append", default=[])
    run.add_argument("--plugin-root", action="append", default=[], help="Plugin root containing */plugin.json")
    run.add_argument("--thinking-budget", type=int, default=10000)
    run.add_argument("--no-thinking", action="store_true")
    run.add_argument("--shallow-thinking", action="store_true", help="Require a prompt-based shallow thinking block")
    run.add_argument("--auto-approve", action="store_true", help="Run approval-gated Core tools without prompting")
    run.add_argument("--max-tokens", type=int, default=4096)
    run.add_argument("--temperature", type=float, default=0.2)
    run.add_argument("--raw", action="store_true")
    run.add_argument("--verbose", action="store_true")
    run.set_defaults(func=cmd_run)

    watch = sub.add_parser("watch", help="Watch a Core app-server thread")
    watch.add_argument("thread_id")
    watch.add_argument("--base-url", default=os.environ.get("LAMTOOLS_CORE_API_URL", "http://127.0.0.1:6173"))
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
    _add_live_connection_arguments(start)
    start.add_argument("--work-root", "--project", dest="work_root", default="")
    start.add_argument("--model-id", default="")
    start.add_argument("--thinking", choices=("enabled", "disabled"), default="enabled")
    start.add_argument("--thinking-budget", type=int, default=10000)
    start.add_argument("--shallow", action="store_true")
    start.add_argument("--approval-policy", choices=("require", "auto_approve"), default="require")
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

    project = sub.add_parser("project", help="Manage Core project workspaces")
    project_sub = project.add_subparsers(dest="project_command", required=True)
    project_list = project_sub.add_parser("list", help="List project workspaces")
    project_list.add_argument("--core-db", default="", help="Core-owned SQLite runtime database")
    project_list.set_defaults(func=cmd_project_list)
    project_create = project_sub.add_parser("create", help="Create or reuse a project workspace")
    project_create.add_argument("work_root")
    project_create.add_argument("--name", default="")
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
    return parser


def _add_live_connection_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--base-url", default=os.environ.get("LAMTOOLS_CORE_API_URL", "http://127.0.0.1:6173"))
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
    try:
        import uvicorn
    except ImportError as exc:
        raise RuntimeError("serve requires uvicorn; install the Core HTTP server dependencies") from exc
    from lamtools_core.app.http_agent_app import create_core_agent_http_app

    app = create_core_agent_http_app(
        model_id=args.model_id,
        config_db=args.config_db or None,
        core_db=args.core_db or None,
        data_dir=args.data_dir or None,
        work_root=args.work_root or None,
        thinking_enabled=args.thinking == "enabled",
        thinking_budget=args.thinking_budget,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
    )
    url = f"http://{args.host}:{args.port}"
    _print_live_result(args, {"url": url}, f"serving {url}")
    server = uvicorn.Server(uvicorn.Config(app, host=args.host, port=args.port))
    await server.serve()
    return 0


async def cmd_start(args: argparse.Namespace) -> int:
    result = await _invoke_live(
        args,
        lambda client: client.start_turn(
            thread_id=args.thread_id,
            input_items=[{"type": "text", "text": " ".join(args.message)}],
            work_root=args.work_root,
            model_id=args.model_id or None,
            thinking_enabled=args.thinking == "enabled",
            thinking_budget=args.thinking_budget,
            shallow_thinking_enabled=bool(args.shallow),
            approval_policy=args.approval_policy,
            client_message_id=args.client_message_id or None,
        ),
    )
    _print_live_result(args, result, f"started {args.thread_id}")
    return await cmd_watch(args) if args.watch else 0


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


async def cmd_run(args: argparse.Namespace) -> int:
    thread_id = _resolve_thread_id(args.thread_id)
    if not args.raw:
        print(f"[session] {thread_id}", flush=True)
    summary = await run_core_cli_task(
        CoreCliRunOptions(
            message=" ".join(args.message),
            model_id=args.model_id,
            config_db=args.config_db or None,
            core_db=args.core_db or None,
            thread_id=thread_id,
            work_root=args.work_root or _default_work_root(),
            run_dir=args.run_dir or None,
            adapter_dirs=tuple(args.adapter_dir or ()),
            plugin_roots=tuple(args.plugin_root or ()),
            thinking_enabled=not bool(args.no_thinking),
            thinking_budget=args.thinking_budget,
            shallow_thinking_enabled=bool(args.shallow_thinking),
            max_tokens=args.max_tokens,
            temperature=args.temperature,
            approval_policy="auto_approve" if bool(args.auto_approve) else "require",
            raw=bool(args.raw),
            verbose=bool(args.verbose),
        )
    )
    if args.raw:
        print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    else:
        print(f"[done] decision={summary['result']['decision']} steps={summary['result']['steps_count']}")
        print(f"[model] {summary['model'].get('display_name') or summary['model'].get('model_id')}")
        proof = summary["proof"]
        print(
            "[proof] "
            f"thinking={proof['has_reasoning_block']} "
            f"text={proof['has_text_block']} "
            f"tool={','.join(proof['tool_names']) or '-'} "
            f"rounds={len(proof['response_indexes'])}"
        )
        if proof.get("document_path"):
            print(f"[file] {proof['document_path']} lines={proof['document_line_count']}")
        print(f"[summary] {summary['artifacts']['summary_json']}")
    return 0 if summary.get("ok") else 2


async def cmd_watch(args: argparse.Namespace) -> int:
    formatter = CliLiveFormatter(
        verbose=bool(args.verbose),
        heartbeat_interval=int(args.heartbeat_interval or 30),
    )

    def output(chunk: OutputChunk) -> None:
        print(str(chunk), end=chunk.end, flush=chunk.flush)

    approval = None
    approval_decision = None
    if args.approval_decision:
        approval = lambda: args.approval_decision
        approval_decision = lambda value: value
    elif not args.raw and (args.interactive_decisions or sys.stdin.isatty()):
        approval = lambda: asyncio.to_thread(input, "reply> ")
        approval_decision = approval_decision_from_reply

    if not args.raw:
        output(OutputChunk(formatter.line("watch", args.thread_id)))
    result = await watch_live_events(
        client_factory=lambda: CoreAppServerClient(args.base_url, path=args.ws_path, token=args.token),
        thread_id=args.thread_id,
        formatter=formatter,
        output=output,
        raw=bool(args.raw),
        approval=approval,
        approval_decision=approval_decision,
        event_timeout=args.event_timeout,
        max_reconnects=int(args.max_reconnects),
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
    root = _repo_root()
    dirs = [root / "core" / "llm_adapters"]
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
        row = con.execute("select id from llm_models order by created_at asc limit 1").fetchone()
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
    return _repo_root()


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
