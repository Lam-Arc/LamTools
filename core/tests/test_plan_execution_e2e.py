"""End-to-end: "开工" on a ready plan puts its goal and steps on the session checklist.

The desktop turns a ready plan document into one ordinary session turn
(``ui/src/app/LamToolsApp.vue`` → ``startPlanFromLibrary``): the turn reads the
plan file back with ``read_file``, checks it against the repository, and
installs the goal and checklist following the ``execute-plan`` skill.

Each half already has unit coverage — the plan library scan (``test_plan_library``),
the checklist tool (``test_default_toolbox``). This drives the whole path
instead: the real operation catalog, the real bundled plugin, the real toolbox
and the real kernel, with a scripted model standing in for the LLM — the same
scaffolding ``test_core_default_agent`` uses.

The contract under test: a plan is a markdown document in the project's 「方案/」
folder, and starting it does not rewrite it.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from lamtools_core.app.default_agent import (
    CoreAgentPaths,
    CoreAgentSpec,
    create_core_agent_operations,
)
from lamtools_core.app.durable_operations import register_durable_operations
from lamtools_core.app.plan_library import plan_library_root
from lamtools_core.llm import LLMRequest, LLMResponse, LLMStreamEvent, LLMToolCall
from lamtools_core.runtime import InMemoryRuntimeStateStore
from lamtools_core.runtime.arrange import ArrangeManager, InMemoryArrangeStore
from lamtools_core.runtime.goal import GoalManager, InMemoryGoalStore

# --- The "开工" prompt, copied verbatim from the UI -------------------------
# If these drift from LamToolsApp.vue the guard below fails, so the test cannot
# keep passing against a prompt the product no longer sends.
_VUE_PLAN_PROMPT_FRAGMENTS = (
    "执行方案《${plan.title}》（${plan.path}）。",
    "先用 read_file 读回这份方案，对照仓库现状核对需求与步骤，有出入的地方先记下结论并更新方案文件；",
    "然后按 execute-plan 的流程把目标与步骤装进当前会话的清单，再逐步开工。",
)

_PROMPT_HEAD = "执行方案《{title}》（{path}）。"
_PROMPT_BODY = (
    "先用 read_file 读回这份方案，对照仓库现状核对需求与步骤，有出入的地方先记下结论并更新方案文件；"
    "然后按 execute-plan 的流程把目标与步骤装进当前会话的清单，再逐步开工。"
)

_UI_SOURCE = Path(__file__).resolve().parents[1] / "ui" / "src" / "app" / "LamToolsApp.vue"

THREAD_ID = "thread-plan-start"
WORK_FOLDER = "work"
PLAN_RELATIVE = "方案/导出显示进度.md"

# The plan document the library shows and the turn executes — one markdown file.
_PLAN_DOCUMENT = """---
状态: 就绪
摘要: 导出长报告时让用户看见进度
---

# 导出显示进度

## 需求与边界

- 复述：导出长报告时用户看不到进度，只能干等。
- 完成后能看到：导出过程中能看到百分比，结束后文件完整。
- 这次不做：
  - 不做取消按钮。
- 假设：
  - 导出体积在后台可读。

## 取舍

- 选定：在导出循环里回报进度，因为改动面最小，不碰导出格式。
- 被否：重写导出器 — 风险高。

## 步骤

1. 导出循环每处理一批就回报一次进度 — 验证：进度回调有单元测试且通过。
2. 把进度接到界面的进度条上 — 验证：界面组件渲染断言通过。
3. 补一条覆盖进度的回归测试 — 验证：新增测试通过。

## 目标与完成判据

- 目标：导出过程对用户可见。
- 判据：
  - 导出时能看到百分比
  - 进度到 100% 后文件完整

## 风险

- 进度回调拖慢导出 — 低 — 节流上报。

## 未答问题

"""


def _ui_plan_start_prompt(plan: dict[str, Any]) -> str:
    """The text the library hands to the session, built the way the UI builds it."""

    head = _PROMPT_HEAD.format(title=plan["title"], path=plan["path"])
    return head + _PROMPT_BODY


def _write_ready_plan(work_root: Path) -> Path:
    folder = plan_library_root(work_root)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "导出显示进度.md"
    path.write_text(_PLAN_DOCUMENT, encoding="utf-8", newline="\n")
    return path


class _Projects:
    """Just enough project store for the workspace → project lookup."""

    def __init__(self, work_root: Path) -> None:
        self._projects = [SimpleNamespace(id="proj-1", work_root=str(work_root))]

    async def list(self) -> list[Any]:
        return list(self._projects)


class _PlanStartLLM:
    """Scripted model that walks the execute-plan flow for one "开工" turn."""

    def __init__(self, *, plan_relative: str) -> None:
        self.plan_relative = plan_relative
        self.requests: list[LLMRequest] = []
        self.system_prompt = ""
        self.plan_content_seen: str | None = None
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
            # The turn must be able to do both halves of the flow: read the
            # plan document and install the run state.
            assert "read_file" in tool_names, "the file tools are not offered to the session"
            assert "write_checklist" in tool_names
            assert "goal" in tool_names
            yield LLMStreamEvent(
                kind="done",
                tool_calls=[
                    LLMToolCall(
                        id="call-read-plan",
                        name="read_file",
                        arguments={"path": self.plan_relative},
                    )
                ],
            )
            return

        if len(self.requests) == 2:
            self.plan_content_seen = _plan_content_from_tool_messages(request.messages)
            assert self.plan_content_seen is not None, "read_file returned no plan to read back"
            # Install exactly what the document says: the goal from 目标与完成判据
            # and the ordered steps from 步骤 — the document is the source.
            self.installed_checklist = {
                "design_summary": "导出过程对用户可见",
                "files": [],
                "steps": [
                    {
                        "id": "s1",
                        "description": "导出循环每处理一批就回报一次进度",
                        "deliverables": ["进度回调有单元测试且通过"],
                        "status": "pending",
                    },
                    {
                        "id": "s2",
                        "description": "把进度接到界面的进度条上",
                        "deliverables": ["界面组件渲染断言通过"],
                        "status": "pending",
                    },
                    {
                        "id": "s3",
                        "description": "补一条覆盖进度的回归测试",
                        "deliverables": ["新增测试通过"],
                        "status": "pending",
                    },
                ],
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
                            "objective": "导出过程对用户可见",
                            "completion_criteria": [
                                "导出时能看到百分比",
                                "进度到 100% 后文件完整",
                            ],
                        },
                    ),
                ],
            )
            return

        yield LLMStreamEvent(kind="content_delta", content="方案已开工，目标和步骤都进了清单。")
        yield LLMStreamEvent(kind="done")


def _plan_content_from_tool_messages(messages: list[Any]) -> str | None:
    """The plan document the model saw in the read_file tool result, parsed back out."""

    for message in reversed(messages):
        if str(getattr(message, "role", "")) != "tool":
            continue
        if str(getattr(message, "name", "")) != "read_file":
            continue
        text = str(getattr(message, "content", "") or "")
        marker = "content:"
        if marker not in text:
            continue
        return text.split(marker, 1)[1].strip()
    return None


class _Harness:
    """The real desktop wiring for one session, over in-memory stores."""

    def __init__(self, tmp_path: Path, llm: _PlanStartLLM) -> None:
        self.work_root = tmp_path / WORK_FOLDER
        self.work_root.mkdir()
        self.state_store = InMemoryRuntimeStateStore()
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

    def write_ready_plan(self) -> Path:
        return _write_ready_plan(self.work_root)

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
    assert "read_file" in source


async def test_starting_a_ready_plan_installs_its_goal_and_steps_and_leaves_it_alone(tmp_path):
    llm = _PlanStartLLM(plan_relative=PLAN_RELATIVE)
    harness = _Harness(tmp_path, llm)
    plan_path = harness.write_ready_plan()
    document_before = plan_path.read_text(encoding="utf-8")

    prompt = _ui_plan_start_prompt({"title": "导出显示进度", "path": PLAN_RELATIVE})
    payload = await harness.run_start_turn(prompt)

    # 1. The prompt really reached the session, and the model could load the flow.
    assert "导出显示进度" in prompt and PLAN_RELATIVE in prompt
    assert "- execute-plan:" in llm.system_prompt, "execute-plan is not offered to this session"

    # 2. The plan document was read back through the file tool, content intact
    # (the tool appends its own metadata suffix after the document's bytes).
    assert llm.plan_content_seen is not None
    assert llm.plan_content_seen.startswith(document_before)

    # 3. The session checklist now carries the plan's goal and steps, in order.
    checklist = await harness.checklist()
    assert checklist["goal"] == "导出过程对用户可见"
    installed = checklist["steps"]
    assert len(installed) == 3
    assert [step["id"] for step in installed] == ["s1", "s2", "s3"]
    assert all(step["description"] for step in installed)
    # Field-for-field the run's own shape: the first step is the one being
    # worked, the rest wait — a plan document is not a run.
    expected_keys = {"id", "description", "deliverables", "status"}
    assert all(set(step) == expected_keys for step in installed)
    assert installed[0]["status"] == "in_progress"
    assert [step["status"] for step in installed[1:]] == ["pending", "pending"]

    # 4. The goal's completion criteria were installed too, as the run's goal.
    goals = await harness.goal_manager.list(thread_id=THREAD_ID)
    assert len(goals) == 1
    assert goals[0].objective == "导出过程对用户可见"
    assert list(goals[0].completion_criteria) == ["导出时能看到百分比", "进度到 100% 后文件完整"]

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

    # 6. Starting is not editing: the plan file keeps its bytes.
    assert plan_path.read_text(encoding="utf-8") == document_before, "starting the plan rewrote the plan document"

    # 7. No file change was required to get here — only reads and run state.
    tool_results = [item for item in payload["run_items"] if item["kind"] == "tool_result"]
    assert {item["payload"].get("tool_name") for item in tool_results} <= {
        "read_file",
        "write_checklist",
        "goal",
    }
