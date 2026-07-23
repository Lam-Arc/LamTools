"""Model-facing Goal and Arrange tools backed by the shared operation catalog."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from lamtools_core.tool import ToolCall, ToolResult, ToolSpec
from lamtools_core.tool.permission import ASK_USER, AUTO_ALLOW


OperationExecutor = Callable[[str, dict[str, Any], dict[str, Any]], Awaitable[Any]]


def durable_tool_specs(*, goal: bool, arrange: bool) -> list[ToolSpec]:
    specs: list[ToolSpec] = []
    if goal:
        specs.append(ToolSpec(
            name="goal",
            description=(
                "Create, inspect, list, or cancel an explicit Goal. Creating a Goal immediately binds it "
                "to the current run, so the agent must continue until it is complete or genuinely blocked. "
                "Use create only when the user explicitly asks to set or track a Goal; an Arrange task does not "
                "need a Goal."
            ),
            input_schema=_schema({
                "action": {"type": "string", "enum": ["create", "list", "get", "cancel"]},
                "objective": {"type": "string", "description": "Goal objective for create"},
                "completion_criteria": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Observable completion criteria",
                },
                "goal_id": {"type": "string", "description": "Goal id for get or cancel"},
            }, required=["action"]),
            permission=AUTO_ALLOW,
            metadata={"category": "control"},
        ))
    if arrange:
        current_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")
        specs.append(ToolSpec(
            name="arrange",
            description=(
                "Create or manage a durable arranged task that remains visible and manageable inside LamTools. "
                "Use it directly for reminders, schedules, recurring work, and event-triggered work. "
                "work_root is required — ask the user if you don't know it. "
                "Creation, pause, resume, and cancellation require user confirmation; list and get are read-only."
                f" Current UTC time is {current_utc}. Convert relative dates before calling the tool."
            ),
            input_schema=_schema({
                "action": {
                    "type": "string",
                    "enum": ["create", "list", "get", "pause", "resume", "cancel"],
                },
                "work_root": {"type": "string", "description": "Project work_root (absolute path) this arrangement belongs to (required)"},
                "instruction": {"type": "string", "description": "Instruction sent when the task runs"},
                "title": {"type": "string", "description": "Short display title (auto-generated from instruction if omitted)"},
                "session_strategy": {
                    "type": "string",
                    "enum": ["fixed", "new"],
                    "description": "fixed = reuse the current session, new = create a fresh session each run (default: new)",
                },
                "model_id": {"type": "string", "description": "Model in provider/model format (e.g. xunfei/deepseek-v4) for new sessions"},
                "kind": {"type": "string", "enum": ["focus", "routine"]},
                "schedule_type": {
                    "type": "string",
                    "enum": ["once", "daily", "monthly", "interval", "event"],
                },
                "date": {"type": "string", "description": "Local date for a one-time run, YYYY-MM-DD"},
                "timezone": {"type": "string", "description": "IANA timezone, for example Asia/Shanghai"},
                "time": {"type": "string", "description": "Local wall-clock time in HH:MM format"},
                "day": {"type": "integer", "minimum": 1, "maximum": 31},
                "every_seconds": {"type": "number", "exclusiveMinimum": 0},
                "event_type": {"type": "string", "description": "Generic event type for event-triggered work"},
                "observer_entry": {
                    "type": "string",
                    "description": (
                        "Relative path to an approved Python observer created under the workspace. "
                        "Use only with an event schedule after loading the observe-events skill."
                    ),
                },
                "max_runs": {"type": "integer", "minimum": 1},
                "job_id": {"type": "string", "description": "Arrange job id for get or management"},
            }, required=["action"]),
            permission=ASK_USER,
            metadata={"category": "control", "read_actions": ["list", "get"]},
        ))
    return specs


def durable_tool_handlers(
    execute_operation: OperationExecutor,
    *,
    work_root: str | Path | None = None,
) -> dict[str, Callable[[ToolCall], Awaitable[ToolResult]]]:
    async def goal(call: ToolCall) -> ToolResult:
        args = _args(call)
        action = str(args.get("action") or "").strip().lower()
        session_id = _session_id(call)
        if action == "create":
            operation = "goal.create"
            payload = {
                "thread_id": session_id,
                "objective": str(args.get("objective") or "").strip(),
                "completion_criteria": list(args.get("completion_criteria") or []),
            }
        elif action == "list":
            operation = "goal.list"
            payload = {"thread_id": session_id}
        elif action == "get":
            operation = "goal.get"
            payload = {"goal_id": str(args.get("goal_id") or "").strip()}
        elif action == "cancel":
            operation = "goal.update"
            payload = {
                "goal_id": str(args.get("goal_id") or "").strip(),
                "status": "archived",
                "status_reason": "cancelled by agent request",
            }
        else:
            return _failed(call, "goal action must be create, list, get, or cancel")
        result = await execute_operation(operation, payload, _operation_metadata(call))
        tool_result = _from_operation(call, result)
        if tool_result.status == "ok" and action == "create":
            goal_payload = tool_result.metadata.get("operation_payload", {}).get("goal", {})
            goal_id = str(goal_payload.get("id") or "") if isinstance(goal_payload, dict) else ""
            if goal_id:
                tool_result.metadata["activate_goal_id"] = goal_id
        return tool_result

    async def arrange(call: ToolCall) -> ToolResult:
        args = _args(call)
        action = str(args.get("action") or "").strip().lower()
        session_id = _session_id(call)
        if action == "create":
            try:
                trigger = _arrange_trigger(args)
            except ValueError as exc:
                return _failed(call, str(exc))
            operation = "arrange.create"
            strategy = str(args.get("session_strategy") or "").strip()
            if strategy not in {"fixed", "new"}:
                strategy = "new"
            payload = {
                "thread_id": session_id,
                "work_root": str(args.get("project_id") or args.get("work_root") or "").strip(),
                "kind": str(args.get("kind") or "routine").strip(),
                "operation": "turn.start",
                "payload": {"message": str(args.get("instruction") or "").strip()},
                "trigger": trigger,
                "title": str(args.get("title") or "").strip(),
                "session_strategy": strategy,
                "model_id": str(args.get("model_id") or "").strip(),
            }
            observer_entry = str(args.get("observer_entry") or "").strip()
            if observer_entry:
                payload["observer"] = {"entry": observer_entry}
                payload["work_root"] = str(Path(work_root).resolve()) if work_root else ""
            if args.get("max_runs") is not None:
                payload["max_runs"] = args["max_runs"]
        elif action == "list":
            operation = "arrange.list"
            payload = {"thread_id": session_id}
        elif action == "get":
            operation = "arrange.get"
            payload = {"job_id": str(args.get("job_id") or "").strip()}
        elif action in {"pause", "resume", "cancel"}:
            operation = f"arrange.{action}"
            payload = {"job_id": str(args.get("job_id") or "").strip()}
        else:
            return _failed(call, "arrange action must be create, list, get, pause, resume, or cancel")
        return _from_operation(
            call,
            await execute_operation(operation, payload, _operation_metadata(call)),
        )

    return {"goal": goal, "arrange": arrange}


def arrange_requires_approval(args: dict[str, Any]) -> bool:
    return str(args.get("action") or "").strip().lower() not in {"list", "get"}


def _arrange_trigger(args: dict[str, Any]) -> dict[str, Any]:
    schedule_type = str(args.get("schedule_type") or "").strip().lower()
    if schedule_type == "once":
        date_value = str(args.get("date") or "").strip()
        if not date_value:
            raise ValueError("date is required for a one-time schedule")
        return {
            "type": "once",
            "date": date_value,
            "time": str(args.get("time") or "09:00").strip(),
            "timezone": str(args.get("timezone") or "Asia/Shanghai").strip(),
        }
    if schedule_type in {"daily", "monthly"}:
        trigger = {
            "type": "calendar",
            "frequency": schedule_type,
            "timezone": str(args.get("timezone") or "Asia/Shanghai").strip(),
            "time": str(args.get("time") or "09:00").strip(),
        }
        if schedule_type == "monthly":
            trigger["day"] = args.get("day")
        return trigger
    if schedule_type == "interval":
        return {"type": "interval", "every_seconds": args.get("every_seconds")}
    if schedule_type == "event":
        return {"type": "event", "event_type": str(args.get("event_type") or "").strip()}
    raise ValueError("schedule_type must be once, daily, monthly, interval, or event")


def _from_operation(call: ToolCall, result: Any) -> ToolResult:
    status = str(getattr(result, "status", "error") or "error")
    payload = deepcopy(getattr(result, "payload", {}) or {})
    if status != "ok":
        return _failed(call, str(payload.get("error") or "operation failed"), payload=payload)
    return ToolResult(
        call_id=call.id,
        name=call.name,
        status="ok",
        content=json.dumps(payload, ensure_ascii=False, default=str),
        metadata={"operation_payload": payload},
    )


def _failed(call: ToolCall, error: str, *, payload: dict[str, Any] | None = None) -> ToolResult:
    return ToolResult(
        call_id=call.id,
        name=call.name,
        status="failed",
        error=error,
        content=error,
        metadata={"operation_payload": payload or {}},
    )


def _args(call: ToolCall) -> dict[str, Any]:
    return call.arguments if isinstance(call.arguments, dict) else {}


def _session_id(call: ToolCall) -> str:
    return str(call.metadata.get("_runtime_session_id") or "").strip()


def _operation_metadata(call: ToolCall) -> dict[str, Any]:
    return {
        "source": "agent_tool",
        "run_id": str(call.metadata.get("_runtime_run_id") or ""),
        "tool_call_id": call.id,
    }


def _schema(properties: dict[str, Any], *, required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": required,
    }


__all__ = [
    "OperationExecutor",
    "arrange_requires_approval",
    "durable_tool_handlers",
    "durable_tool_specs",
]
