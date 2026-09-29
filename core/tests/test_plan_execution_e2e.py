"""End-to-end: "开工" on a ready plan puts its goal and steps on the session checklist.

The desktop turns a ready plan package into one ordinary session turn
(``ui/src/app/LamToolsApp.vue`` → ``buildPlanExecutionPrompt``): the turn reads
the package back with ``plan_package``, checks it against the repository, and
installs the goal and checklist following the ``execute-plan`` skill.

Each half already has unit coverage — the package store (``test_plan_packages``),
the plugin tool (``test_plan_plugin``), the checklist tool (``test_default_toolbox``).
This drives the whole path instead: the real operation catalog, the real bundled
plugin, the real toolbox and the real kernel, with a scripted model standing in
for the LLM — the same scaffolding ``test_core_default_agent`` uses.

The contract under test (``ui/src/plans/types.ts``): a plan step is
"field-for-field the session checklist's step shape, so execution installs it
as-is", and the plan is a document — starting it does not rewrite it.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from lamtools_core.app.default_agent import (
    CoreAgentPaths,
    CoreAgentSpec,
    create_core_agent_operations,
)
from lamtools_core.app.durable_operations import register_durable_operations
from lamtools_core.app.plan_operations import register_plan_operations
from lamtools_core.llm import LLMRequest, LLMResponse, LLMStreamEvent, LLMToolCall
from lamtools_core.runtime import InMemoryRuntimeStateStore
from lamtools_core.runtime.arrange import ArrangeManager, InMemoryArrangeStore
from lamtools_core.runtime.goal import GoalManager, InMemoryGoalStore
from lamtools_core.runtime.plan_package import InMemoryPlanStore, PlanManager

# --- The "开工" prompt, copied verbatim from the UI -------------------------
# If these drift from LamToolsApp.vue the guard below fails, so the test cannot
# keep passing against a prompt the product no longer sends.
_VUE_PLAN_PROMPT_FRAGMENTS = (
    "执行方案《${plan.title}》（plan_id: ${plan.plan_id}，${steps} 步）。",
    "先用 plan_package 读回这份方案，对照仓库现状核对需求与步骤，有出入的地方先记下结论并更新方案；",
    "然后按 execute-plan 的流程把目标与步骤装进当前会话的清单，再逐步开工。",
)

_PROMPT_HEAD = "执行方案《{title}》（plan_id: {plan_id}，{steps} 步）。"
_PROMPT_BODY = (
    "先用 plan_package 读回这份方案，对照仓库现状核对需求与步骤，有出入的地方先记下结论并更新方案；"
    "然后按 execute-plan 的流程把目标与步骤装进当前会话的清单，再逐步开工。"
)

_UI_SOURCE = Path(__file__).resolve().parents[1] / "ui" / "src" / "app" / "LamToolsApp.vue"

THREAD_ID = "thread-plan-start"
WORK_FOLDER = "work"


def _ui_plan_start_prompt(plan: dict[str, Any]) -> str:
    """The text the panel hands to the session, built the way the UI builds it."""

    head = _PROMPT_HEAD.format(
        title=plan["title"],
        plan_id=plan["plan_id"],
        steps=len(plan["checklist"]["steps"]),
    )
    return head + _PROMPT_BODY


def _ready_plan_payload() -> dict[str, Any]:
    """A settled plan: a goal with its criteria, and more than one step."""

    return {
        "title": "导出显示进度",
        "summary": "导出长报告时让用户看见进度",
        "status": "ready",
        "requirement": {
            "restatement": "导出长报告时用户看不到进度，只能干等",
            "success_looks_like": "导出过程中能看到百分比，结束后文件完整",
            "non_goals": ["不做取消按钮"],
            "assumptions": ["导出体积在后台可读"],
        },
        "approach": {
            "chosen": "在导出循环里回报进度",
            "why": "改动面最小，不碰导出格式",
            "rejected": [{"option": "重写导出器", "why": "风险高"}],
        },
        "checklist": {
            "design_summary": "导出过程对用户可见",
            "files": ["core/export.py", "core/tests/test_export.py"],
            "steps": [
                {
                    "id": "s1",
                    "description": "导出循环每处理一批就回报一次进度",
                    "deliverables": ["进度回调"],
                    "status": "pending",
                },
                {
                    "id": "s2",
                    "description": "把进度接到界面的进度条上",
                    "deliverables": ["进度条组件"],
                    "status": "pending",
                },
                {
                    "id": "s3",
                    "description": "补一条覆盖进度的回归测试",
                    "deliverables": ["测试通过"],
                    "status": "pending",
                },
            ],
        },
        "goal": {
            "objective": "导出过程对用户可见",
            "completion_criteria": ["导出时能看到百分比", "进度到 100% 后文件完整"],
        },
        "risks": [{"risk": "进度回调拖慢导出", "severity": "low", "mitigation": "节流上报"}],
    }


class _Projects:
    """Just enough project store for the workspace → project lookup."""

    def __init__(self, work_root: Path) -> None:
        self._projects = [SimpleNamespace(id="proj-1", work_root=str(work_root))]

    async def list(self) -> list[Any]:
        return list(self._projects)


class _PlanStartLLM:
    """Scripted model that walks the execute-plan flow for one "开工" turn."""

    def __init__(self, *, plan_id: str) -> None:
        self.plan_id = plan_id
        self.requests: list[LLMRequest] = []
        self.system_prompt = ""
        self.read_back: dict[str, Any] | None = None
        self.installed_checklist: dict[str, Any] | None = None
        self.completions: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """The bound-goal completion check asks the model whether the goal is met."""

        self.completions.append(request)
        return LLMResponse(
            content=json.dumps({"status": "complete", "summary": "清单已装好"}),
            finish_reason="stop",
        )

    async def stream(self, request: LLMRequest):
        self.requests.append(request)
        if len(self.requests) == 1:
            self.system_prompt = str(request.messages[0].content or "")
            tool_names = {tool["function"]["name"] for tool in request.tools or []}
            # The turn must be able to do both half of the flow: read the
            # document and install the run state.
            assert "plan_package" in tool_names, "the plan tool is not offered to the session"
            assert "write_checklist" in tool_names
            assert "goal" in tool_names
            yield LLMStreamEvent(
                kind="done",
                tool_calls=[
                    LLMToolCall(
                        id="call-read-plan",
                        name="plan_package",
                        arguments={"action": "get", "plan_id": self.plan_id},
                    )
                ],
            )
            return

        if len(self.requests) == 2:
            self.read_back = _plan_from_tool_messages(request.messages)
            assert self.read_back is not None, "plan_package returned no plan to read back"
            goal = dict(self.read_back.get("goal") or {})
            checklist = dict(self.read_back.get("checklist") or {})
            # Install exactly what the package says: its goal as the checklist's
            # goal, and its steps as-is — the type contract says they fit.
            self.installed_checklist = {
                "design_summary": str(goal.get("objective") or ""),
                "files": list(checklist.get("files") or []),
                "steps": [dict(step) for step in checklist.get("steps") or []],
            }
            yield LLMStreamEvent(
                kind="done",
                tool_calls=[
                    LLMToolCall(
                        id="call-write-checklist",
                        name="write_checklist",
                        arguments=self.installed_checklist,
                    ),
                    LLMToolCall(
                        id="call-create-goal",
                        name="goal",
                        arguments={
                            "action": "create",
                            "objective": str(goal.get("objective") or ""),
                            "completion_criteria": list(goal.get("completion_criteria") or []),
                        },
                    ),
                ],
            )
            return

        yield LLMStreamEvent(kind="content_delta", content="方案已开工，目标和步骤都进了清单。")
        yield LLMStreamEvent(kind="done")


def _plan_from_tool_messages(messages: list[Any]) -> dict[str, Any] | None:
    """The plan the model saw in the plan_package tool result, parsed back out."""

    for message in reversed(messages):
        if str(getattr(message, "role", "")) != "tool":
            continue
        if str(getattr(message, "name", "")) != "plan_package":
            continue
        text = str(getattr(message, "content", "") or "")
        marker = "content:\n"
        if marker not in text:
            continue
        body = text.split(marker, 1)[1].strip()
        payload, _ = json.JSONDecoder().raw_decode(body)
        plan = payload.get("plan") if isinstance(payload, dict) else None
        return plan if isinstance(plan, dict) else None
    return None


class _Harness:
    """The real desktop wiring for one session, over in-memory stores."""

    def __init__(self, tmp_path: Path, llm: _PlanStartLLM) -> None:
        self.work_root = tmp_path / WORK_FOLDER
        self.work_root.mkdir()
        self.state_store = InMemoryRuntimeStateStore()
        self.plan_manager = PlanManager(InMemoryPlanStore())
        self.goal_manager = GoalManager(InMemoryGoalStore())
        self.catalog = create_core_agent_operations(
            spec=CoreAgentSpec(),
            paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=self.work_root),
            model_provider=llm,
            runtime_state_store=self.state_store,
            goal_manager=self.goal_manager,
        )
        # The host registers these after the catalog, exactly as http_agent_app does.
        register_durable_operations(
            self.catalog,
            goal_manager=self.goal_manager,
            arrange_manager=ArrangeManager(InMemoryArrangeStore()),
        )
        register_plan_operations(
            self.catalog,
            plan_manager=self.plan_manager,
            project_store=_Projects(self.work_root),
        )

    async def save_ready_plan(self) -> dict[str, Any]:
        saved = await self.catalog.execute(
            "plan.save",
            {**_ready_plan_payload(), "work_root": str(self.work_root)},
            metadata={"source": "test"},
        )
        assert saved.status == "ok", saved.payload
        return dict(saved.payload["plan"])

    async def read_plan(self, plan_id: str) -> dict[str, Any]:
        read = await self.catalog.execute("plan.get", {"plan_id": plan_id})
        assert read.status == "ok", read.payload
        return dict(read.payload["plan"])

    async def run_start_turn(self, prompt: str) -> dict[str, Any]:
        result = await self.catalog.execute(
            "turn.start",
            {"thread_id": THREAD_ID, "message": prompt},
        )
        assert result.status == "ok", result.payload
        return dict(result.payload)

    async def checklist(self) -> dict[str, Any]:
        state = await self.state_store.get(THREAD_ID)
        assert state is not None, "the turn left no runtime state"
        plan = state.metadata.get("task_plan")
        assert isinstance(plan, dict) and plan.get("steps"), "the session checklist is empty"
        return plan


def test_the_ui_start_prompt_still_says_what_the_test_drives():
    """Guards both sides: the prompt the test feeds is the prompt the panel sends."""

    source = _UI_SOURCE.read_text(encoding="utf-8")
    for fragment in _VUE_PLAN_PROMPT_FRAGMENTS:
        assert fragment in source, f'the panel no longer sends: {fragment}'
    # The flow the prompt names has to still exist for the prompt to be honest.
    assert "execute-plan" in source
    assert "plan_package" in source


@pytest.mark.asyncio
async def test_starting_a_ready_plan_installs_its_goal_and_steps_and_leaves_it_alone(tmp_path):
    llm = _PlanStartLLM(plan_id="")  # plan_id filled in after the save
    harness = _Harness(tmp_path, llm)
    stored = await harness.save_ready_plan()
    llm.plan_id = stored["plan_id"]

    # A settled plan with no checkpoints and nothing written yet — the scenario
    # the product owner says must be startable.
    assert stored["status"] == "ready"
    assert stored["revision"] == 1
    assert stored["execution"] is None
    assert stored["docs"] == []

    prompt = _ui_plan_start_prompt(stored)
    payload = await harness.run_start_turn(prompt)

    # 1. The prompt really reached the session, and the model could load the flow.
    assert stored["plan_id"] in prompt and stored["title"] in prompt
    assert "- execute-plan:" in llm.system_prompt, "execute-plan is not offered to this session"

    # 2. The package was read back through the tool, unchanged.
    assert llm.read_back is not None
    assert llm.read_back["plan_id"] == stored["plan_id"]
    assert llm.read_back["goal"] == stored["goal"]
    assert llm.read_back["checklist"]["steps"] == stored["checklist"]["steps"]

    # 3. The session checklist now carries the plan's goal and steps, in order.
    checklist = await harness.checklist()
    assert checklist["goal"] == stored["goal"]["objective"]
    installed = checklist["steps"]
    plan_steps = stored["checklist"]["steps"]
    assert len(installed) == len(plan_steps) >= 2
    assert [step["id"] for step in installed] == [step["id"] for step in plan_steps]

    # Field-for-field, as the package types promise: same four fields, same
    # values. Only the status is the run's own — the first step is the one being
    # worked, a plan document is not a run.
    expected_keys = {"id", "description", "deliverables", "status"}
    assert all(set(step) == expected_keys for step in installed)
    assert all(set(step) == expected_keys for step in plan_steps)
    for got, want in zip(installed, plan_steps):
        assert got["id"] == want["id"]
        assert got["description"] == want["description"]
        assert got["deliverables"] == want["deliverables"]
    assert installed[0]["status"] == "in_progress"
    assert [step["status"] for step in installed[1:]] == ["pending"] * (len(installed) - 1)

    # 4. The goal's completion criteria were installed too, as the run's goal.
    goals = await harness.goal_manager.list(thread_id=THREAD_ID)
    assert len(goals) == 1
    assert goals[0].objective == stored["goal"]["objective"]
    assert list(goals[0].completion_criteria) == stored["goal"]["completion_criteria"]

    # 5. What the run renders as the plan part is the same checklist.
    snapshots = [
        event
        for event in payload["events"]
        if event["name"] == "runtime.part"
        and isinstance(event["payload"].get("metadata"), dict)
        and event["payload"]["metadata"].get("checklist_snapshot") is True
    ]
    assert snapshots, "the checklist was never projected for the UI"
    projected = snapshots[-1]["payload"]["metadata"]["task_plan"]
    assert projected["goal"] == checklist["goal"]
    assert [step["id"] for step in projected["steps"]] == [step["id"] for step in installed]

    # 6. Starting is not editing: the plan keeps its status, revision and body.
    plan_after = await harness.read_plan(stored["plan_id"])
    assert plan_after == stored, "starting the plan rewrote the plan document"

    # 7. No checkpoint and no file change were required to get here.
    assert not [path for path in harness.work_root.rglob("*") if path.is_file()]
    tool_results = [item for item in payload["run_items"] if item["kind"] == "tool_result"]
    assert {item["payload"].get("tool_name") for item in tool_results} <= {
        "plan_package",
        "write_checklist",
        "goal",
    }
