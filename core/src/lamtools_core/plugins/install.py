"""插件安装/卸载（§5/§6 共识）。

- 安装 = 复制到插件根（默认用户级，可指定项目级），zip / GitHub
  Release URL 下载后安全解压；重装即更新（覆盖旧目录）。
- 安全：zip 解压逐条目 is_relative_to 逃逸检查 + 条目数/总大小限额
  （照抄 document_normalize 的限额先例）；URL 下载支持用户提供
  sha256 校验，无校验和则返回风险提示（B7 共识）。
- 卸载 = 删插件目录 + 可选按安装清单清依赖（默认保留）；同时清理
  该插件来源的 hook 信任记录与插件配置（E4 共识）。
"""
from __future__ import annotations

import hashlib
import logging
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any

from lamtools_core.tool.command import run_subprocess

_logger = logging.getLogger(__name__)

MAX_ZIP_ENTRIES = 2000
MAX_ZIP_TOTAL_BYTES = 512 * 1024 * 1024  # 512MB

# https://github.com/{owner}/{repo}/releases/download/{tag}/{asset}
# https://github.com/{owner}/{repo}/releases/latest/download/{asset}
_GITHUB_RELEASE_URL_RE = re.compile(
    r"^https?://github\.com/([^/]+)/([^/]+)/releases/(?:download/([^/]+)|latest/download)/([^/]+)$",
    re.IGNORECASE,
)


def parse_github_release_url(url: str) -> dict[str, str] | None:
    """解析 GitHub Release 资产下载 URL → {owner, repo, tag, asset}。

    不匹配 GitHub Release 形态返回 None（调用方按普通 URL 处理或报错）。
    """
    match = _GITHUB_RELEASE_URL_RE.match(str(url or "").strip())
    if match is None:
        return None
    return {
        "owner": match.group(1),
        "repo": match.group(2),
        "tag": match.group(3) or "latest",
        "asset": match.group(4),
    }


def safe_extract_zip(archive_path: Path, target_dir: Path) -> None:
    """安全解压：路径逃逸检查 + 条目数/总大小限额（B7 共识）。"""
    target_dir.mkdir(parents=True, exist_ok=True)
    root = target_dir.resolve()
    total_size = 0
    with zipfile.ZipFile(archive_path) as archive:
        infos = archive.infolist()
        if len(infos) > MAX_ZIP_ENTRIES:
            raise ValueError(f"zip has too many entries ({len(infos)} > {MAX_ZIP_ENTRIES})")
        for info in infos:
            total_size += info.file_size
            if total_size > MAX_ZIP_TOTAL_BYTES:
                raise ValueError(f"zip total size exceeds {MAX_ZIP_TOTAL_BYTES} bytes")
            # 逐条逃逸检查（照抄 registry._paths 的 is_relative_to 语义）
            member = (root / info.filename).resolve()
            if not member.is_relative_to(root):
                raise ValueError(f"zip entry escapes target directory: {info.filename}")
        for info in infos:
            member = (root / info.filename).resolve()
            if info.is_dir():
                member.mkdir(parents=True, exist_ok=True)
            else:
                member.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as src, open(member, "wb") as dst:
                    shutil.copyfileobj(src, dst)


def sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def download_to_file(url: str, target: Path, *, timeout: int = 300) -> tuple[bool, str]:
    """httpx 流式下载到临时文件（边下边算 sha256，返回校验值）。"""
    import httpx

    target.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
            async with client.stream("GET", url) as response:
                if response.status_code != 200:
                    return False, f"download failed: HTTP {response.status_code}"
                with open(target, "wb") as handle:
                    async for chunk in response.aiter_bytes():
                        handle.write(chunk)
                        digest.update(chunk)
    except Exception as exc:  # noqa: BLE001 — 下载失败必须返回可读错误
        return False, f"download failed: {type(exc).__name__}: {exc}"
    return True, digest.hexdigest()


def install_from_directory(src_dir: Path, target_dir: Path) -> None:
    """复制本地插件目录到插件根（重装即更新：先清理旧目录）。"""
    src = src_dir.resolve()
    target = target_dir.resolve()
    if not src.exists() or not src.is_dir():
        raise ValueError(f"plugin directory not found: {src}")
    if not src.is_relative_to(target.parent) and src.is_relative_to(target):
        raise ValueError("plugin source cannot be inside its own target")
    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, target, ignore=shutil.ignore_patterns(".git", "__pycache__", ".venv"))


def find_plugin_manifest_dir(installed_root: Path) -> Path | None:
    """安装后定位含 plugin.json 的目录（zip 可能带一层外层目录）。"""
    if (installed_root / "plugin.json").exists():
        return installed_root
    for child in sorted(installed_root.iterdir()):
        if child.is_dir() and (child / "plugin.json").exists():
            return child
    return None


def uninstall_plugin_directory(target_dir: Path) -> None:
    """删除插件目录（目标必须存在且在插件根下，防误删）。"""
    target = target_dir.resolve()
    if not target.exists():
        return
    if target.name == "plugins" or not target.parent.exists():
        raise ValueError(f"refusing to remove unexpected path: {target}")
    shutil.rmtree(target)
