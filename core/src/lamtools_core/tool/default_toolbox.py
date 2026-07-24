from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal, Protocol, runtime_checkable

from lamtools_core.event import CoreEvent
from lamtools_core.agent import SUB_AGENT_TOOL_NAME, SUB_AGENT_TOOL_SPEC, SubAgentRunResult
from lamtools_core.skills import SkillRegistry
from lamtools_core.tool import ToolCall, ToolContext, ToolResult, ToolSpec
from lamtools_core.tool.approval import ApprovalGate
from lamtools_core.tool.loadtools import LoadTools, mode_tool_set
from lamtools_core.tool.command import run_subprocess
from lamtools_core.tool.command_tools import CommandToolHandlers
from lamtools_core.tool.durable_tools import (
    OperationExecutor,
    arrange_requires_approval,
    durable_tool_handlers,
    durable_tool_specs,
)
from lamtools_core.tool.git_tools import make_git_diff_handler, make_git_status_handler
from lamtools_core.tool.mcp_tools import MCPToolCaller, execute_mcp_tool_call
from lamtools_core.tool.permission import ASK_USER, AUTO_ALLOW, HARD_BLOCK, PermissionTier
from lamtools_core.tool.spreadsheet import (
    SPREADSHEET_WRITE_INPUT_SCHEMA,
    write_spreadsheet_tool,
)
from lamtools_core.tool.web_tools import (
    make_browser_check_handler,
    make_web_fetch_handler,
    make_web_search_handler,
)
from lamtools_core.tool.workspace_files import (
    DEFAULT_MAX_LIST_ITEMS,
    DEFAULT_MAX_SEARCH_RESULTS,
    DEFAULT_MAX_TEXT_LENGTH,
    make_document_normalize_handler,
    make_edit_file_handler,
    make_write_file_handler,
    WorkspaceReadOnlyTools,
)
from lamtools_core.runtime.plan import (
    apply_checklist_update as _apply_checklist_update,
    auto_advance_plan as _auto_advance_plan,
    format_checklist_markdown,
    normalize_checklist_steps,
)

ToolHandler = Callable[[ToolCall], Awaitable[ToolResult]]
ApprovalPolicy = Literal["require", "auto_approve"]


@runtime_checkable
class SubAgentRunner(Protocol):
    async def run(
        self,
        *,
        task: str,
        agent: str = "",
        parent_call_id: str = "",
        parent_run_id: str = "",
        parent_turn_id: str = "",
    ) -> SubAgentRunResult | str: ...

DEFAULT_COMMAND_TIMEOUT = 120


DEFAULT_TOOL_PERMISSIONS: dict[str, PermissionTier] = {
    "read_file": AUTO_ALLOW,
    "document_normalize": ASK_USER,
    "list_dir": AUTO_ALLOW,
    "search_files": AUTO_ALLOW,
    "search_content": AUTO_ALLOW,
    "load_skill": AUTO_ALLOW,
    "write_file": ASK_USER,
    "write_spreadsheet": ASK_USER,
    "edit_file": ASK_USER,
    "run_command": ASK_USER,
    "run_tests": ASK_USER,
    "git_status": AUTO_ALLOW,
    "git_diff": AUTO_ALLOW,
    "web_search": AUTO_ALLOW,
    "web_fetch": ASK_USER,
    "browser_check": AUTO_ALLOW,
    "mcp_tool": ASK_USER,
    SUB_AGENT_TOOL_NAME: AUTO_ALLOW,
    "write_checklist": AUTO_ALLOW,
    "update_checklist": AUTO_ALLOW,
}


DEFAULT_TOOL_ORDER: tuple[str, ...] = (
    "read_file",
    "document_normalize",
    "list_dir",
    "search_files",
    "search_content",
    "load_skill",
    "write_file",
    "write_spreadsheet",
    "edit_file",
    "run_command",
    "run_tests",
    "git_status",
    "git_diff",
    "web_search",
    "web_fetch",
    "browser_check",
    "mcp_tool",
    SUB_AGENT_TOOL_NAME,
    "write_checklist",
    "update_checklist",
)


DEFAULT_TOOL_CATEGORIES: dict[str, str] = {
    "read_file": "file_read",
    "document_normalize": "file_write",
    "list_dir": "file_read",
    "search_files": "file_read",
    "search_content": "file_read",
    "load_skill": "skill",
    "write_file": "file_write",
    "write_spreadsheet": "file_write",
    "edit_file": "file_write",
    "run_command": "command",
    "run_tests": "command",
    "git_status": "git",
    "git_diff": "git",
    "web_search": "web",
    "web_fetch": "web",
    "browser_check": "browser",
    "mcp_tool": "mcp",
    SUB_AGENT_TOOL_NAME: "agent",
    "write_checklist": "control",
    "update_checklist": "control",
}


DEFAULT_TOOL_FAILURE_MODES: dict[str, list[dict[str, str]]] = {
    "read_file": [
        {"type": "path_outside_root", "message": "Blocked: path is outside work_root"},
        {"type": "file_not_found", "message": "File not found"},
        {"type": "read_error", "message": "Error reading file"},
    ],
    "document_normalize": [
        {"type": "path_outside_root", "message": "Blocked: path is outside work_root"},
        {"type": "file_not_found", "message": "File not found"},
        {"type": "normalize_error", "message": "Document normalization failed"},
    ],
    "write_file": [
        {"type": "path_outside_root", "message": "Blocked: path is outside work_root"},
        {"type": "sensitive_pattern", "message": "Blocked: path contains sensitive pattern"},
        {"type": "write_rejected", "message": "WRITE REJECTED: {reason}"},
    ],
    "write_spreadsheet": [
        {"type": "path_outside_root", "message": "Blocked: path is outside work_root"},
        {"type": "invalid_workbook", "message": "Spreadsheet input or workbook is invalid"},
        {"type": "write_rejected", "message": "Spreadsheet write rejected: {reason}"},
    ],
    "edit_file": [
        {"type": "old_string_empty", "message": "old_string is empty"},
        {"type": "old_string_not_found", "message": "old_string not found in file"},
        {"type": "path_outside_root", "message": "Blocked: path is outside work_root"},
        {"type": "sensitive_pattern", "message": "Blocked: path contains sensitive pattern"},
        {"type": "edit_rejected", "message": "EDIT REJECTED: {reason}"},
    ],
    "run_command": [
        {"type": "command_rejected", "message": "Command rejected: {reason}"},
        {"type": "command_failed", "message": "Command failed with exit code {code}"},
        {"type": "command_timeout", "message": "Command timed out after {timeout}s"},
        {"type": "incompatible_shell", "message": "Incompatible shell command on Windows"},
        {"type": "port_in_use", "message": "Requested local port is already listening"},
        {"type": "wrong_server", "message": "HTTP probe reached a server that is not serving the current work_root"},
        {"type": "probe_unreachable", "message": "Background process did not become reachable at the probe URL"},
        {"type": "probe_http_error", "message": "Readiness URL returned a non-success HTTP status"},
        {"type": "readiness_text_missing", "message": "Readiness response did not contain readiness_text"},
    ],
    "run_tests": [
        {"type": "no_test_command", "message": "No test command detected"},
        {"type": "test_failed", "message": "Tests failed"},
        {"type": "command_timeout", "message": "Test command timed out"},
    ],
    "web_search": [{"type": "search_failed", "message": "Web search failed"}],
    "web_fetch": [
        {"type": "fetch_failed", "message": "Failed to fetch URL"},
        {"type": "invalid_url", "message": "Invalid URL"},
    ],
    "browser_check": [
        {"type": "file_protocol_blocked", "message": "Access to file: protocol is blocked"},
        {"type": "fetch_failed", "message": "Failed to fetch URL"},
    ],
    "mcp_tool": [
        {"type": "mcp_error", "message": "MCP TOOL ERROR: {reason}"},
        {"type": "tool_not_found", "message": "MCP tool not found"},
    ],
}


DEFAULT_TOOL_RECOVERY: dict[str, str] = {
    "read_file": "Check path exists, use list_dir to find correct path",
    "document_normalize": "Check that the path is a readable DOCX, PDF, or XLSX inside the workspace",
    "write_file": "Check path bounds, avoid sensitive patterns, ensure content is valid",
    "write_spreadsheet": (
        "Use workspace-relative .xlsx paths, valid A1 cell references, and formulas beginning with ="
    ),
    "edit_file": "Read file first to get exact content, use precise old_string match",
    "search_content": "Use an exact substring from the file or narrow the search path",
    "run_command": (
        "Fix command syntax, check platform compatibility, or increase timeout. For local preview servers, use "
        "recommended_action from tool metadata; for port_in_use choose a free port instead of retrying the same command."
    ),
    "run_tests": (
        "If assertions fail, fix production code before rerunning equivalent tests. If the command itself is "
        "invalid, pass an explicit command, create a test script, or use alternative verification."
    ),
    "web_search": "Retry with simpler query, try different search terms",
    "web_fetch": "Check URL validity, try alternative URL",
    "browser_check": "Use local static server with http://127.0.0.1:<port>/ instead of file://",
    "mcp_tool": "Check tool name and arguments, verify MCP server status",
}


DEFAULT_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "status": {"type": "string", "enum": ["ok", "failed", "skipped", "blocked"]},
        "content": {"type": "string"},
        "error": {"type": "string"},
        "metadata": {"type": "object"},
        "artifacts": {"type": "array", "items": {"type": "object"}},
    },
    "required": ["status", "content", "error", "metadata", "artifacts"],
}


def _schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": required or [],
    }


DEFAULT_TOOL_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "name": "read_file",
        "description": (
            "Read file content within the workspace. DOCX, PDF, and XLSX documents are automatically normalized "
            "to Markdown and labeled as untrusted content."
        ),
        "input_schema": _schema(
            {"path": {"type": "string", "description": "File path relative to the workspace"}},
            ["path"],
        ),
    },
    {
        "name": "document_normalize",
        "description": (
            "Normalize a DOCX, PDF, or XLSX to Markdown and persist extracted DOCX image assets under "
            ".lamtools/document-assets. This operation writes files and requires approval."
        ),
        "input_schema": _schema(
            {"path": {"type": "string", "description": "Document path relative to the workspace"}},
            ["path"],
        ),
    },
    {
        "name": "list_dir",
        "description": "List directory contents within the workspace.",
        "input_schema": _schema({"path": {"type": "string", "description": "Directory path"}}),
    },
    {
        "name": "search_files",
        "description": "Find files by glob pattern within the workspace.",
        "input_schema": _schema(
            {
                "pattern": {"type": "string", "description": "Glob pattern"},
                "path": {"type": "string", "description": "Search path"},
            },
            ["pattern"],
        ),
    },
    {
        "name": "search_content",
        "description": "Search file contents with a literal text pattern.",
        "input_schema": _schema(
            {
                "pattern": {"type": "string", "description": "Literal text pattern"},
                "path": {"type": "string", "description": "File or directory search path"},
            },
            ["pattern"],
        ),
    },
    {
        "name": "load_skill",
        "description": "Load a local skill's instructions when the task matches that skill.",
        "input_schema": _schema(
            {"name": {"type": "string", "description": "Skill name from the available skills index"}},
            ["name"],
        ),
    },
    {
        "name": "write_file",
        "description": (
            "Write content to a file. Use for creating files or full rewrites; prefer edit_file "
            "for small changes to existing files."
        ),
        "input_schema": _schema(
            {
                "path": {"type": "string", "description": "File path relative to the workspace"},
                "content": {"type": "string", "description": "File content to write"},
            },
            ["path", "content"],
        ),
    },
    {
        "name": "write_spreadsheet",
        "description": (
            "Create a new XLSX workbook or apply structured cell updates to an existing XLSX workbook. "
            "Supports literal values, formulas, common cell formatting, column widths, and freeze panes. "
            "Formulas are preserved but not calculated by Core."
        ),
        "input_schema": SPREADSHEET_WRITE_INPUT_SCHEMA,
    },
    {
        "name": "edit_file",
        "description": "Replace one exact text segment in an existing file.",
        "input_schema": _schema(
            {
                "path": {"type": "string", "description": "File path relative to the workspace"},
                "old_string": {"type": "string", "description": "Exact text to replace"},
                "new_string": {"type": "string", "description": "Replacement text"},
            },
            ["path", "old_string", "new_string"],
        ),
    },
    {
        "name": "run_command",
        "description": (
            "Run a shell command inside the workspace. Servers and watchers must use background=true; "
            "do not append &, nohup, or start. Results separately report process_state, shell_state, "
            "and readiness_state."
        ),
        "input_schema": _schema(
            {
                "command": {"type": "string", "description": "Command to run"},
                "timeout": {"type": "integer", "description": "Timeout in seconds"},
                "background": {
                    "type": "boolean",
                    "description": "Start a server/watcher as a tracked background process instead of shell-level detachment",
                },
                "readiness_url": {"type": "string", "description": "HTTP URL to check when background=true"},
                "readiness_text": {"type": "string", "description": "Optional text expected at readiness_url"},
            },
            ["command"],
        ),
    },
    {
        "name": "run_tests",
        "description": "Run the detected or specified test command inside the workspace.",
        "input_schema": _schema(
            {
                "command": {"type": "string", "description": "Test command; auto-detected when omitted"},
                "timeout": {"type": "integer", "description": "Timeout in seconds"},
            }
        ),
    },
    {
        "name": "git_status",
        "description": "Run git status in the workspace.",
        "input_schema": _schema({}),
    },
    {
        "name": "git_diff",
        "description": "Run git diff in the workspace.",
        "input_schema": _schema({"path": {"type": "string", "description": "Optional path filter"}}),
    },
    {
        "name": "web_search",
        "description": "Search the web.",
        "input_schema": _schema(
            {
                "query": {"type": "string", "description": "Search query"},
                "limit": {"type": "integer", "description": "Maximum result count"},
                "domains": {"type": "array", "items": {"type": "string"}, "description": "Domain filter"},
            },
            ["query"],
        ),
    },
    {
        "name": "web_fetch",
        "description": "Fetch content from a URL.",
        "input_schema": _schema({"url": {"type": "string", "description": "URL to fetch"}}, ["url"]),
    },
    {
        "name": "browser_check",
        "description": "Fetch a URL and optionally check expected text.",
        "input_schema": _schema(
            {
                "url": {"type": "string", "description": "URL to check"},
                "expect": {"type": "string", "description": "Expected text"},
            },
            ["url"],
        ),
    },
    {
        "name": "mcp_tool",
        "description": "Call an MCP-registered tool.",
        "input_schema": _schema(
            {
                "tool_name": {"type": "string", "description": "MCP tool name"},
                "arguments": {"type": "object", "description": "Tool arguments"},
            },
            ["tool_name"],
        ),
    },
    {
        "name": "write_checklist",
        "description": (
            "Create the active structured checklist for the task. Use short numbered steps; each step becomes a "
            "Markdown checkbox in the UI."
        ),
        "input_schema": _schema(
            {
                "design_summary": {
                    "type": "string",
                    "description": "One short business-language sentence describing the goal.",
                },
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Files or deliverables expected to change.",
                },
                "steps": {
                    "type": "array",
                    "description": "Ordered checklist items. Use 3-7 concrete steps for normal engineering tasks.",
                    "items": _schema(
                        {
                            "id": {"type": "string", "description": "Stable id like s1, s2, s3."},
                            "description": {"type": "string", "description": "User-readable action item."},
                            "deliverables": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Concrete outputs for this step.",
                            },
                        },
                        ["id", "description"],
                    ),
                },
            },
            ["design_summary", "steps"],
        ),
    },
    {
        "name": "update_checklist",
        "description": (
            "Update the active structured checklist. Mark a step complete immediately after verifying its deliverable; "
            "do not rewrite the whole checklist for ordinary progress."
        ),
        "input_schema": _schema(
            {
                "action": {
                    "type": "string",
                    "enum": ["add_step", "update_step", "split_step", "block_step", "complete_step", "replace_plan"],
                },
                "step_id": {"type": "string"},
                "description": {"type": "string"},
                "deliverables": {"type": "array", "items": {"type": "string"}},
                "status": {
                    "type": "string",
                    "enum": ["pending", "in_progress", "completed", "blocked", "skipped", "replaced"],
                    "description": "New status for update_step.",
                },
                "steps": {"type": "array", "items": {"type": "object"}},
                "files": {"type": "array", "items": {"type": "string"}},
                "design_summary": {"type": "string"},
                "reason": {"type": "string", "description": "Short reason visible in the run log."},
            },
            ["action", "reason"],
        ),
    },
    deepcopy(SUB_AGENT_TOOL_SPEC),
)


def default_core_tool_specs() -> list[ToolSpec]:
    specs_by_name = {str(item["name"]): item for item in DEFAULT_TOOL_DEFINITIONS}
    specs: list[ToolSpec] = []
    for name in DEFAULT_TOOL_ORDER:
        item = specs_by_name[name]
        category = DEFAULT_TOOL_CATEGORIES[name]
        specs.append(
            ToolSpec(
                name=name,
                description=str(item["description"]),
                input_schema=strict_tool_schema(item["input_schema"]),
                output_schema=deepcopy(DEFAULT_OUTPUT_SCHEMA),
                permission=DEFAULT_TOOL_PERMISSIONS[name],
                metadata={
                    "category": category,
                    "display": _default_display(category),
                    "failure_modes": deepcopy(
                        item.get("failure_modes", DEFAULT_TOOL_FAILURE_MODES.get(name, []))
                    ),
                    "recovery": str(item.get("recovery", DEFAULT_TOOL_RECOVERY.get(name, ""))),
                },
            )
        )
    return specs


def core_model_tools(
    specs: list[ToolSpec] | None = None,
    *,
    include_tools: set[str] | None = None,
    exclude_tools: set[str] | None = None,
) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    for spec in specs or default_core_tool_specs():
        if include_tools is not None and spec.name not in include_tools:
            continue
        if exclude_tools is not None and spec.name in exclude_tools:
            continue
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "strict": True,
                    "parameters": deepcopy(spec.input_schema),
                },
            }
        )
    return tools


def strict_tool_schema(schema: dict[str, Any]) -> dict[str, Any]:
    normalized = deepcopy(schema)

    def allow_null(node: dict[str, Any]) -> None:
        schema_type = node.get("type")
        if isinstance(schema_type, str):
            if schema_type != "null":
                node["type"] = [schema_type, "null"]
        elif isinstance(schema_type, list):
            if "null" not in schema_type:
                node["type"] = [*schema_type, "null"]

    def visit(node: dict[str, Any]) -> None:
        if node.get("type") == "object" or "properties" in node:
            properties = node.get("properties")
            if isinstance(properties, dict):
                originally_required = set(node.get("required") or [])
                for key, child in properties.items():
                    if isinstance(child, dict):
                        if key not in originally_required:
                            allow_null(child)
                        visit(child)
                node["required"] = list(properties.keys())
            node["additionalProperties"] = False
        items = node.get("items")
        if isinstance(items, dict):
            visit(items)

    visit(normalized)
    return normalized


async def _write_checklist_handler(call: ToolCall) -> ToolResult:
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


async def _update_checklist_handler(call: ToolCall) -> ToolResult:
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


class CoreToolbox:
    def __init__(
        self,
        *,
        work_root: str | Path,
        command_timeout: int = DEFAULT_COMMAND_TIMEOUT,
        max_list_items: int = DEFAULT_MAX_LIST_ITEMS,
        max_text_length: int = DEFAULT_MAX_TEXT_LENGTH,
        max_search_results: int = DEFAULT_MAX_SEARCH_RESULTS,
        loaded_skill_roots: set[Path] | None = None,
        skill_registry: SkillRegistry | None = None,
        mcp_caller: MCPToolCaller | None = None,
        mcp_tool_specs: list[ToolSpec] | None = None,
        sub_agent_runner: SubAgentRunner | None = None,
        command_policies: dict[str, object] | None = None,
        approval_policy: ApprovalPolicy = "require",
        disabled_tools: set[str] | None = None,
        core_event_callback: Callable[[CoreEvent], Awaitable[None]] | None = None,
        operation_executor: OperationExecutor | None = None,
        enable_goal_tool: bool = False,
        enable_arrange_tool: bool = False,
        active_tier: "PermissionMode | None" = None,
        tier_tools: "TierTools | None" = None,
        load_tools: LoadTools | None = None,
    ) -> None:
        self.work_root = Path(work_root).resolve()
        self.work_root.mkdir(parents=True, exist_ok=True)
        self.loaded_skill_roots = {Path(item).resolve() for item in loaded_skill_roots or set()}
        self.mcp_caller = mcp_caller
        self.sub_agent_runner = sub_agent_runner
        self._failed_sub_agent_calls: dict[tuple[str, str], dict[str, Any]] = {}
        self.approval_policy = approval_policy
        self.disabled_tools = set(disabled_tools or set())
        self.load_tools = load_tools or {}
        self.tool_permissions = dict(DEFAULT_TOOL_PERMISSIONS)
        self.skill_registry = skill_registry or SkillRegistry(explicit_roots=self.loaded_skill_roots)
        self._dynamic_mcp_tool_names = {spec.name for spec in mcp_tool_specs or [] if spec.name.startswith("mcp__")}
        for spec in mcp_tool_specs or []:
            self.tool_permissions[spec.name] = spec.permission  # type: ignore[assignment]
        durable_specs = durable_tool_specs(
            goal=enable_goal_tool and operation_executor is not None,
            arrange=enable_arrange_tool and operation_executor is not None,
        )
        for spec in durable_specs:
            self.tool_permissions[spec.name] = spec.permission  # type: ignore[assignment]
        for name in self.disabled_tools:
            self.tool_permissions[name] = HARD_BLOCK
        self.approval_gate = ApprovalGate(
            work_root=self.work_root,
            tool_permissions=self.tool_permissions,
            command_policies=command_policies,
            active_tier=active_tier,
            tier_tools=tier_tools,
        )
        self._specs = [*default_core_tool_specs(), *list(mcp_tool_specs or []), *durable_specs]
        self._handlers = self._build_handlers(
            command_timeout=command_timeout,
            max_list_items=max_list_items,
            max_text_length=max_text_length,
            max_search_results=max_search_results,
            core_event_callback=core_event_callback,
            operation_executor=operation_executor,
        )

    def tool_specs(self) -> list[ToolSpec]:
        return [
            replace(spec, permission=self.tool_permissions.get(spec.name, HARD_BLOCK))
            for spec in self._specs
            if spec.name not in self.disabled_tools
        ]

    def model_tools(
        self,
        *,
        include_tools: set[str] | None = None,
        exclude_tools: set[str] | None = None,
        active_mode: str | None = None,
    ) -> list[dict[str, Any]]:
        effective_exclude = set(exclude_tools or set())
        # Apply loadtools active_mode filtering
        if active_mode and self.load_tools:
            allowed = mode_tool_set(self.load_tools, active_mode)
            if allowed is not None:
                # Build exclude set = all tool names NOT in allowed set
                all_names = {spec.name for spec in self.tool_specs()}
                effective_exclude |= (all_names - allowed)
        return core_model_tools(self.tool_specs(), include_tools=include_tools, exclude_tools=effective_exclude or None)

    def skill_index(self) -> str:
        return self.skill_registry.prompt_index(self.work_root)

    def prepare_call(self, call: ToolCall) -> ToolCall:
        args = call.arguments if isinstance(call.arguments, dict) else {}
        decision = self.approval_gate.check(call.name, args)
        if call.name == "arrange" and not arrange_requires_approval(args) and not decision.blocked:
            decision = replace(
                decision,
                allowed=True,
                reason="Auto-approved read-only Arrange action",
                requires_approval=False,
            )
        approval = {
            "tier": decision.permission_tier,
            "reason": decision.reason,
            "blocked": decision.blocked,
            "requires_approval": decision.requires_approval,
        }
        requires_approval = bool(decision.requires_approval)
        if self.approval_policy == "auto_approve" and requires_approval and not decision.blocked:
            requires_approval = False
            approval["requires_approval"] = False
            approval["auto_approved"] = True
        metadata = {**dict(call.metadata or {}), "approval": approval}
        return replace(
            call,
            requires_approval=requires_approval,
            metadata=metadata,
        )

    async def execute(self, call: ToolCall, context: ToolContext | None = None) -> ToolResult:
        approval = call.metadata.get("approval") if isinstance(call.metadata, dict) else None
        if isinstance(approval, dict) and approval.get("blocked"):
            return ToolResult(
                call_id=call.id,
                name=call.name,
                status="blocked",
                error=str(approval.get("reason") or "Tool call blocked"),
                metadata={"approval": approval},
            )
        if call.name in self.disabled_tools:
            return ToolResult(call_id=call.id, name=call.name, status="blocked", error=f"Tool disabled: {call.name}")
        handler = self._handlers.get(call.name)
        if handler is None and call.name in self._dynamic_mcp_tool_names:
            handler = self._handlers.get("mcp_tool")
        if handler is None:
            return ToolResult(call_id=call.id, name=call.name, status="blocked", error=f"Unknown tool: {call.name}")
        return await handler(call)

    def _build_handlers(
        self,
        *,
        command_timeout: int,
        max_list_items: int,
        max_text_length: int,
        max_search_results: int,
        core_event_callback: Callable[[CoreEvent], Awaitable[None]] | None,
        operation_executor: OperationExecutor | None,
    ) -> dict[str, ToolHandler]:
        read_tools = WorkspaceReadOnlyTools(
            self.work_root,
            max_list_items=max_list_items,
            max_text_length=max_text_length,
            max_search_results=max_search_results,
        )
        for root in self.loaded_skill_roots:
            read_tools.add_resource_root(root)
        command_handlers = CommandToolHandlers(
            work_root=self.work_root,
            command_timeout=command_timeout,
            loaded_skill_roots=self.loaded_skill_roots,
            core_event_callback=core_event_callback,
        )

        async def call_mcp(call: ToolCall) -> ToolResult:
            return await execute_mcp_tool_call(call, caller=self.mcp_caller)

        async def load_skill(call: ToolCall) -> ToolResult:
            args = call.arguments if isinstance(call.arguments, dict) else {}
            name = args.get("name", "")
            if not isinstance(name, str) or not name.strip():
                return ToolResult(call_id=call.id, name=call.name, status="failed", error="Missing 'name' argument")

            content = self.skill_registry.load_prompt_content(self.work_root, name)
            found = not content.startswith(f'Skill "{name}" not found.')
            if found:
                skill = self.skill_registry.get(self.work_root, name)
                if skill is not None:
                    base = skill.location.parent.resolve()
                    self.loaded_skill_roots.add(base)
                    read_tools.add_resource_root(base)
            return ToolResult(
                call_id=call.id,
                name=call.name,
                status="ok" if found else "failed",
                content=content,
                error="" if found else content,
                metadata={
                    "skill": name.strip(),
                    "found": found,
                    "resource_roots": [path.as_posix() for path in read_tools.resource_roots()],
                },
            )

        async def call_sub_agent(call: ToolCall) -> ToolResult:
            if self.sub_agent_runner is None:
                return ToolResult(
                    call_id=call.id,
                    name=call.name,
                    status="failed",
                    error="Sub-agent runner not available",
                )
            args = call.arguments if isinstance(call.arguments, dict) else {}
            task = str(args.get("task") or "").strip()
            if not task:
                return ToolResult(call_id=call.id, name=call.name, status="failed", error="sub_agent requires 'task'")
            agent = str(args.get("agent") or "").strip()
            failure_key = (agent.lower(), task)
            previous_failure = self._failed_sub_agent_calls.get(failure_key)
            if previous_failure is not None:
                error = "Identical sub-agent task already failed; repeated execution was blocked."
                return ToolResult(
                    call_id=call.id,
                    name=call.name,
                    status="failed",
                    content=f"SUB_AGENT FAILED: {error}",
                    error=error,
                    metadata={**previous_failure, "duplicate_failure_blocked": True},
                )
            outcome = await self.sub_agent_runner.run(
                task=task,
                agent=agent,
                parent_call_id=call.id,
                parent_run_id=str(call.metadata.get("parent_run_id") or ""),
                parent_turn_id=str(call.metadata.get("parent_turn_id") or ""),
            )
            if isinstance(outcome, SubAgentRunResult):
                metadata = {
                    "agent": agent,
                    "sub_session_id": outcome.session_id,
                    "sub_run_id": outcome.run_id,
                    "decision": outcome.decision,
                    "model_id": outcome.model_id,
                    "tool_call_count": outcome.tool_call_count,
                    "ended_with_final_response": outcome.ended_with_final_response,
                }
                if outcome.decision == "wait":
                    waiting_request = dict(outcome.pending_waiting_request)
                    wait_reason = str(waiting_request.get("request_kind") or "approval")
                    metadata.update({
                        "pending_approval": dict(outcome.pending_approval),
                        "pending_waiting_request": waiting_request,
                        "wait_reason": wait_reason,
                        "delegated_session": {
                            "session_id": outcome.session_id,
                            "agent": agent,
                            "task": task,
                            "parent_call_id": call.id,
                            "parent_run_id": str(call.metadata.get("parent_run_id") or ""),
                            "parent_turn_id": str(call.metadata.get("parent_turn_id") or ""),
                        },
                    })
                    return ToolResult(
                        call_id=call.id,
                        name=call.name,
                        status="blocked",
                        content=(
                            "Sub-agent paused after making no progress."
                            if wait_reason == "no_progress"
                            else "Sub-agent is waiting for approval."
                        ),
                        metadata=metadata,
                    )
                if not outcome.succeeded:
                    error = outcome.failure_message()
                    self._failed_sub_agent_calls[failure_key] = dict(metadata)
                    return ToolResult(
                        call_id=call.id,
                        name=call.name,
                        status="failed",
                        content=f"SUB_AGENT FAILED: {error}",
                        error=error,
                        metadata=metadata,
                    )
                self._failed_sub_agent_calls.pop(failure_key, None)
                return ToolResult(
                    call_id=call.id,
                    name=call.name,
                    status="ok",
                    content=outcome.message,
                    metadata=metadata,
                )
            return ToolResult(
                call_id=call.id,
                name=call.name,
                status="ok",
                content=str(outcome),
                metadata={
                    "agent": str(args.get("agent") or ""),
                },
            )

        handlers: dict[str, ToolHandler] = {
            **read_tools.as_dict(),
            "document_normalize": make_document_normalize_handler(
                self.work_root,
                max_text_length=max_text_length,
            ),
            "load_skill": load_skill,
            "write_file": make_write_file_handler(self.work_root),
            "write_spreadsheet": lambda call: write_spreadsheet_tool(call, work_root=self.work_root),
            "edit_file": make_edit_file_handler(self.work_root),
            "run_command": command_handlers.run_command,
            "run_tests": command_handlers.run_tests,
            "git_status": make_git_status_handler(
                self.work_root,
                command_timeout=command_timeout,
                run_subprocess=run_subprocess,
            ),
            "git_diff": make_git_diff_handler(
                self.work_root,
                command_timeout=command_timeout,
                max_text_length=max_text_length,
                run_subprocess=run_subprocess,
            ),
            "web_search": make_web_search_handler(str(self.work_root)),
            "web_fetch": make_web_fetch_handler(str(self.work_root)),
            "browser_check": make_browser_check_handler(str(self.work_root)),
            "mcp_tool": call_mcp,
            SUB_AGENT_TOOL_NAME: call_sub_agent,
            "write_checklist": _write_checklist_handler,
            "update_checklist": _update_checklist_handler,
        }
        if operation_executor is not None:
            handlers.update(durable_tool_handlers(operation_executor, work_root=self.work_root))
        return handlers


def build_core_toolbox(**kwargs: Any) -> CoreToolbox:
    return CoreToolbox(**kwargs)


def _default_display(category: str) -> dict[str, Any]:
    card_by_category = {
        "file_read": "file",
        "file_write": "diff",
        "command": "command",
        "git": "diff",
        "web": "web",
        "browser": "browser",
        "skill": "skill",
        "mcp": "tool",
        "control": "checklist",
    }
    return {
        "card": card_by_category.get(category, "tool"),
        "default_collapsed": category in {"mcp"},
    }


__all__ = [
    "CoreToolbox",
    "DEFAULT_COMMAND_TIMEOUT",
    "DEFAULT_TOOL_CATEGORIES",
    "DEFAULT_TOOL_FAILURE_MODES",
    "DEFAULT_TOOL_ORDER",
    "DEFAULT_TOOL_PERMISSIONS",
    "DEFAULT_TOOL_RECOVERY",
    "SubAgentRunner",
    "build_core_toolbox",
    "core_model_tools",
    "default_core_tool_specs",
    "strict_tool_schema",
]
