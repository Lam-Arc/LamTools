"""user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(作业控制复用插件作业并按可见会话隔离)。"""
import asyncio

import pytest
from .test_plugin_working_directory import env
from lamtools_core.session import SessionRecord


@pytest.mark.asyncio
async def test_visible_session_sees_own_and_unowned_jobs_but_not_other_session(env):
    ctx, store, _, root = env
    await store.create(SessionRecord("s2", "core", "Second", "idle", metadata={"work_root": str(root)}))
    gate = asyncio.Event()
    async def work(job):
        job.emit("stdout", b"actual")
        await gate.wait()
        return {"ok": True}
    own = ctx.jobs.start("task", "own", work, session_id="s")
    foreign = ctx.jobs.start("task", "foreign", work, session_id="s2")
    common = ctx.jobs.start("task", "common", work)
    try:
        await asyncio.sleep(0)
        values = await ctx.job_controller.list("s")
        assert {item.id for item in values} == {own.id, common.id}
        assert (await ctx.job_controller.read("s", own.id)).stdout == b"actual"
        assert (await ctx.job_controller.read("s", own.id)).stdout == b"actual"
        with pytest.raises(RuntimeError) as error: await ctx.job_controller.read("s", foreign.id)
        assert error.value.code == "job/not-found"
        with pytest.raises(RuntimeError): await ctx.job_controller.kill("s", foreign.id)
        with pytest.raises(RuntimeError): await ctx.job_controller.list("hidden")
        assert not foreign._task.done()
    finally:
        gate.set()


@pytest.mark.asyncio
async def test_kill_only_owned_visible_job_and_awaits_actual_cleanup(env):
    ctx, _, _, _ = env
    entered, cleaned = asyncio.Event(), asyncio.Event()
    async def work(job):
        entered.set()
        try: await asyncio.Event().wait()
        finally: cleaned.set()
    record = ctx.jobs.start("task", "owned", work, session_id="s")
    await entered.wait()
    result = await ctx.job_controller.kill("s", record.id)
    assert result.status == "killed" and cleaned.is_set() and record._task.done()


@pytest.mark.asyncio
async def test_repeated_kill_caller_cancel_waits_for_job_cleanup(env):
    ctx, _, _, _ = env
    entered, closing, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    async def work(job):
        entered.set()
        try: await asyncio.Event().wait()
        finally:
            closing.set()
            await release.wait()
    record = ctx.jobs.start("task", "owned", work, session_id="s")
    await entered.wait()
    caller = asyncio.create_task(ctx.job_controller.kill("s", record.id))
    try:
        await closing.wait()
        caller.cancel()
        await asyncio.sleep(0)
        caller.cancel()
        await asyncio.sleep(0)
        assert not caller.done() and not record._task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError): await caller
        assert record._task.done()
    finally:
        release.set()
        await asyncio.gather(caller, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["host", "scope", "root", "cancel"])
async def test_admission_changes_block_old_job_observation(env, monkeypatch, tmp_path, change):
    ctx, _, _, _ = env
    host = ctx.require_service("working_directory")
    original = host.call
    entered, release = asyncio.Event(), asyncio.Event()
    async def gated(*args, **kwargs):
        value = await original(*args, **kwargs)
        entered.set()
        await release.wait()
        return value
    monkeypatch.setattr(host, "call", gated)
    api = ctx.job_controller
    task = asyncio.create_task(api.list("s"))
    try:
        await entered.wait()
        if change == "host": ctx.set_service("working_directory", object())
        elif change == "scope": ctx._registration_scope.revoke()
        elif change == "root": ctx.work_root = tmp_path / "different"
        else: task.cancel()
        release.set()
        if change == "cancel":
            with pytest.raises(asyncio.CancelledError): await task
        else:
            with pytest.raises((RuntimeError, ValueError)): await task
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_session_job_snapshot_crosses_actual_http(env, tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
    ctx, _, _, _ = env
    gate = asyncio.Event()
    async def work(job): await gate.wait()
    record = ctx.jobs.start("task", "HTTP job", work, session_id="s")
    host, catalog, original_context = _host(tmp_path)
    configure(host)
    ctx._secret_store = original_context._secret_store
    host.backend_manager.context = ctx
    (host.get("hook-demo").root / "ops.py").write_text(
        "async def echo(request, *, context):\n"
        "    return {'jobs': await context.job_controller.list(request.payload['body']['text'])}\n", encoding="utf8")
    catalog.unregister_owner("plugin:hook-demo")
    register_plugin_operations(catalog, host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            headers = {"x-plugin-token": plugin_http_token(host, "hook-demo")}
            response = await client.post("/plugin-remote/hook-demo/demo/echo", json={"args": {"text": "s"}}, headers=headers)
            hidden = await client.post("/plugin-remote/hook-demo/demo/echo", json={"args": {"text": "hidden"}}, headers=headers)
        assert response.status_code == 200 and response.json()["payload"]["jobs"][0]["id"] == record.id
        assert hidden.status_code == 400
    finally:
        gate.set()


@pytest.mark.asyncio
async def test_session_job_binary_output_crosses_multipart_http_without_consuming(env, tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from .test_plugin_remote_binary import set_encoding, decode_parts
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
    ctx, _, _, _ = env
    started, gate = asyncio.Event(), asyncio.Event()
    async def work(job):
        job.emit("stdout", b"\x00\xffjob")
        started.set()
        await gate.wait()
    record = ctx.jobs.start("task", "binary", work, session_id="s")
    await started.wait()
    host, catalog, original_context = _host(tmp_path)
    configure(host)
    set_encoding(host, "multipart")
    ctx._secret_store = original_context._secret_store
    host.backend_manager.context = ctx
    (host.get("hook-demo").root / "ops.py").write_text(
        "async def echo(request, *, context):\n"
        "    return {'output': await context.job_controller.read('s', request.payload['body']['text'])}\n", encoding="utf8")
    catalog.unregister_owner("plugin:hook-demo")
    register_plugin_operations(catalog, host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/plugin-remote/hook-demo/demo/echo", json={"args": {"text": record.id}},
                headers={"x-plugin-token": plugin_http_token(host, "hook-demo")})
        metadata, parts = decode_parts(response)
        stdout = next(row for row in metadata["attachments"] if row["path"] == ["payload", "output", "stdout"])
        assert parts[stdout["part"]] == b"\x00\xffjob"
        assert (await ctx.job_controller.read("s", record.id)).stdout == b"\x00\xffjob"
    finally:
        gate.set()


def test_job_handoff_mentions_actual_narrow_scope(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root = source(tmp_path, {"index.ts": "export function apply(ctx) { ctx.remote.job.list(); }"})
    report = export_port(root, tmp_path / "ported")
    item = next(row for row in report["remotes"] if row["name"] == "job.list")
    assert item["suggestedContract"] == "context.job_controller.list"
    assert "插件" in item["difference"] and report["runtimeVerified"] is False
