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
    from app.core.prompt_assembler import WRITER_TOOLS
    from app.core.writer.permission import TOOL_PERMISSIONS

    controls = await runtime_controls(db, shared_db=shared_db)
    tool_controls = controls["tools"]
    command_policy_controls = controls["command_policies"]
    command_policies = {
        group: str(command_policy_controls.get(group) or policy)
        for group, policy in WRITER_DEFAULT_COMMAND_POLICIES.items()
    }

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
        "agents": [],
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
