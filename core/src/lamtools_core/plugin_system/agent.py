"""Agent takeover declarations: prompt, tools, approval, context and scope.

user:“插件可以自定义整个 Agent”+提示词、工具白名单、审批、上下文四项由插件
声明；同一时间只有一套生效，优先级是会话、模式、全局、Core 默认。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .capabilities import CapabilityError
from .manifest import PluginManifest

VALID_APPROVAL = ("ask", "auto", "block")


@dataclass(frozen=True)
class PluginAgentSpec:
    plugin: str
    scope: str
    mode: str = ""
    prompt: Path | None = None
    prompt_text: str = ""
    tools: tuple[str, ...] | None = None
    approval: str = "ask"
    context: tuple[Path, ...] = ()
    exclusive_tools: bool = False


@dataclass
class AgentAssembly:
    agents: list[PluginAgentSpec] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class AgentPlan:
    source: str
    agent: PluginAgentSpec


def _text_asset(manifest: PluginManifest, value: Any, *, key: str) -> tuple[Path, str]:
    text = str(value or "").strip()
    if not text:
        raise CapabilityError(manifest.name, f"{key} path is empty")
    if not text.startswith("./"):
        raise CapabilityError(manifest.name, f"{key} path must start with './': {text}")
    candidate = (manifest.root / text[2:]).resolve()
    if not candidate.is_relative_to(manifest.root):
        raise CapabilityError(manifest.name, f"{key} path is outside the plugin root: {text}")
    if candidate.suffix.lower() not in (".md", ".txt"):
        raise CapabilityError(manifest.name, f"{key} must be a .md or .txt file: {text}")
    if not candidate.is_file():
        raise CapabilityError(manifest.name, f"{key} file is missing: {text}")
    try:
        content = candidate.read_text(encoding="utf-8-sig").strip()
    except OSError as exc:
        raise CapabilityError(manifest.name, f"{key} file is unreadable: {text}") from exc
    if not content:
        raise CapabilityError(manifest.name, f"{key} file is empty: {text}")
    return candidate, content


def _parse_tools(manifest: PluginManifest, value: Any) -> tuple[str, ...] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise CapabilityError(manifest.name, "agent.tools must be an array")
    tools: list[str] = []
    seen: set[str] = set()
    for item in value:
        name = str(item or "").strip()
        if not name:
            raise CapabilityError(manifest.name, "agent.tools contains an empty name")
        if name in seen:
            raise CapabilityError(manifest.name, f"duplicate tool '{name}' in agent.tools")
        seen.add(name)
        tools.append(name)
    return tuple(tools)


def _parse_context(manifest: PluginManifest, value: Any) -> tuple[Path, ...]:
    if value is None:
        return ()
    raw_items: Iterable[Any]
    if isinstance(value, str):
        raw_items = [value]
    elif isinstance(value, list):
        raw_items = value
    else:
        raise CapabilityError(manifest.name, "agent.context must be a string or an array")
    paths: list[Path] = []
    for index, item in enumerate(raw_items):
        path, _content = _text_asset(manifest, item, key=f"agent.context[{index}]")
        paths.append(path)
    return tuple(paths)


def read_agent(manifest: PluginManifest) -> PluginAgentSpec | None:
    raw = manifest.raw.get("agent")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise CapabilityError(manifest.name, "agent must be an object")

    scope = manifest.scope
    mode = str(raw.get("mode") or "").strip()
    if scope == "mode" and not mode:
        raise CapabilityError(manifest.name, "agent.mode is required when scope is mode")

    prompt_path: Path | None = None
    prompt_text = ""
    if raw.get("prompt") is not None:
        prompt_path, prompt_text = _text_asset(manifest, raw.get("prompt"), key="agent prompt")

    approval = str(raw.get("approval") or "ask").strip().lower()
    if approval not in VALID_APPROVAL:
        raise CapabilityError(
            manifest.name,
            f"agent approval must be one of {', '.join(VALID_APPROVAL)}: {approval}",
        )

    return PluginAgentSpec(
        plugin=manifest.name,
        scope=scope,
        mode=mode,
        prompt=prompt_path,
        prompt_text=prompt_text,
        tools=_parse_tools(manifest, raw.get("tools")),
        approval=approval,
        context=_parse_context(manifest, raw.get("context")),
        exclusive_tools=bool(raw.get("exclusiveTools", False)),
    )


def assemble_agents(manifests: list[PluginManifest]) -> AgentAssembly:
    """Collect enabled agents; a second global agent is an explicit conflict."""
    assembly = AgentAssembly()
    global_owner = ""
    for manifest in manifests:
        if not manifest.enabled:
            continue
        try:
            agent = read_agent(manifest)
        except CapabilityError as exc:
            assembly.errors.append({"plugin": manifest.name, "error": exc.message})
            continue
        if agent is None:
            continue
        if agent.scope == "global":
            if global_owner:
                assembly.errors.append(
                    {
                        "plugin": manifest.name,
                        "error": f"global agent is already declared by plugin '{global_owner}'",
                    }
                )
                continue
            global_owner = manifest.name
        assembly.agents.append(agent)
    return assembly


def resolve_agent_plan(
    agents: list[PluginAgentSpec],
    *,
    active_mode: str = "",
    session_plugin: str | None = None,
) -> AgentPlan | None:
    """Return the winning agent: session, then mode, then global."""
    if session_plugin:
        for agent in agents:
            if agent.scope == "session" and agent.plugin == session_plugin:
                return AgentPlan(source="session", agent=agent)

    if active_mode:
        matches = [
            agent
            for agent in agents
            if agent.scope == "mode"
            and active_mode in {agent.mode, f"{agent.plugin}:{agent.mode}"}
        ]
        if len(matches) == 1:
            return AgentPlan(source="mode", agent=matches[0])
        if len(matches) > 1:
            # The short mode id is ambiguous; callers must use pluginId:modeId.
            return None

    for agent in agents:
        if agent.scope == "global":
            return AgentPlan(source="global", agent=agent)
    return None


__all__ = [
    "VALID_APPROVAL",
    "AgentAssembly",
    "AgentPlan",
    "PluginAgentSpec",
    "assemble_agents",
    "read_agent",
    "resolve_agent_plan",
]
