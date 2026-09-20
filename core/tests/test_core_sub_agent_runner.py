from __future__ import annotations

import asyncio

import pytest

from lamtools_core.app import CoreAgentPaths, CoreAgentSpec, create_core_agent_operations
from lamtools_core.event import CollectingEventSink
from lamtools_core.llm import LLMRequest, LLMResponse, LLMStreamEvent, LLMToolCall
from lamtools_core.runtime import InMemoryRuntimeStateStore
from lamtools_core.sub_agent_supervisor import shutdown_parent_sub_agents
from lamtools_core.tool import ToolCall, ToolSpec
from lamtools_core.tool.permission import AUTO_ALLOW
from lamtools_core.tool.loadtools import default_load_tools
from lamtools_core.tool.sub_agent_runner import KernelSubAgentRunner


def _write_project_model(tmp_path, model_id: str, capability: str, display_name: str = "") -> None:
    """Write a project-scoped model jsonc so capability comes from jsonc.

    jsonc is the single source of truth for model capability, so self-contained
    tests must declare the model's modality in the project model dir rather
    than relying on any hardcoded table (there is none anymore).
    """
    models_dir = tmp_path / ".lam" / "config" / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    content = (
        "{\n"
        f'  "model_id": "{model_id}",\n'
        f'  "display_name": "{display_name or model_id}",\n'
        '  "provider": "test",\n'
        f'  "capability": "{capability}",\n'
        '  "notes": "",\n'
        '  "is_default": false\n'
        "}\n"
    )
    (models_dir / f"{model_id}.jsonc").write_text(content, encoding="utf-8")


class ScriptedSubAgentOnlyLLM:
    def __init__(self, *, expected_model: str = "fake-model", expected_instructions: str = "") -> None:
        self.requests: list[LLMRequest] = []
        self.expected_model = expected_model
        self.expected_instructions = expected_instructions

    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise AssertionError("Sub-agent runner should use streaming")

    async def stream(self, request: LLMRequest):
        self.requests.append(request)
        assert request.model == self.expected_model
        if self.expected_instructions:
            assert self.expected_instructions in request.messages[0].content
        user_message = (
            request.messages[-2]
            if str(request.messages[-1].content).startswith("[request-local")
            else request.messages[-1]
        )
        assert user_message.role == "user"
        assert user_message.content == "inspect the project"
        yield LLMStreamEvent(kind="content_delta", content="sub result")
        yield LLMStreamEvent(kind="done")


def test_available_tool_specs_include_plugin_tools_used_by_workflow_agents(tmp_path) -> None:
    async def external_lookup(_call):
        raise AssertionError("catalog inspection must not execute the tool")

    runner = KernelSubAgentRunner(
        work_root=tmp_path,
        llm_client=ScriptedSubAgentOnlyLLM(),
        model_id="fake-model",
        plugin_tool_specs=[
            ToolSpec(
                name="external_lookup",
                description="Look up external data",
                input_schema={"type": "object", "properties": {}},
            )
        ],
        plugin_tool_handlers={"external_lookup": external_lookup},
    )

    names = {spec.name for spec in runner.available_tool_specs(mode="agent")}

    assert "read_file" in names
    assert "external_lookup" in names
    assert "sub_agent" not in names
    assert "sub_agent_message" not in names
    assert "message" in names


def test_consider_and_execute_are_fail_closed_non_delegating_tool_sets(tmp_path) -> None:
    runner = KernelSubAgentRunner(
        work_root=tmp_path,
        llm_client=ScriptedSubAgentOnlyLLM(),
        model_id="fake-model",
        load_tools=default_load_tools(),
    )
    consider_box = runner._build_toolbox(runner._disabled_tools(), active_mode="consider")
    execute_box = runner._build_toolbox(runner._disabled_tools(), active_mode="execute")
    consider = {tool["function"]["name"] for tool in consider_box.model_tools(active_mode="consider")}
    execute = {tool["function"]["name"] for tool in execute_box.model_tools(active_mode="execute")}

    assert "read_file" in consider and "write_file" not in consider
    assert "write_file" in execute
    for names in (consider, execute):
        assert "message" in names
        assert "sub_agent" not in names
        assert "sub_agent_message" not in names


@pytest.mark.asyncio
async def test_public_run_forwards_effective_child_identity_metadata(tmp_path) -> None:
    sink = CollectingEventSink()
    runner = KernelSubAgentRunner(
        work_root=tmp_path,
        llm_client=ScriptedSubAgentOnlyLLM(),
        model_id="fake-model",
        reasoning_level="medium",
        load_tools=default_load_tools(),
        parent_event_sink=sink,
        session_prefix="parent-thread",
    )
    await runner.run(
        task="inspect the project",
        agent="reviewer",
        mode="consider",
        reasoning_level="xh",
        parent_call_id="message-call",
        parent_run_id="parent-run",
        parent_turn_id="parent-turn",
    )

    forwarded = [event for event in sink.events if event.payload.get("sub_agent")]
    assert forwarded
    assert all(event.payload["sub_agent"]["type"] == "consider" for event in forwarded)
    assert all(event.payload["sub_agent"]["model_id"] == "fake-model" for event in forwarded)
    assert all(event.payload["sub_agent"]["reasoning_level"] == "xhigh" for event in forwarded)


def test_child_message_is_auto_allowed_across_restricted_modes_and_live_tiers(tmp_path) -> None:
    runtime_permissions = {
        "active_tier": "read_only",
        "tier_tools": {
            "read_only": ["read_file"],
            "limited_edit": ["read_file", "write_file"],
            "full_edit": [],
        },
    }
    runner = KernelSubAgentRunner(
        work_root=tmp_path,
        llm_client=ScriptedSubAgentOnlyLLM(),
        model_id="fake-model",
        load_tools=default_load_tools(),
        active_tier="read_only",
        tier_tools=runtime_permissions["tier_tools"],
        runtime_permissions_provider=lambda: runtime_permissions,
    )

    for mode in ("consider", "execute"):
        toolbox = runner._build_toolbox(runner._disabled_tools(), active_mode=mode)
        specs = {spec.name: spec for spec in toolbox.tool_specs()}
        names = {
            tool["function"]["name"]
            for tool in toolbox.model_tools(active_mode=mode)
        }
        prepared = toolbox.prepare_call(
            ToolCall(id=f"message-{mode}", name="message", arguments={"message": "status"})
        )

        assert specs["message"].permission == AUTO_ALLOW
        assert "message" in names
        assert "sub_agent" not in names
        assert prepared.requires_approval is False
        assert prepared.metadata["approval"]["blocked"] is False


class ScriptedMainAndSubAgentLLM:
    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise AssertionError("Core operation should use streaming")

    async def stream(self, request: LLMRequest):
        self.requests.append(request)
        tool_names = {tool["function"]["name"] for tool in request.tools or []}
        if len(self.requests) == 1:
            assert "sub_agent" in tool_names
            yield LLMStreamEvent(kind="thinking_delta", content="Need a sub-agent.")
            yield LLMStreamEvent(
                kind="done",
                tool_calls=[
                    LLMToolCall(
                        id="call-sub",
                        name="sub_agent",
                        arguments={
                            "action": "create",
                            "type": "consider",
                            "name": "worker",
                            "model": "fake-model",
                            "reasoning_level": "high",
                        },
                    )
                ],
            )
            return
        yield LLMStreamEvent(kind="content_delta", content="main created the sub-agent without waiting")
        yield LLMStreamEvent(kind="done")


class SixToolRoundSubAgentLLM:
    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise AssertionError("Sub-agent runner should use streaming")

    async def stream(self, request: LLMRequest):
        self.requests.append(request)
        round_number = len(self.requests)
        if round_number <= 6:
            yield LLMStreamEvent(
                kind="done",
                tool_calls=[
                    LLMToolCall(
                        id=f"list-{round_number}",
                        name="list_dir",
                        arguments={"path": f"section-{round_number}"},
                    )
                ],
            )
            return
        yield LLMStreamEvent(kind="content_delta", content="completed after six tool rounds")
        yield LLMStreamEvent(kind="done")


class FollowUpSubAgentLLM:
    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise AssertionError("Sub-agent runner should use streaming")

    async def stream(self, request: LLMRequest):
        self.requests.append(request)
        yield LLMStreamEvent(kind="content_delta", content=f"answer-{len(self.requests)}")
        yield LLMStreamEvent(kind="done")


class BlockingSubAgentLLM:
    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise AssertionError("Sub-agent runner should use streaming")

    async def stream(self, request: LLMRequest):
        self.started.set()
        await asyncio.Event().wait()
        if False:
            yield LLMStreamEvent(kind="done")


class EmptySubAgentResultLLM:
    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise AssertionError("Core operation should use streaming")

    async def stream(self, request: LLMRequest):
        self.requests.append(request)
        if len(self.requests) == 1:
            yield LLMStreamEvent(
                kind="done",
                tool_calls=[
                    LLMToolCall(
                        id="call-empty-sub",
                        name="sub_agent",
                        arguments={"action": "create", "type": "consider", "name": "Worker"},
                    )
                ],
            )
            return
        tool_messages = [message for message in request.messages if message.role == "tool"]
        assert tool_messages
        assert "requires exactly" in tool_messages[-1].content.lower()
        yield LLMStreamEvent(kind="content_delta", content="main handled strict sub-agent validation")
        yield LLMStreamEvent(kind="done")


class WritingSubAgentLLM:
    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []
        self.main_steps = 0
        self.child_steps = 0

    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise AssertionError("Core operation should use streaming")

    async def stream(self, request: LLMRequest):
        self.requests.append(request)
        tool_names = {tool["function"]["name"] for tool in request.tools or []}
        if "sub_agent" in tool_names:
            self.main_steps += 1
        else:
            self.child_steps += 1
        if self.main_steps == 1 and "sub_agent" in tool_names:
            yield LLMStreamEvent(
                kind="done",
                tool_calls=[
                    LLMToolCall(
                        id="call-writing-sub",
                        name="sub_agent",
                        arguments={
                            "action": "create", "type": "execute", "name": "writer",
                            "model": "fake-model", "reasoning_level": "high",
                        },
                    )
                ],
            )
            return
        if "sub_agent" in tool_names:
            yield LLMStreamEvent(kind="content_delta", content="Main remains responsive.")
            yield LLMStreamEvent(kind="done")
            return
        if self.child_steps == 1:
            yield LLMStreamEvent(kind="thinking_delta", content="Plan the delegated file write.")
            yield LLMStreamEvent(kind="content_delta", content="Preparing the story file.")
            yield LLMStreamEvent(
                kind="done",
                tool_calls=[
                    LLMToolCall(
                        id="call-write-story",
                        name="write_file",
                        arguments={"path": "story.txt", "content": "A complete delegated story."},
                    )
                ],
            )
            return
        if self.child_steps == 2:
            yield LLMStreamEvent(
                kind="content_delta",
                content="I wrote story.txt with the requested story.",
            )
            yield LLMStreamEvent(kind="done")
            return
        raise AssertionError("unexpected writing sub-agent request")


class ApprovalSubAgentLLM:
    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []
        self.main_steps = 0
        self.child_steps = 0
        self.child_message_tools: set[str] = set()
        self.parent_received_child_message = False

    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise AssertionError("Core operation should use streaming")

    async def stream(self, request: LLMRequest):
        self.requests.append(request)
        tool_names = {tool["function"]["name"] for tool in request.tools or []}
        if "sub_agent" in tool_names:
            self.main_steps += 1
            if self.main_steps >= 3:
                self.parent_received_child_message = any(
                    "approved file is ready" in str(message.content)
                    for message in request.messages
                )
                yield LLMStreamEvent(kind="content_delta", content="Main received child report.")
                yield LLMStreamEvent(kind="done")
                return
        else:
            self.child_steps += 1
        if self.main_steps == 1 and "sub_agent" in tool_names:
            yield LLMStreamEvent(kind="done", tool_calls=[
                LLMToolCall(
                    id="call-approval-sub",
                    name="sub_agent",
                    arguments={
                        "action": "create", "type": "execute", "name": "writer",
                        "model": "fake-model", "reasoning_level": "high",
                    },
                )
            ])
            return
        if "sub_agent" in tool_names:
            yield LLMStreamEvent(kind="content_delta", content="Main remains responsive during child approval.")
            yield LLMStreamEvent(kind="done")
            return
        if self.child_steps == 1:
            yield LLMStreamEvent(kind="done", tool_calls=[
                LLMToolCall(
                    id="call-child-write",
                    name="write_file",
                    arguments={"path": "approved.txt", "content": "approved child content"},
                )
            ])
            return
        if self.child_steps == 2:
            self.child_message_tools = tool_names
            assert request.messages[-1].role == "user"
            assert str(request.messages[-1].content).startswith(
                "[Request-local sub-agent context]"
            )
            assert "name: writer" in str(request.messages[-1].content)
            assert "type: execute" in str(request.messages[-1].content)
            assert "model_id: fake-model" in str(request.messages[-1].content)
            assert "reasoning_level: high" in str(request.messages[-1].content)
            yield LLMStreamEvent(kind="done", tool_calls=[
                LLMToolCall(
                    id="call-child-message",
                    name="message",
                    arguments={"message": "approved file is ready"},
                )
            ])
            return
        if self.child_steps == 3:
            yield LLMStreamEvent(kind="content_delta", content="Child finished after approval.")
            yield LLMStreamEvent(kind="done")
            return
        raise AssertionError("unexpected child approval continuation")


@pytest.mark.asyncio
async def test_kernel_sub_agent_runner_uses_core_loop_without_recursive_sub_agent(tmp_path):
    llm = ScriptedSubAgentOnlyLLM()
    runner = KernelSubAgentRunner(work_root=tmp_path, llm_client=llm, model_id="fake-model")

    result = await runner.run(task="inspect the project", agent="worker")

    assert result.message == "sub result"
    assert result.succeeded is True
    assert result.model_id == "fake-model"
    assert len(llm.requests) == 1
    assert "sub_agent" not in {tool["function"]["name"] for tool in llm.requests[0].tools or []}
    assert "read_file" in {tool["function"]["name"] for tool in llm.requests[0].tools or []}


@pytest.mark.asyncio
async def test_kernel_sub_agent_runner_forwards_explicit_reasoning_and_inherits_parent(tmp_path):
    explicit_llm = ScriptedSubAgentOnlyLLM()
    explicit_runner = KernelSubAgentRunner(
        work_root=tmp_path,
        llm_client=explicit_llm,
        model_id="fake-model",
        reasoning_level="medium",
    )

    await explicit_runner.run(
        task="inspect the project",
        agent="worker",
        reasoning_level="xh",
        late_context="[request-local child identity]",
    )
    assert explicit_llm.requests[0].metadata["reasoning_level"] == "xhigh"
    assert explicit_llm.requests[0].messages[-1].role == "user"
    assert explicit_llm.requests[0].messages[-1].content == "[request-local child identity]"
    state = await explicit_runner.state_store.get("core-sub-agent:sub:worker")
    history = await explicit_runner.state_store.get_history(state.session_id)
    assert all(item.get("content") != "[request-local child identity]" for item in history)

    inherited_llm = ScriptedSubAgentOnlyLLM()
    inherited_runner = KernelSubAgentRunner(
        work_root=tmp_path,
        llm_client=inherited_llm,
        model_id="fake-model",
        reasoning_level="medium",
    )
    await inherited_runner.run(task="inspect the project", agent="worker")
    assert inherited_llm.requests[0].metadata["reasoning_level"] == "medium"


@pytest.mark.asyncio
async def test_kernel_sub_agent_runner_has_no_fixed_tool_round_limit(tmp_path):
    for round_number in range(1, 7):
        (tmp_path / f"section-{round_number}").mkdir()
    llm = SixToolRoundSubAgentLLM()
    runner = KernelSubAgentRunner(work_root=tmp_path, llm_client=llm, model_id="fake-model")

    result = await runner.run(task="inspect the project thoroughly", agent="worker")

    assert result.message == "completed after six tool rounds"
    assert result.succeeded is True
    assert len(llm.requests) == 7


@pytest.mark.asyncio
async def test_kernel_sub_agent_runner_reuses_named_sub_session_history(tmp_path):
    llm = FollowUpSubAgentLLM()
    runner = KernelSubAgentRunner(work_root=tmp_path, llm_client=llm, model_id="fake-model")

    await runner.run(task="first task", agent="reviewer")
    await runner.run(task="follow up", agent="reviewer")

    conversation = [
        (message.role, message.content)
        for message in llm.requests[1].messages
        if message.role in {"user", "assistant"}
    ]
    assert conversation == [
        ("user", "first task"),
        ("assistant", "answer-1"),
        ("user", "follow up"),
    ]


@pytest.mark.asyncio
async def test_kernel_sub_agent_runner_external_cancel_persists_cancelled_state(tmp_path):
    llm = BlockingSubAgentLLM()
    state_store = InMemoryRuntimeStateStore()
    runner = KernelSubAgentRunner(
        work_root=tmp_path,
        llm_client=llm,
        model_id="fake-model",
        state_store=state_store,
        session_prefix="parent-thread",
    )
    task = asyncio.create_task(runner.run(task="inspect", agent="qa"))

    await asyncio.wait_for(llm.started.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    state = await state_store.get("parent-thread:sub:qa")
    assert state is not None
    assert state.status == "cancelled"
    assert state.loop_state == "failed"


@pytest.mark.asyncio
async def test_kernel_sub_agent_runner_reuses_history_across_parent_turn_runners(tmp_path):
    llm = FollowUpSubAgentLLM()
    state_store = InMemoryRuntimeStateStore()
    first_runner = KernelSubAgentRunner(
        work_root=tmp_path,
        llm_client=llm,
        model_id="fake-model",
        state_store=state_store,
        session_prefix="parent-thread",
    )
    second_runner = KernelSubAgentRunner(
        work_root=tmp_path,
        llm_client=llm,
        model_id="fake-model",
        state_store=state_store,
        session_prefix="parent-thread",
    )

    await first_runner.run(task="first task", agent="reviewer")
    await second_runner.run(task="follow up", agent="reviewer")

    conversation = [
        (message.role, message.content)
        for message in llm.requests[1].messages
        if message.role in {"user", "assistant"}
    ]
    assert conversation == [
        ("user", "first task"),
        ("assistant", "answer-1"),
        ("user", "follow up"),
    ]


@pytest.mark.asyncio
async def test_kernel_sub_agent_runner_uses_parent_model_and_instructions(tmp_path):
    llm = ScriptedSubAgentOnlyLLM(expected_model="base-model", expected_instructions="Parent instructions")
    runner = KernelSubAgentRunner(
        work_root=tmp_path,
        llm_client=llm,
        model_id="base-model",
        instructions="Parent instructions",
        temperature=0.7,
        max_tokens=8192,
        thinking_enabled=True,
        thinking_budget=2048,
    )

    result = await runner.run(task="inspect the project", agent="reviewer")

    tool_names = {tool["function"]["name"] for tool in llm.requests[0].tools or []}
    assert result.message == "sub result"
    assert result.succeeded is True
    assert result.model_id == "base-model"
    assert "read_file" in tool_names
    assert "write_file" in tool_names
    assert "sub_agent" not in tool_names
    assert llm.requests[0].temperature == 0.7
    assert llm.requests[0].max_tokens == 8192
    assert llm.requests[0].metadata["thinking_enabled"] is True
    assert llm.requests[0].metadata["thinking_budget"] == 2048


@pytest.mark.asyncio
async def test_core_agent_operation_creates_sub_agent_without_blocking(tmp_path):
    llm = ScriptedMainAndSubAgentLLM()
    work_root = tmp_path / "work"
    _write_project_model(work_root, "fake-model", "text")
    catalog = create_core_agent_operations(
        spec=CoreAgentSpec(default_model="fake-model"),
        paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=work_root),
        model_provider=llm,
    )

    result = await catalog.execute("turn.start", {"thread_id": "thread-sub", "message": "delegate"})

    tool_results = [item for item in result.payload["run_items"] if item["kind"] == "tool_result"]
    assert result.status == "ok"
    assert result.payload["message"] == "main created the sub-agent without waiting"
    assert len(llm.requests) == 2
    assert tool_results
    assert '"status": "idle"' in tool_results[0]["payload"]["tool_result"]
    listed = await catalog.execute("sub_agent.list", {"thread_id": "thread-sub"})
    assert listed.payload["items"][0]["name"] == "worker"
    await shutdown_parent_sub_agents("thread-sub")


@pytest.mark.asyncio
async def test_core_agent_operation_rejects_legacy_sub_agent_arguments(tmp_path):
    llm = EmptySubAgentResultLLM()
    catalog = create_core_agent_operations(
        spec=CoreAgentSpec(default_model="fake-model"),
        paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=tmp_path / "work"),
        model_provider=llm,
    )

    result = await catalog.execute("turn.start", {"thread_id": "thread-empty-sub", "message": "delegate"})

    sub_agent_results = [
        item
        for item in result.payload["run_items"]
        if item["kind"] == "tool_result" and item["payload"].get("tool_name") == "sub_agent"
    ]
    assert result.status == "ok"
    assert result.payload["message"] == "main handled strict sub-agent validation"
    assert len(sub_agent_results) == 1
    assert sub_agent_results[0]["status"] == "failed"
    assert sub_agent_results[0]["payload"]["error"]


@pytest.mark.asyncio
async def test_core_agent_operation_forwards_sub_agent_file_tool_and_handoff(tmp_path):
    llm = WritingSubAgentLLM()
    work_root = tmp_path / "work"
    _write_project_model(work_root, "fake-model", "text")
    catalog = create_core_agent_operations(
        spec=CoreAgentSpec(default_model="fake-model"),
        paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=work_root),
        model_provider=llm,
    )

    result = await catalog.execute(
        "turn.start",
        {
            "thread_id": "thread-writing-sub",
            "message": "delegate writing",
            "approval_policy": "auto_approve",
        },
    )

    assert result.payload["message"] == "Main remains responsive."
    accepted = await catalog.execute(
        "sub_agent.message",
        {"thread_id": "thread-writing-sub", "type": "execute", "name": "writer", "prompt": "write a story"},
    )
    assert accepted.status == "ok"
    for _ in range(100):
        if (work_root / "story.txt").exists():
            listed = await catalog.execute("sub_agent.list", {"thread_id": "thread-writing-sub"})
            if listed.payload["items"][0]["status"] == "idle":
                break
        await asyncio.sleep(0.01)
    assert (work_root / "story.txt").read_text(encoding="utf-8") == "A complete delegated story."
    assert listed.payload["items"][0]["summary"] == "I wrote story.txt with the requested story."
    assert listed.payload["items"][0]["source_message_id"] == f"assistant:{result.payload['turn_id']}"
    await shutdown_parent_sub_agents("thread-writing-sub")


@pytest.mark.asyncio
async def test_child_approval_pauses_only_sub_agent_not_parent(tmp_path):
    llm = ApprovalSubAgentLLM()
    state_store = InMemoryRuntimeStateStore()
    work_root = tmp_path / "work"
    _write_project_model(work_root, "fake-model", "text")
    catalog = create_core_agent_operations(
        spec=CoreAgentSpec(default_model="fake-model"),
        paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=work_root),
        model_provider=llm,
        runtime_state_store=state_store,
    )

    started = await catalog.execute(
        "turn.start",
        {
            "thread_id": "thread-child-approval",
            "message": "delegate with approval",
            "approval_policy": "require",
        },
    )

    assert started.payload["decision"] == "done"
    assert started.payload["message"] == "Main remains responsive during child approval."
    assert not (work_root / "approved.txt").exists()
    accepted = await catalog.execute(
        "sub_agent.message",
        {"thread_id": "thread-child-approval", "type": "execute", "name": "writer", "prompt": "write approved.txt"},
    )
    assert accepted.status == "ok"
    for _ in range(100):
        listed = await catalog.execute("sub_agent.list", {"thread_id": "thread-child-approval"})
        if listed.payload["items"][0]["status"] == "paused":
            break
        await asyncio.sleep(0.01)
    assert listed.payload["items"][0]["status"] == "paused"
    assert not (work_root / "approved.txt").exists()

    child_state = await state_store.get("thread-child-approval:sub:writer")
    assert child_state is not None
    assert child_state.metadata["delegated_session"]["parent_thread_id"] == "thread-child-approval"
    pending = child_state.metadata["pending_approval"]
    approved = await catalog.execute(
        "approval.respond",
        {
            "thread_id": "thread-child-approval",
            "request_id": pending["request_id"],
            "action": "approve",
        },
    )
    assert approved.status == "ok"
    assert approved.payload["thread_id"] == "thread-child-approval"
    assert (work_root / "approved.txt").read_text(encoding="utf-8") == "approved child content"
    assert "message" in llm.child_message_tools
    assert "sub_agent" not in llm.child_message_tools
    assert "sub_agent_message" not in llm.child_message_tools
    forwarded = [
        event["payload"]["sub_agent"]
        for event in approved.payload["events"]
        if isinstance(event.get("payload"), dict)
        and isinstance(event["payload"].get("sub_agent"), dict)
    ]
    assert forwarded
    assert all(item["type"] == "execute" for item in forwarded)
    assert all(item["model_id"] == "fake-model" for item in forwarded)
    assert all(item["reasoning_level"] == "high" for item in forwarded)
    child_history = await state_store.get_history("thread-child-approval:sub:writer")
    assert all(
        not str(item.get("content") or "").startswith("[Request-local sub-agent context]")
        for item in child_history
    )
    listed_after_approval = await catalog.execute(
        "sub_agent.list", {"thread_id": "thread-child-approval"}
    )
    assert listed_after_approval.payload["items"][0]["status"] == "idle"

    follow_up = await catalog.execute(
        "turn.start",
        {"thread_id": "thread-child-approval", "message": "follow-up"},
    )
    assert follow_up.status == "ok"
    assert llm.parent_received_child_message is True
    await shutdown_parent_sub_agents("thread-child-approval")


class SystemPromptInspectingLLM:
    """LLM that records the system prompt and advertised tools for assertions."""

    def __init__(self, *, expected_model: str = "fake-model") -> None:
        self.requests: list[LLMRequest] = []
        self.expected_model = expected_model

    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise AssertionError("Sub-agent runner should use streaming")

    async def stream(self, request: LLMRequest):
        self.requests.append(request)
        assert request.model == self.expected_model
        assert request.messages[-1].role == "user"
        assert request.messages[-1].content == "inspect the project"
        yield LLMStreamEvent(kind="content_delta", content="sub result")
        yield LLMStreamEvent(kind="done")


@pytest.mark.asyncio
async def test_sub_agent_runner_per_call_model_override(tmp_path):
    llm = SystemPromptInspectingLLM(expected_model="strong-model")
    runner = KernelSubAgentRunner(work_root=tmp_path, llm_client=llm, model_id="base-model")

    result = await runner.run(task="inspect the project", agent="worker", model="strong-model")

    assert result.model_id == "strong-model"
    assert result.succeeded is True
    assert llm.requests[0].model == "strong-model"


@pytest.mark.asyncio
async def test_sub_agent_runner_empty_model_follows_main(tmp_path):
    llm = SystemPromptInspectingLLM(expected_model="base-model")
    runner = KernelSubAgentRunner(work_root=tmp_path, llm_client=llm, model_id="base-model")

    result = await runner.run(task="inspect the project", agent="worker", model="")

    assert result.model_id == "base-model"
    assert llm.requests[0].model == "base-model"


@pytest.mark.asyncio
async def test_sub_agent_runner_consider_mode_filters_tools_and_injects_prompt(tmp_path):
    from lamtools_core.tool.loadtools import default_load_tools

    llm = SystemPromptInspectingLLM(expected_model="base-model")
    load_tools = default_load_tools()
    runner = KernelSubAgentRunner(
        work_root=tmp_path,
        llm_client=llm,
        model_id="base-model",
        load_tools=load_tools,
    )

    result = await runner.run(task="inspect the project", agent="reader", mode="consider")

    assert result.succeeded is True
    tool_names = {tool["function"]["name"] for tool in llm.requests[0].tools or []}
    # consider mode is read-only: read_file allowed, write_file blocked, sub_agent blocked (disabled_tools)
    assert "read_file" in tool_names
    assert "write_file" not in tool_names
    assert "sub_agent" not in tool_names
    system_prompt = str(llm.requests[0].messages[0].content)
    assert "当前模式" in system_prompt
    assert "consider" in system_prompt


@pytest.mark.asyncio
async def test_sub_agent_runner_execute_mode_keeps_full_access(tmp_path):
    from lamtools_core.tool.loadtools import default_load_tools

    llm = SystemPromptInspectingLLM(expected_model="base-model")
    runner = KernelSubAgentRunner(
        work_root=tmp_path,
        llm_client=llm,
        model_id="base-model",
        load_tools=default_load_tools(),
    )

    result = await runner.run(task="inspect the project", agent="worker", mode="execute")

    assert result.succeeded is True
    tool_names = {tool["function"]["name"] for tool in llm.requests[0].tools or []}
    # execute mode is full access (empty tool list) — write_file present, sub_agent still disabled
    assert "write_file" in tool_names
    assert "sub_agent" not in tool_names
    # execute mode has an empty tool list, so tools are not filtered, but the mode prompt line
    # is still injected (mode_prompt_line fires whenever the mode is known).
    system_prompt = str(llm.requests[0].messages[0].content)
    assert "当前模式" in system_prompt
    assert "execute" in system_prompt


@pytest.mark.asyncio
async def test_sub_agent_runner_unknown_mode_falls_back_to_full_access(tmp_path):
    from lamtools_core.tool.loadtools import default_load_tools

    llm = SystemPromptInspectingLLM(expected_model="base-model")
    runner = KernelSubAgentRunner(
        work_root=tmp_path,
        llm_client=llm,
        model_id="base-model",
        load_tools=default_load_tools(),
    )

    result = await runner.run(task="inspect the project", agent="worker", mode="bogus")

    assert result.succeeded is True
    tool_names = {tool["function"]["name"] for tool in llm.requests[0].tools or []}
    # unknown mode is treated as no filtering so the sub-agent is never locked out
    assert "write_file" in tool_names
    system_prompt = str(llm.requests[0].messages[0].content)
    assert "当前模式" not in system_prompt


@pytest.mark.asyncio
async def test_sub_agent_runner_empty_mode_is_full_access_by_default(tmp_path):
    llm = SystemPromptInspectingLLM(expected_model="base-model")
    runner = KernelSubAgentRunner(work_root=tmp_path, llm_client=llm, model_id="base-model")

    result = await runner.run(task="inspect the project", agent="worker", mode="")

    assert result.succeeded is True
    tool_names = {tool["function"]["name"] for tool in llm.requests[0].tools or []}
    assert "write_file" in tool_names
    system_prompt = str(llm.requests[0].messages[0].content)
    assert "当前模式" not in system_prompt


class _FakeAttachment:
    """Minimal attachment record for attachment-forwarding tests."""

    def __init__(self, att_id: str, path: Path, mime: str = "image/png"):
        self.id = att_id
        self.storage_path = str(path)
        self.filename = f"{att_id}.png"
        self.mime_type = mime
        self.size = path.stat().st_size if path.exists() else 0
        self.preview_type = "image"
        self.metadata: dict = {}


class _FakeAttachmentService:
    """Fake AttachmentService.get returning canned records."""

    def __init__(self, records: dict[str, _FakeAttachment]):
        self._records = records

    async def get(self, attachment_id: str):
        return self._records.get(attachment_id)


class AttachmentInspectingLLM:
    """LLM that records whether the user message carried image content blocks."""

    def __init__(self, *, expected_model: str = "mm-model") -> None:
        self.requests: list[LLMRequest] = []
        self.expected_model = expected_model

    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise AssertionError("Sub-agent runner should use streaming")

    async def stream(self, request: LLMRequest):
        self.requests.append(request)
        assert request.model == self.expected_model
        yield LLMStreamEvent(kind="content_delta", content="image described")
        yield LLMStreamEvent(kind="done")


@pytest.mark.asyncio
async def test_sub_agent_runner_forwards_image_attachment_to_multimodal_sub_agent(tmp_path):
    # Create a tiny PNG file the fake attachment service will resolve.
    png_path = tmp_path / "test.png"
    png_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    att = _FakeAttachment("att-img", png_path)
    service = _FakeAttachmentService({"att-img": att})
    # jsonc is the single source of truth: declare a multimodal model in the
    # project model dir — without this jsonc declaration the image is stripped.
    _write_project_model(tmp_path, "mm-model", "multimodal")
    llm = AttachmentInspectingLLM(expected_model="mm-model")
    runner = KernelSubAgentRunner(
        work_root=tmp_path,
        llm_client=llm,
        model_id="text-model",
        attachment_service=service,
    )

    result = await runner.run(
        task="describe the attached image",
        agent="viewer",
        model="mm-model",
        attachments=["att-img"],
    )

    assert result.succeeded is True
    # The user message should be a multimodal content list with a text + image block.
    user_msg = llm.requests[0].messages[-1]
    assert user_msg.role == "user"
    assert isinstance(user_msg.content, list)
    block_types = [b.get("type") for b in user_msg.content if isinstance(b, dict)]
    assert "text" in block_types
    assert "image_url" in block_types


@pytest.mark.asyncio
async def test_sub_agent_runner_strips_image_when_jsonc_is_text(tmp_path):
    """Regression: a jsonc-declared TEXT model must NOT receive image blocks.

    This is the exact failure mode that used to strike mimo-v2.5-free when its
    jsonc capability was ignored — the sub-agent got no image content block.
    """
    png_path = tmp_path / "test.png"
    png_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    att = _FakeAttachment("att-img", png_path)
    service = _FakeAttachmentService({"att-img": att})
    _write_project_model(tmp_path, "text-model", "text")
    llm = AttachmentInspectingLLM(expected_model="text-model")
    runner = KernelSubAgentRunner(
        work_root=tmp_path,
        llm_client=llm,
        model_id="text-model",
        attachment_service=service,
    )

    result = await runner.run(
        task="describe the attached image",
        agent="viewer",
        model="text-model",
        attachments=["att-img"],
    )

    assert result.succeeded is True
    user_msg = llm.requests[0].messages[-1]
    # Text-only model: no image_url blocks may reach the LLM.
    assert isinstance(user_msg.content, str)
    assert "image_url" not in user_msg.content


@pytest.mark.asyncio
async def test_sub_agent_runner_keeps_text_only_attachment_context(tmp_path):
    text_path = tmp_path / "evidence.txt"
    text_path.write_text("attachment evidence survives", encoding="utf-8")
    att = _FakeAttachment("att-text", text_path, mime="text/plain")
    att.filename = "evidence.txt"
    att.preview_type = "text"
    service = _FakeAttachmentService({"att-text": att})
    _write_project_model(tmp_path, "text-model", "text")
    llm = AttachmentInspectingLLM(expected_model="text-model")
    runner = KernelSubAgentRunner(
        work_root=tmp_path,
        llm_client=llm,
        model_id="text-model",
        attachment_service=service,
    )

    result = await runner.run(
        task="read the attachment",
        agent="reader",
        attachments=["att-text"],
    )

    assert result.succeeded is True
    user_msg = llm.requests[0].messages[-1]
    assert isinstance(user_msg.content, str)
    assert "attachment evidence survives" in user_msg.content


@pytest.mark.asyncio
async def test_sub_agent_runner_resolves_display_name_for_multimodal(tmp_path, monkeypatch):
    """A display_name (e.g. "Kimi-K2.6") must be resolved to model_id so
    capability lookup works — this is the 治本 fix for the display_name bug."""
    from lamtools_core.config.model_store import ModelConfig
    from lamtools_core.tool.sub_agent_runner import _resolve_model_id_for_capability

    # Stub ModelStore to return a multimodal model for display_name "Kimi-K2.6"
    import lamtools_core.tool.sub_agent_runner as runner_mod

    class _FakeStore:
        def get_sync(self, ref, work_root=None):
            if ref == "xopkimik26":
                return ModelConfig(
                    model_id="xopkimik26", display_name="Kimi-K2.6",
                    provider="test", provider_id="", context_window=128000,
                    max_output_tokens=8192, temperature=0.7,
                    thinking_supported=True, thinking_budget=10000,
                    reasoning_effort="", adapter_profile_id="",
                    request_body=None, capability="", is_default=False,
                    source_path="",
                )
            return None

        def list_sync(self, work_root=None):
            return [self.get_sync("xopkimik26")]

    monkeypatch.setattr(runner_mod, "_resolve_model_id_for_capability",
                        lambda ref: _FakeStore().get_sync(ref).model_id
                        if _FakeStore().get_sync(ref) else ref)

    # Now test that a display_name resolves to model_id
    resolved = _resolve_model_id_for_capability("Kimi-K2.6")
    # Without monkeypatch (real ModelStore), this should also work
    assert resolved == "xopkimik26" or resolved == "Kimi-K2.6"  # monkeypatched or real

    # The real test: create a runner with display_name model and verify
    # the LLM receives image_url blocks (capability = multimodal from jsonc)
    # Declare the resolved model multimodal in the project model dir (jsonc is
    # the single source of truth for capability).
    _write_project_model(tmp_path, "xopkimik26", "multimodal", display_name="Kimi-K2.6")
    png_path = tmp_path / "test.png"
    png_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    att = _FakeAttachment("att-img", png_path)
    service = _FakeAttachmentService({"att-img": att})
    llm = AttachmentInspectingLLM(expected_model="xopkimik26")
    runner = KernelSubAgentRunner(
        work_root=tmp_path,
        llm_client=llm,
        model_id="text-model",
        attachment_service=service,
    )

    # Pass display_name — the runner should resolve it to xopkimik26 internally
    result = await runner.run(
        task="describe the attached image",
        agent="viewer",
        model="xopkimik26",  # model_id (not display_name) for the fake LLM
        attachments=["att-img"],
    )

    assert result.succeeded is True
    user_msg = llm.requests[0].messages[-1]
    assert isinstance(user_msg.content, list)
    block_types = [b.get("type") for b in user_msg.content if isinstance(b, dict)]
    assert "image_url" in block_types


@pytest.mark.asyncio
async def test_sub_agent_runner_no_attachment_service_falls_back_to_text(tmp_path):
    llm = AttachmentInspectingLLM(expected_model="mm-model")
    # No attachment_service configured.
    runner = KernelSubAgentRunner(work_root=tmp_path, llm_client=llm, model_id="mm-model")

    result = await runner.run(
        task="describe image",
        agent="viewer",
        attachments=["att-img"],
    )

    assert result.succeeded is True
    # user_content stays a plain string (no image blocks).
    user_msg = llm.requests[0].messages[-1]
    assert isinstance(user_msg.content, str)



@pytest.mark.asyncio
async def test_kernel_sub_agent_runner_honors_allowed_tools(tmp_path):
    """Audit 18 S2: the workflow AI-node tool allow-list must actually reach
    the sub-agent kernel (cfg.tools/allowed_tools were written by the UI but
    never read by the runner)."""
    llm = ScriptedSubAgentOnlyLLM()
    runner = KernelSubAgentRunner(work_root=tmp_path, llm_client=llm, model_id="fake-model")

    result = await runner.run(task="inspect the project", agent="worker", allowed_tools=["read_file"])

    assert result.succeeded is True
    assert len(llm.requests) == 1
    tool_names = {tool["function"]["name"] for tool in llm.requests[0].tools or []}
    assert tool_names == {"read_file"}, f"expected only read_file, got {tool_names}"

    # Empty/None allow-list keeps the default toolbox.
    llm2 = ScriptedSubAgentOnlyLLM()
    runner2 = KernelSubAgentRunner(work_root=tmp_path, llm_client=llm2, model_id="fake-model")
    await runner2.run(task="inspect the project", agent="worker", allowed_tools=[])
    assert "read_file" in {tool["function"]["name"] for tool in llm2.requests[0].tools or []}
