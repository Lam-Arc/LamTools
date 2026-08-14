"""插件 Python 依赖管理（§5 共识）。

- 安装目标 = core 运行环境（同一 interpreter，§1 硬约束）——
  一律用 ``sys.executable -m pip``，绝不用 PATH 上的 pip（可能指向
  别的 Python，破坏"同一 interpreter"前提）。
- 冲突保护（B3 共识）：安装前 ``pip install --dry-run`` 预演解析，
  任何对已装包的 upgrade/downgrade 都被视为与现有环境冲突而拒装
  （core 依赖已装，覆盖会被拦；纯新增 "Would install" 放行）。
- 卸载按安装清单回滚，多插件共用依赖不卸（检查其他插件清单）。
"""
from __future__ import annotations

import importlib.metadata
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lamtools_core.tool.command import run_subprocess

PIP_INSTALL_TIMEOUT = 600
PIP_DRYRUN_TIMEOUT = 120

_REQUIREMENT_RE = re.compile(
    r"^\s*([A-Za-z0-9_.-]+)"  # 包名
    r"(?:\s*(>=|<=|==|!=|~=|>|<)\s*([0-9][A-Za-z0-9._-]*))?\s*$"
)

# pip --dry-run 输出中表示"将覆盖已装包"的关键行
_RE_DRYRUN_UPGRADE = re.compile(r"Would (install|upgrade|downgrade|uninstall)\s+([A-Za-z0-9_.-]+)")


@dataclass(frozen=True)
class Requirement:
    name: str
    operator: str = ""
    version: str = ""
    raw: str = ""

    def requirement_string(self) -> str:
        if self.operator and self.version:
            return f"{self.name}{self.operator}{self.version}"
        return self.name


def parse_requirement(raw: str) -> Requirement | None:
    match = _REQUIREMENT_RE.match(str(raw or "").strip())
    if match is None:
        return None
    return Requirement(
        name=match.group(1),
        operator=match.group(2) or "",
        version=match.group(3) or "",
        raw=str(raw or "").strip(),
    )


def _version_tuple(version: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", version or "")
    return tuple(int(item) for item in parts)


def _satisfies(installed: str, req: Requirement) -> bool:
    if not req.operator:
        return True
    cur = _version_tuple(installed)
    want = _version_tuple(req.version)
    if req.operator in (">=", ">"):
        return (cur > want) if req.operator == ">" else (cur >= want)
    if req.operator in ("<=", "<"):
        return (cur < want) if req.operator == "<" else (cur <= want)
    if req.operator == "==":
        return cur == want
    if req.operator == "!=":
        return cur != want
    if req.operator == "~=":
        return cur[: len(want)] == want  # 前段兼容（近似语义，够用）
    return True


def check_dependencies(dependencies: list[str]) -> dict[str, Any]:
    """探测依赖状态：已装 / 缺失 / 版本不符。

    Returns:
        {"status": "ok"|"missing"|"version_mismatch",
         "items": [{raw, name, installed, required, ok}...],
         "missing": [requirement 字符串...]}
    """
    items: list[dict[str, Any]] = []
    missing: list[str] = []
    status = "ok"
    for raw in dependencies:
        req = parse_requirement(raw)
        if req is None:
            items.append({"raw": str(raw), "name": str(raw), "ok": False, "error": "invalid requirement"})
            missing.append(str(raw))
            status = "missing" if status == "ok" else status
            continue
        installed = ""
        try:
            installed = importlib.metadata.version(req.name)
        except importlib.metadata.PackageNotFoundError:
            installed = ""
        ok = bool(installed) and _satisfies(installed, req)
        items.append(
            {
                "raw": req.raw or req.requirement_string(),
                "name": req.name,
                "installed": installed,
                "required": req.requirement_string(),
                "ok": ok,
            }
        )
        if not ok:
            if not installed:
                status = "missing" if status != "version_mismatch" else status
                missing.append(req.requirement_string())
            else:
                status = "version_mismatch"
                missing.append(req.requirement_string())
    return {"status": status, "items": items, "missing": missing}


def install_command_hint(dependencies: list[str]) -> str:
    """给用户的安装命令提示（依赖缺失时附在错误信息里）。"""
    quoted = " ".join(dependencies)
    return f"{sys.executable} -m pip install {quoted}"


async def dry_run_install(dependencies: list[str], *, cwd: Path) -> tuple[bool, list[str], str]:
    """预演解析依赖安装：True = 可安全安装；False = 与现有包冲突。

    Returns:
        (ok, conflicts, detail) — conflicts 为将被覆盖的包名列表。
    """
    args = [sys.executable, "-m", "pip", "install", "--dry-run", "--quiet", *dependencies]
    execution = await run_subprocess(args, cwd=cwd, timeout=PIP_DRYRUN_TIMEOUT)
    if execution.exit_code != 0:
        return False, [], (execution.stderr or execution.stdout or "pip dry-run failed")
    conflicts: list[str] = []
    for line in (execution.stdout or "").splitlines():
        match = _RE_DRYRUN_UPGRADE.search(line)
        if match and match.group(1) in ("upgrade", "downgrade", "uninstall"):
            conflicts.append(match.group(2))
    return (not conflicts), conflicts, (execution.stdout or "")


async def install_dependencies(dependencies: list[str], *, cwd: Path) -> tuple[bool, str]:
    """安装依赖到 core 运行环境。失败返回 (False, 错误摘要)。"""
    args = [sys.executable, "-m", "pip", "install", *dependencies]
    execution = await run_subprocess(args, cwd=cwd, timeout=PIP_INSTALL_TIMEOUT)
    if execution.exit_code != 0:
        detail = (execution.stderr or execution.stdout or "").strip()
        return False, detail or "pip install failed"
    return True, (execution.stdout or "").strip()


async def uninstall_dependencies(packages: list[str], *, cwd: Path) -> tuple[bool, str]:
    if not packages:
        return True, ""
    args = [sys.executable, "-m", "pip", "uninstall", "-y", *packages]
    execution = await run_subprocess(args, cwd=cwd, timeout=PIP_INSTALL_TIMEOUT)
    if execution.exit_code != 0:
        return False, (execution.stderr or execution.stdout or "pip uninstall failed").strip()
    return True, (execution.stdout or "").strip()
