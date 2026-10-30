"""user:“继续，把 2 阶段都做完”+(本地路径、文件 URI 和包含判断必须有真实路径证据，不假装远程执行世界)。"""
import pytest
from lamtools_core.plugin_system import PluginContext, FilesystemError


def test_local_target_resolution_process_path_uri_and_containment(tmp_path):
    ctx = PluginContext(tmp_path)
    ctx._begin_registration_scope("example", 1)
    fs = ctx.filesystem
    (tmp_path / "中文 file.txt").write_text("x")
    target = fs.resolve("中文 file.txt")
    assert target == (tmp_path / "中文 file.txt").resolve()
    assert fs.process_path(target) == str(target)
    assert fs.file_url(target) == target.as_uri()
    assert fs.contains(tmp_path, target)
    assert not fs.contains(tmp_path, tmp_path.parent)
    assert fs.process_path_from_host_path(target) == str(target)
    assert fs.process_path_from_host_path(tmp_path.parent) is None


def test_absent_final_target_is_resolvable_but_not_a_grant_or_mount(tmp_path):
    ctx = PluginContext(tmp_path)
    ctx._begin_registration_scope("example", 1)
    target = ctx.filesystem.resolve("not-created")
    assert target == tmp_path / "not-created" and not target.exists()
    with pytest.raises(FilesystemError):
        ctx.filesystem.resolve("../outside")
    with pytest.raises(FilesystemError):
        ctx.filesystem.process_path_from_host_path("relative")
