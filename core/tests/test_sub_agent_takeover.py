"""Core Task 1C — child takeover on Stop/Resume and question-answer resume.

Two behaviors are pinned here:

1. When the parent turn is already terminal but children are still active, the
   Stop/Resume controls address the children themselves. The parent turn is
   neither restarted nor re-cancelled while the user takes over its members.
2. When a child asks a question through the parent interface, answering resumes
   that child with the user's answer as its own tool result: the answer is
   persisted in the child session's history (never the parent's) and the child
   continues on its own identity.

All models are scripted and state stores are in-memory; zero paid provider
calls, no production database, no live host.
"""
from __future__ import annotations

import asyncio
import sys
import uuid

import pytest

from lamtools_core.app import CoreAgentPaths, CoreAgentSpec, create_core_agent_operations
from lamtools_core.event import CollectingEventSink
from lamtools_core.llm import LLMRequest, LLMResponse, LLMStreamEvent, LLMToolCall
from lamtools_core.runtime import InMemoryRuntimeStateStore
from lamtools_core.tool.sub_agent_runner import KernelSubAgentRunner
from lamtools_core.sub_agent_supervisor import (
    find_sub_agent_supervisor,
    shutdown_parent_sub_agents,
)

# Supervisors live in a process-global map keyed by (data_dir, thread), and the
# lookup helper matches on thread id alone, so every test needs its own thread:
# reusing one id made a test resolve another test's supervisor.
THREAD = "thread-1c-takeover"
CHILD_SESSION = f"{THREAD}:sub:worker"


@pytest.fixture(autouse=True)
def _unique_thread(monkeypatch):
    global THREAD, CHILD_SESSION
    suffix = uuid.uuid4().hex[:8]
    THREAD = f"thread-1c-{suffix}"
    CHILD_SESSION = f"{THREAD}:sub:worker"
    monkeypatch.setattr(sys.modules[__name__], "THREAD", THREAD, raising=False)
    monkeypatch.setattr(sys.modules[__name__], "CHILD_SESSION", CHILD_SESSION, raising=False)


def _write_project_model(tmp_path, model_id: str, capability: str = "text") -> None:
    """jsonc is the single source of truth for model capability."""
    models_dir = tmp_path / ".lam" / "config" / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    (models_dir / f"{model_id}.jsonc").write_text(
        "{\n"
        f'  "model_id": "{model_id}",\n'
        f'  "display_name": "{model_id}",\n'
        '  "provider": "test",\n'
        f'  "capability": "{capability}",\n'
        '  "notes": "",\n'
        '  "is_default": false\n'
        "}\n",
        encoding="utf-8",
    )


def _catalog(tmp_path, llm, state_store):
    work_root = tmp_path / "work"
    work_root.mkdir(parents=True, exist_ok=True)
    _write_project_model(work_root, "fake-model")
    return create_core_agent_operations(
        spec=CoreAgentSpec(default_model="fake-model"),
        paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=work_root),
        model_provider=llm,
        runtime_state_store=state_store,
    )


async def _wait_for_child_status(catalog, thread_id: str, status: str) -> str:
    """Poll the durable member list until it reports ``status`` (or time out)."""
    listed = await catalog.execute("sub_agent.list", {"thread_id": thread_id})
    for _ in range(200):
        current = listed.payload["items"][0]["status"] if listed.payload["items"] else ""
        if current == status:
            return current
        await asyncio.sleep(0.01)
        listed = await catalog.execute("sub_agent.list", {"thread_id": thread_id})
    return listed.payload["items"][0]["status"] if listed.payload["items"] else ""


async def shutdown_parent_supervisor(thread_id: str) -> None:
    supervisor = find_sub_agent_supervisor(thread_id)
    assert supervisor is not None
    await supervisor.shutdown()


class _ParentDelegateMixin:
    """Shared parent script: create the member, then answer the user."""

    def __init__(self) -> None:
        self.parent_calls = 0

    def _parent_stream(self, request: LLMRequest, *, create: bool):
        self.parent_calls += 1
        if create:
            yield LLMStreamEvent(kind="done", tool_calls=[
                LLMToolCall(
                    id="call-create-member",
                    name="sub_agent",
                    arguments={
                        "action": "create", "type": "execute", "name": "worker",
                        "model": "fake-model", "reasoning_level": "high",
                    },
                )
            ])
            return
        yield LLMStreamEvent(kind="content_delta", content="Main remains responsive.")
        yield LLMStreamEvent(kind="done")


class InterruptibleChildLLM(_ParentDelegateMixin):
    """The child's first model call blocks until Stop interrupts it."""

    def __init__(self) -> None:
        super().__init__()
        self.child_calls = 0
        self.child_started = asyncio.Event()
        self.resume_prompt_seen = False

    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise AssertionError("Core operation should use streaming")

    async def stream(self, request: LLMRequest):
        tool_names = {tool["function"]["name"] for tool in request.tools or []}
        if "sub_agent" in tool_names:
            for event in self._parent_stream(request, create=self.parent_calls == 0):
                yield event
            return
        self.child_calls += 1
        if self.child_calls == 1:
            self.child_started.set()
            # Only task.cancel() ends this: the member stays genuinely running
            # while the parent turn is already over.
            await asyncio.Event().wait()
        self.resume_prompt_seen = any(
            "Continue the interrupted sub-agent task" in str(getattr(message, "content", ""))
            for message in request.messages
        )
        yield LLMStreamEvent(kind="content_delta", content="Child resumed and finished.")
        yield LLMStreamEvent(kind="done")


class QuestionChildLLM(_ParentDelegateMixin):
    """The child asks a question and pauses until the user answers."""

    def __init__(self) -> None:
        super().__init__()
        self.child_calls = 0
        self.answer_seen = ""
        self.question_row_written = False

    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise AssertionError("Core operation should use streaming")

    async def stream(self, request: LLMRequest):
        tool_names = {tool["function"]["name"] for tool in request.tools or []}
        if "sub_agent" in tool_names:
            for event in self._parent_stream(request, create=self.parent_calls == 0):
                yield event
            return
        self.child_calls += 1
        if self.child_calls == 1:
            yield LLMStreamEvent(kind="done", tool_calls=[
                LLMToolCall(
                    id="call-child-question",
                    name="question",
                    arguments={
                        "question": "Which color should the report use?",
                        "options": [{"label": "blue"}, {"label": "green"}],
                    },
                )
            ])
            return
        for message in request.messages:
            if getattr(message, "role", "") == "tool" and getattr(message, "name", "") == "question":
                self.question_row_written = True
        self.answer_seen = " ".join(
            str(getattr(message, "content", "")) for message in request.messages
        )
        yield LLMStreamEvent(kind="content_delta", content="Child finished with the answer.")
        yield LLMStreamEvent(kind="done")


@pytest.mark.asyncio
async def test_child_stop_takes_over_a_running_member_after_the_parent_turn_ended(tmp_path):
    llm = InterruptibleChildLLM()
    state_store = InMemoryRuntimeStateStore()
    catalog = _catalog(tmp_path, llm, state_store)

    started = await catalog.execute(
        "turn.start",
        {"thread_id": THREAD, "message": "delegate the work", "approval_policy": "require"},
    )
    assert started.payload["decision"] == "done"
    assert llm.parent_calls == 2
    parent_state = await state_store.get(THREAD)
    assert parent_state is not None
    assert parent_state.status not in {"running", "waiting", "interrupting"}
    parent_history_before = await state_store.get_history(THREAD)

    accepted = await catalog.execute(
        "sub_agent.message",
        {"thread_id": THREAD, "type": "execute", "name": "worker", "prompt": "long job"},
    )
    assert accepted.status == "ok"
    assert await asyncio.wait_for(llm.child_started.wait(), timeout=5)

    # The parent turn is over, the member is still working: Stop addresses the
    # member, and nothing about the parent turn changes.
    stopped = await catalog.execute("sub_agent.interrupt", {"thread_id": THREAD})
    assert stopped.status == "ok"
    assert stopped.payload["lifecycle_action"] == "members_interrupted"
    assert [item["status"] for item in stopped.payload["items"]] == ["interrupted"]
    listed = await catalog.execute("sub_agent.list", {"thread_id": THREAD})
    assert listed.payload["items"][0]["status"] == "interrupted"

    child_state = await state_store.get(CHILD_SESSION)
    assert child_state is not None
    assert child_state.status == "cancelled"
    assert "pending_approval" not in child_state.metadata

    assert llm.parent_calls == 2
    parent_state_after = await state_store.get(THREAD)
    assert parent_state_after.status == parent_state.status
    assert await state_store.get_history(THREAD) == parent_history_before
    await shutdown_parent_sub_agents(THREAD)


@pytest.mark.asyncio
async def test_child_resume_continues_the_interrupted_member_without_restarting_the_parent(tmp_path):
    llm = InterruptibleChildLLM()
    state_store = InMemoryRuntimeStateStore()
    catalog = _catalog(tmp_path, llm, state_store)

    started = await catalog.execute(
        "turn.start",
        {"thread_id": THREAD, "message": "delegate the work", "approval_policy": "require"},
    )
    assert started.payload["decision"] == "done"
    accepted = await catalog.execute(
        "sub_agent.message",
        {"thread_id": THREAD, "type": "execute", "name": "worker", "prompt": "long job"},
    )
    assert accepted.status == "ok"
    assert await asyncio.wait_for(llm.child_started.wait(), timeout=5)
    stopped = await catalog.execute("sub_agent.interrupt", {"thread_id": THREAD})
    assert stopped.status == "ok"
    assert llm.parent_calls == 2

    resumed = await catalog.execute("sub_agent.resume", {"thread_id": THREAD})
    assert resumed.status == "ok"
    assert resumed.payload["lifecycle_action"] == "members_resumed"
    assert [item["status"] for item in resumed.payload["items"]] == ["running"]

    assert await _wait_for_child_status(catalog, THREAD, "idle") == "idle"
    listed = await catalog.execute("sub_agent.list", {"thread_id": THREAD})
    assert listed.payload["items"][0]["summary"] == "Child resumed and finished."
    assert llm.child_calls == 2
    assert llm.resume_prompt_seen is True
    # Resume continued the member; the parent turn was never restarted for it.
    assert llm.parent_calls == 2
    await shutdown_parent_sub_agents(THREAD)


@pytest.mark.asyncio
async def test_takeover_operations_are_registered_on_the_catalog(tmp_path):
    llm = InterruptibleChildLLM()
    state_store = InMemoryRuntimeStateStore()
    catalog = _catalog(tmp_path, llm, state_store)
    assert catalog.has("sub_agent.interrupt")
    assert catalog.has("sub_agent.resume")
    # Both refuse a thread with no live member rather than inventing one.
    idle = await catalog.execute("sub_agent.interrupt", {"thread_id": "thread-without-members"})
    assert idle.status == "ok"
    assert idle.payload["items"] == []


@pytest.mark.asyncio
async def test_answered_child_question_resumes_that_child_with_the_answer(tmp_path):
    llm = QuestionChildLLM()
    state_store = InMemoryRuntimeStateStore()
    catalog = _catalog(tmp_path, llm, state_store)

    started = await catalog.execute(
        "turn.start",
        {"thread_id": THREAD, "message": "delegate the work", "approval_policy": "require"},
    )
    assert started.payload["decision"] == "done"
    accepted = await catalog.execute(
        "sub_agent.message",
        {
            "thread_id": THREAD, "type": "execute", "name": "worker",
            "prompt": "start the report",
        },
    )
    assert accepted.status == "ok"
    for _ in range(200):
        listed = await catalog.execute("sub_agent.list", {"thread_id": THREAD})
        if listed.payload["items"][0]["status"] == "paused":
            break
        await asyncio.sleep(0.01)
    assert listed.payload["items"][0]["status"] == "paused"

    child_state = await state_store.get(CHILD_SESSION)
    assert child_state is not None
    pending = child_state.metadata["pending_approval"]
    assert pending["tool_call"]["name"] == "question"

    # An option click travels as an approval decision with the option text in
    # the guidance payload (exactly what the UI sends for a question card).
    answered = await catalog.execute(
        "approval.respond",
        {
            "thread_id": THREAD,
            "request_id": pending["request_id"],
            "decision": "approve_once",
            "guidance": "blue",
        },
    )
    assert answered.status == "ok"
    assert llm.child_calls == 2

    # The answer is the child's own tool result, in the child's history.
    child_history = await state_store.get_history(CHILD_SESSION)
    question_rows = [row for row in child_history if row.get("name") == "question"]
    assert question_rows, child_history
    assert question_rows[-1]["role"] == "tool"
    assert question_rows[-1]["content"] == "blue"
    assert question_rows[-1]["tool_call_id"] == "call-child-question"
    assert llm.question_row_written is True
    assert "blue" in llm.answer_seen

    # It never lands in the parent thread's history, and the parent turn did
    # not run again to deliver it.
    parent_history = await state_store.get_history(THREAD)
    assert not [row for row in parent_history if row.get("name") == "question"]
    assert llm.parent_calls == 2

    listed = await catalog.execute("sub_agent.list", {"thread_id": THREAD})
    assert listed.payload["items"][0]["status"] == "idle"
    assert listed.payload["items"][0]["summary"] == "Child finished with the answer."
    await shutdown_parent_supervisor(THREAD)


@pytest.mark.asyncio
async def test_free_text_answer_also_resumes_the_child_that_asked(tmp_path):
    llm = QuestionChildLLM()
    state_store = InMemoryRuntimeStateStore()
    catalog = _catalog(tmp_path, llm, state_store)

    await catalog.execute(
        "turn.start",
        {"thread_id": THREAD, "message": "delegate the work", "approval_policy": "require"},
    )
    accepted = await catalog.execute(
        "sub_agent.message",
        {
            "thread_id": THREAD, "type": "execute", "name": "worker",
            "prompt": "start the report",
        },
    )
    assert accepted.status == "ok"
    for _ in range(200):
        listed = await catalog.execute("sub_agent.list", {"thread_id": THREAD})
        if listed.payload["items"][0]["status"] == "paused":
            break
        await asyncio.sleep(0.01)
    child_state = await state_store.get(CHILD_SESSION)
    pending = child_state.metadata["pending_approval"]

    answered = await catalog.execute(
        "approval.respond",
        {
            "thread_id": THREAD,
            "request_id": pending["request_id"],
            "decision": "other_guidance",
            "guidance": "use the brand palette",
        },
    )
    assert answered.status == "ok"

    child_history = await state_store.get_history(CHILD_SESSION)
    question_rows = [row for row in child_history if row.get("name") == "question"]
    assert question_rows[-1]["content"] == "use the brand palette"
    assert "use the brand palette" in llm.answer_seen
    assert llm.parent_calls == 2
    listed = await catalog.execute("sub_agent.list", {"thread_id": THREAD})
    assert listed.payload["items"][0]["status"] == "idle"
    await shutdown_parent_supervisor(THREAD)


class QuestionMainLLM:
    """The main agent asks a question through the same card a child would use."""

    def __init__(self) -> None:
        self.main_calls = 0
        self.answer_seen = ""

    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise AssertionError("Core operation should use streaming")

    async def stream(self, request: LLMRequest):
        self.main_calls += 1
        if self.main_calls == 1:
            yield LLMStreamEvent(kind="done", tool_calls=[
                LLMToolCall(
                    id="call-main-question",
                    name="question",
                    arguments={
                        "question": "Proceed with the report?",
                        "options": [{"label": "yes"}, {"label": "no"}],
                    },
                )
            ])
            return
        self.answer_seen = " ".join(
            str(getattr(message, "content", "")) for message in request.messages
        )
        yield LLMStreamEvent(kind="content_delta", content="Main continued after the answer.")
        yield LLMStreamEvent(kind="done")


@pytest.mark.asyncio
async def test_main_agent_option_click_still_lands_in_the_thread_history(tmp_path):
    """Regression guard for the shared question path: an option click on the
    main agent's question answers it in the thread that asked, as before."""
    llm = QuestionMainLLM()
    state_store = InMemoryRuntimeStateStore()
    catalog = _catalog(tmp_path, llm, state_store)

    started = await catalog.execute(
        "turn.start",
        {"thread_id": THREAD, "message": "ask me first", "approval_policy": "require"},
    )
    assert started.payload["decision"] == "wait"
    state = await state_store.get(THREAD)
    pending = state.metadata["pending_approval"]
    assert pending["tool_call"]["name"] == "question"

    answered = await catalog.execute(
        "approval.respond",
        {
            "thread_id": THREAD,
            "request_id": pending["request_id"],
            "decision": "approve_once",
            "guidance": "yes",
        },
    )
    assert answered.status == "ok"
    history = await state_store.get_history(THREAD)
    rows = [row for row in history if row.get("name") == "question"]
    assert rows and rows[-1]["role"] == "tool"
    assert rows[-1]["content"] == "yes"
    assert "yes" in llm.answer_seen


def test_cli_exposes_child_takeover_verbs() -> None:
    from lamtools_core.cli import build_parser

    parser = build_parser()
    interrupt = parser.parse_args(["subagent", "interrupt", "thread-1"])
    resume = parser.parse_args(["subagent", "resume", "thread-1"])
    assert (interrupt.subagent_command, interrupt.thread_id) == ("interrupt", "thread-1")
    assert (resume.subagent_command, resume.thread_id) == ("resume", "thread-1")


@pytest.mark.asyncio
async def test_dismissed_child_question_still_resumes_the_child(tmp_path):
    """Dismissing a child's question (deny/cancel) must not strand the child:
    it continues with the recorded 'declined' answer instead of staying paused."""
    llm = QuestionChildLLM()
    state_store = InMemoryRuntimeStateStore()
    catalog = _catalog(tmp_path, llm, state_store)

    await catalog.execute(
        "turn.start",
        {"thread_id": THREAD, "message": "delegate the work", "approval_policy": "require"},
    )
    accepted = await catalog.execute(
        "sub_agent.message",
        {
            "thread_id": THREAD, "type": "execute", "name": "worker",
            "prompt": "start the report",
        },
    )
    assert accepted.status == "ok"
    for _ in range(200):
        listed = await catalog.execute("sub_agent.list", {"thread_id": THREAD})
        if listed.payload["items"][0]["status"] == "paused":
            break
        await asyncio.sleep(0.01)
    child_state = await state_store.get(CHILD_SESSION)
    pending = child_state.metadata["pending_approval"]

    dismissed = await catalog.execute(
        "approval.respond",
        {"thread_id": THREAD, "request_id": pending["request_id"], "decision": "deny"},
    )
    assert dismissed.status == "ok"

    child_history = await state_store.get_history(CHILD_SESSION)
    question_rows = [row for row in child_history if row.get("name") == "question"]
    assert question_rows[-1]["content"] == "用户取消了该问题，未提供回答。"
    assert llm.child_calls == 2
    listed = await catalog.execute("sub_agent.list", {"thread_id": THREAD})
    assert listed.payload["items"][0]["status"] == "idle"
    await shutdown_parent_supervisor(THREAD)
# ── Bug 3: the child question card must resolve in place, and a second child's
# answer must be admitted while the first child keeps working ────────────────

@pytest.mark.asyncio
async def test_question_answer_reuses_the_waiting_items_identity(tmp_path):
    """The answer's events must carry the identity the question was asked under.

    The projection scopes a child's items by (child run, invocation). Reusing
    that scope is what makes the answer update the card that asked instead of
    creating a second item and leaving the first stuck as waiting.
    """
    llm = QuestionChildLLM()
    state_store = InMemoryRuntimeStateStore()
    sink = CollectingEventSink(None, should_collect=lambda _event: True)
    runner = KernelSubAgentRunner(
        work_root=tmp_path,
        llm_client=llm,
        model_id="fake-model",
        state_store=state_store,
        session_prefix="parent-thread",
        parent_event_sink=sink,
    )

    result = await runner.run(task="ask the user", agent="asker")
    assert result.decision == "wait"
    request = next(e for e in sink.events if e.name == "runtime.approval_request")
    requested_identity = dict(request.payload["sub_agent"])
    child_state = await state_store.get("parent-thread:sub:asker")
    assert child_state.metadata["sub_invocation_id"] == requested_identity["invocation_id"]

    await runner.resume_question(
        session_id="parent-thread:sub:asker",
        pending_call=dict(child_state.metadata["pending_approval"]["tool_call"]),
        task="ask the user",
        agent="asker",
        parent_call_id="",
        answer="blue",
        question="Which colour?",
    )
    resolved = [
        event for event in sink.events
        if event.name == "runtime.tool.finished"
        and (event.payload or {}).get("tool_name") == "question"
    ]
    assert resolved, "the answer must be published on the parent timeline"
    resolved_identity = dict(resolved[-1].payload["sub_agent"])
    assert resolved_identity["run_id"] == requested_identity["run_id"]
    assert resolved_identity["invocation_id"] == requested_identity["invocation_id"]
    assert resolved_identity["parent_item_key"] == requested_identity["parent_item_key"]


@pytest.mark.asyncio
async def test_refused_continuation_leaves_the_question_answerable(tmp_path):
    """A refused claim must roll the pending back, not strand it as 'executing'."""
    llm = QuestionChildLLM()
    state_store = InMemoryRuntimeStateStore()
    catalog = _catalog(tmp_path, llm, state_store)

    await catalog.execute(
        "turn.start",
        {"thread_id": THREAD, "message": "delegate the work", "approval_policy": "require"},
    )
    accepted = await catalog.execute(
        "sub_agent.message",
        {"thread_id": THREAD, "type": "execute", "name": "worker", "prompt": "start"},
    )
    assert accepted.status == "ok"
    for _ in range(200):
        listed = await catalog.execute("sub_agent.list", {"thread_id": THREAD})
        if listed.payload["items"][0]["status"] == "paused":
            break
        await asyncio.sleep(0.01)
    child_state = await state_store.get(CHILD_SESSION)
    pending = child_state.metadata["pending_approval"]

    async def refused(_info):
        raise RuntimeError("approval continuation runtime claim failed")

    with pytest.raises(RuntimeError):
        await catalog.execute(
            "approval.respond",
            {
                "thread_id": THREAD,
                "request_id": pending["request_id"],
                "decision": "approve_once",
                "guidance": "blue",
            },
            metadata={"approval_decision_durable": refused},
        )
    after = await state_store.get(CHILD_SESSION)
    assert after.metadata["pending_approval"]["status"] == "waiting", after.metadata["pending_approval"]

    retried = await catalog.execute(
        "approval.respond",
        {
            "thread_id": THREAD,
            "request_id": pending["request_id"],
            "decision": "approve_once",
            "guidance": "blue",
        },
    )
    assert retried.status == "ok", retried.payload
    assert llm.child_calls == 2
    await shutdown_parent_supervisor(THREAD)


@pytest.mark.asyncio
async def test_child_continuation_is_admitted_per_child_session(tmp_path):
    """A child continuation claims its own session, never the parent thread.

    Claiming the parent made one child's answer block every other child (and a
    new parent turn) for as long as that child kept working, which is what made
    a second question card unanswerable.
    """
    llm = QuestionChildLLM()
    state_store = InMemoryRuntimeStateStore()
    catalog = _catalog(tmp_path, llm, state_store)

    await catalog.execute(
        "turn.start",
        {"thread_id": THREAD, "message": "delegate the work", "approval_policy": "require"},
    )
    accepted = await catalog.execute(
        "sub_agent.message",
        {"thread_id": THREAD, "type": "execute", "name": "worker", "prompt": "start"},
    )
    assert accepted.status == "ok", accepted.payload
    for _ in range(200):
        listed = await catalog.execute("sub_agent.list", {"thread_id": THREAD})
        if listed.payload["items"][0]["status"] == "paused":
            break
        await asyncio.sleep(0.01)
    child_state = await state_store.get(CHILD_SESSION)
    pending = child_state.metadata["pending_approval"]

    seen: dict[str, object] = {}

    async def durable(info):
        seen.update(info)
        return None

    answered = await catalog.execute(
        "approval.respond",
        {
            "thread_id": THREAD,
            "request_id": pending["request_id"],
            "decision": "approve_once",
            "guidance": "blue",
        },
        metadata={"approval_decision_durable": durable},
    )
    assert answered.status == "ok", answered.payload
    assert seen["thread_id"] == THREAD, "events stay on the parent timeline"
    assert seen["claim_thread_id"] == CHILD_SESSION, "the claim is per child session"
    await shutdown_parent_supervisor(THREAD)


class _StubPersistence:
    """Just enough persistence for the cancel finalizer's record attempt."""

    async def load(self, _db, thread_id: str):
        return {"thread_id": thread_id, "turns": {}, "items": {}, "item_order": [],
                "core": {"turns": {}, "items": {}, "item_order": []}}

    async def write(self, action):
        return await action(object())

    async def assert_revision(self, _db, _thread_id, _revision):
        return None


class _StubHub:
    async def publish(self, _event) -> None:
        return None


@pytest.mark.asyncio
async def test_user_stop_interrupts_the_sessions_running_children(tmp_path):
    """A user Stop must leave nothing of this session working behind it."""
    from types import SimpleNamespace

    from lamtools_core.app.live_operations import (
        handle_turn_cancel_operation,
        wait_live_background_tasks,
    )
    from lamtools_core.runtime import default_runtime_task_registry

    llm = InterruptibleChildLLM()
    state_store = InMemoryRuntimeStateStore()
    catalog = _catalog(tmp_path, llm, state_store)

    await catalog.execute(
        "turn.start",
        {"thread_id": THREAD, "message": "delegate the work", "approval_policy": "require"},
    )
    accepted = await catalog.execute(
        "sub_agent.message",
        {"thread_id": THREAD, "type": "execute", "name": "worker", "prompt": "long job"},
    )
    assert accepted.status == "ok"
    assert await asyncio.wait_for(llm.child_started.wait(), timeout=5)
    assert llm.parent_calls == 2

    context = SimpleNamespace(
        persistence=_StubPersistence(),
        hub=_StubHub(),
        host=SimpleNamespace(runtime_task_registry=default_runtime_task_registry()),
        session_factory=None,
        runtime_state_store=state_store,
    )
    outcome = await handle_turn_cancel_operation(
        request_id=1, params={"thread_id": THREAD}, context=context
    )
    assert outcome.response.get("error") is None, outcome.response
    await wait_live_background_tasks()

    listed = await catalog.execute("sub_agent.list", {"thread_id": THREAD})
    assert listed.payload["items"][0]["status"] == "interrupted", listed.payload
    child_state = await state_store.get(CHILD_SESSION)
    assert child_state is not None and child_state.status == "cancelled"
    assert llm.parent_calls == 2, "stopping must not restart the parent"
    await shutdown_parent_supervisor(THREAD)
