"""user:“每一个地方 sunday 都有等价或者近似接口”+(实际CLI启动事实在插件启动前公开，不伪造桌面启动任务)。"""
import json

import pytest

from lamtools_core.cli_commands.task import CoreCliRunOptions, run_core_cli_task
from lamtools_core.plugin_system import PluginContext
from .test_core_cli import ScriptedCoreCliAnswerOnlyLLM


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["runtime", "db"])
async def test_cli_repeated_caller_cancellation_waits_for_owned_cleanup(tmp_path, isolated_config_root, monkeypatch, stage):
    # user:“完成真实接口、参数/错误、作用域、取消/清理”+(反复取消CLI调用者不能中断已经开始的资源收尾，清理完成后再传播取消)。
    import asyncio
    from lamtools_core.cli_commands import task
    from lamtools_core.runtime import RuntimeTaskRegistry
    entered, release = asyncio.Event(), asyncio.Event()
    finished, databases = set(), []
    shutdown = RuntimeTaskRegistry.shutdown
    async def observed_shutdown(instance):
        if stage == "runtime":
            entered.set()
            await release.wait()
        await shutdown(instance)
        finished.add("runtime")
    monkeypatch.setattr(RuntimeTaskRegistry, "shutdown", observed_shutdown)
    open_db = task.open_core_app_db
    async def observed_open(*args, **kwargs):
        db = await open_db(*args, **kwargs)
        close = type(db).close
        databases.append((db, close))
        async def observed_close(instance):
            if stage == "db":
                entered.set()
                await release.wait()
            await close(instance)
            finished.add("db")
        monkeypatch.setattr(type(db), "close", observed_close)
        return db
    monkeypatch.setattr(task, "open_core_app_db", observed_open)
    def fail_assembly(*args, **kwargs):
        raise RuntimeError("controlled setup failure before cleanup")
    monkeypatch.setattr(task, "assemble_core_agent_plugins", fail_assembly)
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    pending = asyncio.create_task(run_core_cli_task(CoreCliRunOptions(message="Answer directly", model_id="fake-model",
        work_root=tmp_path / "workspace", run_dir=tmp_path / "run", core_db=tmp_path / "core.db", plugin_roots=(plugins,)),
        llm_client=ScriptedCoreCliAnswerOnlyLLM()))
    try:
        await asyncio.wait_for(entered.wait(), 8)
        pending.cancel()
        await asyncio.sleep(0)
        pending.cancel()
        await asyncio.sleep(0)
        assert not pending.done(), "caller cancellation must wait for the actual cleanup"
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert finished == {"runtime", "db"}
    finally:
        release.set()
        await asyncio.gather(pending, return_exceptions=True)
        for db, close in databases:
            if "db" not in finished:
                await close(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("explicit_roots", [False, True])
async def test_cli_profile_discovery_uses_same_plugin_roots_as_assembly(tmp_path, isolated_config_root, monkeypatch, explicit_roots):
    # user:“复用现有宿主权威”+(运行档发现与实际插件装配使用同一组根，显式根优先，缺省仍用原目录)。
    from lamtools_core.plugin_system import paths, profiles
    root = tmp_path / "selected-plugins" / "root-profile"
    root.mkdir(parents=True)
    (root / "plugin.json").write_text(json.dumps({"name": "root-profile", "version": "1",
        "profiles": {"answer": {"tools": ["read_file"]}}}))
    default_roots = tmp_path / "empty-default"
    default_roots.mkdir()
    monkeypatch.setattr(paths, "default_plugin_roots", lambda work_root, **kwargs: [default_roots] if explicit_roots else [root.parent])
    observed = []
    apply = profiles.apply_profile
    def capture(toolbox, spec):
        observed.append(spec.full_name)
        return apply(toolbox, spec)
    monkeypatch.setattr(profiles, "apply_profile", capture)
    summary = await run_core_cli_task(CoreCliRunOptions(message="Answer directly", model_id="fake-model",
        profile="root-profile:answer", work_root=tmp_path / "workspace", run_dir=tmp_path / "run",
        core_db=tmp_path / "core.db", plugin_roots=(root.parent,) if explicit_roots else ()),
        llm_client=ScriptedCoreCliAnswerOnlyLLM())
    assert summary["ok"] and observed == ["root-profile:answer"]


@pytest.mark.asyncio
@pytest.mark.parametrize("override", [False, True])
async def test_cli_profile_override_preserves_native_constraints(tmp_path, isolated_config_root, monkeypatch, override):
    # user:“复用现有宿主权威”+(CLI覆盖仅改变指定字段，原manifest的MCP限制及其余运行档声明必须到达实际执行门面)。
    from lamtools_core.plugin_system import paths, profiles
    root = tmp_path / "plugins" / "constrained"
    root.mkdir(parents=True)
    (root / "plugin.json").write_text(json.dumps({"name": "constrained", "version": "1", "profiles": {
        "answer": {"tools": ["read_file", "mcp"], "approval": "ask", "mcpServers": ["test-server"],
            "mcpTools": ["mcp__test-server__read"], "skills": ["local-skill"],
            "approvedTools": ["mcp__test-server__read"], "budget": {"maxToolCalls": 3, "maxTokens": 10000}}}}))
    monkeypatch.setattr(paths, "default_plugin_roots", lambda work_root: (root.parent,))
    captured = []
    apply = profiles.apply_profile
    def observed(toolbox, spec):
        captured.append(spec)
        assert spec.mcp_servers == ("test-server",)
        assert spec.mcp_tools == ("mcp__test-server__read",)
        assert spec.skills == ("local-skill",)
        assert spec.approved_tools == ("mcp__test-server__read",)
        assert spec.tools == (("read_file",) if override else ("read_file", "mcp"))
        assert spec.approval == ("auto" if override else "ask")
        assert spec.budget.max_tool_calls == (5 if override else 3)
        assert spec.budget.max_tokens == 10000
        result = apply(toolbox, spec)
        assert toolbox.mcp_service.allowed_tools == frozenset(spec.mcp_tools)
        assert toolbox.approved_mcp_tools == set(spec.approved_tools)
        return result
    monkeypatch.setattr(profiles, "apply_profile", observed)
    summary = await run_core_cli_task(CoreCliRunOptions(message="Answer directly", model_id="fake-model",
        profile="constrained:answer", profile_tools="read_file" if override else "",
        profile_approval="auto" if override else "", profile_budget_calls=5 if override else None,
        work_root=tmp_path / "workspace", run_dir=tmp_path / "run", core_db=tmp_path / "core.db",
        plugin_roots=(root.parent,)), llm_client=ScriptedCoreCliAnswerOnlyLLM())
    assert summary["ok"] and len(captured) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("explicit", [False, True])
@pytest.mark.parametrize("injected", [False, True])
async def test_cli_profile_scene_selection_reaches_model_route(tmp_path, isolated_config_root, monkeypatch, explicit, injected):
    # user:“复用现有宿主权威”+(实际manifest场景走原解析器，显式模型优先，解析结果到配置加载及运行摘要保持一致)。
    from types import SimpleNamespace
    from lamtools_core.cli_commands import config
    from lamtools_core.config import model_selection
    from lamtools_core.plugin_system import paths
    root = tmp_path / "plugins" / "scene-reader"
    root.mkdir(parents=True)
    (root / "plugin.json").write_text(json.dumps({"name": "scene-reader", "version": "1",
        "profiles": {"answer": {"tools": ["read_file"], "modelScene": "answer-scene"}}}))
    monkeypatch.setattr(paths, "default_plugin_roots", lambda work_root: (root.parent,))
    scenes = []
    def resolve(scene):
        scenes.append(scene)
        return SimpleNamespace(model_id="scene-model")
    monkeypatch.setattr(model_selection, "resolve_scene_model", resolve)
    expected = "explicit-model" if explicit else "scene-model"
    class ConfigReached(RuntimeError):
        pass
    def load(*, model_ref):
        assert model_ref == expected
        raise ConfigReached()
    monkeypatch.setattr(config, "load_llm_config", load)
    options = CoreCliRunOptions(message="Answer directly", model_id="explicit-model" if explicit else "",
        profile="scene-reader:answer", work_root=tmp_path / "workspace", run_dir=tmp_path / "run",
        core_db=tmp_path / "core.db", plugin_roots=(root.parent,))
    if injected:
        summary = await run_core_cli_task(options, llm_client=ScriptedCoreCliAnswerOnlyLLM())
        assert summary["ok"] and summary["model"]["model_id"] == expected
    else:
        with pytest.raises(ConfigReached):
            await run_core_cli_task(options)
    assert scenes.count("answer-scene") == (0 if explicit else 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("stage",["assembly","mcp","skill","cleanup"])
async def test_cli_early_failure_and_cleanup_failure_revoke_startup_and_close_owned_resources(tmp_path,isolated_config_root,monkeypatch,stage):
    # user:“完成真实接口、参数/错误、作用域、取消/清理”+(整个原CLI启动流程都受同一清理保护，早期失败或某项清理失败不能留下启动值和后续资源)。
    from lamtools_core.cli_commands import task
    from lamtools_core import mcp, plugin_system, skill_runtime
    from lamtools_core.plugin_system.startup_access import StartupAccessError
    class StartupFailure(RuntimeError):
        pass
    class CleanupFailure(RuntimeError):
        pass
    events, captured, databases, registries = [], [], [], []
    db_closed, runtime_closed = set(), set()
    open_db = task.open_core_app_db
    async def observed_open(*args,**kwargs):
        db = await open_db(*args,**kwargs)
        close = type(db).close
        databases.append((db,close))
        async def observed_close(instance):
            if instance is db:
                events.append("db")
            await close(instance)
            db_closed.add(id(instance))
        monkeypatch.setattr(type(db),"close",observed_close)
        return db
    monkeypatch.setattr(task,"open_core_app_db",observed_open)
    assemble = task.assemble_core_agent_plugins
    def observed_assembly(*args,**kwargs):
        context = kwargs["context"]
        captured.append(context.headless_startup)
        assert captured[-1].get()["task"] == "Answer directly"
        registry = context.runtime_task_registry
        shutdown = type(registry).shutdown
        registries.append((registry,shutdown))
        async def observed_shutdown(instance):
            if instance is registry:
                events.append("runtime")
            await shutdown(instance)
            runtime_closed.add(id(instance))
        monkeypatch.setattr(type(registry),"shutdown",observed_shutdown)
        if stage == "assembly":
            raise StartupFailure("assembly failure")
        return assemble(*args,**kwargs)
    monkeypatch.setattr(task,"assemble_core_agent_plugins",observed_assembly)
    close_mcp = mcp.MCPToolRegistry.close
    async def observed_mcp_close(instance):
        events.append("mcp")
        await close_mcp(instance)
    monkeypatch.setattr(mcp.MCPToolRegistry,"close",observed_mcp_close)
    shutdown_plugins = plugin_system.shutdown_plugin_backends
    async def observed_plugin_shutdown(handles):
        events.append("plugins")
        if stage == "cleanup":
            raise CleanupFailure("plugin cleanup failure")
        await shutdown_plugins(handles)
    monkeypatch.setattr(plugin_system,"shutdown_plugin_backends",observed_plugin_shutdown)
    def fail(*args,**kwargs):
        raise StartupFailure(stage + " failure")
    if stage == "mcp":
        monkeypatch.setattr(mcp,"MCPToolRegistry",fail)
    if stage == "skill":
        monkeypatch.setattr(skill_runtime,"create_skill_runtime",fail)
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    try:
        with pytest.raises(CleanupFailure if stage == "cleanup" else StartupFailure):
            await run_core_cli_task(CoreCliRunOptions(message="Answer directly",model_id="fake-model",thread_id="failure-run",
                work_root=tmp_path / "workspace",run_dir=tmp_path / "run",core_db=tmp_path / "core.db",plugin_roots=(plugins,)),
                llm_client=ScriptedCoreCliAnswerOnlyLLM())
        with pytest.raises(StartupAccessError) as error:
            captured[0].get()
        assert error.value.code == "startup/host-changed"
        assert events == {"assembly":["runtime","db"],"mcp":["plugins","runtime","db"],
            "skill":["plugins","runtime","mcp","db"],"cleanup":["plugins","runtime","mcp","db"]}[stage]
        assert all(id(db) in db_closed for db,_ in databases)
    finally:
        for registry,shutdown in registries:
            if id(registry) not in runtime_closed:
                await shutdown(registry)
        for db,close in databases:
            if id(db) not in db_closed:
                await close(db)


@pytest.mark.asyncio
async def test_actual_cli_plugin_reads_frozen_startup_and_run_persists(tmp_path, isolated_config_root):
    root = tmp_path / "plugins" / "startup-reader"
    root.mkdir(parents=True)
    (root / "plugin.json").write_text(json.dumps({"name": "startup-reader", "version": "1", "backend": "./backend.py"}))
    (root / "backend.py").write_text('''
import json
class Runtime:
    def __init__(self, ctx):
        snapshot = ctx.headless_startup.get()
        (ctx.work_root / 'startup.json').write_text(json.dumps(snapshot))
        snapshot['task'] = 'MUTATED'
        assert ctx.headless_startup.get()['task'] != 'MUTATED'
        ctx.service('startup_capture')(ctx.headless_startup)
def create_plugin(ctx):
    return Runtime(ctx)
''')
    captured = []
    summary = await run_core_cli_task(CoreCliRunOptions(message="Answer directly", model_id="fake-model",
        thread_id="startup-run", work_root=tmp_path / "workspace", run_dir=tmp_path / "run",
        core_db=tmp_path / "core.db", plugin_roots=(root.parent,), raw=True, permission_preset="auto",
        plugin_services={"startup_capture": captured.append}),
        llm_client=ScriptedCoreCliAnswerOnlyLLM())
    saved = json.loads((tmp_path / "workspace" / "startup.json").read_text())
    assert saved["task"] == "Answer directly" and saved["thread_id"] == "startup-run"
    assert saved["requested_session_id"] == "startup-run" and saved["json_summary"] is True
    assert saved["permission_preset"] == "auto" and saved["approval_policy"] == "auto_approve"
    assert saved["additional_writable_roots"] == []
    assert summary["ok"] and (tmp_path / "core.db").is_file()
    from lamtools_core.plugin_system.startup_access import StartupAccessError
    with pytest.raises(StartupAccessError) as error:
        captured[0].get()
    assert error.value.code == "startup/host-changed"


@pytest.mark.asyncio
async def test_desktop_has_no_headless_invocation_and_stale_facade_fails(tmp_path):
    from lamtools_core.plugin_system.startup_access import StartupAccessError
    from lamtools_core.plugin_system.services import ServiceError
    ctx = PluginContext(tmp_path)
    ctx._begin_registration_scope("reader", 1)
    api = ctx.headless_startup
    with pytest.raises(StartupAccessError) as error:
        api.get()
    assert error.value.code == "startup/unavailable"
    await ctx._registration_scope.dispose()
    with pytest.raises(ServiceError):
        api.get()
