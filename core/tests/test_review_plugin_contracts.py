"""user:“该修修”+(验证插件配置、协议参数与转写的实际契约)。"""
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

ROOT = Path(__file__).resolve().parents[2] / "plugins/bili-scroll"


def load(name, path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_setup_does_not_rewrite_release_template(tmp_path, monkeypatch):
    ops = load("review_ops", ROOT / "ops.py", monkeypatch)
    template = tmp_path / "mcp.json"
    original = '{"mcpServers":{"bilibili":{"command":"{{PLUGIN_PYTHON}}"}}}'
    template.write_text(original, encoding="utf8")
    python = tmp_path / "python.exe"
    python.touch()
    monkeypatch.setattr(ops, "_MCP_JSON", template)
    monkeypatch.setattr(ops, "_venv_python", lambda: python)
    monkeypatch.setattr(ops, "_install_dependencies", AsyncMock(return_value=""))
    result = await ops.setup(SimpleNamespace(name="setup"))
    assert result.status == "ok" and result.payload["installed"]
    assert template.read_text(encoding="utf8") == original


def test_paths_resolve_after_json_parsing(tmp_path):
    from lamtools_core.mcp.config import load_mcp_server_configs
    config = tmp_path / "plugin" / "mcp" / "mcp.json"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({"mcpServers": {"bilibili": {
        "command": "{{PLUGIN_PYTHON}}", "args": ["{{PLUGIN_DIR}}/server/bili_server.py"], "transport": "json_lines"}}}), encoding="utf8")
    configs = load_mcp_server_configs(tmp_path, config_files=[config], default_paths=[])
    item = next(c for c in configs if c.name == "bilibili")
    assert "{{" not in item.command
    assert str(config.parent.parent) in item.command
    assert item.transport == "json_lines"


@pytest.mark.asyncio
async def test_mcp_server_preserves_parameter_schema(monkeypatch):
    pytest.importorskip("mcp")
    server = load("review_bili_server", ROOT / "server/bili_server.py", monkeypatch)
    tools = {tool.name: tool for tool in await server.mcp.list_tools()}
    assert "keyword" in tools["search"].inputSchema["properties"]
    assert tools["brief"].inputSchema.get("required", []) == []


@pytest.mark.asyncio
async def test_actual_fastmcp_process_accepts_command(tmp_path):
    pytest.importorskip("mcp")
    from lamtools_core.mcp import MCPToolRegistry
    from lamtools_core.mcp.command_service import MCPCommandService
    config = tmp_path / "fastmcp.json"
    config.write_text(json.dumps({"mcpServers": {"bilibili": {
        "command": sys.executable, "args": [str(ROOT / "server/bili_server.py")],
        "transport": "json_lines", "timeout": 5}}}), encoding="utf8")
    service = MCPCommandService(MCPToolRegistry(tmp_path, config_files=[config]))
    try:
        result = await service.execute_command("core mcp call --tool mcp__bilibili__brief --arguments '{}'")
        assert "keywords" in json.loads(result)
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_transcribe_downloads_audio_and_returns_text(tmp_path, monkeypatch):
    import httpx
    module = load("review_transcribe", ROOT / "server/transcribe.py", monkeypatch)
    monkeypatch.setattr(module, "_check", lambda: [])
    monkeypatch.setattr(module, "_audio_url", AsyncMock(return_value=("https://audio.example/a", 1)))
    monkeypatch.setattr(module.bili_core, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(module.bili_core, "_cookies", lambda: {})
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"audio")), **kwargs))
    async def create(*args, **kwargs):
        assert (tmp_path / "transcripts/BV12345678.m4a").read_bytes() == b"audio"
        (tmp_path / "transcripts/BV12345678.txt").write_text("transcribed", encoding="utf8")
        return SimpleNamespace(communicate=AsyncMock(return_value=(b"", None)), returncode=0)
    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", create)
    result = json.loads(await module.run_transcribe("BV12345678"))
    assert result["transcript"] == "transcribed"
    assert not (tmp_path / "transcripts/BV12345678.m4a").exists()
