from __future__ import annotations

"""Generic runtime for delegated Writer agents.

This module registers durable sub-agents. Core provides the reusable agent
runtime mechanics; Writer decides which delegated roles are available.
"""

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from lamtools_core.agent import SUB_AGENT_SPEC, build_sub_agent_prompt
from lamtools_core.runtime import RuntimeState
from lamtools_core.sub_session import (
    SubSessionManager,
    SubSessionRuntimeStateStore,
    filter_sub_agent_tools,
    normalize_sub_session_agent_name,
)
from lamtools_core.tool.sub_agent import (
    SubAgentDefinition,
    definition_map,
    delete_project_sub_agent_definition,
    parse_sub_agent_definition,
    project_sub_agent_definition_path,
    render_sub_agent_definition,
    validate_project_sub_agent_name,
    write_project_sub_agent_definition,
)

SUB_AGENT_READ_TOOLS = frozenset({
    "inspect_project",
    "read_file",
    "list_dir",
    "search_files",
    "search_content",
    "recall_session",
    "load_skill",
    "web_search",
    "web_fetch",
    "browser_check",
    "git_status",
    "git_diff",
})

SUB_AGENT_REVIEW_TOOLS = frozenset({
    *SUB_AGENT_READ_TOOLS,
    "run_tests",
})

SUB_AGENT_IMPLEMENTATION_TOOLS = frozenset({
    *SUB_AGENT_REVIEW_TOOLS,
    "write_file",
    "edit_file",
})

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


BUILTIN_SUB_AGENT_DEFINITIONS: tuple[SubAgentDefinition, ...] = (
    SubAgentDefinition(
        name="default",
        aliases=("general-purpose", "general_purpose", "general"),
        description="General-purpose delegated agent for focused investigation and handoff.",
        role="general",
        tools=tuple(sorted(SUB_AGENT_READ_TOOLS)),
        developer_instructions=(
            "Handle broad delegated tasks conservatively. Prefer reading and searching before conclusions. "
            "Return concise findings, risks, and a handoff for the main Writer."
        ),
    ),
    SubAgentDefinition(
        name="explorer",
        aliases=("explore", "researcher", "searcher"),
        description="Read-only exploration agent for codebase search, documentation lookup, and evidence gathering.",
        role="research",
        tools=tuple(sorted(SUB_AGENT_READ_TOOLS)),
        developer_instructions=(
            "Explore only. Gather facts with file/search/web tools, cite concrete evidence in findings, "
            "and do not modify files or run broad commands."
        ),
    ),
    SubAgentDefinition(
        name="worker",
        aliases=("coder", "coding", "implementer"),
        description="Implementation worker for small scoped code changes under reduced permissions.",
        role="implementation",
        tools=tuple(sorted(SUB_AGENT_IMPLEMENTATION_TOOLS)),
        developer_instructions=(
            "Implement only the delegated slice. Keep edits small, use existing patterns, and report changed files, "
            "verification, risks, and what the main Writer must review before acceptance."
        ),
    ),
    SubAgentDefinition(
        name="reviewer",
        aliases=("review", "qa", "tester", "diagnostic"),
        description="Review and diagnosis agent for tests, regressions, and quality checks.",
        role="review",
        tools=tuple(sorted(SUB_AGENT_REVIEW_TOOLS)),
        developer_instructions=(
            "Review, diagnose, and verify. You may run targeted tests, but do not edit files. "
            "Return blocking issues, likely causes, and the smallest next action."
        ),
    ),
)


def load_sub_agent_definitions(work_root: str | Path | None = None) -> tuple[SubAgentDefinition, ...]:
    """Load project/user subagent definitions, with project files overriding built-ins.

    Definition files follow the Claude-style shape:

    ---
    name: explorer
    description: Read-only exploration agent
    tools:
      - read_file
      - search_content
    model: ""
    ---
    Developer instructions...
    """
    definitions: dict[str, SubAgentDefinition] = {
        item.name: item for item in BUILTIN_SUB_AGENT_DEFINITIONS
    }
    for directory, source in _sub_agent_definition_dirs(work_root):
        for path in sorted(directory.glob("*.md")):
            parsed = parse_sub_agent_definition(path, source)
            if parsed is not None:
                definitions[parsed.name] = parsed
    return tuple(definitions[name] for name in sorted(definitions))


def sub_agent_definition_map(work_root: str | Path | None = None) -> dict[str, SubAgentDefinition]:
    return definition_map(load_sub_agent_definitions(work_root))


def _sub_agent_definition_dirs(work_root: str | Path | None) -> list[tuple[Path, str]]:
    dirs: list[tuple[Path, str]] = []
    home = Path.home()
    for directory in (home / ".writer" / "agents", home / ".claude" / "agents"):
        if directory.is_dir():
            dirs.append((directory, "user"))
    if work_root:
        root = Path(work_root).resolve()
        for directory in (root / ".lamtools" / "agents", root / ".writer" / "agents", root / ".claude" / "agents"):
            if directory.is_dir():
                dirs.append((directory, "project"))
    return dirs


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
        work_root: str | Path | None = None,
        sub_agent_llm_client_factory: Callable[[SubAgentDefinition, AgentCall], Awaitable[Any]] | None = None,
        sub_agent_workspace_factory: Callable[[SubAgentDefinition, AgentCall], Awaitable[dict[str, Any] | None]] | None = None,
        sub_agent_kernel_runner: Callable[
            [SubAgentDefinition, AgentCall, str, frozenset[str], dict[str, Any]],
            Awaitable[tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]],
        ] | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._design_mode_selector = design_mode_selector
        self._tool_runner = tool_runner
        self._runtime_fact_recorder = runtime_fact_recorder
        self.registry = registry or default_agent_registry()
        self._model_tools = list(model_tools or [])
        self._sub_agent_definitions = sub_agent_definition_map(work_root)
        self._sub_agent_llm_client_factory = sub_agent_llm_client_factory
        self._sub_agent_workspace_factory = sub_agent_workspace_factory
        self._sub_agent_kernel_runner = sub_agent_kernel_runner
        self._cache: dict[str, AgentRunResult] = {}
        self._agent_stack: list[str] = []
        self._agent_tool_stack: list[frozenset[str]] = []
        self._agent_workspace_stack: list[dict[str, Any]] = []
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
            call.options.setdefault("_sub_session_state_store", SubSessionRuntimeStateStore(parent_state))

        available_tools = self._available_tools_for_call(spec, call)
        run_id = f"{spec.name}-{uuid4().hex[:12]}"
        sub_line_id = f"subline-{run_id}"
        call.options.setdefault("_agent_run_id", run_id)
        call.options.setdefault("_sub_line_id", sub_line_id)
        definition = self._sub_agent_definition_for_call(call) if spec.name == "sub" else None
        workspace = await self._workspace_for_call(spec, call)
        self._agent_stack.append(spec.name)
        self._agent_tool_stack.append(available_tools)
        self._agent_workspace_stack.append(workspace)
        try:
            if spec.name == "sub":
                result = await self._run_sub(session_id, spec, call)
            else:
                raise RuntimeError(f"Agent registered but not implemented: {spec.name}")
            result.metadata = self._standard_agent_metadata(spec, call, result)
            return result
        finally:
            self._agent_tool_stack.pop()
            self._agent_workspace_stack.pop()
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

    def _sub_agent_definition_for_call(self, call: AgentCall) -> SubAgentDefinition:
        agent_name = self._agent_name_for_call(call)
        return SubAgentDefinition(
            name=agent_name,
            description="Reusable delegated sub session",
            role="sub",
            developer_instructions="",
            tools=tuple(sorted(self._parent_tool_names())),
            source="runtime",
        )

    async def _workspace_for_call(self, spec: AgentSpec, call: AgentCall) -> dict[str, Any]:
        _ = spec, call
        return {}

    def _agent_name_for_call(self, call: AgentCall) -> str:
        return normalize_sub_session_agent_name(
            call.options.get("_agent_name")
            or call.options.get("agent")
            or call.options.get("name")
        )

    def _parent_tool_names(self) -> tuple[str, ...]:
        names: list[str] = []
        for tool in filter_sub_agent_tools(self._model_tools):
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
        definition = self._sub_agent_definition_for_call(call)
        role = str(call.options.get("role") or definition.role).strip() or definition.role
        expected_output = str(call.options.get("expected_output") or "focused findings and concrete next steps").strip()
        context = call.options.get("context", {})
        workspace = self._agent_workspace_stack[-1] if self._agent_workspace_stack else {}
        task_context = {
            "context_inheritance": "sub_session",
            "delegated_by": "Writer",
            "full_main_conversation": False,
            "agent_name": definition.name,
            "agent_index": str(call.options.get("_agent_index") or ""),
            "sub_session_id": str(call.options.get("_sub_session_id") or ""),
            "project_context": context if isinstance(context, dict) else {"value": context},
        }
        available_tools = self._available_tools_for_call(spec, call)
        developer_instructions = str(call.options.get("developer_instructions") or definition.developer_instructions)
        prompt = build_sub_agent_prompt(
            member_name="Writer",
            agent_name=definition.name,
            role=role,
            task=call.task,
            expected_output=expected_output,
            context=json_dumps(task_context),
            tools=tuple(sorted(available_tools)),
            tool_policy=(
                "权限等同主 Agent；只能调用列出的工具。"
                "不能继续调用 sub_agent 或派发其它 Agent。"
            ),
            developer_instructions=developer_instructions,
        )
        tool_records: list[dict[str, Any]] = []
        reasoning_blocks: list[dict[str, Any]] = []
        diagnostics: dict[str, Any] = {}
        try:
            if self._sub_agent_kernel_runner is None:
                raise RuntimeError("SubAgent must run through the core kernel loop")
            data, tool_records, reasoning_blocks, diagnostics = await self._sub_agent_kernel_runner(
                definition,
                call,
                prompt,
                available_tools,
                workspace,
            )
            if not data:
                diagnostics.setdefault("fallback_reason", "empty_final_output")
                data = {"content": self._sub_agent_failure_text(definition, call, role, diagnostics)}
        except Exception as exc:
            diagnostics = {
                "fallback_reason": "exception",
                "exception_type": type(exc).__name__,
                "exception": self._truncate(str(exc), 500),
            }
            data = {"content": self._sub_agent_failure_text(definition, call, role, diagnostics)}
        used_fallback = bool(diagnostics.get("fallback_reason"))

        output = str(data.get("content") or self._sub_agent_failure_text(definition, call, role, diagnostics))
        delivery = diagnostics.get("workspace_delivery")
        delivery_meta = dict(delivery) if isinstance(delivery, dict) else {}
        changed_files = delivery_meta.get("changed_files") or delivery_meta.get("paths") or []
        if not isinstance(changed_files, list):
            changed_files = []
        changed_files = [str(item) for item in changed_files if str(item)]
        return AgentRunResult(spec.name, output, {
            "agent_run_id": str(call.options.get("_agent_run_id") or ""),
            "sub_line_id": str(call.options.get("_sub_line_id") or ""),
            "role": role,
            "agent": definition.name,
            "agent_index": str(call.options.get("_agent_index") or ""),
            "sub_session_id": str(call.options.get("_sub_session_id") or ""),
            "subagent_description": definition.description,
            "model": str(call.options.get("model") or definition.model or ""),
            "workspace_delivery": delivery_meta,
            "changed_files": changed_files,
            "changed_files_count": len(changed_files),
            "tools": sorted(available_tools),
            "tool_calls": tool_records,
            "reasoning_blocks": reasoning_blocks,
            "diagnostics": diagnostics,
            **({"fallback_reason": diagnostics.get("fallback_reason", "unknown")} if used_fallback else {}),
        })

    def _sub_agent_failure_text(
        self,
        definition: SubAgentDefinition,
        call: AgentCall,
        role: str,
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
            f"子代理 {definition.name} 执行失败。\n\n"
            f"- 角色：{role}\n"
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
        workspace = self._agent_workspace_stack[-1] if self._agent_workspace_stack else {}
        if workspace.get("work_root"):
            params = dict(params)
            params["__agent_work_root"] = str(workspace["work_root"])
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
