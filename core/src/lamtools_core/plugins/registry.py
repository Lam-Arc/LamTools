from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from .models import PluginManifest

_logger = logging.getLogger(__name__)


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


class PluginStateStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"plugins": {}}
        data = json.loads(self.path.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {"plugins": {}}

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

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


class PluginRegistry:
    def __init__(
        self,
        *,
        plugin_roots: list[Path | str],
        state_store: PluginStateStore | None = None,
    ) -> None:
        self.plugin_roots = [Path(root).resolve() for root in plugin_roots]
        self.state_store = state_store

    def discover(self) -> list[PluginManifest]:
        items: list[PluginManifest] = []
        for root in self.plugin_roots:
            if not root.exists():
                continue
            for manifest_path in sorted(root.glob("*/plugin.json")):
                try:
                    items.append(self._read_manifest(manifest_path))
                except (OSError, ValueError, json.JSONDecodeError):
                    # One corrupt plugin must never hide every other plugin
                    # (audit 11) — skip it and keep going.
                    _logger.warning(
                        "[plugins:discover] skipping unreadable manifest %s",
                        manifest_path,
                        exc_info=True,
                    )
        return sorted(items, key=lambda item: item.name)

    def _read_manifest(self, manifest_path: Path) -> PluginManifest:
        raw = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        if not isinstance(raw, dict):
            raise ValueError(f"plugin manifest must be an object: {manifest_path}")
        name = str(raw.get("name") or manifest_path.parent.name).strip()
        if not name:
            raise ValueError(f"plugin name is required: {manifest_path}")
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
            root=root,
            enabled=enabled,
            skill_roots=self._paths(root, raw.get("skills")),
            hook_files=hook_files,
            mcp_files=mcp_files,
            permissions=raw.get("permissions") if isinstance(raw.get("permissions"), dict) else {},
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
