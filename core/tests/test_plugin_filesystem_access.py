"""user:“宿主能力补齐和接口完善与文档更新”+(验收工作目录绑定、有限只读访问及停用撤回)。"""
from pathlib import Path

import pytest

from lamtools_core.plugin_system.context import PluginContext


def view(root):
    ctx = PluginContext(root)
    ctx._begin_registration_scope("example", 1)
    return ctx, ctx.filesystem


def test_binary_text_stat_and_directory(tmp_path):
    ctx, fs = view(tmp_path)
    raw = "你好\r\nlast".encode()
    (tmp_path / "a.txt").write_bytes(raw)
    (tmp_path / "folder").mkdir()
    assert fs.root == tmp_path.resolve()
    assert fs.read_bytes("a.txt", max_bytes=len(raw)) == raw
    assert fs.read_text("a.txt", max_bytes=len(raw)) == "你好\r\nlast"
    info = fs.stat("a.txt")
    assert info.kind == "file" and info.size == len(raw)
    assert fs.stat("folder").kind == "directory"
    listing = fs.list_dir(limit=1)
    assert len(listing.entries) == 1 and listing.truncated
    assert {e.name for e in fs.list_dir().entries} == {"a.txt", "folder"}
    ctx.work_root = tmp_path / "folder"
    assert fs.read_bytes("a.txt", max_bytes=len(raw)) == raw
    assert ctx.filesystem.root == (tmp_path / "folder").resolve()


@pytest.mark.parametrize("path", ["../outside", "bad\x00name", "file:stream"])
def test_invalid_or_outside_paths_fail(tmp_path, path):
    _, fs = view(tmp_path)
    with pytest.raises(ValueError):
        fs.stat(path)


def test_absolute_inside_allowed_outside_denied(tmp_path):
    _, fs = view(tmp_path)
    assert fs.stat(tmp_path).kind == "directory"
    with pytest.raises(ValueError):
        fs.stat(tmp_path.parent)


@pytest.mark.parametrize("limit", [True, 0, -1, 1.2, 1048577])
def test_invalid_byte_limits(tmp_path, limit):
    _, fs = view(tmp_path)
    with pytest.raises(ValueError):
        fs.read_bytes("absent", max_bytes=limit)


def test_limits_and_errors_do_not_return_partial_success(tmp_path):
    from lamtools_core.plugin_system.filesystem_access import FilesystemError
    _, fs = view(tmp_path)
    (tmp_path / "big").write_bytes(b"abc")
    (tmp_path / "binary").write_bytes(b"\xff")
    for call, code in [
        (lambda: fs.read_bytes("big", max_bytes=2), "fs/too-large"),
        (lambda: fs.read_text("binary", max_bytes=2), "fs/not-text"),
        (lambda: fs.read_bytes(".", max_bytes=2), "fs/not-file"),
        (lambda: fs.stat("absent"), "fs/not-found"),
        (lambda: fs.list_dir("big"), "fs/not-directory"),
    ]:
        with pytest.raises(FilesystemError) as error:
            call()
        assert error.value.code == code


def test_symlink_or_junction_not_followed(tmp_path):
    import subprocess
    _, fs = view(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    (target / "value").write_text("x")
    link = tmp_path / "link"
    import os
    if os.name == "nt":
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
        assert result.returncode == 0
    else:
        link.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError):
        fs.read_bytes("link/value", max_bytes=2)
    assert next(e for e in fs.list_dir().entries if e.name == "link").kind == "link"


@pytest.mark.asyncio
async def test_old_views_revoked_after_scope_disposal(tmp_path):
    from lamtools_core.plugin_system.services import ServiceError
    ctx, fs = view(tmp_path)
    await ctx._registration_scope.dispose()
    for call in [lambda: fs.root, lambda: fs.stat(), lambda: fs.list_dir(), lambda: fs.read_text("a", max_bytes=1)]:
        with pytest.raises(ServiceError):
            call()


@pytest.mark.parametrize("limit", [True, 0, 1001])
def test_invalid_listing_limits(tmp_path, limit):
    _, fs = view(tmp_path)
    with pytest.raises(ValueError):
        fs.list_dir(limit=limit)


def test_unmanaged_context_has_no_filesystem(tmp_path):
    from lamtools_core.plugin_system.services import ServiceError
    with pytest.raises(ServiceError):
        _ = PluginContext(tmp_path).filesystem


def test_nul_text_and_exact_listing_boundary(tmp_path):
    from lamtools_core.plugin_system import FilesystemError
    _, fs = view(tmp_path)
    (tmp_path / "nul-text.bin").write_bytes(b"a\x00b")
    assert not fs.list_dir(limit=1).truncated
    with pytest.raises(FilesystemError) as error:
        fs.read_text("nul-text.bin", max_bytes=3)
    assert error.value.code == "fs/not-text"


@pytest.mark.asyncio
async def test_managed_start_stop_and_reload_get_fresh_view(tmp_path):
    from lamtools_core.plugin_system import PluginManifest, PluginRuntimeHandle
    from lamtools_core.plugin_system.lifecycle import start_plugin_backend, stop_plugin_backend
    from lamtools_core.plugin_system.services import ServiceError
    root = PluginContext(tmp_path)
    views = []
    handle = PluginRuntimeHandle(PluginManifest("example", "1", root=tmp_path), {"start": lambda ctx: views.append(ctx.filesystem)}, context=root.for_work_root(tmp_path))
    try:
        await start_plugin_backend(handle, root)
        assert views[0].stat().kind == "directory"
        await stop_plugin_backend(handle)
        with pytest.raises(ServiceError):
            views[0].stat()
        await start_plugin_backend(handle, root)
        assert views[1].stat().kind == "directory"
        with pytest.raises(ServiceError):
            views[0].list_dir()
    finally:
        await stop_plugin_backend(handle)
