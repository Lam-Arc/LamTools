"""Runtime artifacts assembled from the six declarative capabilities.

The legacy agent keeps its own assembly during the rewrite. This runtime turns
one manifest set into the artifact kinds the agent consumes, behind one object,
so later steps can swap the agent over without touching the declarative layer.

user:“六样都生效”+先把六类产物一次装配出来；开关插件时六类一起消失或回来。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lamtools_core.tool import ToolSpec

from .capabilities import (
    PluginCommandSpec,
    PluginContextSpec,
    PluginHookSpec,
    PluginSkillSpec,
    PluginToolSpec,
    assemble_capabilities,
)
from .host import PluginHost


@dataclass
class RuntimeArtifacts:
    tools: list[ToolSpec] = field(default_factory=list)
    skills: list[PluginSkillSpec] = field(default_factory=list)
    skill_roots: list[Path] = field(default_factory=list)
    hooks: list[PluginHookSpec] = field(default_factory=list)
    mcp_files: list[Path] = field(default_factory=list)
    commands: list[PluginCommandSpec] = field(default_factory=list)
    context: list[PluginContextSpec] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not any(
            (
                self.tools,
                self.skills,
                self.hooks,
                self.mcp_files,
                self.commands,
                self.context,
            )
        )


def _tool_spec(tool: PluginToolSpec) -> ToolSpec:
    metadata: dict[str, Any] = {
        "category": "plugin",
        "handler": tool.handler,
        "plugin": tool.plugin,
        "plugin_root": tool.plugin_root,
        "visibility": tool.visibility,
        "skill": tool.skill,
    }
    if tool.timeout is not None:
        metadata["timeout"] = tool.timeout
    return ToolSpec(
        name=tool.name,
        description=tool.description,
        input_schema=dict(tool.input_schema),
        output_schema=dict(tool.output_schema),
        permission=tool.permission,
        metadata=metadata,
    )


class PluginSystemRuntime:
    """Assemble one set of enabled plugins into agent-facing artifacts."""

    def __init__(self, host: PluginHost) -> None:
        self.host = host

    def assemble(self) -> RuntimeArtifacts:
        manifests = self.host.discover()
        assembly = assemble_capabilities(manifests)
        artifacts = RuntimeArtifacts(errors=[*self.host.errors, *assembly.errors])
        artifacts.tools = [_tool_spec(tool) for tool in assembly.tools]
        artifacts.skills = list(assembly.skills)
        artifacts.skill_roots = sorted(
            {skill.root for skill in assembly.skills if skill.root is not None}
        )
        artifacts.hooks = list(assembly.hooks)
        artifacts.mcp_files = list(assembly.mcp_files)
        artifacts.commands = list(assembly.commands)
        artifacts.context = list(assembly.context)
        return artifacts


__all__ = ["PluginSystemRuntime", "RuntimeArtifacts"]
