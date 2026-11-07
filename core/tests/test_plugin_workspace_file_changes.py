"""user:“第二阶段结束后 就继续开展第三阶段”+(会话文件变化复用原受管watch并实际回收，关联文件只在同一会话根解析)。"""
import asyncio
from copy import copy

import pytest

from .test_plugin_working_directory import env


async def ticks(stream, count):
    async with asyncio.timeout(3):
        while stream._watch._changes < count:
            await asyncio.sleep(0.005)


@pytest.mark.asyncio
async def test_real_file_change_delete_recreate_frames_and_ready_order(env):
    ctx, _, _, root = env
    path = root / "watch.txt"
    path.write_text("before")
    stream = await ctx.workspace_files.changes("s", "watch.txt", interval=0.01)
    try:
        assert await anext(stream) == {"kind": "ready"}
        path.write_text("changed-data")
        frame = await asyncio.wait_for(anext(stream), 3)
        assert frame["kind"] == "change" and frame["change"]["absolute_path"] == str(path)
        assert frame["change"]["bytes"] == len("changed-data") and frame["change"]["version"]
        path.unlink()
        assert (await asyncio.wait_for(anext(stream), 3))["change"]["absent"] is True
        path.write_text("rebuilt")
        assert (await asyncio.wait_for(anext(stream), 3))["change"]["bytes"] == 7
    finally:
        await stream.aclose()
    assert stream._watch._task.done()


@pytest.mark.asyncio
async def test_directory_changes_include_existing_child_metadata_updates(env):
    ctx, _, _, root = env
    path = root / "one" / "item.txt"
    path.write_text("first")
    stream = await ctx.workspace_files.changes("s", "one", interval=0.01)
    try:
        assert (await anext(stream))["kind"] == "ready"
        path.write_text("second-longer")
        first = (await asyncio.wait_for(anext(stream), 3))["change"]
        path.write_text("third-even-longer")
        second = (await asyncio.wait_for(anext(stream), 3))["change"]
        assert first["absolute_path"] == str(root / "one") and first["version"] != second["version"]
    finally:
        await stream.aclose()


@pytest.mark.asyncio
async def test_cancelled_next_closes_and_joins_actual_watch(env):
    ctx, _, _, root = env
    (root / "cancel.txt").write_text("unchanged")
    stream = await ctx.workspace_files.changes("s", "cancel.txt", interval=0.01)
    await anext(stream)
    pending = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert stream._watch._task.done() and not stream._fs._watches


@pytest.mark.asyncio
@pytest.mark.parametrize("dispose_scope", [False, True])
async def test_idle_consumer_does_not_prevent_close_or_plugin_disposal(env, dispose_scope):
    ctx, _, _, root = env
    (root / "idle.txt").write_text("before")
    stream = await ctx.workspace_files.changes("s", "idle.txt", interval=0.01)
    await anext(stream)
    (root / "idle.txt").write_text("after")
    await asyncio.wait_for(stream._available.wait(), 3)
    if dispose_scope:
        await asyncio.wait_for(ctx._registration_scope.dispose(), 3)
    else:
        await stream.aclose()
    assert stream._watch._task.done() and not stream._fs._watches


@pytest.mark.asyncio
async def test_replaced_directory_host_ends_watch_even_without_file_changes(env):
    ctx, _, _, root = env
    (root / "bound.txt").write_text("same")
    stream = await ctx.workspace_files.changes("s", "bound.txt", interval=0.01)
    await anext(stream)
    host = ctx.service("working_directory")
    try:
        ctx.set_service("working_directory", copy(host))
        await asyncio.wait_for(asyncio.shield(stream._watch._task), 3)
        with pytest.raises(ValueError) as error:
            await anext(stream)
        assert error.value.code == "workspace-file/host-changed"
        assert not stream._fs._watches
    finally:
        ctx.set_service("working_directory", host)
        await stream.aclose()


@pytest.mark.asyncio
async def test_missing_file_can_be_watched_then_recreated(env):
    ctx, _, _, root = env
    stream = await ctx.workspace_files.changes("s", "new.txt", interval=0.01)
    try:
        assert await anext(stream) == {"kind": "ready"}
        (root / "new.txt").write_text("new")
        assert (await asyncio.wait_for(anext(stream), 3))["change"]["bytes"] == 3
    finally:
        await stream.aclose()


@pytest.mark.asyncio
async def test_slow_consumer_coalesces_invalidations_in_one_latest_slot(env):
    ctx, _, _, root = env
    path = root / "slow.txt"
    path.write_text("start")
    stream = await ctx.workspace_files.changes("s", "slow.txt", interval=0.01)
    try:
        await anext(stream)
        path.write_text("one")
        await ticks(stream, 1)
        path.write_text("latest-long")
        await ticks(stream, 2)
        assert (await anext(stream))["change"]["bytes"] == len("latest-long")
        assert stream._latest is None
    finally:
        await stream.aclose()


@pytest.mark.asyncio
async def test_stream_capacity_is_released_after_actual_close(env, monkeypatch):
    from lamtools_core.plugin_system import workspace_file_changes
    monkeypatch.setattr(workspace_file_changes, "MAX_STREAMS", 2)
    ctx, _, _, root = env
    (root / "limit.txt").write_text("value")
    first = await ctx.workspace_files.changes("s", "limit.txt", interval=0.01)
    second = await ctx.workspace_files.changes("s", "limit.txt", interval=0.01)
    try:
        with pytest.raises(ValueError) as error:
            await ctx.workspace_files.changes("s", "limit.txt", interval=0.01)
        assert error.value.code == "workspace-file/watch-limit"
        await first.aclose()
        third = await ctx.workspace_files.changes("s", "limit.txt", interval=0.01)
        await third.aclose()
    finally:
        await first.aclose()
        await second.aclose()


@pytest.mark.asyncio
async def test_associated_binary_file_is_resolved_from_regular_base_inside_session(env):
    ctx, _, _, root = env
    (root / "one" / "base.txt").write_text("base")
    (root / "one" / "asset.bin").write_bytes(b"\x00\xff\x01")
    api = ctx.workspace_files
    whole = await api.read_bytes("s", "asset.bin", base_file="one/base.txt")
    assert whole["data"] == b"\x00\xff\x01" and whole["absolute_path"] == str(root / "one" / "asset.bin")
    window = await api.read_bytes("s", "asset.bin", base_file="one/base.txt", offset=1, length=1)
    assert window["data"] == b"\xff" and window["offset"] == 1 and not window["eof"]


@pytest.mark.asyncio
@pytest.mark.parametrize("path,base", [("/absolute.bin", "one/base.txt"), ("https://example.test/file", "one/base.txt"),
    ("asset.bin", "one"), ("../../outside.bin", "one/base.txt"), ("asset.bin", ""), ("asset.bin", [])])
async def test_associated_path_rejects_absolute_url_invalid_base_and_escape(env, path, base):
    ctx, _, _, root = env
    (root / "one" / "base.txt").write_text("base")
    with pytest.raises(ValueError):
        await ctx.workspace_files.read_bytes("s", path, base_file=base)


def test_changes_and_base_file_handoff_records_real_sdk_but_not_remote_stream(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root = source(tmp_path, {"index.ts": "export function apply(ctx) { ctx.workspaceFiles.changes(); ctx.workspaceFiles.readBytes(); }"})
    report = export_port(root, tmp_path / "ported")
    methods = {r["name"]: r for r in report["workspaceFileMethods"]}
    assert methods["workspaceFiles.changes"]["candidateContract"] == "context.workspace_files.changes"
    assert "轮询" in methods["workspaceFiles.changes"]["difference"]
    assert "base_file" in methods["workspaceFiles.readBytes"]["difference"]
    assert report["runtimeVerified"] is False


@pytest.mark.asyncio
async def test_repeated_close_caller_cancel_waits_for_native_join(env):
    ctx, _, _, root = env
    (root / "joined.txt").write_text("same")
    stream = await ctx.workspace_files.changes("s", "joined.txt", interval=0.01)
    original = stream._watch.aclose
    entered, release = asyncio.Event(), asyncio.Event()

    async def gated_close():
        entered.set()
        await release.wait()
        await original()

    stream._watch.aclose = gated_close
    caller = asyncio.create_task(stream.aclose())
    await entered.wait()
    caller.cancel()
    await asyncio.sleep(0)
    caller.cancel()
    await asyncio.sleep(0)
    assert not caller.done() and not stream._watch._task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await caller
    assert stream._watch._task.done() and not stream._fs._watches


@pytest.mark.asyncio
@pytest.mark.parametrize("interval", [True, 0, float("nan"), "1"])
async def test_invalid_poll_interval_leaves_no_watch(env, interval):
    ctx, _, _, root = env
    (root / "invalid.txt").write_text("same")
    with pytest.raises(ValueError) as error:
        await ctx.workspace_files.changes("s", "invalid.txt", interval=interval)
    assert error.value.code == "fs/invalid-watch"
    state = ctx._registration_scope._workspace_file_changes
    assert not state["streams"] and not state["roots"]
