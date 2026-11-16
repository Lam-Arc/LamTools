"""user:“逐项对照固定上游完成可安全落地的非前端后端契约”+(支持固定Remote schema中的可选原始类型参数，并保持实际校验)。"""
import json

import httpx
import pytest
from fastapi import FastAPI

from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
from .test_plugin_http_routes import _host
from .test_plugin_remote_gateway import configure


def _set_schema(host, schema, *, resource=None):
    manifest_path = host.get("hook-demo").root / "plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf8"))
    declaration = manifest["http"]["remote"][0]
    declaration["argsSchema"] = schema
    if resource is not None:
        declaration["resource"] = resource
    manifest_path.write_text(json.dumps(manifest), encoding="utf8")
    host._invalidate()


@pytest.mark.asyncio
async def test_remote_accepts_omitted_optional_primitive_and_checks_it_when_present(tmp_path):
    host, catalog, _ = _host(tmp_path)
    configure(host)
    _set_schema(host, {"type": "object", "properties": {
        "text": {"type": "string"}, "suffix": {"type": "string", "enum": ["!", "?"]}},
        "required": ["text"], "additionalProperties": False})
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    headers = {"x-plugin-token": plugin_http_token(host, "hook-demo")}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        omitted = await client.post("/plugin-remote/hook-demo/demo/echo", json={"args": {"text": "hi"}}, headers=headers)
        included = await client.post("/plugin-remote/hook-demo/demo/echo", json={"args": {"text": "hi", "suffix": "!"}}, headers=headers)
        invalid = await client.post("/plugin-remote/hook-demo/demo/echo", json={"args": {"text": "hi", "suffix": "x"}}, headers=headers)
    assert omitted.status_code == included.status_code == 200
    assert omitted.json()["payload"]["echo"] == {"text": "hi"}
    assert included.json()["payload"]["echo"] == {"text": "hi", "suffix": "!"}
    assert invalid.status_code == 400


@pytest.mark.asyncio
async def test_remote_resource_argument_must_be_required(tmp_path):
    host, catalog, _ = _host(tmp_path)
    configure(host)
    _set_schema(host, {"type": "object", "properties": {
        "text": {"type": "string"}, "session_id": {"type": "string"}},
        "required": ["text"], "additionalProperties": False},
        resource={"kind": "session", "argument": "session_id"})
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/plugin-remote/hook-demo/demo/echo", json={"args": {"text": "hi"}},
            headers={"x-plugin-token": plugin_http_token(host, "hook-demo")})
    assert response.status_code == 400
    assert response.json() == {"error": "invalid plugin Remote declaration"}


def test_remote_migration_handoff_documents_optional_fields_and_required_resource_keys(tmp_path):
    # user:“迁移脚本、机器清单与文档同步”+(自动交接说明有限可选字段支持及资源标识仍须必填)。
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port

    root = source(tmp_path, {"index.ts": "export function apply(ctx) { ctx.remote.session.prompt({}); }"})
    export_port(root, tmp_path / "ported-optional-remote")
    handoff = (tmp_path / "ported-optional-remote" / "PORTING.md").read_text(encoding="utf8")
    assert "可选原始类型字段" in handoff
    assert "资源标识仍须必填" in handoff
