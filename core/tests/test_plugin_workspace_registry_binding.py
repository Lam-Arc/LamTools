"""user:“复用原宿主权威”+(项目读取不得发布被替换原操作的旧结果)。"""
import asyncio
import pytest
from .test_plugin_workspace_registry_current import workspace_env


@pytest.mark.asyncio
@pytest.mark.parametrize('method,name', [('get', 'project.get'), ('resolve_by_path', 'project.resolve')])
async def test_project_read_rejects_same_name_replacement(workspace_env, monkeypatch, method, name):
    ctx, _, catalog, project, _ = workspace_env
    entered, release = asyncio.Event(), asyncio.Event()
    original_execute = catalog.execute
    async def gated(*args, **kwargs):
        result = await original_execute(*args, **kwargs)
        entered.set()
        await release.wait()
        return result
    monkeypatch.setattr(catalog, 'execute', gated)
    api = ctx.workspace_registry
    value = project.id if method == 'get' else str(ctx.work_root)
    task = asyncio.create_task(getattr(api, method)(value))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        handler = catalog._handlers.pop(name)
        catalog.register(name, handler)
        release.set()
        with pytest.raises(RuntimeError) as error:
            await task
        assert error.value.code == 'workspace-registry/host-changed'
        assert ctx._registration_scope._idle.is_set()
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
