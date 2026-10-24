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

from .agent import AgentAssembly, AgentPlan, assemble_agents, resolve_agent_plan
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


def _tool_spec(tool: PluginToolSpec, dependencies: tuple[str, ...] = ()) -> ToolSpec:
    metadata: dict[str, Any] = {
        "category": "plugin",
        "handler": tool.handler,
        "plugin": tool.plugin,
        "plugin_root": tool.plugin_root,
        "visibility": tool.visibility,
        "skill": tool.skill,
    }
    # user:“依赖缺失不静默降级”+插件声明的依赖随工具元数据下发，
    # 工具箱据此换上带安装提示的占位 handler。
    if dependencies:
        metadata["dependencies"] = list(dependencies)
    if tool.timeout is not None:
        metadata["timeout"] = tool.timeout
    description = tool.description
    input_schema = dict(tool.input_schema)
    output_schema = dict(tool.output_schema)
    if not description or not input_schema:
        # user:“换芯声明”+插件工具与核心工具同名时，缺的描述与 schema 从核心
        # 工具表补全（handler 换成插件的，schema 沿用核心，字段必兼容）。
        base = _core_tool_base(tool.name)
        if base is not None:
            description = description or str(getattr(base, "description", "") or "")
            if not input_schema:
                base_input = getattr(base, "input_schema", None)
                input_schema = dict(base_input) if isinstance(base_input, dict) else {}
            if not output_schema:
                base_output = getattr(base, "output_schema", None)
                output_schema = dict(base_output) if isinstance(base_output, dict) else {}
            base_metadata = getattr(base, "metadata", None)
            if isinstance(base_metadata, dict):
                if base_metadata.get("display"):
                    metadata["display"] = dict(base_metadata["display"])
                # 半声明换芯：分类与故障说明沿用核心常量，避免作者抄一遍。
                if base_metadata.get("category"):
                    metadata["category"] = base_metadata["category"]
                if base_metadata.get("failure_modes"):
                    metadata["failure_modes"] = list(base_metadata["failure_modes"])
                if base_metadata.get("recovery"):
                    metadata["recovery"] = base_metadata["recovery"]
            metadata["overrides_core_tool"] = True
    return ToolSpec(
        name=tool.name,
        description=description,
        input_schema=input_schema,
        output_schema=output_schema,
        permission=tool.permission,
        metadata=metadata,
    )


def _core_tool_base(name: str) -> Any | None:
    try:
        from lamtools_core.tool.default_toolbox import (
            bundled_core_tool_specs,
            default_core_tool_specs,
        )
    except Exception:  # noqa: BLE001 — 核心工具表不可用时按纯声明处理
        return None
    for spec in (*default_core_tool_specs(), *bundled_core_tool_specs()):
        if getattr(spec, "name", "") == name:
            return spec
    return None


class PluginSystemRuntime:
    """Assemble one set of enabled plugins into agent-facing artifacts."""

    def __init__(self, host: PluginHost) -> None:
        self.host = host

    def assemble(self, manifests: list[Any] | None = None) -> RuntimeArtifacts:
        manifests = self.host.discover() if manifests is None else manifests
        assembly = assemble_capabilities(manifests)
        artifacts = RuntimeArtifacts(errors=[*self.host.errors, *assembly.errors])
        plugin_dependencies = self._declared_dependencies(manifests)
        artifacts.tools = [
            _tool_spec(tool, plugin_dependencies.get(tool.plugin, ()))
            for tool in assembly.tools
        ]
        artifacts.skills = list(assembly.skills)
        artifacts.skill_roots = sorted(set(assembly.skill_roots))
        artifacts.hooks = list(assembly.hooks)
        artifacts.mcp_files = list(assembly.mcp_files)
        artifacts.commands = list(assembly.commands)
        artifacts.context = list(assembly.context)
        return artifacts


    def _declared_dependencies(self, manifests: list[Any]) -> dict[str, tuple[str, ...]]:
        from .engine import read_engine

        declared: dict[str, tuple[str, ...]] = {}
        for manifest in manifests:
            try:
                engine = read_engine(manifest)
            except Exception:  # noqa: BLE001 — 坏声明不阻断装配，错误走 assembly.errors
                continue
            if engine.dependencies:
                declared[manifest.name] = engine.dependencies
        return declared

    def agents(self, manifests: list[Any] | None = None) -> AgentAssembly:
        manifests = self.host.discover() if manifests is None else manifests
        return assemble_agents(manifests)

    def agent_plan(
        self,
        *,
        active_mode: str = "",
        session_plugin: str | None = None,
    ) -> AgentPlan | None:
        return resolve_agent_plan(
            self.agents().agents,
            active_mode=active_mode,
            session_plugin=session_plugin,
        )


__all__ = ["PluginSystemRuntime", "RuntimeArtifacts"]
