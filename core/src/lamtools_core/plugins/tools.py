"""插件原生工具：tools.jsonc 解析 + ToolSpec 补全（半声明式）。

两条声明通道，复用同一套补全逻辑：
- 第三方插件：tools.jsonc 完整声明（name/description/input_schema/...）；
- 内置插件（S3）：tools.jsonc 只列 name/handler，description/input_schema
  等从 core 常量（default_core_tool_specs 按名索引）补全——零 spec 迁移。

补全模式照抄 default_toolbox.default_core_tool_specs（510-533）：
声明字段优先，集中表兜底。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ._jsonc import load_jsonc_text
from .models import PluginToolSpec

_logger = logging.getLogger(__name__)

_VALID_PERMISSIONS = ("auto_allow", "ask_user", "hard_block")
_VALID_VISIBILITIES = ("always", "on_load")

# 插件工具 spec 的默认元数据（与 default_toolbox 的 display 卡片同构）
_DEFAULT_CATEGORY = "plugin"
_DEFAULT_DISPLAY = {"card": "tool", "default_collapsed": False}


def load_plugin_tools(tool_files: list[Path], *, plugin_root: Path) -> list[PluginToolSpec]:
    """解析插件的 tools.jsonc 清单（全部文件合并，重复工具名报错）。

    Raises:
        ValueError / OSError / json.JSONDecodeError — 清单非法；调用方
        （装配 / plugin.list）负责把错误表面化为"工具不可用"状态。
    """
    declared: list[PluginToolSpec] = []
    seen: dict[str, Path] = {}
    for tool_file in tool_files:
        data = load_jsonc_text(tool_file)
        items = data.get("tools") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise ValueError(f"tools.jsonc must contain a 'tools' array: {tool_file}")
        for idx, raw in enumerate(items):
            if not isinstance(raw, dict):
                raise ValueError(f"tool #{idx} must be an object: {tool_file}")
            name = str(raw.get("name") or "").strip()
            if not name:
                raise ValueError(f"tool #{idx} is missing 'name': {tool_file}")
            handler = str(raw.get("handler") or "").strip()
            if not handler:
                raise ValueError(f"tool '{name}' is missing 'handler' (module:function): {tool_file}")
            if name in seen:
                raise ValueError(
                    f"duplicate tool name '{name}' ({seen[name]} and {tool_file})"
                )
            seen[name] = tool_file
            permission = str(raw.get("permission") or "ask_user").strip()
            if permission not in _VALID_PERMISSIONS:
                raise ValueError(
                    f"tool '{name}' has invalid permission '{permission}' "
                    f"(expected one of {_VALID_PERMISSIONS}): {tool_file}"
                )
            visibility = str(raw.get("visibility") or "always").strip()
            if visibility not in _VALID_VISIBILITIES:
                raise ValueError(
                    f"tool '{name}' has invalid visibility '{visibility}' "
                    f"(expected one of {_VALID_VISIBILITIES}): {tool_file}"
                )
            skill = str(raw.get("skill") or "").strip()
            if visibility == "on_load" and not skill:
                raise ValueError(
                    f"tool '{name}' has visibility=on_load but no 'skill' "
                    f"(declare which skill loads it): {tool_file}"
                )
            timeout_raw = raw.get("timeout")
            timeout: float | None = None
            if timeout_raw is not None:
                try:
                    timeout = float(timeout_raw)
                except (TypeError, ValueError):
                    raise ValueError(
                        f"tool '{name}' has invalid timeout '{timeout_raw!r}': {tool_file}"
                    ) from None
                if timeout <= 0:
                    raise ValueError(f"tool '{name}' timeout must be positive: {tool_file}")
            declared.append(
                PluginToolSpec(
                    name=name,
                    description=str(raw.get("description") or ""),
                    input_schema=(
                        raw.get("input_schema")
                        if isinstance(raw.get("input_schema"), dict)
                        else {}
                    ),
                    output_schema=(
                        raw.get("output_schema")
                        if isinstance(raw.get("output_schema"), dict)
                        else {}
                    ),
                    permission=permission,
                    category=str(raw.get("category") or _DEFAULT_CATEGORY).strip(),
                    visibility=visibility,
                    skill=skill,
                    handler=handler,
                    timeout=timeout,
                    raw=dict(raw),
                )
            )
    return declared


def complete_plugin_tool_specs(
    declared: list[PluginToolSpec],
    *,
    plugin_name: str,
    plugin_root: Path,
    base_specs_by_name: dict[str, Any] | None = None,
    dependencies: list[str] | None = None,
) -> list[Any]:
    """把插件工具声明补全为 core 的 ToolSpec（惰性 import 避免循环）。

    - 声明字段优先；缺失的 description/input_schema/output_schema 从
      base_specs_by_name（内置插件半声明式引用 core 常量）补全。
    - permission 永远以声明为准（安全默认 ask_user），不继承 base——
      插件工具权限独立声明（§4 共识）。
    - 额外字段（category/visibility/skill/timeout/handler/plugin 归属）
      按约定进 ToolSpec.metadata（与 default_core_tool_specs 同构）。
    """
    from lamtools_core.tool import ToolSpec

    specs: list[ToolSpec] = []
    for item in declared:
        base = (base_specs_by_name or {}).get(item.name)
        description = item.description or (getattr(base, "description", "") if base else "")
        input_schema = item.input_schema or (getattr(base, "input_schema", {}) if base else {})
        output_schema = item.output_schema or (getattr(base, "output_schema", {}) if base else {})
        base_metadata = (getattr(base, "metadata", {}) or {}) if base else {}
        # category 默认值 "plugin" 非空——内置半声明式引用 core 常量时，
        # 未显式声明 category 则从 base 补全（第三方完整声明不受影响）
        category = item.category
        if base is not None and "category" not in item.raw:
            category = str(base_metadata.get("category") or item.category or _DEFAULT_CATEGORY)
        metadata: dict[str, Any] = {
            "category": category,
            "display": dict(base_metadata.get("display") or _DEFAULT_DISPLAY),
            "failure_modes": [],
            "recovery": "",
            "visibility": item.visibility,
            "handler": item.handler,
            "plugin": plugin_name,
            "plugin_root": str(plugin_root),
        }
        if dependencies:
            metadata["dependencies"] = list(dependencies)
        if item.skill:
            metadata["skill"] = item.skill
        if item.timeout is not None:
            metadata["timeout"] = item.timeout
        # 内置半声明式引用 core 常量时，保留其 failure_modes/recovery 契约
        if base is not None and not item.raw.get("failure_modes"):
            if base_metadata.get("failure_modes"):
                metadata["failure_modes"] = list(base_metadata["failure_modes"])
            if base_metadata.get("recovery"):
                metadata["recovery"] = str(base_metadata["recovery"])
        specs.append(
            ToolSpec(
                name=item.name,
                description=description,
                input_schema=input_schema,
                output_schema=output_schema,
                permission=item.permission,  # type: ignore[arg-type]
                metadata=metadata,
            )
        )
    return specs
