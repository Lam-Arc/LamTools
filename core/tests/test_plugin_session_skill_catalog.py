"""user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(会话技能目录复用原注册表，保留用户调用策略和实际目录)。"""
import asyncio
from copy import copy
from pathlib import Path

import pytest
from lamtools_core.skills import Skill, SkillRegistry, SkillStateStore
from lamtools_core.app.operation_catalog import OperationCatalog
from .test_plugin_working_directory import env


@pytest.fixture
def provider(env, tmp_path):
    ctx, _, _, root = env
    skills = [Skill("allowed", "Can use", None, "SECRET BODY", user_invocable=True),
        Skill("model-only", "Not for user", None, "hidden", user_invocable=False),
        Skill("disabled", "Disabled", None, "hidden", user_invocable=True)]
    registry = SkillRegistry(runtime_skills=lambda: skills)
    state = SkillStateStore(tmp_path / "skill-state.json")
    state.set_enabled("disabled", False)
    catalog = ctx.operation_catalog = OperationCatalog()
    catalog.command_skill_registry_factory = lambda: registry
    catalog.command_skill_state_store_factory = lambda: state
    return ctx, registry, state, skills, root


@pytest.mark.asyncio
async def test_original_registry_user_policy_and_enabled_state_without_body(provider):
    ctx, _, _, _, _ = provider
    result = await ctx.session_skill_catalog.list("s")
    assert [row["name"] for row in result["skills"]] == ["allowed"]
    assert result["skills"][0]["model_invocable"] is True
    assert "SECRET BODY" not in repr(result)
    with pytest.raises((RuntimeError, ValueError)): await ctx.session_skill_catalog.list("hidden")


@pytest.mark.asyncio
async def test_session_execution_directory_selects_real_disk_skill(provider):
    ctx, _, _, _, root = provider
    skill = root / "one" / ".lam" / "skills" / "local" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("---\nname: local\ndescription: In session directory\n---\nprivate body", encoding="utf8")
    state = await ctx.working_directory.get("s")
    await ctx.working_directory.set("s", "one", expected_revision=state.revision)
    result = await ctx.session_skill_catalog.list("s")
    assert "local" in [row["name"] for row in result["skills"]]
    assert "private body" not in repr(result)


@pytest.mark.asyncio
async def test_missing_registry_is_explicit_error_not_empty_success(env):
    ctx, _, _, _ = env
    with pytest.raises(RuntimeError) as error: await ctx.session_skill_catalog.list("s")
    assert error.value.code == "session-skill/unavailable"


@pytest.mark.asyncio
async def test_visible_session_from_another_project_is_rejected(provider, env, tmp_path):
    from lamtools_core.session import SessionRecord
    ctx, _, _, _, _ = provider
    _, store, _, _ = env
    other = tmp_path / "foreign-root"
    other.mkdir()
    await store.create(SessionRecord("foreign", "core", "Foreign", "idle", metadata={"work_root": str(other)}))
    with pytest.raises(ValueError) as error: await ctx.session_skill_catalog.list("foreign")
    assert error.value.code == "workspace-file/outside-workspace"


@pytest.mark.asyncio
async def test_skill_catalog_bounds_and_provider_withdrawal(provider):
    ctx, _, _, skills, _ = provider
    skills.append(Skill("another", "Another", None, "body"))
    result = await ctx.session_skill_catalog.list("s", limit=1)
    assert len(result["skills"]) == 1 and result["truncated"]
    for invalid in [0, 501, True]:
        with pytest.raises(ValueError): await ctx.session_skill_catalog.list("s", limit=invalid)
    api = ctx.session_skill_catalog
    ctx.operation_catalog.command_skill_state_store_factory = None
    with pytest.raises(RuntimeError) as error: await api.list("s")
    assert error.value.code == "session-skill/host-changed"


@pytest.mark.asyncio
async def test_original_skill_catalog_through_real_http(provider, tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
    ctx, _, _, _, _ = provider
    host, catalog, original_context = _host(tmp_path)
    configure(host)
    ctx._secret_store = original_context._secret_store
    host.backend_manager.context = ctx
    (host.get("hook-demo").root / "ops.py").write_text(
        "async def echo(request, *, context):\n"
        "    return await context.session_skill_catalog.list(request.payload['body']['text'])\n", encoding="utf8")
    catalog.unregister_owner("plugin:hook-demo")
    register_plugin_operations(catalog, host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        headers = {"x-plugin-token": plugin_http_token(host, "hook-demo")}
        response = await client.post("/plugin-remote/hook-demo/demo/echo", json={"args": {"text": "s"}}, headers=headers)
        denied = await client.post("/plugin-remote/hook-demo/demo/echo", json={"args": {"text": "hidden"}}, headers=headers)
    assert response.status_code == 200 and response.json()["payload"]["skills"][0]["name"] == "allowed"
    assert "SECRET BODY" not in response.text and denied.status_code == 400


def test_skill_catalog_migration_identifies_actual_scope_and_gap(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root = source(tmp_path, {"index.ts": "export function apply(ctx) { ctx.remote.skills.list(); }"})
    report = export_port(root, tmp_path / "ported")
    item = next(row for row in report["remotes"] if row["name"] == "skills.list")
    assert item["suggestedContract"] == "context.session_skill_catalog.list"
    assert "预设" in item["difference"] and report["runtimeVerified"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["host", "catalog", "factory", "state", "scope", "cancel"])
async def test_session_admission_binding_and_cancellation(provider, monkeypatch, change):
    ctx, _, _, _, _ = provider
    host, catalog = ctx.require_service("working_directory"), ctx.operation_catalog
    original = host.call
    entered, release = asyncio.Event(), asyncio.Event()
    async def gated(*args, **kwargs):
        value = await original(*args, **kwargs)
        entered.set()
        await release.wait()
        return value
    monkeypatch.setattr(host, "call", gated)
    api = ctx.session_skill_catalog
    task = asyncio.create_task(api.list("s"))
    try:
        await entered.wait()
        if change == "host": ctx.set_service("working_directory", copy(host))
        elif change == "catalog": ctx.operation_catalog = type(catalog)()
        elif change == "factory": catalog.command_skill_registry_factory = lambda: None
        elif change == "state": catalog.command_skill_state_store_factory = lambda: None
        elif change == "scope": ctx._registration_scope.revoke()
        else: task.cancel()
        release.set()
        if change == "cancel":
            with pytest.raises(asyncio.CancelledError): await task
        else:
            with pytest.raises((RuntimeError, ValueError)): await task
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
