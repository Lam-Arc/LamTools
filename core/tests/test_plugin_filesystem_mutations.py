"""user:“继续，把 2 阶段都做完”+(文件修改必须先验收缺失/版本冲突、原子发布、字面编辑与失败回执，不以只读子集代替)。"""
from concurrent.futures import ThreadPoolExecutor

import pytest

from lamtools_core.plugin_system import FilesystemError, PluginContext


def access(root, *, data_dir=True, owner="example"):
    ctx = PluginContext(root, data_dir=root / "host-data" if data_dir else None)
    ctx._begin_registration_scope(owner, 1)
    return ctx, ctx.filesystem


def test_observe_absent_create_then_replace_with_exact_revision(tmp_path):
    _, fs = access(tmp_path)
    before = fs.observe("new.txt")
    assert not before.exists and before.revision is None
    result = fs.write_text("new.txt", "hello\r\n你好", expected_revision=None)
    assert result.written and result.bytes_written == len("hello\r\n你好".encode())
    current = fs.observe("new.txt")
    assert current.exists and current.revision == result.revision
    assert fs.read_text("new.txt", max_bytes=100) == "hello\r\n你好"
    same = fs.write_text("new.txt", "hello\r\n你好", expected_revision=current.revision)
    assert not same.written and same.revision == current.revision
    assert fs.write_text("new.txt", "changed", expected_revision=current.revision).revision != current.revision


def test_revision_conflict_and_absent_guard_never_overwrite(tmp_path):
    _, fs = access(tmp_path)
    first = fs.write_text("file", "first", expected_revision=None)
    fs.write_text("file", "second", expected_revision=first.revision)
    for revision in (None, first.revision):
        with pytest.raises(FilesystemError) as error:
            fs.write_text("file", "lost", expected_revision=revision)
        assert error.value.code == "fs/conflict"
    assert (tmp_path / "file").read_text() == "second"


def test_literal_edit_requires_unambiguous_match_unless_replace_all(tmp_path):
    _, fs = access(tmp_path)
    version = fs.write_text("file", "one one\r\n你好", expected_revision=None).revision
    for search, code in [("one", "fs/ambiguous-edit"), ("absent", "fs/no-match")]:
        with pytest.raises(FilesystemError) as error:
            fs.edit_text("file", search, "two", expected_revision=version)
        assert error.value.code == code
    result = fs.edit_text("file", "one", "two", expected_revision=version, replace_all=True)
    assert result.replacements == 2 and result.written
    assert (tmp_path / "file").read_bytes() == "two two\r\n你好".encode()


@pytest.mark.parametrize("content", ["bad\x00text", "x" * 1048577, b"bytes"], ids=["nul", "over-limit", "bytes"])
def test_invalid_text_never_creates_destination(tmp_path, content):
    _, fs = access(tmp_path)
    with pytest.raises(FilesystemError) as error:
        fs.write_text("file", content, expected_revision=None)
    assert error.value.code == "fs/not-text" or error.value.code == "fs/too-large"
    assert not (tmp_path / "file").exists()


def test_binary_existing_content_cannot_be_replaced_as_text(tmp_path):
    _, fs = access(tmp_path)
    (tmp_path / "binary").write_bytes(b"\xff")
    snapshot = fs.observe("binary")
    with pytest.raises(FilesystemError) as error:
        fs.write_text("binary", "text", expected_revision=snapshot.revision)
    assert error.value.code == "fs/not-text"
    assert (tmp_path / "binary").read_bytes() == b"\xff"


def test_cooperating_owners_share_one_path_lock_and_only_one_revision_wins(tmp_path):
    _, first = access(tmp_path, owner="one")
    _, second = access(tmp_path, owner="two")
    revision = first.write_text("shared", "old", expected_revision=None).revision
    def write(pair):
        fs, content = pair
        try:
            return fs.write_text("shared", content, expected_revision=revision)
        except FilesystemError as error:
            return error
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, [(first, "one"), (second, "two")]))
    assert sum(not isinstance(item, FilesystemError) for item in results) == 1
    assert [item.code for item in results if isinstance(item, FilesystemError)] == ["fs/conflict"]


def test_publish_failure_and_unknown_acknowledgement_are_explicit(tmp_path, monkeypatch):
    import lamtools_core.plugin_system.filesystem_access as implementation
    _, fs = access(tmp_path)
    original = implementation.atomic_write_bytes
    version = fs.write_text("file", "old", expected_revision=None).revision
    def fail(path, payload):
        raise OSError("failed before publish")
    monkeypatch.setattr(implementation, "atomic_write_bytes", fail)
    with pytest.raises(FilesystemError) as error:
        fs.write_text("file", "new", expected_revision=version)
    assert error.value.code == "fs/write-failed" and error.value.may_have_changed
    assert (tmp_path / "file").read_text() == "old"
    def unknown(path, payload):
        original(path, payload)
        raise OSError("acknowledgement lost")
    monkeypatch.setattr(implementation, "atomic_write_bytes", unknown)
    with pytest.raises(FilesystemError) as error:
        fs.write_text("file", "new", expected_revision=version)
    assert error.value.may_have_changed
    assert fs.observe("file").revision != version


@pytest.mark.asyncio
async def test_mutations_preserve_path_epoch_and_host_store_boundaries(tmp_path):
    _, readonly = access(tmp_path, data_dir=False)
    with pytest.raises(FilesystemError) as error:
        readonly.write_text("file", "x", expected_revision=None)
    assert error.value.code == "fs/unavailable"
    ctx, fs = access(tmp_path)
    with pytest.raises(FilesystemError):
        fs.write_text("../outside", "x", expected_revision=None)
    with pytest.raises(FilesystemError):
        fs.write_text("missing-parent/file", "x", expected_revision=None)
    await ctx._registration_scope.dispose()
    from lamtools_core.plugin_system.services import ServiceError
    with pytest.raises(ServiceError):
        fs.write_text("file", "x", expected_revision=None)
