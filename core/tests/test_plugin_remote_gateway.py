"""user:“第二阶段结束后 就继续开展第三阶段”+(明确Remote方法和参数，复用原插件HTTP认证、操作归属及审批)。"""
import json
import asyncio

import httpx
import pytest
from fastapi import FastAPI

from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
from .test_plugin_http_routes import _host


def configure(host, *, target="/hook", remove=False, bad_schema=False):
    path = host.get("hook-demo").root / "plugin.json"
    data = json.loads(path.read_text(encoding="utf8"))
    data["http"]["remote"] = [] if remove else [{"namespace": "demo", "method": "echo", "route": target,
        "argsSchema": {"type": "object", "properties": {"text": {"type": "object" if bad_schema else "string"}},
            "required": ["text"], "additionalProperties": False}}]
    path.write_text(json.dumps(data), encoding="utf8")
    host._invalidate()


def test_migration_handoff_exposes_verified_remote_transport_without_blind_mapping(tmp_path):
    # user:“保持迁移脚本、机器清单、文档同步”+(迁移交接公开真实Remote入口和差异，不能把上游方法自动绑定到任意操作)。
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root = source(tmp_path, {"index.ts": "export function apply(ctx) { ctx.remote.session.prompt({}); }"})
    output = tmp_path / "ported"
    report = export_port(root, output)
    contract = report["sundayHostContracts"]["remoteGateway"]
    assert contract["version"] == 9
    assert "POST /api/core/plugin-remote/{plugin}/{namespace}/{method}" in contract["apis"]
    handoff = (output / "PORTING.md").read_text(encoding="utf8")
    assert "plugin_phase3_remote.md" in handoff and "http.remote" in handoff
    manifest = json.loads((output / "plugin.json").read_text(encoding="utf8"))
    assert not manifest.get("http", {}).get("remote")
    assert report["runtimeVerified"] is False and report["status"] == "needs-port"


@pytest.mark.asyncio
@pytest.mark.parametrize("case,expected", [("valid", 200), ("unknown", 404), ("missing", 400),
    ("extra", 400), ("wrong-type", 400), ("envelope", 400), ("token", 401), ("approval", 403),
    ("foreign-owner", 403), ("disabled", 409), ("public-route", 400), ("schema", 400)])
async def test_explicit_remote_mapping_enforces_original_dispatch_authority(tmp_path, monkeypatch, case, expected):
    # user:“复用原宿主权威”+(明确映射只到原token路由，参数和身份拒绝不能进入业务操作，不开放任意目录调用)。
    host, catalog, _ = _host(tmp_path)
    configure(host, target="/ask" if case == "approval" else "/open" if case == "public-route" else "/hook",
        bad_schema=case == "schema")
    token = plugin_http_token(host, "hook-demo")
    if case == "foreign-owner":
        catalog.unregister_owner("plugin:hook-demo")
        catalog.register("hook-demo.echo", lambda request: pytest.fail("foreign operation must not execute"), owner="another-owner")
    if case == "disabled":
        host.disable("hook-demo")
    calls = []
    original = catalog.execute
    async def observed(*args, **kwargs):
        calls.append(args[0])
        return await original(*args, **kwargs)
    monkeypatch.setattr(catalog, "execute", observed)
    body = {"args": {"text": "hello"}}
    if case == "missing": body["args"] = {}
    if case == "extra": body["args"]["extra"] = "denied"
    if case == "wrong-type": body["args"]["text"] = 123
    if case == "envelope": body["untrusted"] = "denied"
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog), prefix="/api/core")
    endpoint = "other" if case == "unknown" else "echo"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/api/core/plugin-remote/hook-demo/demo/{endpoint}", json=body,
            headers={"x-plugin-token": "wrong" if case == "token" else token})
    assert response.status_code == expected
    assert calls == (["hook-demo.echo"] if case == "valid" else [])
    if case == "valid":
        assert response.json()["payload"]["echo"] == {"text": "hello"}
        assert "x-plugin-token" not in response.json()["payload"]["headers"]


@pytest.mark.asyncio
async def test_remote_descriptor_withdrawal_has_no_untyped_catalog_fallback(tmp_path):
    # user:“完成真实接口、参数/错误、作用域、取消/清理”+(每次取当前明确描述符，撤回后原操作即使存在也不能继续Remote调用)。
    host, catalog, _ = _host(tmp_path)
    configure(host)
    token = plugin_http_token(host, "hook-demo")
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        path = "/plugin-remote/hook-demo/demo/echo"
        assert (await client.post(path, json={"args": {"text": "before"}}, headers={"x-plugin-token": token})).status_code == 200
        configure(host, remove=True)
        assert catalog.has("hook-demo.echo")
        assert (await client.post(path, json={"args": {"text": "after"}}, headers={"x-plugin-token": token})).status_code == 404


@pytest.mark.asyncio
async def test_remote_inherits_core_and_plugin_authentication_without_client_claims(tmp_path):
    # user:“复用原宿主权威”+(已有Core访问边界和插件令牌都必须通过，客户端声明不能取代两层认证)。
    from lamtools_core.app.api_access import CoreApiAccessMiddleware, CoreApiAccessPolicy
    host, catalog, _ = _host(tmp_path)
    configure(host)
    token = plugin_http_token(host, "hook-demo")
    core_token = "test-core-token-" + "a" * 32
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    app.add_middleware(CoreApiAccessMiddleware, policy=CoreApiAccessPolicy(allow_lan=True, token=core_token))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        path, body = "/plugin-remote/hook-demo/demo/echo", {"args": {"text": "auth"}}
        assert (await client.post(path, json=body, headers={"x-plugin-token": token})).status_code == 401
        assert (await client.post(path, json=body, headers={"authorization": "Bearer " + core_token})).status_code == 401
        response = await client.post(path, json=body, headers={"authorization": "Bearer " + core_token, "x-plugin-token": token})
        assert response.status_code == 200
        assert core_token not in response.text and token not in response.text


@pytest.mark.asyncio
async def test_remote_shares_bounded_body_reader_and_original_http_still_works(tmp_path, monkeypatch):
    # user:“完成真实接口、参数/错误、作用域、取消/清理”+(Remote与原HTTP共用限额，抽取读取器后不破坏原文本操作)。
    from lamtools_core.plugin_system import plugin_http
    monkeypatch.setattr(plugin_http, "MAX_REQUEST_BODY_BYTES", 64)
    host, catalog, _ = _host(tmp_path)
    configure(host)
    token = plugin_http_token(host, "hook-demo")
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
        headers={"x-plugin-token": token}) as client:
        assert (await client.post("/plugin-remote/hook-demo/demo/echo", json={"args": {"text": "x" * 80}})).status_code == 413
        assert (await client.post("/plugin-remote/hook-demo/demo/echo", json={"args": {"text": "normal"}})).status_code == 200
        response = await client.post("/plugin-http/hook-demo/hook", content=b"a" * 64)
        assert response.status_code == 200 and response.json()["payload"]["echo"] == "a" * 64


@pytest.mark.asyncio
async def test_remote_request_cancellation_reaches_original_operation_and_joins_cleanup(tmp_path):
    # user:“完成真实接口、参数/错误、作用域、取消/清理”+(请求取消沿原目录传给协作式业务操作，等待实际finally清理，不能保留脱管后台任务)。
    from lamtools_core.app.operation_catalog import OperationResult
    host, catalog, _ = _host(tmp_path)
    configure(host)
    entered, cleaned = asyncio.Event(), asyncio.Event()
    async def slow(request):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()
        return OperationResult(request.name)
    catalog.unregister_owner("plugin:hook-demo")
    catalog.register("hook-demo.echo", slow, owner="plugin:hook-demo")
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        pending = asyncio.create_task(client.post("/plugin-remote/hook-demo/demo/echo", json={"args": {"text": "wait"}},
            headers={"x-plugin-token": plugin_http_token(host, "hook-demo")}))
        try:
            await asyncio.wait_for(entered.wait(), 3)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            assert cleaned.is_set()
        finally:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
