"""Update check — query GitHub Releases for a newer LamCore build.

The desktop app (设置 → 关于与更新) and the CLI both call :func:`check_update`
to learn whether a newer release exists and where to download it. Only the
*check* is automated: installing stays a manual step (the user runs the
downloaded setup.exe), so no signing infrastructure is involved.

The update source is the GitHub Releases API of the Lam-Arc/LamTools repo —
the same channel the ``release.yml`` workflow publishes to. Network/parse
failures are folded into a ``check_failed`` result instead of raising, so a
temporary outage never breaks the app or the CLI.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from lamtools_core import __version__

_log = logging.getLogger(__name__)

#: Repo that hosts releases (kept in sync with .github/workflows/release.yml).
UPDATE_REPO = "Lam-Arc/LamTools"
#: GitHub API endpoint returning the newest non-prerelease release.
RELEASES_LATEST_URL = f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest"
#: Public releases page (fallback / human link).
RELEASES_PAGE_URL = f"https://github.com/{UPDATE_REPO}/releases/latest"

#: Installer asset name pattern inside a release (e.g. LamCore_0.2.2_x64-setup.exe).
SETUP_ASSET_PATTERN = re.compile(r"-setup\.exe$", re.IGNORECASE)

#: Release notes are trimmed to this many characters for the settings UI.
NOTES_MAX_CHARS = 800

#: GitHub API is unauthenticated here; a descriptive UA keeps the request clean.
_USER_AGENT = f"LamCore/{__version__} (update-check)"

#: Timeout budget for the whole request (connect + read).
REQUEST_TIMEOUT_SECONDS = 10.0


def compare_versions(a: str, b: str) -> int:
    """Compare two version strings, returning -1/0/1.

    ``v`` prefixes and non-numeric suffixes (e.g. ``-beta``) are tolerated:
    only dotted numeric segments participate, so ``v0.2.2`` vs ``0.2.2``
    compare equal and ``0.2.10 > 0.2.9``.
    """
    numbers = lambda v: [int(part) for part in re.findall(r"\d+", v or "")]

    pa, pb = numbers(a), numbers(b)
    for x, y in zip(pa, pb):
        if x != y:
            return -1 if x < y else 1
    if len(pa) != len(pb):
        return -1 if len(pa) < len(pb) else 1
    return 0


def _http_get_json(url: str) -> dict[str, Any]:
    """GET ``url`` and parse it as JSON, raising on any failure."""
    import httpx

    with httpx.Client(
        timeout=REQUEST_TIMEOUT_SECONDS,
        follow_redirects=True,
        headers={"User-Agent": _USER_AGENT, "Accept": "application/vnd.github+json"},
    ) as client:
        response = client.get(url)
        response.raise_for_status()
        data = response.json()
    if not isinstance(data, dict):
        raise ValueError(f"expected a JSON object, got {type(data).__name__}")
    return data


def _setup_asset(release: dict[str, Any]) -> str:
    """Return the browser_download_url of the ``*-setup.exe`` asset, or empty."""
    for asset in release.get("assets") or []:
        name = str(asset.get("name") or "")
        if SETUP_ASSET_PATTERN.search(name):
            return str(asset.get("browser_download_url") or "")
    return ""


def check_update() -> dict[str, Any]:
    """Check GitHub Releases for a newer LamCore than the running one.

    Returns one of:

    - ``{"status": "update_available", "current_version", "latest_version",
      "release_notes", "download_url", "release_url"}`` — a newer release with
      a downloadable installer exists.
    - ``{"status": "up_to_date", "current_version", "latest_version"}`` —
      the running version is the newest (or the newest release cannot be
      downloaded, e.g. it carries no installer asset).
    - ``{"status": "check_failed", "current_version", "error"}`` —
      network error, rate limit, or unparseable response. Never raises.
    """
    base: dict[str, Any] = {"current_version": __version__}
    try:
        release = _http_get_json(RELEASES_LATEST_URL)
    except Exception as exc:  # noqa: BLE001 — every failure becomes a check_failed
        _log.warning("Update check failed: %s", exc)
        base["status"] = "check_failed"
        base["error"] = str(exc)
        return base

    latest = str(release.get("tag_name") or "").lstrip("v").strip() or __version__
    base["latest_version"] = latest

    download_url = _setup_asset(release)
    if not download_url:
        # A release without an installer asset is not downloadable — treat as
        # up-to-date so the UI never offers an install it cannot perform.
        _log.info("Update check: latest release %s has no setup.exe asset", latest)
        base["status"] = "up_to_date"
        return base

    if compare_versions(__version__, latest) >= 0:
        base["status"] = "up_to_date"
        return base

    notes = str(release.get("body") or "").strip()
    if len(notes) > NOTES_MAX_CHARS:
        notes = notes[:NOTES_MAX_CHARS].rstrip() + "…"
    base["status"] = "update_available"
    base["release_notes"] = notes
    base["download_url"] = download_url
    base["release_url"] = RELEASES_PAGE_URL
    base["published_at"] = str(release.get("published_at") or "")
    return base


__all__ = ["RELEASES_PAGE_URL", "RELEASES_LATEST_URL", "check_update", "compare_versions"]
