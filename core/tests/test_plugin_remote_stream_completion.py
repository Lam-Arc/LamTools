"""user:“建立真实请求、错误、作用域、取消/流和清理验收”+(流终止也须复核原授权，撤回不能伪装正常完成)。"""
import asyncio
import json

import httpx
import pytest

from .test_plugin_remote_stream import setup
from .test_plugin_remote_gateway import configure
from lamtools_core.plugin_system.plugin_http import plugin_http_token


@pytest.mark.asyncio
@pytest.mark.parametrize("withdraw", ["declaration", "token", "generation"])
async def test_withdrawal_inside_source_completion_never_sends_success_end(tmp_path, withdraw):
    closed = asyncio.Event()
    async def source():
        try:
            yield "last-authorized-item"
            if withdraw == "declaration":
                configure(host, remove=True)
            elif withdraw == "token":
                host.backend_manager.context._secret_store.view("hook-demo").delete("httpToken")
            else:
                host.backend_manager.generation["hook-demo"] = 777
        finally:
            closed.set()
    host, _, app = setup(tmp_path, source())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/plugin-remote/hook-demo/demo/echo", json={"args": {"text": "last"}},
            headers={"x-plugin-token": plugin_http_token(host, "hook-demo")})
    assert response.status_code == 200
    frames = [json.loads(line) for line in response.iter_lines()]
    assert frames[0] == {"kind": "item", "payload": "last-authorized-item"}
    assert frames[-1]["kind"] == "error" and all(frame["kind"] != "end" for frame in frames)
    assert closed.is_set() and not host._remote_stream_slots
