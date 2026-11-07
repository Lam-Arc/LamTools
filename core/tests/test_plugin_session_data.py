"""user:“给我把 2 阶段做完，前端除外”+(附件、标题和只读投影使用真实数据库及现有会话可见性)。"""
import asyncio

import pytest

from .test_plugin_working_directory import env


@pytest.mark.asyncio
@pytest.mark.parametrize("method",["get","set"])
@pytest.mark.parametrize("change",["shutdown","store"])
async def test_title_read_wait_rejects_host_invalidation_before_return_or_write(env,monkeypatch,method,change):
    # user:“复用原宿主权威”+(共享会话数据读取后复核宿主，失效时不能返回旧标题或写回旧存储)。
    from lamtools_core.plugin_system.session_data import SessionDataError
    ctx, store, sessions, _ = env
    api = ctx.session_title
    host = sessions._context().host
    original = store.get_readonly_revision
    before = await original("s")
    entered, release = asyncio.Event(), asyncio.Event()
    async def gated(session_id):
        result = await original(session_id)
        entered.set()
        await release.wait()
        return result
    monkeypatch.setattr(store,"get_readonly_revision",gated)
    work = api.get("s") if method == "get" else api.set("s","late title",expected_revision=before[1])
    task = asyncio.create_task(work)
    try:
        await asyncio.wait_for(entered.wait(),3)
        if change == "shutdown":
            sessions.shutdown()
        else:
            host.session_store = object()
        release.set()
        with pytest.raises(SessionDataError) as error:
            await asyncio.wait_for(task,3)
        assert error.value.code == "session-data/" + ("closed" if change == "shutdown" else "host-changed")
        assert await original("s") == before
    finally:
        host.session_store = store
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task,return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("change",["shutdown","store","scope"])
async def test_readonly_session_data_rechecks_authority_before_publishing(env,monkeypatch,change):
    # user:“完成真实接口、参数/错误、作用域、取消/清理”+(共用只读门面返回前再检查宿主与启动代，不能发布等待期间失效的结果)。
    from lamtools_core.plugin_system.session_data import SessionDataError
    from lamtools_core.plugin_system.services import ServiceError
    ctx, store, sessions, _ = env
    api = ctx.session_title
    host = sessions._context().host
    original = api._host.call
    entered, release = asyncio.Event(), asyncio.Event()
    async def gated(*args,**kwargs):
        result = await original(*args,**kwargs)
        entered.set()
        await release.wait()
        return result
    monkeypatch.setattr(api._host,"call",gated)
    task = asyncio.create_task(api.get("s"))
    try:
        await asyncio.wait_for(entered.wait(),3)
        if change == "shutdown":
            sessions.shutdown()
        elif change == "store":
            host.session_store = object()
        else:
            ctx._registration_scope.revoke()
        release.set()
        with pytest.raises(ServiceError if change == "scope" else SessionDataError) as error:
            await asyncio.wait_for(task,3)
        assert error.value.code == {"shutdown":"session-data/closed","store":"session-data/host-changed","scope":"service/scope-closed"}[change]
    finally:
        host.session_store = store
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task,return_exceptions=True)


@pytest.mark.asyncio
async def test_attachment_content_and_index_survive_reload_and_are_session_scoped(env):
    from lamtools_core.plugin_system.session_data import SessionDataError
    ctx, _, _, project = env
    api = ctx.attachments
    item = await api.create("s", filename="sample.txt", content=b"actual saved content")
    assert item["session_id"] == "s"
    assert __import__("pathlib").Path(item["path"]).read_bytes() == b"actual saved content"
    assert (await api.get("s", item["id"]))["id"] == item["id"]
    assert "actual saved content" in (await api.preview("s", item["id"]))["text"]
    assert [row["id"] for row in (await api.list("s"))["items"]] == [item["id"]]
    for sid in ("hidden", "unknown"):
        with pytest.raises(SessionDataError) as error:
            await api.get(sid, item["id"])
        assert error.value.code == "session-data/not-found"
    await ctx._registration_scope.dispose()
    ctx._begin_registration_scope("example", 2)
    assert (await ctx.attachments.list("s"))["items"][0]["id"] == item["id"]


@pytest.mark.asyncio
async def test_reference_checks_project_paths_and_cross_session_ids(env):
    from lamtools_core.plugin_system.session_data import SessionDataError
    from lamtools_core.session import SessionRecord
    ctx, store, _, project = env
    await store.create(SessionRecord("other", "core", "Other", "idle", metadata={"work_root": str(project)}))
    (project / "input.txt").write_text("source", encoding="utf-8")
    item = await ctx.attachments.reference("s", "input.txt")
    assert item["path"] == str(project / "input.txt")
    assert item["metadata"]["managed"] is False
    with pytest.raises(SessionDataError) as error:
        await ctx.attachments.get("other", item["id"])
    assert error.value.code == "session-data/not-found"
    with pytest.raises(Exception):
        await ctx.attachments.reference("s", "../outside")


@pytest.mark.asyncio
async def test_title_cas_is_persistent_and_never_overwrites_concurrent_update(env):
    from lamtools_core.plugin_system.session_data import SessionDataError
    ctx, store, _, _ = env
    state = await ctx.session_title.get("s")
    saved = await ctx.session_title.set("s", "New title", expected_revision=state["revision"])
    assert saved["title"] == (await store.get_readonly("s")).title == "New title"
    with pytest.raises(SessionDataError) as error:
        await ctx.session_title.set("s", "Lost", expected_revision=state["revision"])
    assert error.value.code == "session-data/conflict"
    assert (await ctx.session_title.get("s"))["title"] == "New title"


@pytest.mark.asyncio
async def test_projection_is_fresh_bounded_and_never_returns_mutable_metadata(env):
    ctx, store, _, _ = env
    first = await ctx.session_projections.get("s")
    assert "metadata" not in first
    first["title"] = "caller mutation"
    assert (await ctx.session_projections.get("s"))["title"] == "Example"
    title = await ctx.session_title.get("s")
    await ctx.session_title.set("s", "Changed", expected_revision=title["revision"])
    assert (await ctx.session_projections.get("s"))["title"] == "Changed"
    page = await ctx.session_projections.events("s", after_seq=0, limit=2, max_bytes=4096)
    assert len(page.events) <= 2


@pytest.mark.asyncio
async def test_stopped_views_and_replaced_host_are_rejected(env):
    from lamtools_core.plugin_system.services import ServiceError
    from lamtools_core.plugin_system.session_data import SessionDataError
    ctx, _, sessions, _ = env
    api = ctx.session_title
    attachments = ctx.attachments
    await ctx._registration_scope.dispose()
    with pytest.raises(ServiceError):
        await api.get("s")
    with pytest.raises(ServiceError):
        await attachments.list("s")
    ctx._begin_registration_scope("example", 2)
    api = ctx.session_title
    sessions._context().host.session_store = object()
    with pytest.raises(SessionDataError) as error:
        await api.get("s")
    assert error.value.code == "session-data/host-changed"


@pytest.mark.asyncio
async def test_cancelled_title_save_joins_commit_before_releasing_scope(env, monkeypatch):
    ctx, store, _, _ = env
    state = await ctx.session_title.get("s")
    entered, release = asyncio.Event(), asyncio.Event()
    patch = store.patch
    async def delayed(*args, **kwargs):
        entered.set()
        await release.wait()
        return await patch(*args, **kwargs)
    monkeypatch.setattr(store, "patch", delayed)
    task = asyncio.create_task(ctx.session_title.set("s", "Committed", expected_revision=state["revision"]))
    await asyncio.wait_for(entered.wait(), 3)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (await store.get_readonly("s")).title == "Committed"


@pytest.mark.asyncio
async def test_existing_oversized_titles_have_explicitly_bounded_public_views(env):
    # user:“审查当前代码，然后继续”+(旧存储可能有超长标题，公开读取同样要限额并标注截断)。
    ctx, store, _, _ = env
    await store.patch("s", title="title" * 1000)
    for result in (await ctx.session_title.get("s"), await ctx.session_projections.get("s")):
        assert len(result["title"]) == 1024 and result["title_truncated"]
