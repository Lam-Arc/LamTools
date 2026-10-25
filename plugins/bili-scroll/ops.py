"""bili-scroll 的操作处理器（RPC 面）。

user:“命令与面板都走 operation”+值班参数、日报列表、装依赖、跑一轮、
自检从这里出，与斜杠命令共用同一条通道。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import venv as _venv
from datetime import datetime
from pathlib import Path
from typing import Any

from lamtools_core.app import OperationRequest, OperationResult
from lamtools_core.plugin_system.jsonc import load_jsonc_text

_PLUGIN_ROOT = Path(__file__).resolve().parent
_DATA_DIR = _PLUGIN_ROOT / "data"
_OUT_DIR = _DATA_DIR / "out"
_MCP_JSON = _PLUGIN_ROOT / "mcp" / "mcp.json"
_VENV_DIR = _DATA_DIR / "venv"


def _venv_python() -> Path:
    return _VENV_DIR / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _config() -> dict[str, Any]:
    try:
        data = load_jsonc_text(_DATA_DIR / "config.jsonc")
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


async def duty_brief(request: OperationRequest) -> OperationResult:
    # 与 MCP 的 brief 工具共用同一份载荷（单一事实来源）。
    from bili_core import duty_brief_payload

    return OperationResult(name=request.name, payload=duty_brief_payload())


async def reports_list(request: OperationRequest) -> OperationResult:
    reports = []
    if _OUT_DIR.is_dir():
        for path in sorted(_OUT_DIR.glob("*.md"), reverse=True):
            reports.append(
                {
                    "file": path.name,
                    "path": str(path),
                    "bytes": path.stat().st_size,
                }
            )
    return OperationResult(name=request.name, payload={"reports": reports, "count": len(reports)})


async def setup(request: OperationRequest) -> OperationResult:
    """装依赖：建插件自管 venv（httpx + mcp），把解析后的绝对路径写回 mcp.json。

    user:“装主依赖”+原版的引导按钮；本操作跑在宿主进程里，用
    sys.executable 建 venv，服务端依赖装进 venv——与宿主打包无关。
    """
    python_exe = _venv_python()
    if not python_exe.exists():
        _venv.create(str(_VENV_DIR), with_pip=True)
    result = subprocess.run(
        [str(python_exe), "-m", "pip", "install", "--quiet", "httpx", "mcp"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return OperationResult(
            name=request.name,
            status="error",
            payload={"error": f"依赖安装失败：{(result.stdout + result.stderr)[-300:]}"},
        )

    # user:“静态 mcp.json 指不到动态 venv 路径”+setup 把解析后的绝对路径
    # 写回安装副本的 mcp.json；写回前 MCP 起不来（工具暂缺，宿主优雅降级）。
    template = _MCP_JSON.read_text(encoding="utf-8")
    resolved = template.replace("{{BILI_VENV_PYTHON}}", str(python_exe)).replace(
        "{{PLUGIN_DIR}}", str(_PLUGIN_ROOT)
    )
    _MCP_JSON.write_text(resolved, encoding="utf-8")
    return OperationResult(
        name=request.name,
        payload={
            "installed": True,
            "venv": str(_VENV_DIR),
            "mcp_json": str(_MCP_JSON),
            "note": "MCP 服务端将在下一次会话激活时以新路径启动。",
        },
    )


async def selfcheck(request: OperationRequest) -> OperationResult:
    """环境自检：venv、mcp.json、凭证、whisper、ffmpeg 逐项报告。"""
    checks = {
        "venv": _venv_python().exists(),
        "mcp_json_resolved": _MCP_JSON.exists() and "{{" not in _MCP_JSON.read_text(encoding="utf-8"),
        "credentials": bool(_config().get("sessdata")),
        "whisper": shutil.which("whisper") is not None,
        "ffmpeg": shutil.which("ffmpeg") is not None,
    }
    return OperationResult(
        name=request.name,
        payload={"checks": checks, "all_ok": all(checks.values())},
    )


async def run_now(request: OperationRequest, *, context: Any = None) -> OperationResult:
    """现在跑一轮：按运行档 bili-scroll:duty 拉起值班子代理。

    user:“现在跑一轮”+值班轮由 backend 的运行时在后台执行，操作立即返回；
    进度与结果经日报与卡片墙查看。
    """
    service = context.service("bili-scroll.duty") if context is not None else None
    if service is None:
        return OperationResult(
            name=request.name,
            status="error",
            payload={"error": "值班运行时未就绪（backend 未启用或宿主未注入）"},
        )
    return OperationResult(name=request.name, payload={"started": True, **service.trigger_now()})
