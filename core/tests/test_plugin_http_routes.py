"""Plugin-declared HTTP routes: matching, token auth and operation dispatch."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lamtools_core.app import OperationCatalog
from lamtools_core.plugin_system import PluginContext, PluginHost
from lamtools_core.plugin_system.backend_runtime import PluginSupervisor
from lamtools_core.plugin_system.capabilities import CapabilityError
from lamtools_core.plugin_system.manifest import load_manifest
from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
from lamtools_core.plugin_system.plugin_http import (
    dispatch_http_request,
    plugin_http_token,
    read_http_routes,
)
from lamtools_core.plugin_system.secrets import PluginSecretStore


def _plugin(tmp_path: Path) -> Path:
    folder = tmp_path / "plugins" / "hook-demo"
    folder.mkdir(parents=True)
    (folder / "plugin.json").write_text(
        json.dumps(
            {
                "name": "hook-demo",
                "version": "1",
                "operations": [
                    {"name": "hook-demo.echo", "handler": "ops:echo", "permission": "auto_allow"},
                    {"name": "hook-demo.ask", "handler": "ops:echo", "permission": "ask_user"},
                ],
                "http": {
                    "routes": [
                        {"method": "POST", "path": "/hook", "operation": "hook-demo.echo"},
                        {"method": "GET", "path": "/open", "operation": "hook-demo.echo", "auth": "none"},
                        {"method": "POST", "path": "/ask", "operation": "hook-demo.ask"},
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    (folder / "ops.py").write_text(
        "def echo(request, *, work_root=None):\n"
        "    payload = dict(request.payload or {})\n"
        "    return {'echo': payload.get('body'), 'method': payload.get('method'), 'headers': payload.get('headers')}\n",
        encoding="utf-8",
    )
    return folder


def _host(tmp_path: Path):
    folder = _plugin(tmp_path)
    host = PluginHost(roots=[folder.parent], state_path=tmp_path / "state.json")
    context = PluginContext(work_root=tmp_path, data_dir=tmp_path)
    context._secret_store = PluginSecretStore(tmp_path / "secrets")
    host.backend_manager = PluginSupervisor([], host, context)
    catalog = OperationCatalog()
    register_plugin_operations(catalog, host)
    return host, catalog, context


def test_routes_are_declared_and_validated(tmp_path: Path) -> None:
    host, _, _ = _host(tmp_path)
    manifest = host.get("hook-demo")
    assert manifest is not None
    routes = read_http_routes(manifest)
    assert [(route.method, route.path, route.auth) for route in routes] == [
        ("POST", "/hook", "token"),
        ("GET", "/open", "none"),
        ("POST", "/ask", "token"),
    ]

    manifest.raw["http"]["routes"] = [{"method": "POST", "path": "../escape", "operation": "hook-demo.echo"}]
    with pytest.raises(CapabilityError):
        read_http_routes(manifest)


@pytest.mark.asyncio
@pytest.mark.parametrize("transfer", ["declared", "chunked", "within-limit"])
async def test_http_request_body_limit_is_enforced_before_operation_dispatch(tmp_path, monkeypatch, transfer):
    # user:“第二阶段结束后 就继续开展第三阶段”+(Remote接入实际限制请求体，声明长度和分块都检查，超限不派发操作，限内请求保留原行为)。
    import httpx
    from fastapi import FastAPI
    from lamtools_core.plugin_system import plugin_http
    monkeypatch.setattr(plugin_http, "MAX_REQUEST_BODY_BYTES", 64, raising=False)
    host, catalog, _ = _host(tmp_path)
    token = plugin_http_token(host, "hook-demo")
    calls, chunks = [], []
    original = catalog.execute
    async def observed(*args, **kwargs):
        calls.append(args[0])
        return await original(*args, **kwargs)
    monkeypatch.setattr(catalog, "execute", observed)
    async def content():
        for index, body in enumerate((b"a" * 40, b"b" * 40, b"unread-tail")):
            chunks.append(index)
            yield body
    app = FastAPI()
    app.include_router(plugin_http.create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        body = content() if transfer == "chunked" else b"a" * (65 if transfer == "declared" else 64)
        response = await client.post("/plugin-http/hook-demo/hook", content=body,
            headers={"authorization": "Bearer " + token})
        if transfer == "within-limit":
            assert response.status_code == 200 and len(calls) == 1
            assert response.json()["payload"]["echo"] == "a" * 64
        else:
            assert response.status_code == 413 and not calls
            if transfer == "chunked":
                assert chunks == [0, 1]
            response = await client.post("/plugin-http/hook-demo/hook", json={"normal": True},
                headers={"authorization": "Bearer " + token})
            assert response.status_code == 200 and len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("header", ["x-plugin-token", "authorization"])
async def test_http_non_ascii_token_is_rejected_without_breaking_valid_request(tmp_path, header):
    # user:“第二阶段结束后 就继续开展第三阶段”+(Remote后端先验证真实HTTP认证边界，畸形令牌返回401而非未处理异常，合法请求仍走原操作目录)。
    import httpx
    from fastapi import FastAPI
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router
    host, catalog, _ = _host(tmp_path)
    token = plugin_http_token(host, "hook-demo")
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    malformed = "invalid-é"
    if header == "authorization":
        malformed = "Bearer " + malformed
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/plugin-http/hook-demo/hook", content=b"{}",
            headers=[(header.encode(), malformed.encode("latin1")), (b"content-type", b"application/json")])
        assert response.status_code == 401
        response = await client.post("/plugin-http/hook-demo/hook", json={"normal": True},
            headers={"authorization": "Bearer " + token})
        assert response.status_code == 200 and response.json()["payload"]["echo"] == {"normal": True}


@pytest.mark.asyncio
async def test_http_plugin_token_is_not_forwarded_into_operation_headers(tmp_path):
    # user:“复用原宿主权威”+(认证令牌只在原HTTP认证层使用，不作为普通请求头转交插件操作或回显)。
    host, catalog, _ = _host(tmp_path)
    token = plugin_http_token(host, "hook-demo")
    status, result = await dispatch_http_request(host=host, catalog=catalog, plugin="hook-demo",
        method="POST", path="/hook", headers={"X-Plugin-Token": token, "X-Request-Label": "keep"})
    assert status == 200
    assert "x-plugin-token" not in result["payload"]["headers"]
    assert result["payload"]["headers"]["x-request-label"] == "keep"
    assert token not in json.dumps(result)


async def test_token_route_rejects_missing_or_wrong_token(tmp_path: Path) -> None:
    host, catalog, context = _host(tmp_path)

    status, payload = await dispatch_http_request(
        host=host,
        catalog=catalog,
        plugin="hook-demo",
        method="POST",
        path="/hook",
        body={"hello": "world"},
    )
    assert status == 401
    assert "token" in payload["error"]

    token = plugin_http_token(host, "hook-demo")
    assert token
    assert context._secret_store.view("hook-demo").get("httpToken") == token

    status, payload = await dispatch_http_request(
        host=host,
        catalog=catalog,
        plugin="hook-demo",
        method="POST",
        path="/hook",
        body={"hello": "world"},
        headers={"X-Plugin-Token": token},
    )
    assert status == 200
    assert payload["status"] == "ok"
    assert payload["payload"]["echo"] == {"hello": "world"}
    assert "authorization" not in payload["payload"]["headers"]

    status, _ = await dispatch_http_request(
        host=host,
        catalog=catalog,
        plugin="hook-demo",
        method="POST",
        path="/hook",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert status == 200


async def test_open_route_and_permission_and_matching(tmp_path: Path) -> None:
    host, catalog, _ = _host(tmp_path)
    status, payload = await dispatch_http_request(
        host=host,
        catalog=catalog,
        plugin="hook-demo",
        method="GET",
        path="/open",
    )
    assert status == 200
    assert payload["payload"]["method"] == "GET"

    token = plugin_http_token(host, "hook-demo")
    status, payload = await dispatch_http_request(
        host=host,
        catalog=catalog,
        plugin="hook-demo",
        method="POST",
        path="/ask",
        headers={"X-Plugin-Token": token},
    )
    assert status == 403
    assert "approval" in payload["error"]

    status, _ = await dispatch_http_request(
        host=host,
        catalog=catalog,
        plugin="hook-demo",
        method="GET",
        path="/hook",
    )
    assert status == 404

    status, _ = await dispatch_http_request(
        host=host,
        catalog=catalog,
        plugin="hook-demo",
        method="POST",
        path="/../hook",
    )
    assert status == 404


def test_router_mounts_under_the_core_api(tmp_path: Path) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router

    host, catalog, _ = _host(tmp_path)
    app = FastAPI()
    app.include_router(
        create_plugin_http_router(lambda: host, lambda: catalog),
        prefix="/api/core",
    )
    client = TestClient(app)
    token = plugin_http_token(host, "hook-demo")

    response = client.post(
        "/api/core/plugin-http/hook-demo/hook",
        json={"hello": "router"},
        headers={"X-Plugin-Token": token},
    )

    assert response.status_code == 200
    assert response.json()["payload"]["echo"] == {"hello": "router"}
