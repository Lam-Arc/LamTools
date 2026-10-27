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
