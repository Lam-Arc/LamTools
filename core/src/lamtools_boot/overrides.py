"""Load and install module overrides before ``lamtools_core`` is imported.

user:“禁用我们的某一个文件，自己提供上去”+启动时先读覆盖表，再导入宿主；
安全模式跳过全部覆盖。这里只用标准库，不能导入 lamtools_core。
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Mapping

from .import_hook import OverrideFinder, install_overrides

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


def _default_roots(environ: Mapping[str, str]) -> list[Path]:
    home = environ.get("LAMTOOLS_HOME")
    if home:
        return [Path(home) / "plugins"]
    appdata = environ.get("APPDATA")
    if appdata:
        return [Path(appdata) / "LamTools" / "plugins"]
    return []


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
    return None


def _is_enabled(state: Mapping[str, Any], name: str) -> bool:
    plugins = state.get("plugins")
    entry = plugins.get(name) if isinstance(plugins, dict) else None
    if isinstance(entry, dict) and isinstance(entry.get("enabled"), bool):
        return entry["enabled"]
    return True


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
            if not name or not _is_enabled(state, name):
                continue
            declared = data.get("overrides")
            if not isinstance(declared, dict):
                continue
            plugin_root = manifest_path.parent.resolve()
            for raw_target, raw_value in declared.items():
                target = str(raw_target or "").strip()
                if not target.startswith(HOST_PREFIX):
                    errors.append(f"{name}: override target must start with '{HOST_PREFIX}': {target}")
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


__all__ = ["SAFE_MODE_ENV", "apply_boot_overrides", "load_boot_overrides"]
