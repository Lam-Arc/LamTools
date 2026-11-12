"""user:“任何一个人看见这个工具描述，能够在 5 秒内看懂并理解这是个什么、怎么操作”
+(目标工具要自解释：它是防偷懒闸门，模型自己决定完成、阻塞还是放弃。)

user:“如果这个 Agent 遇到什么极重大的问题必须停下来，那就标记成阻塞”+(工具必须能真的把目标标成 blocked)。
"""

from __future__ import annotations

import pytest

from lamtools_core.app.durable_operations import register_durable_operations
from lamtools_core.app.operation_catalog import OperationCatalog
from lamtools_core.runtime.arrange import ArrangeManager, InMemoryArrangeStore
from lamtools_core.runtime.goal import GoalManager, InMemoryGoalStore
from lamtools_core.tool import ToolCall
from lamtools_core.tool.durable_tools import durable_tool_handlers, durable_tool_specs


def _goal_tool(manager: GoalManager):
    catalog = OperationCatalog()
    register_durable_operations(
        catalog,
        goal_manager=manager,
        arrange_manager=ArrangeManager(InMemoryArrangeStore()),
    )

    async def execute(operation: str, payload: dict, metadata: dict):
        return await catalog.execute(operation, payload, metadata=metadata)

    handlers = durable_tool_handlers(execute)
    return handlers["goal"]


def _call(**arguments) -> ToolCall:
    return ToolCall(
        id="call-1",
        name="goal",
        arguments=arguments,
        metadata={"_runtime_session_id": "thread-1"},
    )


def test_goal_tool_description_explains_the_gate_and_every_action() -> None:
    spec = next(item for item in durable_tool_specs(goal=True, arrange=False) if item.name == "goal")
    description = str(spec.description or "")

    # 5 秒读懂：它是什么（闸门，不是任务列表）以及怎么收口。
    assert "不是任务" in description
    assert "什么时候调用" in description
    assert "下一回合" in description
    for action in ("create", "complete", "block", "cancel"):
        assert action in description
    assert "阻塞" in description
    # 不允许再出现“额外调模型校验”的暗示。
    assert "evaluator" not in description.lower()
    # 描述本身要短到能一眼扫完。
    assert len(description) <= 420


def test_goal_actions_are_complete_block_cancel() -> None:
    spec = next(item for item in durable_tool_specs(goal=True, arrange=False) if item.name == "goal")
    actions = spec.input_schema["properties"]["action"]["enum"]

    assert actions == ["create", "list", "get", "complete", "block", "cancel"]


@pytest.mark.asyncio
async def test_block_without_goal_id_stops_the_single_live_goal() -> None:
    manager = GoalManager(InMemoryGoalStore())
    goal = await manager.create(thread_id="thread-1", objective="把报告写完")
    goal_tool = _goal_tool(manager)

    result = await goal_tool(_call(action="block"))

    assert result.status == "ok"
    stored = await manager.get(goal.id)
    assert stored is not None and stored.status == "blocked"


@pytest.mark.asyncio
async def test_complete_without_goal_id_archives_the_current_goal() -> None:
    manager = GoalManager(InMemoryGoalStore())
    goal = await manager.create(thread_id="thread-1", objective="把报告写完")
    goal_tool = _goal_tool(manager)

    result = await goal_tool(_call(action="complete"))

    assert result.status == "ok"
    stored = await manager.get(goal.id)
    assert stored is not None and stored.status == "archived"
    assert stored.status_reason == "completed by agent request"


@pytest.mark.asyncio
async def test_finishing_a_goal_without_any_live_goal_says_so_plainly() -> None:
    manager = GoalManager(InMemoryGoalStore())
    goal_tool = _goal_tool(manager)

    result = await goal_tool(_call(action="complete"))

    assert result.status == "failed"
    assert "目标" in str(result.error or "")


@pytest.mark.asyncio
async def test_second_create_is_rejected_while_a_goal_is_live() -> None:
    manager = GoalManager(InMemoryGoalStore())
    first = await manager.create(thread_id="thread-1", objective="先做完 A")
    goal_tool = _goal_tool(manager)

    result = await goal_tool(_call(action="create", objective="再开一个 B"))

    assert result.status == "failed"
    assert first.id in str(result.error or "")
    live = await manager.list(thread_id="thread-1", status="active")
    assert [item.id for item in live] == [first.id]


@pytest.mark.asyncio
async def test_updating_another_sessions_goal_is_refused() -> None:
    """user:“边界情况”+(模型拿着别人的 goal_id 也不该能改到另一个会话的目标)。"""
    manager = GoalManager(InMemoryGoalStore())
    foreign = await manager.create(thread_id="thread-2", objective="别的会话的目标")
    goal_tool = _goal_tool(manager)

    result = await goal_tool(_call(action="complete", goal_id=foreign.id))

    assert result.status == "failed"
    assert "different thread" in str(result.error or "")
    stored = await manager.get(foreign.id)
    assert stored is not None and stored.status == "active"
