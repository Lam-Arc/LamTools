"""Generic channel runtime: turn loop, streaming, approvals, commands, sessions."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from lamtools_core.channel import (
    ChannelCommand,
    ChannelMessage,
    ChannelRuntime,
    ChannelTarget,
)


class FakeStream:
    def __init__(self) -> None:
        self.updates: list[str] = []
        self.completed = 0
        self.should_fallback = False

    async def update(self, text: str) -> None:
        self.updates.append(text)

    async def complete(self) -> None:
        self.completed += 1


class FakeAdapter:
    name = "test"

    def __init__(self) -> None:
        self.sent: list[tuple] = []
        self.files: list[tuple] = []
        self.streams: list[FakeStream] = []
        self.approvals: list[dict] = []
        self.questions: list[dict] = []
        self.interactions: list[object] = []
        self.acks: list[object] = []
        self.approval_decision = "allow"
        self.question_answer = {"selected": ["A"]}

    async def send_text(self, target, text, keyboard=None):
        self.sent.append((target, text, keyboard))
        return {"id": "sent"}

    async def send_file(self, target, path, file_name=""):
        self.files.append((target, path, file_name))
        return {"outcome": "sent"}

    def open_stream(self, target):
        stream = FakeStream()
        self.streams.append(stream)
        return stream

    async def ask_approval(self, session, pending, timeout_ms):
        self.approvals.append(pending)
        return self.approval_decision

    async def ask_questions(self, session, pending, timeout_ms):
        self.questions.append(pending)
        return self.question_answer

    def handle_interaction(self, event):
        self.interactions.append(event)
        return True

    def handle_text(self, scope, peer_id, text):
        return False

    def cancel_pending(self, session):
        return None

    def acknowledge_interaction(self, event):
        self.acks.append(event)


class FakeRunner:
    def __init__(self, results=None) -> None:
        self.results = list(results or [])
        self.calls: list[dict] = []
        self.resume_calls: list[tuple[str, dict]] = []
        self.parent_event_sink = None

    async def _emit(self, name, agent, **payload):
        if self.parent_event_sink is not None:
            await self.parent_event_sink(
                SimpleNamespace(name=name, payload={**payload, "sub_agent": {"agent": agent}})
            )

    async def run(self, **kwargs):
        self.calls.append(kwargs)
        agent = kwargs["agent"]
        if not self.results:
            await self._emit("runtime.reply_delta", agent, content="hel")
            await self._emit("runtime.reply_delta", agent, content="lo")
            await self._emit("runtime.reply", agent, content="hello")
            await self._emit("runtime.done", agent)
            return SimpleNamespace(session_id="s1", decision="done", message="hello", error="", pending_approval={})
        return self.results.pop(0)

    async def resume_approved(self, **kwargs):
        self.resume_calls.append(("approved", kwargs))
        await self._emit("runtime.done", kwargs["agent"])
        return SimpleNamespace(session_id="s1", decision="done", message="ok", error="", pending_approval={})

    async def resume_question(self, **kwargs):
        self.resume_calls.append(("question", kwargs))
        await self._emit("runtime.done", kwargs["agent"])
        return SimpleNamespace(session_id="s1", decision="done", message="ok", error="", pending_approval={})

    async def compact(self, session_id):
        return {"status": "compacted", "compacted_messages": 2, "before_tokens": 10, "after_tokens": 5}

    async def fork(self, session_id, new_agent_name):
        return {"session_id": f"prefix:sub:{new_agent_name}", "agent": new_agent_name, "history_count": 2}

    async def session_info(self, session_id):
        return {"message_count": 2, "usage": {"input": 1, "output": 2, "cacheRead": 0, "cacheWrite": 0}}


class FakeContext:
    def service(self, name, default=None):
        return None


def _message(text: str, message_id: str = "m1") -> ChannelMessage:
    target = ChannelTarget("c2c", "u1", message_id)
    return ChannelMessage(
        channel="test",
        scope="c2c",
        peer_id="u1",
        sender_id="u1",
        text=text,
        message_id=message_id,
        target=target,
    )


def _runtime(tmp_path: Path, adapter=None, runner=None, config=None):
    return ChannelRuntime(
        adapter=adapter or FakeAdapter(),
        context=FakeContext(),
        config=config or {"streaming": True, "textChunkLimit": 100},
        data_dir=tmp_path,
        work_root=tmp_path,
        logger=logging.getLogger("test"),
        runner=runner or FakeRunner(),
    )


async def test_runtime_streams_and_replies(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    runtime = _runtime(tmp_path, adapter)
    await runtime.handle_message(_message("hi"))
    assert adapter.streams
    assert adapter.streams[0].updates[-1] == "hello"
    assert adapter.streams[0].completed == 1
    assert adapter.sent == []
    session = runtime.get("c2c", "u1")
    assert session is not None
    assert session.session_id == "s1"


async def test_runtime_commands_bypass_the_agent(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    runner = FakeRunner()
    runtime = _runtime(tmp_path, adapter, runner)
    runtime.register_command(ChannelCommand(("ping",), "ping", lambda ctx: "pong"))
    await runtime.handle_message(_message("/ping"))
    assert adapter.sent and adapter.sent[0][1] == "pong"
    assert runner.calls == []


async def test_runtime_approval_allow(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    runner = FakeRunner(
        [
            SimpleNamespace(
                session_id="s1",
                decision="wait",
                message="",
                error="",
                pending_approval={
                    "tool_call": {"id": "c1", "name": "run_command", "arguments": {"command": "echo hi"}},
                    "request_payload": {"message": "允许吗"},
                },
            )
        ]
    )
    runtime = _runtime(tmp_path, adapter, runner)
    await runtime.handle_message(_message("hi"))
    assert adapter.approvals
    assert runner.resume_calls[0][0] == "approved"


async def test_runtime_question_answer(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    runner = FakeRunner(
        [
            SimpleNamespace(
                session_id="s1",
                decision="wait",
                message="",
                error="",
                pending_approval={
                    "request_kind": "question",
                    "tool_call": {
                        "id": "c1",
                        "name": "question",
                        "arguments": {"questions": [{"question": "Pick", "options": [{"label": "A"}]}]},
                    },
                    "request_payload": {"request_id": "q1", "message": "Pick"},
                },
            )
        ]
    )
    runtime = _runtime(tmp_path, adapter, runner)
    await runtime.handle_message(_message("hi"))
    assert adapter.questions
    assert runner.resume_calls[0][0] == "question"
    assert runner.resume_calls[0][1]["answer"] == "A"


async def test_runtime_session_operations(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    runner = FakeRunner()
    runtime = _runtime(tmp_path, adapter, runner)
    await runtime.handle_message(_message("hi"))
    session = runtime.get("c2c", "u1")
    assert session is not None
    info = await runtime.session_info(session)
    assert info["sessionId"] == "s1"
    compact = await runtime.compact(session)
    assert compact["status"] == "compacted"
    old_agent = session.agent_name
    forked = await runtime.fork(session, "branch")
    assert forked["agent"] == "branch"
    assert runtime.by_agent("branch") is session
    assert runtime.by_agent(old_agent) is None
    runtime.reset(session)
    assert session.session_id == ""
    assert runtime.export_markdown(session).startswith("# 会话导出")


async def test_runtime_merges_messages_for_the_same_peer(tmp_path: Path) -> None:
    adapter = FakeAdapter()

    class SlowRunner(FakeRunner):
        async def run(self, **kwargs):
            self.calls.append(kwargs)
            await asyncio.sleep(0.05)
            return SimpleNamespace(session_id="s1", decision="done", message="ok", error="", pending_approval={})

    runner = SlowRunner()
    runtime = _runtime(tmp_path, adapter, runner, config={"streaming": False, "textChunkLimit": 100})
    await asyncio.gather(
        runtime.handle_message(_message("one", "m1")),
        runtime.handle_message(_message("two", "m2")),
        runtime.handle_message(_message("three", "m3")),
    )
    assert len(runner.calls) == 2
    assert runner.calls[0]["task"] == "one"
    assert "two" in runner.calls[1]["task"]
    assert "three" in runner.calls[1]["task"]


async def test_runtime_interaction_delegates_to_adapter(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    runtime = _runtime(tmp_path, adapter)
    event = {"id": "e1", "data": {}}
    assert await runtime.handle_interaction(event)
    assert adapter.interactions == [event]
    assert adapter.acks == [event]


async def test_runtime_prefers_the_preset_compaction_service(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    runner = FakeRunner()
    seen: list[str] = []

    class Service:
        async def compact_now(self, session_id: str) -> dict:
            seen.append(session_id)
            return {"status": "service-compacted"}

    runner.preset_service = lambda name, preset_id="": Service() if name == "compaction" else None
    runtime = _runtime(tmp_path, adapter, runner)
    await runtime.handle_message(_message("hi"))
    session = runtime.get("c2c", "u1")
    assert session is not None

    result = await runtime.compact(session)

    assert result["status"] == "service-compacted"
    assert seen == ["s1"]


async def test_runtime_deduplicates_tool_artifacts_and_deliverables(tmp_path: Path) -> None:
    adapter = FakeAdapter()

    class DeliverableRunner(FakeRunner):
        async def run(self, **kwargs):
            agent = kwargs["agent"]
            file = {"kind": "file", "uri": "C:/tmp/report.txt", "metadata": {"path": "C:/tmp/report.txt"}}
            await self._emit(
                "runtime.tool.finished",
                agent,
                call_id="c1",
                tool_name="make_report",
                status="ok",
                content="",
                error="",
                artifacts=[file],
                metadata={},
            )
            await self._emit("deliverables/presented", agent, files=[file])
            await self._emit("runtime.done", agent)
            return SimpleNamespace(session_id="s1", decision="done", message="", error="", pending_approval={})

    runtime = _runtime(tmp_path, adapter, DeliverableRunner())
    await runtime.handle_message(_message("hi"))

    assert len(adapter.files) == 1
    assert adapter.files[0][1] == "C:/tmp/report.txt"
