"""Manifest loading for the redesigned plugin system.

user:“几十行代码就能写出来一个插件”+清单只强制 name 和 version，其余字段
全部可选；未知字段原样保留，后续能力阶段再消费，新增字段不会让旧插件失效。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MANIFEST_FILENAME = "plugin.json"
SUPPORTED_SCOPES = ("global", "mode", "session")

#: Plugin names double as directory names, so they must stay one path segment.
_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class PluginManifestError(ValueError):
    """A manifest that cannot be loaded; one bad plugin must not hide others."""

    def __init__(self, path: Path, message: str) -> None:
        super().__init__(f"{message}: {path}")
        self.path = Path(path)
        self.message = message


@dataclass(frozen=True)
class PluginManifest:
    """The declarative half of a plugin, as read from ``plugin.json``."""

    name: str
    version: str
    description: str = ""
    root: Path = Path()
    enabled: bool = True
    scope: str = "global"
    #: Migration marker: ``v2`` plugins are assembled by the new plugin system
    #: and skipped by the legacy registry. Absent means ``v1``.
    assembly: str = "v1"
    #: Every declared field, including ones this step does not consume yet.
    raw: dict[str, Any] = field(default_factory=dict)


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise PluginManifestError(path, f"cannot read manifest ({exc})") from exc
    except json.JSONDecodeError as exc:
        raise PluginManifestError(path, f"manifest is not valid JSON ({exc.msg})") from exc
    if not isinstance(raw, dict):
        raise PluginManifestError(path, "manifest must be a JSON object")
    return raw


def _validate_name(value: Any, path: Path) -> str:
    name = str(value or "").strip()
    if not name:
        raise PluginManifestError(path, "name is required")
    if ".." in name or not _NAME_PATTERN.fullmatch(name):
        raise PluginManifestError(
            path,
            "name must be one path segment using letters, digits, dot, underscore or dash",
        )
    return name


def load_manifest(manifest_path: Path | str, *, enabled: bool = True) -> PluginManifest:
    """Read and validate one ``plugin.json``.

    Raises:
        PluginManifestError: the file is unreadable, not a JSON object, or a
            required field is missing or malformed.
    """
    path = Path(manifest_path)
    raw = _read_json_object(path)
    name = _validate_name(raw.get("name"), path)
    version = str(raw.get("version") or "").strip()
    if not version:
        raise PluginManifestError(path, "version is required")
    scope = str(raw.get("scope") or "global").strip().lower()
    if scope not in SUPPORTED_SCOPES:
        raise PluginManifestError(
            path,
            f"scope must be one of {', '.join(SUPPORTED_SCOPES)}",
        )
    assembly = str(raw.get("assembly") or "v1").strip().lower()
    if assembly not in ("v1", "v2"):
        raise PluginManifestError(path, "assembly must be v1 or v2")
    return PluginManifest(
        name=name,
        version=version,
        description=str(raw.get("description") or "").strip(),
        root=path.parent.resolve(),
        enabled=enabled,
        scope=scope,
        assembly=assembly,
        raw=dict(raw),
    )


__all__ = [
    "MANIFEST_FILENAME",
    "SUPPORTED_SCOPES",
    "PluginManifest",
    "PluginManifestError",
    "load_manifest",
]
