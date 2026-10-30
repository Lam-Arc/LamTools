"""Per-plugin config files under the shared data directory.

user:“配置跟着插件走”+历史通道 ``{data_dir}/plugins/<name>.jsonc`` 仍被
imagegen/websearch 使用（收尾方案步骤 3/5 迁到插件自己的 ``data/`` 前
保持原位）；新代码请用 :mod:`plugin_system.config_store`。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .jsonc import load_jsonc_text

_logger = logging.getLogger(__name__)


def plugin_config_path(data_dir: Path | str, plugin_name: str) -> Path:
    return Path(data_dir) / "plugins" / f"{plugin_name}.jsonc"


def read_plugin_config(data_dir: Path | str, plugin_name: str) -> dict[str, Any]:
    path = plugin_config_path(data_dir, plugin_name)
    if not path.exists():
        return {}
    try:
        data = load_jsonc_text(path)
    except (OSError, ValueError, json.JSONDecodeError):
        _logger.warning("[plugins:config] unreadable %s, treating as empty", path, exc_info=True)
        return {}
    return data if isinstance(data, dict) else {}


def write_plugin_config(data_dir: Path | str, plugin_name: str, config: dict[str, Any]) -> None:
    # user:“宿主能力补齐和接口完善与文档更新”+(内置插件旧写入方也遵守统一配置文件锁，防止与新门面交错写入)。
    from .config_store import replace_config_file
    path = plugin_config_path(data_dir, plugin_name)
    replace_config_file(path, config)


def delete_plugin_config(data_dir: Path | str, plugin_name: str) -> None:
    path = plugin_config_path(data_dir, plugin_name)
    if path.exists():
        try:
            path.unlink()
        except OSError:
            _logger.warning("[plugins:config] failed to remove %s", path, exc_info=True)


def _type_of(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    if value is None:
        return "null"
    return type(value).__name__


def _coerce_value(value: Any, schema: dict[str, Any]) -> Any:
    """按 schema 校验/回退单个值；非法返回 (None, error)。"""
    kind = str(schema.get("type") or "string")
    if kind in ("number", "integer"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None, f"expected {kind}, got {_type_of(value)}"
        if kind == "integer" and not isinstance(value, int):
            return None, "expected integer"
        return value, None
    if kind == "boolean":
        if not isinstance(value, bool):
            return None, "expected boolean"
        return value, None
    if kind == "string":
        if not isinstance(value, str):
            return None, "expected string"
        enum = schema.get("enum")
        if isinstance(enum, list) and value not in {str(item) for item in enum}:
            return None, f"must be one of {list(enum)}"
        return value, None
    if kind == "array":
        if not isinstance(value, list):
            return None, "expected array"
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for item in value:
                if _type_of(item) != str(item_schema.get("type") or "string"):
                    return None, f"array item must be {item_schema.get('type')}"
        return value, None
    if kind == "object":
        if not isinstance(value, dict):
            return None, "expected object"
        return value, None
    return value, None


def validate_config(config: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    """按 configSchema 校验配置值，返回错误列表（空 = 合法）。

    未知键忽略（向前兼容）；缺省值不回写（校验与写值分离，调用方
    决定是否合并默认）。
    """
    errors: list[str] = []
    props = schema.get("properties") if isinstance(schema, dict) else None
    if not isinstance(props, dict):
        return errors
    for key, prop_schema in props.items():
        if key not in config:
            continue
        if not isinstance(prop_schema, dict):
            continue
        value = config[key]
        coerced, error = _coerce_value(value, prop_schema)
        if error is not None:
            errors.append(f"'{key}': {error}")
    return errors


def merged_with_defaults(config: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    """合并 configSchema 中的缺省值（浅层，仅顶层键）。"""
    merged = dict(config)
    props = schema.get("properties") if isinstance(schema, dict) else None
    if not isinstance(props, dict):
        return merged
    for key, prop_schema in props.items():
        if key in merged or not isinstance(prop_schema, dict):
            continue
        if "default" in prop_schema:
            merged[key] = prop_schema["default"]
    return merged


__all__ = [
    "delete_plugin_config",
    "merged_with_defaults",
    "validate_config",
    "plugin_config_path",
    "read_plugin_config",
    "write_plugin_config",
]
