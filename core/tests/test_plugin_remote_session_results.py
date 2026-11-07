"""user:“第二阶段结束后 就继续开展第三阶段”+(会话Remote结果复用真实原宿主，原SDK记录须有界传输而非空壳适配)。"""
import json
import asyncio
from dataclasses import dataclass

import httpx
import pytest
from fastapi import FastAPI

from .test_plugin_session_query import env
from .test_plugin_http_routes import _host
from .test_plugin_remote_gateway import configure
from .test_plugin_remote_binary import set_encoding, decode_parts
from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
from lamtools_core.app.operation_catalog import OperationResult


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["state", "events", "wait", "list"])
async def test_original_session_sdk_records_cross_http_without_activation(env, tmp_path, method):
    ctx, store, sessions = env
    before = await store.get("a")
    host, _, _ = _host(tmp_path)
    configure(host)
    ctx._secret_store = host.backend_manager.context._secret_store
    host.backend_manager.context = ctx
    manifest = host.get("hook-demo")
    (manifest.root / "ops.py").write_text(
        "from lamtools_core.app.operation_catalog import OperationResult\n"
        "from lamtools_core.plugin_system.sessions import SESSIONS\n"
        "async def echo(request, *, context):\n"
        "    sid = request.payload['body']['text']\n"
        + ("    value = await context.session_query.query(limit=2)\n" if method == "list" else
           "    value = await context.bind_service(SESSIONS).call('" + method + "', sid" + (", timeout=0" if method == "wait" else "") + ")\n")
        + "    return OperationResult(request.name, value)\n", encoding="utf8")
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.app.operation_catalog import OperationCatalog
    catalog = OperationCatalog()
    register_plugin_operations(catalog, host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/plugin-remote/hook-demo/demo/echo", json={"args": {"text": "a"}},
            headers={"x-plugin-token": plugin_http_token(host, "hook-demo")})
        assert response.status_code == 200
        value = response.json()["payload"]
        if method == "list":
            assert [item["session_id"] for item in value["items"]] == ["a", "b"] and value["has_more"]
            assert "hidden-secret-session" not in response.text
        elif method == "state": assert value["session_id"] == "a" and not value["running"]
        elif method == "events": assert value["session_id"] == "a" and value["events"] == []
        else: assert value["reason"] == "idle" and value["state"]["session_id"] == "a"
        if method != "list":
            denied = await client.post("/plugin-remote/hook-demo/demo/echo", json={"args": {"text": "hidden-secret-session"}},
                headers={"x-plugin-token": plugin_http_token(host, "hook-demo")})
            assert denied.status_code == 400
    assert await store.get("a") == before
    assert not sessions._context().host.runtime_task_registry.active_run_id("a")


@pytest.mark.asyncio
@pytest.mark.parametrize("shape", ["nested-binary", "cycle", "depth", "dataclass-type"])
async def test_sdk_record_projection_preserves_binary_paths_and_original_limits(tmp_path, monkeypatch, shape):
    @dataclass
    class Record:
        value: object
    host, catalog, _ = _host(tmp_path)
    configure(host)
    set_encoding(host, "multipart")
    record = Record({"bytes": b"\x00\xff"})
    if shape == "cycle": record.value = record
    elif shape == "depth":
        for _ in range(40): record = Record(record)
    elif shape == "dataclass-type": record = Record
    catalog.unregister_owner("plugin:hook-demo")
    catalog.register("hook-demo.echo", lambda request: OperationResult(request.name, record), owner="plugin:hook-demo")
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/plugin-remote/hook-demo/demo/echo", json={"args": {"text": "a"}},
            headers={"x-plugin-token": plugin_http_token(host, "hook-demo")})
    if shape == "nested-binary":
        assert response.status_code == 200
        metadata, parts = decode_parts(response)
        attachment = metadata["attachments"][0]
        assert attachment["path"] == ["payload", "value", "bytes"]
        assert parts[attachment["part"]] == b"\x00\xff"
    else: assert response.status_code == 502


def test_session_remote_handoff_reports_native_projection_and_real_method_limits(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root = source(tmp_path, {"index.ts": "export function apply(ctx) { ctx.remote.session.state(); ctx.remote.session.list(); ctx.remote.session.search(); }"})
    report = export_port(root, tmp_path / "ported")
    methods = {row["name"]: row for row in report["remotes"]}
    assert "dataclass" in methods["session.state"]["difference"]
    assert methods["session.list"]["suggestedContract"] == "context.session_query.query"
    assert "标题" in methods["session.search"]["difference"]
    assert report["runtimeVerified"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("method,wait_at", [("state", "admission"), ("events", "admission"),
    ("state", "snapshot"), ("events", "snapshot"), ("events", "history")])
@pytest.mark.parametrize("change", ["store", "shutdown"])
async def test_passive_session_read_rechecks_original_store_after_admission_wait(env, monkeypatch, method, wait_at, change):
    ctx, store, sessions = env
    target, name = (store, "get") if wait_at == "admission" else (sessions._persistence,
        "load_metadata" if wait_at == "snapshot" else "list_after")
    original = getattr(target, name)
    entered, release = asyncio.Event(), asyncio.Event()
    async def gated(*args, **kwargs):
        result = await original(*args, **kwargs)
        entered.set()
        await release.wait()
        return result
    monkeypatch.setattr(target, name, gated)
    live = sessions._context()
    task = asyncio.create_task(getattr(sessions, method)("a"))
    try:
        await entered.wait()
        if change == "store": live.host.session_store = object()
        else: sessions.shutdown()
        release.set()
        from lamtools_core.plugin_system.sessions import SessionError
        with pytest.raises(SessionError) as error: await task
        assert error.value.code == ("session/host-changed" if change == "store" else "session/closed")
    finally:
        live.host.session_store = store
        release.set()
        await asyncio.gather(task, return_exceptions=True)
