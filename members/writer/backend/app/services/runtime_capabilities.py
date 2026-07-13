from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from lamtools_core.tool.approval import DEFAULT_COMMAND_POLICIES


CORE_RUNTIME_CONTROLS_NAMESPACE = "core.runtimeControls"
WRITER_RUNTIME_CONTROLS_NAMESPACE = "writer.runtimeControls"
LEGACY_RUNTIME_CONTROLS_NAMESPACE = "lamwriter.runtimeControls"
RUNTIME_CONTROLS_NAMESPACE = LEGACY_RUNTIME_CONTROLS_NAMESPACE
WRITER_DEFAULT_COMMAND_POLICIES = dict(DEFAULT_COMMAND_POLICIES)


def _merge_dicts(*values: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for value in values:
        merged.update(value)
    return merged


def _section(value: dict[str, Any], key: str) -> dict[str, Any]:
    section = value.get(key)
    return section if isinstance(section, dict) else {}


async def _setting_value(db: AsyncSession | None, namespace: str) -> dict[str, Any]:
    if db is None:
        return {}
    setting = await db.get(AppSetting, namespace)
    value = setting.value if setting is not None and isinstance(setting.value, dict) else {}
    return value


async def runtime_controls(
    db: AsyncSession,
    *,
    shared_db: AsyncSession | None = None,
) -> dict[str, dict[str, Any]]:
    shared_legacy = await _setting_value(shared_db, LEGACY_RUNTIME_CONTROLS_NAMESPACE)
    shared_core = await _setting_value(shared_db, CORE_RUNTIME_CONTROLS_NAMESPACE)
    writer_legacy = await _setting_value(db, LEGACY_RUNTIME_CONTROLS_NAMESPACE)
    writer_overlay = await _setting_value(db, WRITER_RUNTIME_CONTROLS_NAMESPACE)

    agents = _merge_dicts(
        _section(shared_legacy, "agents"),
        _section(shared_core, "agents"),
        _section(writer_legacy, "agents"),
        _section(writer_overlay, "agents"),
    )
    tools = _merge_dicts(
        _section(shared_legacy, "tools"),
        _section(shared_core, "tools"),
        _section(writer_legacy, "tools"),
        _section(writer_overlay, "tools"),
    )
    command_policies = _merge_dicts(
        dict(WRITER_DEFAULT_COMMAND_POLICIES),
        _section(shared_legacy, "command_policies"),
        _section(shared_core, "command_policies"),
        _section(writer_legacy, "command_policies"),
        _section(writer_overlay, "command_policies"),
    )
    return {"agents": agents, "tools": tools, "command_policies": command_policies}


async def runtime_capabilities_response(
    db: AsyncSession,
    *,
    work_root: str | None = None,
    shared_db: AsyncSession | None = None,
) -> dict[str, Any]:
    from app.config import settings
    from app.core.prompt_assembler import WRITER_TOOLS
    from app.core.writer.agent_runtime import default_agent_registry, load_sub_agent_definitions
    from app.core.writer.permission import TOOL_PERMISSIONS

    controls = await runtime_controls(db, shared_db=shared_db)
    agent_controls = controls["agents"]
    tool_controls = controls["tools"]
    command_policy_controls = controls["command_policies"]
    command_policies = {
        group: str(command_policy_controls.get(group) or policy)
        for group, policy in WRITER_DEFAULT_COMMAND_POLICIES.items()
    }

    registry = default_agent_registry()
    agents = []
    for name in registry.names():
        spec = registry.resolve(name)
        if spec is None:
            continue
        agents.append({
            "name": spec.name,
            "description": spec.description,
            "aliases": list(spec.aliases),
            "modes": list(spec.modes),
            "capabilities": list(spec.capabilities),
            "can_parallel": spec.can_parallel,
            "can_call_agents": spec.can_call_agents,
            "max_depth": spec.max_depth,
            "enabled": bool(agent_controls.get(spec.name, True)),
        })

    effective_work_root = work_root or settings.writer_work_root
    subagents = [
        {
            "name": definition.name,
            "description": definition.description,
            "role": definition.role,
            "developer_instructions": definition.developer_instructions,
            "tools": list(definition.tools),
            "model": definition.model,
            "aliases": list(definition.aliases),
            "source": definition.source,
            "enabled": bool(agent_controls.get(f"sub:{definition.name}", True)),
        }
        for definition in load_sub_agent_definitions(effective_work_root)
    ]

    tools = []
    for item in WRITER_TOOLS:
        function = item.get("function") or {}
        tool_name = str(function.get("name") or "")
        if not tool_name:
            continue
        tools.append({
            "name": tool_name,
            "description": str(function.get("description") or ""),
            "permission": TOOL_PERMISSIONS.get(tool_name, "unknown"),
            "permission_group": "regular" if tool_name != "run_command" else "command",
            "approval_policy": command_policies["regular"] if tool_name == "run_command" else "auto_allow",
            "enabled": bool(tool_controls.get(tool_name, True)),
        })

    return {
        "agents": agents,
        "subagents": subagents,
        "tools": tools,
        "command_policies": command_policies,
    }


__all__ = [
    "CORE_RUNTIME_CONTROLS_NAMESPACE",
    "LEGACY_RUNTIME_CONTROLS_NAMESPACE",
    "RUNTIME_CONTROLS_NAMESPACE",
    "WRITER_RUNTIME_CONTROLS_NAMESPACE",
    "runtime_capabilities_response",
    "runtime_controls",
]
