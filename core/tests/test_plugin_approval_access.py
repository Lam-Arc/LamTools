"""user:“继续，把 2 阶段都做完”+(审批请求必须有审计、缺省拒绝放行及代际撤回，不能把判断器当成已批准)。"""
import asyncio

import pytest

from lamtools_core.app.plugin_sessions import install_plugin_session_services
from lamtools_core.plugin_system import PluginContext
from .test_plugin_session_control import host, append


@pytest.mark.asyncio
async def test_approval_context_refresh_with_same_host_remains_valid(env):
    # user:“复用原宿主权威”+(宿主相同的上下文刷新仍可正常批准，不能把临时上下文对象身份当作授权权威)。
    from copy import copy
    requester, answerer, live, sessions = env
    answerer.approvals.answer(lambda request: "allowed-once")
    answerer._registration_scope.publish(set())
    original = sessions._factory
    sessions._factory = lambda: copy(live)
    try:
        result = await requester.approvals.request("s",tool_name="write_file",call_id="same-host")
        assert result.allowed
        audit = [row for row in (await sessions.events("s")).events if row["method"].startswith("plugin/approval")]
        assert len(audit) == 2 and audit[-1]["payload"]["outcome"] == "allowed-once"
    finally:
        sessions._factory = original


@pytest.mark.asyncio
@pytest.mark.parametrize("change",["shutdown","host"])
async def test_approval_host_invalidated_before_decision_commit_never_grants(env,monkeypatch,change):
    # user:“完成真实接口、参数/错误、作用域、取消/清理”+(回答已允许但提交决定前宿主失效，仍须持久记录取消，不能发出批准)。
    from types import SimpleNamespace
    from lamtools_core.app.plugin_sessions import PluginSessionService
    requester, answerer, live, sessions = env
    answerer.approvals.answer(lambda request: "allowed-once")
    answerer._registration_scope.publish(set())
    original = live.persistence.write
    entered, release = asyncio.Event(), asyncio.Event()
    async def gated(callback):
        if callback.__name__ == "decided":
            entered.set()
            await release.wait()
        return await original(callback)
    monkeypatch.setattr(live.persistence,"write",gated)
    task = asyncio.create_task(requester.approvals.request("s",tool_name="write_file",call_id="late-host"))
    factory = sessions._factory
    reader = PluginSessionService(lambda: live)
    try:
        await asyncio.wait_for(entered.wait(),3)
        if change == "shutdown":
            sessions.shutdown()
        else:
            sessions._factory = lambda: SimpleNamespace(persistence=live.persistence,host=SimpleNamespace())
        release.set()
        result = await asyncio.wait_for(task,3)
        assert not result.allowed and result.outcome == "cancelled"
        events = (await reader.events("s")).events
        audit = [row for row in events if row["method"].startswith("plugin/approval")]
        assert len(audit) == 2 and audit[-1]["payload"]["outcome"] == "cancelled"
        assert audit[-1]["payload"]["request_id"] == result.request_id
    finally:
        sessions._factory = factory
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task,return_exceptions=True)
        reader.shutdown()


@pytest.fixture
async def env(host, tmp_path):
    live, _ = host
    root = PluginContext(tmp_path)
    sessions = install_plugin_session_services(root, lambda: live)
    requester = root.for_work_root(tmp_path)
    requester._begin_registration_scope("requester", 1)
    answerer = root.for_work_root(tmp_path)
    answerer._begin_registration_scope("answerer", 1)
    await sessions.create(session_id="s")
    await append(live, "s", "turn/started", {"status": "running", "type": "turn"}, "turn-one")
    try:
        yield requester, answerer, live, sessions
    finally:
        await requester._registration_scope.dispose()
        await answerer._registration_scope.dispose()
        sessions.shutdown()


@pytest.mark.asyncio
async def test_missing_answerer_fails_closed_with_durable_audit_pair(env):
    requester, _, _, sessions = env
    result = await requester.approvals.request("s", tool_name="write_file", call_id="call-one", reason="change file")
    assert result.outcome == "unavailable" and not result.allowed
    rows = [e for e in (await sessions.events("s")).events if e["method"].startswith("plugin/approval")]
    assert [row["method"] for row in rows] == ["plugin/approvalAsked", "plugin/approvalDecided"]
    assert rows[0]["payload"]["request_id"] == rows[1]["payload"]["request_id"] == result.request_id


@pytest.mark.asyncio
async def test_owned_answerer_decides_exact_request_and_throwing_answerer_fails_closed(env):
    requester, answerer, _, _ = env
    seen = []
    def decide(request):
        seen.append(request)
        return "allowed-once"
    answerer.approvals.answer(decide)
    answerer._registration_scope.publish(set())
    result = await requester.approvals.request("s", tool_name="write_file", call_id="call-one")
    assert result.allowed and seen[0].plugin == "requester" and seen[0].turn_id == "turn-one"


@pytest.mark.asyncio
async def test_cancellation_is_audited_and_does_not_accept_late_answer(env):
    requester, answerer, _, sessions = env
    entered = asyncio.Event()
    async def block(request):
        entered.set()
        await asyncio.Event().wait()
    answerer.approvals.answer(block)
    answerer._registration_scope.publish(set())
    task = asyncio.create_task(requester.approvals.request("s", tool_name="write_file", call_id="call-one"))
    await asyncio.wait_for(entered.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    page = await sessions.events("s")
    assert page.events[-1]["method"] == "plugin/approvalDecided"
    assert page.events[-1]["payload"]["outcome"] == "cancelled"


@pytest.mark.asyncio
async def test_idle_request_is_rejected_without_audit(env):
    requester, _, _, sessions = env
    from lamtools_core.plugin_system import ApprovalAccessError
    await sessions.create(session_id="idle")
    before = (await sessions.state("idle")).last_event_seq
    with pytest.raises(ApprovalAccessError) as error:
        await requester.approvals.request("idle", tool_name="write_file", call_id="call-one")
    assert error.value.code == "approval/no-active-turn"
    assert (await sessions.state("idle")).last_event_seq == before


@pytest.mark.asyncio
async def test_cancellation_after_asked_commit_still_records_cancelled_decision(env, monkeypatch):
    requester, _, live, sessions = env
    original = live.persistence.write
    committed, release = asyncio.Event(), asyncio.Event()
    async def delayed(callback):
        result = await original(callback)
        if callback.__name__ == "asked":
            committed.set()
            await release.wait()
        return result
    monkeypatch.setattr(live.persistence, "write", delayed)
    task = asyncio.create_task(requester.approvals.request("s", tool_name="write_file", call_id="call-one"))
    await asyncio.wait_for(committed.wait(), 5)
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    rows = [row for row in (await sessions.events("s")).events if row["method"].startswith("plugin/approval")]
    assert len(rows) == 2 and rows[-1]["payload"]["outcome"] == "cancelled"


@pytest.mark.asyncio
async def test_revoked_answerer_late_allow_is_discarded(env):
    requester, answerer, _, _ = env
    entered = asyncio.Event()
    async def late(request):
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            return "allowed-once"
    answerer.approvals.answer(late)
    answerer._registration_scope.publish(set())
    task = asyncio.create_task(requester.approvals.request("s", tool_name="write_file", call_id="call-one"))
    await asyncio.wait_for(entered.wait(), 5)
    answerer._registration_scope.revoke()
    result = await task
    assert result.outcome == "cancelled" and not result.allowed


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["throw", "invalid"])
async def test_broken_answerer_is_unavailable_not_allowed(env, bad):
    requester, answerer, _, _ = env
    def broken(request):
        if bad == "throw":
            raise RuntimeError("private callback payload")
        return {"allowed": True}
    answerer.approvals.answer(broken)
    answerer._registration_scope.publish(set())
    assert (await requester.approvals.request("s", tool_name="write_file", call_id="call-one")).outcome == "unavailable"


@pytest.mark.asyncio
async def test_audit_failure_never_returns_grant(env, monkeypatch):
    from lamtools_core.plugin_system import ApprovalAccessError
    requester, answerer, live, _ = env
    answerer.approvals.answer(lambda request: "allowed-once")
    answerer._registration_scope.publish(set())
    original = live.persistence.write
    async def fail_decision(callback):
        if callback.__name__ == "decided":
            raise OSError("cannot commit")
        return await original(callback)
    monkeypatch.setattr(live.persistence, "write", fail_decision)
    with pytest.raises(ApprovalAccessError) as error:
        await requester.approvals.request("s", tool_name="write_file", call_id="call-one")
    assert error.value.code == "approval/audit-failed"
