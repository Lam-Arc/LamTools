from __future__ import annotations

import json as _json
import logging
import os
import re
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from lamtools_core.app import OperationCatalog, OperationRequest, OperationResult
from lamtools_core.config.root import core_config_file
from lamtools_core.skills import SkillRegistry, SkillStateStore

from ._jsonc import strip_jsonc_comments as _strip_jsonc_comments
from .deps import check_dependencies
from .hook_config import HookRegistry
from .registry import PluginRegistry, PluginStateStore
from .trust import HookTrustStore

_logger = logging.getLogger(__name__)


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _detect_dir(base: Path, dir_name: str, case_insensitive: bool) -> Path | None:
    """在 ``base`` 下检测 ``dir_name`` 目录是否存在，返回解析后的绝对路径。

    - 绝对路径：直接解析并检查（大小写不敏感时仍逐级比较）。
    - 相对路径：逐级在 ``base`` 下查找；``case_insensitive=True`` 时每级
      先用原名探测，失败再扫描条目做忽略大小写匹配（Linux/macOS 大小写
      敏感盘上有意义；Windows 上原名探测天然不区分大小写）。
    - 最终统一 ``resolve()`` 规范化——Windows 上顺带把 8.3 短路径/大小写
      差异还原为磁盘上的真实长路径（参考 ``Path.resolve()`` 语义）。
    """
    candidate = Path(dir_name).expanduser()
    if candidate.is_absolute():
        try:
            resolved = candidate.resolve()
        except OSError:
            return None
        return resolved if resolved.is_dir() else None
    parts = [part for part in re.split(r"[\\/]", dir_name) if part]
    if not parts:
        return None
    current = base
    for part in parts:
        direct = current / part
        if direct.exists():
            current = direct
            continue
        if not case_insensitive:
            return None
        # 忽略大小写：扫描当前目录找名字折叠相等的条目
        match: Path | None = None
        try:
            with os.scandir(current) as it:
                for entry in it:
                    if entry.name.casefold() == part.casefold():
                        match = Path(entry.path)
                        break
        except OSError:
            return None
        if match is None:
            return None
        current = match
    try:
        resolved = current.resolve()
    except OSError:
        return None
    return resolved if resolved.is_dir() else None


# 插件配置中的密钥字段名（回显打码 / 掩码提交保留原值，镜像 provider 契约）
_SECRET_KEY_RE = re.compile(r"(?i)(api[_-]?key|token|secret|password)")


def _mask_secret_fields(config: dict[str, Any]) -> dict[str, Any]:
    """把密钥字段打码为 ``********``；返回 (config, has_secrets)。"""
    masked = dict(config)
    has_secrets = False
    for key in list(masked.keys()):
        if _SECRET_KEY_RE.search(str(key)) and isinstance(masked[key], str) and masked[key]:
            masked[key] = "********"
            has_secrets = True
    return {"config": masked, "has_secrets": has_secrets}


def _SECRET_KEY_PATTERN_MATCHES(config: dict[str, Any]) -> list[str]:
    return [key for key in config.keys() if _SECRET_KEY_RE.search(str(key))]


def _skill_names_from_roots(roots: list[Path]) -> list[str]:
    """扫描技能目录下的 SKILL.md，返回技能名列表（frontmatter name）。"""
    names: list[str] = []
    for root in roots:
        if not root.exists() or not root.is_dir():
            continue
        for skill_md in sorted(root.glob("*/SKILL.md")):
            name = ""
            try:
                text = skill_md.read_text(encoding="utf-8-sig", errors="replace")
                fm = re.search(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
                if fm:
                    name_match = re.search(r"^name:\s*(.+?)\s*$", fm.group(1), re.MULTILINE)
                    if name_match:
                        name = name_match.group(1).strip().strip('"\'')
            except OSError:
                continue
            names.append(name or skill_md.parent.name)
    return sorted(set(names))


def _hook_summary_from_files(files: list[Path]) -> list[dict[str, Any]]:
    """解析插件的 hooks.json，返回事件摘要列表（event/matcher/type）。"""
    summary: list[dict[str, Any]] = []
    for path in files:
        if not path.exists():
            continue
        try:
            raw = _json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, _json.JSONDecodeError):
            continue
        hooks = raw.get("hooks", {}) if isinstance(raw, dict) else {}
        if not isinstance(hooks, dict):
            continue
        for event, groups in hooks.items():
            if not isinstance(groups, list):
                continue
            for group in groups:
                if not isinstance(group, dict):
                    continue
                matcher = str(group.get("matcher") or "*")
                handlers = group.get("hooks", [])
                if isinstance(handlers, list) and handlers:
                    first = handlers[0]
                    htype = first.get("type") if isinstance(first, dict) else "command"
                else:
                    htype = "command"
                summary.append(
                    {"event": str(event), "matcher": matcher, "type": str(htype or "command")}
                )
    return summary


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
    from lamtools_core.config.root import lam_home
    home_lam = lam_home()
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
    data_dir: str | Path | None = None,
    install_root: str | Path | None = None,
) -> OperationCatalog:
    catalog = OperationCatalog()

    async def plugin_list(request: OperationRequest) -> OperationResult:
        from .tools import load_plugin_tools

        plugins: list[dict[str, Any]] = []
        for item in plugin_registry.discover():
            tool_status: list[dict[str, Any]] = []
            for tool_file in item.tool_files:
                if not tool_file.exists():
                    tool_status.append({"path": str(tool_file), "error": "tool file not found"})
                    continue
                try:
                    declared = load_plugin_tools([tool_file], plugin_root=item.root)
                except (OSError, ValueError, _json.JSONDecodeError) as exc:
                    tool_status.append({"path": str(tool_file), "error": str(exc)})
                    continue
                tool_status.append(
                    {
                        "path": str(tool_file),
                        "tools": [
                            {
                                "name": tool.name,
                                "permission": tool.permission,
                                "visibility": tool.visibility,
                                "skill": tool.skill,
                                "handler": tool.handler,
                                "timeout": tool.timeout,
                            }
                            for tool in declared
                        ],
                    }
                )
            plugins.append(
                {
                    "name": item.name,
                    "version": item.version,
                    "description": item.description,
                    "manifest_version": item.manifest_version,
                    "root": str(item.root),
                    "enabled": item.enabled,
                    "skills": [str(path) for path in item.skill_roots],
                    "hooks": [str(path) for path in item.hook_files],
                    "mcp": [str(path) for path in item.mcp_files],
                    "tools": tool_status,
                    # 插件资产明细（配置卡片展示用）：具体技能名 / 钩子事件摘要
                    "skill_names": _skill_names_from_roots(item.skill_roots),
                    "hook_summary": _hook_summary_from_files(item.hook_files),
                    "dependencies": list(item.dependencies),
                    # B10：依赖状态（已装/缺失/版本不符）随 list 全量返回
                    "deps_status": (
                        check_dependencies(item.dependencies)["status"]
                        if item.dependencies
                        else "none"
                    ),
                    "config_schema": str(item.config_schema) if item.config_schema else "",
                }
            )
        return OperationResult(
            name=request.name,
            payload={
                "plugins": plugins,
                "errors": plugin_registry.discover_errors,
            },
        )

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

    # NOTE: there is deliberately no ``hook.trust_all`` operation.  Trusting a
    # hook grants it arbitrary command execution on every matching event, so
    # trust must stay a deliberate per-hook decision (audit 12 S2: a page could
    # one-shot trust every repository-delivered hook and then trigger them).

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

    # ── websearch config（D5 共识：配置迁入 websearch 插件配置，
    #    名称/契约保留——websearch.config.get/update 转发 plugin.config，
    #    旧 .lam/core/config/websearch.jsonc 自动迁移）──────────────

    async def websearch_config_get(request: OperationRequest) -> OperationResult:
        from .config_store import plugin_config_path, write_plugin_config

        path = plugin_config_path(data_dir, "websearch") if data_dir else None
        if path is not None and path.exists():
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
                raw = _json.loads(_strip_jsonc_comments(content)) if content.strip() else {}
                if path is not None and isinstance(raw, dict):
                    write_plugin_config(data_dir, "websearch", raw)
                return OperationResult(name=request.name, payload={"content": content, "path": str(legacy)})
            except (_json.JSONDecodeError, OSError) as exc:
                return OperationResult(name=request.name, status="error", payload={"error": str(exc)})
        return OperationResult(
            name=request.name,
            payload={"content": "", "path": str(path) if path else ""},
        )

    async def websearch_config_update(request: OperationRequest) -> OperationResult:
        content = str(request.payload.get("content") or "")
        if data_dir is None:
            return OperationResult(name=request.name, status="error", payload={"error": "data_dir not configured"})
        from .config_store import plugin_config_path, write_plugin_config

        try:
            # validate – allow JSONC (comments), factory strips them on read
            raw = _json.loads(_strip_jsonc_comments(content)) if content.strip() else {}
        except _json.JSONDecodeError as exc:
            return OperationResult(name=request.name, status="error", payload={"error": f"Invalid JSON/JSONC: {exc}"})
        try:
            write_plugin_config(data_dir, "websearch", raw if isinstance(raw, dict) else {})
        except OSError as exc:
            return OperationResult(name=request.name, status="error", payload={"error": str(exc)})
        path = plugin_config_path(data_dir, "websearch")
        return OperationResult(name=request.name, payload={"path": str(path), "saved": True})

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
        if not re.match(r"^[A-Za-z0-9._-]+$", name):
            return OperationResult(
                name=request.name, status="error",
                payload={"error": "技能名只允许字母/数字/._-（将作为目录名）"},
            )
        from lamtools_core.config.root import lam_home

        skill_dir = lam_home() / "skills" / name
        if skill_dir.exists():
            return OperationResult(
                name=request.name, status="error",
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

    # ── 插件生命周期（S2：安装 / 卸载 / 依赖状态 / 配置）──────────

    def _resolve_install_root(target: str) -> Path:
        if target == "project":
            if not work_root:
                raise ValueError("project install requires work_root")
            from .registry import default_project_plugin_root
            return default_project_plugin_root(work_root)
        if install_root is not None:
            return Path(install_root).resolve()
        from .registry import default_user_plugin_root
        return default_user_plugin_root()

    def _read_manifest_raw(plugin_dir: Path) -> dict[str, Any]:
        """读插件目录的 plugin.json（供安装后校验/依赖/名称）。"""
        manifest_path = plugin_dir / "plugin.json"
        if not manifest_path.exists():
            raise ValueError(f"no plugin.json found in {plugin_dir}")
        raw = _json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        if not isinstance(raw, dict):
            raise ValueError(f"plugin manifest must be an object: {manifest_path}")
        return raw

    async def plugin_install(request: OperationRequest) -> OperationResult:
        """安装插件：本地目录 / zip / GitHub Release URL。

        payload: {source: "local"|"zip"|"url", path?, url?, target?,
                  sha256?, install_deps?}
        """
        payload = request.payload if isinstance(request.payload, dict) else {}
        source = str(payload.get("source") or "").strip().lower()
        target = str(payload.get("target") or "user").strip().lower()
        install_deps = bool(payload.get("install_deps", True))
        from .install import (
            download_to_file,
            find_plugin_manifest_dir,
            install_from_directory,
            parse_github_release_url,
            safe_extract_zip,
            sha256_of_file,
        )

        try:
            root = _resolve_install_root(target)
            root.mkdir(parents=True, exist_ok=True)
            staging = root / f".install-{request.metadata.get('tool_call_id', 'tmp')}" if request.metadata else root / ".install-tmp"
            if not source:
                return OperationResult(name=request.name, status="error", payload={"error": "source is required (local|zip|url|cc|codex)"})
            warnings: list[str] = []
            if source in ("cc", "claude-code", "codex"):
                # C1 共识：社区插件适配器——翻译为 LamTools 插件后走 local 流程
                from .adapters import ADAPTERS

                adapter_src = Path(str(payload.get("path") or "")).resolve()
                if not adapter_src.exists() or not adapter_src.is_dir():
                    return OperationResult(
                        name=request.name, status="error",
                        payload={"error": f"plugin directory not found: {adapter_src}"},
                    )
                if staging.exists():
                    shutil.rmtree(staging)
                try:
                    adapter_result = ADAPTERS[source](adapter_src, staging)
                except (OSError, ValueError, _json.JSONDecodeError) as exc:
                    return OperationResult(
                        name=request.name, status="error",
                        payload={"error": f"adapter failed: {exc}"},
                    )
                raw_manifest = _read_manifest_raw(staging)
                name = str(raw_manifest.get("name") or staging.name).strip()
                final_dir = root / name
                if final_dir.exists():
                    shutil.rmtree(final_dir)
                final_dir.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(staging, final_dir)
                warnings = list(adapter_result.get("warnings") or [])
            elif source == "local":
                local_path = str(payload.get("path") or "").strip()
                if not local_path:
                    return OperationResult(name=request.name, status="error", payload={"error": "path is required for local install"})
                src_dir = Path(local_path).resolve()
                if not src_dir.exists() or not src_dir.is_dir():
                    return OperationResult(name=request.name, status="error", payload={"error": f"plugin directory not found: {src_dir}"})
                manifest_dir = src_dir
                raw_manifest = _read_manifest_raw(manifest_dir)
                name = str(raw_manifest.get("name") or manifest_dir.name).strip()
                final_dir = root / name
                install_from_directory(src_dir, final_dir)
            elif source == "zip":
                zip_path = str(payload.get("path") or "").strip()
                if not zip_path:
                    return OperationResult(name=request.name, status="error", payload={"error": "path is required for zip install"})
                archive = Path(zip_path).resolve()
                if not archive.exists():
                    return OperationResult(name=request.name, status="error", payload={"error": f"zip not found: {archive}"})
                if staging.exists():
                    shutil.rmtree(staging)
                try:
                    safe_extract_zip(archive, staging)
                    manifest_dir = find_plugin_manifest_dir(staging)
                    if manifest_dir is None:
                        return OperationResult(name=request.name, status="error", payload={"error": "zip contains no plugin.json"})
                    raw_manifest = _read_manifest_raw(manifest_dir)
                    name = str(raw_manifest.get("name") or manifest_dir.name).strip()
                    final_dir = root / name
                    if final_dir.exists():
                        shutil.rmtree(final_dir)
                    final_dir.parent.mkdir(parents=True, exist_ok=True)
                    if manifest_dir != staging:
                        shutil.copytree(manifest_dir, final_dir)
                    else:
                        shutil.copytree(staging, final_dir)
                finally:
                    if staging.exists():
                        shutil.rmtree(staging)
            elif source == "url":
                url = str(payload.get("url") or "").strip()
                if not url:
                    return OperationResult(name=request.name, status="error", payload={"error": "url is required for url install"})
                parsed = parse_github_release_url(url)
                if parsed is None:
                    return OperationResult(
                        name=request.name, status="error",
                        payload={"error": "unsupported URL: only GitHub Release asset URLs are supported"},
                    )
                if not url.lower().endswith(".zip"):
                    return OperationResult(name=request.name, status="error", payload={"error": "release asset must be a .zip file"})
                archive = root / f".download-{parsed['asset']}"
                ok, result = await download_to_file(url, archive)
                if not ok:
                    return OperationResult(name=request.name, status="error", payload={"error": result})
                digest = result
                expected_sha = str(payload.get("sha256") or "").strip().lower()
                if expected_sha:
                    if digest != expected_sha:
                        try:
                            archive.unlink()
                        except OSError:
                            pass
                        return OperationResult(
                            name=request.name, status="error",
                            payload={"error": f"sha256 mismatch: expected {expected_sha}, got {digest}"},
                        )
                else:
                    _logger.warning(
                        "[plugins:install] no sha256 provided for %s — downloaded digest %s",
                        url, digest,
                    )
                if staging.exists():
                    shutil.rmtree(staging)
                try:
                    safe_extract_zip(archive, staging)
                    manifest_dir = find_plugin_manifest_dir(staging)
                    if manifest_dir is None:
                        return OperationResult(name=request.name, status="error", payload={"error": "zip contains no plugin.json"})
                    raw_manifest = _read_manifest_raw(manifest_dir)
                    name = str(raw_manifest.get("name") or manifest_dir.name).strip()
                    final_dir = root / name
                    if final_dir.exists():
                        shutil.rmtree(final_dir)
                    final_dir.parent.mkdir(parents=True, exist_ok=True)
                    if manifest_dir != staging:
                        shutil.copytree(manifest_dir, final_dir)
                    else:
                        shutil.copytree(staging, final_dir)
                finally:
                    if staging.exists():
                        shutil.rmtree(staging)
                    try:
                        archive.unlink()
                    except OSError:
                        pass
            else:
                return OperationResult(name=request.name, status="error", payload={"error": f"unknown source: {source}"})
            if source in ("cc", "claude-code", "codex") and staging.exists():
                shutil.rmtree(staging)
        except (OSError, ValueError, _json.JSONDecodeError) as exc:
            return OperationResult(name=request.name, status="error", payload={"error": f"install failed: {exc}"})

        # 安装成功：重装即更新（B9）——注册表记录安装信息
        version = str(raw_manifest.get("version") or "0.0.0")
        plugin_state_store.update_entry(
            name,
            installed=True,
            installed_at=_now_iso(),
            source=source,
            target=target,
            version=version,
        )
        # 依赖安装（B3：dry-run 冲突检测 → 拒装并回滚）
        dependencies = [
            str(item).strip()
            for item in raw_manifest.get("dependencies", [])
            if isinstance(item, str) and str(item).strip()
        ] if isinstance(raw_manifest.get("dependencies"), list) else []
        deps_status: dict[str, Any] = {"status": "none", "missing": []}
        if dependencies and install_deps:
            from .deps import dry_run_install, install_dependencies

            cwd = final_dir
            ok_dry, conflicts, detail = await dry_run_install(dependencies, cwd=cwd)
            if not ok_dry:
                if conflicts:
                    # 冲突 → 回滚本次安装（B3 共识：冲突即拒装）
                    try:
                        if final_dir.exists():
                            shutil.rmtree(final_dir)
                    except OSError:
                        pass
                    plugin_state_store.update_entry(name, installed=False)
                    return OperationResult(
                        name=request.name, status="error",
                        payload={
                            "error": "dependency conflict with existing packages",
                            "conflicts": conflicts,
                            "detail": detail,
                            "rollback": "plugin directory removed",
                        },
                    )
                return OperationResult(
                    name=request.name, status="error",
                    payload={"error": f"dependency resolution failed: {detail}"},
                )
            ok_install, install_detail = await install_dependencies(dependencies, cwd=cwd)
            if not ok_install:
                return OperationResult(
                    name=request.name, status="error",
                    payload={"error": f"pip install failed: {install_detail}"},
                )
            plugin_state_store.update_entry(name, deps_installed=list(dependencies))
            deps_status = {"status": "installed", "missing": []}
        elif dependencies:
            deps_status = {"status": "skipped", "missing": list(dependencies)}

        return OperationResult(
            name=request.name,
            payload={
                "name": name,
                "version": version,
                "installed": True,
                "dependencies": deps_status,
                "sha256_verified": bool(expected_sha) if source == "url" else None,
                **({"warnings": warnings} if warnings else {}),
            },
        )

    async def plugin_uninstall(request: OperationRequest) -> OperationResult:
        """卸载插件：删目录 + 可选按安装清单清依赖（默认保留）。

        payload: {name, uninstall_deps?: bool}
        """
        name = str(request.payload.get("name") or "").strip()
        if not name:
            return OperationResult(name=request.name, status="error", payload={"error": "name is required"})
        uninstall_deps = bool(request.payload.get("uninstall_deps", False)) if isinstance(request.payload, dict) else False
        plugin = next((item for item in plugin_registry.discover() if item.name == name), None)
        if plugin is None:
            return OperationResult(name=request.name, status="error", payload={"error": f"plugin '{name}' not found"})
        from .registry import bundled_plugins_dir

        if plugin.root.is_relative_to(bundled_plugins_dir().resolve()):
            # D3 共识：内置插件（包内只读资源）可禁用、不可卸载
            return OperationResult(
                name=request.name, status="error",
                payload={"error": f"'{name}' is a bundled plugin and cannot be uninstalled (disable it instead)"},
            )
        entry = plugin_state_store.get_entry(name)
        deps_installed = [str(item) for item in (entry.get("deps_installed") or []) if isinstance(item, str)]
        # 卸载依赖：检查其他插件安装清单是否共用（共用则不卸）
        removed_deps: list[str] = []
        skipped_shared: list[str] = []
        if uninstall_deps and deps_installed:
            from .deps import uninstall_dependencies

            other_plugins_deps: set[str] = set()
            for other in plugin_registry.discover():
                if other.name == name:
                    continue
                other_entry = plugin_state_store.get_entry(other.name)
                other_plugins_deps.update(
                    str(item) for item in (other_entry.get("deps_installed") or [])
                    if isinstance(item, str)
                )
            to_remove = [dep for dep in deps_installed if dep not in other_plugins_deps]
            skipped_shared = [dep for dep in deps_installed if dep in other_plugins_deps]
            if to_remove:
                ok, detail = await uninstall_dependencies(to_remove, cwd=plugin.root)
                if not ok:
                    return OperationResult(
                        name=request.name, status="error",
                        payload={"error": f"dependency uninstall failed: {detail}"},
                    )
                removed_deps = to_remove
        # 删目录（A2 共识：卸载 = 删目录）
        from .install import uninstall_plugin_directory

        try:
            uninstall_plugin_directory(plugin.root)
        except (OSError, ValueError) as exc:
            return OperationResult(name=request.name, status="error", payload={"error": f"remove failed: {exc}"})
        # 清理（E4 共识）：该插件来源的 hook 信任记录 + 插件配置
        try:
            hooks = hook_registry_factory().load()
            for hook in hooks:
                if hook.plugin_name == name and hook.definition_hash:
                    hook_trust_store.untrust(hook.definition_hash)
        except Exception:  # noqa: BLE001 — 清理失败不阻断卸载
            _logger.warning("[plugins:uninstall] hook trust cleanup failed for %s", name, exc_info=True)
        if data_dir:
            from .config_store import delete_plugin_config
            delete_plugin_config(data_dir, name)
        plugin_state_store.update_entry(name, installed=False)
        return OperationResult(
            name=request.name,
            payload={
                "name": name,
                "uninstalled": True,
                "removed_deps": removed_deps,
                "skipped_shared_deps": skipped_shared,
            },
        )

    async def plugin_deps_status(request: OperationRequest) -> OperationResult:
        """依赖状态：已装 / 缺失 / 版本不符（附安装命令）。"""
        name = str(request.payload.get("name") or "").strip()
        if not name:
            return OperationResult(name=request.name, status="error", payload={"error": "name is required"})
        plugin = next((item for item in plugin_registry.discover() if item.name == name), None)
        if plugin is None:
            return OperationResult(name=request.name, status="error", payload={"error": f"plugin '{name}' not found"})
        if not plugin.dependencies:
            return OperationResult(name=request.name, payload={"name": name, "status": "none", "items": [], "missing": []})
        from .deps import check_dependencies, install_command_hint

        result = check_dependencies(plugin.dependencies)
        result["name"] = name
        result["install_hint"] = install_command_hint(result["missing"]) if result["missing"] else ""
        return OperationResult(name=request.name, payload=result)

    def _load_schema(plugin: Any) -> dict[str, Any]:
        if plugin.config_schema is None or not plugin.config_schema.exists():
            return {}
        return _json.loads(plugin.config_schema.read_text(encoding="utf-8-sig"))

    async def plugin_config_get(request: OperationRequest) -> OperationResult:
        name = str(request.payload.get("name") or "").strip()
        if not name:
            return OperationResult(name=request.name, status="error", payload={"error": "name is required"})
        plugin = next((item for item in plugin_registry.discover() if item.name == name), None)
        if plugin is None:
            return OperationResult(name=request.name, status="error", payload={"error": f"plugin '{name}' not found"})
        schema = _load_schema(plugin)
        if data_dir is None:
            return OperationResult(name=request.name, status="error", payload={"error": "data_dir not configured"})
        from .config_store import merged_with_defaults, read_plugin_config

        config = merged_with_defaults(read_plugin_config(data_dir, name), schema)
        # 密钥打码（照抄 provider 契约：api_key/token/secret/password 字段
        # 不回显明文——mask 后客户端提交掩码/空值即保留原值）
        masked = _mask_secret_fields(config)
        return OperationResult(
            name=request.name,
            payload={
                "name": name,
                "config": masked["config"],
                "schema": schema,
                "config_schema_path": str(plugin.config_schema) if plugin.config_schema else "",
                "has_secrets": masked["has_secrets"],
                # 工作区根：前端把浏览/扫描得到的绝对路径转成工作区相对路径
                "work_root": str(work_root) if work_root else "",
            },
        )

    async def plugin_config_detect_dirs(request: OperationRequest) -> OperationResult:
        """检测 base（缺省 = 当前 work_root）下是否存在指定目录。

        x-control ``scan`` 的数据源：入参 ``{dirs: [string], case_insensitive:
        bool, base?: string}``，返回 ``{found: [{dir, path, relative}],
        missing: [dir]}``。``path`` 为解析后的绝对路径，``relative`` 为相对
        base 的 posix 路径（越界时省略）。
        """
        payload = request.payload if isinstance(request.payload, dict) else {}
        raw_dirs = payload.get("dirs")
        if not isinstance(raw_dirs, list):
            return OperationResult(name=request.name, status="error", payload={"error": "dirs must be a list"})
        dirs = [str(item).strip() for item in raw_dirs if isinstance(item, str) and str(item).strip()]
        case_insensitive = bool(payload.get("case_insensitive", False))
        base_raw = str(payload.get("base") or "").strip()
        if base_raw:
            base = Path(base_raw).expanduser().resolve()
        elif work_root:
            base = Path(work_root).expanduser().resolve()
        else:
            base = Path.cwd()
        found: list[dict[str, str]] = []
        missing: list[str] = []
        for dir_name in dirs:
            resolved = _detect_dir(base, dir_name, case_insensitive)
            if resolved is None:
                missing.append(dir_name)
                continue
            entry: dict[str, str] = {"dir": dir_name, "path": str(resolved)}
            try:
                rel = resolved.relative_to(base)
                entry["relative"] = rel.as_posix()
            except ValueError:
                pass  # 越界：只保留绝对路径
            found.append(entry)
        return OperationResult(
            name=request.name,
            payload={"found": found, "missing": missing, "base": str(base)},
        )

    async def plugin_config_update(request: OperationRequest) -> OperationResult:
        """写入插件配置（configSchema 校验值，E5 共识）。

        密钥字段（api_key/token/secret/password）提交掩码/空值 → 保留原值。
        """
        payload = request.payload if isinstance(request.payload, dict) else {}
        name = str(payload.get("name") or "").strip()
        if not name:
            return OperationResult(name=request.name, status="error", payload={"error": "name is required"})
        raw_config = payload.get("config")
        if not isinstance(raw_config, dict):
            return OperationResult(name=request.name, status="error", payload={"error": "config must be an object"})
        plugin = next((item for item in plugin_registry.discover() if item.name == name), None)
        if plugin is None:
            return OperationResult(name=request.name, status="error", payload={"error": f"plugin '{name}' not found"})
        if data_dir is None:
            return OperationResult(name=request.name, status="error", payload={"error": "data_dir not configured"})
        from .config_store import read_plugin_config, validate_config, write_plugin_config

        schema = _load_schema(plugin)
        if schema:
            errors = validate_config(raw_config, schema)
            if errors:
                return OperationResult(
                    name=request.name, status="error",
                    payload={"error": "config validation failed", "errors": errors},
                )
        # 密钥保留：掩码/空值提交不覆盖原值
        current = read_plugin_config(data_dir, name)
        merged = dict(raw_config)
        for key in _SECRET_KEY_PATTERN_MATCHES(current):
            submitted = merged.get(key)
            if isinstance(submitted, str) and submitted.strip() in {"", "********"}:
                merged[key] = current[key]
        write_plugin_config(data_dir, name, merged)
        return OperationResult(name=request.name, payload={"name": name, "config": merged, "validated": True})

    catalog.register("plugin.list", plugin_list)
    catalog.register("plugin.install", plugin_install)
    catalog.register("plugin.uninstall", plugin_uninstall)
    catalog.register("plugin.deps-status", plugin_deps_status)
    catalog.register("plugin.config.get", plugin_config_get)
    catalog.register("plugin.config.update", plugin_config_update)
    catalog.register("plugin.config.detect-dirs", plugin_config_detect_dirs)
    catalog.register("plugin.enable", plugin_enable)
    catalog.register("plugin.disable", plugin_disable)
    catalog.register("hook.list", hook_list)
    catalog.register("hook.trust", hook_trust)
    catalog.register("hook.untrust", hook_untrust)
    catalog.register("hook.delete", hook_delete)
    catalog.register("hook.config.get", hook_config_get)
    catalog.register("hook.config.update", hook_config_update)
    catalog.register("websearch.config.get", websearch_config_get)
    catalog.register("websearch.config.update", websearch_config_update)
    catalog.register("skill.list", skill_list)
    catalog.register("skill.create", skill_create)
    catalog.register("skill.enable", skill_enable)
    catalog.register("skill.disable", skill_disable)
    return catalog