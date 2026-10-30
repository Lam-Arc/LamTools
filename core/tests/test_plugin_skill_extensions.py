"""user:“宿主能力补齐和接口完善与文档更新”+(内存技能进入原发现、按需加载与用户选择路径，停用撤回且不扩大文件访问)。"""

from __future__ import annotations

from functools import partial

import pytest

from lamtools_core.plugin_system.context import PluginContext
from lamtools_core.plugin_system.lifecycle import PluginRuntimeHandle, start_plugin_backend, stop_plugin_backend
from lamtools_core.plugin_system.manifest import PluginManifest
from lamtools_core.plugin_system.skill_extensions import ensure_skill_extensions
from lamtools_core.skills import SkillRegistry, SkillStateStore
from lamtools_core.tool import ToolCall
from lamtools_core.tool.default_toolbox import CoreToolbox
from lamtools_core.composer_commands import build_composer_command_catalog, prepare_composer_input


@pytest.fixture
async def env(tmp_path):
    root = PluginContext(tmp_path)
    host = ensure_skill_extensions(root)
    handles = []
    async def start(callback, name="example"):
        handle = PluginRuntimeHandle(PluginManifest(name, "1", root=tmp_path), {"start": callback}, context=root.for_work_root(tmp_path))
        handles.append(handle)
        await start_plugin_backend(handle, root)
        return handle
    try:
        yield root, host, start
    finally:
        for handle in reversed(handles):
            await stop_plugin_backend(handle)


def registry(host, **kwargs):
    return SkillRegistry(explicit_roots=(), runtime_skills=host.snapshot, **kwargs)


def box(tmp_path, reg, state=None):
    return CoreToolbox(work_root=tmp_path, loaded_skill_roots=set(), skill_registry=reg, skill_state_store=state)


async def load(toolbox, name="inline-demo"):
    return await toolbox.execute(ToolCall("load", "load_skill", {"name": name}))


@pytest.mark.asyncio
async def test_registration_is_staged_then_old_registry_observes_stop_and_restart(env):
    root, host, start = env
    reg = registry(host)
    def initialize(ctx):
        ctx.skills.register("inline-demo", "Use for testing", "INLINE BODY")
        assert "inline-demo" not in reg.prompt_index(root.work_root)
    handle = await start(initialize)
    assert "inline-demo" in reg.prompt_index(root.work_root)
    await stop_plugin_backend(handle)
    assert "inline-demo" not in reg.prompt_index(root.work_root)
    await start_plugin_backend(handle, root)
    assert "INLINE BODY" in reg.load_prompt_content(root.work_root, "inline-demo")


@pytest.mark.asyncio
async def test_failed_start_and_stale_facade_cannot_leak_skills(env):
    root, host, start = env
    views = []
    def initialize(ctx):
        views.append(ctx.skills)
        ctx.skills.register("inline-demo", "Test", "BODY")
        raise RuntimeError("startup failed")
    with pytest.raises(RuntimeError):
        await start(initialize)
    assert host.snapshot() == []
    with pytest.raises(RuntimeError):
        views[0].register("later", "Test", "BODY")
    with pytest.raises(RuntimeError):
        root.skills.register("outside", "Test", "BODY")


@pytest.mark.asyncio
async def test_duplicate_names_are_rejected_and_old_disposer_cannot_remove_new(env):
    _, host, start = env
    views, removers = [], []
    def initialize(ctx):
        views.append(ctx.skills)
        removers.append(ctx.skills.register("inline-demo", "Test", "OLD"))
        with pytest.raises(ValueError, match="conflict"):
            ctx.skills.register("inline-demo", "Test", "DUPLICATE")
    await start(initialize)
    def other(ctx):
        with pytest.raises(ValueError, match="conflict"):
            ctx.skills.register("inline-demo", "Test", "OTHER")
    await start(other, "other")
    removers[0]()
    views[0].register("inline-demo", "Test", "NEW")
    removers[0]()
    assert host.snapshot()[0].content == "NEW"


@pytest.mark.asyncio
@pytest.mark.parametrize("model,user", [(True, True), (True, False), (False, True), (False, False)])
async def test_model_and_user_policy_are_independent_at_discovery_and_load(env, tmp_path, model, user):
    _, host, start = env
    await start(lambda ctx: ctx.skills.register("inline-demo", "Test", "BODY", model_invocable=model, user_invocable=user))
    reg = registry(host)
    toolbox = box(tmp_path, reg)
    assert ("inline-demo" in toolbox.skill_index()) is model
    assert ((await load(toolbox)).status == "ok") is model
    if not model:
        assert "inline-demo" not in (await load(toolbox, "missing-skill")).content
    names = {c.name for c in build_composer_command_catalog(core_roots=[], member_roots=[], work_root=tmp_path, skill_registry=reg)}
    assert ("inline-demo" in names) is user
    if user:
        prepared = prepare_composer_input(work_root=tmp_path, skill_registry=reg, input_items=[{"type": "skill", "name": "inline-demo"}])
        assert "BODY" in prepared.runtime_text
    else:
        with pytest.raises(ValueError, match="user"):
            prepare_composer_input(work_root=tmp_path, skill_registry=reg, input_items=[{"type": "skill", "name": "inline-demo"}])
        with pytest.raises(ValueError) as missing:
            prepare_composer_input(work_root=tmp_path, skill_registry=reg, input_items=[{"type": "skill", "name": "missing-skill"}])
        assert "inline-demo" not in str(missing.value)


@pytest.mark.asyncio
async def test_inline_load_has_no_fake_file_location_and_adds_no_resource_roots(env, tmp_path):
    _, host, start = env
    handle = await start(lambda ctx: ctx.skills.register("inline-demo", "Test", "BODY"))
    toolbox = box(tmp_path, registry(host))
    before = set(toolbox.loaded_skill_roots)
    result = await load(toolbox)
    assert result.status == "ok" and "BODY" in result.content
    assert "Base directory" not in result.content and "Read files under" not in result.content
    assert toolbox.loaded_skill_roots == before
    assert registry(host).get(tmp_path, "inline-demo").location is None
    await stop_plugin_backend(handle)
    assert (await load(toolbox)).status == "failed"
    assert (await load(toolbox, " inline-demo ")).status == "failed"


@pytest.mark.asyncio
async def test_skill_disable_blocks_both_model_and_user_paths(env, tmp_path):
    _, host, start = env
    await start(lambda ctx: ctx.skills.register("inline-demo", "Test", "BODY"))
    state = SkillStateStore(tmp_path / "skill-state.json")
    state.set_enabled("inline-demo", False)
    reg = registry(host)
    toolbox = box(tmp_path, reg, state)
    assert "inline-demo" not in toolbox.skill_index()
    assert (await load(toolbox)).status == "failed"
    assert (await load(toolbox, " inline-demo ")).status == "failed"
    with pytest.raises(ValueError, match="disabled"):
        prepare_composer_input(work_root=tmp_path, skill_registry=reg, skill_state_store=state,
                               input_items=[{"type": "skill", "name": "inline-demo"}])


@pytest.mark.asyncio
async def test_filesystem_precedence_and_content_truncation_are_preserved(env, tmp_path):
    _, host, start = env
    folder = tmp_path / ".lam" / "skills" / "inline-demo"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text("---\nname: inline-demo\ndescription: Disk\n---\nDISK BODY")
    await start(lambda ctx: ctx.skills.register("inline-demo", "Inline", "INLINE BODY"))
    reg = registry(host, max_content_chars=4)
    assert reg.get(tmp_path, "inline-demo").location == folder / "SKILL.md"
    assert "DISK" in reg.load_prompt_content(tmp_path, "inline-demo")
    (folder / "SKILL.md").unlink()
    assert reg.get(tmp_path, "inline-demo").location is None
    content = reg.load_prompt_content(tmp_path, "inline-demo")
    assert "INLI" in content and "INLINE BODY" not in content and "Read files under" not in content


@pytest.mark.asyncio
async def test_runtime_skills_do_not_leak_between_hosts(env, tmp_path):
    _, host, start = env
    await start(lambda ctx: ctx.skills.register("inline-demo", "Test", "PRIVATE BODY"))
    other_host = ensure_skill_extensions(PluginContext(tmp_path))
    assert "inline-demo" in registry(host).prompt_index(tmp_path)
    assert "inline-demo" not in registry(other_host).prompt_index(tmp_path)


@pytest.mark.asyncio
@pytest.mark.parametrize("name,description,content", [("../escape", "Test", "BODY"), ("UPPER", "Test", "BODY"), ("valid", "", "BODY"), ("valid", "Test", "")])
async def test_invalid_embedded_definitions_are_rejected(env, name, description, content):
    _, host, start = env
    def initialize(ctx):
        with pytest.raises((ValueError, TypeError)):
            ctx.skills.register(name, description, content)
    await start(initialize)
    assert not host.snapshot()


def test_desktop_skill_list_main_child_and_live_user_input_share_runtime_contributions(tmp_path, monkeypatch):
    import json
    from fastapi.testclient import TestClient
    from lamtools_core.app.http_agent_app import create_core_agent_http_app
    from lamtools_core.app.default_agent import _build_core_runtime_toolbox, _close_mcp_registry
    monkeypatch.setattr("lamtools_core.app.http_agent_app.warm_command_shell", lambda: None)
    monkeypatch.setattr("lamtools_core.runtime.power.apply_keep_awake", lambda: None)
    plugin_root = tmp_path / "plugins" / "skill-consumer"
    plugin_root.mkdir(parents=True)
    (plugin_root / "plugin.json").write_text(json.dumps({"name": "skill-consumer", "version": "1", "backend": "./backend.py"}))
    (plugin_root / "backend.py").write_text('''
class Runtime:
    def start(self, context):
        self.context = context
        context.skills.register("test-embedded-skill", "Use in acceptance", "EMBEDDED INSTRUCTIONS")
def create_plugin(context):
    return Runtime()
''')
    app = create_core_agent_http_app(core_db=tmp_path / "boot.db", data_dir=tmp_path / "data",
                                     work_root=tmp_path / "project", plugin_roots=[tmp_path / "plugins"])
    with TestClient(app) as client:
        state = app.state.core_agent_app_state
        handle = next(h for h in state["plugin_runtimes"] if h.plugin.name == "skill-consumer")
        assert handle.state == "ready", handle.error
        operations = state["operations"]
        listed = client.portal.call(operations.execute, "skill.list", {})
        item = next(s for s in listed.payload["skills"] if s["name"] == "test-embedded-skill")
        assert item["location"] == "" and item["source"] == "plugin" and item["deletable"] is False
        deleted = client.portal.call(operations.execute, "skill.delete", {"name": "test-embedded-skill"})
        assert deleted.status == "error"
        toolbox, mcp = client.portal.call(partial(_build_core_runtime_toolbox, work_root=tmp_path / "project",
            plugin_assembly={"plugin_context": handle.value.context, "data_dir": str(tmp_path / "data")}, approval_policy="require", llm_client=object()))
        child = toolbox.sub_agent_runner._build_toolbox(set(), active_mode=None)
        cloned_runner = client.portal.call(toolbox.sub_agent_runner.create_supervisor_runner)
        cloned = cloned_runner._build_toolbox(set(), active_mode=None)
        for actual in (toolbox, child, cloned):
            assert "test-embedded-skill" in actual.skill_index()
            assert "EMBEDDED INSTRUCTIONS" in client.portal.call(load, actual, "test-embedded-skill").content
        sessions = state["plugin_session_service"]
        async def prepare():
            ctx = sessions._context()
            return await ctx.host.member_hooks.prepare_turn_input(thread_id="s", params={"work_root": str(tmp_path / "project")},
                input_items=[{"type": "skill", "name": "test-embedded-skill"}])
        prepared = client.portal.call(prepare)
        assert "EMBEDDED INSTRUCTIONS" in str(prepared)
        assert client.portal.call(operations.execute, "skill.disable", {"name": "test-embedded-skill"}).status == "ok"
        for actual in (toolbox, child, cloned):
            assert "test-embedded-skill" not in actual.skill_index()
            assert client.portal.call(load, actual, "test-embedded-skill").status == "failed"
        with pytest.raises(ValueError, match="disabled"):
            client.portal.call(prepare)
        assert client.portal.call(operations.execute, "skill.enable", {"name": "test-embedded-skill"}).status == "ok"
        client.portal.call(stop_plugin_backend, handle)
        assert "test-embedded-skill" not in toolbox.skill_index()
        assert (client.portal.call(load, child, "test-embedded-skill")).status == "failed"
        client.portal.call(_close_mcp_registry, mcp)
