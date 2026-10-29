"""user:“安装版的样式变成了纯文字”+(打包后的主界面必须允许插件从本地后台加载 CSS)。

The packaged WebView document is served from ``tauri://localhost`` while
plugin stylesheets live on the loopback Core origin. Tauri also injects a
per-document nonce into ``style-src``, which makes ``'unsafe-inline'``
inactive, so without an explicit loopback host source the stylesheet link is
refused and plugin pages render as unstyled text. Development mode loads the
Vite server without that CSP, which is why the bug only shows in the installer.
"""

from __future__ import annotations

import json
from pathlib import Path


CONFIG = Path(__file__).resolve().parents[1] / "desktop" / "src-tauri" / "tauri.conf.json"


def _directive(csp: str, name: str) -> list[str]:
    for rule in csp.split(";"):
        parts = rule.split()
        if parts and parts[0] == name:
            return parts[1:]
    raise AssertionError(f"{name} is missing from the desktop CSP")


def test_packaged_app_allows_plugin_stylesheets_from_the_loopback_backend() -> None:
    csp = json.loads(CONFIG.read_text(encoding="utf-8"))["app"]["security"]["csp"]
    style_sources = _directive(csp, "style-src")

    assert "http://127.0.0.1:*" in style_sources
    assert "http://localhost:*" in style_sources


def test_loopback_style_access_keeps_inline_script_protection() -> None:
    csp = json.loads(CONFIG.read_text(encoding="utf-8"))["app"]["security"]["csp"]
    script_sources = _directive(csp, "script-src")

    assert "unsafe-inline" not in script_sources
