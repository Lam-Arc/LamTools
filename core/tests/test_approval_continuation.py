from __future__ import annotations

import pytest

from lamtools_core.app.approval_continuation import CoreApprovalContinuationCoordinator
from lamtools_core.runtime import RuntimeState
from lamtools_core.tool.approval_continuation import ApprovedToolExecution


class StateStore:
    def __init__(self, state: RuntimeState):
        self.state = state

    async def get(self, session_id: str):
        return self.state if self.state.session_id == session_id else None

    async def save(self, state: RuntimeState):
        self.state = state


def pending_state() -> RuntimeState:
    return RuntimeState(
        session_id="thread-1",
        run_id="turn-1",
        status="waiting",
        loop_state="wait",
        metadata={
            "original_user_message": "do it",
            "pending_approval": {
                "request_id": "call-1",
                "tool_call": {"id": "call-1", "name": "run_tests", "arguments": {"command": "echo ok"}},
            },
        },
    )


@pytest.mark.asyncio
async def test_core_approval_continuation_owns_tool_execution_and_resume():
    store = StateStore(pending_state())
    events = []
    prompts = []

    async def execute(tool_call):
        assert tool_call["id"] == "call-1"
        return ApprovedToolExecution("run_tests", tool_call["arguments"], "ok", "completed")

    coordinator = CoreApprovalContinuationCoordinator(
        state_store=store,
        emit_event=events.append,
        execute_tool=execute,
        continue_turn=lambda prompt, state: prompts.append((prompt, state.run_id)),
    )
    result = await coordinator.respond(
        thread_id="thread-1", request_id="call-1", decision="approve"
    )

    assert result["decision"] == "approve"
    assert "pending_approval" not in store.state.metadata
    assert [event.name for event in events] == ["runtime.approval_response", "runtime.tool.finished"]
    assert prompts and prompts[0][1] == "turn-1"


@pytest.mark.asyncio
async def test_core_approval_continuation_rejects_wrong_request_id():
    coordinator = CoreApprovalContinuationCoordinator(
        state_store=StateStore(pending_state()),
        emit_event=lambda _event: None,
        execute_tool=lambda _call: None,
        continue_turn=lambda _prompt, _state: None,
    )

    with pytest.raises(ValueError, match="does not match"):
        await coordinator.respond(thread_id="thread-1", request_id="wrong", decision="approve")


@pytest.mark.asyncio
async def test_core_approval_continuation_denial_is_terminal_without_member_resume():
    store = StateStore(pending_state())
    events = []
    coordinator = CoreApprovalContinuationCoordinator(
        state_store=store,
        emit_event=events.append,
        execute_tool=lambda _call: None,
        continue_turn=lambda _prompt, _state: None,
    )

    result = await coordinator.respond(
        thread_id="thread-1", request_id="call-1", decision="deny"
    )

    assert result["decision"] == "deny"
    assert store.state.status == "cancelled"
    assert [event.name for event in events] == ["runtime.approval_response", "runtime.cancelled"]


@pytest.mark.asyncio
async def test_core_approval_continuation_routes_delegated_session_back_to_child():
    state = pending_state()
    state.metadata["pending_approval"]["delegated_session"] = {
        "agent": "worker",
        "session_id": "thread-1:sub:001:worker",
    }
    parent_prompts = []
    delegated_prompts = []

    coordinator = CoreApprovalContinuationCoordinator(
        state_store=StateStore(state),
        emit_event=lambda _event: None,
        execute_tool=lambda tool_call: ApprovedToolExecution(
            tool_call["name"], tool_call["arguments"], "ok", "completed"
        ),
        continue_turn=lambda prompt, _state: parent_prompts.append(prompt),
        continue_delegated_turn=lambda prompt, _state, delegated: delegated_prompts.append(
            (prompt, delegated["session_id"])
        ),
    )

    await coordinator.respond(
        thread_id="thread-1", request_id="call-1", decision="approve"
    )

    assert parent_prompts == []
    assert delegated_prompts
    assert delegated_prompts[0][1] == "thread-1:sub:001:worker"
