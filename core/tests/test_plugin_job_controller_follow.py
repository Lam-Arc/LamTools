"""user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(作业跟随复用原非消耗输出并在关闭时停止轮询)。"""
import asyncio
import base64

import pytest
from .test_plugin_working_directory import env


@pytest.mark.asyncio
async def test_follow_actual_job_has_open_output_terminal_and_nonconsuming_bytes(env):
    ctx, _, _, _ = env
    started, release = asyncio.Event(), asyncio.Event()
    async def work(job):
        job.emit("stdout", b"\x00\xffone")
        job.emit("stderr", b"two")
        started.set()
        await release.wait()
        return {"ok": True}
    job = ctx.jobs.start("task", "follow", work, session_id="s")
    await started.wait()
    stream = ctx.job_controller.follow("s", job.id, interval=0.01)
    try:
        opened = await anext(stream)
        assert opened["kind"] == "opened" and opened["job"].id == job.id
        frame = await anext(stream)
        assert base64.b64decode(frame["stdout_base64"]) == b"\x00\xffone"
        assert base64.b64decode(frame["stderr_base64"]) == b"two"
        assert (await ctx.job_controller.read("s", job.id)).stdout == b"\x00\xffone"
        release.set()
        terminal = await asyncio.wait_for(anext(stream), 3)
        assert terminal["kind"] == "status" and terminal["job"].status == "completed"
        with pytest.raises(StopAsyncIteration): await anext(stream)
    finally:
        release.set()
        await stream.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("interval", [0, 3, True, float("nan"), "slow"])
async def test_invalid_poll_interval_fails_before_session_access(env, monkeypatch, interval):
    ctx, _, _, _ = env
    host = ctx.require_service("working_directory")
    def forbidden(*args, **kwargs): pytest.fail("invalid interval must not enter host")
    monkeypatch.setattr(host, "for_scope", forbidden)
    with pytest.raises(ValueError): await anext(ctx.job_controller.follow("s", "unused", interval=interval))


@pytest.mark.asyncio
async def test_foreign_job_is_not_observable_and_cancelling_poll_keeps_job(env):
    ctx, _, _, _ = env
    gate = asyncio.Event()
    async def work(job): await gate.wait()
    foreign = ctx.jobs.start("task", "foreign", work, session_id="hidden")
    own = ctx.jobs.start("task", "own", work, session_id="s")
    try:
        with pytest.raises(RuntimeError): await anext(ctx.job_controller.follow("s", foreign.id, interval=0.01))
        stream = ctx.job_controller.follow("s", own.id, interval=0.01)
        assert (await anext(stream))["kind"] == "opened"
        pending = asyncio.create_task(anext(stream))
        await asyncio.sleep(0.02)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError): await pending
        await stream.aclose()
        assert not own._task.done() and not foreign._task.done()
    finally:
        gate.set()


@pytest.mark.asyncio
async def test_resume_and_lost_output_preserve_original_byte_offsets(env):
    ctx, _, _, _ = env
    started, gate = asyncio.Event(), asyncio.Event()
    async def work(job):
        job.emit("stdout", b"abcdef")
        started.set()
        await gate.wait()
    job = ctx.jobs.start("task", "bounded", work, session_id="s", max_output_bytes=3)
    await started.wait()
    stream = ctx.job_controller.follow("s", job.id, stdout_after=1, interval=0.01)
    try:
        await anext(stream)
        frame = await anext(stream)
        assert base64.b64decode(frame["stdout_base64"]) == b"def"
        assert frame["stdout_offset"] == 6 and frame["stdout_lost"] is True
    finally:
        await stream.aclose()
        gate.set()


@pytest.mark.asyncio
async def test_changed_session_label_is_rechecked_during_follow(env):
    ctx, _, _, _ = env
    gate = asyncio.Event()
    async def work(job): await gate.wait()
    job = ctx.jobs.start("task", "changing", work, session_id="s")
    stream = ctx.job_controller.follow("s", job.id, interval=0.01)
    try:
        await anext(stream)
        job.session_id = "hidden"
        with pytest.raises(RuntimeError) as error: await anext(stream)
        assert error.value.code == "job/not-found"
    finally:
        await stream.aclose()
        gate.set()


def test_follow_migration_names_stream_and_two_offsets(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root = source(tmp_path, {"index.ts": "export function apply(ctx) { ctx.remote.job.follow(); }"})
    report = export_port(root, tmp_path / "ported")
    item = next(row for row in report["remotes"] if row["name"] == "job.follow")
    assert item["suggestedContract"] == "context.job_controller.follow"
    assert "base64" in item["difference"] and report["runtimeVerified"] is False


@pytest.mark.asyncio
async def test_job_follow_crosses_real_ndjson_http_and_finishes(env, tmp_path):
    import httpx
    import json
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from .test_plugin_remote_binary import set_encoding
    from lamtools_core.app.operation_catalog import OperationResult
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
    ctx, _, _, _ = env
    async def work(job): job.emit("stdout", b"\x00\xff")
    job = ctx.jobs.start("task", "http follow", work, session_id="s")
    await job._done.wait()
    host, catalog, original = _host(tmp_path)
    configure(host)
    set_encoding(host, "ndjson")
    ctx._secret_store = original._secret_store
    host.backend_manager.context = ctx
    (host.get("hook-demo").root / "ops.py").write_text(
        "from lamtools_core.app.operation_catalog import OperationResult\n"
        "def echo(request, *, context):\n"
        "    return OperationResult(request.name, context.job_controller.follow('s', request.payload['body']['text'], interval=0.01))\n", encoding="utf8")
    catalog.unregister_owner("plugin:hook-demo")
    register_plugin_operations(catalog, host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/plugin-remote/hook-demo/demo/echo", json={"args": {"text": job.id}},
            headers={"x-plugin-token": plugin_http_token(host, "hook-demo")})
    frames = [json.loads(line) for line in response.iter_lines()]
    assert response.status_code == 200 and frames[-1]["kind"] == "end"
    assert [frame["payload"]["kind"] for frame in frames[:-1]] == ["opened", "output", "status"]
    assert base64.b64decode(frames[1]["payload"]["stdout_base64"]) == b"\x00\xff"


@pytest.mark.asyncio
async def test_http_disconnect_closes_follower_without_stopping_job(env, tmp_path):
    import json
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from .test_plugin_remote_binary import set_encoding
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
    ctx, _, _, _ = env
    gate, disconnected = asyncio.Event(), asyncio.Event()
    async def work(job): await gate.wait()
    job = ctx.jobs.start("task", "idle", work, session_id="s")
    host, catalog, original = _host(tmp_path)
    configure(host)
    set_encoding(host, "ndjson")
    ctx._secret_store = original._secret_store
    host.backend_manager.context = ctx
    (host.get("hook-demo").root / "ops.py").write_text(
        "from lamtools_core.app.operation_catalog import OperationResult\n"
        "def echo(request, *, context):\n"
        "    return OperationResult(request.name, context.job_controller.follow('s', request.payload['body']['text'], interval=0.01))\n", encoding="utf8")
    catalog.unregister_owner("plugin:hook-demo")
    register_plugin_operations(catalog, host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    raw = json.dumps({"args": {"text": job.id}}).encode()
    delivered = False
    async def receive():
        nonlocal delivered
        if not delivered:
            delivered = True
            return {"type": "http.request", "body": raw, "more_body": False}
        await disconnected.wait()
        return {"type": "http.disconnect"}
    async def send(message):
        if message["type"] == "http.response.body": disconnected.set()
    token = plugin_http_token(host, "hook-demo")
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST",
        "scheme": "http", "path": "/plugin-remote/hook-demo/demo/echo", "query_string": b"",
        "headers": [(b"content-type", b"application/json"), (b"x-plugin-token", token.encode())],
        "client": ("127.0.0.1", 123), "server": ("test", 80)}
    try:
        async with asyncio.timeout(3): await app(scope, receive, send)
        assert not host._remote_stream_slots and not job._task.done()
    finally:
        gate.set()
