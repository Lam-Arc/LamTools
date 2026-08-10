from __future__ import annotations

import httpx
import pytest

from lamtools_core.tool import ToolCall
from lamtools_core.tool import web_tools
from lamtools_core.tool.web_tools import (
    make_web_fetch_handler,
    make_web_search_handler,
)


@pytest.mark.asyncio
async def test_web_search_returns_structured_metadata_and_artifact(monkeypatch):
    """新架构：web_search 走 tool/search 包，默认百度 tn=json 内核。

    通过 monkeypatch BaiduSearchProvider 的网络层（httpx.AsyncClient.get）返回
    模拟的百度 JSON 响应，验证 handler 输出契约（metadata.results / artifacts）。
    """
    import json

    from lamtools_core.tool import web_tools
    from lamtools_core.tool.search import baidu as search_baidu

    fake_json = json.dumps(
        {
            "feed": {
                "entry": [
                    {
                        "title": "Python 3.14 有什么新变化",
                        "url": "https://docs.python.org/zh-cn/dev/whatsnew/3.14.html",
                        "abs": "Python 3.14 是 Python 编程语言的最新稳定发布版。",
                        "time": 1700000000,
                    },
                    {
                        "title": "Python 3.14 正式发布",
                        "url": "https://cloud.tencent.com/developer/article/1",
                        "abs": "本文深度解析 Python 3.14 核心新特性。",
                        "time": 1700000001,
                    },
                ]
            }
        },
        ensure_ascii=False,
    )

    class FakeResponse:
        status_code = 200
        text = fake_json
        headers = {}

        def json(self):
            return json.loads(self.text)

    class FakeClient:
        async def get(self, url, params=None, **kwargs):
            assert "tn" in (params or {})
            return FakeResponse()

    async def fake_session(self):
        return FakeClient()

    monkeypatch.setattr(search_baidu.BaiduSearchProvider, "_session", fake_session)
    tool = make_web_search_handler("")
    result = await tool(
        ToolCall(
            id="call-search",
            name="web_search",
            arguments={"query": "example docs", "limit": 1, "domains": ["example.test"]},
        )
    )

    assert result.status == "ok"
    assert result.metadata["provider"] == "baidu"
    assert result.metadata["result_count"] == 1  # limit=1 生效
    assert result.metadata["results"][0]["url"] == "https://docs.python.org/zh-cn/dev/whatsnew/3.14.html"
    assert result.artifacts[0].kind == "web_search_result"


@pytest.mark.asyncio
async def test_web_fetch_blocks_file_protocol():
    tool = make_web_fetch_handler("")

    result = await tool(ToolCall(id="call-fetch", name="web_fetch", arguments={"url": "file:///tmp/a.txt"}))

    assert result.status == "failed"
    assert "file:// protocol is blocked" in result.error


@pytest.mark.asyncio
async def test_web_fetch_returns_readable_html_artifact(monkeypatch):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text="<html><head><title>Example</title></head><body><main>Hello fetch</main></body></html>",
            request=request,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=httpx.Timeout(5.0))
    monkeypatch.setattr(web_tools, "_HTTP_CLIENT", client)
    try:
        tool = make_web_fetch_handler("")
        result = await tool(ToolCall(id="call-fetch", name="web_fetch", arguments={"url": "https://example.test/doc"}))
    finally:
        await client.aclose()
        monkeypatch.setattr(web_tools, "_HTTP_CLIENT", None)

    assert result.status == "ok"
    assert result.metadata["status_code"] == 200
    assert result.artifacts[0].kind == "web_fetch_content"
    assert "Hello fetch" in str(result.artifacts[0].content)


@pytest.mark.asyncio
async def test_web_fetch_reports_expected_text(monkeypatch):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text="<html><head><title>Demo</title></head><body>Hello Browser</body></html>",
            request=request,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=httpx.Timeout(5.0))
    monkeypatch.setattr(web_tools, "_HTTP_CLIENT", client)
    try:
        tool = make_web_fetch_handler("")
        result = await tool(
            ToolCall(
                id="call-fetch-expect",
                name="web_fetch",
                arguments={"url": "http://example.test/", "expect": "Hello Browser"},
            )
        )
    finally:
        await client.aclose()
        monkeypatch.setattr(web_tools, "_HTTP_CLIENT", None)

    assert result.status == "ok"
    assert "Hello Browser" in result.content
    assert "expect_found: true" in result.content
    assert result.metadata["expect_found"] is True


@pytest.mark.asyncio
async def test_web_fetch_fails_when_expected_text_missing(monkeypatch):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="nothing relevant here", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=httpx.Timeout(5.0))
    monkeypatch.setattr(web_tools, "_HTTP_CLIENT", client)
    try:
        tool = make_web_fetch_handler("")
        result = await tool(
            ToolCall(
                id="call-fetch-expect-miss",
                name="web_fetch",
                arguments={"url": "http://example.test/", "expect": "needle"},
            )
        )
    finally:
        await client.aclose()
        monkeypatch.setattr(web_tools, "_HTTP_CLIENT", None)

    assert result.status == "failed"
    assert "Expected text not found: needle" in result.error
    assert result.metadata["expect_found"] is False


@pytest.mark.asyncio
async def test_web_fetch_bypasses_system_proxy_for_loopback_urls(monkeypatch):
    real_client = httpx.AsyncClient
    created: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="local ok", request=request)

    def client_factory(**kwargs):
        created.append(dict(kwargs))
        return real_client(
            transport=httpx.MockTransport(handler),
            timeout=kwargs.get("timeout"),
            follow_redirects=kwargs.get("follow_redirects", False),
            headers=kwargs.get("headers"),
            trust_env=kwargs.get("trust_env", True),
        )

    monkeypatch.setattr(web_tools.httpx, "AsyncClient", client_factory)
    tool = make_web_fetch_handler("")
    result = await tool(ToolCall(
        id="call-fetch-local",
        name="web_fetch",
        arguments={"url": "http://localhost:8080/", "expect": "local ok"},
    ))

    assert result.status == "ok"
    assert any(options.get("trust_env") is False for options in created)
