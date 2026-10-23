"""Engine declarations and the minimal compatibility check.

user:“插件声明自己要什么环境”+宿主公布 Python、应用版本和平台；插件写版本
约束，安装时比对，不满足就拒绝并说清是哪一条。
"""

from __future__ import annotations

import platform
import re
import sys
from dataclasses import dataclass
from typing import Any, Mapping

from .capabilities import CapabilityError
from .manifest import PluginManifest

VALID_RUNTIMES = ("python", "webview", "native")

_CONSTRAINT = re.compile(r"(>=|<=|==|!=|>|<)\s*([0-9][0-9A-Za-z.\-+]*)")


@dataclass(frozen=True)
class PluginEngine:
    runtime: str = "python"
    python: str = ""
    app: str = ""
    platform: str = ""
    dependencies: tuple[str, ...] = ()


def _version_tuple(value: str) -> tuple[int, ...]:
    parts = [int(item) for item in re.findall(r"\d+", str(value))]
    return tuple(parts) or (0,)


def _compare(left: str, right: str) -> int:
    a = _version_tuple(left)
    b = _version_tuple(right)
    size = max(len(a), len(b))
    a = a + (0,) * (size - len(a))
    b = b + (0,) * (size - len(b))
    return (a > b) - (a < b)


def satisfies(version: str, constraint: str) -> bool:
    """Check ``version`` against a comma-separated list of simple constraints."""
    text = str(constraint or "").strip()
    if not text:
        return True
    for token in text.split(","):
        token = token.strip()
        if not token:
            continue
        match = _CONSTRAINT.fullmatch(token)
        if match is None:
            return False
        operator, target = match.group(1), match.group(2)
        comparison = _compare(version, target)
        if operator == ">=" and comparison < 0:
            return False
        if operator == ">" and comparison <= 0:
            return False
        if operator == "<=" and comparison > 0:
            return False
        if operator == "<" and comparison >= 0:
            return False
        if operator == "==" and comparison != 0:
            return False
        if operator == "!=" and comparison == 0:
            return False
    return True


def host_platform() -> str:
    machine = platform.machine().lower()
    if machine in {"x86_64", "amd64"}:
        arch = "x64"
    elif machine in {"arm64", "aarch64"}:
        arch = "arm64"
    else:
        arch = machine or "unknown"
    if sys.platform.startswith("win"):
        return f"windows-{arch}"
    if sys.platform == "darwin":
        return f"macos-{arch}"
    return f"linux-{arch}"


def host_engine_info() -> dict[str, str]:
    from lamtools_core import __version__

    return {
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "app": str(__version__),
        "platform": host_platform(),
    }


def read_engine(manifest: PluginManifest) -> PluginEngine:
    raw = manifest.raw.get("engine")
    if raw is None:
        return PluginEngine()
    if not isinstance(raw, dict):
        raise CapabilityError(manifest.name, "engine must be an object")
    runtime = str(raw.get("runtime") or "python").strip().lower()
    if runtime not in VALID_RUNTIMES:
        raise CapabilityError(
            manifest.name,
            f"engine runtime must be one of {', '.join(VALID_RUNTIMES)}: {runtime}",
        )
    dependencies_raw = raw.get("dependencies")
    dependencies = (
        tuple(
            str(item).strip()
            for item in dependencies_raw
            if isinstance(item, str) and str(item).strip()
        )
        if isinstance(dependencies_raw, list)
        else ()
    )
    return PluginEngine(
        runtime=runtime,
        python=str(raw.get("python") or "").strip(),
        app=str(raw.get("app") or "").strip(),
        platform=str(raw.get("platform") or "").strip(),
        dependencies=dependencies,
    )


def check_engine(
    engine: PluginEngine,
    *,
    host: Mapping[str, str] | None = None,
) -> list[str]:
    """Return one human-readable problem per unmet engine requirement."""
    info = dict(host_engine_info() if host is None else host)
    problems: list[str] = []
    if engine.python and not satisfies(info.get("python", "0"), engine.python):
        problems.append(
            f"requires python {engine.python}, host has {info.get('python', 'unknown')}"
        )
    if engine.app and not satisfies(info.get("app", "0"), engine.app):
        problems.append(
            f"requires app {engine.app}, host has {info.get('app', 'unknown')}"
        )
    if engine.platform and engine.platform != info.get("platform"):
        problems.append(
            f"requires platform {engine.platform}, host is {info.get('platform', 'unknown')}"
        )
    return problems


__all__ = [
    "VALID_RUNTIMES",
    "PluginEngine",
    "check_engine",
    "host_engine_info",
    "host_platform",
    "read_engine",
    "satisfies",
]
