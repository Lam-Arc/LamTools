"""Load and install module overrides before ``lamtools_core`` is imported.

user:“禁用我们的某一个文件，自己提供上去”+启动时先读覆盖表，再导入宿主；
安全模式跳过全部覆盖。这里只用标准库，不能导入 lamtools_core。
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Mapping

from .import_hook import OverrideFinder, install_overrides
from .contract import protected_target

SAFE_MODE_ENV = "LAMTOOLS_SAFE_MODE"
_TRUE_VALUES = {"1", "true", "yes", "on"}
HOST_PREFIX = "lamtools_core."

_logger = logging.getLogger("lamtools.boot.overrides")


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in _TRUE_VALUES


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _data_home(environ: Mapping[str, str]) -> Path:
    """user data dir mirrored from desktop_backend._default_data_dir (stdlib only)."""
    xdg = environ.get("XDG_DATA_HOME", "").strip()
    if xdg:
        return Path(xdg)
    return Path.home() / ".local" / "share"


def _appdata_root(environ: Mapping[str, str]) -> Path:
    appdata = environ.get("APPDATA")
    if appdata:
        return Path(appdata)
    return Path.home() / "AppData" / "Roaming"


def _core_config_root(environ: Mapping[str, str]) -> Path:
    explicit = environ.get("LAMTOOLS_CORE_CONFIG_ROOT")
    if explicit:
        return Path(explicit)
    home = environ.get("LAMTOOLS_HOME")
    if home:
        return (Path(home) / "core").resolve()
    if not getattr(sys, "frozen", False):
        # lamtools_boot → src → core/.lam/core（与 config/root.py 的开发态一致）
        return (Path(__file__).resolve().parent.parent.parent / ".lam" / "core").resolve()
    return (Path(sys.executable).resolve().parent / ".lam" / "core").resolve()


def _bundled_plugins_dir() -> Path:
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", Path(sys.executable).parent)
        return Path(meipass) / "resources" / "plugins" / "bundled"
    # lamtools_boot → src → lamtools_core/plugins/bundled
    return Path(__file__).resolve().parent.parent / "lamtools_core" / "plugins" / "bundled"


def default_plugin_roots(
    environ: Mapping[str, str],
    work_root: Path | str | None = None,
) -> list[Path]:
    """user:“boot 与运行时同一份根”+stdlib 镜像 plugin_system.paths 的
    default_plugin_roots；相等性由测试锁住，漂移即红。
    """
    home = environ.get("LAMTOOLS_HOME")
    if home:
        user_root = Path(home) / "plugins"
    else:
        user_root = _appdata_root(environ) / "LamTools" / "plugins"
    roots = [user_root]
    if work_root is not None:
        roots.append(Path(work_root).resolve() / ".lamtools" / "plugins")
    else:
        env_work_root = environ.get("LAMTOOLS_CORE_WORK_ROOT", "").strip()
        if env_work_root:
            roots.append(Path(env_work_root) / ".lamtools" / "plugins")
    roots.append(_core_config_root(environ) / "plugins")
    roots.append(_bundled_plugins_dir())
    return roots


def _default_roots(environ: Mapping[str, str]) -> list[Path]:
    return default_plugin_roots(environ)


def _default_state_path(environ: Mapping[str, str]) -> Path | None:
    explicit = environ.get("LAMTOOLS_CORE_DATA_DIR")
    if explicit:
        return Path(explicit) / "plugin-system.jsonc"
    home = environ.get("LAMTOOLS_HOME")
    if home:
        return Path(home) / "plugin-system.jsonc"
    appdata = environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "LamCore" / "plugin-system.jsonc"
    # user:“Linux 也要读得到账本”+XDG 数据目录与 desktop_backend 的
    # _default_data_dir 同一处。
    if sys.platform.startswith("linux") or environ.get("XDG_DATA_HOME"):
        return _data_home(environ) / "LamTools" / "plugin-system.jsonc"
    return None


def _is_enabled(state: Mapping[str, Any], name: str, default: bool = True) -> bool:
    plugins = state.get("plugins")
    entry = plugins.get(name) if isinstance(plugins, dict) else None
    if isinstance(entry, dict) and isinstance(entry.get("enabled"), bool):
        return entry["enabled"]
    return default


def load_boot_overrides(
    *,
    environ: Mapping[str, str] | None = None,
    roots: list[Path | str] | None = None,
    state_path: Path | str | None = None,
) -> tuple[dict[str, Path], list[str]]:
    """Return ``{module_name: plugin_file}`` plus human-readable problems."""
    env = os.environ if environ is None else environ
    if _truthy(env.get(SAFE_MODE_ENV)):
        return {}, []

    plugin_roots = [Path(root) for root in roots] if roots is not None else _default_roots(env)
    state = _read_json(Path(state_path)) if state_path is not None else _read_json(
        _default_state_path(env) or Path("__missing__")
    )
    overrides: dict[str, Path] = {}
    errors: list[str] = []
    for root in plugin_roots:
        if not root.is_dir():
            continue
        for manifest_path in sorted(root.glob("*/plugin.json")):
            data = _read_json(manifest_path)
            name = str(data.get("name") or manifest_path.parent.name).strip()
            if not name or not _is_enabled(state, name, data.get("defaultEnabled") is not False):
                continue
            declared = data.get("overrides")
            if not isinstance(declared, dict):
                continue
            plugin_root = manifest_path.parent.resolve()
            for raw_target, raw_value in declared.items():
                target = str(raw_target or "").strip()
                if target.startswith("@/"):
                    # 前端键走 import map（Core 返回页面时注入），与 boot 无关。
                    continue
                if not target.startswith(HOST_PREFIX):
                    errors.append(f"{name}: override target must start with '{HOST_PREFIX}': {target}")
                    continue
                if protected_target(target):
                    errors.append(f"{name}: recovery kernel cannot be overridden: {target}")
                    continue
                text = str(raw_value or "").strip()
                if not text.startswith("./"):
                    errors.append(f"{name}: override path must start with './': {text}")
                    continue
                candidate = (plugin_root / text[2:]).resolve()
                if not candidate.is_relative_to(plugin_root):
                    errors.append(f"{name}: override path is outside the plugin root: {text}")
                    continue
                if candidate.suffix.lower() != ".py" or not candidate.is_file():
                    errors.append(f"{name}: override file is missing or not Python: {text}")
                    continue
                if target in overrides:
                    errors.append(f"{name}: module '{target}' is already overridden")
                    continue
                overrides[target] = candidate
    return overrides, errors


def apply_boot_overrides(
    *,
    environ: Mapping[str, str] | None = None,
    roots: list[Path | str] | None = None,
    state_path: Path | str | None = None,
) -> OverrideFinder | None:
    """Install the finder and return it, or ``None`` when there is nothing to do."""
    overrides, errors = load_boot_overrides(
        environ=environ, roots=roots, state_path=state_path
    )
    for error in errors:
        _logger.warning("[plugin-overrides] %s", error)
    if not overrides:
        return None
    _logger.info("[plugin-overrides] installing %s module override(s)", len(overrides))
    return install_overrides(overrides)


__all__ = [
    "SAFE_MODE_ENV",
    "apply_boot_overrides",
    "default_plugin_roots",
    "load_boot_overrides",
]
