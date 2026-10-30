"""user:“继续，列好清单 逐项打勾”+(所有新增契约进入同一机器清单和agent交接，未知方法保持人工待办)。"""
from .test_dsh_compatibility import source
from lamtools_core.plugin_system.dsh_compat import export_port, load_surface


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


def test_fixed_phase2_ledger_covers_all_services_without_promoting_runtime_status():
    catalog = load_surface()
    phase2 = {row["dsh"] for row in catalog["services"] if row["phase"] == 2}
    ledger = catalog["phase2Acceptance"]
    assert set(ledger) == phase2 and len(ledger) == 71
    assert all(row["state"] in {"verified-approximation", "pending", "frontend-excluded"} for row in ledger.values())
    assert all(row["status"] in {"candidate", "gap"} for row in catalog["services"])
