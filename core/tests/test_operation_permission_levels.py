"""user:“工具权限是改成 123 级，不一棒子按工具类型打死了”+(验收按操作分级)。"""
import json

import pytest

from lamtools_core.tool.approval import ApprovalGate
from lamtools_core.tool.permission import AUTO_ALLOW, ASK_USER, HARD_BLOCK


@pytest.mark.parametrize("preset,limit", [("ask", 1), ("auto", 2), ("full_access", 3)])
@pytest.mark.parametrize("command,level", [("git status --short", 1), ("npm run build", 2), ("git reset --hard", 3)])
def test_each_command_is_classified_by_operation(tmp_path, preset, limit, command, level):
    gate = ApprovalGate(work_root=tmp_path, tool_permissions={"run_command": ASK_USER}, permission_preset=preset)
    decision = gate.check("run_command", {"command": command})
    assert decision.level == level
    assert decision.allowed == (level <= limit)
    assert decision.requires_approval == (level > limit)


@pytest.mark.parametrize("tier,cap", [("read_only", 1), ("limited_edit", 2), ("full_edit", 3)])
def test_capability_is_a_number_not_a_tool_name_list(tmp_path, tier, cap):
    gate = ApprovalGate(work_root=tmp_path, tool_permissions={"run_command": ASK_USER}, active_tier=tier,
                        tier_tools={"read_only": set(), "limited_edit": set(), "full_edit": set()}, permission_preset="full_access")
    assert gate.check("run_command", {"command": "git status"}).allowed
    assert gate.check("run_command", {"command": "npm run build"}).blocked == (cap < 2)
    assert gate.check("run_command", {"command": "git reset --hard"}).blocked == (cap < 3)


def test_same_internal_tool_has_different_action_levels(tmp_path):
    gate = ApprovalGate(work_root=tmp_path, tool_permissions={"arrange": ASK_USER}, permission_preset="ask")
    assert gate.check("arrange", {"action": "list"}).level == 1
    assert gate.check("arrange", {"action": "list"}).allowed
    assert gate.check("arrange", {"action": "create"}).level == 3
    assert gate.check("arrange", {"action": "create"}).requires_approval


def test_hard_blocks_cannot_be_promoted_by_full_mode(tmp_path):
    gate = ApprovalGate(work_root=tmp_path, tool_permissions={"write_file": ASK_USER, "disabled": HARD_BLOCK}, permission_preset="full_access")
    assert gate.check("disabled", {}).blocked
    assert gate.check("write_file", {"path": ".env", "content": "x"}).blocked


def test_fourth_level_is_data_and_full_stays_at_three(tmp_path):
    gate = ApprovalGate(work_root=tmp_path, tool_permissions={"custom": AUTO_ALLOW}, permission_preset="full_access",
                        operation_levels={"custom": 4}, available_level=4)
    decision = gate.check("custom", {})
    assert decision.level == 4 and decision.requires_approval


def test_undeclared_plugin_tool_defaults_to_three(tmp_path):
    gate = ApprovalGate(work_root=tmp_path, tool_permissions={"new_plugin_tool": AUTO_ALLOW}, permission_preset="auto")
    assert gate.check("new_plugin_tool", {}).level == 3
    assert gate.check("new_plugin_tool", {}).requires_approval


@pytest.mark.parametrize("command", ["git status; rm a", "find . -delete", "rg --pre evil text", "git diff --output=result.txt", "python -c 'print(1)'", "echo $(whoami)"])
def test_command_composition_cannot_hide_a_write(tmp_path, command):
    gate = ApprovalGate(work_root=tmp_path, tool_permissions={"run_command": ASK_USER}, permission_preset="auto")
    assert gate.check("run_command", {"command": command}).level == 3


def test_mcp_defaults_to_three_and_plugin_can_declare_each_action(tmp_path):
    from lamtools_core.mcp import MCPToolRegistry
    from lamtools_core.mcp.command_service import MCPCommandService
    config = tmp_path / "mcp.json"
    config.write_text(json.dumps({"mcpServers": {"sample": {"command": "never-launch",
        "toolLevels": {"read": 1, "write": 2, "records": {"default": 3, "actions": {"list": 1, "update": 2}}}}}}), encoding="utf8")
    service = MCPCommandService(MCPToolRegistry(tmp_path, config_files=[config]))
    def command(tool, args="{}"):
        return f"core mcp call --tool mcp__sample__{tool} --arguments '{args}'"
    assert service.level_for_command(command("unknown")) == 3
    assert service.level_for_command(command("read")) == 1
    assert service.level_for_command(command("write")) == 2
    assert service.level_for_command(command("records", '{"action":"list"}')) == 1
    assert service.level_for_command(command("records", '{"action":"update"}')) == 2
    assert service.level_for_command(command("records", '{"action":"delete"}')) == 3


def test_mcp_grade_is_used_by_the_real_toolbox_gate(tmp_path):
    from lamtools_core.tool.default_toolbox import build_core_toolbox
    from lamtools_core.tool import ToolCall
    from lamtools_core.mcp import MCPToolRegistry
    from lamtools_core.mcp.command_service import MCPCommandService
    config = tmp_path / "mcp.json"
    config.write_text(json.dumps({"mcpServers": {"sample": {"command": "never-launch", "toolLevels": {"read": 1}}}}), encoding="utf8")
    service = MCPCommandService(MCPToolRegistry(tmp_path, config_files=[config]))
    toolbox = build_core_toolbox(work_root=tmp_path, mcp_service=service, permission_preset="ask")
    read = toolbox.prepare_call(ToolCall(id="r", name="run_command", arguments={"command": "core mcp call --tool mcp__sample__read --arguments '{}'"}))
    write = toolbox.prepare_call(ToolCall(id="w", name="run_command", arguments={"command": "core mcp call --tool mcp__sample__write --arguments '{}'"}))
    assert not read.requires_approval
    assert write.requires_approval


def test_mcp_server_level_and_zero_are_enforced(tmp_path):
    from lamtools_core.mcp.schemas import MCPServerConfig
    server = MCPServerConfig(name="sample", command="unused", level=2,
                             tool_levels={"disabled": 0, "danger": 3})
    assert server.level_for_tool("new") == 2
    assert server.level_for_tool("disabled") == 0
    assert server.level_for_tool("danger") == 3
    with pytest.raises(ValueError):
        MCPServerConfig(name="bad", command="unused", tool_levels={"read": True})


def test_profile_auto_cannot_implicitly_grant_level_three(tmp_path):
    from lamtools_core.tool.default_toolbox import build_core_toolbox
    from lamtools_core.plugin_system.profiles import ProfileSpec, apply_profile
    from lamtools_core.tool import ToolCall
    toolbox = build_core_toolbox(work_root=tmp_path, permission_preset="ask")
    apply_profile(toolbox, ProfileSpec("sample:duty", "sample", "duty", tools=("run_command",)))
    call = toolbox.prepare_call(ToolCall(id="delete", name="run_command", arguments={"command": "git reset --hard"}))
    assert call.requires_approval


def test_mcp_run_level_comes_from_the_target_tool(tmp_path):
    gate = ApprovalGate(
        work_root=tmp_path,
        tool_permissions={"mcp": AUTO_ALLOW},
        permission_preset="ask",
        mcp_call_level=lambda name, args: 1 if name.endswith("__read") else 3,
    )
    read = gate.check("mcp", {"action": "run", "tool_name": "mcp__sample__read", "arguments": {}})
    write = gate.check("mcp", {"action": "run", "tool_name": "mcp__sample__write", "arguments": {}})
    assert read.level == 1 and read.allowed
    assert write.level == 3 and write.requires_approval
    # Queries stay level 1 and never inherit the target tool's severity.
    assert gate.check("mcp", {"action": "schema", "tool_name": "mcp__sample__write"}).allowed


def test_profile_approved_tools_only_skip_confirmation_for_their_targets(tmp_path):
    from lamtools_core.tool.default_toolbox import build_core_toolbox
    from lamtools_core.plugin_system.profiles import ProfileSpec, apply_profile
    from lamtools_core.tool import ToolCall

    class Service:
        def level_for_tool(self, name, arguments):
            return 3

        def check_tool_allowed(self, name):
            return None

        async def execute_tool(self, name, arguments):
            return "ok"

    toolbox = build_core_toolbox(work_root=tmp_path, mcp_service=Service(), permission_preset="ask")
    apply_profile(
        toolbox,
        ProfileSpec(
            "sample:duty",
            "sample",
            "duty",
            tools=("mcp",),
            approved_tools=("mcp__sample__write",),
        ),
    )
    approved = toolbox.prepare_call(
        ToolCall(id="a", name="mcp", arguments={"action": "run", "tool_name": "mcp__sample__write", "arguments": {}})
    )
    other = toolbox.prepare_call(
        ToolCall(id="b", name="mcp", arguments={"action": "run", "tool_name": "mcp__sample__delete", "arguments": {}})
    )
    assert not approved.requires_approval
    assert other.requires_approval


def test_consider_mode_uses_operation_cap_for_commands(tmp_path):
    from lamtools_core.tool.default_toolbox import build_core_toolbox
    from lamtools_core.tool.loadtools import default_load_tools
    from lamtools_core.tool import ToolCall
    toolbox = build_core_toolbox(work_root=tmp_path, permission_preset="full_access", active_mode="consider", load_tools=default_load_tools())
    assert "run_command" in {tool["function"]["name"] for tool in toolbox.model_tools()}
    read = toolbox.prepare_call(ToolCall(id="r", name="run_command", arguments={"command": "git status"}))
    write = toolbox.prepare_call(ToolCall(id="w", name="run_command", arguments={"command": "npm run build"}))
    assert not read.requires_approval and not read.metadata["approval"]["blocked"]
    assert write.metadata["approval"]["blocked"]


def test_full_mode_does_not_erase_read_only_capability():
    from lamtools_core.app.runtime_permissions import resolve_permission_preset
    resolved = resolve_permission_preset(preset="full_access", base_tier="read_only", base_allow_access_outside_workdir=False)
    assert resolved.active_tier == "read_only"
    assert resolved.to_dict()["auto_approve_level"] == 3
    assert resolved.to_dict()["available_level"] == 1


def test_switching_to_auto_does_not_release_a_level_three_approval():
    from lamtools_core.tool.operation_levels import pending_auto_approvable
    call = {"name": "run_command", "arguments": {"command": "git reset --hard"},
            "metadata": {"approval": {"level": 3, "available_level": 3}}}
    assert not pending_auto_approvable(call, "auto")
    assert pending_auto_approvable(call, "full_access")
    call["metadata"]["approval"]["available_level"] = 1
    assert not pending_auto_approvable(call, "full_access")
