from __future__ import annotations

import pytest

from lamtools_core.llm import LLMResponse
from lamtools_core.runtime import CompletionResult, RuntimeState
from lamtools_core.runtime.goal import (
    GoalCompletionGate,
    GoalManager,
    InMemoryGoalStore,
    ModelGoalEvaluator,
)


@pytest.mark.asyncio
async def test_goal_manager_persists_and_updates_lifecycle() -> None:
    manager = GoalManager(InMemoryGoalStore())

    goal = await manager.create(
        thread_id="thread-1",
        objective="Produce a verified report",
        completion_criteria=["report exists", "sources are cited"],
    )
    blocked = await manager.update(goal.id, status="blocked", status_reason="approval required")
    resumed = await manager.update(blocked.id, status="active")
    completed = await manager.update(resumed.id, status="archived", status_reason="verified")

    assert completed.revision == 4
    assert completed.status == "archived"
    assert completed.completed_at is not None
    assert [item.id for item in await manager.list(thread_id="thread-1")] == [goal.id]


@pytest.mark.asyncio
async def test_goal_manager_rejects_updates_after_terminal_state() -> None:
    manager = GoalManager(InMemoryGoalStore())
    goal = await manager.create(thread_id="thread-1", objective="Ship it")
    await manager.update(goal.id, status="archived")

    with pytest.raises(ValueError, match="terminal"):
        await manager.update(goal.id, objective="Change it")

    unchanged = await manager.update(goal.id, status="archived")
    assert unchanged.revision == 2


@pytest.mark.asyncio
async def test_goal_manager_requires_non_empty_objective() -> None:
    manager = GoalManager(InMemoryGoalStore())

    with pytest.raises(ValueError, match="objective"):
        await manager.create(thread_id="thread-1", objective="   ")


@pytest.mark.asyncio
async def test_goal_completion_gate_updates_goal_and_caps_repair_loop() -> None:
    manager = GoalManager(InMemoryGoalStore())
    goal = await manager.create(thread_id="thread-1", objective="Verify it")

    async def incomplete(_goal, _context):
        return CompletionResult(
            passed=False,
            summary="source missing",
            repair_instruction="Find the primary source",
        )

    gate = GoalCompletionGate(manager, goal.id, incomplete, max_repair_attempts=2)
    state = RuntimeState(session_id="thread-1")
    first = await gate.verify(state, {})
    second = await gate.verify(state, {})

    assert first.blocked is False
    assert second.blocked is True
    stored = await manager.get(goal.id)
    assert stored is not None
    assert stored.status == "blocked"
    assert stored.metadata["completion_attempts"] == 2


@pytest.mark.asyncio
async def test_goal_completion_gate_pauses_after_ten_default_repair_attempts() -> None:
    manager = GoalManager(InMemoryGoalStore())
    goal = await manager.create(thread_id="thread-1", objective="Finish the task")

    async def incomplete(_goal, _context):
        return CompletionResult(
            passed=False,
            summary="work remains",
            repair_instruction="Continue the remaining work",
        )

    gate = GoalCompletionGate(manager, goal.id, incomplete)
    state = RuntimeState(session_id="thread-1")
    results = [await gate.verify(state, {}) for _ in range(10)]

    assert all(result.blocked is False for result in results[:9])
    assert results[9].blocked is True
    stored = await manager.get(goal.id)
    assert stored is not None
    assert stored.status == "blocked"
    assert stored.metadata["completion_attempts"] == 10


@pytest.mark.asyncio
async def test_model_goal_evaluator_uses_strict_structured_completion_check() -> None:
    class Client:
        def __init__(self) -> None:
            self.requests = []

        async def complete(self, request):
            self.requests.append(request)
            return LLMResponse(content='{"status":"continue","summary":"citation missing","repair_instruction":"add citation"}')

    manager = GoalManager(InMemoryGoalStore())
    goal = await manager.create(thread_id="thread-1", objective="Verified answer")
    client = Client()

    result = await ModelGoalEvaluator(client, model_id="judge-model")(goal, {})

    assert result.passed is False
    assert result.repair_instruction == "add citation"
    assert client.requests[0].model == "judge-model"
    assert client.requests[0].response_format == {"type": "json_object"}


@pytest.mark.asyncio
async def test_model_goal_evaluator_treats_invalid_protocol_output_as_retryable() -> None:
    class Client:
        async def complete(self, _request):
            return LLMResponse(content="I cannot return JSON")

    manager = GoalManager(InMemoryGoalStore())
    goal = await manager.create(thread_id="thread-1", objective="Verified answer")

    result = await ModelGoalEvaluator(Client(), model_id="judge-model")(goal, {})

    assert result.passed is False
    assert result.blocked is False
    assert "invalid JSON" in result.summary
    assert result.repair_instruction


@pytest.mark.asyncio
async def test_goal_completion_gate_rejects_cross_thread_binding() -> None:
    manager = GoalManager(InMemoryGoalStore())
    goal = await manager.create(thread_id="thread-1", objective="Keep scope isolated")

    async def evaluator(_goal, _context):
        raise AssertionError("cross-thread goal must not be evaluated")

    result = await GoalCompletionGate(manager, goal.id, evaluator).verify(
        RuntimeState(session_id="thread-2"),
        {},
    )

    assert result.blocked is True
    assert "different thread" in result.summary


@pytest.mark.asyncio
async def test_goal_completion_gate_uses_goal_activated_during_current_run() -> None:
    manager = GoalManager(InMemoryGoalStore())
    goal = await manager.create(thread_id="thread-1", objective="Finish this run")
    seen: list[str] = []

    async def evaluator(active_goal, _context):
        seen.append(active_goal.id)
        return CompletionResult(passed=True, summary="done")

    gate = GoalCompletionGate(manager, evaluator=evaluator)
    state = RuntimeState(session_id="thread-1", metadata={"goal_id": goal.id})

    result = await gate.verify(state, {})

    assert result.passed is True
    assert seen == [goal.id]
    assert (await manager.get(goal.id)).status == "archived"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_goal_completion_gate_skips_model_when_run_has_no_goal() -> None:
    manager = GoalManager(InMemoryGoalStore())

    async def evaluator(_goal, _context):
        raise AssertionError("ordinary runs must not invoke the Goal evaluator")

    result = await GoalCompletionGate(manager, evaluator=evaluator).verify(
        RuntimeState(session_id="thread-1"),
        {},
    )

    assert result.passed is True
