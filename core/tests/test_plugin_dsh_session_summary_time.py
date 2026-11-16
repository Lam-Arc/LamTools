"""Acceptance tests for the current-project DSH session-summary approximation."""

import asyncio
from dataclasses import asdict
from datetime import datetime

import httpx
import pytest
from fastapi import FastAPI

from .test_plugin_workspace_registry_current import workspace_env
from .test_plugin_workspace_sessions import populated


@pytest.mark.asyncio
async def test_project_session_summary_exposes_latest_core_prompt_acceptance_time(populated):
    # user:“每一个地方 sunday 都有等价或者近似接口”+(为DSH的lastPromptAt提供原Core最近输入接收时间近似，明确不称为原提示时间)。
    from lamtools_core.app.core_db import CoreAppEvent

    _, db, _, _, _, _ = populated
    first = datetime(2025, 7, 8, 9, 10, 11)
    latest = datetime(2025, 7, 9, 10, 11, 12)
    unrelated = datetime(2025, 7, 10, 11, 12, 13)
    async with db.session_factory() as session:
        session.add_all([
            CoreAppEvent(event_id="prompt-a-1", thread_id="a", seq=1,
                         method="turn/accepted", payload_json={"type": "turn"}, created_at=first),
            CoreAppEvent(event_id="prompt-a-2", thread_id="a", seq=2,
                         method="turn/accepted", payload_json={"type": "turn"}, created_at=latest),
            CoreAppEvent(event_id="later-non-prompt", thread_id="a", seq=3,
                         method="thread/metadata", payload_json={}, created_at=unrelated),
            CoreAppEvent(event_id="prompt-b-1", thread_id="b", seq=1,
                         method="turn/accepted", payload_json={"type": "turn"}, created_at=first),
            CoreAppEvent(event_id="prompt-hidden", thread_id="hidden", seq=1,
                         method="turn/accepted", payload_json={"type": "turn"}, created_at=unrelated),
        ])
        await session.commit()

    ctx, _, _, project, _, _ = populated
    page = await ctx.session_controller.list_current_project(limit=50)
    items = {item.session_id: item for item in page.items}
    assert items["a"].last_prompt_received_at_ms == int(latest.timestamp() * 1000)
    assert items["b"].last_prompt_received_at_ms == int(first.timestamp() * 1000)
    assert "hidden" not in items and all(item.cwd == str(project.work_root) for item in items.values())


@pytest.mark.asyncio
async def test_project_session_summary_carries_original_record_updated_time_through_authenticated_http(
    populated, tmp_path,
):
    # user:“逐项核对固定上游源码及手册，建立真实请求、错误、作用域、取消/流和清理验收”+(复用原会话更新时间并通过认证HTTP返回，明确其为Sunday近似字段)。
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.app.core_db import CoreAppEvent
    from lamtools_core.app.core_db import CoreThreadSnapshot
    from lamtools_core.app.operation_catalog import OperationResult
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token

    ctx, db, catalog, project, _, _ = populated
    updated_at = datetime(2025, 6, 7, 8, 9, 10)
    prompt_received_at = datetime(2025, 6, 8, 9, 10, 11)
    async with db.project_store.session_factory() as session:
        row = await session.get(CoreThreadSnapshot, "a")
        row.updated_at = updated_at
        session.add(CoreAppEvent(
            event_id="remote-prompt-a",
            thread_id="a",
            seq=1,
            method="turn/accepted",
            payload_json={"type": "turn"},
            created_at=prompt_received_at,
        ))
        await session.commit()

    host, _, original = _host(tmp_path)
    configure(host)
    ctx._secret_store = original._secret_store
    host.backend_manager.context = ctx
    manifest_path = host.get("hook-demo").root / "plugin.json"
    import json
    manifest = json.loads(manifest_path.read_text(encoding="utf8"))
    manifest["operations"].append({
        "name": "hook-demo.session-list-time",
        "handler": "ops:session_list_time",
        "permission": "auto_allow",
    })
    manifest["http"]["routes"].append({
        "method": "POST",
        "path": "/session-list-time",
        "operation": "hook-demo.session-list-time",
    })
    manifest_path.write_text(json.dumps(manifest), encoding="utf8")
    (manifest_path.parent / "ops.py").write_text(
        "from dataclasses import asdict\n"
        "from lamtools_core.app.operation_catalog import OperationResult\n"
        "async def session_list_time(request, *, context):\n"
        "    page = await context.session_controller.list_current_project(limit=50)\n"
        "    return OperationResult(request.name, {'items': [asdict(item) for item in page.items]})\n",
        encoding="utf8",
    )
    host._invalidate()
    catalog.unregister_owner("plugin:hook-demo")
    register_plugin_operations(catalog, host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        url = "/plugin-http/hook-demo/session-list-time"
        rejected = await client.post(url, json={"args": {"text": "read"}}, headers={"x-plugin-token": "wrong"})
        response = await client.post(
            url,
            json={"args": {"text": "read"}},
            headers={"x-plugin-token": plugin_http_token(host, "hook-demo")},
        )

    assert rejected.status_code == 401
    assert response.status_code == 200, response.text
    items = response.json()["payload"]["items"]
    item = next(row for row in items if row["session_id"] == "a")
    assert item["updated_at_ms"] == int(updated_at.timestamp() * 1000)
    assert item["last_prompt_received_at_ms"] == int(prompt_received_at.timestamp() * 1000)
    assert item["cwd"] == str(project.work_root)
    assert item["session_id"] != project.id


@pytest.mark.asyncio
async def test_project_session_summary_rejects_unusable_original_update_time(populated, monkeypatch):
    # user:“建立真实请求、错误、作用域、取消/流和清理验收”+(原记录不能提供可转换更新时间时返回明确宿主错误，不伪造时间值)。
    from lamtools_core.plugin_system.session_query import SessionQueryError

    ctx, _, _, _, _, store = populated
    original = store.get_readonly

    async def invalid_timestamp(session_id):
        record = await original(session_id)
        if record is not None and session_id == "a":
            record.updated_at = "not-a-time"
        return record

    monkeypatch.setattr(store, "get_readonly", invalid_timestamp)
    with pytest.raises(SessionQueryError) as error:
        await ctx.session_controller.list_current_project(limit=50)
    assert error.value.code == "session-query/invalid-result"


@pytest.mark.asyncio
async def test_project_session_summary_cwd_stays_within_visible_project(populated, monkeypatch):
    # user:“不把插件权限扩展成全局Peer访问”+(cwd路径提示只随原当前项目可见列表返回，不泄漏隐藏或其他项目会话目录)。
    ctx, _, _, project, _, _ = populated
    sessions = ctx.session_controller._sessions.get()
    original = sessions.state
    state_reads = []

    async def track_state(session_id):
        state_reads.append(session_id)
        return await original(session_id)

    monkeypatch.setattr(sessions, "state", track_state)
    page = await ctx.session_controller.list_current_project(limit=50)
    session_ids = {item.session_id for item in page.items}
    assert {"a", "b"}.issubset(session_ids)
    assert "hidden" not in session_ids and "private" not in session_ids
    assert set(state_reads) == session_ids
    assert all(item.cwd == str(project.work_root) for item in page.items)


@pytest.mark.asyncio
async def test_project_session_summary_running_uses_original_session_state(populated):
    # user:“每一个地方 sunday 都有等价或者近似接口”+(running只从原会话控制器读取，不由持久摘要状态猜测)。
    ctx, _, _, _, _, _ = populated
    sessions = ctx.session_controller._sessions.get()
    host = sessions._context().host
    running = asyncio.create_task(asyncio.Event().wait())
    host.runtime_task_registry.register("a", running, run_id="turn-a", turn_id="turn-a")
    try:
        page = await ctx.session_controller.list_current_project(limit=50)
        summary = next(item for item in page.items if item.session_id == "a")
        assert summary.running is True
        other = next(item for item in page.items if item.session_id == "b")
        assert other.running is False
    finally:
        running.cancel()
        await asyncio.gather(running, return_exceptions=True)


@pytest.mark.asyncio
async def test_project_session_summary_cancellation_waits_for_original_state_cleanup(populated, monkeypatch):
    # user:“建立真实请求、错误、作用域、取消/流和清理验收”+(列表取消需等原会话状态读取结束后才释放作用域)。
    ctx, _, _, _, _, _ = populated
    sessions = ctx.session_controller._sessions.get()
    original = sessions.state
    entered, release = asyncio.Event(), asyncio.Event()

    async def blocked(session_id):
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            await release.wait()
            raise
        return await original(session_id)

    monkeypatch.setattr(sessions, "state", blocked)
    task = asyncio.create_task(ctx.session_controller.list_current_project(limit=50))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_project_session_summary_rechecks_project_after_state_read(populated, monkeypatch):
    # user:“复用原宿主权威”+(读取动态会话状态后重新检查项目归属，移动出去的会话不得出现在摘要)。
    ctx, _, _, project, other, store = populated
    original_get = store.get_readonly
    moved = False

    async def current_record(session_id):
        record = await original_get(session_id)
        if session_id == "a" and moved and record is not None:
            record.metadata["work_root"] = str(other.work_root)
        return record

    sessions = ctx.session_controller._sessions.get()
    original_state = sessions.state

    async def move_after_state(session_id):
        nonlocal moved
        result = await original_state(session_id)
        if session_id == "a":
            moved = True
        return result

    monkeypatch.setattr(store, "get_readonly", current_record)
    monkeypatch.setattr(sessions, "state", move_after_state)
    page = await ctx.session_controller.list_current_project(limit=50)
    ids = {item.session_id for item in page.items}
    assert "a" not in ids and "b" in ids
    assert all(item.cwd == str(project.work_root) for item in page.items)


def test_session_list_migration_names_core_timestamp_as_an_approximation(tmp_path):
    # user:“剩下问题交给 agent 来移植”+(自动迁移只建议已核实的时间近似，并明确上游时间语义差异)。
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port

    root = source(tmp_path, {"index.ts": "export function apply(ctx) { ctx.remote.session.list({}); }"})
    report = export_port(root, tmp_path / "ported-session-list-time")
    method = next(row for row in report["remotes"] if row["name"] == "session.list")
    assert method["suggestedContract"] == "context.session_controller.list_current_project"
    assert "updated_at_ms" in method["difference"]
    assert "last_prompt_received_at_ms" in method["difference"]
    assert "lastPromptAt" in method["difference"]
    assert "blank" in method["difference"]
    assert "cursor" in method["difference"]
    assert "limit" in method["difference"]
    assert "has_more" in method["difference"]
    assert "cwd" in method["difference"]
    assert "running" in method["difference"]
    assert "agentAvailable" in method["difference"]
