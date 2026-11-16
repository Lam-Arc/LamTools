"""Migration handoff for the fixed upstream global session control stream."""

from .test_dsh_compatibility import source
from lamtools_core.plugin_system.dsh_compat import export_port


def test_session_control_remote_is_not_mapped_to_single_session_projection_polling(tmp_path):
    # user:“剩下问题交给 agent 来移植”+(全局基线与逐项替换流没有Sunday原宿主事件权威时必须保留差异，不映射成单会话轮询)。
    root = source(tmp_path, {
        "index.ts": "export function apply(ctx) { ctx.remote.session.control({}); ctx.remote.session.delete({}); }",
    })
    report = export_port(root, tmp_path / "ported-session-control")
    methods = {row["name"]: row for row in report["remotes"]}
    method = methods["session.control"]

    assert method["conversion"] == "agent-required"
    assert "suggestedContract" not in method
    assert "host-wide" in method["difference"].lower()
    assert "context.session_controller.observe_projections" in method["difference"]
    assert "资源授权" in method["difference"]

    # user:“剩下问题交给 agent 来移植”+(固定上游没有session.delete Remote，迁移不得把全局Core删除误当成安全等价)。
    unknown = methods["session.delete"]
    assert unknown["conversion"] == "agent-required"
    assert "suggestedContract" not in unknown
    assert "核对" in unknown["difference"]
