"""user:“第二阶段结束后 就继续开展第三阶段”+(二进制走明确Remote的真实multipart响应，不能把Python bytes或base64假作原生传输)。"""
import json
from email import policy
from email.parser import BytesParser

import httpx
import pytest
from fastapi import FastAPI

from .test_plugin_http_routes import _host
from .test_plugin_remote_gateway import configure
from .test_plugin_working_directory import env
from lamtools_core.app.operation_catalog import OperationResult
from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token


def set_encoding(host, encoding):
    path = host.get("hook-demo").root / "plugin.json"
    data = json.loads(path.read_text(encoding="utf8"))
    if encoding is not None:
        data["http"]["remote"][0]["resultEncoding"] = encoding
    path.write_text(json.dumps(data), encoding="utf8")
    host._invalidate()


def decode_parts(response):
    message = BytesParser(policy=policy.default).parsebytes(
        b"Content-Type: " + response.headers["content-type"].encode() + b"\r\nMIME-Version: 1.0\r\n\r\n" + response.content)
    assert message.get_content_type() == "multipart/form-data"
    parts = {part.get_param("name", header="content-disposition"): part.get_payload(decode=True) for part in message.iter_parts()}
    metadata = json.loads(parts.pop("metadata"))
    return metadata, parts


def test_binary_remote_contract_and_handoff_are_explicit_without_automatic_opt_in(tmp_path):
    # user:“保持迁移脚本、机器清单、文档同步”+(交接说明真实二进制选择与限制，生成包不得擅自为上游方法开启字节出口)。
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root = source(tmp_path, {"index.ts": "export function apply(ctx) { ctx.workspaceFiles.readBytes(); }"})
    output = tmp_path / "ported"
    report = export_port(root, output)
    contract = report["sundayHostContracts"]["remoteGateway"]
    assert contract["version"] == 5
    assert "plugin.json http.remote.resultEncoding" in contract["apis"]
    assert "resultEncoding" in (output / "PORTING.md").read_text(encoding="utf8")
    assert not json.loads((output / "plugin.json").read_text(encoding="utf8")).get("http", {}).get("remote")
    assert report["runtimeVerified"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("encoding", ["unknown", [], {}])
async def test_invalid_binary_declaration_never_dispatches_operation(tmp_path, encoding):
    # user:“完成真实接口、参数/错误、作用域、取消/清理”+(结果传输方式来自清单枚举，错误类型/未知选择在进入业务前拒绝)。
    host, catalog, _ = _host(tmp_path)
    configure(host)
    set_encoding(host, encoding)
    catalog.unregister_owner("plugin:hook-demo")
    catalog.register("hook-demo.echo", lambda request: pytest.fail("invalid descriptor must not dispatch"), owner="plugin:hook-demo")
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/plugin-remote/hook-demo/demo/echo", json={"args": {"text": "invalid"}},
            headers={"x-plugin-token": plugin_http_token(host, "hook-demo")})
    assert response.status_code == 400


@pytest.mark.asyncio
@pytest.mark.parametrize("binary", [False, True])
async def test_failed_business_response_never_uses_binary_success_transport(tmp_path, binary):
    # user:“复用原宿主权威”+(原失败保持JSON，不让失败业务夹带字节走成功multipart出口)。
    host, catalog, _ = _host(tmp_path)
    configure(host)
    set_encoding(host, "multipart")
    value = {"data": b"private-failed-payload"} if binary else {"code": "business/rejected"}
    catalog.unregister_owner("plugin:hook-demo")
    catalog.register("hook-demo.echo", lambda request: OperationResult(request.name, value, status="failed"), owner="plugin:hook-demo")
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/plugin-remote/hook-demo/demo/echo", json={"args": {"text": "failure"}},
            headers={"x-plugin-token": plugin_http_token(host, "hook-demo")})
    assert response.status_code == (502 if binary else 400)
    assert response.headers["content-type"].startswith("application/json")
    assert b"private-failed-payload" not in response.content


@pytest.mark.asyncio
@pytest.mark.parametrize("shape", ["root", "nested"])
async def test_explicit_binary_remote_returns_raw_bytes_with_relative_attachment_paths(tmp_path, shape):
    # user:“完成真实接口、参数/错误、作用域、取消/清理”+(真实响应保留任意字节、空字节和Unicode字段，附件路径明确，不把二进制塞进JSON或base64)。
    host, catalog, _ = _host(tmp_path)
    configure(host)
    set_encoding(host, "multipart")
    data = bytes(range(256)) + b"\r\n\x00\xff"
    value = data if shape == "root" else {"文件": [data, {"empty": b""}], "label": "中文"}
    catalog.unregister_owner("plugin:hook-demo")
    catalog.register("hook-demo.echo", lambda request: OperationResult(request.name, value), owner="plugin:hook-demo")
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/plugin-remote/hook-demo/demo/echo", json={"args": {"text": "binary"}},
            headers={"x-plugin-token": plugin_http_token(host, "hook-demo")})
    assert response.status_code == 200
    metadata, parts = decode_parts(response)
    assert metadata["name"] == "hook-demo.echo" and metadata["status"] == "ok"
    expected = [["payload"]] if shape == "root" else [["payload", "文件", 0], ["payload", "文件", 1, "empty"]]
    assert [entry["path"] for entry in metadata["attachments"]] == expected
    assert all(entry["codec"] == "bytes" for entry in metadata["attachments"])
    assert parts[metadata["attachments"][0]["part"]] == data
    if shape == "nested":
        assert metadata["payload"] == {"文件": [None, {"empty": None}], "label": "中文"}
        assert parts[metadata["attachments"][1]["part"]] == b""
    else:
        assert metadata["payload"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["bytes-limit", "metadata-limit", "attachment-limit", "depth-limit", "node-limit", "nan", "cycle", "unmarked"])
async def test_invalid_or_oversized_remote_results_fail_without_binary_delivery(tmp_path, monkeypatch, case):
    # user:“完成真实接口、参数/错误、作用域、取消/清理”+(结果限制在公开响应前生效，循环/非有限JSON/过量二进制不能引发500或半份multipart)。
    from lamtools_core.plugin_system import remote_gateway
    host, catalog, _ = _host(tmp_path)
    configure(host)
    set_encoding(host, None if case == "unmarked" else "multipart")
    value = {"data": b"data"}
    if case == "bytes-limit": monkeypatch.setattr(remote_gateway, "MAX_BINARY_BYTES", 3, raising=False)
    if case == "metadata-limit":
        monkeypatch.setattr(remote_gateway, "MAX_RESULT_JSON_BYTES", 64, raising=False)
        value = {"text": "x" * 100}
    if case == "attachment-limit":
        monkeypatch.setattr(remote_gateway, "MAX_ATTACHMENTS", 1, raising=False)
        value = {"data": [b"a", b"b"]}
    if case == "depth-limit":
        monkeypatch.setattr(remote_gateway, "MAX_RESULT_DEPTH", 2, raising=False)
        value = {"data": {"nested": {"deep": "value"}}}
    if case == "node-limit": monkeypatch.setattr(remote_gateway, "MAX_RESULT_NODES", 2, raising=False)
    if case == "nan": value = {"number": float("nan")}
    if case == "cycle":
        value = {}
        value["self"] = value
    catalog.unregister_owner("plugin:hook-demo")
    catalog.register("hook-demo.echo", lambda request: OperationResult(request.name, value), owner="plugin:hook-demo")
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/plugin-remote/hook-demo/demo/echo", json={"args": {"text": "limits"}},
            headers={"x-plugin-token": plugin_http_token(host, "hook-demo")})
    assert response.status_code == 502
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"]["code"] == "gateway/invalid-result"


@pytest.mark.asyncio
async def test_binary_capable_method_keeps_plain_json_when_no_attachments(tmp_path):
    # user:“复用原宿主权威”+(没有二进制时保留原JSON envelope，不强制multipart或改变原操作结果)。
    host, catalog, _ = _host(tmp_path)
    configure(host)
    set_encoding(host, "multipart")
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/plugin-remote/hook-demo/demo/echo", json={"args": {"text": "normal"}},
            headers={"x-plugin-token": plugin_http_token(host, "hook-demo")})
    assert response.status_code == 200 and response.headers["content-type"].startswith("application/json")
    assert response.json()["payload"]["echo"] == {"text": "normal"}


@pytest.mark.asyncio
async def test_session_file_bytes_cross_http_as_raw_multipart_and_hidden_session_stays_denied(env):
    # user:“第二阶段结束后 就继续开展第三阶段”+(文件字节从真实会话文件系统到HTTP往返，隐藏会话不能借二进制出口读取)。
    ctx, _, _, root = env
    (root / "binary.bin").write_bytes(b"\x00\xff\x80\x01")
    host, catalog, _ = _host(root)
    configure(host)
    path = host.get("hook-demo").root / "plugin.json"
    manifest = json.loads(path.read_text(encoding="utf8"))
    manifest["http"]["remote"][0].update(namespace="workspaceFiles", method="readBytes", resultEncoding="multipart",
        argsSchema={"type": "object", "properties": {"session_id": {"type": "string"}, "path": {"type": "string"}},
            "required": ["session_id", "path"], "additionalProperties": False})
    path.write_text(json.dumps(manifest), encoding="utf8")
    host._invalidate()
    async def read(request):
        try:
            return OperationResult(request.name, await ctx.workspace_files.read_bytes(**request.payload["body"]))
        except (ValueError, RuntimeError) as error:
            return OperationResult(request.name, {"code": getattr(error, "code", "invalid")}, status="failed")
    catalog.unregister_owner("plugin:hook-demo")
    catalog.register("hook-demo.echo", read, owner="plugin:hook-demo")
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
        headers={"x-plugin-token": plugin_http_token(host, "hook-demo")}) as client:
        endpoint = "/plugin-remote/hook-demo/workspaceFiles/readBytes"
        response = await client.post(endpoint, json={"args": {"session_id": "s", "path": "binary.bin"}})
        assert response.status_code == 200
        metadata, parts = decode_parts(response)
        assert metadata["payload"]["bytes"] == 4
        assert parts[metadata["attachments"][0]["part"]] == b"\x00\xff\x80\x01"
        response = await client.post(endpoint, json={"args": {"session_id": "hidden", "path": "binary.bin"}})
        assert response.status_code == 400 and response.headers["content-type"].startswith("application/json")
