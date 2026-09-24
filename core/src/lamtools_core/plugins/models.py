from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


HookSource = Literal["user", "project", "plugin", "managed"]
HookHandlerType = Literal["command", "http", "mcp", "prompt"]
HookDecisionKind = Literal["allow", "block"]


@dataclass(frozen=True)
class PluginUIView:
    """A plugin-contributed UI view declared in ``plugin.json``."""

    id: str
    title: str
    entry: Path
    icon: str = ""


@dataclass(frozen=True)
class PluginUIMode:
    """A plugin-contributed top-level application mode."""

    id: str
    title: str
    entry: Path
    icon: str = ""
    tools: list[str] = field(default_factory=list)
    # None means the manifest makes no claim and the host keeps every surface;
    # an empty list claims the mode supports none of them.
    capabilities: list[str] | None = None


@dataclass(frozen=True)
class PluginWidgetAction:
    """One host-rendered action exposed by a sidebar widget."""

    id: str
    title: str
    operation: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    dangerous: bool = False
    mutates: bool = False


@dataclass(frozen=True)
class PluginSidebarWidget:
    """A right-sidebar contribution declared by a plugin manifest.

    Blocks are untrusted data rendered by Core.  Component entries are code
    from an already-trusted plugin installation, but the path is still
    resolved and confined to the plugin root during manifest discovery.
    """

    id: str
    title: str
    renderer: Literal["blocks", "component"]
    scope: Literal["global", "workspace", "session"]
    icon: str = ""
    order: int = 0
    snapshot_operation: str = ""
    entry: Path | None = None
    actions: list[PluginWidgetAction] = field(default_factory=list)


@dataclass(frozen=True)
class PluginUIContribution:
    """Manifest-declared UI contributions.

    ``entry`` is resolved inside the plugin root by :class:`PluginRegistry`.
    The first UI runtime only consumes bundled entries; keeping the same
    manifest shape for installed plugins lets the protocol grow without a
    second plugin-specific channel.
    """

    views: list[PluginUIView] = field(default_factory=list)
    modes: list[PluginUIMode] = field(default_factory=list)
    sidebar_widgets: list[PluginSidebarWidget] = field(default_factory=list)


@dataclass(frozen=True)
class PluginComposerCommand:
    """A data-only slash command contributed by an enabled plugin."""

    name: str
    title: str
    description: str = ""
    icon: str = "puzzle"
    kind: str = "action"
    action: str = "run_action"
    accepts_args: bool = False
    operation: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    effect: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PluginCLIArgument:
    """One argparse-compatible argument declared by a plugin command.

    ``flags`` contains either one positional name (``["name"]``) or one or
    more option strings (for example ``["--name", "-n"]``).  Keeping the
    declaration data-only means Core can mount commands without importing a
    plugin-specific parser or handler until that command is actually
    registered.
    """

    flags: tuple[str, ...]
    dest: str = ""
    action: str = "store"
    type: str = "str"
    default: Any = None
    required: bool = False
    nargs: str | int | None = None
    choices: tuple[str, ...] = field(default_factory=tuple)
    metavar: str = ""
    help: str = ""
    const: Any = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PluginCLICommand:
    """A plugin CLI command or command group declared in ``plugin.json``."""

    name: str
    help: str = ""
    handler: str = ""
    aliases: tuple[str, ...] = field(default_factory=tuple)
    arguments: list[PluginCLIArgument] = field(default_factory=list)
    commands: list["PluginCLICommand"] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PluginCLIContribution:
    """Manifest-declared CLI command groups contributed by a plugin."""

    commands: list[PluginCLICommand] = field(default_factory=list)

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
    builtin: bool = False
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
    # Optional self-contained desktop UI. The entry stays inside the plugin
    # root and is served by the Core loopback HTTP app; Tauri only hosts the
    # resulting window and never imports plugin code into the main UI bundle.
    desktop_entry: Path | None = None
    desktop_title: str = ""
    desktop_window: dict[str, Any] = field(default_factory=dict)
    desktop_card_width: int = 376
    desktop_card_height: int = 360
    desktop_file_drop: bool = False
    ui: PluginUIContribution | None = None
    cli: PluginCLIContribution | None = None
    commands: list[PluginComposerCommand] = field(default_factory=list)
    backend_entry: Path | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    # Stable manifest identity. Older manifests used ``name`` as their
    # identity, so discovery falls back to that value when ``id`` is omitted.
    # Keep extension fields at the end to preserve positional construction of
    # the pre-id manifest model for third-party integrations.
    id: str = ""
    # Optional mode scopes keyed by declared skill root. Kept at the end so
    # older positional manifest construction remains stable.
    skill_modes: dict[Path, tuple[str, ...]] = field(default_factory=dict)


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
