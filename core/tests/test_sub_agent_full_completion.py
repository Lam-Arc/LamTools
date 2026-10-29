"""user:“把最多 500 字符这个限制给去掉”+(主代理收到完整的子代理最终消息。)"""

from types import SimpleNamespace

import pytest

from lamtools_core.agent import SubAgentRunResult
from lamtools_core.sub_agent_supervisor import (
    SubAgentRecord,
    SubAgentSupervisor,
    mark_member_events_delivered,
    member_wake_prompt,
    peek_member_events,
)


def _completed_result(message: str) -> SubAgentRunResult:
    return SubAgentRunResult(
        session_id="parent:sub:worker", run_id="child-run", decision="done",
        message=message, ended_with_final_response=True,
    )


def _seed_idle_member(supervisor: SubAgentSupervisor) -> None:
    supervisor._save(SubAgentRecord(
        parent_thread_id="parent", name="worker", type="execute",
        model_id="fixture", reasoning_level="high", status="idle",
        sub_session_id="parent:sub:worker",
    ))


@pytest.mark.asyncio
async def test_finished_member_message_is_injected_into_a_live_parent_run(tmp_path):
    # user:“子代理异常，主诉：子代理完成后不会回传最终回复”
    # +(父回合还在跑时，成员一完成就把完整最终消息作为指导注入该回合，
    # 而不是只落一条持久事件等下一个回合。)
    message = "完整结果：\n" + "这一段包含不可省略的执行结果。\n" * 150 + "最终结论：保留到最后一个字。"
    captured: dict[str, object] = {}

    async def run(**kwargs):  # noqa: ANN003 - test double
        return _completed_result(message)

    def parent_guidance_sink(*args, **kwargs):  # noqa: ANN002, ANN003 - test double
        captured["args"] = args
        captured["kwargs"] = kwargs
        return True

    database = tmp_path / "sub_agents.sqlite3"
    supervisor = SubAgentSupervisor(
        parent_thread_id="parent", database_path=database,
        runner=SimpleNamespace(run=run, parent_guidance_sink=parent_guidance_sink),
    )
    _seed_idle_member(supervisor)
    supervisor._pending_prompts["worker"] = "complete the task"
    try:
        await supervisor._drive("worker")
    finally:
        await supervisor.shutdown()

    assert captured, "the finished member's message never reached the live parent run"
    args = captured["args"]
    assert args[0] == "parent"
    assert args[2] == f"子代理 worker 已完成：{message}"
    guidance_id = str(args[3])
    metadata = args[4]
    assert metadata["source"] == "sub_agent"
    assert metadata["name"] == "worker"
    assert metadata["status"] == "idle"

    # The guidance id is the durable event row id: the kernel's checkpoint
    # acknowledgement is what marks the event delivered, and until then the
    # event stays queued (a live run that never consumed it must not lose it).
    pending = peek_member_events(database, "parent")
    assert [item["id"] for item in pending] == [guidance_id]
    assert pending[0]["payload"]["summary"] == message

    mark_member_events_delivered(database, [guidance_id])
    assert peek_member_events(database, "parent") == []


@pytest.mark.asyncio
@pytest.mark.parametrize("sink", ["rejected", "missing"], ids=["no-live-run", "no-sink"])
async def test_finished_member_message_stays_queued_without_a_live_parent_run(tmp_path, sink):
    message = "最终结论：后台完成。"
    delivered: list[tuple] = []

    async def run(**kwargs):  # noqa: ANN003 - test double
        return _completed_result(message)

    runner = SimpleNamespace(run=run)
    if sink == "rejected":
        def parent_guidance_sink(*args):  # noqa: ANN002 - test double
            delivered.append(args)
            return False

        runner.parent_guidance_sink = parent_guidance_sink

    database = tmp_path / "sub_agents.sqlite3"
    supervisor = SubAgentSupervisor(
        parent_thread_id="parent", database_path=database, runner=runner,
    )
    _seed_idle_member(supervisor)
    supervisor._pending_prompts["worker"] = "complete the task"
    try:
        await supervisor._drive("worker")
    finally:
        await supervisor.shutdown()

    if sink == "rejected":
        assert delivered, "the supervisor must still try the live parent run"
    pending = peek_member_events(database, "parent")
    assert len(pending) == 1
    assert pending[0]["payload"]["event"] == "member_finished"
    assert pending[0]["payload"]["summary"] == message


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
