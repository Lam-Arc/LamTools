"""user:“继续”+(专用Git工具使用已固定的执行目录，目录变更不使已送审的调用转向另一仓库)。"""
import subprocess
from pathlib import Path

import pytest

from lamtools_core.tool import ToolCall
from .test_plugin_working_directory import env
from .test_main_execution_directory import box_for


def git(root, *args):
    result = subprocess.run(["git", "-c", "core.autocrlf=false", *args], cwd=root, capture_output=True, text=True, check=True)
    return result.stdout


def repository(root, name):
    git(root, "init", "--quiet")
    (root / "note.txt").write_text("base\n", encoding="utf-8")
    git(root, "add", "note.txt")
    (root / "note.txt").write_text(name + " changed\n", encoding="utf-8")
    (root / (name + "-only.txt")).write_text(name, encoding="utf-8")


@pytest.mark.asyncio
async def test_real_git_status_and_diff_select_current_repository_and_preserve_pending_target(env):
    ctx, _, _, project = env
    repository(project / "one", "one")
    repository(project / "two", "two")
    state = await ctx.working_directory.get("s")
    await ctx.working_directory.set("s", "one", expected_revision=state.revision)
    box = box_for(ctx, project)
    await box.refresh_execution_directory("s")
    pending_status = box.prepare_call(ToolCall("status-old", "git_status", {}))
    pending_diff = box.prepare_call(ToolCall("diff-old", "git_diff", {"path": "note.txt"}))
    assert pending_diff.arguments["cwd"] == str(project / "one")
    state = await ctx.working_directory.get("s")
    await ctx.working_directory.set("s", "two", expected_revision=state.revision)
    await box.refresh_execution_directory("s")
    status = await box.execute(box.prepare_approved_call(pending_status))
    difference = await box.execute(box.prepare_approved_call(pending_diff))
    assert status.status == difference.status == "ok"
    assert "one-only.txt" in status.content and "two-only.txt" not in status.content
    assert "+one changed" in difference.content and "+two changed" not in difference.content
    assert difference.metadata["cwd"] == str(project / "one")
    latest = await box.execute(box.prepare_approved_call(ToolCall("status-new", "git_status", {})))
    assert "two-only.txt" in latest.content and "one-only.txt" not in latest.content
    assert box.work_root == project


@pytest.mark.asyncio
@pytest.mark.parametrize("name,args", [
    ("git_status", {"cwd": ".."}),
    ("git_diff", {"cwd": "missing", "path": "note.txt"}),
    ("git_diff", {"path": ["invalid"]}),
    ("git_diff", {"path": "../outside"}),
])
async def test_invalid_git_cwd_and_path_are_rejected_before_any_process(tmp_path, name, args):
    from lamtools_core.tool.git_tools import make_git_status_handler, make_git_diff_handler
    async def forbidden(*args, **kwargs):
        pytest.fail("Invalid Git input must not start a process")
    handler = make_git_status_handler(tmp_path, command_timeout=10, run_subprocess=forbidden) if name == "git_status" else make_git_diff_handler(tmp_path, command_timeout=10, max_text_length=1024, run_subprocess=forbidden)
    result = await handler(ToolCall("invalid", name, args))
    assert result.status == "failed"
    assert result.error_code in {"git/invalid-cwd", "git/invalid-path"}


@pytest.mark.asyncio
async def test_bundled_git_handler_uses_same_directory_contract(env):
    from lamtools_core.tool import ToolSpec
    ctx, _, _, project = env
    repository(project / "one", "one")
    box = box_for(ctx, project)
    handler = box._bundled_plugin_handler(ToolSpec(name="git_status", description="Git", input_schema={}),
        command_timeout=10, max_text_length=1024, imagegen_config=None)
    result = await handler(ToolCall("bundled", "git_status", {"cwd": str(project / "one")}))
    assert result.status == "ok", result.error
    assert "one-only.txt" in result.content
    assert result.metadata["cwd"] == str(project / "one")


@pytest.mark.asyncio
async def test_missing_pinned_repository_does_not_fall_back_to_new_repository(env):
    ctx, _, _, project = env
    repository(project / "one", "one")
    repository(project / "two", "two")
    state = await ctx.working_directory.get("s")
    await ctx.working_directory.set("s", "one", expected_revision=state.revision)
    box = box_for(ctx, project)
    await box.refresh_execution_directory("s")
    pending = box.prepare_call(ToolCall("old", "git_status", {}))
    (project / "one").rename(project / "moved")
    state = await ctx.working_directory.get("s")
    await ctx.working_directory.set("s", "two", expected_revision=state.revision)
    await box.refresh_execution_directory("s")
    result = await box.execute(box.prepare_approved_call(pending))
    assert result.status == "failed" and result.error_code == "git/invalid-cwd"
    assert "two-only.txt" not in result.content
