"""Tests for lamtools_core.runtime module."""

import asyncio

import pytest

from lamtools_core.runtime import (
    CompletionCheck,
    CompletionGate,
    CompletionResult,
    InMemoryRuntimeStateStore,
    RuntimeTaskRegistry,
    RuntimeDriver,
    RuntimeLoopState,
    RuntimeState,
    RuntimeStateStore,
    RuntimeStatus,
    RuntimeToolStep,
    RuntimeTurnInput,
    RuntimeTurnResult,
)
from lamtools_core.llm import LLMResponse, LLMToolCall
from lamtools_core.tool import ToolCall, ToolResult
from lamtools_core.event import CoreEvent


class TestRuntimeTypes:
    def test_runtime_state_construction(self):
        state = RuntimeState(session_id="s1", status="running", turn_count=3)
        assert state.session_id == "s1"
        assert state.status == "running"
        assert state.turn_count == 3
        assert state.loop_state == "continue"

    def test_runtime_state_to_dict(self):
        state = RuntimeState(session_id="s1", position="phase_a")
        d = state.to_dict()
        assert d["session_id"] == "s1"
        assert d["position"] == "phase_a"
        assert d["loop_state"] == "continue"

    def test_runtime_tool_step(self):
        call = ToolCall(id="c1", name="search", arguments={"q": "test"})
        step = RuntimeToolStep(call=call)
        d = step.to_dict()
        assert d["call"]["name"] == "search"

    def test_runtime_tool_step_with_result(self):
        call = ToolCall(id="c1", name="read", arguments={})
        result = ToolResult(call_id="c1", name="read", content="data")
        step = RuntimeToolStep(call=call, result=result)
        d = step.to_dict()
        assert d["result"]["content"] == "data"

    def test_runtime_turn_input(self):
        inp = RuntimeTurnInput(user_message="hello")
        d = inp.to_dict()
        assert d["user_message"] == "hello"

    def test_runtime_turn_result_continue(self):
        r = RuntimeTurnResult(message="working", loop_state="continue")
        assert r.loop_state == "continue"
        assert not r.complete

    def test_runtime_turn_result_done(self):
        r = RuntimeTurnResult(message="done", loop_state="done", complete=True)
        d = r.to_dict()
        assert d["loop_state"] == "done"
        assert d["complete"] is True

    def test_runtime_turn_result_with_model_response(self):
        resp = LLMResponse(content="I will search", tool_calls=[
            LLMToolCall(id="tc1", name="search", arguments={"q": "x"}),
        ])
        r = RuntimeTurnResult(model_response=resp)
        d = r.to_dict()
        assert d["model_response"]["content"] == "I will search"
        assert len(d["model_response"]["tool_calls"]) == 1

    def test_runtime_turn_result_with_events(self):
        evt = CoreEvent(name="progress", category="progress")
        r = RuntimeTurnResult(events=[evt])
        assert len(r.events) == 1

    def test_completion_check(self):
        c = CompletionCheck(name="response_ready", passed=True, output="all checks complete")
        d = c.to_dict()
        assert d["passed"] is True
        assert d["name"] == "response_ready"

    def test_completion_result(self):
        c1 = CompletionCheck(name="primary_check", passed=True)
        c2 = CompletionCheck(name="secondary_check", passed=False, output="3 errors")
        cr = CompletionResult(passed=False, summary="2 checks, 1 failed", checks=[c1, c2])
        d = cr.to_dict()
        assert d["passed"] is False
        assert len(d["checks"]) == 2
        assert d["checks"][1]["output"] == "3 errors"

    def test_all_loop_states(self):
        states: list[RuntimeLoopState] = ["continue", "wait", "done", "failed"]
        for s in states:
            st = RuntimeState(session_id="x", loop_state=s)
            assert st.loop_state == s

    def test_all_runtime_statuses(self):
        statuses: list[RuntimeStatus] = [
            "idle", "running", "waiting", "completed", "failed", "cancelled",
        ]
        for s in statuses:
            st = RuntimeState(session_id="x", status=s)
            assert st.status == s

    def test_protocols_are_runtime_checkable(self):
        assert isinstance("not_a_store", RuntimeStateStore) is False
        assert isinstance("not_a_gate", CompletionGate) is False
        assert isinstance("not_a_driver", RuntimeDriver) is False


class TestInMemoryRuntimeStateStore:
    @pytest.mark.asyncio
    async def test_save_get_and_clear(self):
        store = InMemoryRuntimeStateStore()
        state = RuntimeState(session_id="s1", status="running")

        assert await store.get("s1") is None
        await store.save(state)
        assert await store.get("s1") is state

        store.clear()
        assert await store.get("s1") is None


class TestRuntimeTaskRegistry:
    @pytest.mark.asyncio
    async def test_register_running_and_cleanup(self):
        registry = RuntimeTaskRegistry()

        async def short_task():
            await asyncio.sleep(0)

        task = asyncio.create_task(short_task())
        registry.register("thread-1", task, run_id="turn-1")

        assert registry.is_running("thread-1") is True
        assert registry.is_running("thread-1", run_id="turn-1") is True
        assert registry.is_running("thread-1", run_id="turn-2") is False
        assert registry.task("thread-1", run_id="turn-1") is task
        await task
        await asyncio.sleep(0)
        assert registry.is_running("thread-1") is False

    @pytest.mark.asyncio
    async def test_cancel_sets_cooperative_signal_without_force_cancelling_task(self):
        registry = RuntimeTaskRegistry()

        async def long_task():
            await asyncio.sleep(60)

        task = asyncio.create_task(long_task())
        registry.register("thread-1", task, run_id="turn-1")
        cancel_event = registry.get_cancel_event("thread-1")

        registry.cancel("thread-1", run_id="turn-1")

        assert cancel_event.is_set() is True
        assert task.done() is False
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    @pytest.mark.asyncio
    async def test_force_cancel_cancels_registered_task(self):
        registry = RuntimeTaskRegistry()

        async def long_task():
            await asyncio.sleep(60)

        task = asyncio.create_task(long_task())
        registry.register("thread-1", task, run_id="turn-1")

        registry.cancel("thread-1", run_id="turn-1", force=True)

        with pytest.raises(asyncio.CancelledError):
            await task

    @pytest.mark.asyncio
    async def test_cancel_ignores_mismatched_run_id(self):
        registry = RuntimeTaskRegistry()

        async def long_task():
            await asyncio.sleep(60)

        task = asyncio.create_task(long_task())
        registry.register("thread-1", task, run_id="turn-1")
        cancel_event = registry.get_cancel_event("thread-1")

        registry.cancel("thread-1", run_id="turn-2", force=True)

        assert cancel_event.is_set() is False
        assert task.done() is False
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    def test_reset_cancel_event_clears_stale_signal(self):
        registry = RuntimeTaskRegistry()
        event = registry.get_cancel_event("thread-1")
        registry.cancel("thread-1")
        assert event.is_set() is True

        reset = registry.reset_cancel_event("thread-1")

        assert reset is event
        assert reset.is_set() is False

    def test_accept_run_clears_stale_cancel_signal(self):
        registry = RuntimeTaskRegistry()
        event = registry.get_cancel_event("thread-1")
        registry.cancel("thread-1")

        assert registry.accept_run("thread-1", "turn-2") is True
        assert event.is_set() is False

    @pytest.mark.asyncio
    async def test_shutdown_cancels_and_joins_tracked_tasks(self):
        registry = RuntimeTaskRegistry()
        cancelled = asyncio.Event()

        async def run_until_cancelled():
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        task = asyncio.create_task(run_until_cancelled())
        assert registry.register("thread-1", task, run_id="turn-1") is True
        await asyncio.sleep(0)

        await registry.shutdown()

        assert task.done()
        assert cancelled.is_set()
        assert registry.task("thread-1") is None
