"""引导与回合结束之间的竞态：边界之前进回合，边界之后开新回合。

user:“审查并修复 Sunday 引导（Steer）与回合结束之间的竞态问题”+(
引导能否进入当前回合必须由一个原子的结束边界决定：
1) 边界之前收到的引导照常注入当前回合（内核继续）；
2) 越过边界（正在收尾/已经结束）之后收到的引导，原回合正常结束，这段文字必须
   走普通发送链路成为一条真实用户消息并自动开启新回合；
3) 不得伪造一条没人消费的 turn/steered，也不得靠强制 continue 延长收尾中的回合；
4) 同一请求重发只落一条消息；连续引导互不覆盖；投影不得凭空造出运行中的旧回合)。
"""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from lamtools_core.app.event_store import AppEventEnvelope
from lamtools_core.app.live.events import _append_run_item
from lamtools_core.app.live.runtime_tasks import _mirror_turn_status
from lamtools_core.app.live_operations import (
    handle_turn_start_operation,
    handle_turn_steer_operation,
    wait_live_background_tasks,
)
from lamtools_core.app.snapshot_store import CoreAppSnapshotProjector
from lamtools_core.event import CollectingEventSink, RunItemEvent
from lamtools_core.kernel import CoreLoopKernel, LoopPolicy
from lamtools_core.llm import LLMResponse
from lamtools_core.runtime import (
    RuntimeState,
    RuntimeTaskRegistry,
    RuntimeTurnInput,
)

from .test_core_live import _context, _register_blocking_turn_start
from .test_kernel import MockKitStep, MockRuntimeKit, _make_kernel, _make_turn_input


# ---------------------------------------------------------------------------
# Registry / kernel: the end boundary is an atomic state transition
# ---------------------------------------------------------------------------


async def _register_idle_run(registry: RuntimeTaskRegistry, thread_id: str, run_id: str) -> asyncio.Task[None]:
    async def _idle() -> None:
        await asyncio.sleep(60)

    task = asyncio.create_task(_idle())
    assert registry.accept_run(thread_id, run_id, turn_id=run_id) is True
    assert registry.register(thread_id, task, run_id=run_id, turn_id=run_id) is True
    return task


async def _stop(task: asyncio.Task[None]) -> None:
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def test_seal_refuses_later_steering_and_keeps_what_was_already_accepted():
    registry = RuntimeTaskRegistry()
    task = await _register_idle_run(registry, "boundary-thread", "boundary-run")
    try:
        assert registry.accept_guidance(
            "boundary-thread", "before the boundary", run_id="boundary-run", guidance_id="g-before",
        ) == "accepted"
        # 封口是同步原子转换：它之后到达的引导一律拒绝，调用方据此开新回合。
        assert registry.seal_guidance("boundary-thread", run_id="boundary-run") is True
        assert registry.accept_guidance(
            "boundary-thread", "after the boundary", run_id="boundary-run", guidance_id="g-after",
        ) == "closed"
        # 边界之前收下的那条仍然属于这一回合，不会被封口抹掉。
        offered = registry.offer_guidance("boundary-thread", run_id="boundary-run")
        assert [item["content"] for item in offered] == ["before the boundary"]
        registry.acknowledge_guidance(
            "boundary-thread", run_id="boundary-run", guidance_ids=["g-before"],
        )
        assert registry.accept_guidance(
            "boundary-thread", "still after", run_id="boundary-run", guidance_id="g-later",
        ) == "closed"
    finally:
        await _stop(task)


async def test_releasing_a_run_seals_guidance_before_it_disappears():
    registry = RuntimeTaskRegistry()
    task = await _register_idle_run(registry, "release-thread", "release-run")
    try:
        registry.release_run("release-thread", run_id="release-run")
        assert registry.accept_guidance(
            "release-thread", "too late", run_id="release-run", guidance_id="g-late",
        ) == "not_active"
        assert registry.guidance_is_open("release-thread", run_id="release-run") is False
    finally:
        await _stop(task)


@pytest.mark.asyncio
async def test_kernel_seals_guidance_at_every_terminal_exit():
    """A waiting turn is a terminal exit too: its guidance intake closes there."""
    registry = RuntimeTaskRegistry()
    thread_id, run_id = "wait-thread", "wait-run"
    task = await _register_idle_run(registry, thread_id, run_id)
    try:
        kernel = _make_kernel(MockRuntimeKit([MockKitStep(reply="need your choice", decision="wait")]))
        result = await kernel.run(RuntimeTurnInput(
            user_message="start",
            run_id=run_id,
            turn_id=run_id,
            metadata={"session_id": thread_id},
            guidance_source=registry.guidance_source(thread_id, run_id=run_id),
            guidance_finalizer=registry.guidance_finalizer(thread_id, run_id=run_id),
            guidance_sealer=lambda: registry.seal_guidance(thread_id, run_id=run_id),
        ))
        assert result.decision == "wait"
        # 从前这里收下引导、却再没有任何人消费它（回合已停在 waiting）。
        assert registry.accept_guidance(
            thread_id, "answer typed late", run_id=run_id, guidance_id="late-wait",
        ) == "closed"
    finally:
        await _stop(task)


@pytest.mark.asyncio
async def test_compaction_failure_seals_the_boundary_instead_of_swallowing_guidance():
    """上下文压缩把这一轮判死时，边界同样要封口：晚到的引导改走新回合。"""
    from lamtools_core.context_compaction import ContextCompactionError

    registry = RuntimeTaskRegistry()
    thread_id, run_id = "compact-thread", "compact-run"
    task = await _register_idle_run(registry, thread_id, run_id)

    class CompactionBreaks(MockRuntimeKit):
        async def build_model_request(self, state, context):
            raise ContextCompactionError("summary provider unavailable")

    try:
        kernel = _make_kernel(CompactionBreaks([MockKitStep(decision="done")]))
        result = await kernel.run(RuntimeTurnInput(
            user_message="start",
            run_id=run_id,
            turn_id=run_id,
            metadata={"session_id": thread_id},
            guidance_source=registry.guidance_source(thread_id, run_id=run_id),
            guidance_finalizer=registry.guidance_finalizer(thread_id, run_id=run_id),
            guidance_sealer=lambda: registry.seal_guidance(thread_id, run_id=run_id),
        ))
        assert result.decision == "failed"
        assert registry.accept_guidance(
            thread_id, "late during compaction", run_id=run_id, guidance_id="late-compact",
        ) == "closed"
    finally:
        await _stop(task)


@pytest.mark.asyncio
async def test_guidance_during_tool_execution_lands_in_that_same_turn():
    """工具执行期间收下的引导属于当前回合：下一步的模型请求里能看到它。"""
    from lamtools_core.tool import ToolCall, ToolResult

    registry = RuntimeTaskRegistry()
    thread_id, run_id = "tool-thread", "tool-run"
    current = asyncio.current_task()
    assert current is not None
    assert registry.accept_run(thread_id, run_id, turn_id=run_id) is True
    assert registry.register(thread_id, current, run_id=run_id, turn_id=run_id) is True
    accepted: list[str] = []

    class GuidanceInTool(MockRuntimeKit):
        async def execute_tool(self, state, call):
            accepted.append(registry.accept_guidance(
                thread_id, "prefer the short path", run_id=run_id, guidance_id="g-tool",
            ))
            return ToolResult(call_id=call.id, name=call.name, content="tool output")

    kit = GuidanceInTool([
        MockKitStep(
            reply="running a tool",
            tool_calls=[ToolCall(id="call-1", name="lookup", arguments={})],
            decision="continue",
        ),
        MockKitStep(reply="done after tool", decision="done"),
    ])
    kernel = _make_kernel(kit)
    try:
        result = await kernel.run(RuntimeTurnInput(
            user_message="start",
            run_id=run_id,
            turn_id=run_id,
            metadata={"session_id": thread_id},
            guidance_source=registry.guidance_source(thread_id, run_id=run_id, include_metadata=True),
            guidance_finalizer=registry.guidance_finalizer(thread_id, run_id=run_id, include_metadata=True),
            guidance_sealer=lambda: registry.seal_guidance(thread_id, run_id=run_id),
        ))
        assert result.decision == "done"
        assert accepted == ["accepted"]
        assert any(
            message.content == "prefer the short path"
            for message in kit.context_histories[-1]
        )
        # 边界之后同样封口。
        assert registry.accept_guidance(
            thread_id, "after tool turn", run_id=run_id, guidance_id="g-after",
        ) == "closed"
    finally:
        registry.release_run(thread_id, run_id=run_id)


@pytest.mark.asyncio
async def test_guidance_accepted_before_the_boundary_still_continues_the_turn():
    """The boundary only refuses what arrives after it; in-turn guidance wins."""
    registry = RuntimeTaskRegistry()
    thread_id, run_id = "open-thread", "open-run"
    current = asyncio.current_task()
    assert current is not None
    assert registry.accept_run(thread_id, run_id, turn_id=run_id) is True
    assert registry.register(thread_id, current, run_id=run_id, turn_id=run_id) is True
    accepted = []

    class InjectingLLM:
        calls = 0

        async def stream(self, request):
            raise NotImplementedError

        async def complete(self, request):
            self.calls += 1
            if self.calls == 1:
                accepted.append(registry.accept_guidance(
                    thread_id, "use the safer path", run_id=run_id, guidance_id="g-open",
                ))
            return LLMResponse(content="Final")

    llm = InjectingLLM()
    sink = CollectingEventSink()
    kernel = _make_kernel(
        MockRuntimeKit([
            MockKitStep(reply="first final", decision="done"),
            MockKitStep(reply="guided final", decision="done"),
        ]),
        llm_client=llm,
        event_sink=sink,
    )
    try:
        result = await kernel.run(RuntimeTurnInput(
            user_message="start",
            run_id=run_id,
            turn_id=run_id,
            metadata={"session_id": thread_id},
            guidance_source=registry.guidance_source(thread_id, run_id=run_id, include_metadata=True),
            guidance_finalizer=registry.guidance_finalizer(thread_id, run_id=run_id, include_metadata=True),
            guidance_sealer=lambda: registry.seal_guidance(thread_id, run_id=run_id),
        ))
        assert result.decision == "done"
        assert accepted == ["accepted"]
        assert [
            event.payload["content"] for event in sink.events if event.name == "runtime.guidance_received"
        ] == ["use the safer path"]
        assert registry.accept_guidance(
            thread_id, "after", run_id=run_id, guidance_id="g-after",
        ) == "closed"
    finally:
        registry.release_run(thread_id, run_id=run_id)


# ---------------------------------------------------------------------------
# turn/steer: a refusal becomes a real user message, never a phantom steer
# ---------------------------------------------------------------------------


def _steer_params(thread_id: str, turn_id: str, client_id: str, text: str) -> dict:
    return {
        "thread_id": thread_id,
        "turn_id": turn_id,
        "client_message_id": client_id,
        "input": [{"type": "text", "text": text}],
    }


async def _settle_turn(context, thread_id: str, turn_id: str) -> None:
    """Commit the terminal status a real runtime writes when its reply is done."""
    terminal = RunItemEvent(
        kind="status",
        thread_id=thread_id,
        event_id=f"{turn_id}:terminal",
        run_id=turn_id,
        turn_id=turn_id,
        item_id=f"{turn_id}:terminal",
        status="completed",
    )

    async def write(db):
        return await _append_run_item(db, context=context, event=terminal)

    event = await context.persistence.write(write)
    await context.hub.publish(event)
    await _mirror_turn_status(
        context=context, thread_id=thread_id, turn_id=turn_id, status="completed",
    )


async def _thread_events(context, thread_id: str) -> list[AppEventEnvelope]:
    async with context.session_factory() as db:
        return await context.persistence.list_thread(db, thread_id=thread_id)


def _user_messages(events: list[AppEventEnvelope], turn_id: str) -> list[AppEventEnvelope]:
    """The conversation row a normal send writes for its user input."""
    return [
        event for event in events
        if event.method == "item/started"
        and event.turn_id == turn_id
        and event.payload.get("type") == "userMessage"
    ]


async def _snapshot(context, thread_id: str) -> dict:
    async with context.session_factory() as db:
        return await context.persistence.load(db, thread_id)


@pytest.mark.asyncio
async def test_steer_past_the_end_boundary_opens_a_real_user_turn(tmp_path):
    engine, context = await _context(tmp_path)
    thread_id = "thread-steer-boundary"
    release = _register_blocking_turn_start(context)
    try:
        started = await handle_turn_start_operation(request_id=1, params={
            "thread_id": thread_id,
            "client_message_id": "start-1",
            "input": [{"type": "text", "text": "start"}],
        }, context=context)
        turn_id = started.response["result"]["runtime_start"]["turn_id"]
        # 越过结束边界：内核在此封口，回合随后正常结束。
        assert context.runtime_task_registry.seal_guidance(thread_id, run_id=turn_id) is True
        await _settle_turn(context, thread_id, turn_id)
        context.runtime_task_registry.release_run(thread_id, run_id=turn_id)

        steered = await handle_turn_steer_operation(
            request_id=2,
            params=_steer_params(thread_id, turn_id, "steer-after-end", "now do the other thing"),
            context=context,
        )

        result = steered.response["result"]
        assert result["applied"] is False
        assert result["reason"] == "run_not_active"
        assert result["submitted"] is True
        assert result["queued"] is False
        new_turn_id = result["turn_id"]
        assert new_turn_id and new_turn_id != turn_id

        events = await _thread_events(context, thread_id)
        # 没有任何伪造的引导事件：这段文字只以一条真实用户消息存在。
        assert [event for event in events if event.method == "turn/steered"] == []
        accepted = [
            event for event in events
            if event.method == "turn/accepted" and event.client_message_id == "steer-after-end"
        ]
        assert len(accepted) == 1
        user_items = _user_messages(events, new_turn_id)
        assert len(user_items) == 1
        assert "now do the other thing" in str(user_items[0].payload.get("content") or user_items[0].payload)

        # 旧回合有终态、新回合是唯一的活动回合：不存在幽灵运行态。
        snapshot = await _snapshot(context, thread_id)
        turns = {**(snapshot.get("turns") or {}), **((snapshot.get("core") or {}).get("turns") or {})}
        assert turns[turn_id]["status"] == "completed"
        active = [
            key for key, turn in turns.items()
            if isinstance(turn, dict) and str(turn.get("status") or "") in {"running", "waiting"}
        ]
        assert active == [new_turn_id]
        assert snapshot["status"] in {"running", "waiting"}

        # 断线重连后读同一份快照：这条用户消息与普通发送落库的那条完全一样，
        # 而且归属新回合（不是旧回合里的引导气泡）。
        items = snapshot.get("items") or {}
        new_bubbles = [
            item for item in items.values()
            if str(item.get("turn_id") or "") == new_turn_id
            and str(item.get("type") or "") == "userMessage"
        ]
        assert len(new_bubbles) == 1
        assert "now do the other thing" in str(new_bubbles[0].get("content"))
        old_bubbles = [
            item for item in items.values()
            if str(item.get("turn_id") or "") == turn_id
            and "now do the other thing" in str(item.get("content"))
        ]
        assert old_bubbles == []
    finally:
        release.set()
        task = context.runtime_task_registry.task(thread_id)
        if task is not None:
            await task
        await wait_live_background_tasks()
        await engine.dispose()


@pytest.mark.asyncio
async def test_repeated_steer_request_submits_exactly_one_new_turn(tmp_path):
    engine, context = await _context(tmp_path)
    thread_id = "thread-steer-retry"
    release = _register_blocking_turn_start(context)
    try:
        started = await handle_turn_start_operation(request_id=1, params={
            "thread_id": thread_id,
            "client_message_id": "start-retry",
            "input": [{"type": "text", "text": "start"}],
        }, context=context)
        turn_id = started.response["result"]["runtime_start"]["turn_id"]
        context.runtime_task_registry.seal_guidance(thread_id, run_id=turn_id)
        await _settle_turn(context, thread_id, turn_id)
        context.runtime_task_registry.release_run(thread_id, run_id=turn_id)
        params = _steer_params(thread_id, turn_id, "steer-retry", "only once")

        first = await handle_turn_steer_operation(request_id=2, params=params, context=context)
        second = await handle_turn_steer_operation(request_id=3, params=params, context=context)

        assert first.response["result"]["submitted"] is True
        assert second.response["result"]["submitted"] is True
        assert first.response["result"]["turn_id"] == second.response["result"]["turn_id"]

        events = await _thread_events(context, thread_id)
        accepted = [
            event for event in events
            if event.method == "turn/accepted" and event.client_message_id == "steer-retry"
        ]
        assert len(accepted) == 1
        assert [event for event in events if event.method == "turn/steered"] == []
        # 第一条是开局的用户消息，第二条是这次重试只落一次的那条。
        assert sum(
            1 for event in events
            if event.method == "item/started" and event.payload.get("type") == "userMessage"
        ) == 2
    finally:
        release.set()
        task = context.runtime_task_registry.task(thread_id)
        if task is not None:
            await task
        await wait_live_background_tasks()
        await engine.dispose()


@pytest.mark.asyncio
async def test_steer_while_the_turn_is_still_finishing_queues_and_auto_starts_the_next_turn(tmp_path):
    engine, context = await _context(tmp_path)
    thread_id = "thread-steer-finishing"
    release = _register_blocking_turn_start(context)
    try:
        started = await handle_turn_start_operation(request_id=1, params={
            "thread_id": thread_id,
            "client_message_id": "start-finishing",
            "input": [{"type": "text", "text": "start"}],
        }, context=context)
        turn_id = started.response["result"]["runtime_start"]["turn_id"]
        # 结束边界已过，但回合还在收尾（运行任务仍被占用）：不能抢开第二个回合。
        context.runtime_task_registry.seal_guidance(thread_id, run_id=turn_id)

        steered = await handle_turn_steer_operation(
            request_id=2,
            params=_steer_params(thread_id, turn_id, "steer-finishing", "after this one"),
            context=context,
        )
        result = steered.response["result"]
        assert result["applied"] is False
        assert result["submitted"] is False
        assert result["queued"] is True
        assert context.runtime_task_registry.active_run_id(thread_id) == turn_id

        # 旧回合收尾后队列自己发出这条消息：真实用户消息 + 新回合。
        release.set()
        task = context.runtime_task_registry.task(thread_id)
        if task is not None:
            await task
        await wait_live_background_tasks()

        events = await _thread_events(context, thread_id)
        assert [event for event in events if event.method == "turn/steered"] == []
        dispatched = [event for event in events if event.method == "turn/accepted" and event.turn_id != turn_id]
        assert len(dispatched) == 1
        new_turn_id = dispatched[0].turn_id
        user_items = _user_messages(events, new_turn_id)
        assert len(user_items) == 1
        assert "after this one" in str(user_items[0].payload)
        snapshot = await _snapshot(context, thread_id)
        queue = snapshot.get("queue") or []
        assert [item for item in queue if item.get("status") == "queued"] == []
    finally:
        release.set()
        for task in [
            context.runtime_task_registry.task(thread_id),
        ]:
            if task is not None:
                await task
        await wait_live_background_tasks()
        await engine.dispose()


@pytest.mark.asyncio
async def test_consecutive_steering_inside_the_turn_keeps_every_message_in_order(tmp_path):
    engine, context = await _context(tmp_path)
    thread_id = "thread-steer-consecutive"
    release = _register_blocking_turn_start(context)
    try:
        started = await handle_turn_start_operation(request_id=1, params={
            "thread_id": thread_id,
            "client_message_id": "start-consecutive",
            "input": [{"type": "text", "text": "start"}],
        }, context=context)
        turn_id = started.response["result"]["runtime_start"]["turn_id"]
        for index, text in enumerate(["first change", "second change"], start=1):
            steered = await handle_turn_steer_operation(
                request_id=index + 1,
                params=_steer_params(thread_id, turn_id, f"steer-{index}", text),
                context=context,
            )
            assert steered.response["result"]["applied"] is True
        offered = context.runtime_task_registry.offer_guidance(thread_id, run_id=turn_id)
        assert [item["content"] for item in offered] == ["first change", "second change"]
        events = await _thread_events(context, thread_id)
        assert len([event for event in events if event.method == "turn/steered"]) == 2
    finally:
        release.set()
        task = context.runtime_task_registry.task(thread_id)
        if task is not None:
            await task
        await wait_live_background_tasks()
        await engine.dispose()


# ---------------------------------------------------------------------------
# Projection: guidance must never fabricate a running turn
# ---------------------------------------------------------------------------


def _envelope(seq: int, payload: dict, *, method: str, turn_id: str = "") -> AppEventEnvelope:
    return AppEventEnvelope(
        event_id=f"event-{seq}",
        protocol_version="core.app_server.v1",
        seq=seq,
        thread_id="proj-thread",
        method=method,
        payload=payload,
        created_at=datetime(2026, 1, 1, 0, 0, seq),
        turn_id=turn_id or None,
    )


def test_turn_steered_never_creates_or_revives_a_running_turn():
    projector = CoreAppSnapshotProjector(member_defaults={"queue": []})

    # 一个投影不认识的回合收到引导事件：不能凭空造出「运行中」的回合。
    unknown = projector.empty("proj-thread")
    unknown["turns"] = {"turn-1": {"turn_id": "turn-1", "status": "running", "last_seq": 2, "items": []}}
    after_unknown = projector.apply(unknown, _envelope(
        4, {"turn_id": "ghost-turn", "input": "late"}, method="turn/steered", turn_id="ghost-turn",
    ))
    assert "ghost-turn" not in after_unknown["turns"]
    # 也不改这条线程的活动回合。
    assert after_unknown["turns"]["turn-1"]["last_seq"] == 2

    # 已终态的回合收到引导事件：不能把 last_seq 顶到最新，让界面把它当活动回合。
    finished = projector.empty("proj-thread")
    finished["status"] = "completed"
    finished["turns"] = {
        "turn-1": {"turn_id": "turn-1", "status": "completed", "last_seq": 3, "items": []},
        "turn-2": {"turn_id": "turn-2", "status": "running", "last_seq": 5, "items": []},
    }
    after = projector.apply(finished, _envelope(
        9, {"turn_id": "turn-1", "input": "late"}, method="turn/steered", turn_id="turn-1",
    ))
    assert after["turns"]["turn-1"]["status"] == "completed"
    assert after["turns"]["turn-1"]["last_seq"] == 3

    # 活动回合照常接收追加输入（引导自身的能力不能因此消失）。
    live = projector.apply(finished, _envelope(
        10, {"turn_id": "turn-2", "input": "steer"}, method="turn/steered", turn_id="turn-2",
    ))
    assert live["turns"]["turn-2"]["last_seq"] == 10
    assert live["turns"]["turn-2"]["last_method"] == "turn/steered"
