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
from collections import OrderedDict
from dataclasses import replace
from pathlib import Path
from typing import Any

from .engine import check_engine, read_engine
from .manifest import MANIFEST_FILENAME, PluginManifest, PluginManifestError, load_manifest
from .state import PluginStateStore


class PluginHost:
    """Own the plugin roots and the enable/disable ledger.

    user:“声明每轮重读”+发现保持无状态语义，但按目录指纹做短缓存：文件
    与账本没动就复用上一批清单对象，免得每次 RPC 都全量扫盘；任何写入
    （启停/安装/卸载/更新）都会显式失效。
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
        self._cache: tuple[tuple[Any, ...], list[PluginManifest], list[dict[str, Any]]] | None = None
        self._sweep_stale_staging()


    def _sweep_stale_staging(self) -> None:
        from .storage import recover_transactions
        for root in self.roots:
            if root.is_dir():
                recover_transactions(root)

    # ── 指纹缓存 ─────────────────────────────────────────────────────

    def _fingerprint(self) -> tuple[Any, ...]:
        parts: list[Any] = []
        for root in self.roots:
            root_key = str(root.resolve())
            try:
                entries = sorted(os.scandir(root), key=lambda item: item.name)
            except OSError:
                parts.append((root_key, None))
                continue
            for entry in entries:
                try:
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                    dir_mtime = entry.stat(follow_symlinks=False).st_mtime_ns
                    manifest_mtime = (
                        Path(entry.path) / MANIFEST_FILENAME
                    ).stat().st_mtime_ns
                except OSError:
                    continue
                parts.append((root_key, entry.name, dir_mtime, manifest_mtime))
        try:
            parts.append(("state", self.state.path.stat().st_mtime_ns))
        except OSError:
            parts.append(("state", None))
        return tuple(parts)

    def _invalidate(self) -> None:
        self._cache = None

    # ── 发现 ─────────────────────────────────────────────────────────

    def discover(self) -> list[PluginManifest]:
        """Return every readable plugin, sorted by name, with its enablement."""
        fingerprint = self._fingerprint()
        if self._cache is not None and self._cache[0] == fingerprint:
            return self._cache[1]
        self.errors = []
        found: dict[str, PluginManifest] = {}
        for root in self.roots:
            if not root.is_dir():
                continue
            for manifest_path in sorted(root.glob(f"*/{MANIFEST_FILENAME}")):
                if manifest_path.parent.name.startswith("."):
                    # 点开头目录（含历史 .update-/.backup- 残留）不是插件。
                    continue
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
        manifests = sorted(found.values(), key=lambda item: item.name)
        self._cache = (fingerprint, manifests, list(self.errors))
        return manifests

    def get(self, name: str) -> PluginManifest | None:
        return next((item for item in self.discover() if item.name == name), None)

    def enable(self, name: str) -> bool:
        if self.get(name) is None:
            return False
        self.state.set_enabled(name, True)
        self._invalidate()
        return True

    def disable(self, name: str) -> bool:
        if self.get(name) is None:
            return False
        self.state.set_enabled(name, False)
        self._invalidate()
        return True

    def install_from_directory(
        self,
        source: Path | str,
        *,
        target_root: Path | str | None = None,
    ) -> Path:
        """Copy one local plugin folder into a plugin root after validating it."""
        transaction = self.begin_install(source, target_root=target_root)
        transaction.commit()
        self._invalidate()
        return transaction.target

    def begin_install(self, source: Path | str, *, target_root: Path | str | None = None):
        # user:“修完打包发布新版本”+(首次安装与更新一样，运行时验证前保留可跨进程恢复的事务)。
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
        if target.exists() and (target / MANIFEST_FILENAME).exists():
            raise ValueError(f"plugin '{manifest.name}' already exists: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        from .storage import CodeTransaction
        transaction = CodeTransaction(target, source_path, self.data_path(manifest.name))
        self._invalidate()
        return transaction

    def data_path(self, name: str) -> Path:
        # user:“该重建就重建”+(数据不属于代码目录，卸载与更新不能改变其身份)。
        from .manifest import _validate_name
        _validate_name(name, self.state.path)
        return (self.state.path.parent / "plugin-data" / name).resolve()

    def available(self, name: str) -> bool:
        from .safety import safe_mode
        if safe_mode():
            return False
        manifest = self.get(name)
        if manifest is None or not manifest.enabled:
            return False
        manager = getattr(self, "backend_manager", None)
        if manager is not None:
            return manager.is_enabled(name)
        from .lifecycle import backend_entry
        return backend_entry(manifest) is None

    def runtime_manifests(self) -> list[PluginManifest]:
        return [item for item in self.discover() if self.available(item.name)]

    def uninstall(self, name: str, *, keep_data: bool = True) -> None:
        manifest = self.get(name)
        if manifest is None:
            raise KeyError(f"plugin '{name}' is not installed")
        self._assert_mutable(manifest)
        from .storage import prepare_data, remove_tree
        prepare_data(manifest.root, self.data_path(name))
        remove_tree(manifest.root)
        if not keep_data:
            remove_tree(self.data_path(name))
        self.state.forget(name)
        self._invalidate()

    def _assert_mutable(self, manifest: PluginManifest) -> None:
        from .paths import bundled_plugins_dir
        if manifest.root.parent == bundled_plugins_dir().resolve():
            raise ValueError(f"plugin '{manifest.name}' is bundled; update the application")

    def begin_update(self, source: Path | str):
        source_path = Path(source).resolve()
        incoming = load_manifest(source_path / MANIFEST_FILENAME)
        problems = check_engine(read_engine(incoming))
        if problems:
            raise ValueError('; '.join(problems))
        existing = self.get(incoming.name)
        if existing is None:
            raise ValueError(f"plugin '{incoming.name}' is not installed")
        self._assert_mutable(existing)
        from .storage import CodeTransaction
        transaction = CodeTransaction(existing.root, source_path, self.data_path(incoming.name))
        self._invalidate()
        return transaction

    def update_from_directory(self, source: Path | str) -> Path:
        # user:“该重建就重建”+(离线文件操作同样使用可回滚、同磁盘事务)。
        transaction = self.begin_update(source)
        transaction.commit()
        self._invalidate()
        return transaction.target

    def update_from_zip(self, archive: Path | str) -> Path:
        """Extract one plugin root from a zip and update from it."""
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
                    name for name in names if name.replace("\\", "/").endswith(MANIFEST_FILENAME)
                ]
                if not manifests:
                    raise ValueError("zip contains no plugin.json")
                shallowest = min(manifests, key=lambda item: item.count("/"))
                prefix = shallowest.replace("\\", "/")[: -len(MANIFEST_FILENAME)]
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
            return self.update_from_directory(staging_root)
        finally:
            shutil.rmtree(staging_root, ignore_errors=True)

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


# ── 进程级共享宿主 ─────────────────────────────────────────────────
#
# user:“宿主按（根集合, 账本）共享”+同一进程内同参数只建一个 PluginHost，
# 装配、目录构建、会话可见性复用同一实例；上限 32 个防测试会话膨胀。

_SHARED_HOSTS: "OrderedDict[tuple[tuple[str, ...], str], PluginHost]" = OrderedDict()
_SHARED_HOST_LIMIT = 32


def shared_host(*, roots: list[Path | str], state_path: Path | str) -> PluginHost:
    key = (
        tuple(str(Path(root).resolve()) for root in roots),
        str(Path(state_path).resolve()),
    )
    host = _SHARED_HOSTS.get(key)
    if host is None:
        host = PluginHost(roots=roots, state_path=state_path)
        _SHARED_HOSTS[key] = host
        while len(_SHARED_HOSTS) > _SHARED_HOST_LIMIT:
            _SHARED_HOSTS.popitem(last=False)
    else:
        _SHARED_HOSTS.move_to_end(key)
    return host


__all__ = ["PluginHost", "shared_host"]
