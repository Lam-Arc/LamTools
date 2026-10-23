"""Discovery, install, enablement and uninstall for the redesigned plugin system.

user:“一个只有名字和版本的文件夹，装上去就能用”+发现只看 plugin.json，
坏插件只报错不连坐；卸载默认保留 data。
"""

from __future__ import annotations

import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any

from .manifest import MANIFEST_FILENAME, PluginManifest, PluginManifestError, load_manifest
from .state import PluginStateStore


class PluginHost:
    """Own the plugin roots and the enable/disable ledger.

    Discovery is deliberately stateless: every call re-reads the manifests, so
    a plugin dropped into a root is visible without a restart. Later steps add
    capability assembly on top of the returned manifests.
    """

    def __init__(
        self,
        *,
        roots: list[Path | str],
        state_path: Path | str,
    ) -> None:
        self.roots = [Path(root) for root in roots]
        self.state = PluginStateStore(state_path)
        #: Load errors for the most recent discovery, surfaced by the plugin page.
        self.errors: list[dict[str, Any]] = []

    def discover(self) -> list[PluginManifest]:
        """Return every readable plugin, sorted by name, with its enablement."""
        self.errors = []
        found: dict[str, PluginManifest] = {}
        for root in self.roots:
            if not root.is_dir():
                continue
            for manifest_path in sorted(root.glob(f"*/{MANIFEST_FILENAME}")):
                try:
                    manifest = load_manifest(manifest_path)
                except PluginManifestError as exc:
                    self.errors.append(
                        {
                            "name": manifest_path.parent.name,
                            "path": str(manifest_path),
                            "error": exc.message,
                        }
                    )
                    continue
                if manifest.name in found:
                    # Conflicts are explicit: keep the first root in scan order
                    # and report the loser instead of silently overwriting it.
                    self.errors.append(
                        {
                            "name": manifest.name,
                            "path": str(manifest_path),
                            "error": "duplicate plugin name; the first root in scan order wins",
                        }
                    )
                    continue
                found[manifest.name] = replace(
                    manifest, enabled=self.state.is_enabled(manifest.name)
                )
        return sorted(found.values(), key=lambda item: item.name)

    def get(self, name: str) -> PluginManifest | None:
        return next((item for item in self.discover() if item.name == name), None)

    def enable(self, name: str) -> bool:
        if self.get(name) is None:
            return False
        self.state.set_enabled(name, True)
        return True

    def disable(self, name: str) -> bool:
        if self.get(name) is None:
            return False
        self.state.set_enabled(name, False)
        return True

    def install_from_directory(
        self,
        source: Path | str,
        *,
        target_root: Path | str | None = None,
    ) -> Path:
        """Copy one local plugin folder into a plugin root after validating it."""
        source_path = Path(source).resolve()
        manifest_path = source_path / MANIFEST_FILENAME
        if not manifest_path.is_file():
            raise PluginManifestError(manifest_path, "plugin.json is missing")
        manifest = load_manifest(manifest_path)
        root = Path(target_root) if target_root is not None else (
            self.roots[0] if self.roots else None
        )
        if root is None:
            raise ValueError("no plugin root is configured")
        target = (root / manifest.name).resolve()
        if target.exists():
            raise ValueError(f"plugin '{manifest.name}' already exists: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_path, target)
        try:
            load_manifest(target / MANIFEST_FILENAME)
        except BaseException:
            shutil.rmtree(target, ignore_errors=True)
            raise
        return target

    def uninstall(self, name: str, *, keep_data: bool = True) -> None:
        """Remove a plugin; ``keep_data`` preserves its ``data/`` directory."""
        manifest = self.get(name)
        if manifest is None:
            raise KeyError(f"plugin '{name}' is not installed")
        if keep_data:
            for child in manifest.root.iterdir():
                if child.name == "data":
                    continue
                if child.is_symlink() or child.is_file():
                    child.unlink()
                else:
                    shutil.rmtree(child)
        else:
            shutil.rmtree(manifest.root)
        self.state.forget(name)


__all__ = ["PluginHost"]
