"""user:“继续，无人值守模式，不要停下来”+(工作区变化复用受管Git进程，按NUL解析路径，拒绝借父仓库或环境变量读取其他项目)。"""
import os
import subprocess

import pytest

from lamtools_core.plugin_system import PluginContext


def git(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=True)
    return result.stdout


@pytest.fixture
def ctx(tmp_path):
    git(tmp_path, "init", "-q")
    context = PluginContext(tmp_path)
    context._begin_registration_scope("changes", 1)
    return context


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "nt", reason="Windows Job native process owner")
async def test_real_git_status_snapshots_parse_unicode_paths_and_detach_results(ctx):
    before = await ctx.workspace_changes.snapshot()
    assert before["items"] == []
    (ctx.work_root / "文件 name.txt").write_text("actual", encoding="utf8")
    after = await ctx.workspace_changes.snapshot()
    assert after["items"] == [{"path": "文件 name.txt", "status": "??"}]
    diff = await ctx.workspace_changes.compare_status(before)
    assert diff["added"] == after["items"]
    assert diff["snapshot"]["status_revision"] == after["status_revision"]
    await ctx._registration_scope.dispose()


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "nt", reason="Windows Job native process owner")
async def test_parent_repository_is_not_used_for_nested_project(ctx):
    child = ctx.work_root / "nested"
    child.mkdir()
    view = ctx.for_work_root(child)
    with pytest.raises(Exception) as error:
        await view.workspace_changes.snapshot()
    assert error.value.code == "workspace/repository-root-mismatch"
    await ctx._registration_scope.dispose()


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "nt", reason="Windows Job native process owner")
async def test_inherited_git_directory_does_not_redirect_queries(ctx, tmp_path, monkeypatch):
    outside = tmp_path / "other"
    outside.mkdir()
    git(outside, "init", "-q")
    monkeypatch.setenv("GIT_DIR", str(outside / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(outside))
    (ctx.work_root / "expected.txt").write_text("actual", encoding="utf8")
    result = await ctx.workspace_changes.snapshot()
    assert any(item["path"] == "expected.txt" for item in result["items"])
    api = ctx.workspace_changes
    await ctx._registration_scope.dispose()
    with pytest.raises(Exception):
        await api.snapshot()
