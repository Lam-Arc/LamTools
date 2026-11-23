"""引导的回合归属由「最终 Step 的结果」决定，而不是到达时的回合状态。

user:“引导的回合归属，应由其所在 Step 的最终结果决定，而不是引导到达时的回合状态”
user:“最终 Step 开始后收到的所有引导，都应开启下一回合，而不是续接当前回合”

契约：
- 模型输出期间收到的引导：正常接收，归属未定。
- 该步有工具调用 → 引导在当前回合消费（下一步开头进历史）。
- 该步无工具调用（自然结束）→ 引导不in本回合消费，由执行层投成下一回合。
- Step 结束到回合正式关闭之间到达的引导：同样归属下一回合。
- 不丢失、不重复消费；界面项只在真正被回合消费时出现（旧回合里不出现引导项）。
"""
from __future__ import annotations

import asyncio

import pytest

from lamtools_core.app.live_operations import (
    handle_turn_start_operation,
    handle_turn_steer_operation,
    wait_live_background_tasks,
)
from lamtools_core.app.steering import GUIDANCE_CONSUMED_METHOD, pending_steering
from lamtools_core.kernel import CoreLoopKernel
from lamtools_core.llm import LLMStreamEvent, LLMToolCall
from lamtools_core.runtime import RuntimeTaskRegistry
from lamtools_core.tool import ToolCall, ToolResult

from tests.test_guidance_consumption_durable import _model_dir, context_for
from tests.test_kernel import MockKitStep, MockRuntimeKit, _make_kernel


# ── 内核层：步的最终结果决定归属 ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_natural_end_step_defers_guidance_instead_of_continuing():
    """无工具调用的步就是最终步：尾部引导不得把它续成下一步。"""
    registry = RuntimeTaskRegistry()
    current_task = asyncio.current_task()
    assert current_task is not None
    assert registry.accept_run("tail-thread", "tail-run") is True
    assert registry.register("tail-thread", current_task, run_id="tail-run") is True

    class GuidanceDuringAnswerKit(MockRuntimeKit):
        """在模型「输出答复」期间收到一条引导（归属未定）。"""

        async def parse_model_output(self, state, response):
            assert registry.accept_guidance(
                "tail-thread",
                "MUST_GO_TO_NEXT_TURN",
                run_id="tail-run",
                guidance_id="guidance-tail",
            ) == "accepted"
            return await super().parse_model_output(state, response)

    kit = GuidanceDuringAnswerKit([MockKitStep(reply="final answer", decision="done")])
    kernel = _make_kernel(kit)
    result = await kernel.run(_turn_input(
        registry=registry,
        session_id="tail-thread",
        run_id="tail-run",
    ))

    assert result.decision == "done"
    # 只有一步：没有因为尾部引导再要一轮模型。
    assert kit.build_context_calls == [0]
    # 引导没有进本回合的历史。
    assert all(
        message.content != "MUST_GO_TO_NEXT_TURN"
        for history in kit.context_histories
        for message in history
    )
    # 引导也没有被消费掉（执行层还要把它投成下一回合）。
    assert registry.consume_guidance("tail-thread", run_id="tail-run") == ["MUST_GO_TO_NEXT_TURN"]


@pytest.mark.asyncio
async def test_tool_step_still_consumes_guidance_in_the_same_turn():
    """有工具调用的步：引导仍归当前回合，在下一步开头进历史。"""
    registry = RuntimeTaskRegistry()
    current_task = asyncio.current_task()
    assert current_task is not None
    assert registry.accept_run("tool-thread", "tool-run") is True
    assert registry.register("tool-thread", current_task, run_id="tool-run") is True
    call = ToolCall(id="call-1", name="run_command", arguments={"command": "step"})

    class GuidanceDuringToolKit(MockRuntimeKit):
        async def execute_tool(self, state, call):
            assert registry.accept_guidance(
                "tool-thread",
                "STAYS_IN_TURN",
                run_id="tool-run",
                guidance_id="guidance-tool",
            ) == "accepted"
            return ToolResult(call_id=call.id, name=call.name, content="ok")

    kit = GuidanceDuringToolKit([
        MockKitStep(tool_calls=[call], decision="continue"),
        MockKitStep(reply="done", decision="done"),
    ])
    kernel = _make_kernel(kit)
    result = await kernel.run(_turn_input(
        registry=registry,
        session_id="tool-thread",
        run_id="tool-run",
    ))

    assert result.decision == "done"
    assert kit.build_context_calls == [0, 1]
    assert any(
        message.role == "user" and message.content == "STAYS_IN_TURN"
        for message in kit.context_histories[1]
    )


def _turn_input(*, registry: RuntimeTaskRegistry, session_id: str, run_id: str):
    from lamtools_core.runtime import RuntimeTurnInput

    return RuntimeTurnInput(
        user_message="start",
        run_id=run_id,
        turn_id=run_id,
        metadata={"session_id": session_id},
        guidance_source=registry.guidance_source(session_id, run_id=run_id),
        guidance_finalizer=registry.guidance_finalizer(session_id, run_id=run_id),
        guidance_sealer=lambda: registry.seal_guidance(session_id, run_id=run_id),
        # user:“最终 Step 开始后收到的所有引导，都应开启下一回合”+(主回合开启；
        # 子代理的补充消息仍走原有语义，见 sub_agent_runner)。
        defer_tail_guidance=True,
    )


# ── 执行层：尾部引导投成新回合 ──────────────────────────────────────────────


class TailModel:
    """第一回合：输出答复期间挂起，等待测试把引导插进来。"""

    def __init__(self) -> None:
        self.requests: list[object] = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def complete(self, request):
        raise AssertionError("scripted stream only")

    async def stream(self, request):
        self.requests.append(request)
        yield LLMStreamEvent(kind="content_delta", content=f"answer-{len(self.requests)}")
        if len(self.requests) == 1:
            self.entered.set()
            await self.release.wait()
        yield LLMStreamEvent(kind="done")


@pytest.mark.asyncio
async def test_live_tail_guidance_opens_a_new_turn(tmp_path, monkeypatch):
    """答复已经在出的时候插进来的引导：不进本回合，另开一个新回合。"""
    _model_dir(tmp_path)
    model = TailModel()

    async def tool(self, state, call, **kwargs):  # pragma: no cover - 本用例不用工具
        return ToolResult(call_id=call.id, name=call.name, status="ok", content="ok")

    monkeypatch.setattr(CoreLoopKernel, "_execute_tool", tool)
    db = await open_core_app_db_for(tmp_path)
    context = await context_for(db, tmp_path, model)
    try:
        accepted = await handle_turn_start_operation(request_id=1, params={
            "thread_id": "thread", "input": [{"type": "text", "text": "task"}],
            "model_id": "fixture", "permission_preset": "full_access", "include_snapshot": False,
        }, context=context)
        first_turn = accepted.runtime_start["turn_id"]
        await asyncio.wait_for(model.entered.wait(), 10)

        steered = await handle_turn_steer_operation(request_id=2, params={
            "thread_id": "thread", "turn_id": first_turn, "client_message_id": "g-tail",
            "input": [{"type": "text", "text": "NEXT_TURN_TEXT"}], "include_snapshot": False,
        }, context=context)
        assert steered.response["result"]["applied"] is True, steered.response

        model.release.set()
        task = context.runtime_task_registry.task("thread")
        if task:
            await asyncio.wait_for(task, 10)
        for _ in range(100):
            await wait_live_background_tasks()
            pending_task = context.runtime_task_registry.task("thread")
            if pending_task is not None:
                try:
                    await asyncio.wait_for(asyncio.shield(pending_task), 5)
                except BaseException:
                    pass
            if len(model.requests) >= 2:
                break
            await asyncio.sleep(0.05)

        async with db.session_factory() as session:
            events = await db.persistence.list_after(session, thread_id="thread", after_seq=0)

        accepted_turns = [event for event in events if event.method == "turn/accepted"]
        # 引导自己开了一个新回合，且原来那一回合没有因为引导多跑一步。
        assert len(accepted_turns) == 2, [event.turn_id for event in accepted_turns]
        assert accepted_turns[1].turn_id != first_turn
        assert str(accepted_turns[1].client_message_id or "") == "g-tail"
        assert len(model.requests) == 2

        consumed = [
            event for event in events
            if event.method == GUIDANCE_CONSUMED_METHOD
            and "g-tail" in (event.payload or {}).get("guidance_ids", [])
        ]
        assert consumed, "移交必须留下回执，否则下一回合会重复消费"
        assert consumed[0].turn_id == accepted_turns[1].turn_id

        # 旧回合里不出现引导项（界面项只在被回合消费时才产生）。
        guide_items = [
            event for event in events
            if event.method == "core/runItem"
            and "guidance" in str((event.payload or {}).get("kind") or "")
        ]
        assert not guide_items, guide_items

        # 不重复消费：回执落库后不再算「待投递」。
        assert await pending_steering(
            db.session_factory, "thread",
            event_store=db.event_store, write_coordinator=db.persistence.write_coordinator,
        ) == []
    finally:
        context.runtime_task_registry.clear()
        await wait_live_background_tasks()
        await db.close()


async def open_core_app_db_for(tmp_path):
    from lamtools_core.app import open_core_app_db

    return await open_core_app_db(tmp_path / "core.db")
