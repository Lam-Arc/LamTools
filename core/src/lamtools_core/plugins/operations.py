from __future__ import annotations

import json as _json
from collections.abc import Callable
from pathlib import Path

from lamtools_core.app import OperationCatalog, OperationRequest, OperationResult
from lamtools_core.config.root import core_config_file
from lamtools_core.skills import SkillRegistry, SkillStateStore

from .hook_config import HookRegistry
from .registry import PluginRegistry, PluginStateStore
from .trust import HookTrustStore


def _skill_source(location: Path, work_root: str | Path | None) -> str:
    """Guess the source category of a skill by its location."""
    loc = location.resolve()
    if work_root:
        wr = Path(work_root).resolve()
        try:
            loc.relative_to(wr / ".lam")
        except ValueError:
            pass
        else:
            return "project"
        try:
            loc.relative_to(wr / ".lamtools")
        except ValueError:
            pass
        else:
            return "project"
    home_lam = Path.home() / ".lam"
    try:
        loc.relative_to(home_lam)
    except ValueError:
        pass
    else:
        return "user"
    return "core"


def build_plugin_operation_catalog(
    *,
    plugin_registry: PluginRegistry,
    plugin_state_store: PluginStateStore,
    hook_registry_factory: Callable[[], HookRegistry],
    hook_trust_store: HookTrustStore,
    skill_state_store: SkillStateStore | None = None,
    skill_registry_factory: Callable[[], SkillRegistry] | None = None,
    work_root: str | Path | None = None,
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
        hooks = hook_registry_factory().load()
        items = [
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
            for hook in hooks
        ]
        trustable = [h for h in hooks if h.status == "pending_review"]
        return OperationResult(name=request.name, payload={
            "hooks": items,
            "trustable_count": len(trustable),
            "total_count": len(items),
            "trusted_count": sum(1 for h in hooks if h.trusted),
        })

    async def hook_trust(request: OperationRequest) -> OperationResult:
        hook_id = str(request.payload.get("hook_id") or request.payload.get("hookId") or "").strip()
        hooks = hook_registry_factory().load()
        hook = next((item for item in hooks if item.id == hook_id), None)
        if hook is None:
            return OperationResult(name=request.name, status="error", payload={"error": "hook_id not found"})
        hook_trust_store.trust(hook.definition_hash)
        return OperationResult(name=request.name, payload={"hook_id": hook_id, "trusted": True})

    async def hook_trust_all(request: OperationRequest) -> OperationResult:
        hooks = hook_registry_factory().load()
        pending = [h for h in hooks if h.status == "pending_review"]
        for hook in pending:
            hook_trust_store.trust(hook.definition_hash)
        return OperationResult(name=request.name, payload={
            "trusted_count": len(pending),
            "trusted_ids": [h.id for h in pending],
        })

    async def hook_untrust(request: OperationRequest) -> OperationResult:
        hook_id = str(request.payload.get("hook_id") or request.payload.get("hookId") or "").strip()
        hooks = hook_registry_factory().load()
        hook = next((item for item in hooks if item.id == hook_id), None)
        if hook is None:
            return OperationResult(name=request.name, status="error", payload={"error": "hook_id not found"})
        hook_trust_store.untrust(hook.definition_hash)
        return OperationResult(name=request.name, payload={"hook_id": hook_id, "trusted": False})

    async def hook_delete(request: OperationRequest) -> OperationResult:
        hook_id = str(request.payload.get("hook_id") or request.payload.get("hookId") or "").strip()
        if not hook_id:
            return OperationResult(name=request.name, status="error", payload={"error": "hook_id is required"})
        hooks = hook_registry_factory().load()
        target = next((item for item in hooks if item.id == hook_id), None)
        if target is None:
            return OperationResult(name=request.name, status="error", payload={"error": "hook_id not found"})
        if target.source in ("plugin", "managed"):
            return OperationResult(name=request.name, status="error", payload={"error": "cannot delete plugin-managed hook"})
        config_path = target.config_path
        if not config_path.exists():
            return OperationResult(name=request.name, status="error", payload={"error": "config file not found"})
        try:
            raw = _json.loads(config_path.read_text(encoding="utf-8-sig"))
        except (_json.JSONDecodeError, OSError) as exc:
            return OperationResult(name=request.name, status="error", payload={"error": str(exc)})
        hooks_section = raw.get("hooks", {}) if isinstance(raw, dict) else {}
        if not isinstance(hooks_section, dict):
            return OperationResult(name=request.name, status="error", payload={"error": "hooks section is not an object"})
        # The hook id encodes: source:source_name:event:group_index:handler_index:hash
        # We need event, group_index, handler_index to locate and remove it.
        parts = hook_id.split(":")
        if len(parts) < 5:
            return OperationResult(name=request.name, status="error", payload={"error": "invalid hook id format"})
        event = parts[2]
        try:
            group_index = int(parts[3])
            handler_index = int(parts[4])
        except ValueError:
            return OperationResult(name=request.name, status="error", payload={"error": "invalid hook id format"})
        groups = hooks_section.get(event, [])
        if not isinstance(groups, list) or group_index >= len(groups):
            return OperationResult(name=request.name, status="error", payload={"error": "hook group not found"})
        group = groups[group_index]
        if not isinstance(group, dict):
            return OperationResult(name=request.name, status="error", payload={"error": "hook group is not an object"})
        handlers = group.get("hooks", [])
        if not isinstance(handlers, list) or handler_index >= len(handlers):
            return OperationResult(name=request.name, status="error", payload={"error": "hook handler not found"})
        handlers.pop(handler_index)
        if not handlers:
            groups.pop(group_index)
        if not groups:
            hooks_section.pop(event, None)
        if hooks_section:
            raw["hooks"] = hooks_section
        else:
            raw.pop("hooks", None)
        try:
            config_path.write_text(_json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            return OperationResult(name=request.name, status="error", payload={"error": str(exc)})
        return OperationResult(name=request.name, payload={"hook_id": hook_id, "deleted": True})

    # ── hook config read / write ──────────────────────────────────────────

    async def hook_config_get(request: OperationRequest) -> OperationResult:
        config_path = core_config_file("hooks.json")
        if config_path.exists():
            try:
                content = config_path.read_text(encoding="utf-8")
            except OSError as exc:
                return OperationResult(name=request.name, status="error", payload={"error": str(exc)})
        else:
            content = "{}"
        return OperationResult(name=request.name, payload={"content": content, "path": str(config_path)})

    async def hook_config_update(request: OperationRequest) -> OperationResult:
        content = str(request.payload.get("content") or "")
        config_path = core_config_file("hooks.json")
        try:
            # validate – must be valid JSON
            _json.loads(content) if content.strip() else {}
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(content, encoding="utf-8")
        except _json.JSONDecodeError as exc:
            return OperationResult(name=request.name, status="error", payload={"error": f"Invalid JSON: {exc}"})
        except OSError as exc:
            return OperationResult(name=request.name, status="error", payload={"error": str(exc)})
        return OperationResult(name=request.name, payload={"path": str(config_path), "saved": True})

    # ── skill operations ──────────────────────────────────────────────────

    async def skill_list(request: OperationRequest) -> OperationResult:
        store = skill_state_store
        skills: list[dict[str, object]] = []
        if skill_registry_factory is not None:
            for skill in skill_registry_factory().available(work_root):
                enabled = store.is_enabled(skill.name) if store else True
                skills.append({
                    "name": skill.name,
                    "description": skill.description,
                    "location": str(skill.location),
                    "source": _skill_source(skill.location, work_root),
                    "enabled": enabled,
                })
        return OperationResult(name=request.name, payload={
            "skills": skills,
            "total_count": len(skills),
            "enabled_count": sum(1 for s in skills if s.get("enabled")),
        })

    async def skill_enable(request: OperationRequest) -> OperationResult:
        name = str(request.payload.get("name") or "").strip()
        if not name:
            return OperationResult(name=request.name, status="error", payload={"error": "name is required"})
        if skill_state_store is None:
            return OperationResult(name=request.name, status="error", payload={"error": "skill state store not available"})
        skill_state_store.set_enabled(name, True)
        return OperationResult(name=request.name, payload={"name": name, "enabled": True})

    async def skill_disable(request: OperationRequest) -> OperationResult:
        name = str(request.payload.get("name") or "").strip()
        if not name:
            return OperationResult(name=request.name, status="error", payload={"error": "name is required"})
        if skill_state_store is None:
            return OperationResult(name=request.name, status="error", payload={"error": "skill state store not available"})
        skill_state_store.set_enabled(name, False)
        return OperationResult(name=request.name, payload={"name": name, "enabled": False})

    catalog.register("plugin.list", plugin_list)
    catalog.register("plugin.enable", plugin_enable)
    catalog.register("plugin.disable", plugin_disable)
    catalog.register("hook.list", hook_list)
    catalog.register("hook.trust", hook_trust)
    catalog.register("hook.trust_all", hook_trust_all)
    catalog.register("hook.untrust", hook_untrust)
    catalog.register("hook.delete", hook_delete)
    catalog.register("hook.config.get", hook_config_get)
    catalog.register("hook.config.update", hook_config_update)
    catalog.register("skill.list", skill_list)
    catalog.register("skill.enable", skill_enable)
    catalog.register("skill.disable", skill_disable)
    return catalog