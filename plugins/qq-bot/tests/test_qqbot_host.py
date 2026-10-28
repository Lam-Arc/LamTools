"""Host integration: manifest declarations, assembly, operations and tools."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from lamtools_core.app.base_agent import assemble_core_agent_plugins
from lamtools_core.plugin_system import PluginContext, load_manifest, read_capabilities, read_ui
from lamtools_core.tool import ToolCall

PLUGIN_ROOT = Path(__file__).resolve().parent.parent


def _isolated_plugin_root(tmp_path: Path) -> Path:
    root = tmp_path / "plugins"
    shutil.copytree(
        PLUGIN_ROOT,
        root / "qq-bot",
        ignore=shutil.ignore_patterns("tests", "__pycache__", "*.pyc"),
    )
    return root


def test_manifest_declarations() -> None:
    manifest = load_manifest(PLUGIN_ROOT / "plugin.json")
    assert manifest.name == "qq-bot"
    assert manifest.raw["backend"] == "./backend/__init__.py"
    presets = manifest.raw["agentPresets"]
    assert {item["id"] for item in presets} == {"qq-default", "qq-readonly", "qq-careful"}

    capabilities = read_capabilities(manifest)
    tool_names = {spec.name for spec in capabilities.tools}
    assert {"qqbot_send_file", "qqbot_status", "qqbot_bind_start"} <= tool_names
    from qqbot.util import jsonc_loads

    operation_names = {
        item["name"]
        for item in jsonc_loads((PLUGIN_ROOT / "operations.jsonc").read_text(encoding="utf-8"))["operations"]
    }
    assert "qqbot.status" in operation_names
    assert "qqbot.bind.manual" in operation_names

    ui = read_ui(manifest)
    pages = {page.id: page for page in ui.pages}
    assert pages["qq-bot"].navigation is True
    assert pages["qq-bot-bind"].navigation is False
    assert ui.windows[0].id == "qq-bot-bind"
    assert ui.regions[0].region == "right"


async def test_host_assembly_exposes_tools_presets_and_waterfall(tmp_path: Path) -> None:
    plugin_root = _isolated_plugin_root(tmp_path)
    data_dir = tmp_path / "data"
    context = PluginContext(work_root=tmp_path, data_dir=data_dir)
    context.services["sub_agent_runner_factory"] = lambda: SimpleNamespace(parent_event_sink=None)

    assembly = assemble_core_agent_plugins(
        data_dir=data_dir,
        work_root=tmp_path,
        plugin_roots=[plugin_root],
        include_user_plugins=False,
        context=context,
    )

    names = {spec.name for spec in assembly["plugin_runtime_specs"]}
    assert {"qqbot_send_file", "qqbot_status", "qqbot_bind_start"} <= names
    handlers = {spec.name: (spec.metadata or {}).get("handler") for spec in assembly["plugin_runtime_specs"]}
    assert handlers["qqbot_status"] == "tools:status"
    assert handlers["qqbot_send_file"] == "tools:send_file"

    presets = context.services.get("agent_presets")
    assert presets is not None
    assert presets.has("qq-readonly")
    readonly = presets.resolve("qq-readonly")
    assert "read_file" in readonly.tools
    assert readonly.mode == "low"

    assert context.services.get("system_prompt_waterfall") is not None


async def test_operations_use_the_running_runtime(tmp_path: Path) -> None:
    from qqbot import state as qqstate
    import ops

    class FakeRuntime:
        data_dir = tmp_path
        work_root = tmp_path
        config = {"appId": "app"}

        def status(self):
            return {"ok": True, "bound": False, "gateway": "unbound"}

        def bind_state(self):
            return {"phase": "starting"}

        def config_get(self):
            return {"ok": True, "config": {"appId": "app"}}

        async def config_update(self, patch):
            return {"ok": True, "patch": patch}

        def logs_tail(self, tail):
            return {"ok": True, "lines": ["line"]}

    fake = FakeRuntime()
    qqstate.set_runtime(fake)
    try:
        status = await ops.status(None)
        assert status.status == "ok"
        assert status.payload["gateway"] == "unbound"
        state = await ops.bind_state(None)
        assert state.payload["phase"] == "starting"
        updated = await ops.config_update(SimpleNamespace(payload={"patch": {"debug": True}}))
        assert updated.payload["patch"] == {"debug": True}
        logs = await ops.logs_tail(SimpleNamespace(payload={"tail": 5}))
        assert logs.payload["lines"] == ["line"]
    finally:
        qqstate.set_runtime(None)


async def test_tool_status_and_send_file(tmp_path: Path) -> None:
    from qqbot import state as qqstate
    from qqbot.agent_bridge import PeerSession, _current_session
    from qqbot.config import normalize
    from qqbot.protocol import ReplyTarget
    import tools

    media_dir = tmp_path / "media"
    media_dir.mkdir()
    file_path = tmp_path / "report.txt"
    file_path.write_text("hello", encoding="utf-8")

    class FakeApi:
        async def send_media(self, target, file_type, *, data=None, local_path=None, file_name=""):
            return {"upload": {"file_uuid": "uuid-1"}, "message": {"id": "msg-1"}}

    class FakeBridge:
        def all_sessions(self):
            return []

    runtime = SimpleNamespace(
        data_dir=tmp_path,
        work_root=tmp_path,
        config=normalize({"appId": "app"}),
        logger=logging.getLogger("test"),
        _api=FakeApi(),
        _bridge=FakeBridge(),
        context=SimpleNamespace(llm_client=None),
    )
    runtime.status = lambda: {"ok": True, "bound": True}
    qqstate.set_runtime(runtime)
    session = PeerSession(
        key="qqbot:app:c2c:u",
        scope="c2c",
        peer_id="u",
        sender_id="u",
        agent_name="qq_u",
        reply_target=ReplyTarget("c2c", "u", "m"),
    )
    token = _current_session.set(session)
    try:
        status = await tools.status(ToolCall(id="1", name="qqbot_status", arguments={}))
        assert status.status == "ok"
        assert "bound" in status.content

        result = await tools.send_file(
            ToolCall(id="2", name="qqbot_send_file", arguments={"file_path": str(file_path)})
        )
        assert result.status == "ok"
        assert "uuid-1" in result.content
    finally:
        _current_session.reset(token)
        qqstate.set_runtime(None)


async def test_describe_image_falls_back_to_main_model(tmp_path: Path) -> None:
    from qqbot import state as qqstate
    from qqbot.config import normalize
    import tools

    image = tmp_path / "pixel.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    runtime = SimpleNamespace(
        data_dir=tmp_path,
        work_root=tmp_path,
        config=normalize({"appId": "app"}),
        logger=logging.getLogger("test"),
        context=SimpleNamespace(llm_client=None),
    )
    qqstate.set_runtime(runtime)
    try:
        result = await tools.describe_image(
            ToolCall(id="3", name="qqbot_describe_image", arguments={"image": str(image)})
        )
        assert result.status == "ok"
        assert result.model_image_data_url.startswith("data:image/png;base64,")
    finally:
        qqstate.set_runtime(None)
