"""RPC operations for the redesigned plugin system.

user:“插件页能看到它”+先只暴露列表、启停和卸载，安装与能力装配在后续步骤接。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import quote

from lamtools_core.app import OperationCatalog, OperationRequest, OperationResult

from .agent import assemble_agents, resolve_agent_plan
from .capabilities import CapabilityError, assemble_capabilities
from .config_store import (
    read_config_values,
    read_schema,
    validate_config,
    write_config_values,
)
from .host import PluginHost
from .settings import read_config
from .ui import assemble_ui

OWNER = "plugin-system"


async def apply_plugin_enablement(
    host: PluginHost, name: str, enabled: bool
) -> tuple[bool, str]:
    """Flip the ledger, then start or stop the plugin backend."""
    changed = host.enable(name) if enabled else host.disable(name)
    if not changed:
        return False, ""
    manager = getattr(host, "backend_manager", None)
    if manager is None:
        return True, ""
    try:
        if enabled:
            await manager.start(name)
        else:
            await manager.stop(name)
    except Exception as exc:  # noqa: BLE001 - the ledger already changed
        return True, f"{type(exc).__name__}: {exc}"
    return True, ""



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
                # user:“注册到模式切换，类似 study 和 workflow”+模式描述和旧
                # 插件同形，前端沿用同一张加载表，后端只负责声明。
                "modes": [
                    {
                        "pluginId": mode.plugin,
                        "plugin": mode.plugin,
                        "id": mode.id,
                        "title": mode.title,
                        "entry": str(mode.entry or ""),
                        "entry_url": _asset_url(
                            mode.plugin, roots.get(mode.plugin), mode.entry
                        ),
                        "icon": mode.icon,
                        "order": mode.order,
                        "tools": list(mode.tools),
                        "enabled": True,
                        **(
                            {"capabilities": list(mode.capabilities)}
                            if mode.capabilities is not None
                            else {}
                        ),
                    }
                    for mode in assembly.modes
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

    async def config_get(request: OperationRequest) -> OperationResult:
        payload = request.payload if isinstance(request.payload, dict) else {}
        name = str(payload.get("name") or "").strip()
        if not name:
            return OperationResult(
                name=request.name, status="error", payload={"error": "name is required"}
            )
        manifest = host.get(name)
        if manifest is None:
            return OperationResult(
                name=request.name,
                status="error",
                payload={"error": f"plugin '{name}' is not installed"},
            )
        try:
            spec = read_config(manifest)
        except CapabilityError as exc:
            return OperationResult(
                name=request.name, status="error", payload={"error": exc.message}
            )
        return OperationResult(
            name=request.name,
            payload={
                "name": name,
                "version": manifest.version,
                "description": manifest.description,
                "config": read_config_values(manifest),
                "schema": read_schema(manifest, spec),
                "has_schema": spec.schema is not None,
                # user:“每一个插件都应该有配置面板”+自定义面板按插件自己的脚本
                # 挂载，没有脚本时前端用默认表单；两种情况身份信息都由宿主补。
                "panel_url": _asset_url(name, manifest.root, spec.panel),
                "has_panel": spec.panel is not None,
            },
        )

    async def config_update(request: OperationRequest) -> OperationResult:
        payload = request.payload if isinstance(request.payload, dict) else {}
        name = str(payload.get("name") or "").strip()
        if not name:
            return OperationResult(
                name=request.name, status="error", payload={"error": "name is required"}
            )
        manifest = host.get(name)
        if manifest is None:
            return OperationResult(
                name=request.name,
                status="error",
                payload={"error": f"plugin '{name}' is not installed"},
            )
        values = payload.get("config")
        if not isinstance(values, dict):
            return OperationResult(
                name=request.name,
                status="error",
                payload={"error": "config must be an object"},
            )
        try:
            spec = read_config(manifest)
        except CapabilityError as exc:
            return OperationResult(
                name=request.name, status="error", payload={"error": exc.message}
            )
        problems = validate_config(read_schema(manifest, spec), values)
        if problems:
            return OperationResult(
                name=request.name,
                status="error",
                payload={"error": "; ".join(problems)},
            )
        path = write_config_values(manifest, values)
        return OperationResult(
            name=request.name,
            payload={"name": name, "saved": True, "path": str(path)},
        )

    async def set_enabled(request: OperationRequest, enabled: bool) -> OperationResult:
        name = str(request.payload.get("name") or "").strip()
        if not name:
            return OperationResult(
                name=request.name, status="error", payload={"error": "name is required"}
            )
        # user:“插件可以有自己的后端”+开关插件时同步启停后端，工具面和
        # 后台任务一起回来或一起消失。
        changed, backend_error = await apply_plugin_enablement(host, name, enabled)
        if not changed:
            return OperationResult(
                name=request.name,
                status="error",
                payload={"error": f"plugin {chr(39)}{name}{chr(39)} is not installed"},
            )
        payload_out: dict[str, Any] = {"name": name, "enabled": enabled}
        if backend_error:
            payload_out["backend_error"] = backend_error
        return OperationResult(name=request.name, payload=payload_out)

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
        except (KeyError, ValueError) as exc:
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
    catalog.register("plugin.system.config.get", config_get, owner=OWNER)
    catalog.register("plugin.system.config.update", config_update, owner=OWNER)
    catalog.register("plugin.system.enable", enable_plugin, owner=OWNER)
    catalog.register("plugin.system.disable", disable_plugin, owner=OWNER)
    catalog.register("plugin.system.uninstall", uninstall_plugin, owner=OWNER)
    # user:“插件自己也提供操作”+v2 插件在 operations.jsonc 里声明的 RPC 面
    # 在启动时挂进来，禁用插件后这些操作自动不可用。
    from .operation_bridge import register_plugin_operations

    register_plugin_operations(catalog, host)


__all__ = ["OWNER", "register_plugin_system_operations"]
