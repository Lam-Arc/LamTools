from __future__ import annotations

import asyncio
import gzip
import os
import sys
import time

import httpx
import pytest

from lamtools_core.tool import ToolCall, web_tools
from lamtools_core.tool.search import factory
from lamtools_core.tool.search.baidu import BaiduSearchProvider
from lamtools_core.tool.search.bing import BingSearchProvider
from lamtools_core.tool.search.duckduckgo import DuckDuckGoSearchProvider
from lamtools_core.tool.search.external import ExternalSearchError, ExternalSearchProvider
from lamtools_core.tool.search.http_requests import ResponseTooLarge, bounded_request
from lamtools_core.tool.search.process import SearchProcessError, run_search_process


class Stream(httpx.AsyncByteStream):
    def __init__(self, chunks=None, *, drip=False):
        self.chunks = chunks or []
        self.drip = drip
        self.closed = False
        self.started = asyncio.Event()
        self.read_count = 0

    async def __aiter__(self):
        self.started.set()
        if self.drip:
            while True:
                await asyncio.sleep(0.01)
                self.read_count += 1
                yield b"x"
        for chunk in self.chunks:
            self.read_count += 1
            yield chunk

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
async def test_http_total_deadline_expires_despite_continuous_data():
    stream = Stream(drip=True)
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, stream=stream)
    )) as client:
        started = time.monotonic()
        with pytest.raises(httpx.TimeoutException, match="total time limit"):
            await bounded_request(client, "GET", "https://source.test", total_timeout=0.06)
        assert time.monotonic() - started < 0.5
    assert stream.read_count >= 2
    assert stream.closed


@pytest.mark.asyncio
async def test_http_size_limit_applies_without_content_length_and_closes_stream():
    stream = Stream([b"1234", b"56789", b"must not read"])
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, stream=stream)
    )) as client:
        with pytest.raises(ResponseTooLarge, match="8 byte decoded size limit"):
            await bounded_request(client, "GET", "https://source.test", total_timeout=1, max_response_bytes=8)
    assert stream.closed
    assert stream.read_count == 2


@pytest.mark.asyncio
async def test_http_size_limit_counts_decompressed_bytes():
    stream = Stream([gzip.compress(b"x" * 500)])
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, headers={"content-encoding": "gzip"}, stream=stream)
    )) as client:
        with pytest.raises(ResponseTooLarge):
            await bounded_request(client, "GET", "https://source.test", total_timeout=1, max_response_bytes=100)
    assert stream.closed


@pytest.mark.asyncio
async def test_http_normal_compressed_text_is_decoded_once():
    stream = Stream([gzip.compress("source text 中文".encode())])
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, headers={
            "content-encoding": "gzip", "content-type": "text/plain; charset=utf-8",
        }, stream=stream)
    )) as client:
        result = await bounded_request(client, "GET", "https://source.test", total_timeout=1)
    assert result.text == "source text 中文"
    assert stream.closed


@pytest.mark.asyncio
async def test_http_redirect_skips_body_and_preserves_post_redirect_and_cookie_rules():
    redirect_stream = Stream(drip=True)
    requests = []

    def handle(request):
        requests.append(request)
        if request.url.path == "/start":
            return httpx.Response(302, headers={
                "location": "/end", "set-cookie": "source_cookie=yes; Path=/",
            }, stream=redirect_stream)
        assert request.method == "GET"
        assert request.headers["cookie"] == "source_cookie=yes"
        return httpx.Response(200, text="final source")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle), follow_redirects=True) as client:
        result = await bounded_request(
            client, "POST", "https://source.test/start", total_timeout=0.2, data={"q": "query"}
        )
    assert result.text == "final source"
    assert str(result.url) == "https://source.test/end"
    assert len(requests) == 2
    assert redirect_stream.read_count == 0
    assert redirect_stream.closed


@pytest.mark.asyncio
async def test_http_cancel_closes_response_and_stays_cancelled():
    stream = Stream(drip=True)
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, stream=stream)
    )) as client:
        task = asyncio.create_task(bounded_request(client, "GET", "https://source.test", total_timeout=10))
        await asyncio.wait_for(stream.started.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=0.5)
    assert stream.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_type", [BaiduSearchProvider, BingSearchProvider, DuckDuckGoSearchProvider])
async def test_builtin_search_providers_use_bounded_streaming(provider_type):
    stream = Stream(drip=True)
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, stream=stream)
    )) as client:
        provider = provider_type({"timeout": 0.05})
        provider._client = client
        search = provider._search_once if provider_type is BaiduSearchProvider else provider.search
        with pytest.raises(httpx.TimeoutException, match="total time limit"):
            await search("query", 1, None)
    assert stream.closed


@pytest.mark.asyncio
async def test_external_http_search_uses_bounded_streaming(monkeypatch):
    from lamtools_core.tool.search import external

    stream = Stream(drip=True)
    client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, stream=stream)
    ))
    monkeypatch.setattr(external.httpx, "AsyncClient", lambda **kwargs: client)
    provider = ExternalSearchProvider("test", "http", url="https://source.test", timeout=0.05)
    with pytest.raises(ExternalSearchError, match="total time limit"):
        await provider.search("query")
    assert stream.closed


@pytest.mark.asyncio
async def test_web_fetch_reports_oversized_response(monkeypatch):
    stream = Stream([b"123456789"])
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, stream=stream)
    )) as client:
        monkeypatch.setattr(web_tools, "_http_session", lambda *args: client)
        monkeypatch.setattr(web_tools, "_FETCH_MAX_RESPONSE_BYTES", 8)
        result = await web_tools.make_web_fetch_handler("")(
            ToolCall("fetch", "web_fetch", {"url": "https://source.test"})
        )
    assert result.status == "failed"
    assert result.error_code == "fetch_response_too_large"
    assert "8 byte" in result.error
    assert stream.closed


@pytest.mark.asyncio
async def test_web_fetch_total_budget_covers_entire_redirect_chain(monkeypatch):
    async def handle(request):
        await asyncio.sleep(0.04)
        return httpx.Response(302, headers={"location": "/another"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        monkeypatch.setattr(web_tools, "_http_session", lambda *args: client)
        monkeypatch.setattr(web_tools, "_FETCH_TOTAL_TIMEOUT", 0.06)
        result = await web_tools.make_web_fetch_handler("")(
            ToolCall("fetch", "web_fetch", {"url": "https://source.test"})
        )
    assert result.status == "failed"
    assert result.error_code == "fetch_timeout"


@pytest.mark.asyncio
async def test_search_total_budget_covers_provider_retries_and_fallbacks(monkeypatch):
    class Provider:
        name = "test"
        async def search(self, *args, **kwargs):
            await asyncio.Event().wait()

    monkeypatch.setattr(factory, "_default_config", lambda *args, **kwargs: {"fallback_providers": []})
    monkeypatch.setattr(factory, "get_provider", lambda *args, **kwargs: Provider())
    monkeypatch.setattr(factory, "SEARCH_TOTAL_TIMEOUT_SECONDS", 0.05)
    result = await factory.build_web_search_handler("")(ToolCall("search", "web_search", {"query": "q"}))
    assert result.status == "failed"
    assert result.error_code == "search_timeout"
    assert "including retries and fallback" in result.error


def _pid_running(pid):
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x00100000, False, pid)
        if not handle:
            return False
        try:
            return kernel.WaitForSingleObject(handle, 0) == 258
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


async def _wait_for_file(path):
    async with asyncio.timeout(3):
        while not path.exists():
            await asyncio.sleep(0.01)
    return int(path.read_text())


@pytest.mark.asyncio
async def test_external_search_success_keeps_json_contract():
    script = 'import json,sys; q=json.loads(sys.argv[1])["query"]; print(json.dumps({"results":[{"title":q,"url":"https://source.test","snippet":"ok"}]}))'
    provider = ExternalSearchProvider("test", "subprocess", command=[sys.executable, "-c", script], timeout=3)
    results = await provider.search("original query")
    assert results == [{"title": "original query", "url": "https://source.test", "snippet": "ok", "source": "external"}]


@pytest.mark.asyncio
@pytest.mark.parametrize("finish", ["cancel", "timeout", "success"])
async def test_external_search_cleans_descendants_that_inherit_output(tmp_path, finish):
    root_pid_path = tmp_path / "root.pid"
    child_pid_path = tmp_path / "child.pid"
    child = f"import os,pathlib,time; pathlib.Path({str(child_pid_path)!r}).write_text(str(os.getpid())); time.sleep(3)"
    script = (
        "import os,pathlib,subprocess,sys,time; "
        f"pathlib.Path({str(root_pid_path)!r}).write_text(str(os.getpid())); "
        f"subprocess.Popen([sys.executable,'-c',{child!r}]); "
        f"p=pathlib.Path({str(child_pid_path)!r}); "
        "\nwhile not p.exists(): time.sleep(.01)\n"
        + ('print(\'{"results":[]}\', flush=True)' if finish == "success" else "time.sleep(3)")
    )
    provider = ExternalSearchProvider(
        "test", "subprocess", command=[sys.executable, "-c", script],
        timeout=0.4 if finish == "timeout" else 3,
    )
    task = asyncio.create_task(provider.search("q"))
    root_pid = await _wait_for_file(root_pid_path)
    child_pid = await _wait_for_file(child_pid_path)
    started = time.monotonic()
    if finish == "cancel":
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 4)
    elif finish == "timeout":
        with pytest.raises(ExternalSearchError, match="total time limit"):
            await asyncio.wait_for(task, 4)
    else:
        assert await asyncio.wait_for(task, 4) == []
    assert time.monotonic() - started < 3.5
    # Killing a Windows job is asynchronous for descendants. Allow a brief
    # reap interval while still proving cleanup rather than natural 3s exit.
    async with asyncio.timeout(1):
        while _pid_running(root_pid) or _pid_running(child_pid):
            await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_external_search_output_is_bounded():
    with pytest.raises(SearchProcessError, match="byte limit"):
        await run_search_process(
            [sys.executable, "-c", "print('x'*4096)"], timeout=3,
            env=dict(os.environ), max_output_bytes=128,
        )
