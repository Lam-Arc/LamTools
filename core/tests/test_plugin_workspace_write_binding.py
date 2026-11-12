"""user:“复用原宿主权威”+(写入完成后拒绝原操作已替换的结果)。"""
import asyncio
import pytest
from .test_plugin_workspace_registry_current import workspace_env


@pytest.mark.asyncio
@pytest.mark.parametrize('method,operation', [('rename', 'project.update'), ('create_session', 'project.sessions.create')])
async def test_write_replacement_after_commit_reports_uncertain(workspace_env, monkeypatch, method, operation):
    ctx, db, catalog, project, _ = workspace_env
    original = catalog.execute
    entered, release = asyncio.Event(), asyncio.Event()
    async def gated(name, *args, **kwargs):
        result = await original(name, *args, **kwargs)
        if name == operation:
            entered.set()
            await release.wait()
        return result
    monkeypatch.setattr(catalog, 'execute', gated)
    api = ctx.workspace_controller
    work = api.rename(project.id, 'Updated', expected_revision=project.revision) if method == 'rename' else api.create_session(project.id, title='Created')
    task = asyncio.create_task(work)
    try:
        await asyncio.wait_for(entered.wait(), 3)
        handler = catalog._handlers.pop(operation)
        catalog.register(operation, handler)
        release.set()
        with pytest.raises(RuntimeError) as error: await task
        assert error.value.may_have_changed
        if method == 'rename': assert (await db.project_store.get(project.id)).name == 'Updated'
        else: assert any(s.title == 'Created' for s in await db.project_store.list_sessions(project.id))
        assert ctx._registration_scope._idle.is_set()
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
