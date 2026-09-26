"""Update check — read the official site manifest, fall back to GitHub Releases.

The desktop app (设置 → 关于与更新) and the CLI both call :func:`check_update`
to learn whether a newer release exists and where to download it. Only the
*check* is automated: installing stays a manual step (the user runs the
downloaded platform installer), so no signing infrastructure is involved.

The official site is the primary *download* channel: ``downloads/desktop-update.json``
sits next to the installers the project publishes, so it points at a download that
works in the same regions. Both sources are consulted and the higher version wins
(a stale manifest can no longer freeze update detection); on a tie the manifest
supplies the download URL and GitHub supplies the release notes. Network/parse
failures are folded into a ``check_failed`` result instead of raising, so a
temporary outage never breaks the app or the CLI — and when both sources fail,
the error names both.
"""

from __future__ import annotations

import logging
import os
import platform
import re
from itertools import zip_longest
from typing import Any

from lamtools_core import __version__

_log = logging.getLogger(__name__)

#: Repo that hosts releases (kept in sync with .github/workflows/release.yml).
UPDATE_REPO = "Lam-Arc/LamTools"
#: GitHub API endpoint returning the newest non-prerelease release.
RELEASES_LATEST_URL = f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest"
#: Public releases page (fallback / human link).
RELEASES_PAGE_URL = f"https://github.com/{UPDATE_REPO}/releases/latest"

#: Official-site update manifest, published next to the installers and beside
#: the mobile manifest (``scripts/build-desktop-update.py`` writes it).
DEFAULT_SITE_UPDATE_URL = "https://47.114.43.99.nip.io/downloads/desktop-update.json"
#: Deployment override, so a renamed or self-hosted manifest needs no code change.
SITE_UPDATE_URL_ENV = "LAMTOOLS_DESKTOP_UPDATE_URL"

#: Where a result came from, for the settings UI and for diagnostics.
SOURCE_SITE = "site"
SOURCE_GITHUB = "github"

#: Repository-owned Inno installer asset name (e.g. Sunday_0.3.2_x64-setup.exe).
SETUP_ASSET_PATTERN = re.compile(
    r"^Sunday_\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?_x64-setup\.exe$",
    re.IGNORECASE,
)

# Tauri's default Linux bundle names (e.g. Sunday_0.3.5_amd64.AppImage and
# Sunday_0.3.5_amd64.deb). AppImage is preferred below because it is portable
# across distributions; the Debian package remains a useful native fallback.
LINUX_APPIMAGE_ASSET_PATTERN = re.compile(
    r"^Sunday_\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?_(?:amd64|x86_64)\.AppImage$",
    re.IGNORECASE,
)
LINUX_DEB_ASSET_PATTERN = re.compile(
    r"^Sunday_\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?_(?:amd64|x86_64)\.deb$",
    re.IGNORECASE,
)

_X64_MACHINE_NAMES = frozenset({"amd64", "x86_64", "x64"})

#: Release notes are trimmed to this many characters for the settings UI.
NOTES_MAX_CHARS = 800

#: GitHub API is unauthenticated here; a descriptive UA keeps the request clean.
_USER_AGENT = f"Sunday/{__version__} (update-check)"

#: Timeout budget for the whole request (connect + read).
REQUEST_TIMEOUT_SECONDS = 10.0


def _split_version(value: str) -> tuple[list[int], list[str]]:
    """Split a version into (numeric core, pre-release identifiers)."""
    text = str(value or "").strip().lstrip("vV").split("+", 1)[0]
    core, _, pre = text.partition("-")
    numbers = [int(part) for part in re.findall(r"\d+", core)] or [0]
    identifiers = [part for part in pre.split(".") if part] if pre else []
    return numbers, identifiers


def compare_versions(a: str, b: str) -> int:
    """Compare two version strings, returning -1/0/1.

    Semver-aware: numeric cores compare with the shorter side padded by zeros
    (``0.3.10 == 0.3.10.0``), build metadata is ignored, and a pre-release ranks
    *below* its release — ``0.3.7-beta.1 < 0.3.7``. Pre-release identifiers
    compare per semver: numeric identifiers numerically (and below
    alphanumeric ones), then ASCII. ``v`` prefixes stay tolerated, so
    ``v0.2.2`` and ``0.2.2`` compare equal and ``0.2.10 > 0.2.9``.

    The old shape only collected digit runs, which made ``0.3.7-beta.1`` rank
    *above* ``0.3.7`` and left beta users permanently "up to date"
    (2026-09-25 审计 P1).
    """
    core_a, pre_a = _split_version(a)
    core_b, pre_b = _split_version(b)
    for left, right in zip_longest(core_a, core_b, fillvalue=0):
        if left != right:
            return -1 if left < right else 1
    if bool(pre_a) != bool(pre_b):
        return -1 if pre_a else 1
    for left, right in zip_longest(pre_a, pre_b):
        if left is None:
            return -1
        if right is None:
            return 1
        left_numeric, right_numeric = left.isdigit(), right.isdigit()
        if left_numeric and right_numeric:
            if int(left) != int(right):
                return -1 if int(left) < int(right) else 1
            continue
        if left_numeric != right_numeric:
            return -1 if left_numeric else 1
        if left != right:
            return -1 if left < right else 1
    return 0


def _http_get_json(url: str) -> dict[str, Any]:
    """GET ``url`` and parse it as JSON, raising on any failure."""
    import httpx

    accept = "application/vnd.github+json" if "api.github.com" in url else "application/json"
    with httpx.Client(
        timeout=REQUEST_TIMEOUT_SECONDS,
        follow_redirects=True,
        headers={"User-Agent": _USER_AGENT, "Accept": accept},
    ) as client:
        response = client.get(url)
        response.raise_for_status()
        data = response.json()
    if not isinstance(data, dict):
        raise ValueError(f"expected a JSON object, got {type(data).__name__}")
    return data


def site_update_url() -> str:
    """Return the official-site manifest URL for this deployment."""
    return os.environ.get(SITE_UPDATE_URL_ENV, "").strip() or DEFAULT_SITE_UPDATE_URL


#: Display labels for the source keys, shared by the CLI output.
SOURCE_LABELS = {SOURCE_SITE: "官网", SOURCE_GITHUB: "GitHub Releases"}


def source_label(key: str | None) -> str:
    """Human-readable name of a source key ('' when unknown)."""
    return SOURCE_LABELS.get(str(key or ""), "")


def _first_line(message: str) -> str:
    """Collapse a library error to its first line for display."""
    return message.strip().splitlines()[0].strip() if message.strip() else "unavailable"


class SourceUnavailable(Exception):
    """A source answered but cannot serve this platform's installer.

    Carries the version that source reported, so a release without a usable
    asset still reports ``up_to_date`` (with its version) instead of a failure.
    """

    def __init__(self, reason: str, latest_version: str = "") -> None:
        super().__init__(reason)
        self.latest_version = latest_version


def _setup_asset(release: dict[str, Any]) -> str:
    """Return the browser_download_url of the ``*-setup.exe`` asset, or empty."""
    for asset in release.get("assets") or []:
        name = str(asset.get("name") or "")
        if SETUP_ASSET_PATTERN.search(name):
            return str(asset.get("browser_download_url") or "")
    return ""


def _matching_asset(release: dict[str, Any], pattern: re.Pattern[str]) -> str:
    """Return the first non-empty download URL matching ``pattern``."""
    for asset in release.get("assets") or []:
        name = str(asset.get("name") or "")
        if pattern.search(name):
            url = str(asset.get("browser_download_url") or "")
            if url:
                return url
    return ""


def _runtime_platform() -> str:
    """Return the supported update target for this process.

    Windows keeps the historical setup.exe path. Linux is intentionally
    limited to x86_64 because no other Linux architecture is published yet;
    unsupported platforms receive no installer URL rather than a misleading
    foreign binary.
    """
    system = platform.system().lower()
    if system == "windows":
        return "windows-x64"
    if system == "linux" and platform.machine().lower() in _X64_MACHINE_NAMES:
        return "linux-x64"
    return "unsupported"


def _runtime_asset(release: dict[str, Any]) -> str:
    """Return the download URL suitable for this runtime, or empty."""
    target = _runtime_platform()
    if target == "windows-x64":
        return _setup_asset(release)
    if target == "linux-x64":
        appimage = _matching_asset(release, LINUX_APPIMAGE_ASSET_PATTERN)
        if appimage:
            return appimage
        deb = _matching_asset(release, LINUX_DEB_ASSET_PATTERN)
        if deb:
            return deb
    return ""


def _site_candidate() -> dict[str, Any]:
    """Read the official-site manifest, raising when it cannot serve this platform.

    The manifest mirrors the mobile one (``version`` / ``download_url`` /
    ``release_url`` / ``release_notes``) and may add ``linux_download_url`` for
    the Linux bundles, so one file describes every published installer.
    """
    manifest = _http_get_json(site_update_url())
    version = str(manifest.get("version") or "").lstrip("v").strip()
    target = _runtime_platform()
    if not version:
        raise ValueError("manifest has no version")
    # A platform never falls back to another platform's installer.
    keys = {
        "windows-x64": ("download_url", "sha256", "size"),
        "linux-x64": ("linux_download_url", "linux_sha256", "linux_size"),
    }.get(target, ("", "", ""))
    url_key, digest_key, size_key = keys
    download_url = str(manifest.get(url_key) or "").strip() if url_key else ""
    if not download_url:
        raise SourceUnavailable(f"manifest has no installer for {target}", version)
    # The digest is what a download is verified against before an installer sees
    # it; a manifest without one simply loses the in-app install path.
    digest = str(manifest.get(digest_key) or "").strip().lower() if digest_key else ""
    size_value = str(manifest.get(size_key) or "") if size_key else ""
    return {
        "version": version,
        "download_url": download_url,
        "release_url": str(manifest.get("release_url") or RELEASES_PAGE_URL),
        "release_notes": str(manifest.get("release_notes") or ""),
        "published_at": str(manifest.get("published_at") or ""),
        "sha256": digest if len(digest) == 64 else "",
        "size": int(size_value) if size_value.isdigit() else 0,
    }


def _github_candidate() -> dict[str, Any]:
    """Read the newest GitHub release, raising when it carries no usable asset."""
    release = _http_get_json(RELEASES_LATEST_URL)
    version = str(release.get("tag_name") or "").lstrip("v").strip()
    download_url = _runtime_asset(release)
    if not version:
        raise ValueError("release has no tag")
    if not download_url:
        raise SourceUnavailable(
            f"release {version} has no installer for {_runtime_platform()}", version
        )
    notes = str(release.get("body") or "").strip()
    if len(notes) > NOTES_MAX_CHARS:
        notes = notes[:NOTES_MAX_CHARS].rstrip() + "…"
    return {
        "version": version,
        "download_url": download_url,
        "release_url": RELEASES_PAGE_URL,
        "release_notes": notes,
        "published_at": str(release.get("published_at") or ""),
    }


def check_update() -> dict[str, Any]:
    """Check for a newer Sunday, consulting both sources and taking the higher.

    Returns one of:

    - ``{"status": "update_available", "current_version", "latest_version",
      "release_notes", "notes_source", "download_url", "release_url",
      "published_at", "source"}`` — a newer version with a target-specific
      installer exists.
    - ``{"status": "up_to_date", "current_version", "latest_version",
      "source"}`` — the running version is the newest.

      When no source can serve this platform's installer, the same status
      carries ``"reason": "no_installer_for_platform"`` so the UI can say so
      instead of claiming the app is current.
    - ``{"status": "check_failed", "current_version", "error"}`` — both
      sources failed; the error names each one. Never raises.

    Both sources are asked, and the *higher* version wins; on a tie the
    official site supplies the download URL (same build, better regional
    reach) while GitHub supplies the release notes (it has the real release
    body). A stale site manifest therefore no longer freezes update detection
    — it only loses the download link (2026-09-25 审计 P1).
    """
    base: dict[str, Any] = {"current_version": __version__}
    candidates: dict[str, dict[str, Any]] = {}
    reasons: list[str] = []
    reported_version = ""
    reported_source = ""
    for name, key, loader in (
        ("official site", SOURCE_SITE, _site_candidate),
        ("GitHub", SOURCE_GITHUB, _github_candidate),
    ):
        try:
            candidates[key] = loader()
        except SourceUnavailable as exc:
            reasons.append(f"{name}: {_first_line(str(exc))}")
            if exc.latest_version and not reported_version:
                reported_version = exc.latest_version
                reported_source = key
            _log.info("Update check: %s cannot serve this platform: %s", name, exc)
        except Exception as exc:  # noqa: BLE001 — every failure becomes a check_failed
            reasons.append(f"{name}: {_first_line(str(exc))}")
            _log.warning("Update check: %s source unavailable: %s", name, exc)

    if not candidates:
        if reported_version:
            # Someone published a release, but nothing installable for this
            # platform: report up to date (with the reason) rather than
            # offering an install that cannot be performed.
            base["status"] = "up_to_date"
            base["latest_version"] = reported_version
            base["source"] = reported_source
            base["reason"] = "no_installer_for_platform"
            return base
        base["status"] = "check_failed"
        base["error"] = "; ".join(reasons)
        return base

    # Tie-break order: whoever appears first wins, i.e. the official site.
    chosen_key = ""
    for key in (SOURCE_SITE, SOURCE_GITHUB):
        if key not in candidates:
            continue
        if not chosen_key or compare_versions(candidates[key]["version"], candidates[chosen_key]["version"]) > 0:
            chosen_key = key
    chosen = candidates[chosen_key]
    latest = chosen["version"]

    github = candidates.get(SOURCE_GITHUB)
    notes_key = chosen_key
    if github is not None and compare_versions(github["version"], latest) == 0:
        notes_key = SOURCE_GITHUB

    base["latest_version"] = latest
    base["source"] = chosen_key
    base["notes_source"] = notes_key
    if compare_versions(__version__, latest) >= 0:
        base["status"] = "up_to_date"
        return base

    base["status"] = "update_available"
    base["release_notes"] = candidates[notes_key]["release_notes"]
    base["download_url"] = chosen["download_url"]
    base["release_url"] = chosen["release_url"]
    base["published_at"] = chosen["published_at"]
    # The in-app install needs a digest to verify against, and a platform with a
    # single "run this installer" step. Both hosts apply the same rule, so the
    # button only appears when downloading and installing can actually work.
    digest = str(chosen.get("sha256") or "")
    if digest:
        base["sha256"] = digest
        if chosen.get("size"):
            base["size"] = chosen["size"]
        if os.name == "nt":
            base["install_supported"] = True
            base["install_hint"] = "点「立即安装」会运行安装包；安装向导会要求先退出 Sunday。"
    return base


__all__ = [
    "DEFAULT_SITE_UPDATE_URL",
    "RELEASES_LATEST_URL",
    "RELEASES_PAGE_URL",
    "SITE_UPDATE_URL_ENV",
    "SOURCE_GITHUB",
    "SOURCE_LABELS",
    "SOURCE_SITE",
    "check_update",
    "compare_versions",
    "site_update_url",
    "source_label",
]
