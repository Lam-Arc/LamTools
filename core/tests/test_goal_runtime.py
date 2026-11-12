from __future__ import annotations

import pytest

from lamtools_core.runtime.goal import GoalManager, InMemoryGoalStore


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
async def test_goal_manager_rejects_a_second_live_goal_in_the_same_thread() -> None:
    """user:“边界情况”+(同时有两个在跑的目标，续跑就不知道该推哪一个)。"""
    manager = GoalManager(InMemoryGoalStore())
    first = await manager.create(thread_id="thread-1", objective="先做完 A")

    with pytest.raises(ValueError, match=first.id):
        await manager.create(thread_id="thread-1", objective="再开一个 B")

    await manager.update(first.id, status="archived", status_reason="completed by agent request")
    second = await manager.create(thread_id="thread-1", objective="现在做 B")
    assert second.id != first.id
