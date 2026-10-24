"""Plugin path authority for the unified plugin system.

user:“账本统一与 v1 注册表删除”+路径权威从旧 v1 注册表搬进新系统，
全仓只有一个地方回答“插件根在哪”。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


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
    """内置插件根（包内只读资源，D3 共识）。

    dev 指向源码包内 ``plugins/bundled``；frozen（PyInstaller）从
    ``_MEIPASS/resources/plugins/bundled`` 读（hatch force-include 目标）。
    目录本体留在 ``lamtools_core/plugins/bundled`` 不动，这里只从包位置推导。
    """
    if getattr(sys, "frozen", False):
        meipass = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return meipass / "resources" / "plugins" / "bundled"
    import lamtools_core.plugins as _plugins_package

    return Path(_plugins_package.__file__).resolve().parent / "bundled"


def core_plugins_root() -> Path:
    from lamtools_core.config.root import core_plugins_root as _root

    return _root()


def default_plugin_roots(
    work_root: str | Path,
    *,
    include_user_plugins: bool = True,
) -> list[Path]:
    """The scan order every host uses: user, project, core, bundled."""
    roots: list[Path] = []
    if include_user_plugins:
        roots.append(default_user_plugin_root())
    roots.append(default_project_plugin_root(work_root))
    roots.append(core_plugins_root())
    roots.append(bundled_plugins_dir())
    return roots


__all__ = [
    "bundled_plugins_dir",
    "core_plugins_root",
    "default_plugin_roots",
    "default_project_plugin_root",
    "default_user_plugin_root",
]
