"""The behavior table: which module owns which replaceable behavior.

user:“行为表随版本发布”+后端条目用包反射算出来，前端条目来自构建产物
的基础映射；每个条目要么标“可替换模块”，要么标“内核”。内核四样不可
替换：插件加载器、模块清单本身、安全模式入口、日志。
"""

from __future__ import annotations

import pkgutil
from pathlib import Path
from typing import Any

import lamtools_core

#: 内核（不可替换）：加载器与清单、账本、安全模式、日志。
from lamtools_boot.contract import KERNEL_BACKEND, KERNEL_FRONTEND_PREFIXES


CORE_PACKAGE = "lamtools_core"


def backend_modules() -> list[dict[str, Any]]:
    """Reflect ``lamtools_core`` into module entries (name + ownership)."""
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for module_info in pkgutil.walk_packages(lamtools_core.__path__, prefix=f"{CORE_PACKAGE}."):
        name = module_info.name
        if name in seen:
            continue
        seen.add(name)
        entries.append(
            {
                "module": name,
                "layer": "backend",
                "replaceable": name not in KERNEL_BACKEND,
                "ownership": "kernel" if name in KERNEL_BACKEND else "module",
            }
        )
    return sorted(entries, key=lambda item: item["module"])


def frontend_modules(frontend_dir: Path | str | None) -> list[dict[str, Any]]:
    """Frontend entries come from the build's base import map."""
    from .import_map import load_base_map

    base = load_base_map(frontend_dir)
    entries: list[dict[str, Any]] = []
    for module in sorted(base):
        kernel = any(module.startswith(prefix) for prefix in KERNEL_FRONTEND_PREFIXES)
        entries.append(
            {
                "module": module,
                "layer": "frontend",
                "replaceable": not kernel,
                "ownership": "kernel" if kernel else "module",
            }
        )
    return entries


def build_behavior_table(frontend_dir: Path | str | None = None) -> dict[str, Any]:
    backend = backend_modules()
    frontend = frontend_modules(frontend_dir)
    return {
        "backend": backend,
        "frontend": frontend,
        "counts": {
            "backend": len(backend),
            "frontend": len(frontend),
            "kernel_backend": sum(1 for item in backend if item["ownership"] == "kernel"),
            "kernel_frontend": sum(1 for item in frontend if item["ownership"] == "kernel"),
        },
    }


def query_behavior_table(table: dict[str, Any], term: str) -> list[dict[str, Any]]:
    """Case-insensitive module search for the plugin page."""
    needle = term.strip().lower()
    if not needle:
        return []
    return [
        item
        for item in [*table.get("backend", []), *table.get("frontend", [])]
        if needle in item["module"].lower()
    ]


__all__ = [
    "KERNEL_BACKEND",
    "backend_modules",
    "build_behavior_table",
    "frontend_modules",
    "query_behavior_table",
]
