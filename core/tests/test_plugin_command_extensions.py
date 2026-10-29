"""user:“宿主能力补齐和接口完善与文档更新”+(动态斜杠命令进入原目录和执行入口，范围、撤回、调用排空有可验证契约)。"""

from __future__ import annotations

import asyncio
from functools import partial

import pytest

from lamtools_core.plugin_system.context import PluginContext
from lamtools_core.plugin_system.lifecycle import PluginRuntimeHandle, start_plugin_backend, stop_plugin_backend
from lamtools_core.plugin_system.manifest import PluginManifest
from lamtools_core.plugin_system.command_extensions import CommandResult, ensure_command_extensions


@pytest.fixture
async def env(tmp_path):
    root = PluginContext(tmp_path)
    host = ensure_command_extensions(root, reserved_names={"compact"})
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


def definitions(host, session="s"):
    return host.merge_catalog([], session_id=session)


async def invoke(host, *, session="s", arguments="hello", definition=None):
    definition = definition or next(d for d in definitions(host, session) if d.name == "echo")
    return await host.dispatch(definition.metadata["owned_command_token"], name="echo", session_id=session,
                               arguments=arguments, work_root="project")


@pytest.mark.asyncio
async def test_staged_registration_enters_real_catalog_shape_then_retracts(env):
    _, host, start = env
    def initialize(ctx):
        ctx.commands.register("echo", lambda i: CommandResult(text=i.arguments), title="Echo")
        assert definitions(host) == []
    handle = await start(initialize)
    listed = definitions(host)
    assert listed[0].to_dict()["kind"] == "action" and listed[0].title == "Echo"
    assert (await invoke(host)).text == "hello"
    await stop_plugin_backend(handle)
    assert definitions(host) == []


@pytest.mark.asyncio
async def test_start_failure_and_stale_facade_cannot_leave_commands(env):
    root, host, start = env
    views = []
    def initialize(ctx):
        views.append(ctx.commands)
        ctx.commands.register("echo", lambda i: CommandResult())
        raise RuntimeError("startup failed")
    with pytest.raises(RuntimeError):
        await start(initialize)
    assert not definitions(host)
    with pytest.raises(RuntimeError):
        views[0].register("later", lambda i: CommandResult())
    with pytest.raises(RuntimeError):
        root.commands.register("outside", lambda i: CommandResult())


@pytest.mark.asyncio
async def test_session_override_restores_global_after_dispose(env):
    _, host, start = env
    removers = []
    def initialize(ctx):
        ctx.commands.register("echo", lambda i: CommandResult(text="global"))
        removers.append(ctx.commands.register("echo", lambda i: CommandResult(text=i.session_id), session_id="s"))
    await start(initialize)
    assert (await invoke(host)).text == "s"
    assert (await invoke(host, session="other")).text == "global"
    removers[0]()
    removers[0]()
    assert (await invoke(host)).text == "global"


@pytest.mark.asyncio
async def test_duplicate_core_and_cross_plugin_names_are_explicit_conflicts(env):
    _, _, start = env
    def initialize(ctx):
        ctx.commands.register("echo", lambda i: CommandResult())
        with pytest.raises(ValueError, match="conflict"):
            ctx.commands.register("echo", lambda i: CommandResult())
        with pytest.raises(ValueError, match="reserved"):
            ctx.commands.register("compact", lambda i: CommandResult())
    await start(initialize)
    def other(ctx):
        with pytest.raises(ValueError, match="conflict"):
            ctx.commands.register("echo", lambda i: CommandResult(), session_id="other")
    await start(other, "other")


@pytest.mark.asyncio
async def test_new_static_collision_hides_both_and_dispatch_checks_actual_availability(env):
    from lamtools_core.composer_commands import ComposerCommandDefinition
    _, host, start = env
    await start(lambda ctx: ctx.commands.register("echo", lambda i: CommandResult()))
    stale = definitions(host)[0]
    static = ComposerCommandDefinition("echo", "Static", "", "", "run_action", "plugin")
    assert host.merge_catalog([static], session_id="s") == []
    with pytest.raises(RuntimeError, match="conflict"):
        await invoke(host, definition=stale)


@pytest.mark.asyncio
async def test_old_definition_cannot_execute_restarted_handler(env):
    root, host, start = env
    handle = await start(lambda ctx: ctx.commands.register("echo", lambda i: CommandResult(text="current")))
    old = definitions(host)[0]
    await stop_plugin_backend(handle)
    await start_plugin_backend(handle, root)
    with pytest.raises(RuntimeError, match="registration"):
        await invoke(host, definition=old)
    assert (await invoke(host)).text == "current"


@pytest.mark.asyncio
async def test_wrong_session_and_disallowed_input_never_call_handler(env):
    _, host, start = env
    ran = []
    await start(lambda ctx: ctx.commands.register("echo", lambda i: ran.append(1) or CommandResult(), session_id="s", accepts_args=False))
    definition = definitions(host)[0]
    with pytest.raises(RuntimeError):
        await invoke(host, definition=definition, session="other", arguments="")
    with pytest.raises(ValueError, match="arguments"):
        await invoke(host, arguments="forbidden")
    assert ran == []


@pytest.mark.asyncio
async def test_stop_drains_active_handler_and_cancellation_releases_lease(env):
    _, host, start = env
    entered, release = asyncio.Event(), asyncio.Event()
    cleaned = []
    async def handler(i):
        entered.set()
        await release.wait()
        return CommandResult(text="done")
    def initialize(ctx):
        ctx.commands.register("echo", handler)
        ctx.on_dispose(lambda: cleaned.append(1))
    handle = await start(initialize)
    task = asyncio.create_task(invoke(host))
    await entered.wait()
    stopping = asyncio.create_task(stop_plugin_backend(handle))
    await asyncio.sleep(0)
    assert not stopping.done() and not cleaned and not definitions(host)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await stopping
    assert cleaned == [1]


@pytest.mark.asyncio
async def test_invalid_result_is_rejected_and_invocation_is_immutable(env):
    from dataclasses import FrozenInstanceError
    _, host, start = env
    def handler(i):
        with pytest.raises(FrozenInstanceError):
            i.session_id = "different"
        return {"text": "not a CommandResult"}
    await start(lambda ctx: ctx.commands.register("echo", handler))
    with pytest.raises(TypeError, match="CommandResult"):
        await invoke(host)


@pytest.mark.asyncio
async def test_regular_handler_exception_is_reported_and_successful_call_drains_before_stop(env):
    _, host, start = env
    entered, release = asyncio.Event(), asyncio.Event()
    async def handler(i):
        if i.arguments == "error":
            raise OSError("external failure")
        entered.set()
        await release.wait()
        return CommandResult(text="done")
    handle = await start(lambda ctx: ctx.commands.register("echo", handler))
    with pytest.raises(RuntimeError, match="external failure"):
        await invoke(host, arguments="error")
    task = asyncio.create_task(invoke(host))
    await entered.wait()
    stopping = asyncio.create_task(stop_plugin_backend(handle))
    await asyncio.sleep(0)
    assert not stopping.done()
    release.set()
    assert (await task).text == "done"
    await stopping


@pytest.mark.asyncio
async def test_global_descriptor_cannot_bypass_new_session_override(env):
    _, host, start = env
    views = []
    def initialize(ctx):
        views.append(ctx.commands)
        ctx.commands.register("echo", lambda i: CommandResult(text="global"))
    await start(initialize)
    old = definitions(host)[0]
    views[0].register("echo", lambda i: CommandResult(text="scoped"), session_id="s")
    with pytest.raises(RuntimeError, match="registration"):
        await invoke(host, definition=old)
    assert (await invoke(host)).text == "scoped"


def test_desktop_startup_catalog_and_execute_use_real_dynamic_command(tmp_path, monkeypatch):
    import json
    from fastapi.testclient import TestClient
    from lamtools_core.app.http_agent_app import create_core_agent_http_app
    monkeypatch.setattr("lamtools_core.app.http_agent_app.warm_command_shell", lambda: None)
    monkeypatch.setattr("lamtools_core.runtime.power.apply_keep_awake", lambda: None)
    plugin_root = tmp_path / "plugins" / "command-consumer"
    plugin_root.mkdir(parents=True)
    (plugin_root / "plugin.json").write_text(json.dumps({"name": "command-consumer", "version": "1", "backend": "./backend.py"}))
    (plugin_root / "backend.py").write_text('''
from lamtools_core.plugin_system import CommandResult
class Runtime:
    def start(self, context):
        self.ran = []
        def handler(i):
            self.ran.append(i)
            return CommandResult(text=i.session_id + ":" + i.arguments)
        context.commands.register("plugin-echo", handler)
        context.commands.register("plugin-private", handler, session_id="chosen")
        context.commands.register("plugin-fail", lambda i: CommandResult("error", "reported failure"))
def create_plugin(context):
    return Runtime()
''')
    app = create_core_agent_http_app(core_db=tmp_path / "boot.db", data_dir=tmp_path / "data",
                                     work_root=tmp_path / "project", plugin_roots=[tmp_path / "plugins"])
    with TestClient(app) as client:
        state = app.state.core_agent_app_state
        handle = next(h for h in state["plugin_runtimes"] if h.plugin.name == "command-consumer")
        assert handle.state == "ready", handle.error
        operations = state["operations"]
        listed = client.portal.call(operations.execute, "command.catalog", {"thread_id": "chosen"})
        names = {d["name"] for d in listed.payload["commands"]}
        assert {"plugin-echo", "plugin-private"} <= names
        listed_other = client.portal.call(operations.execute, "command.catalog", {"thread_id": "other"})
        assert "plugin-private" not in {d["name"] for d in listed_other.payload["commands"]}
        async def execute(name, **extra):
            return await operations.execute("command.execute", {"thread_id": "chosen", "command": name, "arguments": " hello ", **extra})
        result = client.portal.call(execute, "plugin-echo")
        assert result.status == "ok" and result.payload["result"]["text"] == "chosen:hello"
        assert handle.value.ran[0].work_root == str(tmp_path / "project")
        rejected = client.portal.call(partial(execute, "plugin-echo", attachments=[{"type": "file"}]))
        assert rejected.status == "error" and len(handle.value.ran) == 1
        failed = client.portal.call(execute, "plugin-fail")
        assert failed.status == "error" and "reported failure" in failed.payload["error"]
        # The live adapter performs its ordinary revision check and forwards
        # the same catalog and action, without starting an assistant turn.
        sessions = state["plugin_session_service"]
        client.portal.call(partial(sessions.create, session_id="chosen"))
        async def live_execute():
            ctx = sessions._context()
            async def wrong_action(**kwargs):
                return {"text": "WRONG HANDLER"}
            monkeypatch.setattr(ctx.host.member_hooks, "command_action_handlers", lambda: {"plugin-echo": wrong_action})
            async with ctx.session_factory() as db:
                revision = await ctx.persistence.current_revision(db, "chosen")
            return await ctx.host.execute("command.execute", request_id="cmd", params={
                "thread_id": "chosen", "command": "plugin-echo", "arguments": "live",
                "expected_revision": revision,
            }, context=ctx)
        outcome = client.portal.call(live_execute)
        assert outcome.response["result"]["result"]["text"] == "chosen:live"
        assert client.portal.call(sessions.state, "chosen").active_run_id is None
        client.portal.call(stop_plugin_backend, handle)
        assert client.portal.call(execute, "plugin-echo").status == "error"
        assert "error" in client.portal.call(live_execute).response
