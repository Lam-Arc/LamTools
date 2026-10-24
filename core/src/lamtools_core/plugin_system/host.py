"""Discovery, install, enablement and uninstall for the redesigned plugin system.

user:“一个只有名字和版本的文件夹，装上去就能用”+发现只看 plugin.json，
坏插件只报错不连坐；卸载默认保留 data。
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import zipfile
from dataclasses import replace
from pathlib import Path
from typing import Any

from .engine import check_engine, read_engine
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
                # 随包样板可以用 defaultEnabled 声明初次状态；用户一旦在
                # 插件页开关过，账本永远优先。
                default_enabled = manifest.raw.get("defaultEnabled", True)
                found[manifest.name] = replace(
                    manifest,
                    enabled=self.state.is_enabled(
                        manifest.name,
                        default=default_enabled
                        if isinstance(default_enabled, bool)
                        else True,
                    ),
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
        problems = check_engine(read_engine(manifest))
        if problems:
            raise ValueError(
                f"plugin '{manifest.name}' cannot run on this host: {'; '.join(problems)}"
            )
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
        # 随包插件属于应用本体，卸载只会把安装目录弄坏。
        try:
            from lamtools_core.plugins.registry import bundled_plugins_dir

            if manifest.root.parent == bundled_plugins_dir().resolve():
                raise ValueError(f"plugin '{name}' is bundled and cannot be uninstalled")
        except ImportError:
            pass
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


    def update_from_directory(self, source: Path | str) -> Path:
        """Replace code and resources while keeping the plugin's ``data/``."""
        source_path = Path(source).resolve()
        manifest_path = source_path / MANIFEST_FILENAME
        if not manifest_path.is_file():
            raise PluginManifestError(manifest_path, "plugin.json is missing")
        incoming = load_manifest(manifest_path)
        problems = check_engine(read_engine(incoming))
        if problems:
            raise ValueError(
                f"plugin '{incoming.name}' cannot run on this host: {'; '.join(problems)}"
            )
        existing = self.get(incoming.name)
        if existing is None:
            raise ValueError(
                f"plugin '{incoming.name}' is not installed; update cannot change the name"
            )
        target = existing.root
        staging = target.parent / f".update-{incoming.name}-{os.getpid()}"
        if staging.exists():
            shutil.rmtree(staging)
        shutil.copytree(source_path, staging)
        data = target / "data"
        if data.is_dir():
            staged_data = staging / "data"
            if staged_data.exists():
                shutil.rmtree(staged_data)
            shutil.move(str(data), str(staged_data))
        backup = target.parent / f".backup-{incoming.name}-{os.getpid()}"
        if backup.exists():
            shutil.rmtree(backup)
        os.replace(target, backup)
        try:
            os.replace(staging, target)
        except BaseException:
            os.replace(backup, target)
            raise
        shutil.rmtree(backup, ignore_errors=True)
        return target.resolve()

    def install_from_zip(
        self,
        archive: Path | str,
        *,
        target_root: Path | str | None = None,
    ) -> Path:
        """Extract one plugin root from a zip and install it."""
        archive_path = Path(archive).resolve()
        staging_root = Path(tempfile.mkdtemp(prefix="lamtools-plugin-")).resolve()
        try:
            with zipfile.ZipFile(archive_path) as bundle:
                names = bundle.namelist()
                for name in names:
                    normalized = name.replace("\\", "/")
                    if (
                        normalized.startswith("/")
                        or re.match(r"^[A-Za-z]:", normalized)
                        or ".." in Path(normalized).parts
                    ):
                        raise ValueError(f"zip contains a path traversal entry: {name}")
                manifests = [
                    name for name in names if name.replace("\\", "/").endswith("plugin.json")
                ]
                if not manifests:
                    raise ValueError("zip contains no plugin.json")
                shallowest = min(manifests, key=lambda item: item.count("/"))
                prefix = shallowest.replace("\\", "/")[: -len("plugin.json")]
                for name in names:
                    normalized = name.replace("\\", "/")
                    if not normalized.startswith(prefix):
                        continue
                    relative = normalized[len(prefix):]
                    if not relative or normalized.endswith("/"):
                        continue
                    destination = (staging_root / relative).resolve()
                    if not destination.is_relative_to(staging_root):
                        raise ValueError(f"zip contains a path traversal entry: {name}")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with bundle.open(name) as source, open(destination, "wb") as out:
                        shutil.copyfileobj(source, out)
            return self.install_from_directory(staging_root, target_root=target_root)
        finally:
            shutil.rmtree(staging_root, ignore_errors=True)

    def logs_dir(self, name: str) -> Path:
        manifest = self.get(name)
        if manifest is None:
            raise KeyError(f"plugin '{name}' is not installed")
        path = (manifest.root / "data" / "logs").resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path


__all__ = ["PluginHost"]
