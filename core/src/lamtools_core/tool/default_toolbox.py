from __future__ import annotations

import json
import logging
import inspect
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal, Mapping, Protocol, runtime_checkable

from lamtools_core.event import CoreEvent
from lamtools_core.agent import (
    SUB_AGENT_MESSAGE_TOOL_NAME,
    SUB_AGENT_MESSAGE_TOOL_SPEC,
    SUB_AGENT_TOOL_NAME,
    SUB_AGENT_TOOL_SPEC,
    SubAgentRunResult,
)
from lamtools_core.llm import normalize_reasoning_level, reasoning_level_from_legacy
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
from lamtools_core.tool.image_tools import make_generate_image_handler
from lamtools_core.tool.mcp_tools import MCPToolCaller, execute_mcp_tool_call
from lamtools_core.tool.outside_access import (
    GRANT_METADATA_KEY,
    call_has_outside_grant,
    outside_access_grant,
    outside_access_granted,
)
from lamtools_core.tool.memory_tools import (
    MEMORY_TOOL_DESCRIPTION,
    MEMORY_TOOL_NAME,
    MEMORY_TOOL_SCHEMA,
    make_memory_handler,
)
from lamtools_core.tool.library_tools import (
    LIBRARY_TOOL_DESCRIPTION,
    LIBRARY_TOOL_NAME,
    LIBRARY_TOOL_SCHEMA,
    make_library_handler,
)
from lamtools_core.tool.permission import ASK_USER, AUTO_ALLOW, HARD_BLOCK, PermissionTier
from lamtools_core.tool.web_tools import make_web_fetch_handler
from lamtools_core.tool.search import build_web_search_handler
from lamtools_core.tool.workspace_files import (
    DEFAULT_MAX_LIST_ITEMS,
    DEFAULT_MAX_SEARCH_RESULTS,
    DEFAULT_MAX_TEXT_LENGTH,
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

_logger = logging.getLogger(__name__)


_WORKFLOW_CONTEXT_METADATA_KEYS = (
    "parent_session_id",
    "parent_run_id",
    "parent_turn_id",
    "parent_call_id",
    "cwd",
    "pause_on_cancel",
    "permissions",
    "runtime_permissions",
    "event_metadata",
    "attachments",
    "runtime_snapshot",
    "snapshot",
    "environment",
    "capabilities",
    "trace_id",
    "traceId",
    "correlation_id",
    "actor_id",
    "actor_kind",
    "lineage",
    "parent_lineage",
    "workflow_stack",
    "active_workflows",
    "depth",
    "nesting_depth",
    "max_depth",
    "max_nesting_depth",
)


def _workflow_context_from_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Extract the serializable workflow envelope from a ToolCall.

    Tool metadata is the only stable hand-off available to handlers assembled
    dynamically by the workflow plugin.  Keep this extraction tolerant of
    both nested and flattened forms while excluding unrelated provider data.
    """
    nested = metadata.get("execution_context", metadata.get("workflow_execution"))
    if callable(getattr(nested, "metadata", None)):
        try:
            nested = nested.metadata()
        except Exception:  # noqa: BLE001 - optional context cannot block a tool
            nested = None
    result = deepcopy(dict(nested)) if isinstance(nested, Mapping) else {}
    for key in _WORKFLOW_CONTEXT_METADATA_KEYS:
        if key in metadata:
            result[key] = deepcopy(metadata[key])
    return result


def _missing_dependency_handler(tool_name: str, error: str) -> ToolHandler:
    """依赖缺失占位 handler：返回明确错误（附安装命令），不静默降级。"""

    async def handler(call: ToolCall) -> ToolResult:
        return ToolResult(
            call_id=call.id,
            name=call.name,
            status="failed",
            error=error,
            content=f"MISSING DEPENDENCIES: {error}",
            metadata={"error_type": "missing_plugin_dependencies"},
        )

    return handler


@runtime_checkable
class SubAgentRunner(Protocol):
    async def run(
        self,
        *,
        task: str,
        agent: str = "",
        model: str = "",
        mode: str = "",
        attachments: list[str] | None = None,
        parent_call_id: str = "",
        parent_run_id: str = "",
        parent_turn_id: str = "",
        execution_context: Any | None = None,
    ) -> SubAgentRunResult | str: ...

DEFAULT_COMMAND_TIMEOUT = 120


DEFAULT_TOOL_PERMISSIONS: dict[str, PermissionTier] = {
    "read_file": AUTO_ALLOW,
    "list_dir": AUTO_ALLOW,
    "search_files": AUTO_ALLOW,
    "search_content": AUTO_ALLOW,
    "load_skill": AUTO_ALLOW,
    MEMORY_TOOL_NAME: AUTO_ALLOW,
    LIBRARY_TOOL_NAME: AUTO_ALLOW,
    "write_file": ASK_USER,
    "edit_file": ASK_USER,
    "run_command": ASK_USER,
    "list_processes": AUTO_ALLOW,
    "kill_process": AUTO_ALLOW,
    "git_status": AUTO_ALLOW,
    "git_diff": AUTO_ALLOW,
    "web_search": AUTO_ALLOW,
    "web_fetch": ASK_USER,
    "generate_image": ASK_USER,
    "mcp_tool": ASK_USER,
    "mcp_activate": AUTO_ALLOW,
    SUB_AGENT_TOOL_NAME: AUTO_ALLOW,
    SUB_AGENT_MESSAGE_TOOL_NAME: AUTO_ALLOW,
    "write_checklist": AUTO_ALLOW,
    "update_checklist": AUTO_ALLOW,
    "question": ASK_USER,
}


DEFAULT_TOOL_ORDER: tuple[str, ...] = (
    "read_file",
    "list_dir",
    "search_files",
    "search_content",
    "load_skill",
    MEMORY_TOOL_NAME,
    LIBRARY_TOOL_NAME,
    "write_file",
    "edit_file",
    "run_command",
    "list_processes",
    "kill_process",
    "git_status",
    "git_diff",
    "web_search",
    "web_fetch",
    "generate_image",
    "mcp_activate",
    "mcp_tool",
    SUB_AGENT_TOOL_NAME,
    SUB_AGENT_MESSAGE_TOOL_NAME,
    "write_checklist",
    "update_checklist",
    "question",
)


DEFAULT_TOOL_CATEGORIES: dict[str, str] = {
    "read_file": "file_read",
    "list_dir": "file_read",
    "search_files": "file_read",
    "search_content": "file_read",
    "load_skill": "skill",
    MEMORY_TOOL_NAME: "memory",
    LIBRARY_TOOL_NAME: "library",
    "write_file": "file_write",
    "edit_file": "file_write",
    "run_command": "command",
    "list_processes": "command",
    "kill_process": "command",
    "git_status": "git",
    "git_diff": "git",
    "web_search": "web",
    "web_fetch": "web",
    "generate_image": "image",
    "mcp_tool": "mcp",
    "mcp_activate": "mcp",
    SUB_AGENT_TOOL_NAME: "agent",
    SUB_AGENT_MESSAGE_TOOL_NAME: "agent",
    "write_checklist": "control",
    "update_checklist": "control",
    "question": "control",
}


DEFAULT_TOOL_FAILURE_MODES: dict[str, list[dict[str, str]]] = {
    "read_file": [
        {"type": "missing_argument", "message": "Required argument is missing"},
        {"type": "invalid_argument", "message": "Argument has an invalid type or value"},
        {"type": "path_outside_root", "message": "Blocked: path is outside work_root"},
        {"type": "file_not_found", "message": "File not found"},
        {"type": "invalid_utf8", "message": "File is not valid UTF-8"},
        {"type": "read_failed", "message": "Error reading file"},
        {"type": "read_error", "message": "Error reading file"},
    ],
    "write_file": [
        {"type": "missing_argument", "message": "Required argument is missing"},
        {"type": "invalid_argument", "message": "Argument has an invalid type or value"},
        {"type": "path_outside_root", "message": "Blocked: path is outside work_root"},
        {"type": "sensitive_pattern", "message": "Blocked: path contains sensitive pattern"},
        {"type": "file_already_exists", "message": "File already exists"},
        {"type": "file_not_found", "message": "File not found"},
        {"type": "file_version_changed", "message": "The file changed since it was read"},
        {"type": "invalid_utf8", "message": "Content is not valid UTF-8"},
        {"type": "write_rejected", "message": "WRITE REJECTED: {reason}"},
    ],
    "edit_file": [
        {"type": "missing_argument", "message": "Required argument is missing"},
        {"type": "invalid_argument", "message": "Argument has an invalid type or value"},
        {"type": "old_string_empty", "message": "old_string is empty"},
        {"type": "file_not_found", "message": "File not found"},
        {"type": "old_string_not_found", "message": "old_string not found in file"},
        {"type": "ambiguous_match", "message": "old_string matched more than once"},
        {"type": "context_mismatch", "message": "Edit context did not match"},
        {"type": "content_version_changed", "message": "The selected content changed"},
        {"type": "file_version_changed", "message": "The file changed since it was read"},
        {"type": "invalid_utf8", "message": "File or replacement is not valid UTF-8"},
        {"type": "path_outside_root", "message": "Blocked: path is outside work_root"},
        {"type": "sensitive_pattern", "message": "Blocked: path contains sensitive pattern"},
        {"type": "edit_rejected", "message": "EDIT REJECTED: {reason}"},
    ],
    "memory": [],
    LIBRARY_TOOL_NAME: [
        {"type": "missing_argument", "message": "Required argument is missing"},
        {"type": "invalid_argument", "message": "Argument has an invalid type or value"},
        {"type": "path_outside_root", "message": "Blocked: path is outside work_root"},
        {"type": "file_not_found", "message": "File not found"},
        {"type": "entry_not_found", "message": "Library entry not found"},
        {"type": "project_not_found", "message": "No project is bound to the current workspace"},
        {"type": "library_unavailable", "message": "The library catalog is unavailable"},
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
    "web_search": [{"type": "search_failed", "message": "Web search failed"}],
    "web_fetch": [
        {"type": "fetch_failed", "message": "Failed to fetch URL"},
        {"type": "invalid_url", "message": "Invalid URL"},
        {"type": "expected_text_missing", "message": "Expected text not found in fetched content"},
    ],
    "generate_image": [
        {"type": "missing_image_provider", "message": "生图未配置：请在设置 → 生图中配置 API 地址"},
        {"type": "api_timeout", "message": "生图 API 超时（生成较慢可稍后重试）"},
        {"type": "api_error", "message": "生图 API 请求失败: {reason}"},
        {"type": "no_image_in_response", "message": "生图响应中没有解析出图片"},
        {"type": "reference_missing", "message": "参考图文件不存在: {path}"},
    ],
    "mcp_activate": [
        {"type": "server_not_found", "message": "MCP server not found"},
    ],
    "mcp_tool": [
        {"type": "mcp_error", "message": "MCP TOOL ERROR: {reason}"},
        {"type": "tool_not_found", "message": "MCP tool not found"},
    ],
    "question": [],
}


DEFAULT_TOOL_RECOVERY: dict[str, str] = {
    "read_file": "Check path exists, use list_dir to find correct path",
    "write_file": "Check path bounds and content; on file_version_changed, re-read before retrying",
    "edit_file": "Read file first; on a version or match conflict, re-read and use exact context or occurrence",
    "memory": "List the tier first; paths are relative to the memory root and INDEX.md is generated and read-only",
    LIBRARY_TOOL_NAME: "List the library first and use the returned entry ids; layers follow the project's existing folders",
    "search_content": "Use an exact substring from the file or narrow the search path",
    "run_command": (
        "Fix command syntax, check platform compatibility, or increase timeout. For local preview servers, use "
        "recommended_action from tool metadata; for port_in_use choose a free port instead of retrying the same command."
    ),
    "list_processes": "Use a returned pid with kill_process; log paths point at the workspace background log directory",
    "kill_process": "Only pids from list_processes can be terminated; a not_owned result means the process predates the last backend restart",
    "web_search": "Retry with simpler query, try different search terms",
    "web_fetch": "Check URL validity, try alternative URL",
    "generate_image": (
        "Check 设置 → 生图 已启用且 API 地址正确；生成较慢可重试；参考图需为可访问 URL 或工作区内文件"
    ),
    "mcp_activate": "Check the server name against available MCP servers; use exact names listed in the system prompt.",
    "mcp_tool": "Check tool name and arguments, verify MCP server status",
    "question": "Rephrase the question, simplify options, or proceed with a reasonable default",
}


DEFAULT_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "status": {"type": "string", "enum": ["ok", "failed", "skipped", "blocked"]},
        "content": {"type": "string"},
        "error": {"type": "string"},
        "error_code": {"type": "string"},
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
            "to Markdown and labeled as untrusted content. "
            "Image files (PNG/JPG/JPEG/GIF/WebP/AVIF/BMP) are returned as an image the model can view directly."
        ),
        "input_schema": _schema(
            {"path": {"type": "string", "description": "File path relative to the workspace"}},
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
            "for small changes to existing files. Writes are UTF-8, newline-preserving, and atomic. "
            "Use expected_file_hash for optimistic concurrency; use must_not_exist to create without overwriting."
        ),
        "input_schema": _schema(
            {
                "path": {"type": "string", "description": "File path relative to the workspace"},
                "content": {"type": "string", "description": "File content to write"},
                "expected_file_hash": {
                    "type": ["string", "null"],
                    "description": "Expected full-file sha256:... hash, or null for no version check",
                },
                "must_not_exist": {
                    "type": ["boolean", "null"],
                    "description": "When true, fail if the target already exists; otherwise use null",
                },
            },
            ["path", "content"],
        ),
    },
    {
        "name": "edit_file",
        "description": (
            "Replace one exact UTF-8 text segment in an existing file. Matching is case-sensitive and preserves "
            "all whitespace and line endings. The edit must be unique unless occurrence (1-based) or exact "
            "before_context/after_context makes it unique; never guess among multiple matches. "
            "When no context constraint is needed, omit those fields or pass JSON null without quotes; the "
            "string \"null\" is treated as four literal characters."
        ),
        "input_schema": _schema(
            {
                "path": {"type": "string", "description": "File path relative to the workspace"},
                "old_string": {"type": "string", "description": "Exact text to replace"},
                "new_string": {"type": "string", "description": "Replacement text"},
                "expected_file_hash": {
                    "type": ["string", "null"],
                    "description": "Expected full-file sha256:... hash, or null for no full-file check",
                },
                "occurrence": {
                    "type": ["integer", "null"],
                    "description": "Optional 1-based occurrence after context filtering",
                },
                "before_context": {
                    "type": ["string", "null"],
                    "description": (
                        "Exact text immediately before old_string, or JSON null (without quotes) when unused; "
                        "the string \"null\" is literal text"
                    ),
                },
                "after_context": {
                    "type": ["string", "null"],
                    "description": (
                        "Exact text immediately after old_string, or JSON null (without quotes) when unused; "
                        "the string \"null\" is literal text"
                    ),
                },
                "expected_content_hash": {
                    "type": ["string", "null"],
                    "description": (
                        "Expected sha256:... hash of the selected old_string plus any supplied contexts, or null"
                    ),
                },
            },
            ["path", "old_string", "new_string"],
        ),
    },
    {
        "name": MEMORY_TOOL_NAME,
        "description": MEMORY_TOOL_DESCRIPTION,
        "input_schema": MEMORY_TOOL_SCHEMA,
    },
    {
        "name": LIBRARY_TOOL_NAME,
        "description": LIBRARY_TOOL_DESCRIPTION,
        "input_schema": LIBRARY_TOOL_SCHEMA,
    },
    {
        "name": "run_command",
        "description": (
            "Run a shell command inside the workspace. Servers and watchers must use background=true; "
            "do not append &, nohup, or start. Results separately report process_state, shell_state, "
            "and readiness_state. persistent=true (together with background=true) registers a long-lived "
            "process that survives turn end; check it with list_processes and terminate it with kill_process."
        ),
        "input_schema": _schema(
            {
                "command": {"type": "string", "description": "Command to run"},
                "timeout": {"type": "integer", "description": "Timeout in seconds"},
                "background": {
                    "type": "boolean",
                    "description": "Start a server/watcher as a tracked background process instead of shell-level detachment",
                },
                "persistent": {
                    "type": "boolean",
                    "description": "Register the background process as long-lived: it survives turn end, shows in the session process list, and keeps running until killed or the app exits",
                },
                "readiness_url": {
                    "type": ["string", "null"],
                    "description": (
                        "HTTP URL to check when background=true; omit it or pass JSON null (without quotes) "
                        "for commands that are not servers"
                    ),
                },
                "readiness_text": {
                    "type": ["string", "null"],
                    "description": (
                        "Optional text expected at readiness_url; omit it or pass JSON null (without quotes) "
                        "when unused"
                    ),
                },
            },
            ["command"],
        ),
    },
    {
        "name": "list_processes",
        "description": (
            "List background processes registered for this session, including long-lived ones that keep "
            "running after the turn ends. Returns pid, liveness, command and log paths."
        ),
        "input_schema": _schema({}),
    },
    {
        "name": "kill_process",
        "description": (
            "Terminate a background process that was started in this session. The pid must be registered "
            "in this session's process list; unrelated processes cannot be terminated."
        ),
        "input_schema": _schema(
            {"pid": {"type": "integer", "description": "Process id from list_processes"}},
            ["pid"],
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
        "description": "Search web pages or image results. Image results include an HTTPS image URL and its source page for verification and attribution.",
        "input_schema": _schema(
            {
                "query": {
                    "type": "string",
                    "description": (
                        "Precise search query. For images, name the exact subject, concept, artifact type, "
                        "and useful domain/standard terms; result relevance is judged by the model."
                    ),
                },
                "limit": {"type": "integer", "description": "Maximum result count"},
                "domains": {"type": "array", "items": {"type": "string"}, "description": "Domain filter"},
                "search_type": {
                    "type": "string",
                    "enum": ["web", "image"],
                    "description": (
                        "Use 'image' for source-backed picture candidates; the provider does not "
                        "semantically filter them, so inspect title, source page, and image URL. Defaults to 'web'."
                    ),
                },
                "provider": {"type": "string", "description": "Optional search provider override"},
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
        "name": "generate_image",
        "description": (
            "调用生图 API 生成或编辑图片。无 reference_urls 时按提示词文生图（可一次生成多张）；"
            "带 reference_urls（可访问的图片 URL 或工作区内图片路径）时走参考图编辑模式，"
            "参考图作为输入、生成其编辑/变体。图片保存到 .lam/artifacts/images/ 并在界面中预览；"
            "如需把图片转存到正常工作区，可后续用 run_command 复制。"
        ),
        "input_schema": _schema(
            {
                "prompt": {"type": "string", "description": "生图提示词，描述期望的画面内容（英文效果更佳）"},
                "count": {
                    "type": "integer",
                    "description": "生成图片数量，默认 1，最多 4（仅文生图模式生效）",
                },
                "size": {
                    "type": "string",
                    "description": "图片尺寸，默认 1024x1024",
                },
                "reference_urls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "可选参考图列表（http(s) URL 或工作区内相对路径），提供时走参考图编辑模式",
                },
            },
            ["prompt"],
        ),
    },
    {
        "name": "mcp_activate",
        "description": (
            "Activate an MCP (Model Context Protocol) tool server to gain access to its full tool set. "
            "Call this first when you need browser automation or other MCP-provided tools. "
            "The server's full tool definitions will be available on the next turn. "
            "Returns a complete list of available tools from that server."
        ),
        "input_schema": _schema(
            {"server_name": {"type": "string", "description": "Name of the MCP server to activate (e.g. 'playwright')"}},
            ["server_name"],
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
            "Optionally create the main agent's planning/progress checklist for the task; simple tasks may skip it. "
            "For complex tasks, use 3-7 non-overlapping steps. Each step's deliverables must be verifiable "
            "sub-items. Sub-agents should focus on their delegated task and return evidence. Each step becomes a "
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
                    "description": "Files or deliverables expected to change; omit for tasks with no file outputs.",
                },
                "steps": {
                    "type": "array",
                    "description": "Ordered, non-overlapping checklist items. Use 3-7 concrete steps for complex tasks; simple tasks may skip the checklist.",
                    "items": _schema(
                        {
                            "id": {"type": "string", "description": "Stable id like s1, s2, s3."},
                            "description": {"type": "string", "description": "User-readable action item."},
                            "deliverables": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Verifiable sub-items produced by this step.",
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
    {
        "name": "question",
        "description": (
            "Ask the user a question or request confirmation when you need "
            "clarification, a decision between options, or explicit approval "
            "before proceeding. The run pauses until the user responds."
        ),
        "input_schema": _schema(
            {
                "question": {
                    "type": "string",
                    "description": "The question or confirmation prompt to present to the user.",
                },
                "options": {
                    "type": "array",
                    "description": "Selectable choices. Omit for a simple confirm/deny question.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string", "description": "Short option label."},
                            "description": {"type": "string", "description": "Optional detail."},
                        },
                        "required": ["label"],
                    },
                },
                "context": {
                    "type": "string",
                    "description": "Optional context or background for the question.",
                },
            },
            ["question"],
        ),
    },
    deepcopy(SUB_AGENT_TOOL_SPEC),
    deepcopy(SUB_AGENT_MESSAGE_TOOL_SPEC),
)


# S3 共识（D2）：git/websearch/imagegen 三个内置插件的工具声明外移，
# handler 留在 core、按名由 core 显式装配。以下 4 个工具不再由
# default_core_tool_specs() 输出（基础集 = 15），常量定义保留——
# 内置插件 tools.jsonc 半声明式引用（bundled_core_tool_specs 补全）。
_BUNDLED_PLUGIN_TOOL_NAMES = frozenset({"git_status", "git_diff", "web_search", "generate_image"})


def _core_spec_for(name: str) -> ToolSpec:
    item = {str(i["name"]): i for i in DEFAULT_TOOL_DEFINITIONS}[name]
    category = DEFAULT_TOOL_CATEGORIES[name]
    return ToolSpec(
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


def default_core_tool_specs() -> list[ToolSpec]:
    return [
        _core_spec_for(name)
        for name in DEFAULT_TOOL_ORDER
        if name not in _BUNDLED_PLUGIN_TOOL_NAMES
    ]


def bundled_core_tool_specs() -> list[ToolSpec]:
    """内置插件（git/websearch/imagegen）的 core 侧 spec 常量。

    供内置插件 tools.jsonc 半声明式补全（description/input_schema 按名
    引用）；基础集装配不含它们。
    """
    return [_core_spec_for(name) for name in DEFAULT_TOOL_ORDER if name in _BUNDLED_PLUGIN_TOOL_NAMES]


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
                    # Every model-facing function is advertised as strict.
                    # Normalize injected, durable, and plugin schemas here as well
                    # as the built-in schemas so every property is required,
                    # optional values are nullable, and objects reject extras.
                    "parameters": strict_tool_schema(spec.input_schema),
                },
            }
        )
    return tools


def strict_tool_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Normalize a tool input schema for strict function calling.

    Strict function schemas require every object to close its properties and
    every declared property to be required.  Tool sources are intentionally
    allowed to use ordinary JSON Schema (including optional fields), so this
    adapter also converts optional fields to nullable fields.  The final
    normalization is the single guard for built-in, plugin, MCP, and durable
    tools.
    """

    normalized = deepcopy(schema) if isinstance(schema, dict) else {}

    def allow_null(node: dict[str, Any]) -> None:
        schema_type = node.get("type")
        if isinstance(schema_type, str):
            if schema_type != "null":
                node["type"] = [schema_type, "null"]
        elif isinstance(schema_type, list):
            if "null" not in schema_type:
                node["type"] = [*schema_type, "null"]
        elif isinstance(node.get("anyOf"), list):
            branches = node["anyOf"]
            if not any(
                isinstance(branch, dict)
                and (
                    branch.get("type") == "null"
                    or (
                        isinstance(branch.get("type"), list)
                        and "null" in branch["type"]
                    )
                )
                for branch in branches
            ):
                branches.append({"type": "null"})
        elif "$ref" in node:
            original = deepcopy(node)
            node.clear()
            node["anyOf"] = [original, {"type": "null"}]
        else:
            # A property without a type is not a valid strict schema.  Use a
            # scalar fallback for third-party/generic declarations; schemas
            # that genuinely need other types declare them explicitly.
            node["type"] = ["string", "null"]

    def infer_type(node: dict[str, Any]) -> None:
        schema_type = node.get("type")
        if isinstance(schema_type, (str, list)):
            return
        if "properties" in node:
            node["type"] = "object"
        elif "items" in node:
            node["type"] = "array"
        elif isinstance(node.get("anyOf"), list) or "$ref" in node:
            # anyOf/$ref are valid schema forms without a sibling type.
            return
        else:
            # enum-only and empty third-party leaf schemas both need a type.
            node["type"] = "string"

    def is_object(node: dict[str, Any]) -> bool:
        schema_type = node.get("type")
        return (
            schema_type == "object"
            or (isinstance(schema_type, list) and "object" in schema_type)
            or "properties" in node
        )

    def is_array(node: dict[str, Any]) -> bool:
        schema_type = node.get("type")
        return schema_type == "array" or (
            isinstance(schema_type, list) and "array" in schema_type
        )

    def visit(node: dict[str, Any]) -> None:
        if not isinstance(node, dict):
            return

        # OpenAI strict mode supports anyOf but not oneOf.  No current core
        # schema emits oneOf, yet normalizing it here keeps plugin schemas from
        # being able to reintroduce an unsupported composition keyword.
        if "oneOf" in node and "anyOf" not in node:
            node["anyOf"] = node.pop("oneOf")

        branches = node.get("anyOf")
        if isinstance(branches, list):
            for branch in branches:
                if isinstance(branch, dict):
                    visit(branch)

        definitions = node.get("$defs")
        if isinstance(definitions, dict):
            for definition in definitions.values():
                if isinstance(definition, dict):
                    visit(definition)

        infer_type(node)
        if is_object(node):
            properties = node.get("properties")
            if not isinstance(properties, dict):
                properties = {}
                node["properties"] = properties
            originally_required = set(node.get("required") or [])
            for key, child in list(properties.items()):
                if not isinstance(child, dict):
                    child = {}
                    properties[key] = child
                visit(child)
                if key not in originally_required:
                    allow_null(child)
            node["required"] = list(properties.keys())
            node["additionalProperties"] = False
        elif is_array(node):
            items = node.get("items")
            if not isinstance(items, dict):
                # Strict validators require an item schema for model-facing
                # arrays.  Keep the fallback concrete and nullable-safe.
                node["items"] = {"type": "string"}
            else:
                visit(items)

    root_type = normalized.get("type")
    root_is_object = (
        root_type == "object"
        or (isinstance(root_type, list) and "object" in root_type)
        or "properties" in normalized
    )
    if not root_is_object:
        # Function parameters must always be a root object.  A malformed or
        # generic plugin declaration must not turn the whole parameters node
        # into a scalar/anyOf schema and make the API reject the request.
        description = normalized.get("description")
        normalized = {"type": "object", "properties": {}}
        if description:
            normalized["description"] = description
    visit(normalized)
    return normalized


async def _write_checklist_handler(call: ToolCall) -> ToolResult:
    args = call.arguments if isinstance(call.arguments, dict) else {}
    raw_files = args.get("files")
    files = [str(item) for item in raw_files] if isinstance(raw_files, list) else []
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


async def _question_handler(call: ToolCall) -> ToolResult:
    """Defensive fallback for the question tool.

    Under normal operation the approval gate pauses the run before this
    handler is reached, and the user's answer is injected as the tool result
    by the approval-respond flow. This handler only runs when
    ``approval_policy='auto_approve'`` bypasses the gate — in that case we
    return a placeholder so the model knows no real user answer was collected.
    """
    args = call.arguments if isinstance(call.arguments, dict) else {}
    question = str(args.get("question") or "")
    return ToolResult(
        call_id=call.id,
        name=call.name,
        status="ok",
        content=(
            "Question was auto-approved without user input."
            + (f" The question was: {question}" if question else "")
            + " No user answer was collected."
        ),
        metadata={"auto_approved": True},
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
        imagegen_config: dict | None = None,
        active_tier: "PermissionMode | None" = None,
        tier_tools: "TierTools | None" = None,
        load_tools: LoadTools | None = None,
        active_mode: str | None = None,
        activated_mcp_servers: set[str] | None = None,
        plugin_tool_providers: list[Callable[..., Any]] | None = None,
        allow_access_outside_workdir: bool = False,
        runtime_permissions_provider: Callable[[], Mapping[str, Any] | None] | None = None,
        plugin_tool_specs: list[ToolSpec] | None = None,
        plugin_tool_handlers: dict[str, ToolHandler] | None = None,
        plugin_mode_tool_sets: dict[str, set[str]] | None = None,
        plugin_availability: Callable[[str], bool] | None = None,
        skill_state_store: Any | None = None,
        permission_overrides: dict[str, str] | None = None,
        enable_plugin_manager: bool = False,
        data_dir: str | Path | None = None,
        artifact_store: Any | None = None,
    ) -> None:
        self.work_root = Path(work_root).resolve()
        self.work_root.mkdir(parents=True, exist_ok=True)
        if loaded_skill_roots is None and skill_registry is None:
            from lamtools_core.skill_runtime import create_skill_runtime

            skill_runtime = create_skill_runtime()
            self.loaded_skill_roots = set(skill_runtime.roots)
            skill_registry = skill_runtime.registry
        else:
            self.loaded_skill_roots = {Path(item).resolve() for item in loaded_skill_roots or set()}
        self.loaded_skill_names: set[str] = set()
        self.mcp_caller = mcp_caller
        self.sub_agent_runner = sub_agent_runner
        self._failed_sub_agent_calls: dict[tuple[str, str], dict[str, Any]] = {}
        self.approval_policy = approval_policy
        self.active_tier = active_tier
        self.tier_tools = tier_tools
        self.disabled_tools = set(disabled_tools or set())
        self.load_tools = load_tools or {}
        self.active_mode = active_mode
        self.activated_mcp_servers = activated_mcp_servers or set()
        self.imagegen_config = imagegen_config
        self.tool_permissions = dict(DEFAULT_TOOL_PERMISSIONS)
        # Manifest permissions are a separate authority from user overrides.
        # In particular, a manifest hard_block must remain present even when
        # the corresponding ToolSpec is intentionally hidden from the model.
        self.manifest_tool_permissions: dict[str, PermissionTier] = {}
        self.manifest_hard_block_tools: set[str] = set()
        self.skill_registry = skill_registry or SkillRegistry(explicit_roots=self.loaded_skill_roots)
        self.skill_state_store = skill_state_store
        self.data_dir = Path(data_dir) if data_dir else None
        # 项目资料库的存储句柄：library 工具经它整理当前项目的成果目录。
        self.artifact_store = artifact_store
        # Generic plugin contributions. Plugin implementations are discovered
        # and supplied by the host's plugin assembly; Core does not name a
        # concrete plugin here.
        self.plugin_tool_providers = list(plugin_tool_providers or [])
        self.plugin_tool_handlers = dict(plugin_tool_handlers or {})
        self.plugin_availability = plugin_availability
        self.plugin_mode_tool_sets = {
            str(mode): {str(name) for name in names}
            for mode, names in (plugin_mode_tool_sets or {}).items()
        }
        self.allow_access_outside_workdir = allow_access_outside_workdir
        self.runtime_permissions_provider = runtime_permissions_provider
        # B8 共识：工具名全局唯一——与已注入工具（基础/MCP/durable）同名
        # 的插件工具报不可用；插件之间同名同样互斥
        # （先声明的保留，后者报冲突）。bundled_core_tool_specs 是内置
        # 插件自己的补全源，不算冲突（内置插件工具经装配注入）。
        self.plugin_tool_specs = list(plugin_tool_specs or [])
        self._plugin_handler_errors: dict[str, str] = {}
        self._plugin_conflicts: dict[str, str] = {}
        core_spec_names = {
            spec.name for spec in default_core_tool_specs()
        } | {spec.name for spec in mcp_tool_specs or []} | {
            spec.name for spec in durable_tool_specs(
                goal=enable_goal_tool and operation_executor is not None,
                arrange=enable_arrange_tool and operation_executor is not None,
            )
        }
        resolved_plugin_specs: list[ToolSpec] = []
        plugin_seen: dict[str, str] = {}
        for spec in self.plugin_tool_specs:
            if spec.name not in self.manifest_tool_permissions:
                self.manifest_tool_permissions[spec.name] = spec.permission  # type: ignore[assignment]
            if spec.permission == HARD_BLOCK:
                self.manifest_hard_block_tools.add(spec.name)
                self.tool_permissions[spec.name] = HARD_BLOCK
            if spec.name in core_spec_names:
                self._plugin_conflicts[spec.name] = (
                    f"tool name '{spec.name}' conflicts with a core tool"
                )
                continue
            if spec.name in plugin_seen:
                self._plugin_conflicts[spec.name] = (
                    f"tool name '{spec.name}' also declared by plugin "
                    f"'{plugin_seen[spec.name]}'"
                )
                continue
            plugin_seen[spec.name] = str(spec.metadata.get("plugin", ""))
            if spec.permission == HARD_BLOCK:
                # 与 MCP 先例同语义：hard_block 工具不注入 spec（模型不可见、
                # 执行走 Unknown tool），权限映射仍记录供 ApprovalGate 兜底。
                self._plugin_conflicts[spec.name] = "tool is hard_blocked by manifest"
                continue
            resolved_plugin_specs.append(spec)
        self.plugin_tool_specs = resolved_plugin_specs
        self._plugin_timeouts: dict[str, float] = {
            spec.name: float(spec.metadata["timeout"])
            for spec in self.plugin_tool_specs
            if spec.metadata.get("timeout") is not None
        }
        self._dynamic_mcp_tool_names = {spec.name for spec in mcp_tool_specs or [] if spec.name.startswith("mcp__")}
        for spec in mcp_tool_specs or []:
            self.tool_permissions[spec.name] = spec.permission  # type: ignore[assignment]
        durable_specs = durable_tool_specs(
            goal=enable_goal_tool and operation_executor is not None,
            arrange=enable_arrange_tool and operation_executor is not None,
        )
        for spec in durable_specs:
            self.tool_permissions[spec.name] = spec.permission  # type: ignore[assignment]
        for spec in self.plugin_tool_specs:
            self.tool_permissions[spec.name] = spec.permission  # type: ignore[assignment]
        from lamtools_core.plugins.manager_tools import plugin_manager_tool_specs

        plugin_manager_specs = (
            plugin_manager_tool_specs() if (enable_plugin_manager and operation_executor is not None) else []
        )
        for spec in plugin_manager_specs:
            self.tool_permissions[spec.name] = spec.permission  # type: ignore[assignment]
        for name in self.disabled_tools:
            self.tool_permissions[name] = HARD_BLOCK
        # 用户权限覆盖（E3 共识：用户可升降级插件工具 permission）。
        # 不覆盖显式 disabled 的工具——禁用语义优先于覆盖。
        for name, tier in (permission_overrides or {}).items():
            if name in self.disabled_tools or name in self.manifest_tool_permissions:
                continue
            self.tool_permissions[name] = tier  # type: ignore[assignment]
        # Dynamic plugin specs declare their own permission; prime
        # the permission map BEFORE the approval gate snapshots it, so those
        # tools are gated per declaration instead of defaulting to HARD_BLOCK.
        self._dynamic_plugin_specs()
        self.approval_gate = ApprovalGate(
            work_root=self.work_root,
            tool_permissions=self.tool_permissions,
            command_policies=command_policies,
            active_tier=active_tier,
            tier_tools=tier_tools,
            allow_access_outside_workdir=allow_access_outside_workdir,
            approval_policy=approval_policy,
            manifest_tool_permissions=self.manifest_tool_permissions,
            manifest_hard_block_tools=self.manifest_hard_block_tools | self.disabled_tools,
            # A loaded skill folder is granted scope: its assets are not a
            # consent question (the skill body is what pointed at them).
            resource_roots=lambda: tuple(self.loaded_skill_roots),
        )
        self._specs = [
            *default_core_tool_specs(),
            *list(mcp_tool_specs or []),
            *durable_specs,
            *plugin_manager_specs,
            *self.plugin_tool_specs,
        ]
        self._handlers = self._build_handlers(
            command_timeout=command_timeout,
            max_list_items=max_list_items,
            max_text_length=max_text_length,
            max_search_results=max_search_results,
            core_event_callback=core_event_callback,
            operation_executor=operation_executor,
            imagegen_config=imagegen_config,
            allow_access_outside_workdir=allow_access_outside_workdir,
            plugin_tool_specs=self.plugin_tool_specs,
            plugin_manager_specs=plugin_manager_specs,
        )

    @staticmethod
    def _invoke_plugin_provider(provider: Callable[..., Any], work_root: Path) -> Any:
        """Ask a plugin provider for the current project-scoped bundle.

        Providers written before project-scoped plugin contexts were added are
        still zero-argument callables. Signature inspection keeps those
        providers compatible while allowing long-lived runtimes to receive the
        active root on every toolbox refresh.
        """
        try:
            parameters = inspect.signature(provider).parameters
        except (TypeError, ValueError):
            parameters = {}
        work_root_parameter = parameters.get("work_root")
        accepts_kwargs = any(
            item.kind == inspect.Parameter.VAR_KEYWORD
            for item in parameters.values()
        )
        if work_root_parameter is not None and work_root_parameter.kind != inspect.Parameter.POSITIONAL_ONLY:
            return provider(work_root=str(work_root))
        if accepts_kwargs:
            return provider(work_root=str(work_root))
        if work_root_parameter is not None:
            return provider(str(work_root))
        return provider()

    @staticmethod
    def _call_work_root(call: ToolCall, fallback: Path) -> Path:
        metadata = call.metadata if isinstance(call.metadata, dict) else {}
        raw = metadata.get("work_root")
        if raw:
            try:
                return Path(str(raw)).expanduser().resolve()
            except OSError:
                pass
        return fallback

    def _dynamic_plugin_specs(self, *, work_root: Path | None = None) -> list[ToolSpec]:
        specs: list[ToolSpec] = []
        effective_root = work_root or self.work_root
        for provider in self.plugin_tool_providers:
            try:
                bundle = self._invoke_plugin_provider(provider, effective_root)
            except Exception:  # noqa: BLE001 — plugin tools must never break the toolbox
                continue
            specs.extend(list(getattr(bundle, "specs", []) or []))
        specs = [spec for spec in specs if self._plugin_spec_available(spec)]
        # Dynamic plugin tools carry their own permission on the
        # spec; register it so the approval gate treats them per declaration
        # instead of defaulting unknown names to HARD_BLOCK.
        for spec in specs:
            self.manifest_tool_permissions.setdefault(spec.name, spec.permission)  # type: ignore[assignment]
            if spec.permission == HARD_BLOCK:
                # Keep this union monotonic for the lifetime of the toolbox:
                # a later dynamic registration cannot downgrade a previously
                # hard-blocked tool.
                self.manifest_hard_block_tools.add(spec.name)
                self.tool_permissions[spec.name] = HARD_BLOCK
            elif spec.name not in self.tool_permissions:
                self.tool_permissions[spec.name] = spec.permission
            approval_gate = getattr(self, "approval_gate", None)
            if approval_gate is not None:
                approval_gate.manifest_tool_permissions.setdefault(spec.name, spec.permission)
                if spec.permission == HARD_BLOCK:
                    approval_gate.manifest_hard_block_tools.add(spec.name)
                    approval_gate.tool_permissions[spec.name] = HARD_BLOCK
                elif spec.name not in approval_gate.tool_permissions:
                    approval_gate.tool_permissions[spec.name] = spec.permission
        return specs

    def _plugin_spec_available(self, spec: ToolSpec) -> bool:
        """Apply the host lifecycle gate to a plugin contribution.

        Toolboxes can outlive a plugin enable/disable operation for one turn.
        The generic callback keeps those stale snapshots from advertising or
        executing a stopped plugin while leaving Core unaware of plugin names.
        """
        plugin_name = str(spec.metadata.get("plugin") or "").strip()
        if not plugin_name or self.plugin_availability is None:
            return True
        try:
            return bool(self.plugin_availability(plugin_name))
        except Exception:  # noqa: BLE001 — a broken lifecycle gate is closed
            return False

    def tool_specs(self) -> list[ToolSpec]:
        specs = [
            replace(spec, permission=self._effective_tool_permission(spec.name, HARD_BLOCK))
            for spec in self._specs
            if spec.name not in self.disabled_tools and self._plugin_spec_available(spec)
        ]
        plugin_specs = [
            replace(spec, permission=self._effective_tool_permission(spec.name, spec.permission))
            for spec in self._dynamic_plugin_specs()
            if spec.name not in self.disabled_tools and spec.name not in self.manifest_hard_block_tools
        ]
        return [*specs, *plugin_specs]

    def _effective_tool_permission(self, name: str, fallback: PermissionTier | str) -> str:
        if name in self.manifest_hard_block_tools:
            return HARD_BLOCK
        if name in self.manifest_tool_permissions:
            return self.manifest_tool_permissions[name]
        return self.tool_permissions.get(name, fallback)

    def _outside_access_allowed(self) -> bool:
        """Whether tools may touch paths outside ``work_root``.

        Always true: the product decision of 2026-09-27 is that no workspace
        boundary is enforced.  ``allow_access_outside_workdir`` and the
        one-shot approval grant stay readable for compatibility, but nothing
        narrows access any more.
        """
        return True

    def _refresh_runtime_permissions(self) -> None:
        """Apply the latest session permission state before each tool boundary."""
        if self.runtime_permissions_provider is None:
            return
        try:
            value = self.runtime_permissions_provider()
        except Exception:  # noqa: BLE001 - retain the last safe state on cache failure
            return
        if not isinstance(value, Mapping):
            return
        policy = value.get("approval_policy")
        if policy in {"require", "auto_approve"}:
            self.approval_policy = policy
            self.approval_gate.approval_policy = policy
        tier = value.get("active_tier")
        if tier in {"read_only", "limited_edit", "full_edit"}:
            self.active_tier = tier
            self.approval_gate.active_tier = tier
        raw_tier_tools = value.get("tier_tools")
        if isinstance(raw_tier_tools, Mapping):
            tier_tools = {
                str(name): {str(tool) for tool in tools}
                for name, tools in raw_tier_tools.items()
                if isinstance(tools, (set, frozenset, list, tuple))
            }
            self.tier_tools = tier_tools
            self.approval_gate.tier_tools = tier_tools
        outside = value.get("allow_access_outside_workdir")
        if isinstance(outside, bool):
            self.allow_access_outside_workdir = outside
            self.approval_gate.allow_access_outside_workdir = outside

    def model_tools(
        self,
        *,
        include_tools: set[str] | None = None,
        exclude_tools: set[str] | None = None,
        active_mode: str | None = None,
    ) -> list[dict[str, Any]]:
        self._refresh_runtime_permissions()
        effective_exclude = set(exclude_tools or set())
        if self.mcp_caller is None:
            # No MCP tools were loaded, so neither gateway can be used.
            effective_exclude.update({"mcp_activate", "mcp_tool"})
        # Apply loadtools active_mode filtering
        if active_mode and self.load_tools:
            allowed = self._mode_tool_set(active_mode)
            if allowed is not None:
                all_specs = self.tool_specs()
                all_names = {spec.name for spec in all_specs}
                # A plugin may contribute dynamic tools for its own mode.  The
                # mode/category match is generic; Core does not name a plugin.
                allowed = set(allowed) | self._plugin_mode_tool_names(active_mode, all_specs)
                # Build exclude set = all tool names NOT in allowed set
                effective_exclude |= (all_names - allowed)
        # Filter out MCP tools from non-activated servers
        # Activated servers have their full mcp__{server}__* tools exposed;
        # unactivated servers only expose the mcp_activate gateway tool.
        for spec in self.tool_specs():
            name = spec.name
            if not name.startswith("mcp__"):
                continue
            # name format: mcp__{server}__{tool_name}
            parts = name.split("__", 2)
            if len(parts) >= 2:
                server = parts[1]
                if server not in self.activated_mcp_servers:
                    effective_exclude.add(name)
        # Lazy exposure（惰性暴露，§4 共识）：visibility=on_load 的工具在
        # 对应 skill 加载前不进入模型可见列表（loaded_skill_roots 追踪
        # 同款语义；加载后全套生效）。只影响模型侧，执行时权限照常。
        for spec in self.tool_specs():
            if str(spec.metadata.get("visibility")) != "on_load":
                continue
            skill_name = str(spec.metadata.get("skill") or "")
            if skill_name not in self.loaded_skill_names:
                effective_exclude.add(spec.name)
        return core_model_tools(self.tool_specs(), include_tools=include_tools, exclude_tools=effective_exclude or None)

    def skill_index(self) -> str:
        try:
            return self.skill_registry.prompt_index(
                self.work_root, self.skill_state_store, active_mode=self.active_mode
            )
        except TypeError:
            # Backward-compatible seam for injected third-party registries.
            return self.skill_registry.prompt_index(self.work_root, self.skill_state_store)

    def _mode_block_reason(self, name: str) -> str | None:
        """Return the fixed mode-enforcement error when ``name`` is not allowed
        in the current active mode, or None when the call may proceed.

        Mirrors the advertisement filter in :meth:`model_tools`: an unknown
        mode or a full-access mode (empty whitelist) never blocks; the
        plugin modes additionally allow their dynamic plugin-contributed tools.
        """
        if not self.active_mode or not self.load_tools:
            return None
        allowed = self._mode_tool_set(self.active_mode)
        if allowed is None:
            return None
        allowed = set(allowed) | self._plugin_mode_tool_names(self.active_mode, self.tool_specs())
        if name in allowed:
            return None
        return (
            f"You are in the {self.active_mode} mode, you can't use {name}. "
            "Please make the plan prepared and ask user to switch mode."
        )

    def _mode_tool_set(self, active_mode: str) -> set[str] | None:
        if active_mode in self.plugin_mode_tool_sets:
            return set(self.plugin_mode_tool_sets[active_mode])
        return mode_tool_set(self.load_tools, active_mode)

    def _plugin_mode_tool_names(self, active_mode: str, specs: list[ToolSpec]) -> set[str]:
        configured = self.plugin_mode_tool_sets.get(active_mode)
        if configured is not None:
            plugin_id = active_mode.split(":", 1)[0]
            return set(configured) | {
                spec.name
                for spec in specs
                if spec.metadata.get("plugin_dynamic") is True
                and str(spec.metadata.get("plugin") or "") == plugin_id
            }
        return {
            spec.name
            for spec in specs
            if str(spec.metadata.get("plugin_mode") or spec.metadata.get("category") or "") == active_mode
        }

    def prepare_call(self, call: ToolCall) -> ToolCall:
        self._refresh_runtime_permissions()
        # Plugin handlers have no closure-injected workspace context (core
        # tools receive work_root/data_dir via factory closures); inject it
        # into call.metadata so plugin tools are first-class citizens.
        call.metadata.setdefault("work_root", str(self.work_root))
        call.metadata.setdefault("data_dir", str(self.data_dir))
        # Manifest hard blocks are independent of active mode and approval
        # preset.  Evaluate them before mode/capability filtering so the
        # strongest reason cannot be hidden by a weaker mode denial.
        if call.name in self.manifest_hard_block_tools or call.name in self.disabled_tools:
            decision = self.approval_gate.check(call.name, call.arguments if isinstance(call.arguments, dict) else {})
            approval = {
                "tier": decision.permission_tier,
                "reason": decision.reason,
                "blocked": True,
                "requires_approval": False,
            }
            return replace(
                call,
                requires_approval=False,
                metadata={**dict(call.metadata or {}), "approval": approval},
            )
        # Mode enforcement runs first: the toolset advertised to the model is
        # mode-filtered, and the same filter must hold at execution time — a
        # model with stale context (e.g. the mode changed between turns) must
        # not be able to run a tool the current mode forbids.
        mode_reason = self._mode_block_reason(call.name)
        if mode_reason:
            approval = {
                "tier": "blocked",
                "reason": mode_reason,
                "blocked": True,
                "requires_approval": False,
            }
            return replace(
                call,
                requires_approval=False,
                metadata={**dict(call.metadata or {}), "approval": approval},
            )
        # question is a user-interaction request, not a permission decision —
        # bypass ApprovalGate entirely; it always requires user input and is
        # never affected by approval_policy / active_tier.
        if call.name == "question":
            approval = {
                "tier": "ask_user",
                "reason": "Question requires user input",
                "blocked": False,
                "requires_approval": True,
            }
            return replace(
                call,
                requires_approval=True,
                metadata={**dict(call.metadata or {}), "approval": approval},
            )

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
            "outside_workdir": decision.outside_workdir,
        }
        requires_approval = bool(decision.requires_approval)
        # The automatic preset approves inside the session's capability.  The
        # ``outside_workdir`` dimension no longer carves anything out of that
        # capability (2026-09-27), so the preset settles every ask it covers.
        if self.approval_policy == "auto_approve" and not decision.blocked:
            if requires_approval:
                requires_approval = False
                approval["requires_approval"] = False
            # Keep an explicit audit marker for every decision made by the
            # automatic preset, including tools that were already auto-allow.
            approval["auto_approved"] = True
        metadata = {**dict(call.metadata or {}), "approval": approval}
        return replace(
            call,
            requires_approval=requires_approval,
            metadata=metadata,
        )

    def prepare_approved_call(self, call: ToolCall) -> ToolCall:
        """Re-check a call before executing an externally approved request.

        Approval continuations cannot simply execute the serialized call:
        plugin manifests, lifecycle state, mode, tier, and path arguments may
        have changed while the approval card was open.  Re-run the same
        preparation boundary against the live-refreshed toolbox, then suppress only
        the already-resolved user approval requirement.  A hard block remains
        a hard block.
        """
        prepared = self.prepare_call(call)
        approval = prepared.metadata.get("approval")
        if not isinstance(approval, dict) or approval.get("blocked"):
            return prepared
        approval = {
            **approval,
            "approved": True,
            "auto_approved": True,
            "requires_approval": False,
        }
        if approval.get("outside_workdir"):
            # The user consented to this specific out-of-workspace target:
            # release the handlers' fail-closed path check for this call only.
            approval[GRANT_METADATA_KEY] = True
        return replace(
            prepared,
            requires_approval=False,
            metadata={**dict(prepared.metadata or {}), "approval": approval},
        )

    async def execute(self, call: ToolCall, context: ToolContext | None = None) -> ToolResult:
        self._refresh_runtime_permissions()
        # Refresh dynamic declarations before any direct execution path.  This
        # keeps a newly registered manifest hard_block effective even when a
        # caller presents a serialized call without going through
        # ``prepare_call`` first.
        provider_root = self._call_work_root(call, self.work_root)
        self._dynamic_plugin_specs(work_root=provider_root)
        if call.name in self.manifest_hard_block_tools:
            return ToolResult(
                call_id=call.id,
                name=call.name,
                status="blocked",
                error=f"Tool '{call.name}' is hard-blocked by its manifest",
                metadata={
                    "approval": {
                        "tier": HARD_BLOCK,
                        "reason": f"Tool '{call.name}' is hard-blocked by its manifest",
                        "blocked": True,
                        "requires_approval": False,
                    }
                },
            )
        approval = call.metadata.get("approval") if isinstance(call.metadata, dict) else None
        if isinstance(approval, dict) and approval.get("blocked"):
            return ToolResult(
                call_id=call.id,
                name=call.name,
                status="blocked",
                error=str(approval.get("reason") or "Tool call blocked"),
                metadata={"approval": approval},
            )
        # The Kernel normally prepares model calls during parse_model_output,
        # but CoreToolbox is also a public low-level entry point used by
        # plugin/runtime callers.  When a runtime capability snapshot is
        # configured, an unprepared direct call must pass the same tier and
        # approval gate; otherwise an ``auto_allow`` plugin could bypass the
        # active capability boundary simply by calling execute() directly.
        if not isinstance(approval, dict) and self.active_tier is not None and self.tier_tools is not None:
            call = self.prepare_call(call)
            approval = call.metadata.get("approval") if isinstance(call.metadata, dict) else None
            if isinstance(approval, dict) and approval.get("blocked"):
                return ToolResult(
                    call_id=call.id,
                    name=call.name,
                    status="blocked",
                    error=str(approval.get("reason") or "Tool call blocked"),
                    metadata={"approval": approval},
                )
        # A prepared ask_user call is a waiting-gate contract, not permission
        # to execute.  Only prepare_approved_call() clears this flag for an
        # approval continuation.
        if call.requires_approval:
            return ToolResult(
                call_id=call.id,
                name=call.name,
                status="blocked",
                error="Tool requires approval and was not routed through a waiting request.",
                metadata={"approval": approval} if isinstance(approval, dict) else {},
            )
        if call.name in self.disabled_tools:
            return ToolResult(call_id=call.id, name=call.name, status="blocked", error=f"Tool disabled: {call.name}")
        static_spec = next((spec for spec in self._specs if spec.name == call.name), None)
        if static_spec is not None and not self._plugin_spec_available(static_spec):
            plugin_name = str(static_spec.metadata.get("plugin") or "plugin")
            return ToolResult(
                call_id=call.id,
                name=call.name,
                status="blocked",
                error=f"Plugin disabled: {plugin_name}",
            )
        handler = self._handlers.get(call.name)
        if handler is None and call.name in self._dynamic_mcp_tool_names:
            handler = self._handlers.get("mcp_tool")
        if handler is None:
            for provider in self.plugin_tool_providers:
                try:
                    bundle = self._invoke_plugin_provider(provider, provider_root)
                    handler = (getattr(bundle, "handlers", {}) or {}).get(call.name)
                except Exception:  # noqa: BLE001
                    handler = None
                if handler is not None:
                    break
        if handler is None:
            return ToolResult(call_id=call.id, name=call.name, status="blocked", error=f"Unknown tool: {call.name}")
        timeout = self._plugin_timeouts.get(call.name)
        granted = call_has_outside_grant(approval)
        if timeout is None:
            with outside_access_grant(granted):
                return await handler(call)
        # 插件工具可选执行超时（E2 共识：不声明 = 长任务不限）
        import asyncio

        try:
            with outside_access_grant(granted):
                return await asyncio.wait_for(handler(call), timeout=timeout)
        except asyncio.TimeoutError:
            return ToolResult(
                call_id=call.id,
                name=call.name,
                status="failed",
                error=f"Plugin tool timed out after {timeout}s",
                metadata={"error_type": "plugin_timeout", "timed_out": True},
            )

    def _build_handlers(
        self,
        *,
        command_timeout: int,
        max_list_items: int,
        max_text_length: int,
        max_search_results: int,
        core_event_callback: Callable[[CoreEvent], Awaitable[None]] | None,
        operation_executor: OperationExecutor | None,
        imagegen_config: dict | None = None,
        allow_access_outside_workdir: bool = False,
        plugin_tool_specs: list[ToolSpec] | None = None,
        plugin_manager_specs: list[ToolSpec] | None = None,
    ) -> dict[str, ToolHandler]:
        read_tools = WorkspaceReadOnlyTools(
            self.work_root,
            max_list_items=max_list_items,
            max_text_length=max_text_length,
            max_search_results=max_search_results,
            allow_access_outside_workdir=self._outside_access_allowed,
        )
        for root in self.loaded_skill_roots:
            read_tools.add_resource_root(root)
        command_handlers = CommandToolHandlers(
            work_root=self.work_root,
            command_timeout=command_timeout,
            loaded_skill_roots=self.loaded_skill_roots,
            core_event_callback=core_event_callback,
            allow_access_outside_workdir=self._outside_access_allowed,
        )

        async def call_mcp(call: ToolCall) -> ToolResult:
            return await execute_mcp_tool_call(call, caller=self.mcp_caller)

        async def activate_mcp(call: ToolCall) -> ToolResult:
            args = call.arguments if isinstance(call.arguments, dict) else {}
            server_name = str(args.get("server_name") or "").strip()
            if not server_name:
                return ToolResult(
                    call_id=call.id,
                    name=call.name,
                    status="failed",
                    error="Missing 'server_name' argument",
                )
            if self.mcp_caller is None:
                return ToolResult(
                    call_id=call.id,
                    name=call.name,
                    status="failed",
                    error="MCP tool caller not available",
                )
            if not hasattr(self.mcp_caller, "tool_summary"):
                return ToolResult(
                    call_id=call.id,
                    name=call.name,
                    status="failed",
                    error="MCP registry does not support tool summaries",
                )
            summary = self.mcp_caller.tool_summary(server_name)
            not_found = "not found" in summary.lower() and "available servers:" in summary.lower()
            return ToolResult(
                call_id=call.id,
                name=call.name,
                status="failed" if not_found else "ok",
                content=summary,
                error="" if not not_found else f"MCP server '{server_name}' not found",
                metadata={"activated_server": server_name} if not not_found else {},
            )

        async def load_skill(call: ToolCall) -> ToolResult:
            args = call.arguments if isinstance(call.arguments, dict) else {}
            name = args.get("name", "")
            if not isinstance(name, str) or not name.strip():
                return ToolResult(call_id=call.id, name=call.name, status="failed", error="Missing 'name' argument")

            # 缺口 #1：已禁用 skill 不加载（SkillStateStore 只在 skill.list
            # 显示层生效的时代结束——load_skill 直接查禁用状态）。
            if self.skill_state_store is not None and not self.skill_state_store.is_enabled(name):
                return ToolResult(
                    call_id=call.id,
                    name=call.name,
                    status="failed",
                    error=f'Skill "{name}" is disabled',
                    content=f'Skill "{name}" is disabled. Enable it in settings (skills) before loading.',
                )

            try:
                content = self.skill_registry.load_prompt_content(
                    self.work_root, name, active_mode=self.active_mode
                )
            except TypeError:
                content = self.skill_registry.load_prompt_content(self.work_root, name)
            found = not content.startswith(f'Skill "{name}" not found.')
            if found:
                try:
                    skill = self.skill_registry.get(self.work_root, name, active_mode=self.active_mode)
                except TypeError:
                    skill = self.skill_registry.get(self.work_root, name)
                if skill is not None:
                    base = skill.location.parent.resolve()
                    self.loaded_skill_roots.add(base)
                    # 惰性暴露的关联追踪：on_load 工具按 skill 名过滤
                    self.loaded_skill_names.add(name.strip())
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
            # Narrow injected runners are an internal compatibility seam used
            # by Workflow adapters/tests, not the model-facing main-agent path.
            if not hasattr(self.sub_agent_runner, "session_prefix"):
                return await _legacy_call_sub_agent(call)
            args = call.arguments if isinstance(call.arguments, dict) else {}
            # The model-facing lifecycle contract is intentionally strict.
            # Workflow internals still use KernelSubAgentRunner.run directly.
            required = {"action", "type", "name", "model", "reasoning_level"}
            if set(args) != required:
                return ToolResult(call_id=call.id, name=call.name, status="failed", error="sub_agent requires exactly action,type,name,model,reasoning_level")
            from lamtools_core.sub_agent_supervisor import get_sub_agent_supervisor
            call_metadata = call.metadata if isinstance(call.metadata, Mapping) else {}
            parent_thread_id = str(
                call_metadata.get("parent_session_id")
                or call_metadata.get("session_id")
                or getattr(self.sub_agent_runner, "session_prefix", "")
            )
            supervisor = await get_sub_agent_supervisor(
                parent_thread_id=parent_thread_id,
                runner=self.sub_agent_runner,
                data_dir=self.data_dir or (self.work_root / ".lam" / "core" / "data"),
            )
            try:
                common = {
                    "type": args["type"], "name": args["name"], "model": args["model"],
                    "reasoning_level": args["reasoning_level"],
                }
                if args["action"] == "create":
                    operation = await supervisor.create_operation(
                        **common,
                        source_ids={
                            "call_id": call.id,
                            "run_id": str(call_metadata.get("parent_run_id") or ""),
                            "turn_id": str(call_metadata.get("parent_turn_id") or ""),
                            "message_id": str(call_metadata.get("parent_message_id") or ""),
                            "part_id": str(call_metadata.get("parent_part_id") or ""),
                        },
                    )
                elif args["action"] == "close":
                    operation = await supervisor.close_operation(
                        **common,
                        source_ids={
                            "call_id": call.id,
                            "run_id": str(call_metadata.get("parent_run_id") or ""),
                            "turn_id": str(call_metadata.get("parent_turn_id") or ""),
                            "message_id": str(call_metadata.get("parent_message_id") or ""),
                            "part_id": str(call_metadata.get("parent_part_id") or ""),
                        },
                    )
                else:
                    raise ValueError("action must be exactly 'create' or 'close'")
            except ValueError as exc:
                return ToolResult(call_id=call.id, name=call.name, status="failed", error=str(exc))
            return ToolResult(
                call_id=call.id, name=call.name, status="ok",
                content=json.dumps(operation.to_dict(), ensure_ascii=False), metadata=operation.to_dict(),
            )

        async def call_sub_agent_message(call: ToolCall) -> ToolResult:
            if self.sub_agent_runner is None:
                return ToolResult(call_id=call.id, name=call.name, status="failed", error="Sub-agent runner not available")
            args = call.arguments if isinstance(call.arguments, dict) else {}
            if set(args) != {"type", "name", "prompt"}:
                return ToolResult(call_id=call.id, name=call.name, status="failed", error="sub_agent_message requires exactly type,name,prompt")
            from lamtools_core.sub_agent_supervisor import get_sub_agent_supervisor
            meta = call.metadata if isinstance(call.metadata, Mapping) else {}
            supervisor = await get_sub_agent_supervisor(
                parent_thread_id=str(meta.get("parent_session_id") or meta.get("session_id") or getattr(self.sub_agent_runner, "session_prefix", "")),
                runner=self.sub_agent_runner,
                data_dir=self.data_dir or (self.work_root / ".lam" / "core" / "data"),
            )
            try:
                payload = await supervisor.message(
                    type=args["type"],
                    name=args["name"],
                    prompt=args["prompt"],
                    source_ids={
                        "call_id": call.id,
                        "run_id": str(meta.get("parent_run_id") or ""),
                        "turn_id": str(meta.get("parent_turn_id") or ""),
                        "message_id": str(meta.get("parent_message_id") or ""),
                        "part_id": str(meta.get("parent_part_id") or ""),
                    },
                )
            except ValueError as exc:
                return ToolResult(call_id=call.id, name=call.name, status="failed", error=str(exc))
            return ToolResult(call_id=call.id, name=call.name, status="ok", content="accepted", metadata=payload)

        async def call_sub_agent_legacy_removed(call: ToolCall) -> ToolResult:
            # Kept only as a marker to make the old synchronous body below
            # unreachable without deleting its well-tested result formatting.
            return await call_sub_agent(call)

        async def _legacy_call_sub_agent(call: ToolCall) -> ToolResult:
            args = call.arguments if isinstance(call.arguments, dict) else {}
            task = str(args.get("task") or "").strip()
            if not task:
                return ToolResult(call_id=call.id, name=call.name, status="failed", error="sub_agent requires 'task'")
            agent = str(args.get("agent") or "").strip()
            # Treat "null"/"None"/"undefined" strings as empty (LLMs sometimes
            # emit these instead of JSON null for optional params).
            model = str(args.get("model") or "").strip()
            if model.lower() in ("null", "none", "undefined"):
                model = ""
            mode = str(args.get("mode") or "").strip()
            if mode.lower() in ("null", "none", "undefined"):
                mode = ""
            requested_reasoning_level = str(args.get("reasoning_level") or "").strip()
            requested_reasoning_effort = str(args.get("reasoning_effort") or "").strip()
            if requested_reasoning_level.lower() in ("null", "none", "undefined"):
                requested_reasoning_level = ""
            if requested_reasoning_effort.lower() in ("null", "none", "undefined"):
                requested_reasoning_effort = ""
            parent_reasoning_level = reasoning_level_from_legacy(
                reasoning_level=getattr(self.sub_agent_runner, "reasoning_level", ""),
                thinking_enabled=getattr(self.sub_agent_runner, "thinking_enabled", None),
                fallback="off",
            )
            explicit_reasoning = requested_reasoning_level or requested_reasoning_effort
            effective_reasoning_level = (
                normalize_reasoning_level(explicit_reasoning, parent_reasoning_level)
                if explicit_reasoning
                else parent_reasoning_level
            )
            raw_attachments = args.get("attachments")
            attachments = [str(a) for a in raw_attachments if isinstance(a, (str, int)) and str(a).strip()] if isinstance(raw_attachments, list) else []
            call_metadata = call.metadata if isinstance(call.metadata, Mapping) else {}
            execution_context = _workflow_context_from_metadata(call_metadata)
            if not attachments and isinstance(execution_context.get("attachments"), list):
                attachments = [str(item) for item in execution_context["attachments"]]
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
            run_kwargs: dict[str, Any] = {
                "task": task,
                "agent": agent,
                "model": model,
                "mode": mode,
                "attachments": attachments,
                "parent_call_id": call.id,
                "parent_run_id": str(call_metadata.get("parent_run_id") or ""),
                "parent_turn_id": str(call_metadata.get("parent_turn_id") or ""),
            }
            # Forward an explicit override only to runners that advertise the
            # canonical parameter.  Deliberately leaving an omitted override
            # out preserves inheritance for the production runner and keeps
            # narrow legacy/fake runners compatible.
            if explicit_reasoning:
                run_kwargs["reasoning_level"] = effective_reasoning_level
            if execution_context:
                run_kwargs["execution_context"] = execution_context
            # Existing hosts often provide a deliberately narrow fake/legacy
            # runner.  Forward the new context only when its signature opts in
            # (or accepts **kwargs), avoiding a compatibility break while the
            # production KernelSubAgentRunner receives the full envelope.
            try:
                parameters = inspect.signature(self.sub_agent_runner.run).parameters
            except (TypeError, ValueError):
                parameters = {}
            accepts_context = (
                not parameters
                or "execution_context" in parameters
                or any(item.kind == inspect.Parameter.VAR_KEYWORD for item in parameters.values())
            )
            if not accepts_context:
                run_kwargs.pop("execution_context", None)
            accepts_reasoning = (
                not parameters
                or "reasoning_level" in parameters
                or any(item.kind == inspect.Parameter.VAR_KEYWORD for item in parameters.values())
            )
            if not accepts_reasoning:
                run_kwargs.pop("reasoning_level", None)
            outcome = await self.sub_agent_runner.run(**run_kwargs)
            if isinstance(outcome, SubAgentRunResult):
                metadata = {
                    "agent": agent,
                    "model": model,
                    "mode": mode,
                    "reasoning_level": effective_reasoning_level,
                    "attachments": attachments,
                    "sub_session_id": outcome.session_id,
                    "sub_run_id": outcome.run_id,
                    "decision": outcome.decision,
                    "model_id": outcome.model_id,
                    "tool_call_count": outcome.tool_call_count,
                    "ended_with_final_response": outcome.ended_with_final_response,
                    "model_rounds": outcome.model_rounds,
                    "tool_call_breakdown": dict(outcome.tool_call_breakdown),
                    "death_scene": outcome.death_scene,
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
                            "model": model,
                            "mode": mode,
                            "reasoning_level": effective_reasoning_level,
                            "attachments": attachments,
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
                    # failure_message() already carries the death scene (last
                    # model round: reply + tools + statuses); append the summary
                    # counters so the parent agent sees the full picture.
                    content_lines = [f"SUB_AGENT FAILED: {error}"]
                    content_lines.append(f"model_rounds: {outcome.model_rounds}")
                    if outcome.tool_call_breakdown:
                        breakdown = ", ".join(
                            f"{name}={count}"
                            for name, count in sorted(outcome.tool_call_breakdown.items())
                        )
                        content_lines.append(f"tool_calls: {outcome.tool_call_count} ({breakdown})")
                    else:
                        content_lines.append(f"tool_calls: {outcome.tool_call_count}")
                    return ToolResult(
                        call_id=call.id,
                        name=call.name,
                        status="failed",
                        content="\n".join(content_lines),
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
                    "reasoning_level": effective_reasoning_level,
                },
            )

        handlers: dict[str, ToolHandler] = {
            **read_tools.as_dict(),
            "load_skill": load_skill,
            MEMORY_TOOL_NAME: make_memory_handler(self.work_root),
            LIBRARY_TOOL_NAME: make_library_handler(self.artifact_store, self.work_root),
            "write_file": make_write_file_handler(
                self.work_root,
                allow_access_outside_workdir=self._outside_access_allowed,
            ),
            "edit_file": make_edit_file_handler(
                self.work_root,
                allow_access_outside_workdir=self._outside_access_allowed,
            ),
            "run_command": command_handlers.run_command,
            "list_processes": command_handlers.list_processes,
            "kill_process": command_handlers.kill_process,
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
            "web_search": build_web_search_handler(str(self.work_root), data_dir=self.data_dir),
            "web_fetch": make_web_fetch_handler(str(self.work_root)),
            "generate_image": make_generate_image_handler(
                imagegen_config,
                str(self.work_root),
                artifact_registry=self.imagegen_config.get("artifact_registry") if isinstance(imagegen_config, dict) else None,
            ),
            "mcp_tool": call_mcp,
            "mcp_activate": activate_mcp,
            SUB_AGENT_TOOL_NAME: call_sub_agent,
            SUB_AGENT_MESSAGE_TOOL_NAME: call_sub_agent_message,
            "write_checklist": _write_checklist_handler,
            "update_checklist": _update_checklist_handler,
            "question": _question_handler,
        }
        if operation_executor is not None:
            handlers.update(durable_tool_handlers(operation_executor, work_root=self.work_root))
        # 插件原生工具 handler：动态导入 module:function（§3 定点 #4）。
        # 导入失败 = 该工具不可用（不注册，执行走 Unknown tool；错误记录
        # 供 plugin.list 报状态与诊断）。
        # 依赖缺失（§5：不静默降级）→ 注册占位 handler 返回明确错误附
        # 安装命令，让模型/用户知道怎么修，而不是 Unknown tool 黑盒。
        from lamtools_core.plugins.deps import check_dependencies, install_command_hint

        for spec in plugin_tool_specs or []:
            dependencies = [
                str(item)
                for item in (spec.metadata.get("dependencies") or [])
                if isinstance(item, str)
            ]
            if dependencies:
                dep_result = check_dependencies(dependencies)
                if dep_result["status"] != "ok":
                    missing = " ".join(dep_result["missing"])
                    hint = install_command_hint(dep_result["missing"])
                    error = (
                        f"plugin '{spec.metadata.get('plugin', '')}' is missing dependencies: "
                        f"{missing}. Install them with: {hint}"
                    )
                    self._plugin_handler_errors[spec.name] = error
                    handlers[spec.name] = _missing_dependency_handler(spec.name, error)
                    continue
            handler = (self.plugin_tool_handlers or {}).get(spec.name)
            if handler is None:
                handler = self._bundled_plugin_handler(
                spec,
                command_timeout=command_timeout,
                max_text_length=max_text_length,
                imagegen_config=imagegen_config,
                operation_executor=operation_executor,
                )
            if handler is None:
                handler = self._import_plugin_handler(spec)
            if handler is not None:
                handlers[spec.name] = handler
        # 模型可调插件管理工具（F2：skill 引导安装的调用通道）
        if plugin_manager_specs and operation_executor is not None:
            from lamtools_core.plugins.manager_tools import plugin_manager_tool_handlers

            handlers.update(
                plugin_manager_tool_handlers(operation_executor, work_root=self.work_root)
            )
        return handlers

    def _bundled_plugin_handler(
        self,
        spec: ToolSpec,
        *,
        command_timeout: int,
        max_text_length: int,
        imagegen_config: dict | None,
        operation_executor: OperationExecutor | None = None,
    ) -> ToolHandler | None:
        """内置插件工具（D2 共识）由 core 显式装配——handler 工厂留在
        core 包内，按工具名解析（不走通用动态导入，工厂需要 work_root/
        timeout 等装配参数）。未命中（第三方插件）返回 None 走动态导入。
        """
        name = spec.name
        if name == "git_status":
            return make_git_status_handler(
                self.work_root,
                command_timeout=command_timeout,
                run_subprocess=run_subprocess,
            )
        if name == "git_diff":
            return make_git_diff_handler(
                self.work_root,
                command_timeout=command_timeout,
                max_text_length=max_text_length,
                run_subprocess=run_subprocess,
            )
        if name == "web_search":
            return build_web_search_handler(
                str(self.work_root),
                data_dir=self.data_dir,
            )
        if name == "generate_image":
            return make_generate_image_handler(
                imagegen_config,
                str(self.work_root),
                artifact_registry=(
                    self.imagegen_config.get("artifact_registry")
                    if isinstance(self.imagegen_config, dict)
                    else None
                ),
            )
        return None

    def _import_plugin_handler(self, spec: ToolSpec) -> ToolHandler | None:
        import importlib

        entry = str(spec.metadata.get("handler") or "")
        if ":" not in entry:
            self._plugin_handler_errors[spec.name] = f"invalid handler entry (expected module:function): {entry!r}"
            return None
        module_name, func_name = entry.split(":", 1)
        try:
            module = importlib.import_module(module_name)
            func = getattr(module, func_name)
        except Exception as exc:  # noqa: BLE001 — plugin code must never break the toolbox
            self._plugin_handler_errors[spec.name] = f"{type(exc).__name__}: {exc}"
            _logger.warning(
                "[plugins:handler] import failed for %s: %s", spec.name, exc, exc_info=True
            )
            return None
        if not callable(func):
            self._plugin_handler_errors[spec.name] = f"handler '{func_name}' is not callable"
            return None
        return func


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
