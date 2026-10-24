"""收尾方案步骤 3 验收：链接安装 / 安装时依赖报告 / zip 更新。

user:“装、更新、卸载全程在 v2 页完成”+plugin.system.install 支持
local/zip/url 三来源；依赖检查提示不阻止（设计 10.1）；更新保留 data。
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from lamtools_core.app import OperationCatalog
from lamtools_core.plugin_system import PluginHost, shared_host
from lamtools_core.plugin_system.hooks import HookTrustStore
from lamtools_core.plugin_system.host_operations import register_host_operations
from lamtools_core.plugin_system.operations import register_plugin_system_operations
from lamtools_core.skills import SkillStateStore


def _make_plugin(root: Path, name: str, version: str, *, deps: list[str] | None = None) -> Path:
    plugin = root / name
    plugin.mkdir(parents=True, exist_ok=True)
    manifest: dict = {"name": name, "version": version}
    if deps:
        manifest["dependencies"] = deps
    (plugin / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    (plugin / "code.txt").write_text(f"{name} {version}\n", encoding="utf-8")
    return plugin


def _make_zip(tmp_path: Path, name: str, version: str, target: Path | None = None) -> Path:
    source = _make_plugin(tmp_path / "src", name, version)
    archive = target or (tmp_path / f"{name}-{version}.zip")
    with zipfile.ZipFile(archive, "w") as bundle:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                bundle.write(path, path.relative_to(source).as_posix())
    return archive


def _catalog(tmp_path: Path, roots: Path) -> OperationCatalog:
    host = shared_host(roots=[roots], state_path=tmp_path / "data" / "plugin-system.jsonc")
    catalog = OperationCatalog()
    register_plugin_system_operations(catalog, host)
    register_host_operations(
        catalog,
        host,
        work_root=tmp_path,
        data_dir=tmp_path / "data",
        skill_state_store=SkillStateStore(tmp_path / "skill_state.json"),
        skill_registry_factory=lambda: None,
        hook_trust_store=HookTrustStore(tmp_path / "hook_trust.json"),
    )
    return catalog


@pytest.mark.asyncio
async def test_install_from_url_downloads_then_installs(tmp_path, monkeypatch):
    roots = tmp_path / "roots"
    roots.mkdir()
    archive = _make_zip(tmp_path, "linked", "1.0.0")
    catalog = _catalog(tmp_path, roots)

    from lamtools_core.plugin_system import installer

    def fake_download(url: str, expected_sha256: str = "") -> Path:
        assert url == "https://example.com/linked.zip"
        return archive

    monkeypatch.setattr(installer, "download_archive", fake_download)

    result = await catalog.execute(
        "plugin.system.install",
        {"source": "url", "url": "https://example.com/linked.zip"},
    )

    assert result.status == "ok", result.payload
    assert result.payload["name"] == "linked"
    assert (roots / "linked" / "plugin.json").exists()


@pytest.mark.asyncio
async def test_install_reports_missing_dependencies_without_blocking(tmp_path):
    roots = tmp_path / "roots"
    roots.mkdir()
    source = _make_plugin(tmp_path / "src", "needy", "1.0.0", deps=["json", "no-such-pkg-xyz"])
    catalog = _catalog(tmp_path, roots)

    result = await catalog.execute(
        "plugin.system.install", {"source": "local", "path": str(source)}
    )

    # user:“缺包提示不阻止安装”+装进去了，同时报告缺哪个包。
    assert result.status == "ok", result.payload
    by_name = {item["name"]: item["status"] for item in result.payload["dependencies"]}
    assert by_name["json"] == "ok"
    assert by_name["no-such-pkg-xyz"] == "missing"
    assert result.payload["missing_dependencies"] == 1
    assert (roots / "needy" / "plugin.json").exists()


@pytest.mark.asyncio
async def test_update_from_zip_keeps_data(tmp_path):
    roots = tmp_path / "roots"
    roots.mkdir()
    first = _make_plugin(tmp_path / "src1", "keeper", "1.0.0")
    catalog = _catalog(tmp_path, roots)
    installed = await catalog.execute(
        "plugin.system.install", {"source": "local", "path": str(first)}
    )
    assert installed.status == "ok"
    data_dir = roots / "keeper" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "state.json").write_text('{"saved": true}', encoding="utf-8")

    upgrade = _make_zip(tmp_path, "keeper", "2.0.0")

    result = await catalog.execute(
        "plugin.system.update", {"source": "zip", "path": str(upgrade)}
    )

    assert result.status == "ok", result.payload
    manifest = json.loads((roots / "keeper" / "plugin.json").read_text(encoding="utf-8"))
    assert manifest["version"] == "2.0.0"
    # user:“更新只换代码和资源，data/ 保留”+数据还在原位。
    assert (data_dir / "state.json").read_text(encoding="utf-8") == '{"saved": true}'


@pytest.mark.asyncio
async def test_url_install_bad_checksum_is_rejected(tmp_path, monkeypatch):
    roots = tmp_path / "roots"
    roots.mkdir()
    archive = _make_zip(tmp_path, "checksummed", "1.0.0")
    catalog = _catalog(tmp_path, roots)

    from lamtools_core.plugin_system import installer

    monkeypatch.setattr(
        installer, "download_archive", lambda url, expected_sha256="": archive
    )
    # download_archive 负责校验；这里模拟校验失败。
    def rejected_download(url: str, expected_sha256: str = "") -> Path:
        raise ValueError("sha256 mismatch: expected deadbeef")

    monkeypatch.setattr(installer, "download_archive", rejected_download)

    result = await catalog.execute(
        "plugin.system.install",
        {"source": "url", "url": "https://example.com/a.zip", "sha256": "deadbeef"},
    )

    assert result.status == "error"
    assert "sha256 mismatch" in result.payload["error"]
    assert not (roots / "checksummed").exists()
