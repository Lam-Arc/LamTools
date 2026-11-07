"""user:“给我把 2 阶段做完，前端除外”+(验证持久模型政策和真实子代理创建门禁)。"""
import asyncio
from dataclasses import replace

import pytest
from lamtools_core.plugin_system.session_data import SessionDataError
from lamtools_core.plugin_system.model_access import ModelAccessError
from lamtools_core.plugin_system.subagent_models import SubagentModelError

from .test_plugin_working_directory import env
from .test_plugin_subagent_access import setup
from .test_plugin_model_access import store as model_config


@pytest.fixture
def routes(model_config, monkeypatch, setup):
    from lamtools_core.config.model_store import ModelStore
    from lamtools_core.plugin_system.model_catalog import ModelCatalogService
    import lamtools_core.sub_agent_supervisor as native
    ctx, _, _, _, root = setup
    ctx.set_service("model_catalog", ModelCatalogService(work_root=root))
    monkeypatch.setattr(native, "ModelStore", ModelStore)
    model_config["records"] = [replace(m, model_id=m.id) for m in model_config["records"]]
    return model_config


async def configure(ctx, allowed=None, default="route-one"):
    api = ctx.subagent_models
    current = await api.read("s")
    return await api.set("s", allowed=allowed if allowed is not None else ["route-one"],
                         default=default, expected_revision=current["revision"])


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["read", "set", "select"])
@pytest.mark.parametrize("change", ["host", "scope"])
async def test_model_policy_wait_rechecks_host_before_read_save_or_selection(setup, routes, monkeypatch, operation, change):
    # user:“复用原宿主权威”+(父模型策略读取后复核同一会话宿主，失效不能发布旧策略、选模或向旧存储写入)。
    from copy import copy
    from lamtools_core.plugin_system.services import ServiceError
    ctx, store, _, _, _ = setup
    await configure(ctx)
    api = ctx.subagent_models
    before = await store.get_readonly_revision("s")
    original = api._host._read
    entered, release = asyncio.Event(), asyncio.Event()
    async def gated(*args, **kwargs):
        result = await original(*args, **kwargs)
        entered.set()
        await release.wait()
        return result
    monkeypatch.setattr(api._host, "_read", gated)
    work = (api.read("s") if operation == "read" else api.select("s") if operation == "select" else
        api.set("s", allowed=[], default=None, expected_revision=before[1]))
    pending = asyncio.create_task(work)
    old = ctx.service("session_data")
    try:
        await asyncio.wait_for(entered.wait(), 3)
        if change == "host":
            ctx.set_service("session_data", copy(old))
        else:
            ctx._registration_scope.revoke()
        release.set()
        with pytest.raises((SubagentModelError, ServiceError)) as error:
            await pending
        assert error.value.code == ("subagent-model/host-changed" if change == "host" else "service/scope-closed")
        assert await store.get_readonly_revision("s") == before
        assert not ctx._registration_scope._calls
    finally:
        ctx.set_service("session_data", old)
        release.set()
        await asyncio.gather(pending, return_exceptions=True)


@pytest.mark.asyncio
async def test_policy_persists_cas_preserves_metadata_and_revokes_old_facade(setup, routes):
    from lamtools_core.plugin_system.services import ServiceError
    ctx, db, _, _, _ = setup
    api = ctx.subagent_models
    initial = await api.read("s")
    assert initial["configured"] is False
    saved = await configure(ctx)
    with pytest.raises(SubagentModelError) as error:
        await api.set("s", allowed=[], default=None, expected_revision=initial["revision"])
    assert error.value.code == "subagent-model/conflict"
    assert (await db.get_readonly("s")).metadata["project_id"] == "original"
    await ctx._registration_scope.dispose()
    ctx._begin_registration_scope("example", 2)
    assert await ctx.subagent_models.read("s") == saved
    with pytest.raises(ServiceError):
        await api.read("s")


@pytest.mark.asyncio
async def test_default_reaches_native_member_and_tightening_keeps_cleanup(setup, routes):
    ctx, _, runner, _, _ = setup
    await configure(ctx)
    row = await ctx.subagents.create("s", "worker", kind="consider", reasoning_level="high")
    assert row["model_id"] == "route-one"
    await ctx.subagents.message("s", "worker", request_id="one", text="Work")
    await asyncio.wait_for(runner.started.wait(), 3)
    await configure(ctx, [], None)
    for call in (ctx.subagents.create("s", "denied", kind="consider", model="route-one", reasoning_level="high"),
                 ctx.subagents.message("s", "worker", request_id="two", text="More")):
        with pytest.raises(SubagentModelError) as error:
            await call
        assert error.value.code == "subagent-model/denied"
    await ctx.subagents.interrupt("s", "worker")
    assert runner.finished.is_set()
    with pytest.raises(SubagentModelError) as error:
        await ctx.subagents.resume("s", "worker")
    assert error.value.code == "subagent-model/denied"
    assert (await ctx.subagents.close("s", "worker"))["status"] == "closed"


@pytest.mark.asyncio
async def test_selection_rejects_disallowed_retargeted_unavailable_and_ambiguous_routes(setup, routes):
    ctx, _, _, _, _ = setup
    await configure(ctx)
    assert (await ctx.subagent_models.select("s"))["id"] == "route-one"
    with pytest.raises(SubagentModelError) as error:
        await ctx.subagent_models.select("s", "route-two")
    assert error.value.code == "subagent-model/denied"
    routes["unavailable"].update({"one", "One"})
    with pytest.raises(ModelAccessError):
        await ctx.subagent_models.select("s")
    routes["unavailable"].clear()
    routes["records"][0] = replace(routes["records"][0], provider_id="two")
    with pytest.raises(SubagentModelError) as error:
        await ctx.subagent_models.select("s")
    assert error.value.code == "subagent-model/retargeted"
    with pytest.raises(ModelAccessError):
        await configure(ctx, ["Shared"], "Shared")


@pytest.mark.asyncio
async def test_policy_owner_parent_isolation_and_explicit_empty_denial(setup, routes):
    ctx, _, _, _, root = setup
    await configure(ctx)
    other = ctx.for_work_root(root)
    other._registration_scope = None
    other._begin_registration_scope("other", 1)
    try:
        assert not (await other.subagent_models.read("s"))["configured"]
        with pytest.raises(SubagentModelError):
            await other.subagent_models.select("s")
        with pytest.raises(SessionDataError):
            await ctx.subagent_models.read("hidden")
        with pytest.raises(SubagentModelError):
            await ctx.subagent_models.read("s:sub:any")
        await configure(ctx, [], None)
        assert (await ctx.subagent_models.read("s"))["allowed"] == []
    finally:
        await other._registration_scope.dispose()


@pytest.mark.asyncio
async def test_duplicate_wire_routes_cannot_lose_provider_identity(setup, routes):
    ctx, _, _, _, _ = setup
    routes["records"][1] = replace(routes["records"][1], model_id="route-one")
    with pytest.raises(SubagentModelError) as error:
        await configure(ctx)
    assert error.value.code == "subagent-model/ambiguous-route"


@pytest.mark.asyncio
async def test_disabled_allowed_default_cannot_create_native_child(setup, routes):
    from lamtools_core.plugin_system.model_access import ModelAccessError
    ctx, _, _, _, _ = setup
    await configure(ctx)
    routes["records"][0] = replace(routes["records"][0], enabled=False)
    with pytest.raises(ModelAccessError) as error:
        await ctx.subagents.create("s", "disabled", kind="consider", reasoning_level="high")
    assert error.value.code == "model/unavailable"
    assert (await ctx.subagents.list("s"))["items"] == []


@pytest.mark.asyncio
async def test_concurrent_policy_saves_have_one_winner(setup, routes):
    ctx, _, _, _, _ = setup
    revision = (await ctx.subagent_models.read("s"))["revision"]
    results = await asyncio.gather(*[ctx.subagent_models.set("s", allowed=[route], default=route,
                  expected_revision=revision) for route in ("route-one", "route-two")], return_exceptions=True)
    assert sum(isinstance(row, dict) for row in results) == 1
    errors = [row for row in results if isinstance(row, SubagentModelError)]
    assert len(errors) == 1 and errors[0].code == "subagent-model/conflict"


@pytest.mark.asyncio
async def test_policy_write_cancellation_drains_original_commit(setup, routes, monkeypatch):
    ctx, db, _, _, _ = setup
    revision = (await ctx.subagent_models.read("s"))["revision"]
    entered, release = asyncio.Event(), asyncio.Event()
    original = db.patch
    async def delayed(*args, **kwargs):
        entered.set()
        await release.wait()
        return await original(*args, **kwargs)
    monkeypatch.setattr(db, "patch", delayed)
    task = asyncio.create_task(ctx.subagent_models.set("s", allowed=["route-one"],
                               default="route-one", expected_revision=revision))
    await asyncio.wait_for(entered.wait(), 3)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (await ctx.subagent_models.read("s"))["default"] == "route-one"


@pytest.mark.asyncio
async def test_invalid_policy_never_writes_and_project_isolation(setup, routes, tmp_path):
    ctx, _, _, _, _ = setup
    initial = await ctx.subagent_models.read("s")
    for allowed, default, revision in [(["route-one"] * 33, None, initial["revision"]),
                                     (["route-one"] * 2, None, initial["revision"]),
                                     ([], "route-one", initial["revision"]), ([], None, True)]:
        with pytest.raises(SubagentModelError):
            await ctx.subagent_models.set("s", allowed=allowed, default=default, expected_revision=revision)
    assert await ctx.subagent_models.read("s") == initial
    with pytest.raises(SessionDataError):
        await ctx.for_work_root(tmp_path / "foreign").subagent_models.read("s")
