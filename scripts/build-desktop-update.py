"""Build ``downloads/desktop-update.json`` for the official site.

The desktop update check reads this manifest first (the official site is the
primary channel; GitHub Releases is the fallback), so it must describe an
installer the site actually serves.  The version comes from the *built*
installer's file name and the working tree must agree with it, so a release
cannot publish a manifest for a different build — the same guard the mobile
release flow applies to its APK.

The script writes two copies:

* ``core/desktop/update-manifest.json`` — the repository copy.
* ``<bundle>/desktop-update.json`` — next to the installer, ready to upload.

Uploading stays with the existing cloud flow: put the installer and this
manifest under the site's ``downloads/`` directory (the manifest's download URL
must match the uploaded file name).

Usage (from the repository root)::

    py -3.14 scripts/build-desktop-update.py
    py -3.14 scripts/build-desktop-update.py --installer <path-to-setup.exe>
    py -3.14 scripts/build-desktop-update.py --notes-file release-notes.md
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DESKTOP = REPO_ROOT / "core" / "desktop"
BUNDLE = DESKTOP / "src-tauri" / "target" / "release" / "bundle"
REPO_MANIFEST = DESKTOP / "update-manifest.json"
TAURI_CONF = DESKTOP / "src-tauri" / "tauri.conf.json"

DEFAULT_BASE_URL = "https://47.114.43.99.nip.io/downloads"
DEFAULT_RELEASE_URL = "https://47.114.43.99.nip.io/#download"

SETUP_NAME = re.compile(
    r"^Sunday_(?P<version>\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?)_x64-setup\.exe$"
)


def _version_of(installer: Path) -> str:
    match = SETUP_NAME.match(installer.name)
    if not match:
        raise SystemExit(f"unexpected installer name: {installer.name}")
    return match.group("version")


def _tree_version() -> str:
    """The version the working tree declares, so the manifest cannot drift."""
    data = json.loads(TAURI_CONF.read_text(encoding="utf-8"))
    return str(data.get("version") or "").strip()


def _newest_installer() -> Path:
    candidates = sorted(
        (BUNDLE / "inno").glob("Sunday_*_x64-setup.exe"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise SystemExit(f"no installer under {BUNDLE / 'inno'}; build one or pass --installer")
    return candidates[0]


def _linux_url(version: str, base_url: str) -> str:
    """Return the AppImage URL for this version, falling back to the deb."""
    for folder, pattern in (("appimage", f"Sunday_{version}_amd64.AppImage"), ("deb", f"Sunday_{version}_amd64.deb")):
        artifact = BUNDLE / folder / pattern
        if artifact.exists():
            return f"{base_url.rstrip('/')}/{artifact.name}"
    return ""


def _resolve_installer(args: argparse.Namespace) -> Path:
    """解析要描述的那个安装包（一次；调用方复用它写同目录副本）。"""
    installer = Path(args.installer).resolve() if args.installer else _newest_installer()
    if not installer.exists():
        raise SystemExit(f"installer not found: {installer}")
    return installer


def build_manifest(args: argparse.Namespace, installer: Path | None = None) -> dict:
    installer = installer or _resolve_installer(args)
    version = _version_of(installer)
    tree = _tree_version()
    if tree != version and not args.allow_version_mismatch:
        raise SystemExit(
            f"installer is {version} but tauri.conf.json says {tree}: rebuild, or pass "
            "--allow-version-mismatch when packaging an older artifact on purpose"
        )
    base = args.base_url.rstrip("/")
    notes = args.notes
    if args.notes_file:
        notes = Path(args.notes_file).read_text(encoding="utf-8").strip()
    manifest = {
        "version": version,
        "download_url": f"{base}/{installer.name}",
        "release_url": args.release_url,
        "release_notes": notes or f"Sunday {version}",
        "published_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    linux = _linux_url(version, base)
    if linux:
        manifest["linux_download_url"] = linux
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installer", default="")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--release-url", default=DEFAULT_RELEASE_URL)
    parser.add_argument("--notes", default="")
    parser.add_argument("--notes-file", default="")
    parser.add_argument(
        "--allow-version-mismatch",
        action="store_true",
        help="package an artifact whose version differs from tauri.conf.json (not for releases)",
    )
    args = parser.parse_args()

    # 只解析一次安装包：仓库副本与上传副本必须描述同一个文件。
    installer = _resolve_installer(args)
    manifest = build_manifest(args, installer)
    payload = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"

    REPO_MANIFEST.write_text(payload, encoding="utf-8", newline="\n")
    deploy_copy = installer.parent / "desktop-update.json"
    deploy_copy.write_text(payload, encoding="utf-8", newline="\n")

    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(f"\nrepository copy : {REPO_MANIFEST}")
    print(f"upload copy     : {deploy_copy}")
    print(f"sha256(16)      : {digest}")
    if "linux_download_url" not in manifest:
        print("note: no Linux artifact for this version — Linux clients fall back to GitHub Releases")
    print(
        "upload both files to the site's downloads/ directory, and keep "
        "website/src/components/Download.vue's version in step"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
