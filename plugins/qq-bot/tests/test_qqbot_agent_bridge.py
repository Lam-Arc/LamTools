"""Agent bridge: approval/question continuation, prompt waterfall and presets."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from qqbot.agent_bridge import AgentBridge
from qqbot.channels import ApprovalChannel, QuestionChannel
from qqbot.config import normalize
from qqbot.protocol import ReplyTarget
from qqbot.store import PrefsStore


class FakeRunner:
    def __init__(self, results):
        self.results = list(results)
        self.calls: list[dict] = []
        self.resume_calls: list[tuple[str, dict]] = []
        self.parent_event_sink = None

    async def run(self, **kwargs):
        self.calls.append(kwargs)
        return self.results.pop(0)

    async def resume_approved(self, **kwargs):
        self.resume_calls.append(("approved", kwargs))
        return self.results.pop(0)

    async def resume_question(self, **kwargs):
        self.resume_calls.append(("question", kwargs))
        return self.results.pop(0)

    async def resume_interrupted(self, **kwargs):
        return SimpleNamespace(decision="done", message="")


class FakeContext:
    def __init__(self, services):
        self.services = dict(services)

    def service(self, name, default=None):
        return self.services.get(name, default)


class FakeWaterfall:
    def __init__(self):
        self.handlers = []

    def register(self, handler, *, plugin="", order=100):
        self.handlers.append(handler)

        def unregister():
            if handler in self.handlers:
                self.handlers.remove(handler)

        return unregister


def _bridge(tmp_path: Path, runner, *, waterfall=None, presets=None) -> AgentBridge:
    services = {"sub_agent_runner_factory": lambda: runner}
    if waterfall is not None:
        services["system_prompt_waterfall"] = waterfall
    if presets is not None:
        services["agent_presets"] = presets
    context = FakeContext(services)
    return AgentBridge(
        context=context,
        config=normalize({"appId": "app"}),
        data_dir=tmp_path,
        work_root=tmp_path,
        logger=logging.getLogger("test"),
        approvals=ApprovalChannel(logger=logging.getLogger("test")),
        questions=QuestionChannel(logger=logging.getLogger("test")),
        on_event=_noop,
    )


async def _noop(event) -> None:
    return None


async def _wait_for(predicate, attempts=100):
    for _ in range(attempts):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition was not reached")


def _session(bridge: AgentBridge, sent: list[str]):
    async def sender(target, content, keyboard=None):
        sent.append(content)
        return None

    return bridge.get_or_create(
        scope="c2c",
        peer_id="u1",
        sender_id="u1",
        reply_target=ReplyTarget("c2c", "u1", "m1"),
        sender=sender,
    )


async def test_bridge_approval_allow(tmp_path: Path) -> None:
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
            ),
            SimpleNamespace(session_id="s1", decision="done", message="done", error="", pending_approval={}),
        ]
    )
    bridge = _bridge(tmp_path, runner)
    sent: list[str] = []
    session = _session(bridge, sent)
    task = asyncio.create_task(bridge.run(session, "hi"))
    await _wait_for(lambda: bool(bridge.approvals.pending))
    matched = bridge.approvals.handle_interaction(
        {
            "user_openid": "u1",
            "data": {"resolved": {"button_data": '{"t":"approval","d":"allow"}'}},
        },
        bridge,
    )
    assert matched
    result = await task
    assert result.decision == "done"
    assert runner.resume_calls[0][0] == "approved"
    assert runner.resume_calls[0][1]["session_id"] == "s1"
    assert "echo hi" in sent[0]
    assert session.transcript[-1]["text"] == "done"
    await bridge.dispose_all()


async def test_bridge_question_text_answer(tmp_path: Path) -> None:
    runner = FakeRunner(
        [
            SimpleNamespace(
                session_id="s1",
                decision="wait",
                message="",
                error="",
                pending_approval={
                    "request_kind": "question",
                    "tool_call": {"id": "c1", "name": "question", "arguments": {}},
                    "request_payload": {
                        "request_id": "q1",
                        "message": "选一个",
                        "options": [{"label": "A"}, {"label": "B"}],
                    },
                },
            ),
            SimpleNamespace(session_id="s1", decision="done", message="ok", error="", pending_approval={}),
        ]
    )
    bridge = _bridge(tmp_path, runner)
    session = _session(bridge, [])
    task = asyncio.create_task(bridge.run(session, "hi"))
    await _wait_for(lambda: bool(bridge.questions.pending))
    assert bridge.questions.handle_text("c2c", "u1", "2", bridge)
    result = await task
    assert result.decision == "done"
    assert runner.resume_calls[0][0] == "question"
    assert runner.resume_calls[0][1]["answer"] == "B"
    await bridge.dispose_all()


async def test_bridge_registers_and_removes_prompt_section(tmp_path: Path) -> None:
    from lamtools_core.plugin_system.prompt_waterfall import PromptAssembly, PromptContext

    waterfall = FakeWaterfall()
    runner = FakeRunner([])
    bridge = _bridge(tmp_path, runner, waterfall=waterfall)
    bridge.config["directPrompt"] = "DIRECT PROMPT"
    sent: list[str] = []
    session = _session(bridge, sent)
    assert waterfall.handlers
    assembly = PromptAssembly(text="BASE", sections=[])
    result = waterfall.handlers[0](
        PromptContext(agent_name=session.agent_name),
        assembly,
    )
    assert "qqbot:scope-prompt" in [section.name for section in result.sections]
    await bridge.dispose_all()
    assert waterfall.handlers == []


async def test_bridge_multi_question(tmp_path: Path) -> None:
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
                        "arguments": {
                            "questions": [
                                {"question": "First?", "options": [{"label": "A"}, {"label": "B"}]},
                                {"question": "Second?", "options": [{"label": "C"}, {"label": "D"}]},
                            ]
                        },
                    },
                    "request_payload": {"request_id": "batch", "message": "First?"},
                },
            ),
            SimpleNamespace(session_id="s1", decision="done", message="ok", error="", pending_approval={}),
        ]
    )
    bridge = _bridge(tmp_path, runner)
    session = _session(bridge, [])
    task = asyncio.create_task(bridge.run(session, "hi"))
    await _wait_for(lambda: bool(bridge.questions.pending))
    assert bridge.questions.handle_text("c2c", "u1", "1", bridge)
    await asyncio.sleep(0.05)
    assert bridge.questions.handle_text("c2c", "u1", "2", bridge)
    result = await task
    assert result.decision == "done"
    answer = runner.resume_calls[0][1]["answer"]
    assert "问题 1: A" in answer
    assert "问题 2: D" in answer
    await bridge.dispose_all()


async def test_bridge_picks_up_late_host_services(tmp_path: Path) -> None:
    """The operation catalog may start the backend before agent assembly."""
    waterfall = FakeWaterfall()
    runner = FakeRunner([])
    bridge = _bridge(tmp_path, runner)
    assert bridge.prompt_waterfall is None
    bridge.context.services["system_prompt_waterfall"] = waterfall
    bridge.context.services["agent_presets"] = object()
    bridge._ensure_host_services()
    assert bridge.prompt_waterfall is waterfall
    assert waterfall.handlers
    assert bridge.agent_presets is not None
    await bridge.dispose_all()
    assert waterfall.handlers == []


async def test_bridge_uses_host_presets(tmp_path: Path) -> None:
    class FakePresets:
        def list(self):
            return [SimpleNamespace(id="p1", title="P1", description="", mode="low", tools=("read_file",))]

        def has(self, preset_id):
            return preset_id == "p1"

    runner = FakeRunner(
        [SimpleNamespace(session_id="s1", decision="done", message="ok", error="", pending_approval={})]
    )
    bridge = _bridge(tmp_path, runner, presets=FakePresets())
    sent: list[str] = []
    session = _session(bridge, sent)
    assert [item["id"] for item in bridge.list_presets()] == ["p1"]
    assert bridge.set_preset(session, "p1")["ok"] is True
    await bridge.run(session, "hi")
    assert runner.calls[0]["preset"] == "p1"
    await bridge.dispose_all()


async def test_fork_session_switches_peer_to_new_branch(tmp_path: Path) -> None:
    runner = FakeRunner([])
    runner.fork = _fake_fork
    bridge = _bridge(tmp_path, runner)
    sent: list[str] = []
    session = _session(bridge, sent)
    session.session_id = "qq:sub:old"
    old_agent = session.agent_name

    result = await bridge.fork_session(session)

    assert result["forked_from"] == "qq:sub:old"
    assert result["history_count"] == 4
    assert session.agent_name == result["agent"] != old_agent
    assert session.session_id == result["session_id"]
    assert bridge.by_agent(old_agent) is None
    assert bridge.by_agent(session.agent_name) is session
    assert bridge.prefs.get_session_id(session.key) == result["session_id"]
    await bridge.dispose_all()


async def test_fork_session_requires_an_active_session(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path, FakeRunner([]))
    session = _session(bridge, [])
    with pytest.raises(RuntimeError):
        await bridge.fork_session(session)
    await bridge.dispose_all()


async def test_session_info_reads_child_transcript(tmp_path: Path) -> None:
    runner = FakeRunner([])
    runner.session_info = _fake_session_info
    bridge = _bridge(tmp_path, runner)
    session = _session(bridge, [])
    session.session_id = "qq:sub:s1"

    info = await bridge.session_info(session)

    assert info["history_count"] == 2
    assert [item["role"] for item in info["messages"]] == ["user", "assistant"]
    await bridge.dispose_all()


async def _fake_fork(session_id: str, agent_name: str) -> dict:
    return {
        "session_id": f"qq:sub:{agent_name}",
        "agent": agent_name,
        "forked_from": session_id,
        "history_count": 4,
    }


async def _fake_session_info(session_id: str) -> dict:
    return {
        "session_id": session_id,
        "status": "idle",
        "turn_count": 1,
        "history_count": 2,
        "messages": [
            {"role": "user", "text": "你好"},
            {"role": "assistant", "text": "你好呀"},
        ],
    }


async def test_fork_history_and_compact_commands_use_host_services(tmp_path: Path) -> None:
    from qqbot.commands import CommandContext, CommandRegistry, build_commands

    runner = FakeRunner([])
    runner.fork = _fake_fork
    runner.session_info = _fake_session_info
    compacted: list[str] = []

    class CompactionService:
        async def compact_now(self, session_id: str) -> dict:
            compacted.append(session_id)
            return {"status": "compacted", "compacted_messages": 3, "before_tokens": 100, "after_tokens": 40}

    runner.preset_service = lambda name, preset_id="": CompactionService() if name == "compaction" else None
    bridge = _bridge(tmp_path, runner)
    session = _session(bridge, [])
    session.session_id = "qq:sub:s1"
    registry = CommandRegistry(build_commands(bridge, None, {}))
    ctx = CommandContext(
        session=session,
        message=SimpleNamespace(timestamp_ms=0),
        args=[],
        raw="",
        bridge=bridge,
        runtime=None,
    )

    compact = await registry.find("compact").handler(ctx)
    assert "已压缩 3 条历史" in compact.text
    assert compacted == ["qq:sub:s1"]

    history = await registry.find("history").handler(ctx)
    assert "会话历史" in history.text
    assert "你好呀" in history.text

    fork = await registry.find("fork").handler(ctx)
    assert "已从当前会话分叉" in fork.text
    assert session.session_id.startswith("qq:sub:")
    await bridge.dispose_all()


async def test_bridge_creates_runner_in_the_plugin_working_directory(tmp_path: Path) -> None:
    seen: dict = {}
    runner = FakeRunner([])

    def factory(**kwargs):
        seen.update(kwargs)
        return runner

    bridge = AgentBridge(
        context=FakeContext({"sub_agent_runner_factory": factory}),
        config=normalize({"appId": "app", "cwd": str(tmp_path / "bot-home")}),
        data_dir=tmp_path,
        work_root=tmp_path,
        logger=logging.getLogger("test"),
        approvals=ApprovalChannel(logger=logging.getLogger("test")),
        questions=QuestionChannel(logger=logging.getLogger("test")),
        on_event=_noop,
    )

    assert seen["work_root"] == str(tmp_path / "bot-home")
    await bridge.dispose_all()


def test_session_title_uses_a_stable_qq_format(tmp_path: Path) -> None:
    from qqbot.agent_bridge import session_title

    assert session_title("c2c", "9F63903D858D", "霖") == "QQ-私聊-霖"
    assert session_title("group", "GROUP123", "群友") == "QQ-群聊-群友"
    assert session_title("c2c", "9F63903D858D", "") == "QQ-私聊-3D858D"


def test_status_includes_the_session_title(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path, FakeRunner([]))
    session = bridge.get_or_create(
        scope="c2c",
        peer_id="9F63903D858D",
        sender_id="9F63903D858D",
        sender_name="霖",
        reply_target=ReplyTarget("c2c", "9F63903D858D", "m1"),
        sender=_noop,
    )
    assert session.title == "QQ-私聊-霖"
    assert bridge.status(session)["title"] == "QQ-私聊-霖"
