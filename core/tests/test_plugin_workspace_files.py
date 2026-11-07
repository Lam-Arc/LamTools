"""user:“第二阶段结束后 就继续开展第三阶段”+(文件控制器复用真实会话目录和原文件系统，不能让请求指定授权根)。"""
import asyncio
import json
from copy import copy

import httpx
import pytest
from fastapi import FastAPI

from .test_plugin_working_directory import env


def test_workspace_file_migration_handoff_names_only_real_controller_methods(tmp_path):
    # user:“保持迁移脚本、机器清单、文档同步”+(只为真实文件控制器提供候选，未实现changes流和二进制传输明确交给agent)。
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root = source(tmp_path, {"index.ts": "export function apply(ctx) { ctx.workspaceFiles.read(); ctx.workspaceFiles.readBytes(); ctx.workspaceFiles.stat(); ctx.workspaceFiles.list(); ctx.workspaceFiles.changes(); }"})
    output = tmp_path / "ported"
    report = export_port(root, output)
    methods = {row["name"]: row for row in report["workspaceFileMethods"]}
    for name, target in [("read", "read"), ("readBytes", "read_bytes"), ("stat", "stat"), ("list", "list")]:
        assert methods["workspaceFiles." + name]["candidateContract"] == "context.workspace_files." + target
        assert methods["workspaceFiles." + name]["conversion"] == "agent-required"
    assert methods["workspaceFiles.changes"]["candidateContract"] == "context.workspace_files.changes"
    handoff = (output / "PORTING.md").read_text(encoding="utf8")
    assert "plugin_workspace_files.md" in handoff and "context.workspace_files.read_bytes" in handoff
    assert report["runtimeVerified"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("text,offset,limit,expected,lines,eof", [
    ("a\nb\nc\n", 2, 1, "b", 1, False), ("a\n", 1, 1, "a", 1, True),
    ("\n", 1, 1, "", 1, True), ("", 1, 2, "", 0, True),
    ("a\nb", 5, 2, "", 0, True), ("中\n尾", 1, 2, "中\n尾", 2, True)])
async def test_session_file_line_pages_preserve_empty_lines_and_eof(env, text, offset, limit, expected, lines, eof):
    # user:“复用原宿主权威”+(真实文件按选定会话目录分页，末尾换行不虚构空行，空页与空行可区分)。
    ctx, store, _, root = env
    (root / "page.txt").write_bytes(text.encode("utf8"))
    before = await store.get_readonly_revision("s")
    result = await ctx.workspace_files.read("s", "page.txt", offset=offset, limit=limit)
    assert (result["text"], result["lines"], result["eof"]) == (expected, lines, eof)
    assert result["offset"] == offset and result["bytes"] == len(text.encode("utf8"))
    assert result["absolute_path"] == str(root / "page.txt") and result["version"]
    assert await store.get_readonly_revision("s") == before


@pytest.mark.asyncio
async def test_session_file_directory_and_binary_use_selected_root_and_original_bounds(env):
    # user:“完成真实接口、参数/错误、作用域、取消/清理”+(真实二进制窗口、目录和元数据共用会话目录，根外/隐藏会话不能读取)。
    ctx, _, _, root = env
    (root / "parent.txt").write_text("outside selected session")
    (root / "one" / "binary.bin").write_bytes(b"\x00\x01\xff\x02")
    directory = await ctx.working_directory.get("s")
    await ctx.working_directory.set("s", "one", expected_revision=directory.revision)
    api = ctx.workspace_files
    result = await api.read_bytes("s", "binary.bin", offset=1, length=2)
    assert result["data"] == b"\x01\xff" and result["offset"] == 1 and not result["eof"]
    assert (await api.read_bytes("s", "binary.bin"))["data"] == b"\x00\x01\xff\x02"
    assert (await api.stat("s", "binary.bin"))["bytes"] == 4
    assert [row["name"] for row in (await api.list("s"))["entries"]] == ["binary.bin"]
    for session, path in [("s", "../parent.txt"), ("hidden", "parent.txt")]:
        with pytest.raises((ValueError, RuntimeError)):
            await api.stat(session, path)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["host", "scope", "cancel"])
async def test_session_file_admission_rechecks_authority_and_cancellation(env, monkeypatch, change):
    # user:“完成真实接口、参数/错误、作用域、取消/清理”+(等待原会话目录时更换宿主/撤回/取消，不能继续触及文件，租约释放)。
    ctx, _, _, _ = env
    from lamtools_core.plugin_system.services import ServiceError
    api = ctx.workspace_files
    host = ctx.service("working_directory")
    original = host.call
    entered, release = asyncio.Event(), asyncio.Event()
    async def gated(*args, **kwargs):
        result = await original(*args, **kwargs)
        entered.set()
        await release.wait()
        return result
    monkeypatch.setattr(host, "call", gated)
    pending = asyncio.create_task(api.stat("s", "never-read.txt"))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        if change == "host": ctx.set_service("working_directory", copy(host))
        elif change == "scope": ctx._registration_scope.revoke()
        else: pending.cancel()
        release.set()
        if change == "cancel":
            with pytest.raises(asyncio.CancelledError): await pending
        else:
            with pytest.raises((ValueError, ServiceError)) as error: await pending
            assert getattr(error.value, "code", "") == ("workspace-file/host-changed" if change == "host" else "service/scope-closed")
        assert not ctx._registration_scope._calls
    finally:
        ctx.set_service("working_directory", host)
        release.set()
        await asyncio.gather(pending, return_exceptions=True)


@pytest.mark.asyncio
async def test_session_file_page_budget_excludes_skipped_prefix_and_rejects_bad_text(env, monkeypatch):
    # user:“完成真实接口、参数/错误、作用域、取消/清理”+(页限制只计算返回页，不能为跳过前缀保留无限长行，坏文本明确拒绝)。
    from lamtools_core.plugin_system import workspace_files
    ctx, _, _, root = env
    monkeypatch.setattr(workspace_files, "MAX_PAGE_BYTES", 16)
    (root / "prefix.txt").write_bytes(b"x" * 100 + b"\nok")
    assert (await ctx.workspace_files.read("s", "prefix.txt", offset=2, limit=1))["text"] == "ok"
    for name, data, code in [("long.txt", b"x" * 17, "workspace-file/too-large"),
        ("bad.txt", b"\xff", "workspace-file/not-text"), ("nul.txt", b"a\x00b", "workspace-file/not-text")]:
        (root / name).write_bytes(data)
        with pytest.raises(ValueError) as error:
            await ctx.workspace_files.read("s", name)
        assert getattr(error.value, "code", None) == code


@pytest.mark.asyncio
@pytest.mark.parametrize("text,offset,expected", [("x" * 16 + "\n", 1, "x" * 16),
    ("x" * 15 + "\n\n", 1, "x" * 15 + "\n"), ("x" * 8192 + "\nend", 2, "end")],
    ids=["exact-line", "exact-empty-line", "chunk-prefix"])
async def test_page_exact_budget_and_chunk_boundary_do_not_create_trailing_empty_line(env, monkeypatch, text, offset, expected):
    # user:“完成真实接口、参数/错误、作用域、取消/清理”+(页恰好到限额时末尾换行不算新行，跨原读取块的前缀不改变页边界)。
    from lamtools_core.plugin_system import workspace_files
    ctx, _, _, root = env
    monkeypatch.setattr(workspace_files, "MAX_PAGE_BYTES", 16)
    (root / "exact.txt").write_bytes(text.encode("utf8"))
    result = await ctx.workspace_files.read("s", "exact.txt", offset=offset, limit=10)
    assert result["text"] == expected and result["eof"]


@pytest.mark.asyncio
async def test_session_file_controller_is_callable_through_explicit_remote_without_root_override(env):
    # user:“第二阶段结束后 就继续开展第三阶段”+(实际HTTP到原会话/文件权威，不信任客户端授权根，隐藏会话仍拒绝)。
    from .test_plugin_http_routes import _host
    from lamtools_core.app.operation_catalog import OperationResult
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
    ctx, store, _, root = env
    (root / "remote.txt").write_text("first\nsecond", encoding="utf8")
    host, catalog, _ = _host(root)
    path = host.get("hook-demo").root / "plugin.json"
    manifest = json.loads(path.read_text(encoding="utf8"))
    manifest["http"]["remote"] = [{"namespace": "workspaceFiles", "method": "read", "route": "/hook",
        "argsSchema": {"type": "object", "properties": {"session_id": {"type": "string"}, "path": {"type": "string"},
            "offset": {"type": "integer"}, "limit": {"type": "integer"}}, "required": ["session_id", "path", "offset", "limit"], "additionalProperties": False}}]
    path.write_text(json.dumps(manifest), encoding="utf8")
    host._invalidate()
    async def read(request):
        try:
            return OperationResult(request.name, await ctx.workspace_files.read(**request.payload["body"]))
        except (ValueError, RuntimeError) as error:
            return OperationResult(request.name, {"code": getattr(error, "code", "invalid")}, status="failed")
    catalog.unregister_owner("plugin:hook-demo")
    catalog.register("hook-demo.echo", read, owner="plugin:hook-demo")
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    before = await store.get_readonly_revision("s")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
        headers={"x-plugin-token": plugin_http_token(host, "hook-demo")}) as client:
        args = {"session_id": "s", "path": "remote.txt", "offset": 2, "limit": 1}
        response = await client.post("/plugin-remote/hook-demo/workspaceFiles/read", json={"args": args})
        assert response.status_code == 200 and response.json()["payload"]["text"] == "second"
        assert (await client.post("/plugin-remote/hook-demo/workspaceFiles/read", json={"args": {**args, "root": str(root.parent)}})).status_code == 400
        response = await client.post("/plugin-remote/hook-demo/workspaceFiles/read", json={"args": {**args, "session_id": "hidden"}})
        assert response.status_code == 400 and "second" not in response.text
    assert await store.get_readonly_revision("s") == before
