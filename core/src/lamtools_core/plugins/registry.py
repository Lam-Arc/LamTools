from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from ._jsonc import load_jsonc_text
from .models import PluginManifest

_logger = logging.getLogger(__name__)

# 当前支持的 manifest 版本（未来适配器时代扩展时递增校验）
SUPPORTED_MANIFEST_VERSION = "1"

# manifest 键 → PluginManifest 字段（新增工具/依赖/配置字段）
MANIFEST_DEPENDENCIES_KEY = "dependencies"
MANIFEST_TOOLS_KEY = "tools"
MANIFEST_CONFIG_SCHEMA_KEY = "configSchema"


def _appdata_root() -> Path:
    # Green/portable mode: everything lives beside the app.
    home = os.environ.get("LAMTOOLS_HOME")
    if home:
        return Path(home)
    raw = os.environ.get("APPDATA")
    if raw:
        return Path(raw)
    return Path.home() / "AppData" / "Roaming"


def default_user_plugin_root() -> Path:
    # Green/portable mode: beside the app (no LamTools nesting).
    if os.environ.get("LAMTOOLS_HOME"):
        from lamtools_core.config.root import lam_home
        return lam_home() / "plugins"
    return _appdata_root() / "LamTools" / "plugins"


def default_project_plugin_root(project_root: Path | str) -> Path:
    return Path(project_root).resolve() / ".lamtools" / "plugins"


def bundled_plugins_dir() -> Path:
    """内置插件根（git/websearch/imagegen，D3 共识：包内只读资源）。

    dev 指向源码包内 ``plugins/bundled``；frozen（PyInstaller）从
    ``_MEIPASS/resources/plugins/bundled`` 读（hatch force-include 目标，
    照抄 live_operations._bundled_config_resources_dir 双分支模式）。
    """
    import sys

    if getattr(sys, "frozen", False):
        meipass = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return meipass / "resources" / "plugins" / "bundled"
    return Path(__file__).resolve().parent / "bundled"


class PluginStateStore:
    """插件启停状态 + 安装记录，持久化于 ``{data_dir}/plugins.jsonc``。

    迁移（F1 共识）：历史 ``plugins.json`` 仍可读——jsonc 文件不存在时
    回退读旧 json 并立即写一份 jsonc，旧文件保留（不删除，避免误伤
    用户数据）。
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def _legacy_json_path(self) -> Path:
        if self.path.suffix == ".jsonc":
            return self.path.with_suffix(".json")
        return self.path

    def _load(self) -> dict[str, Any]:
        if self.path.exists():
            try:
                data = load_jsonc_text(self.path)
            except (OSError, ValueError, json.JSONDecodeError):
                _logger.warning(
                    "[plugins:state] unreadable %s, treating as empty",
                    self.path,
                    exc_info=True,
                )
                return {"plugins": {}}
            return data if isinstance(data, dict) else {"plugins": {}}
        legacy = self._legacy_json_path()
        if legacy.exists():
            try:
                data = json.loads(legacy.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError):
                return {"plugins": {}}
            if not isinstance(data, dict):
                return {"plugins": {}}
            # 首次读到旧 json → 立即写 jsonc（幂等迁移，不删旧文件）
            try:
                self._save(data)
            except OSError:
                _logger.warning("[plugins:state] failed to migrate %s", legacy, exc_info=True)
            return data
        return {"plugins": {}}

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        from lamtools_core.config.root import atomic_write_text

        atomic_write_text(
            self.path,
            json.dumps(data, ensure_ascii=False, indent=2),
        )

    def is_enabled(self, name: str) -> bool:
        plugins = self._load().get("plugins", {})
        if not isinstance(plugins, dict):
            return True
        raw = plugins.get(name, {})
        return bool(raw.get("enabled", True)) if isinstance(raw, dict) else True

    def set_enabled(self, name: str, enabled: bool) -> None:
        data = self._load()
        plugins = data.setdefault("plugins", {})
        if not isinstance(plugins, dict):
            plugins = {}
            data["plugins"] = plugins
        entry = plugins.setdefault(name, {})
        if not isinstance(entry, dict):
            entry = {}
            plugins[name] = entry
        entry["enabled"] = bool(enabled)
        self._save(data)

    def get_entry(self, name: str) -> dict[str, Any]:
        """读取插件注册表条目（安装记录/依赖清单等，缺省空 dict）。"""
        plugins = self._load().get("plugins", {})
        if not isinstance(plugins, dict):
            return {}
        raw = plugins.get(name, {})
        return dict(raw) if isinstance(raw, dict) else {}

    def update_entry(self, name: str, **fields: Any) -> None:
        data = self._load()
        plugins = data.setdefault("plugins", {})
        if not isinstance(plugins, dict):
            plugins = {}
            data["plugins"] = plugins
        entry = plugins.setdefault(name, {})
        if not isinstance(entry, dict):
            entry = {}
            plugins[name] = entry
        entry.update(fields)
        self._save(data)


class PluginRegistry:
    def __init__(
        self,
        *,
        plugin_roots: list[Path | str],
        state_store: PluginStateStore | None = None,
    ) -> None:
        self.plugin_roots = [Path(root).resolve() for root in plugin_roots]
        self.state_store = state_store
        # discover 收集的加载错误（E6：损坏插件在 plugin.list 报状态，不静默）
        self.discover_errors: list[dict[str, Any]] = []

    def discover(self) -> list[PluginManifest]:
        items: list[PluginManifest] = []
        self.discover_errors = []
        seen: set[Path] = set()
        for root in self.plugin_roots:
            if not root.exists():
                continue
            for manifest_path in sorted(root.glob("*/plugin.json")):
                if manifest_path in seen:
                    continue
                seen.add(manifest_path)
                try:
                    items.append(self._read_manifest(manifest_path))
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    # One corrupt plugin must never hide every other plugin
                    # (audit 11) — skip it, keep going, but surface it in
                    # plugin.list (E6 共识：加载错误可见，不静默跳过).
                    _logger.warning(
                        "[plugins:discover] skipping unreadable manifest %s",
                        manifest_path,
                        exc_info=True,
                    )
                    self.discover_errors.append(
                        {
                            "name": manifest_path.parent.name,
                            "path": str(manifest_path),
                            "error": str(exc),
                        }
                    )
        return sorted(items, key=lambda item: item.name)

    def _read_manifest(self, manifest_path: Path) -> PluginManifest:
        raw = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        if not isinstance(raw, dict):
            raise ValueError(f"plugin manifest must be an object: {manifest_path}")
        name = str(raw.get("name") or manifest_path.parent.name).strip()
        if not name:
            raise ValueError(f"plugin name is required: {manifest_path}")
        manifest_version = str(raw.get("manifest_version") or SUPPORTED_MANIFEST_VERSION).strip()
        if manifest_version != SUPPORTED_MANIFEST_VERSION:
            raise ValueError(
                f"unsupported manifest_version '{manifest_version}' "
                f"(supported: '{SUPPORTED_MANIFEST_VERSION}'): {manifest_path}"
            )
        root = manifest_path.parent.resolve()
        hook_files = self._paths(root, raw.get("hooks"))
        if not hook_files and (root / "hooks" / "hooks.json").exists():
            hook_files = [root / "hooks" / "hooks.json"]
        mcp_files = self._paths(root, raw.get("mcpServers"))
        if not mcp_files:
            if (root / ".mcp.json").exists():
                mcp_files = [root / ".mcp.json"]
            elif (root / "mcp" / "mcp.json").exists():
                mcp_files = [root / "mcp" / "mcp.json"]
        enabled = self.state_store.is_enabled(name) if self.state_store else True
        return PluginManifest(
            name=name,
            version=str(raw.get("version") or "0.0.0"),
            description=str(raw.get("description") or ""),
            manifest_version=manifest_version,
            root=root,
            enabled=enabled,
            skill_roots=self._paths(root, raw.get("skills")),
            hook_files=hook_files,
            mcp_files=mcp_files,
            tool_files=self._paths(root, raw.get(MANIFEST_TOOLS_KEY)),
            dependencies=[
                str(item).strip()
                for item in raw.get(MANIFEST_DEPENDENCIES_KEY, [])
                if isinstance(item, str) and str(item).strip()
            ]
            if isinstance(raw.get(MANIFEST_DEPENDENCIES_KEY), list)
            else [],
            config_schema=(
                self._paths(root, raw.get(MANIFEST_CONFIG_SCHEMA_KEY))[0]
                if raw.get(MANIFEST_CONFIG_SCHEMA_KEY)
                else None
            ),
            raw=dict(raw),
        )

    def _paths(self, root: Path, value: object) -> list[Path]:
        values = value if isinstance(value, list) else [value] if isinstance(value, str) else []
        paths: list[Path] = []
        for raw in values:
            text = str(raw or "").strip()
            if not text:
                continue
            if not text.startswith("./"):
                raise ValueError(f"plugin resource path must start with './': {text}")
            path = (root / text[2:]).resolve()
            if not path.is_relative_to(root):
                raise ValueError(f"plugin resource path is outside plugin root: {text}")
            paths.append(path)
        return paths
