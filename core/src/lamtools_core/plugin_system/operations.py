"""RPC operations for the redesigned plugin system.

user:“插件页能看到它”+先只暴露列表、启停和卸载，安装与能力装配在后续步骤接。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import quote

from lamtools_core.app import OperationCatalog, OperationRequest, OperationResult

from .agent import assemble_agents, resolve_agent_plan
from .capabilities import assemble_capabilities
from .host import PluginHost
from .ui import assemble_ui

OWNER = "plugin-system"


def _capability_summary(capabilities: Any) -> dict[str, list[str]]:
    if capabilities is None:
        return {
            "tools": [],
            "skills": [],
            "hooks": [],
            "mcp": [],
            "commands": [],
            "context": [],
        }
    return {
        "tools": [tool.name for tool in capabilities.tools],
        "skills": [skill.name for skill in capabilities.skills],
        "hooks": [f"{hook.event}:{hook.matcher}" for hook in capabilities.hooks],
        "mcp": [path.name for path in capabilities.mcp_files],
        "commands": [command.name for command in capabilities.commands],
        "context": [entry.file.name for entry in capabilities.context],
    }


def _plugin_payload(plugin: Any, assembly: Any = None) -> dict[str, Any]:
    payload = {
        "name": plugin.name,
        "version": plugin.version,
        "description": plugin.description,
        "enabled": plugin.enabled,
        "scope": plugin.scope,
        "root": str(plugin.root),
        "capabilities": _capability_summary(None),
    }
    if assembly is not None:
        capabilities = assembly.plugins.get(plugin.name)
        payload["capabilities"] = _capability_summary(capabilities)
        if capabilities is None:
            error = next(
                (
                    item["error"]
                    for item in assembly.errors
                    if item.get("plugin") == plugin.name
                ),
                "",
            )
            payload["capability_error"] = error
    return payload


def _asset_url(plugin: str, root: Path | None, path: Path | None) -> str:
    if root is None or path is None:
        return ""
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError:
        return ""
    return (
        f"/api/core/plugin-system/{quote(plugin, safe='')}"
        f"/assets/{quote(relative, safe='/')}"
    )


def _block_payload(block: Any) -> dict[str, Any]:
    payload = {
        "type": block.type,
        "label": block.label,
        "value": block.value,
        "text": block.text,
        "state": block.state,
        "items": list(block.items),
        "detail": block.detail,
    }
    if block.max is not None:
        payload["max"] = block.max
    return payload


def _action_payload(action: Any) -> dict[str, Any]:
    return {
        "id": action.id,
        "title": action.title,
        "operation": action.operation,
        "input_schema": action.input_schema,
        "dangerous": action.dangerous,
        "mutates": action.mutates,
    }


def _region_payload(region: Any, roots: dict[str, Path]) -> dict[str, Any]:
    return {
        "plugin": region.plugin,
        "region": region.region,
        "order": region.order,
        "mode": region.mode,
        "replace": region.replace,
        "blocks": [_block_payload(block) for block in region.blocks],
        "actions": [_action_payload(action) for action in region.actions],
        "entry_url": _asset_url(region.plugin, roots.get(region.plugin), region.entry),
    }


def _agent_payload(agent: Any) -> dict[str, Any]:
    return {
        "plugin": agent.plugin,
        "scope": agent.scope,
        "mode": agent.mode,
        "prompt": agent.prompt_text,
        "tools": list(agent.tools) if agent.tools is not None else None,
        "approval": agent.approval,
        "context": [str(path) for path in agent.context],
        "exclusive_tools": agent.exclusive_tools,
    }


def register_plugin_system_operations(catalog: OperationCatalog, host: PluginHost) -> None:
    """Register the preview surface used by the plugin page."""

    async def list_plugins(request: OperationRequest) -> OperationResult:
        del request
        plugins = host.discover()
        assembly = assemble_capabilities(plugins)
        return OperationResult(
            name="plugin.system.list",
            payload={
                "plugins": [_plugin_payload(plugin, assembly) for plugin in plugins],
                "errors": list(host.errors),
                "capability_errors": list(assembly.errors),
            },
        )

    async def list_ui(request: OperationRequest) -> OperationResult:
        del request
        manifests = host.discover()
        assembly = assemble_ui(manifests)
        roots = {manifest.name: manifest.root for manifest in manifests}
        return OperationResult(
            name="plugin.system.ui",
            payload={
                "styles": [
                    {"plugin": asset.plugin, "url": _asset_url(asset.plugin, asset.root, asset.path)}
                    for asset in assembly.styles
                ],
                "scripts": [
                    {"plugin": asset.plugin, "url": _asset_url(asset.plugin, asset.root, asset.path)}
                    for asset in assembly.scripts
                ],
                "regions": [_region_payload(region, roots) for region in assembly.regions],
                "windows": [
                    {
                        "plugin": window.plugin,
                        "id": window.id,
                        "title": window.title,
                        "url": _asset_url(window.plugin, window.root, window.entry),
                        "width": window.width,
                        "height": window.height,
                    }
                    for window in assembly.windows
                ],
                "errors": list(assembly.errors),
            },
        )

    async def get_agent(request: OperationRequest) -> OperationResult:
        payload = request.payload if isinstance(request.payload, dict) else {}
        assembly = assemble_agents(host.discover())
        plan = resolve_agent_plan(
            assembly.agents,
            active_mode=str(payload.get("active_mode") or ""),
            session_plugin=str(payload.get("session_plugin") or "") or None,
        )
        return OperationResult(
            name="plugin.system.agent",
            payload={
                "agents": [_agent_payload(agent) for agent in assembly.agents],
                "plan": (
                    {"source": plan.source, **_agent_payload(plan.agent)}
                    if plan is not None
                    else None
                ),
                "errors": list(assembly.errors),
            },
        )

    async def install_plugin(request: OperationRequest) -> OperationResult:
        payload = request.payload if isinstance(request.payload, dict) else {}
        source = str(payload.get("source") or "local").strip().lower()
        path = str(payload.get("path") or "").strip()
        if not path:
            return OperationResult(
                name=request.name, status="error", payload={"error": "path is required"}
            )
        try:
            if source == "local":
                installed = host.install_from_directory(path)
            elif source == "zip":
                installed = host.install_from_zip(path)
            else:
                return OperationResult(
                    name=request.name,
                    status="error",
                    payload={"error": "source must be local or zip"},
                )
        except (OSError, ValueError) as exc:
            return OperationResult(
                name=request.name, status="error", payload={"error": str(exc)}
            )
        return OperationResult(
            name=request.name,
            payload={
                "installed": True,
                "name": installed.name,
                "root": str(installed),
            },
        )

    async def update_plugin(request: OperationRequest) -> OperationResult:
        payload = request.payload if isinstance(request.payload, dict) else {}
        source = str(payload.get("source") or "local").strip().lower()
        path = str(payload.get("path") or "").strip()
        if source != "local":
            return OperationResult(
                name=request.name,
                status="error",
                payload={"error": "update currently supports local directories"},
            )
        if not path:
            return OperationResult(
                name=request.name, status="error", payload={"error": "path is required"}
            )
        try:
            updated = host.update_from_directory(path)
        except (OSError, ValueError) as exc:
            return OperationResult(
                name=request.name, status="error", payload={"error": str(exc)}
            )
        return OperationResult(
            name=request.name,
            payload={"updated": True, "name": updated.name, "root": str(updated)},
        )

    async def set_enabled(request: OperationRequest, enabled: bool) -> OperationResult:
        name = str(request.payload.get("name") or "").strip()
        if not name:
            return OperationResult(
                name=request.name, status="error", payload={"error": "name is required"}
            )
        changed = host.enable(name) if enabled else host.disable(name)
        if not changed:
            return OperationResult(
                name=request.name,
                status="error",
                payload={"error": f"plugin '{name}' is not installed"},
            )
        return OperationResult(
            name=request.name, payload={"name": name, "enabled": enabled}
        )

    async def enable_plugin(request: OperationRequest) -> OperationResult:
        return await set_enabled(request, True)

    async def disable_plugin(request: OperationRequest) -> OperationResult:
        return await set_enabled(request, False)

    async def uninstall_plugin(request: OperationRequest) -> OperationResult:
        name = str(request.payload.get("name") or "").strip()
        if not name:
            return OperationResult(
                name=request.name, status="error", payload={"error": "name is required"}
            )
        keep_data = bool(request.payload.get("keep_data", True))
        try:
            host.uninstall(name, keep_data=keep_data)
        except KeyError as exc:
            return OperationResult(
                name=request.name, status="error", payload={"error": str(exc)}
            )
        return OperationResult(
            name=request.name, payload={"name": name, "uninstalled": True}
        )

    catalog.register("plugin.system.list", list_plugins, owner=OWNER)
    catalog.register("plugin.system.ui", list_ui, owner=OWNER)
    catalog.register("plugin.system.agent", get_agent, owner=OWNER)
    catalog.register("plugin.system.install", install_plugin, owner=OWNER)
    catalog.register("plugin.system.update", update_plugin, owner=OWNER)
    catalog.register("plugin.system.enable", enable_plugin, owner=OWNER)
    catalog.register("plugin.system.disable", disable_plugin, owner=OWNER)
    catalog.register("plugin.system.uninstall", uninstall_plugin, owner=OWNER)


__all__ = ["OWNER", "register_plugin_system_operations"]
