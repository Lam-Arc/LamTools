#!/usr/bin/env python3
"""Publish the built Android APK to the fixed GitHub Release location.

Why this is not a CI job: an installable APK carries the embedded runtime (proot plus a
rootfs tarball), and that asset never enters the repository. `android-apk.yml` proves a
clean checkout can build; the package a phone actually installs is built locally and
uploaded from here.

Usage:
    python scripts/publish-android.py
    python scripts/publish-android.py --apk path/to/other.apk --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_APK = ROOT / "artifacts/android/sunday-m-arm64-debug.apk"
TAG = "android-latest"
ASSET_NAME = "Sunday-mobile-arm64.apk"
MIN_BYTES = 100 * 1024 * 1024


def die(message: str) -> None:
    print(f"publish-android: {message}", file=sys.stderr)
    raise SystemExit(1)


def check_apk(apk: Path) -> None:
    """Refuse to publish a package that would fail on first launch."""
    if not apk.is_file():
        die(f"找不到 APK：{apk}")
    size = apk.stat().st_size
    if size < MIN_BYTES:
        die(f"APK 只有 {size / 1024 / 1024:.0f} MB，应该没有内置运行时，装上会报 cannot start proot")
    with zipfile.ZipFile(apk) as archive:
        names = archive.namelist()
    if not any(name.startswith("lib/arm64-v8a/libproot.so") for name in names):
        die("APK 里没有 lib/arm64-v8a/libproot.so")
    if not any(name.startswith("assets/runtime/rootfs") for name in names):
        die("APK 里没有 assets/runtime/rootfs-*")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def gh(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["gh", *arguments], cwd=ROOT, capture_output=True, text=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", type=Path, default=DEFAULT_APK)
    parser.add_argument("--tag", default=TAG)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    apk = args.apk.resolve()
    check_apk(apk)
    digest = sha256(apk)
    size_mb = apk.stat().st_size / 1024 / 1024
    print(f"APK      {apk.name}  {size_mb:.0f} MB")
    print(f"SHA-256  {digest}")
    if args.dry_run:
        print("dry run: 没有上传")
        return

    listed = gh("release", "view", args.tag, "--json", "assets", "-q", ".assets[].name")
    if listed.returncode != 0:
        created = gh(
            "release",
            "create",
            args.tag,
            "--latest=false",
            "--title",
            "Sunday Mobile 安卓版（持续更新）",
            "--notes",
            "安卓客户端安装包，固定链接随每次构建覆盖更新。",
        )
        if created.returncode != 0:
            die(f"创建 Release 失败：{created.stderr.strip()}")

    with tempfile.TemporaryDirectory() as temporary:
        # 资产名必须是固定的：官网链接和二维码都指向它。
        staged = Path(temporary) / ASSET_NAME
        shutil.copy2(apk, staged)
        uploaded = gh("release", "upload", args.tag, str(staged), "--clobber")
        if uploaded.returncode != 0:
            die(f"上传失败：{uploaded.stderr.strip()}")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    notes = f"""安卓客户端安装包，固定链接随每次构建覆盖更新。

安装：手机扫码或打开本页下载 APK，允许「安装未知来源应用」后安装。debug 签名，覆盖安装需要与上一版签名一致。

- 构建时间：{now}
- 大小：{size_mb:.0f} MB
- SHA-256：{digest}

下载链接：
https://github.com/Lam-Arc/LamTools/releases/download/{args.tag}/{ASSET_NAME}"""
    edited = gh("release", "edit", args.tag, "--notes", notes)
    if edited.returncode != 0:
        print(f"publish-android: 更新说明失败：{edited.stderr.strip()}", file=sys.stderr)

    print(f"已发布 https://github.com/Lam-Arc/LamTools/releases/download/{args.tag}/{ASSET_NAME}")


if __name__ == "__main__":
    main()
