from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


HookSource = Literal["user", "project", "plugin", "managed"]
HookHandlerType = Literal["command", "http", "mcp", "prompt"]
HookDecisionKind = Literal["allow", "block"]

# ── 平台分类（2026-09-28 用户共识：插件与技能共用同一套词）──────────────
#
# 一个插件或技能声明它属于哪一类，宿主只提供本机适用 + 通用的部分：
#
#   desktop    桌面专属：手机没有对应能力（git 可执行文件、办公命令行、桌宠窗口）
#   mobile     移动专属：桌面没有对应能力
#   universal  通用（未声明即通用）：两端都提供
#
# 未声明默认通用，因此新增字段不影响既有插件；取值非法按清单错误报出，写了
# 错别字不会被当成"没声明"悄悄放行。
PlatformClass = Literal["desktop", "mobile", "universal"]
PLATFORM_DESKTOP = "desktop"
PLATFORM_MOBILE = "mobile"
PLATFORM_UNIVERSAL = "universal"
PLATFORM_CLASSES: tuple[str, ...] = (PLATFORM_DESKTOP, PLATFORM_MOBILE, PLATFORM_UNIVERSAL)
MANIFEST_PLATFORMS_KEY = "platforms"
#: 本 Python Core 永远扮演的宿主。移动端的插件目录不在这里：手机没有插件
#: 加载器，移动宿主由 Rust 侧的运行时按同一个分类词决定（见 runtime-rs）。
CORE_HOST_PLATFORM: str = PLATFORM_DESKTOP


def parse_platform_class(raw: dict[str, Any], *, source: str) -> str:
    """清单里的平台分类；缺省通用，取值非法即报错。

    ``source`` 只用于错误消息（清单路径或安装来源），校验语两处一致，安装与
    发现不会各判一套。
    """
    value = raw.get(MANIFEST_PLATFORMS_KEY)
    if value is None:
        return PLATFORM_UNIVERSAL
    if not isinstance(value, str):
        raise ValueError(
            f"plugin platforms must be one of {', '.join(PLATFORM_CLASSES)}: {source}"
        )
    platforms = value.strip()
    if platforms not in PLATFORM_CLASSES:
        raise ValueError(
            f"unsupported platforms '{platforms}' "
            f"(supported: {', '.join(PLATFORM_CLASSES)}): {source}"
        )
    return platforms


def platform_supports_host(platforms: str, host: str) -> bool:
    """该分类是否属于 ``host`` 这台宿主。"""
    return platforms == PLATFORM_UNIVERSAL or platforms == host


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
    # 声明本模式独占 tools 里属于本插件自己的那些工具：只有该模式激活时，
    # 这些工具才会出现在模型的工具集里，也不可被其他模式执行
    # （generic 工具如 read_file 不受影响）。默认 False = 工具在各模式下通用。
    exclusive_tools: bool = False
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
    # Platform class the manifest declares (see ``PlatformClass``); absent
    # means universal. Kept at the end with the other extension fields.
    platforms: str = PLATFORM_UNIVERSAL


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
