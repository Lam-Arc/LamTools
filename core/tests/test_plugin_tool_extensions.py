"""user:“宿主能力补齐和接口完善与文档更新”+(动态工具必须经真实工具箱权限链，钩子与插件启动代际一起撤回)。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from lamtools_core.plugin_system.context import PluginContext
from lamtools_core.plugin_system.tool_extensions import ToolDecision, ToolPatch, ensure_tool_extensions
from lamtools_core.plugin_system.lifecycle import PluginRuntimeHandle, start_plugin_backend, stop_plugin_backend
from lamtools_core.plugin_system.manifest import PluginManifest
from lamtools_core.tool import ToolSpec, ToolCall, ToolContext, ToolResult
from lamtools_core.tool.default_toolbox import CoreToolbox


def spec(name="demo_echo", permission="auto_allow"):
    return ToolSpec(name, "Echo", {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"], "additionalProperties": False}, permission=permission,
                    metadata={"operation_level": 1 if permission == "auto_allow" else 3})


def plugin(root, name, start):
    return PluginRuntimeHandle(PluginManifest(name, "1", root=root.work_root), {"start": start}, context=root.for_work_root(root.work_root))


def toolbox(tmp_path, host):
    return CoreToolbox(work_root=tmp_path, loaded_skill_roots=set(), plugin_tool_providers=[host.provider], permission_preset="ask")


def call(name="demo_echo", text="hello", **metadata):
    return ToolCall("call", name, {"text": text}, metadata=metadata)


@pytest.fixture
async def env(tmp_path):
    root = PluginContext(tmp_path)
    host = ensure_tool_extensions(root, reserved_names={"read_file"})
    handles = []
    async def start(callback, name="provider"):
        handle = plugin(root, name, callback)
        handles.append(handle)
        await start_plugin_backend(handle, root)
        return handle
    try:
        yield root, host, start
    finally:
        for handle in reversed(handles):
            await stop_plugin_backend(handle)


@pytest.mark.asyncio
async def test_registration_is_staged_then_model_visible_and_executable(env, tmp_path):
    root, host, start = env
    box = toolbox(tmp_path, host)
    async def initialize(ctx):
        ctx.tools.register(spec(), lambda invocation: ToolResult(invocation.call_id, invocation.name, content=invocation.arguments["text"]))
        assert "demo_echo" not in {s.name for s in box.tool_specs()}
    await start(initialize)
    assert "demo_echo" in {s.name for s in box.tool_specs()}
    result = await box.execute(call(), ToolContext(session_id="s"))
    assert result.content == "hello", result.to_dict()


@pytest.mark.asyncio
async def test_startup_failure_never_exposes_tools(env, tmp_path):
    root, host, start = env
    def initialize(ctx):
        ctx.tools.register(spec(), lambda i: ToolResult(i.call_id, i.name))
        raise RuntimeError("startup failed")
    with pytest.raises(RuntimeError):
        await start(initialize)
    assert "demo_echo" not in {s.name for s in toolbox(tmp_path, host).tool_specs()}


@pytest.mark.asyncio
async def test_duplicate_and_core_tool_names_are_rejected(env):
    _, _, start = env
    def initialize(ctx):
        ctx.tools.register(spec(), lambda i: ToolResult(i.call_id, i.name))
        with pytest.raises(ValueError, match="conflict"):
            ctx.tools.register(spec(), lambda i: ToolResult(i.call_id, i.name))
        with pytest.raises(ValueError, match="reserved"):
            ctx.tools.register(spec("read_file"), lambda i: ToolResult(i.call_id, i.name))
    await start(initialize)


@pytest.mark.asyncio
async def test_scope_required_and_old_facade_cannot_register_after_stop(env):
    root, _, start = env
    with pytest.raises(RuntimeError):
        root.tools.register(spec(), lambda i: None)
    views = []
    handle = await start(lambda ctx: views.append(ctx.tools))
    await stop_plugin_backend(handle)
    with pytest.raises(RuntimeError):
        views[0].register(spec(), lambda i: None)


@pytest.mark.asyncio
async def test_stop_hides_tool_and_invalidates_prepared_call_across_restart(env, tmp_path):
    root, host, start = env
    contexts = []
    def initialize(ctx):
        contexts.append(ctx)
        ctx.tools.register(spec(), lambda i: ToolResult(i.call_id, i.name, content="new"))
    handle = await start(initialize)
    box = toolbox(tmp_path, host)
    prepared = box.prepare_call(call())
    await stop_plugin_backend(handle)
    assert "demo_echo" not in {s.name for s in box.tool_specs()}
    assert (await box.execute(prepared)).status == "blocked"
    await start_plugin_backend(handle, root)
    assert (await box.execute(prepared)).status == "blocked"
    assert (await box.execute(call())).content == "new"


@pytest.mark.asyncio
async def test_ask_user_and_hard_block_follow_existing_approval_gate(env, tmp_path):
    _, host, start = env
    ran = []
    def initialize(ctx):
        ctx.tools.register(spec("demo_ask", "ask_user"), lambda i: ran.append(i.name) or ToolResult(i.call_id, i.name))
        ctx.tools.register(spec("demo_block", "hard_block"), lambda i: ran.append(i.name) or ToolResult(i.call_id, i.name))
    await start(initialize)
    box = toolbox(tmp_path, host)
    prepared = box.prepare_call(call("demo_ask"))
    assert prepared.requires_approval
    assert (await box.execute(prepared)).status == "blocked" and ran == []
    approved = box.prepare_approved_call(prepared)
    assert (await box.execute(approved)).status == "ok" and ran == ["demo_ask"]
    assert (await box.execute(box.prepare_approved_call(call("demo_block")))).status == "blocked"
    assert ran == ["demo_ask"]


@pytest.mark.asyncio
async def test_same_name_stricter_permission_cannot_inherit_previous_auto_allow(env, tmp_path):
    _, host, start = env
    controls = []
    def initialize(ctx):
        controls.append((ctx.tools, ctx.tools.register(spec(), lambda i: ToolResult(i.call_id, i.name))))
    await start(initialize)
    box = toolbox(tmp_path, host)
    assert not box.prepare_call(call()).requires_approval
    api, unregister = controls[0]
    unregister()
    api.register(spec(permission="ask_user"), lambda i: ToolResult(i.call_id, i.name))
    assert box.prepare_call(call()).requires_approval


@pytest.mark.asyncio
async def test_session_tool_and_restriction_have_matching_display_and_execution(env, tmp_path):
    _, host, start = env
    def initialize(ctx):
        ctx.tools.register(spec(), lambda i: ToolResult(i.call_id, i.name, content=i.session_id), session_id="one")
        ctx.tools.restrict(deny={"read_file"}, session_id="one")
    await start(initialize)
    box = toolbox(tmp_path, host)
    box.bind_session("one")
    assert "demo_echo" in {s.name for s in box.tool_specs()} and "read_file" not in {s.name for s in box.tool_specs()}
    assert (await box.execute(call(), ToolContext(session_id="one"))).content == "one"
    assert (await box.execute(ToolCall("r", "read_file", {"path": "anything"}), ToolContext(session_id="one"))).status == "blocked"
    box.bind_session("two")
    assert "demo_echo" not in {s.name for s in box.tool_specs()} and "read_file" in {s.name for s in box.tool_specs()}
    assert (await box.execute(call(), ToolContext(session_id="two"))).status == "blocked"


@pytest.mark.asyncio
async def test_guards_are_final_denials_and_pre_hooks_cannot_allow_past_them(env, tmp_path):
    _, host, start = env
    ran = []
    def initialize(ctx):
        ctx.tools.register(spec(), lambda i: ran.append(True) or ToolResult(i.call_id, i.name))
        ctx.tools.guard(lambda i: ToolDecision("deny", "policy"))
        ctx.tools.on("tools/pre-execute", lambda i: ToolDecision("allow"))
    await start(initialize)
    result = await toolbox(tmp_path, host).execute(call())
    assert result.status == "blocked" and "policy" in result.error and not ran


@pytest.mark.asyncio
async def test_pre_hook_failure_is_closed(env, tmp_path):
    _, host, start = env
    ran = []
    def fail(invocation):
        raise ValueError("bad policy")
    removers = []
    def initialize(ctx):
        ctx.tools.register(spec(), lambda i: ran.append(True) or ToolResult(i.call_id, i.name))
        removers.append(ctx.tools.on("tools/pre-execute", fail))
    await start(initialize)
    result = await toolbox(tmp_path, host).execute(call())
    assert result.status == "blocked" and "bad policy" in result.error and not ran


@pytest.mark.asyncio
async def test_native_and_legacy_name_collision_hides_and_blocks_both(env, tmp_path):
    _, host, start = env
    ran = []
    await start(lambda ctx: ctx.tools.register(spec(), lambda i: ran.append("native") or ToolResult(i.call_id, i.name)))
    def legacy(**kwargs):
        return SimpleNamespace(specs=[spec()], handlers={"demo_echo": lambda c: ran.append("legacy")})
    box = CoreToolbox(work_root=tmp_path, loaded_skill_roots=set(), plugin_tool_providers=[legacy, host.provider], permission_preset="ask")
    assert "demo_echo" not in {s.name for s in box.tool_specs()}
    assert box.prepare_call(call()).metadata["approval"]["blocked"]
    assert (await box.execute(call())).status == "blocked" and not ran


@pytest.mark.asyncio
async def test_legacy_metadata_cannot_impersonate_native_permission_declaration(env, tmp_path):
    _, host, _ = env
    fake = spec()
    fake.metadata = {"plugin_owned_tool": True}
    box = CoreToolbox(work_root=tmp_path, loaded_skill_roots=set(), plugin_tool_providers=[host.provider, lambda **kw: SimpleNamespace(specs=[fake])])
    assert "demo_echo" in {s.name for s in box.tool_specs()}
    assert "demo_echo" not in box._native_operation_levels


@pytest.mark.asyncio
async def test_unadvertised_legacy_handler_cannot_replace_owned_registration(env, tmp_path):
    _, host, start = env
    ran = []
    await start(lambda ctx: ctx.tools.register(spec(), lambda i: ToolResult(i.call_id, i.name, content="native")))
    async def wrong_handler(c):
        ran.append(1)
        return ToolResult(c.id, c.name, content="wrong")
    def legacy(**kwargs):
        return SimpleNamespace(specs=[], handlers={"demo_echo": wrong_handler})
    box = CoreToolbox(work_root=tmp_path, loaded_skill_roots=set(), plugin_tool_providers=[legacy, host.provider], permission_preset="ask")
    assert (await box.execute(call())).content == "native" and not ran


@pytest.mark.asyncio
async def test_handler_cancellation_releases_lifetime_lease(env, tmp_path):
    _, host, start = env
    entered = asyncio.Event()
    async def handler(i):
        entered.set()
        await asyncio.Future()
    handle = await start(lambda ctx: ctx.tools.register(spec(), handler))
    task = asyncio.create_task(toolbox(tmp_path, host).execute(call()))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await stop_plugin_backend(handle)
    assert "demo_echo" not in host.tools


@pytest.mark.asyncio
async def test_handler_budget_exhaustion_remains_kernel_termination_signal(env, tmp_path):
    _, host, start = env
    class Exhausted(Exception):
        budget_exhausted = True
    def handler(i):
        raise Exhausted("budget")
    await start(lambda ctx: ctx.tools.register(spec(), handler))
    with pytest.raises(Exhausted):
        await toolbox(tmp_path, host).execute(call())


@pytest.mark.asyncio
async def test_guard_added_by_pre_hook_is_enforced_before_handler(env, tmp_path):
    _, host, start = env
    ran = []
    def initialize(ctx):
        ctx.tools.register(spec(), lambda i: ran.append(1) or ToolResult(i.call_id, i.name))
        ctx.tools.on("tools/pre-execute", lambda i: ctx.tools.guard(lambda j: ToolDecision("deny", "new policy")) and None)
    await start(initialize)
    assert (await toolbox(tmp_path, host).execute(call())).status == "blocked" and not ran


@pytest.mark.asyncio
async def test_default_level_requires_approval_and_invalid_handler_result_fails(env, tmp_path):
    _, host, start = env
    def initialize(ctx):
        ctx.tools.register(ToolSpec("unknown_level", "Unknown", {"type": "object"}), lambda i: ToolResult(i.call_id, i.name))
        ctx.tools.register(spec(), lambda i: ToolResult("wrong-id", i.name))
    await start(initialize)
    box = toolbox(tmp_path, host)
    assert box.prepare_call(ToolCall("u", "unknown_level", {})).requires_approval
    result = await box.execute(call())
    assert result.status == "failed" and result.error_code == "tool/handler-error"


@pytest.mark.asyncio
async def test_registered_schema_is_isolated_and_nested_non_json_keys_are_rejected(env, tmp_path):
    _, host, start = env
    ran = []
    def initialize(ctx):
        original = spec()
        original.input_schema["additionalProperties"] = True
        ctx.tools.register(original, lambda i: ran.append(1) or ToolResult(i.call_id, i.name))
        original.input_schema["properties"]["text"]["type"] = "integer"
    await start(initialize)
    box = toolbox(tmp_path, host)
    assert (await box.execute(call())).status == "ok"
    bad = ToolCall("bad", "demo_echo", {"text": "ok", "extra": {1: "invalid JSON key"}})
    assert (await box.execute(bad)).status == "failed" and ran == [1]


@pytest.mark.asyncio
async def test_post_transform_and_observer_are_immutable_and_ordered(env, tmp_path):
    _, host, start = env
    seen = []
    def observe(outcome):
        with pytest.raises(TypeError):
            outcome.result["content"] = "tampered"
        with pytest.raises(TypeError):
            outcome.invocation.arguments["text"] = "tampered"
        seen.append(outcome.result["content"])
    def initialize(ctx):
        ctx.tools.register(spec(), lambda i: ToolResult(i.call_id, i.name, content="original"))
        ctx.tools.on("tools/post-execute", lambda o: ToolPatch(content=o.result["content"] + "!"))
        ctx.tools.on("tools/result", observe)
    await start(initialize)
    result = await toolbox(tmp_path, host).execute(call())
    assert result.content == "original!" and seen == ["original!"]


@pytest.mark.asyncio
async def test_post_and_observer_errors_do_not_repeat_or_undo_tool_side_effect(env, tmp_path, caplog):
    _, host, start = env
    ran = []
    def fail(o):
        raise ValueError("observer problem")
    def initialize(ctx):
        ctx.tools.register(spec(), lambda i: ran.append(1) or ToolResult(i.call_id, i.name, content="done"))
        ctx.tools.on("tools/post-execute", fail)
        ctx.tools.on("tools/result", fail)
    await start(initialize)
    result = await toolbox(tmp_path, host).execute(call())
    assert result.status == "ok" and result.content == "done" and ran == [1]
    assert result.metadata["tool_hook_errors"] and "observer problem" in caplog.text


@pytest.mark.asyncio
async def test_stop_waits_for_handler_lease_before_cleanup(env, tmp_path):
    _, host, start = env
    entered, release = asyncio.Event(), asyncio.Event()
    cleaned = []
    async def handler(i):
        entered.set()
        await release.wait()
        return ToolResult(i.call_id, i.name)
    def initialize(ctx):
        ctx.tools.register(spec(), handler)
        ctx.on_dispose(lambda: cleaned.append(True))
    handle = await start(initialize)
    task = asyncio.create_task(toolbox(tmp_path, host).execute(call()))
    await entered.wait()
    stopping = asyncio.create_task(stop_plugin_backend(handle))
    await asyncio.sleep(0)
    assert not cleaned and not stopping.done()
    release.set()
    assert (await task).status == "ok"
    await stopping
    assert cleaned == [True]


@pytest.mark.asyncio
async def test_flat_schema_is_validated_and_unsupported_keywords_are_explicit(env, tmp_path):
    _, host, start = env
    ran = []
    def initialize(ctx):
        ctx.tools.register(spec(), lambda i: ran.append(1) or ToolResult(i.call_id, i.name))
        invalid = spec("unsupported")
        invalid.input_schema["oneOf"] = []
        with pytest.raises(ValueError, match="schema"):
            ctx.tools.register(invalid, lambda i: None)
    await start(initialize)
    bad = ToolCall("bad", "demo_echo", {"text": 2})
    result = await toolbox(tmp_path, host).execute(bad)
    assert result.status == "failed" and not ran and "text" in result.error


@pytest.mark.asyncio
async def test_kernel_observer_runs_once_after_legacy_post_hook(env, tmp_path):
    from .test_kernel import _make_kernel, MockRuntimeKit
    from lamtools_core.runtime import RuntimeState
    from lamtools_core.plugin_system.hooks import HookDecision
    _, host, start = env
    seen, pre = [], []
    def initialize(ctx):
        ctx.tools.register(spec(), lambda i: ToolResult(i.call_id, i.name, content="body"))
        ctx.tools.on("tools/pre-execute", lambda i: pre.append(i.call_id) or ToolDecision("allow"))
        ctx.tools.on("tools/result", lambda o: seen.append(o.result["content"]))
    await start(initialize)
    box = toolbox(tmp_path, host)
    class Kit(MockRuntimeKit):
        async def execute_tool(self, state, invocation):
            return await box.execute(invocation, ToolContext(session_id=state.session_id, run_id=state.run_id, work_root=str(tmp_path)))
    kit = Kit()
    kit.toolbox = box
    kernel = _make_kernel(kit)
    class Legacy:
        async def run(self, event):
            return HookDecision(updated_output={"content": "legacy-final"}) if event.event_name == "PostToolUse" else HookDecision()
    kernel.hook_engine = Legacy()
    state = RuntimeState(session_id="s", run_id="run")
    invocation = box.prepare_call(call())
    assert await kernel._apply_pre_tool_hook(state, invocation) is None
    result = await kernel._execute_tool(state, invocation)
    assert seen == []
    result = await kernel._apply_post_tool_hook(state, invocation, result)
    await kernel._emit_tool_finished(state, invocation, result)
    assert seen == ["legacy-final"] and pre == ["call"]


@pytest.mark.asyncio
async def test_kernel_pre_guard_blocks_before_ask_user_wait(env, tmp_path):
    from .test_kernel import _make_kernel, MockRuntimeKit
    from lamtools_core.runtime import RuntimeState
    _, host, start = env
    def initialize(ctx):
        ctx.tools.register(spec(permission="ask_user"), lambda i: ToolResult(i.call_id, i.name))
        ctx.tools.guard(lambda i: ToolDecision("deny", "no question needed"))
    await start(initialize)
    box = toolbox(tmp_path, host)
    kit = MockRuntimeKit()
    kit.toolbox = box
    kernel = _make_kernel(kit)
    invocation = box.prepare_call(call())
    assert invocation.requires_approval
    result = await kernel._apply_pre_tool_hook(RuntimeState(session_id="s", run_id="r"), invocation)
    assert result.status == "blocked" and "no question needed" in result.error


@pytest.mark.asyncio
async def test_numeric_cap_and_user_override_cannot_weaken_hard_block(env, tmp_path):
    _, host, start = env
    ran = []
    def initialize(ctx):
        ctx.tools.register(spec(), lambda i: ran.append(1) or ToolResult(i.call_id, i.name), level=3)
        ctx.tools.register(spec("never"), lambda i: ran.append(2) or ToolResult(i.call_id, i.name), level=0)
    await start(initialize)
    box = toolbox(tmp_path, host)
    box.approval_gate.available_level = 1
    assert (await box.execute(box.prepare_approved_call(call()))).status == "blocked" and not ran
    box.approval_gate.available_level = 3
    box.approval_gate.operation_levels["demo_echo"] = 1
    assert not box.prepare_call(call()).requires_approval
    assert (await box.execute(call())).status == "ok"
    box.approval_gate.operation_levels["never"] = 1
    assert (await box.execute(box.prepare_approved_call(call("never")))).status == "blocked" and ran == [1]


def test_desktop_startup_exposes_tools_to_real_main_and_child_toolboxes(tmp_path, monkeypatch):
    import json
    from functools import partial
    from fastapi.testclient import TestClient
    from lamtools_core.app.http_agent_app import create_core_agent_http_app
    from lamtools_core.app.default_agent import _build_core_runtime_toolbox
    monkeypatch.setattr("lamtools_core.app.http_agent_app.warm_command_shell", lambda: None)
    monkeypatch.setattr("lamtools_core.runtime.power.apply_keep_awake", lambda: None)
    plugin_root = tmp_path / "plugins" / "tool-consumer"
    plugin_root.mkdir(parents=True)
    (plugin_root / "plugin.json").write_text(json.dumps({"name": "tool-consumer", "version": "1", "backend": "./backend.py"}))
    (plugin_root / "backend.py").write_text('''
from lamtools_core.tool import ToolSpec, ToolResult
class Runtime:
    def start(self, context):
        self.context = context
        context.tools.register(ToolSpec("boot_echo", "Echo", {"type": "object"}),
            lambda i: ToolResult(i.call_id, i.name, content=i.session_id), level=1)
        context.tools.register(ToolSpec("boot_scoped", "Scoped", {"type": "object"}),
            lambda i: ToolResult(i.call_id, i.name), level=1, session_id="chosen")
def create_plugin(context):
    return Runtime()
''')
    app = create_core_agent_http_app(core_db=tmp_path / "boot.db", data_dir=tmp_path / "data",
                                     work_root=tmp_path / "project", plugin_roots=[tmp_path / "plugins"])
    with TestClient(app) as client:
        state = app.state.core_agent_app_state
        handle = next(h for h in state["plugin_runtimes"] if h.plugin.name == "tool-consumer")
        assert handle.state == "ready", handle.error
        box, registry = client.portal.call(partial(_build_core_runtime_toolbox, work_root=tmp_path / "project",
            plugin_assembly={"plugin_context": handle.value.context}, approval_policy="require", llm_client=object()))
        child = box.sub_agent_runner._build_toolbox(set(), active_mode=None)
        for actual in (box, child):
            actual.bind_session("chosen")
            assert {"boot_echo", "boot_scoped"} <= {s.name for s in actual.tool_specs()}
            result = client.portal.call(actual.execute, ToolCall("b", "boot_echo", {}), ToolContext(session_id="chosen"))
            assert result.status == "ok" and result.content == "chosen"
            actual.bind_session("other")
            assert "boot_scoped" not in {s.name for s in actual.tool_specs()}
        from lamtools_core.app.default_agent import _close_mcp_registry
        client.portal.call(_close_mcp_registry, registry)
    assert "boot_echo" not in {s.name for s in box.tool_specs()}
