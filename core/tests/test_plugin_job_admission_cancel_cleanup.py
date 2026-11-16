"""user:“建立真实请求、错误、作用域、取消/流和清理验收”+(作业观察取消等待原会话准入清理)。"""
import asyncio

import pytest

from .test_plugin_working_directory import env


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["list", "read", "follow", "watch_list", "kill"])
async def test_repeated_cancel_waits_for_real_admission_cleanup(env, monkeypatch, method):
    ctx, _, _, _ = env
    gate, entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event(), asyncio.Event()
    async def work(job): await gate.wait()
    job = ctx.jobs.start("task", "owned", work, session_id="s")
    host = ctx.require_service("working_directory")
    async def blocked(*args, **kwargs):
        entered.set()
        try: await asyncio.Event().wait()
        finally: cleaning.set(); await release.wait()
    monkeypatch.setattr(host, "call", blocked)
    api = ctx.job_controller
    stream = None
    if method == "list": call = api.list("s")
    elif method == "read": call = api.read("s", job.id)
    elif method == "kill": call = api.kill("s", job.id)
    elif method == "follow":
        stream = api.follow("s", job.id); call = anext(stream)
    else:
        stream = api.watch_list("s"); call = anext(stream)
    task = asyncio.create_task(call)
    try:
        await entered.wait(); task.cancel(); await cleaning.wait(); task.cancel(); await asyncio.sleep(0)
        assert not task.done() and not ctx._registration_scope._idle.is_set()
        assert not job._task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError): await task
        if stream is not None: await stream.aclose()
        assert ctx._registration_scope._idle.is_set() and not job._task.done()
    finally:
        release.set(); gate.set(); await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_normal_observation_still_reads_real_job(env):
    ctx, _, _, _ = env
    entered, release = asyncio.Event(), asyncio.Event()
    async def work(job):
        job.emit("stdout", b"real-output"); entered.set(); await release.wait()
    job = ctx.jobs.start("task", "owned", work, session_id="s")
    try:
        await entered.wait()
        assert job.id in {row.id for row in await ctx.job_controller.list("s")}
        assert (await ctx.job_controller.read("s", job.id)).stdout == b"real-output"
    finally:
        release.set()


@pytest.mark.asyncio
async def test_remote_cancel_waits_for_original_admission_cleanup(env, monkeypatch, tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
    ctx, _, _, _ = env
    process_gate, entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event(), asyncio.Event()
    async def work(job): await process_gate.wait()
    job = ctx.jobs.start("task", "owned", work, session_id="s")
    host, catalog, old = _host(tmp_path); configure(host)
    ctx._secret_store = old._secret_store; host.backend_manager.context = ctx
    (host.get("hook-demo").root / "ops.py").write_text(
        "from lamtools_core.app.operation_catalog import OperationResult\n"
        "async def echo(request, *, context):\n"
        "    return OperationResult(request.name, await context.job_controller.list('s'))\n", encoding="utf8")
    catalog.unregister_owner("plugin:hook-demo"); register_plugin_operations(catalog, host)
    async def blocked(*args, **kwargs):
        entered.set()
        try: await asyncio.Event().wait()
        finally: cleaning.set(); await release.wait()
    monkeypatch.setattr(ctx.require_service("working_directory"), "call", blocked)
    app = FastAPI(); app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        task = asyncio.create_task(client.post("/plugin-remote/hook-demo/demo/echo", json={"args": {"text": "x"}},
            headers={"x-plugin-token": plugin_http_token(host, "hook-demo")}))
        try:
            await entered.wait(); task.cancel(); await cleaning.wait(); task.cancel(); await asyncio.sleep(0)
            assert not task.done() and not ctx._registration_scope._idle.is_set() and not job._task.done()
            release.set()
            with pytest.raises(asyncio.CancelledError): await task
            assert ctx._registration_scope._idle.is_set() and not job._task.done()
        finally:
            release.set(); process_gate.set(); await asyncio.gather(task, return_exceptions=True)


def test_migration_mentions_job_admission_cleanup(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root = source(tmp_path, {"index.ts": "export function apply(ctx) { ctx.remote.job.follow(); }"})
    export_port(root, tmp_path / "ported")
    assert "作业会话准入取消" in (tmp_path / "ported" / "PORTING.md").read_text(encoding="utf8")
