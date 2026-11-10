"""交互层的瞬时资源：表情包图片的落盘、按名读取与过期清理。

user:“还有一些瞬时的东西，它有受控时长。比如说这个表情包标记的是 3 秒，
我传的参数就是 3 秒，那我这个东西发出去 3 秒钟之后，它就自动淡出消失了”+
(图片不放进轮询状态里，状态只存文件名，避免每次全量快照都带一份 base64。)

图片落盘到系统临时目录下的独立子目录，文件名由服务端生成，路由只按文件名
读取，不接受任何路径片段。
"""

from __future__ import annotations

import re
import tempfile
import time
import uuid
from pathlib import Path

# 只收常见位图，SVG 不收：SVG 可以内嵌脚本，表情包不需要它。
ALLOWED_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
MAX_IMAGE_BYTES = 3 * 1024 * 1024
# 资源保留时间不能短于标记的最长寿命，否则长 ttl 的图片标记会裂图。
# 过期在下次写入时顺手清掉。
ASSET_TTL_SECONDS = 90_000
_NAME_PATTERN = re.compile(r"^[a-z0-9]{8,40}\.(png|jpg|jpeg|webp|gif|bmp)$")


def asset_dir() -> Path:
    directory = Path(tempfile.gettempdir()) / "sunday-overlay-assets"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _prune(directory: Path) -> None:
    cutoff = time.time() - ASSET_TTL_SECONDS
    try:
        entries = list(directory.iterdir())
    except OSError:
        return
    for entry in entries:
        try:
            if entry.is_file() and entry.stat().st_mtime < cutoff:
                entry.unlink()
        except OSError:
            continue


def save_image(source: Path) -> dict[str, str]:
    """把一张已校验过的图片复制进资源目录，返回 {asset, suffix}。"""
    suffix = source.suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise ValueError(f"不支持的图片格式 {suffix!r}")
    size = source.stat().st_size
    if size > MAX_IMAGE_BYTES:
        raise ValueError(f"图片最大 {MAX_IMAGE_BYTES // 1024 // 1024} MB，收到 {size} 字节")

    directory = asset_dir()
    _prune(directory)
    name = f"{uuid.uuid4().hex}{suffix}"
    target = directory / name
    target.write_bytes(source.read_bytes())
    return {"asset": name}


def path_for(name: str) -> Path | None:
    """按资源名取文件；名字不合法或文件不存在都返回 None。"""
    if not _NAME_PATTERN.fullmatch(name):
        return None
    path = asset_dir() / name
    if not path.is_file():
        return None
    return path
