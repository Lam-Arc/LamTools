from __future__ import annotations

from pathlib import Path

from lamtools_core.tool import ToolCall, ToolResult
from lamtools_core.tool.workspace import validate_workspace_path as _validate_path
from lamtools_core.runtime.plan import format_checklist_markdown, normalize_checklist_steps


async def request_commit_review(call: ToolCall) -> ToolResult:
    args = call.arguments if isinstance(call.arguments, dict) else {}
    title = str(args.get("title") or "").strip()
    summary = str(args.get("summary") or "").strip()
    how_to_review = str(args.get("how_to_review") or "").strip()
    self_check = str(args.get("self_check") or "").strip()
    commit_message = str(args.get("commit_message") or "").strip()

    if not title:
        title = "请验收本阶段改动"
    if not summary:
        return ToolResult(
            call_id=call.id,
            name=call.name,
            status="failed",
            error="请说明这次改了什么，方便用户验收。",
        )
    if not how_to_review:
        how_to_review = "查看右侧改动，按本轮需求做一次关键流程验证。"

    payload = {
        "title": title[:120],
        "summary": summary[:1200],
        "how_to_review": how_to_review[:800],
        "self_check": self_check[:800],
        "commit_message": commit_message[:160],
    }
    return ToolResult(
        call_id=call.id,
        name=call.name,
        status="ok",
        content=f"已发起验收：{payload['title']}",
        metadata={"commit_review_request": payload},
    )


async def write_checklist(call: ToolCall) -> ToolResult:
    args = call.arguments if isinstance(call.arguments, dict) else {}
    files = args.get("files", [])
    design_summary = args.get("design_summary", "")
    steps = args.get("steps", [])
    normalized_steps = normalize_checklist_steps(steps, files)
    task_plan = {
        "goal": design_summary or "Task plan",
        "status": "active",
        "current_step_id": normalized_steps[0]["id"] if normalized_steps else "",
        "steps": normalized_steps,
        "files": files,
    }

    title = f"Checklist: {design_summary}" if design_summary else "Checklist"
    content = (
        format_checklist_markdown(normalized_steps, [str(item) for item in files], title)
        if normalized_steps
        else "Checklist recorded (no steps)"
    )

    return ToolResult(
        call_id=call.id,
        name=call.name,
        status="ok",
        content=content,
        metadata={
            "plan_files": files,
            "plan_steps": normalized_steps,
            "plan_summary": design_summary,
            "task_plan": task_plan,
        },
    )


async def update_checklist(call: ToolCall) -> ToolResult:
    args = call.arguments if isinstance(call.arguments, dict) else {}
    action = str(args.get("action") or "")
    reason = str(args.get("reason") or "").strip()
    allowed = {
        "add_step",
        "update_step",
        "split_step",
        "block_step",
        "complete_step",
        "replace_plan",
    }
    if action not in allowed:
        return ToolResult(
            call_id=call.id,
            name=call.name,
            status="failed",
            error=f"Unsupported checklist update action: {action}",
        )
    if not reason:
        return ToolResult(
            call_id=call.id,
            name=call.name,
            status="failed",
            error="Checklist update requires a reason",
        )

    update = {
        "action": action,
        "step_id": args.get("step_id"),
        "description": args.get("description"),
        "deliverables": args.get("deliverables"),
        "status": args.get("status"),
        "steps": args.get("steps"),
        "files": args.get("files"),
        "design_summary": args.get("design_summary"),
        "reason": reason,
    }
    step_suffix = f" {update['step_id']}" if update.get("step_id") else ""
    check = "x" if action == "complete_step" else " "
    summary = str(update.get("description") or reason)
    return ToolResult(
        call_id=call.id,
        name=call.name,
        status="ok",
        content=f"- [{check}] {action}{step_suffix}: {summary}\n\nReason: {reason}",
        metadata={"checklist_update": update},
    )


async def verify_design(call: ToolCall, *, work_root: Path) -> ToolResult:
    args = call.arguments if isinstance(call.arguments, dict) else {}
    design_path = args.get("design_path", "design.html")

    try:
        design_resolved = _validate_path(design_path, work_root)
    except ValueError:
        design_resolved = None

    findings = []
    if design_resolved and design_resolved.is_file():
        findings.append(f"Design file {design_path} exists")
    else:
        findings.append(f"Design file {design_path} not found (skipping cross-reference check)")

    try:
        existing_files = set()
        for path in work_root.rglob("*"):
            if path.is_file() and ".git" not in path.parts:
                existing_files.add(path.relative_to(work_root).as_posix())
        findings.append(f"Found {len(existing_files)} files in work directory")
    except OSError:
        findings.append("Could not list work directory files")

    return ToolResult(
        call_id=call.id,
        name=call.name,
        status="ok",
        content="\n".join(findings),
    )
