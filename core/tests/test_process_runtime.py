"""External-process plugin runtime: manifest, lifecycle, tools and operations.

user:“外部进程插件运行时。只有 MCP 能跑外部进程；Node 插件没有受支持的托管方式”
+(宿主托管一个 JSON-RPC stdio 子进程，插件照常声明工具/操作，生命周期、健康
检查和停用规则与 Python 后端一致)。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from lamtools_core.app import OperationCatalog
from lamtools_core.plugin_system import PluginContext, PluginHost
from lamtools_core.plugin_system.backend_runtime import register_manager
from lamtools_core.plugin_system.capabilities import read_capabilities
from lamtools_core.plugin_system.lifecycle import (
    await_plugin_backends,
    load_enabled_plugin_backends,
    start_plugin_backend,
    stop_plugin_backend,
)
from lamtools_core.plugin_system.operation_bridge import read_operations, register_plugin_operations
from lamtools_core.plugin_system.operations import register_plugin_system_operations
from lamtools_core.tool import ToolCall

WORKER = r'''
import json
import sys


def respond(request_id, result):
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    message = json.loads(line)
    request_id = message.get("id")
    method = message.get("method")
    params = message.get("params") or {}
    if method == "initialize":
        respond(request_id, {
            "name": "worker",
            "version": "1",
            "tools": [{"name": "process_echo"}],
            "operations": [{"name": "demo-process.ping"}],
        })
    elif method == "tools/call":
        respond(request_id, {
            "status": "ok",
            "content": "echo:" + str((params.get("arguments") or {}).get("text", "")),
            "metadata": {"callId": params.get("callId")},
        })
    elif method == "operations/call":
        respond(request_id, {
            "status": "ok",
            "payload": {
                "name": params.get("name"),
                "value": (params.get("payload") or {}).get("value"),
                "pid": __import__("os").getpid(),
            },
        })
    elif method == "health":
        respond(request_id, {"ok": True})
    elif method == "shutdown":
        respond(request_id, {})
        break
    else:
        respond(request_id, {"error": "unknown method"})
'''


def make_plugin(folder: Path, *, command: list[str] | None = None) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "worker.py").write_text(WORKER, encoding="utf-8")
    (folder / "tools.json").write_text(
        json.dumps(
            {
                "tools": [
                    {
                        "name": "process_echo",
                        "description": "Echo through the child process",
                        "input_schema": {"type": "object", "properties": {"text": {"type": "string"}}},
                        "permission": "auto_allow",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (folder / "operations.json").write_text(
        json.dumps(
            {
                "operations": [
                    {
                        "name": "demo-process.ping",
                        "description": "Ping through the child process",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    manifest = {
        "name": "demo-process",
        "version": "1.0.0",
        "runtime": {
            "kind": "process",
            "command": command or [sys.executable, "worker.py"],
            "startupTimeoutMs": 10000,
            "requestTimeoutMs": 10000,
        },
        "tools": ["./tools.json"],
        "operations": ["./operations.json"],
    }
    (folder / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    return folder


async def boot(tmp_path: Path):
    folder = make_plugin(tmp_path / "plugins" / "demo-process")
    host = PluginHost(roots=[folder.parent], state_path=tmp_path / "state.json")
    context = PluginContext(work_root=tmp_path, data_dir=tmp_path)
    handles = load_enabled_plugin_backends(host.discover(), context, start=True)
    manager = register_manager(host, handles, context)
    await await_plugin_backends(manager.handles)
    catalog = OperationCatalog()
    context.operation_catalog = catalog
    register_plugin_system_operations(catalog, host)
    register_plugin_operations(catalog, host)
    return host, manager, catalog, folder


def test_process_manifest_does_not_require_python_handlers(tmp_path: Path) -> None:
    folder = make_plugin(tmp_path / "plugins" / "demo-process")
    host = PluginHost(roots=[folder.parent], state_path=tmp_path / "state.json")
    plugin = host.get("demo-process")
    assert plugin is not None

    tools = read_capabilities(plugin).tools
    operations = read_operations(plugin)
    assert [tool.name for tool in tools] == ["process_echo"]
    assert [operation.name for operation in operations] == ["demo-process.ping"]
    # The declaration is accepted, and the placeholder handler never loads a
    # Python module for a process plugin.
    assert tools[0].handler == "process:process_echo"
    assert operations[0].handler == "process:demo-process.ping"


async def test_process_lifecycle_tools_and_operations(tmp_path: Path) -> None:
    host, manager, catalog, folder = await boot(tmp_path)
    handle = manager.get("demo-process")
    assert handle is not None and handle.started
    assert manager.status("demo-process")["state"] == "ready"
    health = handle.value.health_check()
    assert health["ready"] is True
    assert health["pid"]

    result = await handle.value.call_tool(
        "process_echo",
        ToolCall(id="call-1", name="process_echo", arguments={"text": "你好"}),
    )
    assert result.status == "ok"
    assert result.content == "echo:你好"
    assert result.metadata["callId"] == "call-1"

    ping = await catalog.execute("demo-process.ping", {"value": 42})
    assert ping.status == "ok"
    assert ping.payload["name"] == "demo-process.ping"
    assert ping.payload["value"] == 42
    assert ping.payload["pid"] == health["pid"]

    pid = health["pid"]
    await manager.stop("demo-process")
    assert manager.status("demo-process")["state"] != "ready"
    assert handle.value.health_check()["ready"] is False

    # Restart is host-managed: the same declaration starts a fresh process.
    await start_plugin_backend(handle, handle.context)
    try:
        assert handle.value.health_check()["ready"] is True
        assert handle.value.health_check()["pid"] != pid
    finally:
        await stop_plugin_backend(handle)


async def test_process_plugin_can_be_disabled_and_reenabled(tmp_path: Path) -> None:
    host, manager, catalog, folder = await boot(tmp_path)
    assert (await catalog.execute("demo-process.ping", {})).status == "ok"

    disabled = await catalog.execute("plugin.system.disable", {"name": "demo-process"})
    assert disabled.status == "ok", disabled.payload
    stopped = manager.get("demo-process")
    assert stopped is None or stopped.started is False
    with pytest.raises(KeyError):
        await catalog.execute("demo-process.ping", {})

    enabled = await catalog.execute("plugin.system.enable", {"name": "demo-process"})
    assert enabled.status == "ok", enabled.payload
    assert (await catalog.execute("demo-process.ping", {})).status == "ok"
    await manager.stop("demo-process")


async def test_dead_process_reports_an_error_instead_of_hanging(tmp_path: Path) -> None:
    folder = make_plugin(tmp_path / "plugins" / "demo-process", command=[sys.executable, "-c", "print('bye')"])
    host = PluginHost(roots=[folder.parent], state_path=tmp_path / "state.json")
    context = PluginContext(work_root=tmp_path, data_dir=tmp_path)
    handles = load_enabled_plugin_backends(host.discover(), context, start=False)
    handle = handles[0]
    with pytest.raises(Exception):
        await start_plugin_backend(handle, context)
    assert handle.started is False
    assert handle.state == "failed"
    assert handle.last_error is not None
    await stop_plugin_backend(handle)
