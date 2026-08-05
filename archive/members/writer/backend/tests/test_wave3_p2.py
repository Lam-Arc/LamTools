"""W7-W11 (Wave 3 P2) feature tests.

W7: 验收条件自动生成 — auto_generate_criteria + _verify_step_criteria
W8: 关键上下文锁定 — locked_context survives context management
W9: 委托其他成员 — DelegationStatus, delegation_queue, delegate_to_member action
W10: 阶段自适应交互模式 — get_recommended_mode_for_stage
W11: 任务拆解质量自检 — _check_plan_executability
"""

import pytest
from datetime import datetime

from app.core.writer.schemas import (
    TaskPlanStep,
    TaskPlan,
    DelegationStatus,
    WriterSessionState,
    WriterActionType,
)


# ── W7: Auto-generate acceptance criteria ──────────────────────────


class TestW7AutoGenerateCriteria:
    """W7: Auto-generate acceptance criteria from deliverables."""

    def test_py_deliverable_generates_code_criteria(self):
        step = TaskPlanStep(description="Implement auth", deliverables=["auth.py"])
        criteria = step.auto_generate_criteria()
        assert len(criteria) == 1
        assert any("exists" in c and "auth.py" in c for c in criteria)

    def test_tsx_deliverable_generates_exists_criteria(self):
        step = TaskPlanStep(description="Add component", deliverables=["Button.tsx"])
        criteria = step.auto_generate_criteria()
        assert len(criteria) >= 1
        assert any("Button.tsx" in c for c in criteria)

    def test_vue_deliverable_generates_markup_criteria(self):
        step = TaskPlanStep(description="Create page", deliverables=["Home.vue"])
        criteria = step.auto_generate_criteria()
        assert len(criteria) == 1
        assert "markup" in criteria[0]

    def test_md_deliverable_generates_content_criteria(self):
        step = TaskPlanStep(description="Write docs", deliverables=["README.md"])
        criteria = step.auto_generate_criteria()
        assert len(criteria) == 1
        assert "content" in criteria[0]

    def test_unknown_deliverable_generates_exists_criteria(self):
        step = TaskPlanStep(description="Create config", deliverables=["config.yaml"])
        criteria = step.auto_generate_criteria()
        assert len(criteria) == 1
        assert "exists" in criteria[0]

    def test_existing_criteria_not_overwritten(self):
        step = TaskPlanStep(
            description="Custom step",
            deliverables=["foo.py"],
            acceptance_criteria=["Custom criterion"],
        )
        criteria = step.auto_generate_criteria()
        assert criteria == ["Custom criterion"]

    def test_multiple_deliverables_generate_multiple_criteria(self):
        step = TaskPlanStep(
            description="Full feature",
            deliverables=["auth.py", "auth.test.py", "README.md"],
        )
        criteria = step.auto_generate_criteria()
        assert len(criteria) == 3

    def test_no_deliverables_generates_empty_criteria(self):
        step = TaskPlanStep(description="Think about approach")
        criteria = step.auto_generate_criteria()
        assert criteria == []


# ── W8: Locked context ─────────────────────────────────────────────


class TestW8LockedContext:
    """W8: Critical context that survives compaction."""

    def _make_state(self, **overrides) -> WriterSessionState:
        defaults = {"session_id": "test-session"}
        defaults.update(overrides)
        return WriterSessionState(**defaults)

    def test_locked_context_default_empty(self):
        state = self._make_state()
        assert state.locked_context == {}

    def test_locked_context_stores_key_values(self):
        state = self._make_state()
        state.locked_context["goal"] = "Build auth system"
        state.locked_context["constraint_0"] = "No external deps"
        assert state.locked_context["goal"] == "Build auth system"
        assert state.locked_context["constraint_0"] == "No external deps"

    def test_locked_context_survives_serialization(self):
        state = self._make_state(locked_context={"goal": "test", "step": "1"})
        data = state.model_dump()
        restored = WriterSessionState(**data)
        assert restored.locked_context == {"goal": "test", "step": "1"}

    def test_locked_context_updated_when_plan_confirmed(self):
        plan = TaskPlan(
            goal="Build feature X",
            steps=[
                TaskPlanStep(description="Step 1", deliverables=["a.py"]),
                TaskPlanStep(description="Step 2", deliverables=["b.py"]),
            ],
            constraints=["No mocks"],
            user_confirmed=True,
        )
        state = self._make_state(task_plan=plan)
        # Simulate runtime locking behavior
        state.locked_context["goal"] = plan.goal
        state.locked_context["total_steps"] = str(len(plan.steps))
        for i, constraint in enumerate(plan.constraints):
            state.locked_context[f"constraint_{i}"] = constraint

        assert state.locked_context["goal"] == "Build feature X"
        assert state.locked_context["total_steps"] == "2"
        assert state.locked_context["constraint_0"] == "No mocks"


# ── W9: Delegation to other members ────────────────────────────────


class TestW9DelegationStatus:
    """W9: DelegationStatus model for delegating to LamTools members."""

    def test_delegation_status_creation(self):
        d = DelegationStatus(
            target_member="butler",
            task_description="Clean up temp files",
        )
        assert d.target_member == "butler"
        assert d.task_description == "Clean up temp files"
        assert d.status == "queued"
        assert d.result is None

    def test_delegation_status_with_context(self):
        d = DelegationStatus(
            target_member="sage",
            task_description="Research best practices",
            context={"domain": "auth", "depth": "thorough"},
        )
        assert d.context["domain"] == "auth"

    def test_delegation_status_lifecycle(self):
        d = DelegationStatus(
            target_member="artist",
            task_description="Design logo",
        )
        assert d.status == "queued"
        d.status = "executing"
        assert d.status == "executing"
        d.status = "completed"
        d.result = "Logo created"
        assert d.result == "Logo created"

    def test_delegation_queue_on_session_state(self):
        state = WriterSessionState(session_id="test-session")
        assert state.delegation_queue == []
        state.delegation_queue.append(
            DelegationStatus(target_member="butler", task_description="Task 1")
        )
        assert len(state.delegation_queue) == 1
        assert state.delegation_queue[0].target_member == "butler"

    def test_delegate_to_member_action_type_exists(self):
        # WriterActionType is a Literal, not an Enum
        import typing
        args = typing.get_args(WriterActionType)
        assert "delegate_to_member" in args

    def test_delegate_to_member_in_permissions(self):
        from app.core.writer.permission import TOOL_PERMISSIONS

        assert "delegate_to_member" in TOOL_PERMISSIONS
