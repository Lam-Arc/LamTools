"""user:“逐项核对固定上游源码及手册”+(仅列原执行提供方真实解析的本机shell候选)。"""
import asyncio
import os
from pathlib import Path

import pytest

from .test_plugin_working_directory import env


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "nt", reason="original process owner is Windows-only")
async def test_resolved_shell_candidates_match_original_provider(env, monkeypatch):
    from lamtools_core.plugin_system import terminal_controller
    ctx, _, _, _ = env
    monkeypatch.setattr(terminal_controller, "_SHELL_CANDIDATES", ("cmd.exe", "pwsh.exe", "not-a-real-dsh-shell-9127.exe"))
    api = ctx.terminal_controller
    result = await api.shells("s")
    assert result["pty"] is False
    assert any(item["name"].casefold() == "cmd.exe" for item in result["shells"])
    assert all(Path(item["path"]).is_file() for item in result["shells"])
    assert all("not-a-real" not in item["name"] for item in result["shells"])
    for item in result["shells"]:
        assert Path(item["path"]) == ctx.processes.resolve_executable(item["name"])


@pytest.mark.asyncio
async def test_shells_rejects_hidden_session_before_path_lookup(env, monkeypatch):
    ctx, _, _, _ = env
    monkeypatch.setattr(ctx.processes, "resolve_executable", lambda *args, **kwargs: pytest.fail("hidden session reached lookup"))
    with pytest.raises(RuntimeError): await ctx.terminal_controller.shells("hidden")


@pytest.mark.asyncio
async def test_shells_rejects_withdrawn_session_after_resolution(env, monkeypatch):
    from lamtools_core.plugin_system import terminal_controller
    from lamtools_core.plugin_system.process_access import ProcessAccessError
    ctx, store, _, _ = env
    monkeypatch.setattr(terminal_controller, "_SHELL_CANDIDATES", ("missing.exe",))
    def changed(*args, **kwargs):
        store._session_visible = lambda sid, _: sid != "s"
        raise ProcessAccessError("process/not-found", "missing")
    monkeypatch.setattr(ctx.processes, "resolve_executable", changed)
    with pytest.raises(RuntimeError): await ctx.terminal_controller.shells("s")


@pytest.mark.asyncio
async def test_shells_propagates_provider_errors(env, monkeypatch):
    from lamtools_core.plugin_system.process_access import ProcessAccessError
    ctx, _, _, _ = env
    def unavailable(*args, **kwargs): raise ProcessAccessError("process/lookup-failed", "lookup failed")
    monkeypatch.setattr(ctx.processes, "resolve_executable", unavailable)
    with pytest.raises(ProcessAccessError) as error: await ctx.terminal_controller.shells("s")
    assert error.value.code == "process/lookup-failed"


@pytest.mark.asyncio
async def test_shells_empty_path_is_not_a_fake_provider(env, monkeypatch, tmp_path):
    ctx, _, _, _ = env
    monkeypatch.setenv("PATH", str(tmp_path))
    result = await ctx.terminal_controller.shells("s")
    assert result == {"shells": [], "pty": False, "default": None}


@pytest.mark.asyncio
async def test_shells_repeated_cancel_waits_for_real_admission_cleanup(env, monkeypatch):
    ctx, _, _, _ = env
    host = ctx.require_service("working_directory")
    entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    async def blocked(*args, **kwargs):
        entered.set()
        try: await asyncio.Event().wait()
        finally: cleaning.set(); await release.wait()
    monkeypatch.setattr(host, "call", blocked)
    task = asyncio.create_task(ctx.terminal_controller.shells("s"))
    try:
        await entered.wait(); task.cancel(); await cleaning.wait(); task.cancel(); await asyncio.sleep(0)
        assert not task.done() and not ctx._registration_scope._idle.is_set()
        release.set()
        with pytest.raises(asyncio.CancelledError): await task
        assert ctx._registration_scope._idle.is_set()
    finally:
        release.set(); await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "nt", reason="original process owner is Windows-only")
async def test_shells_over_explicit_authenticated_remote(env, tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
    ctx, _, _, _ = env
    host, catalog, old = _host(tmp_path); configure(host)
    ctx._secret_store = old._secret_store; host.backend_manager.context = ctx
    (host.get("hook-demo").root / "ops.py").write_text(
        "async def echo(request, *, context):\n"
        "    return await context.terminal_controller.shells(request.payload['body']['text'])\n", encoding="utf8")
    catalog.unregister_owner("plugin:hook-demo"); register_plugin_operations(catalog, host)
    app = FastAPI(); app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        url = "/plugin-remote/hook-demo/demo/echo"; body = {"args": {"text": "s"}}
        denied = await client.post(url, json=body, headers={"x-plugin-token": "wrong"})
        response = await client.post(url, json=body, headers={"x-plugin-token": plugin_http_token(host, "hook-demo")})
    assert denied.status_code == 401 and response.status_code == 200
    assert response.json()["payload"]["pty"] is False
    assert any(item["name"].casefold() == "cmd.exe" for item in response.json()["payload"]["shells"])


def test_shell_discovery_migration_is_manual(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root = source(tmp_path, {"index.ts": "export function apply(ctx) { ctx.remote.terminal.shells(); }"})
    report = export_port(root, tmp_path / "ported")
    row = next(item for item in report["remotes"] if item["name"] == "terminal.shells")
    assert row["suggestedContract"] == "context.terminal_controller.shells"
    assert report["runtimeVerified"] is False
