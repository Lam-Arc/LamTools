"""插件原生 operations：operations.jsonc 解析 + operation catalog 注册（G 组）。

与 tools.jsonc 同构（G1 规格：解析/越界校验规则与 tools 相同）：
- ``operations.jsonc`` 声明数组，字段 name/description/input_schema/permission/handler；
- permission 缺省 ``auto_allow``（operation 由 UI/CLI 直接发起，调用者即用户，
  不参与模型审批链）；``hard_block`` 拒绝注册（plugin.list 报状态）；
- handler 契约：``async def handler(request, *, work_root, data_dir) -> OperationResult``
  ——注册时 partial 绑定上下文（与工具 handler 的 metadata 传参同源，但 operation
  无 ToolCall，改为关键字参数直传）。

信任语义同工具 handler（G3）：安装即永信（B4）——动态导入失败 = 该 operation
不可用，plugin.list 报状态，不阻断其他插件。
"""
from __future__ import annotations

import functools
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from lamtools_core.app import OperationCatalog, OperationRequest, OperationResult

from ._jsonc import load_jsonc_text
from .models import PluginOperationSpec

_logger = logging.getLogger(__name__)

_VALID_PERMISSIONS = ("auto_allow", "ask_user", "hard_block")


def load_plugin_operations(
    operation_files: list[Path], *, plugin_root: Path
) -> list[PluginOperationSpec]:
    """解析插件的 operations.jsonc 清单（全部文件合并，重复名报错）。

    Raises:
        ValueError / OSError / json.JSONDecodeError — 清单非法；调用方
        （catalog 构建 / plugin.list）负责把错误表面化为"operation 不可用"。
    """
    declared: list[PluginOperationSpec] = []
    seen: dict[str, Path] = {}
    for operation_file in operation_files:
        data = load_jsonc_text(operation_file)
        items = data.get("operations") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise ValueError(f"operations.jsonc must contain an 'operations' array: {operation_file}")
        for idx, raw in enumerate(items):
            if not isinstance(raw, dict):
                raise ValueError(f"operation #{idx} must be an object: {operation_file}")
            name = str(raw.get("name") or "").strip()
            if not name:
                raise ValueError(f"operation #{idx} is missing 'name': {operation_file}")
            handler = str(raw.get("handler") or "").strip()
            if not handler:
                raise ValueError(
                    f"operation '{name}' is missing 'handler' (module:function): {operation_file}"
                )
            if name in seen:
                raise ValueError(
                    f"duplicate operation name '{name}' ({seen[name]} and {operation_file})"
                )
            seen[name] = operation_file
            permission = str(raw.get("permission") or "auto_allow").strip()
            if permission not in _VALID_PERMISSIONS:
                raise ValueError(
                    f"operation '{name}' has invalid permission '{permission}' "
                    f"(expected one of {_VALID_PERMISSIONS}): {operation_file}"
                )
            declared.append(
                PluginOperationSpec(
                    name=name,
                    description=str(raw.get("description") or ""),
                    input_schema=(
                        raw.get("input_schema") if isinstance(raw.get("input_schema"), dict) else {}
                    ),
                    permission=permission,
                    handler=handler,
                    raw=dict(raw),
                )
            )
    return declared


def import_plugin_operation_handler(
    spec: PluginOperationSpec,
) -> Callable[[OperationRequest], Awaitable[OperationResult]] | None:
    """动态导入 ``module:function``（照抄工具 handler 模式，失败返回 None）。"""
    import importlib

    entry = spec.handler
    if ":" not in entry:
        _logger.warning("[plugins:operation] invalid handler entry for %s: %r", spec.name, entry)
        return None
    module_name, func_name = entry.split(":", 1)
    try:
        module = importlib.import_module(module_name)
        func = getattr(module, func_name)
    except Exception as exc:  # noqa: BLE001 — plugin code must never break the catalog
        _logger.warning(
            "[plugins:operation] import failed for %s: %s", spec.name, exc, exc_info=True
        )
        return None
    if not callable(func):
        _logger.warning("[plugins:operation] handler %r for %s is not callable", func_name, spec.name)
        return None
    return func


def register_plugin_operations(
    catalog: OperationCatalog,
    declared: list[PluginOperationSpec],
    *,
    plugin_name: str,
    work_root: Path | None = None,
    data_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """把插件 operations 注册进 catalog；返回错误列表（hard_block/导入失败/同名冲突）。

    - hard_block：拒绝注册（与工具 hard_block 同语义，list 报状态）；
    - 动态导入失败：不可用（安装即永信，失败不阻断其他 operation）；
    - 同名冲突：后注册者报错（catalog.register 抛 ValueError，捕获记录）。
    """
    errors: list[dict[str, Any]] = []
    for spec in declared:
        if spec.permission == "hard_block":
            errors.append(
                {
                    "name": spec.name,
                    "error": "operation is hard_blocked by manifest",
                }
            )
            continue
        handler = import_plugin_operation_handler(spec)
        if handler is None:
            errors.append(
                {
                    "name": spec.name,
                    "error": f"handler import failed: {spec.handler!r}",
                }
            )
            continue
        try:
            catalog.register(
                spec.name,
                functools.partial(handler, work_root=work_root, data_dir=data_dir),
            )
        except ValueError as exc:
            errors.append({"name": spec.name, "error": str(exc)})
    return errors
