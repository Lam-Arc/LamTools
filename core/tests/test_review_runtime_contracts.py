"""user:“该修修”+(先证明后台恢复、退出与预算契约)。"""
import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def duty_module():
    path = Path(__file__).resolve().parents[2] / "plugins/bili-scroll/backend/__init__.py"
    spec = importlib.util.spec_from_file_location("review_duty", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_stop_waits_for_duty_cleanup():
    module = duty_module()
    cleaned = []
    async def work():
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0)
            cleaned.append(True)
    runtime = module.DutyRuntime(None)
    runtime._current = asyncio.create_task(work())
    await asyncio.sleep(0)
    await runtime.stop()
    assert runtime._current.done() and cleaned == [True]
    assert runtime.trigger_now()["started"] is False


@pytest.mark.asyncio
async def test_failed_round_can_retry_and_success_is_persisted(tmp_path, monkeypatch):
    module = duty_module()
    monkeypatch.setattr(module, "_SCHEDULE_PATH", tmp_path / "schedule.json")
    class Runner:
        async def run(self, **kwargs):
            return SimpleNamespace(status="failed", error="model unavailable")
    context = SimpleNamespace(service=lambda name: (lambda: Runner()))
    runtime = module.DutyRuntime(context)
    runtime.state = "ready"
    runtime._profile_spec = lambda: SimpleNamespace(full_name="bili-scroll:duty")
    runtime.trigger_now(window="noon", window_date="2026-10-25")
    await runtime._current
    assert runtime._schedule().get("noon") != "2026-10-25"
    assert runtime.last_run["status"] == "failed"
    async def success(**kwargs):
        return SimpleNamespace(status="done", error="")
    Runner.run = staticmethod(success)
    runtime.trigger_now(window="noon", window_date="2026-10-25")
    await runtime._current
    assert runtime._schedule()["noon"] == "2026-10-25"


def test_night_window_keeps_one_identity_across_midnight():
    from datetime import datetime
    module = duty_module()
    assert module._window_date(datetime(2026, 10, 25, 20), "night") == "2026-10-25"
    assert module._window_date(datetime(2026, 10, 26, 7), "night") == "2026-10-25"


def test_model_usage_exhausts_run_budget_without_any_tool_calls():
    from lamtools_core.plugin_system.profiles import RunBudget, ProfileBudget, BudgetExhausted
    from lamtools_core.llm import LLMUsage
    budget = RunBudget(ProfileBudget(max_tokens=5))
    with pytest.raises(BudgetExhausted):
        budget.record_model_usage(LLMUsage(prompt_tokens=4, completion_tokens=2))


@pytest.mark.asyncio
async def test_tool_budget_raises_to_stop_kernel():
    from lamtools_core.plugin_system.profiles import ProfileBudget, ProfileSpec, apply_profile, BudgetExhausted
    async def execute(call, context=None):
        return SimpleNamespace(usage=None)
    toolbox = SimpleNamespace(execute=execute)
    apply_profile(toolbox, ProfileSpec("test:duty", "test", "duty", tools=("read_file",), budget=ProfileBudget(max_tool_calls=1)))
    call = SimpleNamespace(id="x", name="read_file")
    await toolbox.execute(call)
    with pytest.raises(BudgetExhausted):
        await toolbox.execute(call)


@pytest.mark.asyncio
async def test_kernel_stops_on_model_budget_with_no_tools(tmp_path):
    from lamtools_core.tool.sub_agent_runner import KernelSubAgentRunner
    from lamtools_core.plugin_system.profiles import ProfileSpec, ProfileBudget
    from lamtools_core.llm import LLMStreamEvent, LLMUsage
    class Model:
        calls = 0
        async def stream(self, request):
            self.calls += 1
            yield LLMStreamEvent(kind="usage", usage=LLMUsage(prompt_tokens=4, completion_tokens=2))
            yield LLMStreamEvent(kind="content_delta", content="done")
            yield LLMStreamEvent(kind="done")
    model = Model()
    runner = KernelSubAgentRunner(work_root=tmp_path, llm_client=model, model_id="test-model")
    result = await runner.run(task="test", profile_spec=ProfileSpec("test:duty", "test", "duty", tools=("read_file",), budget=ProfileBudget(max_tokens=5)))
    assert result.decision == "failed"
    assert "预算" in result.error
    assert model.calls == 1


@pytest.mark.asyncio
async def test_kernel_does_not_turn_tool_budget_exhaustion_into_retryable_tool_error(tmp_path, instant_model_retry_sleep):
    from lamtools_core.tool.sub_agent_runner import KernelSubAgentRunner
    from lamtools_core.plugin_system.profiles import ProfileSpec, ProfileBudget
    from lamtools_core.llm import LLMStreamEvent, LLMToolCall
    (tmp_path / "read.txt").write_text("content", encoding="utf8")
    class Model:
        calls = 0
        async def stream(self, request):
            self.calls += 1
            if self.calls > 2:
                raise RuntimeError("budget did not stop the model")
            yield LLMStreamEvent(kind="done", tool_calls=[LLMToolCall(id=str(self.calls), name="read_file", arguments={"path": "read.txt"})])
    model = Model()
    runner = KernelSubAgentRunner(work_root=tmp_path, llm_client=model, model_id="test-model")
    result = await runner.run(task="read", profile_spec=ProfileSpec("test:duty", "test", "duty", tools=("read_file",), budget=ProfileBudget(max_tool_calls=1)))
    assert result.decision == "failed" and "预算" in result.error
    assert model.calls == 2


@pytest.mark.asyncio
async def test_terminal_budget_waits_for_parallel_tool_cleanup():
    from lamtools_core.kernel.loop import CoreLoopKernel
    from lamtools_core.plugin_system.profiles import BudgetExhausted
    from lamtools_core.tool import ToolCall
    started = asyncio.Event()
    cleaned = []
    async def execute(state, call, **kwargs):
        if call.id == "slow":
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)
                cleaned.append(True)
        else:
            await started.wait()
            raise BudgetExhausted("stop")
    kernel = SimpleNamespace(policy=SimpleNamespace(max_concurrent_tools=None), _execute_tool=execute)
    with pytest.raises(BudgetExhausted):
        await CoreLoopKernel._execute_tools_parallel(kernel, None, [ToolCall(id="slow", name="read"), ToolCall(id="budget", name="read")])
    assert cleaned == [True]
