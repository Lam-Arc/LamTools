"""Per-plugin configuration stored under the plugin's own data directory.

user:“配置面板必填，作者可以自定义样式”+配置值落在 data/config.jsonc；
没有 schema 就接受任意对象，有 schema 就做最小类型、必填和枚举校验。
"""

from __future__ import annotations

import json
import os
import tempfile
import hashlib
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lamtools_core.llm.profiles import strip_jsonc

from .manifest import PluginManifest
from .settings import PluginConfigSpec
from .jsonc import strip_jsonc_comments, strip_trailing_commas
from .file_lock import locked_file, FileLockBusy


class ConfigError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class ConfigValidation:
    valid: bool
    problems: tuple[str, ...]
    level: str = "basic"


@dataclass(frozen=True)
class ConfigSnapshot:
    values: dict[str, Any]
    schema: dict[str, Any]
    revision: str
    exists: bool
    path: str
    validation: ConfigValidation


@dataclass(frozen=True)
class ConfigSaveResult:
    snapshot: ConfigSnapshot
    saved: bool = True
    applied: bool = False
    requires_reload: bool = True


def _encode_values(values):
    def check(value):
        if type(value) is dict:
            if any(type(key) is not str for key in value):
                raise ValueError("Object keys must be strings")
            for child in value.values():
                check(child)
        elif type(value) is list:
            for child in value:
                check(child)
        elif value is not None and (type(value) not in {str, int, float, bool} or type(value) is float and not math.isfinite(value)):
            raise ValueError("Invalid JSON value")
    try:
        if type(values) is not dict:
            raise ValueError("Object required")
        check(values)
        payload = json.dumps(values, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        if len(payload.encode("utf-8")) > 1024 * 1024:
            raise ValueError("Too large")
        return payload
    except (ValueError, TypeError, RecursionError):
        raise ConfigError("config/invalid-values", "Configuration must be a finite JSON object of at most 1 MiB") from None


def _document(path, *, missing=False):
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        if missing:
            return {}, None
        raise ConfigError("config/schema", "Declared configuration schema is missing") from None
    except OSError:
        raise ConfigError("config/io", "Cannot read configuration") from None
    try:
        if len(raw) > 1024 * 1024:
            raise ValueError("Too large")
        values = json.loads(strip_trailing_commas(strip_jsonc_comments(raw.decode("utf-8-sig"))))
        _encode_values(values)
    except (ValueError, TypeError, ConfigError, RecursionError):
        raise ConfigError("config/corrupt" if missing else "config/schema", "Configuration document is not a supported JSONC object") from None
    return values, raw


def resolved_config_path(manifest, data_dir=None):
    from .paths import bundled_plugins_dir
    if manifest.root.parent.resolve() == bundled_plugins_dir().resolve():
        if data_dir is None:
            raise ConfigError("config/unavailable", "Bundled configuration requires the host data directory")
        from .plugin_data import plugin_config_path
        return plugin_config_path(data_dir, manifest.name).resolve()
    return config_path(manifest)


def _schema(manifest):
    from .settings import read_config
    from .capabilities import CapabilityError
    try:
        spec = read_config(manifest)
    except CapabilityError:
        raise ConfigError("config/schema", "Invalid plugin configuration declaration") from None
    return _document(spec.schema) if spec.schema is not None else ({}, None)


def validate_config_values(manifest, values):
    payload = _encode_values(values)
    schema, _ = _schema(manifest)
    problems = tuple(validate_config(schema, json.loads(payload)))
    return ConfigValidation(not problems, problems)


def read_config_snapshot(manifest, *, data_dir=None):
    # user:“宿主能力补齐和接口完善与文档更新”+(配置、schema 与原始字节修订一起读取，坏文件不能伪装为空配置)。
    path = resolved_config_path(manifest, data_dir)
    values, raw = _document(path, missing=True)
    schema, schema_raw = _schema(manifest)
    signature = json.dumps([str(path), manifest.name, manifest.version]).encode("utf-8")
    for value in (raw, schema_raw):
        signature += b"\x00missing" if value is None else b"\x00present" + len(value).to_bytes(8, "big") + value
    problems = tuple(validate_config(schema, values))
    return ConfigSnapshot(values, schema, hashlib.sha256(signature).hexdigest(), raw is not None, str(path), ConfigValidation(not problems, problems))


def _atomic_write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle_fd, temp_path = tempfile.mkstemp(dir=str(path.parent), prefix=".config-", suffix=".tmp")
    try:
        with os.fdopen(handle_fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        try:
            os.unlink(temp_path)
        except FileNotFoundError:
            pass


def save_config_values(manifest, values, *, data_dir=None, expected_revision=None):
    payload = _encode_values(values)
    if expected_revision is not None and (not isinstance(expected_revision, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_revision)):
        raise ConfigError("config/invalid-revision", "Expected revision must be a snapshot revision")
    path = resolved_config_path(manifest, data_dir)
    try:
        with locked_file(path.with_suffix(".lock")):
            before = read_config_snapshot(manifest, data_dir=data_dir)
            if expected_revision is not None and expected_revision != before.revision:
                raise ConfigError("config/conflict", "Configuration or schema changed; read the current snapshot before saving")
            problems = validate_config(before.schema, json.loads(payload))
            if problems:
                raise ConfigError("config/invalid-values", "; ".join(problems))
            _atomic_write(path, payload)
            return ConfigSaveResult(read_config_snapshot(manifest, data_dir=data_dir))
    except FileLockBusy:
        raise ConfigError("config/busy", "Configuration is locked by another writer") from None
    except OSError:
        raise ConfigError("config/io", "Cannot save configuration") from None


def replace_config_file(path, values):
    """Coordinate legacy bundled writers without claiming schema validation."""
    path = Path(path).resolve()
    payload = _encode_values(values)
    try:
        with locked_file(path.with_suffix(".lock")):
            _document(path, missing=True)
            _atomic_write(path, payload)
    except FileLockBusy:
        raise ConfigError("config/busy", "Configuration is locked by another writer") from None
    except OSError:
        raise ConfigError("config/io", "Cannot save configuration") from None


def config_path(manifest: PluginManifest) -> Path:
    return (manifest.root / "data" / "config.jsonc").resolve()


def read_config_values(manifest: PluginManifest) -> dict[str, Any]:
    path = config_path(manifest)
    try:
        text = path.read_text(encoding="utf-8-sig")
        data = json.loads(strip_trailing_commas(strip_jsonc_comments(text)))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_config_values(manifest: PluginManifest, values: dict[str, Any]) -> Path:
    # user:“宿主能力补齐和接口完善与文档更新”+(旧直接写入也经过同一锁与坏文件检查，不保留第二套无条件文件替换实现)。
    return Path(save_config_values(manifest, values).snapshot.path)


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
