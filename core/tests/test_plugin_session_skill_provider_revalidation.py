"""user:“复用原宿主权威”+(目录发现完成后拒绝已撤换的原技能提供方结果)。"""
import pytest

from lamtools_core.skills import SkillRegistry, SkillStateStore
from .test_plugin_session_skill_catalog import provider
from .test_plugin_working_directory import env


@pytest.mark.asyncio
async def test_registry_replacement_during_discovery_rejects_old_metadata(provider, monkeypatch):
    ctx, registry, _, _, _ = provider
    selected = {"registry": registry}
    ctx.operation_catalog.command_skill_registry_factory = lambda: selected["registry"]
    original = registry.available
    replacement = SkillRegistry(runtime_skills=lambda: [])

    def replace_after_scan(path):
        result = original(path)
        selected["registry"] = replacement
        return result

    monkeypatch.setattr(registry, "available", replace_after_scan)
    with pytest.raises(RuntimeError) as error:
        await ctx.session_skill_catalog.list("s")
    assert error.value.code == "session-skill/provider-changed"


@pytest.mark.asyncio
async def test_state_provider_replacement_during_discovery_rejects_old_metadata(provider, monkeypatch, tmp_path):
    ctx, registry, state, _, _ = provider
    selected = {"state": state}
    ctx.operation_catalog.command_skill_state_store_factory = lambda: selected["state"]
    original = registry.available
    replacement = SkillStateStore(tmp_path / "replacement-state.json")
    replacement.set_enabled("allowed", False)

    def replace_after_scan(path):
        result = original(path)
        selected["state"] = replacement
        return result

    monkeypatch.setattr(registry, "available", replace_after_scan)
    with pytest.raises(RuntimeError) as error:
        await ctx.session_skill_catalog.list("s")
    assert error.value.code == "session-skill/provider-changed"


@pytest.mark.asyncio
async def test_remote_does_not_publish_metadata_after_registry_replacement(provider, monkeypatch, tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token

    ctx, registry, _, _, _ = provider
    selected = {"registry": registry}
    ctx.operation_catalog.command_skill_registry_factory = lambda: selected["registry"]
    original = registry.available
    replacement = SkillRegistry(runtime_skills=lambda: [])

    def replace_after_scan(path):
        result = original(path)
        selected["registry"] = replacement
        return result

    monkeypatch.setattr(registry, "available", replace_after_scan)
    host, catalog, previous = _host(tmp_path)
    configure(host)
    ctx._secret_store = previous._secret_store
    host.backend_manager.context = ctx
    (host.get("hook-demo").root / "ops.py").write_text(
        "async def echo(request, *, context):\n"
        "    return await context.session_skill_catalog.list('s')\n", encoding="utf8")
    catalog.unregister_owner("plugin:hook-demo")
    register_plugin_operations(catalog, host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/plugin-remote/hook-demo/demo/echo", json={"args": {"text": "find"}},
            headers={"x-plugin-token": plugin_http_token(host, "hook-demo")})
    assert response.status_code == 400
    assert "allowed" not in response.text and "SECRET BODY" not in response.text
