from __future__ import annotations

import pytest

from lamtools_core.app import CoreAgentPaths, CoreAgentSpec, create_core_agent_operations
from lamtools_core.llm import LLMRequest, LLMResponse, LLMStreamEvent, LLMToolCall
from lamtools_core.tool.sub_agent_runner import KernelSubAgentRunner


class ScriptedSubAgentOnlyLLM:
    def __init__(self, *, expected_model: str = "fake-model", expected_prompt: str = "") -> None:
        self.requests: list[LLMRequest] = []
        self.expected_model = expected_model
        self.expected_prompt = expected_prompt

    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise AssertionError("Sub-agent runner should use streaming")

    async def stream(self, request: LLMRequest):
        self.requests.append(request)
        assert request.model == self.expected_model
        if self.expected_prompt:
            assert self.expected_prompt in request.messages[0].content
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
                        arguments={"path": "."},
                    )
                ],
            )
            return
        yield LLMStreamEvent(kind="content_delta", content="completed after six tool rounds")
        yield LLMStreamEvent(kind="done")


@pytest.mark.asyncio
async def test_kernel_sub_agent_runner_uses_core_loop_without_recursive_sub_agent(tmp_path):
    llm = ScriptedSubAgentOnlyLLM()
    runner = KernelSubAgentRunner(work_root=tmp_path, llm_client=llm, model_id="fake-model")

    result = await runner.run(task="inspect the project", agent="worker", expected_output="summary")

    assert result == "sub result"
    assert len(llm.requests) == 1
    assert "sub_agent" not in {tool["function"]["name"] for tool in llm.requests[0].tools or []}
    assert "read_file" in {tool["function"]["name"] for tool in llm.requests[0].tools or []}


@pytest.mark.asyncio
async def test_kernel_sub_agent_runner_has_no_fixed_tool_round_limit(tmp_path):
    llm = SixToolRoundSubAgentLLM()
    runner = KernelSubAgentRunner(work_root=tmp_path, llm_client=llm, model_id="fake-model")

    result = await runner.run(task="inspect the project thoroughly", agent="worker")

    assert result == "completed after six tool rounds"
    assert len(llm.requests) == 7


@pytest.mark.asyncio
async def test_kernel_sub_agent_runner_loads_agent_definition_roots(tmp_path):
    agent_root = tmp_path / "agents"
    agent_root.mkdir()
    (agent_root / "reviewer.md").write_text(
        "---\n"
        "name: reviewer\n"
        "description: Review work\n"
        "role: Reviewer\n"
        "model: agent-model\n"
        "tools:\n"
        "  - read_file\n"
        "---\n"
        "Use reviewer instruction.\n",
        encoding="utf-8",
    )
    llm = ScriptedSubAgentOnlyLLM(expected_model="agent-model", expected_prompt="Use reviewer instruction.")
    runner = KernelSubAgentRunner(
        work_root=tmp_path,
        llm_client=llm,
        model_id="base-model",
        agent_roots=[agent_root],
    )

    result = await runner.run(task="inspect the project", agent="reviewer")

    tool_names = {tool["function"]["name"] for tool in llm.requests[0].tools or []}
    assert result == "sub result"
    assert "read_file" in tool_names
    assert "write_file" not in tool_names
    assert "sub_agent" not in tool_names


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
