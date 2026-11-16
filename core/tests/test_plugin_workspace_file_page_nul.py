"""user:“逐项核对固定上游源码及手册”+(文件文本页只将所返回内容中的NUL视为二进制)。"""
import pytest

from .test_plugin_working_directory import env


@pytest.mark.asyncio
@pytest.mark.parametrize("data,offset,eof", [
    (b"prefix\x00\nsafe\nafter", 2, False),
    (b"safe\nafter\x00", 1, False),
    (b"x" * 8190 + b"\x00x\nsafe\n", 2, True),
])
async def test_nul_outside_selected_page_does_not_reject_read(env, data, offset, eof):
    ctx, _, _, root = env
    (root / "page.txt").write_bytes(data)
    result = await ctx.workspace_files.read("s", "page.txt", offset=offset, limit=1)
    assert result["text"] == "safe" and result["lines"] == 1 and result["eof"] is eof


@pytest.mark.asyncio
async def test_nul_inside_selected_page_and_original_stream_are_rejected(env):
    ctx, _, _, root = env
    (root / "page.txt").write_bytes(b"prefix\x00\nselected\x00data\nsafe")
    with pytest.raises(ValueError) as error:
        await ctx.workspace_files.read("s", "page.txt", offset=2, limit=1)
    assert error.value.code == "workspace-file/not-text"
    with pytest.raises(ValueError) as error:
        list(ctx.filesystem.stream_text("page.txt", max_bytes=100))
    assert error.value.code == "fs/not-text"


@pytest.mark.asyncio
async def test_selected_page_still_requires_valid_utf8_in_original_read_chunk(env):
    ctx, _, _, root = env
    (root / "page.txt").write_bytes(b"safe\n\xff")
    with pytest.raises(ValueError) as error:
        await ctx.workspace_files.read("s", "page.txt", offset=1, limit=1)
    assert error.value.code == "workspace-file/not-text"


@pytest.mark.asyncio
async def test_scoped_page_read_over_authenticated_remote(env, tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token

    ctx, _, _, root = env
    (root / "page.txt").write_bytes(b"prefix\x00\nsafe\nafter\x00")
    host, catalog, previous = _host(tmp_path)
    configure(host)
    ctx._secret_store = previous._secret_store
    host.backend_manager.context = ctx
    (host.get("hook-demo").root / "ops.py").write_text(
        "async def echo(request, *, context):\n"
        "    return await context.workspace_files.read(request.payload['body']['text'], 'page.txt', offset=2, limit=1)\n",
        encoding="utf8")
    catalog.unregister_owner("plugin:hook-demo")
    register_plugin_operations(catalog, host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        url = "/plugin-remote/hook-demo/demo/echo"
        headers = {"x-plugin-token": plugin_http_token(host, "hook-demo")}
        valid = await client.post(url, json={"args": {"text": "s"}}, headers=headers)
        hidden = await client.post(url, json={"args": {"text": "hidden"}}, headers=headers)
        denied = await client.post(url, json={"args": {"text": "s"}}, headers={"x-plugin-token": "wrong"})
    assert valid.status_code == 200 and valid.json()["payload"]["text"] == "safe"
    assert hidden.status_code == 400 and "safe" not in hidden.text
    assert denied.status_code == 401


def test_migration_describes_page_scoped_nul_check(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port

    root = source(tmp_path, {"index.ts": "export function apply(ctx) { ctx.remote.workspaceFiles.read(); }"})
    export_port(root, tmp_path / "ported")
    assert "NUL仅检查所选页" in (tmp_path / "ported" / "PORTING.md").read_text(encoding="utf8")
