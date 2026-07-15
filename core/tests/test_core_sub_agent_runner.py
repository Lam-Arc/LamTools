from __future__ import annotations

import pytest

from lamtools_core.app import CoreAgentPaths, CoreAgentSpec, create_core_agent_operations
from lamtools_core.llm import LLMRequest, LLMResponse, LLMStreamEvent, LLMToolCall
from lamtools_core.runtime import InMemoryRuntimeStateStore
from lamtools_core.tool.sub_agent_runner import KernelSubAgentRunner


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
        assert request.messages[-1].role == "user"
        assert request.messages[-1].content == "inspect the project"
        yield LLMStreamEvent(kind="content_delta", content="sub result")
        yield LLMStreamEvent(kind="done")


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
                        arguments={"task": "inspect the project", "agent": "worker"},
                    )
                ],
            )
            return
        if len(self.requests) == 2:
            assert "sub_agent" not in tool_names
            yield LLMStreamEvent(kind="content_delta", content="sub result")
            yield LLMStreamEvent(kind="done")
            return
        yield LLMStreamEvent(kind="content_delta", content="main saw sub result")
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
                        arguments={"task": "inspect the project", "agent": "worker"},
                    )
                ],
            )
            return
        if len(self.requests) == 2:
            yield LLMStreamEvent(kind="done")
            return
        tool_messages = [message for message in request.messages if message.role == "tool"]
        assert tool_messages
        assert "failed" in tool_messages[-1].content.lower()
        if len(self.requests) == 3:
            yield LLMStreamEvent(
                kind="content_delta",
                content=(
                    "[根因] 子 Agent 返回空结果 [证据] 工具状态为 failed "
                    "[方案1] 主 Agent 接管 [方案2] 重新委派 [选择] 方案1 "
                    "[验证信号] 主 Agent 给出有效答复"
                ),
            )
            yield LLMStreamEvent(kind="done")
            return
        yield LLMStreamEvent(kind="content_delta", content="main handled sub-agent failure")
        yield LLMStreamEvent(kind="done")


class WritingSubAgentLLM:
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
                        id="call-writing-sub",
                        name="sub_agent",
                        arguments={"task": "write a story to story.txt", "agent": "writer"},
                    )
                ],
            )
            return
        if len(self.requests) == 2:
            assert "sub_agent" not in {tool["function"]["name"] for tool in request.tools or []}
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
        if len(self.requests) == 3:
            assert request.messages[-1].role == "tool"
            yield LLMStreamEvent(
                kind="content_delta",
                content="I wrote story.txt with the requested story.",
            )
            yield LLMStreamEvent(kind="done")
            return
        tool_messages = [message for message in request.messages if message.role == "tool"]
        assert tool_messages
        assert "I wrote story.txt" in tool_messages[-1].content
        yield LLMStreamEvent(
            kind="content_delta",
            content="The sub-agent wrote story.txt and confirmed completion.",
        )
        yield LLMStreamEvent(kind="done")


class ApprovalSubAgentLLM:
    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []
        self.child_started = False

    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise AssertionError("Core operation should use streaming")

    async def stream(self, request: LLMRequest):
        self.requests.append(request)
        tool_names = {tool["function"]["name"] for tool in request.tools or []}
        if len(self.requests) == 1:
            yield LLMStreamEvent(kind="done", tool_calls=[
                LLMToolCall(
                    id="call-approval-sub",
                    name="sub_agent",
                    arguments={"task": "write approved.txt", "agent": "writer"},
                )
            ])
            return
        if "sub_agent" not in tool_names and not self.child_started:
            self.child_started = True
            yield LLMStreamEvent(kind="done", tool_calls=[
                LLMToolCall(
                    id="call-child-write",
                    name="write_file",
                    arguments={"path": "approved.txt", "content": "approved child content"},
                )
            ])
            return
        if "sub_agent" not in tool_names:
            yield LLMStreamEvent(kind="content_delta", content="Child saved approved.txt.")
            yield LLMStreamEvent(kind="done")
            return
        yield LLMStreamEvent(kind="content_delta", content="Main received the approved child result.")
        yield LLMStreamEvent(kind="done")


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
async def test_core_agent_operation_executes_default_sub_agent_runner(tmp_path):
    llm = ScriptedMainAndSubAgentLLM()
    catalog = create_core_agent_operations(
        spec=CoreAgentSpec(default_model="fake-model"),
        paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=tmp_path / "work"),
        model_provider=llm,
    )

    result = await catalog.execute("turn.start", {"thread_id": "thread-sub", "message": "delegate"})

    tool_results = [item for item in result.payload["run_items"] if item["kind"] == "tool_result"]
    assert result.status == "ok"
    assert result.payload["message"] == "main saw sub result"
    assert len(llm.requests) == 3
    assert tool_results
    assert "sub result" in tool_results[0]["payload"]["tool_result"]


@pytest.mark.asyncio
async def test_core_agent_operation_reports_empty_sub_agent_result_as_failed(tmp_path):
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
    assert result.payload["message"] == "main handled sub-agent failure"
    assert len(sub_agent_results) == 1
    assert sub_agent_results[0]["status"] == "failed"
    assert sub_agent_results[0]["payload"]["error"]


@pytest.mark.asyncio
async def test_core_agent_operation_forwards_sub_agent_file_tool_and_handoff(tmp_path):
    llm = WritingSubAgentLLM()
    work_root = tmp_path / "work"
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

    write_results = [
        item
        for item in result.payload["run_items"]
        if item["kind"] == "tool_result" and item["payload"].get("tool_name") == "write_file"
    ]
    sub_agent_results = [
        item
        for item in result.payload["run_items"]
        if item["kind"] == "tool_result" and item["payload"].get("tool_name") == "sub_agent"
    ]
    sub_agent_calls = [
        item
        for item in result.payload["run_items"]
        if item["kind"] == "tool_call" and item["payload"].get("tool_name") == "sub_agent"
    ]
    child_reasoning = [
        item
        for item in result.payload["run_items"]
        if item["kind"] == "thinking" and item.get("source") == "sub_agent"
    ]
    child_text = [
        item
        for item in result.payload["run_items"]
        if item["kind"] == "message" and item.get("source") == "sub_agent"
    ]
    assert (work_root / "story.txt").read_text(encoding="utf-8") == "A complete delegated story."
    assert result.payload["message"] == "The sub-agent wrote story.txt and confirmed completion."
    assert len(write_results) == 1
    parent_item_ids = {item["item_id"] for item in sub_agent_calls}
    assert len(parent_item_ids) == 1
    parent_item_id = parent_item_ids.pop()
    assert write_results[0]["source"] == "sub_agent"
    assert write_results[0]["turn_id"] == result.payload["turn_id"]
    assert write_results[0]["parent_item_id"] == parent_item_id
    assert write_results[0]["metadata"]["sub_agent"]["agent"] == "writer"
    assert child_reasoning
    assert child_reasoning[0]["parent_item_id"] == parent_item_id
    assert child_reasoning[0]["metadata"]["sub_agent"]["run_id"]
    assert any("Preparing the story file." in item["payload"].get("content", "") for item in child_text)
    assert any("I wrote story.txt" in item["payload"].get("content", "") for item in child_text)
    assert all(item["parent_item_id"] == parent_item_id for item in child_text)
    assert len(sub_agent_results) == 1
    assert sub_agent_results[0]["payload"]["metadata"]["ended_with_final_response"] is True


@pytest.mark.asyncio
async def test_core_agent_operation_resumes_sub_agent_after_child_tool_approval(tmp_path):
    llm = ApprovalSubAgentLLM()
    work_root = tmp_path / "work"
    catalog = create_core_agent_operations(
        spec=CoreAgentSpec(default_model="fake-model"),
        paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=work_root),
        model_provider=llm,
    )

    started = await catalog.execute(
        "turn.start",
        {
            "thread_id": "thread-child-approval",
            "message": "delegate with approval",
            "approval_policy": "require",
        },
    )

    assert started.payload["decision"] == "wait"
    assert not (work_root / "approved.txt").exists()
    child_approvals = [
        item
        for item in started.payload["run_items"]
        if item["kind"] == "approval_request" and item["payload"].get("request_id") == "call-child-write"
    ]
    assert len(child_approvals) == 1
    assert child_approvals[0]["source"] == "sub_agent"
    delegated_waits = [
        item
        for item in started.payload["run_items"]
        if item["kind"] == "tool_result" and item["payload"].get("tool_name") == "sub_agent"
    ]
    assert len(delegated_waits) == 1
    assert delegated_waits[0]["status"] == "waiting"

    resumed = await catalog.execute(
        "approval.respond",
        {
            "thread_id": "thread-child-approval",
            "request_id": "call-child-write",
            "decision": "approve_once",
        },
    )

    assert resumed.status == "ok"
    assert resumed.payload["decision"] == "done"
    assert resumed.payload["message"] == "Main received the approved child result."
    assert (work_root / "approved.txt").read_text(encoding="utf-8") == "approved child content"
    handoffs = [
        item
        for item in resumed.payload["run_items"]
        if item["kind"] == "tool_result" and item["payload"].get("tool_name") == "sub_agent"
    ]
    assert len(handoffs) == 1
    assert handoffs[0]["payload"]["metadata"]["ended_with_final_response"] is True
    assert handoffs[0]["payload"]["metadata"]["tool_call_count"] == 1
    assert len(llm.requests) == 4
