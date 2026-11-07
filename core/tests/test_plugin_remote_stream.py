"""user:“第二阶段结束后 就继续开展第三阶段”+(真实HTTP流须明确声明，断连、撤回和坏帧都回收原迭代器)。"""
import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI

from lamtools_core.app.operation_catalog import OperationResult
from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
from .test_plugin_http_routes import _host
from .test_plugin_remote_gateway import configure
from .test_plugin_remote_binary import set_encoding
from .test_plugin_working_directory import env


def setup(tmp_path, source):
    host, catalog, _ = _host(tmp_path)
    configure(host)
    set_encoding(host, "ndjson")
    catalog.unregister_owner("plugin:hook-demo")
    catalog.register("hook-demo.echo", lambda request: OperationResult(request.name, source), owner="plugin:hook-demo")
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    return host, catalog, app


@pytest.mark.asyncio
async def test_explicit_ndjson_http_has_items_end_and_actual_close(tmp_path):
    closed = asyncio.Event()
    async def source():
        try:
            yield {"kind": "ready"}
            yield {"kind": "change", "path": "中文.txt"}
        finally:
            closed.set()
    host, _, app = setup(tmp_path, source())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/plugin-remote/hook-demo/demo/echo", json={"args": {"text": "watch"}},
            headers={"x-plugin-token": plugin_http_token(host, "hook-demo")})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    frames = [json.loads(line) for line in response.iter_lines()]
    assert frames == [{"kind": "item", "payload": {"kind": "ready"}},
        {"kind": "item", "payload": {"kind": "change", "path": "中文.txt"}}, {"kind": "end"}]
    assert closed.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["token", "args", "approval"])
async def test_stream_rejection_never_opens_iterator(tmp_path, case):
    async def source():
        pytest.fail("must not consume rejected stream")
        yield
    host, catalog, app = setup(tmp_path, source())
    catalog.unregister_owner("plugin:hook-demo")
    catalog.register("hook-demo.echo", lambda request: pytest.fail("must not dispatch"), owner="plugin:hook-demo")
    if case == "approval":
        path = host.get("hook-demo").root / "plugin.json"
        data = json.loads(path.read_text(encoding="utf8"))
        data["operations"][0]["permission"] = "ask_user"
        path.write_text(json.dumps(data), encoding="utf8")
        host._invalidate()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/plugin-remote/hook-demo/demo/echo",
            json={"args": {} if case == "args" else {"text": "watch"}},
            headers={"x-plugin-token": "wrong" if case == "token" else plugin_http_token(host, "hook-demo")})
    assert response.status_code == {"token": 401, "args": 400, "approval": 403}[case]


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [b"private-bytes", float("nan"), {"too-large": "x" * (1024*1024)}])
async def test_invalid_stream_frame_is_sanitized_and_iterator_closed(tmp_path, bad):
    closed = asyncio.Event()
    async def source():
        try:
            yield "first"
            yield bad
        finally:
            closed.set()
    host, _, app = setup(tmp_path, source())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/plugin-remote/hook-demo/demo/echo", json={"args": {"text": "watch"}},
            headers={"x-plugin-token": plugin_http_token(host, "hook-demo")})
    frames = [json.loads(line) for line in response.iter_lines()]
    assert frames == [{"kind": "item", "payload": "first"}, {"kind": "error", "code": "gateway/stream-failed"}]
    assert closed.is_set() and b"private-bytes" not in response.content


@pytest.mark.asyncio
@pytest.mark.parametrize("stop", ["disconnect", "withdraw", "generation", "token", "disable", "cancel"])
async def test_idle_http_stream_termination_joins_source(tmp_path, stop, monkeypatch):
    from lamtools_core.plugin_system import remote_stream
    monkeypatch.setattr(remote_stream, "POLL_INTERVAL", 0.01)
    closed, waiting, disconnect = asyncio.Event(), asyncio.Event(), asyncio.Event()
    class Source:
        def __aiter__(self): return self
        async def __anext__(self):
            waiting.set()
            await asyncio.Event().wait()
        async def aclose(self): closed.set()
    host, _, app = setup(tmp_path, Source())
    token = plugin_http_token(host, "hook-demo")
    raw = json.dumps({"args": {"text": "watch"}}).encode()
    delivered = False
    async def receive():
        nonlocal delivered
        if not delivered:
            delivered = True
            return {"type": "http.request", "body": raw, "more_body": False}
        await disconnect.wait()
        return {"type": "http.disconnect"}
    sent = []
    async def send(message): sent.append(message)
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST",
        "scheme": "http", "path": "/plugin-remote/hook-demo/demo/echo", "query_string": b"",
        "headers": [(b"content-type", b"application/json"), (b"x-plugin-token", token.encode())],
        "client": ("127.0.0.1", 123), "server": ("test", 80)}
    running = asyncio.create_task(app(scope, receive, send))
    async with asyncio.timeout(3):
        await waiting.wait()
        if stop == "disconnect": disconnect.set()
        elif stop == "withdraw": configure(host, remove=True)
        elif stop == "generation": host.backend_manager.generation["hook-demo"] = 999
        elif stop == "token": host.backend_manager.context._secret_store.view("hook-demo").delete("httpToken")
        elif stop == "disable": host.disable("hook-demo")
        else: running.cancel()
        if stop == "cancel":
            with pytest.raises(asyncio.CancelledError): await running
        else: await running
    assert closed.is_set()
    assert sent[0]["status"] == 200
    if stop not in {"disconnect", "cancel"}:
        assert sent[-1]["type"] == "http.response.body" and sent[-1]["more_body"] is False
        assert json.loads(sent[-1]["body"])["kind"] == "error"
    if stop == "token":
        assert not host.backend_manager.context._secret_store.view("hook-demo").get("httpToken")


@pytest.mark.asyncio
async def test_failed_operation_closes_stream_payload_before_json_error(tmp_path):
    closed = asyncio.Event()
    class Source:
        def __aiter__(self): return self
        async def __anext__(self): pytest.fail("failed result must not be pulled")
        async def aclose(self): closed.set()
    source = Source()
    host, catalog, app = setup(tmp_path, source)
    catalog.unregister_owner("plugin:hook-demo")
    catalog.register("hook-demo.echo", lambda request: OperationResult(request.name, source, status="failed"), owner="plugin:hook-demo")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/plugin-remote/hook-demo/demo/echo", json={"args": {"text": "watch"}},
            headers={"x-plugin-token": plugin_http_token(host, "hook-demo")})
    assert response.status_code == 502 and closed.is_set()


@pytest.mark.asyncio
async def test_stream_slot_released_after_real_close_and_no_prefetch_under_send_backpressure(tmp_path, monkeypatch):
    from lamtools_core.plugin_system import remote_stream
    from lamtools_core.plugin_system.remote_gateway import dispatch_remote_request
    monkeypatch.setattr(remote_stream, "MAX_STREAMS", 1)
    pulls = []
    closed, sent, block = asyncio.Event(), asyncio.Event(), asyncio.Event()
    class Source:
        def __aiter__(self): return self
        async def __anext__(self):
            pulls.append(1)
            return "one"
        async def aclose(self): closed.set()
    host, catalog, _ = setup(tmp_path, Source())
    kwargs = dict(host=host, catalog=catalog, plugin="hook-demo", namespace="demo", method="echo",
        body={"args": {"text": "watch"}}, headers={"x-plugin-token": plugin_http_token(host, "hook-demo")})
    status, response = await dispatch_remote_request(**kwargs)
    assert status == 200
    assert (await dispatch_remote_request(**kwargs))[0] == 429
    async def receive(): await asyncio.Event().wait()
    async def send(message):
        if message["type"] == "http.response.body":
            sent.set()
            await block.wait()
    running = asyncio.create_task(response({}, receive, send))
    await sent.wait()
    await asyncio.sleep(0)
    assert len(pulls) == 1
    running.cancel()
    with pytest.raises(asyncio.CancelledError): await running
    assert closed.is_set() and not host._remote_stream_slots


@pytest.mark.asyncio
async def test_original_operation_bridge_and_session_file_watch_cross_real_http(env, tmp_path):
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    ctx, _, _, root = env
    target = root / "network.txt"
    target.write_text("before")
    host, catalog, _ = _host(tmp_path)
    configure(host)
    set_encoding(host, "ndjson")
    ctx._secret_store = host.backend_manager.context._secret_store
    host.backend_manager.context = ctx
    (host.get("hook-demo").root / "ops.py").write_text(
        "from lamtools_core.app.operation_catalog import OperationResult\n"
        "async def echo(request, *, context):\n"
        "    stream = await context.workspace_files.changes('s', request.payload['body']['text'], interval=0.01)\n"
        "    return OperationResult(request.name, stream)\n", encoding="utf8")
    catalog.unregister_owner("plugin:hook-demo")
    register_plugin_operations(catalog, host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    raw = json.dumps({"args": {"text": "network.txt"}}).encode()
    disconnect = asyncio.Event()
    delivered = False
    async def receive():
        nonlocal delivered
        if not delivered:
            delivered = True
            return {"type": "http.request", "body": raw, "more_body": False}
        await disconnect.wait()
        return {"type": "http.disconnect"}
    frames = []
    async def send(message):
        if message["type"] == "http.response.start": assert message["status"] == 200
        elif message.get("body"):
            frames.append(json.loads(message["body"]))
            if len(frames) == 1: target.write_text("changed-on-network")
            else: disconnect.set()
    token = plugin_http_token(host, "hook-demo")
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST",
        "scheme": "http", "path": "/plugin-remote/hook-demo/demo/echo", "query_string": b"",
        "headers": [(b"content-type", b"application/json"), (b"x-plugin-token", token.encode())],
        "client": ("127.0.0.1", 123), "server": ("test", 80)}
    async with asyncio.timeout(3): await app(scope, receive, send)
    assert frames[0] == {"kind": "item", "payload": {"kind": "ready"}}
    assert frames[1]["payload"]["change"]["bytes"] == len("changed-on-network")
    state = ctx._registration_scope._workspace_file_changes
    assert not state["streams"] and all(not fs._watches for fs in state["roots"].values())


@pytest.mark.asyncio
@pytest.mark.parametrize("shape", ["plain", "broken-iterator", "unmarked"])
async def test_invalid_or_unmarked_stream_result_is_rejected_and_closed(tmp_path, shape):
    closed = asyncio.Event()
    class Source:
        def __aiter__(self):
            if shape == "broken-iterator": raise ValueError("private-details")
            return self
        async def __anext__(self): pytest.fail("invalid stream must not pull")
        async def aclose(self): closed.set()
    source = {} if shape == "plain" else Source()
    host, _, app = setup(tmp_path, source)
    if shape == "unmarked": set_encoding(host, "json")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/plugin-remote/hook-demo/demo/echo", json={"args": {"text": "watch"}},
            headers={"x-plugin-token": plugin_http_token(host, "hook-demo")})
    assert response.status_code == 502 and "private-details" not in response.text
    assert shape == "plain" or closed.is_set()


@pytest.mark.asyncio
async def test_stream_keeps_core_and_plugin_authentication(tmp_path):
    from lamtools_core.app.api_access import CoreApiAccessMiddleware, CoreApiAccessPolicy
    async def source(): yield "allowed"
    host, _, app = setup(tmp_path, source())
    token, core_token = plugin_http_token(host, "hook-demo"), "test-core-token-" + "a" * 32
    app.add_middleware(CoreApiAccessMiddleware, policy=CoreApiAccessPolicy(allow_lan=True, token=core_token))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        path, body = "/plugin-remote/hook-demo/demo/echo", {"args": {"text": "auth"}}
        assert (await client.post(path, json=body, headers={"x-plugin-token": token})).status_code == 401
        assert (await client.post(path, json=body, headers={"authorization": "Bearer " + core_token})).status_code == 401
        response = await client.post(path, json=body, headers={"authorization": "Bearer " + core_token, "x-plugin-token": token})
    assert response.status_code == 200
    assert token not in response.text and core_token not in response.text


def test_stream_handoff_names_explicit_transport_without_auto_mapping(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root = source(tmp_path, {"index.ts": "export function apply(ctx) { ctx.workspaceFiles.changes(); }"})
    output = tmp_path / "ported"
    report = export_port(root, output)
    assert report["sundayHostContracts"]["remoteGateway"]["version"] == 3
    assert "ndjson" in (output / "PORTING.md").read_text(encoding="utf8")
    assert "ndjson" in report["workspaceFileMethods"][0]["difference"]
    assert not json.loads((output / "plugin.json").read_text(encoding="utf8")).get("http", {}).get("remote")


@pytest.mark.asyncio
async def test_repeated_response_cancel_joins_actual_provider_close_before_releasing_slot(tmp_path):
    from lamtools_core.plugin_system.remote_gateway import dispatch_remote_request
    waiting, closing, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    class Source:
        def __aiter__(self): return self
        async def __anext__(self):
            waiting.set()
            await asyncio.Event().wait()
        async def aclose(self):
            closing.set()
            await release.wait()
    host, catalog, _ = setup(tmp_path, Source())
    _, response = await dispatch_remote_request(host=host, catalog=catalog, plugin="hook-demo", namespace="demo", method="echo",
        body={"args": {"text": "watch"}}, headers={"x-plugin-token": plugin_http_token(host, "hook-demo")})
    async def receive(): await asyncio.Event().wait()
    async def send(message): pass
    running = asyncio.create_task(response({}, receive, send))
    await waiting.wait()
    running.cancel()
    await closing.wait()
    running.cancel()
    await asyncio.sleep(0)
    assert not running.done() and host._remote_stream_slots["hook-demo"] == 1
    release.set()
    with pytest.raises(asyncio.CancelledError): await running
    assert not host._remote_stream_slots
