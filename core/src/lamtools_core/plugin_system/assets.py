"""Resolve a plugin asset path for the same-origin asset route.

user:“样式注入主界面”+插件目录里的 CSS 和图片要能以 URL 加载，但不能越出
插件根，也不能从一个已禁用的插件里取文件。
"""

from __future__ import annotations

from pathlib import Path

from .host import PluginHost

MEDIA_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
}


def resolve_plugin_asset(
    host: PluginHost,
    plugin_name: str,
    asset_path: str,
) -> Path | None:
    """Return the file to serve, or ``None`` when the request must 404.

    The plugin must be installed and enabled in the new ledger; the resolved
    path must stay inside that plugin's root.
    """
    plugin = host.get(plugin_name)
    if plugin is None or not plugin.enabled:
        return None
    root = plugin.root.resolve()
    target = (root / asset_path).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        return None
    return target


def media_type_for(path: Path) -> str:
    return MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")


__all__ = ["MEDIA_TYPES", "media_type_for", "resolve_plugin_asset"]
