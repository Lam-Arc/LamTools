"""user:“不要出错”+(验证实际路由、桌面嵌入策略与不开放主程序权限)。"""
from pathlib import Path

import httpx
import pytest

from lamtools_core.app.factory import create_app
from lamtools_core.app.api_access import CoreApiAccessPolicy


@pytest.mark.asyncio
async def test_runtime_is_a_static_sandbox_without_app_or_network_privileges():
    transport = httpx.ASGITransport(app=create_app(), client=("127.0.0.1", 32100))
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:5172") as client:
        response = await client.get("/api/core/inline-visualizations/runtime")
        assert response.status_code == 200
        csp = response.headers["content-security-policy"]
        for rule in ("default-src 'none'", "connect-src 'none'", "sandbox allow-scripts", "form-action 'none'", "frame-src 'none'", "base-uri 'none'"):
            assert rule in csp
        assert "allow-same-origin" not in csp
        assert "'unsafe-eval'" not in csp
        assert response.headers.get("x-frame-options") is None
        assert "tauri://localhost" in csp
        assert response.headers["cache-control"] == "no-store"
        assert "sunday-visualization:ready" in response.text
        health = await client.get("/api/health")
        assert health.headers["x-frame-options"] == "SAMEORIGIN"


def test_model_knows_the_explicit_fence_and_its_constraints():
    from lamtools_core.app.base_agent import INLINE_VISUALIZATION_PROTOCOL
    assert "interactive-html" in INLINE_VISUALIZATION_PROTOCOL
    assert "network" in INLINE_VISUALIZATION_PROTOCOL
    assert "Sunday" in INLINE_VISUALIZATION_PROTOCOL


def test_desktop_csp_keeps_inline_scripts_disabled_in_the_main_app():
    import json
    config = json.loads((Path(__file__).parents[1] / "desktop/src-tauri/tauri.conf.json").read_text(encoding="utf8"))
    csp = config["app"]["security"]["csp"]
    script_rule = next(rule.strip() for rule in csp.split(";") if rule.strip().startswith("script-src"))
    assert "unsafe-inline" not in script_rule


@pytest.mark.asyncio
async def test_runtime_keeps_lan_authentication_and_loopback_checks():
    token = "x" * 40
    app = create_app(access_policy=CoreApiAccessPolicy(allow_lan=True, token=token))
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 32100))
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:5172") as client:
        assert (await client.get("/api/core/inline-visualizations/runtime")).status_code == 401
        assert (await client.get("/api/core/inline-visualizations/runtime", headers={"Authorization": f"Bearer {token}"})).status_code == 200
    transport = httpx.ASGITransport(app=create_app(), client=("203.0.113.5", 32100))
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:5172") as client:
        assert (await client.get("/api/core/inline-visualizations/runtime")).status_code == 403
