"""Turn-boundary semantics when members outlive the main agent's turn.

The main agent now ENDS its turn when it is done and only background members
remain; the member-wake watchdog starts the continuation. These tests lock the
two halves of that contract: the kernel must not hold the turn open past a short
grace, and the ended turn must still let a member's own timeline keep updating
while a new user turn is allowed to start.
"""
from __future__ import annotations

import asyncio

import pytest

from lamtools_core.agent import SubAgentRunResult
from lamtools_core.app import CoreAppEventHub, OperationCatalog, open_core_app_db
import lamtools_core.app.default_agent as default_agent_module
from lamtools_core.app.default_agent import CoreAgentPaths, CoreAgentSpec, create_core_agent_operations
from lamtools_core.app.live_operations import CoreLiveContext, handle_turn_start_operation
from lamtools_core.event import CollectingEventSink, CoreEvent, RunItemEvent
from lamtools_core.kernel import CoreLoopKernel, LoopPolicy
from lamtools_core.kernel.state import KernelResult
from lamtools_core.llm import TAIL_SYSTEM_MESSAGE_MARKER, ChatMessage
from lamtools_core.llm.policy import RetryPolicy
from lamtools_core.runtime import (
    CompletionResult,
    InMemoryRuntimeStateStore,
    RuntimeState,
    RuntimeTaskRegistry,
    RuntimeTurnInput,
)
from lamtools_core.snapshot import apply_run_item_event, empty_thread_snapshot
from lamtools_core.sub_agent_supervisor import SubAgentSupervisor

from .test_kernel import (
    InMemoryStateStore,
    MockKitStep,
    MockLLMClient,
    MockRuntimeKit,
    _make_kernel,
    _make_turn_input,
)


class _FakeSupervisor:
    """A member that is running; records whether the turn tried to consume it."""

    def __init__(self, *, active: bool = True) -> None:
        self.active = active
        self.waited = 0.0
        self.drained = 0
        self.wait_turns: list[str] = []
        self.reports = 0

    async def drain_member_events(self):
        self.drained += 1
        return []

    async def has_active_members(self) -> bool:
        return self.active

    async def active_member_status(self):
        return [{"name": "worker", "status": "running", "running_ms": 1000}]

    async def wait_for_activity(self, timeout: float) -> str:
        self.waited = float(timeout)
        return "timeout"

    def note_member_wait_turn(self, turn_id: object) -> None:
        self.wait_turns.append(str(turn_id or ""))

    async def report_members_drained(self) -> bool:
        self.reports += 1
        return True


class _ContinueOnceGate:
    """Completion gate that rejects the first final answer, then accepts.

    This reproduces the exact path the members-running fact was mis-published
    on: the model returns a final no-tool answer, the gate sets ``continue``,
    and the turn keeps running.
    """

    def __init__(self) -> None:
        self.calls = 0

    def should_verify(self, state) -> bool:  # noqa: ANN001 - test double
        return True

    async def verify(self, state, context):  # noqa: ANN001 - test double
        self.calls += 1
        passed = self.calls > 1
        return CompletionResult(
            passed=passed,
            summary="goal check",
            repair_instruction="" if passed else "keep going",
        )


@pytest.mark.asyncio
async def test_member_wake_is_one_marked_system_history_entry_without_user_duplicate():
    kernel = _make_kernel(
        MockRuntimeKit([MockKitStep(reply="done", decision="done")]),
        state_store=InMemoryStateStore(),
    )
    state = RuntimeState(
        session_id="wake-history",
        status="completed",
        metadata={"turn_id": "turn-wake"},
    )
    history = [ChatMessage(role="user", content="prior task")]

    appended = await kernel._begin_run(
        state,
        RuntimeTurnInput(
            user_message="子代理 worker 已完成。",
            turn_id="turn-wake",
            metadata={"session_id": state.session_id, "origin": "member_wake"},
        ),
        history,
    )

    assert [message.role for message in appended] == ["system"]
    assert appended[0].metadata == {
        "origin": "member_wake",
        TAIL_SYSTEM_MESSAGE_MARKER: True,
        "turn_id": "turn-wake",
    }
    assert [message.role for message in history] == ["user", "system"]
    assert [message.content for message in history].count("子代理 worker 已完成。") == 1


@pytest.mark.asyncio
async def test_memory_resume_and_manual_turns_remain_user_history_entries():
    for metadata in (
        {"session_id": "normal-history"},
        {"session_id": "resume-history", "origin": "memory_resume"},
    ):
        kernel = _make_kernel(
            MockRuntimeKit([MockKitStep(reply="done", decision="done")]),
            state_store=InMemoryStateStore(),
        )
        state = RuntimeState(session_id=metadata["session_id"], status="completed")
        history: list[ChatMessage] = []
        appended = await kernel._begin_run(
            state,
            RuntimeTurnInput(user_message="continue", metadata=metadata),
            history,
        )
        assert [message.role for message in appended] == ["user"]
        assert not appended[0].metadata.get(TAIL_SYSTEM_MESSAGE_MARKER)


@pytest.mark.asyncio
async def test_done_never_consumes_or_waits_for_members(monkeypatch):
    """The turn announces running members but never drains or waits for them.

    A member's result must be its own NEXT turn through the wake path, so the
    ending turn can never fold it into the summary the user is reading. This is
    the structural guarantee: no consumption, no wait, regardless of when the
    event lands (while streaming, just before the terminal, or just after).
    """
    import lamtools_core.sub_agent_supervisor as supervisor_module

    fake = _FakeSupervisor(active=True)
    monkeypatch.setattr(supervisor_module, "find_sub_agent_supervisor", lambda _tid: fake)

    kernel = _make_kernel(MockRuntimeKit(), MockLLMClient())
    state = RuntimeState(
        session_id="s",
        run_id="r",
        status="running",
        metadata={"turn_id": "t"},
    )

    await kernel._announce_active_members(state, 0)

    assert fake.drained == 0
    assert fake.waited == 0.0
    emitted = [event.name for event in kernel.event_sink.events]
    assert "runtime.sub_agent_wait" in emitted
    wait_event = next(e for e in kernel.event_sink.events if e.name == "runtime.sub_agent_wait")
    assert [m["name"] for m in wait_event.payload["members"]] == ["worker"]
    assert wait_event.payload["wait_seconds"] == 0


def _run_item(**kwargs) -> RunItemEvent:
    return RunItemEvent(**kwargs)


@pytest.mark.asyncio
async def test_members_fact_is_published_only_after_the_turn_is_terminal(monkeypatch):
    """A turn that keeps running after a final answer must not carry the fact.

    The defect: the fact was written at the done decision, then the completion
    gate could set ``continue``, so the turn kept running with the fact already
    latched — and the interface reads any fact on a running turn as "the main
    agent stopped". Publishing only after the terminal status is written makes
    that impossible: the fact can never precede the terminal event.
    """
    import lamtools_core.sub_agent_supervisor as supervisor_module

    fake = _FakeSupervisor(active=True)
    monkeypatch.setattr(supervisor_module, "find_sub_agent_supervisor", lambda _tid: fake)

    kit = MockRuntimeKit([
        MockKitStep(reply="first final answer", decision="done"),
        MockKitStep(reply="second final answer", decision="done"),
    ])
    sink = CollectingEventSink()
    kernel = CoreLoopKernel(
        kit=kit,
        llm_client=MockLLMClient(),
        state_store=InMemoryStateStore(),
        event_sink=sink,
        policy=LoopPolicy(),
        retry_policy=RetryPolicy(),
        completion_gate=_ContinueOnceGate(),
    )

    result = await kernel.run(_make_turn_input())

    assert result.decision == "done"
    names = [event.name for event in sink.events]
    # The fact exists for the ended turn...
    assert "runtime.sub_agent_wait" in names
    # ...but only after the terminal event, never while the turn was running.
    assert names.index("runtime.done") < names.index("runtime.sub_agent_wait")
    # The fact is published once, and the supervisor is told which turn owns it
    # so it can retract it when the members finish.
    assert names.count("runtime.sub_agent_wait") == 1
    assert len(fake.wait_turns) == 1 and fake.wait_turns[0]


class _FinishRunner:
    """Minimal sub-agent runner that completes immediately, capturing reports."""

    def __init__(self, work_root) -> None:  # noqa: ANN001 - test double
        self.work_root = work_root
        self.parent_event_sink = CollectingEventSink()

    async def run(self, **kwargs):  # noqa: ANN003 - test double
        return SubAgentRunResult(
            session_id=f"parent:sub:{kwargs['agent']}",
            run_id="child-run",
            decision="done",
            model_id=kwargs["model"],
            message="done",
            ended_with_final_response=True,
        )


def _seed_model(root) -> None:  # noqa: ANN001 - test double
    directory = root / ".lam" / "config" / "models"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "test-model.jsonc").write_text(
        '{"model_id":"test-model","display_name":"Test Model"}', encoding="utf-8"
    )


@pytest.mark.asyncio
async def test_last_member_finishing_clears_the_members_running_fact(tmp_path):
    """The fact is retracted when the last member of the recorded turn finishes.

    Today nothing clears it (the only producer of a cleared fact is gone), so an
    ended turn advertises that its members are still running forever. The
    supervisor now publishes the retraction once nothing is left to run.
    """
    _seed_model(tmp_path)
    runner = _FinishRunner(tmp_path)
    supervisor = SubAgentSupervisor(
        parent_thread_id="parent",
        runner=runner,
        database_path=tmp_path / "state.sqlite3",
    )
    # The kernel published the members-running fact for this ended turn.
    supervisor.note_member_wait_turn("turn-1")
    await supervisor.create(
        type="consider", name="worker", model="test-model", reasoning_level="high"
    )
    await supervisor.message(type="consider", name="worker", prompt="do it")

    reports: list[CoreEvent] = []
    for _ in range(300):
        reports = [e for e in runner.parent_event_sink.events if e.name == "runtime.sub_agent_report"]
        if reports:
            break
        await asyncio.sleep(0.01)
    await asyncio.gather(
        *[task for task in supervisor._tasks.values() if not task.done()],
        return_exceptions=True,
    )

    assert reports, [event.name for event in runner.parent_event_sink.events]
    assert reports[-1].turn_id == "turn-1"
    assert reports[-1].payload == {"waiting_on_members": False, "members": []}
    # One-shot: a single drain publishes one retraction.
    assert len(reports) == 1

    # End to end: the retraction the supervisor published actually clears the
    # ended turn's fact through the same projection the interface reads.
    from datetime import datetime, timezone

    from lamtools_core.app.base_agent import core_events_to_run_items
    from lamtools_core.app.event_store import AppEventEnvelope
    from lamtools_core.app.snapshot_store import CoreAppSnapshotProjector

    projector = CoreAppSnapshotProjector()
    wait_event = CoreEvent(
        name="runtime.sub_agent_wait",
        category="message",
        payload={"wait_seconds": 0, "members": [{"name": "worker", "status": "running"}]},
        session_id="parent",
        turn_id="turn-1",
    )

    def envelope(seq: int, event: CoreEvent) -> AppEventEnvelope:
        item = core_events_to_run_items([event], thread_id="parent")[0]
        return AppEventEnvelope(
            event_id=f"e{seq}",
            protocol_version="v1",
            seq=seq,
            thread_id="parent",
            method="core/runItem",
            payload=item.to_dict(),
            created_at=datetime.now(timezone.utc),
            turn_id=item.turn_id,
            item_id=item.item_id,
        )

    state = projector.empty("parent")
    state = projector.apply(state, envelope(1, wait_event))
    assert state["turns"]["turn-1"]["waiting_on_members"] is True
    assert state["turns"]["turn-1"]["running_members"] == ["worker"]

    state = projector.apply(state, envelope(2, reports[-1]))
    assert state["turns"]["turn-1"]["waiting_on_members"] is False
    assert state["turns"]["turn-1"]["running_members"] == []


def test_member_timeline_keeps_updating_after_the_parent_turn_ended():
    """The parent turn is terminal, but the member it dispatched is not.

    A member's child items carry the parent's delegated tool row as
    ``parent_item_id``. When the parent turn ends while the member keeps
    working, those rows must keep their own status instead of being forced
    completed, and the ended turn must not re-open.
    """
    state = empty_thread_snapshot("thread-1")
    state = apply_run_item_event(state, _run_item(
        kind="status", thread_id="thread-1", event_id="s1", turn_id="turn-1",
        item_id="turn-1:running", status="running",
        payload={"type": "turn", "status": "running"},
    ))
    state = apply_run_item_event(state, _run_item(
        kind="status", thread_id="thread-1", event_id="s2", turn_id="turn-1",
        item_id="turn-1:terminal", status="completed",
        payload={"type": "turn", "status": "completed"},
    ))
    assert state["status"] == "completed"

    # A member tool call started by that turn keeps streaming afterwards.
    state = apply_run_item_event(state, _run_item(
        kind="tool_call", thread_id="thread-1", event_id="c1", run_id="turn-1",
        turn_id="turn-1", item_id="thread-1:sub:worker:call-1:tool",
        parent_item_id="thread-1:turn-1:call-0:tool", status="running",
        payload={"type": "dynamicToolCall", "tool_name": "read_file"},
    ))

    assert state["items"]["thread-1:sub:worker:call-1:tool"]["status"] == "running"
    assert state["turns"]["turn-1"]["status"] == "completed"
    assert state["status"] == "completed"

    # The member's own completion closes it, not the parent turn.
    state = apply_run_item_event(state, _run_item(
        kind="tool_result", thread_id="thread-1", event_id="c2", run_id="turn-1",
        turn_id="turn-1", item_id="thread-1:sub:worker:call-1:tool",
        parent_item_id="thread-1:turn-1:call-0:tool", status="completed",
        payload={"type": "dynamicToolCall", "delta": "ok"},
    ))
    assert state["items"]["thread-1:sub:worker:call-1:tool"]["status"] == "completed"


@pytest.mark.asyncio
async def test_turn_start_is_allowed_after_a_member_held_turn_ends(tmp_path):
    """Once the member-held turn is terminal, a user message starts a NEW turn.

    Before the change the turn was held "running", so ``turn.start`` answered
    SESSION_BUSY and the composer queued instead. With the turn ended, the
    backend accepts a fresh user turn.
    """
    db = await open_core_app_db(tmp_path / "core.db")
    store = InMemoryRuntimeStateStore()
    await store.save(RuntimeState(session_id="thread-m", run_id="turn-1", status="completed", metadata={}))
    context = CoreLiveContext(
        operations=OperationCatalog(),
        session_factory=db.session_factory,
        persistence=db.persistence,
        runtime_state_store=store,
        hub=CoreAppEventHub(),
    )
    try:
        async def write(db_session):
            return await context.persistence.append_batch(
                db_session,
                app_events=[],
                run_item_events=[
                    _run_item(
                        kind="status", thread_id="thread-m", event_id="t1", turn_id="turn-1",
                        item_id="turn-1:terminal", status="completed",
                        payload={"type": "turn", "status": "completed"},
                    )
                ],
            )

        await context.persistence.write(write)

        started = await handle_turn_start_operation(
            request_id=1,
            params={
                "thread_id": "thread-m",
                "client_message_id": "client-user",
                "input": [{"type": "text", "text": "carry on"}],
            },
            context=context,
        )
        assert "result" in started.response, started.response
        assert started.response["result"]["events"][0]["method"] == "turn/accepted"
    finally:
        await db.close()


def test_waiting_on_members_survives_the_turn_terminal_with_member_names():
    """The interface must still read "main agent stopped, these members run".

    The waiting-on-members fact is lifted onto the turn by the projector; the
    ended turn must keep it (with the member names) so the client can render the
    stopped state instead of a generic running spinner.
    """
    from datetime import datetime, timezone

    from lamtools_core.app.event_store import AppEventEnvelope
    from lamtools_core.app.snapshot_store import CoreAppSnapshotProjector

    projector = CoreAppSnapshotProjector(member_defaults={"queue": []})

    def envelope(seq: int, payload: dict, turn_id: str, item_id: str) -> AppEventEnvelope:
        return AppEventEnvelope(
            event_id=f"e{seq}",
            protocol_version="v1",
            seq=seq,
            thread_id="thread-1",
            method="core/runItem",
            payload=payload,
            created_at=datetime.now(timezone.utc),
            turn_id=turn_id,
            item_id=item_id,
        )

    wait = {
        "kind": "status", "thread_id": "thread-1", "event_id": "w",
        "turn_id": "turn-1", "item_id": "turn-1:sub-agent-wait", "status": "running",
        "payload": {
            "type": "subAgents", "status": "running", "waiting_on_members": True,
            "members": [{"name": "store_graph_v2", "status": "running", "running_ms": 1000}],
        },
    }
    terminal = {
        "kind": "status", "thread_id": "thread-1", "event_id": "t",
        "turn_id": "turn-1", "item_id": "turn-1:terminal", "status": "completed",
        "payload": {"type": "turn", "status": "completed"},
    }

    state = projector.reduce("thread-1", [
        envelope(1, wait, "turn-1", "turn-1:sub-agent-wait"),
        envelope(2, terminal, "turn-1", "turn-1:terminal"),
    ])

    assert state["status"] == "completed"
    assert state["turns"]["turn-1"]["status"] == "completed"
    assert state["turns"]["turn-1"]["waiting_on_members"] is True
    assert state["turns"]["turn-1"]["running_members"] == ["store_graph_v2"]


async def _open_context(tmp_path):
    db = await open_core_app_db(tmp_path / "core.db")
    store = InMemoryRuntimeStateStore()
    context = CoreLiveContext(
        operations=OperationCatalog(),
        session_factory=db.session_factory,
        persistence=db.persistence,
        runtime_state_store=store,
        runtime_task_registry=RuntimeTaskRegistry(),
        hub=CoreAppEventHub(),
    )
    return db, context


async def _seed_event(context, thread_id: str, *, turn_id: str, status: str) -> int:
    async def write(db_session):
        return await context.persistence.append_batch(
            db_session,
            run_item_events=[
                _run_item(
                    kind="status", thread_id=thread_id, event_id=f"{turn_id}:{status}",
                    turn_id=turn_id, item_id=f"{turn_id}:{status}", status=status,
                    payload={"type": "turn", "status": status},
                )
            ],
        )

    await context.persistence.write(write)
    async with context.session_factory() as db:
        return await context.persistence.current_revision(db, thread_id)


@pytest.mark.asyncio
async def test_turn_start_is_accepted_with_a_stale_revision_when_no_turn_is_active(tmp_path):
    """A new turn is an append; a stale client revision must not block it.

    The revision advances by itself (background members keep appending), so a
    client can never supply a current value. Nothing is read-modify-written here,
    so the revision CAS on turn creation is over-strict.
    """
    db, context = await _open_context(tmp_path)
    try:
        current = await _seed_event(context, "thread-s", turn_id="turn-old", status="completed")
        started = await handle_turn_start_operation(
            request_id=1,
            params={
                "thread_id": "thread-s",
                "client_message_id": "client-stale",
                "input": [{"type": "text", "text": "hello"}],
                "expected_revision": max(0, current - 1),
            },
            context=context,
        )
        assert "result" in started.response, started.response
        assert started.response["result"]["events"][0]["method"] == "turn/accepted"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_turn_start_reports_busy_not_a_revision_conflict_when_a_turn_is_active(tmp_path):
    """With a live turn the answer must be SESSION_BUSY, not a revision conflict.

    The CAS fired before the active-turn check, so a stale revision masked the
    real state ("a turn is already running") with a misleading revision error the
    client retried forever.
    """
    db, context = await _open_context(tmp_path)
    try:
        await _seed_event(context, "thread-busy", turn_id="turn-live", status="running")
        current = await _seed_event(context, "thread-busy", turn_id="turn-live", status="running")
        blocked = await handle_turn_start_operation(
            request_id=1,
            params={
                "thread_id": "thread-busy",
                "client_message_id": "client-busy",
                "input": [{"type": "text", "text": "hello"}],
                "expected_revision": max(0, current - 1),
            },
            context=context,
        )
        error = blocked.response.get("error")
        assert error is not None, blocked.response
        assert error["data"]["code"] == "SESSION_BUSY", error
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_turn_start_reports_busy_immediately_when_the_run_is_already_claimed(tmp_path):
    """A claimed run short-circuits turn/start before the serialized wait.

    The answer cannot change while the request queues behind the session actor
    and the write coordinator, so a busy session should answer at once instead of
    after 1.6-26.5 seconds of streaming.
    """
    db, context = await _open_context(tmp_path)
    try:
        assert context.runtime_task_registry.accept_run("thread-fast", "turn-active")
        outcome = await context.host.execute(
            "turn.start",
            request_id=1,
            params={
                "thread_id": "thread-fast",
                "client_message_id": "client-fast",
                "input": [{"type": "text", "text": "hi"}],
            },
            context=context,
        )
        error = outcome.response.get("error")
        assert error is not None, outcome.response
        assert error["data"]["code"] == "SESSION_BUSY"
        assert error["data"]["active_run_id"] == "turn-active"
    finally:
        context.runtime_task_registry.release_run("thread-fast", run_id="turn-active")
        await db.close()


@pytest.mark.asyncio
async def test_queued_message_is_dispatched_as_a_new_turn_when_the_turn_ends(tmp_path):
    """End to end: queue during an active turn, dispatch it when the turn ends.

    The queue is only useful if the message actually goes out; this runs the whole
    sequence once (active turn -> queue create -> terminal -> dispatch) instead of
    proving the two halves separately.
    """
    from lamtools_core.app import OperationResult
    from lamtools_core.app import live_operations as live_operations_module
    from lamtools_core.app.live_operations import handle_queue_create_operation

    db, context = await _open_context(tmp_path)
    started: list[dict] = []

    async def stub_turn_start(request):
        started.append(dict(request.payload))
        return OperationResult(name="turn.start", payload={"ok": True})

    context.operations.register("turn.start", stub_turn_start)
    try:
        await _seed_event(context, "thread-q", turn_id="turn-A", status="running")
        assert context.runtime_task_registry.accept_run("thread-q", "turn-A")

        queued = await handle_queue_create_operation(
            request_id=1,
            params={
                "thread_id": "thread-q",
                "client_message_id": "client-queued",
                "input": [{"type": "text", "text": "next please"}],
            },
            context=context,
        )
        queue_item_id = queued.response["result"]["queue_item"]["queue_item_id"]
        async with context.session_factory() as db_session:
            metadata = await context.persistence.load_metadata(db_session, "thread-q")
        assert [item["queue_item_id"] for item in metadata["queue"]] == [queue_item_id]
        assert metadata["queue"][0]["status"] == "queued"

        # The kernel ends the turn (natural completion under the new behaviour).
        await _seed_event(context, "thread-q", turn_id="turn-A", status="completed")

        await live_operations_module._dispatch_next_queue_item(
            context=context,
            thread_id="thread-q",
            work_root=str(tmp_path),
            completed_turn_id="turn-A",
        )

        async with context.session_factory() as db_session:
            metadata = await context.persistence.load_metadata(db_session, "thread-q")
            events = await context.persistence.list_thread(db_session, thread_id="thread-q")
        assert metadata["queue"] == []
        methods = [event.method for event in events]
        assert "queue/itemDispatched" in methods
        accepted = [event for event in events if event.method == "turn/accepted"]
        assert len(accepted) == 1
        assert accepted[0].payload["input"] == [{"type": "text", "text": "next please"}]
        assert started, "the dispatched turn was not started"
    finally:
        task = context.runtime_task_registry.task("thread-q")
        if task is not None:
            task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=5)
            except BaseException:
                pass
        context.runtime_task_registry.clear()
        await db.close()


@pytest.mark.asyncio
async def test_wake_turn_is_marked_and_a_user_turn_is_not(tmp_path):
    """A wake continuation must be identifiable as a system event in the snapshot.

    The wake input renders like a system message once it carries provenance; the
    turn and its input item both carry ``origin == "member_wake"``, and an
    ordinary user turn carries no ``origin``. The kernel also receives that
    provenance so it can keep the model-visible wake entry marked as system.
    """
    db, context = await _open_context(tmp_path)
    try:
        wake = await handle_turn_start_operation(
            request_id=1,
            params={
                "thread_id": "thread-w",
                "client_message_id": "client-wake",
                "input": [{"type": "text", "text": "member event"}],
                "origin": "member_wake",
            },
            context=context,
        )
        assert "result" in wake.response, wake.response
        turn_id = wake.response["result"]["runtime_start"]["turn_id"]
        user_item_id = wake.response["result"]["runtime_start"]["user_message_id"]
        async with context.session_factory() as db_session:
            snapshot = await context.persistence.load(db_session, "thread-w")
        assert snapshot["turns"][turn_id]["origin"] == "member_wake"
        assert snapshot["items"][user_item_id]["origin"] == "member_wake"
        # A system message, not the user's input.
        assert snapshot["items"][user_item_id]["type"] == "systemMessage"
        assert snapshot["items"][user_item_id]["role"] == "system"

        user = await handle_turn_start_operation(
            request_id=2,
            params={
                "thread_id": "thread-u",
                "client_message_id": "client-user",
                "input": [{"type": "text", "text": "hi"}],
            },
            context=context,
        )
        assert "result" in user.response, user.response
        user_turn_id = user.response["result"]["runtime_start"]["turn_id"]
        user_item = user.response["result"]["runtime_start"]["user_message_id"]
        async with context.session_factory() as db_session:
            snapshot_u = await context.persistence.load(db_session, "thread-u")
        assert "origin" not in snapshot_u["turns"][user_turn_id]
        assert "origin" not in snapshot_u["items"][user_item]
        assert snapshot_u["items"][user_item]["type"] == "userMessage"
    finally:
        context.runtime_task_registry.clear()
        await db.close()


@pytest.mark.asyncio
async def test_live_runtime_start_origin_reaches_kernel_metadata(tmp_path, monkeypatch):
    """The live runtime payload keeps ``member_wake`` through the real operation path."""
    db = await open_core_app_db(tmp_path / "core.db")
    captured: dict[str, RuntimeTurnInput] = {}

    class CapturingKernel:
        async def run(self, turn_input: RuntimeTurnInput) -> KernelResult:
            captured["input"] = turn_input
            return KernelResult(
                session_id=turn_input.metadata["session_id"],
                run_id=turn_input.run_id,
                decision="done",
                message="done",
            )

    monkeypatch.setattr(default_agent_module, "create_kernel", lambda **_kwargs: CapturingKernel())
    catalog = create_core_agent_operations(
        spec=CoreAgentSpec(),
        paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=tmp_path / "work"),
        model_provider=MockLLMClient(),
        db_session_factory=db.session_factory,
        app_event_store=db.event_store,
        thread_snapshot_store=db.snapshot_store,
        runtime_state_store=db.runtime_state_store,
    )
    context = CoreLiveContext(
        operations=catalog,
        session_factory=db.session_factory,
        persistence=db.persistence,
        runtime_state_store=db.runtime_state_store,
        runtime_task_registry=RuntimeTaskRegistry(),
        hub=CoreAppEventHub(),
    )
    try:
        outcome = await handle_turn_start_operation(
            request_id=1,
            params={
                "thread_id": "thread-wake-kernel",
                "client_message_id": "client-wake-kernel",
                "input": [{"type": "text", "text": "member event"}],
                "origin": "member_wake",
            },
            context=context,
        )
        assert "result" in outcome.response, outcome.response
        assert outcome.runtime_start is not None
        assert outcome.runtime_start["origin"] == "member_wake"
        task = context.runtime_task_registry.task("thread-wake-kernel")
        assert task is not None
        await task
        assert captured["input"].metadata["origin"] == "member_wake"
    finally:
        context.runtime_task_registry.clear()
        await db.close()


def test_member_wake_prompt_is_minimal_and_templated():
    """The wake line is the shortest form of the fact; no banner, no coaching.

    Fully templated from the stored event (name/event/summary), so no model call
    is involved. The member's full report stays in its own timeline.
    """
    from lamtools_core.sub_agent_supervisor import member_wake_prompt

    assert member_wake_prompt(
        [{"payload": {"event": "member_finished", "name": "worker"}}]
    ) == "子代理 worker 已完成。"
    assert member_wake_prompt(
        [{"payload": {"event": "member_finished", "name": "worker", "summary": "改好了 3 个文件"}}]
    ) == "子代理 worker 已完成：改好了 3 个文件"
    assert member_wake_prompt(
        [{"payload": {"event": "member_failed", "name": "beta", "summary": "boom"}}]
    ) == "子代理 beta 已失败：boom"
    assert member_wake_prompt(
        [{"payload": {
            "event": "member_interrupted", "name": "renderer",
            "detail": "进程重启时该成员仍在运行",
        }}]
    ) == "子代理 renderer 已中断，原因：进程重启时该成员仍在运行。"
    text = member_wake_prompt([{"payload": {"event": "member_finished", "name": "worker"}}])
    assert "【子代理事件】" not in text
    assert "请据此继续" not in text
