"""Writer tool specifications as a Core base plus Writer overlay.

Core owns generic Agent tool contracts. Writer keeps only product-specific
tool additions and compatibility helpers for existing Writer callers.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from lamtools_core.agent import SUB_AGENT_TOOL_NAME
from lamtools_core.tool import ToolSpec
from lamtools_core.tool.default_toolbox import (
    DEFAULT_OUTPUT_SCHEMA,
    DEFAULT_TOOL_CATEGORIES,
    DEFAULT_TOOL_ORDER,
    default_core_tool_specs,
    strict_tool_schema,
)
from lamtools_core.tool.permission import AUTO_ALLOW, PermissionTier


WRITER_TOOL_CATEGORIES: dict[str, str] = {
    "inspect_project": "file_read",
    "request_commit_review": "control",
    "write_checklist": "control",
    "update_checklist": "control",
    "verify_design": "control",
}

TOOL_CATEGORY_BY_NAME: dict[str, str] = {
    **DEFAULT_TOOL_CATEGORIES,
    **WRITER_TOOL_CATEGORIES,
}

MODEL_VISIBLE_CATEGORIES = frozenset({
    "file_read",
    "file_write",
    "command",
    "git",
    "web",
    "browser",
    "memory",
    "skill",
    "agent",
    "control",
})

INTERNAL_ONLY_TOOLS = frozenset({
    "mcp_tool",
})

MODEL_TOOL_ORDER: tuple[str, ...] = (
    "read_file",
    "document_normalize",
    "write_file",
    "edit_file",
    "search_content",
    "search_files",
    "load_skill",
    "web_search",
    "run_command",
    "git_status",
    "git_diff",
    "list_dir",
    "web_fetch",
    "run_tests",
    "inspect_project",
    "browser_check",
    "request_commit_review",
    "write_checklist",
    "update_checklist",
    "verify_design",
    SUB_AGENT_TOOL_NAME,
)


def _schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": required or [],
    }


def _default_display(category: str) -> dict[str, Any]:
    card_by_category = {
        "file_read": "file",
        "file_write": "diff",
        "command": "command",
        "git": "diff",
        "web": "web",
        "browser": "browser",
        "memory": "memory",
        "skill": "skill",
        "agent": "agent",
        "mcp": "tool",
        "control": "process",
    }
    return {
        "card": card_by_category.get(category, "tool"),
        "default_collapsed": category in {"control", "memory", "skill"},
    }


WRITER_OVERLAY_TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "inspect_project",
        "description": "Inspect project structure and stack.",
        "input_schema": _schema(
            {
                "path": {"type": "string", "description": "Project path"},
                "max_files": {"type": "integer", "description": "Max files to inspect"},
            }
        ),
        "permission": AUTO_ALLOW,
    },
    {
        "name": "request_commit_review",
        "description": "Ask the user to review the current completed work before creating a formal commit.",
        "input_schema": _schema(
            {
                "title": {"type": "string", "description": "Short user-facing review title"},
                "summary": {"type": "string", "description": "Brief business-language summary"},
                "how_to_review": {"type": "string", "description": "Short practical review instruction"},
                "self_check": {"type": "string", "description": "What Writer already checked"},
                "commit_message": {"type": "string", "description": "Suggested commit message"},
            },
            ["title", "summary", "how_to_review"],
        ),
        "permission": AUTO_ALLOW,
        "failure_modes": [{"type": "missing_review_summary", "message": "Review request needs a clear summary"}],
        "recovery": "State what changed and how the user can verify it",
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
        "permission": AUTO_ALLOW,
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
        "permission": AUTO_ALLOW,
    },
    {
        "name": "verify_design",
        "description": "Verify design constraints.",
        "input_schema": _schema({}),
        "permission": AUTO_ALLOW,
    },
]


def _from_core_spec(spec: ToolSpec) -> dict[str, Any]:
    metadata = deepcopy(spec.metadata)
    category = str(metadata.get("category") or TOOL_CATEGORY_BY_NAME.get(spec.name) or "tool")
    return {
        "name": spec.name,
        "description": spec.description,
        "input_schema": deepcopy(spec.input_schema),
        "permission": spec.permission,
        "failure_modes": deepcopy(metadata.get("failure_modes", [])),
        "recovery": str(metadata.get("recovery", "")),
        "category": category,
        "internal_only": spec.name in INTERNAL_ONLY_TOOLS,
        "output_schema": deepcopy(spec.output_schema),
        "display": deepcopy(metadata.get("display") or _default_display(category)),
    }


def _from_writer_overlay(spec: dict[str, Any]) -> dict[str, Any]:
    name = str(spec["name"])
    category = TOOL_CATEGORY_BY_NAME.get(name)
    if category is None:
        raise RuntimeError(f"Writer tool spec missing category: {name}")
    return {
        "name": name,
        "description": str(spec["description"]),
        "input_schema": strict_tool_schema(spec["input_schema"]),
        "permission": spec["permission"],
        "failure_modes": deepcopy(spec.get("failure_modes", [])),
        "recovery": str(spec.get("recovery", "")),
        "category": category,
        "internal_only": name in INTERNAL_ONLY_TOOLS,
        "output_schema": deepcopy(spec.get("output_schema", DEFAULT_OUTPUT_SCHEMA)),
        "display": deepcopy(spec.get("display", _default_display(category))),
    }


def _build_writer_tool_specs() -> list[dict[str, Any]]:
    core_specs = {_spec.name: _from_core_spec(_spec) for _spec in default_core_tool_specs()}
    overlay_specs = {str(_spec["name"]): _from_writer_overlay(_spec) for _spec in WRITER_OVERLAY_TOOL_SPECS}
    all_specs = {**core_specs, **overlay_specs}
    ordered_names = [
        *MODEL_TOOL_ORDER,
        "mcp_tool",
    ]
    seen: set[str] = set()
    ordered: list[dict[str, Any]] = []
    for name in [*ordered_names, *DEFAULT_TOOL_ORDER, *overlay_specs.keys()]:
        if name in seen:
            continue
        spec = all_specs.get(name)
        if spec is None:
            continue
        seen.add(name)
        ordered.append(spec)
    return ordered


WRITER_TOOL_SPECS: list[dict[str, Any]] = _build_writer_tool_specs()

WRITER_TOOL_PERMISSIONS: dict[str, PermissionTier] = {
    spec["name"]: spec["permission"]
    for spec in WRITER_TOOL_SPECS
}


def writer_model_tools() -> list[dict[str, Any]]:
    """Generate OpenAI-compatible function tools from Writer tool specs."""
    specs_by_name = {str(spec["name"]): spec for spec in WRITER_TOOL_SPECS}
    tools: list[dict[str, Any]] = []

    for name in MODEL_TOOL_ORDER:
        spec = specs_by_name.get(name)
        if not spec:
            continue
        if spec.get("internal_only"):
            continue
        if spec.get("category") not in MODEL_VISIBLE_CATEGORIES:
            continue
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": str(spec["description"]),
                    "strict": True,
                    "parameters": deepcopy(spec["input_schema"]),
                },
            }
        )

    return tools


WRITER_TOOLS: list[dict[str, Any]] = writer_model_tools()


def writer_tool_spec(name: str) -> dict[str, Any] | None:
    """Look up a tool spec by name. Returns None if not found."""
    for spec in WRITER_TOOL_SPECS:
        if spec["name"] == name:
            return spec
    return None


__all__ = [
    "DEFAULT_OUTPUT_SCHEMA",
    "INTERNAL_ONLY_TOOLS",
    "MODEL_VISIBLE_CATEGORIES",
    "TOOL_CATEGORY_BY_NAME",
    "WRITER_OVERLAY_TOOL_SPECS",
    "WRITER_TOOLS",
    "WRITER_TOOL_SPECS",
    "WRITER_TOOL_PERMISSIONS",
    "writer_model_tools",
    "writer_tool_spec",
]
