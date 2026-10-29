"""user:“宿主能力补齐和接口完善与文档更新”+(提示词贡献进入真实组装链，按启动代撤回，错误不污染内置提示词)。"""

from __future__ import annotations

import pytest

from lamtools_core.plugin_system.context import PluginContext
from lamtools_core.plugin_system.lifecycle import PluginRuntimeHandle, start_plugin_backend, stop_plugin_backend
from lamtools_core.plugin_system.manifest import PluginManifest
from lamtools_core.plugin_system.prompt_waterfall import PromptAssembly, PromptContext, PromptSection, SystemPromptWaterfall


@pytest.fixture
async def env(tmp_path):
    root = PluginContext(tmp_path)
    waterfall = SystemPromptWaterfall()
    root.set_service("system_prompt_waterfall", waterfall)
    handles = []
    async def start(callback, name="example"):
        handle = PluginRuntimeHandle(PluginManifest(name, "1", root=tmp_path), {"start": callback}, context=root.for_work_root(tmp_path))
        handles.append(handle)
        await start_plugin_backend(handle, root)
        return handle
    try:
        yield root, waterfall, start
    finally:
        for handle in reversed(handles):
            await stop_plugin_backend(handle)


def assemble(waterfall, session="s", agent="a"):
    return waterfall.assemble(PromptContext(session_id=session, agent_id=agent),
                              PromptAssembly(text="BASE", sections=[PromptSection("base", 0, "BASE")]))


@pytest.mark.asyncio
async def test_sections_stage_until_start_success_and_revoke_on_stop(env):
    root, waterfall, start = env
    def initialize(ctx):
        ctx.prompts.section("facts", "PLUGIN")
        assert assemble(waterfall).text == "BASE"
    handle = await start(initialize)
    assert assemble(waterfall).text == "BASE\n\nPLUGIN"
    await stop_plugin_backend(handle)
    assert assemble(waterfall).text == "BASE"


@pytest.mark.asyncio
async def test_failed_start_does_not_leave_prompt_contribution(env):
    _, waterfall, start = env
    def initialize(ctx):
        ctx.prompts.section("facts", "LEAK")
        raise RuntimeError("startup failed")
    with pytest.raises(RuntimeError, match="startup failed"):
        await start(initialize)
    assert assemble(waterfall).text == "BASE"


@pytest.mark.asyncio
async def test_old_facade_and_disposer_cannot_change_restarted_plugin(env):
    root, waterfall, start = env
    views, removers = [], []
    def initialize(ctx):
        views.append(ctx.prompts)
        removers.append(ctx.prompts.section("facts", "CURRENT"))
    handle = await start(initialize)
    await stop_plugin_backend(handle)
    await start_plugin_backend(handle, root)
    removers[0]()
    with pytest.raises(RuntimeError):
        views[0].section("stale", "WRONG")
    assert assemble(waterfall).text.endswith("CURRENT")


@pytest.mark.asyncio
async def test_scoped_sections_shadow_global_for_one_session_and_agent(env):
    _, waterfall, start = env
    def initialize(ctx):
        ctx.prompts.section("facts", "GLOBAL")
        ctx.prompts.section("facts", "AGENT", agent_id="a")
        ctx.prompts.section("facts", "SESSION", session_id="s")
        ctx.prompts.section("facts", "BOTH", session_id="s", agent_id="a")
    await start(initialize)
    assert assemble(waterfall).text == "BASE\n\nBOTH"
    assert assemble(waterfall, "other", "a").text == "BASE\n\nAGENT"
    assert assemble(waterfall, "s", "other").text == "BASE\n\nSESSION"
    assert assemble(waterfall, "other", "other").text == "BASE\n\nGLOBAL"


@pytest.mark.asyncio
async def test_sections_sort_by_order_then_name_and_do_not_reorder_builtin(env):
    _, waterfall, start = env
    def initialize(ctx):
        ctx.prompts.section("z", "LAST", order=20)
        ctx.prompts.section("b", "SECOND", order=-10.5)
        ctx.prompts.section("a", "FIRST", order=-10.5)
    await start(initialize)
    result = assemble(waterfall)
    assert result.text == "BASE\n\nFIRST\n\nSECOND\n\nLAST"
    assert [section.name for section in result.sections] == ["base", "example:a", "example:b", "example:z"]
    assert result.sections[1].order == -10.5


@pytest.mark.asyncio
async def test_variable_is_resolved_per_assembly_scoped_and_literal_text_is_preserved(env):
    _, waterfall, start = env
    value = ["one"]
    def initialize(ctx):
        ctx.prompts.variable("fact", lambda c: value[0])
        ctx.prompts.variable("fact", lambda c: c.session_id, session_id="s")
        ctx.prompts.section("dynamic", lambda c: "fact={{fact}}")
        ctx.prompts.section("literal", "{{missing}}", interpolate=False)
    await start(initialize)
    assert assemble(waterfall).text == "BASE\n\nfact=s\n\n{{missing}}"
    assert "fact=one" in assemble(waterfall, "other").text
    value[0] = "two"
    assert "fact=two" in assemble(waterfall, "other").text


@pytest.mark.asyncio
async def test_cross_plugin_variable_conflict_is_explicit_and_section_names_are_owned(env):
    _, waterfall, start = env
    await start(lambda ctx: (ctx.prompts.variable("fact", lambda c: "A"), ctx.prompts.section("same", "A")), "one")
    def initialize(ctx):
        ctx.prompts.section("same", "B")
        with pytest.raises(ValueError, match="conflict"):
            ctx.prompts.variable("fact", lambda c: "B")
    await start(initialize, "two")
    assert {s.name for s in assemble(waterfall).sections} >= {"one:same", "two:same"}


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["{{unknown}}", "{{ fact }}", "{{{broken}}", "{{}}"])
async def test_unresolved_or_malformed_variables_fail_without_partial_mutation(env, text):
    _, waterfall, start = env
    await start(lambda ctx: ctx.prompts.section("invalid", text))
    original = PromptAssembly(text="BASE", sections=[PromptSection("base", 0, "BASE")])
    with pytest.raises((ValueError, RuntimeError), match="variable"):
        waterfall.assemble(PromptContext(), original)
    assert original.text == "BASE" and len(original.sections) == 1


@pytest.mark.asyncio
async def test_assembly_hook_is_scoped_and_cannot_mutate_runtime_metadata(env):
    _, waterfall, start = env
    def transform(context, assembly):
        context.metadata["nested"]["value"] = "changed"
        assembly.append_section("owned-hook", "HOOK")
    await start(lambda ctx: ctx.prompts.on_assemble(transform, session_id="chosen"))
    metadata = {"nested": {"value": "original"}}
    context = PromptContext(session_id="chosen", metadata=metadata)
    assert waterfall.assemble(context, PromptAssembly(text="BASE")).text.endswith("HOOK")
    assert metadata == {"nested": {"value": "original"}}
    assert assemble(waterfall).text == "BASE"


@pytest.mark.asyncio
async def test_callback_failure_rolls_back_legacy_and_owned_mutations(env):
    _, waterfall, start = env
    def broken(context, assembly):
        assembly.append_section("leak", "LEAK")
        raise ValueError("broken")
    waterfall.register(lambda c, a: a.append_section("legacy", "LEGACY"))
    await start(lambda ctx: ctx.prompts.on_assemble(broken))
    original = PromptAssembly(text="BASE", sections=[])
    with pytest.raises(RuntimeError, match="broken"):
        waterfall.assemble(PromptContext(), original)
    assert original.text == "BASE" and original.sections == []


@pytest.mark.asyncio
async def test_async_and_invalid_providers_are_rejected_and_cleanup_is_idempotent(env):
    root, waterfall, start = env
    with pytest.raises(RuntimeError):
        root.prompts.section("bad", "BAD")
    removers = []
    def initialize(ctx):
        async def bad(c):
            return "ASYNC"
        with pytest.raises(TypeError, match="synchronous"):
            ctx.prompts.variable("bad", bad)
        with pytest.raises(ValueError):
            ctx.prompts.section("bad", "TEXT", order=float("nan"))
        removers.append(ctx.prompts.section("ok", "OK"))
    await start(initialize)
    removers[0]()
    removers[0]()
    assert assemble(waterfall).text == "BASE"


@pytest.mark.asyncio
async def test_real_agent_prompt_keeps_builtin_on_plugin_failure(env, tmp_path, monkeypatch, caplog):
    from .test_agent_presets_prompt_waterfall import _kit
    from lamtools_core.runtime import RuntimeState
    _, waterfall, start = env
    def broken(c, a):
        a.text = "LEAK"
        a.sections.clear()
        raise ValueError("broken prompt")
    await start(lambda ctx: ctx.prompts.on_assemble(broken))
    monkeypatch.setattr("lamtools_core.app.base_agent.command_shell_prompt", lambda: "[Shell]")
    kit = _kit(tmp_path, waterfall)
    text, blocks = kit._compose_system_prompt(RuntimeState(session_id="s"), study_mode=False, effective_instructions="BASE INSTRUCTIONS")
    assert "BASE INSTRUCTIONS" in text and "LEAK" not in text and blocks
    assert "broken prompt" in caplog.text


@pytest.mark.asyncio
async def test_bad_assembly_fields_fail_inside_fallback_boundary(env, tmp_path, monkeypatch, caplog):
    from .test_agent_presets_prompt_waterfall import _kit
    from lamtools_core.runtime import RuntimeState
    _, waterfall, start = env
    def broken(c, a):
        a.sections = None
    await start(lambda ctx: ctx.prompts.on_assemble(broken))
    monkeypatch.setattr("lamtools_core.app.base_agent.command_shell_prompt", lambda: "[Shell]")
    text, blocks = _kit(tmp_path, waterfall)._compose_system_prompt(RuntimeState(session_id="s"), study_mode=False, effective_instructions="BASE")
    assert "BASE" in text and blocks and "system prompt waterfall failed" in caplog.text


@pytest.mark.asyncio
async def test_returned_assembly_is_detached_from_plugin_retained_object(env):
    _, waterfall, start = env
    retained = PromptAssembly("SHARED", [PromptSection("shared", 0, "SHARED")])
    await start(lambda ctx: ctx.prompts.on_assemble(lambda c, a: retained))
    result = assemble(waterfall)
    retained.text = "CHANGED LATER"
    retained.sections.clear()
    assert result.text == "SHARED" and len(result.sections) == 1


@pytest.mark.asyncio
async def test_unregister_scoped_override_restores_default_and_missing_variable_is_explicit(env):
    _, waterfall, start = env
    removers = []
    def initialize(ctx):
        ctx.prompts.variable("fact", lambda c: "DEFAULT")
        removers.append(ctx.prompts.variable("fact", lambda c: None, session_id="s"))
        ctx.prompts.section("fact", "{{fact}}; unmatched {{prose")
    await start(initialize)
    with pytest.raises(ValueError, match="variable"):
        assemble(waterfall)
    removers[0]()
    assert assemble(waterfall).text == "BASE\n\nDEFAULT; unmatched {{prose"


def test_desktop_boot_and_child_model_request_use_managed_prompt_contributions(tmp_path, monkeypatch):
    import json
    from functools import partial
    from fastapi.testclient import TestClient
    from .test_agent_presets_prompt_waterfall import _kit, _ScriptedLLM
    from lamtools_core.app.http_agent_app import create_core_agent_http_app
    from lamtools_core.runtime import RuntimeState, InMemoryRuntimeStateStore
    from lamtools_core.tool.sub_agent_runner import KernelSubAgentRunner
    monkeypatch.setattr("lamtools_core.app.http_agent_app.warm_command_shell", lambda: None)
    monkeypatch.setattr("lamtools_core.runtime.power.apply_keep_awake", lambda: None)
    monkeypatch.setattr("lamtools_core.app.base_agent.command_shell_prompt", lambda: "[Shell]")
    plugin_root = tmp_path / "plugins" / "prompt-consumer"
    plugin_root.mkdir(parents=True)
    (plugin_root / "plugin.json").write_text(json.dumps({"name": "prompt-consumer", "version": "1", "backend": "./backend.py"}))
    (plugin_root / "backend.py").write_text('''
class Runtime:
    def start(self, context):
        self.context = context
        context.prompts.variable("language", lambda c: "Chinese")
        context.prompts.section("language", "REPLY IN {{language}}")
def create_plugin(context):
    return Runtime()
''')
    app = create_core_agent_http_app(core_db=tmp_path / "boot.db", data_dir=tmp_path / "data",
                                     work_root=tmp_path / "project", plugin_roots=[tmp_path / "plugins"])
    with TestClient(app) as client:
        handle = next(h for h in app.state.core_agent_app_state["plugin_runtimes"] if h.plugin.name == "prompt-consumer")
        assert handle.state == "ready", handle.error
        waterfall = handle.value.context.service("system_prompt_waterfall")
        kit = _kit(tmp_path, waterfall)
        text, blocks = kit._compose_system_prompt(RuntimeState(session_id="main"), study_mode=False, effective_instructions="MAIN BASE")
        assert "REPLY IN Chinese" in text and any(b.key == "prompt-consumer:language" for b in blocks)
        llm = _ScriptedLLM()
        runner = KernelSubAgentRunner(work_root=tmp_path / "project", llm_client=llm, model_id="test", instructions="CHILD BASE",
            loaded_skill_roots=(), prompt_waterfall=waterfall, state_store=InMemoryRuntimeStateStore())
        result = client.portal.call(partial(runner.run, task="Reply done", agent="example"))
        assert result.decision == "done" and llm.requests
        assert "REPLY IN Chinese" in str(llm.requests[0].messages[0].content)
        client.portal.call(stop_plugin_backend, handle)
        text, _ = kit._compose_system_prompt(RuntimeState(session_id="main"), study_mode=False, effective_instructions="MAIN BASE")
        assert "REPLY IN Chinese" not in text


def test_legacy_transform_remains_usable_and_result_is_transactional():
    waterfall = SystemPromptWaterfall()
    def transform(c, a):
        assert a.replace_section("base", "REPLACED")
        a.append_section("legacy", "LEGACY")
        return a
    remove = waterfall.register(transform, plugin="old-plugin")
    original = PromptAssembly("BASE", [PromptSection("base", 0, "BASE")])
    result = waterfall.assemble(PromptContext(), original)
    assert result.text == "REPLACED\n\nLEGACY" and original.text == "BASE"
    remove()
    assert waterfall.assemble(PromptContext(), original).text == "BASE"
