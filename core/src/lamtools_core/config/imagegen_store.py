"""Image-generation settings stored in a dedicated imagegen.jsonc.

The generate_image tool configuration (enabled / api_url / api_key / model)
lives in its own file under the unified config directory, parallel to
``loadtools.jsonc`` / ``websearch.jsonc`` — not inside settings.jsonc.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lamtools_core.config.root import core_config_file
from lamtools_core.llm.profiles import load_jsonc

IMAGEGEN_FILENAME = "imagegen.jsonc"

# Settings RPC namespace that routes to this file (kept for the
# settings.get/update contract used by the frontend).
IMAGEGEN_NAMESPACE = "core.imagegen"


def imagegen_config_path() -> Path:
    """Return the imagegen.jsonc path (unified config directory)."""
    return core_config_file(IMAGEGEN_FILENAME)


def _load_legacy() -> dict[str, Any]:
    """读旧位置（.lam/core/config/imagegen.jsonc）。"""
    try:
        data = load_jsonc(imagegen_config_path())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def load_imagegen_config(data_dir: Path | str | None = None) -> dict[str, Any]:
    """Read the imagegen settings.

    D5 共识：配置迁入插件配置位置 ``{data_dir}/plugins/imagegen.jsonc``。
    - ``data_dir`` 给定时优先读插件配置；旧位置（.lam/core/config/
      imagegen.jsonc）有数据则自动迁移（读旧写新，幂等，不删旧文件）。
    - ``data_dir`` 为 None 时保持旧行为（兼容未接 data_dir 的调用方）。
    """
    if data_dir is not None:
        from lamtools_core.plugins.config_store import read_plugin_config, write_plugin_config

        config = read_plugin_config(data_dir, "imagegen")
        if config:
            return config
        legacy = _load_legacy()
        if legacy:
            try:
                write_plugin_config(data_dir, "imagegen", legacy)
            except OSError:
                pass  # 迁移失败不阻断——下次仍会尝试
            return legacy
        return {}
    return _load_legacy()


def save_imagegen_config(value: dict[str, Any], data_dir: Path | str | None = None) -> Path:
    """Write the imagegen settings (atomic-ish, plaintext api_key).

    D5：data_dir 给定时写插件配置位置（配置迁入插件），否则写旧位置。
    """
    if data_dir is not None:
        from lamtools_core.plugins.config_store import write_plugin_config

        write_plugin_config(data_dir, "imagegen", value)
        return imagegen_config_path()
    path = imagegen_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    import json

    from lamtools_core.config.root import atomic_write_text

    atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2))
    return path


__all__ = [
    "IMAGEGEN_FILENAME",
    "IMAGEGEN_NAMESPACE",
    "imagegen_config_path",
    "load_imagegen_config",
    "save_imagegen_config",
]
