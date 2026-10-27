"""user:“都试一试”+(目录、压缩包、链接及冲突都从正式安装入口验收)。"""
import hashlib
import io
import json
import tarfile
import zipfile

import httpx
import pytest

from lamtools_core.app import OperationCatalog
from lamtools_core.plugin_system import PluginHost, PluginContext
from lamtools_core.plugin_system.backend_runtime import register_manager
from lamtools_core.plugin_system.operations import register_plugin_system_operations


def archive_bytes(kind):
    files = {"pkg/plugin.json": json.dumps({"name": "probe", "version": "1", "operations": [{"name": "probe.read", "handler": "ops:read"}]}).encode(),
             "pkg/ops.py": b"def read(request): return {'loaded': True}\n"}
    stream = io.BytesIO()
    if kind == "zip":
        with zipfile.ZipFile(stream, "w") as archive:
            for name, value in files.items():
                archive.writestr(name, value)
    else:
        with tarfile.open(fileobj=stream, mode="w:gz") as archive:
            for name, value in files.items():
                info = tarfile.TarInfo(name); info.size = len(value)
                archive.addfile(info, io.BytesIO(value))
    return stream.getvalue()


def setup(tmp_path):
    host = PluginHost(roots=[tmp_path / "plugins"], state_path=tmp_path / "state.json")
    register_manager(host, [], PluginContext(work_root=tmp_path))
    catalog = OperationCatalog()
    register_plugin_system_operations(catalog, host)
    return host, catalog


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["zip", "tgz"])
async def test_archive_install_calls_declared_operation(tmp_path, kind):
    host, catalog = setup(tmp_path)
    path = tmp_path / ("plugin." + kind)
    path.write_bytes(archive_bytes(kind))
    result = await catalog.execute("plugin.system.install", {"source": "zip", "path": str(path)})
    assert result.status == "ok", result.payload
    assert (await catalog.execute("probe.read")).payload["loaded"]


@pytest.mark.asyncio
async def test_release_url_follows_redirect_and_verifies_digest(tmp_path, monkeypatch):
    host, catalog = setup(tmp_path)
    data = archive_bytes("zip")
    original = httpx.Client
    def response(request):
        if request.url.path == "/release.zip":
            return httpx.Response(302, headers={"Location": "https://assets.example/plugin.zip"})
        return httpx.Response(200, content=data)
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(response), **kwargs))
    result = await catalog.execute("plugin.system.install", {"source": "url", "url": "https://example.test/release.zip", "sha256": hashlib.sha256(data).hexdigest()})
    assert result.status == "ok", result.payload
    assert (await catalog.execute("probe.read")).payload["loaded"]


@pytest.mark.asyncio
async def test_wrong_digest_does_not_install_any_code(tmp_path, monkeypatch):
    host, catalog = setup(tmp_path)
    data = archive_bytes("zip")
    original = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=data)), **kwargs))
    result = await catalog.execute("plugin.system.install", {"source": "url", "url": "https://example.test/release.zip", "sha256": "00" * 32})
    assert result.status == "error"
    assert host.discover() == []


@pytest.mark.asyncio
async def test_conflicting_operation_is_rejected_before_loading_new_backend(tmp_path):
    from tests.test_plugin_host_rebuild import boot, plugin
    host, manager, catalog, folder = await boot(tmp_path)
    source = plugin(tmp_path / "incoming", "1")
    raw = json.loads((source / "plugin.json").read_text()); raw["name"] = "other"
    (source / "plugin.json").write_text(json.dumps(raw))
    (source / "backend.py").write_text("raise AssertionError('conflicting backend must not execute')")
    result = await catalog.execute("plugin.system.install", {"path": str(source)})
    assert result.status == "error" and "demo.read" in result.payload["error"]
    assert host.get("other") is None
    assert host.available("demo")
    await manager.stop("demo")


@pytest.mark.asyncio
async def test_unrelated_invalid_plugin_does_not_block_install(tmp_path):
    # user:“该重建就重建”+(无关插件的坏声明不能阻断正常插件安装)。
    host, catalog = setup(tmp_path)
    broken = tmp_path / "plugins" / "broken"
    broken.mkdir(parents=True)
    (broken / "plugin.json").write_text(json.dumps({"name": "broken", "version": "1", "operations": ["./absent.json"]}))
    path = tmp_path / "plugin.zip"
    path.write_bytes(archive_bytes("zip"))
    result = await catalog.execute("plugin.system.install", {"path": str(path), "source": "zip"})
    assert result.status == "ok", result.payload
    assert (await catalog.execute("probe.read")).payload["loaded"]
