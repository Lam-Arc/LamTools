"""Load and install module replacements and function patches before import.

user:“禁用我们的某一段函数，自己提供一个函数上去”+启动时先读覆盖表，再导入
宿主；函数补丁在模块执行完成、调用方绑定名字之前应用。安全模式跳过全部覆盖。
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Mapping

from .contract import protected_target
from .import_hook import OverrideFinder, OverrideTable, install_overrides

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
        # user:“迁移”+(新目录优先；如果只有旧版写过的 LamCore 账本，
        # 仍按旧位置读取，等待壳的一次性搬迁把它挪到 Sunday。)
        current = Path(appdata) / "Sunday" / "plugin-system.jsonc"
        legacy = Path(appdata) / "LamCore" / "plugin-system.jsonc"
        return current if current.exists() or not legacy.exists() else legacy
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


def _parse_target(name: str, raw: Any, errors: list[str]) -> tuple[str, str] | None:
    target = str(raw or "").strip()
    module, _separator, function = target.partition(":")
    if not module.startswith(HOST_PREFIX):
        errors.append(f"{name}: override target must start with '{HOST_PREFIX}': {target}")
        return None
    if protected_target(module):
        errors.append(f"{name}: recovery kernel cannot be overridden: {module}")
        return None
    if any(not part.isidentifier() for part in module.split(".")):
        errors.append(f"{name}: override target is not a module name: {target}")
        return None
    if function and not function.isidentifier():
        errors.append(f"{name}: override function is not a name: {target}")
        return None
    return module, function


def load_boot_overrides(
    *,
    environ: Mapping[str, str] | None = None,
    roots: list[Path | str] | None = None,
    state_path: Path | str | None = None,
) -> tuple[OverrideTable, list[str]]:
    """Return the override table plus human-readable problems."""
    env = os.environ if environ is None else environ
    if _truthy(env.get(SAFE_MODE_ENV)):
        return OverrideTable(), []

    plugin_roots = [Path(root) for root in roots] if roots is not None else _default_roots(env)
    state = _read_json(Path(state_path)) if state_path is not None else _read_json(
        _default_state_path(env) or Path("__missing__")
    )
    table = OverrideTable()
    errors: list[str] = []
    for root in plugin_roots:
        if not root.is_dir():
            continue
        for manifest_path in sorted(root.glob("*/plugin.json")):
            data = _read_json(manifest_path)
            name = str(data.get("name") or manifest_path.parent.name).strip()
            if not name or not _is_enabled(
                state, name, data.get("defaultEnabled") is not False
            ):
                continue
            declared = data.get("overrides")
            if not isinstance(declared, dict):
                continue
            plugin_root = manifest_path.parent.resolve()
            for raw_target, raw_value in declared.items():
                target_text = str(raw_target or "").strip()
                if target_text.startswith("@/"):
                    # 前端键走 import map（Core 返回页面时注入），与 boot 无关。
                    continue
                parsed = _parse_target(name, target_text, errors)
                if parsed is None:
                    continue
                module, function = parsed
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
                if function:
                    if module in table.modules:
                        errors.append(
                            f"{name}: module '{module}' is replaced; function patch '{function}' skipped"
                        )
                        continue
                    patches = table.patches.setdefault(module, {})
                    if function in patches:
                        errors.append(
                            f"{name}: function '{module}:{function}' is already patched"
                        )
                        continue
                    patches[function] = candidate
                else:
                    if table.patches.get(module):
                        errors.append(
                            f"{name}: module '{module}' has function patches; whole-module replacement skipped"
                        )
                        continue
                    if module in table.modules:
                        errors.append(f"{name}: module '{module}' is already overridden")
                        continue
                    table.modules[module] = candidate
    return table, errors


def apply_boot_overrides(
    *,
    environ: Mapping[str, str] | None = None,
    roots: list[Path | str] | None = None,
    state_path: Path | str | None = None,
) -> OverrideFinder | None:
    """Install the finder and return it, or ``None`` when there is nothing to do."""
    table, errors = load_boot_overrides(
        environ=environ, roots=roots, state_path=state_path
    )
    for error in errors:
        _logger.warning("[plugin-overrides] %s", error)
    if table.is_empty():
        return None
    count = len(table.modules) + sum(len(items) for items in table.patches.values())
    _logger.info("[plugin-overrides] installing %s override(s)", count)
    return install_overrides(table)


__all__ = [
    "SAFE_MODE_ENV",
    "apply_boot_overrides",
    "default_plugin_roots",
    "load_boot_overrides",
]
