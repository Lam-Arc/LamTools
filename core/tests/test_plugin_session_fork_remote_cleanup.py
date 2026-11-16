"""user:“建立真实请求、错误、作用域、取消/流和清理验收”+(分叉沿原桌面提交，取消需等已派发提交结算)。"""
import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI

from .test_core_checkpoint_graph import _append_production_turn, _runtime
from .test_plugin_checkpoint_access import setup
from .test_plugin_http_routes import _host
from .test_plugin_remote_gateway import configure
from .test_plugin_working_directory import env
from lamtools_core.checkpoint import register_checkpoint_operations


@pytest.mark.asyncio
async def test_cancelled_fork_waits_for_original_commit_and_scope_cleanup(setup, monkeypatch):
    ctx, store, _, project, db = setup
    await _runtime(db, "s", history=[], status="completed")
    await _append_production_turn(db, "s", "fork-turn", "fork this production-shaped turn")
    catalog = ctx.operation_catalog
    original = catalog._handlers["session.fork"]
    entered, release = asyncio.Event(), asyncio.Event()

    async def gated(request):
        entered.set()
        await release.wait()
        return await original(request)

    monkeypatch.setitem(catalog._handlers, "session.fork", gated)
    scope = ctx._registration_scope
    task = asyncio.create_task(ctx.session_controller.fork(
        "s", turn_id="fork-turn", new_session_id="forked-session", title="Forked"
    ))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        assert await store.get_readonly("forked-session") is None
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        child = await store.get_readonly("forked-session")
        assert child is not None and child.metadata["work_root"] == str(project)
        assert scope._idle.is_set()
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_fork_uses_original_project_commit_through_authenticated_remote(env, tmp_path):
    ctx, store, sessions, project = env
    db = store._db_provider()
    catalog = sessions._context().operations
    ctx.operation_catalog = catalog
    register_checkpoint_operations(catalog, session_factory=db.session_factory, default_work_root=project,
        app_event_store=db.event_store, thread_snapshot_store=db.snapshot_store)
    await _runtime(db, "s", history=[], status="completed")
    await _append_production_turn(db, "s", "http-fork-turn", "fork over the real plugin route")

    host, _, original_ctx = _host(tmp_path)
    configure(host)
    manifest_path = host.get("hook-demo").root / "plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf8"))
    manifest["http"]["remote"][0]["argsSchema"] = {
        "type": "object",
        "properties": {"source": {"type": "string"}, "turn": {"type": "string"},
                       "target": {"type": "string"}},
        "required": ["source", "turn", "target"],
        "additionalProperties": False,
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf8")
    host._invalidate()
    ctx._secret_store = original_ctx._secret_store
    host.backend_manager.context = ctx
    (host.get("hook-demo").root / "ops.py").write_text(
        "from lamtools_core.app.operation_catalog import OperationResult\n"
        "async def echo(request, *, context):\n"
        "    body=request.payload['body']\n"
        "    result=await context.session_controller.fork(body['source'], turn_id=body['turn'], "
        "new_session_id=body['target'], title='HTTP fork')\n"
        "    return OperationResult(request.name, result)\n",
        encoding="utf8",
    )
    from lamtools_core.app.operation_catalog import OperationCatalog
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token

    plugin_catalog = OperationCatalog()
    register_plugin_operations(plugin_catalog, host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: plugin_catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/plugin-remote/hook-demo/demo/echo",
            json={"args": {"source": "s", "turn": "http-fork-turn", "target": "http-forked"}},
            headers={"x-plugin-token": plugin_http_token(host, "hook-demo")},
        )

    assert response.status_code == 200, response.text
    assert response.json()["payload"]["session_id"] == "http-forked"
    forked = await ctx.service("sessions")._context().host.session_store.get_readonly("http-forked")
    assert forked is not None and forked.metadata["work_root"] == str(project)
