from .test_dsh_compatibility import source
from lamtools_core.plugin_system.dsh_compat import export_port


def test_workspace_files_remotes_map_to_scoped_sdk_candidates_without_guessing_unknown_methods(tmp_path):
    # user:“迁移脚本、机器清单与文档同步”+(固定workspaceFiles Remote方法交给已有受限文件SDK候选，不猜未声明方法)。
    calls = " ".join(
        f"ctx.remote.workspaceFiles.{method}();"
        for method in ("stat", "read", "readBytes", "list", "changes", "write")
    )
    root = source(tmp_path, {"index.ts": f"export function apply(ctx) {{ {calls} }}"})
    report = export_port(root, tmp_path / "ported-workspace-files")
    rows = {row["name"]: row for row in report["remotes"]}

    expected = {
        "workspaceFiles.stat": "stat",
        "workspaceFiles.read": "read",
        "workspaceFiles.readBytes": "read_bytes",
        "workspaceFiles.list": "list",
        "workspaceFiles.changes": "changes",
    }
    for name, method in expected.items():
        row = rows[name]
        assert row["conversion"] == "agent-required"
        assert row["suggestedContract"] == f"context.workspace_files.{method}"
        assert "workspaceFileScopeId" in row["difference"]
        assert "session_id" in row["difference"]
    assert "multipart" in rows["workspaceFiles.readBytes"]["difference"]
    assert "ndjson" in rows["workspaceFiles.changes"]["difference"]

    unknown = rows["workspaceFiles.write"]
    assert unknown["conversion"] == "agent-required"
    assert "suggestedContract" not in unknown
    assert report["runtimeVerified"] is False
