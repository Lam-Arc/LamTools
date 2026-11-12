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


# user:“如果这个 Agent 遇到什么极重大的问题必须停下来，那就标记成阻塞”
# +(模型侧三种收口动作都收敛到 goal.update 的两个状态上)。
_GOAL_ACTION_STATUS: dict[str, dict[str, str]] = {
    "complete": {"status": "archived", "status_reason": "completed by agent request"},
    "block": {"status": "blocked", "status_reason": "blocked by agent request"},
    "cancel": {"status": "archived", "status_reason": "cancelled by agent request"},
}


def durable_tool_specs(*, goal: bool, arrange: bool) -> list[ToolSpec]:
    specs: list[ToolSpec] = []
    if goal:
        specs.append(ToolSpec(
            name="goal",
            # user:“任何一个人看见这个工具描述，能够在 5 秒内看懂并理解这是个什么、怎么操作”
            # +(先讲它是什么闸门，再讲三种收口方式，最后讲什么时候别用)。
            description=(
                "目标不是任务清单，是一道防偷懒闸门：这件事没做完，不许收工。\n"
                "什么时候调用：用户要你把一件需要多步、且能自己判断做完没有的事做完，"
                "或明确让你盯住别提前交差时，create 一个；普通问答、闲聊、排定时任务都不要建。\n"
                "active 期间你自然收尾不算结束，系统会开下一回合并追问「存在目标：… 未完成，请继续」。\n"
                "收口由你判断：complete 真做完；block 标阻塞，必须用户拍板才能继续；cancel 放弃。"
            ),
            input_schema=_schema({
                "action": {
                    "type": "string",
                    "enum": ["create", "list", "get", "complete", "block", "cancel"],
                    "description": "create 建目标；list/get 查看；complete 标记完成；block 标记阻塞；cancel 放弃",
                },
                "objective": {
                    "type": "string",
                    "description": "一句话目标，会原样出现在续跑提醒里",
                },
                "completion_criteria": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "你自己判断完成用的标准，会随提醒一起列出来。没有外部校验，做完与否由你决定"
                    ),
                },
                "goal_id": {
                    "type": "string",
                    "description": "complete/block/cancel 省略时作用于本会话当前目标；其它动作按需填写",
                },
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
        elif action in {"get", "complete", "block", "cancel"}:
            goal_id = str(args.get("goal_id") or "").strip()
            if not goal_id:
                # user:“complete/block/cancel 省略时作用于本会话当前目标”
                # +(模型通常不知道目标 id，让它不必先 list 再猜；一个会话同时只有一个在跑的目标)。
                goal_id, lookup_error = await _current_goal_id(
                    execute_operation, session_id, call
                )
                if lookup_error:
                    return _failed(call, lookup_error)
            if action == "get":
                operation = "goal.get"
                payload = {"goal_id": goal_id}
            else:
                operation = "goal.update"
                payload = {"goal_id": goal_id, **_GOAL_ACTION_STATUS[action]}
        else:
            return _failed(call, "goal action must be create, list, get, complete, block, or cancel")
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
                "work_root": str(args.get("project_id") or args.get("work_root") or "").strip()
                or (str(Path(work_root).resolve()) if work_root else ""),
                "kind": str(args.get("kind") or "routine").strip(),
                "operation": "turn.start",
                "payload": {"message": str(args.get("instruction") or "").strip()},
                "trigger": trigger,
                "title": str(args.get("title") or "").strip(),
                "session_strategy": strategy,
                # An explicit user-selected model wins.  Otherwise retain the
                # host-stamped model from the active turn so a scheduled run
                # does not silently switch to the application default.
                "model_id": str(
                    args.get("model_id")
                    or call.metadata.get("_runtime_model_id")
                    or ""
                ).strip(),
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


async def _current_goal_id(
    execute_operation: OperationExecutor, session_id: str, call: ToolCall
) -> tuple[str, str]:
    """Resolve the session's single live goal, or an explanation for the model."""
    if not session_id:
        return "", "无法确定当前会话，不能操作目标；请显式传入 goal_id。"
    result = await execute_operation(
        "goal.list", {"thread_id": session_id}, _operation_metadata(call)
    )
    if str(getattr(result, "status", "")) != "ok":
        failed_payload = getattr(result, "payload", None)
        detail = (
            str(failed_payload.get("error") or "")
            if isinstance(failed_payload, dict)
            else ""
        )
        return "", detail or "目标列表读取失败，请稍后重试。"
    payload = getattr(result, "payload", None)
    goals = payload.get("goals") if isinstance(payload, dict) else None
    live = [
        goal
        for goal in (goals or [])
        if isinstance(goal, dict) and str(goal.get("status") or "") in {"active", "blocked"}
    ]
    if not live:
        return "", "本会话当前没有进行中的目标；确实需要盯住一件事时先用 create 建一个。"
    if len(live) > 1:
        return "", "本会话有多个进行中的目标，请用 goal_id 指定要操作哪一个。"
    return str(live[0].get("id") or ""), ""


def _operation_metadata(call: ToolCall) -> dict[str, Any]:
    return {
        "source": "agent_tool",
        # user:“边界情况”+(操作层要靠它判断目标是否属于本会话，避免误改别人的目标)。
        "session_id": _session_id(call),
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
