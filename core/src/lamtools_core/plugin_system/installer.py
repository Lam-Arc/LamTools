"""Install orchestration shared by every operation surface.

user:“本地文件夹、压缩包、链接同一条流程”+下载校验、目录/zip 安装、
更新（保留 data）、依赖报告都在这里；plugin.system.* 与旧名别名只是壳。
"""

from __future__ import annotations

import hashlib
import importlib.util
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from .engine import read_engine
from .host import PluginHost


def download_archive(url: str, expected_sha256: str = "", *, fallback_url: str = "") -> Path:
    """Download one bounded archive through the shared verified transfer path."""
    import os
    from lamtools_core.distribution import download_file
    handle, name = tempfile.mkstemp(prefix="lamtools-plugin-download-", suffix=".zip")
    os.close(handle)
    target = Path(name)
    # user:“插件更新…自动通过网络拓展加速”+(完整传输重试与应用安装包共用实现，失败后不保留半包)。
    download_file(url, target, expected_sha256=expected_sha256, max_bytes=256 * 1024 * 1024,
                  headers={"Accept": "application/octet-stream"}, fallback_urls=(fallback_url,) if fallback_url else ())
    return target


def dependency_report(host: PluginHost, name: str) -> dict[str, Any]:
    """Declared dependencies with an importable probe; missing ones are named."""
    manifest = host.get(name)
    if manifest is None:
        return {"dependencies": [], "missing": 0}
    try:
        dependencies = read_engine(manifest).dependencies
    except Exception:  # noqa: BLE001 — 坏声明按“无依赖”报告，错误另行走 errors
        dependencies = ()
    from .deps import check_dependencies
    checked = check_dependencies(list(dependencies))
    items = [{"name": row.get("raw") or row["name"], "status": "ok" if row.get("ok") else "missing"} for row in checked["items"]]
    return {"dependencies": items, "missing": sum(item["status"] != "ok" for item in items)}


def run_install(host: PluginHost, payload: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    """Install from local / zip / url; returns (ok, payload-or-error)."""
    source = str(payload.get("source") or "local").strip().lower()
    path = str(payload.get("path") or "").strip()
    url = str(payload.get("url") or "").strip()
    sha256 = str(payload.get("sha256") or "").strip()
    downloaded: Path | None = None
    try:
        if source == "url":
            if not url:
                return False, {"error": "url is required"}
            downloaded = download_archive(url, sha256)
            installed = host.install_from_zip(downloaded)
        elif source == "zip":
            if not path:
                return False, {"error": "path is required"}
            installed = host.install_from_zip(path)
        elif source == "local":
            if not path:
                return False, {"error": "path is required"}
            installed = host.install_from_directory(path)
        else:
            return False, {"error": "source must be local, zip or url"}
    except (OSError, ValueError) as exc:
        return False, {"error": str(exc)}
    finally:
        if downloaded is not None:
            downloaded.unlink(missing_ok=True)
    report = dependency_report(host, installed.name)
    return True, {
        "installed": True,
        "name": installed.name,
        "root": str(installed),
        "dependencies": report["dependencies"],
        "missing_dependencies": report["missing"],
    }


def run_update(host: PluginHost, payload: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    """Update from a local directory or zip archive, keeping ``data/``."""
    source = str(payload.get("source") or "local").strip().lower()
    path = str(payload.get("path") or "").strip()
    url = str(payload.get("url") or "").strip()
    sha256 = str(payload.get("sha256") or "").strip()
    downloaded: Path | None = None
    try:
        if source == "url":
            if not url:
                return False, {"error": "url is required"}
            downloaded = download_archive(url, sha256)
            updated = host.update_from_zip(downloaded)
        elif source == "zip":
            if not path:
                return False, {"error": "path is required"}
            updated = host.update_from_zip(path)
        elif source == "local":
            if not path:
                return False, {"error": "path is required"}
            updated = host.update_from_directory(path)
        else:
            return False, {"error": "source must be local, zip or url"}
    except (OSError, ValueError) as exc:
        return False, {"error": str(exc)}
    finally:
        if downloaded is not None:
            downloaded.unlink(missing_ok=True)
    report = dependency_report(host, updated.name)
    return True, {
        "updated": True,
        "name": updated.name,
        "root": str(updated),
        "dependencies": report["dependencies"],
        "missing_dependencies": report["missing"],
    }


__all__ = ["dependency_report", "download_archive", "run_install", "run_update"]
