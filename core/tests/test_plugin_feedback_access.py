"""user:“给我把 2 阶段做完，前端除外”+(反馈必须真实持久化、版本冲突不丢写，隐藏会话不泄露)。"""
import asyncio

import pytest

from .test_plugin_working_directory import env


@pytest.mark.asyncio
async def test_message_feedback_versions_tombstones_and_reload(env):
    from lamtools_core.session import MessageRecord
    from lamtools_core.plugin_system.session_data import SessionDataError
    ctx, store, _, _ = env
    await store.add_message(MessageRecord(id="message", session_id="s", role="assistant", content="Answer"))
    first = await ctx.message_feedback.put("s", "message", rating="positive", if_version=None, note="Useful")
    assert first["version"] == 1 and first["rating"] == "positive"
    with pytest.raises(SessionDataError) as error:
        await ctx.message_feedback.put("s", "message", rating="negative", if_version=None)
    assert error.value.code == "session-data/conflict"
    await ctx._registration_scope.dispose()
    ctx._begin_registration_scope("example", 2)
    rows = await ctx.message_feedback.list("s")
    assert rows["items"][0]["note"] == "Useful"
    deleted = await ctx.message_feedback.delete("s", "message", if_version=1)
    assert deleted["version"] == 2
    assert (await ctx.message_feedback.list("s"))["items"] == []
    with pytest.raises(SessionDataError):
        await ctx.message_feedback.put("s", "message", rating="positive", if_version=1)
    assert (await ctx.message_feedback.put("s", "message", rating="negative", if_version=2))["version"] == 3


@pytest.mark.asyncio
async def test_feedback_target_visibility_owner_and_session_submission(env):
    from lamtools_core.plugin_system.session_data import SessionDataError
    ctx, store, _, project = env
    for sid in ("hidden", "unknown"):
        with pytest.raises(SessionDataError):
            await ctx.session_feedback.record(sid, text="feedback", request_id="one")
    with pytest.raises(SessionDataError):
        await ctx.message_feedback.put("s", "absent", rating="positive", if_version=None)
    first = await ctx.session_feedback.record("s", text="Please improve", category="quality", request_id="one")
    again = await ctx.session_feedback.record("s", text="Changed retry", request_id="one")
    assert first == again
    assert (await ctx.session_feedback.list("s"))["items"][0]["text"] == "Please improve"
    other = ctx.for_work_root(project)
    other._registration_scope = None
    other._begin_registration_scope("other", 1)
    assert (await other.session_feedback.list("s"))["items"] == []
    await other._registration_scope.dispose()


@pytest.mark.asyncio
async def test_feedback_competing_message_versions_allow_only_one_commit(env):
    from lamtools_core.session import MessageRecord
    from lamtools_core.plugin_system.session_data import SessionDataError
    ctx, store, _, _ = env
    await store.add_message(MessageRecord(id="m", session_id="s", role="assistant", content="answer"))
    results = await asyncio.gather(*[ctx.message_feedback.put("s", "m", rating=rating, if_version=None)
                                    for rating in ("positive", "negative")], return_exceptions=True)
    assert sum(isinstance(item, dict) for item in results) == 1
    assert sum(isinstance(item, SessionDataError) and item.code == "session-data/conflict" for item in results) == 1
