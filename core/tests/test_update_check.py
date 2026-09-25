"""Tests for the update check (official site first, GitHub fallback)."""

from __future__ import annotations

import lamtools_core
import pytest
from lamtools_core.update.checker import (
    DEFAULT_SITE_UPDATE_URL,
    RELEASES_LATEST_URL,
    RELEASES_PAGE_URL,
    SITE_UPDATE_URL_ENV,
    SOURCE_GITHUB,
    SOURCE_SITE,
    check_update,
    compare_versions,
    site_update_url,
)


@pytest.fixture(autouse=True)
def _windows_runtime_by_default(monkeypatch) -> None:
    """Keep legacy asset tests deterministic on every CI host OS."""
    monkeypatch.setattr("lamtools_core.update.checker.platform.system", lambda: "Windows")
    monkeypatch.setattr("lamtools_core.update.checker.platform.machine", lambda: "AMD64")


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
                "name": "Sunday_9.9.9_x64-setup.exe",
                "browser_download_url": f"https://github.com/Lam-Arc/LamTools/releases/download/{tag}/Sunday_9.9.9_x64-setup.exe",
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
    assert result["download_url"].endswith("Sunday_9.9.9_x64-setup.exe")
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


def test_legacy_nsis_asset_is_not_selected(monkeypatch) -> None:
    _stub_http(
        monkeypatch,
        _release(
            tag="v9.9.9",
            assets=[
                {
                    "name": "LamCore_9.9.9_x64-setup.exe",
                    "browser_download_url": "https://example.test/legacy.exe",
                }
            ],
        ),
    )
    result = check_update()
    assert result["status"] == "up_to_date"


def test_linux_prefers_appimage_over_deb(monkeypatch) -> None:
    monkeypatch.setattr("lamtools_core.update.checker.platform.system", lambda: "Linux")
    monkeypatch.setattr("lamtools_core.update.checker.platform.machine", lambda: "x86_64")
    _stub_http(
        monkeypatch,
        _release(
            tag="v9.9.9",
            assets=[
                {
                    "name": "Sunday_9.9.9_amd64.deb",
                    "browser_download_url": "https://example.test/Sunday_9.9.9_amd64.deb",
                },
                {
                    "name": "Sunday_9.9.9_amd64.AppImage",
                    "browser_download_url": "https://example.test/Sunday_9.9.9_amd64.AppImage",
                },
            ],
        ),
    )
    result = check_update()
    assert result["status"] == "update_available"
    assert result["download_url"].endswith("Sunday_9.9.9_amd64.AppImage")


def test_linux_falls_back_to_deb(monkeypatch) -> None:
    monkeypatch.setattr("lamtools_core.update.checker.platform.system", lambda: "Linux")
    monkeypatch.setattr("lamtools_core.update.checker.platform.machine", lambda: "amd64")
    _stub_http(
        monkeypatch,
        _release(
            tag="v9.9.9",
            assets=[
                {
                    "name": "Sunday_9.9.9_amd64.deb",
                    "browser_download_url": "https://example.test/Sunday_9.9.9_amd64.deb",
                }
            ],
        ),
    )
    result = check_update()
    assert result["status"] == "update_available"
    assert result["download_url"].endswith("Sunday_9.9.9_amd64.deb")


def test_unsupported_platform_does_not_offer_foreign_asset(monkeypatch) -> None:
    monkeypatch.setattr("lamtools_core.update.checker.platform.system", lambda: "Darwin")
    _stub_http(monkeypatch, _release(tag="v9.9.9"))
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
    assert compare_versions("1.0", "0.9.9") == 1
    # 尾零补齐：与移动端 compareVersion 同语义（旧的"段多者更新"已废除）
    assert compare_versions("0.3.10", "0.3.10.0") == 0


def test_compare_versions_ranks_pre_releases_below_the_release() -> None:
    """预发布低于同名正式版。

    旧实现只收集数字段，``0.3.7-beta.1`` 会被判成比 ``0.3.7`` 更新，于是
    beta 用户永远收不到正式版升级（2026-09-25 审计 P1）——这条测试钉住新语义。
    """
    assert compare_versions("0.3.0-beta", "0.3.0") == -1
    assert compare_versions("0.3.7-beta.1", "0.3.7") == -1
    assert compare_versions("0.3.7", "0.3.7-beta.1") == 1
    assert compare_versions("0.3.7-beta.2", "0.3.7-beta.1") == 1
    assert compare_versions("0.3.7-beta.1", "0.3.7-beta.1") == 0
    assert compare_versions("0.3.7-beta", "0.3.7-rc") == -1          # 字母段按 ASCII
    assert compare_versions("0.3.7-beta.2", "0.3.7-beta.10") == -1   # 数字段按数值
    assert compare_versions("0.3.7-2", "0.3.7-beta") == -1           # 数字段 < 字母段
    assert compare_versions("0.3.7-beta.1+build.9", "0.3.7-beta.1") == 0  # 构建元数据忽略


def _stub_by_url(monkeypatch, **routes):
    """Route ``_http_get_json`` per URL; a value may be a payload or an exception."""
    calls: list[str] = []

    def fake(url: str) -> dict:
        calls.append(url)
        route = routes.get(url)
        if route is None:
            raise OSError(f"no route for {url}")
        if isinstance(route, Exception):
            raise route
        return route

    monkeypatch.setattr("lamtools_core.update.checker._http_get_json", fake)
    return calls


def _site_manifest(*, version="9.9.9", **extra) -> dict:
    return {"version": version, "download_url": f"https://site/downloads/Sunday_{version}_x64-setup.exe",
            "release_url": "https://site/#download", "release_notes": f"Sunday {version}", **extra}


def test_site_manifest_is_the_primary_source(monkeypatch) -> None:
    _stub_by_url(monkeypatch, **{DEFAULT_SITE_UPDATE_URL: _site_manifest()})
    result = check_update()
    assert result["status"] == "update_available"
    assert result["source"] == SOURCE_SITE
    assert result["latest_version"] == "9.9.9"
    assert result["download_url"].startswith("https://site/downloads/")
    assert result["release_url"] == "https://site/#download"


def test_site_version_wins_over_a_newer_github_release(monkeypatch) -> None:
    """落后不再冻结：两源都问、取版本较高者（2026-09-25 审计 P1）。

    旧实现"先答者胜"，清单停在 9.9.9 时 GitHub 的 v10.0.0 永远不会被看到。
    """
    _stub_by_url(
        monkeypatch,
        **{DEFAULT_SITE_UPDATE_URL: _site_manifest(version="9.9.9"),
           RELEASES_LATEST_URL: _release(tag="v10.0.0")},
    )
    result = check_update()

    assert result["status"] == "update_available"
    assert result["latest_version"] == "10.0.0"
    assert result["source"] == SOURCE_GITHUB


def test_same_version_takes_the_site_download_and_github_notes(monkeypatch) -> None:
    """同版本时：下载地址用官网，更新说明用 GitHub 的发布正文。"""
    _stub_by_url(
        monkeypatch,
        **{DEFAULT_SITE_UPDATE_URL: _site_manifest(version="9.9.9"),
           RELEASES_LATEST_URL: _release(tag="v9.9.9", body="## 更新内容\n- 真正文")},
    )
    result = check_update()

    assert result["status"] == "update_available"
    assert result["latest_version"] == "9.9.9"
    assert result["source"] == SOURCE_SITE
    assert result["notes_source"] == SOURCE_GITHUB
    assert result["download_url"].startswith("https://site/downloads/")
    assert "真正文" in result["release_notes"]


def test_notes_come_from_the_winner_when_github_is_older(monkeypatch) -> None:
    _stub_by_url(
        monkeypatch,
        **{DEFAULT_SITE_UPDATE_URL: _site_manifest(version="9.9.9"),
           RELEASES_LATEST_URL: _release(tag="v9.0.0", body="旧正文")},
    )
    result = check_update()

    assert result["source"] == SOURCE_SITE
    assert result["notes_source"] == SOURCE_SITE
    assert result["release_notes"] == "Sunday 9.9.9"


def test_site_failure_falls_back_to_github(monkeypatch) -> None:
    calls = _stub_by_url(monkeypatch, **{RELEASES_LATEST_URL: _release(tag="v9.9.9")})
    result = check_update()
    assert result["status"] == "update_available"
    assert result["source"] == SOURCE_GITHUB
    assert result["latest_version"] == "9.9.9"
    assert DEFAULT_SITE_UPDATE_URL in calls


def test_site_manifest_without_a_version_is_ignored(monkeypatch) -> None:
    _stub_by_url(
        monkeypatch,
        **{DEFAULT_SITE_UPDATE_URL: {"download_url": "https://site/downloads/whatever.exe"},
           RELEASES_LATEST_URL: _release(tag="v9.9.9")},
    )
    result = check_update()
    assert result["source"] == SOURCE_GITHUB


def test_site_manifest_without_this_platform_installer_falls_back(monkeypatch) -> None:
    monkeypatch.setattr("lamtools_core.update.checker.platform.system", lambda: "Linux")
    monkeypatch.setattr("lamtools_core.update.checker.platform.machine", lambda: "x86_64")
    asset = "Sunday_9.9.9_amd64.AppImage"
    _stub_by_url(
        monkeypatch,
        **{DEFAULT_SITE_UPDATE_URL: _site_manifest(),  # Windows installer only
           RELEASES_LATEST_URL: _release(tag="v9.9.9", assets=[{
               "name": asset,
               "browser_download_url": f"https://github.com/Lam-Arc/LamTools/releases/download/v9.9.9/{asset}"}])},
    )
    result = check_update()
    assert result["source"] == SOURCE_GITHUB
    assert result["download_url"].endswith(asset)


def test_site_manifest_serves_linux_from_its_own_key(monkeypatch) -> None:
    monkeypatch.setattr("lamtools_core.update.checker.platform.system", lambda: "Linux")
    monkeypatch.setattr("lamtools_core.update.checker.platform.machine", lambda: "x86_64")
    _stub_by_url(
        monkeypatch,
        **{DEFAULT_SITE_UPDATE_URL: _site_manifest(linux_download_url="https://site/downloads/Sunday_9.9.9_amd64.AppImage")},
    )
    result = check_update()
    assert result["source"] == SOURCE_SITE
    assert result["download_url"].endswith("Sunday_9.9.9_amd64.AppImage")


def test_both_sources_failing_names_both(monkeypatch) -> None:
    _stub_by_url(
        monkeypatch,
        **{DEFAULT_SITE_UPDATE_URL: OSError("site unreachable"),
           RELEASES_LATEST_URL: OSError("github unreachable")},
    )
    result = check_update()
    assert result["status"] == "check_failed"
    assert "site unreachable" in result["error"] and "github unreachable" in result["error"]
    assert "official site" in result["error"] and "GitHub" in result["error"]


def test_no_installer_anywhere_stays_up_to_date(monkeypatch) -> None:
    _stub_by_url(
        monkeypatch,
        **{DEFAULT_SITE_UPDATE_URL: {"version": "9.9.9"},
           RELEASES_LATEST_URL: _release(tag="v9.9.9", assets=[])},
    )
    result = check_update()
    assert result["status"] == "up_to_date"
    assert result["latest_version"] == "9.9.9"


def test_site_update_url_can_be_pointed_elsewhere(monkeypatch) -> None:
    custom = "https://mirror.example/desktop-update.json"
    monkeypatch.setenv(SITE_UPDATE_URL_ENV, custom)
    assert site_update_url() == custom
    calls = _stub_by_url(monkeypatch, **{custom: _site_manifest()})
    result = check_update()
    assert result["source"] == SOURCE_SITE
    # 覆盖生效：请求的是自定义地址，不是内置默认（两源都会问，见 check_update）
    assert custom in calls
    assert DEFAULT_SITE_UPDATE_URL not in calls
