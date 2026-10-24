"""模型可调插件管理工具（F2 共识：skill 引导插件安装的调用通道）。

照抄 durable_tools 骨架（operation 包装为 ToolSpec + handler）：
- ``plugin_install``：ASK_USER（pip 是可执行操作，§5 需审批）——自动
  获得 ApprovalGate → loop 等待门 → approval.respond 全链路；
- ``plugin_deps`` / ``plugin_list``：AUTO_ALLOW 只读。
模型 load plugin-manager skill 后按引导调用，用户确认后完成安装。
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
import json
from pathlib import Path
from typing import Any

from lamtools_core.tool import ToolCall, ToolResult, ToolSpec
from lamtools_core.tool.permission import ASK_USER, AUTO_ALLOW

OperationExecutor = Callable[[str, dict[str, Any], dict[str, Any]], Awaitable[Any]]

PLUGIN_INSTALL_TOOL = "plugin_install"
PLUGIN_DEPS_TOOL = "plugin_deps"
PLUGIN_LIST_TOOL = "plugin_list"


def _args(call: ToolCall) -> dict[str, Any]:
    return dict(call.arguments if isinstance(call.arguments, dict) else {})


def _session_id(call: ToolCall) -> str:
    metadata = call.metadata if isinstance(call.metadata, dict) else {}
    return str(metadata.get("session_id") or metadata.get("thread_id") or "")


def plugin_manager_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            name=PLUGIN_INSTALL_TOOL,
            description=(
                "Install or update a LamTools plugin. Sources: local directory path, "
                "local .zip path, or a GitHub Release asset URL (must be a .zip). "
                "Requires user confirmation — pip may run for dependencies. "
                "Reinstalling an existing plugin name updates it. "
                "Use this only when the user explicitly asks to install or update a plugin."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "enum": ["local", "zip", "url"],
                        "description": "Install source kind",
                    },
                    "path": {
                        "type": "string",
                        "description": "Local plugin directory or .zip path (for local/zip sources)",
                    },
                    "url": {
                        "type": "string",
                        "description": "GitHub Release .zip asset URL (for url source)",
                    },
                    "target": {
                        "type": "string",
                        "enum": ["user", "project"],
                        "description": "Plugin root to install into (default user)",
                    },
                    "sha256": {
                        "type": "string",
                        "description": "Optional expected sha256 of the downloaded asset",
                    },
                    "install_deps": {
                        "type": "boolean",
                        "description": "Install declared pip dependencies (default true)",
                    },
                },
                "required": ["source"],
            },
            permission=ASK_USER,
            metadata={"category": "plugin"},
        ),
        ToolSpec(
            name=PLUGIN_DEPS_TOOL,
            description=(
                "Check a plugin's pip dependency status (installed / missing / version mismatch). "
                "Read-only."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Plugin name"},
                },
                "required": ["name"],
            },
            permission=AUTO_ALLOW,
            metadata={"category": "plugin"},
        ),
        ToolSpec(
            name=PLUGIN_LIST_TOOL,
            description=(
                "List installed plugins (name/version/enabled/dependency status/tools). Read-only."
            ),
            input_schema={
                "type": "object",
                "properties": {},
            },
            permission=AUTO_ALLOW,
            metadata={"category": "plugin"},
        ),
    ]


def plugin_manager_tool_handlers(
    execute_operation: OperationExecutor,
    *,
    work_root: str | Path | None = None,
) -> dict[str, Callable[[ToolCall], Awaitable[ToolResult]]]:
    async def plugin_install(call: ToolCall) -> ToolResult:
        args = _args(call)
        payload: dict[str, Any] = {}
        for key in ("source", "path", "url", "target", "sha256"):
            if args.get(key) not in (None, ""):
                payload[key] = args[key]
        if "install_deps" in args:
            payload["install_deps"] = bool(args["install_deps"])
        outcome = await execute_operation(
            "plugin.install", payload,
            _operation_metadata(call),
        )
        return _from_operation(call, outcome, default_error="plugin install failed")

    async def plugin_deps(call: ToolCall) -> ToolResult:
        args = _args(call)
        outcome = await execute_operation(
            "plugin.deps-status",
            {"name": str(args.get("name") or "").strip()},
            _operation_metadata(call),
        )
        return _from_operation(call, outcome, default_error="plugin dependency check failed")

    async def plugin_list(call: ToolCall) -> ToolResult:
        outcome = await execute_operation("plugin.list", {}, _operation_metadata(call))
        return _from_operation(call, outcome, default_error="plugin list failed")

    return {
        PLUGIN_INSTALL_TOOL: plugin_install,
        PLUGIN_DEPS_TOOL: plugin_deps,
        PLUGIN_LIST_TOOL: plugin_list,
    }


def _operation_metadata(call: ToolCall) -> dict[str, Any]:
    metadata = dict(call.metadata if isinstance(call.metadata, dict) else {})
    metadata["tool_call_id"] = call.id
    return metadata


def _from_operation(
    call: ToolCall,
    outcome: Any,
    *,
    default_error: str,
) -> ToolResult:
    """OperationResult → ToolResult（照抄 durable_tools._from_operation）。"""
    status = getattr(outcome, "status", "error")
    payload = getattr(outcome, "payload", None)
    if status == "ok" and isinstance(payload, dict):
        return ToolResult(
            call_id=call.id,
            name=call.name,
            status="ok",
            content=json.dumps(payload, ensure_ascii=False, sort_keys=True),
            metadata={"operation_payload": payload},
        )
    error = ""
    if isinstance(payload, dict):
        error = str(payload.get("error") or payload.get("detail") or default_error)
    return ToolResult(
        call_id=call.id,
        name=call.name,
        status="failed",
        content=f"{default_error}: {error}",
        error=error or default_error,
        metadata={"operation_error": True},
    )
