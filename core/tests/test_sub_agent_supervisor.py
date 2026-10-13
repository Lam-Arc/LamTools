from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from lamtools_core.agent import SubAgentRunResult
from lamtools_core.agent import SUB_AGENT_TOOL_SPEC
from lamtools_core.app import open_core_app_db
from lamtools_core.app.core_db import (
    CoreAppEvent,
    CoreHistoryEntry,
    CoreRuntimeSession,
    CoreThreadSnapshot,
    CoreThreadSnapshotItem,
)
from lamtools_core.cli import build_parser
from lamtools_core.event import CollectingEventSink
from lamtools_core.sub_agent_supervisor import (
    SubAgentRecord,
    SubAgentSupervisor,
    acknowledge_parent_mailbox,
    current_child_identity,
    drain_parent_mailbox,
    find_sub_agent_supervisor,
    resolve_model_id,
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


def seed_models(root, entries) -> None:
    """Seed several model jsonc files into a project-scoped model dir."""
    directory = root / ".lam" / "config" / "models"
    directory.mkdir(parents=True, exist_ok=True)
    for record_id, payload in entries:
        (directory / f"{record_id}.jsonc").write_text(
            json.dumps({"id": record_id, **payload}), encoding="utf-8"
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


def test_resolve_model_id_exact_real_id_wins(tmp_path):
    seed_models(tmp_path, [
        ("prov-a-alpha", {"model_id": "prov-a/alpha-1", "display_name": "Alpha One", "provider": "Prov A"}),
        ("prov-b-shared", {"model_id": "prov-b/shared", "display_name": "Twin Label", "provider": "Prov B"}),
        ("prov-c-shared", {"model_id": "prov-c/shared", "display_name": "Twin Label", "provider": "Prov C"}),
    ])
    # Upstream model_id is the canonical real id and wins exactly.
    assert resolve_model_id("prov-a/alpha-1", work_root=tmp_path) == "prov-a/alpha-1"
    # The record/file id is also an exact real id.
    assert resolve_model_id("prov-a-alpha", work_root=tmp_path) == "prov-a/alpha-1"
    # Exact real ids resolve even when a display label is duplicated elsewhere.
    assert resolve_model_id("prov-b/shared", work_root=tmp_path) == "prov-b/shared"


def test_resolve_model_id_unique_display_label_and_provider_label(tmp_path):
    seed_models(tmp_path, [
        ("uniq", {"model_id": "vendor/uniq-1", "display_name": "Unique Label", "provider": "Prov X"}),
    ])
    assert resolve_model_id("Unique Label", work_root=tmp_path) == "vendor/uniq-1"
    # The label the running agent actually sees is "<provider>/<display_name>".
    assert resolve_model_id("Prov X/Unique Label", work_root=tmp_path) == "vendor/uniq-1"
    # Models commonly echo the label lower-cased; matching is case-insensitive.
    assert resolve_model_id("unique label", work_root=tmp_path) == "vendor/uniq-1"
    assert resolve_model_id("prov x/unique label", work_root=tmp_path) == "vendor/uniq-1"


def test_resolve_model_id_duplicate_display_label_is_rejected_with_candidates(tmp_path):
    seed_models(tmp_path, [
        ("dup-a", {"model_id": "prov-a/twin", "display_name": "Twin Label", "provider": "Prov A"}),
        ("dup-b", {"model_id": "prov-b/twin", "display_name": "Twin Label", "provider": "Prov B"}),
    ])
    with pytest.raises(ValueError) as excinfo:
        resolve_model_id("Twin Label", work_root=tmp_path)
    message = str(excinfo.value)
    assert "ambiguous" in message
    # Every colliding candidate is listed by its real id so the caller can retry.
    assert "prov-a/twin" in message
    assert "prov-b/twin" in message
    # A lower-cased duplicated label is still rejected, not silently resolved.
    with pytest.raises(ValueError, match="ambiguous"):
        resolve_model_id("twin label", work_root=tmp_path)
    # A provider-qualified label is unique and therefore still resolves.
    assert resolve_model_id("Prov A/Twin Label", work_root=tmp_path) == "prov-a/twin"


def test_resolve_model_id_unknown_lists_available_ids(tmp_path):
    seed_models(tmp_path, [
        ("only", {"model_id": "vendor/only-1", "display_name": "Only Model", "provider": "Prov Z"}),
    ])
    with pytest.raises(ValueError) as excinfo:
        resolve_model_id("no-such-model-xyz", work_root=tmp_path)
    message = str(excinfo.value)
    assert "unknown model" in message
    assert "vendor/only-1" in message
    # Display labels stay as a supplementary note next to the real id.
    assert "Only Model" in message


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



# --- 成员状态事件（会话级唤醒） -------------------------------------------


def test_chinese_member_names_are_accepted():
    """用户可用稳定中文称呼（张前端/苏测试），拉丁名规则保持兼容。"""
    from lamtools_core.sub_agent_supervisor import validate_name

    assert validate_name("张前端") == "张前端"
    assert validate_name("苏测试") == "苏测试"
    assert validate_name("ui_zhang") == "ui_zhang"
    for bad in ("Bad-Name", "9start", "_leading", ""):
        with pytest.raises(ValueError, match="name must match"):
            validate_name(bad)


@pytest.mark.asyncio
async def test_member_completion_writes_session_scoped_event_and_wakes_waiter(tmp_path):
    """成员跑完后：事件落进父邮箱（幂等）、活动信号点亮、等待方被唤醒。"""
    seed_model(tmp_path)
    runner = FakeRunner(tmp_path)
    supervisor = SubAgentSupervisor(
        parent_thread_id="parent", runner=runner, database_path=tmp_path / "state.sqlite3"
    )
    await supervisor.create(
        type="execute", name="张前端", model="test-model", reasoning_level="medium"
    )
    await supervisor.message(
        type="execute", name="张前端",
        prompt="build the ui", source_ids={"call_id": "call-1", "run_id": "run-1"},
    )
    assert await supervisor.has_active_members() is True

    # 等待发生在成员完成之前 → 完成时被唤醒（而不是靠 sleep 轮询）。
    waiter = asyncio.create_task(supervisor.wait_for_activity(5.0))
    await asyncio.sleep(0.05)
    runner.release.set()
    assert await waiter == "activity"

    for _ in range(50):
        if not await supervisor.has_active_members():
            break
        await asyncio.sleep(0.02)
    assert await supervisor.has_active_members() is False

    events = await supervisor.drain_member_events()
    finished = [item for item in events if item.get("event") == "member_finished"]
    assert finished, f"expected a member_finished event, got {events!r}"
    assert finished[0]["name"] == "张前端"
    assert finished[0]["status"] == "idle"

    # 事件已投递，不会重复出现（幂等）。
    assert await supervisor.drain_member_events() == []


@pytest.mark.asyncio
async def test_close_and_shutdown_report_interrupted_events(tmp_path):
    """关闭运行中的成员 / 进程收尾：都要如实上报事件，而不是静默消失。"""
    seed_model(tmp_path)
    runner = FakeRunner(tmp_path)
    supervisor = SubAgentSupervisor(
        parent_thread_id="parent", runner=runner, database_path=tmp_path / "state.sqlite3"
    )
    await supervisor.create(
        type="execute", name="李数据", model="test-model", reasoning_level="medium"
    )
    await supervisor.message(
        type="execute", name="李数据",
        prompt="build the store", source_ids={"call_id": "call-2", "run_id": "run-1"},
    )
    await supervisor.close(
        type="execute", name="李数据", model="test-model", reasoning_level="medium"
    )
    events = await supervisor.drain_member_events()
    assert any(item.get("event") == "member_closed" for item in events), events


@pytest.mark.asyncio
async def test_wait_for_activity_times_out_without_events(tmp_path):
    supervisor = SubAgentSupervisor(
        parent_thread_id="parent", runner=FakeRunner(tmp_path), database_path=tmp_path / "state.sqlite3"
    )
    assert await supervisor.wait_for_activity(0.05) == "timeout"


@pytest.mark.asyncio
async def test_recover_reports_orphaned_running_member(tmp_path):
    """上次进程留下的 running 记录：转 interrupted 并留下事件，供父会话处置。"""
    database = tmp_path / "state.sqlite3"
    first = SubAgentSupervisor(
        parent_thread_id="parent", runner=FakeRunner(tmp_path), database_path=database
    )
    first._save(
        SubAgentRecord(
            parent_thread_id="parent", type="execute", name="王构建",
            model_id="test-model", reasoning_level="medium", status="running",
            started_at=time.time() - 30,
        )
    )
    second = SubAgentSupervisor(
        parent_thread_id="parent", runner=FakeRunner(tmp_path), database_path=database
    )
    await second.recover()
    assert second._load("王构建").status == "interrupted"
    payloads = await second.drain_member_events()
    interrupted = next(item for item in payloads if item.get("event") == "member_interrupted")
    assert interrupted["detail"] == "进程重启时该成员仍在运行"


@pytest.mark.asyncio
async def test_shutdown_reports_why_running_member_was_interrupted(tmp_path):
    database = tmp_path / "shutdown.sqlite3"
    supervisor = SubAgentSupervisor(
        parent_thread_id="parent", runner=FakeRunner(tmp_path), database_path=database
    )
    supervisor._save(
        SubAgentRecord(
            parent_thread_id="parent", type="execute", name="李数据",
            model_id="test-model", reasoning_level="medium", status="running",
            started_at=time.time() - 2,
        )
    )

    async def hold_open():
        await asyncio.Event().wait()

    supervisor._tasks["李数据"] = asyncio.create_task(hold_open())
    await supervisor.shutdown()
    events = await supervisor.drain_member_events()
    interrupted = next(item for item in events if item.get("event") == "member_interrupted")
    assert interrupted["detail"] == "进程关闭时该成员仍在运行"


def test_find_sub_agent_supervisor_resolves_by_thread_id(tmp_path):
    from lamtools_core.sub_agent_supervisor import (
        _SUPERVISORS,
        find_sub_agent_supervisor,
    )

    supervisor = SubAgentSupervisor(
        parent_thread_id="thread-lookup", runner=FakeRunner(tmp_path),
        database_path=tmp_path / "state.sqlite3",
    )
    _SUPERVISORS[(str(tmp_path.resolve()), "thread-lookup")] = supervisor
    try:
        assert find_sub_agent_supervisor("thread-lookup") is supervisor
        assert find_sub_agent_supervisor("missing-thread") is None
        assert find_sub_agent_supervisor("") is None
    finally:
        _SUPERVISORS.pop((str(tmp_path.resolve()), "thread-lookup"), None)


async def _seed_session_family(db, *, session_id: str, history: int) -> None:
    """Seed the runtime-state row and history rows a member's runs leave behind."""
    async with db.session_factory() as session:
        session.add(CoreRuntimeSession(
            thread_id=session_id,
            revision=1,
            runtime_state_json={"session_id": session_id, "status": "idle", "metadata": {}},
            history_json=[],
        ))
        for index in range(1, history + 1):
            session.add(CoreHistoryEntry(
                thread_id=session_id,
                seq=index,
                revision=index,
                message_json={"role": "assistant", "content": f"{session_id} message {index}"},
            ))
        await session.commit()


async def _scalar_count(db, statement) -> int:
    async with db.session_factory() as session:
        return int((await session.execute(statement)).scalar_one())


@pytest.mark.asyncio
async def test_delete_removes_only_the_members_own_rows_and_its_session_family(tmp_path):
    """Deleting a member frees its own storage and damages nothing else.

    Removed: the member's durable record, its events and mailbox, and its own
    session family (runtime state + full internal transcript). Protected: the
    parent session's own conversation rows and every other member — they carry
    different session ids, so the purge can never reach them.
    """
    seed_model(tmp_path)
    db = await open_core_app_db(tmp_path / "core.db")
    try:
        runner = FakeRunner(tmp_path)
        runner.state_store = db.runtime_state_store
        supervisor = SubAgentSupervisor(
            parent_thread_id="parent", runner=runner,
            database_path=tmp_path / "state.sqlite3",
        )
        await supervisor.create(type="execute", name="worker", model="test-model", reasoning_level="high")
        await supervisor.create(type="execute", name="other", model="test-model", reasoning_level="high")

        worker_session = "parent:sub:worker"
        other_session = "parent:sub:other"
        await _seed_session_family(db, session_id=worker_session, history=3)
        await _seed_session_family(db, session_id=other_session, history=1)

        # The parent session's own conversation is a different session id.
        async with db.session_factory() as session:
            session.add(CoreThreadSnapshot(thread_id="parent", snapshot_json={"status": "completed"}))
            session.add(CoreAppEvent(
                event_id="event-1", thread_id="parent", seq=1,
                method="core/runItem", payload_json={"kind": "message"},
            ))
            session.add(CoreThreadSnapshotItem(
                thread_id="parent", item_id="item-1", seq=1, item_json={"item_id": "item-1"},
            ))
            await session.commit()

        # The member's own event/mailbox rows, plus a sibling's that must survive.
        with supervisor._connection() as connection:
            connection.execute(
                "INSERT INTO sub_agent_events(id,parent_thread_id,name,payload,event_key,created_at)"
                " VALUES(?,?,?,?,?,?)",
                ("worker-event", "parent", "worker",
                 json.dumps({"event": "member_finished", "name": "worker"}),
                 "member_finished:worker:1", time.time()),
            )
            connection.execute(
                "INSERT INTO sub_agent_events(id,parent_thread_id,name,payload,event_key,created_at)"
                " VALUES(?,?,?,?,?,?)",
                ("other-event", "parent", "other",
                 json.dumps({"event": "member_finished", "name": "other"}),
                 "member_finished:other:1", time.time()),
            )
            connection.execute(
                "INSERT INTO sub_agent_mailbox(id,parent_thread_id,name,direction,body,digest,message_key,created_at)"
                " VALUES(?,?,?,?,?,?,?,?)",
                ("worker-mail", "parent", "worker", "parent_to_child", "hi", "d", "k-worker", time.time()),
            )

        result = await supervisor.delete_operation(name="worker")

        assert result["lifecycle_action"] == "deleted"
        assert result["freed_sub_session"] is True
        assert result["sub_session_id"] == worker_session

        # The member's durable record, events and mailbox are actually gone.
        assert supervisor._load("worker") is None
        with supervisor._connection() as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM sub_agents WHERE parent_thread_id='parent' AND name='worker'"
            ).fetchone()[0] == 0
            assert connection.execute(
                "SELECT COUNT(*) FROM sub_agent_events WHERE parent_thread_id='parent' AND name='worker'"
            ).fetchone()[0] == 0
            assert connection.execute(
                "SELECT COUNT(*) FROM sub_agent_mailbox WHERE parent_thread_id='parent' AND name='worker'"
            ).fetchone()[0] == 0
            # The sibling member's rows are untouched.
            assert connection.execute(
                "SELECT COUNT(*) FROM sub_agents WHERE parent_thread_id='parent' AND name='other'"
            ).fetchone()[0] == 1
            assert connection.execute(
                "SELECT COUNT(*) FROM sub_agent_events WHERE parent_thread_id='parent' AND name='other'"
            ).fetchone()[0] == 1

        # The member's own session family is gone...
        assert await _scalar_count(
            db, select(func.count()).select_from(CoreRuntimeSession).where(
                CoreRuntimeSession.thread_id == worker_session
            )
        ) == 0
        assert await _scalar_count(
            db, select(func.count()).select_from(CoreHistoryEntry).where(
                CoreHistoryEntry.thread_id == worker_session
            )
        ) == 0
        # ...while the sibling's family and the parent session's own content remain.
        assert await _scalar_count(
            db, select(func.count()).select_from(CoreRuntimeSession).where(
                CoreRuntimeSession.thread_id == other_session
            )
        ) == 1
        assert await _scalar_count(
            db, select(func.count()).select_from(CoreHistoryEntry).where(
                CoreHistoryEntry.thread_id == other_session
            )
        ) == 1
        assert await _scalar_count(
            db, select(func.count()).select_from(CoreThreadSnapshot).where(
                CoreThreadSnapshot.thread_id == "parent"
            )
        ) == 1
        assert await _scalar_count(
            db, select(func.count()).select_from(CoreAppEvent).where(
                CoreAppEvent.thread_id == "parent"
            )
        ) == 1
        assert await _scalar_count(
            db, select(func.count()).select_from(CoreThreadSnapshotItem).where(
                CoreThreadSnapshotItem.thread_id == "parent"
            )
        ) == 1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_delete_refuses_a_running_member_and_succeeds_after_close(tmp_path):
    """A running member is refused, never half-deleted; stopping it first works."""
    seed_model(tmp_path)
    runner = FakeRunner(tmp_path)
    supervisor = SubAgentSupervisor(
        parent_thread_id="parent", runner=runner, database_path=tmp_path / "state.sqlite3"
    )
    await supervisor.create(type="execute", name="worker", model="test-model", reasoning_level="medium")
    await supervisor.message(
        type="execute", name="worker", prompt="do it",
        source_ids={"call_id": "c1", "run_id": "r1"},
    )

    with pytest.raises(ValueError, match="is running"):
        await supervisor.delete_operation(name="worker")
    # Nothing was removed while the task is live.
    assert supervisor._load("worker") is not None

    # Stopping it first is the explicit, loss-free path; delete is then allowed.
    await supervisor.close(type="execute", name="worker", model="test-model", reasoning_level="medium")
    result = await supervisor.delete_operation(name="worker")
    assert result["lifecycle_action"] == "deleted"
    assert supervisor._load("worker") is None


@pytest.mark.asyncio
async def test_toolbox_and_cli_expose_delete(tmp_path):
    """Delete is reachable from the model-facing tool and the CLI parser."""
    seed_model(tmp_path)
    runner = FakeRunner(tmp_path)
    runner.session_prefix = "toolbox-delete"
    toolbox = build_core_toolbox(
        work_root=tmp_path, data_dir=tmp_path / "data", sub_agent_runner=runner,
    )
    common = {"type": "execute", "name": "worker", "model": "test-model", "reasoning_level": "xh"}
    await toolbox.execute(ToolCall(id="create-1", name="sub_agent", arguments={"action": "create", **common}))
    deleted = await toolbox.execute(ToolCall(
        id="delete-1", name="sub_agent", arguments={"action": "delete", **common},
    ))
    assert deleted.status == "ok"
    assert deleted.metadata["lifecycle_action"] == "deleted"
    supervisor = find_sub_agent_supervisor("toolbox-delete")
    assert supervisor is not None
    assert await supervisor.list() == []

    parsed = build_parser().parse_args([
        "subagent", "delete", "thread-1", "--type", "execute", "--name", "worker",
    ])
    assert parsed.subagent_command == "delete"
    assert parsed.func is not None



@pytest.mark.asyncio
async def test_member_status_is_published_mid_turn_when_it_finishes(tmp_path):
    """A member finishing while the turn is open is published as finished.

    The parent's tool-call row stays running until the turn closes it, and the
    members-running fact is turn-terminal. So the member's own status must be
    published at each transition; here the turn is never closed, yet the
    member's real status is already on the live stream.
    """
    from lamtools_core.app.base_agent import core_events_to_run_items

    seed_model(tmp_path)
    runner = FakeRunner(tmp_path)
    runner.parent_event_sink = CollectingEventSink()
    supervisor = SubAgentSupervisor(
        parent_thread_id="parent", runner=runner, database_path=tmp_path / "state.sqlite3"
    )
    await supervisor.create(type="execute", name="worker", model="test-model", reasoning_level="medium")
    await supervisor.message(
        type="execute", name="worker", prompt="do it",
        source_ids={"call_id": "c1", "run_id": "run-1", "turn_id": "turn-1"},
    )
    runner.release.set()
    for _ in range(200):
        if not await supervisor.has_active_members():
            break
        await asyncio.sleep(0.02)
    await supervisor.close(type="execute", name="worker", model="test-model", reasoning_level="medium")

    statuses = [e for e in runner.parent_event_sink.events if e.name == "runtime.sub_agent_status"]
    events = [e.payload["event"] for e in statuses]
    assert events[0] == "member_running", events
    assert "member_finished" in events, events
    finished = next(e for e in statuses if e.payload["event"] == "member_finished")
    assert finished.payload["sub_agent"]["name"] == "worker"
    assert finished.payload["sub_agent"]["status"] == "idle"
    assert finished.turn_id == "turn-1"

    # And it projects to a per-member row carrying that real status.
    items = core_events_to_run_items([finished], thread_id="parent")
    assert len(items) == 1
    assert items[0].payload["sub_agent"]["status"] == "idle"
    assert items[0].metadata["sub_agent"]["name"] == "worker"
