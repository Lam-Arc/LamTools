from __future__ import annotations

from collections.abc import Callable

from lamtools_core.app import OperationCatalog, OperationRequest, OperationResult

from .hook_config import HookRegistry
from .registry import PluginRegistry, PluginStateStore
from .trust import HookTrustStore


def build_plugin_operation_catalog(
    *,
    plugin_registry: PluginRegistry,
    plugin_state_store: PluginStateStore,
    hook_registry_factory: Callable[[], HookRegistry],
    hook_trust_store: HookTrustStore,
) -> OperationCatalog:
    catalog = OperationCatalog()

    async def plugin_list(request: OperationRequest) -> OperationResult:
        plugins = [
            {
                "name": item.name,
                "version": item.version,
                "description": item.description,
                "root": str(item.root),
                "enabled": item.enabled,
                "skills": [str(path) for path in item.skill_roots],
                "hooks": [str(path) for path in item.hook_files],
                "mcp": [str(path) for path in item.mcp_files],
            }
            for item in plugin_registry.discover()
        ]
        return OperationResult(name=request.name, payload={"plugins": plugins})

    async def plugin_enable(request: OperationRequest) -> OperationResult:
        name = str(request.payload.get("name") or "").strip()
        if not name:
            return OperationResult(name=request.name, status="error", payload={"error": "name is required"})
        plugin_state_store.set_enabled(name, True)
        return OperationResult(name=request.name, payload={"name": name, "enabled": True})

    async def plugin_disable(request: OperationRequest) -> OperationResult:
        name = str(request.payload.get("name") or "").strip()
        if not name:
            return OperationResult(name=request.name, status="error", payload={"error": "name is required"})
        plugin_state_store.set_enabled(name, False)
        return OperationResult(name=request.name, payload={"name": name, "enabled": False})

    async def hook_list(request: OperationRequest) -> OperationResult:
        hooks = [
            {
                "id": hook.id,
                "event": hook.event,
                "matcher": hook.matcher,
                "source": hook.source,
                "source_name": hook.source_name,
                "plugin_name": hook.plugin_name,
                "config_path": str(hook.config_path),
                "handler_type": hook.handler.type,
                "command": hook.handler.command,
                "definition_hash": hook.definition_hash,
                "trusted": hook.trusted,
                "status": hook.status,
            }
            for hook in hook_registry_factory().load()
        ]
        return OperationResult(name=request.name, payload={"hooks": hooks})

    async def hook_trust(request: OperationRequest) -> OperationResult:
        hook_id = str(request.payload.get("hook_id") or request.payload.get("hookId") or "").strip()
        hooks = hook_registry_factory().load()
        hook = next((item for item in hooks if item.id == hook_id), None)
        if hook is None:
            return OperationResult(name=request.name, status="error", payload={"error": "hook_id not found"})
        hook_trust_store.trust(hook.definition_hash)
        return OperationResult(name=request.name, payload={"hook_id": hook_id, "trusted": True})

    catalog.register("plugin.list", plugin_list)
    catalog.register("plugin.enable", plugin_enable)
    catalog.register("plugin.disable", plugin_disable)
    catalog.register("hook.list", hook_list)
    catalog.register("hook.trust", hook_trust)
    return catalog
