from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


HookSource = Literal["user", "project", "plugin", "managed"]
HookHandlerType = Literal["command", "http", "mcp", "prompt"]
HookDecisionKind = Literal["allow", "block"]

# ── canonical hook event names ──────────────────────────────
HOOK_EVENT_PRE_TOOL_USE = "PreToolUse"
HOOK_EVENT_POST_TOOL_USE = "PostToolUse"
HOOK_EVENT_POST_TOOL_USE_FAILURE = "PostToolUseFailure"
HOOK_EVENT_SESSION_START = "SessionStart"
HOOK_EVENT_SESSION_STOP = "Stop"
HOOK_EVENT_USER_PROMPT_SUBMIT = "UserPromptSubmit"
HOOK_EVENT_PERMISSION_REQUEST = "PermissionRequest"

_ALL_HOOK_EVENTS = (
    HOOK_EVENT_SESSION_START,
    HOOK_EVENT_USER_PROMPT_SUBMIT,
    HOOK_EVENT_PRE_TOOL_USE,
    HOOK_EVENT_PERMISSION_REQUEST,
    HOOK_EVENT_POST_TOOL_USE,
    HOOK_EVENT_POST_TOOL_USE_FAILURE,
    HOOK_EVENT_SESSION_STOP,
)


@dataclass(frozen=True)
class PluginManifest:
    name: str
    version: str
    description: str = ""
    root: Path = Path()
    enabled: bool = True
    skill_roots: list[Path] = field(default_factory=list)
    hook_files: list[Path] = field(default_factory=list)
    mcp_files: list[Path] = field(default_factory=list)
    permissions: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PluginResource:
    plugin_name: str
    kind: str
    path: Path


@dataclass(frozen=True)
class HookHandler:
    type: HookHandlerType
    command: str = ""
    url: str = ""
    tool: str = ""
    prompt: str = ""
    timeout: float = 10.0
    required: bool = False
    status_message: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HookDefinition:
    id: str
    event: str
    matcher: str
    source: HookSource
    source_name: str
    config_path: Path
    plugin_name: str = ""
    plugin_root: Path | None = None
    handler: HookHandler = field(default_factory=lambda: HookHandler(type="command"))
    definition_hash: str = ""
    trusted: bool = False
    status: str = "pending_review"


@dataclass(frozen=True)
class HookEvent:
    event_name: str
    session_id: str = ""
    run_id: str = ""
    turn_id: str = ""
    cwd: str = ""
    project_root: str = ""
    plugin_name: str = ""
    plugin_root: str = ""
    plugin_data: str = ""
    transcript_path: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    tool_name: str = ""
    tool_input: dict[str, Any] = field(default_factory=dict)
    # ── PostToolUse / PostToolUseFailure ─────────────────────
    tool_call_id: str = ""
    tool_result: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    error_type: str = ""
    # ── UserPromptSubmit ─────────────────────────────────────
    user_message: str = ""
    # ── PermissionRequest ────────────────────────────────────
    permission_request: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HookDecision:
    decision: HookDecisionKind = "allow"
    reason: str = ""
    additional_context: str = ""
    updated_input: dict[str, Any] | None = None
    permission_decision: str = ""
    permission_decision_reason: str = ""
    audit_events: list[dict[str, Any]] = field(default_factory=list)
    # ── PostToolUse 输出改写 ─────────────────────────────────
    updated_output: dict[str, Any] | None = None
    # ── 用户可见的状态消息 ──────────────────────────────────
    status_message: str = ""