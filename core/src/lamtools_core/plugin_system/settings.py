"""Config declarations: the schema form and the optional custom panel.

user:“配置面板必填，作者可以自定义样式，不定义就落到默认样式”+schema 走
默认表单，panel 走作者自己的界面；两者都可选，缺省就是自动生成的面板。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .capabilities import CapabilityError
from .manifest import PluginManifest


@dataclass(frozen=True)
class PluginConfigSpec:
    schema: Path | None = None
    panel: Path | None = None


def _path(
    manifest: PluginManifest,
    value: Any,
    *,
    key: str,
    suffixes: tuple[str, ...],
) -> Path | None:
    if value is None:
        return None
    text = str(value or "").strip()
    if not text:
        raise CapabilityError(manifest.name, f"{key} path is empty")
    if not text.startswith("./"):
        raise CapabilityError(manifest.name, f"{key} path must start with './': {text}")
    candidate = (manifest.root / text[2:]).resolve()
    if not candidate.is_relative_to(manifest.root):
        raise CapabilityError(manifest.name, f"{key} path is outside the plugin root: {text}")
    if candidate.suffix.lower() not in suffixes:
        raise CapabilityError(
            manifest.name,
            f"{key} must be one of {', '.join(suffixes)}: {text}",
        )
    if not candidate.is_file():
        raise CapabilityError(manifest.name, f"{key} file is missing: {text}")
    return candidate


def read_config(manifest: PluginManifest) -> PluginConfigSpec:
    raw = manifest.raw.get("config")
    if raw is None:
        return PluginConfigSpec()
    if not isinstance(raw, dict):
        raise CapabilityError(manifest.name, "config must be an object")
    return PluginConfigSpec(
        schema=_path(
            manifest,
            raw.get("schema"),
            key="config schema",
            suffixes=(".jsonc", ".json"),
        ),
        panel=_path(
            manifest,
            raw.get("panel"),
            key="config panel",
            suffixes=(".js", ".mjs"),
        ),
    )


__all__ = ["PluginConfigSpec", "read_config"]
