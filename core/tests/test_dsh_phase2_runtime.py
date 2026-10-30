"""user:“继续，把 2 阶段都做完”+(新增运行能力必须同步迁移提示，不能误映射尚缺的终端、监听和完整目标域)。"""
from .test_dsh_compatibility import source
from lamtools_core.plugin_system.dsh_compat import export_port


def test_runtime_ports_advertise_real_calls_but_keep_unsupported_seams(tmp_path):
    src = source(tmp_path, {"index.ts": '''ctx.subprocess.spawn(spec);ctx.subprocess.spawnTerminal(spec);
ctx.fs.writeText(target,text);ctx.fs.editText(target,edit);ctx.fs.watch(target,changed,signal);
ctx.llm.stream(request);ctx.goals.create(agent,request);ctx.schedule.create(sessionId,request);'''})
    report = export_port(src, tmp_path / "out")
    processes = {row["name"]: row for row in report["processMethods"]}
    files = {row["name"]: row for row in report["filesystemMethods"]}
    models = {row["name"]: row for row in report["modelMethods"]}
    durable = {row["name"]: row for row in report["durableMethods"]}
    assert processes["subprocess.spawn"]["suggestedContract"] == "context.processes.spawn"
    assert "suggestedContract" not in processes["subprocess.spawnTerminal"]
    assert files["fs.writeText"]["suggestedContract"] == "context.filesystem.write_text"
    assert files["fs.editText"]["suggestedContract"] == "context.filesystem.edit_text"
    assert "suggestedContract" not in files["fs.watch"]
    assert models["llm.stream"]["suggestedContract"] == "context.llm.stream"
    assert durable["goals.create"]["suggestedContract"] == "context.goals.create"
    assert durable["schedule.create"]["suggestedContract"] == "context.schedule.create"
    assert not report["runtimeVerified"]


def test_local_targets_and_polling_watch_keep_explicit_approximation(tmp_path):
    # user:“继续，把 2 阶段都做完”+(本地路径及轮询监听有可检查提示，但不自动替换 DSH 目标域)。
    src = source(tmp_path, {"index.ts": '''ctx.fs.resolve(p);ctx.fs.processPath(p);ctx.fs.fileUrl(p);
ctx.fs.contains(a,b);ctx.fs.processPathFromHostPath(p);ctx.fs.watch(p,callback);'''})
    report = export_port(src, tmp_path / "out")
    files = {row["name"]: row for row in report["filesystemMethods"]}
    for name, target in {"resolve": "resolve", "processPath": "process_path", "fileUrl": "file_url",
                         "contains": "contains", "processPathFromHostPath": "process_path_from_host_path",
                         "watch": "watch"}.items():
        item = files["fs." + name]
        assert item["candidateContract"] == "context.filesystem." + target
        assert item["conversion"] == "agent-required"
        assert "suggestedContract" not in item
    assert "轮询" in files["fs.watch"]["difference"]


def test_shell_and_environment_candidates_keep_native_lifecycle_differences(tmp_path):
    # user:“继续，把 2 阶段都做完”+(Shell 与环境可调用但参数、后台期限和命名空间须由 agent 显式调整)。
    src = source(tmp_path, {"index.ts": "ctx.shell.resolve(request);ctx.shell.execute(spec);ctx.shellEnv.register(c);ctx.shellEnv.collect(e);ctx.shellEnv.list();"})
    report = export_port(src, tmp_path / "out")
    methods = {row["name"]: row for row in report["processMethods"]}
    for original, target in {"shell.resolve": "shell.resolve", "shell.execute": "shell.execute",
                             "shellEnv.register": "shell_env.register", "shellEnv.collect": "shell_env.collect",
                             "shellEnv.list": "shell_env.list"}.items():
        assert methods[original]["candidateContract"] == "context." + target
        assert methods[original]["conversion"] == "agent-required"
        assert "suggestedContract" not in methods[original]


def test_jobs_and_spill_are_explicit_python_ports_with_remaining_protocol_gaps(tmp_path):
    # user:“继续，把 2 阶段都做完”+(作业和长文本保存迁移不得猜测 session 授权、控制器或交付协议)。
    src = source(tmp_path, {"index.ts": "ctx.jobs.start(spec);ctx.jobs.read(id);ctx.jobs.kill(id);ctx.jobs.readAt(id,offset);ctx.spillStore.saveText(request);"})
    report = export_port(src, tmp_path / "out")
    methods = {row["name"]: row for row in report["backgroundMethods"]}
    assert methods["jobs.start"]["candidateContract"] == "context.jobs.start"
    assert methods["jobs.read"]["candidateContract"] == "context.jobs.read"
    assert methods["jobs.kill"]["candidateContract"] == "context.jobs.kill"
    assert "candidateContract" not in methods["jobs.readAt"]
    assert methods["spillStore.saveText"]["candidateContract"] == "context.spill_store.save_text"
    assert all(row["conversion"] == "agent-required" for row in methods.values())


def test_questions_port_does_not_fake_timed_continuation_or_approval(tmp_path):
    # user:“继续，把 2 阶段都做完”+(只给程序化普通问答候选，计时继续/客户端接手协议继续交给 agent)。
    src = source(tmp_path, {"index.ts": "ctx.userQuestions.ask(request);ctx.userQuestions.askTimed(request);"})
    report = export_port(src, tmp_path / "out")
    methods = {row["name"]: row for row in report["questionMethods"]}
    assert methods["ask"]["candidateContract"] == "context.questions.ask"
    assert "candidateContract" not in methods["askTimed"]
    assert all(row["conversion"] == "agent-required" for row in methods.values())


def test_working_directory_candidates_require_session_revision_and_explicit_view(tmp_path):
    # user:“继续，把 2 阶段都做完”+(会话目录迁移保留原项目；新执行视图与主代理通知差异须交给agent)。
    src = source(tmp_path, {"index.ts": "ctx.workingDirectory.get(session);ctx.workingDirectory.set(session,p);ctx.workingDirectory.ensure(session);"})
    report = export_port(src, tmp_path / "out")
    methods = {row["name"]: row for row in report["filesystemMethods"]}
    for name in ("get", "set", "ensure"):
        row = methods["workingDirectory." + name]
        assert row["candidateContract"] == "context.working_directory." + name
        assert row["conversion"] == "agent-required"
        assert "suggestedContract" not in row
        assert "for_session" in row["difference"]
    assert not report["runtimeVerified"]


def test_directory_mapping_names_main_request_boundary_and_remaining_protocol_gaps(tmp_path):
    # user:“继续”+(主代理接线后更新差异，不再把已接通接口写成完全缺失)。
    src = source(tmp_path, {"index.ts": "ctx.workingDirectory.set(session,p);"})
    report = export_port(src, tmp_path / "out")
    row = next(row for row in report["filesystemMethods"] if row["name"] == "workingDirectory.set")
    assert "主代理" in row["difference"] and "请求" in row["difference"]
    assert "Git" in row["difference"] and "DSH" in row["difference"]
    assert row["conversion"] == "agent-required" and not report["runtimeVerified"]


def test_subagent_candidates_do_not_fake_agent_handles_or_activation_results(tmp_path):
    # user:“继续”+(Sunday持久成员控制只给人工候选，不伪装DSH根Agent、fork或activation结果)。
    src = source(tmp_path, {"index.ts": "ctx.subagents.startActivation(spec);ctx.subagents.sendMessage(m);ctx.subagents.listChildren(parent);ctx.agents.create(spec);"})
    report = export_port(src, tmp_path / "out")
    methods = {row["name"]: row for row in report["subagentMethods"]}
    assert methods["subagents.startActivation"]["candidateContract"] == "context.subagents"
    assert methods["subagents.sendMessage"]["candidateContract"] == "context.subagents.message"
    assert methods["subagents.listChildren"]["candidateContract"] == "context.subagents.list"
    assert "candidateContract" not in methods["agents.create"]
    assert all(row["conversion"] == "agent-required" for row in methods.values())


def test_member_interrupt_mapping_keeps_native_authority_and_resume_limits(tmp_path):
    # user:“继续”+(DSH中断只给人工近似候选，根Agent恢复不能映射成某个具名成员的恢复)。
    src = source(tmp_path, {"index.ts": "ctx.subagents.interrupt(child,authority);ctx.agents.resume(options);"})
    report = export_port(src, tmp_path / "out")
    methods = {row["name"]: row for row in report["subagentMethods"]}
    assert methods["subagents.interrupt"]["candidateContract"] == "context.subagents.interrupt"
    assert "candidateContract" not in methods["agents.resume"]
    assert methods["subagents.interrupt"]["conversion"] == "agent-required"
    assert not report["runtimeVerified"]
