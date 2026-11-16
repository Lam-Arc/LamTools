"""user:“逐项核对固定上游源码及手册”+(大文件文本页只限制实际前缀扫描，不拒绝短的前部页面)。"""
import pytest

from .test_plugin_working_directory import env


@pytest.mark.asyncio
@pytest.mark.parametrize("offset,expected", [(1, "first"), (2, "second")])
async def test_page_within_scan_budget_reads_file_larger_than_budget(env, monkeypatch, offset, expected):
    from lamtools_core.plugin_system import workspace_files

    ctx, _, _, root = env
    monkeypatch.setattr(workspace_files, "MAX_SOURCE_BYTES", 16)
    (root / "large.txt").write_bytes(b"first\nsecond\n" + b"x" * 50)
    page = await ctx.workspace_files.read("s", "large.txt", offset=offset, limit=1)
    assert page["text"] == expected and page["lines"] == 1 and page["eof"] is False
    with pytest.raises(ValueError) as error:
        ctx.filesystem.stream_text("large.txt", max_bytes=16)
    assert error.value.code == "fs/too-large"


@pytest.mark.asyncio
async def test_page_requiring_more_than_scan_budget_fails_explicitly(env, monkeypatch):
    from pathlib import Path
    from lamtools_core.plugin_system import workspace_files

    ctx, _, _, root = env
    monkeypatch.setattr(workspace_files, "MAX_SOURCE_BYTES", 16)
    target = root / "large.txt"
    target.write_bytes(b"x" * 16 + b"\nlate\n")
    original_open = Path.open
    read_sizes = []

    class TrackedFile:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            self.stream.__enter__()
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def __getattr__(self, name):
            return getattr(self.stream, name)

        def read(self, size):
            data = self.stream.read(size)
            read_sizes.append(len(data))
            return data

    def tracked_open(path, *args, **kwargs):
        stream = original_open(path, *args, **kwargs)
        return TrackedFile(stream) if path == target and args and args[0] == "rb" else stream

    monkeypatch.setattr(Path, "open", tracked_open)
    with pytest.raises(ValueError) as error:
        await ctx.workspace_files.read("s", "large.txt", offset=2, limit=1)
    assert error.value.code == "workspace-file/too-large"
    assert sum(read_sizes) == 16


@pytest.mark.asyncio
async def test_large_file_change_during_scan_is_rejected(env, monkeypatch):
    from pathlib import Path
    from lamtools_core.plugin_system import workspace_files

    ctx, _, _, root = env
    monkeypatch.setattr(workspace_files, "MAX_SOURCE_BYTES", 9000)
    target = root / "large.txt"
    target.write_bytes(b"x" * 8200 + b"\nlate\n" + b"x" * 1000)
    original_open = Path.open
    changed = False

    class ChangeAfterRead:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            self.stream.__enter__()
            return self

        def __exit__(self, *args):
            nonlocal changed
            result = self.stream.__exit__(*args)
            if not changed:
                changed = True
                with original_open(target, "ab") as stream:
                    stream.write(b"changed")
            return result

        def __getattr__(self, name):
            return getattr(self.stream, name)

    def tracked_open(path, *args, **kwargs):
        stream = original_open(path, *args, **kwargs)
        return ChangeAfterRead(stream) if path == target and args and args[0] == "rb" else stream

    monkeypatch.setattr(Path, "open", tracked_open)
    with pytest.raises(ValueError) as error:
        await ctx.workspace_files.read("s", "large.txt", offset=2, limit=1)
    assert changed and error.value.code == "fs/changed"


@pytest.mark.asyncio
async def test_exact_scan_budget_file_retains_end_of_file(env, monkeypatch):
    from lamtools_core.plugin_system import workspace_files

    ctx, _, _, root = env
    monkeypatch.setattr(workspace_files, "MAX_SOURCE_BYTES", 16)
    (root / "exact.txt").write_bytes(b"first\n" + b"x" * 10)
    page = await ctx.workspace_files.read("s", "exact.txt", offset=2, limit=1)
    assert page["text"] == "x" * 10 and page["eof"] is True


@pytest.mark.asyncio
async def test_page_at_scan_boundary_cannot_claim_eof_without_lookahead(env, monkeypatch):
    from lamtools_core.plugin_system import workspace_files

    ctx, _, _, root = env
    monkeypatch.setattr(workspace_files, "MAX_SOURCE_BYTES", 16)
    (root / "boundary.txt").write_bytes(b"first\n" + b"x" * 9 + b"\nmore")
    with pytest.raises(ValueError) as error:
        await ctx.workspace_files.read("s", "boundary.txt", offset=2, limit=1)
    assert error.value.code == "workspace-file/too-large"


@pytest.mark.asyncio
async def test_actual_over_64m_file_can_return_early_page(env):
    ctx, _, _, root = env
    with (root / "large.txt").open("wb") as stream:
        stream.write(b"first\nsecond\n")
        stream.seek(64 * 1024 * 1024)
        stream.write(b"x")
    page = await ctx.workspace_files.read("s", "large.txt", offset=1, limit=1)
    assert page["text"] == "first" and page["eof"] is False


@pytest.mark.asyncio
async def test_large_file_page_uses_authenticated_remote_and_session_scope(env, monkeypatch, tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system import workspace_files
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token

    ctx, _, _, root = env
    monkeypatch.setattr(workspace_files, "MAX_SOURCE_BYTES", 16)
    (root / "large.txt").write_bytes(b"first\nsecond\n" + b"x" * 50)
    host, catalog, previous = _host(tmp_path)
    configure(host)
    ctx._secret_store = previous._secret_store
    host.backend_manager.context = ctx
    (host.get("hook-demo").root / "ops.py").write_text(
        "async def echo(request, *, context):\n"
        "    return await context.workspace_files.read(request.payload['body']['text'], 'large.txt', offset=1, limit=1)\n",
        encoding="utf8")
    catalog.unregister_owner("plugin:hook-demo")
    register_plugin_operations(catalog, host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        url = "/plugin-remote/hook-demo/demo/echo"
        headers = {"x-plugin-token": plugin_http_token(host, "hook-demo")}
        good = await client.post(url, json={"args": {"text": "s"}}, headers=headers)
        hidden = await client.post(url, json={"args": {"text": "hidden"}}, headers=headers)
        denied = await client.post(url, json={"args": {"text": "s"}}, headers={"x-plugin-token": "wrong"})
    assert good.status_code == 200 and good.json()["payload"]["text"] == "first"
    assert hidden.status_code == 400 and "first" not in hidden.text
    assert denied.status_code == 401


def test_migration_records_scan_limit_for_large_files(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port

    root = source(tmp_path, {"index.ts": "export function apply(ctx) { ctx.remote.workspaceFiles.read(); }"})
    export_port(root, tmp_path / "ported")
    handoff = (tmp_path / "ported" / "PORTING.md").read_text(encoding="utf8")
    assert "文本页扫描最多64MiB" in handoff
