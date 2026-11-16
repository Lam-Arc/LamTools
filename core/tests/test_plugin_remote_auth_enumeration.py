"""user:“第三阶段先做Remote/网关的后端访问控制与明确方法名单”+(未通过插件令牌认证的Remote请求不泄露插件安装或启用状态)。"""
import httpx
import pytest
from fastapi import FastAPI

from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
from .test_plugin_http_routes import _host
from .test_plugin_remote_gateway import configure


@pytest.mark.asyncio
async def test_remote_invalid_token_does_not_disclose_plugin_availability(tmp_path):
    host, catalog, _ = _host(tmp_path)
    configure(host)
    token = plugin_http_token(host, "hook-demo")
    host.disable("hook-demo")
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        disabled = await client.post("/plugin-remote/hook-demo/demo/echo", json={"args": {"text": "x"}},
                                     headers={"x-plugin-token": "invalid"})
        missing = await client.post("/plugin-remote/not-installed/demo/echo", json={"args": {"text": "x"}},
                                    headers={"x-plugin-token": "invalid"})
        disabled_valid = await client.post("/plugin-remote/hook-demo/demo/echo", json={"args": {"text": "x"}},
                                            headers={"x-plugin-token": token})
    assert disabled.status_code == 401
    assert disabled.json() == {"error": "invalid plugin token"}
    assert missing.status_code == disabled.status_code
    assert missing.json() == disabled.json()
    assert disabled_valid.status_code == 409
