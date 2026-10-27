"""user:“都试一试”+(用一颗真实安装的探针插件验收六类能力、Agent、UI 和恢复边界)。"""
import json
from pathlib import Path
import pytest
from tests.test_plugin_host_rebuild import boot, plugin


@pytest.mark.asyncio
async def test_six_capabilities_share_the_same_enablement_gate(tmp_path):
    from lamtools_core.plugin_system.runtime import PluginSystemRuntime
    from lamtools_core.plugin_system.commands import composer_plugin_handles
    from lamtools_core.plugin_system.hooks import plugin_hook_definitions
    from lamtools_core.plugin_system.hook_engine import HookEngine
    from lamtools_core.plugin_system.hooks import HookEvent
    host, manager, catalog, folder = await boot(tmp_path)
    (folder / "skills/demo").mkdir(parents=True)
    (folder / "skills/demo/SKILL.md").write_text('---\nname: demo\ndescription: probe\n---\nProbe skill')
    (folder / "tools.json").write_text(json.dumps({"tools": [{"name": "probe", "handler": "ops:read", "description": "probe"}]}))
    (folder / "hooks.json").write_text(json.dumps({"hooks": {"PreToolUse": [{"matcher": "*", "hooks": [{"type": "prompt", "prompt": "probe hook context"}]}]}}))
    (folder / "mcp.json").write_text('{"mcpServers":{"probe":{"command":"python"}}}')
    (folder / "context.md").write_text("probe context")
    raw = json.loads((folder / "plugin.json").read_text())
    raw.update(tools=["./tools.json"], skills=["./skills"], hooks=["./hooks.json"], mcp=["./mcp.json"],
               commands=[{"name": "probe", "operation": "demo.read"}], context=[{"file": "./context.md"}])
    (folder / "plugin.json").write_text(json.dumps(raw))
    host._invalidate()
    artifacts = PluginSystemRuntime(host).assemble()
    assert not artifacts.errors
    assert all([artifacts.tools, artifacts.skills, artifacts.hooks, artifacts.mcp_files, artifacts.commands, artifacts.context])
    assert composer_plugin_handles(host)[0].commands[0].operation == "demo.read"
    definitions = plugin_hook_definitions(host.runtime_manifests())
    decision = await HookEngine(definitions).run(HookEvent(event_name="PreToolUse", tool_name="probe"))
    assert "probe hook context" in decision.additional_context
    await catalog.execute("plugin.system.disable", {"name": "demo"})
    assert PluginSystemRuntime(host).assemble().is_empty()
    assert composer_plugin_handles(host) == []


@pytest.mark.asyncio
async def test_mode_and_session_agents_resolve_without_crossing_scope(tmp_path):
    from lamtools_core.plugin_system.agent import assemble_agents, resolve_agent_plan
    from lamtools_core.plugin_system.manifest import load_manifest
    first = plugin(tmp_path / "mode", scope="mode", agent={"mode": "special", "approval": "ask"}, backend=False)
    session = tmp_path / "session"
    plugin(session, scope="session", agent={"approval": "block"}, backend=False)
    raw = json.loads((session / "plugin.json").read_text()); raw["name"] = "session-owner"
    (session / "plugin.json").write_text(json.dumps(raw))
    agents = assemble_agents([load_manifest(first / "plugin.json"), load_manifest(session / "plugin.json")]).agents
    assert resolve_agent_plan(agents) is None
    assert resolve_agent_plan(agents, active_mode="demo:special").agent.plugin == "demo"
    assert resolve_agent_plan(agents, session_plugin="session-owner").agent.plugin == "session-owner"


def test_kernel_override_rejected_consistently_by_boot_and_runtime(tmp_path):
    from lamtools_boot.overrides import load_boot_overrides
    from lamtools_core.plugin_system.overrides import assemble_overrides
    from lamtools_core.plugin_system.manifest import load_manifest
    folder = plugin(tmp_path / "plugins" / "demo", overrides={"lamtools_core.plugin_system.host": "./override.py"})
    (folder / "override.py").write_text("raise RuntimeError('must not load')")
    runtime = assemble_overrides([load_manifest(folder / "plugin.json")])
    assert not runtime.overrides and runtime.errors
    overrides, errors = load_boot_overrides(roots=[folder.parent], state_path=tmp_path / "state.json", environ={})
    assert not overrides and errors


def test_permitted_backend_and_frontend_module_replacements_work(tmp_path):
    import importlib, sys
    from lamtools_boot.overrides import load_boot_overrides
    from lamtools_boot.import_hook import install_overrides, remove_overrides
    from lamtools_core.plugin_system import PluginHost
    from lamtools_core.plugin_system.import_map import build_import_map, inject_import_map
    folder = plugin(tmp_path / "plugins" / "demo", backend=False, overrides={
        "lamtools_core.rebuild_probe": "./override.py", "@/helpers/rebuild-probe": "./entry.mjs"})
    (folder / "override.py").write_text("VALUE = 'replacement-loaded'\n")
    (folder / "entry.mjs").write_text("export const value = 'replacement-loaded';")
    replacements, errors = load_boot_overrides(roots=[folder.parent], state_path=tmp_path / "state.json", environ={})
    assert not errors
    finder = install_overrides(replacements)
    try:
        assert importlib.import_module("lamtools_core.rebuild_probe").VALUE == "replacement-loaded"
    finally:
        remove_overrides(finder); sys.modules.pop("lamtools_core.rebuild_probe", None)
    host = PluginHost(roots=[folder.parent], state_path=tmp_path / "state.json")
    mapping = build_import_map(host)
    assert mapping["@/helpers/rebuild-probe"].endswith("entry.mjs")
    html = inject_import_map('<head><script type="module" src="app.js"></script></head>', mapping)
    assert html.index('type="importmap"') < html.index('type="module"')
