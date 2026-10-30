"""user:“继续”+(主代理工具与目录通知接通，路径送审前固定，项目身份和稳定提示前缀保留)。"""
import json

import pytest

from lamtools_core.prompt import PromptContext
from lamtools_core.runtime import RuntimeState
from lamtools_core.tool import ToolCall
from lamtools_core.tool.default_toolbox import CoreToolbox
from .test_plugin_working_directory import env
from .test_base_agent_prompt_translation import _isolated_kit


def box_for(ctx, project):
    from lamtools_core.app.plugin_working_directory import install_runtime_directory_source
    box = CoreToolbox(work_root=project, loaded_skill_roots=set(), approval_policy="auto", permission_preset="full_access")
    install_runtime_directory_source(box, ctx)
    return box


@pytest.mark.asyncio
async def test_main_file_targets_are_pinned_before_approval_and_do_not_retarget(env):
    ctx, _, _, project = env
    (project / "one" / "note.txt").write_text("one")
    (project / "two" / "note.txt").write_text("two")
    state = await ctx.working_directory.get("s")
    await ctx.working_directory.set("s", "one", expected_revision=state.revision)
    box = box_for(ctx, project)
    await box.refresh_execution_directory("s")
    call = box.prepare_call(ToolCall("read", "read_file", {"path": "note.txt"}))
    assert call.arguments["path"] == str(project / "one" / "note.txt")
    state = await ctx.working_directory.get("s")
    await ctx.working_directory.set("s", "two", expected_revision=state.revision)
    await box.refresh_execution_directory("s")
    approved = box.prepare_approved_call(call)
    assert approved.arguments["path"] == call.arguments["path"]
    assert "one" in (await box.execute(approved)).content
    current = box.prepare_approved_call(ToolCall("read-new", "read_file", {"path": "note.txt"}))
    assert "two" in (await box.execute(current)).content
    assert box.work_root == project


@pytest.mark.asyncio
async def test_directory_notices_append_without_replacing_system_prefix_and_deduplicate(env, monkeypatch):
    ctx, _, _, project = env
    box = box_for(ctx, project)
    kit = _isolated_kit(monkeypatch, project)
    kit.toolbox = box
    state = RuntimeState(session_id="s", metadata={"work_root": str(project)})
    request = await kit.build_model_request(state, PromptContext(session_id="s"))
    prefix = request.messages[0].content
    expected = "Current working directory: " + json.dumps(str(project), ensure_ascii=False) + "."
    assert any(expected in str(m.content) for m in request.messages[1:])
    again = await kit.build_model_request(state, PromptContext(session_id="s"))
    assert not any("Current working directory:" in str(m.content) for m in again.metadata.get("_runtime_context_delta", []))
    current = await ctx.working_directory.get("s")
    await ctx.working_directory.set("s", "one", expected_revision=current.revision)
    changed = await kit.build_model_request(state, PromptContext(session_id="s"))
    assert changed.messages[0].content == prefix
    expected = "Current working directory: " + json.dumps(str(project / "one"), ensure_ascii=False) + "."
    assert any(expected in str(m.content) for m in changed.metadata["_runtime_context_delta"])
    assert kit.work_root == project


@pytest.mark.asyncio
async def test_main_runtime_restores_missing_directory_and_refuses_missing_project(env, monkeypatch):
    from lamtools_core.plugin_system.working_directory import WorkingDirectoryError
    ctx, _, _, project = env
    current = await ctx.working_directory.get("s")
    await ctx.working_directory.set("s", "one", expected_revision=current.revision)
    box = box_for(ctx, project)
    assert await box.refresh_execution_directory("s") == str(project / "one")
    (project / "one").rmdir()
    assert await box.refresh_execution_directory("s") == str(project)
    assert (await ctx.working_directory.get("s")).path == str(project)
    project.rename(project.with_name("moved"))
    kit = _isolated_kit(monkeypatch, project)
    kit.toolbox = box
    with pytest.raises(WorkingDirectoryError):
        await kit.build_model_request(RuntimeState(session_id="s"), PromptContext(session_id="s"))


@pytest.mark.asyncio
async def test_command_cwd_is_explicit_and_remains_fixed_after_directory_change(env):
    ctx, _, _, project = env
    current = await ctx.working_directory.get("s")
    await ctx.working_directory.set("s", "one", expected_revision=current.revision)
    box = box_for(ctx, project)
    await box.refresh_execution_directory("s")
    call = box.prepare_call(ToolCall("cmd", "run_command", {"command": "echo example"}))
    assert call.arguments["cwd"] == str(project / "one")
    current = await ctx.working_directory.get("s")
    await ctx.working_directory.set("s", "two", expected_revision=current.revision)
    await box.refresh_execution_directory("s")
    assert box.prepare_approved_call(call).arguments["cwd"] == str(project / "one")


@pytest.mark.asyncio
async def test_real_command_runs_in_selected_directory_and_invalid_cwd_does_not_start(env, monkeypatch):
    import os
    import shutil
    from lamtools_core.tool import command_tools, command_runner
    if os.name != "nt":
        pytest.skip("Desktop native PowerShell acceptance")
    executable = shutil.which("pwsh.exe") or shutil.which("powershell.exe")
    assert executable
    shell = command_runner.CommandShell(name="Test PowerShell", executable=executable,
                                         kind="pwsh" if "pwsh" in executable.lower() else "powershell")
    monkeypatch.setattr(command_tools, "resolve_command_shell", lambda: shell)
    ctx, _, _, project = env
    current = await ctx.working_directory.get("s")
    await ctx.working_directory.set("s", "one", expected_revision=current.revision)
    box = box_for(ctx, project)
    await box.refresh_execution_directory("s")
    call = box.prepare_approved_call(ToolCall("cmd-real", "run_command", {"command": "[Console]::Out.Write((Get-Location).Path)", "timeout": 10}))
    current = await ctx.working_directory.get("s")
    await ctx.working_directory.set("s", "two", expected_revision=current.revision)
    await box.refresh_execution_directory("s")
    call = box.prepare_approved_call(call)
    result = await box.execute(call)
    assert result.status == "ok", result.error
    assert str(project / "one") in result.content
    async def forbidden(*args, **kwargs):
        pytest.fail("Invalid cwd must not start a process")
    monkeypatch.setattr(command_tools, "_run_subprocess", forbidden)
    bad = box.prepare_approved_call(ToolCall("bad", "run_command", {"command": "echo bad", "cwd": str(project.parent)}))
    assert (await box.execute(bad)).error_code == "command/invalid-cwd"


@pytest.mark.asyncio
async def test_real_runtime_toolbox_factory_installs_directory_source(env):
    from lamtools_core.app.default_agent import _build_core_runtime_toolbox, _close_mcp_registry
    ctx, _, sessions, project = env
    catalog = sessions._context().operations
    catalog.plugin_context = ctx
    box, registry = await _build_core_runtime_toolbox(work_root=project,
        plugin_assembly={"plugin_context": ctx, "data_dir": ctx.data_dir},
        operation_catalog=catalog, approval_policy="auto_approve", permission_preset="full_access")
    try:
        current = await ctx.working_directory.get("s")
        await ctx.working_directory.set("s", "one", expected_revision=current.revision)
        assert await box.refresh_execution_directory("s") == str(project / "one")
        assert box.work_root == project
    finally:
        await _close_mcp_registry(registry)


@pytest.mark.asyncio
async def test_subagent_without_catalog_row_keeps_native_project_directory(env):
    ctx, _, _, project = env
    box = box_for(ctx, project)
    assert await box.refresh_execution_directory("s:sub:worker") is None
    assert box.work_root == project


@pytest.mark.asyncio
async def test_directory_snapshot_after_compaction_and_actual_file_write_follow_selected_directory(env, monkeypatch):
    ctx, _, _, project = env
    current = await ctx.working_directory.get("s")
    await ctx.working_directory.set("s", "one", expected_revision=current.revision)
    box = box_for(ctx, project)
    kit = _isolated_kit(monkeypatch, project)
    kit.toolbox = box
    state = RuntimeState(session_id="s")
    await kit.build_model_request(state, PromptContext(session_id="s"))
    snapshot = kit.emit_runtime_context_snapshot(state)
    assert snapshot is not None
    assert "Current working directory: " + json.dumps(str(project / "one")) + "." in snapshot.content
    call = box.prepare_approved_call(ToolCall("write", "write_file", {"path": "new.txt", "content": "created here"}))
    result = await box.execute(call)
    assert result.status == "ok", result.error
    assert (project / "one" / "new.txt").read_text() == "created here"
    assert not (project / "new.txt").exists()


@pytest.mark.asyncio
async def test_factory_does_not_recreate_deleted_session_project(env):
    from lamtools_core.app.default_agent import _build_core_runtime_toolbox
    from lamtools_core.plugin_system.working_directory import WorkingDirectoryError
    ctx, _, sessions, project = env
    catalog = sessions._context().operations
    catalog.plugin_context = ctx
    project.rename(project.with_name("moved"))
    with pytest.raises(WorkingDirectoryError):
        await _build_core_runtime_toolbox(work_root=project,
            plugin_assembly={"plugin_context": ctx, "data_dir": ctx.data_dir},
            operation_catalog=catalog, approval_policy="auto_approve")
    assert not project.exists()


@pytest.mark.asyncio
async def test_automatic_recovery_does_not_overwrite_concurrent_directory_selection(env, monkeypatch):
    ctx, store, _, project = env
    current = await ctx.working_directory.get("s")
    await ctx.working_directory.set("s", "one", expected_revision=current.revision)
    (project / "one").rmdir()
    original = store.patch
    changed = False
    async def race(session_id, **kwargs):
        nonlocal changed
        if not changed and kwargs.get("metadata", {}).get("execution_directory") == str(project):
            changed = True
            record, revision = await store.get_readonly_revision(session_id)
            await original(session_id, metadata={**record.metadata, "execution_directory": str(project / "two")}, expected_revision=revision)
        return await original(session_id, **kwargs)
    monkeypatch.setattr(store, "patch", race)
    assert await box_for(ctx, project).refresh_execution_directory("s") == str(project / "two")
    assert (await ctx.working_directory.get("s")).path == str(project / "two")
