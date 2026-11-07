"""user:“给我把 2 阶段做完，前端除外”+(实际隔离文件效果、原政策持久化/CAS和原Job清理，不以注册成功代替验收)。"""
import asyncio
import json

import pytest
from pathlib import Path

from .test_plugin_working_directory import env


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["resolve", "set"])
@pytest.mark.parametrize("change", ["session", "directory", "scope"])
async def test_policy_read_revalidates_bindings_before_publish_or_save(env, monkeypatch, operation, change):
    # user:“复用原宿主权威”+(政策读取等待后重新检查原会话/目录绑定，不能发布旧策略或写入已替换宿主)。
    from copy import copy
    from lamtools_core.plugin_system.sandbox_access import SandboxAccessError
    from lamtools_core.plugin_system.services import ServiceError
    ctx, store, _, _ = env
    api = ctx.sandbox_policy
    before = await store.get_readonly_revision("s")
    original = api._host._read
    entered, release = asyncio.Event(), asyncio.Event()
    async def gated(*args, **kwargs):
        result = await original(*args, **kwargs)
        entered.set()
        await release.wait()
        return result
    monkeypatch.setattr(api._host, "_read", gated)
    pending = asyncio.create_task(api.resolve("s") if operation == "resolve" else
        api.set("s", mode="workspace-write", expected_revision=before[1]))
    service = "session_data" if change == "session" else "working_directory"
    old_service = ctx.service(service)
    try:
        await asyncio.wait_for(entered.wait(), 3)
        if change == "scope":
            ctx._registration_scope.revoke()
        else:
            ctx.set_service(service, copy(old_service))
        release.set()
        with pytest.raises((SandboxAccessError, ServiceError)) as error:
            await pending
        assert error.value.code == ("service/scope-closed" if change == "scope" else "sandbox/host-changed")
        assert await store.get_readonly_revision("s") == before
        assert not ctx._registration_scope._calls
    finally:
        ctx.set_service(service, old_service)
        release.set()
        await asyncio.gather(pending, return_exceptions=True)


@pytest.mark.asyncio
async def test_policy_persists_with_original_session_revision_and_directory(env):
    ctx, store, _, root = env
    initial = await ctx.sandbox_policy.resolve("s")
    assert initial["mode"] == "read-only" and initial["workspace_root"] == str(root)
    saved = await ctx.sandbox_policy.set("s", mode="workspace-write", expected_revision=initial["revision"])
    from lamtools_core.plugin_system.sandbox_access import SandboxAccessError
    with pytest.raises(SandboxAccessError) as error:
        await ctx.sandbox_policy.set("s", mode="danger-full-access", expected_revision=initial["revision"])
    assert error.value.code == "sandbox/conflict"
    assert (await store.get_readonly("s")).metadata["project_id"] == "original"
    await ctx._registration_scope.dispose()
    ctx._begin_registration_scope("example", 2)
    assert (await ctx.sandbox_policy.resolve("s"))["mode"] == saved["mode"]
    directory = await ctx.working_directory.get("s")
    await ctx.working_directory.set("s", "one", expected_revision=directory.revision)
    assert (await ctx.sandbox_policy.resolve("s"))["workspace_root"] == str(root / "one")


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["read-only", "workspace-write"])
async def test_native_sandbox_restricts_real_file_effects_and_cleans_scratch(env, tmp_path, mode):
    ctx, _, _, root = env
    outside = tmp_path / "outside.txt"
    outside.write_text("unchanged")
    paths = [["inside",str(root / "inside.txt")],["outside",str(outside)]]
    source = 'const fs=require("node:fs");let r={};for(const[k,p]of '+json.dumps(paths)+'){try{fs.writeFileSync(p,"changed");r[k]=true}catch(e){r[k]=e.code}}console.log(JSON.stringify(r));'
    node = ctx.processes.resolve_executable("node.exe")
    result = await ctx.sandbox.run([str(node),"-e",source],session_id="s",mode=mode,timeout=15)
    assert result["enforcement"] == "partial" and result["confined"] and result["quiescent"]
    outcomes = json.loads(result["stdout"])
    assert outcomes["outside"] in {"EPERM","EACCES"} and outside.read_text() == "unchanged"
    assert outcomes["inside"] is True if mode == "workspace-write" else outcomes["inside"] in {"EPERM","EACCES"}
    assert not Path(result["scratch_directory"]).exists()


@pytest.mark.asyncio
async def test_missing_runtime_fails_closed_and_full_access_is_explicit(env, monkeypatch):
    from lamtools_core.plugin_system.sandbox_access import SandboxAccessError
    ctx, _, _, root = env
    api = ctx.sandbox
    monkeypatch.setattr(api, "_runtime", lambda: (_ for _ in ()).throw(SandboxAccessError("sandbox/unavailable", "missing")))
    with pytest.raises(SandboxAccessError):
        await api.run(["cmd.exe","/d","/c","echo forbidden>unexpected.txt"],session_id="s")
    assert not (root / "unexpected.txt").exists()
    result = await api.run(["cmd.exe","/d","/c","echo explicit>explicit.txt"],session_id="s",mode="danger-full-access")
    assert result["exit_code"] == 0 and not result["confined"] and result["enforcement"] == "none"
    assert (root / "explicit.txt").is_file()


@pytest.mark.asyncio
async def test_policy_hidden_parent_owner_isolation_and_revoke(env):
    from lamtools_core.plugin_system.services import ServiceError
    from lamtools_core.plugin_system.session_data import SessionDataError
    ctx, _, _, root = env
    first = await ctx.sandbox_policy.resolve("s")
    await ctx.sandbox_policy.set("s",mode="workspace-write",expected_revision=first["revision"])
    other = ctx.for_work_root(root)
    other._registration_scope = None
    other._begin_registration_scope("other",1)
    try:
        assert (await other.sandbox_policy.resolve("s"))["mode"] == "read-only"
        with pytest.raises(SessionDataError):
            await ctx.sandbox_policy.resolve("hidden")
        api = ctx.sandbox
        await ctx._registration_scope.dispose()
        with pytest.raises(ServiceError):
            await api.run(["cmd.exe","/c","exit 0"],session_id="s")
    finally:
        await other._registration_scope.dispose()


@pytest.mark.asyncio
async def test_cancel_real_confined_child_reclaims_job_and_temp_grants(env, monkeypatch):
    ctx, _, _, _ = env
    api = ctx.sandbox
    original = api._processes.spawn
    handles, scratch = [], []
    async def observed(argv, **kwargs):
        scratch.append(Path(argv[argv.index("--temp")+1]))
        handle = await original(argv, **kwargs)
        handles.append(handle)
        return handle
    monkeypatch.setattr(api._processes,"spawn",observed)
    node = ctx.processes.resolve_executable("node.exe")
    task = asyncio.create_task(api.run([str(node),"-e",'console.log("READY");setInterval(()=>{},1000)'],
                                      session_id="s",mode="workspace-write",timeout=15))
    async with asyncio.timeout(5):
        while not handles or b"READY" not in handles[0].read_output().stdout:
            await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert handles[0]._cleaned and not scratch[0].exists()


@pytest.mark.asyncio
async def test_cancel_policy_save_waits_for_original_commit(env, monkeypatch):
    ctx, store, _, _ = env
    state = await ctx.sandbox_policy.resolve("s")
    entered, release = asyncio.Event(),asyncio.Event()
    original = store.patch
    async def delayed(*a, **kw):
        entered.set()
        await release.wait()
        return await original(*a,**kw)
    monkeypatch.setattr(store,"patch",delayed)
    task = asyncio.create_task(ctx.sandbox_policy.set("s",mode="workspace-write",expected_revision=state["revision"]))
    await asyncio.wait_for(entered.wait(),3)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (await ctx.sandbox_policy.resolve("s"))["mode"] == "workspace-write"
