from __future__ import annotations

import httpx
import pytest

from lamtools_core.tool import ToolCall
from lamtools_core.tool import web_tools
from lamtools_core.tool.web_tools import (
    make_browser_check_handler,
    make_web_fetch_handler,
    make_web_search_handler,
)


@pytest.mark.asyncio
async def test_web_search_returns_structured_metadata_and_artifact(monkeypatch):
    html = """
    <html><body>
      <a class="result__a" href="https://example.test/doc">Example Docs</a>
      <a class="result__snippet">Official docs snippet</a>
    </body></html>
    """
    requested_body = ""

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requested_body
        requested_body = request.content.decode("utf-8", errors="replace")
        return httpx.Response(200, text=html, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=httpx.Timeout(5.0))
    monkeypatch.setattr(web_tools, "_HTTP_CLIENT", client)
    try:
        tool = make_web_search_handler("")
        result = await tool(
            ToolCall(
                id="call-search",
                name="web_search",
                arguments={"query": "example docs", "limit": 1, "domains": ["example.test"]},
            )
        )
    finally:
        await client.aclose()
        monkeypatch.setattr(web_tools, "_HTTP_CLIENT", None)

    assert result.status == "ok"
    assert result.metadata["result_count"] == 1
    assert result.metadata["results"][0]["url"] == "https://example.test/doc"
    assert result.artifacts[0].kind == "web_search_result"
    assert "site%3Aexample.test" in requested_body


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
async def test_browser_check_reports_expected_text(monkeypatch):
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
        tool = make_browser_check_handler("")
        result = await tool(
            ToolCall(
                id="call-browser",
                name="browser_check",
                arguments={"url": "http://example.test/", "expect": "Hello Browser"},
            )
        )
    finally:
        await client.aclose()
        monkeypatch.setattr(web_tools, "_HTTP_CLIENT", None)

    assert result.status == "ok"
    assert "title: Demo" in result.content
    assert result.metadata["expect_found"] is True


@pytest.mark.asyncio
async def test_browser_check_bypasses_system_proxy_for_loopback_urls(monkeypatch):
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
    tool = make_browser_check_handler("")
    result = await tool(ToolCall(
        id="call-browser-local",
        name="browser_check",
        arguments={"url": "http://localhost:8080/", "expect": "local ok"},
    ))

    assert result.status == "ok"
    assert any(options.get("trust_env") is False for options in created)
