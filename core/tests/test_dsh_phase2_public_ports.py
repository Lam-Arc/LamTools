"""user:“继续，列好清单 逐项打勾”+(所有新增契约进入同一机器清单和agent交接，未知方法保持人工待办)。"""
from .test_dsh_compatibility import source
from lamtools_core.plugin_system.dsh_compat import export_port, load_surface


def test_export_handoff_carries_known_method_differences_to_porting_agent(tmp_path):
    # user:“脚本不必能处理所有问题，剩下问题交给 agent 来移植”+(交接文档必须携带已知候选和语义差异，不能只在JSON中保留)。
    src = source(tmp_path, {"index.ts": "export function apply(ctx) { ctx.fileReferences.list(agent,q,signal); ctx.fileReferences.unknown(); }"})
    output = tmp_path / "handoff"
    report = export_port(src, output)
    known = next(row for row in report["phase2Methods"] if row["name"] == "fileReferences.list")
    unknown = next(row for row in report["phase2Methods"] if row["name"] == "fileReferences.unknown")
    handoff = (output / "PORTING.md").read_text(encoding="utf8")
    assert known["candidateContract"] in handoff and known["difference"] in handoff
    assert known["conversion"] == "agent-required" and "agent-required" in handoff
    assert unknown["difference"] in handoff and "candidateContract" not in unknown
    assert not report["runtimeVerified"]


def test_new_public_ports_are_candidates_with_explicit_semantic_limits(tmp_path):
    src = source(tmp_path, {"index.ts": """ctx.browserUse.register(name);ctx.computerUse.register(name);
ctx.lsp.query(request);ctx.lsp.registerProvider(provider);ctx.mcpResources.register(server,p);
ctx.attachments.saveFile(request);ctx.attachments.saveFileStream(request);ctx.sessionTitle.set(request);
ctx.toolResultPruner.pruneContent(blocks);ctx.toolResultPruner.pruneSession(session);
ctx.fileReferences.list(agent,q,signal);ctx.web.fetch(url);ctx.planMode.enter(session);
ctx.messageFeedback.put(request);ctx.sessionFeedback.record(request);ctx.sessionProjections.get(id);"""})
    result = export_port(src, tmp_path / "output")
    rows = {row["name"]: row for row in result["phase2Methods"]}
    for name in ("browserUse.register", "computerUse.register", "lsp.query", "attachments.saveFile", "toolResultPruner.pruneContent",
                 "fileReferences.list", "web.fetch", "planMode.enter", "messageFeedback.put", "sessionFeedback.record"):
        assert rows[name]["candidateContract"].startswith("context.")
        assert rows[name]["conversion"] == "agent-required"
        assert rows[name]["difference"]
    for name in ("attachments.saveFileStream", "toolResultPruner.pruneSession"):
        assert "candidateContract" not in rows[name]
    assert not result["runtimeVerified"]
    assert "phase2Methods" in (tmp_path / "output" / "PORTING.md").read_text(encoding="utf8")


def test_subagent_model_service_handoff_uses_persistent_admission_policy(tmp_path):
    src = source(tmp_path, {"index.ts": "ctx.subagentModelSelection.read(session);"})
    result = export_port(src, tmp_path / "output")
    row = next(row for row in result["services"] if row["name"] == "subagentModelSelection")
    assert row["suggestedContract"] == "context.subagent_models"
    assert "SDK" in row["difference"] and row["conversion"] == "agent-required"
    assert not result["runtimeVerified"]
    assert load_surface()["phase2Acceptance"]["subagentModelSelection"]["state"] == "verified-approximation"


def test_office_conversion_handoff_keeps_authorization_and_queue_differences(tmp_path):
    src = source(tmp_path, {"index.ts": "ctx.officeToPdf.convert(request);ctx.officeToPdf.render(scope,path);"})
    result = export_port(src, tmp_path / "output")
    rows = {row["name"]: row for row in result["phase2Methods"]}
    assert rows["officeToPdf.convert"]["candidateContract"] == "context.office_to_pdf.convert"
    assert rows["officeToPdf.convert"]["conversion"] == "agent-required"
    assert "candidateContract" not in rows["officeToPdf.render"]
    assert load_surface()["phase2Acceptance"]["officeToPdf"]["state"] == "verified-approximation"


def test_directory_browse_handoff_does_not_invent_a_native_dialog(tmp_path):
    src = source(tmp_path, {"index.ts": "ctx.directoryPicker.capability();"})
    result = export_port(src, tmp_path / "output")
    row = next(row for row in result["phase2Methods"] if row["name"] == "directoryPicker.capability")
    assert row["candidateContract"] == "context.directory_picker.capability"
    assert row["conversion"] == "agent-required" and "browse" in row["difference"]
    assert load_surface()["phase2Acceptance"]["directoryPicker"]["state"] == "verified-approximation"


def test_llm_extension_handoff_keeps_sdk_and_acceptance_boundary(tmp_path):
    src = source(tmp_path, {"index.ts": "ctx.deepseekLlmApiExtensions.register(field,p);ctx.deepseekLlmApiExtensions.prepare(req);"})
    result = export_port(src, tmp_path / "output")
    rows = {row["name"]: row for row in result["phase2Methods"]}
    assert rows["deepseekLlmApiExtensions.register"]["candidateContract"] == "context.llm_extensions.register"
    assert rows["deepseekLlmApiExtensions.prepare"]["candidateContract"] == "context.llm_extensions.prepare"
    assert "HTTP2xx" in rows["deepseekLlmApiExtensions.prepare"]["difference"]
    assert load_surface()["phase2Acceptance"]["deepseekLlmApiExtensions"]["state"] == "verified-approximation"


def test_ssh_handoff_does_not_imply_dsh_remote_helper_rpc(tmp_path):
    src = source(tmp_path, {"index.ts": "ctx.ssh.request(method,args,schema);ctx.ssh.connectStream(endpoint);"})
    result = export_port(src, tmp_path / "output")
    rows = [row for row in result["phase2Methods"] if row["name"].startswith("ssh.")]
    assert len(rows) == 2 and all("candidateContract" not in row for row in rows)
    service = next(row for row in result["services"] if row["name"] == "ssh")
    assert "context.ssh.connect" in service["sunday"]
    assert load_surface()["phase2Acceptance"]["ssh"]["state"] == "verified-approximation"


def test_sandbox_handoff_requires_integrated_run_and_partial_enforcement(tmp_path):
    src = source(tmp_path, {"index.ts": "ctx.sandbox.confine(argv,policy);ctx.sandboxPolicy.resolve(req);"})
    result = export_port(src, tmp_path / "output")
    rows = {row["name"]: row for row in result["phase2Methods"]}
    assert rows["sandbox.confine"]["candidateContract"] == "context.sandbox.run"
    assert "partial" in rows["sandbox.confine"]["difference"] and rows["sandbox.confine"]["conversion"] == "agent-required"
    assert rows["sandboxPolicy.resolve"]["candidateContract"] == "context.sandbox_policy.resolve"
    assert load_surface()["phase2Acceptance"]["sandbox"]["state"] == "verified-approximation"
    assert load_surface()["phase2Acceptance"]["sandboxPolicy"]["state"] == "verified-approximation"


def test_web_app_handoff_keeps_configured_url_without_browser_handoff(tmp_path):
    src=source(tmp_path,{"index.ts":"ctx.webApp.getAdvertisedUrl();"})
    result=export_port(src,tmp_path/"output")
    row=next(row for row in result["phase2Methods"] if row["name"]=="webApp.getAdvertisedUrl")
    assert row["candidateContract"]=="context.web_app.get_advertised_url"
    assert row["conversion"]=="agent-required"
    assert load_surface()["phase2Acceptance"]["webApp"]["state"]=="verified-approximation"


def test_account_handoff_requires_explicit_factory_and_callback_bridge(tmp_path):
    src=source(tmp_path,{"index.ts":"ctx.deepseekAccount.getState();ctx.deepseekAccount.startSignIn(client,origin,source);"})
    result=export_port(src,tmp_path/"output")
    rows={row["name"]:row for row in result["phase2Methods"]}
    assert rows["deepseekAccount.getState"]["factoryContract"]=="context.deepseek_account.open"
    assert rows["deepseekAccount.startSignIn"]["candidateContract"]=="account.sign_in"
    assert rows["deepseekAccount.startSignIn"]["conversion"]=="agent-required"
    assert load_surface()["phase2Acceptance"]["deepseekAccount"]["state"]=="verified-approximation"


def test_fixed_phase2_ledger_covers_all_services_without_promoting_runtime_status():
    catalog = load_surface()
    phase2 = {row["dsh"] for row in catalog["services"] if row["phase"] == 2}
    ledger = catalog["phase2Acceptance"]
    assert set(ledger) == phase2 and len(ledger) == 71
    assert all(row["state"] in {"verified-approximation", "pending", "frontend-excluded"} for row in ledger.values())
    assert all(row["status"] in {"candidate", "gap"} for row in catalog["services"])


def test_unattended_native_ports_keep_factory_privacy_and_transaction_boundaries(tmp_path):
    src = source(tmp_path, {"index.ts": """ctx.agents.create(spec);ctx.storageDomain.open(spec);
ctx.otel.createEventReporter(config);ctx.productTelemetry.emit(record);ctx.sessionTelemetry.emit(record);
ctx.settings.validate(values);ctx.workspaceChanges.snapshot();ctx.agentLoop.create(id);"""})
    result = export_port(src, tmp_path / "output")
    rows = {row["name"]: row for row in result["phase2Methods"]}
    assert rows["agents.create"]["candidateContract"] == "context.agents.create"
    assert rows["storageDomain.open"]["candidateContract"] == "context.storage_domain.open"
    assert rows["settings.validate"]["candidateContract"] == "context.settings.validate"
    assert rows["workspaceChanges.snapshot"]["candidateContract"] == "context.workspace_changes.snapshot"
    assert rows["agentLoop.create"]["candidateContract"] == "context.agent_loop.create"
    assert rows["productTelemetry.emit"]["factoryContract"] == "context.otel.create_event_reporter"
    assert rows["sessionTelemetry.emit"]["factoryContract"] == "context.otel.create_session_reporter"
    assert all(row["conversion"] == "agent-required" for row in rows.values())
    assert not result["runtimeVerified"]
