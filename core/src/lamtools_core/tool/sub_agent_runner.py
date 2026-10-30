from __future__ import annotations

import asyncio
import copy
import uuid
from collections.abc import Iterable
from dataclasses import asdict, replace
from copy import deepcopy
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping

from lamtools_core.agent import (
    SUB_AGENT_CHILD_MESSAGE_TOOL_NAME,
    SUB_AGENT_CHILD_MESSAGE_TOOL_SPEC,
    SUB_AGENT_MESSAGE_TOOL_NAME,
    SUB_AGENT_TOOL_NAME,
    SubAgentRunResult,
)
from lamtools_core.app.base_agent import CoreBaseAgentConfig, CoreBaseAgentKit
from lamtools_core.attachment.service import AttachmentRecord, build_capability_aware_attachment_input
from lamtools_core.event import CoreEvent, EventSink
from lamtools_core.kernel import CoreLoopKernel, LoopPolicy
from lamtools_core.llm import ChatMessage, normalize_reasoning_level, reasoning_level_from_legacy
from lamtools_core.llm.image_payload import MESSAGE_ADDED_AT_STEP
from lamtools_core.runtime import (
    InMemoryRuntimeStateStore,
    RuntimeCheckpointStore,
    RuntimeStateStore,
    RuntimeTurnInput,
)
from lamtools_core.skills import SkillRegistry
from lamtools_core.sub_agent import CallableEventSink, SubAgentEventForwardingSink
from lamtools_core.sub_agent import normalize_sub_session_agent_name
from lamtools_core.tool import ToolCall, ToolSpec
from lamtools_core.tool.approval_continuation import (
    ApprovedToolExecution,
    approved_tool_continuation_prompt,
    approved_tool_failure_continuation_prompt,
    question_answer_continuation_prompt,
)
from lamtools_core.tool.default_toolbox import ApprovalPolicy, CoreToolbox, build_core_toolbox
from lamtools_core.tool.loadtools import LoadTools, mode_names
from lamtools_core.tool.mcp_tools import MCPToolCaller
from lamtools_core.tool.permission import AUTO_ALLOW

# Type alias for the attachment-lookup protocol (duck-typed AttachmentService.get).
AttachmentServiceLike = Any


class RunnerCompactionService:
    """Preset-scoped compaction service backed by one child-session runner."""

    def __init__(self, runner: "KernelSubAgentRunner") -> None:
        self._runner = runner

    async def compact_now(self, session_id: str, *, source_command_id: str = "") -> dict[str, Any]:
        del source_command_id
        return await self._runner.compact(session_id)


def deliverables_payload(artifacts: list[Any], *, tool_name: str = "", call_id: str = "") -> dict[str, Any]:
    """Normalize tool artifacts for the host ``deliverables/presented`` event."""
    files = [
        artifact.to_dict() if callable(getattr(artifact, "to_dict", None)) else dict(artifact)
        for artifact in artifacts
        if artifact is not None
    ]
    payload: dict[str, Any] = {"files": files}
    if tool_name:
        payload["tool_name"] = tool_name
    if call_id:
        payload["call_id"] = call_id
    return payload


def _history_message_text(item: dict[str, Any]) -> str:
    content = item.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
        return "\n".join(part for part in parts if part)
    return ""


def _state_invocation_id(state: Any) -> str:
    """Projection scope of the run that owns ``state`` (empty when unknown).

    An empty value makes the sink mint a fresh scope, which is right for a new
    invocation; continuations of an existing run pass the recorded scope so the
    items they touch are the ones that run already created.
    """
    metadata = getattr(state, "metadata", None)
    if not isinstance(metadata, dict):
        return ""
    return str(metadata.get("sub_invocation_id") or "")


_WORKFLOW_CONTEXT_KEYS = (
    "parent_session_id",
    "parent_run_id",
    "parent_turn_id",
    "parent_call_id",
    "cwd",
    "pause_on_cancel",
    "permissions",
    "runtime_permissions",
    "event_metadata",
    "attachments",
    "runtime_snapshot",
    "snapshot",
    "environment",
    "capabilities",
    "trace_id",
    "traceId",
    "correlation_id",
    "actor_id",
    "actor_kind",
    "lineage",
    "parent_lineage",
    "workflow_stack",
    "active_workflows",
    "depth",
    "nesting_depth",
    "max_depth",
    "max_nesting_depth",
)


def _workflow_context_metadata(
    execution_context: Any | None,
    *,
    attachments: list[str] | None = None,
) -> dict[str, Any]:
    """Normalize a workflow context for the RuntimeTurnInput envelope.

    The production path supplies :class:`WorkflowExecutionContext`, while
    adapters and tests may pass a serialized mapping or a small duck-typed
    object.  Supporting all three here keeps the runner boundary independent
    of the workflow plugin's concrete class and preserves aliases used by
    older hosts.
    """
    if execution_context is None:
        result: dict[str, Any] = {}
    else:
        metadata_method = getattr(execution_context, "metadata", None)
        if callable(metadata_method):
            try:
                raw = metadata_method()
            except Exception:  # noqa: BLE001 - optional context cannot break delegation
                raw = {}
        elif isinstance(execution_context, Mapping):
            raw = execution_context
        else:
            raw = {
                key: getattr(execution_context, key)
                for key in _WORKFLOW_CONTEXT_KEYS
                if hasattr(execution_context, key)
            }
        source = dict(raw) if isinstance(raw, Mapping) else {}
        nested = source.get("workflow_execution", source.get("execution_context"))
        if callable(getattr(nested, "metadata", None)):
            try:
                nested = nested.metadata()
            except Exception:  # noqa: BLE001
                nested = None
        result = deepcopy(dict(nested)) if isinstance(nested, Mapping) else {}
        for key in _WORKFLOW_CONTEXT_KEYS:
            if key in source:
                result[key] = deepcopy(source[key])

    # A direct runner caller can provide attachments as the normal sub-agent
    # argument rather than embedding them in a WorkflowExecutionContext.
    if attachments and not result.get("attachments"):
        result["attachments"] = deepcopy(list(attachments))
    return result


def _resolve_model_id_for_capability(model_ref: str) -> str:
    """Resolve a model reference to the routable model record id.

    The ``model`` parameter passed to ``sub_agent`` may be a display_name
    (e.g. "Kimi-K2.6") or a bare upstream model id (e.g.
    ``deepseek-v4.1-flash``).  Provider routing and tool calling use the
    model *record* id (``opencode-go-deepseek-v4.1-flash``), which is also
    what the main conversation sends; returning the bare ``model_id`` here
    made the same provider receive a different model string on the plugin
    sub-agent path.  Fall back to the canonical model id only when the record
    has no separate id.
    """
    ref = (model_ref or "").strip()
    if not ref or ref.lower() in ("null", "none", "undefined"):
        return ""
    try:
        from lamtools_core.config.model_store import ModelStore
        store = ModelStore()
        # Exact model_id match
        model = store.get_sync(ref)
        if model is not None:
            return model.id or model.model_id
        # Try matching by display_name (case-insensitive)
        all_models = store.list_sync()
        ref_lower = ref.lower()
        for m in all_models:
            if (m.display_name or "").lower() == ref_lower:
                return m.id or m.model_id
    except Exception:
        pass
    return ref


class KernelSubAgentRunner:
    @property
    def parent_event_sink(self) -> EventSink | None:
        return self._parent_event_sink

    @parent_event_sink.setter
    def parent_event_sink(self, value: EventSink | Callable[[CoreEvent], Any] | None) -> None:
        # Host channel runtimes and plugins often pass a plain async callback.
        # Normalize it once so every consumer (sub-agent forwarding, supervisor)
        # can rely on the EventSink contract.
        if value is not None and not callable(getattr(value, "emit", None)) and callable(value):
            value = CallableEventSink(value)
        self._parent_event_sink = value

    def __init__(
        self,
        *,
        work_root: str | Path,
        llm_client: Any,
        model_id: str = "",
        instructions: str = "",
        temperature: float = 0.2,
        max_tokens: int | None = None,
        reasoning_level: str = "",
        thinking_enabled: bool | None = None,
        thinking_budget: int | None = None,
        approval_policy: ApprovalPolicy = "require",
        permission_preset: str = "ask",
        active_tier: str | None = None,
        tier_tools: dict[str, Any] | None = None,
        runtime_snapshot: dict[str, Any] | None = None,
        loaded_skill_roots: Iterable[Path] | None = None,
        skill_registry: SkillRegistry | None = None,
        skill_state_store: Any | None = None,
        mcp_caller: MCPToolCaller | None = None,
        mcp_tool_specs: list[ToolSpec] | None = None,
        mcp_config_files: Iterable[Path] | None = None,
        context_window_tokens: int | None = None,
        compact_trigger_ratio: float = 0.8,
        # 成员＝主代理的受限变体：除工具与提示词外不应有差异。父内核已解析的
        # LoopPolicy 可直接传入（推荐），成员内核据此原样继承；无法传策略对象
        # 的调用方也应传入与主代理相同的显式压缩旋钮，避免成员静默回落到默认值。
        loop_policy: Any | None = None,
        compact_trigger_tokens: int | None = None,
        compact_limit_tokens: int | None = None,
        compact_retained_steps: int | None = None,
        compact_limit_ratio: float | None = None,
        state_store: RuntimeStateStore | None = None,
        session_prefix: str = "core-sub-agent",
        parent_event_sink: EventSink | None = None,
        checkpoint_coordinator: Any | None = None,
        activated_mcp_servers: set[str] | None = None,
        active_mode: str | None = None,
        load_tools: LoadTools | None = None,
        attachment_service: AttachmentServiceLike = None,
        imagegen_config: dict | None = None,
        allow_access_outside_workdir: bool = False,
        runtime_permissions_provider: Callable[[], Mapping[str, Any] | None] | None = None,
        model_context_sink: Any | None = None,
        plugin_tool_specs: list[ToolSpec] | None = None,
        plugin_tool_handlers: dict[str, Any] | None = None,
        plugin_tool_providers: list[Callable[..., Any]] | None = None,
        plugin_mode_tool_sets: dict[str, set[str]] | None = None,
        plugin_availability: Callable[[str], bool] | None = None,
        parent_guidance_sink: Callable[[str, str, str, str], bool] | None = None,
        artifact_store: Any | None = None,
        plugin_mode_exclusive_tools: dict[str, set[str]] | None = None,
        agent_presets: Any | None = None,
        prompt_waterfall: Any | None = None,
    ) -> None:
        self.work_root = Path(work_root)
        # library 工具经它整理当前项目的成果目录；子代理与主代理同库。
        self.artifact_store = artifact_store
        self.plugin_mode_exclusive_tools = dict(plugin_mode_exclusive_tools or {})
        self.llm_client = llm_client
        self.model_id = model_id
        self.instructions = instructions
        self.temperature = temperature
        self.max_tokens = max_tokens
        # Normalize once at the runner boundary so every child model call
        # receives a canonical product level. Legacy boolean callers retain
        # their previous enabled-by-default high behavior.
        self.reasoning_level = reasoning_level_from_legacy(
            reasoning_level=reasoning_level,
            thinking_enabled=thinking_enabled,
            fallback="off",
        )
        self.thinking_enabled = thinking_enabled
        self.thinking_budget = thinking_budget
        self.approval_policy = approval_policy
        # user:“宿主能力补齐和接口完善与文档更新”+(子助手和克隆继承同一技能禁用账本，不能绕过管理界面已关闭的技能)。
        self.skill_state_store = skill_state_store
        self.permission_preset = str(permission_preset or "ask")
        self.active_tier = active_tier
        self.tier_tools = deepcopy(tier_tools) if isinstance(tier_tools, dict) else tier_tools
        self.runtime_snapshot = deepcopy(runtime_snapshot) if isinstance(runtime_snapshot, dict) else None
        if loaded_skill_roots is None and skill_registry is None:
            from lamtools_core.skill_runtime import create_skill_runtime

            skill_runtime = create_skill_runtime()
            self.loaded_skill_roots = skill_runtime.roots
            self.skill_registry = skill_runtime.registry
        else:
            self.loaded_skill_roots = tuple(
                dict.fromkeys(Path(root).resolve() for root in (loaded_skill_roots or ()))
            )
            self.skill_registry = skill_registry or SkillRegistry(
                explicit_roots=self.loaded_skill_roots
            )
        self.mcp_config_files = tuple(mcp_config_files or ())
        self.mcp_caller = mcp_caller
        self.mcp_tool_specs = list(mcp_tool_specs or [])
        self.context_window_tokens = context_window_tokens
        self.compact_trigger_ratio = compact_trigger_ratio
        self._loop_policy_template = loop_policy
        self.compact_trigger_tokens = compact_trigger_tokens
        self.compact_limit_tokens = compact_limit_tokens
        self.compact_retained_steps = compact_retained_steps
        self.compact_limit_ratio = compact_limit_ratio
        self.state_store = state_store or InMemoryRuntimeStateStore()
        self.session_prefix = str(session_prefix or "core-sub-agent")
        self.parent_event_sink = parent_event_sink
        self.checkpoint_coordinator = checkpoint_coordinator
        self.activated_mcp_servers = activated_mcp_servers or set()
        self.active_mode = active_mode
        self.load_tools = load_tools
        self.attachment_service = attachment_service
        self.imagegen_config = imagegen_config
        self.allow_access_outside_workdir = allow_access_outside_workdir
        self.runtime_permissions_provider = runtime_permissions_provider
        self.model_context_sink = model_context_sink
        self.plugin_tool_specs = list(plugin_tool_specs or [])
        self.plugin_tool_handlers = dict(plugin_tool_handlers or {})
        self.plugin_tool_providers = list(plugin_tool_providers or [])
        self.plugin_mode_tool_sets = {
            str(mode): {str(name) for name in names}
            for mode, names in (plugin_mode_tool_sets or {}).items()
        }
        self.plugin_availability = plugin_availability
        self.parent_guidance_sink = parent_guidance_sink
        # user:“agent preset（智能体预设）…是宿主缺失，去补”+(子代理运行器
        # 接受宿主预设注册表；预设只填补调用方未显式设置的 mode/tools/model/prompt)。
        self.agent_presets = agent_presets
        # user:“system-prompt waterfall（系统提示词流水线）都是宿主缺失，去补”
        # +(子代理内核的提示词组装接入插件流水线)。
        self.prompt_waterfall = prompt_waterfall
        # Per-session serialization: parallel sub_agent calls with the same
        # agent name share one child session id, so concurrent runs would
        # interleave history writes (audit 02 S2).  Keyed by session id, which
        # keeps the dict bounded by the number of distinct agent names.
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._owned_mcp_registry: Any | None = None
        # Session-level pause signal shared with the supervisor that drives
        # this runner's children. A child kernel polls it and ends in the
        # resumable ``paused`` state, so a paused session never turns into a
        # killed child.
        self._pause_event: asyncio.Event | None = None

    def set_pause_event(self, event: "asyncio.Event | None") -> None:
        self._pause_event = event

    async def create_supervisor_runner(self) -> "KernelSubAgentRunner":
        """Clone with an MCP registry whose lifecycle belongs to the supervisor."""
        independent_mcp = None
        independent_specs: list[ToolSpec] = []
        if self.mcp_caller is not None and hasattr(self.mcp_caller, "config_files"):
            from lamtools_core.mcp import MCPToolRegistry

            independent_mcp = MCPToolRegistry(
                self.work_root, config_files=list(self.mcp_caller.config_files),
                plugin_host=getattr(getattr(self.plugin_availability, "__self__", None), "host", None),
            )
            await independent_mcp.load()
            independent_specs = independent_mcp.tool_specs()
        clone = KernelSubAgentRunner(
            work_root=self.work_root, llm_client=self.llm_client, model_id=self.model_id,
            instructions=self.instructions, temperature=self.temperature, max_tokens=self.max_tokens,
            reasoning_level=self.reasoning_level, thinking_enabled=self.thinking_enabled,
            thinking_budget=self.thinking_budget, approval_policy=self.approval_policy,
            permission_preset=self.permission_preset, active_tier=self.active_tier,
            tier_tools=self.tier_tools, runtime_snapshot=self.runtime_snapshot,
            loaded_skill_roots=self.loaded_skill_roots, skill_registry=self.skill_registry,
            skill_state_store=self.skill_state_store,
            mcp_caller=independent_mcp, mcp_tool_specs=independent_specs,
            mcp_config_files=self.mcp_config_files,
            context_window_tokens=self.context_window_tokens,
            compact_trigger_ratio=self.compact_trigger_ratio,
            loop_policy=self._loop_policy_template,
            compact_trigger_tokens=self.compact_trigger_tokens,
            compact_limit_tokens=self.compact_limit_tokens,
            compact_retained_steps=self.compact_retained_steps,
            compact_limit_ratio=self.compact_limit_ratio,
            state_store=self.state_store,
            session_prefix=self.session_prefix, parent_event_sink=self.parent_event_sink,
            checkpoint_coordinator=self.checkpoint_coordinator,
            activated_mcp_servers=set(self.activated_mcp_servers), active_mode=self.active_mode,
            load_tools=self.load_tools, attachment_service=self.attachment_service,
            imagegen_config=self.imagegen_config,
            allow_access_outside_workdir=self.allow_access_outside_workdir,
            runtime_permissions_provider=self.runtime_permissions_provider,
            model_context_sink=self.model_context_sink, plugin_tool_specs=self.plugin_tool_specs,
            plugin_tool_handlers=self.plugin_tool_handlers,
            plugin_tool_providers=self.plugin_tool_providers,
            plugin_mode_tool_sets=self.plugin_mode_tool_sets,
            plugin_availability=self.plugin_availability,
            parent_guidance_sink=self.parent_guidance_sink,
            artifact_store=self.artifact_store,
            plugin_mode_exclusive_tools=self.plugin_mode_exclusive_tools,
            agent_presets=self.agent_presets,
            prompt_waterfall=self.prompt_waterfall,
        )
        clone._owned_mcp_registry = independent_mcp
        return clone

    def config_signature(self) -> tuple[Any, ...]:
        """Identity of the turn-local configuration this runner was built for.

        The supervisor keeps one cloned runner for its lifetime for its MCP
        registry, but the parent's project, model, permissions and skills can
        change between turns.  Comparing this signature lets the supervisor
        rebuild the clone instead of silently running new turns with the first
        turn's configuration.
        """
        import json as _json

        def stable(value: Any) -> str:
            try:
                return _json.dumps(value, sort_keys=True, default=str)
            except (TypeError, ValueError):
                return repr(value)

        return (
            str(self.work_root),
            self.model_id,
            self.reasoning_level,
            self.approval_policy,
            self.permission_preset,
            self.active_tier,
            stable(self.tier_tools),
            stable(self.runtime_snapshot),
            self.active_mode,
            bool(self.allow_access_outside_workdir),
            str(self.instructions or ""),
            id(self.artifact_store) if self.artifact_store is not None else 0,
            stable(self.plugin_mode_exclusive_tools),
            tuple(str(path) for path in self.mcp_config_files),
        )

    async def close(self) -> None:
        if self._owned_mcp_registry is not None:
            await self._owned_mcp_registry.close()
            self._owned_mcp_registry = None

    # ── Child-session lifecycle APIs for plugins ───────────────────────────
    def clone_with_work_root(self, work_root: str | Path) -> "KernelSubAgentRunner":
        """Return a runner view whose tools run in a plugin-owned directory.

        The state store, session locks and plugin tool handlers are shared, so
        the clone is a different working directory for the same child-session
        namespace, not a second runtime.
        """
        clone = copy.copy(self)
        clone.work_root = Path(work_root)
        return clone

    def preset_service(self, name: str, preset_id: str = "") -> Any | None:
        """Resolve a live service for the active preset.

        The registry may hold a plugin-registered service under
        ``(preset_id, name)``.  Compaction is built in: every runner can
        compact its own child sessions, so it is returned even when no plugin
        registered one.
        """
        name = str(name or "")
        if self.agent_presets is not None and hasattr(self.agent_presets, "service_for"):
            service = self.agent_presets.service_for(preset_id, name)
            if service is not None:
                return service
        if name == "compaction":
            return RunnerCompactionService(self)
        return None

    async def compact(self, session_id: str) -> dict[str, Any]:
        """Manually compact one child session (same pipeline as a normal turn)."""
        if not isinstance(self.state_store, RuntimeCheckpointStore):
            raise RuntimeError("child-session history storage does not support manual compaction")
        from lamtools_core.app.command_execution import compact_runtime_history

        return await compact_runtime_history(
            runtime_state_store=self.state_store,
            thread_id=session_id,
            llm_client=self.llm_client,
            model=self.model_id,
        )

    async def fork(self, session_id: str, new_agent_name: str) -> dict[str, Any]:
        """Fork a child session's committed state and history to a new agent name."""
        state = await self.state_store.get(session_id)
        if state is None:
            raise ValueError(f"child session not found: {session_id}")
        agent_name = normalize_sub_session_agent_name(new_agent_name)
        new_session_id = f"{self.session_prefix}:sub:{agent_name}"
        if new_session_id == session_id:
            raise ValueError("fork target must be a different agent name")
        history: list[dict[str, Any]] = []
        if isinstance(self.state_store, RuntimeCheckpointStore):
            history = await self.state_store.get_history(session_id)
        forked = deepcopy(state)
        forked.session_id = new_session_id
        forked.run_id = uuid.uuid4().hex
        forked.status = "idle"
        forked.position = ""
        forked.loop_state = "continue"
        forked.turn_count = 0
        metadata = forked.metadata if isinstance(forked.metadata, dict) else {}
        metadata.pop("pending_approval", None)
        metadata.pop("pending_waiting_request", None)
        metadata.pop("sub_invocation_id", None)
        delegated = metadata.get("delegated_session")
        if isinstance(delegated, dict):
            delegated["session_id"] = new_session_id
            delegated["agent"] = agent_name
        forked.metadata = metadata
        if isinstance(self.state_store, RuntimeCheckpointStore):
            await self.state_store.save_checkpoint(forked, history)
        else:
            await self.state_store.save(forked)
        return {
            "session_id": new_session_id,
            "agent": agent_name,
            "forked_from": session_id,
            "history_count": len(history),
        }

    async def session_info(self, session_id: str) -> dict[str, Any]:
        """Read a child session's status, usage and recent transcript."""
        state = await self.state_store.get(session_id)
        if state is None:
            raise ValueError(f"child session not found: {session_id}")
        history: list[dict[str, Any]] = []
        if isinstance(self.state_store, RuntimeCheckpointStore):
            history = await self.state_store.get_history(session_id)
        usage = state.metadata.get("runtime_usage") if isinstance(state.metadata, dict) else None
        if not isinstance(usage, dict):
            usage = state.metadata.get("usage") if isinstance(state.metadata, dict) else None
        usage = usage if isinstance(usage, dict) else {}
        messages = [
            {
                "role": str(item.get("role") or ""),
                "text": _history_message_text(item),
                **({"name": str(item.get("name"))} if item.get("name") else {}),
            }
            for item in history
            if str(item.get("role") or "") in {"user", "assistant"}
        ]
        return {
            "session_id": session_id,
            "status": state.status,
            "loop_state": state.loop_state,
            "turn_count": state.turn_count,
            "history_count": len(history),
            "message_count": len(messages),
            "model_id": str((state.metadata or {}).get("model_id") or ""),
            "agent_preset": str((state.metadata or {}).get("agent_preset") or ""),
            "pending": bool(
                (state.metadata or {}).get("pending_approval")
                or (state.metadata or {}).get("pending_waiting_request")
            ),
            "usage": {
                "input": int(usage.get("prompt_tokens") or usage.get("input") or 0),
                "output": int(usage.get("completion_tokens") or usage.get("output") or 0),
                "cacheRead": int(usage.get("cached_tokens") or usage.get("cacheRead") or 0),
                "cacheWrite": int(usage.get("cache_creation_tokens") or usage.get("cacheWrite") or 0),
            },
            "messages": messages[-20:],
        }

    def _disabled_tools(self) -> set[str]:
        """Sub-agent disabled set: never sub_agent itself; generate_image only
        when the 生图 setting is disabled (mirrors the main agent)."""
        disabled = {SUB_AGENT_TOOL_NAME, SUB_AGENT_MESSAGE_TOOL_NAME}
        if not bool((self.imagegen_config or {}).get("enabled")):
            disabled.add("generate_image")
        return disabled

    def _build_toolbox(self, disabled_tools: set[str], *, active_mode: str | None, mcp_service: Any | None = None) -> CoreToolbox:
        # user:“给我把 2 阶段做完，前端除外”+(子工具独立捕获目录源，配置/技能/模型仍读取原项目)。
        from lamtools_core.sub_agent_supervisor import current_child_identity
        directory_identity = current_child_identity()
        if directory_identity is not None:
            directory_identity[0].member_execution_directory(directory_identity[2])
        async def child_message(call: ToolCall):
            from lamtools_core.sub_agent_supervisor import current_child_identity

            identity = current_child_identity()
            if identity is None:
                from lamtools_core.tool import ToolResult
                return ToolResult(call_id=call.id, name=call.name, status="failed", error="unbound child context")
            supervisor, _child_type, _child_name = identity
            try:
                payload = await supervisor.child_message(
                    (call.arguments or {}).get("message"),
                    message_id=call.id,
                )
            except ValueError as exc:
                from lamtools_core.tool import ToolResult
                return ToolResult(call_id=call.id, name=call.name, status="failed", error=str(exc))
            from lamtools_core.tool import ToolResult
            return ToolResult(call_id=call.id, name=call.name, status="ok", content="accepted", metadata=payload)

        child_message_spec = ToolSpec(
            name=SUB_AGENT_CHILD_MESSAGE_TOOL_NAME,
            description=SUB_AGENT_CHILD_MESSAGE_TOOL_SPEC["description"],
            input_schema=SUB_AGENT_CHILD_MESSAGE_TOOL_SPEC["input_schema"],
            permission=AUTO_ALLOW,
        )
        child_load_tools = deepcopy(self.load_tools or {})
        for mode_config in child_load_tools.values():
            if mode_config.tools and SUB_AGENT_CHILD_MESSAGE_TOOL_NAME not in mode_config.tools:
                mode_config.tools.append(SUB_AGENT_CHILD_MESSAGE_TOOL_NAME)

        def child_runtime_permissions() -> Mapping[str, Any] | None:
            provider = self.runtime_permissions_provider
            value = provider() if provider is not None else None
            if not isinstance(value, Mapping):
                return value
            merged = dict(value)
            raw_tiers = value.get("tier_tools")
            if isinstance(raw_tiers, Mapping):
                merged["tier_tools"] = {
                    str(tier): (
                        []
                        if str(tier) == "full_edit" and not tools
                        else [
                            *dict.fromkeys(
                                [*(str(tool) for tool in tools), SUB_AGENT_CHILD_MESSAGE_TOOL_NAME]
                            )
                        ]
                    )
                    for tier, tools in raw_tiers.items()
                    if isinstance(tools, (set, frozenset, list, tuple))
                }
            return merged

        child_tier_tools = deepcopy(self.tier_tools)
        if isinstance(child_tier_tools, dict):
            for tier, tools in child_tier_tools.items():
                if str(tier) == "full_edit" and not tools:
                    continue
                if isinstance(tools, set):
                    tools.add(SUB_AGENT_CHILD_MESSAGE_TOOL_NAME)
                elif isinstance(tools, (list, tuple, frozenset)):
                    child_tier_tools[tier] = [
                        *dict.fromkeys(
                            [*(str(tool) for tool in tools), SUB_AGENT_CHILD_MESSAGE_TOOL_NAME]
                        )
                    ]
        toolbox = build_core_toolbox(
            work_root=self.work_root,
            approval_policy=self.approval_policy,
            # user:“处于完全访问状态，但是它运行命令的时候弹审批了”+(子代理继承相同的完全访问授权)。
            permission_preset=self.permission_preset,
            active_tier=self.active_tier,
            tier_tools=child_tier_tools,
            loaded_skill_roots=self.loaded_skill_roots,
            skill_registry=self.skill_registry,
            skill_state_store=self.skill_state_store,
            mcp_service=mcp_service,
            mcp_caller=self.mcp_caller,
            disabled_tools=disabled_tools,
            imagegen_config=self.imagegen_config,
            activated_mcp_servers=self.activated_mcp_servers,
            load_tools=child_load_tools,
            active_mode=active_mode,
            allow_access_outside_workdir=self.allow_access_outside_workdir,
            runtime_permissions_provider=(
                child_runtime_permissions if self.runtime_permissions_provider is not None else None
            ),
            plugin_tool_specs=[*self.plugin_tool_specs, child_message_spec],
            plugin_tool_handlers={**self.plugin_tool_handlers, SUB_AGENT_CHILD_MESSAGE_TOOL_NAME: child_message},
            plugin_tool_providers=self.plugin_tool_providers,
            plugin_mode_tool_sets=self.plugin_mode_tool_sets,
            plugin_availability=self.plugin_availability,
            artifact_store=self.artifact_store,
            plugin_mode_exclusive_tools=self.plugin_mode_exclusive_tools,
        )
        if directory_identity is not None:
            supervisor, _, member = directory_identity
            def source(_session_id):
                return supervisor.member_execution_directory(member)
            toolbox.execution_directory_source = source
        return toolbox

    def available_tool_specs(self, *, mode: str = "") -> list[ToolSpec]:
        """Return exactly the tools a workflow Agent node can execute.

        The workflow editor consumes this catalog, so it must be assembled by
        the same toolbox path as execution rather than from the workflow
        plugin's graph-editing tools alone.
        """

        effective_mode = self._resolve_mode(mode)
        toolbox = self._build_toolbox(self._disabled_tools(), active_mode=effective_mode)
        return list(toolbox.tool_specs())

    def _resolve_mode(self, mode: str) -> str | None:
        """Resolve a per-call mode override against the configured loadtools.

        An empty override falls back to the runner's baseline ``active_mode``.
        A non-empty mode that is not a known loadtools mode is treated as no
        filtering (full access) so an unknown name never silently locks the
        sub-agent out of its tools.
        """
        candidate = (mode or "").strip() or self.active_mode
        if not candidate:
            return None
        if self.load_tools and candidate not in mode_names(self.load_tools):
            return None
        return candidate

    async def _fetch_attachment_content(
        self, task: str, attachment_ids: list[str], model_id: str = ""
    ) -> str | list[dict[str, Any]]:
        """Build the sub-agent user message, optionally with attachment content blocks.

        Uses capability-aware splitting: attachments the sub-agent's model can
        process (e.g. images for a multimodal model) become content blocks;
        unsupported ones are deferred as IDs (rare for sub-agents, but handled).
        """
        if not attachment_ids or self.attachment_service is None:
            return task
        records: list[AttachmentRecord] = []
        for att_id in attachment_ids:
            att_id = str(att_id or "").strip()
            if not att_id:
                continue
            try:
                record = await self.attachment_service.get(att_id)
            except Exception:
                record = None
            if record is not None:
                records.append(record)
        if not records:
            return task
        # Resolve the sub-agent model's capability from its jsonc definition
        # (jsonc is the single source of truth; model_id alone is insufficient).
        from lamtools_core.config.model_store import resolve_model_capability

        capability = resolve_model_capability(model_id or self.model_id, work_root=str(self.work_root))
        index_text, content_blocks, _deferred = await asyncio.to_thread(
            build_capability_aware_attachment_input,
            records,
            [r.id for r in records],
            capability,
        )
        if not content_blocks:
            return task + (index_text or "")
        # Text block first (the task + attachment index), then content blocks.
        return [{"type": "text", "text": task + (index_text or "")}, *content_blocks]

    async def run(
        self,
        *,
        task: str,
        agent: str = "",
        model: str = "",
        reasoning_level: str | None = None,
        reasoning_effort: str | None = None,
        mode: str = "",
        attachments: list[str] | None = None,
        parent_call_id: str = "",
        parent_run_id: str = "",
        parent_turn_id: str = "",
        profile_spec: Any | None = None,
        allowed_tools: list[str] | None = None,
        execution_context: Any | None = None,
        late_context: str = "",
        guidance_source: Callable[[], list[Any]] | None = None,
        guidance_finalizer: Callable[[], list[Any] | None | Awaitable[list[Any] | None]] | None = None,
        guidance_acknowledger: Callable[[list[str]], Any] | None = None,
        initial_guidance_ids: list[str] | None = None,
        preset: str = "",
    ) -> SubAgentRunResult:
        agent_name = normalize_sub_session_agent_name(agent)
        lock = self._session_locks.setdefault(
            f"{self.session_prefix}:sub:{agent_name}", asyncio.Lock()
        )
        # user:“该修修”+(每轮独占连接、命令白名单和清理，不修改 runner 的共享激活集)。
        service, owns_service = self._new_command_service(profile_spec)
        try:
            async with lock:
                return await self._run_locked(
                    mcp_service=service,
                    task=task,
                    agent=agent,
                    model=model,
                    reasoning_level=reasoning_level,
                    reasoning_effort=reasoning_effort,
                    mode=mode,
                    attachments=attachments,
                    parent_call_id=parent_call_id,
                    parent_run_id=parent_run_id,
                    parent_turn_id=parent_turn_id,
                    allowed_tools=allowed_tools,
                    profile_spec=profile_spec,
                    execution_context=execution_context,
                    late_context=late_context,
                    guidance_source=guidance_source,
                    guidance_finalizer=guidance_finalizer,
                    guidance_acknowledger=guidance_acknowledger,
                    initial_guidance_ids=initial_guidance_ids,
                    preset=preset,
                )
        finally:
            if owns_service:
                await service.close()

    def _new_command_service(self, profile_spec=None):
        from lamtools_core.mcp.command_service import MCPCommandService
        from lamtools_core.mcp import MCPToolRegistry
        owned = bool(self.mcp_config_files) or self.mcp_caller is None
        # user:“该调的模块就是该写的东西”+(子代理的 MCP 同样归插件宿主管理，更新前必须排空并关闭)。
        registry = MCPToolRegistry(self.work_root, config_files=list(self.mcp_config_files),
            plugin_host=getattr(getattr(self.plugin_availability, "__self__", None), "host", None)) if owned else self.mcp_caller
        service = MCPCommandService(registry, loaded=not owned)
        if profile_spec is not None and profile_spec.mcp_tools:
            service.allowed_tools = frozenset(profile_spec.mcp_tools)
        return service, owned

    @staticmethod
    def _profile_from_state(state):
        from lamtools_core.plugin_system.profiles import ProfileSpec, ProfileBudget
        raw = state.metadata.get("run_profile_spec")
        if not isinstance(raw, dict):
            return None
        values = dict(raw)
        values["budget"] = ProfileBudget(**dict(values.get("budget") or {}))
        for key in ("tools", "mcp_servers", "mcp_tools", "skills"):
            values[key] = tuple(values.get(key) or ())
        return ProfileSpec(**values)

    async def _save_profile_budget(self, result, toolbox):
        budget = getattr(toolbox, "run_budget", None)
        if budget is not None:
            result.state.metadata["run_profile_budget"] = dict(budget.counters)
            await self.state_store.save(result.state)

    async def _run_locked(
        self,
        *,
        mcp_service: Any | None = None,
        task: str,
        agent: str = "",
        invocation_id: str = "",
        model: str = "",
        reasoning_level: str | None = None,
        reasoning_effort: str | None = None,
        mode: str = "",
        attachments: list[str] | None = None,
        parent_call_id: str = "",
        parent_run_id: str = "",
        parent_turn_id: str = "",
        profile_spec: Any | None = None,
        allowed_tools: list[str] | None = None,
        execution_context: Any | None = None,
        late_context: str = "",
        guidance_source: Callable[[], list[Any]] | None = None,
        guidance_finalizer: Callable[[], list[Any] | None | Awaitable[list[Any] | None]] | None = None,
        guidance_acknowledger: Callable[[list[str]], Any] | None = None,
        initial_guidance_ids: list[str] | None = None,
        preset: str = "",
    ) -> SubAgentRunResult:
        preset_id = str(preset or "").strip()
        preset_prompt = ""
        if preset_id and self.agent_presets is not None:
            try:
                composed = self.agent_presets.compose(
                    preset_id,
                    mode=mode,
                    allowed_tools=allowed_tools,
                    model=model,
                    prompt=late_context,
                )
            except KeyError as exc:
                raise ValueError(f"unknown agent preset '{preset_id}'") from exc
            mode = composed.mode or mode
            allowed_tools = composed.allowed_tools if composed.allowed_tools is not None else allowed_tools
            model = composed.model or model
            late_context = composed.prompt
            preset_prompt = composed.preset_prompt
        # Resolve model early: the LLM may pass a display_name (e.g. "Kimi-K2.6")
        # instead of a model_id (e.g. "xopkimik26"). Translate to canonical
        # model_id once so the entire downstream chain (capability lookup,
        # kernel config, metadata, result) uses the same value.
        effective_model = _resolve_model_id_for_capability(
            (model or "").strip() or self.model_id
        )
        explicit_reasoning = str(reasoning_level or "").strip() or str(reasoning_effort or "").strip()
        effective_reasoning_level = (
            normalize_reasoning_level(explicit_reasoning, self.reasoning_level)
            if explicit_reasoning
            else self.reasoning_level
        )
        effective_mode = self._resolve_mode(mode)
        if profile_spec is not None and getattr(profile_spec, "model_scene", ""):
            # user:“运行档声明模型场景”+无人值守的模型由运行档决定，调用方不可加宽。
            from lamtools_core.config.model_selection import ModelResolutionError, resolve_scene_model

            try:
                effective_model = resolve_scene_model(profile_spec.model_scene).model_id
            except ModelResolutionError as exc:
                raise RuntimeError(
                    f"profile '{profile_spec.full_name}' model scene '{profile_spec.model_scene}' has no model: {exc}"
                ) from exc
        user_content = await self._fetch_attachment_content(task, list(attachments or []), model_id=effective_model)
        disabled_tools = self._disabled_tools()
        has_mcp = bool(self.mcp_config_files) or self.mcp_caller is not None or bool(
            profile_spec is not None
            and (getattr(profile_spec, "mcp_servers", ()) or getattr(profile_spec, "mcp_tools", ()))
        )
        # A child without any MCP server must not advertise the generic ``mcp``
        # tool: it has no tools to discover and the model otherwise burns
        # rounds calling it with a plugin tool name.
        mcp_tools_service = mcp_service if has_mcp else None
        if profile_spec is not None:
            # user:“运行档由宿主强制”+白名单以声明为准（覆盖调用方传入的
            # allowed_tools），配合 apply_profile 的 fail closed 执行拒绝。
            allowed = set(profile_spec.tools)
            probe = self._build_toolbox(disabled_tools, active_mode=effective_mode, mcp_service=mcp_tools_service)
            full_names = {spec.name for spec in probe.tool_specs()}
            disabled_tools |= full_names - allowed
        elif allowed_tools:
            allowed = {str(name).strip() for name in allowed_tools if str(name).strip()}
            if allowed:
                # An explicit tool allow-list: disable everything else.  The
                # full name set is the toolbox's own spec set (audit 18 S2 —
                # cfg.tools/allowed_tools from plugin UIs must be honored by
                # the runner rather than only persisted in the session.
                probe = self._build_toolbox(disabled_tools, active_mode=effective_mode, mcp_service=mcp_tools_service)
                full_names = {spec.name for spec in probe.tool_specs()}
                disabled_tools |= full_names - allowed
        toolbox = self._build_toolbox(disabled_tools, active_mode=effective_mode, mcp_service=mcp_tools_service)
        if profile_spec is not None:
            # 宿主强制：白名单可见面 + execute 拒绝 + 审批覆盖 + 预算计数。
            from lamtools_core.plugin_system.profiles import apply_profile

            apply_profile(toolbox, profile_spec)
        if profile_spec is not None:
            # user:“该修修”+(运行档依赖的技能正文由宿主预载，受限工具面不必另开文件读取权)。
            bodies = []
            for skill_name in getattr(profile_spec, "skills", ()):
                body = self.skill_registry.load_prompt_content(self.work_root, skill_name)
                if body.startswith(f'Skill "{skill_name}" not found.'):
                    raise ValueError(body)
                bodies.append(body)
            late_context = "\n\n".join([*bodies, late_context]).strip()
        agent_name = normalize_sub_session_agent_name(agent)
        child_sink = SubAgentEventForwardingSink(
            parent_sink=self.parent_event_sink,
            parent_session_id=self.session_prefix,
            agent=agent_name,
            task=task,
            parent_call_id=parent_call_id,
            parent_run_id=parent_run_id,
            parent_turn_id=parent_turn_id,
            type=effective_mode or "execute",
            model_id=effective_model,
            reasoning_level=effective_reasoning_level,
            invocation_id=invocation_id,
        )
        kernel = self._build_kernel(
            toolbox=toolbox,
            event_sink=child_sink,
            model_id=effective_model,
            reasoning_level=effective_reasoning_level,
            active_mode=effective_mode,
            late_context=late_context,
            preset_prompt=preset_prompt,
        )
        workflow_metadata = _workflow_context_metadata(
            execution_context,
            attachments=list(attachments or []),
        )
        result = await kernel.run(
            RuntimeTurnInput(
                user_message=task,
                user_content=user_content if user_content is not task else None,
                metadata={
                    **deepcopy(workflow_metadata),
                    "session_id": f"{self.session_prefix}:sub:{agent_name}",
                    "model_id": effective_model,
                    "active_mode": effective_mode,
                    "reasoning_level": effective_reasoning_level,
                    "thinking_enabled": self.thinking_enabled,
                    "thinking_budget": self.thinking_budget,
                    "actor_kind": "sub_agent",
                    "run_profile_spec": asdict(profile_spec) if profile_spec is not None else None,
                    "initial_guidance_ids": list(initial_guidance_ids or []),
                    **({"agent_preset": preset_id} if preset_id else {}),
                    "delegated_session": {
                        "session_id": f"{self.session_prefix}:sub:{agent_name}",
                        "parent_thread_id": self.session_prefix,
                        "agent": agent_name,
                        "task": task,
                        "model": effective_model,
                        "mode": effective_mode or "execute",
                        "reasoning_level": effective_reasoning_level,
                        "attachments": list(attachments or []),
                        "parent_call_id": parent_call_id,
                        "parent_run_id": parent_run_id,
                        "parent_turn_id": parent_turn_id,
                    },
                    **({"workflow_execution": workflow_metadata} if workflow_metadata else {}),
                    **(
                        {
                            "runtime_snapshot": deepcopy(self.runtime_snapshot),
                            "runtime_snapshot_fresh": True,
                        }
                        if self.runtime_snapshot is not None and "runtime_snapshot" not in workflow_metadata
                        else {}
                    ),
                },
                guidance_source=guidance_source,
                guidance_finalizer=guidance_finalizer,
                guidance_acknowledger=guidance_acknowledger,
            )
        )
        if preset_id:
            result.state.metadata["agent_preset"] = preset_id
        await self._save_profile_budget(result, toolbox)
        delegated_session = {
            "session_id": result.session_id,
            "parent_thread_id": self.session_prefix,
            "agent": agent_name,
            "task": task,
            "model": effective_model,
            "mode": effective_mode or "execute",
            "reasoning_level": effective_reasoning_level,
            "attachments": list(attachments or []),
            "parent_call_id": parent_call_id,
            "parent_run_id": parent_run_id,
            "parent_turn_id": parent_turn_id,
        }
        result.state.metadata["actor_kind"] = "sub_agent"
        result.state.metadata["delegated_session"] = delegated_session
        # The scope its items were projected under. A continuation of this same
        # run (an answered question or approval) must reuse it: the waiting item
        # and its resolution then share one item id, so the card resolves in
        # place instead of leaving a stale waiting card behind.
        result.state.metadata["sub_invocation_id"] = child_sink.invocation_id
        pending_approval = result.state.metadata.get("pending_approval")
        if isinstance(pending_approval, dict):
            result.state.metadata["pending_approval"] = {
                **pending_approval,
                "delegated_session": delegated_session,
            }
        await self.state_store.save(result.state)
        return self._result_from_kernel(result, model_id=effective_model)

    def _build_kernel(
        self,
        *,
        toolbox: Any,
        event_sink: EventSink,
        model_id: str = "",
        reasoning_level: str | None = None,
        active_mode: str | None = None,
        late_context: str = "",
        preset_prompt: str = "",
    ) -> CoreLoopKernel:
        return CoreLoopKernel(
            kit=CoreBaseAgentKit(
                work_root=self.work_root,
                config=CoreBaseAgentConfig(
                    model_id=model_id or self.model_id,
                    instructions=self.instructions,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    reasoning_level=reasoning_level or self.reasoning_level,
                    thinking_enabled=self.thinking_enabled,
                    thinking_budget=self.thinking_budget,
                    approval_policy=self.approval_policy,
                    active_mode=active_mode,
                    request_local_late_context=late_context,
                    agent_preset_prompt=preset_prompt,
                ),
                toolbox=toolbox,
                prompt_waterfall=self.prompt_waterfall,
            ),
            llm_client=self.llm_client,
            state_store=self.state_store,
            event_sink=event_sink,
            checkpoint_coordinator=self.checkpoint_coordinator,
            policy=self._member_loop_policy(),
            retry_policy=self._retry_policy(),
            pause_event_source=self._pause_event,
            model_context_sink=self.model_context_sink,
        )

    def _member_loop_policy(self) -> LoopPolicy:
        """成员内核的运行策略。

        成员是主代理的受限变体，差异只允许出现在工具与提示词层；压缩、重试、
        超时等运行策略必须与主代理一致。因此这里优先整份继承父内核已解析的
        ``LoopPolicy``；只有在调用方无法提供策略对象时，才用与主代理相同的显式
        旋钮拼装（不再单方面硬编码默认值）。
        """
        template = self._loop_policy_template
        if isinstance(template, LoopPolicy):
            return replace(template)
        policy_kwargs: dict[str, Any] = {**self._retry_policy_overrides()}
        if self.context_window_tokens is not None:
            policy_kwargs["context_window_tokens"] = self.context_window_tokens
        policy_kwargs.setdefault("compact_trigger_ratio", self.compact_trigger_ratio)
        for key, value in (
            ("compact_trigger_tokens", self.compact_trigger_tokens),
            ("compact_limit_tokens", self.compact_limit_tokens),
            ("compact_retained_steps", self.compact_retained_steps),
            ("compact_limit_ratio", self.compact_limit_ratio),
        ):
            if value is not None:
                policy_kwargs[key] = value
        return LoopPolicy(**policy_kwargs)

    def _retry_policy_overrides(self) -> dict[str, Any]:
        """LoopPolicy retry knobs from model_retry.jsonc (config-file defaults)."""
        from lamtools_core.config.retry_store import (
            load_model_retry_config,
            loop_policy_overrides,
        )

        return loop_policy_overrides(load_model_retry_config())

    def _retry_policy(self) -> Any:
        """Transport RetryPolicy from model_retry.jsonc."""
        from lamtools_core.config.retry_store import (
            load_model_retry_config,
            retry_policy_from_config,
        )

        return retry_policy_from_config(load_model_retry_config())

    def _result_from_kernel(self, result: Any, *, model_id: str = "") -> SubAgentRunResult:
        last_turn = result.steps[-1].turn if result.steps else None
        ended_with_final_response = bool(
            result.decision == "done"
            and result.message.strip()
            and last_turn is not None
            and not last_turn.tool_calls
            and last_turn.reply.strip()
        )
        logged_steps = result.state.metadata.get("kernel_steps")
        if isinstance(logged_steps, list):
            tool_call_count = sum(
                len(step.get("tool_calls") or [])
                for step in logged_steps
                if isinstance(step, dict)
            )
        else:
            tool_call_count = sum(len(step.tool_steps) for step in result.steps)
        model_rounds = len(result.steps)
        tool_call_breakdown = self._extract_tool_call_breakdown(result)
        death_scene = self._extract_death_scene(result)
        return SubAgentRunResult(
            session_id=result.session_id,
            run_id=result.run_id,
            decision=result.decision,
            model_id=model_id or self.model_id,
            message=result.message,
            error=result.error,
            tool_call_count=tool_call_count,
            ended_with_final_response=ended_with_final_response,
            pending_approval=dict(result.state.metadata.get("pending_approval") or {}),
            pending_waiting_request=dict(result.state.metadata.get("pending_waiting_request") or {}),
            model_rounds=model_rounds,
            tool_call_breakdown=tool_call_breakdown,
            death_scene=death_scene,
        )

    @staticmethod
    def _extract_tool_call_breakdown(result: Any) -> dict[str, int]:
        """Aggregate tool call counts by tool name across all kernel steps."""
        breakdown: dict[str, int] = {}
        logged_steps = result.state.metadata.get("kernel_steps")
        if isinstance(logged_steps, list):
            for step in logged_steps:
                if not isinstance(step, dict):
                    continue
                for tc in step.get("tool_calls") or []:
                    if isinstance(tc, dict):
                        name = str(tc.get("name") or "")
                        if name:
                            breakdown[name] = breakdown.get(name, 0) + 1
        else:
            for step in result.steps:
                for ts in step.tool_steps:
                    name = ts.call.name
                    breakdown[name] = breakdown.get(name, 0) + 1
        return breakdown

    @staticmethod
    def _extract_death_scene(result: Any) -> str:
        """Build a compact summary of the last model round for failure forwarding.

        Captures the model's last reply (truncated) and the tools it called in
        that round along with their execution status, so the parent agent can
        understand *why* the sub-agent died instead of seeing only a generic
        'failed without a final response' message.
        """
        if not result.steps:
            return ""
        last_step = result.steps[-1]
        lines = ["--- Sub-agent death scene (last model round) ---"]
        turn = last_step.turn
        if turn is not None and turn.reply.strip():
            reply = turn.reply.strip()
            if len(reply) > 500:
                reply = reply[:500] + "…"
            lines.append(f"Model reply: {reply}")
        else:
            lines.append("Model reply: (empty — no text produced)")
        if last_step.tool_steps:
            lines.append("Tools called this round:")
            for ts in last_step.tool_steps:
                status = ts.result.status if ts.result else "unknown"
                entry = f"  - {ts.call.name} → {status}"
                if ts.result and ts.result.error:
                    err = ts.result.error.strip()
                    if len(err) > 200:
                        err = err[:200] + "…"
                    entry += f": {err}"
                lines.append(entry)
        else:
            lines.append("Tools called this round: (none)")
        if last_step.error:
            lines.append(f"Step error: {last_step.error}")
        return "\n".join(lines)

    async def resume_approved(
        self,
        *,
        session_id: str,
        pending_call: dict[str, Any],
        task: str,
        agent: str,
        parent_call_id: str,
        parent_run_id: str = "",
        parent_turn_id: str = "",
        model: str = "",
        reasoning_level: str | None = None,
        reasoning_effort: str | None = None,
        mode: str = "",
        attachments: list[str] | None = None,
        execution_context: Any | None = None,
        supervisor: Any | None = None,
    ) -> SubAgentRunResult:
        state = await self.state_store.get(session_id)
        if state is None:
            raise ValueError("Sub-agent runtime state not found")
        call = ToolCall(
            id=str(pending_call.get("id") or ""),
            name=str(pending_call.get("name") or ""),
            arguments=(
                dict(pending_call.get("arguments"))
                if isinstance(pending_call.get("arguments"), dict)
                else {}
            ),
            metadata={
                **(
                    dict(pending_call.get("metadata"))
                    if isinstance(pending_call.get("metadata"), dict)
                    else {}
                ),
                "approval": {"approved": True, "auto_approved": True},
            },
        )
        effective_model = _resolve_model_id_for_capability(
            (model or "").strip() or self.model_id
        )
        explicit_reasoning = (
            str(reasoning_level or "").strip()
            or str(reasoning_effort or "").strip()
        )
        effective_reasoning_level = (
            normalize_reasoning_level(explicit_reasoning, self.reasoning_level)
            if explicit_reasoning
            else self.reasoning_level
        )
        effective_mode = self._resolve_mode(mode)
        child_sink = SubAgentEventForwardingSink(
            parent_sink=self.parent_event_sink,
            parent_session_id=self.session_prefix,
            agent=normalize_sub_session_agent_name(agent),
            task=task,
            parent_call_id=parent_call_id,
            parent_run_id=parent_run_id,
            parent_turn_id=parent_turn_id,
            type=effective_mode or "execute",
            model_id=effective_model,
            reasoning_level=effective_reasoning_level,
            invocation_id=_state_invocation_id(state),
        )
        await child_sink.emit(CoreEvent(
            name="runtime.approval_response",
            category="decision",
            payload={
                "request_id": call.id,
                "tool_call_id": call.id,
                "decision": "approve",
                "action": "approve",
                "status": "resolved",
            },
            session_id=session_id,
            run_id=state.run_id,
            tags=["approval", "resolved"],
        ))
        # user:“一次性处理干净 不要留尾巴”+(审批恢复仍装配命令连接、白名单与已消耗预算)。
        profile = self._profile_from_state(state)
        service, owned = self._new_command_service(profile)
        try:
            approval_toolbox = self._build_toolbox(self._disabled_tools(), active_mode=effective_mode, mcp_service=service)
            if profile is not None:
                from lamtools_core.plugin_system.profiles import apply_profile
                counters = apply_profile(approval_toolbox, profile)
                counters.update(state.metadata.get("run_profile_budget") or {})
            if call.metadata.pop("trust_requested", False):
                approval_toolbox.approval_gate.trust_operation(call.name, call.arguments)
            call = approval_toolbox.prepare_approved_call(call)
            tool_result = await approval_toolbox.execute(call)
            if profile is not None:
                state.metadata["run_profile_budget"] = dict(counters)
        finally:
            if owned:
                await service.close()
        await child_sink.emit(CoreEvent(
            name="runtime.tool.finished",
            category="tool",
            payload={
                "tool_name": call.name,
                "call_id": call.id,
                "status": tool_result.status,
                "content": tool_result.content or "",
                "error": tool_result.error or "",
                "artifacts": [artifact.to_dict() for artifact in tool_result.artifacts],
                "metadata": tool_result.metadata,
            },
            session_id=session_id,
            run_id=state.run_id,
            tags=["tool"],
        ))
        if tool_result.artifacts:
            # user:“该做就做”+(宿主把工具产物统一发成交付物事件；通道插件
            # 不必只靠扫描 tool.finished 来发现文件)。
            await child_sink.emit(CoreEvent(
                name="deliverables/presented",
                category="artifact",
                payload=deliverables_payload(tool_result.artifacts, tool_name=call.name, call_id=call.id),
                session_id=session_id,
                run_id=state.run_id,
                tags=["artifact", "deliverable"],
            ))
        if tool_result.status == "blocked":
            # A refused call cannot be continued with; a *failed* result is a
            # correctable tool failure and is handed back to the child below.
            raise RuntimeError(tool_result.error or tool_result.content or "Approved sub-agent tool failed")

        state.metadata.pop("pending_approval", None)
        state.metadata.pop("pending_waiting_request", None)
        state.status = "running"
        state.loop_state = "continue"
        if isinstance(self.state_store, RuntimeCheckpointStore):
            tool_msg = ChatMessage(
                role="tool",
                name=call.name,
                tool_call_id=call.id,
                content=tool_result.content or tool_result.error,
                # user:“作为下一轮的输入时，它应该是以自己本身的清晰度输入”+子代理审批恢复的
                # 工具结果也要带计数，续跑的第一请求仍看原图。
                metadata={MESSAGE_ADDED_AT_STEP: int(getattr(state, "turn_count", 0) or 0)},
            ).to_dict()
            await self.state_store.append_history(session_id, [tool_msg])
            await self.state_store.save(state)
        else:
            await self.state_store.save(state)

        approved_tool = ApprovedToolExecution(
            tool_name=call.name,
            tool_args=call.arguments,
            tool_content=(
                (tool_result.content or tool_result.error)
                + (
                    f"\nerror_code: {tool_result.error_code}"
                    if tool_result.error_code
                    else ""
                )
            ),
            tool_status="completed" if tool_result.status == "ok" else "failed",
        )
        if tool_result.status == "failed":
            continuation = approved_tool_failure_continuation_prompt(
                original_task=task,
                approved_tool=approved_tool,
            )
        else:
            continuation = approved_tool_continuation_prompt(
                original_task=task,
                approved_tool=approved_tool,
            )
        async def continue_child() -> SubAgentRunResult:
            resume_late_context = (
                await supervisor.request_local_context(agent)
                if supervisor is not None
                else (
                    "[Request-local sub-agent context]\n"
                    f"name: {normalize_sub_session_agent_name(agent)}\n"
                    f"type: {effective_mode or 'execute'}\n"
                    f"model_id: {effective_model}\n"
                    f"reasoning_level: {effective_reasoning_level}\n"
                    "summary: (none)"
                )
            )
            return await self._run_turn(
                task=continuation,
                agent=agent,
                parent_call_id=parent_call_id,
                session_id=session_id,
                state=state,
                parent_run_id=parent_run_id,
                parent_turn_id=parent_turn_id,
                model=model,
                reasoning_level=reasoning_level,
                reasoning_effort=reasoning_effort,
                mode=mode,
                attachments=attachments,
                execution_context=execution_context,
                late_context=resume_late_context,
                invocation_id=_state_invocation_id(state),
            )

        if supervisor is None:
            resumed = await continue_child()
        else:
            from lamtools_core.sub_agent_supervisor import bound_child_identity

            with bound_child_identity(supervisor, effective_mode or "execute", agent):
                resumed = await continue_child()
        return replace(resumed, tool_call_count=resumed.tool_call_count + 1)

    async def resume_question(
        self,
        *,
        session_id: str,
        pending_call: dict[str, Any],
        task: str,
        agent: str,
        parent_call_id: str,
        answer: str,
        question: str = "",
        skipped: bool = False,
        parent_run_id: str = "",
        parent_turn_id: str = "",
        model: str = "",
        reasoning_level: str | None = None,
        reasoning_effort: str | None = None,
        mode: str = "",
        attachments: list[str] | None = None,
        execution_context: Any | None = None,
        supervisor: Any | None = None,
    ) -> SubAgentRunResult:
        """Continue a child whose ``question`` tool waited for the user's answer.

        The answer is the child's own tool result: it is persisted in the child
        session's history (never the parent's) and forwarded to the parent
        timeline through the child's identity, so the waiting card resolves with
        the answer the user actually gave. The child keeps its logical turn and
        run; only the answer arrives.
        """
        state = await self.state_store.get(session_id)
        if state is None:
            raise ValueError("Sub-agent runtime state not found")
        call_id = str(pending_call.get("id") or "")
        effective_model = _resolve_model_id_for_capability(
            (model or "").strip() or self.model_id
        )
        explicit_reasoning = (
            str(reasoning_level or "").strip()
            or str(reasoning_effort or "").strip()
        )
        effective_reasoning_level = (
            normalize_reasoning_level(explicit_reasoning, self.reasoning_level)
            if explicit_reasoning
            else self.reasoning_level
        )
        effective_mode = self._resolve_mode(mode)
        child_sink = SubAgentEventForwardingSink(
            parent_sink=self.parent_event_sink,
            parent_session_id=self.session_prefix,
            agent=normalize_sub_session_agent_name(agent),
            task=task,
            parent_call_id=parent_call_id,
            parent_run_id=parent_run_id,
            parent_turn_id=parent_turn_id,
            type=effective_mode or "execute",
            model_id=effective_model,
            reasoning_level=effective_reasoning_level,
            invocation_id=_state_invocation_id(state),
        )
        await child_sink.emit(CoreEvent(
            name="runtime.tool.finished",
            category="tool",
            payload={
                "tool_name": "question",
                "call_id": call_id,
                "status": "ok",
                "content": answer,
                "error": "",
                "artifacts": [],
                "metadata": {
                    "question": question,
                    "answer": answer,
                    **({"skipped": True} if skipped else {}),
                },
            },
            session_id=session_id,
            run_id=state.run_id,
            tags=["tool"],
        ))
        state.metadata.pop("pending_approval", None)
        state.metadata.pop("pending_waiting_request", None)
        state.status = "running"
        state.loop_state = "continue"
        question_message = ChatMessage(
            role="tool",
            name="question",
            tool_call_id=call_id,
            content=answer,
            metadata={MESSAGE_ADDED_AT_STEP: int(getattr(state, "turn_count", 0) or 0)},
        ).to_dict()
        if isinstance(self.state_store, RuntimeCheckpointStore):
            await self.state_store.append_history(session_id, [question_message])
            await self.state_store.save(state)
        else:
            await self.state_store.save(state)
        continuation = question_answer_continuation_prompt(
            original_task=task,
            question=question,
            answer=answer,
            skipped=skipped,
        )

        async def continue_child() -> SubAgentRunResult:
            resume_late_context = (
                await supervisor.request_local_context(agent)
                if supervisor is not None
                else (
                    "[Request-local sub-agent context]\n"
                    f"name: {normalize_sub_session_agent_name(agent)}\n"
                    f"type: {effective_mode or 'execute'}\n"
                    f"model_id: {effective_model}\n"
                    f"reasoning_level: {effective_reasoning_level}\n"
                    "summary: (none)"
                )
            )
            return await self._run_turn(
                task=continuation,
                agent=agent,
                parent_call_id=parent_call_id,
                session_id=session_id,
                state=state,
                parent_run_id=parent_run_id,
                parent_turn_id=parent_turn_id,
                model=model,
                reasoning_level=reasoning_level,
                reasoning_effort=reasoning_effort,
                mode=mode,
                attachments=attachments,
                execution_context=execution_context,
                late_context=resume_late_context,
                invocation_id=_state_invocation_id(state),
            )

        if supervisor is None:
            resumed = await continue_child()
        else:
            from lamtools_core.sub_agent_supervisor import bound_child_identity

            with bound_child_identity(supervisor, effective_mode or "execute", agent):
                resumed = await continue_child()
        return replace(resumed, tool_call_count=resumed.tool_call_count + 1)

    async def resume_interrupted(
        self,
        *,
        session_id: str,
        agent: str,
        parent_call_id: str = "",
        parent_run_id: str = "",
        parent_turn_id: str = "",
        model: str = "",
        reasoning_level: str | None = None,
        reasoning_effort: str | None = None,
        mode: str = "",
        attachments: list[str] | None = None,
        execution_context: Any | None = None,
        supervisor: Any | None = None,
        prompt: str | None = None,
    ) -> SubAgentRunResult:
        """Continue a stopped child from its committed runtime state.

        ``prompt`` overrides the continuation text. The default names the
        interruption because a crash-interrupted child benefits from knowing
        that; a user pause passes ``""`` for a pure continuation, because the
        committed history already says everything and the resumed child must
        not be re-narrated by a synthetic message.
        """
        state = await self.state_store.get(session_id)
        if state is None:
            raise ValueError("Sub-agent runtime state not found")
        delegated = state.metadata.get("delegated_session") if isinstance(state.metadata, dict) else None
        original_task = (
            str(delegated.get("task") or "").strip()
            if isinstance(delegated, dict)
            else ""
        )
        effective_model = _resolve_model_id_for_capability(
            (model or "").strip() or self.model_id
        )
        explicit_reasoning = str(reasoning_level or "").strip() or str(reasoning_effort or "").strip()
        effective_reasoning_level = (
            normalize_reasoning_level(explicit_reasoning, self.reasoning_level)
            if explicit_reasoning
            else self.reasoning_level
        )
        effective_mode = self._resolve_mode(mode)
        resume_late_context = (
            await supervisor.request_local_context(agent)
            if supervisor is not None
            else (
                "[Request-local sub-agent context]\n"
                f"name: {normalize_sub_session_agent_name(agent)}\n"
                f"type: {effective_mode or 'execute'}\n"
                f"model_id: {effective_model}\n"
                f"reasoning_level: {effective_reasoning_level}\n"
                "summary: (none)"
            )
        )
        continuation = prompt if prompt is not None else (
            "Continue the interrupted sub-agent task using committed conversation history. "
            "Preserve completed work and do not repeat completed tool executions. "
            "Tools without a recorded result may have uncertain side effects."
        )
        turn_id = str((state.metadata or {}).get("turn_id") or state.run_id or "")
        if not turn_id:
            raise ValueError("Sub-agent logical turn id is missing")
        run_id = uuid.uuid4().hex
        kwargs = {
            "task": continuation,
            "delegated_task": original_task,
            "agent": agent,
            "parent_call_id": parent_call_id,
            "session_id": session_id,
            "state": state,
            "run_id": run_id,
            "turn_id": turn_id,
            "origin": "turn_resume",
            "parent_run_id": parent_run_id,
            "parent_turn_id": parent_turn_id,
            "model": effective_model,
            "reasoning_level": effective_reasoning_level,
            "mode": effective_mode or "",
            "attachments": attachments,
            "execution_context": execution_context,
            "late_context": resume_late_context,
        }
        if supervisor is None:
            return await self._run_turn(**kwargs)
        from lamtools_core.sub_agent_supervisor import bound_child_identity

        with bound_child_identity(supervisor, effective_mode or "execute", agent):
            return await self._run_turn(**kwargs)

    async def _run_turn(self, **kwargs) -> SubAgentRunResult:
        profile = self._profile_from_state(kwargs["state"])
        service, owned = self._new_command_service(profile)
        try:
            return await self._run_turn_in_context(mcp_service=service, profile_spec=profile, **kwargs)
        finally:
            if owned:
                await service.close()

    async def _run_turn_in_context(
        self,
        *,
        mcp_service: Any,
        profile_spec: Any | None = None,
        task: str,
        delegated_task: str | None = None,
        agent: str,
        parent_call_id: str,
        session_id: str,
        state: Any,
        run_id: str = "",
        turn_id: str = "",
        origin: str = "",
        parent_run_id: str = "",
        parent_turn_id: str = "",
        model: str = "",
        reasoning_level: str | None = None,
        reasoning_effort: str | None = None,
        mode: str = "",
        attachments: list[str] | None = None,
        execution_context: Any | None = None,
        late_context: str = "",
        invocation_id: str = "",
    ) -> SubAgentRunResult:
        preset_id = ""
        preset_tools: list[str] | None = None
        preset_prompt = ""
        if self.agent_presets is not None:
            metadata = state.metadata if isinstance(state.metadata, dict) else {}
            preset_id = str(metadata.get("agent_preset") or "").strip()
            if preset_id:
                try:
                    composed = self.agent_presets.compose(
                        preset_id,
                        mode=mode,
                        allowed_tools=None,
                        model=model,
                        prompt=late_context,
                    )
                except KeyError:
                    composed = None
                if composed is not None:
                    mode = composed.mode or mode
                    model = composed.model or model
                    late_context = composed.prompt
                    preset_tools = composed.allowed_tools
                    preset_prompt = composed.preset_prompt
        # Same early resolution as run() — translate display_name to model_id.
        effective_model = _resolve_model_id_for_capability(
            (model or "").strip() or self.model_id
        )
        explicit_reasoning = str(reasoning_level or "").strip() or str(reasoning_effort or "").strip()
        effective_reasoning_level = (
            normalize_reasoning_level(explicit_reasoning, self.reasoning_level)
            if explicit_reasoning
            else self.reasoning_level
        )
        effective_mode = self._resolve_mode(mode)
        user_content = await self._fetch_attachment_content(task, list(attachments or []), model_id=effective_model)
        disabled_tools = self._disabled_tools()
        if preset_tools:
            probe = self._build_toolbox(disabled_tools, active_mode=effective_mode, mcp_service=mcp_service)
            disabled_tools |= {spec.name for spec in probe.tool_specs()} - set(preset_tools)
        toolbox = self._build_toolbox(disabled_tools, active_mode=effective_mode, mcp_service=mcp_service)
        if profile_spec is not None:
            from lamtools_core.plugin_system.profiles import apply_profile
            counters = apply_profile(toolbox, profile_spec)
            counters.update(state.metadata.get("run_profile_budget") or {})
            bodies = [self.skill_registry.load_prompt_content(self.work_root, name) for name in profile_spec.skills]
            late_context = "\n\n".join([*bodies, late_context]).strip()
        agent_name = normalize_sub_session_agent_name(agent)
        child_sink = SubAgentEventForwardingSink(
            parent_sink=self.parent_event_sink,
            parent_session_id=self.session_prefix,
            agent=agent_name,
            task=delegated_task or task,
            parent_call_id=parent_call_id,
            parent_run_id=parent_run_id,
            parent_turn_id=parent_turn_id,
            type=effective_mode or "execute",
            model_id=effective_model,
            reasoning_level=effective_reasoning_level,
            invocation_id=invocation_id,
        )
        kernel = self._build_kernel(
            toolbox=toolbox,
            event_sink=child_sink,
            model_id=effective_model,
            reasoning_level=effective_reasoning_level,
            active_mode=effective_mode,
            late_context=late_context,
            preset_prompt=preset_prompt,
        )
        workflow_metadata = _workflow_context_metadata(
            execution_context,
            attachments=list(attachments or []),
        )
        state.metadata["sub_invocation_id"] = child_sink.invocation_id
        if preset_id:
            state.metadata["agent_preset"] = preset_id
        result = await kernel.run(
            RuntimeTurnInput(
                user_message=task,
                user_content=user_content if user_content is not task else None,
                state=state,
                run_id=run_id or state.run_id,
                turn_id=turn_id,
                metadata={
                    **deepcopy(workflow_metadata),
                    "session_id": session_id,
                    "model_id": effective_model,
                    "active_mode": effective_mode,
                    "reasoning_level": effective_reasoning_level,
                    "thinking_enabled": self.thinking_enabled,
                    "thinking_budget": self.thinking_budget,
                    "actor_kind": "sub_agent",
                    **({"origin": origin} if origin else {}),
                    **({"agent_preset": preset_id} if preset_id else {}),
                    "delegated_session": {
                        "session_id": session_id,
                        "parent_thread_id": self.session_prefix,
                        "agent": agent_name,
                        "task": delegated_task or task,
                        "model": effective_model,
                        "mode": effective_mode or "execute",
                        "reasoning_level": effective_reasoning_level,
                        "attachments": list(attachments or []),
                        "parent_call_id": parent_call_id,
                        "parent_run_id": parent_run_id,
                        "parent_turn_id": parent_turn_id,
                    },
                    **({"workflow_execution": workflow_metadata} if workflow_metadata else {}),
                    **(
                        {"runtime_snapshot": deepcopy(self.runtime_snapshot)}
                        if self.runtime_snapshot is not None and "runtime_snapshot" not in workflow_metadata
                        else {}
                    ),
                },
            )
        )
        await self._save_profile_budget(result, toolbox)
        return self._result_from_kernel(result, model_id=effective_model)

__all__ = ["KernelSubAgentRunner"]
