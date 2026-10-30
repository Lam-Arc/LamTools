"""user:“继续，把 2 阶段都做完”+(插件管理与运行档公开原业务操作，不重建管理器、不吞掉未授权或失败状态)。"""
import pytest

from lamtools_core.plugin_system import PluginContext
from .test_plugin_system_operations import make_catalog


@pytest.mark.asyncio
async def test_management_calls_real_catalog_and_updates_existing_ledger(tmp_path):
    catalog = make_catalog(tmp_path)
    ctx = PluginContext(tmp_path, operation_catalog=catalog)
    ctx._begin_registration_scope("caller", 1)
    try:
        rows = await ctx.plugins.list()
        assert rows["plugins"][0]["name"] == "hello"
        assert (await ctx.plugins.disable("hello"))["enabled"] is False
        assert (await ctx.plugins.enable("hello"))["enabled"] is True
    finally:
        await ctx._registration_scope.dispose()


@pytest.mark.asyncio
async def test_self_reload_is_rejected_and_old_facade_is_revoked(tmp_path):
    from lamtools_core.plugin_system import HostOperationError
    from lamtools_core.plugin_system.services import ServiceError
    ctx = PluginContext(tmp_path, operation_catalog=make_catalog(tmp_path))
    ctx._begin_registration_scope("hello", 1)
    api = ctx.plugins
    with pytest.raises(HostOperationError) as error:
        await api.reload("hello")
    assert error.value.code == "host/self-management"
    await ctx._registration_scope.dispose()
    with pytest.raises(ServiceError):
        await api.list()


@pytest.mark.asyncio
async def test_missing_profile_host_is_an_error_not_empty_catalog(tmp_path):
    from lamtools_core.plugin_system import HostOperationError
    ctx = PluginContext(tmp_path, operation_catalog=make_catalog(tmp_path))
    ctx._begin_registration_scope("caller", 1)
    try:
        with pytest.raises(HostOperationError) as error:
            await ctx.profiles.list()
        assert error.value.code == "host/unavailable"
    finally:
        await ctx._registration_scope.dispose()


@pytest.mark.asyncio
async def test_profile_read_uses_real_manifest_resolver(tmp_path):
    import json
    from lamtools_core.app import CoreAgentPaths, CoreAgentSpec, create_core_agent_operations
    root = tmp_path / "plugins"
    plugin = root / "demo"
    plugin.mkdir(parents=True)
    (plugin / "plugin.json").write_text(json.dumps({"name": "demo", "version": "1", "profiles": {"duty": {"tools": ["read_file"], "approval": "ask"}}}), encoding="utf-8")
    class Model:
        async def complete(self, request):
            pytest.fail("Profile query must not invoke a model")
    catalog = create_core_agent_operations(spec=CoreAgentSpec(), paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=tmp_path), model_provider=Model(), plugin_roots=[root])
    context = PluginContext(tmp_path, operation_catalog=catalog)
    context._begin_registration_scope("caller", 1)
    try:
        assert "demo:duty" in [row["full_name"] for row in (await context.profiles.list())["profiles"]]
        assert (await context.profiles.resolve("demo:duty"))["profile"]["approval"] == "ask"
    finally:
        await context._registration_scope.dispose()
