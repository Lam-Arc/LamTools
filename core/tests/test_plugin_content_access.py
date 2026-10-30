"""user:“给我把 2 阶段做完，前端除外”+(本地引用、内容裁剪、Web和计划限制验证实际行为)。"""
import asyncio
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
    assert not host.allows("write_file", "s")
    assert not host.allows("run_command", "s")
    assert host.allows("write_file", "other")
    ctx.plan_mode.exit("s")
    assert host.allows("write_file", "s")
    ctx.plan_mode.enter("s")
    await ctx._registration_scope.dispose()
    assert host.allows("write_file", "s")
