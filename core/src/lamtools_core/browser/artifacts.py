"""截图落盘：浏览器工具与搜索降级共用（不把 base64 塞进模型上下文）。

user:“不必要的 HTML、CSS 和脚本”与“视觉感知作为补充”+(截图只在兜底时落盘，
返回的是路径与尺寸，不是图片数据；模型要看再由 read_page/inspect_page 决定)。
"""

from __future__ import annotations

import base64
import time
from pathlib import Path

PNG_PREFIX = "data:image/png;base64,"


def screenshot_dir(work_root: str | Path) -> Path:
    base = Path(work_root) if str(work_root).strip() else Path.cwd()
    directory = base / ".lam" / "artifacts" / "browser"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def save_png(work_root: str | Path, tab: str, data_url: str) -> Path | None:
    """把 data URL 落盘；不是 PNG data URL 时返回 None（不猜别的格式）。"""
    if not isinstance(data_url, str) or not data_url.startswith(PNG_PREFIX):
        return None
    try:
        raw = base64.b64decode(data_url[len(PNG_PREFIX) :], validate=True)
    except Exception:  # noqa: BLE001 - 坏数据不许拖垮整次工具调用
        return None
    safe_tab = "".join(char for char in str(tab) if char.isalnum()) or "tab"
    target = screenshot_dir(work_root) / f"{safe_tab}-{time.strftime('%Y%m%d-%H%M%S')}.png"
    target.write_bytes(raw)
    return target
