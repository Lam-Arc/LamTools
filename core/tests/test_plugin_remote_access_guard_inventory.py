"""user:“第三阶段先做Remote/网关的后端访问控制与明确方法名单”+(名单反映同操作资源声明限制)。"""
import json

import pytest

from .test_plugin_remote_access_inventory import remote_env


@pytest.mark.parametrize("alias_resource,expected", [
    (None, ["echo"]),
    ({"kind": "session", "argument": "text"}, ["alias", "echo"]),
    ({"kind": "workspace", "argument": "text"}, []),
])
def test_inventory_only_lists_methods_that_pass_operation_guard(remote_env, alias_resource, expected):
    ctx, host, _ = remote_env
    path = host.get("hook-demo").root / "plugin.json"
    manifest = json.loads(path.read_text(encoding="utf8"))
    original = manifest["http"]["remote"][0]
    original["resource"] = {"kind": "session", "argument": "text"}
    alias = dict(original, method="alias")
    if alias_resource is None:
        alias.pop("resource")
    else:
        alias["resource"] = alias_resource
    manifest["http"]["remote"].append(alias)
    path.write_text(json.dumps(manifest), encoding="utf8")
    host._invalidate()
    assert [item["method"] for item in ctx.remote_access.declared_methods()["methods"]] == expected


def test_inventory_drops_method_when_upload_guard_conflicts(remote_env):
    ctx, host, _ = remote_env
    path = host.get("hook-demo").root / "plugin.json"
    manifest = json.loads(path.read_text(encoding="utf8"))
    manifest["http"]["remote"][0]["resource"] = {"kind": "session", "argument": "text"}
    manifest["http"]["uploads"] = [{"name": "files", "route": "/hook", "resource": "session"}]
    path.write_text(json.dumps(manifest), encoding="utf8")
    host._invalidate()
    assert ctx.remote_access.declared_methods() == {"methods": []}


def test_inventory_preserves_unprotected_methods(remote_env):
    ctx, _, _ = remote_env
    assert [item["method"] for item in ctx.remote_access.declared_methods()["methods"]] == ["echo"]


def test_migration_explains_guarded_inventory(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root = source(tmp_path, {"index.ts": "export function apply(ctx) { ctx.remoteAccess.follow(); }"})
    export_port(root, tmp_path / "ported")
    assert "同操作资源声明门禁" in (tmp_path / "ported" / "PORTING.md").read_text(encoding="utf8")


@pytest.mark.asyncio
async def test_guard_filtered_inventory_through_authenticated_http(remote_env):
    import httpx
    from fastapi import FastAPI
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
    ctx, host, catalog = remote_env
    host.backend_manager.context = ctx
    path = host.get("hook-demo").root / "plugin.json"
    manifest = json.loads(path.read_text(encoding="utf8"))
    manifest["http"]["remote"][0]["resource"] = {"kind": "session", "argument": "text"}
    alias = dict(manifest["http"]["remote"][0], method="unsafe")
    alias.pop("resource")
    manifest["http"]["remote"].append(alias)
    manifest["operations"].append({"name": "hook-demo.inventory", "handler": "ops:inventory", "permission": "auto_allow"})
    manifest["http"]["routes"].append({"method": "POST", "path": "/inventory", "operation": "hook-demo.inventory"})
    path.write_text(json.dumps(manifest), encoding="utf8")
    (path.parent / "ops.py").write_text("def inventory(request, *, context):\n    return context.remote_access.declared_methods()\n", encoding="utf8")
    host._invalidate()
    catalog.unregister_owner("plugin:hook-demo")
    register_plugin_operations(catalog, host)
    app = FastAPI(); app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    token = plugin_http_token(host, "hook-demo")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        denied = await client.post("/plugin-http/hook-demo/inventory", headers={"x-plugin-token": "wrong"})
        response = await client.post("/plugin-http/hook-demo/inventory", headers={"x-plugin-token": token})
    assert denied.status_code == 401 and response.status_code == 200
    assert [item["method"] for item in response.json()["payload"]["methods"]] == ["echo"]
    assert token not in response.text
