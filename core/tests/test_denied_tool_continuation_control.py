"""user:“修”+(拒绝主代理工具后续跑必须及时返回，并能被终止。)"""

import asyncio

import pytest

from lamtools_core.app import CoreAgentPaths, CoreAgentSpec, create_core_agent_operations, open_core_app_db
from lamtools_core.app.live_hub import CoreAppEventHub
from lamtools_core.app.live_operations import CoreLiveContext
from lamtools_core.llm import LLMStreamEvent, LLMToolCall
from lamtools_core.runtime import RuntimeTaskRegistry


@pytest.mark.asyncio
async def test_denied_main_tool_acknowledges_and_remains_terminable(tmp_path):
    started = asyncio.Event()
    release = asyncio.Event()

    class Model:
        calls = 0

        async def complete(self, request):
            raise AssertionError("the continuation must use the streaming model")

        async def stream(self, request):
            self.calls += 1
            if self.calls == 1:
                yield LLMStreamEvent(kind="done", tool_calls=[LLMToolCall(
                    id="write-1", name="write_file",
                    arguments={"path": "denied.txt", "content": "must not be written"},
                )])
                return
            started.set()
            await release.wait()
            yield LLMStreamEvent(kind="content_delta", content="I will choose another approach.")
            yield LLMStreamEvent(kind="done")

    db = await open_core_app_db(tmp_path / "core.db")
    registry = RuntimeTaskRegistry()
    hub = CoreAppEventHub()
    operations = create_core_agent_operations(
        spec=CoreAgentSpec(default_model="fixture"),
        paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=tmp_path),
        model_provider=Model(),
        runtime_state_store=db.runtime_state_store,
        runtime_task_registry=registry,
        db_session_factory=db.session_factory,
        app_event_store=db.event_store,
        thread_snapshot_store=db.snapshot_store,
        app_event_hub=hub,
        write_coordinator=db.persistence.write_coordinator,
    )
    context = CoreLiveContext(
        session_factory=db.session_factory, persistence=db.persistence,
        operations=operations, hub=hub, runtime_task_registry=registry,
        runtime_state_store=db.runtime_state_store,
    )
    rpc = None
    continuation = None
    try:
        waiting = await operations.execute("turn.start", {
            "thread_id": "denied-control", "message": "write a file",
        })
        assert waiting.payload["decision"] == "wait"
        state = await db.runtime_state_store.get("denied-control")
        request_id = state.metadata["pending_approval"]["request_id"]
        rpc = asyncio.create_task(context.host.execute(
            "approval.respond", request_id=1,
            params={"thread_id": "denied-control", "request_id": request_id, "decision": "deny"},
            context=context,
        ))
        await asyncio.wait_for(started.wait(), timeout=5)
        continuation = registry.task("denied-control")
        assert continuation is not None and not continuation.done()
        outcome = await asyncio.wait_for(asyncio.shield(rpc), timeout=2)
        assert outcome.response["result"]["status"] == "accepted"
        assert not (tmp_path / "denied.txt").exists()

        terminated = await asyncio.wait_for(context.host.execute(
            "turn.terminate", request_id=2,
            params={"thread_id": "denied-control", "turn_id": waiting.payload["turn_id"]},
            context=context,
        ), timeout=5)
        assert "error" not in terminated.response
        await asyncio.wait_for(asyncio.gather(continuation, return_exceptions=True), timeout=5)
        state = await db.runtime_state_store.get("denied-control")
        assert state.status == "cancelled"
    finally:
        release.set()
        if rpc is not None:
            await asyncio.wait_for(asyncio.gather(rpc, return_exceptions=True), timeout=5)
        if continuation is not None:
            await asyncio.wait_for(asyncio.gather(continuation, return_exceptions=True), timeout=5)
        await registry.shutdown()
        await db.close()
