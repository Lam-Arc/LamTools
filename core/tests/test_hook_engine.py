from __future__ import annotations

import json
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from lamtools_core.plugins import HookDefinition, HookEngine, HookEvent, HookHandler


def make_script(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


class FakeMCPHookCaller:
    def __init__(self) -> None:
        self.calls = []

    async def call(self, tool_name, arguments):
        self.calls.append((tool_name, arguments))
        return json.dumps({"decision": "block", "reason": f"mcp blocked {arguments['tool_input']['command']}"})


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


@pytest.mark.asyncio
async def test_http_hook_can_block_tool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.delenv("NO_PROXY", raising=False)
    captured = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length") or "0")
            captured["payload"] = json.loads(self.rfile.read(length).decode("utf-8"))
            body = json.dumps({"decision": "block", "reason": "blocked by http hook"}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        hook = HookDefinition(
            id="http-hook",
            event="PreToolUse",
            matcher="run_command",
            source="project",
            source_name="project",
            config_path=tmp_path / "hooks.json",
            handler=HookHandler(type="http", url=f"http://127.0.0.1:{server.server_port}/hook", timeout=5),
            trusted=True,
            status="trusted",
        )

        decision = await HookEngine([hook]).run(
            HookEvent(event_name="PreToolUse", project_root=str(tmp_path), tool_name="run_command", tool_input={"command": "pytest"})
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert captured["payload"]["tool_name"] == "run_command"
    assert decision.decision == "block"
    assert decision.reason == "blocked by http hook"
    assert decision.audit_events[0]["status"] == "completed"


@pytest.mark.asyncio
async def test_prompt_hook_adds_context_without_external_execution(tmp_path: Path):
    hook = HookDefinition(
        id="prompt-hook",
        event="PreToolUse",
        matcher="run_command",
        source="project",
        source_name="project",
        config_path=tmp_path / "hooks.json",
        handler=HookHandler(type="prompt", prompt="Before ${TOOL_NAME}: inspect ${PROJECT_ROOT}"),
        trusted=True,
        status="trusted",
    )

    decision = await HookEngine([hook]).run(
        HookEvent(event_name="PreToolUse", project_root=str(tmp_path), tool_name="run_command", tool_input={"command": "pytest"})
    )

    assert decision.decision == "allow"
    assert f"inspect {tmp_path}" in decision.additional_context
    assert decision.audit_events[0]["status"] == "completed"


@pytest.mark.asyncio
async def test_mcp_hook_can_block_tool(tmp_path: Path):
    caller = FakeMCPHookCaller()
    hook = HookDefinition(
        id="mcp-hook",
        event="PreToolUse",
        matcher="run_command",
        source="project",
        source_name="project",
        config_path=tmp_path / "hooks.json",
        handler=HookHandler(type="mcp", tool="policy.check", timeout=5),
        trusted=True,
        status="trusted",
    )

    decision = await HookEngine([hook], mcp_caller=caller).run(
        HookEvent(event_name="PreToolUse", project_root=str(tmp_path), tool_name="run_command", tool_input={"command": "pytest"})
    )

    assert caller.calls[0][0] == "policy.check"
    assert caller.calls[0][1]["tool_input"] == {"command": "pytest"}
    assert decision.decision == "block"
    assert decision.reason == "mcp blocked pytest"
