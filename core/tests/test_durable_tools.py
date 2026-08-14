"""Tests for the model-facing durable (goal / arrange) tools."""

from __future__ import annotations

from typing import Any

import pytest

from lamtools_core.app.operation_catalog import OperationResult
from lamtools_core.tool import ToolCall, ToolResult
from lamtools_core.tool.durable_tools import (
    arrange_requires_approval,
    durable_tool_handlers,
    durable_tool_specs,
)


def _call(name: str, arguments: dict) -> ToolCall:
    return ToolCall(id="call-1", name=name, arguments=arguments)


def _ok_result(payload: dict | None = None) -> OperationResult:
    return OperationResult(name="op", payload=payload or {}, status="ok")


def _executor(calls: list[tuple[str, dict, dict]], payload: dict | None = None):
    """Build an async OperationExecutor that records invocations."""

    async def executor(operation: str, op_payload: dict, meta: dict) -> Any:
        calls.append((operation, op_payload, meta))
        return _ok_result(payload)

    return executor


class TestDurableToolSpecs:
    def test_goal_and_arrange_specs_gated_by_flags(self):
        assert [s.name for s in durable_tool_specs(goal=True, arrange=False)] == ["goal"]
        assert [s.name for s in durable_tool_specs(goal=False, arrange=True)] == ["arrange"]
        assert durable_tool_specs(goal=True, arrange=True)  # both

    def test_arrange_spec_carries_current_utc_hint(self):
        [spec] = durable_tool_specs(goal=False, arrange=True)
        assert "Current UTC time is" in spec.description


class TestGoalTool:
    async def test_create_maps_operation_and_activates_goal(self):
        calls: list[tuple[str, dict, dict]] = []
        handlers = durable_tool_handlers(_executor(calls, {"goal": {"id": "goal-1"}}))
        result = await handlers["goal"](_call("goal", {
            "action": "create",
            "objective": "完成任务",
            "completion_criteria": ["c1", "c2"],
        }))
        assert result.status == "ok"
        assert calls[0][0] == "goal.create"
        assert calls[0][1]["objective"] == "完成任务"
        assert calls[0][1]["completion_criteria"] == ["c1", "c2"]
        assert result.metadata.get("activate_goal_id") == "goal-1"

    async def test_list_get_cancel_map_to_operations(self):
        calls: list[tuple[str, dict, dict]] = []
        handlers = durable_tool_handlers(_executor(calls))
        await handlers["goal"](_call("goal", {"action": "list"}))
        await handlers["goal"](_call("goal", {"action": "get", "goal_id": "g-9"}))
        await handlers["goal"](_call("goal", {"action": "cancel", "goal_id": "g-9"}))

        assert [c[0] for c in calls] == ["goal.list", "goal.get", "goal.update"]
        assert calls[1][1]["goal_id"] == "g-9"
        assert calls[2][1]["status"] == "archived"

    async def test_unknown_action_fails_without_calling_operation(self):
        calls: list[tuple[str, dict, dict]] = []
        handlers = durable_tool_handlers(_executor(calls))
        result = await handlers["goal"](_call("goal", {"action": "explode"}))
        assert result.status == "failed"
        assert "goal action must be create, list, get, or cancel" in result.error
        assert calls == []


class TestArrangeTool:
    async def test_create_builds_trigger_and_payload(self):
        calls: list[tuple[str, dict, dict]] = []
        handlers = durable_tool_handlers(
            _executor(calls, {"job": {"id": "j-1"}}),
            work_root="C:/proj",
        )
        result = await handlers["arrange"](_call("arrange", {
            "action": "create",
            "instruction": "提醒我喝水",
            "schedule_type": "interval",
            "every_seconds": 1800,
            "title": "喝水提醒",
        }))
        assert result.status == "ok"
        assert calls[0][0] == "arrange.create"
        payload = calls[0][1]
        assert payload["work_root"].replace("\\", "/") == "C:/proj"
        assert payload["payload"]["message"] == "提醒我喝水"
        assert payload["trigger"] == {"type": "interval", "every_seconds": 1800}
        assert payload["session_strategy"] == "new"

    async def test_create_with_observer_entry_forces_work_root(self):
        calls: list[tuple[str, dict, dict]] = []
        handlers = durable_tool_handlers(_executor(calls))
        await handlers["arrange"](_call("arrange", {
            "action": "create",
            "instruction": "x",
            "schedule_type": "once",
            "date": "2026-08-14",
            "time": "10:00",
            "observer_entry": "trigger",
        }))
        assert calls[0][1]["observer"] == {"entry": "trigger"}

    async def test_invalid_trigger_fails_fast(self):
        handlers = durable_tool_handlers(_executor([]))
        result = await handlers["arrange"](_call("arrange", {
            "action": "create",
            "instruction": "x",
            "schedule_type": "bogus",
        }))
        assert result.status == "failed"
        assert "schedule_type" in result.error.lower()

    async def test_get_and_pause_map_to_operations(self):
        calls: list[tuple[str, dict, dict]] = []
        handlers = durable_tool_handlers(_executor(calls))
        await handlers["arrange"](_call("arrange", {"action": "get", "job_id": "j-1"}))
        await handlers["arrange"](_call("arrange", {"action": "pause", "job_id": "j-1"}))
        await handlers["arrange"](_call("arrange", {"action": "cancel", "job_id": "j-1"}))
        assert [c[0] for c in calls] == ["arrange.get", "arrange.pause", "arrange.cancel"]

    async def test_unknown_action_fails(self):
        handlers = durable_tool_handlers(_executor([]))
        result = await handlers["arrange"](_call("arrange", {"action": "nope"}))
        assert result.status == "failed"


class TestArrangeApproval:
    def test_write_actions_require_approval(self):
        assert arrange_requires_approval({"action": "create"})
        assert arrange_requires_approval({"action": "pause"})
        assert arrange_requires_approval({"action": "resume"})
        assert arrange_requires_approval({"action": "cancel"})

    def test_read_actions_do_not(self):
        assert not arrange_requires_approval({"action": "list"})
        assert not arrange_requires_approval({"action": "get"})
