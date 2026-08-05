"""Tests for W5 多阶段进度状态 (Multi-Stage Progress Tracking).

Verifies:
1. TaskPlan.progress_summary returns correct counts at each state
2. TaskPlan.advance_step() transitions status correctly
3. TaskPlan.fail_current_step() records failure and moves on
4. progress_pct updates correctly through a full plan lifecycle
5. TaskPlanStep new fields (started_at, completed_at, failure_reason) work
"""

import pytest
from datetime import datetime

from app.core.writer.schemas import TaskPlan, TaskPlanStep


def make_plan(num_steps: int = 3) -> TaskPlan:
    """Helper: create a TaskPlan with N steps, first step in_progress."""
    steps = []
    for i in range(num_steps):
        status = "in_progress" if i == 0 else "pending"
        steps.append(TaskPlanStep(
            step_id=f"step_{i + 1}",
            description=f"Step {i + 1}: do something",
            deliverables=[f"file_{i + 1}.py"],
            acceptance_criteria=[f"Verify step {i + 1} works"],
            status=status,
            started_at=datetime.now() if i == 0 else None,
        ))
    return TaskPlan(
        goal="Test task",
        steps=steps,
        constraints=["no breaking changes"],
        user_confirmed=True,
    )


class TestTaskPlanStep:
    """Test TaskPlanStep model fields."""

    def test_default_status_is_pending(self):
        step = TaskPlanStep(step_id="s1")
        assert step.status == "pending"
        assert step.failure_reason == ""
        assert step.started_at is None
        assert step.completed_at is None

    def test_failure_fields_populated(self):
        now = datetime.now()
        step = TaskPlanStep(
            step_id="s1",
            status="failed",
            failure_reason="build error",
            completed_at=now,
        )
        assert step.status == "failed"
        assert step.failure_reason == "build error"
        assert step.completed_at == now


class TestProgressSummary:
    """Test TaskPlan.progress_summary property."""

    def test_empty_plan_returns_zero_pct(self):
        plan = TaskPlan(goal="empty")
        summary = plan.progress_summary
        assert summary["total_steps"] == 0
        assert summary["completed"] == 0
        assert summary["failed"] == 0
        assert summary["progress_pct"] == 0
        assert summary["current_step"] is None
        assert summary["next_step"] is None
        assert summary["failed_steps"] == []

    def test_all_pending_returns_zero_completed(self):
        plan = TaskPlan(
            goal="pending only",
            steps=[TaskPlanStep(step_id="s1"), TaskPlanStep(step_id="s2")],
        )
        summary = plan.progress_summary
        assert summary["total_steps"] == 2
        assert summary["completed"] == 0
        assert summary["progress_pct"] == 0

    def test_one_of_three_completed(self):
        plan = make_plan(3)
        plan.steps[0].status = "completed"
        plan.steps[0].completed_at = datetime.now()
        summary = plan.progress_summary
        assert summary["total_steps"] == 3
        assert summary["completed"] == 1
        assert summary["progress_pct"] == 33

    def test_all_completed_returns_100_pct(self):
        plan = make_plan(2)
        for step in plan.steps:
            step.status = "completed"
            step.completed_at = datetime.now()
        summary = plan.progress_summary
        assert summary["completed"] == 2
        assert summary["progress_pct"] == 100

    def test_failed_steps_tracked(self):
        plan = make_plan(3)
        plan.steps[0].status = "failed"
        plan.steps[0].failure_reason = "test error"
        plan.steps[1].status = "failed"
        plan.steps[1].failure_reason = "build error"
        summary = plan.progress_summary
        assert summary["failed"] == 2
        assert len(summary["failed_steps"]) == 2
        assert "Step 1" in summary["failed_steps"][0]
        assert "Step 2" in summary["failed_steps"][1]

    def test_current_step_reported(self):
        plan = make_plan(3)
        # Step 1 is in_progress by default from make_plan
        summary = plan.progress_summary
        assert summary["current_step"] == "Step 1: do something"

    def test_next_step_reported(self):
        plan = make_plan(3)
        summary = plan.progress_summary
        assert summary["next_step"] == "Step 2: do something"

    def test_no_next_step_when_all_done(self):
        plan = make_plan(2)
        for step in plan.steps:
            step.status = "completed"
        summary = plan.progress_summary
        assert summary["next_step"] is None


class TestAdvanceStep:
    """Test TaskPlan.advance_step() method."""

    def test_advance_completes_current_and_starts_next(self):
        plan = make_plan(3)
        assert plan.current_step is not None
        assert plan.current_step.step_id == "step_1"
        assert plan.current_step.status == "in_progress"

        new_step = plan.advance_step()

        # Step 1 should now be completed
        assert plan.steps[0].status == "completed"
        assert plan.steps[0].completed_at is not None

        # Step 2 should now be in_progress
        assert plan.steps[1].status == "in_progress"
        assert plan.steps[1].started_at is not None

        # Returns the new current step
        assert new_step is not None
        assert new_step.step_id == "step_2"

    def test_advance_last_step_returns_none(self):
        plan = make_plan(1)
        new_step = plan.advance_step()
        assert new_step is None
        assert plan.steps[0].status == "completed"
        assert plan.current_step is None
        assert plan.next_step is None
    def test_advance_multiple_steps(self):
        plan = make_plan(3)
        plan.advance_step()  # complete 1, start 2
        plan.advance_step()  # complete 2, start 3
        plan.advance_step()  # complete 3, none left

        assert plan.steps[0].status == "completed"
        assert plan.steps[1].status == "completed"
        assert plan.steps[2].status == "completed"
        assert plan.current_step is None
        assert plan.progress_summary["progress_pct"] == 100

    def test_advance_no_current_step_is_noop(self):
        plan = TaskPlan(goal="empty")
        assert plan.current_step is None
        new_step = plan.advance_step()
        assert new_step is None
        # No crash, nothing changed
        assert plan.progress_summary["total_steps"] == 0

    def test_progress_pct_updates_after_advance(self):
        plan = make_plan(3)
        assert plan.progress_summary["progress_pct"] == 0

        plan.advance_step()
        assert plan.progress_summary["progress_pct"] == 33

        plan.advance_step()
        assert plan.progress_summary["progress_pct"] == 67

        plan.advance_step()
        assert plan.progress_summary["progress_pct"] == 100


class TestFailCurrentStep:
    """Test TaskPlan.fail_current_step() method."""

    def test_fail_records_reason_and_completed_at(self):
        plan = make_plan(3)
        assert plan.current_step is not None
        assert plan.current_step.step_id == "step_1"

        failed = plan.fail_current_step(reason="build error")

        assert failed is not None
        assert failed == plan.steps[0]
        assert plan.steps[0].status == "failed"
        assert plan.steps[0].failure_reason == "build error"
        assert plan.steps[0].completed_at is not None

        # The next step should NOT auto-advance on failure
        assert plan.steps[1].status == "pending"

    def test_fail_no_current_is_noop(self):
        plan = TaskPlan(goal="empty")
        failed = plan.fail_current_step()
        assert failed is None

    def test_failed_step_appears_in_summary(self):
        plan = make_plan(3)
        plan.fail_current_step(reason="test error")

        summary = plan.progress_summary
        assert summary["failed"] == 1
        assert summary["failed_steps"] == ["Step 1: do something"]

    def test_mixed_progress_failed_and_completed(self):
        plan = make_plan(4)
        plan.steps[0].status = "failed"
        plan.steps[0].failure_reason = "bad"
        plan.steps[0].completed_at = datetime.now()
        plan.steps[1].status = "completed"
        plan.steps[1].completed_at = datetime.now()
        plan.steps[2].status = "in_progress"
        plan.steps[2].started_at = datetime.now()
        # step 3 is pending

        summary = plan.progress_summary
        assert summary["total_steps"] == 4
        assert summary["completed"] == 1
        assert summary["failed"] == 1
        assert summary["progress_pct"] == 25
        assert summary["current_step"] == "Step 3: do something"
        assert summary["next_step"] == "Step 4: do something"
        assert "Step 1" in summary["failed_steps"][0]


class TestCurrentStepNextStep:
    """Test TaskPlan.current_step and next_step properties."""

    def test_current_step_returns_in_progress(self):
        plan = make_plan(3)
        step = plan.current_step
        assert step is not None
        assert step.status == "in_progress"
        assert step.step_id == "step_1"

    def test_current_step_returns_none_when_none_in_progress(self):
        plan = TaskPlan(goal="all pending", steps=[
            TaskPlanStep(step_id="s1"),
            TaskPlanStep(step_id="s2"),
        ])
        assert plan.current_step is None

    def test_next_step_returns_first_pending(self):
        plan = make_plan(3)
        step = plan.next_step
        assert step is not None
        assert step.status == "pending"
        assert step.step_id == "step_2"

    def test_next_step_skips_completed(self):
        plan = make_plan(3)
        plan.steps[1].status = "completed"
        plan.steps[1].completed_at = datetime.now()
        # next should be step 3 (pending), skipping completed step 2
        step = plan.next_step
        assert step is not None
        assert step.step_id == "step_3"

    def test_next_step_returns_none_when_all_completed(self):
        plan = make_plan(2)
        for step in plan.steps:
            step.status = "completed"
        assert plan.next_step is None
