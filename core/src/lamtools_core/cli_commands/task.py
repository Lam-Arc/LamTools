"""Local task execution, task commands and live event watching."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import argparse
import asyncio
import json
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from lamtools_core.app.base_agent import (
    CoreBaseAgentConfig,
    CoreBaseAgentKit,
    DEFAULT_CORE_INSTRUCTIONS,
    assemble_core_agent_plugins,
    core_events_to_run_items,
)
from lamtools_core.app.cli_live import (
    CliLiveFormatter,
    OutputChunk,
    approval_decision_from_reply,
    watch_live_events,
)
from lamtools_core.app.core_db import open_core_app_db, persist_core_run_items
from lamtools_core.app.live_client import CoreAppServerClient
from lamtools_core.app.runtime_permissions import (
    load_global_runtime_controls,
    resolve_session_permissions,
    runtime_snapshot as build_runtime_snapshot,
    session_runtime_preferences,
)
from lamtools_core.cli_reporting import _build_summary, _redact_event, _should_collect_cli_event
from lamtools_core.event import CollectingEventSink, RunItemEvent
from lamtools_core.export import build_handoff_context
from lamtools_core.kernel import CoreLoopKernel, LoopPolicy
from lamtools_core.llm.http_client import CoreHttpLLMClient
from lamtools_core.llm.reasoning import reasoning_level_from_legacy
from lamtools_core.llm.shallow_thinking import ShallowThinkingClient
from lamtools_core.runtime import RuntimeTurnInput
from lamtools_core.tool.default_toolbox import ApprovalPolicy, build_core_toolbox


@dataclass(frozen=True)
class CoreCliRunOptions:
    message: str
    model_id: str = ""
    profile: str = ""
    profile_tools: str = ""
    profile_approval: str = ""
    profile_budget_calls: int | None = None
    profile_budget_tokens: int | None = None
    profile_mode: str = ""
    work_root: Path | str = "."
    run_dir: Path | str | None = None
    core_db: Path | str | None = None
    thread_id: str = ""
    adapter_dirs: tuple[Path | str, ...] = ()
    plugin_roots: tuple[Path | str, ...] = ()
    reasoning_level: str = ""
    thinking_enabled: bool = True
    thinking_budget: int = 10000
    shallow_thinking_enabled: bool = False
    max_tokens: int | None = None
    compact_trigger_tokens: int | None = None
    compact_limit_tokens: int | None = None
    temperature: float = 0.2
    # ``None`` means "use the frozen Session preference".  Keeping the
    # absence distinct from ``require`` prevents repeated CLI runs from
    # silently resetting an existing Session's Composer choice.
    approval_policy: ApprovalPolicy | None = None
    permission_preset: str | None = None
    # Allow file tools to access paths outside work_root (default: read from
    # settings core.runtimeControls.allow_access_outside_workdir).
    allow_outside_workdir: bool | None = None
    raw: bool = False
    verbose: bool = False
    # Optional plugin mode and host services.  Plugin-specific behavior is
    # contributed by manifests and runtime handles, not named by Core.
    active_mode: str = ""
    instructions: str = ""
    plugin_services: dict[str, Any] = field(default_factory=dict)
    operation_catalog: Any = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "work_root", Path(self.work_root))
        if self.run_dir is not None:
            object.__setattr__(self, "run_dir", Path(self.run_dir))
        if self.core_db is not None:
            object.__setattr__(self, "core_db", Path(self.core_db))
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


async def run_core_cli_task(
    options: CoreCliRunOptions,
    *,
    llm_client: Any | None = None,
) -> dict[str, Any]:
    from .config import _default_run_dir, _resolve_adapter_profile, _resolve_core_db, _resolve_thread_id, load_llm_config
    run_dir = Path(options.run_dir) if options.run_dir is not None else _default_run_dir()
    work_root = Path(options.work_root)
    core_db_path = _resolve_core_db(options.core_db)
    thread_id = _resolve_thread_id(options.thread_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    work_root.mkdir(parents=True, exist_ok=True)

    profile_spec = None
    if getattr(options, "profile", ""):
        from lamtools_core.plugin_system import PluginHost, resolve_profile
        from lamtools_core.plugin_system.paths import default_plugin_roots

        host = PluginHost(
            roots=default_plugin_roots(work_root),
            state_path=run_dir / "plugin-system.jsonc",
        )
        profile_spec = resolve_profile(host.discover(), options.profile)
        # user:“运行档声明模型场景”+场景解析提前到模型配置装载之前。
        if profile_spec.model_scene and not resolved_model_id:
            from lamtools_core.config.model_selection import resolve_scene_model

            resolved_model_id = resolve_scene_model(profile_spec.model_scene).model_id
    # user:"profile 支持后续参数与 CLI 即席定义"+声明档为基础，CLI 参数覆盖；
    # --tools 即席构造（无需声明档）；--mode 走既有 active_mode 机制收窄（两者相交）。
    has_cli_override = bool(
        options.profile_tools
        or options.profile_approval
        or options.profile_budget_calls is not None
        or options.profile_budget_tokens is not None
    )
    if options.profile_tools or has_cli_override or profile_spec is not None:
        from lamtools_core.plugin_system.profiles import ProfileBudget, ProfileSpec

        base = profile_spec
        tools = (
            tuple(item.strip() for item in options.profile_tools.split(",") if item.strip())
            if options.profile_tools
            else (base.tools if base is not None else ())
        )
        if tools or base is not None:
            approval = options.profile_approval or (base.approval if base is not None else "auto")
            budget = ProfileBudget(
                max_tool_calls=(
                    options.profile_budget_calls
                    if options.profile_budget_calls is not None
                    else (base.budget.max_tool_calls if base is not None else None)
                ),
                max_tokens=(
                    options.profile_budget_tokens
                    if options.profile_budget_tokens is not None
                    else (base.budget.max_tokens if base is not None else None)
                ),
            )
            profile_spec = ProfileSpec(
                full_name=(base.full_name if base is not None else "cli:adhoc"),
                plugin=(base.plugin if base is not None else "cli"),
                profile=(base.profile if base is not None else "adhoc"),
                title=(base.title if base is not None else "CLI ad-hoc run profile"),
                tools=tools,
                approval=approval,
                model_scene=(base.model_scene if base is not None else ""),
                budget=budget,
            )
    resolved_model_id = options.model_id
    context_window_tokens: int | None = None
    max_output_tokens = options.max_tokens
    model_context: dict[str, Any] = {"model_id": resolved_model_id}
    effective_reasoning_level = reasoning_level_from_legacy(
        reasoning_level=options.reasoning_level,
        thinking_enabled=options.thinking_enabled,
        fallback="high" if options.thinking_enabled else "off",
    )
    if llm_client is None:
        config = load_llm_config(model_ref=options.model_id)
        profile = _resolve_adapter_profile(config, options.adapter_dirs)
        resolved_model_id = config.model_id
        context_window_tokens = config.context_window or None
        max_output_tokens = options.max_tokens or config.max_output_tokens
        model_context = {
            "model_record_id": config.model_record_id,
            "model_id": config.model_id,
            "display_name": config.display_name,
            "provider": config.provider_name,
            "reasoning_level": effective_reasoning_level,
            "thinking_enabled": options.thinking_enabled,
            "thinking_budget": options.thinking_budget or config.thinking_budget,
            "shallow_thinking_enabled": options.shallow_thinking_enabled,
        }
        llm_client = CoreHttpLLMClient(
            config=config,
            adapter_profile=profile,
            thinking_enabled=options.thinking_enabled,
            thinking_budget=options.thinking_budget or config.thinking_budget,
            reasoning_effort=config.reasoning_effort,
            reasoning_level=effective_reasoning_level,
            max_tokens=max_output_tokens,
            temperature=options.temperature if options.temperature is not None else config.temperature,
        )
    if options.shallow_thinking_enabled:
        llm_client = ShallowThinkingClient(llm_client)


    # ``run-local`` has no live consumer for token-by-token stream updates.
    # Keeping those transient events in memory made the diagnostic artifact
    # grow quadratically when tool arguments were streamed as cumulative
    # snapshots.  The app host already excludes the same events from durable
    # persistence; the CLI should retain only the authoritative checkpoints.
    sink = CollectingEventSink(should_collect=_should_collect_cli_event)
    # Resolve the same permission preset used by the live host.  The CLI is a
    # first-class client, so it also freezes one expanded snapshot for this
    # run instead of letting individual tools reinterpret the flags.
    global_controls = load_global_runtime_controls()
    from lamtools_core.config.root import core_config_file
    from lamtools_core.tool.approval import load_access_tools

    tier_tools = load_access_tools(core_config_file("access_tools.jsonc"))
    core_db = await open_core_app_db(core_db_path)

    # Establish/read the Session before resolving runtime permissions.  Global
    # runtimeControls initialize new Sessions only; an existing Session owns
    # its persisted preference until the caller explicitly changes it.
    _, session, _ = await core_db.project_store.ensure_session(
        work_root,
        thread_id,
        title=options.message,
    )
    # One session has one runtime; a second process writing the same row would
    # interleave two runs.  Refuse when another live process owns it, and let a
    # row left behind by a crashed run be adopted (the kernel marks the takeover
    # in state metadata on its first save).
    live_owner = await core_db.runtime_state_store.live_owner(thread_id)
    if live_owner:
        raise RuntimeError(
            f"会话 {thread_id} 正被另一个进程运行（pid={live_owner.get('pid')}，"
            f"主机={live_owner.get('host')}）；请等它结束，或换一个 --thread-id。"
        )
    session_preferences = session_runtime_preferences(
        session.metadata,
        global_controls=global_controls,
    )
    if options.allow_outside_workdir is None:
        base_allow_outside = bool(session_preferences["base_allow_access_outside_workdir"])
    else:
        base_allow_outside = bool(options.allow_outside_workdir)
    if options.permission_preset is not None:
        requested_preset = options.permission_preset
    elif options.approval_policy == "auto_approve":
        requested_preset = "auto"
    else:
        requested_preset = str(session_preferences["permission_preset"])
    resolved_permissions = resolve_session_permissions(
        preset=requested_preset,
        base_tier=session_preferences["base_tier"],
        base_allow_access_outside_workdir=base_allow_outside,
        tier_tools=tier_tools,
        global_controls=global_controls,
    )
    allow_outside_workdir = resolved_permissions.allow_access_outside_workdir

    from lamtools_core.plugin_system.context import PluginContext
    from lamtools_core.runtime import RuntimeTaskRegistry
    from lamtools_core.tool.approval import ApprovalGate
    from lamtools_core.tool.permission import ASK_USER

    runtime_task_registry = RuntimeTaskRegistry()
    plugin_permission_service = ApprovalGate(
        work_root=work_root,
        tool_permissions={"run_command": ASK_USER},
        allow_access_outside_workdir=allow_outside_workdir,
    )

    plugin_context = PluginContext(
        work_root=work_root,
        data_dir=run_dir,
        permission_service=plugin_permission_service,
        runtime_task_registry=runtime_task_registry,
        services=dict(options.plugin_services),
    )
    plugin_assembly = assemble_core_agent_plugins(
        data_dir=run_dir,
        work_root=work_root,
        plugin_roots=options.plugin_roots or None,
        context=plugin_context,
    )
    from lamtools_core.mcp import MCPToolRegistry

    mcp_registry = MCPToolRegistry(work_root, config_files=plugin_assembly.get("mcp_files") or [])
    # user:“通过 command 运行”+(本地 CLI 代理也不预加载和注入 MCP 协议工具)。
    from lamtools_core.mcp.command_service import MCPCommandService
    mcp_service = MCPCommandService(mcp_registry)
    if plugin_assembly["hook_engine"] is not None:
        plugin_assembly["hook_engine"].set_mcp_caller(mcp_service)
    from lamtools_core.tool.sub_agent_runner import KernelSubAgentRunner
    from lamtools_core.skill_runtime import create_skill_runtime

    skill_runtime = create_skill_runtime(
        plugin_skill_roots=plugin_assembly.get("skill_roots") or []
    )
    skill_roots = set(skill_runtime.roots)

    async def capture_model_context(state: Any, request: Any) -> None:
        payload = build_handoff_context(getattr(request, "messages", []))
        await core_db.handoff_context_store.save(state.session_id, payload)

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
    core_instructions = DEFAULT_CORE_INSTRUCTIONS
    if options.instructions:
        core_instructions = options.instructions
    context_window_tokens = int(getattr(llm_client, "context_window", 0) or 0) or context_window_tokens
    runtime_snapshot = build_runtime_snapshot(
        permissions=resolved_permissions,
        active_mode=options.active_mode or None,
        model_id=resolved_model_id,
        reasoning_level=effective_reasoning_level,
        thinking_enabled=options.thinking_enabled,
        thinking_budget=options.thinking_budget,
        shallow_thinking_enabled=options.shallow_thinking_enabled,
        context_window_tokens=context_window_tokens,
        max_tokens=max_output_tokens,
        temperature=options.temperature,
        compact_trigger_tokens=options.compact_trigger_tokens,
        compact_limit_tokens=options.compact_limit_tokens,
    )

    sub_agent_runner = KernelSubAgentRunner(
        work_root=work_root,
        llm_client=llm_client,
        model_id=resolved_model_id,
        instructions=core_instructions,
        temperature=options.temperature,
        max_tokens=max_output_tokens,
        reasoning_level=effective_reasoning_level,
        thinking_enabled=options.thinking_enabled,
        thinking_budget=options.thinking_budget,
        approval_policy=resolved_permissions.approval_policy,
        permission_preset=resolved_permissions.permission_preset,
        active_tier=resolved_permissions.active_tier,
        tier_tools=resolved_permissions.tier_tools,
        runtime_snapshot=runtime_snapshot,
        loaded_skill_roots=skill_roots,
        skill_registry=skill_runtime.registry,
        mcp_config_files=plugin_assembly.get("mcp_files") or [],
        context_window_tokens=context_window_tokens,
        compact_trigger_tokens=options.compact_trigger_tokens,
        compact_limit_tokens=options.compact_limit_tokens,
        state_store=core_db.runtime_state_store,
        session_prefix=thread_id,
        parent_event_sink=sink,
        model_context_sink=capture_model_context,
    )

    # Every local run uses the same plugin operation loader as the HTTP app.
    # Reuse the already-loaded backend handles so one plugin owns one runtime
    # instance (and one store) for the whole task.
    operation_catalog = options.operation_catalog
    if operation_catalog is None:
        from lamtools_core.app.base_agent import build_core_plugin_operation_catalog

        operation_catalog = build_core_plugin_operation_catalog(
            data_dir=run_dir,
            work_root=work_root,
            plugin_roots=options.plugin_roots or None,
            context=plugin_context,
            plugin_runtimes=plugin_assembly.get("plugin_runtimes") or [],
        )
    plugin_context.operation_catalog = operation_catalog
    plugin_context.llm_client = llm_client
    plugin_context.set_service("sub_agent_runner", sub_agent_runner)
    plugin_context.set_service("sub_agent_runner_factory", lambda: sub_agent_runner)
    for runtime_handle in plugin_assembly.get("plugin_runtimes") or []:
        runner = getattr(runtime_handle.value, "runner", None)
        if runner is not None:
            runner.sub_agent_runner = sub_agent_runner

    load_tools_obj = None
    active_mode = options.active_mode or None
    if active_mode:
        from lamtools_core.tool.loadtools import default_load_tools

        load_tools_obj = default_load_tools()

    async def execute_operation(name: str, payload: dict[str, Any], metadata: dict[str, Any]) -> Any:
        if operation_catalog is None:
            raise RuntimeError("operation catalog is not configured")
        return await operation_catalog.execute(name, payload, metadata=metadata)

    # user:“换芯声明”+声明工具在装配期已补全，这里直接归并。
    plugin_tool_specs: list[Any] = list(plugin_assembly.get("plugin_runtime_specs") or [])

    toolbox = build_core_toolbox(
        work_root=work_root,
        approval_policy=resolved_permissions.approval_policy,
        active_tier=resolved_permissions.active_tier,
        tier_tools=resolved_permissions.tier_tools,
        loaded_skill_roots=skill_roots,
        skill_registry=skill_runtime.registry,
        mcp_service=mcp_service,
        sub_agent_runner=sub_agent_runner,
        operation_executor=execute_operation if operation_catalog is not None else None,
        load_tools=load_tools_obj,
        active_mode=active_mode,
        plugin_tool_providers=plugin_assembly.get("plugin_tool_providers") or [],
        plugin_tool_handlers=plugin_assembly.get("plugin_tool_handlers") or {},
        plugin_tool_specs=plugin_tool_specs,
        data_dir=run_dir,
        allow_access_outside_workdir=allow_outside_workdir,
        artifact_store=getattr(core_db, "artifact_store", None),
        plugin_mode_exclusive_tools=plugin_assembly.get("plugin_mode_exclusive_tools") or {},
    )
    # user:“运行档由宿主强制”+白名单可见面、execute 拒绝、审批覆盖、预算计数。
    if profile_spec is not None:
        from lamtools_core.plugin_system.profiles import apply_profile

        apply_profile(toolbox, profile_spec)
    kit = CoreBaseAgentKit(
        work_root=work_root,
        config=CoreBaseAgentConfig(
            model_id=resolved_model_id,
            instructions=core_instructions,
            temperature=options.temperature,
            max_tokens=max_output_tokens,
            reasoning_level=effective_reasoning_level,
            thinking_enabled=options.thinking_enabled,
            thinking_budget=options.thinking_budget,
            approval_policy=resolved_permissions.approval_policy,
            active_mode=active_mode,
        ),
        toolbox=toolbox,
    )
    try:
        from lamtools_core.config.retry_store import (
            load_model_retry_config,
            loop_policy_overrides,
            retry_policy_from_config,
        )

        _retry_config = load_model_retry_config()
        kernel = CoreLoopKernel(
            kit=kit,
            llm_client=llm_client,
            state_store=core_db.runtime_state_store,
            event_sink=sink,
            policy=LoopPolicy(
                **{
                    **loop_policy_overrides(_retry_config),
                    "model_timeout_seconds": 360,
                    "persist_steps": True,
                    "context_window_tokens": context_window_tokens,
                    "compact_trigger_tokens": options.compact_trigger_tokens,
                    "compact_limit_tokens": options.compact_limit_tokens,
                    "parallel_tool_names": ("sub_agent",),
                }
            ),
            retry_policy=retry_policy_from_config(_retry_config),
            hook_engine=plugin_assembly["hook_engine"],
            model_context_sink=capture_model_context,
        )
        result = await kernel.run(
            RuntimeTurnInput(
                user_message=options.message,
                run_id=run_id,
                turn_id=turn_id,
                metadata={
                    "session_id": thread_id,
                    "model_id": resolved_model_id,
                    "reasoning_level": effective_reasoning_level,
                    "thinking_enabled": options.thinking_enabled,
                    "thinking_budget": options.thinking_budget,
                    "shallow_thinking_enabled": options.shallow_thinking_enabled,
                    "runtime_snapshot": runtime_snapshot,
                    "runtime_snapshot_fresh": True,
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
        from lamtools_core.plugin_system import shutdown_plugin_backends

        await shutdown_plugin_backends(plugin_assembly.get("plugin_runtimes") or [])
        await runtime_task_registry.shutdown()
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


async def cmd_run(args: argparse.Namespace) -> int:
    from .config import _default_work_root, _resolve_cli_context_window, _resolve_cli_max_output_tokens, _resolve_thread_id
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
    max_output_tokens = _resolve_cli_max_output_tokens(args)
    if not args.raw:
        print(f"[session] {thread_id}", flush=True)
    async def start(client: CoreAppServerClient) -> dict[str, Any]:
        reasoning_level = getattr(args, "reasoning_level", None)
        if reasoning_level is None:
            reasoning_level = "off" if bool(args.no_thinking) else "high"
        params: dict[str, Any] = {
            "thread_id": thread_id,
            "input_items": [{"type": "text", "text": " ".join(args.message)}],
            "work_root": str(args.work_root or _default_work_root()),
            "model_id": args.model_id or None,
            "goal_id": args.goal_id or None,
            "reasoning_level": reasoning_level,
            "thinking_budget": args.thinking_budget,
            "shallow_thinking_enabled": bool(args.shallow_thinking),
            "max_tokens": max_output_tokens,
            "temperature": float(args.temperature),
            "compact_trigger_tokens": compact_trigger_tokens,
            "compact_limit_tokens": compact_limit_tokens,
            "context_window_tokens": context_window_tokens,
        }
        permission_preset = getattr(args, "permission_preset", None)
        if permission_preset is not None:
            params["permission_preset"] = permission_preset
        elif bool(getattr(args, "auto_approve", False)):
            # Omit the legacy field when the user did not request it.  The
            # server then reads the existing Session preference instead of
            # resetting it to ``require``.
            params["approval_policy"] = "auto_approve"
        allow_outside = getattr(args, "allow_outside_workdir", None)
        if allow_outside is not None:
            params["allow_access_outside_workdir"] = bool(allow_outside)
        return await client.start_turn(**params)


    return await _watch_live_cli(args, thread_id=thread_id, on_connected=start)


async def cmd_run_local(args: argparse.Namespace) -> int:
    from .config import _default_work_root, _resolve_thread_id
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
        profile=getattr(args, "profile", "") or "",
        profile_tools=str(getattr(args, "tools", "") or ""),
        profile_approval=getattr(args, "profile_approval", None) or "",
        profile_budget_calls=getattr(args, "profile_budget_calls", None),
        profile_budget_tokens=getattr(args, "profile_budget_tokens", None),
        profile_mode=getattr(args, "profile_mode", "") or "",
        active_mode=getattr(args, "profile_mode", "") or "",
        work_root=args.work_root or _default_work_root(),
        run_dir=args.run_dir or None,
        core_db=args.core_db or None,
        thread_id=args.thread_id or _resolve_thread_id(""),
        adapter_dirs=(),
        plugin_roots=(),
        reasoning_level=(getattr(args, "reasoning_level", None) or ("off" if bool(args.no_thinking) else "high")),
        thinking_enabled=not bool(args.no_thinking),
        thinking_budget=args.thinking_budget,
        shallow_thinking_enabled=bool(args.shallow_thinking),
        max_tokens=int(args.max_tokens) if args.max_tokens is not None else None,
        compact_trigger_tokens=compact_trigger_tokens,
        compact_limit_tokens=compact_limit_tokens,
        temperature=float(args.temperature),
        approval_policy="auto_approve" if bool(args.auto_approve) else None,
        permission_preset=getattr(args, "permission_preset", None),
        allow_outside_workdir=getattr(args, "allow_outside_workdir", None),
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
