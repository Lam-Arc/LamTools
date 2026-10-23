"""Per-plugin configuration stored under the plugin's own data directory.

user:“配置面板必填，作者可以自定义样式”+配置值落在 data/config.jsonc；
没有 schema 就接受任意对象，有 schema 就做最小类型、必填和枚举校验。
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from lamtools_core.llm.profiles import strip_jsonc

from .manifest import PluginManifest
from .settings import PluginConfigSpec


def config_path(manifest: PluginManifest) -> Path:
    return (manifest.root / "data" / "config.jsonc").resolve()


def read_config_values(manifest: PluginManifest) -> dict[str, Any]:
    path = config_path(manifest)
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_config_values(manifest: PluginManifest, values: dict[str, Any]) -> Path:
    path = config_path(manifest)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(values, ensure_ascii=False, indent=2) + "\n"
    handle_fd, temp_path = tempfile.mkstemp(
        dir=str(path.parent), prefix=".config-", suffix=".tmp"
    )
    try:
        with os.fdopen(handle_fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
        os.replace(temp_path, path)
    except BaseException:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise
    return path


def read_schema(manifest: PluginManifest, spec: PluginConfigSpec) -> dict[str, Any]:
    if spec.schema is None:
        return {}
    try:
        text = spec.schema.read_text(encoding="utf-8-sig")
    except OSError:
        return {}
    try:
        data = json.loads(strip_jsonc(text))
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _type_problem(key: str, value: Any, expected: str) -> str | None:
    if expected == "string":
        return None if isinstance(value, str) else f"property '{key}' must be a string"
    if expected == "integer":
        return (
            None
            if isinstance(value, int) and not isinstance(value, bool)
            else f"property '{key}' must be an integer"
        )
    if expected == "number":
        return (
            None
            if isinstance(value, (int, float)) and not isinstance(value, bool)
            else f"property '{key}' must be a number"
        )
    if expected == "boolean":
        return None if isinstance(value, bool) else f"property '{key}' must be a boolean"
    if expected == "array":
        return None if isinstance(value, list) else f"property '{key}' must be an array"
    if expected == "object":
        return None if isinstance(value, dict) else f"property '{key}' must be an object"
    return None


def validate_config(schema: dict[str, Any], values: Any) -> list[str]:
    if not isinstance(values, dict):
        return ["config must be an object"]
    if not schema:
        return []
    problems: list[str] = []
    required = schema.get("required")
    if isinstance(required, list):
        for key in required:
            if isinstance(key, str) and key not in values:
                problems.append(f"missing required key '{key}'")
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return problems
    for key, value in values.items():
        prop = properties.get(key)
        if not isinstance(prop, dict):
            continue
        expected = prop.get("type")
        if isinstance(expected, str):
            problem = _type_problem(key, value, expected)
            if problem:
                problems.append(problem)
        enum = prop.get("enum")
        if isinstance(enum, list) and value not in enum:
            problems.append(f"property '{key}' must be one of {enum}")
    return problems


__all__ = [
    "config_path",
    "read_config_values",
    "read_schema",
    "validate_config",
    "write_config_values",
]
