from __future__ import annotations

import asyncio
import socket
import sys
from types import SimpleNamespace

import httpx
import pytest
from fastapi import APIRouter, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from lamtools_core.app.api_access import CoreApiAccessPolicy, is_loopback_address
from lamtools_core.app.factory import add_spa_fallback, create_app
from lamtools_core.cli import build_parser


TOKEN = "test-only-core-access-token-0123456789"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def surface(tmp_path):
    def build(policy=None):
        frontend = tmp_path / "frontend"
        (frontend / "assets").mkdir(parents=True, exist_ok=True)
        (frontend / "index.html").write_text("<html>Sunday</html>", encoding="utf-8")
        (frontend / "assets" / "test.js").write_text("// asset", encoding="utf-8")
        app = create_app(access_policy=policy, frontend_dir=frontend)
        router = APIRouter()

        @router.post("/write")
        async def write():
            app.state.writes += 1
            return {"ok": True}

        @router.websocket("/ws")
        async def websocket(ws: WebSocket):
            await ws.accept()
            await ws.send_json({"ok": True})
            await ws.close()

        app.state.writes = 0
        app.include_router(router, prefix="/api/extension")
        add_spa_fallback(app, frontend)
        return app

    return build


@pytest.mark.parametrize("host", ["127.0.0.1", "127.0.0.2", "::1", "::ffff:127.0.0.1"])
def test_local_desktop_and_gateway_peers_remain_usable(surface, host):
    client = TestClient(surface(), client=(host, 50000))
    assert client.get("/api/health").status_code == 200
    assert client.post("/api/extension/write").status_code == 200
    with client.websocket_connect("/api/extension/ws") as ws:
        assert ws.receive_json() == {"ok": True}


@pytest.mark.parametrize("host", ["192.168.1.8", "203.0.113.8", "::", "2001:db8::8", "testclient", "localhost"])
@pytest.mark.parametrize("headers", [{}, AUTH, {"Origin": "tauri://localhost"}, {
    "Host": "127.0.0.1", "X-Forwarded-For": "127.0.0.1", "Forwarded": "for=127.0.0.1",
}])
def test_originless_or_spoofed_remote_peer_is_not_local(surface, host, headers):
    app = surface()
    client = TestClient(app, client=(host, 50000), headers=headers)
    assert client.get("/api/health").status_code == 403
    assert client.post("/api/extension/write").status_code == 403
    assert app.state.writes == 0
    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect("/api/extension/ws"):
            pytest.fail("remote connection accepted in loopback mode")
    assert closed.value.code == 1008


@pytest.mark.parametrize("path", ["/api/health", "/api/members", "/docs", "/openapi.json", "/assets/test.js", "/", "/api/core/sessions", "/unknown"])
@pytest.mark.parametrize("peer", ["192.168.1.8", "127.0.0.1"])
def test_lan_auth_covers_health_docs_mounts_and_loopback_proxies(surface, path, peer):
    client = TestClient(surface(CoreApiAccessPolicy(True, TOKEN)), client=(peer, 50000))
    assert client.get(path).status_code == 401
    assert client.get(path).headers["www-authenticate"] == "Bearer"
    # Auth succeeds at the boundary; nonexistent API paths can still use SPA fallback.
    assert client.get(path, headers=AUTH).status_code == 200


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}, {"Authorization": f"Basic {TOKEN}"}, {
    "Origin": "tauri://localhost", "X-Forwarded-For": "127.0.0.1",
}, {"Cookie": f"token={TOKEN}"}, {"Authorization": f"Bearer {TOKEN} extra"}])
def test_lan_rejects_unauthenticated_http_and_ws_before_dispatch(surface, headers):
    app = surface(CoreApiAccessPolicy(True, TOKEN))
    client = TestClient(app, client=("192.168.1.8", 50000))
    assert client.post(f"/api/extension/write?token={TOKEN}", headers=headers).status_code == 401
    assert client.options("/api/extension/write", headers={**headers, "Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"}).status_code == 401
    assert app.state.writes == 0
    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect(f"/api/extension/ws?token={TOKEN}", headers=headers):
            pytest.fail("missing/invalid bearer accepted")
    assert closed.value.code == 1008


def test_authenticated_lan_http_and_ws_preserve_origin_defence(surface):
    app = surface(CoreApiAccessPolicy(True, TOKEN))
    client = TestClient(app, client=("192.168.1.8", 50000))
    assert client.post("/api/extension/write", headers=AUTH).status_code == 200
    assert app.state.writes == 1
    assert client.post("/api/extension/write", headers={**AUTH, "Origin": "https://evil.example"}).status_code == 403
    with client.websocket_connect("/api/extension/ws", headers=AUTH) as ws:
        assert ws.receive_json() == {"ok": True}


def test_auth_is_fail_closed_for_unknown_peers_and_ambiguous_headers():
    assert CoreApiAccessPolicy().rejection({"client": None})[0] == 403
    policy = CoreApiAccessPolicy(True, TOKEN)
    for headers in [
        [(b"authorization", b"Bearer " + TOKEN.encode()), (b"authorization", b"Bearer wrong")],
        [(b"authorization", b"Bearer \xff")],
    ]:
        assert policy.rejection({"headers": headers})[0] == 401
    assert TOKEN not in repr(policy)


@pytest.mark.parametrize("token", ["", "short", "x" * 31, "x" * 32 + " ", "x" * 32 + "\n", "中" * 32])
def test_lan_requires_valid_token(token):
    with pytest.raises(ValueError, match="LAMTOOLS_CORE_API_TOKEN") as error:
        CoreApiAccessPolicy(True, token)
    if token:
        assert token not in str(error.value)


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.4", "::"])
async def test_cli_refuses_unconfigured_exposure_before_creating_app(monkeypatch, host):
    monkeypatch.delenv("LAMTOOLS_CORE_ALLOW_LAN", raising=False)
    monkeypatch.delenv("LAMTOOLS_CORE_API_TOKEN", raising=False)
    def forbidden(**kwargs):
        pytest.fail("insecure CLI initialized the app")
    monkeypatch.setattr("lamtools_core.app.http_agent_app.create_core_agent_http_app", forbidden)
    args = build_parser().parse_args(["serve", "--host", host])
    with pytest.raises(ValueError, match="Non-loopback"):
        await args.func(args)


async def test_cli_lan_configuration_reaches_app_and_disables_forwarded_trust(monkeypatch):
    monkeypatch.setenv("LAMTOOLS_CORE_API_TOKEN", TOKEN)
    seen = {}
    def build(**kwargs):
        seen["policy"] = kwargs["access_policy"]
        return object()
    class Server:
        def __init__(self, config):
            seen["config"] = config
        async def serve(self):
            pass
    monkeypatch.setattr("lamtools_core.app.http_agent_app.create_core_agent_http_app", build)
    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(Config=lambda app, **kwargs: kwargs, Server=Server))
    args = build_parser().parse_args(["serve", "--host", "192.168.1.4", "--allow-lan", "--ssl-certfile", "cert.pem", "--ssl-keyfile", "key.pem"])
    assert await args.func(args) == 0
    assert seen["policy"] == CoreApiAccessPolicy(True, TOKEN)
    assert seen["config"]["proxy_headers"] is False
    assert seen["config"]["ssl_certfile"] == "cert.pem"


def test_environment_policy_for_asgi_module_launch(monkeypatch):
    monkeypatch.setenv("LAMTOOLS_CORE_ALLOW_LAN", "1")
    monkeypatch.setenv("LAMTOOLS_CORE_API_TOKEN", TOKEN)
    app = create_app()
    assert TestClient(app).get("/api/health").status_code == 401
    assert TestClient(app).get("/api/health", headers=AUTH).status_code == 200
    monkeypatch.setenv("LAMTOOLS_CORE_ALLOW_LAN", "invalid")
    with pytest.raises(ValueError, match="ALLOW_LAN"):
        create_app()


def test_bind_names_are_not_a_dns_trust_bypass():
    assert CoreApiAccessPolicy().validate_bind_host("localhost") == "127.0.0.1"
    assert not is_loopback_address("localhost")
    with pytest.raises(ValueError, match="numeric IP"):
        CoreApiAccessPolicy().validate_bind_host("local.attacker.example")


def test_actual_core_routes_and_rpc_require_auth(tmp_path):
    from lamtools_core.app.http_agent_app import create_core_agent_http_app
    app = create_core_agent_http_app(core_db=tmp_path / "core.db", data_dir=tmp_path / "data", access_policy=CoreApiAccessPolicy(True, TOKEN))
    with TestClient(app, client=("192.168.1.8", 50000)) as client:
        for path in ["/api/core/sessions", "/api/core/projects", "/api/core/config/models", "/api/core/config/providers", "/api/core/desktop-plugins/example/assets/index.html", "/api/core/sessions/example/attachments"]:
            assert client.get(path).status_code == 401
            assert client.post(path, json={}).status_code == 401
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/api/core/app-server"):
                pytest.fail("Core RPC accepted without authentication")
        assert client.get("/api/core/sessions", headers=AUTH).status_code == 200
        with pytest.raises(WebSocketDisconnect) as closed:
            with client.websocket_connect("/api/core/app-server", headers={**AUTH, "Origin": "https://evil.example"}):
                pytest.fail("foreign browser Origin accepted")
        assert closed.value.code == 1008
        with client.websocket_connect("/api/core/app-server", headers=AUTH) as ws:
            ws.send_json({"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "authenticated-lan-test"}}})
            assert ws.receive_json()["result"]["protocolVersion"] == "core.app_server.v1"


async def test_real_socket_cli_bearer_and_forwarded_header_boundary(tmp_path):
    import uvicorn
    import aiohttp
    from lamtools_core.app.live_client import CoreAppServerClient
    from lamtools_core.app.http_agent_app import create_core_agent_http_app
    app = create_core_agent_http_app(core_db=tmp_path / "socket.db", data_dir=tmp_path / "data", access_policy=CoreApiAccessPolicy(True, TOKEN))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, proxy_headers=False, log_level="error"))
    task = asyncio.create_task(server.serve())
    try:
        for _ in range(200):
            if server.started:
                break
            if task.done():
                await task
            await asyncio.sleep(0.01)
        assert server.started
        base = f"http://127.0.0.1:{port}"
        async with httpx.AsyncClient(base_url=base, trust_env=False) as http:
            assert (await http.get("/api/health", headers={"X-Forwarded-For": "127.0.0.1"})).status_code == 401
            assert (await http.get("/api/health", headers=AUTH)).status_code == 200
        denied = CoreAppServerClient(base)
        try:
            with pytest.raises(aiohttp.WSServerHandshakeError) as error:
                await denied.connect()
            assert error.value.status == 403
        finally:
            await denied.close()
        client = CoreAppServerClient(base, token=TOKEN)
        try:
            await client.connect()
        finally:
            await client.close()
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 10)


def test_packaged_sidecar_remains_internal_despite_lan_environment(monkeypatch, tmp_path):
    import desktop_backend
    seen = {}
    monkeypatch.setenv("LAMCORE_HOST", "127.0.0.1")
    monkeypatch.setenv("LAMTOOLS_CORE_ALLOW_LAN", "1")
    monkeypatch.setenv("LAMTOOLS_CORE_API_TOKEN", TOKEN)
    monkeypatch.setenv("LAMTOOLS_CORE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr("lamtools_core.config.defaults.ensure_default_config_files", lambda: None)
    monkeypatch.setattr("lamtools_core.logging_setup.attach_backend_file_logger", lambda directory: directory / "test.log")
    def build(**kwargs):
        seen["policy"] = kwargs["access_policy"]
        return object()
    monkeypatch.setattr("lamtools_core.app.http_agent_app.create_default_core_agent_http_app", build)
    monkeypatch.setattr(desktop_backend.uvicorn, "run", lambda app, **kwargs: seen.update(kwargs))
    desktop_backend._run()
    assert seen["host"] == "127.0.0.1"
    assert seen["proxy_headers"] is False
    assert seen["policy"] == CoreApiAccessPolicy()
    monkeypatch.setenv("LAMCORE_HOST", "0.0.0.0")
    with pytest.raises(ValueError, match="Non-loopback"):
        desktop_backend._run()
