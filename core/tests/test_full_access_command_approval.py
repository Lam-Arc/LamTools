"""user:“处于完全访问状态，但是它运行命令的时候弹审批了”+(完全访问下命令不再要求确认)。"""

import pytest

from lamtools_core.app.default_agent import _build_core_runtime_toolbox
from lamtools_core.tool import ToolCall
from lamtools_core.tool.approval import ApprovalGate, PermissionResolver
from lamtools_core.tool.default_toolbox import build_core_toolbox
from lamtools_core.tool.sub_agent_runner import KernelSubAgentRunner


RECORDED_COMMAND = 'grep -n "async def shutdown" -A 25 sub_agent_supervisor.py | head -35'


def test_child_toolbox_inherits_full_access_without_live_provider(tmp_path):
    runner = KernelSubAgentRunner(work_root=tmp_path, llm_client=object(),
        approval_policy="auto_approve", permission_preset="full_access")
    toolbox = runner._build_toolbox(set(), active_mode=None)
    call = ToolCall(id="c", name="run_command", arguments={"command": RECORDED_COMMAND})
    assert not toolbox.prepare_call(call).requires_approval


def test_full_access_does_not_enable_disabled_command_tool(tmp_path):
    toolbox = build_core_toolbox(work_root=tmp_path, approval_policy="auto_approve",
        permission_preset="full_access", disabled_tools={"run_command"})
    call = toolbox.prepare_call(ToolCall(id="c", name="run_command", arguments={"command": "echo ok"}))
    assert call.metadata["approval"]["blocked"]
    assert not call.requires_approval


@pytest.mark.parametrize("command", [RECORDED_COMMAND, "git reset --hard", 'python -c "print(1)"'])
def test_full_access_snapshot_settles_command_confirmation(tmp_path, command):
    gate = ApprovalGate(work_root=tmp_path, tool_permissions={"run_command": "ask_user"})
    resolver = PermissionResolver(gate)
    resolver.apply_snapshot({"permission_preset": "full_access", "approval_policy": "auto_approve",
        "active_tier": "full_edit", "tier_tools": {"full_edit": []}})
    decision = resolver.resolve("run_command", {"command": command})
    assert decision.allowed
    assert not decision.requires_approval
    assert decision.auto_approved


def test_switching_back_to_auto_or_ask_restores_command_confirmation(tmp_path):
    gate = ApprovalGate(work_root=tmp_path, tool_permissions={"run_command": "ask_user"})
    resolver = PermissionResolver(gate)
    for preset, policy in [("full_access", "auto_approve"), ("auto", "auto_approve"), ("ask", "require")]:
        resolver.apply_snapshot({"permission_preset": preset, "approval_policy": policy})
        decision = resolver.resolve("run_command", {"command": "git reset --hard"})
        assert decision.requires_approval == (preset != "full_access")


def test_live_toolbox_uses_full_access_without_running_command(tmp_path):
    snapshot = {"permission_preset": "full_access", "approval_policy": "auto_approve"}
    toolbox = build_core_toolbox(work_root=tmp_path, runtime_permissions_provider=lambda: snapshot)
    call = ToolCall(id="c", name="run_command", arguments={"command": RECORDED_COMMAND})
    assert not toolbox.prepare_call(call).requires_approval
    snapshot.update(permission_preset="auto")
    assert toolbox.prepare_call(call).requires_approval


@pytest.mark.asyncio
async def test_runtime_toolbox_preserves_initial_full_access_without_live_provider(tmp_path):
    toolbox, registry = await _build_core_runtime_toolbox(
        work_root=tmp_path, plugin_assembly={}, approval_policy="auto_approve", permission_preset="full_access",
        active_tier="full_edit", tier_tools={"full_edit": set()},
    )
    try:
        call = ToolCall(id="c", name="run_command", arguments={"command": RECORDED_COMMAND})
        assert not toolbox.prepare_call(call).requires_approval
    finally:
        if registry is not None:
            await registry.close()
