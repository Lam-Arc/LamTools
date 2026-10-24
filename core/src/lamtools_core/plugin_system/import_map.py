"""Frontend module overrides: build and inject the page import map.

user:“前端模块替换”+构建产物按模块边界输出一张基础映射（base map），
启用的插件可以用 ``@/...`` 键顶掉其中任意一项；Core 返回页面时把合并结果
作为 import map 注入在任何模块脚本之前。安全模式只给基础映射。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

from .host import PluginHost
from .overrides import FRONTEND_KEY_PREFIX, OverrideAssembly, assemble_overrides

SAFE_MODE_ENV = "LAMTOOLS_SAFE_MODE"

#: 进程级登记：宿主应用启动时告知前端产物目录（base map / 行为表用）。
_FRONTEND_DIR: Path | None = None


def set_frontend_dir(frontend_dir: Path | str | None) -> None:
    global _FRONTEND_DIR
    _FRONTEND_DIR = Path(frontend_dir).resolve() if frontend_dir else None


def frontend_dir() -> Path | None:
    return _FRONTEND_DIR
_TRUE_VALUES = {"1", "true", "yes", "on"}
BASE_MAP_FILENAME = "importmap.base.json"


def _safe_mode() -> bool:
    return str(os.environ.get(SAFE_MODE_ENV) or "").strip().lower() in _TRUE_VALUES


def asset_url(plugin: str, root: Path | None, path: Path | None) -> str:
    if root is None or path is None:
        return ""
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError:
        return ""
    return (
        f"/api/core/plugin-system/{quote(plugin, safe='')}"
        f"/assets/{quote(relative, safe='/')}"
    )


def load_base_map(frontend_dir: Path | str | None) -> dict[str, str]:
    """The build emits ``importmap.base.json`` beside ``index.html``; absent
    means the bundle is not module-mapped yet and only plugin entries apply."""
    if frontend_dir is None:
        return {}
    base_path = Path(frontend_dir).resolve() / BASE_MAP_FILENAME
    if not base_path.is_file():
        return {}
    try:
        data = json.loads(base_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    imports = data.get("imports") if isinstance(data, dict) else None
    return dict(imports) if isinstance(imports, dict) else {}


def build_import_map(
    host: PluginHost | None,
    *,
    frontend_dir: Path | str | None = None,
    safe_mode: bool | None = None,
    assembly: OverrideAssembly | None = None,
) -> dict[str, str]:
    """Base map plus enabled plugins' frontend overrides (plugins win)."""
    imports = load_base_map(frontend_dir)
    if safe_mode is None:
        safe_mode = _safe_mode()
    if safe_mode or host is None:
        return imports
    resolved = assembly if assembly is not None else assemble_overrides(host.discover())
    for spec in resolved.frontend_overrides().values():
        url = asset_url(spec.plugin, spec.root, spec.path)
        if url:
            imports[spec.target] = url
    return imports


def inject_import_map(html: str, imports: dict[str, str]) -> str:
    """Insert the import map tag before the first module script.

    Import maps must appear before any module loads; when the page has no
    script tag the map is placed before ``</head>``.
    """
    if not imports:
        return html
    payload = json.dumps({"imports": imports}, ensure_ascii=False)
    tag = f'<script type="importmap">{payload}</script>'
    lowered = html.lower()
    script_at = lowered.find("<script")
    if script_at != -1:
        return html[:script_at] + tag + html[script_at:]
    head_at = lowered.find("</head>")
    if head_at != -1:
        return html[:head_at] + tag + html[head_at:]
    return tag + html


def import_map_provider_from_state(
    app_state: dict[str, Any],
    frontend_dir: Path | str | None,
) -> Callable[[], dict[str, str]]:
    """Lazy provider: the plugin host lands in app state after agent boot."""

    def provide() -> dict[str, str]:
        host = app_state.get("plugin_system_host")
        return build_import_map(
            host if isinstance(host, PluginHost) else None,
            frontend_dir=frontend_dir,
        )

    return provide


__all__ = [
    "BASE_MAP_FILENAME",
    "frontend_dir",
    "set_frontend_dir",
    "FRONTEND_KEY_PREFIX",
    "SAFE_MODE_ENV",
    "asset_url",
    "build_import_map",
    "import_map_provider_from_state",
    "inject_import_map",
    "load_base_map",
]
