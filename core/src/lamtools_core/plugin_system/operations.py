"""RPC operations for the redesigned plugin system.

user:“插件页能看到它”+先只暴露列表、启停和卸载，安装与能力装配在后续步骤接。
"""

from __future__ import annotations

from typing import Any

from lamtools_core.app import OperationCatalog, OperationRequest, OperationResult

from .capabilities import assemble_capabilities
from .host import PluginHost

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
    catalog.register("plugin.system.enable", enable_plugin, owner=OWNER)
    catalog.register("plugin.system.disable", disable_plugin, owner=OWNER)
    catalog.register("plugin.system.uninstall", uninstall_plugin, owner=OWNER)


__all__ = ["OWNER", "register_plugin_system_operations"]
