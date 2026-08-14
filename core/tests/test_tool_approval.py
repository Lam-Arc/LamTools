from __future__ import annotations

from pathlib import Path

from lamtools_core.tool.approval import (
    ApprovalGate,
    classify_command,
    command_permission_decision,
)
from lamtools_core.tool.permission import ASK_USER, AUTO_ALLOW


def test_classify_command_marks_regular_and_dangerous():
    assert classify_command("echo hello") == "regular"
    assert classify_command("rm -rf /tmp/demo") == "dangerous"


def test_command_permission_decision_asks_for_dangerous_command():
    decision = command_permission_decision("shutdown /s")

    assert decision.group == "dangerous"
    assert decision.requires_approval is True
    assert decision.reason == "高危命令需要运行前确认"


def test_approval_gate_auto_allows_read_tool(tmp_path: Path):
    gate = ApprovalGate(work_root=tmp_path, tool_permissions={"read_file": AUTO_ALLOW})

    decision = gate.check("read_file", {"path": "notes.txt"})

    assert decision.allowed is True
    assert "Auto-approved" in decision.reason


def test_approval_gate_blocks_path_escape(tmp_path: Path):
    gate = ApprovalGate(work_root=tmp_path, tool_permissions={"write_file": ASK_USER})

    decision = gate.check("write_file", {"path": "../outside.txt"})

    assert decision.allowed is False
    assert decision.blocked is True
    assert "outside work_root" in decision.reason


def test_approval_gate_requires_user_for_write(tmp_path: Path):
    gate = ApprovalGate(work_root=tmp_path, tool_permissions={"write_file": ASK_USER})

    decision = gate.check("write_file", {"path": "inside.txt"})

    assert decision.allowed is False
    assert decision.requires_approval is True
    assert "requires user confirmation" in decision.reason


def test_approval_gate_applies_command_policy(tmp_path: Path):
    gate = ApprovalGate(work_root=tmp_path, tool_permissions={"run_command": ASK_USER})

    regular = gate.check("run_command", {"command": "echo ok"})
    dangerous = gate.check("run_command", {"command": "git reset --hard"})

    assert regular.allowed is True
    assert regular.reason == "Auto-approved regular command"
    assert dangerous.allowed is False
    assert dangerous.requires_approval is True


def test_shell_structure_bypasses_are_never_auto_allowed():
    """Audit 06 S1 regression: shell structure features must stay ask_user.

    The old heuristics were beaten by ``\rm -rf /``, ``$(rm -rf /)``,
    backticks, quoted command names, ``~``/``$VAR`` expansion and
    interpreter ``-c`` code.
    """
    bypasses = [
        r"\rm -rf /",
        "$(rm -rf /)",
        "`rm -rf /`",
        '"rm" -rf /',
        "cat ~/.ssh/id_rsa",
        "cat $HOME/.ssh/id_rsa",
        "echo x > ~/.bashrc",
        'python -c "import os; os.system(\'rm -rf /\')"',
        "bash -c 'rm -rf /'",
    ]
    for command in bypasses:
        decision = command_permission_decision(command)
        assert decision.requires_approval is True, f"bypass not caught: {command!r}"

    # Even with the dangerous group configured to auto_allow, shell structure
    # features must stay ask_user.
    decision = command_permission_decision("cat ~/.ssh/id_rsa", {"dangerous": "auto_allow"})
    assert decision.requires_approval is True


def test_shell_structure_does_not_flag_plain_commands():
    plain = [
        "ls -la",
        "git status",
        "npm test",
        "py -m pytest",
        "python script.py",
        "cat file.txt",
        "mkdir -p build",
    ]
    for command in plain:
        decision = command_permission_decision(command)
        assert decision.requires_approval is False, f"false positive: {command!r}"


def test_approval_gate_tier_list_does_not_short_circuit_dangerous_commands(tmp_path: Path):
    """Audit 06 S2: tier access lists must not bypass command classification."""
    gate = ApprovalGate(
        work_root=tmp_path,
        tool_permissions={"run_command": ASK_USER},
        active_tier="full_edit",
        tier_tools={"full_edit": {"run_command"}},
    )
    decision = gate.check("run_command", {"command": "rm -rf /"})
    assert decision.allowed is False
    assert decision.requires_approval is True

    allowed = gate.check("run_command", {"command": "echo ok"})
    assert allowed.allowed is True


def test_hard_block_patterns_are_case_insensitive(tmp_path: Path):
    """Audit 06 S2: Windows paths are case-insensitive; .ENV must be blocked."""
    gate = ApprovalGate(work_root=tmp_path, tool_permissions={"write_file": ASK_USER})
    decision = gate.check("write_file", {"path": ".ENV"})
    assert decision.blocked is True
    decision = gate.check("write_file", {"path": "config/.Env"})
    assert decision.blocked is True
