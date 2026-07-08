from __future__ import annotations

from pathlib import Path

import pytest

from lamtools_core.plugins import HookDefinition, HookEngine, HookEvent, HookHandler


def make_script(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


@pytest.mark.asyncio
async def test_command_hook_can_block_tool(tmp_path: Path):
    script = tmp_path / "block.py"
    make_script(script, """
import json, sys
_payload = json.load(sys.stdin)
print(json.dumps({"decision": "block", "reason": "blocked by policy"}))
""".strip())
    hook = HookDefinition(
        id="hook-1",
        event="PreToolUse",
        matcher="run_command",
        source="project",
        source_name="project",
        config_path=tmp_path / "hooks.json",
        handler=HookHandler(type="command", command=f"python {script}", timeout=5),
        trusted=True,
        status="trusted",
    )

    decision = await HookEngine([hook]).run(HookEvent(
        event_name="PreToolUse",
        project_root=str(tmp_path),
        tool_name="run_command",
        tool_input={"command": "pytest"},
    ))

    assert decision.decision == "block"
    assert decision.reason == "blocked by policy"
    assert decision.audit_events[0]["hook_id"] == "hook-1"


@pytest.mark.asyncio
async def test_command_hook_can_update_tool_input(tmp_path: Path):
    script = tmp_path / "rewrite.py"
    make_script(script, """
import json, sys
payload = json.load(sys.stdin)
tool_input = payload["tool_input"]
tool_input["command"] = "py -3.14 -m pytest"
print(json.dumps({"updatedInput": tool_input}))
""".strip())
    hook = HookDefinition(
        id="hook-1",
        event="PreToolUse",
        matcher="run_command",
        source="project",
        source_name="project",
        config_path=tmp_path / "hooks.json",
        handler=HookHandler(type="command", command=f"python {script}", timeout=5),
        trusted=True,
        status="trusted",
    )

    decision = await HookEngine([hook]).run(HookEvent(
        event_name="PreToolUse",
        project_root=str(tmp_path),
        tool_name="run_command",
        tool_input={"command": "pytest"},
    ))

    assert decision.updated_input == {"command": "py -3.14 -m pytest"}


@pytest.mark.asyncio
async def test_untrusted_hook_does_not_execute(tmp_path: Path):
    script = tmp_path / "block.py"
    make_script(script, "print('should not run')")
    hook = HookDefinition(
        id="hook-1",
        event="PreToolUse",
        matcher="*",
        source="project",
        source_name="project",
        config_path=tmp_path / "hooks.json",
        handler=HookHandler(type="command", command=f"python {script}", timeout=5),
        trusted=False,
        status="pending_review",
    )

    decision = await HookEngine([hook]).run(HookEvent(event_name="PreToolUse", tool_name="run_command"))

    assert decision.decision == "allow"
    assert decision.audit_events[0]["status"] == "skipped_untrusted"
