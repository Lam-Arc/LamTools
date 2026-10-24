"""Host operations: hook management, skill management and legacy aliases.

user:“拆 v1 成单一系统”+钩子页与技能页的正式操作从旧 v1 操作目录搬到
新系统；``plugin.list/install/deps-status`` 以旧名转发新实现，前端搜索页
和模型工具不改调用方。websearch 配置垫片保留到右栏迁移（收尾方案步骤 5）。
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any, Callable

from lamtools_core.app import OperationCatalog, OperationRequest, OperationResult

from .engine import read_engine
from .host import PluginHost
from .hooks import HookTrustStore, load_all_hooks
from .jsonc import strip_jsonc_comments as _strip_jsonc_comments
from .jsonc import strip_trailing_commas as _strip_trailing_commas

OWNER = "plugin-system"


def _skill_source(location: Path, work_root: Path | None, manifests: list[Any]) -> str:
    """Guess the source category of a skill by its location."""
    loc = location.resolve()
    for plugin in manifests:
        if not bool(getattr(plugin, "enabled", False)):
            continue
        root = Path(getattr(plugin, "root", Path()))
        try:
            loc.relative_to(root)
        except ValueError:
            continue
        return "plugin"
    if work_root:
        wr = work_root.resolve()
        for child in (".lam", ".lamtools"):
            try:
                loc.relative_to(wr / child)
            except ValueError:
                continue
            return "project"
    from lamtools_core.config.root import lam_home

    try:
        loc.relative_to(lam_home())
    except ValueError:
        pass
    else:
        return "user"
    return "core"


from .plugin_data import plugin_config_path as _plugin_config_path
from .plugin_data import write_plugin_config as _write_plugin_config


class _LiveHookRegistry:
    """File hooks plus live-discovered plugin hooks, one object."""

    def __init__(self, host: PluginHost, work_root: Path, store: HookTrustStore) -> None:
        self._host = host
        self._work_root = work_root
        self._store = store

    def load(self) -> list[Any]:
        return load_all_hooks(
            project_root=self._work_root,
            trust_store=self._store,
            manifests=self._host.discover(),
        )


SkillRegistryFactory = Callable[[], Any]


def register_host_operations(
    catalog: OperationCatalog,
    host: PluginHost,
    *,
    work_root: Path,
    data_dir: Path,
    skill_state_store: Any,
    skill_registry_factory: SkillRegistryFactory,
    hook_trust_store: HookTrustStore,
) -> None:
    """Register the hook/skill management surface plus legacy aliases."""

    def hook_registry_factory() -> _LiveHookRegistry:
        return _LiveHookRegistry(host, work_root, hook_trust_store)

    # ── hook management ────────────────────────────────────────────────────

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
        trustable = [hook for hook in hooks if hook.status == "pending_review"]
        return OperationResult(
            name=request.name,
            payload={
                "hooks": items,
                "trustable_count": len(trustable),
                "total_count": len(items),
                "trusted_count": sum(1 for hook in hooks if hook.trusted),
            },
        )

    async def hook_trust(request: OperationRequest) -> OperationResult:
        hook_id = str(request.payload.get("hook_id") or request.payload.get("hookId") or "").strip()
        hooks = hook_registry_factory().load()
        hook = next((item for item in hooks if item.id == hook_id), None)
        if hook is None:
            return OperationResult(name=request.name, status="error", payload={"error": "hook_id not found"})
        hook_trust_store.trust(hook.definition_hash)
        return OperationResult(name=request.name, payload={"hook_id": hook_id, "trusted": True})

    # NOTE: there is deliberately no ``hook.trust_all`` operation.  Trusting a
    # hook grants it arbitrary command execution on every matching event, so
    # trust must stay a deliberate per-hook decision.

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
            raw = json.loads(config_path.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, OSError) as exc:
            return OperationResult(name=request.name, status="error", payload={"error": str(exc)})
        hooks_section = raw.get("hooks", {}) if isinstance(raw, dict) else {}
        if not isinstance(hooks_section, dict):
            return OperationResult(name=request.name, status="error", payload={"error": "hooks section is not an object"})
        # The hook id encodes: source:source_name:event:group_index:handler_index:hash
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
            config_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            return OperationResult(name=request.name, status="error", payload={"error": str(exc)})
        return OperationResult(name=request.name, payload={"hook_id": hook_id, "deleted": True})

    async def hook_config_get(request: OperationRequest) -> OperationResult:
        from lamtools_core.config.root import core_config_file

        config_path = core_config_file("hooks.json")
        if config_path.exists():
            try:
                content = config_path.read_text(encoding="utf-8")
            except OSError as exc:
                return OperationResult(name=request.name, status="error", payload={"error": str(exc)})
        else:
            content = "{}"
        # 随包 hooks.json 带注释：除了原文（原始编辑器要用）再给出归一化形态，
        # 让 UI 不必自己实现一遍 JSONC 解析。
        payload: dict[str, Any] = {"content": content, "path": str(config_path)}
        try:
            data = json.loads(_strip_jsonc_comments(content)) if content.strip() else {}
            if isinstance(data, dict):
                payload["parsed"] = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        except json.JSONDecodeError as exc:
            payload["parse_error"] = str(exc)
        return OperationResult(name=request.name, payload=payload)

    async def hook_config_update(request: OperationRequest) -> OperationResult:
        from lamtools_core.config.root import atomic_write_text, core_config_file

        content = str(request.payload.get("content") or "")
        config_path = core_config_file("hooks.json")
        try:
            # 接受 JSONC（注释、尾逗号），保存时归一到严格 JSON：其余读取方
            # 不必各自容错，文件也不会在两次保存之间反复变形态。
            data = json.loads(_strip_trailing_commas(_strip_jsonc_comments(content))) if content.strip() else {}
            if not isinstance(data, dict):
                raise ValueError("hooks config must be a JSON object")
            atomic_write_text(config_path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        except json.JSONDecodeError as exc:
            return OperationResult(name=request.name, status="error", payload={"error": f"Invalid JSON: {exc}"})
        except (OSError, ValueError) as exc:
            return OperationResult(name=request.name, status="error", payload={"error": str(exc)})
        return OperationResult(name=request.name, payload={"path": str(config_path), "saved": True})

    # ── skill management ───────────────────────────────────────────────────

    def _resolve_skill(name: str) -> Any:
        if skill_registry_factory is None:
            return None
        target = name.strip().lstrip("/").lower()
        return next(
            (
                skill
                for skill in skill_registry_factory().available(work_root)
                if skill.name.strip().lstrip("/").lower() == target
            ),
            None,
        )

    def _deletable_skill_dir(skill: Any) -> Path | None:
        location = Path(skill.location).resolve()
        source = _skill_source(location, work_root, host.discover())
        if source not in {"project", "user"} or location.name != "SKILL.md":
            return None
        skill_dir = location.parent
        allowed_roots: list[Path] = []
        if source == "project":
            root = work_root.resolve()
            allowed_roots.extend([(root / ".lam").resolve(), (root / ".lamtools").resolve()])
        elif source == "user":
            from lamtools_core.config.root import lam_home

            allowed_roots.append(lam_home().resolve())
        for allowed in allowed_roots:
            try:
                skill_dir.relative_to(allowed)
            except ValueError:
                continue
            if skill_dir != allowed:
                return skill_dir
        return None

    async def skill_list(request: OperationRequest) -> OperationResult:
        skills: list[dict[str, object]] = []
        if skill_registry_factory is not None:
            for skill in skill_registry_factory().available(work_root):
                enabled = skill_state_store.is_enabled(skill.name) if skill_state_store else True
                source = _skill_source(skill.location, work_root, host.discover())
                skills.append(
                    {
                        "name": skill.name,
                        "description": skill.description,
                        "location": str(skill.location),
                        "source": source,
                        "enabled": enabled,
                        "deletable": _deletable_skill_dir(skill) is not None,
                    }
                )
        return OperationResult(
            name=request.name,
            payload={
                "skills": skills,
                "total_count": len(skills),
                "enabled_count": sum(1 for item in skills if item.get("enabled")),
            },
        )

    async def skill_create(request: OperationRequest) -> OperationResult:
        """新建技能：标题（name）/ 描述（description）/ 内容（content）三块，
        写入用户级技能目录 ``{lam_home}/skills/<name>/SKILL.md``。
        """
        payload = request.payload if isinstance(request.payload, dict) else {}
        name = str(payload.get("name") or "").strip()
        description = str(payload.get("description") or "").strip()
        content = str(payload.get("content") or "").strip()
        if not name:
            return OperationResult(name=request.name, status="error", payload={"error": "标题（name）是必填的"})
        if not description:
            return OperationResult(name=request.name, status="error", payload={"error": "描述（description）是必填的"})
        if not content:
            return OperationResult(name=request.name, status="error", payload={"error": "内容（content）是必填的"})
        if not re.match(r"^[A-Za-z0-9._-]+$", name) or name.startswith("."):
            return OperationResult(
                name=request.name,
                status="error",
                payload={"error": "技能名只允许字母/数字/._-（将作为目录名，且不能以 . 开头）"},
            )
        from lamtools_core.config.root import lam_home

        skill_dir = lam_home() / "skills" / name
        if skill_dir.exists():
            return OperationResult(
                name=request.name,
                status="error",
                payload={"error": f"技能 '{name}' 已存在（{skill_dir}）"},
            )
        try:
            skill_dir.mkdir(parents=True, exist_ok=False)
            (skill_dir / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: {description}\n---\n\n{content}\n",
                encoding="utf-8",
            )
        except OSError as exc:
            return OperationResult(name=request.name, status="error", payload={"error": f"创建失败: {exc}"})
        return OperationResult(
            name=request.name,
            payload={"name": name, "location": str(skill_dir / "SKILL.md"), "created": True},
        )

    async def skill_enable(request: OperationRequest) -> OperationResult:
        name = str(request.payload.get("name") or "").strip()
        if not name:
            return OperationResult(name=request.name, status="error", payload={"error": "name is required"})
        skill = _resolve_skill(name)
        if skill is None:
            return OperationResult(name=request.name, status="error", payload={"error": f"Skill '{name}' was not found"})
        if skill_state_store is None:
            return OperationResult(name=request.name, status="error", payload={"error": "skill state store not available"})
        skill_state_store.set_enabled(skill.name, True)
        return OperationResult(name=request.name, payload={"name": skill.name, "enabled": True})

    async def skill_disable(request: OperationRequest) -> OperationResult:
        name = str(request.payload.get("name") or "").strip()
        if not name:
            return OperationResult(name=request.name, status="error", payload={"error": "name is required"})
        skill = _resolve_skill(name)
        if skill is None:
            return OperationResult(name=request.name, status="error", payload={"error": f"Skill '{name}' was not found"})
        if skill_state_store is None:
            return OperationResult(name=request.name, status="error", payload={"error": "skill state store not available"})
        skill_state_store.set_enabled(skill.name, False)
        return OperationResult(name=request.name, payload={"name": skill.name, "enabled": False})

    async def skill_delete(request: OperationRequest) -> OperationResult:
        name = str(request.payload.get("name") or "").strip()
        if not name:
            return OperationResult(name=request.name, status="error", payload={"error": "name is required"})
        skill = _resolve_skill(name)
        if skill is None:
            return OperationResult(
                name=request.name,
                status="error",
                payload={"error": f"Skill '{name}' was not found"},
            )
        skill_dir = _deletable_skill_dir(skill)
        if skill_dir is None:
            return OperationResult(
                name=request.name,
                status="error",
                payload={"error": f"Skill '{skill.name}' is read-only and cannot be deleted"},
            )
        try:
            shutil.rmtree(skill_dir)
        except OSError as exc:
            return OperationResult(name=request.name, status="error", payload={"error": f"Delete failed: {exc}"})
        if skill_state_store is not None:
            skill_state_store.remove(skill.name)
        return OperationResult(
            name=request.name,
            payload={"name": skill.name, "location": str(skill.location), "deleted": True},
        )

    # ── websearch config shim（保留到收尾方案步骤 5 右栏迁移）────────────

    async def websearch_config_get(request: OperationRequest) -> OperationResult:
        from lamtools_core.config.root import core_config_file

        path = _plugin_config_path(data_dir, "websearch")
        if path.exists():
            try:
                return OperationResult(
                    name=request.name,
                    payload={"content": path.read_text(encoding="utf-8"), "path": str(path)},
                )
            except OSError as exc:
                return OperationResult(name=request.name, status="error", payload={"error": str(exc)})
        # 旧位置（.lam/core/config/websearch.jsonc）→ 迁移写新，返回原文
        legacy = core_config_file("websearch.jsonc")
        if legacy.exists():
            try:
                content = legacy.read_text(encoding="utf-8")
                raw = json.loads(_strip_jsonc_comments(content)) if content.strip() else {}
                if isinstance(raw, dict):
                    _write_plugin_config(data_dir, "websearch", raw)
                return OperationResult(name=request.name, payload={"content": content, "path": str(legacy)})
            except (json.JSONDecodeError, OSError) as exc:
                return OperationResult(name=request.name, status="error", payload={"error": str(exc)})
        return OperationResult(name=request.name, payload={"content": "", "path": str(path)})

    async def websearch_config_update(request: OperationRequest) -> OperationResult:
        content = str(request.payload.get("content") or "")
        try:
            # validate – allow JSONC (comments), factory strips them on read
            raw = json.loads(_strip_jsonc_comments(content)) if content.strip() else {}
        except json.JSONDecodeError as exc:
            return OperationResult(name=request.name, status="error", payload={"error": f"Invalid JSON/JSONC: {exc}"})
        try:
            _write_plugin_config(data_dir, "websearch", raw if isinstance(raw, dict) else {})
        except OSError as exc:
            return OperationResult(name=request.name, status="error", payload={"error": str(exc)})
        return OperationResult(
            name=request.name,
            payload={"path": str(_plugin_config_path(data_dir, "websearch")), "saved": True},
        )

    # ── legacy aliases（旧名转发新实现，调用方不必改）─────────────────────

    async def plugin_list_alias(request: OperationRequest) -> OperationResult:
        del request
        manifests = host.discover()
        return OperationResult(
            name="plugin.list",
            payload={
                "plugins": [
                    {
                        "name": manifest.name,
                        "id": manifest.name,
                        "version": manifest.version,
                        "description": manifest.description,
                        "enabled": manifest.enabled,
                        "available": manifest.enabled,
                    }
                    for manifest in manifests
                ],
                "errors": list(host.errors),
            },
        )

    async def plugin_install_alias(request: OperationRequest) -> OperationResult:
        from .installer import run_install

        payload = request.payload if isinstance(request.payload, dict) else {}
        ok, result = run_install(host, payload)
        if not ok:
            return OperationResult(name=request.name, status="error", payload=result)
        return OperationResult(name=request.name, payload=result)

    async def plugin_uninstall_alias(request: OperationRequest) -> OperationResult:
        payload = request.payload if isinstance(request.payload, dict) else {}
        name = str(payload.get("name") or "").strip()
        keep_data = bool(payload.get("keep_data", True))
        if not name:
            return OperationResult(name=request.name, status="error", payload={"error": "name is required"})
        try:
            host.uninstall(name, keep_data=keep_data)
        except (KeyError, ValueError, OSError) as exc:
            return OperationResult(name=request.name, status="error", payload={"error": str(exc)})
        return OperationResult(name=request.name, payload={"name": name, "uninstalled": True})

    async def plugin_deps_status_alias(request: OperationRequest) -> OperationResult:
        import importlib.util

        payload = request.payload if isinstance(request.payload, dict) else {}
        name = str(payload.get("name") or "").strip()
        manifest = host.get(name)
        if manifest is None:
            return OperationResult(
                name=request.name,
                status="error",
                payload={"error": f"plugin '{name}' is not installed"},
            )
        dependencies = read_engine(manifest).dependencies
        items: list[dict[str, Any]] = []
        for dependency in dependencies:
            found = importlib.util.find_spec(dependency) is not None
            items.append({"name": dependency, "status": "ok" if found else "missing"})
        return OperationResult(
            name=request.name,
            payload={"name": name, "dependencies": items, "missing": sum(1 for item in items if item["status"] == "missing")},
        )

    catalog.register("hook.list", hook_list, owner=OWNER)
    catalog.register("hook.trust", hook_trust, owner=OWNER)
    catalog.register("hook.untrust", hook_untrust, owner=OWNER)
    catalog.register("hook.delete", hook_delete, owner=OWNER)
    catalog.register("hook.config.get", hook_config_get, owner=OWNER)
    catalog.register("hook.config.update", hook_config_update, owner=OWNER)
    catalog.register("skill.list", skill_list, owner=OWNER)
    catalog.register("skill.create", skill_create, owner=OWNER)
    catalog.register("skill.enable", skill_enable, owner=OWNER)
    catalog.register("skill.disable", skill_disable, owner=OWNER)
    catalog.register("skill.delete", skill_delete, owner=OWNER)
    catalog.register("websearch.config.get", websearch_config_get, owner=OWNER)
    catalog.register("websearch.config.update", websearch_config_update, owner=OWNER)
    catalog.register("plugin.list", plugin_list_alias, owner=OWNER)
    catalog.register("plugin.install", plugin_install_alias, owner=OWNER)
    catalog.register("plugin.uninstall", plugin_uninstall_alias, owner=OWNER)
    catalog.register("plugin.deps-status", plugin_deps_status_alias, owner=OWNER)


__all__ = ["register_host_operations"]
