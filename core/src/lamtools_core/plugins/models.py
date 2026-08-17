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
    manifest_version: str = "1"
    root: Path = Path()
    enabled: bool = True
    skill_roots: list[Path] = field(default_factory=list)
    hook_files: list[Path] = field(default_factory=list)
    mcp_files: list[Path] = field(default_factory=list)
    # ── 原生工具 / 依赖 / 配置（插件系统改造新增）──────────────
    tool_files: list[Path] = field(default_factory=list)
    operation_files: list[Path] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    config_schema: Path | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PluginToolSpec:
    """tools.jsonc 中的单个工具声明（manifest 原生工具通道）。

    permission 缺省 ``ask_user``（安全默认，与 ApprovalGate 未知工具
    默认 HARD_BLOCK 的保守语义对齐）；visibility=on_load 时 ``skill``
    指明该工具随哪个 skill 加载暴露。
    """

    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    permission: str = "ask_user"  # auto_allow | ask_user | hard_block
    category: str = "plugin"
    visibility: str = "always"  # always | on_load
    skill: str = ""
    handler: str = ""  # module:function 动态导入入口
    timeout: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PluginOperationSpec:
    """operations.jsonc 中的单个 operation 声明（RPC 面，G 组增量）。

    operation 由 UI/CLI 直接发起（不经 kernel/toolbox）——调用者即用户
    或开发工具，不参与 ApprovalGate 审批链；permission 缺省
    ``auto_allow``，``hard_block`` 拒绝注册（plugin.list 报状态）。
    handler 为 ``module:function`` 动态导入入口，契约：
    ``async def handler(request, *, work_root, data_dir) -> OperationResult``。
    """

    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    permission: str = "auto_allow"  # auto_allow | ask_user | hard_block
    handler: str = ""  # module:function 动态导入入口
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