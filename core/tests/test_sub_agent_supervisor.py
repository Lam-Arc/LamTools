from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from lamtools_core.agent import SubAgentRunResult
from lamtools_core.agent import SUB_AGENT_TOOL_SPEC
from lamtools_core.sub_agent_supervisor import (
    SubAgentRecord,
    SubAgentSupervisor,
    acknowledge_parent_mailbox,
    current_child_identity,
    drain_parent_mailbox,
    validate_reasoning,
)
from lamtools_core.tool import ToolCall
from lamtools_core.tool.default_toolbox import build_core_toolbox


def seed_model(root) -> None:
    directory = root / ".lam" / "config" / "models"
    directory.mkdir(parents=True)
    (directory / "test-model.jsonc").write_text(
        '{"model_id":"test-model","display_name":"Test Model"}', encoding="utf-8"
    )


@dataclass
class FakeRunner:
    work_root: object

    def __post_init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.calls: list[dict] = []
        self.guidance: list[str] = []

    async def run(self, **kwargs):
        self.calls.append(kwargs)
        self.started.set()
        await self.release.wait()
        self.guidance.extend(kwargs["guidance_source"]())
        identity = current_child_identity()
        assert identity is not None
        await identity[0].child_message("evidence ready", message_id="message-1")
        await identity[0].child_message("evidence ready", message_id="message-1")
        await identity[0].child_message("evidence ready", message_id="message-2")
        return SubAgentRunResult(
            session_id=f"parent:sub:{kwargs['agent']}", run_id="child-run", decision="done",
            model_id=kwargs["model"], message="done", ended_with_final_response=True,
        )


@pytest.mark.asyncio
async def test_supervisor_strict_lifecycle_and_exact_reopen(tmp_path):
    seed_model(tmp_path)
    runner = FakeRunner(tmp_path)
    supervisor = SubAgentSupervisor(parent_thread_id="parent", runner=runner, database_path=tmp_path / "state.sqlite3")

    created = await supervisor.create(type="consider", name="reader_1", model="test-model", reasoning_level="xh")
    assert created.reasoning_level == "xhigh"
    assert created.status == "idle"
    assert (await supervisor.create(type="consider", name="reader_1", model="Test Model", reasoning_level="xhigh")).to_dict() == created.to_dict()
    with pytest.raises(ValueError, match="different configuration"):
        await supervisor.create(type="execute", name="reader_1", model="test-model", reasoning_level="xhigh")
    with pytest.raises(ValueError, match="name must match"):
        await supervisor.create(type="consider", name="Reader-1", model="test-model", reasoning_level="xhigh")
    with pytest.raises(ValueError, match="unknown model"):
        await supervisor.create(type="consider", name="other", model="terra", reasoning_level="high")

    closed = await supervisor.close(type="consider", name="reader_1", model="test-model", reasoning_level="xh")
    assert closed.status == "closed"
    reopened = await supervisor.create(type="consider", name="reader_1", model="test-model", reasoning_level="xhigh")
    assert reopened.status == "idle"
    await supervisor.shutdown()


@pytest.mark.asyncio
async def test_operation_results_distinguish_created_enabled_and_closed_without_persisting_action(tmp_path):
    seed_model(tmp_path)
    runner = FakeRunner(tmp_path)
    supervisor = SubAgentSupervisor(
        parent_thread_id="parent",
        runner=runner,
        database_path=tmp_path / "state.sqlite3",
    )

    created = await supervisor.create_operation(
        type="consider", name="reader", model="test-model", reasoning_level="high"
    )
    existing = await supervisor.create_operation(
        type="consider", name="reader", model="test-model", reasoning_level="high"
    )
    closed = await supervisor.close_operation(
        type="consider", name="reader", model="test-model", reasoning_level="high"
    )
    reopened = await supervisor.create_operation(
        type="consider", name="reader", model="test-model", reasoning_level="high"
    )

    assert [
        created.lifecycle_action,
        existing.lifecycle_action,
        closed.lifecycle_action,
        reopened.lifecycle_action,
    ] == ["created", "enabled", "closed", "enabled"]
    assert "lifecycle_action" not in (await supervisor.list())[0]
    await supervisor.shutdown()


@pytest.mark.asyncio
async def test_toolbox_lifecycle_results_expose_transient_actions(tmp_path):
    seed_model(tmp_path)
    runner = FakeRunner(tmp_path)
    runner.session_prefix = "toolbox-parent"
    toolbox = build_core_toolbox(
        work_root=tmp_path,
        data_dir=tmp_path / "data",
        sub_agent_runner=runner,
    )
    common = {
        "type": "execute",
        "name": "worker",
        "model": "test-model",
        "reasoning_level": "xh",
    }

    prepared_create = toolbox.prepare_call(ToolCall(
        id="create-1",
        name="sub_agent",
        arguments={"action": "create", **common},
    ))
    assert prepared_create.requires_approval is False
    assert prepared_create.metadata["approval"]["blocked"] is False
    created = await toolbox.execute(prepared_create)
    enabled = await toolbox.execute(ToolCall(
        id="create-2",
        name="sub_agent",
        arguments={"action": "create", **common},
    ))
    sent = await toolbox.execute(ToolCall(
        id="message-1",
        name="sub_agent_message",
        arguments={"type": "execute", "name": "worker", "prompt": "do it"},
    ))
    closed = await toolbox.execute(ToolCall(
        id="close-1",
        name="sub_agent",
        arguments={"action": "close", **common},
        metadata={
            "parent_run_id": "close-run",
            "parent_turn_id": "close-turn",
            "parent_message_id": "close-message",
        },
    ))

    assert created.metadata["lifecycle_action"] == "created"
    assert created.metadata["reasoning_level"] == "xhigh"
    assert enabled.metadata["lifecycle_action"] == "enabled"
    assert sent.metadata["lifecycle_action"] == "message_sent"
    assert closed.metadata["lifecycle_action"] == "closed"
    assert closed.metadata["source_call_id"] == "close-1"
    assert closed.metadata["source_run_id"] == "close-run"
    assert closed.metadata["source_turn_id"] == "close-turn"
    assert closed.metadata["source_message_id"] == "close-message"
    assert closed.metadata["source_part_id"] == "toolbox-parent:close-run:close-1:tool"


def test_sub_agent_reasoning_schema_and_normalizer_accept_user_aliases():
    enum = SUB_AGENT_TOOL_SPEC["input_schema"]["properties"]["reasoning_level"]["enum"]
    assert "xh" in enum
    assert "Medium" in enum
    assert validate_reasoning(" xh ") == "xhigh"
    assert validate_reasoning(" Medium ") == "medium"


@pytest.mark.asyncio
async def test_busy_message_is_next_step_guidance_and_mailbox_deduplicates_by_call_id(tmp_path):
    seed_model(tmp_path)
    runner = FakeRunner(tmp_path)
    supervisor = SubAgentSupervisor(parent_thread_id="parent", runner=runner, database_path=tmp_path / "state.sqlite3")
    await supervisor.create(type="execute", name="worker", model="test-model", reasoning_level="max")

    accepted = await supervisor.message(type="execute", name="worker", prompt="initial work")
    assert accepted["accepted"] is True
    second = await supervisor.message(type="execute", name="worker", prompt="steer the next step")
    assert second["accepted"] is True
    await asyncio.wait_for(runner.started.wait(), timeout=1)
    assert len(runner.calls) == 1
    runner.release.set()
    await asyncio.wait_for(supervisor._tasks["worker"], timeout=1)

    assert runner.guidance == ["steer the next step"]
    assert "name: worker" in runner.calls[0]["late_context"]
    assert "model_id: test-model" in runner.calls[0]["late_context"]
    mailbox = await supervisor.drain_parent_mailbox()
    assert [item["body"] for item in mailbox] == ["evidence ready", "evidence ready"]
    assert await supervisor.drain_parent_mailbox() == []

    first = (await supervisor.list())[0]
    await supervisor.message(type="execute", name="worker", prompt="follow-up work")
    await asyncio.wait_for(supervisor._tasks["worker"], timeout=1)
    second = (await supervisor.list())[0]
    assert len(runner.calls) == 2
    assert "summary: done" in runner.calls[1]["late_context"]
    assert second["status"] == "idle"
    assert second["started_at"] >= first["completed_at"]

    closed = await supervisor.close(
        type="execute", name="worker", model="test-model", reasoning_level="max"
    )
    reopened = await supervisor.create(
        type="execute", name="worker", model="test-model", reasoning_level="max"
    )
    assert closed.summary == "done"
    assert reopened.summary == "done"
    assert reopened.started_at is None
    assert reopened.completed_at is None
    assert reopened.elapsed_ms is None
    await supervisor.shutdown()


@pytest.mark.asyncio
async def test_parent_message_refreshes_source_and_deduplicates_only_within_parent_run(tmp_path):
    seed_model(tmp_path)
    runner = FakeRunner(tmp_path)
    supervisor = SubAgentSupervisor(
        parent_thread_id="parent",
        runner=runner,
        database_path=tmp_path / "state.sqlite3",
    )
    await supervisor.create(
        type="execute",
        name="worker",
        model="test-model",
        reasoning_level="max",
        source_ids={"call_id": "create-call", "run_id": "create-run", "turn_id": "create-turn"},
    )
    reused = await supervisor.create_operation(
        type="execute",
        name="worker",
        model="test-model",
        reasoning_level="max",
        source_ids={"call_id": "reuse-call", "run_id": "reuse-run", "turn_id": "reuse-turn"},
    )
    assert reused.record.source_call_id == "reuse-call"
    assert reused.record.source_run_id == "reuse-run"
    assert reused.record.source_part_id == "parent:reuse-run:reuse-call:tool"

    first = await supervisor.message(
        type="execute",
        name="worker",
        prompt="first",
        source_ids={"call_id": "shared-call", "run_id": "parent-run-1", "turn_id": "turn-1"},
    )
    duplicate = await supervisor.message(
        type="execute",
        name="worker",
        prompt="first",
        source_ids={"call_id": "shared-call", "run_id": "parent-run-1", "turn_id": "turn-1"},
    )
    runner.release.set()
    await asyncio.wait_for(supervisor._tasks["worker"], timeout=1)
    assert first["deduplicated"] is False
    assert duplicate["deduplicated"] is True
    assert len(runner.calls) == 1
    assert runner.calls[0]["parent_call_id"] == "shared-call"
    assert runner.calls[0]["parent_run_id"] == "parent-run-1"
    assert len(await supervisor.drain_parent_mailbox()) == 2

    second = await supervisor.message(
        type="execute",
        name="worker",
        prompt="second",
        source_ids={"call_id": "shared-call", "run_id": "parent-run-2", "turn_id": "turn-2"},
    )
    await asyncio.wait_for(supervisor._tasks["worker"], timeout=1)
    assert second["deduplicated"] is False
    assert len(runner.calls) == 2
    assert runner.calls[1]["parent_call_id"] == "shared-call"
    assert runner.calls[1]["parent_run_id"] == "parent-run-2"
    assert len(await supervisor.drain_parent_mailbox()) == 2
    await supervisor.shutdown()


@pytest.mark.asyncio
async def test_child_message_injects_sub_agent_source_metadata(tmp_path):
    seed_model(tmp_path)
    runner = FakeRunner(tmp_path)
    injected: list[tuple[object, ...]] = []

    def parent_guidance_sink(*args: object) -> bool:
        injected.append(args)
        return True

    runner.parent_guidance_sink = parent_guidance_sink
    supervisor = SubAgentSupervisor(
        parent_thread_id="parent",
        runner=runner,
        database_path=tmp_path / "state.sqlite3",
    )
    await supervisor.create(
        type="execute",
        name="worker",
        model="test-model",
        reasoning_level="max",
        source_ids={"run_id": "parent-run"},
    )
    await supervisor.message(
        type="execute",
        name="worker",
        prompt="initial work",
        source_ids={
            "call_id": "message-call",
            "run_id": "message-run",
            "turn_id": "message-turn",
        },
    )
    await asyncio.wait_for(runner.started.wait(), timeout=1)
    runner.release.set()
    await asyncio.wait_for(supervisor._tasks["worker"], timeout=1)

    assert injected[0][0:4] == (
        "parent",
        "message-run",
        "evidence ready",
        "sub-agent:parent:worker:message-1",
    )
    assert injected[0][4] == {
        "source": "sub_agent",
        "name": "worker",
        "type": "execute",
        "status": "running",
        "summary": "",
        "session_id": "parent:sub:worker",
        "sub_session_id": "parent:sub:worker",
        "model_id": "test-model",
        "reasoning_level": "max",
        "parent_call_id": "message-call",
        "parent_run_id": "message-run",
        "parent_turn_id": "message-turn",
        "invocation_id": injected[0][4]["invocation_id"],
    }
    await supervisor.shutdown()


@pytest.mark.asyncio
async def test_child_message_keeps_legacy_four_argument_guidance_sink_compatible(tmp_path):
    seed_model(tmp_path)
    runner = FakeRunner(tmp_path)
    injected: list[tuple[str, str, str, str]] = []

    def legacy_sink(parent_id: str, run_id: str, text: str, guidance_id: str) -> bool:
        injected.append((parent_id, run_id, text, guidance_id))
        return True

    runner.parent_guidance_sink = legacy_sink
    supervisor = SubAgentSupervisor(
        parent_thread_id="parent",
        runner=runner,
        database_path=tmp_path / "state.sqlite3",
    )
    await supervisor.create(
        type="execute",
        name="worker",
        model="test-model",
        reasoning_level="max",
        source_ids={"run_id": "parent-run"},
    )
    await supervisor.message(type="execute", name="worker", prompt="initial work")
    await asyncio.wait_for(runner.started.wait(), timeout=1)
    runner.release.set()
    await asyncio.wait_for(supervisor._tasks["worker"], timeout=1)

    assert injected[0][0:3] == ("parent", "parent-run", "evidence ready")
    await supervisor.shutdown()


@pytest.mark.asyncio
async def test_recover_marks_orphaned_running_record_interrupted(tmp_path):
    seed_model(tmp_path)
    runner = FakeRunner(tmp_path)
    database = tmp_path / "state.sqlite3"
    first = SubAgentSupervisor(parent_thread_id="parent", runner=runner, database_path=database)
    record = await first.create(type="consider", name="reader", model="test-model", reasoning_level="light")
    record.status = "running"
    record.started_at = 1.0
    first._save(record)

    recovered = SubAgentSupervisor(parent_thread_id="parent", runner=runner, database_path=database)
    await recovered.recover()
    items = await recovered.list()
    assert items[0]["status"] == "interrupted"
    assert items[0]["completed_at"] is not None


def test_parent_mailbox_peek_survives_failed_turn_until_acknowledged(tmp_path):
    database = tmp_path / "state.sqlite3"
    supervisor = SubAgentSupervisor(
        parent_thread_id="parent",
        runner=FakeRunner(tmp_path),
        database_path=database,
    )
    supervisor._mail("worker", "child_to_parent", "retained", message_key="message-1")

    first = drain_parent_mailbox(database, "parent", mark_delivered=False)
    second = drain_parent_mailbox(database, "parent", mark_delivered=False)
    assert [item["body"] for item in first] == ["retained"]
    assert [item["id"] for item in second] == [item["id"] for item in first]

    acknowledge_parent_mailbox(database, "parent", [first[0]["id"]])
    assert drain_parent_mailbox(database, "parent", mark_delivered=False) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("decision", "error", "expected"),
    [
        ("done", "", "idle"),
        ("wait", "", "paused"),
        ("cancelled", "", "interrupted"),
        ("interrupted", "", "interrupted"),
        ("failed", "", "failed"),
        ("done", "boom", "failed"),
    ],
)
async def test_finalize_resumed_normalizes_durable_child_status(
    tmp_path, decision, error, expected
):
    seed_model(tmp_path)
    supervisor = SubAgentSupervisor(
        parent_thread_id="parent",
        runner=FakeRunner(tmp_path),
        database_path=tmp_path / "state.sqlite3",
    )
    await supervisor.create(
        type="execute",
        name="worker",
        model="test-model",
        reasoning_level="max",
    )
    record = await supervisor.finalize_resumed(
        "worker",
        SimpleNamespace(decision=decision, error=error, message="summary"),
    )
    assert record.status == expected


@pytest.mark.asyncio
async def test_supervisor_closes_every_sqlite_connection(tmp_path, monkeypatch):
    """短连接用完即关（sqlite3 的 ``with`` 只提交不关闭，曾每次调用泄漏一个句柄）。"""
    import sqlite3

    opened: list[sqlite3.Connection] = []
    real_connect = sqlite3.connect

    def tracking_connect(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", tracking_connect)

    supervisor = SubAgentSupervisor(
        parent_thread_id="parent",
        runner=FakeRunner(tmp_path),
        database_path=tmp_path / "state.sqlite3",
    )
    supervisor._save(
        SubAgentRecord(
            parent_thread_id="parent",
            type="execute",
            name="worker",
            model_id="test-model",
            reasoning_level="medium",
            status="running",
        )
    )
    assert supervisor._load("worker") is not None
    assert supervisor._mail("worker", "parent_to_child", "hi", message_key="k1") is True

    assert len(opened) >= 3, "expected the init, save, load and mail connections"
    for connection in opened:
        with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
            connection.execute("SELECT 1")

