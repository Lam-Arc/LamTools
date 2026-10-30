"""user:“继续，列好清单 逐项打勾”+(文本流按解码、资源和生命周期逐项验收，部分前缀不是完整成功)。"""
from __future__ import annotations

from pathlib import Path

import pytest

from lamtools_core.plugin_system import FilesystemError, PluginContext


def access(root):
    context = PluginContext(root)
    context._begin_registration_scope("example", 1)
    return context, context.filesystem


def test_stream_decodes_utf8_across_byte_boundaries_and_preserves_newlines(tmp_path):
    _, fs = access(tmp_path)
    content = "\ufeff你好🙂\r\nlast\n"
    (tmp_path / "text").write_bytes(content.encode("utf-8"))
    chunks = list(fs.stream_text("text", max_bytes=100, chunk_bytes=1))
    assert chunks and all(isinstance(chunk, str) and chunk for chunk in chunks)
    assert "".join(chunks) == content
    (tmp_path / "empty").write_bytes(b"")
    assert list(fs.stream_text("empty", max_bytes=1)) == []


@pytest.mark.parametrize("maximum,chunk", [(True, 1), (0, 1), (67108865, 1), ("1", 1), (10, 0), (10, True), (10, 65537)])
def test_stream_limits_checked_at_creation_before_path_access(tmp_path, maximum, chunk):
    _, fs = access(tmp_path)
    with pytest.raises(FilesystemError) as error:
        fs.stream_text("missing", max_bytes=maximum, chunk_bytes=chunk)
    assert error.value.code == "fs/invalid-limit"


def test_stream_large_file_and_rejects_over_budget_before_any_prefix(tmp_path):
    _, fs = access(tmp_path)
    raw = "hello你好\n".encode() * 150000
    (tmp_path / "large").write_bytes(raw)
    with pytest.raises(FilesystemError) as error:
        fs.stream_text("large", max_bytes=len(raw)-1)
    assert error.value.code == "fs/too-large"
    chunks = list(fs.stream_text("large", max_bytes=len(raw), chunk_bytes=65536))
    assert "".join(chunks).encode() == raw and len(chunks) > 1


@pytest.mark.parametrize("raw", [b"abc\xff", b"abc\x00", b"abc\xf0\x9f"])
def test_invalid_later_content_raises_after_prefix_not_false_completion(tmp_path, raw):
    _, fs = access(tmp_path)
    (tmp_path / "bad").write_bytes(raw)
    stream = fs.stream_text("bad", max_bytes=100, chunk_bytes=3)
    assert next(stream) == "abc"
    with pytest.raises(FilesystemError) as error:
        list(stream)
    assert error.value.code == "fs/not-text"


@pytest.mark.parametrize("change", ["rewrite", "replace", "truncate"])
def test_changed_file_is_detected_between_chunks(tmp_path, change):
    _, fs = access(tmp_path)
    file = tmp_path / "text"
    file.write_bytes(b"abcdef")
    stream = fs.stream_text("text", max_bytes=100, chunk_bytes=3)
    assert next(stream) == "abc"
    if change == "replace":
        replacement = tmp_path / "replacement"
        replacement.write_bytes(b"different contents")
        replacement.replace(file)
    else:
        file.write_bytes(b"x" if change == "truncate" else b"rewritten contents")
    with pytest.raises(FilesystemError) as error:
        list(stream)
    assert error.value.code == "fs/changed"


def test_file_handles_are_closed_before_yield_and_reads_are_chunk_bounded(tmp_path, monkeypatch):
    _, fs = access(tmp_path)
    (tmp_path / "text").write_bytes(b"abcdefghijkl")
    original = Path.open
    handles = []
    requests = []
    class Meter:
        def __init__(self, stream):
            self.stream = stream
            handles.append(stream)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.stream.close()
        def fileno(self):
            return self.stream.fileno()
        def seek(self, offset):
            return self.stream.seek(offset)
        def read(self, size):
            requests.append(size)
            assert 0 < size <= 3
            return self.stream.read(size)
    monkeypatch.setattr(Path, "open", lambda path, *args, **kwargs: Meter(original(path, *args, **kwargs)))
    stream = fs.stream_text("text", max_bytes=100, chunk_bytes=3)
    assert next(stream) == "abc"
    assert all(handle.closed for handle in handles)
    # 提前停止甚至不 close 生成器，也不能遗留文件句柄。
    assert requests == [3]


@pytest.mark.asyncio
async def test_stop_revokes_created_and_partially_consumed_streams(tmp_path):
    from lamtools_core.plugin_system.services import ServiceError
    context, fs = access(tmp_path)
    (tmp_path / "text").write_bytes(b"abcdef")
    active = fs.stream_text("text", max_bytes=100, chunk_bytes=3)
    pending = fs.stream_text("text", max_bytes=100)
    assert next(active) == "abc"
    await context._registration_scope.dispose()
    for stream in (active, pending):
        with pytest.raises(ServiceError):
            next(stream)


def test_stream_rejects_directory_and_outside_paths(tmp_path):
    _, fs = access(tmp_path)
    for path, code in [(".", "fs/not-file"), ("../outside", "fs/invalid-path"), ("missing", "fs/not-found")]:
        with pytest.raises(FilesystemError) as error:
            fs.stream_text(path, max_bytes=100)
        assert error.value.code == code


def test_windows_ctime_interface_difference_does_not_fake_content_change(tmp_path, monkeypatch):
    import os
    from types import SimpleNamespace
    _, fs = access(tmp_path)
    (tmp_path / "text").write_bytes(b"unchanged")
    original = os.fstat
    def different_ctime(fd):
        info = original(fd)
        return SimpleNamespace(st_dev=info.st_dev, st_ino=info.st_ino, st_size=info.st_size,
                               st_mtime_ns=info.st_mtime_ns, st_ctime_ns=info.st_ctime_ns + 1000000)
    monkeypatch.setattr(os, "fstat", different_ctime)
    assert "".join(fs.stream_text("text", max_bytes=100, chunk_bytes=3)) == "unchanged"


def test_change_after_last_chunk_is_checked_before_successful_exhaustion(tmp_path):
    _, fs = access(tmp_path)
    file = tmp_path / "text"
    file.write_bytes(b"abc")
    stream = fs.stream_text("text", max_bytes=100, chunk_bytes=3)
    assert next(stream) == "abc"
    file.write_bytes(b"changed after final chunk")
    with pytest.raises(FilesystemError) as error:
        next(stream)
    assert error.value.code == "fs/changed"
