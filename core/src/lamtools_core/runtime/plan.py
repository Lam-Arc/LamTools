from __future__ import annotations

import datetime
from typing import Any

from lamtools_core.tool import ToolResult


def normalize_checklist_steps(raw_steps: Any, files: list[str]) -> list[dict[str, Any]]:
    steps = raw_steps if isinstance(raw_steps, list) else []
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(steps, start=1):
        if not isinstance(raw, dict):
            continue
        sid = str(raw.get("id") or f"s{index}")
        deliverables_raw = raw.get("deliverables")
        deliverables = [
            str(item)
            for item in (deliverables_raw if isinstance(deliverables_raw, list) else [])
            if str(item)
        ]
        normalized.append({
            "id": sid,
            "description": str(raw.get("description") or f"Step {index}"),
            "deliverables": deliverables,
            "status": "in_progress" if not normalized else "pending",
        })

    if not normalized and files:
        normalized.append({
            "id": "s1",
            "description": "Create planned deliverables",
            "deliverables": [str(item) for item in files],
            "status": "in_progress",
        })
    return normalized


def new_plan_revision(plan: dict[str, Any], reason: str, action: str, payload: dict[str, Any] | None = None) -> None:
    plan["revision"] = int(plan.get("revision") or 0) + 1
    history = plan.setdefault("history", [])
    if isinstance(history, list):
        history.append({
            "revision": plan["revision"],
            "action": action,
            "reason": reason,
            "payload": payload or {},
            "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
        })


def plan_to_active_plan(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "plan_files": plan.get("files", []),
        "plan_steps": plan.get("steps", []),
        "plan_summary": plan.get("goal", ""),
    }


def _checklist_mark(status: Any) -> str:
    return "x" if str(status or "").lower() == "completed" else " "


def format_checklist_markdown(steps: list[dict[str, Any]], files: list[str] | None = None, title: str = "Checklist") -> str:
    lines = [title.strip() or "Checklist"]
    for index, step in enumerate(steps, start=1):
        description = str(step.get("description") or f"Step {index}").strip()
        sid = str(step.get("id") or f"s{index}").strip()
        deliverables = step.get("deliverables") if isinstance(step.get("deliverables"), list) else []
        suffix = f" -> {', '.join(str(item) for item in deliverables if str(item))}" if deliverables else ""
        lines.append(f"{index}. - [{_checklist_mark(step.get('status'))}] {sid}. {description}{suffix}")
    if files:
        lines.append("")
        lines.append("Files:")
        for file in files:
            lines.append(f"- {file}")
    return "\n".join(lines)


def find_plan_step(plan: dict[str, Any], step_id: str) -> tuple[int, dict[str, Any] | None]:
    steps = plan.get("steps", [])
    if not isinstance(steps, list):
        return -1, None
    for index, step in enumerate(steps):
        if isinstance(step, dict) and str(step.get("id") or "") == step_id:
            return index, step
    return -1, None


def apply_checklist_update(plan: dict[str, Any] | None, update: dict[str, Any]) -> dict[str, Any]:
    current = dict(plan or {})
    current.setdefault("goal", "Task plan")
    current.setdefault("status", "active")
    current.setdefault("files", [])
    current.setdefault("steps", [])
    current.setdefault("revision", 0)
    action = str(update.get("action") or "")
    reason = str(update.get("reason") or "plan update")

    if action == "replace_plan":
        files = update.get("files") if isinstance(update.get("files"), list) else []
        summary = str(update.get("design_summary") or current.get("goal") or "Task plan")
        steps = normalize_checklist_steps(update.get("steps"), [str(item) for item in files])
        current.update({
            "goal": summary,
            "status": "active",
            "files": [str(item) for item in files],
            "steps": steps,
            "current_step_id": steps[0]["id"] if steps else "",
        })
        new_plan_revision(current, reason, action, update)
        return current

    steps = current.get("steps")
    if not isinstance(steps, list):
        steps = []
        current["steps"] = steps
    step_id = str(update.get("step_id") or "")
    index, step = find_plan_step(current, step_id)

    if action == "add_step":
        new_id = step_id or f"s{len(steps) + 1}"
        steps.append({
            "id": new_id,
            "description": str(update.get("description") or "New step"),
            "deliverables": [str(item) for item in (update.get("deliverables") or [])],
            "status": "pending" if current.get("current_step_id") else "in_progress",
        })
        current.setdefault("current_step_id", new_id)
    elif action == "update_step" and step is not None:
        if update.get("description"):
            step["description"] = str(update["description"])
        if isinstance(update.get("deliverables"), list):
            step["deliverables"] = [str(item) for item in update["deliverables"]]
        if update.get("status"):
            step["status"] = str(update["status"])
    elif action == "split_step" and step is not None:
        children = normalize_checklist_steps(update.get("steps"), [])
        if children:
            original_status = step.get("status", "pending")
            step["status"] = "replaced"
            for child in children:
                child["status"] = "in_progress" if original_status == "in_progress" and child is children[0] else "pending"
            steps[index + 1:index + 1] = children
            if original_status == "in_progress":
                current["current_step_id"] = children[0]["id"]
    elif action == "block_step" and step is not None:
        step["status"] = "blocked"
        step["blocked_reason"] = reason
        current["status"] = "blocked"
    elif action == "complete_step" and step is not None:
        step["status"] = "completed"
        start_next_pending_step(current)

    new_plan_revision(current, reason, action, update)
    return current


def start_next_pending_step(plan: dict[str, Any]) -> None:
    steps = plan.get("steps", [])
    if not isinstance(steps, list):
        plan["current_step_id"] = ""
        return
    for step in steps:
        if isinstance(step, dict) and step.get("status") == "in_progress":
            plan["current_step_id"] = step.get("id", "")
            return
    for step in steps:
        if isinstance(step, dict) and step.get("status") == "pending":
            step["status"] = "in_progress"
            plan["current_step_id"] = step.get("id", "")
            plan["status"] = "active"
            return
    plan["current_step_id"] = ""
    if steps:
        plan["status"] = "completed"


def _produced_paths(tool_results: list[ToolResult]) -> set[str]:
    produced: set[str] = set()
    for result in tool_results:
        if result.status != "ok" or result.name not in {"write_file", "edit_file"}:
            continue
        path = result.metadata.get("path") if isinstance(result.metadata, dict) else None
        if path:
            produced.add(str(path).replace("\\", "/"))
        for artifact in result.artifacts:
            if artifact.uri:
                produced.add(str(artifact.uri).replace("\\", "/"))
    return produced


def plan_is_completed(plan: Any) -> bool:
    if not isinstance(plan, dict):
        return False
    if str(plan.get("status") or "").lower() == "completed":
        return True
    steps = plan.get("steps")
    if not isinstance(steps, list) or not steps:
        return False
    return all(
        isinstance(step, dict)
        and str(step.get("status") or "").lower() in {"completed", "skipped"}
        for step in steps
    )


def has_delivery_progress(metadata: dict[str, Any]) -> bool:
    written_files = metadata.get("written_files")
    if isinstance(written_files, list) and any(str(item).strip() for item in written_files):
        return True

    recent_tools = metadata.get("recent_tools")
    if isinstance(recent_tools, list) and any(str(tool) in {"write_file", "edit_file"} for tool in recent_tools):
        return True

    artifact_registry = metadata.get("artifact_registry")
    if isinstance(artifact_registry, list):
        for item in artifact_registry:
            if isinstance(item, dict) and item.get("kind") == "file_change":
                return True

    return plan_is_completed(metadata.get("task_plan"))


def auto_advance_plan(plan: dict[str, Any], tool_results: list[ToolResult]) -> bool:
    produced = _produced_paths(tool_results)
    if not produced:
        return False
    current_id = str(plan.get("current_step_id") or "")
    _, step = find_plan_step(plan, current_id)
    if step is None or step.get("status") != "in_progress":
        return False
    deliverables = [str(item).replace("\\", "/") for item in step.get("deliverables", []) or []]
    if not deliverables or not set(deliverables).issubset(produced):
        return False
    step["status"] = "completed"
    start_next_pending_step(plan)
    new_plan_revision(plan, "current step deliverables were produced", "auto_complete_step", {
        "step_id": current_id,
        "produced": sorted(produced),
    })
    return True


__all__ = [
    "normalize_checklist_steps",
    "new_plan_revision",
    "plan_to_active_plan",
    "format_checklist_markdown",
    "find_plan_step",
    "apply_checklist_update",
    "start_next_pending_step",
    "plan_is_completed",
    "has_delivery_progress",
    "auto_advance_plan",
]