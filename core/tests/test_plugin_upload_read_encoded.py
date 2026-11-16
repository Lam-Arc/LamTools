"""user:“复用原宿主权威”+(只读当前会话原托管附件并验证实际字节)。"""
import asyncio
import base64
from pathlib import Path

import pytest

from .test_plugin_session_data import env


@pytest.mark.asyncio
async def test_roundtrip_actual_managed_file_without_exposing_path(env):
    ctx, _, _, _ = env
    data = b"\x00\xffreal\n"
    saved = await ctx.file_uploads.save_encoded("s", filename="payload.bin", content_base64=base64.b64encode(data).decode())
    result = await ctx.file_uploads.read_encoded("s", saved["id"])
    assert base64.b64decode(result["content_base64"]) == data and result["id"] == saved["id"]
    assert str(Path(saved["path"])) not in repr(result)
    with pytest.raises(RuntimeError): await ctx.file_uploads.read_encoded("hidden", saved["id"])


@pytest.mark.asyncio
async def test_corrupted_or_external_file_is_not_returned(env, tmp_path):
    ctx, _, _, _ = env
    saved = await ctx.file_uploads.save_encoded("s", filename="payload.bin", content_base64="YWJj")
    Path(saved["path"]).write_bytes(b"xyz")
    with pytest.raises(RuntimeError): await ctx.file_uploads.read_encoded("s", saved["id"])
    local = ctx.work_root / "external.txt"; local.write_text("outside", encoding="utf8")
    reference = await ctx.attachments.reference("s", str(local))
    with pytest.raises(RuntimeError): await ctx.file_uploads.read_encoded("s", reference["id"])


@pytest.mark.asyncio
async def test_read_limit_and_post_read_visibility(env, monkeypatch):
    from lamtools_core.plugin_system import file_uploads
    ctx, store, _, _ = env
    saved = await ctx.file_uploads.save_encoded("s", filename="payload.bin", content_base64="YWJj")
    monkeypatch.setattr(file_uploads, "MAX_ENCODED_UPLOAD_BYTES", 2)
    with pytest.raises(RuntimeError): await ctx.file_uploads.read_encoded("s", saved["id"])
    monkeypatch.setattr(file_uploads, "MAX_ENCODED_UPLOAD_BYTES", 512 * 1024)
    host = ctx.require_service("session_data"); original = host.call; calls = 0
    async def changed(*args, **kwargs):
        nonlocal calls
        result = await original(*args, **kwargs); calls += 1
        if calls == 1: store._session_visible = lambda sid, _: sid != "s"
        return result
    monkeypatch.setattr(host, "call", changed)
    with pytest.raises(RuntimeError): await ctx.file_uploads.read_encoded("s", saved["id"])


@pytest.mark.asyncio
async def test_repeated_cancel_waits_for_original_read_cleanup(env, monkeypatch):
    ctx, _, _, _ = env
    saved = await ctx.file_uploads.save_encoded("s", filename="payload.bin", content_base64="YWJj")
    host = ctx.require_service("session_data"); entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    async def blocked(*args, **kwargs):
        entered.set()
        try: await asyncio.Event().wait()
        finally: cleaning.set(); await release.wait()
    monkeypatch.setattr(host, "call", blocked)
    task = asyncio.create_task(ctx.file_uploads.read_encoded("s", saved["id"]))
    try:
        await entered.wait(); task.cancel(); await cleaning.wait(); task.cancel(); await asyncio.sleep(0)
        assert not task.done() and not ctx._registration_scope._idle.is_set()
        release.set()
        with pytest.raises(asyncio.CancelledError): await task
        assert ctx._registration_scope._idle.is_set()
    finally:
        release.set(); await asyncio.gather(task, return_exceptions=True)


def test_migration_identifies_managed_file_read_limit(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root = source(tmp_path, {"index.ts": "export function apply(ctx) { ctx.fileUploads.upload(); }"})
    export_port(root, tmp_path / "ported")
    assert "file_uploads.read_encoded" in (tmp_path / "ported" / "PORTING.md").read_text(encoding="utf8")


@pytest.mark.asyncio
async def test_managed_file_read_through_authenticated_http(env, tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
    ctx, _, _, _ = env
    saved = await ctx.file_uploads.save_encoded("s", filename="payload.bin", content_base64="AP9h")
    host, catalog, old = _host(tmp_path); configure(host)
    ctx._secret_store = old._secret_store; host.backend_manager.context = ctx
    (host.get("hook-demo").root / "ops.py").write_text(
        "async def echo(request, *, context):\n"
        "    return await context.file_uploads.read_encoded('s', request.payload['body']['text'])\n", encoding="utf8")
    catalog.unregister_owner("plugin:hook-demo"); register_plugin_operations(catalog, host)
    app = FastAPI(); app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        url = "/plugin-remote/hook-demo/demo/echo"; body = {"args": {"text": saved["id"]}}
        denied = await client.post(url, json=body, headers={"x-plugin-token": "wrong"})
        response = await client.post(url, json=body, headers={"x-plugin-token": plugin_http_token(host, "hook-demo")})
    assert denied.status_code == 401 and response.status_code == 200
    assert response.json()["payload"]["content_base64"] == "AP9h" and saved["path"] not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("session_id,attachment_id", [("\ud800", "id"), ("s", "\ud800")])
async def test_invalid_unicode_identifier_fails_before_original_host(env, monkeypatch, session_id, attachment_id):
    ctx, _, _, _ = env
    async def forbidden(*args, **kwargs): pytest.fail("invalid identifier reached host")
    monkeypatch.setattr(ctx.require_service("session_data"), "call", forbidden)
    with pytest.raises(RuntimeError): await ctx.file_uploads.read_encoded(session_id, attachment_id)
