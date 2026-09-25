"""Verify the mobile version is in step in every place that carries it.

The mobile release flow documents eight places; nothing guarded them until
2026-09-25 (`bump-version.ps1` only covers the desktop's five, and the release
workflow never looks at the mobile app). A drifted version ships an APK whose
update check compares against a version nobody published.

Usage (repository root)::

    py -3.14 scripts/verify-mobile-version.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MOBILE = REPO_ROOT / "core" / "mobile"
WEBSITE_DOWNLOAD = REPO_ROOT / "website" / "src" / "components" / "Download.vue"


def _version_code(version: str) -> int:
    """Android versionCode = major*1000000 + minor*1000 + patch."""
    core = version.split("-", 1)[0].split("+", 1)[0]
    parts = [int(part) for part in core.split(".")[:3]]
    while len(parts) < 3:
        parts.append(0)
    major, minor, patch = parts
    return major * 1000000 + minor * 1000 + patch


def _cargo_lock_version() -> str:
    """Version of the ``sunday-mobile`` package in Cargo.lock ('' when absent)."""
    lock = MOBILE / "src-tauri" / "Cargo.lock"
    if not lock.exists():
        return ""
    block = re.search(
        r'\[\[package\]\]\nname = "sunday-mobile"\nversion = "([^"]+)"',
        lock.read_text(encoding="utf-8"),
    )
    return block.group(1) if block else ""


def check() -> list[str]:
    """Return a list of problems (empty when every place agrees)."""
    problems: list[str] = []
    package = json.loads((MOBILE / "package.json").read_text(encoding="utf-8"))["version"]
    tauri = json.loads((MOBILE / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))["version"]
    cargo_text = (MOBILE / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8")
    cargo_match = re.search(r'^version\s*=\s*"([^"]+)"', cargo_text, re.M)
    cargo = cargo_match.group(1) if cargo_match else ""
    manifest = json.loads((MOBILE / "update-manifest.json").read_text(encoding="utf-8"))["version"]
    properties = (MOBILE / "src-tauri" / "gen" / "android" / "app" / "tauri.properties").read_text(encoding="utf-8")
    gradle = (MOBILE / "src-tauri" / "gen" / "android" / "app" / "build.gradle.kts").read_text(encoding="utf-8")

    for label, value in (
        ("package.json", package),
        ("src-tauri/tauri.conf.json", tauri),
        ("src-tauri/Cargo.toml", cargo),
        ("update-manifest.json", manifest),
    ):
        if value != package:
            problems.append(f"{label} is {value!r}, expected {package!r}")

    if _cargo_lock_version() not in {"", package}:
        problems.append(
            f"src-tauri/Cargo.lock (sunday-mobile) is {_cargo_lock_version()!r}, expected {package!r}"
        )

    expected_code = _version_code(package)
    if f"versionCode={expected_code}" not in properties:
        problems.append(f"gen/android/app/tauri.properties lacks versionCode={expected_code}")
    if f"versionName={package}" not in properties:
        problems.append(f"gen/android/app/tauri.properties lacks versionName={package}")
    if f'"{expected_code}"' not in gradle:
        problems.append(f"gen/android/app/build.gradle.kts default lacks versionCode {expected_code}")
    if f'"{package}"' not in gradle:
        problems.append(f"gen/android/app/build.gradle.kts default lacks versionName {package}")

    website = WEBSITE_DOWNLOAD.read_text(encoding="utf-8")
    if f"'{package}'" not in website and f'"{package}"' not in website:
        problems.append(f"website Download.vue does not default VITE_SUNDAY_MOBILE_VERSION to {package}")
    return problems


def main() -> int:
    problems = check()
    if problems:
        print("mobile version drift:")
        for item in problems:
            print(f"  - {item}")
        return 1
    package = json.loads((MOBILE / "package.json").read_text(encoding="utf-8"))["version"]
    print(f"mobile version {package} is consistent everywhere (versionCode {_version_code(package)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
