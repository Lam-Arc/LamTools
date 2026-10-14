"""Same-turn Resume contracts using committed SQLite history and scripted models."""
import asyncio

import pytest

from lamtools_core.app import CoreAgentPaths, CoreAgentSpec, create_core_agent_operations, open_core_app_db
from lamtools_core.app.live_hub import CoreAppEventHub
from lamtools_core.app.live_operations import (
    CoreLiveContext, handle_turn_start_operation, handle_turn_pause_operation,
    handle_turn_resume_operation, handle_turn_steer_operation, recover_stale_active_turns, wait_live_background_tasks,
)
from lamtools_core.kernel import CoreLoopKernel
from lamtools_core.llm import LLMStreamEvent, LLMToolCall
from lamtools_core.runtime import RuntimeTaskRegistry, RuntimeState
from lamtools_core.app.event_store import AppEventInput
from lamtools_core.tool import ToolResult


async def context_for(db, tmp_path, model):
    registry = RuntimeTaskRegistry()
    hub = CoreAppEventHub()
    operations = create_core_agent_operations(
        spec=CoreAgentSpec(default_model="fixture"),
        paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=tmp_path), model_provider=model,
        runtime_state_store=db.runtime_state_store, runtime_task_registry=registry,
        db_session_factory=db.session_factory, app_event_store=db.event_store,
        thread_snapshot_store=db.snapshot_store, app_event_hub=hub,
        write_coordinator=db.persistence.write_coordinator,
    )
    return CoreLiveContext(session_factory=db.session_factory, persistence=db.persistence,
        operations=operations, hub=hub, runtime_task_registry=registry, runtime_state_store=db.runtime_state_store)


class ScriptedModel:
    def __init__(self, mode):
        self.mode = mode
        self.requests = []
        self.blocked = asyncio.Event()
    async def complete(self, request):
        raise AssertionError("no paid calls")
    async def stream(self, request):
        self.requests.append(request)
        if len(self.requests) == 1:
            if self.mode == "tools":
                yield LLMStreamEvent(kind="content_delta", content="Completed plan")
                yield LLMStreamEvent(kind="done", tool_calls=[
                    LLMToolCall(id="committed", name="run_command", arguments={"command": "echo one"}),
                    LLMToolCall(id="uncertain", name="run_command", arguments={"command": "echo two"}),
                ])
                return
            yield LLMStreamEvent(kind="content_delta", content="INCOMPLETE_FRAGMENT")
            self.blocked.set()
            await asyncio.Event().wait()
        yield LLMStreamEvent(kind="content_delta", content="Finished after resume")
        yield LLMStreamEvent(kind="done")


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["stream", "tools"])
@pytest.mark.parametrize("restart", [False, True])
async def test_stop_resume_keeps_turn_history_and_does_not_replay_tools(tmp_path, monkeypatch, mode, restart):
    models = tmp_path / ".lam" / "config" / "models"
    models.mkdir(parents=True)
    (models / "fixture.jsonc").write_text('{"model_id":"fixture","capability":"text"}', encoding="utf-8")
    model = ScriptedModel(mode)
    executed = []
    async def tool(self, state, call, **kwargs):
        executed.append(call.id)
        if call.id == "uncertain":
            model.blocked.set()
            await asyncio.Event().wait()
        return ToolResult(call_id=call.id, name=call.name, status="ok", content="COMMITTED_RESULT")
    monkeypatch.setattr(CoreLoopKernel, "_execute_tool", tool)
    db = await open_core_app_db(tmp_path / "core.db")
    context = await context_for(db, tmp_path, model)
    try:
        accepted = await handle_turn_start_operation(request_id=1, params={
            "thread_id": "thread", "input": [{"type": "text", "text": "original task"}],
            "model_id": "fixture", "permission_preset": "full_access", "include_snapshot": False,
        }, context=context)
        turn_id = accepted.runtime_start["turn_id"]
        await asyncio.wait_for(model.blocked.wait(), 10)
        task = context.runtime_task_registry.task("thread")
        await handle_turn_pause_operation(request_id=2, params={"thread_id": "thread", "turn_id": turn_id}, context=context)
        await asyncio.gather(task, return_exceptions=True)
        await wait_live_background_tasks()
        async with db.session_factory() as session:
            stopped = await db.persistence.load(session, "thread")
        assert stopped["turns"][turn_id]["status"] == "paused"
        history = await db.runtime_state_store.get_history("thread")
        assert "INCOMPLETE_FRAGMENT" not in str(history)
        assert len([m for m in history if m["role"] == "user"]) == 1
        if mode == "tools":
            assert "COMMITTED_RESULT" in str(history)
            assert "Completed plan" in str(history)
            assert executed == ["committed", "uncertain"]
        if restart:
            await db.close()
            db = await open_core_app_db(tmp_path / "core.db")
            context = await context_for(db, tmp_path, model)
            assert await recover_stale_active_turns(context=context) == 0
            assert len(model.requests) == 1  # restart never resumes a user stop
            assert not context.runtime_task_registry.is_running("thread")
        resumed = await handle_turn_resume_operation(request_id=3, params={"thread_id": "thread", "turn_id": turn_id, "client_message_id": "resume-once"}, context=context)
        assert "error" not in resumed.response, resumed.response
        assert resumed.runtime_start["turn_id"] == turn_id
        assert resumed.runtime_start["run_id"] != turn_id
        task = context.runtime_task_registry.task("thread")
        await asyncio.wait_for(task, 10)
        requests_before_retry = len(model.requests)
        receipt = await handle_turn_resume_operation(request_id=33, params={"thread_id": "thread", "turn_id": turn_id, "client_message_id": "resume-once"}, context=context)
        assert "error" not in receipt.response, receipt.response
        assert receipt.runtime_start is None
        assert len(model.requests) == requests_before_retry
        async with db.session_factory() as session:
            final = await db.persistence.load(session, "thread")
            events = await db.persistence.list_after(session, thread_id="thread", after_seq=0)
        assert list(final["turns"]) == [turn_id]
        assert final["turns"][turn_id]["status"] == "completed"
        assert len([event for event in events if event.method == "turn/accepted"]) == 1
        assert len([event for event in events if event.method == "item/started" and event.payload.get("type") == "userMessage"]) == 1
        history = await db.runtime_state_store.get_history("thread")
        assert len([m for m in history if m["role"] == "user"]) == 1
        assert "Continue the interrupted task" not in str(history), "resume must not narrate itself"
        assert "INCOMPLETE_FRAGMENT" not in str(model.requests[-1].messages)
        if mode == "tools":
            assert executed == ["committed", "uncertain"]
            assert "COMMITTED_RESULT" in str(model.requests[-1].messages)
            assert "interrupted" in str(model.requests[-1].messages)
        rejected = await handle_turn_resume_operation(request_id=4, params={"thread_id": "thread", "turn_id": turn_id}, context=context)
        assert "error" in rejected.response  # normal completion cannot resume
    finally:
        context.runtime_task_registry.clear()
        await wait_live_background_tasks()
        await db.close()


@pytest.mark.asyncio
async def test_stop_before_kernel_starts_then_resume_uses_accepted_input(tmp_path):
    model = ScriptedModel("stream")
    # The cancelled execution never sampled; the first resumed request completes.
    model.requests.append(None)
    db = await open_core_app_db(tmp_path / "core.db")
    context = await context_for(db, tmp_path, model)
    try:
        accepted = await handle_turn_start_operation(request_id=1, params={
            "thread_id": "thread", "input": [{"type": "text", "text": "early original task"}],
            "include_snapshot": False,
        }, context=context)
        turn_id = accepted.runtime_start["turn_id"]
        # No yield to the runtime task between acceptance and Stop.
        await handle_turn_pause_operation(request_id=2, params={"thread_id": "thread", "turn_id": turn_id}, context=context)
        await wait_live_background_tasks()
        resumed = await handle_turn_resume_operation(request_id=3, params={"thread_id": "thread", "turn_id": turn_id}, context=context)
        assert "error" not in resumed.response, resumed.response
        assert resumed.runtime_start["text"] == "" or "early original task" in resumed.runtime_start["text"]
        # Stop the resumed attempt before it starts too: terminal identities
        # must be distinct even though the Turn ID is unchanged.
        await handle_turn_pause_operation(request_id=4, params={"thread_id": "thread", "turn_id": turn_id}, context=context)
        await wait_live_background_tasks()
        resumed = await handle_turn_resume_operation(request_id=5, params={"thread_id": "thread", "turn_id": turn_id}, context=context)
        assert "error" not in resumed.response, resumed.response
        await context.runtime_task_registry.task("thread")
        history = await db.runtime_state_store.get_history("thread")
        assert not [row for row in history if row["role"] == "user"]
        assert "early original task" in str(history)
    finally:
        context.runtime_task_registry.clear()
        await wait_live_background_tasks()
        await db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("second_action", ["stop", "steer"])
async def test_resumed_execution_uses_same_steering_identity_and_can_stop_again(tmp_path, second_action):
    class Model(ScriptedModel):
        def __init__(self):
            super().__init__("stream")
            self.boundaries = [asyncio.Event(), asyncio.Event()]
            self.release = asyncio.Event()
        async def stream(self, request):
            self.requests.append(request)
            index = len(self.requests) - 1
            if index < 2:
                self.boundaries[index].set()
                await self.release.wait()
            yield LLMStreamEvent(kind="content_delta", content="done")
            yield LLMStreamEvent(kind="done")
    model = Model()
    db = await open_core_app_db(tmp_path / "core.db")
    context = await context_for(db, tmp_path, model)
    try:
        accepted = await handle_turn_start_operation(request_id=1, params={
            "thread_id": "thread", "input": [{"type": "text", "text": "task"}], "include_snapshot": False,
        }, context=context)
        turn_id = accepted.runtime_start["turn_id"]
        await asyncio.wait_for(model.boundaries[0].wait(), 10)
        task = context.runtime_task_registry.task("thread")
        await handle_turn_pause_operation(request_id=2, params={"thread_id": "thread", "turn_id": turn_id}, context=context)
        await asyncio.gather(task, return_exceptions=True)
        await wait_live_background_tasks()
        first = await handle_turn_resume_operation(request_id=3, params={"thread_id": "thread", "turn_id": turn_id}, context=context)
        await asyncio.wait_for(model.boundaries[1].wait(), 10)
        task = context.runtime_task_registry.task("thread")
        # A second Resume cannot steal a running execution.
        busy = await handle_turn_resume_operation(request_id=4, params={"thread_id": "thread", "turn_id": turn_id}, context=context)
        assert "error" in busy.response
        if second_action == "stop":
            await handle_turn_pause_operation(request_id=5, params={"thread_id": "thread", "turn_id": turn_id}, context=context)
            await asyncio.gather(task, return_exceptions=True)
            await wait_live_background_tasks()
            second = await handle_turn_resume_operation(request_id=6, params={"thread_id": "thread", "turn_id": turn_id}, context=context)
            assert second.runtime_start["turn_id"] == turn_id
            assert second.runtime_start["run_id"] != first.runtime_start["run_id"]
            task = context.runtime_task_registry.task("thread")
        else:
            guided = await handle_turn_steer_operation(request_id=5, params={
                "thread_id": "thread", "turn_id": turn_id, "client_message_id": "resume-guidance",
                "input": [{"type": "text", "text": "steering after resume"}], "include_snapshot": False,
            }, context=context)
            assert guided.response["result"]["applied"] is True
            model.release.set()
        await asyncio.wait_for(task, 10)
        history = await db.runtime_state_store.get_history("thread")
        if second_action == "steer":
            assert "steering after resume" in str(model.requests[-1].messages)
            assert any("resume-guidance" in row.get("metadata", {}).get("guidance_ids", []) for row in history)
        else:
            assert len([row for row in history if row["role"] == "user"]) == 1
        async with db.session_factory() as session:
            snapshot = await db.persistence.load(session, "thread")
        assert list(snapshot["turns"]) == [turn_id]
        assert snapshot["turns"][turn_id]["status"] == "completed"
    finally:
        context.runtime_task_registry.clear()
        await wait_live_background_tasks()
        await db.close()


@pytest.mark.asyncio
async def test_restart_closes_each_orphaned_resumed_attempt_without_auto_execution(tmp_path, monkeypatch):
    model = ScriptedModel("stream")
    model.requests.append(None)
    db = await open_core_app_db(tmp_path / "core.db")
    context = await context_for(db, tmp_path, model)
    try:
        accepted = await handle_turn_start_operation(request_id=1, params={
            "thread_id": "thread", "input": [{"type": "text", "text": "original task"}], "include_snapshot": False,
        }, context=context)
        turn_id = accepted.runtime_start["turn_id"]
        await handle_turn_pause_operation(request_id=2, params={"thread_id": "thread", "turn_id": turn_id}, context=context)
        await wait_live_background_tasks()
        monkeypatch.setattr("lamtools_core.runtime_owner.owner_is_live", lambda token: False)
        for attempt in range(2):
            execution_id = f"orphaned-execution-{attempt}"
            async def leave_interrupted(session):
                await db.persistence.append(session, AppEventInput(thread_id="thread", turn_id=turn_id,
                    method="turn/started", payload={"resumed": True, "status": "running", "run_id": execution_id}))
            await db.persistence.write(leave_interrupted)
            state = await db.runtime_state_store.get("thread") or RuntimeState(session_id="thread")
            state.run_id = execution_id
            state.status = "running"
            state.metadata["turn_id"] = turn_id
            await db.runtime_state_store.save(state)
            await db.close()
            db = await open_core_app_db(tmp_path / "core.db")
            context = await context_for(db, tmp_path, model)
            assert await recover_stale_active_turns(context=context) == 1
            state = await db.runtime_state_store.get("thread")
            assert state.status == "cancelled"
            assert state.metadata["cancellation_reason"] == "unexpected_shutdown"
            async with db.session_factory() as session:
                snapshot = await db.persistence.load(session, "thread")
            assert snapshot["turns"][turn_id]["status"] == "cancelled"
            assert len(model.requests) == 1
            assert not context.runtime_task_registry.is_running("thread")
        # A turn the runtime ended on its own is a terminated turn now: the
        # crash left an interruption, not a pause, so there is nothing to
        # continue. Only a paused turn survives a restart as resumable.
        refused = await handle_turn_resume_operation(
            request_id=3, params={"thread_id": "thread", "turn_id": turn_id}, context=context
        )
        assert "error" in refused.response, refused.response
    finally:
        context.runtime_task_registry.clear()
        await wait_live_background_tasks()
        await db.close()


@pytest.mark.asyncio
async def test_cli_resume_routes_to_the_same_live_operation(monkeypatch):
    from lamtools_core import cli
    from lamtools_core.app.live_client import CoreAppServerClient
    calls = []
    class Client:
        async def request(self, method, params):
            calls.append((method, params))
            return {"turn_id": "turn"}
        resume_turn = CoreAppServerClient.resume_turn
    async def invoke(args, callback):
        return await callback(Client())
    monkeypatch.setattr(cli, "_invoke_live", invoke)
    args = cli.build_parser().parse_args(["resume", "thread", "--turn-id", "turn", "--raw"])
    assert await args.func(args) == 0
    assert calls == [("turn.resume", {"thread_id": "thread", "turn_id": "turn"})]


@pytest.mark.asyncio
async def test_failed_resume_transaction_releases_claim_and_keeps_interruption(tmp_path, monkeypatch):
    model = ScriptedModel("stream")
    db = await open_core_app_db(tmp_path / "core.db")
    context = await context_for(db, tmp_path, model)
    try:
        accepted = await handle_turn_start_operation(request_id=1, params={
            "thread_id": "thread", "input": [{"type": "text", "text": "task"}], "include_snapshot": False,
        }, context=context)
        turn_id = accepted.runtime_start["turn_id"]
        await handle_turn_pause_operation(request_id=2, params={"thread_id": "thread", "turn_id": turn_id}, context=context)
        await wait_live_background_tasks()
        async def fail(*args, **kwargs):
            raise RuntimeError("resume commit failed")
        monkeypatch.setattr(db.persistence, "append", fail)
        with pytest.raises(RuntimeError, match="resume commit failed"):
            await handle_turn_resume_operation(request_id=3, params={"thread_id": "thread", "turn_id": turn_id}, context=context)
        assert context.runtime_task_registry.active_run_id("thread") is None
        assert model.requests == []
        async with db.session_factory() as session:
            snapshot = await db.persistence.load(session, "thread")
        # The failed resume must leave the turn exactly as the pause left it.
        assert snapshot["turns"][turn_id]["status"] == "paused"
    finally:
        context.runtime_task_registry.clear()
        await wait_live_background_tasks()
        await db.close()
