"""End-to-end QQ -> Sunday live-session guidance test with a mock provider."""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
CORE_TESTS = ROOT / "core" / "tests"
for path in (str(ROOT / "core" / "src"), str(CORE_TESTS)):
    if path not in sys.path:
        sys.path.insert(0, path)

from lamtools_core.app.live_operations import handle_turn_start_operation
from lamtools_core.app.live_plugin_service import LiveTurnService

from qqbot.protocol import InboundMessage
from qqbot.runtime import QQBotRuntime
from qqbot.session_target import SessionTargetClient

import test_core_live as core_live


class LivePluginContext:
    def __init__(self, context, *, data_dir=None) -> None:
        self.context = context
        self.event_bus = context.hub
        self.runtime_task_registry = context.runtime_task_registry
        self.work_root = "."
        self.data_dir = data_dir

    def service(self, name: str, default=None):
        if name == "live_turn_service":
            return LiveTurnService(lambda: self.context)
        if name == "session_store":
            return self.context.host.session_store
        return default


@pytest.mark.asyncio
async def test_qq_message_reaches_running_sunday_turn_as_guidance(tmp_path) -> None:
    llm = core_live.GuidedCoreLLM()
    engine, live_context = await core_live._live_core_context(tmp_path, llm)
    replies: list[str] = []

    async def on_reply(text: str) -> None:
        replies.append(text)

    try:
        started = await handle_turn_start_operation(
            request_id=1,
            params={
                "thread_id": "session-qq-live",
                "client_message_id": "client-start",
                "input": [{"type": "text", "text": "complete this"}],
            },
            context=live_context,
        )
        turn_id = started.response["result"]["events"][0]["turn_id"]
        task = live_context.runtime_task_registry.task("session-qq-live", run_id=turn_id)
        assert task is not None
        await llm.started.wait()

        client = SessionTargetClient(LivePluginContext(live_context), timeout_ms=5000)
        send_task = asyncio.create_task(
            client.send(
                session_id="session-qq-live",
                text="use the safer path",
                client_message_id="qq-guidance-1",
                on_reply=on_reply,
            )
        )

        for _ in range(100):
            if live_context.runtime_task_registry.has_guidance(
                "session-qq-live",
                run_id=turn_id,
                guidance_id="qq-guidance-1",
            ):
                break
            await asyncio.sleep(0.01)
        assert live_context.runtime_task_registry.has_guidance(
            "session-qq-live",
            run_id=turn_id,
            guidance_id="qq-guidance-1",
        )

        llm.release.set()
        result = await send_task
        await task

        assert result["ok"] is True
        assert len(llm.requests) == 2
        assert any(message.content == "use the safer path" for message in llm.requests[1].messages)
        assert "guided final" in replies
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_runtime_injects_second_qq_message_while_first_turn_runs(tmp_path) -> None:
    """The plugin must not hold the second QQ message in its merge buffer."""
    llm = core_live.GuidedCoreLLM()
    engine, live_context = await core_live._live_core_context(tmp_path, llm)
    bot_dir = tmp_path / "qqbot"
    plugin_context = LivePluginContext(live_context, data_dir=bot_dir)
    runtime = QQBotRuntime(plugin_context, data_dir=bot_dir)  # type: ignore[arg-type]
    runtime.config["targetSessionId"] = "session-qq-live"
    runtime.config["requireMention"] = False
    runtime._target = SessionTargetClient(plugin_context, timeout_ms=5000)

    class FakeOutbound:
        def __init__(self) -> None:
            self.sent: list[str] = []

        async def send_markdown(self, target, content, keyboard=None):
            self.sent.append(content)

    outbound = FakeOutbound()
    runtime._outbound = outbound  # type: ignore[assignment]

    first = InboundMessage(
        raw_event_type="C2C_MESSAGE_CREATE",
        kind="c2c",
        sender_id="user-1",
        content="complete this",
        message_id="qq-message-1",
        timestamp=str(int(time.time() * 1000)),
    )
    second = InboundMessage(
        raw_event_type="C2C_MESSAGE_CREATE",
        kind="c2c",
        sender_id="user-1",
        content="use the safer path",
        message_id="qq-message-2",
        timestamp=str(int(time.time() * 1000)),
    )

    first_task = asyncio.create_task(runtime._process_message(first))
    try:
        await asyncio.wait_for(llm.started.wait(), timeout=60)
        second_task = asyncio.create_task(runtime._process_message(second))
        turn_id = ""
        registry = live_context.runtime_task_registry
        for _ in range(200):
            turn_id = str(registry.active_run_id("session-qq-live") or "")
            if turn_id and registry.has_guidance(
                "session-qq-live",
                run_id=turn_id,
                guidance_id="qqbot:qq-message-2",
            ):
                break
            await asyncio.sleep(0.01)
        assert turn_id
        assert registry.has_guidance(
            "session-qq-live",
            run_id=turn_id,
            guidance_id="qqbot:qq-message-2",
        )

        llm.release.set()
        await asyncio.gather(first_task, second_task)
        assert len(llm.requests) == 2
        assert any(message.content == "use the safer path" for message in llm.requests[1].messages)
    finally:
        if not llm.release.is_set():
            llm.release.set()
        await engine.dispose()
