"""user:“逐项核对固定上游源码及手册，建立真实请求、错误、作用域、取消/流和清理验收。”+(验证Host探测并发、失败缓存和卸载清理，不发起真实公网请求)。"""
import asyncio

import httpx
import pytest


OFFICIAL = "https://registry.npmjs.org/"
MIRROR = "https://registry.npmmirror.com/"


class _TrackedStream(httpx.AsyncByteStream):
    def __init__(self, closed):
        self.closed = closed

    async def __aiter__(self):
        yield b"ignored response body"

    async def aclose(self):
        self.closed.set()


def _context(tmp_path, monkeypatch, handler, *, options=None):
    from lamtools_core.plugin_system import registry_probe
    from lamtools_core.plugin_system.context import PluginContext
    from lamtools_core.plugin_system.services import HostServiceRegistry

    client_options = []
    real_client = httpx.AsyncClient
    monkeypatch.setattr(registry_probe, "httpx_client_kwargs", lambda url: {})
    def client_factory(**kwargs):
        client_options.append({"timeout": kwargs["timeout"], "follow_redirects": kwargs["follow_redirects"]})
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(registry_probe.httpx, "AsyncClient", client_factory)
    ctx = PluginContext(work_root=tmp_path, _service_registry=HostServiceRegistry({}),
                        registry_probe_options=options or {})
    scope = ctx._begin_registration_scope("probe-test", 1)
    return ctx, scope, client_options


@pytest.mark.asyncio
@pytest.mark.parametrize("winner", [OFFICIAL, MIRROR])
async def test_fastest_shares_probe_cancels_loser_closes_response_and_caches(tmp_path, monkeypatch, winner):
    started = {OFFICIAL + "-/ping": asyncio.Event(), MIRROR + "-/ping": asyncio.Event()}
    loser_cancelled, body_closed = asyncio.Event(), asyncio.Event()
    calls = []

    async def handle(request):
        url = str(request.url)
        calls.append((url, request.extensions.get("timeout")))
        started[url].set()
        if url != winner + "-/ping":
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                loser_cancelled.set()
                raise
        return httpx.Response(204, stream=_TrackedStream(body_closed))

    ctx, scope, client_options = _context(tmp_path, monkeypatch, handle)
    api = ctx.plugin_registry_probe
    first = asyncio.create_task(api.fastest())
    second = asyncio.create_task(api.fastest())
    try:
        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in started.values())), 2)
        assert await asyncio.gather(first, second) == [winner, winner]
        assert loser_cancelled.is_set()
        assert body_closed.is_set()
        assert await api.fastest() == winner
        assert len(calls) == 2
        assert {row[0] for row in calls} == {OFFICIAL + "-/ping", MIRROR + "-/ping"}
        assert len(client_options) == 2 and all(row["follow_redirects"] is False for row in client_options)
    finally:
        await scope.dispose()


@pytest.mark.asyncio
async def test_unavailable_result_is_cached(tmp_path, monkeypatch):
    calls = 0

    async def fail(request):
        nonlocal calls
        calls += 1
        return httpx.Response(503)

    ctx, scope, _ = _context(tmp_path, monkeypatch, fail)
    api = ctx.plugin_registry_probe
    try:
        assert await api.fastest() is None
        assert await api.fastest() is None
        assert calls == 2
    finally:
        await scope.dispose()


@pytest.mark.asyncio
async def test_scope_disposal_cancels_and_joins_probe(tmp_path, monkeypatch):
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def hang(request):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    ctx, scope, _ = _context(tmp_path, monkeypatch, hang)
    request = asyncio.create_task(ctx.plugin_registry_probe.fastest())
    await asyncio.wait_for(started.wait(), 2)
    await scope.dispose()
    with pytest.raises(asyncio.CancelledError):
        await request
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_disabled_probe_makes_no_request_and_rejects_use_after_disposal(tmp_path, monkeypatch):
    async def unexpected(request):
        raise AssertionError("disabled probe must not send requests")

    ctx, scope, _ = _context(tmp_path, monkeypatch, unexpected, options={"enabled": False})
    api = ctx.plugin_registry_probe
    assert not api.enabled
    assert await api.fastest() is None
    await scope.dispose()
    with pytest.raises(Exception, match="scope-closed"):
        await api.fastest()


@pytest.mark.asyncio
async def test_timeout_cancels_and_joins_both_requests(tmp_path, monkeypatch):
    cancelled = 0
    both_started = asyncio.Event()
    starts = 0

    async def hang(request):
        nonlocal cancelled, starts
        starts += 1
        if starts == 2:
            both_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled += 1
            raise

    ctx, scope, client_options = _context(tmp_path, monkeypatch, hang, options={"timeout_ms": 25})
    try:
        api = ctx.plugin_registry_probe
        task = asyncio.create_task(api.fastest())
        await asyncio.wait_for(both_started.wait(), 2)
        assert await task is None
        assert cancelled == 2
        assert len(client_options) == 2 and all(row["timeout"] == 0.025 for row in client_options)
    finally:
        await scope.dispose()


def test_migration_recommends_host_probe_without_claiming_client_compatibility(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port

    root = source(tmp_path, {"index.ts": "export function apply(ctx) { ctx.pluginRegistryProbe.fastest() }"})
    export_port(root, tmp_path / "ported")
    report = (tmp_path / "ported" / "PORTING.md").read_text(encoding="utf-8")
    assert "context.plugin_registry_probe.fastest" in report
    assert "浏览器初始选择/安装界面" in report
