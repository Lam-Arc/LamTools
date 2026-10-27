"""Resume supplements use the same durable, visible guidance path as live steering."""
import asyncio
import pytest
from tests.test_same_turn_resume import context_for
from lamtools_core.app import open_core_app_db, CoreAgentPaths, CoreAgentSpec, create_core_agent_operations
from lamtools_core.app.live_hub import CoreAppEventHub
from lamtools_core.attachment import AttachmentRecord
from lamtools_core.runtime import RuntimeTaskRegistry
from lamtools_core.app import live_operations as live
from lamtools_core.app.event_store import AppEventInput
from lamtools_core.kernel import CoreLoopKernel
from lamtools_core.llm import LLMStreamEvent, LLMToolCall
from lamtools_core.tool import ToolResult


class GuidanceModel:
    def __init__(self, early):
        self.requests = []
        self.blocked = asyncio.Event()
        self.early = early

    async def complete(self, request):
        raise AssertionError("scripted stream only; no external model calls")

    async def stream(self, request):
        self.requests.append(request)
        index = len(self.requests)
        if not self.early and index == 1:
            self.blocked.set()
            await asyncio.Event().wait()
        offset = 0 if self.early else 1
        if index - offset < 3:
            yield LLMStreamEvent(kind="done", tool_calls=[
                LLMToolCall(id=f"step-{index}", name="list_dir", arguments={"path": "."})])
        else:
            yield LLMStreamEvent(kind="content_delta", content="finished")
            yield LLMStreamEvent(kind="done")


# user:“把它作为一个引导信息发进去”+(恢复补充只入历史一次、显示一次，后续请求保留原位置)。
@pytest.mark.asyncio
@pytest.mark.parametrize("early", [False, True])
@pytest.mark.parametrize("restart_before_consumption", [False, True])
async def test_resume_supplement_is_visible_once_and_stays_before_tool_results(
    tmp_path, monkeypatch, early, restart_before_consumption,
):
    monkeypatch.setenv("LAMTOOLS_HOME", str(tmp_path / "home"))
    models = tmp_path / ".lam" / "config" / "models"
    models.mkdir(parents=True)
    (models / "fixture.jsonc").write_text('{"model_id":"fixture","capability":"text"}', encoding="utf-8")
    model = GuidanceModel(early)
    async def tool(self, state, call, **kwargs):
        return ToolResult(call_id=call.id, name=call.name, status="ok", content="AFTER_GUIDANCE_TOOL")
    monkeypatch.setattr(CoreLoopKernel, "_execute_tool", tool)
    db = await open_core_app_db(tmp_path / "core.db")
    context = await context_for(db, tmp_path, model)
    try:
        accepted = await live.handle_turn_start_operation(request_id=1, params={
            "thread_id": "thread", "input": [{"type": "text", "text": "ORIGINAL_TASK"}],
            "model_id": "fixture",
            "permission_preset": "full_access", "include_snapshot": False,
        }, context=context)
        turn = accepted.runtime_start["turn_id"]
        if not early:
            await asyncio.wait_for(model.blocked.wait(), 10)
        old_task = context.runtime_task_registry.task("thread")
        await live.handle_turn_pause_operation(request_id=2, params={"thread_id":"thread", "turn_id":turn}, context=context)
        if old_task:
            await asyncio.gather(old_task, return_exceptions=True)
        await live.wait_live_background_tasks()
        params = {"thread_id":"thread", "turn_id":turn, "client_message_id":"resume-once",
                  "input":[{"type":"text", "text":"UNIQUE_SUPPLEMENT"}]}
        if restart_before_consumption:
            # Durable guidance survived a process exit without a history ACK.
            # Keep the turn paused; reopening must consume it without new input.
            async def seed(session):
                await db.persistence.append(session, AppEventInput(
                    thread_id="thread", turn_id=turn, method="turn/steered",
                    client_message_id="resume-guide:resume-once",
                    payload={"type":"turn", "guidance_id":"resume-guide:resume-once",
                             "input":params["input"], "runtime_input":params["input"]},
                ))
            await db.persistence.write(seed)
            await context.runtime_task_registry.shutdown()
            await live.wait_live_background_tasks()
            await db.close()
            db = await open_core_app_db(tmp_path / "core.db")
            context = await context_for(db, tmp_path, model)
            resume_params = {"thread_id":"thread", "turn_id":turn, "client_message_id":"after-restart"}
        else:
            resume_params = params
        resumed = await live.handle_turn_resume_operation(request_id=31, params=resume_params, context=context)
        assert "error" not in resumed.response, resumed.response
        task = context.runtime_task_registry.task("thread")
        if task:
            await asyncio.wait_for(task, 15)
        calls = model.requests if early else model.requests[1:]
        assert len(calls) == 3
        for request in calls:
            supplements = [m for m in request.messages if "UNIQUE_SUPPLEMENT" in str(m.content)]
            assert len(supplements) == 1
            assert supplements[0].role == "user", "resume input must use normal guidance, not a pinned system instruction"
            assert "ORIGINAL_TASK" in str(request.messages)
        final_messages = calls[-1].messages
        guide_index = next(i for i,m in enumerate(final_messages) if "UNIQUE_SUPPLEMENT" in str(m.content))
        tool_index = next(i for i,m in enumerate(final_messages) if m.role == "tool")
        assert guide_index < tool_index, "guidance must remain at its original history position"
        receipt = await live.handle_turn_resume_operation(request_id=4, params=resume_params, context=context)
        assert "error" not in receipt.response
        assert receipt.runtime_start is None
        history = await db.runtime_state_store.get_history("thread")
        assert len([m for m in history if "UNIQUE_SUPPLEMENT" in str(m.get("content"))]) == 1
        async with db.session_factory() as session:
            events = await db.persistence.list_after(session, thread_id="thread", after_seq=0)
        steering = [e for e in events if e.method == "turn/steered"]
        assert len(steering) == 1
        visible = [e for e in events if e.method == "core/runItem"
                   and e.payload.get("kind") == "message"
                   and ":user:guide:" in str(e.item_id)
                   and "UNIQUE_SUPPLEMENT" in str(e.payload)]
        assert len(visible) == 1, "resume supplement must appear as one guidance message"
        assert len([e for e in events if e.method == "turn/accepted"]) == 1
    finally:
        await context.runtime_task_registry.shutdown()
        await live.wait_live_background_tasks()
        await db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("with_text", [False, True])
async def test_resume_attachment_is_part_of_one_visible_guidance(tmp_path, monkeypatch, with_text):
    monkeypatch.setenv("LAMTOOLS_HOME", str(tmp_path / "home"))
    attachment = tmp_path / "note.txt"
    attachment.write_text("ATTACHMENT_EVIDENCE", encoding="utf-8")
    record = AttachmentRecord(
        id="att-resume", session_id="thread", filename="note.txt", mime_type="text/plain",
        size=attachment.stat().st_size, storage_path=str(attachment), preview_type="text",
    )
    class Attachments:
        async def get(self, attachment_id):
            assert attachment_id == record.id
            return record
    model = GuidanceModel(early=True)
    async def tool(self, state, call, **kwargs):
        return ToolResult(call_id=call.id, name=call.name, status="ok", content="AFTER_GUIDANCE_TOOL")
    monkeypatch.setattr(CoreLoopKernel, "_execute_tool", tool)
    db = await open_core_app_db(tmp_path / "core.db")
    registry, hub = RuntimeTaskRegistry(), CoreAppEventHub()
    operations = create_core_agent_operations(
        spec=CoreAgentSpec(default_model="fixture"),
        paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=tmp_path), model_provider=model,
        attachment_service=Attachments(), runtime_state_store=db.runtime_state_store,
        runtime_task_registry=registry, db_session_factory=db.session_factory,
        app_event_store=db.event_store, thread_snapshot_store=db.snapshot_store,
        app_event_hub=hub, write_coordinator=db.persistence.write_coordinator,
    )
    context = live.CoreLiveContext(
        session_factory=db.session_factory, persistence=db.persistence,
        operations=operations, hub=hub, runtime_task_registry=registry,
        runtime_state_store=db.runtime_state_store,
    )
    try:
        accepted = await live.handle_turn_start_operation(request_id=1, params={
            "thread_id":"thread", "input":[{"type":"text", "text":"ORIGINAL_TASK"}],
            "include_snapshot":False,
        }, context=context)
        turn = accepted.runtime_start["turn_id"]
        await live.handle_turn_pause_operation(request_id=2, params={"thread_id":"thread", "turn_id":turn}, context=context)
        await live.wait_live_background_tasks()
        input_items = ([{"type":"text", "text":"SEE_ATTACHMENT"}] if with_text else [])
        input_items.append({"type":"attachment", "attachment_id":record.id})
        resumed = await live.handle_turn_resume_operation(request_id=3, params={
            "thread_id":"thread", "turn_id":turn, "input":input_items,
        }, context=context)
        assert "error" not in resumed.response
        task = registry.task("thread")
        if task:
            await asyncio.wait_for(task, 15)
        assert len(model.requests) == 3
        for request in model.requests:
            attachment_messages = [m for m in request.messages if "ATTACHMENT_EVIDENCE" in str(m.content)]
            assert len(attachment_messages) == 1
            assert attachment_messages[0].role == "user"
            if with_text:
                assert "SEE_ATTACHMENT" in str(attachment_messages[0].content)
        async with db.session_factory() as session:
            events = await db.persistence.list_after(session, thread_id="thread", after_seq=0)
        visible = [e for e in events if ":user:guide:" in str(e.item_id) and e.payload.get("kind") == "message"]
        assert len(visible) == 1
        assert "user_content" not in str(visible[0].payload), "model attachment blocks must not be copied into UI metadata"
    finally:
        await registry.shutdown()
        await live.wait_live_background_tasks()
        await db.close()


