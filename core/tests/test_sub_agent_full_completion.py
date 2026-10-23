"""user:“把最多 500 字符这个限制给去掉”+(主代理收到完整的子代理最终消息。)"""

from types import SimpleNamespace

import pytest

from lamtools_core.agent import SubAgentRunResult
from lamtools_core.sub_agent_supervisor import (
    SubAgentRecord,
    SubAgentSupervisor,
    member_wake_prompt,
    peek_member_events,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("resumed", [False, True], ids=["normal", "after-approval-or-question"])
async def test_complete_message_survives_storage_and_parent_notification(tmp_path, resumed):
    # Exceed both the event's former 500-character limit and the upstream
    # record's 1,000-character limit; the tail must reach the parent intact.
    message = "完整结果：\n" + "这一段包含不可省略的执行结果。\n" * 150 + "最终结论：保留到最后一个字。"
    result = SubAgentRunResult(
        session_id="parent:sub:worker", run_id="child-run", decision="done",
        message=message, ended_with_final_response=True,
    )

    async def run(**kwargs):
        return result

    database = tmp_path / "sub_agents.sqlite3"
    supervisor = SubAgentSupervisor(
        parent_thread_id="parent", database_path=database,
        runner=SimpleNamespace(run=run),
    )
    supervisor._save(SubAgentRecord(
        parent_thread_id="parent", name="worker", type="execute",
        model_id="fixture", reasoning_level="high", status="idle",
        sub_session_id="parent:sub:worker",
    ))
    try:
        if resumed:
            record = await supervisor.finalize_resumed("worker", result)
            # The periodic reconciliation publishes this completion through
            # the same durable outbox writer after an approval/question resume.
            supervisor._write_member_event(record, "member_finished")
        else:
            supervisor._pending_prompts["worker"] = "complete the task"
            await supervisor._drive("worker")

        assert supervisor._required("worker").summary == message
        events = peek_member_events(database, "parent")
        assert len(events) == 1
        assert events[0]["payload"]["summary"] == message
        assert member_wake_prompt(events) == f"子代理 worker 已完成：{message}"

        reopened = SubAgentSupervisor(
            parent_thread_id="parent", database_path=database, runner=SimpleNamespace(),
        )
        try:
            assert reopened._required("worker").summary == message
            assert member_wake_prompt(peek_member_events(database, "parent")) == f"子代理 worker 已完成：{message}"
        finally:
            await reopened.shutdown()
    finally:
        await supervisor.shutdown()
