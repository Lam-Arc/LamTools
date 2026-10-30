"""user:“给我把 2 阶段做完，前端除外”+(附件、标题和只读投影使用真实数据库及现有会话可见性)。"""
import asyncio

import pytest

from .test_plugin_working_directory import env


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
