"""user:“写好清单，逐项打勾完成，不要出错”+(验收真正有界的字节窗口及不跟随最终链接的元数据，不提前宣称完整文件系统)。"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

from lamtools_core.plugin_system import FilesystemError, PluginContext


def access(root):
    ctx = PluginContext(root)
    ctx._begin_registration_scope("example", 1)
    return ctx, ctx.filesystem


def test_range_reads_raw_bytes_and_handles_eof_and_zero_length(tmp_path):
    _, fs = access(tmp_path)
    (tmp_path / "bytes").write_bytes(b"a\xff\x00xyz")
    assert fs.read_byte_range("bytes", offset=1, length=3) == b"\xff\x00x"
    assert fs.read_byte_range("bytes", offset=4, length=20) == b"yz"
    assert fs.read_byte_range("bytes", offset=6, length=1) == b""
    assert fs.read_byte_range("bytes", offset=100, length=2) == b""
    assert fs.read_byte_range("bytes", offset=0, length=0) == b""
    assert fs.read_byte_range("bytes", offset=2**63-1, length=0) == b""


def test_large_file_window_does_not_load_the_prefix_or_whole_file(tmp_path, monkeypatch):
    _, fs = access(tmp_path)
    file = tmp_path / "large.bin"
    position = 8 * 1024 * 1024
    with file.open("wb") as stream:
        stream.seek(position)
        stream.write(b"target")
    original_open = Path.open
    calls = []
    class Meter:
        def __init__(self, stream):
            self.stream = stream
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.stream.close()
        def fileno(self):
            return self.stream.fileno()
        def seek(self, offset):
            calls.append(("seek", offset))
            return self.stream.seek(offset)
        def read(self, length):
            calls.append(("read", length))
            assert length == 6
            return self.stream.read(length)
    def counted(path, *args, **kwargs):
        return Meter(original_open(path, *args, **kwargs))
    monkeypatch.setattr(Path, "open", counted)
    assert fs.read_byte_range("large.bin", offset=position, length=6) == b"target"
    assert calls == [("seek", position), ("read", 6)]


@pytest.mark.parametrize("offset,length", [(-1, 1), (True, 1), (1.5, 1), ("0", 1), (0, -1), (0, True), (0, 1048577), (2**63, 0), (2**63-1, 1)])
def test_bad_ranges_fail_before_opening_path(tmp_path, offset, length):
    _, fs = access(tmp_path)
    with pytest.raises(FilesystemError) as error:
        fs.read_byte_range("missing", offset=offset, length=length)
    assert error.value.code == "fs/invalid-range"


def test_zero_length_still_checks_file_existence_kind_and_path(tmp_path):
    _, fs = access(tmp_path)
    for path, code in [("missing", "fs/not-found"), (".", "fs/not-file"), ("../outside", "fs/invalid-path")]:
        with pytest.raises(FilesystemError) as error:
            fs.read_byte_range(path, offset=0, length=0)
        assert error.value.code == code


def test_lstat_regular_file_directory_and_missing(tmp_path):
    _, fs = access(tmp_path)
    (tmp_path / "regular").write_bytes(b"abc")
    info = fs.lstat("regular")
    assert info.kind == "file" and info.size == 3
    assert fs.lstat().kind == "directory"
    with pytest.raises(FilesystemError) as error:
        fs.lstat("missing")
    assert error.value.code == "fs/not-found"


def test_final_link_metadata_does_not_follow_outside_target_or_allow_traversal(tmp_path):
    _, fs = access(tmp_path)
    outside = tmp_path.parent / (tmp_path.name + "-target")
    outside.mkdir()
    link = tmp_path / "link"
    if os.name == "nt":
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        assert result.returncode == 0
    else:
        link.symlink_to(outside, target_is_directory=True)
    assert fs.lstat("link").kind == "link"
    for call in [lambda: fs.lstat("link/child"), lambda: fs.stat("link"), lambda: fs.read_byte_range("link", offset=0, length=1)]:
        with pytest.raises(FilesystemError) as error:
            call()
        assert error.value.code == "fs/link-not-supported"
    outside.rmdir()
    assert fs.lstat("link").kind == "link"


@pytest.mark.asyncio
async def test_range_and_lstat_keep_root_and_epoch_boundaries(tmp_path):
    from lamtools_core.plugin_system.services import ServiceError
    ctx, fs = access(tmp_path)
    (tmp_path / "value").write_bytes(b"root")
    ctx.work_root = tmp_path / "elsewhere"
    assert fs.read_byte_range("value", offset=0, length=4) == b"root"
    await ctx._registration_scope.dispose()
    for call in [lambda: fs.lstat(), lambda: fs.read_byte_range("value", offset=0, length=1)]:
        with pytest.raises(ServiceError):
            call()


def test_lstat_never_allows_pinned_root_replaced_by_link(tmp_path):
    _, fs = access(tmp_path)
    target = tmp_path.parent / (tmp_path.name + "-root-target")
    target.mkdir()
    tmp_path.rmdir()
    if os.name == "nt":
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(tmp_path), str(target)], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        assert result.returncode == 0
    else:
        tmp_path.symlink_to(target, target_is_directory=True)
    with pytest.raises(FilesystemError) as error:
        fs.lstat()
    assert error.value.code == "fs/link-not-supported"
