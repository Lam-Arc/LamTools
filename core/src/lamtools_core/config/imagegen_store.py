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


def load_imagegen_config() -> dict[str, Any]:
    """Read the imagegen settings; missing/corrupt file yields {}."""
    try:
        data = load_jsonc(imagegen_config_path())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_imagegen_config(value: dict[str, Any]) -> Path:
    """Write the imagegen settings (atomic-ish, plaintext api_key)."""
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
