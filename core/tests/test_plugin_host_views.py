"""user:“审查当前代码，然后继续”+(类型注册、预设、只读检查与投影缓存复用现有权威，并验证撤回和新鲜度)。"""
from typing import Protocol, runtime_checkable

import pytest

from lamtools_core.plugin_system import PluginContext
from lamtools_core.plugin_system.services import ServiceKey
from .test_plugin_working_directory import env


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["list", "resolve", "compose"])
@pytest.mark.parametrize("change", ["requester", "provider"])
async def test_preset_read_rechecks_authority_after_provider_wait(tmp_path, method, change):
    # user:“完成真实接口、参数/错误、作用域、取消/清理”+(原预设查询等待期间失效后不能发布迟到只读结果，调用租约仍须释放)。
    import asyncio
    from lamtools_core.plugin_system.agent_presets import AgentPreset, AgentPresetRegistry
    from lamtools_core.plugin_system.services import ServiceError
    entered, release = asyncio.Event(), asyncio.Event()
    class WaitingRegistry(AgentPresetRegistry):
        async def list(self):
            entered.set()
            await release.wait()
            return super().list()
        async def resolve(self, preset_id=None):
            entered.set()
            await release.wait()
            return super().resolve(preset_id)
        async def compose(self, preset_id=None, **kwargs):
            entered.set()
            await release.wait()
            return AgentPresetRegistry([AgentPreset("research", mode="consider")]).compose(preset_id, **kwargs)
    registry = WaitingRegistry([AgentPreset("research", mode="consider")])
    ctx = PluginContext(tmp_path, services={"agent_presets": registry})
    ctx._begin_registration_scope("preset-wait", 1)
    scope = ctx._registration_scope
    api = ctx.agent_presets
    pending = asyncio.create_task(getattr(api, method)(*(() if method == "list" else ("research",))))
    await entered.wait()
    if change == "requester":
        scope.revoke()
    else:
        ctx.set_service("agent_presets", AgentPresetRegistry())
    release.set()
    try:
        with pytest.raises(ServiceError) as error:
            await pending
        assert error.value.code == ("service/scope-closed" if change == "requester" else "service/stale")
        assert not scope._calls
    finally:
        release.set()
        await asyncio.gather(pending, return_exceptions=True)
        await scope.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind",["services","operations"])
async def test_inspector_exact_query_is_not_limited_to_first_snapshot_page(tmp_path,kind):
    # user:“完成真实接口、参数/错误、作用域、取消/清理”+(精确名称查询不能因快照截断而把实际存在的服务或操作误报为不存在)。
    from lamtools_core.app.operation_catalog import OperationCatalog
    from lamtools_core.plugin_system.services import ServiceError
    catalog = OperationCatalog()
    def never_execute(request):
        pytest.fail("inspection must never execute an operation")
    for index in range(1101):
        catalog.register(f"entry{index:04}",never_execute)
    ctx = PluginContext(tmp_path,operation_catalog=catalog,
        services={f"entry{index:04}":"private-inspection-value" for index in range(1101)})
    ctx._begin_registration_scope("large-inspector",1)
    api = ctx.inspector
    try:
        snapshot = api.snapshot()
        assert snapshot["truncated"] and len(snapshot[kind]) == 1000
        result = api.query(kind,"entry1100")
        assert result is not None and result["name"] == "entry1100"
        assert "private-inspection-value" not in str(result)
        result["name"] = "caller mutation"
        assert api.query(kind,"entry1100")["name"] == "entry1100"
        assert api.query(kind,"absent") is None
        assert len(api.snapshot()[kind]) == 1000
    finally:
        await ctx._registration_scope.dispose()
    with pytest.raises(ServiceError):
        api.query(kind,"entry1100")


@runtime_checkable
class Calculation(Protocol):
    async def compute(self, value: int) -> int: ...


@pytest.mark.asyncio
async def test_typed_view_uses_native_validation_publication_and_stale_references(tmp_path):
    from lamtools_core.plugin_system.services import ServiceError
    ctx = PluginContext(tmp_path)
    ctx._begin_registration_scope("typed", 1)
    key = ServiceKey("calculation", protocol=Calculation)
    class Provider:
        async def compute(self, value):
            return value + 1
    with pytest.raises(TypeError):
        ctx.types.register(key, object())
    dispose = ctx.types.register(key, Provider())
    ref = ctx.types.require(key)
    assert await ref.call("compute", 4) == 5
    assert ctx.types.get("absent") is None
    dispose()
    with pytest.raises(ServiceError):
        await ref.call("compute", 4)
    await ctx._registration_scope.dispose()


@pytest.mark.asyncio
async def test_inspector_reads_descriptors_without_exporting_values(tmp_path):
    ctx = PluginContext(tmp_path, services={"secret": "private-secret-value"})
    ctx._begin_registration_scope("inspection", 1)
    result = ctx.inspector.snapshot()
    assert result["services"][0]["name"] == "secret"
    assert "private-secret-value" not in str(result)
    assert ctx.inspector.query("services", "secret")["available"]
    assert ctx.inspector.query("services", "absent") is None
    api = ctx.inspector
    await ctx._registration_scope.dispose()
    with pytest.raises(Exception):
        api.snapshot()


@pytest.mark.asyncio
async def test_preset_view_uses_native_composition_and_returns_copies(tmp_path):
    from lamtools_core.plugin_system.agent_presets import AgentPreset, AgentPresetRegistry
    registry = AgentPresetRegistry([AgentPreset("research", mode="consider", model="local", tools=("read_file",))])
    ctx = PluginContext(tmp_path, services={"agent_presets": registry})
    ctx._begin_registration_scope("preset", 1)
    result = await ctx.agent_presets.compose("research", model="explicit")
    assert result["mode"] == "consider" and result["model"] == "explicit"
    result["allowed_tools"].append("write_file")
    assert (await ctx.agent_presets.resolve("research"))["tools"] == ["read_file"]
    assert (await ctx.agent_presets.list())[0]["id"] == "research"
    await ctx._registration_scope.dispose()


@pytest.mark.asyncio
async def test_projection_cache_revalidates_native_state_and_invalidates_real_entries(env):
    ctx, _, _, _ = env
    cache = ctx.session_projection_cache
    first = await cache.get("s")
    first["title"] = "Caller mutation"
    assert (await cache.get("s"))["title"] == "Example"
    title = await ctx.session_title.get("s")
    await ctx.session_title.set("s", "Updated", expected_revision=title["revision"])
    assert (await cache.get("s"))["title"] == "Updated"
    assert cache.invalidate("s") == 1
    assert cache.invalidate("s") == 0
    await ctx._registration_scope.dispose()
    with pytest.raises(Exception):
        await cache.get("s")
