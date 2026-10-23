"""The active plugin agent decides the approval stance for gated calls."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from lamtools_core.app.base_agent import CoreBaseAgentConfig, CoreBaseAgentKit
from lamtools_core.plugin_system.agent import PluginAgentSpec
from lamtools_core.tool.approval import ApprovalGate
from lamtools_core.tool.permission import ASK_USER, AUTO_ALLOW, HARD_BLOCK


def make_gate(tmp_path: Path, plugin_approval: str | None) -> ApprovalGate:
    return ApprovalGate(
        work_root=tmp_path,
        tool_permissions={
            "write_file": ASK_USER,
            "read_file": AUTO_ALLOW,
            "dangerous_tool": HARD_BLOCK,
        },
        plugin_approval=plugin_approval,
    )


def test_auto_skips_the_question_for_gated_calls(tmp_path: Path) -> None:
    decision = make_gate(tmp_path, "auto").check("write_file", {"path": "notes.md"})

    assert decision.allowed is True
    assert decision.requires_approval is False
    assert decision.auto_approved is True


def test_block_refuses_gated_calls(tmp_path: Path) -> None:
    decision = make_gate(tmp_path, "block").check("write_file", {"path": "notes.md"})

    assert decision.allowed is False
    assert decision.blocked is True
    assert decision.requires_approval is False


def test_ask_keeps_the_normal_question(tmp_path: Path) -> None:
    decision = make_gate(tmp_path, "ask").check("write_file", {"path": "notes.md"})

    assert decision.allowed is False
    assert decision.requires_approval is True


def test_hard_blocks_survive_auto_approval(tmp_path: Path) -> None:
    decision = make_gate(tmp_path, "auto").check("dangerous_tool")

    assert decision.allowed is False
    assert decision.blocked is True


def test_read_only_calls_are_untouched(tmp_path: Path) -> None:
    decision = make_gate(tmp_path, "block").check("read_file", {"path": "notes.md"})

    assert decision.allowed is True
    assert decision.blocked is False


def test_active_plugin_agent_sets_the_gate_stance(tmp_path: Path) -> None:
    kit = object.__new__(CoreBaseAgentKit)
    kit.work_root = tmp_path.resolve()
    kit.config = CoreBaseAgentConfig(
        instructions="BASE",
        active_mode="demo:focus",
        model_id="test-model",
    )
    gate = make_gate(tmp_path, None)
    kit.toolbox = SimpleNamespace(
        skill_index=lambda: "",
        mcp_caller=None,
        agent_tool_whitelist=None,
        approval_gate=gate,
    )
    kit.plugin_agents = [
        PluginAgentSpec(plugin="demo", scope="mode", mode="focus", approval="block")
    ]
    kit.plugin_context_files = []
    kit._subagent_guide_cache = ""
    kit._subagent_roles_cache = ""
    kit._subagent_strategy_cache = ""
    kit._delegation_strategy = "allowed"

    kit._compose_system_prompt(
        SimpleNamespace(session_id="s1", metadata={}),
        study_mode=False,
        effective_instructions=kit.config.instructions,
    )

    assert gate.plugin_approval == "block"
    assert gate.check("write_file", {"path": "notes.md"}).blocked is True
