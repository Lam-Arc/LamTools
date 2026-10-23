from dataclasses import fields

import pytest

from lamtools_core.kernel import LoopPolicy
from lamtools_core.tool import ToolCall
from core.tests.test_kernel import MockKitStep, MockRuntimeKit, _make_kernel, _make_turn_input


# user:“直接把这个功能删掉，一点都不要留”+(连续工具调用不得触发汇报要求或保留配置)。
@pytest.mark.asyncio
@pytest.mark.parametrize("narrated_round", [None, 14])
async def test_long_tool_run_leaves_narration_to_the_model(narrated_round):
    kit = MockRuntimeKit([
        MockKitStep(
            reply="I found another file" if index == narrated_round else "",
            tool_calls=[ToolCall(id=f"read-{index}", name="read_file", arguments={"path": f"{index}.txt"})],
        )
        for index in range(30)
    ] + [MockKitStep(reply="Complete", decision="done")])

    result = await _make_kernel(kit).run(_make_turn_input())

    assert result.decision == "done"
    assert len(result.steps) == 31
    # Only the original request may be a user message; no artificial demand.
    for history in kit.context_histories:
        assert all(message.content == "hello" for message in history if message.role == "user")
    assert sum(len(step.tool_steps) for step in result.steps) == 30


def test_loop_policy_has_no_narration_threshold():
    assert "max_tool_only_rounds_without_progress" not in {field.name for field in fields(LoopPolicy)}
