from __future__ import annotations

import json
from io import BytesIO

import httpx
import pytest

from lamtools_core.tool import ToolCall
from lamtools_core.tool import web_tools
from lamtools_core.tool.web_tools import (
    make_web_fetch_handler,
    make_web_search_handler,
)


def _pdf_bytes_with_text(text: str) -> bytes:
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_reference = writer._add_object(font)
    page = writer.add_blank_page(width=612, height=792)
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_reference})}
    )
    content = DecodedStreamObject()
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    content.set_data(f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("latin-1"))
    page[NameObject("/Contents")] = writer._add_object(content)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


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
            arguments={
                "query": "example docs",
                "limit": 1,
                "domains": ["example.test"],
                "provider": "baidu",
            },
        )
    )

    assert result.status == "ok"
    assert result.metadata["provider"] == "baidu"
    assert result.metadata["result_count"] == 1  # limit=1 生效
    assert result.metadata["results"][0]["url"] == "https://docs.python.org/zh-cn/dev/whatsnew/3.14.html"
    assert result.artifacts[0].kind == "web_search_result"


@pytest.mark.asyncio
async def test_web_search_image_results_include_https_image_and_source_page(monkeypatch):
    from lamtools_core.tool.search import bing as search_bing

    payload = (
        "{&quot;murl&quot;:&quot;https://images.example.test/newton.jpg&quot;,"
        "&quot;purl&quot;:&quot;https://museum.example.test/newton&quot;,"
        "&quot;turl&quot;:&quot;https://thumb.example.test/newton.jpg&quot;,"
        "&quot;t&quot;:&quot;Newton portrait&quot;,&quot;desc&quot;:&quot;Museum portrait&quot;}"
    )

    class FakeResponse:
        status_code = 200
        text = f'<div class="iusc" m="{payload}"></div>'

    class FakeClient:
        async def get(self, url, params=None, **kwargs):
            assert "/images/search" in url
            return FakeResponse()

    async def fake_session(self):
        return FakeClient()

    monkeypatch.setattr(search_bing.BingSearchProvider, "_session", fake_session)
    tool = make_web_search_handler("")
    result = await tool(ToolCall(
        id="image-search",
        name="web_search",
        arguments={
            "query": "Newton portrait",
            "search_type": "image",
            "limit": 1,
            "provider": "bing",
        },
    ))

    assert result.status == "ok"
    assert result.metadata["search_type"] == "image"
    assert result.metadata["provider"] == "bing"
    assert result.metadata["results"][0]["image_url"] == "https://images.example.test/newton.jpg"
    assert result.metadata["results"][0]["url"] == "https://museum.example.test/newton"
    assert "Source page: https://museum.example.test/newton" in result.content


@pytest.mark.asyncio
async def test_web_search_image_does_not_semantically_filter_provider_results(monkeypatch):
    import html
    import json

    from lamtools_core.tool.search import bing as search_bing

    items = [
        {
            "murl": "https://cars.example.test/hongqi-h5.jpg",
            "purl": "https://cars.example.test/hongqi-h5",
            "t": "红旗 H5 汽车图片",
            "desc": "红旗轿车外观",
        },
        {
            "murl": "https://circuits.example.test/kvl-loop.png",
            "purl": "https://circuits.example.test/kirchhoff-voltage-law",
            "t": "Kirchhoff voltage law loop",
            "desc": "KVL circuit with voltage polarities",
        },
    ]
    payloads = "".join(
        f'<div class="iusc" m="{html.escape(json.dumps(item))}"></div>'
        for item in items
    )

    class FakeResponse:
        status_code = 200
        text = payloads

    class FakeClient:
        async def get(self, url, params=None, **kwargs):
            assert params["count"] >= 20
            assert params["mkt"] == "en-US"
            assert params["setlang"] == "en-us"
            return FakeResponse()

    async def fake_session(self):
        return FakeClient()

    monkeypatch.setattr(search_bing.BingSearchProvider, "_session", fake_session)
    tool = make_web_search_handler("")
    result = await tool(ToolCall(
        id="image-search-relevance",
        name="web_search",
        arguments={
            "query": "Kirchhoff's voltage law KVL simple loop schematic diagram",
            "search_type": "image",
            "limit": 5,
            "provider": "bing",
        },
    ))

    assert result.status == "ok"
    assert result.metadata["result_count"] == 2
    assert result.metadata["results"][0]["title"] == "红旗 H5 汽车图片"
    assert result.metadata["results"][1]["title"] == "Kirchhoff voltage law loop"


@pytest.mark.asyncio
async def test_web_search_image_returns_provider_results_for_model_judgment(monkeypatch):
    from lamtools_core.tool.search import bing as search_bing

    payload = (
        "{&quot;murl&quot;:&quot;https://cars.example.test/hongqi-h5.jpg&quot;,"
        "&quot;purl&quot;:&quot;https://cars.example.test/hongqi-h5&quot;,"
        "&quot;t&quot;:&quot;红旗 H5 汽车图片&quot;,&quot;desc&quot;:&quot;红旗轿车外观&quot;}"
    )

    class FakeResponse:
        status_code = 200
        text = f'<div class="iusc" m="{payload}"></div>'

    class FakeClient:
        async def get(self, url, params=None, **kwargs):
            return FakeResponse()

    async def fake_session(self):
        return FakeClient()

    monkeypatch.setattr(search_bing.BingSearchProvider, "_session", fake_session)
    tool = make_web_search_handler("")
    result = await tool(ToolCall(
        id="image-search-empty",
        name="web_search",
        arguments={
            "query": "Kirchhoff voltage law KVL",
            "search_type": "image",
            "limit": 5,
            "provider": "bing",
        },
    ))

    assert result.status == "ok"
    assert result.metadata["result_count"] == 1
    assert result.metadata["results"][0]["title"] == "红旗 H5 汽车图片"


@pytest.mark.asyncio
async def test_web_search_image_uses_configured_default_provider(monkeypatch):
    from lamtools_core.tool.search import duckduckgo

    async def fake_search_images(self, query, limit=5, domains=None):
        return [
            {
                "title": "KVL circuit",
                "url": "https://circuits.example.test/kvl",
                "snippet": query,
                "source": "ddg_images",
                "image_url": "https://circuits.example.test/kvl.png",
            }
        ]

    monkeypatch.setattr(duckduckgo.DuckDuckGoSearchProvider, "search_images", fake_search_images)
    tool = make_web_search_handler("")
    result = await tool(ToolCall(
        id="image-search-default",
        name="web_search",
        arguments={"query": "KVL circuit diagram", "search_type": "image", "limit": 1},
    ))

    assert result.status == "ok"
    assert result.metadata["provider"] == "ddg"
    assert result.metadata["attempted_providers"] == ["ddg"]


@pytest.mark.asyncio
async def test_duckduckgo_image_search_extracts_source_images_without_semantic_filter(monkeypatch):
    from lamtools_core.tool.search.duckduckgo import DuckDuckGoSearchProvider

    provider = DuckDuckGoSearchProvider()

    async def fake_search(query, limit=5, domains=None):
        return [
            {
                "title": "Circuit source",
                "url": "https://source.example.test/kvl",
                "snippet": "source summary",
                "source": "ddg",
            }
        ]

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "text/html; charset=utf-8"}
        text = '<meta property="og:image" content="https://cdn.example.test/candidate.png">'
        url = "https://source.example.test/kvl"

    class FakeClient:
        async def get(self, url, **kwargs):
            assert kwargs["headers"]["Range"] == "bytes=0-2097151"
            assert kwargs["timeout"] == 8.0
            return FakeResponse()

    async def fake_session():
        return FakeClient()

    monkeypatch.setattr(provider, "search", fake_search)
    monkeypatch.setattr(provider, "_session", fake_session)

    results = await provider.search_images("KVL circuit diagram", limit=1)

    assert results == [
        {
            "title": "Circuit source",
            "url": "https://source.example.test/kvl",
            "snippet": "source summary",
            "source": "ddg_images",
            "image_url": "https://cdn.example.test/candidate.png",
            "thumbnail_url": "",
        }
    ]


@pytest.mark.asyncio
async def test_web_search_falls_back_when_default_provider_fails(monkeypatch):
    from lamtools_core.tool.search import factory

    class FakeProvider:
        transport = "inproc"

        def __init__(self, name: str, *, error: str = "") -> None:
            self.name = name
            self.error = error

        async def search(self, query, limit=5, domains=None):
            if self.error:
                raise RuntimeError(self.error)
            return [{"title": "Fallback result", "url": "https://example.test", "snippet": query, "source": self.name}]

    monkeypatch.setattr(
        factory,
        "_default_config",
        lambda work_root=None, data_dir=None: {
            "provider": "baidu",
            "fallback_providers": ["ddg", "bing"],
        },
    )
    monkeypatch.setattr(
        factory,
        "get_provider",
        lambda name=None, config=None: FakeProvider("baidu", error="captcha")
        if name == "baidu"
        else FakeProvider(str(name)),
    )

    tool = factory.build_web_search_handler("")
    result = await tool(ToolCall(id="fallback", name="web_search", arguments={"query": "fallback"}))

    assert result.status == "ok"
    assert result.metadata["provider"] == "ddg"
    assert result.metadata["attempted_providers"] == ["baidu", "ddg"]
    assert result.metadata["provider_errors"] == {"baidu": "captcha"}


@pytest.mark.asyncio
async def test_web_search_explicit_provider_does_not_fall_back(monkeypatch):
    from lamtools_core.tool.search import factory

    class FakeProvider:
        transport = "inproc"

        def __init__(self, name: str) -> None:
            self.name = name

        async def search(self, query, limit=5, domains=None):
            raise RuntimeError(f"{self.name} unavailable")

    monkeypatch.setattr(
        factory,
        "_default_config",
        lambda work_root=None, data_dir=None: {
            "provider": "ddg",
            "fallback_providers": ["bing"],
        },
    )
    monkeypatch.setattr(factory, "get_provider", lambda name=None, config=None: FakeProvider(str(name)))

    tool = factory.build_web_search_handler("")
    result = await tool(ToolCall(
        id="explicit",
        name="web_search",
        arguments={"query": "strict", "provider": "baidu"},
    ))

    assert result.status == "failed"
    assert result.metadata["attempted_providers"] == ["baidu"]


def test_web_search_accepts_duckduckgo_alias():
    from lamtools_core.tool.search.factory import get_provider

    assert get_provider("duckduckgo").name == "ddg"


@pytest.mark.asyncio
async def test_duckduckgo_uses_configured_local_proxy_port(monkeypatch):
    from lamtools_core.tool.search import duckduckgo

    options: dict = {}
    client = object()

    def client_factory(**kwargs):
        options.update(kwargs)
        return client

    monkeypatch.setattr(duckduckgo.httpx, "AsyncClient", client_factory)
    provider = duckduckgo.DuckDuckGoSearchProvider({"proxy_port": 7890})

    assert await provider._session() is client
    assert options["proxy"] == "http://127.0.0.1:7890"


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
async def test_web_fetch_exposes_https_image_candidates_from_source_page(monkeypatch):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text=(
                '<html><head><meta property="og:image" '
                'content="https://cdn.example.test/portrait.jpg"></head>'
                '<body><main><img src="http://insecure.example.test/skip.jpg" alt="skip">'
                '<img src="/detail.png" alt="Detail view">Source text</main></body></html>'
            ),
            request=request,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=httpx.Timeout(5.0))
    monkeypatch.setattr(web_tools, "_HTTP_CLIENT", client)
    try:
        tool = make_web_fetch_handler("")
        result = await tool(ToolCall(id="fetch-images", name="web_fetch", arguments={"url": "https://example.test/doc"}))
    finally:
        await client.aclose()
        monkeypatch.setattr(web_tools, "_HTTP_CLIENT", None)

    candidates = result.metadata["image_candidates"]
    assert [item["url"] for item in candidates] == [
        "https://cdn.example.test/portrait.jpg",
        "https://example.test/detail.png",
    ]
    assert candidates[1]["alt"] == "Detail view"
    assert "[image candidates from this source page]" in result.content


@pytest.mark.asyncio
async def test_web_fetch_verifies_direct_image_without_decoding_binary_as_text(monkeypatch):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "image/png"},
            content=b"\x89PNG\r\n\x1a\n",
            request=request,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=httpx.Timeout(5.0))
    monkeypatch.setattr(web_tools, "_HTTP_CLIENT", client)
    try:
        tool = make_web_fetch_handler("")
        result = await tool(ToolCall(id="fetch-image", name="web_fetch", arguments={"url": "https://cdn.example.test/a.png"}))
    finally:
        await client.aclose()
        monkeypatch.setattr(web_tools, "_HTTP_CLIENT", None)

    assert result.status == "ok"
    assert result.metadata["verified_image"] is True
    assert result.metadata["content_type"] == "image/png"
    assert "Verified image response" in result.content


@pytest.mark.asyncio
@pytest.mark.parametrize("content_type", ["application/pdf", "application/octet-stream"])
async def test_web_fetch_parses_pdf_without_decoding_binary_as_text(monkeypatch, content_type):
    pdf = _pdf_bytes_with_text("TI current law evidence")

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": content_type},
            content=pdf,
            request=request,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=httpx.Timeout(5.0))
    monkeypatch.setattr(web_tools, "_HTTP_CLIENT", client)
    try:
        tool = make_web_fetch_handler("")
        result = await tool(
            ToolCall(
                id="fetch-pdf",
                name="web_fetch",
                arguments={"url": "https://www.ti.com/lit/pdf/slva477", "expect": "current law"},
            )
        )
    finally:
        await client.aclose()
        monkeypatch.setattr(web_tools, "_HTTP_CLIENT", None)

    assert result.status == "ok"
    assert result.metadata["document_format"] == "pdf"
    assert result.metadata["content_trust"] == "untrusted"
    assert result.metadata["expect_found"] is True
    assert result.metadata["warnings"]
    assert "## Page 1" in result.content
    assert "TI current law evidence" in result.content
    assert "%PDF-" not in result.content
    assert result.artifacts[0].content.startswith("[UNTRUSTED DOCUMENT CONTENT]")


@pytest.mark.asyncio
async def test_web_fetch_reports_invalid_pdf_as_parse_failure(monkeypatch):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/pdf"},
            content=b"not a pdf",
            request=request,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=httpx.Timeout(5.0))
    monkeypatch.setattr(web_tools, "_HTTP_CLIENT", client)
    try:
        tool = make_web_fetch_handler("")
        result = await tool(ToolCall(id="broken-pdf", name="web_fetch", arguments={"url": "https://example.test/a.pdf"}))
    finally:
        await client.aclose()
        monkeypatch.setattr(web_tools, "_HTTP_CLIENT", None)

    assert result.status == "failed"
    assert "PDF parsing failed" in result.error
    assert result.metadata["document_format"] == "pdf"


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


# ── 配置来源（2026-09-25 审计 P1：工作区文件不得参与内核选择）──────────

def test_web_search_config_ignores_workspace_file(tmp_path):
    """仓库里的 .lam/core/config/websearch.jsonc 不能指定要执行的命令。"""
    from lamtools_core.tool.search import factory

    work_root = tmp_path / "project"
    config_dir = work_root / ".lam" / "core" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "websearch.jsonc").write_text(
        json.dumps({"provider": "subprocess", "command": ["evil-binary"]}),
        encoding="utf-8",
    )

    cfg = factory._default_config(str(work_root), data_dir=tmp_path / "data")

    assert cfg["provider"] == factory.DEFAULT_PROVIDER
    assert not cfg["command"]


def test_web_search_config_reads_user_scope_jsonc(tmp_path):
    """用户配置根仍被读取，且字符串里的 URL 不被注释剥离器截断。"""
    from lamtools_core.config.root import core_config_file
    from lamtools_core.tool.search import factory

    target = core_config_file("websearch.jsonc")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "// 注释：内核地址见下\n"
        '{"provider": "http", "url": "https://search.example.test/api", "limit": 3}\n',
        encoding="utf-8",
    )

    cfg = factory._default_config(data_dir=tmp_path / "data")

    assert cfg["provider"] == "http"
    assert cfg["url"] == "https://search.example.test/api"
    assert cfg["limit"] == 3
