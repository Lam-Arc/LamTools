"""user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(编码上传复用原会话附件持久化，不冒充DSH暂存凭证)。"""
import asyncio
import base64
from pathlib import Path

import pytest
from .test_plugin_session_data import env


@pytest.mark.asyncio
async def test_encoded_upload_uses_real_session_attachment_storage(env):
    ctx, _, _, _ = env
    data = b"\x00\xffreal-file\n"
    saved = await ctx.file_uploads.save_encoded("s", filename="sample.bin", content_base64=base64.b64encode(data).decode())
    assert saved["session_id"] == "s" and Path(saved["path"]).read_bytes() == data
    assert (await ctx.attachments.get("s", saved["id"]))["id"] == saved["id"]
    with pytest.raises(RuntimeError):
        await ctx.file_uploads.save_encoded("hidden", filename="sample.bin", content_base64="YQ==")


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [None, [], " ", "YQ", "YQ==\n", "ab=c", "YQ===", "é"])
async def test_invalid_noncanonical_base64_is_rejected_before_host(env, value, monkeypatch):
    ctx, _, _, _ = env
    host = ctx.require_service("session_data")
    async def forbidden(*args, **kwargs): pytest.fail("invalid upload must not touch host")
    monkeypatch.setattr(host, "call", forbidden)
    with pytest.raises(ValueError): await ctx.file_uploads.save_encoded("s", filename="a", content_base64=value)


@pytest.mark.asyncio
async def test_caller_cancellation_waits_for_original_dispatched_write(env, monkeypatch):
    ctx, _, _, _ = env
    host = ctx.require_service("session_data")
    original = host.call
    entered, release, committed = asyncio.Event(), asyncio.Event(), asyncio.Event()
    async def gated(*args, **kwargs):
        entered.set()
        await release.wait()
        value = await original(*args, **kwargs)
        committed.set()
        return value
    monkeypatch.setattr(host, "call", gated)
    task = asyncio.create_task(ctx.file_uploads.save_encoded("s", filename="cancel.txt", content_base64="YQ=="))
    try:
        await entered.wait()
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError): await task
        assert committed.is_set()
        assert any(item["filename"] == "cancel.txt" for item in (await ctx.attachments.list("s"))["items"])
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_encoded_upload_byte_limit_checks_decoded_size_before_write(env, monkeypatch):
    from lamtools_core.plugin_system import file_uploads
    monkeypatch.setattr(file_uploads, "MAX_ENCODED_UPLOAD_BYTES", 2)
    ctx, _, _, _ = env
    saved = await ctx.file_uploads.save_encoded("s", filename="two.bin", content_base64=base64.b64encode(b"12").decode())
    assert Path(saved["path"]).read_bytes() == b"12"
    with pytest.raises(ValueError):
        await ctx.file_uploads.save_encoded("s", filename="three.bin", content_base64=base64.b64encode(b"123").decode())


@pytest.mark.asyncio
async def test_encoded_upload_crosses_actual_plugin_http_and_original_store(env, tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
    ctx, _, _, _ = env
    host, catalog, original_context = _host(tmp_path)
    configure(host)
    ctx._secret_store = original_context._secret_store
    host.backend_manager.context = ctx
    (host.get("hook-demo").root / "ops.py").write_text(
        "async def echo(request, *, context):\n"
        "    item = await context.file_uploads.save_encoded('s', filename='remote.bin', content_base64=request.payload['body']['text'])\n"
        "    return {'id': item['id']}\n", encoding="utf8")
    catalog.unregister_owner("plugin:hook-demo")
    register_plugin_operations(catalog, host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        endpoint = "/plugin-remote/hook-demo/demo/echo"
        response = await client.post(endpoint, json={"args": {"text": "AP9h"}},
            headers={"x-plugin-token": plugin_http_token(host, "hook-demo")})
        denied = await client.post(endpoint, json={"args": {"text": "AP9h"}}, headers={"x-plugin-token": "wrong"})
    assert response.status_code == 200 and denied.status_code == 401
    item = await ctx.attachments.get("s", response.json()["payload"]["id"])
    assert Path(item["path"]).read_bytes() == b"\x00\xffa"


def test_upload_migration_mentions_saved_attachment_not_staged_receipt(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root = source(tmp_path, {"index.ts": "export function apply(ctx) { ctx.fileUploads.upload(); }"})
    report = export_port(root, tmp_path / "ported")
    item = next(row for row in report["services"] if row["name"] == "fileUploads")
    assert item["candidateContract"] == "context.file_uploads.save_encoded"
    assert "暂存" in item["difference"] and report["runtimeVerified"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["host", "scope", "root"])
async def test_upload_rejects_stale_binding_before_dispatch(env, change, tmp_path, monkeypatch):
    ctx, _, _, _ = env
    host = ctx.require_service("session_data")
    api = ctx.file_uploads
    async def forbidden(*args, **kwargs): pytest.fail("stale upload must not dispatch")
    monkeypatch.setattr(host, "call", forbidden)
    if change == "host": ctx.set_service("session_data", object())
    elif change == "scope": ctx._registration_scope.revoke()
    else: ctx.work_root = tmp_path / "other"
    with pytest.raises((ValueError, RuntimeError)):
        await api.save_encoded("s", filename="a", content_base64="YQ==")
