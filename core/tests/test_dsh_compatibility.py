"""user:“脚本不必能处理所有问题，剩下问题交给 agent 来移植”+(验收真实转换与明确交接，禁止把扫描成功当作运行兼容)。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from lamtools_core.plugin_system.context import PluginContext
from lamtools_core.plugin_system.dsh_compat import analyze, export_port, load_surface, render_matrix
from lamtools_core.plugin_system.manifest import load_manifest
from lamtools_core.plugin_system.capabilities import read_capabilities
from lamtools_core.app.operation_catalog import OperationCatalog, OperationResult


def source(tmp_path: Path, files: dict[str, str], **metadata) -> Path:
    root = tmp_path / "original"
    root.mkdir()
    (root / "package.json").write_text(json.dumps({
        "name": "@example/dsh-demo", "version": "1.2.3", **metadata,
    }), encoding="utf-8")
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


def test_surface_has_pinned_provenance_and_no_claim_of_runtime_compatibility():
    catalog = load_surface()
    assert catalog["upstreamCommit"] == "f3803c96974ad4a94195fb97e5c637e9c2a3afe3"
    services = catalog["services"]
    assert len(services) == len({row["dsh"] for row in services}) == 107
    assert {"tools", "agents", "sessionController", "webServer", "credentials"} <= {r["dsh"] for r in services}
    assert all(r["status"] in {"candidate", "gap"} for r in services)
    points = catalog["extensionPoints"]
    assert {"agent/pre-step", "tools/result", "session", "terminal", "conversation.chat.node"} <= {r["name"] for r in points}
    root = Path(__file__).resolve().parents[2]
    for row in services:
        assert row["phase"] in {2, 3, 4}
        assert row["boundary"]
        for path in row["evidence"]:
            assert (root / path).is_file(), path
    assert (root / "agent_docs/dsh_compatibility_matrix.md").read_text(encoding="utf-8") == render_matrix()


def test_analysis_tracks_aliases_unknowns_hooks_remote_and_dynamic_access(tmp_path):
    root = source(tmp_path, {"src/index.ts": '''
export const inject = ['tools', 'futureService']
export function apply(context) {
  const ctx = context;
  ctx.tools.register({});
  ctx.on('agent/pre-step', () => {});
  ctx.remote.session.prompt({});
  ctx[serviceName].invoke();
}
'''})
    report = analyze(root)
    assert report["status"] == "needs-port"
    assert {r["name"] for r in report["services"]} >= {"tools", "futureService"}
    assert {r["name"] for r in report["events"]} == {"agent/pre-step"}
    assert report["remotes"][0]["name"] == "session.prompt"
    assert report["remotes"][0]["suggestedContract"] == "sessions.prompt"
    assert report["remotes"][0]["conversion"] == "agent-required"
    codes = {r["code"] for r in report["findings"]}
    assert {"javascript-runtime", "dynamic-access", "unknown-service"} <= codes
    assert all(r["file"] and r["line"] >= 1 for r in report["services"])
    assert not (root / "plugin.json").exists()


def test_export_static_skills_and_mcp_load_through_real_sunday_parser(tmp_path):
    root = source(tmp_path, {
        "skills/demo/SKILL.md": "---\nname: demo\ndescription: Test skill\n---\n\nHello",
        "skills/demo/reference.txt": "supporting file",
        "mcp.json": json.dumps({"mcpServers": {"demo": {"command": "node", "args": ["server.mjs"]}}}),
    })
    output = tmp_path / "ported"
    report = export_port(root, output)
    assert report["status"] == "declarative-only"
    manifest = load_manifest(output / "plugin.json")
    capabilities = read_capabilities(manifest)
    assert manifest.name == "example-dsh-demo"
    assert manifest.raw["defaultEnabled"] is False
    assert [s.name for s in capabilities.skills] == ["demo"]
    assert len(capabilities.mcp_files) == 1
    assert (output / "upstream/skills/demo/reference.txt").read_text() == "supporting file"
    assert json.loads((output / "migration-report.json").read_text(encoding="utf-8"))["runtimeVerified"] is False
    assert "agent" in (output / "PORTING.md").read_text(encoding="utf-8")


def test_source_code_preserved_but_never_registered_as_working_backend(tmp_path):
    code = "export function apply(ctx) { ctx.tools.register({name: 'echo'}) }"
    root = source(tmp_path, {"src/index.js": code})
    report = export_port(root, tmp_path / "ported")
    manifest = load_manifest(tmp_path / "ported/plugin.json")
    assert report["status"] == "needs-port"
    assert not {"backend", "runtime", "tools"}.intersection(manifest.raw)
    assert (tmp_path / "ported/upstream/src/index.js").read_text() == code
    assert any(item["code"] == "javascript-runtime" for item in report["findings"])


@pytest.mark.parametrize("target", ["original", "original/nested"])
def test_export_refuses_in_place_or_nested_output(tmp_path, target):
    root = source(tmp_path, {})
    before = (root / "package.json").read_bytes()
    with pytest.raises(ValueError):
        export_port(root, tmp_path / target)
    assert (root / "package.json").read_bytes() == before


def test_export_refuses_existing_output_and_reports_non_root_package(tmp_path):
    root = source(tmp_path, {"packages/child/package.json": '{"name":"child"}'})
    output = tmp_path / "existing"
    output.mkdir()
    with pytest.raises(FileExistsError):
        export_port(root, output)
    report = analyze(root)
    assert "nested-package" in {r["code"] for r in report["findings"]}


def test_limits_and_non_objects_fail_without_partial_export(tmp_path):
    root = source(tmp_path, {"huge.ts": "x" * 100})
    with pytest.raises(ValueError, match="limit"):
        export_port(root, tmp_path / "ported", max_bytes=50)
    assert not (tmp_path / "ported").exists()
    (root / "package.json").write_text("[]")
    with pytest.raises(ValueError, match="object"):
        analyze(root)


def test_unsupported_manifest_declarations_produce_agent_todo(tmp_path):
    root = source(tmp_path, {"cordis.patch.yml": "- insert: []"}, dsh={"bundle": {"patch": "cordis.patch.yml"}})
    report = export_port(root, tmp_path / "ported")
    assert report["status"] == "needs-port"
    assert "composition" in {r["code"] for r in report["findings"]}
    handoff = (tmp_path / "ported/PORTING.md").read_text(encoding="utf-8")
    assert "cordis.patch.yml" in handoff
    assert "验收" in handoff


def test_host_discovery_uses_live_scoped_service_and_never_serializes_values(tmp_path):
    context = PluginContext(work_root=tmp_path, services={"model_catalog": {"secret": "DO-NOT-LEAK"}})
    view = context.for_work_root(tmp_path / "other")
    view.set_scoped_service("model_catalog", "private")
    description = view.describe_host()
    assert description["contractVersion"] == 1
    assert {r["name"]: r["scope"] for r in description["services"]}["model_catalog"] == "plugin"
    assert "DO-NOT-LEAK" not in json.dumps(description)
    assert view.require_service("model_catalog") == "private"
    with pytest.raises(LookupError, match="missing"):
        view.require_service("missing")
    context.set_service("late", object())
    assert view.require_service("late") is context.service("late")
    context.set_service("none", None)
    with pytest.raises(LookupError):
        view.require_service("none")


@pytest.mark.asyncio
async def test_host_operation_calls_keep_live_catalog_availability_and_metadata(tmp_path):
    context = PluginContext(work_root=tmp_path)
    view = PluginContext(work_root=tmp_path, parent=context)
    catalog = OperationCatalog()
    available = True
    async def echo(request):
        return OperationResult(request.name, payload=request.payload, metadata=request.metadata)
    catalog.register("demo.echo", echo, availability=lambda: available)
    context.operation_catalog = catalog
    assert view.describe_host()["operations"] == ["demo.echo"]
    result = await view.operation_executor()("demo.echo", {"text": "hello"}, {"session_id": "s"})
    assert result.payload == {"text": "hello"} and result.metadata == {"session_id": "s"}
    available = False
    assert view.describe_host()["operations"] == []
    with pytest.raises(KeyError):
        await view.operation_executor()("demo.echo", {})


def test_cli_reports_review_with_exit_two_and_writes_only_when_requested(tmp_path, capsys):
    from lamtools_core.plugin_system.dsh_compat.__main__ import main
    root = source(tmp_path, {"src/plugin.js": "export function apply(ctx) {}"})
    assert main([str(root)]) == 2
    assert json.loads(capsys.readouterr().out)["runtimeVerified"] is False
    assert main([str(root), "--output", str(tmp_path / "ported")]) == 2
    assert (tmp_path / "ported/PORTING.md").is_file()
    capsys.readouterr()
    assert main([str(root), "--output", str(tmp_path / "ported")]) == 1
    assert json.loads(capsys.readouterr().err)["error"]


def test_unsupported_json_config_and_root_skill_are_not_silently_lost(tmp_path):
    root = source(tmp_path, {"SKILL.md": "# Root skill", "hooks.json": "{}"})
    report = analyze(root)
    assert report["status"] == "needs-port"
    assert {"root-skill", "declarative-review"} <= {r["code"] for r in report["findings"]}


def test_ignored_generated_dependencies_do_not_count_toward_scan_budget(tmp_path):
    root = source(tmp_path, {"node_modules/big.js": "a" * 1000, ".env": "secret", ".env.local": "secret"})
    report = export_port(root, tmp_path / "ported", max_bytes=300)
    assert report["files"] == ["package.json"]
    assert not (tmp_path / "ported/upstream/.env").exists()


def test_linked_sources_rejected_before_creating_output(tmp_path):
    root = source(tmp_path, {})
    outside = tmp_path / "outside.txt"
    outside.write_text("outside")
    try:
        (root / "linked.txt").symlink_to(outside)
    except OSError:
        pytest.skip("Windows symlink privilege unavailable")
    with pytest.raises(ValueError, match="linked source"):
        export_port(root, tmp_path / "ported")
    assert not (tmp_path / "ported").exists()


def test_duplicate_skills_fail_real_host_validation_without_partial_export(tmp_path):
    skill = "---\nname: duplicate\ndescription: Demo\n---\nBody"
    root = source(tmp_path, {"skills/one/SKILL.md": skill, "skills/two/SKILL.md": skill})
    with pytest.raises(ValueError, match="skill parser rejected"):
        export_port(root, tmp_path / "ported")
    assert not (tmp_path / "ported").exists()


def test_repository_script_runs_from_another_directory_without_pythonpath(tmp_path):
    root = source(tmp_path, {"index.js": "export function apply(ctx) { ctx.tools.register({}) }"})
    script = Path(__file__).resolve().parents[2] / "scripts/dsh_compat.py"
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, str(script), str(root)], cwd=tmp_path,
        env=env, capture_output=True, encoding="utf-8",
    )
    assert result.returncode == 2, result.stderr
    report = json.loads(result.stdout)
    assert report["services"][0]["name"] == "tools"
    assert report["runtimeVerified"] is False
    assert report["sundayHostContracts"]["ownedServices"]["version"] == 1
    assert report["sundayHostContracts"]["sessions"]["version"] == 1


def test_tool_migration_suggests_verified_subset_without_claiming_js_execution(tmp_path):
    root = source(tmp_path, {"index.js": '''export function apply(ctx) {
        ctx.tools.register({});
        ctx.on('tools/pre-execute', () => {});
        ctx.on('tools/execute', () => {});
    }'''})
    report = export_port(root, tmp_path / "ported")
    assert report["sundayHostContracts"]["tools"]["status"] == "verified-python"
    mapped = next(item for item in report["services"] if item["name"] == "tools")
    assert mapped["suggestedContract"] == "context.tools" and mapped["conversion"] == "agent-required"
    before = next(item for item in report["events"] if item["name"] == "tools/pre-execute")
    assert before["suggestedContract"] == 'context.tools.on("tools/pre-execute", callback)'
    wrapper = next(item for item in report["events"] if item["name"] == "tools/execute")
    assert "suggestedContract" not in wrapper
    assert report["runtimeVerified"] is False and report["status"] == "needs-port"
    assert "plugin_tool_extensions.md" in (tmp_path / "ported/PORTING.md").read_text(encoding="utf-8")


def test_prompt_migration_maps_supported_methods_and_preserves_unsupported_work(tmp_path):
    root = source(tmp_path, {"index.js": '''export function apply(context) {
        const ctx = context;
        ctx.systemPrompt.section({name: 'facts', text: '{{fact}}'});
        ctx.systemPrompt.variable('fact', () => 'value');
        ctx.systemPrompt.refreshContext({});
        ctx.on('system-prompt/assemble', (a) => a);
        ctx.on('system-prompt/change', () => {});
    }'''})
    report = export_port(root, tmp_path / "ported")
    assert report["sundayHostContracts"]["prompts"]["status"] == "verified-python"
    methods = {item["name"]: item for item in report["promptMethods"]}
    assert methods["section"]["suggestedContract"] == "context.prompts.section"
    assert methods["variable"]["suggestedContract"] == "context.prompts.variable"
    assert methods["refreshContext"]["conversion"] == "agent-required"
    assert "suggestedContract" not in methods["refreshContext"]
    events = {item["name"]: item for item in report["events"]}
    assert events["system-prompt/assemble"]["suggestedContract"] == "context.prompts.on_assemble"
    assert "suggestedContract" not in events["system-prompt/change"]
    handoff = (tmp_path / "ported/PORTING.md").read_text(encoding="utf-8")
    assert "plugin_prompt_extensions.md" in handoff and "refreshContext" in handoff
    assert report["runtimeVerified"] is False and report["status"] == "needs-port"


def test_command_migration_maps_registration_and_discovery_without_fake_handler_translation(tmp_path):
    root = source(tmp_path, {"index.js": '''export function apply(ctx) {
        ctx.commands.register({name: 'echo', handler: () => ({kind: 'success'})});
        ctx.commands.list(agent);
        ctx.commands.execute(agent, '/echo');
        ctx.commands.find(agent, 'echo');
        ctx.on('commands/change', () => {});
    }'''})
    report = export_port(root, tmp_path / "ported")
    assert report["sundayHostContracts"]["commands"]["status"] == "verified-python"
    methods = {item["name"]: item for item in report["commandMethods"]}
    assert methods["register"]["suggestedContract"] == "context.commands.register"
    assert methods["list"]["suggestedContract"] == "command.catalog"
    assert methods["execute"]["suggestedContract"] == "command.execute"
    assert "suggestedContract" not in methods["find"]
    assert all(item["conversion"] == "agent-required" for item in methods.values())
    assert "suggestedContract" not in report["events"][0]
    assert "plugin_command_extensions.md" in (tmp_path / "ported/PORTING.md").read_text(encoding="utf-8")
    assert report["status"] == "needs-port" and report["runtimeVerified"] is False
