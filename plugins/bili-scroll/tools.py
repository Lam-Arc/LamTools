# user:“对比原版，能力应当只增不减”+(保留完整移植能力，并使用宿主独立模块空间)。
"""bili-scroll —— 模型侧工具（宿主自己的那层能力）。

⚠️ 这里**没有** bili_search / bili_subtitle / bili_comments / bili_reply / bili_cover / bili_frames：
那些是随包内置的 **bilibili-mcp 服务器**提供的工具（原版也是 MCP，不是宿主工具）。
本文件只放 MCP 包不住的那层：环境、登录、配置、状态、跑一轮、诊断。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

from lamtools_core.tool import ToolResult  # noqa: E402

from . import service  # noqa: E402


def _result(call, payload: dict, ok: bool | None = None) -> ToolResult:
    if ok is None:
        ok = bool(payload.get("ok", True))
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if ok:
        return ToolResult(call_id=call.id, name=call.name, status="ok", content=text)
    return ToolResult(call_id=call.id, name=call.name, status="failed",
                      error=str(payload.get("error") or text), content=text)


def _args(call) -> dict:
    args = getattr(call, "arguments", None)
    return args if isinstance(args, dict) else {}


async def bili_status(call) -> ToolResult:
    return _result(call, await service.run_io(service.status))


async def bili_config(call) -> ToolResult:
    args = _args(call)
    patch = args.get("patch") if isinstance(args.get("patch"), dict) else None
    if patch:
        return _result(call, await service.run_io(service.config_update,patch))
    return _result(call, await service.run_io(service.config_get))


async def bili_setup(call) -> ToolResult:
    return _result(call, await service.run_io(service.setup_deps))


async def bili_run(call) -> ToolResult:
    why = str(_args(call).get("why") or "manual")
    return _result(call, service.run_round(why))


async def bili_login_start(call) -> ToolResult:
    return _result(call, await service.run_io(service.login_start))


async def bili_login_poll(call) -> ToolResult:
    return _result(call, await service.run_io(service.login_poll,str(_args(call).get("key") or "")))


async def bili_login_cookie(call) -> ToolResult:
    args = _args(call)
    return _result(
        call,
        await service.run_io(service.import_cookie,
            str(args.get("sessdata") or ""),
            str(args.get("bili_jct") or ""),
            str(args.get("dedeuserid") or ""),
            str(args.get("buvid3") or ""),
        ),
    )


async def bili_diagnose(call) -> ToolResult:
    return _result(call, await service.run_io(service.diagnose))
