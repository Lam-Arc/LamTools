from __future__ import annotations

"""Writer adapter for reusable delegated sub-sessions."""

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from lamtools_core.agent import SUB_AGENT_SPEC
from lamtools_core.runtime import RuntimeState
from lamtools_core.sub_session import (
    SubSessionManager,
    SubSessionRuntimeStateStore,
    filter_sub_agent_tools,
    normalize_sub_session_agent_name,
)

@dataclass(frozen=True)
class AgentSpec:
    name: str
    description: str
    aliases: tuple[str, ...] = ()
    modes: tuple[str, ...] = ("auto",)
    capabilities: tuple[str, ...] = ()
    can_parallel: bool = False
    can_call_agents: bool = False
    max_depth: int = 0


@dataclass
class AgentCall:
    name: str
    task: str
    mode: str = "auto"
    clean: bool = False
    options: dict[str, Any] = field(default_factory=dict)
    parent_agent_id: str | None = None
    depth: int = 0


@dataclass
class AgentRunResult:
    name: str
    output: str
    metadata: dict[str, Any] = field(default_factory=dict)


class AgentRegistry:
    """Name/alias registry for Writer agents."""

    def __init__(self) -> None:
        self._specs: dict[str, AgentSpec] = {}
        self._aliases: dict[str, str] = {}

    def register(self, spec: AgentSpec) -> None:
        key = self._normalize(spec.name)
        self._specs[key] = spec
        self._aliases[key] = key
        for alias in spec.aliases:
            self._aliases[self._normalize(alias)] = key

    def resolve(self, name: str) -> AgentSpec | None:
        canonical = self._aliases.get(self._normalize(name))
        if canonical is None:
            return None
        return self._specs.get(canonical)

    def names(self) -> list[str]:
        return sorted(spec.name for spec in self._specs.values())

    @staticmethod
    def _normalize(name: str) -> str:
        return (name or "").strip().lower()


def default_agent_registry() -> AgentRegistry:
    registry = AgentRegistry()
    registry.register(AgentSpec(
        name=SUB_AGENT_SPEC.name,
        aliases=(),
        description=SUB_AGENT_SPEC.description,
        modes=SUB_AGENT_SPEC.modes,
        capabilities=SUB_AGENT_SPEC.capabilities,
        can_parallel=True,
        can_call_agents=False,
        max_depth=SUB_AGENT_SPEC.max_depth,
    ))
    return registry


class AgentRuntime:
    """Dispatches registered agents and owns per-runtime agent caches."""

    AGENT_TOOL_ALLOWLIST: dict[str, frozenset[str]] = {
        "sub": frozenset(),
    }

    def __init__(
        self,
        *,
        llm_client: Any,
        design_mode_selector: Callable[[str], str],
        tool_runner: Callable[[str, dict[str, Any]], Awaitable[str]] | None = None,
        runtime_fact_recorder: Callable[..., Awaitable[str | None]] | None = None,
        registry: AgentRegistry | None = None,
        model_tools: list[dict[str, Any]] | None = None,
        model_tools_provider: Callable[[], list[dict[str, Any]]] | None = None,
        parent_state_store: Any | None = None,
        sub_agent_kernel_runner: Callable[
            [str, AgentCall, str, frozenset[str]],
            Awaitable[tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]],
        ] | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._design_mode_selector = design_mode_selector
        self._tool_runner = tool_runner
        self._runtime_fact_recorder = runtime_fact_recorder
        self.registry = registry or default_agent_registry()
        self._model_tools = list(model_tools or [])
        self._model_tools_provider = model_tools_provider
        self._parent_state_store = parent_state_store
        self._sub_agent_kernel_runner = sub_agent_kernel_runner
        self._cache: dict[str, AgentRunResult] = {}
        self._agent_stack: list[str] = []
        self._agent_tool_stack: list[frozenset[str]] = []
        self._sub_session_manager = SubSessionManager()
        self._fallback_parent_states: dict[str, RuntimeState] = {}

    async def run(
        self,
        session_id: str,
        call: AgentCall,
        *,
        parent_state: RuntimeState | None = None,
    ) -> AgentRunResult:
        spec = self.registry.resolve(call.name)
        if spec is None:
            available = ", ".join(self.registry.names()) or "(none)"
            return AgentRunResult(
                name=call.name,
                output=(
                    f"Unknown agent: {call.name or '(empty)'}.\n"
                    f"Available agents: {available}.\n"
                    "Call a registered agent tool such as sub_agent."
                ),
                metadata={"error": "unknown_agent", "available_agents": self.registry.names()},
            )

        if call.depth > spec.max_depth:
            return AgentRunResult(
                name=spec.name,
                output=(
                    f"Agent depth rejected: {spec.name} depth={call.depth} exceeds max_depth={spec.max_depth}."
                ),
                metadata={"error": "agent_depth_exceeded", "max_depth": spec.max_depth},
            )

        if spec.name == "sub":
            if parent_state is None:
                parent_state = self._fallback_parent_states.setdefault(
                    session_id,
                    RuntimeState(session_id=session_id),
                )
            sub_session = self._sub_session_manager.get_or_create(
                parent_state,
                self._agent_name_for_call(call),
            )
            call.options.setdefault("_agent_name", sub_session.agent_name)
            call.options.setdefault("_agent_index", sub_session.agent_index)
            call.options.setdefault("_sub_session_id", sub_session.session_id)
            call.options.setdefault(
                "_sub_session_state_store",
                SubSessionRuntimeStateStore(
                    parent_state,
                    parent_state_store=self._parent_state_store,
                ),
            )
            call.options.setdefault("_parent_session_id", parent_state.session_id)
            call.options.setdefault("_parent_run_id", parent_state.run_id)

        available_tools = self._available_tools_for_call(spec, call)
        run_id = f"{spec.name}-{uuid4().hex[:12]}"
        sub_line_id = f"subline-{run_id}"
        call.options.setdefault("_agent_run_id", run_id)
        call.options.setdefault("_sub_line_id", sub_line_id)
        self._agent_stack.append(spec.name)
        self._agent_tool_stack.append(available_tools)
        try:
            if spec.name == "sub":
                result = await self._run_sub(session_id, spec, call)
            else:
                raise RuntimeError(f"Agent registered but not implemented: {spec.name}")
            result.metadata = self._standard_agent_metadata(spec, call, result)
            return result
        finally:
            self._agent_tool_stack.pop()
            self._agent_stack.pop()

    def _standard_agent_metadata(
        self,
        spec: AgentSpec,
        call: AgentCall,
        result: AgentRunResult,
    ) -> dict[str, Any]:
        metadata = dict(result.metadata or {})
        output_data = self._json_obj(result.output)
        tool_calls = metadata.get("tool_calls")
        if not isinstance(tool_calls, list):
            tool_calls = []
        referenced_tools: list[str] = []
        for item in tool_calls:
            if isinstance(item, dict) and item.get("name"):
                referenced_tools.append(str(item["name"]))
        for item in metadata.get("referenced_tools", []):
            if item:
                referenced_tools.append(str(item))

        substeps = metadata.get("substeps")
        if not isinstance(substeps, list):
            substeps = []
        if spec.name != "sub" and tool_calls:
            substeps.append({
                "label": "调用工具",
                "value": ", ".join(referenced_tools) or f"{len(tool_calls)} tools",
                "status": "completed",
            })
        verdict = output_data.get("verdict") or metadata.get("verdict")
        if verdict:
            substeps.append({
                "label": "结论",
                "value": str(verdict),
                "status": "completed",
            })

        actual_agent = str(metadata.get("agent") or output_data.get("agent") or spec.name)
        updates = {
            "agent_run_id": str(call.options.get("_agent_run_id") or ""),
            "sub_line_id": str(call.options.get("_sub_line_id") or ""),
            "agent_name": actual_agent,
            "agent": actual_agent,
            "runtime_agent": spec.name,
            "task": call.task,
            "mode": call.mode,
            "status": metadata.get("status") or "completed",
            "capabilities": list(spec.capabilities),
            "can_call_agents": spec.can_call_agents,
            "tools": list(metadata.get("tools") or sorted(self._available_tools_for_call(spec, call))),
            "tool_calls": tool_calls,
        }
        if spec.name != "sub":
            updates["substeps"] = substeps
            updates["referenced_tools"] = sorted(set(referenced_tools))
            updates["final_answer"] = metadata.get("final_answer") or self._agent_final_answer(output_data, result.output)
        metadata.update(updates)
        return metadata

    def _available_tools_for_call(self, spec: AgentSpec, call: AgentCall) -> frozenset[str]:
        if spec.name != "sub":
            return self.AGENT_TOOL_ALLOWLIST.get(spec.name, frozenset())

        available = set(self._parent_tool_names())
        return frozenset(available)

    def _agent_name_for_call(self, call: AgentCall) -> str:
        return normalize_sub_session_agent_name(
            call.options.get("_agent_name")
            or call.options.get("agent")
            or call.options.get("name")
        )

    def _parent_tool_names(self) -> tuple[str, ...]:
        names: list[str] = []
        tools = self._model_tools_provider() if self._model_tools_provider is not None else self._model_tools
        for tool in filter_sub_agent_tools(tools):
            function = tool.get("function") if isinstance(tool, dict) else None
            if isinstance(function, dict):
                name = str(function.get("name") or "").strip()
            else:
                name = str(tool.get("name") or "").strip() if isinstance(tool, dict) else ""
            if name:
                names.append(name)
        return tuple(sorted(dict.fromkeys(names)))

    @staticmethod
    def _agent_final_answer(output_data: dict[str, Any], fallback: str) -> str:
        for key in (
            "summary",
            "handoff",
            "verdict",
            "recommended_next_action",
            "next_fix",
            "commercial_safety",
        ):
            value = output_data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for key in ("blocking_issues", "required_next_actions", "risks", "facts"):
            value = output_data.get(key)
            if isinstance(value, list) and value:
                return "; ".join(str(item) for item in value[:3])
        return str(fallback or "").strip()[:1000]

    async def _run_sub(self, session_id: str, spec: AgentSpec, call: AgentCall) -> AgentRunResult:
        agent_name = self._agent_name_for_call(call)
        available_tools = self._available_tools_for_call(spec, call)
        prompt = call.task
        tool_records: list[dict[str, Any]] = []
        reasoning_blocks: list[dict[str, Any]] = []
        diagnostics: dict[str, Any] = {}
        try:
            if self._sub_agent_kernel_runner is None:
                raise RuntimeError("SubAgent must run through the core kernel loop")
            data, tool_records, reasoning_blocks, diagnostics = await self._sub_agent_kernel_runner(
                agent_name,
                call,
                prompt,
                available_tools,
            )
            if not data:
                diagnostics.setdefault("fallback_reason", "empty_final_output")
                data = {"content": self._sub_agent_failure_text(agent_name, call, diagnostics)}
        except Exception as exc:
            diagnostics = {
                "fallback_reason": "exception",
                "exception_type": type(exc).__name__,
                "exception": self._truncate(str(exc), 500),
            }
            data = {"content": self._sub_agent_failure_text(agent_name, call, diagnostics)}
        used_fallback = bool(diagnostics.get("fallback_reason"))

        output = str(data.get("content") or self._sub_agent_failure_text(agent_name, call, diagnostics))
        return AgentRunResult(spec.name, output, {
            "agent_run_id": str(call.options.get("_agent_run_id") or ""),
            "sub_line_id": str(call.options.get("_sub_line_id") or ""),
            "agent": agent_name,
            "agent_index": str(call.options.get("_agent_index") or ""),
            "sub_session_id": str(call.options.get("_sub_session_id") or ""),
            "tools": sorted(available_tools),
            "tool_calls": tool_records,
            "reasoning_blocks": reasoning_blocks,
            "diagnostics": diagnostics,
            **({"fallback_reason": diagnostics.get("fallback_reason", "unknown")} if used_fallback else {}),
        })

    def _sub_agent_failure_text(
        self,
        agent_name: str,
        call: AgentCall,
        diagnostics: dict[str, Any],
    ) -> str:
        reason = (
            diagnostics.get("error")
            or diagnostics.get("exception")
            or diagnostics.get("fallback_reason")
            or "子代理没有返回正文。"
        )
        reason_text = self._truncate(str(reason), 1000)
        runner = str(diagnostics.get("runner") or "sub_agent")
        decision = str(diagnostics.get("decision") or "unknown")
        tool_count = diagnostics.get("tool_call_count")
        event_count = diagnostics.get("event_count")
        observed = []
        if tool_count is not None:
            observed.append(f"工具调用数：{tool_count}")
        if event_count is not None:
            observed.append(f"事件数：{event_count}")
        observed_text = f"\n- 观测：{'；'.join(observed)}" if observed else ""
        return (
            f"子代理 {agent_name} 执行失败。\n\n"
            f"- 任务：{call.task}\n"
            f"- 运行器：{runner}\n"
            f"- 决策：{decision}{observed_text}\n"
            f"- 失败原因：{reason_text}\n\n"
            "主 Writer 不应把这次子任务当作已完成；请根据失败原因修正配置或改用其它可用路径。"
        )

    @staticmethod
    def _truncate(text: Any, limit: int) -> str:
        value = str(text or "")
        if len(value) <= limit:
            return value
        return value[:limit] + "...[truncated]"


    async def _tool(self, name: str, params: dict[str, Any]) -> str:
        current_agent = self._agent_stack[-1] if self._agent_stack else ""
        allowlist = self._agent_tool_stack[-1] if self._agent_tool_stack else self.AGENT_TOOL_ALLOWLIST.get(current_agent)
        if allowlist is not None and name not in allowlist:
            return (
                f"AGENT TOOL REJECTED: agent={current_agent or 'unknown'} "
                f"cannot call tool={name}. Allowed tools: {', '.join(sorted(allowlist)) or '(none)'}."
            )
        if self._tool_runner is None:
            return f"Tool unavailable for agent runtime: {name}"
        try:
            return await self._tool_runner(name, params)
        except Exception as exc:
            return json_dumps({
                "ok": False,
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
            })

    @staticmethod
    def _json_obj(text: Any) -> dict[str, Any]:
        if isinstance(text, dict):
            return text
        if not isinstance(text, str):
            return {}
        value = text.strip()
        if not value:
            return {}
        for candidate in AgentRuntime._json_candidates(value):
            try:
                data = json_loads(candidate)
                if isinstance(data, dict):
                    return data
            except Exception:
                continue
        try:
            import json

            decoder = json.JSONDecoder()
            for index, char in enumerate(value):
                if char != "{":
                    continue
                try:
                    data, _ = decoder.raw_decode(value[index:])
                except Exception:
                    continue
                if isinstance(data, dict):
                    return data
        except Exception:
            return {}
        return {}

    @staticmethod
    def _json_candidates(value: str) -> list[str]:
        candidates = [value]
        fence = re.fullmatch(r"```(?:json|JSON)?\s*([\s\S]*?)\s*```", value)
        if fence:
            candidates.append(fence.group(1).strip())
        for fence in re.finditer(r"```(?:json|JSON)?\s*([\s\S]*?)\s*```", value):
            candidates.append(fence.group(1).strip())
        return candidates


def json_dumps(data: Any) -> str:
    import json

    return json.dumps(data, ensure_ascii=False, indent=2)


def json_loads(text: str) -> Any:
    import json

    return json.loads(text)
