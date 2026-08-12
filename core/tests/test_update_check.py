"""Tests for the update check (GitHub Releases source)."""

from __future__ import annotations

import lamtools_core
from lamtools_core.update.checker import (
    RELEASES_PAGE_URL,
    check_update,
    compare_versions,
)


def _release(
    *,
    tag: str,
    assets: list[dict] | None = None,
    body: str = "",
) -> dict:
    return {
        "tag_name": tag,
        "name": tag,
        "body": body,
        "published_at": "2026-08-13T00:00:00Z",
        "assets": assets
        if assets is not None
        else [
            {
                "name": "LamCore_x64-setup.exe",
                "browser_download_url": f"https://github.com/Lam-Arc/LamTools/releases/download/{tag}/LamCore_x64-setup.exe",
            }
        ],
    }


def _stub_http(monkeypatch, release: dict) -> None:
    """Point the network call at a canned GitHub release payload."""
    monkeypatch.setattr(
        "lamtools_core.update.checker._http_get_json",
        lambda url: release,
    )


def test_newer_release_available(monkeypatch) -> None:
    _stub_http(monkeypatch, _release(tag="v9.9.9", body="## 更新内容\n- 新功能"))
    result = check_update()
    assert result["status"] == "update_available"
    assert result["current_version"] == lamtools_core.__version__
    assert result["latest_version"] == "9.9.9"
    assert "新功能" in result["release_notes"]
    assert result["download_url"].endswith("LamCore_x64-setup.exe")
    assert result["release_url"] == RELEASES_PAGE_URL
    assert result["published_at"]


def test_up_to_date_when_versions_match(monkeypatch) -> None:
    _stub_http(monkeypatch, _release(tag=f"v{lamtools_core.__version__}"))
    result = check_update()
    assert result["status"] == "up_to_date"
    assert result["latest_version"] == lamtools_core.__version__


def test_older_release_is_up_to_date(monkeypatch) -> None:
    _stub_http(monkeypatch, _release(tag="v0.0.1"))
    result = check_update()
    assert result["status"] == "up_to_date"


def test_release_without_installer_asset_is_not_downloadable(monkeypatch) -> None:
    _stub_http(monkeypatch, _release(tag="v9.9.9", assets=[]))
    result = check_update()
    assert result["status"] == "up_to_date"


def test_network_failure_becomes_check_failed(monkeypatch) -> None:
    def boom(_url: str) -> dict:
        raise ConnectionError("network unreachable")

    monkeypatch.setattr("lamtools_core.update.checker._http_get_json", boom)
    result = check_update()
    assert result["status"] == "check_failed"
    assert "network unreachable" in result["error"]
    assert result["current_version"] == lamtools_core.__version__


def test_compare_versions() -> None:
    assert compare_versions("0.2.2", "0.2.2") == 0
    assert compare_versions("v0.2.2", "0.2.2") == 0
    assert compare_versions("0.2.9", "0.2.10") == -1
    assert compare_versions("0.3.0", "0.2.99") == 1
    assert compare_versions("0.3.0-beta", "0.3.0") == 0  # pre-release suffix ignored
    assert compare_versions("1.0", "0.9.9") == 1
