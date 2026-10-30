"""user:“给我把 2 阶段做完，前端除外”+(跨会话引用仅构造可见项目的有限不可变摘录，不自动注入或启动模型)。"""
import pytest

from .test_plugin_working_directory import env
from lamtools_core.session import SessionRecord, MessageRecord


@pytest.mark.asyncio
async def test_candidates_and_prepared_excerpts_omit_hidden_self_and_outside_project(env):
    ctx, store, _, project = env
    await store.create(SessionRecord("reference", "core", "Reference", "idle", metadata={"work_root": str(project)}))
    await store.create(SessionRecord("outside", "core", "Outside", "idle", metadata={"work_root": str(project.parent)}))
    await store.add_message(MessageRecord("m", "reference", "assistant", "A useful result\n" * 100))
    candidates = await ctx.session_references.list_candidates("s")
    assert [row["session_id"] for row in candidates["items"]] == ["reference"]
    prepared = await ctx.session_references.prepare("s", ["reference"], max_chars=200)
    assert prepared["references"][0]["session_id"] == "reference"
    assert prepared["references"][0]["truncated"]
    assert len(prepared["references"][0]["text"]) <= 200
    assert prepared["published"] is False
    await store.add_message(MessageRecord("new", "reference", "user", "Later update"))
    assert "Later update" not in prepared["references"][0]["text"]
    with pytest.raises(Exception):
        await ctx.session_references.prepare("s", ["hidden"])
    with pytest.raises(Exception):
        await ctx.session_references.prepare("s", ["s"])


@pytest.mark.asyncio
async def test_reference_limits_and_stopped_scope(env):
    ctx, _, _, _ = env
    with pytest.raises(ValueError):
        await ctx.session_references.prepare("s", ["ref"] * 9)
    api = ctx.session_references
    await ctx._registration_scope.dispose()
    with pytest.raises(Exception):
        await api.list_candidates("s")
