"""user:“给我把 2 阶段做完，前端除外”+(本地引用、内容裁剪、Web和计划限制验证实际行为)。"""
import asyncio
import threading
from pathlib import Path

import pytest

from lamtools_core.plugin_system import PluginContext


@pytest.fixture
def ctx(tmp_path):
    context = PluginContext(tmp_path)
    context._begin_registration_scope("content", 1)
    return context


def test_pruner_counts_unicode_preserves_rich_blocks_and_never_mutates(ctx):
    blocks = [{"type": "text", "text": "😀" * 20}, {"type": "image", "uri": "same"}, {"type": "text", "text": "尾" * 20}]
    assert ctx.tool_result_pruner.measure_content(blocks) == 40
    result = ctx.tool_result_pruner.prune_content(blocks, threshold_chars=30, head_chars=5, tail_chars=4)
    assert result[0]["text"].startswith("😀" * 5)
    assert result[-1]["text"].endswith("尾" * 4)
    assert result[1] == blocks[1]
    assert blocks[0]["text"] == "😀" * 20
    assert ctx.tool_result_pruner.prune_content(blocks, threshold_chars=100, head_chars=5, tail_chars=4) is None


@pytest.mark.asyncio
async def test_file_reference_search_is_deterministic_scoped_and_reports_scan_limit(ctx):
    root = ctx.work_root
    (root / "src").mkdir()
    for name in ("b.py", "a.py"):
        (root / "src" / name).write_text("value", encoding="utf8")
    result = await ctx.file_references.list("src/", limit=20)
    assert [row["path"] for row in result["items"]] == ["src/a.py", "src/b.py"]
    assert (await ctx.file_references.list(".py", limit=1))["truncated"]
    found = ctx.file_references.resolve("src/a.py")
    assert found["path"] == str(root / "src" / "a.py")
    with pytest.raises(Exception):
        ctx.file_references.resolve("../outside.py")
    await ctx._registration_scope.dispose()
    with pytest.raises(Exception):
        await ctx.file_references.list("")


@pytest.mark.asyncio
async def test_cancelled_reference_scan_keeps_scope_until_real_worker_stops(ctx,monkeypatch):
    # user:“完成真实接口、参数/错误、作用域、取消/清理”+(取消不能留下仍访问项目的扫描线程并提前放掉启动代租约)。
    from lamtools_core.plugin_system import content_access
    entered, release = threading.Event(), threading.Event()
    (ctx.work_root / "nested").mkdir()
    visited = []
    original = content_access.os.scandir
    def gated(path):
        visited.append(Path(path))
        entered.set()
        assert release.wait(3), "test must release the actual directory worker"
        return original(path)
    monkeypatch.setattr(content_access.os,"scandir",gated)
    task = asyncio.create_task(ctx.file_references.list())
    disposal = None
    try:
        assert await asyncio.to_thread(entered.wait,2)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done() and task in ctx._registration_scope._calls
        disposal = asyncio.create_task(ctx._registration_scope.dispose())
        await asyncio.sleep(0)
        assert not disposal.done()
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
    finally:
        release.set()
        await asyncio.gather(task,return_exceptions=True)
        if disposal is not None:
            await asyncio.wait_for(disposal,3)
        else:
            await ctx._registration_scope.dispose()
    assert task.cancelled() and not ctx._registration_scope._calls
    assert visited == [ctx.work_root]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 503])
@pytest.mark.parametrize("revoke", [False, True])
async def test_web_fetch_rechecks_scope_after_actual_http_response(ctx, monkeypatch, status, revoke):
    # user:“完成真实接口、参数/错误、作用域、取消/清理”+(真实HTTP等待后，成功和失败结果均不得越过撤回启动代发布，原返回语义保留)。
    import httpx
    from lamtools_core.tool import web_tools
    from lamtools_core.plugin_system.services import ServiceError
    entered, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()
    async def serve(reader, writer):
        try:
            await reader.readuntil(b"\r\n\r\n")
            entered.set()
            await release.wait()
            body = b"native http result"
            writer.write(f"HTTP/1.1 {status} Test\r\nContent-Type: text/plain\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode() + body)
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
            finished.set()
    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    async with httpx.AsyncClient(trust_env=False) as client:
        monkeypatch.setattr(web_tools, "_HTTP_CLIENT", client)
        task = asyncio.create_task(ctx.web.fetch(f"http://127.0.0.1:{port}/result"))
        try:
            await asyncio.wait_for(entered.wait(), 3)
            if revoke:
                ctx._registration_scope.revoke()
            release.set()
            if revoke:
                with pytest.raises(ServiceError) as error:
                    await task
                assert error.value.code == "service/scope-closed"
            else:
                result = await task
                assert result["status"] == ("ok" if status == 200 else "failed")
                assert "native http result" in result["content"]
            assert not ctx._registration_scope._calls
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
            server.close()
            await server.wait_closed()
            await asyncio.wait_for(finished.wait(), 3)
            await ctx._registration_scope.dispose()


@pytest.mark.asyncio
async def test_web_fetch_uses_native_transport_and_preserves_result_error(ctx, monkeypatch):
    import httpx
    from lamtools_core.tool import web_tools
    async def fetch(url):
        return httpx.Response(200, text="actual fetched text", headers={"content-type": "text/plain"}, request=httpx.Request("GET", url))
    monkeypatch.setattr(web_tools, "_fetch_with_loopback_bypass", fetch)
    result = await ctx.web.fetch("https://example.test/page")
    assert result["status"] == "ok" and "actual fetched text" in result["content"]
    assert result["metadata"]["url"] == "https://example.test/page"
    with pytest.raises(ValueError):
        await ctx.web.fetch("file:///private")
    await ctx._registration_scope.dispose()


@pytest.mark.asyncio
async def test_plan_mode_actually_restricts_tools_and_cleanup_restores(ctx):
    from lamtools_core.plugin_system.tool_extensions import ensure_tool_extensions
    host = ensure_tool_extensions(ctx)
    ctx._registration_scope.publish(set())
    assert host.allows("write_file", "s")
    ctx.plan_mode.enter("s")
    assert ctx.plan_mode.get("s")["active"]
    assert host.allows("read_file", "s")
    assert host.allows("list_dir", "s")
    assert host.allows("search_content", "s")
    assert not host.allows("write_file", "s")
    assert not host.allows("run_command", "s")
    assert host.allows("write_file", "other")
    ctx.plan_mode.exit("s")
    assert host.allows("write_file", "s")
    ctx.plan_mode.enter("s")
    await ctx._registration_scope.dispose()
    assert host.allows("write_file", "s")
